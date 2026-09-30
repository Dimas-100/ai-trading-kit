"""The `aitk` command. Run it with no arguments to see the path and where you are on it."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__, guide, lab, paths, practice, prices, state, strategies, vault
from .connect import apps as apps_mod
from .connect import doctor, launcher, wizard
from .connect.recipes import LISTED, READY, RecipeError, find, get, load_all
from .ui import Cancelled, Choice, Console

LAB_NAME = "ai-trading-kit-lab"


# ── helpers ───────────────────────────────────────────────────────────────────
def _pct(v) -> str:
    return "" if v is None else f"{v:+.2f}%"


def _money(v) -> str:
    return f"${v:,.2f}"


def _print_report(console: Console, report: lab.Report, show_trades: bool, kind: str) -> None:
    m = report.metrics
    console.title(f"{report.strategy} on {report.symbol}  ({report.first} to {report.last})")
    if report.params:
        console.note("settings: " + ", ".join(f"{k}={v}" for k, v in report.params.items()))
    if kind == prices.DEMO:
        console.warn("These are made-up DEMO prices. Run 'aitk prices get "
                     f"{report.symbol}' for real history.")
    console.table(["what", "value"], [
        ["the rule made", _pct(m["total_return_pct"])],
        ["buying and holding made", _pct(m["buy_hold_return_pct"])],
        ["worst fall from a peak", _pct(m["max_drawdown_pct"])],
        ["yearly rate", _pct(m["cagr_pct"])],
        ["closed trades", m["trades"]],
        ["winning trades", f"{m['win_rate_pct']:.0f}%"],
        ["average trade", _pct(m["avg_return_pct"])],
        ["best / worst trade", f"{_pct(m['best_trade_pct'])} / {_pct(m['worst_trade_pct'])}"],
        ["stopped out", m["stopped_out"]],
        ["time in the market", f"{m['exposure_pct']:.0f}%"],
        ["started with / ended with", f"{_money(m['starting_cash'])} / {_money(m['final_value'])}"],
    ])
    console.write()
    for line in report.verdict:
        console.say(f"- {line}")
    if show_trades and report.trades:
        console.write()
        console.table(["entered", "exited", "in", "out", "shares", "result", "why"],
                      [[t["entry_ts"], t["exit_ts"], f"{t['entry_price']:.2f}", f"{t['exit_price']:.2f}",
                        t["quantity"], _pct(t["return_pct"]), t["reason"]] for t in report.trades])


def _bars_for(console: Console, book: prices.PriceBook, symbol: str, years: float | None):
    symbol = prices.clean_symbol(symbol)
    bars = book.all_bars(symbol)
    if years:
        bars = bars[-int(years * 252):]
    return symbol, bars, book.kind(symbol)


# ── commands ──────────────────────────────────────────────────────────────────
def cmd_home(args, console: Console) -> int:
    console.title("ai-trading-kit")
    console.say("Connect your broker to your AI, then learn to test and practice ideas with pretend money. "
                "Nothing here places a real order.")
    rows = guide.steps()
    console.write()
    for row in rows:
        s = row["step"]
        mark = console.style("done", "green") if row["done"] else "    "
        console.write(f"  [{mark}] {s.number}. {s.title}")
        console.say(s.what, indent=12)
        console.note(f"            {s.command}")
    nxt = guide.next_step()
    done = sum(1 for r in rows if r["done"])
    console.write()
    console.say(console.style(f"{done} of {len(rows)} steps done.", "bold") if done else
                console.style("Welcome. Nothing is set up yet; step 1 takes about five minutes.", "bold"))
    if nxt:
        console.say(f"Next for you: step {nxt.number}. Run: {nxt.command}   (lesson: aitk lesson {nxt.number})")
    else:
        console.say("Every step is done. Keep testing ideas, and keep them in pretend money until you are sure.")
    console.note("Anything wrong? Run: aitk check")
    if not args.menu or not sys.stdin.isatty():
        return 0
    choices = [Choice(str(r["step"].number), f"{r['step'].title}  ->  {r['step'].command}") for r in rows]
    picked = console.ask_choice("Which step do you want to read about?", choices, str(nxt.number) if nxt else None)
    console.raw(guide.lesson(picked))
    return 0


def cmd_connect(args, console: Console) -> int:
    result = wizard.run(console, broker=args.broker, app_id=args.app, yes=args.yes, skip_test=args.skip_test)
    return 0 if result.ok else 1


def cmd_connect_lab(args, console: Console) -> int:
    console.title("Give your AI the practice lab")
    console.say("The lab lets your AI test ideas on price history and trade a pretend-money account on this "
                "computer. It has no connection to any broker.")
    app = wizard.choose_app(console, args.app)
    if not app.supports_local:
        console.fail(f"{app.name} cannot start a program on your computer, so it cannot use the lab. "
                     "Use Claude Desktop, Claude Code or Cursor for the lab.")
        return 1
    program, program_args = paths.kit_command("lab")
    entry = {"command": program, "args": program_args}
    home = paths.home()
    import os
    if os.environ.get(paths.ENV_HOME):
        entry["env"] = {paths.ENV_HOME: str(home)}
    preview = app.preview(LAB_NAME, entry)
    if preview:
        console.say("This is what will be added:")
        console.raw(preview)
    if not (args.yes or console.ask_yes_no("Add it?")):
        console.say("Nothing was changed.")
        return 1
    try:
        outcome = app.add_local(LAB_NAME, entry)
    except apps_mod.AppError as exc:
        console.fail(str(exc))
        return 1
    wizard.show_outcome(console, outcome)
    if outcome.done:
        state.add_connection("lab", app.id, LAB_NAME)
        state.mark_done("lab")
        console.title("Try it")
        console.say(f'In {app.name}, ask: "List the strategies you can test, then backtest sma_cross on SPY and '
                    'tell me honestly whether it beat buying and holding."')
    return 0 if outcome.done else 1


def cmd_disconnect(args, console: Console) -> int:
    app = apps_mod.get_app(args.app)
    name = LAB_NAME if args.broker == "lab" else get(args.broker).server_name
    outcome = app.remove(name)
    wizard.show_outcome(console, outcome)
    state.remove_connection(args.broker, app.id)
    return 0


def cmd_check(args, console: Console) -> int:
    console.title("Checking")
    conns = state.load()["connections"]
    wanted = [c for c in conns if c["broker"] != "lab"]
    recipes = [get(c["broker"]) for c in wanted if c["broker"] in load_all()]
    problems = 0
    for c in doctor.environment(recipes or [], ):
        (console.ok if c.ok else console.fail)(c.title + (f": {c.detail}" if c.detail and not c.ok else ""))
        if not c.ok:
            problems += 1
            console.say(c.fix, indent=5)
    if not conns:
        console.say("No connections yet. Run: aitk connect")
        return 0
    store = vault.open_store()
    for c in conns:
        app = apps_mod.all_apps().get(c["app"])
        label = f"{c['broker']} in {app.name if app else c['app']}"
        console.write()
        console.say(console.style(label, "bold"))
        if app and app.existing(c["server_name"]) is None and app.id != "chatgpt":
            console.fail(f"'{c['server_name']}' is no longer in {app.name}'s settings.")
            console.say(f"Run: aitk connect --broker {c['broker']} --app {app.id}", indent=5)
            problems += 1
        if c["broker"] == "lab":
            console.ok("The practice lab needs no keys.")
            continue
        recipe = get(c["broker"])
        k = doctor.check_keys(recipe, store)
        (console.ok if k.ok else console.fail)(k.title + (f": {k.detail}" if not k.ok else ""))
        if not k.ok:
            problems += 1
            continue
        report = doctor.check_connection(recipe, store)
        wizard.show_report(console, report)
        if not report.ok:
            problems += 1
    console.write()
    if problems:
        console.say(f"{problems} thing(s) need attention, listed above.")
    else:
        console.ok("Everything works.")
    return 1 if problems else 0


def cmd_brokers(args, console: Console) -> int:
    if args.name:
        hits = find(args.name)
        if not hits:
            console.say(f"No recipe matches '{args.name}'. The broker may offer no official connector; SnapTrade "
                        "may still read it. Run 'aitk brokers' for the full list.")
            return 1
        for r in hits:
            console.title(r.name)
            console.say(r.summary)
            console.say(f"Safety: {wizard.describe_lock(r)}. {r.read_only_note}")
            if r.warning:
                console.warn(r.warning)
            if r.status == LISTED:
                console.say(r.advice)
            elif r.access_steps:
                console.say("Getting access:")
                console.steps(r.access_steps)
            if r.docs_url:
                console.note(f"Broker's guide: {r.docs_url}   (details checked {r.checked}: {r.confidence})")
            if r.status == READY:
                console.say(f"Set it up: aitk connect --broker {r.id}")
        return 0
    rows = []
    for r in sorted(load_all().values(), key=lambda r: (r.status != READY, r.difficulty != "easy", r.name)):
        rows.append([r.id, r.name, "ready" if r.status == READY else "info only", r.difficulty,
                     wizard.describe_lock(r), ", ".join(r.assets)])
    console.table(["id", "broker", "wizard", "effort", "safety", "assets"], rows)
    console.write()
    console.say("Details: aitk brokers <id or name>.   Set one up: aitk connect")
    return 0


def cmd_apps(args, console: Console) -> int:
    rows = [[a.id, a.name, "yes" if a.installed() else "no", "yes" if a.supports_local else "sign-in brokers only"]
            for a in apps_mod.all_apps().values()]
    console.table(["id", "app", "found here", "local connections"], rows)
    return 0


def cmd_keys(args, console: Console) -> int:
    recipe = get(args.broker)
    store = vault.open_store()
    if args.forget:
        n = sum(1 for f in recipe.fields if store.delete(recipe.id, f.key))
        console.ok(f"Removed {n} stored value(s) for {recipe.name}.")
        return 0
    if not recipe.fields:
        console.say(f"{recipe.name} needs no keys: you sign in at the broker from your AI app.")
        return 0
    wizard.collect_keys(console, recipe, store, ask_again=True)
    return 0


def cmd_approve(args, console: Console) -> int:
    recipe = get(args.broker)
    if not recipe.first_run:
        console.say(f"{recipe.name} needs no one-time approval.")
        return 0
    return 0 if wizard.run_first_run(console, recipe, vault.open_store()) else 1


def cmd_run_connector(args, console: Console) -> int:
    return launcher.run(args.broker)


def cmd_lab(args, console: Console) -> int:
    from .mcp import lab_server
    return lab_server.main()


def cmd_prices(args, console: Console) -> int:
    store = vault.open_store()
    if args.prices_cmd == "list":
        have = prices.downloaded()
        if not have:
            console.say("No price files yet. Everything uses made-up demo prices until you run: aitk prices get SPY")
        else:
            console.say("Price files: " + ", ".join(have))
            console.note(f"Folder: {paths.prices_dir()}")
        provider = prices.available_provider(store)
        console.say(f"Provider with a stored key: {provider or 'none (run: aitk prices key)'}")
        return 0
    if args.prices_cmd == "key":
        provider = args.provider
        if not provider:
            choices = [Choice(k, v["name"], v["note"]) for k, v in prices.PROVIDERS.items()]
            provider = console.ask_choice("Where should prices come from?", choices, "tiingo")
        info = prices.PROVIDERS[provider]
        console.say(f"Get a free key: {info['signup']}")
        for key, label in info["fields"]:
            store.set(info["store_as"], key, console.ask_secret(label))
        console.ok(f"Stored in {store.label}. Now run: aitk prices get SPY")
        return 0
    if args.prices_cmd == "get":
        for symbol in args.symbols:
            try:
                path, n, provider = prices.download(symbol, store, provider=args.provider, years=args.years)
            except prices.PriceError as exc:
                console.fail(f"{symbol}: {exc}")
                return 1
            console.ok(f"{prices.clean_symbol(symbol)}: {n} days from {prices.PROVIDERS[provider]['name']} -> {path}")
        return 0
    if args.prices_cmd == "import":
        path, n = prices.import_csv(args.file, args.symbol)
        console.ok(f"{n} days imported -> {path}")
        return 0
    return 1


def cmd_strategies(args, console: Console) -> int:
    rows = [[d["name"], d["level"], ", ".join(f"{k}={v}" for k, v in d["settings"].items()) or "-", d["summary"]]
            for d in strategies.describe()]
    console.table(["name", "level", "settings (defaults)", "what it does"], rows)
    for fname, err in strategies.load_errors.items():
        console.fail(f"{fname} could not be loaded: {err}")
    console.note(f"Your own strategies live in {paths.strategies_dir()}   (create one: aitk strategy new NAME)")
    return 0


def cmd_strategy_new(args, console: Console) -> int:
    if args.strategy_cmd == "show":
        console.raw(strategies.read(args.name))
        return 0
    path = strategies.create(args.name)
    console.ok(f"Created {path}")
    console.say("Open it, change the rule, then run: aitk backtest " + args.name + " SPY")
    console.note("Or describe the idea to your AI: with the lab connected it can write and save the file itself.")
    return 0


def cmd_backtest(args, console: Console) -> int:
    book = prices.PriceBook()
    symbol, bars, kind = _bars_for(console, book, args.symbol, args.years)
    report = lab.evaluate(args.strategy, bars, symbol=symbol, params=strategies.parse_settings(args.set),
                          starting_cash=args.cash)
    if args.json:
        console.raw(json.dumps({**report.as_dict(), "prices": kind}, indent=2))
    else:
        _print_report(console, report, args.trades, kind)
    if args.save:
        folder = paths.ensure(paths.reports_dir())
        target = folder / f"{report.last}-{report.strategy}-{symbol}.json"
        target.write_text(json.dumps({**report.as_dict(), "prices": kind}, indent=2), encoding="utf-8")
        console.note(f"Saved to {target}")
    state.mark_done("backtest")
    return 0


def cmd_compare(args, console: Console) -> int:
    book = prices.PriceBook()
    symbol, bars, kind = _bars_for(console, book, args.symbol, args.years)
    rows = lab.compare(strategies.names(), bars, symbol=symbol)
    console.title(f"Every strategy on {symbol}  ({bars[0].ts} to {bars[-1].ts})")
    if kind == prices.DEMO:
        console.warn(f"These are made-up DEMO prices. Run 'aitk prices get {symbol}' for real history.")
    console.table(["strategy", "made", "buy & hold", "worst fall", "trades", "wins", "in market"],
                  [[r.strategy, _pct(r.metrics["total_return_pct"]), _pct(r.metrics["buy_hold_return_pct"]),
                    _pct(r.metrics["max_drawdown_pct"]), r.metrics["trades"], f"{r.metrics['win_rate_pct']:.0f}%",
                    f"{r.metrics['exposure_pct']:.0f}%"] for r in rows])
    console.note("Ranked by what each made on this one history. The order can flip on another symbol or period.")
    state.mark_done("backtest")
    return 0


def cmd_sweep(args, console: Console) -> int:
    book = prices.PriceBook()
    symbol, bars, kind = _bars_for(console, book, args.symbol, args.years)
    result = lab.sweep(args.strategy, bars, strategies.parse_grid(args.settings), symbol=symbol,
                       train_fraction=args.first_part)
    if args.json:
        console.raw(json.dumps({**result.as_dict(), "prices": kind}, indent=2))
        return 0
    console.title(f"{args.strategy} on {symbol}: {result.tried} settings, chosen before {result.split_at}")
    if kind == prices.DEMO:
        console.warn("These are made-up DEMO prices.")
    console.table(["settings", "first part", "trades", "unseen part", "trades", "buy & hold (unseen)"],
                  [[", ".join(f"{k}={v}" for k, v in r["params"].items()), _pct(r["first_return_pct"]),
                    r["first_trades"], _pct(r["last_return_pct"]), r["last_trades"], _pct(r["last_buy_hold_pct"])]
                   for r in result.rows[:args.show]])
    console.write()
    for line in result.verdict:
        console.say(f"- {line}")
    state.mark_done("own" if args.strategy not in ("sma_cross", "rsi2", "donchian", "buy_hold") else "backtest")
    return 0


def cmd_practice(args, console: Console) -> int:
    acct = practice.Practice()
    sub = args.practice_cmd
    if sub == "scenarios":
        console.title("Starting points worth living through")
        console.table(["name", "starts", "why"], [[k, v[0], v[1]] for k, v in practice.SCENARIOS.items()])
        console.say("Start one: aitk practice start --scenario 2022-bear   (needs real prices: aitk prices get SPY)")
        return 0
    if sub == "report":
        rep = acct.report()
        console.title(f"Report card   {rep['started_on']} to {rep['today']}"
                      + (f"   scenario: {rep['scenario']}" if rep["scenario"] else ""))
        if rep["scenario_note"]:
            console.note(rep["scenario_note"])
        console.table(["you", f"holding {rep['hold_symbol']}", "account value", "fills", "trading days"],
                      [[_pct(rep["you_pct"]), _pct(rep["hold_pct"]), _money(rep["account_value"]), rep["fills"],
                        rep["trading_days"]]])
        console.write()
        for line in rep["verdict"]:
            console.say(f"- {line}")
        return 0
    if sub == "start":
        st = acct.start(cash=args.cash, start=args.start, replace=args.reset, scenario=args.scenario)
        console.ok(f"Practice account opened with {_money(st.started_with)} of pretend money. Today is {st.today}.")
        if args.scenario:
            console.note(practice.SCENARIOS[args.scenario][1])
        console.say("Place an order (aitk practice buy SPY 5), then move time forward (aitk practice next). "
                    "See how you are doing any time with: aitk practice report")
        state.mark_done("practice")
        return 0
    if sub == "status":
        st = acct.status()
        console.title(f"Practice account   today: {st.today}")
        console.table(["cash", "buying power", "account value", "since start"],
                      [[_money(st.cash), _money(st.buying_power), _money(st.value), _pct(st.change_pct)]])
        if st.positions:
            console.write()
            console.table(["symbol", "shares", "avg cost", "price", "value", "gain", "prices"],
                          [[p["symbol"], p["shares"], f"{p['avg_cost']:.2f}", f"{p['price']:.2f}",
                            _money(p["value"]), _pct(p["gain_pct"]), st.prices_kind.get(p["symbol"], "")]
                           for p in st.positions])
        if st.open_orders:
            console.write()
            console.table(["order id", "side", "symbol", "shares", "type", "limit", "stop"],
                          [[o["client_order_id"][:8], o["side"], o["symbol"], o["quantity"], o["order_type"],
                            o["limit_price"] or "", o["stop_price"] or ""] for o in st.open_orders])
        if not st.positions and not st.open_orders:
            console.say("No positions and no open orders.")
        if prices.DEMO in st.prices_kind.values():
            console.note("'demo' means made-up prices. Run 'aitk prices get SYMBOL' for real history.")
        return 0
    if sub in ("buy", "sell"):
        out = acct.order(sub, args.symbol, args.shares, limit=args.limit, stop=args.stop,
                         good_til_cancelled=args.keep_open)
        console.ok(f"{out['side']} {out['shares']} {out['symbol']} {out['type']} accepted "
                   f"(last price {out['last_price']:.2f}, order id {out['order_id'][:8]}).")
        console.say(out["note"])
        if out["prices"] == prices.DEMO:
            console.note("Made-up demo prices for this symbol.")
        return 0
    if sub == "cancel":
        console.ok("Cancelled." if acct.cancel(args.order_id) else "Nothing to cancel.")
        return 0
    if sub == "next":
        st, fills = acct.advance(args.days)
        console.say(f"Today is now {st.today}.")
        for f in fills:
            console.ok(f"Filled: {f.side.value} {f.quantity} {f.symbol} at {f.price:.2f} on {f.ts}")
        if not fills:
            console.say("No orders filled.")
        console.say(f"Account value {_money(st.value)} ({_pct(st.change_pct)} since start), cash {_money(st.cash)}.")
        state.mark_done("practice")
        return 0
    if sub == "history":
        rows = acct.history()
        if not rows:
            console.say("No fills yet.")
        else:
            console.table(["date", "side", "symbol", "shares", "price"],
                          [[f["ts"], f["side"], f["symbol"], f["quantity"], f"{f['price']:.2f}"] for f in rows])
        return 0
    return 1


def cmd_prompts(args, console: Console) -> int:
    if args.name:
        console.raw(guide.prompt(args.name))
        state.mark_done("understand")
        return 0
    console.title("Questions to paste into your AI app")
    console.table(["name", "what it asks"], [[n, guide.prompt_title(n)] for n in guide.prompt_names()])
    console.say("Print one: aitk prompts <name>")
    return 0


def cmd_where(args, console: Console) -> int:
    console.table(["what", "where"], [
        ["the kit's home folder", str(paths.home())],
        ["price files", str(paths.prices_dir())],
        ["your strategies", str(paths.strategies_dir())],
        ["practice account", str(paths.paper_file().parent)],
        ["saved reports", str(paths.reports_dir())],
        ["settings backups", str(paths.backups_dir())],
    ])
    console.note("Move it all by setting the AITK_HOME environment variable.")
    return 0


def cmd_lesson(args, console: Console) -> int:
    console.raw(guide.lesson(args.step))
    return 0


# ── parser ────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aitk", description="Connect your broker to your AI, then learn to test "
                                "and practice trading ideas with pretend money.", allow_abbrev=False)
    p.add_argument("--version", action="version", version=f"ai-trading-kit {__version__}")
    p.add_argument("--no-menu", dest="menu", action="store_false", help="show the path without asking anything")
    sub = p.add_subparsers(dest="cmd")

    c = sub.add_parser("connect", help="connect a broker to your AI app (read-only)")
    c.add_argument("--broker")
    c.add_argument("--app", choices=list(apps_mod.all_apps()))
    c.add_argument("--yes", action="store_true", help="accept the confirmations")
    c.add_argument("--skip-test", action="store_true")
    c.set_defaults(func=cmd_connect)

    c = sub.add_parser("connect-lab", help="give your AI the practice lab (backtests, pretend money)")
    c.add_argument("--app", choices=list(apps_mod.all_apps()))
    c.add_argument("--yes", action="store_true")
    c.set_defaults(func=cmd_connect_lab)

    c = sub.add_parser("disconnect", help="remove a connection from an AI app")
    c.add_argument("broker", help="broker id, or 'lab'")
    c.add_argument("--app", required=True, choices=list(apps_mod.all_apps()))
    c.set_defaults(func=cmd_disconnect)

    sub.add_parser("check", help="re-test every connection and say what to fix").set_defaults(func=cmd_check)

    c = sub.add_parser("brokers", help="list the brokers the kit knows")
    c.add_argument("name", nargs="?")
    c.set_defaults(func=cmd_brokers)
    sub.add_parser("apps", help="list the AI apps the kit can set up").set_defaults(func=cmd_apps)

    c = sub.add_parser("keys", help="enter or forget a broker's keys")
    c.add_argument("broker")
    c.add_argument("--forget", action="store_true")
    c.set_defaults(func=cmd_keys)

    c = sub.add_parser("approve", help="run a broker's one-time approval step")
    c.add_argument("broker")
    c.set_defaults(func=cmd_approve)

    c = sub.add_parser("run-connector", help=argparse.SUPPRESS)
    c.add_argument("broker")
    c.set_defaults(func=cmd_run_connector)
    sub.add_parser("lab", help=argparse.SUPPRESS).set_defaults(func=cmd_lab)

    c = sub.add_parser("prices", help="download or import price history")
    ps = c.add_subparsers(dest="prices_cmd", required=True)
    ps.add_parser("list", help="what is on disk")
    k = ps.add_parser("key", help="store a free price-data key")
    k.add_argument("provider", nargs="?", choices=list(prices.PROVIDERS))
    g = ps.add_parser("get", help="download daily prices for symbols")
    g.add_argument("symbols", nargs="+")
    g.add_argument("--years", type=int, default=20)
    g.add_argument("--provider", choices=list(prices.PROVIDERS))
    i = ps.add_parser("import", help="import a CSV you already have")
    i.add_argument("file")
    i.add_argument("symbol")
    c.set_defaults(func=cmd_prices)

    sub.add_parser("strategies", help="list strategies").set_defaults(func=cmd_strategies)
    c = sub.add_parser("strategy", help="create your own strategy file")
    ss = c.add_subparsers(dest="strategy_cmd", required=True)
    n = ss.add_parser("new", help="create a template file")
    n.add_argument("name")
    sh = ss.add_parser("show", help="print one of your strategy files")
    sh.add_argument("name")
    c.set_defaults(func=cmd_strategy_new)

    c = sub.add_parser("backtest", help="replay a strategy over history")
    c.add_argument("strategy")
    c.add_argument("symbol")
    c.add_argument("--years", type=float)
    c.add_argument("--set", action="append", metavar="NAME=VALUE", help="a strategy setting (repeatable)")
    c.add_argument("--cash", type=float, default=10_000.0)
    c.add_argument("--trades", action="store_true", help="list the trades")
    c.add_argument("--json", action="store_true")
    c.add_argument("--save", action="store_true", help="save the report to the reports folder")
    c.set_defaults(func=cmd_backtest)

    c = sub.add_parser("compare", help="every strategy on one symbol")
    c.add_argument("symbol")
    c.add_argument("--years", type=float)
    c.set_defaults(func=cmd_compare)

    c = sub.add_parser("sweep", help="try settings, then check them on unseen history")
    c.add_argument("strategy")
    c.add_argument("symbol")
    c.add_argument("settings", nargs="+", metavar="NAME=V1,V2,...")
    c.add_argument("--years", type=float)
    c.add_argument("--first-part", type=float, default=0.7)
    c.add_argument("--show", type=int, default=15)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_sweep)

    c = sub.add_parser("practice", help="the pretend-money account")
    pr = c.add_subparsers(dest="practice_cmd", required=True)
    s = pr.add_parser("start")
    s.add_argument("--cash", type=float, default=practice.DEFAULT_CASH)
    s.add_argument("--start", metavar="YYYY-MM-DD", help="the day to begin on (default: about a year back)")
    s.add_argument("--reset", action="store_true", help="replace an existing practice account")
    s.add_argument("--scenario", choices=list(practice.SCENARIOS), help="begin at a moment worth living through")
    pr.add_parser("status")
    pr.add_parser("report", help="how you did against simply holding")
    pr.add_parser("scenarios", help="starting points worth living through")
    for side in ("buy", "sell"):
        o = pr.add_parser(side)
        o.add_argument("symbol")
        o.add_argument("shares", type=int)
        o.add_argument("--limit", type=float)
        o.add_argument("--stop", type=float)
        o.add_argument("--keep-open", action="store_true")
    x = pr.add_parser("cancel")
    x.add_argument("order_id")
    nx = pr.add_parser("next")
    nx.add_argument("days", nargs="?", type=int, default=1)
    pr.add_parser("history")
    c.set_defaults(func=cmd_practice)

    c = sub.add_parser("prompts", help="questions to paste into your AI")
    c.add_argument("name", nargs="?")
    c.set_defaults(func=cmd_prompts)
    sub.add_parser("where", help="the folders the kit uses").set_defaults(func=cmd_where)
    c = sub.add_parser("lesson", help="read a step's lesson")
    c.add_argument("step")
    c.set_defaults(func=cmd_lesson)
    return p


KNOWN_ERRORS = (lab.LabError, prices.PriceError, practice.PracticeError, strategies.StrategyError, RecipeError,
                apps_mod.AppError, vault.SecretStoreError, launcher.LaunchError, KeyError)


def main(argv=None, console: Console | None = None) -> int:
    console = console or Console()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        args.func = cmd_home
    try:
        return int(args.func(args, console) or 0)
    except Cancelled:
        console.write()
        console.say("Stopped. Nothing was changed.")
        return 130
    except KNOWN_ERRORS as exc:
        console.fail(str(exc).strip("'\""))
        return 1


if __name__ == "__main__":
    sys.exit(main())
