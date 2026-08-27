// Раздел «Статистика услуг ДНР»: сводный обзор + свод по отделениям МФЦ.
//
// Обычный конструктор дашбордов сюда не подходит — нужен список отделений с
// раскрытием по ведомству и услуге внутри строки (аккордеон), а не набор
// виджетов на странице. Верхний уровень — «Обзор»: главные KPI-карточки,
// тренд по ВСЕМ накопленным датам срезов и лента алертов, собранные ОДНИМ
// запросом (`overview`) из тех же данных, что показывает список отделений и
// дашборды ведомства/услуги — второго источника правды здесь нет.
import { useEffect, useMemo, useState } from 'react'
import { authH } from '../api/http'
import { listObjects, type Obj } from '../api/objects'
import { alertLook } from '../lib/alertColors'
import { fmtNumber } from '../lib/format'
import EChart from './EChart'
import { chartColors, useThemeVersion } from '../theme'

function ruDate(iso: string | null | undefined): string {
  return iso ? iso.split('-').reverse().join('.') : '—'
}

function fmt(n: number | null | undefined): string {
  return n == null ? '—' : fmtNumber(n)
}

function signed(n: number | null | undefined): string {
  if (n == null) return '—'
  return (n >= 0 ? '+' : '') + fmt(n)
}

type ServiceRow = {
  name: string
  prioritet: string | null
  okazyvaetsya: string | null
  prinyato_prev: number | null
  prinyato_now: number | null
  prirost_prinyato: number | null
  vydano_prev: number | null
  vydano_now: number | null
  prirost_vydano: number | null
}
type DeptRow = {
  code: string; name: string
  prinyato_prev: number | null; prinyato_now: number | null; prirost: number | null
  vydano_prev: number | null; vydano_now: number | null; vydano_prirost: number | null
  services: ServiceRow[]
}
type OfficeRow = {
  office: string; city: string
  prinyato_prev: number; prinyato_now: number; prirost: number; prirost_pct: number | null
  departments: DeptRow[]; as_of: string | null
}
type OfficesResp = {
  offices: OfficeRow[]; cities: { city: string; prinyato_now: number; prirost: number }[]; total: number
  period_prev: string | null; period_now: string | null
}

export default function DnrStatsPage() {
  const [objects, setObjects] = useState<Obj[] | null>(null)
  const [objectId, setObjectId] = useState<string>('')
  const [view, setView] = useState<'overview' | 'list'>('overview')
  const [deptView, setDeptView] = useState<{ office: string; dept: string } | null>(null)
  const [serviceView, setServiceView] = useState<{ office: string; dept: string; idx: number } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    listObjects().then((list) => {
      setObjects(list)
      const preferred = list.find((o) => o.name.toLowerCase().includes('статистика услуг'))
      setObjectId((preferred || list[0])?.id || '')
    }).catch((e) => setError(String(e.message || e)))
  }, [])

  if (error) return <div style={{ color: 'var(--danger)' }}>{error}</div>
  if (!objectId) return <div style={{ color: 'var(--text-muted)' }}>Загрузка…</div>

  if (serviceView) {
    return <ServiceDashboard objectId={objectId} office={serviceView.office} dept={serviceView.dept} idx={serviceView.idx}
      onBack={() => setServiceView(null)} />
  }
  if (deptView) {
    return <DeptDashboard objectId={objectId} office={deptView.office} dept={deptView.dept}
      onOpenService={(idx) => setServiceView({ office: deptView.office, dept: deptView.dept, idx })}
      onBack={() => setDeptView(null)} />
  }

  const objectPicker = objects && objects.length > 1 && (
    <select value={objectId} onChange={(e) => { setObjectId(e.target.value) }}
      style={{ padding: '4px 8px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', color: 'var(--text)' }}>
      {objects.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
    </select>
  )

  if (view === 'overview') {
    return <OverviewView objectId={objectId} objectPicker={objectPicker} onOpenList={() => setView('list')} />
  }

  return <OfficesList objectId={objectId} objectPicker={objectPicker} onBackToOverview={() => setView('overview')}
    onOpenDept={(office, dept) => setDeptView({ office, dept })} />
}

// ---------------------------------------------------------------------------
// Обзор — верхний уровень раздела.
// ---------------------------------------------------------------------------

type DeptSummary = {
  code: string; name: string; prinyato: number; vydano: number; growth: number | null
  period_prev: string | null; period_now: string | null
}
type TrendPoint = { period: string; prinyato: number; vydano: number }
type KpiRow = {
  index: number; name: string; unit?: string | null
  plan?: number | null; fakt?: number | null; dostizheniya_pokazatelya?: number | null
}
type Alert = { kind: string; text: string }
type Overview = {
  as_of: string | null; period_prev: string | null; kpi_as_of: string | null
  totals: { prinyato: number; vydano: number; growth: number | null; conversion_pct: number | null }
  offices_total: number; offices_no_growth: number
  services_total: number; services_active: number
  leader: DeptSummary | null
  departments: DeptSummary[]
  trend: TrendPoint[]
  satisfaction: KpiRow | null
  wait_time: KpiRow | null
  alerts: Alert[]
}

function alertColor(kind: string): string {
  const level = kind === 'kpi' || kind === 'wait_time' ? 'danger' : 'warn'
  return alertLook({ level })?.color || 'var(--text)'
}

function OverviewView({ objectId, objectPicker, onOpenList }: {
  objectId: string; objectPicker: React.ReactNode; onOpenList: () => void
}) {
  const [d, setD] = useState<Overview | null>(null)
  const [error, setError] = useState('')
  useThemeVersion()

  useEffect(() => {
    setD(null); setError('')
    fetch(`/dnr-stats/${objectId}/overview`, { headers: authH() })
      .then((r) => { if (!r.ok) throw new Error('Не удалось загрузить свод'); return r.json() })
      .then((x) => setD(x))
      .catch((e) => setError(String(e.message || e)))
  }, [objectId])

  const growthOption = useMemo(() => {
    if (!d || d.departments.length === 0) return null
    const cc = chartColors()
    const sorted = [...d.departments].sort((a, b) => (b.growth ?? -Infinity) - (a.growth ?? -Infinity))
    return {
      grid: { left: 60, right: 20, top: 20, bottom: 60 },
      xAxis: { type: 'category', data: sorted.map((x) => x.name), axisLabel: { rotate: sorted.length > 4 ? 30 : 0 } },
      yAxis: { type: 'value' },
      tooltip: { trigger: 'axis' },
      series: [{
        type: 'bar',
        data: sorted.map((x, i) => ({ value: x.growth ?? 0, itemStyle: { color: i === 0 ? cc.c1 : cc.trend } })),
      }],
    }
  }, [d])

  const totalOption = useMemo(() => {
    if (!d || d.departments.length === 0) return null
    const cc = chartColors()
    const sorted = [...d.departments].sort((a, b) => b.prinyato - a.prinyato)
    return {
      grid: { left: 140, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value' },
      yAxis: { type: 'category', data: sorted.map((x) => x.name).reverse(), axisLabel: { fontSize: 11 } },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      series: [{ type: 'bar', data: sorted.map((x) => x.prinyato).reverse(), itemStyle: { color: cc.c1 } }],
    }
  }, [d])

  const trendOption = useMemo(() => {
    if (!d || d.trend.length === 0) return null
    const cc = chartColors()
    return {
      grid: { left: 70, right: 20, top: 20, bottom: 40 },
      xAxis: { type: 'category', data: d.trend.map((p) => ruDate(p.period)) },
      yAxis: { type: 'value' },
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0 },
      series: [
        { name: 'Принято накопительно', type: 'line', data: d.trend.map((p) => p.prinyato),
          itemStyle: { color: cc.c1 }, lineStyle: { color: cc.c1 } },
        { name: 'Выдано накопительно', type: 'line', data: d.trend.map((p) => p.vydano),
          itemStyle: { color: cc.trend }, lineStyle: { color: cc.trend } },
      ],
    }
  }, [d])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 12, marginBottom: 4 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0 }}>Статистика услуг ДНР</h2>
          {objectPicker}
        </div>
        <button onClick={onOpenList} style={linkBtn}>Список отделений →</button>
      </div>

      {error && <div style={{ color: 'var(--danger)', marginBottom: 12 }}>{error}</div>}
      {!d && !error && <div style={{ color: 'var(--text-muted)' }}>Загрузка…</div>}
      {d && (
        <>
          <div style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 16 }}>
            Данные: неделя {ruDate(d.period_prev)} → {ruDate(d.as_of)}
            {d.kpi_as_of ? ` · КПЭ на ${ruDate(d.kpi_as_of)}` : ''}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 20 }}>
            <Card label={`Принято заявлений (на ${ruDate(d.as_of)})`} value={fmt(d.totals.prinyato)}
              sub={d.totals.growth != null ? `${d.totals.growth >= 0 ? '↗' : '↘'} ${signed(d.totals.growth)} за период` : undefined} />
            <Card label={`Выдано результатов (на ${ruDate(d.as_of)})`} value={fmt(d.totals.vydano)} />
            <Card label="Конверсия выдачи" value={d.totals.conversion_pct != null ? `${d.totals.conversion_pct.toFixed(1)}%` : '—'}
              sub="выдано / принято, за период" />
            <Card label="Услуг оказывается" value={`${d.services_active} из ${d.services_total}`}
              sub={d.services_total ? `${((d.services_active / d.services_total) * 100).toFixed(1)}% перечня` : undefined} />
            <Card label="Отделений МФЦ" value={`${d.offices_total}`} sub={`без прироста за период: ${d.offices_no_growth}`} />
            <Card label="Лидер периода по приросту" value={d.leader ? d.leader.name : '—'}
              sub={d.leader?.growth != null ? `↗ ${signed(d.leader.growth)} заявлений` : undefined} />
            {d.satisfaction && d.satisfaction.fakt != null && (
              <Card label={`Удовлетворённость граждан (КПЭ на ${ruDate(d.kpi_as_of)})`} value={`${d.satisfaction.fakt.toFixed(2)}%`}
                sub={d.satisfaction.plan != null ? `план ${d.satisfaction.plan}%` : undefined} />
            )}
            {d.wait_time && d.wait_time.fakt != null && (
              <Card label="Среднее время ожидания" value={`${d.wait_time.fakt.toFixed(2)} мин`}
                sub={d.wait_time.plan != null ? `план ${d.wait_time.plan} мин` : undefined} />
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16, marginBottom: 20 }}>
            {growthOption && (
              <div style={panelStyle}>
                <div style={panelTitle}>Прирост заявлений по ведомствам за период {ruDate(d.period_prev)} → {ruDate(d.as_of)}</div>
                <EChart option={growthOption as any} height={260} />
              </div>
            )}
            {totalOption && (
              <div style={panelStyle}>
                <div style={panelTitle}>Всего заявлений по ведомствам на {ruDate(d.as_of)} (накопительно)</div>
                <EChart option={totalOption as any} height={260} />
              </div>
            )}
          </div>

          {trendOption && (
            <div style={panelStyle}>
              <div style={panelTitle}>Динамика по всем датам срезов ({d.trend.length})</div>
              <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 8 }}>
                Накопительные итоги по всем ведомствам; каждая точка — дата среза из загруженных файлов.
                По мере поступления новых еженедельных файлов на графике сама появится следующая точка.
              </div>
              <EChart option={trendOption as any} height={260} />
            </div>
          )}

          <div style={panelStyle}>
            <div style={panelTitle}>Алерты ({d.alerts.length})</div>
            {d.alerts.length === 0 && <div style={{ color: 'var(--text-muted)' }}>Замечаний нет.</div>}
            {d.alerts.length > 0 && (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {d.alerts.map((a, i) => (
                  <li key={i} style={{ marginBottom: 6, color: alertColor(a.kind) }}>{a.text}</li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px' }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{sub}</div>}
    </div>
  )
}

const panelStyle: React.CSSProperties = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 20 }
const panelTitle: React.CSSProperties = { fontWeight: 600, marginBottom: 8 }
const linkBtn: React.CSSProperties = {
  background: 'none', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 12px',
  cursor: 'pointer', color: 'var(--accent)', fontSize: 13, whiteSpace: 'nowrap',
}

// ---------------------------------------------------------------------------
// Список отделений (прежний уровень 1).
// ---------------------------------------------------------------------------

function OfficesList({ objectId, objectPicker, onBackToOverview, onOpenDept }: {
  objectId: string; objectPicker: React.ReactNode; onBackToOverview: () => void
  onOpenDept: (office: string, dept: string) => void
}) {
  const [data, setData] = useState<OfficesResp | null>(null)
  const [error, setError] = useState('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('total_desc')
  const [open, setOpen] = useState<string | null>(null)
  useThemeVersion()

  useEffect(() => {
    if (!objectId) return
    const t = setTimeout(() => {
      const p = new URLSearchParams({ sort })
      if (q.trim()) p.set('q', q.trim())
      fetch(`/dnr-stats/${objectId}/offices?${p}`, { headers: authH() })
        .then((r) => { if (!r.ok) throw new Error('Не удалось загрузить'); return r.json() })
        .then((d) => { setData(d); setError('') })
        .catch((e) => setError(String(e.message || e)))
    }, 200)
    return () => clearTimeout(t)
  }, [objectId, q, sort])

  const cityOption = useMemo(() => {
    if (!data) return null
    const cc = chartColors()
    const cats = data.cities.map((c) => c.city)
    return {
      grid: { left: 60, right: 20, top: 30, bottom: 60 },
      xAxis: { type: 'category', data: cats, axisLabel: { rotate: 30 } },
      yAxis: { type: 'value' },
      tooltip: { trigger: 'axis' },
      series: [
        { name: 'Принято накопительно', type: 'bar', data: data.cities.map((c) => c.prinyato_now), itemStyle: { color: cc.c1 } },
        { name: 'Прирост за период', type: 'bar', data: data.cities.map((c) => c.prirost), itemStyle: { color: cc.trend } },
      ],
      legend: { bottom: 0 },
    }
  }, [data])

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4, flexWrap: 'wrap' }}>
        <button onClick={onBackToOverview} style={backBtn}>← Обзор</button>
        <h2 style={{ margin: 0 }}>Статистика услуг ДНР</h2>
        {objectPicker}
      </div>
      <div style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 16 }}>
        Отделения МФЦ, ведомства и услуги — свод по последнему выпуску данных
        {data?.period_now ? ` (на ${ruDate(data.period_now)})` : ''}.
      </div>

      {error && <div style={{ color: 'var(--danger)', marginBottom: 12 }}>{error}</div>}
      {!data && !error && <div style={{ color: 'var(--text-muted)' }}>Загрузка…</div>}
      {data && (
      <>

      {cityOption && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>Нагрузка по городам (топ-12)</div>
          <EChart option={cityOption as any} height={260} />
        </div>
      )}

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        <div style={{ fontWeight: 600 }}>Отделения ({data.total})</div>
        <input placeholder="🔍 Поиск по адресу или городу…" value={q} onChange={(e) => setQ(e.target.value)}
          style={{ flex: '1 1 260px', padding: '6px 10px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', color: 'var(--text)' }} />
        <select value={sort} onChange={(e) => setSort(e.target.value)}
          style={{ padding: '6px 10px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', color: 'var(--text)' }}>
          <option value="total_desc">Сортировка: по объёму</option>
          <option value="growth_desc">Сортировка: по приросту</option>
          <option value="name">Сортировка: по названию</option>
        </select>
      </div>

      <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 8 }}>
        Показатель: принятые заявления накопительно; клик по отделению — все показатели по ведомствам и услугам.
      </div>

      <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: 'var(--surface-2)', textAlign: 'left' }}>
              <th style={th}>Отделение</th>
              <th style={th}>Город</th>
              <th style={{ ...th, textAlign: 'right' }}>Принято на {ruDate(data.period_prev)}</th>
              <th style={{ ...th, textAlign: 'right' }}>Принято на {ruDate(data.period_now)}</th>
              <th style={{ ...th, textAlign: 'right' }}>Прирост</th>
              <th style={{ ...th, textAlign: 'right' }}>Прирост, %</th>
            </tr>
          </thead>
          <tbody>
            {data.offices.map((o) => (
              <OfficeRowView key={o.office} o={o} isOpen={open === o.office}
                onToggle={() => setOpen(open === o.office ? null : o.office)}
                onOpenDept={(dept) => onOpenDept(o.office, dept)} />
            ))}
          </tbody>
        </table>
      </div>
      </>
      )}
    </div>
  )
}

const th: React.CSSProperties = { padding: '8px 10px', borderBottom: '1px solid var(--border)', fontWeight: 600 }
const td: React.CSSProperties = { padding: '8px 10px', borderBottom: '1px solid var(--border)', verticalAlign: 'top' }

function OfficeRowView({ o, isOpen, onToggle, onOpenDept }: {
  o: OfficeRow; isOpen: boolean; onToggle: () => void; onOpenDept: (dept: string) => void
}) {
  const maxGrowth = Math.max(1, o.prinyato_now)
  return (
    <>
      <tr onClick={onToggle} style={{ cursor: 'pointer' }} title="Показать ведомства и услуги этого отделения">
        <td style={{ ...td, color: 'var(--accent)' }}>{isOpen ? '▾ ' : '▸ '}{o.office}</td>
        <td style={td}>{o.city}</td>
        <td style={{ ...td, textAlign: 'right' }}>{fmt(o.prinyato_prev)}</td>
        <td style={{ ...td, textAlign: 'right', fontWeight: 600 }}>{fmt(o.prinyato_now)}</td>
        <td style={{ ...td, textAlign: 'right', color: o.prirost >= 0 ? 'var(--good, #0f6e56)' : 'var(--danger)' }}>
          {signed(o.prirost)}
        </td>
        <td style={{ ...td, minWidth: 140 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span>{o.prirost_pct != null ? `${o.prirost_pct.toFixed(1)}%` : '—'}</span>
            <div style={{ flex: 1, height: 6, background: 'var(--surface-2)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(100, (o.prinyato_now / maxGrowth) * 100)}%`, height: '100%', background: 'var(--accent)' }} />
            </div>
          </div>
        </td>
      </tr>
      {isOpen && (
        <tr>
          <td colSpan={6} style={{ ...td, background: 'var(--surface-2)', padding: 16 }}>
            {o.departments.length === 0 && <div style={{ color: 'var(--text-muted)' }}>Нет данных по ведомствам.</div>}
            {o.departments.map((d) => <DeptBlock key={d.code} d={d} onOpenDashboard={() => onOpenDept(d.code)} />)}
          </td>
        </tr>
      )}
    </>
  )
}

function DeptBlock({ d, onOpenDashboard }: { d: DeptRow; onOpenDashboard: () => void }) {
  return (
    <div style={{ marginBottom: 14, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
      <div style={{ fontWeight: 700, marginBottom: 6, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span>
          {d.name} <span style={{ fontWeight: 400, color: 'var(--text-muted)', fontSize: 12 }}>
            оказано всего: {fmt(d.prinyato_now)} · прирост принятых: {signed(d.prirost)} ·
            выдано всего: {fmt(d.vydano_now)} · прирост выданных: {signed(d.vydano_prirost)}
          </span>
        </span>
        <button onClick={onOpenDashboard} title="Открыть дашборд этого ведомства для этого отделения"
          style={{ fontWeight: 400, fontSize: 12, color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', whiteSpace: 'nowrap' }}>
          → дашборд ведомства
        </button>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
        <thead>
          <tr style={{ textAlign: 'left', color: 'var(--text-muted)' }}>
            <th style={thSmall}>Услуга</th>
            <th style={thSmall}>Приорит.</th>
            <th style={thSmall}>Оказывается</th>
            <th style={{ ...thSmall, textAlign: 'right' }}>Принято прошлый раз</th>
            <th style={{ ...thSmall, textAlign: 'right' }}>Принято сейчас</th>
            <th style={{ ...thSmall, textAlign: 'right' }}>Прирост</th>
            <th style={{ ...thSmall, textAlign: 'right' }}>Выдано сейчас</th>
            <th style={{ ...thSmall, textAlign: 'right' }}>Доля</th>
          </tr>
        </thead>
        <tbody>
          {d.services.map((s, i) => {
            const inactive = s.okazyvaetsya === 'нет'
            const share = d.prinyato_now ? ((s.prinyato_now || 0) / d.prinyato_now * 100) : null
            return (
              <tr key={i} style={inactive ? { color: 'var(--text-faint)' } : undefined}>
                <td style={tdSmall} title={s.name}>{s.name.length > 90 ? s.name.slice(0, 87) + '…' : s.name}</td>
                <td style={tdSmall}>{s.prioritet ?? '—'}</td>
                <td style={{ ...tdSmall, color: inactive ? 'var(--danger)' : undefined }}>{s.okazyvaetsya ?? '—'}</td>
                <td style={{ ...tdSmall, textAlign: 'right' }}>{fmt(s.prinyato_prev)}</td>
                <td style={{ ...tdSmall, textAlign: 'right' }}>{fmt(s.prinyato_now)}</td>
                <td style={{ ...tdSmall, textAlign: 'right', color: (s.prirost_prinyato || 0) > 0 ? 'var(--good, #0f6e56)' : undefined }}>
                  {s.prirost_prinyato != null ? signed(s.prirost_prinyato) : '—'}
                </td>
                <td style={{ ...tdSmall, textAlign: 'right' }}>{fmt(s.vydano_now)}</td>
                <td style={{ ...tdSmall, textAlign: 'right' }}>{share != null ? `${share.toFixed(1)}%` : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

const thSmall: React.CSSProperties = { padding: '4px 8px', borderBottom: '1px solid var(--border)' }
const tdSmall: React.CSSProperties = { padding: '4px 8px', borderBottom: '1px solid var(--border)' }

type DeptDetail = {
  office: string; city: string; department: { code: string; name: string }
  as_of: string | null; period_prev: string | null; period_now: string | null
  prinyato_prev: number | null; prinyato_now: number | null; prirost: number | null
  vydano_prev: number | null; vydano_now: number | null; vydano_prirost: number | null
  conversion_pct: number | null; active_services: number; total_services: number
  services: ServiceRow[]
  rank: { place: number | null; total: number; top10: { office: string; value: number }[] }
}

function DeptDashboard({ objectId, office, dept, onBack, onOpenService }: {
  objectId: string; office: string; dept: string; onBack: () => void; onOpenService: (idx: number) => void
}) {
  const [d, setD] = useState<DeptDetail | null>(null)
  const [error, setError] = useState('')
  useThemeVersion()

  useEffect(() => {
    const p = new URLSearchParams({ office, dept })
    fetch(`/dnr-stats/${objectId}/office-department?${p}`, { headers: authH() })
      .then((r) => { if (!r.ok) throw new Error('Не удалось загрузить'); return r.json() })
      .then((x) => { setD(x); setError('') })
      .catch((e) => setError(String(e.message || e)))
  }, [objectId, office, dept])

  const trendOption = useMemo(() => {
    if (!d) return null
    const cc = chartColors()
    return {
      grid: { left: 60, right: 20, top: 30, bottom: 40 },
      xAxis: { type: 'category', data: [ruDate(d.period_prev), ruDate(d.period_now)] },
      yAxis: { type: 'value' },
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0 },
      series: [
        { name: 'Принято накоп.', type: 'bar', data: [d.prinyato_prev, d.prinyato_now], itemStyle: { color: cc.c1 } },
        { name: 'Выдано накоп.', type: 'bar', data: [d.vydano_prev, d.vydano_now], itemStyle: { color: cc.trend } },
      ],
    }
  }, [d])

  const servicesOption = useMemo(() => {
    if (!d) return null
    const cc = chartColors()
    const sorted = [...d.services].sort((a, b) => (b.prinyato_now || 0) - (a.prinyato_now || 0))
    return {
      grid: { left: 220, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value' },
      yAxis: { type: 'category', data: sorted.map((s) => s.name.length > 40 ? s.name.slice(0, 37) + '…' : s.name).reverse(),
        axisLabel: { fontSize: 11 } },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      series: [
        { name: `Принято на ${ruDate(d.period_now)}`, type: 'bar', data: sorted.map((s) => s.prinyato_now || 0).reverse(), itemStyle: { color: cc.c1 } },
        { name: `Выдано на ${ruDate(d.period_now)}`, type: 'bar', data: sorted.map((s) => s.vydano_now || 0).reverse(), itemStyle: { color: cc.trend } },
      ],
      legend: { bottom: 0 },
    }
  }, [d])

  const rankOption = useMemo(() => {
    if (!d) return null
    const cc = chartColors()
    const shortThis = d.office
    // ECharts (SVG-рендерер) не резолвит var(...) в itemStyle.color сам — та же
    // ловушка, что и во всех графиках проекта: цвет берём из токена ЗАРАНЕЕ,
    // тем же способом, что chartColors() читает палитру серий.
    const muted = getComputedStyle(document.documentElement).getPropertyValue('--border').trim() || '#d9d2c9'
    return {
      grid: { left: 20, right: 20, top: 10, bottom: 60 },
      xAxis: { type: 'category', data: d.rank.top10.map((r) => r.office), axisLabel: { rotate: 30 } },
      yAxis: { type: 'value' },
      tooltip: { trigger: 'axis' },
      series: [{
        type: 'bar', data: d.rank.top10.map((r) => ({
          value: r.value,
          itemStyle: { color: r.office === _short(shortThis) ? cc.c1 : muted },
        })),
      }],
    }
  }, [d])

  if (error) return <div><button onClick={onBack} style={backBtn}>← Назад</button><div style={{ color: 'var(--danger)', marginTop: 12 }}>{error}</div></div>
  if (!d) return <div><button onClick={onBack} style={backBtn}>← Назад</button><div style={{ color: 'var(--text-muted)', marginTop: 12 }}>Загрузка…</div></div>

  return (
    <div>
      <button onClick={onBack} style={backBtn}>← Назад</button>
      <h2 style={{ margin: '10px 0 2px' }}>{d.department.name} — дашборд ведомства</h2>
      <div style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 16 }}>{d.office}</div>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
        <Card label={`Принято накоп. на ${ruDate(d.period_now)}`} value={fmt(d.prinyato_now)}
          sub={`прирост: ${signed(d.prirost)} с ${ruDate(d.period_prev)}`} />
        <Card label={`Выдано накоп. на ${ruDate(d.period_now)}`} value={fmt(d.vydano_now)}
          sub={`прирост: ${signed(d.vydano_prirost)}`} />
        <Card label="Конверсия выдано/принято" value={d.conversion_pct != null ? `${d.conversion_pct.toFixed(1)}%` : '—'} />
        <Card label="Предоставляемых услуг" value={`${d.active_services}`} sub={`всего в ведомстве: ${d.total_services}`} />
        <Card label="Место среди отделений" value={d.rank.place ? `${d.rank.place} из ${d.rank.total}` : '—'}
          sub={`по принятым на ${ruDate(d.period_now)}`} />
      </div>

      {trendOption && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>Динамика ведомства по датам срезов</div>
          <EChart option={trendOption as any} height={240} />
        </div>
      )}

      {servicesOption && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>Все услуги ведомства в этом отделении — принято и выдано на {ruDate(d.period_now)}</div>
          <EChart option={servicesOption as any} height={Math.max(160, d.services.length * 34)} />
        </div>
      )}

      {rankOption && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>
            Сравнение с другими отделениями (топ-10 по принятым на {ruDate(d.period_now)}; выделено — это отделение)
          </div>
          <EChart option={rankOption as any} height={260} />
        </div>
      )}

      <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr style={{ background: 'var(--surface-2)', textAlign: 'left' }}>
              <th style={thSmall}>Услуга</th>
              <th style={thSmall}>Приорит.</th>
              <th style={thSmall}>Оказывается</th>
              <th style={{ ...thSmall, textAlign: 'right' }}>Принято {ruDate(d.period_prev)}</th>
              <th style={{ ...thSmall, textAlign: 'right' }}>Принято {ruDate(d.period_now)}</th>
              <th style={{ ...thSmall, textAlign: 'right' }}>Прирост</th>
              <th style={{ ...thSmall, textAlign: 'right' }}>Выдано {ruDate(d.period_now)}</th>
              <th style={{ ...thSmall, textAlign: 'right' }}>Доля</th>
            </tr>
          </thead>
          <tbody>
            {d.services.map((s, i) => {
              const inactive = s.okazyvaetsya === 'нет'
              const share = d.prinyato_now ? ((s.prinyato_now || 0) / d.prinyato_now * 100) : null
              return (
                <tr key={i} style={{ cursor: 'pointer', ...(inactive ? { color: 'var(--text-faint)' } : {}) }}
                  onClick={() => onOpenService(i + 1)} title="Открыть дашборд этой услуги">
                  <td style={{ ...tdSmall, color: 'var(--accent)' }}>{s.name}</td>
                  <td style={tdSmall}>{s.prioritet ?? '—'}</td>
                  <td style={{ ...tdSmall, color: inactive ? 'var(--danger)' : undefined }}>{s.okazyvaetsya ?? '—'}</td>
                  <td style={{ ...tdSmall, textAlign: 'right' }}>{fmt(s.prinyato_prev)}</td>
                  <td style={{ ...tdSmall, textAlign: 'right' }}>{fmt(s.prinyato_now)}</td>
                  <td style={{ ...tdSmall, textAlign: 'right', color: (s.prirost_prinyato || 0) > 0 ? 'var(--good, #0f6e56)' : undefined }}>
                    {s.prirost_prinyato != null ? signed(s.prirost_prinyato) : '—'}
                  </td>
                  <td style={{ ...tdSmall, textAlign: 'right' }}>{fmt(s.vydano_now)}</td>
                  <td style={{ ...tdSmall, textAlign: 'right' }}>{share != null ? `${share.toFixed(1)}%` : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function _short(label: string): string {
  for (const marker of ['г. ', 'г.']) {
    const i = label.indexOf(marker)
    if (i !== -1) return label.slice(i + marker.length).split(',')[0].trim()
  }
  return label.slice(0, 20)
}

const backBtn: React.CSSProperties = {
  background: 'none', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 12px',
  cursor: 'pointer', color: 'var(--text)', fontSize: 13,
}

type ServiceDetail = {
  office: string; city: string; department: { code: string; name: string }
  as_of: string | null; period_prev: string | null; period_now: string | null
  service: ServiceRow; service_index: number; conversion_pct: number | null
  rank: { place: number | null; total: number; top10: { office: string; value: number }[] }
}

function ServiceDashboard({ objectId, office, dept, idx, onBack }: {
  objectId: string; office: string; dept: string; idx: number; onBack: () => void
}) {
  const [d, setD] = useState<ServiceDetail | null>(null)
  const [error, setError] = useState('')
  useThemeVersion()

  useEffect(() => {
    const p = new URLSearchParams({ office, dept, idx: String(idx) })
    fetch(`/dnr-stats/${objectId}/office-service?${p}`, { headers: authH() })
      .then((r) => { if (!r.ok) throw new Error('Не удалось загрузить'); return r.json() })
      .then((x) => { setD(x); setError('') })
      .catch((e) => setError(String(e.message || e)))
  }, [objectId, office, dept, idx])

  const trendOption = useMemo(() => {
    if (!d) return null
    const cc = chartColors()
    return {
      grid: { left: 60, right: 20, top: 30, bottom: 40 },
      xAxis: { type: 'category', data: [ruDate(d.period_prev), ruDate(d.period_now)] },
      yAxis: { type: 'value' },
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0 },
      series: [
        { name: 'Принято накоп.', type: 'bar', data: [d.service.prinyato_prev, d.service.prinyato_now], itemStyle: { color: cc.c1 } },
        { name: 'Выдано накоп.', type: 'bar', data: [d.service.vydano_prev, d.service.vydano_now], itemStyle: { color: cc.trend } },
      ],
    }
  }, [d])

  const rankOption = useMemo(() => {
    if (!d) return null
    const cc = chartColors()
    const muted = getComputedStyle(document.documentElement).getPropertyValue('--border').trim() || '#d9d2c9'
    const shortThis = _short(d.office)
    return {
      grid: { left: 20, right: 20, top: 10, bottom: 60 },
      xAxis: { type: 'category', data: d.rank.top10.map((r) => r.office), axisLabel: { rotate: 30 } },
      yAxis: { type: 'value' },
      tooltip: { trigger: 'axis' },
      series: [{
        type: 'bar', data: d.rank.top10.map((r) => ({
          value: r.value,
          itemStyle: { color: r.office === shortThis ? cc.c1 : muted },
        })),
      }],
    }
  }, [d])

  if (error) return <div><button onClick={onBack} style={backBtn}>← Назад</button><div style={{ color: 'var(--danger)', marginTop: 12 }}>{error}</div></div>
  if (!d) return <div><button onClick={onBack} style={backBtn}>← Назад</button><div style={{ color: 'var(--text-muted)', marginTop: 12 }}>Загрузка…</div></div>

  const s = d.service
  const inactive = s.okazyvaetsya === 'нет'

  return (
    <div>
      <button onClick={onBack} style={backBtn}>← Назад</button>
      <h2 style={{ margin: '10px 0 2px' }}>{s.name}</h2>
      <div style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 16 }}>
        {d.department.name} · {d.office}
      </div>

      {inactive && (
        <div style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 16, color: 'var(--danger)' }}>
          ⚠ В этом отделении услуга не оказывается{s.okazyvaetsya ? '' : ' — данных нет'}.
        </div>
      )}

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
        <Card label={`Принято накоп. на ${ruDate(d.period_now)}`} value={fmt(s.prinyato_now)}
          sub={`прирост: ${signed(s.prirost_prinyato)} с ${ruDate(d.period_prev)}`} />
        <Card label={`Выдано накоп. на ${ruDate(d.period_now)}`} value={fmt(s.vydano_now)}
          sub={`прирост: ${signed(s.prirost_vydano)}`} />
        <Card label="Конверсия выдано/принято" value={d.conversion_pct != null ? `${d.conversion_pct.toFixed(1)}%` : '—'} />
        <Card label="Приоритетная услуга" value={s.prioritet ?? '—'} />
        <Card label="Место среди отделений" value={d.rank.place ? `${d.rank.place} из ${d.rank.total}` : '—'}
          sub={`по принятым на ${ruDate(d.period_now)}`} />
      </div>

      {trendOption && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>Динамика услуги по всем датам срезов</div>
          <EChart option={trendOption as any} height={240} />
        </div>
      )}

      {rankOption && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>
            Сравнение с другими отделениями (топ-10 по принятым на {ruDate(d.period_now)}; выделено — это отделение)
          </div>
          <EChart option={rankOption as any} height={260} />
        </div>
      )}
    </div>
  )
}
