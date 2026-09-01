import { useEffect, useState, type FormEvent } from 'react'
import { login, setToken, submitBlockedAppeal, type LoginError } from '../api'
import Logo from './Logo'
import { LoginBackdrop } from './Art'
import ThemeToggle from './ThemeToggle'

/**
 * Переключатель темы в углу страницы входа.
 *
 * До входа тема была недоступна: человеку, которому нужна тёмная (или который
 * ей просто пользуется), первый экран всё равно светил белым, и переключить он
 * мог только уже войдя. Выбор хранится в браузере, авторизация для него не нужна.
 */
function ThemeCorner() {
  return (
    <div style={{ position: 'absolute', top: 16, right: 16, zIndex: 2 }}>
      <ThemeToggle />
    </div>
  )
}

// Стартовая страница входа. Двухпанельная: слева — о портале, справа — форма.
// БРЕНД: цвета/название/эмблема вынесены в BRAND ниже — под будущий брендбук МФЦ
// достаточно поменять значения (или заменить эмблему на <img> с логотипом).
const BRAND = {
  primary: 'var(--accent)',   // фирменный красный «Мои Документы»
  primaryDark: '#a5361f',     // глубокий красный
  accent: '#c39367',          // фирменный бежевый
  orgShort: 'ГБУ «МФЦ ДНР»',
  orgFull: 'Многофункциональный центр предоставления государственных и муниципальных услуг',
  portal: 'Аналитический портал',
}

const FEATURES: { icon: string; title: string; text: string }[] = [
  { icon: 'dashboards', title: 'Дашборды и показатели', text: 'KPI, план-факт и динамика в наглядных панелях — картина по услугам и подразделениям на одном экране.' },
  { icon: 'transparency', title: 'Прозрачность данных', text: 'По каждому показателю видно, из чего он собран: формула, источник, первичные строки.' },
  { icon: 'analytics', title: 'Аналитика для решений', text: 'Сравнение периодов и подразделений, тренды, цели и бенчмарки — основа управленческих решений.' },
  { icon: 'access', title: 'Ролевой доступ и модерация', text: 'Каждый видит только своё; публикация дашборда — только после проверки модератором.' },
  { icon: 'reports', title: 'Отчёты и выгрузки', text: 'Готовые отчёты, экспорт в Excel/PDF/PNG, витрины из нескольких дашбордов и журналы аудита.' },
  { icon: 'suggest', title: 'Рекомендации и аномалии', text: 'Система сама подсказывает недостающие показатели и отмечает выбросы на графиках.' },
]

// Иллюстрации-иконки (белые линии — для тёмной гео-панели входа)
const ICON_BOX: React.CSSProperties = { width: 26, height: 26, flexShrink: 0 }
const W = 'rgba(255,255,255,0.92)'
const FEATURE_ICONS: Record<string, React.ReactNode> = {
  dashboards: (
    <svg style={ICON_BOX} viewBox="0 0 26 26">
      <rect x="2" y="2" width="10" height="10" rx="1.5" fill="none" stroke={W} strokeWidth="1.6" />
      <rect x="14" y="2" width="10" height="6" rx="1.5" fill="none" stroke={W} strokeWidth="1.6" />
      <rect x="2" y="14" width="6" height="10" rx="1.5" fill="none" stroke={W} strokeWidth="1.6" />
      <rect x="10" y="14" width="14" height="10" rx="1.5" fill="none" stroke={W} strokeWidth="1.6" />
    </svg>
  ),
  transparency: (
    <svg style={ICON_BOX} viewBox="0 0 26 26">
      <rect x="3" y="14" width="3.5" height="7" fill={W} />
      <rect x="9" y="9" width="3.5" height="12" fill={W} />
      <circle cx="18" cy="8" r="5" fill="none" stroke={W} strokeWidth="1.6" />
      <line x1="21.5" y1="11.5" x2="24.5" y2="14.5" stroke={W} strokeWidth="2" strokeLinecap="round" />
    </svg>
  ),
  analytics: (
    <svg style={ICON_BOX} viewBox="0 0 26 26">
      <polyline points="2,20 9,12 14,16 24,4" fill="none" stroke={W} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="17,4 24,4 24,11" fill="none" stroke={W} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  access: (
    <svg style={ICON_BOX} viewBox="0 0 26 26">
      <path d="M13 2 L23 6 V12 C23 19 18 23 13 25 C8 23 3 19 3 12 V6 Z" fill="none" stroke={W} strokeWidth="1.6" />
      <path d="M8.5 13 L11.5 16.5 L18 9" fill="none" stroke={W} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  reports: (
    <svg style={ICON_BOX} viewBox="0 0 26 26">
      <rect x="4" y="2" width="14" height="18" rx="1.5" fill="none" stroke={W} strokeWidth="1.6" />
      <line x1="7.5" y1="7" x2="14.5" y2="7" stroke={W} strokeWidth="1.4" strokeLinecap="round" />
      <line x1="7.5" y1="11" x2="14.5" y2="11" stroke={W} strokeWidth="1.4" strokeLinecap="round" />
      <path d="M16 16 L22 16 L22 22 M22 16 L15 23" fill="none" stroke={W} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  suggest: (
    <svg style={ICON_BOX} viewBox="0 0 26 26">
      <path d="M13 3a6.5 6.5 0 0 0-4 11.7c.8.6 1.3 1.5 1.3 2.5v1.3h5.4v-1.3c0-1 .5-1.9 1.3-2.5A6.5 6.5 0 0 0 13 3Z" fill="none" stroke={W} strokeWidth="1.6" />
      <line x1="10.3" y1="22" x2="15.7" y2="22" stroke={W} strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
}

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
  const [blockedMsg, setBlockedMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const narrow = useNarrow()

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setBlockedMsg(null)
    try {
      const token = await login(username.trim(), password)
      setToken(token)
      onLogin(token)
    } catch (err) {
      const le = err as LoginError
      if (le.code === 'account_blocked') setBlockedMsg(le.message)
      else setError(le.message)
    } finally {
      setBusy(false)
    }
  }

  if (blockedMsg) {
    return (
      <div style={{ ...page, flexDirection: narrow ? 'column' : 'row', position: 'relative' }}>
        <ThemeCorner />
        <div style={{ ...hero, padding: narrow ? '32px 24px' : '56px 52px', minHeight: narrow ? undefined : '100vh' }}>
          <div style={heroInner}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: narrow ? 20 : 40 }}>
              <Logo size={48} radius={12} border={false} />
              <div>
                <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: 0.3 }}>Dashboard</div>
                <div style={{ fontSize: 12, opacity: 0.8 }}>{BRAND.orgShort}</div>
              </div>
            </div>
            <h1 style={{ fontSize: narrow ? 22 : 30, lineHeight: 1.2, margin: '0 0 14px', fontWeight: 800 }}>Учётная запись заблокирована</h1>
            <p style={{ fontSize: 14, lineHeight: 1.55, opacity: 0.92, maxWidth: 480 }}>{blockedMsg}</p>
          </div>
        </div>
        <div style={{ ...formSide, padding: narrow ? '28px 24px 44px' : 24, minHeight: narrow ? undefined : '100vh' }}>
          <BlockedAppealForm login={username.trim()} onBack={() => setBlockedMsg(null)} />
        </div>
      </div>
    )
  }

  return (
    <div style={{ ...page, flexDirection: narrow ? 'column' : 'row', position: 'relative' }}>
      <ThemeCorner />
      {/* Левая панель — о портале */}
      <div style={{ ...hero, padding: narrow ? '32px 24px' : '56px 52px', minHeight: narrow ? undefined : '100vh' }}>
        <div style={heroInner}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: narrow ? 20 : 40 }}>
            <Logo size={48} radius={12} border={false} />
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: 0.3 }}>Dashboard</div>
              <div style={{ fontSize: 12, opacity: 0.8 }}>{BRAND.orgShort}</div>
            </div>
          </div>

          <h1 style={{ fontSize: narrow ? 26 : 38, lineHeight: 1.15, margin: '0 0 14px', fontWeight: 800 }}>
            {BRAND.portal}<br />
            <span style={{ color: '#ffe0a3' }}>для управленческих решений</span>
          </h1>
          <p style={{ fontSize: narrow ? 14 : 16, lineHeight: 1.55, opacity: 0.92, margin: '0 0 8px', maxWidth: 560 }}>
            Единое пространство данных {BRAND.orgShort}: показатели работы центра, услуги, нагрузка и
            качество обслуживания — собраны, проверены и представлены так, чтобы решения принимались
            на основе фактов, а не догадок.
          </p>
          <p style={{ fontSize: narrow ? 12.5 : 13.5, lineHeight: 1.5, opacity: 0.78, margin: '0 0 28px', maxWidth: 560 }}>
            25 типов виджетов, drill-down до первичных строк, ролевой доступ и модерация публикаций,
            архив данных за прошлые периоды и экспорт в Excel/PDF.
          </p>

          {!narrow && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, maxWidth: 620 }}>
              {FEATURES.map((f) => (
                <div key={f.title} style={featCard}>
                  <div style={{ marginBottom: 8 }}>{FEATURE_ICONS[f.icon]}</div>
                  <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 3 }}>{f.title}</div>
                  <div style={{ fontSize: 12.5, lineHeight: 1.45, opacity: 0.85 }}>{f.text}</div>
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: narrow ? 20 : 40, fontSize: 12, opacity: 0.7 }}>{BRAND.orgFull}</div>
        </div>
      </div>

      {/* Правая панель — форма входа. Под формой лежит приглушённая графика:
          левая половина высокая и прокручивается, а правая без неё читалась
          как незавершённая. На узком экране не рисуем — там места и так нет. */}
      <div style={{ ...formSide, padding: narrow ? '28px 24px 44px' : 24, minHeight: narrow ? undefined : '100vh', position: 'relative', overflow: 'hidden' }}>
        {!narrow && <LoginBackdrop />}
        <form onSubmit={submit} style={{ ...card, position: 'relative' }}>
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

// Форма обращения без входа (login уже недоступен для входа — заблокирован).
function BlockedAppealForm({ login: userLogin, onBack }: { login: string; onBack: () => void }) {
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function send() {
    if (!message.trim()) return
    setBusy(true); setErr(null)
    try { await submitBlockedAppeal(userLogin, message.trim()); setSent(true) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <div style={card}>
      {sent ? (
        <>
          <h2 style={{ fontSize: 18, margin: '0 0 8px' }}>Обращение отправлено</h2>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 20px' }}>
            Администратор получит уведомление и рассмотрит вашу заявку.
          </p>
          <button style={button} onClick={onBack}>Назад ко входу</button>
        </>
      ) : (
        <>
          <h2 style={{ fontSize: 18, margin: '0 0 4px' }}>Написать администратору</h2>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 16px' }}>
            Опишите проблему — обращение будет направлено администратору системы.
          </p>
          <label style={label}>Логин</label>
          <input style={{ ...input, background: 'var(--surface-2)' }} value={userLogin} disabled />
          <label style={label}>Сообщение</label>
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={4}
            style={{ ...input, height: 'auto', padding: '8px 12px', resize: 'vertical', fontFamily: 'inherit' }} />
          {err && <div style={errBox}>{err}</div>}
          <button style={{ ...button, opacity: busy || !message.trim() ? 0.6 : 1 }} disabled={busy || !message.trim()} onClick={send}>
            {busy ? 'Отправка…' : 'Отправить'}
          </button>
          <button type="button" onClick={onBack}
            style={{ border: 'none', background: 'none', color: 'var(--text-faint)', cursor: 'pointer', fontSize: 12, marginTop: 12 }}>
            ← Назад ко входу
          </button>
        </>
      )}
    </div>
  )
}

const page: React.CSSProperties = { minHeight: '100vh', display: 'flex', fontFamily: 'var(--font-body)', color: 'var(--text)' }
const hero: React.CSSProperties = {
  flex: 1.25, color: 'var(--on-accent)', display: 'flex', alignItems: 'center',
  background: `radial-gradient(1200px 600px at 15% -10%, ${BRAND.primary} 0%, ${BRAND.primaryDark} 55%, #3a1e12 100%)`,
}
const heroInner: React.CSSProperties = { width: '100%', maxWidth: 680 }
const featCard: React.CSSProperties = {
  background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.14)', borderRadius: 12, padding: '14px 16px',
}
const formSide: React.CSSProperties = { flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }
const card: React.CSSProperties = {
  width: '100%', maxWidth: 360, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 16,
  padding: 28, display: 'flex', flexDirection: 'column', boxShadow: '0 10px 40px rgba(20,35,76,0.08)',
}
const label: React.CSSProperties = { fontSize: 13, color: 'var(--text-muted)', marginBottom: 4 }
const input: React.CSSProperties = { height: 40, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 9, marginBottom: 14, fontSize: 14 }
const button: React.CSSProperties = { height: 42, border: 'none', borderRadius: 9, background: BRAND.primary, color: 'var(--on-accent)', fontSize: 15, fontWeight: 600, cursor: 'pointer', marginTop: 4 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
