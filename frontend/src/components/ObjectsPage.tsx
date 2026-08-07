import { useEffect, useState, type FormEvent } from 'react'
import {
  createFolder, createObject, deleteFolder, deleteObject, listDocuments, listFolders, listObjects,
  updateFolder, updateObject, uploadDocument,
  type Doc, type Folder, type Obj,
} from '../api'
import { folderLabel, folderTree } from '../lib/folderTree'
import ExtractionPage from './ExtractionPage'
import RowAclEditor from './RowAclEditor'

const DOCS_PAGE = 50

export default function ObjectsPage({ canManage }: { canManage: boolean }) {
  const [objects, setObjects] = useState<Obj[]>([])
  const [obj, setObj] = useState<Obj | null>(null)
  const [folders, setFolders] = useState<Folder[]>([])
  const [folder, setFolder] = useState<Folder | null>(null)
  const [docs, setDocs] = useState<Doc[]>([])
  const [docsTotal, setDocsTotal] = useState(0)
  const [openDoc, setOpenDoc] = useState<Doc | null>(null)
  const [rowAclObj, setRowAclObj] = useState<Obj | null>(null)
  const [editObj, setEditObj] = useState<Obj | null>(null)
  const [editFolder, setEditFolder] = useState<Folder | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [newObj, setNewObj] = useState('')
  const [newFolder, setNewFolder] = useState('')
  const [newFolderParent, setNewFolderParent] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [date, setDate] = useState('')
  const [busy, setBusy] = useState(false)

  function fail(e: unknown) {
    setError((e as Error).message)
  }

  useEffect(() => {
    listObjects().then(setObjects).catch(fail)
  }, [])

  async function openObject(o: Obj) {
    setError(null)
    setObj(o)
    setFolder(null)
    setOpenDoc(null)
    setDocs([])
    setDocsTotal(0)
    setNewFolderParent('')
    try {
      setFolders(await listFolders(o.id))
    } catch (e) {
      fail(e)
    }
  }

  async function loadDocs(folderId: string) {
    const page = await listDocuments(folderId, DOCS_PAGE, 0)
    setDocs(page.items)
    setDocsTotal(page.total)
  }

  async function openFolder(f: Folder) {
    setError(null)
    setFolder(f)
    setOpenDoc(null)
    try {
      await loadDocs(f.id)
    } catch (e) {
      fail(e)
    }
  }

  async function refreshDocs() {
    if (!folder) return
    try {
      await loadDocs(folder.id)
    } catch (e) {
      fail(e)
    }
  }

  async function loadMoreDocs() {
    if (!folder) return
    try {
      const page = await listDocuments(folder.id, DOCS_PAGE, docs.length)
      setDocs((prev) => [...prev, ...page.items])
      setDocsTotal(page.total)
    } catch (e) {
      fail(e)
    }
  }

  async function addObject(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const o = await createObject(newObj.trim())
      setNewObj('')
      setObjects(await listObjects())
      openObject(o)
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  async function addFolder(e: FormEvent) {
    e.preventDefault()
    if (!obj) return
    setBusy(true)
    setError(null)
    try {
      await createFolder(obj.id, newFolder.trim(), newFolderParent || null)
      setNewFolder(''); setNewFolderParent('')
      setFolders(await listFolders(obj.id))
      // В списке объектов показан счётчик папок — держим его в актуальном виде,
      // иначе он разойдётся с отказом удаления («папок: 1» против «папок: 0»).
      setObjects(await listObjects())
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  async function saveObject(vals: Record<string, string>) {
    if (!editObj) return
    setBusy(true)
    setError(null)
    try {
      const upd = await updateObject(editObj.id, {
        name: vals.name.trim(), code: vals.code.trim() || null, description: vals.description.trim() || null,
      })
      setEditObj(null)
      setObjects(await listObjects())
      // Открытый объект показан в «хлебных крошках» и заголовках — обновляем и его.
      if (obj?.id === upd.id) setObj({ ...obj, ...upd })
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  async function removeObject(o: Obj) {
    if (!confirm(`Удалить объект «${o.name}»?\n\nУдаление возможно, только если внутри ничего нет.`)) return
    setBusy(true)
    setError(null)
    try {
      await deleteObject(o.id)
      if (obj?.id === o.id) { setObj(null); setFolder(null); setOpenDoc(null) }
      setObjects(await listObjects())
    } catch (e) {
      fail(e)
      // Отказ означает, что внутри что-то есть — перечитываем счётчики,
      // чтобы список объяснял причину, а не спорил с сообщением об ошибке.
      listObjects().then(setObjects).catch(() => {})
    } finally {
      setBusy(false)
    }
  }

  async function saveFolder(vals: Record<string, string>) {
    if (!obj || !editFolder) return
    setBusy(true)
    setError(null)
    try {
      await updateFolder(obj.id, editFolder.id, vals.name.trim())
      setEditFolder(null)
      setFolders(await listFolders(obj.id))
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  async function removeFolder(f: Folder) {
    if (!obj) return
    if (!confirm(`Удалить папку «${f.name}»?\n\nУдаление возможно, только если внутри ничего нет.`)) return
    setBusy(true)
    setError(null)
    try {
      await deleteFolder(obj.id, f.id)
      if (folder?.id === f.id) setFolder(null)
      setFolders(await listFolders(obj.id))
      setObjects(await listObjects())
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  async function upload(e: FormEvent) {
    e.preventDefault()
    if (!folder || !file || !date) return
    setBusy(true)
    setError(null)
    try {
      await uploadDocument(folder.id, file, date)
      setFile(null)
      setDate('')
      await loadDocs(folder.id)
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, marginBottom: 16 }}>
        <button style={crumb} onClick={() => { setObj(null); setFolder(null); setOpenDoc(null) }}>Объекты</button>
        {obj && <><span style={{ color: 'var(--text-faint)' }}>/</span><button style={crumb} onClick={() => { setFolder(null); setOpenDoc(null) }}>{obj.name}</button></>}
        {folder && <><span style={{ color: 'var(--text-faint)' }}>/</span><button style={crumb} onClick={() => setOpenDoc(null)}>{folder.name}</button></>}
        {openDoc && <><span style={{ color: 'var(--text-faint)' }}>/</span><span>{openDoc.original_filename}</span></>}
      </div>

      {error && <div style={errBox}>{error}</div>}

      {!obj && (
        <Section title="Объекты">
          <form onSubmit={addObject} style={rowForm}>
            <input style={input} placeholder="Название объекта" value={newObj} onChange={(e) => setNewObj(e.target.value)} />
            <button style={btn} disabled={busy || !newObj.trim()}>＋ Объект</button>
          </form>
          <List
            items={objects.map((o) => ({
              id: o.id,
              title: o.name,
              sub: `папок: ${o.folders_count ?? 0}${o.code ? ` · код: ${o.code}` : ''}`,
              onClick: () => openObject(o),
              actions: canManage ? (
                <>
                  <IconBtn title="Переименовать объект" onClick={() => setEditObj(o)}>✏️</IconBtn>
                  <IconBtn title="Удалить объект" danger disabled={busy} onClick={() => removeObject(o)}>🗑</IconBtn>
                </>
              ) : undefined,
            }))}
            empty="Пока нет объектов"
          />
        </Section>
      )}

      {obj && !folder && (
        <Section title={`Папки объекта «${obj.name}»`}>
          <form onSubmit={addFolder} style={rowForm}>
            <input style={input} placeholder="Название папки" value={newFolder} onChange={(e) => setNewFolder(e.target.value)} />
            {folders.length > 0 && (
              <select style={input} value={newFolderParent} onChange={(e) => setNewFolderParent(e.target.value)}
                title="Вложить в существующую папку (необязательно)">
                <option value="">— верхний уровень —</option>
                {folderTree(folders).map((f) => <option key={f.id} value={f.id}>{folderLabel(f)}</option>)}
              </select>
            )}
            <button style={btn} disabled={busy || !newFolder.trim()}>＋ Папка</button>
            {canManage && (
              <button type="button" style={{ ...btn, background: 'var(--accent-weak-bg)', color: 'var(--accent)' }}
                onClick={() => setRowAclObj(obj)} title="Ограничить видимость строк данных по подразделению">
                🔐 Доступ к строкам
              </button>
            )}
          </form>
          <List
            items={folderTree(folders).map((f) => ({
              id: f.id,
              title: folderLabel(f),
              sub: '',
              onClick: () => openFolder(f),
              actions: canManage ? (
                <>
                  <IconBtn title="Переименовать папку" onClick={() => setEditFolder(f)}>✏️</IconBtn>
                  <IconBtn title="Удалить папку" danger disabled={busy} onClick={() => removeFolder(f)}>🗑</IconBtn>
                </>
              ) : undefined,
            }))}
            empty="В объекте пока нет папок"
          />
        </Section>
      )}

      {rowAclObj && <RowAclEditor object={rowAclObj} onClose={() => setRowAclObj(null)} />}

      {editObj && (
        <EditDialog
          title={`Объект «${editObj.name}»`}
          busy={busy}
          fields={[
            { key: 'name', label: 'Название', value: editObj.name },
            { key: 'code', label: 'Код (необязательно)', value: editObj.code ?? '', placeholder: 'например, MFC-01' },
            { key: 'description', label: 'Описание (необязательно)', value: editObj.description ?? '', multiline: true },
          ]}
          onSave={saveObject}
          onClose={() => setEditObj(null)}
        />
      )}

      {editFolder && (
        <EditDialog
          title={`Папка «${editFolder.name}»`}
          busy={busy}
          fields={[{ key: 'name', label: 'Название', value: editFolder.name }]}
          onSave={saveFolder}
          onClose={() => setEditFolder(null)}
        />
      )}

      {folder && openDoc && (
        <ExtractionPage doc={openDoc} canManage={canManage} onBack={() => { setOpenDoc(null); refreshDocs() }} />
      )}

      {folder && !openDoc && (
        <Section title={`Документы папки «${folder.name}»`}>
          <form onSubmit={upload} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16, alignItems: 'center' }}>
            <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <label style={{ fontSize: 13, color: 'var(--text-muted)' }}>Отчётная дата:</label>
            <input style={{ ...input, width: 160 }} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            <button style={btn} disabled={busy || !file || !date}>Загрузить</button>
          </form>
          <List
            items={docs.map((d) => ({ id: d.id, title: d.original_filename, sub: `${d.source_type.toUpperCase()} · ${d.reporting_period_start} · ${fmtSize(d.size)} · ${statusLabel(d.status)}`, onClick: () => setOpenDoc(d) }))}
            empty="В папке пока нет документов"
          />
          {docs.length < docsTotal && (
            <div style={{ textAlign: 'center', marginTop: 12 }}>
              <button style={{ ...btn, background: 'var(--accent-weak-bg)', color: 'var(--accent)' }} onClick={loadMoreDocs}>
                Показать ещё ({docsTotal - docs.length})
              </button>
            </div>
          )}
        </Section>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 style={{ fontSize: 16, margin: '0 0 12px' }}>{title}</h2>
      {children}
    </div>
  )
}

type ListItem = { id: string; title: string; sub: string; onClick?: () => void; actions?: React.ReactNode }

function List({ items, empty }: { items: ListItem[]; empty: string }) {
  if (items.length === 0) return <div style={{ color: 'var(--text-faint)', fontSize: 14, padding: '8px 0' }}>{empty}</div>
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
      {items.map((it, i) => (
        <div
          key={it.id}
          onClick={it.onClick}
          style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, padding: '10px 14px',
            borderTop: i ? '1px solid var(--border-faint)' : 'none', cursor: it.onClick ? 'pointer' : 'default',
          }}
        >
          <span style={{ fontSize: 14 }}>{it.title}</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{it.sub}</span>
            {/* Клик по действию не должен открывать строку. */}
            {it.actions && <span style={{ display: 'flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>{it.actions}</span>}
          </span>
        </div>
      ))}
    </div>
  )
}

function IconBtn(
  { children, title, onClick, danger, disabled }:
  { children: React.ReactNode; title: string; onClick: () => void; danger?: boolean; disabled?: boolean },
) {
  return (
    <button
      type="button" title={title} aria-label={title} disabled={disabled} onClick={onClick}
      style={{
        border: '1px solid var(--border)', borderRadius: 8, background: 'transparent', cursor: disabled ? 'default' : 'pointer',
        fontSize: 13, lineHeight: 1, padding: '5px 8px', opacity: disabled ? 0.5 : 1,
        color: danger ? 'var(--danger)' : 'var(--text-muted)',
      }}
    >
      {children}
    </button>
  )
}

type EditField = { key: string; label: string; value: string; placeholder?: string; multiline?: boolean }

/** Диалог правки названия/кода/описания — общий для объекта и папки. */
function EditDialog(
  { title, fields, busy, onSave, onClose }:
  { title: string; fields: EditField[]; busy: boolean; onSave: (v: Record<string, string>) => void; onClose: () => void },
) {
  const [vals, setVals] = useState<Record<string, string>>(
    () => Object.fromEntries(fields.map((f) => [f.key, f.value])),
  )
  const nameEmpty = !(vals.name ?? '').trim()

  return (
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>{title}</h3>
        {fields.map((f) => (
          <label key={f.key} style={{ display: 'block', marginBottom: 12 }}>
            <span style={{ display: 'block', fontSize: 13, color: 'var(--text-muted)', marginBottom: 4 }}>{f.label}</span>
            {f.multiline ? (
              <textarea
                style={{ ...input, width: '100%', height: 72, padding: 8, resize: 'vertical' }}
                value={vals[f.key]} placeholder={f.placeholder}
                onChange={(e) => setVals((p) => ({ ...p, [f.key]: e.target.value }))}
              />
            ) : (
              <input
                style={{ ...input, width: '100%' }} value={vals[f.key]} placeholder={f.placeholder}
                onChange={(e) => setVals((p) => ({ ...p, [f.key]: e.target.value }))}
              />
            )}
          </label>
        ))}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 18 }}>
          <button type="button" style={{ ...btn, background: 'var(--accent-weak-bg)', color: 'var(--accent)' }} onClick={onClose}>
            Отмена
          </button>
          <button type="button" style={btn} disabled={busy || nameEmpty} onClick={() => onSave(vals)}>
            Сохранить
          </button>
        </div>
      </div>
    </div>
  )
}

const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60, padding: 20 }
const dialog: React.CSSProperties = { background: 'var(--surface)', borderRadius: 14, padding: 22, width: 480, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }

function fmtSize(n: number | null): string {
  if (n == null) return '—'
  if (n < 1024) return `${n} Б`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} КБ`
  return `${(n / 1024 / 1024).toFixed(1)} МБ`
}

function statusLabel(s: string): string {
  const m: Record<string, string> = {
    uploaded: 'загружен', parsing: 'распознаётся', extracted: 'распознан',
    period_pending: 'ожидает период', confirmed: 'подтверждён', mapped: 'размечен',
    rejected: 'отклонён', released: 'опубликован',
  }
  return m[s] || s
}

const crumb: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 14, padding: 0 }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14 }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
const rowForm: React.CSSProperties = { display: 'flex', gap: 8, marginBottom: 16 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
