# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Chrome extension + FastAPI backend that answers "what's the single best way to learn X on YouTube right now." Three modes:
- **Best Pick** — single best video for a query.
- **Learning Path** — an ordered, non-overlapping sequence of videos covering a topic end to end (topic decomposed into subtopics, one best video picked per subtopic).
- **Skill Mix** — like Learning Path, but for topics that genuinely span multiple distinct skill domains (e.g. "a good LinkedIn graphic post" needs both LinkedIn content strategy and graphic design). Auto-detects whether a topic needs splitting into domains.

All three modes recommend **videos only** — playlists were removed entirely (see "Deviations from instructions.md" below).

The original design spec is [instructions.md](instructions.md) (targets YouTube Data API v3 + Anthropic). The actual build diverges from it in several ways documented in [README.md](README.md) — read that file for the full rationale behind each deviation before assuming instructions.md is current.

## Commands

### Backend
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload          # runs on :8000, auto-reloads on file changes
```

Test a single request manually (costs real SerpApi credits if run live — see Cost sensitivity below):
```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "learn python", "mode": "best_pick", "level": "all"}'
```
`mode` is one of `best_pick`, `learning_path`, `skill_mix`. `level` is one of `all`, `beginner`, `intermediate`, `advanced`.

There is no committed test suite — verification has been done via ad hoc mocked scripts (patching `fetcher.youtube_search.search_youtube`, `fetcher.video_details.get_video_details`, `scorer.llm_scorer.score_candidates`, and the `call_json` LLM calls) run from the backend directory with `backend` on `sys.path`. Prefer this mocked approach over live calls — see below.

### Extension
1. `chrome://extensions` → enable Developer Mode → "Load Unpacked" → select `extension/`.
2. Click the extension icon → Settings → set Backend URL (defaults to `http://localhost:8000`).
3. Search anything on `youtube.com/results` — the sidebar injects via content script.

No build step; it's plain JS/HTML/CSS (Manifest V3).

## Cost sensitivity — read before testing live

SerpApi's free tier is 250 searches/month, and **one user-facing search costs many SerpApi calls**: 1 search call + 2 calls per surviving candidate (transcript + video_details). Best Pick alone can cost ~17 calls; Learning Path/Skill Mix cost more since they do one search per subtopic before the per-candidate fetches. Credits have been exhausted twice already during development.

Before spending real SerpApi/Gemini credits on a live test, prefer a mocked test (patch the fetcher/scorer functions as in the smoke tests above) unless the user explicitly asks for a live run. Mitigations already in place: 30-day SQLite caching (keyed by `video_id`, see below), an optional Jev relevance gate that narrows the candidate pool before transcript fetches, and playlists removed entirely (they used to cost 2x a video candidate).

## Architecture

### Backend pipeline (`backend/main.py`)

Both `run_best_pick` and the shared `_run_path_based_mode` (used by both Learning Path and Skill Mix) follow the same core pipeline:

1. **Search** (`fetcher/youtube_search.py`) — wraps SerpApi `engine=youtube`. Returns only `video_results`; `playlist_results` is ignored entirely.
2. **Metadata pre-filter** (`scorer/metadata_filter.py`) — cheap duration/recency filtering + a free-metadata score, keeps top `MAX_CANDIDATES` (or `LEARNING_PATH_CANDIDATES_PER_SUBTOPIC` per subtopic). No SerpApi cost — works off fields already in the search response.
3. **Relevance gate** (`scorer/relevance_gate.py`, optional) — Jev (TypeSafe AI's "System One" decision model, via OpenRouter) scores each candidate's free metadata (title/description/channel) for topic relevance and keeps the top `RELEVANCE_GATE_KEEP_N`. No-op if `JEV_API_KEY` is unset. This is the one layer that reduces SerpApi spend (not just LLM spend), since it runs *before* transcript/video_details calls.
4. **Transcript fetch + LLM scoring** (`fetcher/transcript.py`, `scorer/llm_scorer.py`) — fetches transcripts (SerpApi `engine=youtube_video_transcript`), batches them (5 per call) to Gemini for a 0-10 content-quality score, level, topic coverage, and summary. Candidates with no fetchable transcript get a metadata-only fallback score (`flag: "no_transcript"`), not dropped. Scores are cached by `video_id` alone (not `(video_id, topic)`) per instructions.md's literal wording — a real cross-topic accuracy/cost tradeoff.
5. **Ranking** (`ranker/rank.py`) — enriches survivors with `video_details` (views/likes/subscribers via SerpApi `engine=youtube_video`) and computes a weighted final score (`VIDEO_WEIGHTS`: llm 0.50, views 0.15, like_ratio 0.15, recency 0.10, channel_authority 0.10). Formulas shared with the pre-filter live in `scorer/formulas.py`.
6. **Mode-specific assembly**:
   - Best Pick: top-ranked candidate + up to 4 runners-up, with a deterministic (non-LLM) `why_best` explanation.
   - Learning Path / Skill Mix: `learning_path/assembler.py` dedups a single video across subtopics and flags subtopics with no result scoring above `GAP_SCORE_THRESHOLD` as gaps rather than padding with a weak pick; `learning_path/path_ranker.py` generates a real LLM rationale per step.

Topic decomposition differs by mode: `learning_path/decomposer.py` (ordered subtopics for a single skill) vs `skill_mix/decomposer.py` (detects whether a topic spans multiple distinct skill *domains* — deliberately biased toward NOT splitting single-coherent-skill topics; see the prompt's calibration examples). Both funnel into the same `_run_path_based_mode` in `main.py`.

All per-candidate and per-subtopic SerpApi/LLM calls are parallelized with `ThreadPoolExecutor(max_workers=config.FETCH_CONCURRENCY)` — these are I/O-bound and were previously sequential loops that made a single search take 90+ seconds.

Full-result caching: `cache/db.py` SQLite store, 30-day TTL, used for transcripts, LLM scores, video_details, and whole assembled paths (`path_cache_key` includes `mode` so Learning Path and Skill Mix don't collide on the same topic+level).

### LLM provider

Gemini, via its OpenAI-compatible endpoint (`backend/llm_client.py`'s `call_json`), not Anthropic as instructions.md originally specified (went Anthropic → Groq → Gemini; see README for why each swap happened). `reasoning_effort="minimal"` is required on every call — Gemini 3's hidden "thinking" tokens otherwise silently consume the `max_tokens` budget and truncate responses to empty.

### Extension (`extension/`)

Manifest V3, no build step. `content_script.js` injects a sidebar into `youtube.com/results` pages with three tabs (Best Pick / Path / Skill Mix) and talks to the backend through `background.js` (which also opens a `chrome.runtime.connect()` keep-alive port for the duration of a request, since MV3 terminates idle service workers mid-request otherwise). Client has a 120s timeout and a 5s minimum interval between searches (`MIN_FETCH_INTERVAL_MS`) to guard against accidental repeat-search credit burn. No API keys ever live in the extension — all SerpApi/Gemini/Jev calls are server-side only.

### Key deviations from instructions.md (full detail in README.md)

- SerpApi only, not YouTube Data API v3 + a transcript-scraping library.
- Playlists removed entirely from all three modes (not just Best Pick) — SerpApi only exposes a 2-episode preview per playlist with no expansion engine, making playlist scoring an unreliable approximation and 2x the SerpApi cost of a video candidate.
- LLM provider is Gemini, not Anthropic.
- Skill Mix is a third mode not in the original spec.
- Jev relevance pre-filter is an added, optional layer not in the original spec.
