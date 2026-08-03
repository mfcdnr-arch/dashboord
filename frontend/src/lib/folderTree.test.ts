import { describe, expect, it } from 'vitest'
import { folderLabel, folderTree } from './folderTree'
import type { Folder } from '../api'

function f(id: string, name: string, parent: string | null = null): Folder {
  return { id, name, parent_folder_id: parent, created_at: '2026-01-01T00:00:00Z' }
}

describe('folderTree', () => {
  it('ставит родителя перед детьми, глубина растёт', () => {
    const flat = [f('c', 'Ребёнок', 'a'), f('a', 'Родитель'), f('b', 'Другой корень')]
    const tree = folderTree(flat)
    const order = tree.map((n) => n.id)
    expect(order.indexOf('a')).toBeLessThan(order.indexOf('c'))
    expect(tree.find((n) => n.id === 'a')!.depth).toBe(0)
    expect(tree.find((n) => n.id === 'c')!.depth).toBe(1)
    expect(tree.find((n) => n.id === 'b')!.depth).toBe(0)
  })

  it('сортирует по-русски внутри одного уровня', () => {
    const flat = [f('1', 'Яблоко'), f('2', 'Апельсин')]
    const tree = folderTree(flat)
    expect(tree.map((n) => n.name)).toEqual(['Апельсин', 'Яблоко'])
  })

  it('не теряет папку с недостижимым/отсутствующим родителем', () => {
    const flat = [f('x', 'Сирота', 'no-such-parent-id')]
    const tree = folderTree(flat)
    expect(tree.map((n) => n.id)).toEqual(['x'])
  })

  it('folderLabel добавляет отступ и стрелку только для вложенных', () => {
    const flat = [f('a', 'Родитель'), f('c', 'Ребёнок', 'a')]
    const tree = folderTree(flat)
    const root = tree.find((n) => n.id === 'a')!
    const child = tree.find((n) => n.id === 'c')!
    expect(folderLabel(root)).toBe('Родитель')
    expect(folderLabel(child)).toContain('Ребёнок')
    expect(folderLabel(child)).not.toBe('Ребёнок')
  })
})
