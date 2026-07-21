import { createRouter, createWebHashHistory } from 'vue-router'
import { getToken } from '../api'

// 路由 → 所需权限映射（无 perm = 所有登录用户可访问）
const ROUTE_PERMS = {
  dashboard:   ['ads.read'],
  ads:         ['ads.read'],
  'ad-manager':['ads.read'],
  landing:     ['landing.manage'],
  guard:       ['rules.read'],
  'kpi-mapping':['rules.read'],
  settings:    [],  // 所有人可看自己的设置
  members:     ['members.manage'],
  tokens:      ['ads.read'],
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
      { path: 'landing', name: 'landing', component: () => import('../views/Landing.vue'), meta: { title: '落地页', icon: 'Link' } },
      { path: 'guard', name: 'guard', component: () => import('../views/Guard.vue'), meta: { title: '规则引擎', icon: 'SetUp' } },
      { path: 'kpi-mapping', name: 'kpi-mapping', component: () => import('../views/KpiMapping.vue'), meta: { title: '转化映射', icon: 'Histogram' } },
      { path: 'settings', name: 'settings', component: () => import('../views/Settings.vue'), meta: { title: '设置', icon: 'Setting' } },
      { path: 'members', name: 'members', component: () => import('../views/Members.vue'), meta: { title: '成员权限', icon: 'User' } },
      { path: 'tokens', name: 'tokens', component: () => import('../views/Tokens.vue'), meta: { title: 'Facebook 授权' } },
    ],
  },
]

const router = createRouter({ history: createWebHashHistory(), routes })

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

export default router
