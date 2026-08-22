// Полоса «Недавно смотрели» над списком отчётов (п. 10 списка предложений).
//
// Избранное отвечает на вопрос «что мне нужно всегда», а этот — «где я был
// вчера»: у модератора отчётов десятки, и после недели работы вернуться к
// вчерашнему можно было только вспомнив его название и найдя в списке.
// Просмотры берутся из журнала (`audit_log`, action=view) — того же, по
// которому считается популярность; второго счётчика рядом с ним нет.
import type { RecentDashboard } from '../../api'
import { timeAgo } from '../../lib/time'

export function RecentStrip({ items, onOpen }: {
  items: RecentDashboard[]
  onOpen: (id: string) => void
}) {
  // Одна плитка полосу не оправдывает: она просто повторила бы строку списка,
  // заняв место над ним. Полоса нужна там, где есть ИЗ ЧЕГО выбирать.
  if (items.length < 2) return null
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 6px 2px' }}>
        🕓 Недавно смотрели
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'stretch' }}>
        {items.map((d) => (
          <button key={d.id} onClick={() => onOpen(d.id)}
            title={`${d.name}${d.object_name || d.folder_name
              ? ` · ${[d.object_name, d.folder_name].filter(Boolean).join(' / ')}` : ''}`
              + `\nПоследний просмотр: ${new Date(d.viewed_at).toLocaleString('ru-RU')}`}
            style={{
              display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
              justifyContent: 'space-between', gap: 3,
              width: 232, padding: '7px 12px', cursor: 'pointer', textAlign: 'left',
              borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--border-strong)',
              borderRadius: 10, background: 'var(--surface)',
            }}>
            {/* Имя отчёта режем С КОНЦА, а не по середине (`elideMiddle`):
                у дашбордов различает НАЧАЛО названия, а сокращение середины
                оставляет «Внедрение…Х — еженедельный доклад». Две строки —
                чтобы обычное название помещалось целиком. */}
            <span style={{
              fontSize: 13, color: 'var(--text)', display: '-webkit-box', WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical', overflow: 'hidden', overflowWrap: 'anywhere',
            }}>
              {d.is_favorite && <span style={{ color: '#e0a800' }}>★ </span>}
              {d.name}
            </span>
            <span style={{
              fontSize: 11, color: 'var(--text-muted)', maxWidth: '100%',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {d.folder_name ? `📁 ${d.folder_name} · ` : ''}{timeAgo(d.viewed_at)}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

export default RecentStrip
