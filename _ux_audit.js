const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 } });
  const page = await ctx.newPage();
  await ctx.addInitScript((t) => {
    localStorage.setItem('tova_token', t); localStorage.setItem('tova_super', '1'); localStorage.setItem('tova_perms', '[]');
  }, process.env.SV_TOKEN);
  await page.goto('https://tovaads.pages.dev/#/settings', { waitUntil: 'load' });
  await page.waitForSelector('.anchor-btn', { timeout: 15000 });
  const secs = await page.locator('.anchor-btn').allTextContents();
  console.log('分区数:', secs.length);
  // 逐区截图 + 布局统计
  const stats = [];
  for (let i = 0; i < secs.length; i++) {
    await page.locator('.anchor-btn').nth(i).click();
    await page.waitForTimeout(900);
    const id = await page.locator('.anchor-btn.active').getAttribute('id').catch(() => '');
    const st = await page.evaluate(() => {
      const card = document.querySelector('.card');
      if (!card) return null;
      const labels = [...card.querySelectorAll('.form-l > label')].map(l => Math.round(l.getBoundingClientRect().width));
      const inputs = [...card.querySelectorAll('.form-l .input, .form-l input.el-input__inner')].map(x => Math.round(x.getBoundingClientRect().width));
      const btns = [...card.querySelectorAll('button')].map(b => b.className.split(' ').filter(c => c !== 'btn').join('|') || 'plain');
      const desc = card.querySelector('.d');
      return {
        h: Math.round(card.getBoundingClientRect().height),
        labelWidths: [...new Set(labels)],
        inputWidths: [...new Set(inputs)],
        btnKinds: [...new Set(btns)],
        descLen: desc ? desc.textContent.trim().length : 0,
        formRows: card.querySelectorAll('.form-l').length,
      };
    });
    stats.push({ sec: secs[i], ...st });
    const fname = 'D:/dev/Mira_One/_shots/sec-' + i + '.png';
    await page.screenshot({ path: fname, fullPage: true });
  }
  stats.forEach(s => console.log(JSON.stringify(s)));
  await browser.close();
})();
