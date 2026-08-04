import { authH, errText, type Page } from './http'

// --- Метрики и формулы ---

export interface Metric {
  id: string
  code: string
  name: string
  description: string | null
  info_text?: string | null
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

export async function listMetrics(q = '', limit = 50, offset = 0): Promise<Page<Metric>> {
  const p = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (q.trim()) p.set('q', q.trim())
  const res = await fetch(`/metrics?${p}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function getMetric(id: string): Promise<{ metric: Metric; versions: MetricVersion[] }> {
  const res = await fetch(`/metrics/${id}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function updateMetric(id: string, patch: { name?: string; description?: string | null; info_text?: string | null; owner_id?: string | null }): Promise<Metric> {
  const res = await fetch(`/metrics/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(patch),
  })
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

// Рекомендательная система, часть B (2026-08-04): предложения производных метрик.
export interface MetricSuggestion {
  type: string  // diff | share | period_compare | yoy | running_total | plan_fact | deviation
  name: string
  formula: string
  unit: string | null
  based_on: string[]
  code: string  // черновой уникальный код — используется при принятии предложения
}
export async function metricSuggestions(dashboardId: string): Promise<{ specs: MetricSuggestion[]; candidates_count: number }> {
  const res = await fetch(`/metrics/suggestions?dashboard_id=${encodeURIComponent(dashboardId)}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

