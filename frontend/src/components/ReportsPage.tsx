import { useEffect, useState } from 'react'
import {
  getArchiveRunStatus, getAttendanceReport, getBackupStatus, getBusinessReport, getDashboardViewers, getDataQualityReport, getHealHistory, getLogs, getModerationReport, getPopularityReport, getSystemReport, healSystem, runArchiveNow, runBackupNow,
  type ArchiveRunStatus, type AttendanceReport, type BackupStatus, type BusinessReport, type DashboardViewers, type DataQualityReport, type Gauge, type HealHistoryEntry, type HealResult, type LogsResult, type ModerationReport, type PopularityReport, type SystemReport,
} from '../api'
import EChart from './EChartLazy'
import UserCard from './users/UserCard'
import { fmtNumber as num } from '../lib/format'
import { getLoginEvents, type LoginEventsReport } from '../api'


// Раздел «Отчёты» (admin): системный мониторинг (CPU/RAM/диск через psutil +
// статусы сервисов, с порогами) и посещаемость (по login_events).

const LVL: Record<string, { c: string; bg: string }> = {
  good: { c: 'var(--success)', bg: '#e8f5f0' }, warn: { c: 'var(--warn)', bg: '#fff4e0' }, danger: { c: 'var(--danger)', bg: 'var(--danger-bg)' },
}
function fmtBytes(n?: number | null): string {
  if (n == null) return '—'
  const u = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']; let i = 0; let v = n
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`
}
function fmtUptime(sec: number): string {
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60)
  return d > 0 ? `${d} д ${h} ч` : h > 0 ? `${h} ч ${m} мин` : `${m} мин`
}
function fmtDt(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

export default function ReportsPage({ me }: { me: { roles: string[] } }) {
  const [sys, setSys] = useState<SystemReport | null>(null)
  const [att, setAtt] = useState<AttendanceReport | null>(null)
  const [dq, setDq] = useState<DataQualityReport | null>(null)
  const [biz, setBiz] = useState<BusinessReport | null>(null)
  const [pop, setPop] = useState<PopularityReport | null>(null)
  const [viewers, setViewers] = useState<DashboardViewers | null>(null)
  const [mod, setMod] = useState<ModerationReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [heal, setHeal] = useState<HealResult | null>(null)
  const [healing, setHealing] = useState(false)
  const [healHist, setHealHist] = useState<HealHistoryEntry[] | null>(null)
  const [logsService, setLogsService] = useState('api')
  const [logsMinutes, setLogsMinutes] = useState(30)
  const [logsQuery, setLogsQuery] = useState('')
  const [logs, setLogs] = useState<LogsResult | null>(null)
  const [logsLoading, setLogsLoading] = useState(false)
  const [backup, setBackup] = useState<BackupStatus | null>(null)
  const [backupRequesting, setBackupRequesting] = useState(false)
  const [archiveStat, setArchiveStat] = useState<ArchiveRunStatus | null>(null)
  const [archiveRunning, setArchiveRunning] = useState(false)
  const canAdmin = me.roles.includes('admin') || me.roles.includes('superadmin')

  const loadSys = () => getSystemReport().then(setSys).catch((e) => setError((e as Error).message))
  const loadHealHist = () => getHealHistory().then(setHealHist).catch((e) => setError((e as Error).message))
  async function doHeal() {
    setHealing(true); setError(null)
    try { setHeal(await healSystem()); await loadSys(); await loadHealHist() } catch (e) { setError((e as Error).message) } finally { setHealing(false) }
  }
  async function loadLogs() {
    setLogsLoading(true); setError(null)
    try { setLogs(await getLogs(logsService, logsMinutes, 200, logsQuery || undefined)) }
    catch (e) { setError((e as Error).message) } finally { setLogsLoading(false) }
  }
  const loadBackup = () => getBackupStatus().then(setBackup).catch((e) => setError((e as Error).message))
  const loadArchiveStat = () => getArchiveRunStatus().then(setArchiveStat).catch((e) => setError((e as Error).message))
  async function doBackupNow() {
    setBackupRequesting(true); setError(null)
    try { await runBackupNow(); await loadBackup() } catch (e) { setError((e as Error).message) } finally { setBackupRequesting(false) }
  }
  async function doArchiveNow() {
    setArchiveRunning(true); setError(null)
    try { await runArchiveNow(); await loadArchiveStat() } catch (e) { setError((e as Error).message) } finally { setArchiveRunning(false) }
  }
  useEffect(() => {
    if (!canAdmin) return
    loadSys()
    loadHealHist()
    loadLogs()
    loadBackup()
    loadArchiveStat()
    getAttendanceReport().then(setAtt).catch((e) => setError((e as Error).message))
    getPopularityReport().then(setPop).catch((e) => setError((e as Error).message))
    getModerationReport().then(setMod).catch((e) => setError((e as Error).message))
    getDataQualityReport().then(setDq).catch((e) => setError((e as Error).message))
    getBusinessReport().then(setBiz).catch((e) => setError((e as Error).message))
    const t = setInterval(loadSys, 15000) // авто-обновление мониторинга
    const th = setInterval(loadHealHist, 60000) // история чинится сторожевым cron раз в 10 мин
    return () => { clearInterval(t); clearInterval(th) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (!canAdmin) return <div style={{ color: 'var(--danger)' }}>Раздел «Отчёты» доступен только администратору.</div>

  const maxDay = Math.max(1, ...(att?.per_day.map((d) => d.logins + d.failed) || [1]))

  return (
    <div>
      <h2 style={{ fontSize: 20, margin: '0 0 16px' }}>Отчёты</h2>
      {error && <div style={errBox}>{error}</div>}

      {/* Здоровье системы + автопочинка */}
      <Section title="Здоровье системы" hint="обновляется автоматически каждые 15 с">
        {!sys ? <span style={muted}>Загрузка…</span> : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 12px', borderRadius: 12, fontWeight: 600,
                background: sys.status === 'degraded' ? 'var(--danger-bg)' : '#e8f5f0', color: sys.status === 'degraded' ? 'var(--danger)' : 'var(--success)' }}>
                {sys.status === 'degraded' ? '⚠ Есть проблемы' : '✓ Система в норме'}
              </span>
              <button style={btnGhost} disabled={healing} onClick={doHeal} title="Безопасная автопочинка: бакет MinIO, связь с Redis">
                {healing ? '⏳ Починка…' : '🔧 Починить'}
              </button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 12 }}>
              <GaugeCard title="Процессор (CPU)" g={sys.cpu} sub={`${sys.cores} ядер${sys.load ? ` · load ${sys.load.map((x) => x.toFixed(2)).join(' ')}` : ''}`} />
              <GaugeCard title="Память (RAM)" g={sys.memory} sub={`${fmtBytes(sys.memory.used)} из ${fmtBytes(sys.memory.total)}`} />
              <GaugeCard title="Диск" g={sys.disk} sub={`${fmtBytes(sys.disk.used)} из ${fmtBytes(sys.disk.total)}`} />
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center', fontSize: 13, color: 'var(--text-2)' }}>
              <span>Аптайм: <b>{fmtUptime(sys.uptime_sec)}</b></span>
              <span>Размер БД: <b>{fmtBytes(sys.db_size)}</b></span>
              <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>Сервисы:
                {sys.services.map((s) => (
                  <span key={s.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 10, background: s.ok ? '#e8f5f0' : 'var(--danger-bg)', color: s.ok ? 'var(--success)' : 'var(--danger)' }}>
                    {s.ok ? '●' : '○'} {s.name}{s.latency_ms != null && <span style={{ color: 'var(--text-faint)' }}>· {s.latency_ms} мс</span>}
                  </span>
                ))}
              </span>
            </div>
            {heal && (
              <div style={{ marginTop: 12, padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 10, background: 'var(--surface-2)' }}>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Результат починки {heal.healthy ? '✓' : '⚠'}</div>
                {heal.actions.map((a) => (
                  <div key={a.name} style={{ fontSize: 13, color: a.ok ? 'var(--text-2)' : 'var(--danger)', padding: '2px 0' }}>
                    {a.ok ? '✓' : '✗'} {a.name}: {a.result}
                  </div>
                ))}
              </div>
            )}
            <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 8 }}>
              Автопочинка — уровень приложения (бакет MinIO, связь с Redis). Авто-рестарт упавших контейнеров выполняет Docker (restart: unless-stopped).
              Сторожевой процесс сам проверяет статус каждые 10 мин и чинит при деградации — не только по кнопке.
            </div>
            {healHist && healHist.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>История починок</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 220, overflowY: 'auto' }}>
                  {healHist.map((h) => (
                    <div key={h.id} style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 12.5, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                      <span style={{ color: 'var(--text-faint)', minWidth: 118 }}>{fmtDt(h.created_at)}</span>
                      <span style={{ padding: '1px 8px', borderRadius: 8, background: 'var(--surface-2)', color: 'var(--text-2)' }}>
                        {h.triggered_by === 'auto' ? '🤖 авто' : `🖱 ${h.triggered_by_login ?? 'вручную'}`}
                      </span>
                      <span>{h.status_before} → {h.status_after}</span>
                      <span style={{ color: h.healthy ? 'var(--success)' : 'var(--danger)' }}>{h.healthy ? '✓ починено' : '⚠ остались проблемы'}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </Section>

      {/* Логи сервисов (через Loki — уже есть в мониторинг-стеке, без дублирования инфраструктуры) */}
      <Section title="Логи сервисов" hint="через Loki; если мониторинг не включён — покажет подсказку">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 10 }}>
          <label style={{ fontSize: 12 }}>Сервис
            <select value={logsService} onChange={(e) => setLogsService(e.target.value)}
              style={{ display: 'block', height: 32, marginTop: 2, borderRadius: 8, border: '1px solid var(--border-strong)', background: 'var(--surface)', color: 'var(--text)' }}>
              {(logs?.services ?? ['api', 'worker', 'web', 'postgres', 'redis', 'minio']).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label style={{ fontSize: 12 }}>За, мин
            <input type="number" min={1} max={1440} value={logsMinutes} onChange={(e) => setLogsMinutes(Number(e.target.value) || 30)}
              style={{ display: 'block', width: 80, height: 32, marginTop: 2, borderRadius: 8, border: '1px solid var(--border-strong)', background: 'var(--surface)', color: 'var(--text)', padding: '0 8px' }} />
          </label>
          <label style={{ fontSize: 12, flex: '1 1 160px' }}>Поиск по тексту
            <input value={logsQuery} onChange={(e) => setLogsQuery(e.target.value)} placeholder="необязательно"
              style={{ display: 'block', width: '100%', height: 32, marginTop: 2, borderRadius: 8, border: '1px solid var(--border-strong)', background: 'var(--surface)', color: 'var(--text)', padding: '0 8px' }} />
          </label>
          <button onClick={loadLogs} disabled={logsLoading}
            style={{ height: 32, padding: '0 14px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text-2)', cursor: 'pointer', fontSize: 13 }}>
            {logsLoading ? '⏳ Загрузка…' : '🔎 Показать'}
          </button>
        </div>
        {logs && !logs.available && (
          <div style={{ fontSize: 13, color: 'var(--text-faint)' }}>{logs.hint}</div>
        )}
        {logs && logs.available && (
          logs.lines.length === 0
            ? <span style={muted}>Ничего не найдено за выбранное окно.</span>
            : (
              <div style={{ maxHeight: 260, overflowY: 'auto', background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', fontFamily: 'monospace', fontSize: 12 }}>
                {logs.lines.map((l, i) => (
                  <div key={i} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', padding: '1px 0', borderBottom: i < logs.lines.length - 1 ? '1px solid var(--border)' : undefined }}>
                    <span style={{ color: 'var(--text-faint)' }}>{new Date(l.ts_ns / 1e6).toLocaleTimeString('ru-RU')}</span> {l.line}
                  </div>
                ))}
              </div>
            )
        )}
      </Section>

      {/* Бэкап и автоархив: статус читается с реального тома/из БД + «Запустить сейчас».
          Бэкап физически делает хостовой backup.sh (не приложение — нет docker.sock
          в контейнере), поэтому «сейчас» — это файл-триггер, который подхватывает
          ops-trigger-watch.sh в течение минуты, а не мгновенное выполнение. */}
      <Section title="Бэкап и автоархив" hint="статус — с реального диска/из БД; действие «сейчас» — не мгновенно">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Резервное копирование</div>
            {!backup ? <span style={muted}>Загрузка…</span> : (
              <>
                {!backup.watcher_configured && (
                  <div style={{ fontSize: 12, color: 'var(--text-faint)', marginBottom: 6 }}>
                    Наблюдатель хоста не настроен — «Запустить сейчас» не будет подхвачено.
                    Установите: <code>sudo ./backup-schedule.sh install</code>.
                  </div>
                )}
                {backup.sets.length === 0
                  ? <div style={muted}>Бэкапов ещё не было.</div>
                  : <div style={{ fontSize: 13, marginBottom: 6 }}>Последний: <b>{fmtDt(backup.sets[0].created_at)}</b>
                      {backup.sets[0].db_dump_bytes != null && <> · БД {fmtBytes(backup.sets[0].db_dump_bytes)}</>}
                      {backup.sets[0].minio_tgz_bytes != null && <> · MinIO {fmtBytes(backup.sets[0].minio_tgz_bytes)}</>}
                      <span style={{ color: 'var(--text-faint)' }}> · хранится {backup.sets.length}</span>
                    </div>}
                {backup.pending && <div style={{ fontSize: 12, color: 'var(--warn)', marginBottom: 6 }}>⏳ Заявка ожидает обработки хостом (до 1 мин).</div>}
                {backup.last_manual_result && (
                  <div style={{ fontSize: 12, color: backup.last_manual_result.ok ? 'var(--success)' : 'var(--danger)', marginBottom: 6 }}>
                    Последний ручной запуск: {backup.last_manual_result.ok ? '✓' : '✗'} {backup.last_manual_result.message}
                  </div>
                )}
                <button style={btnGhost} disabled={backupRequesting || backup.pending} onClick={doBackupNow}>
                  {backupRequesting ? '⏳ Отправка…' : backup.pending ? '⏳ Уже в очереди' : '💾 Запустить сейчас'}
                </button>
              </>
            )}
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Автоархив дашбордов</div>
            {!archiveStat ? <span style={muted}>Загрузка…</span> : (
              <>
                <div style={{ fontSize: 13, marginBottom: 6 }}>
                  {archiveStat.last_run ? <>Последний: <b>{fmtDt(archiveStat.last_run)}</b></> : <span style={muted}>Ещё не выполнялся.</span>}
                  <span style={{ color: 'var(--text-faint)' }}> · слепков за 31 день: {archiveStat.recent_count}</span>
                </div>
                <button style={btnGhost} disabled={archiveRunning} onClick={doArchiveNow} title="Идемпотентно: не дублирует слепки за уже обработанный месяц">
                  {archiveRunning ? '⏳ Выполняется…' : '📦 Запустить сейчас'}
                </button>
              </>
            )}
          </div>
        </div>
      </Section>

      {/* Активность конкретного сотрудника: журнал входов + действия + выгрузки
          + комментарии + обращения. Раньше это жило только в разделе
          «Пользователи», хотя по смыслу — отчёт. */}
      <UserActivitySection />

      {/* Посещаемость */}
      <Section title="Посещаемость (за 30 дней)">
        {!att ? <span style={muted}>Загрузка…</span> : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 20 }}>
            <div>
              <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
                <Stat t="Входов" v={att.totals.logins} />
                <Stat t="Активных" v={att.totals.active_users} />
                <Stat t="Неудач" v={att.totals.failed} danger={att.totals.failed > 0} />
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Входы по дням (14 дней)</div>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 90, borderBottom: '1px solid var(--border)' }}>
                {att.per_day.length === 0 && <span style={muted}>Нет данных.</span>}
                {att.per_day.map((d) => (
                  <div key={d.day} title={`${d.day}: входов ${d.logins}, неудач ${d.failed}`} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', alignItems: 'center', gap: 2 }}>
                    {d.failed > 0 && <div style={{ width: '70%', height: `${(d.failed / maxDay) * 70}px`, background: '#e6a5a5', borderRadius: '2px 2px 0 0' }} />}
                    <div style={{ width: '70%', height: `${(d.logins / maxDay) * 70}px`, background: 'var(--accent)', borderRadius: '2px 2px 0 0' }} />
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Активнее всех</div>
              {att.top_users.length === 0 ? <span style={muted}>Нет входов за период.</span> : att.top_users.map((u, i) => (
                <div key={u.login} style={{ display: 'flex', gap: 8, fontSize: 13, padding: '3px 0' }}>
                  <span style={{ color: 'var(--text-faint)', width: 18 }}>{i + 1}.</span>
                  <span style={{ flex: 1, fontWeight: 600 }}>{u.login}</span>
                  <span>{u.logins} вх.</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Section>

      {/* Популярность дашбордов */}
      <Section title="Популярность дашбордов (за 30 дней)">
        {!pop ? <span style={muted}>Загрузка…</span> : (
          <div>
            <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
              <Stat t="Просмотров" v={pop.totals.views} />
              <Stat t="Зрителей" v={pop.totals.viewers} />
            </div>
            {pop.top_dashboards.length === 0 ? <span style={muted}>Просмотров за период пока нет.</span> : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 20 }}>
                <div>
                  {/* Диаграмма просмотров (req #4). Клик по столбцу → «кто смотрел» */}
                  <EChart height={Math.max(160, pop.top_dashboards.length * 34)}
                    onPick={(name) => { const d = pop.top_dashboards.find((x) => x.name === name); if (d) getDashboardViewers(d.dashboard_id).then(setViewers).catch((e) => setError((e as Error).message)) }}
                    option={{
                      grid: { left: 4, right: 24, top: 6, bottom: 6, containLabel: true },
                      xAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef0f3' } } },
                      yAxis: { type: 'category', inverse: true, data: pop.top_dashboards.map((d) => d.name), axisLabel: { fontSize: 11, width: 130, overflow: 'truncate' } },
                      tooltip: { trigger: 'item' },
                      series: [{ type: 'bar', data: pop.top_dashboards.map((d) => d.views), itemStyle: { color: '#e04e39', borderRadius: [0, 4, 4, 0] }, barMaxWidth: 20, label: { show: true, position: 'right', fontSize: 11 } }],
                    }} />
                  <div style={{ ...muted, fontSize: 11 }}>Клик по столбцу — кто смотрел дашборд.</div>
                </div>
                <div>
                  {viewers ? (
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                        Кто смотрел: {viewers.name}
                        <button style={{ border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, marginLeft: 8 }} onClick={() => setViewers(null)}>× сбросить</button>
                      </div>
                      {viewers.viewers.length === 0 ? <span style={muted}>Просмотров нет.</span> : (
                        <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
                          <thead><tr>{['Пользователь', 'Просмотров', 'Последний'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
                          <tbody>
                            {viewers.viewers.map((v) => (
                              <tr key={v.login}>
                                <td style={{ ...td, fontWeight: 600 }}>{v.who}</td>
                                <td style={{ ...td, textAlign: 'center' }}>{v.views}</td>
                                <td style={td}>{v.last_view ? new Date(v.last_view).toLocaleDateString('ru-RU') : '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  ) : (
                    <div style={{ overflowX: 'auto' }}>
                      <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
                        <thead><tr>{['#', 'Дашборд', 'Просм.', 'Зрит.', ''].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
                        <tbody>
                          {pop.top_dashboards.map((d, i) => (
                            <tr key={d.dashboard_id}>
                              <td style={{ ...td, color: 'var(--text-faint)', textAlign: 'center' }}>{i + 1}</td>
                              <td style={{ ...td, fontWeight: 600 }}>{d.name}</td>
                              <td style={{ ...td, textAlign: 'center' }}>{d.views}</td>
                              <td style={{ ...td, textAlign: 'center' }}>{d.viewers}</td>
                              <td style={{ ...td, whiteSpace: 'nowrap' }}><button style={{ border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12 }} onClick={() => getDashboardViewers(d.dashboard_id).then(setViewers).catch((e) => setError((e as Error).message))}>кто смотрел</button></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </Section>

      {/* Модерация */}
      <Section title="Модерация (за 30 дней)">
        {!mod ? <span style={muted}>Загрузка…</span> : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 20 }}>
            <div>
              <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
                <Stat t="В очереди" v={mod.pending} danger={mod.pending > 0} />
                <Stat t="Одобрено" v={mod.totals.approved} />
                <Stat t="Возвращено" v={mod.totals.returned} />
              </div>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 13, color: 'var(--text-2)' }}>
                <span>Доля возвратов: <b>{mod.totals.return_rate == null ? '—' : `${mod.totals.return_rate}%`}</b></span>
                <span>Ср. время проверки: <b>{mod.totals.avg_hours == null ? '—' : `${mod.totals.avg_hours} ч`}</b></span>
                {mod.totals.cancelled > 0 && <span>Отозвано: <b>{mod.totals.cancelled}</b></span>}
              </div>
              {mod.top_reviewers.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Активнее всех (модераторы)</div>
                  {mod.top_reviewers.map((r) => (
                    <div key={r.login} style={{ display: 'flex', gap: 8, fontSize: 13, padding: '3px 0' }}>
                      <span style={{ flex: 1, fontWeight: 600 }}>{r.login}</span>
                      <span style={{ color: 'var(--success)' }}>✓ {r.approved}</span>
                      <span style={{ color: 'var(--danger)' }}>↩ {r.returned}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Частые причины возврата</div>
              {mod.top_reasons.length === 0 ? <span style={muted}>Возвратов за период не было.</span> : mod.top_reasons.map((r, i) => (
                <div key={r.label + i} style={{ display: 'flex', gap: 8, fontSize: 13, padding: '3px 0' }}>
                  <span style={{ color: 'var(--text-faint)', width: 18 }}>{i + 1}.</span>
                  <span style={{ flex: 1 }}>{r.label}</span>
                  <span style={{ color: 'var(--warn)', fontWeight: 600 }}>{r.count}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Section>

      {/* Качество данных */}
      <Section title="Качество данных">
        {!dq ? <span style={muted}>Загрузка…</span> : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 20 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Свежесть по объектам</div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
                  <thead><tr>{['Объект', 'Датасетов', 'Данные на', 'Обновлён'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
                  <tbody>
                    {dq.objects.map((o) => (
                      <tr key={o.name}>
                        <td style={{ ...td, fontWeight: 600 }}>{o.name}</td>
                        <td style={{ ...td, textAlign: 'center', color: o.datasets ? undefined : 'var(--danger)' }}>{o.datasets || '—'}</td>
                        <td style={td}>{o.last_period || <span style={{ color: 'var(--danger)' }}>нет данных</span>}</td>
                        <td style={td}>{o.last_update ? new Date(o.last_update).toLocaleDateString('ru-RU') : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Ошибки расчёта метрик ({dq.metric_errors.length} из {dq.metrics_total})</div>
              {dq.metric_errors.length === 0 ? <div style={{ ...muted, color: 'var(--success)' }}>✓ Все метрики считаются без ошибок.</div> : dq.metric_errors.map((m) => (
                <div key={m.code} style={{ fontSize: 12, marginBottom: 6 }}>
                  <b style={{ color: 'var(--danger)' }}>{m.name}</b> <span style={{ color: 'var(--text-faint)' }}>({m.code})</span>
                  <div style={{ color: 'var(--text-muted)' }}>{m.error}</div>
                </div>
              ))}
              {dq.no_data.length > 0 && (
                <div style={{ marginTop: 10, fontSize: 12, color: 'var(--warn)' }}>⚠ Объекты без данных: {dq.no_data.join(', ')}</div>
              )}
            </div>
          </div>
        )}
      </Section>

      {/* Бизнес-сводка */}
      <Section title="Бизнес-сводка">
        {!biz ? <span style={muted}>Загрузка…</span> : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 20 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Показатели (текущие значения)</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {biz.metrics.length === 0 && <span style={muted}>Метрик пока нет.</span>}
                {biz.metrics.map((m) => (
                  <div key={m.code} style={{ display: 'flex', gap: 8, fontSize: 13, alignItems: 'baseline' }}>
                    <span style={{ flex: 1 }}>{m.name}</span>
                    {m.error
                      ? <span style={{ color: 'var(--danger)', fontSize: 12 }} title={m.error}>ошибка</span>
                      : <b style={{ color: 'var(--accent)' }}>{num(m.value)}{m.unit ? <span style={{ color: 'var(--text-faint)', fontWeight: 400 }}> {m.unit}</span> : ''}</b>}
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Сработавшие KPI-алерты ({biz.alerts.length})</div>
              {biz.alerts.length === 0 ? <div style={{ ...muted, color: 'var(--success)' }}>✓ Активных тревог нет.</div> : biz.alerts.map((a, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, fontSize: 12, alignItems: 'baseline', marginBottom: 4 }}>
                  <span style={{ color: a.level === 'danger' ? 'var(--danger)' : 'var(--warn)' }}>⚠</span>
                  <span style={{ flex: 1 }}><b>{a.widget_name}</b> <span style={{ color: 'var(--text-faint)' }}>· {a.dashboard_name}</span></span>
                  <span style={{ color: a.level === 'danger' ? 'var(--danger)' : 'var(--warn)' }}>{a.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Section>

      <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>
        Журнал действий — в разделе «Аудит». Управление проверкой — в разделе «Модерация».
      </div>
    </div>
  )
}

function GaugeCard({ title, g, sub }: { title: string; g: Gauge; sub: string }) {
  const s = LVL[g.level] || LVL.good
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 12, padding: 12 }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{title}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color: s.c }}>{g.percent}%</div>
      <div style={{ height: 8, background: 'var(--border-faint)', borderRadius: 6, overflow: 'hidden', margin: '4px 0' }}>
        <div style={{ width: `${Math.min(100, g.percent)}%`, height: '100%', background: s.c }} />
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>{sub}</div>
    </div>
  )
}
function Stat({ t, v, danger }: { t: string; v: number; danger?: boolean }) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 12, padding: '10px 16px', textAlign: 'center', minWidth: 84 }}>
      <div style={{ fontSize: 24, fontWeight: 700, color: danger ? 'var(--danger)' : 'var(--accent)' }}>{v}</div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t}</div>
    </div>
  )
}
function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 10 }}>
        <h3 style={{ fontSize: 15, margin: 0 }}>{title}</h3>
        {hint && <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>{hint}</span>}
      </div>
      {children}
    </div>
  )
}

const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 13 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const btnGhost: React.CSSProperties = { height: 32, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text-2)', fontSize: 13, cursor: 'pointer' }
const th: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '6px 10px', background: 'var(--surface-2)', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600 }
const td: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '6px 10px' }


// ── Активность пользователей ────────────────────────────────────────────────
// Выбор сотрудника → его «кабинет» глазами администратора. Список для выбора
// берётся из сводки журнала входов: там уже есть все учётки организации со
// счётчиками, отдельный запрос не нужен.
function UserActivitySection() {
  const [report, setReport] = useState<LoginEventsReport | null>(null)
  const [forbidden, setForbidden] = useState(false)
  const [sel, setSel] = useState('')

  useEffect(() => {
    getLoginEvents()
      .then(setReport)
      .catch((e) => { if (/доступа к аудиту/i.test((e as Error).message)) setForbidden(true) })
  }, [])

  if (forbidden) {
    return (
      <Section title="Активность пользователей">
        <span style={muted}>
          Нужен доступ к журналам аудита. Суперадминистратор выдаёт его в разделе «Пользователи» кнопкой «🕵 дать аудит».
        </span>
      </Section>
    )
  }

  const list = (report?.summary || [])
  return (
    <Section title="Активность пользователей" hint="кто, когда и что делал — по одному сотруднику">
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          Сотрудник:
          <select style={selStyle} value={sel} onChange={(e) => setSel(e.target.value)}>
            <option value="">— выберите —</option>
            {list.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.login}{u.full_name ? ` · ${u.full_name}` : ''}{u.is_active ? '' : ' (заблокирован)'}
              </option>
            ))}
          </select>
        </label>
        {sel && <button style={linkBtnStyle} onClick={() => setSel('')}>очистить</button>}
      </div>
      {!sel
        ? <span style={muted}>Выберите сотрудника — покажем его входы, действия, выгрузки, комментарии и обращения.</span>
        : <UserCard userId={sel} compact />}
    </Section>
  )
}

const selStyle: React.CSSProperties = {
  height: 32, padding: '0 8px', borderRadius: 8, border: '1px solid var(--border-strong)',
  background: 'var(--surface)', color: 'var(--text)', fontSize: 13,
}
const linkBtnStyle: React.CSSProperties = {
  border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 13, padding: 0,
}
