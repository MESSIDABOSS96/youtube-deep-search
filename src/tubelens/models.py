"""Pydantic schemas shared across the pipeline (SPEC §6, §10).

These typed models are the contract between stages: the YouTube layer produces
`Candidate`s, triage attaches `TriageResult`s, deep-read attaches `DeepResult`s, and the
report renders from the combined objects. LLM outputs are validated against these so
malformed JSON is caught and retried (SPEC §9).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CandidateStatus(str, Enum):
    """Lifecycle of a candidate, surfaced in the coverage table (SPEC §7.2)."""

    FOUND = "found"
    DEEP_READ = "deep-read"
    TRIAGED_OUT = "triaged out"
    NO_TRANSCRIPT = "no transcript"
    RATE_LIMITED = "skipped: rate-limited"
    FILTERED_SHORT = "filtered: short"
    FILTERED_LIVE = "filtered: live"
    FILTERED_LANG = "filtered: lang"


class TranscriptSegment(BaseModel):
    """One caption segment; `start` (seconds) powers the jump-to links (SPEC §6.3)."""

    start: float
    duration: float = 0.0
    text: str


class ClarifyExpand(BaseModel):
    """Output of the clarify-gate + query-expansion call (SPEC §6.1)."""

    ambiguous: bool
    clarifying_questions: list[str] = Field(default_factory=list)
    search_queries: list[str]
    intent_summary: str


class TriageResult(BaseModel):
    """Stage-1 cheap score for a single candidate (SPEC §6.4)."""

    video_id: str
    score: float  # 0–10 likelihood the content addresses the intent
    reason: str  # ~5 words, shown in the coverage table


class DeepResult(BaseModel):
    """Stage-2 deep-read score for a top candidate (SPEC §6.5)."""

    video_id: str
    score: float  # 0–10 content match to intent (calibrated anchors in the prompt)
    why: str  # <= 12 words — concise by contract, enforced in the prompt
    best_timestamp_seconds: int = 0
    timestamp_reason: str = ""  # <= 6 words
    key_points: list[str] = Field(default_factory=list)
    # How much of the video addresses the intent: "whole video" | "one section" |
    # "brief mention". Shown as a chip so an 8 for a fully-on-topic video and an 8 for
    # three relevant minutes inside a vlog stop looking identical.
    coverage: str = ""
    # Tier assigned by the comparative rank pass ("strong" | "partial" | "weak").
    # Set post-hoc in the pipeline, not by the per-video deep-read call.
    tier: str = ""
    # For non-strong matches: how this video relates to the intent but diverges from it
    # ("covers post-launch ASO, not pre-launch"). Set by the comparative pass, which is
    # the only stage that sees the intent and all videos side by side. Frames lower
    # tiers as adjacent-and-possibly-interesting rather than junk.
    relation: str = ""


class TierAssignment(BaseModel):
    """One entry of the comparative rank pass: relative ordering + tier per video.

    Independent per-video scores are uncalibrated (isolated LLM grading clusters at
    7–9), so a final single call compares all deep-read summaries side by side and
    returns an explicit best-to-worst ordering with a tier for each.
    """

    video_id: str
    tier: str  # "strong" | "partial" | "weak"
    # For partial/weak: MAX ~12 words on how the video relates to but diverges from the
    # intent ("covers X, not Y"). Empty for strong matches.
    note: str = ""


class SourceRef(BaseModel):
    """A citation from a playbook point back to a result video (SPEC §6.6, §7.2).

    `video_index` is the 0-based index into the ranked results list rendered in the
    report; `seconds` is the timestamp to deep-link to.
    """

    video_index: int
    seconds: int = 0


class PlaybookPoint(BaseModel):
    """One actionable point in the synthesized brief (SPEC §6.6)."""

    text: str
    sources: list[SourceRef] = Field(default_factory=list)


class Playbook(BaseModel):
    """Synthesized brief over the top results (SPEC §6.6).

    Each point must cite >=1 source video so the brief is verifiable, not hand-wavy.
    """

    title: str
    points: list[PlaybookPoint]


class Candidate(BaseModel):
    """A YouTube video under consideration, hydrated with metadata and transcript.

    SPEC §6.2–6.3. `transcript` segments preserve timestamps to power jump links.
    Videos without a transcript are kept with `transcript=None` and surfaced in the
    coverage table (trust requirement, SPEC §7.3).
    """

    video_id: str
    title: str
    channel: str
    duration_seconds: int = 0
    view_count: int = 0
    thumbnail_url: str = ""
    language: str | None = None
    search_query: str | None = None  # which expanded query surfaced this video

    transcript: list[TranscriptSegment] | None = None
    status: CandidateStatus = CandidateStatus.FOUND

    triage: TriageResult | None = None
    deep: DeepResult | None = None

    @property
    def has_transcript(self) -> bool:
        return self.transcript is not None and len(self.transcript) > 0
