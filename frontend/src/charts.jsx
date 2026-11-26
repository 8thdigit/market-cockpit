import React, { useEffect, useRef } from 'react'
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts'

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

function baseChart(el, height) {
  return createChart(el, {
    height,
    autoSize: true,
    layout: { background: { color: 'transparent' }, textColor: css('--muted'), fontFamily: 'inherit' },
    grid: { vertLines: { color: css('--grid') }, horzLines: { color: css('--grid') } },
    rightPriceScale: { borderColor: css('--line') },
    timeScale: { borderColor: css('--line'), timeVisible: false },
    crosshair: { mode: CrosshairMode.Normal },
  })
}

const BULL = new Set(['three_line_strike_bull', 'three_white_soldiers', 'morning_star', 'bullish_engulfing', 'hammer', 'selling_climax'])
const BEAR = new Set(['three_black_crows', 'evening_star', 'bearish_engulfing', 'shooting_star'])

export function CandleChart({ bars, signals, picks, height = 420 }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!ref.current || !bars?.length) return
    const chart = baseChart(ref.current, height)
    const candles = chart.addCandlestickSeries({
      upColor: css('--up'), downColor: css('--down'), borderVisible: false,
      wickUpColor: css('--up'), wickDownColor: css('--down'),
    })
    candles.setData(bars.map((b) => ({ time: b.date, open: b.open, high: b.high, low: b.low, close: b.close })))
    const vol = chart.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' } })
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
    vol.setData(bars.map((b) => ({ time: b.date, value: b.volume, color: b.close >= b.open ? css('--up-dim') : css('--down-dim') })))
    const ema = (key, color) => {
      const s = chart.addLineSeries({ color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
      s.setData(signals.filter((x) => x[key] != null).map((x) => ({ time: x.date, value: x[key] })))
    }
    ema('ema20', css('--c1'))
    ema('ema50', css('--c2'))
    ema('ema200', css('--c3'))
    const markers = []
    signals.forEach((s) => {
      const bull = s.patterns.filter((p) => BULL.has(p))
      const bear = s.patterns.filter((p) => BEAR.has(p))
      if (bull.length) markers.push({ time: s.date, position: 'belowBar', color: css('--up'), shape: 'arrowUp', text: bull[0].replace(/_/g, ' ') })
      if (bear.length) markers.push({ time: s.date, position: 'aboveBar', color: css('--down'), shape: 'arrowDown', text: bear[0].replace(/_/g, ' ') })
    })
    picks.forEach((p) => markers.push({ time: p.date, position: 'belowBar', color: css('--gold'), shape: 'circle', text: p.jackpot ? 'JACKPOT' : 'PICK' }))
    const seen = new Set()
    candles.setMarkers(markers.sort((a, b) => (a.time < b.time ? -1 : 1)).filter((m) => {
      const k = m.time + m.position
      if (seen.has(k)) return false
      seen.add(k)
      return true
    }))
    const live = picks.find((p) => p.status === 'open')
    if (live) {
      candles.createPriceLine({ price: live.stop, color: css('--down'), lineStyle: LineStyle.Dashed, title: 'stop' })
      candles.createPriceLine({ price: live.target, color: css('--up'), lineStyle: LineStyle.Dashed, title: 'target' })
      candles.createPriceLine({ price: live.entry, color: css('--gold'), lineStyle: LineStyle.Dotted, title: 'entry' })
    }
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [bars, signals, picks, height])
  return <div ref={ref} className="chart" role="img" aria-label="Candlestick chart with moving averages, patterns and picks" />
}

export function LineChart({ series, height = 220, zero = false }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!ref.current || !series?.length) return
    const chart = baseChart(ref.current, height)
    series.forEach((s, i) => {
      const line = chart.addLineSeries({ color: s.color || css(`--c${i + 1}`), lineWidth: 2, priceLineVisible: false })
      line.setData(s.data)
      if (zero && i === 0) line.createPriceLine({ price: 0, color: css('--line'), lineStyle: LineStyle.Dashed })
      if (s.bands) s.bands.forEach((b) => line.createPriceLine({ price: b.v, color: css(b.c), lineStyle: LineStyle.Dotted, title: b.t }))
    })
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [series, height, zero])
  return <div ref={ref} className="chart" role="img" aria-label={series?.map((s) => s.name).join(', ')} />
}
