import { useEffect, useRef, useState, type FormEvent } from 'react'
import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'
import GridLayout, { WidthProvider, type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import {
  autoBuildDashboard, createDashboard, createPage, createWidget, deletePage, deleteWidget, getDashboard,
  getDataSources, listDashboardVersions, listDashboards, listObjects, listPageWidgets,
  publishDashboard, restoreDashboardVersion, unpublishDashboard, updateWidget,
  type Dashboard, type DashPage, type DataSources, type Obj, type Widget,
} from '../api'
import WidgetView from './WidgetView'

const GL = WidthProvider(GridLayout)

// размеры по умолчанию для новых виджетов (сетка cols=12, rowHeight=40)
const DEFAULT_SIZE: Record<string, { w: number; h: number }> = {
  kpi: { w: 3, h: 3 }, plan_fact: { w: 4, h: 5 }, table: { w: 6, h: 6 },
  bar: { w: 5, h: 6 }, line: { w: 5, h: 6 }, pie: { w: 4, h: 6 },
  dynamics: { w: 6, h: 6 }, compare: { w: 6, h: 7 },
}

const WT = [
  { v: 'kpi', t: 'KPI (число)' }, { v: 'bar', t: 'Столбцы' }, { v: 'line', t: 'Линия' },
  { v: 'pie', t: 'Круговая' }, { v: 'table', t: 'Таблица' }, { v: 'plan_fact', t: 'План-факт' },
  { v: 'dynamics', t: 'Динамика (периоды)' }, { v: 'compare', t: 'Сравнение (неск. полей)' },
]

export default function DashboardsPage({ canManage, initialDashboardId }: { canManage: boolean; initialDashboardId?: string | null }) {
  const [dashboards, setDashboards] = useState<Dashboard[]>([])
  const [sel, setSel] = useState<{ dashboard: Dashboard; pages: DashPage[] } | null>(null)
  const [page, setPage] = useState<DashPage | null>(null)
  const [widgets, setWidgets] = useState<Widget[]>([])
  const [sources, setSources] = useState<DataSources | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const [newDash, setNewDash] = useState('')
  const [newPage, setNewPage] = useState('')
  const [busy, setBusy] = useState(false)
  const [pFrom, setPFrom] = useState('')
  const [pTo, setPTo] = useState('')
  const [crossRow, setCrossRow] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const pageRef = useRef<HTMLDivElement>(null)
  const [objects, setObjects] = useState<Obj[]>([])
  const [autoObj, setAutoObj] = useState('')
  const [editMode, setEditMode] = useState(false)
  const [versions, setVersions] = useState<{ version_no: number; status_code: string; created_at: string }[] | null>(null)

  const fail = (e: unknown) => setError((e as Error).message)
  const refresh = () => listDashboards().then(setDashboards).catch(fail)

  useEffect(() => {
    refresh(); getDataSources().then(setSources).catch(() => setSources({ datasets: [], metrics: [] }))
    listObjects().then(setObjects).catch(() => {})
    if (initialDashboardId) openDashboard(initialDashboardId)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function openDashboard(id: string) {
    setError(null); setPage(null); setWidgets([])
    try {
      const d = await getDashboard(id)
      setSel(d)
      if (d.pages.length) openPage(d.pages[0])
    } catch (e) { fail(e) }
  }
  async function openPage(p: DashPage) {
    setError(null); setPage(p)
    try { setWidgets((await listPageWidgets(p.id)).widgets) } catch (e) { fail(e) }
  }
  async function reloadPage() {
    if (page) { try { setWidgets((await listPageWidgets(page.id)).widgets) } catch (e) { fail(e) } }
  }

  async function addDashboard(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null)
    try { const d = await createDashboard(newDash.trim()); setNewDash(''); await refresh(); openDashboard(d.id) }
    catch (e) { fail(e) } finally { setBusy(false) }
  }
  async function autoBuild() {
    if (!autoObj) return
    setBusy(true); setError(null)
    try { const r = await autoBuildDashboard(autoObj); setAutoObj(''); await refresh(); openDashboard(r.dashboard_id) }
    catch (e) { fail(e) } finally { setBusy(false) }
  }
  async function addPage(e: FormEvent) {
    e.preventDefault(); if (!sel) return; setBusy(true); setError(null)
    try {
      const p = await createPage(sel.dashboard.id, newPage.trim())
      setNewPage(''); const d = await getDashboard(sel.dashboard.id); setSel(d); openPage(p)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }
  async function delPage(p: DashPage) {
    if (!sel || !confirm(`Удалить страницу «${p.name}» со всеми виджетами?`)) return
    try { await deletePage(p.id); const d = await getDashboard(sel.dashboard.id); setSel(d); setPage(null); setWidgets([]) }
    catch (e) { fail(e) }
  }
  async function addWidget(body: { name: string; widget_type: string; config: Record<string, unknown>; width?: number; height?: number }) {
    if (!page) return
    try { await createWidget(page.id, { ...body, position_x: 0, position_y: 999 }); await reloadPage(); setReloadKey((k) => k + 1) } catch (e) { fail(e) }
  }
  async function delWidget(w: Widget) {
    try { await deleteWidget(w.id); await reloadPage() } catch (e) { fail(e) }
  }
  async function doPublish() {
    if (!sel) return
    try { await publishDashboard(sel.dashboard.id); setSel(await getDashboard(sel.dashboard.id)) } catch (e) { fail(e) }
  }
  async function doUnpublish() {
    if (!sel) return
    try { await unpublishDashboard(sel.dashboard.id); setSel(await getDashboard(sel.dashboard.id)) } catch (e) { fail(e) }
  }
  async function loadVersions() {
    if (!sel) return
    try { setVersions(await listDashboardVersions(sel.dashboard.id)) } catch (e) { fail(e) }
  }
  async function doRestore(v: number) {
    if (!sel || !confirm(`Откатить к версии ${v}? Текущие страницы и виджеты будут заменены снимком.`)) return
    try {
      await restoreDashboardVersion(sel.dashboard.id, v)
      const d = await getDashboard(sel.dashboard.id); setSel(d); setVersions(null)
      if (d.pages.length) openPage(d.pages[0]); else { setPage(null); setWidgets([]) }
    } catch (e) { fail(e) }
  }
  async function exportPdf() {
    const el = pageRef.current
    if (!el || !sel || !page) return
    setExporting(true)
    try {
      const canvas = await html2canvas(el, { scale: 2, backgroundColor: '#ffffff', useCORS: true })
      const pdf = new jsPDF('p', 'mm', 'a4')
      const pw = pdf.internal.pageSize.getWidth(), ph = pdf.internal.pageSize.getHeight()
      const pageCanvasH = Math.floor((canvas.width * ph) / pw)
      let rendered = 0, first = true
      while (rendered < canvas.height) {
        const h = Math.min(pageCanvasH, canvas.height - rendered)
        const slice = document.createElement('canvas')
        slice.width = canvas.width; slice.height = h
        slice.getContext('2d')!.drawImage(canvas, 0, rendered, canvas.width, h, 0, 0, canvas.width, h)
        if (!first) pdf.addPage()
        pdf.addImage(slice.toDataURL('image/png'), 'PNG', 0, 0, pw, (h * pw) / canvas.width)
        rendered += h; first = false
      }
      pdf.save(`${sel.dashboard.name} — ${page.name}.pdf`)
    } catch (e) { fail(e) } finally { setExporting(false) }
  }
  async function persistItem(l: Layout) {
    try {
      await updateWidget(l.i, { position_x: l.x, position_y: l.y, width: l.w, height: l.h })
      setWidgets((ws) => ws.map((w) => (w.id === l.i ? { ...w, position_x: l.x, position_y: l.y, width: l.w, height: l.h } : w)))
    } catch (e) { fail(e) }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, marginBottom: 16 }}>
        <button style={crumb} onClick={() => { setSel(null); setPage(null) }}>Дашборды</button>
        {sel && <><span style={{ color: '#9aa4b2' }}>/</span><span>{sel.dashboard.name}</span></>}
      </div>

      {error && <div style={errBox}>{error}</div>}

      {!sel && (
        <div>
          {canManage && (
            <form onSubmit={addDashboard} style={rowForm}>
              <input style={{ ...input, width: 260 }} placeholder="Название дашборда" value={newDash} onChange={(e) => setNewDash(e.target.value)} />
              <button style={btn} disabled={busy || !newDash.trim()}>＋ Дашборд</button>
            </form>
          )}
          {canManage && objects.length > 0 && (
            <div style={{ ...rowForm, alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: '#6b7280' }}>или собрать автоматически из объекта:</span>
              <select style={{ ...input, height: 36 }} value={autoObj} onChange={(e) => setAutoObj(e.target.value)}>
                <option value="">выберите объект…</option>
                {objects.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
              <button style={btnAuto} disabled={busy || !autoObj} onClick={autoBuild}>✨ Собрать</button>
            </div>
          )}
          {dashboards.length === 0 ? <div style={muted}>Пока нет дашбордов.</div> : (
            <div style={{ border: '1px solid #e5e7eb', borderRadius: 12, overflow: 'hidden' }}>
              {dashboards.map((d, i) => (
                <div key={d.id} onClick={() => openDashboard(d.id)} style={{ ...rowItem, borderTop: i ? '1px solid #f0f0f0' : 'none' }}>
                  <span style={{ fontSize: 14 }}>{d.name}</span>
                  <span style={{ fontSize: 12, color: '#6b7280' }}>страниц: {d.pages ?? 0} · {d.publication_status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {sel && (
        <div>
          {/* Публикация и версии */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
            <PubBadge status={sel.dashboard.publication_status} />
            {canManage && sel.dashboard.publication_status !== 'published' && <button style={btn} onClick={doPublish}>Опубликовать</button>}
            {canManage && sel.dashboard.publication_status === 'published' && <button style={btnGhost} onClick={doUnpublish}>Снять с публикации</button>}
            {canManage && <button style={btnGhost} onClick={loadVersions}>История версий</button>}
            {page && <button style={btnGhost} disabled={exporting} onClick={exportPdf}>{exporting ? 'Экспорт…' : '⤓ Экспорт в PDF'}</button>}
          </div>
          {versions && (
            <div style={{ border: '1px solid #e5e7eb', borderRadius: 10, padding: 12, marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
                <b style={{ fontSize: 13 }}>История версий</b>
                <button style={{ ...linkDanger, marginLeft: 'auto', color: '#6b7280' }} onClick={() => setVersions(null)}>закрыть</button>
              </div>
              {versions.length === 0 ? <div style={muted}>Пока нет опубликованных версий.</div> : versions.map((v) => (
                <div key={v.version_no} style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 13, padding: '4px 0' }}>
                  <span>v{v.version_no}</span><span style={{ color: '#6b7280' }}>{v.status_code}</span>
                  <span style={{ color: '#9aa4b2' }}>{new Date(v.created_at).toLocaleString('ru-RU')}</span>
                  {canManage && <button style={{ ...linkDanger, color: '#2f5496', marginLeft: 'auto' }} onClick={() => doRestore(v.version_no)}>откатить</button>}
                </div>
              ))}
            </div>
          )}
          {/* Вкладки страниц */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12, alignItems: 'center' }}>
            {sel.pages.map((p) => (
              <button key={p.id} onClick={() => openPage(p)} style={{ ...tab, ...(page?.id === p.id ? tabActive : {}) }}>
                {p.name}
              </button>
            ))}
            {canManage && (
              <form onSubmit={addPage} style={{ display: 'flex', gap: 6 }}>
                <input style={{ ...input, height: 32, width: 150 }} placeholder="Новая страница" value={newPage} onChange={(e) => setNewPage(e.target.value)} />
                <button style={{ ...btn, height: 32 }} disabled={busy || !newPage.trim()}>＋</button>
              </form>
            )}
          </div>

          {!page ? (
            <div style={muted}>{sel.pages.length ? 'Выберите страницу.' : 'Создайте первую страницу дашборда.'}</div>
          ) : (
            <div ref={pageRef} style={{ background: '#fff' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
                <h3 style={{ fontSize: 15, margin: 0 }}>Страница «{page.name}»</h3>
                {canManage && <button style={{ ...tab, height: 30, ...(editMode ? tabActive : {}) }} onClick={() => setEditMode((v) => !v)}>{editMode ? '✓ Готово' : '✎ Раскладка'}</button>}
                {canManage && <button style={linkDanger} onClick={() => delPage(page)}>удалить страницу</button>}
                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#6b7280' }}>
                  <span>Период:</span>
                  <input type="date" style={{ ...input, height: 30, width: 140 }} value={pFrom} onChange={(e) => setPFrom(e.target.value)} />
                  <span>—</span>
                  <input type="date" style={{ ...input, height: 30, width: 140 }} value={pTo} onChange={(e) => setPTo(e.target.value)} />
                  {(pFrom || pTo) && <button style={linkDanger} onClick={() => { setPFrom(''); setPTo('') }}>сброс</button>}
                </div>
              </div>

              {crossRow && (
                <div style={{ marginBottom: 10 }}>
                  <span style={{ fontSize: 13, background: '#eef', color: '#2f5496', padding: '4px 10px', borderRadius: 12 }}>
                    Фильтр по строке: <b>{crossRow}</b>
                    <button style={{ border: 'none', background: 'none', color: '#2f5496', cursor: 'pointer', marginLeft: 6 }} onClick={() => setCrossRow(null)}>✕</button>
                  </span>
                  <span style={{ fontSize: 12, color: '#9aa4b2', marginLeft: 8 }}>клик по столбцу/сектору фильтрует остальные виджеты</span>
                </div>
              )}

              {/* Сетка виджетов (drag-drop в режиме раскладки) */}
              {widgets.length === 0 ? <div style={muted}>На странице пока нет виджетов.</div> : (
                <GL className="layout" cols={12} rowHeight={40} margin={[12, 12]}
                  isDraggable={canManage && editMode} isResizable={canManage && editMode}
                  draggableHandle=".wdrag" compactType="vertical"
                  onDragStop={(_l, _o, n) => persistItem(n)} onResizeStop={(_l, _o, n) => persistItem(n)}
                  layout={widgets.map((w) => ({ i: w.id, x: w.position_x || 0, y: w.position_y || 0, w: w.width || 4, h: w.height || 4 }))}>
                  {widgets.map((w) => (
                    <div key={w.id} style={{ ...widgetCard, height: '100%', overflow: 'hidden', outline: editMode ? '1px dashed #9aa4b2' : 'none' }}>
                      <div className={editMode ? 'wdrag' : ''} style={{ display: 'flex', alignItems: 'center', marginBottom: 8, cursor: editMode ? 'move' : 'default' }}>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>{w.name}</div>
                        <span style={wtBadge}>{WT.find((x) => x.v === w.widget_type)?.t || w.widget_type}</span>
                        {canManage && <button style={rmBtn} onClick={() => delWidget(w)} title="Удалить">✕</button>}
                      </div>
                      <div style={{ overflow: 'auto', maxHeight: 'calc(100% - 30px)' }}>
                        <WidgetView widgetId={w.id} reloadKey={reloadKey} from={pFrom || undefined} to={pTo || undefined} row={crossRow || undefined} onPick={setCrossRow} />
                      </div>
                    </div>
                  ))}
                </GL>
              )}

              {canManage && sources && (
                <div style={{ marginTop: 20 }}>
                  <h3 style={{ fontSize: 14, margin: '0 0 8px' }}>Добавить виджет</h3>
                  <WidgetForm sources={sources} onCreate={addWidget} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function WidgetForm({ sources, onCreate }: { sources: DataSources; onCreate: (b: { name: string; widget_type: string; config: Record<string, unknown>; width?: number; height?: number }) => void }) {
  const [name, setName] = useState('')
  const [type, setType] = useState('kpi')
  const [source, setSource] = useState<'metric' | 'dataset'>('metric')
  const [metricCode, setMetricCode] = useState(sources.metrics[0]?.code || '')
  const [factMetric, setFactMetric] = useState(sources.metrics[1]?.code || sources.metrics[0]?.code || '')
  const [dataset, setDataset] = useState(sources.datasets[0]?.code || '')
  const numFields = (dc: string) => (sources.datasets.find((d) => d.code === dc)?.fields.filter((f) => f.data_type === 'number') || [])
  const [valueField, setValueField] = useState(numFields(sources.datasets[0]?.code || '')[0]?.code || '')
  const [planField, setPlanField] = useState(numFields(sources.datasets[0]?.code || '')[0]?.code || '')
  const [factField, setFactField] = useState(numFields(sources.datasets[0]?.code || '')[0]?.code || '')
  const [multiFields, setMultiFields] = useState<string[]>([])
  const [viz, setViz] = useState('bar')

  const usesSource = type === 'kpi' || type === 'plan_fact'
  const usesDataset = (usesSource && source === 'dataset') || type === 'table' || ['bar', 'line', 'pie', 'dynamics', 'compare'].includes(type)
  const usesValueField = ['bar', 'line', 'pie', 'dynamics'].includes(type) || (type === 'kpi' && source === 'dataset')
  const usesMulti = type === 'compare'
  const toggleField = (c: string) => setMultiFields((s) => s.includes(c) ? s.filter((x) => x !== c) : [...s, c])

  function submit(e: FormEvent) {
    e.preventDefault()
    let config: Record<string, unknown> = {}
    if (type === 'kpi') config = source === 'metric' ? { metric_code: metricCode } : { dataset_code: dataset, value_field: valueField }
    else if (type === 'plan_fact') config = source === 'metric' ? { plan_metric: metricCode, fact_metric: factMetric } : { dataset_code: dataset, plan_field: planField, fact_field: factField }
    else if (type === 'table') config = { dataset_code: dataset }
    else if (type === 'compare') { if (multiFields.length === 0) return; config = { dataset_code: dataset, value_fields: multiFields, viz } }
    else config = { dataset_code: dataset, value_field: valueField }
    const sz = DEFAULT_SIZE[type] || { w: 4, h: 4 }
    onCreate({ name: name.trim() || WT.find((x) => x.v === type)?.t || type, widget_type: type, config, width: sz.w, height: sz.h })
    setName('')
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end', border: '1px solid #e5e7eb', borderRadius: 10, padding: 12 }}>
      <F t="Название"><input style={sel} placeholder="Заголовок виджета" value={name} onChange={(e) => setName(e.target.value)} /></F>
      <F t="Тип"><select style={sel} value={type} onChange={(e) => setType(e.target.value)}>{WT.map((x) => <option key={x.v} value={x.v}>{x.t}</option>)}</select></F>
      {usesSource && (
        <F t="Источник"><select style={sel} value={source} onChange={(e) => setSource(e.target.value as any)}>
          <option value="metric">Метрика</option><option value="dataset">Датасет</option>
        </select></F>
      )}
      {usesSource && source === 'metric' && (
        <F t={type === 'plan_fact' ? 'Метрика (план)' : 'Метрика'}><select style={sel} value={metricCode} onChange={(e) => setMetricCode(e.target.value)}>{sources.metrics.map((m) => <option key={m.code} value={m.code}>{m.name}</option>)}</select></F>
      )}
      {type === 'plan_fact' && source === 'metric' && (
        <F t="Метрика (факт)"><select style={sel} value={factMetric} onChange={(e) => setFactMetric(e.target.value)}>{sources.metrics.map((m) => <option key={m.code} value={m.code}>{m.name}</option>)}</select></F>
      )}
      {usesDataset && (
        <F t="Датасет"><select style={sel} value={dataset} onChange={(e) => { setDataset(e.target.value); const nf = numFields(e.target.value); setValueField(nf[0]?.code || ''); setPlanField(nf[0]?.code || ''); setFactField(nf[0]?.code || ''); setMultiFields([]) }}>{sources.datasets.map((d) => <option key={d.code} value={d.code}>{d.name} ({d.code})</option>)}</select></F>
      )}
      {usesValueField && (
        <F t="Поле (значение)"><select style={sel} value={valueField} onChange={(e) => setValueField(e.target.value)}>{numFields(dataset).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></F>
      )}
      {usesMulti && (
        <>
          <F t="Поля (несколько)">
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', height: 34, alignItems: 'center' }}>
              {numFields(dataset).map((f) => (
                <label key={f.code} style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: 13 }}>
                  <input type="checkbox" checked={multiFields.includes(f.code)} onChange={() => toggleField(f.code)} />{f.name}
                </label>
              ))}
            </div>
          </F>
          <F t="Вид"><select style={sel} value={viz} onChange={(e) => setViz(e.target.value)}><option value="bar">Столбцы</option><option value="line">Линии</option></select></F>
        </>
      )}
      {type === 'plan_fact' && source === 'dataset' && (
        <>
          <F t="Поле (план)"><select style={sel} value={planField} onChange={(e) => setPlanField(e.target.value)}>{numFields(dataset).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></F>
          <F t="Поле (факт)"><select style={sel} value={factField} onChange={(e) => setFactField(e.target.value)}>{numFields(dataset).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></F>
        </>
      )}
      <button style={btn}>Добавить</button>
    </form>
  )
}

function F({ t, children }: { t: string; children: React.ReactNode }) {
  return <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 11, color: '#6b7280' }}>{t}{children}</label>
}

function PubBadge({ status }: { status: string }) {
  const m: Record<string, { t: string; bg: string; c: string }> = {
    draft: { t: 'черновик', bg: '#f1f2f4', c: '#6b7280' },
    review: { t: 'на проверке', bg: '#fef6e0', c: '#8a6d1a' },
    published: { t: 'опубликован', bg: '#e1f5ee', c: '#0f6e56' },
    archived: { t: 'в архиве', bg: '#f1f2f4', c: '#9aa4b2' },
  }
  const s = m[status] || m.draft
  return <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 12, background: s.bg, color: s.c }}>{s.t}</span>
}

const crumb: React.CSSProperties = { border: 'none', background: 'none', color: '#2f5496', cursor: 'pointer', fontSize: 14, padding: 0 }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14 }
const sel: React.CSSProperties = { height: 34, padding: '0 8px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 13, background: '#fff' }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: '#2f5496', color: '#fff', fontSize: 14, cursor: 'pointer' }
const btnAuto: React.CSSProperties = { height: 36, padding: '0 14px', border: '1px solid #2f5496', borderRadius: 8, background: '#eef', color: '#2f5496', fontSize: 14, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { height: 36, padding: '0 14px', border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', color: '#374151', fontSize: 14, cursor: 'pointer' }
const rowForm: React.CSSProperties = { display: 'flex', gap: 8, marginBottom: 16 }
const rowItem: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', cursor: 'pointer' }
const tab: React.CSSProperties = { height: 34, padding: '0 14px', border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', cursor: 'pointer', fontSize: 13 }
const tabActive: React.CSSProperties = { background: '#eef', border: '1px solid #2f5496', color: '#2f5496' }
const widgetCard: React.CSSProperties = { border: '1px solid #e5e7eb', borderRadius: 12, padding: 14, background: '#fff' }
const wtBadge: React.CSSProperties = { marginLeft: 8, fontSize: 11, padding: '1px 7px', borderRadius: 8, background: '#eef', color: '#2f5496' }
const rmBtn: React.CSSProperties = { marginLeft: 'auto', width: 24, height: 24, border: '1px solid #e5e7eb', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#a32d2d' }
const muted: React.CSSProperties = { color: '#6b7280', fontSize: 14, padding: '8px 0' }
const errBox: React.CSSProperties = { background: '#fcebeb', color: '#a32d2d', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const linkDanger: React.CSSProperties = { border: 'none', background: 'none', color: '#a32d2d', cursor: 'pointer', fontSize: 12, padding: 0 }
