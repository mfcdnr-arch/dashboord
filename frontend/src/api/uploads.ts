import { authH, errText } from './http'

// --- Общая зона загрузки (шаг ⑤) ---
// Файл кладут, не выбирая папку: систему просят узнать форму по отпечатку
// структуры и разложить файл самой. Пока форма незнакома, файл ждёт человека
// во «Входящих» — чужая папка означала бы неверные цифры на дашборде.

export interface UploadResult {
  id: string
  extraction_job_id: string | null
  original_filename: string
  reporting_period_start: string | null
  /** Дату вычитали из имени файла, а не спросили у человека. */
  period_guessed?: boolean
}

export interface JournalItem {
  id: string
  filename: string
  period: string | null
  uploaded_at: string | null
  uploaded_by: string | null
  folder_name: string | null
  object_name: string | null
  in_inbox: boolean
  routed_by: 'template' | 'manual' | null
  routed_note: string | null
  state: string
  released: boolean
}

export async function uploadToInbox(file: File, period?: string, force = false): Promise<UploadResult> {
  const fd = new FormData()
  fd.append('file', file)
  if (period) fd.append('reporting_period_start', period)
  if (force) fd.append('force', 'true')
  const res = await fetch('/uploads', { method: 'POST', headers: authH(), body: fd })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function uploadJournal(limit = 50): Promise<{ items: JournalItem[] }> {
  const res = await fetch(`/uploads?limit=${limit}`, { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}

export async function routeUpload(documentId: string, folderId: string): Promise<void> {
  const fd = new FormData()
  fd.append('folder_id', folderId)
  const res = await fetch(`/uploads/${documentId}/route`, { method: 'POST', headers: authH(), body: fd })
  if (!res.ok) throw new Error(await errText(res))
}

export interface KnownForm {
  object_id: string
  object_name: string
  dataset_code: string | null
  folder_name: string | null
  example_filename: string | null
  row_count: number | null
  periods_loaded: number
  updated_at: string | null
}

/** Формы, которые «📥 Загрузка» уже узнаёт сама по структуре — подсказка перед перетаскиванием файла. */
export async function knownForms(): Promise<{ items: KnownForm[] }> {
  const res = await fetch('/uploads/known-forms', { headers: authH() })
  if (!res.ok) throw new Error(await errText(res))
  return res.json()
}
