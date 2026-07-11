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
"""

from __future__ import annotations

import datetime as dt
import webbrowser
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import CandidateStatus

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def timestamp_url(video_id: str, seconds: int) -> str:
    """Deep link that opens a video at a moment: youtube.com/watch?v=ID&t=252s."""
    return f"https://www.youtube.com/watch?v={video_id}&t={int(seconds)}s"


def _fmt_ts(seconds) -> str:
    """Seconds -> mm:ss (or h:mm:ss)."""
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "0:00"
    h, rem = divmod(total, 3600)
    mm, ss = divmod(rem, 60)
    if h:
        return f"{h}:{mm:02d}:{ss:02d}"
    return f"{mm}:{ss:02d}"


def _fmt_duration(seconds) -> str:
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "?"
    h, rem = divmod(total, 3600)
    mm, ss = divmod(rem, 60)
    if h:
        return f"{h}:{mm:02d}:{ss:02d}"
    return f"{mm}:{ss:02d}"


def _fmt_views(views) -> str:
    try:
        v = int(float(views))
    except (TypeError, ValueError):
        return "?"
    for unit, scale in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if v >= scale:
            return f"{v / scale:.1f}{unit}".rstrip("0").rstrip(".")
    return str(v)


def _status_class(status: CandidateStatus) -> str:
    if status == CandidateStatus.DEEP_READ:
        return "status-deep"
    if status in (CandidateStatus.NO_TRANSCRIPT,):
        return "status-no"
    return "status-out"


def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    env.filters["fmt_ts"] = _fmt_ts
    env.filters["fmt_duration"] = _fmt_duration
    env.filters["fmt_views"] = _fmt_views
    return env


def _build_context(
    query: str,
    intent_summary: str,
    search_queries: list[str],
    candidates: list,  # list[Candidate]
    ranked: list,  # list[tuple[Candidate, DeepResult]]
    playbook,  # Playbook | None
    model: str,
    triage_model: str,
    results_count: int,
    duration_seconds: float,
) -> dict:
    results_view = []
    for c, d in ranked:
        results_view.append(
            {
                "candidate": c,
                "deep": d,
                "jump_url": timestamp_url(c.video_id, d.best_timestamp_seconds or 0),
            }
        )

    # Group by tier for display (order: strong -> partial -> weak). Results missing a
    # tier (older callers / fixtures) fall back to a score-derived tier.
    tier_meta = {
        "strong": ("Strong matches", "Content directly addresses your query — start here."),
        "partial": ("Partial matches", "A useful section or angle, not the main focus."),
        "weak": (
            "Related — different focus",
            "On the same topic but aimed elsewhere; each notes how it connects.",
        ),
    }
    grouped: dict[str, list[dict]] = {"strong": [], "partial": [], "weak": []}
    for rv in results_view:
        tier = rv["deep"].tier
        if tier not in grouped:
            score = rv["deep"].score
            tier = "strong" if score >= 7.5 else ("partial" if score >= 5.0 else "weak")
        grouped[tier].append(rv)
    tiers_view = [
        {"key": k, "label": tier_meta[k][0], "hint": tier_meta[k][1], "results": grouped[k]}
        for k in ("strong", "partial", "weak")
        if grouped[k]
    ]

    all_candidates = [{"candidate": c, "status_class": _status_class(c.status)} for c in candidates]

    return {
        "query": query,
        "intent_summary": intent_summary,
        "coverage": {
            "searches": len(search_queries),
            "found": len(candidates),
            "transcripts": sum(1 for c in candidates if c.has_transcript),
            "deep_read": sum(1 for c in candidates if c.status == CandidateStatus.DEEP_READ),
            # Everything deep-read is shown, grouped by tier — no arbitrary cut.
            "shown": len(results_view),
            "expanded_queries": search_queries,
        },
        "playbook": playbook,
        "results": results_view,
        "tiers": tiers_view,
        "all_candidates": all_candidates,
        "model": model,
        "triage_model": triage_model,
        "duration_seconds": duration_seconds,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def render(
    query: str,
    intent_summary: str,
    search_queries: list[str],
    candidates: list,
    ranked: list,
    playbook,
    model: str,
    triage_model: str,
    results_count: int,
    duration_seconds: float,
    out_path: Path,
) -> Path:
    """Render templates/report.html.j2 to `out_path`. SPEC §7."""
    env = _make_env()
    context = _build_context(
        query, intent_summary, search_queries, candidates, ranked, playbook,
        model, triage_model, results_count, duration_seconds,
    )
    template = env.get_template("report.html.j2")
    html = template.render(**context)
    out_path = Path(out_path)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def open_in_browser(path: Path) -> None:
    """Best-effort open of the report in the user's default browser (SPEC §5)."""
    try:
        webbrowser.open(f"file://{Path(path).resolve()}")
    except Exception:
        pass
