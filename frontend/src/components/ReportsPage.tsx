import { useEffect, useState } from 'react'
import {
  getAttendanceReport, getBusinessReport, getDashboardViewers, getDataQualityReport, getModerationReport, getPopularityReport, getSystemReport,
  type AttendanceReport, type BusinessReport, type DashboardViewers, type DataQualityReport, type Gauge, type ModerationReport, type PopularityReport, type SystemReport,
} from '../api'
import EChart from './EChartLazy'

function num(n: number | null): string {
  if (n == null || !isFinite(n)) return '—'
  return Number.isInteger(n) ? n.toLocaleString('ru-RU') : n.toFixed(2)
}

// Раздел «Отчёты» (admin): системный мониторинг (CPU/RAM/диск через psutil +
// статусы сервисов, с порогами) и посещаемость (по login_events).

const LVL: Record<string, { c: string; bg: string }> = {
  good: { c: '#0f6e56', bg: '#e8f5f0' }, warn: { c: '#9a6a00', bg: '#fff4e0' }, danger: { c: '#a32d2d', bg: '#fcebeb' },
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

export default function ReportsPage({ me }: { me: { roles: string[] } }) {
  const [sys, setSys] = useState<SystemReport | null>(null)
  const [att, setAtt] = useState<AttendanceReport | null>(null)
  const [dq, setDq] = useState<DataQualityReport | null>(null)
  const [biz, setBiz] = useState<BusinessReport | null>(null)
  const [pop, setPop] = useState<PopularityReport | null>(null)
  const [viewers, setViewers] = useState<DashboardViewers | null>(null)
  const [mod, setMod] = useState<ModerationReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadSys = () => getSystemReport().then(setSys).catch((e) => setError((e as Error).message))
  useEffect(() => {
    if (!me.roles.includes('admin')) return
    loadSys()
    getAttendanceReport().then(setAtt).catch((e) => setError((e as Error).message))
    getPopularityReport().then(setPop).catch((e) => setError((e as Error).message))
    getModerationReport().then(setMod).catch((e) => setError((e as Error).message))
    getDataQualityReport().then(setDq).catch((e) => setError((e as Error).message))
    getBusinessReport().then(setBiz).catch((e) => setError((e as Error).message))
    const t = setInterval(loadSys, 15000) // авто-обновление мониторинга
    return () => clearInterval(t)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (!me.roles.includes('admin')) return <div style={{ color: '#a32d2d' }}>Раздел «Отчёты» доступен только администратору.</div>

  const maxDay = Math.max(1, ...(att?.per_day.map((d) => d.logins + d.failed) || [1]))

  return (
    <div>
      <h2 style={{ fontSize: 20, margin: '0 0 16px' }}>Отчёты</h2>
      {error && <div style={errBox}>{error}</div>}

      {/* Системный мониторинг */}
      <Section title="Системный мониторинг" hint="обновляется автоматически каждые 15 с">
        {!sys ? <span style={muted}>Загрузка…</span> : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 12 }}>
              <GaugeCard title="Процессор (CPU)" g={sys.cpu} sub={`${sys.cores} ядер${sys.load ? ` · load ${sys.load.map((x) => x.toFixed(2)).join(' ')}` : ''}`} />
              <GaugeCard title="Память (RAM)" g={sys.memory} sub={`${fmtBytes(sys.memory.used)} из ${fmtBytes(sys.memory.total)}`} />
              <GaugeCard title="Диск" g={sys.disk} sub={`${fmtBytes(sys.disk.used)} из ${fmtBytes(sys.disk.total)}`} />
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center', fontSize: 13, color: '#374151' }}>
              <span>Аптайм: <b>{fmtUptime(sys.uptime_sec)}</b></span>
              <span>Размер БД: <b>{fmtBytes(sys.db_size)}</b></span>
              <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>Сервисы:
                {sys.services.map((s) => (
                  <span key={s.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 10, background: s.ok ? '#e8f5f0' : '#fcebeb', color: s.ok ? '#0f6e56' : '#a32d2d' }}>
                    {s.ok ? '●' : '○'} {s.name}
                  </span>
                ))}
              </span>
            </div>
          </>
        )}
      </Section>

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
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 90, borderBottom: '1px solid #e5e7eb' }}>
                {att.per_day.length === 0 && <span style={muted}>Нет данных.</span>}
                {att.per_day.map((d) => (
                  <div key={d.day} title={`${d.day}: входов ${d.logins}, неудач ${d.failed}`} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', alignItems: 'center', gap: 2 }}>
                    {d.failed > 0 && <div style={{ width: '70%', height: `${(d.failed / maxDay) * 70}px`, background: '#e6a5a5', borderRadius: '2px 2px 0 0' }} />}
                    <div style={{ width: '70%', height: `${(d.logins / maxDay) * 70}px`, background: '#2f5496', borderRadius: '2px 2px 0 0' }} />
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Активнее всех</div>
              {att.top_users.length === 0 ? <span style={muted}>Нет входов за период.</span> : att.top_users.map((u, i) => (
                <div key={u.login} style={{ display: 'flex', gap: 8, fontSize: 13, padding: '3px 0' }}>
                  <span style={{ color: '#9aa4b2', width: 18 }}>{i + 1}.</span>
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
                      series: [{ type: 'bar', data: pop.top_dashboards.map((d) => d.views), itemStyle: { color: '#2f5496', borderRadius: [0, 4, 4, 0] }, barMaxWidth: 20, label: { show: true, position: 'right', fontSize: 11 } }],
                    }} />
                  <div style={{ ...muted, fontSize: 11 }}>Клик по столбцу — кто смотрел дашборд.</div>
                </div>
                <div>
                  {viewers ? (
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                        Кто смотрел: {viewers.name}
                        <button style={{ border: 'none', background: 'none', color: '#2f5496', cursor: 'pointer', fontSize: 12, marginLeft: 8 }} onClick={() => setViewers(null)}>× сбросить</button>
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
                              <td style={{ ...td, color: '#9aa4b2', textAlign: 'center' }}>{i + 1}</td>
                              <td style={{ ...td, fontWeight: 600 }}>{d.name}</td>
                              <td style={{ ...td, textAlign: 'center' }}>{d.views}</td>
                              <td style={{ ...td, textAlign: 'center' }}>{d.viewers}</td>
                              <td style={{ ...td, whiteSpace: 'nowrap' }}><button style={{ border: 'none', background: 'none', color: '#2f5496', cursor: 'pointer', fontSize: 12 }} onClick={() => getDashboardViewers(d.dashboard_id).then(setViewers).catch((e) => setError((e as Error).message))}>кто смотрел</button></td>
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
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 13, color: '#374151' }}>
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
                      <span style={{ color: '#0f6e56' }}>✓ {r.approved}</span>
                      <span style={{ color: '#a32d2d' }}>↩ {r.returned}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Частые причины возврата</div>
              {mod.top_reasons.length === 0 ? <span style={muted}>Возвратов за период не было.</span> : mod.top_reasons.map((r, i) => (
                <div key={r.label + i} style={{ display: 'flex', gap: 8, fontSize: 13, padding: '3px 0' }}>
                  <span style={{ color: '#9aa4b2', width: 18 }}>{i + 1}.</span>
                  <span style={{ flex: 1 }}>{r.label}</span>
                  <span style={{ color: '#9a6a00', fontWeight: 600 }}>{r.count}</span>
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
                        <td style={{ ...td, textAlign: 'center', color: o.datasets ? undefined : '#a32d2d' }}>{o.datasets || '—'}</td>
                        <td style={td}>{o.last_period || <span style={{ color: '#a32d2d' }}>нет данных</span>}</td>
                        <td style={td}>{o.last_update ? new Date(o.last_update).toLocaleDateString('ru-RU') : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Ошибки расчёта метрик ({dq.metric_errors.length} из {dq.metrics_total})</div>
              {dq.metric_errors.length === 0 ? <div style={{ ...muted, color: '#0f6e56' }}>✓ Все метрики считаются без ошибок.</div> : dq.metric_errors.map((m) => (
                <div key={m.code} style={{ fontSize: 12, marginBottom: 6 }}>
                  <b style={{ color: '#a32d2d' }}>{m.name}</b> <span style={{ color: '#9aa4b2' }}>({m.code})</span>
                  <div style={{ color: '#6b7280' }}>{m.error}</div>
                </div>
              ))}
              {dq.no_data.length > 0 && (
                <div style={{ marginTop: 10, fontSize: 12, color: '#9a6a00' }}>⚠ Объекты без данных: {dq.no_data.join(', ')}</div>
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
                      ? <span style={{ color: '#a32d2d', fontSize: 12 }} title={m.error}>ошибка</span>
                      : <b style={{ color: '#2f5496' }}>{num(m.value)}{m.unit ? <span style={{ color: '#9aa4b2', fontWeight: 400 }}> {m.unit}</span> : ''}</b>}
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Сработавшие KPI-алерты ({biz.alerts.length})</div>
              {biz.alerts.length === 0 ? <div style={{ ...muted, color: '#0f6e56' }}>✓ Активных тревог нет.</div> : biz.alerts.map((a, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, fontSize: 12, alignItems: 'baseline', marginBottom: 4 }}>
                  <span style={{ color: a.level === 'danger' ? '#a32d2d' : '#9a6a00' }}>⚠</span>
                  <span style={{ flex: 1 }}><b>{a.widget_name}</b> <span style={{ color: '#9aa4b2' }}>· {a.dashboard_name}</span></span>
                  <span style={{ color: a.level === 'danger' ? '#a32d2d' : '#9a6a00' }}>{a.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Section>

      <div style={{ fontSize: 12, color: '#9aa4b2' }}>
        Журнал действий — в разделе «Аудит». Управление проверкой — в разделе «Модерация».
      </div>
    </div>
  )
}

function GaugeCard({ title, g, sub }: { title: string; g: Gauge; sub: string }) {
  const s = LVL[g.level] || LVL.good
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 12, padding: 12 }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{title}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color: s.c }}>{g.percent}%</div>
      <div style={{ height: 8, background: '#eef0f3', borderRadius: 6, overflow: 'hidden', margin: '4px 0' }}>
        <div style={{ width: `${Math.min(100, g.percent)}%`, height: '100%', background: s.c }} />
      </div>
      <div style={{ fontSize: 11, color: '#9aa4b2' }}>{sub}</div>
    </div>
  )
}
function Stat({ t, v, danger }: { t: string; v: number; danger?: boolean }) {
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 12, padding: '10px 16px', textAlign: 'center', minWidth: 84 }}>
      <div style={{ fontSize: 24, fontWeight: 700, color: danger ? '#a32d2d' : '#2f5496' }}>{v}</div>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{t}</div>
    </div>
  )
}
function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 10 }}>
        <h3 style={{ fontSize: 15, margin: 0 }}>{title}</h3>
        {hint && <span style={{ fontSize: 12, color: '#9aa4b2' }}>{hint}</span>}
      </div>
      {children}
    </div>
  )
}

const muted: React.CSSProperties = { color: '#9aa4b2', fontSize: 13 }
const errBox: React.CSSProperties = { background: '#fcebeb', color: '#a32d2d', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const th: React.CSSProperties = { border: '1px solid #eef0f3', padding: '6px 10px', background: '#f9fafb', textAlign: 'left', color: '#6b7280', fontWeight: 600 }
const td: React.CSSProperties = { border: '1px solid #eef0f3', padding: '6px 10px' }
