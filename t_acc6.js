const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1680, height: 1000 } });
  await page.addInitScript(t => { try { localStorage.setItem('tova_token', t) } catch (e) {} }, fs.readFileSync('D:/dev/Mira_One/_o_token.txt', 'utf8').trim());
  await page.goto('https://tovaads.com/#/launch-templates', { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForTimeout(2500);
  await page.locator('button.op.primary').first().click();
  await page.waitForTimeout(3000);
  const st = await page.evaluate(() => {
    const drawer = [...document.querySelectorAll('.el-drawer')].find(d => d.offsetParent !== null);
    const rows = [...drawer.querySelectorAll('.acc-row input')].map(i => `${i.closest('.acc-row').querySelector('.acc-name').textContent.slice(0,14)} disabled=${i.disabled}`);
    // 从 Vue app 实例挖 setupState
    const app = document.querySelector('#app').__vue_app__;
    let found = null;
    const walk = (c, d) => {
      if (!c || d > 6 || found) return;
      const s = c.setupState || {};
      if (s.reuseDeployPage !== undefined) { found = { page: s.reuseDeployPage, eligible: [...(s.reuseEligibleActs || [])], tpl_ps: s.deployTpl?.post_source, reuseRef: s.deployTpl?.reuse_post_ref }; }
      (c.subTree?.component && walk(c.subTree.component, d + 1));
      const ch = c.subTree;
      if (ch?.children) { const arr = Array.isArray(ch.children) ? ch.children : Object.values(ch.children); arr.forEach(x => x?.component && walk(x.component, d + 1)); }
      if (ch?.component) walk(ch.component, d + 1);
    };
    walk(app._instance, 0);
    return JSON.stringify({ rows, vue: found });
  });
  console.log('STATE:', st);
  await browser.close();
})().catch(e => { console.error('SCRIPT_FAIL', String(e).slice(0, 200)); process.exit(2); });
