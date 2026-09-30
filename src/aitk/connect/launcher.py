"""What an AI app actually starts: `python -m aitk run-connector <broker>`.

The launcher reads the broker's keys from the vault at that moment, starts the broker's official
connector (or reaches its hosted address), and puts the read-only guard in between. Because the keys
are fetched here, the AI app's own settings file never contains them.

Nothing may be printed to stdout except protocol messages: stdout IS the connection."""
from __future__ import annotations

import os
import shutil
import sys

from .. import paths, vault
from . import guard as guard_mod
from .recipes import READY, Recipe, RecipeError, get


class LaunchError(RuntimeError):
    pass


def current_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def missing_programs(recipe: Recipe, which=shutil.which) -> list[str]:
    return [n for n in recipe.needs if which(n) is None]


def collect_fields(recipe: Recipe, store) -> dict:
    """Every stored value for this broker. Raises LaunchError naming what is missing."""
    values, missing = {}, []
    for f in recipe.fields:
        value = store.get(recipe.id, f.key)
        if value in (None, ""):
            if f.optional:
                continue
            if f.default:
                value = f.default
            else:
                missing.append(f.label)
                continue
        values[f.key] = value
    if missing:
        raise LaunchError(f"{recipe.name} is missing: {', '.join(missing)}. Run 'aitk keys {recipe.id}' to enter "
                          "them.")
    return values


def resolve_command(recipe: Recipe, which=shutil.which) -> list[str]:
    program = which(recipe.command[0])
    if program is None:
        raise LaunchError(f"'{recipe.command[0]}' is not installed or not on the PATH. Run 'aitk doctor' for "
                          "how to install it.")
    return [program, *recipe.command[1:]]


def build_env(recipe: Recipe, values: dict, base: dict | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    for key, value in values.items():
        if key not in recipe.header_fields:
            env[key] = value
    env.update(recipe.env)           # the broker's own read-only switches always win
    return env


def make_guard(recipe: Recipe) -> guard_mod.Guard:
    return guard_mod.Guard(allow=frozenset(recipe.allow_tools), deny=frozenset(recipe.deny_tools))


def run(recipe_id: str, store=None, stdin=None, stdout=None, stderr=None) -> int:
    stderr = stderr if stderr is not None else sys.stderr
    try:
        recipe = get(recipe_id)
        if recipe.status != READY or not recipe.guarded:
            raise LaunchError(f"{recipe.name} is not started by the kit: it is added to your AI app by its address.")
        store = store if store is not None else vault.open_store()
        values = collect_fields(recipe, store)
        the_guard = make_guard(recipe)
        if recipe.transport == "http":
            headers = {k: v for k, v in values.items() if k in recipe.header_fields}
            return guard_mod.run_http(the_guard, recipe.url, headers, stdin, stdout, stderr)
        command = resolve_command(recipe)
        return guard_mod.run_stdio(the_guard, command, build_env(recipe, values), stdin, stdout, stderr)
    except (LaunchError, RecipeError, vault.SecretStoreError) as exc:
        stderr.write(f"ai-trading-kit: {exc}\n")
        return 2


def app_entry(recipe: Recipe, python: str | None = None) -> dict:
    """The settings an AI app needs to start this connection. It holds no key."""
    entry = {"command": python or sys.executable, "args": ["-m", "aitk", "run-connector", recipe.id]}
    custom_home = os.environ.get(paths.ENV_HOME, "").strip()
    env = {}
    if custom_home:
        env[paths.ENV_HOME] = custom_home
    if os.environ.get("AITK_SECRETS", "").strip():
        env["AITK_SECRETS"] = os.environ["AITK_SECRETS"].strip()
    if env:
        entry["env"] = env
    return entry
