import { describe, expect, it } from 'vitest'
import type { NotificationItem } from '../api'
import { message, targetOf } from './notifications'

const item = (event_type: string, payload: Record<string, unknown>, entity_id = 'obj-1'): NotificationItem => ({
  recipient_id: 'r1', event_type, label: 'Заголовок', entity_type: 'object', entity_id,
  payload, created_at: '2026-10-01T09:00:00Z', is_read: false,
})

const NEW_ONE = {
  dataset_code: 'rco_daily', object_name: 'РЦО — ежедневный отчёт', period: '2026-09-14',
  fields: [{ code: 'zap', name: 'ИП Хиневич · Принято, ед.' }], total: 1, gone: 0,
  dashboards: [{ id: 'd1', name: 'РЦО: ежедневный отчёт' }], dashboards_total: 1,
}

describe('уведомление «в форме появились новые графы»', () => {
  it('называет форму, отчёт, графу и задаёт вопрос', () => {
    const t = message(item('data.new_fields', NEW_ONE))
    expect(t).toContain('«РЦО — ежедневный отчёт»')
    expect(t).toContain('отчёт за 14.09.2026')
    expect(t).toContain('появилась новая графа — «ИП Хиневич · Принято, ед.»')
    expect(t).toContain('Дашборд «РЦО: ежедневный отчёт» её не показывает — добавить виджет?')
    expect(t).not.toContain('переименование')
  })

  it('много граф — первые три и «ещё N»; несколько дашбордов — во множественном числе', () => {
    const fields = Array.from({ length: 10 }, (_, i) => ({ code: `f${i}`, name: `Графа ${i}` }))
    const t = message(item('data.new_fields', {
      ...NEW_ONE, fields, total: 10,
      dashboards: [{ id: 'd1', name: 'А' }, { id: 'd2', name: 'Б' }, { id: 'd3', name: 'В' }], dashboards_total: 3,
    }))
    expect(t).toContain('появились новые графы (10) — «Графа 0», «Графа 1», «Графа 2» и ещё 7.')
    expect(t).toContain('Дашборды «А», «Б» и ещё 1 их не показывают')
  })

  it('пропавшие графы прошлого отчёта названы как возможное переименование', () => {
    const t = message(item('data.new_fields', { ...NEW_ONE, gone: 35, total: 35 }))
    expect(t).toContain('пропали 35 граф прошлого отчёта — возможно, это переименование, а не новые графы')
  })

  it('ведёт на дашборд с отмеченными новыми графами; без дашборда — к объекту', () => {
    expect(targetOf(item('data.new_fields', NEW_ONE), true))
      .toEqual({ section: 'dashboards', dashboardId: 'd1', newFields: ['zap'] })
    expect(targetOf(item('data.new_fields', { ...NEW_ONE, dashboards: [] }), true))
      .toEqual({ section: 'objects', objectId: 'obj-1' })
  })
})

describe('прежние события не сломаны выносом в lib', () => {
  it('комментарий к дашборду говорит, где и кто, а не повторяет заголовок', () => {
    const t = message(item('dashboard.comment', { dashboard_name: 'КПЭ', author: 'Иванов', snippet: 'Проверьте июль' }))
    expect(t).toBe('«КПЭ» — Иванов: Проверьте июль')
  })

  it('дыра в ряду и переходы прежних типов', () => {
    const t = message(item('data.gap', { object_name: 'МВД', missing: ['2026-08-26'], cadence_days: 7 }))
    expect(t).toContain('нет отчёта за 26.08.2026')
    expect(targetOf(item('data.gap', {}), true)).toEqual({ section: 'objects', objectId: 'obj-1' })
    expect(targetOf(item('appeal.replied', {}, 'a1'), false)).toEqual({ section: 'profile', appealId: 'a1' })
    expect(targetOf(item('unknown.type', {}), true)).toBeNull()
  })
})
