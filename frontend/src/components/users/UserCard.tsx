import { useEffect, useState } from 'react'
import { getUserActivity, type UserActivity } from '../../api'

const ACTION_RU: Record<string, string> = {
  create: 'Создание', update: 'Изменение', delete: 'Удаление', publish: 'Публикация',
  grant_access: 'Выдача доступа', revoke_access: 'Отзыв доступа', view: 'Просмотр',
  export: 'Выгрузка', heal: 'Автопочинка',
}
const STATUS_RU: Record<string, string> = { open: 'открыто', answered: 'отвечено', closed: 'закрыто' }

function fmtDt(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleString('ru-RU')
}

// «Кабинет сотрудника глазами администратора»: карточка учётной записи, входы,
// действия (включая просмотры и выгрузки), комментарии и обращения — в одном
// месте вместо четырёх разных экранов.
//
// Это ПРОСМОТР, а не вход под чужой учётной записью: система не позволяет
// действовать от чужого имени, иначе аудит перестал бы отвечать на вопрос
// «кто это сделал».
export default function UserCard({ userId, compact = false }: { userId: string; compact?: boolean }) {
  const [data, setData] = useState<UserActivity | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    setData(null); setErr(null)
    getUserActivity(userId).then(setData).catch((e) => setErr((e as Error).message))
  }, [userId])

  if (err) return <div style={errBox}>{err}</div>
  if (!data) return <div style={muted}>Загрузка…</div>
  const u = data.user

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Карточка учётной записи */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        <Fact t="Отдел" v={u.department || '—'} />
        <Fact t="Роли" v={(u.roles || []).join(', ') || '—'} />
        <Fact t="Состояние" v={u.is_active ? 'активна' : 'заблокирована'}
          color={u.is_active ? 'var(--success)' : 'var(--danger)'} />
        <Fact t="Последний вход" v={fmtDt(u.last_login || null)} />
        <Fact t="Успешных входов" v={String(data.login_count)} />
        {u.email && <Fact t="Почта" v={u.email} />}
        {u.must_change_password && <Fact t="Пароль" v="временный, не сменён" color="var(--warn)" />}
      </div>

      <Block title="Последние входы" empty="Входов не было." count={data.logins.length} compact={compact}>
        {data.logins.map((l, i) => (
          <div key={i} style={row}>
            <span style={{ color: l.success ? 'var(--success)' : 'var(--danger)' }}>{l.success ? '✓' : '✕'}</span>
            <span style={{ color: 'var(--text-faint)', flex: 1 }}>{l.ip || '—'}</span>
            <span style={{ color: 'var(--text-faint)' }}>{fmtDt(l.created_at)}</span>
          </div>
        ))}
      </Block>

      <Block title="Действия (в т.ч. просмотры и выгрузки)" empty="Действий не зафиксировано."
        count={data.events.length} compact={compact}>
        {data.events.map((e) => (
          <div key={e.id} style={row}>
            <span style={badge}>{ACTION_RU[e.action] || e.action}</span>
            <span style={{ flex: 1, minWidth: 0 }}>{e.entity_name || e.entity_type}</span>
            <span style={{ color: 'var(--text-faint)' }}>{fmtDt(e.created_at)}</span>
          </div>
        ))}
      </Block>

      <Block title="Комментарии к дашбордам" empty="Комментариев не оставлял."
        count={data.comments.length} compact={compact}>
        {data.comments.map((c) => (
          <div key={c.id} style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-faint)' }}>{fmtDt(c.created_at)} · {c.dashboard_name}: </span>{c.body}
          </div>
        ))}
      </Block>

      <Block title="Обращения к администратору" empty="Обращений не было."
        count={(data.appeals || []).length} compact={compact}>
        {(data.appeals || []).map((a) => (
          <div key={a.id} style={row}>
            <span style={badge}>{STATUS_RU[a.status] || a.status}</span>
            <span style={{ flex: 1, minWidth: 0 }}>{a.subject || 'без темы'}</span>
            <span style={{ color: 'var(--text-faint)' }}>{fmtDt(a.updated_at)}</span>
          </div>
        ))}
      </Block>
    </div>
  )
}

function Fact({ t, v, color }: { t: string; v: string; color?: string }) {
  return (
    <div style={{ border: '1px solid var(--border-faint)', borderRadius: 8, padding: '6px 10px', minWidth: 130 }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{t}</div>
      <div style={{ fontSize: 13, color: color || 'var(--text)' }}>{v}</div>
    </div>
  )
}

function Block({ title, empty, count, compact, children }: {
  title: string; empty: string; count: number; compact: boolean; children: React.ReactNode
}) {
  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
        {title}{count > 0 && <span style={{ color: 'var(--text-faint)', fontWeight: 400 }}> · {count}</span>}
      </div>
      {count === 0 ? <div style={muted}>{empty}</div> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3,
          maxHeight: compact ? 130 : 200, overflowY: 'auto' }}>{children}</div>
      )}
    </div>
  )
}

const row: React.CSSProperties = { display: 'flex', gap: 8, fontSize: 12, alignItems: 'baseline' }
const badge: React.CSSProperties = {
  display: 'inline-block', padding: '1px 8px', borderRadius: 8,
  background: 'var(--surface-3)', color: 'var(--text-2)', fontSize: 12, flexShrink: 0,
}
const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 13 }
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13,
  padding: '8px 10px', borderRadius: 8,
}
