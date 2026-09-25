"""The ONLY prompt constructor (SPEC §5.5; v2 templates: SPEC v2 §4).

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

TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"
TEMPLATE_VERSION = "v2"  # default for new configs
_TEMPLATE_FILES = {
    "v1": ("base.txt", "interaction_block.txt", "payoff_block.txt", "buffer_lines.json"),
    "v2": ("base.txt", "interaction_block.txt", "interaction_block_own_only.txt",
           "interaction_block_nonsocial.txt", "payoff_block.txt", "buffer_lines.json"),
}


@lru_cache(maxsize=None)
def _template(version: str, name: str) -> str:
    return (TEMPLATE_ROOT / version / name).read_text()


@lru_cache(maxsize=None)
def _lines(version: str) -> dict:
    return json.loads(_template(version, "buffer_lines.json"))


def template_hashes(version: str = TEMPLATE_VERSION) -> dict:
    return {n: hashlib.sha256(_template(version, n).encode()).hexdigest() for n in _TEMPLATE_FILES[version]}


def _k(lines: dict, n_back: int) -> str:
    return lines["k.latest"] if n_back == 1 else lines["k.ago"].format(n=n_back)


def _record_line(rec: dict, n_back: int, config, lines: dict) -> str:
    fb = config.feedback_mode
    if config.memory_content == "own_only":
        key = "own_only.numeric_score" if fb == "numeric_score" else "own_only.choices_only"
    elif getattr(config, "framing", "social") == "nonsocial":
        key = "own_and_partner.choices_only.nonsocial"
    else:
        key = f"own_and_partner.{fb}"
    match_text = lines["match_text.same" if rec["self_label"] == rec["partner_label"] else "match_text.different"]
    return lines[key].format(k=_k(lines, n_back), self=rec["self_label"], partner=rec["partner_label"],
                             points=rec.get("points"), match_text=match_text)


def render_buffer(agent: Agent, config) -> tuple[str, list[int]]:
    """Render the agent's own records with relative indices only (R10)."""
    lines = _lines(config.template_version)
    if not config.memory_on or not agent.buffer:
        return lines["empty_buffer"], []
    records = list(agent.buffer)  # oldest -> newest
    n = len(records)
    indexed = [(n - i, rec) for i, rec in enumerate(records)]  # (n_back, rec)
    if config.memory_order == "newest_first":
        indexed.reverse()
    text = "\n".join(_record_line(rec, n_back, config, lines) for n_back, rec in indexed)
    return text, [rec["round"] for _, rec in indexed]


def interaction_block(config) -> str:
    """Which interaction paragraph a config renders (empty for isolated agents)."""
    v = config.template_version
    if config.pairing == "isolated":
        return ""
    if v == "v2":
        if getattr(config, "framing", "social") == "nonsocial":
            return _template(v, "interaction_block_nonsocial.txt")
        if config.memory_on and config.memory_content == "own_only":
            return _template(v, "interaction_block_own_only.txt")
    return _template(v, "interaction_block.txt")


def build_agent_prompt(agent: Agent, config, round_idx: int, order_rng, labels) -> tuple[str, list[str], list[int]]:
    """Render one agent's prompt.

    Returns (prompt_text, label_order_shown, memory_round_ids_included). The
    label order is drawn from `order_rng` independently for every prompt.
    `round_idx` is accepted for logging symmetry but never rendered.
    """
    del round_idx
    v = config.template_version
    order = [labels[i] for i in order_rng.permutation(len(labels))]
    lines = _lines(v)

    payoff = ""
    if config.reward_mode == "local_match" and config.pairing != "isolated":
        cumulative = ""
        if config.show_cumulative_points:
            cumulative = lines["cumulative_line"].format(total=agent.cum_points) + "\n"
        payoff = (_template(v, "payoff_block.txt")
                  .replace("{cumulative_line}\n", cumulative)
                  .replace("{match_payoff}", str(config.payoff.match))
                  .replace("{mismatch_payoff}", str(config.payoff.mismatch)))

    buffer_text, included = render_buffer(agent, config)
    base = _template(v, "base.txt")
    if not config.show_own_agent_id:
        base = base.replace("You are participant {agent_id}.\n", "")
    prompt = (base
              .replace("{agent_id}", agent.agent_id)
              .replace("{stimulus_id}", "s0")
              .replace("{interaction_block}", interaction_block(config))
              .replace("{payoff_block}", payoff)
              .replace("{shuffled_labels}", "\n".join(f"- {lab}" for lab in order))
              .replace("{own_buffer_or_none}", buffer_text))
    return prompt.rstrip("\n"), order, included
