import { useState } from 'react'
import { createPortal } from 'react-dom'

import { WT, btn, btnGhost, dialog, input, overlay, rmBtn } from './shared'
import type { Dashboard, DashPage, Widget } from '../../api'

/**
 * Правка самого дашборда: название и описание.
 *
 * До этого имя задавалось при создании и оставалось навсегда — опечатку было
 * не исправить, а описание задать негде.
 */
export function EditDashboardDialog(
  { initial, onClose, onSave, loadDraft }: {
    initial: { name: string; description: string }
    onClose: () => void
    onSave: (v: { name: string; description: string }) => void
    /** Черновик описания, собранный системой по составу дашборда. */
    loadDraft?: () => Promise<string>
  },
) {
  const [name, setName] = useState(initial.name)
  const [description, setDescription] = useState(initial.description)
  const [drafting, setDrafting] = useState(false)
  return createPortal((
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 520 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>✎ Дашборд</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <label style={lbl}>Название
          <input style={{ ...input, width: '100%' }} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label style={{ ...lbl, marginTop: 10 }}>Описание — что показывает дашборд и кому предназначен
          {/* Описание видит руководитель в разделе «Руководителю» вместо
              голого имени отчёта. Заполнять его руками никто не станет,
              поэтому черновик собирает система — по составу самого дашборда. */}
          {loadDraft && (
            <button type="button" style={{ ...btnGhost, height: 26, fontSize: 12, marginLeft: 8 }}
              disabled={drafting}
              title="Собрать описание по составу дашборда: объект, показатели, периоды"
              onClick={async () => {
                setDrafting(true)
                try { setDescription(await loadDraft()) } finally { setDrafting(false) }
              }}>{drafting ? 'Составляю…' : '✨ Составить'}</button>
          )}
          <textarea
            style={{ ...input, width: '100%', height: 90, padding: 10, resize: 'vertical' }}
            placeholder="Например: ход внедрения сервиса записи в МФЦ, для еженедельного доклада руководству"
            value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
          <button style={btnGhost} onClick={onClose}>Отмена</button>
          <button style={btn} disabled={!name.trim()} onClick={() => onSave({ name, description })}>Сохранить</button>
        </div>
      </div>
    </div>
  ), document.body)
}

/**
 * «О дашборде» — что это и из чего собрано.
 *
 * Кнопка «подробнее» есть у каждого виджета и объясняет ОДИН показатель.
 * Про дашборд целиком не было сказано нигде: ни что он показывает, ни из каких
 * файлов взяты цифры. Здесь всё собрано в одном месте: назначение, где лежит,
 * состояние, состав по типам виджетов и — главное — источники данных.
 */
export function AboutDashboard(
  { dashboard, pages, widgets, currentPage, onClose }: {
    dashboard: Dashboard
    pages: DashPage[]
    widgets: Widget[]
    currentPage: DashPage | null
    onClose: () => void
  },
) {
  // Источники собираем из конфигураций виджетов: датасет (файл-первоисточник)
  // и метрика (расчёт с формулой) — это ответ на вопрос «откуда цифры».
  const datasets = new Set<string>()
  const metrics = new Set<string>()
  const byType = new Map<string, number>()
  for (const w of widgets) {
    const c = (w.config || {}) as Record<string, unknown>
    if (typeof c.dataset_code === 'string') datasets.add(c.dataset_code)
    for (const key of ['metric_code', 'plan_metric', 'fact_metric']) {
      if (typeof c[key] === 'string') metrics.add(c[key] as string)
    }
    for (const s of (Array.isArray(c.series) ? c.series : []) as Record<string, unknown>[]) {
      if (typeof s?.dataset_code === 'string') datasets.add(s.dataset_code as string)
    }
    byType.set(w.widget_type, (byType.get(w.widget_type) || 0) + 1)
  }
  const typeName = (t: string) => WT.find((x) => x.v === t)?.t || t

  return createPortal((
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 600 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>О дашборде: {dashboard.name}</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>

        <Section title="Назначение">
          {dashboard.description
            ? <div style={txt}>{dashboard.description}</div>
            : <div style={faint}>Описание не задано. Кнопка ✎ рядом с названием — добавить.</div>}
        </Section>

        <Section title="Где лежит и в каком состоянии">
          <Row k="Объект" v={dashboard.object_name || '—'} />
          <Row k="Папка" v={dashboard.folder_name || 'без папки'} />
          <Row k="Состояние" v={STATUS[dashboard.publication_status] || dashboard.publication_status} />
          <Row k="Создан" v={new Date(dashboard.created_at).toLocaleString('ru-RU')} />
          {dashboard.updated_at && <Row k="Изменён" v={new Date(dashboard.updated_at).toLocaleString('ru-RU')} />}
        </Section>

        <Section title="Из чего состоит">
          <Row k="Страниц" v={String(pages.length)} />
          <Row k="Открыта страница" v={currentPage?.name || '—'} />
          <Row k="Виджетов на ней" v={String(widgets.length)} />
          {byType.size > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
              {[...byType].map(([t, n]) => (
                <span key={t} style={chip}>{typeName(t)}{n > 1 ? ` × ${n}` : ''}</span>
              ))}
            </div>
          )}
        </Section>

        <Section title="Откуда цифры">
          {datasets.size === 0 && metrics.size === 0 && <div style={faint}>Источники не заданы.</div>}
          {datasets.size > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div style={faint}>Датасеты (данные из загруженных документов):</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                {[...datasets].map((d) => <span key={d} style={mono}>{d}</span>)}
              </div>
            </div>
          )}
          {metrics.size > 0 && (
            <div>
              <div style={faint}>Метрики (расчёт по формуле):</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                {[...metrics].map((m) => <span key={m} style={mono}>{m}</span>)}
              </div>
            </div>
          )}
          <div style={{ ...faint, marginTop: 8 }}>
            Как посчитан конкретный показатель — кнопка «🔍 подробнее» на самом виджете:
            там формула и первичные строки из файла.
          </div>
        </Section>
      </div>
    </div>
  ), document.body)
}

const STATUS: Record<string, string> = {
  draft: 'черновик — виден только staff',
  review: 'на проверке у модератора',
  published: 'опубликован — виден пользователям',
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)', marginBottom: 6 }}>{title}</div>
      {children}
    </div>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 13, padding: '2px 0' }}>
      <span style={{ color: 'var(--text-muted)', minWidth: 150 }}>{k}</span>
      <span>{v}</span>
    </div>
  )
}

const lbl: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: 'var(--text-muted)' }
const txt: React.CSSProperties = { fontSize: 13, lineHeight: 1.5 }
const faint: React.CSSProperties = { fontSize: 12, color: 'var(--text-faint)' }
const chip: React.CSSProperties = { fontSize: 12, background: 'var(--accent-weak-bg)', color: 'var(--accent)', padding: '2px 8px', borderRadius: 10 }
const mono: React.CSSProperties = { fontFamily: 'ui-monospace, monospace', fontSize: 12, background: 'var(--surface-2)', padding: '2px 8px', borderRadius: 6 }
