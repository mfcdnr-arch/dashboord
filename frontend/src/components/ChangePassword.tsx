import { useEffect, useState, type FormEvent } from 'react'
import { changePassword, checkPassword, getPasswordPolicy, passwordHint, type PasswordPolicy } from '../api'

export default function ChangePassword({
  token,
  onDone,
}: {
  token: string
  onDone: () => void
}) {
  const [pw1, setPw1] = useState('')
  const [pw2, setPw2] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [policy, setPolicy] = useState<PasswordPolicy>({ min_length: 8, require_complexity: true })
  useEffect(() => { getPasswordPolicy().then(setPolicy) }, [])
  const pwErr = pw1 ? checkPassword(pw1, policy) : null

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const v = checkPassword(pw1, policy)
    if (v) { setError(v); return }
    if (pw1 !== pw2) {
      setError('Пароли не совпадают')
      return
    }
    setBusy(true)
    try {
      await changePassword(token, pw1)
      onDone()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={wrap}>
      <form onSubmit={submit} style={card}>
        <h1 style={{ fontSize: 18, marginTop: 0 }}>Смена пароля</h1>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 0 }}>
          При первом входе необходимо задать новый пароль.
        </p>
        <label style={label}>Новый пароль</label>
        <input style={{ ...input, marginBottom: 4, borderColor: pwErr ? '#d99' : 'var(--border-strong)' }} type="password" value={pw1} onChange={(e) => setPw1(e.target.value)} autoFocus />
        <div style={{ fontSize: 12, color: pwErr ? 'var(--danger)' : 'var(--text-muted)', marginBottom: 10 }}>{pwErr || passwordHint(policy)}</div>
        <label style={label}>Повторите пароль</label>
        <input style={input} type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} />
        {error && <div style={errBox}>{error}</div>}
        <button style={button} disabled={busy || !pw1 || !pw2}>
          {busy ? 'Сохранение…' : 'Сохранить'}
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
  width: 320, border: '1px solid var(--border)', borderRadius: 12, padding: 24, display: 'flex', flexDirection: 'column',
}
const label: React.CSSProperties = { fontSize: 13, color: 'var(--text-muted)', marginBottom: 4 }
const input: React.CSSProperties = {
  height: 38, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, marginBottom: 14, fontSize: 14,
}
const button: React.CSSProperties = {
  height: 40, border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 15, cursor: 'pointer', marginTop: 4,
}
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12,
}
