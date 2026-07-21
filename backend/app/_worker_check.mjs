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

// 造一个 /a/ 请求（模拟真实广告点击：带 ad 参数 + UA + referer）
const req = new Request('https://example.com/a/__check__?ad=1234567890&fbclid=abc', {
  headers: {
    'user-agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Mobile',
    'cf-connecting-ip': '1.2.3.4',
    'referer': 'https://www.facebook.com/',
  },
})
const env = { ASSETS: { fetch: async () => new Response('assets', { status: 200 }) } }
const ctx = { waitUntil: (p) => { try { if (p && p.catch) p.catch(() => {}) } catch (e) {} } }

try {
  const resp = await worker.fetch(req, env, ctx)
  if (!resp || typeof resp.status !== 'number') {
    console.error('WORKER_BAD_RESPONSE: fetch 没返回 Response')
    process.exit(1)
  }
  console.log('WORKER_OK status=' + resp.status)
  process.exit(0)
} catch (e) {
  console.error('WORKER_RUNTIME_ERR:', e.message, e.stack ? e.stack.split('\n')[1] : '')
  process.exit(1)
}
