import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { addComment, deleteComment, listComments, type DashComment } from '../../api'

const ru = (iso?: string | null) => (iso ? iso.slice(0, 10).split('-').reverse().join('.') : '')
const when = (iso: string) => new Date(iso).toLocaleString('ru-RU',
  { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })

// Обсуждение КОНКРЕТНОЙ ЦИФРЫ (п. 8).
//
// Раньше замечание можно было оставить только ко всему отчёту, и разговор
// начинался с объяснения, о какой из тридцати цифр речь.
//
// Главное здесь — ДАТА. Виджет показывает последний выпуск, поэтому замечание
// об августовском числе через неделю висело бы рядом с сентябрьским и молча
// вводило бы в заблуждение. Вместе с текстом сохраняется отчётная дата, которую
// человек видел, а лента прямо помечает замечания, относящиеся к ДРУГОЙ цифре.
//
// Окно выводится порталом в body: карточка виджета обрезает содержимое
// (`overflow: hidden`), а сетка дашборда двигает её трансформацией — внутри
// такого предка `position: fixed` считается от него, а не от окна. Эти грабли
// в проекте уже ловили дважды (drill-модалка и подсказка ⓘ).
export default function WidgetComments(
  { dashboardId, widgetId, widgetName, period, rowLabel, onClose, onChanged }: {
    dashboardId: string; widgetId: string; widgetName: string
    /** Отчётная дата, которую человек видит СЕЙЧАС. Уходит вместе с текстом. */
    period?: string | null
    /** Строка, в которую провалились: замечание про район, а не про итог. */
    rowLabel?: string | null
    onClose: () => void
    onChanged?: () => void
  },
) {
  const [items, setItems] = useState<DashComment[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const box = useRef<HTMLTextAreaElement>(null)

  const load = () => listComments(dashboardId, 50, 0, widgetId)
    .then((p) => setItems(p.items))
    .catch((e) => setErr((e as Error).message))

  useEffect(() => { load(); box.current?.focus() }, [dashboardId, widgetId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  async function send() {
    const body = text.trim()
    if (!body) return
    setBusy(true); setErr(null)
    try {
      await addComment(dashboardId, body, { widget_id: widgetId, period, row_label: rowLabel })
      setText(''); await load(); onChanged?.()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  async function remove(id: string) {
    try { await deleteComment(dashboardId, id); await load(); onChanged?.() }
    catch (e) { setErr((e as Error).message) }
  }

  return createPortal(
    <div style={backdrop} onClick={onClose}>
      <div style={modal} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <div style={{ fontSize: 15, fontWeight: 600, flex: 1, minWidth: 0 }}>
            💬 Замечания к цифре
          </div>
          <button type="button" onClick={onClose} style={xBtn} title="Закрыть">✕</button>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>
          {widgetName}
          {rowLabel && <> · строка «{rowLabel}»</>}
          {period && <> · данные на {ru(period)}</>}
        </div>

        <div style={{ maxHeight: 300, overflowY: 'auto', margin: '10px 0' }}>
          {items.length === 0 && (
            <div style={{ fontSize: 12.5, color: 'var(--text-2)' }}>
              Замечаний к этой цифре пока нет. Напишите, если значение выглядит неверным
              или требует пояснения — это увидят все, кому доступен отчёт.
            </div>
          )}
          {items.map((c) => {
            // Замечание про ДРУГУЮ отчётную дату: цифра с тех пор изменилась,
            // и молчать об этом нельзя — иначе старый текст читается как
            // сказанный про то, что на экране сейчас.
            const stale = !!c.period && !!period && c.period !== period
            return (
              <div key={c.id} style={{ padding: '6px 0', borderBottom: '1px solid var(--border-faint)' }}>
                <div style={{ fontSize: 11.5, color: 'var(--text-2)' }}>
                  <b>{c.author}</b> · {when(c.created_at)}
                  {c.row_label && <> · строка «{c.row_label}»</>}
                  {c.can_delete && (
                    <button type="button" onClick={() => remove(c.id)} style={linkBtn} title="Удалить">
                      удалить
                    </button>
                  )}
                </div>
                {stale && (
                  <div style={{ fontSize: 11, color: 'var(--alert-warn)' }}>
                    ⌛ о цифре за {ru(c.period)} — сейчас на экране данные на {ru(period)}
                  </div>
                )}
                <div style={{ fontSize: 13, whiteSpace: 'pre-wrap', marginTop: 2 }}>{c.body}</div>
              </div>
            )
          })}
        </div>

        {err && <div style={errBox}>{err}</div>}
        <textarea ref={box} value={text} onChange={(e) => setText(e.target.value)}
          rows={3} placeholder="Например: значение занижено — отделение переезжало"
          style={area} />
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6 }}>
          <button type="button" onClick={send} disabled={busy || !text.trim()} style={btn}>
            {busy ? 'Отправка…' : 'Отправить'}
          </button>
          <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
            Замечание сохранит отчётную дату{period ? ` (${ru(period)})` : ''} — через неделю будет
            видно, о какой цифре шла речь.
          </span>
        </div>
      </div>
    </div>,
    document.body,
  )
}

const backdrop: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,.35)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
}
const modal: React.CSSProperties = {
  background: 'var(--surface)', color: 'var(--text)', borderRadius: 10, padding: 16,
  width: 'min(560px, 94vw)', maxHeight: '86vh', overflowY: 'auto',
  boxShadow: '0 10px 40px rgba(0,0,0,.25)',
}
const area: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: 8, borderRadius: 6, fontSize: 13,
  border: '1px solid var(--border-strong)', background: 'var(--surface)', color: 'var(--text)',
  fontFamily: 'inherit', resize: 'vertical',
}
const btn: React.CSSProperties = {
  padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
  background: 'var(--accent)', color: '#fff', fontSize: 13,
}
const xBtn: React.CSSProperties = {
  background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--text-2)',
}
const linkBtn: React.CSSProperties = {
  background: 'none', border: 'none', padding: '0 0 0 8px', cursor: 'pointer',
  color: 'var(--accent)', textDecoration: 'underline', fontSize: 11,
}
const errBox: React.CSSProperties = {
  padding: 8, borderRadius: 6, fontSize: 12.5, marginBottom: 6,
  background: 'var(--alert-danger-bg)', color: 'var(--alert-danger)',
}
