// Инструкции, объявления и главная обычного пользователя.
//
// Раздел закрывает то, чего у сотрудника не было: где прочитать, как
// пользоваться системой, и как узнать, что сегодня идут работы на сервере.
import { authH, errText } from './http'

export type Instruction = {
  id: string
  section: string | null
  title: string
  body: string | null
  file_name: string | null
  file_size_bytes: number | null
  position: number
  is_published: boolean
  created_at: string
  updated_at: string
  /** Открывал ли этот человек инструкцию — на этом держится отметка «новое». */
  is_read?: boolean
}

export type Announcement = {
  id: string
  title: string
  body: string
  important: boolean
  starts_at: string
  ends_at: string | null
  is_active: boolean
  created_at: string
}

export type PortalHome = {
  announcements: Announcement[]
  objects: { object_name: string; dashboards: { id: string; name: string; folder_name: string | null; updated_at: string | null }[] }[]
  dashboards_total: number
  fresh_data: { name: string; object_name: string | null; period: string | null; created_at: string }[]
  instructions: { total: number; unread: number }
  show_featured: boolean
  stale_password: boolean
}

export async function getPortalHome(): Promise<PortalHome> {
  const res = await fetch('/home/portal', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function listInstructions(opts: { q?: string; drafts?: boolean } = {}):
  Promise<{ items: Instruction[]; unread: number }> {
  const p = new URLSearchParams()
  if (opts.q) p.set('q', opts.q)
  if (opts.drafts) p.set('drafts', 'true')
  const res = await fetch(`/instructions?${p}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

/** Открытие отмечает инструкцию прочитанной — «новое» гасит сервер, не клиент. */
export async function getInstruction(id: string): Promise<Instruction> {
  const res = await fetch(`/instructions/${id}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createInstruction(data: Partial<Instruction>): Promise<Instruction> {
  const res = await fetch('/instructions', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function updateInstruction(id: string, patch: Partial<Instruction>): Promise<Instruction> {
  const res = await fetch(`/instructions/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function deleteInstruction(id: string): Promise<void> {
  const res = await fetch(`/instructions/${id}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

export async function uploadInstructionFile(id: string, file: File): Promise<Instruction> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`/instructions/${id}/file`, { method: 'POST', headers: authH(), body: fd })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

/** Скачивание идёт через fetch с токеном: прямой ссылке заголовок не передать. */
export async function downloadInstructionFile(id: string, name: string): Promise<void> {
  const res = await fetch(`/instructions/${id}/file`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = name || 'instruction'
  document.body.appendChild(a); a.click(); a.remove()
  URL.revokeObjectURL(url)
}

export async function listAnnouncements(all = false): Promise<Announcement[]> {
  const res = await fetch(`/announcements${all ? '?all=true' : ''}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function createAnnouncement(data: {
  title: string; body: string; important?: boolean; ends_at?: string | null
}): Promise<Announcement> {
  const res = await fetch('/announcements', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function updateAnnouncement(id: string, patch: Partial<Announcement>): Promise<Announcement> {
  const res = await fetch(`/announcements/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function deleteAnnouncement(id: string): Promise<void> {
  const res = await fetch(`/announcements/${id}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
