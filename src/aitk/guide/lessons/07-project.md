# Step 7: Make it a project

**What you get:** one folder that is yours: the rules you trade by, a record of why you did what you
did, your strategy files, and a history of every change. This is what separates a hobby from a
practice.

**Do it:**

    aitk init my-trading          # creates the folder and its first git commit
    cd my-trading
    aitk connect-lab              # point your AI at this folder (its practice account and prices live here)

## What is in the folder

| File | What it is for |
|---|---|
| `plan.md` | The rules: goal, buy, sell, safety net, size, and when you will review. Change it at a review, never mid-trade. |
| `journal.md` | Dated entries: what you decided, why, and what would change your mind. Your AI can write them ("log this"). |
| `strategies/` | Your strategy files, the ones the AI writes with `save_strategy` and the ones you write yourself. |
| `prices/`, `practice/` | Downloaded history and the practice account. Kept out of git. |
| `AGENTS.md` | Tells any AI opened in the folder what this place is and how to behave: read the plan first, journal decisions, never real orders. |

## Why the journal matters more than the strategy

Six months from now you will not remember why you sold. The journal will. Reading your own reasons
back, next to what actually happened, is the fastest way anyone learns to trade, and it costs one
sentence per decision.

## Working inside the folder

`aitk` finds the project on its own when you run it anywhere inside. Ask your AI "read my plan and
tell me whether this trade fits it" or "log that I bought 5 SPY because the rule triggered". Commit
when something changes: `git add -A && git commit -m "what changed"`.
