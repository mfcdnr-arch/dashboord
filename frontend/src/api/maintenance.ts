import { authH, errText } from './http'

// Автопочинка прод-стека (уровень приложения): безопасные идемпотентные
// восстановления — бакет MinIO, связь с Redis. Инфраструктурный авто-рестарт
// упавших контейнеров делает Docker (restart: unless-stopped).
export interface HealResult {
  healthy: boolean
  actions: { name: string; ok: boolean; result: string; latency_ms?: number }[]
  status_before?: string
  status_after?: string
}

export async function healSystem(): Promise<HealResult> {
  const res = await fetch('/maintenance/heal', { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// История heal-событий (ручных и автоматических от сторожевого arq-cron раз в 10 мин).
export interface HealHistoryEntry {
  id: string
  triggered_by: 'manual' | 'auto'
  triggered_by_login: string | null
  status_before: string
  status_after: string
  healthy: boolean
  actions: HealResult['actions']
  created_at: string
}

export async function getHealHistory(limit = 20): Promise<HealHistoryEntry[]> {
  const res = await fetch(`/maintenance/heal-history?limit=${limit}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// Статус бэкапа + «Запустить сейчас» (backup.sh физически выполняется на ХОСТЕ —
// см. backend/app/modules/maintenance/backup_service.py).
export interface BackupSet {
  name: string
  created_at: string
  db_dump_bytes: number | null
  minio_tgz_bytes: number | null
}
export interface BackupStatus {
  sets: BackupSet[]
  pending: boolean
  last_manual_result: { ts: string; ok: boolean; message: string } | null
  watcher_configured: boolean
}

export async function getBackupStatus(): Promise<BackupStatus> {
  const res = await fetch('/maintenance/backup/status', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function runBackupNow(): Promise<{ requested: boolean }> {
  const res = await fetch('/maintenance/backup/run-now', { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// Ретенция (окно хранения данных). Удаление НЕОБРАТИМО, поэтому в UI сначала
// предпросмотр: что именно уйдёт и какие дашборды останутся без данных.
export interface RetentionItem {
  id: string
  code: string
  name: string
  object_name: string | null
  status: string
  period: string | null
  values_count: number
}
export interface RetentionPreview {
  enabled: boolean
  months: number | null
  releases: number
  values: number
  items: RetentionItem[]
  items_limit: number
  affected_dashboards?: string[]
}

export async function getRetentionPreview(months?: number): Promise<RetentionPreview> {
  const q = months ? `?months=${months}` : ''
  const res = await fetch(`/maintenance/retention/preview${q}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function runRetention(months?: number): Promise<{ enabled: boolean; months?: number; deleted_releases: number }> {
  const q = months ? `?months=${months}` : ''
  const res = await fetch(`/maintenance/retention/run${q}`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// Проверка свежести данных вне расписания: рассылает уведомления по объектам,
// где давно не было новых данных.
export async function checkFreshness(staleDays?: number): Promise<{ stale_objects: number; notifications_created: number }> {
  const q = staleDays ? `?stale_days=${staleDays}` : ''
  const res = await fetch(`/maintenance/freshness/check${q}`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

// Статус ежемесячного автоархива дашбордов + запуск вне расписания (идемпотентно).
export interface ArchiveRunStatus {
  last_run: string | null
  recent_count: number
}

export async function getArchiveRunStatus(): Promise<ArchiveRunStatus> {
  const res = await fetch('/maintenance/archive/status', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function runArchiveNow(): Promise<{ archived: number }> {
  const res = await fetch('/maintenance/archive/run-now', { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
