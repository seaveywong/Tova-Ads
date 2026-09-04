// 数据看板截图（登录态注入 + 多视口全页截图）
import { chromium } from 'playwright';

const TOKEN = process.env.TOK;
const BASE = process.env.SITE || 'https://app.tovaads.com';
const OUT = 'D:/dev/Mira_One/toveads/_shots';

const browser = await chromium.launch();
for (const vp of [
  { name: 'desktop1920', width: 1920, height: 1080 },
  { name: 'lap1366', width: 1366, height: 768 },
  { name: 'pad1024', width: 1024, height: 768 },
  { name: 'mobile390', width: 390, height: 844 },
]) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: vp.name === 'mobile390' ? 2 : 1 });
  const page = await ctx.newPage();
  // 先开登录页（同源）注入 token，再进看板
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => {
    localStorage.setItem('tova_token', t);
    localStorage.setItem('tova_locale', 'zh');
  }, TOKEN);
  await page.goto(BASE + '/dashboard', { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(4500); // 等数据渲染+图表
  await page.screenshot({ path: `${OUT}/dash-${vp.name}.png`, fullPage: true });
  // 落地页 tab 也截一张（桌面/移动）
  try {
    await page.evaluate(() => { const els = [...document.querySelectorAll('.main-tab, [class*=tab]')]; const el = els.find(e => e.textContent && e.textContent.includes('落地')); if (el) el.click(); });
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${OUT}/dash-landing-${vp.name}.png`, fullPage: true });
  } catch {}
  await ctx.close();
  console.log('done', vp.name);
}
await browser.close();
