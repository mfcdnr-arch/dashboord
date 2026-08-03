// Архив дашбордов: слепки, месячные папки, темы, доступ, автоархивация.
import { authH, downloadFile, errText } from './http'

export type ArchiveItem = {
  id: string
  dashboard_id: string | null
  dashboard_name: string
  topic: string | null
  note: string | null
  archive_month: string
  auto: boolean
  archived_at: string
  archived_by_name: string | null
  pages: number
}

export type ArchiveMonth = { month: string; count: number }

export type ArchiveWidget = { id: string; name: string; widget_type: string; x: number; y: number; w: number; h: number; data?: unknown; error?: string }
export type ArchiveSnapshot = { pages: { name: string; widgets: ArchiveWidget[] }[] }
export type ArchiveFull = Omit<ArchiveItem, 'pages'> & { snapshot: ArchiveSnapshot }

export type ArchiveAccessRow = { user_id: string; login: string; full_name: string | null; granted_at: string }

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
async function send<T>(url: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method, headers: { 'Content-Type': 'application/json', ...authH() },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.status === 204 ? (undefined as T) : res.json()
}

export const archiveMe = () => get<{ allowed: boolean }>('/archive/me')
export const archiveMonths = () => get<ArchiveMonth[]>('/archive/months')
export const archiveTopics = () => get<string[]>('/archive/topics')

export function listArchive(month?: string, q?: string, topic?: string, fromDate?: string, toDate?: string): Promise<ArchiveItem[]> {
  const p = new URLSearchParams()
  if (month) p.set('month', month)
  if (q) p.set('q', q)
  if (topic) p.set('topic', topic)
  if (fromDate) p.set('from_date', fromDate)
  if (toDate) p.set('to_date', toDate)
  const qs = p.toString()
  return get(`/archive${qs ? `?${qs}` : ''}`)
}
export const getArchive = (id: string) => get<ArchiveFull>(`/archive/${id}`)

export const archiveDashboard = (dashboardId: string, topic: string, note: string) =>
  send<{ id: string; archive_month: string }>(`/dashboards/${dashboardId}/archive`, 'POST', { topic: topic || null, note: note || null })
export const setAutoArchive = (dashboardId: string, enabled: boolean) =>
  send<{ auto_archive: boolean }>(`/dashboards/${dashboardId}/auto-archive`, 'POST', { enabled })
export const unarchive = (archiveId: string) =>
  send<{ dashboard_id: string; publication_status: string }>(`/archive/${archiveId}/unarchive`, 'POST')
export const deleteArchive = (archiveId: string) => send<void>(`/archive/${archiveId}`, 'DELETE')
export const exportArchiveXlsx = (archiveId: string, name: string) =>
  downloadFile(`/archive/${archiveId}/export.xlsx`, `Архив_${name}.xlsx`)

export const listArchiveAccess = () => get<ArchiveAccessRow[]>('/archive-access')
export const addArchiveAccess = (userId: string) => send<{ user_id: string }>('/archive-access', 'POST', { user_id: userId })
export const removeArchiveAccess = (userId: string) => send<void>(`/archive-access/${userId}`, 'DELETE')
