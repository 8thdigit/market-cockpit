# Market Cockpit

A complete system that **watches** markets and macro data on a schedule, **analyses** them with technical, pattern and regime engines, **keeps history**, and **feeds a dashboard**. The dashboard has a date picker (replay any past day), a severity filter, **Jackpot picks**, a setup scanner, candlestick charts, a live track record and data-health monitoring.

> Educational analytics, not investment advice. Every confidence figure in the system is a *measured* hit-rate of comparable past setups, not a promise. No method reliably delivers 80% directional accuracy; this system aims for a positive **edge per trade** (expectancy) and shows you whether it has one.

```
┌────────────── collectors ──────────────┐   ┌──────────── engines ─────────────┐   ┌──── serve ────┐
│ Yahoo Finance (prices, 87 instruments) │   │ indicators: EMA/RSI/ATR/ADX/BB/   │   │ FastAPI  /api │
│   └─ Stooq fallback                    │──▶│   volume/relative strength        │──▶│ React dash    │
│ FRED (Fed target, yields, real yield,  │   │ candlestick patterns (12)         │   │ or static JSON│
│   CPI, core PCE, unemployment)         │   │ confluence score 0–100            │   │ (GitHub Pages)│
│ RSS news (Fed, RBI, EIA, Google News)  │   │ macro regime (risk-on/off)        │   └───────────────┘
│   └─ VADER + finance lexicon sentiment │   │ calibration → hit-rate & edge     │
│ config/events.json (FOMC, RBI, OPEC+)  │   │ picks + Jackpot, outcome tracking │
└────────────────────────────────────────┘   │ alerts: info/watch/warning/critical│
            SQLite history (WAL)  ◀──────────┴───────────────────────────────────┘
```

## Quick start

```bash
# backend
cd backend
pip install -r requirements.txt
python -m cockpit backfill --days 250      # first run: ~3 years of bars, 250 days analysed
python -m cockpit serve                    # API on :8000 + scheduler (15-min intraday, hourly news, EOD)

# dashboard (dev)
cd ../frontend && npm install && npm run dev   # http://localhost:5173 (proxies /api to :8000)
```

No network? `COCKPIT_PROVIDER=fixture python -m cockpit backfill` builds a synthetic demo database (labelled **DEMO DATA** in the UI).

### Docker (one container: API + dashboard + scheduler)

```bash
cp .env.example .env          # optional: add FRED_API_KEY
docker compose up -d --build  # http://localhost:8000
docker compose exec cockpit python -m cockpit backfill --days 250
```

### Serverless monitoring on GitHub (free)

`.github/workflows/monitor.yml` runs every 30 minutes during the Indian and US sessions plus an end-of-day pass. It restores the history database from the `data` branch, collects and analyses, saves the database back, exports static JSON and publishes the dashboard to GitHub Pages.

1. **Settings → Pages → Source: GitHub Actions.**
2. Optional: **Settings → Secrets → Actions → `FRED_API_KEY`** (free key from FRED).
3. **Actions → Monitor markets → Run workflow** with `backfill_days = 250` for the first run.
4. Dashboard: `https://<user>.github.io/<repo>/`

GitHub's scheduler can delay runs by several minutes; for tighter monitoring run the Docker image on any small VM.

## How the engines work

**Setup score (0–100)** for long swing trades, weights matching the checklist:

| Component | Points | Rule |
|---|---|---|
| Trend | 20 | close > 20/50-EMA, 50-EMA > 200-EMA |
| RSI pullback | 15 | RSI 40–55 and turning up inside an uptrend |
| Volume behaviour | 20 | pullback volume < 0.8× 20-day avg; up-day volume > 1.5× |
| Consolidation | 15 | Bollinger width in bottom 20% of 6 months; NR7 |
| Relative strength | 10 | 3-month return vs Nifty / S&P |
| Pullback & ADX | 10 | within 3% of 20/50-EMA; ADX > 20 |
| Regime | 10 | Risk-on 10 · Neutral 5 · Risk-off 0 |
| Candles | +10 / −15 | bullish reversal patterns add, bearish subtract |
| Gold macro tilt | ±5 | dollar below 20-EMA, yields falling (gold, silver, GLD, GOLDBEES) |

**Picks**: score ≥ 70. Entry = close, stop = 1.5×ATR (or just under the 10-day low), target = 2R, max hold 15 days.

**Calibration**: each night every instrument's full history is replayed with the same rules. Each pick shows the hit-rate and the *edge* (average R per trade, shrunk toward 0 for small samples) of its market and score bucket.

**Jackpot**: up to 3 picks a day with score ≥ 80 (88 in Risk-off) **and** a calibrated edge ≥ +0.15R. Empty days are normal and deliberate.

**Outcome tracking**: open picks are checked against every new bar. A bar touching both stop and target counts as a stop (conservative). Results feed the Track record tab.

**Regime**: S&P vs 50-DMA, Nasdaq-100 vs 200-DMA, Nifty vs 50-DMA, VIX, India VIX, dollar trend, 20-day yield change, 3-month Fed target change, news sentiment. Each scores −2…+2, rescaled to 0–100.

**Alerts**: regime flips, VIX > 25 / > 30, ≥ 2.5σ daily moves, yield moves ≥ 12 bp, RSI extremes on macro assets, 52-week highs, strong candle patterns, score crossing 70, new picks, stops/targets hit, approaching high-impact events, stale data.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/snapshot?date=&severity=` | everything for the cockpit as of a date |
| `GET /api/signals?date=&market=IN\|US\|CMD&min_score=` | scanner rows |
| `GET /api/instrument/{symbol}?date=&bars=` | bars, indicators, patterns, picks |
| `GET /api/track-record?date=` | closed picks, hit-rates, equity curve, calibration |
| `GET /api/health` | source status, run log, per-instrument freshness |
| `GET /api/dates` | analysed dates (for the date picker) |
| `POST /api/run` | run a collect + analyse cycle now |

## Configure

- `config/universe.json`: instruments (35 NSE stocks, 35 US stocks/ETFs, indices, gold, silver, Brent, WTI, DXY, USD/INR, 10-yr).
- `config/events.json`: scheduled events (FOMC, RBI, OPEC+, CPI, payrolls). Keep it current; verify dates on official sites.
- `.env`: provider, FRED key, thresholds (`COCKPIT_MIN_PICK_SCORE`, `COCKPIT_JACKPOT_SCORE`, `COCKPIT_JACKPOT_MIN_EDGE`, `COCKPIT_REWARD_RISK`, `COCKPIT_MAX_HOLD_DAYS`).

## Reliability

- Every source and symbol fails independently; retries with exponential backoff; Stooq fallback for prices.
- Bars are cleaned (duplicates, zero/NaN closes, inconsistent highs/lows).
- Idempotent upserts and deterministic alert ids, so reruns never duplicate.
- A job lock prevents overlapping scheduler runs; every run is logged in `runs`, and source status in `source_health`.
- Stale-data alerts fire when an instrument stops updating.
- `pytest` covers indicators, patterns, trade simulation, calibration, the full pipeline and the API (offline fixture data; runs in CI).

## Known limits

- Yahoo Finance is unofficial and can rate-limit or change; for production use, add a licensed feed (e.g. a broker API) as another provider in `backend/cockpit/providers/`.
- Daily bars only; "intraday" runs refresh today's forming bar.
- When backfilling, calibration uses the full history, so historical picks carry slight look-ahead in their displayed hit-rate. Live picks don't.
- Long-only setups; bearish signals appear as alerts and score penalties.

## Deploy on Vercel

`vercel.json` + `scripts/vercel-build.sh`: every Vercel build downloads live prices, macro data and headlines, analyses them, exports static JSON and publishes the dashboard. A build fails on purpose if the live feed mostly fails, so the last good deployment stays up.

- **Fresh data every 30 min:** create a Deploy Hook (Vercel → Project → Settings → Git → Deploy Hooks, branch `main`) and save its URL as the GitHub secret `VERCEL_DEPLOY_HOOK`. The *Monitor markets* workflow then triggers a rebuild after each run.
- **Keep full history across builds (optional):** add a Vercel env var `GITHUB_DATA_TOKEN`, a fine-grained GitHub token with read-only *Contents* access to this repo. The build then restores the database the workflow saves on the `data` branch.
