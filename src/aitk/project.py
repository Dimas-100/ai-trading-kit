"""A project folder: the person's own trading project, the way a serious hobbyist keeps one.

`aitk init NAME` creates a folder that holds the plan they trade by, a journal of decisions, their
strategy files, and (ignored by git) their prices and practice account. The folder is also the kit's
home while they work inside it, so nothing is scattered. An AI opened in the folder finds AGENTS.md
and knows what the place is for."""
from __future__ import annotations

import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path

MARKER = "aitk-project.toml"


class ProjectError(ValueError):
    pass


def find(start: Path | None = None) -> Path | None:
    """The nearest enclosing project folder, or None."""
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / MARKER).is_file():
            return folder
    return None


def _files(name: str) -> dict[str, str]:
    today = date.today().isoformat()
    title = name.replace("-", " ").replace("_", " ").strip().title() or "My Trading Project"
    return {
        MARKER: f'# Marks this folder as an ai-trading-kit project. The kit uses it as its home while you work here.\n'
                f'name = "{name}"\ncreated = "{today}"\nkit = "ai-trading-kit"\n',
        "README.md": f"""# {title}

My trading project, built with [ai-trading-kit](https://github.com/Dimas-100/ai-trading-kit).

| What | Where |
|---|---|
| The rules I trade by | `plan.md` |
| Why I made each decision | `journal.md` |
| My strategy files | `strategies/` |
| Price history and the practice account | `prices/`, `practice/` (not committed) |

Work here with `aitk` (it finds this folder on its own) or by opening the folder in an AI app that
has the kit's lab connected. Practice money only: nothing in this folder can place a real order.
""",
        "plan.md": f"""# Plan

*Started {today}. Change this file on purpose, at a review, never in the middle of a trade.*

## Goal

What I want from this, in one sentence. (Example: learn whether a simple rule can beat holding an
index fund, using pretend money for at least six months before any of it is real.)

## The rule

- **Buy when:**
- **Sell when:**
- **Safety net (stop):** a set percent below the entry, placed the same day I buy.
- **Size:** at most ___ % of the account in one position; at most ___ positions.

## What I will not do

- Buy anything I have not written a sell rule for.
- Change the rule because of one trade.
- Move to real money before the review below says so.

## Review

After 20 closed practice trades or three months, whichever comes first: compare against simply
holding (`aitk practice report`), read the journal, and decide whether the rule earned its keep.
""",
        "journal.md": f"""# Journal

One entry per decision or per week. Say what you did, why, and what would make you change your mind.
Your AI can add entries for you (ask it to "log this").

## {today}

Started the project.
""",
        "AGENTS.md": """# For AI assistants working in this folder

This is a personal trading project made with ai-trading-kit. Practice money only: nothing here can
place a real order, and you must not add anything that could.

- `plan.md` holds the rules the person trades by. Read it before suggesting a trade or a change.
  Suggest changes to the plan only at a review, and say so.
- `journal.md` is the record of decisions. When the person decides something, add a dated entry
  (the lab's `journal_add` tool does this) with what, why, and what would change their mind.
- `strategies/` holds strategy files. Write new ones with the lab's `save_strategy` tool; it checks
  and test-runs the code first. Backtest before and after any change and report honestly, including
  the reality check.
- Never ask the person to paste an API key or secret into the chat. Keys are typed only into the
  `aitk` wizard in their own terminal.
- Nothing you say is financial advice. Say what the numbers show and what they cannot show.
""",
        "CLAUDE.md": "Read `AGENTS.md`: it holds the rules for any AI assistant working in this folder.\n",
        ".gitignore": """# personal data and anything with a key stays out of git
prices/
practice/
reports/
backups/
state.json
keys.json
.env
*.log
__pycache__/
""",
    }


def create(name: str, parent: Path | None = None, here: bool = False, git: bool = True) -> dict:
    name = str(name).strip()
    if not name or any(c in name for c in '\\/:*?"<>|'):
        raise ProjectError("give the project a simple folder name, for example my-trading")
    folder = (parent or Path.cwd()).resolve() if here else (parent or Path.cwd()).resolve() / name
    if find(folder) is not None:
        raise ProjectError(f"{find(folder)} is already an ai-trading-kit project")
    if not here and folder.exists() and any(folder.iterdir()):
        raise ProjectError(f"{folder} already exists and is not empty")
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for rel, text in _files(name).items():
        target = folder / rel
        if target.exists():
            continue
        target.write_text(text, encoding="utf-8")
        written.append(rel)
    (folder / "strategies").mkdir(exist_ok=True)
    note = folder / "strategies" / "README.md"
    if not note.exists():
        note.write_text("Strategy files live here, one per idea. `aitk strategy new NAME` writes a template; with the "
                        "lab connected your AI can write and save one from a description.\n", encoding="utf-8")
        written.append("strategies/README.md")
    git_done = False
    if git and shutil.which("git"):
        try:
            if not (folder / ".git").exists():
                subprocess.run(["git", "init", "-q"], cwd=folder, check=True, capture_output=True, timeout=30)
            subprocess.run(["git", "add", "-A"], cwd=folder, check=True, capture_output=True, timeout=30)
            commit = ["git", "commit", "-q", "-m", "Start my trading project"]
            done = subprocess.run(commit, cwd=folder, capture_output=True, timeout=30)
            if done.returncode != 0:            # no git identity on this computer yet: commit as the kit
                subprocess.run(["git", "-c", "user.name=ai-trading-kit", "-c", "user.email=kit@localhost", *commit[1:]],
                               cwd=folder, check=True, capture_output=True, timeout=30)
            git_done = True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            git_done = False
    return {"folder": str(folder), "written": written, "git": git_done}


def journal_add(folder: Path, text: str, title: str = "") -> Path:
    text = str(text).strip()
    if not text:
        raise ProjectError("the entry is empty")
    f = folder / "journal.md"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    heading = f"## {stamp}" + (f" — {title.strip()}" if title.strip() else "")
    existing = f.read_text(encoding="utf-8") if f.exists() else "# Journal\n"
    f.write_text(existing.rstrip("\n") + f"\n\n{heading}\n\n{text}\n", encoding="utf-8")
    return f


def read_notes(folder: Path, journal_entries: int = 5) -> dict:
    plan = (folder / "plan.md").read_text(encoding="utf-8") if (folder / "plan.md").exists() else ""
    journal = (folder / "journal.md").read_text(encoding="utf-8") if (folder / "journal.md").exists() else ""
    entries = [e for e in journal.split("\n## ") if e.strip()]
    head, rest = (entries[0], entries[1:]) if entries and not journal.startswith("## ") else ("", entries)
    recent = ["## " + e.strip() for e in rest[-journal_entries:]]
    return {"folder": str(folder), "plan": plan, "recent_journal": recent, "journal_entries": len(rest)}
