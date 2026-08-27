// Раздел «Статистика услуг ДНР»: свод по отделениям МФЦ.
//
// Обычный конструктор дашбордов сюда не подходит — нужен список отделений с
// раскрытием по ведомству и услуге внутри строки (аккордеон), а не набор
// виджетов на странице. Первый кусок по согласованному плану: список
// отделений + нагрузка по городам + раскрытие по клику. Дальше по тому же
// образцу достраиваются вкладки «Ведомства»/«Услуги» и дашборды услуги/
// ведомства — когда будут размечены остальные 11 ведомств.
import { useEffect, useMemo, useState } from 'react'
import { authH } from '../api/http'
import { listObjects, type Obj } from '../api/objects'
import { fmtNumber } from '../lib/format'
import EChart from './EChart'
import { chartColors, useThemeVersion } from '../theme'

type ServiceRow = {
  name: string
  prioritet: string | null
  okazyvaetsya: string | null
  prinyato_12: number | null
  prinyato_19: number | null
  prirost_prinyato: number | null
  vydano_12: number | null
  vydano_19: number | null
  prirost_vydano: number | null
}
type DeptRow = {
  code: string; name: string
  prinyato_12: number | null; prinyato_19: number | null; prirost: number | null
  vydano_12: number | null; vydano_19: number | null; vydano_prirost: number | null
  services: ServiceRow[]
}
type OfficeRow = {
  office: string; city: string
  prinyato_12: number; prinyato_19: number; prirost: number; prirost_pct: number | null
  departments: DeptRow[]; as_of: string | null
}
type Resp = { offices: OfficeRow[]; cities: { city: string; prinyato_19: number; prirost: number }[]; total: number }

function fmt(n: number | null | undefined): string {
  return n == null ? '—' : fmtNumber(n)
}

export default function DnrStatsPage() {
  const [objects, setObjects] = useState<Obj[] | null>(null)
  const [objectId, setObjectId] = useState<string>('')
  const [data, setData] = useState<Resp | null>(null)
  const [error, setError] = useState('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('total_desc')
  const [open, setOpen] = useState<string | null>(null)
  const [deptView, setDeptView] = useState<{ office: string; dept: string } | null>(null)
  const [serviceView, setServiceView] = useState<{ office: string; dept: string; idx: number } | null>(null)
  useThemeVersion()

  useEffect(() => {
    listObjects().then((list) => {
      setObjects(list)
      const preferred = list.find((o) => o.name.toLowerCase().includes('статистика услуг'))
      setObjectId((preferred || list[0])?.id || '')
    }).catch((e) => setError(String(e.message || e)))
  }, [])

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
        { name: 'Принято накопительно', type: 'bar', data: data.cities.map((c) => c.prinyato_19), itemStyle: { color: cc.c1 } },
        { name: 'Прирост за период', type: 'bar', data: data.cities.map((c) => c.prirost), itemStyle: { color: cc.trend } },
      ],
      legend: { bottom: 0 },
    }
  }, [data])

  if (serviceView) {
    return <ServiceDashboard objectId={objectId} office={serviceView.office} dept={serviceView.dept} idx={serviceView.idx}
      onBack={() => setServiceView(null)} />
  }

  if (deptView) {
    return <DeptDashboard objectId={objectId} office={deptView.office} dept={deptView.dept}
      onOpenService={(idx) => setServiceView({ office: deptView.office, dept: deptView.dept, idx })}
      onBack={() => setDeptView(null)} />
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Статистика услуг ДНР</h2>
        {objects && objects.length > 1 && (
          <select value={objectId} onChange={(e) => { setOpen(null); setObjectId(e.target.value) }}
            style={{ padding: '4px 8px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', color: 'var(--text)' }}>
            {objects.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        )}
      </div>
      <div style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 16 }}>
        Отделения МФЦ, ведомства и услуги — свод по последнему выпуску данных
        {data?.offices[0]?.as_of ? ` (на ${data.offices[0].as_of.split('-').reverse().join('.')})` : ''}.
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
              <th style={{ ...th, textAlign: 'right' }}>Принято на 12.08.2026</th>
              <th style={{ ...th, textAlign: 'right' }}>Принято на 19.08.2026</th>
              <th style={{ ...th, textAlign: 'right' }}>Прирост</th>
              <th style={{ ...th, textAlign: 'right' }}>Прирост, %</th>
            </tr>
          </thead>
          <tbody>
            {data.offices.map((o) => (
              <OfficeRowView key={o.office} o={o} isOpen={open === o.office}
                onToggle={() => setOpen(open === o.office ? null : o.office)}
                onOpenDept={(dept) => setDeptView({ office: o.office, dept })} />
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
  const maxGrowth = Math.max(1, o.prinyato_19)
  return (
    <>
      <tr onClick={onToggle} style={{ cursor: 'pointer' }} title="Показать ведомства и услуги этого отделения">
        <td style={{ ...td, color: 'var(--accent)' }}>{isOpen ? '▾ ' : '▸ '}{o.office}</td>
        <td style={td}>{o.city}</td>
        <td style={{ ...td, textAlign: 'right' }}>{fmt(o.prinyato_12)}</td>
        <td style={{ ...td, textAlign: 'right', fontWeight: 600 }}>{fmt(o.prinyato_19)}</td>
        <td style={{ ...td, textAlign: 'right', color: o.prirost >= 0 ? 'var(--good, #0f6e56)' : 'var(--danger)' }}>
          {o.prirost >= 0 ? '+' : ''}{fmt(o.prirost)}
        </td>
        <td style={{ ...td, minWidth: 140 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span>{o.prirost_pct != null ? `${o.prirost_pct.toFixed(1)}%` : '—'}</span>
            <div style={{ flex: 1, height: 6, background: 'var(--surface-2)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(100, (o.prinyato_19 / maxGrowth) * 100)}%`, height: '100%', background: 'var(--accent)' }} />
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
            оказано всего: {fmt(d.prinyato_19)} · прирост принятых: {d.prirost != null && d.prirost >= 0 ? '+' : ''}{fmt(d.prirost)} ·
            выдано всего: {fmt(d.vydano_19)} · прирост выданных: {d.vydano_prirost != null && d.vydano_prirost >= 0 ? '+' : ''}{fmt(d.vydano_prirost)}
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
            <th style={{ ...thSmall, textAlign: 'right' }}>Принято 12.08</th>
            <th style={{ ...thSmall, textAlign: 'right' }}>Принято 19.08</th>
            <th style={{ ...thSmall, textAlign: 'right' }}>Прирост</th>
            <th style={{ ...thSmall, textAlign: 'right' }}>Выдано 19.08</th>
            <th style={{ ...thSmall, textAlign: 'right' }}>Доля</th>
          </tr>
        </thead>
        <tbody>
          {d.services.map((s, i) => {
            const inactive = s.okazyvaetsya === 'нет'
            const share = d.prinyato_19 ? ((s.prinyato_19 || 0) / d.prinyato_19 * 100) : null
            return (
              <tr key={i} style={inactive ? { color: 'var(--text-faint)' } : undefined}>
                <td style={tdSmall} title={s.name}>{s.name.length > 90 ? s.name.slice(0, 87) + '…' : s.name}</td>
                <td style={tdSmall}>{s.prioritet ?? '—'}</td>
                <td style={{ ...tdSmall, color: inactive ? 'var(--danger)' : undefined }}>{s.okazyvaetsya ?? '—'}</td>
                <td style={{ ...tdSmall, textAlign: 'right' }}>{fmt(s.prinyato_12)}</td>
                <td style={{ ...tdSmall, textAlign: 'right' }}>{fmt(s.prinyato_19)}</td>
                <td style={{ ...tdSmall, textAlign: 'right', color: (s.prirost_prinyato || 0) > 0 ? 'var(--good, #0f6e56)' : undefined }}>
                  {s.prirost_prinyato != null ? (s.prirost_prinyato >= 0 ? '+' : '') + fmt(s.prirost_prinyato) : '—'}
                </td>
                <td style={{ ...tdSmall, textAlign: 'right' }}>{fmt(s.vydano_19)}</td>
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
  office: string; city: string; department: { code: string; name: string }; as_of: string | null
  prinyato_12: number | null; prinyato_19: number | null; prirost: number | null
  vydano_12: number | null; vydano_19: number | null; vydano_prirost: number | null
  conversion_pct: number | null; active_services: number; total_services: number
  services: ServiceRow[]
  rank: { place: number | null; total: number; top10: { office: string; value: number }[] }
}

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', minWidth: 160 }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{sub}</div>}
    </div>
  )
}

// Даты «12.08.2026»/«19.08.2026» — не выдумка: это буквально то, что написано
// в заголовках исходных столбцов формы («…с 01.01.2026 по 12.08.2026» и
// «…по 19.08.2026»). Третьей точки (05.08) у нас нет — история копится по
// мере новых выпусков, придумывать её нельзя.
const DATE_PREV = '12.08.2026'
const DATE_NOW = '19.08.2026'

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
      xAxis: { type: 'category', data: [DATE_PREV, DATE_NOW] },
      yAxis: { type: 'value' },
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0 },
      series: [
        { name: 'Принято накоп.', type: 'bar', data: [d.prinyato_12, d.prinyato_19], itemStyle: { color: cc.c1 } },
        { name: 'Выдано накоп.', type: 'bar', data: [d.vydano_12, d.vydano_19], itemStyle: { color: cc.trend } },
      ],
    }
  }, [d])

  const servicesOption = useMemo(() => {
    if (!d) return null
    const cc = chartColors()
    const sorted = [...d.services].sort((a, b) => (b.prinyato_19 || 0) - (a.prinyato_19 || 0))
    return {
      grid: { left: 220, right: 30, top: 10, bottom: 10 },
      xAxis: { type: 'value' },
      yAxis: { type: 'category', data: sorted.map((s) => s.name.length > 40 ? s.name.slice(0, 37) + '…' : s.name).reverse(),
        axisLabel: { fontSize: 11 } },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      series: [
        { name: 'Принято 19.08', type: 'bar', data: sorted.map((s) => s.prinyato_19 || 0).reverse(), itemStyle: { color: cc.c1 } },
        { name: 'Выдано 19.08', type: 'bar', data: sorted.map((s) => s.vydano_19 || 0).reverse(), itemStyle: { color: cc.trend } },
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
        <Card label={`Принято накоп. на ${DATE_NOW}`} value={fmt(d.prinyato_19)}
          sub={`прирост: ${d.prirost != null && d.prirost >= 0 ? '+' : ''}${fmt(d.prirost)} с ${DATE_PREV}`} />
        <Card label={`Выдано накоп. на ${DATE_NOW}`} value={fmt(d.vydano_19)}
          sub={`прирост: ${d.vydano_prirost != null && d.vydano_prirost >= 0 ? '+' : ''}${fmt(d.vydano_prirost)}`} />
        <Card label="Конверсия выдано/принято" value={d.conversion_pct != null ? `${d.conversion_pct.toFixed(1)}%` : '—'} />
        <Card label="Предоставляемых услуг" value={`${d.active_services}`} sub={`всего в ведомстве: ${d.total_services}`} />
        <Card label="Место среди отделений" value={d.rank.place ? `${d.rank.place} из ${d.rank.total}` : '—'}
          sub={`по принятым на ${DATE_NOW}`} />
      </div>

      {trendOption && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>Динамика ведомства по датам срезов</div>
          <EChart option={trendOption as any} height={240} />
        </div>
      )}

      {servicesOption && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>Все услуги ведомства в этом отделении — принято и выдано на {DATE_NOW}</div>
          <EChart option={servicesOption as any} height={Math.max(160, d.services.length * 34)} />
        </div>
      )}

      {rankOption && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>
            Сравнение с другими отделениями (топ-10 по принятым на {DATE_NOW}; выделено — это отделение)
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
              <th style={{ ...thSmall, textAlign: 'right' }}>Принято {DATE_PREV}</th>
              <th style={{ ...thSmall, textAlign: 'right' }}>Принято {DATE_NOW}</th>
              <th style={{ ...thSmall, textAlign: 'right' }}>Прирост</th>
              <th style={{ ...thSmall, textAlign: 'right' }}>Выдано {DATE_NOW}</th>
              <th style={{ ...thSmall, textAlign: 'right' }}>Доля</th>
            </tr>
          </thead>
          <tbody>
            {d.services.map((s, i) => {
              const inactive = s.okazyvaetsya === 'нет'
              const share = d.prinyato_19 ? ((s.prinyato_19 || 0) / d.prinyato_19 * 100) : null
              return (
                <tr key={i} style={{ cursor: 'pointer', ...(inactive ? { color: 'var(--text-faint)' } : {}) }}
                  onClick={() => onOpenService(i + 1)} title="Открыть дашборд этой услуги">
                  <td style={{ ...tdSmall, color: 'var(--accent)' }}>{s.name}</td>
                  <td style={tdSmall}>{s.prioritet ?? '—'}</td>
                  <td style={{ ...tdSmall, color: inactive ? 'var(--danger)' : undefined }}>{s.okazyvaetsya ?? '—'}</td>
                  <td style={{ ...tdSmall, textAlign: 'right' }}>{fmt(s.prinyato_12)}</td>
                  <td style={{ ...tdSmall, textAlign: 'right' }}>{fmt(s.prinyato_19)}</td>
                  <td style={{ ...tdSmall, textAlign: 'right', color: (s.prirost_prinyato || 0) > 0 ? 'var(--good, #0f6e56)' : undefined }}>
                    {s.prirost_prinyato != null ? (s.prirost_prinyato >= 0 ? '+' : '') + fmt(s.prirost_prinyato) : '—'}
                  </td>
                  <td style={{ ...tdSmall, textAlign: 'right' }}>{fmt(s.vydano_19)}</td>
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
  office: string; city: string; department: { code: string; name: string }; as_of: string | null
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
      xAxis: { type: 'category', data: [DATE_PREV, DATE_NOW] },
      yAxis: { type: 'value' },
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0 },
      series: [
        { name: 'Принято накоп.', type: 'bar', data: [d.service.prinyato_12, d.service.prinyato_19], itemStyle: { color: cc.c1 } },
        { name: 'Выдано накоп.', type: 'bar', data: [d.service.vydano_12, d.service.vydano_19], itemStyle: { color: cc.trend } },
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
        <Card label={`Принято накоп. на ${DATE_NOW}`} value={fmt(s.prinyato_19)}
          sub={`прирост: ${s.prirost_prinyato != null && s.prirost_prinyato >= 0 ? '+' : ''}${fmt(s.prirost_prinyato)} с ${DATE_PREV}`} />
        <Card label={`Выдано накоп. на ${DATE_NOW}`} value={fmt(s.vydano_19)}
          sub={`прирост: ${s.prirost_vydano != null && s.prirost_vydano >= 0 ? '+' : ''}${fmt(s.prirost_vydano)}`} />
        <Card label="Конверсия выдано/принято" value={d.conversion_pct != null ? `${d.conversion_pct.toFixed(1)}%` : '—'} />
        <Card label="Приоритетная услуга" value={s.prioritet ?? '—'} />
        <Card label="Место среди отделений" value={d.rank.place ? `${d.rank.place} из ${d.rank.total}` : '—'}
          sub={`по принятым на ${DATE_NOW}`} />
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
            Сравнение с другими отделениями (топ-10 по принятым на {DATE_NOW}; выделено — это отделение)
          </div>
          <EChart option={rankOption as any} height={260} />
        </div>
      )}
    </div>
  )
}
