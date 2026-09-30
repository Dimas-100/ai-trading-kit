# CLAUDE.md

Read `AGENTS.md`: it holds the rules for any AI assistant working in this repository, and what to do
when a person asks to be "set up". Nothing here overrides it.

Owner notes (not for the public README): this project was split out of the private `webull` trading
system on 2026-09-29 so that the live real-money folder never hosts unrelated work. The engine under
`src/aitk/engine/` is vendored from the local `trading-rails` folder; improve it here, not there.
