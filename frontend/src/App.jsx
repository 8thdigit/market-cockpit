import React, { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import { SEVERITIES, Tabs } from './ui.jsx'
import { Scanner, Instrument, Health } from './views.jsx'
import { InfluencersPage, HistoryPage, StocksPage, CommoditiesPage } from './pages.jsx'

const TABS = [
  ['influencers', '1 · Influencers'],
  ['history', '2 · History'],
  ['stocks', '3 · Stocks cockpit'],
  ['commodities', '4 · Gold & Oil cockpit'],
  ['instrument', 'Chart'],
  ['scanner', 'Scanner'],
  ['health', 'Data health'],
]

function useHash() {
  const read = () => {
    const p = new URLSearchParams(window.location.hash.slice(1))
    return { tab: p.get('tab') || 'influencers', sym: p.get('sym') || 'GC=F', date: p.get('date') || '', sev: p.get('sev') || '' }
  }
  const [st, setSt] = useState(read)
  useEffect(() => {
    const f = () => setSt(read())
    window.addEventListener('hashchange', f)
    return () => window.removeEventListener('hashchange', f)
  }, [])
  const set = useCallback((patch) => {
    const next = { ...read(), ...patch }
    const p = new URLSearchParams()
    Object.entries(next).forEach(([k, v]) => v && p.set(k, v))
    window.location.hash = p.toString()
  }, [])
  return [st, set]
}

export default function App() {
  const [st, set] = useHash()
  const [dates, setDates] = useState([])
  const [snap, setSnap] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    api.dates().then((r) => setDates(r.dates || [])).catch((e) => setErr(String(e)))
  }, [tick])

  useEffect(() => {
    setLoading(true)
    api.snapshot(st.date || null, st.sev || null)
      .then((s) => { setSnap(s); setErr('') })
      .catch((e) => setErr(`Could not load data: ${e.message}. Is the backend running?`))
      .finally(() => setLoading(false))
  }, [st.date, st.sev, tick])

  // Live mode: refresh every 5 minutes when viewing the latest date.
  useEffect(() => {
    if (api.isStatic || st.date) return
    const t = setInterval(() => setTick((x) => x + 1), 5 * 60 * 1000)
    return () => clearInterval(t)
  }, [st.date])

  const asOf = snap?.date || ''
  const minD = dates[0], maxD = dates[dates.length - 1]
  const step = (dir) => {
    if (!dates.length) return
    const i = dates.indexOf(asOf)
    const j = Math.min(dates.length - 1, Math.max(0, (i < 0 ? dates.length - 1 : i) + dir))
    set({ date: j === dates.length - 1 ? '' : dates[j] })
  }
  const openSym = (sym) => set({ tab: 'instrument', sym })

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="dot" /> Market Cockpit
          {snap?.provider === 'fixture' && <span className="demo" title="Synthetic data — set COCKPIT_PROVIDER=yahoo for live markets">DEMO DATA</span>}
          {api.isStatic && <span className="badge">static</span>}
        </div>
        <div className="controls">
          <label className="ctl">
            <span>As of</span>
            <button className="ghost" onClick={() => step(-1)} aria-label="Previous trading day">‹</button>
            <input type="date" value={asOf} min={minD} max={maxD}
              onChange={(e) => set({ date: e.target.value && e.target.value < maxD ? e.target.value : '' })} />
            <button className="ghost" onClick={() => step(1)} aria-label="Next trading day">›</button>
            {st.date && <button className="link" onClick={() => set({ date: '' })}>Latest</button>}
          </label>
          <label className="ctl">
            <span>Severity</span>
            <select value={st.sev} onChange={(e) => set({ sev: e.target.value })}>
              <option value="">All</option>
              {SEVERITIES.slice(1).map((s) => <option key={s} value={s}>{s}+</option>)}
            </select>
          </label>
          {!api.isStatic && (
            <button className="primary" disabled={loading} onClick={() => { setLoading(true); api.runNow().finally(() => setTick((x) => x + 1)) }}>
              {loading ? 'Working…' : 'Run now'}
            </button>
          )}
        </div>
      </header>
      <Tabs tabs={TABS} value={st.tab} onChange={(tab) => set({ tab })} />
      {err && <div className="error">{err}</div>}
      <main>
        {snap?.empty && <div className="empty big">No analysed data yet. Run <code>python -m cockpit backfill</code> to build history.</div>}
        {snap && !snap.empty && (
          <>
            {st.tab === 'influencers' && <InfluencersPage key={`i${tick}`} date={asOf} openSym={openSym} />}
            {st.tab === 'history' && <HistoryPage key={`h${tick}`} date={asOf} />}
            {st.tab === 'stocks' && <StocksPage key={`s${tick}`} date={asOf} openSym={openSym} />}
            {st.tab === 'commodities' && <CommoditiesPage key={`c${tick}`} date={asOf} openSym={openSym} />}
            {st.tab === 'scanner' && <Scanner date={asOf} openSym={openSym} />}
            {st.tab === 'instrument' && <Instrument sym={st.sym} date={asOf} onSym={(sym) => set({ sym })} />}
            {st.tab === 'health' && <Health />}
          </>
        )}
      </main>
      <footer className="foot">
        Educational analytics, not investment advice. Hit rate and edge = measured results of comparable past setups (stop 1.5×ATR, target 2R,
        15-day max hold); past performance does not guarantee future results.
      </footer>
    </div>
  )
}
