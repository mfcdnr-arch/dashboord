import { useEffect, useState } from 'react'
import { getRowAcl, setRowAcl, type Obj, type RowAcl } from '../api'

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
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>🔐 Доступ к строкам: {object.name}</div>
          <button style={xBtn} onClick={onClose}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 12 }}>
          Ограничение по подразделению: пользователь видит в виджетах только разрешённые его отделу строки данных этого объекта.
          Пока ни для одного отдела нет правил — строки видят все. Администраторы/модераторы видят все строки всегда.
        </div>

        {!data ? <div style={muted}>Загрузка…</div> : data.row_labels.length === 0 ? (
          <div style={muted}>У объекта пока нет строк данных (загрузите и выпустите датасет).</div>
        ) : (
          <>
            {data.enabled && (
              <div style={{ fontSize: 12, color: '#8a6d1a', background: '#fdf6e3', border: '1px solid #f0e2b6', borderRadius: 8, padding: '7px 10px', marginBottom: 12 }}>
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
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 260, overflowY: 'auto', border: '1px solid #eef0f3', borderRadius: 8, padding: 8 }}>
                  {data.row_labels.map((lbl) => (
                    <label key={lbl} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer' }}>
                      <input type="checkbox" checked={checked.has(lbl)} onChange={() => toggle(lbl)} /> {lbl}
                    </label>
                  ))}
                </div>
                <div style={{ fontSize: 12, color: '#9aa4b2', marginTop: 4 }}>Пусто = отдел не видит строк этого объекта (при включённом RLS).</div>
                <button style={{ ...btn, marginTop: 10 }} disabled={busy} onClick={save}>Сохранить для подразделения</button>
              </div>
            )}
          </>
        )}
        {err && <div style={{ color: '#a32d2d', fontSize: 13, marginTop: 8 }}>{err}</div>}
      </div>
    </div>
  )
}

const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60, padding: 20 }
const dialog: React.CSSProperties = { background: '#fff', borderRadius: 14, padding: 22, width: 520, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }
const label: React.CSSProperties = { fontSize: 12, color: '#6b7280', marginBottom: 4 }
const sel: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14, background: '#fff', minWidth: 220 }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: '#2f5496', color: '#fff', fontSize: 14, cursor: 'pointer' }
const xBtn: React.CSSProperties = { marginLeft: 'auto', width: 24, height: 24, border: '1px solid #e5e7eb', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#a32d2d' }
const muted: React.CSSProperties = { color: '#9aa4b2', fontSize: 14, padding: '8px 0' }
