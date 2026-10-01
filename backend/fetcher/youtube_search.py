"""Wraps SerpApi engine=youtube. Returns normalized video candidates.

Playlists are deliberately ignored: all three modes (Best Pick, Learning
Path, Skill Mix) recommend individual videos only — a playlist's full
content can't be judged from SerpApi's 2-episode preview, and dropping it
also halves per-candidate SerpApi spend (a playlist candidate cost 2x a
video candidate: transcript + video_details per previewed episode)."""
from fetcher._client import serpapi_get


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


def search_youtube(query: str, gl: str | None = None, hl: str | None = None) -> dict:
    """Returns {"videos": [...]} for a query. See module docstring on why
    playlist_results is ignored entirely."""
    params = {"engine": "youtube", "search_query": query}
    if gl:
        params["gl"] = gl
    if hl:
        params["hl"] = hl
    data = serpapi_get(params)
    videos = [_parse_video(v) for v in data.get("video_results", [])]
    return {"videos": videos}
