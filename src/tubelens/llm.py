"""Provider-agnostic LLM access via litellm (SPEC §8, §9).

One thin wrapper so every stage makes the same kind of call regardless of provider
(Anthropic / OpenAI / Gemini / local Ollama). Prompts are plain text + "respond with JSON
matching this schema"; no provider-specific features (no tool-use / structured-output
APIs) so any litellm backend works.

complete_json() requests JSON, parses it, validates against a pydantic model, and retries
once with the validation error appended before failing the item gracefully (SPEC §9).

Also owns the expensive-model heads-up (SPEC §8): if the model matches
config.EXPENSIVE_MODEL_PATTERNS, print a one-line warning and proceed (never block).
"""

from __future__ import annotations

import json
import re
import sys
from typing import TypeVar

import litellm
from pydantic import BaseModel, ValidationError

from .config import EXPENSIVE_MODEL_PATTERNS

T = TypeVar("T", bound=BaseModel)

# Keep litellm from being chatty in the user's terminal.
try:
    litellm.suppress_debug_info = True
    litellm.set_verbose = False
except Exception:
    pass


class LLMError(Exception):
    """An LLM call failed after retries (SPEC §9)."""


def warn_if_expensive(model: str) -> None:
    """SPEC §8: one-line cost warning if the model matches a known-expensive pattern."""
    for pat in EXPENSIVE_MODEL_PATTERNS:
        if re.search(pat, model, re.IGNORECASE):
            print(
                f"tubelens: heads up — '{model}' looks like a frontier/pricier model; "
                "ranking is a judgment task cheap models do well. Proceeding "
                "(expect ~10–30× the default cost). See README §Cost.",
                file=sys.stderr,
            )
            return


def _strip_fences(text: str) -> str:
    """Best-effort extraction of JSON from a model response that may wrap it in fences."""
    text = text.strip()
    if text.startswith("```"):
        # Drop an optional language tag on the first fence.
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```$", "", text.strip())
        return text.strip()
    return text


def _parse_json(text: str) -> object:
    raw = _strip_fences(text)
    # Find the first { or [ to the matching last } or ] as a fallback for chatty models.
    if raw and raw[0] not in "{[":
        start = min(
            (i for i in (raw.find("{"), raw.find("[")) if i != -1),
            default=-1,
        )
        if start != -1:
            raw = raw[start:]
    return json.loads(raw)


async def _raw_complete(prompt: str, model: str) -> str:
    """One litellm call; returns the assistant message content string."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a precise assistant that only outputs valid JSON. "
                "Respond with a single JSON object (or JSON array when asked) and "
                "nothing else — no prose, no markdown fences, no commentary."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    try:
        response = await litellm.acompletion(model=model, messages=messages, temperature=0.2)
    except Exception as exc:  # noqa: BLE001 — surface a clean error, never a traceback.
        raise LLMError(f"LLM call to '{model}' failed: {exc}") from exc
    try:
        return response["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"Unexpected LLM response shape from '{model}': {exc}") from exc


async def complete_json(prompt: str, schema: type[T], model: str) -> T:
    """Call the LLM, parse+validate JSON against `schema`, retry once (SPEC §9).

    On malformed JSON or validation failure, the call is retried once with the error
    message appended so the model can self-correct. If it still fails, raises LLMError so
    the caller can drop that item gracefully.
    """
    content = await _raw_complete(prompt, model)
    try:
        data = _parse_json(content)
        return schema.model_validate(data)
    except (json.JSONDecodeError, ValidationError, ValueError) as first_err:
        retry_prompt = (
            prompt
            + f"\n\nYour previous response was not valid: {first_err}\n"
            "Please respond again with strictly valid JSON matching the schema, "
            "and nothing else."
        )
        content = await _raw_complete(retry_prompt, model)
        try:
            data = _parse_json(content)
            return schema.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(
                f"LLM returned invalid JSON for {schema.__name__} after retry: {exc}"
            ) from exc


async def complete_json_list(prompt: str, item_schema: type[T], model: str) -> list[T]:
    """Like complete_json but for a JSON array validated element-by-element (SPEC §6.4).

    Used by triage, where the LLM returns a list. One retry with the error appended; on
    failure returns an empty list so the caller can fall back (SPEC §9).
    """
    content = await _raw_complete(prompt, model)
    try:
        data = _parse_json(content)
        if not isinstance(data, list):
            raise ValueError("expected a JSON array")
        return [item_schema.model_validate(item) for item in data]
    except Exception as first_err:  # noqa: BLE001
        retry_prompt = (
            prompt
            + f"\n\nYour previous response was not a valid JSON array: {first_err}\n"
            "Please respond again with strictly a JSON array matching the schema, "
            "and nothing else."
        )
        content = await _raw_complete(retry_prompt, model)
        try:
            data = _parse_json(content)
            if not isinstance(data, list):
                raise ValueError("expected a JSON array")
            return [item_schema.model_validate(item) for item in data]
        except Exception as exc:  # noqa: BLE001
            print(
                f"tubelens: warning — LLM JSON parse failed after retry ({exc}); "
                "falling back for this batch.",
                file=sys.stderr,
            )
            return []
