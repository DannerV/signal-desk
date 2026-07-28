"""
check.py — one-shot runner. This is what GitHub Actions calls every 5 min.

  1. load watchlist + prior state
  2. pull prices
  3. evaluate each ticker against its levels
  4. alert on state CHANGES into BUY_WATCH / BROKEN (cooldown + quiet hours)
  5. rewrite the static dashboard
  6. persist state (the workflow commits it back)

Flags:
  --digest   send the full board to Discord regardless of changes
  --dry-run  evaluate and render, but never post
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Dict, List

import render
from lib import notify, store
from lib.clock import fmt_local, in_quiet_hours, is_market_open, now_local
from lib.data import fetch
from lib.engine import ALERTING_STATES, evaluate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("check")


def load_watchlist(path: str = "watchlist.json") -> Dict:
    with open(path) as fh:
        return json.load(fh)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--digest", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_watchlist()
    risk = config["risk"]
    tickers = config["tickers"]
    symbols = [t["symbol"] for t in tickers]

    log.info("checking %d symbols | market_open=%s", len(symbols), is_market_open())

    snapshots = fetch(symbols)
    state = store.load()

    results: List[Dict] = []
    alerts: List[Dict] = []

    for cfg in tickers:
        result = evaluate(cfg, snapshots.get(cfg["symbol"]), risk)
        results.append(result)

        symbol = result["symbol"]
        new_state = result["state"]
        old_state = store.previous_state(state, symbol)
        changed = old_state is not None and old_state != new_state
        first_seen = old_state is None

        should_alert = (
            new_state in ALERTING_STATES
            and (changed or (first_seen and new_state in ALERTING_STATES))
            and not store.in_cooldown(state, symbol, risk["alert_cooldown_hours"])
            and not in_quiet_hours(*risk["quiet_hours_local"])
        )

        if should_alert:
            alerts.append(result)
        log.info("%-6s %-9s -> %-9s%s", symbol, old_state or "new", new_state,
                 "  ALERT" if should_alert else "")

        store.record(state, symbol, new_state, alerted=should_alert)

    if args.dry_run:
        log.info("dry run - not posting. %d alert(s) would have fired", len(alerts))
    else:
        for result in alerts:
            notify.send_alert(result)
        if args.digest:
            notify.send_digest(results, "Pre-market digest — {}".format(fmt_local(now_local())))

    path = render.write(results)
    log.info("dashboard written to %s", path)

    if not args.dry_run:
        store.save(state)

    return 0


if __name__ == "__main__":
    sys.exit(main())
