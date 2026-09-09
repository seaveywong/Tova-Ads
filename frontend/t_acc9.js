const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1680, height: 1000 } });
  await page.addInitScript(t => { try { localStorage.setItem('tova_token', t) } catch (e) {} }, fs.readFileSync('D:/dev/Mira_One/_o_token.txt', 'utf8').trim());
  const reqs = [];
  page.on('response', r => { if (r.url().includes('/api/') || r.url().includes('tovaads.com/') && r.url().includes('/launch')) reqs.push(r.status() + ' ' + r.url().slice(-60)); });
  await page.goto('https://tovaads.com/#/launch-templates', { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForTimeout(2000);
  await page.locator('button.op.primary').first().click();
  const samples = [];
  for (let k = 0; k < 10; k++) {
    await page.waitForTimeout(600);
    const s = await page.evaluate(() => {
      const drawer = [...document.querySelectorAll('.el-drawer')].find(d => d.offsetParent !== null);
      if (!drawer) return 'nodrawer';
      const inps = [...drawer.querySelectorAll('.acc-row input')];
      return inps.map(i => i.disabled ? 'D' : 'e').join('') + '|' + (drawer.querySelector('.acc-block.disabled') ? 'blkDis' : 'blkOk');
    });
    samples.push(s);
  }
  console.log('TIMELINE:', samples.join(' > '));
  console.log('REQS:', reqs.slice(-8).join(' ; '));
  await browser.close();
})().catch(e => { console.error('SCRIPT_FAIL', String(e).slice(0, 200)); process.exit(2); });
