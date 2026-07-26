import { useEffect, useState } from 'react'
import {
  autoBuildDashboard, createDashboard, createDepartment, createFolder, createObject, createUser,
  dismissSetup, getSetupStatus, listDepartments, listFolders, listObjects, listRoles, uploadDocument,
  type Department, type Folder, type Obj, type Role, type SetupStatus,
} from '../api'

// Мастер первичной настройки: проводит администратора через заведение отделов,
// пользователей, первого объекта, ЗАГРУЗКУ ДАННЫХ и СБОРКУ ДАШБОРДА — целиком
// внутри мастера, чтобы нетехнический сотрудник МФЦ запустил систему «за руку».
// Показывается автоматически на свежей установке (структурно пусто) и пока не
// закрыт — флаг серверный (organizations.setup_dismissed), переживает смену
// браузера. Тяжёлые действия переиспользуют готовые API (без дублирования).

type StepKey = 'welcome' | 'departments' | 'users' | 'object' | 'data' | 'dashboard' | 'done'
const STEPS: StepKey[] = ['welcome', 'departments', 'users', 'object', 'data', 'dashboard', 'done']

export default function SetupWizard({ onClose, onNavigate }: {
  onClose: () => void
  onNavigate: (section: string) => void
}) {
  const [i, setI] = useState(0)
  const step = STEPS[i]
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [depts, setDepts] = useState<Department[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [objects, setObjects] = useState<Obj[]>([])
  const [err, setErr] = useState<string | null>(null)

  const refresh = () => Promise.all([
    getSetupStatus().then(setStatus).catch(() => {}),
    listDepartments().then(setDepts).catch(() => {}),
    listObjects().then(setObjects).catch(() => {}),
  ])
  useEffect(() => { refresh(); listRoles().then(setRoles).catch(() => {}) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Закрытие мастера ставит серверный флаг (не всплывёт снова). Навигация в
  // раздел — тоже (пользователь уже вовлечён), чтобы не мешать.
  const close = async () => { try { await dismissSetup() } catch { /* noop */ } onClose() }
  const goto = async (section: string) => { try { await dismissSetup() } catch { /* noop */ } onNavigate(section) }
  const next = () => setI((n) => Math.min(n + 1, STEPS.length - 1))
  const back = () => setI((n) => Math.max(n - 1, 0))
  const run = async (fn: () => Promise<unknown>) => { setErr(null); try { await fn(); await refresh() } catch (e) { setErr((e as Error).message) } }

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
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>🧭 Мастер настройки</div>
          <button style={{ ...xBtn, marginLeft: 'auto' }} onClick={close} title="Закрыть (больше не всплывёт; открыть можно кнопкой 🧭)">✕</button>
        </div>
        <div style={{ display: 'flex', gap: 5, marginBottom: 16 }}>
          {STEPS.map((s, idx) => (
            <div key={s} style={{ flex: 1, height: 4, borderRadius: 2, background: idx <= i ? 'var(--accent)' : 'var(--surface-3)' }} />
          ))}
        </div>

        {err && <div style={errBox}>{err}</div>}

        {step === 'welcome' && (
          <div>
            <p style={p}>Добро пожаловать в аналитический портал ГБУ «МФЦ ДНР». Мастер поможет
              подготовить систему к работе за несколько шагов — прямо здесь, не покидая окна.
              Всё можно изменить позже в разделах.</p>
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
          <StepDepartments depts={depts} onAdd={(name) => run(() => createDepartment(name))} />
        )}

        {step === 'users' && (
          <StepUsers roles={roles} depts={depts} usersCount={status?.users ?? 0}
            onGoto={() => goto('users')}
            onAdd={(b) => run(() => createUser(b))} />
        )}

        {step === 'object' && (
          <StepObject objectsCount={status?.objects ?? 0}
            onAdd={(name) => run(() => createObject(name))} />
        )}

        {step === 'data' && (
          <StepData objects={objects} docsCount={status?.documents ?? 0}
            onCreateFolder={(objId, name) => createFolder(objId, name)}
            onUpload={(folderId, file, date) => run(() => uploadDocument(folderId, file, date))}
            onGoto={() => goto('objects')} />
        )}

        {step === 'dashboard' && (
          <StepDashboard objects={objects} dashCount={status?.dashboards ?? 0}
            onAuto={(objId) => run(() => autoBuildDashboard(objId))}
            onCreateEmpty={(name) => run(() => createDashboard(name))}
            onGoto={() => goto('dashboards')} />
        )}

        {step === 'done' && (
          <div>
            <p style={p}>Готово! Настройка завершена ({doneCount}/5). Открыть можно снова кнопкой
              «🧭 Настройка» в шапке. Приятной работы!</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button style={btnWide} onClick={() => goto('home')}>🏠 На главную (витрина показателей)</button>
              <button style={btnWide} onClick={() => goto('dashboards')}>📊 К дашбордам</button>
            </div>
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, marginTop: 20, alignItems: 'center' }}>
          {i > 0 && <button style={btnGhost} onClick={back}>← Назад</button>}
          <button style={{ ...btnGhost, color: 'var(--text-muted)' }} onClick={close}>Пропустить настройку</button>
          <div style={{ marginLeft: 'auto' }}>
            {step === 'done'
              ? <button style={btn} onClick={close}>Завершить</button>
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
        хотя бы один — к ним привязываются пользователи и данные.</p>
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
  const shownRoles = roles.filter((r) => r.code !== 'superadmin')
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

function StepObject({ objectsCount, onAdd }: { objectsCount: number; onAdd: (name: string) => Promise<void> }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const add = async () => { if (!name.trim()) return; setBusy(true); await onAdd(name.trim()); setName(''); setBusy(false) }
  return (
    <div>
      <h3 style={h3}>Шаг 3. Первый объект</h3>
      <p style={p}>Объект — то, по чему собираются данные (услуга, направление, подразделение). Внутри
        объекта заводятся папки и загружаются документы. Уже создано: <b>{objectsCount}</b>.</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
        <input style={input} placeholder="Название объекта (напр. Приём граждан)" value={name}
          onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <button style={btn} disabled={busy} onClick={add}>＋ Создать</button>
      </div>
    </div>
  )
}

function StepData({ objects, docsCount, onCreateFolder, onUpload, onGoto }: {
  objects: Obj[]; docsCount: number
  onCreateFolder: (objId: string, name: string) => Promise<Folder>
  onUpload: (folderId: string, file: File, date: string) => Promise<void>
  onGoto: () => void
}) {
  const [objId, setObjId] = useState('')
  const [folders, setFolders] = useState<Folder[]>([])
  const [folderId, setFolderId] = useState('')
  const [newFolder, setNewFolder] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [date, setDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [local, setLocal] = useState<string | null>(null)

  useEffect(() => { if (!objId && objects[0]) setObjId(objects[0].id) }, [objects]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!objId) { setFolders([]); return }
    listFolders(objId).then((f) => { setFolders(f); setFolderId(f[0]?.id || '') }).catch(() => {})
  }, [objId])

  const addFolder = async () => {
    if (!objId || !newFolder.trim()) return
    setLocal(null)
    try { const f = await onCreateFolder(objId, newFolder.trim()); setNewFolder(''); const list = await listFolders(objId); setFolders(list); setFolderId(f.id) }
    catch (e) { setLocal((e as Error).message) }
  }
  const upload = async () => {
    if (!folderId || !file || !date) { setLocal('Выберите папку, файл и отчётную дату'); return }
    setBusy(true); setLocal(null)
    try { await onUpload(folderId, file, date); setFile(null) } finally { setBusy(false) }
  }

  if (objects.length === 0) {
    return (
      <div>
        <h3 style={h3}>Шаг 4. Данные</h3>
        <p style={p}>Сначала создайте объект на предыдущем шаге — в него загружаются документы.</p>
      </div>
    )
  }
  return (
    <div>
      <h3 style={h3}>Шаг 4. Данные</h3>
      <p style={p}>Загрузите документ (Excel/PDF/CSV/Word) в папку объекта — система распознает таблицу
        и подготовит датасет. Уже загружено: <b>{docsCount}</b>.</p>
      {local && <div style={errBox}>{local}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
        <L t="Объект"><select style={input} value={objId} onChange={(e) => setObjId(e.target.value)}>
          {objects.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select></L>
        <L t="Папка"><select style={input} value={folderId} onChange={(e) => setFolderId(e.target.value)}>
          {folders.length === 0 && <option value="">— нет папок, создайте ниже —</option>}
          {folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select></L>
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <input style={{ ...input, flex: 1 }} placeholder="Новая папка (напр. Отчёты 2026)" value={newFolder}
          onChange={(e) => setNewFolder(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addFolder()} />
        <button style={btnGhost} onClick={addFolder}>＋ Папка</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10, alignItems: 'end' }}>
        <L t="Файл документа"><input type="file" style={{ fontSize: 13 }} onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></L>
        <L t="Отчётная дата"><input type="date" style={input} value={date} onChange={(e) => setDate(e.target.value)} /></L>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button style={btn} disabled={busy || !folderId || !file || !date} onClick={upload}>{busy ? 'Загрузка…' : '⤴ Загрузить документ'}</button>
        <button style={btnGhost} onClick={onGoto}>Открыть раздел «Объекты» (распознавание, маппинг) →</button>
      </div>
    </div>
  )
}

function StepDashboard({ objects, dashCount, onAuto, onCreateEmpty, onGoto }: {
  objects: Obj[]; dashCount: number
  onAuto: (objId: string) => Promise<void>
  onCreateEmpty: (name: string) => Promise<void>
  onGoto: () => void
}) {
  const [objId, setObjId] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (!objId && objects[0]) setObjId(objects[0].id) }, [objects]) // eslint-disable-line react-hooks/exhaustive-deps
  const auto = async () => { if (!objId) return; setBusy(true); await onAuto(objId); setBusy(false) }
  const empty = async () => { if (!name.trim()) return; setBusy(true); await onCreateEmpty(name.trim()); setName(''); setBusy(false) }
  return (
    <div>
      <h3 style={h3}>Шаг 5. Дашборд</h3>
      <p style={p}>Соберите первый дашборд автоматически из объекта — система сама создаст виджеты по
        загруженным данным. Уже собрано: <b>{dashCount}</b>.</p>
      {objects.length > 0 ? (
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <select style={{ ...input, flex: 1 }} value={objId} onChange={(e) => setObjId(e.target.value)}>
            {objects.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <button style={btn} disabled={busy || !objId} onClick={auto}>✨ Собрать из объекта</button>
        </div>
      ) : <p style={muted}>Сначала создайте объект и загрузите данные.</p>}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input style={{ ...input, flex: 1 }} placeholder="…или пустой дашборд по названию" value={name}
          onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && empty()} />
        <button style={btnGhost} disabled={busy || !name.trim()} onClick={empty}>Создать пустой</button>
      </div>
      <button style={{ ...btnGhost, marginTop: 10 }} onClick={onGoto}>Открыть раздел «Дашборды» (конструктор) →</button>
    </div>
  )
}

function L({ t, children }: { t: string; children: React.ReactNode }) {
  return <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12, color: 'var(--text-muted)' }}>{t}{children}</label>
}

const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 80, padding: 20 }
const dialog: React.CSSProperties = { background: 'var(--surface)', borderRadius: 16, padding: 24, width: 640, maxWidth: '96vw', maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 12px 48px rgba(0,0,0,0.25)' }
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
