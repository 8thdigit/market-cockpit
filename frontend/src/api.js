// Two modes: live API (default) or static JSON exported by `python -m cockpit export` (GitHub Pages).
const STATIC = import.meta.env.VITE_STATIC === '1'
const BASE = import.meta.env.BASE_URL || '/'
const SEV = ['info', 'watch', 'warning', 'critical']

async function get(url) {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

const safe = (s) => s.replace(/\^/g, '_').replace(/=/g, '_').replace(/&/g, '_')
let datesCache = null

async function staticDate(date) {
  if (!datesCache) datesCache = (await get(`${BASE}data/dates.json`)).dates
  if (!date) return datesCache[datesCache.length - 1]
  const ok = datesCache.filter((d) => d <= date)
  return ok.length ? ok[ok.length - 1] : datesCache[0]
}

export const api = {
  isStatic: STATIC,
  async dates() {
    return STATIC ? get(`${BASE}data/dates.json`) : get('/api/dates')
  },
  async snapshot(date, severity) {
    if (!STATIC) {
      const q = new URLSearchParams()
      if (date) q.set('date', date)
      if (severity) q.set('severity', severity)
      return get(`/api/snapshot?${q}`)
    }
    const d = await staticDate(date)
    const snap = await get(`${BASE}data/snapshot/${d}.json`)
    if (severity) {
      const min = SEV.indexOf(severity)
      snap.alerts = snap.alerts.filter((a) => SEV.indexOf(a.severity) >= min)
    }
    return snap
  },
  async signals(date, market) {
    if (!STATIC) {
      const q = new URLSearchParams()
      if (date) q.set('date', date)
      if (market) q.set('market', market)
      return get(`/api/signals?${q}`)
    }
    const d = await staticDate(date)
    const s = await get(`${BASE}data/signals/${d}.json`)
    if (market) s.signals = s.signals.filter((x) => x.market === market)
    return s
  },
  async instrument(symbol, date) {
    if (!STATIC) return get(`/api/instrument/${encodeURIComponent(symbol)}?${date ? `date=${date}&` : ''}bars=400`)
    const r = await get(`${BASE}data/instrument/${safe(symbol)}.json`)
    if (date) {
      r.bars = r.bars.filter((b) => b.date <= date)
      r.signals = r.signals.filter((b) => b.date <= date)
      r.picks = r.picks.filter((p) => p.date <= date)
    }
    return r
  },
  async page(name, date) {
    if (!STATIC) return get(`/api/page/${name}${date ? `?date=${date}` : ''}`)
    const d = await staticDate(date)
    return get(`${BASE}data/page/${name}/${d}.json`)
  },
  async trackRecord(date) {
    return STATIC ? get(`${BASE}data/track-record.json`) : get(`/api/track-record${date ? `?date=${date}` : ''}`)
  },
  async health() {
    return STATIC ? get(`${BASE}data/health.json`) : get('/api/health')
  },
  async runNow() {
    if (STATIC) throw new Error('Static mode: runs happen on the GitHub Actions schedule')
    const r = await fetch('/api/run', { method: 'POST' })
    if (!r.ok) throw new Error(`${r.status}`)
    return r.json()
  },
}
