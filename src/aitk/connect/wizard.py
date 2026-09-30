"""The connection wizard: pick an AI app, pick a broker, follow the steps, see a test result.

It never shows a key back, never writes a key into an AI app's settings, and always says what it is
about to change and where the backup went."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .. import state, vault
from ..ui import Choice, Console
from . import apps as apps_mod
from . import doctor, launcher
from .recipes import LISTED, READY, RO_BROKER, RO_KIT, RO_NONE, RO_SIGN_IN, Recipe, find, load_all

LOCK_LABEL = {
    RO_KIT: "read-only, enforced by the kit",
    RO_BROKER: "read-only by the broker's design",
    RO_SIGN_IN: "read-only if you choose so while signing in",
    RO_NONE: "NOT read-only",
}
OTHER = "__other__"


@dataclass(frozen=True)
class Result:
    ok: bool
    broker: str = ""
    app: str = ""
    message: str = ""


def describe_lock(recipe: Recipe) -> str:
    return LOCK_LABEL[recipe.read_only]


def _usable(recipe: Recipe, app) -> tuple[bool, str]:
    if recipe.status != READY:
        return False, "not set up by the wizard yet"
    if launcher.current_platform() not in recipe.platforms:
        return False, f"its connector runs on {', '.join(recipe.platforms)} only"
    if recipe.guarded and not app.supports_local:
        return False, f"{app.name} can only use connections you sign in to"
    return True, ""


def choose_app(console: Console, preset: str | None = None):
    all_apps = apps_mod.all_apps()
    if preset:
        return apps_mod.get_app(preset)
    choices = []
    for app in all_apps.values():
        found = app.installed()
        hint = "found on this computer" if found and app.id != "chatgpt" else ""
        if app.id == "chatgpt":
            hint = "works with brokers you sign in to; the kit gives you the steps"
        elif not found:
            hint = "not found on this computer"
        choices.append(Choice(app.id, app.name, hint))
    default = next((a.id for a in all_apps.values() if a.id != "chatgpt" and a.installed()), None)
    return all_apps[console.ask_choice("Which AI app do you use?", choices, default)]


def choose_broker(console: Console, app, preset: str | None = None) -> Recipe | None:
    recipes = load_all()
    if preset:
        hits = [recipes[preset]] if preset in recipes else find(preset)
        if not hits:
            console.fail(f"No broker matches '{preset}'. Run 'aitk brokers' to see the list.")
            return None
        return _accept(console, hits[0], app)
    while True:
        choices = []
        for r in sorted(recipes.values(), key=lambda r: (r.difficulty != "easy", r.name)):
            ok, why = _usable(r, app)
            if r.status == READY and ok:
                choices.append(Choice(r.id, r.name, f"{r.summary} ({describe_lock(r)})"))
        choices.append(Choice(OTHER, "My broker is not in this list", "Type its name and see what is possible"))
        picked = console.ask_choice("Which broker do you want to connect?", choices)
        if picked != OTHER:
            return _accept(console, recipes[picked], app)
        name = console.ask_text("What is your broker called")
        hits = find(name)
        if not hits:
            console.warn(f"The kit has no recipe for '{name}'. It may offer no official connector. "
                         "SnapTrade reads many brokers without being able to trade; check if yours is covered.")
            continue
        for r in hits:
            console.title(r.name)
            console.say(r.summary)
            if r.status == LISTED:
                console.say(r.advice)
        ready = [r for r in hits if r.status == READY and _usable(r, app)[0]]
        if ready and console.ask_yes_no(f"Set up {ready[0].name} now?"):
            return _accept(console, ready[0], app)


def _accept(console: Console, recipe: Recipe, app) -> Recipe | None:
    ok, why = _usable(recipe, app)
    if not ok:
        console.title(recipe.name)
        console.say(recipe.summary)
        console.fail(f"The wizard cannot set this up with {app.name}: {why}.")
        if recipe.advice:
            console.say(recipe.advice)
        return None
    return recipe


def explain(console: Console, recipe: Recipe, yes: bool = False) -> bool:
    console.title(recipe.name)
    console.say(recipe.summary)
    console.write()
    console.say(f"Safety: {describe_lock(recipe)}.")
    console.say(recipe.read_only_note, indent=2)
    if recipe.confidence != "checked":
        console.note(f"Some details of this recipe could not be confirmed on the broker's own pages (last "
                     f"looked at {recipe.checked}). The test step below tells you whether it works.")
    if recipe.warning:
        console.write()
        console.warn(recipe.warning)
    if recipe.read_only == RO_NONE:
        console.write()
        console.warn("The kit cannot make this connection read-only.")
        return yes or console.ask_yes_no("Continue anyway?", default=False)
    return True


def ensure_programs(console: Console, recipe: Recipe) -> bool:
    while True:
        missing = launcher.missing_programs(recipe)
        if not missing:
            return True
        for name in missing:
            label, fix = doctor.INSTALL_HELP.get(name, (name, f"Install '{name}' and open a NEW terminal."))
            console.fail(f"{label} is not installed")
            console.say(fix, indent=5)
        if not console.ask_yes_no("Check again? (answer after installing, in a NEW terminal if needed)",
                                  default=False):
            console.say("Run 'aitk connect' again once it is installed. Nothing was changed.")
            return False


def collect_keys(console: Console, recipe: Recipe, store, ask_again: bool = True) -> bool:
    """Ask for the broker's keys. Stored keys are kept unless the person asks to enter them again
    (`ask_again=False` skips that question, for `--yes`)."""
    if not recipe.fields:
        return True
    have = {f.key: store.get(recipe.id, f.key) for f in recipe.fields}
    needed = [f for f in recipe.fields if not f.optional and not f.default]
    if needed and all(have[f.key] for f in needed):
        console.ok(f"Keys for {recipe.name} are already stored.")
        if not ask_again or not console.ask_yes_no("Enter them again?", default=False):
            return True
    console.title("Your keys")
    console.say(f"They are kept in {store.label}. They are not written into the project folder or into your "
                "AI app's settings, and they are never shown back.")
    for f in recipe.fields:
        if f.help:
            console.note(f.help)
        if f.choices:
            value = console.ask_choice(f.label, [Choice(c, c) for c in f.choices], f.default or None)
        elif f.secret:
            value = console.ask_secret(f.label)
        else:
            value = console.ask_text(f.label, default=f.default or None, required=not f.optional)
        if value:
            store.set(recipe.id, f.key, value)
        elif f.optional:
            store.delete(recipe.id, f.key)
    console.ok("Stored.")
    return True


def first_run(console: Console, recipe: Recipe, store, yes: bool = False, runner=subprocess.call) -> bool:
    if not recipe.first_run:
        return True
    console.title("One-time approval")
    console.say(recipe.first_run_note)
    if not (yes or console.ask_yes_no("Do it now?")):
        console.say(f"Later, run: aitk approve {recipe.id}")
        return True
    return run_first_run(console, recipe, store, runner)


def run_first_run(console: Console, recipe: Recipe, store, runner=subprocess.call) -> bool:
    try:
        values = launcher.collect_fields(recipe, store)
        command = [launcher.resolve_command(recipe)[0], *recipe.first_run[1:]]
    except launcher.LaunchError as exc:
        console.fail(str(exc))
        return False
    try:
        code = runner(command, env=launcher.build_env(recipe, values))
    except OSError as exc:
        console.fail(f"Could not start it: {exc}")
        return False
    if code != 0:
        console.fail("The approval did not finish. You can try again with: " + f"aitk approve {recipe.id}")
        return False
    console.ok("Approved.")
    return True


def show_report(console: Console, report) -> None:
    (console.ok if report.ok else console.fail)(report.message)
    if report.removed:
        console.say("Removed, so your AI cannot use them:", indent=5)
        for name, reason in report.removed[:12]:
            console.say(f"- {name} ({reason})", indent=7)
        if len(report.removed) > 12:
            console.say(f"... and {len(report.removed) - 12} more", indent=7)
    if report.fix:
        console.say(report.fix, indent=5)


def register(console: Console, recipe: Recipe, app, yes: bool = False):
    name = recipe.server_name
    console.title(f"Adding it to {app.name}")
    if recipe.guarded:
        entry = launcher.app_entry(recipe)
        preview = app.preview(name, entry)
        if preview:
            console.say("This is what will be added. It holds no key:")
            console.raw(preview)
        if app.existing(name) is not None:
            console.note(f"A connection called '{name}' already exists in {app.name} and will be replaced.")
        if not (yes or console.ask_yes_no("Add it?")):
            console.say("Nothing was changed.")
            return None
        return app.add_local(name, entry)
    return app.add_remote(name, recipe.url)


def show_outcome(console: Console, outcome) -> None:
    (console.ok if outcome.done else console.say)(outcome.summary)
    if outcome.backup:
        console.note(f"Your previous settings were copied to {outcome.backup}")
    if outcome.steps:
        console.write()
        console.steps(outcome.steps)
    if outcome.restart:
        console.write()
        console.say(outcome.restart)


FIRST_QUESTIONS = (
    "What do I own right now, and how much is each position worth?",
    "Which of my positions is the largest share of my account?",
    "Show my open orders and explain what each one will do.",
)


def run(console: Console, broker: str | None = None, app_id: str | None = None, yes: bool = False,
        skip_test: bool = False, store=None) -> Result:
    console.title("Connect your broker to your AI")
    console.say("This sets up a connection that lets your AI assistant READ your account: balances, positions, "
                "orders and prices. Where the kit is in control, the connection cannot place, change or cancel "
                "an order. The wizard tells you plainly when a broker cannot be held to that.")
    console.note("Type q at any question to stop. Nothing is changed until the last step.")

    app = choose_app(console, app_id)
    recipe = choose_broker(console, app, broker)
    if recipe is None:
        return Result(False, message="no broker chosen")
    if not explain(console, recipe, yes):
        console.say("Stopped. Nothing was changed.")
        return Result(False, recipe.id, app.id, "declined")
    if not ensure_programs(console, recipe):
        return Result(False, recipe.id, app.id, "a needed program is missing")

    console.title("Getting access")
    console.steps(recipe.access_steps)
    if recipe.docs_url:
        console.note(f"The broker's own guide: {recipe.docs_url}")
    if not yes:
        console.pause()

    store = store if store is not None else vault.open_store()
    collect_keys(console, recipe, store, ask_again=not yes)
    first_run(console, recipe, store, yes)

    if not skip_test:
        console.title("Testing the connection")
        if recipe.needs and "uvx" in recipe.needs:
            console.note("The first test downloads the broker's connector, which can take a minute.")
        report = doctor.check_connection(recipe, store)
        show_report(console, report)
        if not report.ok and not (yes or console.ask_yes_no("Add it to your AI app anyway?", default=False)):
            console.say("Nothing was added. Fix the problem above, then run 'aitk connect' again. "
                        "Your keys stay stored.")
            return Result(False, recipe.id, app.id, report.message)

    try:
        outcome = register(console, recipe, app, yes)
    except apps_mod.AppError as exc:
        console.fail(str(exc))
        return Result(False, recipe.id, app.id, str(exc))
    if outcome is None:
        return Result(False, recipe.id, app.id, "declined")
    show_outcome(console, outcome)
    state.add_connection(recipe.id, app.id, recipe.server_name, {"read_only": recipe.read_only})
    state.mark_done("connect")

    console.title("Try it")
    console.say(f"In {app.name}, ask:")
    for q in FIRST_QUESTIONS:
        console.say(f'"{q}"', indent=2)
    console.write()
    console.say("Next: run 'aitk' to see the whole path, or 'aitk check' any time to re-test your connections.")
    return Result(True, recipe.id, app.id, outcome.summary)
