import { describe, expect, it } from 'vitest'
import { buildReleaseFields, type PreviewColumn } from './releaseFields'

const COLS: PreviewColumn[] = [
  { column_index: 0, field_code: 'nomer', field_name: '№ п/п', data_type: 'text' },
  { column_index: 1, field_code: 'subekt', field_name: 'Субъект', data_type: 'text' },
  { column_index: 2, field_code: 'narastayuschim', field_name: 'нарастающим итогом', data_type: 'number' },
]

describe('buildReleaseFields', () => {
  it('берёт только оставленные столбцы и отмечает столбец названий строк', () => {
    const f = buildReleaseFields(COLS, { excluded: new Set([0]), labelColumn: 1 })
    expect(f.map((x) => x.column_index)).toEqual([1, 2])
    expect(f.find((x) => x.is_row_label)?.column_index).toBe(1)
  })

  it('коды прошлого выпуска важнее вычисленных по файлу', () => {
    // Ради этого правила всё и делается: показатель склеивается между неделями
    // по коду. Возьми система код из заголовка — прошлые недели отвалились бы.
    const f = buildReleaseFields(COLS, {
      excluded: new Set([0]), labelColumn: 1,
      templateCodes: { 1: 'subj', 2: 'obr_total' },
    })
    expect(f.map((x) => x.field_code)).toEqual(['subj', 'obr_total'])
  })

  it('переименование не меняет код', () => {
    const f = buildReleaseFields(COLS, {
      excluded: new Set([0]), labelColumn: 1,
      templateCodes: { 2: 'obr_total' },
      names: { 2: 'Обращения' },
    })
    const col = f.find((x) => x.column_index === 2)!
    expect(col.field_name).toBe('Обращения')
    expect(col.field_code).toBe('obr_total')
  })

  it('без шаблона используется код, вычисленный по файлу', () => {
    const f = buildReleaseFields(COLS, { excluded: new Set([0]), labelColumn: 1 })
    expect(f.map((x) => x.field_code)).toEqual(['subekt', 'narastayuschim'])
  })

  it('пустое имя откатывается к предложенному, а не уходит пустым', () => {
    const f = buildReleaseFields(COLS, {
      excluded: new Set([0]), labelColumn: 1, names: { 2: '   ' },
    })
    expect(f.find((x) => x.column_index === 2)?.field_name).toBe('нарастающим итогом')
  })

  it('без выбранного столбца названий строк выпуск не собирается', () => {
    expect(buildReleaseFields(COLS, { excluded: new Set(), labelColumn: null })).toEqual([])
  })
})
