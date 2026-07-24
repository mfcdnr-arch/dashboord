import { authH, errText } from './http'

// --- Справочники: услуги + служебные документы ---
export interface Service { id: string; code: string; name: string; category: string | null; description: string | null; is_active: boolean; created_at: string }
export interface RefDoc { id: string; title: string; description: string | null; url: string | null; created_at: string }

export async function listServices(): Promise<Service[]> {
  const res = await fetch('/catalog/services', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function createService(body: { code: string; name: string; category?: string | null; description?: string | null }): Promise<Service> {
  const res = await fetch('/catalog/services', { method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify(body) })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function updateService(id: string, patch: { name?: string; category?: string | null; description?: string | null; is_active?: boolean }): Promise<Service> {
  const res = await fetch(`/catalog/services/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify(patch) })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function deleteService(id: string): Promise<void> {
  const res = await fetch(`/catalog/services/${id}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}
export async function listRefDocs(): Promise<RefDoc[]> {
  const res = await fetch('/catalog/reference-docs', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function createRefDoc(body: { title: string; description?: string | null; url?: string | null }): Promise<RefDoc> {
  const res = await fetch('/catalog/reference-docs', { method: 'POST', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify(body) })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function deleteRefDoc(id: string): Promise<void> {
  const res = await fetch(`/catalog/reference-docs/${id}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

