import { useEffect, useState } from 'react'
import { getRestoreCheck, runRestoreCheckNow, type RestoreCheckState } from '../api'
import { plural } from '../lib/text'

// Проверка резервной копии НАСТОЯЩИМ восстановлением (restore-check.sh на хосте).
//
// backup.sh убеждается, что дамп читается; эта проверка — что из него
// действительно поднимается база. Хост делает её сам раз в месяц ночью; здесь —
// итог последней проверки и «Проверить сейчас». Отсутствие проверки не
// выдаётся за порядок: «ни разу» и «давно» видны отдельно.
const ruDate = (iso: string) => new Date(iso).toLocaleDateString('ru-RU')

export default function RestoreCheckLine() {
  const [st, setSt] = useState<RestoreCheckState | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = () => getRestoreCheck().then(setSt).catch((e) => setErr((e as Error).message))
  useEffect(() => { load() }, [])

  if (err) return <div style={{ fontSize: 12.5, color: 'var(--danger)', marginTop: 8 }}>{err}</div>
  if (!st) return null
  const run = async () => {
    setBusy(true); setErr(null)
    try { await runRestoreCheckNow(); await load() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const last = st.last
  const ago = st.age_days == null ? '' : st.age_days === 0 ? ' (сегодня)'
    : ` (${st.age_days} ${plural(st.age_days, 'день', 'дня', 'дней')} назад)`
  const when = last ? ` ${ruDate(last.ts)}${ago}` : ''
  const line = {
    ok: { c: 'var(--success)', t: `✓ Последняя копия проверена восстановлением${when}: всё совпало.` },
    diff: { c: 'var(--success)', t: `✓ Последняя копия проверена восстановлением${when}: набор цел (рабочая база с тех пор ушла вперёд — это нормально).` },
    fail: { c: 'var(--danger)', t: `⚠ Проверка восстановлением${when} НЕ пройдена: восстановиться из этой копии может не получиться.` },
    overdue: { c: 'var(--warn)', t: `⚠ Копию давно не проверяли восстановлением — последний раз${when}. Плановая проверка — раз в ${st.planned_days} дней; возможно, наблюдатель на сервере не работает.` },
    never: { c: 'var(--warn)', t: 'Копию ещё ни разу не проверяли восстановлением. Сервер делает это сам раз в месяц ночью; первую проверку можно запустить сейчас.' },
  }[st.state]
  return (
    <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Проверка восстановлением</div>
      <div style={{ fontSize: 12.5, color: line.c, marginBottom: 4 }}>{line.t}</div>
      {last?.message && st.state !== 'never' && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }} title={last.message}>
          {last.set && !last.message.includes(last.set) && <>Набор {last.set}. </>}{last.message.length > 220 ? last.message.slice(0, 220) + '…' : last.message}
        </div>
      )}
      {(st.pending || st.running) && (
        <div style={{ fontSize: 12, color: 'var(--warn)', marginBottom: 6 }}>
          {st.running ? '⏳ Проверка идёт — обычно это несколько минут.' : '⏳ Заявка ожидает хоста (до 1 мин).'}
        </div>
      )}
      <button
        style={{ height: 32, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 8,
          background: 'var(--surface)', color: 'var(--text-2)', fontSize: 13, cursor: 'pointer' }}
        disabled={busy || st.pending || st.running} onClick={run}
        title="Восстанавливает последний годный набор во временную базу рядом с рабочей и сверяет. Рабочая база только читается.">
        {busy ? '⏳ Отправка…' : '🔁 Проверить сейчас'}
      </button>
    </div>
  )
}
