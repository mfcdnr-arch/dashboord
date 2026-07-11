import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api'

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e) => setError(String(e)))
  }, [])

  const ok = health?.status === 'ok'

  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <div
          style={{
            width: 32, height: 32, borderRadius: 8, background: '#2f5496',
            color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700,
          }}
        >
          D
        </div>
        <h1 style={{ fontSize: 20, margin: 0 }}>Dashbord</h1>
        <span style={{ marginLeft: 'auto', fontSize: 13, padding: '4px 10px', borderRadius: 12,
          background: ok ? '#e1f5ee' : '#fcebeb', color: ok ? '#0f6e56' : '#a32d2d' }}>
          API: {error ? 'недоступен' : health ? `${health.status} · БД ${health.db}` : '…'}
        </span>
      </header>

      <p style={{ color: '#6b7280', marginBottom: 24 }}>
        Каркас интерфейса. Две зоны появятся здесь по мере разработки.
      </p>

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
