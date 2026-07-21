<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { GET, POST, DELETE } from '../api'
import { ElMessage, ElMessageBox, useZIndex } from 'element-plus'
const { nextZIndex } = useZIndex()
const route = useRoute()
// 自定义 overlay 用 EP 的 nextZIndex 取 z-index，保证在 el-drawer(2000+) 之上，
// 且从 overlay 内弹出的 ElMessageBox 又在 overlay 之上（EP 共享计数器单调递增）。
const ovZ = ref(2050)
const popOverlay = () => { ovZ.value = nextZIndex() }

const tokens = ref([])
const loading = ref(true)
const editId = ref(null)
const editAlias = ref('')
const importOpen = ref(false)
const importTab = ref('oauth')
const importForm = ref({ access_token: '', alias: '', token_type: 'operate' })
const importing = ref(false)
const appConfigOpen = ref(false)
const apps = ref([])
const appLoading = ref(false)
const appForm = ref({ app_id: '', app_secret: '', name: '', is_system: false })
const appEditing = ref(null)

const drawerOpen = ref(false)
const drawerToken = ref(null)
const drawerTab = ref('accounts')
const assetCache = ref({})
const assetLoading = ref(false)

const summaryCache = ref({})

// 风险账户（绑定令牌不可用）—— 实时 DB 检测，令牌页提示
const atRiskAccounts = ref([])
const atRiskOpen = ref(false)

// 导入账户 modal（勾选清单 / ID 导入）
const loadOpen = ref(false)
const loadTab = ref('list')
const loadableAccounts = ref([])
const loadLoading = ref(false)
const loadSearch = ref('')
const loadSelected = ref({})
const loadIdText = ref('')
const loadImporting = ref(false)

const load = async () => {
  loading.value = true
  try { tokens.value = await GET('/fb/credentials') }
  catch (e) { ElMessage.error(e.message || '加载失败') }
  loading.value = false
}
const loadSummary = async () => {
  try { summaryCache.value = await GET('/fb/credentials/assets-summary') }
  catch { /* 静默：账户列退回本地计数 */ }
}
const loadAtRisk = async () => {
  try { atRiskAccounts.value = await GET('/fb/accounts/at-risk') }
  catch { atRiskAccounts.value = [] }
}
onMounted(() => {
  load(); loadSummary(); loadAtRisk()
  // OAuth 回调处理（FB 授权后 302 回来 ?oauth=ok/fail&msg=）
  const st = route.query.oauth
  if (st === 'ok') ElMessage.success('Facebook 授权成功，令牌已导入')
  else if (st === 'fail') ElMessage.error('授权失败：' + (route.query.msg || '未知错误'))
})

const statusOrder = (t) => {
  const s = t.status, f = t.consecutive_fails || 0
  if (['expired','revoked','inactive'].includes(s)) return 0
  if (['suspended','limited'].includes(s) || f >= 3) return 1
  if (s === 'disabled') return 2
  return 3
}
const sortedTokens = computed(() => [...tokens.value].sort((a, b) => statusOrder(a) - statusOrder(b)))

const statusMeta = (t) => {
  const s = t.status, f = t.consecutive_fails || 0
  if (['expired','revoked','inactive'].includes(s)) return { dot: 'err', label: '失效' }
  if (['limited'].includes(s) || f >= 3) return { dot: 'warn', label: `限流${f}` }
  if (s === 'suspended') return { dot: 'warn', label: '待认证' }
  if (s === 'disabled') return { dot: 'off', label: '停用' }
  if (f > 0) return { dot: 'warn', label: `异常${f}` }
  return { dot: 'ok', label: '正常' }
}
const TYPE_META = {
  operate: { label: '操作', title: '操作号：可写广告 + 读 + 可暂停' },
  manage:  { label: '管理', title: '管理号：读 + 可暂停，不建新广告' },
  user:    { label: '只读', title: '只读号：仅查看，不可写/暂停' },
}
const typeMeta = (t) => TYPE_META[t] || TYPE_META.user
const sourceLabel = (s) => ({ manual: '手动', oauth: 'OAuth' }[s] || '—')
const fmtTime = (s) => {
  if (!s || s === 'None') return '—'
  const d = new Date(s.endsWith('Z') ? s : s.replace(' ', 'T') + 'Z')
  if (isNaN(d)) return '—'
  const diff = (Date.now() - d.getTime()) / 60000
  if (diff < 1) return '刚刚'
  if (diff < 60) return `${Math.floor(diff)}分前`
  if (diff < 1440) return `${Math.floor(diff/60)}时前`
  return d.toLocaleDateString('zh-CN')
}
const permCount = (p) => (!p || !p.scopes) ? 0 : p.scopes.length

const accountStatusMeta = (s) => {
  const n = Number(s)
  if (n === 1) return { label: '可用', cls: 'ok' }
  if (n === 2) return { label: '已禁用', cls: 'off' }
  if (n === 3) return { label: '未结算', cls: 'warn' }
  if (n === 7) return { label: '被封', cls: 'err' }
  if (n === 9) return { label: '待关闭', cls: 'warn' }
  return { label: '—', cls: 'off' }
}
const SCOPE_LABELS = {
  ads_management: '广告管理', ads_read: '广告读取',
  pages_show_list: '主页展示', pages_messaging: '主页消息',
  pages_manage_metadata: '主页管理元数据', pages_read_engagement: '主页读取互动',
  pages_manage_posts: '主页管理帖子', pages_read_user_content: '主页读取用户内容',
  pages_manage_engagement: '主页管理互动', pages_events: '主页事件',
  business_management: '商务管理平台', read_insights: '读取分析',
  instagram_basic: 'Instagram 基础', instagram_manage_insights: 'Instagram 管理分析',
  instagram_manage_comments: 'Instagram 管理评论',
  public_profile: '公共主页资料', email: '邮箱',
  attribution_read: '归因读取', catalog_management: '目录管理',
  whatsapp_business_management: 'WhatsApp 商务管理',
  leads_retrieval: '潜在客户检索', pages_manage_cta: '主页管理 CTA',
}
const scopeLabel = (s) => SCOPE_LABELS[s] || s

const copyId = async (id) => {
  if (!id) return
  try { await navigator.clipboard.writeText(id); ElMessage.success('已复制 ' + id) }
  catch { ElMessage.warning('复制失败，请手动选择') }
}

const countOf = (t, kind) => {
  const cached = assetCache.value[t.id]
  if (cached && Array.isArray(cached[kind])) return cached[kind].length
  const s = summaryCache.value[t.id]
  if (s && s[kind] != null) return s[kind]
  if (kind === 'accounts' && t.account_count != null) return t.account_count
  return '—'
}
const summaryError = (t) => summaryCache.value[t.id]?.error || ''

// 抽屉资产：可用优先排序
const drawerAccounts = computed(() => {
  const list = drawerToken.value && assetCache.value[drawerToken.value.id]?.accounts
  if (!list) return []
  return [...list].sort((a, b) => (a.account_status === 1 ? 0 : 1) - (b.account_status === 1 ? 0 : 1))
})
const drawerBusinesses = computed(() => {
  const list = drawerToken.value && assetCache.value[drawerToken.value.id]?.businesses
  if (!list) return []
  return [...list].sort((a, b) => (a.role === '完全' ? 0 : 1) - (b.role === '完全' ? 0 : 1))
})
const drawerPages = computed(() => {
  const list = drawerToken.value && assetCache.value[drawerToken.value.id]?.pages
  if (!list) return []
  return [...list].sort((a, b) => (b.fan_count || 0) - (a.fan_count || 0))
})

const refreshAll = async () => {
  let ok = 0, fail = 0
  ElMessage.info('检测全部令牌中…')
  for (const t of tokens.value) {
    try { const r = await POST(`/fb/credentials/${t.id}/check`, {}); r.now_valid ? ok++ : fail++ }
    catch { fail++ }
  }
  await load()
  await loadAtRisk()
  ElMessage.success(`完成：${ok} 个正常，${fail} 个异常`)
}
const refreshAccounts = async (t) => {
  try { ElMessage.info('刷新中…'); const r = await POST(`/fb/credentials/${t.id}/refresh-accounts`, {}); delete assetCache.value[t.id]; await loadDrawerAssets(t); ElMessage.success(`已刷新 ${r.updated||0} 个账户`) }
  catch (e) { ElMessage.error('刷新失败：'+(e.message||'')) }
}
const handleAction = (cmd, t) => {
  if (cmd === 'check') checkToken(t)
  else if (cmd === 'refresh') refreshAccounts(t)
  else if (cmd === 'delete') deleteToken(t)
}
const handleAccountCmd = async (cmd, a) => {
  if (cmd === 'unmanage') {
    try {
      await ElMessageBox.confirm(`取消纳管「${a.name}」？将不再管理此账户（令牌权限不变，FB 上仍存在，可随时重新导入）。`, '确认', {type:'warning'})
      await DELETE(`/fb/accounts/${a.account_id}`)
      ElMessage.success('已取消纳管')
      if (drawerToken.value) await loadDrawerAssets(drawerToken.value)
      await Promise.all([load(), loadSummary(), loadAtRisk()])
    } catch {}
  }
}

const startEdit = (t) => { editId.value = t.id; editAlias.value = t.alias || '' }
const saveEdit = async (t) => {
  if (editId.value === null) return
  const id = editId.value, val = editAlias.value.trim()
  editId.value = null
  if (val === (t.alias || '')) return
  try { await POST(`/fb/credentials/${id}/rename`, { alias: val }); t.alias = val; ElMessage.success('已更新') }
  catch { ElMessage.error('更新失败') }
}

const loadDrawerAssets = async (t) => {
  assetLoading.value = true
  try {
    const data = await GET(`/fb/credentials/${t.id}/assets`)
    assetCache.value[t.id] = { accounts: data.accounts || [], pages: data.pages || [],
                               businesses: data.businesses || [], error: data.error || null }
    if (data.error) ElMessage.warning(`部分资产读取失败：${data.error}`)
  } catch (e) { assetCache.value[t.id] = { accounts: [], pages: [], businesses: [], error: e.message || '读取失败' } }
  assetLoading.value = false
}
const openDrawer = async (t) => {
  drawerToken.value = t
  drawerTab.value = 'accounts'
  drawerOpen.value = true
  if (!assetCache.value[t.id]) await loadDrawerAssets(t)
}
const onTabChange = () => {}
const drawerTitle = computed(() => {
  if (!drawerToken.value) return ''
  return `${drawerToken.value.fb_user_name || '未知'} · 用户资产`
})

// 导入账户
const openLoad = async () => {
  popOverlay()
  loadOpen.value = true
  loadTab.value = 'list'
  loadSearch.value = ''
  loadIdText.value = ''
  loadSelected.value = {}
  loadLoading.value = true
  try { loadableAccounts.value = await GET('/fb/credentials/loadable-accounts') }
  catch (e) { ElMessage.error('拉取失败：'+(e.message||'')); loadableAccounts.value = [] }
  loadLoading.value = false
}
const filteredLoadable = computed(() => {
  const q = loadSearch.value.trim().toLowerCase()
  let arr = loadableAccounts.value
  if (q) arr = arr.filter(a => (a.name || '').toLowerCase().includes(q) || (a.account_id || '').includes(q))
  return [...arr].sort((a, b) => (a.account_status === 1 ? 0 : 1) - (b.account_status === 1 ? 0 : 1)
    || (a.imported ? 1 : 0) - (b.imported ? 1 : 0))
})
const loadSelectedCount = computed(() => Object.values(loadSelected.value).filter(Boolean).length)
const doImport = async (ids) => {
  loadImporting.value = true
  try {
    const r = await POST('/fb/import', { account_ids: ids })
    const parts = [`导入 ${r.count}`]
    if (r.skipped_existing) parts.push(`跳过已存在 ${r.skipped_existing}`)
    if (r.not_found && r.not_found.length) parts.push(`未找到 ${r.not_found.length}`)
    ElMessage.success(parts.join(' · '))
    loadOpen.value = false
    await Promise.all([load(), loadSummary(), loadAtRisk()])
    if (drawerToken.value) await loadDrawerAssets(drawerToken.value)
  } catch (e) { ElMessage.error('导入失败：'+(e.message||'')) }
  loadImporting.value = false
}
const commitLoadList = async () => {
  const impSet = new Set(loadableAccounts.value.filter(a => a.imported).map(a => a.account_id))
  const ids = Object.keys(loadSelected.value).filter(k => loadSelected.value[k] && !impSet.has(k))
  if (!ids.length) { ElMessage.warning('勾选未导入的账户'); return }
  await doImport(ids)
}
const commitLoadIds = async () => {
  const ids = loadIdText.value.split(/[\s,]+/).map(s => s.trim()).filter(Boolean)
  if (!ids.length) { ElMessage.warning('粘贴账户 ID'); return }
  await doImport(ids)
}

// App
const loadApps = async () => { appLoading.value = true; try { apps.value = await GET('/fb/apps') } catch { apps.value = [] }; appLoading.value = false }
const openAppConfig = async () => { popOverlay(); appConfigOpen.value = true; await loadApps() }
const saveApp = async () => {
  if (!appForm.value.app_id.trim() || !appForm.value.app_secret.trim()) { ElMessage.warning('填 App ID + Secret'); return }
  try {
    if (appEditing.value) await POST(`/fb/apps/${appEditing.value}`, { ...appForm.value })
    else await POST('/fb/apps', { ...appForm.value })
    ElMessage.success('已保存'); appForm.value = { app_id:'', app_secret:'', name:'', is_system:false }; appEditing.value = null; await loadApps()
  } catch { ElMessage.error('失败') }
}
const editApp = (a) => { appEditing.value = a.id; appForm.value = { app_id: a.app_id, app_secret: '', name: a.name||'', is_system: a.is_system } }
const deleteApp = async (a) => { try { await ElMessageBox.confirm(`删除「${a.name||a.app_id}」？`, '确认', {type:'warning'}); await DELETE(`/fb/apps/${a.id}`); ElMessage.success('已删'); await loadApps() } catch {} }
const systemApps = computed(() => apps.value.filter(a => a.is_system))
const myApps = computed(() => apps.value.filter(a => !a.is_system))
const startOAuth = async (a) => {
  try { const r = await GET(`/fb/oauth/start?app_pk=${a.id}`); if (r.url) window.location.href = r.url }
  catch (e) { ElMessage.error('启动授权失败：' + (e.message || '')) }
}

const submitImport = async () => {
  if (!importForm.value.access_token.trim()) return ElMessage.warning('填 token')
  importing.value = true
  try { await POST('/fb/credentials', { access_token: importForm.value.access_token.trim(), alias: importForm.value.alias.trim(), token_type: importForm.value.token_type }); ElMessage.success('成功'); importOpen.value = false; importForm.value = { access_token:'', alias:'', token_type:'operate' }; await Promise.all([load(), loadSummary(), loadAtRisk()]) }
  catch (e) { ElMessage.error('失败：'+(e.message||'')) }
  importing.value = false
}
const checkToken = async (t) => {
  try { ElMessage.info('检测中…'); const r = await POST(`/fb/credentials/${t.id}/check`, {}); r.now_valid ? ElMessage.success(r.detail||'正常') : ElMessage.warning(r.detail||'异常') }
  catch { ElMessage.error('检测失败') }
  delete assetCache.value[t.id]; await load(); await loadAtRisk()
}
const deleteToken = async (t) => {
  try { await ElMessageBox.confirm(`删除「${t.alias||t.fb_user_name||t.id}」？关联账户将解绑。`, '确认', {type:'warning'}); await DELETE(`/fb/credentials/${t.id}`); ElMessage.success('已删'); await Promise.all([load(), loadSummary(), loadAtRisk()]) }
  catch {}
}
</script>

<template>
  <div class="page">
    <div class="bar">
      <div class="bar-r">
        <button class="btn primary" @click="importOpen = true">连接 Facebook</button>
        <button class="btn" @click="openLoad">导入账户</button>
        <button class="btn" @click="openAppConfig">配置 App</button>
        <button class="btn" @click="refreshAll">刷新全部</button>
      </div>
    </div>

    <div v-if="atRiskAccounts.length" class="risk-banner" @click="atRiskOpen = !atRiskOpen">
      <span>⚠ {{ atRiskAccounts.length }} 个账户缺少可用令牌，暂无法读写</span>
      <span class="risk-toggle">{{ atRiskOpen ? '收起 ▲' : '查看 ▼' }}</span>
    </div>
    <div v-if="atRiskOpen && atRiskAccounts.length" class="risk-list">
      <div v-for="a in atRiskAccounts" :key="a.act_id" class="risk-row">
        <span class="ai-name">{{ a.name }}</span>
        <span class="ai-id blue" @click.stop="copyId(a.act_id)">{{ a.act_id }}</span>
        <span class="ai-meta">{{ a.bound_alias ? ('原绑 ' + a.bound_alias) : '未绑定令牌' }}</span>
        <span class="st-tag" :class="a.bound_status==='unbound'?'off':'err'">{{ a.bound_status==='unbound'?'未绑定':a.bound_status }}</span>
      </div>
    </div>

    <div class="tbl" v-loading="loading">
      <div class="row head">
        <span>状态</span><span>名称</span><span>FB 用户</span>
        <span class="num-h">账户</span><span class="num-h">主页</span><span class="num-h">BM</span>
        <span>类型</span><span></span>
      </div>
      <div v-for="t in sortedTokens" :key="t.id" class="row" :class="statusMeta(t).dot" @click="openDrawer(t)">
        <span class="c-st"><span class="dot" :class="statusMeta(t).dot"></span>{{ statusMeta(t).label }}</span>
        <span class="c-nm" @click.stop>
          <input v-if="editId===t.id" v-model="editAlias" class="inp" @keyup.enter="saveEdit(t)" @blur="saveEdit(t)" />
          <span v-else class="nm" @click="startEdit(t)">{{ t.alias || '未命名' }}<span class="pen">✎</span></span>
        </span>
        <span class="c-fb">
          <span class="fbn">{{ t.fb_user_name || '—' }}</span>
          <span class="fbi" :title="t.fb_user_id">{{ t.fb_user_id?.slice(-10) || '—' }}</span>
        </span>
        <span class="c-num" :class="{err:summaryError(t)}" :title="summaryError(t)||'已导入账户数'">{{ summaryError(t) ? '!' : countOf(t,'accounts') }}</span>
        <span class="c-num">{{ countOf(t,'pages') }}</span>
        <span class="c-num">{{ countOf(t,'businesses') }}</span>
        <span class="c-ty"><span class="tag" :class="t.token_type" :title="typeMeta(t.token_type).title">{{ typeMeta(t.token_type).label }}</span></span>
        <span class="c-op" @click.stop>
          <el-dropdown trigger="click" @command="cmd => handleAction(cmd, t)">
            <button class="dots-btn" @click.stop>⋯</button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="check">检测有效性</el-dropdown-item>
                <el-dropdown-item command="refresh">刷新账户</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除令牌</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </span>
      </div>
      <div v-if="!tokens.length && !loading" class="empty">暂无令牌</div>
    </div>

    <el-drawer v-model="drawerOpen" :title="drawerTitle" direction="rtl" size="480px" :destroy-on-close="true">
      <div v-if="drawerToken" class="info-sec">
        <div class="info-grid">
          <div class="info-cell"><label>令牌名称</label><span>{{ drawerToken.alias || '未命名' }}</span></div>
          <div class="info-cell"><label>类型 / 来源</label><span :title="typeMeta(drawerToken.token_type).title">{{ typeMeta(drawerToken.token_type).label }} · {{ sourceLabel(drawerToken.token_source) }}</span></div>
          <div class="info-cell"><label>最近检测</label><span>{{ fmtTime(drawerToken.last_verified_at) }}</span></div>
          <div class="info-cell"><label>连续失败</label><span :class="{warn:(drawerToken.consecutive_fails||0)>=1}">{{ drawerToken.consecutive_fails || 0 }} 次</span></div>
          <div class="info-cell"><label>关联账户</label><span>{{ drawerToken.account_count ?? 0 }} 个（已导入）</span></div>
          <div class="info-cell"><label>权限数</label><span>{{ permCount(drawerToken.permission_snapshot) }} 项</span></div>
        </div>
      </div>

      <div class="drawer-tabs">
        <button v-for="tab in ['accounts','pages','businesses','perm']" :key="tab" class="d-tab" :class="{on:drawerTab===tab}" @click="drawerTab=tab;onTabChange()">
          {{ {accounts:'广告账户',pages:'主页',businesses:'BM',perm:'权限详情'}[tab] }}
        </button>
      </div>
      <div v-loading="assetLoading">
        <div v-if="drawerTab==='accounts'">
          <div v-if="drawerToken && statusMeta(drawerToken).dot !== 'ok'" class="token-warn">
            ⚠ 此令牌当前不可用（{{ statusMeta(drawerToken).label }}），名下账户暂无法读写——建议检测令牌，或用可用令牌重新导入绑定。
          </div>
          <div class="add-row"><button class="add-btn" @click="openLoad">+ 添加账户</button></div>
          <div v-if="drawerAccounts.length" class="asset-list">
            <div v-for="a in drawerAccounts" :key="a.account_id" class="asset-item">
              <div class="ai-main">
                <span class="ai-name">{{ a.name }}</span>
                <span class="ai-id blue" title="点击复制" @click.stop="copyId(a.account_id)">{{ a.account_id }}</span>
                <span class="ai-meta" v-if="a.balance_label">可用 · {{ a.balance_label }}</span>
              </div>
              <span class="st-tag" :class="accountStatusMeta(a.account_status).cls">{{ accountStatusMeta(a.account_status).label }}</span>
              <el-dropdown trigger="click" @command="cmd => handleAccountCmd(cmd, a)" @click.stop>
                <button class="dots-btn small" @click.stop>⋯</button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="publish">发布广告（即将上线）</el-dropdown-item>
                    <el-dropdown-item command="insights">查看数据洞察（即将上线）</el-dropdown-item>
                    <el-dropdown-item command="unmanage" divided>取消纳管</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
          <div v-else-if="!assetLoading" class="drawer-empty">暂无已导入账户</div>
        </div>
        <div v-if="drawerTab==='pages'">
          <div v-if="drawerPages.length" class="asset-list">
            <div v-for="p in drawerPages" :key="p.id" class="asset-item">
              <div class="ai-main">
                <span class="ai-name">{{ p.name }}</span>
                <span class="ai-id blue" title="点击复制" @click.stop="copyId(p.id)">{{ p.id }}</span>
                <span class="ai-meta" v-if="p.category">{{ p.category }}</span>
                <span class="ai-meta" v-if="p.fan_count">{{ p.fan_count }} 粉丝</span>
              </div>
              <span class="st-tag ok">可用</span>
              <el-dropdown trigger="click" @click.stop>
                <button class="dots-btn small" @click.stop>⋯</button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item @click.stop>改名（即将上线）</el-dropdown-item>
                    <el-dropdown-item @click.stop>修改类型（即将上线）</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
          <div v-else-if="!assetLoading" class="drawer-empty">无主页</div>
        </div>
        <div v-if="drawerTab==='businesses'">
          <div v-if="drawerBusinesses.length" class="asset-list">
            <div v-for="b in drawerBusinesses" :key="b.id" class="asset-item">
              <div class="ai-main">
                <span class="ai-name">{{ b.name }}</span>
                <span class="ai-id blue" title="点击复制" @click.stop="copyId(b.id)">{{ b.id }}</span>
              </div>
              <span class="st-tag" :class="b.role==='完全'?'ok':'off'">{{ b.role }}</span>
              <el-dropdown trigger="click" @click.stop>
                <button class="dots-btn small" @click.stop>⋯</button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item @click.stop>查看成员（即将上线）</el-dropdown-item>
                    <el-dropdown-item @click.stop>管理资产（即将上线）</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
          <div v-else-if="!assetLoading" class="drawer-empty">无 BM</div>
        </div>
        <div v-if="drawerTab==='perm' && drawerToken" class="perm-detail">
          <div class="sec-title">权限（{{ permCount(drawerToken.permission_snapshot) }}）</div>
          <div class="perm-tags"><span v-for="s in (drawerToken.permission_snapshot?.scopes||[])" :key="s" class="tag-mono" :title="s">{{ scopeLabel(s) }}</span></div>
          <div class="sec-title mt">详情</div>
          <div class="kv"><label>App ID</label><code>{{ drawerToken.permission_snapshot?.app_id || '—' }}</code></div>
          <div class="kv"><label>用户 ID</label><code>{{ drawerToken.fb_user_id || '—' }}</code></div>
          <div class="kv"><label>状态</label><span>{{ statusMeta(drawerToken).label }}</span></div>
        </div>
      </div>
      <div v-if="drawerToken && assetCache[drawerToken.id]?.error" class="asset-err">部分资产读取失败：{{ assetCache[drawerToken.id].error }}</div>
    </el-drawer>

    <div v-if="loadOpen" class="overlay" :style="{ zIndex: ovZ }" @click.self="loadOpen=false">
      <div class="modal wide">
        <div class="m-title">导入账户</div>
        <div class="m-tabs">
          <button class="mt-btn" :class="{on:loadTab==='list'}" @click="loadTab='list'">勾选清单</button>
          <button class="mt-btn" :class="{on:loadTab==='ids'}" @click="loadTab='ids'">ID 导入</button>
        </div>
        <div v-if="loadTab==='list'">
          <input v-model="loadSearch" class="input load-search" placeholder="模糊搜索：账户名或 ID" />
          <div class="load-meta">共 {{ loadableAccounts.length }} 个可管理账户，已选 {{ loadSelectedCount }}</div>
          <div v-loading="loadLoading" class="load-list">
            <label v-for="a in filteredLoadable" :key="a.account_id" class="load-row" :class="{off:a.imported}">
              <input type="checkbox" :checked="!!loadSelected[a.account_id]" :disabled="a.imported" @change="loadSelected[a.account_id] = $event.target.checked" />
              <span class="ai-name">{{ a.name }}</span>
              <span class="ai-id blue" @click.stop="copyId(a.account_id)">{{ a.account_id }}</span>
              <span v-if="a.imported" class="imp-mark">已导入</span>
              <span class="st-tag" :class="accountStatusMeta(a.account_status).cls">{{ accountStatusMeta(a.account_status).label }}</span>
              <span class="load-tokens">
                <span v-for="tk in a.tokens" :key="tk.id" class="tk-badge" :class="{dead:!tk.available}" :title="tk.available?'该令牌可用':'该令牌不可用（冷却/限流）'">{{ tk.alias }}</span>
              </span>
            </label>
            <div v-if="!filteredLoadable.length && !loadLoading" class="drawer-empty">无匹配账户</div>
          </div>
          <div class="m-foot">
            <button class="btn" @click="loadOpen=false">取消</button>
            <button class="btn primary" :disabled="loadImporting" @click="commitLoadList">导入选中</button>
          </div>
        </div>
        <div v-if="loadTab==='ids'">
          <div class="hint-left">粘贴账户 ID，每行一个或用逗号/空格分隔。</div>
          <textarea v-model="loadIdText" class="input load-area" placeholder="act_1234567890&#10;9876543210&#10;..."></textarea>
          <div class="m-foot">
            <button class="btn" @click="loadOpen=false">取消</button>
            <button class="btn primary" :disabled="loadImporting" @click="commitLoadIds">导入</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="importOpen" class="overlay" :style="{ zIndex: ovZ }" @click.self="importOpen=false">
      <div class="modal">
        <div class="m-title">连接 Facebook</div>
        <div class="m-tabs"><button class="mt-btn" :class="{on:importTab==='oauth'}" @click="importTab='oauth'">OAuth 授权</button><button class="mt-btn" :class="{on:importTab==='manual'}" @click="importTab='manual'">个人令牌</button></div>
        <div v-if="importTab==='oauth'" class="m-body">
          <div v-if="!apps.length" class="hint">先在「配置 App」添加 App。</div>
          <div v-else><div v-for="a in apps" :key="a.id" class="oauth-app" @click="startOAuth(a)"><span>{{ a.name||a.app_id }}</span><span class="badge" :class="{sys:a.is_system}">{{ a.is_system?'系统':'我的' }}</span><span class="arrow">→</span></div></div>
        </div>
        <div v-if="importTab==='manual'" class="m-body">
          <div class="warn">⚠ 无法自动续期，建议用 OAuth。</div>
          <input v-model="importForm.access_token" class="input" placeholder="访问令牌（Access Token）" />
          <input v-model="importForm.alias" class="input" placeholder="名称（可选）" />
          <select v-model="importForm.token_type" class="input">
            <option value="operate">操作号（写广告 + 读 + 可暂停）</option>
            <option value="manage">管理号（读 + 可暂停，不建新广告）</option>
            <option value="user">只读号（仅查看，不可暂停）</option>
          </select>
        </div>
        <div class="m-foot"><button class="btn" @click="importOpen=false">取消</button><button v-if="importTab==='manual'" class="btn primary" :disabled="importing" @click="submitImport">导入</button></div>
      </div>
    </div>

    <div v-if="appConfigOpen" class="overlay" :style="{ zIndex: ovZ }" @click.self="appConfigOpen=false">
      <div class="modal wide">
        <div class="m-title">App 配置</div>
        <div class="app-list" v-loading="appLoading">
          <div v-if="systemApps.length" class="app-group">
            <div class="app-group-h">系统级（平台共享 · 超管管理）</div>
            <div v-for="a in systemApps" :key="a.id" class="app-row">
              <span class="app-n">{{ a.name || a.app_id }}</span>
              <span class="badge sys">系统级</span>
              <span class="app-id">{{ a.app_id }}</span>
              <div class="app-ops"><button class="mb" @click="editApp(a)">编</button><button class="mb danger" @click="deleteApp(a)">删</button></div>
            </div>
          </div>
          <div v-if="myApps.length" class="app-group">
            <div class="app-group-h">我的（本租户私有）</div>
            <div v-for="a in myApps" :key="a.id" class="app-row">
              <span class="app-n">{{ a.name || a.app_id }}</span>
              <span class="badge">我的</span>
              <span class="app-id">{{ a.app_id }}</span>
              <div class="app-ops"><button class="mb" @click="editApp(a)">编</button><button class="mb danger" @click="deleteApp(a)">删</button></div>
            </div>
          </div>
          <div v-if="!apps.length && !appLoading" class="empty">暂无 App</div>
        </div>
        <div class="app-form">
          <div class="form-h">{{ appEditing ? '编辑 App' : '添加 App' }}</div>
          <div class="af-row"><label>名称</label><input v-model="appForm.name" class="input" placeholder="可选（备注名）" /></div>
          <div class="af-row"><label>App ID</label><input v-model="appForm.app_id" class="input" placeholder="必填" /></div>
          <div class="af-row"><label>Secret</label><input v-model="appForm.app_secret" class="input" type="password" placeholder="必填" /></div>
          <label class="af-ck"><input type="checkbox" v-model="appForm.is_system" /><span>系统级 App（全租户共享，超管管理）</span></label>
          <div class="af-btns">
            <button class="btn primary" @click="saveApp">{{ appEditing ? '更新' : '添加' }}</button>
            <button v-if="appEditing" class="btn" @click="appEditing=null; appForm={app_id:'',app_secret:'',name:'',is_system:false}">取消</button>
          </div>
        </div>
        <div class="m-foot"><button class="btn" @click="appConfigOpen=false">关闭</button></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page{width:100%}
.bar{display:flex;justify-content:flex-end;margin-bottom:12px}
.bar-r{display:flex;gap:8px}
.risk-banner{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;background:rgba(255,159,10,.1);border:1px solid rgba(255,159,10,.3);border-radius:6px;font-size:12px;color:var(--warning);cursor:pointer;margin-bottom:8px}
.risk-banner:hover{background:rgba(255,159,10,.16)}
.risk-toggle{font-size:11px;flex-shrink:0}
.risk-list{border:1px solid var(--bd);border-radius:6px;margin-bottom:10px;max-height:220px;overflow-y:auto;background:var(--bg3)}
.risk-row{display:flex;align-items:center;gap:8px;padding:7px 10px;border-bottom:1px solid var(--bd);font-size:12px;color:var(--t1)}
.risk-row:last-child{border-bottom:none}
.risk-row .st-tag{margin-left:auto}
.load-row .st-tag{margin-left:auto}

.btn{padding:6px 14px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:6px;font-size:13px;cursor:pointer;white-space:nowrap;transition:.15s}
.btn:hover{background:var(--bg3)}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn.primary:disabled{opacity:.5}
.mb{padding:3px 8px;border:1px solid var(--bd);background:transparent;color:var(--t2);border-radius:4px;font-size:11px;cursor:pointer}
.mb:hover{color:var(--ac);border-color:var(--ac)}
.mb.danger:hover{color:var(--error);border-color:var(--error)}

/* 8 列：状态|名称|FB用户|账户|主页|BM|类型|操作 */
.tbl{border:1px solid var(--bd);border-radius:8px;overflow:hidden}
.row{display:grid;grid-template-columns:72px minmax(90px,120px) minmax(100px,1fr) 52px 52px 52px 64px 36px;gap:10px;align-items:center;padding:10px 14px;border-bottom:1px solid var(--bd);font-size:13px;color:var(--t1);cursor:pointer;transition:background .1s}
.row.head{color:var(--t3);font-size:10px;text-transform:uppercase;letter-spacing:.05em;background:var(--bg2);cursor:default;padding:8px 14px}
.row:not(.head):hover{background:var(--bg3)}
.row.err{opacity:.65}

.c-st{display:flex;align-items:center;gap:4px;font-size:12px}
.dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.dot.ok{background:var(--success)}.dot.warn{background:var(--warning)}.dot.err{background:var(--error)}.dot.off{background:var(--t3)}

.c-nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nm{cursor:text;display:inline-flex;align-items:center;gap:3px}
.pen{font-size:9px;color:var(--t3);opacity:0}.nm:hover .pen{opacity:1}
.inp{width:80px;padding:2px 6px;background:var(--bg3);border:1px solid var(--ac);border-radius:4px;color:var(--t1);font-size:13px}

.c-fb{display:flex;flex-direction:column;line-height:1.3;overflow:hidden}
.fbn{font-size:12px;color:var(--t1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fbi{font-size:9px;color:var(--t3);font-family:'SF Mono','Fira Code',monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

.num-h{text-align:center}
.c-num{text-align:center;font-size:13px;color:var(--t2);font-variant-numeric:tabular-nums}
.c-num.err{color:var(--error);font-weight:600;cursor:help}

.c-ty{display:flex;align-items:center;justify-content:center}
.tag{font-size:10px;padding:1px 7px;border-radius:9px;white-space:nowrap;line-height:1.5}
.tag.operate{background:rgba(10,132,255,.12);color:var(--ac)}.tag.manage{background:rgba(48,209,88,.1);color:var(--success)}.tag.user{background:var(--bg3);color:var(--t3)}

.c-op{display:flex;justify-content:center;align-items:center}
.dots-btn{border:none;background:transparent;color:var(--t3);font-size:16px;cursor:pointer;padding:0 6px;border-radius:4px;line-height:1;transition:.15s}
.dots-btn:hover{background:var(--bg3);color:var(--t1)}
.dots-btn.small{font-size:14px;padding:0 4px}

.info-sec{background:var(--bg3);border:1px solid var(--bd);border-radius:8px;padding:10px 12px;margin-bottom:14px}
.info-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px 14px}
.info-cell{display:flex;flex-direction:column;gap:2px}
.info-cell label{font-size:10px;color:var(--t3);text-transform:uppercase;letter-spacing:.03em}
.info-cell span{font-size:12px;color:var(--t1)}
.info-cell span.warn{color:var(--warning)}

.drawer-tabs{display:flex;border-bottom:1px solid var(--bd);margin-bottom:12px}
.d-tab{padding:8px 12px;border:none;background:transparent;color:var(--t3);font-size:13px;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap}
.d-tab.on{color:var(--ac);border-bottom-color:var(--ac)}
.asset-list{display:flex;flex-direction:column;gap:6px}
.asset-item{display:flex;align-items:center;gap:8px;padding:8px 10px;background:var(--bg3);border-radius:6px;border:1px solid var(--bd)}
.ai-main{display:flex;align-items:center;gap:6px;flex:1;overflow:hidden}
.ai-name{font-size:13px;color:var(--t1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ai-id{font-size:10px;color:var(--t3);font-family:'SF Mono','Fira Code',monospace;white-space:nowrap}
.ai-id.blue{color:var(--ac);cursor:pointer}
.ai-id.blue:hover{text-decoration:underline}
.ai-meta{font-size:10px;color:var(--t3);white-space:nowrap}
/* 状态 tag：账户可用/已禁用/被封 + BM 完全/基本 + 主页分类 统一规格 */
.st-tag{font-size:10px;padding:1px 7px;border-radius:9px;white-space:nowrap;line-height:1.5;flex-shrink:0}
.st-tag.ok{background:rgba(48,209,88,.1);color:var(--success)}
.st-tag.warn{background:rgba(255,159,10,.12);color:var(--warning)}
.st-tag.err{background:rgba(255,69,58,.12);color:var(--error)}
.st-tag.off{background:var(--bg2);color:var(--t3)}
.drawer-empty{text-align:center;color:var(--t3);padding:24px;font-size:13px}
.asset-err{margin-top:10px;padding:8px 10px;background:rgba(255,69,58,.06);border:1px solid rgba(255,69,58,.2);border-radius:6px;font-size:11px;color:var(--error)}

.add-row{margin-bottom:8px}
.add-btn{padding:4px 10px;border:1px dashed var(--bd);background:transparent;color:var(--t2);border-radius:6px;font-size:12px;cursor:pointer}
.add-btn:hover{color:var(--ac);border-color:var(--ac)}
.token-warn{padding:8px 10px;background:rgba(255,159,10,.08);border:1px solid rgba(255,159,10,.25);border-radius:6px;font-size:11px;color:var(--warning);line-height:1.5;margin-bottom:8px}

.perm-detail{padding:0 4px}
.sec-title{font-size:11px;color:var(--t3);margin-bottom:8px;text-transform:uppercase}
.mt{margin-top:16px}
.perm-tags{display:flex;flex-wrap:wrap;gap:4px}
.tag-mono{font-size:10px;padding:2px 6px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;color:var(--t2);font-family:'SF Mono',monospace}
.kv{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--bd);font-size:12px}
.kv label{color:var(--t3)}.kv code{font-family:'SF Mono',monospace;font-size:11px}

/* 导入账户 modal */
.load-search{margin-bottom:8px}
.load-meta{font-size:11px;color:var(--t3);margin-bottom:6px;font-variant-numeric:tabular-nums}
.load-list{max-height:340px;overflow-y:auto;display:flex;flex-direction:column;gap:2px;border:1px solid var(--bd);border-radius:6px;padding:4px;background:var(--bg3)}
.load-row{display:flex;align-items:center;gap:6px;padding:6px 6px;border-radius:4px;cursor:pointer;flex-wrap:wrap}
.load-row:hover{background:var(--bg2)}
.load-row.off{opacity:.55}
.load-row input{width:14px;height:14px;flex-shrink:0}
.load-tokens{display:inline-flex;gap:3px;flex-wrap:wrap}
.tk-badge{font-size:9px;padding:1px 5px;border-radius:4px;background:rgba(48,209,88,.1);color:var(--success);white-space:nowrap}
.tk-badge.dead{background:rgba(255,159,10,.12);color:var(--warning)}
.imp-mark{font-size:9px;padding:1px 5px;border-radius:4px;background:var(--bg2);color:var(--t3)}
.load-area{min-height:120px;resize:vertical;font-family:'SF Mono','Fira Code',monospace;font-size:12px}
.hint-left{font-size:11px;color:var(--t3);margin-bottom:8px;line-height:1.5}
.hint-left code{font-family:'SF Mono',monospace;font-size:10px;background:var(--bg3);padding:0 4px;border-radius:3px}

.overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1000;display:flex;align-items:center;justify-content:center}
.modal{background:var(--bg2);border-radius:12px;padding:20px;width:420px;max-width:90vw;box-shadow:var(--shadow-dropdown)}
.modal.wide{width:540px}
.m-title{font-size:15px;font-weight:600;color:var(--t1);margin-bottom:12px}
.m-tabs{display:flex;margin-bottom:12px;border-bottom:1px solid var(--bd)}
.mt-btn{padding:6px 14px;border:none;background:transparent;color:var(--t3);font-size:13px;cursor:pointer;border-bottom:2px solid transparent}
.mt-btn.on{color:var(--ac);border-bottom-color:var(--ac)}
.m-body{display:flex;flex-direction:column;gap:6px;margin-bottom:14px}
.input{width:100%;padding:7px 10px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:13px;font-family:inherit}
.input:focus{border-color:var(--ac);outline:none}
.warn{padding:8px;background:rgba(255,214,10,.08);border:1px solid rgba(255,214,10,.2);border-radius:6px;font-size:12px;color:var(--warning)}
.hint{text-align:center;color:var(--t3);padding:16px;font-size:13px}
.oauth-app{display:flex;align-items:center;gap:8px;padding:9px;background:var(--bg3);border-radius:6px;cursor:pointer}.oauth-app:hover{background:var(--bgh)}
.arrow{margin-left:auto;color:var(--ac)}
.m-foot{display:flex;justify-content:flex-end;gap:8px;margin-top:12px}
.badge{font-size:10px;padding:2px 7px;border-radius:8px;background:var(--acg);color:var(--ac)}.badge.sys{background:rgba(48,209,88,.12);color:var(--success)}

.app-list{margin-bottom:12px;max-height:220px;overflow-y:auto}
.app-row{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--bd)}
.app-n{font-size:13px;color:var(--t1);min-width:80px}
.app-id{font-size:10px;color:var(--t3);font-family:'SF Mono',monospace}
.app-ops{margin-left:auto;display:flex;gap:3px}
.app-form{border-top:1px solid var(--bd);padding-top:12px}
.form-h{font-size:11px;color:var(--t3);text-transform:uppercase;margin-bottom:10px;letter-spacing:.5px}
.af-row{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.af-row label{font-size:12px;color:var(--t3);width:60px;text-align:right;flex-shrink:0}
.af-row .input{flex:1;min-width:0}
.af-ck{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--t2);margin:12px 0 4px;padding-left:70px;cursor:pointer}
.af-ck input{width:14px;height:14px;cursor:pointer}
.af-btns{display:flex;gap:8px;margin-top:14px}

.empty{text-align:center;color:var(--t3);padding:24px;font-size:14px}
</style>
