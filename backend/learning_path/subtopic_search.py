"""Step 2 — Per-Subtopic Search (instructions.md's Learning Path Feature).
For each subtopic, run a targeted YouTube search and metadata-prefilter down
to a small candidate set, reusing the same fetcher/scorer pipeline as Best
Pick. Each candidate is tagged with the subtopic(s) it was found under so the
assembler (Step 3) can dedup a single video/playlist across subtopics."""
import config
from fetcher.youtube_search import search_youtube
from scorer.metadata_filter import prefilter_candidates


def _candidate_id(c: dict) -> str:
    return c["video_id"] if c["type"] == "video" else c["playlist_id"]


def search_all_subtopics(topic: str, subtopics: list[str]) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Returns (candidates_by_id, subtopic -> ordered list of candidate ids)."""
    candidates_by_id: dict[str, dict] = {}
    ids_by_subtopic: dict[str, list[str]] = {}

    for subtopic in subtopics:
        query = f"{topic} {subtopic} tutorial"
        results = search_youtube(query)
        top = prefilter_candidates(
            results["videos"], results["playlists"],
            top_n=config.LEARNING_PATH_CANDIDATES_PER_SUBTOPIC,
        )
        ids = []
        for c in top:
            cid = _candidate_id(c)
            ids.append(cid)
            if cid in candidates_by_id:
                candidates_by_id[cid]["_subtopics"].append(subtopic)
            else:
                candidates_by_id[cid] = {**c, "_subtopics": [subtopic]}
        ids_by_subtopic[subtopic] = ids

    return candidates_by_id, ids_by_subtopic
