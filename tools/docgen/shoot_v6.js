// Досъёмка 27.08–11.09.2026: раздел «Статистика услуг ДНР», «Быстрый доступ»,
// подсказка «уже узнаются сами» на «Загрузке», ступени формы и лестница
// уровней (полоса, ветка, страница «Разбор по ступеням»), пять новых типов
// виджетов (bullet, thermometer, ranked, spark_table, field_list), матрица по
// месяцам, водопад по периодам, тепловая карта, честная обрезка «Сравнения».
//
//   node shoot_v6.js            → shots/80_*.png … 99_*.png
//
// Всё снимается на РЕАЛЬНЫХ данных дев-стенда (РЦО, МАХ, «Статистика услуг»):
// свои временные данные не нужны и не создаются. Действия только читающие —
// ни один клик не подтверждает выпуск, создание или публикацию.
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

const BASE = process.env.DOCGEN_BASE || 'http://localhost:3080'
const API = process.env.DOCGEN_API || 'http://127.0.0.1:8080'
const SHOTS = path.join(__dirname, 'shots')
const VIEWPORT = { width: 1440, height: 900 }

const shot = async (page, name, opts = {}) => {
  fs.mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), ...opts })
  console.log('  ✓', name)
}

const api = async (method, url, token, body) => {
  const res = await fetch(API + url, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
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
  if (!res.ok) throw new Error(`вход ${u} → ${res.status}: ${await res.text()}`)
  return (await res.json()).access_token
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

const nav = async (page, section) => {
  await page.evaluate((s) => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === s)
    if (b) b.click()
  }, section)
  await page.waitForTimeout(2200)
}

const clickBtn = async (page, part, wait = 1800) => {
  const ok = await page.evaluate((p) => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.includes(p))
    if (!b) return false
    b.click()
    return true
  }, part)
  if (!ok) throw new Error(`кнопка не найдена: ${part}`)
  await page.waitForTimeout(wait)
}

const clickExact = async (page, text, wait = 1800) => {
  const ok = await page.evaluate((t) => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === t)
    if (!b) return false
    b.click()
    return true
  }, text)
  if (!ok) throw new Error(`кнопка не найдена (точно): ${text}`)
  await page.waitForTimeout(wait)
}

const clickDeepest = async (page, re, wait = 1600) => {
  const ok = await page.evaluate((pattern) => {
    const rx = new RegExp(pattern)
    const els = [...document.querySelectorAll('*')].filter((e) => e.children.length === 0 && rx.test(e.textContent))
    if (!els.length) return false
    els[els.length - 1].click()
    return true
  }, re.source)
  if (!ok) throw new Error(`не найдено по /${re.source}/`)
  await page.waitForTimeout(wait)
}

// Ссылка прямо на страницу дашборда — тем же deep link, которым пользуется сам
// интерфейс. Надёжнее кликов по списку: не зависит ни от порядка строк, ни от
// того, какая страница открылась «последней» (грабли докгена 25.08).
const openPage = async (page, dashId, pageId) => {
  await page.goto(`${BASE}/?s=dashboards&d=${dashId}&p=${pageId}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(4200)
}

// Кадр ОДНОГО виджета: карточку ищем по data-widget-id, который ставит
// WidgetCard. По названию искать нельзя — у виджетов госформы имена длинные и
// повторяются кусками.
// Высокие виджеты (список показателей, матрица, строки с мини-графиками)
// обрезаем по высоте: в документе картинка тянется на ширину текста, и кадр с
// соотношением 1:2,8 занял бы две с половиной страницы, где всё равно ничего
// не разобрать. Показываем верх — этого хватает, чтобы увидеть устройство.
const MAX_ASPECT = 0.8
const shotWidget = async (page, widgetId, name) => {
  const loc = page.locator(`[data-widget-id="${widgetId}"]`)
  await loc.scrollIntoViewIfNeeded()
  await page.waitForTimeout(1200)
  let box = await loc.boundingBox()
  if (!box) throw new Error(`карточка не видна: ${widgetId}`)
  fs.mkdirSync(SHOTS, { recursive: true })
  const cap = box.width * MAX_ASPECT
  if (box.height <= cap) {
    await loc.screenshot({ path: path.join(SHOTS, `${name}.png`) })
  } else {
    // Ставим ВЕРХ карточки к верху окна и меряем заново: иначе высокий виджет
    // начинается у нижнего края, и обрезка выходит за пределы кадра.
    await page.evaluate((id) => {
      document.querySelector(`[data-widget-id="${id}"]`)?.scrollIntoView({ block: 'start' })
      // Липкая шапка страницы (вкладки + строка контекста) накрывает верх
      // карточки — отступаем, иначе в кадр попадает чужой заголовок.
      window.scrollBy(0, -130)
    }, widgetId)
    await page.waitForTimeout(900)
    box = await loc.boundingBox()
    const vh = page.viewportSize().height
    const top = Math.max(0, box.y)
    const height = Math.max(120, Math.min(cap, vh - top - 2))
    await page.screenshot({ path: path.join(SHOTS, `${name}.png`),
      clip: { x: box.x, y: top, width: box.width, height } })
  }
  console.log('  ✓', name, '(виджет)')
}

// Кадр произвольного блока по тексту внутри него: поднимаемся от самого
// глубокого элемента с этим текстом до предка нужной высоты.
const shotBlock = async (page, textPart, name, minH = 120) => {
  const handle = await page.evaluateHandle(({ t, mh }) => {
    const deep = [...document.querySelectorAll('*')]
      .filter((e) => e.children.length === 0 && e.textContent && e.textContent.includes(t))
    if (!deep.length) return null
    let el = deep[0]
    for (let i = 0; i < 10 && el; i++) {
      if (el.clientHeight >= mh && el.clientWidth > 300) return el
      el = el.parentElement
    }
    return el
  }, { t: textPart, mh: minH })
  const el = handle.asElement()
  if (!el) throw new Error(`блок не найден: ${textPart}`)
  await el.scrollIntoViewIfNeeded()
  await page.waitForTimeout(900)
  fs.mkdirSync(SHOTS, { recursive: true })
  await el.screenshot({ path: path.join(SHOTS, `${name}.png`) })
  console.log('  ✓', name, '(блок)')
}

;(async () => {
  const admin = await login('admin', 'admin')
  const dashboards = (await api('GET', '/dashboards', admin)).items
  const dash = (part) => {
    const d = dashboards.find((x) => x.name.includes(part))
    if (!d) throw new Error(`дашборд не найден: ${part}; есть: ${dashboards.map((x) => x.name).join(' | ')}`)
    return d
  }
  const pagesOf = async (id) => (await api('GET', `/dashboards/${id}`, admin)).pages
  const widgetsOf = async (pageId) => (await api('GET', `/dashboard-pages/${pageId}/widgets`, admin)).widgets
  const wid = (ws, type, namePart) => {
    const w = ws.find((x) => x.widget_type === type && (!namePart || x.name.includes(namePart)))
    if (!w) throw new Error(`виджет не найден: ${type} ${namePart || ''}`)
    return w.id
  }

  const rco = dash('РЦО: ежедневный отчёт')
  const okna = dash('окна и часы')
  const max = dash('Внедрение сервиса МАХ')
  const rcoPages = await pagesOf(rco.id)
  const maxPages = await pagesOf(max.id)
  const oknaPages = await pagesOf(okna.id)
  const p = (pages, n) => {
    const x = pages.find((q) => q.name === n)
    if (!x) throw new Error(`страница не найдена: ${n}; есть: ${pages.map((q) => q.name).join(' | ')}`)
    return x
  }

  const browser = await chromium.launch()
  const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2, locale: 'ru-RU' })
  const page = await ctx.newPage()
  page.on('pageerror', (e) => console.log('  [pageerror]', e.message))
  page.on('console', (m) => { if (m.type() === 'error') console.log('  [console.error]', m.text()) })

  const step = async (title, fn) => {
    console.log(title)
    try { await fn() } catch (e) { console.log('  ✗ ПРОПУЩЕНО:', e.message.slice(0, 220)) }
  }

  try {
    await uiLogin(page, 'admin', 'admin')

    // ═══ Раздел «Статистика услуг ДНР» ══════════════════════════════════
    await step('Статистика услуг: обзор…', async () => {
      await nav(page, 'Статистика услуг')
      await page.waitForTimeout(2500)
      await shot(page, '80_dnr_overview')
    })
    await step('Статистика услуг: сравнение ведомств…', async () => {
      await shotBlock(page, 'Ведомства в сравнении', '81_dnr_compare', 200)
    })
    await step('Статистика услуг: пробелы в услугах…', async () => {
      await shotBlock(page, 'Есть у соседей', '82_dnr_gaps', 200)
    })
    await step('Статистика услуг: список отделений…', async () => {
      await clickBtn(page, 'Список отделений', 2500)
      await shot(page, '83_dnr_offices')
      await clickBtn(page, 'Обзор', 1800)
    })

    // ═══ «Быстрый доступ» и «Загрузка» ══════════════════════════════════
    await step('Быстрый доступ…', async () => {
      await nav(page, 'Быстрый доступ')
      await page.waitForTimeout(1500)
      await shot(page, '84_quick_links')
    })
    await step('Загрузка: «уже узнаются сами»…', async () => {
      await nav(page, 'Загрузка')
      await page.waitForTimeout(1800)
      await clickDeepest(page, /узнаются сами/, 1400)
      await shot(page, '85_uploads_known_forms')
    })

    // ═══ Ступени формы на экране объекта ════════════════════════════════
    await step('Объекты: ступени формы…', async () => {
      await nav(page, 'Объекты')
      await page.waitForTimeout(1500)
      await clickDeepest(page, /^РЦО — ежедневный отчёт$/, 2500)
      await shotBlock(page, 'Ступени формы', '86_form_levels', 150)
    })

    // ═══ Лестница уровней на дашборде РЦО ═══════════════════════════════
    await step('Лестница: полоса над виджетами…', async () => {
      await openPage(page, rco.id, p(rcoPages, 'Обзор').id)
      await shotBlock(page, '🪜', '87_ladder_bar', 120)
    })
    await step('Лестница: спуск в ветку…', async () => {
      await clickDeepest(page, /^Росреестр$/, 3500)
      await shot(page, '88_ladder_branch')
    })
    await step('Лестница: страница «Разбор по ступеням»…', async () => {
      await openPage(page, rco.id, p(rcoPages, 'Разбор по ступеням').id)
      await shot(page, '89_ladder_page')
    })

    // ═══ Новые типы виджетов ════════════════════════════════════════════
    const ladderWs = await widgetsOf(p(rcoPages, 'Разбор по ступеням').id)
    await step('Показатели списком (field_list)…', async () => {
      await shotWidget(page, wid(ladderWs, 'field_list'), '90_field_list')
    })

    const rcoOverview = await widgetsOf(p(rcoPages, 'Обзор').id)
    await step('Ранжированный список…', async () => {
      await openPage(page, rco.id, p(rcoPages, 'Обзор').id)
      await shotWidget(page, wid(rcoOverview, 'ranked'), '91_ranked')
    })
    await step('Сравнение показателей: честная обрезка…', async () => {
      await shotWidget(page, wid(rcoOverview, 'compare'), '92_compare_trim')
    })

    const rcoDyn = await widgetsOf(p(rcoPages, 'Динамика').id)
    await step('Строки с мини-графиками…', async () => {
      await openPage(page, rco.id, p(rcoPages, 'Динамика').id)
      await shotWidget(page, wid(rcoDyn, 'spark_table'), '94_spark_table')
    })
    await step('Матрица по месяцам…', async () => {
      await shotWidget(page, wid(rcoDyn, 'matrix', 'месяцам'), '95_matrix_months')
    })
    await step('Водопад: вклад периодов…', async () => {
      await shotWidget(page, wid(rcoDyn, 'waterfall'), '96_waterfall_periods')
    })

    const rcoRaw = await widgetsOf(p(rcoPages, 'Первичные данные').id)
    await step('Тепловая карта: нагрузка по отделениям и услугам…', async () => {
      await openPage(page, rco.id, p(rcoPages, 'Первичные данные').id)
      await shotWidget(page, wid(rcoRaw, 'heatmap'), '97_heatmap')
    })

    const maxOverview = await widgetsOf(p(maxPages, 'Обзор').id)
    await step('Полосы план-факт…', async () => {
      await openPage(page, max.id, p(maxPages, 'Обзор').id)
      await shotWidget(page, wid(maxOverview, 'bullet'), '98_bullet')
    })
    await step('Термометр к сроку…', async () => {
      await shotWidget(page, wid(maxOverview, 'thermometer'), '99_thermometer')
    })

    await step('Блок «На что посмотреть» (на «окнах и часах» есть замечания)…', async () => {
      await openPage(page, okna.id, p(oknaPages, 'Обзор').id)
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.waitForTimeout(600)
      try { await clickDeepest(page, /^посмотреть$/, 1200) } catch (e) { /* уже раскрыт */ }
      await shotBlock(page, 'На что посмотреть', '93_attention', 60)
    })

    // Мини-график с подсказкой: наводим курсор на линию в карточке «окон и часов».
    await step('Мини-график: значение по наведению…', async () => {
      await openPage(page, okna.id, p(oknaPages, 'Обзор').id)
      const box = await page.evaluate(() => {
        const svg = document.querySelector('svg[aria-label^="Динамика по"]')
        if (!svg) return null
        const r = svg.parentElement.getBoundingClientRect()
        return { x: r.left + r.width * 0.45, y: r.top + r.height / 2 }
      })
      if (!box) throw new Error('мини-график не найден')
      await page.mouse.move(box.x, box.y)
      await page.waitForTimeout(800)
      // Кадрируем по САМОЙ карточке, а не по заранее подобранным числам: место
      // карточки на экране зависит от высоты шапки и от того, сколько строк
      // заняли «Как дела» и «На что посмотреть».
      const clip = await page.evaluate(() => {
        const svg = document.querySelector('svg[aria-label^="Динамика по"]')
        let el = svg
        for (let i = 0; i < 8 && el; i++) { if (el.hasAttribute && el.hasAttribute('data-widget-id')) break; el = el.parentElement }
        const r = (el || svg).getBoundingClientRect()
        // сверху оставляем место облачку — оно рисуется НАД точкой
        return { x: Math.max(0, r.left - 12), y: Math.max(0, r.top - 46),
                 width: Math.min(window.innerWidth - r.left + 12, r.width * 2 + 40), height: r.height + 60 }
      })
      await shot(page, '79_spark_tooltip', { clip })
    })
  } finally {
    await browser.close()
  }
  console.log('ALL DONE (v6)')
})()
