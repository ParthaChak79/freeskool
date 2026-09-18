"""Batched LLM content scoring — instructions.md's Batch Prompt Structure,
exactly as specified (batch size 5, one JSON array per call), sourced from
Phase 2's transcript.py instead of a scraped transcript library.
"""
import config
from cache.db import get_cached_score, set_cached_score
from fetcher.transcript import get_transcript, truncate_to_tokens
from llm_client import call_json

BATCH_SIZE = 5
NO_TRANSCRIPT_FLAG = "no_transcript"


def _build_video_transcript_block(video_id: str) -> str | None:
    tr = get_transcript(video_id)
    if not tr["has_transcript"]:
        return None
    return truncate_to_tokens(tr["text"], config.MAX_TRANSCRIPT_TOKENS)


def _build_playlist_transcript_block(candidate: dict) -> str | None:
    # instructions.md: first 3 episodes, 2000 tokens each. Phase 0 confirmed
    # SerpApi exposes at most MAX_PLAYLIST_PREVIEW_VIDEOS (2) preview episodes
    # per playlist, so this uses min(configured count, what's available).
    n = min(config.PLAYLIST_TRANSCRIPT_VIDEOS, config.MAX_PLAYLIST_PREVIEW_VIDEOS)
    episodes = candidate.get("preview_videos", [])[:n]
    parts = []
    for i, ep in enumerate(episodes, start=1):
        tr = get_transcript(ep["video_id"])
        if not tr["has_transcript"]:
            continue
        truncated = truncate_to_tokens(tr["text"], 2000)
        parts.append(f"--- Episode {i}: {ep.get('title', '')} ---\n{truncated}")
    return "\n\n".join(parts) if parts else None


def _candidate_id(candidate: dict) -> str:
    return candidate["video_id"] if candidate["type"] == "video" else candidate["playlist_id"]


def _build_prompt(topic: str, batch: list[tuple[str, str]]) -> str:
    transcript_lines = "\n".join(f"[{cid}]: {text}" for cid, text in batch)
    return f"""You are evaluating YouTube tutorial transcripts for quality.
For each transcript below, return a JSON array with:
- id (as given)
- score (0-10)
- level ("beginner" | "intermediate" | "advanced")
- covers_topic (true/false)
- subtopics_covered (list of strings — specific concepts this video teaches)
- summary (max 2 sentences)

Topic being searched: "{topic}"

Transcripts:
{transcript_lines}

Return ONLY valid JSON. No preamble."""


def _score_batch(topic: str, batch: list[tuple[str, str]]) -> dict[str, dict]:
    prompt = _build_prompt(topic, batch)
    results = call_json(prompt, max_tokens=2000)
    return {str(r["id"]): r for r in results}


def score_candidates(topic: str, candidates: list[dict]) -> dict[str, dict]:
    """Returns {candidate_id: score_result}. Candidates with no fetchable
    transcript get a flagged metadata-only fallback per instructions.md's
    Known Limitations ("fall back to metadata-only score with a flag").

    Scores are cached by video_id only (per instructions.md's Token
    Optimization Strategy #4), not by (video_id, topic). A cached score is
    reused even if this candidate now comes up under a different search
    topic than the one it was originally scored against — content-quality
    scoring is genuinely topic-dependent (covers_topic, subtopics_covered),
    so this trades some cross-topic accuracy for the cost savings the spec
    calls for. Worth knowing if scores look stale for a reused video.
    """
    scorable: list[tuple[str, str]] = []
    results: dict[str, dict] = {}

    for c in candidates:
        cid = _candidate_id(c)
        cached = get_cached_score(cid)
        if cached is not None:
            results[cid] = cached
            continue

        block = (
            _build_video_transcript_block(cid)
            if c["type"] == "video"
            else _build_playlist_transcript_block(c)
        )
        if block is None:
            results[cid] = {
                "id": cid, "score": None, "level": None, "covers_topic": None,
                "subtopics_covered": [], "summary": "", "flag": NO_TRANSCRIPT_FLAG,
            }
        else:
            scorable.append((cid, block))

    for i in range(0, len(scorable), BATCH_SIZE):
        batch = scorable[i:i + BATCH_SIZE]
        batch_results = _score_batch(topic, batch)
        for cid, r in batch_results.items():
            set_cached_score(cid, r)
        results.update(batch_results)

    return results
