import { authH, errText } from './http'

// --- Отчёты (волна B) ---
export interface Gauge { percent: number; level: 'good' | 'warn' | 'danger'; used?: number; total?: number }
export interface SystemReport {
  cpu: Gauge; memory: Gauge; disk: Gauge
  load: number[] | null; cores: number; uptime_sec: number; db_size: number | null
  services: { name: string; ok: boolean }[]
}
export interface AttendanceReport {
  totals: { logins: number; failed: number; active_users: number }
  per_day: { day: string; logins: number; failed: number }[]
  top_users: { login: string; logins: number }[]
}
export async function getSystemReport(): Promise<SystemReport> {
  const res = await fetch('/reports/system', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function getAttendanceReport(): Promise<AttendanceReport> {
  const res = await fetch('/reports/attendance', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export interface PopularityReport {
  days: number
  totals: { views: number; viewers: number }
  top_dashboards: { dashboard_id: string; name: string; views: number; viewers: number; last_view: string | null }[]
}
export async function getPopularityReport(): Promise<PopularityReport> {
  const res = await fetch('/reports/popularity', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export interface DashboardViewers {
  dashboard_id: string
  name: string
  days: number
  viewers: { who: string; login: string; views: number; last_view: string | null }[]
}
export async function getDashboardViewers(dashboardId: string): Promise<DashboardViewers> {
  const res = await fetch(`/reports/popularity/viewers?dashboard_id=${encodeURIComponent(dashboardId)}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export interface ModerationReport {
  days: number
  pending: number
  totals: { approved: number; returned: number; cancelled: number; avg_hours: number | null; return_rate: number | null }
  top_reasons: { label: string; count: number }[]
  top_reviewers: { login: string; approved: number; returned: number }[]
}
export async function getModerationReport(): Promise<ModerationReport> {
  const res = await fetch('/reports/moderation', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export interface DataQualityReport {
  objects: { name: string; datasets: number; last_period: string | null; last_update: string | null; status: string }[]
  no_data: string[]
  metric_errors: { code: string; name: string; error: string }[]
  metrics_total: number
}
export interface BusinessReport {
  metrics: { code: string; name: string; unit: string | null; value: number | null; error: string | null }[]
  alerts: { widget_name: string; dashboard_name: string; level: 'warn' | 'danger'; label: string; measure: number | null }[]
}
export async function getDataQualityReport(): Promise<DataQualityReport> {
  const res = await fetch('/reports/data-quality', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function getBusinessReport(): Promise<BusinessReport> {
  const res = await fetch('/reports/business', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
