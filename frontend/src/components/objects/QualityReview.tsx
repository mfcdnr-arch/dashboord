import { useState } from 'react'
import { getQualityReview, type QualityReview as Review } from '../../api/objects'
import { plural } from '../../lib/text'

// Проверка качества по ВСЕЙ истории формы.
//
// Замечания к данным в системе есть с 15.08, но увидеть их можно было ровно в
// двух местах, и оба смотрят на ОДИН отчёт: модератор — на тот, что выпускает,
// а блок «На что посмотреть» — на последний активный. Поэтому вопрос «а по
// всей истории где расходится?» ответа не имел: расхождение итоговой графы на
// 54 отчётах из 201 пришлось искать разовым скриптом.
//
// 🔴 Проверка НЕ запускается сама при открытии объекта. Она читает значения
// каждого отчёта целиком, и у широкой формы это двадцать тысяч строк на отчёт:
// на двухстах отчётах — десятки секунд. Глубину выбирает человек, и по
// умолчанию это последние тридцать, а не «всё».
export default function QualityReview({ objectId }: { objectId: string }) {
  const [limit, setLimit] = useState(30)
  const [res, setRes] = useState<Review | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const run = async () => {
    setBusy(true); setErr(null)
    try { setRes(await getQualityReview(objectId, limit)) }
    catch (e) { setErr((e as Error).message); setRes(null) }
    finally { setBusy(false) }
  }

  return (
    <Frame>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <b>🔎 Проверка качества по истории</b>
        <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          те же правила, что показываются при выпуске, — но по всем отчётам сразу
        </span>
        <select style={sel} value={limit} onChange={(e) => setLimit(Number(e.target.value))}
          aria-label="Глубина проверки" title="Сколько последних отчётов проверить">
          <option value={30}>последние 30</option>
          <option value={100}>последние 100</option>
          <option value={400}>всю историю</option>
        </select>
        <button type="button" style={btn} onClick={run} disabled={busy}>
          {busy ? 'Проверяю…' : 'Проверить'}
        </button>
      </div>

      {err && <div style={{ ...note, background: 'var(--danger-bg)', color: 'var(--danger)' }}>{err}</div>}

      {res && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            Проверено {res.checked} из {res.total} {plural(res.total, 'отчёта', 'отчётов', 'отчётов')}
            {res.first_period && res.last_period
              ? ` (${ru(res.first_period)} — ${ru(res.last_period)})` : ''}
            {' · '}без замечаний: <b>{res.clean}</b>
          </div>

          {res.issues.length === 0 ? (
            <div style={{ ...note, background: 'var(--alert-good-bg)', color: 'var(--alert-good)' }}>
              ✓ Замечаний нет ни в одном проверенном отчёте.
            </div>
          ) : (
            <div style={{ marginTop: 10 }}>
              {res.issues.map((i) => (
                <div key={i.code} style={row}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div><b>{i.title}</b></div>
                    {/* Пример — с числами из настоящего отчёта: заголовок
                        правила сам по себе не говорит, насколько всё плохо. */}
                    {i.example && <div style={sample} title={i.example}>{i.example}</div>}
                    <div style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 4 }}>
                      {i.periods.slice(0, 12).map(ru).join(', ')}
                      {i.releases > i.periods.length || i.periods.length > 12
                        ? ` … и ещё ${i.releases - Math.min(12, i.periods.length)}` : ''}
                    </div>
                  </div>
                  <div style={{ whiteSpace: 'nowrap', fontSize: 13 }}>
                    {i.releases} {plural(i.releases, 'отчёт', 'отчёта', 'отчётов')}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Граница проверки названа прямо: замечания к РАЗБОРУ файла (строки
              без названия, нераспознанные числа) считаются по сетке исходного
              листа в момент выпуска, и задним числом их не пересчитать. */}
          <div style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 10 }}>
            Проверяется арифметика выпущенных значений и сверка с предыдущим отчётом.
            Замечания к разбору самого файла видны только в момент выпуска.
          </div>
        </div>
      )}
    </Frame>
  )
}

/** Отчётные даты по-русски: в системе принят ДД.ММ.ГГГГ. */
function ru(v: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(v) ? v.split('-').reverse().join('.') : v
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
  fontSize: 13, color: 'var(--text-muted)', overflow: 'hidden',
  textOverflow: 'ellipsis', whiteSpace: 'nowrap',
}
const note: React.CSSProperties = {
  marginTop: 10, padding: '8px 10px', borderRadius: 8, fontSize: 13,
}
const sel: React.CSSProperties = {
  height: 34, padding: '0 8px', border: '1px solid var(--border-strong)',
  borderRadius: 8, fontSize: 14, marginLeft: 'auto',
}
const btn: React.CSSProperties = {
  height: 34, padding: '0 14px', border: 'none', borderRadius: 8,
  background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer',
}
