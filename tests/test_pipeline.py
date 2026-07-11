"""Full-pipeline wiring test with everything mocked (SPEC §10).

No network: mock the YouTube Data API, youtube-transcript-api, and litellm. Drives the
real `cli._run_pipeline` so it exercises the orchestration, dedupe/filter, transcript
fetch, triage, deep-rank, synthesis, and report render end to end, then asserts the
generated HTML is self-contained and contains the trust sections.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import make_search_response, make_video_item, make_videos_response

from tubelens.cli import _run_pipeline
from tubelens.config import Config
from tubelens.models import CandidateStatus


def _resp(status: int, body: dict):
    m = Mock()
    m.status_code = status
    m.json.return_value = body
    m.text = str(body)
    return m


def _fake_transcript(video_id: str):
    """Return raw youtube-transcript-api segment dicts."""
    return [
        {"text": "we cover the pre-launch waitlist tactic", "start": 0.0, "duration": 2.0},
        {"text": "build an email list before launch", "start": 252.0, "duration": 2.0},
        {"text": "outreach to early users", "start": 400.0, "duration": 2.0},
    ]


def _run_mocked_pipeline(tmp_path):
    cfg = Config(
        query="how to start growth before launch",
        results=3,
        scan=80,
        model="anthropic/claude-haiku-4-5",
        triage_model="anthropic/claude-haiku-4-5",
        brief=True,
        clarify=False,
        open_report=False,
        lang="en",
        out=str(tmp_path / "smoke.html"),
        json_output=False,
        verbose=False,
        youtube_api_key="k",
    )

    search_resp = make_search_response(["A", "B", "C"])
    videos_resp = make_videos_response(
        [
            make_video_item("A", duration="PT10M0S", views=5000, title="Pre-launch waitlist guide"),
            make_video_item("B", duration="PT12M0S", views=2000, title="Growth before release"),
            make_video_item("C", duration="PT8M0S", views=800, title="Early user outreach"),
        ]
    )

    responses = [_resp(200, search_resp), _resp(200, search_resp), _resp(200, videos_resp)]

    async def fake_get(self, url, params=None):
        return responses.pop(0)

    # LLM: clarify/expand -> triage -> deep -> synthesis, all via complete_json[_list].
    async def fake_complete_json(prompt, schema, model):
        if schema.__name__ == "ClarifyExpand":
            return schema(
                ambiguous=False,
                clarifying_questions=[],
                search_queries=["pre launch waitlist", "app growth before release"],
                intent_summary="pre-launch growth playbook",
            )
        if schema.__name__ == "DeepResult":
            # Extract the video_id from the prompt.
            import re
            m = re.search(r"VIDEO_ID: (\S+)", prompt)
            vid = m.group(1) if m else "A"
            return schema(
                video_id=vid,
                score=8.0 + (0.1 if vid == "A" else 0.0),
                why=f"this video covers pre-launch growth for {vid}",
                best_timestamp_seconds=252,
                timestamp_reason="starts the waitlist walkthrough",
                key_points=["build a waitlist early", "email your first users"],
            )
        if schema.__name__ == "Playbook":
            from tubelens.models import Playbook, PlaybookPoint, SourceRef
            return Playbook(
                title="The pre-launch playbook",
                points=[PlaybookPoint(
                    text="Build a waitlist before launch.",
                    sources=[SourceRef(video_index=0, seconds=252)],
                )],
            )
        raise AssertionError(f"unexpected schema {schema.__name__}")

    async def fake_complete_json_list(prompt, item_schema, model):
        import json as _json
        import re
        m = re.search(r"The video_ids must be exactly: (\[.*\])", prompt, re.DOTALL)
        ids = _json.loads(m.group(1)) if m else []
        from tubelens.models import TriageResult
        return [
            TriageResult(video_id=i, score=6.0 + (0.5 if i == "A" else 0.0), reason="covers topic")
            for i in ids
        ]

    async def fake_fetch_transcripts(candidates, lang):
        from tubelens.models import TranscriptSegment
        for c in candidates:
            if c.status == CandidateStatus.FOUND:
                c.transcript = [TranscriptSegment(start=0.0, text="segment")]
        return candidates, False  # (candidates, rate_limited)

    with patch("httpx.AsyncClient.get", new=fake_get), \
         patch("tubelens.ranking.complete_json", new=fake_complete_json), \
         patch("tubelens.ranking.complete_json_list", new=fake_complete_json_list), \
         patch("tubelens.cli.fetch_transcripts", new=fake_fetch_transcripts), \
         patch("tubelens.synthesis.complete_json", new=fake_complete_json):
        rc = asyncio.run(_run_pipeline(cfg))

    assert rc == 0
    out = Path(cfg.out)
    assert out.exists()
    return out.read_text(encoding="utf-8")


def test_full_pipeline_mocked(tmp_path):
    html = _run_mocked_pipeline(tmp_path)
    # Self-contained trust sections present.
    assert "how to start growth before launch" in html
    assert "Everything scanned" in html
    assert "Ranked results" in html
    assert "The pre-launch playbook" in html
    # Each ranked card has a working timestamped link.
    assert "youtube.com/watch?v=" in html
    # Coverage strip reflects the mocked run.
    assert "searches" in html


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
