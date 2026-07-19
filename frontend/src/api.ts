// Клиент к Dashboard API (в dev проксируется через Vite на порт 8080).

const TOKEN_KEY = 'dashbord_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t: string): void {
  localStorage.setItem(TOKEN_KEY, t)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export interface Health {
  status: string
  service: string
  env: string
  db: string
}

export async function getHealth(): Promise<Health> {
  const res = await fetch('/health')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function login(username: string, password: string): Promise<string> {
  const body = new URLSearchParams({ username, password })
  const res = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!res.ok) throw new Error('Неверный логин или пароль')
  const data = await res.json()
  return data.access_token as string
}

export interface Me {
  id: string
  login: string
  full_name: string | null
  must_change_password: boolean
  roles: string[]
}

export async function getMe(token: string): Promise<Me> {
  const res = await fetch('/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('unauthorized')
  return res.json()
}

export async function changePassword(token: string, newPassword: string): Promise<void> {
  const res = await fetch('/auth/change-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ new_password: newPassword }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Ошибка смены пароля')
  }
}

// --- Объекты / папки / документы ---

function authH(): Record<string, string> {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

async function errText(res: Response): Promise<string> {
  try {
    const e = await res.json()
    return typeof e.detail === 'string' ? e.detail : `Ошибка (${res.status})`
  } catch {
    return `Ошибка (${res.status})`
  }
}

export interface Obj {
  id: string
  name: string
  description: string | null
  created_at: string
  folders_count?: number
}
export interface Folder {
  id: string
  name: string
  parent_folder_id: string | null
  created_at: string
}
export interface Doc {
  id: string
  original_filename: string
  source_type: string
  status: string
  reporting_period_start: string
  reporting_period_end: string | null
  size: number | null
  created_at: string
  version_id: string | null
}

export async function listObjects(): Promise<Obj[]> {
  const res = await fetch('/objects', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createObject(name: string, description?: string): Promise<Obj> {
  const res = await fetch('/objects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ name, description: description || null }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function listFolders(objectId: string): Promise<Folder[]> {
  const res = await fetch(`/objects/${objectId}/folders`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createFolder(objectId: string, name: string): Promise<Folder> {
  const res = await fetch(`/objects/${objectId}/folders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ name }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function listDocuments(folderId: string): Promise<Doc[]> {
  const res = await fetch(`/folders/${folderId}/documents`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function uploadDocument(folderId: string, file: File, reportingDate: string): Promise<void> {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('reporting_period_start', reportingDate)
  const res = await fetch(`/folders/${folderId}/documents`, { method: 'POST', headers: authH(), body: fd })
  if (!res.ok) throw new Error(await errText(res))
}

// --- Извлечение (ingestion): распознавание, маппинг, выпуск датасета ---

export interface ExtractedColumn {
  column_index: number
  source_header: string
  inferred_type: string
  confidence_score: number | null
  canonical_field_code: string | null
}
export interface ExtractedTable {
  id: string
  sheet_or_page: string | null
  table_index: number
  row_count: number
  column_count: number
  header_rows: number
  preview: string[][]
  columns: ExtractedColumn[]
}
export interface ExtractionJob {
  status: string // none | queued | running | succeeded | needs_review | failed
  job_id?: string
  document_version_id?: string
  confidence_score?: number | null
  warnings?: string[]
  error_message?: string | null
  tables: ExtractedTable[]
}
export interface FieldSuggestion {
  column_index: number
  source_header: string
  field_code: string
  field_name: string
  data_type: string
  is_row_label: boolean
  confidence: number | null
}
export interface MappingSuggestion {
  row_label_column: number | null
  columns: FieldSuggestion[]
}
export interface FieldMap {
  column_index: number
  field_code: string
  field_name: string
  data_type: string
  unit?: string | null
  is_row_label: boolean
}
export interface ReleaseResult {
  release_id: string
  status: string
  values_count: number
  rows: number
  superseded_release_id: string | null
}
export interface ReleaseConflict {
  conflict: true
  existing: { id: string; name: string; status: string; created_at: string }
}

export async function startExtraction(versionId: string): Promise<{ job_id: string; status: string }> {
  const res = await fetch(`/document-versions/${versionId}/extract`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function getExtractionForVersion(versionId: string): Promise<ExtractionJob> {
  const res = await fetch(`/document-versions/${versionId}/extraction`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function getJob(jobId: string): Promise<ExtractionJob> {
  const res = await fetch(`/extraction-jobs/${jobId}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function getMappingSuggestion(jobId: string, tableId: string): Promise<MappingSuggestion> {
  const res = await fetch(`/extraction-jobs/${jobId}/tables/${tableId}/mapping-suggestion`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createRelease(
  jobId: string,
  body: { table_id: string; code: string; name: string; reporting_period_start: string | null; fields: FieldMap[]; supersede: boolean },
): Promise<ReleaseResult | ReleaseConflict> {
  const res = await fetch(`/extraction-jobs/${jobId}/release`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(body),
  })
  if (res.status === 409) {
    const e = await res.json().catch(() => ({}))
    return { conflict: true, existing: e?.detail?.existing } as ReleaseConflict
  }
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// --- Метрики и формулы ---

export interface Metric {
  id: string
  code: string
  name: string
  description: string | null
  created_at: string
  versions?: number
  unit?: string | null
  has_approved?: boolean
}
export interface MetricVersion {
  id: string
  version_no: number
  status: string // draft | validated | approved | deprecated | archived
  formula_expression: string
  unit: string | null
  grain: string | null
  calculation_type: string
  created_by: string
  approved_by: string | null
  approved_at: string | null
  created_at: string
}
export interface Dependencies { datasets: string[]; metrics: string[] }

export async function listMetrics(): Promise<Metric[]> {
  const res = await fetch('/metrics', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function getMetric(id: string): Promise<{ metric: Metric; versions: MetricVersion[] }> {
  const res = await fetch(`/metrics/${id}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createMetric(code: string, name: string, description?: string): Promise<Metric> {
  const res = await fetch('/metrics', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ code, name, description: description || null }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createVersion(
  metricId: string,
  body: { formula: string; unit?: string | null; grain?: string | null; calculation_type?: string },
): Promise<{ version_id: string; version_no: number; status: string; dependencies: Dependencies }> {
  const res = await fetch(`/metrics/${metricId}/versions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function previewFormula(formula: string): Promise<{ value: number; dependencies: Dependencies }> {
  const res = await fetch('/metrics/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ formula }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function validateVersion(versionId: string): Promise<void> {
  const res = await fetch(`/metrics/versions/${versionId}/validate`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

export async function approveVersion(versionId: string): Promise<void> {
  const res = await fetch(`/metrics/versions/${versionId}/approve`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

export async function versionValue(versionId: string): Promise<{ value: number; unit: string | null }> {
  const res = await fetch(`/metrics/versions/${versionId}/value`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// Справочник для визуального конструктора формул
export interface DsField { code: string; name: string; data_type: string; is_row_label: boolean }
export interface DataSet { code: string; name: string; object: string | null; folder: string | null; document: string | null; dates: string[]; fields: DsField[]; rows: string[] }
export interface MetricSource { code: string; name: string; unit?: string | null; formula?: string | null }
export interface DataSources { datasets: DataSet[]; metrics: MetricSource[] }

export async function getDataSources(): Promise<DataSources> {
  const res = await fetch('/metrics/data-sources', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// --- Дашборды / страницы / виджеты ---

export interface Dashboard {
  id: string
  name: string
  description: string | null
  publication_status: string
  created_at: string
  pages?: number
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
}

export async function listDashboards(): Promise<Dashboard[]> {
  const res = await fetch('/dashboards', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function createDashboard(name: string, description?: string): Promise<Dashboard> {
  const res = await fetch('/dashboards', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ name, description: description || null }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function autoBuildDashboard(objectId: string, name?: string): Promise<{ dashboard_id: string; page_id: string; widgets: number }> {
  const res = await fetch('/dashboards/auto', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ object_id: objectId, name: name || null }),
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
export async function instantiateTemplate(templateId: string, name: string): Promise<{ dashboard_id: string }> {
  const res = await fetch(`/dashboard-templates/${templateId}/instantiate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ name }),
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
export interface DashGrant { id: string; grantee_type: 'role' | 'user'; role_id: string | null; user_id: string | null; label: string; granted_at: string }
export interface GrantTargets { users: { id: string; login: string; full_name: string | null }[]; roles: { id: string; code: string; name: string }[] }
export async function listDashboardGrants(dashboardId: string): Promise<{ grants: DashGrant[]; targets: GrantTargets }> {
  const res = await fetch(`/dashboards/${dashboardId}/grants`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function addDashboardGrant(dashboardId: string, body: { grantee_type: 'role' | 'user'; role_id?: string; user_id?: string }): Promise<{ id: string }> {
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
export async function widgetSuggestions(datasetCode: string): Promise<WidgetSpec[]> {
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

// --- Главная ---
export interface HomeData {
  counters: { dashboards: number; objects: number; metrics: number; datasets: number; users: number }
  pages: { dashboard_id: string; dashboard_name: string; page_id: string; page_name: string; description: string | null; widgets: number }[]
  recent: { kind: string; title: string; at: string }[]
  freshness: { name: string; last_update: string | null; last_period: string | null }[]
  key_kpis: { code: string; name: string; value: number | null; unit: string | null; error: string | null }[]
  alerts: {
    widget_id: string; widget_name: string; widget_type: string
    dashboard_id: string; dashboard_name: string; page_name: string | null; published: boolean
    level: 'warn' | 'danger'; label: string; measure: number | null; unit: string | null
  }[]
}
export async function getHome(): Promise<HomeData> {
  const res = await fetch('/home', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function addHomeKpi(metricCode: string): Promise<void> {
  const res = await fetch('/home/kpis', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ metric_code: metricCode }),
  })
  if (!res.ok) throw new Error(await errText(res))
}
export async function removeHomeKpi(metricCode: string): Promise<void> {
  const res = await fetch(`/home/kpis/${metricCode}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

// --- Модуль «Пользователи» (волна B) ---
export interface Department { id: string; name: string; users: number }
export interface Role { id: string; code: string; name: string }
export interface AppUser {
  id: string; login: string; full_name: string | null
  last_name: string | null; first_name: string | null; middle_name: string | null
  email: string | null; is_active: boolean; must_change_password: boolean
  department_id: string | null; department: string | null; roles: string[]; created_at: string
}
export async function listDepartments(): Promise<Department[]> {
  const res = await fetch('/departments', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function createDepartment(name: string): Promise<Department> {
  const res = await fetch('/departments', { method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify({ name }) })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function deleteDepartment(id: string): Promise<void> {
  const res = await fetch(`/departments/${id}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
export async function listRoles(): Promise<Role[]> {
  const res = await fetch('/roles', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function listUsers(): Promise<AppUser[]> {
  const res = await fetch('/users', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export interface UserInput {
  login: string; password: string; last_name?: string; first_name?: string; middle_name?: string
  email?: string; department_id?: string; role_ids: string[]
}
export async function createUser(body: UserInput): Promise<{ id: string; login: string }> {
  const res = await fetch('/users', { method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify(body) })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function updateUser(id: string, patch: {
  last_name?: string; first_name?: string; middle_name?: string; email?: string; department_id?: string | null; role_ids?: string[]
}): Promise<void> {
  const res = await fetch(`/users/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify(patch) })
  if (!res.ok) throw new Error(await errText(res))
}
export async function setUserActive(id: string, is_active: boolean): Promise<void> {
  const res = await fetch(`/users/${id}/active`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify({ is_active }) })
  if (!res.ok) throw new Error(await errText(res))
}
export async function resetUserPassword(id: string, password: string): Promise<void> {
  const res = await fetch(`/users/${id}/reset-password`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify({ password }) })
  if (!res.ok) throw new Error(await errText(res))
}

export interface LoginEventsReport {
  summary: { login: string; full_name: string | null; is_active: boolean; logins: number; failed: number; last_login: string | null }[]
  recent: { login: string; full_name: string | null; ip: string | null; success: boolean; created_at: string }[]
}
export async function getLoginEvents(): Promise<LoginEventsReport> {
  const res = await fetch('/login-events', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// --- Аудит действий (журнал изменений сущностей) ---
export interface AuditItem {
  id: string
  action: string
  entity_type: string
  entity_id: string
  entity_name: string | null
  actor_user_id: string | null
  actor_login: string | null
  actor_name: string | null
  ip_address: string | null
  created_at: string
  changed_fields: string[]
}
export interface AuditFacets {
  actors: { id: string; login: string; full_name: string | null }[]
  entity_types: { code: string; label: string }[]
  actions: string[]
}
export interface AuditList {
  total: number
  limit: number
  offset: number
  items: AuditItem[]
  facets: AuditFacets
}
export interface AuditDiffField { field: string; old: unknown; new: unknown; changed: boolean }
export interface AuditDetail {
  id: string
  action: string
  entity_type: string
  entity_id: string
  entity_name: string | null
  actor_user_id: string | null
  actor_login: string | null
  actor_name: string | null
  ip_address: string | null
  created_at: string
  diff: AuditDiffField[]
}
export interface AuditQuery {
  actor?: string
  entity_type?: string
  entity_id?: string
  action?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}
export async function listAudit(q: AuditQuery = {}): Promise<AuditList> {
  const p = new URLSearchParams()
  Object.entries(q).forEach(([k, v]) => {
    if (v !== undefined && v !== '' && v !== null) p.set(k, String(v))
  })
  const res = await fetch(`/audit?${p.toString()}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function getAuditEvent(id: string): Promise<AuditDetail> {
  const res = await fetch(`/audit/${id}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// --- Отчёты (волна B) ---
export interface Gauge { percent: number; level: 'good' | 'warn' | 'danger'; used?: number; total?: number }
export interface SystemReport {
  cpu: Gauge; memory: Gauge; disk: Gauge
  load: number[] | null; cores: number; uptime_sec: number; db_size: number | null
  services: { name: string; ok: boolean }[]
}
export interface AttendanceReport {
  totals: { logins: number; failed: number; active_users: number }
  per_day: { day: string; logins: number; failed: number }[]
  top_users: { login: string; logins: number }[]
}
export async function getSystemReport(): Promise<SystemReport> {
  const res = await fetch('/reports/system', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function getAttendanceReport(): Promise<AttendanceReport> {
  const res = await fetch('/reports/attendance', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export interface DataQualityReport {
  objects: { name: string; datasets: number; last_period: string | null; last_update: string | null; status: string }[]
  no_data: string[]
  metric_errors: { code: string; name: string; error: string }[]
  metrics_total: number
}
export interface BusinessReport {
  metrics: { code: string; name: string; unit: string | null; value: number | null; error: string | null }[]
  alerts: { widget_name: string; dashboard_name: string; level: 'warn' | 'danger'; label: string; measure: number | null }[]
}
export async function getDataQualityReport(): Promise<DataQualityReport> {
  const res = await fetch('/reports/data-quality', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function getBusinessReport(): Promise<BusinessReport> {
  const res = await fetch('/reports/business', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
