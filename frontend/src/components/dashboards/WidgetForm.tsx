import { useEffect, useState, type FormEvent } from 'react'
import { previewWidget, widgetSuggestions, type DataSources, type MetricSource, type Widget, type WidgetSpec } from '../../api'
import { WidgetPreviewBody } from '../WidgetView'
import FormulaBuilder from '../FormulaBuilder'
import { DEFAULT_SIZE, F, WT, btn, btnAuto, btnGhost, sel, wtBadge } from './shared'

export function SourceCatalog({ sources }: { sources: DataSources }) {
  const [open, setOpen] = useState(false)
  const [exp, setExp] = useState<string | null>(null)
  if (!open) {
    return (
      <button style={{ ...btnGhost, height: 34, marginBottom: 12 }} onClick={() => setOpen(true)}
        title="Какие документы, датасеты, поля, строки, показатели можно применить">
        📚 Каталог источников
      </button>
    )
  }
  const chip = (bg: string, color: string): React.CSSProperties => ({ display: 'inline-block', margin: '2px 4px 2px 0', padding: '1px 8px', borderRadius: 8, background: bg, color, fontSize: 12 })
  return (
    <div style={{ border: '1px solid #d1d5db', borderRadius: 10, padding: 12, marginBottom: 12, background: '#f8fafc' }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
        <b style={{ fontSize: 13 }}>📚 Каталог источников</b>
        <span style={{ fontSize: 12, color: '#6b7280', marginLeft: 8 }}>что можно применить в дашборде</span>
        <button style={{ ...btnGhost, height: 28, marginLeft: 'auto' }} onClick={() => setOpen(false)}>Скрыть</button>
      </div>

      <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Датасеты (из документов) — клик раскрывает поля/строки/периоды</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
        {sources.datasets.length === 0 && <span style={{ fontSize: 12, color: '#9aa4b2' }}>Нет датасетов — сначала распознайте документ.</span>}
        {sources.datasets.map((d) => (
          <div key={d.code} style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '6px 10px', background: '#fff' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }} onClick={() => setExp(exp === d.code ? null : d.code)}>
              <span style={{ color: '#2f5496' }}>{exp === d.code ? '▾' : '▸'}</span>
              <span style={{ fontSize: 13, fontWeight: 600 }}>{d.name}</span>
              <span style={{ fontSize: 11, color: '#9aa4b2' }}>({d.code})</span>
              <span style={{ fontSize: 12, color: '#6b7280', marginLeft: 'auto' }}>📄 {[d.document, d.folder, d.object].filter(Boolean).join(' · ') || '—'}</span>
            </div>
            {exp === d.code && (
              <div style={{ marginTop: 8, fontSize: 12, color: '#374151' }}>
                <div style={{ marginBottom: 4 }}><b>Поля/столбцы:</b> {d.fields.length === 0 ? '—' : d.fields.map((f) => (
                  <span key={f.code} style={chip('#eef', '#2f5496')}>{f.name} <span style={{ color: '#9aa4b2' }}>· {f.data_type === 'number' ? 'число' : f.data_type === 'date' ? 'дата' : 'текст'}{f.is_row_label ? ' · строка' : ''}</span></span>
                ))}</div>
                <div style={{ marginBottom: 4 }}><b>Строки:</b> {d.rows.length === 0 ? '—' : d.rows.map((r, i) => <span key={i} style={chip('#f1f2f4', '#374151')}>{r}</span>)}</div>
                <div><b>Периоды:</b> {d.dates.length === 0 ? '—' : d.dates.join(', ')}</div>
              </div>
            )}
          </div>
        ))}
      </div>

      <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Показатели (метрики) — готовые формулы для KPI/план-факта</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {sources.metrics.length === 0 && <span style={{ fontSize: 12, color: '#9aa4b2' }}>Нет метрик — создайте в разделе «Метрики».</span>}
        {sources.metrics.map((m) => <span key={m.code} style={chip('#eef', '#2f5496')}>{m.name} <span style={{ color: '#9aa4b2' }}>({m.code})</span></span>)}
      </div>
    </div>
  )
}

// ── Подсказки «что собрать»: система предлагает виджеты под выбранный датасет ──
export function SuggestPanel({ datasets, onAdd }: { datasets: DataSources['datasets']; onAdd: (specs: WidgetSpec[]) => Promise<void> }) {
  const [dc, setDc] = useState(datasets[0]?.code || '')
  const [specs, setSpecs] = useState<WidgetSpec[]>([])
  const [chosen, setChosen] = useState<Set<number>>(new Set())
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)

  function load(code: string) {
    setErr(null); setSpecs([]); setChosen(new Set())
    if (!code) return
    widgetSuggestions(code).then((s) => { setSpecs(s); setChosen(new Set(s.map((_, i) => i))) }).catch((e) => setErr((e as Error).message))
  }
  useEffect(() => { if (open && dc) load(dc) }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (i: number) => setChosen((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n })
  async function add() {
    const picked = specs.filter((_, i) => chosen.has(i))
    if (!picked.length) return
    setBusy(true)
    try { await onAdd(picked) } finally { setBusy(false) }
  }

  if (!open) {
    return (
      <button style={{ ...btnAuto, height: 34, marginBottom: 12 }} onClick={() => setOpen(true)}>
        ✨ Предложить виджеты под датасет
      </button>
    )
  }
  return (
    <div style={{ border: '1px solid #d1d5db', borderRadius: 10, padding: 12, marginBottom: 12, background: '#f8fafc' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <F t="Датасет"><select style={sel} value={dc} onChange={(e) => { setDc(e.target.value); load(e.target.value) }}>
          {datasets.map((d) => <option key={d.code} value={d.code}>{d.name} ({d.code})</option>)}
        </select></F>
        <button style={{ ...btn, height: 34 }} disabled={busy || chosen.size === 0} onClick={add}>{busy ? 'Добавление…' : `＋ Добавить выбранные (${chosen.size})`}</button>
        <button style={{ ...btnGhost, height: 34 }} onClick={() => setOpen(false)}>Скрыть</button>
        <span style={{ fontSize: 12, color: '#6b7280' }}>отметьте нужные предложения</span>
      </div>
      {err && <div style={{ color: '#a32d2d', fontSize: 12, marginBottom: 6 }}>{err}</div>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {specs.length === 0 && !err && <span style={{ fontSize: 12, color: '#9aa4b2' }}>Нет предложений.</span>}
        {specs.map((s, i) => (
          <label key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, border: '1px solid #e5e7eb', borderRadius: 8, padding: '5px 10px', background: chosen.has(i) ? '#eef' : '#fff', cursor: 'pointer' }}>
            <input type="checkbox" checked={chosen.has(i)} onChange={() => toggle(i)} />
            {s.name}
            <span style={{ ...wtBadge, marginLeft: 4 }}>{WT.find((x) => x.v === s.widget_type)?.t || s.widget_type}</span>
          </label>
        ))}
      </div>
    </div>
  )
}

export function WidgetForm({ sources, onCreate, initial, submitLabel }: {
  sources: DataSources
  onCreate: (b: { name: string; widget_type: string; config: Record<string, unknown>; width?: number; height?: number }) => void
  initial?: Widget
  submitLabel?: string
}) {
  const cfg0 = (initial?.config || {}) as Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any
  const numFields = (dc: string) => (sources.datasets.find((d) => d.code === dc)?.fields.filter((f) => f.data_type === 'number') || [])
  const initDataset = cfg0.dataset_code || sources.datasets[0]?.code || ''
  const [name, setName] = useState(initial?.name || '')
  const [type, setType] = useState(initial?.widget_type || 'kpi')
  const [source, setSource] = useState<'metric' | 'dataset' | 'formula'>(cfg0.formula ? 'formula' : (cfg0.metric_code || cfg0.plan_metric) ? 'metric' : (cfg0.dataset_code ? 'dataset' : 'metric'))
  const [formulaDsl, setFormulaDsl] = useState<string>(cfg0.formula || '')
  const [formulaUnit, setFormulaUnit] = useState<string>(cfg0.unit || '')
  const [metricCode, setMetricCode] = useState(cfg0.metric_code || cfg0.plan_metric || sources.metrics[0]?.code || '')
  const [factMetric, setFactMetric] = useState(cfg0.fact_metric || sources.metrics[1]?.code || sources.metrics[0]?.code || '')
  const [dataset, setDataset] = useState(initDataset)
  const [valueField, setValueField] = useState(cfg0.value_field || numFields(initDataset)[0]?.code || '')
  const [planField, setPlanField] = useState(cfg0.plan_field || numFields(initDataset)[0]?.code || '')
  const [factField, setFactField] = useState(cfg0.fact_field || numFields(initDataset)[0]?.code || '')
  const [multiFields, setMultiFields] = useState<string[]>(cfg0.value_fields || [])
  const [viz, setViz] = useState(cfg0.viz || 'bar')
  const [heading, setHeading] = useState(cfg0.heading || '')
  const [bodyText, setBodyText] = useState(cfg0.body || '')
  const [align, setAlign] = useState(cfg0.align || 'left')
  const [imgUrl, setImgUrl] = useState(cfg0.url || '')
  const [caption, setCaption] = useState(cfg0.caption || '')

  const isText = type === 'text'
  const isImage = type === 'image'
  const usesSource = type === 'kpi' || type === 'plan_fact'
  const usesDataset = (usesSource && source === 'dataset') || type === 'table' || ['bar', 'line', 'pie', 'dynamics', 'compare'].includes(type)
  const usesValueField = ['bar', 'line', 'pie', 'dynamics'].includes(type) || (type === 'kpi' && source === 'dataset')
  const usesMulti = type === 'compare'
  const toggleField = (c: string) => setMultiFields((s) => s.includes(c) ? s.filter((x) => x !== c) : [...s, c])

  // Свой фильтр виджета (переопределение глобального фильтра страницы).
  const [ownFilter, setOwnFilter] = useState<boolean>(cfg0.filter_scope === 'own')
  const [ownFrom, setOwnFrom] = useState<string>(cfg0.own_from || '')
  const [ownTo, setOwnTo] = useState<string>(cfg0.own_to || '')
  const [ownRow, setOwnRow] = useState<string>(cfg0.own_row || '')

  // Базовый config по выбору источника; null — если данных ещё недостаточно.
  function baseConfig(): Record<string, unknown> | null {
    if (type === 'text') return { heading: heading.trim() || undefined, body: bodyText.trim() || undefined, align }
    if (type === 'image') return imgUrl.trim() ? { url: imgUrl.trim(), caption: caption.trim() || undefined, fit: 'contain' } : null
    if (type === 'kpi') return source === 'formula' ? (formulaDsl.trim() ? { formula: formulaDsl.trim(), unit: formulaUnit.trim() || undefined } : null)
      : source === 'metric' ? (metricCode ? { metric_code: metricCode } : null) : ((dataset && valueField) ? { dataset_code: dataset, value_field: valueField } : null)
    if (type === 'plan_fact') return source === 'metric' ? ((metricCode && factMetric) ? { plan_metric: metricCode, fact_metric: factMetric } : null) : ((dataset && planField && factField) ? { dataset_code: dataset, plan_field: planField, fact_field: factField } : null)
    if (type === 'table') return dataset ? { dataset_code: dataset } : null
    if (type === 'compare') return (dataset && multiFields.length) ? { dataset_code: dataset, value_fields: multiFields, viz } : null
    return (dataset && valueField) ? { dataset_code: dataset, value_field: valueField } : null // bar/line/pie/dynamics
  }

  // Итоговый config = базовый + (опционально) свой фильтр (кроме text/image).
  function currentConfig(): Record<string, unknown> | null {
    const b = baseConfig()
    if (!b) return null
    if (ownFilter && !isText && !isImage) {
      return { ...b, filter_scope: 'own', own_from: ownFrom || undefined, own_to: ownTo || undefined, own_row: ownRow || undefined }
    }
    return b
  }

  // Живой предпросмотр (как в конструкторе формул): рендер по конфигу без сохранения.
  const [preview, setPreview] = useState<any>(null) // eslint-disable-line @typescript-eslint/no-explicit-any
  const [previewErr, setPreviewErr] = useState<string | null>(null)
  const cfgKey = JSON.stringify([type, currentConfig(), name])
  useEffect(() => {
    const config = currentConfig()
    if (!config) { setPreview(null); setPreviewErr(null); return }
    let cancelled = false
    const t = setTimeout(() => {
      previewWidget({ widget_type: type, name: name.trim() || undefined, config })
        .then((d) => { if (!cancelled) { setPreview(d); setPreviewErr(null) } })
        .catch((e) => { if (!cancelled) { setPreview(null); setPreviewErr((e as Error).message) } })
    }, 350)
    return () => { cancelled = true; clearTimeout(t) }
  }, [cfgKey]) // eslint-disable-line react-hooks/exhaustive-deps

  function submit(e: FormEvent) {
    e.preventDefault()
    const config = currentConfig()
    if (!config) return
    // при редактировании сохраняем условное форматирование (алерты), если тип по-прежнему его поддерживает
    if (initial && cfg0.alerts && ['kpi', 'plan_fact', 'dynamics'].includes(type)) {
      config.alerts = cfg0.alerts
      if (cfg0.alert_on) config.alert_on = cfg0.alert_on
    }
    const body: { name: string; widget_type: string; config: Record<string, unknown>; width?: number; height?: number } = {
      name: name.trim() || WT.find((x) => x.v === type)?.t || type, widget_type: type, config,
    }
    if (!initial) { const sz = DEFAULT_SIZE[type] || { w: 4, h: 4 }; body.width = sz.w; body.height = sz.h } // размер только для новых
    onCreate(body)
    if (!initial) setName('')
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end', border: initial ? 'none' : '1px solid #e5e7eb', borderRadius: 10, padding: initial ? 0 : 12 }}>
      <F t="Название"><input style={sel} placeholder="Заголовок виджета" value={name} onChange={(e) => setName(e.target.value)} /></F>
      <F t="Тип"><select style={sel} value={type} onChange={(e) => { const v = e.target.value; setType(v); if (v !== 'kpi' && source === 'formula') setSource('metric') }}>{WT.map((x) => <option key={x.v} value={x.v}>{x.t}</option>)}</select></F>
      {isText && (
        <>
          <F t="Заголовок (крупно)"><input style={{ ...sel, width: 200 }} placeholder="напр. Итоги квартала" value={heading} onChange={(e) => setHeading(e.target.value)} /></F>
          <F t="Текст"><input style={{ ...sel, width: 260 }} placeholder="пояснение к разделу" value={bodyText} onChange={(e) => setBodyText(e.target.value)} /></F>
          <F t="Выравнивание"><select style={sel} value={align} onChange={(e) => setAlign(e.target.value)}><option value="left">Слева</option><option value="center">По центру</option></select></F>
        </>
      )}
      {isImage && (
        <>
          <F t="URL картинки"><input style={{ ...sel, width: 300 }} placeholder="https://… или data:image/…" value={imgUrl} onChange={(e) => setImgUrl(e.target.value)} /></F>
          <F t="Подпись (необяз.)"><input style={{ ...sel, width: 180 }} placeholder="напр. Логотип МФЦ" value={caption} onChange={(e) => setCaption(e.target.value)} /></F>
        </>
      )}
      {usesSource && (
        <F t="Источник"><select style={sel} value={source} onChange={(e) => setSource(e.target.value as 'metric' | 'dataset' | 'formula')}>
          <option value="metric">Метрика</option><option value="dataset">Датасет</option>
          {type === 'kpi' && <option value="formula">Формула</option>}
        </select></F>
      )}
      {type === 'kpi' && source === 'formula' && (
        <>
          <F t="Единица (необяз.)"><input style={{ ...sel, width: 110 }} placeholder="напр. шт, %" value={formulaUnit} onChange={(e) => setFormulaUnit(e.target.value)} /></F>
          <div style={{ flexBasis: '100%' }}>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Формула показателя — соберите мышью ниже или введите текстом; считается на лету, без создания метрики</div>
            <input style={{ ...sel, width: '100%', fontFamily: 'ui-monospace, monospace', marginBottom: 8 }}
              placeholder="напр. SUM(field('plan','kol')) + 10" value={formulaDsl} onChange={(e) => setFormulaDsl(e.target.value)} />
            <FormulaBuilder sources={sources} onFormula={setFormulaDsl} />
          </div>
        </>
      )}
      {usesSource && source === 'metric' && (
        <F t={type === 'plan_fact' ? 'Метрика (план)' : 'Метрика'}><select style={sel} value={metricCode} onChange={(e) => setMetricCode(e.target.value)}>{sources.metrics.map((m) => <option key={m.code} value={m.code}>{m.name}{m.unit ? ` · ${m.unit}` : ''}</option>)}</select></F>
      )}
      {type === 'plan_fact' && source === 'metric' && (
        <F t="Метрика (факт)"><select style={sel} value={factMetric} onChange={(e) => setFactMetric(e.target.value)}>{sources.metrics.map((m) => <option key={m.code} value={m.code}>{m.name}{m.unit ? ` · ${m.unit}` : ''}</option>)}</select></F>
      )}
      {usesSource && source === 'metric' && (() => {
        const line = (lbl: string, x?: MetricSource) => (x && (x.formula || x.unit)) ? (
          <div style={{ fontSize: 11, color: '#6b7280' }}>{lbl}<b style={{ color: '#374151' }}>{x.name}</b>{x.unit ? ` · ед.: ${x.unit}` : ''}{x.formula ? <> · формула: <code style={{ fontFamily: 'ui-monospace, monospace', background: '#f1f2f4', padding: '0 4px', borderRadius: 4 }}>{x.formula}</code></> : ''}</div>
        ) : null
        const m = sources.metrics.find((x) => x.code === metricCode)
        const fm = type === 'plan_fact' ? sources.metrics.find((x) => x.code === factMetric) : undefined
        return (m || fm) ? <div style={{ flexBasis: '100%', margin: '-2px 0 2px' }}>{line(type === 'plan_fact' ? 'План: ' : '', m)}{line('Факт: ', fm)}</div> : null
      })()}
      {usesDataset && (
        <F t="Датасет"><select style={sel} value={dataset} onChange={(e) => { setDataset(e.target.value); const nf = numFields(e.target.value); setValueField(nf[0]?.code || ''); setPlanField(nf[0]?.code || ''); setFactField(nf[0]?.code || ''); setMultiFields([]) }}>{sources.datasets.map((d) => <option key={d.code} value={d.code}>{d.name} ({d.code})</option>)}</select></F>
      )}
      {usesValueField && (
        <F t="Поле (значение)"><select style={sel} value={valueField} onChange={(e) => setValueField(e.target.value)}>{numFields(dataset).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></F>
      )}
      {usesMulti && (
        <>
          <F t="Поля (несколько)">
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', height: 34, alignItems: 'center' }}>
              {numFields(dataset).map((f) => (
                <label key={f.code} style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: 13 }}>
                  <input type="checkbox" checked={multiFields.includes(f.code)} onChange={() => toggleField(f.code)} />{f.name}
                </label>
              ))}
            </div>
          </F>
          <F t="Вид"><select style={sel} value={viz} onChange={(e) => setViz(e.target.value)}><option value="bar">Столбцы</option><option value="line">Линии</option></select></F>
        </>
      )}
      {type === 'plan_fact' && source === 'dataset' && (
        <>
          <F t="Поле (план)"><select style={sel} value={planField} onChange={(e) => setPlanField(e.target.value)}>{numFields(dataset).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></F>
          <F t="Поле (факт)"><select style={sel} value={factField} onChange={(e) => setFactField(e.target.value)}>{numFields(dataset).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></F>
        </>
      )}
      {!isText && !isImage && (
        <div style={{ flexBasis: '100%', marginTop: 4, padding: '8px 10px', border: '1px solid #eef0f3', borderRadius: 8, background: '#fafbfc' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#374151' }}>
            <input type="checkbox" checked={ownFilter} onChange={(e) => setOwnFilter(e.target.checked)} />
            Свой фильтр (не зависит от фильтра страницы)
          </label>
          {ownFilter && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
              <F t="С даты"><input type="date" style={sel} value={ownFrom} onChange={(e) => setOwnFrom(e.target.value)} /></F>
              <F t="По дату"><input type="date" style={sel} value={ownTo} onChange={(e) => setOwnTo(e.target.value)} /></F>
              <F t="Строка"><input style={sel} value={ownRow} onChange={(e) => setOwnRow(e.target.value)} placeholder="напр. Паспорт" /></F>
            </div>
          )}
        </div>
      )}
      <div style={{ flexBasis: '100%', marginTop: 6 }}>
        <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Предпросмотр</div>
        <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: 12, minHeight: 56, background: '#fff' }}>
          {previewErr ? <div style={{ color: '#a32d2d', fontSize: 12 }}>{previewErr}</div>
            : preview ? <WidgetPreviewBody data={preview} />
              : <div style={{ color: '#9aa4b2', fontSize: 12 }}>Заполните поля — здесь появится живой предпросмотр виджета</div>}
        </div>
      </div>
      <button style={{ ...btn, flexBasis: '100%' }}>{submitLabel || 'Добавить'}</button>
    </form>
  )
}

