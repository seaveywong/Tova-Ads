import { createRouter, createWebHashHistory } from 'vue-router'
import { getToken } from '../api'

// 路由 → 所需权限映射（无 perm = 所有登录用户可访问）
const ROUTE_PERMS = {
  dashboard:   ['ads.read'],
  ads:         ['ads.read'],
  'ad-manager':['ads.read'],
  'launch-templates':['ads.create'],
  'form-templates':['ads.create'],
  landing:     ['landing.manage'],
  guard:       ['rules.read'],
  'kpi-mapping':['__superadmin__'],  // 仅超管可见（前端 isSuperadmin 控制，不走权限矩阵）
  'admin-teams':['__superadmin__'],  // 团队管理（超管）
  settings:    [],  // 所有人可看自己的设置
  members:     ['members.manage'],
  logs:        ['audit.read'],  // 操作日志（owner 可见）
  tokens:      ['ads.read'],
  assets:      ['assets.manage'],  // 素材库（owner+operator）
}

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/Login.vue') },
  {
    path: '/',
    component: () => import('../layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '数据看板', icon: 'DataAnalysis' } },
      { path: 'ads', name: 'ads', component: () => import('../views/Ads.vue'), meta: { title: '广告账户', icon: 'Promotion' } },
      { path: 'ad-manager', name: 'ad-manager', component: () => import('../views/AdManager.vue'), meta: { title: '广告管理器', icon: 'Operation' } },
      { path: 'launch-templates', name: 'launch-templates', component: () => import('../views/LaunchTemplates.vue'), meta: { title: '投放模板', icon: 'Promotion' } },
      { path: 'form-templates', name: 'form-templates', component: () => import('../views/FormTemplates.vue'), meta: { title: '表单模板', icon: 'Document' } },
      { path: 'assets', name: 'assets', component: () => import('../views/Assets.vue'), meta: { title: '素材库', icon: 'Picture' } },
      { path: 'landing', name: 'landing', component: () => import('../views/Landing.vue'), meta: { title: '落地页', icon: 'Link' } },
      { path: 'guard', name: 'guard', component: () => import('../views/Guard.vue'), meta: { title: '规则引擎', icon: 'SetUp' } },
      { path: 'kpi-mapping', name: 'kpi-mapping', component: () => import('../views/KpiMapping.vue'), meta: { title: '转化映射', icon: 'Histogram' } },
      { path: 'admin-teams', name: 'admin-teams', component: () => import('../views/AdminTeams.vue'), meta: { title: '团队管理', icon: 'OfficeBuilding' } },
      { path: 'logs', name: 'logs', component: () => import('../views/AuditLog.vue'), meta: { title: '操作日志', icon: 'Document' } },
      { path: 'settings', name: 'settings', component: () => import('../views/Settings.vue'), meta: { title: '设置', icon: 'Setting' } },
      { path: 'members', name: 'members', component: () => import('../views/Members.vue'), meta: { title: '成员权限', icon: 'User' } },
      { path: 'tokens', name: 'tokens', component: () => import('../views/Tokens.vue'), meta: { title: 'Facebook 授权' } },
    ],
  },
]

const router = createRouter({ history: createWebHashHistory(), routes })

// 从 JWT 同步解析 is_superadmin（路由守卫/导航过滤用，权威，不依赖异步 /auth/me 或 localStorage 时序）
// token payload 由后端 create_access_token 签发，含 is_superadmin 字段（见 security.py）
export function isSuperadminSync() {
  try {
    const t = getToken()
    if (!t) return false
    const part = t.split('.')[1]
    if (!part) return false
    const payload = JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/')))
    return payload.is_superadmin === true
  } catch { return false }
}

// 缓存用户权限（从 localStorage 读，/auth/me 时写）
export function getUserPerms() {
  try { return JSON.parse(localStorage.getItem('tova_perms') || '[]') } catch { return [] }
}
export function setUserPerms(perms) {
  localStorage.setItem('tova_perms', JSON.stringify(perms || []))
}

router.beforeEach((to, from, next) => {
  if (to.name === 'login' || !getToken()) { if (to.name !== 'login') return next({ name: 'login' }); return next() }
  // 路由级权限拦截：无所需权限 → 跳到第一个有权限的页（或 dashboard）
  const required = ROUTE_PERMS[to.name]
  if (required && required.length) {
    if (required.includes('__superadmin__')) {
      if (!isSuperadminSync()) return next({ name: 'dashboard' })
      return next()  // 超管放行（__superadmin__ 非权限 key，超管 perms 不含它，不能走下面的 perms 检查）
    }
    if (isSuperadminSync()) return next()  // 超管放行所有路由（平台管理员，与导航过滤一致；后端 require_permission 也超管放行）
    const perms = getUserPerms()
    const hasAll = required.every(p => perms.includes(p))
    if (!hasAll) {
      // 找一个有权限的路由跳
      const fallback = Object.entries(ROUTE_PERMS).find(([_, ps]) => ps.every(p => perms.includes(p)))
      return next({ name: fallback ? fallback[0] : 'settings' })
    }
  }
  next()
})

// chunk 加载失败（部署后旧 hash 缓存）→ 带 cache-buster 强制刷新拿新 index.html
function _handleChunkFail(error) {
  const msg = (error && error.message) || String(error)
  if (!msg.includes('Failed to fetch dynamically imported module') &&
      !msg.includes('Importing a module script failed')) return
  if (sessionStorage.getItem('_chunk_reload')) return  // 同 session 只刷一次（防死循环）
  sessionStorage.setItem('_chunk_reload', '1')
  // 关键：加 ?_r=时间戳 绕开浏览器缓存的旧 index.html（否则 reload 还是旧 hash → 还是 404）
  try {
    const u = new URL(window.location.href)
    u.searchParams.set('_r', String(Date.now()))
    window.location.replace(u.toString())
  } catch {
    window.location.reload()
  }
}
router.onError(_handleChunkFail)
// 非 路由场景的 dynamic import 失败（组件内 import()）也要兜
window.addEventListener('error', (e) => {
  if (e && e.error && typeof e.error.message === 'string' &&
      e.error.message.includes('dynamically imported module')) {
    _handleChunkFail(e.error)
  }
})
// 成功导航后清 flag（下次部署后能再次触发）
router.afterEach(() => {
  sessionStorage.removeItem('_chunk_reload')
})

export default router
