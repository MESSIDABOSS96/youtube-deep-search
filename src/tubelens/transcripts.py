"""Transcript fetching (SPEC §6.3).

Uses youtube-transcript-api, preferring manual captions then auto-generated, in --lang
then any available language. Keeps segment timestamps (they power the jump-to links).
Videos with no transcript are marked `no_transcript`, excluded from ranking, but kept for
the coverage table (trust requirement, SPEC §7.3).

Rate-limit safety (SPEC §6.3): the transcript endpoint is unofficial and YouTube
IP-throttles bursts of requests. Three defenses keep repeated use from getting a user
blocked: (1) a cross-run cache so each video is fetched at most once ever (see cache.py);
(2) polite fetching — low concurrency plus a small randomized delay between requests; and
(3) a circuit breaker — the first time YouTube returns an IP-block, we stop making further
requests immediately (so we don't deepen the block), proceed with whatever we already
have, and report the truth to the user instead of a misleading "no captions."

Also provides timestamp-preserving chunking used by triage digests (SPEC §6.4) and
deep-read truncation (SPEC §6.5).
"""

from __future__ import annotations

import asyncio
import random

from . import cache
from .models import Candidate, CandidateStatus, TranscriptSegment

# Polite by design: few parallel requests + a small jitter between them, so the request
# pattern doesn't look like a scraper burst (which is what trips YouTube's rate limiter).
MAX_CONCURRENCY = 3
PACING_DELAY_RANGE = (0.2, 0.6)  # seconds of randomized delay before each network fetch
PER_VIDEO_TIMEOUT_SECONDS = 12

# Rough token estimate: ~4 chars per token.
CHARS_PER_TOKEN = 4
DIGEST_TOKEN_BUDGET = 300
DEEP_READ_CHAR_BUDGET = 24000  # ~6k tokens, roomy for cheap models

# Fetch outcomes returned by _fetch_sync.
_OK = "ok"          # got a transcript (data = raw segment dicts)
_EMPTY = "empty"    # video genuinely has no usable transcript
_BLOCKED = "blocked"  # YouTube is rate-limiting / IP-blocking us


def _is_block_error(exc: Exception) -> bool:
    """True if the exception signals an IP block / rate-limit rather than 'no captions'.

    Detected by class name and message so it survives youtube-transcript-api version
    changes (IpBlocked / RequestBlocked / TooManyRequests / YouTubeRequestFailed)."""
    name = type(exc).__name__.lower()
    if any(k in name for k in ("ipblocked", "requestblocked", "toomanyrequests")):
        return True
    msg = str(exc).lower()
    return (
        "too many requests" in msg
        or "blocking requests from your ip" in msg
        or "your ip" in msg and "block" in msg
    )


def _fetch_sync(video_id: str, lang: str) -> tuple[str, list[dict] | None]:
    """Synchronous fetch via youtube-transcript-api v1.x. Returns (outcome, raw_segments).

    outcome is one of _OK / _EMPTY / _BLOCKED. Distinguishing a genuine 'no captions'
    from an IP block is essential: the former is cached and the run continues; the latter
    trips the circuit breaker and is never cached.
    """
    from youtube_transcript_api import YouTubeTranscriptApi  # local import for testability

    prefs = [lang, f"{lang}-US", "en"] if lang else ["en"]
    seen: set[str] = set()
    languages = [x for x in prefs if not (x in seen or seen.add(x))]

    api = YouTubeTranscriptApi()

    # 1. Preferred languages, in order.
    try:
        return _OK, api.fetch(video_id, languages=languages).to_raw_data()
    except Exception as exc:  # noqa: BLE001
        if _is_block_error(exc):
            return _BLOCKED, None

    # 2. Fallback: any transcript that exists (manual or auto-generated), any language.
    try:
        for transcript in api.list(video_id):
            try:
                return _OK, transcript.fetch().to_raw_data()
            except Exception as exc:  # noqa: BLE001
                if _is_block_error(exc):
                    return _BLOCKED, None
                continue
    except Exception as exc:  # noqa: BLE001
        if _is_block_error(exc):
            return _BLOCKED, None
        return _EMPTY, None
    return _EMPTY, None


def _apply_segments(candidate: Candidate, raw: list[dict]) -> None:
    """Convert raw {text,start,duration} dicts into TranscriptSegments on the candidate."""
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


async def _fetch_one(
    candidate: Candidate, lang: str, sem: asyncio.Semaphore, breaker: asyncio.Event
) -> None:
    vid = candidate.video_id

    # 1. Cache first — no network for a cache hit (the main rate-limit defense).
    cached = cache.get(vid, lang)
    if cached is not None:
        if cached:  # non-empty → positive hit
            _apply_segments(candidate, cached)
        elif candidate.status == CandidateStatus.FOUND:  # [] → known no-transcript
            candidate.status = CandidateStatus.NO_TRANSCRIPT
        return

    # 2. If we've already been blocked this run, don't make it worse — skip the network.
    if breaker.is_set():
        if candidate.status == CandidateStatus.FOUND:
            candidate.status = CandidateStatus.RATE_LIMITED
        return

    async with sem:
        if breaker.is_set():
            if candidate.status == CandidateStatus.FOUND:
                candidate.status = CandidateStatus.RATE_LIMITED
            return
        # Polite pacing: a small randomized delay so requests don't burst.
        await asyncio.sleep(random.uniform(*PACING_DELAY_RANGE))
        try:
            outcome, raw = await asyncio.wait_for(
                asyncio.to_thread(_fetch_sync, vid, lang),
                timeout=PER_VIDEO_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            outcome, raw = _EMPTY, None
        except Exception:  # noqa: BLE001 — treat unknown errors as a transient miss
            outcome, raw = _EMPTY, None

    if outcome == _BLOCKED:
        breaker.set()  # trip the circuit breaker for the rest of the run
        if candidate.status == CandidateStatus.FOUND:
            candidate.status = CandidateStatus.RATE_LIMITED
        return

    if outcome == _OK and raw:
        cache.put_transcript(vid, lang, raw)
        _apply_segments(candidate, raw)
        return

    # Genuine "no transcript" — cache it (with TTL) so we don't re-request next run.
    cache.put_none(vid, lang)
    if candidate.status == CandidateStatus.FOUND:
        candidate.status = CandidateStatus.NO_TRANSCRIPT


async def fetch_transcripts(
    candidates: list[Candidate], lang: str
) -> tuple[list[Candidate], bool]:
    """Attach transcripts (cache-first, politely). SPEC §6.3.

    Returns (candidates, rate_limited). `rate_limited` is True if YouTube IP-blocked us
    mid-run; the caller surfaces an honest message. Only FOUND candidates are fetched;
    already-filtered ones (short/live/lang) are left alone for the coverage table.
    """
    to_fetch = [c for c in candidates if c.status == CandidateStatus.FOUND]
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    breaker = asyncio.Event()

    await asyncio.gather(*(_fetch_one(c, lang, sem, breaker) for c in to_fetch))
    return candidates, breaker.is_set()


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
