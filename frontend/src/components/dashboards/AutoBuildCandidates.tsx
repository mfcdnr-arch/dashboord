import { useMemo, useState } from 'react'
import type { AutoPlanCandidate } from '../../api'
import InfoTip from '../InfoTip'
import { plural } from '../../lib/text'

/**
 * Виджеты, которые предлагает планировщик, — по страницам будущего дашборда.
 *
 * Решения заказчика 23.09.2026: рекомендованные отмечены по умолчанию, человек
 * снимает лишнее; остальное — в свёрнутом «Ещё можно добавить» с поиском, у
 * каждого сказано, ПОЧЕМУ не рекомендую; добавить можно всё — вместо запрета
 * предупреждение. Пояснение ⓘ — тот же текст, что увидит пользователь у
 * созданного виджета.
 *
 * Отметка кандидата хранится ключом (`include` / `exclude`), а не номером в
 * списке: список пересчитывается при каждой галочке, и номер указывал бы
 * уже на другой виджет.
 */
export default function AutoBuildCandidates({ candidates, include, exclude, onToggle }: {
  candidates: AutoPlanCandidate[]
  include: string[]
  exclude: string[]
  onToggle: (c: AutoPlanCandidate) => void
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const inc = useMemo(() => new Set(include), [include])
  const exc = useMemo(() => new Set(exclude), [exclude])
  // Отметку показываем сразу, не дожидаясь пересчёта с сервера: иначе
  // галочка «отставала» бы от щелчка на время запроса. Правило — серверное
  // (`build`): рекомендован или добавлен, и не снят.
  const chosen = (c: AutoPlanCandidate) => (c.recommended || inc.has(c.key)) && !exc.has(c.key)

  const main = candidates.filter((c) => c.recommended || inc.has(c.key))
  const extra = candidates.filter((c) => !c.recommended && !inc.has(c.key))
  const pages: string[] = []
  for (const c of main) if (!pages.includes(c.page)) pages.push(c.page)

  const needle = q.trim().toLowerCase()
  const found = needle
    ? extra.filter((c) => `${c.name} ${c.type_label} ${c.reason} ${c.page}`.toLowerCase().includes(needle))
    : extra

  if (!candidates.length) return null
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 4 }}>
        Виджеты ({main.filter(chosen).length} из {main.length} отмечено)
      </div>
      <div style={{ ...hint, marginBottom: 6 }}>
        Отмечено то, что рекомендую. Снимите лишнее; что покажет виджет — в ⓘ,
        тот же текст потом будет у самого виджета.
      </div>
      <div style={box}>
        {pages.map((page) => (
          <div key={page}>
            <div style={pageHead}>{page}</div>
            {main.filter((c) => c.page === page).map((c) => (
              // Вид и ⓘ — вне <label>: иначе они вошли бы в имя галочки, и
              // диктор читал бы «ИТОГО Показатель в разрезах Что покажет…».
              <div key={c.key} style={row}>
                <label style={pick}>
                  <input type="checkbox" checked={chosen(c)} onChange={() => onToggle(c)} />
                  <span style={{ minWidth: 0 }}>
                    <span style={nameStyle}>{c.name}</span>
                    {!c.recommended && (
                      <span style={{ ...hint, display: 'block' }}>добавлен вами · {c.reason}</span>
                    )}
                  </span>
                </label>
                <span style={chip}>{c.type_label}</span>
                <InfoTip text={c.explain_text} label={`Что покажет «${c.name}»`} />
              </div>
            ))}
          </div>
        ))}
      </div>

      {extra.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <button type="button" style={linkBtn} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            {open ? '▾' : '▸'} Ещё можно добавить ({extra.length})
          </button>
          {open && (
            <div style={{ marginTop: 6 }}>
              <div style={{ ...hint, marginBottom: 6 }}>
                Эти виджеты система не рекомендует — причина названа у каждого. Добавить
                можно любой: решение за вами.
              </div>
              <input
                style={search} value={q} onChange={(e) => setQ(e.target.value)}
                placeholder="Поиск по названию, виду или причине" aria-label="Поиск среди нерекомендованных виджетов"
              />
              <div style={{ ...box, maxHeight: 260 }}>
                {found.length === 0 && <div style={hint}>Ничего не найдено.</div>}
                {found.map((c) => (
                  <div key={c.key} style={row}>
                    <span style={{ minWidth: 0, flex: 1 }}>
                      <span style={nameStyle}>{c.name}</span>
                      <span style={{ ...hint, display: 'block' }}>
                        {c.page} · {c.reason}
                      </span>
                    </span>
                    <span style={chip}>{c.type_label}</span>
                    <InfoTip text={c.explain_text} label={`Что покажет «${c.name}»`} />
                    <button type="button" style={addBtn} onClick={() => onToggle(c)}
                      aria-label={`Добавить «${c.name}»`}>
                      ＋ добавить
                    </button>
                  </div>
                ))}
              </div>
              {needle && found.length > 0 && (
                <div style={{ ...hint, marginTop: 4 }}>
                  Найдено {found.length} {plural(found.length, 'виджет', 'виджета', 'виджетов')}.
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const hint: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 12 }
const box: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 320, overflowY: 'auto',
  border: '1px solid var(--border-faint)', borderRadius: 8, padding: '6px 8px',
}
const pageHead: React.CSSProperties = {
  fontSize: 11.5, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase',
  letterSpacing: 0.3, margin: '8px 0 2px',
}
const row: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, padding: '3px 0' }
const pick: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0, cursor: 'pointer',
}
const nameStyle: React.CSSProperties = { overflowWrap: 'anywhere' }
const chip: React.CSSProperties = {
  flexShrink: 0, fontSize: 11, padding: '1px 7px', borderRadius: 10,
  background: 'var(--surface-2)', color: 'var(--text-muted)', border: '1px solid var(--border-faint)',
}
const linkBtn: React.CSSProperties = {
  border: 'none', background: 'none', color: 'var(--accent-text)', fontSize: 12.5, cursor: 'pointer', padding: 0,
}
const addBtn: React.CSSProperties = {
  flexShrink: 0, height: 26, padding: '0 8px', border: '1px solid var(--border-strong)', borderRadius: 6,
  background: 'var(--surface)', color: 'var(--accent-text)', fontSize: 12, cursor: 'pointer',
}
const search: React.CSSProperties = {
  height: 30, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13,
  width: '100%', marginBottom: 6, boxSizing: 'border-box',
}
