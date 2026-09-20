// Общий HTTP-слой клиента к Dashboard API: токен, заголовки авторизации,
// единый разбор ошибок. В dev проксируется через Vite на порт 8080.
const TOKEN_KEY = 'dashbord_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t: string): void {
  localStorage.setItem(TOKEN_KEY, t)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function authH(): Record<string, string> {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

// Единый конверт постраничной выдачи (совпадает с бэкендом: total/limit/offset/items).
export interface Page<T> {
  total: number
  limit: number
  offset: number
  items: T[]
}

// Скачивание файла с авторизацией (blob → ссылка → клик). Для выгрузок CSV/XLSX.
export async function downloadFile(url: string, filename: string): Promise<void> {
  const res = await fetch(url, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  const href = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  a.click()
  URL.revokeObjectURL(href)
}

/** Отказ, который человек может обойти осознанно: найден дубль (файла,
 *  дашборда). Отличается от обычной ошибки тем, что интерфейс переспрашивает
 *  и повторяет запрос с признаком «всё равно», а не просто печатает красное. */
export class DuplicateError extends Error {
  constructor(message: string) { super(message); this.name = 'DuplicateError' }
}

/** Событие «сессия кончилась»: его слушает App и возвращает человека на вход. */
export const UNAUTHORIZED_EVENT = 'dashbord:unauthorized'

// Публичные маршруты входа: 401 там означает «неверный логин или пароль», а
// вовсе не «сессия истекла». Сбрасывать на них нечего, и сообщение о неверном
// пароле человек должен увидеть, а не экран входа заново.
const PUBLIC_AUTH = /\/auth\/(login|password-policy|blocked-appeal)\b/

/**
 * Истёкший токен возвращает человека на вход (20.09.2026).
 *
 * Токен живёт 12 часов, а `clearToken` вызывался только при загрузке страницы
 * и по кнопке «Выйти». Открытая со вчера вкладка выглядела рабочей, но каждое
 * действие давало красное «Недействительный токен»; F5 всё лечил, но
 * догадаться об этом человек не мог.
 *
 * Не перезагружаем страницу, а сообщаем приложению событием: токен лежит в
 * состоянии React, поэтому экран входа покажется сам, и введённое в соседних
 * полях не пропадёт от внезапного reload.
 */
function notifyUnauthorized(res: Response): void {
  if (res.status !== 401) return
  if (PUBLIC_AUTH.test(res.url)) return
  if (!getToken()) return          // не вошли — экран входа и так на месте
  clearToken()
  window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
}

export async function errText(res: Response): Promise<string> {
  // Единственная точка, через которую проходят почти все неуспешные ответы
  // (243 проверки `!res.ok` в api/ зовут её). Обёртка над fetch потребовала бы
  // переписать их все — ради одного побочного эффекта это лишний риск.
  notifyUnauthorized(res)
  try {
    const e = await res.json()
    if (typeof e.detail === 'string') return e.detail
    // При 422 FastAPI отдаёт СПИСОК не пройденных проверок, а не строку.
    // Раньше он молча превращался в «Ошибка (422)» — по такому сообщению
    // невозможно понять, что именно не так (реальный случай: название метрики
    // на 204 символа при пределе 200).
    if (Array.isArray(e.detail) && e.detail.length) {
      const parts = e.detail.map((d: { loc?: unknown[]; msg?: string }) => {
        const field = Array.isArray(d.loc) && d.loc.length ? String(d.loc[d.loc.length - 1]) : ''
        return [field, d.msg].filter(Boolean).join(': ')
      })
      return `Проверка не пройдена — ${parts.join('; ')}`
    }
    // Отказы, которые человек может обойти осознанно (найден дубль файла или
    // дашборда), приходят объектом: сообщение + подробности находки. Без этой
    // ветки они превращались бы в бесполезное «Ошибка (409)».
    if (e.detail && typeof e.detail === 'object' && typeof e.detail.message === 'string') {
      return e.detail.message
    }
    return `Ошибка (${res.status})`
  } catch {
    return `Ошибка (${res.status})`
  }
}
