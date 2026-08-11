import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { btnGhost, dialog, overlay, rmBtn } from './shared'

/**
 * Подтверждение необратимого действия — вместо системного `confirm()`.
 *
 * Причина та же, что у [RenameDialog]: браузер вправе подавить системный
 * диалог (в частности, после того как пользователь отметил «не показывать
 * больше диалоги на этой странице»), и тогда `confirm()` молча возвращает
 * false — кнопка выглядит сломанной. Для удаления это опаснее всего: человек
 * жмёт ещё раз, решив, что не сработало.
 *
 * Портал в body — чтобы окно не обрезалось карточкой или сеткой дашборда.
 */
export function ConfirmDialog(
  { title, message, confirmLabel = 'Удалить', busy, onClose, onConfirm }: {
    title: string
    message: React.ReactNode
    confirmLabel?: string
    busy?: boolean
    onClose: () => void
    onConfirm: () => void
  },
) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal((
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 480 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{title}</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose} title="Закрыть">✕</button>
        </div>
        <div style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.5, whiteSpace: 'pre-line' }}>{message}</div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 18 }}>
          <button style={btnGhost} onClick={onClose}>Отмена</button>
          <button
            autoFocus={false} disabled={busy} onClick={onConfirm}
            style={{
              height: 36, padding: '0 14px', border: '1px solid var(--danger)', borderRadius: 8,
              background: 'var(--danger)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer',
              opacity: busy ? 0.6 : 1,
            }}
          >{busy ? 'Удаление…' : confirmLabel}</button>
        </div>
      </div>
    </div>
  ), document.body)
}
