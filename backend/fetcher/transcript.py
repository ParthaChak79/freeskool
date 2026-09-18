"""Wraps SerpApi engine=youtube_video_transcript. Returns cleaned transcript text + chapters."""
import re

from cache.db import get_cached_transcript, set_cached_transcript
from fetcher._client import SerpApiError, serpapi_get

FILLER_PATTERN = re.compile(r"\b(um+|uh+|you know|like)\b", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")

CHARS_PER_TOKEN = 4  # rough approximation used only for truncation, not billing


def _clean(text: str) -> str:
    text = FILLER_PATTERN.sub("", text)
    text = WHITESPACE_PATTERN.sub(" ", text)
    return text.strip()


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    max_chars = max_tokens * CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0]


def get_transcript(video_id: str, language_code: str = "en", type_: str | None = None) -> dict:
    """Returns cleaned transcript text (timestamps stripped, filler removed,
    whitespace collapsed) plus available chapters. No truncation applied here —
    callers (Phase 4's llm_scorer) truncate per instructions.md's per-context limits."""
    cached = get_cached_transcript(video_id)
    if cached is not None:
        return {
            "video_id": video_id, "text": cached, "segment_count": None,
            "chapters": None, "available_transcripts": [], "has_transcript": bool(cached),
        }

    params = {"engine": "youtube_video_transcript", "v": video_id, "language_code": language_code}
    if type_:
        params["type"] = type_
    try:
        data = serpapi_get(params)
    except SerpApiError:
        # No transcript in the requested language (disabled captions, non-English,
        # etc.) is an expected outcome per instructions.md's Known Limitations,
        # not a hard failure — callers fall back to a metadata-only score.
        return {
            "video_id": video_id, "text": "", "segment_count": 0,
            "chapters": None, "available_transcripts": [], "has_transcript": False,
        }
    segments = data.get("transcript") or []
    raw_text = " ".join(seg.get("snippet", "") for seg in segments)
    cleaned = _clean(raw_text)
    set_cached_transcript(video_id, cleaned)
    return {
        "video_id": video_id,
        "text": cleaned,
        "segment_count": len(segments),
        "chapters": data.get("chapters"),
        "available_transcripts": data.get("available_transcripts", []),
        "has_transcript": len(segments) > 0,
    }
