"""HTML report rendering (SPEC §7).

Renders one self-contained .html file from templates/report.html.j2 (all CSS inline,
tiny vanilla JS for collapse/expand, no external fetches except i.ytimg.com thumbnails)
and opens it in the browser unless --no-open.

Must render, in order (SPEC §7.2): header (verbatim query), coverage strip
(trust requirement), the playbook with per-point source links, ranked cards with
timestamped jump links, the collapsed "everything scanned" table (every candidate incl.
triaged-out and no-transcript, with scores/status), and a footer (models, duration).

The coverage strip, expanded-queries list, and full scan table are REQUIRED and must not
be dropped for visual minimalism (trust requirement, SPEC §7.3).

TODO(implement): render(), open_in_browser(), timestamp_url() helper.
"""

from __future__ import annotations

from pathlib import Path


def timestamp_url(video_id: str, seconds: int) -> str:
    """Deep link that opens a video at a moment: youtube.com/watch?v=ID&t=252s."""
    return f"https://www.youtube.com/watch?v={video_id}&t={seconds}s"


def render(context: dict, out_path: Path) -> Path:
    raise NotImplementedError("Render templates/report.html.j2 per SPEC §7.")
