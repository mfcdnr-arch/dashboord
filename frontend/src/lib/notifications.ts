import type { NotificationItem } from '../api'
import { elideMiddle, plural } from './text'

/**
 * Текст и переход уведомления — отдельно от колокольчика.
 *
 * Жили внутри `NotificationBell` и не были покрыты ни одним тестом: регрессию
 * в тексте или в переходе можно было заметить только руками в браузере.
 * Заголовок (`label`) по-прежнему приходит с сервера (`EVENT_LABELS`), здесь —
 * тело и цель перехода. Новый тип события требует ветки в обеих функциях,
 * иначе тело повторит заголовок, а клик никуда не поведёт.
 */

export type NotifyTarget = {
  section: string
  appealId?: string
  dashboardId?: string
  objectId?: string
  /** Открыть на дашборде окно новых граф и отметить эти графы формы. Форма —
   *  обязательно: у двух форм дашборда коды граф могут совпасть. */
  newFields?: { datasetCode: string; codes: string[] }
  /** Куда идти, если дашборд из уведомления успели удалить: остальные
   *  дашборды формы по порядку, затем объект формы (`objectId`). */
  fallbackDashboardIds?: string[]
}

/**
 * «Добавить виджет?» из уведомления — что страница дашборда должна сделать:
 * открыть дашборд и окно новых граф с отмеченными графами формы. Одноразовое:
 * страница забирает его и сообщает об этом (`onNewFieldsConsumed`), иначе окно
 * всплывало бы при каждом следующем заходе на этот дашборд (найдено ревью 08.10).
 */
export type NewFieldsIntent = {
  dashboardId: string
  datasetCode: string
  codes: string[]
  fallbackDashboardIds: string[]
  objectId?: string
  seq: number
}

export function fmtDt(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

/** Отчётные даты показываем по-русски: в системе принят ДД.ММ.ГГГГ. */
export function ruDate(v: unknown): string {
  const s = String(v ?? '')
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s.split('-').reverse().join('.') : s
}

type Named = { id?: string; code?: string; name?: string }
const list = (v: unknown): Named[] => (Array.isArray(v) ? v.filter((x) => x && typeof x === 'object') : [])
const quoted = (names: string[]) => names.map((n) => `«${n}»`).join(', ')

/**
 * Графы одной услуги — одной строкой. Имена граф РЦО по 190 знаков и приходят
 * тройками «Принято / Выдано / Отказ» одной услуги: три полных имени давали
 * уведомление на 762 знака с трижды повторённым названием услуги (замер ревью
 * 08.10). Голова имени (всё до последнего разделителя) — одна на группу, и её
 * середина при нужде схлопывается; полный список — в окне дашборда.
 */
function groupFieldNames(names: string[]): { text: string; count: number }[] {
  const groups: { head: string; tails: string[]; first: string }[] = []
  for (const name of names) {
    const sep = name.includes(' · ') ? ' · ' : (name.includes(': ') ? ': ' : '')
    const cut = sep ? name.lastIndexOf(sep) : -1
    const head = cut > 0 ? name.slice(0, cut) : ''
    const tail = cut > 0 ? name.slice(cut + sep.length) : name
    const last = groups[groups.length - 1]
    if (head && last && last.head === head) last.tails.push(tail)
    else groups.push({ head, tails: [tail], first: name })
  }
  return groups.map((g) => (g.head && g.tails.length > 1
    ? { text: `«${elideMiddle(g.head, 70)}» — ${g.tails.join(', ')}`, count: g.tails.length }
    : { text: `«${elideMiddle(g.first, 90)}»`, count: 1 }))
}

/** «В форме появились новые графы»: что появилось, где не показано и вопрос. */
function newFieldsText(p: Record<string, unknown>): string {
  const fields = list(p.fields).map((f) => String(f.name ?? f.code ?? ''))
  const total = Number(p.total) || fields.length
  const shown = groupFieldNames(fields).slice(0, 3)
  const more = total - shown.reduce((n, g) => n + g.count, 0)
  const gone = Number(p.gone) || 0
  const dash = list(p.dashboards).map((d) => String(d.name ?? ''))
  const dashTotal = Number(p.dashboards_total) || dash.length
  const one = total === 1
  let s = `Форма «${p.object_name ?? p.dataset_code}»`
    + `${p.period ? ` (отчёт за ${ruDate(p.period)})` : ''}: `
    // Точка с запятой — только между группами: внутри группы стоят запятые.
    + `${one ? 'появилась новая графа' : `появились новые графы (${total})`} — `
    + `${shown.map((g) => g.text).join(shown.some((g) => g.count > 1) ? '; ' : ', ')}`
    + `${more > 0 ? ` и ещё ${more}` : ''}.`
  // Переименование заголовка даёт новый код графы, и система принимает его
  // за новую графу. Подавлять по догадке нельзя — называем, что видно.
  if (gone > 0) {
    s += ` В том же отчёте ${plural(gone, 'пропала', 'пропали', 'пропали')} ${gone} `
      + `${plural(gone, 'графа', 'графы', 'граф')} прошлого отчёта — возможно, это переименование, а не новые графы.`
  }
  if (dash.length) {
    const names = quoted(dash.slice(0, 2)) + (dashTotal > 2 ? ` и ещё ${dashTotal - 2}` : '')
    s += ` ${dashTotal > 1 ? 'Дашборды' : 'Дашборд'} ${names} ${one ? 'её' : 'их'} не `
      + `${dashTotal > 1 ? 'показывают' : 'показывает'} — добавить виджет?`
  }
  return s
}

export function message(n: NotificationItem): string {
  const p = n.payload || {}
  if (n.event_type === 'data.stale') return `Объект «${p.object_name}»: нет новых данных ${p.days_since_upload} дн. (порог ${p.threshold_days}).`
  if (n.event_type === 'data.missing') {
    return `Объект «${p.object_name}»: отчёт за ${ruDate(p.expected_period)} не поступил `
      + `(форма приходит раз в ${p.cadence_days} дн., последний — за ${ruDate(p.last_period)}).`
  }
  // Дыра ВНУТРИ ряда: ряд продолжился, и «отчёт не поступил» тут неверно —
  // отчёты идут, просто одного дня в них нет. Даты называем поимённо: без них
  // человеку негде начать искать.
  if (n.event_type === 'data.gap') {
    const miss = (Array.isArray(p.missing) ? p.missing : []).map(ruDate)
    const shown = miss.slice(0, 5).join(', ')
    return `Объект «${p.object_name}»: в ряду отчётов пропуск — нет ${miss.length > 1 ? 'отчётов' : 'отчёта'} за `
      + `${shown}${miss.length > 5 ? ` и ещё ${miss.length - 5}` : ''} `
      + `(форма приходит раз в ${p.cadence_days} дн.). Данные за этот период на дашбордах не учтены.`
  }
  if (n.event_type === 'data.new_fields') return newFieldsText(p)
  if (n.event_type === 'dashboard.review_requested') {
    return `«${p.dashboard_name}» ждёт проверки${p.author ? ` — отправил ${p.author}` : ''}.`
  }
  // Раньше тело комментария повторяло заголовок, хотя в событии есть и дашборд,
  // и автор, и начало текста.
  if (n.event_type === 'dashboard.comment') {
    return `«${p.dashboard_name ?? 'Дашборд'}»${p.author ? ` — ${p.author}` : ''}${p.snippet ? `: ${p.snippet}` : ''}`
  }
  if (n.event_type === 'data.retention') return `Ретенция: удалено релизов — ${p.deleted_releases} (окно ${p.window_months} мес.).`
  // Предупреждение, а не отчёт об удалении: планировщик ничего не удаляет,
  // он зовёт человека решить. Поэтому в тексте — что именно под отсечкой и
  // прямое указание, что данные ещё на месте.
  if (n.event_type === 'data.retention_due') {
    const k = Number(p.releases) || 0
    return `Под окно хранения (${p.window_months} мес.) попадает ${k} `
      + `${plural(k, 'выпуск', 'выпуска', 'выпусков')} данных`
      + `${p.oldest ? `, самый ранний — за ${ruDate(p.oldest)}` : ''}`
      + `${p.values ? ` (значений: ${p.values})` : ''}. `
      + 'Ничего не удалено: откройте «Настройки» → «Хранение данных», посмотрите список и решите сами.'
  }
  if (n.event_type === 'widget.created.no_explicit_access') return `Новый виджет без явных прав: ${p.widget_name ?? ''}`
  if (n.event_type === 'system.degraded') {
    // Называем ПРИЧИНУ: «автопочинка не помогла» без неё отправляет человека
    // разбираться вслепую, а чаще всего дело в ресурсах, которые приложение
    // чинить и не умеет.
    const why = Array.isArray(p.reasons) && p.reasons.length ? ` Что не так: ${p.reasons.join('; ')}.` : ''
    return `Система в плохом состоянии (${p.status_after ?? 'degraded'}).${why}`
      + ' Посмотрите раздел «Отчёты» → «Здоровье системы».'
  }
  // Воркер перезапущен хостовым сторожем. Сообщаем ОБЯЗАТЕЛЬНО, в том числе об
  // удачном перезапуске: молчание скрыло бы, что воркер падает регулярно.
  if (n.event_type === 'system.worker_restarted') return p.healthy
    ? 'Фоновый воркер не отмечался и был перезапущен автоматически — конвейер данных снова работает. Если это повторяется, стоит разобраться с причиной: «Отчёты» → «Здоровье системы».'
    : 'Фоновый воркер перезапущен автоматически, но так и не отметился: загрузка файлов, выпуск данных и уведомления остановлены. Нужен разбор причины — «Отчёты» → «Здоровье системы».'
  if (n.event_type === 'appeal.created' || n.event_type === 'appeal.message') return `${p.author ?? ''}: ${p.snippet ?? ''}`
  if (n.event_type === 'appeal.replied') return `${p.author ?? 'Администратор'} ответил на ваше обращение: ${p.snippet ?? ''}`
  if (n.event_type === 'data.auto_released') {
    return `Данные из «${p.document ?? 'файла'}» за ${ruDate(p.period)} выпущены автоматически`
      + `${p.folder ? ` (папка «${p.folder}»)` : ''}: форма совпала с прошлым отчётом, замечаний нет. `
      + `Значений: ${p.values ?? '—'}. Уже считаются на дашбордах.`
  }
  if (n.event_type === 'appeal.seen') return `${p.author ?? 'Администратор'} открыл ваше обращение${p.subject ? ` «${p.subject}»` : ''} — ответ придёт следующим уведомлением.`
  return n.label
}

/**
 * Куда ведёт уведомление.
 *
 * Уведомление без перехода — тупик: человек прочитал «ztest: не работает
 * выгрузка» и должен сам вспомнить, в каком разделе искать это обращение.
 * Поэтому каждое событие знает свою сущность (entity_type/entity_id), и клик
 * открывает именно её. Обычного пользователя ведём в «Кабинет»: раздела
 * «Обращения» у него нет, его переписка живёт там.
 */
export function targetOf(n: NotificationItem, staff: boolean): NotifyTarget | null {
  const id = n.entity_id || undefined
  if (n.event_type.startsWith('appeal.')) {
    return { section: staff ? 'appeals' : 'profile', appealId: id }
  }
  if (n.event_type === 'dashboard.comment' || n.event_type === 'dashboard.review_requested') {
    return { section: 'dashboards', dashboardId: id }
  }
  // Новые графы: на первый дашборд формы — сразу с окном «добавить виджет?» и
  // отмеченными новыми графами. Список дашбордов — снимок на момент
  // объявления, и первый из них могли успеть удалить: тогда страница пробует
  // следующие, а за ними — объект, где лежит форма.
  if (n.event_type === 'data.new_fields') {
    const p = n.payload || {}
    const dash = list(p.dashboards).map((d) => String(d.id ?? '')).filter(Boolean)
    const objectId = (p.object_id as string | undefined) || id
    if (dash.length) {
      return { section: 'dashboards', dashboardId: dash[0], fallbackDashboardIds: dash.slice(1), objectId,
        newFields: { datasetCode: String(p.dataset_code ?? ''),
          codes: list(p.fields).map((f) => String(f.code ?? '')).filter(Boolean) } }
    }
    return { section: 'objects', objectId }
  }
  if (n.event_type === 'data.stale' || n.event_type === 'data.missing' || n.event_type === 'data.gap') {
    return { section: 'objects', objectId: id }
  }
  // У выпуска своего экрана нет — ведём к объекту, где лежит файл (id берём из
  // payload: entity_id здесь — сам выпуск).
  if (n.event_type === 'data.auto_released') {
    const oid = (n.payload || {}).object_id as string | undefined
    return oid ? { section: 'objects', objectId: oid } : { section: 'objects' }
  }
  if (n.event_type === 'data.retention') return { section: 'settings' }
  if (n.event_type === 'data.retention_due') return { section: 'settings' }
  if (n.event_type === 'system.degraded') return { section: 'reports' }
  if (n.event_type === 'system.worker_restarted') return { section: 'reports' }
  return null
}
