import { useState } from 'react'
import { updateWidget, type Widget } from '../../api'
import { F, btn, btnGhost, dialog, muted, overlay, rmBtn, sel } from './shared'

// ── Редактор порогов KPI-алерта (условное форматирование) ──────────────────
type AlertRule = { level: string; op: string; value: string; value2?: string; label?: string }
const LEVELS = [
  { v: 'danger', t: 'Критично (красный)' }, { v: 'warn', t: 'Внимание (жёлтый)' }, { v: 'good', t: 'Хорошо (зелёный)' },
]
const OPS = [
  { v: 'lt', t: '<' }, { v: 'lte', t: '≤' }, { v: 'gt', t: '>' }, { v: 'gte', t: '≥' },
  { v: 'eq', t: '=' }, { v: 'between', t: 'в диапазоне' }, { v: 'outside', t: 'вне диапазона' },
]
// Готовый набор «нормы плана» — тот же, что авто-сборка ставит сама
// (backend `_suggest.PLAN_PCT_ALERTS`). Пустое окно с предложением составить
// правило с нуля мало кому помогало: человек знает, что «ниже плана — плохо»,
// но не обязан переводить это в набор условий.
const PLAN_PRESET: AlertRule[] = [
  { level: 'danger', op: 'lt', value: '90', label: 'ниже 90 % плана' },
  { level: 'warn', op: 'lt', value: '100', label: 'план не выполнен' },
  { level: 'good', op: 'gte', value: '100', label: 'план выполнен' },
]

const ALERT_ON: Record<string, { v: string; t: string }[]> = {
  plan_fact: [{ v: 'pct', t: 'Выполнение, %' }, { v: 'fact', t: 'Факт' }, { v: 'delta', t: 'Δ (факт−план)' }, { v: 'plan', t: 'План' }],
  dynamics: [{ v: 'last', t: 'Последний период' }, { v: 'change', t: 'Δ к пред.' }, { v: 'change_pct', t: 'Δ %, к пред.' }],
}

export function AlertEditor({ widget, onClose, onSaved }: { widget: Widget; onClose: () => void; onSaved: () => void }) {
  const cfg = (widget.config || {}) as Record<string, unknown>
  const init = (cfg.alerts as AlertRule[] | undefined)?.map((r) => ({
    level: r.level || 'danger', op: r.op || 'lt', value: String(r.value ?? ''),
    value2: r.value2 != null ? String(r.value2) : '', label: r.label || '',
  })) || []
  const [rules, setRules] = useState<AlertRule[]>(init)
  const [alertOn, setAlertOn] = useState<string>((cfg.alert_on as string) || (widget.widget_type === 'plan_fact' ? 'pct' : widget.widget_type === 'dynamics' ? 'last' : 'value'))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const onOpts = ALERT_ON[widget.widget_type]
  // Готовую норму предлагаем только там, где сравнивается процент: у полосы
  // «план-факт» это выполнение, у карточки и спидометра — само значение, и
  // «90 / 100» имеет смысл, лишь когда оно в процентах.
  const planPresetFits = widget.widget_type === 'plan_fact'
    || String((cfg.unit as string) || '').includes('%')

  const set = (i: number, patch: Partial<AlertRule>) => setRules((rs) => rs.map((r, k) => k === i ? { ...r, ...patch } : r))
  const add = () => setRules((rs) => [...rs, { level: 'danger', op: 'lt', value: '', value2: '', label: '' }])
  const del = (i: number) => setRules((rs) => rs.filter((_, k) => k !== i))

  async function save() {
    setErr(null)
    const clean: any[] = []
    for (const r of rules) {
      if (r.value === '' || isNaN(Number(r.value))) { setErr('Заполните числовой порог во всех правилах'); return }
      const rule: any = { level: r.level, op: r.op, value: Number(r.value) }
      if (r.op === 'between' || r.op === 'outside') {
        if (r.value2 === '' || isNaN(Number(r.value2))) { setErr('Для диапазона нужны два значения'); return }
        rule.value2 = Number(r.value2)
      }
      if (r.label?.trim()) rule.label = r.label.trim()
      clean.push(rule)
    }
    const newCfg: Record<string, unknown> = { ...cfg, alerts: clean }
    if (onOpts) newCfg.alert_on = alertOn; else delete newCfg.alert_on
    setBusy(true)
    try { await updateWidget(widget.id, { config: newCfg }); onSaved() }
    catch (e) { setErr((e as Error).message); setBusy(false) }
  }

  return (
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 640 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>⚠ Подсветка по порогам: {widget.name}</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
          Виджет красится, когда значение переходит заданную границу: красным — когда всё плохо,
          жёлтым — когда близко, зелёным — когда норма достигнута. Правила проверяются сверху
          вниз, срабатывает первое подходящее.
        </div>

        {onOpts && (
          <div style={{ marginBottom: 12 }}>
            <F t="Сравнивать по">
              <select style={sel} value={alertOn} onChange={(e) => setAlertOn(e.target.value)}>
                {onOpts.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}
              </select>
            </F>
          </div>
        )}

        {rules.length === 0 && (
          <div style={{ ...muted, marginBottom: 10 }}>
            Порогов пока нет — виджет всегда одного цвета.
            {planPresetFits && (
              <>
                {' '}Если это выполнение плана, подставьте готовую норму:{' '}
                <button style={{ ...btnGhost, height: 26, padding: '0 8px', fontSize: 12 }}
                  onClick={() => setRules(PLAN_PRESET.map((r) => ({ ...r })))}>
                  90 / 100 %
                </button>
              </>
            )}
          </div>
        )}
        {rules.map((r, i) => (
          <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 8, borderBottom: '1px solid var(--surface-2)', paddingBottom: 8 }}>
            <F t="Уровень"><select style={sel} value={r.level} onChange={(e) => set(i, { level: e.target.value })}>{LEVELS.map((l) => <option key={l.v} value={l.v}>{l.t}</option>)}</select></F>
            <F t="Условие"><select style={sel} value={r.op} onChange={(e) => set(i, { op: e.target.value })}>{OPS.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}</select></F>
            <F t="Значение"><input style={{ ...sel, width: 90 }} type="number" value={r.value} onChange={(e) => set(i, { value: e.target.value })} /></F>
            {(r.op === 'between' || r.op === 'outside') && (
              <F t="…до"><input style={{ ...sel, width: 90 }} type="number" value={r.value2} onChange={(e) => set(i, { value2: e.target.value })} /></F>
            )}
            <F t="Подпись (необяз.)"><input style={{ ...sel, width: 150 }} placeholder="напр. План не выполнен" value={r.label} onChange={(e) => set(i, { label: e.target.value })} /></F>
            <button style={rmBtn} onClick={() => del(i)} title="Удалить правило">✕</button>
          </div>
        ))}

        {err && <div style={{ color: 'var(--danger)', fontSize: 13, marginTop: 6 }}>{err}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button style={btnGhost} onClick={add}>+ Правило</button>
          <button style={{ ...btn, marginLeft: 'auto' }} disabled={busy} onClick={save}>{busy ? 'Сохранение…' : 'Сохранить'}</button>
        </div>
      </div>
    </div>
  )
}
