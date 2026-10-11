import { useEffect, useState } from 'react'
import {
  confirmOfficeNames, confirmSuggestedOfficeNames, forgetOfficeName, getOfficeNames,
  type NameConfirmResult, type NameItem, type OfficeNamesReview,
} from '../../api'
import { plural } from '../../lib/text'
import { useConfirm } from '../dashboards/ConfirmDialog'
import Notice from '../Notice'

// Эталонные названия отделений в формах.
//
// Одно отделение формы пишут по-разному («Отделение МФЦ № 3 г. Донецк» и
// «Отделение № 3 ГБУ "МФЦ ДНР" г. Донецк пр-т Ильича, 63 а»), и для системы
// это разные строки: формы не сопоставляются, а на карту ничего не попадает.
// Здесь человек один раз подтверждает, какой вариант какому отделению
// соответствует, — дальше система подменяет его при выпуске сама.

export default function OfficeNamesPanel({ openSeq, onChanged }: { openSeq?: number; onChanged?: () => void }) {
  const { ask, node: confirmNode } = useConfirm()
  const [data, setData] = useState<OfficeNamesReview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<NameConfirmResult | null>(null)
  const [pick, setPick] = useState<Record<string, string>>({})
  const [showDecisions, setShowDecisions] = useState(false)

  const fail = (e: unknown) => setError((e as Error).message)
  const load = () => getOfficeNames().then(setData).catch(fail)
  useEffect(() => { load() }, [openSeq]) // eslint-disable-line react-hooks/exhaustive-deps

  async function run(p: Promise<NameConfirmResult>) {
    setBusy(true); setError(null); setRes(null)
    try { setRes(await p); await load(); onChanged?.() } catch (e) { fail(e) } finally { setBusy(false) }
  }

  async function confirmAll() {
    const n = data?.with_suggestion || 0
    if (!await ask({
      title: `Подтвердить ${n} ${plural(n, 'подсказку', 'подсказки', 'подсказок')}?`,
      message: 'Система запомнит, какому отделению соответствует каждый вариант, и переименует его во всех '
        + 'уже загруженных отчётах. Числа не меняются — меняется только название строки. Если в каком-то отчёте '
        + 'эталонное название уже есть, этот отчёт не трогается и будет назван отдельно.',
      confirmLabel: 'Подтвердить', busyLabel: 'Сопоставление…', tone: 'accent',
    })) return
    await run(confirmSuggestedOfficeNames())
  }

  function one(it: NameItem, officeId: string | null) {
    return run(confirmOfficeNames([{ label: it.label, office_id: officeId }]))
  }

  async function forget(id: string, label: string) {
    if (!await ask({
      title: `Забыть соответствие «${label}»?`,
      message: 'Новые файлы с этим названием больше не будут подменяться. Уже переименованные отчёты останутся '
        + 'как есть: обратно их не отличить от строк, которые пришли с эталонным названием.',
      confirmLabel: 'Забыть',
    })) return
    setBusy(true)
    try { await forgetOfficeName(id); await load() } catch (e) { fail(e) } finally { setBusy(false) }
  }

  const formName = (code: string) => data?.forms.find((f) => f.code === code)?.object_name || code
  const items = data?.items || []

  return (
    <div style={card}>
      {confirmNode}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <h2 style={{ fontSize: 13, fontWeight: 700, margin: 0 }}>Названия отделений в формах</h2>
        {data && (
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            форм по отделениям: {data.forms.length} · не узнано {items.length}
            {items.length > 0 && ` · с уверенной подсказкой ${data.with_suggestion}`}
          </span>
        )}
        <div style={{ flex: 1 }} />
        {data && data.with_suggestion > 0 && (
          <button style={btn} disabled={busy} onClick={confirmAll}>
            ✓ Подтвердить все подсказки ({data.with_suggestion})
          </button>
        )}
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
        Разные формы пишут одно отделение по-разному. Подтвердите один раз, какому отделению соответствует название, —
        дальше система сама подменит его эталонным при каждой загрузке, и формы можно будет сравнивать между собой
        и показывать на карте. Незнакомое название система молча не подменяет.
      </div>
      {error && <Notice>{error}</Notice>}
      {res && <Notice kind="ok">{resultText(res)}</Notice>}
      {res && res.conflicts.length > 0 && (
        <Notice kind="warn">
          Не переименовано в {res.conflicts.length} {plural(res.conflicts.length, 'отчёте', 'отчётах', 'отчётах')}:
          там уже есть строка с эталонным названием, и переименование сложило бы цифры одного отделения дважды.
          {' '}{res.conflicts.slice(0, 3).map((c) => `${formName(c.code)} за ${fmtDate(c.period)}`).join('; ')}
          {res.conflicts.length > 3 && ` и ещё ${res.conflicts.length - 3}`}.
        </Notice>
      )}
      {!data && !error && <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>Сверяю формы…</div>}
      {data && items.length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--success)' }}>
          ✓ Во всех формах по отделениям названия совпадают с эталоном.
        </div>
      )}
      {items.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', maxHeight: 360, overflowY: 'auto' }}>
          {items.map((it) => (
            <div key={it.label} style={rowLine}>
              <div style={{ flex: '1 1 260px', minWidth: 0 }}>
                <div style={{ overflowWrap: 'anywhere' }}>{it.label}</div>
                <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>
                  {it.forms.length === 1 ? formName(it.forms[0])
                    : `в ${it.forms.length} ${plural(it.forms.length, 'форме', 'формах', 'формах')}: ${it.forms.slice(0, 2).map(formName).join(', ')}${it.forms.length > 2 ? '…' : ''}`}
                </div>
              </div>
              <div style={{ flex: '1 1 260px', minWidth: 0, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
                {it.suggestion ? (
                  <>
                    <span style={{ fontSize: 12 }} title={it.suggestion.target || undefined}>
                      → <b>{it.suggestion.office}</b>
                      <span style={{ color: 'var(--text-muted)' }}> · {it.suggestion.reason}</span>
                    </span>
                    <button style={linkBtn} disabled={busy} onClick={() => one(it, it.suggestion!.office_id)}>подтвердить</button>
                  </>
                ) : (
                  <>
                    <select style={{ ...inp, maxWidth: 260 }} value={pick[it.label] || ''}
                      aria-label={`Отделение для названия «${it.label}»`}
                      onChange={(e) => setPick({ ...pick, [it.label]: e.target.value })}>
                      <option value="">— выберите отделение —</option>
                      {data!.offices.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                    </select>
                    <button style={linkBtn} disabled={busy || !pick[it.label]}
                      onClick={() => one(it, pick[it.label])}>сопоставить</button>
                  </>
                )}
                <button style={{ ...linkBtn, color: 'var(--text-muted)' }} disabled={busy}
                  title="Итоговая или служебная строка: больше не спрашивать"
                  onClick={() => one(it, null)}>не отделение</button>
              </div>
            </div>
          ))}
        </div>
      )}
      {data && data.decisions.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <button style={linkBtn} aria-expanded={showDecisions} onClick={() => setShowDecisions(!showDecisions)}>
            {showDecisions ? '▾' : '▸'} Запомненные соответствия ({data.decisions.length})
          </button>
          {showDecisions && (
            <div style={{ display: 'flex', flexDirection: 'column', maxHeight: 260, overflowY: 'auto', marginTop: 4 }}>
              {data.decisions.map((d) => (
                <div key={d.id} style={rowLine}>
                  <span style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{d.label}</span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {d.status === 'ignored' ? 'не отделение' : `→ ${d.office}`}
                  </span>
                  <button style={linkBtn} disabled={busy} onClick={() => forget(d.id, d.label)}>забыть</button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function resultText(r: NameConfirmResult): string {
  const parts: string[] = []
  const n = r.aliased.length + r.linked.length
  if (n) parts.push(`Сопоставлено ${n} ${plural(n, 'название', 'названия', 'названий')}`)
  if (r.renamed_values) {
    parts.push(`переименовано строк в ${r.renamed_releases} ${plural(r.renamed_releases, 'отчёте', 'отчётах', 'отчётах')}`)
  }
  if (r.ignored.length) parts.push(`помечено «не отделение»: ${r.ignored.length}`)
  if (r.errors.length) parts.push(`не удалось: ${r.errors.map((e) => `${e.label} — ${e.error}`).join('; ')}`)
  if (r.left_manual?.length) {
    parts.push(`осталось решить вручную: ${r.left_manual.length} — у них нет однозначного отделения`)
  }
  if (!parts.length) return 'Нечего менять.'
  const t = parts.join(', ') + '.'
  return t[0].toUpperCase() + t.slice(1)
}

function fmtDate(iso?: string | null): string {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}.${m}.${y}`
}

const btn: React.CSSProperties = { height: 32, padding: '0 12px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer' }
const inp: React.CSSProperties = { height: 30, padding: '0 8px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 12, boxSizing: 'border-box', background: 'var(--surface)', color: 'var(--text)' }
const linkBtn: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent-text)', cursor: 'pointer', fontSize: 12, padding: '0 6px 0 0' }
const card: React.CSSProperties = { border: '1px solid var(--border-faint)', borderRadius: 10, padding: 12, marginBottom: 12, background: 'var(--surface-2)', boxSizing: 'border-box' }
const rowLine: React.CSSProperties = { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, fontSize: 13, padding: '5px 0', borderBottom: '1px solid var(--border-faint)' }
