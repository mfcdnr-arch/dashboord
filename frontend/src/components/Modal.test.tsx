import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Modal } from './Modal'

const tab = (shift = false) => fireEvent.keyDown(document.activeElement ?? document, { key: 'Tab', shiftKey: shift })
const esc = () => fireEvent.keyDown(document.activeElement ?? document, { key: 'Escape' })

describe('Modal — окно объявляет себя диктору', () => {
  it('это диалог, он модальный и у него есть имя', () => {
    render(<Modal label="Удаление отчёта" onClose={() => {}}><button>Отмена</button></Modal>)
    const box = screen.getByRole('dialog')
    expect(box).toHaveAttribute('aria-modal', 'true')
    expect(box).toHaveAccessibleName('Удаление отчёта')
  })
})

describe('Modal — выход с клавиатуры', () => {
  it('Escape закрывает', () => {
    const onClose = vi.fn()
    render(<Modal label="Окно" onClose={onClose}><button>Отмена</button></Modal>)
    esc()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('клик по затемнению закрывает, а клик внутри окна — нет', () => {
    const onClose = vi.fn()
    render(<Modal label="Окно" onClose={onClose}><button>Внутри</button></Modal>)
    fireEvent.click(screen.getByText('Внутри'))
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('dialog').parentElement!)
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe('Modal — фокус не уходит за окно', () => {
  it('Tab с последнего элемента возвращается на первый, Shift+Tab — наоборот', () => {
    render(
      <Modal label="Окно" onClose={() => {}}>
        <button>Первая</button><button>Вторая</button><button>Третья</button>
      </Modal>,
    )
    screen.getByText('Третья').focus()
    tab()
    expect(document.activeElement).toBe(screen.getByText('Первая'))
    tab(true)
    expect(document.activeElement).toBe(screen.getByText('Третья'))
  })

  it('фокус ставится в окно при открытии — иначе Tab начал бы с интерфейса под ним', () => {
    render(<Modal label="Окно" onClose={() => {}}><button>Первая</button></Modal>)
    expect(document.activeElement).toBe(screen.getByText('Первая'))
  })

  it('окно без кнопок держит фокус на себе, а не отпускает наружу', () => {
    render(<Modal label="Пустое" onClose={() => {}}><span>только текст</span></Modal>)
    expect(document.activeElement).toBe(screen.getByRole('dialog'))
    tab()
    expect(document.activeElement).toBe(screen.getByRole('dialog'))
  })

  it('не перебивает поле с autoFocus — курсор остался бы не там, где ждёт человек', () => {
    render(
      <Modal label="Переименовать" onClose={() => {}}>
        <button>Отмена</button>
        <input autoFocus aria-label="Название" />
      </Modal>,
    )
    expect(document.activeElement).toBe(screen.getByLabelText('Название'))
  })
})

describe('Modal — возврат фокуса', () => {
  it('фокус возвращается на кнопку, которой окно открыли', () => {
    function Host() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button onClick={() => setOpen(true)}>Открыть</button>
          {open && <Modal label="Окно" onClose={() => setOpen(false)}><button>Готово</button></Modal>}
        </>
      )
    }
    render(<Host />)
    const opener = screen.getByText('Открыть')
    opener.focus()
    fireEvent.click(opener)
    expect(document.activeElement).toBe(screen.getByText('Готово'))
    esc()
    expect(document.activeElement).toBe(opener)
  })
})

describe('Modal — вложенные окна', () => {
  it('Escape закрывает только верхнее: иначе одним нажатием исчезали бы оба', () => {
    const onCloseOuter = vi.fn()
    const onCloseInner = vi.fn()
    render(
      <>
        <Modal label="Нижнее" onClose={onCloseOuter}><button>Низ</button></Modal>
        <Modal label="Верхнее" onClose={onCloseInner}><button>Верх</button></Modal>
      </>,
    )
    esc()
    expect(onCloseInner).toHaveBeenCalledTimes(1)
    expect(onCloseOuter).not.toHaveBeenCalled()
  })

  it('Tab ловит верхнее окно, а не то, что под ним', () => {
    render(
      <>
        <Modal label="Нижнее" onClose={() => {}}><button>Низ</button></Modal>
        <Modal label="Верхнее" onClose={() => {}}><button>Верх-1</button><button>Верх-2</button></Modal>
      </>,
    )
    screen.getByText('Верх-2').focus()
    tab()
    expect(document.activeElement).toBe(screen.getByText('Верх-1'))
  })
})

describe('Modal — форма', () => {
  it('окно-форма отправляется по Enter и остаётся диалогом', () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault())
    render(
      <Modal label="Архив" onClose={() => {}} onSubmit={onSubmit}>
        <input aria-label="Тема" />
        <button type="submit">Сохранить</button>
      </Modal>,
    )
    expect(screen.getByRole('dialog').tagName).toBe('FORM')
    fireEvent.submit(screen.getByRole('dialog'))
    expect(onSubmit).toHaveBeenCalled()
  })
})
