<script setup>
import { ref, computed, onMounted, onUnmounted, h, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { GET, POST, PATCH, DELETE, downloadFile } from '../api'
import { useLatest } from '../composables/useLatest'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fbAdStatus, ttAdStatus } from '../composables/useStatus'
import { DATE_PRESETS, presetRange } from '../composables/useDateRange'
import { usePlatform } from '../composables/usePlatform'
import { useI18n } from 'vue-i18n'
import DatePresetBar from '../components/DatePresetBar.vue'
import { entityKey, entityContext, searchMatches, compareRows, columnsFor, normalizeViewPreferences, fbResult } from '../composables/adManagerView'

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const accounts = ref([])
const selectedActs = ref([])
const datePreset = ref('today')
const showCustom = ref(false)
const customFrom = ref('')
const customTo = ref('')
const tab = ref('campaign')
const data = ref({ campaigns: [], adsets: [], ads: [], currency: 'USD' })
// 每账户读令牌可用性（/ads/list 透传）：false=数据源已断（无可用令牌），该账户所有状态是
// cache 最后快照而非实时——页头横幅+行内「快照」标，别让"投放中"误导（令牌失效后 cache 停更）
const tokenStatus = ref({})
const deadAccounts = computed(() => Object.entries(tokenStatus.value).filter(([, v]) => v === false).map(([k]) => k))
const accDead = (a) => tokenStatus.value[a?.act_id] === false
// 脱管=有账户行但令牌没了/失效（管不了但账户本身还活着）
const accUnmanaged = (a) => {
  const acc = accounts.value.find(x => x.act_id === (a?.act_id || a))
  return acc?.no_token === true || acc?.is_managed === false
}
// 被禁=FB 侧账户本身被禁（account_status!=1 或有 disable_reason）
const accBanned = (a) => {
  const acc = accounts.value.find(x => x.act_id === (a?.act_id || a))
  return acc && (acc.account_status === 2 || acc.account_status === 3 || !!acc.disable_reason)
}
// 统一状态标签：脱管/被禁/正常
const accStateTag = (a) => {
  if (accBanned(a)) return { cls: 'banned', label: t('adm.accBanned') }
  if (accDead(a) || accUnmanaged(a)) return { cls: 'unmanaged', label: t('adm.accUnmanaged') }
  return null
}
// 组行悬停显示所属系列名（非下钻视图下组的归属上下文；下钻时 drill-tag 已标）
// 批AI：层级状态联动——FB Ads Manager 语义：广告全停 ⇒ 所属组显示「已暂停」；组全停 ⇒ 所属系列显示「已暂停」。
// 只做「全停→父层暂停」单向推导（父 ACTIVE 但子全停=实质停投）；父已停/异常态原样显示（不覆盖 FB 真实态）。
const childPausedMap = computed(() => {
  // 批AJ 修正：广告对象直存集合（曾存对象却按 id find → 恒不匹配）；campaign 推导写 campAllPaused（曾误写 adsetAllPaused）
  const adsByAdset = {}
  for (const a of (data.value.ads || [])) {
    const k = String(_idOf(a.adset_id))
    ;(adsByAdset[k] = adsByAdset[k] || []).push(a)
  }
  const adsetsByCamp = {}
  for (const s of (data.value.adsets || [])) {
    const k = String(_idOf(s.campaign_id))
    ;(adsetsByCamp[k] = adsetsByCamp[k] || []).push(s)
  }
  const adsetAllPaused = {}, campAllPaused = {}
  for (const [sid, kids] of Object.entries(adsByAdset))
    adsetAllPaused[sid] = kids.length > 0 && kids.every(a => (a.effective_status || '').includes('PAUSED'))
  // 批BG：系列层判「全停」要用电组的生效态（组原生 status 不随广告停——广告全停的组
  // 原生仍 ACTIVE，读原生会导致广告全停后系列仍显示投放中）
  for (const [cid, kids] of Object.entries(adsetsByCamp))
    campAllPaused[cid] = kids.length > 0 && kids.every(s =>
      (s.effective_status || '').includes('PAUSED') || adsetAllPaused[String(_idOf(s.id))])
  // 批BU（用户点名）：系列/组「有没有真正在投的广告」——容器开着但零生效广告 ≠ 投放中
  const adsByCamp = {}
  for (const a of (data.value.ads || [])) {
    const k = String(_idOf(a.campaign_id))
    ;(adsByCamp[k] = adsByCamp[k] || []).push(a)
  }
  const countActive = (kids) => kids.filter(a => (a.effective_status || '') === 'ACTIVE').length
  const adsetActiveAds = {}, campActiveAds = {}
  for (const [sid, kids] of Object.entries(adsByAdset)) adsetActiveAds[sid] = countActive(kids)
  for (const [cid, kids] of Object.entries(adsByCamp)) campActiveAds[cid] = countActive(kids)
  return { adsetAllPaused, campAllPaused, adsetActiveAds, campActiveAds }
})
const effectiveStatusOf = (row, level) => {
  const st = row.effective_status || ''
  if (st !== 'ACTIVE') return st   // 已停/异常态原样
  const m = childPausedMap.value
  if (level === 'adset') {
    if (m.adsetAllPaused[String(row.id)]) return 'PAUSED'
    // 批BU：容器开着但下面零条生效投放中的广告 → 显示「无在投广告」（投放中=误导）
    if (!((m.adsetActiveAds || {})[String(row.id)] > 0)) return 'NO_ACTIVE_ADS'
  } else if (level === 'campaign') {
    if (m.campAllPaused[String(row.id)]) return 'PAUSED'
    if (!((m.campActiveAds || {})[String(row.id)] > 0)) return 'NO_ACTIVE_ADS'
  }
  return st
}
// 批BU：无在投广告态的悬浮说明（其余态不占 title）
const stIdleTitle = (row, level) =>
  effectiveStatusOf(row, level) === 'NO_ACTIVE_ADS' ? t('adm.stIdleTitle') : ''
const campNameOf = (s) => {
  const c = (data.value.campaigns || []).find(x => String(x.id) === String(s.campaign_id))
  return c ? t('adm.belongsToCampaign', { name: c.name }) : ''
}
const loading = ref(false)
const loadError = ref('')   // UI审计D：页面级错误态——空态与加载失败可区分
const _loadGuard = useLatest()
const _diagGuard = useLatest()    // 全库审查P2：诊断/潜客各自请求序列守卫（快速连点旧响应后到丢弃）
const _leadsGuard = useLatest()
const drillCampaign = ref('')
const drillAdset = ref('')
const statusFilter = ref('all')
const sortKey = ref('_status_rank')
const sortDir = ref('desc')
const searchQ = ref('')
let savedView = {}
try { savedView = JSON.parse(localStorage.getItem('admanager-view-v1') || '{}') } catch {}
const viewPrefs = ref(normalizeViewPreferences(savedView))
const availableColumns = computed(() => columnsFor(tab.value))
const visibleColumns = computed(() => availableColumns.value.filter(c => viewPrefs.value[tab.value]?.columns.includes(c.id)))
const contextOf = computed(() => entityContext(data.value))
watch(tab, level => {
  const pref = viewPrefs.value[level]
  if (pref) { sortKey.value = pref.sortKey; sortDir.value = pref.sortDir }
  selected.value = new Set(); budgetDialog.value = false
  batchResults.value = []   // 审查P2：批量结果条随 tab 切换清空（曾永驻且无关闭入口）
}, { flush: 'sync' })
sortKey.value = viewPrefs.value.campaign.sortKey
sortDir.value = viewPrefs.value.campaign.sortDir
watch([sortKey, sortDir], () => {
  const pref = viewPrefs.value[tab.value]
  if (pref) { pref.sortKey = sortKey.value; pref.sortDir = sortDir.value }
})
watch(viewPrefs, value => { try { localStorage.setItem('admanager-view-v1', JSON.stringify(value)) } catch {} }, { deep: true })

const curRange = computed(() => {
  if (showCustom.value && customFrom.value) return { date_from: customFrom.value, date_to: customTo.value || customFrom.value }
  const r = presetRange(datePreset.value)
  return r ? { date_from: r[0], date_to: r[1] } : { date_from: '', date_to: '' }
})

// 状态展示统一方案：后端已把 TT 行归一成 FB 形状 effective_status（ACTIVE/PAUSED/DISAPPROVED…），
// 主用 fbAdStatus；TT 特有枚举（STATUS_BUDGET_EXCEED 等透传值，FB registry 未收录）回落
// TT registry 翻译——三层表一套 chip 逻辑，无 per-row 平台分支
const _fbKnown = (s) => s && fbAdStatus(s).label !== s
const statusLabel = (s) => _fbKnown(s) ? fbAdStatus(s).label : ttAdStatus(s).label
const statusDot = (s) => _fbKnown(s) ? fbAdStatus(s).cls : ttAdStatus(s).cls
const OBJ_MAP = computed(() => ({ OUTCOME_SALES: t('adm.objSales'), OUTCOME_TRAFFIC: t('adm.objTraffic'), OUTCOME_ENGAGEMENT: t('adm.objEngagement'), OUTCOME_AWARENESS: t('adm.objAwareness'), OUTCOME_LEAD_GENERATION: t('adm.objLead'), LINK_CLICKS: t('adm.objTraffic'), CONVERSIONS: t('adm.objSales'), MESSAGES: t('adm.objMessages'), PAGE_LIKES: t('adm.objPageLikes'), POST_ENGAGEMENT: t('adm.objEngagement'), VIDEO_VIEWS: t('adm.objVideoViews'), BRAND_AWARENESS: t('adm.objAwareness'), REACH: t('adm.objReach') }))
const objLabel = (o) => OBJ_MAP.value[o] || o || '-'
const OPT_MAP = computed(() => ({ OFFSITE_CONVERSIONS: t('adm.optConversion'), LINK_CLICKS: t('adm.optLinkClicks'), LANDING_PAGE_VIEWS: t('adm.optLandingViews'), POST_ENGAGEMENT: t('adm.objEngagement'), REACH: t('adm.objReach'), IMPRESSIONS: t('adm.optImpressions'), VIDEO_VIEWS: t('adm.objVideoViews'), APP_INSTALLS: t('adm.optAppInstalls'), LEAD_GENERATION: t('adm.optLeadGen'), MESSAGING_CONVERSATIONS: t('adm.optMsgConv'), VALUE: t('adm.optValue') }))
const optLabel = (o) => OPT_MAP.value[o] || o || '-'

const _idOf = (v) => (v && typeof v === 'object') ? v.id : v
// 金额走中央 useFormat（'-' 显示与 AdManager 现状一致，用单横线）；reach 0→'-' 为"无触达"提示语义，本地保留
import { fmtUsd as _fmtUsd } from '../composables/useFormat'
import { fmtTime } from '../composables/useTz'
const fmtMoney = (v) => (v == null) ? '-' : _fmtUsd(v).replace('—', '-')
// 币种感知金额：USD → $；非 USD 本币 → "数值 币种代码"（与看板 fmtSpendDual 同约定，本币不加 $）
const fmtAmount = (v, cur) => {
  if (v == null) return '-'
  if (!cur || cur === 'USD') return _fmtUsd(v).replace('—', '-')
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }) + ' ' + cur
}
const fmtNum = (v) => (v == null || v === 0) ? '-' : Number(v).toLocaleString()
const fmtBudget = (a, ctx) => {
  if (a.daily_budget_amount != null) return t('adm.budgetDaily', { v: fmtAmount(a.daily_budget_amount, a.currency) })
  if (a.lifetime_budget_amount != null) return t('adm.budgetLifetime', { v: fmtAmount(a.lifetime_budget_amount, a.currency) })
  return ctx === 'campaign' ? t('adm.budgetAdsetLevel') : t('adm.budgetCampaignLevel')
}
const hasBudget = (a) => a.daily_budget_amount != null || a.lifetime_budget_amount != null

const loadAccounts = async () => {
  try {
    accounts.value = await GET('/fb/accounts'); const q = route.query.act; if (q) selectedActs.value = [q]
    await Promise.all([load(), loadRedirectMap()])   // 两者互不依赖且内部自吞错——并行省 1 RTT
  }
  catch (e) { ElMessage.error(e.message || t('adm.loadAccountsFail')) }
}
const load = async (refresh = false, silent = false) => {
  const isLatest = _loadGuard.next()
  if (!silent) loading.value = true
  try {
    const params = new URLSearchParams(curRange.value)
    if (refresh) params.set('refresh', '1')
    const r = await GET(`/ads/list?${params.toString()}`)
    if (!isLatest()) return   // 快速切日期/轮询完成回调并发时旧响应后到——丢弃
    data.value = r
    tokenStatus.value = r.token_status || {}
    loadError.value = ''
    if (refresh) { drillCampaign.value = ''; drillAdset.value = '' }   // 只在用户主动刷新时清下钻——后台刷新完成自动 load 不踢用户出当前视图
    // 后台刷：立即返回了缓存 → 轮询 refresh-status，完成后自动更新列表
    if (refresh && data.value.refreshing) watchRefreshDone()
  }
  catch (e) { if (isLatest()) { loadError.value = e.message || t('common.fail'); ElMessage.error(loadError.value) } }
  if (isLatest()) loading.value = false
}
// 后台刷新轮询：每 3s 查 /ads/refresh-status，running=false 时重拉列表；上限 20 次防死循环
let _refreshPoller = null
const watchRefreshDone = () => {
  if (_refreshPoller) return
  ElMessage.info(t('adm.bgRefreshing'))
  let n = 0
  _refreshPoller = setInterval(async () => {
    n++
    let done = false
    try { const st = await GET('/ads/refresh-status'); done = !st.running }
    catch { done = true }  // 状态端点失败也别死循环
    if (done || n >= 20) {
      clearInterval(_refreshPoller); _refreshPoller = null
      load()
    }
  }, 3000)
}
// 异常档集合：被拒/审核中/待定/有问题/封禁（不含已暂停——暂停是主动操作不是异常）
const ABNORMAL_SET = new Set(['DISAPPROVED', 'PENDING', 'PENDING_REVIEW', 'WITH_ISSUES', 'BLOCKED'])
const statusMatch = (s) => {
  if (statusFilter.value === 'all') return true
  if (statusFilter.value === 'active') return s === 'ACTIVE'
  if (statusFilter.value === 'idle') return s === 'NO_ACTIVE_ADS'   // 批BW：容器开但零在投（此前被「已暂停」误吞）
  if (statusFilter.value === 'abnormal') return ABNORMAL_SET.has(s)
  return s === 'PAUSED' || (s && s.includes('PAUSED'))
}
// 批AI：筛选按推导态（子全停的系列在「已暂停」筛选可见）——传行进来进行层级感知匹配
const statusMatchRow = (row, rawStatus) => {
  if (tab.value === 'ad') return statusMatch(rawStatus)
  return statusMatch(effectiveStatusOf(row, tab.value))
}
const actMatch = (item) => !selectedActs.value.length ? true : selectedActs.value.includes(item.act_id)
// 平台切换器过滤（纯前端：accounts 带 platform 字段，实体行按所属账户过滤）
const { platform } = usePlatform()
const platAccounts = computed(() => platform.value === 'all' ? accounts.value : accounts.value.filter(a => (a.platform || 'fb') === platform.value))
const platActIds = computed(() => platform.value === 'all' ? null : new Set(platAccounts.value.map(a => a.act_id)))
const platMatch = (item) => platform.value === 'all' || (item.platform || 'fb') === platform.value
// 页头副信息：仅选中单个账户时显示该账户名
const currentAccountName = computed(() => {
  if (selectedActs.value.length !== 1) return ''
  const a = accounts.value.find(x => x.act_id === selectedActs.value[0])
  return a?.name || ''
})
watch(platform, () => {
  // 切平台：勾选账户里不属于新平台的清掉（防"选中永不匹配"空列表）
  if (platActIds.value) selectedActs.value = selectedActs.value.filter(id => platActIds.value.has(id))
})
const platChip = (a) => (a && (a.platform === 'tt' || a.platform === 'fb')) ? a.platform : ''
// 按 act_id 反查平台（账户多选已选 tag 内渲染平台色 chip 用；#label slot 只拿得到 value）
const platChipOf = (actId) => platChip(accounts.value.find(x => x.act_id === actId))
// 已按平台筛选时行内平台 chip 冗余——隐藏（账户下拉选项仍带前缀）
const platChipByAct = (actId) => {
  if (platform.value !== 'all') return ''
  const a = accounts.value.find(x => x.act_id === actId)
  return platChip(a)
}
const sortBy = (key) => { if (sortKey.value === key) sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'; else { sortKey.value = key; sortDir.value = 'desc' } }
const _rankMap = { ACTIVE: 0, PAUSED: 1, NO_ACTIVE_ADS: 2, CAMPAIGN_PAUSED: 3, ADSET_PAUSED: 4, PENDING_REVIEW: 5, WITH_ISSUES: 6, DISAPPROVED: 7, ARCHIVED: 8, DELETED: 9 }
const statusRank = (s) => _rankMap[s] ?? 9
const sortIcon = (key) => sortKey.value === key ? (sortDir.value === 'desc' ? '▼' : '▲') : ''

// 当前筛选下实体的币种集合：>1 = 多币种混选 → Spend/CPA 折算 USD 展示与排序（本币裸加无意义）
const viewCurs = computed(() => {
  const s = new Set()
  for (const arr of [data.value.campaigns, data.value.adsets, data.value.ads])
    for (const it of (arr || [])) if (platMatch(it) && actMatch(it) && it.currency) s.add(it.currency)
  return s
})
const mixedCur = computed(() => viewCurs.value.size > 1)
const viewCur = computed(() => (mixedCur.value || !viewCurs.value.size) ? 'USD' : [...viewCurs.value][0])
// 预算列头币种标注：单一币种时显示 (XXX)；多币种混选不标（各行已带本币代码）
const fmtSpendCol = (a) => mixedCur.value ? fmtMoney(a.spend_usd) : fmtAmount(a.spend, viewCur.value)
const fmtCpaCol = (a) => mixedCur.value ? (a.cpa_usd ? fmtMoney(a.cpa_usd) : '-') : (a.cpa ? fmtAmount(a.cpa, viewCur.value) : '-')

// 数据时间戳统一在工具条「数据 X 分钟前」一处表达（批M：页头绝对时间 chip 移除，绝对值进 hover）


// 缓存新鲜度标签（批P3 双层诚实显示）：广告层 = 巡检 ~5min 回写（/ads 顶层 last_sync，
// 存活账户最新值）；系列/组结构层 = ~15min 全量同步（存活账户 campaign/adset snapshot_at 最新值）。
// 不随 Tab 暗变、不取最旧行——之前在系列/组 Tab 显示结构层龄被误解为"数据 14 分钟没更新"。
// 30s 心跳让「X 分钟前」自动走字
const nowTick = ref(Date.now())
let _ageTimer = null
const _ageMin = (iso) => {
  if (!iso) return null
  const ts = new Date(iso).getTime()
  if (isNaN(ts)) return null
  return Math.max(0, Math.floor((Date.now() - ts) / 60000))
}
const adsAgeMin = computed(() => { void nowTick.value; return _ageMin(data.value.last_sync) })
const structAgeMin = computed(() => {
  void nowTick.value
  // 死令牌账户恒冻结（拉不动）——不算进聚合，否则整页被僵尸行钉死（批K）
  const dead = new Set(deadAccounts.value)
  const ts = [...(data.value.campaigns || []), ...(data.value.adsets || [])]
    .filter(a => !dead.has(a.act_id))
    .map(a => a.snapshot_at).filter(Boolean).sort()
  return ts.length ? _ageMin(ts[ts.length - 1]) : null
})
const _ageTxt = (m) => m == null ? '—' : (m < 1 ? t('adm.cacheAgeLt1Short') : t('adm.cacheAgeShort', { n: m }))
const cacheAgeText = computed(() => {
  // 批AF：巡检 5min 同时回写广告层与结构层（campaigns/adsets）——两层同龄，单层显示取更旧者
  const a = adsAgeMin.value, s = structAgeMin.value
  if (a == null && s == null) return t('adm.cacheAgeNone')
  return t('adm.cacheAgeSingle', { v: _ageTxt(Math.max(a ?? 0, s ?? 0)) })
})
const cacheAgeStale = computed(() => adsAgeMin.value != null && adsAgeMin.value >= 60)

// 实时核验：对选中账户逐个调 GET /ads/live-status?act_id=，用返回 {ads:[{id,effective_status}]} 逐条 patch 本地行
// 失败 toast；同账户 10s 防抖（后端另有缓存，双保险）
const liveVerifying = ref(false)
const liveVerifiedAt = ref('')
const _liveLastCall = {}
const verifyLive = async () => {
  const targets = [...new Set(selectedActs.value)]
  if (!targets.length) return ElMessage.warning(t('adm.liveVerifyPickAccount'))
  const now = Date.now()
  const todo = targets.filter(id => (now - (_liveLastCall[id] || 0)) >= 10000)
  if (!todo.length) return ElMessage.warning(t('adm.liveVerifyTooOften'))
  liveVerifying.value = true
  let patched = 0
  let firstErr = null
  for (const actId of todo) {
    _liveLastCall[actId] = Date.now()
    try {
      const r = await GET('/ads/live-status?act_id=' + encodeURIComponent(actId))
      const m = new Map((r.ads || []).map(x => [String(x.id), x.effective_status]))
      for (const ad of (data.value.ads || [])) {
        if (ad.act_id !== actId) continue
        const st = m.get(String(ad.id))
        if (st != null) { ad.effective_status = st; patched++ }
      }
    } catch (e) { if (!/not found/i.test(e.message || '')) firstErr = firstErr || e }
  }
  liveVerifying.value = false
  if (firstErr) { ElMessage.error(t('adm.liveVerifyFail') + '：' + (firstErr.message || '')); return }
  liveVerifiedAt.value = new Date().toLocaleTimeString(locale.value === 'en' ? 'en-US' : 'zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  ElMessage.success(t('adm.liveVerifyOk', { n: patched }))
}

// 细分（Breakdowns）：广告行按年龄/性别/版位拉 FB insights 分组弹窗（FB 账户专属，TT 无此结构）
const breakdownOpen = ref(false)
const breakdownLoading = ref(false)
const breakdownRows = ref([])
const breakdownDim = ref('age')
const breakdownTarget = ref(null)
const BREAKDOWN_DIMS = computed(() => [
  { id: 'age', label: t('adm.breakdownAge') },
  { id: 'gender', label: t('adm.breakdownGender') },
  { id: 'placement', label: t('adm.breakdownPlacement') },
  { id: 'conversion_location', label: t('adm.breakdownConvLoc') },
])
const _bdGuard = useLatest()   // 快速切维度连发——旧响应后到丢弃
const openBreakdown = (item) => {
  breakdownTarget.value = { act_id: item.act_id, id: item.id, name: item.name, currency: item.currency || 'USD' }
  breakdownDim.value = 'age'
  breakdownRows.value = []
  breakdownOpen.value = true
  loadBreakdown()
}
const loadBreakdown = async (refresh = false) => {
  if (!breakdownTarget.value) return
  const isLatest = _bdGuard.next()
  breakdownLoading.value = true
  try {
    const params = new URLSearchParams({
      act_id: breakdownTarget.value.act_id, ad_id: breakdownTarget.value.id,
      dimension: breakdownDim.value, ...curRange.value,
    })
    if (refresh) params.set('refresh', '1')
    const r = await GET('/ads/insights/breakdown?' + params.toString())
    if (!isLatest()) return
    breakdownRows.value = r.rows || []
    if (r.currency) breakdownTarget.value.currency = r.currency
  } catch (e) {
    if (isLatest()) { breakdownRows.value = []; ElMessage.error(t('adm.breakdownFail', { msg: e.message || '' })) }
  }
  if (isLatest()) breakdownLoading.value = false
}
watch(breakdownDim, () => { if (breakdownOpen.value) loadBreakdown() })
// 版位行值：fb/ig/an/msg 是 FB 内部码，翻译成品牌名；其余段（feed/story 等）原样
const _PLAT_NAMES = { fb: 'Facebook', ig: 'Instagram', an: 'Audience Network', msg: 'Messenger' }
const bdLabel = (v) => String(v || '').split(' · ').map(seg => _PLAT_NAMES[seg.toLowerCase()] || seg).filter(Boolean).join(' · ')
// 转化位置行值（conversion_destination，FB 返英文显示名）中文映射；en 原样
const _CONV_DEST_ZH = { Website: '网站', App: '应用', Shop: '店铺', 'Instant Experience': '即时体验', 'On your ad': '广告中' }
const bdConvLabel = (v) => (locale.value === 'en' || !v) ? String(v || '') : (_CONV_DEST_ZH[v] || v)

const curList = computed(() => {
  let arr
  if (tab.value === 'campaign') arr = data.value.campaigns || []
  else if (tab.value === 'adset') { arr = data.value.adsets || []; if (drillCampaign.value) arr = arr.filter(a => _idOf(a.campaign_id) === drillCampaign.value) }
  else { arr = data.value.ads || []; if (drillAdset.value) arr = arr.filter(a => String(_idOf(a.adset_id)) === String(drillAdset.value)); else if (drillCampaign.value) arr = arr.filter(a => String(_idOf(a.campaign_id)) === String(drillCampaign.value)) }
  arr = arr.filter(a => platMatch(a) && actMatch(a) && statusMatchRow(a, a.effective_status))
  // 脱管/被禁账户排后面（用户反馈：不好区分，正常在前异常在后）
  const _deadRank = (a) => accStateTag(a) ? 1 : 0
  arr = arr.slice()
  if (searchQ.value.trim()) {
    const q = searchQ.value.trim().toLowerCase()
    arr = arr.filter(a => searchMatches(a, q, contextOf.value))
  }
  return arr.slice().sort((a, b) => {
    // P0-1：statusOf 物化派生态（NO_ACTIVE_ADS/联动暂停）——曾只传字符串 rank 函数读原始
    // effective_status，_rankMap 的 NO_ACTIVE_ADS:2 是不可达死配置，「无在投」与投放中同层
    return compareRows(a, b, { key: sortKey.value, direction: sortDir.value, mixedCurrency: mixedCur.value, blocked: _deadRank, statusRank, statusOf: r => effectiveStatusOf(r, tab.value) })

  })
})
// 表尾汇总：当前筛选后的消耗/转化合计（多币种折 USD，与列口径一致）
const sumSpend = computed(() => {
  let native = 0, usd = 0
  for (const it of curList.value) { native += Number(it.spend || 0); usd += Number(it.spend_usd || 0) }
  return mixedCur.value ? (usd ? fmtMoney(usd) : '-') : fmtAmount(native, viewCur.value)
})
const totalLabel = computed(() => t('adm.totalRow', { n: curList.value.length }))
const drillName = computed(() => {
  if (tab.value === 'adset' && drillCampaign.value) { const c = (data.value.campaigns || []).find(x => x.id === drillCampaign.value); return c ? t('adm.drillCampaign', { name: c.name }) : '' }
  if (tab.value === 'ad' && drillAdset.value) { const s = (data.value.adsets || []).find(x => x.id === drillAdset.value); return s ? t('adm.drillAdset', { name: s.name }) : '' }
  return ''
})
const drillToAdset = (c) => { drillCampaign.value = c.id; drillAdset.value = ''; tab.value = 'adset'; selectedActs.value = [c.act_id] }
const drillToAd = (s) => { drillCampaign.value = _idOf(s.campaign_id) || ''; drillAdset.value = s.id; tab.value = 'ad'; selectedActs.value = [s.act_id] }
const clearDrill = () => { drillCampaign.value = ''; drillAdset.value = '' }
onMounted(() => { loadAccounts(); _ageTimer = setInterval(() => { nowTick.value = Date.now() }, 30000) })
// 自动跟随巡检（批N）：巡检 5min 一轮回写缓存，页面静默同步（不弹 loading、不清下钻）；
// 页面在后台时跳过（回来后 30s 心跳仍会刷新「X 分钟前」走字，下次前台周期再拉）
let _autoTimer = null
onMounted(() => {
  _autoTimer = setInterval(() => {
    if (document.hidden || loading.value || tab.value === 'lead') return
    load(false, true)
  }, 5 * 60 * 1000)
})
onUnmounted(() => { if (_refreshPoller) { clearInterval(_refreshPoller); _refreshPoller = null }; if (_leadsTimer) { clearInterval(_leadsTimer); _leadsTimer = null }; if (_ageTimer) { clearInterval(_ageTimer); _ageTimer = null }; if (_autoTimer) { clearInterval(_autoTimer); _autoTimer = null } })

const selected = ref(new Set())
const opLoading = ref(false)
const budgetDialog = ref(false)
const budgetTarget = ref(null)
const budgetInput = ref('')
// 广告级跳转链接覆盖
const redirectMap = ref({})           // {ad_id: target_url} 内联显示用
const redirectDialog = ref(false)     // 设单条
const redirectTarget = ref(null)      // {id, name}
const redirectInput = ref('')
const redirectMgmtOpen = ref(false)   // 管理列表
const redirectList = ref([])
const curLevel = () => tab.value === 'campaign' ? 'campaign' : (tab.value === 'adset' ? 'adset' : 'ad')

const toggleStatus = async (item) => {
  if (opLoading.value || accStateTag(item)) return
  const ns = item.effective_status === 'ACTIVE' ? 'PAUSED' : 'ACTIVE'
  opLoading.value = true
  try {
    const r = await POST('/ads/status', { act_id: item.act_id, node_id: item.id, level: curLevel(), status: ns })
    if (r.success) {
      item.effective_status = r.effective_status || ns; item.status = ns
      // 假停/未生效：后端回读核验 verified=false 或带 warning → 警示而非成功提示
      if (r.verified === false || r.warning) ElMessage.warning(r.warning || t('adm.fakePauseWarn'))
      else ElMessage.success(ns === 'ACTIVE' ? t('adm.activated') : t('adm.paused'))
    } else ElMessage.error(r.error || t('common.opFail'))
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  opLoading.value = false
}
const openBudget = (item) => {
  if (opLoading.value || accStateTag(item)) return
  const isLifetime = item.daily_budget_amount == null && item.lifetime_budget_amount != null
  budgetTarget.value = {
    act_id: item.act_id, node_id: item.id, level: curLevel(), name: item.name,
    budget_type: isLifetime ? 'lifetime' : 'daily',
    old_value: Number(isLifetime ? item.lifetime_budget_amount : item.daily_budget_amount) || 0,
    currency: item.currency || 'USD',
  }
  budgetInput.value = ''
  budgetDialog.value = true
}
// 预算大幅上调防护：新值 > 旧值×3 且差额 > 500（本币）→ 二次确认（防手滑多打一个 0；×2 快捷键叠加后同判）
const _fmtBudgetVal = (v, cur) => cur === 'USD' ? '$' + Number(v).toLocaleString() : Number(v).toLocaleString()
const saveBudget = async () => {
  if (opLoading.value) return
  if (!budgetInput.value || budgetInput.value <= 0) return ElMessage.warning(t('adm.budgetGtZero'))
  const nv = Number(budgetInput.value)
  const ov = Number(budgetTarget.value.old_value || 0)
  const cur = budgetTarget.value.currency || 'USD'
  if (ov > 0 && nv > ov * 3 && nv - ov > 500) {
    const change = _fmtBudgetVal(ov, cur) + ' → ' + _fmtBudgetVal(nv, cur) + ' (' + cur + ')'
    try { await ElMessageBox.confirm(t('adm.budgetBigJumpConfirm', { change }), t('adm.budgetBigJumpTitle'), { type: 'warning', confirmButtonText: t('common.save'), cancelButtonText: t('common.cancel') }) }
    catch { return }   // 用户取消：留在对话框可改回
  }
  const bt = budgetTarget.value.budget_type
  const payload = { act_id: budgetTarget.value.act_id, node_id: budgetTarget.value.node_id, level: budgetTarget.value.level, budget_type: bt }
  payload[bt === 'lifetime' ? 'lifetime_budget' : 'daily_budget'] = budgetInput.value
  opLoading.value = true
  try {
    const r = await POST('/ads/budget', payload)
    if (r.success && (r.verified === false || r.warning)) {
      ElMessage.warning(r.warning || t('adm.budgetUnverified'))
      opLoading.value = false
      return
    }
    if (r.success) {
      const it = curList.value.find(x => x.id === budgetTarget.value.node_id)
      if (it) {
        if (bt === 'lifetime') { it.lifetime_budget_amount = budgetInput.value; it.lifetime_budget = r.budget_minor }
        else { it.daily_budget_amount = budgetInput.value; it.daily_budget = r.budget_minor }
      }
      ElMessage.success(t('adm.budgetUpdated')); budgetDialog.value = false
    } else ElMessage.error(r.error || t('common.opFail'))
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  opLoading.value = false
}
const deleteItem = async (item) => {
  try {
    // 批BW：确认文案写明级联范围（FB 删除不可逆：系列连带全部组/广告，组连带广告）
    await ElMessageBox.confirm(
      t('adm.delConfirm', { name: item.name }) + (tab.value === 'campaign' ? `\n\n${t('adm.delCascadeCampaign')}` : tab.value === 'adset' ? `\n\n${t('adm.delCascadeAdset')}` : ''),
      t('common.delConfirm'), { type: 'warning', confirmButtonText: t('common.delConfirm'), confirmButtonClass: 'el-button--danger' })
    opLoading.value = true
    try {
      await POST('/ads/delete', { act_id: item.act_id, node_id: item.id })
      // 本地移除（FB 删除即定局；删系列连带组/广告，删组连带广告）——省掉全量重拉 /ads/list
      const _idStr = String(item.id)
      const _keepParent = (pk) => (x) => String(_idOf(x[pk])) !== _idStr
      data.value.campaigns = (data.value.campaigns || []).filter(x => String(x.id) !== _idStr)
      if (tab.value === 'campaign') data.value.adsets = (data.value.adsets || []).filter(_keepParent('campaign_id'))
      if (tab.value !== 'ad') {
        const _fk = tab.value === 'campaign' ? 'campaign_id' : 'adset_id'
        data.value.ads = (data.value.ads || []).filter(_keepParent(_fk))
      }
      ElMessage.success(t('adm.deleted'))
    } catch (e) { ElMessage.error(e.message || t('common.opFail')) }   // 失败（无写令牌/FB 拒/并发锁）要告诉用户为什么
  } catch(e) { /* 用户取消 */ }
  opLoading.value = false
}
const batchStatus = async (status) => {
  if (opLoading.value) return
  if (!selected.value.size) return ElMessage.warning(t('adm.selectRowsFirst'))
  if (status === 'PAUSED') {
    try { await ElMessageBox.confirm(t('adm.batchPauseConfirm', { n: selected.value.size }), t('adm.batchPauseTitle'), { type: 'warning', confirmButtonText: t('adm.paused'), cancelButtonText: t('common.cancel'), confirmButtonClass: 'el-button--danger' }) }
    catch { return }
  } else if (status === 'ACTIVE') {
    try { await ElMessageBox.confirm(t('adm.batchActivateConfirm', { n: selected.value.size }), t('adm.batchActivateTitle'), { type: 'warning', confirmButtonText: t('adm.batchActivate'), cancelButtonText: t('common.cancel') }) }
    catch { return }
  }
  const items = []; for (const id of selected.value) { const it = curList.value.find(x => entityKey(x) === id); if (it && !accStateTag(it)) items.push({ act_id: it.act_id, node_id: it.id, level: curLevel(), status }) }
  if (!items.length) return ElMessage.warning(t('adm.selectRowsFirst'))
  opLoading.value = true
  try {
    const r = await POST('/ads/batch-status', { items })
    batchResults.value = r.results || []
    // 任一条假停/未生效（verified=false 或 warning）→ warning 而非 success
    const warnItem = (r.results || []).find(x => !x.success || x.warning || x.verified === false)
    if (warnItem || r.success_count !== items.length) ElMessage.warning(t('adm.batchResult', { ok: r.success_count, n: items.length }) + ' · ' + (warnItem?.warning || warnItem?.error || t('adm.fakePauseWarn')))
    else ElMessage.success(t('adm.batchResult', { ok: r.success_count, n: items.length }))
    const failedKeys = new Set(items.filter(it => !batchResults.value.some(r => r.node_id === it.node_id && (!r.act_id || r.act_id === it.act_id) && r.success && r.verified !== false && !r.warning)).map(it => {
      const row = curList.value.find(a => a.id === it.node_id && a.act_id === it.act_id)
      return row && entityKey(row)
    }).filter(Boolean))
    // 原地 patch 成功行（写响应逐项带 effective_status）——省掉全量重拉 /ads/list；失败行保留勾选便于重试
    for (const rr of (r.results || [])) {
      if (!rr.success || rr.verified === false) continue
      const row = curList.value.find(a => String(a.id) === String(rr.node_id) && (!rr.act_id || a.act_id === rr.act_id))
      if (row) {
        const st = rr.effective_status || status
        row.effective_status = st; row.status = st
      }
    }
    selected.value = failedKeys
  } catch (e) { ElMessage.error(e.message || t('adm.batchOpFail')) }
  opLoading.value = false
}
// 创意缩略图：大图源优先（adimages 原图 CDN / 本地素材），FB thumbnail_url(128px) 兜底。
// 行内缩略与点击放大弹窗共用（全库审查P2：删除优先级链完全相同的重复 bigThumbOf）
const thumbFailures = ref({})
const batchResults = ref([])
const thumbSources = a => [...new Set([a?.big_thumb, a?.local_thumb, a?.creative?.thumbnail_url].filter(Boolean))]
const thumbOf = a => thumbSources(a)[thumbFailures.value[entityKey(a)] || 0] || ''
const nextThumb = a => { const key = entityKey(a); thumbFailures.value[key] = (thumbFailures.value[key] || 0) + 1 }
// FB CTA 按钮文案（FB 官方中文叫法；en 原名本身即英文）
const CTA_LABELS = {
  LEARN_MORE: '了解详情', SHOP_NOW: '立即购物', SIGN_UP: '注册', SUBSCRIBE: '订阅',
  CONTACT_US: '联系我们', DOWNLOAD: '下载应用', BOOK_TRAVEL: '预订', BOOK_NOW: '立即预订',
  GET_OFFER: '领取优惠', ORDER_NOW: '立即订购', CALL_NOW: '立即致电', WATCH_MORE: '观看更多',
  LISTEN_NOW: '立即收听', REQUEST_TIME: '预约时间', GET_QUOTE: '获取报价', LINK_CLICK: '点击链接',
  LIKE_PAGE: '赞主页', FOLLOW_PAGE: '关注主页', NO_BUTTON: '无按钮',
}
const ctaOf = (a) => {
  const cta = a?.creative?.object_story_spec?.link_data?.call_to_action
  const ty = cta?.type || ''
  return ty ? { label: (locale.value === 'en' ? ty.replaceAll('_', ' ') : CTA_LABELS[ty]) || ty, link: cta?.value?.link || '' } : null
}
const showThumb = (a) => {
  const u = thumbOf(a)
  const ti = titleOf(a), co = copyOf(a), cta = ctaOf(a)
  ElMessageBox.alert(h('div', { class: 'cre-preview' }, [
    u ? h('img', { src: u, style: 'width:100%;border-radius:8px;display:block', onError: event => { nextThumb(a); const next = thumbOf(a); if (next) event.target.src = next; else event.target.replaceWith(document.createTextNode(t('adm.thumbNone'))) } }) : h('div', t('adm.thumbNone')),
    ti ? h('div', { style: 'font-weight:600;margin:10px 2px 2px;font-size:14px' }, ti) : null,
    co ? h('div', { style: 'color:var(--t3);margin:2px;font-size:12px;line-height:1.5;white-space:pre-wrap' }, co) : null,
    cta ? h('div', { style: 'margin:10px 2px 2px' }, [
      h('span', { style: 'display:inline-block;background:#0a84ff;color:#fff;border-radius:6px;padding:6px 14px;font-size:12px', title: cta.link || '' }, `▶ ${cta.label}`),
    ]) : null,
  ]), t('adm.thumbTitle'), { confirmButtonText: t('common.confirm'), customStyle: { maxWidth: '520px' } })
}
// 创意文案：creative.body/title（v25 仍可读）优先，object_story_spec.link_data 兜底（spec 创建的）
const titleOf = (a) => a?.creative?.title || a?.creative?.object_story_spec?.link_data?.name || ''
const copyOf = (a) => a?.creative?.body || a?.creative?.object_story_spec?.link_data?.message || ''
// FB review_feedback 结构不固定——递归收集字符串（跳过纯数字 id），逐行展示
const rfText = (rf) => {
  if (!rf) return ''
  if (typeof rf === 'string') return rf
  const lines = []
  const walk = (o) => {
    if (o == null || lines.length >= 15) return
    if (typeof o === 'string' || typeof o === 'number') {
      const s = String(o).trim()
      if (s && !/^\d+$/.test(s)) lines.push(s)
    } else if (Array.isArray(o)) o.forEach(walk)
    else if (typeof o === 'object') Object.values(o).forEach(walk)
  }
  walk(rf)
  return lines.join('\n')
}
const rfOf = (a) => rfText(a.review_feedback)
const showReview = (a) => {
  const txt = rfOf(a)
  if (!txt) return
  ElMessageBox.alert(h('div', { style: 'white-space:pre-wrap;word-break:break-word;font-size:12px;line-height:1.7;max-height:50vh;overflow:auto' }, txt), t('adm.reviewFlagTitle'), { confirmButtonText: t('common.confirm') })
}
// 改名（campaign/adset/ad 通用）
const renameItem = async (item) => {
  try {
    const { value } = await ElMessageBox.prompt(t('adm.renamePrompt'), t('adm.renameTitle', { name: item.name }), {
      inputValue: item.name, confirmButtonText: t('common.save'), cancelButtonText: t('common.cancel'),
      inputValidator: (v) => (!v || !v.trim()) ? t('adm.renameEmpty') : (v.trim().length > 200 ? t('adm.renameTooLong') : true),
    })
    const name = value.trim()
    opLoading.value = true
    try {
      const r = await POST('/ads/rename', { act_id: item.act_id, node_id: item.id, level: curLevel(), name })
      if (r.success) { item.name = r.name || name; ElMessage.success(t('adm.renamed')) }
      else ElMessage.error(r.error || t('common.opFail'))
    } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  } catch (e) { /* 用户取消 */ }
  opLoading.value = false
}
const onAction = (cmd, item) => { if (cmd === 'toggle') toggleStatus(item); else if (cmd === 'rename') renameItem(item); else if (cmd === 'budget') openBudget(item); else if (cmd === 'delete') deleteItem(item); else if (cmd === 'redirect') openRedirect(item); else if (cmd === 'logs') router.push({ name: 'landing', query: { tab: 'logs', ad_id: item.id } }); else if (cmd === 'diagnose') openDiagnose(item); else if (cmd === 'breakdown') openBreakdown(item); else if (cmd === 'reuse') router.push({ name: 'launch-templates', query: { reuse_post: item.object_story_id } }) }

// 广告诊断
const diagOpen = ref(false)
const diagLoading = ref(false)
const diagData = ref(null)
const openDiagnose = async (item) => {
  const isLatest = _diagGuard.next()   // 全库审查P2：连点不同广告诊断——旧响应后到丢弃，不覆盖新弹窗数据
  diagOpen.value = true; diagLoading.value = true; diagData.value = null
  try { const r = await GET('/ads/' + item.id + '/diagnose'); if (isLatest()) diagData.value = r }
  catch (e) { if (isLatest()) ElMessage.error(t('adm.diagFail', { msg: e.message || '' })) }
  if (isLatest()) diagLoading.value = false
}
const RULE_ZH = computed(() => ({ bleed_abs: t('adm.ruleBleedAbs'), cpa_exceed: t('adm.ruleCpaExceed'), consecutive_bad: t('adm.ruleConsecutiveBad'), click_no_conv: t('adm.ruleClickNoConv'), reach_no_conv: t('adm.ruleReachNoConv'), low_ctr_no_conv: t('adm.ruleLowCtrNoConv'), budget_burn_fast: t('adm.ruleBudgetBurnFast'), cpm_high: t('adm.ruleCpmHigh'), cpc_high: t('adm.ruleCpcHigh'), click_fraud: t('adm.ruleClickFraud'), fast_scale: t('adm.ruleFastScale') }))
const CS_ZH = computed(() => ({ fb: t('adm.csFb'), landing: t('adm.csLanding'), either: t('adm.csEither') }))
const goLandingLogs = (slug, adId) => { router.push({ name: 'landing', query: { tab: 'logs', slug, ad_id: adId } }) }
const loadRedirectMap = async () => { try { redirectMap.value = await GET('/ads/redirects/map') } catch (e) {} }
const openRedirect = (item) => { redirectTarget.value = { id: item.id, name: item.name }; redirectInput.value = redirectMap.value[item.id] || ''; redirectDialog.value = true }
const redirectSaving = ref(false)
const saveRedirect = async () => {
  if (redirectSaving.value) return   // 防双击重复 POST
  redirectSaving.value = true
  const adId = redirectTarget.value.id
  try { await POST('/ads/redirects', { ad_id: adId, target_url: redirectInput.value.trim() })
    if (redirectInput.value.trim()) { redirectMap.value = { ...redirectMap.value, [adId]: redirectInput.value.trim() } }
    else { const m = { ...redirectMap.value }; delete m[adId]; redirectMap.value = m }
    ElMessage.success(redirectInput.value.trim() ? t('adm.redirectSet') : t('adm.redirectRestored')); redirectDialog.value = false
  } catch (e) { ElMessage.error(t('common.fail') + ': ' + (e.message || '')) }
  redirectSaving.value = false
}
const mgmtLoading = ref(false)
const hostOf = (u) => { try { return new URL(u).hostname } catch { return '' } }
const openRedirectMgmt = async () => {
  redirectMgmtOpen.value = true; mgmtLoading.value = true
  try { redirectList.value = await GET('/ads/redirects') } catch (e) {}
  mgmtLoading.value = false
}
const removeRedirect = async (adId) => {
  try { await ElMessageBox.confirm(t('adm.redirectRemoveConfirm'), t('common.confirm'), { type: 'warning' }) } catch { return }
  opLoading.value = true
  try { await DELETE('/ads/redirects/' + adId); const m = { ...redirectMap.value }; delete m[adId]; redirectMap.value = m; redirectList.value = redirectList.value.filter(r => r.ad_id !== adId); ElMessage.success(t('adm.redirectRestored')) }
  catch (e) { ElMessage.error(e.message || t('common.fail')) }   // UI审计#5：曾静默吞错——删失败零反馈且可连点
  opLoading.value = false
}
const resetRedirects = async () => {
  try { await ElMessageBox.confirm(t('adm.resetRedirectsMsg'), t('common.confirm'), { type: 'warning' })
    const r = await POST('/ads/redirects/reset', {}); redirectMap.value = {}; redirectList.value = []; ElMessage.success(t('adm.redirectsCleared', { n: r.cleared || 0 }))
  } catch (e) {}
}
const toggleSelect = (id) => { const s = new Set(selected.value); s.has(id) ? s.delete(id) : s.add(id); selected.value = s }
const selectAll = () => { selected.value = allSelected.value ? new Set() : new Set(curList.value.map(entityKey)) }
const isSelected = (id) => selected.value.has(id)
const allSelected = computed(() => curList.value.length > 0 && curList.value.every(a => selected.value.has(entityKey(a))))
watch(curList, rows => {
  const keys = new Set(rows.map(entityKey))
  selected.value = new Set([...selected.value].filter(key => keys.has(key)))
})
const campaignCrumb = computed(() => (data.value.campaigns || []).find(a => String(a.id) === String(drillCampaign.value) && actMatch(a))?.name || drillCampaign.value)
const adsetCrumb = computed(() => (data.value.adsets || []).find(a => String(a.id) === String(drillAdset.value) && actMatch(a))?.name || drillAdset.value)
const tableWidth = computed(() => 600 + visibleColumns.value.reduce((n, c) => n + c.width, 0))
// 行内快照三档（批M 降噪）：≤1h 灰色相对分钟；1-6h 灰色小时；>6h 橙色过期（绝对时间在 title）
const _snapMins = a => {
  if (!a.snapshot_at) return null
  const ts = new Date(a.snapshot_at).getTime()
  return isNaN(ts) ? null : Math.max(0, Math.floor((nowTick.value - ts) / 60000))
}
const snapshotStale = a => { const m = _snapMins(a); return m != null && m > 360 }
const snapshotText = a => {
  const m = _snapMins(a)
  if (m == null) return t('adm.snapshotUnknown')
  if (m > 360) return t('adm.staleSnapshot', { n: Math.floor(m / 60) })
  if (m >= 60) return t('adm.snapHour', { n: Math.floor(m / 60) })
  return t('adm.snapMin', { n: m })
}
// 成效（FB）列缺失成因区分：早于采集上线（迁移默认 0）vs 日期范围无完整数据
const fbTip = (a) => a.results_fb_available === false ? t('adm.fbNotCollected') : (a.results_fb_complete === false || a.results_fb == null ? t('adm.fbMissing') : '')
const metricText = (a, id) => {
  if (id === 'objective') return objLabel(a.objective)
  if (id === 'optimization_goal') return optLabel(a.optimization_goal)
  if (id === 'pixel') {   // 组级转化像素（promoted_object.pixel_id；缓存可能存字符串形态）
    let po = a.promoted_object
    if (typeof po === 'string') { try { po = JSON.parse(po) } catch { po = null } }
    return po?.pixel_id || '—'
  }
  if (id === 'spend') return fmtSpendCol(a)
  if (id === 'cpa') return fmtCpaCol(a)
  if (id === 'results_fb') return fbResult(a) == null ? '—' : fbResult(a).toLocaleString()
  if (id === 'cost_per_result') return fmtAmount(mixedCur.value ? a.cost_per_result_usd : a.cost_per_result, viewCur.value)
  if (id === 'ctr') return a.ctr == null ? '—' : Number(a.ctr).toFixed(2) + '%'
  if (id === 'pass_rate') return a.landing_visits ? Math.round((a.landing_pass || 0) / a.landing_visits * 100) + '%' : '—'
  return a[id] == null || a[id] === '' ? '—' : typeof a[id] === 'number' ? a[id].toLocaleString() : a[id]
}
const sumMetric = id => {
  if (id === 'spend') return sumSpend.value
  if (!['results_fb','impressions','clicks','landing_visits','landing_pass'].includes(id)) return ''
  if (id === 'results_fb' && curList.value.some(a => fbResult(a) == null)) return '—'
  return curList.value.reduce((sum, a) => sum + Number(a[id] || 0), 0).toLocaleString()
}

// 潜客（FB Leadgen）
const leads = ref([])
const leadsLoading = ref(false)
const FIELD_LABELS = computed(() => ({ city: t('adm.lfCity'), state: t('adm.lfState'), zip_code: t('adm.lfZip'), postal_code: t('adm.lfZip'), country: t('adm.lfCountry'), gender: t('adm.lfGender'), date_of_birth: t('adm.lfDob'), marital_status: t('adm.lfMarital'), company_name: t('adm.lfCompany'), job_title: t('adm.lfJob'), address: t('adm.lfAddress'), no_of_employees: t('adm.lfEmps') }))
const fieldLabel = (k) => FIELD_LABELS.value[k] || k.replace(/_/g, ' ')
const leadFieldMap = (l) => { const m = {}; for (const f of (l.field_data || [])) m[f.name] = (f.values || [])[0] || ''; return m }
const leadField = (l, names) => { const m = leadFieldMap(l); for (const n of names) if (m[n]) return m[n]; return '' }
const LEAD_SKIP = ['full_name', 'first_name', 'last_name', 'email', 'work_email', 'phone_number', 'phone', 'work_phone_number']
const leadExtra = (l) => Object.entries(leadFieldMap(l)).filter(([k]) => !LEAD_SKIP.includes(k))
const fmtLeadTime = (iso) => { if (!iso) return '-'; try { return new Date(iso).toLocaleString(locale.value === 'en' ? 'en-US' : 'zh-CN', { hour12: false }) } catch { return iso } }
// 轻 CRM：跟进状态（new/contacted/won/lost）+ 备注 + 筛选
const LEAD_STATUSES = ['new', 'contacted', 'won', 'lost']
const leadStatusFilter = ref('all')
const LEAD_STATUS_LABEL = computed(() => ({ new: t('adm.leadStatus.new'), contacted: t('adm.leadStatus.contacted'), won: t('adm.leadStatus.won'), lost: t('adm.leadStatus.lost') }))
const leadStatusLabel = (s) => LEAD_STATUS_LABEL.value[s || 'new'] || s
const leadStatusFilterLabel = (s) => s === 'all' ? t('common.all') : leadStatusLabel(s)
const switchLeadTab = () => { tab.value = 'lead'; selected.value = new Set(); if (!leads.value.length) loadLeads() }
const loadLeads = async () => {
  const isLatest = _leadsGuard.next()   // 全库审查P2：快速切状态筛选连发——旧响应后到丢弃
  leadsLoading.value = true
  try {
    const q = leadStatusFilter.value !== 'all' ? '?status=' + encodeURIComponent(leadStatusFilter.value) : ''
    const r = await GET('/leads' + q)
    if (!isLatest()) return
    leads.value = r.items || []
  }
  catch (e) { if (isLatest()) ElMessage.error(e.message || t('common.fail')) }
  if (isLatest()) leadsLoading.value = false
}
const setLeadStatus = async (l, status) => {
  if ((l.status || 'new') === status) return
  try {
    const r = await PATCH('/leads/' + l.id, { status })
    l.status = r.status; l.status_updated_at = r.status_updated_at
    ElMessage.success(t('adm.leadStatusUpdated'))
    // 筛选中把行改成不属于当前筛选的状态 → 重载让它消失（all/同筛选下原地更新即可）
    if (leadStatusFilter.value !== 'all' && leadStatusFilter.value !== status) await loadLeads()
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
}
const editLeadNote = async (l) => {
  const name = leadField(l, ['full_name', 'first_name', 'last_name']) || l.lead_id
  try {
    const { value } = await ElMessageBox.prompt(t('adm.leadNotePrompt'), t('adm.leadNoteTitle', { name }), {
      inputValue: l.note || '',
      confirmButtonText: t('common.save'), cancelButtonText: t('common.cancel'),
      inputType: 'textarea',
      inputValidator: (v) => ((v || '').length > 2000) ? t('adm.leadNoteTooLong') : true,
    })
    const note = (value || '').trim()
    const r = await PATCH('/leads/' + l.id, { note })
    l.note = r.note; l.status_updated_at = r.status_updated_at
    ElMessage.success(t('adm.leadNoteUpdated'))
  } catch (e) { if (e && e.message) ElMessage.error(e.message || t('common.opFail')) }
}
const syncLeads = async () => {
  opLoading.value = true
  try {
    let baseTotal = 0
    try { baseTotal = (await GET('/leads')).total || 0 } catch {}
    const r = await POST('/leads/sync')
    if (r.error) ElMessage.warning(t('adm.leadsErr', { msg: r.error }))
    else if (!r.started) { await loadLeads() }
    else {
      // 后台跑：3s 轮询 /leads，total 涨了或满 10 次（30s）就停
      ElMessage.info(t('adm.bgRefreshing'))
      let n = 0
      if (_leadsTimer) clearInterval(_leadsTimer)
      _leadsTimer = setInterval(async () => {
        n++
        let stop = n >= 10
        try { const lr = await GET('/leads'); if ((lr.total || 0) > baseTotal) stop = true }
        catch { stop = true }
        if (stop) { clearInterval(_leadsTimer); _leadsTimer = null; opLoading.value = false; await loadLeads() }
      }, 3000)
      return
    }
  } catch (e) { ElMessage.error(e.message || t('common.fail')) }
  opLoading.value = false
}
let _leadsTimer = null
const exportLeadsBusy = ref(false)
const exportLeads = async () => {
  if (exportLeadsBusy.value) return
  exportLeadsBusy.value = true
  try { await downloadFile('/leads/export') }
  catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  exportLeadsBusy.value = false
}
const subscribeLeads = async (pageIds = null) => {
  opLoading.value = true
  try {
    const r = await POST('/leads/subscribe', pageIds ? { page_ids: pageIds } : {})
    if (r.error) { ElMessage.error(t('adm.leadsErr', { msg: r.error })) }
    else {
      // 部分失败时带第一条原因（0/N 时用户第一问就是"为什么"——FB 原文最有用）
      const fail = (r.pages || []).find(p => p && p.ok === false && p.error)
      const base = t('adm.leadsSubscribed', { ok: r.subscribed || 0, n: r.total_pages || 0 })
      if ((r.subscribed || 0) < (r.total_pages || 0) && fail) ElMessage.warning(`${base} · ${fail.page_name || fail.page_id}: ${fail.error}`)
      else ElMessage.success(base)
      if (pagesDlg.value) loadLeadPages()   // 面板开着 → 刷新订阅实况
    }
  } catch (e) { ElMessage.error(e.message || t('common.fail')) }
  opLoading.value = false
}
// 主页受控面板：页清单+权限面+订阅实况（哪些页真的在掌控中——权限是 FB 侧角色，OAuth 复制不了）
const pagesDlg = ref(false)
const leadPages = ref([])
const pagesLoading = ref(false)
const pageSel = ref(new Set())
const loadLeadPages = async () => {
  pagesLoading.value = true
  try {
    const r = await GET('/leads/pages')
    leadPages.value = r.pages || []
    pageSel.value = new Set(leadPages.value.filter(p => p.can_manage && p.subscribed !== true).map(p => p.page_id))
  } catch (e) { ElMessage.error(e.message || t('common.fail')) }
  pagesLoading.value = false
}
const openPagesPanel = () => { pagesDlg.value = true; loadLeadPages() }
const togglePage = (pid) => { const s = new Set(pageSel.value); s.has(pid) ? s.delete(pid) : s.add(pid); pageSel.value = s }
const subscribeSelected = () => subscribeLeads([...pageSel.value])
const purgeStalePages = async () => {
  try {
    await ElMessageBox.confirm(t('adm.purgeStaleConfirm'), t('adm.pagesPanelTitle'), { type: 'warning', confirmButtonText: t('common.confirm') })
  } catch { return }
  opLoading.value = true
  try {
    const r = await POST('/leads/purge-stale-pages')
    ElMessage.success(t('adm.purgeStaleDone', { leads: r.leads_deleted || 0, tpls: r.templates_archived || 0 }))
    loadLeads(); loadLeadPages()
  } catch (e) { ElMessage.error(e.message || t('common.fail')) }
  opLoading.value = false
}
const unsubscribeLeads = async () => {
  try { await ElMessageBox.confirm(t('adm.leadsUnsubConfirm'), t('common.confirm'), { type: 'warning' }) }
  catch { return }
  opLoading.value = true
  try {
    const r = await POST('/leads/unsubscribe')
    if (r.error) { ElMessage.error(t('adm.leadsErr', { msg: r.error })) }
    else ElMessage.success(t('adm.leadsUnsubscribed', { ok: r.unsubscribed || 0, n: r.total_pages || 0 }))
  } catch (e) { ElMessage.error(e.message || t('common.fail')) }
  opLoading.value = false
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="ph-left">
        <h1 class="ph-title">{{ t('adm.pageTitle') }}</h1>
        <span v-if="currentAccountName" class="ph-fresh">{{ currentAccountName }}</span>
      </div>
      <div class="ph-actions">
        <button class="head-btn primary" :disabled="loading || (tab === 'lead' && leadsLoading)" :title="t('adm.refreshTip')" @click="tab === 'lead' ? loadLeads() : load(true)">{{ (tab === 'lead' ? leadsLoading : loading) ? t('common.loading') + '…' : t('common.refresh') }}</button>
      </div>
    </header>
    <!-- 警示条归组：账户状态横幅 + 死令牌横幅相邻（都在工具条上方，间距统一） -->
    <div v-if="selectedActs.length === 1 && accStateTag({ act_id: selectedActs[0] })" :class="['acc-warn-bar', accStateTag({ act_id: selectedActs[0] }).cls]">
          {{ accStateTag({ act_id: selectedActs[0] }).cls === 'banned' ? t('adm.accBannedBanner') : t('adm.accUnmanagedBanner') }}
        </div>
    <div v-if="tab !== 'lead' && deadAccounts.length" class="dead-acc-bar" :title="t('adm.tokenDeadTip')">
      ⚠ {{ t('adm.tokenDeadBar', { n: deadAccounts.length }) }}
    </div>
        <div class="ctrl-bar">
      <!-- 工具条顺序照 FB Ads Manager：＋创建 → 账户 → 日期 → 筛选 → 搜索 → 列 → 核验 → 其它（跳转链接）→ 缓存龄 -->
      <button class="ctrl-btn create-btn" @click="router.push({ name: 'launch-templates' })">＋ {{ t('adm.createAd') }}</button>
      <el-select v-if="tab !== 'lead'" v-model="selectedActs" multiple filterable collapse-tags collapse-tags-tooltip clearable :placeholder="t('adm.allAccounts')" class="act-filter" style="width:180px">
        <template #label="{ label, value }">
          <span v-if="platChipOf(value)" :class="['plat-chip', platChipOf(value)]">{{ platChipOf(value).toUpperCase() }}</span>{{ label }}
        </template>
        <el-option v-for="a in platAccounts" :key="a.act_id" :value="a.act_id" :label="(accStateTag(a) ? accStateTag(a).label + ' ' : '') + a.name">
          <span v-if="platChip(a)" :class="['plat-chip', platChip(a)]">{{ platChip(a).toUpperCase() }}</span>{{ a.name }}
          <span v-if="accStateTag(a)" :class="['mini-tag', accStateTag(a).cls]">{{ accStateTag(a).label }}</span>
        </el-option>
      </el-select>
      <DatePresetBar v-if="tab !== 'lead'" :presets="DATE_PRESETS" v-model="datePreset" @preset="() => { showCustom = false; load() }" @custom="({from,to}) => { customFrom = from; customTo = to; showCustom = true; load() }" />
      <div v-if="tab !== 'lead'" class="sf-group"><button class="ctrl-btn sm" :class="{ on: statusFilter === 'all' }" @click="statusFilter = 'all'">{{ t('common.all') }}</button><button class="ctrl-btn sm" :class="{ on: statusFilter === 'active' }" @click="statusFilter = 'active'">{{ t('adm.active') }}</button><button class="ctrl-btn sm" :class="{ on: statusFilter === 'idle' }" @click="statusFilter = 'idle'" :title="t('adm.filterIdleTip')">{{ t('status.adIdle') }}</button><button class="ctrl-btn sm" :class="{ on: statusFilter === 'paused' }" @click="statusFilter = 'paused'">{{ t('adm.paused') }}</button><button class="ctrl-btn sm" :class="{ on: statusFilter === 'abnormal' }" @click="statusFilter = 'abnormal'" :title="t('adm.filterAbnormalTip')">{{ t('adm.filterAbnormal') }}</button></div>
      <input v-if="tab !== 'lead'" v-model="searchQ" class="ctrl-btn search-input" :placeholder="t('adm.searchContext')" />
      <el-popover v-if="tab !== 'lead'" trigger="click" width="250" placement="bottom-end">
        <template #reference><button class="ctrl-btn">{{ t('adm.columns') }}</button></template>
        <el-checkbox-group v-model="viewPrefs[tab].columns" class="column-options">
          <el-checkbox v-for="col in availableColumns" :key="col.id" :value="col.id">{{ t('adm.' + col.label) }}</el-checkbox>
        </el-checkbox-group>
      </el-popover>
      <button v-if="tab !== 'lead'" class="ctrl-btn" :disabled="liveVerifying" @click="verifyLive" :title="t('adm.liveVerifyTip')">{{ liveVerifying ? t('adm.liveVerifying') : t('adm.liveVerify') }}</button>
      <span v-if="liveVerifiedAt && tab !== 'lead'" class="cache-at live-ok">{{ t('adm.liveVerifiedAt', { time: liveVerifiedAt }) }}</span>
      <button v-if="tab !== 'lead'" class="ctrl-btn" @click="openRedirectMgmt">{{ t('adm.redirectLink') }}<span v-if="Object.keys(redirectMap).length" class="rd-badge">{{ Object.keys(redirectMap).length }}</span></button>
      <span v-if="tab !== 'lead'" class="cache-at" :class="{ stale: cacheAgeStale }" :title="(cacheAgeStale ? t('adm.cacheAdsStaleTip') : t('adm.cacheAgeTip')) + (data.cached_at ? '\n' + t('adm.dataAsOf', { t: fmtTime(data.cached_at) }) : '')">{{ cacheAgeText }}</span>
    </div>
    <div v-if="loadError" class="page-error-bar">
      ⚠ {{ t('adm.loadFailed') }}：{{ loadError }}
      <button class="ctrl-btn sm" @click="load()">{{ t('common.retry') }}</button>
    </div>
    <transition name="slide">
      <div v-if="selected.size" class="batch-bar">
        <span class="batch-count">{{ t('adm.selectedCount', { n: selected.size }) }}</span>
        <button class="ctrl-btn sm" @click="selectAll">{{ t('adm.selectAll') }}</button>
        <button class="ctrl-btn sm" @click="batchStatus('ACTIVE')" :disabled="opLoading">{{ t('adm.batchActivate') }}</button>
        <button class="ctrl-btn sm" @click="batchStatus('PAUSED')" :disabled="opLoading">{{ t('adm.batchPause') }}</button>
        <button class="ctrl-btn sm ghost" @click="selected = new Set()">{{ t('adm.clearSelection') }}</button>
      </div>
    </transition>
    <details v-if="batchResults.length" class="batch-results" open>
      <summary>{{ t('adm.operationResults') }}</summary>
      <div v-for="(result, i) in batchResults" :key="i">{{ result.node_id }} · {{ t(!result.success ? 'adm.failed' : result.verified === false || result.warning ? 'adm.unverified' : 'adm.verified') }} <span>{{ result.error || result.warning || '' }}</span></div>
    </details>
    <div class="tabs">
      <div :class="['tab', { on: tab === 'campaign' }]" @click="tab = 'campaign'; clearDrill(); selected = new Set()">{{ t('adm.tabCampaign') }}</div>
      <div :class="['tab', { on: tab === 'adset' }]" @click="tab = 'adset'; selected = new Set()">{{ t('adm.tabAdset') }}</div>
      <div :class="['tab', { on: tab === 'ad' }]" @click="tab = 'ad'; selected = new Set()">{{ t('adm.tabAd') }}</div>
      <div :class="['tab', { on: tab === 'lead' }]" @click="switchLeadTab">{{ t('adm.tabLead') }}</div>
      <span v-if="platform !== 'all'" :class="['scope-chip', platform]">{{ platform === 'fb' ? 'Facebook' : 'TikTok' }} · {{ t('adm.scopeAccounts', { n: platAccounts.length }) }}</span>
    </div>
    <div v-if="tab !== 'lead'" class="manager-tools">
      <nav class="breadcrumbs" :aria-label="t('adm.pageTitle')">
        <button class="ctrl-btn sm" @click="tab = 'campaign'; clearDrill()">{{ t('adm.allCampaigns') }}</button>
        <template v-if="drillCampaign"><span>›</span><button class="ctrl-btn sm" @click="tab = 'adset'; drillAdset = ''">{{ campaignCrumb }}</button></template>
        <template v-if="drillAdset"><span>›</span><span>{{ adsetCrumb }}</span><span class="crumb-x" @click="clearDrill" :title="t('adm.clearDrill')">✕</span></template>
      </nav>
    </div>
    <div class="tbl" v-if="tab !== 'lead'" v-loading="loading">
      <table class="manager-table" :style="{ minWidth: tableWidth + 'px' }">
        <thead><tr>
          <th class="select-cell"><input type="checkbox" :aria-label="t('adm.selectAll')" :checked="allSelected" @change="selectAll" /></th>
          <th class="status-col"><button class="sort-button" @click="sortBy('_status_rank')">{{ t('common.status') }} {{ sortIcon('_status_rank') }}</button></th>
          <th class="name-col"><button class="sort-button" @click="sortBy('name')">{{ t(tab === 'campaign' ? 'adm.colSeries' : tab === 'adset' ? 'adm.colAdset' : 'adm.tabAd') }} {{ sortIcon('name') }}</button></th>
          <th v-for="col in visibleColumns" :key="col.id" :style="{ width: col.width + 'px' }"><button class="sort-button" :disabled="!col.sort" @click="col.sort && sortBy(col.sort)">{{ t('adm.' + col.label) }} {{ ['spend','cpa','cost_per_result','budget'].includes(col.id) ? '(' + viewCur + ')' : '' }} {{ sortIcon(col.sort) }}</button></th>
          <th class="action-col">{{ t('adm.actions') }}</th>
        </tr></thead>
        <tbody>
          <template v-for="a in curList" :key="entityKey(a)">
            <tr :class="{ sel: isSelected(entityKey(a)) }">
              <td><input type="checkbox" :checked="isSelected(entityKey(a))" :aria-label="a.name || String(a.id)" @change="toggleSelect(entityKey(a))" /></td>
              <td><div class="status-cell" :title="stIdleTitle(a, tab)">
                <div class="st-line1"><el-switch :model-value="effectiveStatusOf(a, tab) === 'ACTIVE'" size="small" @change="toggleStatus(a)" :disabled="opLoading || !!accStateTag(a)" /><span :class="['st-badge', statusDot(effectiveStatusOf(a, tab))]">{{ statusLabel(effectiveStatusOf(a, tab)) }}</span></div>
                <span v-if="accStateTag(a)" :class="['acc-state-tag', accStateTag(a).cls]" :title="accStateTag(a).cls === 'banned' ? t('adm.accBannedTip') : t('adm.accUnmanagedTip')">{{ accStateTag(a).label }}</span>
              </div></td>
              <td><div class="ad-nm">
                <button v-if="tab === 'ad'" class="preview-button" :title="t('adm.thumbTitle')" @click="showThumb(a)"><img v-if="thumbOf(a)" :src="thumbOf(a)" class="ad-thumb" :alt="t('adm.thumbTitle')" @error="nextThumb(a)" /><span v-else class="ad-thumb ph">{{ t('adm.thumbNoneShort') }}</span></button>
                <div class="txt"><button class="entity-name" @click="tab === 'campaign' ? drillToAdset(a) : tab === 'adset' ? drillToAd(a) : showThumb(a)">{{ a.name }}</button>
                  <div class="sid">{{ a.account_name }} · {{ a.id }}</div>
                  <div v-if="tab !== 'campaign'" class="sid">{{ contextOf(a).campaign?.name }}<template v-if="tab === 'ad' && contextOf(a).adset"> › {{ contextOf(a).adset.name }}</template></div>
                  <div v-if="snapshotStale(a) || accDead(a)" class="sid" :class="{ 'stale-snapshot': snapshotStale(a) }" :title="a.snapshot_at ? t('adm.metricsAt', { time: fmtTime(a.snapshot_at) }) : ''">{{ snapshotText(a) }}</div>
                  <span v-if="tab === 'ad' && redirectMap[a.id]" class="rd-mark" @click="openRedirect(a)">{{ t('adm.redirectShort') }}</span>
                </div>
              </div></td>
              <td v-for="col in visibleColumns" :key="col.id">
                <button v-if="col.id === 'budget'" class="budget-cell sort-button" :disabled="!hasBudget(a) || !!accStateTag(a) || opLoading" @click="openBudget(a)">{{ fmtBudget(a, tab) }}</button>
                <code v-else-if="col.id === 'slug' && a.slug" class="ad-slug" @click="goLandingLogs(a.slug, a.id)">/a/{{ a.slug }}</code>
                <span v-else :title="col.id === 'results_fb' && fbResult(a) == null ? fbTip(a) : ''">{{ metricText(a, col.id) }}</span>
              </td>
              <td><el-dropdown trigger="click" @command="cmd => onAction(cmd, a)" placement="bottom-end"><button class="more-btn" :aria-label="t('adm.actions')" :disabled="opLoading">···</button><template #dropdown><el-dropdown-menu>
                <el-dropdown-item command="toggle" :disabled="!!accStateTag(a)">{{ a.effective_status === 'ACTIVE' ? t('adm.paused') : t('adm.activate') }}</el-dropdown-item>
                <el-dropdown-item command="rename" :disabled="!!accStateTag(a)">{{ t('adm.rename') }}</el-dropdown-item>
                <el-dropdown-item v-if="hasBudget(a)" command="budget" :disabled="!!accStateTag(a)">{{ t('adm.editBudget') }}</el-dropdown-item>
                <template v-if="tab === 'ad'"><el-dropdown-item command="redirect">{{ t('adm.redirectLink') }}</el-dropdown-item><el-dropdown-item command="logs">{{ t('adm.viewLandingLogs') }}</el-dropdown-item><el-dropdown-item command="diagnose">{{ t('adm.adDiagnose') }}</el-dropdown-item><el-dropdown-item v-if="a.platform !== 'tt'" command="breakdown">{{ t('adm.breakdown') }}</el-dropdown-item><el-dropdown-item v-if="a.object_story_id" command="reuse">{{ t('adm.reuseThisPost') }}</el-dropdown-item></template>
                <el-dropdown-item command="delete" :disabled="!!accStateTag(a)" divided>{{ t('common.delete') }}</el-dropdown-item>
              </el-dropdown-menu></template></el-dropdown></td>
            </tr>
            <tr v-if="budgetDialog && budgetTarget?.node_id === a.id && budgetTarget?.act_id === a.act_id"><td :colspan="visibleColumns.length + 4">
              <form class="inline-budget" @submit.prevent="saveBudget" @keydown.esc="!opLoading && (budgetDialog = false)">
                <label>{{ budgetTarget.budget_type === 'lifetime' ? t('adm.lifetimeBudgetLabel') : t('adm.dailyBudgetLabel') }} ({{ budgetTarget.currency }})
                  <input v-model.number="budgetInput" type="number" min="0.01" step="0.01" class="budget-input" :placeholder="String(budgetTarget.old_value)" :disabled="opLoading" required /></label>
                <button type="submit" class="ctrl-btn primary" :disabled="opLoading">{{ t('common.save') }}</button><button type="button" class="ctrl-btn" :disabled="opLoading" @click="budgetDialog = false">{{ t('common.cancel') }}</button>
              </form>
            </td></tr>
          </template>
        </tbody>
        <tfoot v-if="curList.length"><tr><td></td><td></td><td>{{ totalLabel }}</td><td v-for="col in visibleColumns" :key="col.id">{{ sumMetric(col.id) }}</td><td></td></tr></tfoot>
      </table>
      <div v-if="!curList.length && !loading && !loadError" class="empty">{{ t('adm.emptyAdsHint') }}<button class="btn primary" style="margin-top:10px" @click="router.push({ name: 'launch-templates' })">+ {{ t('launch.newTemplate') }}</button></div>
    </div>
    <div v-if="tab === 'lead'" class="leads-panel">
      <div class="leads-bar">
        <span class="rd-cnt">{{ t('adm.leadsCount', { n: leads.length }) }}</span>
        <div class="sf-group">
          <button v-for="s in ['all', ...LEAD_STATUSES]" :key="s" class="ctrl-btn sm" :class="{ on: leadStatusFilter === s }" @click="leadStatusFilter = s; loadLeads()">{{ leadStatusFilterLabel(s) }}</button>
        </div>
        <button class="ctrl-btn sm" :disabled="opLoading" @click="syncLeads">⟳ {{ t('adm.leadsSync') }}</button>
        <button class="ctrl-btn sm" :disabled="!leads.length" @click="exportLeads">⬇ {{ t('common.exportCsv') }}</button>
        <!-- 订阅管理类操作收进 ⋯（批M：主栏只留数据操作） -->
        <el-dropdown trigger="click" :disabled="opLoading" @command="cmd => cmd === 'pages' ? openPagesPanel() : cmd === 'sub' ? subscribeLeads() : cmd === 'unsub' ? unsubscribeLeads() : purgeStalePages()">
          <button class="ctrl-btn sm">⋯</button>
          <template #dropdown><el-dropdown-menu>
            <el-dropdown-item command="pages">{{ t('adm.pagesPanelBtn') }}</el-dropdown-item>
            <el-dropdown-item command="sub">{{ t('adm.leadsSubscribe') }}</el-dropdown-item>
            <el-dropdown-item command="unsub">{{ t('adm.leadsUnsubscribe') }}</el-dropdown-item>
            <el-dropdown-item command="purge" divided>{{ t('adm.purgeStaleBtn') }}</el-dropdown-item>
          </el-dropdown-menu></template>
        </el-dropdown>
      </div>
      <div class="tbl" v-loading="leadsLoading">
        <div class="row head lead-row"><div>{{ t('adm.lcolTime') }}</div><div>{{ t('adm.lcolName') }}</div><div>{{ t('adm.lcolEmail') }}</div><div>{{ t('adm.lcolPhone') }}</div><div>{{ t('adm.lcolSource') }}</div><div>{{ t('adm.lcolStatus') }}</div><div>{{ t('adm.lcolNote') }}</div><div>{{ t('adm.lcolDetail') }}</div></div>
        <div v-for="l in leads" :key="l.lead_id" class="row lead-row">
          <div class="ld-time">{{ fmtLeadTime(l.created_time) }}</div>
          <div class="ld-name">{{ leadField(l, ['full_name', 'first_name', 'last_name']) || '-' }}</div>
          <div class="ld-email">{{ leadField(l, ['email', 'work_email']) || '-' }}</div>
          <div>{{ leadField(l, ['phone_number', 'phone', 'work_phone_number']) || '-' }}</div>
          <div class="ld-src"><code v-if="l.ad_id">{{ l.ad_id }}</code><span v-else-if="l.form_id" class="muted">form …{{ String(l.form_id).slice(-6) }}</span><span v-else class="muted">-</span></div>
          <div class="ld-status">
            <el-dropdown trigger="click" :disabled="opLoading" @command="cmd => setLeadStatus(l, cmd)" placement="bottom-start">
              <span :class="['ld-st-tag', l.status || 'new']">{{ leadStatusLabel(l.status) }} ▾</span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-for="s in LEAD_STATUSES" :key="s" :command="s"><span :class="['ld-st-dot', s]"></span>{{ LEAD_STATUS_LABEL[s] }}<span v-if="(l.status || 'new') === s" class="ld-st-cur">✓</span></el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <div class="ld-note"><span v-if="l.note" class="ld-note-txt" :title="l.note">{{ l.note }}</span><button class="ld-note-btn" :title="t('adm.lcolNote')" @click="editLeadNote(l)">✎</button></div>
          <div class="ld-extra"><span v-for="[k, v] in leadExtra(l)" :key="k" class="ld-chip">{{ fieldLabel(k) }}: {{ v }}</span></div>
        </div>
        <div v-if="!leads.length && !leadsLoading" class="empty">{{ t('adm.leadsEmpty') }}</div>
      </div>
    </div>
    <el-dialog v-model="pagesDlg" :title="t('adm.pagesPanelTitle')" width="640px" :destroy-on-close="true" append-to-body>
      <div v-loading="pagesLoading" class="pages-panel">
        <div class="pp-hint">{{ t('adm.pagesPanelHint') }}</div>
        <div class="pp-row pp-head"><div></div><div>{{ t('adm.ppColPage') }}</div><div>{{ t('adm.ppColPerm') }}</div><div>{{ t('adm.ppColSub') }}</div></div>
        <div v-for="p in leadPages" :key="p.page_id" class="pp-row">
          <input type="checkbox" :checked="pageSel.has(p.page_id)" :disabled="!p.can_manage" @change="togglePage(p.page_id)" :title="p.can_manage ? '' : t('adm.ppNoManage')" />
          <div class="pp-name">{{ p.page_name }}<div class="sid">{{ p.alias }} · {{ p.page_id }}</div></div>
          <div><span v-if="p.can_manage" class="pp-tag ok">{{ t('adm.ppManage') }}</span><span v-else-if="p.can_advertise" class="pp-tag mid" :title="t('adm.ppAdvertiseTip')">{{ t('adm.ppAdvertise') }}</span><span v-else class="pp-tag low" :title="t('adm.ppViewTip')">{{ t('adm.ppView') }}</span></div>
          <div><span v-if="p.subscribed === true" class="pp-tag ok">✓ {{ t('adm.ppSubscribed') }}</span><span v-else-if="p.subscribed === false" class="muted">—</span><span v-else class="muted">?</span></div>
        </div>
        <div v-if="!leadPages.length && !pagesLoading" class="empty">{{ t('adm.ppEmpty') }}</div>
      </div>
      <template #footer>
        <button class="ctrl-btn" :disabled="pagesLoading" @click="loadLeadPages">⟳ {{ t('common.refresh') }}</button>
        <button class="ctrl-btn" :disabled="opLoading || !pageSel.size" @click="subscribeSelected">{{ t('adm.ppSubscribeSelected', { n: pageSel.size }) }}</button>
        <button class="ctrl-btn" style="color: var(--error)" :disabled="opLoading" @click="purgeStalePages">{{ t('adm.purgeStaleBtn') }}</button>
      </template>
    </el-dialog>

    <el-dialog v-model="redirectDialog" :title="t('adm.redirectDialogTitle', { name: redirectTarget?.name || '' })" width="440px" :close-on-click-modal="false" :destroy-on-close="true" append-to-body>
      <div class="rd-form">
        <label>{{ t('adm.redirectFormLabel') }}</label>
        <input v-model.trim="redirectInput" class="budget-input" :placeholder="t('adm.redirectInputPh')" />
        <div class="rd-hint">{{ t('adm.redirectHint') }}</div>
      </div>
      <template #footer>
        <button class="ctrl-btn" :disabled="redirectSaving" @click="redirectDialog = false">{{ t('common.cancel') }}</button>
        <button v-if="redirectMap[redirectTarget?.id]" class="ctrl-btn" :disabled="redirectSaving" @click="redirectInput=''; saveRedirect()">{{ t('adm.restoreDefault') }}</button>
        <button class="ctrl-btn primary" :disabled="redirectSaving" @click="saveRedirect">{{ redirectSaving ? t('common.saving') + '…' : t('common.save') }}</button>
      </template>
    </el-dialog>

    <el-dialog v-model="redirectMgmtOpen" :title="t('adm.redirectMgmtTitle')" width="640px" :destroy-on-close="true" append-to-body>
      <div class="rd-mgmt-bar">
        <span class="rd-cnt">{{ t('adm.redirectMgmtCount', { n: redirectList.length }) }}</span>
        <button class="ctrl-btn sm" :disabled="!redirectList.length" @click="resetRedirects">{{ t('adm.restoreAllDefault') }}</button>
      </div>
      <div class="rd-mgmt-list" v-loading="mgmtLoading">
        <div v-for="r in redirectList" :key="r.ad_id" class="rd-mgmt-row">
          <div class="rd-mid-wrap">
            <code class="rd-mid" title="ad_id">{{ r.ad_id }}</code>
            <span class="rd-mhost">{{ hostOf(r.target_url) }}</span>
          </div>
          <span class="rd-murl" :title="r.target_url">{{ r.target_url }}</span>
          <button class="ctrl-btn sm" :disabled="opLoading" @click="removeRedirect(r.ad_id)">{{ t('common.remove') }}</button>
        </div>
        <div v-if="!redirectList.length" class="empty" style="padding:30px">{{ t('adm.redirectMgmtEmpty') }}</div>
      </div>
    </el-dialog>

    <el-dialog v-model="breakdownOpen" :title="t('adm.breakdownTitle', { name: breakdownTarget?.name || '' })" width="680px" :destroy-on-close="true" append-to-body>
      <div class="bd-bar">
        <div class="sf-group">
          <button v-for="d in BREAKDOWN_DIMS" :key="d.id" class="ctrl-btn sm" :class="{ on: breakdownDim === d.id }" @click="breakdownDim = d.id">{{ d.label }}</button>
        </div>
        <button class="ctrl-btn sm" :disabled="breakdownLoading" @click="loadBreakdown(true)">⟳ {{ t('common.refresh') }}</button>
      </div>
      <div class="tbl" v-loading="breakdownLoading">
        <table class="manager-table bd-table">
          <thead><tr>
            <th>{{ t('adm.breakdownDim') }}</th>
            <th>{{ t('adm.colSpend') }} ({{ breakdownTarget?.currency }})</th>
            <th>{{ t('adm.diagImpressions') }}</th>
            <th>{{ t('adm.diagClicks') }}</th>
            <th>{{ t('adm.ctrLabel') }}</th>
            <th>{{ t('adm.colReach') }}</th>
            <th>{{ t('adm.colFrequency') }}</th>
            <th>{{ t('adm.breakdownResults') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="(r, i) in breakdownRows" :key="i">
              <td>{{ breakdownDim === 'conversion_location' ? bdConvLabel(r.dimension_value) : bdLabel(r.dimension_value) }}</td>
              <td>{{ r.spend ? fmtAmount(r.spend, breakdownTarget?.currency) : '—' }}</td>
              <td>{{ r.impressions ? r.impressions.toLocaleString() : '—' }}</td>
              <td>{{ r.clicks ? r.clicks.toLocaleString() : '—' }}</td>
              <td>{{ r.ctr ? Number(r.ctr).toFixed(2) + '%' : '—' }}</td>
              <td>{{ r.reach ? r.reach.toLocaleString() : '—' }}</td>
              <td>{{ r.frequency ? Number(r.frequency).toFixed(2) : '—' }}</td>
              <td>{{ r.results ? r.results.toLocaleString() : '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!breakdownRows.length && !breakdownLoading" class="empty">{{ t('adm.breakdownEmpty') }}</div>
        <div v-if="breakdownDim === 'conversion_location' && breakdownRows.length" class="bd-note">{{ t('adm.breakdownConvNote') }}</div>
      </div>
    </el-dialog>

    <el-drawer v-model="diagOpen" :title="t('adm.adDiagnose')" direction="rtl" size="520px" :destroy-on-close="true">
      <div v-loading="diagLoading" class="diag-body">
        <template v-if="diagData">
          <div v-if="diagData.fb_error" class="diag-warn">⚠ {{ diagData.fb_error }}</div>
          <div class="diag-sec">
            <div class="diag-sec-title">{{ t('adm.diagBasicInfo') }}</div>
            <div class="diag-grid">
              <div><span class="dl">{{ t('adm.diagAccount') }}</span><span class="dv">{{ diagData.account_name }}</span></div>
              <div><span class="dl">{{ t('adm.diagAdId') }}</span><span class="dv">{{ diagData.ad_id }}</span></div>
              <div><span class="dl">{{ t('adm.colSubcode') }}</span><span class="dv">{{ diagData.subcode || t('adm.unbound') }}</span></div>
              <div><span class="dl">{{ t('adm.diagFbStatus') }}</span><span class="dv">{{ statusLabel(diagData.fb_status) }}</span></div>
            </div>
          </div>
          <div class="diag-sec">
            <div class="diag-sec-title">{{ t('adm.diagTodayData', { tz: diagData.account_timezone }) }}</div>
            <div class="diag-grid">
              <div><span class="dl">{{ t('adm.colSpend') }}</span><span class="dv">{{ diagData.spend_usd ? '$' + diagData.spend_usd : '—' }}</span></div>
              <div><span class="dl">{{ t('adm.diagImpressions') }}</span><span class="dv">{{ diagData.impressions || 0 }}</span></div>
              <div><span class="dl">{{ t('adm.diagClicks') }}</span><span class="dv">{{ diagData.clicks || 0 }}</span></div>
              <div><span class="dl">{{ t('adm.colReach') }}</span><span class="dv">{{ diagData.reach || 0 }}</span></div>
              <div><span class="dl">{{ t('adm.diagFbConv') }}</span><span class="dv">{{ diagData.fb_conversions }} <span class="dsub">{{ diagData.fb_kpi_source }}</span></span></div>
              <div><span class="dl">{{ t('adm.diagLandingClicks') }}</span><span class="dv">{{ diagData.landing_clicks }} <span class="dsub">{{ t('adm.dedupIp') }}</span></span></div>
              <div><span class="dl">{{ t('adm.diagLandingVisits') }}</span><span class="dv">{{ diagData.landing_visits }}</span></div>
              <div><span class="dl">{{ t('adm.diagEffectiveConv') }}</span><span class="dv hl">{{ diagData.effective_conversions }} <span class="dsub">{{ CS_ZH[diagData.conversion_source] || diagData.conversion_source }}</span></span></div>
            </div>
          </div>
          <div class="diag-sec" v-if="diagData.rules.length">
            <div class="diag-sec-title">{{ t('adm.diagRuleEval') }}</div>
            <div v-for="r in diagData.rules" :key="r.rule_id" class="diag-rule" :class="{ hit: r.hit }">
              <span class="rule-icon">{{ r.hit ? '' : '' }}</span>
              <div class="rule-info">
                <div class="rule-title">{{ r.rule_name }} <span class="rule-type">{{ RULE_ZH[r.rule_type] || r.rule_type }}</span></div>
                <div class="rule-detail" v-if="r.detail">{{ r.detail }}</div>
                <div class="rule-meta">
                  <span>CPA={{ r.cpa != null ? '$' + r.cpa : '—' }}</span>
                  <span>FB={{ r.fb_conversions }} {{ t('adm.colLandingShort') }}={{ r.landing_clicks }} {{ t('adm.effectiveShort') }}={{ r.effective_conversions }}</span>
                </div>
              </div>
            </div>
          </div>
          <div class="diag-sec" v-if="!diagData.rules.length && !diagData.fb_error">
            <div class="diag-empty">{{ t('adm.diagNoRules') }}</div>
          </div>
          <div class="diag-sec" v-if="diagData.cooldown">
            <div class="diag-sec-title">{{ t('adm.diagCooldown') }}</div>
            <div class="diag-cooldown">
              🔒 {{ t('adm.diagCooldownMsg', { rule: diagData.cooldown.rule, ago: Math.max(0, Math.round((Date.now() - new Date(diagData.cooldown.paused_at).getTime()) / 60000)), left: diagData.cooldown.remaining_min }) }}
            </div>
          </div>
          <div class="diag-sec" v-if="diagData.whitelisted">
            <div class="diag-warn" style="background:rgba(48,209,97,.08);color:var(--success)">✓ {{ t('adm.diagWhitelisted') }}</div>
          </div>
          <div class="diag-sec" v-if="diagData.recent_actions && diagData.recent_actions.length">
            <div class="diag-sec-title">{{ t('adm.diagRecentActions') }}</div>
            <div v-for="a in diagData.recent_actions" :key="a.time" class="diag-action">
              <span class="da-time">{{ a.time ? a.time.slice(5,19).replace('T',' ') : '' }}</span>
              <span class="da-type">{{ a.action }}</span>
              <span class="da-trigger">{{ a.trigger }}</span>
              <span class="da-result" :class="{ ok: a.result === 'success', fail: a.result === 'fail' }">{{ a.result }}</span>
            </div>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.ctrl-bar { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; margin-bottom: 10px }
.ctrl-btn { height: 32px; padding: 0 12px; line-height: 30px; font-size: 13px; background: var(--bg2); color: var(--t2); border: 1px solid var(--bd); border-radius: var(--rs); cursor: pointer; box-sizing: border-box; white-space: nowrap; transition: all .15s }
.ctrl-btn:hover { color: var(--t1); border-color: var(--bd2) }
.ctrl-btn.active { background: var(--acg); color: var(--ac); border-color: var(--ac); font-weight: 600 }
.ctrl-btn.apply { background: var(--ac); color: #fff; margin-left: 2px; padding: 0 8px }
.ctrl-btn.primary { background: var(--ac); color: #fff; border-color: var(--ac) }
.ctrl-btn.primary:hover { filter: brightness(1.08) }
.ctrl-btn.primary:disabled { opacity: .5; cursor: wait }
.ctrl-btn.sm { padding: 0 8px; font-size: 12px }
.ctrl-btn.ghost { background: transparent; color: var(--t3) }
.ctrl-btn.on { background: var(--acg); color: var(--ac); border-color: var(--ac); font-weight: 600 }
.search-input { width: 210px; text-align: left; color-scheme: dark }
.custom-range { display: flex; align-items: center; gap: 4px }
.date-input { height: 32px; padding: 0 8px; font-size: 13px; background: var(--bg3); color: var(--t1); border: 1px solid var(--bd); border-radius: var(--rs); color-scheme: dark; box-sizing: border-box }
.date-input:focus { outline: none; border-color: var(--ac) }
.sep { color: var(--t3); font-size: 12px }
.sf-group { display: flex; gap: 2px; margin-left: 4px }
.act-filter { flex-shrink: 0 }
.act-filter :deep(.el-input__wrapper) { height: 32px; min-height: 32px; border-radius: var(--rs); box-shadow: 0 0 0 1px var(--bd) inset; background: var(--bg2) }
.act-filter :deep(.el-input__inner) { height: 32px; line-height: 30px; font-size: 13px }
.slide-enter-active, .slide-leave-active { transition: all .2s }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateY(-8px) }
.batch-bar { display: flex; align-items: center; gap: 6px; padding: 6px 12px; margin-bottom: 8px; background: var(--bg2); border: 1px solid var(--ac); border-radius: var(--rs) }
.batch-count { font-size: 12px; color: var(--ac); font-weight: 600; margin-right: 4px }
.tabs { display: flex; flex-wrap: wrap; align-items: center; gap: 2px; margin-bottom: 8px; border-bottom: 1px solid var(--bd); padding-left: 4px }
.tab { padding: 6px 14px; font-size: 13px; color: var(--t3); cursor: pointer; border-bottom: 2px solid transparent }
.tab.on { color: var(--t1); border-bottom-color: var(--ac); font-weight: 600 }
.crumb-x { cursor: pointer; color: var(--t3); margin-left: 4px; font-size: 11px }
.crumb-x:hover { color: var(--t1) }
/* Tab 行右缘平台范围 chip（平台≠all 时显示，品牌色语境） */
.scope-chip { margin-left: auto; display: inline-flex; align-items: center; height: 20px; padding: 0 9px; border-radius: 10px; background: var(--bg3); color: var(--t2); font-size: 11px; white-space: nowrap }
.scope-chip.fb { background: rgba(24,119,242,.12); color: #5aa2ff }
.scope-chip.tt { background: rgba(254,44,85,.1); color: #ff6f8d }
.tbl { border: 1px solid var(--bd); border-radius: 8px; overflow-x: auto }
.row { display: grid; gap: 4px; padding: 5px 8px; align-items: center; font-size: 12px; border-bottom: 1px solid var(--bd); font-variant-numeric: tabular-nums }
.row.head { background: var(--bg2); color: var(--t3); font-size: 11px; font-weight: 600 }
.row:last-child { border-bottom: none }
.row.sel { background: rgba(10,132,255,.08); border-left: 2px solid var(--ac); padding-left: 6px }
.row:hover { background: var(--bg2) }
.row.sel:hover { background: rgba(10,132,255,.1) }
/* 表尾汇总行（sticky bottom：滚动容器内可滚时贴底，否则随表尾） */
.row.sum { position: sticky; bottom: 0; z-index: 2; background: var(--bg2); border-top: 1px solid var(--bd2); border-bottom: none }
.sum-label { font-size: 11px; color: var(--t3); font-weight: 600 }
.sum-val { font-weight: 600; color: var(--t1) }
.ops { display: flex; justify-content: flex-end }
.more-btn { width: 24px; height: 22px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t2); font-size: 13px; cursor: pointer; border-radius: 4px; padding: 0; line-height: 20px; text-align: center }
.more-btn:hover { background: var(--ac); color: #fff; border-color: var(--ac) }
.more-btn:disabled { opacity: .5; cursor: wait }
.nm { font-weight: 600; color: var(--t1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.nm.clk { cursor: pointer }
.nm.clk:hover { color: var(--ac) }
.sid { font-size: 10px; color: var(--t3); font-weight: 400 }
/* 平台小标用 main.css 全局 .plat-chip */
.lv { color: var(--ac); font-size: 11px; font-weight: 600 }
.lp { color: var(--ac); font-size: 11px; font-weight: 600 }
.lpr { color: var(--t2); font-size: 11px }
.slug-cell { overflow: hidden }
.ad-slug { color: var(--ac); font-size: 11px; font-family: monospace; cursor: pointer; white-space: nowrap }
.ad-slug:hover { text-decoration: underline }
.muted { color: var(--t3) }
.so { cursor: pointer; user-select: none }
.so:hover { color: var(--ac) }
.status-cell { display: flex; align-items: center; gap: 4px; font-size: 11px; white-space: nowrap }
.dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 4px; vertical-align: middle }
/* 批BW：状态徽章（替代 dot+裸文字——一格四元素挤成乱，改开关+徽章一行/账户tag换行） */
.status-cell { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; }
.st-line1 { display: flex; align-items: center; gap: 6px; }
.st-badge { display: inline-block; font-size: 11px; font-weight: 500; line-height: 1.5; padding: 1px 8px; border-radius: 5px; white-space: nowrap; }
.st-badge.ok { color: var(--success); background: rgba(52,199,89,.13) }
.st-badge.warn { color: var(--warning); background: rgba(255,159,10,.13) }
.st-badge.err { color: var(--error); background: rgba(255,69,58,.13) }
.st-badge.off { color: var(--t3); background: var(--bg3) }
.dot.ok { background: var(--success) } .dot.warn { background: var(--warning) } .dot.err { background: var(--error) } .dot.off { background: var(--t3); opacity: .4 }
.budget-cell { cursor: default }
.budget-cell.editable { cursor: pointer; color: var(--ac) }
.budget-cell.editable:hover { text-decoration: underline; text-decoration-style: dotted }
.empty { padding: 40px; text-align: center; color: var(--t3); font-size: 13px }
.budget-form { display: flex; flex-direction: column; gap: 8px }
.budget-form label { font-size: 12px; color: var(--t3) }
.budget-input { width: 100%; padding: 8px 12px; font-size: 18px; background: var(--bg3); color: var(--t1); border: 1px solid var(--bd); border-radius: 6px; box-sizing: border-box }
.budget-input:focus { outline: none; border-color: var(--ac) }
.quick-btns { display: flex; gap: 6px; margin-top: 4px }
.rd-mark { font-size: 10px; color: var(--ac); background: rgba(10,132,255,.12); padding: 1px 5px; border-radius: 4px; margin-left: 6px; font-weight: 400; vertical-align: middle }
.ad-thumb { width: 72px; height: 40px; border-radius: 6px; object-fit: cover; cursor: zoom-in; flex: none }
/* 无预览占位（FB 对归档广告不返回缩略图；个别 ACTIVE 也缺）——显式占位而非留空，布局一致 */
.ad-thumb.ph { display: flex; align-items: center; justify-content: center; background: var(--bd); color: var(--t3); font-size:10px   /* UI审计B：9px 中文笔画不可读 */; cursor: default; text-align: center; line-height: 1.3 }
/* 广告行创意优先：文案标题/正文各放开 2 行，广告名降为小字行（campaign/adset 的 .nm 不套 ad-nm） */
.ad-nm { display: flex; align-items: center; gap: 8px; min-width: 0 }
.ad-nm .txt { min-width: 0; flex: 1 }
.ad-nm .cpy { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden }
.ad-nm .cpy.tt { font-size: 12px; color: var(--t1) }
.ad-nm .cpy.bd { font-size: 11px; font-weight: 400; color: var(--t3); margin-top: 1px }
.ad-nm .an { font-size: 10px; color: var(--t3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 2px }
.rf-flag { color: var(--error); cursor: pointer; font-size: 11px; margin-left: 2px }
.rf-flag:hover { opacity: .8 }
.cache-at { font-size: 11px; color: var(--t3); white-space: nowrap; margin-left: 8px }
.cache-at.stale { color: var(--warning) }
/* 脱管/被禁账户视觉体系：行内标签 + 顶部警示条 */
.acc-state-tag { font-size: 10px; border-radius: 3px; padding: 0 5px; margin-left: 4px; line-height: 1.5; cursor: help; font-weight: 500; white-space: nowrap }
.acc-state-tag.unmanaged { color: var(--warning, #e6a700); border: 1px solid var(--warning, #e6a700); background: transparent }
.acc-state-tag.banned { color: var(--error, #f56c6c); border: 1px solid var(--error, #f56c6c); background: transparent }
.mini-tag { font-size: 10px; margin-left: 6px; padding: 0 4px; border-radius: 3px }
.mini-tag.unmanaged { color: var(--warning); border: 1px solid var(--warning) }
.mini-tag.banned { color: var(--error); border: 1px solid var(--error) }
.acc-warn-bar { padding: 8px 14px; border-radius: var(--rs); font-size: 13px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px }
.acc-warn-bar.unmanaged { background: rgba(230,167,0,0.08); border: 1px solid rgba(230,167,0,0.3); color: var(--warning, #e6a700) }
.acc-warn-bar.banned { background: rgba(245,108,108,0.08); border: 1px solid rgba(245,108,108,0.3); color: var(--error, #f56c6c) }

/* 数据源断链（无可用令牌）账户的快照态标注 */
.dead-acc-bar { margin: 0 0 6px; padding: 6px 10px; border-radius: 8px; font-size: 12px; color: var(--warning); background: color-mix(in srgb, var(--warning) 10%, transparent); border: 1px solid color-mix(in srgb, var(--warning) 35%, transparent) }
.snap-tag { font-size:10px   /* UI审计B：9px 中文笔画不可读 */; color: var(--t3); border: 1px solid var(--bd); border-radius: 3px; padding: 0 3px; margin-left: 4px; line-height: 1.4; cursor: help }
/* 主页受控面板（页权限 + 订阅实况） */
.pages-panel { max-height: 56vh; overflow-y: auto }
.pp-hint { font-size: 11px; color: var(--t3); margin-bottom: 8px; line-height: 1.5 }
.pp-row { display: grid; grid-template-columns: 22px 1fr 110px 90px; gap: 8px; align-items: center; padding: 6px 2px; border-bottom: 1px solid var(--bd) }
.pp-row.pp-head { font-size: 11px; color: var(--t3); border-bottom: 1px solid var(--bd) }
.pp-name { min-width: 0; font-weight: 600; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.pp-tag { font-size: 10px; border-radius: 3px; padding: 1px 5px; border: 1px solid var(--bd); white-space: nowrap }
.pp-tag.ok { color: var(--ok, #34c759); border-color: currentColor }
.pp-tag.mid { color: var(--warning) }
.pp-tag.low { color: var(--t3) }
.cache-at.live-ok { color: var(--success) }
.rd-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 15px; height: 15px; padding: 0 3px; margin-left: 5px; font-size: 10px; line-height: 1; background: var(--acg); color: var(--ac); border: 1px solid var(--ac); border-radius: 8px; vertical-align: middle; box-sizing: border-box }
.rd-form { display: flex; flex-direction: column; gap: 8px }
.rd-form label { font-size: 12px; color: var(--t3) }
.rd-hint { font-size: 11px; color: var(--t3); line-height: 1.5 }
.rd-mgmt-bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px }
.rd-cnt { font-size: 12px; color: var(--t2) }
.rd-mgmt-list { max-height: 380px; overflow-y: auto }
.rd-mgmt-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--bd); font-size: 12px }
.rd-mid-wrap { display: flex; flex-direction: column; gap: 2px; width: 150px; flex-shrink: 0 }
.rd-mid { color: var(--t3); font-size: 10px; letter-spacing: .2px; overflow: hidden; text-overflow: ellipsis }
.rd-mhost { color: var(--ac); font-size: 10px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.rd-murl { flex: 1; color: var(--ac); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px }
.diag-body { padding: 0 4px }
.diag-warn { padding: 10px 14px; background: rgba(255,159,10,.08); color: var(--warning); border-radius: 8px; font-size: 12px; line-height: 1.5; margin-bottom: 16px }
.diag-sec { margin-bottom: 20px }
.diag-sec-title { font-size: 13px; font-weight: 600; color: var(--t1); margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid var(--bd) }
.diag-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 16px }
.diag-grid > div { display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px }
.dl { color: var(--t3) }
.dv { color: var(--t1); font-variant-numeric: tabular-nums }
.dv.hl { color: var(--ac); font-weight: 600 }
.dsub { font-size: 10px; color: var(--t3); margin-left: 4px }
.diag-rule { display: flex; align-items: flex-start; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--bd) }
.diag-rule:last-child { border-bottom: none }
.diag-rule.hit { background: rgba(255,69,58,.04); border-radius: 6px; padding: 8px }
.rule-icon { font-size: 14px; line-height: 1.4 }
.rule-info { flex: 1 }
.rule-title { font-size: 13px; color: var(--t1); font-weight: 500 }
.rule-type { font-size: 10px; color: var(--t3); margin-left: 6px }
.rule-detail { font-size: 11px; color: var(--t2); margin-top: 2px }
.rule-meta { display: flex; gap: 12px; font-size: 10px; color: var(--t3); margin-top: 2px }
.diag-cooldown { padding: 10px 14px; background: rgba(10,132,255,.08); border-radius: 8px; font-size: 12px; color: var(--ac); line-height: 1.5 }
.diag-action { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 11px }
.da-time { color: var(--t3); width: 110px }
.da-type { color: var(--t1); width: 60px }
.da-trigger { color: var(--t2); flex: 1 }
.da-result { width: 50px; text-align: right }
.da-result.ok { color: var(--success) }
.da-result.fail { color: var(--error) }
.diag-empty { padding: 20px; text-align: center; color: var(--t3); font-size: 12px }
.leads-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap }
.leads-hint { font-size: 11px; color: var(--t3); margin-left: auto }
.lead-row { grid-template-columns: 1.3fr 1fr 1.4fr 1.1fr 1fr 0.95fr 1.4fr 1.5fr; min-width: 900px }
.ld-time { color: var(--t3); font-size: 11px; white-space: nowrap }
.ld-name { font-weight: 600; color: var(--t1) }
.ld-email { color: var(--ac); font-size: 11px; word-break: break-all }
.ld-src code { font-size: 11px; color: var(--t3) }
.ld-status { min-width: 0 }
.ld-st-tag { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; padding: 2px 8px; border-radius: 10px; cursor: pointer; white-space: nowrap; line-height: 1.5; border: none }
.ld-st-tag::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: currentColor; flex-shrink: 0 }
.ld-st-tag.new { color: var(--success); background: rgba(48, 209, 88, .1) }
.ld-st-tag.contacted { color: var(--ac); background: rgba(10, 132, 255, .1) }
.ld-st-tag.won { color: var(--warning); background: rgba(255, 214, 10, .1) }
.ld-st-tag.lost { color: var(--t2); background: var(--bg3) }
.ld-st-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 8px }
.ld-st-dot.new { background: var(--success) }
.ld-st-dot.contacted { background: var(--ac) }
.ld-st-dot.won { background: var(--warning) }
.ld-st-dot.lost { background: var(--t3) }
.ld-st-cur { margin-left: 8px; color: var(--ac) }
.ld-note { display: flex; align-items: center; gap: 6px; min-width: 0 }
.ld-note-txt { flex: 1; font-size: 11px; color: var(--t2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.ld-note-btn { flex-shrink: 0; border: none; background: none; color: var(--t3); cursor: pointer; font-size: 12px; padding: 2px; line-height: 1 }
.ld-note-btn:hover { color: var(--ac) }
.ld-extra { display: flex; flex-wrap: wrap; gap: 4px }
.ld-chip { font-size: 10px; color: var(--t2); background: var(--bg3); padding: 1px 6px; border-radius: 8px; white-space: nowrap }

/* UI审计D：页面级错误横幅——加载失败与空态区分 */
.page-error-bar { display: flex; align-items: center; gap: 10px; margin: 0 0 6px; padding: 6px 10px; border-radius: 8px; font-size: 12px; color: var(--error); background: color-mix(in srgb, var(--error) 8%, transparent); border: 1px solid color-mix(in srgb, var(--error) 30%, transparent) }

.manager-tools, .breadcrumbs, .inline-budget { display:flex; align-items:center; gap:10px; flex-wrap:wrap }
.manager-tools { justify-content:space-between; margin:12px 0 }
.column-options { display:flex; flex-direction:column }
.manager-table { width:100%; table-layout:fixed; border-collapse:collapse; font-size:12px }
.manager-table th, .manager-table td { padding:12px 10px; text-align:left; border-bottom:1px solid var(--bd); overflow-wrap:anywhere; vertical-align:middle }
.manager-table th { background:var(--bg2); color:var(--t2); font-weight:500 }
.manager-table .select-cell { width:30px }
.manager-table .status-col { width:190px }
.manager-table .name-col { width:300px }
.manager-table .action-col { width:60px }
.manager-table tr.sel { background:color-mix(in srgb,var(--ac) 8%,transparent) }
.manager-table tbody tr:hover { background:var(--bg2) }
.manager-table tfoot { background:var(--bg2); font-weight:600 }
.sort-button, .entity-name, .preview-button { border:0; background:transparent; color:inherit; padding:0; cursor:pointer; font:inherit; text-align:left }
.sort-button:disabled { cursor:default }
.entity-name { color:var(--t1); font-weight:500; overflow-wrap:anywhere }
.entity-name:hover { color:var(--ac); text-decoration:underline }
.preview-button { flex-shrink:0 }
.inline-budget { padding:8px; gap:12px }
.inline-budget label { display:flex; align-items:center; gap:12px }
.inline-budget input { width:180px }
.stale-snapshot { color:var(--warning, #b87917) }
/* 细分弹窗（年龄/性别/版位/转化位置维度表） */
.bd-bar { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px }
.bd-table td { padding:8px 10px; font-size:12px }
.bd-note { margin-top:8px; font-size:11px; color:var(--t3); line-height:1.5 }
/* FB 顶栏式工具条：绿色创建按钮（同 FB Ads Manager 主操作位） */
.ctrl-btn.create-btn { background:var(--ac); color:#fff; border-color:var(--ac); font-weight:600 }
.ctrl-btn.create-btn:hover { filter:brightness(1.06); color:#fff }
</style>
