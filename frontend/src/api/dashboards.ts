import { authH, DuplicateError, errText, type Page } from './http'

// --- Дашборды / страницы / виджеты ---

export interface Dashboard {
  id: string
  name: string
  description: string | null
  publication_status: string
  auto_archive?: boolean
  /** Подсказывать ли о показателях, которых нет на дашборде. */
  suggest_new_fields?: boolean
  created_at: string
  updated_at?: string
  pages?: number
  comments_count?: number
  is_favorite?: boolean
  /** Входит в подборку «Руководителю» (состав подборки, не доступ к дашборду). */
  featured?: boolean
  folder_id?: string | null
  folder_name?: string | null
  object_name?: string | null
  /** При фильтре по файлу: собран ИМЕННО по этому отчёту (виджеты закреплены
   *  за его датой), а не просто читает эту форму. */
  pinned_to_document?: boolean
}
export async function setDashboardFavorite(id: string, on: boolean): Promise<void> {
  const res = await fetch(`/dashboards/${id}/favorite`, { method: on ? 'POST' : 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
export interface DashPage { id: string; name: string; description: string | null; position: number }
export interface Widget {
  id: string
  name: string
  widget_type: string
  position_x: number
  position_y: number
  width: number
  height: number
  config: Record<string, unknown>
  /** «Что это за цифра»: показатель, формула, состояние согласования — для ⓘ.
   *  Считается на сервере пачкой на всю страницу. */
  explain?: string | null
}

export async function listDashboards(
  q = '', fav = false, limit = 50, offset = 0, fromDate = '', toDate = '', folderId = '',
  documentId = '',
): Promise<Page<Dashboard>> {
  const p = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (q.trim()) p.set('q', q.trim())
  if (fav) p.set('fav', 'true')
  if (fromDate) p.set('from_date', fromDate)
  if (toDate) p.set('to_date', toDate)
  if (folderId) p.set('folder_id', folderId)
  // «Какие дашборды построены на данных этого отчёта».
  if (documentId) p.set('document_id', documentId)
  const res = await fetch(`/dashboards?${p}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
// Переместить дашборд в папку («банк отделов», волна D); null — убрать из папки.
export async function moveDashboardToFolder(id: string, folderId: string | null): Promise<{ folder_id: string | null }> {
  const res = await fetch(`/dashboards/${id}/folder`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ folder_id: folderId }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
// force=true — «всё равно создать»: дашборд с таким названием уже есть, и
// сервер отказал 409-м, чтобы в списке не появились два неразличимых.
export async function createDashboard(name: string, description?: string, force = false): Promise<Dashboard> {
  const res = await fetch('/dashboards', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ name, description: description || null, force }),
  })
  if (!res.ok) {
    const msg = await errText(res)
    throw res.status === 409 ? new DuplicateError(msg) : new Error(msg)
  }
  return res.json()
}
/** Что взять из одного набора данных. Пусто = всё. */
export type DatasetPick = {
  fields?: string[]
  blocks?: string[]
  /** Вид конкретного показателя: kpi | dynamics | both | none. */
  views?: Record<string, string>
  /** Отчётные даты, для которых нужны отдельные страницы-срезы. */
  periods?: string[]
}

export type AutoPlanDataset = {
  code: string
  name: string
  periods: number
  releases: number
  fields: { code: string; name: string }[]
  /** Отчётные даты, доступные для страниц-срезов (свежие сверху). */
  period_dates?: string[]
}

/** Расчётный показатель, который можно завести прямо в мастере. */
export type AutoMetricOption = {
  code: string
  name: string
  formula: string
  unit?: string | null
  why?: string | null
  preview_value?: number | null
  dataset_code?: string
  /** Вид предложения: у «plan_fact_pct» норма известна — ему ставятся пороги. */
  type?: string | null
}

export type AutoPlan = {
  object: { id: string; name: string }
  /** Что можно посчитать по данным: проценты выполнения, доли, приросты. */
  metrics?: AutoMetricOption[]
  /** Выбор прошлой сборки — им мастер открывается в следующий раз. */
  saved_selection?: {
    selection?: Record<string, DatasetPick>; metrics?: string[]; alerts?: boolean
  } | null
  datasets: AutoPlanDataset[]
  blocks: string[]
  warnings: string[]
  widgets: number
  pages: { name: string; widgets: number }[]
  by_type: Record<string, number>
  /** Как система предлагает показать каждый показатель: {код набора: {код поля: вид}}. */
  views: Record<string, Record<string, string>>
}

/** Предпросмотр мастера: что будет создано при таком выборе. Считается тем же
 *  планировщиком, что и сама сборка, — цифра не может разойтись с результатом. */
export async function autoBuildPlan(
  objectId: string, selection?: Record<string, DatasetPick>,
  documentId?: string, lockPeriod = true,
): Promise<AutoPlan> {
  const res = await fetch('/dashboards/auto/plan', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({
      object_id: objectId, selection: selection || null,
      // Сборка по конкретному отчёту: показатели берутся из его выпуска, а
      // виджеты закрепляются за его отчётной датой (если не снять галочку).
      document_id: documentId || null, lock_period: lockPeriod,
    }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function autoBuildDashboard(
  objectId: string,
  opts: {
    name?: string; selection?: Record<string, DatasetPick>; dashboardId?: string
    /** Коды расчётных показателей: заводятся черновиками, по каждому — карточка. */
    metrics?: string[]
    /** Пороги невыполнения плана: полоса и спидометр краснеют ниже нормы. */
    alerts?: boolean
    /** Собрать по КОНКРЕТНОМУ файлу (объект → папка → файл). */
    documentId?: string
    /** Закрепить виджеты за отчётной датой файла (по умолчанию да). */
    lockPeriod?: boolean
  } = {},
): Promise<{ dashboard_id: string; page_id: string; widgets: number; metrics?: number }> {
  const res = await fetch('/dashboards/auto', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({
      object_id: objectId, name: opts.name || null,
      selection: opts.selection || null, dashboard_id: opts.dashboardId || null,
      metrics: opts.metrics && opts.metrics.length ? opts.metrics : null,
      alerts: opts.alerts !== false,
      document_id: opts.documentId || null,
      lock_period: opts.lockPeriod !== false,
    }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function getDashboard(id: string): Promise<{ dashboard: Dashboard; pages: DashPage[] }> {
  const res = await fetch(`/dashboards/${id}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function createPage(dashboardId: string, name: string, description?: string): Promise<DashPage> {
  const res = await fetch(`/dashboards/${dashboardId}/pages`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ name, description: description || null }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export interface DashTemplate { id: string; name: string; description: string | null; created_at: string }
export async function listTemplates(): Promise<DashTemplate[]> {
  const res = await fetch('/dashboard-templates', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function saveAsTemplate(dashboardId: string, name: string, description?: string): Promise<{ id: string; name: string }> {
  const res = await fetch(`/dashboards/${dashboardId}/save-template`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ name, description: description || null }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export interface TemplateBindings { datasets: string[]; metrics: string[] }
export async function getTemplateBindings(templateId: string): Promise<TemplateBindings> {
  const res = await fetch(`/dashboard-templates/${templateId}/bindings`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function instantiateTemplate(templateId: string, name: string,
  datasetMap: Record<string, string> = {}, metricMap: Record<string, string> = {},
  /** Перепривязка ПОЛЕЙ: у другого объекта коды показателей свои. */
  fieldMap: Record<string, string> = {}): Promise<{ dashboard_id: string }> {
  const res = await fetch(`/dashboard-templates/${templateId}/instantiate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ name, dataset_map: datasetMap, metric_map: metricMap, field_map: fieldMap }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function publishDashboard(id: string): Promise<{ publication_status: string; version_no: number }> {
  const res = await fetch(`/dashboards/${id}/publish`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function unpublishDashboard(id: string): Promise<void> {
  const res = await fetch(`/dashboards/${id}/unpublish`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
/** Переименование страницы дашборда (вкладки). */
export async function updatePage(pageId: string, patch: { name?: string; description?: string }): Promise<DashPage> {
  const res = await fetch(`/dashboard-pages/${pageId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

/** Правка дашборда: название и/или описание (передаём только изменяемое). */
export async function updateDashboard(
  id: string, patch: { name?: string; description?: string | null; suggest_new_fields?: boolean },
): Promise<{ id: string; name: string; description: string | null }> {
  const res = await fetch(`/dashboards/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function deleteDashboard(id: string): Promise<void> {
  const res = await fetch(`/dashboards/${id}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
export async function listDashboardVersions(id: string): Promise<{ version_no: number; status_code: string; created_at: string }[]> {
  const res = await fetch(`/dashboards/${id}/versions`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function restoreDashboardVersion(id: string, versionNo: number): Promise<void> {
  const res = await fetch(`/dashboards/${id}/versions/${versionNo}/restore`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
export async function deletePage(pageId: string): Promise<void> {
  const res = await fetch(`/dashboard-pages/${pageId}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}


// --- Доступ к дашборду (RLS через ACL) ---
export interface DashGrant { id: string; scope: 'dashboard' | 'widget'; grantee_type: 'role' | 'user'; role_id: string | null; user_id: string | null; widget_id: string | null; widget_name: string | null; label: string; granted_at: string }
export interface GrantTargets { users: { id: string; login: string; full_name: string | null }[]; roles: { id: string; code: string; name: string }[] }
export interface GrantWidget { id: string; name: string; widget_type: string; page_title: string }
export async function listDashboardGrants(dashboardId: string): Promise<{ grants: DashGrant[]; targets: GrantTargets; widgets: GrantWidget[] }> {
  const res = await fetch(`/dashboards/${dashboardId}/grants`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function addDashboardGrant(dashboardId: string, body: { grantee_type: 'role' | 'user'; role_id?: string; user_id?: string; scope?: 'dashboard' | 'widget'; widget_id?: string }): Promise<{ id: string }> {
  const res = await fetch(`/dashboards/${dashboardId}/grants`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function removeDashboardGrant(dashboardId: string, grantId: string): Promise<void> {
  const res = await fetch(`/dashboards/${dashboardId}/grants/${grantId}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

// --- Обсуждение дашборда (комментарии) ---
export interface DashComment { id: string; body: string; created_at: string; author_id: string | null; author: string; can_delete: boolean }
export async function listComments(dashboardId: string, limit = 50, offset = 0): Promise<Page<DashComment>> {
  const p = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  const res = await fetch(`/dashboards/${dashboardId}/comments?${p}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function addComment(dashboardId: string, body: string): Promise<{ id: string }> {
  const res = await fetch(`/dashboards/${dashboardId}/comments`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify({ body }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function deleteComment(dashboardId: string, commentId: string): Promise<void> {
  const res = await fetch(`/dashboards/${dashboardId}/comments/${commentId}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

// --- Пресеты фильтров дашборда (FR-13) ---
export interface DashFilters { from?: string; to?: string; row?: string }
export interface DashPreset { id: string; name: string; filters: DashFilters }
export async function listPresets(dashboardId: string): Promise<DashPreset[]> {
  const res = await fetch(`/dashboards/${dashboardId}/presets`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function createPreset(dashboardId: string, name: string, filters: DashFilters): Promise<DashPreset> {
  const res = await fetch(`/dashboards/${dashboardId}/presets`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify({ name, filters }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function deletePreset(dashboardId: string, presetId: string): Promise<void> {
  const res = await fetch(`/dashboards/${dashboardId}/presets/${presetId}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
export interface WidgetSpec { name: string; widget_type: string; config: Record<string, unknown>; width: number; height: number }
export interface WidgetSuggestions { specs: WidgetSpec[]; total_candidates: number; already_built: number }
export async function widgetSuggestions(datasetCode: string): Promise<WidgetSuggestions> {
  const res = await fetch(`/widgets/suggestions?dataset_code=${encodeURIComponent(datasetCode)}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function previewWidget(body: { widget_type: string; name?: string; config: Record<string, unknown> }): Promise<any> {
  const res = await fetch('/widgets/preview', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function exportPageXlsx(pageId: string): Promise<Blob> {
  const res = await fetch(`/dashboard-pages/${pageId}/export.xlsx`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.blob()
}
export async function listPageWidgets(pageId: string): Promise<{ page_id: string; widgets: Widget[] }> {
  const res = await fetch(`/dashboard-pages/${pageId}/widgets`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
// Данные всех виджетов страницы за 1 запрос (перф). Учитывает фильтры страницы.
export interface PageWidgetData { id: string; data?: any; error?: string } // eslint-disable-line @typescript-eslint/no-explicit-any
export async function getPageData(pageId: string, from?: string, to?: string, row?: string): Promise<{ page_id: string; widgets: PageWidgetData[] }> {
  const p = new URLSearchParams()
  if (from) p.set('from', from)
  if (to) p.set('to', to)
  if (row) p.set('row', row)
  const qs = p.toString()
  const res = await fetch(`/dashboard-pages/${pageId}/data${qs ? '?' + qs : ''}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
/** Дашборд в подборке «Руководителю». Доступ определяют обычные гранты —
 *  здесь только состав подборки и то, что нужно, чтобы её прочитать. */
export type FeaturedDashboard = {
  id: string
  name: string
  description: string | null
  publication_status: string
  updated_at: string
  folder_name: string | null
  object_name: string | null
  pages: number
  /** Главные цифры отчёта — прямо на плитке подборки, чтобы «как дела» было
   *  видно без открывания каждого дашборда. Считаются тем же кодом, что рисует
   *  сами виджеты. */
  highlights?: {
    name: string; value: number | null; unit: string | null
    delta_pct: number | null; plan_pct: number | null; alert: string | null
  }[]
}

export async function listFeatured(): Promise<{ items: FeaturedDashboard[] }> {
  const res = await fetch('/dashboards/featured', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function setFeatured(id: string, featured: boolean): Promise<{ featured: boolean }> {
  const res = await fetch(`/dashboards/${id}/featured`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ featured }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

/** Черновик описания, собранный системой по составу дашборда. В БД не пишется:
 *  сохраняет человек, посмотрев глазами. */
export async function getDescriptionDraft(id: string): Promise<{ draft: string; current: string | null }> {
  const res = await fetch(`/dashboards/${id}/description-draft`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

/** Подогнать размеры виджетов страницы под их тип. Состав не меняется —
 *  двигаются только размер и место (лечит старые дашборды с карточками 3×3). */
export async function fitPageLayout(pageId: string): Promise<{ widgets: number; changed: number }> {
  const res = await fetch(`/dashboard-pages/${pageId}/fit-layout`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createWidget(pageId: string, body: {
  name: string; widget_type: string; config: Record<string, unknown>
  position_x?: number; position_y?: number; width?: number; height?: number
}): Promise<{ id: string }> {
  const res = await fetch(`/dashboard-pages/${pageId}/widgets`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function updateWidget(widgetId: string, patch: {
  name?: string; widget_type?: string; config?: Record<string, unknown>
  position_x?: number; position_y?: number; width?: number; height?: number
}): Promise<void> {
  const res = await fetch(`/widgets/${widgetId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error(await errText(res))
}
export async function deleteWidget(widgetId: string): Promise<void> {
  const res = await fetch(`/widgets/${widgetId}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
export async function getWidgetData(widgetId: string, from?: string, to?: string, row?: string): Promise<any> {
  const q = new URLSearchParams()
  if (from) q.set('from', from)
  if (to) q.set('to', to)
  if (row) q.set('row', row)
  const qs = q.toString()
  const res = await fetch(`/widgets/${widgetId}/data${qs ? `?${qs}` : ''}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function getWidgetDrill(widgetId: string): Promise<any> {
  const res = await fetch(`/widgets/${widgetId}/drill`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}



/** Дата самых свежих данных под дашбордом — для тихой проверки «не появилось ли новое». */
export async function dashboardFreshness(
  id: string,
): Promise<{ as_of: string | null; datasets: number; releases?: number }> {
  const res = await fetch(`/dashboards/${id}/freshness`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

/** Показатели, которые есть в данных, но не показаны на дашборде. */
export async function dashboardMissingFields(
  id: string,
): Promise<{ count: number; fields: { code: string; name: string; dataset_code: string }[] }> {
  const res = await fetch(`/dashboards/${id}/missing-fields`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}


/** Как шаблон ляжет на другой объект: сопоставление показателей по именам. */
export type TemplateBinding = {
  target: { dataset_code: string; dataset_name: string; fields: { code: string; name: string }[] }
  dataset_map: Record<string, string>
  field_map: Record<string, string>
  matched: { from: string; from_name: string; to: string }[]
  missing: { from: string; from_name: string }[]
  metrics: string[]
}

export async function templateBinding(templateId: string, objectId: string): Promise<TemplateBinding> {
  const res = await fetch(`/dashboard-templates/${templateId}/bindings?object_id=${objectId}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}



/** Поставить карточку показателя на страницу рядом с близким по смыслу виджетом.
 *  Место выбирает сервер: он знает, какие виджеты уже стоят и что они показывают. */
export async function placeMetricOnDashboard(body: {
  page_id: string
  metric_code: string
  name: string
  unit?: string | null
  based_on?: string[]
  dataset_code?: string | null
}): Promise<{ widget_id: string; placed_near: string | null }> {
  const res = await fetch('/dashboards/place-metric', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}


/** Показатели, уже размещённые на дашборде: чтобы не предлагать их повторно. */
export async function dashboardMetricCodes(id: string): Promise<{ codes: string[] }> {
  const res = await fetch(`/dashboards/${id}/metrics`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// «Куда можно перейти от этой цифры» (п. 1). Пункты строятся сервером по
// данным — из формул и настроек виджетов, а не из связок, настроенных руками:
// такие связки устаревают молча и ведут в никуда.
export interface RelatedWidgetRef {
  widget_id: string; widget_name: string; widget_type: string
  dashboard_id: string; dashboard_name: string
  page_id: string | null; page_name: string | null
}
export interface WidgetRelated {
  widget_id: string
  widget_name: string
  subject: { kind: string; code: string | null; name: string | null; dataset_code?: string }
  elsewhere: RelatedWidgetRef[]
  /** Соседние графы формы. `shown_widget_id` заполнен, если такая карточка на
   *  этом дашборде уже есть: тогда к ней переходят, а не заводят вторую. */
  siblings: {
    field: string; name: string
    shown_widget_id?: string; shown_widget_name?: string; shown_page_id?: string | null
  }[]
  dynamics: { available: boolean; periods: number; first?: string | null; last?: string | null }
  /** Страница, с которой смотрят: сюда кладётся карточка нового соседа. */
  page_id: string | null
  dashboard_id: string
}
export async function getWidgetRelated(widgetId: string): Promise<WidgetRelated> {
  const res = await fetch(`/widgets/${widgetId}/related`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// «Сообщить о проблеме» прямо с виджета (п. 15 — обратная связь). Контекст
// (дашборд, страница, показатель, значение на экране) собирает СЕРВЕР: человек
// не должен объяснять словами, где именно он это увидел.
export interface ProblemKind { code: string; label: string }
export async function widgetProblemKinds(): Promise<{ kinds: ProblemKind[] }> {
  const res = await fetch('/widgets/problem-kinds', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function reportWidgetProblem(
  widgetId: string, kind: string, comment: string,
): Promise<{ appeal_id: string; appended: boolean; subject: string | null; widget_name: string }> {
  const res = await fetch(`/widgets/${widgetId}/report-problem`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ kind, comment: comment || null }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// Кандидаты в подборку «Руководителю» (пп. 2–3 запроса заказчика): список всех
// доступных дашбордов с галочками, советом системы и объяснением «почему».
export type FeaturedCandidate = {
  id: string
  name: string
  description: string | null
  publication_status: string
  featured: boolean
  folder_name: string | null
  object_name: string | null
  widgets: number
  number_widgets: number
  views_30d: number
  /** Скольким сотрудникам отчёт реально виден: отметка в подборку доступа НЕ даёт. */
  visible_to: number
  recommended: boolean
  why: string[]
  blockers: string[]
}
export async function listFeaturedCandidates(): Promise<{ items: FeaturedCandidate[] }> {
  const res = await fetch('/dashboards/featured/candidates', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function setFeaturedBulk(featured: string[], unfeatured: string[]): Promise<{
  featured: number; unfeatured: number
}> {
  const res = await fetch('/dashboards/featured/bulk', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ featured, unfeatured }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// Доступ к подборке «Руководителю» пакетом. Состав подборки и доступ остаются
// разными вещами (иначе отметка молча открывала бы отчёт всем), но выдать
// доступ на всю подборку — одно действие, а не поход по каждому дашборду.
export interface FeaturedAccess {
  dashboards: { id: string; name: string; publication_status: string }[]
  users: { id: string; login: string; full_name: string | null; has: number; privileged: boolean }[]
  roles: { id: string; code: string; name: string; members: number; has: number }[]
}
export async function getFeaturedAccess(): Promise<FeaturedAccess> {
  const res = await fetch('/dashboards/featured/access', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function grantFeaturedAccess(
  userIds: string[], roleIds: string[], dashboardIds?: string[],
): Promise<{ granted: number; dashboards: number }> {
  const res = await fetch('/dashboards/featured/access', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ user_ids: userIds, role_ids: roleIds, dashboard_ids: dashboardIds ?? null }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
