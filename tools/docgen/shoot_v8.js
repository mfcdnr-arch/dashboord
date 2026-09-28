// Досъёмка 24.09.2026: мастер «✨ Собрать» с новым списком виджетов —
// рекомендованные по страницам, «Ещё можно добавить» с причинами и пояснение ⓘ.
//
//   node shoot_v8.js            → shots/v8_*.png
//
// Снимается на РЕАЛЬНЫХ данных дев-стенда (объект «РЦО — ежедневный отчёт»),
// своих временных данных не создаёт. Действия только читающие: мастер
// открывается и закрывается, кнопка «Собрать» не нажимается.
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

const BASE = process.env.DOCGEN_BASE || 'http://localhost:3080'
const SHOTS = path.join(__dirname, 'shots')
const VIEWPORT = { width: 1440, height: 900 }
const OBJECT = 'РЦО — ежедневный отчёт'

const shot = async (target, name, opts = {}) => {
  fs.mkdirSync(SHOTS, { recursive: true })
  await target.screenshot({ path: path.join(SHOTS, `${name}.png`), ...opts })
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

;(async () => {
  const browser = await chromium.launch()
  const ctx = await browser.newContext({ viewport: VIEWPORT, locale: 'ru-RU', deviceScaleFactor: 2 })
  const page = await ctx.newPage()
  await uiLogin(page, 'admin', 'admin')

  // ── Дашборды → «✨ Собрать» по объекту ────────────────────────────────────
  await nav(page, 'Дашборды', 3000)
  const picked = await page.evaluate((name) => {
    const sel = [...document.querySelectorAll('select')]
      .find((s) => [...s.options].some((o) => o.textContent === 'выберите объект…'))
    const opt = sel && [...sel.options].find((o) => o.textContent === name)
    if (!opt) return false
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(sel, opt.value)
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    return true
  }, OBJECT)
  if (!picked) throw new Error(`объект не найден: ${OBJECT}`)
  await page.waitForTimeout(400)
  await page.getByRole('button', { name: '✨ Собрать' }).click()
  // Мастер открывается со списком кандидатов — ждём первую галочку виджета.
  await page.locator('[role=dialog] input[type=checkbox]').first().waitFor({ timeout: 20000 })
  await page.waitForTimeout(1500)

  const dialog = page.locator('[role=dialog]')
  // Кадр 1: список «Виджеты» — рекомендованные, по страницам будущего дашборда.
  const list = dialog.locator('div', { hasText: /^Виджеты \(/ }).last()
  await list.scrollIntoViewIfNeeded()
  await page.waitForTimeout(400)
  const block = list.locator('xpath=..')
  await shot(block, 'v8_wizard_candidates')

  // Кадр 2: пояснение ⓘ — тот же текст, что будет у созданного виджета.
  const tip = dialog.getByRole('button', { name: /^Что покажет/ }).nth(1)
  await tip.hover()
  await page.waitForTimeout(700)
  await shot(page, 'v8_wizard_explain')

  // Кадр 3: «Ещё можно добавить» — причина у каждого.
  await page.mouse.move(5, 5)
  await dialog.getByRole('button', { name: /Ещё можно добавить/ }).click()
  await page.waitForTimeout(600)
  const extra = dialog.getByRole('button', { name: /Ещё можно добавить/ }).locator('xpath=..')
  await extra.scrollIntoViewIfNeeded()
  await shot(extra, 'v8_wizard_extra')

  // Кадр 4: итог со счётчиком карточек.
  const total = dialog.locator('div', { hasText: /^Карточек показателей/ }).last().locator('xpath=..')
  await total.scrollIntoViewIfNeeded()
  await shot(total, 'v8_wizard_total')

  await browser.close()
})().catch((e) => { console.error(e); process.exit(1) })
