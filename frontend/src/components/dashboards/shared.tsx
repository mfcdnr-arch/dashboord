// Общие константы, стили и мелкие хелперы раздела «Дашборды» (вынесено из DashboardsPage.tsx).

// размеры по умолчанию для новых виджетов (сетка cols=12, rowHeight=40)
export const DEFAULT_SIZE: Record<string, { w: number; h: number }> = {
  kpi: { w: 3, h: 3 }, gauge: { w: 3, h: 5 }, plan_fact: { w: 4, h: 5 }, table: { w: 6, h: 6 },
  bar: { w: 5, h: 6 }, line: { w: 5, h: 6 }, pie: { w: 4, h: 6 },
  dynamics: { w: 6, h: 6 }, yoy: { w: 6, h: 6 }, compare: { w: 6, h: 7 }, heatmap: { w: 6, h: 7 }, pivot: { w: 6, h: 6 }, waterfall: { w: 6, h: 6 },
  objects_compare: { w: 6, h: 6 }, text: { w: 6, h: 2 }, image: { w: 3, h: 3 },
}

export const WT = [
  { v: 'kpi', t: 'KPI (число)' }, { v: 'gauge', t: 'Спидометр (gauge)' }, { v: 'bar', t: 'Столбцы' }, { v: 'line', t: 'Линия' },
  { v: 'pie', t: 'Круговая' }, { v: 'table', t: 'Таблица' }, { v: 'plan_fact', t: 'План-факт' },
  { v: 'dynamics', t: 'Динамика (периоды)' }, { v: 'yoy', t: 'Год к году' }, { v: 'compare', t: 'Сравнение (неск. полей)' },
  { v: 'waterfall', t: 'Водопад' }, { v: 'objects_compare', t: 'Сравнение подразделений' },
  { v: 'heatmap', t: 'Тепловая карта' }, { v: 'pivot', t: 'Сводная таблица' },
  { v: 'text', t: 'Текст/заголовок' }, { v: 'image', t: 'Картинка/лого' },
]

export function F({ t, children }: { t: string; children: React.ReactNode }) {
  return <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 11, color: 'var(--text-muted)' }}>{t}{children}</label>
}

export function PubBadge({ status }: { status: string }) {
  const m: Record<string, { t: string; bg: string; c: string }> = {
    draft: { t: 'черновик', bg: 'var(--surface-3)', c: 'var(--text-muted)' },
    review: { t: 'на проверке', bg: 'var(--warn-bg)', c: 'var(--warn)' },
    published: { t: 'опубликован', bg: 'var(--success-bg)', c: 'var(--success)' },
    archived: { t: 'в архиве', bg: 'var(--surface-3)', c: 'var(--text-faint)' },
  }
  const s = m[status] || m.draft
  return <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 12, background: s.bg, color: s.c }}>{s.t}</span>
}

export const crumb: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 14, padding: 0 }
export const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14 }
export const sel: React.CSSProperties = { height: 34, padding: '0 8px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13, background: 'var(--surface)' }
export const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
export const btnAuto: React.CSSProperties = { height: 36, padding: '0 14px', border: '1px solid var(--accent)', borderRadius: 8, background: 'var(--accent-weak-bg)', color: 'var(--accent)', fontSize: 14, cursor: 'pointer' }
export const btnGhost: React.CSSProperties = { height: 36, padding: '0 14px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text-2)', fontSize: 14, cursor: 'pointer' }
export const rowForm: React.CSSProperties = { display: 'flex', gap: 8, marginBottom: 16 }
export const rowItem: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', cursor: 'pointer' }
export const tab: React.CSSProperties = { height: 34, padding: '0 14px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', cursor: 'pointer', fontSize: 13 }
export const presetChip: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, background: 'var(--accent-weak-bg)', padding: '3px 10px', borderRadius: 12 }
export const tabActive: React.CSSProperties = { background: 'var(--accent-weak-bg)', border: '1px solid var(--accent)', color: 'var(--accent)' }
export const widgetCard: React.CSSProperties = { border: '1px solid var(--border)', borderRadius: 12, padding: 14, background: 'var(--surface)' }
export const wtBadge: React.CSSProperties = { marginLeft: 8, fontSize: 11, padding: '1px 7px', borderRadius: 8, background: 'var(--accent-weak-bg)', color: 'var(--accent)' }
export const rmBtn: React.CSSProperties = { marginLeft: 'auto', width: 24, height: 24, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', cursor: 'pointer', color: 'var(--danger)' }
export const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 14, padding: '8px 0' }
export const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
export const linkDanger: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--danger)', cursor: 'pointer', fontSize: 12, padding: 0 }
export const alertBtn: React.CSSProperties = { marginLeft: 8, width: 24, height: 24, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', cursor: 'pointer', color: 'var(--warn)' }
export const editBtn: React.CSSProperties = { marginLeft: 8, width: 24, height: 24, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', cursor: 'pointer', color: 'var(--accent)' }
export const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60, padding: 20 }
export const dialog: React.CSSProperties = { background: 'var(--surface)', borderRadius: 14, padding: 22, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }
