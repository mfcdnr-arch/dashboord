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

// Тонкая обёртка над ECharts: инициализирует график в div, применяет option,
// подстраивает размер под контейнер, освобождает ресурсы при размонтировании.
export default function EChart({ option, height = 200, onPick }: { option: EChartsOption; height?: number; onPick?: (name: string) => void }) {
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
    chart.on('click', (p: any) => { if (p?.name) pickRef.current?.(p.name) })
    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(ref.current)
    // Перерисовать при смене темы (data-theme на <html>) — обновить цвета текста.
    const mo = new MutationObserver(() => chart.setOption({ ...themeDefaults(), ...optionRef.current }, true))
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { ro.disconnect(); mo.disconnect(); chart.dispose(); chartRef.current = null }
  }, [])

  useEffect(() => {
    chartRef.current?.setOption({ ...themeDefaults(), ...option }, true)
  }, [option])

  return <div ref={ref} style={{ width: '100%', height }} />
}
