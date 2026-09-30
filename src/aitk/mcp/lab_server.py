"""The kit's own connection for an AI assistant: the practice lab.

It gives the assistant tools to test ideas on history and to trade a practice account. Every tool
works on made-up money or on price files on this computer. None can reach a real account."""
from __future__ import annotations

from .. import __version__, lab, paths, practice, prices, strategies
from .protocol import Server, Tool, ToolError

INSTRUCTIONS = (
    "These tools are a practice lab. Everything uses pretend money and price history stored on the person's "
    "computer; nothing here can reach a real brokerage account. When you report a backtest, always give the "
    "buy-and-hold comparison and the largest drop alongside the return, mention how many trades the result "
    "rests on, and repeat the cautions in 'verdict'. If 'prices' says 'demo', tell the person the prices are "
    "made up and suggest 'aitk prices get SYMBOL' for real history. Do not present any result as advice to "
    "buy or sell."
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

    def practice_status(_args):
        return account.status().as_dict()

    def practice_start(args):
        return account.start(cash=float(args.get("cash", practice.DEFAULT_CASH)), start=args.get("start_date"),
                             replace=bool(args.get("start_over", False))).as_dict()

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

    sym = {"type": "string", "description": "Ticker symbol, for example SPY"}
    years = {"type": "number", "description": "Use only the most recent N years (default: all history)"}
    tools = [
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
        Tool("practice_status", "Show the practice account: its date, cash, positions and open orders. Pretend "
             "money only.", _obj({}), practice_status),
        Tool("practice_start", "Open a practice account with pretend money, starting on a date in the past.",
             _obj({"cash": {"type": "number"}, "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                   "start_over": {"type": "boolean", "description": "Replace an existing practice account"}}),
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
    ]
    for tool in tools:
        server.add(Tool(tool.name, tool.description, tool.input_schema, guarded(tool.handler), tool.read_only))
    return server


def main() -> int:
    build().serve()
    return 0
