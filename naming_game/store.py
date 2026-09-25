"""Append-only analyst store (SPEC §6). Agents have no handle to it.

Layout: logs/experiments/{experiment_id}/{run_id}/
  config.json, manifest.json, calls.jsonl, interactions.csv, population.csv,
  events.jsonl, summary.json, leakage_report.json
Rows of a round are written together after the round completes, so a crashed
run always ends on a whole round (resume truncates any partial tail).
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs" / "experiments"

INTERACTION_COLUMNS = [
    "run_id", "seed", "config_hash", "label_set_id", "round", "t_pc", "dyad_id", "agent_id", "partner_id",
    "policy", "is_minority", "stimulus_id", "choice", "partner_choice", "partner_actual_choice", "partner_source", "match", "void", "valid", "attempts",
    "points", "cum_points", "memory_records_included", "label_order_shown", "choice_position",
    "reward_shown", "feedback_text_shown", "block_id", "within_block", "prompt_sha256", "raw_output",
]
POPULATION_COLUMNS = [
    "round", "t_pc_mean",
    *[f"{s}{m}" for s in ("round_", "state_", "state_excl_minority_")
      for m in ("entropy", "entropy_norm", "modal_label", "modal_share", "n_unique_labels", "modal_tie")],
    "switch_rate", "n_choices", "invalid_rate", "void_rate",
]


def _clean(v):
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def sanitize(o):
    """Replace NaN/inf with None recursively so JSON stays strict."""
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [sanitize(v) for v in o]
    return o


def _cell(v):
    if isinstance(v, (list, tuple, dict)):
        return json.dumps(v)
    if v is None:
        return ""
    return v


class RunStore:
    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_config(cls, config, base: Path | None = None) -> "RunStore":
        return cls(Path(base if base is not None else LOGS_DIR) / config.experiment_id / config.run_id)

    def path(self, name: str) -> Path:
        return self.dir / name

    # ---- writers ---------------------------------------------------------
    def write_json(self, name: str, obj):
        tmp = self.path(name + ".tmp")
        tmp.write_text(json.dumps(sanitize(obj), indent=2, allow_nan=False) + "\n")
        tmp.replace(self.path(name))

    def update_manifest(self, **fields):
        m = self.read_json("manifest.json") or {}
        m.update(fields)
        self.write_json("manifest.json", m)

    def _append_csv(self, name, columns, rows):
        p = self.path(name)
        new = not p.exists()
        if not new:  # keep the header of an existing file (runs written by an older schema)
            with p.open(newline="") as f:
                columns = next(csv.reader(f), None) or columns
        with p.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columns, extrasaction="raise" if new else "ignore")
            if new:
                w.writeheader()
            for r in rows:
                w.writerow({k: _cell(_clean(r.get(k))) for k in columns})
            f.flush()

    def append_round(self, calls: list[dict], interactions: list[dict], population: dict, events: list[dict]):
        with self.path("calls.jsonl").open("a") as f:
            for c in calls:
                f.write(json.dumps(sanitize(c)) + "\n")
        if events:
            with self.path("events.jsonl").open("a") as f:
                for e in events:
                    f.write(json.dumps(e) + "\n")
        self._append_csv("interactions.csv", INTERACTION_COLUMNS, interactions)
        # population last: its presence marks the round as complete
        self._append_csv("population.csv", POPULATION_COLUMNS, [population])

    # ---- readers (analyst side only) ------------------------------------
    def read_json(self, name: str):
        p = self.path(name)
        return json.loads(p.read_text()) if p.exists() else None

    def read_csv(self, name: str) -> list[dict]:
        p = self.path(name)
        if not p.exists():
            return []
        with p.open(newline="") as f:
            return list(csv.DictReader(f))

    def read_jsonl(self, name: str, limit: int | None = None) -> list[dict]:
        p = self.path(name)
        if not p.exists():
            return []
        out = []
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    break  # partial trailing line from a crash
                if limit and len(out) >= limit:
                    break
        return out

    def last_complete_round(self) -> int:
        rows = self.read_csv("population.csv")
        return int(rows[-1]["round"]) if rows else -1

    def truncate_after(self, last_round: int):
        """Drop rows of any round after `last_round` (partial tail of a crash)."""
        for name in ("interactions.csv", "population.csv"):
            rows = self.read_csv(name)
            if not rows:
                continue
            keep = [r for r in rows if _int(r.get("round")) is not None and _int(r["round"]) <= last_round]
            cols = list(rows[0].keys())  # keep the file's own header
            with self.path(name).open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows(keep)
        for name in ("calls.jsonl", "events.jsonl"):
            rows = [r for r in self.read_jsonl(name) if _int(r.get("round", -1)) is not None
                    and _int(r.get("round", -1)) <= last_round]
            with self.path(name).open("w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")


def list_runs(base: Path | None = None) -> list[dict]:
    base = Path(base) if base is not None else LOGS_DIR
    out = []
    if not base.exists():
        return out
    for mpath in base.glob("*/*/manifest.json"):
        try:
            m = json.loads(mpath.read_text())
        except json.JSONDecodeError:
            continue
        cfg_path = mpath.parent / "config.json"
        cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        summ_path = mpath.parent / "summary.json"
        summ = json.loads(summ_path.read_text()) if summ_path.exists() else {}
        out.append({"run_id": m.get("run_id"), "experiment_id": m.get("experiment_id"),
                    "status": m.get("status"), "started_at": m.get("started_at"), "ended_at": m.get("ended_at"),
                    "config_hash": m.get("config_hash"), "seed": cfg.get("seed"),
                    "label_set_id": cfg.get("label_set_id"), "n_agents": cfg.get("n_agents"),
                    "n_rounds": cfg.get("n_rounds"), "pairing": cfg.get("pairing"),
                    "reward_mode": cfg.get("reward_mode"), "memory_mode": cfg.get("memory_mode"),
                    "memory_content": cfg.get("memory_content"), "H": cfg.get("memory_horizon_H"),
                    "policy": cfg.get("policy_default"), "model": (cfg.get("model") or {}).get("model_id"),
                    "temperature": (cfg.get("model") or {}).get("temperature"),
                    "cell_id": cfg.get("cell_id"), "phase": cfg.get("phase", "pilot"),
                    "template_version": cfg.get("template_version", "v1"),
                    "partner_source": cfg.get("partner_source", "actual"), "framing": cfg.get("framing", "social"),
                    "model_versions": m.get("model_versions", []),
                    "answer_mode": (cfg.get("model") or {}).get("answer_mode", "free_text") if cfg.get("model") else None,
                    "provider": (cfg.get("model") or {}).get("provider"), "notes": cfg.get("notes", ""),
                    "summary": summ, "leakage_passed": m.get("leakage_passed"),
                    "rounds_done": m.get("rounds_done"), "dir": str(mpath.parent)})
    out.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return out


def find_run(run_id: str, base: Path | None = None) -> Path | None:
    base = Path(base) if base is not None else LOGS_DIR
    for p in base.glob(f"*/{run_id}"):
        if p.is_dir():
            return p
    return None
