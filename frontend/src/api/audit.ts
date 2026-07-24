import { authH, errText } from './http'

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
export async function getAuditEvent(id: string): Promise<AuditDetail> {
  const res = await fetch(`/audit/${id}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

