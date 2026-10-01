import { useEffect, useRef, useState } from 'react'
import {
  getNotifications, markAllNotificationsRead, markNotificationRead,
  type NotificationItem, type NotificationsResult,
} from '../api'
import { fmtDt, message, targetOf, type NotifyTarget } from '../lib/notifications'

// Колокольчик уведомлений в шапке: непрочитанные + выпадающая лента.
// Опрос каждые 60с. Текст и переход каждого события — lib/notifications.ts.

export type { NotifyTarget }

export default function NotificationBell(
  { staff, onNavigate }: { staff: boolean; onNavigate?: (t: NotifyTarget) => void },
) {
  const [data, setData] = useState<NotificationsResult | null>(null)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)

  const load = () => getNotifications().then(setData).catch(() => {})
  useEffect(() => { load(); const t = setInterval(load, 60000); return () => clearInterval(t) }, [])
  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const unread = data?.unread ?? 0
  async function readOne(n: NotificationItem) {
    if (!n.is_read) { try { await markNotificationRead(n.recipient_id); load() } catch { /* ignore */ } }
    const target = targetOf(n, staff)
    if (target && onNavigate) { setOpen(false); onNavigate(target) }
  }
  async function readAll() { try { await markAllNotificationsRead(); load() } catch { /* ignore */ } }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button type="button" onClick={() => { setOpen((v) => !v); if (!open) load() }} title="Уведомления"
        aria-label={unread > 0 ? `Уведомления, непрочитанных: ${unread}` : 'Уведомления'} aria-expanded={open}
        style={{ position: 'relative', height: 32, width: 36, border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', cursor: 'pointer', fontSize: 16 }}>
        🔔
        {unread > 0 && (
          <span style={{ position: 'absolute', top: -6, right: -6, minWidth: 18, height: 18, padding: '0 4px', borderRadius: 9, background: 'var(--danger)', color: 'var(--on-danger)', fontSize: 11, lineHeight: '18px', textAlign: 'center' }}>
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div style={{ position: 'absolute', right: 0, top: 40, width: 360, maxWidth: '92vw', maxHeight: 420, overflowY: 'auto', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, boxShadow: '0 10px 40px rgba(0,0,0,0.18)', zIndex: 80 }}>
          <div style={{ display: 'flex', alignItems: 'center', padding: '10px 12px', borderBottom: '1px solid var(--border-faint)' }}>
            <b style={{ fontSize: 14 }}>Уведомления</b>
            {unread > 0 && <button onClick={readAll} style={{ marginLeft: 'auto', border: 'none', background: 'none', color: 'var(--accent-text)', cursor: 'pointer', fontSize: 12 }}>прочитать всё</button>}
          </div>
          {!data ? <div style={{ padding: 14, color: 'var(--text-faint)', fontSize: 13 }}>Загрузка…</div>
            : data.items.length === 0 ? <div style={{ padding: 14, color: 'var(--text-faint)', fontSize: 13 }}>Уведомлений нет.</div>
              : data.items.map((n) => (
                // Кнопка, а не div с onClick: строку ленты надо уметь открыть
                // с клавиатуры, а div в обход Tab не попадает вовсе.
                <button key={n.recipient_id} type="button" onClick={() => readOne(n)}
                  title={targetOf(n, staff) ? 'Открыть' : undefined}
                  style={{
                    display: 'block', width: '100%', boxSizing: 'border-box', textAlign: 'left',
                    font: 'inherit', color: 'inherit', border: 'none',
                    padding: '10px 12px', borderBottom: '1px solid var(--border-faint)',
                    // Курсор-указатель, пока есть куда вести: у прочитанного
                    // уведомления переход остаётся, и «default» врал бы.
                    cursor: targetOf(n, staff) || !n.is_read ? 'pointer' : 'default',
                    background: n.is_read ? 'var(--surface)' : 'var(--surface-accent)',
                  }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {!n.is_read && <span aria-label="не прочитано" style={{ width: 7, height: 7, borderRadius: 4, background: 'var(--accent)', flexShrink: 0 }} />}
                    <span style={{ fontSize: 13, fontWeight: 600 }}>{n.label}</span>
                    <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-faint)', whiteSpace: 'nowrap' }}>{fmtDt(n.created_at)}</span>
                  </span>
                  <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{message(n)}</span>
                </button>
              ))}
        </div>
      )}
    </div>
  )
}
