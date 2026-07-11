"""Shared test fixtures (SPEC §10). No network — everything is canned."""
from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def make_search_response(video_ids: list[str]) -> dict:
    """Build a canned YouTube search.list response."""
    items = []
    for vid in video_ids:
        items.append(
            {
                "id": {"kind": "youtube#video", "videoId": vid},
                "snippet": {
                    "title": f"Video {vid}",
                    "channelTitle": f"Channel {vid}",
                    "thumbnails": {
                        "high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"},
                    },
                },
            }
        )
    return {"items": items, "pageInfo": {"totalResults": len(items)}}


def make_videos_response(items: list[dict]) -> dict:
    return {"items": items}


def make_video_item(
    vid: str,
    duration: str = "PT10M0S",
    views: int = 1000,
    live: bool = False,
    lang: str = "en",
    title: str | None = None,
) -> dict:
    return {
        "id": vid,
        "snippet": {
            "title": title or f"Video {vid}",
            "channelTitle": f"Channel {vid}",
            "liveBroadcastContent": "live" if live else "none",
            "defaultAudioLanguage": lang,
            "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}},
        },
        "statistics": {"viewCount": str(views)},
        "contentDetails": {"duration": duration},
    }
