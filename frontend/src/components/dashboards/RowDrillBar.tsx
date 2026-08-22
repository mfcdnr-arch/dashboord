import { useEffect, useState } from 'react'
import { pageRowRank, type RowRank } from '../../api'
import { fmtNumber } from '../../lib/format'

/**
 * Полоса разбора СТРОКИ: куда человек провалился и как эта строка выглядит на
 * фоне остальных.
 *
 * Клик по строке таблицы (или по столбцу графика) фильтрует всю страницу — но
 * одной цифры мало: вопрос, ради которого в строку и проваливаются, звучит как
 * «это много или мало по сравнению с другими». Здесь ответ: место по главным
 * показателям страницы, доля от общего итога и кто впереди.
 *
 * Показатели берутся из САМОЙ страницы (её датасет и самые ходовые поля) — см.
 * backend `_rowrank.py`. Иначе разбор говорил бы об одном, а страница о другом.
 */
export function RowDrillBar(
  { pageId, row, from, to, onClear }:
  { pageId: string | null; row: string | null; from: string; to: string; onClear: () => void },
) {
  const [rank, setRank] = useState<RowRank | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!pageId || !row) { setRank(null); return }
    let cancelled = false
    setRank(null); setFailed(false)
    pageRowRank(pageId, row, from, to)
      .then((r) => { if (!cancelled) setRank(r) })
      // Разбор — дополнение к странице, а не её условие: если он не посчитался,
      // строка всё равно остаётся отфильтрованной, и кнопка «ко всем строкам»
      // обязана работать.
      .catch(() => { if (!cancelled) setFailed(true) })
    return () => { cancelled = true }
  }, [pageId, row, from, to])

  if (!row) return null

  const single = rank !== null && rank.rows_total <= 1
  return (
    <div data-export-hide style={{
      display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
      background: 'var(--accent-weak-bg)', border: '1px solid var(--accent)',
      borderRadius: 10, padding: '7px 12px', margin: '0 0 12px', fontSize: 12.5,
      color: 'var(--text-2)',
    }}>
      <span style={{ fontWeight: 600, color: 'var(--accent)' }}>📍 {row}</span>
      <span style={{ color: 'var(--text-muted)' }}>вся страница показана по этой строке</span>

      {rank === null && !failed && <span style={{ color: 'var(--text-faint)' }}>считаем место среди строк…</span>}
      {failed && <span style={{ color: 'var(--text-faint)' }}>разбор по строкам недоступен</span>}
      {single && (
        <span style={{ color: 'var(--text-faint)' }}>
          в этой форме одна строка — сравнивать не с чем
        </span>
      )}
      {rank !== null && !single && rank.metrics.length === 0 && (
        <span style={{ color: 'var(--text-faint)' }}>у показателей страницы нет значения по этой строке</span>
      )}
      {rank !== null && !single && rank.metrics.map((m) => (
        <span key={m.field} title={`${m.name}: ${fmtNumber(m.value)} из ${fmtNumber(m.total)} по всем строкам`}
          style={{ display: 'inline-flex', gap: 5, alignItems: 'center' }}>
          <b style={{ color: m.rank === 1 ? 'var(--success)' : 'var(--text)' }}>
            {m.rank}-е из {m.rows}
          </b>
          <span style={{ color: 'var(--text-muted)' }}>
            по «{shortName(m.name)}»{m.share !== null ? ` · ${m.share.toFixed(1)} % от итога` : ''}
            {m.rank > 1 ? ` · впереди «${m.leader}»` : ''}
          </span>
        </span>
      ))}

      <button type="button" onClick={onClear}
        title="Снять фильтр по строке и вернуться ко всем строкам"
        style={{
          marginLeft: 'auto', height: 26, padding: '0 10px', borderWidth: 1, borderStyle: 'solid',
          borderColor: 'var(--accent)', borderRadius: 8, background: 'var(--surface)',
          color: 'var(--accent)', fontSize: 12.5, cursor: 'pointer', whiteSpace: 'nowrap',
        }}>← ко всем строкам</button>
    </div>
  )
}

/** Имена госформ длиной под сотню знаков в строку не помещаются. */
function shortName(name: string): string {
  const head = name.split('·')[0].trim()
  return head.length > 46 ? `${head.slice(0, 46)}…` : head
}
