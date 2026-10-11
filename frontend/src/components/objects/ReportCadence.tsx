import { useEffect, useState } from 'react'
import { getObjectCadence, updateObject, type ObjectCadence } from '../../api/objects'
import { plural } from '../../lib/text'

// Как часто приходит отчёт объекта.
//
// Ритм система выводит из истории, и ей нужно четыре отчёта: у новой формы
// напоминание «отчёт не поступил» молчит первый месяц. Если ритм известен
// заранее (книга Минэкономразвития — каждую неделю), его задают здесь, и он
// действует с первого отчёта. Рядом — что система поняла сама.
const OPTIONS: { v: number | null; t: string }[] = [
  { v: null, t: 'определять по истории' },
  { v: 1, t: 'каждый день' },
  { v: 7, t: 'каждую неделю' },
  { v: 30, t: 'каждый месяц' },
]
const ruDate = (iso: string) => new Date(iso).toLocaleDateString('ru-RU')

export default function ReportCadence({ objectId }: { objectId: string }) {
  const [st, setSt] = useState<ObjectCadence | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = () => getObjectCadence(objectId).then(setSt).catch((e) => setErr((e as Error).message))
  useEffect(() => { setSt(null); load() }, [objectId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <div style={frame}><span style={{ color: 'var(--danger)' }}>{err}</span></div>
  if (!st || st.reports === 0) return null
  const save = async (v: number | null) => {
    setBusy(true); setErr(null)
    try { await updateObject(objectId, { report_cadence_days: v }); await load() }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const custom = st.declared != null && !OPTIONS.some((o) => o.v === st.declared)
  const found = st.inferred
    ? `По истории система определила: раз в ${st.inferred} ${plural(st.inferred, 'день', 'дня', 'дней')}.`
    : `По истории его пока не определить: ${st.reports} ${plural(st.reports, 'отчёт', 'отчёта', 'отчётов')}, а нужно хотя бы 4.`
  return (
    <div style={frame}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <b>📅 Отчёт приходит</b>
        <select aria-label="Как часто приходит отчёт" disabled={busy}
          value={st.declared ?? ''} onChange={(e) => save(e.target.value ? Number(e.target.value) : null)}
          style={{ height: 28, borderRadius: 6, border: '1px solid var(--border-strong)', background: 'var(--surface)', color: 'var(--text)', fontSize: 13 }}>
          {OPTIONS.map((o) => <option key={o.t} value={o.v ?? ''}>{o.t}</option>)}
          {custom && <option value={st.declared!}>раз в {st.declared} дн.</option>}
        </select>
      </div>
      <div style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 6 }}>
        {st.declared == null
          ? <>Ритм не задан. {found}{!st.inferred && ' Пока ритма нет, напоминание «отчёт не поступил» не придёт; если он известен, выберите его здесь.'}</>
          : <>Задано вручную. {found}</>}
        {st.next_expected && <> Следующий отчёт ожидается за <b>{ruDate(st.next_expected)}</b> — если не придёт, управляющим придёт напоминание.</>}
      </div>
    </div>
  )
}

const frame: React.CSSProperties = {
  border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px',
  marginBottom: 14, background: 'var(--surface-2)', fontSize: 14,
}
