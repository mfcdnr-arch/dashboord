// Досъёмка 08.10.2026: формы-реестры — подсчёт строк, матрица рисков, лента.
//
//   node shoot_v12.js           → shots/v12_*.png
//
// Матрица и счётчики снимаются на ВРЕМЕННОЙ учебной форме («Реестр вопросов —
// учебный пример», код doc_reestr_voprosov): настоящий лист «Проблемные
// вопросы» формы Минэкономразвития пока пуст. Её заводит shoot_v12_seed.py
// внутри контейнера api, дашборд на ней — тем же API, что экран, с меткой в
// описании. Лента снимается на настоящем дашборде Минэкономразвития (только
// чтение). Уборка — по имени объекта, коду формы и метке, в том числе после сбоя.
const { chromium } = require('playwright')
const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const BASE = process.env.DOCGEN_BASE || 'http://localhost:3080'
const SHOTS = path.join(__dirname, 'shots')
const VIEWPORT = { width: 1440, height: 900 }
const MARK = 'zdoc-temp'
const SEED = path.join(__dirname, 'shoot_v12_seed.py')
const CODE = 'doc_reestr_voprosov'
const MER = 'МФЦ ДНР — еженедельный отчёт для Минэкономразвития'

const seed = (step) => {
  execSync(`docker cp "${SEED}" dashbord_api:/tmp/shoot_v12_seed.py`)
  return execSync(`docker exec dashbord_api python3 /tmp/shoot_v12_seed.py ${step}`, { encoding: 'utf8' }).trim()
}
const psql = (sql) => execSync(
  'docker exec -i dashbord_postgres psql -U dashbord -d dashbord -tA -v ON_ERROR_STOP=1',
  { input: sql, encoding: 'utf8' })

const cleanup = () => {
  try { psql(`delete from dashboards where description = '${MARK}'`) } catch (e) { console.log('cleanup:', String(e).slice(0, 120)) }
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

const card = (page, title) => page.locator('[data-widget-id]', { hasText: title }).first()

;(async () => {
  cleanup()
  const browser = await chromium.launch()
  try {
    seed('base')
    const ctx = await browser.newContext({ viewport: VIEWPORT, locale: 'ru-RU', deviceScaleFactor: 2 })
    const page = await ctx.newPage()
    await uiLogin(page, 'admin', 'admin')

    const NOT_CLOSED = [{ field: 'status', op: 'ne', value: 'Вопрос решен' }, { field: 'status', op: 'ne', value: 'Не актуально' }]
    const dashId = await page.evaluate(async ({ mark, code, notClosed }) => {
      const tok = localStorage.getItem('dashbord_token')
      const H = { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok }
      const d = await (await fetch('/dashboards', { method: 'POST', headers: H,
        body: JSON.stringify({ name: 'Проблемные вопросы', description: mark, force: true }) })).json()
      const pid = (await (await fetch(`/dashboards/${d.id}/pages`, { method: 'POST', headers: H,
        body: JSON.stringify({ name: 'Проблемные вопросы', layout_mode: 'flow' }) })).json()).id
      const ws = [
        { name: 'Высокий риск (оценка 15 и выше)', widget_type: 'kpi', config: { dataset_code: code, count: true,
          where: [{ field: 'ocenka_riska', op: 'gte', value: 15 }, ...notClosed] } },
        { name: 'Срок решения истёк', widget_type: 'kpi', config: { dataset_code: code, count: true,
          where: [{ field: 'srok_resheniya', op: 'date_before_report' }, ...notClosed] } },
        { name: 'Вопросов в работе', widget_type: 'kpi', config: { dataset_code: code, count: true,
          where: [{ field: 'status', op: 'eq', value: 'В работе' }] } },
        { name: 'Матрица рисков: вероятность × влияние', widget_type: 'heatmap', config: { dataset_code: code, count: true,
          group_by: 'veroyatnost', group_values: ['5', '4', '3', '2', '1'],
          group_by2: 'vliyanie', group_values2: ['1', '2', '3', '4', '5'], where: notClosed } },
        { name: 'Вопросы по уровню риска', widget_type: 'bar', config: { dataset_code: code, count: true,
          group_by: 'uroven_riska', group_values: ['Высокий', 'Средний', 'Низкий', 'Снят', 'Не актуально'] } },
      ]
      for (let y = 0; y < ws.length; y++) {
        await fetch(`/dashboard-pages/${pid}/widgets`, { method: 'POST', headers: H,
          body: JSON.stringify({ ...ws[y], position_x: 0, position_y: y }) })
      }
      return d.id
    }, { mark: MARK, code: CODE, notClosed: NOT_CLOSED })

    await page.goto(`${BASE}/?s=dashboards&d=${dashId}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2500)

    // ── Матрица рисков ─────────────────────────────────────────────────────
    const matrix = card(page, 'Матрица рисков')
    await matrix.scrollIntoViewIfNeeded()
    await page.waitForTimeout(800)
    await shot(matrix, 'v12_matrix')

    // ── Счётчики: строка карточек с оговоркой про нераспознанный срок ──────
    {
      const a = await card(page, 'Высокий риск').boundingBox()
      const c = await card(page, 'Вопросов в работе').boundingBox()
      await page.evaluate((y) => window.scrollTo(0, window.scrollY + y - 120), a.y)
      await page.waitForTimeout(500)
      const a2 = await card(page, 'Высокий риск').boundingBox()
      const c2 = await card(page, 'Вопросов в работе').boundingBox()
      await shot(page, 'v12_counts', { clip: { x: a2.x - 6, y: a2.y - 6, width: c2.x + c2.width - a2.x + 12,
        height: Math.max(a2.height, c2.height) + 12 } })
      void c
    }

    // ── Конструктор: «Число строк» и условия ──────────────────────────────
    await page.getByRole('button', { name: '⋯' }).first().click()
    await page.getByText(/✎ Правка/).first().click()
    await page.waitForTimeout(800)
    await card(page, 'Срок решения истёк').locator('button[title="Изменить данные/тип виджета"]').click()
    await page.waitForTimeout(1500)
    const form = page.locator('[role=dialog]').first()
    if (await form.count()) {
      await shot(form, 'v12_form')
    } else {
      const f = page.locator('form, div', { hasText: 'Что показать' }).last()
      await shot(f, 'v12_form')
    }
    await page.keyboard.press('Escape')

    // ── Лента особо значимых на настоящем дашборде (только чтение) ─────────
    const merId = psql(`select id from dashboards where name = '${MER}' limit 1`).trim()
    if (merId) {
      await page.goto(`${BASE}/?s=dashboards&d=${merId}`, { waitUntil: 'networkidle' })
      await page.waitForTimeout(2000)
      await page.getByRole('button', { name: 'Итоги недели', exact: true }).click()
      await page.waitForTimeout(2500)
      const feed = card(page, 'Особо значимые результаты недели')
      await feed.scrollIntoViewIfNeeded()
      await page.waitForTimeout(600)
      await shot(feed, 'v12_feed')
    } else {
      console.log('  — дашборда Минэкономразвития нет, кадр ленты пропущен')
    }
  } finally {
    await browser.close()
    cleanup()
  }
})().catch((e) => { console.error(e); cleanup(); process.exit(1) })
