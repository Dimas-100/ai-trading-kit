# Design: ai-trading-kit

*Decided 2026-09-29. This records why the kit is shaped the way it is, so later changes can be
checked against the intent.*

## Purpose

Give other people the chance to build, in hours, what the author built over months: a brokerage
account an AI assistant can read, a way to test trading ideas honestly, and a place to practice
without risking money. Beginners get a path; experienced people get tooling that respects the
statistics of backtesting.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Scope of the first release | Read-only connections and pretend-money practice; no real orders | Safe to hand to strangers; the useful part for most people |
| Brokers | As many as have an official connector, through the broker's own connector | Brokers maintain the connection code; the kit configures and guards |
| Unofficial libraries | Never | They log in with the person's password and break most brokers' terms |
| Read-only | The kit's own guard in front of every connector it starts, plus the broker's own switch | A stranger's account must not be changed by a wrong tool call; two independent locks |
| AI apps | Claude Desktop, Claude Code, Cursor (written for you), ChatGPT (steps) | The apps people who clone a repo use; each is one adapter |
| Interface | A terminal wizard with numbered questions | Works everywhere, needs nothing else installed, testable with a script |
| Keys | OS password vault; a private file when no vault exists | Never in the repo, never in an AI app's settings file |
| Dependencies | `keyring` only; MCP client and server written in the kit | A small surface a person can read; nothing to break on install |
| Practice account | Its own calendar in the past that the person advances | A month of decisions in ten minutes; fills at the next day's prices |
| Backtest honesty | Buy-and-hold on every report; a sweep that chooses on the first part of history and judges on the last | Overfitting is the beginner's main trap; the tooling should make it visible |
| Where it lives | Its own repository, not inside the author's live trading system | Different goal, almost no shared code, and a real-money folder should not host unrelated work |

## The stages beyond this release

The path has seven steps, all of which ship (step 7, the project folder, was added on 2026-09-30). Two possible later stages were deliberately left out:
live orders behind rails (dry-run, caps, typed confirmation) and scheduled automation with a
watchdog and kill switch. Each would need its own design and security review, and a person should
have finished the path before either is offered.

## Components

- **Recipes** (`connect/recipes/*.toml`): data, one per broker. Adding a broker is adding a file.
- **Guard** (`connect/guard.py`): pure decision logic plus two transports (stdio child process,
  streamable HTTP with header keys).
- **Launcher** (`connect/launcher.py`): what the AI app starts; fetches keys from the vault.
- **Apps** (`connect/apps.py`): one adapter per AI app; JSON file apps back up before writing.
- **Doctor** (`connect/doctor.py`): starts a connector the way the app will and reports the tool split.
- **Wizard** (`connect/wizard.py`): the conversation; everything it asks goes through `ui.Console`.
- **Engine** (`engine/`): vendored from the author's `trading-rails`: models, one fill model shared
  by practice and backtest, indicators, strategies, the paper broker.
- **Lab** (`lab.py`): reports with verdicts, comparison, the split sweep.
- **Practice** (`practice.py`): the account with a calendar.
- **Prices** (`prices.py`): files on disk, demo prices, downloads with the person's own free key.
- **Lab server** (`mcp/lab_server.py`): the kit's own MCP connector for AI assistants.
- **Guide** (`guide/`): steps, lessons, prompts, progress.

## Testing

No test touches the network or a real settings file: every test runs against a temporary kit home
and a temporary user home. A fake broker connector (`tests/fake_broker_mcp.py`) stands in for real
ones; the guard, the launcher and the doctor are tested end to end through real subprocesses and a
local HTTP server. The lab server was also registered in Claude Code for real and reported
"Connected". Three real connectors (Alpaca, Public, Webull) were started with dummy keys to confirm
the package names, the tool lists and the guard's decisions.
