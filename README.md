# EURUSD / XAUUSD HalfTrend Signal Alert System

A free, automated system that watches EURUSD (5-minute candles) and XAUUSD/Gold (3-minute candles), detects trend-flip signals using your HalfTrend strategy, and emails you a fully worked trade plan the moment one forms — entry, stop loss, three targets, position size per account, and daily/weekly/monthly/yearly performance journaling.

## What this does — and does not do

- ✅ Watches price, detects signals, calculates position sizing, sends email alerts.
- ✅ Journals every signal's outcome (stop / TP1 / TP2 / TP3) and reports win rate and % returns daily, weekly, monthly, and yearly.
- ❌ **Never places, modifies, or touches a real trade.** This is read-only market data and notification only — you decide every entry yourself.
- ❌ Does not manage open positions in a broker account, and does not know your real account balance — position sizing is calculated risk-based from the account sizes you configure, not read from a live broker connection.

Full technical design record — every decision and why it was made — lives in `CLAUDE.md` at the repo root, for anyone (human or AI) picking this project back up later.

## One-time setup

### 1. Get an OANDA API key (optional — only if you have a legitimate OANDA account)

The system works out of the box with no market-data account at all, using free Yahoo Finance data. If you do have an OANDA account:

1. Log into your OANDA account at oanda.com
2. Go to **Manage API Access** in account settings
3. Click **Generate** to create a Personal Access Token — copy it immediately, it's shown only once
4. That's your `OANDA_API_KEY`. You don't need an account ID for this system.

If you skip this, leave `OANDA_API_KEY` unset — the system automatically uses Yahoo Finance instead, with no setup needed. See `CLAUDE.md` section 1/7 for the trade-offs between the two.

### 2. Create a Gmail App Password

This is what lets the system send email through your Gmail account without using your real password.

1. Go to myaccount.google.com/security and turn on **2-Step Verification** (required first)
2. Go to myaccount.google.com/apppasswords
3. Give it a name (e.g. "trading-alerts"), click **Create**
4. Copy the 16-character password shown — that's your `GMAIL_APP_PASSWORD`. Remove the spaces when you use it.

A dedicated Gmail address just for this bot (rather than your everyday one) is a reasonable, zero-cost precaution, but not required.

### 3. Set up local testing (optional)

```
cp .env.example .env
```
Fill in the values in `.env`. This file is git-ignored — it never gets committed. Then:
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/          # run the test suite
python -m src.health_check        # confirm your data source(s) are reachable
python -m src.validate_signals    # see recent real signals, to cross-check against TradingView
```

### 4. Add GitHub repo secrets (required for the automated/deployed version)

Go to the repo's **Settings → Secrets and variables → Actions → New repository secret**, and add each of the following (values from your local `.env` — never paste secrets into a chat or anywhere public):

| Secret | Required? | Purpose |
|---|---|---|
| `GMAIL_SENDER` | Yes | sending Gmail address |
| `GMAIL_APP_PASSWORD` | Yes | the App Password from step 2 |
| `ALERT_RECIPIENT_EMAIL` | Yes | where alerts/journals go |
| `ACCOUNT_SIZES` | Yes | comma-separated, e.g. `6000,10000,25000` |
| `RISK_PERCENTAGES` | Yes | comma-separated, e.g. `0.5,0.75,1` |
| `OANDA_API_KEY` | No | only if you have an OANDA account |
| `OANDA_ENVIRONMENT` | No | `practice` or `live`, defaults to `practice` |
| `EURUSD_AMPLITUDE` / `EURUSD_CHANNEL_DEVIATION` / `EURUSD_BASE_RISK_MULT` | No | HalfTrend strategy tuning for EURUSD, defaults to `20`/`2.0`/`3.0` |
| `XAUUSD_AMPLITUDE` / `XAUUSD_CHANNEL_DEVIATION` / `XAUUSD_BASE_RISK_MULT` | No | same, for XAUUSD |
| `SESSION_START` / `SESSION_END` | No | trading window, `HH:MM` IST, defaults to `06:00`/`21:30` |
| `TRADING_DAYS` | No | comma-separated weekday numbers (Monday=0), defaults to `0,1,2,3,4` (Mon-Fri) |

All secrets go in the **Secrets** tab, not **Variables** — the workflows reference them as `secrets.*`.

## Changing your configuration later

Every value above is read fresh on every run — **change a GitHub secret and it takes effect on the very next scheduled check, no code change, no redeploy.** Add a 4th account size, widen the trading hours, retune the strategy — just edit the secret.

## How it runs

Three scheduled GitHub Actions workflows (`.github/workflows/`), fully automatic once the secrets above are set — nothing to start or babysit:

- **EURUSD HalfTrend Check** — checks every 5 minutes
- **XAUUSD HalfTrend Check** — checks every 3 minutes
- **Daily Trade Journal** — runs once/day after session close; also sends weekly/monthly/yearly rollups on the right calendar boundaries

Each one independently re-checks the actual configured trading window before doing anything — the schedule is just an approximate trigger, not the real gate.

## How to verify it's working

Go to the **Actions** tab on the repo. Each run shows as ✅ or ❌:
- A ✅ with a log line like `"outside trading session -- skipping"` is normal and expected outside trading hours — not a failure.
- A ✅ with `"sent '...'"` means a real signal fired and an email went out.
- A ❌ is a real problem — click into it, expand the failing step, and the Python error/traceback will be at the bottom of the log.

You can also trigger any workflow manually anytime via the **"Run workflow"** button on that workflow's page, without waiting for its schedule — useful for testing.

## A few things worth knowing

- **This repo is public.** That was a deliberate choice (see `CLAUDE.md`) — GitHub Actions is free and unlimited on public repos, while private repos are capped at 2,000 minutes/month, which this system's polling frequency would exceed within days. Your secrets (API keys, passwords, account sizes) stay encrypted and hidden regardless of repo visibility — what's visible publicly is the source code, the Actions run logs (which show signal timing/direction, not dollar amounts), and the trade journal log.
- **HalfTrend signal accuracy was cross-checked against a live TradingView chart** before being trusted (`CLAUDE.md` section 3) — if you ever change the strategy port itself, re-validate the same way with `python -m src.validate_signals` before trusting new output.
- **This is a signal tool, not a broker.** Position sizes shown are risk-based calculations only — always confirm your broker accepts the calculated lot size, and confirm the live spread before entering; the shown entry price is never guaranteed to be your fill price.
