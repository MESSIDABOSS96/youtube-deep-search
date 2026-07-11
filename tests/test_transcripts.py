"""Tests for transcript fetching: cache, pacing, and the rate-limit circuit breaker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tubelens import cache, transcripts
from tubelens.models import Candidate, CandidateStatus
from tubelens.transcripts import _BLOCKED, _EMPTY, _OK, _is_block_error, fetch_transcripts


def _cand(vid: str) -> Candidate:
    return Candidate(video_id=vid, title=f"V {vid}", channel="c")


def test_is_block_error_detects_ip_block():
    class IpBlocked(Exception):
        pass

    class NoTranscriptFound(Exception):
        pass

    assert _is_block_error(IpBlocked("YouTube is blocking requests from your IP"))
    assert _is_block_error(Exception("Too Many Requests"))
    assert not _is_block_error(NoTranscriptFound("no captions for this video"))


def test_cache_hit_skips_network(tmp_path):
    # Point the cache at a temp dir and pre-seed a positive entry.
    with patch.object(cache, "CACHE_DIR", tmp_path):
        cache.put_transcript("VID", "en", [{"text": "hello", "start": 1.0, "duration": 2.0}])

        called = {"fetch": 0}

        def spy_fetch_sync(video_id, lang):
            called["fetch"] += 1
            return _OK, [{"text": "x", "start": 0.0, "duration": 1.0}]

        with patch.object(transcripts, "_fetch_sync", spy_fetch_sync):
            cands, rate_limited = asyncio.run(fetch_transcripts([_cand("VID")], "en"))

    assert called["fetch"] == 0  # served entirely from cache — no network
    assert rate_limited is False
    assert cands[0].has_transcript
    assert cands[0].transcript[0].text == "hello"


def test_block_trips_breaker_and_stops_fetching(tmp_path):
    # First video returns BLOCKED; the breaker must stop the rest from hitting the network.
    order: list[str] = []

    def fake_fetch_sync(video_id, lang):
        order.append(video_id)
        if video_id == "A":
            return _BLOCKED, None
        return _OK, [{"text": "t", "start": 0.0, "duration": 1.0}]

    with patch.object(cache, "CACHE_DIR", tmp_path), \
         patch.object(transcripts, "MAX_CONCURRENCY", 1), \
         patch.object(transcripts, "PACING_DELAY_RANGE", (0.0, 0.0)), \
         patch.object(transcripts, "_fetch_sync", fake_fetch_sync):
        cands, rate_limited = asyncio.run(
            fetch_transcripts([_cand("A"), _cand("B"), _cand("C")], "en")
        )

    assert rate_limited is True
    # A was tried; B and C must be skipped (breaker set) — never fetched.
    assert order == ["A"]
    by_id = {c.video_id: c for c in cands}
    assert by_id["A"].status == CandidateStatus.RATE_LIMITED
    assert by_id["B"].status == CandidateStatus.RATE_LIMITED
    assert by_id["C"].status == CandidateStatus.RATE_LIMITED


def test_block_is_not_cached(tmp_path):
    """A block must never be cached as 'no transcript' — that would poison the cache."""
    with patch.object(cache, "CACHE_DIR", tmp_path), \
         patch.object(transcripts, "PACING_DELAY_RANGE", (0.0, 0.0)), \
         patch.object(transcripts, "_fetch_sync", lambda vid, lang: (_BLOCKED, None)):
        asyncio.run(fetch_transcripts([_cand("Z")], "en"))
        # Nothing cached for Z, so a later run is free to retry (assert inside the patch).
        assert cache.get("Z", "en") is None


def test_empty_is_cached_as_none(tmp_path):
    with patch.object(cache, "CACHE_DIR", tmp_path), \
         patch.object(transcripts, "PACING_DELAY_RANGE", (0.0, 0.0)), \
         patch.object(transcripts, "_fetch_sync", lambda vid, lang: (_EMPTY, None)):
        cands, rate_limited = asyncio.run(fetch_transcripts([_cand("E")], "en"))
        assert cache.get("E", "en") == []  # negative cache entry written (inside patch)
    assert rate_limited is False
    assert cands[0].status == CandidateStatus.NO_TRANSCRIPT


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
