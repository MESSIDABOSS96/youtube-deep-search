"""Playbook synthesis (SPEC §6.6).

One LLM call over the top ~6 deep-read results' key_points/why/metadata. Produces a titled
brief of 3–6 actionable points; every point must cite >=1 source video by index so the
brief is verifiable. Synthesize only from provided material (no outside knowledge); if the
videos disagree, say so. Skipped entirely when --no-brief.

TODO(implement): synthesize_playbook().
"""

from __future__ import annotations

from .models import Candidate, DeepResult, Playbook


async def synthesize_playbook(
    top: list[tuple[Candidate, DeepResult]], intent: str, model: str
) -> Playbook:
    raise NotImplementedError("Implement per SPEC §6.6 (cite sources per point).")
