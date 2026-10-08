import { describe, expect, it } from 'vitest'
import { colorAt, textOn } from './contrast'

describe('читаемый текст поверх заливки', () => {
  it('на насыщенной клетке — белый, на бледной — тёмный', () => {
    expect(textOn('#a5563c')).toBe('#ffffff') // светлая тема, верх шкалы (матрица рисков)
    expect(textOn('#faf0e9')).toBe('#1f1a17') // низ шкалы светлой темы
    // Тёмная тема идёт от тёмного к светлому: на её верхней клетке белый не годился бы
    // так же, как тёмный на нижней.
    expect(textOn('#33261d')).toBe('#ffffff')
    expect(textOn('#1b285c')).toBe('#ffffff') // «МинЭк», верх шкалы
  })

  it('цвет в точке шкалы — как интерполирует график', () => {
    const p = ['#000000', '#ffffff']
    expect(colorAt(p, 0)).toBe('#000000')
    expect(colorAt(p, 1)).toBe('#ffffff')
    expect(colorAt(p, 0.5)).toBe('#808080')
    expect(colorAt(['#faf0e9', '#e0b58f', '#e0885f', '#e04e39', '#a5563c'], 1)).toBe('#a5563c')
    // Выход за шкалу и мусор не роняют расчёт.
    expect(colorAt(p, 7)).toBe('#ffffff')
    expect(colorAt(p, NaN)).toBe('#000000')
    expect(colorAt(['var(--x)'], 0.5)).toBeNull()
    expect(textOn(null)).toBe('#1f1a17')
  })
})
