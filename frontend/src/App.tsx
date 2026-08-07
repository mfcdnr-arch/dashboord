import { useEffect, useState } from 'react'
import { clearToken, getAppealsStats, getHealth, getMe, getSetupStatus, getToken, type Health, type Me } from './api'
import Login from './components/Login'
import ChangePassword from './components/ChangePassword'
import ObjectsPage from './components/ObjectsPage'
import MetricsPage from './components/MetricsPage'
import DashboardsPage from './components/DashboardsPage'
import HomePage from './components/HomePage'
import UsersPage from './components/UsersPage'
import ReportsPage from './components/ReportsPage'
import AuditPage from './components/AuditPage'
import ModerationPage from './components/ModerationPage'
import CatalogPage from './components/CatalogPage'
import SettingsPage from './components/SettingsPage'
import ProfilePage from './components/ProfilePage'
import ShowcasesPage from './components/ShowcasesPage'
import AppealsPage from './components/AppealsPage'
import NotificationBell from './components/NotificationBell'
import OnboardingHint from './components/OnboardingHint'
import ThemeToggle from './components/ThemeToggle'
import Logo from './components/Logo'
import SetupWizard from './components/SetupWizard'
import ArchivePage from './components/ArchivePage'
import { archiveMe } from './api/archive'

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
  if (me?.must_change_password) return <ChangePassword token={token} onDone={(t) => { setToken(t); loadMe(t) }} />
  return <Shell me={me!} onLogout={onLogout} />
}

// Разделы, которым нужна вся ширина экрана (сетка виджетов), а не колонка чтения.
// «Объекты» попали сюда из-за конструктора разметки: там показывается лист
// документа как в оригинале, а у отчётов госсектора бывает и 16 столбцов —
// на 900px от таблицы видно два столбца из шестнадцати.
const WIDE_SECTIONS = new Set(['dashboards', 'showcases', 'archive', 'objects'])

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--font-body)', color: 'var(--text-muted)' }}>
      {children}
    </div>
  )
}

const NAV = [
  { key: 'home', label: 'Главная', ready: true },
  { key: 'objects', label: 'Объекты', ready: true },
  { key: 'metrics', label: 'Метрики', ready: true },
  { key: 'dashboards', label: 'Дашборды', ready: true },
  { key: 'showcases', label: 'Витрины', ready: true },
  { key: 'archive', label: 'Архив', ready: true, archiveGate: true },
  { key: 'moderation', label: 'Модерация', ready: true, modOnly: true },
  { key: 'appeals', label: 'Обращения', ready: true, modOnly: true },
  { key: 'catalog', label: 'Справочники', ready: true, modOnly: true },
  { key: 'users', label: 'Пользователи', ready: true, adminOnly: true },
  { key: 'audit', label: 'Аудит', ready: true, adminOnly: true },
  { key: 'reports', label: 'Отчёты', ready: true, adminOnly: true },
  { key: 'settings', label: 'Настройки', ready: true, adminOnly: true },
  { key: 'profile', label: 'Кабинет', ready: true },
]

// Узкий экран (телефон/планшет): переключает боковую навигацию на верхнюю
// прокручиваемую полосу и убирает ограничение ширины контента.
function useIsNarrow(maxWidth = 760): boolean {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.matchMedia(`(max-width:${maxWidth}px)`).matches)
  useEffect(() => {
    const mq = window.matchMedia(`(max-width:${maxWidth}px)`)
    const on = () => setNarrow(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [maxWidth])
  return narrow
}

function Shell({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const narrow = useIsNarrow()
  const [health, setHealth] = useState<Health | null>(null)
  const [section, setSection] = useState('home')
  const [openDash, setOpenDash] = useState<string | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
  }, [])
  const ok = health?.status === 'ok'
  const canManage = me.roles.includes('admin') || me.roles.includes('moderator') || me.roles.includes('superadmin')
  const isAdmin = me.roles.includes('admin') || me.roles.includes('superadmin')
  // Мастер первичной настройки: показываем автоматически на «свежей установке»
  // (структурно пусто) администратору, пока настройка не закрыта (серверный флаг
  // organizations.setup_dismissed — переживает смену браузера). Открыть вручную —
  // кнопкой «🧭 Настройка» в шапке.
  useEffect(() => {
    if (!isAdmin) return
    getSetupStatus().then((s) => { if (s.fresh_install && !s.setup_dismissed) setWizardOpen(true) }).catch(() => {})
  }, [isAdmin])
  const canModerate = me.roles.some((r) => ['admin', 'moderator', 'senior_moderator'].includes(r))
  // Раздел «Архив»: привилегированным — всегда; обычному пользователю — только
  // по допуску, выданному администратором/модератором (спрашиваем сервер).
  const [archiveOk, setArchiveOk] = useState(false)
  useEffect(() => {
    if (canModerate) { setArchiveOk(true); return }
    archiveMe().then((r) => setArchiveOk(r.allowed)).catch(() => setArchiveOk(false))
  }, [canModerate])
  // Значок «сколько обращений ждут ответа» у пункта «Обращения» (только staff).
  // Best-effort, не real-time (полноценный push через WebSocket/SSE был бы
  // избыточен для масштаба МФЦ) — но обновляется часто и по актуальным поводам:
  // по таймеру, при переходе между разделами и при возврате на вкладку/в фокус
  // (частая ситуация — свернули, кто-то ответил, вернулись).
  const [appealsOpen, setAppealsOpen] = useState(0)
  useEffect(() => {
    if (!canModerate) return
    const load = () => getAppealsStats().then((s) => setAppealsOpen(s.open)).catch(() => {})
    load()
    const t = setInterval(load, 20000)
    const onVisible = () => { if (document.visibilityState === 'visible') load() }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', load)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onVisible); window.removeEventListener('focus', load) }
  }, [canModerate, section])
  const nav = NAV.filter((n) => (!n.adminOnly || isAdmin) && (!n.modOnly || canModerate)
    && (!(n as { archiveGate?: boolean }).archiveGate || archiveOk))

  return (
    <div style={{ fontFamily: 'var(--font-body)', minHeight: '100vh' }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 20px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        <Logo size={34} />
        <div>
          <div style={{ fontSize: 16, fontWeight: 600, lineHeight: 1 }}>Dashboard</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>ГБУ «МФЦ ДНР»</div>
        </div>
        <span style={{ marginLeft: 'auto', fontSize: 13, padding: '4px 10px', borderRadius: 12, background: ok ? 'var(--success-bg)' : 'var(--danger-bg)', color: ok ? 'var(--success)' : 'var(--danger)' }}>
          API: {health ? `${health.status} · БД ${health.db}` : '…'}
        </span>
        <span style={{ fontSize: 13 }}><strong>{me.full_name || me.login}</strong></span>
        {!narrow && <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: 'var(--accent-weak-bg)', color: 'var(--accent)' }}>{me.roles.join(', ')}</span>}
        {isAdmin && (
          <button onClick={() => setWizardOpen(true)} title="Мастер первичной настройки"
            style={{ height: 32, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text-2)', cursor: 'pointer', fontSize: 13 }}>
            🧭{narrow ? '' : ' Настройка'}
          </button>
        )}
        <NotificationBell />
        <ThemeToggle />
        <button onClick={onLogout} style={{ height: 32, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text)', cursor: 'pointer', fontSize: 13 }}>Выйти</button>
      </header>
      {wizardOpen && (
        <SetupWizard onClose={() => setWizardOpen(false)}
          onNavigate={(s) => { setWizardOpen(false); setOpenDash(null); setSection(s) }} />
      )}

      <div style={{ display: 'flex', flexDirection: narrow ? 'column' : 'row', minHeight: 'calc(100vh - 55px)' }}>
        <nav style={narrow
          ? { display: 'flex', gap: 6, overflowX: 'auto', padding: '8px 12px', borderBottom: '1px solid var(--border)' }
          : { width: 200, borderRight: '1px solid var(--border)', padding: 12 }}>
          {nav.map((n) => (
            <button
              key={n.key}
              onClick={() => { setOpenDash(null); setSection(n.key) }}
              style={{
                display: 'block', width: narrow ? 'auto' : '100%', whiteSpace: 'nowrap', textAlign: 'left',
                padding: '8px 12px', marginBottom: narrow ? 0 : 4,
                border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 14,
                background: section === n.key ? 'var(--accent-weak-bg)' : 'transparent',
                color: section === n.key ? 'var(--accent)' : n.ready ? 'var(--text)' : 'var(--text-faint)',
              }}
            >
              {n.label}{!n.ready && <span style={{ fontSize: 11 }}> · в разработке</span>}
              {n.key === 'appeals' && appealsOpen > 0 && (
                <span style={{ marginLeft: 6, fontSize: 11, padding: '1px 6px', borderRadius: 9, background: 'var(--danger)', color: 'var(--on-accent)' }}>
                  {appealsOpen > 99 ? '99+' : appealsOpen}
                </span>
              )}
            </button>
          ))}
        </nav>

        {/* Ширина колонки контента. Текстовые/табличные разделы читаются лучше в
            узкой колонке (900px — комфортная длина строки), но ДАШБОРДЫ и ВИТРИНЫ —
            это плотная сетка виджетов: на 900px из 12 колонок сетки получаются
            узкие карточки, а на мониторе 1920 половина экрана простаивала. */}
        <main style={{ flex: 1, padding: narrow ? 12 : 24, maxWidth: narrow ? '100%' : (WIDE_SECTIONS.has(section) ? 1600 : 900), minWidth: 0 }}>
          <OnboardingHint section={section} roles={me.roles} userKey={me.login} />
          {section === 'home' ? (
            <HomePage me={me} canManage={canManage} onOpenDashboard={(id) => { setOpenDash(id); setSection('dashboards') }} />
          ) : section === 'objects' ? (
            <ObjectsPage canManage={canManage} />
          ) : section === 'metrics' ? (
            <MetricsPage canManage={canManage} />
          ) : section === 'dashboards' ? (
            <DashboardsPage canManage={canManage} isAdmin={isAdmin} initialDashboardId={openDash} />
          ) : section === 'showcases' ? (
            <ShowcasesPage canManage={canManage} onOpenDashboard={(id) => { setOpenDash(id); setSection('dashboards') }} />
          ) : section === 'users' ? (
            <UsersPage me={me} />
          ) : section === 'reports' ? (
            <ReportsPage me={me} />
          ) : section === 'audit' ? (
            <AuditPage me={me} />
          ) : section === 'archive' ? (
            <ArchivePage canManage={canModerate} isAdmin={isAdmin} />
          ) : section === 'moderation' ? (
            <ModerationPage me={me} onOpenDashboard={(id) => { setOpenDash(id); setSection('dashboards') }} />
          ) : section === 'appeals' ? (
            <AppealsPage />
          ) : section === 'catalog' ? (
            <CatalogPage me={me} />
          ) : section === 'settings' ? (
            <SettingsPage me={me} />
          ) : section === 'profile' ? (
            <ProfilePage me={me} />
          ) : (
            <div style={{ color: 'var(--text-faint)' }}>Раздел «{NAV.find((n) => n.key === section)?.label}» в разработке.</div>
          )}
        </main>
      </div>
    </div>
  )
}
