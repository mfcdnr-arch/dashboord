import { describe, expect, it } from 'vitest'
import { checkPassword, passwordHint, type PasswordPolicy } from './auth'

const P: PasswordPolicy = { min_length: 8, require_complexity: true }

describe('checkPassword (парольная политика)', () => {
  it('отклоняет слишком короткий', () => {
    expect(checkPassword('ab1', P)).toMatch(/коротк/i)
  })
  it('отклоняет без цифры', () => {
    expect(checkPassword('abcdefgh', P)).toMatch(/буквы.*цифры/i)
  })
  it('отклоняет без буквы', () => {
    expect(checkPassword('12345678', P)).toMatch(/буквы.*цифры/i)
  })
  it('отклоняет совпадение с логином (без учёта регистра)', () => {
    expect(checkPassword('Str0ngPass9', P, 'admin123')).toBeNull() // отличается от логина
    expect(checkPassword('Admin123', P, 'admin123')).toMatch(/логин/i) // равен без учёта регистра
  })
  it('принимает стойкий пароль', () => {
    expect(checkPassword('Str0ngPass9', P)).toBeNull()
  })
  it('уважает require_complexity=false', () => {
    expect(checkPassword('abcdefgh', { min_length: 8, require_complexity: false })).toBeNull()
  })
})

describe('passwordHint', () => {
  it('содержит минимальную длину', () => {
    expect(passwordHint(P)).toContain('8')
  })
})
