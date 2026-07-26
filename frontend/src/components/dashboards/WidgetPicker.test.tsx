import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { WidgetPicker, WIDGET_GROUPS, WIDGET_META } from './WidgetPicker'

describe('WidgetPicker (галерея типов виджетов)', () => {
  it('показывает все 4 группы', () => {
    render(<WidgetPicker value="kpi" onPick={() => {}} onClose={() => {}} />)
    for (const title of ['Показатели', 'Графики', 'Матрицы', 'Оформление']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
  })

  it('показывает новые типы (heatmap/pivot/waterfall/сравнение подразделений/год к году)', () => {
    render(<WidgetPicker value="kpi" onPick={() => {}} onClose={() => {}} />)
    for (const t of ['Тепловая карта', 'Сводная таблица', 'Водопад', 'Сравнение подразделений', 'Год к году']) {
      expect(screen.getByText(t)).toBeInTheDocument()
    }
  })

  it('клик по карточке вызывает onPick с типом и onClose', () => {
    const onPick = vi.fn()
    const onClose = vi.fn()
    render(<WidgetPicker value="kpi" onPick={onPick} onClose={onClose} />)
    fireEvent.click(screen.getByText('Тепловая карта'))
    expect(onPick).toHaveBeenCalledWith('heatmap')
    expect(onClose).toHaveBeenCalled()
  })

  it('WIDGET_META согласован с группами (каждый тип имеет метаданные)', () => {
    const all = WIDGET_GROUPS.flatMap((g) => g.items.map((i) => i.v))
    for (const v of all) expect(WIDGET_META[v]).toBeTruthy()
  })
})
