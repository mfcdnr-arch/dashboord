import { useEffect, useState } from 'react'
import { addDashboardGrant, listDashboardGrants, removeDashboardGrant, type Dashboard, type DashGrant, type GrantTargets, type GrantWidget } from '../../api'
import { F, btn, dialog, muted, overlay, rmBtn, sel } from './shared'

export function AccessEditor({ dashboard, onClose }: { dashboard: Dashboard; onClose: () => void }) {
  const [grants, setGrants] = useState<DashGrant[]>([])
  const [targets, setTargets] = useState<GrantTargets | null>(null)
  const [widgets, setWidgets] = useState<GrantWidget[]>([])
  const [scope, setScope] = useState<'dashboard' | 'widget'>('dashboard')
  const [wid, setWid] = useState('')
  const [gtype, setGtype] = useState<'role' | 'user'>('user')
  const [gid, setGid] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => listDashboardGrants(dashboard.id)
    .then((d) => { setGrants(d.grants); setTargets(d.targets); setWidgets(d.widgets) })
    .catch((e) => setErr((e as Error).message))
  useEffect(() => { load() }, [dashboard.id])

  const options = gtype === 'role' ? (targets?.roles.map((r) => ({ v: r.id, t: r.name })) || [])
    : (targets?.users.map((u) => ({ v: u.id, t: u.full_name || u.login })) || [])

  const dashGrants = grants.filter((g) => g.scope === 'dashboard')
  const widgetGrants = grants.filter((g) => g.scope === 'widget')

  async function add() {
    if (!gid) { setErr('Выберите, кому выдать доступ'); return }
    if (scope === 'widget' && !wid) { setErr('Выберите виджет'); return }
    setErr(null); setBusy(true)
    try {
      const who = gtype === 'role' ? { grantee_type: 'role' as const, role_id: gid } : { grantee_type: 'user' as const, user_id: gid }
      await addDashboardGrant(dashboard.id, scope === 'widget' ? { ...who, scope: 'widget', widget_id: wid } : who)
      setGid(''); await load()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function remove(id: string) {
    setErr(null)
    try { await removeDashboardGrant(dashboard.id, id); await load() } catch (e) { setErr((e as Error).message) }
  }

  const chip = (g: DashGrant) => (
    <span key={g.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, background: '#eef', color: '#2f5496', padding: '4px 10px', borderRadius: 12 }}>
      {g.grantee_type === 'role' ? '👥' : '👤'} {g.label}
      <button style={{ border: 'none', background: 'none', color: '#a32d2d', cursor: 'pointer', padding: 0 }} onClick={() => remove(g.id)} title="Убрать доступ">✕</button>
    </span>
  )

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

        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Доступ к дашборду целиком</div>
        <div style={{ marginBottom: 14 }}>
          {dashGrants.length === 0 ? <div style={muted}>Явных грантов нет — дашборд виден только администраторам/модераторам и автору.</div> : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{dashGrants.map(chip)}</div>
          )}
        </div>

        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Доступ к отдельным виджетам</div>
        <div style={{ marginBottom: 8 }}>
          {widgetGrants.length === 0 ? <div style={muted}>Ограничений по виджетам нет — зрителям дашборда видны все виджеты.</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {widgets.filter((w) => widgetGrants.some((g) => g.widget_id === w.id)).map((w) => (
                <div key={w.id} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 13, color: '#374151' }}>▦ {w.name}:</span>
                  {widgetGrants.filter((g) => g.widget_id === w.id).map(chip)}
                </div>
              ))}
            </div>
          )}
        </div>
        {widgetGrants.length > 0 && (
          <div style={{ fontSize: 12, color: '#8a6d1a', background: '#fdf6e3', border: '1px solid #f0e2b6', borderRadius: 8, padding: '7px 10px', marginBottom: 12 }}>
            ⚠️ Пока есть хотя бы один виджет-грант, зрители-по-гранту видят <b>только</b> выданные им виджеты (белый список). Уберите все виджет-гранты, чтобы вернуть показ всех виджетов.
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <F t="Область"><select style={sel} value={scope} onChange={(e) => { setScope(e.target.value as 'dashboard' | 'widget'); setWid('') }}>
            <option value="dashboard">Весь дашборд</option><option value="widget">Отдельный виджет</option>
          </select></F>
          {scope === 'widget' && (
            <F t="Виджет">
              <select style={{ ...sel, minWidth: 180 }} value={wid} onChange={(e) => setWid(e.target.value)}>
                <option value="">выберите…</option>
                {widgets.map((w) => <option key={w.id} value={w.id}>{w.name} ({w.page_title})</option>)}
              </select>
            </F>
          )}
          <F t="Кому"><select style={sel} value={gtype} onChange={(e) => { setGtype(e.target.value as 'role' | 'user'); setGid('') }}>
            <option value="user">Пользователю</option><option value="role">Роли</option>
          </select></F>
          <F t={gtype === 'role' ? 'Роль' : 'Пользователь'}>
            <select style={{ ...sel, minWidth: 180 }} value={gid} onChange={(e) => setGid(e.target.value)}>
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
