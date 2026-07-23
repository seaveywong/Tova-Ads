// API 封装 — 所有后端调用走这里
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
        throw new Error(data.detail || '邮箱或密码错误')
      }
      if (!_redirecting401) {
        _redirecting401 = true
        setToken('')
        try { localStorage.removeItem('tova_perms') } catch {}
        setTimeout(() => { _redirecting401 = false; window.location.hash = '#/login' }, 50)
      }
      throw new Error('未登录')
    }
    const text = await res.text()
    let data = {}
    try { data = JSON.parse(text) } catch {}
    if (!res.ok) throw new Error(data.detail || data.message || text || `HTTP ${res.status}`)
    return data
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('请求超时')
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
