import { useEffect, useState } from 'react'
import {
  createDepartment, createObject, createUser, getSetupStatus, listDepartments, listRoles,
  type Department, type Role, type SetupStatus,
} from '../api'

// Мастер первичной настройки: за несколько шагов проводит администратора через
// заведение отделов, пользователей и первого объекта — чтобы нетехнический
// сотрудник МФЦ запустил систему «за руку», без похода по разделам. Показывается
// автоматически на свежей установке; можно открыть вручную и закрыть в любой момент.
// Тяжёлые шаги (загрузка документа, сборка дашборда) — переход в нужный раздел.

const dismissKey = (login: string) => `setup_done:${login}`
export function isSetupDismissed(login: string): boolean {
  try { return localStorage.getItem(dismissKey(login)) === '1' } catch { return false }
}
function dismissSetup(login: string) {
  try { localStorage.setItem(dismissKey(login), '1') } catch { /* noop */ }
}

type StepKey = 'welcome' | 'departments' | 'users' | 'object' | 'done'
const STEPS: StepKey[] = ['welcome', 'departments', 'users', 'object', 'done']

export default function SetupWizard({ me, onClose, onNavigate }: {
  me: { login: string }
  onClose: () => void
  onNavigate: (section: string) => void
}) {
  const [i, setI] = useState(0)
  const step = STEPS[i]
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [depts, setDepts] = useState<Department[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [err, setErr] = useState<string | null>(null)

  const refresh = () => Promise.all([
    getSetupStatus().then(setStatus).catch(() => {}),
    listDepartments().then(setDepts).catch(() => {}),
  ])
  useEffect(() => { refresh(); listRoles().then(setRoles).catch(() => {}) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const close = (markDone: boolean) => { if (markDone) dismissSetup(me.login); onClose() }
  const next = () => setI((n) => Math.min(n + 1, STEPS.length - 1))
  const back = () => setI((n) => Math.max(n - 1, 0))
  const goto = (section: string) => { dismissSetup(me.login); onNavigate(section) }

  // Прогресс (для чек-листа приветствия и финала).
  const checks = status ? [
    { t: 'Отделы заведены', ok: status.departments > 0 },
    { t: 'Пользователи добавлены', ok: status.users > 2 },
    { t: 'Первый объект создан', ok: status.objects > 0 },
    { t: 'Данные загружены (документ)', ok: status.documents > 0 },
    { t: 'Дашборд собран', ok: status.dashboards > 0 },
  ] : []
  const doneCount = checks.filter((c) => c.ok).length

  return (
    <div style={overlay}>
      <div style={dialog}>
        {/* Шапка с прогрессом-точками */}
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>🧭 Мастер настройки</div>
          <button style={{ ...xBtn, marginLeft: 'auto' }} onClick={() => close(false)} title="Закрыть (можно вернуться позже)">✕</button>
        </div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
          {STEPS.map((s, idx) => (
            <div key={s} style={{ flex: 1, height: 4, borderRadius: 2, background: idx <= i ? 'var(--accent)' : 'var(--surface-3)' }} />
          ))}
        </div>

        {err && <div style={errBox}>{err}</div>}

        {step === 'welcome' && (
          <div>
            <p style={p}>Добро пожаловать в аналитический портал ГБУ «МФЦ ДНР». Этот мастер поможет
              подготовить систему к работе за несколько шагов. Всё можно изменить позже в разделах.</p>
            <div style={card}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Готовность ({doneCount}/5)</div>
              {checks.map((c) => (
                <div key={c.t} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, padding: '3px 0' }}>
                  <span style={{ color: c.ok ? 'var(--success)' : 'var(--text-faint)' }}>{c.ok ? '✓' : '○'}</span>
                  <span style={{ color: c.ok ? 'var(--text)' : 'var(--text-muted)' }}>{c.t}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {step === 'departments' && (
          <StepDepartments depts={depts} onAdd={async (name) => {
            setErr(null)
            try { await createDepartment(name); await refresh() } catch (e) { setErr((e as Error).message) }
          }} />
        )}

        {step === 'users' && (
          <StepUsers roles={roles} depts={depts} usersCount={status?.users ?? 0}
            onGoto={() => goto('users')}
            onAdd={async (b) => {
              setErr(null)
              try { await createUser(b); await refresh() } catch (e) { setErr((e as Error).message) }
            }} />
        )}

        {step === 'object' && (
          <StepObject objectsCount={status?.objects ?? 0}
            onGoto={() => goto('objects')}
            onAdd={async (name) => {
              setErr(null)
              try { await createObject(name); await refresh() } catch (e) { setErr((e as Error).message) }
            }} />
        )}

        {step === 'done' && (
          <div>
            <p style={p}>Готово! Базовая настройка завершена ({doneCount}/5). Дальше — загрузите данные
              в объект и соберите первый дашборд.</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button style={btnWide} onClick={() => goto('objects')}>📄 Загрузить документ (раздел «Объекты»)</button>
              <button style={btnWide} onClick={() => goto('dashboards')}>📊 Собрать дашборд (раздел «Дашборды»)</button>
            </div>
          </div>
        )}

        {/* Навигация мастера */}
        <div style={{ display: 'flex', gap: 8, marginTop: 20, alignItems: 'center' }}>
          {i > 0 && <button style={btnGhost} onClick={back}>← Назад</button>}
          <button style={{ ...btnGhost, color: 'var(--text-muted)' }} onClick={() => close(true)}>Пропустить настройку</button>
          <div style={{ marginLeft: 'auto' }}>
            {step === 'done'
              ? <button style={btn} onClick={() => close(true)}>Завершить</button>
              : <button style={btn} onClick={next}>Далее →</button>}
          </div>
        </div>
      </div>
    </div>
  )
}

function StepDepartments({ depts, onAdd }: { depts: Department[]; onAdd: (name: string) => Promise<void> }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const add = async () => { if (!name.trim()) return; setBusy(true); await onAdd(name.trim()); setName(''); setBusy(false) }
  return (
    <div>
      <h3 style={h3}>Шаг 1. Отделы</h3>
      <p style={p}>Отделы (подразделения/районы) нужны для разграничения доступа и отчётности. Заведите
        хотя бы один — потом к ним привязываются пользователи и данные.</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <input style={input} placeholder="Название отдела (напр. Центр «Ленинский»)" value={name}
          onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <button style={btn} disabled={busy} onClick={add}>＋ Добавить</button>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {depts.length === 0 && <span style={muted}>Пока нет отделов.</span>}
        {depts.map((d) => <span key={d.id} style={chip}>{d.name}</span>)}
      </div>
    </div>
  )
}

function StepUsers({ roles, depts, usersCount, onAdd, onGoto }: {
  roles: Role[]; depts: Department[]; usersCount: number
  onAdd: (b: { login: string; password: string; role_ids: string[]; department_id?: string }) => Promise<void>
  onGoto: () => void
}) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const userRole = roles.find((r) => r.code === 'user')
  const [roleId, setRoleId] = useState('')
  const [deptId, setDeptId] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (userRole && !roleId) setRoleId(userRole.id) }, [roles]) // eslint-disable-line react-hooks/exhaustive-deps
  const shownRoles = roles.filter((r) => r.code !== 'superadmin') // выдачу superadmin — не из мастера
  const add = async () => {
    if (!login.trim() || !password) return
    setBusy(true)
    await onAdd({ login: login.trim(), password, role_ids: roleId ? [roleId] : [], department_id: deptId || undefined })
    setBusy(false); setLogin(''); setPassword('')
  }
  return (
    <div>
      <h3 style={h3}>Шаг 2. Пользователи</h3>
      <p style={p}>Заведите сотрудников. Пароль — временный: при первом входе система попросит сменить.
        Уже заведено: <b>{usersCount}</b>.</p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
        <input style={input} placeholder="Логин" value={login} onChange={(e) => setLogin(e.target.value)} />
        <input style={input} placeholder="Временный пароль (мин. 8, буквы+цифры)" value={password} onChange={(e) => setPassword(e.target.value)} />
        <select style={input} value={roleId} onChange={(e) => setRoleId(e.target.value)}>
          {shownRoles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <select style={input} value={deptId} onChange={(e) => setDeptId(e.target.value)}>
          <option value="">— без отдела —</option>
          {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button style={btn} disabled={busy} onClick={add}>＋ Добавить пользователя</button>
        <button style={btnGhost} onClick={onGoto}>Открыть раздел «Пользователи» →</button>
      </div>
    </div>
  )
}

function StepObject({ objectsCount, onAdd, onGoto }: {
  objectsCount: number; onAdd: (name: string) => Promise<void>; onGoto: () => void
}) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const add = async () => { if (!name.trim()) return; setBusy(true); await onAdd(name.trim()); setName(''); setBusy(false) }
  return (
    <div>
      <h3 style={h3}>Шаг 3. Первый объект</h3>
      <p style={p}>Объект — это то, по чему собираются данные (услуга, направление, подразделение). Внутри
        объекта заводятся папки и загружаются документы. Уже создано: <b>{objectsCount}</b>.</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <input style={input} placeholder="Название объекта (напр. Приём граждан)" value={name}
          onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <button style={btn} disabled={busy} onClick={add}>＋ Создать</button>
      </div>
      <button style={btnGhost} onClick={onGoto}>Открыть раздел «Объекты» (папки, загрузка данных) →</button>
    </div>
  )
}

const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 80, padding: 20 }
const dialog: React.CSSProperties = { background: 'var(--surface)', borderRadius: 16, padding: 24, width: 620, maxWidth: '96vw', maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 12px 48px rgba(0,0,0,0.25)' }
const card: React.CSSProperties = { border: '1px solid var(--border)', borderRadius: 12, padding: 14, background: 'var(--surface-2)' }
const p: React.CSSProperties = { fontSize: 14, color: 'var(--text-2)', lineHeight: 1.5, margin: '0 0 14px' }
const h3: React.CSSProperties = { fontSize: 16, margin: '0 0 8px' }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14, background: 'var(--surface)' }
const btn: React.CSSProperties = { height: 36, padding: '0 16px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
const btnWide: React.CSSProperties = { ...btn, height: 42, textAlign: 'left' }
const btnGhost: React.CSSProperties = { height: 36, padding: '0 14px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text-2)', fontSize: 14, cursor: 'pointer' }
const xBtn: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18 }
const chip: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', background: 'var(--accent-weak-bg)', color: 'var(--accent)', padding: '4px 10px', borderRadius: 12, fontSize: 13 }
const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 13 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
