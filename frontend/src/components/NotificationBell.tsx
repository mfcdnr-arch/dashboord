import { useEffect, useRef, useState } from 'react'
import {
  getNotifications, markAllNotificationsRead, markNotificationRead,
  type NotificationItem, type NotificationsResult,
} from '../api'

// Колокольчик уведомлений в шапке: непрочитанные + выпадающая лента.
// Опрос каждые 60с. Служебные события: устаревание данных, ретенция и т.п.

function fmtDt(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

function message(n: NotificationItem): string {
  const p = n.payload || {}
  if (n.event_type === 'data.stale') return `Объект «${p.object_name}»: нет новых данных ${p.days_since_upload} дн. (порог ${p.threshold_days}).`
  if (n.event_type === 'data.retention') return `Ретенция: удалено релизов — ${p.deleted_releases} (окно ${p.window_months} мес.).`
  if (n.event_type === 'widget.created.no_explicit_access') return `Новый виджет без явных прав: ${p.widget_name ?? ''}`
  return n.label
}

export default function NotificationBell() {
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
  }
  async function readAll() { try { await markAllNotificationsRead(); load() } catch { /* ignore */ } }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button onClick={() => { setOpen((v) => !v); if (!open) load() }} title="Уведомления"
        style={{ position: 'relative', height: 32, width: 36, border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', cursor: 'pointer', fontSize: 16 }}>
        🔔
        {unread > 0 && (
          <span style={{ position: 'absolute', top: -6, right: -6, minWidth: 18, height: 18, padding: '0 4px', borderRadius: 9, background: 'var(--danger)', color: 'var(--on-accent)', fontSize: 11, lineHeight: '18px', textAlign: 'center' }}>
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div style={{ position: 'absolute', right: 0, top: 40, width: 360, maxWidth: '92vw', maxHeight: 420, overflowY: 'auto', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, boxShadow: '0 10px 40px rgba(0,0,0,0.18)', zIndex: 80 }}>
          <div style={{ display: 'flex', alignItems: 'center', padding: '10px 12px', borderBottom: '1px solid var(--border-faint)' }}>
            <b style={{ fontSize: 14 }}>Уведомления</b>
            {unread > 0 && <button onClick={readAll} style={{ marginLeft: 'auto', border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12 }}>прочитать всё</button>}
          </div>
          {!data ? <div style={{ padding: 14, color: 'var(--text-faint)', fontSize: 13 }}>Загрузка…</div>
            : data.items.length === 0 ? <div style={{ padding: 14, color: 'var(--text-faint)', fontSize: 13 }}>Уведомлений нет.</div>
              : data.items.map((n) => (
                <div key={n.recipient_id} onClick={() => readOne(n)}
                  style={{ padding: '10px 12px', borderBottom: '1px solid var(--border-faint)', cursor: n.is_read ? 'default' : 'pointer', background: n.is_read ? 'var(--surface)' : 'var(--surface-accent)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {!n.is_read && <span style={{ width: 7, height: 7, borderRadius: 4, background: 'var(--accent)', flexShrink: 0 }} />}
                    <span style={{ fontSize: 13, fontWeight: 600 }}>{n.label}</span>
                    <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-faint)', whiteSpace: 'nowrap' }}>{fmtDt(n.created_at)}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{message(n)}</div>
                </div>
              ))}
        </div>
      )}
    </div>
  )
}
