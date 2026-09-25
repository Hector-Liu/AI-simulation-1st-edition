"""Run management for the web app and CLI: background runs, progress events,
cancellation, resume, matrix expansion and cost estimates (SPEC §9, §10)."""
from __future__ import annotations

import asyncio
import itertools
import json
import threading
import uuid
from typing import Optional

import numpy as np

from .config import ExperimentConfig
from .labels import get_labels
from . import local_settings
from .llm import MockModel, model_notes
from .rooms import ROOMS, room_fields
from .prompts import build_agent_prompt
from .agents import Agent
from .scheduler import Dyad, Simulation, commit_dyad, rng_for
from .store import RunStore

# ------------------------------------------------------------- estimates ---


def n_calls(cfg: ExperimentConfig) -> int:
    per_round = 2 if cfg.pairing == "star" else cfg.n_agents
    return per_round * cfg.n_rounds


def example_prompts(cfg: ExperimentConfig) -> dict:
    """Rendered example prompts: first round (empty buffer) and one with a
    full buffer, for this config and for its other reward arm."""
    labels = get_labels(cfg.label_set_id)

    def render(c, filled):
        cap = c.H if c.memory_on else 0
        ag, partner = Agent(c.agent_ids[0], "llm", cap), Agent(c.agent_ids[1], "llm", cap)
        if filled and c.memory_on:
            # illustrative history, written through the single memory writer
            for i in range(c.H):
                mine = labels[i % len(labels)]
                theirs = mine if i % 2 else labels[(i * 3 + 1) % len(labels)]
                commit_dyad(Dyad(i, (ag, partner)), {ag.agent_id: mine, partner.agent_id: theirs}, c, i)
        return build_agent_prompt(ag, c, 0, rng_for(c.seed, "order", 0), labels)[0]

    out = {"this_config": {"first_round": render(cfg, False), "with_memory": render(cfg, True)}}
    if cfg.pairing != "isolated":
        d = cfg.model_dump()
        # v2: the two reward arms differ only by the payoff block (choices_only in both)
        fb = cfg.feedback_mode if cfg.feedback_mode != "numeric_score" else "choices_only"
        if cfg.reward_mode == "none":
            d.update(reward_mode="local_match", payoff=None, feedback_mode=fb,
                     show_cumulative_points=None, experiment_id="rewarded_naming")
        else:
            d.update(reward_mode="none", payoff=None, feedback_mode=fb,
                     show_cumulative_points=None, experiment_id="no_reward_convergence")
        if cfg.cell_id:
            d["cell_id"] = COUNTERPART.get(cfg.cell_id)
        try:
            other = ExperimentConfig(**d)
            out["other_arm"] = {"first_round": render(other, False), "with_memory": render(other, True)}
        except Exception as ex:  # noqa: BLE001
            out["other_arm_error"] = str(ex)
    return out


COUNTERPART = {"B0": "A0", "B1": "A1", "B2": "A2", "A0": "B0", "A1": "B1", "A2": "B2", "B2R": "A2R", "A2R": "B2R"}


def estimate(cfg: ExperimentConfig) -> dict:
    calls = n_calls(cfg) if cfg.policy_default == "llm" else 0
    prompts = example_prompts(cfg)["this_config"]
    avg_chars = (len(prompts["first_round"]) + len(prompts["with_memory"])) / 2
    tokens_in = int(avg_chars / 3.5) + 8  # rough; the calls log records real usage
    tokens_out = 4
    uncertain = False
    if cfg.model and cfg.model.provider == "anthropic":
        from .llm import ANTHROPIC_PROFILES
        if ANTHROPIC_PROFILES.get(cfg.model.model_id, {}).get("thinking") == "always":
            tokens_out, uncertain = 300, True  # hidden reasoning tokens are billed; rough guess
    provider = cfg.model.provider if cfg.model else "mock"
    model_id = cfg.model.model_id if cfg.model else "mock"
    price = (0.0, 0.0) if provider == "mock" else local_settings.price_for(model_id)
    retry_factor = 1.03
    total_in, total_out = calls * tokens_in * retry_factor, calls * tokens_out * retry_factor
    cost = None if price is None else (total_in * price[0] + total_out * price[1]) / 1e6
    return {"calls": calls, "est_input_tokens": int(total_in), "est_output_tokens": int(total_out),
            "est_cost_usd": cost, "price_per_mtok": price, "pricing_known": price is not None,
            "paid": provider != "mock" and calls > 0, "output_estimate_uncertain": uncertain,
            "model_notes": model_notes(provider, model_id) if cfg.model else []}


# ------------------------------------------------------------- matrix ------

def expand_matrix(spec: dict) -> list[ExperimentConfig]:
    """spec = {"base": {...config...}, "factors": {"field": [values], ...},
    "seeds": [..] or "n_seeds": k, "seed_start": 0, "label_sets": ["L1", ...]}.
    Seeds are nested in label sets and spread evenly (SPEC §3.2)."""
    base = dict(spec["base"])
    factors = spec.get("factors", {})
    seeds = spec.get("seeds") or list(range(spec.get("seed_start", 0), spec.get("seed_start", 0) + spec.get("n_seeds", 1)))
    label_sets = spec.get("label_sets") or [base.get("label_set_id", "L1")]
    keys = list(factors)
    out = []
    for combo in itertools.product(*(factors[k] for k in keys)) if keys else [()]:
        for i, seed in enumerate(seeds):
            d = dict(base)
            for k, v in zip(keys, combo):
                if isinstance(v, dict) and k == "_cell":
                    d.update(v)
                else:
                    d[k] = v
            d["seed"] = seed
            d["label_set_id"] = label_sets[i % len(label_sets)]
            d.pop("run_id", None)
            out.append(ExperimentConfig(**d))
    return out


def estimate_matrix(configs) -> dict:
    ests = [estimate(c) for c in configs]
    costs = [e["est_cost_usd"] for e in ests]
    return {"n_runs": len(configs), "calls": sum(e["calls"] for e in ests),
            "est_cost_usd": None if any(c is None for c in costs) else sum(costs),
            "paid": any(e["paid"] for e in ests)}


# ------------------------------------------------------------- jobs --------

class Job:
    def __init__(self, kind: str, run_ids: list[str]):
        self.id = uuid.uuid4().hex[:10]
        self.kind = kind
        self.run_ids = run_ids
        self.events: list[dict] = []
        self.status = "queued"
        self.cancel = threading.Event()
        self.cond = threading.Condition()
        self.current_run: Optional[str] = None

    def emit(self, ev: dict):
        with self.cond:
            self.events.append(ev)
            self.cond.notify_all()


class JobManager:
    """Runs experiments in background threads (one asyncio loop per job)."""

    def __init__(self):
        self.jobs: dict[str, Job] = {}

    def start(self, configs: list[ExperimentConfig], kind="run", resume_dirs=None) -> Job:
        job = Job(kind, [c.run_id for c in configs] if configs else [])
        self.jobs[job.id] = job
        threading.Thread(target=self._work, args=(job, configs, resume_dirs), daemon=True).start()
        return job

    def _work(self, job: Job, configs, resume_dirs):
        job.status = "running"
        job.emit({"type": "job_started", "job_id": job.id, "n_runs": len(configs or resume_dirs or [])})

        async def main():
            cancel = asyncio.Event()

            async def watch():
                while not job.cancel.is_set():
                    await asyncio.sleep(0.2)
                cancel.set()
            watcher = asyncio.create_task(watch())
            try:
                items = resume_dirs or configs
                for i, item in enumerate(items):
                    if job.cancel.is_set():
                        break
                    try:
                        if resume_dirs:
                            sim, start = Simulation.resume(RunStore(item), progress=job.emit, cancel_event=cancel)
                        else:
                            sim = Simulation(item, store=RunStore.for_config(item), progress=job.emit,
                                             cancel_event=cancel)
                            start = 0
                        job.current_run = sim.config.run_id
                        job.emit({"type": "run_started", "run_id": sim.config.run_id, "index": i, "n_runs": len(items),
                                  "n_rounds": sim.config.n_rounds, "start_round": start, "cell_id": sim.config.cell_id,
                                  "label_set_id": sim.config.label_set_id, "seed": sim.config.seed})
                        await sim.run(start_round=start)
                    except Exception as ex:  # noqa: BLE001
                        job.emit({"type": "error", "message": f"{type(ex).__name__}: {ex}"})
            finally:
                watcher.cancel()

        try:
            asyncio.run(main())
            job.status = "cancelled" if job.cancel.is_set() else "finished"
        except Exception as ex:  # noqa: BLE001
            job.status = "failed"
            job.emit({"type": "error", "message": str(ex)})
        job.emit({"type": "job_done", "job_id": job.id, "status": job.status})


jobs = JobManager()


def dry_run(cfg_dict: dict) -> dict:
    """Whole pipeline with the mock model and no store; returns sample prompts
    and structural checks (SPEC §9 /dry-run)."""
    d = dict(cfg_dict)
    d["model"] = {"provider": "mock", "model_id": "mock", "mock_mode": "uniform"}
    if d.get("policy_default", "llm") != "llm":
        d["model"] = None
    d["n_rounds"] = min(int(d.get("n_rounds", 20)), 20)
    d["phase"] = "test"
    d.pop("run_id", None)
    cfg = ExperimentConfig(**d)
    model = MockModel() if cfg.policy_default == "llm" else None
    sim = Simulation(cfg, store=None, model=model)
    res = asyncio.run(sim.run())
    return {"status": res["status"], "rounds": res["rounds_done"], "leakage": res["leakage"],
            "population": sim.round_rows, "sample_prompts": example_prompts(cfg)}


# ------------------------------------------------------------- study plan --

class PlanError(ValueError):
    pass


def plan_configs(spec: dict) -> tuple[list[ExperimentConfig], list[dict]]:
    """Expand a Study Plan launch request into configs.

    spec: {rooms, label_sets, n_seeds, seed_start, n_agents, n_rounds, H,
           model: {provider, model_id, temperature, max_tokens_cap, pin_version},
           phase, prior_mode: derive|uniform, max_concurrency, notes}
    Returns (configs in an interleaved order, notes about priors used).
    """
    from .priors import derive_prior
    rooms, label_sets = spec.get("rooms") or [], spec.get("label_sets") or []
    if not rooms:
        raise PlanError("select at least one room")
    if not label_sets:
        raise PlanError("select at least one label set")
    n_seeds = int(spec.get("n_seeds", 1))
    seed_start = int(spec.get("seed_start", 0))
    model = dict(spec.get("model") or {})
    phase = spec.get("phase", "pilot")
    if model.get("provider") == "mock":
        phase = "test"
    prior_mode = spec.get("prior_mode", "derive")
    configs, prior_notes = [], []
    prior_cache = {}
    for room in rooms:
        if room not in ROOMS:
            raise PlanError(f"unknown room {room}")
        for ls in label_sets:
            labels = get_labels(ls)
            extra = {}
            if ROOMS[room].get("partner_source") == "prior_replay":
                src = ROOMS[room]["prior_room"]
                key = (src, ls)
                if key not in prior_cache:
                    if prior_mode == "uniform":
                        prior_cache[key] = {"p0": [1 / len(labels)] * len(labels), "source": "uniform (explicit)", "available": True}
                    else:
                        pr = derive_prior(ls, src, model.get("provider"), model.get("model_id"),
                                          model.get("temperature"), phase)
                        if not pr["available"]:
                            raise PlanError(f"room {room} needs a matched prior from room {src} on label set {ls} "
                                            f"with the same model and temperature, but no completed {src} run exists yet. "
                                            f"Run {src} first, or choose a uniform prior.")
                        prior_cache[key] = {"p0": pr["p0_smoothed"], "source": pr["source"], "available": True}
                    prior_notes.append({"room": room, "label_set": ls, "source": prior_cache[key]["source"]})
                extra = {"p0": prior_cache[key]["p0"], "p0_source": prior_cache[key]["source"]}
            for seed in range(seed_start, seed_start + n_seeds):
                d = {**room_fields(room), **extra, "seed": seed, "label_set_id": ls, "label_pool_size": len(labels),
                     "n_agents": int(spec.get("n_agents", 24)), "n_rounds": int(spec.get("n_rounds", 300)),
                     "phase": phase, "model": model, "max_concurrency": int(spec.get("max_concurrency", 24)),
                     "notes": spec.get("notes", "")}
                if d.get("memory_mode") != "none":
                    d["memory_horizon_H"] = int(spec.get("H", 5))
                configs.append(ExperimentConfig(**d))
    import random as _random
    order_seed = spec.get("order_seed")
    if order_seed is None:
        order_seed = _random.SystemRandom().randrange(2 ** 31)
    rng = np.random.default_rng(int(order_seed))
    configs = [configs[i] for i in rng.permutation(len(configs))]  # interleave cells (P3-7)
    return configs, prior_notes + [{"order_seed": int(order_seed)}]


def dumps(o) -> str:
    from .store import sanitize
    return json.dumps(sanitize(o))
