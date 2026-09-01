// Worker 发布前校验：导入待发布 worker，mock 一个 /a/ 请求跑一遍。
// 捕获语法错（node --check 兜）+ 运行时错（ReferenceError 等）。
// 用法: node _worker_check.mjs <worker_js_path>
// 退出 0=OK，1=出错（stderr 打印错误）。
const path = process.argv[2]
if (!path) { console.error('用法: node _worker_check.mjs <worker.mjs>'); process.exit(1) }

// mock 全局 fetch（worker 内部会调 route_next/ingest/frequency，不能真打网络）
globalThis.fetch = async (url, opts) => {
  const u = typeof url === 'string' ? url : (url && url.url) || ''
  if (u.includes('/router/next')) {
    return new Response(JSON.stringify({ pixel_ids: [], target_url: 'https://example.com', conversion_events: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  if (u.includes('/frequency-check')) return new Response(JSON.stringify({ exceeded: false }), { status: 200 })
  return new Response('{"ok":true}', { status: 200 })
}

let worker
try {
  worker = (await import('file://' + path)).default
} catch (e) {
  console.error('WORKER_IMPORT_ERR:', e.message)
  process.exit(1)
}
if (!worker || typeof worker.fetch !== 'function') {
  console.error('WORKER_NO_DEFAULT_FETCH: 缺 export default { fetch }')
  process.exit(1)
}

const env = { ASSETS: { fetch: async () => new Response('assets', { status: 200 }) } }
const ctx = { waitUntil: (p) => { try { if (p && p.catch) p.catch(() => {}) } catch (e) {} } }

async function runOnce(w, url) {
  const req = new Request(url, {
    headers: {
      'user-agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Mobile',
      'cf-connecting-ip': '1.2.3.4',
      'referer': 'https://www.facebook.com/',
    },
  })
  const resp = await w.fetch(req, env, ctx)
  if (!resp || typeof resp.status !== 'number') throw new Error('fetch 没返回 Response')
  return resp.status
}

// ① 主路径：按真实配置跑一遍 /a/ 请求（模拟广告点击）
try {
  const status = await runOnce(worker, 'https://example.com/a/__check__?ad=1234567890&fbclid=abc')
  console.log('WORKER_OK status=' + status)
} catch (e) {
  console.error('WORKER_RUNTIME_ERR:', e.message, e.stack ? e.stack.split('\n')[1] : '')
  process.exit(1)
}

// ② 变体：把首行 LP_CONFIG 换成 {block_enabled:true, rules:0} 再跑 —— 强制执行
//    evalProtection 的 rules 兜底分支（rules 非 object）。V8 对"未执行分支里的 const
//    重赋值"不报错（node --check / import 都放行），只有 wrangler 的 esbuild 静态分析
//    才拦；让兜底分支真执行，这类错误在发布门就被拦下，不会到 wrangler 才炸。
//    rules=0（非 null）：后续 LP_CONFIG.rules.frequency 读 undefined 不炸，只测兜底分支。
const fs = await import('node:fs')
const src = await fs.promises.readFile(path, 'utf8')
const mutated = src.replace(/^const LP_CONFIG = .*\n/m, 'const LP_CONFIG = {block_enabled:true, rules:0};\n')
if (mutated !== src) {
  const tmp2 = path + '.nulcfg.mjs'
  await fs.promises.writeFile(tmp2, mutated, 'utf8')
  try {
    const w2 = (await import('file://' + tmp2)).default
    await runOnce(w2, 'https://example.com/a/__check2__')
  } catch (e) {
    console.error('WORKER_NULLCFG_ERR:', e.message)
    process.exit(1)
  } finally {
    try { fs.unlinkSync(tmp2) } catch (e) {}
  }
}
process.exit(0)
