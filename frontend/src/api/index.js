// API 封装 — 所有后端调用走这里
import i18n from '../i18n'
const BASE = import.meta.env.VITE_API_BASE || 'https://api.tovaads.com'

let _token = localStorage.getItem('tova_token') || ''
let _redirecting401 = false

export function setToken(token) {
  _token = token
  if (token) localStorage.setItem('tova_token', token)
  else localStorage.removeItem('tova_token')
}

export function getToken() { return _token }

function headers() {
  const h = { 'Content-Type': 'application/json' }
  if (_token) h['Authorization'] = `Bearer ${_token}`
  // 语言：后端按此把中文报错 detail 译成英文（取 i18n 实际当前值，覆盖未 toggle 的新用户）
  h['X-Locale'] = (i18n.global.locale && i18n.global.locale.value) || localStorage.getItem('tova_locale') || 'zh'
  return h
}

export async function api(method, path, body) {
  const opts = { method, headers: headers() }
  if (body) opts.body = JSON.stringify(body)
  // 超时 + 中止：防止空闲时 fetch 堆积（网络瞬断→pending 连接耗尽→页面卡死）
  const _ctrl = new AbortController()
  opts.signal = _ctrl.signal
  const _timer = setTimeout(() => _ctrl.abort(), 30000)
  try {
    const res = await fetch(`${BASE}${path}`, opts)
    // 滑动续期：后端返新 token 就存（活跃用永不掉线）
    const _newTok = res.headers.get('X-New-Token')
    if (_newTok) setToken(_newTok)
    if (res.status === 401) {
      // 登录请求的 401 = 凭证错误，不走全局拦截（显示后端返回的真实错误）
      if (path === '/auth/login') {
        const text = await res.text()
        let data = {}
        try { data = JSON.parse(text) } catch {}
        throw new Error(data.detail || i18n.global.t('login.errCreds'))
      }
      if (!_redirecting401) {
        _redirecting401 = true
        setToken('')
        try { localStorage.removeItem('tova_perms') } catch {}
        setTimeout(() => { _redirecting401 = false; window.location.hash = '#/login' }, 50)
      }
      throw new Error(i18n.global.t('error.unauthorized'))
    }
    const text = await res.text()
    let data = {}
    try { data = JSON.parse(text) } catch {}
    if (!res.ok) throw new Error(data.detail || data.message || text || `HTTP ${res.status}`)
    return data
  } catch (e) {
    if (e.name === 'AbortError') throw new Error(i18n.global.t('error.timeout'))
    throw e
  } finally {
    clearTimeout(_timer)
  }
}

export const GET = (p) => api('GET', p)
export const POST = (p, b) => api('POST', p, b)
export const PUT = (p, b) => api('PUT', p, b)
export const PATCH = (p, b) => api('PATCH', p, b)
export const DELETE = (p) => api('DELETE', p)

// CSV/文件下载：fetch + Bearer + X-Locale（后端按 locale 出列头）→ blob 落盘
export async function downloadFile(path, fallbackName = 'export.csv') {
  const res = await fetch(BASE + path, { headers: headers() })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try { const j = await res.json(); msg = j.detail || msg } catch {}
    throw new Error(msg)
  }
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  const m = cd.match(/filename="?([^";]+)"?/)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = m ? m[1] : fallbackName
  a.click()
  URL.revokeObjectURL(url)
}
