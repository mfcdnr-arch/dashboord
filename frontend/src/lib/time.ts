import { plural } from './text'

/**
 * «Когда это было» по-человечески: «только что», «12 мин назад», «3 ч назад»,
 * «вчера», дальше — дата.
 *
 * Полная отметка времени («22.08.2026, 14:07») в плитке «Недавно смотрели»
 * отвечает не на тот вопрос: человек ищет, где он был ПОСЛЕДНИЙ раз, а не
 * когда именно. Точное время остаётся в подсказке при наведении — там оно
 * иногда и нужно.
 *
 * Будущее (часы машины разошлись, отметка из журнала чуть впереди) считаем
 * настоящим: «через 2 минуты» в такой строке выглядит поломкой.
 */
export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return ''
  const t = new Date(iso)
  if (isNaN(t.getTime())) return ''
  // Дни считаем по КАЛЕНДАРЮ, а не по 24 часам, и проверяем их ПЕРВЫМИ:
  // открытое вчера в 23:00 человек называет «вчера», а не «16 часов назад» —
  // он помнит день, а не сколько часов с тех пор прошло.
  const days = Math.round((startOfDay(now).getTime() - startOfDay(t).getTime()) / 86400000)
  if (days === 1) return 'вчера'
  if (days >= 2) {
    return days < 7 ? `${days} ${plural(days, 'день', 'дня', 'дней')} назад` : t.toLocaleDateString('ru-RU')
  }
  const min = Math.floor(Math.max(0, now.getTime() - t.getTime()) / 60000)
  if (min < 1) return 'только что'
  if (min < 60) return `${min} ${plural(min, 'минуту', 'минуты', 'минут')} назад`
  const hours = Math.floor(min / 60)
  return `${hours} ${plural(hours, 'час', 'часа', 'часов')} назад`
}

const startOfDay = (d: Date): Date => new Date(d.getFullYear(), d.getMonth(), d.getDate())
