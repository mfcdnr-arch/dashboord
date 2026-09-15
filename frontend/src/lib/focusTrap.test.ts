import { describe, expect, it } from 'vitest'
import { focusablesIn, nextIndex } from './focusTrap'

describe('nextIndex — куда ведёт Tab', () => {
  it('ходит по кругу вперёд и назад', () => {
    expect(nextIndex(3, 0, false)).toBe(1)
    expect(nextIndex(3, 2, false)).toBe(0) // с последнего — на первый
    expect(nextIndex(3, 0, true)).toBe(2) // с первого назад — на последний
  })

  it('фокус вне окна возвращает внутрь с ближайшего края', () => {
    // Так бывает, когда элемент под фокусом исчез (удалили строку).
    expect(nextIndex(3, -1, false)).toBe(0)
    expect(nextIndex(3, -1, true)).toBe(2)
  })

  it('в окне без фокусируемых элементов вести некуда', () => {
    expect(nextIndex(0, -1, false)).toBe(-1)
  })

  it('единственный элемент остаётся под фокусом', () => {
    expect(nextIndex(1, 0, false)).toBe(0)
    expect(nextIndex(1, 0, true)).toBe(0)
  })
})

describe('focusablesIn — что считаем достижимым', () => {
  const mount = (html: string) => {
    const root = document.createElement('div')
    root.innerHTML = html
    document.body.appendChild(root)
    return root
  }

  it('берёт кнопки, поля и ссылки, но не выключенные', () => {
    const root = mount(`
      <button>ок</button>
      <button disabled>занято</button>
      <input />
      <input disabled />
      <a href="#">ссылка</a>
      <a>не ссылка</a>
    `)
    // Достижимы трое: кнопка, поле и ссылка с href. Выключенные и <a> без
    // href Tab не берёт вовсе.
    expect(focusablesIn(root).length).toBe(3)
  })

  it('не ведёт на скрытое — фокус ушёл бы в никуда', () => {
    const root = mount(`
      <button>видимая</button>
      <button hidden>скрытая</button>
      <div hidden><button>внутри скрытого блока</button></div>
      <button style="display:none">погашенная</button>
    `)
    expect(focusablesIn(root).map((e) => e.textContent)).toEqual(['видимая'])
  })

  it('tabindex="-1" в цикл не входит: он для программного фокуса самого окна', () => {
    const root = mount('<div tabindex="-1">окно</div><div tabindex="0">вкладка</div>')
    expect(focusablesIn(root).length).toBe(1)
  })
})
