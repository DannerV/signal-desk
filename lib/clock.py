"""
clock.py — market session and quiet-hours logic.

All decisions are made in US/Eastern (the market's timezone); all display
and quiet-hours are in TZ_LOCAL (Dan's, America/Los_Angeles).
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from typing import Tuple
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("America/New_York")
LOCAL_TZ = ZoneInfo(os.environ.get("TZ_LOCAL", "America/Los_Angeles"))

OPEN_TIME = time(9, 30)
CLOSE_TIME = time(16, 0)

# 2026 US market holidays (NYSE). Update annually.
HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
}


def now_market() -> datetime:
    return datetime.now(MARKET_TZ)


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def is_trading_day(when: datetime) -> bool:
    return when.weekday() < 5 and when.date() not in HOLIDAYS_2026


def is_market_open(when: datetime = None) -> bool:
    when = when or now_market()
    if not is_trading_day(when):
        return False
    return OPEN_TIME <= when.time() < CLOSE_TIME


def session_close(when: datetime = None) -> datetime:
    """The 4pm ET close of the session `when` falls in."""
    when = when or now_market()
    return when.replace(hour=16, minute=0, second=0, microsecond=0)


def in_quiet_hours(start_hour: int, end_hour: int, when: datetime = None) -> bool:
    """Quiet window wraps midnight, e.g. 21 -> 6."""
    hour = (when or now_local()).astimezone(LOCAL_TZ).hour
    if start_hour <= end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def earnings_blackout(
    earnings_date: str, timing: str, when: datetime = None, lead_days: int = 2
) -> Tuple[bool, str]:
    """
    True while we are inside the window around a print and should not act.

    The window OPENS `lead_days` calendar days before the report - not the
    moment the date is known. A print three weeks out is not a reason to
    stop trading a name; a print tomorrow is.

    'am' reports land before the open, so the blackout ends at that day's
    close (the reaction session). 'pm' reports land after the close, so the
    blackout runs through the NEXT session's close.
    """
    if not earnings_date:
        return False, ""

    when = when or now_market()
    day = datetime.strptime(earnings_date, "%Y-%m-%d").date()

    blackout_start = datetime.combine(
        day - timedelta(days=lead_days), OPEN_TIME, tzinfo=MARKET_TZ
    )
    if when < blackout_start:
        return False, ""

    if (timing or "pm").lower() == "am":
        blackout_end = datetime.combine(day, CLOSE_TIME, tzinfo=MARKET_TZ)
    else:
        nxt = day + timedelta(days=1)
        while nxt.weekday() >= 5 or nxt in HOLIDAYS_2026:
            nxt += timedelta(days=1)
        blackout_end = datetime.combine(nxt, CLOSE_TIME, tzinfo=MARKET_TZ)

    if when < blackout_end:
        label = "before the open" if (timing or "pm").lower() == "am" else "after the close"
        return True, "earnings {} {} - holding fire".format(day.isoformat(), label)
    return False, ""


def fmt_local(when: datetime) -> str:
    return when.astimezone(LOCAL_TZ).strftime("%a %b %d, %-I:%M%p PT")
