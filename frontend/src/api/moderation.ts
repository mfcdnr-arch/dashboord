import { authH, errText } from './http'

// --- Модерация дашбордов ---
export interface ModerationQueueItem {
  dashboard_id: string
  name: string
  requested_at: string
  requester: string
  own: boolean // собственный дашборд — одобрять нельзя (конфликт интересов)
}
export interface ReasonCode { code: string; label: string; severity: 'low' | 'medium' | 'high' | 'critical' }
export interface ModerationHistoryItem {
  status: string
  requested_at: string
  resolved_at: string | null
  requester: string | null
  decision: string | null
  comment: string | null
  decided_at: string | null
  reviewer: string | null
}
export interface ModerationDecision {
  decision: 'approve' | 'return'
  reason_code?: string
  comment?: string
  checklist?: Record<string, string>
}
export async function submitDashboardReview(id: string): Promise<{ publication_status: string; version_no: number }> {
  const res = await fetch(`/dashboards/${id}/submit-review`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function cancelDashboardReview(id: string): Promise<{ publication_status: string }> {
  const res = await fetch(`/dashboards/${id}/cancel-review`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function getModerationQueue(): Promise<ModerationQueueItem[]> {
  const res = await fetch('/moderation/queue', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function getReasonCodes(): Promise<ReasonCode[]> {
  const res = await fetch('/moderation/reason-codes', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function moderateDashboard(id: string, body: ModerationDecision): Promise<{ decision: string; publication_status: string }> {
  const res = await fetch(`/dashboards/${id}/moderate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function getModerationHistory(id: string): Promise<ModerationHistoryItem[]> {
  const res = await fetch(`/dashboards/${id}/moderation-history`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

