import { authH, errText } from './http'

// Автопочинка прод-стека (уровень приложения): безопасные идемпотентные
// восстановления — бакет MinIO, связь с Redis. Инфраструктурный авто-рестарт
// упавших контейнеров делает Docker (restart: unless-stopped).
export interface HealResult {
  healthy: boolean
  actions: { name: string; ok: boolean; result: string; latency_ms?: number }[]
}

export async function healSystem(): Promise<HealResult> {
  const res = await fetch('/maintenance/heal', { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
