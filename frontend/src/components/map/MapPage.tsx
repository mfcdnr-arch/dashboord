import { useEffect, useMemo, useRef, useState } from 'react'
import {
  deleteOffice, getDataSources, getMapSettings, hoursSummary, importOffices, listOffices,
  saveMapSettings, unmatchedRows, updateOffice,
  type DataSet, type ImportResult, type Office, type UnmatchedReport,
} from '../../api'
import { useConfirm } from '../dashboards/ConfirmDialog'
import OfficeForm from './OfficeForm'

// Раздел «Карта» → справочник отделений.
//
// До него отделение существовало только строкой отчёта: адрес, телефон и режим
// работы система не хранила нигде, и поправить их было нечем. Карта строится
// ПО ЭТОМУ СПРАВОЧНИКУ, поэтому правка здесь сразу меняет то, что видно на
// точке, — без пересборки и без участия разработчика.

export default function MapPage({ me }: { me: { roles: string[] } }) {
  const canManage = me.roles.some((r) => ['admin', 'superadmin'].includes(r))
  const { ask, node: confirmNode } = useConfirm()
  const [items, setItems] = useState<Office[]>([])
  const [q, setQ] = useState('')
  const [onlyActive, setOnlyActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [edit, setEdit] = useState<Office | null | undefined>(undefined) // undefined — закрыто, null — новое
  const [report, setReport] = useState<UnmatchedReport | null>(null)
  const [datasets, setDatasets] = useState<DataSet[]>([])
  const [dsCode, setDsCode] = useState<string>('')
  const [imp, setImp] = useState<ImportResult | null>(null)
  const [updateExisting, setUpdateExisting] = useState(false)
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const fail = (e: unknown) => setError((e as Error).message)
  const reload = () => listOffices({ q: q.trim() || undefined, only_active: onlyActive }).then(setItems).catch(fail)

  useEffect(() => { const t = setTimeout(reload, 250); return () => clearTimeout(t) }, [q, onlyActive]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!canManage) return
    getDataSources().then((d) => setDatasets(d.datasets)).catch(() => {})
    getMapSettings().then((s) => { setDsCode(s.map_dataset_code || ''); if (s.map_dataset_code) refreshReport(s.map_dataset_code) }).catch(() => {})
  }, [canManage]) // eslint-disable-line react-hooks/exhaustive-deps

  function refreshReport(code: string) {
    if (!code) { setReport(null); return }
    unmatchedRows(code).then(setReport).catch(fail)
  }
  async function pickDataset(code: string) {
    setDsCode(code)
    try { await saveMapSettings(code || null); refreshReport(code) } catch (e) { fail(e) }
  }

  async function onFile(file: File) {
    setBusy(true); setError(null); setImp(null)
    try {
      setImp(await importOffices(file, updateExisting))
      reload(); if (dsCode) refreshReport(dsCode)
    } catch (e) { fail(e) } finally { setBusy(false); if (fileRef.current) fileRef.current.value = '' }
  }

  async function link(officeId: string, rowLabel: string) {
    try { await updateOffice(officeId, { row_label: rowLabel }); reload(); refreshReport(dsCode) } catch (e) { fail(e) }
  }
  async function remove(o: Office) {
    if (!await ask({
      title: `Удалить отделение «${o.name}»?`,
      message: 'Сведения исчезнут из справочника, и точка пропадёт с карты. Цифры отчётов это не затронет. '
        + 'Если отделение просто закрылось — снимите отметку «действует»: тогда история останется связанной.',
    })) return
    try { await deleteOffice(o.id); reload(); if (dsCode) refreshReport(dsCode) } catch (e) { fail(e) }
  }

  // Строки отчёта для выпадашки в карточке: несопоставленные + уже связанная.
  const rowOptions = useMemo(() => (report?.unmatched || []).map((u) => u.row_label), [report])
  const linkedCount = items.filter((o) => o.row_label).length
  const noCoords = items.filter((o) => o.lat == null).length
  const outside = items.filter((o) => o.inside_contour === false).length

  return (
    <div>
      {confirmNode}
      <h2 style={{ fontSize: 20, margin: '0 0 4px' }}>Карта</h2>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
        Справочник отделений — сведения, которые карта показывает на точке: адрес, телефон, режим работы.
        {canManage ? ' Правка здесь сразу меняет то, что видит человек.' : ' Правка — у администратора.'}
      </div>
      {error && <div style={errBox}>{error}</div>}

      {/* Сверка с отчётом: без неё новое отделение попадает в цифры, но не на карту. */}
      {canManage && (
        <div style={card}>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: report?.unmatched?.length ? 10 : 0 }}>
            <b style={{ fontSize: 13 }}>Сверка с отчётом</b>
            <select style={{ ...inp, width: 320 }} value={dsCode} onChange={(e) => pickDataset(e.target.value)}
              aria-label="Отчёт, по которому сверяются отделения">
              <option value="">— не сверять —</option>
              {datasets.map((d) => <option key={d.code} value={d.code}>{d.name} ({d.code})</option>)}
            </select>
            {report?.dataset_code && (
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                отчёт за {fmtDate(report.period)} · строк {report.rows_total} · связано {report.linked}
              </span>
            )}
          </div>
          {!dsCode && <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>
            Выберите отчёт — и система будет сама показывать отделения, которые появились в данных, но не заведены в справочнике.
          </div>}
          {report && report.unmatched.length > 0 && (
            <div>
              <div style={{ fontSize: 13, marginBottom: 6 }}>
                ⚠ В отчёте есть отделения, которых нет на карте: <b>{report.unmatched.length}</b>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 260, overflowY: 'auto' }}>
                {report.unmatched.map((u) => (
                  <div key={u.row_label} style={rowLine}>
                    <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={u.row_label}>{u.row_label}</span>
                    {u.suggestion ? (
                      <>
                        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>похоже на «{u.suggestion.name}»</span>
                        <button style={linkBtn} onClick={() => link(u.suggestion!.id, u.row_label)}>связать</button>
                      </>
                    ) : <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>подходящего отделения нет</span>}
                    <button style={linkBtn} onClick={() => setEdit(null)}>завести</button>
                  </div>
                ))}
              </div>
            </div>
          )}
          {report && report.unmatched.length === 0 && report.dataset_code && (
            <div style={{ fontSize: 12, color: 'var(--success)' }}>✓ Все строки отчёта сопоставлены отделениям.</div>
          )}
        </div>
      )}

      {/* Панель управления списком */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        <input style={{ ...inp, width: 260 }} value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Поиск по названию, адресу, городу" aria-label="Поиск отделения" />
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
          <input type="checkbox" checked={onlyActive} onChange={(e) => setOnlyActive(e.target.checked)} />
          только действующие
        </label>
        <div style={{ flex: 1 }} />
        {canManage && <>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-muted)', cursor: 'pointer' }}
            title="По умолчанию загрузка добавляет только новые отделения и не трогает то, что вы правили руками">
            <input type="checkbox" checked={updateExisting} onChange={(e) => setUpdateExisting(e.target.checked)} />
            обновлять существующие
          </label>
          <input ref={fileRef} type="file" accept=".csv,text/csv" style={{ display: 'none' }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f) }} />
          <button style={btnGhost} disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? 'Загрузка…' : '⤒ Загрузить перечень'}
          </button>
          <button style={btn} onClick={() => setEdit(null)}>＋ Отделение</button>
        </>}
      </div>

      {imp && (
        <div style={card}>
          <b style={{ fontSize: 13 }}>Загрузка перечня</b>
          <div style={{ fontSize: 13, marginTop: 4 }}>
            Строк в файле: {imp.total} · заведено: {imp.created} · обновлено: {imp.updated} · пропущено как уже известные: {imp.skipped}
          </div>
          {imp.no_coords.length > 0 && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
            Без координат (в справочнике есть, на карте не появятся): {imp.no_coords.join(', ')}
          </div>}
          {imp.outside_contour.length > 0 && <div style={{ fontSize: 12, color: 'var(--danger)', marginTop: 4 }}>
            Точка вне контура республики: {imp.outside_contour.join(', ')}
          </div>}
          {imp.errors.length > 0 && <div style={{ fontSize: 12, color: 'var(--danger)', marginTop: 4 }}>
            Не загружено: {imp.errors.map((e) => (e.line ? `строка ${e.line}: ` : '') + e.error).join('; ')}
          </div>}
          <button style={{ ...linkBtn, marginTop: 6 }} onClick={() => setImp(null)}>скрыть</button>
        </div>
      )}

      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
        Отделений: <b>{items.length}</b>
        {linkedCount > 0 && <> · связано с отчётом: {linkedCount}</>}
        {noCoords > 0 && <> · без координат: {noCoords}</>}
        {outside > 0 && <> · <span style={{ color: 'var(--danger)' }}>вне контура: {outside}</span></>}
      </div>

      {items.length === 0 ? (
        <div style={{ color: 'var(--text-faint)', fontSize: 13 }}>
          {q ? 'Ничего не найдено.' : 'Отделений пока нет. Заведите первое кнопкой «＋ Отделение» или загрузите перечень файлом.'}
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
            {/* Колонки «На карте» и «Отчёт» — служебные: координаты и связка со
                строкой отчёта нужны тому, кто ведёт справочник. Обычному
                человеку «не связано» читается как неисправность, поэтому
                показываем ему только сведения об отделении. */}
            <thead><tr>{['Отделение', 'Адрес', 'Телефон', 'Режим работы', ...(canManage ? ['На карте', 'Отчёт', ''] : [])].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
            <tbody>
              {items.map((o) => (
                <tr key={o.id} style={{ opacity: o.is_active ? 1 : 0.55 }}>
                  <td style={{ ...td, fontWeight: 600 }}>
                    {o.name}
                    {!o.is_active && <span style={{ color: 'var(--text-faint)', fontWeight: 400 }}> · не действует</span>}
                    {o.city && <div style={{ fontWeight: 400, fontSize: 12, color: 'var(--text-muted)' }}>{o.city}</div>}
                  </td>
                  <td style={td}>{o.address || '—'}</td>
                  <td style={{ ...td, whiteSpace: 'nowrap' }}>{o.phone || '—'}</td>
                  <td style={td}>
                    {hoursSummary(o.hours)}
                    {o.note && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{o.note}</div>}
                  </td>
                  {canManage && <td style={{ ...td, whiteSpace: 'nowrap' }}>
                    {o.lat == null ? <span style={{ color: 'var(--text-faint)' }}>нет координат</span>
                      : o.inside_contour === false ? <span style={{ color: 'var(--danger)' }}>вне контура</span>
                        : <span style={{ color: 'var(--success)' }}>✓ {o.lat.toFixed(4)}, {o.lon!.toFixed(4)}</span>}
                  </td>}
                  {canManage && <td style={td}>
                    {o.row_label
                      ? <span title={o.row_label} style={{ display: 'inline-block', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', verticalAlign: 'bottom' }}>{o.row_label}</span>
                      : <span style={{ color: 'var(--text-faint)' }}>не связано</span>}
                  </td>}
                  {canManage && (
                    <td style={{ ...td, whiteSpace: 'nowrap' }}>
                      <button style={linkBtn} onClick={() => setEdit(o)}>изменить</button>
                      <button style={{ ...linkBtn, color: 'var(--danger)' }} onClick={() => remove(o)}>удалить</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {edit !== undefined && (
        <OfficeForm office={edit} rowOptions={rowOptions}
          onClose={() => setEdit(undefined)}
          onSaved={() => { setEdit(undefined); reload(); if (dsCode) refreshReport(dsCode) }} />
      )}
    </div>
  )
}

function fmtDate(iso?: string | null): string {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${d}.${m}.${y}`
}

const inp: React.CSSProperties = { height: 34, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13, boxSizing: 'border-box', background: 'var(--surface)', color: 'var(--text)' }
const btn: React.CSSProperties = { height: 34, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { ...btn, background: 'transparent', color: 'var(--text)', border: '1px solid var(--border-strong)' }
const linkBtn: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: '0 6px 0 0' }
const th: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '6px 10px', background: 'var(--surface-2)', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600 }
const td: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '6px 10px' }
const card: React.CSSProperties = { border: '1px solid var(--border-faint)', borderRadius: 10, padding: 12, marginBottom: 12, background: 'var(--surface-2)', boxSizing: 'border-box' }
const rowLine: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, padding: '3px 0', borderBottom: '1px solid var(--border-faint)' }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
