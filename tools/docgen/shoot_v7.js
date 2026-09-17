// Досъёмка 12–17.09.2026: раздел «Карта» (карта отделений, карточка точки,
// режим «Руководителю», справочник отделений), строка фонового воркера в
// «Здоровье системы», смена пароля с подтверждением текущего и ссылка
// «К содержимому».
//
//   node shoot_v7.js            → shots/v7_*.png
//
// Снимается на РЕАЛЬНЫХ данных дев-стенда (62 отделения), своих временных
// данных не создаёт. Действия только читающие: ни один клик не сохраняет
// форму, не меняет пароль и не трогает справочник.
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

const BASE = process.env.DOCGEN_BASE || 'http://localhost:3080'
const SHOTS = path.join(__dirname, 'shots')
const VIEWPORT = { width: 1440, height: 900 }

const shot = async (page, name, opts = {}) => {
  fs.mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), ...opts })
  console.log('  ✓', name)
}

const uiLogin = async (page, user, pass) => {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.clear())
  await page.goto(BASE, { waitUntil: 'networkidle' })
  const inputs = page.locator('form input')
  await inputs.nth(0).fill(user)
  await inputs.nth(1).fill(pass)
  await page.getByRole('button', { name: 'Войти' }).click()
  await page.waitForTimeout(2400)
}

const nav = async (page, section, wait = 2600) => {
  await page.evaluate((s) => {
    const b = [...document.querySelectorAll('nav button')].find((x) => x.textContent.trim() === s)
    if (b) b.click()
  }, section)
  await page.waitForTimeout(wait)
}

const clickBtn = async (page, part, wait = 1800) => {
  const ok = await page.evaluate((p) => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.includes(p))
    if (!b) return false
    b.click()
    return true
  }, part)
  if (!ok) throw new Error(`кнопка не найдена: ${part}`)
  await page.waitForTimeout(wait)
}

;(async () => {
  const browser = await chromium.launch()
  const ctx = await browser.newContext({ viewport: VIEWPORT, locale: 'ru-RU', deviceScaleFactor: 2 })
  const page = await ctx.newPage()

  await uiLogin(page, 'admin', 'admin')

  // ── Карта ─────────────────────────────────────────────────────────────────
  await nav(page, 'Карта', 3000)
  // Вкладка могла остаться от прошлого прогона — выбираем карту явно.
  await clickBtn(page, '🗺 Карта', 4200)
  await shot(page, 'v7_map_overview')

  // Карточка отделения: точку выбирает НАСТОЯЩИЙ клик мышью. Синтетические
  // pointer-события сюда не годятся — выбор срабатывает на отпускании
  // указателя с проверкой пройденного расстояния, и событие без координат
  // на самом SVG до обработчика не доходит (грабли карты 12.09).
  // Цель выбора — ГРУППА .mv-pt: обработчик ищет её через closest() от той
  // цели, что запомнил pointerdown. Кружок .mv-dot внутри неё не подходит —
  // события, посланные мимо группы, до обработчика не доходят.
  const dots = page.locator('.mv-pt')
  const n = await dots.count()
  if (n) {
    await dots.nth(Math.min(3, n - 1)).click({ force: true })
    await page.waitForTimeout(1600)
    const opened = await page.evaluate(() => !/Нажмите точку на карте/.test(document.body.innerText))
    if (opened) await shot(page, 'v7_map_office_card')
    else console.log('  · карточка отделения не раскрылась — кадр не снят')
  } else {
    console.log('  · точек на карте нет — карточка не снята')
  }

  // Режим «Руководителю»: нагрузка на точках.
  try {
    await clickBtn(page, 'Показать нагрузку', 3600)
    await shot(page, 'v7_map_load')
  } catch (e) {
    console.log('  · режим нагрузки недоступен:', e.message)
  }

  // Справочник отделений — вкладка «Отделения».
  try {
    await clickBtn(page, 'Отделения', 2600)
    await shot(page, 'v7_map_offices')
  } catch (e) {
    console.log('  · вкладка «Отделения» не найдена:', e.message)
  }

  // ── Здоровье системы: строка фонового воркера ─────────────────────────────
  await nav(page, 'Отчёты', 3800)
  const health = await page.evaluate(() => {
    const el = [...document.querySelectorAll('h2, h3, div')].find((e) => e.children.length === 0 && /Здоровье системы/.test(e.textContent))
    if (!el) return null
    ;(el.closest('section') || el.parentElement || el).scrollIntoView({ block: 'center' })
    return true
  })
  await page.waitForTimeout(1200)
  if (health) await shot(page, 'v7_health_worker')

  // ── Кабинет: смена пароля спрашивает текущий ──────────────────────────────
  await nav(page, 'Кабинет', 3000)
  // Форма раскрывается кнопкой — до нажатия поля «Текущий пароль» в DOM нет.
  try { await clickBtn(page, 'Сменить пароль', 1400) } catch (e) { console.log('  ·', e.message) }
  const pwd = await page.evaluate(() => {
    const l = [...document.querySelectorAll('label')].find((x) => /Текущий пароль/.test(x.textContent))
    if (!l) return false
    l.scrollIntoView({ block: 'center' })
    return true
  })
  await page.waitForTimeout(1000)
  if (pwd) await shot(page, 'v7_password_current')
  else console.log('  · форма смены пароля не найдена')

  // ── Ссылка «К содержимому» ────────────────────────────────────────────────
  await nav(page, 'Главная', 2600)
  // Ставим фокус явно: Tab зависит от того, где фокус был до него, и на
  // прокрученной странице кадр уезжает к середине меню.
  const shown = await page.evaluate(() => {
    window.scrollTo(0, 0)
    const a = document.querySelector('.skip-link')
    if (!a) return false
    a.focus()
    return getComputedStyle(a).top === '0px'
  })
  await page.waitForTimeout(600)
  if (shown) await shot(page, 'v7_skip_link', { clip: { x: 0, y: 0, width: 700, height: 150 } })
  else console.log('  · ссылка «К содержимому» не показалась — кадр не снят')

  await browser.close()
  console.log('ALL DONE (v7)')
})().catch((e) => { console.error('ОШИБКА:', e.message); process.exit(1) })
