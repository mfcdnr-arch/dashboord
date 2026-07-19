import { useEffect, useState } from 'react'
import { getAttendanceReport, getSystemReport, type AttendanceReport, type Gauge, type SystemReport } from '../api'

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
  const [error, setError] = useState<string | null>(null)

  const loadSys = () => getSystemReport().then(setSys).catch((e) => setError((e as Error).message))
  useEffect(() => {
    if (!me.roles.includes('admin')) return
    loadSys(); getAttendanceReport().then(setAtt).catch((e) => setError((e as Error).message))
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

      <div style={{ fontSize: 12, color: '#9aa4b2' }}>
        Другие отчёты (аудит действий, качество данных, модерация, бизнес-сводки) — в разработке.
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
