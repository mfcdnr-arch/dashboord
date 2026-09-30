// Досъёмка 30.09.2026: этап 4 — система предлагает виджеты новой форме.
//
//   node shoot_v10.js           → shots/v10_*.png
//
// Настоящие дашборды заказчика НЕ трогаются. Плашка «это новая форма»
// снимается как есть (на стенде есть формы без дашбордов); для режима
// «отдельной новой страницей» заводится ВРЕМЕННЫЙ дашборд с правдоподобным
// именем и меткой в описании, сборка в него снимается и тут же отменяется
// штатной кнопкой «Отменить сборку» — то есть съёмка заодно проверяет отмену.
// Уборка — по запомненному id и по метке в описании (на случай сбоя до того,
// как id получен).
const { chromium } = require('playwright')
const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const BASE = process.env.DOCGEN_BASE || 'http://localhost:3080'
const SHOTS = path.join(__dirname, 'shots')
const VIEWPORT = { width: 1440, height: 900 }
const MARK = 'zdoc-temp'  // метка в описании временного дашборда
const HOST = 'Сводный доклад по услугам'
let hostId = null

const psql = (sql) => execSync(
  'docker exec -i dashbord_postgres psql -U dashbord -d dashbord -tA -v ON_ERROR_STOP=1',
  { input: sql, encoding: 'utf8' })

const cleanup = () => {
  const id = hostId ? `'${hostId}'` : "'00000000-0000-0000-0000-000000000000'"
  const pick = `select id from dashboards where id = ${id} or description = '${MARK}'`
  for (const sql of [
    `delete from notification_events where entity_type = 'dashboard' and entity_id in (${pick})`,
    `delete from dashboards where id in (${pick})`,
  ]) { try { psql(sql) } catch (e) { console.log('cleanup:', String(e).slice(0, 120)) } }
}

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
  cleanup()
  const browser = await chromium.launch()
  try {
    const ctx = await browser.newContext({ viewport: VIEWPORT, locale: 'ru-RU', deviceScaleFactor: 2 })
    const page = await ctx.newPage()
    await uiLogin(page, 'admin', 'admin')

    // Временный дашборд со своей страницей — тем же API, что и экран.
    hostId = await page.evaluate(async ({ name, mark }) => {
      const tok = sessionStorage.getItem('dashbord_token') || localStorage.getItem('dashbord_token')
      const H = { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok }
      const d = await (await fetch('/dashboards', { method: 'POST', headers: H,
        body: JSON.stringify({ name, description: mark, force: true }) })).json()
      await fetch(`/dashboards/${d.id}/pages`, { method: 'POST', headers: H, body: JSON.stringify({ name: 'Итоги' }) })
      return d.id
    }, { name: HOST, mark: MARK })
    console.log('  временный дашборд:', hostId ? 'есть' : 'НЕТ')

    // ── «Загрузка»: плашка «это новая форма» ───────────────────────────────
    await nav(page, 'Загрузка', 3200)
    const banner = page.locator('[role=status]', { hasText: 'новая форма' }).first()
    await banner.waitFor({ timeout: 15000 })
    await shot(banner, 'v10_offer_banner')

    // ── Мастер: предпросмотр кандидата ─────────────────────────────────────
    await banner.getByRole('button', { name: '✨ Предложить виджеты' }).click()
    await page.locator('[role=dialog] button[aria-label^="Предпросмотр «"]').first().waitFor({ timeout: 30000 })
    await page.waitForTimeout(800)
    // Именно 👁: у ⓘ в той же строке тоже есть имя виджета, и стоит она раньше.
    const eye = page.locator('[role=dialog] button[aria-label^="Предпросмотр «"][aria-label*="сравнение"]').first()
    await (await eye.count() ? eye : page.locator('[role=dialog] button[aria-label^="Предпросмотр «"]').first()).click()
    const region = page.locator('[role=region][aria-label^="Предпросмотр «"]').first()
    await region.waitFor({ timeout: 20000 })
    await page.waitForTimeout(4000)  // расчёт на сервере, ленивый график и анимация появления
    console.log('  предпросмотр:', await region.getAttribute('aria-label'),
      '— svg:', await region.locator('svg').count(), '—', (await region.innerText()).slice(0, 80).replace(/\n/g, ' '))
    // Список кандидатов — ближайший предок предпросмотра со своей прокруткой.
    await page.evaluate(() => {
      const reg = document.querySelector('[role=region][aria-label^="Предпросмотр «"]')
      let el = reg && reg.parentElement
      while (el && getComputedStyle(el).overflowY !== 'auto') el = el.parentElement
      if (el) { el.setAttribute('data-shot', 'cands'); el.scrollTop = Math.max(0, reg.offsetTop - el.offsetTop - 120) }
    })
    const cands = page.locator('[data-shot=cands]')
    await cands.scrollIntoViewIfNeeded()
    await page.waitForTimeout(400)
    await shot(cands, 'v10_candidate_preview')

    // ── «Куда собрать»: отдельной новой страницей ──────────────────────────
    const where = page.locator('[role=dialog] select').filter({ has: page.locator('option', { hasText: 'Новый дашборд' }) })
    await where.selectOption(`page:${hostId}`)
    await page.locator('input[aria-label="Название новой страницы"]').waitFor({ timeout: 5000 })
    await page.waitForTimeout(500)
    // Прокручиваем окно мастера вниз: там выбор, название страницы и итог.
    // Прокручивать надо предка САМОГО выпадающего списка: первым попавшимся
    // блоком с прокруткой оказывается список показателей.
    await where.evaluate((sel) => {
      let sc = sel.parentElement
      while (sc && !['auto', 'scroll'].includes(getComputedStyle(sc).overflowY)) sc = sc.parentElement
      if (sc) sc.scrollTop = sc.scrollHeight
    })
    await page.waitForTimeout(600)
    await shot(page.locator('[role=dialog]'), 'v10_into_page')

    // ── Итог и отмена ──────────────────────────────────────────────────────
    await page.getByRole('button', { name: 'Добавить страницу' }).click()
    await page.getByText('✅ Готово').waitFor({ timeout: 30000 })
    await page.waitForTimeout(500)
    await shot(page.locator('[role=dialog]'), 'v10_done_undo')
    await page.getByRole('button', { name: 'Отменить сборку' }).click()
    await page.getByText('↩ Сборка отменена').waitFor({ timeout: 15000 })
    await page.waitForTimeout(400)
    await shot(page.locator('[role=dialog]'), 'v10_undone')
    await page.getByRole('button', { name: 'Закрыть' }).click()
  } finally {
    await browser.close()
    cleanup()
  }
})().catch((e) => { console.error(e); cleanup(); process.exit(1) })
