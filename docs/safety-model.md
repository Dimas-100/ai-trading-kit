# Safety model

The kit's promise: **nothing in it can place, change or cancel a real order**, and **no key ever
leaves the person's computer or lands in a file it should not**. This page says how that is kept,
and where the promise stops.

## 1. There is no order path

The kit contains no code that submits an order to a broker. The engine's `safety.should_submit`
exists (it is shared with the toolkit the engine came from) but nothing calls it; the only `Broker`
in the kit is the practice simulator, which writes one JSON file. A test asserts that every tool of
the lab server that can change state is a `practice_*` tool.

## 2. The guard

For brokers whose connector the kit starts (`transport = "stdio"`) or reaches with a token
(`transport = "http"`), the AI app talks to `aitk run-connector <broker>`, never to the connector
directly. The guard in between:

- filters every `tools/list` answer, removing tools that could change the account;
- refuses `tools/call` for such a tool even when it was never listed, and sends nothing on;
- passes every other message through untouched.

A tool is removed when its publisher marks it `readOnlyHint: false` or destructive, when its name
begins with a change-word (`place`, `submit`, `cancel`, `create`, `update`, `transfer`, ...), when its
name ends in `order` or `trade`, or when a change-word appears anywhere in it (leading-only words
such as `open` and `order` are allowed elsewhere in a name, so `get_open_orders` passes). Names that
begin with a read-word (`get`, `list`, `search`, `preview`, ...) pass. Ambiguous leads (`order_history`)
pass only when the rest of the name says lookup or the publisher marks the tool read-only. Anything
the rule cannot place is kept only when nothing in its name or markings suggests a change; a recipe
can correct single tools with `allow_tools` and `deny_tools`.

Checked against real connectors on 2026-09-29: Alpaca (45 tools: 44 kept, `update_account_config`
removed), Public (37 tools: 27 kept, all 10 place/cancel tools removed by their own
`readOnlyHint: false` marking).

The guard is a second lock, not the only one. Every recipe also uses the broker's own read-only
setting where one exists (`ALPACA_TOOLSETS`, `WEBULL_TOOLSETS`, Kraken's default service set), and
the wizard tells people to create keys with only read permissions where the broker offers that.

## 3. Sign-in connectors

Hosted connectors that use the broker's own sign-in (`transport = "oauth"`) cannot be proxied, so the
guard does not apply. The recipe says which of three cases holds and the wizard repeats it:

| `read_only` | Meaning |
|---|---|
| `broker` | The connector cannot trade at all (SnapTrade). |
| `sign-in` | The person chooses permissions at sign-in; the wizard says which to tick (Webull, Coinbase). |
| `none` | Trading cannot be switched off (Robinhood, Moomoo). The wizard warns and asks before continuing; the default answer is no. |

## 4. Keys

- Stored in the operating system's vault through `keyring`; on a computer without one, in a file
  under the kit's home folder readable only by its owner, and the wizard says so.
- Read by the launcher at the moment the AI app starts the connector, and passed as environment
  variables (stdio) or HTTP headers (http). They are never written into an AI app's settings file:
  the entry there is `python -m aitk run-connector <broker>`.
- Never printed. Secret fields are typed hidden. A test asserts the wizard's output never contains
  the secret it was given.
- Never in this repository: recipes name the keys a broker needs and hold no values (a test scans
  them for anything that looks like a key).

## 5. Settings files

The kit edits three files at most: Claude Desktop's `claude_desktop_config.json`, Cursor's
`~/.cursor/mcp.json`, and Claude Code's configuration through the `claude mcp` command. Before a
JSON file is written it is copied to `~/.ai-trading-kit/backups/`. Only the entry being added or
removed changes; a file that is not valid JSON is left untouched and reported.

## 6. Strategy files an AI writes

`save_strategy` lets an assistant write a Python file the kit will later run. Before a byte is written:
the source is parsed and refused if it imports anything but `aitk.engine.indicators`, `aitk.engine.models`,
`aitk.engine.strategy`, `math` or `statistics`; uses `open`, `exec`, `eval`, `__import__`, `getattr` and the
like; or reaches for dunder attributes (`__class__`, `__subclasses__`, ...). It must register exactly the
class named after the file. The file is then imported from a scratch copy and run through a short backtest
on made-up prices; only if that succeeds is it saved. This is a fence against accidents and obvious
misuse, not a sandbox: a person's own AI writes into a person's own folder on their own computer.

## 7. Where the promise stops

- A broker's own connector may change over time. `aitk check` re-tests the tool list at any moment.
- The name rules are conservative, not perfect. A tool with a misleading name and no publisher
  marking could pass; a recipe can deny it by name once known. Report such a tool.
- The lab's practice account is pretend money. Backtests ignore taxes and assume fills. The kit says
  this on every result; it cannot make anyone read it.
- Sign-in connectors marked `none` can trade. The kit can only say so clearly.
