# Adding a broker

A broker is one TOML file in `src/aitk/connect/recipes/`, named after its id. The wizard, the
launcher, the doctor and the broker list all read it. No Python is needed for a broker that offers an
official MCP connector.

## 1. Find the official connector

Only official connectors qualify: published by the broker (or by an aggregator such as SnapTrade),
documented on the broker's own pages. Libraries that log in with a person's password do not.

Write down, from the broker's own documentation:

- how it is started (`uvx package`, `npx -y package`, a binary) or its hosted address;
- the environment variables or headers it needs;
- any setting that turns off its trading tools;
- how a person gets a key, whether approval is needed, and whether a practice account exists.

## 2. Write the recipe

```toml
id = "example"                      # must match the file name example.toml
name = "Example Broker"
summary = "One sentence a beginner understands."
assets = ["stocks", "options"]
difficulty = "easy"                 # easy | medium | hard
read_only = "kit"                   # kit | broker | sign-in | none  (see docs/safety-model.md)
read_only_note = "What keeps this connection read-only, in plain words."
docs_url = "https://example.com/developers/mcp"
checked = "2026-09-29"              # the day you read those pages
confidence = "checked"              # checked | partly | unchecked
access_steps = [
  "Sign in at ... and open ...",
  "Create a key. Keep the page open: you will paste it in the next step.",
]

[[fields]]                          # one per value the wizard must ask for
key = "EXAMPLE_API_KEY"             # the exact environment variable or header name
label = "Example API key"
secret = false                      # false = shown while typing, true = hidden

[[fields]]
key = "EXAMPLE_API_SECRET"
label = "Example API secret"

[connector]
transport = "stdio"                 # stdio | http | oauth
command = ["uvx", "example-mcp-server"]
needs = ["uvx"]                     # programs that must be installed
first_run = ["uvx", "example-mcp-server", "auth"]      # optional one-time step
first_run_note = "What happens during it."

[connector.env]                     # fixed settings; the broker's own read-only switch goes here
EXAMPLE_TOOLSETS = "account,market-data"
```

For a hosted connector with a token in a header:

```toml
[connector]
transport = "http"
url = "https://mcp.example.com/mcp"
header_fields = ["API_KEY"]         # which fields travel as headers instead of environment variables
```

For a hosted connector where the person signs in at the broker:

```toml
read_only = "sign-in"               # or "broker" or "none"
[connector]
transport = "oauth"
url = "https://mcp.example.com/mcp"
```

A broker without a connector, or one you could not verify, gets `status = "listed"` and an `advice`
line instead of a `[connector]` block. It shows in `aitk brokers` with that advice.

## 3. Rules the loader enforces

- A connector the kit starts (`stdio`, `http`) must be `read_only = "kit"`: the guard always applies.
- `oauth` connectors take no `fields` and cannot be `kit`.
- `url` must start with `https://`. `header_fields` must name declared fields.
- Recipes hold no key values. A test scans them.

## 4. Check it

```
aitk brokers example                # the text a person will read
aitk keys example                   # store test keys
aitk check                          # after `aitk connect --broker example --app cursor --skip-test`
```

`aitk check` starts the connector and prints which tools the guard kept and removed. Look at the
removed list: if a read tool was removed because of its name, add it to `allow_tools`; if a tool that
changes the account slipped through, add it to `deny_tools` and open an issue so the rule improves.

Run `pytest` before opening a pull request: `tests/test_recipes.py` validates every recipe.
