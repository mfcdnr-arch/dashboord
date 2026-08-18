import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { buildPlanFact, DuplicateError, planFactPreview, type PlanFactPlan } from '../../api'

// Сводный дашборд «План/факт» по ВСЕМ объектам и папкам.
//
// Полоса «план-факт» внутри дашборда объекта остаётся как была — она отвечает
// за одну форму из одной папки. Здесь собирается общая картина выполнения
// планов по организации: то, что открывают, чтобы одним взглядом понять, где
// отставание.
//
// Состав показывается ДО создания тем же кодом, что и собирает: иначе
// обещанное «будет N виджетов» однажды разошлось бы с результатом — тот же
// принцип, что в мастере авто-сборки.
export default function PlanFactDialog(
  { onClose, onBuilt }: { onClose: () => void; onBuilt?: (dashboardId: string) => void },
) {
  const [plan, setPlan] = useState<PlanFactPlan | null>(null)
  const [err, setErr] = useState<string | null>(null)
  // Переспрос про одноимённый дашборд — отдельно от ошибки: это не сбой,
  // а вопрос, и у него есть кнопка ответа.
  const [dup, setDup] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    planFactPreview().then(setPlan).catch((e) => setErr((e as Error).message))
  }, [])

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const build = async (force = false) => {
    setBusy(true); setErr(null); setDup(null)
    try {
      const r = await buildPlanFact({ force })
      onClose()
      onBuilt?.(r.dashboard_id)
    } catch (e) {
      // Дашборд «План/факт» уже есть: чаще всего нужно пересобрать его, а не
      // завести второй такой же — иначе в списке два неразличимых.
      if (e instanceof DuplicateError) setDup((e as Error).message)
      else setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const nothing = plan && plan.widgets === 0

  return createPortal(
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 4 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>🎯 Сводная страница «План/факт»</div>
          <button style={{ ...xBtn, marginLeft: 'auto' }} onClick={onClose} title="Закрыть">✕</button>
        </div>
        <div style={{ ...muted, marginBottom: 14 }}>
          Собирается по всем объектам и папкам. Факт берётся за последний отчёт каждой формы —
          когда придёт новый файл, цифры обновятся сами.
        </div>

        <div style={scale}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Цвет полосы:</span>
          <span style={{ ...band, background: '#fcebeb', color: '#a32d2d' }}>до 50 %</span>
          <span style={{ ...band, background: '#fdf0e3', color: '#b35309' }}>50–70 %</span>
          <span style={{ ...band, background: '#fff4e0', color: '#9a6a00' }}>70–85 %</span>
          <span style={{ ...band, background: '#eaf5f0', color: '#0f6e56' }}>от 85 %</span>
        </div>

        {err && <div style={errBox}>{err}</div>}
        {dup && (
          <div style={{ ...errBox, background: 'var(--accent-weak-bg)', color: 'var(--text)' }}>
            <div style={{ marginBottom: 8 }}>{dup}</div>
            <div style={{ ...muted, fontSize: 12.5, marginBottom: 8 }}>
              Обычно нужно пересобрать существующий «План/факт», а не заводить второй:
              при пересборке права доступа и обсуждение сохраняются.
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button style={ghostBtn} onClick={() => setDup(null)} disabled={busy}>Отмена</button>
              <button style={primaryBtn} onClick={() => build(true)} disabled={busy}>Всё равно создать</button>
            </div>
          </div>
        )}
        {!plan && !err && <div style={muted}>Ищу пары «План + Факт»…</div>}

        {plan && !nothing && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 13, marginBottom: 8 }}>
              Будет собрано <strong>{plan.widgets}</strong>{' '}
              {plural(plan.widgets, 'показатель', 'показателя', 'показателей')}
              {plan.objects.length > 1 ? ` из ${plan.objects.length} объектов` : ''}:
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 280, overflowY: 'auto' }}>
              {plan.objects.map((o) => (
                <div key={o.name}>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>📁 {o.name}</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    {o.indicators.map((n) => (
                      <div key={n} style={row}>{n}</div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {nothing && (
          <div style={{ ...muted, marginTop: 12 }}>
            Пар «План + Факт» не нашлось. Такая пара собирается из двух граф одной формы:
            одна с ролью «План», вторая — «Факт» в основном разрезе (нарастающим итогом).
            Проверьте, что в загруженных формах есть графы плана.
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
          <button style={ghostBtn} onClick={onClose} disabled={busy}>Отмена</button>
          <button style={primaryBtn} onClick={() => build()} disabled={busy || !plan || !!nothing}>
            {busy ? 'Собираю…' : 'Собрать'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function plural(n: number, one: string, few: string, many: string): string {
  const tail = Math.abs(n) % 100
  if (tail >= 11 && tail <= 14) return many
  const last = tail % 10
  if (last === 1) return one
  if (last >= 2 && last <= 4) return few
  return many
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex',
  alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 16,
}
const dialog: React.CSSProperties = {
  background: 'var(--surface)', borderRadius: 14, padding: 20, width: 560, maxWidth: '94vw',
  maxHeight: '86vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
}
const scale: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
  padding: '8px 10px', borderRadius: 10, background: 'var(--surface-2)',
}
const band: React.CSSProperties = { fontSize: 12, padding: '2px 10px', borderRadius: 10, fontWeight: 600 }
const row: React.CSSProperties = {
  fontSize: 13, padding: '5px 10px', borderRadius: 8,
  background: 'var(--surface-2)', border: '1px solid var(--border-faint)',
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
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13,
  padding: '8px 10px', borderRadius: 8, marginTop: 10,
}
const xBtn: React.CSSProperties = { border: 'none', background: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--text-muted)' }
