<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { GET, POST, setToken } from '../api'
import { useTheme } from '../composables/useTheme'
import { setUserTz, fmtTime } from '../composables/useTz'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getUserPerms, setUserPerms } from '../router'

const router = useRouter()
const route = useRoute()
const { theme, toggle: toggleTheme } = useTheme()

// 当前用户权限
const myPerms = ref([])
const ROLE_ZH = { owner: '管理员', operator: '操作员', finance: '财务' }

// 导航 → 所需权限（同 router/ROUTE_PERMS）
const NAV_PERMS = {
  dashboard: ['ads.read'], ads: ['ads.read'], 'ad-manager': ['ads.read'],
  landing: ['landing.manage'], guard: ['rules.read'], 'kpi-mapping': ['rules.read'],
  settings: [], members: ['members.manage'], tokens: ['ads.read'],
}

// 导航
const allNavGroups = [
  { title: '数据中心', items: [
    { name: 'dashboard', label: '数据看板', icon: 'DataAnalysis' },
  ]},
  { title: '广告管理', items: [
    { name: 'ads', label: '广告账户', icon: 'Promotion' },
    { name: 'ad-manager', label: '广告管理器', icon: 'Operation' },
  ]},
  { title: '自动化', items: [
    { name: 'landing', label: '落地页', icon: 'Link' },
    { name: 'guard', label: '规则引擎', icon: 'SetUp' },
  ]},
  { title: '授权', items: [
    { name: 'tokens', label: 'Facebook', icon: 'Connection' },
  ]},
  { title: '系统', items: [
    { name: 'settings', label: '设置', icon: 'Setting' },
    { name: 'members', label: '成员权限', icon: 'User' },
    { name: 'kpi-mapping', label: '转化映射', icon: 'Histogram' },
  ]},
]
// 按权限过滤导航项
const navGroups = computed(() => {
  const perms = myPerms.value
  return allNavGroups
    .map(g => ({ ...g, items: g.items.filter(item => {
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
const ALERT_EVENT_TYPES = ['rule_pause', 'budget_progress', 'account_status_change', 'sentinel_pause',
  'token_expired', 'token_invalid', 'token_expiring', 'inspection_stalled']
const toggleNotifs = async () => {
  notifOpen.value = !notifOpen.value
  if (notifOpen.value) {
    try {
      const all = await GET('/notifications?limit=20')
      recentNotifs.value = (all || []).filter(n => !ALERT_EVENT_TYPES.includes(n.event_type)).slice(0, 10)
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
  try {
    await POST(`/guard/sentinel/${val ? 'arm' : 'disarm'}`, {})
    sentinelOn.value = val
    loadGuard()
  } catch (e) { ElMessage.error(e.message || '操作失败') }
}
const emergencyPause = () => {
  ElMessageBox.confirm('确定要全局紧急暂停所有 ACTIVE 广告？此操作不可撤销。', '⚠️ 紧急暂停', {
    type: 'error', confirmButtonText: '确认暂停', cancelButtonText: '取消'
  }).then(async () => {
    try {
      ElMessage.warning('正在暂停所有广告…')
      const r = await POST('/guard/emergency-pause', {})
      ElMessage.success(`已暂停 ${r.paused || 0} 条广告`)
      loadGuard()
    } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
  }).catch(() => {})
}

// 用户
const userEmail = ref('')
const isSuperadmin = ref(false)
const userRole = ref('')
const logout = () => { setToken(''); setUserPerms([]); localStorage.removeItem('tova_super'); router.push('/login') }

// 轮询
let pollTimer = null
onMounted(async () => {
  try { const me = await GET('/auth/me'); userEmail.value = me.email; setUserTz(me.timezone)
    isSuperadmin.value = !!me.is_superadmin
    userRole.value = me.role || ''
    localStorage.setItem('tova_super', me.is_superadmin ? '1' : '0')
    // 存权限到 localStorage（路由守卫 + 导航过滤用）
    myPerms.value = me.permissions || []
    setUserPerms(me.permissions || [])
  } catch {}
  loadGuard()
  const poll = async () => {
    try {
      const all = await GET('/notifications?unread_only=true&limit=50')
      unreadCount.value = (all || []).filter(n => !ALERT_EVENT_TYPES.includes(n.event_type)).length
    } catch {}
  }
  poll(); pollTimer = setInterval(poll, 30000)
  // 点外部关通知
  document.addEventListener('click', closeNotifsOnOutside)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  document.removeEventListener('click', closeNotifsOnOutside)
})
const closeNotifsOnOutside = (e) => {
  if (notifOpen.value && !e.target.closest('.notif-wrapper')) notifOpen.value = false
}

const currentTitle = computed(() => route.meta.title || '')
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="logo" @click="router.push('/dashboard')">
        <span class="logo-text">Tova Ads</span>
      </div>
      <nav class="nav">
        <template v-for="group in navGroups" :key="group.title">
          <div class="nav-sec-title">{{ group.title }}</div>
          <div v-for="item in group.items" :key="item.name"
               class="nav-item" :class="{ active: route.name === item.name }"
               @click="router.push({ name: item.name })">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </div>
        </template>
      </nav>
      <div v-if="myPerms.includes('ads.pause') || isSuperadmin" class="guard-panel">
        <div class="guard-title">安全守护</div>
        <div class="guard-row">
          <span>哨兵</span>
          <el-switch :model-value="sentinelOn" @change="toggleSentinel" size="small"
                     active-color="#0a84ff" inactive-color="#3a3a5c" />
        </div>
        <div class="guard-row">
          <span>规则 {{ guardStatus.rules_enabled }} 条</span>
          <span class="guard-dot" :class="{ on: guardStatus.rules_enabled > 0 }"></span>
        </div>
        <button class="emergency-btn" @click="emergencyPause">全局紧急暂停</button>
      </div>
    </aside>

    <div class="main-area">
      <header class="topbar">
        <span class="page-title">{{ currentTitle }}</span>
        <div class="topbar-right">
          <el-icon class="topbar-icon" @click="toggleTheme" :title="theme === 'dark' ? '切亮色' : '切暗色'">
            <Sunny v-if="theme === 'dark'" />
            <Moon v-else />
          </el-icon>
          <div class="notif-wrapper" @click.stop>
            <el-badge :value="unreadCount" :hidden="unreadCount === 0" :max="99">
              <el-icon class="topbar-icon" @click="toggleNotifs"><Bell /></el-icon>
            </el-badge>
            <div v-if="notifOpen" class="notif-dropdown">
              <div class="notif-header">最近通知</div>
              <div v-for="n in recentNotifs" :key="n.id" class="notif-item">
                <span :class="['notif-level-dot', n.level]"></span>
                <div class="notif-body">
                  <div class="notif-text">{{ n.title }}</div>
                  <div class="notif-time">{{ fmtTime(n.created_at) }}</div>
                </div>
              </div>
              <div v-if="!recentNotifs.length" class="notif-empty">暂无通知</div>
            </div>
          </div>
          <el-dropdown trigger="click" @command="cmd => cmd === 'logout' && logout()">
            <span class="user-info">
              <el-icon class="topbar-icon"><User /></el-icon>
              <span class="user-email">{{ userEmail.split('@')[0] }}</span>
              <span v-if="isSuperadmin" class="role-badge super">超管</span>
              <span v-else class="role-badge">{{ ROLE_ZH[userRole] || userRole }}</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>{{ isSuperadmin ? '平台超管' : (ROLE_ZH[userRole] || userRole) }}</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="content">
        <RouterView />
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
.topbar-icon {
  font-size: 20px; color: var(--t2); cursor: pointer;
  transition: color 0.15s;
}
.topbar-icon:hover { color: var(--t1); }

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
</style>
