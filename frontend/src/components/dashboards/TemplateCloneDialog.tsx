import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { templateBinding, type TemplateBinding } from '../../api/dashboards'
import type { Obj } from '../../api'
import { btnGhost, dialog, overlay, rmBtn } from './shared'

/**
 * Тиражирование дашборда на другой объект.
 *
 * Когда появляются районы или вторая форма, дашборд должен переноситься, а не
 * собираться заново для каждого. Мешает одно: у другого объекта СВОИ коды
 * показателей — они выводятся из заголовков его формы, — и перенесённый как
 * есть виджет показал бы «нет данных» на каждой карточке.
 *
 * Сопоставление идёт по ИМЕНАМ показателей (имя — единственное, что устойчиво
 * повторяется в одинаковых формах разных подразделений), а то, что не нашлось,
 * показывается списком ДО создания: неверно сопоставленный показатель опаснее
 * отсутствующего, потому что выглядит рабочим.
 */
export function TemplateCloneDialog(
  { templateId, templateName, objects, busy, onClose, onCreate }: {
    templateId: string
    templateName: string
    objects: Obj[]
    busy?: boolean
    onClose: () => void
    onCreate: (opts: { name: string; datasetMap: Record<string, string>; fieldMap: Record<string, string> }) => void
  },
) {
  const [objectId, setObjectId] = useState('')
  const [name, setName] = useState('')
  const [binding, setBinding] = useState<TemplateBinding | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!objectId) { setBinding(null); setErr(null); return }
    setLoading(true); setErr(null)
    templateBinding(templateId, objectId)
      .then((b) => {
        setBinding(b)
        const obj = objects.find((o) => o.id === objectId)
        if (obj && !name.trim()) setName(`${templateName} — ${obj.name}`)
      })
      .catch((e) => { setBinding(null); setErr((e as Error).message) })
      .finally(() => setLoading(false))
  }, [objectId]) // eslint-disable-line react-hooks/exhaustive-deps

  const ready = Boolean(binding && name.trim())

  return createPortal((
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 620, maxHeight: '84vh', display: 'flex', flexDirection: 'column' }}
        onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Тиражировать «{templateName}»</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose} title="Закрыть">✕</button>
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginBottom: 12 }}>
          Копия дашборда будет привязана к данным выбранного объекта. Показатели сопоставляются
          по названиям — коды у каждого объекта свои.
        </div>

        <label style={lbl}>
          Объект
          <select style={inp} value={objectId} onChange={(e) => setObjectId(e.target.value)}>
            <option value="">выберите объект…</option>
            {objects.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        </label>

        <label style={lbl}>
          Название нового дашборда
          <input style={inp} value={name} onChange={(e) => setName(e.target.value)}
            placeholder="Например: Внедрение МАХ — Мариуполь" />
        </label>

        {err && <div style={{ ...box, borderColor: 'var(--danger)', color: 'var(--danger)' }}>{err}</div>}
        {loading && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Сопоставляем показатели…</div>}

        {binding && (
          <div style={{ overflowY: 'auto', minHeight: 0 }}>
            <div style={{ ...box, borderColor: 'var(--success)', color: 'var(--success)' }}>
              ✓ Сопоставлено показателей: {binding.matched.length}. Данные будут браться из набора
              «{binding.target.dataset_name}».
            </div>
            {binding.missing.length > 0 && (
              <div style={{ ...box, borderColor: 'var(--warn)', color: 'var(--warn)' }}>
                ⚠ Не нашлось у этого объекта ({binding.missing.length}):{' '}
                {binding.missing.map((m) => `«${m.from_name}»`).join(', ')}.
                <div style={{ marginTop: 4, fontSize: 12 }}>
                  Виджеты по ним будут созданы, но покажут ошибку, пока показатель не появится
                  в данных объекта. Их можно удалить с дашборда после создания.
                </div>
              </div>
            )}
            {binding.metrics.length > 0 && (
              <div style={{ ...box, color: 'var(--text-2)' }}>
                В шаблоне есть виджеты по метрикам ({binding.metrics.join(', ')}). Метрики считаются
                по своим формулам и не привязаны к объекту — они останутся прежними.
              </div>
            )}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
          <button style={btnGhost} onClick={onClose}>Отмена</button>
          <button
            disabled={!ready || busy}
            onClick={() => binding && onCreate({
              name: name.trim(), datasetMap: binding.dataset_map, fieldMap: binding.field_map,
            })}
            style={{
              height: 36, padding: '0 14px', border: 'none', borderRadius: 8,
              background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14,
              cursor: ready ? 'pointer' : 'default', opacity: !ready || busy ? 0.6 : 1,
            }}
          >{busy ? 'Создаём…' : 'Создать копию'}</button>
        </div>
      </div>
    </div>
  ), document.body)
}

const lbl: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12.5,
  color: 'var(--text-muted)', marginBottom: 10,
}
const inp: React.CSSProperties = {
  height: 36, padding: '0 10px', border: '1px solid var(--border-strong)',
  borderRadius: 8, fontSize: 14, color: 'var(--text)',
}
const box: React.CSSProperties = {
  border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px',
  fontSize: 12.5, marginBottom: 8,
}
