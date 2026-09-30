"""The path: six steps from nothing to a tested idea, each with one command and one short lesson.

Lessons and prompts are plain Markdown files so anyone can read or improve them without Python."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

from .. import state


@dataclass(frozen=True)
class Step:
    id: str
    number: int
    title: str
    what: str
    command: str
    lesson: str
    level: str


STEPS = (
    Step("connect", 1, "Connect your broker to your AI",
         "Your AI assistant can read your balances, positions and orders. It cannot trade.",
         "aitk connect", "01-connect", "beginner"),
    Step("understand", 2, "Understand what you own",
         "Ready-made questions to ask your AI about your own account.",
         "aitk prompts", "02-understand", "beginner"),
    Step("lab", 3, "Give your AI a practice lab",
         "Your AI gets tools to test ideas and trade pretend money.",
         "aitk connect-lab", "03-lab", "beginner"),
    Step("backtest", 4, "Test an idea on history",
         "See how a simple rule would have done, against just buying and holding.",
         "aitk backtest sma_cross SPY", "04-backtest", "beginner"),
    Step("practice", 5, "Practice with pretend money",
         "Place orders, move time forward, see what fills. No real money anywhere.",
         "aitk practice start", "05-practice", "intermediate"),
    Step("own", 6, "Write and stress-test your own idea",
         "Create a strategy, try many settings, and check it on history it never saw.",
         "aitk strategy new my_idea", "06-your-own", "advanced"),
)


def steps() -> list[dict]:
    done = state.load()["done"]
    out = []
    for s in STEPS:
        out.append({"step": s, "done": s.id in done})
    return out


def next_step() -> Step | None:
    return next((row["step"] for row in steps() if not row["done"]), None)


def _read(folder: str, name: str) -> str:
    entry = resources.files("aitk.guide") / folder / f"{name}.md"
    if not entry.is_file():
        raise KeyError(name)
    return entry.read_text(encoding="utf-8")


def lesson(key: str) -> str:
    match = next((s for s in STEPS if key in (s.id, str(s.number), s.lesson)), None)
    if match is None:
        raise KeyError(key)
    return _read("lessons", match.lesson)


def prompt_names() -> list[str]:
    folder = resources.files("aitk.guide") / "prompts"
    return sorted(e.name[:-3] for e in folder.iterdir() if e.name.endswith(".md"))


def prompt(name: str) -> str:
    return _read("prompts", name)


def prompt_title(name: str) -> str:
    first = prompt(name).strip().split("\n", 1)[0]
    return first.lstrip("# ").strip()
