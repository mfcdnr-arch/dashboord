// Разложить существующие дашборды по направлениям: система предлагает,
// администратор подтверждает (решение заказчика 23.09.2026).
import { useEffect, useState } from 'react'
import { applyDirectionProposal, getDirectionProposal, type DirectionProposalGroup } from '../../api'
import { plural } from '../../lib/text'
import { Modal, ModalTitle } from '../Modal'
import Notice from '../Notice'
import { btn, btnGhost, input, rmBtn } from './shared'

type Draft = DirectionProposalGroup & { title: string; picked: Set<string> }

/**
 * Предложение строится по началу имени объекта («Статистика услуг — МВД» →
 * «Статистика услуг»): так объекты в системе и называются. Имя, совпавшее с
 * уже заведённым направлением, ведёт в него. Всё, что предложено, можно
 * переименовать или снять; снятое остаётся без направления.
 */
export function DirectionProposalDialog({ onClose, onDone }: {
  onClose: () => void
  onDone: (summary: string) => void
}) {
  const [groups, setGroups] = useState<Draft[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    getDirectionProposal()
      .then((r) => setGroups(r.groups.map((g) => ({
        ...g, title: g.name, picked: new Set(g.dashboards.map((d) => d.id)),
      }))))
      .catch((e) => setErr((e as Error).message))
  }, [])

  const patch = (i: number, next: Partial<Draft>) =>
    setGroups((gs) => gs && gs.map((g, j) => (j === i ? { ...g, ...next } : g)))
  const toggle = (i: number, id: string) => {
    if (!groups) return
    const picked = new Set(groups[i].picked)
    if (picked.has(id)) picked.delete(id); else picked.add(id)
    patch(i, { picked })
  }
  const chosen = (groups || []).filter((g) => g.picked.size && g.title.trim())
  const total = chosen.reduce((n, g) => n + g.picked.size, 0)

  async function apply() {
    setBusy(true); setErr(null)
    try {
      const r = await applyDirectionProposal(chosen.map((g) => ({ name: g.title.trim(), dashboard_ids: [...g.picked] })))
      onDone(`Разложено ${r.dashboards_assigned} ${plural(r.dashboards_assigned, 'дашборд', 'дашборда', 'дашбордов')}`
        + (r.directions_created ? `, заведено направлений: ${r.directions_created}` : '') + '.')
    } catch (e) { setErr((e as Error).message); setBusy(false) }
  }

  return (
    <Modal onClose={onClose} width={640}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
        <ModalTitle>🧭 Разложить дашборды по направлениям</ModalTitle>
        <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose} aria-label="Закрыть">✕</button>
      </div>
      <p style={{ fontSize: 12.5, color: 'var(--text-muted)', margin: '0 0 12px' }}>
        Система предлагает группы для дашбордов без направления — по началу имени объекта. Поправьте
        названия и снимите лишнее: снятые останутся без направления. Доступ к дашбордам не меняется.
      </p>
      {err && <Notice style={{ marginBottom: 10 }}>{err}</Notice>}
      {groups === null ? (
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Смотрим, что есть…</div>
      ) : groups.length === 0 ? (
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Все дашборды уже разложены по направлениям.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: '55vh', overflowY: 'auto', marginBottom: 12 }}>
          {groups.map((g, i) => (
            <div key={g.name + i} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: '8px 10px' }}>
              <input style={{ ...input, height: 32, width: '100%', boxSizing: 'border-box', fontWeight: 600 }}
                value={g.title} onChange={(e) => patch(i, { title: e.target.value })}
                aria-label={`Название направления для группы «${g.name}»`} />
              <div style={{ fontSize: 12, color: 'var(--text-muted)', margin: '4px 0 6px' }}>
                {g.direction_id ? '↪ ' : '＋ новое · '}{g.why}
              </div>
              {g.dashboards.map((d) => (
                <label key={d.id} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, padding: '2px 0', cursor: 'pointer' }}>
                  <input type="checkbox" checked={g.picked.has(d.id)} onChange={() => toggle(i, d.id)} />
                  <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
                    {d.name}
                    {d.object_name && <span style={{ color: 'var(--text-muted)', fontSize: 12 }}> · {d.object_name}</span>}
                  </span>
                </label>
              ))}
            </div>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {groups && groups.length > 0 && (
          <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>
            Будет разложено: {total} {plural(total, 'дашборд', 'дашборда', 'дашбордов')} в {chosen.length}
            {' '}{plural(chosen.length, 'направление', 'направления', 'направлений')}
          </span>
        )}
        <button style={{ ...btnGhost, marginLeft: 'auto' }} onClick={onClose}>Отмена</button>
        <button style={btn} disabled={busy || !total} onClick={apply}>Разложить</button>
      </div>
    </Modal>
  )
}
