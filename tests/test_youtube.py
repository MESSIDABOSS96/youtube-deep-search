"""Tests for youtube.py — dedupe, interleave, filters (SPEC §6.2, §10).

No network: mock the YouTube Data API with fixtures in tests/fixtures/. Cover:
  - dedupe by video ID across multiple query result sets
  - interleaving preserves per-query diversity when over the scan cap
  - filters drop Shorts (<60s), live streams, off-language videos

TODO(implement): write these once youtube.py exists.
"""

import pytest


@pytest.mark.skip(reason="youtube.py not implemented yet")
def test_dedupe_and_interleave():
    raise NotImplementedError
