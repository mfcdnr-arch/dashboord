// «Паспорт цифры» (п. 17 списка предложений): откуда взялось это число.
//
// На дашборде видно значение, а вопросов у человека три и все про
// происхождение: как менялось по неделям, из какого файла пришло и кто
// выпустил. Раньше ответ собирался по трём разным экранам — «Динамика»,
// аналитика папки и журнал аудита.
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { widgetPassport, type PassportRow } from '../../api'
import { fmtNumber } from '../../lib/format'
import { dialog, errBox, muted, overlay } from './shared'

const ruDate = (iso?: string | null): string =>
  (iso && /^\d{4}-\d{2}-\d{2}/.test(iso) ? iso.slice(0, 10).split('-').reverse().join('.') : '—')

const ruDateTime = (iso?: string | null): string =>
  (iso ? new Date(iso).toLocaleString('ru-RU') : '—')

export default function PassportDialog(
  { widgetId, row, onClose }: { widgetId: string; row?: string; onClose: () => void },
) {
  const [data, setData] = useState<{ field_name: string; row: string | null; history: PassportRow[] } | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    widgetPassport(widgetId, row).then(setData).catch((e) => setErr((e as Error).message))
  }, [widgetId, row])

  // Портал в body — как у остальных окон раздела: карточка виджета обрезает
  // содержимое (`overflow: hidden`), и окно внутри неё срезалось бы вместе с
  // крестиком.
  return createPortal(
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 860 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>📇 Паспорт цифры</h3>
          <button style={{ marginLeft: 'auto', border: 'none', background: 'none', cursor: 'pointer', fontSize: 16 }}
            onClick={onClose} title="Закрыть">✕</button>
        </div>

        {err && <div style={errBox}>{err}</div>}
        {!data && !err && <div style={muted}>Загрузка…</div>}

        {data && (
          <>
            <div style={{ fontSize: 13, marginBottom: 4 }}>{data.field_name}</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
              {data.row
                ? `по строке «${data.row}»`
                : 'по всем строкам формы, доступным вам'}
            </div>
            {data.history.length === 0 ? (
              <div style={muted}>По этой графе выпущенных данных пока нет.</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
                  <thead>
                    <tr>
                      {['Отчёт', 'Значение', 'Изменение', 'Из какого файла', 'Кто выпустил', 'Когда'].map((h) => (
                        <th key={h} style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border)',
                          fontSize: 11.5, color: 'var(--text-muted)', fontWeight: 600, whiteSpace: 'nowrap' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.history.map((h, i) => (
                      // Замещённый выпуск приглушён, но НЕ спрятан: если цифра
                      // за неделю менялась, человек должен видеть, что её
                      // заместили, — иначе это выглядит ошибкой системы.
                      <tr key={i} style={{ opacity: h.superseded ? 0.55 : 1 }}>
                        <td style={cell}>
                          {ruDate(h.period)}
                          {h.superseded && (
                            <span style={{ fontSize: 10.5, color: 'var(--warn)', marginLeft: 6 }}
                              title="Этот выпуск заместили повторным за ту же дату — на дашборде показан следующий">
                              замещён
                            </span>
                          )}
                        </td>
                        <td style={{ ...cell, fontWeight: 600, whiteSpace: 'nowrap' }}>
                          {fmtNumber(h.value)}
                          {h.aggregate === 'avg' && (
                            <span style={{ fontSize: 10.5, color: 'var(--text-muted)', marginLeft: 4 }}
                              title={`Доля усредняется по ${h.rows_used} строкам: складывать проценты нельзя`}>⌀</span>
                          )}
                        </td>
                        <td style={{ ...cell, whiteSpace: 'nowrap',
                          color: h.delta == null ? 'var(--text-faint)'
                            : h.delta > 0 ? 'var(--success)' : h.delta < 0 ? 'var(--danger)' : 'var(--text-muted)' }}>
                          {h.delta == null ? '—'
                            : `${h.delta > 0 ? '+' : ''}${fmtNumber(h.delta)}${
                              h.delta_pct != null ? ` (${h.delta_pct > 0 ? '+' : ''}${fmtNumber(h.delta_pct)} %)` : ''}`}
                        </td>
                        <td style={{ ...cell, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap' }} title={h.document || ''}>{h.document || '—'}</td>
                        <td style={cell}>
                          {h.released_by || '—'}
                          {h.auto_released && (
                            <span style={{ fontSize: 10.5, color: 'var(--text-muted)', marginLeft: 4 }}
                              title="Выпуск сделан автоматически: форма совпала с прошлым отчётом">⚙</span>
                          )}
                        </td>
                        <td style={{ ...cell, whiteSpace: 'nowrap', color: 'var(--text-muted)', fontSize: 12 }}>
                          {ruDateTime(h.released_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>,
    document.body,
  )
}

const cell: React.CSSProperties = { padding: '6px 8px', borderBottom: '1px solid var(--border-faint)' }
