"""Prompt-matched label priors (SPEC v2 §3.4).

A room's matched prior is the pooled choice frequency from completed runs of
its source room (B0 for the no-reward arm, A0 for the reward arm) on the same
label set, model and temperature. These are analyst-side computations; no
agent ever sees them. A confirmatory run may only use priors from pilot runs.
"""
from __future__ import annotations

from collections import Counter

from .labels import get_labels
from .store import RunStore, list_runs


def derive_prior(label_set_id: str, source_room: str, provider: str, model_id: str,
                 temperature, target_phase: str = "pilot", answer_mode: str = "constrained") -> dict:
    labels = get_labels(label_set_id)
    allowed = {"pilot"} if target_phase == "confirmatory" else {"pilot", "exploratory", "test", "confirmatory"}
    runs = [r for r in list_runs()
            if r.get("cell_id") == source_room and r.get("label_set_id") == label_set_id
            and r.get("provider") == provider and r.get("model") == model_id
            and _same_t(r.get("temperature"), temperature) and r.get("status") == "completed"
            and r.get("template_version") == "v2" and r.get("phase") in allowed
            and r.get("answer_mode") == answer_mode]
    counts = Counter()
    for r in runs:
        for row in RunStore(r["dir"]).read_csv("interactions.csv"):
            if row["choice"]:
                counts[row["choice"]] += 1
    n = sum(counts.values())
    K = len(labels)
    raw = [counts.get(lab, 0) / n if n else 1 / K for lab in labels]
    smoothed = [(counts.get(lab, 0) + 0.5) / (n + 0.5 * K) for lab in labels] if n else [1 / K] * K
    return {
        "available": n > 0, "label_set_id": label_set_id, "labels": list(labels), "source_room": source_room,
        "n_runs": len(runs), "run_ids": [r["run_id"] for r in runs], "n_choices": n,
        "counts": [counts.get(lab, 0) for lab in labels], "p0": raw, "p0_smoothed": smoothed,
        "source": f"derived:{source_room}:{label_set_id}:{provider}:{model_id}:T={temperature}:{answer_mode}:runs={len(runs)}:n={n}",
    }


def _same_t(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) < 1e-9
