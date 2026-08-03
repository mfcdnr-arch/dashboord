import { authH, downloadFile, errText } from './http'

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
  include_views?: boolean
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
// Выгрузка журнала аудита в CSV/XLSX с текущими фильтрами (limit/offset не нужны).
export function exportAudit(q: AuditQuery, fmt: 'csv' | 'xlsx'): Promise<void> {
  const p = new URLSearchParams()
  Object.entries(q).forEach(([k, v]) => {
    if (k === 'limit' || k === 'offset') return
    if (v !== undefined && v !== '' && v !== null) p.set(k, String(v))
  })
  const qs = p.toString()
  return downloadFile(`/audit/export.${fmt}${qs ? '?' + qs : ''}`, `audit.${fmt}`)
}

export async function getAuditEvent(id: string): Promise<AuditDetail> {
  const res = await fetch(`/audit/${id}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}


// Логирование выгрузки, сгенерированной на клиенте (PDF/PNG — без своего
// серверного эндпоинта); xlsx логируется автоматически на сервере.
export async function logClientExport(entityType: string, entityId: string, format: string): Promise<void> {
  await fetch('/audit/log-export', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ entity_type: entityType, entity_id: entityId, format }),
  }).catch(() => {}) // best-effort: не мешаем экспорту, если лог не записался
}

// --- Доступ admin→аудит (управляет только superadmin) ---
export interface AuditAccessRow { user_id: string; login: string; full_name: string | null; granted_at: string }
export async function listAuditAccess(): Promise<AuditAccessRow[]> {
  const res = await fetch('/audit/access', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function grantAuditAccess(userId: string): Promise<void> {
  const res = await fetch(`/audit/access/${userId}`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
export async function revokeAuditAccess(userId: string): Promise<void> {
  const res = await fetch(`/audit/access/${userId}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
