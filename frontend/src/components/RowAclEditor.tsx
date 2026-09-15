import { useEffect, useState } from 'react'
import { getRowAcl, setRowAcl, type Obj, type RowAcl } from '../api'
import { Modal, ModalTitle } from './Modal'

// Редактор row-level RLS: какие строки данных (row_label) объекта видит какое
// подразделение. Пока ни для одного отдела нет правил — строки видят все.
export default function RowAclEditor({ object, onClose }: { object: Obj; onClose: () => void }) {
  const [data, setData] = useState<RowAcl | null>(null)
  const [dept, setDept] = useState('')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => getRowAcl(object.id).then(setData).catch((e) => setErr((e as Error).message))
  useEffect(() => { load() }, [object.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // При смене отдела — подтянуть его текущий набор разрешённых строк.
  useEffect(() => {
    if (!data || !dept) { setChecked(new Set()); return }
    const d = data.departments.find((x) => x.id === dept)
    setChecked(new Set(d?.row_labels || []))
  }, [dept, data])

  function toggle(lbl: string) {
    setChecked((prev) => { const n = new Set(prev); n.has(lbl) ? n.delete(lbl) : n.add(lbl); return n })
  }
  async function save() {
    if (!dept) { setErr('Выберите подразделение'); return }
    setBusy(true); setErr(null)
    try { await setRowAcl(object.id, dept, [...checked]); await load() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <Modal onClose={onClose} width={520}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
        <ModalTitle>🔐 Доступ к строкам: {object.name}</ModalTitle>
        <button style={xBtn} onClick={onClose}>✕</button>
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
        Ограничение по подразделению: пользователь видит в виджетах только разрешённые его отделу строки данных этого объекта.
        Пока ни для одного отдела нет правил — строки видят все. Администраторы/модераторы видят все строки всегда.
      </div>

      {!data ? <div style={muted}>Загрузка…</div> : data.row_labels.length === 0 ? (
        <div style={muted}>У объекта пока нет строк данных (загрузите и выпустите датасет).</div>
      ) : (
        <>
          {data.enabled && (
            <div style={{ fontSize: 12, color: 'var(--warn)', background: 'var(--warn-bg)', border: '1px solid var(--warn)', borderRadius: 8, padding: '7px 10px', marginBottom: 12 }}>
              ⚠️ RLS по строкам ВКЛЮЧЁН для объекта. Отделы без разрешённых строк не увидят данных этого объекта.
            </div>
          )}
          <div style={{ marginBottom: 12 }}>
            <div style={label}>Подразделение</div>
            <select style={sel} value={dept} onChange={(e) => setDept(e.target.value)}>
              <option value="">выберите…</option>
              {data.departments.map((d) => (
                <option key={d.id} value={d.id}>{d.name}{d.row_labels.length ? ` (${d.row_labels.length})` : ''}</option>
              ))}
            </select>
          </div>

          {dept && (
            <div style={{ marginBottom: 12 }}>
              <div style={label}>Разрешённые строки ({checked.size} из {data.row_labels.length})</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 260, overflowY: 'auto', border: '1px solid var(--border-faint)', borderRadius: 8, padding: 8 }}>
                {data.row_labels.map((lbl) => (
                  <label key={lbl} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer' }}>
                    <input type="checkbox" checked={checked.has(lbl)} onChange={() => toggle(lbl)} /> {lbl}
                  </label>
                ))}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 4 }}>Пусто = отдел не видит строк этого объекта (при включённом RLS).</div>
              <button style={{ ...btn, marginTop: 10 }} disabled={busy} onClick={save}>Сохранить для подразделения</button>
            </div>
          )}
        </>
      )}
      {err && <div style={{ color: 'var(--danger)', fontSize: 13, marginTop: 8 }}>{err}</div>}
    </Modal>
  )
}

const label: React.CSSProperties = { fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }
const sel: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14, background: 'var(--surface)', minWidth: 220 }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
const xBtn: React.CSSProperties = { marginLeft: 'auto', width: 24, height: 24, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', cursor: 'pointer', color: 'var(--danger)' }
const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 14, padding: '8px 0' }
