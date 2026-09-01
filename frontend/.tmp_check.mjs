
import { ref, computed, onMounted, onUnmounted, watch, h } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { GET, POST, setToken } from '../api'
import { useTheme } from '../composables/useTheme'
import { useLocale } from '../composables/useLocale'
import { setUserTz, fmtTime } from '../composables/useTz'
import { usePlatform } from '../composables/usePlatform'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getUserPerms, setUserPerms, isSuperadminSync, prefetchRoutes } from '../router'

// 登录后的主壳挂载时预取全部路由 chunk（未登录不拉，见 App.vue）
prefetchRoutes()
const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const { theme, toggle: toggleTheme } = useTheme()
const { locale, toggle: toggleLocale } = useLocale()

// 角色 → i18n key（locale 切换实时生效）
const ROLE_KEY = { owner: 'role.owner', operator: 'role.operator', finance: 'role.finance', superadmin: 'role.superadmin' }
const roleLabel = (r) => (r && ROLE_KEY[r]) ? t(ROLE_KEY[r]) : (r || '')

// 平台切换器（纯前端：localStorage 持久；各页读 usePlatform 过滤数据，不发请求不换 token）
const { platform, setPlatform } = usePlatform()
const PLATFORMS = computed(() => [
  { v: 'all', label: t('common.all') },
  { v: 'fb', label: 'Facebook' },
  { v: 'tt', label: 'TikTok' },
])
const platformLabel = computed(() => PLATFORMS.value.find(p => p.v === platform.value)?.label || t('common.all'))

// 移动端侧边栏抽屉态
const isMobile = ref(false)
const sidebarOpen = ref(false)
const _mq = typeof window !== 'undefined' ? window.matchMedia('(max-width: 768px)') : null
const _onMq = (e) => { isMobile.value = e.matches; if (!e.matches) sidebarOpen.value = false }
if (_mq) { isMobile.value = _mq.matches; _mq.addEventListener?.('change', _onMq) }

// 当前用户权限
const myPerms = ref([])

// 导航 → 所需权限（同 router/ROUTE_PERMS）
const NAV_PERMS = {
  dashboard: ['ads.read'], ads: ['ads.read'], 'ad-manager': ['ads.read'], 'launch-templates': ['ads.create'], 'form-templates': ['ads.create'],
  landing: ['landing.manage'], guard: ['rules.read'],
  settings: [], members: ['members.manage'], logs: ['audit.read'], tokens: ['ads.read'], assets: ['assets.manage'],
}

// 导航（titleKey/labelKey 走 i18n，locale 切换实时生效）
const allNavGroups = [
  { titleKey: 'nav.groupData', items: [
    { name: 'dashboard', labelKey: 'nav.dashboard', icon: 'DataAnalysis' },
  ]},
  { titleKey: 'nav.groupAds', items: [
    { name: 'ads', labelKey: 'nav.ads', icon: 'Promotion' },
    { name: 'ad-manager', labelKey: 'nav.ad-manager', icon: 'Operation' },
    { name: 'launch-templates', labelKey: 'nav.launch-templates', icon: 'Aim' },
    { name: 'form-templates', labelKey: 'nav.form-templates', icon: 'Document' },
    { name: 'assets', labelKey: 'nav.assets', icon: 'Picture' },
  ]},
  { titleKey: 'nav.groupAuto', items: [
    { name: 'landing', labelKey: 'nav.landing', icon: 'Link' },
    { name: 'guard', labelKey: 'nav.guard', icon: 'SetUp' },
  ]},
  { titleKey: 'nav.groupAuth', items: [
    { name: 'tokens', labelKey: 'nav.tokens', icon: 'Connection' },
  ]},
  { titleKey: 'nav.groupSystem', items: [
    { name: 'settings', labelKey: 'nav.settings', icon: 'Setting' },
    { name: 'members', labelKey: 'nav.members', icon: 'User' },
    { name: 'logs', labelKey: 'nav.logs', icon: 'Document' },
    { name: 'admin-teams', labelKey: 'nav.admin-teams', icon: 'OfficeBuilding' },
    { name: 'kpi-mapping', labelKey: 'nav.kpi-mapping', icon: 'Histogram' },
  ]},
]
// 按权限过滤导航项
const navGroups = computed(() => {
  const perms = myPerms.value
  return allNavGroups
    .map(g => ({ ...g, items: g.items.filter(item => {
        if ((item.name === 'kpi-mapping' || item.name === 'admin-teams') && !isSuperadmin.value) return false
        if (isSuperadmin.value) return true  // 超管看全部导航（平台管理员）
        const required = NAV_PERMS[item.name] || []
        return required.length === 0 || required.every(p => perms.includes(p))
      }) }))
    .filter(g => g.items.length > 0)
})

// 通知
const unreadCount = ref(0)
const notifOpen = ref(false)
const recentNotifs = ref([])
// 铃铛只留工单/纯系统消息；广告层面（业务止损 + token/巡检等影响广告保护的）都进 Dashboard 告警
// 值域=后端 emit_notification 的广告类 event_type（budget_alerts 的 budget_progress_50/75/90/98、guard_engine、account_sync、notify_utils）
const ALERT_EVENT_TYPES = ['rule_pause', 'budget_progress_50', 'budget_progress_75', 'budget_progress_90',
  'budget_progress_98', 'account_status_change', 'account_status_recovered', 'sentinel_pause', 'token_expired',
  'token_invalid', 'token_expiring_soon', 'inspection_stalled', 'coverage_lost', 'account_permission_error',
  'token_rate_limited', 'orphan_account', 'subcode_cleanup']
const toggleNotifs = async () => {
  notifOpen.value = !notifOpen.value
  if (notifOpen.value) {
    try {
      const all = await GET('/notifications?limit=20')
      const items = Array.isArray(all) ? all : (all?.items || [])
      recentNotifs.value = items.filter(n => !ALERT_EVENT_TYPES.includes(n.event_type)).slice(0, 10)
    } catch {}
  }
}

// 安全面板
const guardStatus = ref({ rules_enabled: 0, sentinel_armed_accounts: 0, allowances_today: 0 })
const sentinelOn = ref(false)
const loadGuard = async () => {
  try {
    guardStatus.value = await GET('/guard/status')
    sentinelOn.value = guardStatus.value.sentinel_armed_accounts > 0
  } catch {}
}
const toggleSentinel = async (val) => {
  // disarm=关闭自动急停保护（资金安全行为）——必须确认；arm=开启保护，不拦
  if (!val) {
    try {
      await ElMessageBox.confirm(t('layout.sentinelDisarmConfirm'), t('layout.sentinelTitle'), { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'), confirmButtonClass: 'el-button--danger' })
    } catch { return }
  }
  try {
    await POST(`/guard/sentinel/${val ? 'arm' : 'disarm'}`, {})
    sentinelOn.value = val
    loadGuard()
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
}
const emergencyLoading = ref(false)
const emergencyPause = async () => {
  try {
    await ElMessageBox.confirm(t('layout.emergencyConfirm'), t('layout.emergencyTitle'), {
      type: 'error', confirmButtonText: t('layout.emergencyConfirmBtn'), cancelButtonText: t('common.cancel')
    })
  } catch { return }
  emergencyLoading.value = true
  try {
    await POST('/guard/emergency-pause', {})   // 后台异步执行，立即返回
    // 轮询进度直到完成（3s × 40 次上限）
    let st = null
    for (let i = 0; i < 40; i++) {
      await new Promise(r => setTimeout(r, 3000))
      try { st = await GET('/guard/emergency-status') } catch { st = null }
      if (st && !st.running) break
    }
    st = st || {}
    if (st.running) {
      ElMessage.warning(t('layout.emergencyStillRunning'))
    } else {
      const errs = (st.errors || []).join('\n').slice(0, 500)
      await ElMessageBox.alert(
        h('div', null, [
          h('p', { style: 'margin:0 0 8px;white-space:pre-line' },
            t('layout.emergencyResult', { paused: st.paused || 0, total: st.total_accounts || 0, failed: st.verify_failed || 0 })),
          errs ? h('div', null, [
            h('div', { style: 'font-weight:600;margin-bottom:4px' }, t('layout.emergencyErrors')),
            h('pre', { style: 'margin:0;max-height:180px;overflow:auto;font-size:12px;white-space:pre-wrap' }, errs),
          ]) : null,
        ]),
        t('layout.emergencyResultTitle'),
        { type: (st.verify_failed || 0) > 0 ? 'warning' : 'success', confirmButtonText: t('common.confirm') }
      ).catch(() => {})
    }
    loadGuard()
  } catch (e) { ElMessage.error(t('layout.emergencyFail', { msg: e.message || '' })) }
  emergencyLoading.value = false
}

// 用户
const userEmail = ref('')
const isSuperadmin = ref(isSuperadminSync())  // 初始化即从 token 解码（同步权威），onMounted /auth/me 再确认
const userRole = ref('')
// 团队切换（topbar）
const memberships = ref([])
const currentTenantName = ref('')
const currentTenantId = ref(null)
const switchTeam = async (tid) => {
  if (tid === currentTenantId.value) return
  try {
    const r = await POST('/auth/switch-tenant', { tenant_id: tid })
    setToken(r.access_token)
    ElMessage.success(t('layout.switchedTeam', { name: r.tenant_name }))
    location.reload()  // 新 tenant 上下文：权限/数据全变，整页重载最稳
  } catch (e) { ElMessage.error(e.message || t('layout.switchFail')) }
}
const logout = () => { setToken(''); setUserPerms([]); localStorage.removeItem('tova_super'); router.push('/login') }

// 轮询
let pollTimer = null
let poll = null  // 提到 setup 顶层，onUnmounted 才能引用
onMounted(async () => {
  try { const me = await GET('/auth/me'); userEmail.value = me.email; setUserTz(me.timezone)
    isSuperadmin.value = !!me.is_superadmin
    userRole.value = me.role || ''
    localStorage.setItem('tova_super', me.is_superadmin ? '1' : '0')
    memberships.value = me.memberships || []
    currentTenantName.value = me.tenant_name || ''
    currentTenantId.value = me.tenant_id
    // 存权限到 localStorage（路由守卫 + 导航过滤用）
    myPerms.value = me.permissions || []
    setUserPerms(me.permissions || [])
  } catch {}
  if (myPerms.value.includes('ads.pause') || isSuperadmin.value) loadGuard()
  poll = async () => {
    if (document.hidden) return
    try {
      const all = await GET('/notifications?unread_only=true&limit=50')
      const items = Array.isArray(all) ? all : (all?.items || [])
      unreadCount.value = items.filter(n => !ALERT_EVENT_TYPES.includes(n.event_type)).length
    } catch {}
  }
  poll(); pollTimer = setInterval(poll, 30000)
  document.addEventListener('visibilitychange', poll)
  document.addEventListener('click', closeNotifsOnOutside)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (poll) document.removeEventListener('visibilitychange', poll)
  document.removeEventListener('click', closeNotifsOnOutside)
  if (_mq) _mq.removeEventListener?.('change', _onMq)
})
const closeNotifsOnOutside = (e) => {
  if (!notifOpen.value) return
  if (e.target.closest('.notif-wrapper')) return
  if (e.target.closest('.nav-item')) return  // 不拦截导航点击
  notifOpen.value = false
}

const currentTitle = computed(() => route.meta.titleKey ? t(route.meta.titleKey) : '')
// 导航点击：先关所有弹窗再跳（防 el-dropdown click-outside 吞第一次点击）
const navTo = (name) => {
  notifOpen.value = false
  sidebarOpen.value = false  // 移动端：点导航后收起抽屉
  router.push({ name })
}
// 路由切换后收起移动端抽屉（浏览器后退等场景）
watch(() => route.path, () => { sidebarOpen.value = false })
