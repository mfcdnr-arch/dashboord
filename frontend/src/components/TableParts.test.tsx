import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RowPickCell, RowToggleCell, SortableTh } from './TableParts'

const table = (children: React.ReactNode) => render(<table><tbody><tr>{children}</tr></tbody></table>)

describe('SortableTh — сортировка доступна с клавиатуры', () => {
  it('заголовок сортируется кнопкой: Enter и пробел работают сами', () => {
    const onSort = vi.fn()
    table(<SortableTh sort={null} col="plan" onSort={onSort}>План</SortableTh>)
    const btn = screen.getByRole('button', { name: /План/ })
    fireEvent.click(btn)
    expect(onSort).toHaveBeenCalledWith('plan')
  })

  it('диктору сообщается ТЕКУЩИЙ порядок: стрелку ▲ он не увидит', () => {
    const { rerender } = render(
      <table><tbody><tr>
        <SortableTh sort={null} col="plan" onSort={() => {}}>План</SortableTh>
      </tr></tbody></table>,
    )
    expect(screen.getByRole('columnheader')).toHaveAttribute('aria-sort', 'none')
    rerender(
      <table><tbody><tr>
        <SortableTh sort={{ col: 'plan', dir: 1 }} col="plan" onSort={() => {}}>План</SortableTh>
      </tr></tbody></table>,
    )
    expect(screen.getByRole('columnheader')).toHaveAttribute('aria-sort', 'ascending')
    rerender(
      <table><tbody><tr>
        <SortableTh sort={{ col: 'plan', dir: -1 }} col="plan" onSort={() => {}}>План</SortableTh>
      </tr></tbody></table>,
    )
    expect(screen.getByRole('columnheader')).toHaveAttribute('aria-sort', 'descending')
  })

  it('порядок другого столбца этот заголовок не помечает', () => {
    table(<SortableTh sort={{ col: 'fact', dir: 1 }} col="plan" onSort={() => {}}>План</SortableTh>)
    expect(screen.getByRole('columnheader')).toHaveAttribute('aria-sort', 'none')
  })
})

describe('RowPickCell — проваливание в строку с клавиатуры', () => {
  it('название строки — кнопка; имя у неё короткое, пояснение в подсказке', () => {
    const onPick = vi.fn()
    table(<RowPickCell label="Горловка" onPick={onPick} />)
    // Имя кнопки — само название строки: при обходе таблицы диктор читает
    // «Горловка», а не длинную фразу в каждой из шестидесяти строк.
    const btn = screen.getByRole('button', { name: 'Горловка' })
    expect(btn).toHaveAttribute('title', 'Показать всю страницу по строке «Горловка»')
    fireEvent.click(btn)
    expect(onPick).toHaveBeenCalledWith('Горловка')
  })

  it('без проваливания это обычная ячейка, а не мёртвая кнопка', () => {
    table(<RowPickCell label="Горловка" />)
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.getByRole('rowheader')).toHaveTextContent('Горловка')
  })

  it('заголовок строки помечен как заголовок: по нему диктор ведёт по таблице', () => {
    table(<RowPickCell label="Горловка" onPick={() => {}} />)
    expect(screen.getByRole('rowheader')).toBeTruthy()
  })

  it('своё содержимое не теряется — у матрицы там пометка ⌀', () => {
    table(<RowPickCell label="Доля" onPick={() => {}}>Доля ⌀</RowPickCell>)
    expect(screen.getByRole('button')).toHaveTextContent('Доля ⌀')
  })
})

describe('RowToggleCell — состояние переключателя названо вслух', () => {
  it('раскрытая строка помечена aria-expanded', () => {
    const onToggle = vi.fn()
    table(<RowToggleCell onToggle={onToggle} expanded={false}>Мариуполь</RowToggleCell>)
    const btn = screen.getByRole('button')
    expect(btn).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(btn)
    expect(onToggle).toHaveBeenCalled()
  })

  it('строка-фильтр помечена aria-pressed: глазами это подсветка, диктору — ничего', () => {
    table(<RowToggleCell onToggle={() => {}} pressed>admin</RowToggleCell>)
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true')
  })

  it('лишних состояний не выдумываем: раскрытие и нажатость — разные вещи', () => {
    table(<RowToggleCell onToggle={() => {}} expanded>Мариуполь</RowToggleCell>)
    const btn = screen.getByRole('button')
    expect(btn).toHaveAttribute('aria-expanded', 'true')
    expect(btn).not.toHaveAttribute('aria-pressed')
  })
})
