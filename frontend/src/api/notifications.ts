import { authH, errText } from './http'

export interface NotificationItem {
  recipient_id: string
  event_type: string
  label: string
  entity_type: string
  entity_id: string | null
  payload: Record<string, unknown>
  created_at: string
  is_read: boolean
}
export interface NotificationsResult {
  unread: number
  items: NotificationItem[]
}

export async function getNotifications(): Promise<NotificationsResult> {
  const res = await fetch('/notifications', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function markNotificationRead(recipientId: string): Promise<void> {
  const res = await fetch(`/notifications/${recipientId}/read`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
export async function markAllNotificationsRead(): Promise<void> {
  const res = await fetch('/notifications/read-all', { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
