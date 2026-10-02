import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


SERPAPI_API_KEY = os.environ.get("SERPAPI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

CACHE_TTL_DAYS = _int_env("CACHE_TTL_DAYS", 30)
MAX_CANDIDATES = _int_env("MAX_CANDIDATES", 15)
MAX_TRANSCRIPT_TOKENS = _int_env("MAX_TRANSCRIPT_TOKENS", 4000)

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "chrome-extension://YOUR_EXT_ID")

# LLM model used for content scoring, topic decomposition, and path assembly.
# Served via Gemini's OpenAI-compatible endpoint. instructions.md originally
# specified claude-sonnet-4-6 (Anthropic); switched to Groq, then to Gemini
# after Groq's free-tier 8000 TPM cap made the spec's batch size unusable —
# see README for the full provider history and rationale.
# gemini-2.5-flash (docs' recommendation at swap time) 404s live: "no longer
# available to new users... use models/gemini-3.6-flash" — using the model
# the live API itself named over the static docs.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

SERPAPI_BASE_URL = "https://serpapi.com/search"

# Metadata pre-filter floor. Deviates from instructions.md per explicit user
# direction: no max-duration ceiling (a longer video can cover more ground —
# see scorer/formulas.duration_score) and no age cutoff (an older video isn't
# excluded, just weighted lower via recency_score). Only a duration floor
# remains, to exclude shorts/clips too brief to be a real tutorial.
MIN_VIDEO_DURATION_SEC = 5 * 60

# Learning Path mode (instructions.md's Learning Path Feature)
LEARNING_PATH_CANDIDATES_PER_SUBTOPIC = 2  # top N metadata-prefiltered candidates per subtopic search

# Per-candidate/per-subtopic SerpApi fetches (transcript, video_details,
# subtopic search) were all sequential loops - a full 15-candidate Best Pick
# run confirmed live to take 90+ seconds this way. These are independent I/O
# calls, so a thread pool gives real concurrency despite the GIL (released
# during network waits). Kept modest rather than maximal to avoid tripping
# SerpApi's own (undocumented) concurrent-request limits.
FETCH_CONCURRENCY = _int_env("FETCH_CONCURRENCY", 5)

# Optional relevance pre-filter (Jev, TypeSafe AI's "System One" decision
# model) between the metadata pre-filter and transcript fetching. Evaluates
# each candidate's free title/description/channel metadata against the
# search topic and keeps only the top N by relevance *before* any SerpApi
# transcript/video_details calls happen — unlike running it alongside the
# content scorer, this actually reduces SerpApi spend, not just LLM spend.
# Optional: unset JEV_API_KEY disables the gate entirely (candidates pass
# through unfiltered), so this isn't a hard dependency for the app to run.
JEV_API_KEY = os.environ.get("JEV_API_KEY", "")
# Routed through OpenRouter (the key in hand is an OpenRouter key, not a
# direct TypeSafe one) — different endpoint/payload shape than TypeSafe's
# own API. Confirmed live via docs cross-reference 2026-10-01.
JEV_BASE_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.13")
RELEVANCE_GATE_KEEP_N = _int_env("RELEVANCE_GATE_KEEP_N", 8)

def require_api_keys() -> None:
    missing = []
    if not SERPAPI_API_KEY:
        missing.append("SERPAPI_API_KEY")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
