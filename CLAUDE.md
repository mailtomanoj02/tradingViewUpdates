# CLAUDE.md — Automated Trading Alert System (EURUSD 5m + XAUUSD 3m)

This file is the standing brief for anyone (human or Claude) working in this repo. Read it before touching code. It exists so the *why* behind every rule survives, not just the *what* — because in a trading system, the why is what stops someone from "helpfully" breaking something.

Read this like a trading desk risk manual, not a feature list. The person who wrote the spec has been trading long enough to know exactly where systems like this quietly go wrong, and every rule below exists because of a specific failure mode, not because it sounded thorough.

Source specs (do not delete, do not treat as superseded — this file is a distillation, not a replacement):
- `~/Downloads/Claude_Code_Build_Prompt.md` — literal build spec: tech stack, base formulas, file layout, testing requirements. **Its OANDA-specific instructions are superseded — see the data-source note in §1.**
- `~/Downloads/Multi_Pair_Trading_Alert_System_PRD.md` — PRD: the enriched email (R:R, ATR snapshot, timestamp, dollar risk, spread caution), risks/trade-offs, milestones, success criteria. Same OANDA caveat applies.
- `reference/halftrend_source.pine` — the **actual** Pine Script v6 indicator ("HalfTrend Long/Short Signal Engine [Ramesh]", credit: everget for the original HalfTrend logic, CC BY-NC-SA 4.0). This is the ground truth for §3 below — it superseded and corrected an earlier paraphrased description of the algorithm that had gaps (missing `nextTrend` staging variable, missing exact `up`/`down` baseline update rules, missing ATR smoothing method).

Where sources disagree: **for the strategy math, the `.pine` file always wins** — it's the literal algorithm, not a description of it. For the email format, sizing config, and everything non-strategy, the PRD wins over the build prompt (it's the later, more complete spec, v4). **For market data specifically, this file (§1, §8) wins over both** — OANDA is not usable for this build (India-resident account restriction; see project history), and `yfinance` is the replacement.

---

## 1. What this is, in one paragraph

A free, zero-infrastructure-cost robot that watches EURUSD (5m) and XAUUSD/Gold (3m) independently, runs a ported HalfTrend trend-flip strategy on each, and — only within the 6:00 AM–9:30 PM IST trading session — emails a fully worked trade plan (entry, stop, three targets, R:R, ATR context, position size and dollar risk across three accounts) the moment a signal closes. It never places a trade. It never touches an account. Its entire job is to hand a trader a clean, correctly-sized decision the instant one is available, and otherwise stay completely silent.

Everything below exists to protect that one job.

**Market data source decision:** the original spec assumed OANDA for market data. OANDA does not onboard India-resident retail clients, so **`yfinance`** (unofficial Yahoo Finance data, tickers `EURUSD=X` and `GC=F`) is the default/fallback source — free, no API key, no account, works from anywhere. This was a deliberate, researched trade-off (see §7 for what it costs in reliability), not a default nobody thought about: it was chosen over (a) paying ~$29/mo for an official gold data feed and (b) MetaTrader 5 via an India-friendly broker, whose Python package is Windows-only and doesn't run on free GitHub Actions Linux runners.

**Dual-provider architecture:** the system is built OANDA-primary, yfinance-fallback (`src/data_provider.py`), not yfinance-only — so if a legitimate OANDA account ever becomes available (India-eligible route, different jurisdiction, etc.), it starts using it automatically the moment `OANDA_API_KEY` is set, with zero code changes. `OANDA_API_KEY` is set in this deployment (an OANDA UK account, §10) — both EURUSD and XAUUSD now genuinely use OANDA, not yfinance, in normal operation. **Do not use an OANDA account opened under misrepresented residency information to populate this key** — that was explicitly considered and rejected during this project's build (project history); the fallback design exists precisely so the system works correctly and legitimately without one. Concretely: `data_provider.fetch_candles(symbol, lookback_bars)` tries OANDA only if `OANDA_API_KEY` is set, falls back to yfinance on any OANDA failure (logging why to stderr — never a silent swap, per §2's fail-loud rule), and returns `(candles_df, source_label)`. The source label must be surfaced in every alert email (§6) — the trader reading it should always know whether a signal came from broker-grade OANDA data or the unofficial yfinance fallback, since that materially affects how much to trust it (§7).

**XAUUSD's OANDA path was silently broken from initial deployment until this was caught (project history) — worth understanding if you touch `oanda_client.py` again.** OANDA's v20 API has no native 3-minute granularity (valid minute values skip straight from `M2` to `M4`); the original code requested the invalid `"M3"`, which made every single XAUUSD OANDA fetch fail and silently fall back to yfinance, on every run, from day one — `OANDA_API_KEY` being configured didn't matter. The practical cost: every XAUUSD alert was priced off yfinance's `GC=F` futures contract (the ~1.3% premium over spot already documented above) instead of OANDA's true spot `XAU_USD`, and inherited yfinance's extra resampling latency on top — this is very likely the root cause of XAUUSD alerts historically arriving noticeably later than EURUSD's relative to candle close. Fixed by fetching OANDA's native `M1` for XAUUSD and resampling to 3-minute bars ourselves (`market_data_client.resample_candles`/`drop_unclosed_bar`, the same technique already used for the yfinance fallback) — verified live against the real account, confirming OANDA XAUUSD now returns fresher, true-spot data. One knock-on fix that came with it: OANDA caps a single request at 5000 candles, and the journal's larger lookback (`JOURNAL_LOOKBACK_BARS=3000`, §12) needs ~9000 raw M1 candles for XAUUSD after the M1→3m change — `oanda_client.py` now paginates backward in batches when a request would exceed that cap, tested against real 3000-bar XAUUSD fetches. The lesson: an OANDA fetch failure is caught and logged to stderr per the fail-loud rule, but a failure that happens on *every single run* is easy to mistake for "the fallback design working as intended" rather than a bug — if a symbol seems to always be using the yfinance source label, verify the OANDA request parameters are actually valid before assuming the fallback itself is the problem.

---

## 2. Non-negotiables (the safety rails — do not "improve" these away)

These aren't style preferences. Each one maps to a specific way this kind of system fails in the real world:

- **Read-only market data only.** No order placement, no account modification, ever. This is a notification system wearing a trading-system's clothes — it must never grow the ability to touch a live account, even as a "convenience" feature later.
- **EURUSD and XAUUSD are never combined into one email.** A trader glancing at a phone notification under time pressure needs to instantly know which instrument and which chart it refers to. A merged email is a misread waiting to happen.
- **No data fetch, no signal evaluation, no email outside the configured trading window (default 06:00–21:30 IST, Mon-Fri).** Not "don't send outside the window" — *don't even look* outside the window. Liquidity and spread behavior outside session hours make signals there unreliable garbage; evaluating them at all invites false confidence. The window and trading days are configurable (`SESSION_START`/`SESSION_END`/`TRADING_DAYS`, §10, `session.py`) — the non-negotiable is that *some* window is always enforced before any work happens, not that it's permanently fixed at these specific hours/days.
- **Signals only on confirmed/closed candles.** Never evaluate or alert on an in-progress bar. A signal that can flip before the bar closes is a repainting indicator — the single fastest way to destroy trust in a trend-following system and blow up an account trading phantom signals.
- **Stateless per run, no database.** Each scheduled run fetches the latest candle, checks for one signal, and exits. Don't add persistence "to be safe" — it adds failure surface for zero benefit given the requirements.
- **Fail loud, not silent.** If the data fetch errors (or returns something malformed/empty — `yfinance` will do this, see §7), if email send fails, if the HalfTrend calc throws — let it fail visibly in the GitHub Actions run log. A silently-swallowed exception on a trading alert system means a missed signal nobody knows was missed. That's worse than no system at all, because it creates false confidence that "no email = no signal." **This matters more than usual here**, precisely because the data source is an unofficial API that can degrade without warning — a run must be able to distinguish "checked, no signal" from "couldn't actually check" and make the second one loud.
- **Out-of-scope stays out of scope, on purpose.** No auto-trading, no position/PnL tracking, no live spread or news-calendar feed. Every one of these looks like an easy, obviously-useful addition. Resist. Scope creep here is how a signal tool quietly turns into an unaudited trading bot.

---

## 3. Strategy logic — HalfTrend (port this exactly, verify it obsessively)

This is the entire product. Everything else — email, sizing, scheduling — is plumbing around this calculation. A subtly wrong port is worse than a crash: it produces confident, well-formatted, wrong trade plans. The algorithm below is transcribed directly from `reference/halftrend_source.pine` (the real indicator, not a paraphrase) — port it line-for-line, don't "clean it up" or simplify it, and don't trust your own restatement of it over the `.pine` file if they ever seem to differ.

**Inputs:** `amplitude` (Pine default 20), `channelDeviation` (Pine default 2.0, used only for the visual ATR channel bands — see note below), `baseRiskMult` (Pine default 3.0). These are configurable per instrument via env vars (`src/halftrend.py`'s `strategy_params(symbol)`, e.g. `EURUSD_AMPLITUDE`, `XAUUSD_BASE_RISK_MULT`) and currently tuned differently per instrument in this deployment — see §10. Don't assume both instruments run identical settings; always check the actual configured values (or the params printed by `validate_signals.py`), not just the Pine defaults quoted here.

**Core volatility unit:** `atr2 = ATR(100) / 2`, where ATR(100) is **Wilder's smoothed ATR** (Pine's `ta.atr()` uses RMA/Wilder smoothing, i.e. `rma = prev_rma + (tr - prev_rma) / length`) — **not** a simple rolling mean of true range. Using a plain rolling average here will silently produce a different `atr2` and therefore different SL/target distances on every signal. This is the single easiest place to get a "close but wrong" port.

**Per-bar inputs:**
- `highPrice` = the actual `high` at the bar index of the highest high over the trailing `amplitude`-bar window (Pine's `high[abs(highestbars(high, amplitude))]` — i.e. find *which* bar had the highest high in the lookback, then read that bar's high; not just `rolling(amplitude).max()`)
- `lowPrice` = same idea for the lowest low (`low[abs(lowestbars(low, amplitude))]`)
- `highma` = SMA(high, amplitude); `lowma` = SMA(low, amplitude)

**Persistent state carried bar-to-bar** (these are `var`-declared in Pine, meaning they hold their value across bars — in the Python port this must be genuine loop state, not something recomputed fresh each bar from a small window; see the warm-up note below): `trend` (0 = bullish, 1 = bearish, starts at 0), `nextTrend` (starts at 0), `maxLowPrice` (starts at first bar's `low`), `minHighPrice` (starts at first bar's `high`), `up` (starts 0.0), `down` (starts 0.0).

**Trend Logic Matrix — runs every bar, in this exact branching order:**
```
if nextTrend == 1:
    maxLowPrice = max(lowPrice, maxLowPrice)
    if highma < maxLowPrice and close < prevLow:      # prevLow = previous bar's low
        trend = 1
        nextTrend = 0
        minHighPrice = highPrice
else:
    minHighPrice = min(highPrice, minHighPrice)
    if lowma > minHighPrice and close > prevHigh:      # prevHigh = previous bar's high
        trend = 0
        nextTrend = 1
        maxLowPrice = lowPrice
```
Note `nextTrend` is a *staging* variable distinct from `trend` — don't collapse them into one variable, the two-variable handoff is what makes the flip logic work correctly one bar at a time.

**Baseline (`up`/`down`) update — also runs every bar, after the block above:**
```
if trend == 0:
    if prevTrend is not None and prevTrend != 0:        # just flipped bearish -> bullish this bar
        up = prevDown if prevDown is not None else down  # carry the last bearish baseline forward as continuity
    else:
        up = maxLowPrice if prevUp is None else max(maxLowPrice, prevUp)
else:  # trend == 1
    if prevTrend is not None and prevTrend != 1:        # just flipped bullish -> bearish this bar
        down = prevUp if prevUp is not None else up
    else:
        down = minHighPrice if prevDown is None else min(minHighPrice, prevDown)
```
`htLine = up if trend == 0 else down` — this is the reference baseline (not directly needed for the alert email, but useful for validating the port visually against the TradingView plot).

**`channelDeviation` note:** in the source script this only feeds `atrHigh`/`atrLow` (`dev = channelDeviation * atr2`, then `atrHigh/atrLow = baseline ± dev`), which are plotted **channel bands for visualization only** — they do not feed `buySignal`/`sellSignal` or the entry/SL/target math anywhere. Do not port the channel bands; keep `channelDeviation` as a stored/configurable input for fidelity, but it has no effect on alert output.

**Signals (closed bars only):**
- `buySignal` = `trend == 0 and prevTrend == 1` (just flipped bearish→bullish), evaluated only on a confirmed/closed candle
- `sellSignal` = `trend == 1 and prevTrend == 0` (just flipped bullish→bearish), evaluated only on a confirmed/closed candle

**Entry / SL / Targets on signal** (unchanged from the original spec, confirmed against the source script's `activeSL`/`activeTP1-3` block):
```
dist = atr2 * baseRiskMult

LONG (buySignal):
  entry = close
  stopLoss = close - dist
  target1 = close + dist
  target2 = close + (dist * 2)
  target3 = close + (dist * 3)

SHORT (sellSignal):
  entry = close
  stopLoss = close + dist
  target1 = close - dist
  target2 = close - (dist * 2)
  target3 = close - (dist * 3)
```

**What NOT to port:** the source script also includes a multi-asset scanner dashboard (`sym1`-`sym5`, `request.security` calls), a win/loss tracker with a performance table, gradient fills, and label plotting. None of that is needed for this project — it's TradingView visualization/bookkeeping, not signal logic. Port only the core engine above (ATR, `highPrice`/`lowPrice`, `highma`/`lowma`, the trend/nextTrend matrix, the `up`/`down` baseline, `buySignal`/`sellSignal`, and the entry/SL/target math).

**Critical operational note — state warm-up:** because `trend`, `maxLowPrice`, `minHighPrice`, `up`, and `down` are recursive (each bar's value depends on the previous bar's), you cannot compute "the current signal" from just the latest few candles. Each stateless run must fetch enough historical candles (several hundred+, comfortably covering ATR(100)'s warm-up and enough bars for the trend state to have stabilized past its arbitrary bar-1 seed values), then iterate the full state machine forward bar-by-bar from the start of that window to the latest closed bar, and only then check whether a flip happened on the last bar versus the one before it. Fetching too short a window and computing "in isolation" will produce **wrong `maxLowPrice`/`minHighPrice`/baseline values and false or missed signals** — this is a real, easy-to-make bug, not a hypothetical one. Pick and document a fixed lookback (e.g. 1000 candles) that's clearly enough for both instruments/timeframes, and log how many warm-up bars were used on every run.

**Yahoo/`yfinance` lookback caps (relevant to warm-up above):** Yahoo Finance limits intraday history by interval — 5-minute bars are available for roughly the trailing 60 days, 1-minute bars for roughly the trailing 7 days. EURUSD (5m native) fits comfortably: ~1000 bars × 5min ≈ 3.5 days of history, well inside the 60-day cap. XAUUSD has no native 3-minute interval on Yahoo (same gap as most providers) — build it by pulling 1-minute bars and resampling to 3-minute candles; ~1000 3-min bars ≈ 2 days of underlying 1-minute data, which is comfortably inside the 7-day 1-minute cap, but don't push the lookback much larger without checking against that 7-day ceiling.

**Mandatory validation step:** after building this, walk recent historical candles for both instruments and print every detected signal (buy/sell, bar time, entry/SL/targets) so it can be manually cross-checked against the live TradingView HalfTrend chart, bar-for-bar. Do not skip this and do not consider the port "done" until it's been checked — a Pine→Python port that looks right and trades wrong is the single biggest risk in this entire project (see §8, Milestone 6: run in parallel with TradingView for several days before trusting this with a real account).

---

## 4. Position sizing & risk math (exact formulas — this is real money math)

Every signal computes lot size **and dollar risk** across the full account-size × risk-percent matrix. Get a unit conversion wrong here once, and it's wrong in *every single email* until someone notices — there's no visual sanity check on a number that merely looks plausible. Treat this module with the same care as the strategy logic.

**Config (env-driven, never hardcoded):**
```
ACCOUNT_SIZES=6000,10000,25000
RISK_PERCENTAGES=0.5,0.75,1
```
Adding a 4th account size or risk level must require zero code changes — the matrix is generated dynamically from these lists, both in the calculator and in the email table header/columns.

**EURUSD** (1 standard lot = 100,000 units, pip = 0.0001, $10 risk per pip per standard lot):
```
stopLossPips = |entry - stopLoss| / 0.0001
dollarRisk = accountSize * (riskPercent / 100)
lotSize = dollarRisk / (stopLossPips * 10)
```

**XAUUSD** (1 standard lot = 100 troy oz, $100 risk per $1 move per standard lot):
```
stopLossDollars = |entry - stopLoss|
dollarRisk = accountSize * (riskPercent / 100)
lotSize = dollarRisk / (stopLossDollars * 100)
```

Round lot size to 2 decimals. Build as one reusable function: takes symbol, entry, stopLoss (accountSize/riskPercent lists come from env) and returns the full matrix of lot size + dollar risk.

**Trader's note:** this system computes *risk-based* lot size only. It does not check broker margin/leverage limits or lot-step minimums (many brokers step in 0.01 increments — that's covered by rounding, but max lot and margin availability are not checked at all). The email is a sizing recommendation, not a guarantee the broker will accept the order as-is. Never let the code or the email copy imply otherwise.

---

## 5. Volatility & context enrichments (PRD additions on top of the base spec)

These come from the PRD and go beyond the base build prompt — implement them too, they're part of the target spec, not optional polish:

- **Risk:Reward per target** — `R:R = |target - entry| / |stopLoss - entry|`. By construction this is 1:1 / 1:2 / 1:3 for T1/T2/T3, but compute it explicitly rather than hardcoding the labels — it's a correctness check on the target math, not just a display value.
- **ATR volatility snapshot** — the ATR value already computed inside the HalfTrend engine (don't recompute it separately), shown as one line with a relative label (below-average / normal / above-average) derived by comparing current ATR to its own recent rolling average. This needs no new data source. Keep it exactly that simple — see §7 on why not to oversell its precision. **Exact rule** (`src/halftrend.py`'s `atr_volatility_label`, since the spec didn't pin one down): compare the latest raw ATR to the trailing 50-bar mean, ±10% band — below that band = below-average, above it = above-average, inside it = normal. This threshold is a judgment call, not a given; retune the window/band there directly if it feels too twitchy or too sluggish in practice, no need to ask.
- **Signal timestamp in IST** — so the trader can instantly judge freshness on open.
- **Spread caution line** — static text, not live spread data (`⚠ Confirm live spread before entry — this is a signal, not a fill price.` for EURUSD; the gold-specific news-widening variant for XAUUSD). This is mandatory copy, not decoration — see §7.

---

## 6. Email contract

**Subject:** `[SYMBOL] DIRECTION Signal - Entry Formed` (e.g. `[EURUSD] LONG Signal - Entry Formed`)

**Body (plain text) — canonical target format, PRD version:**
```
LONG ENTRY - EURUSD (5m)
Signal Time: 22 Aug 2026, 10:35 AM IST

Entry: 1.0842
Stop Loss: 1.0821   (21 pips)
Target 1: 1.0863    (21 pips | R:R 1:1)
Target 2: 1.0884    (42 pips | R:R 1:2)
Target 3: 1.0905    (63 pips | R:R 1:3)

Volatility (ATR): 18 pips — normal range

POSITION SIZE & RISK — per account
┌─────────────┬───────────────┬────────────────┬────────────────┐
│ Account      │ 0.5%          │ 0.75%          │ 1%             │
├─────────────┼───────────────┼────────────────┼────────────────┤
│ $6,000       │ 0.14 lot ($30)│ 0.21 lot ($45)  │ 0.29 lot ($60)  │
│ $10,000      │ 0.24 lot ($50)│ 0.36 lot ($75)  │ 0.48 lot ($100) │
│ $25,000      │ 0.60 lot($125)│ 0.89 lot ($188) │ 1.19 lot ($250) │
└─────────────┴───────────────┴────────────────┴────────────────┘

⚠ Confirm live spread before entry — this is a signal, not a fill price.
```

For XAUUSD: stop-loss/target distances shown in dollars (e.g. `Stop Loss: 4608.10  ($5.80)`), timeframe labeled `(3m)`, and the gold-specific spread caution (`⚠ Gold spreads can widen sharply near news — confirm live spread before entry.`).

The account/risk table's header row and every column are generated dynamically from `ACCOUNT_SIZES` / `RISK_PERCENTAGES` — never hardcode a 3×3 shape.

Delivery: Gmail SMTP via `smtplib` + `email.mime`, using a Gmail App Password. One email per instrument, sent immediately and independently the moment its own signal fires.

**Optional Telegram companion notification (`src/telegram_alert.py`):** if `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_IDS` are set, `send_signal_alert()` also sends a short "check your email" nudge via Telegram's official Bot API to 1-2 configured chats (or a real group), after the email has already sent. A WhatsApp route via the unofficial CallMeBot API was tried first and dropped — its per-recipient opt-in message reliably took well over CallMeBot's own stated "~2 minutes" during setup, with no way to distinguish "still queued" from "broken." Telegram's official API has no such opt-in delay and was adopted instead. This notification is explicitly secondary — best-effort, never blocks or fails the run if Telegram errors (logged loudly to stderr instead, same posture as yfinance in §7). Email remains the sole source of truth for the full trade plan; Telegram never carries position sizing or the full target ladder, just direction/entry/stop and a pointer to the email.

---

## 7. Trader's hard-won caveats (read before writing the email/sizing/ATR code)

- **Signal price is not a fill price.** By the time a trader reads the email and places an order, price has moved and spread has been added. The email must never imply the shown entry is guaranteed — that's what the spread-caution line is for. Don't cut it "to keep the email shorter."
- **Gold spreads widen sharply and unpredictably near news.** XAUUSD's caution line is not boilerplate — gold is exactly the instrument where ignoring this gets expensive fast.
- **A rounding/unit error in position sizing is a risk-management failure, not a cosmetic bug.** Pips vs dollars, account currency assumptions, decimal rounding — get any of these wrong and every future email silently mis-sizes risk until someone catches it by hand. Test against the worked examples in §9 before trusting the output.
- **The ATR "normal/above-average" label is a rough gut-check, not a volatility model.** It's a comparison to the value's own recent rolling average — nothing more. Don't over-engineer it (no external vol index, no percentile ranking against years of history) and don't let the email copy oversell its precision. Simple and honest beats sophisticated and misleading here.
- **GitHub Actions' built-in `schedule:` trigger is not exact-minute — and at 3-5 minute frequency it's not close.** This was originally accepted as a small trade-off, but real production runs (project history) showed gaps of 20–90+ minutes instead of the configured 3/5 minutes — GitHub documents `schedule:` as best-effort and throttles/delays it under load, especially at this frequency. That's not just cosmetic: `latest_signal()` only checks the single most recent closed candle (§3's stateless design), so a flip that happens mid-gap and isn't the trend anymore by the next delayed run is silently missed — no error, no email. The fix that was adopted: drop the `schedule:` trigger entirely (`eurusd_check.yml`/`xauusd_check.yml` now carry only `workflow_dispatch: {}`) and drive the real timing from an external precise pinger (cron-job.org, free tier) calling GitHub's workflow-dispatch API every exact 5/3 minutes — dispatch-triggered runs aren't subject to the same throttling as `schedule:` events. `session.py`'s window/day gate still runs on every single triggered run regardless of who triggered it, so an off-hours ping is still a harmless no-op. If cron-job.org is ever removed, the `schedule:` block would need to come back (accepting its known imprecision) or be replaced by an equivalent external trigger — don't leave the workflows with no scheduler at all.
- **Logic drift from the Pine Script original is the top risk in this codebase.** Any time the HalfTrend port is touched, re-validate against the live TradingView chart (§3) before trusting new output.
- **ATR must be Wilder-smoothed, not a plain rolling mean.** Pine's `ta.atr()` is RMA-based (§3). A `pandas.rolling(100).mean()` on true range will compile, run, and produce plausible-looking-but-wrong SL/target distances on every single signal — this is exactly the kind of bug that passes a superficial code review and only shows up as a mismatch against the TradingView chart.
- **The trend state machine needs real history, not just the latest candle(s).** `trend`/`maxLowPrice`/`minHighPrice`/`up`/`down` are recursive across bars (§3). Fetching a too-short window and computing signals "fresh" each run will produce wrong or missing signals without erroring — always run the full state machine forward from a well-warmed-up lookback.
- **The yfinance gold leg is a futures price, not true spot XAUUSD — and the gap is not small.** `GC=F` is the COMEX gold futures contract (conveniently also 100 troy oz per contract, matching the position-sizing lot convention already in §4), but a direct bar-by-bar comparison against OANDA's actual spot `XAU_USD` (done during this project's build, not assumed) showed a **consistent ~$58–65 (≈1.3%) premium** at matching timestamps — not a rounding-level difference. This only applies when the yfinance fallback is active (OANDA's `XAU_USD` is true spot). Practically: if a gold signal ever fires from the yfinance fallback, its entry/SL/target prices will be meaningfully off from what a trader sees on a real spot-gold broker chart — this is exactly why the data source must be disclosed in every email (§6), and why a fallback-sourced gold signal should be treated as directional/timing information to manually verify against a real spot price, not as literal entry levels to place blindly. This basis also isn't fixed — it moves with rates/carry costs, so don't hardcode a fixed offset "correction"; disclosure is the honest fix, not a patch.
- **`yfinance` is an unofficial, scraped data source — treat it as a dependency that *will* eventually misbehave, not one that might.** It talks to the same endpoints Yahoo's own site uses, and Yahoo throttles/changes them without notice. Expect occasional `429 Too Many Requests`, empty payloads, or malformed responses. Every fetch needs: (a) retry with backoff for transient failures, (b) explicit validation that returned data is non-empty and shaped as expected before feeding it to the HalfTrend engine, and (c) a loud, visible failure (§2) — never a silently-empty run — when it can't get usable data. This was a deliberate zero-cost trade-off (see §1); the code has to carry the risk the data source doesn't manage for you.
- **Every out-of-scope item in this spec is deliberately excluded** (auto-trading, position/PnL tracking, live spread feed, news calendar). If a task seems to call for one of these "just this once," it doesn't — flag it instead of building it.

---

## 8. Tech stack & project layout

- **Language:** Python 3.11+
- **Market data:** `yfinance` (unofficial Yahoo Finance), tickers `EURUSD=X` (5m native) and `GC=F` (3m built by resampling 1m bars — see §3). No API key, no account — but see §7 for the reliability trade-off this carries and the retry/validation discipline it requires. **Verified by running it, not assumed:** `XAUUSD=X` looks like the obvious gold ticker but returns a 404 on Yahoo — `GC=F` (COMEX gold futures) is the one that actually resolves. This was caught by `src/health_check.py`, not by inspection.
- **Data/math:** `pandas`, `numpy`
- **Email:** `smtplib` + `email.mime` (no paid email service)
- **Scheduling:** GitHub Actions, two independent workflows (EURUSD, XAUUSD), each self-gating on the IST session window before doing any work. Triggering is external, not GitHub's own `schedule:` event: `eurusd_check.yml`/`xauusd_check.yml` declare only `workflow_dispatch: {}`, and a free external service (cron-job.org) calls each workflow's dispatch API on the real exact schedule (every 5 min / every 3 min) — see §7 for why `schedule:` was dropped (it silently throttles at this frequency, which can drop real signals). The *actual* 06:00-21:30 IST + trading-day gating happens inside `src/session.py`, which every triggered run checks first regardless of who triggered it. Off-hours or off-day pings are expected and harmless: they hit the session check, print a one-line skip message, and exit.
- **Config:** everything user-specific (account sizes, risk %, email creds, strategy params) via env vars / `.env.example` — nothing hardcoded
- **No database** — stateless per run

```
/reference
  halftrend_source.pine  # the real Pine v6 indicator — ground truth for §3, do not delete
/src
  halftrend.py           # strategy engine + strategy_params() + risk_reward/ATR-label (symbol/timeframe agnostic)
  position_sizing.py     # lot size + dollar risk calculator
  email_alert.py          # email formatting + sending
  market_data_client.py    # yfinance wrapper: fetch + validate + retry/backoff, 1m->3m resampling for gold
  oanda_client.py           # OANDA v20 wrapper (optional primary source)
  data_provider.py           # OANDA-primary/yfinance-fallback orchestration, source tagging
  session.py                  # configurable trading-window + trading-days check (SESSION_START/END, TRADING_DAYS)
  runner.py                    # shared session -> fetch -> signal -> sizing -> email core
  eurusd_runner.py               # entrypoint: run("EURUSD", "5m")
  xauusd_runner.py                # entrypoint: run("XAUUSD", "3m")
  validate_signals.py              # mandatory validation script (§3) -- also supports --start/--end IST filtering
  health_check.py                   # quick per-provider connectivity check, independent of full warm-up
  trade_journal.py                   # outcome simulator, aggregation, monthly/yearly compounding (§12)
  journal_log.py                      # persisted daily log read/write (§12)
  journal_email.py                     # HTML journal templates (daily/weekly/monthly/yearly)
  journal_runner.py                     # daily journal job core -- also triggers weekly/monthly/yearly
  daily_journal_runner.py                # entrypoint: run_daily_journal()
/.github/workflows
  eurusd_check.yml
  xauusd_check.yml
  daily_journal.yml
/tests
  test_halftrend.py, test_signal_context.py, test_strategy_params.py  # strategy engine + R:R/ATR-label + config
  test_position_sizing.py    # worked-example lot sizes (§9)
  test_email_alert.py         # email formatting (pure, no network)
  test_session.py              # window/trading-days boundary tests
  test_runner.py                 # session/no-signal/signal/error-propagation control flow
  test_trade_journal.py            # outcome simulator + monthly/yearly compounding (§12)
  test_journal_log.py               # persisted log read/write
  test_journal_runner.py             # daily/weekly/monthly/yearly trigger logic
.env.example
requirements.txt
README.md
```

---

## 9. Testing requirements

Unit tests must assert these exact worked examples (from the build spec):

- EURUSD, entry 1.0842, SL 1.0821 (21 pips), account $6,000, risk 0.5% → lot size ≈ 0.14
- EURUSD, entry 1.0842, SL 1.0821 (21 pips), account $25,000, risk 1% → lot size ≈ 1.19
- XAUUSD, entry 4602.30, SL 4608.10 ($5.80), account $6,000, risk 0.5% → lot size ≈ 0.05
- XAUUSD, entry 4602.30, SL 4608.10 ($5.80), account $25,000, risk 1% → lot size ≈ 0.43

Plus a session-filter test confirming execution is blocked outside 06:00–21:30 IST and allowed inside it.

Beyond unit tests: per the PRD's Milestone 6, run the system in parallel against the live TradingView chart for several days — confirming signals, targets, R:R, ATR, and lot sizes are all correct — before relying on it for a real account. Unit tests catch math regressions; only live parallel-running catches strategy-port drift.

---

## 10. Config / secrets

Env vars (local `.env`, and matching GitHub repo secrets for deployment).

| Var | Purpose |
|---|---|
| `OANDA_API_KEY` | optional — OANDA v20 API personal access token. Unset = yfinance-only (§1). Currently set in this deployment. |
| `OANDA_ENVIRONMENT` | optional — `practice` or `live`, defaults to `practice` |
| `SESSION_START` / `SESSION_END` | optional — trading window, `HH:MM` IST, default `06:00`/`21:30` (`session.py`). Widening this may also need a manual edit to a workflow's cron (§8) if the new window falls outside what that cron already covers. |
| `TRADING_DAYS` | optional — comma-separated weekday numbers (Monday=0 ... Sunday=6), default `0,1,2,3,4`. Add `5,6` to include Sat/Sun — used by both the alert session gate and the journal's day/week/month/year boundaries (§12), one shared source of truth. |
| `EURUSD_AMPLITUDE` / `EURUSD_CHANNEL_DEVIATION` / `EURUSD_BASE_RISK_MULT` | optional HalfTrend overrides for EURUSD, default to Pine defaults (§3) if unset. Currently tuned to `25` / `2` / `4` in this deployment. |
| `XAUUSD_AMPLITUDE` / `XAUUSD_CHANNEL_DEVIATION` / `XAUUSD_BASE_RISK_MULT` | same, for XAUUSD. Currently tuned to `25` / `2` / `3`. |
| `GMAIL_SENDER` | sending Gmail address |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not the account password) |
| `ALERT_RECIPIENT_EMAIL` | where alerts go |
| `ACCOUNT_SIZES` | comma-separated, e.g. `6000,10000,25000` |
| `RISK_PERCENTAGES` | comma-separated, e.g. `0.5,0.75,1` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_IDS` | optional — Telegram Bot API token (from @BotFather) and a comma-separated list of chat ids for the companion nudge (§6), e.g. `111111111,-100222222222`. Either unset = feature disabled. |

The "currently tuned to" values above are a snapshot of this deployment's `.env`, not a permanent fact — if you change them later, treat this table as stale and check `.env` directly rather than trusting this note.

Ask for these only when actually needed for local testing — never ask for secrets to be pasted into chat. Point to the exact env var name to set locally and the exact GitHub repo secret name for deployment instead.

---

## 12. Trade Journal (added after the original build spec — read the caveats before touching this)

**This was explicitly out of scope originally.** §2 and §7 both say "no position/PnL tracking" and call scope creep here the way a signal tool turns into an unaudited trading bot. The user asked for it directly and deliberately later — daily/weekly/monthly/yearly emails reporting how each signal actually resolved (direct stop, TP1-then-stop, TP1+TP2-then-stop, or a full TP3 run) plus win rate and % returns. It was built, but every design choice below was a real trade-off discussed and confirmed with the user, not a default — don't casually extend this area without the same care.

**Outcome scoring vs. real PnL — these are two different things, don't conflate them:**
- `src/trade_journal.py`'s `simulate_trade_outcome()` replicates `reference/halftrend_source.pine`'s own win/loss bookkeeping **exactly** (elif-ordered TP1/TP2/TP3 checks, same-bar ambiguity, and the specific "TP1 hit then later stopped = scratch, cancel both the win and the loss" cancellation rule) — this was a deliberate choice to match the user's existing indicator, quirks included, not independently redesigned.
- That scheme is a stylized **win/loss counter**, not a PnL model. Touching TP1/TP2 doesn't reduce risk or lock in profit on this system's single non-partial position (there's no breakeven-stop move, no partial size reduction) — so the actual money outcome (`r_multiple`) is always exactly **-1R for a stop, +3R for a full TP3 run, or unresolved** if the trade hasn't closed within the fetched window. A trade can legitimately show as a "win" in the outcome-count stats while contributing exactly -1R to the real PnL (e.g. TP1 touched, then stopped) — that's not a bug, it's the honest consequence of two different, intentionally separate metrics. If this confuses the user in practice, the fix is better labeling, not changing the numbers.

**Storage: a git-committed JSON log, not a real database (for now).** `src/journal_log.py` appends each trading day's closed-trade list to `journal/daily_log.json`, committed back to the repo by the daily workflow. This was a deliberate, discussed trade-off: individual trade detection stays fully recomputed from raw candles every run (no live open-trade tracking between runs, consistent with §2's stateless design) — but the small daily *summaries* need to persist because a genuine monthly/yearly report can't be re-derived from scratch (yfinance retains only ~7 days of 1m / ~60 days of 5m data — CLAUDE.md §3 — and even OANDA would need heavy pagination for a year of 3m candles). If this ever needs to scale beyond a flat file, swap `journal_log.py` for a real DB; nothing above that layer should need to change. The user explicitly agreed to revisit this if/when it needs to scale.

**One job, four cadences.** `src/journal_runner.py`'s `run_daily_journal()` is the only scheduled entrypoint (`.github/workflows/daily_journal.yml`, Mon-Fri only at 21:30 IST — weekends are skipped at both the cron level, `cron: "30 16 * * 1-5"`, and again inside the runner via `is_trading_day()`, since no trading happens Sat/Sun). It always sends the daily email and appends to the log. On the last trading weekday of the week (Friday) it also sends weekly; on the last trading weekday of the month, monthly; on the last trading weekday of December, yearly — one schedule, not four.

**Compounding: simple sum within a period, compound across periods — and it's two levels deep.** Per the user's explicit choice: trades within a single day, and days within a single week, are simple-summed (`aggregate_trades`'s `r_total`). But a **month's return compounds that month's weekly returns**, and a **year's return compounds that year's monthly returns, where each monthly return is itself already the compound of its weeks** (`trade_journal.py`'s `monthly_report`/`yearly_report`) — not a flat sum of the whole year's trades. Getting this two-level structure right matters for correctness; a single-level "just compound everything together" shortcut gives a different (wrong) number.

**"Return by Account," not "Return by Risk Tier."** The first version showed only abstract %-per-risk-tier (defensible since % return is identical across account sizes for a given risk %, avoiding a "which account" ambiguity) — the user asked for actual dollar figures per configured account size instead, matching the account/risk matrix style already used in the alert emails. `journal_email.py`'s `_account_return_table()` shows dollars per account, with the % kept alongside in small text for context. Fully dynamic from `ACCOUNT_SIZES`/`RISK_PERCENTAGES` — no hardcoded shape, same as every other matrix in this project.

**Modules added:** `trade_journal.py` (simulator, aggregation, monthly/yearly compounding), `journal_log.py` (persisted log read/write), `journal_email.py` (HTML templates, daily/period), `journal_runner.py` (the scheduled job), `daily_journal_runner.py` (its entrypoint). Tests: `test_trade_journal.py`, `test_journal_log.py`, `test_journal_runner.py`.

---

## 13. Definition of done

- EURUSD signals email within 5 minutes of formation; XAUUSD within 3 minutes.
- Each email is separate, correctly labeled, with accurate Entry/SL/3 Targets, R:R per target, signal timestamp, and ATR snapshot.
- Every email includes a correct lot-size + dollar-risk table across all configured accounts/risk levels.
- Changing `ACCOUNT_SIZES` or `RISK_PERCENTAGES` updates future emails with zero code changes.
- No emails outside the configured trading window/days (default 06:00–21:30 IST, Mon-Fri; §10, §12).
- Zero ongoing subscription cost.
- HalfTrend signals validated against the live TradingView chart before the system is trusted with real trading decisions.
- Daily journal email sent every trading day after session close, correctly classifying each closed trade (direct stop / TP1-scratch / TP1+TP2 / TP3), and appending to the persisted log.
- Weekly/monthly/yearly journal emails fire automatically on the correct last-trading-day boundary, with monthly/yearly returns properly two-level compounded (weeks→month, months→year), not flat-summed.
- "Return by Account" in every journal email reflects real `ACCOUNT_SIZES`/`RISK_PERCENTAGES` config, not a hardcoded shape.
