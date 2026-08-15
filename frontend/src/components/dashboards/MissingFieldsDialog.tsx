import { useState } from 'react'
import { createPortal } from 'react-dom'
import { btnGhost, dialog, overlay, rmBtn } from './shared'

export type MissingField = { code: string; name: string; dataset_code: string }

/**
 * Добавить на дашборд показатели, которых на нём нет.
 *
 * Подсказка «в данных есть показатели, которых нет на дашборде» сама по себе
 * была тупиком: она сообщала о недостаче, а сделать с ней что-то можно было
 * только вручную — открыть конструктор и завести карточки по одной.
 *
 * Галочки, а не «добавить всё»: показателей бывает десяток, и десяток
 * карточек разом превращает страницу в стену чисел. Поэтому по умолчанию НЕ
 * отмечено ничего — человек выбирает осознанно.
 */
export function MissingFieldsDialog(
  { fields, busy, onClose, onAdd }: {
    fields: MissingField[]
    busy?: boolean
    onClose: () => void
    onAdd: (picked: MissingField[]) => void
  },
) {
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const toggle = (code: string) => setPicked((s) => {
    const next = new Set(s)
    if (next.has(code)) next.delete(code); else next.add(code)
    return next
  })
  const chosen = fields.filter((f) => picked.has(f.code))

  return createPortal((
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 620, maxHeight: '82vh', display: 'flex', flexDirection: 'column' }}
        onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Добавить показатели на дашборд</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose} title="Закрыть">✕</button>
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginBottom: 10 }}>
          Эти показатели есть в выпущенных данных, но ни один виджет их не показывает.
          Отмеченные добавятся карточками на текущую страницу — вид и размер потом можно
          изменить как у любого виджета.
        </div>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 6 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Выбрано: {chosen.length} из {fields.length}</span>
          <button style={linkBtn} onClick={() => setPicked(new Set(fields.map((f) => f.code)))}>все</button>
          <button style={linkBtn} onClick={() => setPicked(new Set())}>снять</button>
        </div>

        <div style={{
          flex: 1, minHeight: 0, overflowY: 'auto', border: '1px solid var(--border)',
          borderRadius: 10, padding: 10, display: 'flex', flexDirection: 'column', gap: 8,
        }}>
          {fields.map((f) => (
            <label key={f.code} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, cursor: 'pointer' }}>
              <input type="checkbox" checked={picked.has(f.code)} onChange={() => toggle(f.code)}
                style={{ marginTop: 3 }} />
              <span style={{ overflowWrap: 'anywhere' }}>{f.name}</span>
            </label>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
          <button style={btnGhost} onClick={onClose}>Отмена</button>
          <button
            disabled={busy || !chosen.length}
            onClick={() => onAdd(chosen)}
            style={{
              height: 36, padding: '0 14px', border: 'none', borderRadius: 8,
              background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14,
              cursor: chosen.length ? 'pointer' : 'default', opacity: busy || !chosen.length ? 0.6 : 1,
            }}
          >{busy ? 'Добавляем…' : `Добавить ${chosen.length || ''}`.trim()}</button>
        </div>
      </div>
    </div>
  ), document.body)
}

const linkBtn: React.CSSProperties = {
  border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: 0,
}
