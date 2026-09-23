import { useEffect, useState } from 'react'
import { getLayoutTemplates, restoreLayoutTemplate, type TemplateHistory } from '../../api/objects'
import { plural } from '../../lib/text'
import { useConfirm } from '../dashboards/ConfirmDialog'

// Шаблон разметки объекта и его прежние версии.
//
// Шаблон один на объект, и до 23.09.2026 выпуск переписывал его молча: 22.09 на
// боевом ошибочный выпуск перечня услуг затёр разметку формы МАХ, и вернуть
// исключённые строки бланка было неоткуда. Теперь прежний шаблон уходит в
// историю, а блок показывает, когда и кем он заменён, и возвращает его кнопкой.
// Пока истории нет, блок молчит: строка «шаблон есть» без действий — шум.
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
  if (!st || !st.history.length) return null

  const restore = async (id: string, when: string) => {
    const ok = await ask({
      title: 'Вернуть прежний шаблон разметки?',
      message: `Следующие файлы этой формы будут размечаться так, как до ${when}. `
        + 'Действующий шаблон не пропадёт — он уйдёт в историю, и его можно будет вернуть так же.',
      confirmLabel: 'Вернуть', tone: 'accent',
    })
    if (!ok) return
    setBusy(true)
    try { setSt(await restoreLayoutTemplate(objectId, id)) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  const c = st.current
  return (
    <div style={frame}>
      {node}
      <b>🧩 Шаблон разметки</b>
      {c && (
        <div style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 4 }}>
          Действует с {ruDate(c.updated_at)}: код «{c.dataset_code}», {c.fields} {plural(c.fields, 'графа', 'графы', 'граф')}
          {c.period && `, по выпуску за ${ruDate(c.period)}`}.
        </div>
      )}
      <div style={{ fontSize: 13, marginTop: 10, color: 'var(--text-2)' }}>Прежние шаблоны:</div>
      {st.history.map((h) => (
        <div key={h.id} style={row}>
          <div style={{ flex: 1, minWidth: 0 }}>
            код «{h.dataset_code}», {h.fields} {plural(h.fields, 'графа', 'графы', 'граф')}
            {h.period && `, выпуск за ${ruDate(h.period)}`}
            <div style={{ color: 'var(--text-muted)', fontSize: 12.5 }}>
              заменён {ruDate(h.replaced_at)}{h.replaced_by && ` (${h.replaced_by})`}
              {h.reason && ` — ${h.reason}`}
            </div>
          </div>
          <button style={btnGhost} disabled={busy} onClick={() => restore(h.id, ruDate(h.replaced_at))}>
            Вернуть
          </button>
        </div>
      ))}
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
