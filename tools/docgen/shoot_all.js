// Скриншоты Dashboard для документации — ПОЛНЫЙ набор одной командой.
// Требует: dev-фронт :3080, dev-api :8080, admin/admin.
// Сам создаёт и удаляет: учётки ztest_mod/ztest_user (через API нельзя задать
// пароль без смены — создаются через docker exec psql), временный архив-слепок.
const { chromium } = require('playwright');
const { execSync } = require('child_process');
const fs = require('fs');

const BASE = 'http://localhost:3080';
const API = 'http://127.0.0.1:8080';
const OUT = __dirname + '/shots/';
const fails = [];
fs.mkdirSync(OUT, { recursive: true });

// SQL передаём через stdin: bcrypt-хэши содержат `$` — argv через shell их портит.
const psql = (sql) => execSync(
  'docker exec -i dashbord_postgres psql -U dashbord -d dashbord -tA -v ON_ERROR_STOP=1',
  { encoding: 'utf8', input: sql.replace(/\s+/g, ' ').trim() + ';' }).trim();

async function apiToken(login = 'admin', pass = 'admin') {
  const r = await fetch(`${API}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: `username=${login}&password=${pass}` });
  return (await r.json()).access_token;
}

// ── Временные данные ─────────────────────────────────────────────────────────
function prepUsers() {
  const hash = execSync(`docker exec dashbord_api python -c "from app.modules.auth.security import hash_password; print(hash_password('Ztest12345'))"`, { encoding: 'utf8' }).trim();
  psql(`with org as (select id from organizations limit 1)
    insert into users(organization_id, login, full_name, password_hash, must_change_password, is_active)
    select org.id, x.login, x.fn, '${hash}', x.mc, true from org, (values
      ('ztest_mod','Тестовый Модератор', false),
      ('ztest_user','Тестовый Пользователь', true)) as x(login, fn, mc)
    on conflict do nothing`);
  psql(`insert into user_roles(user_id, role_id)
    select u.id, r.id from users u join roles r on (u.login='ztest_mod' and r.code='moderator') or (u.login='ztest_user' and r.code='user')
    on conflict do nothing`);
  psql(`insert into access_grants(scope, dashboard_id, grantee_type, user_id, granted_by)
    select 'dashboard', d.id, 'user', u.id, a.id from dashboards d, users u, users a
    where d.name='Динамика МФЦ' and u.login='ztest_user' and a.login='admin' on conflict do nothing`);
}
function cleanupUsers() {
  for (const sql of [
    `delete from access_grants where user_id in (select id from users where login like 'ztest_%')`,
    `delete from archive_access where user_id in (select id from users where login like 'ztest_%')`,
    `delete from login_events where login like 'ztest_%' or user_id in (select id from users where login like 'ztest_%')`,
    `delete from notification_recipients where user_id in (select id from users where login like 'ztest_%')`,
    `delete from user_roles where user_id in (select id from users where login like 'ztest_%')`,
    `delete from users where login like 'ztest_%'`,
  ]) { try { psql(sql); } catch (e) { console.log('cleanup:', String(e).slice(0, 120)); } }
}

// ── Хелперы браузера ─────────────────────────────────────────────────────────
async function shot(page, name, opts = {}) {
  try {
    await page.waitForTimeout(opts.wait ?? 900);
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
  await page.waitForTimeout(1500);
}
async function closeOverlays(page) {
  for (let i = 0; i < 4; i++) {
    const x = page.locator('button:has-text("✕")').first();
    if (await x.isVisible().catch(() => false)) { await x.click({ force: true }).catch(() => {}); await page.waitForTimeout(250); }
    else break;
  }
  await page.keyboard.press('Escape').catch(() => {});
}
async function clickText(page, text) {
  // Программный клик по строке с текстом — надёжнее координатных кликов
  // (перекрытия/анимации). С ретраями: списки подгружаются асинхронно.
  let lastErr;
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      await page.evaluate((t) => {
    // Название в строках списков — текст-нода среди span'ов (☆, «страниц: N»),
    // отдельного элемента с чистым текстом нет. Берём САМЫЙ ГЛУБОКИЙ элемент,
    // содержащий текст, но не сильно длиннее его (строка списка, не вся страница).
    const els = [...document.querySelectorAll('*')].filter((e) => {
      const s = e.textContent.replace(/\s+/g, ' ').trim();
      return s.includes(t) && s.length < t.length + 45;
    });
        if (els.length) els[els.length - 1].click(); else throw new Error('нет элемента: ' + t);
      }, text);
      await page.waitForTimeout(1500);
      return;
    } catch (e) { lastErr = e; await page.waitForTimeout(900); }
  }
  throw lastErr;
}
async function nav(page, label) {
  await closeOverlays(page);
  try { await page.getByRole('button', { name: label, exact: true }).first().click({ timeout: 8000 }); }
  catch { await page.getByRole('button', { name: label, exact: true }).first().click({ force: true }).catch(() => fails.push('nav ' + label)); }
  await page.waitForTimeout(1100);
}

(async () => {
  prepUsers();
  const browser = await chromium.launch();
  const mkCtx = (w = 1440, h = 900) => browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });

  // ═══ Админ, основной обход ═══
  let ctx = await mkCtx();
  let page = await ctx.newPage();
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.evaluate(() => localStorage.clear());
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await shot(page, '01_login');
  await login(page, 'admin', 'admin');
  await shot(page, '02_home', { wait: 1500 });

  // Мастер: пошагово (03_wizard = шаг 1; 03b/03c/03d — следующие шаги)
  try {
    await page.locator('button[title*="Мастер"], button:has-text("🧭")').first().click();
    await shot(page, '03_wizard');
    for (const stepName of ['03b_wizard_step2', '03c_wizard_step3', '03d_wizard_step4']) {
      const nextBtn = page.locator('button:has-text("Далее")').first();
      if (await nextBtn.isVisible().catch(() => false)) { await nextBtn.click(); await shot(page, stepName, { wait: 700 }); }
    }
    await closeOverlays(page);
  } catch (e) { fails.push('wizard: ' + e.message.split('\n')[0]); }

  try {
    await page.locator('button[title*="Уведомл"], button:has-text("🔔")').first().click();
    await shot(page, '04_notifications', { wait: 700 });
    await page.keyboard.press('Escape'); await page.mouse.click(700, 500); await page.waitForTimeout(300);
  } catch (e) { fails.push('04: ' + e.message.split('\n')[0]); }

  await nav(page, 'Объекты'); await shot(page, '05_objects', { full: true });
  await nav(page, 'Метрики'); await shot(page, '06_metrics');
  try {
    await page.getByText('Итого план').first().click();
    await page.waitForTimeout(1200);
    const c = page.getByRole('button', { name: '🖱 Конструктор' });
    if (await c.isVisible().catch(() => false)) await c.click();
    await shot(page, '07_metric_builder', { full: true });
  } catch (e) { fails.push('07: ' + e.message.split('\n')[0]); }

  await nav(page, 'Дашборды'); await shot(page, '08_dashboards');
  try {
    await clickText(page, 'Дашборд «Динамика тест»');
    await shot(page, '09_editor', { full: true });
    await page.locator('button:has-text("галерея")').first().click();
    await shot(page, '10_widget_picker', { wait: 700 });
    await closeOverlays(page);
  } catch (e) { fails.push('09/10: ' + e.message.split('\n')[0]); }

  try {
    await clickText(page, 'Дашборды'); // крошка: выход из открытого конструктора к списку
    await clickText(page, 'Динамика МФЦ');
    await page.waitForTimeout(500);
    await shot(page, '11_viewer', { full: true });
    await page.locator('button').filter({ hasText: 'Доступ' }).first().click();
    await shot(page, '12_access', { wait: 900 });
    await closeOverlays(page);
    await page.locator('button').filter({ hasText: 'Обсуждение' }).first().click();
    await shot(page, '13_comments', { wait: 900 });
    await closeOverlays(page);
  } catch (e) { fails.push('11-13: ' + e.message.split('\n')[0]); }

  await nav(page, 'Модерация'); await shot(page, '14_moderation');
  await nav(page, 'Справочники'); await shot(page, '15_catalog');
  await nav(page, 'Пользователи'); await shot(page, '16_users', { full: true });
  await nav(page, 'Аудит'); await shot(page, '17_audit', { full: true });
  await nav(page, 'Отчёты'); await shot(page, '18_reports', { full: true, wait: 2000 });

  // Темы: тёмная и «МинЭк»
  try {
    await nav(page, 'Главная');
    await page.evaluate(() => { localStorage.setItem('dashbord_theme', 'dark'); location.reload(); });
    await page.waitForTimeout(2000);
    await shot(page, '19_dark');
    await page.evaluate(() => { localStorage.setItem('dashbord_theme', 'minek'); location.reload(); });
    await page.waitForTimeout(2000);
    await shot(page, '20_minek');
    await page.evaluate(() => { localStorage.setItem('dashbord_theme', 'light'); location.reload(); });
    await page.waitForTimeout(1500);
  } catch (e) { fails.push('themes: ' + e.message.split('\n')[0]); }

  // ═══ Архив (временный слепок «Динамика МФЦ» через API) ═══
  try {
    const tok = await apiToken();
    const H = { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' };
    const list = await (await fetch(`${API}/dashboards?` + new URLSearchParams({ q: 'Динамика МФЦ' }), { headers: H })).json();
    const did = list.items[0].id;
    const arc = await (await fetch(`${API}/dashboards/${did}/archive`, { method: 'POST', headers: H, body: JSON.stringify({ topic: 'Месячная отчётность', note: 'Слепок показателей за июль' }) })).json();
    await nav(page, 'Архив');
    await shot(page, '50_archive', { wait: 1400 });
    await page.getByRole('button', { name: 'Открыть' }).first().click();
    await shot(page, '51_archive_view', { wait: 2000, full: true });
    // вернуть как было
    await fetch(`${API}/archive/${arc.id}/unarchive`, { method: 'POST', headers: H });
    await fetch(`${API}/archive/${arc.id}`, { method: 'DELETE', headers: H });
    // диалог архивации на черновике
    await nav(page, 'Дашборды');
    await clickText(page, 'Показатели МФЦ');
    await page.locator('button').filter({ hasText: 'В архив' }).first().click();
    await shot(page, '52_archive_dialog', { wait: 800 });
    await page.getByRole('button', { name: 'Отмена' }).click().catch(() => {});
  } catch (e) { fails.push('archive: ' + e.message.split('\n')[0]); }
  await ctx.close();

  // ═══ Слайдовые кадры 1600×900 (для презентаций) ═══
  ctx = await mkCtx(1600, 900);
  page = await ctx.newPage();
  await login(page, 'admin', 'admin');
  try {
    await nav(page, 'Дашборды');
    await clickText(page, 'Динамика МФЦ');
    await page.waitForTimeout(500); await page.mouse.wheel(0, 380);
    await shot(page, '60_viewer_slide', { wait: 1200 });
    await clickText(page, 'Дашборды'); // крошка
    await clickText(page, 'Дашборд «Динамика тест»');
    await page.waitForTimeout(500); await page.mouse.wheel(0, 320);
    await shot(page, '61_editor_slide', { wait: 1200 });
    await nav(page, 'Отчёты'); await shot(page, '62_reports_slide', { wait: 1800 });
    await nav(page, 'Объекты'); await shot(page, '63_objects_slide');
    await nav(page, 'Пользователи'); await shot(page, '64_users_slide');
  } catch (e) { fails.push('slides: ' + e.message.split('\n')[0]); }
  await ctx.close();

  // ═══ Модератор ═══
  ctx = await mkCtx();
  page = await ctx.newPage();
  await login(page, 'ztest_mod', 'Ztest12345');
  await shot(page, '30_mod_home', { wait: 1500 });
  try { await nav(page, 'Модерация'); await shot(page, '31_mod_moderation'); } catch (e) { fails.push('31: ' + e.message); }
  await ctx.close();

  // ═══ Пользователь: смена пароля → главная → дашборд ═══
  ctx = await mkCtx();
  page = await ctx.newPage();
  await login(page, 'ztest_user', 'Ztest12345');
  await shot(page, '40_user_password', { wait: 1200 });
  psql(`update users set must_change_password=false where login='ztest_user'`);
  await login(page, 'ztest_user', 'Ztest12345');
  await shot(page, '41_user_home', { wait: 1500 });
  try {
    await nav(page, 'Дашборды');
    await clickText(page, 'Динамика МФЦ');
    await shot(page, '42_user_dashboard', { full: true });
  } catch (e) { fails.push('42: ' + e.message.split('\n')[0]); }
  await ctx.close();

  await browser.close();
  cleanupUsers();
  console.log(fails.length ? 'FAILS:\n' + fails.join('\n') : 'ALL DONE');
})();
