import { useState } from 'react'
import { createPortal } from 'react-dom'
import { btn, btnGhost, dialog, input, overlay, rmBtn } from './shared'

/**
 * Ввод одной строки — вместо системного `prompt()`.
 *
 * Браузеры блокируют `prompt()` (в том числе после того, как пользователь
 * отметил «не показывать больше диалоги»), и нажатие на кнопку выглядело как
 * «ничего не происходит». Свой диалог ведёт себя предсказуемо и выглядит как
 * остальные окна системы. Портал в body — чтобы окно не оказалось внутри
 * трансформированной сетки дашборда и не обрезалось.
 */
export function RenameDialog(
  { title, label, initial, placeholder, onClose, onSave }: {
    title: string
    label: string
    initial: string
    placeholder?: string
    onClose: () => void
    onSave: (value: string) => void
  },
) {
  const [value, setValue] = useState(initial)
  const ok = value.trim().length > 0
  return createPortal((
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 460 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{title}</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: 'var(--text-muted)' }}>
          {label}
          <input
            autoFocus style={{ ...input, width: '100%' }} value={value} placeholder={placeholder}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && ok) onSave(value.trim())
              if (e.key === 'Escape') onClose()
            }}
          />
        </label>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
          <button style={btnGhost} onClick={onClose}>Отмена</button>
          <button style={btn} disabled={!ok} onClick={() => onSave(value.trim())}>Сохранить</button>
        </div>
      </div>
    </div>
  ), document.body)
}
