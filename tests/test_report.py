"""Tests for report.py — renders golden fixture data to valid self-contained HTML.

No network. Cover (SPEC §7, §13):
  - render() produces a single self-contained file (no external <link>/<script> src
    except i.ytimg.com thumbnails)
  - the trust sections are present: coverage strip, expanded-queries, full scan table
    including a no-transcript row
  - timestamp_url() builds youtube.com/watch?v=ID&t=Ns correctly

TODO(implement): write full render assertions once report.py exists.
"""

from tubelens.report import timestamp_url


def test_timestamp_url():
    assert timestamp_url("abc123", 252) == "https://www.youtube.com/watch?v=abc123&t=252s"
