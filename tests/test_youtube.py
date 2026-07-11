"""Tests for youtube.py — dedupe, interleave, filters (SPEC §6.2, §10).

No network: mock the YouTube Data API with fixtures in tests/fixtures/. Cover:
  - dedupe by video ID across multiple query result sets
  - interleaving preserves per-query diversity when over the scan cap
  - filters drop Shorts (<60s), live streams, off-language videos
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fixtures import make_search_response, make_video_item, make_videos_response

from tubelens.models import Candidate, CandidateStatus
from tubelens.youtube import (
    _iso8601_duration_to_seconds,
    dedupe_interleave,
    search_candidates,
)


def _resp_mock(status: int, body: dict):
    """A plain (sync) httpx-like response mock."""
    from unittest.mock import Mock
    m = Mock()
    m.status_code = status
    m.json.return_value = body
    m.text = str(body)
    return m


def _mk(vid: str, q: str = "q") -> Candidate:
    return Candidate(video_id=vid, title=f"Video {vid}", channel=f"Channel {vid}", search_query=q)


def test_dedupe_across_queries():
    a = [_mk("A"), _mk("B"), _mk("C")]
    b = [_mk("B"), _mk("D")]
    out = dedupe_interleave([a, b], scan_cap=100)
    ids = [c.video_id for c in out]
    # B is deduped globally; interleaving is rank-round-robin.
    assert set(ids) == {"A", "B", "C", "D"}
    assert ids.count("B") == 1


def test_interleave_preserves_diversity_under_cap():
    a = [_mk(f"A{i}") for i in range(10)]
    b = [_mk(f"B{i}") for i in range(10)]
    out = dedupe_interleave([a, b], scan_cap=10)
    ids = [c.video_id for c in out]
    # Round-robin interleave, not all of query A first.
    assert ids == ["A0", "B0", "A1", "B1", "A2", "B2", "A3", "B3", "A4", "B4"]


def test_interleave_handles_uneven_query_sizes():
    a = [_mk(f"A{i}") for i in range(3)]
    b = [_mk(f"B{i}") for i in range(3)]
    c = [_mk("A0"), _mk("X1")]  # A0 dedupes; X1 is new
    out = dedupe_interleave([a, b, c], scan_cap=100)
    ids = [x.video_id for x in out]
    assert "A0" in ids and ids.count("A0") == 1
    assert ids.index("X1") > ids.index("B0")  # appears in later round


def test_iso8601_duration():
    assert _iso8601_duration_to_seconds("PT10M0S") == 600
    assert _iso8601_duration_to_seconds("PT1H2M3S") == 3723
    assert _iso8601_duration_to_seconds("PT45S") == 45
    assert _iso8601_duration_to_seconds("") == 0


def test_filters_short_live_lang():
    """SPEC §6.2: drop Shorts (<60s), live streams, off-language videos — but keep
    them in the candidate list with a status for the coverage table."""
    queries = ["q1"]

    search_resp = make_search_response(["S", "L", "O", "G"])
    videos_resp = make_videos_response(
        [
            make_video_item("S", duration="PT30S"),  # short
            make_video_item("L", live=True),  # live
            make_video_item("O", lang="es"),  # off-language
            make_video_item("G", duration="PT5M0S"),  # good
        ]
    )

    responses = [
        _resp_mock(200, search_resp),
        _resp_mock(200, videos_resp),
    ]

    async def fake_get(self, url, params=None):
        return responses.pop(0)

    with patch("httpx.AsyncClient.get", new=fake_get):
        out = asyncio.run(search_candidates(queries, "k", scan_cap=80, lang="en"))

    by_id = {c.video_id: c for c in out}
    assert by_id["S"].status == CandidateStatus.FILTERED_SHORT
    assert by_id["L"].status == CandidateStatus.FILTERED_LIVE
    assert by_id["O"].status == CandidateStatus.FILTERED_LANG
    assert by_id["G"].status == CandidateStatus.FOUND


def test_quota_exceeded_raises_friendly_error():
    from tubelens.youtube import YouTubeError

    queries = ["q1"]

    async def fake_get(self, url, params=None):
        return _resp_mock(403, {"error": {"errors": [{"reason": "quotaExceeded"}]}})

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(YouTubeError, match="quota"):
            asyncio.run(search_candidates(queries, "k", scan_cap=80, lang="en"))


def test_empty_queries_returns_empty():
    assert asyncio.run(search_candidates([], "k", 80)) == []


def test_hydrate_batches_ids_under_50():
    """SPEC §6.2: videos.list accepts at most 50 IDs per call. With a large scan the
    hydrate step must batch — one call of 80 IDs returns HTTP 400 invalidFilters."""
    batch_sizes: list[int] = []

    def _search(n, offset):
        return make_search_response([f"v{offset + i}" for i in range(n)])

    search_count = [0]

    async def fake_get(self, url, params=None):
        if "search" in url:
            i = search_count[0]
            search_count[0] += 1
            return _resp_mock(200, _search(25, i * 25))
        ids = params["id"].split(",")
        batch_sizes.append(len(ids))
        return _resp_mock(200, make_videos_response([make_video_item(i) for i in ids]))

    with patch("httpx.AsyncClient.get", new=fake_get):
        out = asyncio.run(
            search_candidates([f"q{i}" for i in range(7)], "k", scan_cap=80, lang="en")
        )

    assert len(out) == 80
    assert batch_sizes == [50, 30]  # never a single call of 80
    assert all(s <= 50 for s in batch_sizes)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
