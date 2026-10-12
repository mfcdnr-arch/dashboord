import { useEffect, useState } from 'react'
import { getCrossPresets, type CrossPart, type CrossPreset, type CrossSpec, type DataSources } from '../../api'
import Field from '../Field'
import { btnGhost, sel } from './shared'

// Конструктор показателя МЕЖДУ формами: «числитель ÷ знаменатель», где части
// берутся из РАЗНЫХ форм и соединяются по отделению и дню.
//
// Части одной стороны перемножаются: «окна × часы» — это окно-час, «ожидание ×
// талоны» — числитель взвешенного среднего. Значение — отношение СУММ по всем
// совпавшим парам «отделение × день» (см. backend `_crossform`): так считаются
// и «талонов на окно», и среднее, взвешенное по потоку.
//
// Готовые показатели (талонов на окно, на окно-час, взвешенное ожидание…)
// подставляются одним выбором — собирать руками нужно только своё.

export function emptyCross(sources: DataSources): CrossSpec {
  const ds = sources.datasets[0]
  const f = ds?.fields.find((x) => x.data_type === 'number')
  const part = { dataset_code: ds?.code || '', field: f?.code || '' }
  return { num: [part], den: [{ ...part }], unit: null }
}

export function crossValid(c: CrossSpec | null | undefined): boolean {
  if (!c || !c.num?.length || !c.den?.length) return false
  return [...c.num, ...c.den].every((p) => p.dataset_code && p.field)
}

export default function CrossBuilder({ sources, value, onChange, label }: {
  sources: DataSources; value: CrossSpec; onChange: (v: CrossSpec) => void; label?: string
}) {
  const [presets, setPresets] = useState<CrossPreset[]>([])
  useEffect(() => {
    let alive = true
    getCrossPresets().then((r) => { if (alive) setPresets(r.indicators) }).catch(() => { /* без готовых — собираем руками */ })
    return () => { alive = false }
  }, [])

  const numFields = (dc: string) => sources.datasets.find((d) => d.code === dc)?.fields.filter((f) => f.data_type === 'number') || []
  const fieldName = (p: CrossPart) => sources.datasets.find((d) => d.code === p.dataset_code)?.fields.find((f) => f.code === p.field)?.name || p.field
  const presetKey = presets.find((p) => sameParts(p.cross.num, value.num) && sameParts(p.cross.den, value.den))?.key || ''

  function setSide(side: 'num' | 'den', parts: CrossPart[]) {
    const next = { ...value, [side]: parts }
    // Части поменяли руками — имя готового показателя больше не про них.
    delete next.name
    // Привязка порога имеет смысл только к графе числителя — иначе снимаем.
    if (next.norm_field && !next.num.some((p) => p.field === next.norm_field)) delete next.norm_field
    onChange(next)
  }
  function applyPreset(key: string) {
    const p = presets.find((x) => x.key === key)
    if (!p) return
    // Имя готового показателя становится подписью оси: формула из имён граф
    // («(«Среднее время ожидания» × «Всего выдано талонов…») ÷ …») на оси
    // не помещается и сжимает сам график.
    onChange({ ...p.cross, ...(value.span ? { span: value.span } : {}), name: p.name })
  }

  const side = (key: 'num' | 'den', title: string, hint: string) => {
    const parts = value[key]
    return (
      <div style={{ flex: '1 1 280px', minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{title}</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>{hint}</div>
        {parts.map((p, i) => (
          <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6, minWidth: 0 }}>
            {i > 0 && <span aria-hidden style={{ color: 'var(--text-muted)' }}>×</span>}
            <select style={{ ...sel, flex: '1 1 40%' }} value={p.dataset_code}
              aria-label={`${title}: форма, часть ${i + 1}`}
              onChange={(e) => setSide(key, parts.map((x, j) => j === i
                ? { dataset_code: e.target.value, field: numFields(e.target.value)[0]?.code || '' } : x))}>
              {sources.datasets.map((d) => <option key={d.code} value={d.code}>{d.name || d.code}</option>)}
            </select>
            <select style={{ ...sel, flex: '1 1 60%' }} value={p.field}
              aria-label={`${title}: графа, часть ${i + 1}`}
              onChange={(e) => setSide(key, parts.map((x, j) => j === i ? { ...x, field: e.target.value } : x))}>
              {numFields(p.dataset_code).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}
            </select>
            <button type="button" style={{ ...btnGhost, height: 34, padding: '0 10px' }} disabled={parts.length <= 1}
              aria-label={`Убрать часть ${i + 1}: ${title}`} onClick={() => setSide(key, parts.filter((_, j) => j !== i))}>✕</button>
          </div>
        ))}
        {parts.length < 3 && (
          <button type="button" style={{ ...btnGhost, height: 30, fontSize: 12 }}
            onClick={() => setSide(key, [...parts, { dataset_code: parts[parts.length - 1]?.dataset_code || sources.datasets[0]?.code || '',
              field: numFields(parts[parts.length - 1]?.dataset_code || sources.datasets[0]?.code || '')[0]?.code || '' }])}>
            ＋ умножить на графу
          </button>
        )}
      </div>
    )
  }

  const formula = `${value.num.map(fieldName).join(' × ')} ÷ ${value.den.map(fieldName).join(' × ')}`
  return (
    <div style={{ flexBasis: '100%', border: '1px solid var(--border)', borderRadius: 10, padding: 10, minWidth: 0 }}>
      {label && <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>{label}</div>}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 8 }}>
        <Field size="sm" label="Готовый показатель">
          <select style={sel} value={presetKey} onChange={(e) => applyPreset(e.target.value)}>
            <option value="">{presets.length ? 'свой (собрать ниже)' : 'готовых нет — соберите ниже'}</option>
            {presets.map((p) => <option key={p.key} value={p.key} title={p.hint}>{p.name}</option>)}
          </select>
        </Field>
        <Field size="sm" label="Единица">
          <select style={sel} value={value.unit === 'мин' ? 'мин' : value.unit ? 'other' : ''}
            onChange={(e) => onChange({ ...value, unit: e.target.value === 'мин' ? 'мин' : e.target.value === 'other' ? (value.unit && value.unit !== 'мин' ? value.unit : 'ед.') : null })}>
            <option value="">без единицы</option>
            <option value="мин">время (минуты → «ч мин с»)</option>
            <option value="other">своя…</option>
          </select>
        </Field>
        {value.unit && value.unit !== 'мин' && (
          <Field size="sm" label="Своя единица">
            <input style={{ ...sel, width: 90 }} value={value.unit} onChange={(e) => onChange({ ...value, unit: e.target.value || 'ед.' })} />
          </Field>
        )}
        <Field size="sm" label="Порог показателя" hint="Порог графы применяется к показателю, только если они одного смысла: взвешенное ожидание ↔ «Среднее время ожидания». У отношения (талонов на окно) своего порога у графы нет.">
          <select style={sel} value={value.norm_field || ''}
            onChange={(e) => { const n = { ...value }; if (e.target.value) n.norm_field = e.target.value; else delete n.norm_field; onChange(n) }}>
            <option value="">не применять</option>
            {value.num.map((p) => <option key={p.field} value={p.field}>как у «{fieldName(p)}»</option>)}
          </select>
        </Field>
      </div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {side('num', 'Числитель', 'что считаем: талоны, принято, время × талоны')}
        {side('den', 'Знаменатель', 'на что делим: окна, окна × часы, талоны')}
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6, lineHeight: 1.45 }}>
        Получится: <b style={{ color: 'var(--text)' }}>{formula}</b>. Считается как сумма числителя, делённая на сумму
        знаменателя по всем отделениям и дням, где есть ВСЕ части, — отделение, которого нет хотя бы в одной форме,
        не учитывается, и виджет назовёт их число.
      </div>
    </div>
  )
}

function sameParts(a: CrossPart[], b: CrossPart[]): boolean {
  return a.length === b.length && a.every((p, i) => p.dataset_code === b[i].dataset_code && p.field === b[i].field)
}

export const SPAN_OPTIONS: { v: string; t: string }[] = [
  { v: 'last', t: 'последний день' },
  { v: '7', t: '7 дней с данными' },
  { v: '30', t: '30 дней с данными' },
  { v: 'all', t: 'вся история' },
]
