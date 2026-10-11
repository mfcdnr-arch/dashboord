// Досъёмка 11.10.2026: книга из нескольких форм — шаблон разметки на каждую форму.
//
//   node shoot_v13.js           → shots/v13_*.png
//
// Снимается на НАСТОЯЩИХ данных стенда (объект «МФЦ ДНР — отчёт
// Минэкономразвития» и его книга за 06.10.2026), только чтение: временных
// данных скрипт не создаёт и ничего не выпускает.
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

const BASE = process.env.DOCGEN_BASE || 'http://localhost:3080'
const SHOTS = path.join(__dirname, 'shots')
const OBJ = 'МФЦ ДНР — отчёт Минэкономразвития'
const FILE = 'Отчёт_МФЦ_06-10-2026.xlsx'

const shot = async (target, name, opts = {}) => {
  fs.mkdirSync(SHOTS, { recursive: true })
  await target.screenshot({ path: path.join(SHOTS, `${name}.png`), ...opts })
  console.log('  ✓', name)
}

// Клик по самому глубокому элементу с текстом (см. README: списки — так).
const clickText = (page, text) => page.evaluate((t) => {
  const els = [...document.querySelectorAll('button, a, div, span, td, li')]
    .filter((e) => e.textContent.trim().startsWith(t) && [...e.children].every((c) => !c.textContent.includes(t)))
  if (!els.length) throw new Error('не найдено: ' + t)
  els[0].click()
}, text)

;(async () => {
  const browser = await chromium.launch()
  try {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ru-RU', deviceScaleFactor: 2 })
    const page = await ctx.newPage()
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => localStorage.clear())
    await page.goto(BASE, { waitUntil: 'networkidle' })
    const inputs = page.locator('form input')
    await inputs.nth(0).fill('admin')
    await inputs.nth(1).fill('admin')
    await page.getByRole('button', { name: 'Войти' }).click()
    await page.waitForTimeout(2400)

    await page.goto(BASE + '/?s=objects', { waitUntil: 'networkidle' })
    await page.waitForTimeout(1200)
    await clickText(page, OBJ)
    await page.waitForTimeout(2500)

    // Блок шаблонов: формы книги по порядку листов и «Перестать узнавать».
    const tpl = page.locator('div', { has: page.locator('b', { hasText: '🧩 Шаблоны разметки' }) }).last()
    await tpl.scrollIntoViewIfNeeded()
    await shot(tpl, 'v13_templates')
    // Ступени формы — с переключателем формы.
    // Рамка блока — второй предок заголовка (первый — строка с переключателем).
    const lv = page.locator('b', { hasText: '🪜 Ступени формы' }).locator('xpath=ancestor::div[2]')
    await shot(lv, 'v13_levels')

    // Экран разметки книги: вкладки листов с «✓» и подставленная разметка.
    await page.locator('main').getByText('Отчёты', { exact: true }).last().click()
    await page.waitForTimeout(1800)
    await clickText(page, FILE)
    await page.waitForTimeout(3500)
    // Строка вкладок листов («✓» у узнанных форм) и полоса подставленной разметки под ней.
    const chip = page.locator('main button', { hasText: 'Итоги недели' }).first()
    await chip.scrollIntoViewIfNeeded()
    await page.evaluate(() => window.scrollBy(0, -20))
    await page.waitForTimeout(400)
    const row = await chip.locator('xpath=..').boundingBox()
    await shot(page, 'v13_sheets', { clip: { x: row.x - 8, y: row.y - 8, width: row.width + 16, height: 140 } })
    console.log('ALL DONE')
  } finally {
    await browser.close()
  }
})()
