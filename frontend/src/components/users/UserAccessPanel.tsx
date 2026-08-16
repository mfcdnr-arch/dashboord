import { useEffect, useMemo, useState } from 'react'
import {
  getUserDashboardAccess, setUserDashboardAccess,
  type UserDashboardAccess, type UserDashboardAccessItem,
} from '../../api'

const STATUS_RU: Record<string, string> = {
  draft: 'черновик', review: 'на проверке', published: 'опубликован', archived: 'в архиве',
}

// «Кому что доступно» с точки зрения СОТРУДНИКА (пп. 10–11 списка заказчика).
// Раньше доступ выдавался только с самого дашборда, и чтобы открыть человеку
// пять отчётов, нужно было пять раз пройти один и тот же путь.
//
// Что здесь принципиально:
//  • пишем в те же гранты, что и окно «🔒 Доступ» на дашборде — второй системы
//    прав нет, поэтому расхождений между экранами быть не может;
//  • доступ, пришедший ЧЕРЕЗ РОЛЬ, отсюда снять нельзя: он выдан не этому
//    человеку, а всем носителям роли (галочка была бы ловушкой);
//  • подписываем последствие, а не только состояние: привилегированная роль
//    видит всё независимо от галочек, а неопубликованный дашборд зритель не
//    увидит, даже когда доступ выдан.
export default function UserAccessPanel({ userId, compact = false }: { userId: string; compact?: boolean }) {
  const [data, setData] = useState<UserDashboardAccess | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  // Отмеченное человеком состояние галочек: dashboard_id → granted
  const [checked, setChecked] = useState<Record<string, boolean>>({})

  const load = () => {
    setErr(null)
    getUserDashboardAccess(userId).then((d) => {
      setData(d)
      setChecked(Object.fromEntries(d.items.map((i) => [i.dashboard_id, i.granted])))
    }).catch((e) => setErr((e as Error).message))
  }
  useEffect(load, [userId])

  const items = useMemo(() => {
    if (!data) return []
    const needle = q.trim().toLowerCase()
    if (!needle) return data.items
    return data.items.filter((i) =>
      i.name.toLowerCase().includes(needle) ||
      (i.folder_name || '').toLowerCase().includes(needle) ||
      (i.object_name || '').toLowerCase().includes(needle))
  }, [data, q])

  // Разница с тем, что сейчас в базе: её и отправляем.
  const diff = useMemo(() => {
    const grant: string[] = [], revoke: string[] = []
    for (const i of data?.items || []) {
      const now = !!checked[i.dashboard_id]
      if (now && !i.granted) grant.push(i.dashboard_id)
      if (!now && i.granted) revoke.push(i.dashboard_id)
    }
    return { grant, revoke }
  }, [data, checked])

  const save = async () => {
    setBusy(true); setErr(null); setMsg(null)
    try {
      const r = await setUserDashboardAccess(userId, diff.grant, diff.revoke)
      setMsg(`Готово: выдано ${r.granted}, снято ${r.revoked}.`)
      load()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (err && !data) return <div style={errBox}>{err}</div>
  if (!data) return <div style={muted}>Загрузка…</div>
  const changes = diff.grant.length + diff.revoke.length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {data.user.privileged && (
        <div style={noteBox}>
          У сотрудника роль {data.user.roles.join(', ')} — он видит <b>все</b> дашборды организации
          независимо от этих отметок. Галочки пригодятся, если роль позже понизят.
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <input style={input} placeholder="Поиск по названию, папке, объекту"
          value={q} onChange={(e) => setQ(e.target.value)} />
        <button style={linkBtn} onClick={() => setChecked((c) => {
          const n = { ...c }; items.forEach((i) => { if (canEdit(i)) n[i.dashboard_id] = true }); return n
        })}>отметить все</button>
        <button style={linkBtn} onClick={() => setChecked((c) => {
          const n = { ...c }; items.forEach((i) => { if (canEdit(i)) n[i.dashboard_id] = false }); return n
        })}>снять все</button>
        <span style={{ ...muted, marginLeft: 'auto' }}>дашбордов: {items.length}</span>
      </div>

      {err && <div style={errBox}>{err}</div>}
      {msg && <div style={okBox}>{msg}</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: compact ? 220 : 340, overflowY: 'auto' }}>
        {items.length === 0 && <div style={muted}>Ничего не найдено.</div>}
        {items.map((i) => {
          const editable = canEdit(i)
          return (
            <label key={i.dashboard_id}
              style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '4px 6px', borderRadius: 6,
                background: !editable ? 'var(--surface-2)' : undefined, cursor: editable ? 'pointer' : 'default' }}
              title={reason(i)}>
              <input type="checkbox" disabled={!editable} checked={editable ? !!checked[i.dashboard_id] : true}
                onChange={(e) => setChecked((c) => ({ ...c, [i.dashboard_id]: e.target.checked }))} />
              <span style={{ flex: 1, minWidth: 0 }}>
                {i.featured && <span title="Раздел «Руководителю»">👔 </span>}
                {i.name}
                {(i.folder_name || i.object_name) && (
                  <span style={{ color: 'var(--text-faint)', fontSize: 12 }}>
                    {' '}· 📁 {[i.object_name, i.folder_name].filter(Boolean).join(' / ')}
                  </span>
                )}
              </span>
              {i.publication_status !== 'published' && (
                <span style={warnBadge}>{STATUS_RU[i.publication_status] || i.publication_status}</span>
              )}
              {i.is_author && <span style={badge}>автор</span>}
              {i.via_roles.length > 0 && <span style={badge}>через роль: {i.via_roles.join(', ')}</span>}
              {i.widget_limited && <span style={badge}>виджеты по списку</span>}
            </label>
          )
        })}
      </div>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button style={{ ...btn, opacity: changes === 0 || busy ? 0.5 : 1 }}
          disabled={changes === 0 || busy} onClick={save}>
          {busy ? 'Сохранение…' : 'Сохранить доступ'}
        </button>
        <span style={muted}>
          {changes === 0 ? 'Изменений нет.'
            : `Будет выдано: ${diff.grant.length}, снято: ${diff.revoke.length}.`}
        </span>
      </div>

      <div style={{ ...muted, fontSize: 12 }}>
        Доступ, полученный через роль или авторство, отсюда не снимается — роль правится
        в карточке сотрудника, грант на роль на самом дашборде. Неопубликованный дашборд
        зритель не увидит, даже если доступ выдан.
      </div>
    </div>
  )
}

// Личный грант можно снять только там, где доступ идёт именно от него: у автора
// и у носителя роли-получателя галочка ничего не изменила бы.
function canEdit(i: UserDashboardAccessItem): boolean {
  return !i.is_author && i.via_roles.length === 0
}

function reason(i: UserDashboardAccessItem): string {
  if (i.is_author) return 'Сотрудник — автор дашборда, доступ у него есть всегда.'
  if (i.via_roles.length > 0) return `Доступ выдан роли «${i.via_roles.join(', ')}» — снимается на самом дашборде.`
  if (i.publication_status !== 'published') return 'Дашборд не опубликован: зритель увидит его после публикации.'
  return i.visible ? 'Доступ открыт.' : 'Доступа нет.'
}

const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 13 }
const input: React.CSSProperties = {
  height: 30, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13, flex: 1, minWidth: 180,
}
const btn: React.CSSProperties = {
  height: 32, padding: '0 14px', border: 'none', borderRadius: 8,
  background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer',
}
const linkBtn: React.CSSProperties = {
  border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: 0,
}
const badge: React.CSSProperties = {
  display: 'inline-block', padding: '1px 8px', borderRadius: 8,
  background: 'var(--surface-3)', color: 'var(--text-2)', fontSize: 11, flexShrink: 0,
}
const warnBadge: React.CSSProperties = { ...badge, background: 'var(--warn-bg)', color: 'var(--warn)' }
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8,
}
const okBox: React.CSSProperties = {
  background: 'var(--success-bg)', color: 'var(--success)', fontSize: 13, padding: '8px 10px', borderRadius: 8,
}
const noteBox: React.CSSProperties = {
  background: 'var(--surface-2)', color: 'var(--text-2)', fontSize: 12, padding: '8px 10px', borderRadius: 8,
}
