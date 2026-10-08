import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import DashboardsPage from './DashboardsPage'
import type { NewFieldsIntent } from '../lib/notifications'

/**
 * Переход из уведомления «в форме появились новые графы» — сценарии ревью
 * 08.10.2026, которые воспроизводились на настоящей странице:
 *  • намерение «залипало» и открывало окно при каждом следующем заходе;
 *  • при выключенных подсказках клик не делал ничего, а окно всплывало потом;
 *  • удалённый первый дашборд из уведомления давал ошибку вместо следующего;
 *  • частичный успех «Добавить N» читался как «не добавилось ничего».
 */

let suggest = true
let gone: string[] = []
let missing: Record<string, unknown>[] = []
let posts = 0
let failOnPost = 0

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function route(url: string, init?: RequestInit): Response {
  const u = url.split('?')[0]
  const method = init?.method || 'GET'
  if (method === 'POST' && u.startsWith('/dashboard-pages/') && u.endsWith('/widgets')) {
    posts += 1
    if (posts === failOnPost) return json({ detail: 'Сбой на втором' }, 500)
    const b = JSON.parse(String(init!.body))
    missing = missing.filter((f) => f.code !== b.config.value_field)
    return json({ id: `w${posts}` })
  }
  const m = /^\/dashboards\/(d\d)$/.exec(u)
  if (m) {
    if (gone.includes(m[1])) return json({ detail: 'Дашборд не найден' }, 404)
    return json({
      dashboard: { id: m[1], name: `Дашборд ${m[1]}`, description: null, publication_status: 'published',
        suggest_new_fields: suggest, created_at: '2026-09-01T00:00:00Z' },
      pages: [{ id: `p-${m[1]}`, name: 'Обзор', description: null, position: 0, layout_mode: 'grid' }],
    })
  }
  if (u.endsWith('/missing-fields')) return json({ count: missing.length, fields: missing, reviewed: 0 })
  if (u.startsWith('/dashboard-pages/') && u.endsWith('/widgets')) return json({ page_id: 'p', widgets: [] })
  if (u === '/dashboards') return json({ total: 0, limit: 50, offset: 0, items: [] })
  if (u === '/dashboards/recent') return json({ items: [] })
  if (u === '/dashboard-directions') return json({ items: [], without: 0, manage: true })
  if (u === '/metrics/data-sources') return json({ datasets: [], metrics: [] })
  if (u.endsWith('/report-dates')) return json({ dates: [] })
  if (u.endsWith('/freshness')) return json({ as_of: null, datasets: 0 })
  if (u.endsWith('/data')) return json({ widgets: {} })
  return json([])
}

beforeEach(() => {
  suggest = true; gone = []; posts = 0; failOnPost = 0
  missing = [
    { code: 'zap', name: 'Записались', dataset_code: 'f1' },
    { code: 'otk', name: 'Отказано', dataset_code: 'f1' },
  ]
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => route(String(url), init)))
})

const intent = (over: Partial<NewFieldsIntent> = {}): NewFieldsIntent => ({
  dashboardId: 'd1', datasetCode: 'f1', codes: ['zap'], fallbackDashboardIds: [], objectId: 'obj-1', seq: 1, ...over,
})

describe('переход из уведомления о новых графах', () => {
  it('намерение забирается один раз — повторный заход на дашборд окна не открывает', async () => {
    const consumed = vi.fn()
    const r = render(<DashboardsPage canManage initialDashboardId="d1" navSeq={1}
      newFieldsIntent={intent()} onNewFieldsConsumed={consumed} />)
    await screen.findByText('Новые графы формы')
    expect(consumed).toHaveBeenCalledTimes(1)
    expect(screen.getAllByText('из уведомления')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }))
    r.unmount()
    // App сбросил намерение — страница монтируется заново без него.
    render(<DashboardsPage canManage initialDashboardId="d1" navSeq={1} newFieldsIntent={null} />)
    await screen.findByText('Дашборд d1')
    await new Promise((res) => setTimeout(res, 150))
    expect(screen.queryByText('Новые графы формы')).toBeNull()
  })

  it('подсказки выключены — окно всё равно открывается по клику и говорит почему', async () => {
    suggest = false
    render(<DashboardsPage canManage initialDashboardId="d1" navSeq={1} newFieldsIntent={intent()} />)
    await screen.findByText('Новые графы формы')
    expect(screen.getByText(/Подсказки о новых графах на этом дашборде выключены/)).toBeInTheDocument()
  })

  it('первый дашборд уведомления удалён — следующий, а без них — объект формы', async () => {
    gone = ['d1']
    render(<DashboardsPage canManage initialDashboardId="d1" navSeq={1}
      newFieldsIntent={intent({ fallbackDashboardIds: ['d2'] })} />)
    await screen.findByText('Новые графы формы')
    expect(await screen.findByText('Дашборд d2')).toBeInTheDocument()

    gone = ['d1', 'd2']
    const toObject = vi.fn()
    render(<DashboardsPage canManage initialDashboardId="d1" navSeq={1} onOpenObject={toObject}
      newFieldsIntent={intent({ fallbackDashboardIds: ['d2'], seq: 2 })} />)
    await waitFor(() => expect(toObject).toHaveBeenCalledWith('obj-1'))
  })

  it('частичный успех «Добавить» назван: сколько добавлено и что не вышло', async () => {
    failOnPost = 2
    render(<DashboardsPage canManage initialDashboardId="d1" navSeq={1}
      newFieldsIntent={intent({ codes: ['zap', 'otk'] })} />)
    await screen.findByText('Новые графы формы')
    fireEvent.click(screen.getByRole('button', { name: 'Добавить 2' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Добавлено 1 из 2. Остальные не добавлены: Сбой на втором')
  })
})
