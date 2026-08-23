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
  /** Когда обращение впервые открыл кто-то из администрации (волна п.15):
   *  до первого ответа это единственный признак, что жалобу заметили. */
  first_seen_at: string | null
  /** Сколько часов ждёт ОТВЕТА (только у открытых; у отвеченных и закрытых
   *  ожидание кончилось, и растущая цифра означала бы несуществующую проблему). */
  waiting_hours: number | null
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
  /** wrong_value|no_data|… — жалоба с виджета; access_request — запрос доступа. */
  kind: string
  widget_id?: string
  widget_name?: string
  dashboard_id?: string
  dashboard_name?: string
  page_id?: string | null
  page_title?: string | null
  /** Ответственный за показатель (п. 11): кому адресована жалоба. */
  owner_id?: string | null
  owner_name?: string | null
  metric_name?: string | null
}

export interface AppealDetail {
  id: string
  subject: string | null
  status: 'open' | 'answered' | 'closed'
  created_at: string
  updated_at: string
  author: string
  /** id автора — администратору, чтобы из запроса доступа открыть карточку
   *  доступа именно этого сотрудника. */
  author_id: string
  context: AppealContext | null
  first_seen_at: string | null
  first_seen_by: string | null
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

/** «Мне нужен отчёт, которого я не вижу» (п. 15). Список недоступных отчётов
 *  человеку НЕ показывается — даже названия говорят, какие показатели за кем
 *  закреплены; он называет нужный отчёт сам. */
export async function requestDashboardAccess(wanted: string): Promise<{ id: string }> {
  const res = await fetch('/appeals/access-request', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ wanted }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function listMyAppeals(limit = 50, offset = 0): Promise<Page<AppealSummary>> {
  const res = await fetch(`/appeals/mine?limit=${limit}&offset=${offset}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

/** Список для staff: вместе со сроком ответа, заявленным организацией
 *  («Настройки»), — по нему в списке видно, что залежалось. */
export async function listAppeals(status?: string, limit = 50, offset = 0): Promise<Page<AppealSummary> & { response_hours: number }> {
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
