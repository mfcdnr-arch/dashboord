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

