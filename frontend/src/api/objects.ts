import { authH, DuplicateError, errText } from './http'

export interface Obj {
  id: string
  name: string
  code?: string | null
  description: string | null
  created_at: string
  folders_count?: number
}
export interface Folder {
  id: string
  name: string
  parent_folder_id: string | null
  /** Готовить ли выпуск автоматически: распознавать новый файл и подставлять
   *  разметку прошлого выпуска. Сам выпуск всё равно подтверждает человек. */
  auto_prepare?: boolean
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
  /** Состояние конвейера: new | parsing | failed | ready | attention | needs_markup | released.
   *  Считается на сервере из статуса распознавания, сверки со шаблоном и наличия выпуска. */
  pipeline?: string
  /** Что это значит для человека и что делать дальше. */
  pipeline_hint?: string
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

export async function updateObject(
  objectId: string, patch: { name?: string; code?: string | null; description?: string | null },
): Promise<Obj> {
  const res = await fetch(`/objects/${objectId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function deleteObject(objectId: string): Promise<void> {
  const res = await fetch(`/objects/${objectId}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

export async function updateFolder(
  objectId: string, folderId: string,
  patch: string | { name?: string; auto_prepare?: boolean },
): Promise<Folder> {
  const body = typeof patch === 'string' ? { name: patch } : patch
  const res = await fetch(`/objects/${objectId}/folders/${folderId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authH() },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function deleteFolder(objectId: string, folderId: string): Promise<void> {
  const res = await fetch(`/objects/${objectId}/folders/${folderId}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
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

export async function deleteDocument(folderId: string, documentId: string, withData = false): Promise<void> {
  const q = withData ? '?with_data=true' : ''
  const res = await fetch(`/folders/${folderId}/documents/${documentId}${q}`, { method: 'DELETE', headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
}

// force=true — «всё равно загрузить»: сервер нашёл побайтово такой же файл и
// отказал 409-м, чтобы из дубля не выпустили вторые данные за тот же период.
export async function uploadDocument(folderId: string, file: File, reportingDate: string,
                                     force = false): Promise<void> {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('reporting_period_start', reportingDate)
  if (force) fd.append('force', 'true')
  const res = await fetch(`/folders/${folderId}/documents`, { method: 'POST', headers: authH(), body: fd })
  if (!res.ok) {
    const msg = await errText(res)
    throw res.status === 409 ? new DuplicateError(msg) : new Error(msg)
  }
}



/** Стоит ли предложить собрать дашборд по объекту (данные есть, дашборда нет). */
export interface BuildSuggestion {
  suggest: boolean
  reason: string
  object_name?: string
  releases: number
  periods: number
  first_period?: string | null
  last_period?: string | null
  dataset_codes?: string[]
  dashboards?: number
}

export async function getBuildSuggestion(objectId: string): Promise<BuildSuggestion> {
  const res = await fetch(`/objects/${objectId}/build-suggestion`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
