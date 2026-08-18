// Управление темой: 'light' | 'dark' | 'minek'. Выбор пользователя хранится в
// localStorage; по умолчанию — системная тема (prefers-color-scheme).
// Применяется атрибутом data-theme на <html> (см. theme.css).
import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark' | 'minek'
export const THEMES: Theme[] = ['light', 'dark', 'minek']
const KEY = 'dashbord_theme'

export function getStoredTheme(): Theme | null {
  const v = localStorage.getItem(KEY)
  return v === 'light' || v === 'dark' || v === 'minek' ? v : null
}

export function systemTheme(): Theme {
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function currentTheme(): Theme {
  return getStoredTheme() ?? systemTheme()
}

export function applyTheme(t: Theme): void {
  document.documentElement.setAttribute('data-theme', t)
}

export function setTheme(t: Theme): void {
  localStorage.setItem(KEY, t)
  applyTheme(t)
}

// ── Палитра графиков из токенов темы ─────────────────────────────────────────
// ECharts рисует на canvas/svg и не понимает var(); значения серий читаем из
// CSS-токенов. Дефолты — палитра «Мои Документы» (если токен не задан).
export type ChartColors = {
  palette: string[]; c1: string; prev: string; heat: string[]
  /** Роли на графике: вспомогательная линия (тренд/прогноз) и сигнал (аномалия).
   *  Берутся ОТДЕЛЬНО от палитры серий: это не «ещё одна серия данных», а разное
   *  назначение, и цвет должен говорить именно о назначении. */
  trend: string; signal: string
}

const FALLBACK: ChartColors = {
  palette: ['#e04e39', '#2f7d95', '#d99a2b', '#4f7a5f', '#a5563c', '#7a5ea8', '#8b8178'],
  c1: '#e04e39',
  prev: '#c39367',
  trend: '#6b7f99',
  signal: '#b3261e',
  heat: ['#faf0e9', '#e0b58f', '#e0885f', '#e04e39', '#a5563c'],
}

export function chartColors(): ChartColors {
  const cs = getComputedStyle(document.documentElement)
  const tok = (name: string, fb: string) => cs.getPropertyValue(name).trim() || fb
  const palette = FALLBACK.palette.map((fb, i) => tok(`--chart-${i + 1}`, fb))
  return {
    palette,
    c1: palette[0],
    prev: tok('--chart-prev', FALLBACK.prev),
    trend: tok('--chart-trend', FALLBACK.trend),
    signal: tok('--chart-signal', FALLBACK.signal),
    heat: FALLBACK.heat.map((fb, i) => tok(`--chart-heat-${i + 1}`, fb)),
  }
}

// Хук: перерисовать компонент при смене темы (data-theme на <html>), чтобы
// графики пересобрали option с цветами новой темы.
export function useThemeVersion(): number {
  const [v, setV] = useState(0)
  useEffect(() => {
    const mo = new MutationObserver(() => setV((x) => x + 1))
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => mo.disconnect()
  }, [])
  return v
}

// Применить сразу при загрузке модуля (до рендера React), чтобы не было мигания.
applyTheme(currentTheme())
