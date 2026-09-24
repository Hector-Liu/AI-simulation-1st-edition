"""Run management for the web app and CLI: background runs, progress events,
cancellation, resume, matrix expansion and cost estimates (SPEC §9, §10)."""
from __future__ import annotations

import asyncio
import itertools
import json
import threading
import uuid
from typing import Optional

from .config import ExperimentConfig
from .labels import get_labels
from .llm import PRICING, MockModel, model_notes
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
        if cfg.reward_mode == "none":
            d.update(reward_mode="local_match", payoff=None,
                     feedback_mode="numeric_score" if cfg.memory_on else "choices_only",
                     show_cumulative_points=None, experiment_id="rewarded_naming")
        else:
            d.update(reward_mode="none", payoff=None, feedback_mode="choices_only",
                     show_cumulative_points=None, experiment_id="no_reward_convergence")
        try:
            other = ExperimentConfig(**d)
            out["other_arm"] = {"first_round": render(other, False), "with_memory": render(other, True)}
        except Exception as ex:  # noqa: BLE001
            out["other_arm_error"] = str(ex)
    return out


def estimate(cfg: ExperimentConfig) -> dict:
    calls = n_calls(cfg) if cfg.policy_default == "llm" else 0
    prompts = example_prompts(cfg)["this_config"]
    avg_chars = (len(prompts["first_round"]) + len(prompts["with_memory"])) / 2
    tokens_in = int(avg_chars / 3.5) + 8  # rough; the calls log records real usage
    tokens_out = 4
    provider = cfg.model.provider if cfg.model else "mock"
    model_id = cfg.model.model_id if cfg.model else "mock"
    price = PRICING.get("mock" if provider == "mock" else model_id)
    retry_factor = 1.03
    total_in, total_out = calls * tokens_in * retry_factor, calls * tokens_out * retry_factor
    cost = None if price is None else (total_in * price[0] + total_out * price[1]) / 1e6
    return {"calls": calls, "est_input_tokens": int(total_in), "est_output_tokens": int(total_out),
            "est_cost_usd": cost, "price_per_mtok": price, "pricing_known": price is not None,
            "paid": provider != "mock" and calls > 0,
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
                        job.emit({"type": "run_started", "run_id": sim.config.run_id, "index": i,
                                  "n_rounds": sim.config.n_rounds, "start_round": start})
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
    d.pop("run_id", None)
    cfg = ExperimentConfig(**d)
    model = MockModel() if cfg.policy_default == "llm" else None
    sim = Simulation(cfg, store=None, model=model)
    res = asyncio.run(sim.run())
    return {"status": res["status"], "rounds": res["rounds_done"], "leakage": res["leakage"],
            "population": sim.round_rows, "sample_prompts": example_prompts(cfg)}


def dumps(o) -> str:
    from .store import sanitize
    return json.dumps(sanitize(o))
