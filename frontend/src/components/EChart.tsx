import { useEffect, useRef } from 'react'
// Модульная сборка echarts: регистрируем только используемые типы графиков и
// компоненты — так чанк echarts заметно меньше (важно для слабого железа/LAN МФЦ).
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, GaugeChart, HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts' // только тип (стирается при сборке)

echarts.use([BarChart, LineChart, PieChart, GaugeChart, HeatmapChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, VisualMapComponent, CanvasRenderer])

// Тонкая обёртка над ECharts: инициализирует график в div, применяет option,
// подстраивает размер под контейнер, освобождает ресурсы при размонтировании.
export default function EChart({ option, height = 200, onPick }: { option: EChartsOption; height?: number; onPick?: (name: string) => void }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null)
  const pickRef = useRef(onPick)
  pickRef.current = onPick

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    chartRef.current = chart
    chart.on('click', (p: any) => { if (p?.name) pickRef.current?.(p.name) })
    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); chart.dispose(); chartRef.current = null }
  }, [])

  useEffect(() => {
    chartRef.current?.setOption(option, true)
  }, [option])

  return <div ref={ref} style={{ width: '100%', height }} />
}
