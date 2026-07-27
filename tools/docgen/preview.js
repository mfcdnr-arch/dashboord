// Визуальная проверка docx: рендер docx-preview в Chromium → PNG-страницы.
//   node preview.js out/<файл>.docx <префикс> [страницы через запятую]
const { chromium } = require('playwright');
const fs = require('fs');

(async () => {
  const file = process.argv[2];
  const prefix = process.argv[3] || 'prev';
  const b64 = fs.readFileSync(file).toString('base64');
  const lib = fs.readFileSync(__dirname + '/node_modules/docx-preview/dist/docx-preview.min.js', 'utf8');
  const jszip = fs.readFileSync(__dirname + '/node_modules/jszip/dist/jszip.min.js', 'utf8');
  const html = `<!doctype html><html><head><meta charset="utf-8">
  <script>${jszip}</script><script>${lib}</script>
  <style>body{margin:0;background:#888}.docx-wrapper{padding:10px}</style></head>
  <body><div id="c"></div><script>
    const bin = Uint8Array.from(atob("${b64}"), c => c.charCodeAt(0));
    docx.renderAsync(bin.buffer, document.getElementById('c')).then(() => { window.__done = true; }).catch(e => { console.log('RENDER FAIL: ' + e); window.__done = true; });
  </script></body></html>`;
  const tmp = __dirname + '/out/_preview.html';
  fs.writeFileSync(tmp, html);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1000, height: 1400 } });
  page.on('console', (m) => console.log('[pg]', m.text().slice(0, 200)));
  await page.goto('file://' + tmp);
  await page.waitForFunction('window.__done === true', { timeout: 60000 });
  await page.waitForTimeout(1000);
  const pages = page.locator('section.docx');
  const n = await pages.count();
  console.log('pages:', n);
  const want = process.argv[4] ? process.argv[4].split(',').map(Number) : [...Array(Math.min(n, 30)).keys()].map((i) => i + 1);
  for (const i of want) {
    if (i > n) continue;
    await pages.nth(i - 1).scrollIntoViewIfNeeded();
    await pages.nth(i - 1).screenshot({ path: `${__dirname}/out/${prefix}-${String(i).padStart(2, '0')}.png` });
  }
  await browser.close();
  console.log('done');
})();
