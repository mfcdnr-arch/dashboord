import { useEffect, useMemo, useState } from 'react'
import { buildTemplateFormula, listFormulaTemplates, type DataSources, type FormulaTemplate } from '../../api'

// Библиотека готовых метрик: пользователь выбирает рецепт («Процент», «Выполнение
// плана», «Прирост к прошлому периоду») и указывает столбцы выпадашками — формулу
// на языке системы собирает сервер. Знать синтаксис не нужно.
export default function TemplatePicker({ sources, onApply }: {
  sources: DataSources | null
  onApply: (formula: string, unit: string | null, name: string | null) => void
}) {
  const [items, setItems] = useState<FormulaTemplate[]>([])
  const [sel, setSel] = useState<FormulaTemplate | null>(null)
  const [values, setValues] = useState<Record<string, any>>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    listFormulaTemplates().then((r) => setItems(r.items)).catch((e) => setError((e as Error).message))
  }, [])

  const groups = useMemo(() => {
    const m = new Map<string, FormulaTemplate[]>()
    items.forEach((t) => m.set(t.group, [...(m.get(t.group) || []), t]))
    return [...m.entries()]
  }, [items])

  function pick(t: FormulaTemplate) {
    setSel(t); setValues({}); setError(null)
  }

  function setField(key: string, datasetCode: string, field: string) {
    setValues((v) => ({ ...v, [key]: { dataset_code: datasetCode, field } }))
  }

  async function apply() {
    if (!sel) return
    setBusy(true); setError(null)
    try {
      // Подписи столбцов идут вместе со значениями — из них сервер собирает
      // черновое название метрики, чтобы не заставлять придумывать его вручную.
      const labels: Record<string, string> = {}
      sel.inputs.forEach((i) => {
        const v = values[i.key]
        if (v?.field) {
          const ds = sources?.datasets.find((d) => d.code === v.dataset_code)
          labels[i.key] = ds?.fields.find((f) => f.code === v.field)?.name || v.field
        } else if (v?.metric_code) {
          labels[i.key] = sources?.metrics.find((m) => m.code === v.metric_code)?.name || v.metric_code
        }
      })
      const r = await buildTemplateFormula(sel.code, values, labels)
      onApply(r.formula, sel.unit, r.name)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 12, background: 'var(--surface-2)' }}>
      {error && <div style={{ color: 'var(--danger)', fontSize: 13, marginBottom: 8 }}>{error}</div>}
      {!sel && (
        <>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 10 }}>
            Выберите, что нужно посчитать — формулу система соберёт сама.
          </div>
          {groups.map(([group, list]) => (
            <div key={group} style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>{group}</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {list.map((t) => (
                  <button key={t.code} type="button" onClick={() => pick(t)} title={t.description}
                    style={{ textAlign: 'left', maxWidth: 260, padding: '8px 10px', borderRadius: 8, cursor: 'pointer',
                      border: '1px solid var(--border-strong)', background: 'var(--surface)', color: 'var(--text)' }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{t.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{t.description}</div>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </>
      )}

      {sel && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <button type="button" onClick={() => setSel(null)}
              style={{ border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 13, padding: 0 }}>← к списку</button>
            <b style={{ fontSize: 14 }}>{sel.name}</b>
            {sel.unit && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>· {sel.unit}</span>}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
            {sel.description} <i>Например: {sel.example}.</i>
          </div>

          {sel.inputs.map((inp) => (
            <div key={inp.key} style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 4 }}>
                {inp.label}
                {inp.agg && inp.agg !== 'SUM' && <span style={{ color: 'var(--text-muted)' }}> · {AGG_RU[inp.agg] || inp.agg}</span>}
              </div>
              {inp.kind === 'field' && (
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  <select style={sl} value={values[inp.key]?.dataset_code || ''}
                    onChange={(e) => setField(inp.key, e.target.value, '')}>
                    <option value="">датасет…</option>
                    {(sources?.datasets || []).map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
                  </select>
                  <select style={{ ...sl, minWidth: 260 }} value={values[inp.key]?.field || ''}
                    disabled={!values[inp.key]?.dataset_code}
                    onChange={(e) => setField(inp.key, values[inp.key].dataset_code, e.target.value)}>
                    <option value="">столбец…</option>
                    {(sources?.datasets.find((d) => d.code === values[inp.key]?.dataset_code)?.fields || [])
                      .filter((f) => !f.is_row_label)
                      .map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}
                  </select>
                </div>
              )}
              {inp.kind === 'metric' && (
                <select style={{ ...sl, minWidth: 300 }} value={values[inp.key]?.metric_code || ''}
                  onChange={(e) => setValues((v) => ({ ...v, [inp.key]: { metric_code: e.target.value } }))}>
                  <option value="">метрика…</option>
                  {(sources?.metrics || []).map((m) => <option key={m.code} value={m.code}>{m.name}</option>)}
                </select>
              )}
              {inp.kind === 'number' && (
                <input style={{ ...sl, width: 160 }} type="number" placeholder={inp.hint || 'число'}
                  value={values[inp.key] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [inp.key]: e.target.value }))} />
              )}
            </div>
          ))}

          <button type="button" onClick={apply} disabled={busy}
            style={{ height: 34, padding: '0 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
              background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, fontWeight: 600 }}>
            {busy ? 'Собираю…' : 'Подставить формулу'}
          </button>
        </>
      )}
    </div>
  )
}

const AGG_RU: Record<string, string> = { SUM: 'сумма', AVG: 'среднее', MIN: 'минимум', MAX: 'максимум', COUNT: 'количество' }
const sl: React.CSSProperties = {
  height: 32, padding: '0 8px', borderRadius: 8, border: '1px solid var(--border-strong)',
  background: 'var(--surface)', color: 'var(--text)', fontSize: 13, maxWidth: '100%',
}
