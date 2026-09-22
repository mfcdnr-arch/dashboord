import { authH, errText } from './http'

/** Есть ли в разделе «Статистика услуг» данные вообще. */
export interface DnrStatsReadiness {
  ready: boolean
  departments_with_data: number
  departments_total: number
}

/**
 * Лёгкая проверка «есть ли что показывать» — для пункта меню.
 *
 * Отдельно от `/dnr-stats/overview`: тот читает значения всех выпусков всех
 * ведомств, а меню строится при каждом входе. Пункт, ведущий в раздел со
 * стеной нулей, читается как поломка системы (так и вышло на боевом 22.09.2026,
 * где ведомственных файлов нет вовсе).
 */
export async function getDnrStatsReadiness(): Promise<DnrStatsReadiness> {
  const res = await fetch('/dnr-stats/readiness', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
