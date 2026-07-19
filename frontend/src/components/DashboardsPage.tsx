import { useEffect, useRef, useState, type FormEvent } from 'react'
import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'
import GridLayout, { WidthProvider, type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import {
  addDashboardGrant, autoBuildDashboard, createDashboard, createPage, createPreset, createWidget, deletePage, deletePreset, deleteWidget, getDashboard,
  exportPageXlsx, getDataSources, instantiateTemplate, listDashboardGrants, listDashboardVersions, listDashboards, listObjects, listPageWidgets, listPresets, previewWidget,
  listTemplates, publishDashboard, removeDashboardGrant, restoreDashboardVersion, saveAsTemplate, submitDashboardReview, cancelDashboardReview, unpublishDashboard, updateWidget, widgetSuggestions,
  type Dashboard, type DashGrant, type DashPage, type DashPreset, type DashTemplate, type DataSources, type GrantTargets, type MetricSource, type Obj, type Widget, type WidgetSpec,
} from '../api'
import WidgetView, { WidgetPreviewBody } from './WidgetView'
import KioskView from './KioskView'
import FormulaBuilder from './FormulaBuilder'

const GL = WidthProvider(GridLayout)

// размеры по умолчанию для новых виджетов (сетка cols=12, rowHeight=40)
const DEFAULT_SIZE: Record<string, { w: number; h: number }> = {
  kpi: { w: 3, h: 3 }, plan_fact: { w: 4, h: 5 }, table: { w: 6, h: 6 },
  bar: { w: 5, h: 6 }, line: { w: 5, h: 6 }, pie: { w: 4, h: 6 },
  dynamics: { w: 6, h: 6 }, compare: { w: 6, h: 7 }, text: { w: 6, h: 2 }, image: { w: 3, h: 3 },
}

const WT = [
  { v: 'kpi', t: 'KPI (число)' }, { v: 'bar', t: 'Столбцы' }, { v: 'line', t: 'Линия' },
  { v: 'pie', t: 'Круговая' }, { v: 'table', t: 'Таблица' }, { v: 'plan_fact', t: 'План-факт' },
  { v: 'dynamics', t: 'Динамика (периоды)' }, { v: 'compare', t: 'Сравнение (неск. полей)' },
  { v: 'text', t: 'Текст/заголовок' }, { v: 'image', t: 'Картинка/лого' },
]

export default function DashboardsPage({ canManage, isAdmin, initialDashboardId }: { canManage: boolean; isAdmin?: boolean; initialDashboardId?: string | null }) {
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
  const [templates, setTemplates] = useState<DashTemplate[]>([])
  const [tpl, setTpl] = useState('')
  const [editMode, setEditMode] = useState(false)
  const [versions, setVersions] = useState<{ version_no: number; status_code: string; created_at: string }[] | null>(null)
  const [alertWidget, setAlertWidget] = useState<Widget | null>(null)
  const [editWidget, setEditWidget] = useState<Widget | null>(null)
  const [accessOpen, setAccessOpen] = useState(false)
  const [presets, setPresets] = useState<DashPreset[]>([])
  const [kiosk, setKiosk] = useState(false)

  const fail = (e: unknown) => setError((e as Error).message)
  const refresh = () => listDashboards().then(setDashboards).catch(fail)

  useEffect(() => {
    refresh(); getDataSources().then(setSources).catch(() => setSources({ datasets: [], metrics: [] }))
    listObjects().then(setObjects).catch(() => {})
    listTemplates().then(setTemplates).catch(() => {})
    if (initialDashboardId) openDashboard(initialDashboardId)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function openDashboard(id: string) {
    setError(null); setPage(null); setWidgets([]); setPFrom(''); setPTo(''); setCrossRow(null)
    try {
      const d = await getDashboard(id)
      setSel(d)
      listPresets(id).then(setPresets).catch(() => setPresets([]))
      if (d.pages.length) openPage(d.pages[0])
    } catch (e) { fail(e) }
  }
  const reloadPresets = () => { if (sel) listPresets(sel.dashboard.id).then(setPresets).catch(() => {}) }
  function applyPreset(p: DashPreset) {
    setPFrom(p.filters.from || ''); setPTo(p.filters.to || ''); setCrossRow(p.filters.row || null)
  }
  async function savePreset() {
    if (!sel) return
    const name = prompt('Название пресета фильтров:')?.trim()
    if (!name) return
    try {
      await createPreset(sel.dashboard.id, name, { from: pFrom || undefined, to: pTo || undefined, row: crossRow || undefined })
      reloadPresets()
    } catch (e) { fail(e) }
  }
  async function removePreset(p: DashPreset) {
    if (!sel || !confirm(`Удалить пресет «${p.name}»?`)) return
    try { await deletePreset(sel.dashboard.id, p.id); reloadPresets() } catch (e) { fail(e) }
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
  async function saveWidgetEdit(body: { name: string; widget_type: string; config: Record<string, unknown> }) {
    if (!editWidget) return
    try {
      await updateWidget(editWidget.id, { name: body.name, widget_type: body.widget_type, config: body.config })
      setEditWidget(null); await reloadPage(); setReloadKey((k) => k + 1)
    } catch (e) { fail(e) }
  }
  async function addWidgetsBatch(specs: WidgetSpec[]) {
    if (!page) return
    try {
      for (const s of specs) await createWidget(page.id, { ...s, position_x: 0, position_y: 999 })
      await reloadPage(); setReloadKey((k) => k + 1)
    } catch (e) { fail(e) }
  }
  async function delWidget(w: Widget) {
    try { await deleteWidget(w.id); await reloadPage() } catch (e) { fail(e) }
  }
  async function doPublish() {
    if (!sel) return
    try { await publishDashboard(sel.dashboard.id); setSel(await getDashboard(sel.dashboard.id)) } catch (e) { fail(e) }
  }
  async function doSubmitReview() {
    if (!sel) return
    try { await submitDashboardReview(sel.dashboard.id); setSel(await getDashboard(sel.dashboard.id)) } catch (e) { fail(e) }
  }
  async function doCancelReview() {
    if (!sel) return
    try { await cancelDashboardReview(sel.dashboard.id); setSel(await getDashboard(sel.dashboard.id)) } catch (e) { fail(e) }
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
  async function saveTemplate() {
    if (!sel) return
    const name = prompt('Название шаблона:', sel.dashboard.name)
    if (!name) return
    try { await saveAsTemplate(sel.dashboard.id, name.trim()); setTemplates(await listTemplates()) } catch (e) { fail(e) }
  }
  async function createFromTemplate() {
    if (!tpl) return
    const t = templates.find((x) => x.id === tpl)
    const name = prompt('Название нового дашборда:', t ? `${t.name} (копия)` : 'Новый дашборд')
    if (!name) return
    setBusy(true); setError(null)
    try { const r = await instantiateTemplate(tpl, name.trim()); setTpl(''); await refresh(); openDashboard(r.dashboard_id) }
    catch (e) { fail(e) } finally { setBusy(false) }
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
  async function exportPng() {
    const el = pageRef.current
    if (!el || !sel || !page) return
    setExporting(true)
    try {
      const canvas = await html2canvas(el, { scale: 2, backgroundColor: '#ffffff', useCORS: true })
      const a = document.createElement('a')
      a.href = canvas.toDataURL('image/png'); a.download = `${sel.dashboard.name} — ${page.name}.png`; a.click()
    } catch (e) { fail(e) } finally { setExporting(false) }
  }
  async function exportExcel() {
    if (!sel || !page) return
    setExporting(true)
    try {
      const blob = await exportPageXlsx(page.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `${sel.dashboard.name} — ${page.name}.xlsx`; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { fail(e) } finally { setExporting(false) }
  }
  async function persistItem(l: Layout) {
    try {
      await updateWidget(l.i, { position_x: l.x, position_y: l.y, width: l.w, height: l.h })
      setWidgets((ws) => ws.map((w) => (w.id === l.i ? { ...w, position_x: l.x, position_y: l.y, width: l.w, height: l.h } : w)))
    } catch (e) { fail(e) }
  }

  // Категории для фильтра «Строка» — строки датасетов, используемых виджетами страницы
  const catOptions: string[] = (() => {
    if (!sources) return []
    const codes = new Set<string>()
    widgets.forEach((w) => { const dc = (w.config as Record<string, unknown>)?.dataset_code as string | undefined; if (dc) codes.add(dc) })
    const labels = new Set<string>()
    sources.datasets.forEach((d) => { if (codes.has(d.code)) d.rows.forEach((r) => labels.add(r)) })
    return Array.from(labels)
  })()

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
          {canManage && templates.length > 0 && (
            <div style={{ ...rowForm, alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: '#6b7280' }}>или создать из шаблона:</span>
              <select style={{ ...input, height: 36 }} value={tpl} onChange={(e) => setTpl(e.target.value)}>
                <option value="">выберите шаблон…</option>
                {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              <button style={btnAuto} disabled={busy || !tpl} onClick={createFromTemplate}>📋 Создать</button>
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
            {canManage && sel.dashboard.publication_status === 'draft' && <button style={btn} onClick={doSubmitReview}>Отправить на проверку</button>}
            {canManage && isAdmin && sel.dashboard.publication_status === 'draft' && <button style={btnGhost} onClick={doPublish} title="Публикация без модерации (админ)">Опубликовать без проверки</button>}
            {canManage && sel.dashboard.publication_status === 'review' && <button style={btnGhost} onClick={doCancelReview}>Отозвать заявку</button>}
            {canManage && sel.dashboard.publication_status === 'published' && <button style={btnGhost} onClick={doUnpublish}>Снять с публикации</button>}
            {canManage && <button style={btnGhost} onClick={loadVersions}>История версий</button>}
            {sel.pages.length > 0 && <button style={btnGhost} onClick={() => setKiosk(true)} title="Полноэкранный показ с автопрокруткой (для ТВ)">📺 Витрина</button>}
            {page && <button style={btnGhost} disabled={exporting} onClick={exportPdf}>{exporting ? 'Экспорт…' : '⤓ PDF'}</button>}
            {page && <button style={btnGhost} disabled={exporting} onClick={exportExcel} title="Данные страницы в Excel">⤓ Excel</button>}
            {page && <button style={btnGhost} disabled={exporting} onClick={exportPng} title="Снимок страницы в PNG">⤓ PNG</button>}
            {canManage && <button style={btnGhost} onClick={saveTemplate}>Сохранить как шаблон</button>}
            {canManage && <button style={btnGhost} onClick={() => setAccessOpen(true)} title="Кто видит этот дашборд">🔒 Доступ</button>}
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
                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#6b7280', flexWrap: 'wrap' }}>
                  <span>Период:</span>
                  <input type="date" style={{ ...input, height: 30, width: 140 }} value={pFrom} onChange={(e) => setPFrom(e.target.value)} />
                  <span>—</span>
                  <input type="date" style={{ ...input, height: 30, width: 140 }} value={pTo} onChange={(e) => setPTo(e.target.value)} />
                  <span style={{ marginLeft: 4 }}>Строка:</span>
                  {catOptions.length > 0 ? (
                    <select style={{ ...input, height: 30, width: 160 }} value={crossRow || ''} onChange={(e) => setCrossRow(e.target.value || null)}>
                      <option value="">все</option>
                      {catOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  ) : (
                    <input style={{ ...input, height: 30, width: 150 }} placeholder="категория" value={crossRow || ''} onChange={(e) => setCrossRow(e.target.value || null)} />
                  )}
                  {(pFrom || pTo || crossRow) && <button style={linkDanger} onClick={() => { setPFrom(''); setPTo(''); setCrossRow(null) }}>сброс</button>}
                </div>
              </div>

              {/* Пресеты фильтров (сохранённые наборы, FR-13) */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 12, color: '#6b7280' }}>Пресеты:</span>
                {presets.length === 0 && <span style={{ fontSize: 12, color: '#9aa4b2' }}>нет сохранённых наборов</span>}
                {presets.map((p) => (
                  <span key={p.id} style={presetChip}>
                    <button style={{ border: 'none', background: 'none', color: '#2f5496', cursor: 'pointer', padding: 0, fontSize: 13 }} onClick={() => applyPreset(p)} title="Применить набор фильтров">{p.name}</button>
                    {canManage && <button style={{ border: 'none', background: 'none', color: '#a32d2d', cursor: 'pointer', padding: 0 }} onClick={() => removePreset(p)} title="Удалить пресет">✕</button>}
                  </span>
                ))}
                {canManage && <button style={{ ...tab, height: 28 }} onClick={savePreset}>💾 Сохранить текущие</button>}
                <span style={{ fontSize: 12, color: '#9aa4b2', marginLeft: 4 }}>клик по столбцу/сектору тоже задаёт «Строку»</span>
              </div>

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
                        {canManage && sources && <button style={editBtn} onClick={() => setEditWidget(w)} title="Изменить данные/тип виджета">✎</button>}
                        {canManage && ['kpi', 'plan_fact', 'dynamics'].includes(w.widget_type) && (
                          <button style={alertBtn} onClick={() => setAlertWidget(w)}
                            title="Пороги KPI-алерта (условное форматирование)">⚠</button>
                        )}
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
                  <SourceCatalog sources={sources} />
                  {sources.datasets.length > 0 && <SuggestPanel datasets={sources.datasets} onAdd={addWidgetsBatch} />}
                  <WidgetForm sources={sources} onCreate={addWidget} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {alertWidget && (
        <AlertEditor widget={alertWidget} onClose={() => setAlertWidget(null)}
          onSaved={async () => { setAlertWidget(null); await reloadPage(); setReloadKey((k) => k + 1) }} />
      )}
      {editWidget && sources && (
        <div style={overlay} onClick={() => setEditWidget(null)}>
          <div style={{ ...dialog, width: 680 }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
              <div style={{ fontSize: 16, fontWeight: 600 }}>✎ Изменить виджет: {editWidget.name}</div>
              <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={() => setEditWidget(null)}>✕</button>
            </div>
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 12 }}>
              Смените тип, источник, датасет или поля — размещение на странице и пороги алертов сохранятся.
            </div>
            <WidgetForm sources={sources} initial={editWidget} submitLabel="Сохранить" onCreate={saveWidgetEdit} />
          </div>
        </div>
      )}
      {accessOpen && sel && (
        <AccessEditor dashboard={sel.dashboard} onClose={() => setAccessOpen(false)} />
      )}
      {kiosk && sel && (
        <KioskView dashboardName={sel.dashboard.name} pages={sel.pages} onClose={() => setKiosk(false)} />
      )}
    </div>
  )
}

// ── Редактор доступа к дашборду (RLS: выдача просмотра ролям/пользователям) ──
function AccessEditor({ dashboard, onClose }: { dashboard: Dashboard; onClose: () => void }) {
  const [grants, setGrants] = useState<DashGrant[]>([])
  const [targets, setTargets] = useState<GrantTargets | null>(null)
  const [gtype, setGtype] = useState<'role' | 'user'>('user')
  const [gid, setGid] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => listDashboardGrants(dashboard.id).then((d) => { setGrants(d.grants); setTargets(d.targets) }).catch((e) => setErr((e as Error).message))
  useEffect(() => { load() }, [dashboard.id])

  const options = gtype === 'role' ? (targets?.roles.map((r) => ({ v: r.id, t: r.name })) || [])
    : (targets?.users.map((u) => ({ v: u.id, t: u.full_name || u.login })) || [])

  async function add() {
    if (!gid) { setErr('Выберите, кому выдать доступ'); return }
    setErr(null); setBusy(true)
    try {
      await addDashboardGrant(dashboard.id, gtype === 'role' ? { grantee_type: 'role', role_id: gid } : { grantee_type: 'user', user_id: gid })
      setGid(''); await load()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function remove(id: string) {
    setErr(null)
    try { await removeDashboardGrant(dashboard.id, id); await load() } catch (e) { setErr((e as Error).message) }
  }

  return (
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 560 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>🔒 Доступ: {dashboard.name}</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 12 }}>
          Администраторы и модераторы видят все дашборды. Остальные — только выданные здесь (по роли или пользователю) и созданные ими самими.
        </div>

        <div style={{ marginBottom: 12 }}>
          {grants.length === 0 ? <div style={muted}>Явных грантов нет — дашборд виден только администраторам/модераторам и автору.</div> : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {grants.map((g) => (
                <span key={g.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, background: '#eef', color: '#2f5496', padding: '4px 10px', borderRadius: 12 }}>
                  {g.grantee_type === 'role' ? '👥' : '👤'} {g.label}
                  <button style={{ border: 'none', background: 'none', color: '#a32d2d', cursor: 'pointer', padding: 0 }} onClick={() => remove(g.id)} title="Убрать доступ">✕</button>
                </span>
              ))}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <F t="Кому"><select style={sel} value={gtype} onChange={(e) => { setGtype(e.target.value as 'role' | 'user'); setGid('') }}>
            <option value="user">Пользователю</option><option value="role">Роли</option>
          </select></F>
          <F t={gtype === 'role' ? 'Роль' : 'Пользователь'}>
            <select style={{ ...sel, minWidth: 200 }} value={gid} onChange={(e) => setGid(e.target.value)}>
              <option value="">выберите…</option>
              {options.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}
            </select>
          </F>
          <button style={btn} disabled={busy} onClick={add}>＋ Выдать доступ</button>
        </div>
        {err && <div style={{ color: '#a32d2d', fontSize: 13, marginTop: 10 }}>{err}</div>}
      </div>
    </div>
  )
}

// ── Редактор порогов KPI-алерта (условное форматирование) ──────────────────
type AlertRule = { level: string; op: string; value: string; value2?: string; label?: string }
const LEVELS = [
  { v: 'danger', t: 'Критично (красный)' }, { v: 'warn', t: 'Внимание (жёлтый)' }, { v: 'good', t: 'Хорошо (зелёный)' },
]
const OPS = [
  { v: 'lt', t: '<' }, { v: 'lte', t: '≤' }, { v: 'gt', t: '>' }, { v: 'gte', t: '≥' },
  { v: 'eq', t: '=' }, { v: 'between', t: 'в диапазоне' }, { v: 'outside', t: 'вне диапазона' },
]
const ALERT_ON: Record<string, { v: string; t: string }[]> = {
  plan_fact: [{ v: 'pct', t: 'Выполнение, %' }, { v: 'fact', t: 'Факт' }, { v: 'delta', t: 'Δ (факт−план)' }, { v: 'plan', t: 'План' }],
  dynamics: [{ v: 'last', t: 'Последний период' }, { v: 'change', t: 'Δ к пред.' }, { v: 'change_pct', t: 'Δ %, к пред.' }],
}

function AlertEditor({ widget, onClose, onSaved }: { widget: Widget; onClose: () => void; onSaved: () => void }) {
  const cfg = (widget.config || {}) as Record<string, unknown>
  const init = (cfg.alerts as AlertRule[] | undefined)?.map((r) => ({
    level: r.level || 'danger', op: r.op || 'lt', value: String(r.value ?? ''),
    value2: r.value2 != null ? String(r.value2) : '', label: r.label || '',
  })) || []
  const [rules, setRules] = useState<AlertRule[]>(init)
  const [alertOn, setAlertOn] = useState<string>((cfg.alert_on as string) || (widget.widget_type === 'plan_fact' ? 'pct' : widget.widget_type === 'dynamics' ? 'last' : 'value'))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const onOpts = ALERT_ON[widget.widget_type]

  const set = (i: number, patch: Partial<AlertRule>) => setRules((rs) => rs.map((r, k) => k === i ? { ...r, ...patch } : r))
  const add = () => setRules((rs) => [...rs, { level: 'danger', op: 'lt', value: '', value2: '', label: '' }])
  const del = (i: number) => setRules((rs) => rs.filter((_, k) => k !== i))

  async function save() {
    setErr(null)
    const clean: any[] = []
    for (const r of rules) {
      if (r.value === '' || isNaN(Number(r.value))) { setErr('Заполните числовой порог во всех правилах'); return }
      const rule: any = { level: r.level, op: r.op, value: Number(r.value) }
      if (r.op === 'between' || r.op === 'outside') {
        if (r.value2 === '' || isNaN(Number(r.value2))) { setErr('Для диапазона нужны два значения'); return }
        rule.value2 = Number(r.value2)
      }
      if (r.label?.trim()) rule.label = r.label.trim()
      clean.push(rule)
    }
    const newCfg: Record<string, unknown> = { ...cfg, alerts: clean }
    if (onOpts) newCfg.alert_on = alertOn; else delete newCfg.alert_on
    setBusy(true)
    try { await updateWidget(widget.id, { config: newCfg }); onSaved() }
    catch (e) { setErr((e as Error).message); setBusy(false) }
  }

  return (
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 640 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>⚠ Пороги KPI-алерта: {widget.name}</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 12 }}>
          Правила проверяются сверху вниз; срабатывает первое подходящее и задаёт цвет виджета.
        </div>

        {onOpts && (
          <div style={{ marginBottom: 12 }}>
            <F t="Сравнивать по">
              <select style={sel} value={alertOn} onChange={(e) => setAlertOn(e.target.value)}>
                {onOpts.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}
              </select>
            </F>
          </div>
        )}

        {rules.length === 0 && <div style={{ ...muted, marginBottom: 10 }}>Порогов пока нет. Добавьте правило ниже.</div>}
        {rules.map((r, i) => (
          <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 8, borderBottom: '1px solid #f1f3f5', paddingBottom: 8 }}>
            <F t="Уровень"><select style={sel} value={r.level} onChange={(e) => set(i, { level: e.target.value })}>{LEVELS.map((l) => <option key={l.v} value={l.v}>{l.t}</option>)}</select></F>
            <F t="Условие"><select style={sel} value={r.op} onChange={(e) => set(i, { op: e.target.value })}>{OPS.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}</select></F>
            <F t="Значение"><input style={{ ...sel, width: 90 }} type="number" value={r.value} onChange={(e) => set(i, { value: e.target.value })} /></F>
            {(r.op === 'between' || r.op === 'outside') && (
              <F t="…до"><input style={{ ...sel, width: 90 }} type="number" value={r.value2} onChange={(e) => set(i, { value2: e.target.value })} /></F>
            )}
            <F t="Подпись (необяз.)"><input style={{ ...sel, width: 150 }} placeholder="напр. План не выполнен" value={r.label} onChange={(e) => set(i, { label: e.target.value })} /></F>
            <button style={rmBtn} onClick={() => del(i)} title="Удалить правило">✕</button>
          </div>
        ))}

        {err && <div style={{ color: '#a32d2d', fontSize: 13, marginTop: 6 }}>{err}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button style={btnGhost} onClick={add}>+ Правило</button>
          <button style={{ ...btn, marginLeft: 'auto' }} disabled={busy} onClick={save}>{busy ? 'Сохранение…' : 'Сохранить'}</button>
        </div>
      </div>
    </div>
  )
}

// ── Каталог источников: что можно применить (документы→датасеты→поля/строки/периоды + метрики) ──
function SourceCatalog({ sources }: { sources: DataSources }) {
  const [open, setOpen] = useState(false)
  const [exp, setExp] = useState<string | null>(null)
  if (!open) {
    return (
      <button style={{ ...btnGhost, height: 34, marginBottom: 12 }} onClick={() => setOpen(true)}
        title="Какие документы, датасеты, поля, строки, показатели можно применить">
        📚 Каталог источников
      </button>
    )
  }
  const chip = (bg: string, color: string): React.CSSProperties => ({ display: 'inline-block', margin: '2px 4px 2px 0', padding: '1px 8px', borderRadius: 8, background: bg, color, fontSize: 12 })
  return (
    <div style={{ border: '1px solid #d1d5db', borderRadius: 10, padding: 12, marginBottom: 12, background: '#f8fafc' }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
        <b style={{ fontSize: 13 }}>📚 Каталог источников</b>
        <span style={{ fontSize: 12, color: '#6b7280', marginLeft: 8 }}>что можно применить в дашборде</span>
        <button style={{ ...btnGhost, height: 28, marginLeft: 'auto' }} onClick={() => setOpen(false)}>Скрыть</button>
      </div>

      <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Датасеты (из документов) — клик раскрывает поля/строки/периоды</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
        {sources.datasets.length === 0 && <span style={{ fontSize: 12, color: '#9aa4b2' }}>Нет датасетов — сначала распознайте документ.</span>}
        {sources.datasets.map((d) => (
          <div key={d.code} style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '6px 10px', background: '#fff' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }} onClick={() => setExp(exp === d.code ? null : d.code)}>
              <span style={{ color: '#2f5496' }}>{exp === d.code ? '▾' : '▸'}</span>
              <span style={{ fontSize: 13, fontWeight: 600 }}>{d.name}</span>
              <span style={{ fontSize: 11, color: '#9aa4b2' }}>({d.code})</span>
              <span style={{ fontSize: 12, color: '#6b7280', marginLeft: 'auto' }}>📄 {[d.document, d.folder, d.object].filter(Boolean).join(' · ') || '—'}</span>
            </div>
            {exp === d.code && (
              <div style={{ marginTop: 8, fontSize: 12, color: '#374151' }}>
                <div style={{ marginBottom: 4 }}><b>Поля/столбцы:</b> {d.fields.length === 0 ? '—' : d.fields.map((f) => (
                  <span key={f.code} style={chip('#eef', '#2f5496')}>{f.name} <span style={{ color: '#9aa4b2' }}>· {f.data_type === 'number' ? 'число' : f.data_type === 'date' ? 'дата' : 'текст'}{f.is_row_label ? ' · строка' : ''}</span></span>
                ))}</div>
                <div style={{ marginBottom: 4 }}><b>Строки:</b> {d.rows.length === 0 ? '—' : d.rows.map((r, i) => <span key={i} style={chip('#f1f2f4', '#374151')}>{r}</span>)}</div>
                <div><b>Периоды:</b> {d.dates.length === 0 ? '—' : d.dates.join(', ')}</div>
              </div>
            )}
          </div>
        ))}
      </div>

      <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Показатели (метрики) — готовые формулы для KPI/план-факта</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {sources.metrics.length === 0 && <span style={{ fontSize: 12, color: '#9aa4b2' }}>Нет метрик — создайте в разделе «Метрики».</span>}
        {sources.metrics.map((m) => <span key={m.code} style={chip('#eef', '#2f5496')}>{m.name} <span style={{ color: '#9aa4b2' }}>({m.code})</span></span>)}
      </div>
    </div>
  )
}

// ── Подсказки «что собрать»: система предлагает виджеты под выбранный датасет ──
function SuggestPanel({ datasets, onAdd }: { datasets: DataSources['datasets']; onAdd: (specs: WidgetSpec[]) => Promise<void> }) {
  const [dc, setDc] = useState(datasets[0]?.code || '')
  const [specs, setSpecs] = useState<WidgetSpec[]>([])
  const [chosen, setChosen] = useState<Set<number>>(new Set())
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)

  function load(code: string) {
    setErr(null); setSpecs([]); setChosen(new Set())
    if (!code) return
    widgetSuggestions(code).then((s) => { setSpecs(s); setChosen(new Set(s.map((_, i) => i))) }).catch((e) => setErr((e as Error).message))
  }
  useEffect(() => { if (open && dc) load(dc) }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (i: number) => setChosen((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n })
  async function add() {
    const picked = specs.filter((_, i) => chosen.has(i))
    if (!picked.length) return
    setBusy(true)
    try { await onAdd(picked) } finally { setBusy(false) }
  }

  if (!open) {
    return (
      <button style={{ ...btnAuto, height: 34, marginBottom: 12 }} onClick={() => setOpen(true)}>
        ✨ Предложить виджеты под датасет
      </button>
    )
  }
  return (
    <div style={{ border: '1px solid #d1d5db', borderRadius: 10, padding: 12, marginBottom: 12, background: '#f8fafc' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <F t="Датасет"><select style={sel} value={dc} onChange={(e) => { setDc(e.target.value); load(e.target.value) }}>
          {datasets.map((d) => <option key={d.code} value={d.code}>{d.name} ({d.code})</option>)}
        </select></F>
        <button style={{ ...btn, height: 34 }} disabled={busy || chosen.size === 0} onClick={add}>{busy ? 'Добавление…' : `＋ Добавить выбранные (${chosen.size})`}</button>
        <button style={{ ...btnGhost, height: 34 }} onClick={() => setOpen(false)}>Скрыть</button>
        <span style={{ fontSize: 12, color: '#6b7280' }}>отметьте нужные предложения</span>
      </div>
      {err && <div style={{ color: '#a32d2d', fontSize: 12, marginBottom: 6 }}>{err}</div>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {specs.length === 0 && !err && <span style={{ fontSize: 12, color: '#9aa4b2' }}>Нет предложений.</span>}
        {specs.map((s, i) => (
          <label key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, border: '1px solid #e5e7eb', borderRadius: 8, padding: '5px 10px', background: chosen.has(i) ? '#eef' : '#fff', cursor: 'pointer' }}>
            <input type="checkbox" checked={chosen.has(i)} onChange={() => toggle(i)} />
            {s.name}
            <span style={{ ...wtBadge, marginLeft: 4 }}>{WT.find((x) => x.v === s.widget_type)?.t || s.widget_type}</span>
          </label>
        ))}
      </div>
    </div>
  )
}

function WidgetForm({ sources, onCreate, initial, submitLabel }: {
  sources: DataSources
  onCreate: (b: { name: string; widget_type: string; config: Record<string, unknown>; width?: number; height?: number }) => void
  initial?: Widget
  submitLabel?: string
}) {
  const cfg0 = (initial?.config || {}) as Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any
  const numFields = (dc: string) => (sources.datasets.find((d) => d.code === dc)?.fields.filter((f) => f.data_type === 'number') || [])
  const initDataset = cfg0.dataset_code || sources.datasets[0]?.code || ''
  const [name, setName] = useState(initial?.name || '')
  const [type, setType] = useState(initial?.widget_type || 'kpi')
  const [source, setSource] = useState<'metric' | 'dataset' | 'formula'>(cfg0.formula ? 'formula' : (cfg0.metric_code || cfg0.plan_metric) ? 'metric' : (cfg0.dataset_code ? 'dataset' : 'metric'))
  const [formulaDsl, setFormulaDsl] = useState<string>(cfg0.formula || '')
  const [formulaUnit, setFormulaUnit] = useState<string>(cfg0.unit || '')
  const [metricCode, setMetricCode] = useState(cfg0.metric_code || cfg0.plan_metric || sources.metrics[0]?.code || '')
  const [factMetric, setFactMetric] = useState(cfg0.fact_metric || sources.metrics[1]?.code || sources.metrics[0]?.code || '')
  const [dataset, setDataset] = useState(initDataset)
  const [valueField, setValueField] = useState(cfg0.value_field || numFields(initDataset)[0]?.code || '')
  const [planField, setPlanField] = useState(cfg0.plan_field || numFields(initDataset)[0]?.code || '')
  const [factField, setFactField] = useState(cfg0.fact_field || numFields(initDataset)[0]?.code || '')
  const [multiFields, setMultiFields] = useState<string[]>(cfg0.value_fields || [])
  const [viz, setViz] = useState(cfg0.viz || 'bar')
  const [heading, setHeading] = useState(cfg0.heading || '')
  const [bodyText, setBodyText] = useState(cfg0.body || '')
  const [align, setAlign] = useState(cfg0.align || 'left')
  const [imgUrl, setImgUrl] = useState(cfg0.url || '')
  const [caption, setCaption] = useState(cfg0.caption || '')

  const isText = type === 'text'
  const isImage = type === 'image'
  const usesSource = type === 'kpi' || type === 'plan_fact'
  const usesDataset = (usesSource && source === 'dataset') || type === 'table' || ['bar', 'line', 'pie', 'dynamics', 'compare'].includes(type)
  const usesValueField = ['bar', 'line', 'pie', 'dynamics'].includes(type) || (type === 'kpi' && source === 'dataset')
  const usesMulti = type === 'compare'
  const toggleField = (c: string) => setMultiFields((s) => s.includes(c) ? s.filter((x) => x !== c) : [...s, c])

  // Собирает config по текущему выбору; null — если данных для показа ещё недостаточно.
  function currentConfig(): Record<string, unknown> | null {
    if (type === 'text') return { heading: heading.trim() || undefined, body: bodyText.trim() || undefined, align }
    if (type === 'image') return imgUrl.trim() ? { url: imgUrl.trim(), caption: caption.trim() || undefined, fit: 'contain' } : null
    if (type === 'kpi') return source === 'formula' ? (formulaDsl.trim() ? { formula: formulaDsl.trim(), unit: formulaUnit.trim() || undefined } : null)
      : source === 'metric' ? (metricCode ? { metric_code: metricCode } : null) : ((dataset && valueField) ? { dataset_code: dataset, value_field: valueField } : null)
    if (type === 'plan_fact') return source === 'metric' ? ((metricCode && factMetric) ? { plan_metric: metricCode, fact_metric: factMetric } : null) : ((dataset && planField && factField) ? { dataset_code: dataset, plan_field: planField, fact_field: factField } : null)
    if (type === 'table') return dataset ? { dataset_code: dataset } : null
    if (type === 'compare') return (dataset && multiFields.length) ? { dataset_code: dataset, value_fields: multiFields, viz } : null
    return (dataset && valueField) ? { dataset_code: dataset, value_field: valueField } : null // bar/line/pie/dynamics
  }

  // Живой предпросмотр (как в конструкторе формул): рендер по конфигу без сохранения.
  const [preview, setPreview] = useState<any>(null) // eslint-disable-line @typescript-eslint/no-explicit-any
  const [previewErr, setPreviewErr] = useState<string | null>(null)
  const cfgKey = JSON.stringify([type, currentConfig(), name])
  useEffect(() => {
    const config = currentConfig()
    if (!config) { setPreview(null); setPreviewErr(null); return }
    let cancelled = false
    const t = setTimeout(() => {
      previewWidget({ widget_type: type, name: name.trim() || undefined, config })
        .then((d) => { if (!cancelled) { setPreview(d); setPreviewErr(null) } })
        .catch((e) => { if (!cancelled) { setPreview(null); setPreviewErr((e as Error).message) } })
    }, 350)
    return () => { cancelled = true; clearTimeout(t) }
  }, [cfgKey]) // eslint-disable-line react-hooks/exhaustive-deps

  function submit(e: FormEvent) {
    e.preventDefault()
    const config = currentConfig()
    if (!config) return
    // при редактировании сохраняем условное форматирование (алерты), если тип по-прежнему его поддерживает
    if (initial && cfg0.alerts && ['kpi', 'plan_fact', 'dynamics'].includes(type)) {
      config.alerts = cfg0.alerts
      if (cfg0.alert_on) config.alert_on = cfg0.alert_on
    }
    const body: { name: string; widget_type: string; config: Record<string, unknown>; width?: number; height?: number } = {
      name: name.trim() || WT.find((x) => x.v === type)?.t || type, widget_type: type, config,
    }
    if (!initial) { const sz = DEFAULT_SIZE[type] || { w: 4, h: 4 }; body.width = sz.w; body.height = sz.h } // размер только для новых
    onCreate(body)
    if (!initial) setName('')
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end', border: initial ? 'none' : '1px solid #e5e7eb', borderRadius: 10, padding: initial ? 0 : 12 }}>
      <F t="Название"><input style={sel} placeholder="Заголовок виджета" value={name} onChange={(e) => setName(e.target.value)} /></F>
      <F t="Тип"><select style={sel} value={type} onChange={(e) => { const v = e.target.value; setType(v); if (v !== 'kpi' && source === 'formula') setSource('metric') }}>{WT.map((x) => <option key={x.v} value={x.v}>{x.t}</option>)}</select></F>
      {isText && (
        <>
          <F t="Заголовок (крупно)"><input style={{ ...sel, width: 200 }} placeholder="напр. Итоги квартала" value={heading} onChange={(e) => setHeading(e.target.value)} /></F>
          <F t="Текст"><input style={{ ...sel, width: 260 }} placeholder="пояснение к разделу" value={bodyText} onChange={(e) => setBodyText(e.target.value)} /></F>
          <F t="Выравнивание"><select style={sel} value={align} onChange={(e) => setAlign(e.target.value)}><option value="left">Слева</option><option value="center">По центру</option></select></F>
        </>
      )}
      {isImage && (
        <>
          <F t="URL картинки"><input style={{ ...sel, width: 300 }} placeholder="https://… или data:image/…" value={imgUrl} onChange={(e) => setImgUrl(e.target.value)} /></F>
          <F t="Подпись (необяз.)"><input style={{ ...sel, width: 180 }} placeholder="напр. Логотип МФЦ" value={caption} onChange={(e) => setCaption(e.target.value)} /></F>
        </>
      )}
      {usesSource && (
        <F t="Источник"><select style={sel} value={source} onChange={(e) => setSource(e.target.value as 'metric' | 'dataset' | 'formula')}>
          <option value="metric">Метрика</option><option value="dataset">Датасет</option>
          {type === 'kpi' && <option value="formula">Формула</option>}
        </select></F>
      )}
      {type === 'kpi' && source === 'formula' && (
        <>
          <F t="Единица (необяз.)"><input style={{ ...sel, width: 110 }} placeholder="напр. шт, %" value={formulaUnit} onChange={(e) => setFormulaUnit(e.target.value)} /></F>
          <div style={{ flexBasis: '100%' }}>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Формула показателя — соберите мышью ниже или введите текстом; считается на лету, без создания метрики</div>
            <input style={{ ...sel, width: '100%', fontFamily: 'ui-monospace, monospace', marginBottom: 8 }}
              placeholder="напр. SUM(field('plan','kol')) + 10" value={formulaDsl} onChange={(e) => setFormulaDsl(e.target.value)} />
            <FormulaBuilder sources={sources} onFormula={setFormulaDsl} />
          </div>
        </>
      )}
      {usesSource && source === 'metric' && (
        <F t={type === 'plan_fact' ? 'Метрика (план)' : 'Метрика'}><select style={sel} value={metricCode} onChange={(e) => setMetricCode(e.target.value)}>{sources.metrics.map((m) => <option key={m.code} value={m.code}>{m.name}{m.unit ? ` · ${m.unit}` : ''}</option>)}</select></F>
      )}
      {type === 'plan_fact' && source === 'metric' && (
        <F t="Метрика (факт)"><select style={sel} value={factMetric} onChange={(e) => setFactMetric(e.target.value)}>{sources.metrics.map((m) => <option key={m.code} value={m.code}>{m.name}{m.unit ? ` · ${m.unit}` : ''}</option>)}</select></F>
      )}
      {usesSource && source === 'metric' && (() => {
        const line = (lbl: string, x?: MetricSource) => (x && (x.formula || x.unit)) ? (
          <div style={{ fontSize: 11, color: '#6b7280' }}>{lbl}<b style={{ color: '#374151' }}>{x.name}</b>{x.unit ? ` · ед.: ${x.unit}` : ''}{x.formula ? <> · формула: <code style={{ fontFamily: 'ui-monospace, monospace', background: '#f1f2f4', padding: '0 4px', borderRadius: 4 }}>{x.formula}</code></> : ''}</div>
        ) : null
        const m = sources.metrics.find((x) => x.code === metricCode)
        const fm = type === 'plan_fact' ? sources.metrics.find((x) => x.code === factMetric) : undefined
        return (m || fm) ? <div style={{ flexBasis: '100%', margin: '-2px 0 2px' }}>{line(type === 'plan_fact' ? 'План: ' : '', m)}{line('Факт: ', fm)}</div> : null
      })()}
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
      <div style={{ flexBasis: '100%', marginTop: 6 }}>
        <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Предпросмотр</div>
        <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: 12, minHeight: 56, background: '#fff' }}>
          {previewErr ? <div style={{ color: '#a32d2d', fontSize: 12 }}>{previewErr}</div>
            : preview ? <WidgetPreviewBody data={preview} />
              : <div style={{ color: '#9aa4b2', fontSize: 12 }}>Заполните поля — здесь появится живой предпросмотр виджета</div>}
        </div>
      </div>
      <button style={{ ...btn, flexBasis: '100%' }}>{submitLabel || 'Добавить'}</button>
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
const presetChip: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, background: '#eef', padding: '3px 10px', borderRadius: 12 }
const tabActive: React.CSSProperties = { background: '#eef', border: '1px solid #2f5496', color: '#2f5496' }
const widgetCard: React.CSSProperties = { border: '1px solid #e5e7eb', borderRadius: 12, padding: 14, background: '#fff' }
const wtBadge: React.CSSProperties = { marginLeft: 8, fontSize: 11, padding: '1px 7px', borderRadius: 8, background: '#eef', color: '#2f5496' }
const rmBtn: React.CSSProperties = { marginLeft: 'auto', width: 24, height: 24, border: '1px solid #e5e7eb', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#a32d2d' }
const muted: React.CSSProperties = { color: '#6b7280', fontSize: 14, padding: '8px 0' }
const errBox: React.CSSProperties = { background: '#fcebeb', color: '#a32d2d', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const linkDanger: React.CSSProperties = { border: 'none', background: 'none', color: '#a32d2d', cursor: 'pointer', fontSize: 12, padding: 0 }
const alertBtn: React.CSSProperties = { marginLeft: 8, width: 24, height: 24, border: '1px solid #e5e7eb', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#9a6a00' }
const editBtn: React.CSSProperties = { marginLeft: 8, width: 24, height: 24, border: '1px solid #e5e7eb', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#2f5496' }
const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60, padding: 20 }
const dialog: React.CSSProperties = { background: '#fff', borderRadius: 14, padding: 22, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }
