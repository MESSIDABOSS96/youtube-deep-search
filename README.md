<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]

<!-- PROJECT HEADER -->
<br />
<div align="center">
  <h1 align="center">🔍 tubelens</h1>

  <p align="center">
    Content-aware YouTube search — describe what you want, and it ranks videos by what's
    actually <em>said</em> in the transcript, not the title.
    <br />
    <a href="SPEC.md"><strong>Read the design spec »</strong></a>
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

[![tubelens report screenshot][product-screenshot]](https://github.com/MESSIDABOSS96/youtube-deep-search)

YouTube search ranks on titles, tags, and engagement — not on what is actually *said* in
a video. So intent-based questions — *"how to start growth work for an app that isn't
released yet"* or *"elbow pain from golf on the inside of the joint"* — return generic
videos, and the good content stays buried inside videos whose titles never mention what
you searched for.

**tubelens** fixes that: you describe what you want in plain English, and it searches
YouTube, *reads the transcripts* of the videos it finds, and ranks them by what's actually
said inside them. It writes you a short "here's what to do" brief and opens a
self-contained HTML report with clickable, jump-to-timestamp links.

No server, no account, no database. It's a local command that writes a page and opens it —
runs entirely on your own machine with your own API keys.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### How It Works

1. Turns your one question into several YouTube searches (so you don't run them by hand).
2. Pulls transcripts for the candidate videos.
3. Ranks them by content in three passes — a cheap triage over all candidates, a deep read
   of the most promising ones, then a final side-by-side comparison that sorts everything
   into tiers (strong / partial / related) with a one-line reason each.
4. Writes a short synthesized "playbook" from the best videos, with sources cited.
5. Opens a self-contained HTML report in your browser with ranked cards and
   jump-to-timestamp links.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

* [![Python][Python-badge]][Python-url]
* [![litellm][litellm-badge]][litellm-url] — one interface to any LLM provider
* [![Anthropic][Anthropic-badge]][Anthropic-url] — default (any provider or local model works)
* [![Jinja][Jinja-badge]][Jinja-url] — the HTML report
* [![Rich][Rich-badge]][Rich-url] — terminal progress
* [![Pydantic][Pydantic-badge]][Pydantic-url] — config + LLM output validation

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- GETTING STARTED -->
## Getting Started

To get a local copy up and running, follow these steps.

### Prerequisites

**Python 3.10+**, and two API keys (both free to create — ~5 minutes total):

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

**2. An LLM — use whatever provider you already have.** You are *not* locked to Anthropic.
Set that provider's key and point `--model` at it:

| Provider | Set this key | Example `--model` |
|---|---|---|
| Anthropic *(default)* | `ANTHROPIC_API_KEY` | `anthropic/claude-haiku-4-5` |
| OpenAI | `OPENAI_API_KEY` | `openai/gpt-4o-mini` |
| Google Gemini | `GEMINI_API_KEY` | `gemini/gemini-1.5-flash` |
| Groq | `GROQ_API_KEY` | `groq/llama-3.1-8b-instant` |
| Mistral | `MISTRAL_API_KEY` | `mistral/mistral-small-latest` |
| Cohere | `COHERE_API_KEY` | `cohere/command-r` |
| **Local (Ollama)** | *none* | `ollama/llama3.1` |

With a **local model** via [Ollama](https://ollama.com) you need *no LLM key at all* —
YouTube becomes the only key you need. Any
[litellm](https://docs.litellm.ai/docs/providers)-supported provider works, not just the
rows above. (An Anthropic key: create one at
<https://console.anthropic.com/settings/keys> — needs a payment method, but $5 of credit
covers hundreds of runs.)

> **Make your keys stick:** `export` only lasts until you close the terminal. To set them
> permanently, add the export lines to your shell profile, then reopen your terminal:
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
| `--model MODEL` | LLM for ranking/synthesis, e.g. `anthropic/claude-haiku-4-5`, `openai/gpt-4o-mini`, `ollama/llama3.1` |
| `--no-brief` | skip the synthesized playbook |
| `--no-clarify` | never ask clarifying questions |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Cost

Ranking is a judgment task that **cheap models do well** — you do not need a frontier
model, and tubelens defaults to a cheap one on purpose.

| Setup | Approx. cost per query |
|---|---|
| Default cheap cloud model | ~$0.01–0.05 |
| Local model via Ollama | $0.00 |
| Frontier model (not recommended) | ~10–30× the default, for little quality gain |

If you pass a known-expensive model, tubelens prints a one-line heads-up and proceeds.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `command not found: tubelens` | Run `pipx ensurepath`, then open a new terminal |
| "YOUTUBE_API_KEY is not set" | You skipped a prerequisite, or opened a new terminal without adding the key to `~/.zshrc` |
| "quota exceeded" | Free YouTube quota resets at midnight Pacific; or lower usage with `--scan 40` |
| Few/zero transcripts retrieved | Rare-topic videos may lack captions; try a broader query |
| It asks a clarifying question you don't want | Press Enter to skip it, or pass `--no-clarify` |
| Report didn't open | It's saved as `tubelens-<query>-<time>.html` in your current folder — open it manually |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ROADMAP -->
## Roadmap

- [ ] Whisper fallback to transcribe videos that have no captions
- [ ] Cross-run cache for transcripts and results
- [ ] `--refine` interactive loop to adjust the query from the results page
- [ ] Channel / date / duration filter flags
- [ ] Embedding-based triage as a cheaper stage-1 alternative
- [ ] Publish to PyPI (`pipx install tubelens`)

See the [open issues](https://github.com/MESSIDABOSS96/youtube-deep-search/issues) for a
full list of proposed features and known issues.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open-source community such an amazing place to learn and
create. Any contributions you make are **greatly appreciated**.

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
[product-screenshot]: images/screenshot.png
[Python-badge]: https://img.shields.io/badge/Python_3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white
[Python-url]: https://www.python.org/
[litellm-badge]: https://img.shields.io/badge/litellm-1A1A1A?style=for-the-badge&logo=lightning&logoColor=white
[litellm-url]: https://docs.litellm.ai/
[Anthropic-badge]: https://img.shields.io/badge/Anthropic_Claude-D97757?style=for-the-badge&logo=anthropic&logoColor=white
[Anthropic-url]: https://www.anthropic.com/
[Jinja-badge]: https://img.shields.io/badge/Jinja-B41717?style=for-the-badge&logo=jinja&logoColor=white
[Jinja-url]: https://jinja.palletsprojects.com/
[Rich-badge]: https://img.shields.io/badge/Rich-FADE2A?style=for-the-badge&logo=python&logoColor=black
[Rich-url]: https://github.com/Textualize/rich
[Pydantic-badge]: https://img.shields.io/badge/Pydantic-E92063?style=for-the-badge&logo=pydantic&logoColor=white
[Pydantic-url]: https://docs.pydantic.dev/
