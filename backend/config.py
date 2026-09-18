import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


SERPAPI_API_KEY = os.environ.get("SERPAPI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

CACHE_TTL_DAYS = _int_env("CACHE_TTL_DAYS", 30)
MAX_CANDIDATES = _int_env("MAX_CANDIDATES", 15)
MAX_TRANSCRIPT_TOKENS = _int_env("MAX_TRANSCRIPT_TOKENS", 4000)
PLAYLIST_TRANSCRIPT_VIDEOS = _int_env("PLAYLIST_TRANSCRIPT_VIDEOS", 3)

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "chrome-extension://YOUR_EXT_ID")

# LLM model used for content scoring, topic decomposition, and path assembly.
# Served via Groq's OpenAI-compatible API (https://api.groq.com/openai/v1).
# instructions.md originally specified claude-sonnet-4-6 (Anthropic); provider
# switched to Groq for speed/cost — see README for rationale.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

SERPAPI_BASE_URL = "https://serpapi.com/search"

# Metadata pre-filter thresholds (instructions.md)
MIN_VIDEO_DURATION_SEC = 5 * 60
MAX_VIDEO_DURATION_SEC = 3 * 60 * 60
MIN_PLAYLIST_SIZE = 2
MAX_PLAYLIST_SIZE = 100
RECENCY_YEARS_DEFAULT = 3

# Confirmed live 2026-09-18: SerpApi's youtube engine only exposes a 2-video
# preview per playlist (playlist_results[].videos), never the full item list,
# and there is no separate playlist-expansion engine. instructions.md's "first
# 3 playlist episodes" is therefore reduced to 2 — the max SerpApi provides.
MAX_PLAYLIST_PREVIEW_VIDEOS = 2

# instructions.md's playlist score formula references "completeness_score =
# video_count vs expected for topic" without defining "expected." No per-topic
# expected-length signal exists elsewhere in the spec (the Learning Path
# decomposer's subtopic count isn't available during Best Pick's flat ranking),
# so this is a fixed reference length for a "complete" course playlist.
EXPECTED_PLAYLIST_SIZE = 15

# Learning Path mode (instructions.md's Learning Path Feature)
LEARNING_PATH_CANDIDATES_PER_SUBTOPIC = 2  # top N metadata-prefiltered candidates per subtopic search
GAP_SCORE_THRESHOLD = 6  # score < 6 -> flag subtopic as a gap rather than pad with a weak result

def require_api_keys() -> None:
    missing = []
    if not SERPAPI_API_KEY:
        missing.append("SERPAPI_API_KEY")
    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
