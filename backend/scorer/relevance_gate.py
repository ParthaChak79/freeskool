"""Optional relevance pre-filter using Jev (TypeSafe AI's "System One"
decision model) — sits between the metadata pre-filter and transcript
fetching. Jev isn't a text-generation LLM; it takes a text "state" and
answers typed questions about it (here, a "noul" question: a 0-1 probability
that the answer is yes). Evaluated against each candidate's free metadata
(title/description/channel — already in hand from the search step, no
SerpApi cost), so this narrows the candidate pool *before* any transcript or
video_details SerpApi calls happen, unlike running an LLM check alongside
the content scorer (which only happens after that spend is already made).

Routed through OpenRouter (the key in hand is an OpenRouter key, not a
direct TypeSafe one) — different endpoint/payload than TypeSafe's own API.
Verified live via docs cross-reference 2026-10-01 (not hardcoded from
memory — Jev launched 2026-09-15, well past any training cutoff):
POST https://openrouter.ai/api/alpha/decisions
{"model": "typesafe/jev-1.13", "state": "...",
 "questions": {"<key>": {"type": "noul", "instructions": "..."}}}
-> {"answers": {"<key>": {"type": "noul", "noul": <float 0-1>}}, ...}
"""
from concurrent.futures import ThreadPoolExecutor

import requests

import config

QUESTION_KEY = "is_relevant"
NEUTRAL_RELEVANCE = 0.5  # fallback when a single candidate's Jev call fails
                          # — fail open (keep, don't penalize) rather than
                          # silently dropping a candidate over a transient error


def _build_state(topic: str, candidate: dict) -> str:
    return (
        f"Topic being searched: {topic}\n"
        f"Title: {candidate.get('title', '')}\n"
        f"Description: {candidate.get('description', '')}\n"
        f"Channel: {candidate.get('channel_name', '')}"
    )


def _call_jev(topic: str, candidate: dict) -> float:
    payload = {
        "model": config.JEV_MODEL,
        "state": _build_state(topic, candidate),
        "questions": {
            QUESTION_KEY: {
                "type": "noul",
                "instructions": f'Is this YouTube content relevant to and directly about: "{topic}"?',
            }
        },
    }
    resp = requests.post(
        config.JEV_BASE_URL,
        json=payload,
        headers={"Authorization": f"Bearer {config.JEV_API_KEY}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["answers"][QUESTION_KEY]["noul"]


def _score_one(topic: str, candidate: dict) -> tuple[dict, float]:
    try:
        return candidate, _call_jev(topic, candidate)
    except Exception:
        return candidate, NEUTRAL_RELEVANCE


def filter_by_relevance(topic: str, candidates: list[dict], keep_n: int = config.RELEVANCE_GATE_KEEP_N) -> list[dict]:
    """Returns the top keep_n candidates by Jev relevance score, or all
    candidates unchanged if the gate isn't configured (no JEV_API_KEY) or
    there's nothing to filter down."""
    if not config.JEV_API_KEY or len(candidates) <= keep_n:
        return candidates

    with ThreadPoolExecutor(max_workers=config.FETCH_CONCURRENCY) as executor:
        scored = list(executor.map(lambda c: _score_one(topic, c), candidates))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [c for c, _relevance in scored[:keep_n]]
