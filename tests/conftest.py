import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from naming_game.config import ExperimentConfig  # noqa: E402
from naming_game.scheduler import build_run  # noqa: E402


def make_config(**overrides) -> ExperimentConfig:
    d = dict(experiment_id="no_reward_convergence", seed=7, label_set_id="L1", n_agents=12, n_rounds=20,
             reward_mode="none", feedback_mode="choices_only",
             model={"provider": "mock", "model_id": "mock", "mock_mode": "uniform"})
    d.update(overrides)
    return ExperimentConfig(**d)


def run(config, base_dir, **kw):
    sim = build_run(config, base_dir=base_dir, **kw)
    result = asyncio.run(sim.run())
    return sim, result


@pytest.fixture
def tmp_logs(tmp_path):
    return tmp_path / "logs"
