import type { KeyKpi } from '../api'

/**
 * Изменение показателя к прошлому отчёту — рядом с числом на «Главной».
 *
 * Один компонент на обе «Главных» (админскую и пользовательскую): подпись
 * «▲ 3,50 %» и «▲ 1,18 п.п.» должна читаться одинаково, где бы ни стояла.
 *
 * Единица считается на сервере: у процентных показателей изменение приходит в
 * ПУНКТАХ (`delta_is_pp`), у остальных — обычным относительным приростом.
 * «Доля выросла на 3,28 %» без этого различия означало бы то ли «стала
 * 40,46 %», то ли «выросла на 3,28 пункта».
 */
export default function KpiDelta({ kpi, size = 12.5 }: { kpi: KeyKpi; size?: number }) {
  const d = kpi.delta
  if (d == null) return null
  const zero = Math.abs(d) < 0.005
  const color = zero ? 'var(--text-muted)' : d > 0 ? 'var(--success)' : 'var(--danger)'
  const sign = zero ? '=' : d > 0 ? '▲' : '▼'
  const title = kpi.prev_period
    ? `К отчёту за ${kpi.prev_period.split('-').reverse().join('.')}`
    : 'К прошлому отчёту'
  return (
    <span style={{ fontSize: size, fontWeight: 600, color, whiteSpace: 'nowrap' }} title={title}>
      {sign} {Math.abs(d).toFixed(2)} {kpi.delta_is_pp ? 'п.п.' : '%'}
    </span>
  )
}
