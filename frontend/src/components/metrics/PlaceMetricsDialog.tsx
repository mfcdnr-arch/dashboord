import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  dashboardMetricCodes, getDashboard, listDashboards, placeMetricOnDashboard,
  type Dashboard, type DashPage, type MetricValue,
} from '../../api'
import { btnGhost, dialog, overlay, rmBtn } from '../dashboards/shared'

/**
 * Разместить уже заведённые показатели на дашборде.
 *
 * Мастер сборки и панель предложений ставят карточки в момент создания, но у
 * заказчика полтора десятка показателей уже заведены — и единственным способом
 * вывести их было добавлять виджеты по одному руками.
 *
 * Что уже показано на выбранном дашборде, помечается и не предлагается: иначе
 * повторное нажатие тихо наплодило бы дубли карточек.
 */
export function PlaceMetricsDialog(
  { metrics, onClose, onDone }: {
    metrics: MetricValue[]
    onClose: () => void
    onDone: (placed: number, dashboardId: string) => void
  },
) {
  const [dashboards, setDashboards] = useState<Dashboard[]>([])
  const [dashId, setDashId] = useState('')
  const [pages, setPages] = useState<DashPage[]>([])
  const [pageId, setPageId] = useState('')
  const [already, setAlready] = useState<Set<string>>(new Set())
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    listDashboards('', false, 200).then((r) => setDashboards(r.items)).catch(() => setDashboards([]))
  }, [])

  useEffect(() => {
    if (!dashId) { setPages([]); setPageId(''); setAlready(new Set()); return }
    setErr(null)
    Promise.all([getDashboard(dashId), dashboardMetricCodes(dashId)])
      .then(([d, used]) => {
        setPages(d.pages)
        setPageId(d.pages[0]?.id || '')
        setAlready(new Set(used.codes))
        // Уже размещённые снимаем из выбора молча: человек их не выбирал.
        setPicked((p) => new Set([...p].filter((c) => !used.codes.includes(c))))
      })
      .catch((e) => setErr((e as Error).message))
  }, [dashId])

  const free = metrics.filter((m) => !already.has(m.code))
  const ready = Boolean(pageId && picked.size)

  async function place() {
    setBusy(true); setErr(null)
    let placed = 0
    try {
      for (const m of free.filter((x) => picked.has(x.code))) {
        await placeMetricOnDashboard({
          page_id: pageId, metric_code: m.code, name: m.name, unit: m.unit,
        })
        placed += 1
      }
      onDone(placed, dashId)
    } catch (e) {
      setErr(`${(e as Error).message}${placed ? ` (успели разместить: ${placed})` : ''}`)
      setBusy(false)
    }
  }

  return createPortal((
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 660, maxHeight: '84vh', display: 'flex', flexDirection: 'column' }}
        onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Разместить показатели на дашборде</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose} title="Закрыть">✕</button>
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginBottom: 12 }}>
          Каждый отмеченный показатель встанет карточкой рядом с тем, из чего он считается.
          Место система выбирает сама — переставить карточку можно мышью.
        </div>

        <label style={lbl}>
          Дашборд
          <select style={inp} value={dashId} onChange={(e) => setDashId(e.target.value)}>
            <option value="">выберите дашборд…</option>
            {dashboards.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </label>

        {pages.length > 1 && (
          <label style={lbl}>
            Страница
            <select style={inp} value={pageId} onChange={(e) => setPageId(e.target.value)}>
              {pages.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
        )}
        {dashId && !pages.length && (
          <div style={{ fontSize: 12.5, color: 'var(--warn)', marginBottom: 8 }}>
            У дашборда нет ни одной страницы — создайте её и повторите.
          </div>
        )}

        {err && <div style={{ fontSize: 12.5, color: 'var(--danger)', marginBottom: 8 }}>{err}</div>}

        {dashId && (
          <>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, margin: '4px 0 6px' }}>
              <span style={{ fontSize: 12.5, fontWeight: 600 }}>
                Выбрано: {picked.size} из {free.length}
              </span>
              <button style={linkBtn} onClick={() => setPicked(new Set(free.map((m) => m.code)))}>все</button>
              <button style={linkBtn} onClick={() => setPicked(new Set())}>снять</button>
              {already.size > 0 && (
                <span style={{ fontSize: 12, color: 'var(--text-faint)', marginLeft: 'auto' }}>
                  уже на дашборде: {already.size}
                </span>
              )}
            </div>
            <div style={{
              flex: 1, minHeight: 120, overflowY: 'auto', border: '1px solid var(--border)',
              borderRadius: 10, padding: 10, display: 'flex', flexDirection: 'column', gap: 8,
            }}>
              {free.length === 0 && (
                <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                  Все показатели уже размещены на этом дашборде.
                </div>
              )}
              {free.map((m) => (
                <label key={m.code} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, cursor: 'pointer' }}>
                  <input type="checkbox" checked={picked.has(m.code)} style={{ marginTop: 3 }}
                    onChange={() => setPicked((s) => {
                      const n = new Set(s)
                      if (n.has(m.code)) n.delete(m.code); else n.add(m.code)
                      return n
                    })} />
                  <span style={{ minWidth: 0 }}>
                    <span style={{ overflowWrap: 'anywhere' }}>{m.name}</span>
                    {m.value != null && (
                      <span style={{ color: 'var(--accent)', fontWeight: 600 }}>
                        {' '}= {m.value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}{m.unit ? ` ${m.unit}` : ''}
                      </span>
                    )}
                    {m.error && <span style={{ color: 'var(--danger)' }}> · не считается</span>}
                  </span>
                </label>
              ))}
            </div>
          </>
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
          <button style={btnGhost} onClick={onClose}>Отмена</button>
          <button
            disabled={!ready || busy} onClick={place}
            style={{
              height: 36, padding: '0 14px', border: 'none', borderRadius: 8,
              background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14,
              cursor: ready ? 'pointer' : 'default', opacity: !ready || busy ? 0.6 : 1,
            }}
          >{busy ? 'Размещаем…' : `Разместить ${picked.size || ''}`.trim()}</button>
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
const linkBtn: React.CSSProperties = {
  border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: 0,
}
