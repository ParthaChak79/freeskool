"""Wraps SerpApi engine=youtube. Returns normalized video + playlist candidates."""
from urllib.parse import parse_qs, urlparse

from fetcher._client import serpapi_get


def _extract_playlist_id(link: str) -> str:
    return parse_qs(urlparse(link).query).get("list", [""])[0]


def _extract_video_id_from_link(link: str) -> str:
    return parse_qs(urlparse(link).query).get("v", [""])[0]


def _parse_video(v: dict) -> dict:
    channel = v.get("channel") or {}
    return {
        "video_id": v.get("video_id", ""),
        "type": "video",
        "title": v.get("title", ""),
        "url": v.get("link", ""),
        "channel_name": channel.get("name", ""),
        "channel_url": channel.get("link", ""),
        "channel_verified": channel.get("verified", False),
        "views": v.get("views"),  # already an int on search results
        "published_date_text": v.get("published_date", ""),  # relative text, e.g. "3y ago"
        "length_text": v.get("length", ""),  # "H:MM:SS" or "MM:SS"
        "description": v.get("description", ""),
    }


def _parse_playlist(p: dict) -> dict:
    channel = p.get("channel") or {}
    preview_videos = []
    for pv in p.get("videos", []):
        preview_videos.append({
            "video_id": _extract_video_id_from_link(pv.get("link", "")),
            "title": pv.get("title", ""),
            "length_text": pv.get("length", ""),
            "url": pv.get("link", ""),
        })
    return {
        "playlist_id": _extract_playlist_id(p.get("link", "")),
        "type": "playlist",
        "title": p.get("title", ""),
        "url": p.get("link", ""),
        "channel_name": channel.get("name", ""),
        "channel_url": channel.get("link", ""),
        "channel_verified": channel.get("verified", False),
        "video_count": p.get("video_count", 0),
        "preview_videos": preview_videos,  # SerpApi exposes at most 2, see config.MAX_PLAYLIST_PREVIEW_VIDEOS
    }


def search_youtube(query: str, gl: str | None = None, hl: str | None = None) -> dict:
    """Returns {"videos": [...], "playlists": [...]} for a query."""
    params = {"engine": "youtube", "search_query": query}
    if gl:
        params["gl"] = gl
    if hl:
        params["hl"] = hl
    data = serpapi_get(params)
    videos = [_parse_video(v) for v in data.get("video_results", [])]
    playlists = [_parse_playlist(p) for p in data.get("playlist_results", [])]
    return {"videos": videos, "playlists": playlists}
