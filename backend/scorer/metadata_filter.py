"""Metadata pre-filter: duration/recency thresholds from instructions.md,
sourced from SerpApi's youtube_search fetcher output. Keeps the top
MAX_CANDIDATES by a lightweight metadata-only score, so only those go on to
(paid) transcript fetching + LLM scoring in Phase 4.

Videos only — playlists are excluded from all modes, see
fetcher/youtube_search.py's module docstring.
"""
import config
from scorer.formulas import (
    normalized_view_count,
    parse_date_to_age_years,
    parse_duration_to_seconds,
    recency_score,
)


def _filter_videos(videos: list[dict], recency_years: int) -> list[dict]:
    kept = []
    for v in videos:
        duration_sec = parse_duration_to_seconds(v.get("length_text", ""))
        if duration_sec is None:
            continue  # unparseable duration on a video is unusual; skip rather than guess
        if not (config.MIN_VIDEO_DURATION_SEC <= duration_sec <= config.MAX_VIDEO_DURATION_SEC):
            continue

        age_years = parse_date_to_age_years(v.get("published_date_text", ""))
        if age_years is not None and age_years > recency_years:
            continue

        v = {**v, "duration_sec": duration_sec, "age_years": age_years}
        kept.append(v)
    return kept


def _score_videos(videos: list[dict]) -> None:
    max_views = max((v.get("views") or 0 for v in videos), default=1)
    for v in videos:
        v["metadata_score"] = (
            normalized_view_count(v.get("views"), max_views) * 0.6
            + recency_score(v.get("age_years")) * 0.4
        )


def prefilter_candidates(
    videos: list[dict],
    recency_years: int = config.RECENCY_YEARS_DEFAULT,
    top_n: int = config.MAX_CANDIDATES,
) -> list[dict]:
    """Returns up to top_n video candidates, sorted by metadata_score desc."""
    filtered_videos = _filter_videos(videos, recency_years)
    _score_videos(filtered_videos)
    filtered_videos.sort(key=lambda c: c["metadata_score"], reverse=True)
    return filtered_videos[:top_n]
