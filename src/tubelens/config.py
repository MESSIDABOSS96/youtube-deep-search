"""Configuration resolution (SPEC §4, §5, §8).

Precedence: CLI flags > env vars > config file (~/.config/tubelens/config.toml) > defaults.
Also detects which provider key is present and errors with the exact env var name needed
when the chosen model's key is missing (SPEC §8, §9).

TODO(implement): load/merge sources, validate, expose a typed Config object.
"""

from __future__ import annotations

from pydantic import BaseModel

# SPEC §6.4: deep-read pool must never be smaller than --results.
DEFAULT_RESULTS = 10
DEFAULT_SCAN = 80
MAX_SCAN = 200
DEFAULT_MODEL = "anthropic/claude-haiku-4-5"

# SPEC §8: passing one of these triggers a one-line cost warning (never blocks).
EXPENSIVE_MODEL_PATTERNS = [r"opus", r"gpt-4o(?!-mini)", r"o1", r"gemini-.*-pro"]


def deep_read_count(results: int) -> int:
    """SPEC §6.4: max(15, results + 5) so 'more results' stays 'more quality results'."""
    return max(15, results + 5)


class Config(BaseModel):
    """Resolved run configuration. TODO(implement): fill per SPEC §5."""

    query: str
    results: int = DEFAULT_RESULTS
    scan: int = DEFAULT_SCAN
    model: str = DEFAULT_MODEL
    triage_model: str | None = None  # defaults to `model`
    brief: bool = True
    clarify: bool = True
    open_report: bool = True
    lang: str = "en"


def load_config() -> Config:  # noqa: D401
    raise NotImplementedError("Resolve flags/env/config-file/defaults per SPEC §4–5, §8.")
