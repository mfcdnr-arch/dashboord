import { useEffect, useState } from 'react'
import type { DataSet, DataSources } from '../api'

// Визуальный конструктор формул: пользователь собирает выражение из «элементов»
// (агрегат столбца / ячейка / метрика / число), соединяя их действиями (+ − × ÷),
// мышью — без ручного текста. На выходе — та же DSL-строка, что и в текстовом режиме.
// Отдельный режим «Процент (доля)»: база = 100%, второе число — сколько % от базы.

type Kind = 'agg' | 'cell' | 'metric' | 'number'
const AGG = [
  { v: 'SUM', t: 'Сумма' }, { v: 'AVG', t: 'Среднее' }, { v: 'COUNT', t: 'Кол-во' },
  { v: 'MIN', t: 'Минимум' }, { v: 'MAX', t: 'Максимум' },
]
const OPS = [
  { v: '+', t: '＋' }, { v: '-', t: '−' }, { v: '*', t: '×' }, { v: '/', t: '÷' },
]
const KINDS: { v: Kind; t: string }[] = [
  { v: 'agg', t: 'Столбец (агрегат)' }, { v: 'cell', t: 'Ячейка' },
  { v: 'metric', t: 'Метрика' }, { v: 'number', t: 'Число' },
]

interface Term {
  id: number
  op: string
  kind: Kind
  fn: string
  dataset: string
  field: string
  useFilter: boolean
  filterRow: string
  date: string
  row: string
  metricCode: string
  metricVersion: string
  num: string
}

let SEQ = 1
function newTerm(op: string, ds?: DataSet, metricCode?: string): Term {
  const numField = ds?.fields.find((f) => f.data_type === 'number')
  return {
    id: SEQ++, op, kind: 'agg', fn: 'SUM',
    dataset: ds?.code || '', field: numField?.code || '',
    useFilter: false, filterRow: ds?.rows[0] || '',
    date: ds?.dates[0] || '', row: ds?.rows[0] || '',
    metricCode: metricCode || '', metricVersion: 'approved', num: '0',
  }
}

function applyDataset(term: Term, code: string, byCode: Record<string, DataSet>): Term {
  const ds = byCode[code]
  const numField = ds?.fields.find((f) => f.data_type === 'number')
  return {
    ...term, dataset: code, field: numField?.code || ds?.fields[0]?.code || '',
    row: ds?.rows[0] || '', filterRow: ds?.rows[0] || '', date: ds?.dates[0] || '',
  }
}

function rowLabelKey(ds?: DataSet): string {
  return ds?.fields.find((f) => f.is_row_label)?.code || 'строка'
}

function termDsl(t: Term, byCode: Record<string, DataSet>): string {
  if (t.kind === 'number') return t.num.trim() || '0'
  if (t.kind === 'metric') {
    if (!t.metricCode) return '?'
    return t.metricVersion === 'approved' ? `metric('${t.metricCode}')` : `metric('${t.metricCode}', version=${t.metricVersion})`
  }
  if (t.kind === 'cell') {
    if (!t.dataset || !t.field) return '?'
    return `cell('${t.dataset}', date='${t.date}', row='${t.row}', col='${t.field}')`
  }
  if (!t.dataset || !t.field) return '?'
  const base = `field('${t.dataset}','${t.field}')`
  if (t.useFilter && t.filterRow) return `${t.fn}(${base}, filter={'${rowLabelKey(byCode[t.dataset])}'='${t.filterRow}'})`
  return `${t.fn}(${base})`
}

export default function FormulaBuilder({ sources, onFormula }: { sources: DataSources; onFormula: (dsl: string) => void }) {
  const byCode: Record<string, DataSet> = Object.fromEntries(sources.datasets.map((d) => [d.code, d]))
  const first = sources.datasets[0]
  const [mode, setMode] = useState<'expr' | 'percent'>('expr')
  const [terms, setTerms] = useState<Term[]>([newTerm('+', first)])
  const [pctBase, setPctBase] = useState<Term>(() => newTerm('+', first))
  const [pctValue, setPctValue] = useState<Term>(() => newTerm('+', first))

  useEffect(() => {
    if (mode === 'expr') onFormula(terms.map((t, i) => (i ? ` ${t.op} ` : '') + termDsl(t, byCode)).join(''))
    else onFormula(`PERCENT_OF(${termDsl(pctBase, byCode)}, ${termDsl(pctValue, byCode)})`)
  }, [mode, terms, pctBase, pctValue]) // eslint-disable-line react-hooks/exhaustive-deps

  function patch(id: number, p: Partial<Term>) {
    setTerms((ts) => ts.map((t) => (t.id === id ? { ...t, ...p } : t)))
  }
  const addTerm = () => setTerms((ts) => [...ts, newTerm('+', first, sources.metrics[0]?.code)])
  const removeTerm = (id: number) => setTerms((ts) => (ts.length > 1 ? ts.filter((t) => t.id !== id) : ts))

  if (sources.datasets.length === 0 && sources.metrics.length === 0) {
    return <div style={muted}>Нет данных для конструктора. Сначала выпустите датасет (раздел «Объекты» → распознавание) — тогда появятся поля для выбора.</div>
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        <button style={{ ...tabBtn, ...(mode === 'expr' ? tabBtnActive : {}) }} onClick={() => setMode('expr')}>Выражение</button>
        <button style={{ ...tabBtn, ...(mode === 'percent' ? tabBtnActive : {}) }} onClick={() => setMode('percent')}>Процент (доля)</button>
      </div>

      {mode === 'expr' ? (
        <>
          {terms.map((t, i) => (
            <div key={t.id}>
              {i > 0 && (
                <div style={{ display: 'flex', justifyContent: 'center', margin: '4px 0' }}>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {OPS.map((o) => (
                      <button key={o.v} onClick={() => patch(t.id, { op: o.v })}
                        style={{ ...opBtn, ...(t.op === o.v ? opBtnActive : {}) }}>{o.t}</button>
                    ))}
                  </div>
                </div>
              )}
              <TermCard term={t} sources={sources} byCode={byCode}
                onPatch={(p) => patch(t.id, p)}
                onSetDataset={(c) => patch(t.id, applyDataset(t, c, byCode))}
                onRemove={() => removeTerm(t.id)} />
            </div>
          ))}
          <button style={addBtn} onClick={addTerm}>＋ Добавить элемент</button>
        </>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={pctLbl}>База — это 100%</div>
          <TermCard term={pctBase} sources={sources} byCode={byCode}
            onPatch={(p) => setPctBase({ ...pctBase, ...p })}
            onSetDataset={(c) => setPctBase(applyDataset(pctBase, c, byCode))} />
          <div style={{ textAlign: 'center', fontSize: 18, color: '#9aa4b2' }}>%</div>
          <div style={pctLbl}>Значение — сколько % от базы</div>
          <TermCard term={pctValue} sources={sources} byCode={byCode}
            onPatch={(p) => setPctValue({ ...pctValue, ...p })}
            onSetDataset={(c) => setPctValue(applyDataset(pctValue, c, byCode))} />
          <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>
            Результат = значение ÷ база × 100. Пример: план 200 (=100%), факт 50 → 25%.
          </div>
        </div>
      )}
    </div>
  )
}

function TermCard({ term: t, sources, byCode, onPatch, onSetDataset, onRemove }: {
  term: Term; sources: DataSources; byCode: Record<string, DataSet>
  onPatch: (p: Partial<Term>) => void; onSetDataset: (code: string) => void; onRemove?: () => void
}) {
  const ds = byCode[t.dataset]
  const numFields = ds?.fields.filter((f) => f.data_type === 'number') || []
  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <select style={sel} value={t.kind} onChange={(e) => onPatch({ kind: e.target.value as Kind })}>
          {KINDS.map((k) => <option key={k.v} value={k.v}>{k.t}</option>)}
        </select>
        {onRemove && <button style={rmBtn} onClick={onRemove} title="Убрать элемент">✕</button>}
      </div>

      {t.kind === 'agg' && (
        <div style={rowWrap}>
          <Lbl t="Действие"><select style={sel} value={t.fn} onChange={(e) => onPatch({ fn: e.target.value })}>{AGG.map((a) => <option key={a.v} value={a.v}>{a.t}</option>)}</select></Lbl>
          <Lbl t="Датасет (документ)"><DatasetSel sources={sources} value={t.dataset} onChange={onSetDataset} /></Lbl>
          <Lbl t="Поле (число)"><select style={sel} value={t.field} onChange={(e) => onPatch({ field: e.target.value })}>{numFields.map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></Lbl>
          <Lbl t="Только строка">
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, height: 32 }}>
              <input type="checkbox" checked={t.useFilter} onChange={(e) => onPatch({ useFilter: e.target.checked })} />
              <select style={{ ...sel, opacity: t.useFilter ? 1 : 0.5 }} disabled={!t.useFilter} value={t.filterRow} onChange={(e) => onPatch({ filterRow: e.target.value })}>{(ds?.rows || []).map((r) => <option key={r} value={r}>{r}</option>)}</select>
            </label>
          </Lbl>
        </div>
      )}

      {t.kind === 'cell' && (
        <div style={rowWrap}>
          <Lbl t="Датасет (документ)"><DatasetSel sources={sources} value={t.dataset} onChange={onSetDataset} /></Lbl>
          <Lbl t="Дата"><select style={sel} value={t.date} onChange={(e) => onPatch({ date: e.target.value })}>{(ds?.dates || []).map((d) => <option key={d} value={d}>{d}</option>)}</select></Lbl>
          <Lbl t="Строка"><select style={sel} value={t.row} onChange={(e) => onPatch({ row: e.target.value })}>{(ds?.rows || []).map((r) => <option key={r} value={r}>{r}</option>)}</select></Lbl>
          <Lbl t="Столбец"><select style={sel} value={t.field} onChange={(e) => onPatch({ field: e.target.value })}>{numFields.map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></Lbl>
        </div>
      )}

      {t.kind === 'metric' && (
        <div style={rowWrap}>
          <Lbl t="Метрика"><select style={sel} value={t.metricCode} onChange={(e) => onPatch({ metricCode: e.target.value })}><option value="">— выберите —</option>{sources.metrics.map((m) => <option key={m.code} value={m.code}>{m.name}</option>)}</select></Lbl>
          <Lbl t="Версия"><select style={sel} value={t.metricVersion} onChange={(e) => onPatch({ metricVersion: e.target.value })}><option value="approved">одобренная</option><option value="latest">последняя</option></select></Lbl>
        </div>
      )}

      {t.kind === 'number' && (
        <div style={rowWrap}>
          <Lbl t="Значение"><input style={{ ...sel, width: 120 }} type="number" value={t.num} onChange={(e) => onPatch({ num: e.target.value })} /></Lbl>
        </div>
      )}
    </div>
  )
}

function DatasetSel({ sources, value, onChange }: { sources: DataSources; value: string; onChange: (c: string) => void }) {
  return (
    <select style={sel} value={value} onChange={(e) => onChange(e.target.value)}>
      {sources.datasets.map((d) => <option key={d.code} value={d.code}>{d.name} ({d.code}{d.object ? ' · ' + d.object : ''})</option>)}
    </select>
  )
}

function Lbl({ t, children }: { t: string; children: React.ReactNode }) {
  return <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 11, color: '#6b7280' }}>{t}{children}</label>
}

const card: React.CSSProperties = { border: '1px solid #e5e7eb', borderRadius: 10, padding: 12, background: '#fff' }
const rowWrap: React.CSSProperties = { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }
const sel: React.CSSProperties = { height: 32, padding: '0 8px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 13, background: '#fff' }
const opBtn: React.CSSProperties = { width: 34, height: 30, border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', cursor: 'pointer', fontSize: 15 }
const opBtnActive: React.CSSProperties = { background: '#2f5496', color: '#fff', border: '1px solid #2f5496' }
const tabBtn: React.CSSProperties = { height: 30, padding: '0 12px', border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', cursor: 'pointer', fontSize: 13 }
const tabBtnActive: React.CSSProperties = { background: '#eef', border: '1px solid #2f5496', color: '#2f5496' }
const addBtn: React.CSSProperties = { marginTop: 10, height: 34, padding: '0 14px', border: '1px dashed #9aa4b2', borderRadius: 8, background: '#fff', color: '#2f5496', cursor: 'pointer', fontSize: 13 }
const rmBtn: React.CSSProperties = { marginLeft: 'auto', width: 26, height: 26, border: '1px solid #e5e7eb', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#a32d2d' }
const pctLbl: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#2f5496' }
const muted: React.CSSProperties = { color: '#6b7280', fontSize: 13, padding: '8px 0' }
