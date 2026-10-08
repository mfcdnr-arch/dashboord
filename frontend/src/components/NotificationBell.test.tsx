import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('../api', () => ({
  getNotifications: vi.fn(async () => ({
    unread: 1,
    items: [{
      recipient_id: 'r1', event_type: 'data.new_fields', label: 'В форме появились новые графы',
      entity_type: 'object', entity_id: 'obj-1', created_at: '2026-10-01T09:00:00Z', is_read: false,
      payload: { object_name: 'РЦО', fields: [{ code: 'zap', name: 'Записались' }], total: 1,
        dashboards: [{ id: 'd1', name: 'РЦО: отчёт' }], dashboards_total: 1 },
    }],
  })),
  markNotificationRead: vi.fn(async () => ({})),
  markAllNotificationsRead: vi.fn(async () => ({})),
}))

import NotificationBell from './NotificationBell'

describe('колокольчик', () => {
  it('строка ленты — кнопка: её можно открыть с клавиатуры, и она ведёт на дашборд с новыми графами', async () => {
    const onNavigate = vi.fn()
    render(<NotificationBell staff onNavigate={onNavigate} />)
    const bell = await screen.findByRole('button', { name: 'Уведомления, непрочитанных: 1' })
    fireEvent.click(bell)
    const row = await screen.findByRole('button', { name: /В форме появились новые графы/ })
    expect(row.tagName).toBe('BUTTON')
    fireEvent.click(row)
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith({
      section: 'dashboards', dashboardId: 'd1', fallbackDashboardIds: [], objectId: 'obj-1',
      newFields: { datasetCode: '', codes: ['zap'] } }))
  })
})
