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
}

export async function getSetupStatus(): Promise<SetupStatus> {
  const res = await fetch('/system/setup-status', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
