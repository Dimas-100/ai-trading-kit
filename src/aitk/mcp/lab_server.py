"""The kit's own connection for an AI assistant: the practice lab.

It gives the assistant tools to test ideas on history and to trade a practice account. Every tool
works on made-up money or on price files on this computer. None can reach a real account."""
from __future__ import annotations

from .. import __version__, guide, lab, paths, practice, prices, state, strategies, vault
from ..connect import apps as apps_mod
from ..connect import doctor
from ..connect.recipes import READY, find, load_all
from .protocol import Server, Tool, ToolError

INSTRUCTIONS = (
    "These tools are a practice lab and a setup guide. Everything uses pretend money and price history stored "
    "on the person's computer; nothing here can reach a real brokerage account. When you report a backtest, "
    "always give the buy-and-hold comparison and the largest drop alongside the return, mention how many trades "
    "the result rests on, and repeat the cautions in 'verdict'. If 'prices' says 'demo', offer download_prices "
    "or suggest 'aitk prices get SYMBOL'. Do not present any result as advice to buy or sell. When helping "
    "someone connect a broker, use setup_guide and check_connections; NEVER ask the person to paste an API key "
    "or secret into the chat. Keys are typed only into the aitk wizard in their own terminal. When someone "
    "describes a trading idea, turn it into a strategy file with strategy_template and save_strategy, then "
    "backtest it and report honestly, including the reality check. Ask before overwriting a file."
)


def _obj(properties: dict, required=()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def _bars(book: prices.PriceBook, symbol: str, years):
    symbol = prices.clean_symbol(symbol)
    bars = book.all_bars(symbol)
    if years:
        bars = bars[-int(float(years) * 252):]
    return symbol, bars


def build(book: prices.PriceBook | None = None) -> Server:
    book = book or prices.PriceBook()
    account = practice.Practice(book)
    server = Server("ai-trading-kit-lab", __version__, INSTRUCTIONS)

    def guarded(fn):
        def run(args: dict):
            try:
                return fn(args)
            except (lab.LabError, prices.PriceError, practice.PracticeError, strategies.StrategyError) as exc:
                raise ToolError(str(exc)) from exc
            except (TypeError, ValueError, KeyError) as exc:
                raise ToolError(f"that request could not be understood: {exc}") from exc
        return run

    def list_strategies(_args):
        return {"strategies": strategies.describe(), "problems_in_your_files": strategies.load_errors,
                "your_files": str(paths.strategies_dir())}

    def price_history(args):
        symbol, bars = _bars(book, args["symbol"], args.get("years"))
        closes = [b.close for b in bars]
        return {"symbol": symbol, "prices": book.kind(symbol), "days": len(bars), "first": bars[0].ts,
                "last": bars[-1].ts, "last_close": round(closes[-1], 2), "highest": round(max(closes), 2),
                "lowest": round(min(closes), 2),
                "change_pct": round((closes[-1] / closes[0] - 1) * 100, 2),
                "recent": [{"date": b.ts, "close": round(b.close, 2)} for b in bars[-int(args.get("recent", 10)):]]}

    def backtest(args):
        symbol, bars = _bars(book, args["symbol"], args.get("years"))
        strategies.load_user_strategies()
        report = lab.evaluate(args["strategy"], bars, symbol=symbol, params=args.get("settings") or {},
                              starting_cash=float(args.get("starting_cash", 10_000)))
        out = report.as_dict()
        out["prices"] = book.kind(symbol)
        trades = out.pop("trades")
        out["trades_shown"] = trades[-int(args.get("show_trades", 10)):]
        return out

    def compare(args):
        symbol, bars = _bars(book, args["symbol"], args.get("years"))
        wanted = args.get("strategies") or strategies.names()
        strategies.load_user_strategies()
        rows = lab.compare(list(wanted), bars, symbol=symbol)
        return {"symbol": symbol, "prices": book.kind(symbol), "first": bars[0].ts, "last": bars[-1].ts,
                "ranked": [{"strategy": r.strategy, **{k: r.metrics[k] for k in (
                    "total_return_pct", "buy_hold_return_pct", "max_drawdown_pct", "trades", "win_rate_pct",
                    "exposure_pct")}} for r in rows],
                "note": "Ranked by return on this one history. The ranking can flip on another symbol or period."}

    def try_settings(args):
        symbol, bars = _bars(book, args["symbol"], args.get("years"))
        strategies.load_user_strategies()
        result = lab.sweep(args["strategy"], bars, args["settings"], symbol=symbol,
                           train_fraction=float(args.get("first_part", 0.7)))
        out = result.as_dict()
        out["prices"] = book.kind(symbol)
        out["rows"] = out["rows"][:int(args.get("show", 10))]
        return out

    def download_prices(args):
        store = vault.open_store()
        provider = prices.available_provider(store)
        if provider is None:
            raise ToolError("no price provider key is stored. Ask the person to run 'aitk prices key' once "
                            "(Tiingo or Alpaca, both free), then try again.")
        out = []
        for symbol in args["symbols"]:
            path, n, used = prices.download(symbol, store, years=int(args.get("years", 20)))
            out.append({"symbol": prices.clean_symbol(symbol), "days": n, "from": prices.PROVIDERS[used]["name"],
                        "first": book.all_bars(symbol)[0].ts, "last": book.all_bars(symbol)[-1].ts})
        return {"downloaded": out, "note": "Real daily prices, adjusted for splits and dividends, kept on this "
                                          "computer. Backtests on these symbols now use them."}

    def where_am_i(_args):
        rows = guide.steps()
        nxt = guide.next_step()
        return {"steps": [{"number": r["step"].number, "title": r["step"].title, "done": r["done"],
                           "command": r["step"].command} for r in rows],
                "next": None if nxt is None else {"number": nxt.number, "title": nxt.title, "command": nxt.command},
                "connections": state.load()["connections"],
                "price_files": prices.downloaded(), "home_folder": str(paths.home())}

    def list_brokers(args):
        query = str(args.get("query") or "").strip()
        recipes = find(query) if query else list(load_all().values())
        rows = []
        for r in recipes:
            rows.append({"id": r.id, "name": r.name, "ready": r.status == READY, "effort": r.difficulty,
                         "read_only": r.read_only, "read_only_note": r.read_only_note, "summary": r.summary,
                         "assets": list(r.assets), "warning": r.warning, "advice": r.advice,
                         "platforms": list(r.platforms), "docs": r.docs_url})
        if query and not rows:
            return {"brokers": [], "note": f"No recipe matches '{query}'. The broker may offer no official "
                                          "connector; SnapTrade reads many brokers without being able to trade."}
        return {"brokers": rows}

    def setup_guide(args):
        broker_id = str(args.get("broker") or "").strip().lower()
        hits = [r for r in find(broker_id) if r.id == broker_id] or find(broker_id)
        if not hits:
            raise ToolError(f"no broker called '{broker_id}'. Use list_brokers first.")
        r = hits[0]
        app_id = str(args.get("app") or "").strip().lower()
        apps = apps_mod.all_apps()
        app_line = f" --app {app_id}" if app_id in apps else ""
        if r.status != READY:
            return {"broker": r.name, "ready": False, "advice": r.advice, "docs": r.docs_url}
        out = {"broker": r.name, "ready": True, "read_only": r.read_only, "read_only_note": r.read_only_note,
               "warning": r.warning, "steps_at_the_broker": list(r.access_steps),
               "then_run_in_a_terminal": f"aitk connect --broker {r.id}{app_line}",
               "the_wizard_will_ask_for": [f.label for f in r.fields],
               "programs_needed": list(r.needs), "one_time_step": r.first_run_note, "docs": r.docs_url,
               "rule": "Never paste a key or secret into this chat. Type it into the wizard in your own terminal; "
                       "it is stored in your computer's password vault."}
        if app_id == "chatgpt" and r.guarded:
            out["note"] = "ChatGPT cannot use this broker: it can only use brokers you sign in to."
        return out

    def check_connections(_args):
        conns = state.load()["connections"]
        if not conns:
            return {"connections": [], "note": "No connections yet. Use setup_guide to get started."}
        store = vault.open_store()
        results = []
        for c in conns:
            if c["broker"] == "lab":
                results.append({"broker": "lab", "app": c["app"], "ok": True, "message": "The practice lab is this."})
                continue
            recipe = load_all().get(c["broker"])
            if recipe is None:
                continue
            report = doctor.check_connection(recipe, store)
            results.append({"broker": c["broker"], "app": c["app"], "ok": report.ok, "message": report.message,
                            "tools_available": len(report.kept), "tools_removed": [n for n, _ in report.removed],
                            "fix": report.fix})
        return {"connections": results}

    def strategy_template(args):
        return {"template": strategies.template(str(args.get("name") or "my_idea")),
                "rules": ["Keep the class's name attribute equal to the file name.",
                          "Import only aitk.engine.indicators, aitk.engine.models, aitk.engine.strategy, math, "
                          "statistics.",
                          "on_bars sees ascending bars and answers for the newest bar only.",
                          "Nothing that touches files, the network or the system is allowed; save_strategy "
                          "refuses it."]}

    def save_strategy(args):
        return strategies.save(args["name"], args["code"], overwrite=bool(args.get("overwrite", False)))

    def read_strategy(args):
        return {"name": args["name"], "code": strategies.read(args["name"])}

    def practice_status(_args):
        return account.status().as_dict()

    def practice_start(args):
        return account.start(cash=float(args.get("cash", practice.DEFAULT_CASH)), start=args.get("start_date"),
                             replace=bool(args.get("start_over", False)),
                             scenario=args.get("scenario") or None).as_dict()

    def practice_order(args):
        return account.order(args["side"], args["symbol"], args["shares"], limit=args.get("limit_price"),
                             stop=args.get("stop_price"), good_til_cancelled=bool(args.get("keep_open", False)))

    def practice_cancel(args):
        return {"cancelled": account.cancel(args["order_id"])}

    def practice_next_day(args):
        status, fills = account.advance(int(args.get("days", 1)))
        return {"filled": [{"side": f.side.value, "symbol": f.symbol, "shares": f.quantity,
                            "price": round(f.price, 2), "date": f.ts} for f in fills],
                "account": status.as_dict()}

    def practice_history(_args):
        return {"fills": account.history()}

    def practice_report(_args):
        return account.report()

    def practice_scenarios(_args):
        return {"scenarios": [{"name": k, "starts": v[0], "why": v[1]} for k, v in practice.SCENARIOS.items()],
                "how": "practice_start with scenario=<name>. Needs real prices (download_prices SPY).",
                "prices": account.book.kind(practice.CALENDAR_SYMBOL)}

    sym = {"type": "string", "description": "Ticker symbol, for example SPY"}
    years = {"type": "number", "description": "Use only the most recent N years (default: all history)"}
    tools = [
        Tool("where_am_i", "Where the person is on the kit's six-step path, which connections exist, which price "
             "files are on disk, and the next command to suggest.", _obj({}), where_am_i),
        Tool("list_brokers", "The brokers the kit can connect, how much effort each takes and how each is kept "
             "read-only. Give a query to look one up by name (for example 'fidelity').",
             _obj({"query": {"type": "string"}}), list_brokers),
        Tool("setup_guide", "The exact steps to connect a broker: what to do at the broker's site, the command to "
             "run in a terminal, and what the wizard will ask. Never ask for keys in the chat.",
             _obj({"broker": {"type": "string", "description": "Broker id from list_brokers, e.g. alpaca"},
                   "app": {"type": "string", "enum": ["claude-desktop", "claude-code", "cursor", "chatgpt"]}},
                  ["broker"]), setup_guide),
        Tool("check_connections", "Re-test every connection the person set up and say what works and what to fix. "
             "Can take a minute per broker.", _obj({}), check_connections),
        Tool("strategy_template", "A starting file for a new strategy, plus the rules a strategy file must "
             "follow. Use it before writing one.", _obj({"name": {"type": "string"}}), strategy_template),
        Tool("save_strategy", "Write a strategy file into the person's strategies folder. The code is checked "
             "(only engine imports, nothing that touches files or the network), test-run on made-up prices, "
             "and only then saved. Returns what happened and the next command.",
             _obj({"name": {"type": "string", "description": "lower case, letters, digits and _"},
                   "code": {"type": "string", "description": "The whole Python file"},
                   "overwrite": {"type": "boolean"}}, ["name", "code"]), save_strategy, read_only=False),
        Tool("read_strategy", "Read one of the person's strategy files.", _obj({"name": {"type": "string"}}, ["name"]),
             read_strategy),
        Tool("list_strategies", "List the trading strategies that can be tested, with their settings and a "
             "one-line description of each.", _obj({}), list_strategies),
        Tool("price_history", "Summarize the price history the kit has for a symbol: dates covered, high, low, "
             "change, and the most recent closes. Says whether the prices are real files or made-up demo prices.",
             _obj({"symbol": sym, "years": years,
                   "recent": {"type": "integer", "description": "How many recent closes to include (default 10)"}},
                  ["symbol"]), price_history),
        Tool("backtest", "Replay one strategy over a symbol's history with pretend money and report how it did "
             "against buying and holding, with cautions in plain words.",
             _obj({"strategy": {"type": "string"}, "symbol": sym, "years": years,
                   "settings": {"type": "object", "description": "Strategy settings, for example "
                                                                 "{\"fast\": 10, \"slow\": 30}"},
                   "starting_cash": {"type": "number"},
                   "show_trades": {"type": "integer", "description": "How many of the last trades to list"}},
                  ["strategy", "symbol"]), backtest),
        Tool("compare_strategies", "Run several strategies on the same symbol and history and rank them, with "
             "buy and hold as the yardstick.",
             _obj({"symbol": sym, "years": years,
                   "strategies": {"type": "array", "items": {"type": "string"}}}, ["symbol"]), compare),
        Tool("try_settings", "Try many settings of a strategy on the first part of the history, then check each "
             "on the last part it never saw. Shows whether a good result is sturdy or a coincidence.",
             _obj({"strategy": {"type": "string"}, "symbol": sym, "years": years,
                   "settings": {"type": "object", "description": "Values to try per setting, for example "
                                                                 "{\"fast\": [10, 20], \"slow\": [50, 100]}"},
                   "first_part": {"type": "number", "description": "Share of history used for choosing (0.3-0.9)"},
                   "show": {"type": "integer"}}, ["strategy", "symbol", "settings"]), try_settings),
        Tool("download_prices", "Download real daily price history for symbols with the person's own free "
             "provider key (Tiingo or Alpaca), so backtests stop using demo prices. Says if no key is stored.",
             _obj({"symbols": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                   "years": {"type": "integer", "description": "How many years back (default 20)"}}, ["symbols"]),
             download_prices, read_only=False),
        Tool("practice_status", "Show the practice account: its date, cash, positions and open orders. Pretend "
             "money only.", _obj({}), practice_status),
        Tool("practice_start", "Open a practice account with pretend money, starting on a date in the past.",
             _obj({"cash": {"type": "number"}, "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                   "start_over": {"type": "boolean", "description": "Replace an existing practice account"},
                   "scenario": {"type": "string", "description": "A name from practice_scenarios"}}),
             practice_start, read_only=False),
        Tool("practice_order", "Place an order in the practice account (pretend money). It fills at the next "
             "day's prices, after time is moved forward.",
             _obj({"side": {"type": "string", "enum": ["buy", "sell"]}, "symbol": sym,
                   "shares": {"type": "integer", "minimum": 1}, "limit_price": {"type": "number"},
                   "stop_price": {"type": "number"},
                   "keep_open": {"type": "boolean", "description": "Keep the order open until it fills or is "
                                                                   "cancelled (default: it expires after one day)"}},
                  ["side", "symbol", "shares"]), practice_order, read_only=False),
        Tool("practice_cancel", "Cancel an open order in the practice account.",
             _obj({"order_id": {"type": "string"}}, ["order_id"]), practice_cancel, read_only=False),
        Tool("practice_next_day", "Move the practice account's calendar forward and report which orders filled.",
             _obj({"days": {"type": "integer", "minimum": 1, "description": "Trading days to move (default 1)"}}),
             practice_next_day, read_only=False),
        Tool("practice_history", "List every fill in the practice account so far.", _obj({}), practice_history),
        Tool("practice_report", "The report card: how the practice account did since it started against simply "
             "holding, with a plain-words verdict.", _obj({}), practice_report),
        Tool("practice_scenarios", "Named starting points worth living through (a crash, a bear market, a rally) "
             "for practice_start.", _obj({}), practice_scenarios),
    ]
    for tool in tools:
        server.add(Tool(tool.name, tool.description, tool.input_schema, guarded(tool.handler), tool.read_only))
    return server


def main() -> int:
    build().serve()
    return 0
