import { useEffect, useState } from 'react'
import { fmtNumber } from '../../lib/format'
import {
  createMetric, createVersion, dataSuggestions, getDashboard, listDashboards,
  placeMetricOnDashboard, type Dashboard, type DataSuggestion, type SuggestDataset,
} from '../../api'

const TYPE_RU: Record<string, string> = {
  plan_fact_pct: 'План/факт',
  plan_remainder: 'Остаток до плана',
  percent_of: 'Доля',
  percent_of_auto: 'Доля (найдено по данным)',
  period_delta: 'Динамика',
  total_sum: 'Итог',
}

// Откуда столбцы: объект → папка → файл. При нескольких объектах без этого
// не понять, к какому файлу относится предложение.
function source(s: { object_name?: string | null; folder_name?: string | null; document_name?: string | null; dataset_name?: string | null }): string {
  return [s.object_name, s.folder_name, s.document_name || s.dataset_name].filter(Boolean).join(' · ')
}

// «Что можно посчитать по этим данным»: система разбирает названия столбцов
// распознанного файла и предлагает готовые показатели — по образцу разбора,
// который до этого приходилось делать вручную («есть отправленные и доставленные,
// есть план до 1 сентября — напрашиваются доля, выполнение плана и прирост»).
// Принятое предложение создаётся ЧЕРНОВИКОМ и проходит обычную проверку.
export default function DataSuggestPanel({ onCreated }: { onCreated: () => void }) {
  const [specs, setSpecs] = useState<DataSuggestion[] | null>(null)
  const [datasets, setDatasets] = useState<SuggestDataset[]>([])
  const [dsCode, setDsCode] = useState('')
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  // Куда сразу поставить карточки: список дашбордов и выбранный.
  // Раньше принятие предложения давало только черновик метрики, а виджет по
  // ней человек добавлял руками — шаг, о котором легко забыть.
  const [dashboards, setDashboards] = useState<Dashboard[]>([])
  const [placeIn, setPlaceIn] = useState('')

  function load(code: string) {
    setSpecs(null); setError(null); setDone(null)
    dataSuggestions(code || undefined)
      .then((r) => {
        setSpecs(r.specs)
        setDatasets(r.datasets)
        setPicked(new Set(r.specs.map((s) => s.code)))
      })
      .catch((e) => setError((e as Error).message))
  }
  useEffect(() => { load(dsCode) }, [dsCode])
  useEffect(() => {
    listDashboards('', false, 200).then((r) => setDashboards(r.items)).catch(() => setDashboards([]))
  }, [])

  function toggle(code: string) {
    setPicked((p) => {
      const n = new Set(p)
      if (n.has(code)) n.delete(code); else n.add(code)
      return n
    })
  }

  async function accept() {
    if (!specs) return
    setBusy(true); setError(null)
    let created = 0
    let placed = 0
    try {
      // Страницу выбираем один раз: карточки логичнее держать вместе, а место
      // на странице система подберёт для каждой отдельно — рядом с виджетом,
      // который показывает те же показатели.
      let pageId = ''
      if (placeIn) {
        const d = await getDashboard(placeIn)
        pageId = d.pages[0]?.id || ''
        if (!pageId) throw new Error('У выбранного дашборда нет ни одной страницы — создайте её и повторите')
      }
      for (const s of specs.filter((x) => picked.has(x.code))) {
        const m = await createMetric(s.code, s.name)
        await createVersion(m.id, { formula: s.formula, unit: s.unit })
        created += 1
        if (pageId) {
          await placeMetricOnDashboard({
            page_id: pageId, metric_code: s.code, name: s.name, unit: s.unit,
            based_on: s.based_on, dataset_code: s.dataset_code,
          })
          placed += 1
        }
      }
      setDone(placed
        ? `Создано черновиков: ${created}, размещено на дашборде: ${placed}. `
          + 'Карточки встали рядом с близкими по смыслу показателями — их можно переставить мышью.'
        : `Создано черновиков: ${created}. Откройте метрику, проверьте предпросмотр и отправьте на одобрение.`)
      onCreated()
      load(dsCode)
    } catch (e) {
      setError(`${(e as Error).message}${created ? ` (успели создать: ${created})` : ''}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 12, marginBottom: 16, background: 'var(--surface-2)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <b style={{ fontSize: 14 }}>Что можно посчитать по вашим данным</b>
        {datasets.length > 1 && (
          <select style={sl} value={dsCode} onChange={(e) => setDsCode(e.target.value)}
            title="Предложения строятся по столбцам выбранного файла">
            <option value="">все файлы ({datasets.length})</option>
            {datasets.map((d) => (
              <option key={d.code} value={d.code}>
                {[d.object_name, d.folder_name, d.document_name || d.name].filter(Boolean).join(' · ')}
              </option>
            ))}
          </select>
        )}
        <button type="button" onClick={() => load(dsCode)} style={ghost}>↻ Пересчитать</button>
        {specs && specs.length > 0 && dashboards.length > 0 && (
          // Подпись обязательна: без неё выпадающий список читался как фильтр,
          // и человек не догадывался, что здесь выбирается размещение.
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5,
                          color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
            Разместить:
            <select style={{ ...sl, maxWidth: 280 }} value={placeIn}
              onChange={(e) => setPlaceIn(e.target.value)}
              title="Поставить карточки сразу на дашборд — место система выберет рядом с близким по смыслу показателем">
              <option value="">не размещать, только завести</option>
              {dashboards.map((d) => <option key={d.id} value={d.id}>на дашборд «{d.name}»</option>)}
            </select>
          </label>
        )}
        {specs && specs.length > 0 && (
          <button type="button" onClick={accept} disabled={busy || picked.size === 0}
            style={{ marginLeft: 'auto', height: 32, padding: '0 14px', borderRadius: 8, border: 'none',
              cursor: 'pointer', background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 13, fontWeight: 600 }}>
            {busy ? 'Создаю…' : placeIn
              ? `Завести и разместить (${picked.size})`
              : `Добавить как черновики (${picked.size})`}
          </button>
        )}
      </div>

      {specs && specs.length > 0 && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
          Отмеченные показатели будут заведены черновиками. Если в поле «Разместить» выбрать
          дашборд, по каждому сразу появится карточка — рядом с показателем, из которого он
          считается; переставить её можно мышью.
        </div>
      )}
      {error && <div style={{ color: 'var(--danger)', fontSize: 13, marginBottom: 8 }}>{error}</div>}
      {done && <div style={{ color: 'var(--success)', fontSize: 13, marginBottom: 8 }}>{done}</div>}
      {!specs && !error && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Разбираю столбцы…</div>}
      {specs && specs.length === 0 && (
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          Всё, что система смогла предложить по этим данным, уже заведено.
        </div>
      )}

      {specs && specs.length > 0 && specs.map((s) => (
        <label key={s.code} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '6px 0',
          borderTop: '1px solid var(--border-faint)', cursor: 'pointer' }}>
          <input type="checkbox" checked={picked.has(s.code)} onChange={() => toggle(s.code)} style={{ marginTop: 3 }} />
          <span style={{ minWidth: 0 }}>
            <span style={{ fontSize: 11, padding: '1px 8px', borderRadius: 9, background: 'var(--accent-weak-bg)',
              color: 'var(--accent)', marginRight: 6 }}>{TYPE_RU[s.type] || s.type}</span>
            <span style={{ fontSize: 13 }}>{s.name}</span>
            {s.preview_value != null && (
              <span style={{ marginLeft: 6, fontSize: 12, color: 'var(--success)' }}
                title="Предложение проверено расчётом на ваших данных">
                = {fmtNumber(s.preview_value)}{s.unit ? ` ${s.unit}` : ''}
              </span>
            )}
            <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{s.why}</span>
            {source(s) && (
              <span style={{ display: 'block', fontSize: 11, color: 'var(--text-faint)', marginTop: 2 }}>📄 {source(s)}</span>
            )}
            <code style={{ display: 'block', fontSize: 11, color: 'var(--text-faint)', marginTop: 2, wordBreak: 'break-all' }}>{s.formula}</code>
          </span>
        </label>
      ))}
    </div>
  )
}

const sl: React.CSSProperties = {
  height: 32, padding: '0 8px', borderRadius: 8, border: '1px solid var(--border-strong)',
  background: 'var(--surface)', color: 'var(--text)', fontSize: 13,
}
const ghost: React.CSSProperties = {
  height: 32, padding: '0 12px', borderRadius: 8, border: '1px solid var(--border-strong)',
  background: 'var(--surface)', color: 'var(--text)', fontSize: 13, cursor: 'pointer',
}
