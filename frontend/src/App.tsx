import { useEffect, useState } from 'react'
import { clearToken, getHealth, getMe, getToken, type Health, type Me } from './api'
import Login from './components/Login'
import ChangePassword from './components/ChangePassword'
import ObjectsPage from './components/ObjectsPage'
import MetricsPage from './components/MetricsPage'
import DashboardsPage from './components/DashboardsPage'
import HomePage from './components/HomePage'
import UsersPage from './components/UsersPage'
import ReportsPage from './components/ReportsPage'
import AuditPage from './components/AuditPage'

export default function App() {
  const [token, setToken] = useState<string | null>(getToken())
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState<boolean>(!!getToken())

  async function loadMe(t: string) {
    setLoading(true)
    try {
      setMe(await getMe(t))
    } catch {
      clearToken()
      setToken(null)
      setMe(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (token) loadMe(token)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function onLogin(t: string) {
    setToken(t)
    loadMe(t)
  }
  function onLogout() {
    clearToken()
    setToken(null)
    setMe(null)
  }

  if (!token) return <Login onLogin={onLogin} />
  if (loading) return <Centered>Загрузка…</Centered>
  if (me?.must_change_password) return <ChangePassword token={token} onDone={() => loadMe(token)} />
  return <Shell me={me!} onLogout={onLogout} />
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'system-ui, sans-serif', color: '#6b7280' }}>
      {children}
    </div>
  )
}

const NAV = [
  { key: 'home', label: 'Главная', ready: true },
  { key: 'objects', label: 'Объекты', ready: true },
  { key: 'metrics', label: 'Метрики', ready: true },
  { key: 'dashboards', label: 'Дашборды', ready: true },
  { key: 'moderation', label: 'Модерация', ready: false },
  { key: 'users', label: 'Пользователи', ready: true },
  { key: 'audit', label: 'Аудит', ready: true, adminOnly: true },
  { key: 'reports', label: 'Отчёты', ready: true },
]

function Shell({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const [health, setHealth] = useState<Health | null>(null)
  const [section, setSection] = useState('home')
  const [openDash, setOpenDash] = useState<string | null>(null)
  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
  }, [])
  const ok = health?.status === 'ok'
  const canManage = me.roles.includes('admin') || me.roles.includes('moderator')
  const isAdmin = me.roles.includes('admin')
  const nav = NAV.filter((n) => !n.adminOnly || isAdmin)

  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', minHeight: '100vh' }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 20px', borderBottom: '1px solid #e5e7eb' }}>
        <div style={{ width: 30, height: 30, borderRadius: 8, background: '#2f5496', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700 }}>D</div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 600, lineHeight: 1 }}>Dashboard</div>
          <div style={{ fontSize: 11, color: '#6b7280' }}>ГБУ «МФЦ ДНР»</div>
        </div>
        <span style={{ marginLeft: 'auto', fontSize: 13, padding: '4px 10px', borderRadius: 12, background: ok ? '#e1f5ee' : '#fcebeb', color: ok ? '#0f6e56' : '#a32d2d' }}>
          API: {health ? `${health.status} · БД ${health.db}` : '…'}
        </span>
        <span style={{ fontSize: 13 }}><strong>{me.full_name || me.login}</strong></span>
        <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: '#eef', color: '#2f5496' }}>{me.roles.join(', ')}</span>
        <button onClick={onLogout} style={{ height: 32, padding: '0 12px', border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', cursor: 'pointer', fontSize: 13 }}>Выйти</button>
      </header>

      <div style={{ display: 'flex', minHeight: 'calc(100vh - 55px)' }}>
        <nav style={{ width: 200, borderRight: '1px solid #e5e7eb', padding: 12 }}>
          {nav.map((n) => (
            <button
              key={n.key}
              onClick={() => { setOpenDash(null); setSection(n.key) }}
              style={{
                display: 'block', width: '100%', textAlign: 'left', padding: '8px 12px', marginBottom: 4,
                border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 14,
                background: section === n.key ? '#eef' : 'transparent',
                color: section === n.key ? '#2f5496' : n.ready ? '#111827' : '#9aa4b2',
              }}
            >
              {n.label}{!n.ready && <span style={{ fontSize: 11 }}> · в разработке</span>}
            </button>
          ))}
        </nav>

        <main style={{ flex: 1, padding: 24, maxWidth: 900 }}>
          {section === 'home' ? (
            <HomePage me={me} canManage={canManage} onOpenDashboard={(id) => { setOpenDash(id); setSection('dashboards') }} />
          ) : section === 'objects' ? (
            <ObjectsPage canManage={canManage} />
          ) : section === 'metrics' ? (
            <MetricsPage canManage={canManage} />
          ) : section === 'dashboards' ? (
            <DashboardsPage canManage={canManage} initialDashboardId={openDash} />
          ) : section === 'users' ? (
            <UsersPage me={me} />
          ) : section === 'reports' ? (
            <ReportsPage me={me} />
          ) : section === 'audit' ? (
            <AuditPage me={me} />
          ) : (
            <div style={{ color: '#9aa4b2' }}>Раздел «{NAV.find((n) => n.key === section)?.label}» в разработке.</div>
          )}
        </main>
      </div>
    </div>
  )
}
