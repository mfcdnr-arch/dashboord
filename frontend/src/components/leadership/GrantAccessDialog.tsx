import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { getFeaturedAccess, grantFeaturedAccess, type FeaturedAccess } from '../../api'

// «Предоставить доступ» к отчётам подборки (запрос заказчика: выбрали отчёты
// для руководителя — значит открываем их ему).
//
// Состав подборки и доступ остаются РАЗНЫМИ вещами: отметка в подборку не
// открывает отчёт, иначе решение «кому показывать» перестало бы быть решением
// и однажды руководитель увидел бы то, что ему не предназначалось. Но выдавать
// доступ по одному дашборду, когда подборка собрана целиком, — работа
// впустую, поэтому здесь он выдаётся пакетом.
//
// Рядом с каждым показано, сколько отчётов подборки человеку УЖЕ доступно:
// иначе администратор выдаёт выданное и не понимает, почему ничего не
// изменилось. Носителям привилегированных ролей гранты не нужны вовсе — они
// видят все отчёты организации, и об этом сказано прямо.
export default function GrantAccessDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [d, setD] = useState<FeaturedAccess | null>(null)
  const [users, setUsers] = useState<Record<string, boolean>>({})
  const [roles, setRoles] = useState<Record<string, boolean>>({})
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => getFeaturedAccess().then(setD).catch((e) => setErr((e as Error).message))
  useEffect(() => { load() }, [])

  const chosen = useMemo(() => ({
    users: Object.entries(users).filter(([, v]) => v).map(([k]) => k),
    roles: Object.entries(roles).filter(([, v]) => v).map(([k]) => k),
  }), [users, roles])

  const total = d?.dashboards.length ?? 0
  const drafts = (d?.dashboards || []).filter((x) => x.publication_status !== 'published')

  async function grant() {
    setBusy(true); setErr(null); setMsg(null)
    try {
      const r = await grantFeaturedAccess(chosen.users, chosen.roles)
      setMsg(r.granted === 0
        ? 'Всё выбранное уже было открыто — новых доступов не потребовалось.'
        : `Готово: выдано доступов ${r.granted} (отчётов в подборке: ${r.dashboards}).`)
      setUsers({}); setRoles({})
      load()
      onDone()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return createPortal((
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Доступ к отчётам подборки</div>
          <button style={{ ...xBtn, marginLeft: 'auto' }} onClick={onClose} title="Закрыть">✕</button>
        </div>
        <div style={{ ...muted, marginBottom: 10 }}>
          Доступ будет выдан сразу ко всем отчётам подборки ({total}). Снять его можно на самом
          дашборде или в карточке сотрудника — здесь только выдача.
        </div>

        {err && <div style={errBox}>{err}</div>}
        {msg && <div style={okBox}>{msg}</div>}
        {!d && !err && <div style={muted}>Загрузка…</div>}

        {d && total === 0 && (
          <div style={noteBox}>
            В подборке пока нет отчётов. Сначала отметьте их кнопкой «⚙ Настроить подборку».
          </div>
        )}

        {d && total > 0 && (
          <>
            {drafts.length > 0 && (
              <div style={warnBox}>
                Не опубликовано отчётов: {drafts.length}. Доступ к ним выдастся, но зритель увидит
                их только после публикации — это модерационное правило, а не ошибка выдачи.
              </div>
            )}

            <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
              overflowY: 'auto', flex: 1, minHeight: 0 }}>
              <div>
                <div style={head}>Сотрудники</div>
                {d.users.map((u) => (
                  <label key={u.id} style={row} title={u.privileged
                    ? 'Роль администратора или модератора и так открывает все отчёты организации'
                    : undefined}>
                    <input type="checkbox" checked={!!users[u.id]} disabled={u.privileged}
                      onChange={(e) => setUsers((c) => ({ ...c, [u.id]: e.target.checked }))} />
                    <span style={{ flex: 1, minWidth: 0 }}>
                      {u.full_name || u.login}
                      {u.full_name && <span style={muted}> · {u.login}</span>}
                    </span>
                    <span style={u.privileged ? badge : u.has === total ? okBadge : muted}>
                      {u.privileged ? 'видит всё по роли'
                        : u.has === 0 ? 'нет доступа'
                          : u.has === total ? 'открыта вся подборка' : `открыто ${u.has} из ${total}`}
                    </span>
                  </label>
                ))}
              </div>

              <div>
                <div style={head}>Роли</div>
                <div style={{ ...muted, marginBottom: 6 }}>
                  Доступ роли получают все её носители — и те, кого примут в неё позже.
                </div>
                {d.roles.filter((r) => r.members > 0).map((r) => (
                  <label key={r.id} style={row}>
                    <input type="checkbox" checked={!!roles[r.id]}
                      onChange={(e) => setRoles((c) => ({ ...c, [r.id]: e.target.checked }))} />
                    <span style={{ flex: 1, minWidth: 0 }}>{r.name}<span style={muted}> · {r.members} чел.</span></span>
                    <span style={r.has === total ? okBadge : muted}>
                      {r.has === 0 ? 'нет доступа'
                        : r.has === total ? 'открыта вся подборка' : `открыто ${r.has} из ${total}`}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 12 }}>
              <button style={{ ...btn, opacity: (chosen.users.length + chosen.roles.length) === 0 || busy ? 0.5 : 1 }}
                disabled={(chosen.users.length + chosen.roles.length) === 0 || busy} onClick={grant}>
                {busy ? 'Выдача…' : 'Предоставить доступ'}
              </button>
              <span style={muted}>
                {chosen.users.length + chosen.roles.length === 0
                  ? 'Выберите сотрудников или роли.'
                  : `Выбрано: сотрудников ${chosen.users.length}, ролей ${chosen.roles.length}.`}
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  ), document.body)
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex',
  alignItems: 'center', justifyContent: 'center', zIndex: 70, padding: 20,
}
const dialog: React.CSSProperties = {
  background: 'var(--surface)', borderRadius: 14, padding: 20, width: 680, maxWidth: '94vw',
  maxHeight: '86vh', display: 'flex', flexDirection: 'column', boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
}
const row: React.CSSProperties = {
  display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, padding: '4px 2px',
}
const head: React.CSSProperties = { fontSize: 13, fontWeight: 600, marginBottom: 6 }
const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 12 }
const badge: React.CSSProperties = {
  fontSize: 11, padding: '1px 8px', borderRadius: 9, background: 'var(--surface-3)', color: 'var(--text-2)',
}
const okBadge: React.CSSProperties = { ...badge, background: 'var(--success-bg)', color: 'var(--success)' }
const btn: React.CSSProperties = {
  height: 34, padding: '0 16px', border: 'none', borderRadius: 8,
  background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, cursor: 'pointer',
}
const xBtn: React.CSSProperties = {
  border: 'none', background: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--text-muted)',
}
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px',
  borderRadius: 8, marginBottom: 8,
}
const okBox: React.CSSProperties = {
  background: 'var(--success-bg)', color: 'var(--success)', fontSize: 13, padding: '8px 10px',
  borderRadius: 8, marginBottom: 8,
}
const warnBox: React.CSSProperties = {
  background: 'var(--warn-bg)', color: 'var(--warn)', fontSize: 12, padding: '8px 10px',
  borderRadius: 8, marginBottom: 8,
}
const noteBox: React.CSSProperties = {
  background: 'var(--surface-2)', color: 'var(--text-2)', fontSize: 13, padding: '8px 10px', borderRadius: 8,
}
