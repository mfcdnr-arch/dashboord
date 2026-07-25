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

export async function errText(res: Response): Promise<string> {
  try {
    const e = await res.json()
    return typeof e.detail === 'string' ? e.detail : `Ошибка (${res.status})`
  } catch {
    return `Ошибка (${res.status})`
  }
}
