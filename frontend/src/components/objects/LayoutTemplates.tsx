import { useEffect, useState } from 'react'
import {
  forgetLayoutTemplate, getLayoutTemplates, restoreLayoutTemplate, type TemplateHistory,
} from '../../api/objects'
import { plural } from '../../lib/text'
import { useConfirm } from '../dashboards/ConfirmDialog'

// Шаблоны разметки форм объекта и их прежние версии.
//
// До 09.10.2026 шаблон был один на объект, и выпуск одного листа книги затирал
// разметку соседнего. Теперь шаблон — на ФОРМУ (объект + код набора): у книги
// Минэкономразвития их четыре. Блок показывает, какие формы объект узнаёт сам,
// возвращает прежний шаблон кнопкой и даёт «перестать узнавать» форму, которую
// завёл ошибочный выпуск под новым кодом — иначе она навсегда участвовала бы в
// узнавании файлов. Пока узнаётся одна форма и истории нет, блок молчит:
// строка «шаблон есть» без действий — шум.
const ruDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '—')

export default function LayoutTemplates({ objectId }: { objectId: string }) {
  const [st, setSt] = useState<TemplateHistory | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { ask, node } = useConfirm()

  useEffect(() => {
    setSt(null); setErr(null)
    getLayoutTemplates(objectId).then(setSt).catch((e) => setErr((e as Error).message))
  }, [objectId])

  if (err) return <div style={frame}><span style={{ color: 'var(--danger)' }}>{err}</span></div>
  const templates = st?.templates ?? []
  if (!st || (!st.history.length && templates.length <= 1)) return null
  const multi = templates.length > 1

  const restore = async (id: string, when: string, title: string) => {
    const ok = await ask({
      title: 'Вернуть прежний шаблон разметки?',
      message: `Следующие файлы формы «${title}» будут размечаться так, как до ${when}. `
        + 'Действующий шаблон этой формы не пропадёт — он уйдёт в историю, и его можно будет вернуть так же. '
        + 'Остальные формы объекта не изменятся.',
      confirmLabel: 'Вернуть', tone: 'accent',
    })
    if (!ok) return
    setBusy(true)
    try { setSt(await restoreLayoutTemplate(objectId, id)) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  const forget = async (code: string, title: string) => {
    const ok = await ask({
      title: `Перестать узнавать форму «${title}»?`,
      message: 'Новые файлы с этой формой придётся размечать вручную. Выпущенные данные не тронутся, '
        + 'а шаблон уйдёт в историю — его можно вернуть кнопкой «Вернуть».',
      confirmLabel: 'Перестать узнавать', tone: 'danger',
    })
    if (!ok) return
    setBusy(true)
    try { setSt(await forgetLayoutTemplate(objectId, code)) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <div style={frame}>
      {node}
      <b>🧩 Шаблоны разметки</b>
      {templates.length > 0 && (
        <div style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 4 }}>
          {multi
            ? `Объект узнаёт сам ${templates.length} ${plural(templates.length, 'форму', 'формы', 'форм')} — по одной на лист книги:`
            : 'Объект узнаёт форму сам:'}
        </div>
      )}
      {templates.map((c) => {
        const title = c.title || c.sheet_name || c.dataset_code || '—'
        return (
          <div key={c.dataset_code || title} style={row}>
            <div style={{ flex: 1, minWidth: 0 }}>
              {multi ? <b style={{ fontWeight: 600 }}>{title}</b> : `код «${c.dataset_code}»`}
              {multi && <span style={{ color: 'var(--text-muted)' }}> · код «{c.dataset_code}»</span>}
              <div style={{ color: 'var(--text-muted)', fontSize: 12.5 }}>
                {c.fields} {plural(c.fields, 'графа', 'графы', 'граф')}
                {c.period && `, по выпуску за ${ruDate(c.period)}`}, действует с {ruDate(c.updated_at)}
              </div>
            </div>
            {c.dataset_code && (
              <button style={btnGhost} disabled={busy} onClick={() => forget(c.dataset_code!, title)}>
                Перестать узнавать
              </button>
            )}
          </div>
        )
      })}
      {st.history.length > 0 && (
        <div style={{ fontSize: 13, marginTop: 10, color: 'var(--text-2)' }}>Прежние шаблоны:</div>
      )}
      {st.history.map((h) => {
        const title = h.title || h.sheet_name || h.dataset_code || '—'
        return (
          <div key={h.id} style={row}>
            <div style={{ flex: 1, minWidth: 0 }}>
              {multi && <>{title} · </>}код «{h.dataset_code}», {h.fields} {plural(h.fields, 'графа', 'графы', 'граф')}
              {h.period && `, выпуск за ${ruDate(h.period)}`}
              <div style={{ color: 'var(--text-muted)', fontSize: 12.5 }}>
                заменён {ruDate(h.replaced_at)}{h.replaced_by && ` (${h.replaced_by})`}
                {h.reason && ` — ${h.reason}`}
              </div>
            </div>
            <button style={btnGhost} disabled={busy}
              onClick={() => restore(h.id, ruDate(h.replaced_at), title)}>
              Вернуть
            </button>
          </div>
        )
      })}
    </div>
  )
}

const frame: React.CSSProperties = {
  border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px',
  marginBottom: 14, background: 'var(--surface-2)', fontSize: 14,
}
const row: React.CSSProperties = {
  display: 'flex', gap: 12, alignItems: 'center', padding: '8px 0',
  borderTop: '1px solid var(--border)', fontSize: 13.5,
}
const btnGhost: React.CSSProperties = {
  height: 32, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 8,
  background: 'var(--surface)', color: 'var(--text)', fontSize: 13, cursor: 'pointer',
}
