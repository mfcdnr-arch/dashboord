import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  createAnnouncement, createInstruction, deleteAnnouncement, deleteInstruction,
  downloadInstructionFile, getInstruction, listAnnouncements, listInstructions,
  updateAnnouncement, updateInstruction, uploadInstructionFile,
  type Announcement, type Instruction,
} from '../api'
import { useConfirm } from './dashboards/ConfirmDialog'

/**
 * «Инструкции» — то, что читает пользователь, и то, что администратор туда кладёт.
 *
 * Две вкладки в одном разделе намеренно: инструкции и объявления — это одно и
 * то же по смыслу («содержимое для пользователей»), и разводить их по разным
 * пунктам меню значило бы удлинять меню ради классификации, которая читателю
 * безразлична. Пользователь вкладок не видит вовсе — ему показывается только
 * список инструкций.
 */
export default function InstructionsPage({ canManage }: { canManage: boolean }) {
  const [tab, setTab] = useState<'read' | 'manage' | 'ann'>('read')
  return (
    <div>
      <h2 style={{ fontSize: 18, margin: '0 0 4px' }}>Инструкции</h2>
      <div style={{ ...muted, marginBottom: 12 }}>
        Как пользоваться системой: короткие статьи и готовые руководства для скачивания.
      </div>
      {canManage && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
          {([['read', 'Как видит пользователь'], ['manage', '✎ Инструкции'], ['ann', '📢 Объявления']] as const)
            .map(([k, label]) => (
              <button key={k} style={tab === k ? tabActive : tabBtn} onClick={() => setTab(k)}>{label}</button>
            ))}
        </div>
      )}
      {tab === 'read' && <ReadList />}
      {tab === 'manage' && canManage && <ManageList />}
      {tab === 'ann' && canManage && <AnnouncementsAdmin />}
    </div>
  )
}

/* ─── Чтение ────────────────────────────────────────────────────────────── */

function ReadList() {
  const [items, setItems] = useState<Instruction[]>([])
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<Instruction | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback((query: string) => {
    listInstructions({ q: query || undefined })
      .then((r) => setItems(r.items)).catch((e) => setErr((e as Error).message))
  }, [])
  useEffect(() => { load(q) }, [load, q])

  // Разделы: инструкции читают по темам, сплошной список из двадцати статей
  // заставляет искать глазами.
  const sections = useMemo(() => {
    const m = new Map<string, Instruction[]>()
    items.forEach((i) => {
      const key = i.section || 'Прочее'
      m.set(key, [...(m.get(key) || []), i])
    })
    return [...m.entries()]
  }, [items])

  async function openOne(i: Instruction) {
    try {
      // Открытие гасит отметку «новое» на сервере — заодно получаем свежий текст.
      const full = await getInstruction(i.id)
      setOpen(full)
      setItems((cur) => cur.map((x) => (x.id === i.id ? { ...x, is_read: true } : x)))
    } catch (e) { setErr((e as Error).message) }
  }

  if (open) {
    return (
      <div>
        <button style={crumb} onClick={() => setOpen(null)}>← Все инструкции</button>
        <div style={{ ...card, marginTop: 10 }}>
          <div style={{ ...muted, fontSize: 12 }}>{open.section || 'Прочее'}</div>
          <h3 style={{ fontSize: 17, margin: '4px 0 10px' }}>{open.title}</h3>
          {open.body && (
            <div style={{ fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{open.body}</div>
          )}
          {open.file_name && (
            <button style={{ ...btn, marginTop: 14 }}
              onClick={() => downloadInstructionFile(open.id, open.file_name || 'instruction')}>
              ⤓ Скачать «{open.file_name}»
              {open.file_size_bytes ? ` · ${Math.round(open.file_size_bytes / 1024)} КБ` : ''}
            </button>
          )}
          <div style={{ ...muted, fontSize: 12, marginTop: 12 }}>
            Обновлено {new Date(open.updated_at).toLocaleDateString('ru-RU')}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div>
      {err && <div style={errBox}>{err}</div>}
      <input style={{ ...input, maxWidth: 420, marginBottom: 12 }} value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="🔍 Поиск по заголовку и тексту инструкций…" />
      {items.length === 0 ? (
        <div style={muted}>
          {q ? 'Ничего не нашлось — попробуйте другое слово.' : 'Инструкций пока нет.'}
        </div>
      ) : sections.map(([name, list]) => (
        <div key={name} style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)', marginBottom: 6 }}>{name}</div>
          <div style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
            {list.map((i, idx) => (
              <button key={i.id} style={{ ...rowBtn, borderTop: idx ? '1px solid var(--border-faint)' : 'none' }}
                onClick={() => openOne(i)}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                  <span style={{ fontSize: 14, fontWeight: 600 }}>{i.title}</span>
                  {/* «Новое» — по тому, открывал ли ЭТОТ человек: иначе он не
                      узнает, что появилось с прошлого раза, не перечитав всё. */}
                  {!i.is_read && <span style={badgeNew}>новое</span>}
                  {i.file_name && <span style={{ ...muted, fontSize: 11.5 }}>📎 файл</span>}
                </span>
                <span style={{ ...muted, fontSize: 11.5 }}>
                  {new Date(i.updated_at).toLocaleDateString('ru-RU')}
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/* ─── Управление инструкциями ───────────────────────────────────────────── */

function ManageList() {
  const [items, setItems] = useState<Instruction[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [edit, setEdit] = useState<Partial<Instruction> | null>(null)
  const [busy, setBusy] = useState(false)
  const { ask, node } = useConfirm()

  const load = useCallback(() => {
    listInstructions({ drafts: true }).then((r) => setItems(r.items)).catch((e) => setErr((e as Error).message))
  }, [])
  useEffect(() => { load() }, [load])

  async function save() {
    if (!edit) return
    setBusy(true); setErr(null)
    try {
      const saved = edit.id
        ? await updateInstruction(edit.id, {
            title: edit.title, section: edit.section, body: edit.body,
            position: edit.position, is_published: edit.is_published,
          })
        : await createInstruction(edit)
      setEdit(saved); load()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  async function attach(file: File) {
    if (!edit?.id) { setErr('Сначала сохраните инструкцию, потом прикладывайте файл'); return }
    setBusy(true); setErr(null)
    try { setEdit(await uploadInstructionFile(edit.id, file)); load() }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  async function remove(i: Instruction) {
    if (!await ask({
      title: `Удалить «${i.title}»?`,
      message: 'Инструкция и приложенный к ней файл будут удалены безвозвратно. '
        + 'Если нужно просто убрать её у пользователей — снимите галочку «Опубликована».',
      confirmLabel: 'Удалить', busyLabel: 'Удаление…',
    })) return
    try { await deleteInstruction(i.id); if (edit?.id === i.id) setEdit(null); load() }
    catch (e) { setErr((e as Error).message) }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
      {node}
      <div>
        <button style={btn} onClick={() => setEdit({ title: '', section: '', body: '', position: 0, is_published: true })}>
          ＋ Новая инструкция
        </button>
        {err && <div style={{ ...errBox, marginTop: 10 }}>{err}</div>}
        <div style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden', marginTop: 12 }}>
          {items.length === 0 && <div style={{ ...muted, padding: 12 }}>Инструкций пока нет.</div>}
          {items.map((i, idx) => (
            <div key={i.id} style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px',
              borderTop: idx ? '1px solid var(--border-faint)' : 'none',
              background: edit?.id === i.id ? 'var(--accent-weak-bg)' : 'transparent',
            }}>
              <button style={{ ...linkBtn, flex: 1, textAlign: 'left', color: 'var(--text)' }}
                onClick={() => setEdit(i)}>
                <div style={{ fontSize: 13.5, fontWeight: 600 }}>{i.title}</div>
                <div style={{ ...muted, fontSize: 11.5 }}>
                  {i.section || 'Прочее'} · порядок {i.position}
                  {i.file_name && ` · 📎 ${i.file_name}`}
                  {!i.is_published && ' · черновик'}
                </div>
              </button>
              <button style={iconBtn} title="Удалить" onClick={() => remove(i)}>🗑</button>
            </div>
          ))}
        </div>
      </div>

      {edit && (
        <div style={card}>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>
            {edit.id ? 'Правка инструкции' : 'Новая инструкция'}
          </div>
          <label style={lbl}>Раздел (для группировки)</label>
          <input style={input} value={edit.section || ''} placeholder="Начало работы"
            onChange={(e) => setEdit({ ...edit, section: e.target.value })} />
          <label style={lbl}>Название</label>
          <input style={input} value={edit.title || ''}
            onChange={(e) => setEdit({ ...edit, title: e.target.value })} />
          <label style={lbl}>Текст</label>
          <textarea style={{ ...input, minHeight: 180, resize: 'vertical' }} value={edit.body || ''}
            placeholder="Опишите порядок действий по шагам."
            onChange={(e) => setEdit({ ...edit, body: e.target.value })} />
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
            <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13 }}>
              <input type="checkbox" checked={edit.is_published !== false}
                onChange={(e) => setEdit({ ...edit, is_published: e.target.checked })} />
              Опубликована
            </label>
            <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13 }}>
              Порядок
              <input type="number" style={{ ...input, width: 80, margin: 0 }} value={edit.position ?? 0}
                onChange={(e) => setEdit({ ...edit, position: Number(e.target.value) })} />
            </label>
          </div>
          <div style={{ marginTop: 12 }}>
            <label style={lbl}>Приложенный файл</label>
            {edit.file_name
              ? <div style={{ fontSize: 13, marginBottom: 6 }}>📎 {edit.file_name}</div>
              : <div style={{ ...muted, fontSize: 12.5, marginBottom: 6 }}>
                  Можно приложить готовое руководство (.docx, .pdf, .xlsx, картинку) — до 25 МБ.
                </div>}
            <input type="file" disabled={!edit.id || busy}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) attach(f) }} />
            {!edit.id && <div style={{ ...muted, fontSize: 12 }}>Файл можно приложить после сохранения.</div>}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
            <button style={btn} disabled={busy} onClick={save}>{busy ? 'Сохранение…' : 'Сохранить'}</button>
            <button style={btnGhost} onClick={() => setEdit(null)}>Закрыть</button>
          </div>
        </div>
      )}
    </div>
  )
}

/* ─── Объявления ────────────────────────────────────────────────────────── */

function AnnouncementsAdmin() {
  const [items, setItems] = useState<Announcement[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [important, setImportant] = useState(false)
  const [endsAt, setEndsAt] = useState('')
  const [busy, setBusy] = useState(false)
  const { ask, node } = useConfirm()

  const load = useCallback(() => {
    listAnnouncements(true).then(setItems).catch((e) => setErr((e as Error).message))
  }, [])
  useEffect(() => { load() }, [load])

  async function add() {
    setBusy(true); setErr(null)
    try {
      await createAnnouncement({
        title, body, important,
        // Дату превращаем в конец дня: «до 20.08» человек понимает как
        // «включая 20-е», а не «до полуночи 19-го».
        ends_at: endsAt ? `${endsAt}T23:59:59` : null,
      })
      setTitle(''); setBody(''); setImportant(false); setEndsAt(''); load()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  async function remove(a: Announcement) {
    if (!await ask({
      title: 'Удалить объявление?', message: `«${a.title}» исчезнет с главной у всех пользователей.`,
      confirmLabel: 'Удалить', busyLabel: 'Удаление…',
    })) return
    try { await deleteAnnouncement(a.id); load() } catch (e) { setErr((e as Error).message) }
  }

  const now = Date.now()
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
      {node}
      <div style={card}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Новое объявление</div>
        <div style={{ ...muted, fontSize: 12.5, marginBottom: 10 }}>
          Появится на главной у всех пользователей. Важное выделяется красным и стоит первым.
        </div>
        {err && <div style={{ ...errBox, marginBottom: 10 }}>{err}</div>}
        <label style={lbl}>Заголовок</label>
        <input style={input} value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder="Плановые работы в субботу" />
        <label style={lbl}>Текст</label>
        <textarea style={{ ...input, minHeight: 110, resize: 'vertical' }} value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="20.08 с 9:00 до 12:00 система может быть недоступна." />
        <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13 }}>
            <input type="checkbox" checked={important} onChange={(e) => setImportant(e.target.checked)} />
            Важное
          </label>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13 }}>
            Показывать до
            <input type="date" style={{ ...input, width: 150, margin: 0 }} value={endsAt}
              onChange={(e) => setEndsAt(e.target.value)} />
          </label>
        </div>
        <div style={{ ...muted, fontSize: 12, marginTop: 6 }}>
          Без даты объявление висит бессрочно. Срок стоит ставить: главная, заросшая старыми
          сообщениями, перестаёт читаться, и мимо пройдёт важное.
        </div>
        <button style={{ ...btn, marginTop: 12 }} disabled={busy || !title.trim() || !body.trim()} onClick={add}>
          {busy ? 'Публикую…' : 'Опубликовать'}
        </button>
      </div>

      <div>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 8 }}>Опубликованные</div>
        <div style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
          {items.length === 0 && <div style={{ ...muted, padding: 12 }}>Объявлений нет.</div>}
          {items.map((a, i) => {
            const expired = a.ends_at ? new Date(a.ends_at).getTime() < now : false
            return (
              <div key={a.id} style={{
                padding: '10px 12px', borderTop: i ? '1px solid var(--border-faint)' : 'none',
                opacity: expired || !a.is_active ? 0.55 : 1,
              }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 13.5, fontWeight: 600 }}>
                    {a.important ? '❗ ' : ''}{a.title}
                  </span>
                  {expired && <span style={{ ...muted, fontSize: 11.5 }}>срок вышел</span>}
                  {!a.is_active && <span style={{ ...muted, fontSize: 11.5 }}>снято</span>}
                  <button style={{ ...linkBtn, marginLeft: 'auto' }}
                    onClick={() => updateAnnouncement(a.id, { is_active: !a.is_active }).then(load)}>
                    {a.is_active ? 'снять с показа' : 'показать снова'}
                  </button>
                  <button style={iconBtn} title="Удалить" onClick={() => remove(a)}>🗑</button>
                </div>
                <div style={{ fontSize: 12.5, marginTop: 4, whiteSpace: 'pre-wrap' }}>{a.body}</div>
                <div style={{ ...muted, fontSize: 11.5, marginTop: 4 }}>
                  с {new Date(a.starts_at).toLocaleDateString('ru-RU')}
                  {a.ends_at ? ` до ${new Date(a.ends_at).toLocaleDateString('ru-RU')}` : ' · бессрочно'}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: 16,
}
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 13 }
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', padding: 10, borderRadius: 10, fontSize: 13,
}
const input: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '7px 10px', fontSize: 13, marginBottom: 8,
  border: '1px solid var(--border-strong)', borderRadius: 8,
  background: 'var(--surface)', color: 'var(--text)',
}
const lbl: React.CSSProperties = { display: 'block', fontSize: 12.5, fontWeight: 600, marginBottom: 3 }
const btn: React.CSSProperties = {
  padding: '8px 14px', borderRadius: 9, border: 'none',
  background: 'var(--accent)', color: '#fff', fontSize: 13.5, fontWeight: 600, cursor: 'pointer',
}
const btnGhost: React.CSSProperties = {
  padding: '8px 14px', borderRadius: 9, border: '1px solid var(--border-strong)',
  background: 'var(--surface)', color: 'var(--text)', fontSize: 13.5, cursor: 'pointer',
}
const linkBtn: React.CSSProperties = {
  border: 'none', background: 'none', color: 'var(--accent)', fontSize: 12.5, cursor: 'pointer',
}
const iconBtn: React.CSSProperties = {
  border: '1px solid var(--border)', background: 'var(--surface)', borderRadius: 8,
  width: 28, height: 28, cursor: 'pointer', fontSize: 13,
}
const rowBtn: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10,
  width: '100%', padding: '10px 12px', border: 'none', background: 'var(--surface)',
  cursor: 'pointer', textAlign: 'left',
}
const badgeNew: React.CSSProperties = {
  fontSize: 10.5, fontWeight: 700, padding: '1px 7px', borderRadius: 8,
  background: 'var(--accent)', color: '#fff',
}
const crumb: React.CSSProperties = {
  border: 'none', background: 'none', color: 'var(--accent)', fontSize: 13, cursor: 'pointer', padding: 0,
}
const tabBtn: React.CSSProperties = {
  padding: '6px 12px', borderRadius: 9, border: '1px solid var(--border)',
  background: 'var(--surface)', color: 'var(--text)', fontSize: 13, cursor: 'pointer',
}
const tabActive: React.CSSProperties = { ...tabBtn, borderColor: 'var(--accent)', color: 'var(--accent)', fontWeight: 600 }
