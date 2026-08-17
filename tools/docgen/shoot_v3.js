// Съёмка скриншотов для разделов, добавленных 12–17.08.2026:
// фильтр периода (изменил поведение), обратная связь с виджета, запрос доступа,
// аналитика папки, раздел «Руководителю», меню «куда дальше».
//
//   node shoot_v3.js            → shots/*.png
//
// Предпосылки: dev-стек поднят, API на :8080, фронт (vite) на :3080,
// учётка admin/admin, на стенде есть объект с выпущенными данными и дашборд.
//
// Технические уроки (не ломать — каждый стоил отдельного разбирательства):
//  • клик по строкам списков — через page.evaluate по «самому глубокому
//    элементу с текстом»: названия лежат текстовыми нодами среди span'ов;
//  • ВОЗВРАТ из открытого дашборда к списку — ХЛЕБНОЙ КРОШКОЙ: кнопка раздела
//    в навигации состояние открытого дашборда не сбрасывает, и следующий шаг
//    сценария снимет не тот экран;
//  • открытие дашборда — по aria-label «Открыть дашборд «…»»: строка списка
//    это div с onClick, а не ссылка;
//  • у React-полей значение ставится нативным сеттером + событием input,
//    иначе состояние компонента не меняется и фильтр не срабатывает.
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

const nav = async (page, section) => {
  await page.evaluate((s) => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === s)
    if (b) b.click()
  }, section)
  await page.waitForTimeout(1800)
}

/** Из открытого дашборда — назад к списку. Только крошкой (см. урок выше). */
const backToList = async (page) => {
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('*')]
      .filter((e) => e.children.length === 0 && e.textContent.trim() === 'Дашборды')
    all[all.length - 1]?.click()
  })
  await page.waitForTimeout(1800)
}

const openDashboard = async (page, namePart) => {
  const ok = await page.evaluate((part) => {
    const t = [...document.querySelectorAll('[aria-label]')]
      .find((e) => /Открыть дашборд/.test(e.getAttribute('aria-label'))
        && e.getAttribute('aria-label').includes(part))
    if (!t) return false
    t.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    return true
  }, namePart)
  if (!ok) throw new Error(`дашборд не найден: ${namePart}`)
  await page.waitForTimeout(5000)
}

const clickBtn = async (page, part) => {
  const ok = await page.evaluate((p) => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.includes(p))
    if (!b) return false
    b.click()
    return true
  }, part)
  if (!ok) throw new Error(`кнопка не найдена: ${part}`)
  await page.waitForTimeout(1800)
}

/** Значение в React-поле: нативный сеттер + событие input. */
const setInput = async (page, selector, index, value) => {
  await page.evaluate(([sel, i, v]) => {
    const el = [...document.querySelectorAll(sel)][i]
    const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    set.call(el, v)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  }, [selector, index, value])
  await page.waitForTimeout(400)
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

  console.log('Руководителю…')
  await nav(page, 'Руководителю')
  await page.waitForTimeout(2500)
  await shot(page, '56_leadership')

  console.log('Дашборд: фильтр периода…')
  await nav(page, 'Дашборды')
  await openDashboard(page, 'Внедрение')
  // Панель фильтров с быстрым выбором периода.
  await page.evaluate(() => window.scrollTo(0, 260))
  await page.waitForTimeout(800)
  await shot(page, '50_period_filter')

  // Период без отчётов: виджеты должны честно сказать, что данных нет.
  const dates = await page.evaluate(() => document.querySelectorAll('input[type=date]').length)
  await setInput(page, 'input[type=date]', dates - 2, '2020-01-01')
  await setInput(page, 'input[type=date]', dates - 1, '2020-12-31')
  await page.waitForTimeout(3500)
  await page.evaluate(() => window.scrollTo(0, 420))
  await page.waitForTimeout(700)
  await shot(page, '51_period_empty')
  // Сбрасываем фильтр — дальше снимаем нормальное состояние.
  await clickBtn(page, 'сброс')
  await page.waitForTimeout(3000)

  console.log('Меню «куда дальше»…')
  await clickBtn(page, 'куда дальше')
  await page.waitForTimeout(2200)
  await shot(page, '57_related_menu')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(800)

  console.log('Сообщить о проблеме…')
  await clickBtn(page, 'проблема')
  await page.waitForTimeout(1500)
  await shot(page, '52_report_problem')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(800)

  console.log('Аналитика папки…')
  await backToList(page)
  await nav(page, 'Объекты')
  await page.waitForTimeout(2000)
  await page.evaluate(() => {
    const els = [...document.querySelectorAll('*')]
      .filter((e) => e.children.length === 0 && /МФЦ ДНР/.test(e.textContent))
    els[els.length - 1]?.click()
  })
  await page.waitForTimeout(2500)
  await page.evaluate(() => {
    const els = [...document.querySelectorAll('*')]
      .filter((e) => e.children.length === 0 && /Внедрение сервиса/.test(e.textContent))
    els[els.length - 1]?.click()
  })
  await page.waitForTimeout(2500)
  try {
    await clickBtn(page, 'Аналитика папки')
    await page.waitForTimeout(3500)
    await shot(page, '55_folder_analytics')
  } catch (e) {
    console.log('  ⚠ аналитика папки:', e.message)
  }

  console.log('Готово. Кадры в', SHOTS)
  await browser.close()
})()
