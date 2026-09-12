import { authH, errText } from './http'

// --- Раздел «Карта»: справочник отделений МФЦ ---
// Отделение до появления справочника существовало только строкой отчёта и в
// интерфейсе не правилось: адрес, телефон и режим работы система не хранила.

export type DayKey = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'
export const DAYS: { key: DayKey; short: string; full: string }[] = [
  { key: 'mon', short: 'пн', full: 'Понедельник' },
  { key: 'tue', short: 'вт', full: 'Вторник' },
  { key: 'wed', short: 'ср', full: 'Среда' },
  { key: 'thu', short: 'чт', full: 'Четверг' },
  { key: 'fri', short: 'пт', full: 'Пятница' },
  { key: 'sat', short: 'сб', full: 'Суббота' },
  { key: 'sun', short: 'вс', full: 'Воскресенье' },
]
export type DayHours = { from: string; to: string } | null
export type Hours = Partial<Record<DayKey, DayHours>>

export interface Office {
  id: string
  name: string
  address: string | null
  city: string | null
  phone: string | null
  phone2: string | null
  email: string | null
  website: string | null
  hours: Hours
  note: string | null
  lat: number | null
  lon: number | null
  row_label: string | null
  is_active: boolean
  source_id: string | null
  /** null — координат нет, судить не о чем. */
  inside_contour: boolean | null
  created_at: string
  updated_at: string
}

export interface OfficeInput {
  name?: string
  address?: string | null
  city?: string | null
  phone?: string | null
  phone2?: string | null
  email?: string | null
  website?: string | null
  hours?: Hours
  note?: string | null
  lat?: number | null
  lon?: number | null
  row_label?: string | null
  is_active?: boolean
}

export interface ImportResult {
  total: number
  created: number
  updated: number
  skipped: number
  no_coords: string[]
  outside_contour: string[]
  errors: { line: number | null; error: string }[]
}

export interface UnmatchedRow {
  row_label: string
  suggestion: { id: string; name: string; score: number } | null
}
export interface UnmatchedReport {
  dataset_code: string | null
  period?: string | null
  rows_total: number
  linked: number
  unmatched: UnmatchedRow[]
  offices_without_row: { id: string; name: string; city: string | null }[]
  hint?: string
}

export async function listOffices(params: { q?: string; only_active?: boolean } = {}): Promise<Office[]> {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.only_active) qs.set('only_active', 'true')
  const res = await fetch(`/map/offices${qs.toString() ? `?${qs}` : ''}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function createOffice(body: OfficeInput): Promise<Office> {
  const res = await fetch('/map/offices', { method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify(body) })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function updateOffice(id: string, patch: OfficeInput): Promise<Office> {
  const res = await fetch(`/map/offices/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify(patch) })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function deleteOffice(id: string): Promise<void> {
  const res = await fetch(`/map/offices/${id}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
export async function importOffices(file: File, updateExisting: boolean): Promise<ImportResult> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`/map/offices/import?update_existing=${updateExisting}`, { method: 'POST', headers: authH(), body: fd })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function unmatchedRows(datasetCode?: string): Promise<UnmatchedReport> {
  const qs = datasetCode ? `?dataset_code=${encodeURIComponent(datasetCode)}` : ''
  const res = await fetch(`/map/offices/unmatched${qs}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function getMapSettings(): Promise<{ map_dataset_code: string | null }> {
  const res = await fetch('/map/settings', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function saveMapSettings(code: string | null): Promise<{ map_dataset_code: string | null }> {
  const res = await fetch('/map/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify({ map_dataset_code: code }) })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

/** Режим работы одной строкой — для списка, где на семь дней места нет.
 *  Подряд идущие дни сжимаются в диапазон: «пн, вт, ср, чт, пт, сб» занимает
 *  в колонке три строки и читается хуже, чем «пн–сб». */
export function hoursSummary(h: Hours | null | undefined): string {
  if (!h || !Object.keys(h).length) return 'не задан'
  const work = DAYS.filter((d) => h[d.key])
  if (!work.length) return 'выходные все дни'
  const idx = work.map((d) => DAYS.findIndex((x) => x.key === d.key))
  const parts: string[] = []
  let start = 0
  for (let i = 1; i <= idx.length; i++) {
    if (i === idx.length || idx[i] !== idx[i - 1] + 1) {
      const a = DAYS[idx[start]].short
      const b = DAYS[idx[i - 1]].short
      parts.push(i - 1 - start >= 2 ? `${a}–${b}` : work.slice(start, i).map((d) => d.short).join(', '))
      start = i
    }
  }
  const first = h[work[0].key]!
  const same = work.every((d) => h[d.key]!.from === first.from && h[d.key]!.to === first.to)
  return same ? `${parts.join(', ')} · ${first.from}–${first.to}` : `${parts.join(', ')} · по-разному`
}

export interface LinkSuggestedResult {
  linked: number
  items: { row_label: string; office: string }[]
  conflicts: { row_label: string; office: string; reason: string }[]
  left_manual: string[]
}
/** Связать разом все строки отчёта, где подсказка однозначна. Подсказки
 *  пересчитываются на сервере — экран мог устареть. */
export async function linkSuggested(datasetCode?: string): Promise<LinkSuggestedResult> {
  const qs = datasetCode ? `?dataset_code=${encodeURIComponent(datasetCode)}` : ''
  const res = await fetch(`/map/offices/link-suggested${qs}`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
