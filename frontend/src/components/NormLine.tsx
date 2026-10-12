import { useState } from 'react'
import { putFieldNorm } from '../api'
import { DURATION_UNIT, fmtDuration, fmtNumber } from '../lib/format'
import { Modal, ModalTitle } from './Modal'
import Notice from './Notice'

// Порог показателя под виджетом: «Порог: внимание от 20 мин, проблема от 30 мин ✎».
//
// Порог — один на графу формы, а не на виджет (миграция 064): его применяют
// все виджеты по этой графе и блок «На что посмотреть». Поэтому правка здесь
// сразу перекрашивает и карточку, и рейтинг, и таблицу — страница
// перечитывается по событию NORM_CHANGED.

export const NORM_CHANGED = 'dashbord:norm-changed'

export interface NormField {
  dataset_code: string
  field: string
  name: string
  unit: string | null
  norm: { warn: number | null; danger: number | null; direction: 'lower' | 'higher' } | null
  direction: 'lower' | 'higher'
  text: string | null
}

export default function NormLine({ fields, summary, canEdit }: {
  fields: NormField[]; summary?: string | null; canEdit: boolean
}) {
  const [edit, setEdit] = useState<NormField | null>(null)
  const set = fields.filter((f) => f.norm)
  if (!set.length && !canEdit) return null
  const one = fields.length === 1
  return (
    <div style={{ fontSize: 11, color: 'var(--text-muted)', margin: '4px 0 2px', display: 'flex', flexWrap: 'wrap', gap: '2px 10px' }}>
      {fields.map((f) => (
        <span key={f.field} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <span>
            Порог{one ? '' : ` «${f.name}»`}: {f.text || <span style={{ color: 'var(--text-faint)' }}>не задан</span>}
          </span>
          {canEdit && (
            <button className="tap-target" style={editBtn} onClick={() => setEdit(f)}
              aria-label={`${f.norm ? 'Изменить' : 'Задать'} порог «${f.name}»`}
              title="Порог один на показатель: его применяют все виджеты по этой графе и блок «На что посмотреть»">
              {f.norm ? '✎' : '＋ задать'}
            </button>
          )}
        </span>
      ))}
      {summary && <span style={{ flexBasis: '100%' }}>{summary}</span>}
      {edit && <NormDialog f={edit} onClose={() => setEdit(null)} />}
    </div>
  )
}

/** Минуты в поле ввода: «20» или «1:30» (ч:мм) или «0:45:30» — как человеку удобнее. */
function parseInput(s: string, duration: boolean): number | null | 'bad' {
  const t = s.trim().replace(',', '.')
  if (!t) return null
  if (duration && t.includes(':')) {
    const p = t.split(':').map(Number)
    if (p.some((x) => !isFinite(x) || x < 0)) return 'bad'
    if (p.length === 2) return p[0] * 60 + p[1]
    if (p.length === 3) return p[0] * 60 + p[1] + p[2] / 60
    return 'bad'
  }
  const n = Number(t)
  return isFinite(n) && n >= 0 ? n : 'bad'
}

export function NormDialog({ f, onClose, onSaved }: { f: NormField; onClose: () => void; onSaved?: () => void }) {
  const duration = f.unit === DURATION_UNIT
  const lower = (f.norm?.direction || f.direction) === 'lower'
  const [warn, setWarn] = useState(f.norm?.warn != null ? String(f.norm.warn) : '')
  const [danger, setDanger] = useState(f.norm?.danger != null ? String(f.norm.danger) : '')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const w = parseInput(warn, duration)
  const d = parseInput(danger, duration)
  const show = (v: number | null | 'bad') => v === 'bad' ? 'не число' : v == null ? '—'
    : duration ? fmtDuration(v) : fmtNumber(v)

  async function save(clear = false) {
    if (!clear && (w === 'bad' || d === 'bad')) { setError('Введите число' + (duration ? ' минут или ч:мм' : '')); return }
    setBusy(true); setError(null)
    try {
      await putFieldNorm(f.dataset_code, f.field, clear ? { warn: null, danger: null }
        : { warn: w as number | null, danger: d as number | null })
      window.dispatchEvent(new CustomEvent(NORM_CHANGED))
      onSaved?.()
      onClose()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const side = lower ? 'от' : 'до'
  return (
    <Modal onClose={onClose} width={440}>
      <ModalTitle>Порог: {f.name}</ModalTitle>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', margin: '6px 0 12px' }}>
        {lower ? 'Чем меньше, тем лучше.' : 'Чем больше, тем лучше.'} Порог один на показатель: по нему окрасятся
        все виджеты с этой графой — карточки, рейтинги, таблицы, динамика, — и превышения появятся в блоке
        «На что посмотреть». {duration && 'Время — в минутах (20) или в виде ч:мм (1:30).'}
      </div>
      {error && <Notice>{error}</Notice>}
      <label style={lbl}>
        <span>Внимание — {side}</span>
        <input style={inp} value={warn} onChange={(e) => setWarn(e.target.value)} inputMode="decimal"
          aria-label={`Внимание — ${side}${duration ? ', минут' : ''}`}
          placeholder={duration ? 'например 20' : ''} />
        <span style={hint}>{show(w)}</span>
      </label>
      <label style={lbl}>
        <span>Проблема — {side}</span>
        <input style={inp} value={danger} onChange={(e) => setDanger(e.target.value)} inputMode="decimal"
          aria-label={`Проблема — ${side}${duration ? ', минут' : ''}`}
          placeholder={duration ? 'например 30' : ''} />
        <span style={hint}>{show(d)}</span>
      </label>
      <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
        <button style={btn} disabled={busy} onClick={() => save()}>{busy ? 'Сохранение…' : 'Сохранить'}</button>
        {f.norm && <button style={btnGhost} disabled={busy} onClick={() => save(true)}>Снять порог</button>}
        <button style={btnGhost} disabled={busy} onClick={onClose}>Отмена</button>
      </div>
    </Modal>
  )
}

const editBtn: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent-text)', cursor: 'pointer', fontSize: 11, padding: 0 }
const lbl: React.CSSProperties = { display: 'grid', gridTemplateColumns: '130px 1fr auto', alignItems: 'center', gap: 8, fontSize: 13, marginBottom: 8 }
const inp: React.CSSProperties = { height: 32, padding: '0 8px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13, boxSizing: 'border-box', width: '100%', background: 'var(--surface)', color: 'var(--text)' }
const hint: React.CSSProperties = { fontSize: 12, color: 'var(--text-muted)', minWidth: 90 }
const btn: React.CSSProperties = { height: 34, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { ...btn, background: 'transparent', color: 'var(--text)', border: '1px solid var(--border-strong)' }
