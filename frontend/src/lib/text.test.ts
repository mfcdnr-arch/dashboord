import { describe, expect, it } from 'vitest'
import { distinctLabels, dropCommonWords, elideMiddle, fitRotatedAxis, plural, shrinkToWidth } from './text'

describe('elideMiddle', () => {
  it('сохраняет хвост имени — им и различаются показатели госформ', () => {
    const long = 'Количество обращений за результатом оказания услуг в МФЦ · Факт · за отчётную неделю'
    const out = elideMiddle(long, 40)
    expect(out.length).toBeLessThanOrEqual(40)
    expect(out.endsWith('за отчётную неделю')).toBe(true)
    expect(out).toContain('…')
  })

  it('короткое имя не трогает', () => {
    expect(elideMiddle('Обращения', 40)).toBe('Обращения')
  })
})

describe('distinctLabels', () => {
  const forms = [
    'Количество обращений за результатом оказания услуг в МФЦ · Факт · нарастающим итогом',
    'Количество отправленных уведомлений о готовности результатов · Факт · нарастающим итогом',
    'Количество пользователей, записавшихся на посещение МФЦ · Факт · нарастающим итогом',
  ]

  it('оставляет только различающую часть имени', () => {
    const out = distinctLabels(forms)
    expect(out[0]).toBe('обращений за результатом оказания услуг в МФЦ')
    expect(out[1]).toContain('отправленных уведомлений')
    expect(new Set(out).size).toBe(3) // подписи различимы
  })

  it('не трогает имена без общей части', () => {
    const names = ['Принято', 'Выдано']
    expect(distinctLabels(names)).toEqual(names)
  })

  it('возвращает исходные имена, если различающая часть пуста', () => {
    // одинаковые имена: отрезать нечего, иначе получились бы пустые подписи
    const same = ['Количество обращений', 'Количество обращений']
    expect(distinctLabels(same)).toEqual(same)
  })

  it('одно имя возвращает как есть', () => {
    expect(distinctLabels(['Количество обращений'])).toEqual(['Количество обращений'])
  })
})

describe('plural', () => {
  it('склоняет по русским правилам', () => {
    expect(plural(1, 'период', 'периода', 'периодов')).toBe('период')
    expect(plural(2, 'период', 'периода', 'периодов')).toBe('периода')
    expect(plural(5, 'период', 'периода', 'периодов')).toBe('периодов')
    expect(plural(21, 'период', 'периода', 'периодов')).toBe('период')
  })
  it('11–14 — исключение, а не «один»', () => {
    // Ровно та ловушка, из-за которой наивное «n % 10 === 1» даёт
    // «11 период» вместо «11 периодов».
    expect(plural(11, 'период', 'периода', 'периодов')).toBe('периодов')
    expect(plural(12, 'период', 'периода', 'периодов')).toBe('периодов')
    expect(plural(14, 'период', 'периода', 'периодов')).toBe('периодов')
    expect(plural(112, 'период', 'периода', 'периодов')).toBe('периодов')
  })
})

describe('dropCommonWords', () => {
  // Настоящие подписи отделений РЦО: «ГБУ "МФЦ ДНР"» стоит у каждого и не
  // различает ничего, зато занимает треть подписи — из-за него под обрезку
  // попадали номер отделения и город.
  const offices = [
    'Отделение № 1 ГБУ "МФЦ ДНР" г. Мариуполь ул.Ленина, 107',
    'Отделение № 3 ГБУ "МФЦ ДНР" г. Мариуполь ул.Нахимова, 172',
    'Отделение ГБУ "МФЦ ДНР" пгт Сартана ул.Лафазана, 54',
  ]

  it('убирает слова, повторяющиеся у всех, и сохраняет различающие', () => {
    const cut = dropCommonWords(offices)
    expect(cut.every((s) => !s.includes('ГБУ'))).toBe(true)
    expect(cut[0]).toContain('№ 1')
    expect(cut[0]).toContain('Мариуполь')
    expect(cut[2]).toContain('Сартана')
    // Каждая подпись стала короче — ради этого всё и затевалось.
    cut.forEach((s, i) => expect(s.length).toBeLessThan(offices[i].length))
  })

  it('оставляет разделители внутри имени и убирает осиротевшие по краям', () => {
    const cut = dropCommonWords([
      'Росреестр · Выписка из ЕГРН · Принято, ед.',
      'ЕСИА (260) · Принято, ед.',
    ])
    // «Принято,» и «ед.» есть у обеих — уходят, различающая часть остаётся.
    expect(cut[0]).toBe('Росреестр · Выписка из ЕГРН')
    // У короткой подписи после чистки остался бы висячий разделитель — убираем:
    // «ЕСИА (260) ·» читается как оборванное имя.
    expect(cut[1]).toBe('ЕСИА (260)')
  })

  it('возвращает исходные, если после чистки подписи перестали различаться', () => {
    // Различие только в общих словах: убери их — останется одно и то же.
    const names = ['Принято ед.', 'Принято ед. ед.']
    expect(dropCommonWords(names)).toEqual(names)
  })

  it('одну подпись не трогает: различать не с чем', () => {
    expect(dropCommonWords(['Отделение ГБУ "МФЦ ДНР"'])).toEqual(['Отделение ГБУ "МФЦ ДНР"'])
  })
})

describe('fitRotatedAxis', () => {
  // Меряем «шрифтом» в 6px на знак: тесты про ПРАВИЛО, а не про метрики шрифта —
  // настоящую ширину даёт canvas в браузере.
  const measure = (t: string) => t.length * 6
  const opts = (maxBand: number) => ({ fontPx: 11, deg: 30, maxBand, measure })

  it('считает полосу по геометрии поворота, а не берёт её числом', () => {
    // Настоящий замер на дашборде РЦО: подпись шириной 170px при повороте на 30°
    // занимает по высоте 96px (170·sin30 + 12,5·cos30). Прежние зашитые 58px
    // занижали полосу на 38px — на столько подписи и залезали на легенду.
    const wide = 'x'.repeat(170 / 6)
    const { band } = fitRotatedAxis([wide], { fontPx: 11, deg: 30, maxBand: 999, measure })
    expect(band).toBeGreaterThanOrEqual(96)
    expect(band).toBeLessThan(112)
  })

  it('короткие подписи не трогает', () => {
    const labels = ['Донецк', 'Горловка', 'Макеевка']
    const res = fitRotatedAxis(labels, opts(88))
    expect(res.labels).toEqual(labels)
    expect(res.band).toBeLessThanOrEqual(88)
  })

  it('🔴 не влезающие подписи УКОРАЧИВАЕТ, а полосу держит в отведённом', () => {
    // Главный инвариант: наложение невозможно по построению. Сколько подписи
    // занимают — столько под них и зарезервировано, и не больше отведённого.
    // Подписи приходят уже очищенными от общих слов (dropCommonWords), иначе
    // обрезка оставила бы «Отделение…» — то есть ровно то, что не различает.
    const labels = ['№ 3 Мариуполь ул.Нахимова, 172', '№ 2 Мариуполь ул.Орджоникидзе, 51']
    const res = fitRotatedAxis(labels, opts(88))
    expect(res.band).toBeLessThanOrEqual(88)
    res.labels.forEach((l, i) => {
      expect(l.length).toBeLessThan(labels[i].length)
      // Обрезаем середину: и номер отделения, и дом остаются различимы.
      expect(l).toContain('…')
      expect(l.startsWith('№ ')).toBe(true)
      expect(/\d+$/.test(l)).toBe(true)
    })
  })

  it('пустой набор не роняет расчёт', () => {
    expect(fitRotatedAxis([], opts(88)).band).toBeGreaterThan(0)
  })

  it('без поворота полоса — высота одной строки', () => {
    const { band, labels } = fitRotatedAxis(['x'.repeat(80)], { fontPx: 11, deg: 0, maxBand: 30, measure })
    // Резать подписи при нулевом угле бессмысленно: высота от длины не зависит.
    expect(labels[0].length).toBe(80)
    expect(band).toBeLessThan(30)
  })
})

describe('shrinkToWidth', () => {
  const measure = (t: string) => t.length * 6

  it('укладывает подпись в отведённую ширину и не режет то, что и так влезает', () => {
    const s = 'Отделение № 3 ГБУ "МФЦ ДНР" г. Мариуполь ул.Нахимова, 172'
    expect(measure(shrinkToWidth(s, 90, measure))).toBeLessThanOrEqual(90)
    expect(shrinkToWidth('Донецк', 90, measure)).toBe('Донецк')
  })
})
