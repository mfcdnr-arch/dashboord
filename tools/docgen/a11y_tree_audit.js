// Аудит «глазами программы чтения с экрана» (11.10.2026).
//
//   node a11y_tree_audit.js            → отчёт в консоль и out/a11y_tree_audit.json
//
// Диктор (NVDA, JAWS, VoiceOver) читает не HTML, а ДЕРЕВО ДОСТУПНОСТИ, которое
// строит браузер: роль, вычисленное имя и состояние каждого элемента. Здесь это
// дерево берётся у самого Chromium (CDP `Accessibility.getFullAXTree`) — то же,
// что получил бы диктор, — на ключевых экранах под администратором и рядовым
// пользователем. Скрипт только читает: ничего не создаёт и не меняет.
//
// Что считается находкой:
//   • элемент управления без имени (диктор скажет «кнопка» — и всё);
//   • картинка / график без текстового описания;
//   • окно (dialog) без имени;
//   • фокусируемый элемент без роли (div с tabindex — диктор не скажет, что это);
//   • страница без заголовка первого уровня или без основного ориентира (main);
//   • пропуск уровня заголовка (h1 → h3).
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

const BASE = process.env.DOCGEN_BASE || 'http://localhost:3080'
const INTERACTIVE = new Set(['button', 'link', 'textbox', 'searchbox', 'combobox', 'checkbox', 'radio',
  'switch', 'tab', 'menuitem', 'slider', 'spinbutton', 'listbox', 'option', 'menuitemcheckbox', 'treeitem'])
const LANDMARKS = new Set(['main', 'navigation', 'banner', 'contentinfo', 'complementary', 'search', 'region', 'form'])

const val = (p) => (p && p.value !== undefined ? p.value : undefined)
// Свойство узла: {name, value: {type, value}} — разворачиваем оба уровня.
const prop = (n, name) => val(val((n.properties || []).find((p) => p.name === name)))

async function snapshot(page, label) {
  const cdp = await page.context().newCDPSession(page)
  const { nodes } = await cdp.send('Accessibility.getFullAXTree')
  const live = nodes.filter((n) => !n.ignored)
  const out = { screen: label, unnamed: [], images: [], dialogs: [], roleless: [], headings: [], landmarks: [], live: [], where: [] }
  // Где именно находка: начало разметки элемента — чтобы найти его в коде.
  const where = async (n) => {
    if (!n.backendDOMNodeId) return
    try {
      const { object } = await cdp.send('DOM.resolveNode', { backendNodeId: n.backendDOMNodeId })
      const { result } = await cdp.send('Runtime.callFunctionOn', { objectId: object.objectId, returnByValue: true,
        functionDeclaration: 'function(){return (this.outerHTML||String(this.textContent)).slice(0,160)}' })
      out.where.push(`${val(n.role)}: ${result.value}`)
    } catch { /* узел мог исчезнуть */ }
  }
  for (const n of live) {
    const role = val(n.role) || ''
    const name = (val(n.name) || '').trim()
    if (INTERACTIVE.has(role) && !name && !prop(n, 'hidden')) { out.unnamed.push(role); await where(n) }
    if ((role === 'img' || role === 'image') && !name) { out.images.push(role); await where(n) }
    if ((role === 'dialog' || role === 'alertdialog') && !name) out.dialogs.push(role)
    if ((role === 'generic' || role === 'none' || role === 'StaticText') && prop(n, 'focusable')) out.roleless.push(name || '(без текста)')
    if (role === 'heading') out.headings.push({ level: prop(n, 'level'), name: name.slice(0, 60) })
    if (LANDMARKS.has(role)) out.landmarks.push(role + (name ? `: ${name.slice(0, 40)}` : ''))
    const lv = prop(n, 'live')
    if (lv && lv !== 'off') out.live.push(`${role}/${lv}`)
  }
  const h1 = out.headings.filter((h) => h.level === 1).length
  out.problems = []
  // Открыто модальное окно — фон заморожен (inert), и диктор видит только окно.
  // Тогда требования другие: у окна есть имя и свой заголовок, а h1 и main
  // страницы и не должны быть доступны.
  const modal = live.some((n) => ['dialog', 'alertdialog'].includes(val(n.role)) && prop(n, 'modal'))
  if (modal) {
    out.modal = true
    if (!out.headings.length) out.problems.push('у окна нет заголовка')
  } else {
    if (!h1) out.problems.push('нет заголовка первого уровня')
    if (h1 > 1) out.problems.push(`заголовков первого уровня: ${h1}`)
    if (!out.landmarks.some((l) => l.startsWith('main'))) out.problems.push('нет ориентира main')
  }
  let prev = 0
  for (const h of out.headings) {
    if (prev && h.level > prev + 1) { out.problems.push(`пропуск уровня: h${prev} → h${h.level} («${h.name}»)`); break }
    prev = h.level
  }
  // Повторы считаем по ролям, чтобы видеть масштаб, а не стену одинаковых строк.
  const count = (arr) => Object.entries(arr.reduce((m, x) => ({ ...m, [x]: (m[x] || 0) + 1 }), {}))
  out.unnamed = count(out.unnamed); out.images = out.images.length; out.dialogs = out.dialogs.length
  out.roleless = [...new Set(out.roleless)].slice(0, 8)
  out.live = count(out.live)
  out.total = live.length
  await cdp.detach()
  return out
}

async function login(page, user, pass) {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => localStorage.clear())
  await page.goto(BASE, { waitUntil: 'networkidle' })
  const inputs = page.locator('form input')
  await inputs.nth(0).fill(user)
  await inputs.nth(1).fill(pass)
  await page.getByRole('button', { name: 'Войти' }).click()
  await page.waitForTimeout(2500)
}

const clickText = (page, text) => page.evaluate((t) => {
  const els = [...document.querySelectorAll('button, a, div, span, td, li')]
    .filter((e) => e.textContent.trim() === t)
  if (!els.length) throw new Error('не найдено: ' + t)
  els[els.length - 1].click()
}, text)

;(async () => {
  const browser = await chromium.launch()
  const res = []
  try {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ru-RU' })
    const page = await ctx.newPage()
    const go = async (label, fn, wait = 2500) => {
      try { await fn(); await page.waitForTimeout(wait); res.push(await snapshot(page, label)) }
      catch (e) { res.push({ screen: label, error: String(e).slice(0, 200) }) }
    }

    await page.goto(BASE, { waitUntil: 'networkidle' })
    await page.evaluate(() => localStorage.clear())
    await go('Вход', () => page.goto(BASE, { waitUntil: 'networkidle' }), 800)

    await login(page, 'admin', 'admin')
    await go('Главная (администратор)', async () => {})
    await go('Дашборды — список', () => page.goto(BASE + '/?s=dashboards', { waitUntil: 'networkidle' }))
    await go('Дашборд Минэкономразвития — «Итоги недели» (таблица)', async () => {
      await clickText(page, 'МФЦ ДНР — еженедельный отчёт для Минэкономразвития'); await page.waitForTimeout(2500)
      await page.getByRole('button', { name: /Итоги недели/ }).first().click()
    }, 3500)
    await go('Дашборд РЦО — «Обзор» (графики)', async () => {
      await page.goto(BASE + '/?s=dashboards', { waitUntil: 'networkidle' })
      await clickText(page, 'РЦО: ежедневный отчёт по услугам')
    }, 5000)
    await go('Окно «О дашборде»', async () => {
      await page.locator('button[aria-label*="О дашборде"], button[title*="О дашборде"]').first().click()
    }, 1200)
    await page.keyboard.press('Escape')
    await go('Колокольчик открыт', async () => {
      await page.locator('button[aria-label^="Уведомления"]').first().click()
    }, 1200)
    await page.keyboard.press('Escape')
    await go('Объект Минэкономразвития', async () => {
      await page.goto(BASE + '/?s=objects', { waitUntil: 'networkidle' })
      await clickText(page, 'МФЦ ДНР — отчёт Минэкономразвития')
    }, 3000)
    await go('Разметка книги', async () => {
      await page.locator('main').getByText('Отчёты', { exact: true }).last().click(); await page.waitForTimeout(1800)
      await clickText(page, 'Отчёт_МФЦ_06-10-2026.xlsx')
    }, 4000)
    await go('Загрузка', () => page.goto(BASE + '/?s=uploads', { waitUntil: 'networkidle' }))
    await go('Отчёты (здоровье, бэкап)', () => page.goto(BASE + '/?s=reports', { waitUntil: 'networkidle' }), 3500)
    await go('Настройки', () => page.goto(BASE + '/?s=settings', { waitUntil: 'networkidle' }))
    await go('Карта', () => page.goto(BASE + '/?s=map', { waitUntil: 'networkidle' }), 3500)
    await go('Пользователи', () => page.goto(BASE + '/?s=users', { waitUntil: 'networkidle' }))
  } finally {
    await browser.close()
  }
  fs.writeFileSync(path.join(__dirname, 'out', 'a11y_tree_audit.json'), JSON.stringify(res, null, 2))
  for (const r of res) {
    if (r.error) { console.log(`✗ ${r.screen}: ${r.error}`); continue }
    const flags = [
      r.unnamed.length ? `без имени: ${r.unnamed.map(([k, v]) => `${k}×${v}`).join(', ')}` : '',
      r.images ? `картинок без описания: ${r.images}` : '',
      r.dialogs ? `окон без имени: ${r.dialogs}` : '',
      r.roleless.length ? `фокус без роли: ${r.roleless.join(' | ')}` : '',
      ...r.problems,
    ].filter(Boolean)
    console.log(`${flags.length ? '⚠' : '✓'} ${r.screen} — узлов ${r.total}; заголовки: ${r.headings.length}; ориентиры: ${[...new Set(r.landmarks)].join(', ')}`)
    for (const f of flags) console.log('    ' + f)
    for (const w of [...new Set(r.where)].slice(0, 6)) console.log('      · ' + w)
  }
})()
