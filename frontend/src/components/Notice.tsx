/**
 * Сообщение о результате действия — так, чтобы его услышал диктор экрана.
 *
 * Раньше результат («сохранено», «ошибка», «найдено N») рисовался обычным
 * `<div>` и был виден только глазами: программа чтения с экрана о нём молчала,
 * потому что фокус и содержимое страницы формально не менялись (находка
 * аудита — 0 из 285 сообщений объявлялись). Роль задаётся здесь, в одном
 * месте, чтобы про неё не пришлось помнить в каждой из шести десятков форм.
 *
 * `alert` для ошибки — диктор прерывает чтение: не узнав об ошибке сразу,
 * человек продолжит работу, считая, что действие прошло. `status` для успеха
 * и подсказок — сообщается в паузе, не перебивая.
 */
import type React from 'react'

export type NoticeKind = 'error' | 'ok' | 'warn'

const LOOK: Record<NoticeKind, React.CSSProperties> = {
  error: { background: 'var(--danger-bg)', color: 'var(--danger)' },
  ok: { background: 'var(--success-bg)', color: 'var(--success)' },
  warn: { background: 'var(--warn-bg)', color: 'var(--warn)' },
}

const BASE: React.CSSProperties = { fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }

export default function Notice(
  { kind = 'error', style, children }:
  { kind?: NoticeKind; style?: React.CSSProperties; children: React.ReactNode },
) {
  // style переопределяет вид целиком: у уже существующих форм свои отступы и
  // размеры, и менять их заодно с доступностью значило бы смешивать две правки.
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} style={style || { ...BASE, ...LOOK[kind] }}>
      {children}
    </div>
  )
}
