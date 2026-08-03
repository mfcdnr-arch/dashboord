import { useEffect, useState } from 'react'
import {
  addAppealMessage, closeAppeal, createAppeal, getAppeal, listAppeals, listMyAppeals,
  type AppealDetail, type AppealSummary,
} from '../api'

// Переиспользуемая панель обращений: 'mine' — личный кабинет (создание + свои
// заявки), 'all' — раздел «Обращения» для staff (фильтр по статусу + ответ +
// закрытие). Логика прав — на бэкенде (appeals/service.py), здесь только UI.

function fmtDt(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

const STATUS_LABEL: Record<string, { t: string; bg: string; c: string }> = {
  open: { t: 'ожидает ответа', bg: 'var(--warn-bg)', c: 'var(--warn)' },
  answered: { t: 'есть ответ', bg: 'var(--success-bg)', c: 'var(--success)' },
  closed: { t: 'закрыто', bg: 'var(--surface-3)', c: 'var(--text-faint)' },
}

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_LABEL[status] || STATUS_LABEL.open
  return <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: s.bg, color: s.c, whiteSpace: 'nowrap' }}>{s.t}</span>
}

export default function AppealsPanel({ scope }: { scope: 'mine' | 'all' }) {
  const isStaff = scope === 'all'
  const [items, setItems] = useState<AppealSummary[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)
  const [detail, setDetail] = useState<AppealDetail | null>(null)
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [reply, setReply] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => {
    const p = isStaff ? listAppeals(statusFilter || undefined) : listMyAppeals()
    p.then((r) => setItems(r.items)).catch((e) => setErr((e as Error).message))
  }
  useEffect(() => { load() }, [statusFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  async function openThread(id: string) {
    setErr(null)
    try { setDetail(await getAppeal(id)); setOpenId(id) } catch (e) { setErr((e as Error).message) }
  }
  function back() { setOpenId(null); setDetail(null); setReply(''); load() }

  async function submitNew() {
    if (!body.trim()) return
    setBusy(true); setErr(null)
    try { await createAppeal(subject, body); setSubject(''); setBody(''); load() }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function submitReply() {
    if (!openId || !reply.trim()) return
    setBusy(true); setErr(null)
    try { await addAppealMessage(openId, reply); setReply(''); setDetail(await getAppeal(openId)) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function doClose() {
    if (!openId) return
    setBusy(true); setErr(null)
    try { await closeAppeal(openId); setDetail(await getAppeal(openId)); load() }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  if (openId && detail) {
    return (
      <div>
        <button onClick={back} style={crumb}>← К списку обращений</button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '10px 0' }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{detail.subject || 'Обращение'}</div>
          <StatusBadge status={detail.status} />
          {isStaff && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>от {detail.author}</span>}
          {isStaff && detail.status !== 'closed' && (
            <button style={{ ...btnGhost, marginLeft: 'auto' }} disabled={busy} onClick={doClose}>Закрыть обращение</button>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 12 }}>
          {detail.messages.map((m) => (
            <div key={m.id} style={{
              border: '1px solid var(--border-faint)', borderRadius: 10, padding: '8px 12px',
              background: m.is_staff ? 'var(--accent-weak-bg)' : 'var(--surface)',
            }}>
              <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: m.is_staff ? 'var(--accent)' : 'var(--text)' }}>
                  {m.is_staff ? '🛠 ' : ''}{m.author}
                </span>
                <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>{fmtDt(m.created_at)}</span>
              </div>
              <div style={{ fontSize: 14, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{m.body}</div>
            </div>
          ))}
        </div>
        {detail.status !== 'closed' || isStaff ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <textarea value={reply} onChange={(e) => setReply(e.target.value)} rows={2} placeholder="Ваш ответ…"
              style={{ flex: 1, resize: 'vertical', padding: '8px 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14, fontFamily: 'inherit' }} />
            <button style={btn} disabled={busy || !reply.trim()} onClick={submitReply}>Отправить</button>
          </div>
        ) : (
          <div style={muted}>Обращение закрыто. Новое сообщение откроет его снова.</div>
        )}
        {err && <div style={errBox}>{err}</div>}
      </div>
    )
  }

  return (
    <div>
      {!isStaff && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 12, padding: 14, marginBottom: 16 }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Новое обращение</div>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Тема (необязательно)"
            style={{ ...input, width: '100%', marginBottom: 8, boxSizing: 'border-box' }} />
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} placeholder="Опишите вопрос или проблему…"
            style={{ width: '100%', resize: 'vertical', padding: '8px 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14, fontFamily: 'inherit', marginBottom: 8, boxSizing: 'border-box' }} />
          <button style={btn} disabled={busy || !body.trim()} onClick={submitNew}>Отправить администратору</button>
        </div>
      )}
      {isStaff && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          {['', 'open', 'answered', 'closed'].map((s) => (
            <button key={s || 'all'} onClick={() => setStatusFilter(s)} style={statusFilter === s ? tabActive : tab}>
              {s === '' ? 'Все' : STATUS_LABEL[s].t}
            </button>
          ))}
        </div>
      )}
      {err && <div style={errBox}>{err}</div>}
      {items.length === 0 ? <div style={muted}>{isStaff ? 'Обращений нет.' : 'У вас пока нет обращений.'}</div> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {items.map((a) => (
            <div key={a.id} onClick={() => openThread(a.id)}
              style={{ border: '1px solid var(--border)', borderRadius: 10, padding: '10px 14px', cursor: 'pointer' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 600 }}>{a.subject || 'Без темы'}</span>
                <StatusBadge status={a.status} />
                {isStaff && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{a.author}</span>}
                <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-faint)', whiteSpace: 'nowrap' }}>{fmtDt(a.updated_at)}</span>
              </div>
              {a.last_message && (
                <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {a.last_is_staff ? '🛠 ' : ''}{a.last_message}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const crumb: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 14, padding: 0 }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14 }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { height: 32, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text-2)', fontSize: 13, cursor: 'pointer' }
const tab: React.CSSProperties = { height: 32, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', cursor: 'pointer', fontSize: 13 }
const tabActive: React.CSSProperties = { ...tab, background: 'var(--accent-weak-bg)', border: '1px solid var(--accent)', color: 'var(--accent)' }
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 14, padding: '8px 0' }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginTop: 10 }
