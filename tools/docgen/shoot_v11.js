// Досъёмка 01.10.2026: этап 5 — «в форме появились новые графы — добавить виджет?».
//
//   node shoot_v11.js           → shots/v11_*.png
//
// Настоящие данные заказчика НЕ трогаются. Заводится временная форма
// («Запись на приём — недельная сводка», код doc_zapis_week) с двумя отчётами —
// во втором две новые графы — и временный дашборд на ней с меткой в описании.
// Форму и объявление заводит shoot_v11_seed.py внутри контейнера api (тем же
// кодом, что выпуск: ingestion/new_fields.announce). Уборка — по точному имени
// объекта, коду формы и метке дашборда, в том числе после сбоя.
const { chromium } = require('playwright')
const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const BASE = process.env.DOCGEN_BASE || 'http://localhost:3080'
const SHOTS = path.join(__dirname, 'shots')
const VIEWPORT = { width: 1440, height: 900 }
const MARK = 'zdoc-temp'
const DASH = 'Запись на приём'
const SEED = path.join(__dirname, 'shoot_v11_seed.py')

const seed = (step) => {
  execSync(`docker cp "${SEED}" dashbord_api:/tmp/shoot_v11_seed.py`)
  return execSync(`docker exec dashbord_api python3 /tmp/shoot_v11_seed.py ${step}`, { encoding: 'utf8' }).trim()
}
const psql = (sql) => execSync(
  'docker exec -i dashbord_postgres psql -U dashbord -d dashbord -tA -v ON_ERROR_STOP=1',
  { input: sql, encoding: 'utf8' })

const cleanup = () => {
  const pick = `select id from dashboards where description = '${MARK}'`
  for (const sql of [
    `delete from notification_events where entity_type = 'dashboard' and entity_id in (${pick})`,
    `delete from dashboards where id in (${pick})`,
  ]) { try { psql(sql) } catch (e) { console.log('cleanup:', String(e).slice(0, 120)) } }
  try { seed('clean') } catch (e) { console.log('cleanup seed:', String(e).slice(0, 120)) }
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

;(async () => {
  cleanup()
  const browser = await chromium.launch()
  try {
    seed('base')
    const ctx = await browser.newContext({ viewport: VIEWPORT, locale: 'ru-RU', deviceScaleFactor: 2 })
    const page = await ctx.newPage()
    await uiLogin(page, 'admin', 'admin')

    // Дашборд на форме — тем же API, что экран: карточка и таблица всей формы.
    await page.evaluate(async ({ name, mark }) => {
      const tok = sessionStorage.getItem('dashbord_token') || localStorage.getItem('dashbord_token')
      const H = { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok }
      const d = await (await fetch('/dashboards', { method: 'POST', headers: H,
        body: JSON.stringify({ name, description: mark, force: true }) })).json()
      const p = await (await fetch(`/dashboards/${d.id}/pages`, { method: 'POST', headers: H,
        body: JSON.stringify({ name: 'Обзор' }) })).json()
      for (const w of [
        { name: 'Принято заявлений', widget_type: 'kpi', config: { dataset_code: 'doc_zapis_week', value_field: 'obr' } },
        { name: 'Первичные данные', widget_type: 'table', config: { dataset_code: 'doc_zapis_week' } },
      ]) await fetch(`/dashboard-pages/${p.id}/widgets`, { method: 'POST', headers: H, body: JSON.stringify(w) })
    }, { name: DASH, mark: MARK })
    console.log(' ', seed('news'))

    // ── Колокольчик ────────────────────────────────────────────────────────
    await page.reload({ waitUntil: 'networkidle' })
    await page.waitForTimeout(2000)
    await page.locator('button[aria-label^="Уведомления"]').click()
    const row = page.getByRole('button', { name: /В форме появились новые графы/ }).first()
    await row.waitFor({ timeout: 15000 })
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('b')].find((x) => x.textContent.trim() === 'Уведомления')
      const box = b && b.parentElement && b.parentElement.parentElement
      if (box) box.setAttribute('data-shot', 'bell')
    })
    await page.waitForTimeout(400)
    // Только шапка ленты и наша строка: остальные уведомления стенда к главе не относятся.
    {
      const box = await page.locator('[data-shot=bell]').boundingBox()
      const r = await row.boundingBox()
      await shot(page, 'v11_notice', { clip: { x: box.x, y: box.y, width: box.width, height: r.y + r.height - box.y + 1 } })
    }

    // ── Окно «Новые графы формы» ───────────────────────────────────────────
    await row.click()
    await page.locator('[role=dialog]').waitFor({ timeout: 20000 })
    await page.waitForTimeout(800)
    await shot(page.locator('[role=dialog]'), 'v11_dialog')
    await page.getByRole('button', { name: 'Отмена' }).click()
    await page.waitForTimeout(600)

    // ── Подсказка в шапке ──────────────────────────────────────────────────
    const hint = page.locator('button', { hasText: /нов(ая|ые|ых) граф/ }).first()
    await hint.waitFor({ timeout: 10000 })
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find((x) => /нов(ая|ые|ых) граф/.test(x.textContent))
      const row = b && b.parentElement
      if (row) row.setAttribute('data-shot', 'hint')
    })
    // Полоса во всю ширину в документе стала бы нечитаемой нитью — берём её правую часть с подсказкой.
    {
      const bar = await page.locator('[data-shot=hint]').boundingBox()
      const x = Math.max(bar.x, bar.x + bar.width - 560)
      await shot(page, 'v11_hint', { clip: { x, y: bar.y - 6, width: bar.x + bar.width - x, height: bar.height + 12 } })
    }
  } finally {
    await browser.close()
    cleanup()
  }
})().catch((e) => { console.error(e); cleanup(); process.exit(1) })
