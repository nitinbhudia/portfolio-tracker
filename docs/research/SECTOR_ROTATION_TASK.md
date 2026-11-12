# Sector Rotation & Relative Rotation Graph (RRG)

> A module inside Fibonacci AI, not a separate app. Read `PROJECT_BRIEF.md` first; every rule in it
> still applies (no fabricated data, provenance everywhere, SYNTHETIC labels, no buy/sell signals).

## 1. Assessment (Stage 1)

**What already exists and is reused**

| Need | Existing piece | Reuse |
|---|---|---|
| Daily prices for sector ETFs and SPY | Tiingo client + budgeted refresh (`market_data/service.py`), NYSE calendar, unfinished-session filter | Sector ETFs are added as tracked Tiingo targets (origin `sector`); SPY/QQQ/DIA/IWM are already tracked |
| Price storage, provenance, gaps | `price_bars`, `analysis.load_bars`, `analysis.provenance`, `find_gaps` | Unchanged |
| RSI, MACD, SMA 10/20/50/200, ATR | `engine/indicators.compute_all` | Used for the ranking table and the score; nothing re-implemented |
| Swings, Fibonacci, scores, setups | `analysis.compute_analysis` | The sector page shows the ETF's existing analysis (chart, Fibonacci, scores); constituents link to `/analysis/{id}` |
| Charts | `PriceChart` (Lightweight Charts) | Reused for the ETF chart. The RRG is a scatter plot, which Lightweight Charts can't draw, so it's a small hand-written SVG component (no new dependency) |
| Tables, filters, presets, CSV | `DataTable` | Ranking, transitions, constituents |
| Settings, sensitivity, theme, holdings source, watchlist | `app_settings`, Shell, WatchStar | Score weights are stored in `app_settings`; holdings and watchlist flags shown on constituents |
| Synthetic demo | `data/synthetic.py`, seed | 11 synthetic sector ETFs + synthetic SPY, labelled SYNTHETIC, so the module works before a Tiingo key is added |

**What is new**

- `engine/rrg.py`: RS-Ratio, RS-Momentum, quadrants, trails (pure, tested).
- `engine/rotation.py`: ranking metrics, quadrant transitions, rotation events, Rotation Signal Score.
- `market_data/holdings.py`: the official State Street (SSGA) daily holdings file for each SPDR sector
  ETF (`holdings-daily-us-en-{ticker}.xlsx`), parsed with the standard library (no new dependency).
  Checked on 2026-11-06: all 11 files available, dated 4 Nov 2026, columns Name, Ticker,
  Identifier, SEDOL, Weight, Sector, Shares Held, Local Currency.
- `services/sectors.py`, API under `/api/sectors/*`, a **Sector Rotation** page and a sector drill-down page.
- One table, `sector_holdings`, plus one migration.

**Data honesty**

- Real mode needs `TIINGO_API_KEY`; sector ETFs then download with the other US symbols (11 extra
  requests per refresh, within the free plan). Until then the module runs on the synthetic demo,
  clearly labelled. Real and synthetic data are never mixed in one view.
- Constituent prices download **on demand** per sector (10 symbols), to respect Tiingo's free limits.
- **ETF fund flows are not included:** there's no reliable free source. Price and volume are proxies
  for capital rotation, not measurements of institutional flows, and the UI says so.

## 2. RRG methodology: an RRG-inspired approximation

The JdK RS-Ratio and RS-Momentum formulas are proprietary (RRG Research). This module implements a
**documented approximation** and labels it as such everywhere:

1. RS = 100 × sector close ÷ benchmark close, on dates both have (aligned; missing days are not filled).
2. Smooth RS with an EMA (span *s*).
3. **RS-Ratio** = 100 + z-score of smoothed RS over a rolling window *w* (mean and standard deviation of
   the last *w* values). Above 100 means relative strength above its recent norm.
4. **RS-Momentum** = 100 + z-score of the *m*-day change of RS-Ratio over the same window.
5. The benchmark sits at (100, 100) by construction.

Quadrants: Leading (ratio > 100, momentum > 100), Weakening (> 100, < 100), Lagging (< 100, < 100),
Improving (< 100, > 100).

Timeframes set the windows (*w*, *m*, *s*): 10 days (10, 5, 2), 1 month (21, 10, 3), 3 months
(63, 21, 5), 6 months (126, 42, 8), 12 months (252, 63, 10). Trails show the last 5, 10 or 20 sessions.
At least 200 + *w* + *m* aligned bars are loaded, so the 200-day average always exists.

## 3. Ranking, detection and score

- **Ranking columns:** quadrant, RS-Ratio, RS-Momentum, 10/20/50-day price change, 20-day performance
  relative to the benchmark, RSI 14, SMA 10/20/50/200 (and price versus each), and volume trend
  (20-day ÷ 50-day average volume).
- **Transitions** in the last 20 sessions, categorised:
  - Early opportunity: Lagging → Improving, or momentum crossing above 100 while ratio < 100.
  - Established: Improving → Leading.
  - Exit warning: Leading → Weakening, or momentum crossing below 100 while ratio > 100.
  - Deterioration: Weakening → Lagging, or close crossing below SMA 50.
- **Rotation Signal Score (0–100)**, a weighted average of transparent components:
  - relative strength: 50 + 10 × (RS-Ratio − 100)
  - relative momentum: 50 + 10 × (RS-Momentum − 100)
  - acceleration: 50 + 10 × the 5-day change in RS-Momentum
  - MA alignment: 25 points each for close > SMA 20, SMA 20 > SMA 50, SMA 50 > SMA 200, close > SMA 200
  - volume: 50 + 200 × (volume trend − 1)
  - recent transition: Improving → Leading 90, Lagging → Improving 80, none 50, Leading → Weakening 20,
    Weakening → Lagging 10

  Every component is clipped to 0–100. Default weights are 25 / 25 / 15 / 15 / 10 / 10; you can change
  them, and they're renormalised to sum to 1. The breakdown is shown for every sector. The score is a
  research aid, never a buy or sell signal.
- **Three measurements kept apart:** absolute trend (price versus SMA 50/200, 20-day change), relative
  performance (versus the benchmark) and relative momentum (RS-Momentum).

## 4. Drill-down

The ETF's existing analysis (chart, SMAs, RSI, MACD, Fibonacci, scores) via the shared components;
relative performance versus the benchmark; the sector's RRG trail; top 10 holdings by weight (SSGA,
dated); strongest and weakest constituents by 20-day return; and constituents beating the sector (their
own RS-Ratio against the sector ETF above 100). Each constituent links to its existing analysis page.
Your holdings and watchlist are flagged.

## 5. Acceptance criteria

1. RRG engine tested: alignment on common dates, z-score maths by hand, benchmark at 100, quadrant
   classification, trail lengths, no look-ahead (truncation), insufficient history reported.
2. Ranking metrics, transitions, events and score tested on constructed series; score weights validated and stored.
3. Holdings parser tested on a real SSGA file (fixture); missing or partial files are handled.
4. API: dashboard, sector detail, holdings refresh, constituent price download, and score config, each
   with provenance; synthetic and real data never mixed.
5. Existing features unaffected: the full test suite passes, and the scanner and screener include the new
   synthetic ETFs with correct labels.
6. UI: Sector Rotation in the menu; RRG with tooltips, toggles, trails, benchmark and timeframe; ranking,
   transitions and alerts; drill-down to constituents and on to `/analysis/{id}`. Checked at desktop and 390 px.
7. Docs updated (README, ROADMAP, DEVELOPMENT decisions, ARCHITECTURE).

## 6. Follow-up: signals on the Alerts page

Rotation signals are a `sector_rotation` alert type (see DEVELOPMENT.md). They use the same engine and
data choice as the module, closed sessions only, with the shared dedup and cooldown.

## 7. Follow-up: Europe

Region `eu`: 19 iShares STOXX Europe 600 supersector ETFs on Xetra against EXSA, EODHD prices and iShares
holdings (facts verified on ishares.com on 2026-11-06). See DEVELOPMENT.md for details.
