// Направления — группы дашбордов внутри раздела «Дашборды» (этап 3, 29.09.2026).
import { useEffect, useState } from 'react'
import {
  createDirection, deleteDirection, listDirections, reorderDirections, updateDirection,
  type Direction,
} from '../../api'
import { plural } from '../../lib/text'
import { Modal, ModalTitle } from '../Modal'
import Notice from '../Notice'
import { useConfirm } from './ConfirmDialog'
import { btn, btnAuto, btnGhost, input, linkDanger, rmBtn } from './shared'

/**
 * Управление направлениями: завести, переименовать, упорядочить, удалить.
 *
 * Направление только группирует: кто видит какой дашборд, по-прежнему решают
 * доступы к дашбордам (решение заказчика 23.09). Удаление направления
 * дашборды не трогает — они остаются без направления.
 */
export function DirectionsDialog({ onClose, onChanged, onPropose }: {
  onClose: () => void
  /** Что-то поменялось — список дашбордов надо перечитать. */
  onChanged: () => void
  /** Открыть раскладку по предложению системы (только администратору). */
  onPropose?: () => void
}) {
  const { ask, node: confirmNode } = useConfirm()
  const [items, setItems] = useState<Direction[] | null>(null)
  const [newName, setNewName] = useState('')
  const [editId, setEditId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const load = () => listDirections().then((r) => setItems(r.items)).catch((e) => setErr((e as Error).message))
  useEffect(() => { load() }, [])

  async function run(action: () => Promise<unknown>) {
    setBusy(true); setErr(null)
    try { await action(); await load(); onChanged() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const add = () => run(async () => { await createDirection(newName.trim()); setNewName('') })
  const rename = (d: Direction) => run(async () => { await updateDirection(d.id, { name: editName.trim() }); setEditId(null) })
  async function remove(d: Direction) {
    const ok = await ask({
      title: `Удалить направление «${d.name}»?`,
      message: d.dashboards
        ? `${d.dashboards} ${plural(d.dashboards, 'дашборд останется', 'дашборда останутся', 'дашбордов останутся')} без направления — сами дашборды, доступы и данные не пострадают.`
        : 'В направлении нет дашбордов.',
    })
    if (ok) await run(() => deleteDirection(d.id))
  }
  function move(i: number, delta: number) {
    if (!items) return
    const next = [...items]
    const [it] = next.splice(i, 1)
    next.splice(i + delta, 0, it)
    setItems(next)
    run(() => reorderDirections(next.map((d) => d.id)))
  }

  return (
    <Modal onClose={onClose} width={560}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
        <ModalTitle>🧭 Направления</ModalTitle>
        <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose} aria-label="Закрыть">✕</button>
      </div>
      <p style={{ fontSize: 12.5, color: 'var(--text-muted)', margin: '0 0 12px' }}>
        Направление — группа в списке «Дашборды» («РЦО», «МАХ», «Статистика услуг»). У дашборда
        одно направление или никакого. Доступ не меняется: кто видит какой дашборд, решают
        доступы к самим дашбордам. Порядок здесь — порядок групп в списке.
      </p>
      {err && <Notice style={{ marginBottom: 10 }}>{err}</Notice>}
      {items === null ? (
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Загружаем…</div>
      ) : items.length === 0 ? (
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 10 }}>
          Направлений пока нет. Заведите первое ниже
          {onPropose ? ' или разложите дашборды по предложению системы.' : '.'}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12, maxHeight: 360, overflowY: 'auto' }}>
          {items.map((d, i) => (
            <div key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 6px',
              border: '1px solid var(--border-faint)', borderRadius: 8 }}>
              <button style={arrow} disabled={busy || i === 0} onClick={() => move(i, -1)}
                aria-label={`Поднять «${d.name}» выше`}>▲</button>
              <button style={arrow} disabled={busy || i === items.length - 1} onClick={() => move(i, 1)}
                aria-label={`Опустить «${d.name}» ниже`}>▼</button>
              {editId === d.id ? (
                <form style={{ display: 'flex', gap: 6, flex: 1, minWidth: 0 }}
                  onSubmit={(e) => { e.preventDefault(); if (editName.trim()) rename(d) }}>
                  <input style={{ ...input, height: 30, flex: 1, minWidth: 0 }} value={editName} autoFocus
                    aria-label={`Новое название направления «${d.name}»`}
                    onChange={(e) => setEditName(e.target.value)} />
                  <button style={{ ...btn, height: 30 }} disabled={busy || !editName.trim()}>Сохранить</button>
                  <button type="button" style={{ ...btnGhost, height: 30 }} onClick={() => setEditId(null)}>Отмена</button>
                </form>
              ) : (
                <>
                  <span style={{ flex: 1, minWidth: 0, fontSize: 13.5, overflowWrap: 'anywhere' }}>
                    {d.name}
                    <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                      {' · '}{d.dashboards} {plural(d.dashboards, 'дашборд', 'дашборда', 'дашбордов')}
                    </span>
                  </span>
                  <button style={link} disabled={busy} onClick={() => { setEditId(d.id); setEditName(d.name) }}
                    aria-label={`Переименовать «${d.name}»`}>переименовать</button>
                  <button style={linkDanger} disabled={busy} onClick={() => remove(d)}
                    aria-label={`Удалить направление «${d.name}»`}>удалить</button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
      <form style={{ display: 'flex', gap: 8, marginBottom: 12 }}
        onSubmit={(e) => { e.preventDefault(); if (newName.trim()) add() }}>
        <input style={{ ...input, flex: 1, minWidth: 0 }} value={newName} onChange={(e) => setNewName(e.target.value)}
          aria-label="Название нового направления" placeholder="Новое направление, например «Окна и очереди»" />
        <button style={btn} disabled={busy || !newName.trim()}>＋ Завести</button>
      </form>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {onPropose && (
          <button style={btnAuto} onClick={onPropose} disabled={busy}>
            Разложить дашборды по предложению системы…
          </button>
        )}
        <button style={{ ...btnGhost, marginLeft: 'auto' }} onClick={onClose}>Готово</button>
      </div>
      {confirmNode}
    </Modal>
  )
}

const arrow: React.CSSProperties = {
  width: 24, height: 24, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)',
  cursor: 'pointer', fontSize: 10, color: 'var(--text-muted)', padding: 0, flexShrink: 0,
}
const link: React.CSSProperties = {
  border: 'none', background: 'none', color: 'var(--accent-text)', cursor: 'pointer', fontSize: 12, padding: 0,
}
