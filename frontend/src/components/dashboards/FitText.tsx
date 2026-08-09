import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

// Крупное значение, которое УЖИМАЕТСЯ под ширину карточки вместо обрезки.
// Обрезанное число читается как настоящее: «929 8» вместо 929 825 — руководитель
// не видит, что цифра неполная. Поэтому подбирается размер шрифта, а не режется текст.
// Единица измерения задаётся в em, чтобы уменьшаться вместе с числом.
export default function FitText({ size, min = 12, title, style, children }: {
  size: number
  min?: number
  title?: string
  style?: React.CSSProperties
  children: ReactNode
}) {
  const box = useRef<HTMLDivElement>(null)
  const [fs, setFs] = useState(size)

  useLayoutEffect(() => {
    const el = box.current
    const parent = el?.parentElement
    if (!el || !parent) return

    const fit = () => {
      const avail = parent.clientWidth
      if (!avail) return
      // Меряем всегда от БАЗОВОГО размера: иначе замер второй раз пойдёт
      // от уже уменьшенного шрифта и значение «уползёт» с каждым пересчётом.
      el.style.fontSize = `${size}px`
      const natural = el.scrollWidth
      const next = natural > avail ? Math.max(min, Math.floor(size * (avail / natural))) : size
      el.style.fontSize = `${next}px`
      setFs(next)
    }

    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(parent)
    return () => ro.disconnect()
  }, [size, min, children])

  return (
    <div ref={box} title={title} style={{ ...style, fontSize: fs, whiteSpace: 'nowrap' }}>
      {children}
    </div>
  )
}
