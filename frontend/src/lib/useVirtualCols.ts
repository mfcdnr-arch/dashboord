/**
 * Виртуализация КОЛОНОК широкой таблицы.
 *
 * Почему именно колонки, а не обе оси. На настоящих данных взрыв даёт ширина:
 * у ежедневного отчёта РЦО 66 строк против 327 граф, то есть 21 648 ячеек.
 * Отрисовывая только видимые колонки, получаем ~800 ячеек — в 27 раз меньше,
 * при этом вертикальная прокрутка карточки остаётся ровно такой, как была, и
 * привычный вид виджета не меняется. Виртуализировать заодно и строки значило
 * бы завести внутри карточки свой скролл-контейнер с фиксированной высотой —
 * это перестроило бы поведение ради выигрыша, которого на нынешних формах нет.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { visibleRange, type Range } from './virtual'

/** Ширина колонки при виртуализации, px. */
export const VCOL_W = 118
/** Ширина закреплённой колонки с названиями строк, px. */
export const VCOL_FIRST_W = 220
/**
 * С какого числа колонок включаем виртуализацию.
 *
 * Ниже порога оставляем обычную таблицу: там ячеек немного, а виртуализация
 * потребовала бы фиксированной ширины колонок и изменила бы привычный вид без
 * всякой пользы.
 */
export const VIRT_FROM_COLS = 30

export function useVirtualCols(count: number, enabled: boolean) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [scroll, setScroll] = useState(0)
  const [viewport, setViewport] = useState(0)

  const measure = useCallback(() => {
    const el = ref.current
    if (!el) return
    setScroll(el.scrollLeft)
    setViewport(el.clientWidth)
  }, [])

  useEffect(() => {
    if (!enabled) return
    const el = ref.current
    if (!el) return
    measure()
    // Пассивный слушатель: прокрутку мы не отменяем, только читаем.
    el.addEventListener('scroll', measure, { passive: true })
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => {
      el.removeEventListener('scroll', measure)
      ro.disconnect()
    }
  }, [enabled, measure])

  const range: Range = enabled
    ? visibleRange({ scroll, viewport, itemSize: VCOL_W, count, overscan: 4 })
    : { start: 0, end: count, padBefore: 0, padAfter: 0 }

  return { ref, range }
}
