import { useEffect, useState } from 'react'
import {
  getModerationQueue, getReasonCodes, moderateDashboard,
  type ModerationQueueItem, type ReasonCode,
} from '../api'

// Раздел «Модерация» (модератор/старший модератор/админ): очередь дашбордов,
// отправленных на проверку. Одна ступень: одобрение = публикация. Конфликт
// интересов — собственный дашборд одобрять нельзя (кнопка заблокирована).

const CHECK_BLOCKS: { code: string; label: string }[] = [
  { code: 'structure', label: 'Структура' },
  { code: 'data', label: 'Данные' },
  { code: 'metrics', label: 'Метрики' },
  { code: 'filters', label: 'Фильтры' },
  { code: 'access', label: 'Доступ' },
  { code: 'visual', label: 'Визуализация' },
]
const CHECK_OPTIONS: { code: string; label: string; color: string }[] = [
  { code: 'idle', label: '—', color: 'var(--text-faint)' },
  { code: 'passed', label: 'ОК', color: 'var(--success)' },
  { code: 'warning', label: 'Замечание', color: 'var(--warn)' },
  { code: 'failed', label: 'Не пройдено', color: 'var(--danger)' },
  { code: 'skipped', label: 'Пропустить', color: 'var(--text-muted)' },
]

function fmtDt(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

export default function ModerationPage({ me, onOpenDashboard }: {
  me: { id: string; roles: string[] }; onOpenDashboard?: (id: string) => void
}) {
  const [queue, setQueue] = useState<ModerationQueueItem[] | null>(null)
  const [reasons, setReasons] = useState<ReasonCode[]>([])
  const [error, setError] = useState<string | null>(null)
  const [review, setReview] = useState<ModerationQueueItem | null>(null)

  const canModerate = me.roles.some((r) => ['admin', 'moderator', 'senior_moderator'].includes(r))
  const reload = () => getModerationQueue().then(setQueue).catch((e) => setError((e as Error).message))
  useEffect(() => {
    if (!canModerate) return
    reload()
    getReasonCodes().then(setReasons).catch((e) => setError((e as Error).message))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (!canModerate) return <div style={{ color: 'var(--danger)' }}>Раздел «Модерация» доступен модератору или администратору.</div>

  return (
    <div>
      <h2 style={{ fontSize: 20, margin: '0 0 4px' }}>Модерация</h2>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
        Дашборды, отправленные на проверку. Одобрение публикует дашборд. Собственные одобрять нельзя (конфликт интересов).
      </div>
      {error && <div style={errBox}>{error}</div>}

      {!queue ? <span style={muted}>Загрузка…</span> : queue.length === 0 ? (
        <div style={{ ...muted, padding: '20px 0' }}>Очередь пуста — на проверке ничего нет.</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
            <thead><tr>{['Дашборд', 'Отправил', 'Когда', ''].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
            <tbody>
              {queue.map((q) => (
                <tr key={q.dashboard_id}>
                  <td style={{ ...td, fontWeight: 600 }}>
                    {q.name}
                    {onOpenDashboard && <button style={linkBtn} onClick={() => onOpenDashboard(q.dashboard_id)} title="Открыть дашборд">↗</button>}
                  </td>
                  <td style={td}>{q.requester}</td>
                  <td style={{ ...td, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{fmtDt(q.requested_at)}</td>
                  <td style={{ ...td, whiteSpace: 'nowrap' }}>
                    {q.can_approve === false
                      ? <span style={{ color: 'var(--warn)', fontSize: 12 }} title="Вы автор/инициатор — нужен другой модератор">свой · нельзя</span>
                      : <button style={btn} onClick={() => setReview(q)}
                          title={q.own ? 'Это ваш дашборд — как суперадминистратор вы можете одобрить его сами; самоодобрение будет отмечено в журнале' : undefined}>
                          Проверить{q.own ? ' (свой)' : ''}
                        </button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {review && (
        <ReviewModal item={review} reasons={reasons}
          onClose={() => setReview(null)}
          onDone={() => { setReview(null); reload() }}
          onError={(m) => setError(m)} />
      )}
    </div>
  )
}

function ReviewModal({ item, reasons, onClose, onDone, onError }: {
  item: ModerationQueueItem; reasons: ReasonCode[]
  onClose: () => void; onDone: () => void; onError: (m: string) => void
}) {
  const [checks, setChecks] = useState<Record<string, string>>(
    Object.fromEntries(CHECK_BLOCKS.map((b) => [b.code, 'idle'])))
  const [reason, setReason] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)

  async function act(decision: 'approve' | 'return') {
    if (decision === 'return' && !reason) { onError('Для возврата выберите причину'); return }
    if (decision === 'return' && reason === 'OTHER' && !comment.trim()) { onError('Для причины «Иная» укажите комментарий'); return }
    setBusy(true)
    try {
      await moderateDashboard(item.dashboard_id, {
        decision, checklist: checks,
        reason_code: decision === 'return' ? reason : undefined,
        comment: comment.trim() || undefined,
      })
      onDone()
    } catch (e) { onError((e as Error).message); setBusy(false) }
  }

  const hasFail = Object.values(checks).some((s) => s === 'failed')

  return (
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Проверка: {item.name}</div>
          <button style={{ ...xBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>Отправил: {item.requester} · {fmtDt(item.requested_at)}</div>

        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Чек-лист проверки</div>
        <div style={{ display: 'grid', gap: 8, marginBottom: 16 }}>
          {CHECK_BLOCKS.map((b) => (
            <div key={b.code} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ width: 110, fontSize: 13 }}>{b.label}</span>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {CHECK_OPTIONS.map((o) => (
                  <button key={o.code} onClick={() => setChecks((s) => ({ ...s, [b.code]: o.code }))}
                    style={{
                      fontSize: 12, padding: '2px 8px', borderRadius: 8, cursor: 'pointer',
                      border: `1px solid ${checks[b.code] === o.code ? o.color : 'var(--border-strong)'}`,
                      background: checks[b.code] === o.code ? o.color : 'var(--on-accent)',
                      color: checks[b.code] === o.code ? 'var(--on-accent)' : 'var(--text-2)',
                    }}>{o.label}</button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Причина возврата (если возвращаете)</div>
        <select style={{ ...input, width: '100%', marginBottom: 8 }} value={reason} onChange={(e) => setReason(e.target.value)}>
          <option value="">— не выбрана —</option>
          {reasons.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
        </select>
        <textarea style={{ ...input, width: '100%', height: 56, padding: 8, resize: 'vertical' }}
          placeholder="Комментарий (обязателен для причины «Иная»)" value={comment} onChange={(e) => setComment(e.target.value)} />

        {hasFail && <div style={{ fontSize: 12, color: 'var(--warn)', marginTop: 8 }}>⚠ Есть непройденные блоки — обычно такой дашборд возвращают на доработку.</div>}

        <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
          <button style={{ ...btnGhost, marginLeft: 'auto' }} disabled={busy} onClick={() => act('return')}>↩ Вернуть на доработку</button>
          <button style={btn} disabled={busy} onClick={() => act('approve')}>✓ Одобрить и опубликовать</button>
        </div>
      </div>
    </div>
  )
}

const input: React.CSSProperties = { minHeight: 34, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13, background: 'var(--surface)', fontFamily: 'inherit' }
const btn: React.CSSProperties = { height: 34, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { height: 34, padding: '0 14px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', color: 'var(--danger)', fontSize: 13, cursor: 'pointer' }
const linkBtn: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 13, padding: '0 0 0 6px' }
const xBtn: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--danger)', cursor: 'pointer', padding: 0, fontSize: 15 }
const th: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '6px 10px', background: 'var(--surface-2)', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600 }
const td: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '6px 10px' }
const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 13 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60, padding: 20 }
const dialog: React.CSSProperties = { background: 'var(--surface)', borderRadius: 14, padding: 22, width: 560, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }
