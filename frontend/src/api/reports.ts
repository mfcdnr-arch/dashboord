import { authH, downloadFile, errText } from './http'

/** Период отчёта (п. 4): один диапазон на все отчёты раздела и на выгрузку —
 *  иначе файл разошёлся бы с тем, что человек видит на экране. */
export interface ReportPeriod { from?: string; to?: string }
export interface PeriodInfo {
  from: string; to: string; days: number; label: string
  /** Запрошенный период был шире предела и обрезан — экран обязан это сказать. */
  clamped?: boolean
}
function pq(p: ReportPeriod = {}): string {
  const q = new URLSearchParams()
  if (p.from) q.set('from', p.from)
  if (p.to) q.set('to', p.to)
  const s = q.toString()
  return s ? `?${s}` : ''
}

// --- Отчёты (волна B) ---
export interface Gauge { percent: number; level: 'good' | 'warn' | 'danger'; used?: number; total?: number }
export interface SystemReport {
  status?: 'ok' | 'degraded'
  cpu: Gauge; memory: Gauge; disk: Gauge
  load: number[] | null; cores: number; uptime_sec: number; db_size: number | null
  services: { name: string; ok: boolean; latency_ms?: number }[]
}
export interface AttendanceReport {
  period?: PeriodInfo
  totals: { logins: number; failed: number; active_users: number }
  per_day: { day: string; logins: number; failed: number }[]
  top_users: { login: string; logins: number }[]
}
export async function getSystemReport(): Promise<SystemReport> {
  const res = await fetch('/reports/system', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function getAttendanceReport(p: ReportPeriod = {}): Promise<AttendanceReport> {
  const res = await fetch(`/reports/attendance${pq(p)}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export interface PopularityReport {
  days: number
  period?: PeriodInfo
  totals: { views: number; viewers: number }
  top_dashboards: { dashboard_id: string; name: string; views: number; viewers: number; last_view: string | null }[]
}
export async function getPopularityReport(p: ReportPeriod = {}): Promise<PopularityReport> {
  const res = await fetch(`/reports/popularity${pq(p)}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export interface DashboardViewers {
  dashboard_id: string
  name: string
  days: number
  viewers: { who: string; login: string; views: number; last_view: string | null }[]
}
export async function getDashboardViewers(dashboardId: string, p: ReportPeriod = {}): Promise<DashboardViewers> {
  const q = pq(p).replace('?', '&')
  const res = await fetch(`/reports/popularity/viewers?dashboard_id=${encodeURIComponent(dashboardId)}${q}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export interface ModerationReport {
  days: number
  period?: PeriodInfo
  pending: number
  totals: { approved: number; returned: number; cancelled: number; avg_hours: number | null; return_rate: number | null }
  top_reasons: { label: string; count: number }[]
  top_reviewers: { login: string; approved: number; returned: number }[]
}
export async function getModerationReport(p: ReportPeriod = {}): Promise<ModerationReport> {
  const res = await fetch(`/reports/moderation${pq(p)}`, { headers: authH() })
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


// --- Выгрузка отчёта и очистка истории (п. 4 списка заказчика) ---
export type ReportKind = 'attendance' | 'popularity' | 'moderation' | 'data-quality'

export function exportReport(kind: ReportKind, fmt: 'csv' | 'xlsx', p: ReportPeriod = {}): Promise<void> {
  return downloadFile(`/reports/${kind}/export.${fmt}${pq(p)}`, `report-${kind}.${fmt}`)
}

export interface HistoryStats {
  older_than_days: number
  kinds: { kind: string; label: string; total: number; removable: number }[]
  /** Сколько значимых событий аудита НЕ будет удалено ни при каких настройках. */
  protected_audit_events: number
}
export async function getHistoryStats(olderThanDays: number): Promise<HistoryStats> {
  const res = await fetch(`/reports/history?older_than_days=${olderThanDays}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function purgeHistory(kinds: string[], olderThanDays: number): Promise<{
  older_than_days: number; removed: Record<string, number>; total: number
}> {
  const res = await fetch('/reports/history/purge', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ kinds, older_than_days: olderThanDays }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

/** Разбор одного дня графика посещаемости: кто заходил и сколько раз. */
export interface AttendanceDay {
  date: string
  label: string
  totals: { logins: number; failed: number; people: number }
  users: {
    user_id: string; login: string; who: string
    logins: number; failed: number; first_at: string | null; last_at: string | null
  }[]
  /** Записи без ссылки на пользователя: логин, которого в системе нет, ЛИБО
   *  сотрудник, чью учётку удалили (история входов её переживает). Различить
   *  по данным нельзя, поэтому показываем успехи и неудачи раздельно. */
  orphan_logins: { login: string; logins: number; failed: number; ips: number; last_at: string | null }[]
}
export async function getAttendanceDay(day: string): Promise<AttendanceDay> {
  const res = await fetch(`/reports/attendance/day?date=${encodeURIComponent(day)}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
