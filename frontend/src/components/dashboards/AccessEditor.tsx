import { useEffect, useState } from 'react'
import { addDashboardGrant, listDashboardGrants, removeDashboardGrant, type Dashboard, type DashGrant, type GrantTargets } from '../../api'
import { F, btn, dialog, muted, overlay, rmBtn, sel } from './shared'

export function AccessEditor({ dashboard, onClose }: { dashboard: Dashboard; onClose: () => void }) {
  const [grants, setGrants] = useState<DashGrant[]>([])
  const [targets, setTargets] = useState<GrantTargets | null>(null)
  const [gtype, setGtype] = useState<'role' | 'user'>('user')
  const [gid, setGid] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => listDashboardGrants(dashboard.id).then((d) => { setGrants(d.grants); setTargets(d.targets) }).catch((e) => setErr((e as Error).message))
  useEffect(() => { load() }, [dashboard.id])

  const options = gtype === 'role' ? (targets?.roles.map((r) => ({ v: r.id, t: r.name })) || [])
    : (targets?.users.map((u) => ({ v: u.id, t: u.full_name || u.login })) || [])

  async function add() {
    if (!gid) { setErr('Выберите, кому выдать доступ'); return }
    setErr(null); setBusy(true)
    try {
      await addDashboardGrant(dashboard.id, gtype === 'role' ? { grantee_type: 'role', role_id: gid } : { grantee_type: 'user', user_id: gid })
      setGid(''); await load()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function remove(id: string) {
    setErr(null)
    try { await removeDashboardGrant(dashboard.id, id); await load() } catch (e) { setErr((e as Error).message) }
  }

  return (
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 560 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>🔒 Доступ: {dashboard.name}</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 12 }}>
          Администраторы и модераторы видят все дашборды. Остальные — только выданные здесь (по роли или пользователю) и созданные ими самими.
        </div>

        <div style={{ marginBottom: 12 }}>
          {grants.length === 0 ? <div style={muted}>Явных грантов нет — дашборд виден только администраторам/модераторам и автору.</div> : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {grants.map((g) => (
                <span key={g.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, background: '#eef', color: '#2f5496', padding: '4px 10px', borderRadius: 12 }}>
                  {g.grantee_type === 'role' ? '👥' : '👤'} {g.label}
                  <button style={{ border: 'none', background: 'none', color: '#a32d2d', cursor: 'pointer', padding: 0 }} onClick={() => remove(g.id)} title="Убрать доступ">✕</button>
                </span>
              ))}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <F t="Кому"><select style={sel} value={gtype} onChange={(e) => { setGtype(e.target.value as 'role' | 'user'); setGid('') }}>
            <option value="user">Пользователю</option><option value="role">Роли</option>
          </select></F>
          <F t={gtype === 'role' ? 'Роль' : 'Пользователь'}>
            <select style={{ ...sel, minWidth: 200 }} value={gid} onChange={(e) => setGid(e.target.value)}>
              <option value="">выберите…</option>
              {options.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}
            </select>
          </F>
          <button style={btn} disabled={busy} onClick={add}>＋ Выдать доступ</button>
        </div>
        {err && <div style={{ color: '#a32d2d', fontSize: 13, marginTop: 10 }}>{err}</div>}
      </div>
    </div>
  )
}
