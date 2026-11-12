# Phase 6 Task: Alerts (in-app)

> Read `PROJECT_BRIEF.md` first; every rule in it still applies. Implement only this
> file. When every acceptance criterion in §7 passes, write the Phase 6 report and **stop**.

## 0. Goal

Tell the user, inside the app, when a technical condition *changes* on an instrument
they care about: a Fibonacci level is approached or crossed, price crosses a moving
average, RSI enters overbought/oversold, MACD crosses its signal line, volume spikes,
a score moves materially, or a Phase 4 setup newly triggers. Alerts are evaluated on
closed daily bars only, deduplicated, and rate-limited by a cooldown.

**Out of scope (later):** email and Telegram delivery (need SMTP / bot credentials),
intraday alerts, push notifications, a background scheduler. Phase 5 (AI) is skipped.

## 1. Alert types (`app/engine/alerts.py`, `ALERTS_VERSION = "alerts-v1"`)

Every alert is a **transition** between the previous closed bar *t-1* and the current
closed bar *t*, so a condition that simply persists does not re-alert every day.

| Type | Fires when (bar *t-1* → bar *t*) | Default |
|---|---|---|
| `fib_cross` | close moves from one side of a Fibonacci level (levels as known at *t-1*) to the other | on |
| `fib_approach` | nearest level's distance drops to ≤ 0.5 ATR (and it wasn't already that close to the same level) | on |
| `sma_cross` | close crosses SMA *n* up or down, for the chosen periods (10/20/50/100/200) | on, 50 + 200 |
| `golden_death_cross` | SMA50 crosses SMA200 (golden = up, death = down) | on |
| `rsi` | RSI14 rises through 70 (overbought) or falls through 30 (oversold) | on |
| `macd_cross` | MACD line crosses its signal line | on |
| `relvol_spike` | relative volume rises through 2.0 (not for indices) | on |
| `score_change` | a score's change vs 5 bars earlier reaches ±10 points (it was below that at *t-1*) | on |
| `setup_new` | a Phase 4 setup is triggered at *t* but wasn't at *t-1* | on |

Every alert stores its inputs and thresholds so the UI can show exactly why it fired.
Thresholds, enabled rules and periods are user-configurable and validated.

## 2. Scope

Default: instruments the user holds (current holdings source) **plus** the watchlist.
Option: every stored instrument. Synthetic and real alerts are labelled as such.

## 3. Evaluation, closed bars, dedup and cooldown

- **Closed bars only:** a bar counts once its exchange session has ended (bar date before
  the exchange-local date, or the same date after close + 2 h). Unclosed bars are skipped and counted.
- **When:** after any price refresh (all, one symbol, or the refresh-everything button),
  and on demand with *Check now*. No background scheduler.
- **Per listing state** (`alert_state`): last evaluated bar and the config hash. First
  evaluation, or after a config/sensitivity change: only the latest closed bar (no flood
  of historical alerts). Otherwise every new closed bar since the last one, at most 10.
- **Dedup:** one alert per (listing, key, bar date). Re-evaluating never duplicates.
- **Cooldown:** the same key on the same listing is suppressed for *N* bars (default 5)
  after it last fired. Suppressed counts are reported.

## 4. Storage

- `alerts`: listing, type, key, direction, bar date, created_at (UTC), title, details JSON,
  read_at, config hash, input hash, source, is_synthetic.
- `alert_state`: listing, last evaluated bar date, config hash, evaluated_at.
- Config in `app_settings["alert_config"]`.

## 5. API

- `GET /api/alerts?status=unread|all` → alerts (newest first), unread count, last evaluation.
- `GET /api/alerts/summary` → unread count (for the nav badge).
- `POST /api/alerts/evaluate` → runs evaluation, returns the summary.
- `POST /api/alerts/{id}/read`, `POST /api/alerts/read-all`.
- `GET /api/alerts/config`, `PUT /api/alerts/config` (validated; 400/422 on bad values).
- Every response carries `provenance`.

## 6. UI

- Nav item **Alerts** with an unread-count badge.
- Alerts page: *Check now*, last evaluation summary (instruments, bars, created,
  suppressed, skipped unclosed), alerts table (filter by type, symbol, direction, read,
  data source), *Mark all read*, a per-alert "Why?" with every input and threshold.
- Settings panel on the same page: scope, each rule on/off with its thresholds, SMA
  periods, cooldown. Wording: alerts are conditions to research, not trade signals.

## 7. Acceptance criteria

1. Each alert type has unit tests for firing, not firing on a persisting condition, and missing data.
2. No look-ahead: events at bar *t* are identical on full and truncated history.
3. Unclosed bars are never evaluated (tested with an exchange clock).
4. Re-evaluation creates no duplicates; cooldown suppresses repeats; new bars are evaluated once.
5. First evaluation and config changes evaluate only the latest bar.
6. Config validation rejects bad thresholds and unknown periods.
7. Every new endpoint returns `provenance`.
8. Backend and frontend tests, lint and build pass; browser check at desktop and 390 px.
9. Docs updated: README, ROADMAP, DEVELOPMENT (decisions), ARCHITECTURE.
