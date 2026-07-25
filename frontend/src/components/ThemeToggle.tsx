import { useState } from 'react'
import { currentTheme, setTheme, type Theme } from '../theme'

// Переключатель светлой/тёмной темы. Показывает иконку целевой темы.
export default function ThemeToggle() {
  const [theme, setThemeState] = useState<Theme>(currentTheme())
  const next: Theme = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      onClick={() => { setTheme(next); setThemeState(next) }}
      title={next === 'dark' ? 'Тёмная тема' : 'Светлая тема'}
      aria-label={next === 'dark' ? 'Включить тёмную тему' : 'Включить светлую тему'}
      style={{
        width: 34, height: 34, borderRadius: 8, border: '1px solid var(--border)',
        background: 'var(--surface)', color: 'var(--text-2)', cursor: 'pointer', fontSize: 16, lineHeight: 1,
      }}>
      {theme === 'dark' ? '☀️' : '🌙'}
    </button>
  )
}
