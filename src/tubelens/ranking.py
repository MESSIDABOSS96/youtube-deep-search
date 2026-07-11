"""All ranking LLM calls (SPEC §6.1, §6.4, §6.5).

Three responsibilities:
  1. clarify_and_expand()  — one call: clarify gate + query expansion (SPEC §6.1).
       The clarify gate applies the "results-changing" test — only ask a question if
       different answers would lead to different searches/rankings. See SPEC §6.1 for the
       golf example (inside/outside elbow = ask; which arm = never ask).
  2. triage()              — 1–2 batched calls scoring ALL candidates cheaply (SPEC §6.4).
  3. deep_rank()           — parallel per-video full-transcript reads of the top pool
                             (size = config.deep_read_count, SPEC §6.4/§6.5).

All calls go through llm.complete_json() (provider-agnostic via litellm) and are validated
against models.py schemas with one retry on malformed JSON (SPEC §9).

TODO(implement): the three functions and their prompts.
"""

from __future__ import annotations

from .models import Candidate, ClarifyExpand, DeepResult, TriageResult


async def clarify_and_expand(query: str, model: str, allow_clarify: bool) -> ClarifyExpand:
    raise NotImplementedError("Implement per SPEC §6.1 (results-changing clarify test).")


async def triage(
    candidates: list[Candidate], intent: str, model: str
) -> list[TriageResult]:
    raise NotImplementedError("Implement per SPEC §6.4 (batched, cheap, never per-video).")


async def deep_rank(
    top: list[Candidate], intent: str, model: str
) -> list[DeepResult]:
    raise NotImplementedError("Implement per SPEC §6.5.")
