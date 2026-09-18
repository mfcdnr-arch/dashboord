import { useEffect, useMemo, useState } from 'react'
import { DAYS, createOffice, updateOffice, type DayKey, type Hours, type Office, type OfficeInput } from '../../api'

import MapView from './MapView'
import { Modal, ModalTitle } from '../Modal'
import Notice from '../Notice'
import Field from '../Field'
// Карточка отделения: то, что человек видит на точке карты, и то, что
// администратор правит, когда график или телефон изменились.
//
// Окно выводится ПОРТАЛОМ в body — внутри страницы его обрезал бы контейнер со
// своей прокруткой (этот дефект в проекте уже ловили у подсказок и drill-окна).

export default function OfficeForm({ office, rowOptions, allOffices, onClose, onSaved }: {
  office: Office | null
  rowOptions: string[]
  // Соседние отделения показываются на мини-карте как ориентир: «наше рядом с
  // тем, что уже стоит» — единственная привязка, когда точного адреса нет.
  allOffices?: Office[]
  onClose: () => void
  onSaved: (o: Office) => void
}) {
  const [f, setF] = useState<OfficeInput>(() => office ? {
    name: office.name, address: office.address, city: office.city, phone: office.phone,
    phone2: office.phone2, email: office.email, website: office.website, hours: office.hours || {},
    note: office.note, lat: office.lat, lon: office.lon, row_label: office.row_label,
    is_active: office.is_active,
  } : { name: '', hours: {}, is_active: true })
  // Пара координат показывается СВОИМИ цифрами, а не примером: пример в пустом
  // поле читается как значение этого отделения (проверено глазами на кадре —
  // у Амвросиевки «светились» координаты Донецка).
  const [pair, setPair] = useState(() => (office && office.lat != null ? `${office.lat},${office.lon}` : ''))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Карта разворачивается по кнопке, а не всегда: она тянет геометрию
  // республики (районы и населённые пункты), и платить за это при каждой
  // правке телефона незачем.
  const [showMap, setShowMap] = useState(false)

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const set = (k: keyof OfficeInput, v: unknown) => setF((s) => ({ ...s, [k]: v }))
  const hours: Hours = f.hours || {}
  const setDay = (d: DayKey, v: { from: string; to: string } | null) =>
    setF((s) => ({ ...s, hours: { ...(s.hours || {}), [d]: v } }))

  // Пара координат строкой — так они приходят в шаблоне («48.009964,37.808141»),
  // и переписывать их в два поля руками незачем.
  function applyPair(raw: string) {
    setPair(raw)
    const m = raw.trim().match(/^(-?\d+[.,]?\d*)\s*[,;\s]\s*(-?\d+[.,]?\d*)$/)
    if (!m) return
    setF((s) => ({ ...s, lat: Number(m[1].replace(',', '.')), lon: Number(m[2].replace(',', '.')) }))
  }

  const insideHint = useMemo(() => {
    if (f.lat == null || f.lon == null) return null
    // Грубая проверка «похоже на республику» до сохранения; точный ответ даёт
    // сервер по контуру и показывается в списке.
    const ok = f.lat > 46.5 && f.lat < 49.5 && f.lon > 36 && f.lon < 39.5
    return ok ? null : 'Точка выглядит далеко от республики — проверьте, не перепутаны ли широта и долгота'
  }, [f.lat, f.lon])

  async function save() {
    if (!(f.name || '').trim()) { setError('Укажите название отделения'); return }
    setBusy(true); setError(null)
    try {
      const saved = office ? await updateOffice(office.id, f) : await createOffice(f)
      onSaved(saved)
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <Modal
      onClose={onClose}
      style={{ width: 'min(620px, 100%)', maxHeight: '90vh', padding: 0, borderRadius: 12, display: 'flex', flexDirection: 'column' }}
    >
      <div style={head}>
        <ModalTitle style={{ fontSize: 15 }}>{office ? 'Сведения об отделении' : 'Новое отделение'}</ModalTitle>
        <button style={xBtn} onClick={onClose} title="Закрыть">✕</button>
      </div>
      <div style={body}>
        {error && <Notice style={errBox}>{error}</Notice>}

        <Field style={{ marginBottom: 8 }} label="Название" required>
          <input style={inp} value={f.name || ''} onChange={(e) => set('name', e.target.value)}
            placeholder="например: МФЦ №1 по городу Донецк" />
        </Field>
        <Field style={{ marginBottom: 8 }} label="Адрес">
          <input style={inp} value={f.address || ''} onChange={(e) => set('address', e.target.value)}
            placeholder="например: г. Донецк, ул. Челюскинцев, 167" />
        </Field>
        <Field style={{ marginBottom: 8 }} label="Населённый пункт" hint="Заполняется из адреса; правится, если прочитано неверно">
          <input style={inp} value={f.city || ''} onChange={(e) => set('city', e.target.value)} placeholder="например: Донецк" />
        </Field>
        <Field style={{ marginBottom: 8 }} label="Телефон">
          <div style={{ display: 'flex', gap: 8 }}>
            <input style={{ ...inp, flex: 1 }} value={f.phone || ''} onChange={(e) => set('phone', e.target.value)} placeholder="например: 119" />
            <input style={{ ...inp, flex: 1 }} value={f.phone2 || ''} onChange={(e) => set('phone2', e.target.value)} placeholder="доп. телефон" />
          </div>
        </Field>
        <Field style={{ marginBottom: 8 }} label="Почта и сайт">
          <div style={{ display: 'flex', gap: 8 }}>
            <input style={{ ...inp, flex: 1 }} value={f.email || ''} onChange={(e) => set('email', e.target.value)} placeholder="например: mfc@example.ru" />
            <input style={{ ...inp, flex: 1 }} value={f.website || ''} onChange={(e) => set('website', e.target.value)} placeholder="https://…" />
          </div>
        </Field>

        <div style={{ ...blockTitle, marginTop: 14 }}>Режим работы</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 10 }}>
          {DAYS.map((d) => {
            const v = hours[d.key] || null
            return (
              <div key={d.key} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, width: 150, cursor: 'pointer' }}>
                  <input type="checkbox" checked={!!v}
                    onChange={(e) => setDay(d.key, e.target.checked ? { from: '08:00', to: '17:00' } : null)} />
                  {d.full}
                </label>
                {v ? (
                  <>
                    <input style={{ ...inp, width: 90 }} value={v.from} aria-label={`${d.full}: с`}
                      onChange={(e) => setDay(d.key, { ...v, from: e.target.value })} placeholder="08:00" />
                    <span style={{ color: 'var(--text-muted)' }}>–</span>
                    <input style={{ ...inp, width: 90 }} value={v.to} aria-label={`${d.full}: по`}
                      onChange={(e) => setDay(d.key, { ...v, to: e.target.value })} placeholder="17:00" />
                  </>
                ) : <span style={{ color: 'var(--text-faint)' }}>выходной</span>}
              </div>
            )
          })}
        </div>
        <Field style={{ marginBottom: 8 }} label="Примечание" hint="Обед, особые дни — всё, что не укладывается в часы по дням">
          <input style={inp} value={f.note || ''} onChange={(e) => set('note', e.target.value)} placeholder="например: обед 13:00–14:00" />
        </Field>

        <div style={{ ...blockTitle, marginTop: 14 }}>Место на карте</div>
        <Field style={{ marginBottom: 8 }} label="Координаты" hint="Пара из шаблона целиком — широта, долгота">
          <input style={inp} value={pair} onChange={(e) => applyPair(e.target.value)} placeholder="например: 48.009964,37.808141" />
        </Field>
        <Field style={{ marginBottom: 8 }} label="Широта и долгота">
          <div style={{ display: 'flex', gap: 8 }}>
            <input style={{ ...inp, flex: 1 }} value={f.lat ?? ''} aria-label="Широта"
              onChange={(e) => set('lat', e.target.value === '' ? null : Number(e.target.value))} placeholder="широта" />
            <input style={{ ...inp, flex: 1 }} value={f.lon ?? ''} aria-label="Долгота"
              onChange={(e) => set('lon', e.target.value === '' ? null : Number(e.target.value))} placeholder="долгота" />
          </div>
        </Field>
        <button style={{ ...btnGhost, marginBottom: 8 }} onClick={() => setShowMap((v) => !v)}
          aria-expanded={showMap}
          title="Показать карту и поставить точку нажатием — координаты подставятся сами">
          {showMap ? '📍 Скрыть карту' : '📍 Указать на карте'}
        </button>
        {showMap && (
          <div style={{ marginBottom: 8 }}>
            <MapView
              offices={allOffices || []}
              height="320px"
              pick={{
                lat: f.lat ?? null,
                lon: f.lon ?? null,
                onPick: (lat, lon) => { setF((st) => ({ ...st, lat, lon })); setPair(`${lat},${lon}`) },
              }} />
          </div>
        )}
        {insideHint && <div style={warnBox}>⚠ {insideHint}</div>}
        {f.lat == null && (
          <div style={hintBox}>
            Без координат отделение останется в справочнике, но не появится на карте.
          </div>
        )}

        <div style={{ ...blockTitle, marginTop: 14 }}>Связь с отчётом</div>
        <Field style={{ marginBottom: 8 }} label="Строка отчёта" hint="Нужна, чтобы на точке показывалась нагрузка. В отчёте адрес записан иначе, чем в справочнике">
          <select style={inp} value={f.row_label || ''} onChange={(e) => set('row_label', e.target.value || null)}>
            <option value="">— не связано —</option>
            {f.row_label && !rowOptions.includes(f.row_label) && <option value={f.row_label}>{f.row_label}</option>}
            {rowOptions.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </Field>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, marginTop: 12, cursor: 'pointer' }}>
          <input type="checkbox" checked={f.is_active !== false} onChange={(e) => set('is_active', e.target.checked)} />
          Отделение действует
          <span style={{ color: 'var(--text-faint)' }}>— снятая отметка убирает точку с карты, история цифр остаётся</span>
        </label>
      </div>
      <div style={foot}>
        <button style={btnGhost} onClick={onClose}>Отмена</button>
        <button style={btn} onClick={save} disabled={busy}>{busy ? 'Сохранение…' : 'Сохранить'}</button>
      </div>
    </Modal>
  )
}


const head: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid var(--border-faint)' }
const body: React.CSSProperties = { padding: 16, overflowY: 'auto' }
const foot: React.CSSProperties = { display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '12px 16px', borderTop: '1px solid var(--border-faint)' }
const inp: React.CSSProperties = { height: 34, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13, width: '100%', boxSizing: 'border-box', background: 'var(--surface)', color: 'var(--text)' }
const btn: React.CSSProperties = { height: 34, padding: '0 16px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { ...btn, background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border-strong)', cursor: 'pointer' }
const xBtn: React.CSSProperties = { border: 'none', background: 'none', fontSize: 16, cursor: 'pointer', color: 'var(--text-muted)' }
const blockTitle: React.CSSProperties = { fontSize: 13, fontWeight: 700, marginBottom: 8 }
const errBox: React.CSSProperties = { marginBottom: 10 }
const warnBox: React.CSSProperties = { background: 'var(--warn-bg, var(--surface-2))', color: 'var(--text)', fontSize: 12, padding: '6px 10px', borderRadius: 8, marginBottom: 8 }
const hintBox: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 12, marginBottom: 8 }
