import WidgetView from '../WidgetView'
import type { PageWidgetData } from '../../api'

/**
 * Вёрстка ОТЧЁТА для выгрузки — не снимок экрана.
 *
 * Экран ограничен: имя показателя обрезается до трёх строк, таблица прячет
 * столбцы за прокруткой, легенда графика сворачивается в «1/13», у карточки
 * фиксированная высота и потому пустое место. Всё это осмысленно, пока человек
 * может прокрутить, навести и развернуть. В PDF ничего этого нет — там
 * ограничения экрана превращаются в потерю данных: заказчик получил лист, на
 * котором не видно, что за показатель и какой цвет чему соответствует.
 *
 * Поэтому отчёт строится своей вёрсткой: одна колонка, полное имя показателя,
 * подпись «откуда цифра», развёрнутая таблица и легенда. Данные берутся ТЕ ЖЕ,
 * что показаны на экране (`injData` из батч-запроса страницы), и рисуются тем
 * же `WidgetView` — иначе отчёт однажды разошёлся бы с дашбордом.
 */
export type ReportWidget = {
  id: string
  name: string
  widget_type: string
  config?: Record<string, unknown>
}

export const REPORT_WIDTH = 1000      // px вёрстки отчёта (≈ ширина A4 при 120 dpi)

/** Ширина ШИРОКОГО отчёта (PNG): две колонки по ~950px — столько же, сколько
 *  занимает блок в обычном отчёте, поэтому графики и таблицы выглядят так же. */
export const REPORT_WIDTH_WIDE = 1960

/** Виджеты, которые в две колонки не помещаются: у таблиц своя ширина, и в
 *  узкой ячейке они вылезли бы за её край (в отчёте прокрутки нет). */
const FULL_WIDTH = new Set(['table', 'pivot', 'heatmap'])

export default function ReportLayout(
  { title, pageName, objectName, folderName, widgets, data, from, to, row, asOf, columns = 1 }: {
    title: string
    pageName: string
    objectName?: string | null
    folderName?: string | null
    widgets: ReportWidget[]
    data: Record<string, PageWidgetData>
    from?: string
    to?: string
    row?: string | null
    asOf?: string | null
    /** Колонок в потоке блоков. PDF — всегда 1 (страница А4), PNG — 2:
     *  картинка на 20 000 точек в высоту нечитаема, а места по ширине вагон. */
    columns?: number
  },
) {
  const meta = [
    `Выгружено ${new Date().toLocaleString('ru-RU')}`,
    (from || to) && `период ${from || '…'} — ${to || '…'}`,
    row && `строка «${row}»`,
    asOf && `данные на ${new Date(asOf).toLocaleDateString('ru-RU')}`,
  ].filter(Boolean).join(' · ')

  return (
    <div style={{ width: columns > 1 ? REPORT_WIDTH_WIDE : REPORT_WIDTH,
      background: 'var(--surface)', color: 'var(--text)', padding: 24 }}>
      {/* Шапка: по одному листу должно быть понятно, что это за отчёт и на
          какие данные он опирается. В прежней выгрузке не было даже названия. */}
      <div className="report-block" style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 24, fontWeight: 700, lineHeight: 1.25 }}>{title}</div>
        <div style={{ fontSize: 15, color: 'var(--text-2)', marginTop: 4 }}>
          Страница «{pageName}»
          {objectName ? ` · объект «${objectName}»` : ''}
          {folderName ? ` · папка «${folderName}»` : ''}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>{meta}</div>
        <div style={{ borderBottom: '3px solid var(--accent)', marginTop: 10 }} />
      </div>

      {/* Сетка, а не колоночный поток: html2canvas рисует блоки по их
          прямоугольникам, и фрагментация текста по колонкам ему не даётся.
          alignItems: start — чтобы низкий блок не растягивался до высоты
          соседа. */}
      <div style={{ display: 'grid', gap: 14,
        gridTemplateColumns: `repeat(${Math.max(1, columns)}, 1fr)`, alignItems: 'start' }}>
      {widgets.map((w) => {
        const d = data[w.id]
        const src = sourceOf(w)
        return (
          // Блок отчёта — единица разбивки по страницам: разрез проходит между
          // блоками, поэтому виджет не может оказаться разорванным.
          <div key={w.id} className="report-block" style={{
            border: '1px solid var(--border)', borderRadius: 12, padding: 16,
            background: 'var(--surface)', breakInside: 'avoid', minWidth: 0,
            ...(columns > 1 && FULL_WIDTH.has(w.widget_type) ? { gridColumn: '1 / -1' } : {}),
          }}>
            <div style={{ fontSize: 15, fontWeight: 700, lineHeight: 1.3 }}>{w.name}</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 3, marginBottom: 10 }}>
              {TYPE_LABEL[w.widget_type] || w.widget_type}
              {src ? ` · ${src}` : ''}
              {d?.data?.as_of ? ` · данные на ${new Date(d.data.as_of as string).toLocaleDateString('ru-RU')}` : ''}
            </div>
            {d?.error ? (
              <div style={{ fontSize: 13, color: 'var(--danger)' }}>Показатель не рассчитан: {d.error}</div>
            ) : (
              <WidgetView widgetId={w.id} injData={d?.data} batched showDrill={false}
                stripe={false} print pageAsOf={asOf || undefined} />
            )}
          </div>
        )
      })}
      </div>
    </div>
  )
}

/** Откуда цифра: набор данных или показатель. В отчёте это обязательная
 *  подпись — руководителю нужно понимать, на чём основано число. */
function sourceOf(w: ReportWidget): string {
  const c = (w.config || {}) as Record<string, string>
  if (c.metric_code) return `показатель «${c.metric_code}»`
  if (c.dataset_code) return `данные «${c.dataset_code}»`
  return ''
}

const TYPE_LABEL: Record<string, string> = {
  kpi: 'Показатель', gauge: 'Спидометр', plan_fact: 'План и факт',
  bar: 'Столбцы', line: 'Линия', pie: 'Круговая', dynamics: 'Динамика по периодам',
  yoy: 'Год к году', compare: 'Сравнение показателей', waterfall: 'Водопад',
  funnel: 'Воронка', objects_compare: 'Сравнение подразделений',
  cross_dataset_compare: 'Сравнение источников', table: 'Таблица',
  heatmap: 'Тепловая карта', pivot: 'Сводная таблица', status_grid: 'Светофор',
  text: 'Текст', image: 'Изображение',
}
