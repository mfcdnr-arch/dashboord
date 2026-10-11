import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Field from './Field'

// Аудит дерева доступности 11.10.2026: значок ⓘ — это <button>, а <label>
// относится к ПЕРВОМУ подписываемому элементу внутри себя. Пока значок стоял в
// подписи, у каждого поля с подсказкой диктор называл поле пустым именем.
describe('Field — подпись называет поле и с подсказкой ⓘ', () => {
  it('без подсказки поле называется подписью', () => {
    render(<Field label="Порог, дней"><input type="number" /></Field>)
    expect(screen.getByRole('spinbutton', { name: 'Порог, дней' })).toBeTruthy()
  })

  it('с подсказкой поле всё равно называется подписью, а не остаётся безымянным', () => {
    render(<Field label="Этажей шапки" hint="Сколько строк занимает шапка"><input type="number" /></Field>)
    expect(screen.getByRole('spinbutton', { name: 'Этажей шапки' })).toBeTruthy()
    // Значок подсказки — своя кнопка со своим именем, к полю не прилипает.
    expect(screen.getByRole('button', { name: 'Подсказка' })).toBeTruthy()
  })

  it('свой id поля сохраняется, подпись ссылается на него', () => {
    render(<Field label="Показатели расположены" hint="…"><select id="orient"><option>в столбцах</option></select></Field>)
    const sel = screen.getByRole('combobox', { name: 'Показатели расположены' })
    expect(sel.id).toBe('orient')
  })

  it('вместо поля — группа кнопок: она называется подписью', () => {
    render(<Field label="Что размечаем" hint="…"><div><button>Таблица</button><button>Ячейки</button></div></Field>)
    expect(screen.getByRole('group', { name: 'Что размечаем' })).toBeTruthy()
  })
})
