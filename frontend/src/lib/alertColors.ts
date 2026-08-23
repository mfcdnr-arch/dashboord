/**
 * Цвет уровня порога — из ТЕМЫ, а не из ответа сервера.
 *
 * Сервер считает УРОВЕНЬ (danger/poor/warn/good) — это правило, оно одно на
 * систему. А вот каким цветом уровень нарисован — вопрос темы: раньше вместе с
 * уровнем приезжали жёсткие hex одной палитрой на все темы, и в тёмной теме
 * залитая ячейка таблицы и карточка показателя светились светлым маркером на
 * тёмном фоне.
 *
 * Цвета сервера остаются ЗАПАСНЫМ вариантом: если на бэкенде появится новый
 * уровень, которого фронт ещё не знает, он всё равно будет виден — просто в
 * серверных цветах. Согласованность списка уровней держит тест
 * `backend/tests/test_alert_theme_tokens.py`, который читает `theme.css`.
 */
export interface AlertLook { color: string; bg: string }

/** Уровни, для которых в теме заданы токены (`--alert-<уровень>`). */
export const ALERT_LEVELS = ['danger', 'poor', 'warn', 'good'] as const

export function levelLook(level?: string | null): AlertLook | null {
  if (!level || !(ALERT_LEVELS as readonly string[]).includes(level)) return null
  return { color: `var(--alert-${level})`, bg: `var(--alert-${level}-bg)` }
}

/**
 * Оформление сработавшего порога: тема, если уровень знаком, иначе то, что
 * прислал сервер.
 */
export function alertLook(alert?: { level?: string; color?: string; bg?: string } | null): AlertLook | null {
  if (!alert) return null
  return levelLook(alert.level) || (alert.color && alert.bg ? { color: alert.color, bg: alert.bg } : null)
}
