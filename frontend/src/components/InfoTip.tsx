import { useState } from 'react'

// Небольшой ℹ️-тултип: при наведении/фокусе показывает поясняющий текст.
// Используется на виджетах (что показывает виджет) и рядом с элементами интерфейса.
export default function InfoTip({ text, label = 'Подсказка' }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  return (
    <span style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" aria-label={label} title=""
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v) }}
        style={{ width: 16, height: 16, borderRadius: '50%', border: '1px solid var(--border-strong)', background: 'var(--accent-weak-bg)',
          color: 'var(--accent)', fontSize: 11, lineHeight: '14px', cursor: 'help', padding: 0, fontWeight: 700 }}>i</button>
      {open && (
        <span role="tooltip" style={{
          position: 'absolute', top: '130%', left: '50%', transform: 'translateX(-50%)', zIndex: 70,
          width: 220, background: 'var(--text)', color: 'var(--on-accent)', fontSize: 12, lineHeight: 1.4, fontWeight: 400,
          padding: '8px 10px', borderRadius: 8, boxShadow: '0 6px 20px rgba(0,0,0,0.25)', whiteSpace: 'normal',
        }}>{text}</span>
      )}
    </span>
  )
}
