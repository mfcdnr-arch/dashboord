import { lazy, Suspense } from 'react'
import type { EChartsOption } from 'echarts'

// Ленивая обёртка над EChart: echarts (~1МБ) грузится отдельным чанком только
// когда реально нужно нарисовать график. Импортировать ВЕЗДЕ вместо ./EChart,
// иначе статический импорт затянет echarts в основной бандл.
const EChartInner = lazy(() => import('./EChart'))

export default function EChartLazy(props: { option: EChartsOption; height?: number; onPick?: (name: string) => void }) {
  return (
    <Suspense fallback={<div style={{ height: props.height ?? 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#9aa4b2', fontSize: 13 }}>Загрузка графика…</div>}>
      <EChartInner {...props} />
    </Suspense>
  )
}
