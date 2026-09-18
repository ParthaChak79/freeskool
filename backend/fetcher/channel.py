"""Wraps SerpApi engine=youtube_channel with about=true.

Used only where channel-level authority signals (total_views, joined_date)
are needed beyond what video_details.py's embedded channel object already
gives (which has subscribers but not total_views/joined_date/country).
"""
from fetcher._client import serpapi_get


def get_channel_about(channel_id: str) -> dict:
    """channel_id may be a handle (e.g. "@Codevolution") or a UC... id.
    Confirmed live: the about fields are nested under channel_results, not
    top-level as SerpApi's docs summary suggests."""
    data = serpapi_get({"engine": "youtube_channel", "channel_id": channel_id, "about": "true"})
    cr = data.get("channel_results") or {}
    return {
        "channel_id": cr.get("external_id", channel_id),
        "title": cr.get("title", ""),
        "handle": cr.get("handle", ""),
        "subscribers": cr.get("subscribers"),
        "video_count": cr.get("video_count"),
        "country": cr.get("country", ""),
        "joined_date": cr.get("joined_date", ""),
        "total_views": cr.get("total_views"),
        "links": cr.get("links", []),
    }
