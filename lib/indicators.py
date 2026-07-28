"""
indicators.py — plain-arithmetic technical indicators.

Deliberately dependency-light and deterministic: every number here is
reproducible from the OHLCV frame alone. No inference, no model calls.
This is the tier-1 layer the alerts are allowed to act on.
"""

from __future__ import annotations

from typing import List, Optional, Sequence


def sma(values: Sequence[float], window: int) -> Optional[float]:
    """Simple moving average of the last `window` values."""
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def rsi(closes: Sequence[float], window: int = 14) -> Optional[float]:
    """Wilder's RSI. Returns None until there are window+1 closes."""
    if len(closes) < window + 1:
        return None

    gains: List[float] = []
    losses: List[float] = []
    for prev, cur in zip(closes[-(window + 1):-1], closes[-window:]):
        delta = cur - prev
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    window: int = 14,
) -> Optional[float]:
    """Average true range — the unit we measure 'how far is far' in."""
    if len(closes) < window + 1:
        return None

    true_ranges: List[float] = []
    for i in range(1, len(closes)):
        prev_close = closes[i - 1]
        true_ranges.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
        )
    if len(true_ranges) < window:
        return None
    return sum(true_ranges[-window:]) / window


def volume_ratio(volumes: Sequence[float], window: int = 20) -> Optional[float]:
    """Today's volume as a multiple of the trailing average. 1.0 = normal."""
    if len(volumes) < window + 1:
        return None
    baseline = sum(volumes[-(window + 1):-1]) / window
    if baseline == 0:
        return None
    return volumes[-1] / baseline


def pct_change(current: float, reference: float) -> Optional[float]:
    if not reference:
        return None
    return (current - reference) / reference * 100.0
