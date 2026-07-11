"""Configuration resolution (SPEC §4, §5, §8).

Precedence: CLI flags > env vars > config file (~/.config/tubelens/config.toml) > defaults.
Also detects which provider key is present and errors with the exact env var name needed
when the chosen model's key is missing (SPEC §8, §9).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import tomllib
from pydantic import BaseModel, Field

# SPEC §6.4: deep-read pool must never be smaller than --results.
DEFAULT_RESULTS = 10
DEFAULT_SCAN = 80
MAX_SCAN = 200
# No default model on purpose — the user must choose one explicitly. This keeps the tool
# provider-neutral and stops it silently spending money on an assumed provider.

CONFIG_DIR = Path("~/.config/tubelens").expanduser()
CONFIG_FILE = CONFIG_DIR / "config.toml"

# SPEC §8: passing one of these triggers a one-line cost warning (never blocks).
EXPENSIVE_MODEL_PATTERNS = [r"opus", r"gpt-4o(?!-mini)", r"o1", r"gemini-.*-pro"]

# Provider prefix -> env var holding the key (SPEC §8). None = no key required (local).
PROVIDER_KEYS: dict[str, str | None] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "azure": "AZURE_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "nvidia_nim": "NVIDIA_NIM_API_KEY",  # free API access via build.nvidia.com
    "ollama": None,
}


def deep_read_count(results: int) -> int:
    """SPEC §6.4: max(15, results + 5) so 'more results' stays 'more quality results'."""
    return max(15, results + 5)


# A short, curated set of good models per provider, shown in the interactive picker
# (SPEC §8). Suggestions only — any litellm model string still works via --model. The
# first entry per provider is the recommended default. Providers are listed neutrally;
# only those the user actually has a key for (or Ollama, if installed) are ever shown.
RECOMMENDED_MODELS: dict[str, list[tuple[str, str]]] = {
    "anthropic": [
        ("anthropic/claude-haiku-4-5", "cheap, fast"),
        ("anthropic/claude-sonnet-5", "smarter, pricier"),
    ],
    "openai": [
        ("openai/gpt-4o-mini", "cheap, fast"),
        ("openai/gpt-4o", "smarter, pricier"),
    ],
    "gemini": [
        ("gemini/gemini-1.5-flash", "cheap, fast"),
        ("gemini/gemini-1.5-pro", "smarter, pricier"),
    ],
    "groq": [
        ("groq/llama-3.1-8b-instant", "fast"),
        ("groq/llama-3.3-70b-versatile", "smarter"),
    ],
    "mistral": [
        ("mistral/mistral-small-latest", "cheap, fast"),
        ("mistral/mistral-large-latest", "smarter"),
    ],
    "cohere": [
        ("cohere/command-r", "cheap, fast"),
        ("cohere/command-r-plus", "smarter"),
    ],
    "nvidia_nim": [
        ("nvidia_nim/meta/llama-3.1-8b-instruct", "free tier, fast"),
        ("nvidia_nim/meta/llama-3.3-70b-instruct", "free tier, smarter"),
    ],
    "ollama": [
        ("ollama/llama3.1", "local, no key"),
    ],
}


def available_model_choices() -> list[tuple[str, str]]:
    """(model_string, label) for every provider the user can actually use right now.

    A provider qualifies if its key env var is set; Ollama qualifies if it's installed.
    Used by the interactive picker so a first-time user selects from a list instead of
    memorizing a model string.
    """
    choices: list[tuple[str, str]] = []
    for provider, models in RECOMMENDED_MODELS.items():
        if provider == "ollama":
            if shutil.which("ollama") is None:
                continue
        else:
            env_var = PROVIDER_KEYS.get(provider)
            if not env_var or not os.environ.get(env_var):
                continue
        choices.extend(models)
    return choices


def no_model_message() -> str:
    """Friendly 'you must pick a model' message for non-interactive runs (no TTY)."""
    return (
        "No model selected — tubelens has no default; you must choose one.\n\n"
        "Pass --model, or set TUBELENS_MODEL to avoid typing it each time. For example:\n"
        "  --model anthropic/claude-haiku-4-5   (or openai/..., gemini/..., etc.)\n"
        "  --model ollama/llama3.1              (local, no key)\n"
        "  --model nvidia_nim/meta/llama-3.1-8b-instruct   (NVIDIA free tier)\n\n"
        "See the provider table in the README for all options."
    )


class ConfigError(Exception):
    """Raised when configuration is missing/invalid; surfaced as a friendly message."""


class Config(BaseModel):
    """Resolved run configuration (SPEC §5)."""

    query: str
    results: int = DEFAULT_RESULTS
    scan: int = DEFAULT_SCAN
    model: str = ""  # required in practice; load_config() rejects an empty model
    triage_model: str
    brief: bool = True
    clarify: bool = True
    open_report: bool = True
    lang: str = "en"
    out: str | None = None
    json_output: bool = Field(default=False, alias="json")
    verbose: bool = False

    youtube_api_key: str = ""

    def deep_read_count(self) -> int:
        return deep_read_count(self.results)

    def validate_youtube_key(self) -> None:
        """SPEC §9: the YouTube key is always required, whatever the model."""
        if not self.youtube_api_key:
            raise ConfigError(
                "YOUTUBE_API_KEY is not set. Create a YouTube Data API v3 key at "
                "https://console.cloud.google.com/apis/credentials (enable "
                "'YouTube Data API v3'), then:\n\n"
                "    export YOUTUBE_API_KEY=\"your-key\"\n\n"
                "The YouTube key is always required — candidate videos come from "
                "the Data API. See README §Setup."
            )

    def validate_model_key(self) -> None:
        """SPEC §8, §9: the chosen model's provider key must be present."""
        env_var = required_key_for_model(self.model)
        if env_var is not None and not os.environ.get(env_var):
            raise ConfigError(
                f"The model '{self.model}' needs the {env_var} environment variable, "
                f"but it is not set.\n\n"
                f"    export {env_var}=\"your-key\"\n\n"
                "Or use a local model that needs no key, e.g. "
                f"--model ollama/llama3.1. See README §Setup."
            )

    def validate_keys(self) -> None:
        """Validate both keys (kept for callers/tests that want a single check)."""
        self.validate_youtube_key()
        self.validate_model_key()


def required_key_for_model(model: str) -> str | None:
    """Return the env var name required for a litellm model string, or None if no key."""
    provider = model.split("/", 1)[0].lower() if "/" in model else ""
    if provider in PROVIDER_KEYS:
        return PROVIDER_KEYS[provider]
    # Unknown provider: assume a cloud key is needed but we can't name it precisely.
    if not provider:
        return "ANTHROPIC_API_KEY"
    return f"{provider.upper()}_API_KEY"


def _load_config_file() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    try:
        with CONFIG_FILE.open("rb") as f:
            return tomllib.load(f).get("tubelens", {})
    except Exception:
        return {}


def load_config(args: Any) -> Config:
    """Resolve flags > env > config file > defaults (SPEC §4, §5, §8).

    `args` is an argparse Namespace. Only `query` is required from the CLI.
    """
    file_cfg = _load_config_file()

    def pick(flag_name: str, env_name: str, default: Any, cast: type | None = None) -> Any:
        val = getattr(args, flag_name, None)
        if val is None:
            val = os.environ.get(env_name)
        if val is None:
            val = file_cfg.get(flag_name, file_cfg.get(env_name.lower(), default))
        if cast is bool:
            if isinstance(val, str):
                return val.lower() in ("1", "true", "yes", "on")
            return bool(val)
        if cast is int and val is not None:
            return int(val)
        return val

    # No default model. If unset, it stays "" here; main() resolves it via the
    # interactive picker (TTY) or the no_model_message() error (non-interactive).
    model = pick("model", "TUBELENS_MODEL", None) or ""
    triage_model = pick("triage_model", "TUBELENS_TRIAGE_MODEL", None) or model
    results = pick("results", "TUBELENS_RESULTS", DEFAULT_RESULTS, int)
    scan = pick("scan", "TUBELENS_SCAN", DEFAULT_SCAN, int)
    if scan > MAX_SCAN:
        scan = MAX_SCAN

    cfg = Config(
        query=args.query,
        results=results,
        scan=scan,
        model=model,
        triage_model=triage_model,
        brief=not getattr(args, "no_brief", False),
        clarify=not getattr(args, "no_clarify", False),
        open_report=getattr(args, "open", True),
        lang=pick("lang", "TUBELENS_LANG", "en"),
        out=getattr(args, "out", None),
        json_output=getattr(args, "json", False),
        verbose=getattr(args, "verbose", False),
        youtube_api_key=os.environ.get("YOUTUBE_API_KEY", ""),
    )
    return cfg
