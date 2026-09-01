// Виджет-пикер: визуальная галерея типов виджетов с мини-превью, сгруппированная
// по 4 категориям. Заменяет прежний select «Тип» — как в Power BI/Superset.
import { overlay, dialog } from './shared'

// ── Мини-превью (лёгкие SVG-иконки, без данных) ──────────────────────────────
const C1 = '#e04e39', C2 = '#e0885f', C3 = '#c39367', GREEN = '#2f8f6b', GOLD = '#8a5a1a'
const box: React.CSSProperties = { width: 52, height: 34 }

const ICONS: Record<string, React.ReactNode> = {
  kpi: <svg style={box} viewBox="0 0 52 34"><text x="26" y="24" textAnchor="middle" fontSize="20" fontWeight="700" fill={C1}>42</text></svg>,
  kpi_group: <svg style={box} viewBox="0 0 52 34"><rect x="7" y="4" width="38" height="26" rx="3" fill="none" stroke={C1} strokeWidth="1.5" /><text x="11" y="14" fontSize="7" fill={C3}>нараст.</text><text x="41" y="14" fontSize="8" textAnchor="end" fontWeight="700" fill={C1}>1,0м</text><text x="11" y="22" fontSize="7" fill={C3}>месяц</text><text x="41" y="22" fontSize="8" textAnchor="end" fontWeight="700" fill={C1}>158к</text><text x="11" y="29" fontSize="7" fill={C3}>неделя</text><text x="41" y="29" fontSize="8" textAnchor="end" fontWeight="700" fill={GREEN}>5,3к</text></svg>,
  gauge: <svg style={box} viewBox="0 0 52 34"><path d="M8 28 A18 18 0 0 1 44 28" fill="none" stroke="#eef0f3" strokeWidth="5" /><path d="M8 28 A18 18 0 0 1 34 13" fill="none" stroke={C1} strokeWidth="5" /><line x1="26" y1="28" x2="34" y2="16" stroke={C1} strokeWidth="2" /></svg>,
  plan_fact: <svg style={box} viewBox="0 0 52 34"><rect x="8" y="8" width="8" height="20" fill={C3} /><rect x="20" y="14" width="8" height="14" fill={C1} /><rect x="6" y="30" width="40" height="3" rx="1.5" fill="#eef0f3" /><rect x="6" y="30" width="26" height="3" rx="1.5" fill={GREEN} /></svg>,
  bullet: <svg style={box} viewBox="0 0 52 34"><rect x="6" y="7" width="40" height="5" rx="2.5" fill="#eef0f3" /><rect x="6" y="7" width="30" height="5" rx="2.5" fill={GREEN} /><line x1="28" y1="5" x2="28" y2="14" stroke="#4b5563" strokeWidth="1.5" /><rect x="6" y="15" width="40" height="5" rx="2.5" fill="#eef0f3" /><rect x="6" y="15" width="16" height="5" rx="2.5" fill={C1} /><line x1="28" y1="13" x2="28" y2="22" stroke="#4b5563" strokeWidth="1.5" /><rect x="6" y="23" width="40" height="5" rx="2.5" fill="#eef0f3" /><rect x="6" y="23" width="24" height="5" rx="2.5" fill={GOLD} /><line x1="28" y1="21" x2="28" y2="30" stroke="#4b5563" strokeWidth="1.5" /></svg>,
  thermometer: <svg style={box} viewBox="0 0 52 34"><rect x="13" y="4" width="9" height="26" rx="4" fill="#eef0f3" /><rect x="13" y="14" width="9" height="16" rx="4" fill={C1} /><rect x="30" y="4" width="9" height="26" rx="4" fill="#eef0f3" /><rect x="30" y="18" width="9" height="12" rx="4" fill={C3} /><line x1="9" y1="12" x2="44" y2="12" stroke={GREEN} strokeWidth="1.5" strokeDasharray="3 2" /></svg>,
  ranked: <svg style={box} viewBox="0 0 52 34"><text x="5" y="10" fontSize="6" fill={C3}>1</text><rect x="11" y="5" width="34" height="5" rx="2.5" fill={GREEN} /><text x="5" y="18" fontSize="6" fill={C3}>2</text><rect x="11" y="13" width="24" height="5" rx="2.5" fill={GREEN} /><text x="5" y="26" fontSize="6" fill={C3}>⋮</text><rect x="11" y="21" width="12" height="5" rx="2.5" fill={GOLD} /><rect x="11" y="28" width="6" height="5" rx="2.5" fill={C1} /></svg>,
  bar: <svg style={box} viewBox="0 0 52 34"><rect x="8" y="16" width="7" height="12" fill={C1} /><rect x="19" y="8" width="7" height="20" fill={C1} /><rect x="30" y="20" width="7" height="8" fill={C1} /><rect x="41" y="12" width="7" height="16" fill={C1} /></svg>,
  line: <svg style={box} viewBox="0 0 52 34"><polyline points="8,24 18,14 28,18 40,8 46,12" fill="none" stroke={C1} strokeWidth="2.5" /></svg>,
  pie: <svg style={box} viewBox="0 0 52 34"><circle cx="26" cy="17" r="13" fill={C3} /><path d="M26 17 L26 4 A13 13 0 0 1 37 23 Z" fill={C1} /></svg>,
  dynamics: <svg style={box} viewBox="0 0 52 34"><polyline points="8,24 18,20 28,22 40,10 46,8" fill="none" stroke={C1} strokeWidth="2.5" /><circle cx="46" cy="8" r="2.5" fill={C1} /></svg>,
  yoy: <svg style={box} viewBox="0 0 52 34"><polyline points="8,26 18,24 28,25 40,18 46,17" fill="none" stroke={C3} strokeWidth="2" strokeDasharray="3 2" /><polyline points="8,20 18,15 28,17 40,8 46,6" fill="none" stroke={C1} strokeWidth="2.5" /></svg>,
  compare: <svg style={box} viewBox="0 0 52 34"><rect x="8" y="14" width="5" height="14" fill={C1} /><rect x="14" y="18" width="5" height="10" fill={C3} /><rect x="25" y="8" width="5" height="20" fill={C1} /><rect x="31" y="16" width="5" height="12" fill={C3} /></svg>,
  waterfall: <svg style={box} viewBox="0 0 52 34"><rect x="7" y="20" width="7" height="8" fill={GREEN} /><rect x="16" y="14" width="7" height="6" fill={GREEN} /><rect x="25" y="10" width="7" height="4" fill={C1} /><rect x="34" y="14" width="7" height="4" fill={GOLD} /><rect x="43" y="6" width="7" height="22" fill={C1} /></svg>,
  funnel: <svg style={box} viewBox="0 0 52 34"><rect x="8" y="6" width="36" height="6" rx="1" fill={C1} /><rect x="13" y="14" width="26" height="6" rx="1" fill={C3} /><rect x="18" y="22" width="16" height="6" rx="1" fill={GOLD} /></svg>,
  status_grid: <svg style={box} viewBox="0 0 52 34"><rect x="8" y="7" width="14" height="9" rx="2" fill={GREEN} /><rect x="26" y="7" width="14" height="9" rx="2" fill={GOLD} /><rect x="8" y="19" width="14" height="9" rx="2" fill={C1} /><rect x="26" y="19" width="14" height="9" rx="2" fill={GREEN} /></svg>,
  objects_compare: <svg style={box} viewBox="0 0 52 34"><rect x="9" y="8" width="9" height="20" fill={C1} /><rect x="22" y="14" width="9" height="14" fill={GREEN} /><rect x="35" y="18" width="9" height="10" fill={GOLD} /><line x1="6" y1="28" x2="47" y2="28" stroke="#cbd5e1" strokeWidth="1" /></svg>,
  cross_dataset_compare: <svg style={box} viewBox="0 0 52 34"><rect x="5" y="3" width="19" height="25" rx="2" fill="none" stroke={C1} strokeWidth="1.5" /><rect x="28" y="7" width="19" height="21" rx="2" fill="none" stroke={C3} strokeWidth="1.5" /><rect x="9" y="16" width="4" height="9" fill={C1} /><rect x="15" y="10" width="4" height="15" fill={C1} /><rect x="32" y="15" width="4" height="10" fill={C3} /><rect x="38" y="19" width="4" height="6" fill={C3} /></svg>,
  pivot: <svg style={box} viewBox="0 0 52 34"><rect x="8" y="5" width="36" height="24" fill="none" stroke={C1} strokeWidth="1.5" /><line x1="8" y1="12" x2="44" y2="12" stroke={C1} strokeWidth="1.5" /><line x1="8" y1="23" x2="44" y2="23" stroke={GOLD} strokeWidth="1.5" /><line x1="32" y1="5" x2="32" y2="29" stroke={GOLD} strokeWidth="1.5" /><line x1="20" y1="5" x2="20" y2="29" stroke="#cbd5e1" strokeWidth="1" /></svg>,
  heatmap: <svg style={box} viewBox="0 0 52 34">{[0, 1, 2].map(r => [0, 1, 2, 3].map(c => { const arr = ['#faf0e9', C3, C1, GOLD, C2]; return <rect key={`${r}-${c}`} x={8 + c * 9} y={4 + r * 9} width="8" height="8" fill={arr[(r * 4 + c) % arr.length]} /> }))}</svg>,
  matrix: <svg style={box} viewBox="0 0 52 34"><rect x="8" y="5" width="36" height="24" fill="none" stroke={C1} strokeWidth="1.5" /><line x1="8" y1="12" x2="44" y2="12" stroke={C1} strokeWidth="1.5" /><line x1="20" y1="5" x2="20" y2="29" stroke={C1} strokeWidth="1.5" /><line x1="29" y1="5" x2="29" y2="29" stroke="#cbd5e1" strokeWidth="1" /><line x1="38" y1="5" x2="38" y2="29" stroke="#cbd5e1" strokeWidth="1" /><line x1="8" y1="21" x2="44" y2="21" stroke="#cbd5e1" strokeWidth="1" /><polyline points="22,18 26,16" stroke={GREEN} strokeWidth="1.5" fill="none" /><polyline points="31,27 35,25" stroke={GREEN} strokeWidth="1.5" fill="none" /></svg>,
  table: <svg style={box} viewBox="0 0 52 34"><rect x="8" y="6" width="36" height="22" fill="none" stroke={C1} strokeWidth="1.5" /><line x1="8" y1="13" x2="44" y2="13" stroke={C1} strokeWidth="1.5" /><line x1="20" y1="6" x2="20" y2="28" stroke="#cbd5e1" strokeWidth="1" /><line x1="32" y1="6" x2="32" y2="28" stroke="#cbd5e1" strokeWidth="1" /><line x1="8" y1="20" x2="44" y2="20" stroke="#cbd5e1" strokeWidth="1" /></svg>,
  text: <svg style={box} viewBox="0 0 52 34"><text x="8" y="16" fontSize="13" fontWeight="700" fill={C1}>Aa</text><rect x="8" y="20" width="36" height="2.5" rx="1" fill="#cbd5e1" /><rect x="8" y="25" width="28" height="2.5" rx="1" fill="#cbd5e1" /></svg>,
  image: <svg style={box} viewBox="0 0 52 34"><rect x="8" y="6" width="36" height="22" rx="2" fill="none" stroke={C1} strokeWidth="1.5" /><circle cx="17" cy="14" r="3" fill={GOLD} /><path d="M11 26 L22 16 L30 22 L36 17 L41 26 Z" fill={C3} /></svg>,
}

type Meta = { v: string; t: string; hint: string }
type Group = { key: string; title: string; note: string; items: Meta[] }

// 4 группы — от простых показателей к оформлению.
export const WIDGET_GROUPS: Group[] = [
  {
    key: 'kpi', title: 'Показатели', note: 'одно число — быстрый акцент',
    items: [
      { v: 'kpi', t: 'KPI (число)', hint: 'Крупное значение метрики или формулы' },
      { v: 'kpi_group', t: 'Показатель в разрезах', hint: 'Один показатель во всех его разрезах одной карточкой: значение и прирост построчно' },
      { v: 'gauge', t: 'Спидометр', hint: 'Значение на шкале — % выполнения' },
      { v: 'plan_fact', t: 'План-факт', hint: 'План, факт, отклонение и % выполнения' },
      { v: 'bullet', t: 'Полосы план-факт', hint: 'Несколько показателей одной карточкой: у каждого своя полоса выполнения и отметка плана — видно, кто отстаёт' },
      { v: 'thermometer', t: 'Термометр к сроку', hint: 'Успеваем ли к дате: выполнено против прошедшего срока, сколько нужно в день и когда план будет достигнут при нынешнем темпе' },
    ],
  },
  {
    key: 'chart', title: 'Графики', note: 'сравнение и динамика',
    items: [
      { v: 'bar', t: 'Столбцы', hint: 'Значения по строкам датасета' },
      { v: 'line', t: 'Линия', hint: 'Плавная кривая по строкам' },
      { v: 'pie', t: 'Круговая', hint: 'Доли в общем объёме' },
      { v: 'dynamics', t: 'Динамика', hint: 'Ряд по периодам + прирост' },
      { v: 'yoy', t: 'Год к году', hint: 'Текущий год против прошлого по месяцам' },
      { v: 'compare', t: 'Сравнение', hint: 'Несколько полей рядом (мультисерия)' },
      { v: 'waterfall', t: 'Водопад', hint: 'Вклад строк в накопленный итог' },
      { v: 'funnel', t: 'Воронка', hint: 'Этапы процесса: сколько дошло с шага на шаг и где теряются' },
      { v: 'objects_compare', t: 'Сравнение подразделений', hint: 'Показатель по объектам/филиалам рядом' },
      { v: 'cross_dataset_compare', t: 'Сравнение источников', hint: 'Показатели из РАЗНЫХ датасетов/файлов на одном графике' },
    ],
  },
  {
    key: 'matrix', title: 'Матрицы', note: 'строки × столбцы',
    items: [
      { v: 'table', t: 'Таблица', hint: 'Первичные строки датасета' },
      { v: 'heatmap', t: 'Тепловая карта', hint: 'Матрица строки × поля цветом интенсивности' },
      { v: 'pivot', t: 'Сводная таблица', hint: 'Строки × поля с итогами по строкам/столбцам' },
      { v: 'matrix', t: 'Матрица по датам', hint: 'Строки формы × отчётные даты: значение и прирост к прошлому отчёту' },
      { v: 'status_grid', t: 'Светофор', hint: 'Плитка на каждую строку формы, цвет — по порогам' },
      { v: 'ranked', t: 'Рейтинг строк', hint: 'Кто впереди и кто в хвосте: топ и антитоп отделений полосами, с местом, долей и разрывом посередине' },
    ],
  },
  {
    key: 'annot', title: 'Оформление', note: 'без данных',
    items: [
      { v: 'text', t: 'Текст/заголовок', hint: 'Аннотация или заголовок раздела' },
      { v: 'image', t: 'Картинка/лого', hint: 'Логотип МФЦ или изображение' },
    ],
  },
]

// Плоская карта v→метаданные (для подписи выбранного типа в форме).
export const WIDGET_META: Record<string, Meta & { group: string }> = Object.fromEntries(
  WIDGET_GROUPS.flatMap((g) => g.items.map((it) => [it.v, { ...it, group: g.key }])),
)

function Card({ m, active, onPick }: { m: Meta; active: boolean; onPick: (v: string) => void }) {
  return (
    <button type="button" onClick={() => onPick(m.v)} title={m.hint}
      style={{
        display: 'flex', flexDirection: 'column', gap: 6, width: 150, textAlign: 'left',
        border: `1.5px solid ${active ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 12, padding: 10,
        background: active ? 'var(--accent-weak-bg)' : 'var(--surface)', cursor: 'pointer', boxShadow: active ? '0 0 0 3px rgba(47,84,150,0.12)' : 'none',
      }}>
      {/* Значок НАД названием, а не слева от него.
          Рядом со значком заголовку оставалось ~70px из 150, и «Сравнение
          подразделений» либо вылезало за карточку (flex-элемент без
          minWidth: 0 не может стать уже содержимого, а кнопка обрезает), либо
          рвалось посреди слова на четыре строки. Сверху заголовку достаётся
          вся ширина карточки — слова переносятся целиком.
          overflowWrap оставлен страховкой на случай ещё более длинного имени
          типа виджета: лучше перенос внутри слова, чем обрезанный текст. */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ flexShrink: 0 }}>{ICONS[m.v]}</div>
        <span style={{
          fontSize: 13, fontWeight: 600, color: 'var(--text)',
          overflowWrap: 'anywhere', lineHeight: 1.25,
        }}>{m.t}</span>
      </div>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.3 }}>{m.hint}</span>
    </button>
  )
}

// Галерея выбора типа виджета. Открывается из формы виджета.
export function WidgetPicker({ value, onPick, onClose }: { value: string; onPick: (v: string) => void; onClose: () => void }) {
  return (
    <div style={overlay} onClick={onClose}>
      <div style={{ ...dialog, width: 720 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
          <div style={{ fontSize: 17, fontWeight: 700 }}>Выберите тип виджета</div>
          <button type="button" style={closeBtn} onClick={onClose}>✕</button>
        </div>
        {WIDGET_GROUPS.map((g) => (
          <div key={g.key} style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)' }}>{g.title}</span>
              <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>{g.note}</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
              {g.items.map((m) => <Card key={m.v} m={m} active={m.v === value} onPick={(v) => { onPick(v); onClose() }} />)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const closeBtn: React.CSSProperties = { marginLeft: 'auto', width: 28, height: 28, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--surface)', cursor: 'pointer', color: 'var(--text-muted)' }
