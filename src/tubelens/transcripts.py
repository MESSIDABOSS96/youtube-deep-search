"""Transcript fetching (SPEC §6.3).

Uses youtube-transcript-api, preferring manual captions then auto-generated, in --lang
then any available language. Parallel bounded worker pool (~8) with per-video timeout.
Keeps segment timestamps (they power the jump-to links). Videos with no transcript are
marked `no_transcript`, excluded from ranking, but kept for the coverage table
(trust requirement, SPEC §7.3).

Also provides timestamp-preserving chunking used by triage digests (SPEC §6.4) and
deep-read truncation (SPEC §6.5).

TODO(implement): fetch_transcripts(), excerpt_for_digest(), chunk_for_deep_read().
"""

from __future__ import annotations

from .models import Candidate

MAX_CONCURRENCY = 8
PER_VIDEO_TIMEOUT_SECONDS = 10


async def fetch_transcripts(candidates: list[Candidate], lang: str) -> list[Candidate]:
    """Attach transcripts (or mark no_transcript). SPEC §6.3."""
    raise NotImplementedError("Implement per SPEC §6.3.")
