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

/** Отчётные даты показываем по-русски: в системе принят ДД.ММ.ГГГГ. */
function ruDate(v: unknown): string {
  const s = String(v ?? '')
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s.split('-').reverse().join('.') : s
}

function message(n: NotificationItem): string {
  const p = n.payload || {}
  if (n.event_type === 'data.stale') return `Объект «${p.object_name}»: нет новых данных ${p.days_since_upload} дн. (порог ${p.threshold_days}).`
  if (n.event_type === 'data.missing') {
    return `Объект «${p.object_name}»: отчёт за ${ruDate(p.expected_period)} не поступил `
      + `(форма приходит раз в ${p.cadence_days} дн., последний — за ${ruDate(p.last_period)}).`
  }
  if (n.event_type === 'dashboard.review_requested') {
    return `«${p.dashboard_name}» ждёт проверки${p.author ? ` — отправил ${p.author}` : ''}.`
  }
  if (n.event_type === 'data.retention') return `Ретенция: удалено релизов — ${p.deleted_releases} (окно ${p.window_months} мес.).`
  if (n.event_type === 'widget.created.no_explicit_access') return `Новый виджет без явных прав: ${p.widget_name ?? ''}`
  if (n.event_type === 'system.degraded') return `Автопочинка не устранила все проблемы (статус: ${p.status_after ?? 'degraded'}). Посмотрите раздел «Отчёты» → «Здоровье системы».`
  if (n.event_type === 'appeal.created' || n.event_type === 'appeal.message') return `${p.author ?? ''}: ${p.snippet ?? ''}`
  if (n.event_type === 'appeal.replied') return `${p.author ?? 'Администратор'} ответил на ваше обращение: ${p.snippet ?? ''}`
  return n.label
}

/**
   * Куда ведёт уведомление.
   *
   * Уведомление без перехода — тупик: человек прочитал «ztest: не работает
   * выгрузка» и должен сам вспомнить, в каком разделе искать это обращение.
   * Поэтому каждое событие знает свою сущность (entity_type/entity_id), и клик
   * открывает именно её. Обычного пользователя ведём в «Кабинет»: раздела
   * «Обращения» у него нет, его переписка живёт там.
   */
function targetOf(n: NotificationItem, staff: boolean): NotifyTarget | null {
  const id = n.entity_id || undefined
  if (n.event_type.startsWith('appeal.')) {
    return { section: staff ? 'appeals' : 'profile', appealId: id }
  }
  if (n.event_type === 'dashboard.comment' || n.event_type === 'dashboard.review_requested') {
    return { section: 'dashboards', dashboardId: id }
  }
  if (n.event_type === 'data.stale' || n.event_type === 'data.missing') {
    return { section: 'objects', objectId: id }
  }
  if (n.event_type === 'data.retention') return { section: 'settings' }
  if (n.event_type === 'system.degraded') return { section: 'reports' }
  return null
}

export type NotifyTarget = {
  section: string
  appealId?: string
  dashboardId?: string
  objectId?: string
}

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
                  title={targetOf(n, staff) ? 'Открыть' : undefined}
                  style={{
                    padding: '10px 12px', borderBottom: '1px solid var(--border-faint)',
                    // Курсор-указатель, пока есть куда вести: у прочитанного
                    // уведомления переход остаётся, и «default» врал бы.
                    cursor: targetOf(n, staff) || !n.is_read ? 'pointer' : 'default',
                    background: n.is_read ? 'var(--surface)' : 'var(--surface-accent)',
                  }}>
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
