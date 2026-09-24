"""Command line: python -m naming_game.cli <command> ...

  labels [--freeze]              show (or create, once) the frozen label sets
  validate CONFIG.json           validate + cost estimate + example prompt
  dry-run CONFIG.json            whole pipeline with the mock model, no network
  run CONFIG.json [--yes]        one run (asks before paid calls)
  resume RUN_ID                  continue an interrupted run
  matrix SPEC.json [--yes]       expand a factorial, estimate cost, run all
  metrics RUN_ID                 recompute summary.json from the store
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .config import load_config
from .labels import freeze_label_sets, get_labels, load_label_sets
from .metrics import prior_from_calibration, summarize
from .runner import dry_run, estimate, estimate_matrix, example_prompts, expand_matrix
from .scheduler import Simulation
from .store import RunStore, find_run


def _progress(ev):
    if ev["type"] == "round" and (ev["round"] % 10 == 0):
        print(f"  round {ev['round']:4d}  modal {ev['state_modal_label']:<6} share {ev['state_modal_share']:.3f}  "
              f"H_norm {ev['state_entropy_norm']:.3f}  invalid {ev['invalid_rate']:.3f}", flush=True)
    elif ev["type"] == "done":
        print(f"  -> {ev['status']} {ev.get('error') or ''}")


def _confirm(est, yes):
    if not est["paid"]:
        return True
    cost = est["est_cost_usd"]
    print(f"Paid run: {est['calls']:,} calls, ~{est.get('est_input_tokens', 0):,} input tokens, "
          f"estimated ${cost:.4f}" if cost is not None else "estimated cost unknown (model not in PRICING)")
    if yes:
        return True
    return input("Proceed? [y/N] ").strip().lower() == "y"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="naming_game")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("labels"); p.add_argument("--freeze", action="store_true")
    for name in ("validate", "dry-run"):
        sub.add_parser(name).add_argument("config")
    p = sub.add_parser("run"); p.add_argument("config"); p.add_argument("--yes", action="store_true")
    sub.add_parser("resume").add_argument("run_id")
    p = sub.add_parser("matrix"); p.add_argument("spec"); p.add_argument("--yes", action="store_true")
    sub.add_parser("metrics").add_argument("run_id")
    a = ap.parse_args(argv)

    if a.cmd == "labels":
        if a.freeze:
            freeze_label_sets()
        print(json.dumps(load_label_sets(), indent=2))
    elif a.cmd == "validate":
        c = load_config(a.config)
        print(json.dumps({"config_hash": c.config_hash, "estimate": estimate(c)}, indent=2))
        print(example_prompts(c)["this_config"]["with_memory"])
    elif a.cmd == "dry-run":
        with open(a.config) as f:
            r = dry_run(json.load(f))
        print(json.dumps({k: r[k] for k in ("status", "rounds", "leakage")}, indent=2, default=str))
    elif a.cmd == "run":
        c = load_config(a.config)
        if not _confirm(estimate(c), a.yes):
            return 1
        sim = Simulation(c, store=RunStore.for_config(c), progress=_progress)
        print(f"run {c.run_id} -> {sim.store.dir}")
        asyncio.run(sim.run())
    elif a.cmd == "resume":
        d = find_run(a.run_id)
        if d is None:
            print("run not found"); return 1
        sim, start = Simulation.resume(RunStore(d), progress=_progress)
        asyncio.run(sim.run(start_round=start))
    elif a.cmd == "matrix":
        with open(a.spec) as f:
            cfgs = expand_matrix(json.load(f))
        est = estimate_matrix(cfgs)
        print(f"{est['n_runs']} runs")
        if not _confirm(est, a.yes):
            return 1
        for c in cfgs:
            print(f"== {c.run_id} seed {c.seed} {c.label_set_id}")
            asyncio.run(Simulation(c, store=RunStore.for_config(c), progress=_progress).run())
    elif a.cmd == "metrics":
        s = RunStore(find_run(a.run_id))
        cfg = s.read_json("config.json")
        labels = get_labels(cfg["label_set_id"])
        from .config import ExperimentConfig
        cfg.pop("config_hash", None)
        c = ExperimentConfig(**cfg)
        inter = s.read_csv("interactions.csv")
        summ = summarize(s.read_csv("population.csv"), inter, c, labels)
        if c.experiment_id == "prior_calibration":
            summ["prior"] = prior_from_calibration(inter, labels)
        s.write_json("summary.json", summ)
        print(json.dumps(summ, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
