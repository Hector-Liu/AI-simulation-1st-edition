"""Metrics (SPEC §7). Computed from logged choices; never judged by an LLM.

Nothing here is ever passed back to agents. The agent path (agents.py,
prompts.py) must not import this module (test 14).
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np


def entropy_of(values, K: int) -> tuple[float, float]:
    vals = [v for v in values if v]
    if not vals:
        return float("nan"), float("nan")
    n = len(vals)
    h = -sum((c / n) * math.log2(c / n) for c in Counter(vals).values())
    return h, (h / math.log2(K) if K > 1 else 0.0)


def modal(values) -> tuple[str, float, int]:
    vals = [v for v in values if v]
    if not vals:
        return "", float("nan"), 0
    counts = Counter(vals)
    top = max(counts.values())
    label = sorted(k for k, c in counts.items() if c == top)[0]  # ties: alphabetical first
    return label, top / len(vals), len(counts)


def _scope(prefix: str, values, K: int) -> dict:
    h, hn = entropy_of(values, K)
    lab, share, n_unique = modal(values)
    return {f"{prefix}entropy": h, f"{prefix}entropy_norm": hn, f"{prefix}modal_label": lab,
            f"{prefix}modal_share": share, f"{prefix}n_unique_labels": n_unique}


def population_row(round_idx: int, t_pc_mean: float, round_choices: dict, state: dict, prev_state: dict,
                   K: int, n_choices: int, n_invalid: int, n_dyads: int, n_void: int,
                   minority_ids: set) -> dict:
    """One row per round: (a) this round's valid choices, (b) the population
    state (each agent's latest valid choice), and (c) the state without the
    committed minority."""
    row = {"round": round_idx, "t_pc_mean": t_pc_mean}
    row.update(_scope("round_", list(round_choices.values()), K))
    row.update(_scope("state_", list(state.values()), K))
    row.update(_scope("state_excl_minority_", [v for a, v in state.items() if a not in minority_ids], K))
    switched = [a for a, c in round_choices.items() if c and prev_state.get(a) and prev_state[a] != c]
    eligible = [a for a, c in round_choices.items() if c and prev_state.get(a)]
    row["switch_rate"] = len(switched) / len(eligible) if eligible else float("nan")
    row["n_choices"] = n_choices
    row["invalid_rate"] = n_invalid / n_choices if n_choices else 0.0
    row["void_rate"] = n_void / n_dyads if n_dyads else 0.0
    return row


class ConsensusTracker:
    """modal_share(state) >= threshold for >= W consecutive rounds (§7.2, D8)."""

    def __init__(self, window: int, threshold: float = 0.9):
        self.window, self.threshold = window, threshold
        self.run_length = 0
        self.first_round = None  # first round of the first qualifying window

    def update(self, round_idx: int, modal_share: float):
        if modal_share == modal_share and modal_share >= self.threshold:
            self.run_length += 1
            if self.run_length >= self.window and self.first_round is None:
                self.first_round = round_idx - self.window + 1
        else:
            self.run_length = 0

    @property
    def reached(self) -> bool:
        return self.first_round is not None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def summarize(population: list[dict], interactions: list[dict], config, labels) -> dict:
    """Run-level outcomes (§7.2)."""
    n = len(population)
    if n == 0:
        return {"n_rounds_completed": 0}
    tracker = ConsensusTracker(config.consensus_window)
    for r in population:
        tracker.update(int(r["round"]), _f(r["state_modal_share"]))
    tpc = {int(r["round"]): _f(r["t_pc_mean"]) for r in population}
    last = population[-max(1, int(math.ceil(0.2 * n))):]
    last_rounds = {int(r["round"]) for r in last}

    shares = {lab: [] for lab in labels}
    # mean state share per label over the last 20 % of rounds
    state_by_round = _state_shares_by_round(interactions, labels)
    for rd in last_rounds:
        for lab in labels:
            shares[lab].append(state_by_round.get(rd, {}).get(lab, 0.0))
    mean_share = {lab: (float(np.mean(v)) if v else 0.0) for lab, v in shares.items()}
    final_label = max(sorted(mean_share), key=lambda k: mean_share[k])
    fragmented = sum(1 for v in mean_share.values() if v >= 0.3) >= 2

    choices_last = [r["choice"] for r in interactions if int(r["round"]) in last_rounds and r["choice"]]
    n_choices = sum(1 for _ in interactions)
    n_invalid = sum(1 for r in interactions if r["valid"] in (False, "False", "false", 0, "0"))
    dyads = {(r["round"], r["dyad_id"]) for r in interactions}
    void_dyads = {(r["round"], r["dyad_id"]) for r in interactions if r["void"] in (True, "True", "true", 1, "1")}
    invalid_rate = n_invalid / n_choices if n_choices else 0.0
    switch = [_f(r["switch_rate"]) for r in last]
    switch = [x for x in switch if x == x]
    return {
        "n_rounds_completed": n,
        "consensus": tracker.reached,
        "T_consensus_round": tracker.first_round,
        "T_consensus_t_pc": tpc.get(tracker.first_round) if tracker.reached else None,
        "consensus_threshold": tracker.threshold,
        "consensus_window": tracker.window,
        "fragmentation": fragmented,
        "final_modal_label": final_label,
        "final_modal_share": mean_share[final_label],
        "final_label_shares": mean_share,
        "n_unique_last20pct": len(set(choices_last)),
        "mean_switch_rate_last20pct": float(np.mean(switch)) if switch else None,
        "invalid_rate": invalid_rate,
        "void_rate": len(void_dyads) / len(dyads) if dyads else 0.0,
        "flag_invalid": invalid_rate > config.invalid_rate_flag,
        "exclude_invalid": invalid_rate > config.invalid_rate_exclude,
        "final_state_modal_share": _f(population[-1]["state_modal_share"]),
        "final_state_modal_label": population[-1]["state_modal_label"],
    }


def _state_shares_by_round(interactions, labels) -> dict:
    state, out, by_round = {}, {}, {}
    for r in interactions:
        by_round.setdefault(int(r["round"]), []).append(r)
    for rd in sorted(by_round):
        for r in by_round[rd]:
            if r["choice"]:
                state[r["agent_id"]] = r["choice"]
        c = Counter(state.values())
        tot = sum(c.values())
        out[rd] = {lab: c.get(lab, 0) / tot for lab in labels} if tot else {}
    return out


# ------------------------------------------------------------ Study 0 ------
def prior_from_calibration(interactions: list[dict], labels) -> dict:
    """p0(label), p0(position) and the gate (SPEC §3.1)."""
    from scipy.stats import chisquare

    valid = [r for r in interactions if r["choice"]]
    K = len(labels)
    lab_counts = Counter(r["choice"] for r in valid)
    pos_counts = Counter(int(r["choice_position"]) for r in valid)
    n = len(valid)
    p0 = [lab_counts.get(lab, 0) / n if n else 1 / K for lab in labels]
    p_pos = [pos_counts.get(i, 0) / n if n else 1 / K for i in range(K)]
    obs = [lab_counts.get(lab, 0) for lab in labels]
    pval = float(chisquare(obs).pvalue) if n else float("nan")
    ratio = (max(obs) / min(obs)) if n and min(obs) > 0 else float("inf")
    reasons = []
    if n and max(p0) > 0.25:
        reasons.append("a label has p0 > 0.25")
    if n and pval < 0.01 and ratio > 3:
        reasons.append("chi-square vs uniform p < 0.01 with max/min ratio > 3")
    return {"n_valid": n, "n_total": len(interactions), "labels": list(labels), "p0": p0,
            "p0_position": p_pos, "chi2_p": pval, "max_min_ratio": ratio,
            "invalid_rate": 1 - n / len(interactions) if interactions else 0.0,
            "flagged": bool(reasons), "flag_reasons": reasons,
            # Use p0_smoothed as a run's config p0 (add-0.5 smoothing avoids zeros).
            "p0_smoothed": [(c + 0.5) / (n + 0.5 * K) for c in obs] if n else [1 / K] * K}


# ------------------------------------------------------------ H3 export ---
def choice_model_rows(interactions: list[dict], labels, p0, partner_visible: bool = True) -> list[dict]:
    """Long-format rows for the conditional logit (§7.4): one row per
    (choice, candidate label). Exposure variables use only the records that
    were actually rendered into that prompt (memory_records_included)."""
    import json
    by_agent: dict[str, dict[int, dict]] = {}
    for r in interactions:
        by_agent.setdefault(r["agent_id"], {})[int(r["round"])] = r
    out = []
    for r in interactions:
        if not r["choice"]:
            continue
        agent_rows = by_agent[r["agent_id"]]
        included = json.loads(r["memory_records_included"]) if isinstance(r["memory_records_included"], str) else r["memory_records_included"]
        shown = json.loads(r["label_order_shown"]) if isinstance(r["label_order_shown"], str) else r["label_order_shown"]
        recs = [agent_rows[rd] for rd in included if rd in agent_rows]
        prev_rounds = sorted(rd for rd, x in agent_rows.items() if rd < int(r["round"]) and x["choice"])
        own_prev = agent_rows[prev_rounds[-1]]["choice"] if prev_rounds else None
        for k, lab in enumerate(labels):
            out.append({
                "run_id": r["run_id"], "round": r["round"], "agent_id": r["agent_id"], "label": lab,
                "chosen": int(r["choice"] == lab),
                "own_prev": int(own_prev == lab),
                "own_count_H": sum(1 for x in recs if x["choice"] == lab),
                "partner_count_H": (sum(1 for x in recs if x["partner_choice"] == lab)
                                    if partner_visible else 0),
                "log_p0": math.log(p0[k]) if p0[k] > 0 else float("-inf"),
                "position": shown.index(lab) if lab in shown else None,
            })
    return out
