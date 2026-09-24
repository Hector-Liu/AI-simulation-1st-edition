"""Web API smoke tests (mock model only, no network)."""
from fastapi.testclient import TestClient

from naming_game import store
from naming_game.api import app

client = TestClient(app)
BASE = {"experiment_id": "no_reward_convergence", "seed": 1, "label_set_id": "L1", "n_agents": 12,
        "n_rounds": 5, "reward_mode": "none", "feedback_mode": "choices_only"}


def test_meta_and_index():
    assert client.get("/api/health").json() == {"ok": True}
    m = client.get("/api/meta").json()
    assert set(m["label_sets"]) >= {"L1", "L2", "L3"}
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
