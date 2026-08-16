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

export async function errText(res: Response): Promise<string> {
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
