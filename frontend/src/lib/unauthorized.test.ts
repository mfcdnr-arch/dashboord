import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { clearToken, errText, getToken, setToken, UNAUTHORIZED_EVENT } from '../api/http'

/**
 * Истёкший токен возвращает человека на вход (20.09.2026).
 *
 * Токен живёт 12 часов, а `clearToken` вызывался только при загрузке страницы
 * и по кнопке «Выйти». Вкладка, открытая со вчера, выглядела рабочей и на
 * каждое действие отвечала «Недействительный токен».
 */
function res(status: number, url: string, body: unknown = { detail: 'Недействительный токен' }): Response {
  // У Response поле `url` только для чтения, а проверка публичных маршрутов
  // смотрит именно на него — задаём явно.
  const r = new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  })
  Object.defineProperty(r, 'url', { value: url })
  return r
}

describe('401 возвращает на вход', () => {
  let fired = 0
  const onEvent = () => { fired += 1 }

  beforeEach(() => {
    fired = 0
    window.addEventListener(UNAUTHORIZED_EVENT, onEvent)
    setToken('stale-token')
  })
  afterEach(() => {
    window.removeEventListener(UNAUTHORIZED_EVENT, onEvent)
    clearToken()
  })

  it('истёкший токен: сбрасывается и приложению сообщается', async () => {
    await errText(res(401, 'http://localhost/dashboards'))
    expect(getToken()).toBeNull()
    expect(fired).toBe(1)
  })

  it('🔴 неверный пароль при входе — НЕ истёкшая сессия', async () => {
    // На /auth/login 401 означает «логин или пароль неверны». Сбросить сессию
    // и показать экран входа заново значило бы съесть сообщение об ошибке.
    setToken('stale-token')
    await errText(res(401, 'http://localhost/auth/login'))
    expect(getToken()).toBe('stale-token')
    expect(fired).toBe(0)
  })

  it('прочие ошибки сессию не трогают', async () => {
    await errText(res(403, 'http://localhost/metrics'))
    await errText(res(500, 'http://localhost/dashboards'))
    await errText(res(422, 'http://localhost/users', { detail: [{ loc: ['body', 'login'], msg: 'обязательно' }] }))
    expect(getToken()).toBe('stale-token')
    expect(fired).toBe(0)
  })

  it('без токена ничего не происходит: экран входа и так на месте', async () => {
    clearToken()
    await errText(res(401, 'http://localhost/dashboards'))
    expect(fired).toBe(0)
  })
})
