# YouTube Tutorial Finder

A Chrome extension that answers "what's the single best way to learn this topic on YouTube right now," plus a Learning Path mode that assembles an ordered, non-overlapping video sequence covering a topic end to end. Full original design in [instructions.md](instructions.md); this README covers what was actually built, including where the implementation deviates from that spec and why.

## Setup

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env` (already gitignored):

```
SERPAPI_API_KEY=your_serpapi_key
GROQ_API_KEY=your_groq_key
CACHE_TTL_DAYS=30
MAX_CANDIDATES=15
MAX_TRANSCRIPT_TOKENS=4000
PLAYLIST_TRANSCRIPT_VIDEOS=3
BACKEND_URL=http://localhost:8000
ALLOWED_ORIGINS=chrome-extension://YOUR_EXT_ID
```

Get a SerpApi key at [serpapi.com](https://serpapi.com) and a Groq key at [console.groq.com](https://console.groq.com/keys).

Run it:

```bash
uvicorn main:app --reload
```

Test it:

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "learn python", "mode": "best_pick", "level": "all"}'
```

### 2. Chrome extension

1. Go to `chrome://extensions`, enable Developer Mode.
2. Click "Load Unpacked", select the `extension/` folder.
3. Click the extension icon → Settings, set "Backend URL" to wherever your backend is running (defaults to `http://localhost:8000`).
4. Search anything on youtube.com — the sidebar appears on the results page.

No API keys ever live in the extension — all SerpApi and Groq calls are server-side only, per instructions.md's Key Extension Constraints.

## Data source: SerpApi, not YouTube Data API v3

The original spec targeted YouTube Data API v3 plus the unofficial `youtube-transcript-api` scraper library. This build uses **SerpApi exclusively** — `engine=youtube` (search), `engine=youtube_video` (video detail), `engine=youtube_video_transcript` (transcripts, replacing the scraper entirely), and `engine=youtube_channel` (channel authority signals). No YouTube Data API v3 calls, no scraping.

## LLM provider: Groq, not Anthropic

instructions.md originally specified Anthropic (`claude-sonnet-4-6`, itself a stale model string). This build was later switched to **Groq** (`openai/gpt-oss-120b`, served via Groq's OpenAI-compatible API), chosen over `llama-3.3-70b-versatile` for its documented reasoning capability plus higher throughput (500 t/s), and over the smaller `gpt-oss-20b`/`llama-3.1-8b-instant` models for better judgment quality on nuanced scoring (content quality, skill-level detection, subtopic extraction). Prompt wording, batch size (5 transcripts/call), and truncation limits are unchanged from the original spec.

**Known limitation:** Groq's free/on-demand tier caps `openai/gpt-oss-120b` at 8,000 tokens/minute. A single full batch of 5 candidates at the spec's 4,000-token-per-video truncation requests ~13,000+ tokens — over the cap, and retrying doesn't help since it's a single-request ceiling, not a burst limit. Running the batching spec at full scale requires Groq's Dev Tier or higher. Bounded retry-with-backoff (`llm_client.py`) is implemented for the *different* case of several smaller calls cumulatively exceeding the budget in a short window, but does not fix the oversized-single-batch case.

## Phase 0 finding: playlist filtering

The original concern was whether isolating playlist results from `engine=youtube` search required copying YouTube's `sp` filter parameter. It doesn't — a live test call showed the `youtube` engine already returns playlists in a separate top-level `playlist_results` array (undocumented ahead of time, found by testing), distinct from `video_results`. No `sp` workaround needed.

**A real gap found in the same test, requiring a design decision:** SerpApi never exposes a playlist's full video list — `playlist_results[].videos` caps out at 2 preview episodes per playlist, and there's no separate playlist-expansion engine (verified against SerpApi's own docs). This means:
- instructions.md's "score the first 3 playlist episodes" is reduced to 2 (`config.MAX_PLAYLIST_PREVIEW_VIDEOS`) — the max SerpApi provides.
- Playlist-level aggregate metadata (avg views, recency, total duration) is **approximated** from those 2 preview episodes (avg episode length × `video_count` for duration; avg of the 2 episodes' views/dates for the ranking formula's `normalized_view_count`/`recency_score`). This can be noticeably inaccurate for very large playlists (85+ videos) if the 2 sampled episodes aren't representative — seen in testing, where a 5-step React learning path came out to an estimated 45.3 hours, likely overestimated.
- `playlist_expander.py`, listed in instructions.md's Project Structure, doesn't exist in this build — there's nothing for it to wrap.

## Other deviations from instructions.md, all called out in code comments

- **`llm_content_score` scale reconciliation**: the video/playlist score formulas' weights sum to 1.0, but `llm_content_score` is 0–10 while the other components are 0–1. Normalized `llm_content_score` to 0–1 before weighting, then scaled the final sum back to 0–10 for display, to match the spec's own output examples (`"score": 8.7`).
- **`completeness_score`'s "expected [video count] for topic"** was never defined in the spec. Used a fixed reference of 15 videos (`config.EXPECTED_PLAYLIST_SIZE`).
- **Metadata-only fallback scoring**: candidates with no fetchable transcript (non-English, disabled captions) get a score computed from a renormalized non-LLM-only formula and a `flag: "metadata_only"`, rather than being silently dropped — the formulas section didn't define this case, but Known Limitations calls for it.
- **`why_best` and per-step `why` rationale for Learning Path steps** are the only LLM-free vs. LLM-driven design choice worth noting: `why_best` (Best Pick) is generated by deterministic templating (no extra LLM call, to stay within the spec's stated "3 calls per query" budget), while Learning Path's per-step `why` **is** a real LLM call (Step 4 of the spec explicitly calls for LLM-generated rationale) — but factual fields (title/channel/url/duration) are filled in programmatically, not by the LLM, to avoid hallucinated URLs.
- **Score caching is keyed by `video_id` alone**, per the spec's literal wording, not `(video_id, topic)`. Since content-quality scoring is topic-dependent, a video reused across two different topic searches will incorrectly reuse its first score — a real cost/accuracy tradeoff, not an oversight.
- **Learning Path subtopic count** is bounded to 6–10 in the decomposition prompt (an initial unconstrained run produced 17 subtopics for "Learn React," well beyond the spec's own ~8-subtopic example and its stated per-query cost budget).

## Project structure

```
youtube-tutorial-finder/
├── instructions.md
├── extension/              # Chrome extension (MV3)
│   ├── manifest.json
│   ├── content_script.js
│   ├── background.js
│   ├── popup.html / popup.js
│   ├── styles/
│   └── icons/
└── backend/                 # FastAPI backend
    ├── main.py               # /search endpoint, Best Pick + Learning Path orchestration
    ├── config.py
    ├── llm_client.py          # shared Groq call/retry/JSON-parse logic
    ├── fetcher/                # SerpApi wrappers
    ├── scorer/                 # metadata pre-filter, batched LLM scoring, shared formulas
    ├── ranker/                 # weighted final scoring
    ├── learning_path/          # decomposer, subtopic search, assembler, path rationale
    └── cache/                  # SQLite cache (transcripts, scores, paths)
```

## Testing notes

Backend phases were tested against live SerpApi/Groq calls throughout development (see conversation history for specifics per phase). The Chrome extension's rendering logic was verified with a jsdom smoke test against realistic backend response shapes, but **has not been visually tested in a real Chrome browser against live youtube.com** — load it unpacked and try a real search before trusting the UI is polished, per the "Load Unpacked" steps above.
