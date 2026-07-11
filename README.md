<img width="798" height="710" alt="Screenshot 2026-07-10 at 11 50 11 PM" src="https://github.com/user-attachments/assets/d9b2fbea-2f94-4f95-b4ef-79d598806789" />
<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->

<!-- PROJECT HEADER -->
<br />
<div align="center">
  <h1 align="center">🔍 tubelens</h1>

  <p align="center">
    A better way to search YouTube. Naturally describe what you're looking and it returns videos by what's
    actually <em>said</em> in the transcript, not the title.
  </p> 
    <br />
    <a href="#getting-started"><strong>Get started »</strong></a>
    <br />
    <br />
    <a href="https://github.com/MESSIDABOSS96/youtube-deep-search/issues/new?labels=bug">Report Bug</a>
    &middot;
    <a href="https://github.com/MESSIDABOSS96/youtube-deep-search/issues/new?labels=enhancement">Request Feature</a>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#how-it-works">How It Works</a></li>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li>
      <a href="#usage">Usage</a>
      <ul>
        <li><a href="#cost">Cost</a></li>
        <li><a href="#troubleshooting">Troubleshooting</a></li>
      </ul>
    </li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#a-note-on-transcripts-and-youtubes-terms">A Note on YouTube's Terms</a></li>
  </ol>
</details>

<!-- ABOUT THE PROJECT -->
## About The Project

[product-screenshot]: images/screenshot.png

When using YouTube to intentionally learn or find something, I have wasted hours trying 
to skip through videos trying to find one that's actually what I'm looking for. The most
recent example of this was when trying to learn how to grow an app before the app is launched. 
I tried a few keywords but still was mostly getting results of videos talking about how to grow
post-launch (maybe I'm just bad at searching).

But it got me thinking if a lightweight tool that was easy to build could search YouTube better 
than me. That's how I landed on this project. Tubelens allows you to describe what you want in 
plain English, and it searches YouTube, *reads the transcripts* of the videos it finds, and ranks 
them by what's actually said inside them. It gives you a super simple self-contained HTML report (nothing 
fancy here) with clickable, jump-to-timestamp links.

No server, no account, no database. It's a local command that writes a page and opens it. 
Runs entirely on your own machine with your own API keys.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### How It Works

1. Turns your one question into several YouTube searches (so you don't run them by hand).
2. Pulls transcripts for the candidate videos.
3. Ranks them by content in three passes:
      1. a cheap triage over all candidates
      2. a deep read of the most promising ones
      3. then a final side-by-side comparison that sorts everything into tiers (strong / partial / related) with a one-line reason each.
4. Writes a short synthesized "playbook" from the best videos, with sources cited.
5. Opens a self-contained HTML report in your browser with ranked cards and
   jump-to-timestamp links.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

- **Python 3.10+**
- **litellm** — one interface to any LLM provider (you choose which)
- **youtube-transcript-api** — transcript retrieval
- **Jinja2** — the HTML report
- **Rich** — terminal progress
- **Pydantic** — config + LLM output validation

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- GETTING STARTED -->
## Getting Started

To get a local copy up and running, follow these steps.

### Prerequisites

**Python 3.10 or newer.** Check what you have:

```sh
python3 --version
```

If that prints 3.10+ you're set. If it prints something older (macOS ships **3.9** by
default, which is too old), install a newer Python — the quickest way on a Mac is:

```sh
brew install python@3.11
```

Then, when you install tubelens below, add `--python python3.11` to the command so it
uses that version.

Plus two API keys (both free to create — ~5 minutes total):

**1. A YouTube Data API v3 key** — always required; this is how candidate videos are found.
  1. Go to <https://console.cloud.google.com/> and sign in with any Google account.
  2. Create a project (top-left project picker → **New Project** → any name → Create).
  3. Go to <https://console.cloud.google.com/apis/library/youtube.googleapis.com> and
     click **Enable**.
  4. Go to <https://console.cloud.google.com/apis/credentials> → **Create Credentials** →
     **API key** → copy it.
  5. Set it in your terminal:
     ```sh
     export YOUTUBE_API_KEY="paste-your-key-here"
     ```
  Free quota is 10,000 units/day ≈ 16 default runs/day. No billing required.

**2. An LLM — you choose which; there's no default.** tubelens is provider-neutral: set
the key for whatever provider you already use, and **on first run it shows you a menu of
that provider's models to pick from** — you don't have to memorize a model string. Set
any one of these:

| Provider | Set this key |
|---|---|
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` |
| Groq | `GROQ_API_KEY` |
| Mistral | `MISTRAL_API_KEY` |
| Cohere | `COHERE_API_KEY` |
| NVIDIA *(has a free tier)* | `NVIDIA_NIM_API_KEY` |
| Local via [Ollama](https://ollama.com) | *none needed* |

Any [litellm](https://docs.litellm.ai/docs/providers)-supported provider works, not just
these. Want a **free** option? NVIDIA offers free hosted models (this
[X post](https://x.com/k2sbhai/status/2071981082594210054?s=46) walks through getting a
key at build.nvidia.com), and a local Ollama model needs no key at all — either one makes
YouTube the only key you need.

> **Choosing a model.** On first run tubelens shows a numbered menu of models for the
> providers you have keys for — just press Enter for the recommended one, or pick a
> number. To skip the menu, set your choice once:
> `export TUBELENS_MODEL="anthropic/claude-haiku-4-5"` (or any model string). You can also
> pass `--model <string>` on a single run.

> **Make your settings stick:** `export` only lasts until you close the terminal. To set
> them permanently, add these to your shell profile, then reopen your terminal:
> ```sh
> echo 'export YOUTUBE_API_KEY="your-key"' >> ~/.zshrc
> echo 'export ANTHROPIC_API_KEY="your-key"' >> ~/.zshrc   # or your provider's variable
> ```

### Installation

Install straight from GitHub with [pipx](https://pipx.pypa.io/stable/installation/)
(or `uv`):

```sh
pipx install git+https://github.com/MESSIDABOSS96/youtube-deep-search.git
# or: uv tool install git+https://github.com/MESSIDABOSS96/youtube-deep-search.git
```

Check it worked:

```sh
tubelens --version
```

> No pipx? `brew install pipx && pipx ensurepath` on macOS, then reopen your terminal.
> If your system Python is older than 3.10, add `--python python3.11` to the pipx command.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- USAGE -->
## Usage

```sh
tubelens "how to start growth work for an app before it's on the app store"
```

The first time, tubelens shows a quick menu to pick your model (press Enter for the
recommended one). After that — or once you've set `TUBELENS_MODEL` — it goes straight to
the search.

You'll see progress in the terminal (expanding your query into searches → fetching
transcripts → ranking), and in ~30–60 seconds a report opens in your browser with:

- a one-line **coverage strip** (how many searches/videos/transcripts it covered),
- a collapsed **playbook** — the advice synthesized across the top videos, with sources,
- every deep-read video in **tiers** (strong / partial / related), each with a one-line
  reason, a `whole video`/`one section` chip, and a **jump-to-timestamp** link,
- an expandable **"Everything scanned"** table so you can verify nothing was hidden.

Common flags (see `tubelens --help` for all):

| Flag | Meaning |
|---|---|
| `--results N` | how many top videos to deep-read; all are shown, tiered by match strength (default 10) |
| `--scan N` | how many candidate videos to examine (default 80) |
| `--model MODEL` | Which LLM to use, e.g. `anthropic/claude-haiku-4-5`, `openai/gpt-4o-mini`, `ollama/llama3.1`. Omit it and tubelens shows a picker |
| `--no-brief` | skip the synthesized playbook |
| `--no-clarify` | never ask clarifying questions |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Cost

Ranking is a judgment task that **cheap models do well** — you do not need a frontier
model. A cheap model costs pennies per query; free options cost nothing.

| Setup | Approx. cost per query |
|---|---|
| A cheap cloud model (e.g. Haiku, GPT-4o-mini) | ~$0.01–0.05 |
| Free options (NVIDIA free tier, or local Ollama) | $0.00 |
| Frontier model (not recommended) | ~10–30× a cheap model, for little quality gain |

If you pass a known-expensive model, tubelens prints a one-line heads-up and proceeds.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `command not found: tubelens` | Run `pipx ensurepath`, then open a new terminal |
| "YOUTUBE_API_KEY is not set" | You skipped a prerequisite, or opened a new terminal without adding the key to `~/.zshrc` |
| "quota exceeded" | Free YouTube quota resets at midnight Pacific; or lower usage with `--scan 40` |
| Few/zero transcripts retrieved | Rare-topic videos may lack captions; try a broader query |
| "YouTube is rate-limiting … from your IP" | Temporary — usually lifts in minutes to a couple of hours. Just re-run later (see below) |
| It asks a clarifying question you don't want | Press Enter to skip it, or pass `--no-clarify` |
| Report didn't open | It's saved as `tubelens-<query>-<time>.html` in your current folder — open it manually |

**Transcript rate limits.** YouTube's transcript endpoint is unofficial and it throttles
bursts of requests by IP. tubelens is built to stay well under that line: it fetches
politely (few requests at a time, slightly spaced out), **caches every transcript it
fetches** in `~/.cache/tubelens/` so repeating a query re-downloads nothing, and if
YouTube does start blocking, it **stops immediately** rather than digging in, and tells
you plainly. A block is temporary and clears on its own — you never need to change
networks or use a hotspot.

If you are an unusually heavy user and hit limits often, `youtube-transcript-api` (which
tubelens uses) supports routing transcript requests through **your own proxy** — see its
[proxy docs](https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans-requestblocked-or-ipblocked-exception).
This is optional, usually costs money, and most users will never need it.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ROADMAP -->
## Roadmap

- [x] Cross-run transcript cache + polite fetching + rate-limit circuit breaker
- [ ] Whisper fallback to transcribe videos that have no captions
- [ ] `--refine` interactive loop to adjust the query from the results page
- [ ] Channel / date / duration filter flags
- [ ] Embedding-based triage as a cheaper stage-1 alternative
- [ ] Publish to PyPI (`pipx install tubelens`)

See the [open issues](https://github.com/MESSIDABOSS96/youtube-deep-search/issues) for a
full list of proposed features and known issues.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTRIBUTING -->
## Contributing

This is my first open-sourced project so if you want to make any contributions, that'd be **pretty cool and appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a
pull request, or open an issue with the tag "enhancement". See
[CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup and guidelines.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- LICENSE -->
## License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTACT -->
## Contact
Anirudh Chatterjee — [@anirudh_c5](https://x.com/anirudh_c5) (on X) — anirudhc2005@gmail.com

Project Link:
[https://github.com/MESSIDABOSS96/youtube-deep-search](https://github.com/MESSIDABOSS96/youtube-deep-search)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- YOUTUBE TERMS NOTE -->
## A Note on Transcripts and YouTube's Terms

tubelens retrieves captions via an unofficial endpoint (the `youtube-transcript-api`
library), which is a gray area under YouTube's Terms of Service. **This is a personal
research tool for individual, self-hosted use with your own API keys. It is not a hosted
service and should not be run as one.** tubelens uses no YouTube branding or logos.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
[contributors-shield]: https://img.shields.io/github/contributors/MESSIDABOSS96/youtube-deep-search.svg?style=for-the-badge
[contributors-url]: https://github.com/MESSIDABOSS96/youtube-deep-search/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/MESSIDABOSS96/youtube-deep-search.svg?style=for-the-badge
[forks-url]: https://github.com/MESSIDABOSS96/youtube-deep-search/network/members
[stars-shield]: https://img.shields.io/github/stars/MESSIDABOSS96/youtube-deep-search.svg?style=for-the-badge
[stars-url]: https://github.com/MESSIDABOSS96/youtube-deep-search/stargazers
[issues-shield]: https://img.shields.io/github/issues/MESSIDABOSS96/youtube-deep-search.svg?style=for-the-badge
[issues-url]: https://github.com/MESSIDABOSS96/youtube-deep-search/issues
[license-shield]: https://img.shields.io/github/license/MESSIDABOSS96/youtube-deep-search.svg?style=for-the-badge
[license-url]: https://github.com/MESSIDABOSS96/youtube-deep-search/blob/main/LICENSE

