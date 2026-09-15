/**
 * Виртуализация длинных списков и широких таблиц.
 *
 * Рисуем только то, что попало в окно прокрутки, а по краям оставляем распорки
 * нужного размера — полоса прокрутки при этом ведёт себя как у полной таблицы.
 *
 * Почему не обрезка. У ежедневного отчёта РЦО 63 строки × 327 граф = 21 648
 * ячеек в одном узле DOM; замер на живом дашборде: 23 040 узлов страницы, из
 * них 94 % — эта таблица, а попытка отсортировать её кликом по заголовку не
 * уложилась в 45 секунд (React пересобирает все ячейки заново). Но таблица —
 * единственное место, где человек законно хочет увидеть форму ЦЕЛИКОМ, и
 * «показаны первые 20 граф из 327» сделало бы её бесполезной. Поэтому
 * сокращаем не данные, а число нарисованных узлов.
 */

export interface RangeInput {
  /** Текущая прокрутка контейнера, px. */
  scroll: number
  /** Видимый размер контейнера, px. */
  viewport: number
  /** Размер одного элемента (высота строки или ширина колонки), px. */
  itemSize: number
  /** Сколько всего элементов. */
  count: number
  /** Запас по краям, элементов. */
  overscan?: number
}

export interface Range {
  /** Первый отрисовываемый элемент. */
  start: number
  /** Граница «до», не включая. */
  end: number
  /** Распорка перед окном, px. */
  padBefore: number
  /** Распорка после окна, px. */
  padAfter: number
}

export function visibleRange({ scroll, viewport, itemSize, count, overscan = 3 }: RangeInput): Range {
  if (count <= 0 || itemSize <= 0) return { start: 0, end: 0, padBefore: 0, padAfter: 0 }

  // Первый кадр приходит до замера контейнера (viewport = 0). Отдать пустое
  // окно нельзя — таблица моргнула бы пустотой; берём разумный минимум.
  const view = viewport > 0 ? viewport : itemSize * 10

  const first = Math.max(0, Math.floor(scroll / itemSize) - overscan)
  const visible = Math.ceil(view / itemSize) + overscan * 2
  const start = Math.min(first, Math.max(0, count - 1))
  const end = Math.min(count, start + visible)

  return {
    start,
    end,
    padBefore: start * itemSize,
    // Считаем от КОНЦА, а не «count - end», чтобы полная длина сходилась
    // при любом округлении: иначе полоса прокрутки прыгала бы под пальцем.
    padAfter: Math.max(0, (count - end) * itemSize),
  }
}
