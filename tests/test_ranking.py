"""Tests for ranking.py + llm.py — digests, JSON validation/retry (SPEC §6.4, §9, §10).

No network: mock the LLM with fixtures. Cover:
  - triage digest stays within the token budget and batches (never per-video)
  - deep_read_count() = max(15, results + 5)  (import from config)
  - malformed LLM JSON triggers exactly one retry, then graceful failure
  - clarify gate: the "which arm?" style question is suppressed; a results-changing
    question passes (assert against a fixtured LLM response)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tubelens.config import deep_read_count
from tubelens.llm import LLMError, complete_json, complete_json_list
from tubelens.models import Candidate, ClarifyExpand, TriageResult
from tubelens.ranking import _build_digest, clarify_and_expand, triage
from tubelens.transcripts import CHARS_PER_TOKEN, DIGEST_TOKEN_BUDGET


def test_deep_read_count_never_below_results():
    # SPEC §6.4: deep-read pool must never be smaller than --results.
    assert deep_read_count(10) == 15
    assert deep_read_count(20) == 25
    assert deep_read_count(3) == 15


def test_available_model_choices_reflects_keys(monkeypatch):
    """SPEC §8: the picker offers only providers the user actually has a key for."""
    import shutil

    from tubelens import config

    # Clear every provider key, then set only Anthropic's.
    for env_var in config.PROVIDER_KEYS.values():
        if env_var:
            monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: None)  # pretend Ollama not installed

    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    choices = config.available_model_choices()
    assert choices and all(m.startswith("anthropic/") for m, _ in choices)

    # Adding an NVIDIA key surfaces its models too.
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "y")
    both = {m for m, _ in config.available_model_choices()}
    assert any(m.startswith("anthropic/") for m in both)
    assert any(m.startswith("nvidia_nim/") for m in both)

    # With no keys and no Ollama, there are no choices.
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("NVIDIA_NIM_API_KEY")
    assert config.available_model_choices() == []


def _mk_candidate(
    vid: str, transcript_text: str = "the pre-launch waitlist tactic growth"
) -> Candidate:
    from tubelens.models import TranscriptSegment
    return Candidate(
        video_id=vid,
        title=f"Video {vid}",
        channel="Ch",
        duration_seconds=600,
        view_count=1000,
        transcript=[TranscriptSegment(start=0.0, text=transcript_text)],
    )


def test_build_digest_within_budget():
    long_text = " ".join(["word"] * 5000)
    c = _mk_candidate("X", transcript_text=long_text)
    digest = _build_digest(c)
    # Roughly within DIGEST_TOKEN_BUDGET tokens (char budget = tokens * CHARS_PER_TOKEN).
    assert len(digest) <= DIGEST_TOKEN_BUDGET * CHARS_PER_TOKEN + 200  # small header slack
    assert "video_id: X" in digest
    assert "title:" in digest


def test_triage_never_per_video():
    """SPEC §6.4: 1–2 batched calls total, NOT one call per video."""
    candidates = [_mk_candidate(f"v{i}") for i in range(60)]
    call_count = 0

    import json as _json
    import re

    async def fake_complete_json_list(prompt, item_schema, model):
        nonlocal call_count
        call_count += 1
        # Extract the batch's video_ids from the prompt's id-list hint.
        m = re.search(r"The video_ids must be exactly: (\[.*\])", prompt, re.DOTALL)
        ids = _json.loads(m.group(1)) if m else [c.video_id for c in candidates]
        return [TriageResult(video_id=i, score=5.0, reason="ok") for i in ids]

    with patch("tubelens.ranking.complete_json_list", new=fake_complete_json_list):
        results = asyncio.run(triage(candidates, "intent", "model"))

    assert len(results) == 60
    # 60 candidates / TRIAGE_BATCH_SIZE(40) -> 2 batches -> 2 calls (never 60).
    assert call_count == 2
    assert call_count < len(candidates)


def test_triage_drops_hallucinated_ids():
    candidates = [_mk_candidate("real1"), _mk_candidate("real2")]

    async def fake_complete_json_list(prompt, item_schema, model):
        return [
            TriageResult(video_id="real1", score=8.0, reason="good"),
            TriageResult(video_id="fake", score=10.0, reason="hallucinated"),
        ]

    with patch("tubelens.ranking.complete_json_list", new=fake_complete_json_list):
        results = asyncio.run(triage(candidates, "intent", "model"))

    ids = [r.video_id for r in results]
    assert "fake" not in ids
    assert "real1" in ids


def test_complete_json_malformed_then_retry_succeeds():
    """SPEC §9: one retry with the validation error appended, then success."""
    calls = []

    async def fake_raw(prompt, model):
        calls.append(prompt)
        if len(calls) == 1:
            return "not json at all"
        return (
            '{"ambiguous": false, "clarifying_questions": [], '
            '"search_queries": ["q"], "intent_summary": "x"}'
        )

    with patch("tubelens.llm._raw_complete", new=fake_raw):
        out = asyncio.run(complete_json("prompt", ClarifyExpand, "model"))
    assert isinstance(out, ClarifyExpand)
    assert out.search_queries == ["q"]
    assert len(calls) == 2  # exactly one retry


def test_complete_json_retry_still_fails_raises():
    calls = []

    async def fake_raw(prompt, model):
        calls.append(prompt)
        return "still not json"

    with patch("tubelens.llm._raw_complete", new=fake_raw):
        with pytest.raises(LLMError):
            asyncio.run(complete_json("prompt", ClarifyExpand, "model"))
    assert len(calls) == 2  # initial + exactly one retry


def test_complete_json_list_empty_on_failure():
    """SPEC §9: triage batch that fails validation degrades gracefully."""
    async def fake_raw(prompt, model):
        return "garbage {}{}"

    with patch("tubelens.llm._raw_complete", new=fake_raw):
        out = asyncio.run(complete_json_list("prompt", TriageResult, "model"))
    assert out == []


def test_clarify_suppresses_low_value_question_via_fixture():
    """SPEC §6.1: a results-changing question passes; the 'which arm?' style is suppressed.

    We assert behavior against a fixtured LLM response that correctly applied the
    results-changing test for 'elbow pain golf': asks inside/outside elbow, never arm.
    """
    canned = ClarifyExpand(
        ambiguous=True,
        clarifying_questions=["Is the pain on the inside or outside of the elbow?"],
        search_queries=["golfer elbow rehab", "tennis elbow golf fix", "elbow pain golf swing"],
        intent_summary="rehab for elbow pain specific to golf",
    )

    async def fake_complete_json(prompt, schema, model):
        # The prompt must encode the results-changing test and forbid the 'which arm' question.
        assert "results-changing" in prompt.lower()
        assert "which arm" in prompt.lower()  # the forbidden example is taught
        return canned

    with patch("tubelens.ranking.complete_json", new=fake_complete_json):
        out = asyncio.run(clarify_and_expand("elbow pain from golf", "model", allow_clarify=True))

    assert out.ambiguous is True
    assert len(out.clarifying_questions) <= 2
    # The good question distinguishes conditions; 'arm' must not appear in any question.
    for q in out.clarifying_questions:
        assert "arm" not in q.lower()


def test_comparative_rank_orders_and_tiers():
    """Final pass: side-by-side ordering wins over noisy isolated scores."""
    from tubelens.models import DeepResult, TierAssignment
    from tubelens.ranking import comparative_rank

    pairs = [
        (_mk_candidate("A"), DeepResult(video_id="A", score=8.0, why="w")),
        (_mk_candidate("B"), DeepResult(video_id="B", score=8.5, why="w")),
        (_mk_candidate("C"), DeepResult(video_id="C", score=7.0, why="w")),
    ]

    async def fake_list(prompt, schema, model):
        # The judge disagrees with isolated scores: B's 8.5 was inflated.
        assert "ISOLATION" in prompt
        return [
            TierAssignment(video_id="A", tier="strong"),
            TierAssignment(video_id="C", tier="partial", note="one section on it, not the focus"),
            TierAssignment(
                video_id="B", tier="weak", note="covers post-launch ASO, not pre-launch"
            ),
        ]

    with patch("tubelens.ranking.complete_json_list", new=fake_list):
        out = asyncio.run(comparative_rank(pairs, "intent", "model"))

    assert [t.video_id for t in out] == ["A", "C", "B"]
    assert out[0].tier == "strong"
    assert out[0].note == ""  # strong matches carry no relation note
    assert out[2].note == "covers post-launch ASO, not pre-launch"


def test_comparative_rank_rejects_partial_coverage():
    """A partial ordering is worse than the fallback — must return None."""
    from tubelens.models import DeepResult, TierAssignment
    from tubelens.ranking import comparative_rank

    pairs = [
        (_mk_candidate("A"), DeepResult(video_id="A", score=8.0, why="w")),
        (_mk_candidate("B"), DeepResult(video_id="B", score=6.0, why="w")),
    ]

    async def fake_list(prompt, schema, model):
        return [TierAssignment(video_id="A", tier="strong")]  # B missing

    with patch("tubelens.ranking.complete_json_list", new=fake_list):
        out = asyncio.run(comparative_rank(pairs, "intent", "model"))
    assert out is None


def test_tier_from_score_fallback():
    from tubelens.ranking import tier_from_score

    assert tier_from_score(9.0) == "strong"
    assert tier_from_score(7.5) == "strong"
    assert tier_from_score(6.0) == "partial"
    assert tier_from_score(3.0) == "weak"


def test_clarify_no_clarify_flag_forbids_questions():
    async def fake_complete_json(prompt, schema, model):
        assert "do not ask any clarifying questions" in prompt.lower()
        return ClarifyExpand(
            ambiguous=False,
            clarifying_questions=[],
            search_queries=["q"],
            intent_summary="x",
        )

    with patch("tubelens.ranking.complete_json", new=fake_complete_json):
        out = asyncio.run(clarify_and_expand("some query", "model", allow_clarify=False))
    assert out.ambiguous is False
    assert out.clarifying_questions == []


if __name__ == "__main__":
    asyncio.run(_mk_candidate("x"))
    pytest.main([__file__, "-v"])
