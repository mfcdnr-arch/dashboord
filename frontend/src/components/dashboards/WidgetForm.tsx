import { useEffect, useState, type FormEvent } from 'react'
import {
  createMetric, createVersion, metricSuggestions, previewWidget, widgetSuggestions,
  type DataSources, type MetricSource, type MetricSuggestion, type Widget, type WidgetSpec,
} from '../../api'
import { WidgetPreviewBody } from '../WidgetView'
import FormulaBuilder from '../FormulaBuilder'
import { dataUriBytes, fileToEmbeddableDataUri } from '../../lib/image'
import { DEFAULT_SIZE, F, WT, btn, btnAuto, btnGhost, sel, tab, tabActive, wtBadge } from './shared'
import { WidgetPicker, WIDGET_META } from './WidgetPicker'

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
    <div style={{ border: '1px solid var(--border-strong)', borderRadius: 10, padding: 12, marginBottom: 12, background: 'var(--surface-2)' }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
        <b style={{ fontSize: 13 }}>📚 Каталог источников</b>
        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>что можно применить в дашборде</span>
        <button style={{ ...btnGhost, height: 28, marginLeft: 'auto' }} onClick={() => setOpen(false)}>Скрыть</button>
      </div>

      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Датасеты (из документов) — клик раскрывает поля/строки/периоды</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
        {sources.datasets.length === 0 && <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>Нет датасетов — сначала распознайте документ.</span>}
        {sources.datasets.map((d) => (
          <div key={d.code} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '6px 10px', background: 'var(--surface)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }} onClick={() => setExp(exp === d.code ? null : d.code)}>
              <span style={{ color: 'var(--accent)' }}>{exp === d.code ? '▾' : '▸'}</span>
              <span style={{ fontSize: 13, fontWeight: 600 }}>{d.name}</span>
              <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>({d.code})</span>
              <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }}>📄 {[d.document, d.folder, d.object].filter(Boolean).join(' · ') || '—'}</span>
            </div>
            {exp === d.code && (
              <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-2)' }}>
                <div style={{ marginBottom: 4 }}><b>Поля/столбцы:</b> {d.fields.length === 0 ? '—' : d.fields.map((f) => (
                  <span key={f.code} style={chip('var(--accent-weak-bg)', 'var(--accent)')}>{f.name} <span style={{ color: 'var(--text-faint)' }}>· {f.data_type === 'number' ? 'число' : f.data_type === 'date' ? 'дата' : 'текст'}{f.is_row_label ? ' · строка' : ''}</span></span>
                ))}</div>
                <div style={{ marginBottom: 4 }}><b>Строки:</b> {d.rows.length === 0 ? '—' : d.rows.map((r, i) => <span key={i} style={chip('var(--surface-3)', 'var(--text-2)')}>{r}</span>)}</div>
                <div><b>Периоды:</b> {d.dates.length === 0 ? '—' : d.dates.join(', ')}</div>
              </div>
            )}
          </div>
        ))}
      </div>

      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Показатели (метрики) — готовые формулы для KPI/план-факта</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {sources.metrics.length === 0 && <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>Нет метрик — создайте в разделе «Метрики».</span>}
        {sources.metrics.map((m) => <span key={m.code} style={chip('var(--accent-weak-bg)', 'var(--accent)')}>{m.name} <span style={{ color: 'var(--text-faint)' }}>({m.code})</span></span>)}
      </div>
    </div>
  )
}

// ── Подсказки «что собрать»: система предлагает виджеты под выбранный датасет.
// Delta-aware (2026-08-04): то, что уже построено где-либо в организации для
// этого же датасета (= того же объекта), в предложениях не повторяется. ──
export function SuggestPanel({ datasets, onAdd }: { datasets: DataSources['datasets']; onAdd: (specs: WidgetSpec[]) => Promise<void> }) {
  const [dc, setDc] = useState(datasets[0]?.code || '')
  const [specs, setSpecs] = useState<WidgetSpec[]>([])
  const [alreadyBuilt, setAlreadyBuilt] = useState(0)
  const [chosen, setChosen] = useState<Set<number>>(new Set())
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)

  function load(code: string) {
    setErr(null); setSpecs([]); setAlreadyBuilt(0); setChosen(new Set())
    if (!code) return
    widgetSuggestions(code).then((r) => { setSpecs(r.specs); setAlreadyBuilt(r.already_built); setChosen(new Set(r.specs.map((_, i) => i))) }).catch((e) => setErr((e as Error).message))
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
        💡 Предложить ещё
      </button>
    )
  }
  return (
    <div style={{ border: '1px solid var(--border-strong)', borderRadius: 10, padding: 12, marginBottom: 12, background: 'var(--surface-2)' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <F t="Датасет"><select style={sel} value={dc} onChange={(e) => { setDc(e.target.value); load(e.target.value) }}>
          {datasets.map((d) => <option key={d.code} value={d.code}>{d.name} ({d.code})</option>)}
        </select></F>
        <button style={{ ...btn, height: 34 }} disabled={busy || chosen.size === 0} onClick={add}>{busy ? 'Добавление…' : `＋ Добавить выбранные (${chosen.size})`}</button>
        <button style={{ ...btnGhost, height: 34 }} onClick={() => setOpen(false)}>Скрыть</button>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>отметьте нужные предложения</span>
      </div>
      {err && <div style={{ color: 'var(--danger)', fontSize: 12, marginBottom: 6 }}>{err}</div>}
      {alreadyBuilt > 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>Показаны только недостающие — {alreadyBuilt} {alreadyBuilt === 1 ? 'вариант' : 'вариантов'} уже построен(о) для этого датасета.</div>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {specs.length === 0 && !err && <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>{alreadyBuilt > 0 ? 'Всё уже построено — новых предложений нет.' : 'Нет предложений.'}</span>}
        {specs.map((s, i) => (
          <label key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, border: '1px solid var(--border)', borderRadius: 8, padding: '5px 10px', background: chosen.has(i) ? 'var(--accent-weak-bg)' : 'var(--surface)', cursor: 'pointer' }}>
            <input type="checkbox" checked={chosen.has(i)} onChange={() => toggle(i)} />
            {s.name}
            <span style={{ ...wtBadge, marginLeft: 4 }}>{WT.find((x) => x.v === s.widget_type)?.t || s.widget_type}</span>
          </label>
        ))}
      </div>
    </div>
  )
}

const METRIC_TYPE_LABEL: Record<string, string> = {
  diff: 'Разница', share: 'Доля', period_compare: 'Период-к-периоду', yoy: 'Год к году',
  running_total: 'Накопительный итог', plan_fact: 'План/факт', deviation: 'Отклонение от цели',
}

// ── Рекомендательная система, часть B (2026-08-04): предложения ПРОИЗВОДНЫХ
// метрик (разница/доля/период-к-периоду/год-к-году/накопительный итог/план-
// факт-пара/отклонение от цели) на основе метрик, уже используемых на этом
// дашборде и в объекте, к которому он привязан папкой. Принятое предложение
// создаётся как метрика-ЧЕРНОВИК (обычный цикл проверки draft→validated→
// approved) — само по себе на дашборд НЕ добавляется. ──
export function SuggestMetricsPanel({ dashboardId }: { dashboardId: string }) {
  const [specs, setSpecs] = useState<MetricSuggestion[]>([])
  const [candidatesCount, setCandidatesCount] = useState(0)
  const [chosen, setChosen] = useState<Set<number>>(new Set())
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  const [done, setDone] = useState<number | null>(null)

  function load() {
    setErr(null); setDone(null); setSpecs([]); setChosen(new Set())
    metricSuggestions(dashboardId)
      .then((r) => { setSpecs(r.specs); setCandidatesCount(r.candidates_count); setChosen(new Set(r.specs.map((_, i) => i))) })
      .catch((e) => setErr((e as Error).message))
  }
  useEffect(() => { if (open) load() }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (i: number) => setChosen((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n })

  async function add() {
    const picked = specs.filter((_, i) => chosen.has(i))
    if (!picked.length) return
    setBusy(true); setErr(null)
    try {
      for (const s of picked) {
        const m = await createMetric(s.code, s.name)
        await createVersion(m.id, { formula: s.formula, unit: s.unit || undefined })
      }
      setDone(picked.length)
      load()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  if (!open) {
    return (
      <button style={{ ...btnAuto, height: 34, marginBottom: 12, marginLeft: 8 }} onClick={() => setOpen(true)}>
        💡 Предложить метрики
      </button>
    )
  }
  return (
    <div style={{ border: '1px solid var(--border-strong)', borderRadius: 10, padding: 12, marginBottom: 12, background: 'var(--surface-2)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Предложения производных метрик</span>
        <button style={{ ...btn, height: 34 }} disabled={busy || chosen.size === 0} onClick={add}>{busy ? 'Добавление…' : `＋ Добавить как черновики (${chosen.size})`}</button>
        <button style={{ ...btnGhost, height: 34 }} onClick={() => setOpen(false)}>Скрыть</button>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>область: метрики дашборда + объекта</span>
      </div>
      {err && <div style={{ color: 'var(--danger)', fontSize: 12, marginBottom: 6 }}>{err}</div>}
      {done != null && <div style={{ color: 'var(--success)', fontSize: 12, marginBottom: 6 }}>Добавлено {done} черновиков — проверьте и одобрите в разделе «Метрики».</div>}
      {candidatesCount > 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>Метрик в области предложений: {candidatesCount}.</div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {specs.length === 0 && !err && (
          <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>
            {candidatesCount === 0 ? 'На этом дашборде (и в его объекте) пока нет метрик — предлагать не от чего.' : 'Новых предложений нет — похоже, всё уже построено.'}
          </span>
        )}
        {specs.map((s, i) => (
          <label key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, border: '1px solid var(--border)', borderRadius: 8, padding: '6px 10px', background: chosen.has(i) ? 'var(--accent-weak-bg)' : 'var(--surface)', cursor: 'pointer' }}>
            <input type="checkbox" checked={chosen.has(i)} onChange={() => toggle(i)} />
            <span style={{ ...wtBadge, flexShrink: 0 }}>{METRIC_TYPE_LABEL[s.type] || s.type}</span>
            <span>{s.name}</span>
            <code style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>{s.formula}</code>
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
  // Уникальные числовые поля по ВСЕМ датасетам — для «Сравнения подразделений» (поле, не привязанное к датасету).
  const allNumFields = Array.from(new Map(sources.datasets.flatMap((d) => d.fields.filter((f) => f.data_type === 'number').map((f) => [f.code, f])) as [string, { code: string; name: string }][]).values())
  const initDataset = cfg0.dataset_code || sources.datasets[0]?.code || ''
  const [name, setName] = useState(initial?.name || '')
  const [help, setHelp] = useState<string>(cfg0.help || '')  // авторская подсказка-тултип
  const [type, setType] = useState(initial?.widget_type || 'kpi')
  const [source, setSource] = useState<'metric' | 'dataset' | 'formula'>(cfg0.formula ? 'formula' : (cfg0.metric_code || cfg0.plan_metric) ? 'metric' : (cfg0.dataset_code ? 'dataset' : 'metric'))
  const [formulaDsl, setFormulaDsl] = useState<string>(cfg0.formula || '')
  const [formulaUnit, setFormulaUnit] = useState<string>(cfg0.unit || '')
  // Режим ввода формулы: визуальный сборщик (по умолчанию) или ручной текст DSL.
  // При редактировании существующей текстовой формулы — сразу «текст», чтобы её было видно.
  const [formulaMode, setFormulaMode] = useState<'visual' | 'text'>(cfg0.formula ? 'text' : 'visual')
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
  const [imgErr, setImgErr] = useState<string | null>(null)
  const [imgBusy, setImgBusy] = useState(false)
  const [imgKb, setImgKb] = useState<number | null>(null)  // итоговый размер встроенной картинки
  const [imgAdvanced, setImgAdvanced] = useState(false)  // ручной ввод URL — «продвинутый» режим

  // Загрузка картинки файлом → data-URI (встраивается в дашборд, работает офлайн).
  // Крупные изображения сжимаются на клиенте (даунскейл + пере-кодирование),
  // чтобы не раздувать JSON виджета и версии дашборда в БД.
  async function onPickImage(file: File | null) {
    setImgErr(null); setImgKb(null)
    if (!file) return
    setImgBusy(true)
    try {
      const uri = await fileToEmbeddableDataUri(file)
      setImgUrl(uri)
      setImgKb(Math.round(dataUriBytes(uri) / 1024))
    } catch (e) {
      setImgErr((e as Error).message)
    } finally {
      setImgBusy(false)
    }
  }
  const [objField, setObjField] = useState(cfg0.value_field || allNumFields[0]?.code || '')

  // Сравнение источников: список пар (датасет, поле) из РАЗНЫХ файлов + способ
  // сопоставления категорий. Полностью выпадающими списками, без формул.
  type CrossItem = { dataset_code: string; value_field: string; label: string }
  const initCross: CrossItem[] = (cfg0.series as { dataset_code: string; value_field: string; label?: string }[] | undefined)
    ?.map((s) => ({ dataset_code: s.dataset_code, value_field: s.value_field, label: s.label || '' }))
    || [0, 1].map((i) => ({ dataset_code: sources.datasets[i]?.code || '', value_field: numFields(sources.datasets[i]?.code || '')[0]?.code || '', label: '' }))
  const [crossSeries, setCrossSeries] = useState<CrossItem[]>(initCross)
  const [matchBy, setMatchBy] = useState<'row_label' | 'period'>(cfg0.match_by === 'period' ? 'period' : 'row_label')
  function updateCross(i: number, patch: Partial<CrossItem>) {
    setCrossSeries((arr) => arr.map((it, idx) => idx === i ? { ...it, ...patch } : it))
  }
  function addCrossItem() {
    setCrossSeries((arr) => [...arr, { dataset_code: sources.datasets[0]?.code || '', value_field: numFields(sources.datasets[0]?.code || '')[0]?.code || '', label: '' }])
  }
  function removeCrossItem(i: number) {
    setCrossSeries((arr) => arr.length > 2 ? arr.filter((_, idx) => idx !== i) : arr)
  }

  const [pickerOpen, setPickerOpen] = useState(false)
  const isObjectsCompare = type === 'objects_compare'
  const isCrossCompare = type === 'cross_dataset_compare'
  const isText = type === 'text'
  const isImage = type === 'image'
  const usesSource = type === 'kpi' || type === 'gauge' || type === 'plan_fact'
  const usesDataset = (usesSource && source === 'dataset') || type === 'table' || ['bar', 'line', 'pie', 'dynamics', 'yoy', 'compare', 'heatmap', 'pivot', 'waterfall'].includes(type)
  const usesValueField = ['bar', 'line', 'pie', 'dynamics', 'yoy', 'waterfall'].includes(type) || (['kpi', 'gauge'].includes(type) && source === 'dataset')
  const usesMulti = type === 'compare' || type === 'heatmap' || type === 'pivot'
  const toggleField = (c: string) => setMultiFields((s) => s.includes(c) ? s.filter((x) => x !== c) : [...s, c])

  // Шкала спидометра (gauge): максимум; пусто — авто.
  const [gaugeMax, setGaugeMax] = useState<string>(cfg0.gauge_max != null ? String(cfg0.gauge_max) : '')
  // Цель/бенчмарк (kpi/gauge) и линейный тренд (dynamics).
  const [target, setTarget] = useState<string>(cfg0.target != null ? String(cfg0.target) : '')
  const [trend, setTrend] = useState<boolean>(!!cfg0.trend)
  // Волна F: обнаружение аномалий (без ИИ — отклонение от линии тренда в σ).
  const [anomalies, setAnomalies] = useState<boolean>(!!cfg0.anomalies)
  const [anomalyThreshold, setAnomalyThreshold] = useState<string>(cfg0.anomaly_threshold != null ? String(cfg0.anomaly_threshold) : '2')

  // Свой фильтр виджета (переопределение глобального фильтра страницы).
  const [ownFilter, setOwnFilter] = useState<boolean>(cfg0.filter_scope === 'own')
  const [ownFrom, setOwnFrom] = useState<string>(cfg0.own_from || '')
  const [ownTo, setOwnTo] = useState<string>(cfg0.own_to || '')
  const [ownRow, setOwnRow] = useState<string>(cfg0.own_row || '')

  // Базовый config по выбору источника; null — если данных ещё недостаточно.
  function baseConfig(): Record<string, unknown> | null {
    if (type === 'text') return { heading: heading.trim() || undefined, body: bodyText.trim() || undefined, align }
    if (type === 'image') return imgUrl.trim() ? { url: imgUrl.trim(), caption: caption.trim() || undefined, fit: 'contain' } : null
    if (type === 'kpi' || type === 'gauge') {
      const base = source === 'formula' ? (formulaDsl.trim() ? { formula: formulaDsl.trim(), unit: formulaUnit.trim() || undefined } : null)
        : source === 'metric' ? (metricCode ? { metric_code: metricCode } : null) : ((dataset && valueField) ? { dataset_code: dataset, value_field: valueField } : null)
      if (!base) return null
      if (type === 'gauge' && gaugeMax.trim() && !isNaN(Number(gaugeMax))) (base as Record<string, unknown>).gauge_max = Number(gaugeMax)
      if (target.trim() && !isNaN(Number(target))) (base as Record<string, unknown>).target = Number(target)
      return base
    }
    if (type === 'plan_fact') return source === 'metric' ? ((metricCode && factMetric) ? { plan_metric: metricCode, fact_metric: factMetric } : null) : ((dataset && planField && factField) ? { dataset_code: dataset, plan_field: planField, fact_field: factField } : null)
    if (type === 'table') return dataset ? { dataset_code: dataset } : null
    if (type === 'objects_compare') return objField ? { value_field: objField } : null
    if (type === 'cross_dataset_compare') {
      const valid = crossSeries.filter((s) => s.dataset_code && s.value_field)
      return valid.length >= 2
        ? { series: valid.map((s) => ({ dataset_code: s.dataset_code, value_field: s.value_field, ...(s.label.trim() ? { label: s.label.trim() } : {}) })), match_by: matchBy, viz }
        : null
    }
    if (type === 'compare') return (dataset && multiFields.length) ? { dataset_code: dataset, value_fields: multiFields, viz } : null
    if (type === 'heatmap' || type === 'pivot') return (dataset && multiFields.length) ? { dataset_code: dataset, value_fields: multiFields } : null
    if (type === 'dynamics') return (dataset && valueField) ? {
      dataset_code: dataset, value_field: valueField,
      ...(trend ? { trend: true } : {}),
      ...(anomalies ? { anomalies: true, anomaly_threshold: Number(anomalyThreshold) || 2 } : {}),
    } : null
    return (dataset && valueField) ? { dataset_code: dataset, value_field: valueField } : null // bar/line/pie/yoy
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
    if (initial && cfg0.alerts && ['kpi', 'gauge', 'plan_fact', 'dynamics'].includes(type)) {
      config.alerts = cfg0.alerts
      if (cfg0.alert_on) config.alert_on = cfg0.alert_on
    }
    if (help.trim()) config.help = help.trim()  // авторская подсказка → тултип на виджете
    const body: { name: string; widget_type: string; config: Record<string, unknown>; width?: number; height?: number } = {
      name: name.trim() || WT.find((x) => x.v === type)?.t || type, widget_type: type, config,
    }
    if (!initial) { const sz = DEFAULT_SIZE[type] || { w: 4, h: 4 }; body.width = sz.w; body.height = sz.h } // размер только для новых
    onCreate(body)
    if (!initial) setName('')
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end', minWidth: 0, maxWidth: '100%',
      border: initial ? 'none' : '1px solid var(--border)', borderRadius: 10, padding: initial ? 0 : 12 }}>
      <F t="Название"><input style={sel} placeholder="Заголовок виджета" value={name} onChange={(e) => setName(e.target.value)} /></F>
      <F t="Подсказка (тултип)"><input style={sel} placeholder="Что показывает виджет — покажется по значку «i»" value={help} onChange={(e) => setHelp(e.target.value)} /></F>
      <F t="Тип"><button type="button" style={{ ...sel, minWidth: 200, display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'space-between', cursor: 'pointer' }}
        onClick={() => setPickerOpen(true)} title="Открыть галерею типов виджетов">
        <span style={{ fontWeight: 600, color: 'var(--text)' }}>{WIDGET_META[type]?.t || type}</span>
        <span style={{ fontSize: 12, color: 'var(--accent)' }}>▦ галерея</span>
      </button></F>
      {pickerOpen && <WidgetPicker value={type} onClose={() => setPickerOpen(false)}
        onPick={(v) => { setType(v); if (!['kpi', 'gauge'].includes(v) && source === 'formula') setSource('metric') }} />}
      {isText && (
        <>
          <F t="Заголовок (крупно)"><input style={{ ...sel, width: 200 }} placeholder="напр. Итоги квартала" value={heading} onChange={(e) => setHeading(e.target.value)} /></F>
          <F t="Текст"><input style={{ ...sel, width: 260 }} placeholder="пояснение к разделу" value={bodyText} onChange={(e) => setBodyText(e.target.value)} /></F>
          <F t="Выравнивание"><select style={sel} value={align} onChange={(e) => setAlign(e.target.value)}><option value="left">Слева</option><option value="center">По центру</option></select></F>
        </>
      )}
      {isImage && (
        <>
          <div style={{ flexBasis: '100%', display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <F t="Картинка (файл, крупные сжимаются)">
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <label style={{ ...btnGhost, height: 34, display: 'inline-flex', alignItems: 'center', cursor: imgBusy ? 'wait' : 'pointer', opacity: imgBusy ? 0.6 : 1 }}>
                  {imgBusy ? '⏳ Обработка…' : '🖼 Выбрать файл…'}
                  <input type="file" accept="image/*" disabled={imgBusy} style={{ display: 'none' }} onChange={(e) => onPickImage(e.target.files?.[0] ?? null)} />
                </label>
                {imgUrl && (
                  <>
                    <img src={imgUrl} alt="" style={{ height: 34, maxWidth: 90, objectFit: 'contain', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)' }} />
                    {imgKb != null && <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>{imgKb} КБ</span>}
                    <button type="button" style={{ ...btnGhost, height: 34 }} onClick={() => { setImgUrl(''); setImgErr(null); setImgKb(null) }}>Убрать</button>
                  </>
                )}
              </div>
            </F>
            <F t="Подпись (необяз.)"><input style={{ ...sel, width: 180 }} placeholder="напр. Логотип МФЦ" value={caption} onChange={(e) => setCaption(e.target.value)} /></F>
          </div>
          {imgErr && <div style={{ flexBasis: '100%', color: 'var(--danger)', fontSize: 12 }}>{imgErr}</div>}
          <div style={{ flexBasis: '100%' }}>
            <button type="button" style={{ border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: 0 }} onClick={() => setImgAdvanced((v) => !v)}>
              {imgAdvanced ? '▾' : '▸'} Указать ссылкой (URL)
            </button>
            {imgAdvanced && (
              <input style={{ ...sel, width: '100%', marginTop: 6 }} placeholder="https://… или data:image/…" value={imgUrl} onChange={(e) => { setImgUrl(e.target.value); setImgErr(null) }} />
            )}
          </div>
        </>
      )}
      {usesSource && (
        <F t="Источник"><select style={sel} value={source} onChange={(e) => setSource(e.target.value as 'metric' | 'dataset' | 'formula')}>
          <option value="metric">Метрика</option><option value="dataset">Датасет</option>
          {['kpi', 'gauge'].includes(type) && <option value="formula">Формула</option>}
        </select></F>
      )}
      {['kpi', 'gauge'].includes(type) && source === 'formula' && (
        <>
          <F t="Единица (необяз.)"><input style={{ ...sel, width: 110 }} placeholder="напр. шт, %" value={formulaUnit} onChange={(e) => setFormulaUnit(e.target.value)} /></F>
          <div style={{ flexBasis: '100%' }}>
            <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
              <button type="button" style={{ ...tab, ...(formulaMode === 'visual' ? tabActive : {}) }} onClick={() => setFormulaMode('visual')}>🖱 Конструктор</button>
              <button type="button" style={{ ...tab, ...(formulaMode === 'text' ? tabActive : {}) }} onClick={() => setFormulaMode('text')}>⌨ Текст</button>
            </div>
            {formulaMode === 'visual' ? (
              <>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>Соберите показатель мышью — считается на лету, без создания метрики</div>
                <FormulaBuilder sources={sources} onFormula={setFormulaDsl} />
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
                  Получится формула: <code style={{ fontFamily: 'ui-monospace, monospace', background: 'var(--surface-3)', padding: '1px 6px', borderRadius: 4 }}>{formulaDsl || '—'}</code>
                </div>
              </>
            ) : (
              <>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Формула показателя (как в Excel): данные — <code>field('датасет','поле')</code>, действия — <code>+ − * /</code>, свёртка — <code>SUM(…)</code></div>
                <input style={{ ...sel, width: '100%', fontFamily: 'ui-monospace, monospace' }}
                  placeholder="напр. SUM(field('plan','kol')) + 10" value={formulaDsl} onChange={(e) => setFormulaDsl(e.target.value)} />
              </>
            )}
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
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{lbl}<b style={{ color: 'var(--text-2)' }}>{x.name}</b>{x.unit ? ` · ед.: ${x.unit}` : ''}{x.formula ? <> · формула: <code style={{ fontFamily: 'ui-monospace, monospace', background: 'var(--surface-3)', padding: '0 4px', borderRadius: 4 }}>{x.formula}</code></> : ''}</div>
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
      {isObjectsCompare && (
        <F t="Показатель (по подразделениям)"><select style={sel} value={objField} onChange={(e) => setObjField(e.target.value)}>
          {allNumFields.length === 0 && <option value="">— нет числовых полей —</option>}
          {allNumFields.map((f) => <option key={f.code} value={f.code}>{f.name} ({f.code})</option>)}
        </select></F>
      )}
      {isCrossCompare && (
        <div style={{ flexBasis: '100%' }}>
          <F t="Сопоставлять"><select style={sel} value={matchBy} onChange={(e) => setMatchBy(e.target.value as 'row_label' | 'period')}>
            <option value="row_label">По строке (одинаковые названия в разных файлах)</option>
            <option value="period">По периоду (по месяцу выпуска)</option>
          </select></F>
          <F t="Вид"><select style={sel} value={viz} onChange={(e) => setViz(e.target.value)}><option value="bar">Столбцы</option><option value="line">Линии</option></select></F>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', margin: '8px 0 4px' }}>Источники (минимум 2, из разных датасетов/файлов)</div>
          {crossSeries.map((it, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', marginBottom: 6, flexWrap: 'wrap' }}>
              <F t="Датасет"><select style={sel} value={it.dataset_code} onChange={(e) => { const nf = numFields(e.target.value); updateCross(i, { dataset_code: e.target.value, value_field: nf[0]?.code || '' }) }}>
                {sources.datasets.map((d) => <option key={d.code} value={d.code}>{d.name} ({d.code})</option>)}
              </select></F>
              <F t="Поле"><select style={sel} value={it.value_field} onChange={(e) => updateCross(i, { value_field: e.target.value })}>
                {numFields(it.dataset_code).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}
              </select></F>
              <F t="Подпись серии (необяз.)"><input style={{ ...sel, width: 160 }} placeholder={`${it.dataset_code}.${it.value_field}`} value={it.label} onChange={(e) => updateCross(i, { label: e.target.value })} /></F>
              <button type="button" style={{ ...btnGhost, height: 34 }} disabled={crossSeries.length <= 2} onClick={() => removeCrossItem(i)} title={crossSeries.length <= 2 ? 'Минимум 2 источника' : 'Убрать источник'}>✕</button>
            </div>
          ))}
          <button type="button" style={{ ...btnAuto, height: 34 }} onClick={addCrossItem}>＋ Добавить источник</button>
        </div>
      )}
      {type === 'gauge' && (
        <F t="Шкала, max (пусто — авто)"><input style={{ ...sel, width: 130 }} type="number" placeholder="напр. 100" value={gaugeMax} onChange={(e) => setGaugeMax(e.target.value)} /></F>
      )}
      {['kpi', 'gauge'].includes(type) && (
        <F t="Цель (пусто — нет)"><input style={{ ...sel, width: 130 }} type="number" placeholder="напр. 200" value={target} onChange={(e) => setTarget(e.target.value)} /></F>
      )}
      {type === 'dynamics' && (
        <>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, height: 34 }} title="Наложить линию линейного тренда (метод наименьших квадратов)">
            <input type="checkbox" checked={trend} onChange={(e) => setTrend(e.target.checked)} />Линия тренда
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, height: 34 }} title="Отметить точки, отклонившиеся от линии тренда больше чем на N стандартных отклонений (простая статистика, без ИИ)">
            <input type="checkbox" checked={anomalies} onChange={(e) => setAnomalies(e.target.checked)} />Отмечать аномалии
          </label>
          {anomalies && (
            <F t="Порог, σ">
              <input style={{ ...sel, width: 70 }} type="number" min="0.5" step="0.5" value={anomalyThreshold} onChange={(e) => setAnomalyThreshold(e.target.value)} />
            </F>
          )}
        </>
      )}
      {usesMulti && (
        <>
          <F t={type === 'heatmap' ? 'Поля (столбцы карты)' : 'Поля (несколько)'}>
            {/* Высота была жёстко задана в 34px: полтора десятка длинных имён
                показателей госформы туда не помещались и наезжали на соседние
                поля формы. Теперь список занимает столько, сколько нужно, но не
                больше — дальше прокрутка, чтобы форма не разрасталась на экран. */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 132, overflowY: 'auto',
              width: 'min(460px, 100%)', boxSizing: 'border-box',
              padding: '4px 6px', border: '1px solid var(--border-faint)', borderRadius: 8 }}>
              {numFields(dataset).map((f) => (
                <label key={f.code} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, fontSize: 13, lineHeight: 1.3 }}>
                  <input type="checkbox" checked={multiFields.includes(f.code)} onChange={() => toggleField(f.code)} style={{ marginTop: 2, flexShrink: 0 }} />
                  {/* Имена показателей длинные: без переноса они выходят за
                      границы списка и наезжают на соседние поля формы. */}
                  <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>{f.name}</span>
                </label>
              ))}
            </div>
          </F>
          {type === 'compare' && (
            <F t="Вид"><select style={sel} value={viz} onChange={(e) => setViz(e.target.value)}><option value="bar">Столбцы</option><option value="line">Линии</option></select></F>
          )}
        </>
      )}
      {type === 'plan_fact' && source === 'dataset' && (
        <>
          <F t="Поле (план)"><select style={sel} value={planField} onChange={(e) => setPlanField(e.target.value)}>{numFields(dataset).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></F>
          <F t="Поле (факт)"><select style={sel} value={factField} onChange={(e) => setFactField(e.target.value)}>{numFields(dataset).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></F>
        </>
      )}
      {!isText && !isImage && (
        <div style={{ flexBasis: '100%', marginTop: 4, padding: '8px 10px', border: '1px solid var(--border-faint)', borderRadius: 8, background: 'var(--surface-2)' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-2)' }}>
            <input type="checkbox" checked={ownFilter} onChange={(e) => setOwnFilter(e.target.checked)} />
            Свой фильтр (не зависит от фильтра страницы)
          </label>
          {ownFilter && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
              <F t="С даты"><input type="date" style={sel} value={ownFrom} onChange={(e) => setOwnFrom(e.target.value)} /></F>
              <F t="По дату"><input type="date" style={sel} value={ownTo} onChange={(e) => setOwnTo(e.target.value)} /></F>
              <F t="Строка">{(() => {
                // Для «Сравнения источников» строки берём из ВЫБРАННЫХ источников
                // (не из общего `dataset` — он для этого типа виджета не используется).
                const rows = isCrossCompare
                  ? Array.from(new Set(crossSeries.flatMap((s) => sources.datasets.find((d) => d.code === s.dataset_code)?.rows || [])))
                  : sources.datasets.find((d) => d.code === dataset)?.rows || []
                return rows.length
                  ? <select style={sel} value={ownRow} onChange={(e) => setOwnRow(e.target.value)}><option value="">— все строки —</option>{rows.map((r) => <option key={r} value={r}>{r}</option>)}</select>
                  : <input style={sel} value={ownRow} onChange={(e) => setOwnRow(e.target.value)} placeholder="напр. Паспорт" />
              })()}</F>
            </div>
          )}
        </div>
      )}
      {/* minWidth:0 обязателен: без него блок предпросмотра растягивается под
          широкую таблицу (15 показателей) и разрывает форму — содержимое уходит
          за края окна. С ним таблица прокручивается внутри своей рамки. */}
      <div style={{ flexBasis: '100%', width: '100%', minWidth: 0, maxWidth: '100%', marginTop: 6 }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Предпросмотр</div>
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, minHeight: 56,
          background: 'var(--surface)', minWidth: 0, maxWidth: '100%', overflowX: 'auto' }}>
          {previewErr ? <div style={{ color: 'var(--danger)', fontSize: 12 }}>{previewErr}</div>
            : preview ? <WidgetPreviewBody data={preview} />
              : <div style={{ color: 'var(--text-faint)', fontSize: 12 }}>Заполните поля — здесь появится живой предпросмотр виджета</div>}
        </div>
      </div>
      <button style={{ ...btn, flexBasis: '100%' }}>{submitLabel || 'Добавить'}</button>
    </form>
  )
}

