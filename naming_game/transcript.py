"""Human-readable interaction transcripts (analyst side; never shown to agents).

One row per dyad: who was paired with whom in each round, what each chose,
whether they matched, and (for LLM agents) the raw model output.
"""
from __future__ import annotations

import csv
import io
import json

from .store import RunStore

DYAD_COLUMNS = ["round", "dyad_id", "agent_a", "choice_a", "agent_b", "choice_b", "match", "void",
                "partner_source", "shown_to_a", "shown_to_b", "match_a", "match_b",
                "points_a", "points_b", "policy_a", "policy_b", "minority_a", "minority_b",
                "raw_output_a", "raw_output_b", "attempts_a", "attempts_b", "within_block"]


def dyad_rows(store: RunStore, round_from: int | None = None, round_to: int | None = None) -> list[dict]:
    rows = store.read_csv("interactions.csv")
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        rd = int(r["round"])
        if (round_from is not None and rd < round_from) or (round_to is not None and rd > round_to):
            continue
        groups.setdefault((rd, int(r["dyad_id"])), []).append(r)
    out = []
    for (rd, did), members in sorted(groups.items()):
        a = members[0]
        b = members[1] if len(members) > 1 else None
        out.append({
            "round": rd, "dyad_id": did,
            "agent_a": a["agent_id"], "choice_a": a["choice"] or "(invalid)",
            "agent_b": b["agent_id"] if b else "", "choice_b": (b["choice"] or "(invalid)") if b else "",
            "match": a["match"], "void": a["void"],
            "partner_source": a.get("partner_source") or "actual",
            "shown_to_a": a.get("partner_choice", ""), "shown_to_b": b.get("partner_choice", "") if b else "",
            "match_a": a["match"], "match_b": b["match"] if b else "",
            "points_a": a["points"], "points_b": b["points"] if b else "",
            "policy_a": a["policy"], "policy_b": b["policy"] if b else "",
            "minority_a": a["is_minority"], "minority_b": b["is_minority"] if b else "",
            "raw_output_a": a["raw_output"], "raw_output_b": b["raw_output"] if b else "",
            "attempts_a": a["attempts"], "attempts_b": b["attempts"] if b else "",
            "within_block": a["within_block"],
        })
    return out


def transcript_csv(store: RunStore) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=DYAD_COLUMNS)
    w.writeheader()
    w.writerows(dyad_rows(store))
    return buf.getvalue()


def transcript_text(store: RunStore, include_prompts: bool = False) -> str:
    cfg = store.read_json("config.json") or {}
    man = store.read_json("manifest.json") or {}
    pop = {int(p["round"]): p for p in store.read_csv("population.csv")}
    calls: dict[tuple, list[dict]] = {}
    if include_prompts:
        for c in store.read_jsonl("calls.jsonl"):
            calls.setdefault((int(c["round"]), c["agent_id"]), []).append(c)
    model = cfg.get("model") or {}
    lines = [
        f"Naming game transcript — run {cfg.get('run_id')}",
        f"experiment: {cfg.get('experiment_id')} | seed {cfg.get('seed')} | label set {cfg.get('label_set_id')} "
        f"| {cfg.get('n_agents')} agents | {cfg.get('n_rounds')} rounds | pairing {cfg.get('pairing')}",
        f"memory: {cfg.get('memory_mode')} ({cfg.get('memory_content')}, H={cfg.get('memory_horizon_H')}) "
        f"| reward: {cfg.get('reward_mode')} | feedback: {cfg.get('feedback_mode')}",
        f"policy: {cfg.get('policy_default')}" + (f" | model: {model.get('provider')}:{model.get('model_id')}" if model else ""),
        f"labels: {' '.join(man.get('labels', []))}",
        f"status: {man.get('status')} | config_hash {cfg.get('config_hash', '')[:16]}",
        "",
        "Each line: agent (choice) × agent (choice) → outcome. 'void' = an invalid answer after retry;"
        if cfg.get("partner_source") != "prior_replay" else
        "Replayed-partner run: each agent was shown a label drawn from the prior, not its partner's choice.",
        "a void pairing writes nothing to either agent's memory.",
    ]
    current = None
    for d in dyad_rows(store):
        rd = d["round"]
        if rd != current:
            if current is not None and current in pop:
                lines.append(_pop_line(pop[current]))
            lines += ["", f"── Round {rd} " + "─" * 40]
            current = rd
        if d["agent_b"] and d["partner_source"] == "prior_replay":
            def side(agent, choice, shown, m):
                res = "void" if d["void"] == "True" else ("same" if m == "True" else "different")
                return f"{agent} chose {choice}, was shown {shown} → {res}"
            lines.append(f"  {side(d['agent_a'], d['choice_a'], d['shown_to_a'], d['match_a'])} | "
                         f"{side(d['agent_b'], d['choice_b'], d['shown_to_b'], d['match_b'])}")
        elif d["agent_b"]:
            outcome = "VOID" if d["void"] == "True" else ("same label" if d["match"] == "True" else "different labels")
            pts = f"  points {d['points_a']}/{d['points_b']}" if d["points_a"] not in ("", None) else ""
            lines.append(f"  {d['agent_a']} ({d['choice_a']}) × {d['agent_b']} ({d['choice_b']}) → {outcome}{pts}")
        else:
            lines.append(f"  {d['agent_a']} → {d['choice_a']}")
        if include_prompts:
            for aid in filter(None, (d["agent_a"], d["agent_b"])):
                for c in calls.get((rd, aid), []):
                    lines.append(f"    ┌ prompt to {aid} (attempt {c['attempt']})")
                    lines += [f"    │ {ln}" for ln in c["prompt_text"].splitlines()]
                    lines.append(f"    └ raw output: {json.dumps(c['raw_output'])}"
                                 f" → {'parsed ' + c['parsed_label'] if c['valid'] else 'INVALID'}")
    if current is not None and current in pop:
        lines.append(_pop_line(pop[current]))
    return "\n".join(lines) + "\n"


def _pop_line(p: dict) -> str:
    try:
        share = f"{float(p['state_modal_share']):.2f}"
    except (TypeError, ValueError):
        share = "–"
    return f"  population state after this round: most common label {p['state_modal_label']} ({share} of agents)"
