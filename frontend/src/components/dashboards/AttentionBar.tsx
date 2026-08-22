import { useEffect, useState } from 'react'
import { pageAttention, type PageAttention } from '../../api'

/**
 * Блок «На что посмотреть» — замечания к данным страницы.
 *
 * Проверки качества выпуска видел только модератор и только в момент нажатия
 * «Выпустить». Руководитель, открывающий дашборд неделю спустя, видел цифры и
 * ничего не знал о том, что строка совпала с прошлым отчётом посимвольно (то
 * есть данные могли не обновить) или что накопительный итог уменьшился.
 *
 * Правила — ТЕ ЖЕ, что у модератора (`ingestion/quality`), поэтому дашборд не
 * может сказать о данных иное, чем сказала очередь выпуска. Замечание — не
 * приговор данным: формулировки «проверьте», и блок сворачивается.
 */
export function AttentionBar({ pageId }: { pageId: string | null }) {
  const [data, setData] = useState<PageAttention | null>(null)
  const [open, setOpen] = useState(false)
  const [hidden, setHidden] = useState(false)

  useEffect(() => {
    if (!pageId) { setData(null); return }
    let cancelled = false
    setData(null); setHidden(false); setOpen(false)
    // Замечания — дополнение к странице, а не её условие: сбой проверки не
    // должен ни ломать дашборд, ни показывать человеку красную плашку об
    // ошибке, которую он не может исправить.
    pageAttention(pageId).then((r) => { if (!cancelled) setData(r) }).catch(() => {})
    return () => { cancelled = true }
  }, [pageId])

  const items = data?.items || []
  if (!items.length || hidden) return null
  const total = items.reduce((n, it) => n + it.warnings.length, 0)
  const ru = (d?: string | null) => (d && /^\d{4}-\d{2}-\d{2}$/.test(d) ? d.split('-').reverse().join('.') : (d || ''))

  return (
    <div data-export-hide style={{
      border: '1px solid var(--warn)', borderRadius: 10, padding: '7px 12px',
      margin: '0 0 12px', fontSize: 12.5, background: 'var(--surface-2)', color: 'var(--text-2)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 600, color: 'var(--warn)' }}>👀 На что посмотреть</span>
        <span>
          к данным есть {total === 1 ? 'замечание' : 'замечаний'}: <b>{total}</b>
          {items.length > 1 ? ` по ${items.length} формам` : ''}
        </span>
        <button type="button" onClick={() => setOpen((v) => !v)} style={linkBtn}>
          {open ? 'свернуть' : 'посмотреть'}
        </button>
        <button type="button" onClick={() => setHidden(true)} style={{ ...linkBtn, marginLeft: 'auto', color: 'var(--text-faint)' }}
          title="Скрыть до следующего открытия страницы. Замечания никуда не денутся — они считаются по данным.">
          ✕
        </button>
      </div>
      {open && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {items.map((it) => (
            <div key={it.dataset_code}>
              <div style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
                {it.dataset_name || it.dataset_code}
                {it.period ? ` · отчёт за ${ru(it.period)}` : ''}
                {it.previous_period ? ` · сравнение с ${it.previous_period}` : ''}
              </div>
              <ul style={{ margin: '2px 0 0', paddingLeft: 18 }}>
                {it.warnings.map((w, i) => <li key={w.code + i} style={{ lineHeight: 1.4 }}>{w.message}</li>)}
              </ul>
            </div>
          ))}
          <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>
            Это те же проверки, что видит модератор при выпуске данных: сверка последнего отчёта
            с предыдущим. Замечание не значит, что цифры неверны, — значит, что их стоит проверить.
          </div>
        </div>
      )}
    </div>
  )
}

const linkBtn: React.CSSProperties = {
  background: 'none', border: 'none', padding: 0, cursor: 'pointer',
  color: 'var(--accent)', fontSize: 12.5, textDecoration: 'underline dotted',
}
