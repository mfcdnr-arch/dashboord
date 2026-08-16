import { useState } from 'react'
import { getAttendanceDay, type AttendanceDay } from '../../api'

type Day = { day: string; logins: number; failed: number }

/** ISO-дата → ДД.ММ (на оси) и ДД.ММ.ГГГГ (в подсказке и заголовке). */
const short = (iso: string) => iso.slice(8, 10) + '.' + iso.slice(5, 7)
const full = (iso: string) => iso.split('-').reverse().join('.')
const time = (iso: string | null) =>
  (iso ? new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '—')

// Столько подписей помещается под графиком, не слипаясь. При 7 днях подписан
// каждый столбик, при 90 — каждый девятый; иначе даты налезают друг на друга
// (та же беда, что уже чинили у подписей категорий на графиках дашборда).
const MAX_TICKS = 10

// График «Входы по дням» отвечал только «в среду было много»: дат под
// столбиками не было вовсе, а подсказка висела на системном `title` — она
// появляется с задержкой, и её легко не заметить.
//
// Теперь столбик — это кнопка: под ним подпись, при наведении своя подсказка
// с точными числами, по клику раскрывается разбор дня (кто заходил и сколько
// раз). Раньше на этот вопрос отвечал только журнал входов в «Пользователях»,
// куда надо было идти отдельно и фильтровать руками.
export default function AttendanceChart({ days, periodLabel }: { days: Day[]; periodLabel?: string }) {
  const [hover, setHover] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)
  const [detail, setDetail] = useState<AttendanceDay | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const max = Math.max(1, ...days.map((d) => d.logins + d.failed))
  const step = Math.max(1, Math.ceil(days.length / MAX_TICKS))

  async function open(day: string) {
    if (picked === day) { setPicked(null); setDetail(null); return }
    setPicked(day); setDetail(null); setErr(null); setLoading(true)
    try { setDetail(await getAttendanceDay(day)) }
    catch (e) { setErr((e as Error).message) } finally { setLoading(false) }
  }

  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
        Входы по дням{periodLabel ? ` · ${periodLabel}` : ''}
        <span style={{ fontWeight: 400, color: 'var(--text-faint)' }}> — нажмите на столбик, чтобы увидеть, кто заходил</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 96,
        borderBottom: '1px solid var(--border)', position: 'relative' }}>
        {days.length === 0 && <span style={muted}>Нет данных.</span>}
        {days.map((d, i) => {
          const active = picked === d.day || hover === d.day
          return (
            <button key={d.day} type="button"
              aria-label={`${full(d.day)}: входов ${d.logins}, неудачных попыток ${d.failed}`}
              onMouseEnter={() => setHover(d.day)} onMouseLeave={() => setHover(null)}
              onClick={() => open(d.day)}
              style={{
                flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end',
                alignItems: 'center', gap: 2, height: '100%', border: 'none', padding: 0,
                cursor: 'pointer', background: active ? 'var(--surface-3)' : 'transparent',
                borderRadius: '4px 4px 0 0', position: 'relative',
                outline: picked === d.day ? '2px solid var(--accent)' : 'none',
              }}>
              {/* Своя подсказка вместо системной: та появляется с задержкой в
                  секунду, и человек успевает решить, что подсказки нет. */}
              {hover === d.day && (
                // У крайних столбиков подсказку прижимаем к своей стороне,
                // иначе она вылезает за край окна и обрезается — замерено на
                // последнем дне: правый край уходил за границу страницы.
                <div style={{
                  position: 'absolute', bottom: '100%', zIndex: 5, pointerEvents: 'none',
                  ...(i <= 1 ? { left: 0 }
                    : i >= days.length - 2 ? { right: 0 }
                      : { left: '50%', transform: 'translateX(-50%)' }),
                  marginBottom: 6, whiteSpace: 'nowrap',
                  background: 'var(--surface)', border: '1px solid var(--border-strong)',
                  borderRadius: 8, padding: '5px 9px', fontSize: 12, boxShadow: '0 4px 14px rgba(0,0,0,0.14)',
                }}>
                  <b>{full(d.day)}</b> · входов {d.logins}
                  {d.failed > 0 && <span style={{ color: 'var(--danger)' }}> · неудач {d.failed}</span>}
                </div>
              )}
              {d.failed > 0 && (
                <div style={{ width: '70%', height: `${(d.failed / max) * 70}px`,
                  background: '#e6a5a5', borderRadius: '2px 2px 0 0' }} />
              )}
              <div style={{ width: '70%', height: `${(d.logins / max) * 70}px`,
                background: active ? 'var(--accent-strong, var(--accent))' : 'var(--accent)',
                borderRadius: '2px 2px 0 0', opacity: active ? 1 : 0.9 }} />
              {/* Подпись под столбиком: прореживаем, чтобы даты не слипались,
                  но у первого и последнего дня она есть всегда — по ним видно
                  границы периода. */}
              <span style={{ position: 'absolute', top: '100%', marginTop: 4, fontSize: 10,
                color: active ? 'var(--text)' : 'var(--text-faint)', whiteSpace: 'nowrap' }}>
                {(i % step === 0 || i === days.length - 1) ? short(d.day) : ''}
              </span>
            </button>
          )
        })}
      </div>
      <div style={{ height: 18 }} />

      {picked && (
        <div style={{ marginTop: 8, border: '1px solid var(--border-faint)', borderRadius: 10, padding: 12 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>Кто заходил {full(picked)}</div>
            {detail && (
              <span style={muted}>
                входов {detail.totals.logins} · сотрудников {detail.totals.people}
                {detail.totals.failed > 0 && ` · неудачных попыток ${detail.totals.failed}`}
              </span>
            )}
            <button style={{ ...linkBtn, marginLeft: 'auto' }}
              onClick={() => { setPicked(null); setDetail(null) }}>свернуть</button>
          </div>
          {err && <div style={errBox}>{err}</div>}
          {loading && <span style={muted}>Загрузка…</span>}
          {detail && detail.users.length === 0 && !loading && (
            <div style={muted}>В этот день никто не входил.</div>
          )}
          {detail && detail.users.length > 0 && (
            <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
              <thead>
                <tr>
                  <th style={th}>Сотрудник</th><th style={th}>Входов</th>
                  <th style={th}>Неудач</th><th style={th}>Первый</th><th style={th}>Последний</th>
                </tr>
              </thead>
              <tbody>
                {detail.users.map((u) => (
                  <tr key={u.user_id}>
                    <td style={td}>{u.who}{u.who !== u.login && <span style={muted}> · {u.login}</span>}</td>
                    <td style={td}>{u.logins}</td>
                    <td style={{ ...td, color: u.failed > 0 ? 'var(--danger)' : undefined }}>{u.failed || '—'}</td>
                    <td style={td}>{time(u.first_at)}</td>
                    <td style={td}>{time(u.last_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {/* Записи без учётной записи. Это либо логин, которого в системе нет
              (неудачные попытки — признак подбора), либо сотрудник, чью учётку
              потом удалили: история входов её переживает. Различить по данным
              нельзя, поэтому не гадаем о намерении, а показываем числа. */}
          {detail && detail.orphan_logins.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
                Логины без учётной записи
                <span style={{ fontWeight: 400, color: 'var(--text-faint)' }}>
                  {' '}— учётка удалена либо такого логина не было
                </span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {detail.orphan_logins.map((u) => (
                  <span key={u.login} style={u.failed > 0 ? warnChip : chip}
                    title={`Входов: ${u.logins}, неудачных попыток: ${u.failed}, `
                      + `разных адресов: ${u.ips}, последняя запись в ${time(u.last_at)}`}>
                    {u.login} · {u.logins} вх.{u.failed > 0 ? ` · ${u.failed} неуд.` : ''}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 12 }
const linkBtn: React.CSSProperties = {
  border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: 0,
}
const th: React.CSSProperties = {
  border: '1px solid var(--border-faint)', padding: '5px 8px', background: 'var(--surface-2)',
  textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600,
}
const td: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '5px 8px' }
const chip: React.CSSProperties = {
  fontSize: 12, padding: '2px 9px', borderRadius: 10,
  background: 'var(--surface-3)', color: 'var(--text-2)',
}
const warnChip: React.CSSProperties = {
  fontSize: 12, padding: '2px 9px', borderRadius: 10,
  background: 'var(--warn-bg)', color: 'var(--warn)',
}
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8,
}
