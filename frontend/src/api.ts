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
export interface DataSet { code: string; name: string; object: string | null; dates: string[]; fields: DsField[]; rows: string[] }
export interface DataSources { datasets: DataSet[]; metrics: { code: string; name: string }[] }

export async function getDataSources(): Promise<DataSources> {
  const res = await fetch('/metrics/data-sources', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
