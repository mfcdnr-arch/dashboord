import { useEffect, useMemo, useRef, useState } from 'react'
import { pageReportDates, type Dashboard, type DashPage, type DashPreset } from '../../api'
import type { Density } from '../../lib/density'
import { PubBadge, input, linkDanger, presetChip } from './shared'

/**
 * Шапка ОТКРЫТОГО дашборда: крошка, имя, фильтры, вкладки страниц и строка
 * контекста — одним прилипающим блоком.
 *
 * Зачем понадобилась перестройка. Раньше над первым виджетом стояли ПЯТЬ полос
 * управления: ряд из пятнадцати кнопок (публикация, версии, три выгрузки,
 * шаблон, папка, доступ, обсуждение, архив, автослепок, удаление), полоса
 * свежести, подсказка о недостающих показателях, ряд вкладок-«таблеток» с
 * полем «Новая страница», строка «Страница «…»» со служебными кнопками и два
 * ряда фильтров. Замер на макете: до первого виджета уходило 291px против 148
 * после — то есть полтора ряда карточек уезжали под сгиб экрана, а руководитель,
 * пришедший посмотреть цифру, первым делом видел кухню модератора.
 *
 * Принципы, по которым разложено:
 *  • наверху остаётся то, что МЕНЯЕТ ЦИФРЫ (период, строка) и то, что уносят с
 *    собой (выгрузка, витрина). Остальное — в меню «⋯ ещё»;
 *  • служебное (правка раскладки, подгонка размеров, удаление и добавление
 *    страницы) появляется только в режиме правки — тот же приём, что уже
 *    применён к служебному ряду виджета: зритель этих кнопок не видит вовсе;
 *  • у публикации ОДНА кнопка — по текущему статусу («Отправить на проверку» /
 *    «Отозвать заявку» / «Снять с публикации»), а не три подряд, из которых две
 *    всегда неуместны;
 *  • вкладки страниц — подчёркиванием: так они читаются как страницы отчёта, а
 *    не как ещё один ряд действий.
 */

/**
 * Страница-СРЕЗ: закреплена за конкретным отчётом (у её виджетов задан
 * `config.period`), приход новой недели её не меняет.
 *
 * Признак приходит с сервера полем `period`, а НЕ выводится из имени. Раньше
 * срез опознавался по шаблону «Отчёт за ДД.ММ.ГГГГ» — стоило человеку
 * переименовать страницу, и она выпадала из группы срезов, оставаясь срезом по
 * сути. Старые страницы перенесены миграцией 047 (дата взята из самих виджетов).
 */
function periodDate(p: DashPage): string | null {
  return p.period ? p.period.split('-').reverse().join('.') : null
}

/** ISO-дата → сортируемое число (свежие срезы показываем первыми). */
const dateKey = (iso: string): number => Number(iso.replace(/-/g, ''))

const ru = (iso: string | null | undefined): string =>
  (iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.split('-').reverse().join('.') : iso || '')

const wrap: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: '12px 12px 0 0', borderBottom: 'none', padding: '8px 14px 4px',
}
/* Прилипает НЕ вся шапка, а только навигация: вкладки страниц и строка
 * контекста. Замер: вся шапка — 178px постоянно занятого экрана на ноутбуке
 * (пятая часть окна), а прокручивая длинную страницу, человеку нужны ровно два
 * ответа — «на какой я странице» и «за какую дату эти цифры». Имя, чипы и
 * фильтры остаются наверху: до них один рывок колеса. */
const stickyNav: React.CSSProperties = {
  position: 'sticky', top: 0, zIndex: 20, marginBottom: 12,
  background: 'var(--surface)', borderLeft: '1px solid var(--border)',
  borderRight: '1px solid var(--border)',
}
const ctxRow: React.CSSProperties = {
  borderTop: '1px solid var(--border-faint)', borderBottom: '1px solid var(--border)',
  borderRadius: '0 0 12px 12px',
  background: 'var(--surface-2)', padding: '5px 14px', fontSize: 12,
  color: 'var(--text-muted)', display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center',
}
const chip: React.CSSProperties = {
  fontSize: 11.5, padding: '2px 8px', borderRadius: 9,
  background: 'var(--surface-3)', color: 'var(--text-2)',
}
const hbtn: React.CSSProperties = {
  height: 30, padding: '0 10px', borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--border-strong)', borderRadius: 8,
  background: 'var(--surface)', color: 'var(--text-2)', fontSize: 12.5, cursor: 'pointer',
  display: 'inline-flex', alignItems: 'center', gap: 5, whiteSpace: 'nowrap',
}
const tabLine: React.CSSProperties = {
  height: 36, padding: '0 12px',
  borderTop: 'none', borderLeft: 'none', borderRight: 'none',
  borderBottomWidth: 2, borderBottomStyle: 'solid', borderBottomColor: 'transparent',
  background: 'none', color: 'var(--text-2)', fontSize: 13.5, cursor: 'pointer',
  display: 'inline-flex', alignItems: 'center', gap: 6, maxWidth: 260,
  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
}
const tabLineOn: React.CSSProperties = {
  color: 'var(--accent)', borderBottomColor: 'var(--accent)', fontWeight: 600,
}
const menuBox: React.CSSProperties = {
  position: 'absolute', right: 0, top: 34, width: 250, background: 'var(--surface)',
  border: '1px solid var(--border-strong)', borderRadius: 10, padding: 5, zIndex: 40,
  maxWidth: 'calc(100vw - 32px)',
  boxShadow: '0 8px 24px rgba(44,42,41,0.16)',
}
const menuItem: React.CSSProperties = {
  display: 'block', width: '100%', textAlign: 'left', padding: '6px 9px', borderWidth: 0, borderStyle: 'solid',
  borderRadius: 6, background: 'none', color: 'var(--text-2)', fontSize: 12.5, cursor: 'pointer',
}
const menuSep: React.CSSProperties = { border: 'none', borderTop: '1px solid var(--border-faint)', margin: '4px 6px' }

/**
 * Закрытие выпадающего списка кликом вне и по Esc.
 *
 * Именно так, а не по onMouseLeave: на планшете и телефоне события ухода мыши
 * не бывает вовсе, и меню осталось бы открытым навсегда.
 */
function useDismiss(open: boolean, setOpen: (v: boolean) => void) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open, setOpen])
  return box
}

/** Выпадающий список, закрывающийся кликом вне и по Esc. */
function Dropdown(
  { label, title, open, setOpen, width, children }:
  { label: React.ReactNode; title?: string; open: boolean; setOpen: (v: boolean) => void
    width?: number; children: React.ReactNode },
) {
  const box = useDismiss(open, setOpen)
  return (
    <div ref={box} style={{ position: 'relative' }}>
      <button type="button" title={title}
        style={{ ...hbtn, ...(open ? { borderColor: 'var(--accent)', color: 'var(--accent)' } : {}) }}
        onClick={() => setOpen(!open)}>{label} ▾</button>
      {open && <div style={{ ...menuBox, ...(width ? { width } : {}) }}>{children}</div>}
    </div>
  )
}

export interface HeaderActions {
  submitReview: () => void
  cancelReview: () => void
  publish: () => void
  unpublish: () => void
  versions: () => void
  access: () => void
  moveFolder: () => void
  saveTemplate: () => void
  archive: () => void
  toggleAutoArchive: () => void
  toggleSuggestFields: () => void
  del: () => void
  comments: () => void
  kiosk: () => void
  about: () => void
  rename: () => void
  exportPdf: () => void
  exportExcel: () => void
  exportPng: () => void
  fitLayout: () => void
  toggleFlow: () => void
  deletePage: () => void
  renamePage: () => void
}

export function DashboardHeader({
  dashboard, pages, page, onOpenPage, onBack,
  canManage, isAdmin, isSuperadmin, editMode, setEditMode, flowMode,
  asOf, quickPeriods, pFrom, pTo, setPFrom, setPTo, crossRow, setCrossRow, catOptions,
  missingCount, onOpenMissing, presets, applyPreset, removePreset, savePreset,
  newPage, setNewPage, addPage, busy, exporting, a,
  density, setDensity,
}: {
  dashboard: Dashboard
  pages: DashPage[]
  page: DashPage | null
  onOpenPage: (p: DashPage) => void
  onBack: () => void
  canManage: boolean
  isAdmin?: boolean
  isSuperadmin?: boolean
  editMode: boolean
  setEditMode: (v: boolean) => void
  /** Раскладка текущей страницы: «поток» вместо свободной сетки. */
  flowMode: boolean
  asOf: string | null
  quickPeriods: { label: string; hint: string; range: () => [string, string] }[]
  pFrom: string
  pTo: string
  setPFrom: (v: string) => void
  setPTo: (v: string) => void
  crossRow: string | null
  setCrossRow: (v: string | null) => void
  catOptions: string[]
  missingCount: number
  onOpenMissing: () => void
  presets: DashPreset[]
  applyPreset: (p: DashPreset) => void
  removePreset: (p: DashPreset) => void
  savePreset: () => void
  /** Плотность страницы — настройка читателя, не автора (см. lib/density). */
  density: Density
  setDensity: (d: Density) => void
  newPage: string
  setNewPage: (v: string) => void
  addPage: (e: React.FormEvent) => void
  busy: boolean
  exporting: boolean
  a: HeaderActions
}) {
  const [moreOpen, setMoreOpen] = useState(false)
  const [expOpen, setExpOpen] = useState(false)
  // Какой именно список быстрых периодов открыт: верхний или в липкой строке.
  const [quickOpen, setQuickOpen] = useState<'top' | 'sticky' | null>(null)
  const [sliceOpen, setSliceOpen] = useState(false)
  const [sliceRight, setSliceRight] = useState(false)
  const sliceBox = useDismiss(sliceOpen, setSliceOpen)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const filtersBox = useDismiss(filtersOpen, setFiltersOpen)


  // Страницы-срезы («Отчёт за ДД.ММ.ГГГГ») уводим в отдельный выпадающий
  // список: у дашборда заказчика их восемь из одиннадцати, и ряд вкладок
  // превращался в стену дат, в которой не найти «Обзор». Одну такую страницу
  // не прячем — выпадающий список из одного пункта бессмыслен.
  const { plainPages, slicePages } = useMemo(() => {
    const slices = pages.filter((p) => p.period)
    if (slices.length < 2) return { plainPages: pages, slicePages: [] as DashPage[] }
    return {
      plainPages: pages.filter((p) => !p.period),
      slicePages: [...slices].sort((x, y) => dateKey(y.period!) - dateKey(x.period!)),
    }
  }, [pages])

  /**
   * Отчётные даты страницы — чтобы открыть нужный отчёт выбором из списка, а
   * не набором одной и той же даты в двух календарях. При недельной форме за
   * год это 52 даты, которые иначе нужно помнить.
   */
  const [reportDates, setReportDates] = useState<string[]>([])
  useEffect(() => {
    if (!page?.id) { setReportDates([]); return }
    let cancelled = false
    pageReportDates(page.id).then((r) => { if (!cancelled) setReportDates(r.dates) }).catch(() => {})
    return () => { cancelled = true }
  }, [page?.id])
  // Выбранный отчёт — это период «с этой даты по эту же».
  const pickedReport = pFrom && pFrom === pTo ? pFrom : ''

  const sliceActive = Boolean(page?.period)
  /**
   * Фильтры, меняющие цифры. Рисуются ДВАЖДЫ одним кодом: наверху страницы и —
   * когда верх ушёл за экран — в липкой строке под вкладками. Иначе на длинной
   * странице период нельзя было сменить, не вернувшись к началу; а держать их
   * прилипшими постоянно дорого (замер: вся шапка — 178px против 65px).
   */
  const filterControls = (quickId: 'top' | 'sticky') => (
    <>
              {/* Фильтры, меняющие цифры, остаются на виду. */}
              <input type="date" style={{ ...input, height: 30, width: 138, fontSize: 12.5 }} value={pFrom}
                title="Период: с" onChange={(e) => setPFrom(e.target.value)} />
              <input type="date" style={{ ...input, height: 30, width: 138, fontSize: 12.5 }} value={pTo}
                title="Период: по" onChange={(e) => setPTo(e.target.value)} />
              {reportDates.length > 1 && (
                <select style={{ ...input, height: 30, width: 168, fontSize: 12.5 }} value={pickedReport}
                  title="Открыть конкретный отчёт: вся страница покажет его цифры"
                  onChange={(e) => { const v = e.target.value; setPFrom(v); setPTo(v) }}>
                  <option value="">Отчёт: последний</option>
                  {reportDates.map((d) => <option key={d} value={d}>{ru(d)}</option>)}
                </select>
              )}
              <Dropdown label="быстро" title="Готовые периоды" open={quickOpen === quickId} setOpen={(v) => setQuickOpen(v ? quickId : null)} width={270}>
                {quickPeriods.map((q) => (
                  <button key={q.label} type="button" style={menuItem} title={q.hint}
                    onClick={() => { const [f, t] = q.range(); setPFrom(f); setPTo(t); setQuickOpen(null) }}>{q.label}</button>
                ))}
                <hr style={menuSep} />
                {/* Фильтр периода выбирает ОТЧЁТ: иначе человек ждёт, что цифры
                    «просуммируются за период». */}
                <div style={{ fontSize: 11, color: 'var(--text-faint)', padding: '2px 9px 4px', lineHeight: 1.4 }}>
                  показывается последний отчёт, попавший в период; «Динамика» — все точки диапазона
                </div>
              </Dropdown>
              {catOptions.length > 0 ? (
                <select style={{ ...input, height: 30, width: 150, fontSize: 12.5 }} value={crossRow || ''}
                  title="Строка данных: фильтрует все виджеты страницы. Клик по столбцу или сектору на графике задаёт её же"
                  onChange={(e) => setCrossRow(e.target.value || null)}>
                  <option value="">Строка: все</option>
                  {catOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              ) : (
                <input style={{ ...input, height: 30, width: 140, fontSize: 12.5 }} placeholder="Строка"
                  value={crossRow || ''} onChange={(e) => setCrossRow(e.target.value || null)} />
              )}
              {(pFrom || pTo || crossRow) && (
                <button type="button" style={{ ...linkDanger, fontSize: 12 }}
                  onClick={() => { setPFrom(''); setPTo(''); setCrossRow(null) }}>сброс</button>
              )}
    </>
  )

  const status = dashboard.publication_status

  return (
    <>
      <div style={wrap} data-export-hide>
        <button type="button" style={{ ...linkDanger, color: 'var(--accent)', fontSize: 12 }} onClick={onBack}>← Дашборды</button>

        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginTop: 2 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <h2 style={{ fontSize: 19, fontWeight: 700, margin: 0, letterSpacing: '-0.01em' }}>{dashboard.name}</h2>
              {canManage && (
                <button type="button" style={{ ...linkDanger, color: 'var(--text-faint)', fontSize: 13 }}
                  title="Переименовать дашборд, изменить описание" onClick={a.rename}>✎</button>
              )}
              <button type="button" style={{ ...linkDanger, color: 'var(--text-faint)', fontSize: 13 }}
                title="Что это за дашборд и из чего он собран" onClick={a.about}>ℹ</button>
              {dashboard.folder_name && (
                <span style={chip} title="Папка объекта, в которой лежит дашборд">
                  📁 {dashboard.object_name} / {dashboard.folder_name}
                </span>
              )}
              <PubBadge status={status} />
              <button type="button" onClick={a.comments}
                title={dashboard.comments_count ? `Обсуждение: ${dashboard.comments_count} коммент.` : 'Обсуждение дашборда (пока нет комментариев)'}
                style={{
                  ...chip, border: 'none', cursor: 'pointer',
                  ...(dashboard.comments_count ? { background: 'var(--accent-weak-bg)', color: 'var(--accent)', fontWeight: 600 } : {}),
                }}>
                💬 {dashboard.comments_count || ''}
              </button>
            </div>
          </div>

          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            {filterControls('top')}

            {page && (
              <Dropdown label={exporting ? 'Экспорт…' : '⤓ Выгрузить'} title="Выгрузка страницы" open={expOpen} setOpen={setExpOpen} width={230}>
                <button type="button" style={menuItem} disabled={exporting}
                  onClick={() => { setExpOpen(false); a.exportPdf() }}>PDF — отчёт со всеми данными</button>
                <button type="button" style={menuItem} disabled={exporting}
                  onClick={() => { setExpOpen(false); a.exportExcel() }}>Excel — данные страницы</button>
                <button type="button" style={menuItem} disabled={exporting}
                  onClick={() => { setExpOpen(false); a.exportPng() }}>PNG — картинка отчёта</button>
              </Dropdown>
            )}
            {/* Плотность видна ВСЕМ, включая зрителя: это про то, как человек
                смотрит, а не про то, что он вправе менять на странице.
                Подпись называет ДЕЙСТВИЕ, а не состояние: значок-состояние в
                проекте уже подводил (кнопку темы не находили, 11.08). */}
            {page && (
              <button type="button" style={hbtn}
                title={density === 'compact'
                  ? 'Вернуть просторный вид: крупнее поля и промежутки'
                  : 'Компактный вид: те же виджеты, меньше полей и промежутков — на экран помещается больше'}
                onClick={() => setDensity(density === 'compact' ? 'comfortable' : 'compact')}>
                {density === 'compact' ? '⇕ Просторнее' : '⇕ Компактнее'}
              </button>
            )}
            {pages.length > 0 && (
              <button type="button" style={hbtn} title="Полноэкранный показ с автопрокруткой (для ТВ)" onClick={a.kiosk}>📺 Витрина</button>
            )}
            {/* Публикация — ОДНА кнопка по текущему состоянию. */}
            {canManage && status === 'draft' && (
              <button type="button" style={{ ...hbtn, borderColor: 'var(--accent)', color: 'var(--accent)' }} onClick={a.submitReview}>Отправить на проверку</button>
            )}
            {canManage && status === 'review' && (
              <button type="button" style={hbtn} onClick={a.cancelReview}>Отозвать заявку</button>
            )}
            {canManage && status === 'published' && (
              <button type="button" style={hbtn} onClick={a.unpublish}>Снять с публикации</button>
            )}

            {/* У зрителя в этом меню нет НИ ОДНОГО пункта (все под canManage /
                isSuperadmin), и кнопка открывала бы пустую рамку — кнопка,
                которая ничего не делает, читается как поломка. */}
            {(canManage || isSuperadmin) && (
            <Dropdown label="⋯" title="Остальные действия с дашбордом" open={moreOpen} setOpen={setMoreOpen}>
              {canManage && (
                <button type="button" style={{ ...menuItem, color: editMode ? 'var(--accent)' : 'var(--text-2)' }}
                  onClick={() => { setEditMode(!editMode); setMoreOpen(false) }}>
                  {editMode ? '✓ Выйти из режима правки' : '✎ Правка: двигать виджеты'}
                </button>
              )}
              {canManage && isAdmin && status === 'draft' && (
                <button type="button" style={menuItem} onClick={() => { setMoreOpen(false); a.publish() }}>Опубликовать без проверки</button>
              )}
              {canManage && <button type="button" style={menuItem} onClick={() => { setMoreOpen(false); a.versions() }}>История версий</button>}
              <hr style={menuSep} />
              {canManage && <button type="button" style={menuItem} onClick={() => { setMoreOpen(false); a.access() }}>🔒 Доступ</button>}
              {canManage && <button type="button" style={menuItem} onClick={() => { setMoreOpen(false); a.moveFolder() }}>📁 Переместить в папку</button>}
              {canManage && <button type="button" style={menuItem} onClick={() => { setMoreOpen(false); a.saveTemplate() }}>Сохранить как шаблон</button>}
              {canManage && (
                <button type="button" style={menuItem} onClick={() => { setMoreOpen(false); a.toggleSuggestFields() }}
                  title="Подсказка о показателях, которых нет на дашборде">
                  💡 Подсказки о показателях: {dashboard.suggest_new_fields === false ? 'выкл' : 'вкл'}
                </button>
              )}
              {canManage && <hr style={menuSep} />}
              {canManage && <button type="button" style={menuItem} onClick={() => { setMoreOpen(false); a.archive() }}>📦 В архив</button>}
              {canManage && (
                <button type="button" style={menuItem} onClick={() => { setMoreOpen(false); a.toggleAutoArchive() }}
                  title="1-го числа система сама сохранит слепок за прошедший месяц">
                  📅 Автослепок: {dashboard.auto_archive ? 'вкл' : 'выкл'}
                </button>
              )}
              {isSuperadmin && (
                <button type="button" style={{ ...menuItem, color: 'var(--danger)' }}
                  onClick={() => { setMoreOpen(false); a.del() }}
                  title="Удалить дашборд со страницами и виджетами (слепки в архиве сохранятся)">🗑 Удалить дашборд</button>
              )}
            </Dropdown>
            )}
          </div>
        </div>

      </div>

      {/* Липкая навигация: вкладки страниц + строка контекста. */}
      <div style={stickyNav} data-export-hide>
        <div style={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap', padding: '0 14px', borderTop: '1px solid var(--border-faint)' }}>
          {plainPages.map((p) => (
            <button key={p.id} type="button" title={p.name}
              style={{ ...tabLine, ...(page?.id === p.id ? tabLineOn : {}) }}
              onClick={() => onOpenPage(p)}>{p.name}</button>
          ))}
          {slicePages.length > 0 && (
            <div ref={sliceBox} style={{ position: 'relative' }}>
              <button type="button"
                style={{ ...tabLine, ...(sliceActive ? tabLineOn : {}) }}
                title="Страницы-срезы: снимок за конкретный отчёт, данные не обновляются"
                onClick={(e) => {
                  // Сторону раскрытия выбираем по месту на экране: у правого
                  // края список, приколотый слева, вылезал за окно и включал
                  // горизонтальную прокрутку страницы.
                  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
                  setSliceRight(r.left > window.innerWidth * 0.55)
                  setSliceOpen(!sliceOpen)
                }}>
                📌 {sliceActive && page ? periodDate(page) : 'Срезы'} ({slicePages.length}) ▾
              </button>
              {sliceOpen && (
                <div style={{
                  ...menuBox, top: 36, width: 210, maxWidth: 'calc(100vw - 32px)',
                  maxHeight: 320, overflowY: 'auto',
                  ...(sliceRight ? { right: 0, left: 'auto' } : { left: 0, right: 'auto' }),
                }}>
                  <div style={{ fontSize: 11, color: 'var(--text-faint)', padding: '2px 9px 5px' }}>снимок за отчёт, не обновляется</div>
                  {slicePages.map((p) => (
                    <button key={p.id} type="button"
                      style={{ ...menuItem, ...(page?.id === p.id ? { color: 'var(--accent)', fontWeight: 600 } : {}) }}
                      onClick={() => { onOpenPage(p); setSliceOpen(false) }}
                      title={p.name}>📌 {periodDate(p)}</button>
                  ))}
                </div>
              )}
            </div>
          )}
          {/* Служебное — только в режиме правки: зритель этих кнопок не видит. */}
          {canManage && editMode && page && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 8 }}>
              <button type="button" style={{ ...hbtn, height: 26 }} title="Переименовать страницу" onClick={a.renamePage}>✎ имя</button>
              {/* Раскладка страницы. В «потоке» место и размер считаются по типу
                  виджета при отрисовке, поэтому подгонять и двигать нечего —
                  кнопки сетки там не показываем. */}
              <button type="button" style={{ ...hbtn, height: 26, ...(flowMode ? { borderColor: 'var(--accent)', color: 'var(--accent)' } : {}) }}
                title={flowMode
                  ? 'Сейчас «поток»: виджеты сами укладываются по типу. Перейти на свободную сетку с перетаскиванием'
                  : 'Сейчас свободная сетка. Перейти на «поток»: карточки, графики и таблицы уложатся сами и не оставят дыр'}
                onClick={a.toggleFlow}>⧉ {flowMode ? 'Поток' : 'Сетка'}</button>
              {!flowMode && (
                <button type="button" style={{ ...hbtn, height: 26 }}
                  title="Поставить каждому виджету размер по его типу и разложить по сетке. Состав страницы не изменится"
                  onClick={a.fitLayout}>↕ Подогнать размеры</button>
              )}
              <button type="button" style={{ ...linkDanger, fontSize: 12 }} onClick={a.deletePage}>удалить страницу</button>
            </span>
          )}
          {canManage && editMode && (
            <form onSubmit={addPage} style={{ display: 'flex', gap: 6, marginLeft: 8 }}>
              <input style={{ ...input, height: 26, width: 140, fontSize: 12.5 }} placeholder="Новая страница"
                value={newPage} onChange={(e) => setNewPage(e.target.value)} />
              <button style={{ ...hbtn, height: 26 }} disabled={busy || !newPage.trim()}>＋</button>
            </form>
          )}
        </div>

        {/* Строка контекста: ответ на вопрос «что я сейчас смотрю». */}
        <div style={ctxRow}>
        {asOf && <span>🕓 данные на <b style={{ color: 'var(--text-2)' }}>{ru(asOf)}</b></span>}
        {/* Период и строка в липкой строке — не подпись, а КНОПКА: она уже
            говорит, что сейчас применено, и по клику даёт это изменить. Так
            фильтры доступны при прокрутке длинной страницы, не возвращаясь к
            началу, и при этом в шапке не появляется второй такой же набор
            полей. Раньше здесь была задумана кнопка «фильтры», всплывающая
            при уходе шапки за экран, — от неё отказались: она держится на
            событии прокрутки, а его часть встроенных браузеров не отдаёт. */}
        <div ref={filtersBox} style={{ position: 'relative' }}>
          <button type="button"
            title="Период и строка: нажмите, чтобы изменить — не возвращаясь к началу страницы"
            style={{
              border: 'none', background: 'none', padding: 0, cursor: 'pointer', font: 'inherit',
              display: 'inline-flex', gap: 14, alignItems: 'center',
              color: pFrom || pTo || crossRow ? 'var(--accent)' : 'var(--text-muted)',
              textDecoration: 'underline', textDecorationStyle: 'dotted', textUnderlineOffset: 3,
            }}
            onClick={() => setFiltersOpen(!filtersOpen)}>
            <span>{pFrom || pTo ? `период ${ru(pFrom) || '…'} → ${ru(pTo) || '…'}` : 'период: весь'}</span>
            <span>строка: {crossRow || 'все'}</span>
          </button>
          {filtersOpen && (
            <div style={{ ...menuBox, top: 24, left: 0, right: 'auto', width: 'auto', minWidth: 330, padding: 10 }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                {filterControls('sticky')}
              </div>
            </div>
          )}
        </div>
        {dashboard.object_name && <span>объект: {dashboard.object_name}</span>}
        {presets.length > 0 && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            пресеты:
            {presets.map((p) => (
              <span key={p.id} style={presetChip}>
                <button type="button" style={{ border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', padding: 0, fontSize: 12 }}
                  onClick={() => applyPreset(p)} title="Применить набор фильтров">{p.name}</button>
                {canManage && (
                  <button type="button" style={{ border: 'none', background: 'none', color: 'var(--danger)', cursor: 'pointer', padding: 0 }}
                    onClick={() => removePreset(p)} title="Удалить пресет">✕</button>
                )}
              </span>
            ))}
          </span>
        )}
        {canManage && (pFrom || pTo || crossRow) && (
          <button type="button" style={{ ...linkDanger, color: 'var(--text-muted)', fontSize: 12 }}
            onClick={savePreset} title="Сохранить текущие фильтры как набор">💾 сохранить набор</button>
        )}
        {canManage && missingCount > 0 && (
          <button type="button" style={{ ...linkDanger, color: 'var(--accent)', fontSize: 12, marginLeft: 'auto' }}
            onClick={onOpenMissing}
            title="Показатели, которые есть в данных, но не показаны ни одним виджетом">
            💡 {missingCount} показателей не показаны
          </button>
        )}
        </div>
      </div>
    </>
  )
}
