import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

// Тонкая обёртка над ECharts: инициализирует график в div, применяет option,
// подстраивает размер под контейнер, освобождает ресурсы при размонтировании.
export default function EChart({ option, height = 200, onPick }: { option: echarts.EChartsOption; height?: number; onPick?: (name: string) => void }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
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
