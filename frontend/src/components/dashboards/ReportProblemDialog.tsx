import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { reportWidgetProblem, widgetProblemKinds, type ProblemKind } from '../../api'

// «Сообщить о проблеме» прямо с виджета (п. 15 списка заказчика — обратная
// связь пользователь → администратор).
//
// Механизм обращений есть с волны C, но добраться до него можно было только
// через «Кабинет», где человека встречало пустое поле. Дальше начиналось самое
// дорогое: объяснить словами, ГДЕ проблема. «На дашборде с обращениями цифра
// какая-то не такая» — по такому описанию администратор не найдёт ни отчёт, ни
// показатель, и переписка уходит на два круга уточнений.
//
// Поэтому контекст (дашборд, страница, показатель, значение на экране) собирает
// СЕРВЕР по id виджета. Отсюда же следует, что вид проблемы выбирается
// нажатием, а не формулируется: человек, у которого «не сходится цифра», чаще
// всего не знает, как это назвать, и потому не пишет вообще.
//
// Окно выводится порталом в body: карточка виджета обрезает содержимое
// (overflow: hidden) — тот же дефект, что уже ловили у подсказки ⓘ и у окна
// «подробнее».
export default function ReportProblemDialog(
  { widgetId, widgetName, onClose, onOpenAppeals }:
  {
    widgetId: string
    widgetName?: string
    onClose: () => void
    /** Переход в свои обращения, чтобы прочитать ответ. Не передан — показываем
     *  только подтверждение: обещать переход, которого нет, хуже. */
    onOpenAppeals?: () => void
  },
) {
  const [kinds, setKinds] = useState<ProblemKind[]>([])
  const [kind, setKind] = useState('wrong_value')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState<{ appended: boolean } | null>(null)

  useEffect(() => { widgetProblemKinds().then((r) => setKinds(r.kinds)).catch(() => setKinds([])) }, [])

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const send = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await reportWidgetProblem(widgetId, kind, comment)
      setDone({ appended: r.appended })
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>Сообщить о проблеме</div>
            {widgetName && (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{widgetName}</div>
            )}
          </div>
          <button style={{ ...xBtn, marginLeft: 'auto' }} onClick={onClose} title="Закрыть">✕</button>
        </div>

        {done ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={okBox}>
              {done.appended
                ? '✓ Дописано в ваше открытое обращение по этому виджету — второе заводить не стали.'
                : '✓ Обращение отправлено администратору.'}
            </div>
            <div style={muted}>
              Что именно вы видели на экране — дашборд, страницу, показатель и его значение —
              система приложила сама. Ответ придёт уведомлением, переписка — в разделе «Кабинет».
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              {onOpenAppeals && (
                <button style={ghostBtn} onClick={() => { onClose(); onOpenAppeals() }}>Мои обращения</button>
              )}
              <button style={primaryBtn} onClick={onClose}>Закрыть</button>
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div>
              <div style={label}>Что не так</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {kinds.map((k) => (
                  <button key={k.code} style={kind === k.code ? chipOn : chip} onClick={() => setKind(k.code)}>
                    {k.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div style={label}>Подробнее (необязательно)</div>
              <textarea
                value={comment} onChange={(e) => setComment(e.target.value)} rows={4} maxLength={2000}
                placeholder="Например: цифра не изменилась после нового отчёта"
                style={area}
              />
            </div>

            <div style={muted}>
              Указывать, где вы это увидели, не нужно: название отчёта, страницы, показателя и
              значение на экране приложатся к обращению автоматически.
            </div>

            {err && <div style={errBox}>{err}</div>}

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button style={ghostBtn} onClick={onClose} disabled={busy}>Отмена</button>
              <button style={primaryBtn} onClick={send} disabled={busy}>
                {busy ? 'Отправка…' : 'Отправить'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex',
  alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 16,
}
const dialog: React.CSSProperties = {
  background: 'var(--surface)', borderRadius: 14, padding: 20, width: 520, maxWidth: '94vw',
  maxHeight: '86vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
}
const label: React.CSSProperties = { fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }
const chip: React.CSSProperties = {
  fontSize: 13, padding: '5px 12px', borderRadius: 14, cursor: 'pointer',
  background: 'var(--surface-2)', color: 'var(--text)', border: '1px solid var(--border-faint)',
}
const chipOn: React.CSSProperties = {
  ...chip, background: 'var(--accent)', color: '#fff', borderColor: 'var(--accent)', fontWeight: 600,
}
const area: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: 8,
  border: '1px solid var(--border-faint)', background: 'var(--surface-2)', color: 'var(--text)',
  fontSize: 13, fontFamily: 'inherit', resize: 'vertical',
}
const primaryBtn: React.CSSProperties = {
  padding: '7px 16px', borderRadius: 8, border: 'none', background: 'var(--accent)',
  color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer',
}
const ghostBtn: React.CSSProperties = {
  padding: '7px 16px', borderRadius: 8, border: '1px solid var(--border-faint)',
  background: 'var(--surface-2)', color: 'var(--text)', fontSize: 13, cursor: 'pointer',
}
const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 12, lineHeight: 1.5 }
const okBox: React.CSSProperties = {
  background: 'var(--success-bg)', color: 'var(--success)', fontSize: 13,
  padding: '8px 10px', borderRadius: 8,
}
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8,
}
const xBtn: React.CSSProperties = { border: 'none', background: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--text-muted)' }
