import { useEffect, useState, type FormEvent } from 'react'
import {
  addShowcaseItem, createShowcase, deleteShowcase, getShowcase, listDashboards, listShowcases,
  removeShowcaseItem, reorderShowcaseItem,
  type Dashboard, type ShowcaseDetail, type ShowcaseSummary,
} from '../api'
import PagePreview from './PagePreview'

// Витрины (волна E): именованная подборка из N ЦЕЛЫХ дашбордов на одном
// экране («Состав» — управление списком, «Просмотр» — живая сетка панелей).
// НЕ путать с «📺 Витрина» (KioskView) внутри дашборда — это слайд-шоу
// СТРАНИЦ ОДНОГО дашборда, здесь наоборот — несколько РАЗНЫХ дашбордов сразу.
export default function ShowcasesPage({ canManage, onOpenDashboard }: {
  canManage: boolean; onOpenDashboard: (id: string) => void
}) {
  const [list, setList] = useState<ShowcaseSummary[]>([])
  const [sel, setSel] = useState<ShowcaseDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const [viewMode, setViewMode] = useState(false)
  const [allDash, setAllDash] = useState<Dashboard[]>([])
  const [addDashId, setAddDashId] = useState('')

  const fail = (e: unknown) => setError((e as Error).message)
  const refreshList = () => listShowcases().then(setList).catch(fail)
  useEffect(() => { refreshList() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function openShowcase(id: string) {
    setError(null); setViewMode(false)
    try { setSel(await getShowcase(id)) } catch (e) { fail(e) }
  }
  async function reloadSel() {
    if (!sel) return
    try { setSel(await getShowcase(sel.id)) } catch (e) { fail(e) }
  }
  async function create(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null)
    try { const s = await createShowcase(newName.trim()); setNewName(''); await refreshList(); await openShowcase(s.id) }
    catch (e) { fail(e) } finally { setBusy(false) }
  }
  async function removeShowcase() {
    if (!sel || !confirm(`Удалить витрину «${sel.name}»? Сами дашборды не пострадают.`)) return
    try { await deleteShowcase(sel.id); setSel(null); await refreshList() } catch (e) { fail(e) }
  }
  useEffect(() => {
    if (sel && canManage) listDashboards('', false, 200).then((p) => setAllDash(p.items)).catch(() => {})
  }, [sel?.id, canManage]) // eslint-disable-line react-hooks/exhaustive-deps
  async function addDash() {
    if (!sel || !addDashId) return
    try { await addShowcaseItem(sel.id, addDashId); setAddDashId(''); await reloadSel(); await refreshList() } catch (e) { fail(e) }
  }
  async function removeItem(itemId: string) {
    if (!sel) return
    try { await removeShowcaseItem(sel.id, itemId); await reloadSel(); await refreshList() } catch (e) { fail(e) }
  }
  async function move(itemId: string, dir: 'up' | 'down') {
    if (!sel) return
    try { await reorderShowcaseItem(sel.id, itemId, dir); await reloadSel() } catch (e) { fail(e) }
  }

  const availableDash = allDash.filter((d) => !sel?.items.some((it) => it.dashboard_id === d.id))

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, marginBottom: 16 }}>
        <button style={crumb} onClick={() => setSel(null)}>Витрины</button>
        {sel && <><span style={{ color: 'var(--text-faint)' }}>/</span><span>{sel.name}</span></>}
      </div>
      {error && <div style={errBox}>{error}</div>}

      {!sel && (
        <div>
          {canManage && (
            <form onSubmit={create} style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
              <input style={input} placeholder="Название витрины" value={newName} onChange={(e) => setNewName(e.target.value)} />
              <button style={btn} disabled={busy || !newName.trim()}>＋ Витрина</button>
            </form>
          )}
          {list.length === 0 ? (
            <div style={muted}>Пока нет витрин.{canManage ? '' : ' Обратитесь к администратору или модератору.'}</div>
          ) : (
            <div style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
              {list.map((s, i) => (
                <div key={s.id} onClick={() => openShowcase(s.id)} style={{ ...rowItem, borderTop: i ? '1px solid var(--border-faint)' : 'none' }}>
                  <span style={{ fontSize: 14 }}>{s.name}</span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>дашбордов: {s.items_count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {sel && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
            <button style={!viewMode ? { ...tab, ...tabActive } : tab} onClick={() => setViewMode(false)}>Состав</button>
            <button style={viewMode ? { ...tab, ...tabActive } : tab} disabled={sel.items.length === 0} onClick={() => setViewMode(true)}>
              👁 Просмотр
            </button>
            {canManage && <button style={{ ...linkDanger, marginLeft: 'auto' }} onClick={removeShowcase}>Удалить витрину</button>}
          </div>

          {!viewMode ? (
            <div>
              {canManage && (
                <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
                  <select style={input} value={addDashId} onChange={(e) => setAddDashId(e.target.value)}>
                    <option value="">добавить дашборд…</option>
                    {availableDash.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                  </select>
                  <button style={btn} disabled={!addDashId} onClick={addDash}>Добавить</button>
                </div>
              )}
              {sel.items.length === 0 ? <div style={muted}>В витрине пока нет дашбордов.</div> : (
                <div style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
                  {sel.items.map((it, i) => (
                    <div key={it.id} style={{ ...rowItem, borderTop: i ? '1px solid var(--border-faint)' : 'none', cursor: 'default' }}>
                      <span style={{ fontSize: 14 }}>{it.dashboard_name}{it.page_name ? ` · ${it.page_name}` : ''}</span>
                      <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <button style={crumb} onClick={() => onOpenDashboard(it.dashboard_id)}>открыть →</button>
                        {canManage && (
                          <>
                            <button style={editBtn} disabled={i === 0} onClick={() => move(it.id, 'up')} title="Выше">▲</button>
                            <button style={editBtn} disabled={i === sel.items.length - 1} onClick={() => move(it.id, 'down')} title="Ниже">▼</button>
                            <button style={rmBtn} onClick={() => removeItem(it.id)} title="Убрать из витрины">✕</button>
                          </>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              {sel.items.map((it) => (
                <div key={it.id}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <h3 style={{ fontSize: 15, margin: 0 }}>{it.dashboard_name}</h3>
                    <button style={crumb} onClick={() => onOpenDashboard(it.dashboard_id)}>открыть →</button>
                  </div>
                  {it.page_id ? <PagePreview pageId={it.page_id} /> : <div style={muted}>У дашборда нет страниц.</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const crumb: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 14, padding: 0 }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14 }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
const tab: React.CSSProperties = { height: 32, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', cursor: 'pointer', fontSize: 13 }
const tabActive: React.CSSProperties = { ...tab, background: 'var(--accent-weak-bg)', border: '1px solid var(--accent)', color: 'var(--accent)' }
const rowItem: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', cursor: 'pointer' }
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 14, padding: '8px 0' }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const editBtn: React.CSSProperties = { width: 24, height: 24, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', cursor: 'pointer', color: 'var(--accent)', fontSize: 11 }
const rmBtn: React.CSSProperties = { width: 24, height: 24, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', cursor: 'pointer', color: 'var(--danger)' }
const linkDanger: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--danger)', cursor: 'pointer', fontSize: 12, padding: 0 }
