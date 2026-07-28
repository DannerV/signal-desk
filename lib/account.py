"""
account.py — broker snapshot, kept OUT of the public repo.

The CI job cannot reach Robinhood; Claude reads the account in-session and
writes a snapshot. That snapshot is portfolio data in a PUBLIC repository, so
it never touches git. It arrives one of two ways:

  ACCOUNT_SNAPSHOT   a JSON blob in a GitHub Secret (what CI uses)
  account.local.json a gitignored file (what local runs use)

Absent both, the engine falls back to the abstract risk budget and says so.
Stale is the normal condition here - a snapshot is a photograph, not a feed -
so every consumer gets told how old it is.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional

log = logging.getLogger("account")

LOCAL_PATH = os.environ.get("ACCOUNT_SNAPSHOT_PATH", "account.local.json")


def load() -> Optional[Dict]:
    raw = os.environ.get("ACCOUNT_SNAPSHOT")
    if raw:
        try:
            return _stamp(json.loads(raw))
        except json.JSONDecodeError as exc:
            log.warning("ACCOUNT_SNAPSHOT is not valid JSON (%s) - ignoring", exc)

    if os.path.exists(LOCAL_PATH):
        try:
            with open(LOCAL_PATH) as fh:
                return _stamp(json.load(fh))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("%s unreadable (%s) - ignoring", LOCAL_PATH, exc)

    return None


def _stamp(snap: Dict) -> Dict:
    """Attach age in hours so callers can decide how much to trust it."""
    taken = snap.get("taken_at")
    snap["age_hours"] = None
    if taken:
        try:
            when = datetime.fromisoformat(taken)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            snap["age_hours"] = round(
                (datetime.now(timezone.utc) - when).total_seconds() / 3600, 1)
        except ValueError:
            pass
    return snap


def holding(snap: Optional[Dict], symbol: str) -> Optional[Dict]:
    if not snap:
        return None
    for pos in snap.get("positions", []):
        if pos.get("symbol") == symbol:
            return pos
    return None


def buying_power(snap: Optional[Dict]) -> Optional[float]:
    if not snap:
        return None
    value = snap.get("buying_power")
    return float(value) if value is not None else None


def account_value(snap: Optional[Dict]) -> Optional[float]:
    if not snap:
        return None
    value = snap.get("total_value")
    return float(value) if value is not None else None
