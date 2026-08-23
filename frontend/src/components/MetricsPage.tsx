import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  approveVersion, createMetric, createVersion, deleteMetric, getDataSources, getMetric, listMetrics, metricInfoDraft,
  previewFormula, updateMetric, validateVersion, versionValue,
  type DataSources, type Dependencies, type Metric, type MetricVersion,
  metricValues, type MetricValue,
  metricsPending, metricsBulkStatus, type PendingVersion,
  listUsers, type AppUser,
} from '../api'
import FormulaBuilder from './FormulaBuilder'
import { ConfirmDialog } from './dashboards/ConfirmDialog'
import { PlaceMetricsDialog } from './metrics/PlaceMetricsDialog'
import TemplatePicker from './metrics/TemplatePicker'
import DataSuggestPanel from './metrics/DataSuggestPanel'
import { fmtNumber as fmtNum } from '../lib/format'

const FORMULA_HELP = [
  "SUM(field('план','кол'))",
  "PERCENT_OF(SUM(field('всего','кол')), SUM(field('часть','кол')))",
  "PLAN_FACT_PCT(SUM(field('план','кол')), SUM(field('факт','кол')))",
  "cell('нагрузка', date='2026-07-10', row='Паспорт РФ', col='Принято')",
  "metric('итого_план') / metric('план_год') * 100",
]

const METRICS_PAGE = 50

export default function MetricsPage({ canManage, isSuperadmin }: { canManage: boolean; isSuperadmin?: boolean }) {
  const [metrics, setMetrics] = useState<Metric[]>([])
  // Что каждый показатель считает прямо сейчас. Раньше это можно было узнать,
  // только открыв показатель и нажав предпросмотр: при полутора десятках
  // показателей — полтора десятка заходов, а сломанная формула вообще ничем
  // себя не выдавала.
  const [values, setValues] = useState<Record<string, MetricValue>>({})
  // Массовая проверка/одобрение: показатели заводятся пачками (мастер и
  // предложения по данным создают их десятками), и десять одинаковых нажатий —
  // это ровно та ручная работа, от которой уходим.
  const [bulk, setBulk] = useState<{ target: 'validated' | 'approved'; items: PendingVersion[] } | null>(null)
  const [bulkNote, setBulkNote] = useState<string | null>(null)
  // Разместить уже заведённые показатели на дашборде: до этого их можно
  // было вывести только добавляя виджеты по одному руками.
  const [placeOpen, setPlaceOpen] = useState(false)
  const [metricsTotal, setMetricsTotal] = useState(0)
  const [mq, setMq] = useState('')
  const [sel, setSel] = useState<{ metric: Metric; versions: MetricVersion[] } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  const fail = (e: unknown) => setError((e as Error).message)
  // Защита от гонки ответов: применяем только результат последнего запроса.
  const reqSeq = useRef(0)
  const loadMetrics = (query: string) => {
    const seq = ++reqSeq.current
    return listMetrics(query, METRICS_PAGE, 0)
      .then((p) => { if (seq === reqSeq.current) { setMetrics(p.items); setMetricsTotal(p.total) } }).catch(fail)
  }
  const refresh = () => loadMetrics(mq)
  async function loadMoreMetrics() {
    const seq = ++reqSeq.current
    try { const p = await listMetrics(mq, METRICS_PAGE, metrics.length); if (seq === reqSeq.current) { setMetrics((prev) => [...prev, ...p.items]); setMetricsTotal(p.total) } } catch (e) { fail(e) }
  }

  // Список — по поиску с дебаунсом (он же начальная загрузка).
  useEffect(() => { const t = setTimeout(() => loadMetrics(mq), 250); return () => clearTimeout(t) }, [mq]) // eslint-disable-line react-hooks/exhaustive-deps
  // Значения — отдельным запросом: расчёт формул дороже выборки списка, и
  // список не должен ждать его, чтобы показаться.
  async function openBulk(target: 'validated' | 'approved') {
    setBulkNote(null)
    try {
      const r = await metricsPending(target)
      if (!r.items.length) {
        setBulkNote(target === 'validated'
          ? 'Черновиков нет — проверять нечего.'
          : 'Проверенных версий нет. Сначала «Проверить все черновики».')
        return
      }
      setBulk({ target, items: r.items })
    } catch (e) { setError((e as Error).message) }
  }

  async function runBulk() {
    if (!bulk) return
    setBusy(true); setError(null)
    try {
      const r = await metricsBulkStatus(bulk.items.map((i) => i.version_id), bulk.target)
      setBulk(null)
      // Отказы называем поимённо: чаще всего это «нельзя одобрять свою версию»,
      // и человек должен понимать, почему часть показателей осталась как была.
      setBulkNote(r.skipped
        ? `Готово: ${r.ok}. Не удалось: ${r.skipped} — ${r.failed[0]?.error || ''}`
        : `Готово: ${r.ok}.`)
      await loadMetrics(mq)
      await loadValues()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const loadValues = () => metricValues()
    .then((r) => setValues(Object.fromEntries(r.items.map((v) => [v.code, v]))))
    .catch(() => setValues({}))
  useEffect(() => { loadValues() }, [])

  async function openMetric(id: string) {
    setError(null)
    try { setSel(await getMetric(id)) } catch (e) { fail(e) }
  }

  async function addMetric(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const m = await createMetric(code.trim(), name.trim())
      setCode(''); setName('')
      await refresh()
      openMetric(m.id)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, marginBottom: 16 }}>
        <button style={crumb} onClick={() => setSel(null)}>Метрики</button>
        {sel && <><span style={{ color: 'var(--text-faint)' }}>/</span><span>{sel.metric.name}</span></>}
      </div>

      {error && <div style={errBox}>{error}</div>}

      {placeOpen && (
        <PlaceMetricsDialog
          metrics={metrics.map((m) => values[m.code] || {
            code: m.code, name: m.name, status: m.best_status || null,
            value: null, unit: m.unit || null, error: null,
          })}
          onClose={() => setPlaceOpen(false)}
          onDone={(placed) => {
            setPlaceOpen(false)
            setBulkNote(placed
              ? `Размещено карточек: ${placed}. Откройте дашборд — они встали рядом с близкими показателями.`
              : 'Ничего не размещено.')
          }}
        />
      )}

      {bulk && (
        <ConfirmDialog
          title={bulk.target === 'validated'
            ? `Проверить черновиков: ${bulk.items.length}?`
            : `Одобрить проверенных версий: ${bulk.items.length}?`}
          message={
            (bulk.target === 'approved'
              ? 'Одобрение — это подтверждение, что формула считает верно. Свои версии система пропустит: '
                + 'одобрять собственную работу нельзя (кроме суперадминистратора).\n\n'
              : 'Проверка переводит черновик в состояние «проверена» — дальше его одобряет другой сотрудник.\n\n')
            + bulk.items.slice(0, 12).map((i) => `• ${i.name}`).join('\n')
            + (bulk.items.length > 12 ? `\n…и ещё ${bulk.items.length - 12}` : '')
          }
          confirmLabel={bulk.target === 'validated' ? 'Проверить' : 'Одобрить'}
          busyLabel="Выполняем…"
          tone="accent"
          busy={busy}
          onClose={() => setBulk(null)}
          onConfirm={runBulk}
        />
      )}

      {!sel && (
        <div>
          {canManage && <DataSuggestPanel onCreated={refresh} />}
          {canManage && (
            <form onSubmit={addMetric} style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
              <input style={{ ...input, width: 160 }} placeholder="код (латиницей)" value={code} onChange={(e) => setCode(e.target.value)} />
              <input style={{ ...input, width: 240 }} placeholder="Название метрики" value={name} onChange={(e) => setName(e.target.value)} />
              <button style={btn} disabled={busy || !code.trim() || !name.trim()}>＋ Метрика</button>
            </form>
          )}
          {canManage && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
              <button type="button" style={{ ...btnGhostSm }}
                title="Отметить черновики как проверенные — по списку, который покажем перед этим"
                onClick={() => openBulk('validated')}>✓ Проверить все черновики</button>
              <button type="button" style={{ ...btnGhostSm }}
                title="Одобрить проверенные версии. Свою версию одобрить нельзя — это разделение обязанностей"
                onClick={() => openBulk('approved')}>✓✓ Одобрить все проверенные</button>
              <button type="button" style={{ ...btnGhostSm, borderColor: 'var(--accent)', color: 'var(--accent)' }}
                title="Вывести показатели на дашборд карточками — рядом с тем, из чего они считаются"
                onClick={() => setPlaceOpen(true)}>📊 Разместить на дашборде</button>
              {bulkNote && <span style={{ fontSize: 12.5, color: 'var(--text-2)' }}>{bulkNote}</span>}
            </div>
          )}
          <input style={{ ...input, width: '100%', maxWidth: 420, marginBottom: 12 }} placeholder="🔍 Поиск по коду или названию…" value={mq} onChange={(e) => setMq(e.target.value)} />
          {metrics.length === 0 ? (
            <div style={muted}>{mq.trim() ? 'Ничего не найдено.' : 'Пока нет метрик. Создайте первую и задайте ей формулу.'}</div>
          ) : (
            <div style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
              {metrics.map((m, i) => (
                <div key={m.id} onClick={() => openMetric(m.id)} style={{ ...rowItem, borderTop: i ? '1px solid var(--border-faint)' : 'none' }}>
                  {/* Имя показателя длинное (составное имя госформы), поэтому
                      колонке нужен minWidth: 0 — без него flex-элемент не может
                      стать уже содержимого, имя распирает строку и наезжает на
                      значение, а статус уезжает за край. */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, overflowWrap: 'anywhere' }}>{m.name}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-faint)', overflowWrap: 'anywhere' }}>{m.code}</div>
                  </div>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
                    justifyContent: 'flex-end', textAlign: 'right',
                  }}>
                    <MetricNow v={values[m.code]} unit={m.unit} />
                    <span style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                      версий: {m.versions ?? 0}
                    </span>
                    <StatusBadge status={m.best_status || (m.has_approved ? 'approved' : 'draft')} />
                  </div>
                </div>
              ))}
            </div>
          )}
          {metrics.length < metricsTotal && (
            <div style={{ textAlign: 'center', marginTop: 12 }}>
              <button style={{ ...btn, background: 'var(--accent-weak-bg)', color: 'var(--accent)' }} onClick={loadMoreMetrics}>
                Показать ещё ({metricsTotal - metrics.length})
              </button>
            </div>
          )}
        </div>
      )}

      {sel && (
        <MetricDetail
          data={sel} canManage={canManage} isSuperadmin={isSuperadmin}
          onError={fail}
          onChanged={async () => { await refresh(); openMetric(sel.metric.id) }}
          onDeleted={async () => { setSel(null); await refresh() }}
        />
      )}
    </div>
  )
}

function MetricDetail({ data, canManage, isSuperadmin, onError, onChanged, onDeleted }: {
  data: { metric: Metric; versions: MetricVersion[] }
  canManage: boolean
  isSuperadmin?: boolean
  onError: (e: unknown) => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const { metric, versions } = data
  const [formula, setFormula] = useState('')
  const [unit, setUnit] = useState('')
  const [mode, setMode] = useState<'ready' | 'visual' | 'text'>('ready')
  const [sources, setSources] = useState<DataSources | null>(null)
  const [preview, setPreview] = useState<{ value: number; deps: Dependencies } | null>(null)
  const [previewErr, setPreviewErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [askDelete, setAskDelete] = useState(false)
  const [values, setValues] = useState<Record<string, string>>({})
  const [info, setInfo] = useState(metric.info_text || '')
  const [infoBusy, setInfoBusy] = useState(false)
  const [infoSaved, setInfoSaved] = useState(false)
  // Ответственный за показатель (п. 11). Поле есть в БД с самого начала, но в
  // интерфейсе не показывалось нигде — а по ТЗ у каждого KPI должен быть
  // человек, с которого спрашивают. Список сотрудников грузим только тем, кто
  // вправе менять показатель: зрителю он не нужен и права на него нет.
  const [staff, setStaff] = useState<AppUser[]>([])
  const [owner, setOwner] = useState<string>(metric.owner_id || '')
  const [ownerBusy, setOwnerBusy] = useState(false)
  useEffect(() => { setOwner(metric.owner_id || '') }, [metric.id, metric.owner_id])
  useEffect(() => {
    if (!canManage) return
    listUsers('', 200, 0).then((p) => setStaff(p.items)).catch(() => setStaff([]))
  }, [canManage])

  async function saveOwner(next: string) {
    setOwner(next); setOwnerBusy(true)
    try {
      // Пустая строка — осознанное «снять ответственного» (человек уволился,
      // показатель передают), поэтому шлём именно null, а не пропускаем поле.
      await updateMetric(metric.id, { owner_id: next || null })
      onChanged()
    } catch (e) { onError(e) } finally { setOwnerBusy(false) }
  }

  useEffect(() => { getDataSources().then(setSources).catch(() => setSources({ datasets: [], metrics: [] })) }, [])

  // Если описание показателя ещё не заполнено — подставляем черновик, собранный
  // системой из формулы, источников и состояния версии. В БД он НЕ пишется:
  // модератор правит текст и сохраняет сам, поэтому «Информации нет» перестаёт
  // быть нормой, но и выдумок за модератора не появляется.
  const [infoAuto, setInfoAuto] = useState(false)
  useEffect(() => {
    if (metric.info_text) return
    metricInfoDraft(metric.id)
      .then((r) => { setInfo((cur) => (cur ? cur : r.draft)); setInfoAuto(true) })
      .catch(() => {}) // нет версии формулы — описывать пока нечего
  }, [metric.id, metric.info_text])

  async function saveInfo() {
    setInfoBusy(true); setInfoSaved(false)
    try { await updateMetric(metric.id, { info_text: info }); setInfoSaved(true) }
    catch (e) { onError(e) } finally { setInfoBusy(false) }
  }

  async function doPreview() {
    setPreview(null); setPreviewErr(null); setBusy(true)
    try {
      const r = await previewFormula(formula)
      setPreview({ value: r.value, deps: r.dependencies })
    } catch (e) { setPreviewErr((e as Error).message) } finally { setBusy(false) }
  }

  async function saveVersion() {
    setBusy(true)
    try {
      await createVersion(metric.id, { formula: formula.trim(), unit: unit.trim() || null })
      setFormula(''); setUnit(''); setPreview(null); setPreviewErr(null)
      onChanged()
    } catch (e) { onError(e) } finally { setBusy(false) }
  }

  async function act(fn: () => Promise<void>) {
    setBusy(true)
    try { await fn(); onChanged() } catch (e) { onError(e) } finally { setBusy(false) }
  }

  async function removeMetric() {
    setBusy(true)
    try { await deleteMetric(data.metric.id); setAskDelete(false); onDeleted() }
    catch (e) { setAskDelete(false); onError(e) } finally { setBusy(false) }
  }

  // Что именно исчезнет: у показателя может быть несколько версий формулы,
  // и одобренная среди них — не редкость, об этом надо предупредить прямо.
  const versCount = data.versions.length
  const hasApproved = data.versions.some((v) => v.status === 'approved')
  const deleteWarning = (versCount
    ? `Вместе с ним удалятся версии формулы (${versCount})${hasApproved ? ', включая ОДОБРЕННУЮ' : ''}.`
    : 'Версий формулы у него нет.')
    + '\n\nЕсли на показатель ссылаются виджеты или формулы других показателей, система откажет и назовёт их.'

  async function computeValue(v: MetricVersion) {
    try {
      const r = await versionValue(v.id)
      setValues((s) => ({ ...s, [v.id]: `${fmtNum(r.value)}${r.unit ? ' ' + r.unit : ''}` }))
    } catch (e) { setValues((s) => ({ ...s, [v.id]: 'ошибка: ' + (e as Error).message })) }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <h2 style={{ fontSize: 17, margin: '0 0 2px' }}>{metric.name}</h2>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>{metric.code}{metric.description ? ' · ' + metric.description : ''}</div>
          {/* Ответственный — рядом с именем показателя, а не в глубине карточки:
              это первое, что спрашивают, когда с цифрой что-то не так. */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>👤 Ответственный:</span>
            {canManage ? (
              <select style={{ ...input, height: 30, fontSize: 13, minWidth: 220 }} value={owner} disabled={ownerBusy}
                onChange={(e) => saveOwner(e.target.value)}
                title="Кому адресуются жалобы на эту цифру («⚑ проблема» на виджете)">
                <option value="">не назначен</option>
                {staff.map((u) => (
                  <option key={u.id} value={u.id}>{u.full_name || u.login}</option>
                ))}
              </select>
            ) : (
              <span style={{ fontSize: 13 }}>{metric.owner_name || 'не назначен'}</span>
            )}
            {canManage && !owner && (
              <span style={{ fontSize: 11.5, color: 'var(--warn)' }}
                title="Пока ответственного нет, жалобы на эту цифру уходят в общую очередь">
                ⚠ жалобы уйдут в общую очередь
              </span>
            )}
          </div>
        </div>
        {isSuperadmin && (
          <button style={btnDanger} disabled={busy} onClick={() => setAskDelete(true)}
            title="Удалить показатель вместе с версиями формулы. Доступно только суперадминистратору">🗑 Удалить</button>
        )}
      </div>

      {askDelete && (
        <ConfirmDialog
          title={`Удалить показатель «${metric.name}»?`}
          message={deleteWarning}
          busy={busy}
          onClose={() => setAskDelete(false)}
          onConfirm={removeMetric}
        />
      )}

      {/* Расширенная информация (FR-5.9): показывается пользователю при «провале» в показатель (drill) */}
      {canManage && (
        <div style={{ marginBottom: 18 }}>
          <h3 style={h3}>Расширенная информация о показателе</h3>
          <div style={{ ...muted, marginBottom: 6 }}>Необязательно. Виден пользователю в «🔍 подробнее». Если пусто — покажется «Информации нет, в разработке».</div>
          <textarea style={{ width: '100%', minHeight: 70, padding: 8, border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 13, fontFamily: 'inherit', resize: 'vertical' }}
            value={info} onChange={(e) => { setInfo(e.target.value); setInfoSaved(false) }}
            placeholder="Из чего складывается показатель, как читать, за что отвечает…" />
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6, flexWrap: 'wrap' }}>
            <button style={btnSm} disabled={infoBusy} onClick={saveInfo}>{infoBusy ? 'Сохранение…' : 'Сохранить информацию'}</button>
            <button style={btnSm} disabled={infoBusy} title="Собрать описание заново из формулы и источников"
              onClick={() => metricInfoDraft(metric.id).then((r) => { setInfo(r.draft); setInfoAuto(true); setInfoSaved(false) }).catch(onError)}>
              ✨ Заполнить автоматически
            </button>
            {infoSaved && <span style={{ fontSize: 12, color: 'var(--success)' }}>✓ сохранено</span>}
            {infoAuto && !infoSaved && (
              <span style={{ fontSize: 12, color: 'var(--warn)' }}>
                текст подготовлен системой — проверьте, дополните и сохраните
              </span>
            )}
          </div>
        </div>
      )}

      <h3 style={h3}>Версии формулы</h3>
      {versions.length === 0 ? (
        <div style={muted}>Пока нет ни одной версии формулы.</div>
      ) : (
        <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
          {versions.map((v, i) => (
            <div key={v.id} style={{ padding: '10px 14px', borderTop: i ? '1px solid var(--border-faint)' : 'none' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>v{v.version_no}</span>
                <StatusBadge status={v.status} />
                {v.unit && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{v.unit}</span>}
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                  <button style={btnGhostSm} onClick={() => computeValue(v)}>Значение</button>
                  {canManage && v.status === 'draft' && <button style={btnSm} disabled={busy} onClick={() => act(() => validateVersion(v.id))}>Проверить</button>}
                  {canManage && v.status === 'validated' && <button style={btnSm} disabled={busy} onClick={() => act(() => approveVersion(v.id))}>Одобрить</button>}
                </div>
              </div>
              <div style={mono}>{v.formula_expression}</div>
              {values[v.id] && <div style={{ fontSize: 13, color: 'var(--success)', marginTop: 4 }}>= {values[v.id]}</div>}
            </div>
          ))}
        </div>
      )}

      {canManage && (
        <div style={{ marginTop: 20 }}>
          <h3 style={h3}>Новая версия формулы</h3>
          <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
            <button style={{ ...modeBtn, ...(mode === 'ready' ? modeBtnActive : {}) }} onClick={() => setMode('ready')}>📚 Готовые</button>
            <button style={{ ...modeBtn, ...(mode === 'visual' ? modeBtnActive : {}) }} onClick={() => setMode('visual')}>🖱 Конструктор</button>
            <button style={{ ...modeBtn, ...(mode === 'text' ? modeBtnActive : {}) }} onClick={() => setMode('text')}>⌨ Текст</button>
          </div>

          {mode === 'ready' ? (
            <div>
              <TemplatePicker sources={sources} onApply={(f, u) => { setFormula(f); if (u) setUnit(u); setMode('text') }} />
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)' }}>
                Получится формула: <code style={mono2}>{formula || '—'}</code>
              </div>
            </div>
          ) : mode === 'visual' ? (
            <div>
              {sources
                ? <FormulaBuilder sources={sources} onFormula={setFormula} />
                : <div style={muted}>Загрузка данных для выбора…</div>}
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)' }}>
                Получится формула: <code style={mono2}>{formula || '—'}</code>
              </div>
            </div>
          ) : (
            <div>
              <textarea
                style={{ ...input, width: '100%', height: 70, fontFamily: 'ui-monospace, monospace', padding: 10, resize: 'vertical' }}
                placeholder="Например: SUM(field('план','кол'))"
                value={formula} onChange={(e) => setFormula(e.target.value)}
              />
              <div style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 4 }}>
                Пишите как в Excel: данные — <code>field('датасет','поле')</code>, действия — <code>+ − * /</code>,
                свёртка — <code>SUM(…)</code>. Проверяйте кнопкой «Предпросмотр». Справочник ниже 👇
              </div>
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
            <input style={{ ...input, width: 120 }} placeholder="ед. (шт, ₽, %)" value={unit} onChange={(e) => setUnit(e.target.value)} />
            <button style={btnGhost} disabled={busy || !formula.trim()} onClick={doPreview}>Предпросмотр</button>
            <button style={btn} disabled={busy || !formula.trim()} onClick={saveVersion}>Сохранить версию</button>
          </div>

          {preview && (
            <div style={{ ...okBox, marginTop: 10 }}>
              <strong>Предпросмотр: {fmtNum(preview.value)}{unit ? ' ' + unit : ''}</strong>
              <div style={{ fontSize: 12, color: 'var(--success)', marginTop: 2 }}>
                зависит от: {[...preview.deps.datasets.map((d) => `датасет «${d}»`), ...preview.deps.metrics.map((m) => `метрика «${m}»`)].join(', ') || '—'}
              </div>
            </div>
          )}
          {previewErr && <div style={{ ...errBox, marginTop: 10 }}>{previewErr}</div>}

          <details style={{ marginTop: 12 }}>
            <summary style={{ fontSize: 13, color: 'var(--accent)', cursor: 'pointer' }}>📘 Справочник по формулам</summary>
            <div style={helpBox}>
              <div style={helpH}>Данные — откуда берутся числа</div>
              <ul style={helpUl}>
                <li><code>{"field('датасет','поле')"}</code> — весь столбец из выпуска датасета</li>
                <li><code>{"cell('датасет', date='2026-07-10', row='Паспорт РФ', col='принято')"}</code> — одна ячейка за дату (строка по названию)</li>
                <li><code>{"metric('код')"}</code> — значение другой метрики</li>
              </ul>
              <div style={helpH}>Действия</div>
              <div style={{ marginBottom: 4 }}><code>+ − * / ^ ( )</code> — как в Excel (сначала <code>^</code>, потом <code>* /</code>, потом <code>+ −</code>)</div>
              <div style={helpH}>Функции</div>
              <ul style={helpUl}>
                <li><code>SUM / AVG / COUNT / MIN / MAX(field(…))</code> — свернуть столбец в одно число</li>
                <li><code>PLAN_FACT_DELTA(план, факт)</code> — отклонение; <code>PLAN_FACT_PCT(план, факт)</code> — % выполнения плана</li>
                <li><code>PERCENT_OF(база, значение)</code> — процент: база = 100%, ищем % значения от базы (значение ÷ база × 100)</li>
                <li>фильтр строки: <code>{"SUM(field('план','кол'), filter={'услуга'='Паспорт'})"}</code></li>
              </ul>
              <div style={helpH}>Примеры — нажмите, чтобы подставить</div>
              <ul style={helpUl}>
                {FORMULA_HELP.map((f) => (
                  <li key={f}><code style={{ cursor: 'pointer', color: 'var(--accent)' }} onClick={() => setFormula(f)}>{f}</code></li>
                ))}
              </ul>
              <div style={{ marginTop: 6, color: 'var(--text-faint)' }}>
                Совет: всегда жмите «Предпросмотр» — он посчитает результат и покажет зависимости.
                Полная инструкция — <code>docs/Инструкция_по_формулам.md</code>.
              </div>
            </div>
          </details>
        </div>
      )}
    </div>
  )
}

/**
 * Что показатель считает прямо сейчас.
 *
 * Значение важнее статуса: по списку сразу видно и текущую цифру, и то, что
 * формула сломалась. Ошибку показываем словами — сломанный показатель, молча
 * стоящий в списке как обычный, обнаруживается только на дашборде и в самый
 * неподходящий момент.
 */
function MetricNow({ v, unit }: { v?: MetricValue; unit?: string | null }) {
  if (!v) return <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>…</span>
  if (v.error) {
    return (
      <span style={{ fontSize: 12, color: 'var(--danger)', maxWidth: 260, textAlign: 'right' }}
        title={v.error}>⚠ не считается</span>
    )
  }
  const num = v.value == null ? '—' : v.value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
  return (
    <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent)', whiteSpace: 'nowrap' }}
      title="Значение по лучшей версии формулы на текущих данных">
      {num}{(v.unit || unit) ? ` ${v.unit || unit}` : ''}
    </span>
  )
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { t: string; bg: string; c: string }> = {
    draft: { t: 'черновик', bg: 'var(--surface-3)', c: 'var(--text-muted)' },
    validated: { t: 'проверена', bg: 'var(--warn-bg)', c: 'var(--warn)' },
    approved: { t: 'одобрена', bg: 'var(--success-bg)', c: 'var(--success)' },
    deprecated: { t: 'устарела', bg: 'var(--danger-bg)', c: 'var(--danger)' },
    archived: { t: 'в архиве', bg: 'var(--surface-3)', c: 'var(--text-faint)' },
  }
  const s = map[status] || map.draft
  return <span style={{ ...pill, background: s.bg, color: s.c }}>{s.t}</span>
}


const crumb: React.CSSProperties = { border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 14, padding: 0 }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 14 }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 14, cursor: 'pointer' }
const btnGhost: React.CSSProperties = { height: 36, padding: '0 14px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', fontSize: 14, cursor: 'pointer' }
const btnSm: React.CSSProperties = { height: 28, padding: '0 10px', border: 'none', borderRadius: 6, background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 12, cursor: 'pointer' }
const btnDanger: React.CSSProperties = { height: 30, padding: '0 12px', border: '1px solid var(--danger)', borderRadius: 8, background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, fontWeight: 600, cursor: 'pointer', flexShrink: 0, whiteSpace: 'nowrap' }
const btnGhostSm: React.CSSProperties = { height: 28, padding: '0 10px', border: '1px solid var(--border-strong)', borderRadius: 6, background: 'var(--surface)', fontSize: 12, cursor: 'pointer' }
const rowItem: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12,
  padding: '10px 14px', cursor: 'pointer',
}
const pill: React.CSSProperties = { fontSize: 11, padding: '2px 8px', borderRadius: 10, whiteSpace: 'nowrap' }
const h3: React.CSSProperties = { fontSize: 14, margin: '0 0 8px' }
const mono: React.CSSProperties = { fontFamily: 'ui-monospace, monospace', fontSize: 13, color: 'var(--text)', background: 'var(--surface-2)', padding: '6px 8px', borderRadius: 6, overflowX: 'auto' }
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 14 }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const okBox: React.CSSProperties = { background: 'var(--success-bg)', color: 'var(--success)', fontSize: 14, padding: '10px 12px', borderRadius: 8, border: '1px solid var(--success-bg)' }
const helpBox: React.CSSProperties = { fontSize: 12.5, color: 'var(--text-2)', marginTop: 8, padding: '10px 12px', background: 'var(--surface-2)', border: '1px solid var(--border-faint)', borderRadius: 8, lineHeight: 1.5 }
const helpH: React.CSSProperties = { fontWeight: 600, color: 'var(--accent)', marginTop: 8, marginBottom: 2 }
const helpUl: React.CSSProperties = { margin: '2px 0 0', paddingLeft: 18 }
const modeBtn: React.CSSProperties = { height: 32, padding: '0 12px', border: '1px solid var(--border-strong)', borderRadius: 8, background: 'var(--surface)', cursor: 'pointer', fontSize: 13 }
const modeBtnActive: React.CSSProperties = { background: 'var(--accent-weak-bg)', border: '1px solid var(--accent)', color: 'var(--accent)' }
const mono2: React.CSSProperties = { fontFamily: 'ui-monospace, monospace', background: 'var(--surface-2)', padding: '2px 6px', borderRadius: 6, color: 'var(--text)' }
