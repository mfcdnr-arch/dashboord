import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { getWidgetRelated, type RelatedWidgetRef, type WidgetRelated } from '../../api'

const TYPE_RU: Record<string, string> = {
  kpi: 'карточка', gauge: 'спидометр', bar: 'столбцы', line: 'линия', pie: 'круговая',
  table: 'таблица', pivot: 'сводная', dynamics: 'динамика', compare: 'сравнение',
  plan_fact: 'план-факт', heatmap: 'тепловая карта', funnel: 'воронка', status_grid: 'светофор',
  waterfall: 'водопад', yoy: 'год к году', cross_dataset_compare: 'сравнение источников',
}

// «Куда дальше» от конкретной цифры (п. 1 списка заказчика, прототип на одном
// виджете). Дашборд отвечает «сколько», а следующий вопрос всегда «почему
// столько?» — и сегодня ответ ищут руками, вспоминая, в каком отчёте лежит
// показатель.
//
// Пункты меню НЕ настраиваются: их строит сервер из формул и настроек
// виджетов. Настроенная руками связка устаревает молча — форму меняют,
// показатель переименовывают, а пункт продолжает вести в никуда.
//
// Окно выводится порталом в body: карточка виджета обрезает содержимое
// (overflow: hidden), и меню внутри неё было бы срезано — ровно тот дефект,
// который уже ловили у подсказки ⓘ и у окна «подробнее».
export default function RelatedMenu(
  { widgetId, onClose, onOpenDrill, onNavigate }:
  {
    widgetId: string
    onClose: () => void
    onOpenDrill: () => void
    /** Переход к другому виджету: открыть его дашборд/страницу и показать
     *  сам виджет. Без widgetId переход к соседу на ТОЙ ЖЕ странице выглядел
     *  бы как «нажал — ничего не произошло». */
    onNavigate?: (dashboardId: string, pageId: string | null, widgetId: string) => void
  },
) {
  const [data, setData] = useState<WidgetRelated | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    getWidgetRelated(widgetId).then(setData).catch((e) => setErr((e as Error).message))
  }, [widgetId])

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const go = (r: RelatedWidgetRef) => {
    if (!onNavigate) return
    onClose()
    onNavigate(r.dashboard_id, r.page_id, r.widget_id)
  }

  return createPortal(
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>Куда посмотреть дальше</div>
            {data?.subject?.name && (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                {data.subject.kind === 'metric' ? 'Показатель' : 'Графа формы'}: {data.subject.name}
              </div>
            )}
          </div>
          <button style={{ ...xBtn, marginLeft: 'auto' }} onClick={onClose} title="Закрыть">✕</button>
        </div>

        {err && <div style={errBox}>{err}</div>}
        {!data && !err && <div style={muted}>Загрузка…</div>}

        {data && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Group title="Из чего складывается">
              <button style={itemBtn} onClick={() => { onClose(); onOpenDrill() }}>
                🔍 Формула, источник и первичные строки
              </button>
            </Group>

            <Group title="Где ещё показан этот показатель"
              empty={data.elsewhere.length === 0
                ? 'Больше нигде — этот виджет единственный. Если цифру ждут и в другом отчёте, её стоит туда добавить.'
                : undefined}>
              {data.elsewhere.map((r) => (
                <button key={r.widget_id} style={itemBtn} onClick={() => go(r)}
                  disabled={!onNavigate}
                  title={onNavigate ? 'Открыть этот виджет' : 'Переход доступен из режима просмотра дашборда'}>
                  <span style={badge}>{TYPE_RU[r.widget_type] || r.widget_type}</span>
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.widget_name}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-faint)', flexShrink: 0 }}>
                    {r.dashboard_name}{r.page_name ? ` · ${r.page_name}` : ''}
                  </span>
                </button>
              ))}
            </Group>

            <Group title="Соседи по форме"
              empty={data.siblings.length === 0 ? 'Других заполненных граф в этой форме нет.' : undefined}>
              {/* Соседей показываем перечнем, без перехода: они лежат в той же
                  форме, но собственного виджета у каждого может и не быть.
                  Обещать переход, которого нет, хуже, чем просто назвать их. */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {data.siblings.map((s) => (
                  <span key={s.field} style={chip} title={s.field}>{s.name}</span>
                ))}
              </div>
            </Group>

            <Group title="В динамике">
              {data.dynamics.available ? (
                <div style={muted}>
                  По этой форме есть {data.dynamics.periods} отчётных периодов
                  {data.dynamics.first && data.dynamics.last
                    && ` (с ${ru(data.dynamics.first)} по ${ru(data.dynamics.last)})`} — движение построить можно.
                  {data.elsewhere.some((r) => r.widget_type === 'dynamics')
                    && ' График динамики есть в списке выше.'}
                </div>
              ) : (
                <div style={muted}>
                  Отчётный период пока один — движение показывать не из чего.
                </div>
              )}
            </Group>
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}

function ru(iso: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.split('-').reverse().join('.') : iso
}

function Group({ title, empty, children }: { title: string; empty?: string; children?: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{title}</div>
      {empty ? <div style={muted}>{empty}</div>
        : <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>{children}</div>}
    </div>
  )
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex',
  alignItems: 'center', justifyContent: 'center', zIndex: 70, padding: 20,
}
const dialog: React.CSSProperties = {
  background: 'var(--surface)', borderRadius: 14, padding: 20, width: 620, maxWidth: '94vw',
  maxHeight: '86vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
}
const itemBtn: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
  padding: '7px 10px', borderRadius: 8, border: '1px solid var(--border-faint)',
  background: 'var(--surface-2)', color: 'var(--text)', fontSize: 13, cursor: 'pointer',
}
const badge: React.CSSProperties = {
  fontSize: 11, padding: '1px 8px', borderRadius: 8, background: 'var(--surface-3)',
  color: 'var(--text-2)', flexShrink: 0,
}
const chip: React.CSSProperties = {
  fontSize: 12, padding: '3px 10px', borderRadius: 12,
  background: 'var(--surface-3)', color: 'var(--text-2)',
}
const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 13, lineHeight: 1.5 }
const xBtn: React.CSSProperties = { border: 'none', background: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--text-muted)' }
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8,
}
