import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { listFeaturedCandidates, setFeaturedBulk, type FeaturedCandidate } from '../../api'

// Настройка состава подборки «Руководителю» (пп. 2–3 запроса заказчика).
//
// Раньше отчёт попадал в подборку галочкой в общем списке дашбордов: чтобы
// собрать её, администратор должен был сам помнить, какие отчёты вообще есть
// и какие из них годятся руководителю. Здесь тот же выбор сделан списком.
//
// **Совет системы — не решение.** Она смотрит только на проверяемые признаки
// (опубликован, есть числовые показатели, есть описание, смотрят ли его) и
// объясняет каждый. «Полезно руководителю» — суждение человека, поэтому
// галочки ставит он, а рекомендованное просто идёт первым.
//
// **Отметка не выдаёт доступ.** Об этом сказано прямо и показано, скольким
// людям отчёт виден: иначе можно вынести в подборку дашборд, которого
// руководитель всё равно не увидит.
export default function FeaturedPicker({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [items, setItems] = useState<FeaturedCandidate[] | null>(null)
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [q, setQ] = useState('')

  const load = () => {
    listFeaturedCandidates().then((r) => {
      setItems(r.items)
      setChecked(Object.fromEntries(r.items.map((i) => [i.id, i.featured])))
    }).catch((e) => setErr((e as Error).message))
  }
  useEffect(load, [])

  const shown = useMemo(() => {
    const list = items || []
    const needle = q.trim().toLowerCase()
    const filtered = needle
      ? list.filter((i) => i.name.toLowerCase().includes(needle)
        || (i.description || '').toLowerCase().includes(needle)
        || (i.folder_name || '').toLowerCase().includes(needle))
      : list
    // Порядок: уже в подборке → рекомендованные → остальные. Так администратор
    // видит сначала текущий состав, потом то, что стоит добавить.
    return [...filtered].sort((a, b) =>
      Number(b.featured) - Number(a.featured)
      || Number(b.recommended) - Number(a.recommended)
      || a.name.localeCompare(b.name))
  }, [items, q])

  const diff = useMemo(() => {
    const add: string[] = [], remove: string[] = []
    for (const i of items || []) {
      const now = !!checked[i.id]
      if (now && !i.featured) add.push(i.id)
      if (!now && i.featured) remove.push(i.id)
    }
    return { add, remove }
  }, [items, checked])

  async function save() {
    setBusy(true); setErr(null)
    try {
      await setFeaturedBulk(diff.add, diff.remove)
      onSaved()
      onClose()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  const changes = diff.add.length + diff.remove.length
  const recommended = (items || []).filter((i) => i.recommended).length

  return createPortal((
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Состав подборки «Руководителю»</div>
          <button style={{ ...xBtn, marginLeft: 'auto' }} onClick={onClose} title="Закрыть">✕</button>
        </div>
        <div style={{ ...muted, marginBottom: 10 }}>
          Отметьте отчёты, которые нужны руководству. Отметка задаёт только состав подборки —
          <b> доступ к отчёту она не выдаёт</b>: его дают правами на самом дашборде или в карточке сотрудника.
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, flexWrap: 'wrap' }}>
          <input style={input} placeholder="Поиск по названию, описанию, папке"
            value={q} onChange={(e) => setQ(e.target.value)} />
          {recommended > 0 && (
            <button style={linkBtn} onClick={() => setChecked((c) => {
              const n = { ...c }
              ;(items || []).filter((i) => i.recommended).forEach((i) => { n[i.id] = true })
              return n
            })}>отметить рекомендованные ({recommended})</button>
          )}
        </div>

        {err && <div style={errBox}>{err}</div>}
        {!items && !err && <div style={muted}>Загрузка…</div>}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, overflowY: 'auto', flex: 1, minHeight: 0 }}>
          {items && shown.length === 0 && <div style={muted}>Ничего не найдено.</div>}
          {shown.map((i) => (
            <label key={i.id} style={{
              display: 'flex', gap: 10, alignItems: 'flex-start', padding: '8px 10px', borderRadius: 10,
              border: '1px solid var(--border-faint)', cursor: 'pointer',
              background: checked[i.id] ? 'var(--accent-weak-bg)' : undefined,
            }}>
              <input type="checkbox" checked={!!checked[i.id]} style={{ marginTop: 3 }}
                onChange={(e) => setChecked((c) => ({ ...c, [i.id]: e.target.checked }))} />
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <b style={{ fontSize: 13 }}>{i.name}</b>
                  {i.featured && <span style={badge}>уже в подборке</span>}
                  {i.recommended && <span style={okBadge}>рекомендуем</span>}
                  {i.publication_status !== 'published' && <span style={warnBadge}>черновик</span>}
                </span>
                {i.description && (
                  <span style={{ display: 'block', fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>
                    {i.description}
                  </span>
                )}
                <span style={{ display: 'block', ...muted, marginTop: 3 }}>
                  {[i.object_name, i.folder_name].filter(Boolean).join(' / ') || 'без папки'}
                  {' · '}показателей с цифрами: {i.number_widgets}
                  {' · '}виден {i.visible_to} чел.
                  {i.views_30d > 0 && ` · ${i.views_30d} просм. за месяц`}
                </span>
                {/* Что мешает: не запрет, а предупреждение. Отметить можно и
                    такой отчёт — например, доступ выдадут следом. */}
                {i.blockers.length > 0 && (
                  <span style={{ display: 'block', fontSize: 12, color: 'var(--warn)', marginTop: 3 }}>
                    {i.blockers.join(' · ')}
                  </span>
                )}
              </span>
            </label>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 12 }}>
          <button style={{ ...btn, opacity: changes === 0 || busy ? 0.5 : 1 }}
            disabled={changes === 0 || busy} onClick={save}>
            {busy ? 'Сохранение…' : 'Сохранить состав'}
          </button>
          <span style={muted}>
            {changes === 0 ? 'Изменений нет.'
              : `Будет добавлено: ${diff.add.length}, убрано: ${diff.remove.length}.`}
          </span>
        </div>
      </div>
    </div>
  ), document.body)
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex',
  alignItems: 'center', justifyContent: 'center', zIndex: 70, padding: 20,
}
const dialog: React.CSSProperties = {
  background: 'var(--surface)', borderRadius: 14, padding: 20, width: 720, maxWidth: '94vw',
  maxHeight: '86vh', display: 'flex', flexDirection: 'column', boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
}
const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 12 }
const input: React.CSSProperties = {
  height: 32, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8,
  fontSize: 13, flex: 1, minWidth: 200,
}
const btn: React.CSSProperties = {
  height: 34, padding: '0 16px', border: 'none', borderRadius: 8,
  background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer',
}
const linkBtn: React.CSSProperties = {
  border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: 0,
}
const badge: React.CSSProperties = {
  fontSize: 11, padding: '1px 8px', borderRadius: 9, background: 'var(--surface-3)', color: 'var(--text-2)',
}
const okBadge: React.CSSProperties = { ...badge, background: 'var(--success-bg)', color: 'var(--success)' }
const warnBadge: React.CSSProperties = { ...badge, background: 'var(--warn-bg)', color: 'var(--warn)' }
const xBtn: React.CSSProperties = {
  border: 'none', background: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--text-muted)',
}
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px',
  borderRadius: 8, marginBottom: 8,
}
