// Досъёмка 12.10.2026: названия отделений, порог показателя, показатели между
// формами, точечная диаграмма, проверка «время больше N часов».
//
//   node shoot_v14.js           → shots/v14_*.png
//
// Снимается на НАСТОЯЩИХ данных стенда (форма «Время» и дашборд «РЦО: время
// обслуживания и ожидания»). Только чтение: виджеты не сохраняются (матрица и
// конструктор снимаются в ПРЕДПРОСМОТРЕ формы), порог не меняется (окно правки
// закрывается «Отменой»). Каждый кадр — в своём try: сбой одного не роняет
// остальные, а «✓» в выводе означает только «файл записан» — кадры смотреть
// глазами (README).
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

const BASE = process.env.DOCGEN_BASE || 'http://localhost:3080'
const SHOTS = path.join(__dirname, 'shots')
const DASH = 'РЦО: время обслуживания и ожидания'
const OBJ = 'РЦО — время обслуживания и ожидания'

const shot = async (target, name, opts = {}) => {
  fs.mkdirSync(SHOTS, { recursive: true })
  await target.screenshot({ path: path.join(SHOTS, `${name}.png`), ...opts })
  console.log('  ✓', name)
}
const ONLY = process.env.ONLY ? process.env.ONLY.split(',') : null
const step = async (name, fn) => {
  if (ONLY && !ONLY.includes(name)) return
  try { await fn() } catch (e) { console.log('  ✗', name, '—', e.message.split('\n')[0]) }
}
const clickText = (page, text) => page.evaluate((t) => {
  const els = [...document.querySelectorAll('button, a, div, span, td, li')]
    .filter((e) => e.textContent.trim().startsWith(t) && [...e.children].every((c) => !c.textContent.includes(t)))
  if (!els.length) throw new Error('не найдено: ' + t)
  els[0].click()
}, text)
// Кадр от верха элемента, но не выше липкой шапки страницы (README, грабли 4).
const clipOf = async (page, loc, maxH = 900, pad = 10) => {
  await loc.scrollIntoViewIfNeeded()
  await page.evaluate(() => window.scrollBy(0, -130))
  await page.waitForTimeout(500)
  const b = await loc.boundingBox()
  return { x: Math.max(0, b.x - pad), y: Math.max(0, b.y - pad), width: b.width + pad * 2, height: Math.min(b.height + pad * 2, maxH) }
}

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

    // 1. Названия отделений в формах: «Карта» → «Отделения».
    await step('v14_office_names', async () => {
      await page.goto(BASE + '/?s=map', { waitUntil: 'networkidle' })
      await page.waitForTimeout(1500)
      await page.getByRole('button', { name: /Отделения/ }).first().click()
      await page.waitForTimeout(2000)
      const h = page.locator('h2', { hasText: 'Названия отделений в формах' })
      const box = h.locator('xpath=ancestor::div[2]')
      await shot(page, 'v14_office_names', { clip: await clipOf(page, box, 620) })
    })

    // 2–3. «Настройки»: предел времени и список порогов.
    await step('v14_settings', async () => {
      await page.goto(BASE + '/?s=settings', { waitUntil: 'networkidle' })
      await page.waitForTimeout(1800)
      const org = page.locator('h2', { hasText: 'Данные организации' }).locator('xpath=ancestor::div[2]')
      await shot(page, 'v14_duration_limit', { clip: await clipOf(page, org, 360) })
      const norms = page.locator('h2', { hasText: 'Пороги показателей' }).locator('xpath=ancestor::div[2]')
      await shot(page, 'v14_norms_list', { clip: await clipOf(page, norms, 360) })
      // Окно правки порога — и сразу «Отмена»: значение не меняется.
      await page.getByRole('button', { name: /Изменить порог «Среднее время ожидания»/ }).click()
      await page.waitForTimeout(700)
      const dlg = page.getByRole('dialog')
      await shot(dlg, 'v14_norm_dialog')
      await dlg.getByRole('button', { name: 'Отмена' }).click()
      await page.waitForTimeout(400)
    })

    // 4. Проверка качества по истории формы «Время» — замечание «время больше».
    await step('v14_quality', async () => {
      await page.goto(BASE + '/?s=objects', { waitUntil: 'networkidle' })
      await page.waitForTimeout(1200)
      await clickText(page, OBJ)
      await page.waitForTimeout(2500)
      const box = page.locator('b', { hasText: '🔎 Проверка качества по истории' }).locator('xpath=ancestor::div[2]')
      await box.scrollIntoViewIfNeeded()
      await box.getByRole('button', { name: 'Проверить' }).click()
      await page.getByText(/Проверено \d+ из/).first().waitFor({ timeout: 60000 })
      await page.waitForTimeout(800)
      // Рамка блока — не div[2]: результат рисуется ниже шапки в том же
      // контейнере, и кадр по рамке обрезался по шапке. Берём от шапки вниз.
      // Блок — внизу страницы, и кадр в пределах окна обрезался по нижнему
      // краю: снимаем всю страницу и вырезаем в координатах документа.
      const c = await clipOf(page, box, 620)
      const sy = await page.evaluate(() => window.scrollY)
      await shot(page, 'v14_quality', { fullPage: true, clip: { ...c, y: c.y + sy, height: 360 } })
    })

    // 5–7. Дашборд «Время», страница «Между формами».
    const did = await page.evaluate(async (name) => {
      const tok = localStorage.getItem('dashbord_token')
      const r = await (await fetch('/dashboards?limit=200', { headers: { Authorization: 'Bearer ' + tok } })).json()
      return (r.items || r).find((d) => d.name === name)?.id
    }, DASH)
    if (!did) throw new Error('нет дашборда ' + DASH)
    await page.goto(BASE + '/?s=dashboards&d=' + did, { waitUntil: 'networkidle' })
    await page.waitForTimeout(3500)
    await page.locator('main button', { hasText: 'Между формами' }).first().click()
    await page.waitForTimeout(5000)

    await step('v14_cross_cards', async () => {
      const first = page.locator('[data-widget-id]').first()
      const b0 = await first.boundingBox()
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.waitForTimeout(400)
      const b = await first.boundingBox()
      await shot(page, 'v14_cross_cards', { clip: { x: b.x - 10, y: b.y - 10, width: 1440 - b.x - 20, height: Math.min(b0.height + 30, 300) } })
    })
    await step('v14_scatter', async () => {
      const w = page.locator('[data-widget-id]', { hasText: 'где очередь от нехватки окон' }).first()
      await page.waitForTimeout(1500)
      await shot(page, 'v14_scatter', { clip: await clipOf(page, w, 760) })
    })
    await step('v14_cross_ranked', async () => {
      const w = page.locator('[data-widget-id]', { hasText: 'по отделениям за неделю' }).first()
      await shot(page, 'v14_cross_ranked', { clip: await clipOf(page, w, 520) })
    })
    await step('v14_dyn_norm', async () => {
      const w = page.locator('[data-widget-id]', { hasText: 'Динамика: среднее ожидание' }).first()
      await page.waitForTimeout(1000)
      await shot(page, 'v14_dyn_norm', { clip: await clipOf(page, w, 520) })
    })

    // 8–9. Форма виджета (предпросмотр, без сохранения): конструктор
    // показателя между формами и матрица ожидания с окраской по порогу.
    await step('v14_builder', async () => {
      const gallery = page.locator('button[title="Открыть галерею типов виджетов"]').first()
      await gallery.scrollIntoViewIfNeeded()
      await gallery.click()
      await page.waitForTimeout(600)
      await page.getByRole('dialog').getByRole('button', { name: /Точечная диаграмма/ }).click()
      await page.waitForTimeout(1500)
      const presets = page.locator('select', { has: page.locator('option', { hasText: 'Талонов на окно-час' }) })
      await presets.nth(0).selectOption('tickets_per_window_hour')
      await presets.nth(1).selectOption('wait_weighted')
      await page.waitForTimeout(2500)
      const b1 = page.getByText('По горизонтали (например, нагрузка на окно-час)').locator('xpath=..')
      await shot(page, 'v14_builder', { clip: await clipOf(page, b1, 330) })
    })
    await step('v14_matrix_norm', async () => {
      const gallery = page.locator('button[title="Открыть галерею типов виджетов"]').first()
      await gallery.scrollIntoViewIfNeeded()
      await gallery.click()
      await page.waitForTimeout(600)
      await page.getByRole('dialog').getByRole('button', { name: /Матрица по датам/ }).click()
      await page.waitForTimeout(1200)
      await page.locator('select', { has: page.locator('option[value="rco_wait"]') }).first().selectOption('rco_wait')
      await page.waitForTimeout(600)
      await page.locator('select', { has: page.locator('option[value="srednee_vremya_ozhidaniya"]') }).first()
        .selectOption('srednee_vremya_ozhidaniya')
      await page.locator('input[type="number"]').last().fill('6')
      await page.waitForTimeout(3500)
      const prev = page.getByText('Среднее время ожидания · показаны последние', { exact: false }).first().locator('xpath=..')
      await shot(page, 'v14_matrix_norm', { clip: await clipOf(page, prev, 520) })
    })
    console.log('ALL DONE')
  } finally {
    await browser.close()
  }
})()
