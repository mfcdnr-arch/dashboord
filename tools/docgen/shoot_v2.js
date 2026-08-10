// Досъёмка кадров для функций августа 2026 (после 04.08) + переснятие экранов,
// которые с тех пор заметно изменились.
// Требует: dev-фронт :3080, dev-api :8080, admin/admin.
//
// Отличие от shoot_all.js: тот рассчитан на синтетические данные прежнего стенда
// («Динамика МФЦ», «Динамика тест»), а здесь снимаем на РЕАЛЬНЫХ данных заказчика,
// которые сейчас на стенде, — документация получается с настоящими показателями.
// Кадры кладутся в тот же shots/ и подхватываются doc_*.js.
const { chromium } = require('playwright');
const { execSync } = require('child_process');

const BASE = 'http://localhost:3080';
const OUT = __dirname + '/shots/';
const fails = [];

function psql(sql) {
  return execSync(`docker exec -i dashbord_postgres psql -U dashbord -d dashbord -v ON_ERROR_STOP=1`, {
    input: sql, encoding: 'utf8',
  });
}

async function shot(page, name, opts = {}) {
  try {
    await page.waitForTimeout(opts.wait ?? 1200);
    await page.screenshot({ path: OUT + name + '.png', fullPage: !!opts.full });
    console.log('OK ' + name);
  } catch (e) { fails.push(name + ': ' + e.message.split('\n')[0]); }
}

async function login(page, user, pass) {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => localStorage.clear());
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const inputs = page.locator('form input');
  await inputs.nth(0).fill(user);
  await inputs.nth(1).fill(pass);
  await page.getByRole('button', { name: 'Войти' }).click();
  await page.waitForTimeout(1800);
}

// Модальные окна закрываем по-настоящему: пока на экране есть элемент с
// position:fixed, жмём его крестик (он может быть ✕, × или иметь title
// «Закрыть»). Иначе следующий клик по меню уходит «под» окно и кадр снимается
// не тот — именно так первый прогон снял дашборд вместо раздела «Объекты».
async function closeOverlays(page) {
  for (let i = 0; i < 5; i++) {
    const closed = await page.evaluate(() => {
      const fixed = [...document.querySelectorAll('div')].filter((d) => {
        const cs = getComputedStyle(d);
        return cs.position === 'fixed' && d.offsetWidth > 200 && d.offsetHeight > 100;
      });
      if (!fixed.length) return false;
      const top = fixed[fixed.length - 1];
      const btn = [...top.querySelectorAll('button')].find((b) => {
        const t = b.textContent.trim();
        return t === '✕' || t === '×' || /закрыть/i.test(b.getAttribute('title') || '');
      });
      if (btn) { btn.click(); return true; }
      return false;
    });
    if (!closed) break;
    await page.waitForTimeout(400);
  }
  await page.keyboard.press('Escape').catch(() => {});
  await page.waitForTimeout(300);
}

async function nav(page, label) {
  await closeOverlays(page);
  try { await page.getByRole('button', { name: label, exact: true }).first().click({ timeout: 8000 }); }
  catch { fails.push('nav ' + label); }
  await page.waitForTimeout(1300);
}

// Клик по «самому глубокому элементу с этим текстом» — названия в списках лежат
// текст-нодами среди значков, отдельного leaf-элемента нет.
async function clickText(page, text) {
  let lastErr;
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      await page.evaluate((t) => {
        const els = [...document.querySelectorAll('*')].filter((e) => {
          const s = e.textContent.replace(/\s+/g, ' ').trim();
          return s.includes(t) && s.length < t.length + 45;
        });
        if (els.length) els[els.length - 1].click(); else throw new Error('нет элемента: ' + t);
      }, text);
      await page.waitForTimeout(1600);
      return;
    } catch (e) { lastErr = e; await page.waitForTimeout(900); }
  }
  fails.push('clickText ' + text + ': ' + (lastErr && lastErr.message || '').split('\n')[0]);
}

async function openDashboard(page, part) {
  await page.evaluate((p) => {
    const el = [...document.querySelectorAll('*')].find((e) => (e.getAttribute('aria-label') || '').includes(p));
    if (el) el.click();
  }, part);
  await page.waitForTimeout(3000);
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: 'ru-RU' });
  const page = await ctx.newPage();

  // ── Модератор/админ: метрики ──────────────────────────────────────────────
  await login(page, 'admin', 'admin');
  await nav(page, 'Метрики');
  await closeOverlays(page);
  await shot(page, '30_metric_data_suggestions', { full: true }); // «Что можно посчитать по вашим данным»

  await clickText(page, 'Доля доставленных');
  await shot(page, '31_metric_info_auto', { full: true });        // автозаполненное описание показателя
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.includes('📚 Готовые'));
    if (b) b.click();
  });
  await shot(page, '32_metric_templates');                        // библиотека готовых рецептов
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => x.innerText.startsWith('Процент (доля A от B)'));
    if (b) b.click();
  });
  await shot(page, '33_metric_template_form');                    // рецепт: выбор столбцов

  // ── Дашборды: карточка «О дашборде», правка, состав ────────────────────────
  await nav(page, 'Дашборды');
  await closeOverlays(page);
  await shot(page, '34_dashboards_list');
  await openDashboard(page, 'еженедельный доклад');
  await shot(page, '35_dashboard_view', { full: true });
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => (x.getAttribute('title') || '').includes('Что это за дашборд'));
    if (b) b.click();
  });
  await shot(page, '36_dashboard_about');                         // ℹ О дашборде: состав и источники цифр
  await closeOverlays(page);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.includes('Двигать и менять размер'));
    if (b) b.click();
  });
  await shot(page, '37_dashboard_layout_mode');                   // режим раскладки с подсказкой
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.includes('Готово'));
    if (b) b.click();
  });

  // ── Объекты: конструктор разметки документа ───────────────────────────────
  await nav(page, 'Объекты');
  await closeOverlays(page);
  await shot(page, '38_objects', { full: true });

  // ── Взгляд обычного пользователя: меню сведено к дашбордам ────────────────
  await login(page, 'viewer1', 'Mfc2026view');
  await page.waitForTimeout(1500);
  // первый вход требует смены пароля — если экран появился, задаём новый
  const needChange = await page.locator('text=Смена пароля').isVisible().catch(() => false);
  if (needChange) {
    const ins = page.locator('input[type=password]');
    await ins.nth(0).fill('Mfc2026view');
    await ins.nth(1).fill('Mfc2026view');
    await page.getByRole('button', { name: 'Сохранить' }).click();
    await page.waitForTimeout(2000);
  }
  await closeOverlays(page);
  await shot(page, '39_viewer_menu', { full: true });             // у зрителя только «Дашборды» и «Кабинет»

  await browser.close();
  console.log(fails.length ? 'ПРОБЛЕМЫ:\n' + fails.join('\n') : 'ALL DONE');
})();
