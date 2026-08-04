// Перепривязка шаблона: сопоставить коды датасетов/метрик шаблона с кодами
// текущего контекста (если их нет — иначе виджеты дадут ошибку). Отсутствующие
// коды подсвечены; для каждого — выбор из доступных или «оставить как есть».
import { btn, btnGhost, dialog, input, overlay, rmBtn } from './shared'

export type RebindState = {
  templateId: string; name: string
  datasets: { code: string; missing: boolean }[]
  metrics: { code: string; missing: boolean }[]
  availDatasets: { code: string; name: string }[]
  availMetrics: { code: string; name: string }[]
  datasetMap: Record<string, string>
  metricMap: Record<string, string>
}

export function RebindModal({ rebind, setRebind, onConfirm, busy }: {
  rebind: RebindState; setRebind: (r: RebindState | null) => void; onConfirm: () => void; busy: boolean
}) {
  const setD = (code: string, to: string) => setRebind({ ...rebind, datasetMap: { ...rebind.datasetMap, [code]: to } })
  const setM = (code: string, to: string) => setRebind({ ...rebind, metricMap: { ...rebind.metricMap, [code]: to } })
  const missingUnmapped =
    rebind.datasets.some((d) => d.missing && !rebind.datasetMap[d.code]) ||
    rebind.metrics.some((m) => m.missing && !rebind.metricMap[m.code])
  const row = (label: string, code: string, missing: boolean, value: string, avail: { code: string; name: string }[], on: (c: string, v: string) => void) => (
    <div key={label + code} style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 8, alignItems: 'center', padding: '4px 0' }}>
      <span style={{ fontSize: 13, color: missing ? 'var(--danger)' : 'var(--text-2)' }}>
        {missing ? '⚠ ' : '✓ '}<code style={{ background: 'var(--surface-3)', padding: '1px 6px', borderRadius: 4 }}>{code}</code>
      </span>
      <span style={{ color: 'var(--text-faint)' }}>→</span>
      <select style={input} value={value} onChange={(e) => on(code, e.target.value)}>
        <option value="">{missing ? '— выберите замену —' : 'оставить как есть'}</option>
        {avail.map((a) => <option key={a.code} value={a.code}>{a.name} ({a.code})</option>)}
      </select>
    </div>
  )
  return (
    <div style={overlay} onClick={() => setRebind(null)}>
      <div style={{ ...dialog, width: 560 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Перепривязка шаблона</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={() => setRebind(null)}>✕</button>
        </div>
        <p style={{ fontSize: 13, color: 'var(--text-2)', margin: '0 0 12px' }}>
          Шаблон ссылается на коды, которых нет в текущем контексте (⚠). Сопоставьте их с существующими
          датасетами/метриками — иначе виджеты дадут ошибку. Совпадающие (✓) можно не трогать.
        </p>
        {rebind.datasets.length > 0 && <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', margin: '6px 0 2px' }}>Датасеты</div>}
        {rebind.datasets.map((d) => row('d', d.code, d.missing, rebind.datasetMap[d.code] || '', rebind.availDatasets, setD))}
        {rebind.metrics.length > 0 && <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', margin: '10px 0 2px' }}>Метрики</div>}
        {rebind.metrics.map((m) => row('m', m.code, m.missing, rebind.metricMap[m.code] || '', rebind.availMetrics, setM))}
        <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
          <button style={{ ...btnGhost, marginLeft: 'auto' }} onClick={() => setRebind(null)}>Отмена</button>
          <button style={btn} disabled={busy || missingUnmapped} onClick={onConfirm}
            title={missingUnmapped ? 'Сначала сопоставьте все отсутствующие коды (⚠)' : ''}>
            {busy ? 'Создание…' : 'Создать дашборд'}
          </button>
        </div>
      </div>
    </div>
  )
}
