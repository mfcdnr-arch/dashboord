// Витрины (волна E): именованная подборка из N ЦЕЛЫХ дашбордов на одном
// экране. НЕ путать с «📺 Витрина» (KioskView) в дашборде — тот слайд-шоу
// СТРАНИЦ ОДНОГО дашборда.
import { authH, errText } from './http'

export interface ShowcaseSummary {
  id: string
  name: string
  created_at: string
  updated_at: string
  items_count: number
}
export interface ShowcaseItem {
  id: string
  dashboard_id: string
  dashboard_name: string
  page_id: string | null
  page_name: string | null
  position: number
}
export interface ShowcaseDetail {
  id: string
  name: string
  created_at: string
  updated_at: string
  items: ShowcaseItem[]
}

export async function listShowcases(): Promise<ShowcaseSummary[]> {
  const res = await fetch('/showcases', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createShowcase(name: string): Promise<{ id: string; name: string; created_at: string }> {
  const res = await fetch('/showcases', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ name }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function getShowcase(id: string): Promise<ShowcaseDetail> {
  const res = await fetch(`/showcases/${id}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function deleteShowcase(id: string): Promise<void> {
  const res = await fetch(`/showcases/${id}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

export async function addShowcaseItem(id: string, dashboardId: string): Promise<{ id: string; position: number }> {
  const res = await fetch(`/showcases/${id}/items`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ dashboard_id: dashboardId }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function removeShowcaseItem(id: string, itemId: string): Promise<void> {
  const res = await fetch(`/showcases/${id}/items/${itemId}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

export async function reorderShowcaseItem(id: string, itemId: string, direction: 'up' | 'down'): Promise<void> {
  const res = await fetch(`/showcases/${id}/reorder`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ item_id: itemId, direction }),
  })
  if (!res.ok) throw new Error(await errText(res))
}
