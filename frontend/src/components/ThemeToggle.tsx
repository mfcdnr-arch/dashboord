import { useState } from 'react'
import { currentTheme, setTheme, THEMES, type Theme } from '../theme'

// Переключатель тем по кругу: светлая → тёмная → «МинЭк» → светлая.
// Показывает иконку СЛЕДУЮЩЕЙ темы (что будет по клику).
const META: Record<Theme, { icon: string; name: string }> = {
  light: { icon: '☀️', name: 'Светлая тема' },
  dark: { icon: '🌙', name: 'Тёмная тема' },
  minek: { icon: '🏛️', name: 'Тема «МинЭк ДНР» (сине-золотая)' },
}

export default function ThemeToggle() {
  const [theme, setThemeState] = useState<Theme>(currentTheme())
  const next: Theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length]
  return (
    <button
      onClick={() => { setTheme(next); setThemeState(next) }}
      title={`Сейчас: ${META[theme].name}. Нажмите — ${META[next].name.toLowerCase()}`}
      aria-label={`Включить: ${META[next].name}`}
      style={{
        width: 34, height: 34, borderRadius: 8, border: '1px solid var(--border)',
        background: 'var(--surface)', color: 'var(--text-2)', cursor: 'pointer', fontSize: 16, lineHeight: 1,
      }}>
      {META[next].icon}
    </button>
  )
}
