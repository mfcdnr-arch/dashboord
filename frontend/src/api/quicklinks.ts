// Быстрый доступ: куратор-меню коротких названий отчётов («MAX», «КЭП»,
// «Статистика отделов»…) — видно всем ролям, но каждый пункт отфильтрован
// по видимости для смотрящего (дашборд — по RLS, раздел — по его гейту).
import { authH, errText } from './http'

export type QuickLink =
  | { id: string; label: string; kind: 'dashboard'; dashboard_id: string; dashboard_name: string | null }
  | { id: string; label: string; kind: 'section'; section: string }

export async function listQuickLinks(): Promise<{ items: QuickLink[] }> {
  const res = await fetch('/quick-links', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function allowedQuickLinkSections(): Promise<{ sections: string[] }> {
  const res = await fetch('/quick-links/allowed-sections', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createQuickLink(data: {
  label: string; kind: 'dashboard' | 'section'; dashboard_id?: string; section?: string
}): Promise<{ id: string }> {
  const res = await fetch('/quick-links', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function deleteQuickLink(id: string): Promise<void> {
  const res = await fetch(`/quick-links/${id}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

export async function reorderQuickLinks(ids: string[]): Promise<void> {
  const res = await fetch('/quick-links/reorder', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ ids }),
  })
  if (!res.ok) throw new Error(await errText(res))
}
