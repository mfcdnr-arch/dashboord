import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MissingFieldsDialog, type MissingField } from './MissingFieldsDialog'

const FIELDS: MissingField[] = [
  { code: 'a', name: 'Старая без виджета', dataset_code: 'f1', first_period: '2026-09-01', covered_by: [] },
  { code: 'zap', name: 'Записались', dataset_code: 'f1', first_period: '2026-09-14',
    covered_by: ['Первичные данные'] },
  // Тот же код у другой формы — отдельная графа, не дубль.
  { code: 'zap', name: 'Записались (МВД)', dataset_code: 'f2' },
]

describe('окно «новые графы формы»', () => {
  it('графы из уведомления отмечены и стоят первыми', () => {
    const onAdd = vi.fn()
    render(<MissingFieldsDialog fields={FIELDS} highlight={['zap']} onClose={() => {}} onAdd={onAdd} />)
    const boxes = screen.getAllByRole('checkbox') as HTMLInputElement[]
    expect(boxes.map((b) => b.checked)).toEqual([true, true, false])
    expect(screen.getAllByText('из уведомления')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Добавить 2' }))
    expect(onAdd.mock.calls[0][0].map((f: MissingField) => `${f.dataset_code}:${f.code}`)).toEqual(['f1:zap', 'f2:zap'])
  })

  it('без уведомления ничего не отмечено; сказано, когда графа появилась и где уже видна', () => {
    render(<MissingFieldsDialog fields={FIELDS} onClose={() => {}} onAdd={() => {}} />)
    expect((screen.getAllByRole('checkbox') as HTMLInputElement[]).every((b) => !b.checked)).toBe(true)
    expect(screen.getByText(/впервые в отчёте за 14\.09\.2026 · уже видна в «Первичные данные»/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeDisabled()
  })

  it('«больше не предлагать» отдаёт весь показанный список', () => {
    const onDismiss = vi.fn()
    render(<MissingFieldsDialog fields={FIELDS} onClose={() => {}} onAdd={() => {}} onDismiss={onDismiss} />)
    fireEvent.click(screen.getByRole('button', { name: 'Больше не предлагать 3 графы' }))
    expect(onDismiss).toHaveBeenCalledWith(FIELDS)
  })

  it('пустой список — объяснение, а не «Выбрано: 0 из 0»', () => {
    render(<MissingFieldsDialog fields={[]} highlight={['zap']} onClose={() => {}} onAdd={() => {}} />)
    expect(screen.getByText(/их уже добавили или отметили/)).toBeInTheDocument()
    expect(screen.queryByText(/Выбрано/)).toBeNull()
  })

  it('ошибка видна внутри окна и объявляется диктору', () => {
    render(<MissingFieldsDialog fields={FIELDS} error="Дашборд на проверке — правки заблокированы"
      onClose={() => {}} onAdd={() => {}} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Дашборд на проверке')
  })
})
