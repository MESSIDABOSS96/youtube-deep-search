"""CLI entry point + pipeline orchestration (SPEC §5, §6).

Parses args (SPEC §5), resolves config, then drives the pipeline (SPEC §6.0) with a live
`rich` progress line per stage:

    query
      -> clarify_and_expand        (ranking.py)   [may ask questions in terminal]
      -> search_candidates          (youtube.py)
      -> fetch_transcripts          (transcripts.py)
      -> triage                     (ranking.py)   -> keep top deep_read_count()
      -> deep_rank                  (ranking.py)
      -> synthesize_playbook        (synthesis.py) [unless --no-brief]
      -> render + open              (report.py)

Handles the failure modes in SPEC §9 with friendly messages, never a traceback.

TODO(implement): build_parser(), run(), and the async orchestration.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Console-script entry (see pyproject [project.scripts]). SPEC §5."""
    raise NotImplementedError("Wire arg parsing + pipeline orchestration per SPEC §5–6.")


if __name__ == "__main__":
    sys.exit(main())
