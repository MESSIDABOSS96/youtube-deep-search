"""Provider-agnostic LLM access via litellm (SPEC §8, §9).

One thin wrapper so every stage makes the same kind of call regardless of provider
(Anthropic / OpenAI / Gemini / local Ollama). Prompts are plain text + "respond with JSON
matching this schema"; no provider-specific features (no tool-use / structured-output
APIs) so any litellm backend works.

complete_json() requests JSON, parses it, validates against a pydantic model, and retries
once with the validation error appended before failing the item gracefully (SPEC §9).

Also owns the expensive-model heads-up (SPEC §8): if the model matches
config.EXPENSIVE_MODEL_PATTERNS, print a one-line warning and proceed (never block).

TODO(implement): complete_json(), warn_if_expensive().
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


async def complete_json(prompt: str, schema: type[T], model: str) -> T:
    raise NotImplementedError("Call litellm, parse+validate JSON, one retry. SPEC §8–9.")


def warn_if_expensive(model: str) -> None:
    raise NotImplementedError("One-line cost warning per SPEC §8; never block.")
