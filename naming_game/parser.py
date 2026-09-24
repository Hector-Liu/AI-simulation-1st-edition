"""Strict label parser (SPEC §5.7). Never fuzzy-maps to the nearest label."""
from __future__ import annotations

_QUOTES = "\"'`“”‘’"


def normalize(raw: str) -> str:
    s = (raw or "").strip()
    if len(s) >= 2 and s[0] in _QUOTES and s[-1] in _QUOTES:
        s = s[1:-1].strip()
    if s.endswith("."):
        s = s[:-1]
    return s.strip()


def parse_label(raw: str | None, labels) -> str | None:
    """Return the canonical label, or None if the output is invalid."""
    s = normalize(raw or "").lower()
    if not s:
        return None
    matches = [lab for lab in labels if lab.lower() == s]
    return matches[0] if len(matches) == 1 else None
