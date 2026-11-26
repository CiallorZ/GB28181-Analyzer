/**
 * 图表配色：直接从 CSS 变量读，明暗主题切换后重绘即可自动跟随。
 * 以前各视图把 #18212d 之类的深色写死在 option 里，浅色主题下
 * 文字与网格仍是深色，读不出来。
 */
export function chartPalette() {
  const cs = getComputedStyle(document.documentElement)
  const v = (name) => cs.getPropertyValue(name).trim()
  return {
    text: v('--text-2'),
    dim: v('--text-3'),
    faint: v('--text-4'),
    line: v('--line'),
    line2: v('--line-2'),
    surface: v('--surface'),
    tipBg: v('--surface-2'),
    tipBorder: v('--line-2'),
    tipText: v('--text'),
    brand: v('--chart-primary') || v('--brand'),
    ds: v('--chart-blue'),
    ai: v('--status-ai'),
    ok: v('--ok'),
    warn: v('--warning'),
    crit: v('--critical'),
    info: v('--info')
  }
}

export function chartBase(extra = {}) {
  const c = chartPalette()
  return {
    animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    backgroundColor: 'transparent',
    textStyle: { color: c.text, fontSize: 11 },
    tooltip: {
      backgroundColor: c.tipBg,
      borderColor: c.tipBorder,
      borderWidth: 1,
      textStyle: { color: c.tipText, fontSize: 11.5 },
      extraCssText: 'border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.18)'
    },
    ...extra
  }
}

export function seriesPalette() {
  const c = chartPalette()
  return [c.brand, c.info, c.ok, c.warn, c.ai, c.ds, c.dim]
}
