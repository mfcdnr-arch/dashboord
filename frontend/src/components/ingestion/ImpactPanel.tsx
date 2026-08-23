import { useState } from 'react'
import type { ImpactWidget, ReleaseImpact } from '../../api'
import { fmtNumber } from '../../lib/format'
import { distinctLabels, elideMiddle } from '../../lib/text'

const ru = (iso?: string | null) => (iso ? iso.slice(0, 10).split('-').reverse().join('.') : '—')

// «Что изменится на дашбордах» — предпросмотр последствий выпуска (п. 15).
//
// До этого перед кнопкой «Выпустить» человек видел только замечания к самим
// данным. Что от выпуска изменится на экранах у руководителей, не показывал
// никто: выпуск делался вслепую, а последствия обнаруживались уже на дашборде.
//
// Блок РАСКРЫТ по умолчанию только когда есть риск (исчезла графа или строка).
// Молчание, когда всё в порядке, — часть смысла: раскрывай его всегда, и он
// станет фоном, а настоящее предупреждение пройдёт мимо.
export default function ImpactPanel({ impact, loading }: { impact: ReleaseImpact | null; loading: boolean }) {
  const risky = !!impact && (impact.widgets_at_risk > 0 || impact.rows.removed.length > 0)
  const [open, setOpen] = useState(false)
  const shown = open || risky

  if (loading && !impact) return <div style={muted}>Считаем, что изменится на дашбордах…</div>
  if (!impact) return null

  const changed = impact.fields.filter((f) => f.delta !== null && f.delta !== 0)
  const affected = impact.widgets.filter((w) => w.changes)

  return (
    <div style={{
      borderWidth: 1, borderStyle: 'solid',
      borderColor: risky ? 'var(--alert-danger)' : 'var(--border)',
      background: risky ? 'var(--alert-danger-bg)' : 'var(--surface-2)',
      borderRadius: 8, padding: '8px 10px', margin: '0 0 12px', fontSize: 12.5,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 600 }}>📊 Что изменится на дашбордах</span>
        <span style={{ color: 'var(--text-2)' }}>
          {impact.first_release
            ? 'это первый выпуск этих данных'
            : `виджетов затронуто: ${affected.length}`}
          {impact.widgets_at_risk > 0 && (
            <b style={{ color: 'var(--alert-danger)' }}> · останутся без данных: {impact.widgets_at_risk}</b>
          )}
        </span>
        <button type="button" onClick={() => setOpen((v) => !v)} style={linkBtn}>
          {shown ? 'свернуть' : 'посмотреть'}
        </button>
      </div>

      {shown && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {/* ── Сначала то, что может сломаться ───────────────────────────── */}
          {impact.lost_fields.length > 0 && (
            <Note tone="danger">
              <b>В этом файле нет граф, на которые смотрят виджеты.</b> После выпуска они начнут
              показывать «нет данных»:{' '}
              {impact.fields.filter((f) => f.gone).map((f) => `«${f.name}»`).join(', ')}.
              {' '}Проверьте разметку — возможно, столбец не отмечен или переименован.
            </Note>
          )}
          {impact.rows.removed.length > 0 && (
            <Note tone="danger">
              <b>Строки, которые были в прошлом отчёте, в этом файле отсутствуют:</b>{' '}
              {impact.rows.removed.map((r) => `«${r}»`).join(', ')}. Их значения исчезнут с дашбордов.
            </Note>
          )}

          {/* ── Попадут ли данные на экраны вообще ────────────────────────── */}
          {!impact.becomes_current && (
            <Note tone="warn">
              Отчёт за {ru(impact.period)} <b>не попадёт на дашборды</b>: там уже есть более свежий
              отчёт за {ru(impact.latest_period)}, а виджеты показывают последний. Данные сохранятся
              и будут видны в «Динамике» и на страницах-срезах.
            </Note>
          )}
          {impact.replaces && (
            <Note tone="warn">
              За {ru(impact.replaces.period)} выпуск <b>уже есть</b> — этот его заместит.
              Цифры ниже сравниваются именно с ним.
            </Note>
          )}

          {/* ── Что станет с цифрами ──────────────────────────────────────── */}
          {changed.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ borderCollapse: 'collapse', fontSize: 12.5, width: '100%' }}>
                <thead>
                  <tr>
                    <th style={th}>Показатель</th>
                    <th style={{ ...th, textAlign: 'right' }}>Сейчас</th>
                    <th style={{ ...th, textAlign: 'right' }}>Станет</th>
                    <th style={{ ...th, textAlign: 'right' }}>Изменение</th>
                  </tr>
                </thead>
                <tbody>
                  {changed.map((f) => (
                    <tr key={f.field}>
                      <td style={td} title={f.how === 'avg'
                        ? 'Доли усредняются по строкам — так же, как на карточке показателя'
                        : 'Значения по строкам складываются — так же, как на карточке показателя'}>
                        {f.name}{f.how === 'avg' ? ' ⌀' : ''}
                      </td>
                      <td style={{ ...td, textAlign: 'right' }}>{f.current === null ? '—' : fmtNumber(f.current)}</td>
                      <td style={{ ...td, textAlign: 'right', fontWeight: 600 }}>
                        {f.next === null ? '—' : fmtNumber(f.next)}
                      </td>
                      <td style={{ ...td, textAlign: 'right',
                        color: (f.delta ?? 0) > 0 ? 'var(--success)' : 'var(--danger)' }}>
                        {(f.delta ?? 0) > 0 ? '▲ +' : '▼ '}{fmtNumber(f.delta ?? 0)}
                        {f.delta_pct != null && ` (${f.delta_pct > 0 ? '+' : ''}${fmtNumber(f.delta_pct)}%)`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {impact.fields.some((f) => f.is_new) && (
            <div style={muted}>
              Новые графы (на дашбордах их пока никто не показывает):{' '}
              {impact.fields.filter((f) => f.is_new).map((f) => `«${f.name}»`).join(', ')}
            </div>
          )}

          {/* ── Где это увидят ────────────────────────────────────────────── */}
          <WhereSeen widgets={impact.widgets} />

          <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>
            Цифры считаются той же свёрткой, что и карточка показателя, — то, что обещано здесь,
            и появится на дашборде. Выпуск обратим: его можно отменить кнопкой «Отменить выпуск».
          </div>
        </div>
      )}
    </div>
  )
}

/** «Где это увидят», сгруппировано по дашборду и странице.
 *
 *  🔴 Плоский список здесь не годится: у заказчика 29 виджетов на одном
 *  дашборде, имя дашборда повторялось в каждой строке, а имена виджетов —
 *  длиной с имя госформы. Блок занимал весь экран и отодвигал кнопку выпуска
 *  за сгиб — то есть мешал ровно тому, ради чего его открыли.
 *
 *  Поэтому: имя дашборда один раз заголовком; у виджетов внутри группы
 *  отсекается общая часть имени (`distinctLabels` — тот же приём, что в
 *  легенде графиков); а когда НИЧЕГО не сломается, список свёрнут до счётчика
 *  — там важно число, а не перечисление. Виджеты под риском показываются
 *  всегда и первыми: ради них блок и существует. */
function WhereSeen({ widgets }: { widgets: ImpactWidget[] }) {
  const [all, setAll] = useState(false)
  if (widgets.length === 0) {
    return (
      <div style={muted}>
        На эти данные пока не смотрит ни один виджет — выпуск ничего не изменит на дашбордах.
      </div>
    )
  }
  const risky = widgets.filter((w) => w.at_risk)
  const rest = widgets.filter((w) => !w.at_risk)
  const shown = all ? rest : []

  const groups = new Map<string, ImpactWidget[]>()
  for (const w of [...risky, ...shown]) {
    const key = `${w.dashboard}\u0000${w.page || ''}`
    const arr = groups.get(key)
    if (arr) arr.push(w)
    else groups.set(key, [w])
  }

  return (
    <div>
      <div style={{ fontWeight: 600, marginBottom: 3 }}>
        Где это увидят
        <span style={{ fontWeight: 400, color: 'var(--text-2)' }}> · виджетов: {widgets.length}</span>
      </div>
      {[...groups.entries()].map(([key, ws]) => {
        const [dash, page] = key.split('\u0000')
        const short = distinctLabels(ws.map((w) => w.name))
        return (
          <div key={key} style={{ marginBottom: 4 }}>
            <div style={{ fontSize: 12 }}>
              <b>{dash}</b>{page ? ` · ${page}` : ''}
              <span style={{ color: 'var(--text-faint)' }}> — {ws.length}</span>
            </div>
            {ws.map((w, i) => (
              <div key={w.widget_id} style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.5, paddingLeft: 12 }}>
                {w.at_risk ? '🔴 ' : w.changes ? '• ' : '◦ '}
                <span title={w.name}>{elideMiddle(short[i] || w.name, 60)}</span>
                {!w.published && <span style={{ color: 'var(--text-faint)' }}> (не опубликован)</span>}
                {w.at_risk && <span style={{ color: 'var(--alert-danger)' }}> — останется без данных</span>}
                {w.note && <span style={{ color: 'var(--text-faint)' }}> — {w.note}</span>}
                {w.current !== null && w.next !== null && (
                  <span> — {fmtNumber(w.current)} → <b>{fmtNumber(w.next)}</b></span>
                )}
              </div>
            ))}
          </div>
        )
      })}
      {rest.length > 0 && (
        <button type="button" onClick={() => setAll((v) => !v)} style={linkBtn}>
          {all ? 'свернуть список' : `показать все ${rest.length}`}
        </button>
      )}
    </div>
  )
}


function Note({ tone, children }: { tone: 'danger' | 'warn'; children: React.ReactNode }) {
  return (
    <div style={{
      padding: '6px 8px', borderRadius: 6, lineHeight: 1.45,
      background: tone === 'danger' ? 'var(--alert-danger-bg)' : 'var(--alert-warn-bg)',
      color: tone === 'danger' ? 'var(--alert-danger)' : 'var(--alert-warn)',
    }}>{children}</div>
  )
}

const muted: React.CSSProperties = { fontSize: 12, color: 'var(--text-2)' }
const linkBtn: React.CSSProperties = {
  background: 'none', border: 'none', padding: 0, cursor: 'pointer',
  color: 'var(--accent)', textDecoration: 'underline', fontSize: 12,
}
const th: React.CSSProperties = {
  textAlign: 'left', padding: '3px 6px', borderBottom: '1px solid var(--border)',
  fontSize: 11.5, color: 'var(--text-2)', fontWeight: 600,
}
const td: React.CSSProperties = { padding: '3px 6px', borderBottom: '1px solid var(--border-faint)' }
