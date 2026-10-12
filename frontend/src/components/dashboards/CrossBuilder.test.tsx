// Конструктор показателя между формами: собрать «числитель ÷ знаменатель»
// из граф разных форм, подставить готовый показатель одним выбором.
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import CrossBuilder, { crossValid, emptyCross } from './CrossBuilder'
import type { CrossSpec, DataSources } from '../../api'

const sources = {
  metrics: [],
  datasets: [
    { code: 'wait', name: 'Время', object: null, folder: null, document: null, dates: [], rows: [],
      fields: [{ code: 'tickets', name: 'Всего выдано талонов', data_type: 'number' },
               { code: 'wait', name: 'Среднее время ожидания', data_type: 'number' }] },
    { code: 'win', name: 'Окна', object: null, folder: null, document: null, dates: [], rows: [],
      fields: [{ code: 'windows', name: 'Количество работающих окон', data_type: 'number' }] },
  ],
} as unknown as DataSources

const preset = {
  key: 'tickets_per_window', name: 'Талонов на окно', unit: null, hint: '',
  cross: { num: [{ dataset_code: 'wait', field: 'tickets' }], den: [{ dataset_code: 'win', field: 'windows' }], unit: null },
  bind: { dataset_code: 'wait', field: 'tickets' },
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ indicators: [preset] }), { status: 200 })))
})

describe('CrossBuilder', () => {
  it('пустой показатель годен, только когда у каждой части есть форма и графа', () => {
    const e = emptyCross(sources)
    expect(e.num[0]).toEqual({ dataset_code: 'wait', field: 'tickets' })
    expect(crossValid(e)).toBe(true)
    expect(crossValid({ num: [], den: e.den })).toBe(false)
    expect(crossValid({ num: [{ dataset_code: 'wait', field: '' }], den: e.den })).toBe(false)
  })

  it('готовый показатель подставляет части и своё имя — оно станет подписью оси', async () => {
    const onChange = vi.fn()
    render(<CrossBuilder sources={sources} value={emptyCross(sources)} onChange={onChange} />)
    const select = await screen.findByDisplayValue('свой (собрать ниже)')
    await waitFor(() => expect(screen.getByRole('option', { name: 'Талонов на окно' })).toBeTruthy())
    fireEvent.change(select, { target: { value: 'tickets_per_window' } })
    const got: CrossSpec = onChange.mock.calls[onChange.mock.calls.length - 1][0]
    expect(got.den).toEqual([{ dataset_code: 'win', field: 'windows' }])
    expect(got.name).toBe('Талонов на окно')
  })

  it('правка частей руками снимает имя готового и привязку порога к ушедшей графе', () => {
    const onChange = vi.fn()
    const v: CrossSpec = { num: [{ dataset_code: 'wait', field: 'wait' }, { dataset_code: 'wait', field: 'tickets' }],
      den: [{ dataset_code: 'wait', field: 'tickets' }], unit: 'мин', norm_field: 'wait', name: 'Взвешенное ожидание' }
    render(<CrossBuilder sources={sources} value={v} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Убрать часть 1: Числитель' }))
    const got: CrossSpec = onChange.mock.calls[onChange.mock.calls.length - 1][0]
    expect(got.num).toEqual([{ dataset_code: 'wait', field: 'tickets' }])
    expect(got.name).toBeUndefined()
    expect(got.norm_field).toBeUndefined()
  })
})
