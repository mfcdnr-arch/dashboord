import { useEffect, useState } from 'react'
import {
  addHomeKpi, getHome, listMetrics, removeHomeKpi,
  type HomeData, type Metric,
} from '../api'
import { fmtNumber as fmt } from '../lib/format'
import { EmptyKpiArt } from './Art'

const KIND_ICON: Record<string, string> = { dataset: '📄', metric: '📐', dashboard: '📊' }

// ── Иллюстрации блока «О системе» (тема-независимые, через CSS-переменные) ───
const iconBox: React.CSSProperties = { width: 40, height: 40, flexShrink: 0 }
const FEATURE_ICONS: Record<string, React.ReactNode> = {
  builder: (
    <svg style={iconBox} viewBox="0 0 40 40">
      <rect x="4" y="4" width="14" height="14" rx="2" fill="none" stroke="var(--accent)" strokeWidth="2" />
      <rect x="22" y="4" width="14" height="9" rx="2" fill="none" stroke="var(--accent)" strokeWidth="2" />
      <rect x="4" y="22" width="9" height="14" rx="2" fill="none" stroke="var(--accent)" strokeWidth="2" />
      <rect x="17" y="22" width="19" height="14" rx="2" fill="none" stroke="var(--accent)" strokeWidth="2" />
    </svg>
  ),
  transparency: (
    <svg style={iconBox} viewBox="0 0 40 40">
      <rect x="6" y="20" width="5" height="10" fill="var(--chart-2)" />
      <rect x="14" y="14" width="5" height="16" fill="var(--chart-2)" />
      <rect x="22" y="18" width="5" height="12" fill="var(--chart-2)" />
      <circle cx="28" cy="12" r="7" fill="none" stroke="var(--accent)" strokeWidth="2" />
      <line x1="33" y1="17" x2="38" y2="22" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  ),
  access: (
    <svg style={iconBox} viewBox="0 0 40 40">
      <path d="M20 4 L34 9 V19 C34 28 28 34 20 37 C12 34 6 28 6 19 V9 Z" fill="none" stroke="var(--accent)" strokeWidth="2" />
      <path d="M14 20 L18 24 L27 14" fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  suggest: (
    <svg style={iconBox} viewBox="0 0 40 40">
      <path d="M20 6a10 10 0 0 0-6 18c1.2 1 2 2.4 2 4v2h8v-2c0-1.6.8-3 2-4a10 10 0 0 0-6-18Z" fill="none" stroke="var(--accent)" strokeWidth="2" />
      <line x1="16" y1="34" x2="24" y2="34" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  ),
  archive: (
    <svg style={iconBox} viewBox="0 0 40 40">
      <rect x="6" y="10" width="28" height="8" rx="2" fill="none" stroke="var(--accent)" strokeWidth="2" />
      <rect x="8" y="18" width="24" height="16" rx="2" fill="none" stroke="var(--accent)" strokeWidth="2" />
      <line x1="16" y1="24" x2="24" y2="24" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  ),
}
const FEATURES: { icon: string; title: string; text: string }[] = [
  { icon: 'builder', title: 'Конструктор дашбордов', text: 'Готовые шаблоны, drag-and-drop сетка и 21 тип виджетов — от KPI до тепловых карт и сводных таблиц.' },
  { icon: 'transparency', title: 'Прозрачность показателей', text: 'У каждого KPI — формула, источники данных и раскрытие вглубь до первичных строк.' },
  { icon: 'access', title: 'Ролевой доступ и модерация', text: 'Гибкие права на уровне дашборда и строк данных; публикация — только после проверки модератором.' },
  { icon: 'suggest', title: 'Рекомендации и аномалии', text: 'Система подсказывает недостающие виджеты и метрики и отмечает выбросы на графиках динамики.' },
  { icon: 'archive', title: 'Архив, экспорт, витрины', text: 'Помесячные снимки данных, выгрузка в Excel/PDF/PNG и витрины из нескольких дашбордов на одном экране.' },
]

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString('ru-RU')
}

function ago(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

export default function HomePage({ me, canManage, onOpenDashboard }: {
  me: { full_name: string | null; login: string }
  canManage: boolean
  onOpenDashboard: (dashboardId: string, pageId?: string) => void
}) {
  const [data, setData] = useState<HomeData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [now, setNow] = useState(new Date())

  const load = () => getHome().then(setData).catch((e) => setError((e as Error).message))
  useEffect(() => { load(); listMetrics('', 500).then((p) => setMetrics(p.items)).catch(() => {}) }, [])
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t) }, [])

  async function addKpi(code: string) {
    if (!code) return
    try { await addHomeKpi(code); load() } catch (e) { setError((e as Error).message) }
  }
  async function removeKpi(code: string) {
    try { await removeHomeKpi(code); load() } catch (e) { setError((e as Error).message) }
  }

  if (error) return <div style={errBox}>{error}</div>
  if (!data) return <div style={{ color: 'var(--text-faint)' }}>Загрузка…</div>

  const c = data.counters
  const counters = [
    { t: 'Дашборды', v: c.dashboards }, { t: 'Объекты', v: c.objects },
    { t: 'Документы', v: c.documents ?? 0 },
    { t: 'Выпуски данных', v: c.releases ?? 0 },
    { t: 'Метрики', v: c.metrics }, { t: 'Датасеты', v: c.datasets }, { t: 'Пользователи', v: c.users },
  ]

  // Путь настройки: пока система не наполнена, «Главная» состоит из пустых
  // блоков («показатели не выбраны», «страниц нет») и не подсказывает, что
  // делать дальше. Показываем шаги с отметками и ведём к следующему.
  const setup = data.setup
  const steps = setup ? [
    { done: setup.objects, t: 'Создать объект и папку', hint: 'куда складывать отчёты', go: 'objects' },
    { done: setup.documents, t: 'Загрузить документ', hint: 'Excel, CSV, Word или PDF с таблицей', go: 'objects' },
    { done: setup.datasets, t: 'Разметить и выпустить данные', hint: 'указать область данных и показатели', go: 'objects' },
    { done: setup.metrics, t: 'Завести показатель', hint: 'или принять предложение системы', go: 'metrics' },
    { done: setup.dashboards, t: 'Собрать дашборд', hint: 'кнопка «Собрать» строит его по объекту', go: 'dashboards' },
    { done: setup.published, t: 'Опубликовать и выдать доступ', hint: 'после проверки дашборд увидят зрители', go: 'dashboards' },
  ] : []
  const nextStep = steps.find((x) => !x.done)
  const span = data.data_span
  const available = metrics.filter((m) => !data.key_kpis.some((k) => k.code === m.code))

  // группировка каталога по дашбордам
  const byDash: Record<string, { name: string; pages: HomeData['pages'] }> = {}
  for (const p of data.pages) {
    (byDash[p.dashboard_id] ??= { name: p.dashboard_name, pages: [] }).pages.push(p)
  }

  return (
    <div>
      {/* Приветствие + дата/время. Часы отдельной плашкой справа: серой
          строкой рядом с приветствием их не замечали. */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 20, margin: 0 }}>Здравствуйте, {me.full_name || me.login}!</h2>
        <div style={clockBox}>
          <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1, fontVariantNumeric: 'tabular-nums' }}>
            {now.toLocaleTimeString('ru-RU')}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {now.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
          </div>
        </div>
      </div>

      {/* Что уже есть в данных. Идёт ПЕРЕД описанием системы: человек
          открывает главную, чтобы узнать, что нового, а не читать о платформе.
          До появления первого дашборда это к тому же единственное, что
          показывает — система живёт, отчёты загружаются. */}
      {(c.releases ?? 0) > 0 && span && (
        <Section title="Данные в системе">
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 13, marginBottom: 10 }}>
            <span>Загружено документов: <b>{c.documents ?? 0}</b></span>
            <span>Выпусков данных: <b>{c.releases ?? 0}</b></span>
            {span.first_period && span.last_period && (
              <span>Период отчётов: <b>{fmtDate(span.first_period)} — {fmtDate(span.last_period)}</b></span>
            )}
            {span.last_upload && <span>Последняя загрузка: <b>{ago(span.last_upload)}</b></span>}
          </div>
          {/* Что именно поступило: отчёт за какую дату, из какого файла и
              сколько в нём показателей. Общая лента «что нового» отвечает
              «когда», а это — «что пришло и полное ли оно». */}
          {(data.recent_data || []).length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%', tableLayout: 'fixed' }}>
                <thead>
                  <tr>
                    <th style={th}>Отчёт за</th>
                    <th style={th}>Файл</th>
                    <th style={th}>Объект / папка</th>
                    <th style={{ ...th, textAlign: 'right' }}>Показателей</th>
                    <th style={th}>Загружен</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.recent_data || []).map((r) => (
                    <tr key={r.id}>
                      <td style={td}><b>{fmtDate(r.period)}</b></td>
                      {/* Имена госформ длинные; обрезаем по ширине колонки, а
                          полное — в подсказке: иначе таблица уезжает за край. */}
                      <td style={{ ...td, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={r.filename || r.name}>
                        {r.filename || r.name}
                      </td>
                      <td style={td}>
                        {[r.object_name, r.folder_name].filter(Boolean).join(' / ') || '—'}
                      </td>
                      <td style={{ ...td, textAlign: 'right' }}>{r.fields_count}</td>
                      <td style={td}>{ago(r.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {/* О системе */}
      <Section title="О системе">
        <p style={{ margin: '0 0 14px', fontSize: 14, color: 'var(--text-2)', maxWidth: 760, lineHeight: 1.5 }}>
          «Дашборд» — платформа для мониторинга ключевых показателей МФЦ ДНР: наглядные интерактивные дашборды,
          прозрачная методика расчёта каждого значения и удобные инструменты для модераторов и руководителей —
          от загрузки данных до принятия управленческих решений.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
          {FEATURES.map((f) => (
            <div key={f.icon} style={featureCard}>
              {FEATURE_ICONS[f.icon]}
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 3 }}>{f.title}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.4 }}>{f.text}</div>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* Счётчики */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }}>
        {counters.map((x) => (
          <div key={x.t} style={counter}>
            <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--accent)' }}>{x.v}</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{x.t}</div>
          </div>
        ))}
      </div>


      {/* Путь настройки — пока не пройден полностью */}
      {nextStep && canManage && (
        <Section title="С чего начать">
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 10 }}>
            Пройдено шагов: {steps.filter((x) => x.done).length} из {steps.length}.
            Следующий — <b style={{ color: 'var(--text)' }}>{nextStep.t.toLowerCase()}</b>.
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {steps.map((x, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 13,
                opacity: x.done ? 0.6 : 1 }}>
                <span style={{ color: x.done ? 'var(--success)' : 'var(--text-faint)' }}>{x.done ? '✓' : '○'}</span>
                <span style={{ fontWeight: x === nextStep ? 600 : 400 }}>{x.t}</span>
                <span style={{ color: 'var(--text-faint)', fontSize: 12 }}>— {x.hint}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Ждут проверки: модератору видно, что от него ждут действия */}
      {!!data.pending_review && canManage && (
        <Section title="Ждут проверки">
          <div style={{ fontSize: 13 }}>
            Дашбордов на модерации: <b>{data.pending_review}</b>. Раздел «Модерация» — очередь и решение по каждому.
          </div>
        </Section>
      )}

      {/* KPI-алерты (сработавшие пороги) */}
      {data.alerts.length > 0 && (
        <Section title={`⚠ Требуют внимания (${data.alerts.length})`}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 10 }}>
            {data.alerts.map((a) => {
              const st = a.level === 'danger'
                ? { color: 'var(--danger)', bg: 'var(--danger-bg)' } : { color: 'var(--warn)', bg: 'var(--warn-bg)' }
              return (
                <button key={a.widget_id} onClick={() => onOpenDashboard(a.dashboard_id)}
                  style={{ textAlign: 'left', cursor: 'pointer', border: `1px solid ${st.color}`, borderLeft: `4px solid ${st.color}`, borderRadius: 10, padding: '10px 12px', background: st.bg }}
                  title="Открыть дашборд">
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: st.color }}>{a.widget_name}</span>
                    <span style={{ fontSize: 12, color: st.color, marginLeft: 'auto' }}>{a.label}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                    {a.measure != null && <b style={{ color: 'var(--text-2)' }}>{fmt(a.measure)}{a.unit ? ` ${a.unit}` : ''}</b>}
                    <span style={{ marginLeft: a.measure != null ? 8 : 0 }}>{a.dashboard_name}{a.page_name ? ` · ${a.page_name}` : ''}</span>
                    {!a.published && <span style={{ marginLeft: 6, color: 'var(--text-faint)' }}>(черновик)</span>}
                  </div>
                </button>
              )
            })}
          </div>
        </Section>
      )}

      {/* Ключевые KPI */}
      <Section title="Ключевые показатели">
        {data.key_kpis.length === 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap', padding: '6px 0 10px' }}>
            <EmptyKpiArt />
            <div style={{ minWidth: 240, flex: 1 }}>
              <div style={{ fontSize: 14, color: 'var(--text-2)', marginBottom: 4 }}>Показатели ещё не выбраны</div>
              <div style={muted}>
                {canManage
                  ? 'Вынесите сюда несколько показателей — они будут считаться на свежих данных и открываться первым экраном.'
                  : 'Набор показателей на этом экране настраивает администратор.'}
              </div>
            </div>
          </div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12 }}>
          {data.key_kpis.map((k) => (
            <div key={k.code} style={kpiCard}>
              <div style={{ display: 'flex', alignItems: 'flex-start' }}>
                <div style={{ fontSize: 13, color: 'var(--text-2)' }}>{k.name}</div>
                {canManage && <button style={rmBtn} onClick={() => removeKpi(k.code)} title="Убрать с главной">✕</button>}
              </div>
              {k.value != null
                ? <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--accent)', marginTop: 4 }}>{fmt(k.value)}{k.unit && <span style={{ fontSize: 13, color: 'var(--text-muted)', marginLeft: 4 }}>{k.unit}</span>}</div>
                : <div style={{ fontSize: 12, color: 'var(--danger)', marginTop: 6 }}>{k.error || 'нет значения'}</div>}
            </div>
          ))}
        </div>
        {canManage && available.length > 0 && (
          <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
            <select id="addkpi" style={sel} defaultValue="">
              <option value="" disabled>Добавить показатель…</option>
              {available.map((m) => <option key={m.code} value={m.code}>{m.name}</option>)}
            </select>
            <button style={btn} onClick={() => { const el = document.getElementById('addkpi') as HTMLSelectElement; addKpi(el.value); el.value = '' }}>＋ На главную</button>
          </div>
        )}
      </Section>

      {/* Каталог страниц */}
      <Section title="Каталог страниц">
        {data.pages.length === 0 ? <div style={muted}>Пока нет страниц дашбордов.</div> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {Object.entries(byDash).map(([did, g]) => (
              <div key={did} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{g.name}</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {g.pages.map((p) => (
                    <button key={p.page_id} style={pageChip} onClick={() => onOpenDashboard(did, p.page_id)}
                      title={p.description || `Открыть страницу «${p.page_name}»`}>
                      {p.page_name} <span style={{ color: 'var(--text-faint)' }}>· {p.widgets} вид.</span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Активность + свежесть */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        <Section title="Что нового">
          {data.recent.length === 0 ? <div style={muted}>Пока нет событий.</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {data.recent.map((r, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, fontSize: 13 }}>
                  <span>{KIND_ICON[r.kind] || '•'}</span>
                  <span style={{ flex: 1 }}>{r.title}</span>
                  <span style={{ color: 'var(--text-faint)', fontSize: 12 }}>{ago(r.at)}</span>
                </div>
              ))}
            </div>
          )}
        </Section>
        <Section title="Свежесть данных">
          {data.freshness.length === 0 ? <div style={muted}>Нет объектов.</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {data.freshness.map((f, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, fontSize: 13 }}>
                  <span style={{ flex: 1 }}>{f.name}</span>
                  <span style={{ color: f.last_period ? 'var(--text-2)' : 'var(--text-faint)' }}>{f.last_period ? `данные на ${f.last_period}` : 'нет данных'}</span>
                </div>
              ))}
            </div>
          )}
        </Section>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <h3 style={{ fontSize: 15, margin: '0 0 10px' }}>{title}</h3>
      {children}
    </div>
  )
}

const clockBox: React.CSSProperties = {
  border: '1px solid var(--border)', borderRadius: 10, padding: '6px 14px', background: 'var(--surface)',
}
const th: React.CSSProperties = {
  border: '1px solid var(--border-faint)', padding: '5px 9px', background: 'var(--surface-2)',
  textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600, whiteSpace: 'nowrap',
}
const td: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '5px 9px' }


const counter: React.CSSProperties = { minWidth: 96, border: '1px solid var(--border)', borderRadius: 12, padding: '12px 16px', textAlign: 'center' }
const featureCard: React.CSSProperties = { display: 'flex', gap: 10, alignItems: 'flex-start', border: '1px solid var(--border)', borderRadius: 12, padding: 12, background: 'var(--surface)' }
const kpiCard: React.CSSProperties = { border: '1px solid var(--border)', borderRadius: 12, padding: 12, background: 'var(--surface)' }
const pageChip: React.CSSProperties = { border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', padding: '6px 10px', fontSize: 13, cursor: 'pointer', color: 'var(--accent)' }
const sel: React.CSSProperties = { height: 34, padding: '0 8px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13, background: 'var(--surface)' }
const btn: React.CSSProperties = { height: 34, padding: '0 12px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer' }
const rmBtn: React.CSSProperties = { marginLeft: 'auto', width: 22, height: 22, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', cursor: 'pointer', color: 'var(--danger)', fontSize: 11 }
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 14, paddingBottom: 8 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8 }
