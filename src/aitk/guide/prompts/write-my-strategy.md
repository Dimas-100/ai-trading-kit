# Help me write my own strategy

I want to turn this idea into a strategy file: **[describe your idea in plain words]**

1. Use list_strategies to see the existing ones and where my own files live.
2. Write a strategy file in the same shape as the built-in ones: a class with `name`, `summary`,
   `warmup()` and `on_bars(bars)` that returns a `Signal`. It must look only at the bars it is given.
3. Tell me the exact file name and folder to save it in.
4. After I save it, backtest it on SPY and on two other symbols.
5. Tell me what the rule assumes about markets, and when it would be expected to fail.
