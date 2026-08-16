// Список дашбордов: формы создания (вручную/авто из объекта/из шаблона),
// поиск + фильтры (избранное/дата/папка), массовое перемещение в папку,
// сама таблица строк + «показать ещё». Вынесено из DashboardsPage.tsx.
import type { FormEvent } from 'react'
import type { Dashboard, DashTemplate, Folder, Obj } from '../../api'
import { folderLabel, folderTree } from '../../lib/folderTree'
import { PubBadge, btn, btnAuto, input, muted, rowForm, rowItem, tab, tabActive } from './shared'

/** С какого числа отчётов зрителю имеет смысл показывать фильтр по папкам:
 *  при двух-трёх он лишний ряд управления над списком. */
const FOLDER_FILTER_FROM = 8

export function DashboardList({
  canManage, objects, templates,
  newDash, setNewDash, addDashboard, busy,
  autoObj, setAutoObj, autoBuild,
  tpl, setTpl, createFromTemplate, cloneTemplate,
  query, setQuery, favOnly, setFavOnly,
  dashFrom, setDashFrom, dashTo, setDashTo,
  filterObjId, setFilterObjId, filterFolders, folderFilter, setFolderFilter,
  selectedIds, setSelectedIds, onBulkMove, toggleSelect,
  dashboards, dashTotal, openDashboard, toggleFav, loadMoreDash, onToggleFeatured,
}: {
  canManage: boolean; objects: Obj[]; templates: DashTemplate[]
  newDash: string; setNewDash: (v: string) => void; addDashboard: (e: FormEvent) => void; busy: boolean
  autoObj: string; setAutoObj: (v: string) => void; autoBuild: () => void
  tpl: string; setTpl: (v: string) => void; createFromTemplate: () => void
  /** Тиражировать шаблон на другой объект с перепривязкой показателей. */
  cloneTemplate: () => void
  query: string; setQuery: (v: string) => void; favOnly: boolean; setFavOnly: (f: (v: boolean) => boolean) => void
  dashFrom: string; setDashFrom: (v: string) => void; dashTo: string; setDashTo: (v: string) => void
  filterObjId: string; setFilterObjId: (v: string) => void; filterFolders: Folder[]
  folderFilter: string; setFolderFilter: (v: string | ((v: string) => string)) => void
  selectedIds: Set<string>; setSelectedIds: (s: Set<string>) => void
  onBulkMove: () => void; toggleSelect: (e: React.MouseEvent, id: string) => void
  dashboards: Dashboard[]; dashTotal: number; openDashboard: (id: string) => void
  toggleFav: (e: React.MouseEvent, d: Dashboard) => void; loadMoreDash: () => void
  /** Отметить дашборд для подборки «Руководителю» (состав, не доступ). */
  onToggleFeatured: (e: React.MouseEvent, d: Dashboard) => void
}) {
  return (
    <div>
      {canManage && (
        <form onSubmit={addDashboard} style={rowForm}>
          <input style={{ ...input, width: 260 }} placeholder="Название дашборда" value={newDash} onChange={(e) => setNewDash(e.target.value)} />
          <button style={btn} disabled={busy || !newDash.trim()}>＋ Дашборд</button>
        </form>
      )}
      {canManage && objects.length > 0 && (
        <div style={{ ...rowForm, alignItems: 'center' }}>
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>или собрать автоматически из объекта:</span>
          <select style={{ ...input, height: 36 }} value={autoObj} onChange={(e) => setAutoObj(e.target.value)}>
            <option value="">выберите объект…</option>
            {objects.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <button style={btnAuto} disabled={busy || !autoObj} onClick={autoBuild}>✨ Собрать</button>
        </div>
      )}
      {canManage && templates.length > 0 && (
        <div style={{ ...rowForm, alignItems: 'center' }}>
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>или создать из шаблона:</span>
          <select style={{ ...input, height: 36 }} value={tpl} onChange={(e) => setTpl(e.target.value)}>
            <option value="">выберите шаблон…</option>
            {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <button style={btnAuto} disabled={busy || !tpl} onClick={createFromTemplate}>📋 Создать</button>
          <button style={btnAuto} disabled={busy || !tpl} onClick={cloneTemplate}
            title="Создать копию для другого объекта: показатели сопоставятся по названиям">
            🧬 На другой объект
          </button>
        </div>
      )}
      <div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, flexWrap: 'wrap' }}>
          <input style={{ ...input, flex: 1, minWidth: 200 }} placeholder="🔍 Поиск дашборда по названию или странице…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <button style={favOnly ? { ...tab, ...tabActive } : tab} onClick={() => setFavOnly((v) => !v)} title="Показать только избранные">★ Избранное</button>
          {/* Диапазон дат правки — инструмент того, кто дашборды СОБИРАЕТ:
              зритель ищет отчёт по названию, а не по тому, когда его правили.
              Заказчик про экран зрителя сказал прямо: это админский список с
              вырезанными кнопками. */}
          {canManage && (
            <>
              <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--text-muted)' }}>
                изменён с <input type="date" style={{ ...input, width: 140 }} value={dashFrom} onChange={(e) => setDashFrom(e.target.value)} />
                по <input type="date" style={{ ...input, width: 140 }} value={dashTo} onChange={(e) => setDashTo(e.target.value)} />
              </label>
              {(dashFrom || dashTo) && <button style={tab} onClick={() => { setDashFrom(''); setDashTo('') }} title="Сбросить фильтр по дате">✕ дата</button>}
            </>
          )}
        </div>
        {/* Фильтр по папкам зрителю показываем, только когда отчётов
            действительно много: при двух-трёх он лишний ряд управления над
            списком, в котором и так всё видно. */}
        {objects.length > 0 && (canManage || dashTotal > FOLDER_FILTER_FROM) && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>📁 Папка:</span>
            <select style={{ ...input, height: 32 }} value={filterObjId}
              onChange={(e) => { setFilterObjId(e.target.value); setFolderFilter('') }}>
              <option value="">все объекты</option>
              {objects.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
            {filterObjId && (
              <select style={{ ...input, height: 32 }} value={folderFilter} onChange={(e) => setFolderFilter(e.target.value)}>
                <option value="">все папки объекта</option>
                {folderTree(filterFolders).map((f) => <option key={f.id} value={f.id}>{folderLabel(f)}</option>)}
              </select>
            )}
            <button style={folderFilter === 'none' ? { ...tab, ...tabActive } : tab}
              onClick={() => { setFilterObjId(''); setFolderFilter((v) => (v === 'none' ? '' : 'none')) }}>
              без папки
            </button>
            {(filterObjId || folderFilter) && (
              <button style={tab} onClick={() => { setFilterObjId(''); setFolderFilter('') }} title="Сбросить фильтр по папке">✕ папка</button>
            )}
          </div>
        )}
        {canManage && objects.length > 0 && selectedIds.size > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, padding: '8px 12px', borderRadius: 10, background: 'var(--accent-weak-bg)' }}>
            <span style={{ fontSize: 13, color: 'var(--accent)' }}>Выбрано: {selectedIds.size}</span>
            <button style={btnAuto} onClick={onBulkMove}>📁 Переместить в папку</button>
            <button style={{ ...tab, marginLeft: 'auto' }} onClick={() => setSelectedIds(new Set())}>Снять выделение</button>
          </div>
        )}
        {dashboards.length === 0 ? (
          <div style={muted}>{query.trim() || favOnly || dashFrom || dashTo || folderFilter ? 'Ничего не найдено.' : 'Пока нет дашбордов.'}</div>
        ) : (
          <div style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
            {dashboards.map((d, i) => (
              // Строка списка — интерактивный элемент: без role/tabindex её нельзя
              // было открыть с клавиатуры (важно для доступности госсистемы).
              // Вложенные кнопки (★, чекбокс) сохраняют свои обработчики и
              // останавливают всплытие сами.
              <div key={d.id} role="button" tabIndex={0}
                aria-label={`Открыть дашборд «${d.name}»`}
                onClick={() => openDashboard(d.id)}
                onKeyDown={(e) => {
                  if (e.target !== e.currentTarget) return
                  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDashboard(d.id) }
                }}
                style={{ ...rowItem, borderTop: i ? '1px solid var(--border-faint)' : 'none' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14 }}>
                  {canManage && objects.length > 0 && (
                    <input type="checkbox" checked={selectedIds.has(d.id)} onClick={(e) => toggleSelect(e, d.id)} onChange={() => {}}
                      title="Выбрать для массового действия" style={{ cursor: 'pointer' }} />
                  )}
                  <button onClick={(e) => toggleFav(e, d)} title={d.is_favorite ? 'Убрать из избранного' : 'В избранное'}
                    style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: 16, color: d.is_favorite ? '#e0a800' : 'var(--border-strong)', padding: 0, lineHeight: 1 }}>
                    {d.is_favorite ? '★' : '☆'}
                  </button>
                  {canManage && (
                    // Отметка «в подборку руководителю». Отдельной системы прав
                    // за ней нет: кто увидит дашборд, решают те же гранты, что и
                    // в общем списке, — флаг отвечает только за состав подборки.
                    <button onClick={(e) => onToggleFeatured(e, d)}
                      title={d.featured
                        ? 'Убрать из подборки «Руководителю»'
                        : 'Добавить в подборку «Руководителю» (доступ выдаётся отдельно)'}
                      style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: 14, padding: 0, lineHeight: 1, color: d.featured ? 'var(--accent)' : 'var(--border-strong)' }}>
                      {d.featured ? '👔' : '👤'}
                    </button>
                  )}
                  {d.name}
                  {!!d.comments_count && <span title={`Комментариев: ${d.comments_count}`} style={{ fontSize: 12, color: 'var(--accent)' }}>💬{d.comments_count}</span>}
                  {d.folder_name && (
                    <span title={`${d.object_name ?? ''} / ${d.folder_name}`} style={{ fontSize: 11, padding: '1px 8px', borderRadius: 9, background: 'var(--surface-3)', color: 'var(--text-2)' }}>
                      📁 {d.folder_name}
                    </span>
                  )}
                </span>
                {/* minWidth: 0 обязателен: без него flex-элемент не может стать
                    уже своего содержимого, и длинное описание вылезает за
                    карточку (замерено — на 25px), где его срезает overflow. */}
                <span style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6, minWidth: 0,
                  fontSize: 12, color: 'var(--text-muted)' }}>
                  {/* Число страниц и статус публикации — про устройство, а не
                      про содержание: зритель видит только опубликованное, и
                      бейдж «опубликован» на каждой строке ничего ему не
                      сообщает. Вместо них — описание, отвечающее «про что
                      отчёт»; дата остаётся: она говорит о свежести. */}
                  {canManage ? (
                    <>
                      <span>страниц: {d.pages ?? 0}</span>
                      <PubBadge status={d.publication_status} />
                    </>
                  ) : d.description && (
                    <span title={d.description} style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {d.description}
                    </span>
                  )}
                  {d.updated_at && <span>изменён {new Date(d.updated_at).toLocaleDateString('ru-RU')}</span>}
                </span>
              </div>
            ))}
          </div>
        )}
        {dashboards.length < dashTotal && (
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <button style={{ ...btnAuto }} onClick={loadMoreDash}>Показать ещё ({dashTotal - dashboards.length})</button>
          </div>
        )}
      </div>
    </div>
  )
}
