"""
data.py — price data via yfinance.

Unofficial and rate-limited, which is fine at a 5-minute cadence for a
handful of tickers. Every fetch is defensive: a symbol that fails returns
None and the engine marks it STALE rather than inventing a number.
"""

from __future__ import annotations

import logging
import warnings
from typing import Dict, List, Optional

warnings.filterwarnings("ignore")

import yfinance as yf  # noqa: E402

from .indicators import atr, pct_change, rsi, sma, volume_ratio  # noqa: E402

log = logging.getLogger("data")


class Snapshot(dict):
    """Plain dict of metrics for one symbol. dict so it serializes for free."""


def _series(frame, symbol: str, field: str) -> List[float]:
    try:
        col = frame[symbol][field] if symbol in frame.columns.get_level_values(0) else frame[field]
    except Exception:
        return []
    return [float(v) for v in col.dropna().tolist()]


def fetch(symbols: List[str], period: str = "1y") -> Dict[str, Optional[Snapshot]]:
    """Return {symbol: Snapshot or None} of daily-bar derived metrics."""
    out: Dict[str, Optional[Snapshot]] = {s: None for s in symbols}

    try:
        frame = yf.download(
            symbols,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=False,
            group_by="ticker",
            threads=True,
        )
    except Exception as exc:
        log.error("yfinance download failed entirely: %s", exc)
        return out

    if frame is None or frame.empty:
        log.error("yfinance returned an empty frame")
        return out

    for symbol in symbols:
        closes = _series(frame, symbol, "Close")
        highs = _series(frame, symbol, "High")
        lows = _series(frame, symbol, "Low")
        volumes = _series(frame, symbol, "Volume")

        if len(closes) < 30:
            log.warning("%s: only %d closes - marking stale", symbol, len(closes))
            continue

        price = closes[-1]
        prev = closes[-2]
        snap = Snapshot(
            symbol=symbol,
            price=round(price, 2),
            prev_close=round(prev, 2),
            day_pct=round(pct_change(price, prev) or 0.0, 2),
            day_high=round(highs[-1], 2),
            day_low=round(lows[-1], 2),
            sma50=round(sma(closes, 50), 2) if sma(closes, 50) else None,
            sma200=round(sma(closes, 200), 2) if sma(closes, 200) else None,
            rsi14=round(rsi(closes, 14), 1) if rsi(closes, 14) else None,
            atr14=round(atr(highs, lows, closes, 14), 2) if atr(highs, lows, closes, 14) else None,
            vol_ratio=round(volume_ratio(volumes, 20), 2) if volume_ratio(volumes, 20) else None,
            year_high=round(max(closes), 2),
            year_low=round(min(closes), 2),
        )
        out[symbol] = snap

    return out
