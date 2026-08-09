// Единое форматирование чисел для интерфейса.
// Раньше одна и та же функция была скопирована в четыре компонента, и они
// разошлись: целые печатались по-русски («929 825»), а дробные через toFixed —
// с ТОЧКОЙ («37.18»). В одном окне соседствовали две записи одного числа.
export function fmtNumber(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—'
  return Number.isInteger(n)
    ? n.toLocaleString('ru-RU')
    : n.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
