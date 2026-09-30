# Step 4: Test an idea on history

**What you get:** an honest answer to "would this rule have worked?"

**Do it:**

    aitk prices key                 # once: store a free price-data key
    aitk prices get SPY             # download about 20 years of daily prices
    aitk backtest sma_cross SPY     # replay the rule
    aitk compare SPY                # every built-in rule, side by side

## Reading the result

| Number | What it tells you |
|---|---|
| total_return_pct | What the rule made over the whole period. |
| buy_hold_return_pct | What doing nothing made. **The rule has to beat this to be worth the effort.** |
| max_drawdown_pct | The worst fall from a peak. Ask whether you would have kept going. |
| trades | How many closed trades the result rests on. Under 30 is too few to trust. |
| win_rate_pct | Share of trades that made money. High is not the same as profitable. |
| exposure_pct | Share of days the money was in the market. |

## What a backtest cannot show

It assumes every order fills, ignores taxes, and knows nothing about tomorrow. A rule that looks good
on one symbol over one period has shown very little. Test it on several symbols before believing it.
