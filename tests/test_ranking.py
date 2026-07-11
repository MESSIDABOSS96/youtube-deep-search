"""Tests for ranking.py + llm.py — digests, JSON validation/retry (SPEC §6.4, §9, §10).

No network: mock the LLM with fixtures. Cover:
  - triage digest stays within the token budget and batches (never per-video)
  - deep_read_count() = max(15, results + 5)  (import from config)
  - malformed LLM JSON triggers exactly one retry, then graceful failure
  - clarify gate: the "which arm?" style question is suppressed; a results-changing
    question passes (assert against a fixtured LLM response)

TODO(implement): write these once ranking.py exists.
"""

import pytest

from tubelens.config import deep_read_count


def test_deep_read_count_never_below_results():
    # SPEC §6.4: deep-read pool must never be smaller than --results.
    assert deep_read_count(10) == 15
    assert deep_read_count(20) == 25
    assert deep_read_count(3) == 15


@pytest.mark.skip(reason="ranking.py not implemented yet")
def test_clarify_suppresses_low_value_question():
    raise NotImplementedError
