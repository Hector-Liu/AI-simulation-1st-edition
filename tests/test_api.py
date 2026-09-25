"""Web API smoke tests (mock model only, no network)."""
from fastapi.testclient import TestClient

from naming_game import store
from naming_game.api import app

client = TestClient(app)
BASE = {"experiment_id": "no_reward_convergence", "seed": 1, "label_set_id": "P1", "n_agents": 12,
        "n_rounds": 5, "reward_mode": "none", "feedback_mode": "choices_only"}


def test_meta_and_index():
    assert client.get("/api/health").json() == {"ok": True}
    m = client.get("/api/meta").json()
    assert set(m["label_sets"]) >= {"P1", "P2", "P3"} and "L1" not in m["label_sets"]
    assert "has_key" in m["providers"]["anthropic"]
    assert "sk-" not in client.get("/api/meta").text  # never returns key values
    assert client.get("/").status_code == 200


def test_validate_reports_errors_and_prompts():
    bad = client.post("/api/validate", json={**BASE, "feedback_mode": "numeric_score"}).json()
    assert not bad["ok"] and any("numeric_score" in e for e in bad["errors"])
    ok = client.post("/api/validate", json={**BASE, "model": {"provider": "anthropic", "model_id": "claude-haiku-4-5"}}).json()
    assert ok["ok"] and ok["estimate"]["paid"] and ok["estimate"]["calls"] == 60
    assert "Scoring rule" in ok["prompts"]["other_arm"]["first_round"]
    assert "Scoring rule" not in ok["prompts"]["this_config"]["first_round"]


def test_paid_run_requires_confirmation():
    r = client.post("/api/runs", json={"config": {**BASE, "model": {"provider": "anthropic", "model_id": "claude-haiku-4-5"}}})
    assert r.status_code == 409


def test_dry_run():
    r = client.post("/api/dry-run", json={**BASE, "model": {"provider": "anthropic", "model_id": "claude-haiku-4-5"}}).json()
    assert r["status"] == "completed" and r["leakage"]["passed"] and r["rounds"] == 5


def test_runs_listing_reads_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOGS_DIR", tmp_path)
    assert store.list_runs(tmp_path) == []


def test_transcripts_match_interactions(tmp_path):
    import asyncio

    from conftest import make_config
    from naming_game.scheduler import Simulation
    from naming_game.store import RunStore
    from naming_game.transcript import dyad_rows, transcript_csv, transcript_text

    cfg = make_config(experiment_id="rewarded_naming", reward_mode="local_match", feedback_mode="numeric_score",
                      n_rounds=4)
    sim = Simulation(cfg, store=RunStore.for_config(cfg, tmp_path))
    asyncio.run(sim.run())
    rows = dyad_rows(sim.store)
    inter = sim.store.read_csv("interactions.csv")
    assert len(rows) == len(inter) // 2 == 4 * 6
    by_agent = {(r["round"], r["agent_id"]): r for r in inter}
    for d in rows:
        a = by_agent[(str(d["round"]), d["agent_a"])]
        assert a["partner_id"] == d["agent_b"] and a["choice"] == d["choice_a"] and a["partner_choice"] == d["choice_b"]
    assert transcript_csv(sim.store).count("\n") == len(rows) + 1
    txt = transcript_text(sim.store)
    assert "── Round 3" in txt and f"{rows[0]['agent_a']} ({rows[0]['choice_a']}) × {rows[0]['agent_b']}" in txt
    full = transcript_text(sim.store, include_prompts=True)
    assert "Choose exactly one label from this list:" in full and "raw output:" in full
    assert len(dyad_rows(sim.store, 2, 2)) == 6


def test_models_catalog_and_default(tmp_path, monkeypatch):
    from naming_game import local_settings
    monkeypatch.setattr(local_settings, "PATH", tmp_path / "local_settings.json")
    m = client.get("/api/meta").json()
    ids = [x["id"] for x in m["claude_models"]]
    assert "claude-haiku-4-5" in ids and m["default_model"] == "claude-haiku-4-5"
    assert client.post("/api/settings/default-model", json={"model_id": "claude-sonnet-5"}).json()["ok"]
    assert client.get("/api/meta").json()["default_model"] == "claude-sonnet-5"
    assert client.post("/api/settings/default-model", json={"model_id": "bad id!"}).status_code == 400
