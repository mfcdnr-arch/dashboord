import { useEffect, useState } from 'react'
import GridLayout, { WidthProvider } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { getPageData, listPageWidgets, type PageWidgetData, type Widget } from '../api'
import WidgetView from './WidgetView'

const GL = WidthProvider(GridLayout)

// Компактный READ-ONLY рендер одной страницы дашборда — переиспользуется в
// витринах (волна E), чтобы показать сразу НЕСКОЛЬКО ЦЕЛЫХ дашбордов на одном
// экране. Без редактирования/раскладки — только просмотр виджетов с данными
// (батч-запрос, как в DashboardsPage).
export default function PagePreview({ pageId }: { pageId: string }) {
  const [widgets, setWidgets] = useState<Widget[] | null>(null)
  const [pageData, setPageData] = useState<Record<string, PageWidgetData>>({})
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setWidgets(null); setPageData({}); setError(null)
    listPageWidgets(pageId)
      .then((r) => { if (!cancelled) setWidgets(r.widgets) })
      .catch((e) => { if (!cancelled) setError((e as Error).message) })
    getPageData(pageId)
      .then((r) => {
        if (cancelled) return
        const m: Record<string, PageWidgetData> = {}
        r.widgets.forEach((w) => { m[w.id] = w })
        setPageData(m)
      })
      .catch(() => { /* виджеты дофетчат сами через WidgetView, если батч упал */ })
    return () => { cancelled = true }
  }, [pageId])

  if (error) return <div style={{ color: 'var(--danger)', fontSize: 13, padding: 12 }}>{error}</div>
  if (!widgets) return <div style={{ color: 'var(--text-faint)', fontSize: 13, padding: 12 }}>Загрузка…</div>
  if (widgets.length === 0) return <div style={{ color: 'var(--text-faint)', fontSize: 13, padding: 12 }}>На странице нет виджетов.</div>

  return (
    <GL className="layout" cols={12} rowHeight={40} margin={[10, 10]} isDraggable={false} isResizable={false} compactType="vertical"
      layout={widgets.map((w) => ({ i: w.id, x: w.position_x || 0, y: w.position_y || 0, w: w.width || 4, h: w.height || 4 }))}>
      {widgets.map((w) => (
        <div key={w.id} style={{ border: '1px solid var(--border-faint)', borderRadius: 10, padding: 10, background: 'var(--surface)', overflow: 'hidden' }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{w.name}</div>
          <WidgetView widgetId={w.id} showDrill={false} batched injData={pageData[w.id]?.data} injError={pageData[w.id]?.error} />
        </div>
      ))}
    </GL>
  )
}
