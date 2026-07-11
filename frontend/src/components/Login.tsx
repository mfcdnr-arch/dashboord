import { useState, type FormEvent } from 'react'
import { login, setToken } from '../api'

export default function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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
    <div style={wrap}>
      <form onSubmit={submit} style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
          <div style={logo}>D</div>
          <div>
            <h1 style={{ fontSize: 20, margin: 0 }}>Dashboard</h1>
            <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>ГБУ «МФЦ ДНР»</div>
          </div>
        </div>
        <label style={label}>Логин</label>
        <input
          style={input}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />
        <label style={label}>Пароль</label>
        <input
          style={input}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <div style={errBox}>{error}</div>}
        <button style={button} disabled={busy || !username || !password}>
          {busy ? 'Вход…' : 'Войти'}
        </button>
      </form>
    </div>
  )
}

const wrap: React.CSSProperties = {
  minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
  fontFamily: 'system-ui, sans-serif', padding: 24,
}
const card: React.CSSProperties = {
  width: 320, border: '1px solid #e5e7eb', borderRadius: 12, padding: 24, display: 'flex', flexDirection: 'column',
}
const logo: React.CSSProperties = {
  width: 32, height: 32, borderRadius: 8, background: '#2f5496', color: '#fff',
  display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700,
}
const label: React.CSSProperties = { fontSize: 13, color: '#6b7280', marginBottom: 4 }
const input: React.CSSProperties = {
  height: 38, padding: '0 10px', border: '1px solid #d1d5db', borderRadius: 8, marginBottom: 14, fontSize: 14,
}
const button: React.CSSProperties = {
  height: 40, border: 'none', borderRadius: 8, background: '#2f5496', color: '#fff', fontSize: 15, cursor: 'pointer', marginTop: 4,
}
const errBox: React.CSSProperties = {
  background: '#fcebeb', color: '#a32d2d', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12,
}
