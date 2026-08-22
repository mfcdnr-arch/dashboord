import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { EChartsOption } from 'echarts'
import { getWidgetData, getWidgetDrill } from '../api'
import { chartColors, useThemeVersion } from '../theme'
import { useContainerWidth } from '../lib/useWidth'
import EChart from './EChartLazy'
import FitText from './dashboards/FitText'
import RelatedMenu from './dashboards/RelatedMenu'
import ReportProblemDialog from './dashboards/ReportProblemDialog'
import { fmtNumber as fmt, logScaleAdvice } from '../lib/format'
import { distinctLabels, elideMiddle } from '../lib/text'

// Отрисовка данных виджета: KPI/таблица/план-факт — HTML, столбцы/линия/круговая —
// ECharts. По кнопке «подробнее» — drill (прозрачность): формула метрики + первичные строки.


// Дата актуальности данных (as_of) в формате ДД.ММ.ГГГГ.
function fmtAsOf(iso: string): string {
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString('ru-RU')
}

// Один ли это отчётный день. Сравниваем по КАЛЕНДАРНОЙ дате, а не по строке:
// свежесть страницы и as_of виджета приходят из разных запросов и могут
// отличаться временем внутри суток.
function sameDay(a?: string, b?: string): boolean {
  if (!a || !b) return false
  const x = new Date(a), y = new Date(b)
  return !isNaN(x.getTime()) && !isNaN(y.getTime()) && x.toDateString() === y.toDateString()
}

// Высота графика под РЕАЛЬНО доступное место в карточке.
// Раньше высота была константой: как только под графиком добавилась вторая строка
// итогов, содержимое перестало помещаться (276px против 192px), карточка включила
// прокрутку и показала только нижнюю часть оси — линия графика уехала из виду.
// Числа важнее картинки, поэтому ужимается график, а не подписи.
function useFitHeight(base: number) {
  const box = useRef<HTMLDivElement>(null)
  const labels = useRef<HTMLDivElement>(null)
  const [h, setH] = useState(base)

  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    // Ограничивает высоту не прямой родитель, а карточка виджета выше по дереву;
    // между ними лежат и другие блоки («подробнее», «данные на»), которые тоже
    // занимают место. Поэтому меряем не «сколько осталось», а фактическое
    // переполнение карточки и ужимаем график ровно на него.
    let scroller: HTMLElement | null = el.parentElement
    while (scroller && getComputedStyle(scroller).overflowY === 'visible') scroller = scroller.parentElement
    if (!scroller || !scroller.clientHeight) return // предпросмотр в форме: высота не ограничена

    const calc = () => {
      const s = scroller as HTMLElement
      const over = s.scrollHeight - s.clientHeight
      setH((cur) => {
        if (over > 0) return Math.max(MIN_CHART_H, cur - over)
        if (cur < base) return Math.min(base, cur + Math.max(0, s.clientHeight - s.scrollHeight))
        return cur
      })
    }
    calc()
    const ro = new ResizeObserver(calc)
    ro.observe(scroller)
    if (labels.current) ro.observe(labels.current)
    return () => ro.disconnect()
  }, [base])

  return { box, labels, h }
}
// Ниже этого графику нельзя: на 84px даже три деления оси налезали друг на друга.
// Если содержимое всё равно не помещается, карточка включит прокрутку — это
// честнее, чем показать нечитаемый график.
const MIN_CHART_H = 118

// Ширина полосы под подписи оси значений. При миллионах «3 000 000» не влезает
// в фиксированные 44px и обрезается слева — считаем место по самому длинному числу.
function gridLeft(values: (number | null | undefined)[]): number {
  const max = Math.max(0, ...values.filter((v): v is number => typeof v === 'number' && isFinite(v)).map(Math.abs))
  const digits = fmt(Math.round(max)).length
  return Math.min(80, Math.max(44, 12 + digits * 7))
}

// Границы логарифмической оси: ближайшие степени десятки вокруг данных.
// Без них ось уезжает на порядки выше максимума и график «прижимается» к низу.
function logBound(values: number[], kind: 'min' | 'max'): number {
  const nums = values.filter((v) => typeof v === 'number' && isFinite(v) && v > 0)
  if (!nums.length) return kind === 'min' ? 1 : 10
  const v = kind === 'min' ? Math.min(...nums) : Math.max(...nums)
  const p = kind === 'min' ? Math.floor(Math.log10(v)) : Math.ceil(Math.log10(v))
  return Math.pow(10, p)
}

// Подпись периода на графике динамики. Периоды приходят как «2026-07-22»
// (дата выпуска) либо «2026-07» (месяц) — машинный вид на оси читается плохо.
function fmtPeriod(p: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(p)) return fmtAsOf(p)
  const m = /^(\d{4})-(\d{2})$/.exec(p)
  return m ? `${m[2]}.${m[1]}` : p
}

// Палитра серий — из CSS-токенов темы (см. theme.css: --chart-*); при смене темы
// Body перерисовывается (useThemeVersion) и графики пересобираются с новыми цветами.
function chartOption(data: any): EChartsOption {
  const C = chartColors()
  const cats: string[] = data.categories || []
  const vals: number[] = data.values || []
  if (data.type === 'pie') {
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{ type: 'pie', radius: ['35%', '70%'], data: cats.map((c, i) => ({ name: c, value: vals[i] })),
        label: { fontSize: 11 }, color: C.palette }],
    }
  }
  const isLine = data.type === 'line'
  return {
    grid: { left: gridLeft(vals), right: 12, top: 12, bottom: cats.some((c) => c.length > 6) ? 46 : 24 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: cats, axisLabel: { interval: 0, rotate: cats.some((c) => c.length > 6) ? 30 : 0, fontSize: 11 } },
    yAxis: { type: 'value' },
    series: [{ type: isLine ? 'line' : 'bar', data: vals, smooth: isLine,
      color: C.c1, itemStyle: { color: C.c1 }, lineStyle: { color: C.c1, width: 2 }, areaStyle: isLine ? { opacity: 0.08 } : undefined,
      barMaxWidth: 40 }],
  }
}

export default function WidgetView({ widgetId, reloadKey, showDrill = true, from, to, row, onPick, batched, injData, injError, pageAsOf, stripe = true, onNavigate, widgetName, onOpenAppeals, onAddField, print = false }: { widgetId: string; reloadKey?: number; showDrill?: boolean; from?: string; to?: string; row?: string; onPick?: (name: string) => void; batched?: boolean; injData?: any; injError?: string; pageAsOf?: string;
  /** Рисовать ли цветную ленту состояния вокруг тела. На дашборде её рисует
   *  САМА карточка (по всей высоте, включая имя) — там лента здесь была бы
   *  второй полосой внутри первой. */
  stripe?: boolean
  /** Переход к другому виджету из меню «куда дальше» (п. 1). Не передан —
   *  меню показывает связи справочно, без переходов. */
  onNavigate?: (dashboardId: string, pageId: string | null, widgetId: string) => void
  /** Имя виджета — показывается в окне жалобы, чтобы человек видел, на что
   *  жалуется (в самом обращении контекст всё равно проставит сервер). */
  widgetName?: string
  /** Перейти в свои обращения после отправки жалобы (п. 15). */
  onOpenAppeals?: () => void
  /** Завести карточку соседней графы формы прямо из меню «куда дальше».
   *  Не передан — у смотрящего нет права менять дашборд. */
  onAddField?: (field: string, name: string, datasetCode: string) => Promise<void>
  /** Режим отчёта (выгрузка PDF): показываем ВСЁ, а не то, что влезло в карточку —
   *  легенда целиком, таблица со всеми столбцами, график крупнее. На экране эти
   *  ограничения осмысленны (место), в отчёте они превращаются в потерю данных. */
  print?: boolean }) {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [drill, setDrill] = useState<any | null>(null)
  const [related, setRelated] = useState(false)
  const [problem, setProblem] = useState(false)
  const [menu, setMenu] = useState(false)
  const [footRef, footWidth] = useContainerWidth<HTMLDivElement>()

  useEffect(() => {
    // Батч-режим: данные приходят от родителя (1 запрос на всю страницу) — не фетчим сами.
    if (batched) {
      setData(injData ?? null)
      setError(injError ?? null)
      return
    }
    setData(null); setError(null)
    getWidgetData(widgetId, from, to, row).then(setData).catch((e) => setError((e as Error).message))
  }, [widgetId, reloadKey, from, to, row, batched, injData, injError])

  const openDrill = () => getWidgetDrill(widgetId).then(setDrill).catch((e) => setError((e as Error).message))

  const alert = data?.alert
  const isAnnotation = data?.type === 'text' || data?.type === 'image'
  const canDrill = !!data && showDrill && !isAnnotation
  // Жаловаться можно и на сломанный виджет: именно тогда это и нужно.
  const canReport = (!!data || !!error) && showDrill && !isAnnotation
  // Три подписи + отступы занимают ~300px. До первого замера footWidth не
  // определена — показываем полный набор: свернуть потом дешевле, чем моргнуть
  // «⋯» на широкой карточке.
  const actionsFit = footWidth === undefined || footWidth >= 300
  return (
    <div style={alert && stripe ? { borderLeft: `4px solid ${alert.color}`, background: alert.bg, borderRadius: 6, padding: '6px 8px', margin: '-2px 0' } : undefined}>
      {error && <div style={errBox}>{error}</div>}
      {/* Пока данных нет — бледный контур на месте будущего числа, а не слово
          «Загрузка…». На странице в два десятка карточек текст, сменяющийся
          цифрой, читается как рывок: глаз цепляется за каждое слово и теряет
          место. Контур занимает то же место, что и содержимое, поэтому смена
          выглядит проявлением, а не подстановкой. */}
      {!data && !error && <WidgetSkeleton />}
      {alert && (
        <div style={{ display: 'inline-block', fontSize: 11, fontWeight: 600, color: alert.color,
          background: '#fff', border: `1px solid ${alert.color}`, borderRadius: 10, padding: '1px 8px', marginBottom: 6 }}
          title="Сработал порог KPI-алерта">⚠ {alert.label}</div>
      )}
      {data && <div className="w-appear">
        <Body data={data} onPick={onPick} print={print} />
      </div>}
      {/* Подвал действий («куда дальше», «проблема») в выгрузку не идёт: в PDF
          эти ссылки нажать нельзя, а место у самого числа они отнимают. */}
      <div ref={footRef} data-export-hide style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        {/* Три подписи в подвале не помещаются на узкой карточке (12 колонок
            сетки — это ~120px) и уезжают на вторую строку, отнимая высоту у
            самого числа. Поэтому на узких карточках они сворачиваются в «⋯»:
            действия остаются доступны, но не спорят с содержимым за место. */}
        {actionsFit ? (
          <>
            {/* Отдельной кнопки «🔍 подробнее» больше нет: разбор показателя
                стал ПЕРВЫМ пунктом этого же меню. Две кнопки рядом отвечали на
                соседние вопросы («из чего это» и «куда дальше»), и подвал
                узкой карточки они делили с третьей — «проблема». */}
            {canDrill && (
              <button style={drillBtn} onClick={() => setRelated(true)}
                title="Из чего собран показатель, где он ещё есть, что рядом в форме, есть ли динамика">
                ↗ куда дальше
              </button>
            )}
            {/* «Сообщить о проблеме» (п. 15). Показывается и при ОШИБКЕ расчёта —
                именно тогда человеку и нужно пожаловаться, а data в этот момент
                нет. Контекст (отчёт, страница, показатель, значение) приложит
                сервер: объяснять словами, где это, не нужно. */}
            {canReport && (
              <button style={{ ...drillBtn, color: 'var(--text-faint)' }} onClick={() => setProblem(true)}
                title="Сообщить администратору о проблеме с этой цифрой — где вы её увидели, система приложит сама">
                ⚑ проблема
              </button>
            )}
          </>
        ) : (canDrill || canReport) && (
          <button style={drillBtn} onClick={() => setMenu(true)}
            title="Действия: из чего собран показатель, куда посмотреть дальше, сообщить о проблеме">⋯ действия</button>
        )}
        {data?.as_of && (data.period_locked || !sameDay(data.as_of, pageAsOf)) && (
          // У виджета с закреплённым периодом это СРЕЗ: он не обновится, когда
          // придёт следующая неделя. Не сказать об этом — значит выдать снимок
          // за актуальные данные.
          //
          // А вот когда дата виджета совпадает с общей датой страницы (она
          // написана строкой над сеткой), повторять её в КАЖДОЙ карточке незачем:
          // это дубль, который на карточке в три ряда съедал место у самого
          // числа и включал прокрутку. Отличается — показываем: значит виджет
          // смотрит на другие данные, и это важно.
          <span
            style={{ fontSize: 11, color: data.period_locked ? 'var(--warn)' : 'var(--text-faint)' }}
            title={data.period_locked
              ? 'Виджет закреплён за отчётной датой: он показывает срез и не меняется, когда приходит новый отчёт'
              : 'Дата актуальности данных (активный выпуск датасета)'}
          >
            {data.period_locked
              ? `📌 срез за ${fmtAsOf(data.as_of)} · не обновляется`
              : `🕓 данные на ${fmtAsOf(data.as_of)}`}
          </span>
        )}
        {data?.sources && (
          <span style={{ fontSize: 11, color: 'var(--text-faint)' }} title="У виджета несколько источников — единой даты свежести нет, у каждого своя">
            🕓 {data.sources.map((s: any) => `${s.label}: ${s.as_of ? fmtAsOf(s.as_of) : '—'}`).join(' · ')}
          </span>
        )}
      </div>
      {drill && <DrillModal drill={drill} onClose={() => setDrill(null)} />}
      {related && (
        <RelatedMenu widgetId={widgetId} onClose={() => setRelated(false)}
          onOpenDrill={openDrill} onNavigate={onNavigate} onAddField={onAddField} />
      )}
      {problem && (
        <ReportProblemDialog widgetId={widgetId} widgetName={widgetName}
          onClose={() => setProblem(false)} onOpenAppeals={onOpenAppeals} />
      )}
      {menu && (
        <ActionsMenu
          onClose={() => setMenu(false)}
          items={[
            ...(canDrill ? [{ label: '↗ Куда посмотреть дальше', run: () => setRelated(true) }] : []),
            ...(canReport ? [{ label: '⚑ Сообщить о проблеме', run: () => setProblem(true) }] : []),
          ]}
        />
      )}
    </div>
  )
}

// Рендер тела виджета по готовым данным — используется в конструкторе для предпросмотра.
/** Место будущего содержимого, пока идёт расчёт. Не «крутилка»: она сообщает
 *  «система занята», а вопрос у смотрящего другой — «где моя цифра». Контур
 *  занимает ту же площадь, поэтому карточка не прыгает, когда данные приходят. */
function WidgetSkeleton() {
  return (
    <div className="w-skel" aria-label="Данные загружаются" style={{ padding: '4px 0' }}>
      <div className="w-skel-bar" style={{ width: '62%', height: 26, borderRadius: 6 }} />
      <div className="w-skel-bar" style={{ width: '38%', height: 12, borderRadius: 6, marginTop: 8 }} />
    </div>
  )
}

/** Действия виджета, свёрнутые в «⋯» на узкой карточке.
 *
 * Выводится порталом в body: карточка виджета обрезает содержимое
 * (overflow: hidden), и меню внутри неё было бы срезано — тот же дефект, что
 * уже ловили у подсказки ⓘ, окна «подробнее» и меню «куда дальше».
 *
 * Открывается по центру экрана, а не «прилипает» к кнопке: карточка, из
 * которой его зовут, узкая и может стоять у самого края страницы — меню от
 * кнопки пришлось бы поджимать и переворачивать, а список из трёх пунктов от
 * этого читается не лучше. */
function ActionsMenu({ items, onClose }: { items: { label: string; run: () => void }[]; onClose: () => void }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])
  return createPortal(
    <div style={{ position: 'fixed', inset: 0, zIndex: 70, background: 'rgba(0,0,0,0.28)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
      onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ background: 'var(--surface)', borderRadius: 12, padding: 8, minWidth: 240, maxWidth: '92vw',
          boxShadow: '0 10px 40px rgba(0,0,0,0.2)', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {items.map((it) => (
          <button key={it.label} onClick={() => { onClose(); it.run() }}
            style={{ textAlign: 'left', padding: '9px 12px', borderRadius: 8, border: 'none',
              background: 'none', color: 'var(--text)', fontSize: 13, cursor: 'pointer' }}>
            {it.label}
          </button>
        ))}
      </div>
    </div>,
    document.body,
  )
}

export function WidgetPreviewBody({ data }: { data: any }) {
  return <Body data={data} />
}

// Цель/бенчмарк под показателем: значение цели + % достижения (зелёный при ≥100%).
/** Мини-график динамики внутри карточки: только форма движения, без осей. */
function Sparkline({ values, color }: { values: number[]; color: string }) {
  const w = 100, h = 22
  const min = Math.min(...values), max = Math.max(...values)
  const span = max - min || 1
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w
    const y = h - ((v - min) / span) * (h - 3) - 1.5
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const last = values[values.length - 1]
  const lastY = h - ((last - min) / span) * (h - 3) - 1.5
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
      style={{ width: '100%', height: 22, marginTop: 4, display: 'block' }}
      aria-label="Динамика по отчётным периодам">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5}
        vectorEffect="non-scaling-stroke" />
      <circle cx={w} cy={lastY} r={2} fill={color} />
    </svg>
  )
}

function TargetLine({ data }: { data: any }) {
  if (data.target == null) return null
  const pct = data.target_pct
  const reached = pct != null && pct >= 100
  return (
    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
      {data.target_label || 'Цель'}: <b style={{ color: 'var(--text-2)' }}>{fmt(data.target)}</b>
      {pct != null && <span style={{ marginLeft: 6, color: reached ? 'var(--success)' : 'var(--warn)', fontWeight: 600 }}>· {fmt(pct)}%{reached ? ' ✓' : ''}</span>}
    </div>
  )
}

/**
 * Как получено число, когда это неочевидно.
 *
 * Доли и проценты по нескольким строкам нельзя складывать, поэтому карточка
 * показывает среднее — но среднее по строкам это приближение (правильная доля
 * считается из числителя и знаменателя, а их у столбца-процента уже нет).
 * Промолчать значило бы выдать приближение за точный итог. Для суммы подписи
 * нет: сложение количеств никого не удивляет, а лишняя строка съедает высоту.
 */
function AggregateNote({ data }: { data: any }) {
  if (data.aggregate !== 'avg') return null
  return (
    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}
      title="Проценты и доли по строкам не складываются — показано среднее. Точное значение по одной строке смотрите фильтром «Строка» или в таблице">
      среднее по {data.rows_used} строкам
    </div>
  )
}

type SortState = { col: string; dir: 1 | -1 } | null

// Сортировка по клику на заголовок столбца (3 состояния: ▲ → ▼ → сброс) + поиск
// по значениям — общее для table/pivot (виджеты становятся длинными без этого).
function sortRows<T extends Record<string, unknown>>(rows: T[], sort: SortState, getVal: (r: T, col: string) => unknown): T[] {
  if (!sort) return rows
  const { col, dir } = sort
  return [...rows].sort((a, b) => {
    const av = getVal(a, col); const bv = getVal(b, col)
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
    return String(av).localeCompare(String(bv), 'ru') * dir
  })
}
function toggleSort(setSort: (f: (s: SortState) => SortState) => void, col: string) {
  setSort((s) => (s && s.col === col ? (s.dir === 1 ? { col, dir: -1 } : null) : { col, dir: 1 }))
}
function sortArrow(sort: SortState, col: string): string {
  return sort?.col === col ? (sort.dir === 1 ? ' ▲' : ' ▼') : ''
}
const searchInput: React.CSSProperties = {
  height: 30, padding: '0 10px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'var(--surface)', color: 'var(--text)', fontSize: 12, width: 220, marginBottom: 8,
}
const sortableTh: React.CSSProperties = { cursor: 'pointer', userSelect: 'none' }
// Первый столбец (названия строк) не уезжает при горизонтальной прокрутке —
// иначе после сдвига непонятно, к какой строке относится число.
const stickyCol: React.CSSProperties = {
  position: 'sticky', left: 0, zIndex: 2, background: 'var(--surface)',
  boxShadow: '1px 0 0 var(--border-faint)',
}
// У закреплённого ЗАГОЛОВКА фон должен совпадать с остальной шапкой —
// иначе на её фоне он выглядит белой дырой.
const stickyHead: React.CSSProperties = { zIndex: 3, background: 'var(--surface-2)' }
// Значок ▲/▼ у заголовка ничего не объясняет сам по себе — подсказка при наведении
// говорит, что это сортировка и что делает повторный клик.
const SORT_HINT = 'Сортировать по этому столбцу: ▲ по возрастанию, ▼ по убыванию, третий клик — сброс'


/** Прогноз даты достижения плана (plan_fact). Всегда честен: вместо
 *  выдуманной даты говорит, почему её нет. */
function PlanForecast({ f, unit }: { f: any; unit?: string }) {
  const ru = (d?: string) => (d && /^\d{4}-\d{2}-\d{2}$/.test(d) ? d.split('-').reverse().join('.') : d)
  const base: React.CSSProperties = { fontSize: 12, marginTop: 8, paddingTop: 6, borderTop: '1px dashed var(--border-faint)' }
  if (f.reason === 'done') return <div style={{ ...base, color: 'var(--success)' }}>✓ План уже выполнен</div>
  if (f.reason === 'no_growth') return (
    <div style={{ ...base, color: 'var(--danger)' }} title={`Средний темп с ${ru(f.from_period)} по ${ru(f.to_period)} — не выше нуля`}>
      ⚠ При нынешней динамике план не будет достигнут: роста между отчётами нет
    </div>
  )
  if (f.reason === 'too_far') return (
    <div style={{ ...base, color: 'var(--danger)' }}>⚠ При нынешнем темпе до плана более 10 лет — темп нужно менять, а не ждать</div>
  )
  if (f.reason !== 'ok') return (
    <div style={{ ...base, color: 'var(--text-faint)' }}>
      Прогноз не строится: {f.reason === 'few_points' ? 'нужно минимум два отчёта с разными датами' : 'нет данных'}
    </div>
  )
  const rate = f.rate >= 1 ? fmt(Math.round(f.rate)) : fmt(Number(f.rate.toFixed(2)))
  return (
    <div style={base}>
      <span style={{ color: 'var(--text-2)' }}>При нынешнем темпе план будет достигнут </span>
      <b>≈ {ru(f.date)}</b>
      <span style={{ color: 'var(--text-2)' }}> (через {f.days} дн.)</span>
      <div style={{ color: 'var(--text-faint)', fontSize: 11, marginTop: 2 }}>
        средний темп +{rate}{unit ? ` ${unit}` : ''} в день по {f.points} отчётам с {ru(f.from_period)} по {ru(f.to_period)}; осталось {fmt(f.remain)}
      </div>
    </div>
  )
}

function Body({ data, onPick, print = false }: { data: any; onPick?: (name: string) => void; print?: boolean }) {
  useThemeVersion() // перерисовка при смене темы: цвета серий берутся из токенов
  const C = chartColors()
  const [tableSearch, setTableSearch] = useState('')
  const [tableSort, setTableSort] = useState<SortState>(null)
  const [pivotSearch, setPivotSearch] = useState('')
  const [pivotSort, setPivotSort] = useState<SortState>(null)
  const [matrixSort, setMatrixSort] = useState<SortState>(null)
  // Хук объявлен до ветвления по типу виджета: тип может смениться при правке
  // виджета, а порядок хуков между рендерами меняться не должен.
  // В отчёте высоту не подгоняем под карточку: там места столько, сколько
  // нужно графику, и ужимать его незачем — наоборот, он должен читаться.
  const fitRaw = useFitHeight(196)
  const gaugeRaw = useFitHeight(190)
  const fit = print ? { ...fitRaw, h: 300 } : fitRaw
  /** В отчёте графики рисуем БЕЗ анимации.
   *
   *  Снимок делается сразу после отрисовки, а ECharts анимирует появление ~1 с —
   *  в кадр попадали пустые оси без столбиков и линий. Ждать дольше ненадёжно:
   *  на слабой машине анимация идёт дольше, и дефект вернётся молча. */
  const P = (o: EChartsOption): EChartsOption => (print ? { ...o, animation: false } : o)
  const gaugeFit = print ? { ...gaugeRaw, h: 240 } : gaugeRaw
  // За выбранный период отчётов нет. Говорим об этом прямо: раньше фильтр
  // молча показывал последний отчёт, и цифру не за тот период принимали за
  // нужную — пустое место честнее.
  if (data.no_data_in_period) {
    const ru = (d?: string) => (d && /^\d{4}-\d{2}-\d{2}$/.test(d) ? d.split('-').reverse().join('.') : d)
    const range = [ru(data.from_date), ru(data.to_date)].filter(Boolean).join(' — ')
    return (
      <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', height: '100%',
        color: 'var(--text-faint)', fontSize: 13, lineHeight: 1.5, gap: 4 }}>
        <div>За выбранный период отчётов нет{range ? ` (${range})` : ''}.</div>
        <div style={{ fontSize: 12 }}>Снимите фильтр периода или выберите другой диапазон.</div>
      </div>
    )
  }
  if (data.type === 'text') {
    const align = data.align === 'center' ? 'center' : 'left'
    if (!data.heading && !data.body) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Пустая аннотация</div>
    return (
      <div style={{ textAlign: align }}>
        {data.heading && <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>{data.heading}</div>}
        {data.body && <div style={{ fontSize: 14, color: 'var(--text-2)', marginTop: data.heading ? 4 : 0, whiteSpace: 'pre-wrap' }}>{data.body}</div>}
      </div>
    )
  }
  if (data.type === 'image') {
    if (!data.url) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Не указан URL картинки</div>
    return (
      <div style={{ textAlign: 'center' }}>
        <img src={data.url} alt={data.caption || ''} style={{ maxWidth: '100%', maxHeight: 220, objectFit: data.fit === 'cover' ? 'cover' : 'contain' }} />
        {data.caption && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>{data.caption}</div>}
      </div>
    )
  }
  if (data.type === 'kpi') {
    const kpiText = fmt(data.value) + (data.unit ? ' ' + data.unit : '')
    const up = (data.delta ?? 0) > 0
    const flat = !data.delta
    return (
      <div>
        {/* При наличии прироста число чуть мельче: иначе карточка не вмещает
            обе строки и появляется полоса прокрутки. */}
        <FitText size={data.prev_value != null ? 26 : 30} title={kpiText}
          style={{ fontWeight: 700, color: data.alert?.color || 'var(--accent)' }}>{fmt(data.value)}
          {data.unit && <span style={{ fontSize: '0.5em', color: 'var(--text-muted)', marginLeft: 6 }}>{data.unit}</span>}
        </FitText>
        {/* Прирост к прошлому отчёту: голое число не отвечает на вопрос «это
            много или мало» — а «+38 174 (+4,3 %) к 22.07» отвечает. */}
        {data.prev_value != null && (
          // Дату прошлого отчёта держим в подсказке, а не в строке: на узкой
          // карточке она обрезалась хвостом «к 22.0…» и только мешала.
          <div style={{ fontSize: 12, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        color: flat ? 'var(--text-muted)' : up ? 'var(--success)' : 'var(--danger)' }}
            title={`Прошлый отчёт за ${fmtAsOf(String(data.prev_period))}: ${fmt(data.prev_value)}`}>
            {flat ? '= столько же, что и в прошлом отчёте'
              : `${up ? '▲' : '▼'} ${up ? '+' : ''}${fmt(data.delta)}`}
            {data.delta_pct != null && !flat && ` (${data.delta_pct > 0 ? '+' : ''}${fmt(data.delta_pct)} %)`}
          </div>
        )}
        {/* Мини-график: форма движения важнее отдельных значений, поэтому без
            осей и подписей — они на такой высоте всё равно нечитаемы. */}
        {Array.isArray(data.spark) && data.spark.length > 1 && (
          <Sparkline values={data.spark as number[]} color={data.alert?.color || 'var(--accent)'} />
        )}
        <AggregateNote data={data} />
        <TargetLine data={data} />
      </div>
    )
  }
  if (data.type === 'gauge') {
    const max = data.max || 100
    const color = data.alert?.color || C.c1
    // Высота шкалы была константой 190px — и как только над ней встал бейдж
    // порога («⚠ план выполнен»), содержимое перестало помещаться и карточка
    // включила прокрутку. Тот же приём, что у динамики: ужимаем сам график.
    const opt: EChartsOption = {
      series: [{
        type: 'gauge', min: 0, max,
        progress: { show: true, width: 12, itemStyle: { color } },
        axisLine: { lineStyle: { width: 12, color: [[1, '#eef0f3']] } },
        axisTick: { show: false },
        // Делений пять, а не десять по умолчанию: на шкале 0…750 одиннадцать
        // подписей сливались в кашу по дуге.
        splitNumber: 5,
        splitLine: { length: 8, lineStyle: { color: '#c9ccd1' } },
        // Подписаны только КРАЯ шкалы. Радиус на карточке в треть ряда мал, и
        // промежуточные подписи наползали друг на друга у центра дуги; границы
        // дают тот же ориентир «сколько это по шкале», а само значение и так
        // напечатано под дугой.
        // Подписей делений на дуге нет. На карточке в треть ряда радиус мал:
        // внутри дуги они сходились к центру и слипались, снаружи наезжали на
        // само значение. Верх шкалы подписан ниже обычным текстом — там место
        // есть, и он не конкурирует с числом за одни и те же пиксели.
        axisLabel: { show: false },
        pointer: { itemStyle: { color } },
        title: { show: false },
        detail: {
          // Число сидело внутри дуги и налезало на подписи делений — при
          // трёхзначном проценте («656,87 %») перекрывало их полностью.
          // Уводим его ниже дуги; на ужатой карточке уменьшаем и шрифт.
          valueAnimation: true, fontSize: gaugeFit.h < 150 ? 16 : 20, fontWeight: 700,
          color, offsetCenter: [0, '86%'],
          formatter: (v: number) => fmt(v) + (data.unit ? ' ' + data.unit : ''),
        },
        data: [{ value: data.value ?? 0 }],
      }],
    }
    return (
      <div ref={gaugeFit.box}>
        <EChart option={P(opt)} height={gaugeFit.h} />
        <div ref={gaugeFit.labels} style={{ marginTop: -14 }}>
          {/* Шкалу подписываем, только когда она НЕ стандартная: у обычного
              процента верх 100 и так подразумевается, а вот 750 объясняет,
              почему дуга при 656 % не полна. */}
          {max !== 100 && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textAlign: 'center' }}>
              шкала 0…{fmt(max)}{data.unit ? ` ${data.unit}` : ''}
            </div>
          )}
          <AggregateNote data={data} />
          <TargetLine data={data} />
        </div>
      </div>
    )
  }
  if (data.type === 'plan_fact') {
    const pct = data.pct
    return (
      <div style={{ fontSize: 14 }}>
        <div style={{ display: 'flex', gap: 18 }}>
          <div><div style={muted}>План</div><b>{fmt(data.plan)}</b></div>
          <div><div style={muted}>Факт</div><b>{fmt(data.fact)}</b></div>
          <div><div style={muted}>Δ</div><b style={{ color: data.delta >= 0 ? 'var(--success)' : 'var(--danger)' }}>{data.delta >= 0 ? '+' : ''}{fmt(data.delta)}</b></div>
        </div>
        {pct != null && (
          <div style={{ marginTop: 8 }}>
            <div style={{ height: 10, background: 'var(--border-faint)', borderRadius: 6, overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(100, pct)}%`, height: '100%', background: data.alert?.color || (pct >= 100 ? 'var(--success)' : 'var(--accent)') }} />
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 2 }}>Выполнение: <b>{fmt(pct)}%</b></div>
          </div>
        )}
        {/* Прогноз даты достижения плана: линейная экстраполяция по среднему
            темпу между первым и последним отчётом. Метод назван прямо в
            подписи — цифра «когда» без объяснения «откуда» доверия не
            заслуживает, а руководитель по ней принимает решение. */}
        {data.forecast && <PlanForecast f={data.forecast} unit={data.unit} />}
      </div>
    )
  }
  if (data.type === 'table') {
    const cols: string[] = data.columns || []
    let rows: any[] = data.rows || []
    if (tableSearch.trim()) {
      const s = tableSearch.trim().toLowerCase()
      rows = rows.filter((r) => String(r.row ?? '').toLowerCase().includes(s) || cols.some((c) => String(r[c] ?? '').toLowerCase().includes(s)))
    }
    rows = sortRows(rows, tableSort, (r, c) => (c === '__row' ? r.row : r[c]))
    // В отчёте широкая таблица разворачивается ВЕРТИКАЛЬНО: показатель —
    // строкой, значения — столбцами. У госформы 15 граф, её естественная
    // ширина 1474px против 1000px листа: на экране это лечится прокруткой, а
    // в PDF половина столбцов просто пропала бы. Узкая таблица остаётся как есть.
    if (print && cols.length > 6) {
      return (
        <table style={{ borderCollapse: 'collapse', fontSize: 12.5, width: '100%' }}>
          <thead><tr>
            <th style={{ ...th, textAlign: 'left', width: '55%' }}>Показатель</th>
            {rows.map((r: any, i: number) => (
              <th key={i} style={{ ...th, textAlign: 'right' }}>{r.row}</th>
            ))}
          </tr></thead>
          <tbody>
            {cols.map((c: string) => (
              <tr key={c}>
                <td style={{ ...td, fontWeight: 600 }}>{(data.column_titles?.[c] as string) || c}</td>
                {rows.map((r: any, i: number) => (
                  <td key={i} style={{ ...td, textAlign: 'right' }}>
                    {typeof r[c] === 'number' ? fmt(r[c]) : (r[c] ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )
    }
    return (
      <div>
        {/* Поиск и подсказка про сортировку — инструменты экрана: в отчёте
            ими не воспользуешься, а место они занимают. */}
        <div data-export-hide style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <input style={searchInput} placeholder="🔍 Поиск по таблице…" value={tableSearch} onChange={(e) => setTableSearch(e.target.value)} />
          <span style={{ fontSize: 11, color: 'var(--text-faint)', marginBottom: 8 }}>
            клик по заголовку столбца сортирует: ▲ по возрастанию, ▼ по убыванию, третий клик — сброс
          </span>
        </div>
        {/* width:100% обязателен: без него контейнер растягивался под таблицу,
            прокрутка не включалась, и широкая таблица вылезала за карточку. */}
        <div style={{ overflowX: print ? 'visible' : 'auto', width: '100%', maxWidth: '100%' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
          <thead><tr>
            {/* Названия строк закреплены слева: при прокрутке вправо уезжали и
                они, и было не понять, к какой строке относятся числа. */}
            <th style={{ ...th, ...sortableTh, ...stickyCol, ...stickyHead }} title={SORT_HINT} onClick={() => toggleSort(setTableSort, '__row')}>Строка{sortArrow(tableSort, '__row')}</th>
            {/* Заголовок — человеческое имя показателя; код остаётся ключом
                данных и подсказкой, чтобы можно было сверить с формулой. */}
            {cols.map((c: string) => (
              <th key={c} style={{ ...th, ...sortableTh }} title={`${SORT_HINT}\nКод столбца: ${c}`}
                onClick={() => toggleSort(setTableSort, c)}>
                {(data.column_titles?.[c] as string) || c}{sortArrow(tableSort, c)}
              </th>
            ))}
          </tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td style={td} colSpan={cols.length + 1}>Ничего не найдено</td></tr>}
            {/* Клик по строке проваливает ВСЮ страницу в эту строку — тем же
                фильтром, что и клик по столбцу графика. Без этого таблица
                оставалась единственным местом, где строку видно, но нельзя
                выбрать: самый естественный жест не работал. */}
            {rows.map((r: any, i: number) => (
              <tr key={i} onClick={onPick && !print ? () => onPick(String(r.row)) : undefined}
                style={onPick && !print ? { cursor: 'pointer' } : undefined}
                title={onPick && !print ? `Показать всю страницу по строке «${r.row}»` : undefined}>
                <td style={{ ...td, fontWeight: 600, ...stickyCol,
                  ...(onPick && !print ? { color: 'var(--accent)' } : {}) }}>{r.row}</td>
                {cols.map((c: string) => <td key={c} style={td}>{typeof r[c] === 'number' ? fmt(r[c]) : (r[c] ?? '—')}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    )
  }
  if (data.type === 'dynamics') {
    const periods: string[] = data.periods || []
    if (periods.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных за период</div>
    // Индекс роста: бэкенд отдаёт готовый ряд (первая точка = 100 %), график
    // рисует его вместо абсолютных значений. Сами значения никуда не деваются —
    // они остаются в подсказке, иначе «сколько» ответить было бы негде.
    const idxVals: (number | null)[] | null = data.index_values || null
    const plotted: (number | null)[] = idxVals || data.values
    // Тренд и аномалии считаются в абсолютных величинах; индексирование —
    // умножение на постоянную, поэтому их достаточно масштабировать тем же
    // коэффициентом, а не пересчитывать (иначе линия тренда легла бы мимо ряда).
    const idxBase: number | null = idxVals ? ((data.values || []).find((v: number) => v) ?? null) : null
    const k = idxBase ? 100 / idxBase : 1
    const series: any[] = [{ type: 'line', name: idxVals ? 'Индекс роста, %' : 'Значение', data: plotted, smooth: true,
      color: C.c1, itemStyle: { color: C.c1 },
      lineStyle: { color: C.c1, width: 2 }, areaStyle: { opacity: 0.08 } }]
    // Линейный тренд (наложение): прямая по концам от бэкенда, интерполируем по периодам.
    if (data.trend && periods.length >= 2) {
      const [s, e] = data.trend
      const n = periods.length
      const line = periods.map((_, i) => (s + (e - s) * i / (n - 1)) * k)
      // 🔴 Цвет задаётся ряду ЦЕЛИКОМ, а не только линии. Раньше стоял один
      // lineStyle.color, а сам ряд оставался без цвета — и ECharts брал для
      // маркера в подсказке второй цвет своей палитры (синий), хотя линию
      // рисовал жёлтой. Подсказка показывала цвет, которого на графике нет.
      // Тон холодный и приглушённый намеренно: тренд — это РАСЧЁТ, а не данные,
      // он не должен спорить с фактом за внимание.
      series.push({ type: 'line', name: 'Тренд', data: line, smooth: false, symbol: 'none',
        color: C.trend, lineStyle: { color: C.trend, width: 2, type: 'dashed' } })
    }
    // Волна F: точки, отклонившиеся от тренда больше чем на N σ — красные маркеры поверх ряда.
    const anomalies: { index: number; period: string; value: number; expected: number; deviation: number }[] = data.anomalies || []
    if (anomalies.length > 0) {
      // Аномалия отличается не только цветом, но и ФОРМОЙ (ромб вместо круга) и
      // белой обводкой. Цветом одним обойтись нельзя: сигнальный красный и
      // фирменный красный факта — соседние оттенки, на карточке ниже 150px
      // легенда скрыта, а различать цвета умеют не все (дальтонизм ~8% мужчин).
      series.push({
        type: 'scatter', name: 'Аномалии', symbol: 'diamond', symbolSize: 14,
        color: C.signal,
        itemStyle: { color: C.signal, borderColor: '#fff', borderWidth: 2 },
        data: anomalies.map((a) => [a.index, a.value * k]),
      })
    }
    const vals: number[] = data.values || []
    // Легенда «Значение / Тренд / Аномалии» рисуется по нижнему краю и налезала
    // на повёрнутые подписи дат. Теперь под неё резервируется место, а на низком
    // графике она вовсе скрывается: пунктир тренда и красные точки аномалий
    // различимы и без подписи, а места на подписи дат не остаётся.
    const showLegend = (data.trend || anomalies.length > 0) && fit.h >= 150
    const opt: EChartsOption = {
      grid: { left: gridLeft(vals), right: 12, top: 12, bottom: showLegend ? 62 : 40 },
      // Под графиком помещается только последняя пара периодов, а изменение между
      // каждой парой («22.07 → 05.08») видно здесь: наводя на точку, пользователь
      // получает и значение, и прирост к предыдущему периоду.
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          const arr = Array.isArray(params) ? params : [params]
          const i = arr[0]?.dataIndex ?? 0
          const lines = [`<b>${fmtPeriod(periods[i])}</b>`]
          arr.forEach((p: any) => {
            const v = Array.isArray(p.value) ? p.value[1] : p.value
            // Само число красим в цвет ряда: на карточке легенды нет, и подсказка
            // остаётся единственным местом, где видно, «где что». Маленькой точки
            // рядом с названием для этого мало.
            if (v != null) lines.push(`${p.marker} ${p.seriesName}: <b style="color:${p.color}">${fmt(v)}${idxVals ? ' %' : ''}</b>`)
          })
          // При индексе на графике проценты, а «сколько на самом деле» спрашивают
          // тут же — абсолютное значение остаётся в подсказке.
          if (idxVals && vals[i] != null) lines.push(`<span style="color:#888">значение:</span> ${fmt(vals[i])}`)
          if (i > 0 && vals[i] != null && vals[i - 1] != null) {
            const d = vals[i] - vals[i - 1]
            const pct = vals[i - 1] ? (d / vals[i - 1]) * 100 : null
            lines.push(`<span style="color:#888">к ${fmtPeriod(periods[i - 1])}:</span> ${d >= 0 ? '+' : ''}${fmt(d)}${pct != null ? ` (${d >= 0 ? '+' : ''}${fmt(pct)}%)` : ''}`)
          }
          return lines.join('<br/>')
        },
      },
      legend: showLegend ? { bottom: 0, textStyle: { fontSize: 10 }, itemHeight: 8 } : undefined,
      xAxis: { type: 'category', data: periods.map(fmtPeriod), axisLabel: { rotate: 30, fontSize: 11 } },
      // На ужатом по высоте графике деления оси налезают друг на друга — при
      // малой высоте оставляем меньше делений.
      yAxis: { type: 'value', splitNumber: fit.h < 130 ? 3 : 5,
        ...(idxVals ? { axisLabel: { formatter: '{value} %' } } : {}) },
      series,
    }
    const ch = data.change
    const tot = data.total_change
    // Когда точек всего две, «за весь период» и «к пред. периоду» — одно и то же число:
    // вторую строку в этом случае не показываем, чтобы не дублировать.
    const showTotal = tot != null && (data.periods_count ?? 0) > 2
    return (
      <div ref={fit.box} style={{ height: '100%' }}>
        <EChart option={P(opt)} height={fit.h} />
        <div ref={fit.labels}>
        {idxVals && data.index_base_period && (
          <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 3 }}>
            индекс роста: {fmtPeriod(data.index_base_period)} = 100 %
          </div>
        )}
        {ch != null && (
          <div style={{ fontSize: 12.5, marginTop: 3, lineHeight: 1.35 }}>
            К пред.
            {data.change_to_period && (
              <span style={{ color: 'var(--text-muted)' }}> ({fmtPeriod(data.change_from_period)}→{fmtPeriod(data.change_to_period)})</span>
            )}: <b style={{ color: ch >= 0 ? 'var(--success)' : 'var(--danger)' }}>{ch >= 0 ? '↑ +' : '↓ '}{fmt(ch)}{data.change_pct != null ? ` (${fmt(data.change_pct)}%)` : ''}</b>
            {data.trend_slope != null && <span style={{ marginLeft: 10, color: 'var(--warn)' }}>тренд: <b>{data.trend_slope >= 0 ? '↗ рост' : '↘ спад'}</b> ({fmt(data.trend_slope)}/период)</span>}
          </div>
        )}
        {showTotal && (
          <div style={{ fontSize: 12.5, marginTop: 1, lineHeight: 1.35 }}
            title={`${fmt(data.first_value)} на ${fmtPeriod(data.first_period)} → ${fmt(data.last_value)} на ${fmtPeriod(data.last_period)}`}>
            Всего
            <span style={{ color: 'var(--text-muted)' }}> ({fmtPeriod(data.first_period)}→{fmtPeriod(data.last_period)}, точек: {data.periods_count})</span>
            : <b style={{ color: tot >= 0 ? 'var(--success)' : 'var(--danger)' }}>{tot >= 0 ? '↑ +' : '↓ '}{fmt(tot)}{data.total_change_pct != null ? ` (${fmt(data.total_change_pct)}%)` : ''}</b>
          </div>
        )}
        {data.anomaly_threshold != null && (
          anomalies.length > 0
            ? <div style={{ fontSize: 12, marginTop: 4, color: 'var(--danger)' }}>⚠ {anomalies.length} {anomalies.length === 1 ? 'аномалия' : 'аномалии(й)'}: {anomalies.map((a) => fmtPeriod(a.period)).join(', ')}</div>
            : <div style={{ fontSize: 12, marginTop: 4, color: 'var(--text-muted)' }}>Аномалий не обнаружено (порог {data.anomaly_threshold}σ)</div>
        )}
        </div>
      </div>
    )
  }

  if (data.type === 'yoy') {
    // Год к году: текущий год (сплошная) против прошлого (пунктир) по месяцам.
    const months: string[] = data.months || []
    if (months.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
    const series: any[] = [] // eslint-disable-line @typescript-eslint/no-explicit-any
    if (data.previous_year != null) {
      series.push({ type: 'line', name: String(data.previous_year), data: data.previous, smooth: true, symbol: 'circle', symbolSize: 5,
        color: C.prev, itemStyle: { color: C.prev }, lineStyle: { color: C.prev, width: 2, type: 'dashed' } })
    }
    series.push({ type: 'line', name: String(data.current_year), data: data.current, smooth: true, symbol: 'circle', symbolSize: 5,
      color: C.c1, itemStyle: { color: C.c1 }, lineStyle: { color: C.c1, width: 2.5 }, areaStyle: { opacity: 0.08 } })
    // У «Года к году» легенда (два года) нужна всегда — резервируем под неё место,
    // иначе она ложится на подписи месяцев.
    const opt: EChartsOption = {
      grid: { left: 44, right: 12, top: 12, bottom: 56 },
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0, textStyle: { fontSize: 11 } },
      xAxis: { type: 'category', data: months, axisLabel: { fontSize: 11 } },
      yAxis: { type: 'value' },
      series,
    }
    const ch = data.change
    return (
      <div>
        <EChart option={P(opt)} height={196} />
        {ch != null ? (
          <div style={{ fontSize: 13, marginTop: 4 }}>
            К {data.previous_year} г. (сопоставимые месяцы: {data.compared_months}): <b style={{ color: ch >= 0 ? 'var(--success)' : 'var(--danger)' }}>
              {ch >= 0 ? '↑ +' : '↓ '}{fmt(ch)}{data.change_pct != null ? ` (${fmt(data.change_pct)}%)` : ''}{data.unit ? ` ${data.unit}` : ''}</b>
          </div>
        ) : (
          <div style={{ fontSize: 13, marginTop: 4, color: 'var(--text-muted)' }}>Нет данных за прошлый год — сравнение появится, когда будут данные двух лет.</div>
        )}
      </div>
    )
  }

  if (data.type === 'compare' || data.type === 'cross_dataset_compare') {
    const cats: string[] = data.categories || []
    if (cats.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
    // Показатели одной формы называются по шаблону «Количество … · Факт ·
    // нарастающим итогом»: в легенде от них остаётся одинаковое начало и конец,
    // а различие — в середине. Отсекаем общую часть, чтобы подписи различались.
    const allValues: number[] = (data.series || []).flatMap((x: any) => (x.data || []).filter((v: any) => typeof v === 'number'))
    const { helps: logHelps, spread } = logScaleAdvice(allValues)
    // cfg.scale: 'log' | 'linear' | не задано (тогда решает разброс значений)
    const useLog = data.scale === 'log' || (data.scale !== 'linear' && logHelps)
    const seriesNames: string[] = (data.series || []).map((s: any) => s.name)
    const shortened = distinctLabels(seriesNames)
    const shortSeries: Record<string, string> = {}
    seriesNames.forEach((n, i) => { shortSeries[n] = shortened[i] })
    // Снизу претендуют двое: повёрнутые подписи категорий и легенда серий —
    // раньше они делили одно место и наезжали друг на друга. Теперь под каждое
    // резервируется своя полоса, а на низкой карточке легенда убирается совсем:
    // категории важнее, цвета серий читаются по подсказке при наведении.
    // Поворачиваем подписи категорий, только когда их несколько: единственная
    // повёрнутая подпись уходит влево и наезжает на ось значений.
    const singleCat = cats.length === 1
    const rotated = cats.length > 1 && cats.some((c) => c.length > 6)
    // Единственная длинная подпись («Донецкая Народная Республика») шире узкой
    // карточки и вылезала за края графика — переносим её по словам.
    const wrapSingle = cats.length === 1 && cats[0].length > 14
    // В отчёте легенда развёрнута: каждый показатель на своей строке, а имена
    // госформ длинные. Значит под неё нужно РЕЗЕРВИРОВАТЬ место, иначе она
    // ложится поверх столбиков — график становится нечитаемым (проверено на
    // форме из 13 показателей).
    // Шаг строки легенды: высота значка (14) + itemGap (8). Замер на форме из
    // 13 показателей: 276px на 13 строк, то есть 21,3 на строку — прежние 17
    // занижали резерв на 44px, легенда поднималась ВЫШЕ оси и накрывала подпись
    // категории. Лучше зарезервировать с запасом (внизу останется белое поле),
    // чем недобрать: недобор — это наложение.
    const printLegendH = print ? Math.max(1, seriesNames.length) * 22 + 12 : 0
    const legendRoom = 22
    // Полоса, в которую переносится единственная длинная подпись. На карточке
    // она узкая поневоле (130px, и «Донецкая Народная Республика» встаёт в три
    // строки), а в отчёте лист широкий — там та же подпись помещается в ОДНУ
    // строку, и наезжать ей уже не на что. Ширину задаём явно, а не считаем
    // строки: как именно ECharts переносит по словам, снаружи не воспроизвести
    // (замер показал три строки там, где расчёт давал две), а ошибка в этой
    // оценке — это наложение текста поверх текста.
    const catLabelW = print ? 460 : 130
    const catsRoom = (rotated ? 58 : wrapSingle ? 44 : 30) + (print ? 14 : 0)
    const showLegend = seriesNames.length > 1 && fit.h >= 170
    const opt: EChartsOption = {
      grid: { left: gridLeft((data.series || []).flatMap((x: any) => x.data || [])), right: 12, top: 12,
        bottom: catsRoom + (print ? printLegendH : showLegend ? legendRoom : 0) },
      // У столбиков подсказка — про ТОТ столбик, на который навели. При
      // trigger:'axis' ECharts вываливал список всех показателей сразу: на
      // форме из четырнадцати граф это простыня во весь экран, в которой
      // нужное число ещё надо найти. У линии осевая подсказка уместна — там
      // сравнение серий в одной точке и есть смысл графика.
      tooltip: data.viz === 'line' ? { trigger: 'axis' } : { trigger: 'item' },
      // Имена показателей одной формы совпадают началом и концом, поэтому в
      // легенде показываем только различающую часть (distinctLabels), а полное
      // имя остаётся в подсказке. Прокрутка — чтобы 5–6 показателей не съели график.
      // В отчёте легенда развёрнута и с полными именами: в PDF её не
      // пролистаешь, а «1/13» на экране означало бы, что 12 показателей из 13
      // остались без подписи цвета.
      legend: showLegend || print
        ? print
          ? { bottom: 0, type: 'plain', textStyle: { fontSize: 11 }, itemGap: 8,
              formatter: (name: string) => shortSeries[name] || name }
          : { bottom: 0, type: 'scroll', textStyle: { fontSize: 11 },
              formatter: (name: string) => elideMiddle(shortSeries[name] || name, 38) }
        : undefined,
      xAxis: { type: 'category', data: cats,
        axisLabel: {
          interval: 0, rotate: rotated ? 30 : 0, fontSize: 11, hideOverlap: true,
          ...(wrapSingle ? { width: catLabelW, overflow: 'break' as const } : {}),
          formatter: (v: string) => (wrapSingle ? v : elideMiddle(v, 28)),
        } },
      // На ужатом графике пять делений оси налезают друг на друга — оставляем меньше.
      // Логарифмическая шкала — когда показатели различаются на два порядка:
      // на линейной маленькие столбики вырождаются в полоску у нуля. Точные
      // числа подписаны у столбиков, потому что на логарифме длина обманчива.
      // Границы лог-шкалы задаём по данным: без них ECharts растягивает ось до
      // ближайших степеней десятки (при максимуме 2,3 млн верхнее деление
      // оказывалось 10 000 000 000) и столбики жмутся к низу.
      yAxis: useLog
        ? {
            type: 'log', splitNumber: fit.h < 140 ? 2 : 3,
            min: logBound(allValues, 'min'), max: logBound(allValues, 'max'),
          }
        : { type: 'value', splitNumber: fit.h < 140 ? 2 : fit.h < 200 ? 3 : 5 },
      series: (data.series || []).map((s: any, i: number) => ({
        name: s.name, type: data.viz === 'line' ? 'line' : 'bar', data: s.data,
        smooth: data.viz === 'line', itemStyle: { color: C.palette[i % C.palette.length] },
        // Ширина и зазоры зависят от числа категорий. При ОДНОЙ строке (частый
        // случай: сводная форма по одному субъекту) все показатели попадают в
        // единственную группу — с общим ограничением 28px они сбивались в
        // узкий пучок посреди пустой карточки. Даём им занять ширину: группа
        // почти на весь слот категории, между столбиками видимый зазор.
        barMaxWidth: singleCat ? 52 : 28,
        ...(singleCat ? { barGap: '40%', barCategoryGap: '5%' } : {}),
        // На логарифме длина столбика обманчива — подписываем точное число.
        label: useLog && data.viz !== 'line'
          ? { show: true, position: 'top', fontSize: 10, formatter: (p: any) => fmt(p.value) }
          : undefined,
      })),
    }
    return (
      <div ref={fit.box} style={{ height: '100%' }}>
        {/* Высота растёт на высоту легенды: сам график от этого не ужимается. */}
        <EChart option={P(opt)} height={fit.h + printLegendH} onPick={onPick} />
        <div ref={fit.labels}>
          {/* Индекс роста: на оси проценты, а не величины — без подписи график
              выглядел бы как «все ряды около сотни» без объяснения почему. */}
          {data.growth_index && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
              Индекс роста: у каждого источника первая точка = 100 %, дальше — рост в процентах к ней.
            </div>
          )}
          {useLog && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
              {logHelps
                ? `Логарифмическая шкала: значения различаются в ${fmt(Math.round(spread))} раз — на обычной маленькие показатели не видны.`
                : 'Логарифмическая шкала (выбрана в настройках виджета).'}
              {' '}Точные числа подписаны у столбиков.
            </div>
          )}
        </div>
      </div>
    )
  }

  if (data.type === 'heatmap') {
    const rows: string[] = data.rows || []
    const cols: string[] = data.columns || []
    const cells: number[][] = data.cells || []
    if (rows.length === 0 || cols.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
    const longX = cols.some((c) => c.length > 6)
    const opt: EChartsOption = {
      tooltip: { position: 'top', formatter: (p: any) => `${cols[p.value[0]]} · ${rows[p.value[1]]}: <b>${fmt(p.value[2])}</b>` },
      grid: { left: 8, right: 12, top: 10, bottom: longX ? 58 : 44, containLabel: true },
      xAxis: { type: 'category', data: cols, splitArea: { show: true }, axisLabel: { fontSize: 11, interval: 0, rotate: longX ? 30 : 0 } },
      yAxis: { type: 'category', data: rows, splitArea: { show: true }, axisLabel: { fontSize: 11, interval: 0 } },
      visualMap: { min: data.min ?? 0, max: data.max || 1, calculable: true, orient: 'horizontal', left: 'center', bottom: 0,
        itemHeight: 80, textStyle: { fontSize: 10 }, inRange: { color: C.heat } },
      series: [{ type: 'heatmap', data: cells, label: { show: rows.length * cols.length <= 60, fontSize: 10, formatter: (p: any) => fmt(p.value[2]) },
        emphasis: { itemStyle: { shadowBlur: 6, shadowColor: 'rgba(0,0,0,0.3)' } } }],
    }
    const h = Math.min(380, Math.max(200, rows.length * 26 + (longX ? 96 : 82)))
    return <EChart option={P(opt)} height={h} />
  }

  if (data.type === 'matrix') {
    // Матрица «строка × отчётная дата». Значение крупно, прирост к прошлому
    // отчёту — мелким шрифтом ПОД ним: в одной ячейке помещаются оба ответа
    // («сколько» и «лучше или хуже»), и глазами не приходится вычитать
    // соседние столбцы. Первая колонка закреплена — иначе при прокрутке
    // вправо непонятно, чья это строка (тот же приём, что в таблице).
    const periods: string[] = data.periods || []
    let rows: any[] = data.rows || []
    if (rows.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных за период</div>
    const mVal = (r: any, col: string) => (col === '__row' ? r.row : col === '__chg' ? r.total_change : r.values[Number(col)])
    rows = sortRows(rows, matrixSort, mVal)
    const totCell: React.CSSProperties = { ...td, fontWeight: 700, background: 'var(--surface-accent)' }
    return (
      <div>
        <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginBottom: 4 }}>
          {data.field_title}
          {data.total_periods > data.shown_periods
            ? ` · показаны последние ${data.shown_periods} отчётов из ${data.total_periods}`
            : ` · отчётов: ${data.shown_periods}`}
        </div>
        <div style={{ overflowX: print ? 'visible' : 'auto', width: '100%', maxWidth: '100%' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
          <thead><tr>
            <th style={{ ...th, ...sortableTh, ...stickyCol, ...stickyHead }} title={SORT_HINT}
              onClick={() => toggleSort(setMatrixSort, '__row')}>Строка{sortArrow(matrixSort, '__row')}</th>
            {periods.map((p, i) => (
              <th key={p + i} style={{ ...th, ...sortableTh, textAlign: 'right' }} title={SORT_HINT}
                onClick={() => toggleSort(setMatrixSort, String(i))}>{fmtPeriod(p)}{sortArrow(matrixSort, String(i))}</th>
            ))}
            <th style={{ ...th, ...sortableTh, textAlign: 'right', color: 'var(--accent)' }} title={SORT_HINT}
              onClick={() => toggleSort(setMatrixSort, '__chg')}>За период{sortArrow(matrixSort, '__chg')}</th>
          </tr></thead>
          <tbody>
            {rows.map((r: any, i: number) => (
              <tr key={i} onClick={onPick && !print ? () => onPick(String(r.row)) : undefined}
                style={onPick && !print ? { cursor: 'pointer' } : undefined}
                title={onPick && !print ? `Показать всю страницу по строке «${r.row}»` : undefined}>
                <td style={{ ...td, fontWeight: 600, ...stickyCol,
                  ...(onPick && !print ? { color: 'var(--accent)' } : {}) }}>{r.row}</td>
                {periods.map((_p, ci) => {
                  const v = r.values[ci]
                  const d = r.deltas?.[ci]
                  const dp = r.delta_pcts?.[ci]
                  return (
                    <td key={ci} style={{ ...td, textAlign: 'right', whiteSpace: 'nowrap' }}>
                      <div>{typeof v === 'number' ? fmt(v) : '—'}</div>
                      {typeof d === 'number' && d !== 0 && (
                        <div style={{ fontSize: 10.5, color: d > 0 ? 'var(--success)' : 'var(--danger)' }}
                          title={`Изменение к прошлому отчёту: ${d > 0 ? '+' : ''}${fmt(d)}`}>
                          {d > 0 ? '▲ +' : '▼ '}{fmt(d)}{typeof dp === 'number' ? ` (${dp > 0 ? '+' : ''}${fmt(dp)} %)` : ''}
                        </div>
                      )}
                    </td>
                  )
                })}
                <td style={{ ...totCell, textAlign: 'right', whiteSpace: 'nowrap',
                  color: typeof r.total_change === 'number' ? (r.total_change >= 0 ? 'var(--success)' : 'var(--danger)') : undefined }}
                  title="Изменение от первого показанного отчёта к последнему">
                  {typeof r.total_change === 'number' ? `${r.total_change > 0 ? '+' : ''}${fmt(r.total_change)}` : '—'}
                  {typeof r.total_change_pct === 'number' && (
                    <div style={{ fontSize: 10.5 }}>{r.total_change_pct > 0 ? '+' : ''}{fmt(r.total_change_pct)} %</div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
          {/* Итог по столбцу показываем, только когда строк больше одной:
              у формы с единственной строкой он дословно повторял бы её. */}
          {rows.length > 1 && (
            <tfoot><tr>
              <td style={{ ...totCell, ...stickyCol, background: 'var(--surface-2)' }}>Итого</td>
              {(data.col_totals || []).map((v: number | null, i: number) => (
                <td key={i} style={{ ...totCell, textAlign: 'right' }}>{typeof v === 'number' ? fmt(v) : '—'}</td>
              ))}
              <td style={totCell} />
            </tr></tfoot>
          )}
        </table>
        </div>
      </div>
    )
  }

  if (data.type === 'pivot') {
    const cols: string[] = data.columns || []
    let rows: any[] = data.rows || []
    if (rows.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
    const totCell: React.CSSProperties = { ...td, fontWeight: 700, background: 'var(--surface-accent)' }
    if (pivotSearch.trim()) {
      const s = pivotSearch.trim().toLowerCase()
      rows = rows.filter((r) => String(r.row ?? '').toLowerCase().includes(s) || (r.values || []).some((v: unknown) => String(v ?? '').toLowerCase().includes(s)))
    }
    const pivotVal = (r: any, col: string) => (col === '__row' ? r.row : col === '__total' ? r.total : r.values[Number(col)])
    rows = sortRows(rows, pivotSort, pivotVal)
    return (
      <div>
        <input style={searchInput} placeholder="🔍 Поиск по сводной…" value={pivotSearch} onChange={(e) => setPivotSearch(e.target.value)} />
        <div style={{ overflowX: print ? 'visible' : 'auto', width: '100%', maxWidth: '100%' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
          <thead><tr>
            <th style={{ ...th, ...sortableTh, ...stickyCol, ...stickyHead }} title={SORT_HINT} onClick={() => toggleSort(setPivotSort, '__row')}>Строка{sortArrow(pivotSort, '__row')}</th>
            {cols.map((c, ci) => <th key={c} style={{ ...th, ...sortableTh }} title={SORT_HINT} onClick={() => toggleSort(setPivotSort, String(ci))}>{c}{sortArrow(pivotSort, String(ci))}</th>)}
            <th style={{ ...th, ...sortableTh, color: 'var(--accent)' }} title={SORT_HINT} onClick={() => toggleSort(setPivotSort, '__total')}>Итого{sortArrow(pivotSort, '__total')}</th>
          </tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td style={td} colSpan={cols.length + 2}>Ничего не найдено</td></tr>}
            {/* Строка сводной кликается так же, как строка обычной таблицы. */}
            {rows.map((r, i) => (
              <tr key={i} onClick={onPick && !print ? () => onPick(String(r.row)) : undefined}
                style={onPick && !print ? { cursor: 'pointer' } : undefined}
                title={onPick && !print ? `Показать всю страницу по строке «${r.row}»` : undefined}>
                <td style={{ ...td, fontWeight: 600, ...stickyCol,
                  ...(onPick && !print ? { color: 'var(--accent)' } : {}) }}>{r.row}</td>
                {cols.map((_, ci) => <td key={ci} style={{ ...td, textAlign: 'right' }}>{typeof r.values[ci] === 'number' ? fmt(r.values[ci]) : '—'}</td>)}
                <td style={{ ...totCell, textAlign: 'right' }}>{fmt(r.total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr><td style={{ ...totCell, ...stickyCol, background: 'var(--surface-2)' }}>Итого</td>
            {(data.col_totals || []).map((v: number, i: number) => <td key={i} style={{ ...totCell, textAlign: 'right' }}>{fmt(v)}</td>)}
            <td style={{ ...totCell, textAlign: 'right', color: 'var(--accent)' }}>{fmt(data.grand_total)}</td>
          </tr></tfoot>
        </table>
        </div>
      </div>
    )
  }

  if (data.type === 'funnel') {
    // Воронка своими полосами, а не графиком ECharts: главное здесь — не форма
    // трапеции, а ПОДПИСЬ между этапами («дошли 92,3 %»). У воронки ECharts
    // такой подписи нет, пришлось бы рисовать её вторым слоем поверх канваса.
    const stages: any[] = data.stages || []
    const max = Math.max(1, ...stages.map((s) => s.value || 0))
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {stages.map((s, i) => {
          const width = Math.max(6, ((s.value || 0) / max) * 100)
          const drop = s.pct_of_prev != null && s.pct_of_prev < 100
          return (
            <div key={s.field || i}>
              {/* Переход с предыдущего этапа: где именно теряются — ради этого
                  воронку и смотрят, поэтому потеря названа числом и людьми. */}
              {i > 0 && s.pct_of_prev != null && (
                <div style={{ fontSize: 11, color: drop ? 'var(--warn)' : 'var(--success)', margin: '1px 0 1px 2px' }}
                  title={s.lost != null ? `Потеря на этом шаге: ${fmt(s.lost)}` : undefined}>
                  ↓ дошли {fmt(s.pct_of_prev)} %{s.lost ? ` · минус ${fmt(s.lost)}` : ''}
                </div>
              )}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 11.5, color: 'var(--text-2)', overflow: 'hidden',
                                textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={s.name}>{s.name}</div>
                  <div style={{ height: 16, background: 'var(--border-faint)', borderRadius: 4, overflow: 'hidden' }}>
                    <div style={{ width: `${width}%`, height: '100%', background: C.palette[i % C.palette.length],
                                  borderRadius: 4, transition: 'width .4s ease' }} />
                  </div>
                </div>
                <div style={{ fontSize: 13, fontWeight: 700, minWidth: 64, textAlign: 'right' }}>{fmt(s.value)}</div>
              </div>
            </div>
          )
        })}
        {/* Сквозная конверсия: сколько дошло от первого этапа до последнего. */}
        {stages.length > 2 && stages[stages.length - 1].pct_of_first != null && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
            От первого этапа до последнего дошли <b>{fmt(stages[stages.length - 1].pct_of_first)} %</b>
          </div>
        )}
      </div>
    )
  }

  if (data.type === 'status_grid') {
    // «Светофор»: плитка на строку формы. Читается как список «у кого плохо»,
    // а не как таблица, которую надо просматривать числом за числом.
    const cells: any[] = data.cells || []
    if (!cells.length) return <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Нет строк для показа</div>
    return (
      <div style={{ display: 'grid', gap: 6, gridTemplateColumns: 'repeat(auto-fill, minmax(132px, 1fr))' }}>
        {cells.map((c, i) => (
          <div key={c.label || i}
            title={c.plan != null ? `План: ${fmt(c.plan)} · факт: ${fmt(c.value)}` : String(c.label)}
            style={{
              border: `1px solid ${c.color || 'var(--border)'}`,
              // Заливку даём только сработавшему порогу: если раскрасить всё,
              // цвет перестанет означать «сюда посмотри».
              background: c.color ? `${c.color}14` : 'var(--surface-2)',
              borderRadius: 8, padding: '6px 8px',
            }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', overflow: 'hidden',
                          textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.label}</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: c.color || 'var(--text)' }}>
              {data.compared_to_plan && c.pct != null ? `${fmt(c.pct)} %` : fmt(c.value)}
            </div>
            {data.compared_to_plan && c.pct != null && (
              <div style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
                {fmt(c.value)} из {fmt(c.plan)}
              </div>
            )}
          </div>
        ))}
      </div>
    )
  }

  if (data.type === 'waterfall') {
    const cats: string[] = data.categories || []
    if (cats.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
    const vals: number[] = (data.values || []).map((x: any) => (x == null ? 0 : x))
    const total = vals.reduce((a, b) => a + b, 0)
    const catAll = [...cats, data.total_label || 'Итого']
    const placeholder: number[] = []
    const bars: any[] = []
    let run = 0
    vals.forEach((x) => { placeholder.push(x >= 0 ? run : run + x); bars.push({ value: Math.abs(x), itemStyle: { color: x >= 0 ? '#0f6e56' : '#a3532d' } }); run += x })
    placeholder.push(0); bars.push({ value: total, itemStyle: { color: C.c1 } })
    const longX = catAll.some((c) => c.length > 6)
    const opt: EChartsOption = {
      grid: { left: 44, right: 12, top: 12, bottom: longX ? 56 : 40 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (p: any) => { const i = p[0].dataIndex; const v = i < vals.length ? vals[i] : total; return `${catAll[i]}: <b>${fmt(v)}</b>` } },
      xAxis: { type: 'category', data: catAll, axisLabel: { interval: 0, rotate: longX ? 30 : 0, fontSize: 11 } },
      yAxis: { type: 'value' },
      series: [
        { type: 'bar', stack: 'wf', itemStyle: { color: 'transparent' }, emphasis: { itemStyle: { color: 'transparent' } }, data: placeholder, silent: true },
        { type: 'bar', stack: 'wf', data: bars, barMaxWidth: 40, label: { show: true, position: 'top', fontSize: 10, formatter: (p: any) => fmt(p.dataIndex < vals.length ? vals[p.dataIndex] : total) } },
      ],
    }
    return <EChart option={P(opt)} height={220} />
  }

  if (data.type === 'objects_compare') {
    const cats: string[] = data.categories || []
    if (cats.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных по объектам для этого показателя</div>
    const longX = cats.some((c) => c.length > 6)
    const opt: EChartsOption = {
      grid: { left: 44, right: 12, top: 14, bottom: longX ? 60 : 40 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'category', data: cats, axisLabel: { interval: 0, rotate: longX ? 30 : 0, fontSize: 11 } },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', barMaxWidth: 44, label: { show: true, position: 'top', fontSize: 11, formatter: (p: any) => fmt(p.value) },
        data: (data.values || []).map((v: number, i: number) => ({ value: v, itemStyle: { color: C.palette[i % C.palette.length] } })) }],
    }
    return <EChart option={P(opt)} height={220} onPick={onPick} />
  }

  // bar | line | pie
  if ((data.categories || []).length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
  return <EChart option={P(chartOption(data))} height={200} onPick={onPick} />
}

function DrillModal({ drill, onClose }: { drill: any; onClose: () => void }) {
  // Портал в body обязателен: сетка дашборда (react-grid-layout) двигает
  // виджеты CSS-трансформацией, а внутри трансформированного предка
  // position:fixed отсчитывается от НЕГО, а не от окна. Окно «подробнее»
  // оказывалось внутри карточки, обрезалось её overflow:hidden — вместе с
  // крестиком, и закрыть его было нечем.
  return createPortal((
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Из чего собран: {drill.widget}</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>

        {drill.metrics?.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={secH}>Формулы метрик</div>
            {drill.metrics.map((m: any) => (
              <div key={m.code} style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{m.name} <span style={{ color: '#9aa4b2', fontWeight: 400 }}>({m.code} · v{m.version_no} · {m.status})</span></div>
                <div style={mono}>{m.formula}</div>
                {/* Расширенная информация по показателю (FR-5.9): текст модератора или заглушка */}
                {'info_text' in m && (
                  <div style={{ fontSize: 12, marginTop: 4, padding: '6px 8px', borderRadius: 6, background: m.info_text ? '#f4f7fb' : '#fafafa', color: m.info_text ? '#374151' : '#9aa4b2', whiteSpace: 'pre-wrap' }}>
                    {m.info_text ? m.info_text : 'Информации нет, в разработке.'}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div style={secH}>Первичные данные {drill.datasets?.length ? `(датасеты: ${drill.datasets.join(', ')})` : ''}</div>
        {(drill.datasets || []).length === 0 && <div style={muted}>Источники-датасеты не заданы.</div>}
        {(drill.datasets || []).map((dc: string) => {
          const t = drill.tables[dc]
          return (
            <div key={dc} style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Датасет «{dc}»</div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', fontSize: 12, width: '100%' }}>
                  <thead><tr><th style={th}>Строка</th>
                    {t.columns.map((c: string) => (
                      <th key={c} style={th} title={c}>{t.column_titles?.[c] || c}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {t.rows.map((r: any, i: number) => (
                      <tr key={i}><td style={{ ...td, fontWeight: 600 }}>{r.row}</td>
                        {t.columns.map((c: string) => <td key={c} style={td}>{typeof r[c] === 'number' ? fmt(r[c]) : (r[c] ?? '—')}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  ), document.body)
}

const muted: React.CSSProperties = { fontSize: 11, color: 'var(--text-faint)' }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 12, padding: '6px 8px', borderRadius: 6 }
const th: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '4px 8px', background: 'var(--surface-2)', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600 }
const td: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '4px 8px' }
const drillBtn: React.CSSProperties = { marginTop: 8, border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: 0 }
const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60, padding: 20 }
const dialog: React.CSSProperties = { background: 'var(--surface)', borderRadius: 14, padding: 22, width: 560, maxWidth: '92vw', maxHeight: '85vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }
const secH: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: 'var(--accent)', marginBottom: 6 }
const mono: React.CSSProperties = { fontFamily: 'ui-monospace, monospace', fontSize: 12, background: 'var(--surface-2)', padding: '6px 8px', borderRadius: 6, overflowX: 'auto' }
const rmBtn: React.CSSProperties = { width: 26, height: 26, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', cursor: 'pointer', color: 'var(--text-muted)' }
