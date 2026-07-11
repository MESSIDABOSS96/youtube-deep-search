"""Configuration resolution (SPEC §4, §5, §8).

Precedence: CLI flags > env vars > config file (~/.config/tubelens/config.toml) > defaults.
Also detects which provider key is present and errors with the exact env var name needed
when the chosen model's key is missing (SPEC §8, §9).
"""

from __future__ import annotations

import os
import re
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


# Where to create each key, shown inline when a key is missing so a first-time user knows
# what to do next instead of hitting a dead end. Free tiers noted where they exist.
KEY_SETUP_HELP: dict[str, str] = {
    "YOUTUBE_API_KEY": (
        "Get one free at https://console.cloud.google.com/apis/credentials "
        "(enable 'YouTube Data API v3')."
    ),
    "ANTHROPIC_API_KEY": "Get one at https://console.anthropic.com/settings/keys",
    "OPENAI_API_KEY": "Get one at https://platform.openai.com/api-keys",
    "GEMINI_API_KEY": "Get one free at https://aistudio.google.com/apikey",
    "GROQ_API_KEY": "Get one free at https://console.groq.com/keys",
    "MISTRAL_API_KEY": "Get one at https://console.mistral.ai/api-keys",
    "COHERE_API_KEY": "Get one at https://dashboard.cohere.com/api-keys",
    "NVIDIA_NIM_API_KEY": (
        "Get one free at https://build.nvidia.com (open a model, then 'Get API Key')."
    ),
}


def key_setup_help(env_var: str) -> str:
    """A short 'here's where to create this key' hint, or '' if we don't have one."""
    return KEY_SETUP_HELP.get(env_var, "")


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
                "'YouTube Data API v3'), then add this line to ~/.zshrc so it "
                "persists across terminal restarts:\n\n"
                "    export YOUTUBE_API_KEY=\"your-key\"\n\n"
                "Then run `source ~/.zshrc` (or open a new terminal). The YouTube key "
                "is always required — candidate videos come from the Data API. "
                "See README §Setup."
            )

    def validate_model_key(self) -> None:
        """SPEC §8, §9: the chosen model's provider key must be present."""
        env_var = required_key_for_model(self.model)
        if env_var is not None and not os.environ.get(env_var):
            raise ConfigError(
                f"The model '{self.model}' needs the {env_var} environment variable, "
                f"but it is not set.\n\n"
                f"Add this line to ~/.zshrc so it persists across terminal restarts, "
                f"then run `source ~/.zshrc` (or open a new terminal):\n\n"
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


def _toml_value(val: Any) -> str:
    """Serialize a scalar/string-list into TOML. Only the value types we ever store."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, list):
        return "[" + ", ".join(_toml_value(v) for v in val) + "]"
    # string: escape backslashes and quotes for a basic double-quoted TOML string
    escaped = str(val).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def shell_rc_file() -> Path | None:
    """The shell startup file we can safely add an `export` line to, or None.

    Only zsh and bash use `export VAR=...` syntax, so we only offer to edit those. For
    fish or an unknown shell we return None (the caller falls back to env-only + manual
    instructions) rather than writing a line that wouldn't work.
    """
    shell = os.environ.get("SHELL", "")
    home = Path("~").expanduser()
    if "zsh" in shell:
        return home / ".zshrc"
    if "bash" in shell:
        # macOS login shells read .bash_profile; Linux reads .bashrc. Prefer whichever
        # already exists so the export lands where the shell will actually load it.
        for name in (".bash_profile", ".bashrc"):
            if (home / name).exists():
                return home / name
        return home / ".bashrc"
    return None


def _shell_escape(value: str) -> str:
    """Escape a value for use inside a double-quoted shell string."""
    for ch in ("\\", '"', "$", "`"):
        value = value.replace(ch, "\\" + ch)
    return value


def save_key_to_shell_config(env_var: str, key: str, rc: Path | None = None) -> tuple[Path, str]:
    """Append `export <env_var>="<key>"` to the shell rc file so it loads every session.

    Returns (path, status) where status is:
      - "written": a new export line was appended.
      - "already_present": an export for this var already exists; left untouched to avoid
        clobbering a possibly-different value (the caller handles the current run in memory).

    Raises if there is no supported rc file or the write fails; the caller reports it.
    """
    rc = rc or shell_rc_file()
    if rc is None:
        raise ConfigError("no supported shell startup file (zsh/bash) detected")
    if rc.exists():
        try:
            content = rc.read_text(encoding="utf-8")
        except Exception:
            content = ""
        if re.search(rf"^\s*export\s+{re.escape(env_var)}=", content, re.M):
            return rc, "already_present"
    with rc.open("a", encoding="utf-8") as f:
        f.write(f'\nexport {env_var}="{_shell_escape(key)}"\n')
    return rc, "written"


def save_config_values(updates: dict[str, Any]) -> None:
    """Persist settings to ~/.config/tubelens/config.toml so they survive restarts.

    Merges `updates` into the existing [tubelens] table (preserving any hand-added keys)
    and rewrites the file. Best-effort: never raises — a config that can't be written
    should not break the run (the value still applies to the current run in memory).

    No secrets are written here. API keys live only in the environment (SPEC §8); this
    file holds non-sensitive preferences like the chosen model.
    """
    try:
        existing = _load_config_file()
        merged = {**existing, **updates}
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        lines = ["[tubelens]"]
        for key, val in merged.items():
            lines.append(f"{key} = {_toml_value(val)}")
        CONFIG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


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
