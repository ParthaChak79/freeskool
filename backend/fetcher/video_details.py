"""Wraps SerpApi engine=youtube_video. Returns full metadata for a video ID."""
from fetcher._client import serpapi_get


def get_video_details(video_id: str) -> dict:
    data = serpapi_get({"engine": "youtube_video", "v": video_id})
    channel = data.get("channel") or {}
    transcript = data.get("transcript") or {}
    # description is an object ({"content": str, "links": [...]}) on this engine,
    # unlike the plain string returned in engine=youtube's video_results.
    description = data.get("description")
    description_text = description.get("content", "") if isinstance(description, dict) else (description or "")
    return {
        "video_id": video_id,
        "title": data.get("title", ""),
        "channel_name": channel.get("name", ""),
        "channel_url": channel.get("link", ""),
        "channel_verified": channel.get("verified", False),
        "subscribers_text": channel.get("subscribers", ""),
        "extracted_subscribers": channel.get("extracted_subscribers"),
        "views_text": data.get("views", ""),
        "extracted_views": data.get("extracted_views"),
        "likes_text": data.get("likes", ""),
        "extracted_likes": data.get("extracted_likes"),
        "published_date": data.get("published_date", ""),  # absolute date, e.g. "Oct 27, 2025"
        "description": description_text,
        "chapters": data.get("chapters"),
        "related_videos": data.get("related_videos", []),
        "transcript_link": transcript.get("serpapi_link", ""),
    }
