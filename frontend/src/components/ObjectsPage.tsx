import { useEffect, useState, type FormEvent } from 'react'
import {
  createFolder, createObject, listDocuments, listFolders, listObjects, uploadDocument,
  type Doc, type Folder, type Obj,
} from '../api'
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
  const [error, setError] = useState<string | null>(null)

  const [newObj, setNewObj] = useState('')
  const [newFolder, setNewFolder] = useState('')
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
      await createFolder(obj.id, newFolder.trim())
      setNewFolder('')
      setFolders(await listFolders(obj.id))
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
        {obj && <><span style={{ color: '#9aa4b2' }}>/</span><button style={crumb} onClick={() => { setFolder(null); setOpenDoc(null) }}>{obj.name}</button></>}
        {folder && <><span style={{ color: '#9aa4b2' }}>/</span><button style={crumb} onClick={() => setOpenDoc(null)}>{folder.name}</button></>}
        {openDoc && <><span style={{ color: '#9aa4b2' }}>/</span><span>{openDoc.original_filename}</span></>}
      </div>

      {error && <div style={errBox}>{error}</div>}

      {!obj && (
        <Section title="Объекты">
          <form onSubmit={addObject} style={rowForm}>
            <input style={input} placeholder="Название объекта" value={newObj} onChange={(e) => setNewObj(e.target.value)} />
            <button style={btn} disabled={busy || !newObj.trim()}>＋ Объект</button>
          </form>
          <List
            items={objects.map((o) => ({ id: o.id, title: o.name, sub: `папок: ${o.folders_count ?? 0}`, onClick: () => openObject(o) }))}
            empty="Пока нет объектов"
          />
        </Section>
      )}

      {obj && !folder && (
        <Section title={`Папки объекта «${obj.name}»`}>
          <form onSubmit={addFolder} style={rowForm}>
            <input style={input} placeholder="Название папки" value={newFolder} onChange={(e) => setNewFolder(e.target.value)} />
            <button style={btn} disabled={busy || !newFolder.trim()}>＋ Папка</button>
            {canManage && (
              <button type="button" style={{ ...btn, background: '#eef2f8', color: '#2f5496' }}
                onClick={() => setRowAclObj(obj)} title="Ограничить видимость строк данных по подразделению">
                🔐 Доступ к строкам
              </button>
            )}
          </form>
          <List
            items={folders.map((f) => ({ id: f.id, title: f.name, sub: '', onClick: () => openFolder(f) }))}
            empty="В объекте пока нет папок"
          />
        </Section>
      )}

      {rowAclObj && <RowAclEditor object={rowAclObj} onClose={() => setRowAclObj(null)} />}

      {folder && openDoc && (
        <ExtractionPage doc={openDoc} canManage={canManage} onBack={() => { setOpenDoc(null); refreshDocs() }} />
      )}

      {folder && !openDoc && (
        <Section title={`Документы папки «${folder.name}»`}>
          <form onSubmit={upload} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16, alignItems: 'center' }}>
            <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <label style={{ fontSize: 13, color: '#6b7280' }}>Отчётная дата:</label>
            <input style={{ ...input, width: 160 }} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            <button style={btn} disabled={busy || !file || !date}>Загрузить</button>
          </form>
          <List
            items={docs.map((d) => ({ id: d.id, title: d.original_filename, sub: `${d.source_type.toUpperCase()} · ${d.reporting_period_start} · ${fmtSize(d.size)} · ${statusLabel(d.status)}`, onClick: () => setOpenDoc(d) }))}
            empty="В папке пока нет документов"
          />
          {docs.length < docsTotal && (
            <div style={{ textAlign: 'center', marginTop: 12 }}>
              <button style={{ ...btn, background: '#eef2f8', color: '#2f5496' }} onClick={loadMoreDocs}>
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

function List({ items, empty }: { items: { id: string; title: string; sub: string; onClick?: () => void }[]; empty: string }) {
  if (items.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 14, padding: '8px 0' }}>{empty}</div>
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 12, overflow: 'hidden' }}>
      {items.map((it, i) => (
        <div
          key={it.id}
          onClick={it.onClick}
          style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px',
            borderTop: i ? '1px solid #f0f0f0' : 'none', cursor: it.onClick ? 'pointer' : 'default',
          }}
        >
          <span style={{ fontSize: 14 }}>{it.title}</span>
          <span style={{ fontSize: 12, color: '#6b7280' }}>{it.sub}</span>
        </div>
      ))}
    </div>
  )
}

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

const crumb: React.CSSProperties = { border: 'none', background: 'none', color: '#2f5496', cursor: 'pointer', fontSize: 14, padding: 0 }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14 }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: '#2f5496', color: '#fff', fontSize: 14, cursor: 'pointer' }
const rowForm: React.CSSProperties = { display: 'flex', gap: 8, marginBottom: 16 }
const errBox: React.CSSProperties = { background: '#fcebeb', color: '#a32d2d', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
