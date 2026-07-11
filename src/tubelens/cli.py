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
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re
import sys
from pathlib import Path

from rich.console import Console

from . import __version__
from .config import Config, ConfigError, deep_read_count, load_config
from .llm import warn_if_expensive
from .models import CandidateStatus
from .ranking import (
    clarify_and_expand,
    comparative_rank,
    deep_rank,
    tier_from_score,
    triage,
)
from .report import open_in_browser, render
from .synthesis import synthesize_playbook
from .transcripts import fetch_transcripts
from .youtube import YouTubeError, search_candidates

console = Console(stderr=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tubelens",
        description="Content-aware YouTube search — ranks videos by what's said, not titles.",
    )
    p.add_argument("query", help="Natural-language, intent-based search query.")
    p.add_argument(
        "--results", type=int, default=None,
        help="how many top videos to deep-read and rank; all are shown, "
        "grouped by match strength (default 10)",
    )
    p.add_argument(
        "--scan", type=int, default=None,
        help="max candidate videos to scan (default 80, cap 200)",
    )
    p.add_argument("--model", default=None, help="LLM for deep rank + synthesis, litellm format")
    p.add_argument(
        "--triage-model", default=None, dest="triage_model",
        help="LLM for stage-1 triage (default: same as --model)",
    )
    p.add_argument("--no-brief", action="store_true", help="skip the synthesized playbook section")
    p.add_argument("--no-clarify", action="store_true", help="never ask clarifying questions")
    p.add_argument(
        "--open", dest="open", action="store_true", default=True,
        help="open report in browser (default)",
    )
    p.add_argument("--no-open", dest="open", action="store_false", help="do not open the report")
    p.add_argument(
        "--out", default=None,
        help="output path (default ./tubelens-<slug>-<timestamp>.html)",
    )
    p.add_argument(
        "--json", dest="json", action="store_true",
        help="also write raw results as JSON next to the HTML",
    )
    p.add_argument("--lang", default=None, help="transcript language preference (default 'en')")
    p.add_argument("-v", "--verbose", action="store_true", help="show pipeline progress detail")
    p.add_argument("--version", action="version", version=f"tubelens {__version__}")
    return p


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "query"


def _default_out(query: str) -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.cwd() / f"tubelens-{_slugify(query)}-{ts}.html"


def _ask_clarifying(ce) -> object:
    """Print clarifying questions, read answers from stdin (SPEC §6.1)."""
    answers: list[str] = []
    if not ce.clarifying_questions:
        return ce
    console.print("[bold]tubelens needs a little more context:[/bold]")
    for q in ce.clarifying_questions[:2]:
        console.print(f"  • {q}")
        console.print("    [press Enter to skip]")
        try:
            a = input("  > ")
        except (EOFError, KeyboardInterrupt):
            break
        if a.strip():
            answers.append(f"{q} {a.strip()}")
    if not answers:
        return ce
    return answers


async def _run_pipeline(cfg: Config) -> int:
    started = dt.datetime.now()
    console.print(f"[bold]tubelens[/bold] — {cfg.query}")

    # ── Stage 1: clarify + expand ────────────────────────────────────────
    with console.status("[cyan]Expanding query…[/cyan]"):
        ce = await clarify_and_expand(cfg.query, cfg.model, cfg.clarify)

    if cfg.clarify and ce.ambiguous and ce.clarifying_questions:
        answers = _ask_clarifying(ce)
        if isinstance(answers, list) and answers:
            with console.status("[cyan]Re-expanding with your answers…[/cyan]"):
                ce = await clarify_and_expand(
                    cfg.query + "\n\nClarifying answers:\n" + "\n".join(answers),
                    cfg.model,
                    allow_clarify=False,
                )

    if not ce.search_queries:
        ce.search_queries = [cfg.query]
    console.print(
        f"[green]✓[/green] {len(ce.search_queries)} searches: "
        f"{', '.join(ce.search_queries)}"
    )

    # ── Stage 2: search YouTube ──────────────────────────────────────────
    with console.status(f"[cyan]Searching YouTube ({len(ce.search_queries)} queries)…[/cyan]"):
        try:
            candidates = await search_candidates(
                ce.search_queries, cfg.youtube_api_key, cfg.scan, cfg.lang
            )
        except YouTubeError as exc:
            console.print(f"[red]tubelens:[/red] {exc}")
            return 1
    if not candidates:
        console.print(
            "[red]tubelens:[/red] No videos found. The tool expanded your query into:\n  - "
            + "\n  - ".join(ce.search_queries)
            + "\nTry rephrasing, or run with --scan 120."
        )
        return 1
    console.print(f"[green]✓[/green] {len(candidates)} unique videos after search + filter")

    # ── Stage 3: transcripts ─────────────────────────────────────────────
    with console.status("[cyan]Fetching transcripts…[/cyan]"):
        candidates = await fetch_transcripts(candidates, cfg.lang)
    with_transcript = [c for c in candidates if c.has_transcript]
    console.print(
        f"[green]✓[/green] {len(with_transcript)}/{len(candidates)} transcripts retrieved"
    )

    if len(with_transcript) < 5:
        console.print(
            "[yellow]tubelens:[/yellow] warning — fewer than 5 candidates have transcripts. "
            "Ranking quality will be limited."
        )

    if not with_transcript:
        console.print("[red]tubelens:[/red] No transcripts could be retrieved for any candidate.")
        _render_report(cfg, ce, candidates, [], None, started)
        return 1

    # ── Stage 4: triage ─────────────────────────────────────────────────
    with console.status(f"[cyan]Triaging {len(with_transcript)} candidates…[/cyan]"):
        triage_results = await triage(with_transcript, ce.intent_summary, cfg.triage_model)
    triage_by_id = {t.video_id: t for t in triage_results}
    for c in with_transcript:
        if c.video_id in triage_by_id:
            c.triage = triage_by_id[c.video_id]

    # Sort triaged candidates by triage score desc, ties broken by view count.
    triaged = [c for c in with_transcript if c.triage is not None]
    triaged.sort(
        key=lambda c: (c.triage.score, c.view_count),
        reverse=True,
    )

    # SPEC §6.4: deep-read pool must never be smaller than --results.
    pool = triaged[: deep_read_count(cfg.results)]
    console.print(f"[green]✓[/green] top {len(pool)} selected for deep-read")

    # ── Stage 5: deep rank ──────────────────────────────────────────────
    with console.status(f"[cyan]Deep-reading top {len(pool)}…[/cyan]"):
        deep_results = await deep_rank(pool, ce.intent_summary, cfg.model)
    deep_by_id = {d.video_id: d for d in deep_results}
    for c in pool:
        if c.video_id in deep_by_id:
            c.deep = deep_by_id[c.video_id]
            c.status = CandidateStatus.DEEP_READ
    # Candidates triaged but not deep-read: "triaged out".
    for c in with_transcript:
        if c.deep is None and c.status == CandidateStatus.FOUND:
            c.status = CandidateStatus.TRIAGED_OUT

    # Provisional order: stage-2 score (isolated, uncalibrated) as a starting point.
    ranked_pairs = [(c, c.deep) for c in pool if c.deep is not None]
    ranked_pairs.sort(key=lambda pair: pair[1].score, reverse=True)

    # ── Stage 5b: comparative rank ──────────────────────────────────────
    # One call that sees all deep-read summaries side by side: reliable *relative*
    # ordering + a tier per video. Falls back to score order + score-derived tiers.
    with console.status("[cyan]Comparative ranking…[/cyan]"):
        assignments = await comparative_rank(ranked_pairs, ce.intent_summary, cfg.model)
    if assignments is not None:
        order = {t.video_id: i for i, t in enumerate(assignments)}
        by_id = {t.video_id: t for t in assignments}
        ranked_pairs.sort(key=lambda pair: order.get(pair[0].video_id, len(order)))
        for c, d in ranked_pairs:
            t = by_id.get(c.video_id)
            d.tier = (t.tier if t else "") or tier_from_score(d.score)
            # Relation note ("covers X, not Y") — how a non-strong match diverges.
            d.relation = t.note if t else ""
    else:
        for _c, d in ranked_pairs:
            d.tier = tier_from_score(d.score)
        if len(ranked_pairs) >= 2:
            console.print(
                "[yellow]tubelens:[/yellow] comparative ranking unavailable; "
                "using per-video scores."
            )

    # Show everything that was deep-read, grouped by tier — no arbitrary display cut.
    # (--results sizes the deep-read pool; the report labels each tier honestly.)
    n_strong = sum(1 for _c, d in ranked_pairs if d.tier == "strong")
    n_partial = sum(1 for _c, d in ranked_pairs if d.tier == "partial")
    n_weak = len(ranked_pairs) - n_strong - n_partial
    console.print(
        f"[green]✓[/green] ranked {len(ranked_pairs)} results "
        f"({n_strong} strong / {n_partial} partial / {n_weak} weak)"
    )

    # ── Stage 6: synthesis ──────────────────────────────────────────────
    playbook = None
    if cfg.brief and ranked_pairs:
        with console.status("[cyan]Synthesizing brief…[/cyan]"):
            playbook = await synthesize_playbook(ranked_pairs, ce.intent_summary, cfg.model)
        if playbook is None:
            console.print("[yellow]tubelens:[/yellow] synthesis failed; rendering without a brief.")

    # ── Stage 7: render ────────────────────────────────────────────────
    out_path = _render_report(cfg, ce, candidates, ranked_pairs, playbook, started)

    console.print(f"[green]✓[/green] Report: {out_path}")
    if cfg.open_report:
        open_in_browser(out_path)
    return 0


def _render_report(cfg, ce, candidates, ranked_pairs, playbook, started) -> Path:
    out_path = Path(cfg.out) if cfg.out else _default_out(cfg.query)
    duration = (dt.datetime.now() - started).total_seconds()
    render(
        query=cfg.query,
        intent_summary=ce.intent_summary,
        search_queries=ce.search_queries,
        candidates=candidates,
        ranked=ranked_pairs,
        playbook=playbook,
        model=cfg.model,
        triage_model=cfg.triage_model,
        results_count=cfg.results,
        duration_seconds=duration,
        out_path=out_path,
    )
    if cfg.json_output:
        json_path = out_path.with_suffix(".json")
        json_path.write_text(
            json.dumps(
                {
                    "query": cfg.query,
                    "intent_summary": ce.intent_summary,
                    "search_queries": ce.search_queries,
                    "results": [
                        {
                            "video_id": c.video_id,
                            "title": c.title,
                            "channel": c.channel,
                            "tier": d.tier,
                            "score": d.score,
                            "why": d.why,
                            "relation": d.relation,
                            "coverage": d.coverage,
                            "best_timestamp_seconds": d.best_timestamp_seconds,
                            "timestamp_reason": d.timestamp_reason,
                            "key_points": d.key_points,
                        }
                        for c, d in ranked_pairs
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return out_path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        cfg = load_config(args)
    except ConfigError as exc:
        console.print(f"[red]tubelens:[/red] {exc}")
        return 2

    if not cfg.query.strip():
        console.print("[red]tubelens:[/red] please provide a search query.")
        return 2

    try:
        cfg.validate_keys()
    except ConfigError as exc:
        console.print(f"[red]tubelens:[/red] {exc}")
        return 2

    warn_if_expensive(cfg.model)

    try:
        return asyncio.run(_run_pipeline(cfg))
    except KeyboardInterrupt:
        console.print("\n[yellow]tubelens:[/yellow] interrupted.")
        return 130
    except Exception as exc:  # noqa: BLE001 — never a traceback to the user (SPEC §9).
        console.print(f"[red]tubelens:[/red] unexpected error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
