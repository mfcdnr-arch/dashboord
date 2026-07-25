import { useEffect, useRef, useState } from 'react'
import { addComment, deleteComment, listComments, type Dashboard, type DashComment } from '../../api'
import { btn, btnAuto, dialog, muted, overlay, rmBtn } from './shared'

const PAGE = 50

function fmtDt(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

export function Comments({ dashboard, onClose }: { dashboard: Dashboard; onClose: () => void }) {
  const [items, setItems] = useState<DashComment[]>([])
  const [total, setTotal] = useState(0)
  const [text, setText] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)

  const load = () => {
    const s = ++seq.current
    return listComments(dashboard.id, PAGE, 0)
      .then((p) => { if (s === seq.current) { setItems(p.items); setTotal(p.total) } })
      .catch((e) => setErr((e as Error).message))
  }
  useEffect(() => { load() }, [dashboard.id]) // eslint-disable-line react-hooks/exhaustive-deps

  async function loadMore() {
    const s = ++seq.current
    try { const p = await listComments(dashboard.id, PAGE, items.length); if (s === seq.current) { setItems((prev) => [...prev, ...p.items]); setTotal(p.total) } } catch (e) { setErr((e as Error).message) }
  }
  async function send() {
    const body = text.trim()
    if (!body) return
    setBusy(true); setErr(null)
    try { await addComment(dashboard.id, body); setText(''); await load() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function remove(id: string) {
    setErr(null)
    try { await deleteComment(dashboard.id, id); await load() } catch (e) { setErr((e as Error).message) }
  }

  return (
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 560, display: 'flex', flexDirection: 'column' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>💬 Обсуждение: {dashboard.name}</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
          Комментарии видны всем, кто имеет доступ к дашборду. Автор дашборда получит уведомление о новом комментарии.
        </div>

        <div style={{ flex: 1, minHeight: 80, marginBottom: 12 }}>
          {items.length === 0 ? <div style={muted}>Пока нет комментариев. Начните обсуждение.</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {items.map((c) => (
                <div key={c.id} style={{ border: '1px solid var(--border-faint)', borderRadius: 10, padding: '8px 12px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent)' }}>{c.author}</span>
                    <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>{fmtDt(c.created_at)}</span>
                    {c.can_delete && (
                      <button onClick={() => remove(c.id)} title="Удалить комментарий"
                        style={{ marginLeft: 'auto', border: 'none', background: 'none', color: 'var(--danger)', cursor: 'pointer', fontSize: 13, padding: 0 }}>✕</button>
                    )}
                  </div>
                  <div style={{ fontSize: 14, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{c.body}</div>
                </div>
              ))}
              {items.length < total && (
                <div style={{ textAlign: 'center' }}>
                  <button style={btnAuto} onClick={loadMore}>Показать ещё ({total - items.length})</button>
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Написать комментарий…" rows={2}
            style={{ flex: 1, resize: 'vertical', padding: '8px 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14, fontFamily: 'inherit' }} />
          <button style={btn} disabled={busy || !text.trim()} onClick={send}>Отправить</button>
        </div>
        {err && <div style={{ color: 'var(--danger)', fontSize: 13, marginTop: 10 }}>{err}</div>}
      </div>
    </div>
  )
}
