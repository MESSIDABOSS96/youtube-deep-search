"""Cross-run transcript cache (SPEC §6.3).

Transcripts never change, so re-fetching the same video on every run is pure waste — and,
worse, the burst of repeat requests is exactly what trips YouTube's rate limiter and gets
a user's IP temporarily blocked. This cache means a video's transcript is fetched at most
once, ever, per language. Repeated runs of the same query make ~zero transcript requests.

Layout: ~/.cache/tubelens/transcripts/<video_id>.<lang>.json
Entry kinds:
  - {"kind": "transcript", "segments": [{text,start,duration}, ...]}  — cached forever
  - {"kind": "none", "ts": <epoch>}                                    — "no captions",
        honored for NEGATIVE_TTL_SECONDS then re-checked (captions may be added later)

The cache is best-effort: any read/write failure is swallowed and treated as a miss, so a
broken or unwritable cache never breaks a run. Rate-limit/IP-block failures are NEVER
cached — caching those would poison the cache with false "no transcript" entries.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

CACHE_DIR = Path("~/.cache/tubelens/transcripts").expanduser()
# A "no captions" result may become stale if the uploader adds captions later.
NEGATIVE_TTL_SECONDS = 14 * 24 * 3600  # 14 days


def _path(video_id: str, lang: str) -> Path:
    safe_id = "".join(ch for ch in video_id if ch.isalnum() or ch in "-_")
    safe_lang = (lang or "any").replace("/", "_")
    return CACHE_DIR / f"{safe_id}.{safe_lang}.json"


def get(video_id: str, lang: str) -> list[dict] | None:
    """Return cached raw segments, [] for a known-no-transcript, or None on miss.

    A non-empty list is a positive hit; [] means "we already know this video has no
    usable transcript" (still fresh); None means cache miss or expired negative entry.
    """
    p = _path(video_id, lang)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    kind = data.get("kind")
    if kind == "transcript":
        segs = data.get("segments")
        return segs if isinstance(segs, list) and segs else None
    if kind == "none":
        if time.time() - float(data.get("ts", 0)) < NEGATIVE_TTL_SECONDS:
            return []
        return None
    return None


def put_transcript(video_id: str, lang: str, segments: list[dict]) -> None:
    """Cache a successful transcript (kept forever)."""
    _write(video_id, lang, {"kind": "transcript", "segments": segments})


def put_none(video_id: str, lang: str) -> None:
    """Cache a genuine 'no transcript available' result (with a TTL)."""
    _write(video_id, lang, {"kind": "none", "ts": time.time()})


def _write(video_id: str, lang: str, obj: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _path(video_id, lang).write_text(json.dumps(obj), encoding="utf-8")
    except Exception:
        pass  # best-effort — a failed cache write must never break a run
