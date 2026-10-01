"""Step 2 — Per-Subtopic Search (instructions.md's Learning Path Feature).
For each subtopic, run a targeted YouTube search and metadata-prefilter down
to a small candidate set, reusing the same fetcher/scorer pipeline as Best
Pick. Each candidate is tagged with the subtopic(s) it was found under so the
assembler (Step 3) can dedup a single video/playlist across subtopics."""
from concurrent.futures import ThreadPoolExecutor

import config
from fetcher.youtube_search import search_youtube
from scorer.metadata_filter import prefilter_candidates


def _candidate_id(c: dict) -> str:
    return c["video_id"] if c["type"] == "video" else c["playlist_id"]


def _build_search_query(topic: str, subtopic: str) -> str:
    if ": " in subtopic:
        # Domain-prefixed subtopic (skill_mix, e.g. "Graphic Design:
        # choosing a template that matches your brand") — the domain prefix
        # is for display/dedup, not a search term. Concatenating the full
        # (often long, full-sentence) original topic with the whole prefixed
        # string produces a diluted, unfocused YouTube query; search the
        # specific subtopic text alone instead, confirmed live to return
        # weak candidates and empty paths before this fix.
        _, specific = subtopic.split(": ", 1)
        return f"{specific} tutorial"
    return f"{topic} {subtopic} tutorial"


def _search_one_subtopic(topic: str, subtopic: str, video_only: bool) -> list[dict]:
    query = _build_search_query(topic, subtopic)
    results = search_youtube(query)
    return prefilter_candidates(
        results["videos"], results["playlists"],
        top_n=config.LEARNING_PATH_CANDIDATES_PER_SUBTOPIC,
        video_only=video_only,
    )


def search_all_subtopics(topic: str, subtopics: list[str], video_only: bool = False) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Returns (candidates_by_id, subtopic -> ordered list of candidate ids).
    video_only excludes playlists — see metadata_filter.prefilter_candidates."""
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
            executor.map(lambda st: _search_one_subtopic(topic, st, video_only), subtopics),
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
