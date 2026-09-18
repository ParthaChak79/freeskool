# YouTube Tutorial Finder — Project Instructions

## Project Overview

A **Chrome extension** that answers one question: *"What is the single best way to learn this topic on YouTube right now?"*

The core philosophy is **decision elimination** — the user should not have to watch multiple videos to find a good one, compare playlists, or guess at quality. The extension surfaces one clear recommendation and explains why, then optionally generates a **curated learning path**: an ordered sequence of videos from across YouTube that together give complete coverage of the topic.

Results are scored by content quality (via transcript analysis), not just metadata or watch time. Built on **Google Antigravity** (agent-first, agentic IDE). The extension is a thin UI layer; all heavy lifting runs on a hosted backend API.

### Two Core Modes
1. **Best Pick** — The single highest-quality video or playlist for the topic. One recommendation, clearly justified. No scrolling required.
2. **Learning Path** — A curated, ordered sequence of videos (from any channel) that together provide full coverage of the topic from first principles to advanced application. Think of it as a syllabus auto-generated from YouTube.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│             CHROME EXTENSION                │
│                                             │
│  content_script.js                          │
│  ├── Detects YouTube search page            │
│  ├── Extracts search query from URL         │
│  ├── Injects sidebar panel into DOM         │
│  └── Calls Backend API with query + mode    │
│                                             │
│  popup.html / popup.js                      │
│  └── Settings UI (skill level, filters)     │
└─────────────────┬───────────────────────────┘
                  │ POST /search
                  │ { query, mode, level }
                  │ mode = "best_pick" | "learning_path"
                  ▼
┌─────────────────────────────────────────────┐
│             BACKEND API (Python)            │
│                                             │
│  YouTube Data API v3                        │
│  ├── Search: type=video  (top 30)           │
│  └── Search: type=playlist (top 20)         │
│                   │                         │
│  Metadata Pre-Filter                        │
│  ├── Duration: >5 min, <3 hrs               │
│  ├── Playlist size: 2–100 videos            │
│  ├── Recency: last 3 years (default)        │
│  └── Keep top 15 by metadata score          │
│                   │                         │
│  Transcript Fetcher                         │
│  ├── Videos: first 4,000 tokens             │
│  └── Playlists: first 3 videos only         │
│                   │                         │
│  LLM Scorer (Claude claude-sonnet-4-6)      │
│  ├── Batched: 5 transcripts per call        │
│  ├── Content score (0–10)                   │
│  ├── Subtopics covered (list)               │  ← new, used by learning path
│  ├── Skill level detection                  │
│  └── 2-sentence summary                     │
│                   │                         │
│         ┌─────────┴──────────┐              │
│         ▼                    ▼              │
│   [BEST PICK mode]   [LEARNING PATH mode]   │
│   Top ranked result  LLM assembles ordered  │
│   + justification    sequence from scored   │
│                      candidates to cover    │
│                      all subtopics once     │
└─────────────────────────────────────────────┘
```

---

## Data Sources & APIs

| Source | Purpose | Cost |
|---|---|---|
| YouTube Data API v3 | Search, metadata, playlist items | Free (10k units/day) |
| `youtube-transcript-api` (Python) | Fetch transcripts | Free |
| Anthropic API (claude-sonnet-4-6) | Content scoring | ~$0.003 per 1k input tokens |

---

## Token Optimization Strategy

This is the most important cost lever. LLM calls are the only paid component.

### 1. Transcript Truncation
- **Videos**: Truncate transcript to first **4,000 tokens** (~3,000 words)
  - The intro of a tutorial reliably signals depth, clarity, and structure
  - Full transcripts rarely needed; intros are representative
- **Playlists**: Only score the **first 3 videos**, truncated to 2,000 tokens each
  - Playlist episode 1 sets the style; episodes 2–3 confirm depth

### 2. Batch Scoring in One Prompt
- Do **not** make one LLM call per video
- Instead, batch up to **5 transcripts into a single prompt**
- Ask the model to return a JSON array with scores for all 5 at once
- This reduces per-video overhead (system prompt, etc.) by ~80%

**Batch prompt structure:**
```
You are evaluating YouTube tutorial transcripts for quality.
For each transcript below, return a JSON array with:
- id (as given)
- score (0-10)
- level ("beginner" | "intermediate" | "advanced")
- covers_topic (true/false)
- subtopics_covered (list of strings — specific concepts this video teaches)
- summary (max 2 sentences)

Topic being searched: "{USER_TOPIC}"

Transcripts:
[TRANSCRIPT_1_ID]: {truncated transcript}
[TRANSCRIPT_2_ID]: {truncated transcript}
...

Return ONLY valid JSON. No preamble.
```

### 3. Pre-Filter Aggressively Before LLM
- Only send transcripts to the LLM for the **top 15 candidates** (after metadata scoring)
- Never send more than 15 transcripts per query to the LLM
- Batched into 3 groups of 5 = **3 LLM calls total per user query**

### 4. Cache Transcripts and Scores
- Cache transcript + LLM score keyed by `video_id`
- TTL: 30 days (tutorials don't change often)
- Use a simple SQLite DB or Redis
- Repeat queries for the same video cost $0

### 5. Use Compressed Transcript Format
Before sending to LLM, strip filler from transcripts:
- Remove timestamps
- Collapse repeated whitespace
- Remove filler phrases ("um", "uh", "you know", "like")
- This reduces token count by ~15–25%

### 6. Cheap First-Pass Filter with Embeddings (Optional, Advanced)
- Generate an embedding for the user's query
- Generate embeddings for each transcript (can use a free/cheap model)
- Cosine similarity filter: drop transcripts below 0.6 similarity before LLM scoring
- Only worth it at scale (>50 candidates)

## Learning Path Feature

This is a distinct mode that goes beyond ranking — it constructs a **step-by-step viewing sequence** from across YouTube that gives the user complete, non-overlapping coverage of a topic.

### How It Works

**Step 1 — Topic Decomposition**
Before fetching any videos, the LLM breaks the topic into an ordered list of subtopics:
```
Topic: "Learn React"
Subtopics (ordered):
  1. What is React and why use it
  2. JSX and component basics
  3. Props and state
  4. useEffect and lifecycle
  5. Fetching data / async patterns
  6. React Router
  7. State management (Context / Redux)
  8. Testing React apps
```
This becomes the **syllabus** the path must satisfy.

**Step 2 — Per-Subtopic Search**
For each subtopic, run a targeted YouTube search (e.g. `"React useEffect tutorial"`). Fetch and score the top candidate per subtopic using the same transcript pipeline.

**Step 3 — Deduplication & Gap Filling**
- If a single video or playlist already covers multiple subtopics, it takes precedence — don't add redundant videos
- If a subtopic has no good candidate (score < 6), flag it as a gap rather than padding with a weak result
- Prefer videos from the same channel for adjacent subtopics when quality is equal (continuity of teaching style)

**Step 4 — Path Assembly**
LLM assembles the final ordered sequence, with a one-line rationale per step explaining what it adds and why it comes here.

### Learning Path Output Format
```json
{
  "topic": "Learn React",
  "estimated_total_hrs": 9.5,
  "level": "beginner",
  "path": [
    {
      "step": 1,
      "subtopic": "What is React and why use it",
      "type": "video",
      "title": "React in 100 Seconds",
      "channel": "Fireship",
      "url": "https://youtube.com/watch?v=...",
      "duration_mins": 12,
      "why": "Fast orientation before diving deeper. Covers mental model without overwhelming detail."
    },
    {
      "step": 2,
      "subtopic": "JSX, components, props and state",
      "type": "playlist",
      "title": "React Fundamentals",
      "channel": "Traversy Media",
      "url": "https://youtube.com/playlist?list=...",
      "duration_mins": 180,
      "why": "Best-in-class coverage of core concepts. Covers steps 2–4 of the syllabus in one playlist."
    }
  ],
  "gaps": ["Testing React apps — no high-quality tutorial found"]
}
```

### Token Cost for Learning Path Mode
Learning Path mode is more expensive than Best Pick due to the topic decomposition step and per-subtopic searches. Typical cost:
- Topic decomposition: 1 LLM call (~500 tokens)
- Per subtopic scoring: batched, ~2–3 extra LLM calls
- Path assembly: 1 LLM call (~1,000 tokens)
- **Total: ~$0.10–0.15 per learning path query** (vs ~$0.06 for Best Pick)
- Cache all per-subtopic scores as normal — repeat queries are cheap

---

## Sidebar UI — Both Modes

The sidebar has two tabs at the top:

```
[ ★ Best Pick ]  [ 🗺 Learning Path ]
```

**Best Pick tab:**
- Hero card: the #1 result with score, level, type badge, summary, and a large "Watch Now" button
- Below it: 3–4 runner-up cards (collapsed by default) for users who want alternatives
- Rationale text: 1–2 sentences explaining *why* this is the best pick

**Learning Path tab:**
- Shows the step-by-step sequence as numbered cards
- Each card: step number, subtopic label, video/playlist title, channel, duration, "why" text
- Total estimated time shown at the top
- Any gaps flagged with a warning label
- "Open All in Queue" button: opens all videos in a new YouTube playlist or sequentially in tabs

---

### Video Score
```
final_score = (
  llm_content_score * 0.50 +
  normalized_view_count * 0.15 +
  normalized_like_ratio * 0.15 +
  recency_score * 0.10 +
  channel_authority_score * 0.10
)
```

### Playlist Score
```
final_score = (
  llm_content_score * 0.55 +
  normalized_view_count * 0.10 +     # avg views across playlist
  completeness_score * 0.20 +        # video_count vs expected for topic
  recency_score * 0.15
)
```

### Normalization Notes
- `normalized_view_count`: log scale (log10(views) / log10(max_views_in_set))
- `like_ratio`: likes / (likes + dislikes) — use likes / views as proxy since dislikes are hidden
- `recency_score`: 1.0 if <6 months, 0.8 if <1 year, 0.5 if <3 years, 0.2 if older
- `channel_authority_score`: log10(subscribers) / 8 (capped at 1.0)

---

## Output Format

### Best Pick Mode
```json
{
  "mode": "best_pick",
  "recommendation": {
    "type": "playlist",
    "title": "Complete React Course 2024",
    "channel": "Traversy Media",
    "url": "https://youtube.com/playlist?list=...",
    "score": 8.7,
    "level": "beginner",
    "video_count": 14,
    "total_duration_hrs": 6.5,
    "summary": "Covers React from scratch through hooks and state management. Well-paced with real project examples.",
    "why_best": "Highest content score in the candidate set. Covers 7 of 8 core subtopics in a single well-structured playlist, eliminating the need to stitch together multiple sources."
  },
  "runners_up": [
    {
      "type": "video",
      "title": "React in 100 Seconds",
      "channel": "Fireship",
      "url": "https://youtube.com/watch?v=...",
      "score": 8.2,
      "level": "beginner",
      "duration_mins": 12,
      "summary": "Dense, high-quality overview. Best as orientation before a deeper course."
    }
  ]
}
```

See **Learning Path Feature** section above for the learning path output format.

---

## Project Structure

```
youtube-tutorial-finder/
├── instructions.md
│
├── extension/                        # Chrome Extension
│   ├── manifest.json                 # MV3 manifest
│   ├── content_script.js             # Injected into YouTube pages
│   ├── background.js                 # Service worker (handles API calls)
│   ├── popup.html                    # Extension popup UI
│   ├── popup.js                      # Popup logic (settings, filters)
│   ├── styles/
│   │   ├── sidebar.css               # Injected sidebar styles
│   │   └── popup.css
│   └── icons/
│       ├── icon16.png
│       ├── icon48.png
│       └── icon128.png
│
└── backend/                          # Hosted Python API
    ├── main.py                       # FastAPI entry point
    ├── config.py                     # API keys, thresholds, weights
    ├── fetcher/
    │   ├── youtube_search.py         # YouTube Data API calls
    │   ├── playlist_expander.py      # Fetch videos in a playlist
    │   └── transcript.py             # Fetch + clean transcripts
    ├── scorer/
    │   ├── metadata_filter.py        # Pre-filter by views, duration, recency
    │   └── llm_scorer.py             # Batch LLM scoring (returns subtopics_covered)
    ├── ranker/
    │   └── rank.py                   # Weighted final scoring + sorting
    ├── learning_path/
    │   ├── decomposer.py             # LLM topic → ordered subtopics list
    │   ├── subtopic_search.py        # Per-subtopic YouTube search + scoring
    │   ├── assembler.py              # Dedup, gap detection, path ordering
    │   └── path_ranker.py            # Final LLM call to assemble & justify path
    └── cache/
        └── db.py                     # SQLite/Redis cache (videos + paths)
```

---

## Chrome Extension Details

### manifest.json (MV3)
```json
{
  "manifest_version": 3,
  "name": "Tutorial Finder",
  "version": "1.0",
  "permissions": ["storage", "activeTab"],
  "host_permissions": ["https://www.youtube.com/*"],
  "content_scripts": [{
    "matches": ["https://www.youtube.com/results*"],
    "js": ["content_script.js"],
    "css": ["styles/sidebar.css"]
  }],
  "background": { "service_worker": "background.js" },
  "action": {
    "default_popup": "popup.html",
    "default_icon": "icons/icon48.png"
  }
}
```

### How the Content Script Works
1. Fires on any `youtube.com/results?search_query=...` URL
2. Reads `search_query` param from the URL
3. Injects a sidebar panel to the right of YouTube's native results
4. Sends the query to the backend API via `background.js` (avoids CORS issues)
5. Renders ranked results in the sidebar as they return

### Sidebar UI (injected into YouTube)
- Appears as a fixed right-side panel on YouTube search results pages
- Shows a loading skeleton while backend processes
- Each result card shows: rank badge, type tag (VIDEO / PLAYLIST), title, channel, score, level pill, summary, and a direct link
- Filter controls at the top: skill level (All / Beginner / Intermediate / Advanced)
- Results update automatically when the YouTube search query changes (via URL change observer)

### Key Extension Constraints
- **No API keys in the extension** — all keys live server-side only
- Use `chrome.storage.local` for user preferences (skill level filter, etc.)
- MV3 service workers have no persistent state — keep `background.js` stateless
- Sidebar must not break YouTube's layout — use `position: fixed` or inject into a spare column slot

### Publishing
- For personal/team use: sideload via `chrome://extensions` → Developer Mode → Load Unpacked
- For public release: submit to Chrome Web Store (~1–3 day review); requires a $5 one-time developer fee

---

## Environment Variables

```
# Backend only — never in the extension
YOUTUBE_API_KEY=...
ANTHROPIC_API_KEY=...
CACHE_TTL_DAYS=30
MAX_CANDIDATES=15
MAX_TRANSCRIPT_TOKENS=4000
PLAYLIST_TRANSCRIPT_VIDEOS=3
BACKEND_URL=https://your-api.yourdomain.com   # Extension points here
ALLOWED_ORIGINS=chrome-extension://YOUR_EXT_ID
```

---

## Cost Estimate

### Best Pick Mode (per query, 15 candidates, 3 batched LLM calls)

| Item | Estimate |
|---|---|
| Input tokens (3 calls × ~6k tokens) | ~18,000 tokens |
| Output tokens (3 calls × ~500 tokens) | ~1,500 tokens |
| Cost at claude-sonnet-4-6 pricing | ~$0.06 per query |
| With 80% cache hit rate at scale | ~$0.01 effective cost |

### Learning Path Mode (per query)

| Item | Estimate |
|---|---|
| Topic decomposition call | ~$0.01 |
| Per-subtopic scoring (batched) | ~$0.06 |
| Path assembly call | ~$0.02 |
| **Total cold** | **~$0.10–0.15** |
| With cache hits | ~$0.03 effective cost |

---

## Known Limitations

- Auto-generated captions can be noisy; quality varies by creator
- Some videos have no transcripts (non-English, disabled captions) — fall back to metadata-only score with a flag
- Playlists with 50+ videos: only first 3 are transcript-scored; rest is inferred
- YouTube API quota: 10,000 units/day free; a single search costs ~100 units, so ~100 queries/day before quota hit
- YouTube DOM changes may break the sidebar injection — content script may need updates when YouTube ships UI changes
- MV3 service workers are terminated when idle — backend must handle its own request queuing

---

## Future Improvements

- User personalization: beginner vs. advanced preference saved per-user
- Domain-specific scoring rubrics (coding vs. math vs. design vs. language learning)
- Score badge overlaid directly on YouTube's native video thumbnails
- Feedback loop: thumbs up/down on results to improve weights over time
- Multi-language support
- Embedding-based semantic search across cached transcripts at scale
- Firefox port (WebExtensions API is compatible with minor changes)
