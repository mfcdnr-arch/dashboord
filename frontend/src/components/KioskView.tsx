import { useEffect, useState } from 'react'
import GridLayout, { WidthProvider, type Layout } from 'react-grid-layout'
import { listPageWidgets, type DashPage, type Widget } from '../api'
import WidgetView from './WidgetView'

// Режим-витрина / киоск: полноэкранный показ дашборда для ТВ в холле МФЦ.
// Автопрокрутка страниц по таймеру, пауза, ручная навигация (стрелки/пробел),
// часы, авто-обновление данных. Выход — Esc или кнопка. Только просмотр.

const GL = WidthProvider(GridLayout)
const INTERVALS = [10, 15, 20, 30, 60]

export default function KioskView({ dashboardName, pages, onClose }: {
  dashboardName: string
  pages: DashPage[]
  onClose: () => void
}) {
  const [idx, setIdx] = useState(0)
  const [widgetsByPage, setWidgetsByPage] = useState<Record<string, Widget[]>>({})
  const [paused, setPaused] = useState(false)
  const [secs, setSecs] = useState(15)
  const [now, setNow] = useState(new Date())
  const [reloadKey, setReloadKey] = useState(0)

  // Полный экран (лучшая попытка — жест клика уже был) + предзагрузка всех страниц
  useEffect(() => {
    document.documentElement.requestFullscreen?.().catch(() => {})
    pages.forEach((p) => listPageWidgets(p.id)
      .then((r) => setWidgetsByPage((s) => ({ ...s, [p.id]: r.widgets })))
      .catch(() => {}))
    return () => { if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {}) }
  }, [pages])

  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t) }, [])

  // автопрокрутка страниц
  useEffect(() => {
    if (paused || pages.length <= 1) return
    const t = setInterval(() => setIdx((i) => (i + 1) % pages.length), secs * 1000)
    return () => clearInterval(t)
  }, [paused, pages.length, secs])

  // авто-обновление данных виджетов (для «живого» ТВ)
  useEffect(() => { const t = setInterval(() => setReloadKey((k) => k + 1), 60000); return () => clearInterval(t) }, [])

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowRight') setIdx((i) => (i + 1) % pages.length)
      else if (e.key === 'ArrowLeft') setIdx((i) => (i - 1 + pages.length) % pages.length)
      else if (e.key === ' ') { e.preventDefault(); setPaused((p) => !p) }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [pages.length, onClose])

  const page: DashPage | undefined = pages[idx]
  const widgets = (page && widgetsByPage[page.id]) || []
  const layout: Layout[] = widgets.map((w) => ({ i: w.id, x: w.position_x || 0, y: w.position_y || 0, w: w.width || 4, h: w.height || 4 }))

  const go = (d: number) => setIdx((i) => (i + d + pages.length) % pages.length)

  return (
    <div style={overlay}>
      <div style={bar}>
        <div style={{ fontSize: 20, fontWeight: 700 }}>{dashboardName}</div>
        <div style={{ fontSize: 16, color: '#cbd5e1' }}>· {page?.name || '—'}</div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ fontSize: 18, fontVariantNumeric: 'tabular-nums' }}>{now.toLocaleTimeString('ru-RU')}</div>
          <button style={ctrl} onClick={() => go(-1)} title="Предыдущая (←)">‹</button>
          <button style={ctrl} onClick={() => setPaused((p) => !p)} title="Пауза/пуск (пробел)">{paused ? '▶' : '⏸'}</button>
          <button style={ctrl} onClick={() => go(1)} title="Следующая (→)">›</button>
          <select style={selDark} value={secs} onChange={(e) => setSecs(Number(e.target.value))} title="Интервал смены">
            {INTERVALS.map((s) => <option key={s} value={s}>{s}с</option>)}
          </select>
          <button style={{ ...ctrl, color: '#fca5a5' }} onClick={onClose} title="Выход (Esc)">✕</button>
        </div>
      </div>

      {/* индикатор страниц */}
      {pages.length > 1 && (
        <div style={{ display: 'flex', gap: 6, justifyContent: 'center', padding: '6px 0' }}>
          {pages.map((p, i) => (
            <button key={p.id} onClick={() => setIdx(i)} title={p.name}
              style={{ width: i === idx ? 26 : 10, height: 10, borderRadius: 6, border: 'none', cursor: 'pointer', transition: 'width .3s', background: i === idx ? '#60a5fa' : '#475569' }} />
          ))}
        </div>
      )}

      <div style={{ flex: 1, overflow: 'auto', padding: '4px 16px 16px' }}>
        {widgets.length === 0 ? (
          <div style={{ color: '#94a3b8', textAlign: 'center', marginTop: 80, fontSize: 18 }}>
            {page ? 'Загрузка страницы…' : 'На дашборде нет страниц'}
          </div>
        ) : (
          <GL className="layout" cols={12} rowHeight={60} margin={[16, 16]} isDraggable={false} isResizable={false} layout={layout} compactType="vertical">
            {widgets.map((w) => (
              <div key={w.id} style={card}>
                <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>{w.name}</div>
                <div style={{ overflow: 'auto', maxHeight: 'calc(100% - 26px)' }}>
                  <WidgetView widgetId={w.id} reloadKey={reloadKey} showDrill={false} />
                </div>
              </div>
            ))}
          </GL>
        )}
      </div>
    </div>
  )
}

const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: '#0f172a', color: '#fff', zIndex: 200, display: 'flex', flexDirection: 'column' }
const bar: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid #1e293b' }
const ctrl: React.CSSProperties = { width: 34, height: 34, borderRadius: 8, border: '1px solid #334155', background: '#1e293b', color: '#fff', cursor: 'pointer', fontSize: 16 }
const selDark: React.CSSProperties = { height: 34, borderRadius: 8, border: '1px solid #334155', background: '#1e293b', color: '#fff', fontSize: 13, padding: '0 6px' }
const card: React.CSSProperties = { background: '#fff', color: '#111827', borderRadius: 12, padding: 14, overflow: 'hidden', boxShadow: '0 4px 16px rgba(0,0,0,0.25)' }
