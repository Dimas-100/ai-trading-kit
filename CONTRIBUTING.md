# Contributing

Thank you. Three things keep this kit safe to hand to strangers, and every change is checked against them:

1. **No real orders.** Nothing here may submit, change or cancel an order at a broker.
2. **No keys in files.** Keys stay in the vault; recipes and tests never hold one.
3. **Official connectors only.**

See `AGENTS.md` for the full rules, `docs/adding-a-broker.md` to add a broker (one TOML file), and
`docs/safety-model.md` before touching the guard.

Before a pull request: `pytest` and `ruff check .` must pass. Tests never touch the network or real
settings files.
