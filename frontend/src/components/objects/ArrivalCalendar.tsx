import { useEffect, useState } from 'react'
import { getFolderCalendar, type CalendarState, type CalendarWeek, type FolderCalendar } from '../../api'

const ru = (iso?: string | null) => (iso ? iso.split('-').reverse().join('.') : '—')

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
                'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

// Цвет плитки — из токенов темы, а не жёстким hex: те же `--alert-*`, что
// красят пороги на карточках и в таблице (иначе в тёмной теме календарь
// светился бы светлыми маркерами — эти грабли в проекте уже ловили).
//
// «Пропущен» и «не распознан» оба означают «данных за неделю нет», но
// различаются причиной, поэтому различаются и подачей: пропуск — ПУСТАЯ
// клетка в красной рамке (файла нет вовсе), сломанный файл — залитая с ⚠
// (файл есть, но до данных не дошёл).
const LOOK: Record<CalendarState, { bg: string; fg: string; border: string; mark: string; title: string }> = {
  released: { bg: 'var(--alert-good-bg)', fg: 'var(--alert-good)', border: 'var(--alert-good)', mark: '', title: 'данные выпущены' },
  arrived:  { bg: 'var(--alert-warn-bg)', fg: 'var(--alert-warn)', border: 'var(--alert-warn)', mark: '', title: 'файл пришёл, данные не выпущены' },
  failed:   { bg: 'var(--alert-danger-bg)', fg: 'var(--alert-danger)', border: 'var(--alert-danger)', mark: '⚠', title: 'файл не распознан' },
  missing:  { bg: 'transparent', fg: 'var(--alert-danger)', border: 'var(--alert-danger)', mark: '', title: 'отчёт не поступил' },
  empty:    { bg: 'var(--surface-2)', fg: 'var(--text-faint)', border: 'var(--border-faint)', mark: '', title: 'отчёта здесь не ждали' },
}

// Календарь поступлений формы (п. 16 второй волны предложений).
//
// Пропуски в ряду отчётов и до этого были видны — но только строкой «не
// хватает отчётов за 29.07.2026» в аналитике папки. Строка верна и на один
// пропуск читается прекрасно; за год их набирается десяток, и увидеть в
// перечислении дат полосу или сезон нельзя. Плитка отвечает на тот же вопрос
// глазами.
//
// Экран НИЧЕГО не считает сам: и ритм, и список пропусков приходят с сервера
// из тех же функций, что шлют уведомления о пропущенном отчёте.
export default function ArrivalCalendar(
  { objectId, folderId }: { objectId: string; folderId: string },
) {
  const [d, setD] = useState<FolderCalendar | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [year, setYear] = useState<number | undefined>(undefined)

  useEffect(() => {
    setErr(null)
    getFolderCalendar(objectId, folderId, year)
      .then(setD)
      .catch((e) => setErr((e as Error).message))
  }, [objectId, folderId, year])

  if (err) return <div style={errBox}>{err}</div>
  if (!d) return <div style={muted}>Загрузка…</div>

  // Месяцы, в которых есть хоть одна неделя. Пустых строк не рисуем: у
  // формы, начавшейся в июле, полгода пустых рядов сверху — это шум.
  const byMonth: CalendarWeek[][] = Array.from({ length: 12 }, () => [])
  d.weeks.forEach((w) => byMonth[w.month - 1].push(w))
  const t = d.totals

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
        {d.years.length > 1 && (
          <select value={d.year} onChange={(e) => setYear(Number(e.target.value))} style={sel}>
            {d.years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        )}
        {d.years.length === 1 && <b style={{ fontSize: 13 }}>{d.year}</b>}
        <Legend state="released" label={`выпущено (${t.released})`} />
        {t.arrived > 0 && <Legend state="arrived" label={`пришло, без данных (${t.arrived})`} />}
        {t.failed > 0 && <Legend state="failed" label={`не распознано (${t.failed})`} />}
        {t.missing > 0 && <Legend state="missing" label={`не поступило (${t.missing})`} />}
      </div>

      <div style={muted}>
        {d.cadence_days
          ? `Форма приходит раз в ${d.cadence_days} дн. — пропущенные отчёты отмечены красным.`
          : 'Ритм формы пока не определён (нужно не меньше четырёх отчётов), поэтому пропуски не отмечаются: '
            + 'система не станет выдумывать расписание, которого у формы нет.'}
      </div>

      <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 3 }}>
        {byMonth.map((weeks, m) => (
          weeks.length === 0 ? null : (
            <div key={m} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 30, fontSize: 11, color: 'var(--text-2)', textAlign: 'right', flexShrink: 0 }}>
                {MONTHS[m]}
              </div>
              <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                {weeks.map((w) => <Tile key={w.week} w={w} today={d.today} />)}
              </div>
            </div>
          )
        ))}
      </div>

      {t.undated > 0 && (
        <div style={{ ...muted, marginTop: 8 }}>
          Файлов без отчётной даты: {t.undated} — на календаре их разместить негде.
        </div>
      )}
    </div>
  )
}

function Tile({ w, today }: { w: CalendarWeek; today: string }) {
  const look = LOOK[w.state]
  // Неделя, которая ещё не кончилась: отчёт по ней ждать рано. Метка нужна
  // как ориентир «мы здесь», поэтому она НЕЙТРАЛЬНАЯ — подчёркивание, а не
  // цветная обводка: акцентная рамка рядом с красной плиткой пропуска
  // читалась как ещё один сигнал тревоги (поймано осмотром кадра).
  const current = w.start <= today && today <= w.end
  const lines = [
    `Неделя ${ru(w.start)} — ${ru(w.end)}`,
    `Состояние: ${look.title}`,
    ...(current ? ['Текущая неделя — она ещё не кончилась.'] : []),
    ...w.reports.map((r) => `• ${r.filename} · отчёт за ${ru(r.period)}`
      + (r.released ? ' · данные выпущены' : r.status === 'failed' ? ' · не распознан' : ' · данных ещё нет')),
    ...w.missing.map((m) => `• ожидался отчёт за ${ru(m)} — файла нет`),
  ]
  return (
    <div
      title={lines.join('\n')}
      style={{
        width: 34, height: 26, borderRadius: 5,
        background: look.bg,
        borderWidth: 1, borderStyle: w.state === 'missing' ? 'dashed' : 'solid',
        borderColor: look.border,
        color: look.fg, fontSize: 10, fontWeight: 600,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        position: 'relative', cursor: 'default',
        boxShadow: current ? 'inset 0 -3px 0 var(--text-2)' : undefined,
      }}
    >
      {Number(w.start.slice(8, 10))}
      {w.problem && (
        // Проблемный файл рядом с выпущенным не должен теряться за зелёной
        // плиткой: угловая метка видна независимо от основного состояния.
        <span style={{ position: 'absolute', top: -4, right: -3, fontSize: 9, color: 'var(--alert-danger)' }}>⚠</span>
      )}
    </div>
  )
}

function Legend({ state, label }: { state: CalendarState; label: string }) {
  const look = LOOK[state]
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--text-2)' }}>
      <span style={{
        width: 12, height: 12, borderRadius: 3, background: look.bg,
        borderWidth: 1, borderStyle: state === 'missing' ? 'dashed' : 'solid', borderColor: look.border,
        display: 'inline-block',
      }} />
      {label}
    </span>
  )
}

const muted: React.CSSProperties = { fontSize: 12, color: 'var(--text-2)' }
const sel: React.CSSProperties = {
  padding: '3px 6px', fontSize: 12, borderRadius: 6,
  border: '1px solid var(--border-strong)', background: 'var(--surface)', color: 'var(--text)',
}
const errBox: React.CSSProperties = {
  padding: 10, borderRadius: 8, fontSize: 13,
  background: 'var(--alert-danger-bg)', color: 'var(--alert-danger)',
}
