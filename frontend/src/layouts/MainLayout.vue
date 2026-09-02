<script setup>
import { ref, computed, onMounted, onUnmounted, watch, h } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { GET, POST, setToken } from '../api'
import { useTheme } from '../composables/useTheme'
import { useLocale } from '../composables/useLocale'
import { setUserTz, fmtTime } from '../composables/useTz'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getUserPerms, setUserPerms, isSuperadminSync, prefetchRoutes } from '../router'
import PlatformSeg from '../components/PlatformSeg.vue'
import { usePlatform } from '../composables/usePlatform'

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

// 全局平台上下文（usePlatform 单例，localStorage 'tova_platform'）：全局条是唯一写入入口，
// 各数据页只读 platform 联动过滤。选中 FB/TT 时 main-area 挂品牌顶线类（2px 语境色条）。
const { platform } = usePlatform()
const platformScope = computed(() => t(
  platform.value === 'fb' ? 'layout.platformScopeFb'
  : platform.value === 'tt' ? 'layout.platformScopeTt'
  : 'layout.platformScopeAll'
))
const brandTopline = computed(() => (platform.value === 'all' ? '' : 'brand-topline-' + platform.value))

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

// 平台上下文条只在数据相关页面显示（设置/成员/日志等无平台过滤语义，显示=假控件）
const PLATFORM_PAGES = new Set(['dashboard', 'ads', 'ad-manager', 'landing-logs'])
const showPlatformBar = computed(() => PLATFORM_PAGES.has(String(route.name)))
// 导航点击：先关所有弹窗再跳（防 el-dropdown click-outside 吞第一次点击）
const navTo = (name) => {
  notifOpen.value = false
  sidebarOpen.value = false  // 移动端：点导航后收起抽屉
  router.push({ name })
}
// 路由切换后收起移动端抽屉（浏览器后退等场景）
watch(() => route.path, () => { sidebarOpen.value = false })
</script>

<template>
  <div class="layout">
    <!-- 移动端遮罩（侧边栏打开时） -->
    <div v-if="isMobile" class="sidebar-backdrop" :class="{ show: sidebarOpen }" @click="sidebarOpen = false"></div>
    <aside class="sidebar" :class="{ open: isMobile && sidebarOpen }">
      <div class="logo" @click="router.push('/dashboard')">
        <span class="logo-text">Tova Ads</span>
      </div>
      <nav class="nav">
        <template v-for="group in navGroups" :key="group.titleKey">
          <div class="nav-sec-title">{{ t(group.titleKey) }}</div>
          <div v-for="item in group.items" :key="item.name"
               class="nav-item" :class="{ active: route.name === item.name }"
               @click="navTo(item.name)">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ t(item.labelKey) }}</span>
          </div>
        </template>
      </nav>
      <div v-if="myPerms.includes('ads.pause') || isSuperadmin" class="guard-panel">
        <div class="guard-title">{{ t('layout.safetyGuard') }}</div>
        <div class="guard-row">
          <span>{{ t('layout.sentinel') }}</span>
          <el-switch :model-value="sentinelOn" @change="toggleSentinel" size="small"
                     active-color="#0a84ff" inactive-color="#3a3a5c" />
        </div>
        <div class="guard-row">
          <span>{{ t('layout.rulesCount', { n: guardStatus.rules_enabled }) }}</span>
          <span class="guard-dot" :class="{ on: guardStatus.rules_enabled > 0 }"></span>
        </div>
        <button class="emergency-btn" :disabled="emergencyLoading" @click="emergencyPause">{{ emergencyLoading ? t('layout.pausing') : t('layout.emergencyPause') }}</button>
      </div>
    </aside>

    <div class="main-area" :class="brandTopline">
      <header class="topbar">
        <div class="topbar-left">
          <button v-if="isMobile" class="hamburger" @click="sidebarOpen = !sidebarOpen" aria-label="菜单">
            <el-icon><Fold v-if="sidebarOpen" /><Expand v-else /></el-icon>
          </button>
          <span class="page-title">{{ currentTitle }}</span>
        </div>
        <div class="topbar-right">
          <el-dropdown v-if="memberships.length > 1" trigger="click" @command="switchTeam">
            <span class="team-switcher">
              <el-icon><OfficeBuilding /></el-icon>
              <span class="team-name">{{ currentTenantName || t('layout.noTeam') }}</span>
              <span class="team-chip">{{ (currentTenantName || '?').slice(0, 2) }}</span>
              <el-icon v-if="memberships.length > 1" class="caret"><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="m in memberships" :key="m.tenant_id" :command="m.tenant_id"
                  :disabled="m.tenant_id === currentTenantId">
                  <span>{{ m.tenant_name }}</span>
                  <span class="mute-role">· {{ roleLabel(m.role) }}</span>
                  <span v-if="m.tenant_id === currentTenantId" class="cur-mark">{{ t('layout.current') }}</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <span class="lang-toggle" @click="toggleLocale"
                :title="locale === 'zh' ? t('layout.langToEn') : t('layout.langToZh')">
            {{ locale === 'zh' ? 'EN' : '中' }}
          </span>
          <el-icon class="topbar-icon" @click="toggleTheme" :title="theme === 'dark' ? t('layout.themeToLight') : t('layout.themeToDark')">
            <Sunny v-if="theme === 'dark'" />
            <Moon v-else />
          </el-icon>
          <div class="notif-wrapper" @click.stop>
            <el-badge :value="unreadCount" :hidden="unreadCount === 0" :max="99">
              <el-icon class="topbar-icon" @click="toggleNotifs"><Bell /></el-icon>
            </el-badge>
            <div v-if="notifOpen" class="notif-dropdown">
              <div class="notif-header">{{ t('layout.notifTitle') }}</div>
              <div v-for="n in recentNotifs" :key="n.id" class="notif-item">
                <span :class="['notif-level-dot', n.level]"></span>
                <div class="notif-body">
                  <div class="notif-text">{{ n.title }}</div>
                  <div class="notif-time">{{ fmtTime(n.created_at) }}</div>
                </div>
              </div>
              <div v-if="!recentNotifs.length" class="notif-empty">{{ t('layout.notifEmpty') }}</div>
            </div>
          </div>
          <el-dropdown trigger="click" @command="cmd => cmd === 'logout' && logout()">
            <span class="user-info">
              <el-icon class="topbar-icon"><User /></el-icon>
              <span class="user-email">{{ userEmail.split('@')[0] }}</span>
              <span v-if="isSuperadmin" class="role-badge super">{{ t('role.super') }}</span>
              <span v-else class="role-badge">{{ roleLabel(userRole) }}</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>{{ isSuperadmin ? t('role.superadmin') : roleLabel(userRole) }}</el-dropdown-item>
                <el-dropdown-item command="logout" divided>{{ t('layout.logout') }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <!-- 全局平台上下文条：全站唯一的平台切换入口（写 usePlatform 单例），右缘显当前范围说明 -->
      <div v-if="showPlatformBar" class="platform-context-bar">
        <PlatformSeg size="bar" :title="t('layout.platformFilter')" />
        <span class="pc-scope">{{ platformScope }}</span>
      </div>

      <main class="content">
        <!-- keep-alive 缓存重数据页：切 Tab 即回显不重拉（Dashboard 有 60s 自动刷新兜新鲜度）。
             exclude 依赖 route.query 深链的 5 页（缓存后 onMounted 不重跑会丢 query 语义）：
             AdManager(?act)/Landing(?tab)/LandingLogs(?tab,slug,ad_id)/LaunchTemplates(?reuse_post)/Tokens(?oauth) -->
        <RouterView v-slot="{ Component }">
          <!-- exclude = 依赖 route.query 深链状态的页（Landing 内嵌的 LandingLogs tab 随 Landing 一并被排除） -->
          <KeepAlive :exclude="['AdManager', 'Landing', 'LaunchTemplates', 'Tokens']" :max="12">
            <component :is="Component" />
          </KeepAlive>
        </RouterView>
      </main>
    </div>
  </div>
</template>

<style scoped>
.layout { display: flex; height: 100vh; overflow: hidden; }

/* 侧栏 */
.sidebar {
  width: var(--sw);
  background: var(--sidebar-bg);
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--bd);
  flex-shrink: 0;
  z-index: var(--z-sidebar);
  transition: background 0.2s, border-color 0.2s;
}
.logo { height: var(--topbar-h); display: flex; align-items: center; padding: 0 20px; cursor: pointer; }
.logo-text { font-size: 16px; font-weight: 700; color: var(--ac); }
.nav { flex: 1; overflow-y: auto; padding: 4px 12px; }
.nav-sec-title {
  font-size: 11px; color: var(--t3); text-transform: uppercase;
  letter-spacing: 0.05em; padding: 16px 12px 6px;
}
.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; border-radius: var(--rs);
  color: var(--t2); cursor: pointer; font-size: 14px;
  transition: all 0.15s; position: relative;
}
.nav-item:hover { background: var(--bg3); color: var(--t1); }
.nav-item.active { background: var(--acg); color: var(--ac); }
.nav-item.active::before {
  content: ''; position: absolute; left: 0; top: 6px; bottom: 6px;
  width: 3px; background: var(--ac); border-radius: 2px;
}
.nav-item .el-icon { font-size: 18px; }

/* 安全面板 */
.guard-panel { padding: 12px 16px; border-top: 1px solid var(--bd); }
.guard-title { font-size: 11px; color: var(--t3); text-transform: uppercase; margin-bottom: 8px; }
.guard-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 4px 0; font-size: 13px; color: var(--t2);
}
.guard-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--t3); }
.guard-dot.on { background: var(--success); box-shadow: 0 0 6px var(--success); }
.emergency-btn {
  width: 100%; padding: 7px; margin-top: 8px;
  background: var(--error); color: #fff; border: none;
  border-radius: var(--rs); font-size: 12px; cursor: pointer;
  opacity: 0.8; transition: opacity 0.15s;
}
.emergency-btn:hover { opacity: 1; }

/* 主区域 */
.main-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.topbar {
  height: var(--topbar-h);
  display: flex; justify-content: space-between; align-items: center;
  padding: 0 24px;
  background: var(--topbar-bg);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--bd);
  flex-shrink: 0;
  z-index: 200;  /* 高于 Dashboard sticky-top(100)：backdrop-filter 创建 stacking context，
                    topbar 整体层级必须 > sticky-top，否则铃铛 dropdown(topbar内 z200) 被 sticky-top 挡 */
  transition: background 0.2s, border-color 0.2s;
}
.page-title { font-size: 18px; font-weight: 600; color: var(--t1); }
.topbar-right { display: flex; align-items: center; gap: 16px; }
/* 团队切换器 */
.team-switcher {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 10px; border-radius: var(--rs);
  background: var(--bg3); color: var(--t2); cursor: pointer;
  font-size: 13px; transition: background 0.15s;
}
.team-switcher:hover { background: var(--bg2); color: var(--t1); }
.team-switcher .el-icon { font-size: 15px; }
.team-switcher .caret { font-size: 11px; opacity: 0.6; }
.team-name { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.team-chip { display: none; }
.mute-role { color: var(--t3); font-size: 11px; margin-left: 4px; }
.cur-mark { color: var(--ac); font-size: 11px; margin-left: 6px; }
.topbar-icon {
  font-size: 20px; color: var(--t2); cursor: pointer;
  transition: color 0.15s;
}
.topbar-icon:hover { color: var(--t1); }
/* 语言切换（显眼文字 chip） */
.lang-toggle {
  font-size: 12px; font-weight: 700; letter-spacing: 0.02em;
  padding: 3px 8px; border-radius: var(--rs);
  background: var(--bg3); color: var(--t2); cursor: pointer;
  user-select: none; transition: background 0.15s, color 0.15s;
}
.lang-toggle:hover { background: var(--acg); color: var(--ac); }

/* 通知下拉 */
.notif-wrapper { position: relative; }
.notif-dropdown {
  position: absolute; right: 0; top: 36px;
  width: 340px;
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--rs);
  box-shadow: var(--shadow-dropdown);
  z-index: var(--z-dropdown);
  max-height: 420px; overflow-y: auto;
}
.notif-header {
  padding: 12px 16px; font-size: 13px; color: var(--t3);
  border-bottom: 1px solid var(--bd);
}
.notif-item {
  display: flex; align-items: flex-start; gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--bd);
  cursor: pointer; transition: background 0.1s;
}
.notif-item:hover { background: var(--bg3); }
.notif-item:last-child { border-bottom: none; }
.notif-level-dot {
  width: 8px; height: 8px; border-radius: 50%;
  margin-top: 5px; flex-shrink: 0;
}
.notif-level-dot.warning { background: var(--warning); }
.notif-level-dot.critical { background: var(--error); }
.notif-level-dot.info { background: var(--ac); }
.notif-body { flex: 1; }
.notif-text { font-size: 13px; color: var(--t1); line-height: 1.4; }
.notif-time { font-size: 11px; color: var(--t3); margin-top: 2px; }
.notif-empty { padding: 28px; text-align: center; color: var(--t3); font-size: 13px; }

/* 用户 */
.user-info {
  display: flex; align-items: center; gap: 6px;
  cursor: pointer; color: var(--t2);
}
.user-email { font-size: 13px; }
.role-badge { font-size: 10px; padding: 1px 6px; border-radius: 4px; background: var(--bg3); color: var(--t3); margin-left: 6px; white-space: nowrap }
.role-badge.super { background: rgba(255,159,10,.15); color: var(--warning); font-weight: 600 }

/* 内容（min-height:0 是 flex+overflow 必需，否则被子内容撑高导致整 main-area 滚、sticky 失效）*/
.content { flex: 1; overflow-y: auto; padding: 24px; min-height: 0; }

/* topbar-left（汉堡+标题） */
.topbar-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.hamburger { display: none; background: none; border: none; color: var(--t1); cursor: pointer; padding: 4px; font-size: 20px; }

/* 移动端：侧边栏改抽屉 + 顶栏自适应 */
.sidebar-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 2000; opacity: 0; pointer-events: none; transition: opacity .2s; }
.sidebar-backdrop.show { opacity: 1; pointer-events: auto; }
@media (max-width: 768px) {
  .hamburger { display: inline-flex; }
  .sidebar {
    position: fixed; left: 0; top: 0; bottom: 0; z-index: 2001;
    transform: translateX(-100%); transition: transform .22s ease;
    box-shadow: 2px 0 12px rgba(0,0,0,.3);
  }
  .sidebar.open { transform: translateX(0); }
  .topbar { padding: 0 12px; gap: 8px; }
  .topbar-right { gap: 10px; }
  .team-name, .user-email { display: none; }  /* 手机隐藏全名，用首字 chip 替代 */
  .team-chip { display: inline-flex !important; font-size: 11px; padding: 1px 6px; border-radius: 6px; background: var(--acg); color: var(--ac); font-weight: 600; }
  .role-badge { display: none; }
  .page-title { font-size: 15px; }
  .content { padding: 12px; }
  .notif-dropdown { width: 88vw !important; max-width: 340px; }
}
</style>
