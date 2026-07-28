"""
notify.py — Discord webhook alerts with the prepared ticket inline.

One channel. Alerts fire only on a state change into BUY_WATCH or BROKEN,
after cooldown and quiet-hours checks upstream.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List

import requests

log = logging.getLogger("notify")

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_SIGNALS", "")

COLOR_BUY = 0x57F287     # green
COLOR_BROKEN = 0xED4245  # red
COLOR_INFO = 0x5865F2    # blurple

STATE_COLORS = {"BUY_WATCH": COLOR_BUY, "BROKEN": COLOR_BROKEN}
STATE_EMOJI = {"BUY_WATCH": "🟢", "BROKEN": "🔴", "HOLD_FIRE": "⏸️",
               "WAIT": "⚪", "STALE": "⚠️"}


def _post(payload: Dict) -> bool:
    if not WEBHOOK:
        log.warning("DISCORD_WEBHOOK_SIGNALS unset - printing instead")
        print(payload)
        return False
    try:
        resp = requests.post(WEBHOOK, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.error("discord post failed: %s", exc)
        return False


def _sizing_lines(ticket: Dict) -> str:
    """Budget, buying-power cap and position context. Private channel only."""
    bits = [b for b in (ticket.get("budget_note"), ticket.get("size_note")) if b]
    lines = ["_{}_".format(" ".join(bits))] if bits else []
    lines += ["• " + n for n in ticket.get("position_notes", [])]
    return ("\n".join(lines) + "\n") if lines else ""


def send_alert(result: Dict) -> bool:
    """One embed per state change, ticket included when we built one."""
    symbol = result["symbol"]
    state = result["state"]
    snap = result["snap"]
    ticket = result.get("ticket")

    title = "{} {} - {}".format(STATE_EMOJI.get(state, ""), symbol, state.replace("_", " "))

    fields: List[Dict] = [
        {"name": "Price", "value": "${:.2f}  ({:+.2f}%)".format(snap["price"], snap["day_pct"]),
         "inline": True},
        {"name": "Levels", "value": "reclaim ${}\nstop ${}".format(
            result["cfg"].get("reclaim"), result["cfg"].get("invalidation")), "inline": True},
    ]

    if ticket and ticket.get("valid") and ticket["kind"] == "BUY":
        fields.append({
            "name": "📋 PREPARED TICKET - approve or deny",
            "value": (
                "**BUY {shares} {symbol}**\n"
                "limit band  ${band_low} - ${band_high}\n"
                "stop  ${stop}  ({stop_kind})   target  ${target}\n"
                "thesis breaks below  ${thesis}\n"
                "risk  ${risk} → reward  ${reward}   (R:R {rr})\n"
                "{sizing}"
                "*expires {expires}*\n"
                "*voids if {void}*"
            ).format(
                shares=ticket["shares"], symbol=symbol,
                band_low=ticket["limit_band"][0], band_high=ticket["limit_band"][1],
                stop=ticket["stop"], stop_kind=ticket.get("stop_kind", "stop"),
                thesis=ticket.get("thesis_stop", "—"), target=ticket["target"],
                risk=ticket["risk_usd"], reward=ticket["reward_usd"],
                rr=ticket["reward_risk"], expires=ticket["expires_label"],
                sizing=_sizing_lines(ticket),
                void=ticket["void_if"],
            ),
            "inline": False,
        })
    elif ticket and ticket["kind"] == "REVIEW_STOP":
        fields.append({"name": "⚠️ Stop rule triggered", "value": ticket["message"],
                       "inline": False})
    elif ticket and not ticket.get("valid"):
        fields.append({"name": "No ticket prepared", "value": ticket["reason"], "inline": False})

    fields.append({"name": "Context", "value": "\n".join("• " + r for r in result["reasons"]),
                   "inline": False})

    return _post({
        "embeds": [{
            "title": title,
            "color": STATE_COLORS.get(state, COLOR_INFO),
            "fields": fields,
            "footer": {"text": "signal desk • nothing executes without your approval"},
        }]
    })


def send_digest(results: List[Dict], header: str) -> bool:
    lines = []
    for r in sorted(results, key=lambda x: x["symbol"]):
        snap = r["snap"]
        price = "${:.2f} ({:+.2f}%)".format(snap["price"], snap["day_pct"]) if snap else "no data"
        lines.append("{} **{}**  {}  — {}".format(
            STATE_EMOJI.get(r["state"], ""), r["symbol"], price, r["state"].replace("_", " ")))

    return _post({
        "embeds": [{
            "title": header,
            "color": COLOR_INFO,
            "description": "\n".join(lines),
            "footer": {"text": "signal desk • notify only"},
        }]
    })
