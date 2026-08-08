import { useEffect, useRef, useState, type FormEvent } from 'react'
import GridLayout, { type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import {
  autoBuildDashboard, createDashboard, createPage, createPreset, createWidget, deleteDashboard, deletePage, deletePreset, deleteWidget, getDashboard,
  exportPageXlsx, getDataSources, getPageData, getTemplateBindings, instantiateTemplate, listDashboardVersions, listDashboards, listFolders, listObjects, listPageWidgets, listPresets,
  listTemplates, logClientExport, moveDashboardToFolder, publishDashboard, restoreDashboardVersion, saveAsTemplate, setDashboardFavorite, submitDashboardReview, cancelDashboardReview, unpublishDashboard, updateWidget,
  type Dashboard, type DashPage, type DashPreset, type DashTemplate, type DataSources, type Folder, type Obj, type PageWidgetData, type Widget, type WidgetSpec,
} from '../api'
import { useContainerWidth } from '../lib/useWidth'
import { elideMiddle } from '../lib/text'
import WidgetView from './WidgetView'
import InfoTip from './InfoTip'
import { WIDGET_META } from './dashboards/WidgetPicker'
import KioskView from './KioskView'
import ArchiveDialog from './dashboards/ArchiveDialog'
import { archiveDashboard, setAutoArchive } from '../api/archive'

import { AccessEditor } from './dashboards/AccessEditor'
import { Comments } from './dashboards/Comments'
import { AlertEditor } from './dashboards/AlertEditor'
import { DashboardList } from './dashboards/DashboardList'
import { FolderMoveDialog } from './dashboards/FolderMoveDialog'
import { RebindModal, type RebindState } from './dashboards/RebindModal'
import { SourceCatalog, SuggestMetricsPanel, SuggestPanel, WidgetForm } from './dashboards/WidgetForm'
import { PubBadge, WT, alertBtn, btn, btnGhost, crumb, dialog, editBtn, editHint, errBox, input, linkDanger, muted, overlay, presetChip, rmBtn, tab, tabActive, widgetCard, wtBadge } from './dashboards/shared'


const DASH_PAGE = 50

// Текст тултипа виджета: подсказка по типу (из галереи) + авторская заметка
// (config.help), если задана в форме виджета.
function widgetTip(w: { widget_type: string; config: Record<string, unknown> }): string {
  const typeHint = WIDGET_META[w.widget_type]?.hint || ''
  const help = typeof w.config?.help === 'string' ? (w.config.help as string).trim() : ''
  return [typeHint, help].filter(Boolean).join('. ')
}

// html2canvas не понимает CSS-переменные в backgroundColor — резолвим токен
// текущей темы в реальный цвет (фон выгрузки PDF/PNG совпадает с темой).
function surfaceColor(): string {
  return getComputedStyle(document.documentElement).getPropertyValue('--surface').trim() || '#ffffff'
}

export default function DashboardsPage({ canManage, isAdmin, initialDashboardId }: { canManage: boolean; isAdmin?: boolean; initialDashboardId?: string | null }) {
  const [dashboards, setDashboards] = useState<Dashboard[]>([])
  const [dashTotal, setDashTotal] = useState(0)
  const [query, setQuery] = useState('')
  const [favOnly, setFavOnly] = useState(false)
  const [dashFrom, setDashFrom] = useState('')
  const [dashTo, setDashTo] = useState('')
  // Фильтр списка по папке («банк отделов», волна D): Объект → Папка; '' = все,
  // folderFilter='none' = без папки.
  const [filterObjId, setFilterObjId] = useState('')
  const [filterFolders, setFilterFolders] = useState<Folder[]>([])
  const [folderFilter, setFolderFilter] = useState('')
  // Диалог «в какую папку»: обслуживает и одиночное перемещение (из открытого
  // дашборда), и массовое (из списка, по чекбоксам) — ids содержит 1 или N.
  const [folderTarget, setFolderTarget] = useState<{ ids: string[]; label: string; currentPath?: string | null } | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
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
  // Батч-данные страницы: один запрос на все виджеты (перф, вместо N запросов).
  // Виджеты всегда в батч-режиме (ждут данные родителя, не фетчат сами); при СБОЕ
  // батча — фолбэк: batchFailed=true → виджеты дофетчат по одному.
  const [pageData, setPageData] = useState<Record<string, PageWidgetData>>({})
  const [batchFailed, setBatchFailed] = useState(false)
  useEffect(() => {
    if (!page) { setPageData({}); setBatchFailed(false); return }
    let cancelled = false
    setPageData({}); setBatchFailed(false)
    getPageData(page.id, pFrom || undefined, pTo || undefined, crossRow || undefined)
      .then((r) => { if (cancelled) return; const m: Record<string, PageWidgetData> = {}; r.widgets.forEach((w) => { m[w.id] = w }); setPageData(m) })
      .catch(() => { if (!cancelled) setBatchFailed(true) }) // фолбэк на self-fetch
    return () => { cancelled = true }
  }, [page?.id, pFrom, pTo, crossRow, reloadKey]) // eslint-disable-line react-hooks/exhaustive-deps
  const pageRef = useRef<HTMLDivElement>(null)
  const [objects, setObjects] = useState<Obj[]>([])
  const [autoObj, setAutoObj] = useState('')
  const [templates, setTemplates] = useState<DashTemplate[]>([])
  const [tpl, setTpl] = useState('')
  const [rebind, setRebind] = useState<RebindState | null>(null)
  const [editMode, setEditMode] = useState(false)
  // Свёрнутые виджеты (видимость тела скрыта, чтобы страница не была бесконечно
  // длинной) — предпочтение хранится локально в браузере, не на сервере.
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem('dashbord_collapsed_widgets') || '[]')) } catch { return new Set() }
  })
  function toggleCollapse(id: string) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      localStorage.setItem('dashbord_collapsed_widgets', JSON.stringify([...next]))
      return next
    })
  }
  const [versions, setVersions] = useState<{ version_no: number; status_code: string; created_at: string }[] | null>(null)
  const [alertWidget, setAlertWidget] = useState<Widget | null>(null)
  const [editWidget, setEditWidget] = useState<Widget | null>(null)
  const [accessOpen, setAccessOpen] = useState(false)
  const [commentsOpen, setCommentsOpen] = useState(false)
  const [archiveOpen, setArchiveOpen] = useState(false)
  const [presets, setPresets] = useState<DashPreset[]>([])
  const [kiosk, setKiosk] = useState(false)
  const [gridRef, gridWidth] = useContainerWidth<HTMLDivElement>()

  const fail = (e: unknown) => setError((e as Error).message)
  // Защита от гонки ответов: применяем только результат последнего запроса.
  const dashSeq = useRef(0)
  const loadDashboards = (q: string, fav: boolean, fromD = dashFrom, toD = dashTo, folderF = folderFilter) => {
    const seq = ++dashSeq.current
    return listDashboards(q, fav, DASH_PAGE, 0, fromD, toD, folderF)
      .then((p) => { if (seq === dashSeq.current) { setDashboards(p.items); setDashTotal(p.total) } }).catch(fail)
  }
  const refresh = () => loadDashboards(query, favOnly)
  async function loadMoreDash() {
    const seq = ++dashSeq.current
    try { const p = await listDashboards(query, favOnly, DASH_PAGE, dashboards.length, dashFrom, dashTo, folderFilter); if (seq === dashSeq.current) { setDashboards((prev) => [...prev, ...p.items]); setDashTotal(p.total) } } catch (e) { fail(e) }
  }
  async function toggleFav(e: React.MouseEvent, d: Dashboard) {
    e.stopPropagation()
    try { await setDashboardFavorite(d.id, !d.is_favorite); refresh() } catch (e) { fail(e) }
  }
  async function doMoveFolder(folderId: string | null) {
    if (!folderTarget) return
    const ids = folderTarget.ids
    try {
      for (const id of ids) await moveDashboardToFolder(id, folderId)
      setFolderTarget(null)
      setSelectedIds(new Set())
      if (sel && ids.includes(sel.dashboard.id)) setSel(await getDashboard(sel.dashboard.id))
      await refresh()
    } catch (e) { fail(e) }
  }
  function toggleSelect(e: React.MouseEvent, id: string) {
    e.stopPropagation()
    setSelectedIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  // Список — по поиску/фильтру избранного с дебаунсом (он же начальная загрузка).
  useEffect(() => { const t = setTimeout(() => loadDashboards(query, favOnly), 250); return () => clearTimeout(t) }, [query, favOnly, dashFrom, dashTo, folderFilter]) // eslint-disable-line react-hooks/exhaustive-deps
  // Папки фильтра зависят от выбранного объекта.
  useEffect(() => {
    if (!filterObjId) { setFilterFolders([]); return }
    listFolders(filterObjId).then(setFilterFolders).catch(() => setFilterFolders([]))
  }, [filterObjId])
  useEffect(() => {
    getDataSources().then(setSources).catch(() => setSources({ datasets: [], metrics: [] }))
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
  async function doDeleteDashboard() {
    if (!sel) return
    if (!confirm(
      `Удалить дашборд «${sel.dashboard.name}»?\n\n` +
      'Вместе с ним удалятся его страницы, виджеты, права доступа и комментарии. ' +
      'Слепки в архиве сохранятся. Действие необратимо.')) return
    // Гасим прошлую ошибку: иначе после удачного удаления наверху остаётся
    // висеть предыдущий отказ («…снимите с публикации») — читается так, будто
    // и эта попытка провалилась.
    setError(null)
    try {
      await deleteDashboard(sel.dashboard.id)
      setSel(null)                       // вернуться к списку — дашборда больше нет
      await refresh()
    } catch (e) {
      fail(e)
    }
  }

  async function toggleAutoArchive() {
    if (!sel) return
    try {
      await setAutoArchive(sel.dashboard.id, !sel.dashboard.auto_archive)
      setSel(await getDashboard(sel.dashboard.id))
    } catch (e) { fail(e) }
  }
  async function doArchive(topic: string, note: string) {
    if (!sel) return
    try {
      await archiveDashboard(sel.dashboard.id, topic, note)
      setArchiveOpen(false)
      setSel(null)          // дашборд ушёл из основного списка — в раздел «Архив»
      await refresh()
    } catch (e) { fail(e) }
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
    try {
      // Проверяем, есть ли в текущем контексте все коды датасетов/метрик шаблона.
      // Если каких-то нет — открываем перепривязку, чтобы виджеты не сломались.
      const [b, src] = await Promise.all([getTemplateBindings(tpl), getDataSources()])
      const availDatasets = src.datasets.map((d) => ({ code: d.code, name: d.name }))
      const availMetrics = src.metrics.map((m) => ({ code: m.code, name: m.name }))
      const dcodes = new Set(availDatasets.map((d) => d.code))
      const mcodes = new Set(availMetrics.map((m) => m.code))
      const datasets = b.datasets.map((code) => ({ code, missing: !dcodes.has(code) }))
      const metrics = b.metrics.map((code) => ({ code, missing: !mcodes.has(code) }))
      if (!datasets.some((d) => d.missing) && !metrics.some((m) => m.missing)) {
        const r = await instantiateTemplate(tpl, name.trim())  // все коды на месте
        setTpl(''); await refresh(); openDashboard(r.dashboard_id)
      } else {
        setRebind({ templateId: tpl, name: name.trim(), datasets, metrics, availDatasets, availMetrics, datasetMap: {}, metricMap: {} })
      }
    } catch (e) { fail(e) } finally { setBusy(false) }
  }
  async function confirmRebind() {
    if (!rebind) return
    setBusy(true); setError(null)
    try {
      const r = await instantiateTemplate(rebind.templateId, rebind.name, rebind.datasetMap, rebind.metricMap)
      setRebind(null); setTpl(''); await refresh(); openDashboard(r.dashboard_id)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }
  async function exportPdf() {
    const el = pageRef.current
    if (!el || !sel || !page) return
    setExporting(true)
    try {
      // тяжёлые библиотеки грузим по требованию (динамический импорт → отдельный чанк)
      const [{ default: html2canvas }, { jsPDF }] = await Promise.all([import('html2canvas'), import('jspdf')])
      const canvas = await html2canvas(el, { scale: 2, backgroundColor: surfaceColor(), useCORS: true })
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
      logClientExport('dashboard', sel.dashboard.id, 'pdf')
    } catch (e) { fail(e) } finally { setExporting(false) }
  }
  async function exportPng() {
    const el = pageRef.current
    if (!el || !sel || !page) return
    setExporting(true)
    try {
      const { default: html2canvas } = await import('html2canvas')
      const canvas = await html2canvas(el, { scale: 2, backgroundColor: surfaceColor(), useCORS: true })
      const a = document.createElement('a')
      a.href = canvas.toDataURL('image/png'); a.download = `${sel.dashboard.name} — ${page.name}.png`; a.click()
      logClientExport('dashboard', sel.dashboard.id, 'png')
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
        {sel && <><span style={{ color: 'var(--text-faint)' }}>/</span><span>{sel.dashboard.name}</span></>}
      </div>

      {error && <div style={errBox}>{error}</div>}

      {!sel && (
        <DashboardList
          canManage={canManage} objects={objects} templates={templates}
          newDash={newDash} setNewDash={setNewDash} addDashboard={addDashboard} busy={busy}
          autoObj={autoObj} setAutoObj={setAutoObj} autoBuild={autoBuild}
          tpl={tpl} setTpl={setTpl} createFromTemplate={createFromTemplate}
          query={query} setQuery={setQuery} favOnly={favOnly} setFavOnly={setFavOnly}
          dashFrom={dashFrom} setDashFrom={setDashFrom} dashTo={dashTo} setDashTo={setDashTo}
          filterObjId={filterObjId} setFilterObjId={setFilterObjId} filterFolders={filterFolders}
          folderFilter={folderFilter} setFolderFilter={setFolderFilter}
          selectedIds={selectedIds} setSelectedIds={setSelectedIds} toggleSelect={toggleSelect}
          onBulkMove={() => setFolderTarget({ ids: [...selectedIds], label: `дашбордов: ${selectedIds.size}` })}
          dashboards={dashboards} dashTotal={dashTotal} openDashboard={openDashboard}
          toggleFav={toggleFav} loadMoreDash={loadMoreDash}
        />
      )}

      {sel && (
        <div>
          {/* Публикация и версии */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
            <PubBadge status={sel.dashboard.publication_status} />
            <span style={{ fontSize: 12, color: 'var(--text-faint)' }} title="Дата создания / последнего изменения дашборда">
              создан {new Date(sel.dashboard.created_at).toLocaleDateString('ru-RU')}
              {sel.dashboard.updated_at && sel.dashboard.updated_at !== sel.dashboard.created_at
                ? ` · изменён ${new Date(sel.dashboard.updated_at).toLocaleDateString('ru-RU')}` : ''}
            </span>
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
            {canManage && objects.length > 0 && (
              <button style={btnGhost}
                onClick={() => setFolderTarget({
                  ids: [sel.dashboard.id], label: sel.dashboard.name,
                  currentPath: sel.dashboard.folder_name ? `${sel.dashboard.object_name}/${sel.dashboard.folder_name}` : null,
                })}
                title="Разместить дашборд в папке объекта (банк отделов)">
                📁 {sel.dashboard.folder_name ? `${sel.dashboard.object_name}/${sel.dashboard.folder_name}` : 'Без папки'}
              </button>
            )}
            {canManage && <button style={btnGhost} onClick={() => setAccessOpen(true)} title="Кто видит этот дашборд">🔒 Доступ</button>}
            <button
              style={sel.dashboard.comments_count
                ? { ...btnGhost, borderColor: 'var(--accent)', color: 'var(--accent)', background: 'var(--accent-weak-bg)', fontWeight: 600 }
                : btnGhost}
              onClick={() => setCommentsOpen(true)}
              title={sel.dashboard.comments_count ? `Есть обсуждение: ${sel.dashboard.comments_count} коммент.` : 'Обсуждение дашборда (пока нет комментариев)'}>
              {sel.dashboard.comments_count ? `💬 Обсуждение (${sel.dashboard.comments_count})` : '💬 Обсуждение'}
            </button>
            {canManage && <button style={btnGhost} onClick={() => setArchiveOpen(true)} title="Слепок данных в архив; дашборд уйдёт из основного списка">📦 В архив</button>}
            {canManage && (
              <button style={{ ...btnGhost, ...(sel.dashboard.auto_archive ? { borderColor: 'var(--accent)', color: 'var(--accent)', background: 'var(--accent-weak-bg)' } : {}) }}
                title="Ежемесячная автоархивация: 1-го числа система сама сохранит слепок за прошедший месяц"
                onClick={toggleAutoArchive}>📅 автослепок {sel.dashboard.auto_archive ? 'вкл' : 'выкл'}</button>
            )}
            {/* Удаление — крайним и отдельным цветом: соседство с «В архив» не
                должно провоцировать промах, это разные по последствиям вещи. */}
            {canManage && (
              <button style={{ ...btnGhost, marginLeft: 'auto', borderColor: 'var(--danger)', color: 'var(--danger)' }}
                onClick={doDeleteDashboard}
                title="Удалить дашборд со страницами и виджетами (слепки в архиве сохранятся)">
                🗑 Удалить
              </button>
            )}
          </div>
          {versions && (
            <div style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 12, marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
                <b style={{ fontSize: 13 }}>История версий</b>
                <button style={{ ...linkDanger, marginLeft: 'auto', color: 'var(--text-muted)' }} onClick={() => setVersions(null)}>закрыть</button>
              </div>
              {versions.length === 0 ? <div style={muted}>Пока нет опубликованных версий.</div> : versions.map((v) => (
                <div key={v.version_no} style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 13, padding: '4px 0' }}>
                  <span>v{v.version_no}</span><span style={{ color: 'var(--text-muted)' }}>{v.status_code}</span>
                  <span style={{ color: 'var(--text-faint)' }}>{new Date(v.created_at).toLocaleString('ru-RU')}</span>
                  {canManage && <button style={{ ...linkDanger, color: 'var(--accent)', marginLeft: 'auto' }} onClick={() => doRestore(v.version_no)}>откатить</button>}
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
            <div ref={pageRef} style={{ background: 'var(--surface)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
                <h3 style={{ fontSize: 15, margin: 0 }}>Страница «{page.name}»</h3>
                {canManage && (
                  <button style={{ ...tab, height: 30, ...(editMode ? tabActive : {}) }}
                    title={editMode
                      ? 'Выйти из режима правки раскладки'
                      : 'Включить перетаскивание виджетов и изменение их размера'}
                    onClick={() => setEditMode((v) => !v)}>
                    {editMode ? '✓ Готово' : '✎ Двигать и менять размер'}
                  </button>
                )}
                {canManage && <button style={linkDanger} onClick={() => delPage(page)}>удалить страницу</button>}
                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-muted)', flexWrap: 'wrap' }}>
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
                  {crossRow && (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'var(--accent-weak-bg)', color: 'var(--accent)', padding: '2px 8px', borderRadius: 10, fontSize: 12 }}
                      title="Связанная фильтрация: клик по строке/столбцу фильтрует ВСЕ виджеты страницы по этой строке. Повторный клик снимает.">
                      🔗 связано: {crossRow}
                      <button style={{ border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', padding: 0, fontSize: 13 }} onClick={() => setCrossRow(null)}>✕</button>
                    </span>
                  )}
                  {(pFrom || pTo || crossRow) && <button style={linkDanger} onClick={() => { setPFrom(''); setPTo(''); setCrossRow(null) }}>сброс</button>}
                </div>
              </div>

              {/* Пресеты фильтров (сохранённые наборы, FR-13) */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Пресеты:</span>
                {presets.length === 0 && <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>нет сохранённых наборов</span>}
                {presets.map((p) => (
                  <span key={p.id} style={presetChip}>
                    <button style={{ border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', padding: 0, fontSize: 13 }} onClick={() => applyPreset(p)} title="Применить набор фильтров">{p.name}</button>
                    {canManage && <button style={{ border: 'none', background: 'none', color: 'var(--danger)', cursor: 'pointer', padding: 0 }} onClick={() => removePreset(p)} title="Удалить пресет">✕</button>}
                  </span>
                ))}
                {canManage && <button style={{ ...tab, height: 28 }} onClick={savePreset}>💾 Сохранить текущие</button>}
                <span style={{ fontSize: 12, color: 'var(--text-faint)', marginLeft: 4 }}>клик по столбцу/сектору тоже задаёт «Строку»</span>
              </div>

              {/* В режиме правки объясняем, ЧЕМ именно двигать и тянуть: без
                  подсказки перетаскивание и изменение размера просто не
                  находят — кнопка «Раскладка» об этом не говорит. */}
              {editMode && (
                <div style={editHint}>
                  ✎ Перетаскивайте виджет за <strong>заголовок</strong>, размер меняйте за
                  <strong> правый нижний угол</strong>. Свёрнутые виджеты не двигаются — разверните их (▸).
                  Положение и размер сохраняются сразу.
                </div>
              )}

              {/* Сетка виджетов (drag-drop в режиме раскладки). Ширина сетки —
                  ФАКТИЧЕСКАЯ ширина контейнера (useContainerWidth), а не 1280px
                  по умолчанию из WidthProvider: колонка контента ограничена
                  max-width, и сетка выезжала за неё — на странице дашборда
                  появлялась горизонтальная прокрутка, правый виджет обрезался. */}
              <div ref={gridRef}>
              {widgets.length === 0 ? <div style={muted}>На странице пока нет виджетов.</div> : gridWidth !== undefined && (
                <GridLayout className="layout" width={gridWidth} cols={12} rowHeight={40} margin={[12, 12]}
                  isDraggable={canManage && editMode} isResizable={canManage && editMode}
                  draggableHandle=".wdrag" compactType="vertical"
                  onDragStop={(_l, _o, n) => persistItem(n)} onResizeStop={(_l, _o, n) => persistItem(n)}
                  layout={widgets.map((w) => ({
                    i: w.id, x: w.position_x || 0, y: w.position_y || 0, w: w.width || 4,
                    h: collapsed.has(w.id) ? 1 : (w.height || 4),
                    isDraggable: canManage && editMode && !collapsed.has(w.id),
                    isResizable: canManage && editMode && !collapsed.has(w.id),
                  }))}>
                  {widgets.map((w) => (
                    <div key={w.id} style={{ ...widgetCard, height: '100%', overflow: 'hidden', outline: editMode ? '1px dashed var(--text-faint)' : 'none' }}>
                      {/* Шапка строго в одну строку. Иначе длинное имя виджета
                          («… · Факт · нарастающим итогом**») переносится, у
                          свёрнутого виджета высота всего 40px, и кнопка ▸
                          выезжает за карточку — свернуть можно, а развернуть
                          уже нечем. */}
                      <div className={editMode ? 'wdrag' : ''} style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'nowrap', marginBottom: 8, cursor: editMode ? 'move' : 'default' }}>
                        <button style={{ ...editBtn, cursor: 'pointer', flexShrink: 0 }} onClick={() => toggleCollapse(w.id)}
                          title={collapsed.has(w.id) ? 'Развернуть виджет' : 'Свернуть виджет'}>{collapsed.has(w.id) ? '▸' : '▾'}</button>
                        <div style={{ fontSize: 13, fontWeight: 600, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                          title={w.name}>{elideMiddle(w.name, 70)}</div>
                        <span style={{ ...wtBadge, flexShrink: 0 }}>{WT.find((x) => x.v === w.widget_type)?.t || w.widget_type}</span>
                        <span style={{ marginLeft: 6 }}>
                          <InfoTip text={widgetTip(w)} />
                        </span>
                        {canManage && sources && <button style={editBtn} onClick={() => setEditWidget(w)} title="Изменить данные/тип виджета">✎</button>}
                        {canManage && ['kpi', 'gauge', 'plan_fact', 'dynamics'].includes(w.widget_type) && (
                          <button style={alertBtn} onClick={() => setAlertWidget(w)}
                            title="Пороги KPI-алерта (условное форматирование)">⚠</button>
                        )}
                        {canManage && <button style={rmBtn} onClick={() => delWidget(w)} title="Удалить">✕</button>}
                      </div>
                      {!collapsed.has(w.id) && (
                        <div style={{ overflow: 'auto', maxHeight: 'calc(100% - 30px)' }}>
                          <WidgetView widgetId={w.id} reloadKey={reloadKey} from={pFrom || undefined} to={pTo || undefined} row={crossRow || undefined}
                            onPick={(name) => setCrossRow((cur) => cur === name ? null : name)}
                            batched={!batchFailed} injData={pageData[w.id]?.data} injError={pageData[w.id]?.error} />
                        </div>
                      )}
                    </div>
                  ))}
                </GridLayout>
              )}
              </div>

              {canManage && sources && (
                <div style={{ marginTop: 20 }}>
                  <h3 style={{ fontSize: 14, margin: '0 0 8px' }}>Добавить виджет</h3>
                  <SourceCatalog sources={sources} />
                  {sources.datasets.length > 0 && <SuggestPanel datasets={sources.datasets} onAdd={addWidgetsBatch} />}
                  <SuggestMetricsPanel dashboardId={sel.dashboard.id} />
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
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
              Смените тип, источник, датасет или поля — размещение на странице и пороги алертов сохранятся.
            </div>
            <WidgetForm sources={sources} initial={editWidget} submitLabel="Сохранить" onCreate={saveWidgetEdit} />
          </div>
        </div>
      )}
      {commentsOpen && sel && (
        <Comments dashboard={sel.dashboard} onClose={() => { setCommentsOpen(false); getDashboard(sel.dashboard.id).then(setSel).catch(() => {}) }} />
      )}
      {archiveOpen && sel && (
        <ArchiveDialog name={sel.dashboard.name} onClose={() => setArchiveOpen(false)} onSubmit={doArchive} />
      )}

      {accessOpen && sel && (
        <AccessEditor dashboard={sel.dashboard} onClose={() => setAccessOpen(false)} />
      )}
      {kiosk && sel && (
        <KioskView dashboardName={sel.dashboard.name} pages={sel.pages} onClose={() => setKiosk(false)} />
      )}
      {rebind && (
        <RebindModal rebind={rebind} setRebind={setRebind} onConfirm={confirmRebind} busy={busy} />
      )}
      {folderTarget && (
        <FolderMoveDialog target={folderTarget} objects={objects} onClose={() => setFolderTarget(null)}
          onMove={doMoveFolder} onClear={() => doMoveFolder(null)} />
      )}
    </div>
  )
}
