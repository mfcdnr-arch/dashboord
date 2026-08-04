import { useCallback, useRef, useState } from 'react'

/** Ширина контейнера в px, отслеживаемая ResizeObserver.
 *
 * Зачем свой хук вместо `WidthProvider` из react-grid-layout: тот измеряет
 * контейнер один раз в componentDidMount и далее только по событию `resize`
 * окна, и если в момент измерения offsetWidth равен 0, молча остаётся со своей
 * шириной по умолчанию — 1280px. В нашем макете колонка контента ограничена
 * (`main` с max-width), поэтому сетка виджетов верстается по 1280px внутри
 * более узкого контейнера: карточки уезжают за правый край, на странице
 * дашборда появляется горизонтальная прокрутка, правый виджет обрезается.
 *
 * Возвращается CALLBACK-ref, а не обычный: сетка находится внутри условного
 * рендера (пока дашборд/страница не выбраны, узла в DOM нет). Обычный ref +
 * useEffect([]) измерил бы null один раз при монтировании страницы и больше
 * никогда — сетка так и осталась бы без ширины.
 *
 * Возвращает [callback-ref на контейнер, ширина или undefined до измерения].
 */
export function useContainerWidth<T extends HTMLElement>(): [(node: T | null) => void, number | undefined] {
  const [width, setWidth] = useState<number | undefined>(undefined)
  const cleanupRef = useRef<(() => void) | null>(null)

  const ref = useCallback((node: T | null) => {
    cleanupRef.current?.()
    cleanupRef.current = null
    if (!node) return
    const measure = () => setWidth(node.clientWidth || undefined)
    measure()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      cleanupRef.current = () => window.removeEventListener('resize', measure)
      return
    }
    const ro = new ResizeObserver(measure)
    ro.observe(node)
    cleanupRef.current = () => ro.disconnect()
  }, [])

  return [ref, width]
}
