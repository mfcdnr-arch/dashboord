import { useEffect, useState } from 'react'
import {
  checkFreshness, getRetentionPreview, getSettings, runRetention, updateOrgSettings, updateSystemSettings,
  type AllSettings, type OrgThresholds, type RetentionPreview, type SystemThresholds,
} from '../api'

// Раздел «Настройки» (admin/superadmin): пороги, которые раньше менялись только
// правкой .env + рестарт контейнера — теперь через UI, без доступа к серверу.

type SysForm = Record<keyof SystemThresholds, string>
type OrgForm = Record<keyof OrgThresholds, string>

function sysToForm(v: SystemThresholds): SysForm {
  return {
    login_max_attempts: String(v.login_max_attempts), login_lockout_minutes: String(v.login_lockout_minutes),
    cpu_warn: String(v.cpu_warn), cpu_crit: String(v.cpu_crit),
    ram_warn: String(v.ram_warn), ram_crit: String(v.ram_crit),
    disk_warn: String(v.disk_warn), disk_crit: String(v.disk_crit),
  }
}
function orgToForm(v: OrgThresholds): OrgForm {
  return { stale_days: String(v.stale_days), retention_months: String(v.retention_months),
    appeal_response_hours: String(v.appeal_response_hours) }
}

export default function SettingsPage({ me }: { me: { roles: string[] } }) {
  const canAdmin = me.roles.includes('admin') || me.roles.includes('superadmin')
  const [data, setData] = useState<AllSettings | null>(null)
  const [sysForm, setSysForm] = useState<SysForm | null>(null)
  const [orgForm, setOrgForm] = useState<OrgForm | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [savingSys, setSavingSys] = useState(false)
  const [savingOrg, setSavingOrg] = useState(false)
  const [freshBusy, setFreshBusy] = useState(false)
  const [freshResult, setFreshResult] = useState<string | null>(null)

  async function doFreshness() {
    setFreshBusy(true); setError(null); setFreshResult(null)
    try {
      const r = await checkFreshness()
      setFreshResult(r.stale_objects === 0
        ? 'Все объекты обновляются в срок.'
        : `Объектов без свежих данных: ${r.stale_objects}; уведомлений отправлено: ${r.notifications_created}.`)
    } catch (e) { setError((e as Error).message) } finally { setFreshBusy(false) }
  }

  const load = () => getSettings().then((d) => {
    setData(d); setSysForm(sysToForm(d.system)); setOrgForm(orgToForm(d.org))
  }).catch((e) => setError((e as Error).message))
  useEffect(() => { if (canAdmin) load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (!canAdmin) return <div style={{ color: 'var(--danger)' }}>Раздел «Настройки» доступен только администратору.</div>
  if (!data || !sysForm || !orgForm) return <div>{error ? <div style={errBox}>{error}</div> : <span style={muted}>Загрузка…</span>}</div>

  async function saveSys() {
    setSavingSys(true); setError(null)
    try {
      const patch: Partial<SystemThresholds> = {}
      for (const k in sysForm!) patch[k as keyof SystemThresholds] = Number(sysForm![k as keyof SystemThresholds])
      await updateSystemSettings(patch)
      await load(); setSavedAt(Date.now())
    } catch (e) { setError((e as Error).message) } finally { setSavingSys(false) }
  }
  async function saveOrg() {
    setSavingOrg(true); setError(null)
    try {
      const patch: Partial<OrgThresholds> = {}
      for (const k in orgForm!) patch[k as keyof OrgThresholds] = Number(orgForm![k as keyof OrgThresholds])
      await updateOrgSettings(patch)
      await load(); setSavedAt(Date.now())
    } catch (e) { setError((e as Error).message) } finally { setSavingOrg(false) }
  }

  return (
    <div>
      <h2 style={{ fontSize: 20, margin: '0 0 16px' }}>Настройки</h2>
      {error && <div style={errBox}>{error}</div>}
      {savedAt && !error && <div style={okBox}>Сохранено.</div>}

      <Section title="Данные организации" hint="свежесть и хранение (раньше — только через .env)">
        <div style={grid2}>
          <Field label="Свежесть данных, дней" hint="если по объекту нет новых данных дольше — уведомление">
            <input style={inp} type="number" min={1} value={orgForm.stale_days}
              onChange={(e) => setOrgForm({ ...orgForm, stale_days: e.target.value })} />
          </Field>
          <Field label="Ретенция, месяцев" hint="0 — хранить без ограничения; окно скользящего удаления старых данных">
            <input style={inp} type="number" min={0} value={orgForm.retention_months}
              onChange={(e) => setOrgForm({ ...orgForm, retention_months: e.target.value })} />
          </Field>
          <Field label="Срок ответа на обращение, часов"
            hint="ничего не запрещает: делает ожидание видимым — в списке обращений просроченные помечаются красным">
            <input style={inp} type="number" min={1} max={720} value={orgForm.appeal_response_hours}
              onChange={(e) => setOrgForm({ ...orgForm, appeal_response_hours: e.target.value })} />
          </Field>
        </div>
        <button style={btn} disabled={savingOrg} onClick={saveOrg}>{savingOrg ? 'Сохранение…' : 'Сохранить'}</button>
        <button style={{ ...btnGhost, marginLeft: 8 }} disabled={freshBusy} onClick={doFreshness}
          title="Разослать уведомления по объектам, где давно не было новых данных (обычно это делает планировщик)">
          {freshBusy ? 'Проверка…' : '🕓 Проверить свежесть сейчас'}
        </button>
        {freshResult && <span style={{ ...muted, marginLeft: 8 }}>{freshResult}</span>}
      </Section>

      <RetentionSection savedMonths={data.org.retention_months} />

      <Section title="Системные пороги" hint="один сервер на инсталляцию — вход и здоровье системы">
        <div style={grid2}>
          <Field label="Попыток входа до блокировки">
            <input style={inp} type="number" min={0} value={sysForm.login_max_attempts}
              onChange={(e) => setSysForm({ ...sysForm, login_max_attempts: e.target.value })} />
          </Field>
          <Field label="Блокировка, минут">
            <input style={inp} type="number" min={1} value={sysForm.login_lockout_minutes}
              onChange={(e) => setSysForm({ ...sysForm, login_lockout_minutes: e.target.value })} />
          </Field>
          <Field label="CPU: предупреждение, %">
            <input style={inp} type="number" min={1} max={99} value={sysForm.cpu_warn}
              onChange={(e) => setSysForm({ ...sysForm, cpu_warn: e.target.value })} />
          </Field>
          <Field label="CPU: критично, %">
            <input style={inp} type="number" min={1} max={100} value={sysForm.cpu_crit}
              onChange={(e) => setSysForm({ ...sysForm, cpu_crit: e.target.value })} />
          </Field>
          <Field label="RAM: предупреждение, %">
            <input style={inp} type="number" min={1} max={99} value={sysForm.ram_warn}
              onChange={(e) => setSysForm({ ...sysForm, ram_warn: e.target.value })} />
          </Field>
          <Field label="RAM: критично, %">
            <input style={inp} type="number" min={1} max={100} value={sysForm.ram_crit}
              onChange={(e) => setSysForm({ ...sysForm, ram_crit: e.target.value })} />
          </Field>
          <Field label="Диск: предупреждение, %">
            <input style={inp} type="number" min={1} max={99} value={sysForm.disk_warn}
              onChange={(e) => setSysForm({ ...sysForm, disk_warn: e.target.value })} />
          </Field>
          <Field label="Диск: критично, %">
            <input style={inp} type="number" min={1} max={100} value={sysForm.disk_crit}
              onChange={(e) => setSysForm({ ...sysForm, disk_crit: e.target.value })} />
          </Field>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 4, marginBottom: 12 }}>
          При «критично» — статус «Здоровье системы» становится degraded, сторожевой процесс пытается починить.
        </div>
        <button style={btn} disabled={savingSys} onClick={saveSys}>{savingSys ? 'Сохранение…' : 'Сохранить'}</button>
      </Section>
    </div>
  )
}

// Ретенция удаляет данные НЕОБРАТИМО, поэтому здесь сначала предпросмотр
// («что именно уйдёт»), и только потом — запуск с подтверждением. Раньше и то,
// и другое было доступно только через API (curl), без интерфейса.
function RetentionSection({ savedMonths }: { savedMonths: number }) {
  const [preview, setPreview] = useState<RetentionPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [confirm, setConfirm] = useState(false)

  async function load() {
    setBusy(true); setErr(null); setDone(null)
    try { setPreview(await getRetentionPreview()) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  useEffect(() => { load() }, [savedMonths]) // eslint-disable-line react-hooks/exhaustive-deps

  async function doRun() {
    setRunning(true); setErr(null)
    try {
      const r = await runRetention()
      setDone(`Удалено выпусков: ${r.deleted_releases}.`)
      setConfirm(false)
      await load()
    } catch (e) { setErr((e as Error).message) } finally { setRunning(false) }
  }

  return (
    <Section title="Хранение данных (ретенция)" hint="что будет удалено по окну хранения — до удаления">
      {err && <div style={errBox}>{err}</div>}
      {done && <div style={okBox}>{done}</div>}
      {busy && !preview && <span style={muted}>Загрузка предпросмотра…</span>}
      {preview && !preview.enabled && (
        <div style={muted}>Ретенция выключена (окно хранения = 0) — старые данные не удаляются.</div>
      )}
      {preview && preview.enabled && (
        <>
          <div style={{ fontSize: 14, marginBottom: 8 }}>
            Окно хранения: <b>{preview.months} мес.</b> Под удаление попадает{' '}
            <b style={{ color: preview.releases ? 'var(--danger)' : 'inherit' }}>{preview.releases}</b>{' '}
            выпуск(ов) данных и <b>{preview.values}</b> значений.
          </div>
          {preview.releases === 0 && <div style={muted}>Сейчас удалять нечего — все данные внутри окна хранения.</div>}
          {!!preview.affected_dashboards?.length && (
            <div style={{ ...warnBox }}>
              ⚠ После удаления останутся без данных дашборды: {preview.affected_dashboards.join(', ')}
              {preview.affected_dashboards.length >= 20 ? ' …' : ''}
            </div>
          )}
          {!!preview.items.length && (
            <div style={{ maxHeight: 260, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 8, marginBottom: 10 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr>
                    {['Период', 'Объект', 'Датасет', 'Значений'].map((h) => (
                      <th key={h} style={th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.items.map((it) => (
                    <tr key={it.id}>
                      <td style={td}>{it.period || '—'}</td>
                      <td style={td}>{it.object_name || '—'}</td>
                      <td style={td}>{it.name} <span style={{ color: 'var(--text-faint)' }}>({it.code})</span></td>
                      <td style={{ ...td, textAlign: 'right' }}>{it.values_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {preview.releases > preview.items.length && (
                <div style={{ ...muted, padding: '6px 10px' }}>
                  Показаны первые {preview.items.length} из {preview.releases} — остальные будут удалены так же.
                </div>
              )}
            </div>
          )}
          <button style={btnGhost} disabled={busy} onClick={load}>{busy ? 'Обновление…' : '↻ Обновить предпросмотр'}</button>
          {preview.releases > 0 && !confirm && (
            <button style={{ ...btnDanger, marginLeft: 8 }} onClick={() => setConfirm(true)}>
              🗑 Удалить сейчас…
            </button>
          )}
          {confirm && (
            <span style={{ marginLeft: 8 }}>
              <span style={{ fontSize: 13, color: 'var(--danger)', marginRight: 8 }}>
                Удалить {preview.releases} выпуск(ов) безвозвратно?
              </span>
              <button style={btnDanger} disabled={running} onClick={doRun}>{running ? 'Удаление…' : 'Да, удалить'}</button>
              <button style={{ ...btnGhost, marginLeft: 6 }} disabled={running} onClick={() => setConfirm(false)}>Отмена</button>
            </span>
          )}
          <div style={{ ...muted, marginTop: 8 }}>
            Обычно ретенция выполняется планировщиком (воскресенье, 03:00). Ручной запуск нужен, например,
            перед первым включением окна хранения. Перед удалением убедитесь, что есть свежая резервная копия.
          </div>
        </>
      )}
    </Section>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'block' }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{label}</div>
      {children}
      {hint && <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 2 }}>{hint}</div>}
    </label>
  )
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 10 }}>
        <h3 style={{ fontSize: 15, margin: 0 }}>{title}</h3>
        {hint && <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>{hint}</span>}
      </div>
      {children}
    </div>
  )
}

const muted: React.CSSProperties = { color: 'var(--text-faint)', fontSize: 13 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const okBox: React.CSSProperties = { background: 'var(--success-bg)', color: 'var(--success)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const grid2: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginBottom: 12 }
const inp: React.CSSProperties = { width: '100%', height: 34, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text)', fontSize: 14 }
const btn: React.CSSProperties = { height: 34, padding: '0 16px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', cursor: 'pointer', fontSize: 13, fontWeight: 600 }
const btnGhost: React.CSSProperties = { height: 34, padding: '0 14px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text)', cursor: 'pointer', fontSize: 13 }
const btnDanger: React.CSSProperties = { height: 34, padding: '0 14px', border: '1px solid var(--danger)', borderRadius: 8, background: 'var(--danger-bg)', color: 'var(--danger)', cursor: 'pointer', fontSize: 13, fontWeight: 600 }
const warnBox: React.CSSProperties = { background: 'var(--warn-bg)', color: 'var(--warn)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 10 }
const th: React.CSSProperties = { textAlign: 'left', fontSize: 12, fontWeight: 600, padding: '6px 10px', borderBottom: '1px solid var(--border)', background: 'var(--surface-alt, transparent)', position: 'sticky', top: 0 }
const td: React.CSSProperties = { padding: '5px 10px', borderBottom: '1px solid var(--border-faint)' }
