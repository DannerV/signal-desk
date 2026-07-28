"""
engine.py — the rules. This is the whole opinion layer, and it is arithmetic.

States
  HOLD_FIRE  earnings blackout - no buy/sell signal is trustworthy
  BUY_WATCH  price >= reclaim
  BROKEN     price <= invalidation
  WAIT       between the lines
  STALE      no data this run

A state CHANGE into BUY_WATCH or BROKEN is what alerts. On top of that we
try to build a prepared ticket: a fully specified proposal Dan can approve
or deny from his phone. Several guards can refuse to build one - refusing
is a valid, and often correct, output.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, Optional

from .clock import earnings_blackout, fmt_local, now_market, session_close

HOLD_FIRE = "HOLD_FIRE"
BUY_WATCH = "BUY_WATCH"
BROKEN = "BROKEN"
WAIT = "WAIT"
STALE = "STALE"

ALERTING_STATES = {BUY_WATCH, BROKEN}


def evaluate(cfg: Dict, snap: Optional[Dict], risk: Dict, now=None) -> Dict:
    """Return the full assessment for one ticker. `now` is injectable for tests."""
    symbol = cfg["symbol"]
    now = now or now_market()

    if snap is None:
        return {"symbol": symbol, "state": STALE, "reasons": ["no price data this run"],
                "ticket": None, "snap": None, "cfg": cfg}

    price = snap["price"]
    reclaim = cfg.get("reclaim")
    invalidation = cfg.get("invalidation")
    reasons = []

    blackout, why = earnings_blackout(cfg.get("earnings"), cfg.get("earnings_timing"), now)
    if blackout:
        return {"symbol": symbol, "state": HOLD_FIRE, "reasons": [why],
                "ticket": None, "snap": snap, "cfg": cfg}

    if invalidation is not None and price <= invalidation:
        state = BROKEN
        reasons.append("price {:.2f} at or below invalidation {:.2f}".format(price, invalidation))
    elif reclaim is not None and price >= reclaim:
        state = BUY_WATCH
        reasons.append("price {:.2f} reclaimed {:.2f}".format(price, reclaim))
    else:
        state = WAIT
        if reclaim:
            reasons.append("{:.2f} below reclaim {:.2f}".format(reclaim - price, reclaim))
        if invalidation:
            reasons.append("{:.2f} above invalidation {:.2f}".format(price - invalidation, invalidation))

    reasons.extend(_context(snap))

    ticket = None
    if state == BUY_WATCH:
        ticket = _build_ticket(cfg, snap, risk, now)
    elif state == BROKEN:
        ticket = _build_exit_note(cfg, snap)

    return {"symbol": symbol, "state": state, "reasons": reasons,
            "ticket": ticket, "snap": snap, "cfg": cfg}


def _context(snap: Dict) -> list:
    """Non-triggering colour: the stuff worth knowing when you read the alert."""
    out = []
    price, atr14 = snap["price"], snap.get("atr14")

    if snap.get("sma50"):
        side = "above" if price >= snap["sma50"] else "below"
        out.append("{} 50DMA ({:.2f})".format(side, snap["sma50"]))
    if snap.get("sma200"):
        side = "above" if price >= snap["sma200"] else "below"
        out.append("{} 200DMA ({:.2f})".format(side, snap["sma200"]))
    if snap.get("rsi14") is not None:
        tag = " (oversold)" if snap["rsi14"] < 30 else " (overbought)" if snap["rsi14"] > 70 else ""
        out.append("RSI {:.0f}{}".format(snap["rsi14"], tag))
    if snap.get("vol_ratio"):
        out.append("volume {:.1f}x normal".format(snap["vol_ratio"]))
    if atr14 and abs(snap["day_pct"]) > 0:
        moved = abs(price - snap["prev_close"]) / atr14
        if moved >= 2.0:
            out.append("today's move is {:.1f}x ATR - violent".format(moved))
    return out


def _build_ticket(cfg: Dict, snap: Dict, risk: Dict, now=None) -> Dict:
    """
    Construct a prepared BUY ticket, or a refusal explaining why not.

    Guards, in order of how often they should save you money:
      1. violent tape  - a 2.5+ ATR day is not the day to trust a level
      2. gap-through   - if the session never traded at the level, the
                         reclaim never happened; it opened past it
      3. reward:risk   - below the floor, the trade isn't worth the stop
    """
    now = now or now_market()
    price = snap["price"]
    atr14 = snap.get("atr14") or 0.0
    thesis_stop = cfg.get("invalidation")
    target = cfg.get("t1")
    reclaim = cfg.get("reclaim")

    if atr14 and abs(price - snap["prev_close"]) / atr14 >= risk["violent_move_atr"]:
        return _refusal("tape is moving {:.1f}x ATR - too violent to price an entry".format(
            abs(price - snap["prev_close"]) / atr14))

    # A true gap-through: yesterday closed BELOW the level and today never
    # traded down to it. Price simply sitting above a level it reclaimed days
    # ago is continuation, not a gap - don't refuse that forever.
    if reclaim and snap["prev_close"] < reclaim and snap.get("day_low", 0) > reclaim:
        return _refusal("gapped above {:.2f} - never traded at the level, this is a "
                        "different setup than the one the level was drawn for".format(reclaim))

    if not thesis_stop or not target or price <= thesis_stop:
        return _refusal("missing or invalid stop/target")

    sizing_stop, stop_kind = _sizing_stop(cfg, price, atr14, thesis_stop, risk)

    risk_per_share = price - sizing_stop
    reward_per_share = target - price
    if risk_per_share <= 0:
        return _refusal("stop is at or above entry")

    rr = reward_per_share / risk_per_share
    if rr < risk["min_reward_risk"]:
        extra = ""
        if cfg.get("t2"):
            rr2 = (cfg["t2"] - price) / risk_per_share
            extra = " (to T2 it is {:.2f})".format(rr2)
        return _refusal("reward:risk {:.2f} to T1 is below the {:.2f} floor{} - the {} "
                        "sits {:.2f} below entry, which is wide for this target".format(
                            rr, risk["min_reward_risk"], extra, stop_kind, risk_per_share))

    shares = int(risk["account_risk_per_trade_usd"] // risk_per_share)
    if shares < 1:
        return _refusal("stop is {:.2f} wide - one share risks more than the "
                        "{:.0f} budget".format(risk_per_share, risk["account_risk_per_trade_usd"]))

    band_low = round(price - 0.25 * atr14, 2) if atr14 else round(price * 0.995, 2)
    band_high = round(price + 0.25 * atr14, 2) if atr14 else round(price * 1.005, 2)

    # A ticket needs a session left to run in. Near or past the close there
    # is no window to fill it, and an expired-on-arrival ticket reads as
    # actionable when it isn't.
    expires = min(
        now + timedelta(minutes=risk["ticket_expiry_minutes"]),
        session_close(now),
    )
    minutes_left = (expires - now).total_seconds() / 60
    if minutes_left < 10:
        return _refusal("under 10 minutes of session left - no window to work an "
                        "entry. Re-evaluating at tomorrow's open.")

    return {
        "kind": "BUY",
        "valid": True,
        "symbol": cfg["symbol"],
        "side": "buy",
        "shares": shares,
        "limit_band": [band_low, band_high],
        "stop": round(sizing_stop, 2),
        "stop_kind": stop_kind,
        "thesis_stop": round(thesis_stop, 2),
        "target": round(target, 2),
        "risk_usd": round(shares * risk_per_share, 2),
        "reward_usd": round(shares * reward_per_share, 2),
        "reward_risk": round(rr, 2),
        "expires_at": expires.isoformat(),
        "expires_label": fmt_local(expires),
        "void_if": "price leaves {:.2f}-{:.2f}".format(band_low, band_high),
    }


def _sizing_stop(cfg: Dict, price: float, atr14: float, thesis_stop: float, risk: Dict):
    """
    Pick the stop used for POSITION SIZING, which is not always the stop that
    says the idea is wrong.

    `invalidation` is a thesis line - "below here I was wrong about the
    company." On this watchlist those sit 20-40% below the entry trigger,
    which is a fine thesis and a terrible sizing stop: it makes every setup
    fail reward:risk at T1.

    So sizing uses a tighter technical stop:
      - an explicit `entry_stop` in the watchlist, if set
      - otherwise price minus `entry_stop_atr` (default 1.0) ATR

    Two rules keep this honest. The sizing stop can never be LOOSER than the
    thesis stop (that would understate risk), and it can never be so tight it
    sits inside normal daily noise - below 0.5 ATR it will be stopped out by
    nothing at all.

    Returns (stop_price, human_label).
    """
    explicit = cfg.get("entry_stop")
    atr_mult = risk.get("entry_stop_atr", 1.0)

    if explicit is not None:
        candidate, label = float(explicit), "entry stop"
    elif atr14:
        candidate, label = price - atr_mult * atr14, "{:.1f}x ATR stop".format(atr_mult)
    else:
        return thesis_stop, "invalidation"

    # never looser than the thesis line
    if candidate <= thesis_stop:
        return thesis_stop, "invalidation"

    # never inside the noise
    if atr14 and (price - candidate) < 0.5 * atr14:
        candidate = price - 0.5 * atr14
        label = "0.5x ATR floor"

    return round(candidate, 2), label


def _build_exit_note(cfg: Dict, snap: Dict) -> Dict:
    """
    BROKEN fires the stop rule. We do not know Dan's positions, so this is a
    review prompt, never a sized order.
    """
    return {
        "kind": "REVIEW_STOP",
        "valid": True,
        "symbol": cfg["symbol"],
        "message": "{} lost {:.2f}. If you hold this, the stop rule you set has "
                   "triggered. Review - do not auto-act.".format(
                       cfg["symbol"], cfg["invalidation"]),
        "expires_label": "until price reclaims {:.2f}".format(cfg["invalidation"]),
    }


def _refusal(why: str) -> Dict:
    return {"kind": "NO_TICKET", "valid": False, "reason": why}
