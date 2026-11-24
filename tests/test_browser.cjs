const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const cp = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const library = process.env.COMFYUI_EXPRESSION_LIBRARY;

function payload() {
  return JSON.parse(cp.execFileSync('python3', ['-c',
    "import importlib.util,json; s=importlib.util.spec_from_file_location('catalog','catalog.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(json.dumps(m.payload()))"
  ], {cwd: root, env: process.env, maxBuffer: 8 * 1024 * 1024}));
}

test('bilingual gallery, filters, paging, viewer, mobile layout, and node selection', async () => {
  assert.ok(library, 'Set COMFYUI_EXPRESSION_LIBRARY to a generated gallery');
  const data = payload();
  assert.ok(data.records.length >= 7);
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const route = url.pathname;
    const send = (type, body) => {res.setHeader('Content-Type', type); res.end(body);};
    if (route === '/expression_gallery/catalog') return send('application/json', JSON.stringify(data));
    if (route === '/scripts/api.js') return send('text/javascript', 'export const api={apiURL:path=>path};');
    if (route === '/scripts/app.js') return send('text/javascript', `
      class TestNode {
        constructor(){this.widgets=[{name:'expression_id',value:'F01AF'},{name:'language',value:'zh'}];this.outputs=Array.from({length:7},()=>({}));this.title='Expression Gallery 表情图库';}
        addDOMWidget(name,type,element,options){if(options.serialize!==false)throw Error('Unexpected serialization');document.body.append(element);element.dataset.widget=name;return {name,type};}
        setSize(){} setDirtyCanvas(){}
      }
      export const app={graph:{change(){window.changes=(window.changes||0)+1;}},async registerExtension(extension){await extension.beforeRegisterNodeDef(TestNode,{name:'ExpressionClayGallery'});window.testNode=new TestNode();window.testNode.onNodeCreated();}};
    `);
    if (route === '/harness') return send('text/html', '<html><body><script type="module" src="/extensions/expression/expression_gallery_v3.js"></script></body></html>');
    let file;
    if (route === '/expression_gallery/gallery') file = path.join(root, 'web/gallery.html');
    else if (route.startsWith('/expression_gallery/web/') || route.startsWith('/extensions/expression/')) file = path.join(root, 'web', path.basename(route));
    else if (route.startsWith('/expression_gallery/assets/')) {
      const [, , , kind, id] = route.split('/');
      const row = data.records.find(r => r.id === id);
      if (row) file = kind === 'thumbs' ? path.join(library, '.gallery/thumbs', id + '.webp') : path.join(library, row.filename);
    }
    if (!file || !fs.existsSync(file)) {res.writeHead(404);res.end();return;}
    const extension = path.extname(file);
    res.setHeader('Content-Type', {'.html':'text/html','.js':'text/javascript','.mjs':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp'}[extension] || 'application/octet-stream');
    fs.createReadStream(file).pipe(res);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/expression_gallery/gallery?lang=en');
    await page.waitForSelector('#grid .card');
    assert.equal(await page.locator('html').getAttribute('lang'), 'en');
    assert.equal(await page.locator('#grid .card').count(), Math.min(60, data.records.length));
    await page.locator('#grid img').first().evaluate(img => img.decode());
    await page.locator('#q').fill('happy F01');
    assert.equal(await page.locator('#grid .card').count(), 1);
    await page.locator('#grid .card').click();
    await page.locator('#large').evaluate(img => img.decode());
    assert.equal(await page.locator('#detail-title').textContent(), 'happy');
    assert.equal(await page.locator('#download').getAttribute('download'), data.records.find(r => r.id === 'F01HA').filename);
    assert.equal(await page.locator('#use').isDisabled(), true);
    await page.keyboard.press('Escape');
    await page.locator('#language').click();
    assert.equal(await page.locator('html').getAttribute('lang'), 'zh-CN');
    assert.equal(await page.locator('#grid .card').count(), 1);
    await page.locator('#q').fill('悲伤 F01');
    assert.equal(await page.locator('#grid .card').count(), 1);
    await page.locator('#reset').click();
    await page.locator('#actor').selectOption('F01');
    assert.equal(await page.locator('#grid .card').count(), 7);
    await page.locator('#type-options button').filter({hasText:'开心'}).click();
    assert.equal(await page.locator('#grid .card').count(), 1);
    await page.locator('#q').fill('nothing-matches');
    assert.equal(await page.locator('#empty').isVisible(), true);
    await page.locator('#reset').click();
    if (data.records.length > 60) {
      await page.locator('#more').click();
      assert.equal(await page.locator('#grid .card').count(), Math.min(120, data.records.length));
    }
    await page.locator('#grid .card').first().click();
    await page.keyboard.press('ArrowRight');
    assert.match(await page.locator('#position').textContent(), /^2 /);
    await page.keyboard.press('Escape');
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'Mobile page overflows horizontally');
    if (process.env.EXPRESSION_SCREENSHOT) await page.screenshot({path:process.env.EXPRESSION_SCREENSHOT,fullPage:false});
    await page.goto(base + '/harness');
    await page.waitForSelector('[data-widget="expression_browser"]');
    await page.locator('[data-widget="expression_browser"] button').first().click();
    const frame = page.frameLocator('iframe');
    await frame.locator('#close').click();
    await frame.locator('#q').fill('happy F01');
    await frame.locator('#grid .card').click();
    await frame.locator('#use').click();
    await page.waitForFunction(() => window.testNode.widgets[0].value === 'F01HA');
    assert.equal(await page.locator('iframe').count(), 0);
    await page.locator('[data-widget="expression_browser"] button').last().click();
    assert.equal(await page.evaluate(() => window.testNode.widgets[1].value), 'en');
    assert.equal(await page.evaluate(() => window.testNode.outputs[4].label), 'Expression (EN)');
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
});
