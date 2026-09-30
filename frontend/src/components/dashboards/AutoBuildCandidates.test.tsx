import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { previewWidget, type AutoPlanCandidate } from '../../api'
import AutoBuildCandidates from './AutoBuildCandidates'

// Предпросмотр считает сервер и рисует тело виджета — в тесте подменяем оба:
// проверяем, ЧТО спрашивается и когда, а не отрисовку графиков.
vi.mock('../../api', async (orig) => ({
  ...(await orig<typeof import('../../api')>()),
  previewWidget: vi.fn(async () => ({ value: 42 })),
}))
vi.mock('../WidgetView', () => ({
  WidgetPreviewBody: ({ data }: { data: { value: number } }) => <div>тело предпросмотра {data.value}</div>,
}))

const cand = (key: string, over: Partial<AutoPlanCandidate> = {}): AutoPlanCandidate => ({
  key, dataset_code: 't', page: 'Обзор', name: key, widget_type: 'kpi', type_label: 'KPI (число)',
  recommended: true, reason: '', build: true, cards: 1, explain: { what: 'Что это.' },
  explain_text: 'Что это.', config: { dataset_code: 't' }, ...over,
})

const LIST = [
  cand('ИТОГО', { widget_type: 'kpi_group', type_label: 'Показатель в разрезах' }),
  cand('Росреестр', { page: 'Росреестр' }),
  cand('Светофор', {
    widget_type: 'status_grid', type_label: 'Светофор', recommended: false, build: false, cards: 0,
    reason: 'плана у графы нет — все плитки будут одного цвета',
  }),
]

describe('AutoBuildCandidates — рекомендованные отмечены, остальное с причиной', () => {
  it('рекомендованные отмечены и разложены по страницам будущего дашборда', () => {
    render(<AutoBuildCandidates candidates={LIST} include={[]} exclude={[]} onToggle={() => {}} />)
    expect(screen.getByRole('checkbox', { name: 'ИТОГО' })).toBeChecked()
    expect(screen.getByText('Росреестр', { selector: 'div' })).toBeInTheDocument()
    // Нерекомендованного в основном списке нет — он в свёрнутом разделе.
    expect(screen.queryByRole('checkbox', { name: /Светофор/ })).toBeNull()
    expect(screen.getByRole('button', { name: /Ещё можно добавить \(1\)/ })).toHaveAttribute('aria-expanded', 'false')
  })

  it('снятый человеком — не отмечен сразу, не дожидаясь пересчёта', () => {
    render(<AutoBuildCandidates candidates={LIST} include={[]} exclude={['ИТОГО']} onToggle={() => {}} />)
    expect(screen.getByRole('checkbox', { name: 'ИТОГО' })).not.toBeChecked()
  })

  it('вид и ⓘ не входят в имя галочки — диктор читает только название', () => {
    render(<AutoBuildCandidates candidates={LIST} include={[]} exclude={[]} onToggle={() => {}} />)
    // Точное имя: без «Показатель в разрезах» и «Что покажет…».
    expect(screen.getByRole('checkbox', { name: 'ИТОГО' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Что покажет «ИТОГО»' })).toBeInTheDocument()
  })

  it('«Ещё можно добавить»: причина названа, добавить можно, поиск сужает', () => {
    const onToggle = vi.fn()
    render(<AutoBuildCandidates candidates={LIST} include={[]} exclude={[]} onToggle={onToggle} />)
    fireEvent.click(screen.getByRole('button', { name: /Ещё можно добавить/ }))
    expect(screen.getByText(/все плитки будут одного цвета/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Добавить «Светофор»' }))
    expect(onToggle).toHaveBeenCalledWith(LIST[2])

    fireEvent.change(screen.getByRole('textbox', { name: /Поиск/ }), { target: { value: 'рейтинг' } })
    expect(screen.getByText('Ничего не найдено.')).toBeInTheDocument()
  })

  it('ключ сразу в «добавить» и «снять» — не отмечен: правило то же, что у сборки', () => {
    // 🔴 Ревью этапа 2: мастер показывал галочку, а сервер виджет не создавал.
    render(<AutoBuildCandidates candidates={LIST} include={['Светофор']} exclude={['Светофор']} onToggle={() => {}} />)
    expect(screen.getByRole('checkbox', { name: /Светофор/ })).not.toBeChecked()
  })

  it('добавленный человеком переходит в основной список и помечен «добавлен вами»', () => {
    render(<AutoBuildCandidates candidates={LIST} include={['Светофор']} exclude={[]} onToggle={() => {}} />)
    expect(screen.getByRole('checkbox', { name: /Светофор/ })).toBeChecked()
    expect(screen.getByText(/добавлен вами/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Ещё можно добавить/ })).toBeNull()
  })

  it('предпросмотр — настоящий виджет по конфигурации кандидата, один за раз', async () => {
    const withCfg = [
      cand('ИТОГО', { config: { dataset_code: 't', value_fields: ['a'] } }),
      cand('Росреестр', { page: 'Росреестр', config: { dataset_code: 't', value_field: 'b' } }),
    ]
    render(<AutoBuildCandidates candidates={withCfg} include={[]} exclude={[]} onToggle={() => {}} />)
    const eye = screen.getByRole('button', { name: 'Предпросмотр «ИТОГО»' })
    expect(eye).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(eye)
    expect(eye).toHaveAttribute('aria-expanded', 'true')
    expect(await screen.findByText('тело предпросмотра 42')).toBeInTheDocument()
    // Ровно конфигурация планировщика — показано то, что будет создано.
    expect(previewWidget).toHaveBeenCalledWith({
      widget_type: 'kpi', name: 'ИТОГО', config: { dataset_code: 't', value_fields: ['a'] } })

    // Второй открывает свой и закрывает первый: считать все сразу незачем.
    fireEvent.click(screen.getByRole('button', { name: 'Предпросмотр «Росреестр»' }))
    expect(eye).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getAllByRole('region', { name: /Предпросмотр/ })).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: 'Предпросмотр «Росреестр»' }))
    expect(screen.queryByRole('region', { name: /Предпросмотр/ })).toBeNull()
  })
})
