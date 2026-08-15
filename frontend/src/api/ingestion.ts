import { authH, errText } from './http'

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
  /** Диапазоны объединённых ячеек [r1,c1,r2,c2] — предпросмотр рисует их rowSpan/colSpan. */
  merges: number[][]
  /** Область данных [r1,c1,r2,c2], предложенная системой (отсечён текст письма). */
  data_rect: number[] | null
  columns: ExtractedColumn[]
}
/** Разметка прошлого выпуска этой же формы (шаблон объекта).
 *
 *  `match: 'exact'` — структура файла совпала с прошлым выпуском, разметку
 *  можно подставить (`table_id` — к какой таблице). `structure_differs` —
 *  форма изменилась: применять нельзя, иначе цифры будут неверными молча. */
export interface LayoutTemplate {
  match: 'exact' | 'structure_differs'
  mode: 'table' | 'cells'
  table_id: string | null
  layout: { data_rect: number[] | null; header_rows: number | null; orientation: 'columns' | 'rows'; skip_rows: number[] }
  fields: FieldMap[]
  cells: { row: number; col: number; field_code: string; field_name: string; data_type?: string }[]
  dataset_code: string | null
  updated_at: string
  source_release_name: string | null
  source_release_period: string | null
  /** Число строк изменилось или область расширена — человеку стоит проверить границы. */
  rows_differ: boolean
  note: string
}

export interface ExtractionJob {
  status: string // none | queued | running | succeeded | needs_review | failed
  job_id?: string
  /** Как размечали эту форму в прошлый раз — конструктор открывается размеченным. */
  layout_template?: LayoutTemplate | null
  /** Код датасета по умолчанию — от имени объекта (или уже использованный им).
   *  Раньше в форме стояло жёсткое «dataset», из-за чего второй объект
   *  сталкивался с первым: данные ищутся по коду без учёта объекта. */
  suggested_code?: string
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
  /** «№ п/п» и подобное: счётчик строк бланка, а не показатель. */
  is_counter?: boolean
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
export interface ValidationWarning { code: string; count: number; message: string }
export interface ReleaseResult {
  release_id: string
  status: string
  values_count: number
  rows: number
  superseded_release_id: string | null
  validation?: { warnings: ValidationWarning[]; ok: boolean }
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

/** Разметка, выбранная мышью: область, этажи шапки, ориентация, снятые строки. */
export interface Layout {
  data_rect: number[] | null
  header_rows: number
  orientation: 'columns' | 'rows'
  skip_rows: number[]
}
export interface CellPick {
  row: number
  col: number
  field_code: string
  field_name: string
  data_type: string
}
export interface LayoutRow {
  /** Индекс строки в сетке разметки (шапка тоже считается). */
  index: number
  label: string
  has_number: boolean
  /** Заполнено ли название строки — строка с числами, но без подписи почти
   *  всегда служебная и молча удваивает итоги. */
  has_label?: boolean
}
export interface LayoutPreview {
  data_rect: number[]
  header_rows: number
  orientation: string
  row_label_column: number | null
  row_count: number
  columns: FieldSuggestion[]
  rows: LayoutRow[]
  /** Служебные строки: без чисел (подписи, примечания) ИЛИ с числами, но без названия. */
  suspect_rows: number[]
  sample: string[][]
}

/** Пересчёт разметки под текущий выбор — тем же кодом, что и выпуск. */
export async function layoutPreview(jobId: string, body: Layout & { table_id: string }): Promise<LayoutPreview> {
  const res = await fetch(`/extraction-jobs/${jobId}/layout-preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createRelease(
  jobId: string,
  body: {
    table_id: string; code: string; name: string; reporting_period_start: string | null
    fields: FieldMap[]; supersede: boolean; layout?: Layout; cells?: CellPick[]
  },
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


/** Замечания по качеству ДО выпуска: сверка с предыдущей неделей.
 *  Считает та же функция, что и выпуск, — расхождение невозможно. */
export async function qualityCheck(
  jobId: string,
  body: {
    table_id: string; code: string; name: string; reporting_period_start: string | null
    fields: FieldMap[]; layout?: Layout
  },
): Promise<{ warnings: ValidationWarning[]; ok: boolean }> {
  const res = await fetch(`/extraction-jobs/${jobId}/quality-check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ ...body, supersede: false }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export type VersionRelease = {
  id: string
  code: string
  name: string
  status: string
  reporting_period_start: string | null
  values_count: number
}

/** Выпуски, сделанные из этой версии документа. */
export async function listVersionReleases(versionId: string): Promise<VersionRelease[]> {
  const res = await fetch(`/document-versions/${versionId}/dataset-releases`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function cancelRelease(releaseId: string): Promise<{ status: string; affected: string[] }> {
  const res = await fetch(`/dataset-releases/${releaseId}/cancel`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function restoreRelease(releaseId: string): Promise<void> {
  const res = await fetch(`/dataset-releases/${releaseId}/restore`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

export async function deleteRelease(releaseId: string): Promise<void> {
  const res = await fetch(`/dataset-releases/${releaseId}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
