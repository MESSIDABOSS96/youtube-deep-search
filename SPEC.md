# SPEC: `tubelens` — content-aware YouTube search

> Working name: **tubelens** (rename freely; referred to as "the tool" below).
> Status: v1 spec, ready for implementation handoff.

---

## 0. What this is and how it's distributed

**This is an open-source project, and that is a design constraint, not an afterthought.**
It is published publicly on GitHub under the **MIT license** for anyone to install, read,
modify, and share. It is deliberately *not* a hosted product: there is no server the
maintainer runs and no shared bill. Every user installs the CLI and runs it on their own
machine with their own API keys (and, optionally, their own local model — see §8), which
is precisely what keeps it free to maintain and free for others to use.

Concrete implications this spec must honor throughout:
- **Nothing may assume a central server, shared key, or maintainer-operated backend.**
- **Setup must be trivial for a stranger** — install via `pipx`/`uv`, set 1–2 env vars,
  run. The README onboards someone who has never used the tool (§4, §10).
- **Costs are always the user's own and always small by default** (§8) — no design choice
  may quietly spend a user's money.
- **The repo is the product**: README, LICENSE, clear file layout, and offline tests
  (§10) are first-class deliverables, not optional polish.

---

## 1. Problem

YouTube search ranks on titles, descriptions, tags, and engagement — not on what is
actually *said* in a video. Intent-based queries fail:

- *"how to start growth work for an app that isn't released yet"* → returns generic
  "app marketing" videos; the best content is inside videos whose titles never mention
  "pre-launch."
- *"elbow pain when hitting low shots in golf"* → returns generic tennis-elbow /
  golfer's-elbow videos; the user must open many videos to find one describing their
  actual symptom.

Users waste time running multiple keyword queries and skimming videos that don't
contain what they need.

## 2. What the tool does

A command-line tool. The user types one natural-language, intent-based query.
The tool:

1. Optionally asks 1–2 clarifying questions **only if the query is ambiguous**.
2. Expands the query into several keyword searches and runs them against the
   **YouTube Data API v3**.
3. Pulls transcripts for the candidate videos.
4. Ranks candidates by how well their **content** (not title) matches the user's intent,
   using a two-stage LLM ranking pipeline (cheap triage → deep read).
5. Generates a **single self-contained HTML report** and opens it in the default browser:
   - a short **synthesized brief** ("the playbook") drawn from the top videos, with
     per-point source citations,
   - ranked **video cards** with thumbnail, why-it-matches, score, and a
     **timestamped deep link** (`youtube.com/watch?v=ID&t=252s`),
   - a **coverage/transparency section** showing everything that was scanned.

No server. No database. No accounts. The HTML file is written to disk and opened.

## 3. Goals and non-goals

### Goals (v1)
- One command → useful, trustworthy results page in ≤ ~60 seconds for default settings.
- Result quality noticeably better than manual YouTube search for intent-based queries.
- **Trust through transparency**: the user must be able to see that the tool covered at
  least what they would have found manually. This is a product requirement, not a
  nice-to-have (see §7.3).
- **Cheap per query**: target < $0.05/query with default models; ranking must be
  efficient by design (see §6.4).
- Trivial install and setup for an OSS user: `pipx install` (or `uv tool install`),
  two env vars, go.
- Multi-provider LLM support — users bring whatever key they have.

### Non-goals (v1) — explicitly out of scope
- No hosted service, web server, or `localhost` app. The UI is a generated static file.
- No Whisper / local transcription fallback for videos without captions (v2 candidate).
  Videos without retrievable transcripts are skipped **but still listed** in the
  coverage section as "no transcript available."
- No persistent cache or history (a per-run temp cache is fine; nothing survives runs
  except the HTML reports themselves).
- No playlists, channels-only search, comments analysis, or non-YouTube sources.
- No packaging for npm/homebrew; Python packaging only.

## 4. Users and setup

Target user: technically comfortable enough to install a CLI and create API keys.
README must walk through both keys with screenshots-level clarity:

- `YOUTUBE_API_KEY` — YouTube Data API v3 key (free, 10,000 quota units/day;
  each `search.list` call costs 100 units).
- One LLM provider key, e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.

Configuration precedence: CLI flags > env vars > config file
(`~/.config/tubelens/config.toml`, optional) > defaults.

## 5. CLI interface

```
tubelens "how to start growth work for an app before it's on the app store"

Options:
  --results N         number of ranked results to show (default 10)
  --scan N            max candidate videos to scan (default 80, hard cap 200)
  --model MODEL       LLM for deep ranking + synthesis, litellm format
                      (default: anthropic/claude-haiku-4-5)
  --triage-model M    LLM for stage-1 triage (default: same as --model)
  --no-brief          skip the synthesized playbook section
  --no-clarify        never ask clarifying questions
  --open / --no-open  open report in browser (default --open)
  --out PATH          output path (default ./tubelens-<slug>-<timestamp>.html)
  --json              also write raw results as JSON next to the HTML
  --lang LANG         transcript language preference (default "en")
  -v, --verbose       show pipeline progress detail
```

Terminal UX while running: a live progress line per stage
(`Expanding query… → Searching YouTube (6 queries)… → Fetching transcripts (61/84)…
→ Triaging 61 candidates… → Deep-reading top 15… → Synthesizing brief… → Report: <path>`).
Use `rich` for progress display.

## 6. Pipeline (the core)

### 6.0 Stage overview

```
user query
  → [clarify gate]            1 cheap LLM call
  → [query expansion]         same LLM call as clarify gate (single call does both)
  → [YouTube search]          N parallel search.list calls, dedupe
  → [metadata hydrate]        videos.list batch call (stats, duration)
  → [transcript fetch]        parallel, youtube-transcript-api
  → [stage-1 triage]          1–2 batched LLM calls over ALL candidates
  → [stage-2 deep rank]       parallel LLM calls over top ~15 only
  → [synthesis]               1 LLM call over top ~6 deep-read results
  → [render HTML]             local template, no LLM
```

### 6.1 Clarify gate + query expansion (one LLM call)

Single LLM call that receives the user query and returns structured JSON:

```json
{
  "ambiguous": false,
  "clarifying_questions": [],          // 1–2 questions iff ambiguous
  "search_queries": ["...", "..."],    // 4–7 keyword queries for YouTube
  "intent_summary": "one-sentence restatement of what the user wants"
}
```

- **When to ask — the "results-changing" test.** A question is allowed *only if
  different plausible answers would lead to materially different search queries or a
  materially different ranking.* If every answer would produce the same searches and the
  same best videos, the question is forbidden — it only adds friction. Specific,
  well-formed queries must pass silently (`ambiguous: false`, no questions).

  The model must apply this test to each candidate question and keep a question only if
  it can name how the answers diverge. Concretely, for `"elbow pain from golf"`:
  - ✅ **"Is the pain on the inside or outside of the elbow?"** — *good.* Inside vs.
    outside distinguishes golfer's elbow from tennis elbow, which are different
    conditions with different videos. The answer changes the searches.
  - ✅ **"Does it hurt at impact, during the backswing, or when gripping?"** — *good.*
    Points to different causes/fixes, so different videos rank.
  - ❌ **"Which arm is affected — left or right?"** — *forbidden.* The rehab content is
    the same regardless of arm; no answer changes the results. This is exactly the kind
    of low-value question the gate must suppress.

  Rule of thumb the prompt should encode: *"Before asking, state how each possible
  answer would change the search. If you can't, don't ask."* Prefer asking **zero**
  questions over asking a weak one. Cap at the **single most results-changing** question
  when possible; never more than two.
- When a question does clear the bar, print it in the terminal, read answers via stdin,
  then re-run this call with the answers appended. Maximum one clarify round.
- Offer an escape hatch: the user can press enter to skip any question, and `--no-clarify`
  disables the gate entirely (already in §5).
- Query expansion strategy: mix of (a) direct keyword forms of the intent,
  (b) adjacent phrasings practitioners would use, (c) one broader umbrella query.
  The expanded queries are shown in the report (trust requirement).

### 6.2 YouTube search + hydrate

- `search.list` per expanded query (`part=snippet`, `type=video`, `maxResults=25`,
  `relevanceLanguage` from `--lang`, `safeSearch=none`). Run in parallel.
- Deduplicate by video ID; keep the union up to `--scan` cap. If over cap, keep by
  interleaving each query's results in rank order (preserves diversity across queries).
- One batched `videos.list` call (`part=snippet,statistics,contentDetails`) for
  view counts, duration, channel title. Filter out: videos < 60s (Shorts are rarely
  substantive; make this a constant, easily changed), live streams, non-`--lang`
  videos when detectable.
- Quota note for README: default run = ~6 searches × 100 units + 1–2 videos.list units
  ≈ 600 units → ~16 default runs/day on the free quota. Surface a clear error when
  quota is exhausted (see §9).

### 6.3 Transcript fetch

- `youtube-transcript-api` (unofficial; see §11 ToS note), preferring manual captions,
  falling back to auto-generated, in `--lang` then any available language with
  translation to `--lang` if the library supports it.
- Parallelize with a bounded worker pool (~8 concurrent) and per-video timeout (~10s).
- Keep segment timestamps — they power the "jump to 4:12" links.
- Videos with no transcript: mark `no_transcript`, exclude from ranking, include in the
  coverage table (trust requirement).

### 6.4 Stage-1 triage (efficiency requirement)

**Purpose: never pay to deep-read a bad candidate.** All ~60–80 transcript-bearing
candidates are scored in **1–2 batched LLM calls total**, not per-video calls.

- For each candidate build a compact digest: title, channel, duration, view count,
  and ~3 transcript excerpts (beginning / middle / a keyword-relevant chunk), total
  ≤ ~300 tokens per video.
- Prompt: given the user's intent, score each candidate 0–10 for *likelihood its
  content addresses the intent*, with a 5-word reason. Return JSON array.
- Batch all digests into one call if they fit comfortably in context; otherwise split
  into two. Use `--triage-model`.
- Select the top `DEEP_READ_COUNT` for stage 2. **This must never be smaller than
  `--results`**, or the tool would show cards it never actually deep-read. Compute it as
  `max(15, --results + 5)` (a few extra so the displayed set is chosen from a slightly
  larger deep-read pool, not a hard cutoff). Thus asking for more results automatically
  deep-reads more — "more results" stays "more *quality* results," never padding.
- Triage scores and reasons are kept for the coverage table — every scanned video shows
  its score so the user can audit what was left out (trust requirement).

### 6.5 Stage-2 deep rank

For each of the top ~15, one LLM call (run in parallel, bounded ~5 concurrent):

- Input: user intent + the full transcript **with timestamps**, chunked/truncated to
  fit the model's context sensibly (for very long videos, take the stage-1-relevant
  regions plus surrounding context rather than naive head-truncation).
- Output JSON:

```json
{
  "score": 8.5,                       // 0–10 content match to intent
  "why": "one sentence, specific: what this video actually covers for this intent",
  "best_timestamp_seconds": 252,
  "timestamp_reason": "starts the pre-launch waitlist walkthrough",
  "key_points": ["...", "..."]        // 2–4 bullets, used by synthesis
}
```

- Final ranking = stage-2 score (stage-1 score is discarded except for the coverage
  table). Ties broken by view count. Show top `--results`.

### 6.6 Synthesis ("the playbook")

One LLM call over the top ~6 deep-read results' `key_points` + `why` + metadata:

- Output: a titled brief of 3–6 actionable points. **Every point must cite ≥1 source
  video by index**, rendered in HTML as a link to that video at its relevant timestamp.
- Prompt constraint: synthesize only from provided material; no outside knowledge;
  if the videos disagree, say so.
- Skipped entirely with `--no-brief`.

### 6.7 Performance & cost targets

- Wall clock: ≤ 60s default run (network permitting). Transcript fetch and stage-2
  are the long poles; both are parallelized.
- LLM calls per default run: 1 (clarify/expand) + 1–2 (triage) + ~15 (deep) + 1
  (synthesis) ≈ 18–19 calls, all on a cheap model by default → roughly $0.01–0.05.
- All LLM calls request JSON and are validated; one retry with error feedback on
  malformed output, then fail that item gracefully (see §9).

## 7. HTML report

### 7.1 Format

- **One self-contained `.html` file.** All CSS inline in a `<style>` block; a small
  amount of dependency-free vanilla JS inline (collapse/expand only). **No external
  fetches** except thumbnails hotlinked from `i.ytimg.com` (acceptable; if offline,
  cards degrade gracefully via `onerror` hiding the image).
- Rendered from a Python template (Jinja2). Light/dark via
  `prefers-color-scheme`.

### 7.2 Layout (top to bottom)

1. **Header**: the user's original query, verbatim, large. Subline: intent summary.
2. **Coverage strip** (trust requirement, always visible, one line):
   `Expanded into 6 searches · 84 videos found · 61 transcripts read · 15 deep-read · top 10 shown` —
   with "6 searches" expandable to list the exact expanded queries.
3. **The playbook** (unless `--no-brief`): titled brief, numbered points, each point
   followed by small source chips like `▶ 4:12 · How I Got 1,000 Users` linking to
   the timestamped video.
4. **Ranked results**: cards designed to read as *YouTube, but ranked by content*.
   Each card:
   - thumbnail (left), linked to the timestamped URL,
   - title + channel + views + duration (YouTube-familiar metadata row),
   - score badge (e.g. `9.2`),
   - the `why` sentence — specific, not generic,
   - `Jump to 4:12 — starts the pre-launch waitlist walkthrough` link.
5. **Everything scanned** (trust requirement, collapsed by default):
   a table of *all* candidates — title (linked), channel, triage score + 5-word reason,
   and status (`deep-read`, `triaged out`, `no transcript`, `filtered: short`).
   This is how a skeptical user verifies nothing they'd have found manually was hidden.
6. **Footer**: models used, run duration, generated-at timestamp, tool name + repo link.

### 7.3 Trust requirement (design principle, not a feature)

The single biggest adoption risk is the user thinking *"would I have found something
better by hand?"* Every design choice above that shows coverage — the strip, the
expanded-queries list, the full scan table with per-video status and scores — exists to
answer that question on the page itself. Implementations must not drop these for
visual minimalism.

## 8. Multi-provider LLM support

- Use **litellm** as the provider abstraction. `--model` accepts any litellm model
  string (`anthropic/claude-haiku-4-5`, `openai/gpt-4o-mini`, `gemini/...`, local
  `ollama/...`).
- Default: `anthropic/claude-haiku-4-5` (cheap, fast, good at judgment tasks).
- The tool detects which provider key is present at startup; if the chosen model's key
  is missing, error with the exact env var name needed.
- All prompts must be provider-agnostic (plain text + "respond with JSON matching this
  schema"); no provider-specific features (no tool-use, no structured-output APIs) so
  any litellm backend works.
- **Local models are a first-class path**: `--model ollama/<model>` must work with a
  local Ollama install (no LLM key, no cloud calls). Document this in the README as
  the "one key only" setup (the YouTube key is always required — candidates must come
  from the Data API; scraping search results is out of scope and worse ToS territory).
  Test the pipeline against at least one small local model and note in the README which
  one was validated and that small local models may reduce ranking/JSON quality.
- **Cheap-by-default cost posture** (product requirement):
  - The default model stays in the cheap tier; ranking is a judgment task cheap models
    do well, and the README must say so explicitly with a cost table
    (default run ≈ $0.01–0.05 on cheap models; frontier models cost ~10–30× more for
    little quality gain here).
  - Runtime nudge: if `--model` matches a known-expensive pattern (maintained as a
    simple constant list, e.g. `opus`, `gpt-4o` non-mini, `o1`, `gemini-.*-pro`),
    print a one-line warning with the estimated multiplier and proceed. Never block.

## 9. Error handling

| Failure | Behavior |
|---|---|
| Missing `YOUTUBE_API_KEY` / LLM key | Exit immediately with setup instructions incl. exact URL to create the key |
| YouTube quota exceeded | Clear message: quota resets midnight PT; suggest `--scan` reduction |
| Individual transcript fetch fails | Skip video, mark in coverage table, continue |
| < 5 candidates with transcripts | Proceed but warn prominently in terminal and report |
| Zero search results | Say so; show the expanded queries so the user can judge; suggest rephrasing |
| LLM call fails (one item) | One retry; then drop that item with a terminal warning |
| LLM call fails (triage/synthesis) | Triage: fall back to YouTube's own relevance order for deep-read selection, note the fallback in the report. Synthesis: render report without the brief, note it |
| Malformed LLM JSON | One retry with the validation error appended; then treat as call failure |

Nothing should ever stack-trace at the user for an expected failure mode.

## 10. Tech stack & repo layout

- **Python ≥ 3.10**, packaged with `pyproject.toml`, installable via
  `pipx install tubelens` / `uv tool install tubelens`.
- Dependencies (keep to exactly these + stdlib): `httpx` (YouTube API calls — the
  Data API is plain REST; skip the heavy google client), `youtube-transcript-api`,
  `litellm`, `jinja2`, `rich`, `pydantic` (config + LLM output validation).

```
tubelens/
├── pyproject.toml
├── README.md                 # problem, demo GIF placeholder, setup (both keys,
│                             # step-by-step), usage, cost/quota notes, ToS note, v2 list
├── LICENSE                   # MIT
├── src/tubelens/
│   ├── __init__.py
│   ├── cli.py                # arg parsing, progress display, orchestration
│   ├── config.py             # env/flags/config-file resolution (pydantic)
│   ├── youtube.py            # search.list, videos.list, dedupe, filters
│   ├── transcripts.py        # parallel fetch, timestamp-preserving chunking
│   ├── ranking.py            # clarify/expand, triage, deep rank (all LLM calls)
│   ├── synthesis.py          # playbook generation
│   ├── report.py             # Jinja2 render + browser open
│   ├── models.py             # pydantic schemas: Candidate, TriageResult, DeepResult…
│   └── templates/report.html.j2
└── tests/
    ├── test_youtube.py       # dedupe, interleave, filters (mocked API)
    ├── test_ranking.py       # digest building, JSON validation/retry (mocked LLM)
    ├── test_report.py        # renders golden fixture data → valid self-contained HTML
    └── fixtures/             # canned API/LLM responses
```

- Tests: no network in tests; mock YouTube + LLM with fixtures. A `--json` golden-file
  test of the full pipeline wiring with everything mocked.
- Code style: type hints throughout, `ruff` for lint/format.

## 11. Legal / ToS note (README requirement)

`youtube-transcript-api` retrieves captions via an unofficial endpoint, which is a
gray area under YouTube's ToS. The README must state plainly: this is a personal
research tool intended for individual, self-hosted use with the user's own API keys;
it is not a hosted service and should not be operated as one. No YouTube branding/logo
in the tool or report (name the tool distinctly; don't imitate YouTube's logo or
trade dress — visual *familiarity* of card layout is fine, brand imitation is not).

## 12. v2 parking lot (do not build in v1)

- Whisper fallback for uncaptioned videos (via yt-dlp audio download).
- Cross-run transcript/result cache (`~/.cache/tubelens/`).
- `--refine` interactive loop: adjust query from the results page.
- Local web UI wrapper.
- Channel/date/duration filter flags.
- Embedding-based triage as a cheaper stage-1 alternative.

## 13. Acceptance criteria (definition of done for v1)

1. `pipx install .` from a clean checkout → `tubelens --help` works.
2. With valid keys, the pre-launch-growth example query produces, in ≤ ~90s: an HTML
   file that opens automatically and contains a playbook with cited sources, ≥ 8 ranked
   cards each with working timestamped YouTube links, the coverage strip with real
   numbers, and the full collapsed scan table.
3. Every link in the report opens the right video at the right time.
4. Running with a deliberately vague query ("elbow pain golf") triggers ≤ 2 clarifying
   questions in the terminal; running with the spec's example query triggers none.
5. Unplugging each failure mode in §9 (bad key, no quota, no transcripts) produces the
   specified friendly message, never a traceback.
6. `--model openai/gpt-4o-mini` works identically with an OpenAI key (provider
   agnosticism proven with at least two providers).
7. All tests pass offline; `ruff check` clean.
