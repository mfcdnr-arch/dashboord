import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getGeoBase, type GeoBase, type Office } from '../../api'
import { boundsOf, esc, px, py, ringPath, shortName, textWidth, type Rect } from './projection'

// Карта отделений МФЦ.
//
// Разметка SVG собирается СТРОКОЙ и вставляется одним куском: на карте
// 15 тысяч точек контура, 64 района и до сотни подписей, и пересоздавать их
// React-элементами на каждое движение мыши дороже самой отрисовки. Всё, что
// приходит от человека (названия отделений), экранируется — см. `esc`.
//
// Правила, которые стоили отладки в прототипе и которые нельзя потерять:
//  • выбор точки — на ОТПУСКАНИИ указателя, а не по click: захват указателя
//    для перетаскивания перехватывает click, и карточка не открывалась;
//  • колесо зумит ТОЛЬКО с Ctrl/⌘ — иначе карта запирает прокрутку страницы;
//  • порядок подписей «города → посёлки → отделения»: иначе полсотни подписей
//    «МФЦ №N» разом вытесняют названия населённых пунктов;
//  • подпись крепится к МАРКЕРУ, а не к точке под ним — иначе у города с
//    отделением она пропадает при приближении.

const DRAG_SLOP = 4 // пикселей: дальше этого — перетаскивание, ближе — выбор

export default function MapView({ offices, onEdit, canManage }: {
  offices: Office[]
  onEdit?: (o: Office) => void
  canManage?: boolean
}) {
  const [geo, setGeo] = useState<GeoBase | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [layer, setLayer] = useState<'adm' | 'none'>('adm')
  const [sel, setSel] = useState<Office | null>(null)
  const [q, setQ] = useState('')
  const svgRef = useRef<SVGSVGElement | null>(null)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const viewRef = useRef<Rect>({ x: 0, y: 0, w: 1, h: 1 })
  const fullWRef = useRef(1)
  const [tick, setTick] = useState(0) // перерисовать после изменения вида

  useEffect(() => { getGeoBase().then(setGeo).catch((e) => setError((e as Error).message)) }, [])

  const pts = useMemo(() => offices.filter((o) => o.is_active && o.lat != null && o.lon != null), [offices])

  const shapes = useMemo(() => {
    if (!geo) return null
    const ring = geo.contour.geometry.coordinates[0]
    return {
      ring,
      contour: ringPath(ring),
      region: boundsOf(ring),
      districts: geo.districts.map((d) => ({
        n: d.n, col: d.col, d: d.rings.map((r) => ringPath(r)).join(' '),
      })),
      places: geo.places,
    }
  }, [geo])

  const aspect = useCallback(() => {
    const el = svgRef.current
    const w = el?.clientWidth || 800
    const h = el?.clientHeight || 600
    return h / w
  }, [])

  const resetView = useCallback(() => {
    if (!shapes) return
    const a = aspect()
    const r = shapes.region
    const w = Math.max(r.w, r.h / a)
    fullWRef.current = w
    viewRef.current = { x: r.x + r.w / 2 - w / 2, y: r.y + r.h / 2 - (w * a) / 2, w, h: w * a }
    setTick((t) => t + 1)
  }, [shapes, aspect])

  useEffect(() => { resetView() }, [resetView])

  // Пересобрать вид при изменении размера контейнера: иначе карта остаётся
  // растянутой по прежним пропорциям и уезжает за край.
  useEffect(() => {
    const el = wrapRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    let first = true
    const ro = new ResizeObserver(() => { if (first) { first = false; return } setTick((t) => t + 1) })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const draw = useCallback(() => {
    const svg = svgRef.current
    if (!svg || !shapes) return
    const W = svg.clientWidth || 800
    const a = aspect()
    const view = viewRef.current
    if (Math.abs(view.h / view.w - a) > 0.005) {
      const cy = view.y + view.h / 2
      view.h = view.w * a
      view.y = cy - view.h / 2
    }
    const k = view.w / W // единиц проекции на пиксель
    svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`)

    // 1. Скопления: в Донецке полтора десятка отделений, и на обзоре они
    //    сливаются в пятно. Порог — в пикселях, поэтому при приближении
    //    скопления распадаются сами.
    const thr = 20 * k
    type Group = { x: number; y: number; items: Office[]; r: number }
    const groups: Group[] = []
    for (const o of pts) {
      const x = px(o.lon as number), y = py(o.lat as number)
      const g = groups.find((gr) => Math.hypot(gr.x - x, gr.y - y) < thr)
      if (g) {
        g.items.push(o)
        g.x = (g.x * (g.items.length - 1) + x) / g.items.length
        g.y = (g.y * (g.items.length - 1) + y) / g.items.length
      } else groups.push({ x, y, items: [o], r: 0 })
    }
    groups.forEach((g) => { g.r = g.items.length > 1 ? 13 * k : 5 * k })

    // 2. Подписи. Предела по числу НЕТ: место освобождает сам масштаб, поэтому
    //    при приближении названий становится больше, а не меньше.
    const pad = 2.5 * k
    const boxes = groups.map((g) => ({
      x0: g.x - g.r - pad, x1: g.x + g.r + pad, y0: g.y - g.r - pad, y1: g.y + g.r + pad,
    }))
    const free = (b: { x0: number; x1: number; y0: number; y1: number }) =>
      !boxes.some((o) => b.x0 < o.x1 && b.x1 > o.x0 && b.y0 < o.y1 && b.y1 > o.y0)

    const vx0 = view.x - view.w * 0.03, vx1 = view.x + view.w * 1.03
    const vy0 = view.y - view.h * 0.03, vy1 = view.y + view.h * 1.03
    const shown = shapes.places
      .map((p) => ({ p, x: px(p.lon), y: py(p.lat), big: p.pop >= 40000 || p.k === 'city' }))
      .filter((s) => s.x > vx0 && s.x < vx1 && s.y > vy0 && s.y < vy1)
      .sort((A, B) => (B.p.pop || 0) - (A.p.pop || 0))

    const dots: { x: number; y: number; r: number; o: number }[] = []
    const labels: { x: number; y: number; n: string; fs: number; cls: string }[] = []

    function tryLabel(x: number, y: number, r: number, text: string, fs: number, cls: string, bold: boolean) {
      const w = textWidth(text, bold) * fs
      const h = fs * 1.15
      for (const t of [{ y: y - r - fs * 0.45, up: 1 }, { y: y + r + fs * 1.0, up: 0 }]) {
        const box = {
          x0: x - w / 2, x1: x + w / 2,
          y0: t.up ? t.y - h : t.y, y1: t.up ? t.y : t.y + h,
        }
        if (free(box)) { boxes.push(box); labels.push({ x, y: t.y, n: text, fs, cls }); return }
      }
    }
    // Город С отделением: подпись крепим к МАРКЕРУ, а не к точке под ним —
    // иначе название садится на кружок и пропадает при приближении.
    const anchorR = (x: number, y: number, dr: number) => {
      const g = groups.find((gr) => Math.hypot(gr.x - x, gr.y - y) < Math.max(gr.r, 8 * k))
      return g ? g.r : dr
    }
    const placePoint = (s: { p: { n: string; o: number }; x: number; y: number }, dr: number, fs: number, cls: string, bold: boolean) => {
      tryLabel(s.x, s.y, anchorR(s.x, s.y, dr), s.p.n, fs, cls, bold)
      const dbox = { x0: s.x - dr - pad, x1: s.x + dr + pad, y0: s.y - dr - pad, y1: s.y + dr + pad }
      if (free(dbox)) { boxes.push(dbox); dots.push({ x: s.x, y: s.y, r: dr, o: s.p.o }) }
    }

    shown.forEach((s) => { if (s.big) placePoint(s, 2.6 * k, 11 * k, 'big' + (s.p.o ? ' o' : ''), true) })
    shown.forEach((s) => { if (!s.big) placePoint(s, 1.9 * k, 9.2 * k, s.p.o ? 'o' : '', false) })
    // Подписи самих отделений — на том месте, что осталось, и только вблизи.
    if (view.w < fullWRef.current * 0.42) {
      groups.forEach((g) => {
        if (g.items.length > 1) return // у скопления подпись — сам счётчик
        tryLabel(g.x, g.y, g.r, shortName(g.items[0].name, g.items[0].address), 9.5 * k, 'br', true)
      })
    }

    // 3. Сборка: земля → районы → контур → точки → подписи → отделения
    const out: string[] = [
      `<defs><clipPath id="mapclip"><path d="${shapes.contour}"/></clipPath></defs>`,
      `<path class="mv-land" d="${shapes.contour}" vector-effect="non-scaling-stroke"/>`,
    ]
    if (layer === 'adm') {
      out.push('<g clip-path="url(#mapclip)">')
      shapes.districts.forEach((f) => {
        out.push(`<path class="mv-zone mv-z${f.col}" d="${f.d}" vector-effect="non-scaling-stroke"><title>${esc(f.n)}</title></path>`)
      })
      out.push('</g>')
      out.push(`<path class="mv-outline" d="${shapes.contour}" vector-effect="non-scaling-stroke"/>`)
    }
    dots.forEach((d) => out.push(
      `<circle class="mv-dot${d.o ? ' mv-o' : ''}" cx="${d.x.toFixed(1)}" cy="${d.y.toFixed(1)}" r="${d.r.toFixed(1)}"/>`))
    labels.forEach((l) => out.push(
      `<text class="mv-lab ${l.cls}" x="${l.x.toFixed(1)}" y="${l.y.toFixed(1)}" text-anchor="middle" ` +
      `style="font-size:${l.fs.toFixed(2)}px;stroke-width:${(2.6 * k).toFixed(2)}px">${esc(l.n)}</text>`))
    groups.forEach((g, gi) => {
      if (g.items.length > 1) {
        out.push(`<g class="mv-clu" data-g="${gi}" tabindex="0" role="button" aria-label="${g.items.length} отделений, раскрыть">` +
          `<circle cx="${g.x.toFixed(1)}" cy="${g.y.toFixed(1)}" r="${g.r.toFixed(1)}" stroke-width="${(2 * k).toFixed(2)}"/>` +
          `<text x="${g.x.toFixed(1)}" y="${g.y.toFixed(1)}" style="font-size:${(11 * k).toFixed(2)}px">${g.items.length}</text></g>`)
      } else {
        const b = g.items[0]
        out.push(`<g class="mv-pt${sel && sel.id === b.id ? ' mv-on' : ''}" data-id="${esc(b.id)}" tabindex="0" role="button" aria-label="${esc(b.name)}">` +
          `<circle cx="${g.x.toFixed(1)}" cy="${g.y.toFixed(1)}" r="${g.r.toFixed(1)}" stroke-width="${(1.4 * k).toFixed(2)}"/></g>`)
      }
    })
    svg.innerHTML = out.join('')
    ;(svg as unknown as { __groups: Group[] }).__groups = groups
  }, [shapes, pts, layer, sel, aspect])

  useEffect(() => { draw() }, [draw, tick])

  // --- Вид: зум и перетаскивание -----------------------------------------
  const clampW = (w: number) => Math.max(fullWRef.current * 0.012, Math.min(fullWRef.current * 1.6, w))
  const zoomTo = useCallback((cx: number, cy: number, w: number) => {
    const a = aspect()
    const nw = clampW(w)
    viewRef.current = { x: cx - nw / 2, y: cy - (nw * a) / 2, w: nw, h: nw * a }
    setTick((t) => t + 1)
  }, [aspect])

  const toMap = (clientX: number, clientY: number) => {
    const svg = svgRef.current!
    const r = svg.getBoundingClientRect()
    const v = viewRef.current
    return { x: v.x + ((clientX - r.left) / r.width) * v.w, y: v.y + ((clientY - r.top) / r.height) * v.h }
  }

  // Захват указателя переводит цель последующих событий на сам <svg>, поэтому
  // цель запоминается в момент НАЖАТИЯ, а решение «выбор или перетаскивание»
  // принимается на отпускании по пройденному расстоянию.
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean; target: Element | null } | null>(null)

  // 🔴 Захват указателя ОБЯЗАН быть обёрнут: `releasePointerCapture` бросает
  // NotFoundError, если захвата уже нет (браузер снял его сам, пришёл
  // pointercancel, событие синтетическое). Необёрнутый вызов обрывал
  // обработчик ДО выбора точки — нажатие на скопление не делало ничего.
  const capture = (el: Element, id: number, on: boolean) => {
    try {
      if (on) el.setPointerCapture?.(id)
      else if (el.hasPointerCapture?.(id)) el.releasePointerCapture(id)
    } catch { /* захвата нет — значит и освобождать нечего */ }
  }

  function onPointerDown(e: React.PointerEvent<SVGSVGElement>) {
    const v = viewRef.current
    drag.current = { x: e.clientX, y: e.clientY, vx: v.x, vy: v.y, moved: false, target: e.target as Element }
    capture(e.currentTarget as unknown as Element, e.pointerId, true)
  }
  function onPointerMove(e: React.PointerEvent<SVGSVGElement>) {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x, dy = e.clientY - d.y
    if (!d.moved && Math.hypot(dx, dy) < DRAG_SLOP) return
    d.moved = true
    const svg = svgRef.current!
    const r = svg.getBoundingClientRect()
    const v = viewRef.current
    v.x = d.vx - (dx / r.width) * v.w
    v.y = d.vy - (dy / r.height) * v.h
    // Во время движения меняем ТОЛЬКО viewBox: полная перерисовка пересчитывала
    // бы расстановку подписей на каждый кадр.
    svg.setAttribute('viewBox', `${v.x} ${v.y} ${v.w} ${v.h}`)
  }
  function onPointerUp(e: React.PointerEvent<SVGSVGElement>) {
    const d = drag.current
    drag.current = null
    capture(e.currentTarget as unknown as Element, e.pointerId, false)
    if (!d) return
    if (d.moved) { setTick((t) => t + 1); return } // перерисовать после перетаскивания
    const el = (d.target as Element)?.closest?.('.mv-pt, .mv-clu') as SVGGElement | null
    if (!el) return
    if (el.classList.contains('mv-clu')) {
      const gi = Number(el.getAttribute('data-g'))
      const groups = (svgRef.current as unknown as { __groups?: { x: number; y: number; items: Office[] }[] }).__groups
      const g = groups?.[gi]
      if (g) zoomTo(g.x, g.y, viewRef.current.w * 0.4) // раскрыть скопление
      return
    }
    const id = el.getAttribute('data-id')
    const o = pts.find((p) => p.id === id)
    if (o) setSel(o)
  }
  // 🔴 Колесо вешаем НАТИВНО с `passive: false`. React добавляет onWheel
  // пассивным слушателем, в котором preventDefault не работает вовсе
  // (браузер пишет об этом в консоль), — и Ctrl+колесо масштабировало бы
  // заодно всю страницу.
  const onWheelRef = useRef<(e: WheelEvent) => void>(() => {})
  onWheelRef.current = (e: WheelEvent) => {
    // Колесо зумит только с Ctrl/⌘: иначе карта перехватывает прокрутку
    // страницы и та перестаёт листаться — проверено, это раздражает сразу.
    if (!e.ctrlKey && !e.metaKey) return
    e.preventDefault()
    const p = toMap(e.clientX, e.clientY)
    const v = viewRef.current
    const nw = clampW(v.w * (e.deltaY > 0 ? 1.25 : 0.8))
    const rx = (p.x - v.x) / v.w, ry = (p.y - v.y) / v.h
    const a = aspect()
    viewRef.current = { x: p.x - nw * rx, y: p.y - nw * a * ry, w: nw, h: nw * a }
    setTick((t) => t + 1)
  }
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const h = (e: WheelEvent) => onWheelRef.current(e)
    el.addEventListener('wheel', h, { passive: false })
    return () => el.removeEventListener('wheel', h)
    // Зависимость от geo обязательна: пока геометрия грузится, компонент
    // рисует «Загрузка карты…», SVG в разметке ещё нет, и эффект с пустым
    // списком зависимостей вешал бы слушатель в пустоту.
  }, [geo])

  function find(text: string) {
    const t = text.trim().toLowerCase()
    if (!t) return
    const o = pts.find((p) => p.name.toLowerCase().includes(t) || (p.address || '').toLowerCase().includes(t)
      || (p.city || '').toLowerCase().includes(t))
    if (o) { setSel(o); zoomTo(px(o.lon as number), py(o.lat as number), fullWRef.current * 0.12) }
  }

  if (error) return <div style={{ color: 'var(--danger)', fontSize: 13 }}>Карта не загрузилась: {error}</div>
  if (!geo) return <div style={{ color: 'var(--text-faint)', fontSize: 13 }}>Загрузка карты…</div>

  return (
    <div>
      <style>{MAP_CSS}</style>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <input style={inp} value={q} placeholder="Найти отделение или город" aria-label="Поиск на карте"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') find(q) }} />
        <button style={btnGhost} onClick={() => find(q)}>Найти</button>
        <div style={{ flex: 1 }} />
        <button style={btnGhost} aria-pressed={layer === 'adm'} onClick={() => setLayer(layer === 'adm' ? 'none' : 'adm')}>
          {layer === 'adm' ? '▦ Районы показаны' : '▫ Районы скрыты'}
        </button>
        <button style={btnGhost} onClick={() => zoomTo(viewRef.current.x + viewRef.current.w / 2, viewRef.current.y + viewRef.current.h / 2, viewRef.current.w * 0.7)} aria-label="Приблизить">＋</button>
        <button style={btnGhost} onClick={() => zoomTo(viewRef.current.x + viewRef.current.w / 2, viewRef.current.y + viewRef.current.h / 2, viewRef.current.w * 1.4)} aria-label="Отдалить">－</button>
        <button style={btnGhost} onClick={resetView}>Вся республика</button>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-start' }}>
        <div ref={wrapRef} style={{ flex: '1 1 460px', minWidth: 0 }}>
          <svg ref={svgRef} className="mv-svg" role="img"
            aria-label={`Карта отделений МФЦ: ${pts.length} отделений на карте`}
            onPointerDown={onPointerDown} onPointerMove={onPointerMove}
            onPointerUp={onPointerUp} onPointerCancel={onPointerUp} />
          <div style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 4 }}>
            Точку — нажатием, карту — перетаскиванием. Масштаб: Ctrl + колесо (чтобы карта не перехватывала прокрутку страницы).
            {pts.length < offices.length && <> · на карте {pts.length} из {offices.length}: у остальных нет координат или они не действуют.</>}
          </div>
        </div>
        <OfficeCard office={sel} onClose={() => setSel(null)} onEdit={canManage ? onEdit : undefined} />
      </div>
    </div>
  )
}

function OfficeCard({ office, onClose, onEdit }: { office: Office | null; onClose: () => void; onEdit?: (o: Office) => void }) {
  if (!office) {
    return (
      <div style={card}>
        <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          Нажмите точку на карте — здесь появятся адрес, телефон и режим работы отделения.
        </div>
      </div>
    )
  }
  const DAYS: [string, string][] = [['mon', 'Пн'], ['tue', 'Вт'], ['wed', 'Ср'], ['thu', 'Чт'], ['fri', 'Пт'], ['sat', 'Сб'], ['sun', 'Вс']]
  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
        <b style={{ fontSize: 15, flex: 1, minWidth: 0 }}>{office.name}</b>
        <button style={xBtn} onClick={onClose} title="Закрыть">✕</button>
      </div>
      <Row k="Адрес" v={office.address} />
      <Row k="Телефон" v={[office.phone, office.phone2].filter(Boolean).join(', ') || null} />
      <div style={{ display: 'flex', gap: 8, fontSize: 13, marginTop: 6 }}>
        <span style={{ color: 'var(--text-muted)', width: 78, flexShrink: 0 }}>Режим</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          {DAYS.map(([k, ru]) => {
            const h = (office.hours || {})[k as keyof typeof office.hours]
            return (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span>{ru}</span>
                <span style={{ color: h ? 'var(--text)' : 'var(--text-faint)' }}>
                  {h ? `${h.from}–${h.to}` : 'выходной'}
                </span>
              </div>
            )
          })}
        </div>
      </div>
      {office.note && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>{office.note}</div>}
      <Row k="Почта" v={office.email} />
      {office.website && (
        <div style={{ fontSize: 13, marginTop: 6 }}>
          <a href={office.website} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>{office.website}</a>
        </div>
      )}
      {onEdit && <button style={{ ...btnGhost, marginTop: 10 }} onClick={() => onEdit(office)}>✎ Править сведения</button>}
    </div>
  )
}

function Row({ k, v }: { k: string; v: string | null }) {
  if (!v) return null
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 13, marginTop: 6 }}>
      <span style={{ color: 'var(--text-muted)', width: 78, flexShrink: 0 }}>{k}</span>
      <span style={{ flex: 1, minWidth: 0 }}>{v}</span>
    </div>
  )
}

const inp: React.CSSProperties = { height: 34, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13, boxSizing: 'border-box', width: 240, background: 'var(--surface)', color: 'var(--text)' }
const btnGhost: React.CSSProperties = { height: 34, padding: '0 12px', borderRadius: 8, background: 'transparent', color: 'var(--text)', border: '1px solid var(--border-strong)', fontSize: 13, cursor: 'pointer' }
const card: React.CSSProperties = { flex: '0 1 320px', minWidth: 260, border: '1px solid var(--border-faint)', borderRadius: 10, padding: 12, background: 'var(--surface-2)', boxSizing: 'border-box' }
const xBtn: React.CSSProperties = { border: 'none', background: 'none', fontSize: 15, cursor: 'pointer', color: 'var(--text-muted)' }

// Цвета — токенами темы: карта обязана читаться и в тёмной, и в «МинЭк».
// `touch-action: pan-y` — страница листается одним пальцем, карта двигается
// перетаскиванием; иначе на планшете страница перестаёт прокручиваться вовсе.
const MAP_CSS = `
.mv-svg{width:100%;height:min(70vh,620px);display:block;background:var(--surface);
  border:1px solid var(--border-faint);border-radius:10px;touch-action:pan-y;cursor:grab}
.mv-svg:active{cursor:grabbing}
.mv-land{fill:var(--surface-2);stroke:var(--border-strong);stroke-width:1.2}
.mv-outline{fill:none;stroke:var(--border-strong);stroke-width:1.4}
.mv-zone{stroke:var(--border-faint);stroke-width:.6;fill-opacity:.55}
.mv-z0{fill:var(--chart-1)}.mv-z1{fill:var(--chart-2)}.mv-z2{fill:var(--chart-3)}
.mv-z3{fill:var(--chart-4)}.mv-z4{fill:var(--chart-5)}.mv-z5{fill:var(--chart-6)}
.mv-dot{fill:var(--text-muted);opacity:.65}
.mv-dot.mv-o{opacity:.3}
.mv-lab{fill:var(--text);paint-order:stroke;stroke:var(--surface);stroke-linejoin:round;pointer-events:none}
.mv-lab.big{font-weight:700}
.mv-lab.o{fill:var(--text-faint)}
.mv-lab.br{fill:var(--accent)}
.mv-pt circle{fill:var(--accent);stroke:var(--surface);cursor:pointer}
.mv-pt:hover circle,.mv-pt:focus circle{stroke:var(--text)}
.mv-pt.mv-on circle{stroke:var(--text);stroke-width:2}
.mv-clu{cursor:pointer}
.mv-clu circle{fill:var(--brand-brown,var(--text-muted));stroke:var(--surface)}
.mv-clu text{fill:var(--on-accent,#fff);text-anchor:middle;dominant-baseline:central;font-weight:700}
`
