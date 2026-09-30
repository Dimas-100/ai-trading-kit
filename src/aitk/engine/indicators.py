"""Pure technical indicators over price lists. Each returns a list aligned to the input, with None
during the warmup region or on a data gap. Float-only; no numpy."""
from __future__ import annotations


def sma(values, period):
    out = [None] * len(values)
    if period <= 0:
        return out
    for i in range(len(values)):
        if i < period - 1:
            continue
        window = values[i - period + 1:i + 1]
        if any(v is None for v in window):
            continue
        out[i] = sum(window) / period
    return out


def ema(values, period):
    out = [None] * len(values)
    if period <= 0:
        return out
    k = 2.0 / (period + 1)
    prev = None
    for i, v in enumerate(values):
        if v is None:
            prev = None
            continue
        if prev is None:
            window = values[i - period + 1:i + 1] if i >= period - 1 else None
            if window and all(x is not None for x in window):
                prev = sum(window) / period
                out[i] = prev
            continue
        prev = v * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values, period):
    out = [None] * len(values)
    if period <= 0 or len(values) <= period:
        return out
    avg_gain = avg_loss = None
    for i in range(1, len(values)):
        if values[i] is None or values[i - 1] is None:
            avg_gain = avg_loss = None
            continue
        change = values[i] - values[i - 1]
        gain, loss = max(change, 0.0), max(-change, 0.0)
        if avg_gain is None:
            if i >= period and all(values[j] is not None for j in range(i - period, i + 1)):
                gains = [max(values[j] - values[j - 1], 0.0) for j in range(i - period + 1, i + 1)]
                losses = [max(values[j - 1] - values[j], 0.0) for j in range(i - period + 1, i + 1)]
                avg_gain, avg_loss = sum(gains) / period, sum(losses) / period
            else:
                continue
        else:
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def atr(highs, lows, closes, period):
    """Average True Range (Wilder), aligned to the input; None during warmup / on a gap."""
    n = len(closes)
    out = [None] * n
    if period <= 0 or n <= period:
        return out
    tr = [None] * n
    for i in range(1, n):
        h, lo, pc = highs[i], lows[i], closes[i - 1]
        if None in (h, lo, pc):
            continue
        tr[i] = max(h - lo, abs(h - pc), abs(lo - pc))
    prev = None
    for i in range(1, n):
        if tr[i] is None:
            prev = None
            continue
        if prev is None:
            if i < period:
                continue
            window = tr[i - period + 1:i + 1]
            if any(x is None for x in window):
                continue
            prev = sum(window) / period
            out[i] = prev
        else:
            prev = (prev * (period - 1) + tr[i]) / period
            out[i] = prev
    return out
