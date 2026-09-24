"""The ONLY prompt constructor (SPEC §5.5).

Reads only the focal agent's private buffer and the config. It must never
import the store or metrics (test 14): the agent path has no view of the
population.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from .agents import Agent

TEMPLATE_VERSION = "v1"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / TEMPLATE_VERSION
_TEMPLATE_FILES = ("base.txt", "interaction_block.txt", "payoff_block.txt", "buffer_lines.json")


@lru_cache(maxsize=None)
def _template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text()


@lru_cache(maxsize=None)
def _lines() -> dict:
    return json.loads(_template("buffer_lines.json"))


def template_hashes() -> dict:
    return {n: hashlib.sha256(_template(n).encode()).hexdigest() for n in _TEMPLATE_FILES}


def _k(n_back: int) -> str:
    lines = _lines()
    return lines["k.latest"] if n_back == 1 else lines["k.ago"].format(n=n_back)


def _record_line(rec: dict, n_back: int, config) -> str:
    lines = _lines()
    content = config.memory_content
    fb = config.feedback_mode
    if content == "own_only":
        key = "own_only.numeric_score" if fb == "numeric_score" else "own_only.choices_only"
    else:
        key = f"own_and_partner.{fb}"
    match_text = lines["match_text.same" if rec["self_label"] == rec["partner_label"] else "match_text.different"]
    return lines[key].format(k=_k(n_back), self=rec["self_label"], partner=rec["partner_label"],
                             points=rec.get("points"), match_text=match_text)


def render_buffer(agent: Agent, config) -> tuple[str, list[int]]:
    """Render the agent's own records with relative indices only (R10)."""
    if not config.memory_on or not agent.buffer:
        return _lines()["empty_buffer"], []
    records = list(agent.buffer)  # oldest -> newest
    n = len(records)
    indexed = [(n - i, rec) for i, rec in enumerate(records)]  # (n_back, rec)
    if config.memory_order == "newest_first":
        indexed.reverse()
    text = "\n".join(_record_line(rec, n_back, config) for n_back, rec in indexed)
    return text, [rec["round"] for _, rec in indexed]


def build_agent_prompt(agent: Agent, config, round_idx: int, order_rng, labels) -> tuple[str, list[str], list[int]]:
    """Render one agent's prompt.

    Returns (prompt_text, label_order_shown, memory_round_ids_included). The
    label order is drawn from `order_rng` independently for every prompt.
    `round_idx` is accepted for logging symmetry but never rendered.
    """
    del round_idx
    order = [labels[i] for i in order_rng.permutation(len(labels))]
    lines = _lines()

    interaction = "" if config.pairing == "isolated" else _template("interaction_block.txt")
    payoff = ""
    if config.reward_mode == "local_match" and config.pairing != "isolated":
        cumulative = ""
        if config.show_cumulative_points:
            cumulative = lines["cumulative_line"].format(total=agent.cum_points) + "\n"
        payoff = (_template("payoff_block.txt")
                  .replace("{cumulative_line}\n", cumulative)
                  .replace("{match_payoff}", str(config.payoff.match))
                  .replace("{mismatch_payoff}", str(config.payoff.mismatch)))

    buffer_text, included = render_buffer(agent, config)
    base = _template("base.txt")
    if not config.show_own_agent_id:
        base = base.replace("You are participant {agent_id}.\n", "")
    prompt = (base
              .replace("{agent_id}", agent.agent_id)
              .replace("{stimulus_id}", "s0")
              .replace("{interaction_block}", interaction)
              .replace("{payoff_block}", payoff)
              .replace("{shuffled_labels}", "\n".join(f"- {lab}" for lab in order))
              .replace("{own_buffer_or_none}", buffer_text))
    return prompt.rstrip("\n"), order, included
