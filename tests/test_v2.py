"""SPEC v2 tests: rooms, templates v2, prior replay, non-social framing,
model pinning, tie-breaks, minority rules, study plan, label sets, priors."""
import asyncio
import re

import pytest
from pydantic import ValidationError

from conftest import make_config, run
from naming_game import labels as labels_mod
from naming_game import runner, store
from naming_game.config import ExperimentConfig
from naming_game.labels import check_label_set, get_labels
from naming_game.llm import CallResult, MockModel
from naming_game.priors import derive_prior
from naming_game.rooms import ROOMS, room_fields
from naming_game.scheduler import Simulation, replayed_labels
from naming_game.store import RunStore

MOCK = {"provider": "mock", "model_id": "mock", "mock_mode": "uniform"}


def room_config(room, **kw):
    d = {**room_fields(room), "seed": 3, "label_set_id": "P1", "n_agents": 12, "n_rounds": 12,
         "phase": "test", "model": MOCK}
    if d.get("memory_mode") != "none":
        d["memory_horizon_H"] = 5
    if ROOMS[room].get("partner_source") == "prior_replay":
        d["p0"] = [0.1] * 10
        d["p0_source"] = "uniform (explicit)"
    d.update(kw)
    return ExperimentConfig(**d)


def prompts(sim):
    return [c["prompt_text"] for c in sim.store.read_jsonl("calls.jsonl")]


# ---------------------------------------------------------------- rooms ----
def test_every_room_builds_and_runs(tmp_path):
    for room in ROOMS:
        sim, res = run(room_config(room), tmp_path)
        assert res["status"] == "completed", room
        assert sim.store.read_json("manifest.json")["cell_id"] == room
        assert res["summary"]["entropy_final"] is not None


def test_room_signature_is_enforced():
    with pytest.raises(ValidationError):
        room_config("B2", reward_mode="local_match", experiment_id="rewarded_naming")
    with pytest.raises(ValidationError):
        room_config("B1", memory_content="own_and_partner")
    with pytest.raises(ValidationError):
        room_config("A2", feedback_mode="numeric_score")
    with pytest.raises(ValidationError):
        room_config("B2", cell_id="XX")


def test_mock_cannot_be_study_data():
    with pytest.raises(ValidationError):
        make_config(phase="pilot")
    with pytest.raises(ValidationError):
        make_config(phase="confirmatory")


# ---------------------------------------------------------------- 16 -------
def _strip_payoff(p):
    return re.sub(r"Scoring rule for this pairing only:\n(?:.*\n)*?\n", "", p)


@pytest.mark.parametrize("b,a", [("B0", "A0"), ("B1", "A1"), ("B2", "A2")])
def test_16_arm_symmetry_all_memory_columns(tmp_path, b, a):
    sb, _ = run(room_config(b), tmp_path / b)
    sa, _ = run(room_config(a), tmp_path / a)
    pb, pa = prompts(sb), prompts(sa)
    assert len(pb) == len(pa)
    for x, y in zip(pb, pa):
        assert "Scoring rule" in y and "Scoring rule" not in x
        assert "points" not in x
        assert _strip_payoff(y) == x


def test_v2_payoff_text_and_own_only_block():
    c = room_config("A2")
    p = runner.example_prompts(c)["this_config"]["first_round"]
    assert "Your objective is to maximize your own points.\n" in p and "across pairings" not in p
    b1 = runner.example_prompts(room_config("B1"))["this_config"]["with_memory"]
    assert "each of you is shown the other's choice" not in b1
    assert "You are paired with another participant" in b1
    b2 = runner.example_prompts(room_config("B2"))["this_config"]["with_memory"]
    assert "each of you is shown the other's choice" in b2


# ---------------------------------------------------------------- 17 -------
def test_17_round0_prompt_family(tmp_path):
    s0, _ = run(room_config("B0"), tmp_path / "b0")
    s2, _ = run(room_config("B2"), tmp_path / "b2")
    s1, _ = run(room_config("B1"), tmp_path / "b1")
    r0 = lambda sim: [c["prompt_text"] for c in sim.store.read_jsonl("calls.jsonl") if c["round"] == 0]
    assert r0(s2) == r0(s0)            # identical prompt family: pooled into p0_B
    assert r0(s1) != r0(s0)            # own-only block differs: its own family
    assert set(r0(s0)[0].splitlines()) - set(r0(s1)[0].splitlines()) == {
        "After both choices are submitted, each of you is shown the other's choice."}


# ---------------------------------------------------------------- 23 -------
def test_23_random_tiebreaks_are_flagged_and_reproducible():
    from naming_game.metrics import modal
    vals = ["Bagu", "Difa", "Bagu", "Difa"]
    picks = {modal(vals, f"s{i}")[0] for i in range(40)}
    assert picks == {"Bagu", "Difa"}            # not always alphabetical
    assert modal(vals, "k1") == modal(vals, "k1")
    assert modal(vals, "k1")[3] is True and modal(["Bagu"], "k")[3] is False


# ---------------------------------------------------------------- 24 -------
class DriftModel(MockModel):
    def __init__(self):
        super().__init__()
        self.n = 0

    def complete(self, prompt, call_seed):
        self.n += 1
        res = super().complete(prompt, call_seed)
        res.model_version = "mock-1" if self.n <= 20 else "mock-2"
        return res


def test_24_model_drift_aborts(tmp_path):
    cfg = make_config(model={**MOCK, "pin_version": "auto"}, n_rounds=6)
    sim = Simulation(cfg, store=RunStore.for_config(cfg, tmp_path), model=DriftModel())
    res = asyncio.run(sim.run())
    assert res["status"] == "failed_model_drift"
    assert sim.store.read_json("manifest.json")["pinned_version"] == "mock-1"
    cfg2 = make_config(model={**MOCK, "pin_version": "mock-1"}, n_rounds=3)
    assert asyncio.run(Simulation(cfg2, store=None, model=MockModel()).run())["status"] == "completed"


# ---------------------------------------------------------------- 26 -------
def test_26_agent_id_hidden_by_default(tmp_path):
    sim, _ = run(make_config(), tmp_path)
    assert not any(re.search(r"participant a\d\d", p) for p in prompts(sim))
    sim2, _ = run(make_config(show_own_agent_id=True), tmp_path / "shown")
    assert all(re.search(r"You are participant a\d\d\.", p) for p in prompts(sim2))


# ---------------------------------------------------------------- 28 -------
def test_28_prior_replay_is_independent_of_other_agents(tmp_path):
    cfg = room_config("B2R", p0=[0.5] + [0.5 / 9] * 9)
    sim, res = run(cfg, tmp_path)
    assert res["status"] == "completed"
    labels = get_labels("P1")
    rows = sim.store.read_csv("interactions.csv")
    idx = {a: i for i, a in enumerate(cfg.agent_ids)}
    differs = 0
    for r in rows:
        if r["void"] == "True":
            continue
        expect = replayed_labels(cfg, labels, list(cfg.p0), int(r["round"]), [idx[r["agent_id"]]])[idx[r["agent_id"]]]
        assert r["partner_choice"] == expect          # a function of (seed, round, agent) only
        assert r["partner_source"] == "prior_replay"
        differs += r["partner_choice"] != r["partner_actual_choice"]
    assert differs > 0
    # memory holds the replayed label, and the prompt shows it
    calls = sim.store.read_jsonl("calls.jsonl")
    last = [c for c in calls if c["round"] == cfg.n_rounds - 1][0]
    agent_rows = [r for r in rows if r["agent_id"] == last["agent_id"] and int(r["round"]) == cfg.n_rounds - 2]
    if agent_rows and agent_rows[0]["void"] == "False":
        assert f"the other participant chose {agent_rows[0]['partner_choice']}" in last["prompt_text"]


def test_prior_replay_requires_p0():
    with pytest.raises(ValidationError):
        room_config("B2R", p0=None)


# ---------------------------------------------------------------- 29 -------
def test_29_nonsocial_framing(tmp_path):
    ns, _ = run(room_config("NS2"), tmp_path / "ns")
    b2, _ = run(room_config("B2"), tmp_path / "b2")
    for x, y in zip(prompts(ns), prompts(b2)):
        assert "participant" not in x and "reference label" in x
        conv = (x.replace("After you choose, a reference label from the same list is shown to you.",
                          "You are paired with another participant, who chooses from the same list at the same time.\n"
                          "After both choices are submitted, each of you is shown the other's choice.")
                 .replace("; the reference label shown was ", "; the other participant chose "))
        assert conv == y


# ---------------------------------------------------------------- 30 -------
def test_30_minority_random_nonmodal_and_release(tmp_path):
    cfg = make_config(experiment_id="null_model", policy_default="majority_H", n_agents=24, n_rounds=40, model=None,
                      committed_minority={"frac": 0.25, "start_rule": "round", "start_round": 5, "end_round": 15})
    sim, _ = run(cfg, tmp_path)
    ev = sim.store.read_jsonl("events.jsonl")
    act = [e for e in ev if e["event"] == "minority_activated"][0]
    rel = [e for e in ev if e["event"] == "minority_released"][0]
    assert act["round"] == 5 and rel["round"] == 15
    pop = {int(p["round"]): p for p in sim.store.read_csv("population.csv")}
    assert act["label"] != pop[4]["state_modal_label"] or pop[4]["state_modal_tie"] == "True"
    rows = sim.store.read_csv("interactions.csv")
    assert all(r["is_minority"] == "False" for r in rows if int(r["round"]) >= 15)
    assert any(r["is_minority"] == "True" for r in rows if 5 <= int(r["round"]) < 15)


# ---------------------------------------------------------------- plan -----
def test_plan_expansion_and_interleaving():
    spec = {"rooms": ["B0", "B2", "A2"], "label_sets": ["P1", "P2"], "n_seeds": 2, "n_agents": 12, "n_rounds": 5,
            "model": MOCK, "order_seed": 11}
    cfgs, notes = runner.plan_configs(spec)
    assert len(cfgs) == 12 and all(c.phase == "test" for c in cfgs)
    cells = [c.cell_id for c in cfgs]
    assert cells != sorted(cells)  # interleaved, not blocked by room
    again, _ = runner.plan_configs(spec)
    assert [(c.cell_id, c.label_set_id, c.seed) for c in again] == [(c.cell_id, c.label_set_id, c.seed) for c in cfgs]
    assert {(c.cell_id, c.label_set_id, c.seed) for c in cfgs} == {
        (r, ls, s) for r in ("B0", "B2", "A2") for ls in ("P1", "P2") for s in (0, 1)}


def test_plan_replay_room_needs_prior(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOGS_DIR", tmp_path)
    spec = {"rooms": ["B2R"], "label_sets": ["P1"], "n_seeds": 1, "n_agents": 12, "n_rounds": 5, "model": MOCK}
    with pytest.raises(runner.PlanError):
        runner.plan_configs(spec)
    cfgs, notes = runner.plan_configs({**spec, "prior_mode": "uniform"})
    assert cfgs[0].p0 == tuple([0.1] * 10) and "uniform" in cfgs[0].p0_source
    # after a B0 run exists, the prior is derived from it
    b0, _ = runner.plan_configs({**spec, "rooms": ["B0"]})
    sim = Simulation(b0[0], store=RunStore.for_config(b0[0], tmp_path))
    asyncio.run(sim.run())
    pr = derive_prior("P1", "B0", "mock", "mock", None, "test")
    assert pr["available"] and pr["n_choices"] == 12 * 5 and abs(sum(pr["p0_smoothed"]) - 1) < 1e-9
    cfgs, notes = runner.plan_configs(spec)
    assert cfgs[0].p0_source.startswith("derived:B0:P1")
    # confirmatory runs may only use pilot-derived priors
    assert not derive_prior("P1", "B0", "mock", "mock", None, "confirmatory")["available"]


# ---------------------------------------------------------------- labels ---
def test_label_set_checks():
    ok = check_label_set(["Bagu", "Difa", "Feki"])
    assert ok["ok"] and not ok["errors"]
    bad = check_label_set(["Bagu", "bagu", "two words", "Winko"])
    assert not bad["ok"]
    assert any("duplicate" in e for e in bad["errors"])
    assert any("single word" in e for e in bad["errors"])
    assert any("banned" in e for e in bad["errors"])  # 'win' would trip the leakage guard
    warn = check_label_set(["Soru", "Sora", "Apple"])
    assert warn["ok"] and warn["warnings"]


def test_custom_label_sets_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(labels_mod, "USER_LABEL_STORE", tmp_path / "label_sets.json")
    sid = labels_mod.save_custom_label_set("My set", ["Bagu", "Difa", "Feki", "Gevi"])
    assert sid.startswith("C-") and get_labels(sid) == ("Bagu", "Difa", "Feki", "Gevi")
    c = make_config(label_set_id=sid, label_pool_size=4)
    assert c.label_pool_size == 4
    with pytest.raises(ValueError):
        labels_mod.save_custom_label_set("x", ["Bagu", "Bagu"])
    with pytest.raises(ValueError):
        labels_mod.save_custom_label_set("x", ["Bagu"], set_id="P1")
    labels_mod.delete_custom_label_set(sid)
    with pytest.raises(KeyError):
        get_labels(sid)


def test_presets_are_clean_and_legacy_kept():
    sets = labels_mod.load_label_sets()
    assert {"P1", "P2", "P3"} <= set(sets) and sets["L1"]["kind"] == "legacy"
    assert "L1" not in labels_mod.load_label_sets(include_legacy=False)
    for sid in ("P1", "P2", "P3"):
        assert check_label_set(sets[sid]["labels"]) == {"errors": [], "warnings": [], "ok": True}


def test_choice_model_v2_columns(tmp_path):
    from naming_game.metrics import choice_model_rows
    sim, res = run(room_config("B2", n_rounds=8), tmp_path)
    rows = choice_model_rows(sim.store.read_csv("interactions.csv"), get_labels("P1"), [0.1] * 10, True, 4)
    need = {"own_prev_visible", "own_prev_history", "partner_last", "matched_k", "recency_w_partner",
            "pos_first", "pos_last", "pre_consensus"}
    assert need <= set(rows[0])
    assert sum(r["chosen"] for r in rows) == len(rows) // 10
    r0 = [r for r in rows if int(r["round"]) == 0]
    assert all(r["own_prev_visible"] == 0 and r["partner_count_H"] == 0 for r in r0)


def test_anthropic_request_shape(monkeypatch):
    """Temperature goes through extra_body (SDK 1.x); no seed is ever sent."""
    import anthropic

    from naming_game import llm
    captured = {}

    class FakeMessages:
        def create(self, **kw):
            captured.update(kw)

            class U:
                input_tokens, output_tokens = 10, 1

            class B:
                type, text = "text", "Bagu"

            class R:
                content, usage, model, stop_reason = [B()], U(), "claude-haiku-4-5-20251001", "end_turn"
            return R()

    class FakeClient:
        def __init__(self, **kw):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    monkeypatch.setattr(llm, "api_key", lambda p: "sk-test-key-000000")
    res = llm.AnthropicModel("claude-haiku-4-5", 1.0, 16).complete("hi", 123)
    assert captured["extra_body"] == {"temperature": 1.0} and "temperature" not in captured
    assert "seed" not in captured and "seed" not in captured.get("extra_body", {})
    assert res.effective_temperature == 1.0 and res.request_params["extra_body"] == {"temperature": 1.0}
    captured.clear()
    llm.AnthropicModel("claude-sonnet-5", 1.0, 16).complete("hi", 1)
    assert "extra_body" not in captured and captured["thinking"] == {"type": "disabled"}


def test_unexpected_error_marks_run_failed(tmp_path):
    class Boom(MockModel):
        def complete(self, prompt, call_seed):
            raise TypeError("boom")
    cfg = make_config(n_rounds=2)
    sim = Simulation(cfg, store=RunStore.for_config(cfg, tmp_path), model=Boom())
    res = asyncio.run(sim.run())
    assert res["status"] == "failed_error" and "boom" in res["error"]
    assert sim.store.read_json("manifest.json")["status"] == "failed_error"


# ---------------------------------------------------------------- answer mode ---
def test_constrained_answers_use_shown_order_and_are_parsed(tmp_path):
    seen = []

    class Spy(MockModel):
        def complete(self, prompt, call_seed, labels_shown=None):
            seen.append((prompt, list(labels_shown)))
            return super().complete(prompt, call_seed, labels_shown)

    cfg = room_config("A2", n_rounds=4)
    assert cfg.model.answer_mode == "constrained"
    sim = Simulation(cfg, store=RunStore.for_config(cfg, tmp_path), model=Spy(answer_mode="constrained"))
    res = asyncio.run(sim.run())
    assert res["summary"]["invalid_rate"] == 0.0
    for prompt, order in seen:  # enum order == the order printed in that prompt
        assert MockModel.labels_in_prompt(prompt) == order
    calls = sim.store.read_jsonl("calls.jsonl")
    assert all(c["raw_output"].startswith('{"label"') and c["valid"] for c in calls)
    rows = sim.store.read_csv("interactions.csv")
    assert all(r["choice"] in get_labels("P1") for r in rows)


def test_anthropic_constrained_request(monkeypatch):
    import anthropic

    from naming_game import llm
    captured = {}

    class FakeMessages:
        def create(self, **kw):
            captured.clear(); captured.update(kw)

            class U:
                input_tokens, output_tokens = 200, 8

            class B:
                type, text = "text", '{"label": "Difa"}'

            class R:
                content, usage, model, stop_reason = [B()], U(), "claude-haiku-4-5-20251001", "end_turn"
            return R()

    class FakeClient:
        def __init__(self, **kw):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    monkeypatch.setattr(llm, "api_key", lambda p: "sk-test-key-000000")
    order = ["Difa", "Bagu", "Feki"]
    res = llm.AnthropicModel("claude-haiku-4-5", 1.0, 16).complete("prompt", 1, labels_shown=order)
    schema = captured["output_config"]["format"]["schema"]
    assert schema["properties"]["label"]["enum"] == order and captured["max_tokens"] >= 32
    assert llm.extract_label_text(res.text, True) == "Difa"
    llm.AnthropicModel("claude-haiku-4-5", 1.0, 16, answer_mode="free_text").complete("prompt", 1, labels_shown=order)
    assert "output_config" not in captured


def test_old_runs_resume_as_free_text(tmp_path):
    cfg = make_config(n_rounds=4)
    sim = Simulation(cfg, store=RunStore.for_config(cfg, tmp_path))
    asyncio.run(sim.run(stop_after=1))
    import json as _json
    p = sim.store.path("config.json")
    d = _json.loads(p.read_text()); d["model"].pop("answer_mode"); p.write_text(_json.dumps(d))
    resumed, nxt = Simulation.resume(sim.store)
    assert resumed.config.model.answer_mode == "free_text" and nxt == 2
