import { useEffect, useState } from 'react'
import {
  getAuditEvent, listAudit,
  type AuditDetail, type AuditItem, type AuditList, type AuditQuery,
} from '../api'

// Раздел «Аудит действий» (только admin): журнал изменений сущностей
// (дашборды/виджеты/права). Наполняется триггерами БД, автор — из сессии.
// Фильтры по автору/типу/действию/периоду, пагинация и пофайловый diff.

const PAGE = 50

const ACTION_LABEL: Record<string, string> = {
  create: 'Создание', update: 'Изменение', delete: 'Удаление', publish: 'Публикация',
  grant_access: 'Выдача доступа', revoke_access: 'Отзыв доступа', view: 'Просмотр',
}
const ACTION_COLOR: Record<string, string> = {
  create: '#0f6e56', update: '#9a6a00', delete: '#a32d2d', publish: '#2f5496',
  grant_access: '#0f6e56', revoke_access: '#a32d2d', view: '#6b7280',
}

function fmtDt(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
function actorText(it: { actor_login: string | null; actor_name: string | null }): string {
  if (!it.actor_login) return 'система/не указан'
  return it.actor_name ? `${it.actor_name} (${it.actor_login})` : it.actor_login
}

export default function AuditPage({ me }: { me: { roles: string[] } }) {
  const [data, setData] = useState<AuditList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<AuditDetail | null>(null)
  // фильтры
  const [actor, setActor] = useState('')
  const [entityType, setEntityType] = useState('')
  const [action, setAction] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [offset, setOffset] = useState(0)

  function load() {
    setLoading(true)
    setError(null)
    const q: AuditQuery = { limit: PAGE, offset }
    if (actor) q.actor = actor
    if (entityType) q.entity_type = entityType
    if (action) q.action = action
    if (dateFrom) q.date_from = dateFrom
    // верхняя граница включительно по дню: до начала следующего дня
    if (dateTo) { const d = new Date(dateTo); d.setDate(d.getDate() + 1); q.date_to = d.toISOString().slice(0, 10) }
    listAudit(q).then(setData).catch((e) => setError((e as Error).message)).finally(() => setLoading(false))
  }
  // перезагрузка при смене фильтров/страницы
  useEffect(load, [actor, entityType, action, dateFrom, dateTo, offset]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!me.roles.includes('admin')) {
    return <div style={{ color: '#a32d2d' }}>Раздел «Аудит действий» доступен только администратору.</div>
  }

  const facets = data?.facets
  const total = data?.total ?? 0
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + PAGE, total)

  function resetFilters() {
    setActor(''); setEntityType(''); setAction(''); setDateFrom(''); setDateTo(''); setOffset(0)
  }
  function onFilterChange(setter: (v: string) => void) {
    return (v: string) => { setOffset(0); setter(v) }
  }
  function openDetail(id: string) {
    setDetail(null)
    getAuditEvent(id).then(setDetail).catch((e) => setError((e as Error).message))
  }

  const hasFilters = !!(actor || entityType || action || dateFrom || dateTo)

  return (
    <div>
      <h2 style={{ fontSize: 20, margin: '0 0 4px' }}>Аудит действий</h2>
      <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 16 }}>
        Журнал изменений дашбордов, виджетов и прав доступа: кто, что и когда менял.
      </div>
      {error && <div style={errBox}>{error}</div>}

      {/* Фильтры */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'flex-end', marginBottom: 14 }}>
        <F t="Автор">
          <select style={input} value={actor} onChange={(e) => onFilterChange(setActor)(e.target.value)}>
            <option value="">— любой —</option>
            {facets?.actors.map((a) => <option key={a.id} value={a.id}>{a.full_name ? `${a.full_name} (${a.login})` : a.login}</option>)}
          </select>
        </F>
        <F t="Тип объекта">
          <select style={input} value={entityType} onChange={(e) => onFilterChange(setEntityType)(e.target.value)}>
            <option value="">— все —</option>
            {facets?.entity_types.map((et) => <option key={et.code} value={et.code}>{et.label}</option>)}
          </select>
        </F>
        <F t="Действие">
          <select style={input} value={action} onChange={(e) => onFilterChange(setAction)(e.target.value)}>
            <option value="">— все —</option>
            {facets?.actions.map((a) => <option key={a} value={a}>{ACTION_LABEL[a] || a}</option>)}
          </select>
        </F>
        <F t="С даты"><input type="date" style={input} value={dateFrom} onChange={(e) => onFilterChange(setDateFrom)(e.target.value)} /></F>
        <F t="По дату"><input type="date" style={input} value={dateTo} onChange={(e) => onFilterChange(setDateTo)(e.target.value)} /></F>
        {hasFilters && <button style={ghostBtn} onClick={resetFilters}>Сбросить</button>}
      </div>

      {/* Итоги + пагинация */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, fontSize: 13, color: '#6b7280' }}>
        <span>{loading ? 'Загрузка…' : total === 0 ? 'Записей нет' : `${from}–${to} из ${total}`}</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button style={pageBtn} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Назад</button>
          <button style={pageBtn} disabled={to >= total} onClick={() => setOffset(offset + PAGE)}>Вперёд →</button>
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
          <thead><tr>{['Время', 'Автор', 'Действие', 'Объект', 'Изменения', ''].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
          <tbody>
            {data?.items.map((it) => <Row key={it.id} it={it} onOpen={() => openDetail(it.id)} />)}
            {!loading && data && data.items.length === 0 && (
              <tr><td style={{ ...td, color: '#9aa4b2' }} colSpan={6}>Ничего не найдено по заданным фильтрам.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {detail && <DetailModal d={detail} onClose={() => setDetail(null)} />}
    </div>
  )
}

function Row({ it, onOpen }: { it: AuditItem; onOpen: () => void }) {
  const et = it.entity_type === 'dashboard' ? 'Дашборд' : it.entity_type === 'widget' ? 'Виджет' : it.entity_type === 'object_acl' ? 'Права' : it.entity_type
  return (
    <tr>
      <td style={{ ...td, whiteSpace: 'nowrap', color: '#6b7280' }}>{fmtDt(it.created_at)}</td>
      <td style={td}>{actorText(it)}</td>
      <td style={td}><span style={{ color: ACTION_COLOR[it.action] || '#111827', fontWeight: 600 }}>{ACTION_LABEL[it.action] || it.action}</span></td>
      <td style={td}><span style={{ color: '#6b7280' }}>{et}:</span> {it.entity_name || <span style={{ color: '#9aa4b2' }}>{it.entity_id.slice(0, 8)}…</span>}</td>
      <td style={td}>{it.changed_fields.length ? <span style={{ color: '#9a6a00' }}>{it.changed_fields.join(', ')}</span> : <span style={{ color: '#9aa4b2' }}>—</span>}</td>
      <td style={{ ...td, whiteSpace: 'nowrap' }}><button style={linkBtn} onClick={onOpen}>подробнее</button></td>
    </tr>
  )
}

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function DetailModal({ d, onClose }: { d: AuditDetail; onClose: () => void }) {
  const et = d.entity_type === 'dashboard' ? 'Дашборд' : d.entity_type === 'widget' ? 'Виджет' : d.entity_type === 'object_acl' ? 'Права доступа' : d.entity_type
  const changed = d.diff.filter((f) => f.changed)
  return (
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>
            <span style={{ color: ACTION_COLOR[d.action] }}>{ACTION_LABEL[d.action] || d.action}</span> · {et}
          </div>
          <button style={{ ...xBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 4 }}>{d.entity_name || d.entity_id}</div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12, color: '#6b7280', marginBottom: 14 }}>
          <span>Автор: <b style={{ color: '#111827' }}>{actorText(d)}</b></span>
          <span>Время: {fmtDt(d.created_at)}</span>
          {d.ip_address && <span>IP: {d.ip_address}</span>}
        </div>

        {d.action === 'update' ? (
          changed.length === 0 ? <div style={muted}>Содержательных изменений полей нет.</div> : (
            <table style={{ borderCollapse: 'collapse', fontSize: 12, width: '100%' }}>
              <thead><tr>{['Поле', 'Было', 'Стало'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
              <tbody>
                {changed.map((f) => (
                  <tr key={f.field}>
                    <td style={{ ...td, fontWeight: 600, whiteSpace: 'nowrap' }}>{f.field}</td>
                    <td style={{ ...td, color: '#a32d2d', maxWidth: 260, wordBreak: 'break-word' }}>{fmtVal(f.old)}</td>
                    <td style={{ ...td, color: '#0f6e56', maxWidth: 260, wordBreak: 'break-word' }}>{fmtVal(f.new)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : (
          // create/publish/grant — снимок new; delete/revoke — снимок old (что было снято)
          (() => {
            const useOld = d.action === 'delete' || d.action === 'revoke_access'
            const colTitle = d.action === 'delete' ? 'Значение (до удаления)' : d.action === 'revoke_access' ? 'Значение (снято)' : 'Значение'
            const rows = d.diff.filter((f) => (useOld ? f.old : f.new) !== null && (useOld ? f.old : f.new) !== undefined)
            return (
          <table style={{ borderCollapse: 'collapse', fontSize: 12, width: '100%' }}>
            <thead><tr>{['Поле', colTitle].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
            <tbody>
              {rows.map((f) => {
                const v = useOld ? f.old : f.new
                return (
                  <tr key={f.field}>
                    <td style={{ ...td, fontWeight: 600, whiteSpace: 'nowrap' }}>{f.field}</td>
                    <td style={{ ...td, maxWidth: 420, wordBreak: 'break-word' }}>{fmtVal(v)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
            )
          })()
        )}
      </div>
    </div>
  )
}

function F({ t, children }: { t: string; children: React.ReactNode }) {
  return <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12, color: '#6b7280' }}>{t}{children}</label>
}

const input: React.CSSProperties = { height: 34, padding: '0 10px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 13, background: '#fff' }
const linkBtn: React.CSSProperties = { border: 'none', background: 'none', color: '#2f5496', cursor: 'pointer', fontSize: 12, padding: 0 }
const ghostBtn: React.CSSProperties = { height: 34, padding: '0 12px', border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', color: '#6b7280', fontSize: 13, cursor: 'pointer' }
const pageBtn: React.CSSProperties = { height: 30, padding: '0 12px', border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', fontSize: 12, cursor: 'pointer' }
const xBtn: React.CSSProperties = { border: 'none', background: 'none', color: '#a32d2d', cursor: 'pointer', padding: 0, fontSize: 15 }
const th: React.CSSProperties = { border: '1px solid #eef0f3', padding: '6px 10px', background: '#f9fafb', textAlign: 'left', color: '#6b7280', fontWeight: 600 }
const td: React.CSSProperties = { border: '1px solid #eef0f3', padding: '6px 10px', verticalAlign: 'top' }
const muted: React.CSSProperties = { color: '#9aa4b2', fontSize: 13 }
const errBox: React.CSSProperties = { background: '#fcebeb', color: '#a32d2d', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60, padding: 20 }
const dialog: React.CSSProperties = { background: '#fff', borderRadius: 14, padding: 22, width: 640, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }
