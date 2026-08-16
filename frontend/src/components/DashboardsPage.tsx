import { useEffect, useRef, useState, type FormEvent } from 'react'
import GridLayout, { type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import {
  createDashboard, createPage, createPreset, createWidget, deleteDashboard, deletePage, deletePreset, deleteWidget,
  DuplicateError, getDashboard,
  exportPageXlsx, fitPageLayout, getDataSources, getDescriptionDraft, setFeatured, getPageData, getTemplateBindings, instantiateTemplate, listDashboardVersions, listDashboards, listFolders, listObjects, listPageWidgets, listPresets,
  listTemplates, logClientExport, moveDashboardToFolder, publishDashboard, updateDashboard, updatePage, restoreDashboardVersion, saveAsTemplate, setDashboardFavorite, submitDashboardReview, cancelDashboardReview, unpublishDashboard, updateWidget,
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
import AutoBuildWizard from './dashboards/AutoBuildWizard'
import { AboutDashboard, EditDashboardDialog } from './dashboards/AboutDashboard'
import { RenameDialog } from './dashboards/RenameDialog'
import { useConfirm } from './dashboards/ConfirmDialog'
import { dashboardFreshness, dashboardMissingFields } from '../api/dashboards'
import { FreshnessBar } from './dashboards/FreshnessBar'
import { MissingFieldsDialog } from './dashboards/MissingFieldsDialog'
import { TemplateCloneDialog } from './dashboards/TemplateCloneDialog'
import { RebindModal, type RebindState } from './dashboards/RebindModal'
import { SourceCatalog, SuggestMetricsPanel, SuggestPanel, WidgetForm } from './dashboards/WidgetForm'
import { PubBadge, WT, alertBtn, btn, btnGhost, crumb, dialog, editBtn, editHint, errBox, input, linkDanger, muted, overlay, presetChip, rmBtn, tab, tabActive, widgetCard, wtBadge } from './dashboards/shared'


const DASH_PAGE = 50

// Текст тултипа виджета. Порядок частей отвечает на вопросы в том порядке, в
// котором их задают: ЧТО это за цифра (пояснение с сервера — показатель,
// формула, состояние согласования), потом авторская заметка, и лишь потом —
// что за тип виджета. Раньше первым (и часто единственным) шёл тип, то есть
// подсказка объясняла то, что и так видно.
function widgetTip(w: { widget_type: string; config: Record<string, unknown>; explain?: string | null }): string {
  const typeHint = WIDGET_META[w.widget_type]?.hint || ''
  const help = typeof w.config?.help === 'string' ? (w.config.help as string).trim() : ''
  // Тип виджета дописываем, ТОЛЬКО когда сказать о самой цифре нечего:
  // рядом с «Графа «…» из формы «…»» хвост «Крупное значение метрики»
  // объясняет то, что и так видно.
  return [w.explain || typeHint, help].filter(Boolean).join(' ')
}

// html2canvas не понимает CSS-переменные в backgroundColor — резолвим токен
// текущей темы в реальный цвет (фон выгрузки PDF/PNG совпадает с темой).
function surfaceColor(): string {
  return getComputedStyle(document.documentElement).getPropertyValue('--surface').trim() || '#ffffff'
}

export default function DashboardsPage({ canManage, isAdmin, isSuperadmin, initialDashboardId }: { canManage: boolean; isAdmin?: boolean; isSuperadmin?: boolean; initialDashboardId?: string | null }) {
  // Подтверждения — своим окном: системное браузер вправе подавить, и кнопка
  // необратимого действия выглядит нерабочей (см. ConfirmDialog).
  const { ask, node: confirmNode } = useConfirm()
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
  // Свежесть данных под дашбордом. Цифры в виджетах обновляются сами, но
  // ОТКРЫТАЯ страница об этом не знает: руководитель с незакрытой вкладкой
  // смотрит на вчерашние числа и уверен, что они сегодняшние.
  const [asOf, setAsOf] = useState<string | null>(null)
  const [freshAvailable, setFreshAvailable] = useState<string | null>(null)
  const [missingFields, setMissingFields] = useState<{ code: string; name: string; dataset_code: string }[] | null>(null)
  const [missingOpen, setMissingOpen] = useState(false)
  // Тиражирование шаблона на другой объект (перепривязка показателей по именам).
  const [cloneTpl, setCloneTpl] = useState<{ id: string; name: string } | null>(null)
  const [addingFields, setAddingFields] = useState(false)

  const [newDash, setNewDash] = useState('')
  const [newPage, setNewPage] = useState('')
  const [busy, setBusy] = useState(false)
  const [pFrom, setPFrom] = useState('')
  const [pTo, setPTo] = useState('')
  const [crossRow, setCrossRow] = useState<string | null>(null)
  // Виджет, к которому только что перешли из меню «↗ куда дальше»: подсвечен
  // пару секунд, чтобы человек увидел, куда его привели.
  const [highlight, setHighlight] = useState<string | null>(null)
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
  const [wizardObj, setWizardObj] = useState<string | null>(null)
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
  // Правка самого дашборда (имя/описание) и карточка «о дашборде».
  const [editDash, setEditDash] = useState<{ name: string; description: string } | null>(null)
  const [renamePageTarget, setRenamePageTarget] = useState<DashPage | null>(null)
  const [templateName, setTemplateName] = useState<string | null>(null)
  const [presetName, setPresetName] = useState<string | null>(null)
  const [tplName, setTplName] = useState<string | null>(null)
  const [aboutOpen, setAboutOpen] = useState(false)
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
  /** Отметка «в подборку Руководителю»: состав подборки, а не доступ к дашборду
   *  (доступ по-прежнему выдаётся грантами — второй системы прав не заводим). */
  async function toggleFeatured(e: React.MouseEvent, d: Dashboard) {
    e.stopPropagation()
    try { await setFeatured(d.id, !d.featured); refresh() } catch (e) { fail(e) }
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
    // Источники и шаблоны нужны только конструктору: на /metrics/data-sources
    // обычный пользователь получает 403, и запрос уходил впустую при каждом
    // открытии раздела — лишний отказ в логах и в консоли браузера.
    // Список объектов оставляем всем: по нему работает фильтр «Папка».
    listObjects().then(setObjects).catch(() => {})
    if (canManage) {
      getDataSources().then(setSources).catch(() => setSources({ datasets: [], metrics: [] }))
      listTemplates().then(setTemplates).catch(() => {})
    }
    if (initialDashboardId) openDashboard(initialDashboardId)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Тихая проверка свежести раз в минуту. Данные не перезагружаем — только
  // сравниваем дату последнего выпуска и предлагаем обновиться: перезагружать
  // страницу под руками у человека нельзя, он мог что-то настраивать.
  useEffect(() => {
    const id = sel?.dashboard.id
    if (!id) { setAsOf(null); setFreshAvailable(null); return }
    let stop = false
    const check = async (first: boolean) => {
      try {
        const f = await dashboardFreshness(id)
        if (stop) return
        if (first) { setAsOf(f.as_of); setFreshAvailable(null) }
        else if (f.as_of && f.as_of !== asOf) setFreshAvailable(f.as_of)
      } catch { /* свежесть — подсказка, её сбой не мешает работе */ }
    }
    check(true)
    const t = setInterval(() => check(false), 60000)
    return () => { stop = true; clearInterval(t) }
  }, [sel?.dashboard.id, asOf])

  // Показатели, которых нет на дашборде: система подсказывает, но НЕ добавляет
  // виджеты сама — дашборд, который сам себе дорисовывает карточки, однажды
  // поедет вёрсткой прямо на совещании.
  useEffect(() => {
    if (!sel || !canManage || sel.dashboard.suggest_new_fields === false) { setMissingFields(null); return }
    dashboardMissingFields(sel.dashboard.id)
      .then((r) => setMissingFields(r.fields))
      .catch(() => setMissingFields(null))
  }, [sel?.dashboard.id, sel?.dashboard.suggest_new_fields, canManage]) // eslint-disable-line react-hooks/exhaustive-deps

  async function openDashboard(id: string) {
    setError(null); setPage(null); setWidgets([]); setPFrom(''); setPTo(''); setCrossRow(null)
    try {
      const d = await getDashboard(id)
      setSel(d)
      listPresets(id).then(setPresets).catch(() => setPresets([]))
      if (d.pages.length) openPage(d.pages[0])
    } catch (e) { fail(e) }
  }
  // Переход из меню «↗ куда дальше»: открыть дашборд и ту страницу, где лежит
  // связанный виджет. Если это текущий дашборд, дёргать его заново не нужно —
  // достаточно переключить страницу, иначе экран моргает и теряет фильтры.
  async function navigateToWidget(dashboardId: string, pageId: string | null, widgetId: string) {
    if (sel && sel.dashboard.id === dashboardId) {
      const target = pageId && sel.pages.find((p) => p.id === pageId)
      if (target && target.id !== page?.id) await openPage(target)
      revealWidget(widgetId)
      return
    }
    setError(null); setPage(null); setWidgets([]); setCrossRow(null)
    try {
      const d = await getDashboard(dashboardId)
      setSel(d)
      listPresets(dashboardId).then(setPresets).catch(() => setPresets([]))
      const target = (pageId && d.pages.find((p) => p.id === pageId)) || d.pages[0]
      if (target) await openPage(target)
      revealWidget(widgetId)
    } catch (e) { fail(e) }
  }

  /** Показать виджет, к которому перешли: прокрутить к нему и подсветить.
   *  Без этого переход к соседу на ТОЙ ЖЕ странице выглядит как «нажал —
   *  ничего не произошло»: страница уже открыта, меню просто закрылось. */
  function revealWidget(widgetId: string) {
    setHighlight(widgetId)
    // Ждём перерисовку сетки: сразу после смены страницы элемента ещё нет.
    setTimeout(() => {
      document.querySelector(`[data-widget-id="${widgetId}"]`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 120)
    setTimeout(() => setHighlight((cur) => (cur === widgetId ? null : cur)), 2600)
  }

  const reloadPresets = () => { if (sel) listPresets(sel.dashboard.id).then(setPresets).catch(() => {}) }
  function applyPreset(p: DashPreset) {
    setPFrom(p.filters.from || ''); setPTo(p.filters.to || ''); setCrossRow(p.filters.row || null)
  }
  async function savePreset(name: string) {
    if (!sel) return
    setPresetName(null); setError(null)
    try {
      await createPreset(sel.dashboard.id, name, { from: pFrom || undefined, to: pTo || undefined, row: crossRow || undefined })
      reloadPresets()
    } catch (e) { fail(e) }
  }
  async function removePreset(p: DashPreset) {
    if (!sel || !await ask({ title: `Удалить пресет «${p.name}»?`, message: 'Сохранённый набор фильтров будет удалён. Сами данные и виджеты не пострадают.' })) return
    try { await deletePreset(sel.dashboard.id, p.id); reloadPresets() } catch (e) { fail(e) }
  }
  async function openPage(p: DashPage) {
    // Список виджетов чистим ДО запроса. Иначе при сбое запроса на экране
    // оставались виджеты предыдущей страницы: выглядело так, будто на всех
    // вкладках одно и то же, а данные к ним не грузились.
    setError(null); setPage(p); setWidgets([])
    try { setWidgets((await listPageWidgets(p.id)).widgets) } catch (e) { fail(e) }
  }
  async function reloadPage() {
    if (page) { try { setWidgets((await listPageWidgets(page.id)).widgets) } catch (e) { fail(e) } }
  }

  async function addDashboard(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null)
    try {
      let d
      try {
        d = await createDashboard(newDash.trim())
      } catch (e) {
        // Одноимённый дашборд уже есть. Не запрещаем (копия «на следующий год»
        // законна), но переспрашиваем: два одинаковых названия в списке не
        // различить, и однажды руководитель откроет заброшенное.
        if (!(e instanceof DuplicateError)) throw e
        const again = await ask({
          title: 'Дашборд с таким названием уже есть',
          message: e.message,
          confirmLabel: 'Всё равно создать',
          busyLabel: 'Создание…',
          tone: 'accent',
        })
        if (!again) return
        d = await createDashboard(newDash.trim(), undefined, true)
      }
      setNewDash(''); await refresh(); openDashboard(d.id)
    }
    catch (e) { fail(e) } finally { setBusy(false) }
  }
  // «Собрать» открывает мастер, а не собирает сразу: раньше нажатие давало
  // непредсказуемый по объёму дашборд и каждый раз новый. Теперь состав виден
  // до создания, лишнее снимается галочками, и можно пересобрать существующий.
  function autoBuild() {
    if (!autoObj) return
    setError(null)
    setWizardObj(autoObj)
  }
  async function addPage(e: FormEvent) {
    e.preventDefault(); if (!sel) return; setBusy(true); setError(null)
    try {
      const p = await createPage(sel.dashboard.id, newPage.trim())
      setNewPage(''); const d = await getDashboard(sel.dashboard.id); setSel(d); openPage(p)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }
  async function savePageName(name: string) {
    if (!sel || !renamePageTarget) return
    setError(null)
    try {
      await updatePage(renamePageTarget.id, { name })
      const d = await getDashboard(sel.dashboard.id)
      setSel(d)
      // Вкладку перечитываем из ответа: иначе в заголовке осталось бы старое имя.
      const fresh = d.pages.find((x) => x.id === renamePageTarget.id)
      if (fresh) setPage(fresh)
      setRenamePageTarget(null)
    } catch (e) { fail(e) }
  }
  async function delPage(p: DashPage) {
    if (!sel || !await ask({
      title: `Удалить страницу «${p.name}»?`,
      message: 'Вместе со страницей удалятся все её виджеты. Действие необратимо.',
    })) return
    try { await deletePage(p.id); const d = await getDashboard(sel.dashboard.id); setSel(d); setPage(null); setWidgets([]) }
    catch (e) { fail(e) }
  }
  /** Подогнать размеры виджетов страницы под их тип (старые дашборды 3×3). */
  async function fitLayout() {
    if (!page || !await ask({
      title: 'Подогнать размеры виджетов?',
      message: 'Каждый виджет получит размер по своему типу, и они лягут по сетке заново: '
        + 'карточки крупнее (имя показателя перестанет обрезаться), графики и таблицы — во всю ширину. '
        + 'Состав страницы не изменится, ни один виджет не пропадёт. Расстановку потом можно поправить мышью.',
      confirmLabel: 'Подогнать', busyLabel: 'Подгоняем…', tone: 'accent',
    })) return
    setBusy(true); setError(null)
    try {
      await fitPageLayout(page.id)
      await reloadPage(); setReloadKey((k) => k + 1)
    } catch (e) { fail(e) } finally { setBusy(false) }
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
  async function saveDashboardEdit(patch: { name: string; description: string }) {
    if (!sel) return
    setError(null)
    try {
      await updateDashboard(sel.dashboard.id, {
        name: patch.name.trim(),
        description: patch.description.trim() || null,
      })
      setSel(await getDashboard(sel.dashboard.id))
      setEditDash(null)
      refresh() // имя изменилось — обновляем и список
    } catch (e) { fail(e) }
  }

  async function doDeleteDashboard() {
    if (!sel) return
    if (!await ask({
      title: `Удалить дашборд «${sel.dashboard.name}»?`,
      message: 'Вместе с ним удалятся его страницы, виджеты, права доступа и комментарии. '
        + 'Слепки в архиве сохранятся. Действие необратимо.',
    })) return
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
  /** Добавить выбранные показатели карточками на текущую страницу.
   *  Карточка — самый безопасный вид по умолчанию: она не зависит от числа
   *  периодов и читается на любой ширине. Вид и размер меняются потом. */
  async function addMissingFields(picked: { code: string; name: string; dataset_code: string }[]) {
    if (!sel || !page || !picked.length) return
    setAddingFields(true)
    try {
      await addWidgetsBatch(picked.map((f) => ({
        name: f.name, widget_type: 'kpi',
        config: { dataset_code: f.dataset_code, value_field: f.code },
        width: 3, height: 3,
      })))
      setMissingOpen(false)
      const left = await dashboardMissingFields(sel.dashboard.id)
      setMissingFields(left.fields)
    } catch (e) { fail(e) } finally { setAddingFields(false) }
  }

  async function toggleSuggestFields() {
    if (!sel) return
    try {
      await updateDashboard(sel.dashboard.id, { suggest_new_fields: false })
      setSel(await getDashboard(sel.dashboard.id))
      setMissingFields(null)
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
    if (!sel || !await ask({
      title: `Откатить к версии ${v}?`,
      message: 'Текущие страницы и виджеты будут заменены снимком этой версии. '
        + 'Сама текущая раскладка сохранится в истории как отдельная версия.',
      confirmLabel: 'Откатить', busyLabel: 'Откат…', tone: 'accent',
    })) return
    try {
      await restoreDashboardVersion(sel.dashboard.id, v)
      const d = await getDashboard(sel.dashboard.id); setSel(d); setVersions(null)
      if (d.pages.length) openPage(d.pages[0]); else { setPage(null); setWidgets([]) }
    } catch (e) { fail(e) }
  }
  async function saveTemplate(name: string) {
    if (!sel) return
    setError(null)
    try {
      await saveAsTemplate(sel.dashboard.id, name)
      setTemplates(await listTemplates())
      setTemplateName(null)
    } catch (e) { fail(e) }
  }
  async function createFromTemplate(name: string) {
    if (!tpl) return
    setTplName(null)
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
        {sel && (
          <>
            <span style={{ color: 'var(--text-faint)' }}>/</span>
            <span>{sel.dashboard.name}</span>
            {canManage && (
              <button style={{ ...editBtn, cursor: 'pointer' }} title="Переименовать дашборд, изменить описание"
                onClick={() => setEditDash({ name: sel.dashboard.name, description: sel.dashboard.description || '' })}>✎</button>
            )}
            <button style={{ ...editBtn, cursor: 'pointer' }} title="Что это за дашборд и из чего он собран"
              onClick={() => setAboutOpen(true)}>ℹ</button>
          </>
        )}
      </div>

      {error && <div style={errBox}>{error}</div>}

      {!sel && (
        <DashboardList
          canManage={canManage} objects={objects} templates={templates}
          newDash={newDash} setNewDash={setNewDash} addDashboard={addDashboard} busy={busy}
          autoObj={autoObj} setAutoObj={setAutoObj} autoBuild={autoBuild}
          tpl={tpl} setTpl={setTpl} createFromTemplate={() => {
            const t = templates.find((x) => x.id === tpl)
            setTplName(t ? `${t.name} (копия)` : 'Новый дашборд')
          }}
          cloneTemplate={() => {
            const t = templates.find((x) => x.id === tpl)
            if (t) setCloneTpl({ id: t.id, name: t.name })
          }}
          onToggleFeatured={toggleFeatured}
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
            {canManage && <button style={btnGhost} onClick={() => setTemplateName(sel.dashboard.name)}>Сохранить как шаблон</button>}
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
            {isSuperadmin && (
              <button style={{ ...btnGhost, marginLeft: 'auto', borderColor: 'var(--danger)', color: 'var(--danger)' }}
                onClick={doDeleteDashboard}
                title="Удалить дашборд со страницами и виджетами (слепки в архиве сохранятся). Доступно только суперадминистратору">
                🗑 Удалить
              </button>
            )}
          </div>
          <FreshnessBar
            asOf={asOf} available={freshAvailable}
            onRefresh={() => {
              setAsOf(freshAvailable)
              setFreshAvailable(null)
              setReloadKey((k) => k + 1)
            }}
          />

          {canManage && missingFields && missingFields.length > 0 && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
              background: 'var(--surface-2)', fontSize: 13, padding: '8px 12px',
              borderRadius: 8, margin: '0 0 12px', color: 'var(--text-2)',
            }}>
              <span>
                💡 В данных есть показатели, которых нет на дашборде ({missingFields.length}):{' '}
                {missingFields.slice(0, 3).map((f) => `«${f.name}»`).join(', ')}
                {missingFields.length > 3 ? ' и другие' : ''}.
              </span>
              <button type="button" style={{ ...btn, height: 28, fontSize: 12.5, marginLeft: 'auto' }}
                disabled={!page}
                title={page
                  ? 'Выбрать показатели и добавить их карточками на эту страницу'
                  : 'Сначала откройте страницу дашборда'}
                onClick={() => setMissingOpen(true)}>Добавить на дашборд</button>
              <button type="button" style={{ ...btnGhost, height: 28, fontSize: 12.5 }}
                title="Отключить подсказку для этого дашборда"
                onClick={toggleSuggestFields}>Больше не подсказывать</button>
            </div>
          )}

          {missingOpen && missingFields && (
            <MissingFieldsDialog
              fields={missingFields}
              busy={addingFields}
              onClose={() => setMissingOpen(false)}
              onAdd={addMissingFields}
            />
          )}

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
                  <button style={{ ...editBtn, cursor: 'pointer' }} title="Переименовать страницу"
                    onClick={() => setRenamePageTarget(page)}>✎</button>
                )}
                {canManage && (
                  <button style={{ ...tab, height: 30, ...(editMode ? tabActive : {}) }}
                    title={editMode
                      ? 'Выйти из режима правки раскладки'
                      : 'Включить перетаскивание виджетов и изменение их размера'}
                    onClick={() => setEditMode((v) => !v)}>
                    {editMode ? '✓ Готово' : '✎ Двигать и менять размер'}
                  </button>
                )}
                {/* Дашборды, собранные до перехода авто-сборки на крупные
                    карточки, держат виджеты 3×3: имя обрезается до
                    «Колич обращ за…», число не помещается. Растягивать их
                    мышью по одному — полчаса работы. */}
                {canManage && editMode && (
                  <button style={{ ...tab, height: 30 }} disabled={busy}
                    title="Поставить каждому виджету размер по его типу и разложить по сетке. Состав страницы не изменится"
                    onClick={fitLayout}>↕ Подогнать размеры</button>
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
                {canManage && <button style={{ ...tab, height: 28 }} onClick={() => setPresetName('')}>💾 Сохранить текущие</button>}
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
              {/* draggableCancel: кнопки шапки лежат ВНУТРИ ручки перетаскивания,
                  и без этого исключения клик по ним срывался — стоило мыши
                  сместиться на пару пикселей между нажатием и отпусканием, как
                  react-grid-layout начинал тащить виджет, а события click не
                  возникало вовсе. Кнопка при этом получала фокус и выглядела
                  сломанной (жалоба на ⚠ «нажимаю — ничего не происходит»). */}
              {widgets.length === 0 ? <div style={muted}>На странице пока нет виджетов.</div> : gridWidth !== undefined && (
                <GridLayout className="layout" width={gridWidth} cols={12} rowHeight={40} margin={[12, 12]}
                  isDraggable={canManage && editMode} isResizable={canManage && editMode}
                  draggableHandle=".wdrag" draggableCancel=".wnodrag" compactType="vertical"
                  onDragStop={(_l, _o, n) => persistItem(n)} onResizeStop={(_l, _o, n) => persistItem(n)}
                  layout={widgets.map((w) => ({
                    i: w.id, x: w.position_x || 0, y: w.position_y || 0, w: w.width || 4,
                    h: collapsed.has(w.id) ? 1 : (w.height || 4),
                    isDraggable: canManage && editMode && !collapsed.has(w.id),
                    isResizable: canManage && editMode && !collapsed.has(w.id),
                  }))}>
                  {/* Карточка — колонка: шапка занимает сколько нужно, тело
                      забирает остаток. Раньше высота тела считалась вычитанием
                      «магических» 78px, и при любой правке шапки число KPI
                      снова начинало обрезаться. */}
                  {widgets.map((w) => (
                    <div key={w.id} data-widget-id={w.id} style={{ ...widgetCard, height: '100%', overflow: 'hidden',
                      display: 'flex', flexDirection: 'column',
                      // Подсветка цели перехода из меню «↗ куда дальше»: гаснет
                      // сама через пару секунд, чтобы не остаться навсегда.
                      ...(highlight === w.id
                        ? { boxShadow: '0 0 0 3px var(--accent)', transition: 'box-shadow .2s' }
                        : { transition: 'box-shadow .4s' }),
                      // Состояние показателя — лентой по ВСЕЙ карточке, вместе с
                      // именем: раньше красилось только тело под шапкой, и на
                      // странице из полутора десятков карточек «где плохо»
                      // приходилось искать глазами по цифрам.
                      ...(pageData[w.id]?.data?.alert
                        ? { borderLeft: `4px solid ${pageData[w.id]!.data!.alert.color}`,
                            background: pageData[w.id]!.data!.alert.bg }
                        : {}),
                      outline: editMode ? '1px dashed var(--text-faint)' : 'none' }}>
                      {/* Шапка в два ряда: сверху ИМЯ (оно главное — виджет без
                          названия ничего не сообщает), снизу значок типа и
                          действия. Когда всё было одной строкой, на узкой
                          карточке значок типа и четыре кнопки съедали её
                          целиком, а имя сжималось до нулевой ширины и
                          пропадало. У СВЁРНУТОГО виджета высота всего 40px —
                          там оставляем только ▸ и имя, иначе не поместится
                          даже кнопка разворачивания. */}
                      <div className={editMode ? 'wdrag' : ''} style={{ marginBottom: 4, flexShrink: 0, cursor: editMode ? 'move' : 'default' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'nowrap' }}>
                          <button className="wnodrag" style={{ ...editBtn, cursor: 'pointer', flexShrink: 0 }} onClick={() => toggleCollapse(w.id)}
                            title={collapsed.has(w.id) ? 'Развернуть виджет' : 'Свернуть виджет'}>{collapsed.has(w.id) ? '▸' : '▾'}</button>
                          {/* У развёрнутого виджета имя занимает до ДВУХ строк: имена
                              из авто-сборки длинные («… · Факт · нарастающим итогом»),
                              и в одну строку на карточке видно только «Внедре…» —
                              руководитель не понимает, что за число перед ним.
                              У свёрнутого (высота 40px) вторая строка не помещается. */}
                          {/* Обрезает ЛИБО стиль (по строкам), ЛИБО elideMiddle —
                              вместе они давали двойное многоточие («обращений……»).
                              У развёрнутого виджета обрезаем стилем: три строки на
                              карточке шириной в треть ряда вмещают осмысленный
                              кусок имени, а полное имя — в подсказке. */}
                          {/* Имя занимает ВСЮ ширину строки: на карточке в треть
                              ряда каждый соседний элемент отъедает у него столько,
                              что остаётся «Колич обр…» — проверено, значок ⓘ рядом
                              с именем именно к этому и приводил. Значок живёт
                              отдельной строкой ниже. */}
                          <div style={{
                            fontSize: 13, fontWeight: 600, flex: 1, minWidth: 0, overflow: 'hidden',
                            ...(collapsed.has(w.id)
                              ? { textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
                              : { display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', lineHeight: 1.2 }),
                          }}
                            title={w.name}>{collapsed.has(w.id) ? elideMiddle(w.name, 70) : w.name}</div>
                          {/* ⓘ — в строке с именем, а не отдельным рядом: свой ряд
                              стоил 21px, и на карточке в три ряда (144px) их не
                              хватало под само число. По ширине значок отнимает у
                              имени ~20px из 200 — три строки остаются читаемыми
                              (проверено: до двух строк ужимать нельзя, тогда от
                              имени остаётся «Колич обр…»). */}
                          {!collapsed.has(w.id) && !editMode && (
                            <span style={{ flexShrink: 0, alignSelf: 'flex-start' }}><InfoTip text={widgetTip(w)} /></span>
                          )}
                        </div>
                        {/* Служебный ряд (тип виджета, правка, пороги, удаление)
                            показываем ТОЛЬКО в режиме правки. В обычном просмотре
                            он съедал треть маленькой карточки — из-за него у KPI
                            обрезалось само число, ради которого карточка и стоит.
                            Значок ⓘ остаётся всегда: он объясняет, что за цифра.
                            У зрителя режима правки нет, поэтому раньше ряд висел
                            у него ПОСТОЯННО: бейдж типа занимал строку, и места
                            под число оставалось меньше, чем у администратора —
                            хотя именно зритель смотрит на цифру, а не правит. */}
                        {!collapsed.has(w.id) && editMode && (
                          <div className="wnodrag" style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
                            <span style={wtBadge}>{WT.find((x) => x.v === w.widget_type)?.t || w.widget_type}</span>
                            <InfoTip text={widgetTip(w)} />
                            <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                              {canManage && sources && <button style={editBtn} onClick={() => setEditWidget(w)} title="Изменить данные/тип виджета">✎</button>}
                              {canManage && ['kpi', 'gauge', 'plan_fact', 'dynamics'].includes(w.widget_type) && (
                                <button style={alertBtn} onClick={() => setAlertWidget(w)}
                                  title="Пороги KPI-алерта (условное форматирование)">⚠</button>
                              )}
                              {canManage && <button style={rmBtn} onClick={() => delWidget(w)} title="Удалить">✕</button>}
                            </span>
                          </div>
                        )}
                      </div>
                      {!collapsed.has(w.id) && (
                        <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflow: 'auto' }}>
                          <WidgetView widgetId={w.id} reloadKey={reloadKey} from={pFrom || undefined} to={pTo || undefined} row={crossRow || undefined}
                            pageAsOf={asOf || undefined}
                            onPick={(name) => setCrossRow((cur) => cur === name ? null : name)}
                            batched={!batchFailed} injData={pageData[w.id]?.data} injError={pageData[w.id]?.error}
                            onNavigate={navigateToWidget}
                            stripe={false} />
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
      {confirmNode}
      {cloneTpl && (
        <TemplateCloneDialog
          templateId={cloneTpl.id} templateName={cloneTpl.name} objects={objects} busy={busy}
          onClose={() => setCloneTpl(null)}
          onCreate={async ({ name, datasetMap, fieldMap }) => {
            setBusy(true); setError(null)
            try {
              const r = await instantiateTemplate(cloneTpl.id, name, datasetMap, {}, fieldMap)
              setCloneTpl(null); setTpl(''); await refresh(); openDashboard(r.dashboard_id)
            } catch (e) { fail(e) } finally { setBusy(false) }
          }}
        />
      )}
      {renamePageTarget && (
        <RenameDialog
          title="Переименовать страницу" label="Название страницы"
          initial={renamePageTarget.name} placeholder="Например: Обзор, По неделям, По субъектам"
          onClose={() => setRenamePageTarget(null)} onSave={savePageName} />
      )}
      {presetName !== null && (
        <RenameDialog
          title="Сохранить набор фильтров" label="Название набора"
          initial={presetName} placeholder="Например: Июль, только Донецк"
          onClose={() => setPresetName(null)} onSave={savePreset} />
      )}
      {tplName !== null && (
        <RenameDialog
          title="Создать дашборд из шаблона" label="Название нового дашборда"
          initial={tplName} onClose={() => setTplName(null)} onSave={createFromTemplate} />
      )}
      {templateName !== null && (
        <RenameDialog
          title="Сохранить как шаблон" label="Название шаблона"
          initial={templateName} onClose={() => setTemplateName(null)} onSave={saveTemplate} />
      )}
      {editDash && sel && (
        <EditDashboardDialog initial={editDash} onClose={() => setEditDash(null)} onSave={saveDashboardEdit}
          // Черновик описания система собирает по составу дашборда, но НЕ
          // сохраняет молча: описание — обещание читателю, отвечает за него
          // человек. Кнопка просто подставляет текст в поле.
          loadDraft={() => getDescriptionDraft(sel.dashboard.id).then((r) => r.draft)} />
      )}
      {aboutOpen && sel && (
        <AboutDashboard dashboard={sel.dashboard} pages={sel.pages} widgets={widgets}
          currentPage={page} onClose={() => setAboutOpen(false)} />
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
      {wizardObj && (
        <AutoBuildWizard
          objectId={wizardObj}
          objectName={objects.find((o) => o.id === wizardObj)?.name || 'объект'}
          dashboards={dashboards}
          onClose={() => setWizardObj(null)}
          onError={(m) => setError(m)}
          onDone={async (id) => { setWizardObj(null); setAutoObj(''); await refresh(); openDashboard(id) }}
        />
      )}
      {folderTarget && (
        <FolderMoveDialog target={folderTarget} objects={objects} onClose={() => setFolderTarget(null)}
          onMove={doMoveFolder} onClear={() => doMoveFolder(null)} />
      )}
    </div>
  )
}
