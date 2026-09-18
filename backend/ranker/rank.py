"""Weighted final scoring — instructions.md's Video Score / Playlist Score
formulas, exactly as written, sourced from SerpApi fields via Phase 2's
fetchers. Candidates without an LLM score (no_transcript flag from Phase 4)
fall back to a metadata-only score using the non-LLM components, renormalized
to sum to 1 — instructions.md doesn't specify this case, but Known Limitations
says such candidates should get "a metadata-only score with a flag" rather
than being dropped, so ranking has to define what that score is.
"""
import config
from fetcher.video_details import get_video_details
from scorer.formulas import (
    channel_authority_score,
    normalized_view_count,
    parse_date_to_age_years,
    recency_score,
)

VIDEO_WEIGHTS = {"llm": 0.50, "views": 0.15, "like_ratio": 0.15, "recency": 0.10, "channel_authority": 0.10}
PLAYLIST_WEIGHTS = {"llm": 0.55, "views": 0.10, "completeness": 0.20, "recency": 0.15}


def _enrich_video(candidate: dict) -> dict:
    details = get_video_details(candidate["video_id"])
    age_years = parse_date_to_age_years(details["published_date"]) or candidate.get("age_years")
    return {
        **candidate,
        "extracted_views": details["extracted_views"] or candidate.get("views") or 0,
        "extracted_likes": details["extracted_likes"] or 0,
        "extracted_subscribers": details["extracted_subscribers"] or 0,
        "age_years": age_years,
        "channel_name": details["channel_name"] or candidate.get("channel_name", ""),
    }


def _enrich_playlist(candidate: dict) -> dict:
    n = min(config.PLAYLIST_TRANSCRIPT_VIDEOS, config.MAX_PLAYLIST_PREVIEW_VIDEOS)
    episodes = candidate.get("preview_videos", [])[:n]
    views, ages = [], []
    for ep in episodes:
        details = get_video_details(ep["video_id"])
        if details["extracted_views"]:
            views.append(details["extracted_views"])
        age = parse_date_to_age_years(details["published_date"])
        if age is not None:
            ages.append(age)
    avg_views = sum(views) / len(views) if views else 0
    avg_age = sum(ages) / len(ages) if ages else None
    return {**candidate, "avg_views": avg_views, "age_years": avg_age}


def _score_video(candidate: dict, max_views: int, llm_score: dict | None) -> dict:
    like_ratio = 0.0
    if candidate["extracted_views"]:
        like_ratio = min(candidate["extracted_likes"] / candidate["extracted_views"], 1.0)

    components = {
        "views": normalized_view_count(candidate["extracted_views"], max_views),
        "like_ratio": like_ratio,
        "recency": recency_score(candidate["age_years"]),
        "channel_authority": channel_authority_score(candidate["extracted_subscribers"]),
    }
    return _combine(candidate, VIDEO_WEIGHTS, components, llm_score)


def _score_playlist(candidate: dict, max_views: int, llm_score: dict | None) -> dict:
    completeness = min((candidate.get("video_count") or 0) / config.EXPECTED_PLAYLIST_SIZE, 1.0)
    components = {
        "views": normalized_view_count(candidate["avg_views"], max_views),
        "completeness": completeness,
        "recency": recency_score(candidate["age_years"]),
    }
    return _combine(candidate, PLAYLIST_WEIGHTS, components, llm_score)


def _combine(candidate: dict, weights: dict, components: dict, llm_score: dict | None) -> dict:
    has_llm = bool(llm_score) and llm_score.get("score") is not None
    llm_normalized = (llm_score["score"] / 10.0) if has_llm else None

    if has_llm:
        final_0_1 = weights["llm"] * llm_normalized + sum(
            weights[k] * v for k, v in components.items()
        )
        flag = None
    else:
        # Metadata-only fallback: renormalize the non-LLM weights to sum to 1.
        non_llm_weight_total = sum(w for k, w in weights.items() if k != "llm")
        final_0_1 = sum(weights[k] / non_llm_weight_total * v for k, v in components.items())
        flag = "metadata_only"

    return {
        **candidate,
        "score": round(final_0_1 * 10, 1),
        "score_components": components,
        "llm_content_score": llm_score.get("score") if llm_score else None,
        "level": llm_score.get("level") if llm_score else None,
        "covers_topic": llm_score.get("covers_topic") if llm_score else None,
        "subtopics_covered": llm_score.get("subtopics_covered", []) if llm_score else [],
        "summary": llm_score.get("summary", "") if llm_score else "",
        "flag": flag,
    }


def rank_candidates(candidates: list[dict], llm_results: dict[str, dict]) -> list[dict]:
    """Enriches candidates with SerpApi detail-fetches, computes final_score
    per instructions.md's weighted formulas, and returns them sorted desc."""
    enriched = []
    for c in candidates:
        cid = c["video_id"] if c["type"] == "video" else c["playlist_id"]
        e = _enrich_video(c) if c["type"] == "video" else _enrich_playlist(c)
        e["_id"] = cid
        enriched.append(e)

    video_views = [e["extracted_views"] for e in enriched if e["type"] == "video"]
    playlist_views = [e["avg_views"] for e in enriched if e["type"] == "playlist"]
    max_views = max(video_views + playlist_views, default=1)

    scored = []
    for e in enriched:
        llm_score = llm_results.get(e["_id"])
        result = (
            _score_video(e, max_views, llm_score)
            if e["type"] == "video"
            else _score_playlist(e, max_views, llm_score)
        )
        scored.append(result)

    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored
