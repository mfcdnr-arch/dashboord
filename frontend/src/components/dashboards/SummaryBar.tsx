import { useEffect, useState } from 'react'
import { pageSummary, type PageSummary } from '../../api'
import { fmtNumber } from '../../lib/format'

/**
 * Строка «как дела» над виджетами.
 *
 * Дашборд отвечает на «сколько» — числами. Руководитель приходит с другим
 * вопросом: «что изменилось и на что смотреть», и до сих пор ответ он собирал
 * глазами по полутора десяткам карточек.
 *
 * Считается по тем же данным, что показывают виджеты (последний отчёт против
 * предыдущего), поэтому разойтись с карточками нечему. Если отчёт всего один,
 * строка молчит: придумывать динамику там, где сравнивать не с чем, нельзя.
 */
export function SummaryBar({ pageId }: { pageId: string | null }) {
  const [s, setS] = useState<PageSummary | null>(null)

  useEffect(() => {
    if (!pageId) { setS(null); return }
    let cancelled = false
    setS(null)
    // Резюме — дополнение к странице: его сбой не должен ничего ломать.
    pageSummary(pageId).then((r) => { if (!cancelled) setS(r) }).catch(() => {})
    return () => { cancelled = true }
  }, [pageId])

  if (!s || s.single_report || (!s.grew && !s.fell && !s.same)) return null
  const ru = (d?: string | null) => (d && /^\d{4}-\d{2}-\d{2}$/.test(d) ? d.split('-').reverse().join('.') : '')
  const pct = (v: number | null) => (v == null ? '' : ` ${v > 0 ? '+' : ''}${fmtNumber(v)} %`)

  return (
    <div data-export-hide style={{
      display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
      border: '1px solid var(--border-faint)', borderLeft: '3px solid var(--accent)',
      borderRadius: 10, padding: '7px 12px', margin: '0 0 12px',
      background: 'var(--surface)', fontSize: 12.5, color: 'var(--text-2)',
    }}>
      <span style={{ fontWeight: 700, color: 'var(--accent)' }}>Как дела</span>
      <span title={`Отчёт за ${ru(s.period)} против ${ru(s.prev_period)}`}>
        к отчёту за {ru(s.prev_period)}: выросли <b style={{ color: 'var(--success)' }}>{s.grew}</b>,
        просели <b style={{ color: s.fell ? 'var(--danger)' : 'inherit' }}>{s.fell}</b>
        {s.same ? <>, без изменений <b>{s.same}</b></> : null}
      </span>
      {s.top.length > 0 && (
        <span style={{ color: 'var(--success)' }} title={s.top[0].full_name}>
          ↑ {s.top[0].name}{pct(s.top[0].delta_pct)}
        </span>
      )}
      {s.worst.length > 0 && (
        <span style={{ color: 'var(--danger)' }} title={s.worst[0].full_name}>
          ↓ {s.worst[0].name}{pct(s.worst[0].delta_pct)}
        </span>
      )}
      {(s.plans || []).slice(0, 2).map((p) => (
        <span key={p.name} style={{ color: p.pct >= 100 ? 'var(--success)' : 'var(--warn)' }}
          title="Выполнение плана по данным последнего отчёта">
          🎯 {p.name}: {fmtNumber(p.pct)} %
        </span>
      ))}
    </div>
  )
}
