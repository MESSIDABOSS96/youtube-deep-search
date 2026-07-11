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

Requires **Python 3.10+**. Install straight from GitHub with
[pipx](https://pipx.pypa.io/stable/installation/) (or `uv`):

```bash
pipx install git+https://github.com/MESSIDABOSS96/youtube-deep-search.git
# or: uv tool install git+https://github.com/MESSIDABOSS96/youtube-deep-search.git
```

Check it worked:

```bash
tubelens --version
```

> No pipx? `brew install pipx && pipx ensurepath` on macOS, then reopen your terminal.
> If your system Python is older than 3.10, add `--python python3.11` to the pipx command.

## Setup — your keys (~5 minutes, both free to create)

tubelens runs entirely on your own machine with your own keys. You need:

1. **A YouTube Data API v3 key** (free) — always required; this is how candidate videos
   are found:
   1. Go to <https://console.cloud.google.com/> and sign in with any Google account.
   2. Create a project (top-left project picker → **New Project** → any name → Create).
   3. Go to <https://console.cloud.google.com/apis/library/youtube.googleapis.com>
      and click **Enable**.
   4. Go to <https://console.cloud.google.com/apis/credentials> → **Create Credentials**
      → **API key** → copy it.
   5. Set it in your terminal:
      ```bash
      export YOUTUBE_API_KEY="paste-your-key-here"
      ```
   Free quota is 10,000 units/day ≈ 16 default runs/day. No billing required.
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

   Anthropic is only the *default* when you don't pass `--model`
   (create a key at <https://console.anthropic.com/settings/keys> — needs a payment
   method, but $5 of credit covers hundreds of runs). Pick any row:
   ```bash
   export OPENAI_API_KEY="..."      # for example
   tubelens "..." --model openai/gpt-4o-mini
   ```
   With a **local model** via [Ollama](https://ollama.com) you need *no LLM key at all* —
   YouTube becomes the only key you need. If you choose a model whose key isn't set,
   tubelens tells you the exact variable to export. Any
   [litellm](https://docs.litellm.ai/docs/providers)-supported provider works, not just
   the rows above.

> **Make your keys stick:** `export` only lasts until you close the terminal. To set
> them permanently, add the two export lines to your shell profile:
> ```bash
> echo 'export YOUTUBE_API_KEY="your-key"' >> ~/.zshrc
> echo 'export ANTHROPIC_API_KEY="your-key"' >> ~/.zshrc   # or your provider's variable
> ```
> then reopen your terminal.

## Usage

```bash
tubelens "how to start growth work for an app before it's on the app store"
```

You'll see progress in the terminal (expanding your query into searches → fetching
transcripts → ranking), and in ~30–60 seconds a report opens in your browser with:

- a one-line **coverage strip** (how many searches/videos/transcripts it covered),
- a collapsed **playbook** — the advice synthesized across the top videos, with sources,
- every deep-read video in **tiers** (strong / partial / related), each with a
  one-line reason, a `whole video`/`one section` chip, and a **jump-to-timestamp** link,
- an expandable **"Everything scanned"** table so you can verify nothing was hidden.

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

## Troubleshooting

| Symptom | Fix |
|---|---|
| `command not found: tubelens` | Run `pipx ensurepath`, then open a new terminal |
| "YOUTUBE_API_KEY is not set" | You skipped Setup step 1, or opened a new terminal without adding the key to `~/.zshrc` |
| "quota exceeded" | Free YouTube quota resets at midnight Pacific; or lower usage with `--scan 40` |
| Few/zero transcripts retrieved | Rare-topic videos may lack captions; try a broader query |
| It asks a clarifying question you don't want | Press Enter to skip it, or pass `--no-clarify` |
| Report didn't open | It's saved as `tubelens-<query>-<time>.html` in your current folder — open it manually |

## A note on transcripts and YouTube's terms

tubelens retrieves captions via an unofficial endpoint (the `youtube-transcript-api`
library), which is a gray area under YouTube's Terms of Service. **This is a personal
research tool for individual, self-hosted use with your own API keys. It is not a hosted
service and should not be run as one.** tubelens uses no YouTube branding or logos.

## License

MIT — see [LICENSE](LICENSE). Contributions welcome.
