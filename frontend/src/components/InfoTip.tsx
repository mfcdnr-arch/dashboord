import { useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

const TIP_WIDTH = 240
// Пояснение виджета с 24.09 — части «что / отвечает / данные / как / учтите»,
// до 700 знаков. В 240 px такой текст вытягивался в столб на пол-экрана;
// длинному даём ширину строки, которую удобно читать.
const TIP_WIDE = 360
const WIDE_FROM = 260
const GAP = 6 // отступ от значка до облачка
const EDGE = 8 // минимальный зазор от края окна

// Небольшой ℹ️-тултип: при наведении/фокусе показывает поясняющий текст.
// Используется на виджетах (что показывает виджет) и рядом с элементами интерфейса.
//
// Облачко рисуется ПОРТАЛОМ в body и позиционируется от экрана (position: fixed).
// Раньше оно было обычным absolute-элементом внутри карточки виджета, а у карточки
// overflow: hidden — подсказка, вылезшая за край, обрезалась ровно посередине слова.
// Тот же дефект уже ловили у окна «подробнее»; лечение то же.
export default function InfoTip({ text, label = 'Подсказка' }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false)
  const btn = useRef<HTMLButtonElement>(null)
  const tip = useRef<HTMLSpanElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const width = Math.min(text.length > WIDE_FROM ? TIP_WIDE : TIP_WIDTH, window.innerWidth - 2 * EDGE)

  useLayoutEffect(() => {
    if (!open || !btn.current) return

    const place = () => {
      const b = btn.current?.getBoundingClientRect()
      if (!b) return
      const h = tip.current?.offsetHeight ?? 0
      // По горизонтали: по центру значка, но не заезжая за края окна.
      const half = width / 2
      const left = Math.min(Math.max(b.left + b.width / 2 - half, EDGE), window.innerWidth - width - EDGE)
      // По вертикали: под значком, а если снизу не помещается — над ним.
      const below = b.bottom + GAP
      const top = below + h > window.innerHeight - EDGE ? Math.max(b.top - GAP - h, EDGE) : below
      setPos({ top, left })
    }

    place()
    // Прокрутка/изменение размера уводят карточку из-под облачка — пересчитываем.
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [open, text, width])

  if (!text) return null
  return (
    <span style={{ display: 'inline-flex' }}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => { setOpen(false); setPos(null) }}>
      <button ref={btn} type="button" aria-label={label} title="" className="tap-target"
        onFocus={() => setOpen(true)} onBlur={() => { setOpen(false); setPos(null) }}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v) }}
        style={{ width: 16, height: 16, borderRadius: '50%', border: '1px solid var(--border-strong)', background: 'var(--accent-weak-bg)',
          color: 'var(--accent-text)', fontSize: 11, lineHeight: '14px', cursor: 'help', padding: 0, fontWeight: 700 }}>i</button>
      {open && createPortal(
        <span ref={tip} role="tooltip" style={{
          position: 'fixed', top: pos?.top ?? -9999, left: pos?.left ?? -9999, zIndex: 200,
          // border-box: поля входят в ширину. Без этого облачко было на 20 px
          // шире расчётного и у правого края окна обрезалось посреди слова.
          width, boxSizing: 'border-box', background: 'var(--tooltip-bg)', color: 'var(--tooltip-fg)', fontSize: 12, lineHeight: 1.4, fontWeight: 400,
          padding: '8px 10px', borderRadius: 8, boxShadow: '0 6px 20px rgba(0,0,0,0.25)', whiteSpace: 'normal',
          // до первого замера держим облачко невидимым, иначе виден скачок из угла
          visibility: pos ? 'visible' : 'hidden', pointerEvents: 'none',
        }}>{text}</span>,
        document.body,
      )}
    </span>
  )
}
