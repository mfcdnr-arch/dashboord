import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { focusablesIn, nextIndex } from '../lib/focusTrap'
import { dialog, overlay } from './dashboards/shared'

/**
 * Модальное окно: одна обёртка на все окна системы.
 *
 * До неё каждое окно писалось заново — портал, затемнение, остановка клика, —
 * и доступность с клавиатуры получалась случайно: из 38 окон `role="dialog"`
 * стоял у одного, ловушки фокуса не было ни у одного, Escape не закрывал 26.
 * Человек, работающий с клавиатуры, и диктор экрана в окно попадали, но выйти
 * и понять, где они, не могли.
 *
 * Что берёт на себя:
 *  - портал в body — окно не обрезается карточкой виджета и не искажается
 *    трансформацией сетки дашборда (ровно ради этого порталы и заводились);
 *  - `role="dialog"` + `aria-modal` + имя окна — диктор объявляет, куда попал;
 *  - ловушка фокуса: Tab ходит по кругу внутри окна, а не уводит в интерфейс
 *    под ним, до которого всё равно не дотянуться мышью;
 *  - Escape и клик по затемнению — закрыть;
 *  - возврат фокуса на кнопку, которой окно открыли.
 *
 * Чего НЕ делает и почему: фон не помечается `inert`/`aria-hidden`. В body
 * живут и другие порталы (подсказки ⓘ, облачка графиков), и пометить их
 * скопом значило бы погасить то, что окну не мешает. Дикторы понимают
 * `aria-modal`, а Tab за окно не уходит благодаря ловушке.
 */

/** Стек открытых окон: клавиши обрабатывает только верхнее.
 *  Иначе один Escape закрыл бы и подтверждение, и окно под ним. */
const stack: string[] = []

export function Modal(
  { label, onClose, width, style, onSubmit, children, initialFocus = true, closeOnBackdrop = true }: {
    /** Имя окна для диктора. Обычно совпадает с видимым заголовком. */
    label: string
    onClose: () => void
    width?: number | string
    /** Дополнительные стили окна (маскирует `dialog`): флекс-колонка, своя высота. */
    style?: React.CSSProperties
    /** Задан — окно рендерится формой: часть окон отправляется по Enter. */
    onSubmit?: (e: React.FormEvent) => void
    /** false — фокус не переносить: окно с единственным полем ставит его само
     *  через autoFocus, и перехват сбил бы курсор в начало. */
    initialFocus?: boolean
    /** false — клик мимо окна не закрывает. Нужно там, где закрытие несёт
     *  последствие («мастер настройки больше не всплывёт») и промах мимо окна
     *  стоил бы дорого. Escape при этом остаётся: без выхода с клавиатуры
     *  окно превращается в ловушку, ради чего всё и затевалось. */
    closeOnBackdrop?: boolean
    children: React.ReactNode
  },
) {
  const id = useId()
  const boxRef = useRef<HTMLDivElement | HTMLFormElement | null>(null)
  // Кого вернуть фокус при закрытии — запоминаем ДО того, как окно его заберёт.
  const openerRef = useRef<HTMLElement | null>(
    typeof document !== 'undefined' ? (document.activeElement as HTMLElement | null) : null,
  )

  useEffect(() => {
    stack.push(id)
    const box = boxRef.current
    if (initialFocus && box) {
      // Если внутри уже есть autoFocus-поле, оно и держит фокус — не перебиваем.
      if (!box.contains(document.activeElement)) {
        const items = focusablesIn(box)
        ;(items[0] ?? box).focus()
      }
    }
    return () => {
      const i = stack.lastIndexOf(id)
      if (i >= 0) stack.splice(i, 1)
      const opener = openerRef.current
      // Кнопка могла исчезнуть вместе со строкой, которую удалили этим окном —
      // тогда возвращать фокус некуда, и трогать его не надо.
      if (opener && opener.isConnected) opener.focus()
    }
  }, [id, initialFocus])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== id) return
      if (e.key === 'Escape') { e.stopPropagation(); onClose(); return }
      if (e.key !== 'Tab') return
      const box = boxRef.current
      if (!box) return
      const items = focusablesIn(box)
      if (items.length === 0) { e.preventDefault(); box.focus(); return }
      const cur = items.indexOf(document.activeElement as HTMLElement)
      const to = nextIndex(items.length, cur, e.shiftKey)
      // Внутри цикла Tab отдаём браузеру — он ведёт по своему порядку;
      // перехватываем только переход через край, ради которого ловушка и нужна.
      if (cur >= 0 && to !== 0 && to !== items.length - 1) return
      if (cur >= 0 && ((e.shiftKey && cur !== 0) || (!e.shiftKey && cur !== items.length - 1))) return
      e.preventDefault()
      items[to].focus()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [id, onClose])

  const boxStyle: React.CSSProperties = { ...dialog, ...(width !== undefined ? { width } : {}), ...style }
  const common = {
    style: boxStyle,
    role: 'dialog' as const,
    'aria-modal': true,
    'aria-label': label,
    tabIndex: -1,
    onClick: (e: React.MouseEvent) => e.stopPropagation(),
  }

  return createPortal((
    <div style={overlay} onClick={closeOnBackdrop ? onClose : undefined}>
      {onSubmit
        ? <form {...common} ref={boxRef as React.Ref<HTMLFormElement>} onSubmit={onSubmit}>{children}</form>
        : <div {...common} ref={boxRef as React.Ref<HTMLDivElement>}>{children}</div>}
    </div>
  ), document.body)
}
