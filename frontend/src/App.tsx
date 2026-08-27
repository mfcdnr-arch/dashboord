import { useCallback, useEffect, useState } from 'react'
import { clearToken, getAppealsStats, getHealth, getMe, getSetupStatus, getToken, type Health, type Me } from './api'
import Login from './components/Login'
import ChangePassword from './components/ChangePassword'
import ObjectsPage from './components/ObjectsPage'
import MetricsPage from './components/MetricsPage'
import type { LinkState } from './lib/deeplink'
import { initialLink, useDeepLink } from './lib/useDeepLink'
import CommandPalette, { type SearchTarget } from './components/CommandPalette'
import DashboardsPage from './components/DashboardsPage'
import HomePage from './components/HomePage'
import InstructionsPage from './components/InstructionsPage'
import UserHomePage from './components/UserHomePage'
import UsersPage from './components/UsersPage'
import ReportsPage from './components/ReportsPage'
import AuditPage from './components/AuditPage'
import ModerationPage from './components/ModerationPage'
import CatalogPage from './components/CatalogPage'
import SettingsPage from './components/SettingsPage'
import ProfilePage from './components/ProfilePage'
import ShowcasesPage from './components/ShowcasesPage'
import DnrStatsPage from './components/DnrStatsPage'
import AppealsPage from './components/AppealsPage'
import NotificationBell from './components/NotificationBell'
import OnboardingHint from './components/OnboardingHint'
import UploadsPage from './components/UploadsPage'
import ThemeToggle from './components/ThemeToggle'
import Logo from './components/Logo'
import SetupWizard from './components/SetupWizard'
import ArchivePage from './components/ArchivePage'
import { archiveMe } from './api/archive'
import { listShowcases } from './api/showcases'
import { listFeatured } from './api'
import LeadershipPage from './components/LeadershipPage'

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
// Разделы с сеткой виджетов и широкими таблицами занимают ВСЮ ширину окна:
// на мониторе 1920/2560 ограничение по ширине оставляло половину экрана пустой,
// а дашборд смотрят именно на большом экране (в том числе на ТВ в холле).
// Остальные разделы (формы, списки) остаются в узкой колонке — длинные строки
// текста через весь монитор читать неудобно.
const WIDE_SECTIONS = new Set(['dashboards', 'showcases', 'archive', 'objects', 'dnrstats'])

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--font-body)', color: 'var(--text-muted)' }}>
      {children}
    </div>
  )
}

// staffOnly — рабочая кухня (загрузка документов, разметка, формулы, сводка по
// системе). Обычному пользователю там нечего делать: он смотрит готовые дашборды
// и комментирует их, а кнопки создания всё равно упирались бы в «Недостаточно прав».
const NAV = [
  { key: 'home', label: 'Главная', ready: true, staffOnly: true },
  // Своя главная для сотрудника: объявления, его отчёты по объектам, что нового
  // в данных и справка о системе. Админская «Главная» — про наполнение системы.
  { key: 'portal', label: 'Главная', ready: true, userOnly: true },
  // Общая зона загрузки: сдать форму, не зная устройства системы.
  { key: 'uploads', label: 'Загрузка', ready: true, staffOnly: true },
  { key: 'objects', label: 'Объекты', ready: true, staffOnly: true },
  { key: 'metrics', label: 'Метрики', ready: true, staffOnly: true },
  // Подборка для руководства нужна единицам, поэтому показывается по галочке
  // в карточке сотрудника (и всегда — управляющим). Раньше её видели все, у
  // кого есть хоть один отчёт из подборки.
  { key: 'leadership', label: 'Руководителю', ready: true, featuredGate: true },
  { key: 'dashboards', label: 'Дашборды', ready: true },
  { key: 'instructions', label: 'Инструкции', ready: true },
  { key: 'showcases', label: 'Витрины', ready: true, showcaseGate: true },
  // Пилотный раздел (не дашборд): отделения МФЦ с раскрытием по ведомству и
  // услуге — такого разреза обычный конструктор виджетов не строит.
  { key: 'dnrstats', label: 'Статистика услуг', ready: true, staffOnly: true },
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
  // Обычный пользователь начинает сразу со списка дашбордов: «Главной» у него нет.
  const staff = me.roles.some((r) => ['admin', 'moderator', 'superadmin'].includes(r))
  // Пришли по ссылке (п. 6) — начинаем с того места, которое в ней указано.
  const [link0] = useState(initialLink)
  const [section, setSection] = useState(link0.section || (staff ? 'home' : 'dashboards'))
  const [openDash, setOpenDash] = useState<string | null>(link0.dashboard || null)
  // Страница, на которую нужно попасть при открытии дашборда (из каталога
  // «Главной»): без неё клик по «Динамике» приводил на «Обзор».
  const [openPage, setOpenPage] = useState<string | null>(link0.page || null)
  // Фильтры живут внутри DashboardsPage; сюда она их только СООБЩАЕТ, чтобы
  // адрес показывал то, что человек видит. Поднимать их в App значило бы
  // переписать половину страницы ради одной ссылки.
  const [dashLink, setDashLink] = useState<LinkState>(link0)
  // Счётчик нажатий «назад»/«вперёд». Нужен, чтобы отличить ВНЕШНЮЮ смену
  // места (человек в истории браузера) от того, что страница сама сообщила о
  // себе: применять ссылку надо только в первом случае, иначе экран сбрасывал
  // бы фильтры себе под руку.
  const [navSeq, setNavSeq] = useState(0)
  // Куда ведёт клик по уведомлению: раздел + сущность внутри него. Без этого
  // уведомление было тупиком — человек читал «не работает выгрузка» и должен
  // был сам вспомнить, где искать это обращение.
  const [openAppeal, setOpenAppeal] = useState<string | null>(null)
  // С какой вкладки открыть «Кабинет»: с главной ведёт кнопка «Написать администратору».
  const [profileTab, setProfileTab] = useState<'profile' | 'appeals' | undefined>(undefined)
  const [openObject, setOpenObject] = useState<string | null>(null)
  // Показатель, к которому ведёт быстрый поиск (п. 9): раздел «Метрики»
  // remount'ится при каждом переходе в него (см. `nav`-переключатель ниже),
  // поэтому простого initial-пропа достаточно — навSeq для него не нужен.
  const [openMetric, setOpenMetric] = useState<string | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  // Адрес отражает место в системе: раздел, отчёт, страницу и фильтры (п. 6).
  // Внутри раздела «Дашборды» подробности приходят от самой страницы.
  const linkState: LinkState = section === 'dashboards'
    ? { ...dashLink, section: 'dashboards' }
    : { section }
  // Переход к отчёту/странице/виджету — общая точка для ДВУХ вызывающих:
  // нажатия «назад»/«вперёд» в браузере (см. useDeepLink) и выбора результата
  // в быстром поиске (п. 9, Ctrl+K). Оба случая — «где-то там, снаружи,
  // решили открыть другое место», и должны применяться одинаково: раздел
  // «Дашборды» может быть уже открыт (тогда нужен navSeq, чтобы страница
  // среагировала без размонтирования) или ещё не открыт (тогда достаточно
  // initialDashboardId при монтировании — navSeq в этом случае просто не
  // успевает ничего сломать, см. докстроку useDeepLink).
  const goTo = useCallback((s: LinkState) => {
    setSection(s.section || (staff ? 'home' : 'dashboards'))
    setOpenDash(s.dashboard || null)
    setOpenPage(s.page || null)
    setDashLink(s)
    setNavSeq((n) => n + 1)
  }, [staff])
  useDeepLink(linkState, goTo)
  const ok = health?.status === 'ok'
  const canManage = me.roles.includes('admin') || me.roles.includes('moderator') || me.roles.includes('superadmin')
  const isAdmin = me.roles.includes('admin') || me.roles.includes('superadmin')
  // Удаление дашбордов и показателей необратимо — доступно только владельцу
  // системы. Кнопки прячем, а не отключаем: кнопка, которая всегда отвечает
  // отказом, выглядит поломкой.
  const isSuperadmin = me.roles.includes('superadmin')
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
  // «Витрины» обычному пользователю показываем, только если ему реально доступна
  // хоть одна — иначе он открывает раздел и видит пустоту без объяснения.
  const [showcasesOk, setShowcasesOk] = useState(false)
  useEffect(() => {
    if (canManage) return
    listShowcases().then((r) => setShowcasesOk(r.length > 0)).catch(() => setShowcasesOk(false))
  }, [canManage])
  // «Руководителю»: у управляющего пункт есть всегда (ему туда класть), у
  // остальных — когда в подборке есть хоть что-то, доступное лично им.
  const [featuredOk, setFeaturedOk] = useState(false)
  useEffect(() => {
    if (canManage) return
    listFeatured().then((r) => setFeaturedOk(r.items.length > 0)).catch(() => setFeaturedOk(false))
  }, [canManage])
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
    && (!(n as { staffOnly?: boolean }).staffOnly || canManage)
    && (!(n as { userOnly?: boolean }).userOnly || !canManage)
    && (!(n as { archiveGate?: boolean }).archiveGate || archiveOk)
    && (!(n as { showcaseGate?: boolean }).showcaseGate || canManage || showcasesOk)
    // Подборка «Руководителю»: управляющим всегда, остальным — по галочке
    // (одного лишь наличия доступа к отчёту из подборки теперь мало).
    && (!(n as { featuredGate?: boolean }).featuredGate || canManage || (me.show_featured && featuredOk)))

  // Быстрый поиск (п. 9, Ctrl+K): выбор результата ведёт либо через ОБЩИЙ
  // механизм навигации (раздел/отчёт/страница/виджет — тот же `goTo`, что и
  // у кнопок «назад»/«вперёд» браузера), либо через собственный initial-проп
  // раздела (объект, показатель) — второй проще там, где раздел и так
  // размонтируется при уходе с него.
  const onSearchNavigate = useCallback((t: SearchTarget) => {
    switch (t.kind) {
      case 'section': goTo({ section: t.section }); break
      case 'dashboard': goTo({ section: 'dashboards', dashboard: t.dashboard }); break
      case 'page': goTo({ section: 'dashboards', dashboard: t.dashboard, page: t.page }); break
      case 'widget': goTo({ section: 'dashboards', dashboard: t.dashboard,
        page: t.page || undefined, widget: t.widget }); break
      case 'object': setSection('objects'); setOpenObject(t.object); break
      case 'metric': setSection('metrics'); setOpenMetric(t.metric); break
    }
  }, [goTo])

  return (
    <div style={{ fontFamily: 'var(--font-body)', minHeight: '100vh' }}>
      {/* Смонтирован всегда, независимо от раздела — Ctrl+K обязан работать
          из любого места, в этом весь смысл «быстрого» поиска. */}
      <CommandPalette nav={nav} onNavigate={onSearchNavigate} />
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
        <NotificationBell
          staff={staff}
          onNavigate={(t) => {
            setOpenDash(t.dashboardId ?? null)
            setOpenAppeal(t.appealId ?? null)
            setOpenObject(t.objectId ?? null)
            setSection(t.section)
          }}
        />
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
              onClick={() => { setOpenDash(null); setOpenAppeal(null); setOpenObject(null); setSection(n.key) }}
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
        <main style={{ flex: 1, padding: narrow ? 12 : 24, maxWidth: (narrow || WIDE_SECTIONS.has(section)) ? '100%' : 900, minWidth: 0 }}>
          <OnboardingHint section={section} roles={me.roles} userKey={me.login} />
          {section === 'home' ? (
            <HomePage me={me} canManage={canManage}
              onOpenDashboard={(id, pageId) => { setOpenDash(id); setOpenPage(pageId || null); setSection('dashboards') }} />
          ) : section === 'uploads' ? (
            <UploadsPage />
          ) : section === 'objects' ? (
            <ObjectsPage canManage={canManage} isSuperadmin={isSuperadmin} initialObjectId={openObject} />
          ) : section === 'metrics' ? (
            <MetricsPage canManage={canManage} isSuperadmin={isSuperadmin} initialMetricId={openMetric} />
          ) : section === 'leadership' ? (
            <LeadershipPage canManage={canManage}
              onOpen={(id) => { setOpenDash(id); setSection('dashboards') }} />
          ) : section === 'dashboards' ? (
            <DashboardsPage canManage={canManage} isAdmin={isAdmin} isSuperadmin={isSuperadmin} initialDashboardId={openDash} initialPageId={openPage}
              link={dashLink} navSeq={navSeq} onLocationChange={setDashLink}
              // Отправив жалобу с виджета, человек хочет прочитать ответ. Своя
              // переписка у обычного пользователя живёт в «Кабинете» (раздела
              // «Обращения» у него нет) — то же правило, что у уведомлений.
              onOpenAppeals={() => setSection(staff ? 'appeals' : 'profile')} />
          ) : section === 'portal' ? (
            <UserHomePage fullName={me.full_name || me.login}
              onOpenDashboard={(id) => { setOpenDash(id); setSection('dashboards') }}
              onGoto={(s) => {
                // «Написать администратору» ведёт в «Кабинет» сразу на вкладку
                // переписки: отдельный пункт меню дублировал бы её.
                if (s === 'appeals') { setProfileTab('appeals'); setSection('profile') } else setSection(s)
              }} />
          ) : section === 'instructions' ? (
            <InstructionsPage canManage={canManage} />
          ) : section === 'showcases' ? (
            <ShowcasesPage canManage={canManage} onOpenDashboard={(id) => { setOpenDash(id); setSection('dashboards') }} />
          ) : section === 'dnrstats' ? (
            <DnrStatsPage />
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
            <AppealsPage initialAppealId={openAppeal}
              onOpenDashboard={(id: string, pageId?: string | null) => { setOpenDash(id); setOpenPage(pageId || null); setSection('dashboards') }} />
          ) : section === 'catalog' ? (
            <CatalogPage me={me} />
          ) : section === 'settings' ? (
            <SettingsPage me={me} />
          ) : section === 'profile' ? (
            <ProfilePage me={me} initialAppealId={openAppeal} initialTab={profileTab}
              onOpenDashboard={(id: string, pageId?: string | null) => { setOpenDash(id); setOpenPage(pageId || null); setSection('dashboards') }} />
          ) : (
            <div style={{ color: 'var(--text-faint)' }}>Раздел «{NAV.find((n) => n.key === section)?.label}» в разработке.</div>
          )}
        </main>
      </div>
    </div>
  )
}
