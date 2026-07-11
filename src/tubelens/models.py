"""Pydantic schemas shared across the pipeline (SPEC §6, §10).

These typed models are the contract between stages: the YouTube layer produces
`Candidate`s, triage attaches `TriageResult`s, deep-read attaches `DeepResult`s, and the
report renders from the combined objects. LLM outputs are validated against these so
malformed JSON is caught and retried (SPEC §9).

TODO(implement): flesh out fields per the JSON shapes in SPEC §6.1, §6.4, §6.5, §6.6.
"""

from __future__ import annotations

from pydantic import BaseModel


class ClarifyExpand(BaseModel):
    """Output of the clarify-gate + query-expansion call (SPEC §6.1)."""

    ambiguous: bool
    clarifying_questions: list[str]
    search_queries: list[str]
    intent_summary: str


class Candidate(BaseModel):
    """A YouTube video under consideration, hydrated with metadata and transcript.

    SPEC §6.2–6.3. `transcript` segments preserve timestamps to power jump links.
    Videos without a transcript are kept with `transcript=None` and surfaced in the
    coverage table (trust requirement, SPEC §7.3).
    """

    video_id: str
    title: str
    channel: str
    # ...duration, views, thumbnail_url, transcript segments, status flags — see SPEC.


class TriageResult(BaseModel):
    """Stage-1 cheap score for a single candidate (SPEC §6.4)."""

    video_id: str
    score: float  # 0–10 likelihood the content addresses the intent
    reason: str  # ~5 words, shown in the coverage table


class DeepResult(BaseModel):
    """Stage-2 deep-read score for a top candidate (SPEC §6.5)."""

    video_id: str
    score: float  # 0–10 content match to intent
    why: str
    best_timestamp_seconds: int
    timestamp_reason: str
    key_points: list[str]


class Playbook(BaseModel):
    """Synthesized brief over the top results (SPEC §6.6).

    Each point must cite >=1 source video so the brief is verifiable, not hand-wavy.
    """

    title: str
    points: list[str]  # TODO: model per-point source citations, not just strings
