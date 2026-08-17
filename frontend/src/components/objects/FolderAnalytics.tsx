import { useEffect, useState } from 'react'
import { getFolderAnalytics, type FolderAnalytics as Data } from '../../api'
import { fmtNumber } from '../../lib/format'

const ru = (iso?: string | null) => (iso ? iso.split('-').reverse().join('.') : '—')

// Аналитика по папке (п. 8 списка заказчика). Папка — это одна форма, которая
// приходит раз за разом, и вопросы по ней всегда одни и те же:
//   ① что в цифрах, ② можно ли им верить, ③ что уже построено, ④ как на фоне
//   других объектов.
// Экран отвечает ровно на эти четыре и ничего не считает заново: значения
// берутся тем же путём, что у виджетов, ритм — той же функцией, что шлёт
// уведомления о пропущенном отчёте.
export default function FolderAnalytics(
  { objectId, folderId, onOpenDashboard }:
  { objectId: string; folderId: string; onOpenDashboard?: (id: string) => void },
) {
  const [d, setD] = useState<Data | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    setD(null); setErr(null)
    getFolderAnalytics(objectId, folderId).then(setD).catch((e) => setErr((e as Error).message))
  }, [objectId, folderId])

  if (err) return <div style={errBox}>{err}</div>
  if (!d) return <div style={muted}>Загрузка…</div>

  const cov = d.coverage
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {/* ② Состояние данных — идёт первым: пока непонятно, можно ли верить
          цифрам, смотреть на сами цифры рано. */}
      <Block title="Состояние данных">
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
          <Stat t="Отчётов" v={d.data.periods} />
          <Stat t="Файлов" v={d.documents.total} />
          <Stat t="Выпущено" v={d.documents.released} />
          {d.documents.not_released > 0 && (
            <Stat t="Без данных" v={d.documents.not_released} warn />
          )}
        </div>
        <div style={muted}>
          Период данных: {ru(d.data.first_period)} — {ru(d.data.last_period)}
          {d.data.cadence_days
            ? ` · форма приходит раз в ${d.data.cadence_days} дн.`
            : ' · ритм пока не определён (нужно не меньше четырёх отчётов)'}
        </div>
        {d.data.issues.map((i) => (
          <div key={i.kind} style={i.kind === 'no_data' ? noteBox : warnBox}>{i.message}</div>
        ))}
        {d.data.missing_periods.length > 0 && (
          <div style={{ ...muted, marginTop: 6 }}>
            Не хватает отчётов за: {d.data.missing_periods.map(ru).join(', ')}
          </div>
        )}
        {d.documents.waiting.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Файлы без выпущенных данных</div>
            {d.documents.waiting.map((w) => (
              <div key={w.id} style={{ fontSize: 12, color: 'var(--text-2)' }}>
                {w.filename} · отчёт за {ru(w.period)}
                {w.status === 'failed' && <span style={{ color: 'var(--danger)' }}> · не распознан</span>}
              </div>
            ))}
          </div>
        )}
      </Block>

      {/* ① Свод показателей */}
      <Block title={`Показатели папки (${d.indicators.length})`}>
        {d.indicators.length === 0 ? <div style={muted}>Данных пока нет.</div> : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
              <thead>
                <tr>
                  <th style={th}>Показатель</th>
                  <th style={{ ...th, textAlign: 'right' }}>Значение</th>
                  <th style={{ ...th, textAlign: 'right' }}>К прошлому отчёту</th>
                  <th style={th}>На дашборде</th>
                </tr>
              </thead>
              <tbody>
                {d.indicators.map((i) => {
                  const shown = !cov.missing_fields.some((m) => m.field === i.field)
                  return (
                    <tr key={i.dataset_code + i.field}>
                      <td style={td} title={i.field}>{i.name}</td>
                      <td style={{ ...td, textAlign: 'right', fontWeight: 600 }}>
                        {i.value === null ? '—' : fmtNumber(i.value)}{i.unit ? ` ${i.unit}` : ''}
                      </td>
                      <td style={{ ...td, textAlign: 'right',
                        color: i.delta == null ? 'var(--text-faint)'
                          : i.delta > 0 ? 'var(--success)' : i.delta < 0 ? 'var(--danger)' : undefined }}>
                        {i.delta == null ? '—'
                          : `${i.delta > 0 ? '▲ +' : i.delta < 0 ? '▼ ' : ''}${fmtNumber(i.delta)}`}
                        {i.delta_pct != null && ` (${i.delta_pct > 0 ? '+' : ''}${fmtNumber(i.delta_pct)}%)`}
                      </td>
                      <td style={{ ...td, color: shown ? 'var(--success)' : 'var(--warn)' }}>
                        {shown ? '✓ есть' : 'нет'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Block>

      {/* ③ Что построено, а что нет */}
      <Block title="Что построено по этим данным">
        <div style={{ marginBottom: 8 }}>
          {cov.dashboards.length === 0 ? (
            <div style={noteBox}>
              Дашбордов по этой папке пока нет. Собрать можно мастером в карточке объекта —
              он предложит состав по имеющимся данным.
            </div>
          ) : cov.dashboards.map((db) => (
            <div key={db.id} style={{ fontSize: 13, marginBottom: 3 }}>
              <button style={linkBtn} onClick={() => onOpenDashboard?.(db.id)}>{db.name}</button>
              <span style={muted}> · виджетов {db.widgets} · {
                db.publication_status === 'published' ? 'опубликован'
                  : db.publication_status === 'review' ? 'на проверке' : 'черновик'}</span>
            </div>
          ))}
        </div>
        <div style={muted}>
          Показателей на дашбордах: {cov.shown_fields} из {cov.total_fields}
        </div>
        {cov.missing_fields.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--warn)', marginBottom: 4 }}>
              Не показаны нигде
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {cov.missing_fields.map((m) => (
                <span key={m.field} style={warnChip} title={m.field}>{m.name}</span>
              ))}
            </div>
          </div>
        )}
      </Block>

      {/* ④ Сравнение объектов. Показываем только когда есть с кем сравнивать —
          «сравнение» из одной строки вводит в заблуждение. */}
      {d.objects_compare.objects.length > 1 && (
        <Block title="Сравнение с другими объектами">
          <div style={{ ...muted, marginBottom: 6 }}>
            Сопоставление по названиям показателей: коды граф у каждого объекта свои.
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  <th style={{ ...th, position: 'sticky', left: 0, background: 'var(--surface-2)' }}>Объект</th>
                  {d.objects_compare.fields.map((f) => (
                    <th key={f} style={{ ...th, textAlign: 'right', maxWidth: 220 }} title={f}>{f}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.objects_compare.objects.map((o) => (
                  <tr key={o.object_id} style={o.is_current ? { background: 'var(--accent-weak-bg)' } : undefined}>
                    <td style={{ ...td, position: 'sticky', left: 0, background: o.is_current ? 'var(--accent-weak-bg)' : 'var(--surface)',
                      fontWeight: o.is_current ? 600 : 400 }}>{o.name}</td>
                    {d.objects_compare.fields.map((f) => (
                      <td key={f} style={{ ...td, textAlign: 'right' }}>
                        {o.values[f] == null ? '—' : fmtNumber(o.values[f] as number)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Block>
      )}
    </div>
  )
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  )
}

function Stat({ t, v, warn }: { t: string; v: number; warn?: boolean }) {
  return (
    <div style={{ border: '1px solid var(--border-faint)', borderRadius: 10, padding: '8px 14px', minWidth: 90 }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: warn ? 'var(--warn)' : 'var(--accent)' }}>{v}</div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t}</div>
    </div>
  )
}

const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 13 }
const linkBtn: React.CSSProperties = {
  border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 13, padding: 0,
}
const th: React.CSSProperties = {
  border: '1px solid var(--border-faint)', padding: '6px 10px', background: 'var(--surface-2)',
  textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600,
}
const td: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '6px 10px' }
const warnChip: React.CSSProperties = {
  fontSize: 12, padding: '2px 9px', borderRadius: 10, background: 'var(--warn-bg)', color: 'var(--warn)',
}
const warnBox: React.CSSProperties = {
  background: 'var(--warn-bg)', color: 'var(--warn)', fontSize: 13, padding: '8px 10px',
  borderRadius: 8, marginTop: 8,
}
const noteBox: React.CSSProperties = {
  background: 'var(--surface-2)', color: 'var(--text-2)', fontSize: 13, padding: '8px 10px',
  borderRadius: 8, marginTop: 8,
}
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8,
}
