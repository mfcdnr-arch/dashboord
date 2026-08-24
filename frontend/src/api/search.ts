import { authH, errText } from './http'

// Быстрый поиск по системе (п. 9, Ctrl+K).
export interface SearchDashboard { id: string; name: string; object_name: string | null; folder_name: string | null }
export interface SearchPage { id: string; name: string; dashboard_id: string; dashboard_name: string }
export interface SearchWidget {
  id: string; name: string; widget_type: string
  dashboard_id: string; dashboard_name: string
  page_id: string | null; page_name: string | null
}
export interface SearchObject { id: string; name: string }
export interface SearchMetric { id: string; code: string; name: string }
export interface SearchResults {
  dashboards: SearchDashboard[]
  pages: SearchPage[]
  widgets: SearchWidget[]
  objects: SearchObject[]
  metrics: SearchMetric[]
}

export async function globalSearch(q: string): Promise<SearchResults> {
  const res = await fetch(`/search?q=${encodeURIComponent(q)}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
