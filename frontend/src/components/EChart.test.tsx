// Цвета осей и подписей на графиках должны приходить ИЗ ТЕМЫ.
//
// Почему это стоит теста: ECharts не наследует textStyle для подписей значений
// и делений осей — у них свои умолчания (#333 и #6E7079). В светлой теме это
// незаметно, а в тёмной числа над столбиками сливаются с фоном (контраст был
// около 1.5:1). Правило легко потерять при следующей правке обёртки, а увидеть
// потерю можно только глазами и только в тёмной теме.
import { describe, expect, it, beforeEach } from 'vitest'
import { withThemedText } from './EChart'

function setTokens() {
  const r = document.documentElement
  r.style.setProperty('--text-muted', '#b3a498')
  r.style.setProperty('--text-2', '#ddd0c5')
  r.style.setProperty('--border', '#46362a')
  r.style.setProperty('--border-faint', '#372a21')
}

describe('withThemedText', () => {
  beforeEach(setTokens)

  it('красит подписи значений и деления осей цветом темы', () => {
    const out = withThemedText({
      xAxis: { type: 'category', data: ['а', 'б'] },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data: [1, 2], label: { show: true } }],
    } as never) as never as Record<string, never>

    const x = out.xAxis as never as Record<string, Record<string, string>>
    const s = (out.series as never as Record<string, Record<string, string>>[])[0]
    expect(x.axisLabel.color).toBe('#b3a498')
    expect(s.label.color).toBe('#ddd0c5')
  })

  it('НЕ трогает то, что задано явно: у спидометра и тепловой карты свои цвета', () => {
    const out = withThemedText({
      yAxis: { type: 'value', axisLabel: { color: '#ff0000' } },
      series: [{ type: 'gauge', label: { color: '#00ff00' }, axisLine: { lineStyle: { color: [[1, '#123456']] } } }],
    } as never) as never as Record<string, never>

    const y = out.yAxis as never as Record<string, Record<string, string>>
    const s = (out.series as never as Record<string, Record<string, unknown>>[])[0]
    expect(y.axisLabel.color).toBe('#ff0000')
    expect((s.label as Record<string, string>).color).toBe('#00ff00')
    expect(s.axisLine).toEqual({ lineStyle: { color: [[1, '#123456']] } })
  })

  it('ряд без подписи остаётся как был, а несколько осей обрабатываются все', () => {
    const out = withThemedText({
      xAxis: [{ type: 'category' }, { type: 'category' }],
      series: [{ type: 'line', data: [1] }],
    } as never) as never as Record<string, never>

    const xs = out.xAxis as never as Record<string, Record<string, string>>[]
    const s = (out.series as never as Record<string, unknown>[])[0]
    expect(xs).toHaveLength(2)
    expect(xs[1].axisLabel.color).toBe('#b3a498')
    expect(s.label).toBeUndefined()
  })
})
