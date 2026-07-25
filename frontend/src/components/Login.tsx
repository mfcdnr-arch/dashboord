import { useEffect, useState, type FormEvent } from 'react'
import { login, setToken } from '../api'

// Стартовая страница входа. Двухпанельная: слева — о портале, справа — форма.
// БРЕНД: цвета/название/эмблема вынесены в BRAND ниже — под будущий брендбук МФЦ
// достаточно поменять значения (или заменить эмблему на <img> с логотипом).
const BRAND = {
  primary: 'var(--accent)',
  primaryDark: '#1e3a6b',
  accent: '#c69b2f',
  orgShort: 'ГБУ «МФЦ ДНР»',
  orgFull: 'Многофункциональный центр предоставления государственных и муниципальных услуг',
  portal: 'Аналитический портал',
}

const FEATURES: { icon: string; title: string; text: string }[] = [
  { icon: '📊', title: 'Дашборды и показатели', text: 'KPI, план-факт и динамика в наглядных панелях — картина по услугам и подразделениям на одном экране.' },
  { icon: '🔍', title: 'Прозрачность данных', text: 'По каждому показателю видно, из чего он собран: формула, источник, первичные строки.' },
  { icon: '📈', title: 'Аналитика для решений', text: 'Сравнение периодов и подразделений, тренды, цели и бенчмарки — основа управленческих решений.' },
  { icon: '📄', title: 'Отчёты и выгрузки', text: 'Готовые отчёты, экспорт в Excel/PDF и журналы аудита — для контроля и отчётности.' },
]

function useNarrow(max = 900): boolean {
  const [n, setN] = useState(() => typeof window !== 'undefined' && window.innerWidth <= max)
  useEffect(() => {
    const on = () => setN(window.innerWidth <= max)
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [max])
  return n
}

export default function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const narrow = useNarrow()

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const token = await login(username.trim(), password)
      setToken(token)
      onLogin(token)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ ...page, flexDirection: narrow ? 'column' : 'row' }}>
      {/* Левая панель — о портале */}
      <div style={{ ...hero, padding: narrow ? '32px 24px' : '56px 52px', minHeight: narrow ? undefined : '100vh' }}>
        <div style={heroInner}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: narrow ? 20 : 40 }}>
            <div style={emblem}>D</div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: 0.3 }}>Dashboard</div>
              <div style={{ fontSize: 12, opacity: 0.8 }}>{BRAND.orgShort}</div>
            </div>
          </div>

          <h1 style={{ fontSize: narrow ? 26 : 38, lineHeight: 1.15, margin: '0 0 14px', fontWeight: 800 }}>
            {BRAND.portal}<br />
            <span style={{ color: '#ffe0a3' }}>для управленческих решений</span>
          </h1>
          <p style={{ fontSize: narrow ? 14 : 16, lineHeight: 1.55, opacity: 0.92, margin: '0 0 28px', maxWidth: 520 }}>
            Единое пространство данных {BRAND.orgShort}: показатели работы центра, услуги, нагрузка и
            качество обслуживания — собраны, проверены и представлены так, чтобы решения принимались
            на основе фактов, а не догадок.
          </p>

          {!narrow && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, maxWidth: 620 }}>
              {FEATURES.map((f) => (
                <div key={f.title} style={featCard}>
                  <div style={{ fontSize: 22, marginBottom: 6 }}>{f.icon}</div>
                  <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 3 }}>{f.title}</div>
                  <div style={{ fontSize: 12.5, lineHeight: 1.45, opacity: 0.85 }}>{f.text}</div>
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: narrow ? 20 : 40, fontSize: 12, opacity: 0.7 }}>{BRAND.orgFull}</div>
        </div>
      </div>

      {/* Правая панель — форма входа */}
      <div style={{ ...formSide, padding: narrow ? '28px 24px 44px' : 24, minHeight: narrow ? undefined : '100vh' }}>
        <form onSubmit={submit} style={card}>
          <h2 style={{ fontSize: 20, margin: '0 0 4px' }}>Вход в систему</h2>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 20px' }}>Введите логин и пароль, выданные администратором.</p>
          <label style={label}>Логин</label>
          <input style={input} value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          <label style={label}>Пароль</label>
          <input style={input} type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          {error && <div style={errBox}>{error}</div>}
          <button style={{ ...button, opacity: busy || !username || !password ? 0.6 : 1 }} disabled={busy || !username || !password}>
            {busy ? 'Вход…' : 'Войти'}
          </button>
          <div style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 16, textAlign: 'center' }}>
            Нет доступа? Обратитесь к администратору системы.
          </div>
        </form>
      </div>
    </div>
  )
}

const page: React.CSSProperties = { minHeight: '100vh', display: 'flex', fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif', color: 'var(--text)' }
const hero: React.CSSProperties = {
  flex: 1.25, color: 'var(--on-accent)', display: 'flex', alignItems: 'center',
  background: `radial-gradient(1200px 600px at 15% -10%, ${BRAND.primary} 0%, ${BRAND.primaryDark} 55%, #16233f 100%)`,
}
const heroInner: React.CSSProperties = { width: '100%', maxWidth: 680 }
const emblem: React.CSSProperties = {
  width: 44, height: 44, borderRadius: 12, background: 'rgba(255,255,255,0.14)', border: '1px solid rgba(255,255,255,0.25)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 20,
}
const featCard: React.CSSProperties = {
  background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.14)', borderRadius: 12, padding: '14px 16px',
}
const formSide: React.CSSProperties = { flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f4f6fa' }
const card: React.CSSProperties = {
  width: '100%', maxWidth: 360, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 16,
  padding: 28, display: 'flex', flexDirection: 'column', boxShadow: '0 10px 40px rgba(20,35,76,0.08)',
}
const label: React.CSSProperties = { fontSize: 13, color: 'var(--text-muted)', marginBottom: 4 }
const input: React.CSSProperties = { height: 40, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 9, marginBottom: 14, fontSize: 14 }
const button: React.CSSProperties = { height: 42, border: 'none', borderRadius: 9, background: BRAND.primary, color: 'var(--on-accent)', fontSize: 15, fontWeight: 600, cursor: 'pointer', marginTop: 4 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
