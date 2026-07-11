"""Playbook synthesis (SPEC §6.6).

One LLM call over the top ~6 deep-read results' key_points/why/metadata. Produces a titled
brief of 3–6 actionable points; every point must cite >=1 source video by index so the
brief is verifiable. Synthesize only from provided material (no outside knowledge); if the
videos disagree, say so. Skipped entirely when --no-brief.
"""

from __future__ import annotations

from .llm import LLMError, complete_json
from .models import Candidate, DeepResult, Playbook, PlaybookPoint

SYNTH_TOP = 6  # SPEC §6.6: synthesize over the top ~6 deep-read results.


def _build_synth_input(items: list[tuple[Candidate, DeepResult]]) -> str:
    blocks = []
    for i, (c, d) in enumerate(items):
        key_points = "\n".join(f"  - {kp}" for kp in d.key_points) or "  - (none)"
        blocks.append(
            f"[{i}] title: {c.title}\n"
            f"    channel: {c.channel}\n"
            f"    video_id: {c.video_id}\n"
            f"    best_timestamp_seconds: {d.best_timestamp_seconds}\n"
            f"    why it matches: {d.why}\n"
            f"    key_points:\n{key_points}"
        )
    return "\n\n".join(blocks)


def _synth_prompt(items: list[tuple[Candidate, DeepResult]], intent: str) -> str:
    return (
        "You are writing a short, actionable 'playbook' synthesized ONLY from the videos "
        "below. Do not use any outside knowledge. If the videos disagree on a point, say so "
        "explicitly. If the material does not support enough points, write fewer — never "
        "invent.\n\n"
        f"USER INTENT: {intent}\n\n"
        f"VIDEOS (each referenced by its [index]):\n{_build_synth_input(items)}\n\n"
        "Write 3–6 actionable points. EVERY point must cite at least one source video by "
        "its [index] and a timestamp in seconds. Render each point as JSON:\n"
        "{\n"
        '  "title": "<short playbook title>",\n'
        '  "points": [\n'
        '    {\n'
        '      "text": "<the actionable point>",\n'
        '      "sources": [{"video_index": 0, "seconds": 252}, ...]\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Respond with ONLY that JSON object. video_index is the [index] from the list above."
    )


def _sanitize_playbook(pb: Playbook, max_index: int) -> Playbook:
    """Drop any source citations that point at nonexistent videos."""
    clean_points: list[PlaybookPoint] = []
    for p in pb.points:
        clean_sources = [s for s in p.sources if 0 <= s.video_index < max_index]
        if not clean_sources and p.sources:
            # The model cited a bogus index; drop the point rather than show an
            # unverifiable claim (trust requirement, SPEC §7.3).
            continue
        clean_points.append(PlaybookPoint(text=p.text, sources=clean_sources))
    return Playbook(title=pb.title, points=clean_points)


async def synthesize_playbook(
    top: list[tuple[Candidate, DeepResult]], intent: str, model: str
) -> Playbook | None:
    """SPEC §6.6. Returns None if synthesis fails (caller renders without a brief)."""
    items = top[:SYNTH_TOP]
    if not items:
        return None
    try:
        pb = await complete_json(_synth_prompt(items, intent), Playbook, model)
    except LLMError:
        return None
    return _sanitize_playbook(pb, max_index=len(items))
