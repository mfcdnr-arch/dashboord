/**
 * Подпись поля — одна на всё приложение.
 *
 * Раньше этот компонент существовал ВОСЕМЬЮ копиями под пятью именами
 * (`F` ×2, `L` ×2, `Lbl`, `Field` ×2, `Row`) — по своей на файл. Копии
 * расходились молча: одна давала `fontSize: 11`, другая `12`, третья рисовала
 * жирную подпись блоком. Хуже того, поиск по `htmlFor`/`aria-label` их не
 * видел, из-за чего аудит насчитал «0 из 318 полей с подписью», хотя 115 из
 * них были подписаны как раз такой обёрткой.
 *
 * Подпись оборачивает поле, а не ссылается на него через `htmlFor`: так у
 * подписи и поля общая зона нажатия и нет риска, что id разойдётся с целью.
 */
import type React from 'react'
import InfoTip from './InfoTip'

/** Размер подписи. `sm` — плотные формы виджетов, `md` — обычные формы. */
export type FieldSize = 'sm' | 'md'

const SIZE: Record<FieldSize, { fontSize: number; gap: number }> = {
  sm: { fontSize: 11, gap: 2 },
  md: { fontSize: 12, gap: 3 },
}

export default function Field({
  label, hint, required, size = 'md', strong, style, labelStyle, children,
}: {
  label: React.ReactNode
  /** Пояснение в значке ⓘ рядом с подписью. */
  hint?: string
  /** Пометка «обязательное» — звёздочка после подписи. */
  required?: boolean
  size?: FieldSize
  /** Жирная подпись обычным текстом — для страниц настроек, где подпись
   *  читается как заголовок поля, а не как мелкая пометка над ним. */
  strong?: boolean
  style?: React.CSSProperties
  labelStyle?: React.CSSProperties
  children: React.ReactNode
}) {
  const s = SIZE[size]
  const head = strong
    ? { fontSize: 13, fontWeight: 600, marginBottom: 4, color: 'var(--text)' }
    : { fontSize: s.fontSize, color: 'var(--text-muted)' }
  return (
    // minWidth: 0 — без него flex-элемент не может стать уже содержимого, и
    // длинный список внутри подписи выталкивает соседей за край страницы.
    <label style={{ display: 'flex', flexDirection: 'column', gap: strong ? 0 : s.gap, minWidth: 0, maxWidth: '100%', ...style }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, ...head, ...labelStyle }}>
        {label}
        {required && <span style={{ color: 'var(--danger)' }}>*</span>}
        {hint && <InfoTip text={hint} />}
      </span>
      {children}
    </label>
  )
}
