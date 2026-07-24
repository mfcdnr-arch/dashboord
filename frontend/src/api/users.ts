import { authH, errText } from './http'

// --- Модуль «Пользователи» (волна B) ---
export interface Department { id: string; name: string; users: number }
export interface Role { id: string; code: string; name: string }
export interface AppUser {
  id: string; login: string; full_name: string | null
  last_name: string | null; first_name: string | null; middle_name: string | null
  email: string | null; is_active: boolean; must_change_password: boolean
  department_id: string | null; department: string | null; roles: string[]; created_at: string
}
export async function listDepartments(): Promise<Department[]> {
  const res = await fetch('/departments', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function createDepartment(name: string): Promise<Department> {
  const res = await fetch('/departments', { method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify({ name }) })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function deleteDepartment(id: string): Promise<void> {
  const res = await fetch(`/departments/${id}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
export async function listRoles(): Promise<Role[]> {
  const res = await fetch('/roles', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function listUsers(): Promise<AppUser[]> {
  const res = await fetch('/users', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export interface UserInput {
  login: string; password: string; last_name?: string; first_name?: string; middle_name?: string
  email?: string; department_id?: string; role_ids: string[]
}
export async function createUser(body: UserInput): Promise<{ id: string; login: string }> {
  const res = await fetch('/users', { method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify(body) })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function updateUser(id: string, patch: {
  last_name?: string; first_name?: string; middle_name?: string; email?: string; department_id?: string | null; role_ids?: string[]
}): Promise<void> {
  const res = await fetch(`/users/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify(patch) })
  if (!res.ok) throw new Error(await errText(res))
}
export async function setUserActive(id: string, is_active: boolean): Promise<void> {
  const res = await fetch(`/users/${id}/active`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify({ is_active }) })
  if (!res.ok) throw new Error(await errText(res))
}
export async function resetUserPassword(id: string, password: string): Promise<void> {
  const res = await fetch(`/users/${id}/reset-password`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify({ password }) })
  if (!res.ok) throw new Error(await errText(res))
}

export interface LoginEventsReport {
  summary: { login: string; full_name: string | null; is_active: boolean; logins: number; failed: number; last_login: string | null }[]
  recent: { login: string; full_name: string | null; ip: string | null; success: boolean; created_at: string }[]
}
export async function getLoginEvents(): Promise<LoginEventsReport> {
  const res = await fetch('/login-events', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

