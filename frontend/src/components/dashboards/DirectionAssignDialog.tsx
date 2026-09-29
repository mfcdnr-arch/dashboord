// Назначить направление одному или нескольким дашбордам (этап 3, 29.09.2026).
import { useEffect, useState } from 'react'
import { assignDirection, listDirections, type Direction } from '../../api'
import { Modal, ModalTitle } from '../Modal'
import Notice from '../Notice'
import { btn, btnGhost, input, linkDanger, rmBtn } from './shared'

const NEW = '__new__'

/**
 * Одно окно и для одного дашборда (меню «⋯»), и для выбранных галочками.
 * Сохраняется ОДНОЙ операцией на сервере: массовое перемещение в папку идёт
 * циклом запросов, и сбой на середине оставляет часть переложенной — здесь
 * либо все, либо ни одного.
 */
export function DirectionAssignDialog({ target, onClose, onDone }: {
  target: { ids: string[]; label: string; currentId?: string | null; currentName?: string | null }
  onClose: () => void
  onDone: () => void
}) {
  const [dirs, setDirs] = useState<Direction[]>([])
  const [choice, setChoice] = useState(target.currentId || '')
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    listDirections()
      .then((r) => { setDirs(r.items); if (!r.items.length) setChoice(NEW) })
      .catch((e) => setErr((e as Error).message))
  }, [])
  const bulk = target.ids.length > 1

  async function save(clear = false) {
    setBusy(true); setErr(null)
    try {
      if (clear) await assignDirection(target.ids, null)
      else if (choice === NEW) await assignDirection(target.ids, null, newName.trim())
      else await assignDirection(target.ids, choice)
      onDone()
    } catch (e) { setErr((e as Error).message); setBusy(false) }
  }
  const ready = choice === NEW ? !!newName.trim() : !!choice && choice !== target.currentId

  return (
    <Modal onClose={onClose} width={440}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
        <ModalTitle>🧭 {bulk ? `Направление для ${target.label}` : `Направление дашборда «${target.label}»`}</ModalTitle>
        <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose} aria-label="Закрыть">✕</button>
      </div>
      <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 14px' }}>
        {bulk ? 'Направление будет установлено у всех выбранных дашбордов.'
          : target.currentName ? `Сейчас: «${target.currentName}».` : 'Сейчас без направления.'}
        {' '}Доступ к дашбордам не меняется.
      </p>
      {err && <Notice style={{ marginBottom: 10 }}>{err}</Notice>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
        <select style={input} aria-label="Направление" value={choice} onChange={(e) => setChoice(e.target.value)}>
          {dirs.length > 0 && <option value="">выберите направление…</option>}
          {dirs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          <option value={NEW}>＋ Новое направление…</option>
        </select>
        {choice === NEW && (
          <input style={input} value={newName} onChange={(e) => setNewName(e.target.value)} autoFocus
            aria-label="Название нового направления" placeholder="Например, «Статистика услуг»" />
        )}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        {(bulk || target.currentId) && (
          <button style={linkDanger} disabled={busy} onClick={() => save(true)}>
            {bulk ? 'убрать направление у всех' : 'убрать направление'}
          </button>
        )}
        <button style={{ ...btnGhost, marginLeft: 'auto' }} onClick={onClose}>Отмена</button>
        <button style={btn} disabled={busy || !ready} onClick={() => save()}>Сохранить</button>
      </div>
    </Modal>
  )
}
