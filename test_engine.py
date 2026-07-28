"""
test_engine.py — the guards are the whole point, so they get tested.

Run: python test_engine.py
No pytest dependency; this has to work in a bare Actions container.
"""

from __future__ import annotations

from datetime import datetime

from lib.clock import MARKET_TZ, earnings_blackout
from lib.engine import BROKEN, BUY_WATCH, HOLD_FIRE, WAIT, evaluate

# Pin a mid-session clock so results never depend on when the suite runs.
MIDDAY = datetime(2026, 7, 27, 11, 0, tzinfo=MARKET_TZ)

RISK = {
    "account_risk_per_trade_usd": 250,
    "min_reward_risk": 1.5,
    "ticket_expiry_minutes": 60,
    "violent_move_atr": 2.5,
    "alert_cooldown_hours": 2,
    "quiet_hours_local": [21, 6],
}

CFG = {"symbol": "TEST", "reclaim": 100, "invalidation": 90, "t1": 120, "t2": 140,
       "earnings": None, "earnings_timing": None}


def snap(price, prev=None, low=None, atr14=4.0, **kw):
    prev = prev if prev is not None else price
    base = {"symbol": "TEST", "price": price, "prev_close": prev,
            "day_pct": (price - prev) / prev * 100 if prev else 0.0,
            "day_high": max(price, prev), "day_low": low if low is not None else min(price, prev),
            "sma50": 95.0, "sma200": 88.0, "rsi14": 55.0, "atr14": atr14,
            "vol_ratio": 1.1, "year_high": 150.0, "year_low": 70.0}
    base.update(kw)
    return base


passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ok   {}".format(label))
    else:
        failed += 1
        print("  FAIL {} {}".format(label, detail))


print("\nstate machine")
check("above reclaim -> BUY_WATCH", evaluate(CFG, snap(105, 104), RISK, MIDDAY)["state"] == BUY_WATCH)
check("below invalidation -> BROKEN", evaluate(CFG, snap(88, 89), RISK, MIDDAY)["state"] == BROKEN)
check("between -> WAIT", evaluate(CFG, snap(95, 95), RISK, MIDDAY)["state"] == WAIT)
check("no data -> STALE", evaluate(CFG, None, RISK, MIDDAY)["state"] == "STALE")

print("\nticket construction")
# CFG: risk/share = 105-90 = 15, reward/share = 120-105 = 15 -> R:R 1.0, below floor
t = evaluate(CFG, snap(105, 104), RISK, MIDDAY)["ticket"]
check("R:R 1.0 refused by floor", not t["valid"], t)
check("refusal names reward:risk", "reward:risk" in t.get("reason", ""), t)

# continuation (already above the level yesterday) must NOT trip the gap guard
cont = evaluate(dict(CFG, t1=135), snap(105, 104), RISK, MIDDAY)["ticket"]
check("continuation is not a gap", cont["valid"], cont)

# widen the target so R:R clears the floor
generous = dict(CFG, t1=135)               # risk 15, reward 30 -> R:R 2.0
t2 = evaluate(generous, snap(105, 104), RISK, MIDDAY)["ticket"]
check("valid ticket when R:R clears", t2["valid"] and t2["kind"] == "BUY")
check("R:R computed 2.0", abs(t2["reward_risk"] - 2.0) < 0.01, t2.get("reward_risk"))
check("size respects $250 budget", t2["risk_usd"] <= 250, t2.get("risk_usd"))
check("shares = 16", t2["shares"] == 16, t2.get("shares"))
check("limit band brackets price", t2["limit_band"][0] < 105 < t2["limit_band"][1])
check("stop matches invalidation", t2["stop"] == 90)
check("expiry present", bool(t2.get("expires_label")))

print("\nguards")
violent = evaluate(generous, snap(105, 92, atr14=4.0), RISK, MIDDAY)["ticket"]  # 13pt move / 4 ATR = 3.25x
check("violent tape refuses ticket", not violent["valid"], violent)
check("violent reason names ATR", "ATR" in violent.get("reason", ""), violent)

gapped = evaluate(generous, snap(105, 96, low=103, atr14=8.0), RISK, MIDDAY)["ticket"]
check("gap-through refuses ticket", not gapped["valid"], gapped)
check("gap reason explains", "gapped" in gapped.get("reason", ""), gapped)

wide = dict(generous, invalidation=-200)
wide_t = evaluate(wide, snap(105, 104), RISK, MIDDAY)["ticket"]
check("absurd stop width refuses", not wide_t["valid"], wide_t)

print("\nearnings blackout")
now = datetime(2026, 7, 27, 12, 0, tzinfo=MARKET_TZ)
check("pm print tomorrow -> blackout", earnings_blackout("2026-07-28", "pm", now)[0])
check("am print in 2 days -> blackout", earnings_blackout("2026-07-29", "am", now)[0])
check("print 10 days out -> NOT blackout", not earnings_blackout("2026-08-06", "am", now)[0])
check("no earnings -> NOT blackout", not earnings_blackout(None, None, now)[0])
after_pm = datetime(2026, 7, 29, 16, 30, tzinfo=MARKET_TZ)
check("pm print + reaction session done -> clear",
      not earnings_blackout("2026-07-28", "pm", after_pm)[0])
hold = evaluate(dict(CFG, earnings="2026-07-28", earnings_timing="pm"), snap(105, 104), RISK, MIDDAY)
check("blackout overrides BUY_WATCH", hold["state"] == HOLD_FIRE)
check("blackout suppresses ticket", hold["ticket"] is None)

print("\nBROKEN never sizes an order")
b = evaluate(CFG, snap(88, 91), RISK, MIDDAY)["ticket"]
check("exit is review-only", b["kind"] == "REVIEW_STOP" and "shares" not in b)

print("\n{} passed, {} failed".format(passed, failed))
raise SystemExit(1 if failed else 0)
