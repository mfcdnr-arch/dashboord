// Досъёмка двух кадров обратной связи (17.08.2026):
//  • карточка обращения, пришедшего кнопкой «⚑ проблема» с виджета — с
//    контекстом и кнопкой «Открыть отчёт →»;
//  • окно «Нужен отчёт, которого здесь нет» глазами обычного пользователя.
//
//   node shoot_v4.js            → shots/53_appeal_context.png, 54_request_access.png
//
// Скрипт САМ заводит временное обращение (от учётки зрителя, кнопкой с
// виджета) и САМ его убирает: оставлять тестовую переписку в системе нельзя.
// Учётка зрителя на дев-стенде: viewer1 / Viewer1pass!.
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

const BASE = process.env.DOCGEN_BASE || 'http://localhost:3080'
const API = process.env.DOCGEN_API || 'http://127.0.0.1:8080'
const SHOTS = path.join(__dirname, 'shots')
const VIEWPORT = { width: 1440, height: 900 }

const shot = async (page, name) => {
  fs.mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) })
  console.log('  ✓', name)
}

const api = async (method, url, token, body) => {
  const res = await fetch(API + url, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${method} ${url} → ${res.status} ${await res.text()}`)
  return res.status === 204 ? null : res.json()
}

const login = async (u, p) => {
  const res = await fetch(API + '/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: `username=${encodeURIComponent(u)}&password=${encodeURIComponent(p)}`,
  })
  if (!res.ok) throw new Error(`вход ${u} → ${res.status}`)
  return (await res.json()).access_token
}

const nav = async (page, section) => {
  await page.evaluate((s) => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim().startsWith(s))
    if (b) b.click()
  }, section)
  await page.waitForTimeout(1800)
}

;(async () => {
  const admin = await login('admin', 'admin')
  const viewer = await login('viewer1', 'Viewer1pass!')

  // Виджет, с которого «жалуется» зритель: берём тот, что ему доступен.
  const dash = (await api('GET', '/dashboards?limit=5', viewer)).items[0]
  if (!dash) throw new Error('зрителю не выдано ни одного дашборда — сначала выдайте доступ')
  const pages = (await api('GET', `/dashboards/${dash.id}`, viewer)).pages
  const widgets = (await api("GET", `/dashboard-pages/${pages[0].id}/widgets`, viewer)).widgets
  const widget = widgets.find((w) => w.widget_type === 'kpi') || widgets[0]

  console.log('Временное обращение с виджета…')
  const rep = await api('POST', `/widgets/${widget.id}/report-problem`, viewer, {
    kind: 'wrong_value', comment: 'Цифра не изменилась после нового отчёта',
  })

  const browser = await chromium.launch()
  const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2, locale: 'ru-RU' })
  const page = await ctx.newPage()

  try {
    console.log('Карточка обращения (администратор)…')
    await page.goto(BASE, { waitUntil: 'networkidle' })
    await page.fill('input >> nth=0', 'admin')
    await page.fill('input[type=password]', 'admin')
    await page.click('button:has-text("Войти")')
    await page.waitForTimeout(2500)
    await nav(page, 'Обращения')
    await page.evaluate(() => {
      const els = [...document.querySelectorAll('*')]
        .filter((e) => e.children.length === 0 && /Неверная цифра/.test(e.textContent))
      els[els.length - 1]?.click()
    })
    await page.waitForTimeout(2000)
    await shot(page, '53_appeal_context')

    console.log('Запрос доступа (зритель)…')
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === 'Выйти')
      if (b) b.click()
    })
    await page.waitForTimeout(1500)
    await page.fill('input >> nth=0', 'viewer1')
    await page.fill('input[type=password]', 'Viewer1pass!')
    await page.click('button:has-text("Войти")')
    await page.waitForTimeout(3000)
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find((x) => /Нужен другой отчёт/.test(x.textContent))
      if (b) b.click()
    })
    await page.waitForTimeout(1200)
    await shot(page, '54_request_access')
  } finally {
    await browser.close()
    // Уборка: тестовая переписка в системе остаться не должна.
    const { execFileSync } = require('child_process')
    const sql = `delete from appeal_messages where appeal_id='${rep.appeal_id}';`
      + `delete from audit_log where entity_id='${rep.appeal_id}';`
      + `delete from notification_recipients where notification_event_id in `
      + `(select id from notification_events where entity_id='${rep.appeal_id}');`
      + `delete from notification_events where entity_id='${rep.appeal_id}';`
      + `delete from appeals where id='${rep.appeal_id}';`
    execFileSync('docker', ['exec', '-i', 'dashbord_postgres', 'psql', '-q', '-U', 'dashbord', '-d', 'dashbord', '-c', sql])
    console.log('  временное обращение убрано')
  }
})()
