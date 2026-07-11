"""YouTube Data API v3 access (SPEC §6.2).

Plain REST via httpx (no heavy google client). Runs one search.list per expanded query
in parallel, dedupes by video ID, interleaves to preserve query diversity when over the
scan cap, then hydrates with one batched videos.list call. Filters out Shorts (<60s),
live streams, and off-language videos. Surfaces a clear error on quota exhaustion
(SPEC §9).
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import quote_plus

import httpx

from .models import Candidate, CandidateStatus

MIN_DURATION_SECONDS = 60  # SPEC §6.2: filter out Shorts; easily changed constant.

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
MAX_RESULTS_PER_SEARCH = 25
VIDEOS_ID_BATCH = 50  # videos.list hard limit: at most 50 IDs per request.


class YouTubeError(Exception):
    """Friendly YouTube API error (SPEC §9)."""


def _iso8601_duration_to_seconds(iso: str) -> int:
    """Parse an ISO 8601 PT#H#M#S duration (contentDetails.duration) into seconds."""
    if not iso:
        return 0
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", iso)
    if not m:
        return 0
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi or 0) * 60 + int(s or 0)


def dedupe_interleave(result_sets: list[list[Candidate]], scan_cap: int) -> list[Candidate]:
    """Dedupe by video_id and interleave per-query results to preserve diversity.

    When the union fits under `scan_cap`, return it in order. When it exceeds the cap,
    round-robin across the per-query result sets (in each query's rank order) so no
    single query dominates the scanned pool (SPEC §6.2).
    """
    seen: set[str] = set()
    deduped_per_query: list[list[Candidate]] = []
    for qset in result_sets:
        unique = []
        for c in qset:
            if c.video_id in seen:
                continue
            seen.add(c.video_id)
            unique.append(c)
        deduped_per_query.append(unique)

    # Flatten by interleaving in rank order.
    interleaved: list[Candidate] = []
    max_len = max((len(s) for s in deduped_per_query), default=0)
    for i in range(max_len):
        for qset in deduped_per_query:
            if i < len(qset):
                interleaved.append(qset[i])

    return interleaved[:scan_cap]


async def _search_one(
    client: httpx.AsyncClient, query: str, api_key: str, lang: str
) -> list[Candidate]:
    params = {
        "part": "snippet",
        "type": "video",
        "maxResults": MAX_RESULTS_PER_SEARCH,
        "q": query,
        "key": api_key,
        "safeSearch": "none",
    }
    if lang:
        params["relevanceLanguage"] = lang
    try:
        r = await client.get(SEARCH_URL, params=params)
    except httpx.HTTPError as exc:
        raise YouTubeError(f"YouTube search request failed: {exc}") from exc
    _check_quota(r)
    if r.status_code != 200:
        raise YouTubeError(f"YouTube search failed (HTTP {r.status_code}): {r.text}")
    items = r.json().get("items", [])
    out: list[Candidate] = []
    for item in items:
        vid = item.get("id", {}).get("videoId")
        snip = item.get("snippet", {})
        if not vid:
            continue
        thumbs = snip.get("thumbnails", {})
        thumb = (
            thumbs.get("high", {}).get("url")
            or thumbs.get("medium", {}).get("url")
            or thumbs.get("default", {}).get("url", "")
        )
        out.append(
            Candidate(
                video_id=vid,
                title=snip.get("title", "").strip(),
                channel=snip.get("channelTitle", "").strip(),
                thumbnail_url=thumb,
                search_query=query,
            )
        )
    return out


def _check_quota(response: httpx.Response) -> None:
    """SPEC §9: surface quota exhaustion with a clear, actionable message."""
    if response.status_code == 403:
        try:
            body = response.json()
            reasons = body.get("error", {}).get("errors", [])
            for er in reasons:
                if er.get("reason") == "quotaExceeded":
                    raise YouTubeError(
                        "YouTube API quota exceeded. The free quota resets at midnight "
                        "Pacific Time. You can reduce usage with --scan (e.g. --scan 40)."
                    )
        except YouTubeError:
            raise
        except Exception:
            pass
    if response.status_code == 429:
        raise YouTubeError(
            "YouTube API rate-limited. Wait a moment and retry, or lower --scan."
        )


async def _hydrate(
    client: httpx.AsyncClient, candidates: list[Candidate], api_key: str, lang: str
) -> list[Candidate]:
    if not candidates:
        return candidates
    ids = [c.video_id for c in candidates]

    async def _fetch_chunk(chunk: list[str]) -> list[dict]:
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(chunk),
            "key": api_key,
        }
        try:
            r = await client.get(VIDEOS_URL, params=params)
        except httpx.HTTPError as exc:
            raise YouTubeError(f"YouTube videos.list failed: {exc}") from exc
        _check_quota(r)
        if r.status_code != 200:
            raise YouTubeError(
                f"YouTube videos.list failed (HTTP {r.status_code}): {r.text}"
            )
        return r.json().get("items", [])

    # videos.list accepts at most 50 IDs per call — batch and fetch concurrently.
    chunks = [ids[i : i + VIDEOS_ID_BATCH] for i in range(0, len(ids), VIDEOS_ID_BATCH)]
    chunk_results = await asyncio.gather(*(_fetch_chunk(c) for c in chunks))
    by_id: dict[str, dict] = {}
    for items in chunk_results:
        for item in items:
            by_id[item["id"]] = item

    out: list[Candidate] = []
    for c in candidates:
        item = by_id.get(c.video_id)
        if not item:
            out.append(c)
            continue
        snip = item.get("snippet", {})
        stats = item.get("statistics", {})
        cd = item.get("contentDetails", {})
        c.duration_seconds = _iso8601_duration_to_seconds(cd.get("duration", ""))
        c.view_count = int(stats.get("viewCount", 0) or 0)
        c.language = snip.get("defaultAudioLanguage") or snip.get("defaultLanguage")
        if not c.thumbnail_url:
            thumbs = snip.get("thumbnails", {})
            c.thumbnail_url = (
                thumbs.get("high", {}).get("url")
                or thumbs.get("medium", {}).get("url", "")
            )
        c.channel = c.channel or snip.get("channelTitle", "").strip()
        c.title = c.title or snip.get("title", "").strip()
        # Filters (SPEC §6.2): shorts, live streams, off-language.
        if c.duration_seconds and c.duration_seconds < MIN_DURATION_SECONDS:
            c.status = CandidateStatus.FILTERED_SHORT
        elif snip.get("liveBroadcastContent") == "live":
            c.status = CandidateStatus.FILTERED_LIVE
        elif lang and c.language and not c.language.lower().startswith(lang.lower()):
            c.status = CandidateStatus.FILTERED_LANG
        out.append(c)
    return out


async def search_candidates(
    queries: list[str], api_key: str, scan_cap: int, lang: str = "en"
) -> list[Candidate]:
    """Run parallel searches, dedupe/interleave, hydrate metadata. SPEC §6.2."""
    if not queries:
        return []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        result_sets = await asyncio.gather(
            *(_search_one(client, q, api_key, lang) for q in queries),
            return_exceptions=True,
        )
    flattened: list[list[Candidate]] = []
    for _q, res in zip(queries, result_sets, strict=False):
        if isinstance(res, YouTubeError):
            raise res
        if isinstance(res, Exception):
            # A single search failing shouldn't kill the whole run.
            flattened.append([])
        else:
            flattened.append(res)
    candidates = dedupe_interleave(flattened, scan_cap)
    if not candidates:
        return []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        candidates = await _hydrate(client, candidates, api_key, lang)
    return candidates


def quote_query(q: str) -> str:
    """Convenience for URL-encoding a query (kept for tests/external use). -@"""
    return quote_plus(q)
