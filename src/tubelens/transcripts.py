"""Transcript fetching (SPEC §6.3).

Uses youtube-transcript-api, preferring manual captions then auto-generated, in --lang
then any available language. Parallel bounded worker pool (~8) with per-video timeout.
Keeps segment timestamps (they power the jump-to links). Videos with no transcript are
marked `no_transcript`, excluded from ranking, but kept for the coverage table
(trust requirement, SPEC §7.3).

Also provides timestamp-preserving chunking used by triage digests (SPEC §6.4) and
deep-read truncation (SPEC §6.5).
"""

from __future__ import annotations

import asyncio
import sys

from .models import Candidate, CandidateStatus, TranscriptSegment

MAX_CONCURRENCY = 8
PER_VIDEO_TIMEOUT_SECONDS = 10

# Rough token estimate: ~4 chars per token.
CHARS_PER_TOKEN = 4
DIGEST_TOKEN_BUDGET = 300
DEEP_READ_CHAR_BUDGET = 24000  # ~6k tokens, roomy for cheap models


def _fetch_sync(video_id: str, lang: str) -> list[dict] | None:
    """Synchronous youtube-transcript-api fetch. Returns raw segment dicts or None.

    Uses the youtube-transcript-api v1.x instance API (``.fetch()`` / ``.list()``),
    converting the returned FetchedTranscript to the raw ``[{text,start,duration}, ...]``
    dicts the rest of this module expects.
    """
    from youtube_transcript_api import YouTubeTranscriptApi  # local import for testability

    prefs = [lang, f"{lang}-US", "en"] if lang else ["en"]
    seen: set[str] = set()
    languages = [x for x in prefs if not (x in seen or seen.add(x))]

    api = YouTubeTranscriptApi()

    # 1. Preferred languages, in order.
    try:
        return api.fetch(video_id, languages=languages).to_raw_data()
    except Exception:
        pass

    # 2. Fallback: any transcript that exists (manual or auto-generated), any language.
    try:
        for transcript in api.list(video_id):
            try:
                return transcript.fetch().to_raw_data()
            except Exception:
                continue
    except Exception:
        return None
    return None


async def _fetch_one(candidate: Candidate, lang: str) -> Candidate:
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(_fetch_sync, candidate.video_id, lang),
            timeout=PER_VIDEO_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raw = None
    except Exception as exc:  # noqa: BLE001
        print(
            f"tubelens: warning — transcript fetch failed for {candidate.video_id}: {exc}",
            file=sys.stderr,
        )
        raw = None

    if not raw:
        candidate.transcript = None
        if candidate.status == CandidateStatus.FOUND:
            candidate.status = CandidateStatus.NO_TRANSCRIPT
        return candidate

    segments: list[TranscriptSegment] = []
    for seg in raw:
        if not isinstance(seg, dict):
            continue
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                start=float(seg.get("start", 0.0)),
                duration=float(seg.get("duration", 0.0)),
                text=text,
            )
        )
    candidate.transcript = segments or None
    if not candidate.transcript and candidate.status == CandidateStatus.FOUND:
        candidate.status = CandidateStatus.NO_TRANSCRIPT
    return candidate


async def fetch_transcripts(candidates: list[Candidate], lang: str) -> list[Candidate]:
    """Attach transcripts (or mark no_transcript). SPEC §6.3.

    Only candidates still in the FOUND state are fetched; already-filtered candidates
    (short/live/lang) are left alone and kept for the coverage table.
    """
    to_fetch = [c for c in candidates if c.status == CandidateStatus.FOUND]
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def guarded(c: Candidate) -> Candidate:
        async with sem:
            return await _fetch_one(c, lang)

    await asyncio.gather(*(guarded(c) for c in to_fetch))
    return candidates


def excerpt_for_digest(transcript: list[TranscriptSegment]) -> str:
    """Build a compact transcript digest: beginning / middle / a relevant chunk.

    Targets <= DIGEST_TOKEN_BUDGET tokens (CHARS_PER_TOKEN heuristic). SPEC §6.4.
    """
    if not transcript:
        return ""
    budget = DIGEST_TOKEN_BUDGET * CHARS_PER_TOKEN
    n = len(transcript)
    thirds = max(1, n // 3)
    head = " ".join(s.text for s in transcript[:thirds])
    mid_start = n // 2
    middle = " ".join(s.text for s in transcript[mid_start : mid_start + thirds])
    excerpt = f"[opening] {head}\n[middle] {middle}"
    if len(excerpt) > budget:
        excerpt = excerpt[:budget]
    return excerpt


def _format_segment(seg: TranscriptSegment) -> str:
    total = int(seg.start)
    mm, ss = divmod(total, 60)
    return f"[{mm:02d}:{ss:02d}] {seg.text}"


def chunk_for_deep_read(
    transcript: list[TranscriptSegment],
    relevance_hint: str | None = None,
    char_budget: int = DEEP_READ_CHAR_BUDGET,
) -> str:
    """Format the full transcript with timestamps, truncated to fit the model context.

    For very long transcripts, keep the head plus a region around the most relevant chunk
    (found by naive keyword match on `relevance_hint`) rather than naive head-truncation
    (SPEC §6.5). Ties the budget back to char count, not token count, for portability.
    """
    if not transcript:
        return ""
    lines = [_format_segment(s) for s in transcript]
    full = "\n".join(lines)
    if len(full) <= char_budget:
        return full

    head_budget = char_budget // 2
    body_budget = char_budget - head_budget

    head = "\n".join(lines[: head_budget // 60 or 1]) if lines else ""

    # Find the segment whose text best matches the relevance hint keywords.
    start_idx = 0
    if relevance_hint:
        keywords = {w.lower().strip(".,;:!?\"'()") for w in relevance_hint.split() if len(w) > 4}
        if keywords:
            best_idx, best_score = 0, -1
            window = 5
            for i in range(len(lines)):
                window_text = " ".join(lines[i : i + window]).lower()
                score = sum(window_text.count(k) for k in keywords)
                if score > best_score:
                    best_score = score
                    best_idx = i
            if best_score > 0:
                start_idx = best_idx

    relevant_lines = lines[start_idx:]
    relevant = "\n".join(relevant_lines)
    if len(relevant) > body_budget:
        relevant = relevant[:body_budget]

    sep = "\n...\n" if relevant else ""
    return f"{head}{sep}{relevant}"
