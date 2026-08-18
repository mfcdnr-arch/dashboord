import { setToken } from './http'

// Аутентификация и здоровье API.

export interface Health {
  status: string
  service: string
  env: string
  db: string
}

export async function getHealth(): Promise<Health> {
  const res = await fetch('/health')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// Парольная политика (для подсказок и предпроверки в UI). См. /auth/password-policy.
export interface PasswordPolicy { min_length: number; require_complexity: boolean }

export async function getPasswordPolicy(): Promise<PasswordPolicy> {
  try {
    const res = await fetch('/auth/password-policy')
    if (res.ok) return await res.json()
  } catch { /* fallback ниже */ }
  return { min_length: 8, require_complexity: true }
}

// Текст-подсказка «каким должен быть пароль».
export function passwordHint(p: PasswordPolicy): string {
  const parts = [`минимум ${p.min_length} символов`]
  if (p.require_complexity) parts.push('буквы и цифры')
  parts.push('не совпадает с логином')
  return 'Пароль: ' + parts.join(', ') + '.'
}

// Клиентская предпроверка (сервер — финальный авторитет). Возвращает ошибку или null.
export function checkPassword(pw: string, p: PasswordPolicy, login?: string): string | null {
  if (pw.length < p.min_length) return `Пароль слишком короткий: минимум ${p.min_length} символов`
  if (p.require_complexity && (!/[a-zA-Zа-яА-Я]/.test(pw) || !/\d/.test(pw))) return 'Пароль должен содержать и буквы, и цифры'
  if (login && pw.toLowerCase() === login.toLowerCase()) return 'Пароль не должен совпадать с логином'
  return null
}

// Ошибка входа с кодом (сейчас только 'account_blocked' — заблокированный
// аккаунт, см. Login.tsx: показывает форму обращения вместо обычной ошибки).
export interface LoginError extends Error { code?: string }

export async function login(username: string, password: string): Promise<string> {
  const body = new URLSearchParams({ username, password })
  const res = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!res.ok) {
    let detail: unknown = null
    try { detail = (await res.json()).detail } catch { /* нет тела/не JSON */ }
    const isObj = detail && typeof detail === 'object'
    const message = isObj ? (detail as { message?: string }).message
      : typeof detail === 'string' ? detail : 'Неверный логин или пароль'
    const err: LoginError = new Error(message || 'Неверный логин или пароль')
    if (isObj) err.code = (detail as { code?: string }).code
    throw err
  }
  const data = await res.json()
  return data.access_token as string
}

export interface Me {
  id: string
  login: string
  full_name: string | null
  must_change_password: boolean
  roles: string[]
  role_names: string[]
  email: string | null
  last_name: string | null
  first_name: string | null
  middle_name: string | null
  department_name: string | null
  created_at: string
  /** Показывать ли раздел «Руководителю» — выдаётся галочкой в карточке сотрудника. */
  show_featured?: boolean
}

export async function getMe(token: string): Promise<Me> {
  const res = await fetch('/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('unauthorized')
  return res.json()
}

// Смена пароля отзывает ВСЕ ранее выданные токены пользователя (сервер пишет
// users.password_changed_at). Поэтому эндпоинт возвращает свежий токен — его
// нужно сразу сохранить, иначе следующий же запрос получит 401.
export async function changePassword(token: string, newPassword: string): Promise<void> {
  const res = await fetch('/auth/change-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ new_password: newPassword }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Ошибка смены пароля')
  }
  const body = await res.json().catch(() => ({}))
  if (body?.access_token) setToken(body.access_token)
}
