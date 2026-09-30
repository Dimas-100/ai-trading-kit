# Step 6: Write and stress-test your own idea

**What you get:** your own rule, in a file you own, tested the way a careful person tests one.

**Do it:**

    aitk strategy new my_idea                      # creates a starting file and says where it is
    aitk backtest my_idea SPY                      # run it
    aitk sweep my_idea SPY period=20,50,100,200    # try settings, check on unseen history

You can also ask your AI to write the file for you: it knows the template through the lab.

## The one rule of testing

**Choose on the first part of history. Judge on the last part.**

If you try twenty settings and keep the best, you have mostly found luck. `aitk sweep` picks the
winner using only the first 70% of the history, then shows how every setting did on the last 30%,
which played no part in the choice.

| What you see | What it means |
|---|---|
| The winner also does well on the unseen part | Encouraging. Test more symbols. |
| The winner loses on the unseen part | It was a coincidence. Let it go. |
| Most settings make money on the unseen part | The idea is sturdy: it does not depend on one magic number. |
| Only the winner makes money | Fragile. One magic number rarely survives real markets. |

## Before any real money

This kit stops at pretend money on purpose. If you later trade for real, do it at your broker, start
small, and decide your exit before you enter. Nothing in this kit is financial advice.
