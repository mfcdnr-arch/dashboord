import { useState } from 'react'
import type { MissingField } from '../../api'
import { ruDate } from '../../lib/notifications'
import { plural } from '../../lib/text'
import { btnGhost, rmBtn } from './shared'
import { Modal, ModalTitle } from '../Modal'
import Notice from '../Notice'

export type { MissingField }

/** Графа идентифицируется парой «форма + код»: у двух форм коды могут совпасть. */
const keyOf = (f: { dataset_code: string; code: string }) => `${f.dataset_code}\u0000${f.code}`

/**
 * «В форме появились новые графы — добавить виджет?» (этап 5).
 *
 * Список — графы, появившиеся в формах с тех пор, как дашборд собран, и не
 * показанные ни одним виджетом. До 01.10.2026 здесь были ВСЕ графы, которых не
 * называет ни один виджет, — на дашборде РЦО 359, и окно превращало вопрос
 * «добавить виджет?» в поиск иголки.
 *
 * Галочки, а не «добавить всё»: десяток карточек разом превращает страницу в
 * стену чисел. По умолчанию не отмечено ничего — кроме граф, ради которых
 * человек пришёл сюда из уведомления: их он уже выбрал, нажав на него.
 *
 * «Больше не предлагать» — второй честный исход: подсказка, которую нельзя
 * закрыть иначе, чем добавив виджет, висит вечно и учит себя не читать.
 */
export function MissingFieldsDialog(
  { fields, busy, highlight, error, onClose, onAdd, onDismiss }: {
    fields: MissingField[]
    busy?: boolean
    /** Ошибка добавления или отметки — внутри окна: страница за ним не видна. */
    error?: string | null
    /** Коды граф из уведомления: отметить и поставить первыми. */
    highlight?: string[]
    onClose: () => void
    onAdd: (picked: MissingField[]) => void
    onDismiss?: (shown: MissingField[]) => void
  },
) {
  const hl = new Set(highlight || [])
  const ordered = hl.size
    ? [...fields.filter((f) => hl.has(f.code)), ...fields.filter((f) => !hl.has(f.code))]
    : fields
  const [picked, setPicked] = useState<Set<string>>(
    () => new Set(fields.filter((f) => hl.has(f.code)).map(keyOf)))
  const toggle = (k: string) => setPicked((s) => {
    const next = new Set(s)
    if (next.has(k)) next.delete(k); else next.add(k)
    return next
  })
  const chosen = ordered.filter((f) => picked.has(keyOf(f)))

  return (
    <Modal
      onClose={onClose}
      width={620}
      style={{ maxHeight: '82vh', display: 'flex', flexDirection: 'column' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
        <ModalTitle>Новые графы формы</ModalTitle>
        <button type="button" style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose}
          aria-label="Закрыть" title="Закрыть">✕</button>
      </div>

      {fields.length === 0 ? (
        // Пустое окно «Выбрано: 0 из 0» выглядело бы поломкой: человек пришёл
        // по уведомлению, а графы тем временем уже добавили или отклонили.
        <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '6px 0 4px' }}>
          Новых граф, которых нет на дашборде, сейчас нет: их уже добавили или отметили
          «больше не предлагать».
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
            <button type="button" style={btnGhost} onClick={onClose}>Закрыть</button>
          </div>
        </div>
      ) : (
        <>
          <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginBottom: 10 }}>
            Эти графы появились в форме после того, как дашборд собрали, и ни один виджет их
            не называет. Отмеченные добавятся карточками на текущую страницу — вид и размер
            потом можно изменить как у любого виджета.
          </div>

          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 6 }}>
            <span style={{ fontSize: 12.5, fontWeight: 600 }}>Выбрано: {chosen.length} из {fields.length}</span>
            <button type="button" style={linkBtn} onClick={() => setPicked(new Set(fields.map(keyOf)))}>все</button>
            <button type="button" style={linkBtn} onClick={() => setPicked(new Set())}>снять</button>
          </div>

          <div style={{
            flex: 1, minHeight: 0, overflowY: 'auto', border: '1px solid var(--border)',
            borderRadius: 10, padding: 10, display: 'flex', flexDirection: 'column', gap: 8,
          }}>
            {ordered.map((f) => {
              const k = keyOf(f)
              const covered = f.covered_by || []
              return (
                <label key={k} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, cursor: 'pointer' }}>
                  <input type="checkbox" checked={picked.has(k)} onChange={() => toggle(k)}
                    style={{ marginTop: 3 }} />
                  <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
                    {hl.has(f.code) && <span style={newMark}>из уведомления</span>}
                    {f.name}
                    {(f.first_period || covered.length > 0) && (
                      <span style={{ display: 'block', fontSize: 11.5, color: 'var(--text-muted)', marginTop: 1 }}>
                        {f.first_period ? `впервые в отчёте за ${ruDate(f.first_period)}` : ''}
                        {f.first_period && covered.length ? ' · ' : ''}
                        {/* Таблица всей формы показывает графу числом в одной из
                            сотен колонок — это не причина прятать её, но знать надо. */}
                        {covered.length > 0 && `уже видна в ${covered.slice(0, 2).map((c) => `«${c}»`).join(', ')}`
                          + `${covered.length > 2 ? ` и ещё ${covered.length - 2}` : ''}`}
                      </span>
                    )}
                  </span>
                </label>
              )
            })}
          </div>

          {error && <Notice style={{ marginTop: 10, marginBottom: 0 }}>{error}</Notice>}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 14, flexWrap: 'wrap' }}>
            {onDismiss && (
              <button type="button" style={{ ...btnGhost, marginRight: 'auto' }} disabled={busy}
                onClick={() => onDismiss(fields)}
                title="Все графы этого списка больше не будут предлагаться этому дашборду">
                Больше не предлагать {fields.length} {plural(fields.length, 'графу', 'графы', 'граф')}
              </button>
            )}
            <button type="button" style={btnGhost} onClick={onClose}>Отмена</button>
            <button
              type="button"
              disabled={busy || !chosen.length}
              onClick={() => onAdd(chosen)}
              style={{
                height: 36, padding: '0 14px', border: 'none', borderRadius: 8,
                background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14,
                cursor: chosen.length ? 'pointer' : 'default', opacity: busy || !chosen.length ? 0.6 : 1,
              }}
            >{busy ? 'Добавляем…' : `Добавить ${chosen.length || ''}`.trim()}</button>
          </div>
        </>
      )}
    </Modal>
  )
}

const linkBtn: React.CSSProperties = {
  border: 'none', background: 'none', color: 'var(--accent-text)', cursor: 'pointer', fontSize: 12, padding: 0,
}
const newMark: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: 'var(--accent-text)', background: 'var(--accent-weak-bg)',
  borderRadius: 6, padding: '1px 6px', marginRight: 6,
}
