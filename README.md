# Signal Desk

A level monitor that runs while your computer is off, pushes to your phone,
and costs nothing. It watches the lines you drew and tells you when price
crosses one. It does not trade, and it does not predict.

## What it actually is

Every 5 minutes during market hours, a GitHub Actions job pulls prices,
evaluates each ticker against its levels, and:

- posts a **Discord alert** on any state change into BUY WATCH or BROKEN
- rebuilds a **static dashboard** at `docs/index.html` (free GitHub Pages)
- commits state back so it alerts on *changes*, not on every poll

Cost: $0. Actions is free for public repos, and this uses a few minutes a day.

## The honest limits

- **Cadence is ~5–15 minutes, not real time.** GitHub delays scheduled jobs
  under load. Fine for swing levels; useless for anything intraday-reactive.
- **Data is yfinance** — unofficial, occasionally wrong, delayed. Verify in
  your broker before acting on any number here.
- **Nothing executes.** There is no broker connection in this repo by design.
- **The opinion layer is arithmetic**, not judgment. Every number is
  reproducible from the price frame. That is a feature: the part that must
  never fail is the part that can't hallucinate.

## States

| State | Meaning |
|---|---|
| `BUY_WATCH` | price >= reclaim |
| `BROKEN` | price <= invalidation (your stop rule fired) |
| `HOLD_FIRE` | inside the earnings window — no signal is trustworthy |
| `WAIT` | between the lines |
| `STALE` | no data this run |

## Prepared tickets

When a ticker enters BUY WATCH, the engine tries to build a complete,
specific proposal — shares, limit band, stop, target, R:R, expiry — that you
approve or deny. It refuses to build one when:

1. **The tape is violent** (move >= 2.5x ATR). A day like that is not the day
   to trust a level.
2. **Price gapped through the level** — yesterday closed below it, today
   never traded down to it. The reclaim never happened; it opened past it.
3. **Reward:risk is below 1.5** measured to T1.
4. **The stop is so wide** that one share exceeds the risk budget.

A refusal is a real output, not a failure. Most of the value is here.

Every ticket carries an **expiry and a price band**. A ticket computed at
10:05 during a fast move is garbage by 10:25. Outside its band it voids and
the engine re-evaluates.

## Account awareness (optional)

The CI job cannot reach a broker, so position data arrives as a *snapshot*
Claude reads in-session. It never enters git — this repo is public.

- local runs read `account.local.json` (gitignored)
- CI reads the same JSON from the `ACCOUNT_SNAPSHOT` secret

With a snapshot, risk is sized as a **percentage of the account** (default 2%,
capped by the flat dollar figure — whichever is smaller wins, so a stale
snapshot can never inflate risk), share counts are capped by real buying
power, and alerts show existing holdings plus a concentration warning above
25% in one name. Position detail goes to Discord only, never the public page.

Without a snapshot, everything still works off the flat budget and says so.

Snapshots go stale. Every alert states the age.

## Setup

1. Push this repo to GitHub (public = free Actions minutes).
2. Discord → channel → Integrations → Webhooks → New Webhook → copy URL.
3. Repo → Settings → Secrets → Actions → new secret
   `DISCORD_WEBHOOK_SIGNALS` = that URL.
4. Repo → Settings → Pages → Source: `main` branch, `/docs` folder.
5. Actions tab → enable workflows. Bookmark the Pages URL on your phone and
   Add to Home Screen.

## Local use

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python test_engine.py        # 27 assertions on the guards
./.venv/bin/python check.py --dry-run    # evaluate + render, post nothing
./.venv/bin/python check.py --digest     # post the whole board
```

## Editing levels

`watchlist.json` is the contract. `reclaim` is the bullish trigger,
`invalidation` is the stop, `t1`/`t2` are targets, `earnings` plus
`earnings_timing` (`am` = before open, `pm` = after close) drives the
blackout window, which opens 2 days before the print.

Levels are rules you set in advance, when you were calm. That is the entire
point of writing them down.
