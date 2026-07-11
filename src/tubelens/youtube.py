"""YouTube Data API v3 access (SPEC §6.2).

Plain REST via httpx (no heavy google client). Runs one search.list per expanded query
in parallel, dedupes by video ID, interleaves to preserve query diversity when over the
scan cap, then hydrates with one batched videos.list call. Filters out Shorts (<60s),
live streams, and off-language videos. Surfaces a clear error on quota exhaustion
(SPEC §9).

TODO(implement): search_all(), hydrate(), dedupe/interleave, filters.
"""

from __future__ import annotations

from .models import Candidate

MIN_DURATION_SECONDS = 60  # SPEC §6.2: filter out Shorts; easily changed constant.


async def search_candidates(queries: list[str], api_key: str, scan_cap: int) -> list[Candidate]:
    """Run parallel searches, dedupe/interleave, hydrate metadata. SPEC §6.2."""
    raise NotImplementedError("Implement per SPEC §6.2.")
