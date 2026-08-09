import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  approveVersion, createMetric, createVersion, getDataSources, getMetric, listMetrics, previewFormula,
  updateMetric, validateVersion, versionValue,
  type DataSources, type Dependencies, type Metric, type MetricVersion,
} from '../api'
import FormulaBuilder from './FormulaBuilder'
import TemplatePicker from './metrics/TemplatePicker'
import DataSuggestPanel from './metrics/DataSuggestPanel'
import { fmtNumber as fmtNum } from '../lib/format'

const FORMULA_HELP = [
  "SUM(field('план','кол'))",
  "PERCENT_OF(SUM(field('всего','кол')), SUM(field('часть','кол')))",
  "PLAN_FACT_PCT(SUM(field('план','кол')), SUM(field('факт','кол')))",
  "cell('нагрузка', date='2026-07-10', row='Паспорт РФ', col='Принято')",
  "metric('итого_план') / metric('план_год') * 100",
]

const METRICS_PAGE = 50

export default function MetricsPage({ canManage }: { canManage: boolean }) {
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [metricsTotal, setMetricsTotal] = useState(0)
  const [mq, setMq] = useState('')
  const [sel, setSel] = useState<{ metric: Metric; versions: MetricVersion[] } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  const fail = (e: unknown) => setError((e as Error).message)
  // Защита от гонки ответов: применяем только результат последнего запроса.
  const reqSeq = useRef(0)
  const loadMetrics = (query: string) => {
    const seq = ++reqSeq.current
    return listMetrics(query, METRICS_PAGE, 0)
      .then((p) => { if (seq === reqSeq.current) { setMetrics(p.items); setMetricsTotal(p.total) } }).catch(fail)
  }
  const refresh = () => loadMetrics(mq)
  async function loadMoreMetrics() {
    const seq = ++reqSeq.current
    try { const p = await listMetrics(mq, METRICS_PAGE, metrics.length); if (seq === reqSeq.current) { setMetrics((prev) => [...prev, ...p.items]); setMetricsTotal(p.total) } } catch (e) { fail(e) }
  }

  // Список — по поиску с дебаунсом (он же начальная загрузка).
  useEffect(() => { const t = setTimeout(() => loadMetrics(mq), 250); return () => clearTimeout(t) }, [mq]) // eslint-disable-line react-hooks/exhaustive-deps

  async function openMetric(id: string) {
    setError(null)
    try { setSel(await getMetric(id)) } catch (e) { fail(e) }
  }

  async function addMetric(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const m = await createMetric(code.trim(), name.trim())
      setCode(''); setName('')
      await refresh()
      openMetric(m.id)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, marginBottom: 16 }}>
        <button style={crumb} onClick={() => setSel(null)}>Метрики</button>
        {sel && <><span style={{ color: 'var(--text-faint)' }}>/</span><span>{sel.metric.name}</span></>}
      </div>

      {error && <div style={errBox}>{error}</div>}

      {!sel && (
        <div>
          {canManage && <DataSuggestPanel onCreated={refresh} />}
          {canManage && (
            <form onSubmit={addMetric} style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
              <input style={{ ...input, width: 160 }} placeholder="код (латиницей)" value={code} onChange={(e) => setCode(e.target.value)} />
              <input style={{ ...input, width: 240 }} placeholder="Название метрики" value={name} onChange={(e) => setName(e.target.value)} />
              <button style={btn} disabled={busy || !code.trim() || !name.trim()}>＋ Метрика</button>
            </form>
          )}
          <input style={{ ...input, width: '100%', maxWidth: 420, marginBottom: 12 }} placeholder="🔍 Поиск по коду или названию…" value={mq} onChange={(e) => setMq(e.target.value)} />
          {metrics.length === 0 ? (
            <div style={muted}>{mq.trim() ? 'Ничего не найдено.' : 'Пока нет метрик. Создайте первую и задайте ей формулу.'}</div>
          ) : (
            <div style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
              {metrics.map((m, i) => (
                <div key={m.id} onClick={() => openMetric(m.id)} style={{ ...rowItem, borderTop: i ? '1px solid var(--border-faint)' : 'none' }}>
                  <div>
                    <div style={{ fontSize: 14 }}>{m.name}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>{m.code}</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    {m.unit && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{m.unit}</span>}
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>версий: {m.versions ?? 0}</span>
                    <StatusBadge status={m.best_status || (m.has_approved ? 'approved' : 'draft')} />
                  </div>
                </div>
              ))}
            </div>
          )}
          {metrics.length < metricsTotal && (
            <div style={{ textAlign: 'center', marginTop: 12 }}>
              <button style={{ ...btn, background: 'var(--accent-weak-bg)', color: 'var(--accent)' }} onClick={loadMoreMetrics}>
                Показать ещё ({metricsTotal - metrics.length})
              </button>
            </div>
          )}
        </div>
      )}

      {sel && (
        <MetricDetail
          data={sel} canManage={canManage}
          onError={fail}
          onChanged={async () => { await refresh(); openMetric(sel.metric.id) }}
        />
      )}
    </div>
  )
}

function MetricDetail({ data, canManage, onError, onChanged }: {
  data: { metric: Metric; versions: MetricVersion[] }
  canManage: boolean
  onError: (e: unknown) => void
  onChanged: () => void
}) {
  const { metric, versions } = data
  const [formula, setFormula] = useState('')
  const [unit, setUnit] = useState('')
  const [mode, setMode] = useState<'ready' | 'visual' | 'text'>('ready')
  const [sources, setSources] = useState<DataSources | null>(null)
  const [preview, setPreview] = useState<{ value: number; deps: Dependencies } | null>(null)
  const [previewErr, setPreviewErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [values, setValues] = useState<Record<string, string>>({})
  const [info, setInfo] = useState(metric.info_text || '')
  const [infoBusy, setInfoBusy] = useState(false)
  const [infoSaved, setInfoSaved] = useState(false)

  useEffect(() => { getDataSources().then(setSources).catch(() => setSources({ datasets: [], metrics: [] })) }, [])

  async function saveInfo() {
    setInfoBusy(true); setInfoSaved(false)
    try { await updateMetric(metric.id, { info_text: info }); setInfoSaved(true) }
    catch (e) { onError(e) } finally { setInfoBusy(false) }
  }

  async function doPreview() {
    setPreview(null); setPreviewErr(null); setBusy(true)
    try {
      const r = await previewFormula(formula)
      setPreview({ value: r.value, deps: r.dependencies })
    } catch (e) { setPreviewErr((e as Error).message) } finally { setBusy(false) }
  }

  async function saveVersion() {
    setBusy(true)
    try {
      await createVersion(metric.id, { formula: formula.trim(), unit: unit.trim() || null })
      setFormula(''); setUnit(''); setPreview(null); setPreviewErr(null)
      onChanged()
    } catch (e) { onError(e) } finally { setBusy(false) }
  }

  async function act(fn: () => Promise<void>) {
    setBusy(true)
    try { await fn(); onChanged() } catch (e) { onError(e) } finally { setBusy(false) }
  }

  async function computeValue(v: MetricVersion) {
    try {
      const r = await versionValue(v.id)
      setValues((s) => ({ ...s, [v.id]: `${fmtNum(r.value)}${r.unit ? ' ' + r.unit : ''}` }))
    } catch (e) { setValues((s) => ({ ...s, [v.id]: 'ошибка: ' + (e as Error).message })) }
  }

  return (
    <div>
      <h2 style={{ fontSize: 17, margin: '0 0 2px' }}>{metric.name}</h2>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>{metric.code}{metric.description ? ' · ' + metric.description : ''}</div>

      {/* Расширенная информация (FR-5.9): показывается пользователю при «провале» в показатель (drill) */}
      {canManage && (
        <div style={{ marginBottom: 18 }}>
          <h3 style={h3}>Расширенная информация о показателе</h3>
          <div style={{ ...muted, marginBottom: 6 }}>Необязательно. Виден пользователю в «🔍 подробнее». Если пусто — покажется «Информации нет, в разработке».</div>
          <textarea style={{ width: '100%', minHeight: 70, padding: 8, border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13, fontFamily: 'inherit', resize: 'vertical' }}
            value={info} onChange={(e) => { setInfo(e.target.value); setInfoSaved(false) }}
            placeholder="Из чего складывается показатель, как читать, за что отвечает…" />
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
            <button style={btnSm} disabled={infoBusy} onClick={saveInfo}>{infoBusy ? 'Сохранение…' : 'Сохранить информацию'}</button>
            {infoSaved && <span style={{ fontSize: 12, color: 'var(--success)' }}>✓ сохранено</span>}
          </div>
        </div>
      )}

      <h3 style={h3}>Версии формулы</h3>
      {versions.length === 0 ? (
        <div style={muted}>Пока нет ни одной версии формулы.</div>
      ) : (
        <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
          {versions.map((v, i) => (
            <div key={v.id} style={{ padding: '10px 14px', borderTop: i ? '1px solid var(--border-faint)' : 'none' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>v{v.version_no}</span>
                <StatusBadge status={v.status} />
                {v.unit && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{v.unit}</span>}
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                  <button style={btnGhostSm} onClick={() => computeValue(v)}>Значение</button>
                  {canManage && v.status === 'draft' && <button style={btnSm} disabled={busy} onClick={() => act(() => validateVersion(v.id))}>Проверить</button>}
                  {canManage && v.status === 'validated' && <button style={btnSm} disabled={busy} onClick={() => act(() => approveVersion(v.id))}>Одобрить</button>}
                </div>
              </div>
              <div style={mono}>{v.formula_expression}</div>
              {values[v.id] && <div style={{ fontSize: 13, color: 'var(--success)', marginTop: 4 }}>= {values[v.id]}</div>}
            </div>
          ))}
        </div>
      )}

      {canManage && (
        <div style={{ marginTop: 20 }}>
          <h3 style={h3}>Новая версия формулы</h3>
          <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
            <button style={{ ...modeBtn, ...(mode === 'ready' ? modeBtnActive : {}) }} onClick={() => setMode('ready')}>📚 Готовые</button>
            <button style={{ ...modeBtn, ...(mode === 'visual' ? modeBtnActive : {}) }} onClick={() => setMode('visual')}>🖱 Конструктор</button>
            <button style={{ ...modeBtn, ...(mode === 'text' ? modeBtnActive : {}) }} onClick={() => setMode('text')}>⌨ Текст</button>
          </div>

          {mode === 'ready' ? (
            <div>
              <TemplatePicker sources={sources} onApply={(f, u) => { setFormula(f); if (u) setUnit(u); setMode('text') }} />
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)' }}>
                Получится формула: <code style={mono2}>{formula || '—'}</code>
              </div>
            </div>
          ) : mode === 'visual' ? (
            <div>
              {sources
                ? <FormulaBuilder sources={sources} onFormula={setFormula} />
                : <div style={muted}>Загрузка данных для выбора…</div>}
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)' }}>
                Получится формула: <code style={mono2}>{formula || '—'}</code>
              </div>
            </div>
          ) : (
            <div>
              <textarea
                style={{ ...input, width: '100%', height: 70, fontFamily: 'ui-monospace, monospace', padding: 10, resize: 'vertical' }}
                placeholder="Например: SUM(field('план','кол'))"
                value={formula} onChange={(e) => setFormula(e.target.value)}
              />
              <div style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 4 }}>
                Пишите как в Excel: данные — <code>field('датасет','поле')</code>, действия — <code>+ − * /</code>,
                свёртка — <code>SUM(…)</code>. Проверяйте кнопкой «Предпросмотр». Справочник ниже 👇
              </div>
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
            <input style={{ ...input, width: 120 }} placeholder="ед. (шт, ₽, %)" value={unit} onChange={(e) => setUnit(e.target.value)} />
            <button style={btnGhost} disabled={busy || !formula.trim()} onClick={doPreview}>Предпросмотр</button>
            <button style={btn} disabled={busy || !formula.trim()} onClick={saveVersion}>Сохранить версию</button>
          </div>

          {preview && (
            <div style={{ ...okBox, marginTop: 10 }}>
              <strong>Предпросмотр: {fmtNum(preview.value)}{unit ? ' ' + unit : ''}</strong>
              <div style={{ fontSize: 12, color: 'var(--success)', marginTop: 2 }}>
                зависит от: {[...preview.deps.datasets.map((d) => `датасет «${d}»`), ...preview.deps.metrics.map((m) => `метрика «${m}»`)].join(', ') || '—'}
              </div>
            </div>
          )}
          {previewErr && <div style={{ ...errBox, marginTop: 10 }}>{previewErr}</div>}

          <details style={{ marginTop: 12 }}>
            <summary style={{ fontSize: 13, color: 'var(--accent)', cursor: 'pointer' }}>📘 Справочник по формулам</summary>
            <div style={helpBox}>
              <div style={helpH}>Данные — откуда берутся числа</div>
              <ul style={helpUl}>
                <li><code>{"field('датасет','поле')"}</code> — весь столбец из выпуска датасета</li>
                <li><code>{"cell('датасет', date='2026-07-10', row='Паспорт РФ', col='принято')"}</code> — одна ячейка за дату (строка по названию)</li>
                <li><code>{"metric('код')"}</code> — значение другой метрики</li>
              </ul>
              <div style={helpH}>Действия</div>
              <div style={{ marginBottom: 4 }}><code>+ − * / ^ ( )</code> — как в Excel (сначала <code>^</code>, потом <code>* /</code>, потом <code>+ −</code>)</div>
              <div style={helpH}>Функции</div>
              <ul style={helpUl}>
                <li><code>SUM / AVG / COUNT / MIN / MAX(field(…))</code> — свернуть столбец в одно число</li>
                <li><code>PLAN_FACT_DELTA(план, факт)</code> — отклонение; <code>PLAN_FACT_PCT(план, факт)</code> — % выполнения плана</li>
                <li><code>PERCENT_OF(база, значение)</code> — процент: база = 100%, ищем % значения от базы (значение ÷ база × 100)</li>
                <li>фильтр строки: <code>{"SUM(field('план','кол'), filter={'услуга'='Паспорт'})"}</code></li>
              </ul>
              <div style={helpH}>Примеры — нажмите, чтобы подставить</div>
              <ul style={helpUl}>
                {FORMULA_HELP.map((f) => (
                  <li key={f}><code style={{ cursor: 'pointer', color: 'var(--accent)' }} onClick={() => setFormula(f)}>{f}</code></li>
                ))}
              </ul>
              <div style={{ marginTop: 6, color: 'var(--text-faint)' }}>
                Совет: всегда жмите «Предпросмотр» — он посчитает результат и покажет зависимости.
                Полная инструкция — <code>docs/Инструкция_по_формулам.md</code>.
              </div>
            </div>
          </details>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { t: string; bg: string; c: string }> = {
    draft: { t: 'черновик', bg: 'var(--surface-3)', c: 'var(--text-muted)' },
    validated: { t: 'проверена', bg: 'var(--warn-bg)', c: 'var(--warn)' },
    approved: { t: 'одобрена', bg: 'var(--success-bg)', c: 'var(--success)' },
    deprecated: { t: 'устарела', bg: 'var(--danger-bg)', c: 'var(--danger)' },
    archived: { t: 'в архиве', bg: 'var(--surface-3)', c: 'var(--text-faint)' },
  }
  const s = map[status] || map.draft
  return <span style={{ ...pill, background: s.bg, color: s.c }}>{s.t}</span>
}


const crumb: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 14, padding: 0 }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14 }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { height: 36, padding: '0 14px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', fontSize: 14, cursor: 'pointer' }
const btnSm: React.CSSProperties = { height: 28, padding: '0 10px', border: 'none', borderRadius: 6, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 12, cursor: 'pointer' }
const btnGhostSm: React.CSSProperties = { height: 28, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 6, background: 'var(--surface)', fontSize: 12, cursor: 'pointer' }
const rowItem: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', cursor: 'pointer' }
const pill: React.CSSProperties = { fontSize: 11, padding: '2px 8px', borderRadius: 10 }
const h3: React.CSSProperties = { fontSize: 14, margin: '0 0 8px' }
const mono: React.CSSProperties = { fontFamily: 'ui-monospace, monospace', fontSize: 13, color: 'var(--text)', background: 'var(--surface-2)', padding: '6px 8px', borderRadius: 6, overflowX: 'auto' }
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 14 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const okBox: React.CSSProperties = { background: 'var(--success-bg)', color: 'var(--success)', fontSize: 14, padding: '10px 12px', borderRadius: 8, border: '1px solid var(--success-bg)' }
const helpBox: React.CSSProperties = { fontSize: 12.5, color: 'var(--text-2)', marginTop: 8, padding: '10px 12px', background: 'var(--surface-2)', border: '1px solid var(--border-faint)', borderRadius: 8, lineHeight: 1.5 }
const helpH: React.CSSProperties = { fontWeight: 600, color: 'var(--accent)', marginTop: 8, marginBottom: 2 }
const helpUl: React.CSSProperties = { margin: '2px 0 0', paddingLeft: 18 }
const modeBtn: React.CSSProperties = { height: 32, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', cursor: 'pointer', fontSize: 13 }
const modeBtnActive: React.CSSProperties = { background: 'var(--accent-weak-bg)', border: '1px solid var(--accent)', color: 'var(--accent)' }
const mono2: React.CSSProperties = { fontFamily: 'ui-monospace, monospace', background: 'var(--surface-2)', padding: '2px 6px', borderRadius: 6, color: 'var(--text)' }
