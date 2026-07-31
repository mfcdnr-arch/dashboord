import { authH, errText } from './http'

// Статус первичной настройки — счётчики готовности системы + признак «свежей
// установки». Используется мастером первичной настройки (SetupWizard).
export interface SetupStatus {
  departments: number
  users: number
  objects: number
  documents: number
  datasets: number
  dashboards: number
  fresh_install: boolean
  setup_dismissed: boolean
}

export async function getSetupStatus(): Promise<SetupStatus> {
  const res = await fetch('/system/setup-status', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// Серверный флаг «мастер настройки закрыт/завершён» (переживает смену браузера).
export async function dismissSetup(): Promise<void> {
  const res = await fetch('/system/setup-dismiss', { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

// Графические настройки-пороги (взамен правки .env + рестарт).
export interface SystemThresholds {
  login_max_attempts: number
  login_lockout_minutes: number
  cpu_warn: number
  cpu_crit: number
  ram_warn: number
  ram_crit: number
  disk_warn: number
  disk_crit: number
}
export interface OrgThresholds {
  stale_days: number
  retention_months: number
}
export interface AllSettings {
  system: SystemThresholds
  org: OrgThresholds
}

export async function getSettings(): Promise<AllSettings> {
  const res = await fetch('/system/settings', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function updateSystemSettings(patch: Partial<SystemThresholds>): Promise<SystemThresholds> {
  const res = await fetch('/system/settings/system', {
    method: 'PUT', headers: { ...authH(), 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function updateOrgSettings(patch: Partial<OrgThresholds>): Promise<OrgThresholds> {
  const res = await fetch('/system/settings/org', {
    method: 'PUT', headers: { ...authH(), 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// Просмотр логов сервиса через Loki (уже есть в мониторинг-стеке проекта).
export interface LogLine {
  ts_ns: number
  line: string
}
export interface LogsResult {
  available: boolean
  services: string[]
  lines: LogLine[]
  hint?: string
}

export async function getLogs(service: string, minutes = 30, limit = 200, q?: string): Promise<LogsResult> {
  const params = new URLSearchParams({ service, minutes: String(minutes), limit: String(limit) })
  if (q) params.set('q', q)
  const res = await fetch(`/system/logs?${params}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
