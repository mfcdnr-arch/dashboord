import type { Widget } from '../../api'
import { elideMiddle } from '../../lib/text'
import InfoTip from '../InfoTip'
import WidgetView from '../WidgetView'
import { WT, alertBtn, editBtn, rmBtn, widgetCard, wtBadge } from './shared'

/**
 * Карточка виджета на странице дашборда.
 *
 * Вынесена из DashboardsPage, потому что рисуют её ДВЕ раскладки — свободная
 * сетка и «поток». Пока карточка жила внутри сетки, вторая раскладка означала
 * бы копию сотни строк, которая разошлась бы с оригиналом при первой правке.
 * Раскладка отвечает только за МЕСТО и РАЗМЕР; всё, что внутри рамки, — здесь.
 */
export function WidgetCard({
  w, data, error, alert, isCollapsed, onToggleCollapse, highlighted, editMode, canManage,
  hasSources, onEdit, onAlerts, onDelete, tip,
  reloadKey, from, to, row, asOf, onPick, batched, onNavigate, onAddField, onOpenAppeals, shortName,
}: {
  w: Widget
  data?: Record<string, unknown>
  error?: string
  alert?: { color: string; bg: string } | null
  isCollapsed: boolean
  onToggleCollapse: (id: string) => void
  highlighted: boolean
  editMode: boolean
  canManage: boolean
  hasSources: boolean
  onEdit: (w: Widget) => void
  onAlerts: (w: Widget) => void
  onDelete: (w: Widget) => void
  tip: string
  reloadKey: number
  from?: string
  to?: string
  row?: string
  asOf?: string
  onPick: (name: string) => void
  batched: boolean
  onNavigate: (dashboardId: string, pageId: string | null, widgetId: string) => void
  onAddField?: (field: string, name: string, datasetCode: string) => Promise<void>
  /**
   * Имя без общей для всей страницы части.
   *
   * У госформы имена показателей отличаются серединой («Количество
   * обращений … нарастающим итогом» / «… за отчётную неделю»), и в
   * заголовке карточки повторяющееся начало занимало две-три строки —
   * визуально тяжелее самого числа. Полное имя остаётся в подсказке.
   */
  shortName?: string
  onOpenAppeals?: () => void
}) {
  return (
        <div data-widget-id={w.id} style={{ ...widgetCard, height: '100%', overflow: 'hidden',
          display: 'flex', flexDirection: 'column',
          // Подсветка цели перехода из меню «↗ куда дальше»: гаснет
          // сама через пару секунд, чтобы не остаться навсегда.
          ...(highlighted
            ? { boxShadow: '0 0 0 3px var(--accent)', transition: 'box-shadow .2s' }
            : { transition: 'box-shadow .4s' }),
          // Состояние показателя — лентой по ВСЕЙ карточке, вместе с
          // именем: раньше красилось только тело под шапкой, и на
          // странице из полутора десятков карточек «где плохо»
          // приходилось искать глазами по цифрам.
          ...(alert
            ? { borderLeft: `4px solid ${alert.color}`,
                background: alert.bg }
            : {}),
          outline: editMode ? '1px dashed var(--text-faint)' : 'none' }}>
          {/* Шапка в два ряда: сверху ИМЯ (оно главное — виджет без
              названия ничего не сообщает), снизу значок типа и
              действия. Когда всё было одной строкой, на узкой
              карточке значок типа и четыре кнопки съедали её
              целиком, а имя сжималось до нулевой ширины и
              пропадало. У СВЁРНУТОГО виджета высота всего 40px —
              там оставляем только ▸ и имя, иначе не поместится
              даже кнопка разворачивания. */}
          <div className={editMode ? 'wdrag' : ''} style={{ marginBottom: 4, flexShrink: 0, cursor: editMode ? 'move' : 'default' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'nowrap' }}>
              <button className="wnodrag" style={{ ...editBtn, cursor: 'pointer', flexShrink: 0 }} onClick={() => onToggleCollapse(w.id)}
                title={isCollapsed ? 'Развернуть виджет' : 'Свернуть виджет'}>{isCollapsed ? '▸' : '▾'}</button>
              {/* У развёрнутого виджета имя занимает до ДВУХ строк: имена
                  из авто-сборки длинные («… · Факт · нарастающим итогом»),
                  и в одну строку на карточке видно только «Внедре…» —
                  руководитель не понимает, что за число перед ним.
                  У свёрнутого (высота 40px) вторая строка не помещается. */}
              {/* Обрезает ЛИБО стиль (по строкам), ЛИБО elideMiddle —
                  вместе они давали двойное многоточие («обращений……»).
                  У развёрнутого виджета обрезаем стилем: три строки на
                  карточке шириной в треть ряда вмещают осмысленный
                  кусок имени, а полное имя — в подсказке. */}
              {/* Имя занимает ВСЮ ширину строки: на карточке в треть
                  ряда каждый соседний элемент отъедает у него столько,
                  что остаётся «Колич обр…» — проверено, значок ⓘ рядом
                  с именем именно к этому и приводил. Значок живёт
                  отдельной строкой ниже. */}
              <div style={{
                fontSize: 13, fontWeight: 600, flex: 1, minWidth: 0, overflow: 'hidden',
                ...(isCollapsed
                  ? { textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
                  : { display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', lineHeight: 1.2 }),
              }}
                title={w.name}>{isCollapsed ? elideMiddle(shortName || w.name, 70) : (shortName || w.name)}</div>
              {/* ⓘ — в строке с именем, а не отдельным рядом: свой ряд
                  стоил 21px, и на карточке в три ряда (144px) их не
                  хватало под само число. По ширине значок отнимает у
                  имени ~20px из 200 — три строки остаются читаемыми
                  (проверено: до двух строк ужимать нельзя, тогда от
                  имени остаётся «Колич обр…»). */}
              {!isCollapsed && !editMode && (
                <span style={{ flexShrink: 0, alignSelf: 'flex-start' }}><InfoTip text={tip} /></span>
              )}
            </div>
            {/* Служебный ряд (тип виджета, правка, пороги, удаление)
                показываем ТОЛЬКО в режиме правки. В обычном просмотре
                он съедал треть маленькой карточки — из-за него у KPI
                обрезалось само число, ради которого карточка и стоит.
                Значок ⓘ остаётся всегда: он объясняет, что за цифра.
                У зрителя режима правки нет, поэтому раньше ряд висел
                у него ПОСТОЯННО: бейдж типа занимал строку, и места
                под число оставалось меньше, чем у администратора —
                хотя именно зритель смотрит на цифру, а не правит. */}
            {!isCollapsed && editMode && (
              <div className="wnodrag" style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
                <span style={wtBadge}>{WT.find((x) => x.v === w.widget_type)?.t || w.widget_type}</span>
                <InfoTip text={tip} />
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                  {canManage && hasSources && <button style={editBtn} onClick={() => onEdit(w)} title="Изменить данные/тип виджета">✎</button>}
                  {canManage && ['kpi', 'gauge', 'plan_fact', 'dynamics'].includes(w.widget_type) && (
                    <button style={alertBtn} onClick={() => onAlerts(w)}
                      title="Пороги KPI-алерта (условное форматирование)">⚠</button>
                  )}
                  {canManage && <button style={rmBtn} onClick={() => onDelete(w)} title="Удалить">✕</button>}
                </span>
              </div>
            )}
          </div>
          {!isCollapsed && (
            <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflow: 'auto' }}>
              <WidgetView widgetId={w.id} reloadKey={reloadKey} from={from} to={to} row={row}
                pageAsOf={asOf}
                onPick={onPick}
                batched={batched} injData={data} injError={error}
                onNavigate={onNavigate}
                widgetName={w.name}
                onAddField={onAddField}
                onOpenAppeals={onOpenAppeals}
                stripe={false} />
            </div>
          )}
        </div>
  )
}
