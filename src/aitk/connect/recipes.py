"""Broker recipes: one small TOML file per broker saying how a person gets access, which OFFICIAL
connector to start, and how it is held to read-only. Adding a broker is adding a file.

A recipe never contains a key. It names the keys the wizard must ask for."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib import resources

READY, LISTED = "ready", "listed"
# How read-only is achieved, strongest first.
RO_KIT = "kit"            # the kit's guard removes every tool that can change the account
RO_BROKER = "broker"      # the broker's connector is read-only by design
RO_SIGN_IN = "sign-in"    # the person chooses read-only permissions while signing in at the broker
RO_NONE = "none"          # cannot be held to read-only; the wizard says so before continuing
READ_ONLY_MODES = (RO_KIT, RO_BROKER, RO_SIGN_IN, RO_NONE)
TRANSPORTS = ("stdio", "http", "oauth")


class RecipeError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    key: str                 # environment variable or header name the connector expects
    label: str               # what the wizard calls it
    secret: bool = True
    help: str = ""
    optional: bool = False
    default: str = ""
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Recipe:
    id: str
    name: str
    status: str
    summary: str
    assets: tuple[str, ...]
    difficulty: str
    transport: str
    read_only: str
    read_only_note: str
    docs_url: str
    checked: str             # the date the facts below were last checked against the broker's own pages
    confidence: str          # "checked" | "partly" | "unchecked"
    access_steps: tuple[str, ...] = ()
    fields: tuple[Field, ...] = ()
    command: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()            # programs that must be installed (uvx, node, kraken)
    env: dict = field(default_factory=dict)        # fixed settings, including the broker's own read-only switch
    url: str = ""
    header_fields: tuple[str, ...] = ()    # which `fields` travel as HTTP headers (http transport)
    first_run: tuple[str, ...] = ()        # a one-time command the person runs themselves (for example 2FA)
    first_run_note: str = ""
    platforms: tuple[str, ...] = ("windows", "macos", "linux")
    covers: tuple[str, ...] = ()           # other brokers reached through this one
    warning: str = ""
    advice: str = ""                       # for LISTED recipes: what to do instead
    allow_tools: tuple[str, ...] = ()      # guard overrides: tools to keep although their name looks like a change
    deny_tools: tuple[str, ...] = ()       # guard overrides: tools to remove although their name looks harmless

    @property
    def guarded(self) -> bool:
        """True when the AI app talks to the kit's guard, not to the connector directly."""
        return self.transport in ("stdio", "http")

    @property
    def server_name(self) -> str:
        return f"{self.id}-readonly" if self.read_only != RO_NONE else self.id


def _tuple(value) -> tuple:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def parse(doc: dict, source: str = "") -> Recipe:
    def need(key):
        if key not in doc or doc[key] in ("", None):
            raise RecipeError(f"{source}: missing '{key}'")
        return doc[key]

    connector = doc.get("connector", {})
    status = str(doc.get("status", READY))
    if status not in (READY, LISTED):
        raise RecipeError(f"{source}: status must be '{READY}' or '{LISTED}'")
    transport = str(connector.get("transport", ""))
    read_only = str(doc.get("read_only", RO_NONE))
    if read_only not in READ_ONLY_MODES:
        raise RecipeError(f"{source}: read_only must be one of {READ_ONLY_MODES}")
    fields = tuple(Field(key=str(f["key"]), label=str(f["label"]), secret=bool(f.get("secret", True)),
                         help=str(f.get("help", "")), optional=bool(f.get("optional", False)),
                         default=str(f.get("default", "")), choices=_tuple(f.get("choices")))
                   for f in doc.get("fields", []))
    recipe = Recipe(
        id=str(need("id")), name=str(need("name")), status=status, summary=str(need("summary")),
        assets=_tuple(doc.get("assets")), difficulty=str(doc.get("difficulty", "medium")),
        transport=transport, read_only=read_only, read_only_note=str(doc.get("read_only_note", "")),
        docs_url=str(doc.get("docs_url", "")), checked=str(doc.get("checked", "")),
        confidence=str(doc.get("confidence", "unchecked")),
        access_steps=_tuple(doc.get("access_steps")), fields=fields,
        command=_tuple(connector.get("command")), needs=_tuple(connector.get("needs")),
        env={str(k): str(v) for k, v in dict(connector.get("env", {})).items()},
        url=str(connector.get("url", "")), header_fields=_tuple(connector.get("header_fields")),
        first_run=_tuple(connector.get("first_run")), first_run_note=str(connector.get("first_run_note", "")),
        platforms=_tuple(doc.get("platforms")) or ("windows", "macos", "linux"),
        covers=_tuple(doc.get("covers")), warning=str(doc.get("warning", "")), advice=str(doc.get("advice", "")),
        allow_tools=_tuple(connector.get("allow_tools")), deny_tools=_tuple(connector.get("deny_tools")),
    )
    if status == READY:
        if transport not in TRANSPORTS:
            raise RecipeError(f"{source}: connector.transport must be one of {TRANSPORTS}")
        if transport == "stdio" and not recipe.command:
            raise RecipeError(f"{source}: a stdio connector needs connector.command")
        if transport in ("http", "oauth") and not recipe.url.startswith("https://"):
            raise RecipeError(f"{source}: connector.url must start with https://")
        if transport == "oauth" and read_only == RO_KIT:
            raise RecipeError(f"{source}: the guard cannot sit in front of a sign-in connector")
        if transport == "oauth" and fields:
            raise RecipeError(f"{source}: a sign-in connector takes no keys")
        unknown = [h for h in recipe.header_fields if h not in {f.key for f in fields}]
        if unknown:
            raise RecipeError(f"{source}: header_fields {unknown} are not in fields")
    return recipe


def load_all() -> dict[str, Recipe]:
    out: dict[str, Recipe] = {}
    folder = resources.files("aitk.connect") / "recipes"
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".toml"):
            continue
        recipe = parse(tomllib.loads(entry.read_text(encoding="utf-8")), entry.name)
        if recipe.id in out:
            raise RecipeError(f"{entry.name}: duplicate id {recipe.id}")
        if f"{recipe.id}.toml" != entry.name:
            raise RecipeError(f"{entry.name}: the file name must match id '{recipe.id}'")
        out[recipe.id] = recipe
    return out


def get(recipe_id: str) -> Recipe:
    recipes = load_all()
    try:
        return recipes[recipe_id]
    except KeyError as exc:
        raise RecipeError(f"no recipe called '{recipe_id}'. Known: {', '.join(sorted(recipes))}") from exc


def find(text: str) -> list[Recipe]:
    """Match what a person types ('fidelity', 'Schwab') to recipes, including brokers reached through another."""
    q = text.strip().lower()
    if not q:
        return []
    hits = []
    for r in load_all().values():
        names = [r.id, r.name.lower(), *[c.lower() for c in r.covers]]
        if any(q in n or n in q for n in names):
            hits.append(r)
    return sorted(hits, key=lambda r: (r.status != READY, q not in (r.id, r.name.lower()), r.name))
