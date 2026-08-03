import { authH, errText } from './http'

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
  version_id: string | null
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

export async function createFolder(objectId: string, name: string, parentFolderId?: string | null): Promise<Folder> {
  const res = await fetch(`/objects/${objectId}/folders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify({ name, parent_folder_id: parentFolderId || null }),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export interface DocPage {
  total: number
  limit: number
  offset: number
  items: Doc[]
}

// --- Row-level RLS: доступ к строкам данных объекта по подразделению ---
export interface RowAclDept { id: string; name: string; row_labels: string[] }
export interface RowAcl { enabled: boolean; row_labels: string[]; departments: RowAclDept[] }
export async function getRowAcl(objectId: string): Promise<RowAcl> {
  const res = await fetch(`/objects/${objectId}/row-acl`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
export async function setRowAcl(objectId: string, departmentId: string, rowLabels: string[]): Promise<void> {
  const res = await fetch(`/objects/${objectId}/row-acl/${departmentId}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json', ...authH() }, body: JSON.stringify({ row_labels: rowLabels }),
  })
  if (!res.ok) throw new Error(await errText(res))
}

export async function listDocuments(folderId: string, limit = 50, offset = 0): Promise<DocPage> {
  const res = await fetch(`/folders/${folderId}/documents?limit=${limit}&offset=${offset}`, { headers: authH() })
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

