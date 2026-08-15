import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  autoBuildDashboard, autoBuildPlan,
  type AutoPlan, type DatasetPick, type Dashboard,
} from '../../api'
// Тот же формат числа, что на дашборде и в предложениях метрик: два знака
// после запятой. Свой toLocaleString печатал «656,868 %» там, где везде «656,87 %».
import { fmtNumber } from '../../lib/format'

/**
 * Мастер авто-сборки: что нашли в объекте и что из этого собрать.
 *
 * До него «Собрать» был чёрным ящиком — нажал и получил, что дали, каждый раз
 * новый дашборд. Здесь человек видит состав ДО создания, снимает лишнее
 * галочками и решает, собрать новый или пересобрать существующий.
 *
 * Число «будет создано N виджетов» приходит с сервера от того же планировщика,
 * который потом и создаёт виджеты, — иначе предпросмотр рано или поздно
 * разошёлся бы с результатом и превратился в обман.
 */
const BLOCK_LABELS: Record<string, string> = {
  plan_fact: 'Полосы «план и факт»',
  kpi: 'Карточки показателей',
  dynamics: 'Динамика по периодам',
  compare: 'Сравнение показателей',
  bar: 'График по строкам',
  table: 'Таблица первичных данных',
}

// Вид конкретного показателя. Система предлагает его по роли столбца
// («за отчётную неделю» смотрят в движении, накопительный итог — числом),
// но последнее слово за человеком.
const VIEW_LABELS: { v: string; t: string }[] = [
  { v: 'kpi', t: 'карточка' },
  { v: 'dynamics', t: 'тренд' },
  { v: 'both', t: 'карточка и тренд' },
  { v: 'none', t: 'не показывать' },
]

/** Отчётная дата по-русски: в системе принят ДД.ММ.ГГГГ. */
const ruDate = (iso: string): string =>
  (/^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.split('-').reverse().join('.') : iso)

export default function AutoBuildWizard(
  { objectId, objectName, dashboards, onClose, onDone, onError }: {
    objectId: string
    objectName: string
    dashboards: Dashboard[]
    onClose: () => void
    onDone: (dashboardId: string) => void
    onError: (m: string) => void
  },
) {
  const [plan, setPlan] = useState<AutoPlan | null>(null)
  const [sel, setSel] = useState<Record<string, DatasetPick> | null>(null)
  // Расчётные показатели, отмеченные галочками: заводятся черновиками, и по
  // каждому появляется карточка — раньше принятие предложения давало только
  // метрику, а виджет по ней человек добавлял руками.
  const [metricPicks, setMetricPicks] = useState<Set<string>>(new Set())
  // Пороги невыполнения плана. По умолчанию включены: недобор плана — это то,
  // ради чего дашборд и открывают, а увидеть его цветом быстрее, чем вычитая
  // проценты глазами. Выключается здесь, правится потом кнопкой ⚠ у виджета.
  const [alerts, setAlerts] = useState(true)
  const [restored, setRestored] = useState(false)
  const [target, setTarget] = useState('')          // '' — новый дашборд
  const [busy, setBusy] = useState(false)
  const [loadErr, setLoadErr] = useState<string | null>(null)

  // Первый запрос — без выбора: сервер отдаёт всё, что нашёл, и это же
  // становится начальным состоянием галочек (по умолчанию отмечено всё).
  useEffect(() => {
    autoBuildPlan(objectId)
      .then((p) => {
        setPlan(p)
        const init: Record<string, DatasetPick> = {}
        for (const d of p.datasets) {
          init[d.code] = {
            fields: d.fields.map((f) => f.code),
            blocks: [...p.blocks],
            views: { ...(p.views?.[d.code] || {}) },
          }
        }
        // Прошлый выбор — как черновик: мастер не должен каждую неделю
        // спрашивать одно и то же. Берём только то, что ещё существует в данных.
        const saved = p.saved_selection
        if (saved?.selection) {
          for (const [code, pick] of Object.entries(saved.selection)) {
            const ds = p.datasets.find((d) => d.code === code)
            if (!ds || !init[code]) continue
            const known = new Set(ds.fields.map((f) => f.code))
            init[code] = {
              ...init[code],
              fields: (pick.fields || []).filter((f) => known.has(f)),
              blocks: pick.blocks || init[code].blocks,
              views: { ...init[code].views, ...(pick.views || {}) },
              periods: (pick.periods || []).filter((x) => (ds.period_dates || []).includes(x)),
            }
            setRestored(true)
          }
        }
        if (saved && saved.alerts === false) { setAlerts(false); setRestored(true) }
        if (saved?.metrics?.length) {
          const codes = new Set((p.metrics || []).map((m) => m.code))
          setMetricPicks(new Set(saved.metrics.filter((c) => codes.has(c))))
          setRestored(true)
        }
        setSel(init)
      })
      .catch((e) => setLoadErr((e as Error).message))
  }, [objectId])

  // Пересчёт итога при смене галочек. Дебаунс — чтобы клик по «снять все»
  // не порождал запрос на каждую галочку.
  const recount = useCallback((s: Record<string, DatasetPick>) => {
    autoBuildPlan(objectId, s)
      .then((p) => setPlan((cur) => (cur ? { ...cur, widgets: p.widgets, pages: p.pages, by_type: p.by_type } : p)))
      .catch(() => {})
  }, [objectId])
  useEffect(() => {
    if (!sel) return
    const t = setTimeout(() => recount(sel), 250)
    return () => clearTimeout(t)
  }, [sel, recount])

  function toggleField(code: string, field: string) {
    setSel((s) => {
      if (!s) return s
      const cur = s[code]?.fields || []
      const next = cur.includes(field) ? cur.filter((f) => f !== field) : [...cur, field]
      return { ...s, [code]: { ...s[code], fields: next } }
    })
  }
  function setView(code: string, field: string, view: string) {
    setSel((s) => (s ? { ...s, [code]: { ...s[code], views: { ...(s[code]?.views || {}), [field]: view } } } : s))
  }
  function toggleBlock(code: string, block: string) {
    setSel((s) => {
      if (!s) return s
      const cur = s[code]?.blocks || []
      const next = cur.includes(block) ? cur.filter((b) => b !== block) : [...cur, block]
      return { ...s, [code]: { ...s[code], blocks: next } }
    })
  }
  /** Отдельная страница-срез за эту отчётную дату.
   *  Сводные страницы обновляются сами; страница периода — снимок и не меняется. */
  function togglePeriod(code: string, period: string) {
    setSel((s) => {
      if (!s) return s
      const cur = s[code]?.periods || []
      const next = cur.includes(period) ? cur.filter((p) => p !== period) : [...cur, period]
      return { ...s, [code]: { ...s[code], periods: next } }
    })
  }
  function setAllFields(code: string, all: string[], on: boolean) {
    setSel((s) => (s ? { ...s, [code]: { ...s[code], fields: on ? all : [] } } : s))
  }

  async function build() {
    if (!sel) return
    setBusy(true)
    try {
      const r = await autoBuildDashboard(objectId, {
        name: `Дашборд «${objectName}»`, selection: sel, dashboardId: target || undefined,
        metrics: [...metricPicks], alerts,
      })
      onDone(r.dashboard_id)
    } catch (e) { onError((e as Error).message); setBusy(false) }
  }

  return createPortal(
    <div style={backdrop} onClick={onClose}>
      <div style={card} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>Собрать дашборд по объекту «{objectName}»</h3>
          <button style={{ ...btnGhost, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>

        {loadErr && <div style={errBox}>{loadErr}</div>}
        {!plan && !loadErr && <div style={muted}>Смотрим, что есть в объекте…</div>}

        {plan && sel && (
          <>
            {restored && (
              <div style={{ ...muted, fontSize: 12.5, marginBottom: 10 }}>
                ↩ Восстановлен выбор прошлой сборки — поменяйте, если нужно иначе.
              </div>
            )}
            {plan.warnings.map((w, i) => <div key={i} style={warnBox}>⚠ {w}</div>)}

            {plan.datasets.map((d) => {
              const pick = sel[d.code] || {}
              const allFields = d.fields.map((f) => f.code)
              const on = pick.fields || []
              return (
                <div key={d.code} style={block}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>{d.name}</div>
                  <div style={{ ...muted, fontSize: 12.5, marginBottom: 8 }}>
                    код {d.code} · периодов: {d.periods} · показателей: {d.fields.length}
                    {d.periods > 1 && ' · динамика строится по всем периодам'}
                  </div>

                  <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 4 }}>Что показать</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 10 }}>
                    {plan.blocks.map((b) => (
                      <label key={b} style={chk}>
                        <input type="checkbox" checked={(pick.blocks || []).includes(b)}
                          onChange={() => toggleBlock(d.code, b)} />
                        {BLOCK_LABELS[b] || b}
                      </label>
                    ))}
                  </div>

                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 12.5, fontWeight: 600 }}>Показатели ({on.length} из {d.fields.length})</span>
                    <button style={linkBtn} onClick={() => setAllFields(d.code, allFields, true)}>все</button>
                    <button style={linkBtn} onClick={() => setAllFields(d.code, allFields, false)}>снять</button>
                  </div>
                  <div style={fieldBox}>
                    {d.fields.map((f) => (
                      <div key={f.code} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <label style={{ ...chk, flex: 1, minWidth: 0 }} title={f.name}>
                          <input type="checkbox" checked={on.includes(f.code)}
                            onChange={() => toggleField(d.code, f.code)} />
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</span>
                        </label>
                        <select
                          style={viewSel} value={(pick.views || {})[f.code] || 'kpi'}
                          disabled={!on.includes(f.code)}
                          title="Как показать этот показатель"
                          onChange={(e) => setView(d.code, f.code, e.target.value)}
                        >
                          {VIEW_LABELS.filter((v) => d.periods > 1 || v.v === 'kpi' || v.v === 'none')
                            .map((v) => <option key={v.v} value={v.v}>{v.t}</option>)}
                        </select>
                      </div>
                    ))}
                  </div>
                  {(d.period_dates || []).length > 1 && (
                    <>
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, margin: '12px 0 4px' }}>
                        <span style={{ fontSize: 12.5, fontWeight: 600 }}>
                          Отдельные страницы по отчётам ({(pick.periods || []).length})
                        </span>
                      </div>
                      <div style={{ ...muted, fontSize: 12, marginBottom: 6 }}>
                        Страницы выше — сводные: они показывают последний отчёт и обновляются сами,
                        когда приходит новый. Страница за конкретную дату — снимок: её цифры
                        привязаны к этой дате и не меняются. Отметьте недели, которые нужно
                        сохранить отдельно (не больше восьми).
                      </div>
                      <div style={{ ...fieldBox, maxHeight: 110 }}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                          {(d.period_dates || []).map((p) => (
                            <label key={p} style={chk}>
                              <input type="checkbox" checked={(pick.periods || []).includes(p)}
                                disabled={!(pick.periods || []).includes(p) && (pick.periods || []).length >= 8}
                                onChange={() => togglePeriod(d.code, p)} />
                              {ruDate(p)}
                            </label>
                          ))}
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )
            })}

            {(plan.metrics || []).length > 0 && (
              <div style={block}>
                <div style={{ fontSize: 14, fontWeight: 600 }}>
                  Расчётные показатели ({metricPicks.size} из {(plan.metrics || []).length})
                </div>
                <div style={{ ...muted, fontSize: 12, margin: '4px 0 8px' }}>
                  Система нашла их по самим данным и проверила расчётом. Отмеченные будут
                  заведены черновиками и сразу показаны на дашборде — согласование формулы
                  идёт обычным порядком, на дашборде число видно уже сейчас.
                  Проценты показываются спидометром (⏱ рядом с названием): на шкале
                  сразу видно, близко ли к 100 %, — остальные карточкой.
                </div>
                <div style={{ ...fieldBox, maxHeight: 190 }}>
                  {(plan.metrics || []).map((m) => (
                    <label key={m.code} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12.5 }}>
                      <input type="checkbox" checked={metricPicks.has(m.code)}
                        style={{ marginTop: 3 }}
                        onChange={() => setMetricPicks((s2) => {
                          const n = new Set(s2)
                          if (n.has(m.code)) n.delete(m.code); else n.add(m.code)
                          return n
                        })} />
                      <span style={{ minWidth: 0 }}>
                        {(m.unit || '').includes('%') && (
                          <span title="Будет показан спидометром">⏱ </span>
                        )}
                        <span style={{ overflowWrap: 'anywhere' }}>{m.name}</span>
                        {m.preview_value != null && (
                          <span style={{ color: 'var(--accent)' }}> = {fmtNumber(m.preview_value)}
                            {m.unit ? ` ${m.unit}` : ''}</span>
                        )}
                        {m.why && <span style={{ ...muted, display: 'block', fontSize: 11.5 }}>{m.why}</span>}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            )}

            <div style={block}>
              <label style={{ ...chk, fontWeight: 600 }}>
                <input type="checkbox" checked={alerts} onChange={() => setAlerts((v) => !v)} />
                🚦 Подсвечивать невыполнение плана
              </label>
              <div style={{ ...muted, fontSize: 12, marginTop: 4 }}>
                Полоса «план и факт» и спидометр «выполнение плана, %» будут краснеть
                ниже 90 % и желтеть ниже 100 %, а от 100 % — зеленеть. Норма здесь не
                выдумана: 100 % — это сам план. У показателей без известной нормы
                (например, доля доставленных) порогов не будет. Пороги любого виджета
                потом правятся кнопкой ⚠ в режиме «Двигать и менять размер».
              </div>
            </div>

            <div style={block}>
              <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>Куда собрать</div>
              <select style={input} value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="">Новый дашборд</option>
                {dashboards.map((d) => <option key={d.id} value={d.id}>Пересобрать «{d.name}»</option>)}
              </select>
              {target && (
                <div style={{ ...muted, fontSize: 12.5, marginTop: 6 }}>
                  Страницы и виджеты будут заменены. Права доступа, обсуждение и история версий останутся.
                </div>
              )}
            </div>

            <div style={total}>
              Будет создано: <b>{plan.pages?.length || 0}</b> {pagePlural(plan.pages?.length || 0)}
              {' · '}<b>{plan.widgets}</b> {plural(plan.widgets)}
              {(plan.pages || []).length > 0 && (
                <div style={{ color: 'var(--text-muted)', marginTop: 3 }}>
                  {plan.pages.map((p) => `${p.name}: ${p.widgets}`).join(' · ')}
                </div>
              )}
              {plan.widgets > 0 && (
                <span style={{ color: 'var(--text-muted)' }}>
                  {' '}({Object.entries(plan.by_type).filter(([, n]) => n > 0)
                    .map(([t, n]) => `${BLOCK_LABELS[t] || t}: ${n}`).join(', ')})
                </span>
              )}
            </div>

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
              <button style={btnGhost} onClick={onClose}>Отмена</button>
              <button style={btn} disabled={busy || plan.widgets === 0} onClick={build}>
                {busy ? 'Собираем…' : target ? 'Пересобрать' : 'Собрать'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  )
}

function pagePlural(n: number): string {
  const t = n % 100
  if (t >= 11 && t <= 14) return 'страниц'
  switch (n % 10) {
    case 1: return 'страница'
    case 2: case 3: case 4: return 'страницы'
    default: return 'страниц'
  }
}

function plural(n: number): string {
  const t = n % 100
  if (t >= 11 && t <= 14) return 'виджетов'
  switch (n % 10) {
    case 1: return 'виджет'
    case 2: case 3: case 4: return 'виджета'
    default: return 'виджетов'
  }
}

const backdrop: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(20,20,20,0.45)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 16,
}
const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14,
  padding: 18, width: 'min(720px, 100%)', maxHeight: '86vh', overflowY: 'auto',
  display: 'flex', flexDirection: 'column', gap: 10,
}
const block: React.CSSProperties = {
  border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px',
}
const fieldBox: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 190, overflowY: 'auto',
  border: '1px solid var(--border-faint)', borderRadius: 8, padding: '6px 8px',
}
const viewSel: React.CSSProperties = { height: 26, fontSize: 12, border: '1px solid var(--border-strong)', borderRadius: 6, background: 'var(--surface)', flexShrink: 0, maxWidth: 150 }
const chk: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, minWidth: 0, cursor: 'pointer' }
const total: React.CSSProperties = {
  background: 'var(--surface-2)', borderRadius: 8, padding: '9px 12px', fontSize: 13,
}
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 13 }
const input: React.CSSProperties = { height: 34, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13, width: '100%' }
const btn: React.CSSProperties = { height: 34, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { height: 34, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', fontSize: 13, cursor: 'pointer' }
const linkBtn: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', fontSize: 12, cursor: 'pointer', padding: 0 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8 }
const warnBox: React.CSSProperties = { background: 'var(--warn-bg)', color: 'var(--warn)', fontSize: 13, padding: '8px 10px', borderRadius: 8 }
