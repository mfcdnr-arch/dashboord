// Обращения пользователей к администратору/модератору (волна C).
import { authH, errText, type Page } from './http'

export interface AppealSummary {
  id: string
  subject: string | null
  status: 'open' | 'answered' | 'closed'
  created_at: string
  updated_at: string
  last_message: string | null
  last_is_staff: boolean | null
  author: string | null
}

export interface AppealMessage {
  id: string
  is_staff: boolean
  body: string
  created_at: string
  author: string
}

/** Откуда пришла жалоба, если её отправили кнопкой с виджета: даёт в карточке
 *  обращения переход к самому отчёту, а не только рассказ о нём. У обычных
 *  обращений (из кабинета, от заблокированной учётки) контекста нет. */
export interface AppealContext {
  kind: string
  widget_id: string
  widget_name: string
  dashboard_id: string
  dashboard_name: string
  page_id: string | null
  page_title: string | null
}

export interface AppealDetail {
  id: string
  subject: string | null
  status: 'open' | 'answered' | 'closed'
  created_at: string
  updated_at: string
  author: string
  context: AppealContext | null
  messages: AppealMessage[]
}

export async function createAppeal(subject: string, body: string): Promise<{ id: string; created_at: string }> {
  const res = await fetch('/appeals', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ subject: subject || null, body }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function listMyAppeals(limit = 50, offset = 0): Promise<Page<AppealSummary>> {
  const res = await fetch(`/appeals/mine?limit=${limit}&offset=${offset}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function listAppeals(status?: string, limit = 50, offset = 0): Promise<Page<AppealSummary>> {
  const q = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (status) q.set('status', status)
  const res = await fetch(`/appeals?${q}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function getAppealsStats(): Promise<{ open: number }> {
  const res = await fetch('/appeals/stats', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function getAppeal(id: string): Promise<AppealDetail> {
  const res = await fetch(`/appeals/${id}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function addAppealMessage(id: string, body: string): Promise<{ id: string; status: string }> {
  const res = await fetch(`/appeals/${id}/messages`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ body }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function closeAppeal(id: string): Promise<void> {
  const res = await fetch(`/appeals/${id}/close`, { method: 'POST', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

// Заблокированный аккаунт: без токена (войти не может).
export async function submitBlockedAppeal(login: string, message: string): Promise<void> {
  const res = await fetch('/auth/blocked-appeal', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login, message }),
  })
  if (!res.ok) throw new Error(await errText(res))
}
