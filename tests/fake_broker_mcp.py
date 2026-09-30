"""A stand-in for a broker's connector: a few read tools, a few that would change the account.
It answers over stdio like a real one, and reports its environment so tests can see what it got."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from aitk.mcp.protocol import Server, Tool  # noqa: E402


def build() -> Server:
    s = Server("fake-broker", "0.0")
    obj = {"type": "object", "properties": {}}
    s.add(Tool("get_account", "balances", obj, lambda a: {"cash": 100.0, "env_key": os.environ.get("FAKE_KEY", "")},
               read_only=True))
    s.add(Tool("get_positions", "positions", obj, lambda a: [{"symbol": "SPY", "qty": 1}], read_only=True))
    s.add(Tool("stock_quote", "quote", obj, lambda a: {"price": 1.0}, read_only=True))
    s.add(Tool("place_order", "SENDS AN ORDER", obj, lambda a: {"sent": True}, read_only=False))
    s.add(Tool("cancel_order", "cancels", obj, lambda a: {"cancelled": True}, read_only=False))
    s.add(Tool("watchlist_add", "adds to a watchlist", obj, lambda a: {"added": True}, read_only=False))
    if os.environ.get("FAKE_LOG_ON_STDOUT"):
        print("fake-broker: starting up (a stray log line)")
    return s


if __name__ == "__main__":
    build().serve()
