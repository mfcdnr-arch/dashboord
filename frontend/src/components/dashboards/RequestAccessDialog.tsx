import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { requestDashboardAccess } from '../../api'

// «Мне нужен отчёт, которого я не вижу» (п. 15, последняя из трёх идей).
//
// **Списка недоступных отчётов здесь нет — и не будет.** Зритель видит только
// то, что ему открыто, и это не техническое ограничение, а суть: даже одни
// названия отчётов говорят, какие показатели за кем закреплены. Серая строка
// «Финансы отдела Х» с кнопкой «запросить» раскрывала бы ровно то, что скрывает
// разграничение доступа.
//
// Поэтому человек называет отчёт сам — так, как ему его назвали в письме или на
// совещании. Ценность не в списке, а в том, что запрос уходит одним нажатием
// оттуда, где человек его хватился, и приходит администратору с именем автора:
// тому остаётся открыть карточку доступа сотрудника и отметить галочку.
export default function RequestAccessDialog(
  { onClose, onOpenAppeals }: { onClose: () => void; onOpenAppeals?: () => void },
) {
  const [wanted, setWanted] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const send = async () => {
    setBusy(true); setErr(null)
    try {
      await requestDashboardAccess(wanted)
      setDone(true)
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
          <div style={{ fontSize: 16, fontWeight: 600 }}>Нужен отчёт, которого здесь нет</div>
          <button style={{ ...xBtn, marginLeft: 'auto' }} onClick={onClose} title="Закрыть">✕</button>
        </div>

        {done ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={okBox}>✓ Запрос отправлен администратору.</div>
            <div style={muted}>
              Когда доступ выдадут, отчёт появится в этом списке сам. Ответ придёт уведомлением,
              переписка — в разделе «Кабинет».
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
            <div style={muted}>
              В списке показаны только отчёты, открытые лично вам. Если нужного нет — назовите его
              так, как вам его назвали: администратор поймёт, о чём речь, и выдаст доступ.
            </div>
            <textarea
              value={wanted} onChange={(e) => setWanted(e.target.value)} rows={4} maxLength={2000}
              placeholder="Например: еженедельный доклад по внедрению сервиса МАХ — о нём говорили на планёрке"
              style={area}
            />
            {err && <div style={errBox}>{err}</div>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button style={ghostBtn} onClick={onClose} disabled={busy}>Отмена</button>
              <button style={primaryBtn} onClick={send} disabled={busy || !wanted.trim()}>
                {busy ? 'Отправка…' : 'Запросить доступ'}
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
