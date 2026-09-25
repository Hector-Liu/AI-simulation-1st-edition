"""The study's named conditions ("rooms"), SPEC v2 §3.3 and §3.3a.

A config that carries a `cell_id` from this table must match the room's
signature; validation rejects mismatches, so the Study Plan never mixes
conditions under one room.
"""
from __future__ import annotations

ROOMS = {
    # ---- main design: 2 (reward) x 3 (memory) ------------------------------
    "B0": dict(group="main", reward="none", memory="none", title="No reward · no memory",
               short="Prior baseline", tests="What the shared prior alone produces. Also the source of the matched label prior for the no-reward arm."),
    "B1": dict(group="main", reward="none", memory="own_only", title="No reward · own choices only",
               short="Self-persistence control", tests="Convergence from repeating oneself, with no social information."),
    "B2": dict(group="main", reward="none", memory="own_and_partner", title="No reward · own + partner choices",
               short="Key cell", tests="Does a shared label emerge from interaction without any incentive? Compare with B1 (H2a)."),
    "A0": dict(group="main", reward="local_match", memory="none", title="Reward · no memory",
               short="Focal-point control", tests="Coordination from the prior alone. Source of the matched label prior for the reward arm."),
    "A1": dict(group="main", reward="local_match", memory="own_only", title="Reward · own choices only",
               short="Self-persistence control", tests="Reward text, but no social information in memory."),
    "A2": dict(group="main", reward="local_match", memory="own_and_partner", title="Reward · own + partner choices",
               short="Rewarded naming game", tests="Convention formation with a pair-level reward. Compare with A1 (H1a)."),
    # ---- optional control rooms -------------------------------------------
    "B2R": dict(group="control", reward="none", memory="own_and_partner", partner_source="prior_replay",
                title="No reward · replayed partner", short="Loop control (prior replay)", prior_room="B0",
                tests="Same prompts as B2, but the partner label shown is drawn from the prior, so agents never influence each other. Does convergence need the interaction loop? (H7)"),
    "A2R": dict(group="control", reward="local_match", memory="own_and_partner", partner_source="prior_replay",
                title="Reward · replayed partner", short="Loop control (prior replay)", prior_room="A0",
                tests="As B2R, reward arm. Compare with A2 (H7)."),
    "NS2": dict(group="control", reward="none", memory="own_and_partner", framing="nonsocial",
                title="No reward · 'reference label' framing", short="Social vs exposure control",
                tests="Same loop as B2, but the partner's choice is presented as a 'reference label', not another participant. Social conformity or plain in-context copying? (H8)"),
}
ROOM_ORDER = list(ROOMS)


def room_fields(room_id: str) -> dict:
    """Config fields fixed by a room."""
    r = ROOMS[room_id]
    d = {
        "cell_id": room_id,
        "experiment_id": "rewarded_naming" if r["reward"] == "local_match" else "no_reward_convergence",
        "pairing": "random_dyad",
        "reward_mode": r["reward"],
        "feedback_mode": "choices_only",
        "show_own_agent_id": False,
        "template_version": "v2",
        "policy_default": "llm",
        "partner_source": r.get("partner_source", "actual"),
        "framing": r.get("framing", "social"),
    }
    if r["memory"] == "none":
        d["memory_mode"] = "none"
    else:
        d["memory_mode"] = "own_interactions_only"
        d["memory_content"] = r["memory"]
    return d


def room_mismatches(c) -> list[str]:
    """Why config `c` does not belong to the room named by its cell_id."""
    if c.cell_id is None or c.cell_id not in ROOMS:
        return []
    want = room_fields(c.cell_id)
    got = {
        "experiment_id": c.experiment_id, "pairing": c.pairing, "reward_mode": c.reward_mode,
        "feedback_mode": c.feedback_mode, "show_own_agent_id": c.show_own_agent_id,
        "template_version": c.template_version, "policy_default": c.policy_default,
        "partner_source": c.partner_source, "framing": c.framing, "memory_mode": c.memory_mode,
    }
    out = [f"{k}={got[k]!r} (room {c.cell_id} needs {v!r})" for k, v in want.items() if k in got and got[k] != v]
    if c.memory_mode != "none" and c.memory_content != want.get("memory_content"):
        out.append(f"memory_content={c.memory_content!r} (room {c.cell_id} needs {want['memory_content']!r})")
    if c.committed_minority is not None:
        out.append(f"room {c.cell_id} does not allow a committed minority")
    return [f"cell_id {c.cell_id}: {m}" for m in out]
