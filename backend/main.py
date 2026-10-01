from typing import Literal, Optional

import openai
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from cache.db import get_cached_path, path_cache_key, set_cached_path
from fetcher._client import SerpApiError, SerpApiQuotaExceededError
from fetcher.youtube_search import search_youtube
from learning_path.assembler import assemble_path
from learning_path.decomposer import decompose_topic
from learning_path.path_ranker import generate_rationale
from learning_path.subtopic_search import search_all_subtopics
from ranker.rank import rank_candidates
from scorer.llm_scorer import score_candidates
from scorer.metadata_filter import prefilter_candidates
from scorer.relevance_gate import filter_by_relevance
from skill_mix.decomposer import decompose_skill_mix

app = FastAPI(title="YouTube Tutorial Finder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in config.ALLOWED_ORIGINS.split(",") if o.strip()],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

RUNNERS_UP_COUNT = 4


class SearchRequest(BaseModel):
    query: str
    mode: Literal["best_pick", "learning_path", "skill_mix"]
    level: Optional[Literal["all", "beginner", "intermediate", "advanced"]] = "all"


@app.get("/health")
def health():
    return {"status": "ok"}


def _candidate_id(c: dict) -> str:
    return c["video_id"]


def _why_best(pick: dict, ranked: list[dict]) -> str:
    n_subtopics = len(pick.get("subtopics_covered") or [])
    parts = []
    if pick.get("flag") != "metadata_only":
        parts.append(f"Highest content score in the candidate set ({pick['score']}/10).")
    else:
        parts.append(f"Highest-ranked candidate by metadata ({pick['score']}/10) — no transcript was available to score content quality.")
    if n_subtopics:
        parts.append(f"Covers {n_subtopics} relevant concept(s): {', '.join(pick['subtopics_covered'][:5])}.")
    if len(ranked) > 1:
        gap = pick["score"] - ranked[1]["score"]
        if gap > 0:
            parts.append(f"Leads the next-best result by {round(gap, 1)} points.")
    return " ".join(parts)


def _format_result(c: dict) -> dict:
    return {
        "type": c["type"],
        "title": c.get("title", ""),
        "channel": c.get("channel_name", ""),
        "url": c.get("url", ""),
        "score": c["score"],
        "level": c.get("level"),
        "summary": c.get("summary", ""),
        "duration_mins": round((c.get("duration_sec") or 0) / 60, 1),
    }


def run_best_pick(query: str, level: str) -> dict:
    search_results = search_youtube(query)
    prefiltered = prefilter_candidates(search_results["videos"])
    if not prefiltered:
        return {"mode": "best_pick", "query": query, "level": level, "recommendation": None, "runners_up": []}

    # Jev relevance gate (optional, no-op if JEV_API_KEY unset): narrows the
    # pool using free metadata before any transcript/video_details SerpApi
    # calls happen, so this actually cuts SerpApi spend, not just LLM spend.
    prefiltered = filter_by_relevance(query, prefiltered)

    llm_results = score_candidates(query, prefiltered)
    ranked = rank_candidates(prefiltered, llm_results)

    if level != "all":
        level_filtered = [r for r in ranked if (r.get("level") or "").lower() == level]
        ranked = level_filtered or ranked  # fall back to unfiltered rather than an empty result

    if not ranked:
        return {"mode": "best_pick", "query": query, "level": level, "recommendation": None, "runners_up": []}

    pick = ranked[0]
    runners_up = ranked[1:1 + RUNNERS_UP_COUNT]

    recommendation = _format_result(pick)
    recommendation["why_best"] = _why_best(pick, ranked)

    return {
        "mode": "best_pick",
        "recommendation": recommendation,
        "runners_up": [_format_result(r) for r in runners_up],
    }


def _format_path_step(step_num: int, step: dict, why: str) -> dict:
    c = step["candidate"]
    return {
        "step": step_num,
        "subtopic": ", ".join(step["subtopics"]),
        "type": c["type"],
        "title": c.get("title", ""),
        "channel": c.get("channel_name", ""),
        "url": c.get("url", ""),
        "why": why,
        "duration_mins": round((c.get("duration_sec") or 0) / 60, 1),
    }


def _run_path_based_mode(topic: str, level: str, mode: str, decomp: dict) -> dict:
    """Shared body for learning_path and skill_mix — identical mechanics
    (decompose -> per-subtopic search -> relevance gate -> score -> assemble
    -> rationale), differing only in how subtopics were decomposed."""
    cache_key = path_cache_key(topic, level, mode=mode)
    cached = get_cached_path(cache_key)
    if cached is not None:
        return cached

    subtopics = decomp["subtopics"]
    if not subtopics:
        result = {"mode": mode, "topic": topic, "estimated_total_hrs": 0, "level": decomp["level"], "path": [], "gaps": []}
        if "domains" in decomp:
            result["domains"] = decomp["domains"]
        set_cached_path(cache_key, result)
        return result

    candidates_by_id, ids_by_subtopic = search_all_subtopics(topic, subtopics)
    all_candidates = list(candidates_by_id.values())

    # Relevance gate (optional, no-op if JEV_API_KEY unset) — see run_best_pick's comment.
    all_candidates = filter_by_relevance(topic, all_candidates)

    llm_results = score_candidates(topic, all_candidates)
    ranked = rank_candidates(all_candidates, llm_results)

    chosen_steps, gaps = assemble_path(subtopics, ranked, ids_by_subtopic)
    why_list = generate_rationale(topic, chosen_steps)

    path = [
        _format_path_step(i, step, why_list[i - 1] if i - 1 < len(why_list) else "")
        for i, step in enumerate(chosen_steps, start=1)
    ]
    estimated_total_hrs = round(sum(s["duration_mins"] or 0 for s in path) / 60, 1)

    result = {
        "mode": mode,
        "topic": topic,
        "estimated_total_hrs": estimated_total_hrs,
        "level": decomp["level"],
        "path": path,
        "gaps": gaps,
    }
    if "domains" in decomp:
        result["domains"] = decomp["domains"]
    set_cached_path(cache_key, result)
    return result


def run_learning_path(topic: str, level: str) -> dict:
    decomp = decompose_topic(topic, level)
    return _run_path_based_mode(topic, level, "learning_path", decomp)


def run_skill_mix(topic: str, level: str) -> dict:
    """Like Learning Path, but for topics that genuinely span multiple
    distinct skill domains (e.g. "a good LinkedIn graphic post" needs both
    LinkedIn content strategy and graphic design)."""
    decomp = decompose_skill_mix(topic, level)
    return _run_path_based_mode(topic, level, "skill_mix", decomp)


@app.post("/search")
def search(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    try:
        if req.mode == "best_pick":
            return run_best_pick(req.query, req.level or "all")
        if req.mode == "skill_mix":
            return run_skill_mix(req.query, req.level or "all")
        return run_learning_path(req.query, req.level or "all")
    except SerpApiQuotaExceededError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except SerpApiError as e:
        raise HTTPException(status_code=502, detail=f"SerpApi error: {e}") from e
    except openai.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"LLM provider error: {e}") from e
