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
const loading = ref(false)
const _loadGuard = useLatest()
const drillCampaign = ref('')
const drillAdset = ref('')
const statusFilter = ref('all')
const sortKey = ref('spend')
const sortDir = ref('desc')
const searchQ = ref('')

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

const cols = computed(() => tab.value === 'ad'
  ? '0.95fr 1.5fr 0.7fr 0.5fr 0.5fr 0.5fr 0.5fr 0.5fr 0.5fr 0.55fr 0.5fr 28px'
  : '0.95fr 1.5fr 0.6fr 0.65fr 0.6fr 0.5fr 0.5fr 0.6fr 0.5fr 28px')
const rowStyle = computed(() => ({ gridTemplateColumns: cols.value }))

const loadAccounts = async () => {
  try { accounts.value = await GET('/fb/accounts'); const q = route.query.act; if (q) selectedActs.value = [q]; await load(); await loadRedirectMap() }
  catch (e) { ElMessage.error(e.message || t('adm.loadAccountsFail')) }
}
const load = async (refresh = false) => {
  const isLatest = _loadGuard.next()
  loading.value = true
  try {
    const params = new URLSearchParams(curRange.value)
    if (refresh) params.set('refresh', '1')
    const r = await GET(`/ads/list?${params.toString()}`)
    if (!isLatest()) return   // 快速切日期/轮询完成回调并发时旧响应后到——丢弃
    data.value = r
    if (refresh) { drillCampaign.value = ''; drillAdset.value = '' }   // 只在用户主动刷新时清下钻——后台刷新完成自动 load 不踢用户出当前视图
    // 后台刷：立即返回了缓存 → 轮询 refresh-status，完成后自动更新列表
    if (refresh && data.value.refreshing) watchRefreshDone()
  }
  catch (e) { if (isLatest()) ElMessage.error(e.message || t('common.fail')) }
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
const statusMatch = (s) => statusFilter.value === 'all' ? true : (statusFilter.value === 'active' ? s === 'ACTIVE' : (s === 'PAUSED' || (s && s.includes('PAUSED'))))
const actMatch = (item) => !selectedActs.value.length ? true : selectedActs.value.includes(item.act_id)
// 平台切换器过滤（纯前端：accounts 带 platform 字段，实体行按所属账户过滤）
const { platform } = usePlatform()
const platAccounts = computed(() => platform.value === 'all' ? accounts.value : accounts.value.filter(a => (a.platform || 'fb') === platform.value))
const platActIds = computed(() => platform.value === 'all' ? null : new Set(platAccounts.value.map(a => a.act_id)))
const platMatch = (item) => { const ids = platActIds.value; return !ids || ids.has(item.act_id) }
watch(platform, () => {
  // 切平台：勾选账户里不属于新平台的清掉（防"选中永不匹配"空列表）
  if (platActIds.value) selectedActs.value = selectedActs.value.filter(id => platActIds.value.has(id))
})
const platChip = (a) => (a && (a.platform === 'tt' || a.platform === 'fb')) ? a.platform : ''
const platChipByAct = (actId) => {
  const a = accounts.value.find(x => x.act_id === actId)
  return platChip(a)
}
const sortBy = (key) => { if (sortKey.value === key) sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'; else { sortKey.value = key; sortDir.value = 'desc' } }
const _rankMap = { ACTIVE: 0, PAUSED: 1, CAMPAIGN_PAUSED: 2, ADSET_PAUSED: 3, PENDING_REVIEW: 4, WITH_ISSUES: 5, DISAPPROVED: 6, ARCHIVED: 7, DELETED: 8 }
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
const fmtSpendCol = (a) => mixedCur.value ? fmtMoney(a.spend_usd) : fmtAmount(a.spend, viewCur.value)
const fmtCpaCol = (a) => mixedCur.value ? (a.cpa_usd ? fmtMoney(a.cpa_usd) : '-') : (a.cpa ? fmtAmount(a.cpa, viewCur.value) : '-')

// 数据时间（ads_cache 最旧账户的 updated_at）超 1h 变橙提示
const cacheStale = computed(() => {
  const ts = data.value.cached_at ? new Date(data.value.cached_at).getTime() : NaN
  return !isNaN(ts) && (Date.now() - ts > 3600e3)
})

const curList = computed(() => {
  let arr
  if (tab.value === 'campaign') arr = data.value.campaigns || []
  else if (tab.value === 'adset') { arr = data.value.adsets || []; if (drillCampaign.value) arr = arr.filter(a => _idOf(a.campaign_id) === drillCampaign.value) }
  else { arr = data.value.ads || []; if (drillAdset.value) arr = arr.filter(a => _idOf(a.adset_id) === drillAdset.value) }
  arr = arr.filter(a => platMatch(a) && actMatch(a) && statusMatch(a.effective_status))
  if (searchQ.value.trim()) {
    const q = searchQ.value.trim().toLowerCase()
    arr = arr.filter(a => (a.name || '').toLowerCase().includes(q) || String(a.id || '').includes(q))
  }
  return arr.slice().sort((a, b) => {
    if (sortKey.value === '_status_rank') { const d = statusRank(a.effective_status) - statusRank(b.effective_status); return sortDir.value === 'desc' ? d : -d }
    // 用户主动选了排序列：该列为主排序，状态仅作同值兜底（否则"消耗降序"时 PAUSED 永远压底，找不到已停的高消耗）
    const _sk = (mixedCur.value && (sortKey.value === 'spend' || sortKey.value === 'cpa')) ? sortKey.value + '_usd' : sortKey.value
    let va = Number(a[_sk] || 0), vb = Number(b[_sk] || 0)
    if (va !== vb) return sortDir.value === 'desc' ? vb - va : va - vb
    return statusRank(a.effective_status) - statusRank(b.effective_status)
  })
})
const drillName = computed(() => {
  if (tab.value === 'adset' && drillCampaign.value) { const c = (data.value.campaigns || []).find(x => x.id === drillCampaign.value); return c ? t('adm.drillCampaign', { name: c.name }) : '' }
  if (tab.value === 'ad' && drillAdset.value) { const s = (data.value.adsets || []).find(x => x.id === drillAdset.value); return s ? t('adm.drillAdset', { name: s.name }) : '' }
  return ''
})
const drillToAdset = (c) => { drillCampaign.value = c.id; tab.value = 'adset'; if (c.act_id && !selectedActs.value.includes(c.act_id)) selectedActs.value = [c.act_id] }
const drillToAd = (s) => { drillAdset.value = s.id; tab.value = 'ad'; if (s.act_id && !selectedActs.value.includes(s.act_id)) selectedActs.value = [s.act_id] }
const clearDrill = () => { drillCampaign.value = ''; drillAdset.value = '' }
onMounted(loadAccounts)
onUnmounted(() => { if (_refreshPoller) { clearInterval(_refreshPoller); _refreshPoller = null }; if (_leadsTimer) { clearInterval(_leadsTimer); _leadsTimer = null } })

const selected = ref(new Set())
const opLoading = ref(false)
const budgetDialog = ref(false)
const budgetTarget = ref(null)
const budgetInput = ref(0)
// 广告级跳转链接覆盖
const redirectMap = ref({})           // {ad_id: target_url} 内联显示用
const redirectDialog = ref(false)     // 设单条
const redirectTarget = ref(null)      // {id, name}
const redirectInput = ref('')
const redirectMgmtOpen = ref(false)   // 管理列表
const redirectList = ref([])
const curLevel = () => tab.value === 'campaign' ? 'campaign' : (tab.value === 'adset' ? 'adset' : 'ad')

const toggleStatus = async (item) => {
  const ns = item.effective_status === 'ACTIVE' ? 'PAUSED' : 'ACTIVE'
  opLoading.value = true
  try { const r = await POST('/ads/status', { act_id: item.act_id, node_id: item.id, level: curLevel(), status: ns }); if (r.success) { item.effective_status = r.effective_status || ns; item.status = ns; ElMessage.success(ns === 'ACTIVE' ? t('adm.activated') : t('adm.paused')) } else ElMessage.error(r.error || t('common.opFail')) } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  opLoading.value = false
}
const openBudget = (item) => {
  const isLifetime = item.lifetime_budget_amount != null
  budgetTarget.value = { act_id: item.act_id, node_id: item.id, level: curLevel(), name: item.name, budget_type: isLifetime ? 'lifetime' : 'daily' }
  budgetInput.value = Number(item.lifetime_budget_amount ?? (item.daily_budget_amount || 0))
  budgetDialog.value = true
}
const saveBudget = async () => {
  if (!budgetInput.value || budgetInput.value <= 0) return ElMessage.warning(t('adm.budgetGtZero'))
  const bt = budgetTarget.value.budget_type
  const payload = { act_id: budgetTarget.value.act_id, node_id: budgetTarget.value.node_id, level: budgetTarget.value.level, budget_type: bt }
  payload[bt === 'lifetime' ? 'lifetime_budget' : 'daily_budget'] = budgetInput.value
  opLoading.value = true
  try {
    const r = await POST('/ads/budget', payload)
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
const budgetQuick = (m) => { budgetInput.value = Math.round(budgetInput.value * m * 100) / 100 }
const deleteItem = async (item) => {
  try {
    await ElMessageBox.confirm(t('adm.delConfirm', { name: item.name }), t('common.delConfirm'), { type: 'warning', confirmButtonText: t('common.delConfirm'), confirmButtonClass: 'el-button--danger' })
    opLoading.value = true
    try {
      await POST('/ads/delete', { act_id: item.act_id, node_id: item.id })
      ElMessage.success(t('adm.deleted')); await load()
    } catch (e) { ElMessage.error(e.message || t('common.opFail')) }   // 失败（无写令牌/FB 拒/并发锁）要告诉用户为什么
  } catch(e) { /* 用户取消 */ }
  opLoading.value = false
}
const batchStatus = async (status) => {
  if (!selected.value.size) return ElMessage.warning(t('adm.selectRowsFirst'))
  if (status === 'PAUSED') {
    try { await ElMessageBox.confirm(t('adm.batchPauseConfirm', { n: selected.value.size }), t('adm.batchPauseTitle'), { type: 'warning', confirmButtonText: t('adm.paused'), cancelButtonText: t('common.cancel'), confirmButtonClass: 'el-button--danger' }) }
    catch { return }
  }
  const items = []; for (const id of selected.value) { const it = curList.value.find(x => x.id === id); if (it) items.push({ act_id: it.act_id, node_id: it.id, level: curLevel(), status }) }
  opLoading.value = true
  try { const r = await POST('/ads/batch-status', { items }); ElMessage.success(t('adm.batchResult', { ok: r.success_count, n: items.length })); await load(); selected.value = new Set() } catch (e) { ElMessage.error(e.message || t('adm.batchOpFail')) }
  opLoading.value = false
}
// 创意缩略图 + 拒审原因（/ads/list 透传 FB creative.thumbnail_url / review_feedback，纯前端展示）
const thumbOf = (a) => a?.creative?.thumbnail_url || ''
const showThumb = (a) => {
  const u = thumbOf(a)
  if (!u) return
  ElMessageBox.alert(h('img', { src: u, style: 'width:100%;border-radius:8px;display:block' }), t('adm.thumbTitle'), { confirmButtonText: t('common.confirm') })
}
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
const onAction = (cmd, item) => { if (cmd === 'toggle') toggleStatus(item); else if (cmd === 'rename') renameItem(item); else if (cmd === 'budget') openBudget(item); else if (cmd === 'delete') deleteItem(item); else if (cmd === 'redirect') openRedirect(item); else if (cmd === 'logs') router.push({ name: 'landing', query: { tab: 'logs', ad_id: item.id } }); else if (cmd === 'diagnose') openDiagnose(item); else if (cmd === 'reuse') router.push({ name: 'launch-templates', query: { reuse_post: item.object_story_id } }) }

// 广告诊断
const diagOpen = ref(false)
const diagLoading = ref(false)
const diagData = ref(null)
const openDiagnose = async (item) => {
  diagOpen.value = true; diagLoading.value = true; diagData.value = null
  try { diagData.value = await GET('/ads/' + item.id + '/diagnose') }
  catch (e) { ElMessage.error(t('adm.diagFail', { msg: e.message || '' })) }
  diagLoading.value = false
}
const RULE_ZH = computed(() => ({ bleed_abs: t('adm.ruleBleedAbs'), cpa_exceed: t('adm.ruleCpaExceed'), consecutive_bad: t('adm.ruleConsecutiveBad'), click_no_conv: t('adm.ruleClickNoConv'), reach_no_conv: t('adm.ruleReachNoConv'), low_ctr_no_conv: t('adm.ruleLowCtrNoConv'), budget_burn_fast: t('adm.ruleBudgetBurnFast') }))
const CS_ZH = computed(() => ({ fb: t('adm.csFb'), landing: t('adm.csLanding'), either: t('adm.csEither') }))
const goLandingLogs = (slug, adId) => { router.push({ name: 'landing', query: { tab: 'logs', slug, ad_id: adId } }) }
const loadRedirectMap = async () => { try { redirectMap.value = await GET('/ads/redirects/map') } catch (e) {} }
const openRedirect = (item) => { redirectTarget.value = { id: item.id, name: item.name }; redirectInput.value = redirectMap.value[item.id] || ''; redirectDialog.value = true }
const saveRedirect = async () => {
  const adId = redirectTarget.value.id
  try { await POST('/ads/redirects', { ad_id: adId, target_url: redirectInput.value.trim() })
    if (redirectInput.value.trim()) { redirectMap.value = { ...redirectMap.value, [adId]: redirectInput.value.trim() } }
    else { const m = { ...redirectMap.value }; delete m[adId]; redirectMap.value = m }
    ElMessage.success(redirectInput.value.trim() ? t('adm.redirectSet') : t('adm.redirectRestored')); redirectDialog.value = false
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
}
const openRedirectMgmt = async () => { redirectMgmtOpen.value = true; try { redirectList.value = await GET('/ads/redirects') } catch (e) {} }
const removeRedirect = async (adId) => { try { await DELETE('/ads/redirects/' + adId); const m = { ...redirectMap.value }; delete m[adId]; redirectMap.value = m; redirectList.value = redirectList.value.filter(r => r.ad_id !== adId); ElMessage.success(t('adm.redirectRestored')) } catch (e) {} }
const resetRedirects = async () => {
  try { await ElMessageBox.confirm(t('adm.resetRedirectsMsg'), t('common.confirm'), { type: 'warning' })
    const r = await POST('/ads/redirects/reset', {}); redirectMap.value = {}; redirectList.value = []; ElMessage.success(t('adm.redirectsCleared', { n: r.cleared || 0 }))
  } catch (e) {}
}
const toggleSelect = (id) => { const s = new Set(selected.value); s.has(id) ? s.delete(id) : s.add(id); selected.value = s }
const selectAll = () => { selected.value = selected.value.size === curList.value.length ? new Set() : new Set(curList.value.map(x => x.id)) }
const isSelected = (id) => selected.value.has(id)

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
  leadsLoading.value = true
  try {
    const q = leadStatusFilter.value !== 'all' ? '?status=' + encodeURIComponent(leadStatusFilter.value) : ''
    const r = await GET('/leads' + q)
    leads.value = r.items || []
  }
  catch (e) { ElMessage.error(e.message || t('common.fail')) }
  leadsLoading.value = false
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
const subscribeLeads = async () => {
  opLoading.value = true
  try { const r = await POST('/leads/subscribe'); ElMessage.success(r.error ? t('adm.leadsErr', { msg: r.error }) : t('adm.leadsSubscribed', { ok: r.subscribed || 0, n: r.total_pages || 0 })) }
  catch (e) { ElMessage.error(e.message || t('common.fail')) }
  opLoading.value = false
}
</script>

<template>
  <div class="page">
    <div class="ctrl-bar">
      <DatePresetBar :presets="DATE_PRESETS" v-model="datePreset" @preset="() => { showCustom = false; load() }" @custom="({from,to}) => { customFrom = from; customTo = to; showCustom = true; load() }" />
      <el-select v-model="selectedActs" multiple filterable collapse-tags collapse-tags-tooltip clearable :placeholder="t('adm.allAccounts')" class="act-filter" style="width:180px"><el-option v-for="a in platAccounts" :key="a.act_id" :value="a.act_id" :label="(platChip(a) ? platChip(a).toUpperCase() + ' · ' : '') + a.name" /></el-select>
      <div class="sf-group"><button class="ctrl-btn sm" :class="{ on: statusFilter === 'all' }" @click="statusFilter = 'all'">{{ t('common.all') }}</button><button class="ctrl-btn sm" :class="{ on: statusFilter === 'active' }" @click="statusFilter = 'active'">{{ t('adm.active') }}</button><button class="ctrl-btn sm" :class="{ on: statusFilter === 'paused' }" @click="statusFilter = 'paused'">{{ t('adm.paused') }}</button></div>
      <input v-model="searchQ" class="ctrl-btn search-input" :placeholder="t('adm.searchNameId')" />
      <button class="ctrl-btn" @click="openRedirectMgmt">{{ t('adm.redirectLink') }}<span v-if="Object.keys(redirectMap).length" class="rd-badge">{{ Object.keys(redirectMap).length }}</span></button>
      <button class="ctrl-btn primary" :disabled="loading || (tab === 'lead' && leadsLoading)" @click="tab === 'lead' ? loadLeads() : load(true)" style="margin-left:auto">{{ (tab === 'lead' ? leadsLoading : loading) ? t('common.loading') + '…' : t('common.refresh') }}</button>
      <span v-if="data.cached_at" class="cache-at" :class="{ stale: cacheStale }" :title="cacheStale ? t('adm.cacheStaleTip') : ''">{{ t('adm.dataAsOf', { t: fmtTime(data.cached_at) }) }}</span>
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
    <div class="tabs">
      <div :class="['tab', { on: tab === 'campaign' }]" @click="tab = 'campaign'; clearDrill(); selected = new Set()">{{ t('adm.tabCampaign') }}</div>
      <div :class="['tab', { on: tab === 'adset' }]" @click="tab = 'adset'; selected = new Set()">{{ t('adm.tabAdset') }}</div>
      <div :class="['tab', { on: tab === 'ad' }]" @click="tab = 'ad'; selected = new Set()">{{ t('adm.tabAd') }}</div>
      <div :class="['tab', { on: tab === 'lead' }]" @click="switchLeadTab">{{ t('adm.tabLead') }}</div>
      <div v-if="drillName" class="drill-tag">{{ drillName }} <span @click="clearDrill">✕</span></div>
    </div>
    <div class="tbl" v-if="tab !== 'lead'" v-loading="loading">
      <template v-if="tab === 'campaign'">
        <div class="row head" :style="rowStyle"><div class="so" @click="sortBy('_status_rank')">{{ t('common.status') }}{{ sortIcon('_status_rank') }}</div><div>{{ t('adm.colSeries') }}</div><div>{{ t('adm.colObjective') }}</div><div class="so" @click="sortBy('daily_budget_amount')">{{ t('adm.colBudget') }}{{ sortIcon('daily_budget_amount') }}</div><div class="so" :title="mixedCur ? t('adm.mixedCurrencyTip') : ''" @click="sortBy('spend')">{{ t('adm.colSpend') }}{{ mixedCur ? ' (USD)' : '' }}{{ sortIcon('spend') }}</div><div class="so" @click="sortBy('conversions')">{{ t('adm.colConversion') }}{{ sortIcon('conversions') }}</div><div class="so" :title="mixedCur ? t('adm.mixedCurrencyTip') : ''" @click="sortBy('cpa')">CPA{{ mixedCur ? ' ($)' : '' }}{{ sortIcon('cpa') }}</div><div class="so" @click="sortBy('reach')">{{ t('adm.colReach') }}{{ sortIcon('reach') }}</div><div class="so" @click="sortBy('frequency')">{{ t('adm.colFrequency') }}{{ sortIcon('frequency') }}</div><div></div></div>
        <div v-for="c in curList" :key="c.id" class="row" :class="{ sel: isSelected(c.id) }" :style="rowStyle" @click="toggleSelect(c.id)">
          <div class="status-cell" @click.stop><el-switch :model-value="c.effective_status === 'ACTIVE'" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" @change="toggleStatus(c)" :disabled="opLoading" /><span class="dot" :class="statusDot(c.effective_status)"></span>{{ statusLabel(c.effective_status) }}</div>
          <div class="nm clk" @click.stop="drillToAdset(c)">{{ c.name }}<div class="sid"><span v-if="platChipByAct(c.act_id)" :class="['plat-chip', platChipByAct(c.act_id)]">{{ platChipByAct(c.act_id).toUpperCase() }}</span>{{ c.account_name }} · {{ c.id }}</div></div>
          <div>{{ objLabel(c.objective) }}</div>
          <div class="budget-cell" :class="{ editable: hasBudget(c) }" @click.stop="hasBudget(c) && openBudget(c)">{{ fmtBudget(c, 'campaign') }}</div>
          <div>{{ fmtSpendCol(c) }}</div><div>{{ c.conversions || 0 }}</div><div>{{ fmtCpaCol(c) }}</div><div>{{ fmtNum(c.reach) }}</div><div>{{ c.frequency || '-' }}</div>
          <div class="ops" @click.stop><el-dropdown trigger="click" @command="cmd => onAction(cmd, c)" placement="bottom-end"><button class="more-btn" :disabled="opLoading">⚙</button><template #dropdown><el-dropdown-menu><el-dropdown-item command="toggle">{{ c.effective_status === 'ACTIVE' ? t('adm.paused') : t('adm.activate') }}</el-dropdown-item><el-dropdown-item command="rename">{{ t('adm.rename') }}</el-dropdown-item><el-dropdown-item v-if="hasBudget(c)" command="budget">{{ t('adm.editBudget') }}</el-dropdown-item><el-dropdown-item command="delete" divided style="color:var(--error)">{{ t('common.delete') }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
        </div>
      </template>
      <template v-else-if="tab === 'adset'">
        <div class="row head" :style="rowStyle"><div class="so" @click="sortBy('_status_rank')">{{ t('common.status') }}{{ sortIcon('_status_rank') }}</div><div>{{ t('adm.colAdset') }}</div><div>{{ t('adm.colOptGoal') }}</div><div class="so" @click="sortBy('daily_budget_amount')">{{ t('adm.colBudget') }}{{ sortIcon('daily_budget_amount') }}</div><div class="so" :title="mixedCur ? t('adm.mixedCurrencyTip') : ''" @click="sortBy('spend')">{{ t('adm.colSpend') }}{{ mixedCur ? ' (USD)' : '' }}{{ sortIcon('spend') }}</div><div class="so" @click="sortBy('conversions')">{{ t('adm.colConversion') }}{{ sortIcon('conversions') }}</div><div class="so" :title="mixedCur ? t('adm.mixedCurrencyTip') : ''" @click="sortBy('cpa')">CPA{{ mixedCur ? ' ($)' : '' }}{{ sortIcon('cpa') }}</div><div class="so" @click="sortBy('reach')">{{ t('adm.colReach') }}{{ sortIcon('reach') }}</div><div class="so" @click="sortBy('frequency')">{{ t('adm.colFrequency') }}{{ sortIcon('frequency') }}</div><div></div></div>
        <div v-for="s in curList" :key="s.id" class="row" :class="{ sel: isSelected(s.id) }" :style="rowStyle" @click="toggleSelect(s.id)">
          <div class="status-cell" @click.stop><el-switch :model-value="s.effective_status === 'ACTIVE'" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" @change="toggleStatus(s)" :disabled="opLoading" /><span class="dot" :class="statusDot(s.effective_status)"></span>{{ statusLabel(s.effective_status) }}</div>
          <div class="nm clk" @click.stop="drillToAd(s)">{{ s.name }}<div class="sid"><span v-if="platChipByAct(s.act_id)" :class="['plat-chip', platChipByAct(s.act_id)]">{{ platChipByAct(s.act_id).toUpperCase() }}</span>{{ s.account_name }} · {{ s.id }}</div></div>
          <div>{{ optLabel(s.optimization_goal) }}</div>
          <div class="budget-cell" :class="{ editable: hasBudget(s) }" @click.stop="hasBudget(s) && openBudget(s)">{{ fmtBudget(s, 'adset') }}</div>
          <div>{{ fmtSpendCol(s) }}</div><div>{{ s.conversions || 0 }}</div><div>{{ fmtCpaCol(s) }}</div><div>{{ fmtNum(s.reach) }}</div><div>{{ s.frequency || '-' }}</div>
          <div class="ops" @click.stop><el-dropdown trigger="click" @command="cmd => onAction(cmd, s)" placement="bottom-end"><button class="more-btn" :disabled="opLoading">⚙</button><template #dropdown><el-dropdown-menu><el-dropdown-item command="toggle">{{ s.effective_status === 'ACTIVE' ? t('adm.paused') : t('adm.activate') }}</el-dropdown-item><el-dropdown-item command="rename">{{ t('adm.rename') }}</el-dropdown-item><el-dropdown-item v-if="hasBudget(s)" command="budget">{{ t('adm.editBudget') }}</el-dropdown-item><el-dropdown-item command="delete" divided style="color:var(--error)">{{ t('common.delete') }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
        </div>
      </template>
      <template v-else>
        <div class="row head" :style="rowStyle"><div class="so" @click="sortBy('_status_rank')">{{ t('common.status') }}{{ sortIcon('_status_rank') }}</div><div>{{ t('adm.tabAd') }}</div><div>{{ t('adm.colSubcode') }}</div><div class="so" :title="mixedCur ? t('adm.mixedCurrencyTip') : ''" @click="sortBy('spend')">{{ t('adm.colSpend') }}{{ mixedCur ? ' (USD)' : '' }}{{ sortIcon('spend') }}</div><div class="so" @click="sortBy('conversions')">{{ t('adm.colConversion') }}{{ sortIcon('conversions') }}</div><div class="so" :title="mixedCur ? t('adm.mixedCurrencyTip') : ''" @click="sortBy('cpa')">CPA{{ mixedCur ? ' ($)' : '' }}{{ sortIcon('cpa') }}</div><div class="so" @click="sortBy('landing_visits')">{{ t('adm.colVisits') }}{{ sortIcon('landing_visits') }}</div><div class="so" @click="sortBy('landing_pass')">{{ t('adm.colPass') }}{{ sortIcon('landing_pass') }}</div><div>{{ t('adm.colPassRate') }}</div><div class="so" @click="sortBy('reach')">{{ t('adm.colReach') }}{{ sortIcon('reach') }}</div><div class="so" @click="sortBy('ctr')">CTR{{ sortIcon('ctr') }}</div><div></div></div>
        <div v-for="a in curList" :key="a.id" class="row" :class="{ sel: isSelected(a.id) }" :style="rowStyle" @click="toggleSelect(a.id)">
          <div class="status-cell" @click.stop><el-switch :model-value="a.effective_status === 'ACTIVE'" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" @change="toggleStatus(a)" :disabled="opLoading" /><span class="dot" :class="statusDot(a.effective_status)"></span>{{ statusLabel(a.effective_status) }}<span v-if="a.effective_status === 'DISAPPROVED' && rfOf(a)" class="rf-flag" :title="t('adm.reviewFlagHint')" @click.stop="showReview(a)">⚠</span></div>
          <div class="nm"><img v-if="thumbOf(a)" :src="thumbOf(a)" class="ad-thumb" :alt="t('adm.thumbTitle')" @click.stop="showThumb(a)" />{{ a.name }}<span v-if="redirectMap[a.id]" class="rd-mark" @click.stop="openRedirect(a)" :title="t('adm.redirectMarkTitle', { url: redirectMap[a.id] })">{{ t('adm.redirectShort') }}</span><div class="sid"><span v-if="platChipByAct(a.act_id)" :class="['plat-chip', platChipByAct(a.act_id)]">{{ platChipByAct(a.act_id).toUpperCase() }}</span>{{ a.account_name }} · {{ a.id }}</div></div>
          <div class="slug-cell"><code v-if="a.slug" class="ad-slug" @click.stop="goLandingLogs(a.slug, a.id)" :title="t('adm.slugTitle', { slug: a.slug, pass: a.landing_pass||0 })">/a/{{ a.slug }}</code><span v-else class="muted" :title="t('adm.slugEmptyTitle')">{{ t('adm.slugEmpty') }}</span></div>
          <div>{{ fmtSpendCol(a) }}</div><div>{{ a.conversions || 0 }}</div><div>{{ fmtCpaCol(a) }}</div><div class="lv" :title="t('adm.lvTitle')">{{ a.landing_visits || '-' }}</div><div class="lp" :title="t('adm.lpTitle')">{{ a.landing_pass || '-' }}</div><div class="lpr" :title="a.landing_visits ? t('adm.lprTitle', { pass: a.landing_pass||0, visits: a.landing_visits }) : t('adm.noVisits')">{{ a.landing_visits ? Math.round((a.landing_pass || 0) / a.landing_visits * 100) + '%' : '-' }}</div><div>{{ fmtNum(a.reach) }}</div><div>{{ a.ctr ? a.ctr + '%' : '-' }}</div>
          <div class="ops" @click.stop><el-dropdown trigger="click" @command="cmd => onAction(cmd, a)" placement="bottom-end"><button class="more-btn" :disabled="opLoading">⚙</button><template #dropdown><el-dropdown-menu><el-dropdown-item command="toggle">{{ a.effective_status === 'ACTIVE' ? t('adm.paused') : t('adm.activate') }}</el-dropdown-item><el-dropdown-item command="rename">{{ t('adm.rename') }}</el-dropdown-item><el-dropdown-item command="redirect">{{ t('adm.redirectLink') }}{{ redirectMap[a.id] ? ' · ' + t('adm.redirectSet') : '' }}</el-dropdown-item><el-dropdown-item command="logs">{{ t('adm.viewLandingLogs') }}</el-dropdown-item><el-dropdown-item command="diagnose">🔍 {{ t('adm.adDiagnose') }}</el-dropdown-item><el-dropdown-item v-if="a.object_story_id" command="reuse">📌 {{ t('adm.reuseThisPost') }}</el-dropdown-item><el-dropdown-item command="delete" divided style="color:var(--error)">{{ t('common.delete') }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
        </div>
      </template>
      <div v-if="!curList.length && !loading" class="empty">{{ t('common.noData') }}</div>
    </div>
    <div v-if="tab === 'lead'" class="leads-panel">
      <div class="leads-bar">
        <span class="rd-cnt">{{ t('adm.leadsCount', { n: leads.length }) }}</span>
        <div class="sf-group">
          <button v-for="s in ['all', ...LEAD_STATUSES]" :key="s" class="ctrl-btn sm" :class="{ on: leadStatusFilter === s }" @click="leadStatusFilter = s; loadLeads()">{{ leadStatusFilterLabel(s) }}</button>
        </div>
        <button class="ctrl-btn sm" :disabled="opLoading" @click="syncLeads">⟳ {{ t('adm.leadsSync') }}</button>
        <button class="ctrl-btn sm" :disabled="!leads.length" @click="exportLeads">⬇ {{ t('common.exportCsv') }}</button>
        <button class="ctrl-btn sm" :disabled="opLoading" @click="subscribeLeads">🔔 {{ t('adm.leadsSubscribe') }}</button>
        <span class="leads-hint">{{ t('adm.leadsHint') }}</span>
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
    <el-dialog v-model="budgetDialog" :title="t('adm.editBudgetTitle', { name: budgetTarget?.name || '' })" width="360px" :close-on-click-modal="false" :destroy-on-close="true" append-to-body>
      <div class="budget-form">
        <label>{{ budgetTarget?.budget_type === 'lifetime' ? t('adm.lifetimeBudgetLabel') : t('adm.dailyBudgetLabel') }}</label>
        <input v-model.number="budgetInput" type="number" min="1" step="0.01" class="budget-input" />
        <div class="quick-btns"><button v-for="m in [1, 1.2, 1.5, 2]" :key="m" class="ctrl-btn sm" @click="budgetQuick(m)">×{{ m }}</button></div>
      </div>
      <template #footer><button class="ctrl-btn" @click="budgetDialog = false">{{ t('common.cancel') }}</button><button class="ctrl-btn primary" :disabled="opLoading" @click="saveBudget">{{ opLoading ? t('common.saving') + '…' : t('common.save') }}</button></template>
    </el-dialog>

    <el-dialog v-model="redirectDialog" :title="t('adm.redirectDialogTitle', { name: redirectTarget?.name || '' })" width="440px" :close-on-click-modal="false" :destroy-on-close="true" append-to-body>
      <div class="rd-form">
        <label>{{ t('adm.redirectFormLabel') }}</label>
        <input v-model.trim="redirectInput" class="budget-input" :placeholder="t('adm.redirectInputPh')" />
        <div class="rd-hint">{{ t('adm.redirectHint') }}</div>
      </div>
      <template #footer>
        <button class="ctrl-btn" @click="redirectDialog = false">{{ t('common.cancel') }}</button>
        <button v-if="redirectMap[redirectTarget?.id]" class="ctrl-btn" @click="redirectInput=''; saveRedirect()">{{ t('adm.restoreDefault') }}</button>
        <button class="ctrl-btn primary" @click="saveRedirect">{{ t('common.save') }}</button>
      </template>
    </el-dialog>

    <el-dialog v-model="redirectMgmtOpen" :title="t('adm.redirectMgmtTitle')" width="640px" :destroy-on-close="true" append-to-body>
      <div class="rd-mgmt-bar">
        <span class="rd-cnt">{{ t('adm.redirectMgmtCount', { n: redirectList.length }) }}</span>
        <button class="ctrl-btn sm" :disabled="!redirectList.length" @click="resetRedirects">{{ t('adm.restoreAllDefault') }}</button>
      </div>
      <div class="rd-mgmt-list" v-loading="false">
        <div v-for="r in redirectList" :key="r.ad_id" class="rd-mgmt-row">
          <code class="rd-mid">{{ r.ad_id }}</code>
          <span class="rd-murl" :title="r.target_url">{{ r.target_url }}</span>
          <button class="ctrl-btn sm" @click="removeRedirect(r.ad_id)">{{ t('common.remove') }}</button>
        </div>
        <div v-if="!redirectList.length" class="empty" style="padding:30px">{{ t('adm.redirectMgmtEmpty') }}</div>
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
              <span class="rule-icon">{{ r.hit ? '🔴' : '🟢' }}</span>
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
              🔒 {{ t('adm.diagCooldownMsg', { rule: diagData.cooldown.rule, min: diagData.cooldown.remaining_min }) }}
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
.ctrl-btn.active { background: var(--ac); color: #fff; border-color: var(--ac) }
.ctrl-btn.apply { background: var(--ac); color: #fff; margin-left: 2px; padding: 0 8px }
.ctrl-btn.primary { background: var(--ac); color: #fff; border-color: var(--ac) }
.ctrl-btn.primary:hover { filter: brightness(1.08) }
.ctrl-btn.primary:disabled { opacity: .5; cursor: wait }
.ctrl-btn.sm { padding: 0 8px; font-size: 12px }
.ctrl-btn.ghost { background: transparent; color: var(--t3) }
.ctrl-btn.on { background: var(--ac); color: #fff; border-color: var(--ac) }
.search-input { width: 160px; text-align: left; color-scheme: dark }
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
.tabs { display: flex; align-items: center; gap: 2px; margin-bottom: 8px; border-bottom: 1px solid var(--bd); padding-left: 4px }
.tab { padding: 6px 14px; font-size: 13px; color: var(--t3); cursor: pointer; border-bottom: 2px solid transparent }
.tab.on { color: var(--t1); border-bottom-color: var(--ac); font-weight: 600 }
.drill-tag { margin-left: auto; font-size: 11px; color: var(--t2); background: var(--bg3); padding: 2px 8px; border-radius: 10px }
.drill-tag span { cursor: pointer; color: var(--t3); margin-left: 4px }
.tbl { border: 1px solid var(--bd); border-radius: 8px; overflow-x: auto }
.row { display: grid; gap: 4px; padding: 5px 8px; align-items: center; font-size: 12px; border-bottom: 1px solid var(--bd) }
.row.head { background: var(--bg2); color: var(--t3); font-size: 11px; font-weight: 600 }
.row:last-child { border-bottom: none }
.row.sel { background: rgba(10,132,255,.08); border-left: 2px solid var(--ac); padding-left: 6px }
.row:hover { background: var(--bg2) }
.ops { display: flex; justify-content: flex-end }
.more-btn { width: 24px; height: 22px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t2); font-size: 13px; cursor: pointer; border-radius: 4px; padding: 0; line-height: 20px; text-align: center }
.more-btn:hover { background: var(--ac); color: #fff; border-color: var(--ac) }
.more-btn:disabled { opacity: .5; cursor: wait }
.nm { font-weight: 600; color: var(--t1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.nm.clk { cursor: pointer }
.nm.clk:hover { color: var(--ac) }
.sid { font-size: 10px; color: var(--t3); font-weight: 400 }
/* 平台小标（账户名前的 FB/TT chip，明暗主题均可读） */
.plat-chip { display: inline-block; font-size: 9px; font-weight: 600; padding: 0 4px; border-radius: 4px; margin-right: 5px; line-height: 14px; }
.plat-chip.fb { background: rgba(24, 119, 242, .16); color: #5aa2ff; }
.plat-chip.tt { background: rgba(254, 44, 85, .16); color: #ff6f8d; }
.lv { color: var(--ac); font-size: 11px; font-weight: 600 }
.lp { color: var(--success); font-size: 11px; font-weight: 600 }
.lpr { color: var(--t2); font-size: 11px }
.slug-cell { overflow: hidden }
.ad-slug { color: var(--ac); font-size: 11px; font-family: monospace; cursor: pointer; white-space: nowrap }
.ad-slug:hover { text-decoration: underline }
.muted { color: var(--t3) }
.so { cursor: pointer; user-select: none }
.so:hover { color: var(--ac) }
.status-cell { display: flex; align-items: center; gap: 4px; font-size: 11px; white-space: nowrap }
.dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 4px; vertical-align: middle }
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
.ad-thumb { width: 24px; height: 24px; border-radius: 4px; object-fit: cover; vertical-align: middle; margin-right: 6px; cursor: zoom-in }
.rf-flag { color: var(--error); cursor: pointer; font-size: 11px; margin-left: 2px }
.rf-flag:hover { opacity: .8 }
.cache-at { font-size: 11px; color: var(--t3); white-space: nowrap; margin-left: 8px }
.cache-at.stale { color: var(--warning) }
.rd-badge { display: inline-block; min-width: 16px; padding: 0 4px; margin-left: 4px; font-size: 10px; background: var(--ac); color: #fff; border-radius: 8px }
.rd-form { display: flex; flex-direction: column; gap: 8px }
.rd-form label { font-size: 12px; color: var(--t3) }
.rd-hint { font-size: 11px; color: var(--t3); line-height: 1.5 }
.rd-mgmt-bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px }
.rd-cnt { font-size: 12px; color: var(--t2) }
.rd-mgmt-list { max-height: 380px; overflow-y: auto }
.rd-mgmt-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--bd); font-size: 12px }
.rd-mid { color: var(--t3); font-size: 11px; flex-shrink: 0 }
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
.lead-row { grid-template-columns: 1.3fr 1fr 1.4fr 1.1fr 1fr 0.95fr 1.4fr 1.5fr }
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
</style>
