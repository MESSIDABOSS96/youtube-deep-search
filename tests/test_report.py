"""Tests for report.py — renders golden fixture data to valid self-contained HTML.

No network. Cover (SPEC §7, §13):
  - render() produces a single self-contained file (no external <link>/<script> src
    except i.ytimg.com thumbnails)
  - the trust sections are present: coverage strip, expanded-queries, full scan table
    including a no-transcript row
  - timestamp_url() builds youtube.com/watch?v=ID&t=Ns correctly
  - playbook source chips link to the right video at the right timestamp
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tubelens.models import (
    Candidate,
    CandidateStatus,
    DeepResult,
    Playbook,
    PlaybookPoint,
    SourceRef,
    TranscriptSegment,
    TriageResult,
)
from tubelens.report import render, timestamp_url


def test_timestamp_url():
    assert timestamp_url("abc123", 252) == "https://www.youtube.com/watch?v=abc123&t=252s"
    assert timestamp_url("xyz", 0) == "https://www.youtube.com/watch?v=xyz&t=0s"


def _mk_candidate(
    vid: str,
    *,
    status: CandidateStatus = CandidateStatus.DEEP_READ,
    transcript=True,
    triage=True,
) -> Candidate:
    return Candidate(
        video_id=vid,
        title=f"Video {vid}",
        channel=f"Channel {vid}",
        duration_seconds=600,
        view_count=12345,
        thumbnail_url=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        transcript=[TranscriptSegment(start=252.0, text="key moment")] if transcript else None,
        status=status,
        triage=TriageResult(video_id=vid, score=7.0, reason="covers the topic") if triage else None,
    )


def _golden_context(tmp_path):
    candidates = [
        _mk_candidate("A", status=CandidateStatus.DEEP_READ),
        _mk_candidate("B", status=CandidateStatus.TRIAGED_OUT, triage=False),
        _mk_candidate("C", status=CandidateStatus.NO_TRANSCRIPT, transcript=False, triage=False),
        _mk_candidate("D", status=CandidateStatus.FILTERED_SHORT, triage=False),
    ]
    ranked = [
        (
            candidates[0],
            DeepResult(
                video_id="A",
                score=8.5,
                why="walks through the pre-launch waitlist build",
                best_timestamp_seconds=252,
                timestamp_reason="starts the waitlist walkthrough",
                key_points=["build a waitlist", "email early users"],
            ),
        )
    ]
    playbook = Playbook(
        title="The pre-launch playbook",
        points=[
            PlaybookPoint(
                text="Build a waitlist before launch to capture early interest.",
                sources=[SourceRef(video_index=0, seconds=252)],
            )
        ],
    )
    return candidates, ranked, playbook


def test_render_is_self_contained(tmp_path):
    candidates, ranked, playbook = _golden_context(tmp_path)
    out = render(
        query="how to start growth before launch",
        intent_summary="pre-launch growth playbook",
        search_queries=["pre launch waitlist", "app growth before release", "early user growth"],
        candidates=candidates,
        ranked=ranked,
        playbook=playbook,
        model="anthropic/claude-haiku-4-5",
        triage_model="anthropic/claude-haiku-4-5",
        results_count=10,
        duration_seconds=42.5,
        out_path=tmp_path / "report.html",
    )
    html = out.read_text(encoding="utf-8")
    # No external <link> or <script src> — only inline styles/JS (SPEC §7.1).
    assert not re.search(r"<link\b", html, re.IGNORECASE)
    assert not re.search(r"<script[^>]+src=", html, re.IGNORECASE)
    # External references may only be i.ytimg.com (thumbnails) or youtube.com links.
    for src in re.findall(r'(?:src|href)="([^"]+)"', html):
        allowed = ("https://i.ytimg.com/", "https://www.youtube.com/",
                  "https://github.com/", "#", "file://")
        assert src.startswith(allowed), src


def test_render_trust_sections_present(tmp_path):
    candidates, ranked, playbook = _golden_context(tmp_path)
    out = render(
        query="how to start growth before launch",
        intent_summary="pre-launch growth playbook",
        search_queries=["pre launch waitlist", "app growth before release"],
        candidates=candidates,
        ranked=ranked,
        playbook=playbook,
        model="m",
        triage_model="m",
        results_count=10,
        duration_seconds=42.5,
        out_path=tmp_path / "report.html",
    )
    html = out.read_text(encoding="utf-8")
    # 1. Header with verbatim query.
    assert "how to start growth before launch" in html
    # 2. Coverage strip with real numbers.
    assert "2</strong> searches" in html
    assert "4</strong> videos found" in html
    # Expanded queries listed.
    assert "pre launch waitlist" in html
    # 3. Playbook with source chip linking to timestamped video.
    assert "The pre-launch playbook" in html
    # Jinja2 autoescapes '&' -> '&' inside href attributes.
    assert "https://www.youtube.com/watch?v=A&amp;t=252s" in html
    # 4. Ranked card with score + jump link.
    assert "8.5" in html
    assert "Jump to 4:12" in html
    # 5. Full scanned table including a no-transcript row + filtered row.
    assert "Everything scanned" in html
    assert CandidateStatus.NO_TRANSCRIPT.value in html
    assert CandidateStatus.FILTERED_SHORT.value in html
    assert CandidateStatus.TRIAGED_OUT.value in html
    # 6. Footer with models + duration + repo link.
    assert "Generated by" in html
    assert "tubelens" in html


def test_render_groups_by_tier(tmp_path):
    """Results render grouped by match-strength tier; untiered results fall back by score."""
    candidates, ranked, playbook = _golden_context(tmp_path)
    # Fixture DeepResult has score 8.5 and no explicit tier -> "strong" fallback.
    out = render(
        query="q", intent_summary="s", search_queries=["q"],
        candidates=candidates, ranked=ranked, playbook=playbook,
        model="m", triage_model="m", results_count=10, duration_seconds=1.0,
        out_path=tmp_path / "report.html",
    )
    html = out.read_text(encoding="utf-8")
    assert "Strong matches (1)" in html
    # Empty tiers are not rendered at all.
    assert "Partial matches" not in html
    assert "Weak matches" not in html
    # The playbook is collapsed (a <details>, not an always-open section).
    assert '<details class="playbook">' in html


def test_render_without_brief(tmp_path):
    candidates, ranked, _pb = _golden_context(tmp_path)
    out = render(
        query="q", intent_summary="s", search_queries=["q"],
        candidates=candidates, ranked=ranked, playbook=None,
        model="m", triage_model="m", results_count=10, duration_seconds=1.0,
        out_path=tmp_path / "report.html",
    )
    html = out.read_text(encoding="utf-8")
    assert "The pre-launch playbook" not in html
    # Ranked results still present.
    assert "Ranked results" in html


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
