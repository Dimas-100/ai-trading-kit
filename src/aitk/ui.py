"""Everything the kit says and asks goes through a `Console`, so the wizard can be driven by a person at
a terminal or by a script in a test, and so plain text is all any terminal needs to support.

Questions are numbered lists: they work over SSH, in every Windows terminal and with screen readers."""
from __future__ import annotations

import getpass
import os
import sys
import textwrap
from dataclasses import dataclass


class Cancelled(Exception):
    """The person chose to stop (Ctrl+C, end of input, or typed 'q')."""


def _color_ok(stream) -> bool:
    if os.environ.get("NO_COLOR") or os.environ.get("AITK_NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


_CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "blue": "34", "cyan": "36"}


@dataclass(frozen=True)
class Choice:
    value: str
    label: str
    hint: str = ""


class Console:
    """Terminal console. `width` wraps long lines so they stay readable in a narrow window."""

    def __init__(self, stdin=None, stdout=None, width: int = 88, color: bool | None = None):
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.width = width
        self.color = _color_ok(self.stdout) if color is None else color

    # ── output ────────────────────────────────────────────────────────────────
    def style(self, text: str, *names: str) -> str:
        if not self.color or not names:
            return text
        return f"\033[{';'.join(_CODES[n] for n in names)}m{text}\033[0m"

    def write(self, text: str = "") -> None:
        try:
            self.stdout.write(text + "\n")
        except UnicodeEncodeError:   # a legacy Windows code page: degrade, never crash
            enc = getattr(self.stdout, "encoding", None) or "ascii"
            self.stdout.write(text.encode(enc, "replace").decode(enc) + "\n")
        self.stdout.flush()

    def say(self, text: str = "", indent: int = 0) -> None:
        pad = " " * indent
        for para in str(text).split("\n"):
            if not para.strip():
                self.write()
                continue
            for line in textwrap.wrap(para, self.width - indent, break_long_words=False,
                                      break_on_hyphens=False) or [""]:
                self.write(pad + line)

    def raw(self, text: str) -> None:
        """Print exactly as given (commands, paths, tables): wrapping would break a copy and paste."""
        for line in str(text).split("\n"):
            self.write(line)

    def title(self, text: str) -> None:
        self.write()
        self.write(self.style(text, "bold", "cyan"))
        self.write(self.style("-" * min(len(text), self.width), "dim"))

    def ok(self, text: str) -> None:
        self.say(self.style("[ok] ", "green") + text)

    def warn(self, text: str) -> None:
        self.say(self.style("[!]  ", "yellow") + text)

    def fail(self, text: str) -> None:
        self.say(self.style("[x]  ", "red") + text)

    def note(self, text: str) -> None:
        self.say(self.style(text, "dim"))

    def steps(self, items) -> None:
        for i, item in enumerate(items, 1):
            lines = textwrap.wrap(str(item), self.width - 5, break_long_words=False, break_on_hyphens=False)
            for j, line in enumerate(lines or [""]):
                self.write((f"{i:>3}. " if j == 0 else "     ") + line)

    def table(self, headers, rows) -> None:
        rows = [[str(c) for c in r] for r in rows]
        widths = [max(len(str(h)), *(len(r[i]) for r in rows)) if rows else len(str(h))
                  for i, h in enumerate(headers)]
        self.write("  ".join(self.style(str(h).ljust(w), "bold") for h, w in zip(headers, widths)))
        self.write("  ".join("-" * w for w in widths))
        for r in rows:
            self.write("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())

    # ── input ─────────────────────────────────────────────────────────────────
    def _readline(self, prompt: str) -> str:
        self.stdout.write(prompt)
        self.stdout.flush()
        try:
            line = self.stdin.readline()
        except KeyboardInterrupt as exc:
            self.write()
            raise Cancelled() from exc
        if line == "":
            raise Cancelled()
        return line.rstrip("\r\n")

    def ask_text(self, question: str, default: str | None = None, required: bool = True) -> str:
        suffix = f" [{default}]" if default else ""
        while True:
            answer = self._readline(f"{question}{suffix}: ").strip()
            if answer.lower() == "q":
                raise Cancelled()
            if not answer and default is not None:
                return default
            if answer or not required:
                return answer
            self.warn("This one is needed. Type q to stop.")

    def ask_secret(self, question: str) -> str:
        """Hidden when a real terminal is attached; read plainly from a pipe (tests, automation).
        Some Windows terminals drop a paste into a hidden prompt, so an empty answer offers visible input."""
        hidden = self.stdin is sys.stdin and sys.stdin.isatty() and not os.environ.get("AITK_SHOW_SECRETS")
        while True:
            if hidden:
                try:
                    answer = getpass.getpass(f"{question} (hidden as you type): ")
                except (KeyboardInterrupt, EOFError) as exc:
                    self.write()
                    raise Cancelled() from exc
            else:
                answer = self._readline(f"{question}: ")
            answer = answer.strip()
            if answer:
                return answer
            if hidden:
                self.warn("Nothing was entered. Some terminals cannot paste into a hidden prompt.")
                if self.ask_yes_no("Show what you type for this one instead?", default=True):
                    hidden = False
                    self.note("Clear the screen afterwards if someone can see it (type cls or clear).")
            else:
                self.warn("Nothing was entered. Paste the value, then press Enter.")

    def ask_yes_no(self, question: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        while True:
            answer = self._readline(f"{question} [{hint}]: ").strip().lower()
            if not answer:
                return default
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            if answer == "q":
                raise Cancelled()
            self.warn("Please answer y or n.")

    def ask_choice(self, question: str, choices: list[Choice], default: str | None = None) -> str:
        self.write()
        self.say(self.style(question, "bold"))
        for i, c in enumerate(choices, 1):
            self.write(f"  {i:>2}. {c.label}")
            if c.hint:
                for line in textwrap.wrap(c.hint, self.width - 8, break_long_words=False, break_on_hyphens=False):
                    self.write(self.style(f"      {line}", "dim"))
        default_no = next((i for i, c in enumerate(choices, 1) if c.value == default), None)
        suffix = f" [{default_no}]" if default_no else ""
        while True:
            answer = self._readline(f"Type a number{suffix}, or q to stop: ").strip().lower()
            if not answer and default_no:
                return choices[default_no - 1].value
            if answer == "q":
                raise Cancelled()
            if answer.isdigit() and 1 <= int(answer) <= len(choices):
                return choices[int(answer) - 1].value
            match = [c for c in choices if c.value.lower() == answer]
            if match:
                return match[0].value
            self.warn(f"Type a number from 1 to {len(choices)}.")

    def pause(self, text: str = "Press Enter when you are ready to continue") -> None:
        self._readline(f"{text}... ")
