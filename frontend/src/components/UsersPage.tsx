import { useEffect, useRef, useState, type FormEvent } from 'react'
import UserCard from './users/UserCard'
import UserAccessPanel from './users/UserAccessPanel'
import { RenameDialog } from './dashboards/RenameDialog'
import { useConfirm } from './dashboards/ConfirmDialog'
import {
  checkPassword, createDepartment, createUser, deleteDepartment, deleteUser, exportLoginEvents, getLoginEvents, getPasswordPolicy,
  grantAuditAccess, listAuditAccess, listDepartments, listRoles, listUsers, passwordHint, resetUserPassword,
  revokeAuditAccess, setUserActive, updateUser,
  type AppUser, type AuditAccessRow, type Department, type LoginEventsReport, type PasswordPolicy, type Role,
} from '../api'

function fmtDt(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

// Раздел «Пользователи» (admin и superadmin): справочник отделов + управление
// пользователями (заведение с временным паролем, роли, отдел, блокировка, сброс
// пароля, удаление). Иерархия: суперадмина может трогать только суперадмин; роль
// superadmin выдаёт только superadmin; «удаление» гибридное (чистого — жёстко,
// с данными — только блокировка).

const USERS_PAGE = 50

export default function UsersPage({ me }: { me: { id: string; roles: string[] } }) {
  // Подтверждения — своим окном: системное браузер вправе подавить, и кнопка
  // необратимого действия выглядит нерабочей (см. ConfirmDialog).
  const { ask, node: confirmNode } = useConfirm()
  const [users, setUsers] = useState<AppUser[]>([])
  const [usersTotal, setUsersTotal] = useState(0)
  const [uq, setUq] = useState('')
  const [depts, setDepts] = useState<Department[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [pwTarget, setPwTarget] = useState<AppUser | null>(null)
  const [edit, setEdit] = useState<AppUser | null>(null)
  const [creating, setCreating] = useState(false)
  const [audit, setAudit] = useState<LoginEventsReport | null>(null)
  // Доступ к аудиту (волна B): у ТЕКУЩЕГО актора его может не быть (admin без
  // гранта) — тогда не показываем журнал входов как ошибку, а поясняем почему.
  const [auditForbidden, setAuditForbidden] = useState(false)
  const [auditAccess, setAuditAccess] = useState<AuditAccessRow[]>([])
  const [activityUser, setActivityUser] = useState<AppUser | null>(null)
  // Фильтры журнала входов: по сотруднику и «только неудачные».
  const [logUser, setLogUser] = useState('')
  const [onlyFailed, setOnlyFailed] = useState(false)

  const fail = (e: unknown) => setError((e as Error).message)
  const loadAudit = () => getLoginEvents({ userId: logUser || undefined, onlyFailed })
    .then((a) => { setAudit(a); setAuditForbidden(false) })
    .catch((e) => { if (/доступа к аудиту/i.test((e as Error).message)) setAuditForbidden(true); else fail(e) })
  // Смена фильтра — перезапрос журнала (сводка приходит полной и остаётся
  // списком для выбора, поэтому выпадашка не «схлопывается» после фильтрации).
  useEffect(() => { if (!auditForbidden) loadAudit() }, [logUser, onlyFailed]) // eslint-disable-line react-hooks/exhaustive-deps
  // Защита от гонки ответов: применяем только результат последнего запроса.
  const reqSeq = useRef(0)
  const loadUsers = (query: string) => {
    const seq = ++reqSeq.current
    return listUsers(query, USERS_PAGE, 0)
      .then((p) => { if (seq === reqSeq.current) { setUsers(p.items); setUsersTotal(p.total) } }).catch(fail)
  }
  const reload = () => {
    loadUsers(uq)
    listDepartments().then(setDepts).catch(fail)
    loadAudit()
    if (isSuper) listAuditAccess().then(setAuditAccess).catch(() => {})
  }
  async function loadMoreUsers() {
    const seq = ++reqSeq.current
    try { const p = await listUsers(uq, USERS_PAGE, users.length); if (seq === reqSeq.current) { setUsers((prev) => [...prev, ...p.items]); setUsersTotal(p.total) } } catch (e) { fail(e) }
  }
  // Список пользователей — по поиску с дебаунсом (он же начальная загрузка).
  useEffect(() => { const t = setTimeout(() => loadUsers(uq), 250); return () => clearTimeout(t) }, [uq]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    listDepartments().then(setDepts).catch(fail)
    listRoles().then(setRoles).catch(fail)
    loadAudit()
    if (isSuper) listAuditAccess().then(setAuditAccess).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const isSuper = me.roles.includes('superadmin')
  if (!me.roles.includes('admin') && !isSuper) {
    return <div style={{ color: 'var(--danger)' }}>Раздел «Пользователи» доступен только администратору.</div>
  }
  // Может ли текущий актор управлять этим пользователем (иерархия ролей):
  // суперадмина трогает только суперадмин; остальных — и admin, и superadmin.
  const canManage = (u: AppUser) => isSuper || !u.roles.includes('superadmin')

  async function addDept(e: FormEvent) {
    e.preventDefault()
    const el = (e.currentTarget as HTMLFormElement).elements.namedItem('dep') as HTMLInputElement
    const name = el.value.trim(); if (!name) return
    setError(null)
    try { await createDepartment(name); el.value = ''; reload() } catch (e) { fail(e) }
  }
  async function delDept(d: Department) {
    if (!await ask({
      title: `Удалить отдел «${d.name}»?`,
      message: 'Сотрудники отдела останутся в системе, но без подразделения — доступ к строкам данных, '
        + 'выданный на этот отдел, перестанет действовать.',
    })) return
    try { await deleteDepartment(d.id); reload() } catch (e) { fail(e) }
  }
  async function toggleActive(u: AppUser) {
    try { await setUserActive(u.id, !u.is_active); reload() } catch (e) { fail(e) }
  }
  // Своё окно вместо системного prompt(): браузер его блокирует, и кнопка
  // выглядела как неработающая.
  async function resetPw(pw: string) {
    if (!pwTarget) return
    setError(null)
    try {
      await resetUserPassword(pwTarget.id, pw)
      setPwTarget(null)
      setNotice(`Пароль пользователя «${pwTarget.login}» сброшен — он сменит его при входе.`)
    } catch (e) { fail(e) }
  }
  async function removeUser(u: AppUser) {
    if (!await ask({
      title: `Удалить пользователя «${u.login}»?`,
      message: 'Удалить можно только того, кто ничего не создавал. Если за пользователем есть данные '
        + 'или история действий, система предложит заблокировать его — так сохранится журнал аудита.',
    })) return
    setError(null)
    try {
      await deleteUser(u.id)
      reload()
    } catch (e) {
      const msg = (e as Error).message
      // Удаление заблокировано наличием данных → сразу предлагаем блокировку.
      if (/заблокир/i.test(msg) && u.is_active) {
        if (await ask({
          title: `Заблокировать «${u.login}» вместо удаления?`,
          message: `${msg}\n\nБлокировка закроет вход, но сохранит всё, что пользователь создал, `
            + 'и его след в журнале аудита. Действие обратимо.',
          confirmLabel: 'Заблокировать', busyLabel: 'Блокировка…',
        })) {
          try { await setUserActive(u.id, false); reload() } catch (e2) { fail(e2) }
          return
        }
      } else {
        fail(e)
      }
    }
  }

  const roleName = (code: string) => roles.find((r) => r.code === code)?.name || code

  return (
    <div>
      {confirmNode}
      <h2 style={{ fontSize: 20, margin: '0 0 16px' }}>Пользователи</h2>
      {error && <div style={errBox}>{error}</div>}
      {notice && (
        <div style={{ background: 'var(--success-bg)', color: 'var(--success)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }}>
          {notice} <button style={{ border: 'none', background: 'none', color: 'inherit', cursor: 'pointer' }} onClick={() => setNotice(null)}>✕</button>
        </div>
      )}
      {pwTarget && (
        <RenameDialog
          title={`Сброс пароля: ${pwTarget.login}`}
          label="Новый временный пароль (минимум 8 символов, буквы и цифры)"
          initial="" placeholder="Пользователь сменит его при первом входе"
          onClose={() => setPwTarget(null)} onSave={resetPw} />
      )}

      {/* Отделы */}
      <Section title="Отделы (справочник)">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
          {depts.length === 0 && <span style={muted}>Отделов пока нет.</span>}
          {depts.map((d) => (
            <span key={d.id} style={chip}>
              {d.name} <span style={{ color: 'var(--text-faint)' }}>· {d.users}</span>
              <button style={xBtn} onClick={() => delDept(d)} title="Удалить отдел">✕</button>
            </span>
          ))}
        </div>
        <form onSubmit={addDept} style={{ display: 'flex', gap: 8 }}>
          <input name="dep" style={input} placeholder="Новый отдел" />
          <button style={btn}>＋ Отдел</button>
        </form>
      </Section>

      {/* Пользователи */}
      <Section title={`Пользователи (${usersTotal})`}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
          <button style={btn} onClick={() => setCreating(true)}>＋ Добавить пользователя</button>
          <input style={{ ...input, flex: 1, minWidth: 200 }} placeholder="🔍 Поиск по логину или ФИО…" value={uq} onChange={(e) => setUq(e.target.value)} />
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
            <thead><tr>
              {['Логин', 'ФИО', 'Отдел', 'Роли', 'Статус', ''].map((h) => <th key={h} style={th}>{h}</th>)}
            </tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} style={{ opacity: u.is_active ? 1 : 0.55 }}>
                  <td style={{ ...td, fontWeight: 600 }}>{u.login}</td>
                  <td style={td}>{u.full_name || '—'}</td>
                  <td style={td}>{u.department || '—'}</td>
                  <td style={td}>
                    {u.roles.length
                      ? u.roles.map((c) => <span key={c} style={c === 'superadmin' ? superBadge : roleBadge}>{roleName(c)}</span>)
                      : '—'}
                  </td>
                  <td style={td}>
                    {u.is_active ? <span style={{ color: 'var(--success)' }}>активен</span> : <span style={{ color: 'var(--danger)' }}>заблокирован</span>}
                    {u.must_change_password && <span style={{ color: 'var(--warn)', marginLeft: 6 }} title="Сменит пароль при входе">· смена пароля</span>}
                  </td>
                  <td style={{ ...td, whiteSpace: 'nowrap' }}>
                    <button style={linkBtn} onClick={() => setActivityUser(u)} title="История входов, действий и комментариев этого пользователя">📊 активность</button>
                    {canManage(u) ? (
                      <>
                        <button style={linkBtn} onClick={() => setEdit(u)}>✎ изменить</button>
                        <button style={linkBtn} onClick={() => setPwTarget(u)}>🔑 пароль</button>
                        {u.id !== me.id && (
                          <button style={{ ...linkBtn, color: u.is_active ? 'var(--danger)' : 'var(--success)' }} onClick={() => toggleActive(u)}>
                            {u.is_active ? '🔒 блок' : '🔓 разблок'}
                          </button>
                        )}
                        {u.id !== me.id && (
                          <button style={{ ...linkBtn, color: 'var(--danger)' }} onClick={() => removeUser(u)} title="Удалить (жёстко — только если нет данных)">🗑 удалить</button>
                        )}
                        {isSuper && u.roles.includes('admin') && !u.roles.includes('superadmin') && (
                          auditAccess.some((a) => a.user_id === u.id) ? (
                            <button style={{ ...linkBtn, color: 'var(--warn)' }} title="Отозвать доступ к журналу аудита"
                              onClick={() => revokeAuditAccess(u.id).then(() => listAuditAccess().then(setAuditAccess)).catch(fail)}>🕵 отозвать аудит</button>
                          ) : (
                            <button style={linkBtn} title="Выдать доступ к журналу аудита (по умолчанию видит только superadmin)"
                              onClick={() => grantAuditAccess(u.id).then(() => listAuditAccess().then(setAuditAccess)).catch(fail)}>🕵 дать аудит</button>
                          )
                        )}
                      </>
                    ) : (
                      <span style={{ color: 'var(--text-faint)', fontSize: 12 }} title="Управлять суперадминистратором может только суперадминистратор">🔒 только суперадмин</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {users.length === 0 && <div style={muted}>Ничего не найдено.</div>}
        {users.length < usersTotal && (
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <button style={{ ...btn, background: 'var(--accent-weak-bg)', color: 'var(--accent)' }} onClick={loadMoreUsers}>
              Показать ещё ({usersTotal - users.length})
            </button>
          </div>
        )}
      </Section>

      {/* Аудит входов */}
      <Section title="Журнал входов (аудит)">
        {auditForbidden ? (
          <div style={muted}>
            У вас нет доступа к журналу входов. {isSuper ? '' : 'Обратитесь к суперадминистратору — он может выдать доступ.'}
          </div>
        ) : (
          <>
        {/* Фильтры журнала: в организации на два десятка учёток общая лента не
            отвечает на вопрос «когда заходил Иванов». Выгрузка идёт с теми же
            фильтрами — файл должен совпадать с тем, что видно на экране. */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            Пользователь:
            <select style={{ ...input, height: 30 }} value={logUser}
              onChange={(e) => setLogUser(e.target.value)}>
              <option value="">все</option>
              {(audit?.summary || []).map((s) => (
                <option key={s.user_id} value={s.user_id}>{s.login}{s.full_name ? ` · ${s.full_name}` : ''}</option>
              ))}
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
            title="Только неудачные попытки входа — разбор инцидентов">
            <input type="checkbox" checked={onlyFailed} onChange={(e) => setOnlyFailed(e.target.checked)} />
            только неудачные
          </label>
          {(logUser || onlyFailed) && (
            <button style={linkBtn} onClick={() => { setLogUser(''); setOnlyFailed(false) }}>сбросить</button>
          )}
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }} title="Выгрузка учитывает выбранные фильтры">
            <button style={linkBtn} onClick={() => exportLoginEvents('csv', { userId: logUser || undefined, onlyFailed }).catch(() => {})}>⤓ CSV</button>
            <button style={linkBtn} onClick={() => exportLoginEvents('xlsx', { userId: logUser || undefined, onlyFailed }).catch(() => {})}>⤓ Excel</button>
          </span>
        </div>
        {!audit ? <span style={muted}>Загрузка…</span> : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>По пользователям</div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
                  <thead><tr>{['Логин', 'Входов', 'Неудач', 'Последний вход'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
                  <tbody>
                    {audit.summary.map((s) => (
                      <tr key={s.login} onClick={() => setLogUser(s.user_id === logUser ? '' : s.user_id)}
                        title="Показать журнал только по этому пользователю"
                        style={{ opacity: s.is_active ? 1 : 0.55, cursor: 'pointer',
                          background: s.user_id === logUser ? 'var(--accent-weak-bg)' : undefined }}>
                        <td style={{ ...td, fontWeight: 600 }}>{s.login}</td>
                        <td style={td}>{s.logins}</td>
                        <td style={{ ...td, color: s.failed ? 'var(--danger)' : undefined }}>{s.failed}</td>
                        <td style={td}>{fmtDt(s.last_login)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                {logUser
                  ? `События: ${(audit?.summary || []).find((x) => x.user_id === logUser)?.login || ''}`
                  : 'Последние события'}
                {onlyFailed && <span style={{ color: 'var(--danger)', fontWeight: 400 }}> · только неудачные</span>}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 260, overflowY: 'auto' }}>
                {audit.recent.length === 0 && <span style={muted}>Событий пока нет.</span>}
                {audit.recent.map((r, i) => (
                  <div key={i} style={{ display: 'flex', gap: 8, fontSize: 12, alignItems: 'center' }}>
                    <span style={{ color: r.success ? 'var(--success)' : 'var(--danger)' }}>{r.success ? '✓' : '✕'}</span>
                    <span style={{ flex: 1 }}><b>{r.login}</b>{r.full_name ? ` · ${r.full_name}` : ''}</span>
                    <span style={{ color: 'var(--text-faint)' }}>{r.ip || '—'}</span>
                    <span style={{ color: 'var(--text-faint)' }}>{fmtDt(r.created_at)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
          </>
        )}
      </Section>

      {activityUser && <UserActivityPanel user={activityUser} onClose={() => setActivityUser(null)} />}

      {(creating || edit) && (
        <UserEditor user={edit} depts={depts} roles={roles} canGrantSuper={isSuper}
          onClose={() => { setCreating(false); setEdit(null) }}
          onSaved={() => { setCreating(false); setEdit(null); reload() }} />
      )}
    </div>
  )
}

function UserEditor({ user, depts, roles, canGrantSuper, onClose, onSaved }: {
  user: AppUser | null; depts: Department[]; roles: Role[]; canGrantSuper: boolean; onClose: () => void; onSaved: () => void
}) {
  // Роль «superadmin» в выборе показываем только тому, кто вправе её выдавать.
  const shownRoles = roles.filter((r) => r.code !== 'superadmin' || canGrantSuper)
  const isNew = !user
  const [login, setLogin] = useState(user?.login || '')
  const [password, setPassword] = useState('')
  const [last, setLast] = useState(user?.last_name || '')
  const [first, setFirst] = useState(user?.first_name || '')
  const [middle, setMiddle] = useState(user?.middle_name || '')
  const [email, setEmail] = useState(user?.email || '')
  const [deptId, setDeptId] = useState(user?.department_id || '')
  const [roleIds, setRoleIds] = useState<Set<string>>(new Set(
    user ? roles.filter((r) => user.roles.includes(r.code)).map((r) => r.id) : roles.filter((r) => r.code === 'user').map((r) => r.id)))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [policy, setPolicy] = useState<PasswordPolicy>({ min_length: 8, require_complexity: true })
  useEffect(() => { getPasswordPolicy().then(setPolicy) }, [])
  const pwErr = (isNew && password) ? checkPassword(password, policy, login) : null
  const toggle = (id: string) => setRoleIds((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  async function save() {
    setErr(null)
    if (isNew && !login.trim()) { setErr('Укажите логин'); return }
    if (isNew) { const v = checkPassword(password, policy, login); if (v) { setErr(v); return } }
    setBusy(true)
    try {
      const common = { last_name: last.trim() || undefined, first_name: first.trim() || undefined, middle_name: middle.trim() || undefined, email: email.trim() || undefined, department_id: deptId || undefined, role_ids: [...roleIds] }
      if (isNew) await createUser({ login: login.trim(), password, ...common })
      else await updateUser(user!.id, { ...common, department_id: deptId || null })
      onSaved()
    } catch (e) { setErr((e as Error).message); setBusy(false) }
  }

  return (
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{isNew ? 'Новый пользователь' : `Изменить: ${user!.login}`}</div>
          <button style={{ ...xBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          {isNew && <L t="Логин *"><input style={input} value={login} onChange={(e) => setLogin(e.target.value)} /></L>}
          {isNew && <L t="Временный пароль *"><input style={{ ...input, borderColor: pwErr ? '#d99' : undefined }} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={`минимум ${policy.min_length}, буквы+цифры`} /></L>}
          {isNew && <div style={{ gridColumn: '1 / -1', fontSize: 12, color: pwErr ? 'var(--danger)' : 'var(--text-muted)', marginTop: -4 }}>{pwErr || passwordHint(policy)}</div>}
          <L t="Фамилия"><input style={input} value={last} onChange={(e) => setLast(e.target.value)} /></L>
          <L t="Имя"><input style={input} value={first} onChange={(e) => setFirst(e.target.value)} /></L>
          <L t="Отчество"><input style={input} value={middle} onChange={(e) => setMiddle(e.target.value)} /></L>
          <L t="Email"><input style={input} value={email} onChange={(e) => setEmail(e.target.value)} /></L>
          <L t="Отдел"><select style={input} value={deptId} onChange={(e) => setDeptId(e.target.value)}>
            <option value="">— без отдела —</option>
            {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select></L>
        </div>
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Роли</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {shownRoles.map((r) => (
              <label key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13 }}
                title={r.code === 'superadmin' ? 'Полный доступ ко всем пользователям, включая администраторов' : undefined}>
                <input type="checkbox" checked={roleIds.has(r.id)} onChange={() => toggle(r.id)} />{r.name}
              </label>
            ))}
          </div>
        </div>
        {isNew && <div style={{ fontSize: 12, color: 'var(--warn)', marginTop: 8 }}>Пользователь сменит временный пароль при первом входе.</div>}
        {err && <div style={{ color: 'var(--danger)', fontSize: 13, marginTop: 8 }}>{err}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
          <button style={{ ...btn, marginLeft: 'auto' }} disabled={busy} onClick={save}>{busy ? 'Сохранение…' : 'Сохранить'}</button>
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div style={{ marginBottom: 24 }}><h3 style={{ fontSize: 15, margin: '0 0 10px' }}>{title}</h3>{children}</div>
}


// «Личный кабинет» пользователя (волна B): входы, действия из аудита и
// комментарии в одном месте — вместо трёх разных экранов. Доступ как у
// /audit (superadmin всегда, admin — по гранту), поэтому 403 показываем как
// понятное сообщение, а не общую ошибку.
function UserActivityPanel({ user, onClose }: { user: AppUser; onClose: () => void }) {
  // Две вкладки, а не один свиток: активность и доступ отвечают на разные
  // вопросы («что человек делал» и «что ему видно»), и грузятся они разными
  // правами — активность требует гранта аудита, доступ нет. Общий экран
  // означал бы, что администратор без гранта аудита не доберётся и до доступов.
  const [tab, setTab] = useState<'activity' | 'access'>('activity')
  return (
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 760 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>
            📊 Кабинет: {user.login}{user.full_name ? ` (${user.full_name})` : ''}
          </div>
          <button style={{ ...xBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
          <button style={tab === 'activity' ? tabOn : tabOff} onClick={() => setTab('activity')}>Активность</button>
          <button style={tab === 'access' ? tabOn : tabOff} onClick={() => setTab('access')}>🔒 Доступ к дашбордам</button>
        </div>
        {tab === 'activity' ? <UserCard userId={user.id} /> : <UserAccessPanel userId={user.id} />}
      </div>
    </div>
  )
}

const tabOff: React.CSSProperties = {
  height: 30, padding: '0 14px', borderRadius: 8, fontSize: 13, cursor: 'pointer',
  border: '1px solid var(--border-strong)', background: 'var(--surface)', color: 'var(--text-2)',
}
const tabOn: React.CSSProperties = {
  ...tabOff, border: '1px solid var(--accent)', background: 'var(--accent)', color: 'var(--on-accent)',
}

function L({ t, children }: { t: string; children: React.ReactNode }) {
  return <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12, color: 'var(--text-muted)' }}>{t}{children}</label>
}

const input: React.CSSProperties = { height: 34, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13 }
const btn: React.CSSProperties = { height: 34, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer' }
const linkBtn: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: '0 6px 0 0' }
const roleBadge: React.CSSProperties = { display: 'inline-block', margin: '1px 4px 1px 0', padding: '1px 8px', borderRadius: 8, background: 'var(--surface-3)', color: 'var(--text-2)', fontSize: 12 }
const superBadge: React.CSSProperties = { ...roleBadge, background: 'var(--accent)', color: 'var(--on-accent)', fontWeight: 600 }
const chip: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, background: 'var(--accent-weak-bg)', color: 'var(--accent)', padding: '4px 10px', borderRadius: 12, fontSize: 13 }
const xBtn: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--danger)', cursor: 'pointer', padding: 0 }
const th: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '6px 10px', background: 'var(--surface-2)', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600 }
const td: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '6px 10px' }
const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 13 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60, padding: 20 }
const dialog: React.CSSProperties = { background: 'var(--surface)', borderRadius: 14, padding: 22, width: 560, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }
