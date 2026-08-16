import { useEffect, useState, type FormEvent } from 'react'
import {
  createFolder, createObject, deleteDocument, deleteFolder, deleteObject, listDocuments, listFolders,
  listObjects, updateFolder, updateObject, uploadDocument,
  DuplicateError,
  type Doc, type Folder, type Obj,
} from '../api'
import { folderLabel, folderTree } from '../lib/folderTree'
import ExtractionPage from './ExtractionPage'
import RowAclEditor from './RowAclEditor'
import { ConfirmDialog, useConfirm } from './dashboards/ConfirmDialog'
import AutoBuildWizard from './dashboards/AutoBuildWizard'
import { getBuildSuggestion, type BuildSuggestion } from '../api/objects'
import { listDashboards, type Dashboard } from '../api/dashboards'

const DOCS_PAGE = 50

/** Отчётные даты — по-русски: ДД.ММ.ГГГГ. */
const ruDate = (iso?: string | null): string =>
  (iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.split('-').reverse().join('.') : iso || '')

export default function ObjectsPage(
  { canManage, isSuperadmin, initialObjectId }:
  { canManage: boolean; isSuperadmin?: boolean; initialObjectId?: string | null },
) {
  // Подтверждения — своим окном: системное браузер вправе подавить, и кнопка
  // необратимого действия выглядит нерабочей (см. ConfirmDialog).
  const { ask, node: confirmNode } = useConfirm()
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
  const [askDelDoc, setAskDelDoc] = useState<Doc | null>(null)
  // Предложение собрать дашборд: данные копятся сами, а дашборда может не быть
  // месяцами — человек не всегда знает, что система уже готова его собрать.
  const [suggestion, setSuggestion] = useState<BuildSuggestion | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [dashList, setDashList] = useState<Dashboard[]>([])

  function fail(e: unknown) {
    setError((e as Error).message)
  }

  useEffect(() => {
    listObjects().then((list) => {
      setObjects(list)
      // Переход из уведомления «данные не поступили»: открываем тот объект,
      // о котором речь, а не общий список.
      const target = initialObjectId && list.find((o) => o.id === initialObjectId)
      if (target) openObject(target)
    }).catch(fail)
  }, [initialObjectId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function openObject(o: Obj) {
    setError(null)
    setObj(o)
    setSuggestion(null)
    if (canManage) {
      getBuildSuggestion(o.id).then(setSuggestion).catch(() => setSuggestion(null))
    }
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

  // Пока файл распознаётся, список сам догоняет состояние: загрузка теперь
  // сразу ставит распознавание, и без этого человек видел бы «распознаётся…»
  // до тех пор, пока не переоткроет папку.
  useEffect(() => {
    if (!folder || !docs.some((d) => d.pipeline === 'parsing' || d.pipeline === 'new')) return
    const t = setTimeout(() => { loadDocs(folder.id).catch(() => {}) }, 3000)
    return () => clearTimeout(t)
  }, [docs, folder]) // eslint-disable-line react-hooks/exhaustive-deps

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
    if (!await ask({
      title: `Удалить объект «${o.name}»?`,
      message: 'Удаление возможно, только если внутри ничего нет — ни папок, ни справочника показателей. '
        + 'Иначе система откажет и покажет, что именно мешает.',
    })) return
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

  /** Готовить ли выпуски этой папки автоматически. Выпуск всё равно за человеком —
   *  галочка управляет только подготовкой (распознавание + подстановка разметки). */
  async function toggleAutoPrepare(f: Folder) {
    if (!obj) return
    setError(null)
    try {
      await updateFolder(obj.id, f.id, { auto_prepare: f.auto_prepare === false })
      setFolders(await listFolders(obj.id))
    } catch (e) { fail(e) }
  }

  async function saveFolder(vals: Record<string, string>) {
    if (!obj || !editFolder) return
    setBusy(true)
    setError(null)
    try {
      await updateFolder(obj.id, editFolder.id, { name: vals.name.trim() })
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
    if (!await ask({
      title: `Удалить папку «${f.name}»?`,
      message: 'Удаление возможно, только если внутри ничего нет — ни вложенных папок, ни документов, '
        + 'ни привязанных дашбордов. Иначе система откажет и назовёт помеху.',
    })) return
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

  async function removeDoc(d: Doc, withData = false) {
    if (!folder) return
    setBusy(true)
    setError(null)
    try {
      await deleteDocument(folder.id, d.id, withData)
      if (openDoc?.id === d.id) setOpenDoc(null)
      setAskDelDoc(null)
      await loadDocs(folder.id)
    } catch (e) {
      setAskDelDoc(null)
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
      try {
        await uploadDocument(folder.id, file, date)
      } catch (e) {
        // Сервер нашёл побайтово такой же файл. Это чаще всего ошибка (тот же
        // отчёт заливают дважды, и из дубля выпускают вторые данные за период),
        // но бывает и осознанным — решает человек, а не система.
        if (!(e instanceof DuplicateError)) throw e
        const again = await ask({
          title: 'Похоже, этот файл уже загружали',
          message: e.message,
          confirmLabel: 'Всё равно загрузить',
          busyLabel: 'Загрузка…',
          tone: 'accent',
        })
        if (!again) return
        await uploadDocument(folder.id, file, date, true)
      }
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
      {confirmNode}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, marginBottom: 16 }}>
        <button style={crumb} onClick={() => { setObj(null); setFolder(null); setOpenDoc(null) }}>Объекты</button>
        {obj && <><span style={{ color: 'var(--text-faint)' }}>/</span><button style={crumb} onClick={() => { setFolder(null); setOpenDoc(null) }}>{obj.name}</button></>}
        {folder && <><span style={{ color: 'var(--text-faint)' }}>/</span><button style={crumb} onClick={() => setOpenDoc(null)}>{folder.name}</button></>}
        {openDoc && <><span style={{ color: 'var(--text-faint)' }}>/</span><span>{openDoc.original_filename}</span></>}
      </div>

      {error && <div style={errBox}>{error}</div>}

      {!obj && (
        <Section title="Объекты">
          {/* Создание/загрузка — только для тех, у кого есть права: сервер всё равно
              ответит «Недостаточно прав», а нерабочая кнопка выглядит как поломка. */}
          {canManage && (
            <form onSubmit={addObject} style={rowForm}>
              <input style={input} placeholder="Название объекта" value={newObj} onChange={(e) => setNewObj(e.target.value)} />
              <button style={btn} disabled={busy || !newObj.trim()}>＋ Объект</button>
            </form>
          )}
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

      {obj && canManage && suggestion?.suggest && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
          background: 'var(--accent-weak-bg)', color: 'var(--accent)', fontSize: 13,
          padding: '10px 12px', borderRadius: 10, marginBottom: 14,
        }}>
          <span>
            ✨ По объекту накоплено данных: {suggestion.periods === 1
              ? 'один отчёт'
              : `${suggestion.periods} отч. периодов`}
            {suggestion.first_period && suggestion.last_period
              ? ` (с ${ruDate(suggestion.first_period)} по ${ruDate(suggestion.last_period)})`
              : ''}, а дашборда на них нет. Собрать?
          </span>
          <button type="button" style={{ ...btn, height: 30, fontSize: 13, marginLeft: 'auto' }}
            onClick={async () => {
              try { setDashList((await listDashboards('', false, 200)).items) } catch { /* список для «пересобрать» */ }
              setWizardOpen(true)
            }}>Собрать дашборд</button>
        </div>
      )}

      {wizardOpen && obj && (
        <AutoBuildWizard
          objectId={obj.id} objectName={obj.name} dashboards={dashList}
          onClose={() => setWizardOpen(false)}
          onDone={() => {
            setWizardOpen(false)
            // Дашборд появился — предложение больше не актуально.
            getBuildSuggestion(obj.id).then(setSuggestion).catch(() => setSuggestion(null))
          }}
          onError={setError}
        />
      )}

      {obj && !folder && (
        <Section title={`Папки объекта «${obj.name}»`}>
          {canManage && (
            <form onSubmit={addFolder} style={rowForm}>
              <input style={input} placeholder="Название папки" value={newFolder} onChange={(e) => setNewFolder(e.target.value)} />
              {folders.length > 0 && (
                <select style={input} value={newFolderParent} onChange={(e) => setNewFolderParent(e.target.value)}
                  title="Вложить в существующую папку (необязательно)">
                  <option value="">— верхний уровень —</option>
                  {folderTree(folders).map((f) => <option key={f.id} value={f.id}>{folderLabel(f)}</option>)}
                </select>
              )}
              <button style={{ ...btn, whiteSpace: 'nowrap', flexShrink: 0 }}
                disabled={busy || !newFolder.trim()}>＋ Папка</button>
              <button type="button"
                style={{ ...btn, background: 'var(--accent-weak-bg)', color: 'var(--accent)',
                         whiteSpace: 'nowrap', flexShrink: 0 }}
                onClick={() => setRowAclObj(obj)} title="Ограничить видимость строк данных по подразделению">
                🔐 Доступ к строкам
              </button>
            </form>
          )}
          <List
            items={folderTree(folders).map((f) => ({
              id: f.id,
              title: folderLabel(f),
              sub: '',
              onClick: () => openFolder(f),
              badge: canManage ? (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); toggleAutoPrepare(f) }}
                  title={f.auto_prepare === false
                    ? 'Сейчас выключено: новый файл ждёт, пока его отправят на распознавание вручную. Нажмите, чтобы включить'
                    : 'Сейчас включено: новый файл распознаётся сам, разметка подставляется из прошлого выпуска. Выпуск всё равно подтверждает человек. Нажмите, чтобы выключить'}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 6,
                    fontSize: 11.5, padding: '3px 10px', borderRadius: 10, cursor: 'pointer',
                    border: '1px solid ' + (f.auto_prepare === false ? 'var(--border-strong)' : 'var(--success)'),
                    background: f.auto_prepare === false ? 'var(--surface)' : 'var(--success-bg)',
                    color: f.auto_prepare === false ? 'var(--text-muted)' : 'var(--success)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {/* Надпись говорит СОСТОЯНИЕ, а не действие: «готовить
                      автоматически» читалось как предложение включить, хотя
                      означало, что уже включено. */}
                  <span>{f.auto_prepare === false ? '☐' : '☑'}</span>
                  Автоподготовка: {f.auto_prepare === false ? 'выключена' : 'включена'}
                </button>
              ) : undefined,
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

      {askDelDoc && (
        <ConfirmDialog
          title={`Удалить документ «${askDelDoc.original_filename}»?`}
          message={'Файл будет удалён из хранилища.\n\nЕсли из документа уже выпускались данные, система откажет — они питают показатели на дашбордах. Суперадминистратор может удалить документ вместе с этими данными: тогда исчезнут и выпуски, и значения за этот период.'}
          busy={busy}
          onClose={() => setAskDelDoc(null)}
          onConfirm={() => removeDoc(askDelDoc)}
          extraAction={isSuperadmin
            ? { label: 'Удалить вместе с данными', onClick: () => removeDoc(askDelDoc, true) }
            : undefined}
        />
      )}

      {folder && openDoc && (
        <ExtractionPage doc={openDoc} canManage={canManage} isSuperadmin={isSuperadmin} onBack={() => { setOpenDoc(null); refreshDocs() }} />
      )}

      {folder && !openDoc && (
        <Section title={`Документы папки «${folder.name}»`}>
          {canManage && (
            <form onSubmit={upload} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16, alignItems: 'center' }}>
              <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              <label style={{ fontSize: 13, color: 'var(--text-muted)' }}>Отчётная дата:</label>
              <input style={{ ...input, width: 160 }} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              <button style={btn} disabled={busy || !file || !date}>Загрузить</button>
            </form>
          )}
          <List
            items={docs.map((d) => ({
              id: d.id,
              title: d.original_filename,
              sub: `${d.source_type.toUpperCase()} · ${d.reporting_period_start} · ${fmtSize(d.size)}`,
              badge: <PipelineBadge state={d.pipeline} hint={d.pipeline_hint} />,
              onClick: () => setOpenDoc(d),
              actions: canManage ? (
                <IconBtn title="Удалить документ" danger disabled={busy} onClick={() => setAskDelDoc(d)}>🗑</IconBtn>
              ) : undefined,
            }))}
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

type ListItem = {
  id: string; title: string; sub: string
  badge?: React.ReactNode
  onClick?: () => void; actions?: React.ReactNode
}

/**
 * Состояние файла в конвейере — прямо в списке папки.
 *
 * Раньше строка сообщала технический статус документа («распознан»), и чтобы
 * понять, нужен ли тут человек, приходилось открывать каждый файл. Теперь
 * видно главное: готов к выпуску, требует внимания или уже выпущен.
 */
function PipelineBadge({ state, hint }: { state?: string; hint?: string }) {
  const map: Record<string, { t: string; bg: string; c: string }> = {
    new: { t: 'ожидает распознавания', bg: 'var(--surface-3)', c: 'var(--text-muted)' },
    parsing: { t: 'распознаётся…', bg: 'var(--warn-bg)', c: 'var(--warn)' },
    failed: { t: '⚠ не распознан', bg: 'var(--danger-bg)', c: 'var(--danger)' },
    ready: { t: '✓ данные подготовлены', bg: 'var(--success-bg)', c: 'var(--success)' },
    attention: { t: '⚠ требует внимания', bg: 'var(--warn-bg)', c: 'var(--warn)' },
    needs_markup: { t: 'нужна разметка', bg: 'var(--accent-weak-bg)', c: 'var(--accent)' },
    released: { t: 'данные выпущены', bg: 'var(--surface-3)', c: 'var(--text-muted)' },
  }
  const s = map[state || ''] || map.new
  return (
    <span title={hint || ''} style={{
      fontSize: 11, padding: '2px 9px', borderRadius: 10, whiteSpace: 'nowrap',
      background: s.bg, color: s.c,
    }}>{s.t}</span>
  )
}

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
            {it.badge}
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

const crumb: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 14, padding: 0 }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14 }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
// Кнопки в строке формы не сжимаем: при узкой колонке текст переносился внутрь
// в три строки и вылезал за границу кнопки на соседний блок.
const rowForm: React.CSSProperties = {
  display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center',
}
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
