import { useCallback, useEffect, useRef, useState } from 'react'
import {
  knownForms, listFolders, listObjects, routeUpload, uploadJournal, uploadToInbox,
  type Folder, type JournalItem, type KnownForm, type Obj,
} from '../api'

/**
 * Раздел «Загрузка» — общая зона приёма файлов (шаг ⑤).
 *
 * До сих пор, чтобы сдать недельную форму, человек обязан был знать устройство
 * системы: найти объект, внутри него папку, ввести отчётную дату. Здесь он
 * просто бросает файл: дата вычитывается из имени, а папку система определяет
 * сама — по отпечатку структуры формы, уже после распознавания.
 *
 * Чего зона НЕ делает: не угадывает папку, когда форма незнакома или совпала с
 * несколькими. Такой файл остаётся во «Входящих» и ждёт человека — положить
 * его не туда значит показать неверные цифры на дашборде без единого признака
 * ошибки.
 */
export default function UploadsPage() {
  const [items, setItems] = useState<JournalItem[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')
  const [drag, setDrag] = useState(false)
  // Дата нужна редко — только когда её нет в имени файла; поэтому поле
  // необязательное и стоит рядом с зоной, а не спрашивается окном.
  const [period, setPeriod] = useState('')
  // Отдельный фильтр ЖУРНАЛА — по отчётной дате уже загруженных файлов, а не
  // по дате для следующей загрузки. Раньше оба смысла делило одно поле, и
  // смена даты без загрузки файла честно ничего не меняла — путаница.
  const [filterPeriod, setFilterPeriod] = useState('')
  const [objects, setObjects] = useState<Obj[]>([])
  const [folders, setFolders] = useState<Record<string, Folder[]>>({})
  const [routing, setRouting] = useState<string | null>(null)
  const [known, setKnown] = useState<KnownForm[]>([])
  const [knownOpen, setKnownOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const timer = useRef<number | null>(null)

  const load = useCallback(async () => {
    try { setItems((await uploadJournal(50, filterPeriod || undefined)).items) } catch (e) { setErr((e as Error).message) }
    // Тем же тиком: после выпуска (авто- или ручного) список известных форм
    // мог пополниться — подсказка не должна отставать от журнала.
    knownForms().then((r) => setKnown(r.items)).catch(() => {})
  }, [filterPeriod])

  useEffect(() => { load(); listObjects().then(setObjects).catch(() => {}) }, [load])

  // Пока файлы распознаются, состояние в журнале меняется само: без опроса
  // человек видел бы «распознаётся…» и не понимал, ждать ему или обновлять.
  useEffect(() => {
    const pending = items.some((i) => i.state === 'распознаётся…')
    if (!pending) return
    timer.current = window.setTimeout(load, 3000)
    return () => { if (timer.current) window.clearTimeout(timer.current) }
  }, [items, load])

  async function send(files: FileList | File[]) {
    setErr(''); setNote(''); setBusy(true)
    const done: string[] = []
    const failed: string[] = []
    try {
      for (const f of Array.from(files)) {
        try {
          const r = await uploadToInbox(f, period || undefined)
          done.push(r.period_guessed
            ? `${f.name} — дата ${ru(r.reporting_period_start)} из имени файла`
            : f.name)
        } catch (e) {
          const msg = (e as Error).message
          // Системных окон в проекте нет (браузер их подавляет, и кнопка
          // выглядит сломанной): дату человек задаёт полем рядом с зоной, а мы
          // говорим, какому именно файлу её не хватило.
          failed.push(/дат/i.test(msg)
            ? `${f.name}: в имени файла нет отчётной даты — укажите её в поле «Отчётная дата» и перетащите файл ещё раз`
            : `${f.name}: ${msg}`)
        }
      }
      if (done.length) setNote(`Принято: ${done.join('; ')}. Разбираем…`)
      if (failed.length) setErr(failed.join(' · '))
    } finally {
      setBusy(false)
      load()
    }
  }

  async function openRouting(it: JournalItem) {
    setRouting(routing === it.id ? null : it.id)
    if (!objects.length) setObjects(await listObjects())
  }

  async function loadFolders(objectId: string) {
    if (folders[objectId]) return
    try { setFolders((s) => ({ ...s, [objectId]: [] })); const f = await listFolders(objectId); setFolders((s) => ({ ...s, [objectId]: f })) } catch { /* пусто */ }
  }

  async function place(it: JournalItem, folderId: string) {
    try { await routeUpload(it.id, folderId); setRouting(null); load() } catch (e) { setErr((e as Error).message) }
  }

  const waiting = items.filter((i) => i.in_inbox)

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Загрузка</h2>

      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files?.length) send(e.dataTransfer.files) }}
        onClick={() => fileRef.current?.click()}
        style={{
          border: `2px dashed ${drag ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 14,
          padding: '28px 20px', textAlign: 'center', cursor: 'pointer',
          background: drag ? 'var(--accent-weak-bg)' : 'var(--surface)', marginBottom: 14,
        }}>
        <div style={{ fontSize: 34, lineHeight: 1 }}>📥</div>
        <div style={{ fontWeight: 700, marginTop: 8 }}>
          {busy ? 'Загружаем…' : 'Перетащите файлы сюда или нажмите, чтобы выбрать'}
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginTop: 6, maxWidth: 620, marginLeft: 'auto', marginRight: 'auto' }}>
          Папку выбирать не нужно: система разберёт файл и по структуре формы сама положит его туда,
          куда складывают такие отчёты. Отчётная дата берётся из имени файла — если её там нет, спросим.
          Незнакомую форму система не «угадывает»: такой файл подождёт вас здесь же.
        </div>
        <input ref={fileRef} type="file" multiple accept=".xlsx,.xls,.csv,.pdf,.docx" style={{ display: 'none' }}
          onChange={(e) => { if (e.target.files?.length) send(e.target.files); e.target.value = '' }} />
      </div>

      <div style={{ ...box('var(--border)'), marginBottom: 14 }}>
        <button type="button" style={{ ...linkBtn, fontWeight: 600, textDecoration: 'none' }}
          onClick={() => setKnownOpen((v) => !v)}>
          {knownOpen ? '▾' : '▸'} Уже узнаются сами: {known.length}
          {known.length === 0 && ' — пока ни одна форма не размечена'}
        </button>
        {known.length > 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 4 }}>
            Файл такой структуры разложится и выпустится автоматически. Форма не из этого
            списка уйдёт во «Входящие» на ручную разметку — один раз, дальше сама.
          </div>
        )}
        {knownOpen && (
          <div style={{ overflowX: 'auto', marginTop: 8 }}>
            <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12.5 }}>
              <thead><tr>
                {['Ведомство / объект', 'Пример файла', 'Куда попадёт', 'Отчётов загружено', 'Разметка от'].map((h) => (
                  <th key={h} style={th}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {known.length === 0 && (
                  <tr><td style={td} colSpan={5}>
                    Ещё ни одна форма не размечена — первый файл каждого нового бланка требует
                    ручного выбора папки один раз, дальше система запомнит его структуру.
                  </td></tr>
                )}
                {known.map((k) => (
                  <tr key={k.object_id}>
                    <td style={{ ...td, fontWeight: 600 }}>{k.object_name}</td>
                    <td style={{ ...td, color: 'var(--text-2)' }}>{k.example_filename || '—'}</td>
                    <td style={td}>{k.folder_name ? `${k.object_name} / ${k.folder_name}` : '—'}</td>
                    <td style={td}>{k.periods_loaded}</td>
                    <td style={{ ...td, color: 'var(--text-muted)' }}>{when(k.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, fontSize: 13 }}>
        <span style={{ color: 'var(--text-muted)' }}>Отчётная дата (если её нет в имени файла):</span>
        <input type="date" value={period} onChange={(e) => setPeriod(e.target.value)}
          style={{ padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text)' }} />
        {period && <button type="button" style={linkBtn} onClick={() => setPeriod('')}>сбросить</button>}
      </div>

      {err && <div style={box('var(--danger)')}>{err}</div>}
      {note && <div style={box('var(--success)')}>{note}</div>}

      {waiting.length > 0 && (
        <div style={{ ...box('var(--warn)'), marginBottom: 14 }}>
          Ждут вашего решения: <b>{waiting.length}</b> — система не смогла определить папку сама.
        </div>
      )}

      <h3 style={{ marginBottom: 8 }}>Журнал импорта</h3>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13 }}>
        <span style={{ color: 'var(--text-muted)' }}>Показать отчёт за дату:</span>
        <input type="date" value={filterPeriod} onChange={(e) => setFilterPeriod(e.target.value)}
          style={{ padding: '5px 8px', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text)' }} />
        {filterPeriod && <button type="button" style={linkBtn} onClick={() => setFilterPeriod('')}>сбросить</button>}
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-faint)', marginBottom: 8 }}>
        {filterPeriod
          ? `Отчёты за ${ru(filterPeriod)}: найдено ${items.length}.`
          : `Что загрузили, куда это попало и почему — по последним ${items.length} файлам.`}
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
          <thead><tr>
            {['Файл', 'Отчёт за', 'Куда попал', 'Почему', 'Состояние', 'Загрузил'].map((h) => (
              <th key={h} style={th}>{h}</th>
            ))}
          </tr></thead>
          <tbody>
            {items.length === 0 && <tr><td style={td} colSpan={6}>Пока ничего не загружали.</td></tr>}
            {items.map((it) => (
              <tr key={it.id} style={it.in_inbox ? { background: 'var(--surface-2)' } : undefined}>
                <td style={{ ...td, fontWeight: 600 }}>{it.filename}</td>
                <td style={td}>{ru(it.period)}</td>
                <td style={td}>
                  {it.in_inbox ? <span style={{ color: 'var(--warn)' }}>📥 Входящие</span>
                    : <>{it.object_name ? `${it.object_name} / ` : ''}{it.folder_name || '—'}</>}
                  {it.in_inbox && (
                    <div>
                      <button type="button" style={linkBtn} onClick={() => openRouting(it)}>
                        {routing === it.id ? 'скрыть' : 'указать папку'}
                      </button>
                      {routing === it.id && (
                        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 4 }}>
                          {objects.map((o) => (
                            <div key={o.id}>
                              <button type="button" style={linkBtn} onClick={() => loadFolders(o.id)}>📁 {o.name}</button>
                              {(folders[o.id] || []).map((f) => (
                                <div key={f.id} style={{ marginLeft: 14 }}>
                                  <button type="button" style={{ ...linkBtn, color: 'var(--text)' }}
                                    onClick={() => place(it, f.id)}>→ {f.name}</button>
                                </div>
                              ))}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </td>
                <td style={{ ...td, maxWidth: 340, color: 'var(--text-2)' }}>
                  {it.routed_by === 'template' && <b style={{ color: 'var(--success)' }}>🤖 </b>}
                  {it.routed_by === 'manual' && <b>✍ </b>}
                  {it.routed_note || (it.in_inbox ? '' : 'папка выбрана при загрузке')}
                </td>
                <td style={td}>{it.state}</td>
                <td style={{ ...td, color: 'var(--text-muted)' }}>
                  {it.uploaded_by || '—'}<div style={{ fontSize: 11 }}>{when(it.uploaded_at)}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ru(iso?: string | null): string {
  return iso && /^\d{4}-\d{2}-\d{2}/.test(iso) ? iso.slice(0, 10).split('-').reverse().join('.') : '—'
}
function when(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${ru(iso)} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const th: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '5px 8px', background: 'var(--surface-2)', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600 }
const td: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '5px 8px', verticalAlign: 'top' }
const linkBtn: React.CSSProperties = { background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--accent)', fontSize: 12.5, textDecoration: 'underline dotted' }
function box(color: string): React.CSSProperties {
  return { border: `1px solid ${color}`, borderRadius: 10, padding: '7px 12px', marginBottom: 10, fontSize: 13 }
}
