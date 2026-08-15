import { useCallback, useEffect, useState } from 'react'
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
  { title, message, confirmLabel = 'Удалить', busyLabel = 'Удаление…', tone = 'danger',
    busy, onClose, onConfirm, extraAction }: {
    title: string
    message: React.ReactNode
    confirmLabel?: string
    /** Подпись кнопки во время выполнения. У неразрушительных действий
     *  («Вернуть из архива», «Откатить») «Удаление…» читалось бы как угроза. */
    busyLabel?: string
    /** danger — необратимое (красная кнопка), accent — обычное подтверждение. */
    tone?: 'danger' | 'accent'
    busy?: boolean
    onClose: () => void
    onConfirm: () => void
    /** Второй, более разрушительный вариант — например «удалить вместе с данными».
     *  Стоит слева от основного и подписан словами, а не галочкой: галочку
     *  проскакивают не читая, а отдельную кнопку приходится выбрать осознанно. */
    extraAction?: { label: string; onClick: () => void }
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
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 18, flexWrap: 'wrap' }}>
          <button style={btnGhost} onClick={onClose}>Отмена</button>
          {extraAction && (
            <button
              disabled={busy} onClick={extraAction.onClick}
              style={{
                height: 36, padding: '0 14px', border: '1px solid var(--danger)', borderRadius: 8,
                background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 14,
                cursor: 'pointer', opacity: busy ? 0.6 : 1,
              }}
            >{extraAction.label}</button>
          )}
          <button
            autoFocus={false} disabled={busy} onClick={onConfirm}
            style={{
              height: 36, padding: '0 14px',
              border: `1px solid var(--${tone})`, borderRadius: 8,
              background: `var(--${tone})`, color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer',
              opacity: busy ? 0.6 : 1,
            }}
          >{busy ? busyLabel : confirmLabel}</button>
        </div>
      </div>
    </div>
  ), document.body)
}

type ConfirmOpts = {
  title: string
  message: React.ReactNode
  confirmLabel?: string
  busyLabel?: string
  tone?: 'danger' | 'accent'
}

/**
 * Подтверждение как вызов функции: `if (!await ask({...})) return`.
 *
 * Заменяет системный `confirm()` без переписывания логики страницы: тот тоже
 * возвращал «да/нет» одним выражением. Системный диалог браузер вправе
 * подавить — тогда он молча отвечает «нет», и кнопка выглядит сломанной; на
 * удалении файла это уже стоило заказчику разбирательства.
 *
 * Компонент окна рендерится один раз: `const { ask, node } = useConfirm()` и
 * `{node}` в разметке.
 */
export function useConfirm() {
  const [state, setState] = useState<{ opts: ConfirmOpts; resolve: (v: boolean) => void } | null>(null)

  const ask = useCallback(
    (opts: ConfirmOpts) => new Promise<boolean>((resolve) => setState({ opts, resolve })),
    [],
  )

  const finish = (answer: boolean) => {
    state?.resolve(answer)
    setState(null)
  }

  const node = state
    ? <ConfirmDialog {...state.opts} onClose={() => finish(false)} onConfirm={() => finish(true)} />
    : null

  return { ask, node }
}
