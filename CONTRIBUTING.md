# Contributing to tubelens

Thanks for your interest — contributions are welcome, whether it's a bug report, an
idea, or a pull request.

## Ways to help

- **Report a bug or request a feature** — open an
  [issue](https://github.com/MESSIDABOSS96/youtube-deep-search/issues). For bugs, include
  the command you ran, what you expected, and what happened (please redact API keys).
- **Improve the ranking, the report design, or the docs** — these are the areas with the
  most room to grow.
- **Add a provider or a feature from the v2 list** in [`SPEC.md`](SPEC.md).

## Development setup

```bash
git clone https://github.com/MESSIDABOSS96/youtube-deep-search.git
cd youtube-deep-search
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Before you open a pull request

```bash
.venv/bin/python -m pytest    # all tests should pass
.venv/bin/ruff check .        # lint should be clean
```

The test suite runs fully offline — the YouTube API and the LLM are mocked, so you don't
need API keys to develop or test.

## Design notes

[`SPEC.md`](SPEC.md) is the source of truth for how the tool is meant to behave. If a
change alters behavior described there, please update the spec in the same PR so the two
never drift.

Guiding principles worth preserving:
- **Trust through transparency** — the report must always let a user verify that nothing
  they'd have found manually was hidden (the coverage strip and "everything scanned"
  table). Don't drop these for visual minimalism.
- **Cheap by default** — ranking is a judgment task cheap models do well; keep the
  default model cheap and never make a change that quietly spends more of a user's money.
- **No hosted assumptions** — this is a local, bring-your-own-key tool. Nothing should
  assume a central server or shared key.

By contributing, you agree that your contributions are licensed under the MIT License.
