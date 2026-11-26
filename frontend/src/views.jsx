import React, { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { CandleChart, LineChart } from './charts.jsx'
import { Card, ConfBar, Empty, Gauge, PATTERN_LABEL, ScoreChip, Sev, Spark, fmt } from './ui.jsx'

const MKT = { IN: 'India', US: 'US', CMD: 'Commodities' }
const COMP_LABEL = {
  trend: 'Trend', rsi: 'RSI pullback', volume: 'Volume', consolidation: 'Consolidation', relative_strength: 'Rel. strength',
  pullback: 'Pullback/ADX', regime: 'Regime', patterns: 'Candles', macro_tilt: 'Macro tilt',
}
const REG_LABEL = {
  us_trend: 'S&P vs 50-DMA', tech_trend: 'Nasdaq-100 vs 200-DMA', india_trend: 'Nifty vs 50-DMA', vix: 'VIX level',
  india_vix: 'India VIX', dollar: 'Dollar trend', yields: '10-yr 20-day change', fed: 'Fed policy (3m)', news: 'News sentiment',
}

function useLoad(fn, deps) {
  const [state, set] = useState({ data: null, err: '' })
  useEffect(() => {
    let live = true
    set((s) => ({ ...s, err: '' }))
    fn().then((data) => live && set({ data, err: '' })).catch((e) => live && set({ data: null, err: e.message }))
    return () => { live = false }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return state
}

// ---------------------------------------------------------------- Overview
export function Overview({ snap, openSym, goPicks }) {
  const reg = snap.regime
  return (
    <div className="grid">
      <Card title="Macro regime" className="span-4" id="regime">
        {reg ? (
          <div className="regime">
            <Gauge score={reg.score} label={reg.label} />
            <div className={`reg-label ${reg.label === 'Risk-on' ? 'good' : reg.label === 'Risk-off' ? 'bad' : 'mid'}`}>{reg.label}</div>
            <ul className="reg-comp">
              {Object.entries(reg.components).map(([k, v]) => (
                <li key={k}><span>{REG_LABEL[k] || k}</span><b className={v > 0 ? 'good' : v < 0 ? 'bad' : ''}>{v > 0 ? '+' : ''}{v}</b></li>
              ))}
            </ul>
          </div>
        ) : <Empty>No regime yet</Empty>}
      </Card>

      <Card title="Jackpot picks" className="span-8 jackpot-card" id="jackpot"
        right={<button className="link" onClick={goPicks}>All picks →</button>}>
        {snap.jackpot.length ? (
          <div className="jp-row">{snap.jackpot.map((p) => <JackpotCard key={p.id} p={p} openSym={openSym} />)}</div>
        ) : (
          <Empty>
            No setup clears the jackpot bar today (score ≥ 80{reg?.label === 'Risk-off' ? ' — 88 in Risk-off' : ''}, and a historical edge of at least +0.15R per trade for that setup bucket).
            Sitting out is a position. {snap.picks.length ? `${snap.picks.length} regular picks are listed under Jackpot & picks.` : ''}
          </Empty>
        )}
      </Card>

      <Card title="Cockpit gauges" className="span-12" id="tiles">
        <div className="tiles">
          {snap.tiles.map((t) => (
            <button key={t.symbol} className="tile" onClick={() => openSym(t.symbol)}>
              <div className="t-name">{t.name}</div>
              <div className="t-val">{t.is_rate ? `${fmt.num(t.close, 2)}%` : fmt.price(t.close)}</div>
              <div className="t-chg">
                <span className={t.chg_1d >= 0 ? 'good' : 'bad'}>{fmt.pct(t.chg_1d)}</span>
                <span className="muted">5d {fmt.pct(t.chg_5d)}</span>
              </div>
              <Spark data={t.spark} up={t.chg_21d >= 0} />
            </button>
          ))}
        </div>
        {snap.macro.length > 0 && (
          <div className="macro-row">
            {snap.macro.map((m) => (
              <div key={m.series} className="macro">
                <span>{m.label}</span>
                <b>{m.yoy != null ? `${fmt.pct(m.yoy)} y/y` : `${fmt.num(m.value, 2)}${m.unit === '%' ? '%' : ''}`}</b>
                <small>{m.date}</small>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title={`Alerts · ${snap.date}`} className="span-7" id="alerts"
        right={<div className="counts">{Object.entries(snap.alert_counts).reverse().map(([k, v]) => <span key={k} className={`cnt sev-${k}`}>{v}</span>)}</div>}>
        {snap.alerts.length ? (
          <ul className="alerts">
            {snap.alerts.slice(0, 40).map((a) => (
              <li key={a.id} className={`al al-${a.severity}`}>
                <Sev s={a.severity} />
                <div>
                  <div className="al-t">{a.title}</div>
                  {a.detail && <div className="al-d">{a.detail}</div>}
                </div>
                <span className="al-c">{a.category}</span>
              </li>
            ))}
          </ul>
        ) : <Empty>No alerts at this severity.</Empty>}
      </Card>

      <div className="span-5 stack">
        <Card title="Upcoming events" id="events">
          {snap.events.length ? (
            <ul className="events">
              {snap.events.map((e) => (
                <li key={e.ts + e.title}>
                  <span className={`imp imp-${e.impact}`}>{e.impact.replace('_', ' ')}</span>
                  <div><div>{e.title}</div><small>{fmt.time(e.ts)}</small></div>
                </li>
              ))}
            </ul>
          ) : <Empty>No events in the next 3 weeks. Add them in config/events.json.</Empty>}
        </Card>
        <Card title="News sentiment (3 days)" id="news">
          {Object.keys(snap.sentiment).length ? (
            <div className="sent">
              {Object.entries(snap.sentiment).filter(([k]) => k !== 'all').map(([k, v]) => (
                <div key={k} className="sent-row">
                  <span>{k.replace('_', ' ')}</span>
                  <i><b className={v >= 0 ? 'pos' : 'neg'} style={{ width: `${Math.min(50, Math.abs(v) * 100)}%`, [v >= 0 ? 'left' : 'right']: '50%' }} /></i>
                  <em>{v.toFixed(2)}</em>
                </div>
              ))}
            </div>
          ) : <Empty>No headlines collected (news runs hourly in live mode).</Empty>}
          <ul className="news">
            {snap.news.slice(0, 8).map((n) => (
              <li key={n.ts + n.title}>
                <span className={n.sentiment > 0.15 ? 'good' : n.sentiment < -0.15 ? 'bad' : 'muted'}>●</span>
                {n.url ? <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a> : n.title}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="Regime history" className="span-12" id="regime-history">
        <LineChart series={[{ name: 'Risk score', data: snap.regime_history.map((r) => ({ time: r.date, value: r.score })),
          bands: [{ v: 60, c: '--up', t: 'risk-on' }, { v: 40, c: '--down', t: 'risk-off' }] }]} height={180} />
      </Card>
    </div>
  )
}

function JackpotCard({ p, openSym }) {
  return (
    <button className="jp" onClick={() => openSym(p.symbol)}>
      <div className="jp-h"><span className="jp-star">★</span><b>{p.name}</b><span className="muted">{p.symbol} · {MKT[p.market]}</span></div>
      <div className="jp-nums">
        <div><small>Entry</small>{fmt.price(p.entry)}</div>
        <div><small>Stop</small><span className="bad">{fmt.price(p.stop)}</span></div>
        <div><small>Target</small><span className="good">{fmt.price(p.target)}</span></div>
      </div>
      <div className="jp-meta"><ScoreChip v={p.score} /><ConfBar v={p.confidence} /><span className={p.expected_r > 0 ? 'good' : 'bad'} title="Calibrated expectancy per trade">edge {fmt.r(p.expected_r)}</span></div>
      <ul className="why">{p.rationale.slice(0, 4).map((w) => <li key={w}>{w}</li>)}</ul>
    </button>
  )
}

// ---------------------------------------------------------------- Picks
export function Picks({ snap, openSym }) {
  const [mkt, setMkt] = useState('')
  const [open, setOpen] = useState(null)
  const rows = snap.picks.filter((p) => !mkt || p.market === mkt)
  return (
    <div className="grid">
      <Card title={`New picks · ${snap.date}`} className="span-12" id="picks"
        right={<MarketFilter v={mkt} set={setMkt} />}>
        {rows.length ? (
          <div className="tw"><table>
            <thead><tr><th>#</th><th>Instrument</th><th>Mkt</th><th>Score</th><th>Hit rate</th><th className="n">Edge</th><th className="n">Entry</th>
              <th className="n">Stop</th><th className="n">Target</th><th className="n">Risk</th><th className="n">Reward</th><th /></tr></thead>
            <tbody>
              {rows.map((p) => (
                <React.Fragment key={p.id}>
                  <tr className={p.jackpot ? 'jp-row-hl' : ''}>
                    <td>{p.rank}</td>
                    <td><button className="link" onClick={() => openSym(p.symbol)}>{p.jackpot && '★ '}{p.name}</button><div className="muted sm">{p.symbol}</div></td>
                    <td>{MKT[p.market]}</td><td><ScoreChip v={p.score} /></td><td><ConfBar v={p.confidence} /></td>
                    <td className={`n ${p.expected_r > 0 ? 'good' : 'bad'}`}>{fmt.r(p.expected_r)}</td>
                    <td className="n">{fmt.price(p.entry)}</td><td className="n bad">{fmt.price(p.stop)}</td>
                    <td className="n good">{fmt.price(p.target)}</td><td className="n">{fmt.pct(-p.risk_pct)}</td>
                    <td className="n">{fmt.pct(p.reward_pct)}</td>
                    <td><button className="link" onClick={() => setOpen(open === p.id ? null : p.id)}>{open === p.id ? 'Hide' : 'Why?'}</button></td>
                  </tr>
                  {open === p.id && <tr className="why-row"><td colSpan={12}><ul className="why">{p.rationale.map((w) => <li key={w}>{w}</li>)}</ul></td></tr>}
                </React.Fragment>
              ))}
            </tbody>
          </table></div>
        ) : <Empty>No new setups scored 70+ on this date{mkt ? ` in ${MKT[mkt]}` : ''}.</Empty>}
      </Card>
      <Card title="Open positions from earlier picks" className="span-12" id="open">
        {snap.open_picks.length ? (
          <div className="tw"><table>
            <thead><tr><th>Picked</th><th>Instrument</th><th>Score</th><th className="n">Entry</th><th className="n">Stop</th><th className="n">Target</th><th>Status as of {snap.date}</th></tr></thead>
            <tbody>{snap.open_picks.map((p) => (
              <tr key={p.id}><td>{p.date}</td><td><button className="link" onClick={() => openSym(p.symbol)}>{p.jackpot && '★ '}{p.name}</button></td>
                <td><ScoreChip v={p.score} /></td><td className="n">{fmt.price(p.entry)}</td><td className="n bad">{fmt.price(p.stop)}</td>
                <td className="n good">{fmt.price(p.target)}</td><td>{p.exit_date && p.exit_date > snap.date ? 'open' : p.status}</td></tr>
            ))}</tbody>
          </table></div>
        ) : <Empty>No open positions.</Empty>}
      </Card>
    </div>
  )
}

function MarketFilter({ v, set }) {
  return (
    <div className="seg">
      {[['', 'All'], ['IN', 'India'], ['US', 'US'], ['CMD', 'Commodities']].map(([k, l]) => (
        <button key={k} className={v === k ? 'on' : ''} onClick={() => set(k)}>{l}</button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- Scanner
export function Scanner({ date, openSym }) {
  const [mkt, setMkt] = useState('')
  const [sort, setSort] = useState(['score', -1])
  const [q, setQ] = useState('')
  const { data, err } = useLoad(() => api.signals(date, mkt || null), [date, mkt])
  const rows = useMemo(() => {
    const r = (data?.signals || []).filter((s) => !q || (s.name + s.symbol + (s.sector || '')).toLowerCase().includes(q.toLowerCase()))
    const [k, dir] = sort
    return [...r].sort((a, b) => ((a[k] ?? -1e9) > (b[k] ?? -1e9) ? dir : -dir))
  }, [data, sort, q])
  const th = (k, l, n) => (
    <th className={n ? 'n sortable' : 'sortable'} onClick={() => setSort([k, sort[0] === k ? -sort[1] : -1])}>
      {l}{sort[0] === k ? (sort[1] < 0 ? ' ↓' : ' ↑') : ''}
    </th>
  )
  return (
    <Card title={`Setup scanner · ${data?.date || date}`} id="scanner"
      right={<div className="row"><input className="search" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} /><MarketFilter v={mkt} set={setMkt} /></div>}>
      {err && <div className="error">{err}</div>}
      <div className="tw"><table>
        <thead><tr>{th('name', 'Instrument')}{th('sector', 'Sector')}{th('score', 'Score', 1)}{th('trend', 'Trend')}{th('rsi', 'RSI', 1)}
          {th('vol_ratio', 'Vol ×avg', 1)}{th('bb_pctile', 'BB width %ile', 1)}{th('rs_63', 'RS 3m', 1)}{th('adx', 'ADX', 1)}{th('atr_pct', 'ATR %', 1)}<th>Patterns</th><th>Score mix</th></tr></thead>
        <tbody>{rows.map((s) => (
          <tr key={s.symbol}>
            <td><button className="link" onClick={() => openSym(s.symbol)}>{s.name}</button><div className="muted sm">{s.symbol}</div></td>
            <td>{s.sector}</td><td className="n"><ScoreChip v={s.score} /></td>
            <td className={s.trend === 'uptrend' ? 'good' : s.trend === 'downtrend' ? 'bad' : ''}>{s.trend}</td>
            <td className="n">{fmt.num(s.rsi, 0)}</td><td className="n">{fmt.num(s.vol_ratio, 1)}</td>
            <td className="n">{fmt.num(s.bb_pctile * 100, 0)}</td><td className={`n ${s.rs_63 >= 0 ? 'good' : 'bad'}`}>{fmt.pct(s.rs_63)}</td>
            <td className="n">{fmt.num(s.adx, 0)}</td><td className="n">{fmt.num(s.atr_pct * 100, 1)}</td>
            <td className="pats">{s.patterns.map((p) => <span key={p} className="pat">{PATTERN_LABEL(p)}</span>)}</td>
            <td><Mix c={s.components} /></td>
          </tr>
        ))}</tbody>
      </table></div>
    </Card>
  )
}

function Mix({ c }) {
  const parts = Object.entries(c).filter(([, v]) => v > 0)
  return (
    <span className="mix" title={Object.entries(c).map(([k, v]) => `${COMP_LABEL[k] || k}: ${v}`).join('\n')}>
      {parts.map(([k, v], i) => <i key={k} className={`m${i % 7}`} style={{ width: `${v}%` }} />)}
    </span>
  )
}

// ---------------------------------------------------------------- Instrument
export function Instrument({ sym, date, onSym }) {
  const { data, err } = useLoad(() => api.instrument(sym, date), [sym, date])
  const [list, setList] = useState([])
  useEffect(() => { api.health().then((h) => setList(h.freshness || [])).catch(() => {}) }, [])
  const last = data?.signals?.[data.signals.length - 1]
  return (
    <div className="grid">
      <Card className="span-12" id="chart" title={data ? `${data.instrument.name} (${sym})` : sym}
        right={<select value={sym} onChange={(e) => onSym(e.target.value)}>
          {(list.length ? list : [{ symbol: sym, name: sym }]).map((i) => <option key={i.symbol} value={i.symbol}>{i.name || i.symbol}</option>)}
        </select>}>
        {err && <div className="error">{err}</div>}
        {data && <CandleChart bars={data.bars} signals={data.signals} picks={data.picks} />}
        <div className="legend"><span className="c1">EMA 20</span><span className="c2">EMA 50</span><span className="c3">EMA 200</span><span className="gold">● pick</span><span className="good">▲ bullish candle</span><span className="bad">▼ bearish candle</span></div>
      </Card>
      {last && (
        <Card title="Latest reading" className="span-4" id="reading">
          <dl className="kv">
            <dt>Setup score</dt><dd><ScoreChip v={last.score} /></dd>
            <dt>RSI(14)</dt><dd>{fmt.num(last.rsi, 0)}</dd>
            <dt>Volume vs 20-day</dt><dd>{fmt.num(last.vol_ratio, 2)}×</dd>
            <dt>Patterns today</dt><dd>{last.patterns.length ? last.patterns.map(PATTERN_LABEL).join(', ') : 'none'}</dd>
          </dl>
        </Card>
      )}
      {data?.signals?.length > 0 && (
        <Card title="Setup score history" className="span-8" id="score-history">
          <LineChart series={[{ name: 'Score', data: data.signals.map((s) => ({ time: s.date, value: s.score })), bands: [{ v: 70, c: '--gold', t: 'pick' }] }]} height={200} />
        </Card>
      )}
      {data?.picks?.length > 0 && (
        <Card title="Pick history" className="span-12" id="pick-history">
          <div className="tw"><table>
            <thead><tr><th>Date</th><th>Score</th><th>Conf.</th><th className="n">Entry</th><th className="n">Stop</th><th className="n">Target</th><th>Outcome</th><th className="n">R</th></tr></thead>
            <tbody>{data.picks.map((p) => (
              <tr key={p.id}><td>{p.jackpot ? '★ ' : ''}{p.date}</td><td><ScoreChip v={p.score} /></td><td><ConfBar v={p.confidence} /></td>
                <td className="n">{fmt.price(p.entry)}</td><td className="n">{fmt.price(p.stop)}</td><td className="n">{fmt.price(p.target)}</td>
                <td>{p.status}{p.exit_date ? ` · ${p.exit_date}` : ''}</td><td className={`n ${p.r_multiple > 0 ? 'good' : p.r_multiple < 0 ? 'bad' : ''}`}>{fmt.r(p.r_multiple)}</td></tr>
            ))}</tbody>
          </table></div>
        </Card>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- Track record
export function TrackRecord({ date, openSym }) {
  const { data, err } = useLoad(() => api.trackRecord(date), [date])
  if (err) return <div className="error">{err}</div>
  if (!data) return null
  const o = data.overall
  return (
    <div className="grid">
      <Card title="Live track record (closed picks)" className="span-12" id="track">
        <div className="stats">
          <Stat l="Closed trades" v={o.trades} />
          <Stat l="Hit rate" v={fmt.pct0(o.hit_rate)} />
          <Stat l="Avg per trade" v={fmt.r(o.avg_r)} cls={o.avg_r > 0 ? 'good' : 'bad'} />
          <Stat l="Total" v={fmt.r(o.total_r)} cls={o.total_r > 0 ? 'good' : 'bad'} />
          <Stat l="Jackpot hit rate" v={fmt.pct0(data.jackpot.hit_rate)} sub={`${data.jackpot.trades} trades`} />
          {Object.entries(data.by_market).map(([m, s]) => <Stat key={m} l={`${MKT[m]} hit rate`} v={fmt.pct0(s.hit_rate)} sub={`${s.trades} trades · ${fmt.r(s.avg_r)}`} />)}
        </div>
        <p className="note">With a 2:1 reward-to-risk target, a hit rate above ~34% breaks even before costs. Judge the system on average R per trade, not hit rate alone.</p>
        {data.equity.length > 1 && <LineChart series={[{ name: 'Cumulative R', data: data.equity.map((e, i) => ({ time: e.date, value: e.cum_r, i })).filter((e, i, a) => i === a.length - 1 || a[i + 1].time !== e.time) }]} height={220} zero />}
      </Card>
      <Card title="Calibration — historical hit-rate by score bucket" className="span-5" id="calibration">
        <div className="tw"><table>
          <thead><tr><th>Market</th><th>Score</th><th className="n">Trades</th><th className="n">Hit rate</th><th className="n">Avg R</th><th className="n">Edge (shrunk)</th></tr></thead>
          <tbody>{data.calibration.map((c) => (
            <tr key={c.market + c.bucket}><td>{MKT[c.market]}</td><td>{c.bucket}</td><td className="n">{c.trades}</td>
              <td className="n">{fmt.pct0(c.hit_rate)}</td><td className={`n ${c.avg_r > 0 ? 'good' : 'bad'}`}>{fmt.r(c.avg_r)}</td>
              <td className={`n ${c.expected_r > 0 ? 'good' : 'bad'}`}>{fmt.r(c.expected_r)}</td></tr>
          ))}</tbody>
        </table></div>
        <p className="note">Each pick's hit rate and edge come from this table, shrunk toward 50% / 0R when a bucket has few trades. Jackpot needs edge ≥ +0.15R.</p>
      </Card>
      <Card title="Recent closed picks" className="span-7" id="closed">
        <div className="tw"><table>
          <thead><tr><th>Exit</th><th>Instrument</th><th>Outcome</th><th className="n">R</th></tr></thead>
          <tbody>{data.closed.slice(0, 40).map((p) => (
            <tr key={p.id}><td>{p.exit_date}</td><td><button className="link" onClick={() => openSym(p.symbol)}>{p.jackpot ? '★ ' : ''}{p.name}</button></td>
              <td>{p.status}</td><td className={`n ${p.r_multiple > 0 ? 'good' : 'bad'}`}>{fmt.r(p.r_multiple)}</td></tr>
          ))}</tbody>
        </table></div>
      </Card>
    </div>
  )
}

function Stat({ l, v, sub, cls = '' }) {
  return <div className="stat"><small>{l}</small><b className={cls}>{v ?? '—'}</b>{sub && <em>{sub}</em>}</div>
}

// ---------------------------------------------------------------- Health
export function Health() {
  const { data, err } = useLoad(() => api.health(), [])
  if (err) return <div className="error">{err}</div>
  if (!data) return null
  const today = new Date().toISOString().slice(0, 10)
  const age = (d) => Math.round((new Date(today) - new Date(d)) / 86400000)
  return (
    <div className="grid">
      <Card title="Sources" className="span-6" id="sources">
        <div className="tw"><table>
          <thead><tr><th>Source</th><th>Last OK</th><th>Items</th><th>Last error</th></tr></thead>
          <tbody>{data.sources.map((s) => (
            <tr key={s.source}><td>{s.source}</td><td>{fmt.time(s.last_ok)}</td><td>{s.items ?? '—'}</td>
              <td className={s.last_error && (!s.last_ok || s.last_error > s.last_ok) ? 'bad' : 'muted'}>{s.last_error ? `${fmt.time(s.last_error)} — ${s.last_error_msg}` : '—'}</td></tr>
          ))}</tbody>
        </table></div>
      </Card>
      <Card title="Recent runs" className="span-6" id="runs">
        <div className="tw"><table>
          <thead><tr><th>Job</th><th>Finished</th><th>Status</th><th>Message</th></tr></thead>
          <tbody>{data.runs.map((r) => (
            <tr key={r.id}><td>{r.job}</td><td>{fmt.time(r.finished)}</td><td className={r.status === 'ok' ? 'good' : 'bad'}>{r.status}</td>
              <td className="muted sm trunc">{r.message}</td></tr>
          ))}</tbody>
        </table></div>
      </Card>
      <Card title="Data freshness per instrument" className="span-12" id="freshness">
        <div className="fresh">
          {data.freshness.map((f) => {
            const a = age(f.last_date)
            return <span key={f.symbol} className={`fr ${a > 4 ? 'bad' : a > 1 ? 'mid' : 'good'}`} title={`${f.bars} bars`}>{f.name || f.symbol} · {f.last_date}</span>
          })}
        </div>
      </Card>
    </div>
  )
}
