"""Step 2 — Per-Subtopic Search (instructions.md's Learning Path Feature).
For each subtopic, run a targeted YouTube search and metadata-prefilter down
to a small candidate set, reusing the same fetcher/scorer pipeline as Best
Pick. Each candidate is tagged with the subtopic(s) it was found under so the
assembler (Step 3) can dedup a single video across subtopics. Videos only —
see fetcher/youtube_search.py's module docstring."""
from concurrent.futures import ThreadPoolExecutor

import config
from fetcher.youtube_search import search_youtube
from scorer.metadata_filter import prefilter_candidates


def _candidate_id(c: dict) -> str:
    return c["video_id"]


def _build_search_query(subtopic: str) -> str:
    # The decomposer prompt requires every subtopic to already be a
    # self-contained YouTube search topic (including the subject, e.g.
    # "Python variables" not "variables"), so it's searched alone — no need
    # to prepend the original topic. Prepending it anyway (the original
    # design) diluted every query once the topic itself was a long sentence
    # (e.g. "how to create a good graphic post on linkedin"): every subtopic
    # search came back empty and the whole path turned into gaps, confirmed
    # live before this fix. Domain-prefixed subtopics (skill_mix, e.g.
    # "Graphic Design: choosing a template") strip the prefix first — it's
    # for display/dedup only, not a search term.
    if ": " in subtopic:
        _, specific = subtopic.split(": ", 1)
        return f"{specific} tutorial"
    return f"{subtopic} tutorial"


def _search_one_subtopic(subtopic: str) -> list[dict]:
    query = _build_search_query(subtopic)
    results = search_youtube(query)
    return prefilter_candidates(
        results["videos"],
        top_n=config.LEARNING_PATH_CANDIDATES_PER_SUBTOPIC,
    )


def search_all_subtopics(subtopics: list[str]) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Returns (candidates_by_id, subtopic -> ordered list of candidate ids)."""
    candidates_by_id: dict[str, dict] = {}
    ids_by_subtopic: dict[str, list[str]] = {}

    # Each subtopic's search is an independent SerpApi call — was a
    # sequential loop (up to 10 subtopics = 10 calls back to back before
    # any scoring even started). Threaded for the same reason as
    # llm_scorer.py/rank.py. Merge step below stays sequential, in original
    # subtopic order, so dedup/ordering behavior is unchanged.
    with ThreadPoolExecutor(max_workers=config.FETCH_CONCURRENCY) as executor:
        results_by_subtopic = dict(zip(
            subtopics,
            executor.map(_search_one_subtopic, subtopics),
        ))

    for subtopic in subtopics:
        ids = []
        for c in results_by_subtopic[subtopic]:
            cid = _candidate_id(c)
            ids.append(cid)
            if cid in candidates_by_id:
                candidates_by_id[cid]["_subtopics"].append(subtopic)
            else:
                candidates_by_id[cid] = {**c, "_subtopics": [subtopic]}
        ids_by_subtopic[subtopic] = ids

    return candidates_by_id, ids_by_subtopic
