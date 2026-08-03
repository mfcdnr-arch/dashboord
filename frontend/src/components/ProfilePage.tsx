import { useEffect, useState } from 'react'
import {
  changePassword, checkPassword, getMyActivity, getPasswordPolicy, getToken, passwordHint,
  type Me, type PasswordPolicy, type UserActivity,
} from '../api'
import AppealsPanel from './AppealsPanel'

// «Личный кабинет» (волна C): профиль + своя активность + смена пароля +
// мои обращения — в одном месте, доступно ЛЮБОМУ пользователю (не только
// admin/audit, в отличие от панели активности в разделе «Пользователи»).

function fmtDt(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

const ACTION_RU: Record<string, string> = {
  create: 'создание', update: 'изменение', delete: 'удаление', view: 'просмотр',
  publish: 'публикация', grant_access: 'выдача доступа', revoke_access: 'отзыв доступа',
  archive: 'архивация', unarchive: 'возврат из архива', export: 'выгрузка',
}

export default function ProfilePage({ me }: { me: Me }) {
  const [tab, setTab] = useState<'profile' | 'appeals'>('profile')
  return (
    <div>
      <h2 style={{ fontSize: 20, margin: '0 0 4px' }}>Личный кабинет</h2>
      <div style={{ display: 'flex', gap: 8, margin: '12px 0 18px' }}>
        <button onClick={() => setTab('profile')} style={tab === 'profile' ? tabActive : tabBtn}>Профиль и активность</button>
        <button onClick={() => setTab('appeals')} style={tab === 'appeals' ? tabActive : tabBtn}>💬 Мои обращения</button>
      </div>
      {tab === 'profile' ? <ProfileTab me={me} /> : <AppealsPanel scope="mine" />}
    </div>
  )
}

function ProfileTab({ me }: { me: Me }) {
  const fio = [me.last_name, me.first_name, me.middle_name].filter(Boolean).join(' ') || me.full_name || me.login
  const [activity, setActivity] = useState<UserActivity | null>(null)
  const [actErr, setActErr] = useState<string | null>(null)
  useEffect(() => { getMyActivity().then(setActivity).catch((e) => setActErr((e as Error).message)) }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={card}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>{fio}</div>
        <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr', rowGap: 6, fontSize: 13 }}>
          <span style={{ color: 'var(--text-muted)' }}>Логин</span><span>{me.login}</span>
          <span style={{ color: 'var(--text-muted)' }}>Роли</span>
          <span>{me.role_names.join(', ') || '—'}</span>
          <span style={{ color: 'var(--text-muted)' }}>Отдел</span><span>{me.department_name || '—'}</span>
          <span style={{ color: 'var(--text-muted)' }}>Email</span><span>{me.email || '—'}</span>
          <span style={{ color: 'var(--text-muted)' }}>В системе с</span><span>{fmtDt(me.created_at)}</span>
        </div>
      </div>

      <PasswordCard login={me.login} />

      <div style={card}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>Моя активность</div>
        {actErr && <div style={errBox}>{actErr}</div>}
        {!activity && !actErr && <div style={muted}>Загрузка…</div>}
        {activity && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ fontSize: 13 }}>Успешных входов: <b>{activity.login_count}</b></div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Последние входы</div>
              {activity.logins.length === 0 ? <div style={muted}>Входов не было.</div> : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 140, overflowY: 'auto' }}>
                  {activity.logins.map((l, i) => (
                    <div key={i} style={{ display: 'flex', gap: 8, fontSize: 12 }}>
                      <span style={{ color: l.success ? 'var(--success)' : 'var(--danger)' }}>{l.success ? '✓' : '✕'}</span>
                      <span style={{ color: 'var(--text-faint)', flex: 1 }}>{l.ip || '—'}</span>
                      <span style={{ color: 'var(--text-faint)' }}>{fmtDt(l.created_at)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Мои действия (в т.ч. просмотры и выгрузки)</div>
              {activity.events.length === 0 ? <div style={muted}>Действий не зафиксировано.</div> : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 200, overflowY: 'auto' }}>
                  {activity.events.map((e) => (
                    <div key={e.id} style={{ display: 'flex', gap: 8, fontSize: 12 }}>
                      <span style={roleBadge}>{ACTION_RU[e.action] || e.action}</span>
                      <span style={{ flex: 1 }}>{e.entity_name || e.entity_type}</span>
                      <span style={{ color: 'var(--text-faint)' }}>{fmtDt(e.created_at)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Мои комментарии к дашбордам</div>
              {activity.comments.length === 0 ? <div style={muted}>Комментариев не оставлял(а).</div> : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 160, overflowY: 'auto' }}>
                  {activity.comments.map((c) => (
                    <div key={c.id} style={{ fontSize: 12 }}>
                      <span style={{ color: 'var(--text-faint)' }}>{fmtDt(c.created_at)} · {c.dashboard_name}: </span>{c.body}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function PasswordCard({ login }: { login: string }) {
  const [open, setOpen] = useState(false)
  const [pw1, setPw1] = useState('')
  const [pw2, setPw2] = useState('')
  const [policy, setPolicy] = useState<PasswordPolicy>({ min_length: 8, require_complexity: true })
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (open) getPasswordPolicy().then(setPolicy) }, [open])
  const pwErr = pw1 ? checkPassword(pw1, policy, login) : null

  async function submit() {
    setErr(null); setOk(false)
    const v = checkPassword(pw1, policy, login)
    if (v) { setErr(v); return }
    if (pw1 !== pw2) { setErr('Пароли не совпадают'); return }
    setBusy(true)
    try {
      await changePassword(getToken() || '', pw1)
      setOk(true); setPw1(''); setPw2(''); setOpen(false)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>Пароль</div>
        {!open && <button style={{ ...linkBtn, marginLeft: 'auto' }} onClick={() => { setOpen(true); setOk(false) }}>Сменить пароль</button>}
      </div>
      {ok && <div style={{ fontSize: 13, color: 'var(--success)', marginTop: 8 }}>Пароль изменён.</div>}
      {open && (
        <div style={{ marginTop: 12, maxWidth: 320 }}>
          <label style={label}>Новый пароль</label>
          <input style={{ ...input, borderColor: pwErr ? 'var(--danger)' : 'var(--border-strong)' }} type="password"
            value={pw1} onChange={(e) => setPw1(e.target.value)} autoFocus />
          <div style={{ fontSize: 12, color: pwErr ? 'var(--danger)' : 'var(--text-muted)', margin: '4px 0 10px' }}>{pwErr || passwordHint(policy)}</div>
          <label style={label}>Повторите пароль</label>
          <input style={input} type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} />
          {err && <div style={errBox}>{err}</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button style={btn} disabled={busy || !pw1 || !pw2} onClick={submit}>{busy ? 'Сохранение…' : 'Сохранить'}</button>
            <button style={btnGhost} onClick={() => { setOpen(false); setPw1(''); setPw2(''); setErr(null) }}>Отмена</button>
          </div>
        </div>
      )}
    </div>
  )
}

const card: React.CSSProperties = { border: '1px solid var(--border)', borderRadius: 12, padding: 16 }
const tabBtn: React.CSSProperties = { height: 34, padding: '0 14px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', cursor: 'pointer', fontSize: 13 }
const tabActive: React.CSSProperties = { ...tabBtn, background: 'var(--accent-weak-bg)', border: '1px solid var(--accent)', color: 'var(--accent)' }
const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 13 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginTop: 8 }
const roleBadge: React.CSSProperties = { display: 'inline-block', margin: '1px 4px 1px 0', padding: '1px 8px', borderRadius: 8, background: 'var(--surface-3)', color: 'var(--text-2)', fontSize: 12 }
const linkBtn: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 13, padding: 0 }
const label: React.CSSProperties = { fontSize: 13, color: 'var(--text-muted)', marginBottom: 4, display: 'block' }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14, width: '100%', boxSizing: 'border-box' }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { height: 36, padding: '0 14px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text-2)', fontSize: 14, cursor: 'pointer' }
