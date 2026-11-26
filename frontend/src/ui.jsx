import React from 'react'

export const fmt = {
  num: (v, d = 2) => (v == null || Number.isNaN(v) ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })),
  pct: (v, d = 1) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`),
  pct0: (v) => (v == null ? '—' : `${Math.round(v * 100)}%`),
  r: (v) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}R`),
  price: (v) => {
    if (v == null) return '—'
    const a = Math.abs(v)
    return fmt.num(v, a >= 1000 ? 0 : a >= 10 ? 2 : 3)
  },
  time: (iso) => (iso ? new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'),
}

export const SEVERITIES = ['info', 'watch', 'warning', 'critical']

export function Sev({ s }) {
  return <span className={`sev sev-${s}`}>{s}</span>
}

export function Card({ title, right, children, className = '', id }) {
  return (
    <section className={`card ${className}`} id={id}>
      {(title || right) && (
        <header className="card-h">
          <h3>{title}</h3>
          {right}
        </header>
      )}
      {children}
    </section>
  )
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>
}

export function Spark({ data, up, w = 120, h = 32 }) {
  if (!data || data.length < 2) return null
  const ys = data.map((d) => d.close)
  const min = Math.min(...ys), max = Math.max(...ys)
  const pts = ys.map((y, i) => `${(i / (ys.length - 1)) * w},${h - ((y - min) / (max - min || 1)) * (h - 2) - 1}`).join(' ')
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="spark" aria-hidden="true">
      <polyline points={pts} fill="none" className={up ? 'spark-up' : 'spark-dn'} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

export function ConfBar({ v }) {
  const pct = Math.round((v || 0) * 100)
  const cls = pct >= 60 ? 'good' : pct >= 50 ? 'mid' : 'bad'
  return (
    <span className="conf" title="Calibrated hit-rate of similar past setups">
      <i><b className={cls} style={{ width: `${pct}%` }} /></i>
      {pct}%
    </span>
  )
}

export function ScoreChip({ v }) {
  const cls = v >= 85 ? 'hi' : v >= 70 ? 'mid' : v >= 50 ? 'lo' : 'none'
  return <span className={`score score-${cls}`}>{Math.round(v)}</span>
}

export function Gauge({ score, label }) {
  const a = Math.PI * (1 - Math.min(100, Math.max(0, score)) / 100)
  const x = 60 + 48 * Math.cos(a), y = 60 - 48 * Math.sin(a)
  const cls = label === 'Risk-on' ? 'good' : label === 'Risk-off' ? 'bad' : 'mid'
  return (
    <svg viewBox="0 0 120 82" className="gauge" role="img" aria-label={`Regime ${label}, score ${score}`}>
      <path d="M12 60 A48 48 0 0 1 108 60" className="g-track" />
      <path d="M12 60 A48 48 0 0 1 40 21" className="g-bad" />
      <path d="M40 21 A48 48 0 0 1 80 21" className="g-mid" />
      <path d="M80 21 A48 48 0 0 1 108 60" className="g-good" />
      <line x1="60" y1="60" x2={x} y2={y} className="g-needle" />
      <circle cx="60" cy="60" r="4" className="g-hub" />
      <text x="60" y="80" textAnchor="middle" className={`g-val ${cls}`}>{Math.round(score)}</text>
    </svg>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <nav className="tabs" role="tablist">
      {tabs.map(([k, label]) => (
        <button key={k} role="tab" aria-selected={value === k} className={value === k ? 'on' : ''} onClick={() => onChange(k)}>
          {label}
        </button>
      ))}
    </nav>
  )
}

export const PATTERN_LABEL = (p) => p.replace(/_/g, ' ')
