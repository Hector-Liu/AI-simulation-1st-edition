"""Model clients. One user message per call; the exact messages are logged.

Providers: anthropic (official SDK), openai / deepseek (OpenAI-compatible SDK),
and mock (offline, no network). Every call returns text plus metadata:
model version, finish reason, token usage, effective temperature and max
tokens, and latency (SPEC §4.3). No seed is ever forwarded to a provider.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

PROVIDER_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

# Claude models offered in the UI. Price per 1M tokens (input, output) in USD;
# check the provider's price page before any batch (SPEC §10).
# temperature: whether the API accepts a temperature parameter.
# thinking: off_by_default (no hidden reasoning unless requested) |
#           disable (on by default; the engine sends thinking={type: disabled}) |
#           always (cannot be disabled; flagged as a reasoning model)
CLAUDE_MODELS = [
    {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5", "price": (1.00, 5.00),
     "temperature": True, "thinking": "off_by_default",
     "note": "Cheapest; accepts temperature; no hidden reasoning. Good default for pilots."},
    {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "price": (3.00, 15.00),
     "temperature": True, "thinking": "off_by_default",
     "note": "Mid-size; accepts temperature; no hidden reasoning."},
    {"id": "claude-sonnet-5", "name": "Claude Sonnet 5", "price": (2.00, 10.00),
     "temperature": False, "thinking": "disable",
     "note": "Temperature fixed at provider default; thinking switched off by the engine."},
    {"id": "claude-opus-4-6", "name": "Claude Opus 4.6", "price": (5.00, 25.00),
     "temperature": True, "thinking": "off_by_default", "note": "Large; accepts temperature."},
    {"id": "claude-opus-4-7", "name": "Claude Opus 4.7", "price": (5.00, 25.00),
     "temperature": False, "thinking": "off_by_default", "note": "Temperature fixed at provider default."},
    {"id": "claude-opus-4-8", "name": "Claude Opus 4.8", "price": (5.00, 25.00),
     "temperature": False, "thinking": "off_by_default", "note": "Temperature fixed at provider default."},
    {"id": "claude-opus-5", "name": "Claude Opus 5", "price": (5.00, 25.00),
     "temperature": False, "thinking": "disable",
     "note": "Temperature fixed at provider default; thinking switched off by the engine."},
    {"id": "claude-opus-5-5", "name": "Claude Opus 5.5", "price": (4.00, 20.00),
     "temperature": False, "thinking": "always",
     "note": "Reasoning cannot be disabled (flagged). Not recommended for confirmatory cells."},
    {"id": "claude-fable-5-1", "name": "Claude Fable 5.1", "price": (10.00, 50.00),
     "temperature": False, "thinking": "always",
     "note": "Most capable and most expensive; reasoning cannot be disabled (flagged)."},
]
PRICING = {m["id"]: m["price"] for m in CLAUDE_MODELS}
PRICING["mock"] = (0.0, 0.0)
ANTHROPIC_PROFILES = {m["id"]: {"temperature": m["temperature"], "thinking": m["thinking"]} for m in CLAUDE_MODELS}
# Models whose reasoning cannot be switched off need room for hidden reasoning
# tokens; the effective cap is logged per call.
REASONING_MIN_MAX_TOKENS = 2048
PROVIDER_DEFAULT_TEMPERATURE = {"anthropic": 1.0, "openai": 1.0, "deepseek": 1.0}


def model_notes(provider: str, model_id: str) -> list[str]:
    """Design warnings about a model choice (shown in the UI and manifest)."""
    notes = []
    if provider == "anthropic":
        prof = ANTHROPIC_PROFILES.get(model_id)
        if prof is None:
            notes.append("unknown model profile: temperature support and reasoning mode unverified")
        else:
            if not prof["temperature"]:
                notes.append("temperature cannot be set; provider default sampling is used")
            if prof["thinking"] == "always":
                notes.append("reasoning model: hidden reasoning cannot be disabled (flagged; not recommended for confirmatory cells)")
            if prof["thinking"] == "disable":
                notes.append("thinking is on by default; the engine sends thinking={type: disabled}")
    if provider in ("openai", "deepseek") and re.match(r"^(o\d|gpt-5)", model_id or ""):
        notes.append("reasoning model: temperature ignored, hidden reasoning (flagged)")
    return notes


def load_env():
    """Load .env into os.environ without overriding variables already set."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$", line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")


def api_key(provider: str) -> Optional[str]:
    load_env()
    env = PROVIDER_ENV.get(provider)
    v = os.environ.get(env or "", "").strip()
    if not v or "xxx" in v or v.lower().startswith("your") or len(v) < 12:
        return None
    return v


@dataclass
class CallResult:
    text: str
    model_version: Optional[str] = None
    finish_reason: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    latency_ms: Optional[int] = None
    effective_temperature: Optional[float] = None
    effective_max_tokens: Optional[int] = None
    provider_messages: list = field(default_factory=list)
    request_params: dict = field(default_factory=dict)


STRUCTURED_OVERHEAD_TOKENS = 240  # measured on Haiku 4.5: schema + JSON wrapper cost ~240 extra input tokens per call


def choice_schema(labels) -> dict:
    """JSON schema that only admits one of the labels, in the given order.

    The enum order is the label order shown in that prompt, so the schema never
    carries a fixed order shared by all agents (the order stays randomized)."""
    return {"type": "object", "properties": {"label": {"type": "string", "enum": list(labels)}},
            "required": ["label"], "additionalProperties": False}


def extract_label_text(raw: str, constrained: bool) -> str:
    """Constrained answers arrive as {"label": "X"}; return the label text."""
    if not constrained:
        return raw
    try:
        v = json.loads(raw)
        return v.get("label", "") if isinstance(v, dict) else ""
    except (json.JSONDecodeError, TypeError):
        return raw


class RetryableError(Exception):
    pass


class FatalModelError(Exception):
    pass


class MockModel:
    """Offline model. It sees only the prompt string, like a real model.

    mode = uniform: a uniformly random label from the list in the prompt.
    mode = majority: the most frequent partner label in the rendered buffer
    (ties -> own latest -> uniform), i.e. majority_H read from text.
    """
    provider = "mock"

    def __init__(self, model_id="mock", mode="uniform", invalid_rate=0.0, answer_mode="constrained"):
        self.model_id = model_id
        self.mode = mode
        self.invalid_rate = invalid_rate
        self.answer_mode = answer_mode

    @staticmethod
    def labels_in_prompt(prompt: str) -> list[str]:
        block = prompt.split("Choose exactly one label from this list:\n", 1)[1].split("\n\n", 1)[0]
        return [ln[2:] for ln in block.splitlines() if ln.startswith("- ")]

    def complete(self, prompt: str, call_seed: int, labels_shown=None) -> CallResult:
        rng = np.random.default_rng(call_seed)
        labels = self.labels_in_prompt(prompt)
        if self.invalid_rate and rng.random() < self.invalid_rate:
            text = "I would choose " + labels[0]  # prose -> invalid
        elif self.mode == "majority":
            partners = re.findall(r"the other participant chose (\w+)", prompt)
            latest = re.search(r"- Latest interaction: you chose (\w+)", prompt)
            latest_own = latest.group(1) if latest else None
            if partners:
                counts = {p: partners.count(p) for p in set(partners)}
                top = max(counts.values())
                tied = sorted(p for p, c in counts.items() if c == top)
                text = tied[0] if len(tied) == 1 else (latest_own if latest_own in tied else tied[rng.integers(len(tied))])
            else:
                text = labels[rng.integers(len(labels))]
        else:
            text = labels[rng.integers(len(labels))]
        if self.answer_mode == "constrained" and not text.startswith("I would"):
            text = json.dumps({"label": text})
        return CallResult(text=text, model_version="mock-1", finish_reason="stop", tokens_in=len(prompt) // 4,
                          tokens_out=2, latency_ms=0, effective_temperature=None, effective_max_tokens=None,
                          provider_messages=[{"role": "user", "content": prompt}])


class AnthropicModel:
    provider = "anthropic"

    def __init__(self, model_id: str, temperature: Optional[float], max_tokens_cap: int, timeout: float = 60.0,
                 answer_mode: str = "constrained"):
        import anthropic
        key = api_key("anthropic")
        if not key:
            raise FatalModelError("ANTHROPIC_API_KEY is not set (add it on the API & Models page)")
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=timeout)
        self.model_id = model_id
        self.profile = ANTHROPIC_PROFILES.get(model_id, {"temperature": True, "thinking": "off_by_default"})
        self.temperature = temperature
        self.max_tokens_cap = max_tokens_cap
        self.answer_mode = answer_mode

    def complete(self, prompt: str, call_seed: int, labels_shown=None) -> CallResult:
        del call_seed  # never forwarded: the API takes no seed
        messages = [{"role": "user", "content": prompt}]
        max_tokens = self.max_tokens_cap
        output_config = {}
        if self.profile["thinking"] == "always":
            max_tokens = max(max_tokens, REASONING_MIN_MAX_TOKENS)
            output_config["effort"] = "low"
        if self.answer_mode == "constrained" and labels_shown:
            # structured output: the answer must be one of the labels (JSON enum)
            output_config["format"] = {"type": "json_schema", "schema": choice_schema(labels_shown)}
            max_tokens = max(max_tokens, 32)
        params_extra = {"output_config": output_config} if output_config else {}
        params = {"model": self.model_id, "max_tokens": max_tokens, "messages": messages, **params_extra}
        eff_t = PROVIDER_DEFAULT_TEMPERATURE["anthropic"] if self.profile["temperature"] else None
        if self.temperature is not None and self.profile["temperature"]:
            # anthropic>=1.0 removed sampling parameters from the create() signature;
            # models that still accept them get the value through extra_body.
            params["extra_body"] = {"temperature": self.temperature}
            eff_t = self.temperature
        if self.profile["thinking"] == "disable":
            params["thinking"] = {"type": "disabled"}
        a = self._anthropic
        t0 = time.monotonic()
        try:
            resp = self._client.messages.create(**params)
        except (a.RateLimitError, a.InternalServerError, a.APIConnectionError, a.APITimeoutError) as ex:
            raise RetryableError(f"{type(ex).__name__}: {ex}") from ex
        except a.APIStatusError as ex:
            if ex.status_code in (408, 409, 429, 529) or ex.status_code >= 500:
                raise RetryableError(f"HTTP {ex.status_code}: {ex}") from ex
            raise FatalModelError(f"HTTP {ex.status_code}: {ex}") from ex
        latency = int((time.monotonic() - t0) * 1000)
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        usage = resp.usage
        return CallResult(text=text, model_version=resp.model, finish_reason=resp.stop_reason,
                          tokens_in=usage.input_tokens, tokens_out=usage.output_tokens, latency_ms=latency,
                          effective_temperature=eff_t, effective_max_tokens=max_tokens,
                          provider_messages=messages,
                          request_params={k: v for k, v in params.items() if k != "messages"})


class OpenAICompatModel:
    def __init__(self, provider: str, model_id: str, temperature: Optional[float], max_tokens_cap: int,
                 timeout: float = 60.0, answer_mode: str = "constrained"):
        import openai
        key = api_key(provider)
        if not key:
            raise FatalModelError(f"{PROVIDER_ENV[provider]} is not set (add it on the API & Models page)")
        base_url = "https://api.deepseek.com" if provider == "deepseek" else None
        self._openai = openai
        self._client = openai.OpenAI(api_key=key, base_url=base_url, max_retries=0, timeout=timeout)
        self.provider = provider
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens_cap = max_tokens_cap
        self.reasoning = bool(re.match(r"^(o\d|gpt-5)", model_id))
        self.answer_mode = answer_mode

    def complete(self, prompt: str, call_seed: int, labels_shown=None) -> CallResult:
        del call_seed
        messages = [{"role": "user", "content": prompt}]
        params = {"model": self.model_id, "messages": messages}
        cap = self.max_tokens_cap
        if self.answer_mode == "constrained" and labels_shown:
            params["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "label_choice", "strict": True, "schema": choice_schema(labels_shown)}}
            cap = max(cap, 32)
        if self.provider == "openai":
            params["max_completion_tokens"] = cap
        else:
            params["max_tokens"] = cap
        eff_t = None if self.reasoning else PROVIDER_DEFAULT_TEMPERATURE[self.provider]
        if self.temperature is not None and not self.reasoning:
            params["temperature"] = self.temperature
            eff_t = self.temperature
        o = self._openai
        t0 = time.monotonic()
        try:
            resp = self._client.chat.completions.create(**params)
        except (o.RateLimitError, o.InternalServerError, o.APIConnectionError, o.APITimeoutError) as ex:
            raise RetryableError(f"{type(ex).__name__}: {ex}") from ex
        except o.APIStatusError as ex:
            if ex.status_code in (408, 409, 429) or ex.status_code >= 500:
                raise RetryableError(f"HTTP {ex.status_code}: {ex}") from ex
            raise FatalModelError(f"HTTP {ex.status_code}: {ex}") from ex
        latency = int((time.monotonic() - t0) * 1000)
        choice = resp.choices[0]
        usage = resp.usage
        return CallResult(text=choice.message.content or "", model_version=resp.model,
                          finish_reason=choice.finish_reason,
                          tokens_in=getattr(usage, "prompt_tokens", None),
                          tokens_out=getattr(usage, "completion_tokens", None), latency_ms=latency,
                          effective_temperature=eff_t, effective_max_tokens=cap,
                          provider_messages=messages,
                          request_params={k: v for k, v in params.items() if k != "messages"})


def make_model(spec):
    mode = getattr(spec, "answer_mode", "constrained")
    if spec.provider == "mock":
        return MockModel(spec.model_id, spec.mock_mode, spec.mock_invalid_rate, answer_mode=mode)
    if spec.provider == "anthropic":
        return AnthropicModel(spec.model_id, spec.temperature, spec.max_tokens_cap, answer_mode=mode)
    return OpenAICompatModel(spec.provider, spec.model_id, spec.temperature, spec.max_tokens_cap, answer_mode=mode)


def call_seed(seed: int, round_idx: int, agent_idx: int, attempt: int) -> int:
    h = hashlib.sha256(f"{seed}|{round_idx}|{agent_idx}|{attempt}".encode()).digest()
    return int.from_bytes(h[:8], "little")
