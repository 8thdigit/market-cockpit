#!/usr/bin/env bash
# Vercel build: collect live data -> analyse -> export static JSON -> build dashboard.
# Each build is a fresh snapshot of the markets. History:
#   - with GITHUB_DATA_TOKEN set (read access to this repo), the database saved by the
#     GitHub "Monitor markets" workflow on the `data` branch is restored first, so news
#     history and live pick outcomes carry over;
#   - without it, ~3 years of prices are re-downloaded and the last 250 trading days are
#     re-analysed, which rebuilds picks and the track record deterministically.
# If live data can't be fetched the build fails, so the previous good deployment stays live.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export COCKPIT_PROVIDER="${COCKPIT_PROVIDER:-yahoo}"
export COCKPIT_DB="$ROOT/data/cockpit.db"
mkdir -p "$ROOT/data"

echo "== python deps"
PY=python3
$PY -m pip --version >/dev/null 2>&1 || $PY -m ensurepip --upgrade
$PY -m pip install -q --disable-pip-version-check --target "$ROOT/.pydeps" -r "$ROOT/backend/requirements.txt"
export PYTHONPATH="$ROOT/.pydeps:$ROOT/backend"

if [ -n "${GITHUB_DATA_TOKEN:-}" ] && [ -n "${VERCEL_GIT_REPO_OWNER:-}" ]; then
  echo "== restoring history from the data branch"
  curl -fsSL -H "Authorization: Bearer $GITHUB_DATA_TOKEN" -H "Accept: application/vnd.github.raw" \
    "https://api.github.com/repos/$VERCEL_GIT_REPO_OWNER/$VERCEL_GIT_REPO_SLUG/contents/cockpit.db?ref=data" \
    -o "$COCKPIT_DB" || { echo "no saved history yet"; rm -f "$COCKPIT_DB"; }
fi

cd "$ROOT/backend"
if [ -s "$COCKPIT_DB" ]; then
  echo "== incremental run"
  $PY -m cockpit run --days 5
else
  echo "== full backfill"
  $PY -m cockpit backfill --days "${COCKPIT_BACKFILL_DAYS:-250}"
fi

# Guard: refuse to publish if the live feed mostly failed.
$PY - <<'EOF'
import os, sqlite3, sys, datetime as dt
c = sqlite3.connect(os.environ["COCKPIT_DB"])
total = c.execute("select count(distinct symbol) from prices").fetchone()[0]
recent = c.execute("select count(distinct symbol) from prices where date >= ?",
                   ((dt.date.today() - dt.timedelta(days=7)).isoformat(),)).fetchone()[0]
print(f"instruments with data: {total}, updated in last 7 days: {recent}")
if recent < 40:
    sys.exit("Too few instruments updated - not publishing stale data")
EOF

echo "== export"
$PY -m cockpit export --out "$ROOT/frontend/public/data" --days 90

echo "== dashboard"
cd "$ROOT/frontend"
VITE_STATIC=1 VITE_BASE=/ npm run build
