import { useEffect, useState, type FormEvent } from 'react'
import {
  createRefDoc, createService, deleteRefDoc, deleteService, listRefDocs, listServices, updateService,
  type RefDoc, type Service,
} from '../api'
import { useConfirm } from './dashboards/ConfirmDialog'

// Раздел «Справочники» (admin/moderator): перечень услуг + служебные документы,
// которыми пользуется модератор при проверке дашбордов (FR-8.16 / FR-8.17).
// Правка — только admin; модератор видит для сверки.

export default function CatalogPage({ me }: { me: { roles: string[] } }) {
  // Подтверждения — своим окном: системное браузер вправе подавить, и кнопка
  // необратимого действия выглядит нерабочей (см. ConfirmDialog).
  const { ask, node: confirmNode } = useConfirm()
  const [services, setServices] = useState<Service[]>([])
  const [docs, setDocs] = useState<RefDoc[]>([])
  const [error, setError] = useState<string | null>(null)
  const isAdmin = me.roles.includes('admin')
  const canRead = isAdmin || me.roles.some((r) => ['moderator', 'senior_moderator'].includes(r))

  const fail = (e: unknown) => setError((e as Error).message)
  const reload = () => { listServices().then(setServices).catch(fail); listRefDocs().then(setDocs).catch(fail) }
  useEffect(() => { if (canRead) reload() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (!canRead) return <div style={{ color: 'var(--danger)' }}>Раздел «Справочники» доступен модератору или администратору.</div>

  async function addService(e: FormEvent) {
    e.preventDefault()
    const f = e.currentTarget as HTMLFormElement
    const code = (f.elements.namedItem('code') as HTMLInputElement).value.trim()
    const name = (f.elements.namedItem('name') as HTMLInputElement).value.trim()
    const category = (f.elements.namedItem('category') as HTMLInputElement).value.trim()
    if (!code || !name) return
    setError(null)
    try { await createService({ code, name, category: category || null }); f.reset(); reload() } catch (e) { fail(e) }
  }
  async function toggleService(s: Service) {
    try { await updateService(s.id, { is_active: !s.is_active }); reload() } catch (e) { fail(e) }
  }
  async function delService(s: Service) {
    if (!await ask({
      title: `Удалить услугу «${s.name}»?`,
      message: 'Услуга исчезнет из справочника. Уже выпущенные данные и дашборды не пострадают.',
    })) return
    try { await deleteService(s.id); reload() } catch (e) { fail(e) }
  }
  async function addDoc(e: FormEvent) {
    e.preventDefault()
    const f = e.currentTarget as HTMLFormElement
    const title = (f.elements.namedItem('title') as HTMLInputElement).value.trim()
    const url = (f.elements.namedItem('url') as HTMLInputElement).value.trim()
    const description = (f.elements.namedItem('descr') as HTMLInputElement).value.trim()
    if (!title) return
    setError(null)
    try { await createRefDoc({ title, url: url || null, description: description || null }); f.reset(); reload() } catch (e) { fail(e) }
  }
  async function delDoc(d: RefDoc) {
    if (!await ask({
      title: `Удалить документ «${d.title}»?`,
      message: 'Запись справочника документов будет удалена. На загруженные файлы это не влияет.',
    })) return
    try { await deleteRefDoc(d.id); reload() } catch (e) { fail(e) }
  }

  return (
    <div>
      {confirmNode}
      <h2 style={{ fontSize: 20, margin: '0 0 4px' }}>Справочники</h2>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
        Перечень услуг и служебные документы для проверки дашбордов.{!isAdmin && ' Редактирование — у администратора.'}
      </div>
      {error && <div style={errBox}>{error}</div>}

      {/* Услуги */}
      <Section title={`Услуги (${services.length})`}>
        {isAdmin && (
          <form onSubmit={addService} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
            <input name="code" style={{ ...input, width: 140 }} placeholder="код" />
            <input name="name" style={{ ...input, flex: 1, minWidth: 200 }} placeholder="Название услуги" />
            <input name="category" style={{ ...input, width: 180 }} placeholder="Категория (необяз.)" />
            <button style={btn}>＋ Услуга</button>
          </form>
        )}
        {services.length === 0 ? <span style={muted}>Услуг пока нет.</span> : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
              <thead><tr>{['Код', 'Название', 'Категория', 'Статус', ...(isAdmin ? [''] : [])].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
              <tbody>
                {services.map((s) => (
                  <tr key={s.id} style={{ opacity: s.is_active ? 1 : 0.5 }}>
                    <td style={{ ...td, fontFamily: 'monospace' }}>{s.code}</td>
                    <td style={{ ...td, fontWeight: 600 }}>{s.name}</td>
                    <td style={td}>{s.category || '—'}</td>
                    <td style={td}>{s.is_active ? <span style={{ color: 'var(--success)' }}>активна</span> : <span style={{ color: 'var(--text-faint)' }}>скрыта</span>}</td>
                    {isAdmin && (
                      <td style={{ ...td, whiteSpace: 'nowrap' }}>
                        <button style={linkBtn} onClick={() => toggleService(s)}>{s.is_active ? 'скрыть' : 'вернуть'}</button>
                        <button style={{ ...linkBtn, color: 'var(--danger)' }} onClick={() => delService(s)}>удалить</button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* Служебные документы */}
      <Section title={`Служебные документы (${docs.length})`}>
        {isAdmin && (
          <form onSubmit={addDoc} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
            <input name="title" style={{ ...input, flex: 1, minWidth: 200 }} placeholder="Название документа" />
            <input name="url" style={{ ...input, width: 220 }} placeholder="Ссылка (необяз.)" />
            <input name="descr" style={{ ...input, width: 220 }} placeholder="Описание (необяз.)" />
            <button style={btn}>＋ Документ</button>
          </form>
        )}
        {docs.length === 0 ? <span style={muted}>Документов пока нет.</span> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {docs.map((d) => (
              <div key={d.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, border: '1px solid var(--border-faint)', borderRadius: 8, padding: '8px 10px' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>
                    📄 {d.url ? <a href={d.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>{d.title}</a> : d.title}
                  </div>
                  {d.description && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{d.description}</div>}
                </div>
                {isAdmin && <button style={{ ...linkBtn, color: 'var(--danger)' }} onClick={() => delDoc(d)}>удалить</button>}
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div style={{ marginBottom: 24 }}><h3 style={{ fontSize: 15, margin: '0 0 10px' }}>{title}</h3>{children}</div>
}

const input: React.CSSProperties = { height: 34, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13 }
const btn: React.CSSProperties = { height: 34, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer' }
const linkBtn: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: '0 6px 0 0' }
const th: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '6px 10px', background: 'var(--surface-2)', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600 }
const td: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '6px 10px' }
const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 13 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
