import { useEffect, useState } from 'react'
import {
  addAppealMessage, closeAppeal, createAppeal, getAppeal, listAppeals, listMyAppeals,
  type AppealDetail, type AppealSummary,
} from '../api'
import UserAccessPanel from './users/UserAccessPanel'

// Переиспользуемая панель обращений: 'mine' — личный кабинет (создание + свои
// заявки), 'all' — раздел «Обращения» для staff (фильтр по статусу + ответ +
// закрытие). Логика прав — на бэкенде (appeals/service.py), здесь только UI.

function fmtDt(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

const STATUS_LABEL: Record<string, { t: string; bg: string; c: string }> = {
  open: { t: 'ожидает ответа', bg: 'var(--warn-bg)', c: 'var(--warn)' },
  answered: { t: 'есть ответ', bg: 'var(--success-bg)', c: 'var(--success)' },
  closed: { t: 'закрыто', bg: 'var(--surface-3)', c: 'var(--text-faint)' },
}

// Ожидание печатаем в тех единицах, в которых о нём думают: минуты в первый час,
// часы в первые сутки, дальше дни. «53,7 ч» требует считать в уме.
function fmtWait(hours: number): string {
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} мин`
  if (hours < 24) return `${Math.round(hours)} ч`
  const d = Math.floor(hours / 24)
  return `${d} дн`
}

function waitStyle(hours: number, limit: number): React.CSSProperties {
  const over = hours > limit
  return {
    fontSize: 11, padding: '2px 8px', borderRadius: 10, whiteSpace: 'nowrap',
    background: over ? 'var(--danger-bg)' : 'var(--surface-3)',
    color: over ? 'var(--danger)' : 'var(--text-2)',
    fontWeight: over ? 600 : 400,
  }
}

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_LABEL[status] || STATUS_LABEL.open
  return <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: s.bg, color: s.c, whiteSpace: 'nowrap' }}>{s.t}</span>
}

export default function AppealsPanel(
  { scope, initialAppealId, onOpenDashboard }: {
    scope: 'mine' | 'all'
    initialAppealId?: string | null
    /** Открыть отчёт, на который пожаловались кнопкой с виджета (п. 15).
     *  Без него разбор жалобы начинается с поиска дашборда по названию. */
    onOpenDashboard?: (dashboardId: string, pageId?: string | null) => void
  },
) {
  const isStaff = scope === 'all'
  const [items, setItems] = useState<AppealSummary[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)
  const [detail, setDetail] = useState<AppealDetail | null>(null)
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [reply, setReply] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Срок ответа, заявленный организацией («Настройки»). Приходит со списком,
  // чтобы правило было одно и не расходилось с сервером.
  const [respHours, setRespHours] = useState(24)
  // Чья карточка доступа открыта поверх переписки (запрос доступа, п. 15).
  const [accessFor, setAccessFor] = useState<string | null>(null)

  const load = () => {
    if (isStaff) {
      listAppeals(statusFilter || undefined)
        .then((r) => { setItems(r.items); if (r.response_hours) setRespHours(r.response_hours) })
        .catch((e) => setErr((e as Error).message))
    } else {
      listMyAppeals().then((r) => setItems(r.items)).catch((e) => setErr((e as Error).message))
    }
  }
  useEffect(() => { load() }, [statusFilter]) // eslint-disable-line react-hooks/exhaustive-deps
  // Переход из уведомления: открываем сразу нужную переписку, а не список.
  useEffect(() => {
    if (initialAppealId) openThread(initialAppealId)
  }, [initialAppealId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function openThread(id: string) {
    setErr(null)
    try {
      setDetail(await getAppeal(id))
      setOpenId(id)
    } catch (e) {
      // Обращение могли удалить, а уведомление о нём осталось: объясняем это
      // словами, иначе сухое «не найдено» читается как поломка перехода.
      const msg = (e as Error).message
      setErr(/не найден/i.test(msg) ? 'Обращение не найдено — возможно, оно уже удалено.' : msg)
    }
  }
  function back() { setOpenId(null); setDetail(null); setReply(''); load() }

  async function submitNew() {
    if (!body.trim()) return
    setBusy(true); setErr(null)
    try { await createAppeal(subject, body); setSubject(''); setBody(''); load() }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function submitReply() {
    if (!openId || !reply.trim()) return
    setBusy(true); setErr(null)
    try { await addAppealMessage(openId, reply); setReply(''); setDetail(await getAppeal(openId)) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function doClose() {
    if (!openId) return
    setBusy(true); setErr(null)
    try { await closeAppeal(openId); setDetail(await getAppeal(openId)); load() }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  if (openId && detail) {
    return (
      <div>
        <button onClick={back} style={crumb}>← К списку обращений</button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '10px 0' }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{detail.subject || 'Обращение'}</div>
          <StatusBadge status={detail.status} />
          {isStaff && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>от {detail.author}</span>}
          {isStaff && detail.status !== 'closed' && (
            <button style={{ ...btnGhost, marginLeft: 'auto' }} disabled={busy} onClick={doClose}>Закрыть обращение</button>
          )}
        </div>
        {/* Автору: заметили ли жалобу. Администратору: сколько она ждёт.
            Вопросы разные, поэтому и строки разные. */}
        {!isStaff && (
          <div style={{ fontSize: 12, color: detail.first_seen_at ? 'var(--success)' : 'var(--text-muted)', marginBottom: 10 }}>
            {detail.first_seen_at
              ? `👁 Просмотрено ${fmtDt(detail.first_seen_at)}${detail.first_seen_by ? ` · ${detail.first_seen_by}` : ''}`
              : '⏳ Обращение отправлено, администратор его ещё не открывал. Ответ придёт уведомлением.'}
          </div>
        )}
        {isStaff && detail.status === 'open' && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
            ⏱ Ждёт ответа с {fmtDt(detail.created_at)}
            {detail.first_seen_at ? ` · впервые открыто ${fmtDt(detail.first_seen_at)}${detail.first_seen_by ? ` (${detail.first_seen_by})` : ''}` : ''}
          </div>
        )}
        {/* Жалоба пришла с конкретного виджета: здесь и написано, откуда, и
            отсюда же можно туда перейти. Иначе разбор начинается с поиска
            отчёта по названию среди десятков. */}
        {detail.context?.dashboard_id && (
          <div style={ctxBox}>
            <span style={{ fontSize: 13 }}>
              📊 «{detail.context.dashboard_name}»
              {detail.context.page_title ? ` · страница «${detail.context.page_title}»` : ''}
              {detail.context.widget_name ? ` · виджет «${detail.context.widget_name}»` : ''}
              {/* Ответственный за показатель (п. 11): жалоба адресна по своей
                  природе, и первым делом сотрудник ищет, кого спросить. */}
              {detail.context.owner_name ? ` · 👤 отвечает ${detail.context.owner_name}` : ''}
            </span>
            {onOpenDashboard && (
              <button
                style={{ ...btnGhost, marginLeft: 'auto' }}
                onClick={() => onOpenDashboard(detail.context!.dashboard_id!, detail.context!.page_id)}
              >
                Открыть отчёт →
              </button>
            )}
          </div>
        )}
        {/* Запрос доступа (п. 15): администратору некуда «переходить» — отчёт
            человек назвал словами. Зато отсюда открывается его карточка
            доступа, и выдача сводится к одной галочке вместо обхода дашбордов. */}
        {isStaff && detail.context?.kind === 'access_request' && (
          <div style={ctxBox}>
            <span style={{ fontSize: 13 }}>🔑 Запрос доступа к отчёту от «{detail.author}»</span>
            <button style={{ ...btnGhost, marginLeft: 'auto' }} onClick={() => setAccessFor(detail.author_id)}>
              Выдать доступ →
            </button>
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 12 }}>
          {detail.messages.map((m) => (
            <div key={m.id} style={{
              border: '1px solid var(--border-faint)', borderRadius: 10, padding: '8px 12px',
              background: m.is_staff ? 'var(--accent-weak-bg)' : 'var(--surface)',
            }}>
              <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: m.is_staff ? 'var(--accent)' : 'var(--text)' }}>
                  {m.is_staff ? '🛠 ' : ''}{m.author}
                </span>
                <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>{fmtDt(m.created_at)}</span>
              </div>
              <div style={{ fontSize: 14, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{m.body}</div>
            </div>
          ))}
        </div>
        {detail.status !== 'closed' || isStaff ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <textarea value={reply} onChange={(e) => setReply(e.target.value)} rows={2} placeholder="Ваш ответ…"
              style={{ flex: 1, resize: 'vertical', padding: '8px 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14, fontFamily: 'inherit' }} />
            <button style={btn} disabled={busy || !reply.trim()} onClick={submitReply}>Отправить</button>
          </div>
        ) : (
          <div style={muted}>Обращение закрыто. Новое сообщение откроет его снова.</div>
        )}
        {err && <div style={errBox}>{err}</div>}
        {/* Карточка доступа сотрудника поверх переписки: та же панель, что в
            разделе «Пользователи», — второго экрана выдачи прав не заводим. */}
        {accessFor && (
          <div style={accessOverlay} onClick={() => setAccessFor(null)}>
            <div style={accessDialog} onClick={(e) => e.stopPropagation()}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
                <div style={{ fontSize: 15, fontWeight: 600 }}>Доступ к отчётам · {detail.author}</div>
                <button style={{ ...btnGhost, marginLeft: 'auto' }} onClick={() => setAccessFor(null)}>Закрыть</button>
              </div>
              <UserAccessPanel userId={accessFor} />
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div>
      {!isStaff && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 12, padding: 14, marginBottom: 16 }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Новое обращение</div>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Тема (необязательно)"
            style={{ ...input, width: '100%', marginBottom: 8, boxSizing: 'border-box' }} />
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} placeholder="Опишите вопрос или проблему…"
            style={{ width: '100%', resize: 'vertical', padding: '8px 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14, fontFamily: 'inherit', marginBottom: 8, boxSizing: 'border-box' }} />
          <button style={btn} disabled={busy || !body.trim()} onClick={submitNew}>Отправить администратору</button>
        </div>
      )}
      {isStaff && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          {['', 'open', 'answered', 'closed'].map((s) => (
            <button key={s || 'all'} onClick={() => setStatusFilter(s)} style={statusFilter === s ? tabActive : tab}>
              {s === '' ? 'Все' : STATUS_LABEL[s].t}
            </button>
          ))}
        </div>
      )}
      {err && <div style={errBox}>{err}</div>}
      {items.length === 0 ? <div style={muted}>{isStaff ? 'Обращений нет.' : 'У вас пока нет обращений.'}</div> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {items.map((a) => (
            <div key={a.id} onClick={() => openThread(a.id)}
              style={{ border: '1px solid var(--border)', borderRadius: 10, padding: '10px 14px', cursor: 'pointer' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 600 }}>{a.subject || 'Без темы'}</span>
                <StatusBadge status={a.status} />
                {isStaff && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{a.author}</span>}
                {/* Сколько ждёт ответа. Красным — когда срок, заявленный
                    организацией, уже вышел: очередь без этого выглядит одинаково
                    и на первом часу, и на третьи сутки. */}
                {isStaff && a.waiting_hours != null && (
                  <span style={waitStyle(a.waiting_hours, respHours)}
                    title={`Ждёт ответа с ${fmtDt(a.created_at)}. Заявленный срок — ${respHours} ч (меняется в «Настройках»)`}>
                    ⏱ {fmtWait(a.waiting_hours)}{a.waiting_hours > respHours ? ' · срок вышел' : ''}
                  </span>
                )}
                {/* Автору важнее другое: заметили ли жалобу вообще. До первого
                    ответа обращение выглядит так же, как в момент отправки. */}
                {!isStaff && a.status === 'open' && (
                  <span style={{ fontSize: 11, color: a.first_seen_at ? 'var(--success)' : 'var(--text-faint)' }}
                    title={a.first_seen_at ? `Администратор открыл обращение ${fmtDt(a.first_seen_at)}` : 'Администратор ещё не открывал обращение'}>
                    {a.first_seen_at ? '👁 просмотрено' : '⏳ ждёт просмотра'}
                  </span>
                )}
                <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-faint)', whiteSpace: 'nowrap' }}>{fmtDt(a.updated_at)}</span>
              </div>
              {a.last_message && (
                <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {a.last_is_staff ? '🛠 ' : ''}{a.last_message}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const crumb: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 14, padding: 0 }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14 }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { height: 32, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text-2)', fontSize: 13, cursor: 'pointer' }
const accessOverlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex',
  alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 16,
}
const accessDialog: React.CSSProperties = {
  background: 'var(--surface)', borderRadius: 14, padding: 18, width: 860, maxWidth: '95vw',
  maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
}
const ctxBox: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 12,
  padding: '8px 12px', borderRadius: 10, background: 'var(--surface-2)',
  border: '1px solid var(--border-faint)',
}
const tab: React.CSSProperties = { height: 32, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', cursor: 'pointer', fontSize: 13 }
const tabActive: React.CSSProperties = { ...tab, background: 'var(--accent-weak-bg)', border: '1px solid var(--accent)', color: 'var(--accent)' }
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 14, padding: '8px 0' }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginTop: 10 }
