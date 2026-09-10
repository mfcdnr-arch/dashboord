import { useEffect, useState } from 'react'
import { getLadder, type LadderStep } from '../../api/dashboards'
import { fmtNumber } from '../../lib/format'

// Лестница уровней — кусок 3.
//
// Замысел заказчика: «общие показатели, потом по ведомствам, потом по услугам
// в этих ведомствах». Здесь по подтверждённой иерархии начинают ходить: видно,
// где ты находишься, что лежит уровнем ниже и как вернуться наверх.
//
// 🔴 Отличие от полосы разбора строки (RowDrillBar), которая стоит рядом:
// та работает ПО СТРОКАМ формы (отделение), а лестница — ПО ГРАФАМ (ведомство,
// услуга). Строки в лестнице — самая нижняя ступень, и дойдя до неё, человек
// передаёт эстафету уже существующему фильтру строк.
export default function LadderBar(
  { pageId, path, setPath, from, to }:
  { pageId: string | null; path: string[]; setPath: (p: string[]) => void
    from?: string; to?: string },
) {
  const [st, setSt] = useState<LadderStep | null>(null)
  const [measure, setMeasure] = useState<string>('')
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!pageId) { setSt(null); return }
    let alive = true
    getLadder(pageId, path, measure || undefined, from, to)
      .then((s) => { if (alive) setSt(s) })
      .catch(() => { if (alive) setSt(null) })
    return () => { alive = false }
  }, [pageId, path.join('>'), measure, from, to]) // eslint-disable-line react-hooks/exhaustive-deps

  // Ступеней у формы нет или они не подтверждены — молчим совсем. Полоса с
  // объяснением на каждой странице без иерархии была бы фоновым шумом; там,
  // где ступени подтверждать нужно, об этом говорит экран объекта.
  if (!st || !st.available) return null

  const kids = st.children || []
  const top = kids.slice(0, open ? kids.length : 8)
  const max = Math.max(1, ...kids.map((k) => Math.abs(k.total)))
  const levels = st.levels || []

  return (
    <div style={box}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>🪜</span>
        <button type="button" style={crumb(path.length === 0)} onClick={() => setPath([])}>
          Все{levels[0] ? ` · ${levels[0]}` : ''}
        </button>
        {path.map((seg, i) => (
          <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: 'var(--text-faint)' }}>→</span>
            <button type="button" style={crumb(i === path.length - 1)}
              title={seg} onClick={() => setPath(path.slice(0, i + 1))}>{seg}</button>
          </span>
        ))}
        {st.measures && st.measures.length > 1 && (
          <select style={sel} value={measure || st.measure || ''}
            onChange={(e) => setMeasure(e.target.value)}>
            {st.measures.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        )}
      </div>

      {/* Пропуск ступени назван словами: молчаливый пропуск читался бы как
          «здесь показаны услуги», то есть человек принял бы за услуги
          отделения. */}
      {st.note && <div style={note}>{st.note}</div>}

      <div style={{ fontSize: 13, color: 'var(--text-muted)', margin: '8px 0 4px' }}>
        {st.is_rows ? 'Ниже — ' : 'Ниже — уровень '}
        <b style={{ color: 'var(--text-2)' }}>{st.level_name}</b>
        {` · значений: ${kids.length}`}
        {st.measure ? ` · показано «${st.measure}»` : ''}
      </div>

      {kids.length === 0 && (
        <div style={{ fontSize: 13, color: 'var(--text-faint)' }}>
          По этой ветке за выбранный период данных нет.
        </div>
      )}

      {top.map((k) => (
        <button key={k.value} type="button" style={rowBtn}
          title={st.is_rows ? k.value : `Открыть «${k.value}»`}
          disabled={st.is_rows}
          onClick={() => { if (!st.is_rows) setPath([...path, k.value]) }}>
          <span style={{ ...bar, width: `${Math.max(2, Math.abs(k.total) / max * 100)}%` }} />
          <span style={label}>{k.value}</span>
          <span style={num}>
            {fmtNumber(k.total)}
            {k.aggregate === 'avg' && <span title="среднее по строкам" style={avg}> ⌀</span>}
          </span>
        </button>
      ))}

      {kids.length > top.length && (
        <>
          {/* Молчаливой обрезки быть не должно — правило и формулировка те же,
              что у «Ранжированного списка» и «Сравнения показателей». Замер на
              форме РЦО: на первой ступени 29 значений, из них семь за этот день
              с нулём; макет обещал 22 строки, и обе цифры верны — просто
              мелкое и пустое уходит за кнопку, а не исчезает. */}
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
            Показаны самые крупные: {top.length} из {kids.length} — остальные меньше по объёму,
            в том числе те, у кого за этот отчёт ноль.
          </div>
          <button type="button" style={more} onClick={() => setOpen(true)}>
            показать все {kids.length}
          </button>
        </>
      )}
      {open && kids.length > 8 && (
        <button type="button" style={more} onClick={() => setOpen(false)}>свернуть</button>
      )}
    </div>
  )
}

const box: React.CSSProperties = {
  border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px',
  marginBottom: 12, background: 'var(--surface-2)', fontSize: 14,
}
const crumb = (active: boolean): React.CSSProperties => ({
  background: 'none', border: 'none', padding: 0, cursor: active ? 'default' : 'pointer',
  color: active ? 'var(--text)' : 'var(--accent)', fontSize: 13,
  fontWeight: active ? 600 : 400, maxWidth: 260, overflow: 'hidden',
  textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  textDecoration: active ? 'none' : 'underline dotted',
})
const sel: React.CSSProperties = {
  marginLeft: 'auto', height: 28, border: '1px solid var(--border-strong)',
  borderRadius: 8, fontSize: 13, padding: '0 6px', maxWidth: 220,
}
const note: React.CSSProperties = {
  marginTop: 8, padding: '6px 8px', borderRadius: 8, fontSize: 13,
  background: 'var(--alert-warn-bg)', color: 'var(--alert-warn)',
}
const rowBtn: React.CSSProperties = {
  position: 'relative', display: 'flex', alignItems: 'center', gap: 8, width: '100%',
  background: 'none', border: 'none', borderTop: '1px solid var(--border-faint)',
  padding: '6px 4px', cursor: 'pointer', textAlign: 'left', fontSize: 13,
  color: 'var(--text)', boxSizing: 'border-box',
}
// Полоса величины — не сигнальная: она говорит «много или мало на фоне
// остальных», а не «хорошо или плохо» (тот же токен, что в рейтинге строк).
const bar: React.CSSProperties = {
  position: 'absolute', left: 0, top: 4, bottom: 4, background: 'var(--rank-bar)',
  opacity: 0.18, borderRadius: 4, pointerEvents: 'none',
}
const label: React.CSSProperties = {
  minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  position: 'relative',
}
const num: React.CSSProperties = { flexShrink: 0, fontWeight: 600, position: 'relative' }
const avg: React.CSSProperties = { color: 'var(--text-faint)', fontWeight: 400 }
const more: React.CSSProperties = {
  background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer',
  fontSize: 13, padding: '6px 0', textDecoration: 'underline dotted',
}
