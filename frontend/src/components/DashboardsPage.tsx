import { useEffect, useRef, useState, type FormEvent } from 'react'
import ReportLayout, { REPORT_COLUMNS_WIDE } from './dashboards/ReportLayout'
import GridLayout, { type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import {
  createDashboard, createPage, createPreset, createWidget, deleteDashboard, deletePage, deletePreset, deleteWidget,
  DuplicateError, getDashboard,
  exportPageXlsx, fitPageLayout, getDataSources, getDescriptionDraft, setFeatured, getPageData, getTemplateBindings, instantiateTemplate, listDashboardVersions, listDashboards, listFolders, listObjects, listPageWidgets, listPresets,
  listDocuments, listTemplates, logClientExport, moveDashboardToFolder, publishDashboard, updateDashboard, updatePage, restoreDashboardVersion, saveAsTemplate, setDashboardFavorite, submitDashboardReview, cancelDashboardReview, unpublishDashboard, updateWidget,
  type Dashboard, type DashPage, type DashPreset, type DashTemplate, type DataSources, type Doc, type Folder, type Obj, type PageWidgetData, type Widget, type WidgetSpec,
} from '../api'
import { useContainerWidth } from '../lib/useWidth'
import { GAP as FLOW_GAP, flowItems } from '../lib/flowLayout'
import { WidgetCard } from './dashboards/WidgetCard'
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
import { DashboardHeader } from './dashboards/DashboardHeader'
import { MissingFieldsDialog } from './dashboards/MissingFieldsDialog'
import { TemplateCloneDialog } from './dashboards/TemplateCloneDialog'
import { RebindModal, type RebindState } from './dashboards/RebindModal'
import { SourceCatalog, SuggestMetricsPanel, SuggestPanel, WidgetForm } from './dashboards/WidgetForm'
import { crumb, dialog, editHint, errBox, linkDanger, muted, overlay, rmBtn } from './dashboards/shared'


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

/**
 * Снимок страницы для выгрузки PDF/PNG.
 *
 * 🔴 Три вещи, без которых выгрузка получалась негодной.
 *
 * **Пустые карточки — главное.** Сетка раскладывает виджеты CSS-трансформацией
 * (`transform: translate(x, y)`), а html2canvas рисует их содержимое по
 * ИСХОДНЫМ координатам — и оно срезается собственным `overflow: hidden`
 * карточки. В PDF заказчика из 29 виджетов отрисовался ровно один: тот, у
 * которого сдвиг почти нулевой. Поэтому в клоне переводим трансформацию в
 * обычные `left/top` — это то же самое, что делает сетка в режиме без
 * трансформаций, и клипинг исчезает.
 *
 * Заодно гасим анимации: `.w-appear` в клоне начинается заново, и в кадр может
 * попасть её первый кадр (`opacity: 0`).
 *
 * **Служебные элементы.** В снимок попадали кнопки правки («Двигать и менять
 * размер», «удалить страницу»), пресеты фильтров и ссылки действий у каждого
 * виджета. В отчёте, который несут руководителю, это мусор: нажать в PDF
 * ничего нельзя. Прячем всё, помеченное `data-export-hide`.
 */
async function snapshot(
  html2canvas: (el: HTMLElement, opts: Record<string, unknown>) => Promise<HTMLCanvasElement>,
  el: HTMLElement,
): Promise<HTMLCanvasElement> {
  return html2canvas(el, {
    scale: 2, backgroundColor: surfaceColor(), useCORS: true,
    onclone: (doc: Document) => {
      const st = doc.createElement('style')
      st.textContent = '*,*::before,*::after{animation:none!important;transition:none!important}'
      doc.head.appendChild(st)
      doc.querySelectorAll('.react-grid-item').forEach((n) => {
        const el = n as HTMLElement
        const m = (el.style.transform || '').match(/translate(?:3d)?\(\s*(-?[\d.]+)px\s*,\s*(-?[\d.]+)px/)
        if (!m) return
        el.style.transform = 'none'
        el.style.left = `${m[1]}px`
        el.style.top = `${m[2]}px`
      })
      // 🔴 Служебное убираем, НО НИКОГДА не трогаем контейнер, внутри которого
      // лежит сам снимаемый узел. Удалив предка, мы отсоединяем цель от
      // документа, а у отсоединённого элемента getComputedStyle отдаёт ПУСТЫЕ
      // строки — html2canvas падает на первом же свойстве (backgroundColor) с
      // «Error parsing CSS component value, unexpected EOF», и выгрузка не
      // получается вовсе. Ровно так и сломалось: вёрстка отчёта живёт за краем
      // экрана в контейнере, который был помечен data-export-hide.
      const root = doc.querySelector('[data-export-root]')
      doc.querySelectorAll('[data-export-hide]').forEach((n) => {
        if (root && n.contains(root)) return
        n.remove()
      })
      // Шапка есть только в выгрузке: на экране она была бы повтором того,
      // что и так написано в крошках над дашбордом.
      doc.querySelectorAll('[data-export-only]').forEach((n) => {
        (n as HTMLElement).style.display = 'block'
      })
    },
  })
}

// Быстрый выбор периода для фильтра страницы. Единицы те же, что в разделе
// «Отчёты» (7/30/90/год), плюс «прошлый месяц» — самый частый вопрос
// руководителя. Границы считаются от сегодняшнего дня, кроме прошлого месяца:
// у него границы календарные, иначе «прошлый месяц» означал бы «30 дней назад».
const iso = (d: Date): string => d.toISOString().slice(0, 10)
const daysBack = (n: number): [string, string] => {
  const to = new Date()
  const from = new Date()
  from.setDate(from.getDate() - n)
  return [iso(from), iso(to)]
}
const QUICK_PERIODS: { label: string; hint: string; range: () => [string, string] }[] = [
  { label: '7 дн.', hint: 'Последние 7 дней', range: () => daysBack(7) },
  { label: '30 дн.', hint: 'Последние 30 дней', range: () => daysBack(30) },
  { label: 'прошлый месяц', hint: 'Календарный прошлый месяц целиком', range: () => {
    const now = new Date()
    const first = new Date(now.getFullYear(), now.getMonth() - 1, 1)
    const last = new Date(now.getFullYear(), now.getMonth(), 0)
    return [iso(first), iso(last)]
  } },
  { label: '90 дн.', hint: 'Последние 90 дней', range: () => daysBack(90) },
  { label: 'год', hint: 'Последние 365 дней', range: () => daysBack(365) },
]

export default function DashboardsPage({ canManage, isAdmin, isSuperadmin, initialDashboardId, initialPageId, onOpenAppeals }: { canManage: boolean; isAdmin?: boolean; isSuperadmin?: boolean; initialDashboardId?: string | null; initialPageId?: string | null;
  /** Перейти в свои обращения после жалобы с виджета (п. 15). */
  onOpenAppeals?: () => void }) {
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
  // Третий уровень фильтра: конкретный отчёт из папки. Отвечает на вопрос
  // «какие дашборды построены на данных этого файла».
  const [filterDocs, setFilterDocs] = useState<Doc[]>([])
  const [docFilter, setDocFilter] = useState('')
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
  // Вёрстка отчёта рисуется ЗА ЭКРАНОМ на время выгрузки: снимок делается с
  // неё, а не с дашборда. На экране у карточек фиксированная высота, обрезанные
  // имена, прокрутка в таблицах и свёрнутая легенда — в PDF всё это означало бы
  // потерю данных.
  const reportRef = useRef<HTMLDivElement>(null)
  const [reporting, setReporting] = useState(false)
  // Широкий отчёт — только для PNG: это ОДНА картинка, её не листают, и
  // колонка в 1000px превращала её в ленту почти на 20 000 точек высотой.
  // PDF остаётся в одну колонку: там ширина задана листом А4.
  const [reportWide, setReportWide] = useState(false)
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
  const loadDashboards = (q: string, fav: boolean, fromD = dashFrom, toD = dashTo, folderF = folderFilter, docF = docFilter) => {
    const seq = ++dashSeq.current
    return listDashboards(q, fav, DASH_PAGE, 0, fromD, toD, folderF, docF)
      .then((p) => { if (seq === dashSeq.current) { setDashboards(p.items); setDashTotal(p.total) } }).catch(fail)
  }
  const refresh = () => loadDashboards(query, favOnly)
  async function loadMoreDash() {
    const seq = ++dashSeq.current
    try { const p = await listDashboards(query, favOnly, DASH_PAGE, dashboards.length, dashFrom, dashTo, folderFilter, docFilter); if (seq === dashSeq.current) { setDashboards((prev) => [...prev, ...p.items]); setDashTotal(p.total) } } catch (e) { fail(e) }
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
  useEffect(() => { const t = setTimeout(() => loadDashboards(query, favOnly), 250); return () => clearTimeout(t) }, [query, favOnly, dashFrom, dashTo, folderFilter, docFilter]) // eslint-disable-line react-hooks/exhaustive-deps
  // Папки фильтра зависят от выбранного объекта.
  useEffect(() => {
    if (!filterObjId) { setFilterFolders([]); return }
    listFolders(filterObjId).then(setFilterFolders).catch(() => setFilterFolders([]))
  }, [filterObjId])
  // Файлы выбранной папки — третий уровень фильтра. Сбрасываем выбранный
  // отчёт при смене папки: иначе список фильтровался бы по файлу из другой.
  useEffect(() => {
    setDocFilter('')
    if (!folderFilter || folderFilter === 'none') { setFilterDocs([]); return }
    listDocuments(folderFilter, 100, 0).then((r) => setFilterDocs(r.items)).catch(() => setFilterDocs([]))
  }, [folderFilter])
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
    // Страница передаётся вместе с дашбордом: из каталога «Главной» человек
    // нажимает на КОНКРЕТНУЮ страницу («Динамика»), и открывать вместо неё
    // первую — значит не выполнить то, что он попросил.
    if (initialDashboardId) openDashboard(initialDashboardId, initialPageId || undefined)
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

  async function openDashboard(id: string, pageId?: string) {
    setError(null); setPage(null); setWidgets([]); setPFrom(''); setPTo(''); setCrossRow(null)
    try {
      const d = await getDashboard(id)
      setSel(d)
      listPresets(id).then(setPresets).catch(() => setPresets([]))
      // Просили конкретную страницу — открываем её; если её уже нет (удалили),
      // не молчим об этом падением, а показываем первую.
      const target = (pageId && d.pages.find((p) => p.id === pageId)) || d.pages[0]
      if (target) openPage(target)
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

  /** Создание из шаблона с переспросом об одноимённом.
   *
   *  Три места создают дашборд из шаблона (простое создание, перепривязка
   *  кодов и перенос на другой объект), и переспрашивать должно каждое —
   *  иначе одно из них останется единственным, что молча плодит копии. */
  async function withDuplicateAsk<T>(run: (force: boolean) => Promise<T>): Promise<T | null> {
    try {
      return await run(false)
    } catch (e) {
      if (!(e instanceof DuplicateError)) throw e
      const again = await ask({
        title: 'Дашборд с таким названием уже есть',
        message: e.message,
        confirmLabel: 'Всё равно создать',
        busyLabel: 'Создание…',
        tone: 'accent',
      })
      return again ? await run(true) : null
    }
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
  /** Завести карточку соседней графы формы прямо из меню «куда дальше».
   *
   *  Карточка — тот же безопасный вид по умолчанию, что и у «недостающих
   *  показателей»: не зависит от числа периодов и читается на любой ширине.
   *  Размер берём не с потолка: те же 4×5, что ставит авто-сборка, — иначе
   *  добавленная вручную карточка выглядела бы чужой среди собранных. */
  async function addSiblingField(field: string, name: string, datasetCode: string) {
    if (!page) throw new Error('Страница не открыта')
    if (!datasetCode) throw new Error('Не удалось определить набор данных показателя')
    await addWidgetsBatch([{
      name, widget_type: 'kpi',
      config: { dataset_code: datasetCode, value_field: field },
      width: 4, height: 5,
    }])
  }

  async function addMissingFields(picked: { code: string; name: string; dataset_code: string }[]) {
    if (!sel || !page || !picked.length) return
    setAddingFields(true)
    try {
      await addWidgetsBatch(picked.map((f) => ({
        name: f.name, widget_type: 'kpi',
        config: { dataset_code: f.dataset_code, value_field: f.code },
        // 4×5 — тот же размер, что ставит авто-сборка. Было 3×3: на такой
        // карточке имя госформы обрезается до «Колич обращ за…», а число не
        // помещается вовсе (это чинили 16.08 кнопкой «↕ Подогнать размеры»).
        width: 4, height: 5,
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
        const r = await withDuplicateAsk((force) =>
          instantiateTemplate(tpl, name.trim(), {}, {}, {}, force))  // все коды на месте
        if (!r) return
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
      const r = await withDuplicateAsk((force) =>
        instantiateTemplate(rebind.templateId, rebind.name, rebind.datasetMap, rebind.metricMap, {}, force))
      if (!r) return
      setRebind(null); setTpl(''); await refresh(); openDashboard(r.dashboard_id)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }
  /** Ждём, пока вёрстка отчёта отрисуется (React + графики ECharts). */
  function afterPaint(ms = 600): Promise<void> {
    return new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, ms)))
  }

  async function exportPdf() {
    if (!sel || !page) return
    setExporting(true)
    setReporting(true)
    try {
      const [{ default: html2canvas }, { jsPDF }] = await Promise.all([import('html2canvas'), import('jspdf')])
      await afterPaint()
      const el = reportRef.current
      if (!el) return
      const canvas = await snapshot(html2canvas, el)
      // compress: true — иначе jsPDF кладёт в файл СЫРОЙ RGB: одна страница A4
      // при scale 2 весит 13 МБ. Со сжатием тот же снимок — сотни килобайт.
      const pdf = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4', compress: true })
      const pw = pdf.internal.pageSize.getWidth(), ph = pdf.internal.pageSize.getHeight()
      const M = 10
      const px = canvas.width / (pw - M * 2)          // пикселей снимка на мм
      const bodyH = Math.floor((ph - M * 2) * px)

      // Границы блоков отчёта: страница заканчивается МЕЖДУ блоками, поэтому
      // виджет не может оказаться разорванным между листами.
      const box = el.getBoundingClientRect()
      const k = canvas.width / box.width
      const blocks = Array.from(el.querySelectorAll('.report-block')).map((b) => {
        const r = (b as HTMLElement).getBoundingClientRect()
        return { top: (r.top - box.top) * k, bottom: (r.bottom - box.top) * k }
      })
      const cutAfter = (from: number): number => {
        const limit = from + bodyH
        if (limit >= canvas.height) return canvas.height
        let best = 0
        for (const b of blocks) if (b.bottom > from && b.bottom <= limit) best = Math.max(best, b.bottom)
        const crossing = blocks.some((b) => b.top < limit && b.bottom > limit)
        if (!crossing) return limit
        // Блок выше страницы целиком (большая таблица) — режем по линейке,
        // иначе разбивка зациклится.
        return best > from ? Math.ceil(best) + 4 : limit
      }

      const slices: { y: number; h: number }[] = []
      for (let y = 0; y < canvas.height;) {
        const end2 = cutAfter(y)
        slices.push({ y, h: end2 - y })
        y = end2
      }
      slices.forEach((sl, i) => {
        if (i) pdf.addPage()
        const c = document.createElement('canvas')
        c.width = canvas.width; c.height = sl.h
        c.getContext('2d')!.drawImage(canvas, 0, sl.y, canvas.width, sl.h, 0, 0, canvas.width, sl.h)
        pdf.addImage(c.toDataURL('image/png'), 'PNG', M, M, pw - M * 2, sl.h / px)
        // Только цифры: кириллицу встроенные шрифты jsPDF не умеют, а название
        // отчёта нарисовано браузером в шапке первой страницы.
        pdf.setFontSize(8.5); pdf.setTextColor(130)
        pdf.text(`${i + 1} / ${slices.length}`, pw - M, ph - 5, { align: 'right' })
        pdf.setTextColor(0)
      })
      pdf.save(`${sel.dashboard.name} — ${page.name}.pdf`)
      logClientExport('dashboard', sel.dashboard.id, 'pdf')
    } catch (e) { fail(e) } finally { setReporting(false); setExporting(false) }
  }

  async function exportPng() {
    if (!sel || !page) return
    setExporting(true)
    setReportWide(true)
    setReporting(true)
    try {
      const { default: html2canvas } = await import('html2canvas')
      await afterPaint()
      const el = reportRef.current
      if (!el) return
      const canvas = await snapshot(html2canvas, el)
      // Через blob, а не data-URL: отчёт на 29 виджетов даёт ссылку длиной
      // 5,6 млн знаков — вся картинка целиком лежит СТРОКОЙ в памяти вкладки,
      // и с ростом отчёта это упирается либо в память, либо в предел длины
      // ссылки у браузера. Blob отдаётся файлом, а ссылка на него — короткая.
      const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, 'image/png'))
      if (!blob) throw new Error('Не удалось собрать изображение для выгрузки')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `${sel.dashboard.name} — ${page.name}.png`; a.click()
      URL.revokeObjectURL(url)
      logClientExport('dashboard', sel.dashboard.id, 'png')
    } catch (e) { fail(e) } finally { setReporting(false); setReportWide(false); setExporting(false) }
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

  // Раскладка страницы: «поток» считает место и размер по типу виджета при
  // отрисовке, свободная сетка хранит их у виджета. Свойство страницы, а не
  // дашборда: на «Обзоре» уместен поток, а собранную вручную страницу-рассказ
  // человек мог разложить по-своему.
  const flowMode = page?.layout_mode === 'flow'

  async function toggleFlowMode() {
    if (!page) return
    const next = flowMode ? 'grid' : 'flow'
    if (next === 'grid') {
      // Переход «поток → сетка» без раскладки дал бы кучу виджетов в левом
      // верхнем углу: в потоке координаты не хранятся и остались прежними.
      // Раскладываем тем же кодом, что и кнопка «↕ Подогнать размеры».
      if (!await ask({
        title: 'Перейти на свободную сетку?',
        message: 'Виджеты получат размер по своему типу и будут разложены по сетке — дальше их можно двигать мышью. '
          + 'Состав страницы не изменится, ни один виджет не пропадёт.',
        confirmLabel: 'Перейти на сетку',
      })) return
    }
    setBusy(true)
    try {
      const upd = await updatePage(page.id, { layout_mode: next })
      if (next === 'grid') await fitPageLayout(page.id)
      setPage((p) => (p ? { ...p, layout_mode: upd.layout_mode } : p))
      setSel((cur) => (cur
        ? { ...cur, pages: cur.pages.map((x) => (x.id === page.id ? { ...x, layout_mode: upd.layout_mode } : x)) }
        : cur))
      setWidgets((await listPageWidgets(page.id)).widgets)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }

  /** Всё, что нужно карточке виджета: одинаково для обеих раскладок. */
  function cardProps(w: Widget) {
    return {
      w,
      data: pageData[w.id]?.data,
      error: pageData[w.id]?.error,
      alert: pageData[w.id]?.data?.alert,
      isCollapsed: collapsed.has(w.id),
      onToggleCollapse: toggleCollapse,
      highlighted: highlight === w.id,
      editMode, canManage, hasSources: Boolean(sources),
      onEdit: setEditWidget, onAlerts: setAlertWidget, onDelete: delWidget,
      tip: widgetTip(w),
      reloadKey,
      from: pFrom || undefined, to: pTo || undefined, row: crossRow || undefined,
      asOf: asOf || undefined,
      onPick: (name: string) => setCrossRow((cur) => (cur === name ? null : name)),
      batched: !batchFailed,
      onNavigate: navigateToWidget,
      onAddField: canManage ? addSiblingField : undefined,
      onOpenAppeals,
    }
  }

  return (
    <div>
      {/* Крошка списка. У ОТКРЫТОГО дашборда своя крошка внутри шапки
          (DashboardHeader) — две подряд были бы дублем. */}
      {!sel && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, marginBottom: 16 }}>
          <button style={crumb} onClick={() => { setSel(null); setPage(null) }}>Дашборды</button>
        </div>
      )}

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
          onOpenAppeals={onOpenAppeals}
          onPlanFactBuilt={(id) => { refresh(); openDashboard(id) }}
          query={query} setQuery={setQuery} favOnly={favOnly} setFavOnly={setFavOnly}
          dashFrom={dashFrom} setDashFrom={setDashFrom} dashTo={dashTo} setDashTo={setDashTo}
          filterObjId={filterObjId} setFilterObjId={setFilterObjId} filterFolders={filterFolders}
          folderFilter={folderFilter} setFolderFilter={setFolderFilter}
          filterDocs={filterDocs} docFilter={docFilter} setDocFilter={setDocFilter}
          selectedIds={selectedIds} setSelectedIds={setSelectedIds} toggleSelect={toggleSelect}
          onBulkMove={() => setFolderTarget({ ids: [...selectedIds], label: `дашбордов: ${selectedIds.size}` })}
          dashboards={dashboards} dashTotal={dashTotal} openDashboard={openDashboard}
          toggleFav={toggleFav} loadMoreDash={loadMoreDash}
        />
      )}

      {sel && (
        <div>
          <DashboardHeader
            dashboard={sel.dashboard} pages={sel.pages} page={page} onOpenPage={openPage}
            onBack={() => { setSel(null); setPage(null) }}
            canManage={canManage} isAdmin={isAdmin} isSuperadmin={isSuperadmin}
            editMode={editMode} setEditMode={setEditMode} flowMode={flowMode}
            asOf={asOf} quickPeriods={QUICK_PERIODS}
            pFrom={pFrom} pTo={pTo} setPFrom={setPFrom} setPTo={setPTo}
            crossRow={crossRow} setCrossRow={setCrossRow} catOptions={catOptions}
            missingCount={page ? (missingFields?.length || 0) : 0} onOpenMissing={() => setMissingOpen(true)}
            presets={presets} applyPreset={applyPreset} removePreset={removePreset} savePreset={() => setPresetName('')}
            newPage={newPage} setNewPage={setNewPage} addPage={addPage} busy={busy} exporting={exporting}
            a={{
              submitReview: doSubmitReview, cancelReview: doCancelReview, publish: doPublish, unpublish: doUnpublish,
              versions: loadVersions, access: () => setAccessOpen(true),
              moveFolder: () => setFolderTarget({
                ids: [sel.dashboard.id], label: sel.dashboard.name,
                currentPath: sel.dashboard.folder_name ? `${sel.dashboard.object_name}/${sel.dashboard.folder_name}` : null,
              }),
              saveTemplate: () => setTemplateName(sel.dashboard.name),
              archive: () => setArchiveOpen(true), toggleAutoArchive, toggleSuggestFields,
              del: doDeleteDashboard, comments: () => setCommentsOpen(true), kiosk: () => setKiosk(true),
              about: () => setAboutOpen(true),
              rename: () => setEditDash({ name: sel.dashboard.name, description: sel.dashboard.description || '' }),
              exportPdf, exportExcel, exportPng, fitLayout, toggleFlow: toggleFlowMode,
              deletePage: () => { if (page) delPage(page) },
              renamePage: () => { if (page) setRenamePageTarget(page) },
            }}
          />
          {/* Появился более свежий выпуск — предложение обновиться (сама дата
              данных живёт в строке контекста шапки). */}
          <FreshnessBar
            available={freshAvailable}
            asOf={asOf}
            onRefresh={() => {
              setAsOf(freshAvailable)
              setFreshAvailable(null)
              setReloadKey((k) => k + 1)
            }}
          />

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

          {!page ? (
            <div style={muted}>{sel.pages.length ? 'Выберите страницу.' : 'Создайте первую страницу дашборда.'}</div>
          ) : (
            <div ref={pageRef} style={{ background: 'var(--surface)' }}>
              {/* Вёрстка отчёта: живёт за левым краем экрана и только во время
                  выгрузки (position: fixed — на раскладку страницы не влияет).
                  Отдельный узел нужен потому, что отчёт устроен иначе, чем
                  дашборд: одна колонка, полные имена, развёрнутые таблицы. */}
              {reporting && (
                <div style={{ position: 'fixed', left: -20000, top: 0, zIndex: -1 }}>
                  <div ref={reportRef} data-export-root>
                    <ReportLayout
                      title={sel.dashboard.name} pageName={page.name}
                      objectName={sel.dashboard.object_name} folderName={sel.dashboard.folder_name}
                      widgets={widgets.map((w) => ({ id: w.id, name: w.name, widget_type: w.widget_type, config: w.config }))}
                      data={pageData} from={pFrom} to={pTo} row={crossRow} asOf={asOf}
                      columns={reportWide ? REPORT_COLUMNS_WIDE : 1} />
                  </div>
                </div>
              )}

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
              {widgets.length === 0 ? <div style={muted}>На странице пока нет виджетов.</div> : flowMode ? (
                /* «Поток»: место и размер считаются по типу виджета при
                   отрисовке (lib/flowLayout), двигать нечего — страница не
                   может поехать и не оставляет дыр. */
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(12, minmax(0, 1fr))', gap: FLOW_GAP }}>
                  {flowItems(widgets, gridWidth ?? 0, (id) => collapsed.has(id)).map((it) => {
                    const w = widgets.find((x) => x.id === it.id)!
                    return (
                      /* Карточка с авто-высотой не задаёт height: в ряду её
                         растянет соседний виджет (сетка выравнивает по высоте
                         ряда), а одна в ряду — обожмёт содержимое. */
                      <div key={it.id} style={{ gridColumn: `span ${it.span}`, minWidth: 0,
                        ...(it.auto ? { minHeight: 120 } : { height: it.height }) }}>
                        <WidgetCard {...cardProps(w)} />
                      </div>
                    )
                  })}
                </div>
              ) : gridWidth !== undefined && (
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
                    <div key={w.id}>
                      <WidgetCard {...cardProps(w)} />
                    </div>
                  ))}
                </GridLayout>
              )}
              </div>

              {canManage && sources && (
                <div data-export-hide style={{ marginTop: 20 }}>
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
              const r = await withDuplicateAsk((force) =>
                instantiateTemplate(cloneTpl.id, name, datasetMap, {}, fieldMap, force))
              if (!r) return
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
