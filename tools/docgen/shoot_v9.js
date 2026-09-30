// Досъёмка 29.09.2026: направления — группы дашбордов внутри раздела «Дашборды».
//
//   node shoot_v9.js            → shots/v9_*.png
//
// Настоящие дашборды заказчика НЕ трогаются: заводятся два временных дашборда
// и временное направление, по ним и снимается группировка; предложение
// раскладки снимается без применения (оно показывает настоящие группы стенда,
// но ничего не меняет). Имена временных — правдоподобные (в руководстве не
// должно быть служебных «zdoc_»), поэтому уборка идёт не по префиксу, а:
// направление — по метке в описании, дашборды — по запомненным id, а на случай
// сбоя до их получения — по точному имени И отсутствию страниц (у настоящих
// дашбордов страницы есть всегда).
const { chromium } = require('playwright')
const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const BASE = process.env.DOCGEN_BASE || 'http://localhost:3080'
const SHOTS = path.join(__dirname, 'shots')
const VIEWPORT = { width: 1440, height: 900 }
const DIR = 'Окна и очереди'
const MARK = 'zdoc-temp'  // метка в описании временного направления
const DASHES = ['Нагрузка на окна по часам', 'Очередь и время ожидания']
let created = []

const psql = (sql) => execSync(
  'docker exec -i dashbord_postgres psql -U dashbord -d dashbord -tA -v ON_ERROR_STOP=1',
  { input: sql, encoding: 'utf8' })

const cleanup = () => {
  const names = DASHES.map((n) => `'${n}'`).join(',')
  const ids = created.map((i) => `'${i}'`).join(',') || "'00000000-0000-0000-0000-000000000000'"
  const pick = `select id from dashboards d where d.id in (${ids}) or (d.name in (${names}) `
    + 'and not exists (select 1 from dashboard_pages p where p.dashboard_id = d.id))'
  for (const sql of [
    `delete from securable_objects where object_id in (${pick})`,
    `delete from dashboard_favorites where dashboard_id in (${pick})`,
    `delete from dashboards where id in (${pick})`,
    `delete from dashboard_directions where description = '${MARK}'`,
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

    // Временные дашборды и направление — тем же API, что и экран.
    created = await page.evaluate(async ({ dirName, mark, names }) => {
      const tok = sessionStorage.getItem('dashbord_token') || localStorage.getItem('dashbord_token')
      const H = { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok }
      const dir = await (await fetch('/dashboard-directions', {
        method: 'POST', headers: H, body: JSON.stringify({ name: dirName, description: mark }),
      })).json()
      const ids = []
      for (const n of names) {
        const r = await fetch('/dashboards', { method: 'POST', headers: H,
          body: JSON.stringify({ name: n, force: true, direction_id: dir.id }) })
        ids.push((await r.json()).id)
      }
      return ids
    }, { dirName: DIR, mark: MARK, names: DASHES })
    console.log('  временные дашборды:', created.length)

    // ── Список: группы по направлениям и фильтр ─────────────────────────────
    await nav(page, 'Дашборды', 3000)
    const listTop = page.locator('select[aria-label="Направление"]')
    await listTop.scrollIntoViewIfNeeded()
    await shot(page, 'v9_directions_list')

    // ── Окно «Направления» ─────────────────────────────────────────────────
    await page.getByRole('button', { name: '🧭 Направления' }).click()
    await page.waitForTimeout(1200)
    await shot(page.locator('[role=dialog]'), 'v9_directions_manage')
    await page.getByRole('button', { name: 'Готово' }).click()
    await page.waitForTimeout(500)

    // ── Предложение раскладки (без применения) ─────────────────────────────
    const propose = page.locator('button', { hasText: 'без направления…' })
    if (await propose.count()) {
      await propose.first().click()
      await page.waitForTimeout(1500)
      await shot(page.locator('[role=dialog]'), 'v9_directions_propose')
      await page.getByRole('button', { name: 'Отмена' }).click()
      await page.waitForTimeout(500)
    }

    // ── Массовое «В направление…» ──────────────────────────────────────────
    await page.locator(`input[aria-label="Выбрать «${DASHES[0]}» для массового действия"]`).click()
    await page.waitForTimeout(300)
    await page.getByRole('button', { name: '🧭 В направление…' }).click()
    await page.waitForTimeout(900)
    await shot(page.locator('[role=dialog]'), 'v9_directions_assign')
    await page.getByRole('button', { name: 'Отмена' }).click()
    await page.waitForTimeout(400)

    // ── Мастер «✨ Собрать»: блок «Направление» ─────────────────────────────
    await page.evaluate(() => {
      const sel = [...document.querySelectorAll('select')]
        .find((s) => [...s.options].some((o) => o.textContent === 'выберите объект…'))
      const opt = sel && [...sel.options].find((o) => o.textContent === 'РЦО — ежедневный отчёт')
      if (!opt) return
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(sel, opt.value)
      sel.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await page.waitForTimeout(400)
    await page.getByRole('button', { name: '✨ Собрать' }).click()
    await page.locator('select[aria-label="Направление нового дашборда"]').waitFor({ timeout: 20000 })
    await page.waitForTimeout(800)
    const block = page.locator('select[aria-label="Направление нового дашборда"]').locator('xpath=../..')
    await block.scrollIntoViewIfNeeded()
    await shot(block, 'v9_wizard_direction')
  } finally {
    await browser.close()
    cleanup()
  }
})().catch((e) => { console.error(e); cleanup(); process.exit(1) })
