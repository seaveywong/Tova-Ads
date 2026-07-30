<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { GET, POST, DELETE } from '../api'
import { ElMessage, ElMessageBox, useZIndex } from 'element-plus'
import { accountStatus } from '../composables/useStatus'
import { isSuperadminSync } from '../router'
const { t, locale } = useI18n()
const isSuper = isSuperadminSync()
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
  catch (e) { ElMessage.error(e.message || t('tokens.loadFail')) }
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
  load(); loadSummary(); loadAtRisk(); loadApps()
  // OAuth 回调处理（FB 授权后 302 回来 ?oauth=ok/fail&msg=）
  const st = route.query.oauth
  if (st === 'ok') ElMessage.success(t('tokens.oauthSuccess'))
  else if (st === 'fail') ElMessage.error(t('tokens.oauthFail', { msg: route.query.msg || t('common.fail') }))
})

const statusOrder = (t) => {
  const s = t.status, f = t.consecutive_fails || 0
  if (['expired','revoked','inactive'].includes(s)) return 0
  if (['suspended','limited'].includes(s) || f >= 3) return 1
  if (s === 'disabled') return 2
  return 3
}
const sortedTokens = computed(() => [...tokens.value].sort((a, b) => statusOrder(a) - statusOrder(b)))

const statusMeta = (tk) => {
  const s = tk.status, f = tk.consecutive_fails || 0
  if (['expired','revoked','inactive'].includes(s)) return { dot: 'err', label: t('status.tokenInvalid') }
  if (['limited'].includes(s) || f >= 3) return { dot: 'warn', label: t('status.tokenThrottled') + f }
  if (s === 'suspended') return { dot: 'warn', label: t('status.tokenPending') }
  if (s === 'disabled') return { dot: 'off', label: t('common.disable') }
  if (f > 0) return { dot: 'warn', label: t('tokens.abnormal') + f }
  return { dot: 'ok', label: t('status.tokenValid') }
}
const typeMeta = (tk) => {
  const m = {
    operate: { label: t('tokens.typeOperate'), title: t('tokens.typeOperateTitle') },
    manage:  { label: t('tokens.typeManage'), title: t('tokens.typeManageTitle') },
    user:    { label: t('tokens.typeUser'), title: t('tokens.typeUserTitle') },
  }
  return m[tk] || m.user
}
const sourceLabel = (s) => ({ manual: t('tokens.sourceManual'), oauth: 'OAuth' }[s] || '—')
const fmtTime = (s) => {
  if (!s || s === 'None') return '—'
  const d = new Date(s.endsWith('Z') ? s : s.replace(' ', 'T') + 'Z')
  if (isNaN(d)) return '—'
  const diff = (Date.now() - d.getTime()) / 60000
  if (diff < 1) return t('tokens.justNow')
  if (diff < 60) return t('tokens.minutesAgo', { n: Math.floor(diff) })
  if (diff < 1440) return t('tokens.hoursAgo', { n: Math.floor(diff/60) })
  return d.toLocaleDateString(locale.value === 'en' ? 'en-US' : 'zh-CN')
}
const permCount = (p) => (!p || !p.scopes) ? 0 : p.scopes.length

const accountStatusMeta = (s) => accountStatus(s)
const scopeLabel = (s) => ({
  ads_management: t('tokens.scopeAdsManagement'), ads_read: t('tokens.scopeAdsRead'),
  pages_show_list: t('tokens.scopePagesShowList'), pages_messaging: t('tokens.scopePagesMessaging'),
  pages_manage_metadata: t('tokens.scopePagesManageMetadata'), pages_read_engagement: t('tokens.scopePagesReadEngagement'),
  pages_manage_posts: t('tokens.scopePagesManagePosts'), pages_read_user_content: t('tokens.scopePagesReadUserContent'),
  pages_manage_engagement: t('tokens.scopePagesManageEngagement'), pages_events: t('tokens.scopePagesEvents'),
  business_management: t('tokens.scopeBusinessManagement'), read_insights: t('tokens.scopeReadInsights'),
  instagram_basic: t('tokens.scopeInstagramBasic'), instagram_manage_insights: t('tokens.scopeInstagramManageInsights'),
  instagram_manage_comments: t('tokens.scopeInstagramManageComments'),
  public_profile: t('tokens.scopePublicProfile'), email: t('tokens.scopeEmail'),
  attribution_read: t('tokens.scopeAttributionRead'), catalog_management: t('tokens.scopeCatalogManagement'),
  whatsapp_business_management: t('tokens.scopeWhatsappBusinessManagement'),
  leads_retrieval: t('tokens.scopeLeadsRetrieval'), pages_manage_cta: t('tokens.scopePagesManageCta'),
}[s]) || s

const copyId = async (id) => {
  if (!id) return
  try { await navigator.clipboard.writeText(id); ElMessage.success(t('tokens.copiedId', { id })) }
  catch { ElMessage.warning(t('tokens.copyFail')) }
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

const refreshAllLabel = ref(t('tokens.refreshAll'))
const refreshAll = async () => {
  let ok = 0, fail = 0, done = 0
  const total = tokens.value.length
  for (const tk of tokens.value) {
    refreshAllLabel.value = t('tokens.checkingProgress', { done, total })
    try { const r = await POST(`/fb/credentials/${tk.id}/check`, {}); r.now_valid ? ok++ : fail++ }
    catch { fail++ }
    done++
  }
  refreshAllLabel.value = t('tokens.refreshAll')
  await load()
  await loadAtRisk()
  // 刷新令牌=状态+资产都新：清资产缓存（下次开抽屉重拉最新主页/账户/BM）、刷新汇总计数、开着的抽屉也重拉
  assetCache.value = {}
  await loadSummary()
  if (drawerOpen.value && drawerToken.value) await loadDrawerAssets(drawerToken.value)
  ElMessage[fail ? 'warning' : 'success'](t('tokens.refreshAllResult', { ok, fail }) + (fail ? t('tokens.refreshAllResultWarn') : ''))
}
const refreshAccounts = async (tk) => {
  try { ElMessage.info(t('tokens.refreshing')); const r = await POST(`/fb/credentials/${tk.id}/refresh-accounts`, {}); delete assetCache.value[tk.id]; await loadDrawerAssets(tk); ElMessage.success(t('tokens.accountsRefreshed', { n: r.updated||0 })) }
  catch (e) { ElMessage.error(t('tokens.refreshFail') + (e.message||'')) }
}
const handleAction = (cmd, tk) => {
  if (cmd === 'check') checkToken(tk)
  else if (cmd === 'refresh') refreshAccounts(tk)
  else if (cmd === 'delete') deleteToken(tk)
  else if (cmd === 'update_token') updateToken(tk)
}
const handleAccountCmd = async (cmd, a) => {
  if (cmd === 'unmanage') {
    try {
      await ElMessageBox.confirm(t('tokens.unmanageConfirm', { name: a.name }), t('common.confirm'), {type:'warning'})
      await DELETE(`/fb/accounts/${a.account_id}`)
      ElMessage.success(t('tokens.unmanaged'))
      if (drawerToken.value) await loadDrawerAssets(drawerToken.value)
      await Promise.all([load(), loadSummary(), loadAtRisk()])
    } catch {}
  }
}

const startEdit = (tk) => { editId.value = tk.id; editAlias.value = tk.alias || '' }
const saveEdit = async (tk) => {
  if (editId.value === null) return
  const id = editId.value, val = editAlias.value.trim()
  editId.value = null
  if (val === (tk.alias || '')) return
  try { await POST(`/fb/credentials/${id}/rename`, { alias: val }); tk.alias = val; ElMessage.success(t('tokens.updated')) }
  catch { ElMessage.error(t('tokens.updateFail')) }
}

const loadDrawerAssets = async (tk) => {
  assetLoading.value = true
  try {
    const data = await GET(`/fb/credentials/${tk.id}/assets`)
    assetCache.value[tk.id] = { accounts: data.accounts || [], pages: data.pages || [],
                               businesses: data.businesses || [], error: data.error || null }
    if (data.error) ElMessage.warning(t('tokens.assetReadPartial', { msg: data.error }))
  } catch (e) { assetCache.value[tk.id] = { accounts: [], pages: [], businesses: [], error: e.message || t('tokens.assetReadFail') } }
  assetLoading.value = false
}
const openDrawer = async (tk) => {
  drawerToken.value = tk
  drawerTab.value = 'accounts'
  drawerOpen.value = true
  if (!assetCache.value[tk.id]) await loadDrawerAssets(tk)
}
const onTabChange = () => {}
const drawerTitle = computed(() => {
  if (!drawerToken.value) return ''
  return `${drawerToken.value.fb_user_name || t('tokens.unknown')} · ${t('tokens.userAssets')}`
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
  catch (e) { ElMessage.error(t('tokens.fetchFail')+(e.message||'')); loadableAccounts.value = [] }
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
    const parts = [t('tokens.importedCount', { n: r.count })]
    if (r.skipped_existing) parts.push(t('tokens.skippedExisting', { n: r.skipped_existing }))
    if (r.not_found && r.not_found.length) parts.push(t('tokens.notFound', { n: r.not_found.length }))
    ElMessage.success(parts.join(' · '))
    loadOpen.value = false
    await Promise.all([load(), loadSummary(), loadAtRisk()])
    if (drawerToken.value) await loadDrawerAssets(drawerToken.value)
  } catch (e) { ElMessage.error(t('tokens.importFail')+(e.message||'')) }
  loadImporting.value = false
}
const commitLoadList = async () => {
  const impSet = new Set(loadableAccounts.value.filter(a => a.imported).map(a => a.account_id))
  const ids = Object.keys(loadSelected.value).filter(k => loadSelected.value[k] && !impSet.has(k))
  if (!ids.length) { ElMessage.warning(t('tokens.selectUnimported')); return }
  await doImport(ids)
}
const commitLoadIds = async () => {
  const ids = loadIdText.value.split(/[\s,]+/).map(s => s.trim()).filter(Boolean)
  if (!ids.length) { ElMessage.warning(t('tokens.pasteIds')); return }
  await doImport(ids)
}

// App
const loadApps = async () => { appLoading.value = true; try { apps.value = await GET('/fb/apps') } catch { apps.value = [] }; appLoading.value = false }
const openAppConfig = async () => { popOverlay(); appConfigOpen.value = true; await loadApps() }
const saveApp = async () => {
  if (!appForm.value.app_id.trim() || !appForm.value.app_secret.trim()) { ElMessage.warning(t('tokens.fillAppIdSecret')); return }
  try {
    if (appEditing.value) await POST(`/fb/apps/${appEditing.value}`, { ...appForm.value })
    else await POST('/fb/apps', { ...appForm.value })
    ElMessage.success(t('common.savedOk')); appForm.value = { app_id:'', app_secret:'', name:'', is_system:false }; appEditing.value = null; await loadApps()
  } catch { ElMessage.error(t('common.fail')) }
}
const editApp = (a) => { appEditing.value = a.id; appForm.value = { app_id: a.app_id, app_secret: '', name: a.name||'', is_system: a.is_system } }
const deleteApp = async (a) => { try { await ElMessageBox.confirm(t('tokens.deleteAppConfirm', { name: a.name||a.app_id }), t('common.confirm'), {type:'warning'}); await DELETE(`/fb/apps/${a.id}`); ElMessage.success(t('tokens.deleted')); await loadApps() } catch {} }
const systemApps = computed(() => apps.value.filter(a => a.is_system))
const myApps = computed(() => apps.value.filter(a => !a.is_system))
const _oauthUrl = async (a) => {
  try { const r = await GET(`/fb/oauth/start?app_pk=${a.id}`); return r.url || '' }
  catch (e) { ElMessage.error(t('tokens.startOAuthFail') + (e.message || '')); return '' }
}
const startOAuth = async (a) => {  // → 在本浏览器打开（当前页跳转 FB 授权）
  const url = await _oauthUrl(a)
  if (url) window.location.href = url
}
const copyOAuth = async (a) => {  // 复制授权链接（到其他设备/已登录 FB 的浏览器打开）
  const url = await _oauthUrl(a)
  if (!url) return
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success(t('tokens.oauthLinkCopied'))
  } catch {
    ElMessageBox.alert(url, t('tokens.oauthUrlTitle'), { confirmButtonText: t('common.close') }).catch(() => {})
  }
}

const submitImport = async () => {
  if (!importForm.value.access_token.trim()) return ElMessage.warning(t('tokens.fillToken'))
  importing.value = true
  try { await POST('/fb/credentials', { access_token: importForm.value.access_token.trim(), alias: importForm.value.alias.trim(), token_type: importForm.value.token_type }); ElMessage.success(t('tokens.importedOk')); importOpen.value = false; importForm.value = { access_token:'', alias:'', token_type:'operate' }; await Promise.all([load(), loadSummary(), loadAtRisk()]) }
  catch (e) { ElMessage.error(t('tokens.importFail')+(e.message||'')) }
  importing.value = false
}
const updateToken = async (tk) => {
  try {
    const { value } = await ElMessageBox.prompt(t('tokens.updateTokenPrompt'), t('tokens.updateTokenTitle', { name: tk.alias || tk.fb_user_name }), {
      confirmButtonText: t('tokens.updateBtn'), cancelButtonText: t('common.cancel'), inputType: 'password', inputPlaceholder: 'EAA...',
      inputValidator: (v) => v && v.trim().length > 20 || t('tokens.tokenTooShort'),
    })
    const r = await POST(`/fb/credentials/${tk.id}/update-token`, { access_token: value.trim() })
    ElMessage.success(t('tokens.tokenUpdated', { name: r.fb_user_name }))
    await load()
  } catch (e) { if (e === 'cancel') return; ElMessage.error(e.message || t('tokens.updateFail')) }
}
const checkToken = async (tk) => {
  try { ElMessage.info(t('tokens.checking')); const r = await POST(`/fb/credentials/${tk.id}/check`, {}); r.now_valid ? ElMessage.success(r.detail||t('status.tokenValid')) : ElMessage.warning(r.detail||t('tokens.abnormal0')) }
  catch { ElMessage.error(t('tokens.checkFail')) }
  delete assetCache.value[tk.id]; await load(); await loadAtRisk()
}
const deleteToken = async (tk) => {
  try { await ElMessageBox.confirm(t('tokens.deleteTokenConfirm', { name: tk.alias||tk.fb_user_name||tk.id }), t('common.confirm'), {type:'warning'}); await DELETE(`/fb/credentials/${tk.id}`); ElMessage.success(t('tokens.deleted')); await Promise.all([load(), loadSummary(), loadAtRisk()]) }
  catch (e) { if (e !== 'cancel') ElMessage.error(e.message || t('common.opFail')) }
}
</script>

<template>
  <div class="page">
    <div class="bar">
      <div class="bar-r">
        <button class="btn primary" @click="importOpen = true">{{ t('tokens.connectFacebook') }}</button>
        <button class="btn" @click="openLoad">{{ t('tokens.importAccounts') }}</button>
        <button class="btn" @click="openAppConfig">{{ t('tokens.configApp') }}</button>
        <button class="btn" @click="refreshAll">{{ refreshAllLabel }}</button>
      </div>
    </div>

    <div v-if="atRiskAccounts.length" class="risk-banner" @click="atRiskOpen = !atRiskOpen">
      <span>⚠ {{ t('tokens.atRiskSummary', { n: atRiskAccounts.length }) }}</span>
      <span class="risk-toggle">{{ atRiskOpen ? t('tokens.collapse') : t('tokens.viewDetail') }}</span>
    </div>
    <div v-if="atRiskOpen && atRiskAccounts.length" class="risk-list">
      <div v-for="a in atRiskAccounts" :key="a.act_id" class="risk-row">
        <span class="ai-name">{{ a.name }}</span>
        <span class="ai-id blue" @click.stop="copyId(a.act_id)">{{ a.act_id }}</span>
        <span class="ai-meta">{{ a.bound_alias ? t('tokens.prevBound', { name: a.bound_alias }) : t('tokens.unboundToken') }}</span>
        <span class="st-tag" :class="a.bound_status==='unbound'?'off':'err'">{{ a.bound_status==='unbound'?t('tokens.unbound'):a.bound_status }}</span>
      </div>
    </div>

    <div class="tbl" v-loading="loading">
      <div class="row head">
        <span>{{ t('common.status') }}</span><span>{{ t('common.name') }}</span><span>{{ t('tokens.fbUser') }}</span>
        <span class="num-h">{{ t('tokens.colAccounts') }}</span><span class="num-h">{{ t('tokens.colPages') }}</span><span class="num-h">BM</span>
        <span>{{ t('tokens.type') }}</span><span></span>
      </div>
      <div v-for="tk in sortedTokens" :key="tk.id" class="row" :class="statusMeta(tk).dot" @click="openDrawer(tk)">
        <span class="c-st"><span class="dot" :class="statusMeta(tk).dot"></span>{{ statusMeta(tk).label }}</span>
        <span class="c-nm" @click.stop>
          <input v-if="editId===tk.id" v-model="editAlias" class="inp" @keyup.enter="saveEdit(tk)" @blur="saveEdit(tk)" />
          <span v-else class="nm" @click="startEdit(tk)">{{ tk.alias || t('tokens.unnamed') }}<span class="pen">✎</span></span>
        </span>
        <span class="c-fb">
          <span class="fbn">{{ tk.fb_user_name || '—' }}</span>
          <span class="fbi" :title="tk.fb_user_id">{{ tk.fb_user_id?.slice(-10) || '—' }}</span>
        </span>
        <span class="c-num" :class="{err:summaryError(tk)}" :title="summaryError(tk)||t('tokens.accountsCountTip')">{{ summaryError(tk) ? '!' : countOf(tk,'accounts') }}</span>
        <span class="c-num">{{ countOf(tk,'pages') }}</span>
        <span class="c-num">{{ countOf(tk,'businesses') }}</span>
        <span class="c-ty">
          <span class="tag" :class="tk.token_type" :title="typeMeta(tk.token_type).title">{{ typeMeta(tk.token_type).label }}</span>
          <span v-if="(tk.account_count||0) > 0" class="tag rotate" :title="t('tokens.rotatePoolTip')">↻</span>
        </span>
        <span class="c-op" @click.stop>
          <el-dropdown trigger="click" @command="cmd => handleAction(cmd, tk)">
            <button class="dots-btn" @click.stop>⋯</button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="check">{{ t('tokens.checkValidity') }}</el-dropdown-item>
                <el-dropdown-item command="update_token">{{ t('tokens.updateKey') }}</el-dropdown-item>
                <el-dropdown-item command="refresh">{{ t('tokens.refreshAccounts') }}</el-dropdown-item>
                <el-dropdown-item command="delete" divided>{{ t('tokens.deleteToken') }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </span>
      </div>
      <div v-if="!tokens.length && !loading" class="empty empty-cta">
        <div class="empty-title">{{ t('tokens.emptyTitle') }}</div>
        <div class="empty-step">{{ t('tokens.emptyStep') }}</div>
      </div>
    </div>

    <el-drawer v-model="drawerOpen" :title="drawerTitle" direction="rtl" size="480px" :destroy-on-close="true">
      <div v-if="drawerToken" class="info-sec">
        <div class="info-grid">
          <div class="info-cell"><label>{{ t('tokens.tokenName') }}</label><span>{{ drawerToken.alias || t('tokens.unnamed') }}</span></div>
          <div class="info-cell"><label>{{ t('tokens.typeSource') }}</label><span :title="typeMeta(drawerToken.token_type).title">{{ typeMeta(drawerToken.token_type).label }} · {{ sourceLabel(drawerToken.token_source) }}</span></div>
          <div class="info-cell"><label>{{ t('tokens.lastVerified') }}</label><span>{{ fmtTime(drawerToken.last_verified_at) }}</span></div>
          <div class="info-cell"><label>{{ t('tokens.consecutiveFails') }}</label><span :class="{warn:(drawerToken.consecutive_fails||0)>=1}">{{ drawerToken.consecutive_fails || 0 }} {{ t('tokens.times') }}</span></div>
          <div class="info-cell"><label>{{ t('tokens.linkedAccounts') }}</label><span>{{ drawerToken.account_count ?? 0 }} {{ t('tokens.importedUnit') }}</span></div>
          <div class="info-cell"><label>{{ t('tokens.permCount') }}</label><span>{{ permCount(drawerToken.permission_snapshot) }} {{ t('tokens.items') }}</span></div>
        </div>
      </div>

      <div class="drawer-tabs">
        <button v-for="tab in ['accounts','pages','businesses','perm']" :key="tab" class="d-tab" :class="{on:drawerTab===tab}" @click="drawerTab=tab;onTabChange()">
          {{ {accounts:t('tokens.tabAccounts'),pages:t('tokens.tabPages'),businesses:'BM',perm:t('tokens.tabPerm')}[tab] }}
        </button>
      </div>
      <div v-loading="assetLoading">
        <div v-if="drawerTab==='accounts'">
          <div v-if="drawerToken && statusMeta(drawerToken).dot !== 'ok'" class="token-warn">
            ⚠ {{ t('tokens.tokenWarn', { status: statusMeta(drawerToken).label }) }}
          </div>
          <div class="add-row"><button class="add-btn" @click="openLoad">+ {{ t('tokens.addAccount') }}</button></div>
          <div v-if="drawerAccounts.length" class="asset-list">
            <div v-for="a in drawerAccounts" :key="a.account_id" class="asset-item">
              <div class="ai-main">
                <span class="ai-name">{{ a.name }}</span>
                <span class="ai-id blue" :title="t('tokens.clickToCopy')" @click.stop="copyId(a.account_id)">{{ a.account_id }}</span>
                <span class="ai-meta" v-if="a.balance_label">{{ t('status.accActive') }} · {{ a.balance_label }}</span>
              </div>
              <span class="st-tag" :class="accountStatusMeta(a.account_status).cls">{{ accountStatusMeta(a.account_status).label }}</span>
              <el-dropdown trigger="click" @command="cmd => handleAccountCmd(cmd, a)" @click.stop>
                <button class="dots-btn small" @click.stop>⋯</button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item disabled>{{ t('tokens.publishAdsSoon') }}</el-dropdown-item>
                    <el-dropdown-item disabled>{{ t('tokens.viewInsightsSoon') }}</el-dropdown-item>
                    <el-dropdown-item command="unmanage" divided>{{ t('tokens.unmanage') }}</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
          <div v-else-if="!assetLoading" class="drawer-empty">{{ t('tokens.noImportedAccounts') }}</div>
        </div>
        <div v-if="drawerTab==='pages'">
          <div v-if="drawerPages.length" class="asset-list">
            <div v-for="p in drawerPages" :key="p.id" class="asset-item">
              <div class="ai-main">
                <span class="ai-name">{{ p.name }}</span>
                <span class="ai-id blue" :title="t('tokens.clickToCopy')" @click.stop="copyId(p.id)">{{ p.id }}</span>
                <span class="ai-meta" v-if="p.category">{{ p.category }}</span>
                <span class="ai-meta" v-if="p.fan_count">{{ p.fan_count }} {{ t('tokens.fans') }}</span>
              </div>
              <span class="st-tag ok">{{ t('status.accActive') }}</span>
              <el-dropdown trigger="click" @click.stop>
                <button class="dots-btn small" @click.stop>⋯</button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item disabled>{{ t('tokens.renameSoon') }}</el-dropdown-item>
                    <el-dropdown-item disabled>{{ t('tokens.changeTypeSoon') }}</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
          <div v-else-if="!assetLoading" class="drawer-empty">{{ t('tokens.noPages') }}</div>
        </div>
        <div v-if="drawerTab==='businesses'">
          <div v-if="drawerBusinesses.length" class="asset-list">
            <div v-for="b in drawerBusinesses" :key="b.id" class="asset-item">
              <div class="ai-main">
                <span class="ai-name">{{ b.name }}</span>
                <span class="ai-id blue" :title="t('tokens.clickToCopy')" @click.stop="copyId(b.id)">{{ b.id }}</span>
              </div>
              <span class="st-tag" :class="b.role==='完全'?'ok':'off'">{{ b.role }}</span>
              <el-dropdown trigger="click" @click.stop>
                <button class="dots-btn small" @click.stop>⋯</button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item disabled>{{ t('tokens.viewMembersSoon') }}</el-dropdown-item>
                    <el-dropdown-item disabled>{{ t('tokens.manageAssetsSoon') }}</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
          <div v-else-if="!assetLoading" class="drawer-empty">{{ t('tokens.noBM') }}</div>
        </div>
        <div v-if="drawerTab==='perm' && drawerToken" class="perm-detail">
          <div class="sec-title">{{ t('tokens.permDetailTitle', { n: permCount(drawerToken.permission_snapshot) }) }}</div>
          <div class="perm-tags"><span v-for="s in (drawerToken.permission_snapshot?.scopes||[])" :key="s" class="tag-mono" :title="s">{{ scopeLabel(s) }}</span></div>
          <div class="sec-title mt">{{ t('common.detail') }}</div>
          <div class="kv"><label>App ID</label><code>{{ drawerToken.permission_snapshot?.app_id || '—' }}</code></div>
          <div class="kv"><label>{{ t('tokens.userId') }}</label><code>{{ drawerToken.fb_user_id || '—' }}</code></div>
          <div class="kv"><label>{{ t('common.status') }}</label><span>{{ statusMeta(drawerToken).label }}</span></div>
        </div>
      </div>
      <div v-if="drawerToken && assetCache[drawerToken.id]?.error" class="asset-err">{{ t('tokens.assetReadPartialShort') }}{{ assetCache[drawerToken.id].error }}</div>
    </el-drawer>

    <div v-if="loadOpen" class="overlay" :style="{ zIndex: ovZ }" @click.self="loadOpen=false">
      <div class="modal wide">
        <div class="m-title">{{ t('tokens.importAccounts') }}</div>
        <div class="m-tabs">
          <button class="mt-btn" :class="{on:loadTab==='list'}" @click="loadTab='list'">{{ t('tokens.tabChecklist') }}</button>
          <button class="mt-btn" :class="{on:loadTab==='ids'}" @click="loadTab='ids'">{{ t('tokens.tabIdImport') }}</button>
        </div>
        <div v-if="loadTab==='list'">
          <input v-model="loadSearch" class="input load-search" :placeholder="t('tokens.searchAccountPlaceholder')" />
          <div class="load-meta">{{ t('tokens.loadableMeta', { total: loadableAccounts.length, selected: loadSelectedCount }) }}</div>
          <div v-loading="loadLoading" class="load-list">
            <label v-for="a in filteredLoadable" :key="a.account_id" class="load-row" :class="{off:a.imported}">
              <input type="checkbox" :checked="!!loadSelected[a.account_id]" :disabled="a.imported" @change="loadSelected[a.account_id] = $event.target.checked" />
              <span class="ai-name">{{ a.name }}</span>
              <span class="ai-id blue" @click.stop="copyId(a.account_id)">{{ a.account_id }}</span>
              <span v-if="a.imported" class="imp-mark">{{ t('tokens.importedMark') }}</span>
              <span class="st-tag" :class="accountStatusMeta(a.account_status).cls">{{ accountStatusMeta(a.account_status).label }}</span>
              <span class="load-tokens">
                <span v-for="tk in a.tokens" :key="tk.id" class="tk-badge" :class="{dead:!tk.available}" :title="tk.available?t('tokens.tokenAvailable'):t('tokens.tokenUnavailable')">{{ tk.alias }}</span>
              </span>
            </label>
            <div v-if="!filteredLoadable.length && !loadLoading" class="drawer-empty">{{ t('tokens.noMatchAccounts') }}</div>
          </div>
          <div class="m-foot">
            <button class="btn" @click="loadOpen=false">{{ t('common.cancel') }}</button>
            <button class="btn primary" :disabled="loadImporting" @click="commitLoadList">{{ t('tokens.importSelected') }}</button>
          </div>
        </div>
        <div v-if="loadTab==='ids'">
          <div class="hint-left">{{ t('tokens.idImportHint') }}</div>
          <textarea v-model="loadIdText" class="input load-area" placeholder="act_1234567890&#10;9876543210&#10;..."></textarea>
          <div class="m-foot">
            <button class="btn" @click="loadOpen=false">{{ t('common.cancel') }}</button>
            <button class="btn primary" :disabled="loadImporting" @click="commitLoadIds">{{ t('common.import') }}</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="importOpen" class="overlay" :style="{ zIndex: ovZ }" @click.self="importOpen=false">
      <div class="modal">
        <div class="m-title">{{ t('tokens.connectFacebook') }}</div>
        <div class="m-tabs"><button class="mt-btn" :class="{on:importTab==='oauth'}" @click="importTab='oauth'">{{ t('tokens.tabOauth') }}</button><button class="mt-btn" :class="{on:importTab==='manual'}" @click="importTab='manual'">{{ t('tokens.tabManual') }}</button></div>
        <div v-if="importTab==='oauth'" class="m-body">
          <div v-if="!apps.length" class="hint">{{ t('tokens.oauthHint') }}</div>
          <div v-else>
            <div class="oauth-step">{{ t('tokens.oauthPickHint') }}</div>
            <div v-for="a in apps" :key="a.id" class="oauth-app">
              <span class="oa-name">{{ a.name||a.app_id }}</span>
              <span class="badge" :class="{sys:a.is_system}">{{ a.is_system?t('tokens.systemApp'):t('tokens.myApp') }}</span>
              <span class="oa-actions">
                <button class="oa-btn ghost" @click="copyOAuth(a)">{{ t('tokens.copyOAuthUrl') }}</button>
                <button class="oa-btn" @click="startOAuth(a)">{{ t('tokens.openInBrowser') }} →</button>
              </span>
            </div>
          </div>
        </div>
        <div v-if="importTab==='manual'" class="m-body">
          <div class="warn">⚠ {{ t('tokens.manualWarn') }}</div>
          <input v-model="importForm.access_token" class="input" :placeholder="t('tokens.accessTokenPlaceholder')" />
          <input v-model="importForm.alias" class="input" :placeholder="t('tokens.aliasOptional')" />
          <select v-model="importForm.token_type" class="input">
            <option value="operate">{{ t('tokens.optOperate') }}</option>
            <option value="manage">{{ t('tokens.optManage') }}</option>
            <option value="user">{{ t('tokens.optUser') }}</option>
          </select>
        </div>
        <div class="m-foot"><button class="btn" @click="importOpen=false">{{ t('common.cancel') }}</button><button v-if="importTab==='manual'" class="btn primary" :disabled="importing" @click="submitImport">{{ t('common.import') }}</button></div>
      </div>
    </div>

    <div v-if="appConfigOpen" class="overlay" :style="{ zIndex: ovZ }" @click.self="appConfigOpen=false">
      <div class="modal wide">
        <div class="m-title">{{ t('tokens.appConfigTitle') }}</div>
        <div class="app-list" v-loading="appLoading">
          <div v-for="a in apps" :key="a.id" class="app-row">
            <span class="app-n">{{ a.name || a.app_id }}</span>
            <span v-if="a.is_system" class="badge sys">{{ t('tokens.systemLevel') }}</span>
            <span class="app-id">{{ a.app_id }}</span>
            <div class="app-ops"><button class="mb" @click="editApp(a)">{{ t('tokens.editShort') }}</button><button class="mb danger" @click="deleteApp(a)">{{ t('tokens.deleteShort') }}</button></div>
          </div>
          <div v-if="!apps.length && !appLoading" class="empty">{{ t('tokens.noApps') }}</div>
        </div>
        <div class="app-form">
          <div class="form-h">
            {{ appEditing ? t('tokens.editApp') : (appForm.is_system ? t('tokens.addSystemApp') : t('tokens.addApp')) }}
            <a v-if="isSuper && !appEditing" class="sys-toggle" @click="appForm.is_system = !appForm.is_system">
              {{ appForm.is_system ? t('tokens.backToNormalApp') : t('tokens.addSystemAppArrow') }}
            </a>
          </div>
          <div class="af-row"><label>{{ t('common.name') }}</label><input v-model="appForm.name" class="input" :placeholder="t('tokens.appNameOptional')" /></div>
          <div class="af-row"><label>App ID</label><input v-model="appForm.app_id" class="input" :placeholder="t('common.required')" /></div>
          <div class="af-row"><label>Secret</label><input v-model="appForm.app_secret" class="input" type="password" :placeholder="t('common.required')" /></div>
        </div>
        <div class="m-foot">
          <button v-if="appEditing" class="btn" @click="appEditing=null; appForm={app_id:'',app_secret:'',name:'',is_system:false}">{{ t('common.cancel') }}</button>
          <button class="btn primary" @click="saveApp">{{ appEditing ? t('tokens.updateBtn') : t('common.add') }}</button>
          <button class="btn" @click="appConfigOpen=false">{{ t('common.close') }}</button>
        </div>
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
.tbl{border:1px solid var(--bd);border-radius:8px;overflow-x:auto}
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
.tag.rotate{background:rgba(48,209,88,.1);color:var(--success);font-size:11px;padding:1px 5px}

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
.oauth-step{font-size:12px;color:var(--t3);line-height:1.6;padding:2px 2px 10px;text-align:left}
.oauth-app{display:flex;align-items:center;gap:8px;padding:9px;background:var(--bg3);border-radius:6px}.oauth-app:hover{background:var(--bgh)}
.oa-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;color:var(--t1)}
.oa-actions{display:flex;gap:6px;margin-left:auto;flex-shrink:0}
.oa-btn{padding:4px 10px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:5px;font-size:12px;cursor:pointer;font-family:inherit;white-space:nowrap}
.oa-btn:hover{border-color:var(--ac);color:var(--ac)}
.oa-btn.ghost{background:transparent;color:var(--t3)}
.m-foot{display:flex;justify-content:flex-end;gap:8px;margin-top:12px}
.badge{font-size:10px;padding:2px 7px;border-radius:8px;background:var(--acg);color:var(--ac)}.badge.sys{background:rgba(48,209,88,.12);color:var(--success)}

.app-list{margin-bottom:12px;max-height:220px;overflow-y:auto}
.app-row{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--bd)}
.app-row:last-child{border-bottom:none}
.app-n{font-size:13px;color:var(--t1);min-width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.app-id{font-size:10px;color:var(--t3);font-family:'SF Mono',monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1 1 auto;min-width:0}
.app-ops{margin-left:auto;display:flex;gap:3px}
.app-form{border-top:1px solid var(--bd);padding-top:12px}
.form-h{font-size:11px;color:var(--t3);text-transform:uppercase;margin-bottom:10px;letter-spacing:.5px;display:flex;align-items:center;justify-content:space-between}
.sys-toggle{font-size:11px;text-transform:none;letter-spacing:0;color:var(--ac);cursor:pointer;text-decoration:underline}
.af-row{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.af-row label{font-size:12px;color:var(--t3);width:70px;text-align:right;flex-shrink:0}
.af-row .input{flex:1;min-width:0}
.af-ck{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--t2);margin:12px 0 4px;padding-left:70px;cursor:pointer}
.af-ck input{width:14px;height:14px;cursor:pointer}
.af-btns{display:flex;gap:8px;margin-top:14px}

.empty{text-align:center;color:var(--t3);padding:24px;font-size:14px}
.empty-cta{padding:50px 30px}
.empty-title{font-size:15px;color:var(--t2);font-weight:600;margin-bottom:10px}
.empty-step{font-size:13px;color:var(--t3);line-height:1.7}
</style>
