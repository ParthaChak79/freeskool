"""Metadata pre-filter: duration/playlist-size/recency thresholds from
instructions.md, sourced from SerpApi's youtube_search fetcher output.
Keeps the top MAX_CANDIDATES by a lightweight metadata-only score, so only
those go on to (paid) transcript fetching + LLM scoring in Phase 4.

Playlist recency is NOT filtered here: SerpApi's playlist_results carries no
date field, and fetching engine=youtube_video per playlist just to get one
just for a pre-filter cutoff would be wasted spend on candidates that might
not survive anyway. Playlists are filtered on video_count only; recency is
scored properly in Phase 5 using data Phase 4 already fetches for the
survivors' preview episodes.
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


def _filter_playlists(playlists: list[dict]) -> list[dict]:
    kept = []
    for p in playlists:
        count = p.get("video_count", 0)
        if not (config.MIN_PLAYLIST_SIZE <= count <= config.MAX_PLAYLIST_SIZE):
            continue
        kept.append(p)
    return kept


def _score_videos(videos: list[dict]) -> None:
    max_views = max((v.get("views") or 0 for v in videos), default=1)
    for v in videos:
        v["metadata_score"] = (
            normalized_view_count(v.get("views"), max_views) * 0.6
            + recency_score(v.get("age_years")) * 0.4
        )


def _score_playlists(playlists: list[dict]) -> None:
    # No per-playlist view/recency data is available pre-transcript-fetch (see
    # module docstring), so video_count is the only cheap completeness signal.
    max_count = max((p.get("video_count") or 0 for p in playlists), default=1)
    for p in playlists:
        count_ratio = min((p.get("video_count") or 0) / max_count, 1.0) if max_count else 0.0
        p["metadata_score"] = count_ratio


def prefilter_candidates(
    videos: list[dict],
    playlists: list[dict],
    recency_years: int = config.RECENCY_YEARS_DEFAULT,
    top_n: int = config.MAX_CANDIDATES,
) -> list[dict]:
    """Returns up to top_n candidates (mixed videos + playlists), sorted by metadata_score desc."""
    filtered_videos = _filter_videos(videos, recency_years)
    filtered_playlists = _filter_playlists(playlists)

    _score_videos(filtered_videos)
    _score_playlists(filtered_playlists)

    combined = filtered_videos + filtered_playlists
    combined.sort(key=lambda c: c["metadata_score"], reverse=True)
    return combined[:top_n]
