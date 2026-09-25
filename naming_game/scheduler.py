"""Scheduler and run loop (SPEC §5.4). The only component that sees the whole
population; it never serializes that view into a prompt.

Randomness: every draw comes from a generator derived from
SeedSequence(seed, spawn_key=(stream, round[, agent])). Draws therefore do not
depend on call order, async completion order, or whether a run was resumed.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from . import metrics
from .agents import Agent, choose_rule
from .config import ExperimentConfig
from .labels import get_labels, guard_prompt, label_set_hash
from .llm import FatalModelError, RetryableError, call_seed, extract_label_text, make_model, model_notes
from .parser import parse_label
from .prompts import build_agent_prompt, template_hashes
from .store import ROOT, RunStore

STREAMS = {"pairing": 1, "order": 2, "minority": 3, "tiebreak": 4, "policy": 5, "replay": 6}


def rng_for(seed: int, stream: str, *keys: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence(entropy=seed, spawn_key=(STREAMS[stream], *keys)))


class LeakageError(RuntimeError):
    pass


class RunCancelled(RuntimeError):
    pass


class ModelDrift(RuntimeError):
    pass


@dataclass
class Dyad:
    dyad_id: int
    members: tuple  # Agent objects (1 for isolated, 2 otherwise)
    within_block: Optional[bool] = None


# ------------------------------------------------------------- pairing -----
def block_of(config: ExperimentConfig, idx: int) -> Optional[int]:
    if config.pairing != "community":
        return None
    splits = np.array_split(np.arange(config.n_agents), config.topology_params.n_blocks)
    for b, members in enumerate(splits):
        if idx in members:
            return b
    return None


def pair_round(config: ExperimentConfig, round_idx: int) -> list[tuple]:
    """Return a list of index tuples for this round (pairs, or singletons)."""
    n = config.n_agents
    rng = rng_for(config.seed, "pairing", round_idx)
    if config.pairing == "isolated":
        return [(i,) for i in range(n)]
    if config.pairing == "random_dyad":
        perm = rng.permutation(n)
        return [tuple(sorted((int(perm[2 * k]), int(perm[2 * k + 1])))) for k in range(n // 2)]
    if config.pairing == "star":
        hub = config.agent_ids.index(config.topology_params.hub_id)
        leaves = [i for i in range(n) if i != hub]
        leaf = leaves[rng.integers(len(leaves))]
        return [tuple(sorted((hub, leaf)))]
    if config.pairing == "community":
        nb = config.topology_params.n_blocks
        blocks = [list(map(int, b)) for b in np.array_split(np.arange(n), nb)]
        blk = {i: b for b, members in enumerate(blocks) for i in members}
        unmatched = set(range(n))
        pairs = []
        while unmatched:
            i = min(unmatched)
            unmatched.discard(i)
            own = blk[i]
            if rng.random() < config.topology_params.p_within:
                target = own
            else:
                others = [b for b in range(nb) if b != own]
                target = others[rng.integers(len(others))]
            cands = sorted(j for j in unmatched if blk[j] == target)
            if not cands:
                cands = sorted(unmatched)
            j = cands[rng.integers(len(cands))]
            unmatched.discard(j)
            pairs.append(tuple(sorted((i, j))))
        return pairs
    raise ValueError(config.pairing)


# ------------------------------------------------------------- commit ------
def commit_dyad(dyad: Dyad, choices: dict, config: ExperimentConfig, round_idx: int,
                shown: dict | None = None) -> dict:
    """The ONLY memory writer. Appends one record to each participant's own
    buffer (if memory is on) and updates their own points (if reward is on).
    Touches nothing else. Returns {agent_id: points or None}.

    `shown` maps agent_id -> the partner label that agent is shown. By default
    it is the partner's real choice; with partner_source = prior_replay it is
    a label drawn from the prior, and match/points are computed against it."""
    a, b = dyad.members
    ca, cb = choices[a.agent_id], choices[b.agent_id]
    shown = shown or {a.agent_id: cb, b.agent_id: ca}
    out = {}
    for me, other, mine in ((a, b, ca), (b, a, cb)):
        theirs = shown[me.agent_id]
        points = None
        if config.reward_mode == "local_match":
            points = config.payoff.match if mine == theirs else config.payoff.mismatch
        if config.memory_on:
            me.buffer.append({"round": round_idx, "stimulus_id": "s0", "self_label": mine,
                              "partner_label": theirs, "partner_id": other.agent_id, "points": points})
        if points is not None:
            me.cum_points += points
        out[me.agent_id] = points
    return out


def replayed_labels(config: ExperimentConfig, labels, p0, round_idx: int, agent_indices) -> dict:
    """Prior replay: one label per agent drawn from p0, independent of every
    other agent's choice (SPEC v2 §3.3a)."""
    out = {}
    for idx in agent_indices:
        rng = rng_for(config.seed, "replay", round_idx, idx)
        out[idx] = labels[rng.choice(len(labels), p=p0)]
    return out


# ------------------------------------------------------------- run --------
def _git_commit() -> Optional[str]:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except Exception:
        return None


def _versions() -> dict:
    import importlib.metadata as md
    out = {"python": platform.python_version()}
    for pkg in ("numpy", "pydantic", "anthropic", "openai", "scipy"):
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            pass
    return out


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Simulation:
    def __init__(self, config: ExperimentConfig, store: Optional[RunStore] = None, model=None,
                 progress: Optional[Callable[[dict], None]] = None,
                 cancel_event: Optional[asyncio.Event] = None,
                 render_prompts: bool = True):
        self.config = config
        self.store = store
        self.labels = get_labels(config.label_set_id)
        self.K = len(self.labels)
        self.p0 = list(config.p0) if config.p0 else [1.0 / self.K] * self.K
        self.progress = progress
        self.cancel_event = cancel_event
        # Rule-only runs without a store may skip prompt rendering (null
        # models). Randomness is per-stream per-round, so this changes nothing
        # else about the run.
        self.render_prompts = render_prompts or store is not None or config.policy_default == "llm"
        self.model = model
        if config.policy_default == "llm" and self.model is None:
            self.model = make_model(config.model)
        cap = config.H if config.memory_on else 0
        self.agents = [Agent(aid, config.policy_default, cap) for aid in config.agent_ids]
        self.index = {a.agent_id: i for i, a in enumerate(self.agents)}
        # analyst-side state (never shown to agents)
        self.state: dict[str, str] = {}
        self.participations = [0] * config.n_agents
        self.round_choice_history: list[list[str]] = []
        self.tracker = metrics.ConsensusTracker(config.consensus_window)
        self.minority_active = False
        self.minority_released = False
        self.minority_ids: set = set()
        self.pinned_version = None
        if config.model is not None and config.model.pin_version not in (None, "auto"):
            self.pinned_version = config.model.pin_version
        self.prompts_checked = 0
        self.guard_hits: list = []
        self.model_versions: set = set()
        self.effective: dict = {}
        self.round_rows: list[dict] = []  # population rows (kept in memory for summaries)

    # ---- minority -------------------------------------------------------
    def _maybe_activate_minority(self, t: int) -> list[dict]:
        cm = self.config.committed_minority
        if cm is None:
            return []
        if self.minority_active and cm.end_round is not None and t >= cm.end_round and not self.minority_released:
            self._release_minority()
            return [{"round": t, "event": "minority_released", "agent_ids": sorted(self.minority_ids)}]
        if self.minority_active or self.minority_released:
            return []
        due = (t >= cm.start_round) if cm.start_rule == "round" else (self.tracker.reached or t >= cm.start_round)
        if not due:
            return []
        rng = rng_for(self.config.seed, "minority", t)
        k = int(round(cm.frac * self.config.n_agents))
        if cm.label_rule == "least_used_20":
            recent = [c for rnd in self.round_choice_history[-20:] for c in rnd if c]
            counts = {lab: recent.count(lab) for lab in self.labels}
            low = min(counts.values())
            cands = [lab for lab in self.labels if counts[lab] == low]
        else:  # random_nonmodal
            modal = metrics.modal(list(self.state.values()), f"{self.config.seed}|{t}|minority")[0]
            cands = [lab for lab in self.labels if lab != modal]
        label = cands[rng.integers(len(cands))]
        chosen = sorted(int(i) for i in rng.choice(self.config.n_agents, size=k, replace=False))
        self._apply_minority([self.agents[i].agent_id for i in chosen], label)
        return [{"round": t, "event": "minority_activated", "agent_ids": sorted(self.minority_ids),
                 "label": label, "reason": "consensus" if self.tracker.reached else "start_round"}]

    def _release_minority(self):
        for aid in self.minority_ids:
            ag = self.agents[self.index[aid]]
            ag.policy, ag.fixed_label, ag.is_minority = self.config.policy_default, None, False
        self.minority_released = True

    def _apply_minority(self, agent_ids, label):
        for aid in agent_ids:
            ag = self.agents[self.index[aid]]
            ag.policy, ag.fixed_label, ag.is_minority = "scripted_fixed", label, True
        self.minority_ids = set(agent_ids)
        self.minority_active = True

    # ---- model calls -----------------------------------------------------
    async def _call(self, sem, prompt: str, t: int, agent_idx: int, attempt: int, labels_shown=None):
        cfg = self.config
        for k in range(cfg.retry.api_retries + 1):
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise RunCancelled()
            try:
                async with sem:
                    return await asyncio.to_thread(self._complete, prompt, call_seed(cfg.seed, t, agent_idx, attempt), labels_shown)
            except RetryableError:
                if k == cfg.retry.api_retries:
                    raise
                await asyncio.sleep(cfg.retry.backoff_s * (2 ** k))
        raise AssertionError("unreachable")

    def _complete(self, prompt, seed, labels_shown):
        try:
            return self.model.complete(prompt, seed, labels_shown=labels_shown)
        except TypeError as ex:  # models written without the labels_shown argument (tests, plug-ins)
            if "labels_shown" not in str(ex):
                raise
            return self.model.complete(prompt, seed)

    async def _llm_choice(self, sem, prompt, t, agent_idx, agent_id, labels_shown=None):
        calls, parsed, raw, attempts = [], None, "", 0
        constrained = bool(self.config.model and self.config.model.answer_mode == "constrained")
        for attempt in range(1, self.config.retry.parse_retries + 2):
            attempts = attempt
            res = await self._call(sem, prompt, t, agent_idx, attempt, labels_shown)
            raw = res.text
            parsed = parse_label(extract_label_text(raw, constrained), self.labels)
            if res.model_version:
                self.model_versions.add(res.model_version)
                pin = self.config.model.pin_version if self.config.model else None
                if pin is not None:
                    if self.pinned_version is None:
                        self.pinned_version = res.model_version
                    elif res.model_version != self.pinned_version:
                        raise ModelDrift(f"model version changed from {self.pinned_version} to {res.model_version}")
            self.effective = {"temperature": res.effective_temperature, "max_tokens": res.effective_max_tokens,
                              **({"request_params": res.request_params} if res.request_params else {})}
            calls.append({"call_id": f"{t}-{agent_id}-{attempt}", "round": t, "agent_id": agent_id,
                          "attempt": attempt, "prompt_text": prompt,
                          "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                          "provider_messages": res.provider_messages, "request_params": res.request_params,
                          "raw_output": raw, "parsed_label": parsed, "valid": parsed is not None,
                          "model_version": res.model_version, "finish_reason": res.finish_reason,
                          "tokens_in": res.tokens_in, "tokens_out": res.tokens_out, "latency_ms": res.latency_ms,
                          "effective_temperature": res.effective_temperature,
                          "effective_max_tokens": res.effective_max_tokens})
            if parsed is not None:
                break
        return parsed, raw, attempts, calls

    # ---- one round -------------------------------------------------------
    async def play_round(self, t: int, sem) -> dict:
        cfg = self.config
        events = self._maybe_activate_minority(t)
        dyads = [Dyad(k, tuple(self.agents[i] for i in idx),
                      (block_of(cfg, idx[0]) == block_of(cfg, idx[1])) if cfg.pairing == "community" else None)
                 for k, idx in enumerate(pair_round(cfg, t))]

        # 1. build every prompt of the round before any choice exists (simultaneity)
        order_rng = rng_for(cfg.seed, "order", t)
        rendered = {}
        for d in dyads:
            for ag in d.members:
                if self.render_prompts:
                    prompt, order, included = build_agent_prompt(ag, cfg, t, order_rng, self.labels)
                    hits = guard_prompt(prompt, reward_on=cfg.reward_mode == "local_match")
                    self.prompts_checked += 1
                    if hits:
                        self.guard_hits.append({"round": t, "agent_id": ag.agent_id, "hits": hits, "prompt": prompt})
                        raise LeakageError(f"denylist hit in prompt for {ag.agent_id} round {t}: {hits}")
                else:
                    prompt, order, included = "", list(self.labels), [r["round"] for r in ag.buffer]
                rendered[ag.agent_id] = (prompt, order, included)

        # 2. choices: rule policies synchronously, LLM calls concurrently
        results: dict[str, tuple] = {}
        pending = []
        for d in dyads:
            for ag in d.members:
                idx = self.index[ag.agent_id]
                if ag.policy == "llm":
                    pending.append((ag.agent_id, self._llm_choice(sem, rendered[ag.agent_id][0], t, idx, ag.agent_id,
                                                                  rendered[ag.agent_id][1])))
                else:
                    lab = choose_rule(ag, cfg, self.labels, self.p0, rng_for(cfg.seed, "policy", t, idx))
                    results[ag.agent_id] = (lab, lab, 1, [])
        if pending:
            outs = await asyncio.gather(*(c for _, c in pending))
            for (aid, _), out in zip(pending, outs):
                results[aid] = out

        # 3. commit + log
        calls, rows = [], []
        round_choices, prev_state = {}, dict(self.state)
        n_invalid = n_void = 0
        for d in dyads:
            ids = [ag.agent_id for ag in d.members]
            choices = {aid: results[aid][0] for aid in ids}
            void = any(c is None for c in choices.values())
            n_invalid += sum(1 for c in choices.values() if c is None)
            points = {}
            shown = None
            if len(d.members) == 2:
                if cfg.partner_source == "prior_replay":
                    rep_ = replayed_labels(cfg, self.labels, self.p0, t, [self.index[a] for a in ids])
                    shown = {a: rep_[self.index[a]] for a in ids}
                else:
                    shown = {ids[0]: choices[ids[1]], ids[1]: choices[ids[0]]}
            if len(d.members) == 2 and not void:
                points = commit_dyad(d, choices, cfg, t, shown)
            n_void += int(void)
            for ag in d.members:
                aid = ag.agent_id
                idx = self.index[aid]
                self.participations[idx] += 1
                choice, raw, attempts, agent_calls = results[aid]
                calls.extend(agent_calls)
                prompt, order, included = rendered[aid]
                partner = next((m for m in d.members if m.agent_id != aid), None)
                pactual = choices.get(partner.agent_id) if partner else None
                pchoice = shown.get(aid) if (partner and shown) else None
                if choice:
                    self.state[aid] = choice
                round_choices[aid] = choice
                rows.append({
                    "run_id": cfg.run_id, "seed": cfg.seed, "config_hash": cfg.config_hash,
                    "label_set_id": cfg.label_set_id, "round": t, "t_pc": self.participations[idx],
                    "dyad_id": d.dyad_id, "agent_id": aid, "partner_id": partner.agent_id if partner else "",
                    "policy": ag.policy, "is_minority": ag.is_minority, "stimulus_id": "s0",
                    "choice": choice or "", "partner_choice": (pchoice or "") if partner else "",
                    "partner_actual_choice": (pactual or "") if partner else "",
                    "partner_source": cfg.partner_source if partner else "",
                    "match": (choice == pchoice) if (partner and not void) else "",
                    "void": void, "valid": choice is not None, "attempts": attempts,
                    "points": points.get(aid), "cum_points": ag.cum_points,
                    "memory_records_included": included, "label_order_shown": order,
                    "choice_position": order.index(choice) if choice in order else "",
                    "reward_shown": cfg.reward_mode == "local_match" and cfg.pairing != "isolated",
                    "feedback_text_shown": prompt.split("Your own recent interactions, if any:\n", 1)[-1] if prompt else "",
                    "block_id": block_of(cfg, idx), "within_block": d.within_block,
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest() if prompt else "",
                    "raw_output": raw if ag.policy == "llm" else "",
                })
        self.round_choice_history.append([c for c in round_choices.values() if c])
        t_pc_mean = sum(self.participations) / cfg.n_agents
        pop = metrics.population_row(t, t_pc_mean, round_choices, self.state, prev_state, self.K,
                                     n_choices=len(round_choices), n_invalid=n_invalid, n_dyads=len(dyads),
                                     n_void=n_void, minority_ids=self.minority_ids, tie_key=f"{cfg.seed}|{t}")
        self.tracker.update(t, pop["state_modal_share"])
        self.round_rows.append(pop)
        if self.store is not None:
            self.store.append_round(calls, rows, pop, events)
        self._last_rows = rows
        return pop

    # ---- whole run -------------------------------------------------------
    def _manifest_base(self) -> dict:
        cfg = self.config
        return {"run_id": cfg.run_id, "experiment_id": cfg.experiment_id, "config_hash": cfg.config_hash,
                "schema_version": cfg.schema_version, "template_version": cfg.template_version,
                "template_hashes": template_hashes(cfg.template_version), "cell_id": cfg.cell_id, "phase": cfg.phase, "label_set_id": cfg.label_set_id,
                "label_set_hash": label_set_hash(list(self.labels)), "labels": list(self.labels),
                "p0_used": self.p0, "git_commit": _git_commit(), "package_versions": _versions(),
                "model_notes": model_notes(cfg.model.provider, cfg.model.model_id) if cfg.model else []}

    async def run(self, start_round: int = 0, stop_after: Optional[int] = None) -> dict:
        cfg = self.config
        if self.store is not None:
            if start_round == 0:
                self.store.write_json("config.json", {**cfg.model_dump(mode="json"), "config_hash": cfg.config_hash})
                self.store.write_json("manifest.json", {**self._manifest_base(), "status": "running",
                                                        "started_at": _now(), "rounds_done": 0})
            else:
                self.store.update_manifest(status="running", resumed_at=_now())
        sem = asyncio.Semaphore(cfg.max_concurrency)
        status, error = "completed", None
        last = start_round - 1
        try:
            for t in range(start_round, cfg.n_rounds):
                if self.cancel_event is not None and self.cancel_event.is_set():
                    raise RunCancelled()
                pop = await self.play_round(t, sem)
                last = t
                if self.store is not None and (t % 10 == 0 or t == cfg.n_rounds - 1):
                    self.store.update_manifest(rounds_done=t + 1)
                if self.progress:
                    self.progress({"type": "round", "run_id": cfg.run_id, **pop})
                if stop_after is not None and t >= stop_after:
                    status = "stopped"
                    break
        except RunCancelled:
            status = "cancelled"
        except LeakageError as ex:
            status, error = "failed_leakage", str(ex)
        except FatalModelError as ex:
            status, error = "failed_model", str(ex)
        except RetryableError as ex:
            status, error = "failed_api", str(ex)
        except ModelDrift as ex:
            status, error = "failed_model_drift", str(ex)
        except Exception as ex:  # noqa: BLE001 - record any unexpected failure on the run itself
            status, error = "failed_error", f"{type(ex).__name__}: {ex}"
        return self._finish(status, error, last)

    def _finish(self, status, error, last) -> dict:
        cfg = self.config
        leakage = {"passed": not self.guard_hits, "prompts_checked": self.prompts_checked,
                   "hits": self.guard_hits, "checked_at": _now(),
                   "checks": ["denylist + regex on every rendered prompt before dispatch (fail-closed)",
                              "prompts of a round built before any choice of that round exists"]}
        summary = None
        if self.store is not None:
            self.store.write_json("leakage_report.json", leakage)
            interactions = self.store.read_csv("interactions.csv")
            population = self.store.read_csv("population.csv")
            summary = metrics.summarize(population, interactions, cfg, self.labels)
            if cfg.experiment_id == "prior_calibration":
                summary["prior"] = metrics.prior_from_calibration(interactions, self.labels)
            self.store.write_json("summary.json", summary)
            self.store.update_manifest(status=status, error=error, ended_at=_now(), rounds_done=last + 1,
                                       leakage_passed=leakage["passed"],
                                       model_versions=sorted(self.model_versions), pinned_version=self.pinned_version,
                                       effective_sampling=self.effective)
        if self.progress:
            self.progress({"type": "done", "run_id": cfg.run_id, "status": status, "error": error,
                           "summary": summary})
        return {"status": status, "error": error, "rounds_done": last + 1, "summary": summary,
                "leakage": leakage}

    # ---- resume ----------------------------------------------------------
    @classmethod
    def resume(cls, store: RunStore, model=None, progress=None, cancel_event=None) -> tuple["Simulation", int]:
        """Rebuild state from the store (deterministic) and return (sim, next_round)."""
        cfg_json = store.read_json("config.json")
        cfg_json.pop("config_hash", None)
        if cfg_json.get("model") and "answer_mode" not in cfg_json["model"]:
            cfg_json["model"]["answer_mode"] = "free_text"  # runs made before answer_mode existed
        cfg = ExperimentConfig(**cfg_json)
        last = store.last_complete_round()
        store.truncate_after(last)
        sim = cls(cfg, store=store, model=model, progress=progress, cancel_event=cancel_event)
        rows = store.read_csv("interactions.csv")
        events = store.read_jsonl("events.jsonl")
        act = {e["round"]: e for e in events if e.get("event") == "minority_activated"}
        rel = {e["round"] for e in events if e.get("event") == "minority_released"}
        by_round: dict[int, list[dict]] = {}
        for r in rows:
            by_round.setdefault(int(r["round"]), []).append(r)
        for rd in sorted(by_round):
            if rd in act:
                sim._apply_minority(act[rd]["agent_ids"], act[rd]["label"])
            if rd in rel:
                sim._release_minority()
            dyads: dict[int, list[dict]] = {}
            for r in by_round[rd]:
                dyads.setdefault(int(r["dyad_id"]), []).append(r)
            round_choices = []
            for did in sorted(dyads):
                members = dyads[did]
                for r in members:
                    sim.participations[sim.index[r["agent_id"]]] += 1
                    if r["choice"]:
                        sim.state[r["agent_id"]] = r["choice"]
                        round_choices.append(r["choice"])
                if len(members) == 2 and members[0]["void"] != "True":
                    ags = tuple(sim.agents[sim.index[r["agent_id"]]] for r in members)
                    shown = {r["agent_id"]: r["partner_choice"] for r in members}
                    commit_dyad(Dyad(did, ags), {r["agent_id"]: r["choice"] for r in members}, cfg, rd, shown)
            sim.round_choice_history.append(round_choices)
        for p in store.read_csv("population.csv"):
            sim.tracker.update(int(p["round"]), float(p["state_modal_share"] or "nan"))
        return sim, last + 1


def build_run(config: ExperimentConfig, *, base_dir=None, model=None, progress=None, cancel_event=None,
              persist: bool = True) -> Simulation:
    store = None
    if persist:
        store = RunStore.for_config(config) if base_dir is None else RunStore.for_config(config, base_dir)
    return Simulation(config, store=store, model=model, progress=progress, cancel_event=cancel_event)


def run_sync(config: ExperimentConfig, **kw) -> dict:
    return asyncio.run(build_run(config, **kw).run())
