import { sel } from './shared'

/**
 * Условия отбора строк формы (подсчёт и «лента» таблицы, 08.10.2026).
 *
 * Те же условия, что понимает сервер (`_tally.OPS`): строка проходит, если
 * выполнены ВСЕ условия. Значение хранится строкой, как его ввёл человек, а в
 * конфигурацию виджета уходит уже числом или списком (`whereToConfig`) — иначе
 * «больше 15» сравнивало бы текст «15», а «одно из» — одну строку с запятыми.
 */
export type WhereCond = { field: string; op: string; value: string }

export const WHERE_OPS: { v: string; t: string; value: 'text' | 'number' | 'list' | null }[] = [
  { v: 'eq', t: 'равно', value: 'text' },
  { v: 'ne', t: 'не равно', value: 'text' },
  { v: 'in', t: 'одно из (через запятую)', value: 'list' },
  { v: 'contains', t: 'содержит', value: 'text' },
  { v: 'gte', t: 'не меньше', value: 'number' },
  { v: 'gt', t: 'больше', value: 'number' },
  { v: 'lte', t: 'не больше', value: 'number' },
  { v: 'lt', t: 'меньше', value: 'number' },
  { v: 'filled', t: 'заполнена', value: null },
  { v: 'empty', t: 'пуста', value: null },
  { v: 'date_before_report', t: 'срок истёк на дату отчёта', value: null },
]

// Не `?.value ?? 'text'`: у условий без значения оно null, и `??` подменило
// бы его на 'text' — «пуста» и «срок истёк» требовали бы значение и молча
// выбрасывались из конфигурации (поймано тестом).
const kindOf = (op: string) => {
  const o = WHERE_OPS.find((x) => x.v === op)
  return o ? o.value : 'text'
}

/** Условия из сохранённой конфигурации — в вид, удобный для правки. */
export function whereFromConfig(raw: unknown): WhereCond[] {
  if (!Array.isArray(raw)) return []
  return raw.filter((c) => c && typeof c === 'object' && (c as { field?: string }).field).map((c) => {
    const x = c as { field: string; op?: string; value?: unknown }
    const v = Array.isArray(x.value) ? x.value.join(', ') : x.value == null ? '' : String(x.value)
    return { field: x.field, op: x.op || 'eq', value: v }
  })
}

/** Условия для конфигурации виджета. Неполные (без графы или без значения там,
 *  где оно нужно) не отправляются: сервер отверг бы их, а предпросмотр показал
 *  бы ошибку на каждый набранный символ. */
export function whereToConfig(conds: WhereCond[]): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = []
  for (const c of conds) {
    if (!c.field) continue
    const kind = kindOf(c.op)
    if (kind === null) { out.push({ field: c.field, op: c.op }); continue }
    const raw = c.value.trim()
    if (!raw) continue
    if (kind === 'number') {
      const n = Number(raw.replace(',', '.'))
      if (Number.isFinite(n)) out.push({ field: c.field, op: c.op, value: n })
    } else if (kind === 'list') {
      const list = raw.split(',').map((x) => x.trim()).filter(Boolean)
      if (list.length) out.push({ field: c.field, op: c.op, value: list })
    } else {
      out.push({ field: c.field, op: c.op, value: raw })
    }
  }
  return out
}

export function WhereEditor({ fields, value, onChange, title }: {
  fields: { code: string; name: string }[]
  value: WhereCond[]
  onChange: (next: WhereCond[]) => void
  title: string
}) {
  const set = (i: number, patch: Partial<WhereCond>) =>
    onChange(value.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  return (
    <div style={{ flexBasis: '100%' }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', margin: '6px 0 4px' }}>{title}</div>
      {value.map((c, i) => {
        const kind = kindOf(c.op)
        const fname = fields.find((f) => f.code === c.field)?.name || 'графа'
        return (
          // Ряд не переносится: при переносе крестик «убрать» уезжал на
          // отдельную строку и читался как принадлежащий следующему условию.
          // Вместо этого поля сжимаются.
          <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'nowrap', marginBottom: 4 }}>
            <select style={{ ...sel, flex: '1 1 160px', minWidth: 0, maxWidth: 260 }} aria-label={`Графа условия ${i + 1}`}
              value={c.field} onChange={(e) => set(i, { field: e.target.value })}>
              <option value="">— графа —</option>
              {fields.map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}
            </select>
            <select style={{ ...sel, flex: '0 1 auto', minWidth: 0, maxWidth: 220 }} aria-label={`Условие для «${fname}»`} value={c.op}
              onChange={(e) => set(i, { op: e.target.value })}>
              {WHERE_OPS.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}
            </select>
            {kind !== null && (
              <input style={{ ...sel, flex: '1 1 120px', minWidth: 0, width: 'auto', boxSizing: 'border-box' }} aria-label={`Значение для «${fname}»`}
                inputMode={kind === 'number' ? 'decimal' : undefined}
                placeholder={kind === 'list' ? 'например: В работе, Отложен' : kind === 'number' ? 'число' : 'значение'}
                value={c.value} onChange={(e) => set(i, { value: e.target.value })} />
            )}
            <button type="button" aria-label={`Убрать условие ${i + 1}`} title="Убрать условие"
              onClick={() => onChange(value.filter((_, j) => j !== i))}
              style={{ border: 'none', background: 'none', color: 'var(--danger)', cursor: 'pointer', fontSize: 14, flexShrink: 0 }}>✕</button>
          </div>
        )
      })}
      <button type="button" onClick={() => onChange([...value, { field: '', op: 'eq', value: '' }])}
        style={{ border: 'none', background: 'none', color: 'var(--accent-text)', cursor: 'pointer', fontSize: 12, padding: 0 }}>
        ＋ условие
      </button>
    </div>
  )
}
