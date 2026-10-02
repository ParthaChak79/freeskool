"""Weighted final scoring — instructions.md's Video Score formula as a base,
sourced from SerpApi fields via Phase 2's fetchers. Candidates without an
LLM score (no_transcript flag from Phase 4) fall back to a metadata-only
score using the non-LLM components, renormalized to sum to 1 —
instructions.md doesn't specify this case, but Known Limitations says such
candidates should get "a metadata-only score with a flag" rather than being
dropped, so ranking has to define what that score is.

Videos only — playlists are excluded from all modes, see
fetcher/youtube_search.py's module docstring.

Weights deviate from instructions.md's original formula per explicit user
direction: duration is now a positive signal (a longer video can cover more
ground, see scorer/formulas.duration_score) rather than only a filter
threshold, funded by shrinking recency's weight (an older video is no longer
excluded either — see scorer/metadata_filter.py — so it matters less overall
that it's rewarded less here too).
"""
from concurrent.futures import ThreadPoolExecutor

import config
from fetcher.video_details import get_video_details
from scorer.formulas import (
    channel_authority_score,
    duration_score,
    normalized_view_count,
    parse_date_to_age_years,
    recency_score,
)

VIDEO_WEIGHTS = {
    "llm": 0.45, "views": 0.15, "like_ratio": 0.15,
    "duration": 0.10, "recency": 0.05, "channel_authority": 0.10,
}


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


def _score_video(candidate: dict, max_views: int, max_duration: int, llm_score: dict | None) -> dict:
    like_ratio = 0.0
    if candidate["extracted_views"]:
        like_ratio = min(candidate["extracted_likes"] / candidate["extracted_views"], 1.0)

    components = {
        "views": normalized_view_count(candidate["extracted_views"], max_views),
        "like_ratio": like_ratio,
        "duration": duration_score(candidate.get("duration_sec"), max_duration),
        "recency": recency_score(candidate["age_years"]),
        "channel_authority": channel_authority_score(candidate["extracted_subscribers"]),
    }
    return _combine(candidate, VIDEO_WEIGHTS, components, llm_score)


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
    per instructions.md's weighted formula, and returns them sorted desc."""
    def _enrich_one(c: dict) -> dict:
        e = _enrich_video(c)
        e["_id"] = c["video_id"]
        return e

    # Each of these does its own get_video_details() SerpApi call — same
    # sequential-loop-of-independent-I/O problem as llm_scorer.py's transcript
    # fetches, same fix.
    with ThreadPoolExecutor(max_workers=config.FETCH_CONCURRENCY) as executor:
        enriched = list(executor.map(_enrich_one, candidates))

    max_views = max((e["extracted_views"] for e in enriched), default=1)
    max_duration = max((e.get("duration_sec") or 0 for e in enriched), default=1)

    scored = []
    for e in enriched:
        llm_score = llm_results.get(e["_id"])
        scored.append(_score_video(e, max_views, max_duration, llm_score))

    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored
