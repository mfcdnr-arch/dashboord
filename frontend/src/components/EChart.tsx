import { useEffect, useRef } from 'react'
// Модульная сборка echarts: регистрируем только используемые типы графиков и
// компоненты — так чанк echarts заметно меньше (важно для слабого железа/LAN МФЦ).
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, GaugeChart, HeatmapChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent, VisualMapComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts' // только тип (стирается при сборке)

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
  const axis = (a: Ax): Ax => ({
    ...a,
    axisLabel: { color: muted, ...(a.axisLabel as Ax || {}) },
    axisLine: a.axisLine ?? { lineStyle: { color: line } },
    splitLine: a.splitLine ?? { lineStyle: { color: faint } },
  })
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
      withThemedText(withDetachedTooltip({ ...themeDefaults(), ...optionRef.current })), true))
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { ro.disconnect(); mo.disconnect(); chart.dispose(); chartRef.current = null }
  }, [])

  useEffect(() => {
    chartRef.current?.setOption(withThemedText(withDetachedTooltip({ ...themeDefaults(), ...option })), true)
  }, [option])

  return <div ref={ref} style={{ width: '100%', height }} />
}
