import { useEffect, useState } from 'react'
import { clearToken, getHealth, getMe, getToken, type Health, type Me } from './api'
import Login from './components/Login'
import ChangePassword from './components/ChangePassword'

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

function Shell({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const [health, setHealth] = useState<Health | null>(null)
  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
  }, [])
  const ok = health?.status === 'ok'

  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <div style={{ width: 32, height: 32, borderRadius: 8, background: '#2f5496', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700 }}>
          D
        </div>
        <h1 style={{ fontSize: 20, margin: 0 }}>Dashbord</h1>
        <span style={{ marginLeft: 'auto', fontSize: 13, padding: '4px 10px', borderRadius: 12, background: ok ? '#e1f5ee' : '#fcebeb', color: ok ? '#0f6e56' : '#a32d2d' }}>
          API: {health ? `${health.status} · БД ${health.db}` : '…'}
        </span>
      </header>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24, fontSize: 14 }}>
        <span style={{ color: '#6b7280' }}>Вы вошли как</span>
        <strong>{me.full_name || me.login}</strong>
        <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 10, background: '#eef' , color: '#2f5496' }}>
          {me.roles.join(', ')}
        </span>
        <button onClick={onLogout} style={{ marginLeft: 'auto', height: 32, padding: '0 12px', border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', cursor: 'pointer', fontSize: 13 }}>
          Выйти
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <section style={{ border: '1px solid #e5e7eb', borderRadius: 12, padding: 16 }}>
          <h2 style={{ fontSize: 16, marginTop: 0 }}>Панель управления</h2>
          <p style={{ color: '#6b7280', fontSize: 14 }}>
            Объекты, документы, метрики, конструктор, модерация, пользователи, отчёты.
          </p>
        </section>
        <section style={{ border: '1px solid #e5e7eb', borderRadius: 12, padding: 16 }}>
          <h2 style={{ fontSize: 16, marginTop: 0 }}>Viewer</h2>
          <p style={{ color: '#6b7280', fontSize: 14 }}>
            Просмотр разрешённых дашбордов, фильтры, раскрытие значений.
          </p>
        </section>
      </div>
    </div>
  )
}
