import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  createRelease, getExtractionForVersion, getJob, layoutPreview, startExtraction,
  type CellPick, type Doc, type ExtractionJob, type FieldMap, type LayoutPreview, type ReleaseResult,
} from '../api'
import DashboardDraft from './DashboardDraft'
import { elideMiddle } from '../lib/text'
import InfoTip from './InfoTip'
import SheetGrid, { colName, fillMerges, type PickedCell, type Rect } from './SheetGrid'

const TYPES = [
  { v: 'number', t: 'Число' },
  { v: 'date', t: 'Дата' },
  { v: 'text', t: 'Текст' },
]

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const baseName = (f: string) => f.replace(/\.[^.]+$/, '')

/**
 * Конструктор разметки документа.
 *
 * Пользователь видит лист «как в оригинале» (объединения, номера строк, буквы
 * столбцов) и мышью показывает, что брать: область данных, сколько этажей шапки,
 * какие столбцы и строки нужны, где названия строк. Всё, что он выбрал,
 * пересчитывается на сервере ТЕМ ЖЕ кодом, который делает выпуск, — поэтому
 * «что получится» внизу не может разойтись с тем, что уедет в датасет.
 *
 * Два режима: «таблица» (обычный отчёт) и «отдельные ячейки» — для форм вроде
 * «приложение к письму», где нужны несколько конкретных цифр, а размечать
 * таблицу целиком незачем.
 */
export default function ExtractionPage({ doc, canManage, onBack }: { doc: Doc; canManage: boolean; onBack: () => void }) {
  const [job, setJob] = useState<ExtractionJob | null>(null)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [tableId, setTableId] = useState<string | null>(null)
  const [rect, setRect] = useState<Rect>([0, 0, 0, 0])
  const [headerRows, setHeaderRows] = useState(1)
  const [orientation, setOrientation] = useState<'columns' | 'rows'>('columns')
  const [excludedCols, setExcludedCols] = useState<Set<number>>(new Set())
  const [excludedRows, setExcludedRows] = useState<Set<number>>(new Set())
  const [labelField, setLabelField] = useState<number | null>(null)
  const [names, setNames] = useState<Record<number, string>>({})
  const [types, setTypes] = useState<Record<number, string>>({})

  const [mode, setMode] = useState<'table' | 'cells'>('table')
  const [picked, setPicked] = useState<PickedCell[]>([])

  const [preview, setPreview] = useState<LayoutPreview | null>(null)
  const [previewing, setPreviewing] = useState(false)

  const [code, setCode] = useState('dataset')
  const [name, setName] = useState(baseName(doc.original_filename))
  const [period, setPeriod] = useState(doc.reporting_period_start || '')

  const [submitting, setSubmitting] = useState(false)
  const [conflict, setConflict] = useState<{ id: string; name: string; created_at: string } | null>(null)
  const [result, setResult] = useState<ReleaseResult | null>(null)

  const fail = (e: unknown) => setError((e as Error).message)
  const table = job?.tables.find((t) => t.id === tableId) || null
  const transposed = orientation === 'rows'

  // Координаты: сетка разметки против листа. При «показателях в строках»
  // область транспонируется, поэтому строка листа становится ПОЛЕМ, а столбец —
  // записью. Держим исключения в координатах ЛИСТА (их видит пользователь) и
  // переводим только на границе с сервером.
  const skipRows = useMemo(
    () => (transposed
      ? [...excludedCols].map((c) => c - rect[1])
      : [...excludedRows].map((r) => r - rect[0])).filter((i) => i >= 0),
    [transposed, excludedCols, excludedRows, rect],
  )
  // Служебные строки листа (ФИО согласующих, примечания) — сервер помечает
  // строки без единого числа, мы переводим их индексы в координаты листа.
  const suspectSheetRows = useMemo(() => {
    const base = transposed ? rect[1] : rect[0]
    return (preview?.suspect_rows || [])
      .map((i) => base + i)
      .filter((r) => !(transposed ? excludedCols : excludedRows).has(r))
  }, [preview, transposed, rect, excludedCols, excludedRows])

  const excludedFields = useMemo(
    () => new Set(
      (transposed ? [...excludedRows].map((r) => r - rect[0]) : [...excludedCols]).filter((i) => i >= 0),
    ),
    [transposed, excludedRows, excludedCols, rect],
  )

  // Счётчик строк снимается автоматически только при первом расчёте разметки
  // для таблицы: иначе пользователь не смог бы вернуть столбец обратно.
  const trimmed = useRef(false)

  const selectTable = useCallback((j: ExtractionJob, tid: string) => {
    const t = j.tables.find((x) => x.id === tid)
    if (!t) return
    trimmed.current = false
    setTableId(tid)
    const width = t.preview.reduce((w, r) => Math.max(w, r.length), 0)
    const r = (t.data_rect && t.data_rect.length === 4
      ? t.data_rect
      : [0, 0, Math.max(0, t.preview.length - 1), Math.max(0, width - 1)]) as Rect
    setRect(r)
    setHeaderRows(t.header_rows ?? 1)
    setExcludedCols(new Set())
    setExcludedRows(new Set())
    setNames({})
    setTypes({})
    setLabelField(null)
    setPicked([])
  }, [])

  useEffect(() => {
    if (!doc.version_id) { setLoading(false); return }
    getExtractionForVersion(doc.version_id)
      .then((j) => { setJob(j); if (j.tables?.length && j.job_id) selectTable(j, j.tables[0].id) })
      .catch(fail)
      .finally(() => setLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Пересчёт разметки: сервер отвечает теми же заголовками и типами, которые
  // потом попадут в датасет. Небольшая задержка — чтобы протягивание области
  // мышью не порождало запрос на каждый пиксель.
  useEffect(() => {
    if (!job?.job_id || !tableId || mode !== 'table') return
    const id = setTimeout(() => {
      setPreviewing(true)
      layoutPreview(job.job_id!, {
        table_id: tableId, data_rect: rect, header_rows: headerRows,
        orientation, skip_rows: skipRows,
      })
        .then((p) => {
          setPreview(p)
          setLabelField((cur) => (cur === null ? p.row_label_column : cur))
          // Один раз на таблицу снимаем счётчик строк бланка («№ п/п»):
          // на дашборде это не показатель, а номер по порядку. Дальше
          // выбор за пользователем — повторно не вмешиваемся.
          if (!trimmed.current) {
            trimmed.current = true
            const counters = p.columns.filter((c) => c.is_counter).map((c) => c.column_index)
            if (counters.length) setExcludedCols((s) => new Set([...s, ...counters]))
          }
        })
        .catch(fail)
        .finally(() => setPreviewing(false))
    }, 250)
    return () => clearTimeout(id)
  }, [job?.job_id, tableId, rect, headerRows, orientation, skipRows, mode])

  async function runExtraction() {
    if (!doc.version_id) return
    setStarting(true); setError(null); setResult(null)
    try {
      const { job_id } = await startExtraction(doc.version_id)
      let j = await getJob(job_id)
      while (j.status === 'queued' || j.status === 'running') { await sleep(1000); j = await getJob(job_id) }
      setJob(j)
      if (j.tables.length && j.job_id) selectTable(j, j.tables[0].id)
    } catch (e) { fail(e) } finally { setStarting(false) }
  }

  // Имена показателей для шапки листа: в транспонированном режиме поле
  // соответствует СТРОКЕ листа, поэтому подписывать столбцы нечем.
  const fieldNames = useMemo(() => {
    const m = new Map<number, string>()
    if (transposed) return m
    for (const c of preview?.columns || []) {
      if (!excludedFields.has(c.column_index)) m.set(c.column_index, names[c.column_index] ?? c.field_name)
    }
    return m
  }, [preview, names, excludedFields, transposed])

  /** Клик по имени в шапке листа — перевести курсор в поле переименования. */
  function focusName(col: number) {
    const el = document.getElementById(`field-name-${col}`) as HTMLInputElement | null
    if (!el) return
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    el.focus()
    el.select()
  }

  function toggle(set: Set<number>, v: number): Set<number> {
    const next = new Set(set)
    if (next.has(v)) next.delete(v); else next.add(v)
    return next
  }

  /**
   * Имя показателя для отдельной ячейки — из названия строки и заголовка
   * столбца («Донецкая Народная Республика · за отчётную неделю»). Само
   * значение ячейки именем быть не может: «7078» ничего не говорит о том,
   * что это за цифра, а исправлять руками каждую — та же ручная работа,
   * от которой уходим.
   */
  function cellTitle(row: number, col: number, value: string, n: number): string {
    if (!table) return value.trim() || `Показатель ${n}`
    const filled = fillMerges(table.preview, table.merges || [])
    const label = (filled[row]?.[rect[1]] || '').trim()
    const head = Array.from({ length: headerRows }, (_, i) => (filled[rect[0] + i]?.[col] || '').trim())
      .filter((h, i, a) => h && a.indexOf(h) === i)
      .slice(-2)
      .join(' · ')
    const name = [...new Set([label, head].filter(Boolean))].join(' · ').trim()
    return name || value.trim() || `Показатель ${n}`
  }

  function pickCell(row: number, col: number, value: string) {
    setPicked((prev) => {
      const at = prev.findIndex((p) => p.row === row && p.col === col)
      if (at >= 0) return prev.filter((_, i) => i !== at)
      return [...prev, {
        row, col,
        field_name: cellTitle(row, col, value, prev.length + 1).slice(0, 120),
        field_code: `cell_${colName(col).toLowerCase()}${row + 1}`,
      }]
    })
  }

  async function submit(supersede: boolean) {
    if (!job?.job_id || !tableId) return
    if (!code.trim() || !name.trim()) { setError('Заполните код и название датасета'); return }

    let fields: FieldMap[] = []
    let cells: CellPick[] | undefined
    if (mode === 'cells') {
      if (!picked.length) { setError('Выберите хотя бы одну ячейку'); return }
      cells = picked.map((p) => ({
        row: p.row, col: p.col, field_code: p.field_code, field_name: p.field_name, data_type: 'number',
      }))
    } else {
      const cols = (preview?.columns || []).filter((c) => !excludedFields.has(c.column_index))
      if (!cols.length) { setError('Не выбрано ни одного столбца'); return }
      if (labelField === null) { setError('Отметьте, где лежат названия строк (◉)'); return }
      fields = cols.map((c) => ({
        column_index: c.column_index,
        field_code: c.field_code,
        field_name: (names[c.column_index] ?? c.field_name).trim() || c.field_name,
        data_type: types[c.column_index] ?? c.data_type,
        is_row_label: c.column_index === labelField,
      }))
      if (!fields.some((f) => f.is_row_label)) {
        setError('Столбец с названиями строк исключён — верните его или выберите другой')
        return
      }
    }

    setSubmitting(true); setError(null)
    try {
      const r = await createRelease(job.job_id, {
        table_id: tableId, code: code.trim(), name: name.trim(),
        reporting_period_start: period || null, fields, supersede,
        layout: { data_rect: rect, header_rows: headerRows, orientation, skip_rows: skipRows },
        cells,
      })
      if ('conflict' in r) setConflict(r.existing)
      else { setResult(r); setConflict(null) }
    } catch (e) { fail(e) } finally { setSubmitting(false) }
  }

  const ready = job?.status === 'succeeded' || job?.status === 'needs_review'

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <button style={crumb} onClick={onBack}>← Назад к документам</button>
        <StatusBadge status={starting ? 'running' : job?.status || 'none'} />
      </div>
      <h2 style={{ fontSize: 17, margin: '0 0 4px' }}>Разметка: {doc.original_filename}</h2>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
        {doc.source_type.toUpperCase()} · отчётная дата {doc.reporting_period_start}
      </div>

      {error && <div style={errBox}>{error}</div>}
      {job?.warnings?.map((w, i) => <div key={i} style={warnBox}>⚠ {w}</div>)}

      {result ? (
        <ResultPanel result={result} onBack={onBack} />
      ) : loading ? (
        <div style={muted}>Загрузка…</div>
      ) : !doc.version_id ? (
        <div style={muted}>У документа нет загруженной версии файла.</div>
      ) : starting ? (
        <div style={muted}>Идёт распознавание… обновляем статус.</div>
      ) : !ready ? (
        <div>
          <div style={{ ...muted, marginBottom: 12 }}>
            {job?.status === 'failed'
              ? `Распознавание не удалось: ${job.error_message || 'ошибка'}`
              : 'Документ ещё не распознан.'}
          </div>
          {canManage && (
            <button style={btn} onClick={runExtraction}>
              {job?.status === 'failed' ? 'Повторить распознавание' : 'Запустить распознавание'}
            </button>
          )}
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            {job!.tables.length > 1 && job!.tables.map((t) => (
              <button key={t.id} onClick={() => selectTable(job!, t.id)}
                style={{ ...chip, ...(t.id === tableId ? chipActive : {}) }}>
                {t.sheet_or_page || `Таблица ${t.table_index + 1}`} · {t.row_count}×{t.column_count}
              </button>
            ))}
            {/* Повторное распознавание нужно не только после ошибки: разбор
                документа улучшается, а у ранее загруженных файлов остаётся
                сохранённый прежний результат — иначе исправления до них
                просто не доходят. */}
            {canManage && (
              <button type="button" style={{ ...chip, marginLeft: 'auto' }} title="Разобрать файл заново — текущая разметка сбросится"
                onClick={() => { if (confirm('Разобрать документ заново? Текущая разметка сбросится.')) runExtraction() }}>
                ↻ Распознать заново
              </button>
            )}
          </div>

          {table && (
            <>
              <Toolbar
                mode={mode} onMode={setMode}
                orientation={orientation} onOrientation={setOrientation}
                headerRows={headerRows} onHeaderRows={setHeaderRows}
                rect={rect}
                onResetRect={() => {
                  const width = table.preview.reduce((w, r) => Math.max(w, r.length), 0)
                  setRect([0, 0, Math.max(0, table.preview.length - 1), Math.max(0, width - 1)])
                }}
              />

              <SheetGrid
                rows={table.preview}
                merges={table.merges || []}
                rect={rect}
                headerRows={headerRows}
                labelCol={transposed ? null : labelField}
                excludedCols={excludedCols}
                excludedRows={excludedRows}
                mode={mode}
                picked={picked}
                suspectRows={new Set(suspectSheetRows)}
                fieldNames={fieldNames}
                onRect={setRect}
                onToggleCol={(c) => setExcludedCols((s) => toggle(s, c))}
                onToggleRow={(r) => setExcludedRows((s) => toggle(s, r))}
                onLabelCol={(c) => setLabelField(c)}
                onPickCell={pickCell}
                onRenameCol={focusName}
              />

              {suspectSheetRows.length > 0 && mode === 'table' && (
                <div style={hintBox}>
                  <span>
                    ⚠ {suspectSheetRows.length}{' '}
                    {suspectSheetRows.length === 1 ? 'строка без данных' : 'строк(и) без данных'} —
                    обычно это пустые заготовки бланка, подписи и примечания.
                  </span>
                  <button type="button" style={{ ...chip, border: '1px solid var(--warn)', color: 'var(--warn)' }}
                    onClick={() => (transposed
                      ? setExcludedCols((s) => new Set([...s, ...suspectSheetRows]))
                      : setExcludedRows((s) => new Set([...s, ...suspectSheetRows])))}>
                    Исключить их
                  </button>
                </div>
              )}

              <div style={{ fontSize: 12, color: 'var(--text-faint)', margin: '6px 0 18px' }}>
                {mode === 'cells'
                  ? 'Кликайте по ячейкам с нужными цифрами — каждая станет отдельным показателем.'
                  : 'Протяните мышью по ячейкам, чтобы задать область данных. Клик по букве столбца или номеру строки — исключить их. ◉ — где лежат названия строк.'}
                {table.row_count > table.preview.length &&
                  ` Показаны первые ${table.preview.length} строк из ${table.row_count}.`}
              </div>
            </>
          )}

          {table && canManage && mode === 'cells' && (
            <>
              <CellsPanel picked={picked} onRename={(i, v) => setPicked((p) => p.map((x, k) => (k === i ? { ...x, field_name: v } : x)))}
                onRemove={(i) => setPicked((p) => p.filter((_, k) => k !== i))} />
              {picked.length > 0 && (
                <DashboardDraft
                  columns={picked.map((p, i) => ({
                    column_index: i, source_header: p.field_name, field_code: p.field_code,
                    field_name: p.field_name, data_type: 'number', is_row_label: false, confidence: null,
                  }))}
                  rows={[picked.map((p) => fillMerges(table.preview, table.merges || [])[p.row]?.[p.col] ?? '')]}
                  labelColumn={null}
                  names={{}}
                  totalRows={1}
                />
              )}
            </>
          )}

          {table && canManage && mode === 'table' && (
            <FieldsPanel
              preview={preview}
              previewing={previewing}
              transposed={transposed}
              excluded={excludedFields}
              names={names}
              types={types}
              labelField={labelField}
              onName={(i, v) => setNames((s) => ({ ...s, [i]: v }))}
              onType={(i, v) => setTypes((s) => ({ ...s, [i]: v }))}
              onLabel={setLabelField}
              onToggle={(i) => (transposed
                ? setExcludedRows((s) => toggle(s, i + rect[0]))
                : setExcludedCols((s) => toggle(s, i)))}
            />
          )}

          {table && canManage && (
            <div style={{ marginTop: 20 }}>
              <h3 style={h3}>Выпуск датасета</h3>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                <Field label="Код"><input style={input} value={code} onChange={(e) => setCode(e.target.value)} /></Field>
                <Field label="Название"><input style={{ ...input, width: 240 }} value={name} onChange={(e) => setName(e.target.value)} /></Field>
                <Field label="Период"><input style={{ ...input, width: 160 }} type="date" value={period} onChange={(e) => setPeriod(e.target.value)} /></Field>
                <button style={{ ...btn, alignSelf: 'flex-end' }} disabled={submitting} onClick={() => submit(false)}>
                  {submitting ? 'Сохранение…' : 'Подтвердить выпуск'}
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {conflict && (
        <ConflictDialog conflict={conflict} busy={submitting}
          onSupersede={() => submit(true)} onCancel={() => setConflict(null)} />
      )}
    </div>
  )
}

function Toolbar({ mode, onMode, orientation, onOrientation, headerRows, onHeaderRows, rect, onResetRect }: {
  mode: 'table' | 'cells'; onMode: (m: 'table' | 'cells') => void
  orientation: 'columns' | 'rows'; onOrientation: (o: 'columns' | 'rows') => void
  headerRows: number; onHeaderRows: (n: number) => void
  rect: Rect; onResetRect: () => void
}) {
  return (
    <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 10 }}>
      <Field label="Что размечаем" hint="«Таблицу» — когда в файле обычный список строк с показателями. «Отдельные ячейки» — когда из документа нужны всего несколько конкретных цифр.">
        <div style={{ display: 'flex', gap: 6 }}>
          <button type="button" style={{ ...chip, ...(mode === 'table' ? chipActive : {}) }} onClick={() => onMode('table')}>
            Таблицу
          </button>
          <button type="button" style={{ ...chip, ...(mode === 'cells' ? chipActive : {}) }} onClick={() => onMode('cells')}>
            Отдельные ячейки
          </button>
        </div>
      </Field>

      {mode === 'table' && (
        <>
          <Field label="Показатели расположены"
            hint="«В столбцах» — обычный отчёт: строка = объект (район, МФЦ), столбец = показатель. «В строках» — когда наоборот: слева перечень показателей, а по столбцам идут периоды или подразделения.">
            <select style={{ ...input, width: 170 }} value={orientation}
              onChange={(e) => onOrientation(e.target.value as 'columns' | 'rows')}>
              <option value="columns">в столбцах</option>
              <option value="rows">в строках</option>
            </select>
          </Field>
          {/* При «показателях в строках» область транспонирована, и то же самое
              число означает, сколько ЛЕВЫХ столбцов служат заголовками. */}
          <Field
            label={orientation === 'rows' ? 'Столбцов-заголовков слева' : 'Этажей шапки'}
            hint={orientation === 'rows'
              ? 'Сколько левых столбцов — это названия показателей, а не данные.'
              : 'Сколько верхних строк области — заголовки, а не данные. У многоэтажной шапки уровни склеиваются в имя показателя через «·».'}
          >
            <input style={{ ...input, width: 80 }} type="number" min={0} max={10} value={headerRows}
              onChange={(e) => onHeaderRows(Math.max(0, Number(e.target.value) || 0))} />
          </Field>
          <Field
            label={`Область: строки ${rect[0] + 1}–${rect[2] + 1}, столбцы ${colName(rect[1])}–${colName(rect[3])}`}
            hint="Часть листа, в которой лежит таблица. Задаётся протягиванием мыши по ячейкам. Всё, что вне области (шапка письма, подписи внизу), в дашборд не попадает."
          >
            <button type="button" style={chip} onClick={onResetRect}>Взять весь лист</button>
          </Field>
        </>
      )}
    </div>
  )
}

function FieldsPanel({ preview, previewing, transposed, excluded, names, types, labelField, onName, onType, onLabel, onToggle }: {
  preview: LayoutPreview | null; previewing: boolean; transposed: boolean
  excluded: Set<number>; names: Record<number, string>; types: Record<number, string>
  labelField: number | null
  onName: (i: number, v: string) => void
  onType: (i: number, v: string) => void
  onLabel: (i: number) => void
  onToggle: (i: number) => void
}) {
  if (!preview) return <div style={muted}>{previewing ? 'Считаем разметку…' : 'Выберите область данных.'}</div>
  const cols = preview.columns
  const kept = cols.filter((c) => !excluded.has(c.column_index))
  return (
    <div>
      <h3 style={h3}>
        Показатели {previewing && <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>· пересчёт…</span>}
      </h3>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
        Найдено {cols.length}, берём {kept.length}. Строк данных: {preview.row_count}.
        {transposed && ' Показатели взяты из строк листа.'}
      </div>
      <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
        <div style={{ ...mapRow, background: 'var(--surface-2)', fontWeight: 600, fontSize: 12, color: 'var(--text-muted)' }}>
          <span style={{ width: 30 }}>вкл.</span>
          <span style={{ flex: 1 }}>{transposed ? 'Строка листа' : 'Столбец в файле'}</span>
          <span style={{ flex: 1, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            Название показателя
            <InfoTip text="Под этим именем показатель появится на дашборде и в списке метрик. По умолчанию собирается из шапки файла — исправьте на короткое и понятное руководителю." />
          </span>
          <span style={{ width: 110 }}>Тип</span>
          <span style={{ width: 90, textAlign: 'center', display: 'inline-flex', alignItems: 'center', gap: 4, justifyContent: 'center' }}>
            Названия строк
            <InfoTip text="Столбец, из которого берутся подписи строк на дашборде — например, названия районов или МФЦ. Такой столбец должен быть ровно один." />
          </span>
        </div>
        {cols.map((c) => {
          const on = !excluded.has(c.column_index)
          return (
            <div key={c.column_index} style={{ ...mapRow, opacity: on ? 1 : 0.5 }}>
              <span style={{ width: 30 }}>
                <input type="checkbox" checked={on} onChange={() => onToggle(c.column_index)} />
              </span>
              {/* Полный путь по шапке — для сверки с файлом. Сокращаем середину,
                  а не хвост: у составных заголовков различие как раз в конце. */}
              <span style={{ flex: 1, fontSize: 12, color: 'var(--text-muted)' }} title={c.source_header}>
                {elideMiddle(c.source_header, 130)}
              </span>
              <span style={{ flex: 1 }}>
                <input id={`field-name-${c.column_index}`} style={{ ...input, width: '95%', height: 30 }}
                  title="Так показатель будет называться на дашборде"
                  value={names[c.column_index] ?? c.field_name}
                  onChange={(e) => onName(c.column_index, e.target.value)} />
              </span>
              <span style={{ width: 110 }}>
                <select style={{ ...input, width: 104, height: 30 }} value={types[c.column_index] ?? c.data_type}
                  onChange={(e) => onType(c.column_index, e.target.value)}>
                  {TYPES.map((t) => <option key={t.v} value={t.v}>{t.t}</option>)}
                </select>
              </span>
              <span style={{ width: 90, textAlign: 'center' }}>
                <input type="radio" name="rowlabel" checked={labelField === c.column_index}
                  onChange={() => onLabel(c.column_index)} />
              </span>
            </div>
          )
        })}
      </div>

      {preview.sample.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h3 style={h3}>
            Так это будет выглядеть на дашборде{' '}
            <InfoTip text="Черновик по выбранным столбцам и строкам: ничего не сохраняется. Меняйте разметку — картинка пересчитается сразу. На готовом дашборде значения считаются метриками, вид виджетов настраивается отдельно." />
          </h3>
          <DashboardDraft
            columns={kept}
            rows={preview.sample}
            labelColumn={labelField ?? preview.row_label_column}
            names={names}
            totalRows={preview.row_count}
          />
        </div>
      )}

      {preview.sample.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h3 style={h3}>Что получится (данные)</h3>
          <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 10 }}>
            <table style={{ borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  {kept.map((c) => (
                    <th key={c.column_index} style={outHead} title={names[c.column_index] ?? c.field_name}>
                      {/* Сокращаем середину, а не хвост: ограничение по числу
                          строк обрезало бы конец имени — там всё различие. */}
                      <span style={headClamp}>{elideMiddle(names[c.column_index] ?? c.field_name, 90)}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.sample.map((row, i) => (
                  <tr key={i}>
                    {kept.map((c) => <td key={c.column_index} style={outCell}>{row[c.column_index] || '—'}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.row_count > preview.sample.length && (
            <div style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 4 }}>
              …и ещё {preview.row_count - preview.sample.length} строк
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CellsPanel({ picked, onRename, onRemove }: {
  picked: PickedCell[]; onRename: (i: number, v: string) => void; onRemove: (i: number) => void
}) {
  if (!picked.length) return <div style={muted}>Ячейки не выбраны — кликните по нужным цифрам в таблице.</div>
  return (
    <div>
      <h3 style={h3}>Выбранные показатели ({picked.length})</h3>
      <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
        {picked.map((p, i) => (
          <div key={`${p.row}:${p.col}`} style={mapRow}>
            <span style={{ width: 70, fontSize: 12, color: 'var(--text-muted)' }}>{colName(p.col)}{p.row + 1}</span>
            <span style={{ flex: 1 }}>
              <input style={{ ...input, width: '95%', height: 30 }} value={p.field_name}
                onChange={(e) => onRename(i, e.target.value)} />
            </span>
            <button type="button" style={{ ...chip, color: 'var(--danger)' }} onClick={() => onRemove(i)}>убрать</button>
          </div>
        ))}
      </div>
    </div>
  )
}

function ResultPanel({ result, onBack }: { result: ReleaseResult; onBack: () => void }) {
  return (
    <div style={{ border: '1px solid var(--success-bg)', background: 'var(--success-bg)', borderRadius: 12, padding: 20 }}>
      <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--success)', marginBottom: 6 }}>✓ Выпуск датасета создан</div>
      <div style={{ fontSize: 14, color: 'var(--text-2)' }}>
        Материализовано <strong>{result.values_count}</strong> значений из <strong>{result.rows}</strong> строк.
        {result.superseded_release_id && ' Прежний выпуск за этот период помечен как замещённый.'}
      </div>
      {result.validation && result.validation.warnings.length > 0 && (
        <div style={{ marginTop: 12, border: '1px solid var(--warn)', background: 'var(--warn-bg)', borderRadius: 10, padding: '10px 12px' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--warn)', marginBottom: 6 }}>
            ⚠ Проверка данных: замечания ({result.validation.warnings.length}) — данные загружены, рекомендуем проверить
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: 'var(--warn)' }}>
            {result.validation.warnings.map((w) => <li key={w.code} style={{ marginBottom: 2 }}>{w.message}</li>)}
          </ul>
        </div>
      )}
      {result.validation && result.validation.ok && (
        <div style={{ marginTop: 10, fontSize: 13, color: 'var(--success)' }}>✓ Проверка данных пройдена без замечаний.</div>
      )}
      <button style={{ ...btn, marginTop: 14 }} onClick={onBack}>К документам</button>
    </div>
  )
}

function ConflictDialog({ conflict, busy, onSupersede, onCancel }: {
  conflict: { name: string; created_at: string }; busy: boolean
  onSupersede: () => void; onCancel: () => void
}) {
  return (
    <div style={overlay} onClick={onCancel}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Выпуск за этот период уже существует</div>
        <div style={{ fontSize: 14, color: 'var(--text-2)', marginBottom: 16 }}>
          Активный выпуск: «{conflict.name}» от {new Date(conflict.created_at).toLocaleString('ru-RU')}.<br />
          Заместить его новыми данными? Прежний сохранится в истории как замещённый.
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button style={btnGhost} onClick={onCancel} disabled={busy}>Отмена</button>
          <button style={btnDanger} onClick={onSupersede} disabled={busy}>{busy ? 'Замещение…' : 'Заместить'}</button>
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { t: string; bg: string; c: string }> = {
    none: { t: 'не распознан', bg: 'var(--surface-3)', c: 'var(--text-muted)' },
    queued: { t: 'в очереди', bg: 'var(--warn-bg)', c: 'var(--warn)' },
    running: { t: 'распознаётся…', bg: 'var(--warn-bg)', c: 'var(--warn)' },
    succeeded: { t: 'распознан', bg: 'var(--success-bg)', c: 'var(--success)' },
    needs_review: { t: 'нужна проверка', bg: 'var(--warn-bg)', c: 'var(--warn)' },
    failed: { t: 'ошибка', bg: 'var(--danger-bg)', c: 'var(--danger)' },
  }
  const s = map[status] || map.none
  return <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 12, background: s.bg, color: s.c }}>{s.t}</span>
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12, color: 'var(--text-muted)' }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {label}{hint && <InfoTip text={hint} />}
      </span>
      {children}
    </label>
  )
}

const crumb: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 14, padding: 0 }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14 }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { height: 36, padding: '0 14px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', fontSize: 14, cursor: 'pointer' }
const btnDanger: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--danger)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
const chip: React.CSSProperties = { padding: '6px 12px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', fontSize: 13, cursor: 'pointer' }
// border целиком, а не borderColor поверх сокращённого свойства из chip:
// иначе React предупреждает о смешивании и при перерисовке рамка «прыгает».
const chipActive: React.CSSProperties = { background: 'var(--accent-weak-bg)', border: '1px solid var(--accent)', color: 'var(--accent)' }
const h3: React.CSSProperties = { fontSize: 14, margin: '0 0 8px' }
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 14 }
const mapRow: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderTop: '1px solid var(--border-faint)' }
const hintBox: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
  background: 'var(--warn-bg)', color: 'var(--warn)', fontSize: 13,
  padding: '8px 12px', borderRadius: 8, margin: '0 0 14px',
}
// Заголовки переносим по словам и ограничиваем ширину: составное имя
// показателя в одну строку растягивает таблицу на несколько экранов вширь,
// и сравнить столбцы глазами невозможно.
const outHead: React.CSSProperties = {
  border: '1px solid var(--border-faint)', padding: '5px 9px',
  background: 'var(--accent-weak-bg)', color: 'var(--accent)', fontSize: 12,
  whiteSpace: 'normal', overflowWrap: 'anywhere', maxWidth: 190, minWidth: 90,
  textAlign: 'left', verticalAlign: 'bottom',
}
// Больше пяти строк заголовок разрастаться не должен: у формы на 15 граф
// шапка занимала бы пол-экрана. Полное имя — в подсказке при наведении.
const headClamp: React.CSSProperties = {
  display: '-webkit-box', WebkitLineClamp: 5, WebkitBoxOrient: 'vertical', overflow: 'hidden',
}
const outCell: React.CSSProperties = {
  border: '1px solid var(--border-faint)', padding: '5px 9px',
  whiteSpace: 'normal', overflowWrap: 'anywhere', maxWidth: 190, verticalAlign: 'top',
}
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const warnBox: React.CSSProperties = { background: 'var(--warn-bg)', color: 'var(--warn)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 8 }
const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }
const dialog: React.CSSProperties = { background: 'var(--surface)', borderRadius: 14, padding: 24, width: 440, maxWidth: '90vw', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }
