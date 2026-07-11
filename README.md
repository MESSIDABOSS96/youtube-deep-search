# tubelens

**Content-aware YouTube search.** Type a plain-English question; tubelens searches
YouTube, *reads the transcripts* of the videos it finds, and ranks them by what's
actually said inside them — not by their titles. It writes you a short "here's what to
do" brief and opens a results page with clickable, timestamped links.

> YouTube search ranks on titles, tags, and engagement. So intent-based questions —
> *"how to start growth work for an app that isn't released yet"* or *"elbow pain from
> golf on the inside of the joint"* — return generic videos, and the good content stays
> buried inside videos whose titles never mention what you searched for. tubelens fixes
> that by ranking on the transcript, not the title.

> **Status: v1.** Working end to end. See [`SPEC.md`](SPEC.md) for the full design.

---

## How it works

1. Turns your one question into several YouTube searches (so you don't run them by hand).
2. Pulls transcripts for the candidate videos.
3. Ranks them by content in three passes — a cheap triage over all candidates, a deep
   read of the most promising ones, then a final side-by-side comparison that sorts
   everything into tiers (strong / partial / related) with a one-line reason each.
4. Writes a short synthesized "playbook" from the best videos, with sources cited.
5. Opens a self-contained HTML report in your browser with ranked cards and
   jump-to-timestamp links.

No server, no account, no database. It's a local command that writes a page and opens it.

## Install

```bash
pipx install tubelens        # or: uv tool install tubelens
```

## Setup — your keys

tubelens runs entirely on your own machine with your own keys. You need:

1. **A YouTube Data API v3 key** (free) — always required; this is how candidate videos
   are found. Create one at <https://console.cloud.google.com/apis/credentials> (enable
   "YouTube Data API v3"). Free quota is 10,000 units/day ≈ 16 default runs/day.
   ```bash
   export YOUTUBE_API_KEY="..."
   ```
2. **An LLM — use whatever provider you already have.** You are *not* locked to
   Anthropic. tubelens works with any of these; just set that provider's key and point
   `--model` at it:

   | Provider | Set this key | Example `--model` |
   |---|---|---|
   | Anthropic *(default)* | `ANTHROPIC_API_KEY` | `anthropic/claude-haiku-4-5` |
   | OpenAI | `OPENAI_API_KEY` | `openai/gpt-4o-mini` |
   | Google Gemini | `GEMINI_API_KEY` | `gemini/gemini-1.5-flash` |
   | Groq | `GROQ_API_KEY` | `groq/llama-3.1-8b-instant` |
   | Mistral | `MISTRAL_API_KEY` | `mistral/mistral-small-latest` |
   | Cohere | `COHERE_API_KEY` | `cohere/command-r` |
   | **Local (Ollama)** | *none* | `ollama/llama3.1` |

   Anthropic is only the *default* when you don't pass `--model`. Pick any row:
   ```bash
   export OPENAI_API_KEY="..."      # for example
   tubelens "..." --model openai/gpt-4o-mini
   ```
   With a **local model** via [Ollama](https://ollama.com) you need *no LLM key at all* —
   YouTube becomes the only key you need. If you choose a model whose key isn't set,
   tubelens tells you the exact variable to export. Any
   [litellm](https://docs.litellm.ai/docs/providers)-supported provider works, not just
   the rows above.

## Usage

```bash
tubelens "how to start growth work for an app before it's on the app store"
```

Common flags (see `tubelens --help` for all):

| Flag | Meaning |
|---|---|
| `--results N` | how many top videos to deep-read; all are shown, tiered by match strength (default 10) |
| `--scan N` | how many candidate videos to examine (default 80) |
| `--model MODEL` | LLM for ranking/synthesis, e.g. `anthropic/claude-haiku-4-5`, `openai/gpt-4o-mini`, `ollama/llama3.1` |
| `--no-brief` | skip the synthesized playbook |
| `--no-clarify` | never ask clarifying questions |

## Cost

Ranking is a judgment task that **cheap models do well** — you do not need a frontier
model, and tubelens defaults to a cheap one on purpose.

| Setup | Approx. cost per query |
|---|---|
| Default cheap cloud model | ~$0.01–0.05 |
| Local model via Ollama | $0.00 |
| Frontier model (not recommended) | ~10–30× the default, for little quality gain |

If you pass a known-expensive model, tubelens prints a one-line heads-up and proceeds.

## A note on transcripts and YouTube's terms

tubelens retrieves captions via an unofficial endpoint (the `youtube-transcript-api`
library), which is a gray area under YouTube's Terms of Service. **This is a personal
research tool for individual, self-hosted use with your own API keys. It is not a hosted
service and should not be run as one.** tubelens uses no YouTube branding or logos.

## License

MIT — see [LICENSE](LICENSE). Contributions welcome.
