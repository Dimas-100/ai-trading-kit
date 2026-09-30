# Step 5: Practice with pretend money

**What you get:** the feel of placing orders and living with them, without risking anything.

**Do it:**

    aitk practice start             # 10,000 pretend dollars, starting a year back
    aitk practice buy SPY 5         # place an order
    aitk practice next              # move to the next trading day: did it fill?
    aitk practice status            # cash, positions, open orders

## The practice calendar

The account has its own date, in the past. **You** move time forward. An order placed today fills at
tomorrow's prices, the way a real one would. A month of decisions takes ten minutes.

## Order types

| Command | What it does |
|---|---|
| `aitk practice buy SPY 5` | Buy at the next day's opening price. |
| `aitk practice buy SPY 5 --limit 400` | Buy only at 400 or lower. |
| `aitk practice sell SPY 5 --stop 380` | Sell if the price falls to 380. A safety net under a position. |
| add `--keep-open` | Keep the order until it fills or you cancel it. Otherwise it expires after a day. |

## What to practice

Before you buy, write down what would make you sell. Then move time forward and see whether you
follow your own rule. That habit matters more than any strategy.
