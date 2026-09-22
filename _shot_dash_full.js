const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1520, height: 950 } });
  await ctx.addInitScript(([t]) => {
    localStorage.setItem('tova_token', t); localStorage.setItem('tova_super', '1');
    localStorage.setItem('tova_perms', '["*"]'); localStorage.setItem('tova_locale', 'zh');
  }, [process.argv[2]]);
  const page = await ctx.newPage();
  await page.goto('https://app.tovaads.com/#/dashboard', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(4500);
  await page.screenshot({ path: 'D:/dev/Mira_One/_vis_top.png' });                       // 首屏
  await page.screenshot({ path: 'D:/dev/Mira_One/_vis_full.png', fullPage: true });      // 全页
  console.log('shots done');
  await browser.close();
})();
