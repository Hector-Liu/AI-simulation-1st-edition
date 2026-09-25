"""Per-machine preferences (gitignored): default model and price overrides."""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "local_settings.json"
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_TEMPERATURE = 1.0  # see docs/IMPLEMENTATION_NOTES.md "Temperature"


def load() -> dict:
    try:
        return json.loads(PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(d: dict):
    PATH.write_text(json.dumps(d, indent=2) + "\n")


def update(**kw) -> dict:
    d = load()
    d.update(kw)
    save(d)
    return d


def price_for(model_id: str):
    """(input, output) USD per 1M tokens: user override first, then built-in table."""
    from .llm import PRICING
    over = load().get("pricing", {}).get(model_id)
    if over:
        return tuple(over)
    return PRICING.get(model_id)
