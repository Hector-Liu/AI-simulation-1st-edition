"""Agents: a private ring buffer of own interactions, plus rule policies.

An Agent holds no reference to other agents, the population, or the analyst
store. Rule policies (SPEC §3.4) see exactly what an LLM agent would see: the
records rendered into its prompt (partner labels are hidden under own_only).
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class Agent:
    agent_id: str
    policy: str  # llm | prior_sample | voter | majority_H | scripted_fixed
    capacity: int  # H; 0 when memory is off
    buffer: deque = field(default=None)  # records, oldest -> newest
    cum_points: int = 0
    is_minority: bool = False
    fixed_label: Optional[str] = None

    def __post_init__(self):
        if self.buffer is None:
            self.buffer = deque(maxlen=self.capacity) if self.capacity > 0 else deque(maxlen=0)

    def snapshot(self) -> tuple:
        """Byte-comparable view of private state (used by isolation tests)."""
        return (tuple(tuple(sorted(r.items())) for r in self.buffer), self.cum_points,
                self.is_minority, self.fixed_label, self.policy)


def visible_records(agent: Agent, config) -> list[dict]:
    """Records as the agent sees them in its prompt, newest last."""
    if not config.memory_on:
        return []
    out = []
    for r in agent.buffer:
        rec = {"self_label": r["self_label"]}
        if config.memory_content == "own_and_partner":
            rec["partner_label"] = r["partner_label"]
        out.append(rec)
    return out


def _sample_p0(labels, p0, rng) -> str:
    return labels[rng.choice(len(labels), p=p0)]


def choose_rule(agent: Agent, config, labels, p0, rng: np.random.Generator) -> str:
    """Rule-policy choice. Reads only the agent's own visible records and p0."""
    policy = agent.policy
    recs = visible_records(agent, config)
    if policy == "scripted_fixed":
        return agent.fixed_label
    if policy == "prior_sample" or not recs:
        return _sample_p0(labels, p0, rng)
    own_last = recs[-1]["self_label"]
    if policy == "voter":
        q = config.policy_params.q
        partner = recs[-1].get("partner_label")
        if partner is not None and rng.random() < q:
            return partner
        return own_last
    if policy == "majority_H":
        partners = [r["partner_label"] for r in recs if "partner_label" in r]
        if not partners:
            return own_last
        counts = Counter(partners)
        top = max(counts.values())
        tied = sorted(lab for lab, c in counts.items() if c == top)
        if len(tied) == 1:
            return tied[0]
        if own_last in tied:
            return own_last
        idx = [labels.index(t) for t in tied]
        w = np.asarray([p0[i] for i in idx], dtype=float)
        return tied[rng.choice(len(tied), p=w / w.sum())]
    raise ValueError(f"not a rule policy: {policy}")
