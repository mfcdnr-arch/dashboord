import { useEffect, useState } from 'react'
import {
  createRelease, getExtractionForVersion, getJob, getMappingSuggestion, startExtraction,
  type Doc, type ExtractionJob, type ReleaseResult,
} from '../api'

const TYPES = [
  { v: 'number', t: 'Число' },
  { v: 'date', t: 'Дата' },
  { v: 'text', t: 'Текст' },
]

// Редактируемая строка маппинга (поверх авто-предложения).
interface Col {
  column_index: number
  source_header: string
  field_code: string
  field_name: string
  data_type: string
  is_row_label: boolean
  include: boolean
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const baseName = (f: string) => f.replace(/\.[^.]+$/, '')

export default function ExtractionPage({ doc, canManage, onBack }: { doc: Doc; canManage: boolean; onBack: () => void }) {
  const [job, setJob] = useState<ExtractionJob | null>(null)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [tableId, setTableId] = useState<string | null>(null)
  const [cols, setCols] = useState<Col[]>([])
  const [code, setCode] = useState('dataset')
  const [name, setName] = useState(baseName(doc.original_filename))
  const [period, setPeriod] = useState(doc.reporting_period_start || '')

  const [submitting, setSubmitting] = useState(false)
  const [conflict, setConflict] = useState<{ id: string; name: string; created_at: string } | null>(null)
  const [result, setResult] = useState<ReleaseResult | null>(null)

  const fail = (e: unknown) => setError((e as Error).message)

  useEffect(() => {
    if (!doc.version_id) { setLoading(false); return }
    getExtractionForVersion(doc.version_id)
      .then((j) => { setJob(j); if (j.tables?.length && j.job_id) selectTable(j, j.tables[0].id) })
      .catch(fail)
      .finally(() => setLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

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

  async function selectTable(j: ExtractionJob, tid: string) {
    setTableId(tid)
    if (!j.job_id) return
    try {
      const sug = await getMappingSuggestion(j.job_id, tid)
      setCols(sug.columns.map((c) => ({
        column_index: c.column_index, source_header: c.source_header,
        field_code: c.field_code, field_name: c.field_name, data_type: c.data_type,
        is_row_label: c.is_row_label, include: true,
      })))
    } catch (e) { fail(e) }
  }

  function patch(idx: number, p: Partial<Col>) {
    setCols((cs) => cs.map((c) => (c.column_index === idx ? { ...c, ...p } : c)))
  }
  function setRowLabel(idx: number) {
    setCols((cs) => cs.map((c) => ({ ...c, is_row_label: c.column_index === idx, include: c.column_index === idx ? true : c.include })))
  }

  async function submit(supersede: boolean) {
    if (!job?.job_id || !tableId) return
    const fields = cols.filter((c) => c.include).map((c) => ({
      column_index: c.column_index, field_code: c.field_code.trim(), field_name: c.field_name.trim(),
      data_type: c.data_type, is_row_label: c.is_row_label,
    }))
    if (!fields.length) { setError('Не выбрано ни одного столбца'); return }
    if (!fields.some((f) => f.is_row_label)) { setError('Отметьте столбец-метку строки (◉)'); return }
    if (!code.trim() || !name.trim()) { setError('Заполните код и название датасета'); return }
    setSubmitting(true); setError(null)
    try {
      const r = await createRelease(job.job_id, {
        table_id: tableId, code: code.trim(), name: name.trim(),
        reporting_period_start: period || null, fields, supersede,
      })
      if ('conflict' in r) setConflict(r.existing)
      else { setResult(r); setConflict(null) }
    } catch (e) { fail(e) } finally { setSubmitting(false) }
  }

  const table = job?.tables.find((t) => t.id === tableId) || null
  const ready = job?.status === 'succeeded' || job?.status === 'needs_review'

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <button style={crumb} onClick={onBack}>← Назад к документам</button>
        <StatusBadge status={starting ? 'running' : job?.status || 'none'} />
      </div>
      <h2 style={{ fontSize: 17, margin: '0 0 4px' }}>Распознавание: {doc.original_filename}</h2>
      <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 16 }}>
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
          {job!.tables.length > 1 && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
              {job!.tables.map((t) => (
                <button key={t.id} onClick={() => selectTable(job!, t.id)}
                  style={{ ...chip, ...(t.id === tableId ? chipActive : {}) }}>
                  {t.sheet_or_page || `Таблица ${t.table_index + 1}`} · {t.row_count}×{t.column_count}
                </button>
              ))}
            </div>
          )}

          {table && <PreviewGrid table={table} />}

          {table && (
            <div style={{ marginTop: 20 }}>
              <h3 style={h3}>Сопоставление столбцов</h3>
              <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>
                Отметьте столбец-метку строки (◉), задайте тип и снимите ненужные столбцы.
              </div>
              <MappingEditor cols={cols} disabled={!canManage} onPatch={patch} onRowLabel={setRowLabel} />
            </div>
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

function PreviewGrid({ table }: { table: ExtractionJob['tables'][number] }) {
  return (
    <div>
      <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 6 }}>
        Предпросмотр · {table.row_count} строк × {table.column_count} столбцов · шапка: {table.header_rows} стр.
      </div>
      <div style={{ overflowX: 'auto', border: '1px solid #e5e7eb', borderRadius: 10 }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
          <tbody>
            {table.preview.slice(0, 12).map((row, ri) => (
              <tr key={ri} style={{ background: ri < table.header_rows ? '#f3f6fc' : '#fff' }}>
                {row.map((cell, ci) => (
                  <td key={ci} style={{
                    border: '1px solid #eef0f3', padding: '5px 9px', whiteSpace: 'nowrap',
                    fontWeight: ri < table.header_rows ? 600 : 400,
                    color: ri < table.header_rows ? '#2f5496' : '#111827',
                  }}>{cell || '—'}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.row_count > 12 && <div style={{ fontSize: 12, color: '#9aa4b2', marginTop: 4 }}>…показаны первые 12 строк</div>}
    </div>
  )
}

function MappingEditor({ cols, disabled, onPatch, onRowLabel }: {
  cols: Col[]; disabled: boolean
  onPatch: (idx: number, p: Partial<Col>) => void
  onRowLabel: (idx: number) => void
}) {
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 10, overflow: 'hidden' }}>
      <div style={{ ...mapRow, background: '#f9fafb', fontWeight: 600, fontSize: 12, color: '#6b7280' }}>
        <span style={{ width: 30 }}>вкл.</span>
        <span style={{ flex: 1 }}>Столбец в файле</span>
        <span style={{ flex: 1 }}>Имя поля</span>
        <span style={{ width: 110 }}>Тип</span>
        <span style={{ width: 90, textAlign: 'center' }}>Метка строки</span>
      </div>
      {cols.map((c) => (
        <div key={c.column_index} style={{ ...mapRow, opacity: c.include ? 1 : 0.5 }}>
          <span style={{ width: 30 }}>
            <input type="checkbox" checked={c.include} disabled={disabled || c.is_row_label}
              onChange={(e) => onPatch(c.column_index, { include: e.target.checked })} />
          </span>
          <span style={{ flex: 1, fontSize: 13, color: '#374151' }}>{c.source_header}</span>
          <span style={{ flex: 1 }}>
            <input style={{ ...input, width: '95%', height: 30 }} value={c.field_name} disabled={disabled}
              onChange={(e) => onPatch(c.column_index, { field_name: e.target.value })} />
          </span>
          <span style={{ width: 110 }}>
            <select style={{ ...input, width: 104, height: 30 }} value={c.data_type} disabled={disabled}
              onChange={(e) => onPatch(c.column_index, { data_type: e.target.value })}>
              {TYPES.map((t) => <option key={t.v} value={t.v}>{t.t}</option>)}
            </select>
          </span>
          <span style={{ width: 90, textAlign: 'center' }}>
            <input type="radio" name="rowlabel" checked={c.is_row_label} disabled={disabled}
              onChange={() => onRowLabel(c.column_index)} />
          </span>
        </div>
      ))}
    </div>
  )
}

function ResultPanel({ result, onBack }: { result: ReleaseResult; onBack: () => void }) {
  return (
    <div style={{ border: '1px solid #cfe9dd', background: '#f2fbf7', borderRadius: 12, padding: 20 }}>
      <div style={{ fontSize: 15, fontWeight: 600, color: '#0f6e56', marginBottom: 6 }}>✓ Выпуск датасета создан</div>
      <div style={{ fontSize: 14, color: '#374151' }}>
        Материализовано <strong>{result.values_count}</strong> значений из <strong>{result.rows}</strong> строк.
        {result.superseded_release_id && ' Прежний выпуск за этот период помечен как замещённый.'}
      </div>
      {result.validation && result.validation.warnings.length > 0 && (
        <div style={{ marginTop: 12, border: '1px solid #f0d9a8', background: '#fff8e8', borderRadius: 10, padding: '10px 12px' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#8a6d1a', marginBottom: 6 }}>
            ⚠ Проверка данных: замечания ({result.validation.warnings.length}) — данные загружены, рекомендуем проверить
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: '#7a5c12' }}>
            {result.validation.warnings.map((w) => <li key={w.code} style={{ marginBottom: 2 }}>{w.message}</li>)}
          </ul>
        </div>
      )}
      {result.validation && result.validation.ok && (
        <div style={{ marginTop: 10, fontSize: 13, color: '#0f6e56' }}>✓ Проверка данных пройдена без замечаний.</div>
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
        <div style={{ fontSize: 14, color: '#374151', marginBottom: 16 }}>
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
    none: { t: 'не распознан', bg: '#f1f2f4', c: '#6b7280' },
    queued: { t: 'в очереди', bg: '#fef6e0', c: '#8a6d1a' },
    running: { t: 'распознаётся…', bg: '#fef6e0', c: '#8a6d1a' },
    succeeded: { t: 'распознан', bg: '#e1f5ee', c: '#0f6e56' },
    needs_review: { t: 'нужна проверка', bg: '#fef6e0', c: '#8a6d1a' },
    failed: { t: 'ошибка', bg: '#fcebeb', c: '#a32d2d' },
  }
  const s = map[status] || map.none
  return <span style={{ fontSize: 12, padding: '3px 10px', borderRadius: 12, background: s.bg, color: s.c }}>{s.t}</span>
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12, color: '#6b7280' }}>
      {label}{children}
    </label>
  )
}

const crumb: React.CSSProperties = { border: 'none', background: 'none', color: '#2f5496', cursor: 'pointer', fontSize: 14, padding: 0 }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14 }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: '#2f5496', color: '#fff', fontSize: 14, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { height: 36, padding: '0 14px', border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', fontSize: 14, cursor: 'pointer' }
const btnDanger: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: '#a32d2d', color: '#fff', fontSize: 14, cursor: 'pointer' }
const chip: React.CSSProperties = { padding: '6px 12px', border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', fontSize: 13, cursor: 'pointer' }
const chipActive: React.CSSProperties = { background: '#eef', borderColor: '#2f5496', color: '#2f5496' }
const h3: React.CSSProperties = { fontSize: 14, margin: '0 0 8px' }
const muted: React.CSSProperties = { color: '#6b7280', fontSize: 14 }
const mapRow: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderTop: '1px solid #f0f0f0' }
const errBox: React.CSSProperties = { background: '#fcebeb', color: '#a32d2d', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const warnBox: React.CSSProperties = { background: '#fef6e0', color: '#8a6d1a', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 8 }
const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }
const dialog: React.CSSProperties = { background: '#fff', borderRadius: 14, padding: 24, width: 440, maxWidth: '90vw', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }
