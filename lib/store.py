"""
store.py — JSON state persisted back into the repo by the Actions run.

Holds last known state per symbol (so we alert on CHANGES, not on every
poll) and the last alert timestamp (so we respect the cooldown).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

log = logging.getLogger("store")

STATE_PATH = os.environ.get("STATE_PATH", "state/state.json")


def load() -> Dict:
    if not os.path.exists(STATE_PATH):
        return {"symbols": {}, "last_run": None}
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("state unreadable (%s) - starting fresh", exc)
        return {"symbols": {}, "last_run": None}


def save(state: Dict) -> None:
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)


def previous_state(state: Dict, symbol: str) -> Optional[str]:
    return state.get("symbols", {}).get(symbol, {}).get("state")


def record(state: Dict, symbol: str, new_state: str, alerted: bool) -> None:
    entry = state.setdefault("symbols", {}).setdefault(symbol, {})
    entry["state"] = new_state
    entry["seen_at"] = datetime.now(timezone.utc).isoformat()
    if alerted:
        entry["last_alert"] = entry["seen_at"]


def in_cooldown(state: Dict, symbol: str, hours: float) -> bool:
    last = state.get("symbols", {}).get(symbol, {}).get("last_alert")
    if not last:
        return False
    try:
        when = datetime.fromisoformat(last)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - when < timedelta(hours=hours)
