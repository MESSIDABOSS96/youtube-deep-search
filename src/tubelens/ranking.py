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
"""

from __future__ import annotations

import asyncio
import json

from .llm import LLMError, complete_json, complete_json_list
from .models import Candidate, ClarifyExpand, DeepResult, TierAssignment, TriageResult
from .transcripts import chunk_for_deep_read, excerpt_for_digest

CLARIFY_PROMPT = """\
You are helping build a content-aware YouTube search tool.

The user asked (verbatim):
\"\"\"{query}\"\"\"

Your job has two parts, done in a single response as JSON:

1. CLARIFY GATE — decide if the query is ambiguous enough to need clarifying questions.
   Apply the "results-changing" test: a question is allowed ONLY IF different plausible
   answers would lead to materially different YouTube search queries or a materially
   different ranking of videos. If every answer would produce the same searches and the
   same best videos, the question is forbidden — it only adds friction.
   - Good example, "elbow pain from golf": "Is the pain on the inside or outside of the
     elbow?" — good: inside (golfer's elbow) vs outside (tennis elbow) are different
     conditions with different videos.
   - Forbidden example: "Which arm is affected — left or right?" — the rehab content is the
     same regardless of arm; no answer changes the results.
   Rule of thumb: before asking, state how each possible answer would change the search.
   If you can't, don't ask. Prefer asking ZERO questions over a weak one. Cap at the single
   most results-changing question when possible; never more than two.
2. QUERY EXPANSION — produce 4 to 7 YouTube keyword search queries that would surface the
   best videos for this intent. Mix (a) direct keyword forms of the intent, (b) adjacent
   phrasings practitioners would use, and (c) one broader umbrella query. These must be
   plain YouTube search strings, not natural-language questions.

Also write a one-sentence `intent_summary` restating what the user actually wants.

Respond with ONLY a JSON object matching this schema:
{{
  "ambiguous": <true if clarifying questions are needed>,
  "clarifying_questions": ["..."],
  "search_queries": ["...", "..."],
  "intent_summary": "one sentence"
}}
{no_clarify}
"""

CLARIFY_NO_CLARIFY = (
    '\nDo NOT ask any clarifying questions: set "ambiguous" to false and '
    '"clarifying_questions" to []'
)


def _build_digest(c: Candidate) -> str:
    """Compact candidate digest for stage-1 triage (SPEC §6.4): <= ~300 tokens."""
    mins = c.duration_seconds // 60
    secs = c.duration_seconds % 60
    dur = f"{mins}:{secs:02d}" if c.duration_seconds else "?"
    views = f"{c.view_count:,}" if c.view_count else "?"
    excerpt = excerpt_for_digest(c.transcript or [])
    return (
        f"video_id: {c.video_id}\n"
        f"title: {c.title}\n"
        f"channel: {c.channel}\n"
        f"duration: {dur}\n"
        f"views: {views}\n"
        f"transcript excerpts:\n{excerpt}"
    )


def _triage_prompt(batch: list[Candidate], intent: str) -> str:
    digests = "\n\n---\n\n".join(f"# {i}\n{_build_digest(c)}" for i, c in enumerate(batch))
    ids = [c.video_id for c in batch]
    return (
        "You are ranking YouTube videos by how well their *content* (transcript) "
        "addresses a user's intent — not by their titles.\n\n"
        f"USER INTENT: {intent}\n\n"
        f"Here are {len(batch)} candidate videos. For each, score 0–10 the likelihood "
        "that the video's actual content addresses the intent, and give a ~5-word reason.\n\n"
        f"CANDIDATES:\n{digests}\n\n"
        f"Respond with ONLY a JSON array, one entry per candidate, in this exact shape, "
        f"with video_id taken from the digest:\n"
        "  [\n"
        '    {"video_id": "AbC123", "score": 7.5,'
        '     "reason": "covers pre-launch waitlist tactics"},\n'
        "    ...\n"
        f"  ]\n"
        f"The video_ids must be exactly: {json.dumps(ids)}"
    )


TRIAGE_BATCH_SIZE = 40  # keep each triage call comfortably within context.


async def clarify_and_expand(query: str, model: str, allow_clarify: bool) -> ClarifyExpand:
    """SPEC §6.1: one LLM call does the clarify gate + query expansion."""
    prompt = CLARIFY_PROMPT.format(
        query=query,
        no_clarify=CLARIFY_NO_CLARIFY if not allow_clarify else "",
    )
    try:
        return await complete_json(prompt, ClarifyExpand, model)
    except LLMError:
        # Fall back to a safe single-query expansion so the run can still proceed.
        return ClarifyExpand(
            ambiguous=False,
            clarifying_questions=[],
            search_queries=[query],
            intent_summary=query,
        )


async def triage(
    candidates: list[Candidate], intent: str, model: str
) -> list[TriageResult]:
    """SPEC §6.4: 1–2 batched calls over ALL candidates, never per-video."""
    if not candidates:
        return []
    batches = [
        candidates[i : i + TRIAGE_BATCH_SIZE]
        for i in range(0, len(candidates), TRIAGE_BATCH_SIZE)
    ]
    results: list[TriageResult] = []
    # Run batches sequentially (only 1–2 of them) to stay within 1–2 calls total.
    for batch in batches:
        try:
            batch_results = await complete_json_list(
                _triage_prompt(batch, intent), TriageResult, model
            )
        except LLMError:
            batch_results = []
        if not batch_results:
            # Fall back: neutral score so deep-read selection degrades to found order
            # (SPEC §9 — note the fallback in the report via the returned empty list).
            batch_results = [
                TriageResult(video_id=c.video_id, score=5.0, reason="triage unavailable")
                for c in batch
            ]
        results.extend(batch_results)
    # Keep only results matching a known candidate (drop hallucinated ids).
    known = {c.video_id for c in candidates}
    return [r for r in results if r.video_id in known]


async def _deep_rank_one(candidate: Candidate, intent: str, model: str) -> DeepResult | None:
    transcript = candidate.transcript or []
    body = chunk_for_deep_read(transcript, relevance_hint=intent)
    prompt = (
        "You are ranking a single YouTube video by how well its actual *content* "
        "(the transcript) addresses a user's intent. Read the whole transcript; rank on "
        "what is said, not the title.\n\n"
        f"USER INTENT: {intent}\n\n"
        f"VIDEO TITLE: {candidate.title}\n"
        f"CHANNEL: {candidate.channel}\n"
        f"VIDEO_ID: {candidate.video_id}\n\n"
        f"TRANSCRIPT (with timestamps):\n{body}\n\n"
        "SCORING ANCHORS — calibrate hard against these, do not default to 7–9:\n"
        "  9–10: essentially the whole video directly addresses this exact intent\n"
        "  7–8:  a substantial section addresses it directly\n"
        "  4–6:  touches the intent but mostly covers something else\n"
        "  0–3:  barely or not related\n\n"
        "Respond with ONLY a JSON object matching this schema:\n"
        "{\n"
        '  "video_id": "<the video_id above>",\n'
        '  "score": <0–10 per the anchors>,\n'
        '  "why": "<MAX 12 words. Start with a verb. What it covers for this intent.>",\n'
        '  "best_timestamp_seconds": <integer seconds where the key moment starts>,\n'
        '  "timestamp_reason": "<MAX 6 words>",\n'
        '  "key_points": ["<2–4 bullets, MAX 8 words each>"],\n'
        '  "coverage": "<exactly one of: whole video | one section | brief mention>"\n'
        "}\n"
        "Be terse. No filler like 'this video' or 'the creator discusses'."
    )
    try:
        result = await complete_json(prompt, DeepResult, model)
    except LLMError:
        return None
    # Ensure the video_id matches (defensive).
    if result.video_id != candidate.video_id:
        result = result.model_copy(update={"video_id": candidate.video_id})
    return result


DEEP_RANK_CONCURRENCY = 5


async def deep_rank(
    top: list[Candidate], intent: str, model: str
) -> list[DeepResult]:
    """SPEC §6.5: parallel per-video full-transcript reads, bounded to 5 concurrent."""
    if not top:
        return []
    sem = asyncio.Semaphore(DEEP_RANK_CONCURRENCY)

    async def guarded(c: Candidate) -> DeepResult | None:
        async with sem:
            return await _deep_rank_one(c, intent, model)

    results = await asyncio.gather(*(guarded(c) for c in top))
    return [r for r in results if r is not None]


def tier_from_score(score: float) -> str:
    """Deterministic fallback tiering when the comparative pass is unavailable."""
    if score >= 7.5:
        return "strong"
    if score >= 5.0:
        return "partial"
    return "weak"


async def comparative_rank(
    pairs: list[tuple[Candidate, DeepResult]], intent: str, model: str
) -> list[TierAssignment] | None:
    """Final calibration pass: order ALL deep-read videos relative to each other.

    Per-video deep-read scores come from isolated calls — the model never sees two
    videos together, so scores cluster at 7–9 and cross-video ordering is noise.
    One cheap call that compares compact summaries side by side is far more reliable
    at *relative* judgment, and it assigns each video an explicit tier
    (strong / partial / weak) that the report displays instead of a bare number.

    Returns the assignments in best-to-worst order, or None on failure (caller falls
    back to score order + tier_from_score).
    """
    if len(pairs) < 2:
        return None
    lines = []
    for c, d in pairs:
        points = "; ".join(d.key_points) or "(none)"
        lines.append(
            f"- video_id: {c.video_id}\n"
            f"  title: {c.title}\n"
            f"  isolated_score: {d.score}\n"
            f"  coverage: {d.coverage or '?'}\n"
            f"  why: {d.why}\n"
            f"  key_points: {points}"
        )
    ids = [c.video_id for c, _ in pairs]
    prompt = (
        "You are the final ranking judge for a content-aware YouTube search. Below are "
        "summaries of videos that were each scored in ISOLATION (so their scores are not "
        "comparable). Compare them side by side and produce the definitive best-to-worst "
        "ordering for the user's intent.\n\n"
        f"USER INTENT: {intent}\n\n"
        f"VIDEOS:\n{chr(10).join(lines)}\n\n"
        "Judge by: how directly the content addresses the intent, and how much of the "
        "video does (coverage). Ignore popularity. Also assign each video a tier:\n"
        '  "strong"  — watch this; it directly addresses the intent\n'
        '  "partial" — a useful section or angle, but not the main focus\n'
        '  "weak"    — related to the topic but focused on something other than the intent\n\n'
        'For every "partial" or "weak" video, also write a `note`: MAX 12 words stating '
        "how it relates to the intent but diverges from it, in the form "
        '"covers X, not Y" or "X generally, not Y specifically". These videos are '
        "adjacent, not junk — the note tells the user what they'd actually get. "
        'Leave `note` empty ("") for "strong" videos.\n\n'
        "Respond with ONLY a JSON array, best first, one entry per video:\n"
        '  [{"video_id": "...", "tier": "strong", "note": ""},\n'
        '   {"video_id": "...", "tier": "weak",'
        ' "note": "covers post-launch ASO, not pre-launch"}, ...]\n'
        f"Include every video_id exactly once from: {json.dumps(ids)}"
    )
    try:
        out = await complete_json_list(prompt, TierAssignment, model)
    except LLMError:
        return None
    known = set(ids)
    out = [t for t in out if t.video_id in known]
    seen: set[str] = set()
    deduped = [t for t in out if not (t.video_id in seen or seen.add(t.video_id))]
    # Require full coverage of the pool — a partial ordering is worse than the fallback.
    if len(deduped) != len(ids):
        return None
    return deduped
