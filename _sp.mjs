import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto('https://app.tovaads.com/login', { waitUntil: 'domcontentloaded' });
await page.evaluate((t) => { localStorage.setItem('tova_token', t); localStorage.setItem('tova_locale', 'zh'); }, process.env.TOK);
await page.goto('https://app.tovaads.com/dashboard', { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {});
await page.waitForTimeout(10000);
const ac = page.locator('.alert-center');
await ac.scrollIntoViewIfNeeded();
await page.waitForTimeout(400);
await ac.screenshot({ path: '../_shots/p-ac.png' });
// 点查看全部
await page.click('.alert-center .copy-ids-btn:first-child').catch(() => {});
await page.waitForTimeout(800);
await ac.screenshot({ path: '../_shots/p-ac-all.png' });
await browser.close();
console.log('done');
