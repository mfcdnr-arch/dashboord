import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { globalSearch, type SearchResults } from '../api'

/** Куда ведёт выбор результата — App.tsx решает, как это открыть. Раздел и
 *  отчёт/страница/виджет используют один и тот же механизм навигации, что и
 *  ссылка (п. 6); объект и показатель — свои собственные `initial*`-пропы. */
export type SearchTarget =
  | { kind: 'section'; section: string }
  | { kind: 'dashboard'; dashboard: string }
  | { kind: 'page'; dashboard: string; page: string }
  | { kind: 'widget'; dashboard: string; page: string | null; widget: string }
  | { kind: 'object'; object: string }
  | { kind: 'metric'; metric: string }

interface Row { key: string; icon: string; label: string; hint?: string; target: SearchTarget }

const EMPTY: SearchResults = { dashboards: [], pages: [], widgets: [], objects: [], metrics: [] }

/**
 * Быстрый поиск по системе — Ctrl+K (п. 9).
 *
 * До этого поиск существовал только ВНУТРИ разделов: чтобы найти показатель,
 * нужно было сначала догадаться, что искать именно в «Метриках», а не в
 * «Дашбордах». Здесь один запрос сразу по пяти сущностям плюс мгновенный
 * переход между разделами меню — второе не требует обращения к серверу.
 *
 * Открывается всегда (глобальный слушатель клавиш в этом же компоненте, он
 * смонтирован в App.tsx одним экземпляром) — сочетание работает из любого
 * раздела, это и есть весь смысл «быстрого» поиска.
 */
export default function CommandPalette(
  { nav, onNavigate }: {
    /** Уже отфильтрованный по правам список разделов (тот же, что рисует
     *  боковое меню) — переиспользуем готовую фильтрацию, а не дублируем её. */
    nav: { key: string; label: string }[]
    onNavigate: (t: SearchTarget) => void
  },
) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [results, setResults] = useState<SearchResults>(EMPTY)
  const [loading, setLoading] = useState(false)
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const seq = useRef(0)

  const close = useCallback(() => { setOpen(false); setQ(''); setResults(EMPTY); setActive(0) }, [])

  // Ctrl+K / Cmd+K открывает из ЛЮБОГО места; браузер иначе перехватил бы
  // сочетание сам (фокус на адресную строку) — preventDefault обязателен.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((v) => !v)
      } else if (e.key === 'Escape' && open) {
        close()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, close])

  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 30) }, [open])

  // Разделы — мгновенно, без сервера: список короткий и уже есть в памяти.
  const sectionRows: Row[] = useMemo(() => {
    const query = q.trim().toLowerCase()
    if (!query) return []
    return nav
      .filter((n) => n.label.toLowerCase().includes(query))
      .map((n) => ({ key: `s:${n.key}`, icon: '☰', label: n.label, hint: 'раздел',
        target: { kind: 'section', section: n.key } as SearchTarget }))
  }, [nav, q])

  useEffect(() => {
    const query = q.trim()
    if (query.length < 2) { setResults(EMPTY); setLoading(false); return }
    setLoading(true)
    const mySeq = ++seq.current
    const id = setTimeout(() => {
      globalSearch(query)
        .then((r) => { if (mySeq === seq.current) setResults(r) })
        .catch(() => { if (mySeq === seq.current) setResults(EMPTY) })
        .finally(() => { if (mySeq === seq.current) setLoading(false) })
    }, 200)
    return () => clearTimeout(id)
  }, [q])

  const rows: Row[] = useMemo(() => [
    ...sectionRows,
    ...results.dashboards.map((d) => ({
      key: `d:${d.id}`, icon: '📊', label: d.name,
      hint: [d.object_name, d.folder_name].filter(Boolean).join(' / ') || undefined,
      target: { kind: 'dashboard', dashboard: d.id } as SearchTarget,
    })),
    ...results.pages.map((p) => ({
      key: `p:${p.id}`, icon: '📄', label: p.name, hint: p.dashboard_name,
      target: { kind: 'page', dashboard: p.dashboard_id, page: p.id } as SearchTarget,
    })),
    ...results.widgets.map((w) => ({
      key: `w:${w.id}`, icon: '🔢', label: w.name,
      hint: [w.dashboard_name, w.page_name].filter(Boolean).join(' · '),
      target: { kind: 'widget', dashboard: w.dashboard_id, page: w.page_id, widget: w.id } as SearchTarget,
    })),
    ...results.objects.map((o) => ({
      key: `o:${o.id}`, icon: '🗂️', label: o.name, hint: 'объект',
      target: { kind: 'object', object: o.id } as SearchTarget,
    })),
    ...results.metrics.map((m) => ({
      key: `m:${m.id}`, icon: '📐', label: m.name, hint: `показатель · ${m.code}`,
      target: { kind: 'metric', metric: m.id } as SearchTarget,
    })),
  ], [sectionRows, results])

  useEffect(() => { setActive(0) }, [rows.length])

  function choose(r: Row) {
    onNavigate(r.target)
    close()
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => Math.min(i + 1, rows.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (rows[active]) choose(rows[active]) }
  }

  if (!open) return null

  return createPortal(
    <div style={backdrop} onClick={close}>
      <div style={box} onClick={(e) => e.stopPropagation()}>
        <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKeyDown}
          placeholder="Искать дашборд, страницу, показатель, объект…" style={input} />
        <div style={{ maxHeight: 360, overflowY: 'auto' }}>
          {q.trim().length > 0 && q.trim().length < 2 && (
            <div style={hintRow}>Ещё символ — и начнём искать</div>
          )}
          {q.trim().length >= 2 && loading && rows.length === 0 && <div style={hintRow}>Ищем…</div>}
          {q.trim().length >= 2 && !loading && rows.length === 0 && <div style={hintRow}>Ничего не найдено</div>}
          {rows.map((r, i) => (
            <div key={r.key} onClick={() => choose(r)} onMouseEnter={() => setActive(i)}
              style={{ ...row, background: i === active ? 'var(--accent-weak-bg)' : undefined }}>
              <span style={{ width: 20, textAlign: 'center', flexShrink: 0 }}>{r.icon}</span>
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.label}
              </span>
              {r.hint && <span style={{ fontSize: 11.5, color: 'var(--text-faint)', flexShrink: 0 }}>{r.hint}</span>}
            </div>
          ))}
        </div>
        <div style={footer}>↑↓ выбор · Enter открыть · Esc закрыть</div>
      </div>
    </div>,
    document.body,
  )
}

const backdrop: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,.35)',
  display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '12vh', zIndex: 1100,
}
const box: React.CSSProperties = {
  width: 'min(560px, 92vw)', background: 'var(--surface)', color: 'var(--text)',
  borderRadius: 10, boxShadow: '0 12px 44px rgba(0,0,0,.3)', overflow: 'hidden',
}
const input: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '14px 16px', fontSize: 15,
  border: 'none', borderBottom: '1px solid var(--border)', outline: 'none',
  background: 'transparent', color: 'var(--text)', fontFamily: 'inherit',
}
const row: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10, padding: '9px 16px', cursor: 'pointer', fontSize: 13.5,
}
const hintRow: React.CSSProperties = { padding: '14px 16px', fontSize: 13, color: 'var(--text-2)' }
const footer: React.CSSProperties = {
  padding: '6px 16px', fontSize: 11, color: 'var(--text-faint)', borderTop: '1px solid var(--border-faint)',
}
