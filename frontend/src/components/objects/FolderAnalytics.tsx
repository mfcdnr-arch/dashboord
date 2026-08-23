import { useEffect, useState } from 'react'
import {
  createWidget, getDashboard, getFolderAnalytics,
  type DashPage, type FolderAnalytics as Data,
} from '../../api'
import { fmtNumber } from '../../lib/format'
import ArrivalCalendar from './ArrivalCalendar'

const ru = (iso?: string | null) => (iso ? iso.split('-').reverse().join('.') : '—')

// Аналитика по папке (п. 8 списка заказчика). Папка — это одна форма, которая
// приходит раз за разом, и вопросы по ней всегда одни и те же:
//   ① что в цифрах, ② можно ли им верить, ③ что уже построено, ④ как на фоне
//   других объектов.
// Экран отвечает ровно на эти четыре и ничего не считает заново: значения
// берутся тем же путём, что у виджетов, ритм — той же функцией, что шлёт
// уведомления о пропущенном отчёте.
export default function FolderAnalytics(
  { objectId, folderId, canManage, onOpenDashboard }:
  { objectId: string; folderId: string; canManage?: boolean; onOpenDashboard?: (id: string) => void },
) {
  const [d, setD] = useState<Data | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)

  const load = () => {
    setErr(null)
    getFolderAnalytics(objectId, folderId).then(setD).catch((e) => setErr((e as Error).message))
  }
  useEffect(() => { setD(null); load() }, [objectId, folderId]) // eslint-disable-line react-hooks/exhaustive-deps

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

      {/* Календарь поступлений (п. 16). Стоит сразу после состояния данных и
          отвечает на тот же вопрос, что строка «не хватает отчётов за …»
          выше, — но глазами: за год пропуски видно полосой, а не списком дат. */}
      <Block title="Календарь поступлений">
        <ArrivalCalendar objectId={objectId} folderId={folderId} />
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
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--warn)' }}>Не показаны нигде</div>
              {/* Список забытых показателей сам по себе — тупик: он сообщает о
                  недостаче, а завести карточки предлагает вручную. Кнопка
                  делает то, ради чего человек сюда и смотрит. */}
              {canManage && cov.dashboards.length > 0 && (
                <button style={addBtn} onClick={() => setAddOpen(true)}>＋ Добавить на дашборд</button>
              )}
              {canManage && cov.dashboards.length === 0 && (
                <span style={muted}>дашборда по этой папке нет — соберите мастером в карточке объекта</span>
              )}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {cov.missing_fields.map((m) => (
                <span key={m.field} style={warnChip} title={m.field}>{m.name}</span>
              ))}
            </div>
          </div>
        )}
      </Block>

      {addOpen && (
        <AddMissingDialog
          dashboards={cov.dashboards}
          fields={cov.missing_fields}
          datasetCode={d.data.codes[0] || ''}
          onClose={() => setAddOpen(false)}
          onDone={() => { setAddOpen(false); load() }}
        />
      )}

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


// Добавление забытых показателей на дашборд этой папки.
//
// Выбор дашборда и страницы обязателен: карточку надо куда-то положить, а
// «положим на первый попавшийся» однажды удивит человека, у которого их
// несколько. По умолчанию не отмечено ничего — показателей бывает десяток, и
// десяток карточек разом превращает страницу в стену чисел.
function AddMissingDialog(
  { dashboards, fields, datasetCode, onClose, onDone }: {
    dashboards: { id: string; name: string }[]
    fields: { field: string; name: string }[]
    datasetCode: string
    onClose: () => void
    onDone: () => void
  },
) {
  const [dashId, setDashId] = useState(dashboards[0]?.id || '')
  const [pages, setPages] = useState<DashPage[] | null>(null)
  const [pageId, setPageId] = useState('')
  const [picked, setPicked] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!dashId) return
    setPages(null); setPageId('')
    getDashboard(dashId).then((r) => {
      setPages(r.pages)
      setPageId(r.pages[0]?.id || '')
    }).catch((e) => setErr((e as Error).message))
  }, [dashId])

  const chosen = fields.filter((f) => picked[f.field])

  async function add() {
    if (!pageId || chosen.length === 0) return
    setBusy(true); setErr(null)
    try {
      for (const f of chosen) {
        await createWidget(pageId, {
          name: f.name, widget_type: 'kpi',
          config: { dataset_code: datasetCode, value_field: f.field },
          // В конец страницы: место подберёт сетка, а поверх чужих виджетов
          // карточка не ляжет.
          position_x: 0, position_y: 999, width: 4, height: 5,
        })
      }
      onDone()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <div style={dlgOverlay} onClick={onClose}>
      <div style={dlg} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'baseline', marginBottom: 10 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Добавить показатели на дашборд</div>
          <button style={{ ...closeBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        {err && <div style={errBox}>{err}</div>}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          <label style={{ ...muted, display: 'flex', gap: 6, alignItems: 'center' }}>
            дашборд
            <select style={sel} value={dashId} onChange={(e) => setDashId(e.target.value)}>
              {dashboards.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </label>
          <label style={{ ...muted, display: 'flex', gap: 6, alignItems: 'center' }}>
            страница
            <select style={sel} value={pageId} onChange={(e) => setPageId(e.target.value)}
              disabled={!pages || pages.length === 0}>
              {(pages || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
        </div>
        {pages && pages.length === 0 && (
          <div style={{ ...muted, color: 'var(--warn)' }}>
            У дашборда нет ни одной страницы — сначала создайте её в разделе «Дашборды».
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 260, overflowY: 'auto' }}>
          {fields.map((f) => (
            <label key={f.field} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
              <input type="checkbox" checked={!!picked[f.field]}
                onChange={(e) => setPicked((c) => ({ ...c, [f.field]: e.target.checked }))} />
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}
                title={f.field}>{f.name}</span>
            </label>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 12 }}>
          <button style={{ ...addBtn, height: 34, opacity: chosen.length === 0 || !pageId || busy ? 0.5 : 1 }}
            disabled={chosen.length === 0 || !pageId || busy} onClick={add}>
            {busy ? 'Добавление…' : `Добавить (${chosen.length})`}
          </button>
          <span style={muted}>Карточками в конец выбранной страницы.</span>
        </div>
      </div>
    </div>
  )
}

const addBtn: React.CSSProperties = {
  height: 26, padding: '0 12px', border: 'none', borderRadius: 8,
  background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 12, cursor: 'pointer',
}
const dlgOverlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex',
  alignItems: 'center', justifyContent: 'center', zIndex: 70, padding: 20,
}
const dlg: React.CSSProperties = {
  background: 'var(--surface)', borderRadius: 14, padding: 20, width: 560, maxWidth: '94vw',
  maxHeight: '86vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
}
const sel: React.CSSProperties = {
  height: 30, padding: '0 8px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13,
}
const closeBtn: React.CSSProperties = {
  border: 'none', background: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--text-muted)',
}
