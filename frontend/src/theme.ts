// Управление темой: 'light' | 'dark'. Выбор пользователя хранится в localStorage;
// по умолчанию — системная тема (prefers-color-scheme). Применяется атрибутом
// data-theme на <html> (см. theme.css).
export type Theme = 'light' | 'dark'
const KEY = 'dashbord_theme'

export function getStoredTheme(): Theme | null {
  const v = localStorage.getItem(KEY)
  return v === 'light' || v === 'dark' ? v : null
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

// Применить сразу при загрузке модуля (до рендера React), чтобы не было мигания.
applyTheme(currentTheme())
