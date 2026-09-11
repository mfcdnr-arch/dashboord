import { useEffect, useRef } from 'react'
// Модульная сборка echarts: регистрируем только используемые типы графиков и
// компоненты — так чанк echarts заметно меньше (важно для слабого железа/LAN МФЦ).
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, GaugeChart, HeatmapChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent, VisualMapComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts' // только тип (стирается при сборке)
// Русская запись чисел — та же, что во всей системе (см. lib/format).
import { fmtNumber } from '../lib/format'

// SVG-рендерер (а не Canvas): графики — векторные. Причины для гос-он-прем (Astra):
// не зависим от canvas, чётко при печати/PDF, работает в любом браузере с SVG.
// ScatterChart — маркеры аномалий (волна F) поверх линии «Динамика».
echarts.use([BarChart, LineChart, PieChart, GaugeChart, HeatmapChart, ScatterChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, VisualMapComponent, SVGRenderer])

// ECharts рисует на canvas и НЕ понимает CSS-переменные, поэтому значения тем
// (цвет текста/осей) читаем из токенов через getComputedStyle и подставляем
// в option. Тексты осей/легенды без явного цвета наследуют textStyle.color.
function themeDefaults(): EChartsOption {
  const cs = getComputedStyle(document.documentElement)
  const muted = cs.getPropertyValue('--text-muted').trim() || '#6b7280'
  return { textStyle: { color: muted } }
}

/**
 * Оси и подписи значений — цветом ТЕМЫ, а не умолчаниями ECharts.
 *
 * 🔴 `textStyle` наследуют не все элементы: подписи столбиков рисовались `#333`,
 * а деления осей — `#6E7079`. В светлой теме это сходит с рук, а в тёмной текст
 * оказывается почти на фоне (контраст около 1.5:1) — числа над столбиками
 * прочитать нельзя. Правим в ОДНОМ месте, чтобы про это не пришлось помнить
 * при каждом новом типе виджета.
 *
 * Заданное явно не трогаем (`...` идёт ПОСЛЕ умолчания): у спидометра своя
 * шкала, у тепловой карты свои цвета — они должны остаться как есть.
 */
export function withThemedText(option: EChartsOption): EChartsOption {
  const cs = getComputedStyle(document.documentElement)
  const tok = (name: string, fb: string) => cs.getPropertyValue(name).trim() || fb
  const muted = tok('--text-muted', '#6b7280')
  const text = tok('--text-2', tok('--text', '#333'))
  const line = tok('--border', '#e5e7eb')
  const faint = tok('--border-faint', '#f1f5f9')

  type Ax = Record<string, unknown>
  const axis = (a: Ax): Ax => {
    const given = (a.axisLabel as Ax) || {}
    // Числа на оси печатались по умолчанию ECharts — «1,000» вместо «1 000»,
    // хотя ВЕЗДЕ в системе они русские (`fmtNumber`). На одном экране рядом
    // оказывались две записи одного числа. Формат добавляется только оси
    // ЗНАЧЕНИЙ и только там, где свой форматтер не задан: у категорий на оси
    // подписи, а не числа, и трогать их нечем.
    const needsNumberFormat = a.type === 'value' && given.formatter === undefined
    return {
      ...a,
      axisLabel: {
        color: muted,
        ...(needsNumberFormat ? { formatter: (v: number) => fmtNumber(v) } : {}),
        ...given,
      },
      axisLine: a.axisLine ?? { lineStyle: { color: line } },
      splitLine: a.splitLine ?? { lineStyle: { color: faint } },
    }
  }
  const eachAxis = (ax: unknown) =>
    Array.isArray(ax) ? ax.map((a) => axis(a as Ax)) : ax ? axis(ax as Ax) : ax

  const o = option as Record<string, unknown>
  const series = Array.isArray(o.series)
    ? o.series.map((sr) => {
        const one = sr as Ax
        return one?.label ? { ...one, label: { color: text, ...(one.label as Ax) } } : one
      })
    : o.series

  return {
    ...option,
    ...(o.xAxis ? { xAxis: eachAxis(o.xAxis) } : {}),
    ...(o.yAxis ? { yAxis: eachAxis(o.yAxis) } : {}),
    ...(series ? { series } : {}),
    ...(o.legend ? { legend: { textStyle: { color: muted }, ...(o.legend as Ax) } } : {}),
  } as EChartsOption
}

// Подсказка при наведении рисуется ВНУТРИ контейнера графика, а карточка виджета
// обрезает всё, что вылезло за её край (overflow: hidden) — у узких карточек от
// подсказки оставалась половина слова. Выносим её в body, как уже сделано для
// окна «подробнее» и значка ⓘ. Свойство добавляется автоматически всем графикам,
// чтобы про него не пришлось помнить при каждом новом типе виджета.
// confine — держит подсказку в пределах окна: вынесенная в body, она иначе
// уезжает за левый/верхний край экрана, и часть текста прочитать невозможно.
function withDetachedTooltip(option: EChartsOption): EChartsOption {
  const tip = (option as { tooltip?: Record<string, unknown> }).tooltip
  if (!tip) return option
  return {
    ...option,
    tooltip: {
      appendToBody: true, confine: true,
      // Длинные имена показателей госформ не должны растягивать подсказку на
      // весь экран — переносим их по словам.
      extraCssText: 'max-width:min(460px,90vw);white-space:normal;',
      ...tip,
    },
  } as EChartsOption
}

/**
 * CSS-переменные в опциях графика заменяются НАСТОЯЩИМИ цветами.
 *
 * 🔴 Обычное состояние обманчиво: `fill="var(--alert-good)"` в SVG работает —
 * переменную разрешает сам браузер, и столбик зелёный. А при НАВЕДЕНИИ цвет
 * подсветки ECharts вычисляет САМ, осветляя базовый, и строку `var(...)` его
 * разборщик не понимает. Замер на самой библиотеке (zrender/tool/color):
 * `lift('#0f6e56', -0.1)` → `'rgba(16,121,94,1)'`, а `lift('var(--alert-good)',
 * -0.1)` → **undefined**. То есть столбик под курсором красится НИЧЕМ и просто
 * исчезает — ровно это и было видно на водопаде «вклад периодов»: столбик
 * итога с настоящим `#e04e39` наведение переживал, а столбики периодов с
 * `var(--alert-good)` пропадали, и соседний плавающий столбик повисал в
 * воздухе, будто нарисован неверно.
 *
 * Правило «ECharts не понимает var()» в проекте записано давно (theme.ts), но
 * помнить его при каждом новом виджете нельзя — поэтому подстановка живёт
 * ЗДЕСЬ, рядом с цветом текста и подсказками, и покрывает любой график разом.
 *
 * Значение возвращается ТЕМ ЖЕ объектом, если заменять нечего: опция
 * пересобирается на каждую перерисовку, и лишние копии массивов данных
 * (у теплокарты их тысячи) ни к чему.
 */
const CSS_VAR = /^var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)$/

export function withResolvedVars<T>(option: T): T {
  const cs = getComputedStyle(document.documentElement)
  const known = new Map<string, string>()
  const resolve = (s: string): string => {
    const m = CSS_VAR.exec(s)
    if (!m) return s
    let v = known.get(m[1])
    if (v === undefined) { v = cs.getPropertyValue(m[1]).trim(); known.set(m[1], v) }
    // Токена в теме нет — берём запасное значение из самой записи `var(--x, …)`,
    // а если и его нет, оставляем строку как была: пусть лучше цвет не
    // применится, чем виджет молча останется без него.
    return v || (m[2] ? m[2].trim() : s)
  }
  const walk = (v: unknown): unknown => {
    if (typeof v === 'string') return v.startsWith('var(') ? resolve(v) : v
    if (Array.isArray(v)) {
      let changed = false
      const out = v.map((x) => { const y = walk(x); if (y !== x) changed = true; return y })
      return changed ? out : v
    }
    // Только простые объекты: у функций-форматтеров и экземпляров классов
    // внутренностей не трогаем.
    if (v && typeof v === 'object' && (v as object).constructor === Object) {
      let changed = false
      const out: Record<string, unknown> = {}
      for (const [k, x] of Object.entries(v as Record<string, unknown>)) {
        const y = walk(x)
        if (y !== x) changed = true
        out[k] = y
      }
      return changed ? out : v
    }
    return v
  }
  return walk(option) as T
}

// Тонкая обёртка над ECharts: инициализирует график в div, применяет option,
// подстраивает размер под контейнер, освобождает ресурсы при размонтировании.
// onPick получает и ИМЯ, и порядковый номер точки: по имени нельзя надёжно
// найти строку, если имена повторяются (три отчёта «Дашборд «ИТ»» — реальный
// случай на боевом), и клик открывал бы всегда первый из них.
export default function EChart({ option, height = 200, onPick }: { option: EChartsOption; height?: number; onPick?: (name: string, index: number) => void }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null)
  const optionRef = useRef(option)
  optionRef.current = option
  const pickRef = useRef(onPick)
  pickRef.current = onPick

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current, undefined, { renderer: 'svg' })
    chartRef.current = chart
    chart.on('click', (p: any) => { if (p?.name) pickRef.current?.(p.name, p.dataIndex ?? 0) })
    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(ref.current)
    // Перерисовать при смене темы (data-theme на <html>) — обновить цвета текста.
    const mo = new MutationObserver(() => chart.setOption(
      withResolvedVars(withThemedText(withDetachedTooltip({ ...themeDefaults(), ...optionRef.current }))), true))
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { ro.disconnect(); mo.disconnect(); chart.dispose(); chartRef.current = null }
  }, [])

  useEffect(() => {
    chartRef.current?.setOption(withResolvedVars(withThemedText(withDetachedTooltip({ ...themeDefaults(), ...option }))), true)
  }, [option])

  return <div ref={ref} style={{ width: '100%', height }} />
}
