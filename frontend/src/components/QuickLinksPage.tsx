import { useCallback, useEffect, useState } from 'react'
import {
  allowedQuickLinkSections, createQuickLink, deleteQuickLink, listDashboards, listQuickLinks,
  reorderQuickLinks, type Dashboard, type QuickLink,
} from '../api'

const SECTION_LABEL: Record<string, string> = {
  dashboards: 'Дашборды', instructions: 'Инструкции', leadership: 'Руководителю',
  showcases: 'Витрины', dnrstats: 'Статистика услуг', archive: 'Архив',
}

/**
 * «Быстрый доступ» — куратор-меню коротких названий отчётов («MAX», «КЭП»,
 * «Статистика отделов»…), составляемое администратором из уже распознанных
 * форм и дашбордов. Видит и открывает КАЖДЫЙ пользователь — но сервер уже
 * отфильтровал пункты по видимости для него самого (RLS дашборда / гейт
 * раздела), поэтому фронту достаточно просто отрисовать то, что пришло.
 */
export default function QuickLinksPage(
  { canManage, onOpenDashboard, onGoto }:
  { canManage: boolean; onOpenDashboard: (id: string) => void; onGoto: (section: string) => void },
) {
  const [items, setItems] = useState<QuickLink[]>([])
  const [err, setErr] = useState('')
  const [editing, setEditing] = useState(false)

  const load = useCallback(async () => {
    try { setItems((await listQuickLinks()).items) } catch (e) { setErr((e as Error).message) }
  }, [])
  useEffect(() => { load() }, [load])

  function open(l: QuickLink) {
    if (l.kind === 'dashboard') onOpenDashboard(l.dashboard_id)
    else onGoto(l.section)
  }

  async function move(i: number, dir: -1 | 1) {
    const j = i + dir
    if (j < 0 || j >= items.length) return
    const next = items.slice()
    ;[next[i], next[j]] = [next[j], next[i]]
    setItems(next)
    try { await reorderQuickLinks(next.map((x) => x.id)) } catch (e) { setErr((e as Error).message); load() }
  }

  async function remove(id: string) {
    try { await deleteQuickLink(id); load() } catch (e) { setErr((e as Error).message) }
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Быстрый доступ</h2>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 14 }}>
        Короткие ссылки на уже узнаваемые отчёты — вместо поиска дашборда по полному названию.
        {canManage && ' Каждый видит только те пункты, которые ему открыты.'}
      </div>

      {err && <div style={{ ...box('var(--danger)'), marginBottom: 12 }}>{err}</div>}

      {items.length === 0 && !editing && (
        <div style={{ ...box('var(--border)'), color: 'var(--text-muted)' }}>
          {canManage
            ? 'Меню пока пустое — добавьте первый пункт кнопкой ниже.'
            : 'Администратор ещё не составил меню быстрого доступа.'}
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: canManage ? 18 : 0 }}>
        {items.map((l, i) => (
          <div key={l.id} style={tile}>
            <button type="button" style={tileBtn} onClick={() => open(l)}
              title={l.kind === 'dashboard' ? (l.dashboard_name || l.label) : SECTION_LABEL[l.section] || l.section}>
              {l.label}
            </button>
            {canManage && editing && (
              <div style={{ display: 'flex', gap: 2 }}>
                <button type="button" style={miniBtn} disabled={i === 0} onClick={() => move(i, -1)}>▲</button>
                <button type="button" style={miniBtn} disabled={i === items.length - 1} onClick={() => move(i, 1)}>▼</button>
                <button type="button" style={{ ...miniBtn, color: 'var(--danger)' }} onClick={() => remove(l.id)}>✕</button>
              </div>
            )}
          </div>
        ))}
      </div>

      {canManage && (
        <div>
          <button type="button" style={linkBtn} onClick={() => setEditing((v) => !v)}>
            {editing ? 'скрыть настройку меню' : '✎ настроить меню'}
          </button>
          {editing && <Editor onAdded={load} />}
        </div>
      )}
    </div>
  )
}

function Editor({ onAdded }: { onAdded: () => void }) {
  const [label, setLabel] = useState('')
  const [kind, setKind] = useState<'dashboard' | 'section'>('dashboard')
  const [dashboards, setDashboards] = useState<Dashboard[]>([])
  const [dashboardId, setDashboardId] = useState('')
  const [sections, setSections] = useState<string[]>([])
  const [section, setSection] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    listDashboards('', false, 200).then((p) => setDashboards(p.items)).catch(() => {})
    allowedQuickLinkSections().then((r) => setSections(r.sections)).catch(() => {})
  }, [])

  async function add() {
    if (!label.trim()) { setErr('Укажите короткое название пункта'); return }
    if (kind === 'dashboard' && !dashboardId) { setErr('Выберите дашборд'); return }
    if (kind === 'section' && !section) { setErr('Выберите раздел'); return }
    setBusy(true); setErr('')
    try {
      await createQuickLink({ label: label.trim(), kind, dashboard_id: kind === 'dashboard' ? dashboardId : undefined,
                              section: kind === 'section' ? section : undefined })
      setLabel(''); setDashboardId(''); setSection('')
      onAdded()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <div style={{ ...box('var(--border)'), marginTop: 10, maxWidth: 520 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Добавить пункт меню</div>
      {err && <div style={{ color: 'var(--danger)', fontSize: 12.5, marginBottom: 8 }}>{err}</div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={40}
          placeholder="Короткое название (например, MAX)" style={input} />
        <div style={{ display: 'flex', gap: 12, fontSize: 13 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
            <input type="radio" checked={kind === 'dashboard'} onChange={() => setKind('dashboard')} /> дашборд
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
            <input type="radio" checked={kind === 'section'} onChange={() => setKind('section')} /> раздел
          </label>
        </div>
        {kind === 'dashboard' ? (
          <select value={dashboardId} onChange={(e) => setDashboardId(e.target.value)} style={input}>
            <option value="">— выберите дашборд —</option>
            {dashboards.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        ) : (
          <select value={section} onChange={(e) => setSection(e.target.value)} style={input}>
            <option value="">— выберите раздел —</option>
            {sections.map((s) => <option key={s} value={s}>{SECTION_LABEL[s] || s}</option>)}
          </select>
        )}
        <button type="button" style={btn} disabled={busy} onClick={add}>
          {busy ? 'Добавляем…' : '＋ Добавить'}
        </button>
      </div>
    </div>
  )
}

const tile: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 4, border: '1px solid var(--border)',
  borderRadius: 10, background: 'var(--surface)',
}
const tileBtn: React.CSSProperties = {
  padding: '10px 16px', border: 'none', background: 'none', cursor: 'pointer',
  fontSize: 14, fontWeight: 600, color: 'var(--accent)',
}
const miniBtn: React.CSSProperties = {
  border: 'none', background: 'none', cursor: 'pointer', fontSize: 11, color: 'var(--text-muted)', padding: '0 4px',
}
const linkBtn: React.CSSProperties = {
  background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--accent)',
  fontSize: 13, textDecoration: 'underline dotted',
}
const input: React.CSSProperties = {
  padding: '7px 9px', border: '1px solid var(--border)', borderRadius: 8,
  background: 'var(--surface)', color: 'var(--text)', fontSize: 13,
}
const btn: React.CSSProperties = {
  height: 34, padding: '0 14px', border: 'none', borderRadius: 8,
  background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer', alignSelf: 'flex-start',
}
function box(color: string): React.CSSProperties {
  return { border: `1px solid ${color}`, borderRadius: 10, padding: '10px 12px', fontSize: 13 }
}
