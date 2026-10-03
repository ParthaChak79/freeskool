# Freeskool

A Chrome extension that answers "what's the single best way to learn this topic on YouTube right now," plus a Learning Path mode that assembles an ordered, non-overlapping video sequence covering a topic end to end. Full original design in [instructions.md](instructions.md); this README covers what was actually built, including where the implementation deviates from that spec and why.

## Setup

> ⚠️ **Cost note before you start**: every search against the running backend spends real SerpApi (and Gemini) credits — a single Best Pick search costs ~17+ SerpApi calls (1 search + 2 per surviving candidate), and Learning Path/Skill Mix cost more. SerpApi's free tier is 250 searches/month, which burns fast if you test all three modes repeatedly. Budget for that before testing.

### 1. Clone and set up the backend

```bash
git clone https://github.com/ParthaChak79/freeskool.git
cd freeskool/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get API keys

You need your own — none are committed to this repo:
- **SerpApi key** — [serpapi.com](https://serpapi.com) (free tier: 250 searches/month)
- **Gemini key** — [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- **Jev key** (optional) — via [OpenRouter](https://openrouter.ai), only needed if you want the relevance-gate feature active (see "Relevance pre-filter" below); leave it unset and that feature is simply disabled

### 3. Create `backend/.env`

```
SERPAPI_API_KEY=your_serpapi_key
GEMINI_API_KEY=your_gemini_key
JEV_API_KEY=                        # optional — see "Relevance pre-filter" below
CACHE_TTL_DAYS=30
MAX_CANDIDATES=15
MAX_TRANSCRIPT_TOKENS=4000
FETCH_CONCURRENCY=5
RELEVANCE_GATE_KEEP_N=8
BACKEND_URL=http://localhost:8000
ALLOWED_ORIGINS=chrome-extension://YOUR_EXT_ID   # placeholder for now — comes from step 5
```

### 4. Run the backend

```bash
uvicorn main:app --reload
```

Sanity-check it without the extension:

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "learn python", "mode": "best_pick", "level": "all"}'
```

### 5. Load the Chrome extension

1. Go to `chrome://extensions`, enable Developer Mode.
2. Click "Load Unpacked", select the `extension/` folder.
3. Chrome assigns the extension an ID (shown on its card on that page) — copy it, paste it into `backend/.env`'s `ALLOWED_ORIGINS` as `chrome-extension://<that_id>`, and **restart** uvicorn (not just let `--reload` pick it up — `python-dotenv` only loads `.env` once at process start, so `--reload`'s file-watching doesn't apply to it; a stale extension ID here is the most common setup snag, surfacing as a CORS "Failed to fetch" in the sidebar).
4. Click the extension icon → Settings, confirm "Backend URL" is `http://localhost:8000` (or wherever your backend is running).

No API keys ever live in the extension — all SerpApi, Gemini, and Jev calls are server-side only, per instructions.md's Key Extension Constraints.

### 6. Test it

Go to `youtube.com`, search anything from **YouTube's own search bar** (not the browser's URL bar), and the sidebar should appear on the results page with three tabs — **★ Best Pick**, **🗺 Path**, **🎯 Skill Mix**.

## Data source: SerpApi, not YouTube Data API v3

The original spec targeted YouTube Data API v3 plus the unofficial `youtube-transcript-api` scraper library. This build uses **SerpApi exclusively** — `engine=youtube` (search), `engine=youtube_video` (video detail), `engine=youtube_video_transcript` (transcripts, replacing the scraper entirely), and `engine=youtube_channel` (channel authority signals). No YouTube Data API v3 calls, no scraping.

## LLM provider: Gemini (previously Anthropic, then Groq)

instructions.md originally specified Anthropic (`claude-sonnet-4-6`, itself a stale model string). The build was switched to Groq (`openai/gpt-oss-120b`) for speed/cost, then switched again to **Gemini**, served via Gemini's OpenAI-compatible endpoint at `https://generativelanguage.googleapis.com/v1beta/openai/`, after Groq's free/on-demand tier's 8,000 tokens/minute cap made the spec's batch size (5 candidates × up to 4,000 tokens each) structurally impossible to run — a single full batch requested ~13,000+ tokens, over the cap, and retrying doesn't help since it's a single-request ceiling, not a burst limit that clears with time. `gemini-2.5-flash` (Google's own docs' recommendation at swap time, as the best price-performance option for reasoning tasks) 404s live for new accounts — the API's own error message pointed to `gemini-3.6-flash` instead, which is what's actually configured (`config.GEMINI_MODEL`). Gemini 3's models also default to hidden "thinking" tokens that count against `max_tokens` and were silently truncating responses to empty at this task's budgets — `reasoning_effort="minimal"` is passed on every call to disable that, since this is straightforward rubric-applying JSON output, not a task needing deep reasoning. Prompt wording, batch size, and truncation limits are otherwise unchanged from the original spec.

Rate-limit verification: the exact batch shape that broke Groq (5 candidates × ~4000 tokens) was replayed against Gemini with synthetic text and succeeded in ~5s — confirmed, not assumed.

## Relevance pre-filter: Jev (optional)

An optional extra layer, added after the pipeline was confirmed working: [Jev](https://openrouter.ai), TypeSafe AI's "System One" decision model, sits between the metadata pre-filter and transcript fetching (`scorer/relevance_gate.py`). Unlike a typical LLM, Jev doesn't generate text — it takes a text "state" and answers typed questions about it (here, a `noul` question: a 0–1 probability). Each pre-filtered candidate's *free* metadata (title/description/channel, already in hand from the initial search — no SerpApi cost) is scored for relevance to the search topic. Routed through OpenRouter's Jev endpoint (`https://openrouter.ai/api/alpha/decisions`, an alpha API) rather than TypeSafe's own direct API, since that's the key in hand — different endpoint and payload shape (`model` field required) than TypeSafe's own API; verified live, correctly scored an on-topic candidate at 0.98 and an off-topic one at 0.01.

**Applied differently per mode.** Best Pick runs the gate once on its whole flat candidate pool, keeping the top `RELEVANCE_GATE_KEEP_N` (default 8) by relevance. Learning Path/Skill Mix apply it **per subtopic** instead (`learning_path/subtopic_search.py`, keep_n `LEARNING_PATH_RELEVANCE_KEEP_N`, default 1) — applying it globally across all subtopics' merged candidates was tried first and confirmed live to wipe out an entire subtopic's small candidate set whenever its candidates scored lower in Jev's judgment than other subtopics', even when they were a perfectly reasonable pick on their own. Per-subtopic keep_n=1 still halves transcript/`video_details` fetches for that subtopic, but can never zero it out entirely.

This is the one piece of this pipeline that actually reduces SerpApi spend rather than just LLM spend — transcript and video-details calls are what cost SerpApi credits, and narrowing 15 candidates down to 8 before those calls happen cuts them roughly in half. Running a relevance check *after* transcripts are already fetched (e.g. alongside the Gemini content scorer) wouldn't save anything, since the SerpApi cost is already sunk by that point — that's why this sits where it does in the pipeline, not later.

Entirely optional: `filter_by_relevance()` is a no-op (returns candidates unchanged) if `JEV_API_KEY` isn't set, so the app runs the same as before with it blank. Fails open on a per-candidate basis too — if a single Jev call errors, that candidate gets a neutral score rather than being dropped or crashing the whole request.

## Third mode: Skill Mix (`mode=skill_mix`)

Added beyond instructions.md's original two modes. For topics that genuinely require combining multiple distinct skills — e.g. "a good LinkedIn graphic post" needs both LinkedIn content strategy and graphic design, fields normally taught by different creators — a single playlist is unlikely to properly cover all of them. `skill_mix/decomposer.py` identifies the distinct skill domain(s) a topic actually spans (not forcing a split for single-skill topics — confirmed live: "learn python" correctly resolves to one domain, "LinkedIn graphic post" correctly resolves to two or three) and decomposes into domain-prefixed subtopics (e.g. `"Graphic Design: choosing a template"`). From there it reuses Learning Path's entire pipeline unchanged (`main.py`'s `_run_path_based_mode`, shared by both modes) — per-subtopic search, relevance gate, scoring, dedup/gap assembly, rationale — except `prefilter_candidates(..., video_only=True)` excludes playlists throughout. Output format matches Learning Path's exactly, with an added `domains` field listing what was detected.

Not yet exposed in the Chrome extension UI (no third tab) — currently backend-only, testable via `POST /search` with `"mode": "skill_mix"`.

## Phase 0 finding: playlists removed entirely

Playlists were supported early on (instructions.md's "Best Pick: video *or* playlist"), but SerpApi never exposes a playlist's full video list — `playlist_results[].videos` caps out at 2 preview episodes per playlist, with no separate playlist-expansion engine (verified against SerpApi's own docs). Scoring a playlist meant judging it from 1-2 sampled episodes and approximating its total duration (avg episode length × `video_count`) — noticeably inaccurate for large playlists (seen in testing: a 5-step React path came out to an estimated 45.3 hours, likely overestimated). Each playlist episode also costs 2 SerpApi calls (transcript + `video_details`), so a playlist candidate cost 2x what a video candidate cost.

All three modes (Best Pick, Learning Path, Skill Mix) now recommend **videos only** — `fetcher/youtube_search.py` doesn't parse `playlist_results` at all, so the whole downstream pipeline (`metadata_filter`, `llm_scorer`, `rank.py`) only ever deals with videos. This both removes the approximation problem above and roughly halves per-candidate SerpApi spend compared to when playlists were in the mix. `playlist_expander.py`, listed in instructions.md's Project Structure, was never built — there's nothing for it to wrap.

## Other deviations from instructions.md, all called out in code comments

- **`llm_content_score` scale reconciliation**: the video score formula's weights sum to 1.0, but `llm_content_score` is 0–10 while the other components are 0–1. Normalized `llm_content_score` to 0–1 before weighting, then scaled the final sum back to 0–10 for display, to match the spec's own output examples (`"score": 8.7`).
- **Metadata-only fallback scoring**: candidates with no fetchable transcript (non-English, disabled captions) get a score computed from a renormalized non-LLM-only formula and a `flag: "metadata_only"`, rather than being silently dropped — the formulas section didn't define this case, but Known Limitations calls for it.
- **Duration filtering/weighting, per explicit user direction**: instructions.md's hard 3-hour duration ceiling is gone — only a 5-minute duration floor remains (to exclude shorts/clips). A longer video is now a *positive* signal (`scorer/formulas.duration_score`, log-scaled like views) since it can cover more ground, not a reason for exclusion. The 3-year age cutoff is kept as instructions.md specified (still a hard exclusion, not just a scoring penalty — a change to remove it was tried and then explicitly reverted). Both duration and recency carry more weight than instructions.md's original formula, per explicit user direction that a newer, longer video should score meaningfully higher, not just avoid being filtered out: final video ranking weights are now `{llm: 0.40, views: 0.10, like_ratio: 0.10, duration: 0.15, recency: 0.15, channel_authority: 0.10}` (from the original `{llm: 0.50, views: 0.15, like_ratio: 0.15, recency: 0.10, channel_authority: 0.10}`), and the metadata pre-filter's lightweight score is `views × 0.35 + duration × 0.35 + recency × 0.30` (from `views × 0.6 + recency × 0.4`).
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
    ├── llm_client.py          # shared Gemini call/retry/JSON-parse logic
    ├── fetcher/                # SerpApi wrappers
    ├── scorer/                 # metadata pre-filter, batched LLM scoring, shared formulas
    ├── ranker/                 # weighted final scoring
    ├── learning_path/          # decomposer, subtopic search, assembler, path rationale
    ├── skill_mix/               # domain-aware decomposer for mode=skill_mix (see below)
    └── cache/                  # SQLite cache (transcripts, scores, paths)
```

## Testing notes

Backend phases were tested against live SerpApi and Groq calls throughout development (see conversation history for specifics per phase); the Gemini swap has not yet been verified against a real search end-to-end. The Chrome extension's rendering logic was verified with a jsdom smoke test against realistic backend response shapes, but **has not been visually tested in a real Chrome browser against live youtube.com** — load it unpacked and try a real search before trusting the UI is polished, per the "Load Unpacked" steps above.
