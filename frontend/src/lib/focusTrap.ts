/**
 * Ловушка фокуса модального окна: что считать фокусируемым и куда вести Tab.
 *
 * Расчёт вынесен из компонента намеренно — внутри него эти правила нельзя
 * проверить тестом, а ошибка здесь тихая: Tab молча уводит человека за окно,
 * в интерфейс под ним, и он продолжает нажимать, не понимая, где находится.
 */

/**
 * Что браузер ведёт по Tab.
 *
 * `tabindex="-1"` исключён осознанно: такой элемент фокусируется программно
 * (им помечено само окно, чтобы было куда поставить фокус в пустом диалоге),
 * но в обход Tab, и в цикл попадать не должен.
 */
const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

/** Видимые элементы, которые реально можно сфокусировать Tab'ом. */
export function focusablesIn(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(isReachable)
}

function isReachable(el: HTMLElement): boolean {
  // Скрытая кнопка остаётся в разметке (свёрнутый блок, вкладка не та) —
  // но вести на неё Tab значит отправить фокус в никуда.
  if (el.hidden || el.closest('[hidden]')) return false
  const st = el.style
  if (st.display === 'none' || st.visibility === 'hidden') return false
  return true
}

/**
 * Куда перейти по Tab внутри цикла из `count` элементов.
 *
 * `current < 0` означает «фокус сейчас вне окна» — так бывает после того, как
 * элемент под фокусом исчез (строку удалили, вкладку переключили). Тогда Tab
 * возвращает в окно с ближайшего края, а не оставляет человека снаружи.
 */
export function nextIndex(count: number, current: number, back: boolean): number {
  if (count <= 0) return -1
  if (current < 0) return back ? count - 1 : 0
  return back ? (current - 1 + count) % count : (current + 1) % count
}
