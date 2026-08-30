import { useCallback, useEffect, useState } from 'react'
import { fmtNumber as fmt } from '../lib/format'
import { getPortalHome, type PortalHome } from '../api'
import KpiDelta from './KpiDelta'

/**
 * Главная обычного пользователя.
 *
 * Пять ответов по порядку важности: что мне сообщили (объявления), какие у
 * центра сейчас главные цифры (ключевые показатели — тот же curated-набор,
 * что администратор выносит на свою «Главную»: значения org-wide, а не по
 * доступным человеку дашбордам, — это осознанно опубликованная сводка, а не
 * обход прав), какие отчёты доступны и от какого объекта, что нового в
 * данных, и справка о самой системе. Часы и дата — сверху.
 */
export default function UserHomePage(
  { fullName, onOpenDashboard, onGoto }:
  { fullName: string; onOpenDashboard?: (id: string) => void; onGoto?: (section: string) => void },
) {
  const [data, setData] = useState<PortalHome | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [now, setNow] = useState(new Date())

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const load = useCallback(() => {
    getPortalHome().then(setData).catch((e) => setErr((e as Error).message))
  }, [])
  useEffect(() => { load() }, [load])

  const hour = now.getHours()
  const greeting = hour < 5 ? 'Доброй ночи' : hour < 12 ? 'Доброе утро' : hour < 18 ? 'Добрый день' : 'Добрый вечер'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Приветствие и часы */}
      <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 240px', minWidth: 0 }}>
          <div style={{ fontSize: 21, fontWeight: 700 }}>{greeting}, {fullName || 'коллега'}!</div>
          <div style={{ ...muted, marginTop: 4 }}>
            Аналитический портал ГБУ «МФЦ ДНР» — отчёты по показателям работы центра.
          </div>
        </div>
        <div style={{
          textAlign: 'center', padding: '10px 20px', borderRadius: 12,
          background: 'var(--surface-2)', border: '1px solid var(--border)', minWidth: 168,
        }}>
          <div style={{ fontSize: 30, fontWeight: 700, fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
            {now.toLocaleTimeString('ru-RU')}
          </div>
          <div style={{ ...muted, fontSize: 12.5, marginTop: 2 }}>
            {now.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
          </div>
        </div>
      </div>

      {err && <div style={errBox}>{err}</div>}

      {/* Ключевые показатели: то же самое, что видит руководство, первым
          экраном — набор задаёт администратор, здесь только чтение. */}
      {(data?.key_kpis?.length ?? 0) > 0 && (
        <div style={card}>
          <div style={h2}>Ключевые показатели</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginTop: 8 }}>
            {data!.key_kpis.map((k) => (
              <div key={k.code} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 10 }}>
                <div style={{ fontSize: 12.5, color: 'var(--text-2)' }}>{k.name}</div>
                {k.value != null
                  ? (
                    <div style={{ marginTop: 4 }}>
                      <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--accent)' }}>
                        {fmt(k.value)}{k.unit && <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 4 }}>{k.unit}</span>}
                      </div>
                      <KpiDelta kpi={k} size={12} />
                    </div>
                  )
                  : <div style={{ fontSize: 12, color: 'var(--danger)', marginTop: 6 }}>{k.error || 'нет значения'}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Объявления администратора. Важные — акцентом: сообщение о работах на
          сервере не должно теряться среди обычных. */}
      {(data?.announcements || []).map((a) => (
        <div key={a.id} style={{
          ...card,
          borderLeft: `4px solid ${a.important ? 'var(--danger)' : 'var(--accent)'}`,
          background: a.important ? 'var(--danger-bg)' : 'var(--accent-weak-bg)',
        }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 15, fontWeight: 700 }}>
              {a.important ? '❗ ' : '📢 '}{a.title}
            </span>
            <span style={{ ...muted, fontSize: 12 }}>
              от {new Date(a.starts_at).toLocaleDateString('ru-RU')}
              {a.ends_at && ` · показывается до ${new Date(a.ends_at).toLocaleDateString('ru-RU')}`}
            </span>
          </div>
          <div style={{ fontSize: 14, marginTop: 6, whiteSpace: 'pre-wrap', lineHeight: 1.45 }}>{a.body}</div>
        </div>
      ))}

      {data?.stale_password && (
        <div style={{ ...card, borderLeft: '4px solid var(--warn)', background: 'var(--warn-bg)' }}>
          <b>Пароль не менялся более полугода.</b> Смените его в разделе «Кабинет» —
          это занимает полминуты и защищает данные, к которым у вас есть доступ.
        </div>
      )}

      {/* Мои отчёты — по объектам: у одного отдела их бывает десяток, и
          вперемешку с чужими список не читается. */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <div style={h2}>Мои отчёты</div>
          <span style={{ ...muted, fontSize: 13 }}>
            доступно: <b>{data?.dashboards_total ?? '—'}</b>
            {(data?.objects.length ?? 0) > 1 && ` · объектов: ${data?.objects.length}`}
          </span>
          <button style={linkBtn} onClick={() => onGoto?.('dashboards')}>все отчёты →</button>
        </div>
        {data && data.objects.length === 0 && (
          <div style={{ ...muted, marginTop: 8 }}>
            Пока вам не открыт ни один отчёт. Нажмите «Обращение администратору» и напишите,
            какие показатели вам нужны, — доступ выдаёт администратор.
          </div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12, marginTop: 10 }}>
          {(data?.objects || []).map((g) => (
            <div key={g.object_name} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 10 }}>
              <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--accent)', marginBottom: 6 }}>
                🏢 {g.object_name}
                <span style={{ ...muted, fontWeight: 400 }}> · {g.dashboards.length}</span>
              </div>
              {g.dashboards.slice(0, 6).map((d) => (
                <button key={d.id} style={rowBtn} onClick={() => onOpenDashboard?.(d.id)}>
                  <span style={{ fontSize: 13.5 }}>{d.name}</span>
                  <span style={{ ...muted, fontSize: 11.5 }}>
                    {d.folder_name ? `📁 ${d.folder_name}` : ''}
                    {d.updated_at && ` · изменён ${new Date(d.updated_at).toLocaleDateString('ru-RU')}`}
                  </span>
                </button>
              ))}
              {g.dashboards.length > 6 && (
                <div style={{ ...muted, fontSize: 12, marginTop: 4 }}>и ещё {g.dashboards.length - 6}…</div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Что нового в данных: ради этого человек и заходит повторно. */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
        <div style={card}>
          <div style={h2}>Что нового в данных</div>
          <div style={{ ...muted, fontSize: 12.5, marginBottom: 8 }}>Поступления за последнюю неделю.</div>
          {(data?.fresh_data || []).length === 0 ? (
            <div style={muted}>За неделю новых отчётов не поступало.</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <tbody>
                {(data?.fresh_data || []).map((f, i) => (
                  <tr key={i} style={{ borderTop: i ? '1px solid var(--border-faint)' : 'none' }}>
                    <td style={{ padding: '6px 0' }}>
                      <div style={{ fontWeight: 600 }}>{f.name}</div>
                      <div style={{ ...muted, fontSize: 12 }}>
                        {f.object_name || '—'}
                        {f.period && ` · отчёт за ${new Date(f.period).toLocaleDateString('ru-RU')}`}
                      </div>
                    </td>
                    <td style={{ ...muted, fontSize: 12, textAlign: 'right', whiteSpace: 'nowrap' }}>
                      {new Date(f.created_at).toLocaleDateString('ru-RU')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div style={card}>
          <div style={h2}>Инструкции</div>
          <div style={{ ...muted, fontSize: 12.5, marginBottom: 8 }}>
            Как пользоваться системой: короткие статьи и готовые руководства.
          </div>
          <div style={{ fontSize: 14 }}>
            Всего материалов: <b>{data?.instructions.total ?? 0}</b>
            {(data?.instructions.unread ?? 0) > 0 && (
              <span style={{ color: 'var(--accent)', fontWeight: 600 }}> · новых для вас: {data?.instructions.unread}</span>
            )}
          </div>
          <button style={{ ...btn, marginTop: 10 }} onClick={() => onGoto?.('instructions')}>Открыть инструкции</button>
          <button style={{ ...btnGhost, marginTop: 8 }} onClick={() => onGoto?.('appeals')}>
            Написать администратору
          </button>
        </div>
      </div>

      {/* Справка о системе с иллюстрациями: человек должен понимать, что перед
          ним и на что он может рассчитывать. */}
      <div style={card}>
        <div style={h2}>О системе</div>
        <div style={{ ...muted, fontSize: 13, marginTop: 4, lineHeight: 1.5 }}>
          «Дашборд» собирает показатели работы МФЦ из отчётных форм и показывает их наглядно:
          цифры, динамика, выполнение планов. Данные поступают из загруженных отчётов, проходят
          проверку и попадают на дашборды — вы видите то же самое, что руководство.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: 12, marginTop: 12 }}>
          {ABOUT.map((a) => (
            <div key={a.title} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
              <div style={{ marginBottom: 8 }}>{a.art}</div>
              <div style={{ fontSize: 13.5, fontWeight: 700 }}>{a.title}</div>
              <div style={{ ...muted, fontSize: 12.5, marginTop: 4, lineHeight: 1.45 }}>{a.text}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* Иллюстрации рисуем вектором на токенах темы: система разворачивается в
   закрытом контуре, внешних картинок нет, а растр пришлось бы готовить под
   каждую из трёх тем. */
const A = 'var(--accent)'
const A2 = 'var(--chart-2)'
const G = 'var(--border-strong)'

const ABOUT = [
  {
    title: 'Отчёты и показатели',
    text: 'Ключевые цифры, динамика по неделям и выполнение планов — на одном экране.',
    art: (
      <svg viewBox="0 0 120 48" style={{ width: '100%', height: 48 }}>
        <rect x="4" y="26" width="14" height="18" rx="2" fill={A} />
        <rect x="24" y="16" width="14" height="28" rx="2" fill={A2} />
        <rect x="44" y="32" width="14" height="12" rx="2" fill={A} opacity="0.55" />
        <rect x="64" y="8" width="14" height="36" rx="2" fill={A2} opacity="0.75" />
        <path d="M6 20 L31 10 L51 24 L71 4 L114 12" fill="none" stroke={A} strokeWidth="2" />
      </svg>
    ),
  },
  {
    title: 'Откуда цифра',
    text: 'У каждого показателя видно формулу, источник и первичные строки — «⋯ действия» на карточке.',
    art: (
      <svg viewBox="0 0 120 48" style={{ width: '100%', height: 48 }}>
        <rect x="6" y="6" width="46" height="36" rx="4" fill="none" stroke={G} strokeWidth="2" />
        <path d="M12 16h34M12 24h34M12 32h22" stroke={G} strokeWidth="2" strokeLinecap="round" />
        <circle cx="82" cy="22" r="13" fill="none" stroke={A} strokeWidth="2.5" />
        <path d="M92 32 L108 42" stroke={A} strokeWidth="3" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    title: 'Доступ по назначению',
    text: 'Вы видите только те отчёты, которые открыл администратор. Нужен ещё один — напишите ему.',
    art: (
      <svg viewBox="0 0 120 48" style={{ width: '100%', height: 48 }}>
        <rect x="30" y="20" width="34" height="24" rx="4" fill={A} opacity="0.85" />
        <path d="M38 20v-6a9 9 0 0 1 18 0v6" fill="none" stroke={G} strokeWidth="3" />
        <circle cx="47" cy="32" r="3.5" fill="var(--surface)" />
        <path d="M76 14h34M76 24h28M76 34h34" stroke={A2} strokeWidth="2.5" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    title: 'Выгрузки и печать',
    text: 'Любой отчёт можно сохранить в Excel, PDF или картинкой — для доклада и печати.',
    art: (
      <svg viewBox="0 0 120 48" style={{ width: '100%', height: 48 }}>
        <rect x="10" y="6" width="34" height="36" rx="4" fill="none" stroke={G} strokeWidth="2" />
        <path d="M18 16h18M18 24h18M18 32h10" stroke={G} strokeWidth="2" strokeLinecap="round" />
        <path d="M70 10v20" stroke={A} strokeWidth="3" strokeLinecap="round" />
        <path d="M62 24l8 8 8-8" fill="none" stroke={A} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="56" y="38" width="28" height="4" rx="2" fill={A2} />
      </svg>
    ),
  },
]

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: 16,
}
const h2: React.CSSProperties = { fontSize: 15.5, fontWeight: 700 }
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 13 }
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', padding: 10, borderRadius: 10, fontSize: 13,
}
const btn: React.CSSProperties = {
  width: '100%', padding: '8px 12px', borderRadius: 9, border: 'none',
  background: 'var(--accent)', color: '#fff', fontSize: 13.5, fontWeight: 600, cursor: 'pointer',
}
const btnGhost: React.CSSProperties = {
  width: '100%', padding: '8px 12px', borderRadius: 9,
  border: '1px solid var(--border-strong)', background: 'var(--surface)',
  color: 'var(--text)', fontSize: 13.5, cursor: 'pointer',
}
const linkBtn: React.CSSProperties = {
  marginLeft: 'auto', border: 'none', background: 'none', color: 'var(--accent)',
  fontSize: 13, cursor: 'pointer',
}
const rowBtn: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2,
  width: '100%', textAlign: 'left', padding: '6px 8px', marginBottom: 4,
  border: '1px solid var(--border-faint)', borderRadius: 8,
  background: 'var(--surface-2)', cursor: 'pointer',
}
