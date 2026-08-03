import type { Folder } from '../api'

// Плоский список папок (folders.parent_folder_id из БД) → плоский список в
// порядке дерева (родитель всегда перед детьми) с полем depth для отступа.
// Папки объекта в этом проекте не глубокие, поэтому полноценный виджет-дерево
// с раскрытием/сворачиванием избыточен: достаточно отступов в select/списке.
export interface FolderNode extends Folder {
  depth: number
}

export function folderTree(folders: Folder[]): FolderNode[] {
  const byParent = new Map<string, Folder[]>()
  for (const f of folders) {
    const key = f.parent_folder_id || ''
    if (!byParent.has(key)) byParent.set(key, [])
    byParent.get(key)!.push(f)
  }
  const seen = new Set<string>()
  const out: FolderNode[] = []
  function walk(parentKey: string, depth: number) {
    const children = (byParent.get(parentKey) || []).slice().sort((a, b) => a.name.localeCompare(b.name, 'ru'))
    for (const c of children) {
      if (seen.has(c.id)) continue
      seen.add(c.id)
      out.push({ ...c, depth })
      walk(c.id, depth + 1)
    }
  }
  walk('', 0)
  // Подстраховка: родитель не найден в списке (не должно случаться) — не теряем папку.
  for (const f of folders) if (!seen.has(f.id)) out.push({ ...f, depth: 0 })
  return out
}

// NBSP (не обычный пробел) для отступа — обычные пробелы браузер схлопывает внутри <option>.
export function folderLabel(f: FolderNode): string {
  return '  '.repeat(f.depth) + (f.depth > 0 ? '↳ ' : '') + f.name
}
