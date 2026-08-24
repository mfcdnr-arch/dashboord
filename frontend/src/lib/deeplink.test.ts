import { describe, expect, it } from 'vitest'
import { buildLink, isNavigation, parseLink, sameLink } from './deeplink'

describe('deeplink', () => {
  it('переносит отчёт, страницу и период — то, ради чего ссылку и шлют', () => {
    const s = { section: 'dashboards', dashboard: 'd1', page: 'p1', from: '2026-08-01', to: '2026-08-19' }
    const url = buildLink(s)
    expect(url).toBe('/?s=dashboards&d=d1&p=p1&from=2026-08-01&to=2026-08-19')
    expect(parseLink(url.slice(url.indexOf('?')))).toEqual(s)
  })

  it('строка с пробелами и кириллицей переживает круг', () => {
    // Названия строк — «Донецкая Народная Республика»: если экранирование
    // потеряется, ссылка приведёт к пустому фильтру, и это будет выглядеть
    // как «у коллеги другие данные».
    const s = { section: 'dashboards', dashboard: 'd1', row: 'Донецкая Народная Республика' }
    const back = parseLink(buildLink(s).split('?')[1])
    expect(back.row).toBe('Донецкая Народная Республика')
  })

  it('пустые поля в адрес не пишутся', () => {
    expect(buildLink({ section: 'home' })).toBe('/?s=home')
    expect(buildLink({})).toBe('/')
    expect(buildLink({ section: 'dashboards', row: '' })).toBe('/?s=dashboards')
  })

  it('мусор в адресе не ломает разбор', () => {
    // По испорченной ссылке человек должен попасть в рабочую систему, а не в
    // сообщение об ошибке.
    expect(parseLink('?мусор&s=&d=x')).toEqual({ dashboard: 'x' })
    expect(parseLink('')).toEqual({})
  })

  it('порядок ключей фиксирован — одно состояние даёт одну строку', () => {
    // Иначе сравнение «адрес уже такой» ломалось бы и история засорялась бы
    // повторами одного и того же места.
    const a = buildLink({ section: 'dashboards', dashboard: 'd', from: '2026-01-01' })
    const b = buildLink({ from: '2026-01-01', dashboard: 'd', section: 'dashboards' })
    expect(a).toBe(b)
  })

  it('переход отличается от правки фильтра', () => {
    const base = { section: 'dashboards', dashboard: 'd1', page: 'p1' }
    // Другой отчёт/страница/раздел — это шаг в истории.
    expect(isNavigation(base, { ...base, page: 'p2' })).toBe(true)
    expect(isNavigation(base, { ...base, dashboard: 'd2' })).toBe(true)
    expect(isNavigation(base, { section: 'objects' })).toBe(true)
    // А период и строка — уточнение того же места: запись в истории плодить
    // нельзя, иначе «назад» перестанет работать осмысленно.
    expect(isNavigation(base, { ...base, from: '2026-08-01' })).toBe(false)
    expect(isNavigation(base, { ...base, row: 'Горловка' })).toBe(false)
  })

  it('sameLink не отличает пустое от отсутствующего', () => {
    expect(sameLink({ section: 'home' }, { section: 'home', row: '' })).toBe(true)
    expect(sameLink({ section: 'home' }, { section: 'home', row: 'x' })).toBe(false)
  })
})
