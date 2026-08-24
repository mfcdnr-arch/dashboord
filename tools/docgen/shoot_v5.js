// Досъёмка разделов 18.08–25.08.2026: раздел пользователя, перестройка вида
// ①–⑤ (шапка/поток/матрица/индекс/прогноз/«На что посмотреть»/«Загрузка»),
// сводный «План/факт», и вся вторая волна предложений (плотность, экспорт
// виджета, паспорт цифры, владелец показателя, календарь поступлений,
// «призрак» прошлого отчёта, внутренняя сверка, предпросмотр выпуска,
// комментарий к цифре, Ctrl+K).
//
//   node shoot_v5.js            → shots/60_*.png … 78_*.png
//
// Часть кадров снимается НА РЕАЛЬНОМ дашборде заказчика (только чтение —
// GET/просмотр, ни один клик не подтверждает выпуск/создание/публикацию).
// Часть — на СВОЁМ временном дашборде (5 районов × 2 недели, тот же набор,
// что использовался при живой проверке «призрака» 24.08): у реального
// дашборда заказчика нет ни одного bar/line-виджета (только kpi/dynamics/
// compare/table), поэтому «призрак» и матрицу показать на нём нельзя —
// временные данные создаются и убираются в конце скрипта.
//
// Пароль viewer1 на дев-стенде был утерян (не подходил ни один из ранее
// записанных) — сброшен через админский reset-password и снят флаг
// must_change_password (это учётная запись докгена, не реальный человек).
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
  await page.waitForTimeout(2200)
}

const nav = async (page, section) => {
  await page.evaluate((s) => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === s)
    if (b) b.click()
  }, section)
  await page.waitForTimeout(1800)
}

const clickDeepest = async (page, re) => {
  const ok = await page.evaluate((pattern) => {
    const rx = new RegExp(pattern)
    const els = [...document.querySelectorAll('*')].filter((e) => e.children.length === 0 && rx.test(e.textContent))
    if (!els.length) return false
    els[els.length - 1].click()
    return true
  }, re.source)
  if (!ok) throw new Error(`не найдено по /${re.source}/`)
  await page.waitForTimeout(1600)
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

const openDashboard = async (page, namePart) => {
  const ok = await page.evaluate((part) => {
    const t = [...document.querySelectorAll('[aria-label]')]
      .find((e) => /Открыть дашборд/.test(e.getAttribute('aria-label')) && e.getAttribute('aria-label').includes(part))
    if (!t) return false
    t.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    return true
  }, namePart)
  if (!ok) {
    const labels = await page.evaluate(() => [...document.querySelectorAll('[aria-label]')]
      .map((e) => e.getAttribute('aria-label')).filter((l) => /Открыть дашборд/.test(l)))
    throw new Error(`дашборд не найден: ${namePart}; доступные: ${JSON.stringify(labels)}`)
  }
  await page.waitForTimeout(4500)
}

// 🔴 ГРАБЛИ ДОКГЕНА (найдено 25.08): у шапки открытого дашборда с 22.08 крошка
// называется «← Дашборды» (со стрелкой), а не голым «Дашборды». Старый
// backToList в shoot_v3.js/shoot_v4.js ищет ТОЧНОЕ совпадение 'Дашборды' и
// попадает в пункт БОКОВОГО МЕНЮ — а он, по документированному тут же уроку,
// состояние ОТКРЫТОГО дашборда внутри DashboardsPage не сбрасывает (сбрасывает
// только `openDash` в App, но не внутренний `sel` страницы, которая
// смонтирована с пустыми deps на mount-эффекте). Следующий шаг сценария молча
// снимал кадр с прежнего дашборда. Чинить и в shoot_v3/v4 — отдельная правка.
const backToList = async (page) => {
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('*')]
      .filter((e) => e.children.length === 0 && /^←\s*Дашборды$/.test(e.textContent.trim()))
    all[all.length - 1]?.click()
  })
  await page.waitForTimeout(1800)
}

;(async () => {
  const admin = await login('admin', 'admin')

  // ── Временный дашборд для «призрака» и матрицы (у реального нет bar/line/matrix) ──
  console.log('Готовлю временные данные (5 районов × 2 недели)…')
  let tmpObjId, tmpDashId
  {
    const { execFileSync } = require('child_process')
    const sql = `
      do $$
      declare org uuid; adm uuid; obj uuid;
        r1 uuid; r2 uuid; i int;
        labels text[] := array['Донецк','Макеевка','Горловка','Мариуполь','Енакиево'];
        prev numeric[] := array[47000,38000,21000,29000,12000];
        cur  numeric[] := array[51000,41000,19500,33000,14200];
      begin
        select id, organization_id into adm, org from users where login='admin' limit 1;
        insert into objects(organization_id,name) values(org,'zdoc_ghost_obj') returning id into obj;
        insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,object_id)
          values(org,'zdoc_ghost_ds','Районы','released','2026-08-12',adm,obj) returning id into r1;
        insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,object_id)
          values(org,'zdoc_ghost_ds','Районы','released','2026-08-19',adm,obj) returning id into r2;
        for i in 1..5 loop
          insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number)
            values(r1, i-1, labels[i], 'zayavleniy', prev[i]);
          insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number)
            values(r2, i-1, labels[i], 'zayavleniy', cur[i]);
        end loop;
        insert into canonical_fields(object_id,code,name,data_type) values(obj,'zayavleniy','Принято заявлений','number');
      end $$;`
    execFileSync('docker', ['exec', '-i', 'dashbord_postgres', 'psql', '-U', 'dashbord', '-d', 'dashbord'],
      { input: sql, encoding: 'utf8' })
    tmpObjId = execFileSync('docker', ['exec', '-i', 'dashbord_postgres', 'psql', '-U', 'dashbord', '-d', 'dashbord',
      '-t', '-A', '-c', "select id::text from objects where name='zdoc_ghost_obj'"], { encoding: 'utf8' }).trim()
  }
  const tmpDash = await api('POST', '/dashboards', admin, { name: 'zdoc_призрак_и_матрица' })
  tmpDashId = tmpDash.id
  const tmpPage = await api('POST', `/dashboards/${tmpDashId}/pages`, admin, { name: 'Демо' })
  await api('POST', `/dashboard-pages/${tmpPage.id}/widgets`, admin, {
    name: 'Заявления по районам', widget_type: 'bar',
    config: { dataset_code: 'zdoc_ghost_ds', value_field: 'zayavleniy', ghost_prev: true },
    width: 7, height: 6,
  })
  await api('POST', `/dashboard-pages/${tmpPage.id}/widgets`, admin, {
    name: 'Заявления: по неделям', widget_type: 'matrix',
    config: { dataset_code: 'zdoc_ghost_ds', by: 'rows', value_field: 'zayavleniy' },
    width: 5, height: 6,
  })

  const browser = await chromium.launch()
  const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2, locale: 'ru-RU' })
  const page = await ctx.newPage()
  page.on('pageerror', (e) => console.log('  [pageerror]', e.message))
  page.on('console', (m) => { if (m.type() === 'error') console.log('  [console.error]', m.text()) })

  try {
    // ═══ ЧАСТЬ 1 — временный дашборд: призрак и матрица ═══════════════════
    console.log('Временный дашборд: призрак прошлого отчёта…')
    await uiLogin(page, 'admin', 'admin')
    await nav(page, 'Дашборды')
    await openDashboard(page, 'призрак_и_матрица')
    await page.waitForTimeout(1500)
    await shot(page, '60_ghost_and_matrix')
    await backToList(page)
    await page.waitForTimeout(1500)

    // ═══ ЧАСТЬ 2 — реальный дашборд заказчика (только чтение) ═════════════
    console.log('Дашборд заказчика: новая шапка…')
    await openDashboard(page, 'Внедрение сервиса МАХ')
    await page.waitForTimeout(1500)
    await shot(page, '61_new_header')

    console.log('«На что посмотреть»…')
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.waitForTimeout(600)
    try {
      await clickDeepest(page, /посмотреть$/)
      await page.waitForTimeout(800)
    } catch (e) { console.log('  (блок уже раскрыт или не найден:', e.message, ')') }
    await shot(page, '62_attention_block')

    // 🔴 ГРАБЛИ (найдено 25.08): PassportDialog НЕ слушает Escape (закрывается
    // только кликом по backdrop или по кнопке ✕) — `page.keyboard.press('Escape')`
    // молча ничего не делал, диалог оставался смонтированным (портал в body) и
    // засвечивал ВСЕ следующие кадры до первой полной смены страницы. Закрывать
    // только явным кликом по ✕ внутри самого верхнего fixed-блока.
    const closeTopModal = async (page) => {
      await page.evaluate(() => {
        const fixed = [...document.querySelectorAll('div')].filter((d) => {
          const cs = getComputedStyle(d)
          return cs.position === 'fixed' && d.offsetWidth > 200 && d.offsetHeight > 100
        })
        const top = fixed[fixed.length - 1]
        const btn = top && [...top.querySelectorAll('button')].find((b) => b.textContent.trim() === '✕')
        if (btn) btn.click()
      })
      await page.waitForTimeout(600)
    }

    console.log('Паспорт цифры…')
    try {
      await clickBtn(page, 'куда дальше')
      await page.waitForTimeout(1000)
      await clickDeepest(page, /Паспорт цифры/)
      await page.waitForTimeout(1500)
      await shot(page, '63_passport')
      await closeTopModal(page)
    } catch (e) { console.log('  ⚠ паспорт цифры:', e.message) }

    console.log('Замечание к цифре…')
    try {
      // Реального замечания на дашборде заказчика нет ни у одного ВИДЖЕТА
      // (есть только одно — старое, привязанное ко всему ОТЧЁТУ, п. 8) —
      // кадр честно показывает пустое состояние панели и форму отправки.
      await page.evaluate(() => {
        const b = [...document.querySelectorAll('button')].find((x) => /замечание$/.test(x.textContent.trim()))
        b?.click()
      })
      await page.waitForTimeout(1000)
      await shot(page, '64_widget_comment')
      await closeTopModal(page)
    } catch (e) { console.log('  ⚠ комментарий к цифре:', e.message) }

    console.log('Плотность «компактно/просторно»…')
    try {
      await clickBtn(page, 'Компактнее')
      await page.waitForTimeout(900)
      await shot(page, '65_density_compact')
      await clickBtn(page, 'Просторнее')
      await page.waitForTimeout(900)
    } catch (e) { console.log('  ⚠ плотность:', e.message) }

    console.log('Экспорт одного виджета…')
    try {
      // На широкой карточке кнопки подвала не сворачиваются в «⋯» (это
      // происходит только когда подвал уже ~300px) — «⤓ Excel» видна сразу.
      // Ищем её по title, скроллим карточку в кадр и снимаем окрестность.
      const found = await page.evaluate(() => {
        const btn = [...document.querySelectorAll('button')]
          .find((b) => /Выгрузить данные этого виджета в Excel/.test(b.getAttribute('title') || ''))
        if (!btn) return false
        btn.scrollIntoView({ block: 'center' })
        return true
      })
      if (!found) throw new Error('кнопка «⤓ Excel» не найдена ни в одном виджете')
      await page.waitForTimeout(700)
      await shot(page, '66_widget_export_menu')
    } catch (e) { console.log('  ⚠ кнопка экспорта виджета:', e.message) }

    await backToList(page)

    console.log('Выпуск: что изменится на дашбордах + внутренняя сверка…')
    try {
      await nav(page, 'Объекты')
      await page.waitForTimeout(1500)
      await clickDeepest(page, /МФЦ ДНР/)
      await clickDeepest(page, /Внедрение сервиса/)
      await page.waitForTimeout(1500)
      await page.evaluate(() => {
        const els = [...document.querySelectorAll('*')]
          .filter((e) => e.children.length === 0 && /19\.08\.2026\.xlsx/.test(e.textContent))
        els[els.length - 1]?.click()
      })
      await page.waitForTimeout(2500)
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
      await page.waitForTimeout(2500)
      await shot(page, '67_internal_checks')
      try {
        await clickBtn(page, 'посмотреть')
        await page.waitForTimeout(1200)
        await shot(page, '68_release_impact')
      } catch (e) { console.log('  ⚠ раскрыть «что изменится»:', e.message) }
    } catch (e) { console.log('  ⚠ разметка документа:', e.message) }

    console.log('Календарь поступлений…')
    try {
      await clickBtn(page, '← Назад к документам')
      await page.waitForTimeout(2000)
      await clickBtn(page, 'Аналитика папки')
      await page.waitForTimeout(2500)
      await shot(page, '69_folder_calendar')
    } catch (e) { console.log('  ⚠ аналитика папки:', e.message) }

    console.log('Владелец показателя…')
    try {
      await nav(page, 'Метрики')
      await page.waitForTimeout(2000)
      await page.evaluate(() => {
        const els = [...document.querySelectorAll('*')].filter((e) => e.children.length === 0 && /Доля доставленных/.test(e.textContent))
        els[0]?.click()
      })
      await page.waitForTimeout(1500)
      // Поле «Ответственный» — у САМОГО ВЕРХА карточки; без scrollTo кадр
      // однажды уезжает вниз (к библиотеке готовых формул) вслед за прошлым
      // положением скролла страницы списка.
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.waitForTimeout(400)
      await shot(page, '70_metric_owner')
    } catch (e) { console.log('  ⚠ карточка показателя:', e.message) }

    console.log('Сводный «План/факт» (только предпросмотр)…')
    try {
      await nav(page, 'Дашборды')
      await page.waitForTimeout(1500)
      await clickBtn(page, 'План/факт')
      await page.waitForTimeout(2000)
      await shot(page, '71_planfact_preview')
      await page.keyboard.press('Escape')
      await page.waitForTimeout(500)
    } catch (e) { console.log('  ⚠ план/факт:', e.message) }

    console.log('Раздел «Загрузка»…')
    try {
      await nav(page, 'Загрузка')
      await page.waitForTimeout(1800)
      await shot(page, '72_upload_zone')
    } catch (e) { console.log('  ⚠ загрузка:', e.message) }

    console.log('Ctrl+K…')
    try {
      await page.keyboard.down('Control')
      await page.keyboard.press('K')
      await page.keyboard.up('Control')
      await page.waitForTimeout(500)
      await page.keyboard.type('внедрение')
      await page.waitForTimeout(900)
      await shot(page, '73_ctrlk')
      await page.keyboard.press('Escape')
    } catch (e) { console.log('  ⚠ Ctrl+K:', e.message) }

    // ═══ ЧАСТЬ 3 — раздел пользователя (viewer1) ═══════════════════════════
    console.log('Главная пользователя…')
    await uiLogin(page, 'viewer1', 'Viewer1pass!')
    await page.waitForTimeout(1500)
    // У обычного пользователя раздел по умолчанию — «Дашборды», не «Главная»
    // (см. App.tsx: `staff ? 'home' : 'dashboards'`) — переходим явно.
    await nav(page, 'Главная')
    await shot(page, '74_user_home')

    console.log('Инструкции (пользователь)…')
    try {
      await nav(page, 'Инструкции')
      await page.waitForTimeout(1800)
      await shot(page, '75_instructions_user')
    } catch (e) { console.log('  ⚠ инструкции:', e.message) }

    // ═══ ЧАСТЬ 4 — инструкции и объявления (админ, временная запись) ═══════
    console.log('Инструкции и объявления (администратор)…')
    // Название БЕЗ префикса zdoc_: удаление идёт по id из ответа создания, а
    // не поиском по имени, поэтому маркер тут не нужен — а вот в кадре
    // документации техническая приставка выглядела бы неряшливо.
    const instr = await api('POST', '/instructions', admin, {
      title: 'Как загрузить недельный отчёт', body: 'Перетащите файл в раздел «Загрузка» — систему разберёт его сама и разложит по нужной папке.',
      section: 'Загрузка данных', is_published: true,
    }).catch((e) => { console.log('  ⚠ создать инструкцию:', e.message); return null })
    const ann = await api('POST', '/announcements', admin, {
      title: 'Плановое обслуживание', body: '24.08 с 22:00 до 23:00 возможны кратковременные перебои при обновлении сервера.',
      important: true, ends_at: '2027-01-01',
    }).catch((e) => { console.log('  ⚠ создать объявление:', e.message); return null })
    try {
      await uiLogin(page, 'admin', 'admin')
      await nav(page, 'Инструкции')
      await page.waitForTimeout(1800)
      await clickBtn(page, '✎ Инструкции')
      await page.waitForTimeout(1200)
      await shot(page, '76_instructions_admin')
      await clickBtn(page, '📢 Объявления')
      await page.waitForTimeout(1200)
      await shot(page, '77_announcements_admin')
    } catch (e) { console.log('  ⚠ инструкции/объявления (админ):', e.message) }
    if (instr) await api('DELETE', `/instructions/${instr.id}`, admin).catch((e) => console.log('  ⚠ убрать инструкцию:', e.message))
    if (ann) await api('DELETE', `/announcements/${ann.id}`, admin).catch((e) => console.log('  ⚠ убрать объявление:', e.message))

    console.log('Готово. Кадры в', SHOTS)
  } finally {
    await browser.close()
    console.log('Уборка временных данных…')
    const { execFileSync } = require('child_process')
    try {
      if (tmpDashId) {
        execFileSync('docker', ['exec', '-i', 'dashbord_postgres', 'psql', '-q', '-U', 'dashbord', '-d', 'dashbord', '-c', `
          delete from widgets where dashboard_id='${tmpDashId}';
          delete from dashboard_pages where dashboard_id='${tmpDashId}';
          delete from securable_objects where object_type='dashboard' and object_id='${tmpDashId}';
          delete from dashboards where id='${tmpDashId}';
        `])
      }
      execFileSync('docker', ['exec', '-i', 'dashbord_postgres', 'psql', '-q', '-U', 'dashbord', '-d', 'dashbord', '-c', `
        delete from dataset_values where dataset_release_id in (select id from dataset_releases where code='zdoc_ghost_ds');
        delete from dataset_releases where code='zdoc_ghost_ds';
        delete from canonical_fields where object_id in (select id from objects where name='zdoc_ghost_obj');
        delete from objects where name='zdoc_ghost_obj';
      `])
      console.log('  временные данные убраны')
    } catch (e) { console.log('  ⚠ уборка:', e.message) }
  }
})()
