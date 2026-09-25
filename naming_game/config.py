"""Experiment configuration (SPEC §5.2).

`ExperimentConfig` is immutable. Its canonical JSON (sorted keys, no run_id)
is hashed to `config_hash`, so two runs with the same design and seed share a
hash even though their run ids differ.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "2"
PHASES = ("pilot", "confirmatory", "exploratory", "test")
ALLOWED_N = (12, 24, 48)
CALIBRATION_N = 20  # Study 0 uses 20 sterile agents (SPEC §3.1)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TopologyParams(_Frozen):
    n_blocks: int = 2
    p_within: float = 0.9
    hub_id: str = "a00"


class Payoff(_Frozen):
    match: int = 100
    mismatch: int = -50


class PolicyParams(_Frozen):
    q: Optional[float] = None


class CommittedMinority(_Frozen):
    frac: float
    start_rule: Literal["after_consensus", "round"] = "after_consensus"
    start_round: int = 50
    # Planted history (E5): the scripted agents are released at end_round.
    end_round: Optional[int] = None
    # random_nonmodal (v2 default) avoids tying the minority label to a low prior.
    label_rule: Literal["random_nonmodal", "least_used_20"] = "random_nonmodal"


class ModelSpec(_Frozen):
    provider: Literal["anthropic", "openai", "deepseek", "mock"]
    model_id: str
    # None = provider default sampling (D4). 0 is rejected (R15).
    temperature: Optional[float] = None
    max_tokens_cap: int = 16
    # Only for provider = mock: "uniform" | "majority" and an invalid-output rate.
    mock_mode: Literal["uniform", "majority"] = "uniform"
    mock_invalid_rate: float = 0.0
    # "auto" pins to the version returned by the first call; an exact string
    # pins to that version. A different version aborts the run.
    pin_version: Optional[str] = None


class RetryPolicy(_Frozen):
    parse_retries: int = 1
    api_retries: int = 5
    backoff_s: float = 2.0


class ExperimentConfig(_Frozen):
    schema_version: str = SCHEMA_VERSION
    template_version: Literal["v1", "v2"] = "v2"
    cell_id: Optional[str] = None  # a room from rooms.ROOMS, or None for ad-hoc runs
    phase: Literal["pilot", "confirmatory", "exploratory", "test"] = "pilot"
    framing: Literal["social", "nonsocial"] = "social"
    partner_source: Literal["actual", "prior_replay"] = "actual"
    experiment_id: Literal["rewarded_naming", "no_reward_convergence", "prior_calibration", "null_model"]
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    seed: int
    label_set_id: str
    n_agents: int = 24
    n_rounds: int = 300
    pairing: Literal["random_dyad", "star", "community", "isolated"] = "random_dyad"
    topology_params: TopologyParams = TopologyParams()
    memory_mode: Literal["none", "own_interactions_only"] = "own_interactions_only"
    memory_content: Literal["own_and_partner", "own_only"] = "own_and_partner"
    memory_horizon_H: Optional[int] = None  # resolved to 5 when memory is on
    memory_order: Literal["newest_first", "oldest_first"] = "newest_first"
    reward_mode: Literal["none", "local_match"]
    feedback_mode: Literal["choices_only", "match_indicator", "numeric_score"]
    payoff: Optional[Payoff] = None  # resolved to {100, -50} when reward is on
    show_cumulative_points: Optional[bool] = None  # resolved to True with numeric_score
    label_pool_size: int = 10
    n_stimuli: int = 1
    show_own_agent_id: bool = False  # hidden by default (v2, P2-5)
    policy_default: Literal["llm", "prior_sample", "voter", "majority_H"] = "llm"
    policy_params: PolicyParams = PolicyParams()
    committed_minority: Optional[CommittedMinority] = None
    # Label prior used by rule policies and first moves (None = uniform).
    # Fill from a prior-calibration run of the same label set (SPEC §3.1).
    p0: Optional[tuple[float, ...]] = None
    p0_source: str = ""  # where p0 came from, e.g. "derived:B0:P1:n=3 runs" (hashed with the config)
    yoked_source_run_id: Optional[str] = None
    robustness_cell: bool = False  # required for match_indicator (R5)
    model: Optional[ModelSpec] = None
    max_concurrency: int = 24
    retry: RetryPolicy = RetryPolicy()
    invalid_rate_flag: float = 0.02
    invalid_rate_exclude: float = 0.05
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _resolve_defaults(cls, data):
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if d.get("memory_mode", "own_interactions_only") != "none" and d.get("memory_horizon_H") is None:
            d["memory_horizon_H"] = 5
        if d.get("reward_mode") == "local_match" and d.get("payoff") is None:
            d["payoff"] = {"match": 100, "mismatch": -50}
        if d.get("feedback_mode") == "numeric_score" and d.get("show_cumulative_points") is None:
            d["show_cumulative_points"] = True
        return d

    @model_validator(mode="after")
    def _validate(self):
        errors = validation_errors(self)
        if errors:
            raise ValueError("; ".join(errors))
        return self

    # ---- derived -------------------------------------------------------
    @property
    def memory_on(self) -> bool:
        return self.memory_mode != "none"

    @property
    def H(self) -> int:
        return self.memory_horizon_H or 0

    @property
    def agent_ids(self) -> list[str]:
        return [f"a{i:02d}" for i in range(self.n_agents)]

    @property
    def consensus_window(self) -> int:
        return max(10, int(round(0.05 * self.n_rounds)))

    def canonical_json(self) -> str:
        d = self.model_dump(mode="json")
        d.pop("run_id", None)
        d.pop("notes", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    @property
    def config_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


def validation_errors(c: ExperimentConfig) -> list[str]:
    """All illegal combinations from SPEC §5.2 / §8 test 10."""
    e: list[str] = []
    calib = c.experiment_id == "prior_calibration"

    # population / topology
    if c.pairing == "isolated":
        if not calib:
            e.append("pairing=isolated is only allowed for prior_calibration")
        if c.n_agents not in ALLOWED_N + (CALIBRATION_N,):
            e.append(f"n_agents must be one of {ALLOWED_N + (CALIBRATION_N,)} for calibration")
    else:
        if calib:
            e.append("prior_calibration requires pairing=isolated")
        if c.n_agents not in ALLOWED_N:
            e.append(f"n_agents must be one of {ALLOWED_N}")
        if c.pairing in ("random_dyad", "community") and c.n_agents % 2:
            e.append("n_agents must be even for random_dyad and community")
    if c.seed < 0:
        e.append("seed must be >= 0")
    if c.n_rounds < 1:
        e.append("n_rounds must be >= 1")
    tp = c.topology_params
    if not (0 < tp.p_within <= 1):
        e.append("topology_params.p_within must be in (0, 1]")
    if c.pairing == "community" and not (2 <= tp.n_blocks <= max(2, c.n_agents // 2)):
        e.append("topology_params.n_blocks must be >= 2 and leave >= 2 agents per block")
    if c.pairing == "star" and tp.hub_id not in c.agent_ids:
        e.append(f"topology_params.hub_id {tp.hub_id!r} is not an agent id")

    # memory
    if c.memory_mode == "none":
        if c.memory_horizon_H is not None:
            e.append("memory_horizon_H must be unset when memory_mode=none (H=0 is not a valid alias)")
        if c.feedback_mode != "choices_only":
            e.append("memory_mode=none requires feedback_mode=choices_only")
    else:
        if c.memory_horizon_H is None or c.memory_horizon_H < 1:
            e.append("memory_horizon_H must be >= 1 when memory is on")
    if calib and (c.memory_mode != "none" or c.reward_mode != "none"):
        e.append("prior_calibration requires memory_mode=none and reward_mode=none")

    # reward / feedback
    if c.reward_mode == "none":
        if c.feedback_mode == "numeric_score":
            e.append("reward_mode=none cannot use feedback_mode=numeric_score")
        if c.payoff is not None:
            e.append("payoff must be unset when reward_mode=none")
    if c.feedback_mode == "match_indicator":
        if not c.robustness_cell:
            e.append("feedback_mode=match_indicator is a robustness factor only (set robustness_cell=true)")
        if c.memory_content == "own_only":
            e.append("match_indicator cannot be combined with memory_content=own_only (it reveals partner information)")
    if c.show_cumulative_points and c.feedback_mode != "numeric_score":
        e.append("show_cumulative_points requires feedback_mode=numeric_score")

    # v2 conditions
    if c.template_version == "v1" and c.framing != "social":
        e.append("framing=nonsocial requires template_version v2")
    if c.framing == "nonsocial":
        if c.reward_mode != "none" or not c.memory_on or c.memory_content != "own_and_partner" or c.pairing == "isolated":
            e.append("framing=nonsocial requires no reward, memory on with own_and_partner, and partners")
    if c.partner_source == "prior_replay":
        if not c.memory_on or c.memory_content != "own_and_partner" or c.pairing != "random_dyad":
            e.append("partner_source=prior_replay requires random_dyad pairing and own_and_partner memory")
        if c.p0 is None:
            e.append("partner_source=prior_replay needs a label prior p0 (derive it from room B0/A0, or set a uniform prior explicitly)")
        if c.feedback_mode == "numeric_score":
            e.append("partner_source=prior_replay is defined for choices_only feedback")
    from .rooms import ROOMS, room_mismatches
    if c.cell_id is not None and c.cell_id not in ROOMS:
        e.append(f"cell_id {c.cell_id!r} is not a known room")
    e.extend(room_mismatches(c))
    if c.model is not None and c.model.provider == "mock" and c.phase in ("pilot", "confirmatory"):
        e.append("mock-model runs must use phase=test or exploratory (they are never study data)")

    # labels / stimuli
    if not (2 <= c.label_pool_size <= 20):
        e.append("label_pool_size must be between 2 and 20")
    if c.n_stimuli != 1:
        e.append("n_stimuli > 1 is not implemented yet")
    try:
        from .labels import load_label_sets
        sets = load_label_sets()
        if c.label_set_id not in sets:
            e.append(f"label_set_id {c.label_set_id!r} not in the frozen label store")
        elif len(sets[c.label_set_id]["labels"]) != c.label_pool_size:
            e.append("label_pool_size must equal the size of the label set")
    except FileNotFoundError:
        e.append("label store not found; run `python -m naming_game.cli labels --freeze` first")

    if c.p0 is not None:
        if len(c.p0) != c.label_pool_size:
            e.append("p0 must have one probability per label")
        elif any(x < 0 for x in c.p0) or abs(sum(c.p0) - 1) > 1e-6:
            e.append("p0 must be non-negative and sum to 1")

    # policies
    if c.policy_default == "voter":
        q = c.policy_params.q
        if q is None or not (0 <= q <= 1):
            e.append("policy voter requires policy_params.q in [0, 1]")
    if c.policy_default == "llm":
        if c.model is None:
            e.append("policy llm requires a model")
    if c.experiment_id == "null_model" and c.policy_default == "llm":
        e.append("experiment_id=null_model requires a rule policy")
    if c.model is not None:
        if c.model.temperature is not None and c.model.temperature <= 0:
            e.append("temperature must be > 0 (T=0 collapses the baseline to the prior mode)")
        if c.model.max_tokens_cap < 1:
            e.append("max_tokens_cap must be >= 1")
        if not (0 <= c.model.mock_invalid_rate < 1):
            e.append("mock_invalid_rate must be in [0, 1)")
    if c.max_concurrency < 1:
        e.append("max_concurrency must be >= 1")

    # minority / yoked
    cm = c.committed_minority
    if cm is not None:
        if calib or c.pairing == "isolated":
            e.append("committed_minority is not allowed in calibration")
        if not (0 < cm.frac < 0.5):
            e.append("committed_minority.frac must be in (0, 0.5)")
        if cm.end_round is not None and cm.end_round <= (cm.start_round if cm.start_rule == "round" else 0):
            e.append("committed_minority.end_round must come after the start")
        if (0 < cm.frac < 0.5) and round(cm.frac * c.n_agents) < 1:
            e.append("committed_minority.frac * n_agents rounds to 0 agents")
        if c.pairing == "star":
            e.append("committed_minority is not supported with star pairing")
    if c.yoked_source_run_id is not None:
        e.append("yoked exposure (B+3) is not implemented yet")
    return e


def load_config(path) -> ExperimentConfig:
    with open(path) as f:
        return ExperimentConfig(**json.load(f))
