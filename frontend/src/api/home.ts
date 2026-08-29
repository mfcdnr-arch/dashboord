import { authH, errText } from './http'

export type KeyKpi = { code: string; name: string; value: number | null; unit: string | null; error: string | null }

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
  /** Что именно поступило: отчёт за какую дату, из какого файла, сколько в нём
   *  показателей. Лента `recent` отвечает «когда», это — «что пришло». */
  recent_data?: {
    id: string; name: string; code: string; period: string | null; created_at: string | null
    object_name: string | null; folder_name: string | null; filename: string | null
    values_count: number; fields_count: number
  }[]
  freshness: { name: string; last_update: string | null; last_period: string | null }[]
  key_kpis: KeyKpi[]
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

/** Отмеченные графы новой формы → метрики (авто-формула) → сразу на «Главную». */
export async function addHomeKpisFromFields(
  datasetCode: string, fields: { field_code: string; field_name: string }[],
): Promise<{ created: { code: string; name: string }[] }> {
  const res = await fetch('/home/kpis/from-fields', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ dataset_code: datasetCode, fields }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

