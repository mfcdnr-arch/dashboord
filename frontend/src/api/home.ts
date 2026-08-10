import { authH, errText } from './http'

// --- Главная ---
export interface HomeData {
  counters: {
    dashboards: number; objects: number; metrics: number; datasets: number; users: number
    documents?: number; releases?: number
  }
  /** За какой период есть данные и когда последняя загрузка. */
  data_span?: { first_period: string | null; last_period: string | null; last_upload: string | null }
  /** Пройденные шаги настройки — по ним строится подсказка «что дальше». */
  setup?: { objects: boolean; documents: boolean; datasets: boolean; metrics: boolean; dashboards: boolean; published: boolean }
  pending_review?: number
  pages: { dashboard_id: string; dashboard_name: string; page_id: string; page_name: string; description: string | null; widgets: number }[]
  recent: { kind: string; title: string; at: string }[]
  freshness: { name: string; last_update: string | null; last_period: string | null }[]
  key_kpis: { code: string; name: string; value: number | null; unit: string | null; error: string | null }[]
  alerts: {
    widget_id: string; widget_name: string; widget_type: string
    dashboard_id: string; dashboard_name: string; page_name: string | null; published: boolean
    level: 'warn' | 'danger'; label: string; measure: number | null; unit: string | null
  }[]
}
export async function getHome(): Promise<HomeData> {
  const res = await fetch('/home', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function addHomeKpi(metricCode: string): Promise<void> {
  const res = await fetch('/home/kpis', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ metric_code: metricCode }),
  })
  if (!res.ok) throw new Error(await errText(res))
}
export async function removeHomeKpi(metricCode: string): Promise<void> {
  const res = await fetch(`/home/kpis/${metricCode}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

