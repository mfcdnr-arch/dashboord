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
