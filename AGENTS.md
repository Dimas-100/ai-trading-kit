# For AI assistants working in this repository

If a person opens this folder in an AI coding tool and says "set me up", "connect my broker", or
anything like it: the kit has a wizard for that. Run `aitk` (or `python -m aitk`) and let it ask the
questions. If `aitk` is not installed yet, run `start.bat` (Windows) or `./start.sh` first. Do not
edit AI app settings files by hand; the wizard backs them up and knows the formats.

## Rules that hold everywhere in this repo

- **No real orders, ever.** Do not add code that submits, changes or cancels an order at a broker.
  The only `Broker` here is the practice simulator. A pull request that adds an order path is
  declined regardless of how well gated it is; that is a different product.
- **No keys in files.** Keys live in the vault through `aitk.secrets`. Never write one into a
  recipe, a test, a settings file, a log, or a printed message. Tests assert this.
- **Official connectors only.** A broker recipe may name only a connector published by the broker
  or an aggregator on its own documentation. No password-scraping libraries.
- **The guard always applies to connectors the kit starts.** `read_only = "kit"` for every `stdio`
  and `http` recipe. If a broker's own switch exists, set it too.
- **Plain words.** Everything a person reads (wizard, errors, lessons) is written for someone who
  has never traded. No jargon without a gloss, no blame, always say what to do next.
- **Say what is not proven.** Every backtest result carries its cautions; every recipe carries the
  date its facts were checked. Do not remove either.

## Working here

- Python 3.11+, stdlib plus `keyring`. Do not add dependencies without a reason written in the PR.
- `pytest` must pass and `ruff check .` must be clean. Tests never touch the network or real
  settings files: use the `home` / `user_home` fixtures and the fake broker in `tests/`.
- Adding a broker: `docs/adding-a-broker.md`. Changing the guard: read `docs/safety-model.md` first
  and add the new tool name to `tests/test_guard.py`.
- Design intent: `docs/design.md`.
