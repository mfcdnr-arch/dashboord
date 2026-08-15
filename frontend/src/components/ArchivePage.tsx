// Архив дашбордов: месячные папки слепков, поиск по имени/теме, просмотр
// замороженных данных, экспорт, возврат из архива, избирательный доступ.
import { useCallback, useEffect, useState } from 'react'
import {
  ArchiveAccessRow, ArchiveFull, ArchiveItem, ArchiveMonth,
  addArchiveAccess, archiveMonths, archiveTopics, deleteArchive, exportArchiveXlsx,
  getArchive, listArchive, listArchiveAccess, removeArchiveAccess, unarchive,
} from '../api/archive'
import { listUsers, AppUser } from '../api/users'
import WidgetView from './WidgetView'
import { useConfirm } from './dashboards/ConfirmDialog'
import { btn, btnGhost, crumb, dialog, errBox, input, linkDanger, muted, overlay, sel, widgetCard, wtBadge } from './dashboards/shared'

const MONTHS_RU = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
export function monthLabel(m: string): string {
  const [y, mm] = m.split('-')
  const i = Number(mm) - 1
  return i >= 0 && i < 12 ? `${MONTHS_RU[i]} ${y}` : m
}
const fmtDT = (s: string) => new Date(s).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })

export default function ArchivePage({ canManage, isAdmin }: { canManage: boolean; isAdmin: boolean }) {
  // Подтверждения — своим окном: системное браузер вправе подавить, и кнопка
  // необратимого действия выглядит нерабочей (см. ConfirmDialog).
  const { ask, node: confirmNode } = useConfirm()
  const [months, setMonths] = useState<ArchiveMonth[]>([])
  const [topics, setTopics] = useState<string[]>([])
  const [month, setMonth] = useState<string>('')
  const [topic, setTopic] = useState<string>('')
  const [q, setQ] = useState('')
  const [archFrom, setArchFrom] = useState('')
  const [archTo, setArchTo] = useState('')
  const [items, setItems] = useState<ArchiveItem[]>([])
  const [opened, setOpened] = useState<ArchiveFull | null>(null)
  const [page, setPage] = useState(0)
  const [err, setErr] = useState<string | null>(null)
  const [accessOpen, setAccessOpen] = useState(false)

  const reload = useCallback(() => {
    setErr(null)
    Promise.all([archiveMonths(), archiveTopics(),
      listArchive(month || undefined, q || undefined, topic || undefined, archFrom || undefined, archTo || undefined)])
      .then(([m, t, it]) => { setMonths(m); setTopics(t); setItems(it) })
      .catch((e) => setErr((e as Error).message))
  }, [month, q, topic, archFrom, archTo])
  useEffect(() => { const t = setTimeout(reload, 250); return () => clearTimeout(t) }, [reload])

  const open = (id: string) => { setPage(0); getArchive(id).then(setOpened).catch((e) => setErr((e as Error).message)) }

  const doUnarchive = async (a: ArchiveItem) => {
    if (!await ask({
      title: `Вернуть дашборд «${a.dashboard_name}» в работу?`,
      message: 'Дашборд снова появится в разделе «Дашборды». Слепок останется в архиве.',
      confirmLabel: 'Вернуть', busyLabel: 'Возврат…', tone: 'accent',
    })) return
    unarchive(a.id).then(reload).catch((e) => setErr((e as Error).message))
  }
  const doDelete = async (a: ArchiveItem) => {
    if (!await ask({
      title: `Удалить слепок «${a.dashboard_name}»?`,
      message: `Слепок за ${monthLabel(a.archive_month)} и все замороженные в нём данные будут удалены `
        + 'безвозвратно — восстановить их будет нечем.',
    })) return
    deleteArchive(a.id).then(reload).catch((e) => setErr((e as Error).message))
  }

  // ── Просмотр слепка ─────────────────────────────────────────────────────────
  if (opened) {
    const pages = opened.snapshot.pages || []
    const cur = pages[Math.min(page, Math.max(0, pages.length - 1))]
    return (
      <div>
        <div style={{ marginBottom: 10 }}>
          <button style={crumb} onClick={() => setOpened(null)}>Архив</button>
          <span style={{ color: 'var(--text-faint)' }}> / </span>
          <span style={{ fontSize: 14 }}>{opened.dashboard_name}</span>
        </div>
        <div style={{ background: 'var(--accent-weak-bg)', border: '1px solid var(--accent)', borderRadius: 10,
          padding: '8px 12px', fontSize: 13, marginBottom: 12 }}>
          📦 Архивная копия от {fmtDT(opened.archived_at)} · данные зафиксированы на момент архивации
          {opened.topic && <> · тема: <b>{opened.topic}</b></>}
          {opened.auto && <> · создана автоархивацией</>}
          {opened.note && <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>{opened.note}</div>}
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
          {pages.map((p, i) => (
            <button key={i} style={{ ...btnGhost, ...(i === page ? { borderColor: 'var(--accent)', color: 'var(--accent)', background: 'var(--accent-weak-bg)' } : {}) }}
              onClick={() => setPage(i)}>{p.name}</button>
          ))}
          <button style={{ ...btnGhost, marginLeft: 'auto' }} onClick={() => exportArchiveXlsx(opened.id, opened.dashboard_name).catch((e) => setErr((e as Error).message))}>⤓ Excel (слепок)</button>
        </div>
        {err && <div style={errBox}>{err}</div>}
        {!cur || cur.widgets.length === 0 ? (
          <div style={muted}>На этой странице слепка нет виджетов.</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: 12 }}>
            {cur.widgets.map((w) => (
              <div key={w.id} style={{ ...widgetCard, gridColumn: `span ${Math.min(12, Math.max(3, w.w || 6))}` }}>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
                  <b style={{ fontSize: 14 }}>{w.name}</b>
                  <span style={wtBadge}>{w.widget_type}</span>
                </div>
                <WidgetView widgetId={w.id} batched injData={w.data} injError={w.error} showDrill={false} />
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  // ── Список ──────────────────────────────────────────────────────────────────
  return (
    <div>
      {confirmNode}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 20 }}>Архив дашбордов</h2>
        {canManage && <button style={{ ...btnGhost, marginLeft: 'auto' }} onClick={() => setAccessOpen(true)}>🔑 Доступ к архиву</button>}
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <input style={{ ...input, flex: 1, minWidth: 220 }} placeholder="🔍 Поиск по названию, теме или странице…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select style={sel} value={topic} onChange={(e) => setTopic(e.target.value)}>
          <option value="">Все темы</option>
          {topics.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--text-muted)' }}>
          архивирован с <input type="date" style={{ ...input, width: 140 }} value={archFrom} onChange={(e) => setArchFrom(e.target.value)} />
          по <input type="date" style={{ ...input, width: 140 }} value={archTo} onChange={(e) => setArchTo(e.target.value)} />
        </label>
        {(archFrom || archTo) && <button style={btnGhost} onClick={() => { setArchFrom(''); setArchTo('') }}>✕ дата</button>}
      </div>
      {err && <div style={errBox}>{err}</div>}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ minWidth: 170 }}>
          <MonthBtn active={month === ''} label="Все месяцы" count={months.reduce((a, m) => a + m.count, 0)} onClick={() => setMonth('')} />
          {months.map((m) => (
            <MonthBtn key={m.month} active={month === m.month} label={monthLabel(m.month)} count={m.count} onClick={() => setMonth(m.month)} />
          ))}
          {months.length === 0 && <div style={muted}>Архив пуст</div>}
        </div>
        <div style={{ flex: 1, minWidth: 300 }}>
          {items.length === 0 ? (
            <div style={muted}>Ничего не найдено{month ? ` за ${monthLabel(month)}` : ''}.</div>
          ) : items.map((a) => (
            <div key={a.id} style={{ ...widgetCard, marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <b style={{ fontSize: 15, cursor: 'pointer' }} onClick={() => open(a.id)}>{a.dashboard_name}</b>
                {a.topic && <span style={wtBadge}>{a.topic}</span>}
                {a.auto && <span style={{ ...wtBadge, background: 'var(--surface-3)', color: 'var(--text-muted)' }} title="Создан ежемесячной автоархивацией">📅 авто</span>}
                <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-faint)' }}>{monthLabel(a.archive_month)}</span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                {fmtDT(a.archived_at)}{a.archived_by_name ? ` · ${a.archived_by_name}` : ''} · страниц: {a.pages}
                {a.note && <> · {a.note}</>}
              </div>
              <div style={{ display: 'flex', gap: 10, marginTop: 8, alignItems: 'center' }}>
                <button style={{ ...btnGhost, height: 30, fontSize: 13 }} onClick={() => open(a.id)}>Открыть</button>
                <button style={{ ...btnGhost, height: 30, fontSize: 13 }} onClick={() => exportArchiveXlsx(a.id, a.dashboard_name).catch((e) => setErr((e as Error).message))}>⤓ Excel</button>
                {canManage && a.dashboard_id && (
                  <button style={{ ...btnGhost, height: 30, fontSize: 13 }} onClick={() => doUnarchive(a)}>↩ Вернуть из архива</button>
                )}
                {isAdmin && <button style={{ ...linkDanger, marginLeft: 'auto' }} onClick={() => doDelete(a)}>удалить слепок</button>}
              </div>
            </div>
          ))}
        </div>
      </div>
      {accessOpen && <AccessDialog onClose={() => setAccessOpen(false)} />}
    </div>
  )
}

function MonthBtn({ active, label, count, onClick }: { active: boolean; label: string; count: number; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      display: 'flex', width: '100%', alignItems: 'center', justifyContent: 'space-between', gap: 8,
      border: 'none', borderRadius: 8, padding: '8px 10px', marginBottom: 2, cursor: 'pointer', fontSize: 13,
      background: active ? 'var(--accent-weak-bg)' : 'transparent', color: active ? 'var(--accent)' : 'var(--text-2)',
    }}>
      <span>📁 {label}</span><span style={{ fontSize: 12, color: 'var(--text-faint)' }}>{count}</span>
    </button>
  )
}

// Диалог избирательного доступа: кому из обычных пользователей виден архив.
function AccessDialog({ onClose }: { onClose: () => void }) {
  const [rows, setRows] = useState<ArchiveAccessRow[]>([])
  const [users, setUsers] = useState<AppUser[]>([])
  const [uid, setUid] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const reload = () => listArchiveAccess().then(setRows).catch((e) => setErr((e as Error).message))
  useEffect(() => { reload(); listUsers('', 500, 0).then((p) => setUsers(p.items)).catch(() => {}) }, [])
  const free = users.filter((u) => !rows.some((r) => r.user_id === u.id))
  return (
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 520 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
          <b style={{ fontSize: 16 }}>🔑 Доступ к архиву</b>
          <button style={{ marginLeft: 'auto', ...btnGhost, height: 30 }} onClick={onClose}>✕</button>
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 12 }}>
          Администраторы и модераторы видят архив всегда. Ниже — обычные пользователи, которым выдан допуск
          (они видят весь архив: слепки содержат полные данные).
        </div>
        {err && <div style={errBox}>{err}</div>}
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <select style={{ ...sel, flex: 1 }} value={uid} onChange={(e) => setUid(e.target.value)}>
            <option value="">— выберите пользователя —</option>
            {free.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.login} ({u.login})</option>)}
          </select>
          <button style={btn} disabled={!uid} onClick={() => addArchiveAccess(uid).then(() => { setUid(''); reload() }).catch((e) => setErr((e as Error).message))}>Выдать</button>
        </div>
        {rows.length === 0 ? <div style={muted}>Допусков пока нет.</div> : rows.map((r) => (
          <div key={r.user_id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
            <span style={{ fontSize: 14 }}>{r.full_name || r.login}</span>
            <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>({r.login})</span>
            <button style={{ ...linkDanger, marginLeft: 'auto' }} onClick={() => removeArchiveAccess(r.user_id).then(reload).catch((e) => setErr((e as Error).message))}>отозвать</button>
          </div>
        ))}
      </div>
    </div>
  )
}
