import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { WhereEditor, whereFromConfig, whereToConfig, type WhereCond } from './WhereEditor'

describe('условия отбора строк (подсчёт и лента таблицы)', () => {
  it('в конфигурацию уходят числа и списки, а не строки как ввели', () => {
    const conds: WhereCond[] = [
      { field: 'ocenka', op: 'gte', value: '15' },
      { field: 'ocenka', op: 'lt', value: '7,5' },
      { field: 'status', op: 'in', value: 'В работе,  Отложен , ' },
      { field: 'status', op: 'eq', value: ' В работе ' },
      { field: 'srok', op: 'date_before_report', value: 'мусор, который не нужен' },
    ]
    expect(whereToConfig(conds)).toEqual([
      { field: 'ocenka', op: 'gte', value: 15 },
      { field: 'ocenka', op: 'lt', value: 7.5 },
      { field: 'status', op: 'in', value: ['В работе', 'Отложен'] },
      { field: 'status', op: 'eq', value: 'В работе' },
      { field: 'srok', op: 'date_before_report' },
    ])
  })

  it('неполное условие не отправляется: иначе предпросмотр ругался бы на каждый набранный символ', () => {
    expect(whereToConfig([
      { field: '', op: 'eq', value: 'x' },
      { field: 'a', op: 'eq', value: '  ' },
      { field: 'a', op: 'gt', value: 'много' },
      { field: 'a', op: 'filled', value: '' },
    ])).toEqual([{ field: 'a', op: 'filled' }])
  })

  it('сохранённые условия открываются для правки так же, как вводились', () => {
    expect(whereFromConfig([
      { field: 'status', op: 'in', value: ['В работе', 'Отложен'] },
      { field: 'ocenka', op: 'gte', value: 15 },
      { field: 'srok', op: 'date_before_report' },
      { op: 'eq' }, 'мусор',
    ])).toEqual([
      { field: 'status', op: 'in', value: 'В работе, Отложен' },
      { field: 'ocenka', op: 'gte', value: '15' },
      { field: 'srok', op: 'date_before_report', value: '' },
    ])
    expect(whereFromConfig(undefined)).toEqual([])
  })

  it('поля названы для диктора, условие добавляется и убирается', () => {
    const onChange = vi.fn()
    const fields = [{ code: 'status', name: 'Статус' }, { code: 'srok', name: 'Срок решения' }]
    const { rerender } = render(
      <WhereEditor fields={fields} value={[{ field: 'status', op: 'eq', value: 'В работе' }]}
        onChange={onChange} title="Считать только строки, где…" />)
    expect(screen.getByLabelText('Графа условия 1')).toBeInTheDocument()
    expect(screen.getByLabelText('Условие для «Статус»')).toBeInTheDocument()
    expect(screen.getByLabelText('Значение для «Статус»')).toHaveValue('В работе')
    fireEvent.click(screen.getByRole('button', { name: '＋ условие' }))
    expect(onChange).toHaveBeenLastCalledWith([
      { field: 'status', op: 'eq', value: 'В работе' }, { field: '', op: 'eq', value: '' }])
    // Условие без значения («пуста», «срок истёк») поля значения не показывает.
    rerender(<WhereEditor fields={fields} value={[{ field: 'srok', op: 'date_before_report', value: '' }]}
      onChange={onChange} title="t" />)
    expect(screen.queryByLabelText('Значение для «Срок решения»')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Убрать условие 1' }))
    expect(onChange).toHaveBeenLastCalledWith([])
  })
})
