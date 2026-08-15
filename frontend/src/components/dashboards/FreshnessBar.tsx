const ru = (iso: string | null): string =>
  (iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.split('-').reverse().join('.') : iso || '')

/**
 * Честная строка о свежести данных + предложение обновиться.
 *
 * Цифры на дашборде обновляются сами: виджет читает последний неотменённый
 * выпуск. Но человек этого не видит — и не понимает, сегодняшние перед ним
 * числа или прошлогодние. Поэтому дата выпуска сказана прямо.
 *
 * Когда во время просмотра появился более свежий выпуск, страница НЕ
 * перезагружается сама: человек мог настраивать виджеты или читать таблицу.
 * Вместо этого — предложение с кнопкой.
 */
export function FreshnessBar(
  { asOf, available, onRefresh }:
  { asOf: string | null; available: string | null; onRefresh: () => void },
) {
  if (!asOf && !available) return null
  if (available) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        background: 'var(--accent-weak-bg)', color: 'var(--accent)', fontSize: 13,
        padding: '8px 12px', borderRadius: 8, margin: '0 0 12px',
      }}>
        <span>🔄 Появились данные за {ru(available)} — на экране показаны за {ru(asOf)}.</span>
        <button type="button" onClick={onRefresh}
          style={{
            marginLeft: 'auto', height: 28, padding: '0 12px', border: '1px solid var(--accent)',
            borderRadius: 8, background: 'var(--surface)', color: 'var(--accent)',
            fontSize: 12.5, cursor: 'pointer',
          }}>Показать свежие</button>
      </div>
    )
  }
  return (
    <div style={{ fontSize: 12, color: 'var(--text-faint)', margin: '0 0 10px' }}>
      🕓 Данные на {ru(asOf)} · обновляются автоматически, как только выпущен новый отчёт
    </div>
  )
}
