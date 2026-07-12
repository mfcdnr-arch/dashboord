// Клиент к Dashboard API (в dev проксируется через Vite на порт 8080).

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

export async function login(username: string, password: string): Promise<string> {
  const body = new URLSearchParams({ username, password })
  const res = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!res.ok) throw new Error('Неверный логин или пароль')
  const data = await res.json()
  return data.access_token as string
}

export interface Me {
  id: string
  login: string
  full_name: string | null
  must_change_password: boolean
  roles: string[]
}

export async function getMe(token: string): Promise<Me> {
  const res = await fetch('/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('unauthorized')
  return res.json()
}

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
}

// --- Объекты / папки / документы ---

function authH(): Record<string, string> {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

async function errText(res: Response): Promise<string> {
  try {
    const e = await res.json()
    return typeof e.detail === 'string' ? e.detail : `Ошибка (${res.status})`
  } catch {
    return `Ошибка (${res.status})`
  }
}

export interface Obj {
  id: string
  name: string
  description: string | null
  created_at: string
  folders_count?: number
}
export interface Folder {
  id: string
  name: string
  parent_folder_id: string | null
  created_at: string
}
export interface Doc {
  id: string
  original_filename: string
  source_type: string
  status: string
  reporting_period_start: string
  reporting_period_end: string | null
  size: number | null
  created_at: string
}

export async function listObjects(): Promise<Obj[]> {
  const res = await fetch('/objects', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createObject(name: string, description?: string): Promise<Obj> {
  const res = await fetch('/objects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ name, description: description || null }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function listFolders(objectId: string): Promise<Folder[]> {
  const res = await fetch(`/objects/${objectId}/folders`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createFolder(objectId: string, name: string): Promise<Folder> {
  const res = await fetch(`/objects/${objectId}/folders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ name }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function listDocuments(folderId: string): Promise<Doc[]> {
  const res = await fetch(`/folders/${folderId}/documents`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function uploadDocument(folderId: string, file: File, reportingDate: string): Promise<void> {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('reporting_period_start', reportingDate)
  const res = await fetch(`/folders/${folderId}/documents`, { method: 'POST', headers: authH(), body: fd })
  if (!res.ok) throw new Error(await errText(res))
}
