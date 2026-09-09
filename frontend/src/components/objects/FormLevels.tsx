import { useEffect, useState } from 'react'
import {
  confirmFormLevels, getFormLevels,
  type LevelsState,
} from '../../api/objects'

// Мастер ступеней формы — кусок 2 «лестницы».
//
// Замысел заказчика: «делай общий дашборд, потом постепенно разбивай данные на
// более мелкие показатели — по ведомствам, потом по услугам в этих ведомствах».
// Система читает устройство формы по именам граф и ПРЕДЛАГАЕТ ступени; человек
// подтверждает их и даёт названия — один раз на форму, дальше она узнаётся
// сама (тот же контракт, что у разметки: «разметил раз — дальше само»).
//
// 🔴 Названия уровней система не придумывает намеренно. Надёжного источника в
// данных нет: столбец меток строк у РЦО зовётся «Наименование услуги ·
// Наименование отдела МФЦ», у «Статистики услуг» — «МФЦ (адрес)». Подсунуть
// правдоподобное «Ведомство» хуже пустого поля: человек подтвердит не глядя, а
// имя потом попадёт в текст интерфейса. Вместо угадывания показываем ЗНАЧЕНИЯ
// ступени — увидев «Росреестр, МВД, ЕСИА (260)», человек называет уровень сам.
export default function FormLevels(
  { objectId }: { objectId: string },
) {
  const [st, setSt] = useState<LevelsState | null>(null)
  const [open, setOpen] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [names, setNames] = useState<Record<number, string>>({})
  const [rowName, setRowName] = useState('')
  const [group, setGroup] = useState(true)
  const [measure, setMeasure] = useState<string>('')

  const load = () => {
    setErr(null)
    getFormLevels(objectId).then((s) => {
      setSt(s)
      // Подтверждённое подставляем в поля: человек правит, а не вводит заново.
      const c = s.confirmed
      setNames(Object.fromEntries((c?.levels || []).map((l) => [l.index, l.name])))
      setRowName(c?.row_level || '')
      setGroup(c?.group_lone ?? true)
      setMeasure(c?.measure_default || s.suggestion.measure_default || '')
    }).catch((e) => setErr((e as Error).message))
  }
  useEffect(() => { setSt(null); setOpen(false); load() }, [objectId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Перечитываем при возврате к вкладке. Форма меняется не здесь, а на
  // «Загрузке»: человек выпускает новый файл изменившейся структуры, отпечаток
  // в шаблоне становится другим, и подтверждение устаревает. Без этого блок
  // продолжал бы писать «подтверждены» до перезагрузки страницы — найдено
  // живой проверкой. Тот же приём, что у счётчика обращений.
  useEffect(() => {
    const again = () => { if (!document.hidden) load() }
    window.addEventListener('focus', again)
    document.addEventListener('visibilitychange', again)
    return () => {
      window.removeEventListener('focus', again)
      document.removeEventListener('visibilitychange', again)
    }
  }, [objectId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <Frame><span style={{ color: 'var(--danger)' }}>{err}</span></Frame>
  if (!st) return null

  const s = st.suggestion
  // Ступеней в форме нет — сказать это прямо и не предлагать мастер. Пустая
  // лестница на плоской форме выглядела бы недоделкой, а не ответом.
  if (s.kind !== 'hierarchy') {
    return (
      <Frame>
        <b>🪜 Ступени формы</b>
        <div style={{ color: 'var(--text-muted)', marginTop: 6 }}>{s.reason}</div>
      </Frame>
    )
  }

  const ready = st.confirmed && !st.stale
  const filled = s.levels.every((l) => (names[l.index] || '').trim()) && rowName.trim()

  const save = async () => {
    setBusy(true); setErr(null)
    try {
      await confirmFormLevels(objectId, {
        levels: s.levels.map((l) => ({ index: l.index, name: (names[l.index] || '').trim() })),
        row_level: rowName.trim(), group_lone: group, measure_default: measure || null,
      })
      load(); setOpen(false)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <Frame>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <b>🪜 Ступени формы</b>
        <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          {ready
            ? `подтверждены: ${st.confirmed!.levels.map((l) => l.name).join(' → ')} → ${st.confirmed!.row_level}`
            : st.stale
              ? 'форма изменилась — подтвердите заново'
              : `система нашла ${s.levels.length === 1 ? 'одну ступень' : `${s.levels.length} ступени`}`}
        </span>
        <button type="button" style={link} onClick={() => setOpen(!open)}>
          {open ? 'свернуть' : ready ? 'изменить' : 'посмотреть и подтвердить'}
        </button>
      </div>

      {/* Устаревшее подтверждение не молчит: применить его нельзя, и человек
          должен понимать, почему лестница пропала с дашборда. */}
      {st.stale && (
        <div style={{ ...note, background: 'var(--alert-warn-bg)', color: 'var(--alert-warn)' }}>
          ⚠ Форма изменилась с тех пор, как ступени подтверждали. Прежняя иерархия
          не применяется — на новом бланке она показала бы уровни, которых в нём нет.
          Проверьте предложение ниже и подтвердите заново.
        </div>
      )}

      {open && (
        <div style={{ marginTop: 12 }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 10 }}>{s.reason}</div>

          {s.levels.map((l) => (
            <div key={l.index} style={row}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                  Ступень {l.index + 1} · значений: {l.count}
                </div>
                <div style={sample} title={l.sample.join(' · ')}>
                  {l.sample.join(' · ')}{l.count > l.sample.length ? ' …' : ''}
                </div>
              </div>
              <input
                style={input} placeholder="Как назвать этот уровень"
                value={names[l.index] || ''}
                onChange={(e) => setNames({ ...names, [l.index]: e.target.value })} />
            </div>
          ))}

          {/* Строки формы — самая мелкая ступень, и её тоже надо назвать. */}
          <div style={row}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                Нижняя ступень · строк в форме: {s.rows.count}
              </div>
              <div style={sample} title={s.rows.sample.join(' · ')}>{s.rows.sample.join(' · ')}</div>
            </div>
            <input style={input} placeholder="Как назвать этот уровень"
              value={rowName} onChange={(e) => setRowName(e.target.value)} />
          </div>

          {s.measures.length > 0 && (
            <div style={{ ...row, alignItems: 'center' }}>
              <div style={{ minWidth: 0, flex: 1, fontSize: 13, color: 'var(--text-muted)' }}>
                Что показывать на ступени по умолчанию. Переключить можно будет на самой карточке.
              </div>
              <select style={input} value={measure} onChange={(e) => setMeasure(e.target.value)}>
                {s.measures.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
          )}

          {/* Группировка предлагается, только когда ей есть что делать: на
              короткой и на одноступенчатой форме сервер её не считает. */}
          {s.group && s.group.lone.length > 0 && (
            <label style={{ ...row, alignItems: 'flex-start', cursor: 'pointer' }}>
              <input type="checkbox" checked={group} onChange={(e) => setGroup(e.target.checked)}
                style={{ marginTop: 3 }} />
              <span style={{ minWidth: 0, flex: 1 }}>
                <div>Свести одинокие значения в «Отдельные услуги»</div>
                <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                  {s.group.reason} Первый экран: {s.group.rows} строк вместо {s.levels[0].count}.
                </div>
                <div style={sample} title={s.group.lone.join(' · ')}>{s.group.lone.join(' · ')}</div>
              </span>
            </label>
          )}

          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 12 }}>
            <button type="button" style={btn} disabled={!filled || busy} onClick={save}>
              {busy ? 'Сохранение…' : 'Подтвердить ступени'}
            </button>
            {!filled && (
              <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                Назовите каждый уровень — эти имена система будет писать в подсказках
                и в крошках дашборда.
              </span>
            )}
          </div>
        </div>
      )}
    </Frame>
  )
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px',
      marginBottom: 14, background: 'var(--surface-2)', fontSize: 14,
    }}>{children}</div>
  )
}

const row: React.CSSProperties = {
  display: 'flex', gap: 12, alignItems: 'flex-start', padding: '10px 0',
  borderTop: '1px solid var(--border)',
}
const sample: React.CSSProperties = {
  fontSize: 13, color: 'var(--text-faint)', overflow: 'hidden',
  textOverflow: 'ellipsis', whiteSpace: 'nowrap',
}
const note: React.CSSProperties = {
  marginTop: 10, padding: '8px 10px', borderRadius: 8, fontSize: 13,
}
const input: React.CSSProperties = {
  height: 34, padding: '0 10px', border: '1px solid var(--border-strong)',
  borderRadius: 8, fontSize: 14, width: 240, flexShrink: 0,
}
const btn: React.CSSProperties = {
  height: 34, padding: '0 14px', border: 'none', borderRadius: 8,
  background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer',
}
const link: React.CSSProperties = {
  marginLeft: 'auto', background: 'none', border: 'none', color: 'var(--accent)',
  cursor: 'pointer', fontSize: 13, textDecoration: 'underline dotted',
}
