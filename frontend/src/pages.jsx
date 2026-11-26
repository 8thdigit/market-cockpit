import React, { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { LineChart } from './charts.jsx'
import { Card, ConfBar, Empty, Gauge, PATTERN_LABEL, ScoreChip, Sev, Spark, fmt } from './ui.jsx'

const MKT = { IN: 'India', US: 'US', CMD: 'Commodities' }
const ASSET_SHORT = { 'GC=F': 'Gold', 'BZ=F': 'Brent', '^GSPC': 'S&P 500', '^NSEI': 'Nifty' }
const IMPACT_KEYS = [['gold', 'Gold'], ['oil', 'Oil'], ['us', 'US stocks'], ['india', 'India']]
const FEATURE_LABEL = {
  dollar: 'Dollar 20d %', yields: '10-yr 20d bp', oil: 'Brent 20d %', gold: 'Gold 20d %', vix: 'VIX',
  fed: 'Fed 3m chg', spx_trend: 'S&P vs 50-DMA %', nifty_trend: 'Nifty vs 50-DMA %',
}

export function usePage(name, date) {
  const [st, set] = useState({ data: null, err: '' })
  useEffect(() => {
    let live = true
    api.page(name, date || null).then((data) => live && set({ data, err: '' })).catch((e) => live && set({ data: null, err: e.message }))
    return () => { live = false }
  }, [name, date])
  return st
}

const signed = (v, d = 1, unit = '%') => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(d)}${unit}`)
const tone = (v) => (v > 0 ? 'good' : v < 0 ? 'bad' : 'muted')

function StanceBadge({ s }) {
  const cls = { BUY: 'buy', 'ACCUMULATE DIPS': 'acc', SELL: 'sell', 'SELL RALLIES': 'sellr', WAIT: 'wait' }[s] || 'wait'
  return <span className={`stance st-${cls}`}>{s}</span>
}

function Outcome({ o }) {
  if (o === 'met') return <span className="good">✓ met</span>
  if (o === 'failed') return <span className="bad">✗ failed</span>
  if (o === 'pending') return <span className="muted">pending</span>
  return <span className="muted">—</span>
}

function Bias({ b, p }) {
  return <span className={`bias b-${b}`}>{b === 'up' ? '▲ up' : b === 'down' ? '▼ down' : '◆ neutral'} {p != null && <small>{Math.round(p * 100)}%</small>}</span>
}

function Loading({ err }) {
  return err ? <div className="error">{err}</div> : <div className="empty big">Loading…</div>
}

function Pct({ v, d = 0 }) {
  return v == null ? '—' : `${(v * 100).toFixed(d)}%`
}

function levelFmt(i) {
  if (i.level == null) return '—'
  if (i.id === 'geopolitics') return i.level.toFixed(2)
  if (i.id === 'inflation') return `${i.level.toFixed(1)}%`
  if (['fed', 'yields', 'real_yield'].includes(i.id)) return `${i.level.toFixed(2)}%`
  return fmt.price(i.level)
}

function signalFmt(i) {
  if (i.kind === 'level' || i.kind === 'sent') return i.kind === 'sent' ? i.signal.toFixed(2) : i.signal.toFixed(1)
  if (i.kind === 'pct') return `${signed(i.signal)} / ${i.window}d`
  if (i.kind === 'bp' || i.kind === 'bp_macro') return `${signed(i.signal, 0, ' bp')} / ${i.window}d`
  if (i.kind === 'chg') return `${signed(i.signal, 2, ' pts')} / 3m`
  if (i.kind === 'yoy_chg') return `${signed(i.signal, 2, ' pts')} / 1m`
  return i.signal.toFixed(2)
}

// =============================================================== Page 1: Influencers
export function InfluencersPage({ date, openSym }) {
  const { data, err } = usePage('influencers', date)
  if (!data) return <Loading err={err} />
  if (data.empty) return <Empty>No data yet.</Empty>
  const reg = data.regime
  return (
    <div className="grid">
      <Card title="Macro regime" className="span-3" id="p1-regime">
        {reg ? (
          <div className="regime compact">
            <Gauge score={reg.score} label={reg.label} />
            <div className={`reg-label ${reg.label === 'Risk-on' ? 'good' : reg.label === 'Risk-off' ? 'bad' : 'mid'}`}>{reg.label}</div>
          </div>
        ) : <Empty>—</Empty>}
      </Card>
      <Card title="Recommendation by market — next few days" className="span-9" id="p1-calls">
        <div className="calls">
          {data.markets.map((m) => (
            <button key={m.symbol} className="call" onClick={() => openSym(m.symbol)}>
              <div className="call-h"><b>{m.name}</b><StanceBadge s={m.stance} /></div>
              <div className="call-px">{fmt.price(m.close)}</div>
              <div className="call-row"><span>Next 5 days</span><Bias b={m.prob_up_5d >= 0.6 ? 'up' : m.prob_up_5d <= 0.4 ? 'down' : 'neutral'} p={m.prob_up_5d} /></div>
              {m.range5 && <div className="call-row"><span>Likely range</span><span>{fmt.price(m.range5[0])} – {fmt.price(m.range5[1])}</span></div>}
              <div className="call-why">{m.rationale[0]}</div>
            </button>
          ))}
        </div>
      </Card>

      <div className="span-12 section-h"><h2>Influencer movements</h2><p>What each driver is doing now, how it usually pushes each market, and what actually happened next when it was in this state before.</p></div>
      {data.influencers.map((i) => (
        <Card key={i.id} className="span-4 infl" id={`infl-${i.id}`}
          title={i.name} right={<span className={`state s-${i.direction > 0 ? 'up' : i.direction < 0 ? 'down' : 'flat'}`}>{i.state}</span>}>
          <div className="infl-top">
            <div><div className="infl-lvl">{levelFmt(i)}</div><div className="muted sm">{signalFmt(i)}</div></div>
            <div className="infl-spark"><Spark data={i.spark.map((x) => ({ close: x.value }))} up={i.direction >= 0} /></div>
          </div>
          {i.percentile != null && (
            <div className="pctile" title="Where today's move ranks versus the last 3 years">
              <span>3-yr rank</span><i><b style={{ left: `${i.percentile * 100}%` }} /></i><em>{Math.round(i.percentile * 100)}th</em>
            </div>
          )}
          <div className="impact">
            {IMPACT_KEYS.map(([k, l]) => (
              <span key={k} className={`imp-chip ${i.impact[k] > 0 ? 'pos' : i.impact[k] < 0 ? 'neg' : 'neu'}`}>{l} {i.impact[k] > 0 ? '▲' : i.impact[k] < 0 ? '▼' : '–'}</span>
            ))}
          </div>
          <div className="hs">
            <div className="hs-h">History says — next 10 days when {i.state} ({i.history_n} days)</div>
            <table className="mini"><tbody>
              {Object.entries(i.history_says).map(([sym, h]) => (
                <tr key={sym}><td>{h.name}</td><td className={`n ${tone(h.avg)}`}>{signed(h.avg)}</td>
                  <td className="n">{Math.round(h.pct_up * 100)}% up</td></tr>
              ))}
            </tbody></table>
          </div>
        </Card>
      ))}

      <Card title="What to expect — next 5 trading days: call, confidence, expected exit" className="span-8" id="p1-expect">
        <ExpectTable pred={data.predictions} rows={data.expectations} openSym={openSym} />
        <p className="note">Call: BUY / SELL / WATCH for the next 5 trading days. Expected exit = analog median 5-day outcome; stop = far edge of the range. Range = ±1 standard deviation of recent daily moves (about 2 in 3 outcomes land inside). "Analogs" = the 15 most similar past setups (see History page).</p>
      </Card>
      <div className="span-4 stack">
        <Card title="Upcoming events" id="p1-events">
          {data.events.length ? <ul className="events">{data.events.map((e) => (
            <li key={e.ts + e.title}><span className={`imp imp-${e.impact}`}>{e.impact.replace('_', ' ')}</span><div><div>{e.title}</div><small>{fmt.time(e.ts)}</small></div></li>
          ))}</ul> : <Empty>No scheduled events in the next 3 weeks.</Empty>}
        </Card>
        <Card title="Key alerts" id="p1-alerts">
          {data.alerts.length ? <ul className="alerts">{data.alerts.map((a) => (
            <li key={a.id} className={`al al-${a.severity}`}><Sev s={a.severity} /><div><div className="al-t">{a.title}</div></div><span /></li>
          ))}</ul> : <Empty>No warnings today.</Empty>}
        </Card>
        {data.news.length > 0 && (
          <Card title="Headlines" id="p1-news">
            <ul className="news">{data.news.map((n) => (
              <li key={n.ts + n.title}><span className={n.sentiment > 0.15 ? 'good' : n.sentiment < -0.15 ? 'bad' : 'muted'}>●</span>
                {n.url ? <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a> : n.title}</li>
            ))}</ul>
          </Card>
        )}
      </div>
      <PredictionRecord pred={data.predictions} />
    </div>
  )
}

function CallBadge({ c }) {
  return <span className={`stance st-${c === 'BUY' ? 'buy' : c === 'SELL' ? 'sell' : 'wait'}`}>{c}</span>
}

function ConfScore({ v }) {
  const cls = v >= 65 ? 'good' : v >= 55 ? 'mid' : 'bad'
  return <span className="cscore"><i><b className={cls} style={{ width: `${v}%` }} /></i><em className={cls}>{v}</em></span>
}

function ExpectTable({ pred, rows, openSym }) {
  const list = pred?.rows || rows || []
  return (
    <div className="tw"><table>
      <thead><tr><th>Asset</th><th className="n">Now</th><th>Call</th><th>Confidence</th><th className="n">Expected exit (5d)</th>
        <th className="n">Stop</th><th>5-day range</th><th>P(up 5d)</th><th className="n">Last 20</th></tr></thead>
      <tbody>{list.map((e) => {
        const isRate = e.symbol === '^TNX'
        const px = (v) => (v == null ? '—' : isRate ? `${fmt.num(v, 2)}%` : fmt.price(v))
        const chg = e.exit != null ? (e.exit / e.close - 1) * 100 : null
        return (
          <tr key={e.symbol}>
            <td><button className="link" onClick={() => openSym(e.symbol)}>{e.name}</button></td>
            <td className="n">{px(e.close)}</td>
            <td>{e.call ? <CallBadge c={e.call} /> : <Bias b={e.bias} />}</td>
            <td>{e.confidence != null ? <ConfScore v={e.confidence} /> : '—'}</td>
            <td className="n">{px(e.exit ?? e.center5)} <small className={tone(chg)}>{chg != null ? signed(chg) : ''}</small></td>
            <td className="n bad">{px(e.stop)}</td>
            <td>{e.range5 ? <RangeBar lo={e.range5[0]} hi={e.range5[1]} c={e.close} center={e.exit ?? e.center5} /> : '—'}</td>
            <td><Bias b={e.bias} p={e.prob_up_5d} /></td>
            <td className="n">{e.track ? <span title="Successful predictions out of the last resolved ones">{e.track.hits}/{e.track.n} <small className="muted">{e.track.rate != null ? `${Math.round(e.track.rate * 100)}%` : ''}</small></span> : '—'}</td>
          </tr>
        )
      })}</tbody>
    </table></div>
  )
}

function PredictionRecord({ pred, title = 'Prediction track record — last 20 sets' }) {
  if (!pred?.sets?.length) return null
  const syms = pred.rows.map((r) => r.symbol)
  const names = Object.fromEntries(pred.rows.map((r) => [r.symbol, r.name]))
  const o = pred.overall
  return (
    <Card title={title} className="span-12" id="pred-record"
      right={<span className="muted sm">Each call checked 5 trading days later</span>}>
      <div className="stats">
        <Stat l="Resolved predictions" v={o.n} />
        <Stat l="Successful" v={o.hits} cls="good" />
        <Stat l="Failed" v={o.n - o.hits} cls="bad" />
        <Stat l="Success rate" v={<Pct v={o.rate} />} />
        <Stat l="Overall confidence today" v={o.confidence != null ? `${o.confidence}/100` : '—'} />
      </div>
      <div className="tw scroll"><table className="matrix">
        <thead><tr><th>Date</th>{syms.map((s) => <th key={s} className="c">{names[s]}</th>)}</tr></thead>
        <tbody>
          {pred.sets.map((set) => (
            <tr key={set.date}><td>{set.date}</td>{syms.map((s) => {
              const c = set.calls[s]
              if (!c) return <td key={s} className="c muted">—</td>
              const cls = c.result === 'success' ? 'ok' : c.result === 'fail' ? 'ko' : 'pend'
              return (
                <td key={s} className={`c cell-${cls}`} title={`${c.call} at ${fmt.price(c.close)}${c.close5 ? ` → ${fmt.price(c.close5)} (${signed(c.ret5)})` : ' (pending)'}`}>
                  <b>{c.call[0]}</b> {c.result === 'success' ? '✓' : c.result === 'fail' ? '✗' : '…'}
                  {c.ret5 != null && <small> {signed(c.ret5)}</small>}
                </td>
              )
            })}</tr>
          ))}
          <tr className="sumrow"><td>Success</td>{syms.map((s) => {
            const t = pred.summary[s]
            return <td key={s} className="c"><b>{t.rate != null ? `${Math.round(t.rate * 100)}%` : '—'}</b> <small className="muted">{t.hits}/{t.n}</small></td>
          })}</tr>
        </tbody>
      </table></div>
      <p className="note">B = buy, S = sell, W = watch. {pred.rules}</p>
    </Card>
  )
}

function RangeBar({ lo, hi, c, center }) {
  const pos = (v) => `${Math.max(0, Math.min(100, ((v - lo) / (hi - lo || 1)) * 100))}%`
  return (
    <span className="rbar" title={`${fmt.price(lo)} – ${fmt.price(hi)}`}>
      <small>{fmt.price(lo)}</small>
      <i>{center && <b className="ctr" style={{ left: pos(center) }} />}<b className="now" style={{ left: pos(c) }} /></i>
      <small>{fmt.price(hi)}</small>
    </span>
  )
}

// =============================================================== Page 2: History
export function HistoryPage({ date }) {
  const { data, err } = usePage('history', date)
  const [h, setH] = useState(10)
  if (!data) return <Loading err={err} />
  if (data.empty) return <Empty>No data yet.</Empty>
  const an = data.analogs || {}
  const feats = an.features || []
  const avgFeat = (k) => (an.analogs?.length ? an.analogs.reduce((s, a) => s + a.features[k], 0) / an.analogs.length : null)
  return (
    <div className="grid">
      <div className="span-12 section-h"><h2>What history says</h2>
        <p>The engine scans {data.history_from ? `every trading day since ${data.history_from}` : 'the stored history'} for the 15 days whose mix of dollar, yields, oil, gold, VIX, Fed and index trends looked most like {data.date}, then shows what markets did next. Only past data is used.</p></div>

      <Card title="Today's fingerprint vs the analog average" className="span-5" id="p2-fp">
        {feats.length ? (
          <table><thead><tr><th>Factor</th><th className="n">Today</th><th className="n">Analogs avg</th></tr></thead>
            <tbody>{feats.map((k) => (
              <tr key={k}><td>{FEATURE_LABEL[k] || k}</td><td className="n">{fmt.num(an.today?.[k], 1)}</td><td className="n muted">{fmt.num(avgFeat(k), 1)}</td></tr>
            ))}</tbody></table>
        ) : <Empty>Not enough history yet for analogs.</Empty>}
      </Card>

      <Card title="What followed in the analogs" className="span-7" id="p2-fwd"
        right={<div className="seg">{[5, 10, 20].map((x) => <button key={x} className={h === x ? 'on' : ''} onClick={() => setH(x)}>{x} days</button>)}</div>}>
        <div className="fwd">
          {Object.entries(data.targets).map(([sym, name]) => {
            const st = an.forward?.[sym]?.[h]
            if (!st) return null
            return (
              <div key={sym} className="fwd-row">
                <b>{name}</b>
                <DistBar st={st} />
                <span className={`n ${tone(st.median)}`}>median {signed(st.median)}</span>
                <span className="n">{Math.round(st.pct_up * 100)}% rose</span>
              </div>
            )
          })}
        </div>
        <p className="note">Bar shows the 10th–90th percentile of outcomes across the analogs; the tick is the median.</p>
      </Card>

      <Card title="The 15 closest historical analogs" className="span-12" id="p2-analogs">
        <div className="tw"><table>
          <thead><tr><th>Date</th><th className="n">Similarity</th>{feats.map((k) => <th key={k} className="n">{FEATURE_LABEL[k] || k}</th>)}
            {Object.values(ASSET_SHORT).map((n) => <th key={n} className="n">{n} +{h}d</th>)}</tr></thead>
          <tbody>{(an.analogs || []).map((a) => (
            <tr key={a.date}><td>{a.date}</td><td className="n">{(1 / (1 + a.distance) * 100).toFixed(0)}%</td>
              {feats.map((k) => <td key={k} className="n muted">{fmt.num(a.features[k], 1)}</td>)}
              {Object.keys(ASSET_SHORT).map((sym) => {
                const v = a.forward?.[sym]?.[h]
                return <td key={sym} className={`n ${tone(v)}`}>{signed(v)}</td>
              })}</tr>
          ))}</tbody>
        </table></div>
      </Card>

      <Card title="What we can expect next few days" className="span-12" id="p2-expect">
        <ExpectTable pred={data.predictions} rows={data.expectations} openSym={() => {}} />
      </Card>
      <PredictionRecord pred={data.predictions} />

      <div className="span-12 section-h"><h2>Historical reference episodes</h2><p>Moves computed from stored prices for each window (where history covers it).</p></div>
      {data.episodes.map((e) => (
        <Card key={e.name} className="span-6 episode" title={e.name} right={<small className="muted">{e.start} → {e.end}</small>}>
          <p className="ep-setup">{e.setup}</p>
          {Object.keys(e.moves).length ? (
            <div className="ep-moves">{Object.entries(e.moves).map(([sym, m]) => (
              <span key={sym} className="ep-m"><small>{m.name}</small><b className={tone(m.change)}>{signed(m.change, m.unit === 'bp' ? 0 : 1, m.unit === 'bp' ? ' bp' : '%')}</b>
                {m.max_drawdown != null && <em>max dd {m.max_drawdown.toFixed(1)}%</em>}</span>
            ))}</div>
          ) : <p className="muted sm">Before the stored history; add a longer backfill (COCKPIT_MACRO_YEARS) to compute.</p>}
          <p className="ep-lesson"><b>Lesson:</b> {e.lesson}</p>
        </Card>
      ))}
    </div>
  )
}

function DistBar({ st }) {
  const lim = Math.max(Math.abs(st.p10), Math.abs(st.p90), 1)
  const x = (v) => `${50 + (v / lim) * 48}%`
  return (
    <span className="dist">
      <i className="zero" />
      <b style={{ left: x(st.p10), width: `calc(${x(st.p90)} - ${x(st.p10)})` }} className={st.median >= 0 ? 'pos' : 'neg'} />
      <em style={{ left: x(st.median) }} />
    </span>
  )
}

// =============================================================== Page 3: Stocks cockpit
export function StocksPage({ date, openSym }) {
  const { data, err } = usePage('stocks', date)
  const [mkt, setMkt] = useState('')
  const [open, setOpen] = useState(null)
  if (!data) return <Loading err={err} />
  if (data.empty) return <Empty>No data yet.</Empty>
  const picks = data.picks.filter((p) => !mkt || p.market === mkt)
  const rec = data.record
  return (
    <div className="grid">
      <Card title="Stock recommendation scorecard (all picks so far)" className="span-12" id="p3-score">
        <div className="stats">
          <Stat l="Closed picks" v={rec.all.closed} sub={`${rec.all.open} still open`} />
          <Stat l="Hit target" v={rec.all.target_hit} sub={<Pct v={rec.all.target_rate} />} cls="good" />
          <Stat l="Stopped out" v={rec.all.stopped} cls="bad" />
          <Stat l="Success rate (closed in profit)" v={<Pct v={rec.all.success} />} />
          <Stat l="Avg result" v={fmt.r(rec.all.avg_r)} cls={tone(rec.all.avg_r)} sub={`total ${fmt.r(rec.all.total_r)}`} />
          <Stat l="India" v={<Pct v={rec.IN.success} />} sub={`${rec.IN.closed} closed · ${fmt.r(rec.IN.avg_r)}`} />
          <Stat l="US" v={<Pct v={rec.US.success} />} sub={`${rec.US.closed} closed · ${fmt.r(rec.US.avg_r)}`} />
          <Stat l="Jackpot" v={<Pct v={rec.jackpot.success} />} sub={`${rec.jackpot.closed} closed`} />
        </div>
      </Card>

      <Card title={`Jackpot — top conviction · ${data.date}`} className="span-12 jackpot-card" id="p3-jackpot">
        {data.jackpot.length ? <div className="jp-row">{data.jackpot.map((p) => <PickCard key={p.id} p={p} openSym={openSym} />)}</div>
          : <Empty>No stock clears the jackpot bar today (score ≥ 80 and a proven historical edge). Waiting is part of the strategy.</Empty>}
      </Card>

      <Card title={`Recommendations · ${data.date}`} className="span-12" id="p3-picks"
        right={<div className="seg">{[['', 'All'], ['IN', 'India'], ['US', 'US']].map(([k, l]) => <button key={k} className={mkt === k ? 'on' : ''} onClick={() => setMkt(k)}>{l}</button>)}</div>}>
        {picks.length ? (
          <div className="tw"><table>
            <thead><tr><th>Stock</th><th>Mkt</th><th>Score</th><th className="n">Buy at</th><th className="n">Stop</th><th className="n">Target</th>
              <th>Expectation</th><th>Hit rate</th><th className="n">Edge</th><th /></tr></thead>
            <tbody>{picks.map((p) => (
              <React.Fragment key={p.id}>
                <tr className={p.jackpot ? 'jp-row-hl' : ''}>
                  <td><button className="link" onClick={() => openSym(p.symbol)}>{p.jackpot && '★ '}{p.name}</button><div className="muted sm">{p.symbol}</div></td>
                  <td>{MKT[p.market]}</td><td><ScoreChip v={p.score} /></td>
                  <td className="n">{fmt.price(p.entry)}</td><td className="n bad">{fmt.price(p.stop)} <small>({fmt.pct(-p.risk_pct)})</small></td>
                  <td className="n good">{fmt.price(p.target)} <small>({fmt.pct(p.reward_pct)})</small></td>
                  <td className="sm">{fmt.pct(p.reward_pct)} within 15 trading days, or exit at stop</td>
                  <td><ConfBar v={p.confidence} /></td><td className={`n ${tone(p.expected_r)}`}>{fmt.r(p.expected_r)}</td>
                  <td><button className="link" onClick={() => setOpen(open === p.id ? null : p.id)}>{open === p.id ? 'Hide' : 'Why?'}</button></td>
                </tr>
                {open === p.id && <tr className="why-row"><td colSpan={10}><ul className="why">{p.rationale.map((w) => <li key={w}>{w}</li>)}</ul></td></tr>}
              </React.Fragment>
            ))}</tbody>
          </table></div>
        ) : <Empty>No new stock setups scored 70+ on this date.</Empty>}
      </Card>

      {['IN', 'US'].map((m) => (
        <Card key={m} title={`Recommended ${m === 'IN' ? 'India' : 'US'} stocks`} className="span-6" id={`p3-rec-${m}`}
          right={<span className="muted sm">BUY = triggered now · WATCH = buy only above entry</span>}>
          <RecList rows={data.recommended?.[m] || []} openSym={openSym} />
        </Card>
      ))}
      <Card title="Index outlook — next 5 days" className="span-12" id="p3-index">
        <ExpectTable pred={data.predictions} rows={data.expectations} openSym={openSym} />
      </Card>
      <PredictionRecord pred={data.predictions} title="Index prediction track record — last 20 sets" />
      <Card title="Watchlist — closest to a trigger" className="span-12" id="p3-watch">
        <div className="tw"><table>
          <thead><tr><th>Stock</th><th>Score</th><th>Trend</th><th className="n">RSI</th><th className="n">RS 3m</th><th>Candles</th></tr></thead>
          <tbody>{data.watchlist.filter((s) => s.score >= 50).slice(0, 15).map((s) => (
            <tr key={s.symbol}><td><button className="link" onClick={() => openSym(s.symbol)}>{s.name}</button> <span className="muted sm">{MKT[s.market]}</span></td>
              <td><ScoreChip v={s.score} /></td><td className={s.trend === 'uptrend' ? 'good' : s.trend === 'downtrend' ? 'bad' : ''}>{s.trend}</td>
              <td className="n">{fmt.num(s.rsi, 0)}</td><td className={`n ${tone(s.rs_63)}`}>{fmt.pct(s.rs_63)}</td>
              <td className="pats">{s.patterns.map((x) => <span key={x} className="pat">{PATTERN_LABEL(x)}</span>)}</td></tr>
          ))}</tbody>
        </table></div>
      </Card>

      <Card title="Open positions" className="span-6" id="p3-open">
        <PickHistory rows={data.open} openSym={openSym} openOnly />
      </Card>
      <Card title="Past recommendations and outcomes" className="span-6" id="p3-closed">
        <PickHistory rows={data.closed} openSym={openSym} />
      </Card>
      <Card title="Calibration — historical replay by score" className="span-12" id="p3-calib"><Calib rows={data.calibration} /></Card>
    </div>
  )
}

function RecList({ rows, openSym }) {
  if (!rows.length) return <Empty>No stock in an uptrend scores 50+ today.</Empty>
  return (
    <div className="tw"><table>
      <thead><tr><th>Stock</th><th>Call</th><th>Confidence</th><th className="n">Entry</th><th className="n">Exit (target)</th>
        <th className="n">Stop</th><th className="n">Past picks</th></tr></thead>
      <tbody>{rows.map((r) => (
        <tr key={r.symbol}>
          <td><button className="link" onClick={() => openSym(r.symbol)}>{r.name}</button><div className="muted sm">{r.symbol} · score {Math.round(r.score)}</div></td>
          <td><CallBadge c={r.call} /></td>
          <td><ConfScore v={r.confidence} /></td>
          <td className="n">{r.call === 'WATCH' ? <small className="muted">above </small> : null}{fmt.price(r.entry)}</td>
          <td className="n good">{fmt.price(r.exit)} <small>{fmt.pct(r.upside)}</small></td>
          <td className="n bad">{fmt.price(r.stop)} <small>{fmt.pct(-r.risk)}</small></td>
          <td className="n">{r.own_record ? `${r.own_record.wins}/${r.own_record.closed}` : '—'}</td>
        </tr>
      ))}</tbody>
    </table></div>
  )
}

function PickCard({ p, openSym }) {
  return (
    <button className="jp" onClick={() => openSym(p.symbol)}>
      <div className="jp-h"><span className="jp-star">★</span><b>{p.name}</b><span className="muted">{p.symbol} · {MKT[p.market]}{p.direction === 'short' ? ' · SHORT' : ''}</span></div>
      <div className="jp-nums">
        <div><small>Entry</small>{fmt.price(p.entry)}</div>
        <div><small>Stop</small><span className="bad">{fmt.price(p.stop)}</span></div>
        <div><small>Target</small><span className="good">{fmt.price(p.target)}</span></div>
      </div>
      <div className="jp-meta"><ScoreChip v={p.score} /><ConfBar v={p.confidence} /><span className={tone(p.expected_r)}>edge {fmt.r(p.expected_r)}</span></div>
      <ul className="why">{p.rationale.slice(0, 5).map((w) => <li key={w}>{w}</li>)}</ul>
    </button>
  )
}

function PickHistory({ rows, openSym, openOnly }) {
  if (!rows.length) return <Empty>{openOnly ? 'No open positions.' : 'No closed recommendations yet.'}</Empty>
  return (
    <div className="tw scroll"><table>
      <thead><tr><th>Date</th><th>Instrument</th><th>Side</th><th className="n">Entry</th><th className="n">Stop</th><th className="n">Target</th><th>Outcome</th><th className="n">R</th></tr></thead>
      <tbody>{rows.map((p) => (
        <tr key={p.id}><td>{p.date}</td><td><button className="link" onClick={() => openSym(p.symbol)}>{p.jackpot ? '★ ' : ''}{p.name}</button></td>
          <td className={p.direction === 'short' ? 'bad' : 'good'}>{p.direction}</td>
          <td className="n">{fmt.price(p.entry)}</td><td className="n">{fmt.price(p.stop)}</td><td className="n">{fmt.price(p.target)}</td>
          <td>{p.status === 'target' ? <span className="good">✓ target {p.exit_date}</span> : p.status === 'stopped' ? <span className="bad">✗ stopped {p.exit_date}</span>
            : p.status === 'expired' ? <span className="muted">time exit {p.exit_date}</span> : <span className="muted">open</span>}</td>
          <td className={`n ${tone(p.r_multiple)}`}>{fmt.r(p.r_multiple)}</td></tr>
      ))}</tbody>
    </table></div>
  )
}

function Calib({ rows }) {
  const lbl = { IN: 'India', US: 'US', CMD: 'Commodities long', 'CMD-S': 'Commodities short' }
  return (
    <div className="tw"><table>
      <thead><tr><th>Market</th><th>Score</th><th className="n">Past trades</th><th className="n">Hit target first</th><th className="n">Avg R</th><th className="n">Edge (shrunk)</th></tr></thead>
      <tbody>{rows.map((c) => (
        <tr key={c.market + c.bucket}><td>{lbl[c.market] || c.market}</td><td>{c.bucket}</td><td className="n">{c.trades}</td>
          <td className="n"><Pct v={c.hit_rate} /></td><td className={`n ${tone(c.avg_r)}`}>{fmt.r(c.avg_r)}</td><td className={`n ${tone(c.expected_r)}`}>{fmt.r(c.expected_r)}</td></tr>
      ))}</tbody>
    </table></div>
  )
}

function Stat({ l, v, sub, cls = '' }) {
  return <div className="stat"><small>{l}</small><b className={cls}>{v ?? '—'}</b>{sub && <em>{sub}</em>}</div>
}

// =============================================================== Page 4: Gold & Oil cockpit
export function CommoditiesPage({ date, openSym }) {
  const { data, err } = usePage('commodities', date)
  const [filter, setFilter] = useState('')
  if (!data) return <Loading err={err} />
  if (data.empty) return <Empty>No data yet.</Empty>
  const sr = data.stance_record
  const pr = data.pick_record
  const hist = sr.history.filter((h) => h.direction !== 0 && (!filter || h.symbol === filter))
  return (
    <div className="grid">
      {data.stances.map((s) => (
        <Card key={s.symbol} className="span-6 cmd" id={`cmd-${s.symbol}`}
          title={<span><button className="link big" onClick={() => openSym(s.symbol)}>{s.name}</button></span>} right={<StanceBadge s={s.stance} />}>
          <div className="cmd-top">
            <div><div className="cmd-px">{fmt.price(s.close)}</div><div className="muted sm">{s.trend} · conf. {Math.round(s.confidence * 100)}%</div></div>
            <div className="cmd-spark"><Spark data={s.spark} up={s.direction >= 0} w={220} h={48} /></div>
          </div>
          <div className="cmd-levels">
            <div><small>{s.direction < 0 ? 'Sell zone' : 'Buy zone'}</small>{s.entry ? (s.entry[0] === s.entry[1] ? fmt.price(s.entry[0]) : `${fmt.price(s.entry[0])} – ${fmt.price(s.entry[1])}`) : '—'}</div>
            <div><small>Stop</small><span className="bad">{fmt.price(s.stop)}</span></div>
            <div><small>Target</small><span className="good">{fmt.price(s.target)}</span></div>
            <div><small>P(up) 5d</small>{Math.round(s.prob_up_5d * 100)}%</div>
            <div><small>5-day range</small>{s.range5 ? `${fmt.price(s.range5[0])} – ${fmt.price(s.range5[1])}` : '—'}</div>
          </div>
          <div className="scores"><span>Long setup <ScoreChip v={s.long_score} /></span><span>Short setup <ScoreChip v={s.short_score} /></span>
            <span>Track record <b>{sr.per_symbol[s.symbol]?.success != null ? `${Math.round(sr.per_symbol[s.symbol].success * 100)}%` : '—'}</b> <small className="muted">of {sr.per_symbol[s.symbol]?.decided || 0} calls</small></span></div>
          <ul className="why">{s.rationale.map((w) => <li key={w}>{w}</li>)}</ul>
        </Card>
      ))}

      <Card title="Next 5 days — call, confidence, expected exit" className="span-12" id="p4-expect">
        <ExpectTable pred={data.predictions} rows={data.expectations} openSym={openSym} />
      </Card>
      <PredictionRecord pred={data.predictions} title="5-day prediction track record — last 20 sets" />
      <Card title="Recommendation track record (each call checked 5 trading days later)" className="span-12" id="p4-record">
        <div className="stats">
          <Stat l="Directional calls" v={sr.overall.calls} sub={`${sr.overall.pending} pending`} />
          <Stat l="Met" v={sr.overall.met} cls="good" />
          <Stat l="Failed" v={sr.overall.failed} cls="bad" />
          <Stat l="Success rate" v={<Pct v={sr.overall.success} />} />
          <Stat l="Avg 5-day move in call's direction" v={signed(sr.overall.avg_ret_dir, 2)} cls={tone(sr.overall.avg_ret_dir)} />
          {Object.entries(sr.by_stance).filter(([, v]) => v.decided).map(([k, v]) => <Stat key={k} l={k} v={<Pct v={v.success} />} sub={`${v.met}/${v.decided} met`} />)}
        </div>
        <div className="per-sym">
          {Object.entries(sr.per_symbol).map(([sym, v]) => (
            <div key={sym} className="ps"><b>{v.name}</b>
              <div className="ps-bar"><i style={{ width: `${(v.success || 0) * 100}%` }} /></div>
              <span>{v.success != null ? `${Math.round(v.success * 100)}%` : '—'} <small className="muted">{v.met} met · {v.failed} failed</small></span></div>
          ))}
        </div>
      </Card>

      <Card title="Past calls and outcomes" className="span-7" id="p4-hist"
        right={<select value={filter} onChange={(e) => setFilter(e.target.value)}><option value="">All</option>{data.stances.map((s) => <option key={s.symbol} value={s.symbol}>{s.name}</option>)}</select>}>
        <div className="tw scroll"><table>
          <thead><tr><th>Date</th><th>Asset</th><th>Call</th><th className="n">Price</th><th className="n">5 days later</th><th>Outcome</th></tr></thead>
          <tbody>{hist.map((h) => (
            <tr key={h.date + h.symbol}><td>{h.date}</td><td>{h.name}</td><td><StanceBadge s={h.stance} /></td><td className="n">{fmt.price(h.close)}</td>
              <td className={`n ${tone(h.ret_5d)}`}>{signed(h.ret_5d, 2)}</td><td><Outcome o={h.outcome} /></td></tr>
          ))}</tbody>
        </table></div>
      </Card>

      <div className="span-5 stack">
        <Card title="Trade picks (long & short) — results" id="p4-picks">
          <div className="stats">
            <Stat l="Closed" v={pr.all.closed} sub={`${pr.all.open} open`} />
            <Stat l="Target hit" v={pr.all.target_hit} cls="good" />
            <Stat l="Stopped" v={pr.all.stopped} cls="bad" />
            <Stat l="Success" v={<Pct v={pr.all.success} />} sub={`avg ${fmt.r(pr.all.avg_r)}`} />
          </div>
          <table className="mini"><thead><tr><th>Asset</th><th className="n">Closed</th><th className="n">Success</th><th className="n">Avg R</th></tr></thead>
            <tbody>{['GC=F', 'SI=F', 'BZ=F', 'CL=F', 'long', 'short'].map((k) => pr[k] && (
              <tr key={k}><td>{pr[k].name || (k === 'long' ? 'All longs' : 'All shorts')}</td><td className="n">{pr[k].closed}</td>
                <td className="n"><Pct v={pr[k].success} /></td><td className={`n ${tone(pr[k].avg_r)}`}>{fmt.r(pr[k].avg_r)}</td></tr>
            ))}</tbody></table>
        </Card>
        <Card title="Drivers that move gold & oil" id="p4-drivers">
          <ul className="drv">{data.drivers.map((d) => (
            <li key={d.id}><span>{d.name}</span><span className={`state s-${d.direction > 0 ? 'up' : d.direction < 0 ? 'down' : 'flat'}`}>{d.state}</span>
              <span className="sm">Gold {d.impact.gold > 0 ? '▲' : d.impact.gold < 0 ? '▼' : '–'} · Oil {d.impact.oil > 0 ? '▲' : d.impact.oil < 0 ? '▼' : '–'}</span></li>
          ))}</ul>
        </Card>
        <Card title="Events that move commodities" id="p4-events">
          {data.events.length ? <ul className="events">{data.events.map((e) => (
            <li key={e.ts + e.title}><span className={`imp imp-${e.impact}`}>{e.impact.replace('_', ' ')}</span><div><div>{e.title}</div><small>{fmt.time(e.ts)}</small></div></li>
          ))}</ul> : <Empty>None scheduled.</Empty>}
        </Card>
      </div>

      <Card title="Trade picks history" className="span-12" id="p4-pickhist">
        <PickHistory rows={[...data.picks_today, ...data.open, ...data.closed]} openSym={openSym} />
      </Card>
      <Card title="Calibration — commodity setups" className="span-12" id="p4-calib"><Calib rows={data.calibration} /></Card>
    </div>
  )
}
