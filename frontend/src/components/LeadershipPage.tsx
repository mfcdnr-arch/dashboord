import { useEffect, useState } from 'react'
import { listFeatured, type FeaturedDashboard } from '../api'
import { fmtNumber } from '../lib/format'
import FeaturedPicker from './leadership/FeaturedPicker'

/**
 * Раздел «Руководителю» — подборка дашбордов с описаниями.
 *
 * Зачем отдельный раздел. Общий список дашбордов устроен для того, кто их
 * СОБИРАЕТ: поиск по названию, фильтр по папке, диапазон дат изменения,
 * статус публикации, число страниц. Руководителю всё это не нужно — ему нужно
 * понять, какой отчёт про что, и открыть его. Имени для этого мало: «Внедрение
 * сервиса МАХ — еженедельный доклад» не отвечает, что внутри.
 *
 * Состав подборки задаёт администратор галочкой в общем списке; КТО что видит,
 * решают обычные гранты доступа — второй системы прав здесь нет.
 */
export default function LeadershipPage(
  { canManage, onOpen }: { canManage: boolean; onOpen: (id: string) => void },
) {
  const [items, setItems] = useState<FeaturedDashboard[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [picker, setPicker] = useState(false)

  const load = () => listFeatured().then((r) => setItems(r.items))
    .catch((e) => setError((e as Error).message))
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 20, margin: '0 0 4px' }}>Руководителю</h2>
        {/* Состав подборки настраивается здесь же: собирать её, вспоминая
            нужные отчёты в общем списке дашбордов, неудобно — там свои
            фильтры и свои задачи. */}
        {canManage && (
          <button style={setupBtn} onClick={() => setPicker(true)}>⚙ Настроить подборку</button>
        )}
      </div>
      <div style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 16 }}>
        Отчёты, отобранные для руководства. Показаны только те, к которым у вас есть доступ.
      </div>
      {picker && <FeaturedPicker onClose={() => setPicker(false)} onSaved={load} />}

      {error && <div style={errBox}>{error}</div>}
      {!items && !error && <div style={{ color: 'var(--text-muted)' }}>Загрузка…</div>}

      {items && items.length === 0 && (
        <div style={empty}>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>Подборка пока пуста</div>
          <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.5 }}>
            {canManage
              ? 'Откройте раздел «Дашборды» и отметьте нужные отчёты значком ★ «в подборку руководителю». '
                + 'Там же можно дать дашборду описание — оно появится здесь под названием.'
              : 'Отчёты сюда добавляет администратор. Как только он это сделает и откроет вам доступ, они появятся на этой странице.'}
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))' }}>
        {(items || []).map((d) => (
          <button key={d.id} style={card} onClick={() => onOpen(d.id)}
            title="Открыть отчёт">
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <div style={{ fontSize: 15, fontWeight: 600, flex: 1, minWidth: 0 }}>{d.name}</div>
              {/* Черновик в подборке возможен: он виден только тому, у кого и так
                  есть к нему доступ. Но смолчать об этом нельзя — руководитель
                  должен знать, что смотрит на неутверждённое. */}
              {d.publication_status !== 'published' && (
                <span style={draftBadge} title="Отчёт ещё не опубликован — цифры могут измениться">черновик</span>
              )}
            </div>
            {/* Описание — главное, ради чего сделан раздел: по имени отчёта не
                понять, что внутри. Если админ его не задал, честно говорим об
                этом, а не показываем пустоту. */}
            <div style={{ fontSize: 13, color: d.description ? 'var(--text-2)' : 'var(--text-faint)',
                          marginTop: 6, lineHeight: 1.45 }}>
              {d.description || 'Описание не задано — попросите администратора добавить, что показывает этот отчёт.'}
            </div>
            {/* Главные цифры прямо на плитке. Без них руководителю приходится
                открывать каждый отчёт, чтобы понять, куда смотреть, — а раздел
                задуман как ответ «как дела» с одного взгляда. Прирост показан
                рядом со значением: голое число не говорит, хорошо это или
                плохо. */}
            {d.highlights && d.highlights.length > 0 && (
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 12 }}>
                {d.highlights.map((h, i) => (
                  <div key={i} style={{
                    flex: '1 1 140px', minWidth: 0, padding: '8px 10px', borderRadius: 10,
                    background: h.alert === 'danger' ? 'var(--danger-bg)'
                      : h.alert === 'warn' ? 'var(--warn-bg)' : 'var(--surface-2)',
                  }}>
                    <div style={{ fontSize: 20, fontWeight: 700, whiteSpace: 'nowrap',
                      color: h.alert === 'danger' ? 'var(--danger)'
                        : h.alert === 'warn' ? 'var(--warn)' : 'var(--accent)' }}>
                      {h.value == null ? '—' : fmtNumber(h.value)}
                      {h.unit ? <span style={{ fontSize: 13 }}> {h.unit}</span> : null}
                    </div>
                    {(h.delta_pct != null || h.plan_pct != null) && (
                      <div style={{ fontSize: 12, marginTop: 1,
                        color: (h.delta_pct ?? 0) > 0 ? 'var(--success)'
                          : (h.delta_pct ?? 0) < 0 ? 'var(--danger)' : 'var(--text-muted)' }}>
                        {h.delta_pct != null
                          ? `${h.delta_pct > 0 ? '▲ +' : h.delta_pct < 0 ? '▼ ' : ''}${fmtNumber(h.delta_pct)}% к прошлому`
                          : `план выполнен на ${fmtNumber(h.plan_pct as number)}%`}
                      </div>
                    )}
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={h.name}>
                      {h.name}
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 10 }}>
              {[d.object_name, d.folder_name].filter(Boolean).join(' · ') || 'без папки'}
              {' · '}{d.pages} {pagePlural(d.pages)}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

function pagePlural(n: number): string {
  const t = n % 100
  if (t >= 11 && t <= 14) return 'страниц'
  switch (n % 10) {
    case 1: return 'страница'
    case 2: case 3: case 4: return 'страницы'
    default: return 'страниц'
  }
}

const setupBtn: React.CSSProperties = {
  height: 30, padding: '0 12px', borderRadius: 8, fontSize: 13, cursor: 'pointer',
  border: '1px solid var(--border-strong)', background: 'var(--surface)', color: 'var(--text-2)',
}
const card: React.CSSProperties = {
  textAlign: 'left', background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 12, padding: '14px 16px', cursor: 'pointer', font: 'inherit', color: 'inherit',
}
const empty: React.CSSProperties = {
  border: '1px dashed var(--border-strong)', borderRadius: 12, padding: '18px 20px',
  maxWidth: 640, marginBottom: 16,
}
const draftBadge: React.CSSProperties = {
  fontSize: 11, color: 'var(--warn)', border: '1px solid var(--warn)', borderRadius: 10,
  padding: '1px 7px', flexShrink: 0,
}
const errBox: React.CSSProperties = {
  background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 13,
  padding: '8px 10px', borderRadius: 8, marginBottom: 12,
}
