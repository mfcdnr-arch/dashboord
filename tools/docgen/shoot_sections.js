// Съёмка скриншотов для разделов документации, добавленных после 31.07.2026
// (витрины, обращения, личный кабинет, папки дашбордов, аномалии, рекомендации,
// ретенция в UI, отчёт активности пользователя).
//
//   node shoot_sections.js            → shots/*.png
//
// Предпосылки: dev-стек поднят, API на :8080, фронт (vite) на :3080,
// учётка admin/admin, временные данные заведены `python3 prepare_data.py`.
//
// Технические уроки прошлого генератора (не ломать):
//  • клик по строкам списков — через page.evaluate по «самому глубокому
//    элементу, содержащему текст»: названия лежат текстовыми нодами среди
//    span'ов, точного leaf-селектора нет;
//  • возврат из открытого дашборда к списку — ХЛЕБНОЙ КРОШКОЙ (кнопка раздела
//    в навигации не сбрасывает состояние открытого дашборда).
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

// Клик по тексту: самый глубокий элемент, содержащий строку.
const clickText = async (page, text, tag = '*') => {
  const ok = await page.evaluate(([t, sel]) => {
    const els = [...document.querySelectorAll(sel)].filter((e) => e.textContent.includes(t))
    const deepest = els.filter((e) => !els.some((o) => o !== e && e.contains(o)))
    const el = deepest[deepest.length - 1]
    if (!el) return false
    el.click()
    return true
  }, [text, tag])
  if (!ok) throw new Error(`не нашёл элемент с текстом: ${text}`)
  await page.waitForTimeout(1200)
}

const nav = async (page, section) => {
  await page.evaluate((s) => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === s)
    if (b) b.click()
  }, section)
  await page.waitForTimeout(1500)
}

;(async () => {
  const browser = await chromium.launch()
  const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2, locale: 'ru-RU' })
  const page = await ctx.newPage()

  console.log('Вход…')
  await page.goto(BASE, { waitUntil: 'networkidle' })
  await page.fill('input >> nth=0', 'admin')
  await page.fill('input[type=password]', 'admin')
  await page.click('button:has-text("Войти")')
  await page.waitForTimeout(2500)

  console.log('Личный кабинет…')
  await nav(page, 'Кабинет')
  await shot(page, 'cabinet_profile')

  console.log('Обращения…')
  await nav(page, 'Обращения')
  await shot(page, 'appeals_list')
  await clickText(page, 'Услуги центра', 'div')
  await shot(page, 'appeals_thread')

  console.log('Витрины…')
  await nav(page, 'Витрины')
  await shot(page, 'showcases_list')
  await clickText(page, 'zdoc_Оперативная сводка', 'div')
  await shot(page, 'showcase_compose')
  await clickText(page, '👁 Просмотр', 'button')
  await page.waitForTimeout(3500)
  await shot(page, 'showcase_view')

  console.log('Дашборды: папки, аномалии, рекомендации…')
  await nav(page, 'Дашборды')
  await shot(page, 'dashboards_folders')
  await clickText(page, 'zdoc_Услуги центра', 'div')
  await page.waitForTimeout(3500)
  await shot(page, 'dashboard_anomalies')
  await clickText(page, '💡 Предложить ещё', 'button')
  await page.waitForTimeout(2000)
  await shot(page, 'suggest_widgets')
  await clickText(page, '💡 Предложить метрики', 'button')
  await page.waitForTimeout(2500)
  await shot(page, 'suggest_metrics')

  console.log('Настройки: ретенция…')
  await nav(page, 'Настройки')
  await page.waitForTimeout(1500)
  await shot(page, 'settings_retention', { fullPage: true })

  console.log('Пользователи: отчёт активности…')
  await nav(page, 'Пользователи')
  await page.waitForTimeout(1500)
  await clickText(page, '📊 активность', 'button')
  await page.waitForTimeout(2500)
  await shot(page, 'user_activity')

  await browser.close()
  console.log('ALL DONE')
})().catch((e) => {
  console.error('ОШИБКА:', e.message)
  process.exit(1)
})
