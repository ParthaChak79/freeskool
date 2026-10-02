"""Metadata pre-filter, sourced from SerpApi's youtube_search fetcher output.
Keeps the top MAX_CANDIDATES by a lightweight metadata-only score, so only
those go on to (paid) transcript fetching + LLM scoring in Phase 4.

Videos only — playlists are excluded from all modes, see
fetcher/youtube_search.py's module docstring.

Deviates from instructions.md's filter rules per explicit user direction:
a hard 3-hour duration ceiling and 3-year age cutoff both excluded videos
outright; now there's only a floor (5 min, to exclude shorts/clips) — a
longer video is treated as a positive signal (can cover more ground), not
a reason to exclude, and an older video is no longer excluded either.
"""
import config
from scorer.formulas import (
    duration_score,
    normalized_view_count,
    parse_date_to_age_years,
    parse_duration_to_seconds,
    recency_score,
)


def _filter_videos(videos: list[dict]) -> list[dict]:
    kept = []
    for v in videos:
        duration_sec = parse_duration_to_seconds(v.get("length_text", ""))
        if duration_sec is None:
            continue  # unparseable duration on a video is unusual; skip rather than guess
        if duration_sec < config.MIN_VIDEO_DURATION_SEC:
            continue

        age_years = parse_date_to_age_years(v.get("published_date_text", ""))
        v = {**v, "duration_sec": duration_sec, "age_years": age_years}
        kept.append(v)
    return kept


def _score_videos(videos: list[dict]) -> None:
    max_views = max((v.get("views") or 0 for v in videos), default=1)
    max_duration = max((v.get("duration_sec") or 0 for v in videos), default=1)
    for v in videos:
        v["metadata_score"] = (
            normalized_view_count(v.get("views"), max_views) * 0.5
            + duration_score(v.get("duration_sec"), max_duration) * 0.3
            + recency_score(v.get("age_years")) * 0.2
        )


def prefilter_candidates(
    videos: list[dict],
    top_n: int = config.MAX_CANDIDATES,
) -> list[dict]:
    """Returns up to top_n video candidates, sorted by metadata_score desc."""
    filtered_videos = _filter_videos(videos)
    _score_videos(filtered_videos)
    filtered_videos.sort(key=lambda c: c["metadata_score"], reverse=True)
    return filtered_videos[:top_n]
