"""SPEC §8 acceptance tests 1-15. Mock model and rule policies only; no network."""
import ast
import asyncio
import csv
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from scipy.stats import binom

from conftest import make_config, run
from naming_game import prompts as prompts_mod
from naming_game.agents import Agent
from naming_game.labels import (DENY_SUBSTRINGS, get_labels, guard_prompt, label_set_hash,
                                load_label_sets, set_problems)
from naming_game.llm import MockModel
from naming_game.parser import parse_label
from naming_game.prompts import build_agent_prompt
from naming_game.scheduler import Simulation, rng_for
from naming_game.store import RunStore

PKG = Path(__file__).resolve().parents[1] / "naming_game"
LABELS = get_labels("L1")

# A spread of cells that together render every template branch.
CELLS = {
    "B_none_mem": dict(),
    "B_none_nomem": dict(memory_mode="none"),
    "B_own_only": dict(memory_content="own_only"),
    "A_reward": dict(experiment_id="rewarded_naming", reward_mode="local_match", feedback_mode="numeric_score"),
    "A_reward_nocum": dict(experiment_id="rewarded_naming", reward_mode="local_match",
                           feedback_mode="numeric_score", show_cumulative_points=False),
    "A_star": dict(experiment_id="rewarded_naming", reward_mode="local_match", feedback_mode="numeric_score",
                   pairing="star", n_rounds=40),
    "A_community": dict(experiment_id="rewarded_naming", reward_mode="local_match",
                        feedback_mode="numeric_score", pairing="community"),
    "focal_point": dict(experiment_id="rewarded_naming", reward_mode="local_match", memory_mode="none"),
    "B2_own_only_points": dict(experiment_id="rewarded_naming", reward_mode="local_match",
                               feedback_mode="numeric_score", memory_content="own_only"),
    "robust_match_indicator": dict(feedback_mode="match_indicator", robustness_cell=True),
    "oldest_first_no_id": dict(memory_order="oldest_first", show_own_agent_id=False),
    "calibration": dict(experiment_id="prior_calibration", pairing="isolated", n_agents=20,
                        memory_mode="none"),
}


async def _step(sim, t):
    return await sim.play_round(t, asyncio.Semaphore(8))


def _prompts(sim):
    return [c["prompt_text"] for c in sim.store.read_jsonl("calls.jsonl")]


@pytest.fixture(scope="module")
def cell_runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("cells")
    out = {}
    for name, ov in CELLS.items():
        sim, res = run(make_config(**ov), base)
        assert res["status"] == "completed", (name, res)
        out[name] = sim
    return out


# ---------------------------------------------------------------- 1 -------
def test_1_memory_isolation():
    for ov in (dict(), dict(pairing="star"), dict(model={"provider": "mock", "model_id": "mock",
                                                          "mock_invalid_rate": 0.3})):
        cfg = make_config(n_rounds=15, **ov)
        sim = Simulation(cfg, store=None)
        for t in range(cfg.n_rounds):
            before = {a.agent_id: a.snapshot() for a in sim.agents}
            lens = {a.agent_id: len(a.buffer) for a in sim.agents}
            asyncio.run(_step(sim, t))
            rows = {r["agent_id"]: r for r in sim._last_rows}
            for a in sim.agents:
                r = rows.get(a.agent_id)
                grew = len(a.buffer) != lens[a.agent_id] or a.snapshot() != before[a.agent_id]
                if r is None or r["void"]:
                    assert a.snapshot() == before[a.agent_id], (t, a.agent_id)
                else:
                    assert grew and a.buffer[-1]["round"] == t
                    assert a.buffer[-1]["partner_id"] == r["partner_id"]


# ---------------------------------------------------------------- 2 -------
def _expected_buffer(rows_by_agent, aid, t, cfg):
    own = [r for r in rows_by_agent[aid] if int(r["round"]) < t and r["void"] == "False"]
    return [int(r["round"]) for r in own[-cfg.H:]] if cfg.memory_on else []


def test_2_prompt_audit(cell_runs):
    for name, sim in cell_runs.items():
        cfg = sim.config
        rows = sim.store.read_csv("interactions.csv")
        by_agent = {}
        for r in rows:
            by_agent.setdefault(r["agent_id"], []).append(r)
        index = {(r["agent_id"], int(r["round"])): r for r in rows}
        for r in rows:
            aid, t = r["agent_id"], int(r["round"])
            included = json.loads(r["memory_records_included"])
            # exactly the agent's own latest H non-void interactions
            assert sorted(included) == _expected_buffer(by_agent, aid, t, cfg), (name, aid, t)
            # every rendered record line is one of the agent's own interactions
            shown = r["feedback_text_shown"]
            for rd in included:
                own = index[(aid, rd)]
                assert f"you chose {own['choice']}" in shown
                if cfg.memory_content == "own_and_partner":
                    assert f"the other participant chose {own['partner_choice']}" in shown
            n_lines = len([ln for ln in shown.splitlines() if ln.startswith("- ")])
            assert n_lines == len(included)
        # no other agent's id ever appears in a prompt
        for c in sim.store.read_jsonl("calls.jsonl"):
            others = set(re.findall(r"\ba\d\d\b", c["prompt_text"])) - {c["agent_id"]}
            assert not others, (name, others)


# ---------------------------------------------------------------- 3 -------
def test_3_no_global_stats(cell_runs):
    rx = re.compile(r"\d+\s*(agents|participants|%)|\bmost\b|\bmajority\b", re.IGNORECASE)
    for name, sim in cell_runs.items():
        reward_on = sim.config.reward_mode == "local_match"
        for p in _prompts(sim):
            assert not guard_prompt(p, reward_on), name
            assert not rx.search(p), name
        assert sim.store.read_json("leakage_report.json")["passed"]


def test_3b_guard_catches_leaks():
    assert guard_prompt("Most agents chose Laba.", True)
    assert guard_prompt("12 agents chose Laba", True)
    assert guard_prompt("40% chose it", True)
    assert guard_prompt("Try to coordinate with the group.", True)
    assert guard_prompt("you received 5 points", reward_on=False)
    assert not guard_prompt("you received 5 points", reward_on=True)


def test_3c_leak_aborts_run(tmp_logs, monkeypatch):
    real = prompts_mod.build_agent_prompt

    def leaky(*a, **k):
        text, order, inc = real(*a, **k)
        return text + "\nMost participants chose Laba.", order, inc
    import naming_game.scheduler as sch
    monkeypatch.setattr(sch, "build_agent_prompt", leaky)
    sim, res = run(make_config(), tmp_logs)
    assert res["status"] == "failed_leakage"
    assert sim.store.read_json("leakage_report.json")["passed"] is False
    assert not sim.store.read_jsonl("calls.jsonl")  # fail-closed: nothing dispatched


# ---------------------------------------------------------------- 4 -------
def test_4_reward_switch(cell_runs):
    for name, sim in cell_runs.items():
        if sim.config.reward_mode != "none":
            continue
        for p in _prompts(sim):
            low = p.lower()
            for w in ("points", "score", "reward", "success", "failure", "payoff"):
                assert w not in low, (name, w)


# ---------------------------------------------------------------- 5 -------
def test_5_order_randomization():
    cfg = make_config()
    ag_a, ag_b = Agent("a00", "llm", 5), Agent("a01", "llm", 5)
    differ = 0
    for t in range(100):
        rng = rng_for(cfg.seed, "order", t)
        _, oa, _ = build_agent_prompt(ag_a, cfg, t, rng, LABELS)
        _, ob, _ = build_agent_prompt(ag_b, cfg, t, rng, LABELS)
        differ += oa != ob
    assert differ > 90
    # first-position frequency within binomial bounds
    n = 5000
    first = {lab: 0 for lab in LABELS}
    for t in range(n):
        _, o, _ = build_agent_prompt(ag_a, cfg, t, rng_for(cfg.seed, "order", t), LABELS)
        first[o[0]] += 1
    lo, hi = binom.ppf(0.0005, n, 0.1), binom.ppf(0.9995, n, 0.1)
    assert all(lo <= c <= hi for c in first.values()), first


# ---------------------------------------------------------------- 6 -------
REPLAY_DROP = {"run_id"}


def _rows(sim, name):
    return [{k: v for k, v in r.items() if k not in REPLAY_DROP} for r in sim.store.read_csv(name)]


@pytest.mark.parametrize("ov", [
    dict(model={"provider": "mock", "model_id": "mock", "mock_mode": "majority"}),
    dict(experiment_id="null_model", policy_default="voter", policy_params={"q": 0.5}, n_agents=24,
         committed_minority={"frac": 0.1, "start_rule": "round", "start_round": 5}),
    dict(experiment_id="null_model", policy_default="majority_H", pairing="community", n_rounds=30,
         committed_minority={"frac": 0.15, "start_rule": "after_consensus", "start_round": 25}),
])
def test_6_replay(tmp_path, ov):
    s1, _ = run(make_config(**ov), tmp_path / "r1")
    s2, _ = run(make_config(**ov), tmp_path / "r2")
    assert s1.config.run_id != s2.config.run_id
    assert s1.config.config_hash == s2.config.config_hash
    assert _rows(s1, "interactions.csv") == _rows(s2, "interactions.csv")
    assert _rows(s1, "population.csv") == _rows(s2, "population.csv")
    assert s1.store.read_jsonl("events.jsonl") == s2.store.read_jsonl("events.jsonl")
    if s1.config.committed_minority:
        assert s1.store.read_jsonl("events.jsonl"), "minority was never activated"


# ---------------------------------------------------------------- 7 -------
def test_7_parser():
    L = LABELS
    assert parse_label("Laba", L) == "Laba"
    assert parse_label("  laba. ", L) == "Laba"
    assert parse_label('"Laba"', L) == "Laba"
    assert parse_label("`Laba`", L) == "Laba"
    for bad in ("I choose Laba", "Laba, Zago", "Laba Zago", "", "   ", "Lava", "Labaa", "**Laba**",
                "Laba.\nBecause", None, "Laba!"):
        assert parse_label(bad, L) is None, bad


def test_7b_invalid_output_stored_raw_and_voided(tmp_logs):
    cfg = make_config(model={"provider": "mock", "model_id": "mock", "mock_invalid_rate": 0.5}, n_rounds=10)
    sim, res = run(cfg, tmp_logs)
    calls = sim.store.read_jsonl("calls.jsonl")
    bad = [c for c in calls if not c["valid"]]
    assert bad and all(c["parsed_label"] is None and c["raw_output"].startswith("I would choose") for c in bad)
    # a retry reuses the identical prompt
    retried = [c for c in calls if c["attempt"] == 2]
    assert retried
    first = {(c["round"], c["agent_id"]): c for c in calls if c["attempt"] == 1}
    assert all(first[(c["round"], c["agent_id"])]["prompt_text"] == c["prompt_text"] for c in retried)
    rows = sim.store.read_csv("interactions.csv")
    voids = [r for r in rows if r["void"] == "True"]
    assert voids and all(r["points"] == "" for r in voids)
    assert res["summary"]["exclude_invalid"] is True


# ---------------------------------------------------------------- 8 -------
def test_8_simultaneity(tmp_logs, monkeypatch):
    events = []
    import naming_game.scheduler as sch
    real = sch.build_agent_prompt

    def spy_build(agent, config, t, rng, labels):
        events.append(("build", t))
        return real(agent, config, t, rng, labels)

    class SpyModel(MockModel):
        def complete(self, prompt, call_seed):
            events.append(("call", current["t"]))
            return super().complete(prompt, call_seed)

    current = {"t": 0}
    monkeypatch.setattr(sch, "build_agent_prompt", spy_build)
    cfg = make_config(n_rounds=12)
    sim = sch.Simulation(cfg, store=RunStore.for_config(cfg, tmp_logs), model=SpyModel())
    for t in range(cfg.n_rounds):
        current["t"] = t
        asyncio.run(_step(sim, t))
        seq = [e for e in events if e[1] == t]
        first_call = next(i for i, e in enumerate(seq) if e[0] == "call")
        assert all(e[0] == "build" for e in seq[:first_call])
        assert all(e[0] == "call" for e in seq[first_call:])
    # no prompt references a record of the current round
    for r in sim.store.read_csv("interactions.csv"):
        assert all(rd < int(r["round"]) for rd in json.loads(r["memory_records_included"]))


# ---------------------------------------------------------------- 9 -------
def _strip_reward(prompt):
    prompt = re.sub(r"Scoring rule for this pairing only:\n(?:.*\n)*?\n", "", prompt)
    return re.sub(r"; you received -?\d+ points\.", ".", prompt)


def test_9_arm_symmetry(tmp_path):
    s_none, _ = run(make_config(), tmp_path / "a")
    s_rew, _ = run(make_config(experiment_id="rewarded_naming", reward_mode="local_match",
                               feedback_mode="numeric_score"), tmp_path / "b")
    p_none, p_rew = _prompts(s_none), _prompts(s_rew)
    assert len(p_none) == len(p_rew)
    for a, b in zip(p_none, p_rew):
        assert "Scoring rule" in b and "Scoring rule" not in a
        assert _strip_reward(b) == a


# ---------------------------------------------------------------- 10 ------
ILLEGAL = [
    dict(reward_mode="none", feedback_mode="numeric_score"),
    dict(memory_mode="none", memory_horizon_H=5),
    dict(memory_mode="none", memory_horizon_H=0),
    dict(memory_horizon_H=0),
    dict(model={"provider": "mock", "model_id": "mock", "temperature": 0}),
    dict(n_agents=13),
    dict(n_agents=20),
    dict(feedback_mode="match_indicator"),
    dict(feedback_mode="match_indicator", robustness_cell=True, memory_content="own_only"),
    dict(memory_mode="none", feedback_mode="match_indicator", robustness_cell=True),
    dict(payoff={"match": 1, "mismatch": 0}),
    dict(pairing="isolated"),
    dict(experiment_id="prior_calibration"),
    dict(experiment_id="prior_calibration", pairing="isolated", memory_mode="none",
         reward_mode="local_match", feedback_mode="choices_only"),
    dict(label_set_id="nope"),
    dict(label_pool_size=8),
    dict(n_stimuli=2),
    dict(policy_default="voter"),
    dict(policy_default="llm", model=None),
    dict(experiment_id="null_model"),
    dict(committed_minority={"frac": 0.01}),
    dict(yoked_source_run_id="x"),
    dict(seed=-1),
    dict(p0=(0.5, 0.5)),
    dict(pairing="star", topology_params={"hub_id": "a99"}),
    dict(show_cumulative_points=True),
]


@pytest.mark.parametrize("ov", ILLEGAL)
def test_10_config_validation(ov):
    with pytest.raises(ValidationError):
        make_config(**ov)


def test_10b_legal_defaults_and_hash():
    c = make_config()
    assert c.memory_horizon_H == 5 and c.payoff is None
    r = make_config(experiment_id="rewarded_naming", reward_mode="local_match", feedback_mode="numeric_score")
    assert r.payoff.match == 100 and r.payoff.mismatch == -50 and r.show_cumulative_points is True
    assert make_config().config_hash == make_config().config_hash
    assert make_config(seed=8).config_hash != make_config().config_hash


# ---------------------------------------------------------------- 11 ------
def _skeleton(prompt, aid):
    s = prompt.replace(aid, "{ID}")
    s = re.sub(r"(?m)^- [A-Z][a-z]+$", "- {LABEL}", s)
    s = re.sub(r"(?m)^- (Latest interaction|\d+ interactions ago): .*$", "- {REC}", s)
    s = re.sub(r"so far: -?\d+", "so far: {N}", s)
    return re.sub(r"(- \{REC\}\n?)+", "{RECS}", s)


def test_11_hub_neutrality(cell_runs):
    sim = cell_runs["A_star"]
    hub = sim.config.topology_params.hub_id
    hub_sk, leaf_sk = set(), set()
    for c in sim.store.read_jsonl("calls.jsonl"):
        (hub_sk if c["agent_id"] == hub else leaf_sk).add(_skeleton(c["prompt_text"], c["agent_id"]))
    assert hub_sk and hub_sk <= leaf_sk


# ---------------------------------------------------------------- 12 ------
@pytest.mark.parametrize("ov", [
    dict(experiment_id="null_model", policy_default="majority_H", n_rounds=30,
         committed_minority={"frac": 0.2, "start_rule": "round", "start_round": 12}),
    dict(experiment_id="rewarded_naming", reward_mode="local_match", feedback_mode="numeric_score",
         model={"provider": "mock", "model_id": "mock", "mock_mode": "majority", "mock_invalid_rate": 0.05}),
])
def test_12_resume(tmp_path, ov):
    full, _ = run(make_config(**ov), tmp_path / "full")
    cfg = make_config(**ov)
    part = Simulation(cfg, store=RunStore.for_config(cfg, tmp_path / "part"))
    res = asyncio.run(part.run(stop_after=8))
    assert res["status"] == "stopped"
    # simulate a crash mid-round: a round-9 row without its population row,
    # then a half-written line
    rows = part.store.read_csv("interactions.csv")
    with part.store.path("interactions.csv").open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        bad = dict(rows[-1]); bad["round"] = "9"
        w.writerow(bad)
        f.write("x,x,x")
    with part.store.path("calls.jsonl").open("a") as f:
        f.write('{"round": 9, "trunc')
    resumed, nxt = Simulation.resume(part.store)
    assert nxt == 9
    asyncio.run(resumed.run(start_round=nxt))
    assert _rows(full, "interactions.csv") == _rows(resumed, "interactions.csv")
    assert _rows(full, "population.csv") == _rows(resumed, "population.csv")


# ---------------------------------------------------------------- 13 ------
MAJORITY_CONSENSUS_RATE_MIN = 0.99  # frozen after first implementation (observed 1.000 over 1000 seeds)


def test_13_null_model_sanity():
    reached = 0
    n_seeds = 1000
    for s in range(n_seeds):
        cfg = make_config(experiment_id="null_model", policy_default="majority_H", n_agents=24, n_rounds=100,
                          seed=s)
        sim = Simulation(cfg, render_prompts=False)
        asyncio.run(sim.run())
        reached += sim.tracker.reached
    assert reached / n_seeds >= MAJORITY_CONSENSUS_RATE_MIN, reached / n_seeds

    # prior_sample: round entropy within sampling noise of the plug-in expectation for p0
    p0 = (0.3, 0.2, 0.1, 0.1, 0.1, 0.05, 0.05, 0.04, 0.03, 0.03)
    cfg = make_config(experiment_id="null_model", policy_default="prior_sample", n_agents=24, n_rounds=400,
                      p0=p0, seed=3)
    sim = Simulation(cfg, render_prompts=False)
    asyncio.run(sim.run())
    observed = np.mean([r["round_entropy"] for r in sim.round_rows])
    rng = np.random.default_rng(0)
    sims = []
    for _ in range(4000):
        c = np.bincount(rng.choice(10, size=24, p=p0), minlength=10) / 24
        c = c[c > 0]
        sims.append(-(c * np.log2(c)).sum())
    expected, sd = np.mean(sims), np.std(sims) / math.sqrt(400)
    assert abs(observed - expected) < 4 * sd, (observed, expected)
    analytic = -sum(p * math.log2(p) for p in p0)
    assert observed < analytic  # plug-in entropy is biased low, never above


# ---------------------------------------------------------------- 14 ------
def test_14_store_isolation():
    forbidden = {"store", "metrics", "scheduler", "llm"}
    for mod in ("agents.py", "prompts.py", "parser.py"):
        tree = ast.parse((PKG / mod).read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            for n in names:
                assert not any(part in forbidden for part in n.split(".")), (mod, n)


def test_14b_single_writer_and_constructor():
    src = {p.name: p.read_text() for p in PKG.glob("*.py")}
    writers = [n for n, s in src.items() if re.search(r"\.buffer\.append\(", s)]
    assert writers == ["scheduler.py"]
    assert src["scheduler.py"].count(".buffer.append(") == 1  # inside commit_dyad only
    builders = [n for n, s in src.items() if "def build_agent_prompt" in s]
    assert builders == ["prompts.py"]


# ---------------------------------------------------------------- 15 ------
def test_15_label_hygiene():
    sets = {k: v for k, v in load_label_sets().items() if v["kind"] == "preset"}
    assert len(sets) >= 3
    seen = set()
    for sid, entry in sets.items():
        labels = entry["labels"]
        assert not set_problems(labels), (sid, set_problems(labels))
        assert label_set_hash(labels) == entry["hash"]
        for lab in labels:
            assert not any(s in lab.lower() for s in DENY_SUBSTRINGS)
            assert re.fullmatch(r"[BDFGKLMNPRSTVZ][aeiou][bdfgklmnprstvz][aeiou]", lab)
        assert not (seen & {x.lower() for x in labels}), "label sets overlap"
        seen |= {x.lower() for x in labels}
