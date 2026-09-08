<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { showError } from '../composables/useError'
import { fmtTime } from '../composables/useTz'
import { jobStatus, itemStatus, fbAdStatus, subcodeStatus } from '../composables/useStatus'
import { fbErrorText } from '../composables/useFbError'
import { fmtUsd } from '../composables/useFormat'
import { COUNTRIES as ALL_COUNTRIES, countryName } from '../composables/useCountries'

const { t } = useI18n()
const route = useRoute()

const list = ref([])
const loading = ref(false)
// 平台筛选（模板列表顶部 chip）：all / fb / tt——也是新建模板的默认平台来源之一
const platFilter = ref('all')
const filteredList = computed(() => platFilter.value === 'all' ? list.value : list.value.filter(x => (x.platform || 'fb') === platFilter.value))
const editOpen = ref(false)
const editing = ref(null)
const form = ref({})
const saving = ref(false)
const tplPages = ref([])  // 模板编辑器主页下拉选项（从 FB 拉）
// Advantage+ 开关（对齐 FB Ads Manager 2025）
const advantage_audience = ref(true)   // Advantage+ 受众（开=只设国家+AI扩展；关=手动定向）
const advantage_creative = ref(true)   // Advantage+ 创意（开=FB自动生成文案变体/裁切；关=固定1套）
const performance_goal_cpa = ref(0)    // 性能目标 CPA（0=不限）
const editingAsset = ref(null)
const previewOpen = ref(false)
const previewAsset = ref(null)
// 素材选择器
const assetPickerOpen = ref(false)
const pickerAssets = ref([])
const pickerLoading = ref(false)
// 兴趣搜索（结果共享；组卡内联受众按节点添加——searchInterestsForNode/addNodeInterest）
const interestSearching = ref(false)
const interestResults = ref([])
// 部署抽屉
const deployOpen = ref(false)
const deployTpl = ref(null)
const deployAsset = ref(null)
const accounts = ref([])
const accLoading = ref(false)
const deploySearch = ref('')
const filteredDeployAccounts = computed(() => {
  const q = deploySearch.value.trim().toLowerCase()
  if (!q) return accounts.value
  return accounts.value.filter(a =>
    (a.name || '').toLowerCase().includes(q) || (a.act_id || '').includes(q)
  )
})
const selectedAccs = ref(new Set())
const accPages = ref({})  // {act_id: [pages]}
const accPixels = ref({}) // {act_id: [pixels]}
const deployItems = ref({})  // {act_id: {page_id, pixel_id}}
const deploying = ref(false)
// 像素策略（部署抽屉）：template=跟随模板（旧行为）/ random=随机用账户像素 / create=每账户新建像素
const pixelStrategy = ref('template')
// 主页权限总览（部署抽屉顶部折叠面板；懒加载——展开才拉 /leads/pages）
const pageOverviewOpen = ref(false)
const permPages = ref([])
const permPagesLoading = ref(false)
let permPagesLoaded = false
// 按素材批量生成系列（对标 FBInsider batchGenerate）：模板=母版，每个选中素材克隆一个
// 完整系列（campaign+adset+ad），系列名/广告名=素材名；模板自带素材在批量模式下被忽略
const deployMode = ref('single')   // single=单模板部署（默认，旧行为） / batch=按素材批量生成系列
const BATCH_ASSET_MAX = 200        // 批量素材上限（与后端 _validate_batch_assets 一致）
const batchAssets = ref([])        // 素材库（批量选择卡片；懒加载——首次切到批量模式才拉）
const batchAssetsLoading = ref(false)
const batchAssetIds = ref(new Set())
const batchPreview = computed(() => ({
  n: selectedAccs.value.size, m: batchAssetIds.value.size,
  total: selectedAccs.value.size * batchAssetIds.value.size,
}))
// 落地页
const landingPages = ref([])
// 进度
const progressOpen = ref(false)
const activeJob = ref(null)
let pollTimer = null
let pollGen = 0   // 全库审查P1：轮询代际——双开进度弹窗曾产生孤儿轮询链持续请求
// 受众库（SavedAudience 选择器——后端 CRUD 现成，此处接通消费端）
const savedAudiences = ref([])
// 模板已部署清单抽屉
const depOpen = ref(false)
const depTpl = ref(null)
const depJobs = ref([])
const depLoading = ref(false)
const depJobDetail = ref(null)
const depItemsLoading = ref(false)

const OBJECTIVES = [
  { v: 'OUTCOME_SALES', l: 'launch.obj_sales' },
  { v: 'OUTCOME_LEADS', l: 'launch.obj_leads' },
  { v: 'OUTCOME_TRAFFIC', l: 'launch.obj_traffic' },
  { v: 'OUTCOME_ENGAGEMENT', l: 'launch.obj_engagement' },
  { v: 'OUTCOME_AWARENESS', l: 'launch.obj_awareness' },
  { v: 'OUTCOME_APP_PROMOTION', l: 'launch.obj_app_promotion' },
]
// 目标选择弹窗排列序（对齐 FB Objective Picker：知名度 → 销量 从上到下）
const OBJ_PICKER = [
  OBJECTIVES.find(o => o.v === 'OUTCOME_AWARENESS'),
  OBJECTIVES.find(o => o.v === 'OUTCOME_TRAFFIC'),
  OBJECTIVES.find(o => o.v === 'OUTCOME_ENGAGEMENT'),
  OBJECTIVES.find(o => o.v === 'OUTCOME_LEADS'),
  OBJECTIVES.find(o => o.v === 'OUTCOME_APP_PROMOTION'),
  OBJECTIVES.find(o => o.v === 'OUTCOME_SALES'),
].filter(Boolean)
// 每目标一句场景说明（右侧面板）
const OBJ_SCENES = {
  OUTCOME_AWARENESS: 'launch.obj_desc_awareness',
  OUTCOME_TRAFFIC: 'launch.obj_desc_traffic',
  OUTCOME_ENGAGEMENT: 'launch.obj_desc_engagement',
  OUTCOME_LEADS: 'launch.obj_desc_leads',
  OUTCOME_APP_PROMOTION: 'launch.obj_desc_app_promotion',
  OUTCOME_SALES: 'launch.obj_desc_sales',
}
// 特殊广告类别白名单（后端 _SPECIAL_CATS 同枚举）
const SPECIAL_CATS = [
  { v: 'CREDIT', l: 'launch.scat_credit' },
  { v: 'EMPLOYMENT', l: 'launch.scat_employment' },
  { v: 'HOUSING', l: 'launch.scat_housing' },
  { v: 'SOCIAL_ISSUES_ELECTIONS_POLITICS', l: 'launch.scat_politics' },
  { v: 'FINANCIAL_PRODUCTS', l: 'launch.scat_financial' },
]
const OPT_GOALS = [
  {v:'LINK_CLICKS',l:'launch.opt_link_clicks'},{v:'LANDING_PAGE_VIEWS',l:'launch.opt_landing_page_views'},{v:'REACH',l:'launch.opt_reach'},
  {v:'IMPRESSIONS',l:'launch.opt_impressions'},{v:'OFFSITE_CONVERSIONS',l:'launch.opt_offsite_conversions'},{v:'LEAD_GENERATION',l:'launch.opt_lead_generation'},
  {v:'PAGE_LIKES',l:'launch.opt_page_likes'},{v:'POST_ENGAGEMENT',l:'launch.opt_post_engagement'},{v:'CONVERSATIONS',l:'launch.opt_conversations'},
  {v:'THRUPLAY',l:'launch.opt_thruplay'},{v:'APP_INSTALLS',l:'launch.opt_app_installs'},{v:'VALUE',l:'launch.opt_value'},
  {v:'TWO_SECOND_CONTINUOUS_VIDEO_VIEWS',l:'launch.opt_two_second_video_views'},{v:'MESSAGING_PURCHASE_CONVERSION',l:'launch.opt_messaging_purchase'},
  {v:'MESSAGING_APPOINTMENT_CONVERSION',l:'launch.opt_messaging_appointment'},{v:'EVENT_RESPONSES',l:'launch.opt_event_responses'},
  {v:'QUALITY_LEAD',l:'launch.opt_quality_lead'},
]
// ── 批次I 前端镜像常量（同源 backend/app/core/ad_builder.py——后端矩阵变更时此处必须同步）──
// 转化位置合法值按 objective（ad_builder.CONV_LOCATIONS_BY_OBJECTIVE）；顺序=下拉展示序
const CONV_LOCATIONS_BY_OBJECTIVE = {
  OUTCOME_SALES: ['website', 'messenger', 'whatsapp', 'phone_call'],
  OUTCOME_LEADS: ['website', 'on_ad', 'on_ad_messenger', 'messenger', 'whatsapp', 'instagram_direct', 'phone_call'],
  OUTCOME_TRAFFIC: ['website', 'messenger', 'whatsapp', 'instagram_direct', 'phone_call'],
  OUTCOME_ENGAGEMENT: ['website', 'on_page', 'messenger', 'whatsapp', 'instagram_direct'],
  OUTCOME_AWARENESS: [],
  OUTCOME_APP_PROMOTION: [],
}
// 优化目标 × objective 兼容表（ad_builder.OPT_GOALS_BY_OBJECTIVE）：组卡优化目标下拉按此过滤
const OPT_GOALS_BY_OBJECTIVE = {
  OUTCOME_AWARENESS: ['REACH', 'IMPRESSIONS', 'THRUPLAY', 'TWO_SECOND_CONTINUOUS_VIDEO_VIEWS'],
  OUTCOME_TRAFFIC: ['LINK_CLICKS', 'LANDING_PAGE_VIEWS', 'REACH', 'IMPRESSIONS', 'CONVERSATIONS'],
  OUTCOME_ENGAGEMENT: ['REACH', 'IMPRESSIONS', 'LINK_CLICKS', 'LANDING_PAGE_VIEWS', 'POST_ENGAGEMENT',
    'PAGE_LIKES', 'CONVERSATIONS', 'MESSAGING_PURCHASE_CONVERSION', 'MESSAGING_APPOINTMENT_CONVERSION',
    'THRUPLAY', 'TWO_SECOND_CONTINUOUS_VIDEO_VIEWS', 'EVENT_RESPONSES', 'OFFSITE_CONVERSIONS'],
  OUTCOME_LEADS: ['LEAD_GENERATION', 'QUALITY_LEAD', 'OFFSITE_CONVERSIONS', 'CONVERSATIONS',
    'LINK_CLICKS', 'LANDING_PAGE_VIEWS', 'REACH', 'IMPRESSIONS'],
  OUTCOME_SALES: ['OFFSITE_CONVERSIONS', 'VALUE', 'CONVERSATIONS', 'LINK_CLICKS',
    'LANDING_PAGE_VIEWS', 'IMPRESSIONS', 'REACH', 'MESSAGING_PURCHASE_CONVERSION'],
  OUTCOME_APP_PROMOTION: ['APP_INSTALLS', 'VALUE', 'LINK_CLICKS'],
}
const convLocationsForObj = computed(() => CONV_LOCATIONS_BY_OBJECTIVE[form.value.objective] || [])
const optGoalsForObj = computed(() =>
  (OPT_GOALS_BY_OBJECTIVE[form.value.objective] || []).map(v => OPT_GOALS.find(o => o.v === v)).filter(Boolean))
// 转化目标（按 objective 联动）—— FB custom_event_type 枚举
const CONV_GOAL_LABELS = {
  Purchase:'launch.conv_purchase', AddToCart:'launch.conv_add_to_cart', InitiateCheckout:'launch.conv_initiate_checkout', AddPaymentInfo:'launch.conv_add_payment_info',
  CompleteRegistration:'launch.conv_complete_registration', Lead:'launch.conv_lead', Subscribe:'launch.conv_subscribe', Contact:'launch.conv_contact',
  StartTrial:'launch.conv_start_trial', Search:'launch.conv_search', APP_INSTALLS:'launch.conv_app_installs', LEVEL_ACHIEVED:'launch.conv_level_achieved',
  ACHIEVEMENT_UNLOCKED:'launch.conv_achievement_unlocked', SPENT_CREDITS:'launch.conv_spent_credits',
}
const CONV_GOALS = {
  OUTCOME_SALES: ['Purchase','AddToCart','InitiateCheckout','AddPaymentInfo','CompleteRegistration','Lead','Subscribe','Contact','StartTrial','Search'],
  OUTCOME_LEADS: ['Lead','CompleteRegistration','Contact','Subscribe','Search','StartTrial','Purchase'],
  OUTCOME_TRAFFIC: [],
  OUTCOME_ENGAGEMENT: [],
  OUTCOME_AWARENESS: [],
  OUTCOME_APP_PROMOTION: ['APP_INSTALLS','LEVEL_ACHIEVED','ACHIEVEMENT_UNLOCKED','SPENT_CREDITS'],
}
const convGoalsForObjective = computed(() => CONV_GOALS[form.value.objective] || [])

// 广告目标 → 推荐的优化目标/计费事件/目的地/转化事件 默认值（FB Ads Manager 的默认选择）
const OBJ_DEFAULTS = {
  OUTCOME_SALES:    { opt: 'OFFSITE_CONVERSIONS', bill: 'IMPRESSIONS', dest: 'WEBSITE', conv: 'Purchase' },
  OUTCOME_LEADS:    { opt: 'LEAD_GENERATION',     bill: 'IMPRESSIONS', dest: 'ON_AD',   conv: 'Lead' },
  OUTCOME_TRAFFIC:  { opt: 'LINK_CLICKS',          bill: 'IMPRESSIONS', dest: 'WEBSITE', conv: '' },
  OUTCOME_ENGAGEMENT:{ opt: 'PAGE_LIKES',          bill: 'IMPRESSIONS', dest: 'ON_PAGE', conv: '' },
  OUTCOME_AWARENESS:{ opt: 'REACH',                bill: 'IMPRESSIONS', dest: '',        conv: '' },
  OUTCOME_APP_PROMOTION:{ opt: 'APP_INSTALLS',     bill: 'IMPRESSIONS', dest: 'APP',     conv: '' },
}
// 选广告目标 → 自动填广告组推荐默认值（仅当用户没手动改过时）
watch(() => form.value.objective, (newObj, oldObj) => {
  if (!newObj || newObj === oldObj) return
  const d = OBJ_DEFAULTS[newObj]
  if (!d) return
  // 只在空值或旧默认时自动填（不覆盖用户手选）
  const oldD = oldObj ? OBJ_DEFAULTS[oldObj] : null
  if (!form.value.optimization_goal || form.value.optimization_goal === oldD?.opt)
    form.value.optimization_goal = d.opt
  if (!form.value.billing_event || form.value.billing_event === 'IMPRESSIONS')
    form.value.billing_event = d.bill
  if (!form.value.destination_type || form.value.destination_type === oldD?.dest)
    form.value.destination_type = d.dest
  // 转化事件：空 / 旧默认 / 不在新目标词表（跨目标残留）→ 重置（审计 C4）
  const cgOk = CONV_GOALS[newObj] || []
  if (!form.value.conversion_goal || form.value.conversion_goal === oldD?.conv
    || !cgOk.includes(form.value.conversion_goal))
    form.value.conversion_goal = d.conv
  // 组节点不兼容的转化位置/优化目标按新目标白名单清（后端保存 422 同口径前置）
  const _locs = CONV_LOCATIONS_BY_OBJECTIVE[newObj] || []
  const _goals = OPT_GOALS_BY_OBJECTIVE[newObj] || []
  for (const s of tree.value.adsets || []) {
    if (s.conv_location && !_locs.includes(s.conv_location)) s.conv_location = ''
    if (s.optimization_goal && !_goals.includes(s.optimization_goal)) s.optimization_goal = ''
  }
})
// 版位选项
const PLATFORMS = [
  { v: 'facebook', l: 'Facebook', positions: [
    {v:'feed',l:'launch.pos_feed'},{v:'video_feeds',l:'launch.pos_video_feeds'},{v:'instream_video',l:'launch.pos_instream_video'},
    {v:'story',l:'launch.pos_story'},{v:'reels',l:'launch.pos_reels'},{v:'marketplace',l:'launch.pos_marketplace'},
    {v:'right_hand_column',l:'launch.pos_right_hand_column'},{v:'search',l:'launch.pos_search'},
  ]},
  { v: 'instagram', l: 'Instagram', positions: [
    {v:'stream',l:'launch.pos_stream'},{v:'story',l:'launch.pos_story'},{v:'explore',l:'launch.pos_explore'},
    {v:'reels',l:'launch.pos_reels'},{v:'profile',l:'launch.pos_profile'},
  ]},
  { v: 'messenger', l: 'Messenger', positions: [
    {v:'messenger_home',l:'launch.pos_messenger_home'},{v:'story',l:'launch.pos_story'},{v:'sponsored_messages',l:'launch.pos_sponsored_messages'},
  ]},
  { v: 'audience_network', l: 'Audience Network', positions: [
    {v:'classic',l:'launch.pos_classic'},{v:'instream_video',l:'launch.pos_instream_video'},{v:'rewarded_video',l:'launch.pos_rewarded_video'},
  ]},
]
const DEVICES = [{v:'desktop',l:'launch.dev_desktop'}, {v:'mobile',l:'launch.dev_mobile'}]
// 版位平台选项（publisher_platforms 合法值 = backend _PLACEMENT_PLATFORMS）
const PUB_PLATFORMS = ['facebook', 'instagram', 'messenger', 'audience_network']
const PUB_PLATFORM_LABELS = { facebook: 'Facebook', instagram: 'Instagram', messenger: 'Messenger', audience_network: 'Audience Network' }
const BID_STRATEGIES = [
  { v: 'LOWEST_COST_WITHOUT_CAP', l: 'launch.bid_lowest_without_cap' },
  { v: 'COST_CAP', l: 'launch.bid_cost_cap' },
  { v: 'BID_CAP', l: 'launch.bid_cap' },
  { v: 'MIN_ROAS_WITHOUT_CAP', l: 'launch.bid_min_roas' },
  { v: 'LOWEST_COST_WITH_BID_CAP', l: 'launch.bid_lowest_with_cap' },
]
// 出价额类策略（显示 bid_amount_usd 输入）/ ROAS 类（显示 minimum_roas 输入）
const BID_NEEDS_AMOUNT = ['COST_CAP', 'BID_CAP', 'LOWEST_COST_WITH_BID_CAP']
const BID_NEEDS_ROAS = ['MIN_ROAS_WITHOUT_CAP']
const CTAS = [
  { v: 'SHOP_NOW', l: 'launch.cta_shop_now' },{ v: 'SIGN_UP', l: 'launch.cta_sign_up' },{ v: 'SUBSCRIBE', l: 'launch.cta_subscribe' },
  { v: 'LEARN_MORE', l: 'launch.cta_learn_more' },{ v: 'DOWNLOAD', l: 'launch.cta_download' },{ v: 'CONTACT_US', l: 'launch.cta_contact_us' },
  { v: 'GET_QUOTE', l: 'launch.cta_get_quote' },{ v: 'BOOK_NOW', l: 'launch.cta_book_now' },{ v: 'ORDER_NOW', l: 'launch.cta_order_now' },
  { v: 'CALL_NOW', l: 'launch.cta_call_now' },{ v: 'MESSAGE_PAGE', l: 'launch.cta_message_page' },{ v: 'WATCH_MORE', l: 'launch.cta_watch_more' },
  { v: 'ADD_TO_CART', l: 'launch.cta_add_to_cart' },{ v: 'BUY_TICKETS', l: 'launch.cta_buy_tickets' },
]
const LANGS = [
  { v: '24', l: 'launch.lang_en_us' },{ v: '6', l: 'launch.lang_en_gb' },{ v: '37', l: 'launch.lang_en_all' },
  { v: '5', l: 'launch.lang_zh_cn' },{ v: '2', l: 'launch.lang_zh_tw' },{ v: '1', l: 'launch.lang_zh_all' },
  { v: '31', l: 'launch.lang_vi' },{ v: '34', l: 'launch.lang_th' },{ v: '32', l: 'launch.lang_id' },{ v: '27', l: 'launch.lang_ja' },
  { v: '28', l: 'launch.lang_ko' },{ v: '12', l: 'launch.lang_es' },{ v: '14', l: 'launch.lang_pt' },{ v: '15', l: 'launch.lang_ar' },
]
// 归因窗口预设 → FB attribution_spec（仅转化类目标生效）
const ATTRIBUTIONS = [
  { v: '', l: 'launch.attr_default' },
  { v: '1d_click', l: 'launch.attr_1d_click' },
  { v: '7d_click', l: 'launch.attr_7d_click' },
  { v: '1d_click_1d_view', l: 'launch.attr_1d_click_1d_view' },
  { v: '7d_click_1d_view', l: 'launch.attr_7d_click_1d_view' },
]
function attributionToSpec(preset) {
  const C = (d) => [{ event_type: 'CLICK', window_days: d }]
  if (preset === '1d_click') return C(1)
  if (preset === '7d_click') return C(7)
  if (preset === '1d_click_1d_view') return [{ event_type: 'CLICK', window_days: 1 }, { event_type: 'IMPRESSION', window_days: 1 }]
  if (preset === '7d_click_1d_view') return [{ event_type: 'CLICK', window_days: 7 }, { event_type: 'IMPRESSION', window_days: 1 }]
  return null
}
// Dayparting 网格
const DPA_DAYS = ['launch.dpa_mon', 'launch.dpa_tue', 'launch.dpa_wed', 'launch.dpa_thu', 'launch.dpa_fri', 'launch.dpa_sat', 'launch.dpa_sun']
const DPA_FB_DAYS = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY']
const emptyGrid = () => Array.from({ length: 7 }, () => Array(24).fill(false))
// 7×24 矩阵 → FB day_parting_schedule（按天压缩连续时段）
function gridToSchedule(cells) {
  const sched = []
  cells.forEach((hours, di) => {
    let start = -1
    for (let h = 0; h <= 24; h++) {
      const on = h < 24 && hours[h]
      if (on && start < 0) start = h
      else if (!on && start >= 0) {
        sched.push({ days: [DPA_FB_DAYS[di]], start_minute: start * 60, end_minute: h * 60 })
        start = -1
      }
    }
  })
  return sched
}
// 反向：FB schedule → 7×24 矩阵
function scheduleToGrid(sched) {
  const g = emptyGrid()
  if (!Array.isArray(sched)) return g
  const dayIdx = Object.fromEntries(DPA_FB_DAYS.map((d, i) => [d, i]))
  for (const r of sched) {
    const dis = (r.days || []).map(d => dayIdx[d]).filter(i => i !== undefined)
    const sm = Math.floor((r.start_minute || 0) / 60)
    const em = Math.ceil((r.end_minute || 0) / 60)
    for (const di of dis) for (let h = sm; h < em && h < 24; h++) if (h >= 0) g[di][h] = true
  }
  return g
}
const toggleCell = (di, h) => { form.value.daypart_cells[di][h] = !form.value.daypart_cells[di][h] }
const dpaFillAll = () => { form.value.daypart_cells = emptyGrid().map(r => r.map(() => true)) }
const dpaClearAll = () => { form.value.daypart_cells = emptyGrid() }
const dpaFillWorkhours = () => {
  const g = emptyGrid()
  for (let di = 0; di < 7; di++) for (let h = 9; h < 22; h++) g[di][h] = true
  form.value.daypart_cells = g
}

const load = async () => {
  loading.value = true
  try { list.value = await GET('/launch-templates') } catch (e) { showError(e, t('common.fail')) }
  loading.value = false
}
const loadLandingPages = async () => { try { landingPages.value = await GET('/landing/pages') } catch {} }
const onLandingChange = async () => {
  // 选了落地页 → 自动填 public_url + 拉该页子码
  const p = landingPages.value.find(x => x.id === form.value.landing_page_id)
  if (p?.public_url) form.value.landing_url = p.public_url
  // 换页后清掉旧子码（不属于新页）
  if (form.value.subcode_slug && !subcodesForLanding.value.some(s => s.slug === form.value.subcode_slug)) {
    form.value.subcode_slug = ''
  }
  if (form.value.landing_page_id) {
    try {
      const r = await GET(`/subcodes?page_id=${form.value.landing_page_id}&status=all`)
      // 合并进 allSubcodes（去重，保留其他页的缓存）
      const others = allSubcodes.value.filter(s => s.page_id !== form.value.landing_page_id)
      allSubcodes.value = [...others, ...(r.items || [])]
    } catch {}
  }
}
onMounted(() => {
  load(); loadLandingPages(); loadFormMsgTemplates(); loadTplPages(); loadAudiences()
  // 广告列表「复用此帖铺放」入口 → 预填跟帖模板
  const rp = route.query.reuse_post
  if (rp) {
    openNew()
    editMode.value = 'flat'; tree.value = { adsets: [] }   // 跟帖预填走平铺流（直达广告 Tab）
    form.value.post_source = 'reuse'
    form.value.reuse_post_ref = String(rp)
    form.value.page_id = String(rp).split('_')[0]  // {page}_{post} → page
    fetchReusePreview(String(rp))  // 拉帖子内容预览
    _synthTreeFromFlat()   // 平铺模式已移除：预填值合成结构树（首广告节点=跟帖）
    snapshotForm()  // 重新快照（含预填值，避免一开就标 dirty）
    ElMessage.info(t('launch.reusePrefilled'))
  }
})
const loadTplPages = async () => { try { const r = await GET('/fb/assets'); tplPages.value = r.pages || [] } catch {} }
onUnmounted(() => { if (pollTimer) clearTimeout(pollTimer); pollTimer = null; pollGen++ })

// #2 dirty-check：编辑抽屉关闭前确认（含结构模式树 + 模式本身——树编辑不写 form，须一并快照）
let _formSnapshot = ''
const _editSnapshot = () => JSON.stringify({ f: form.value, m: editMode.value, t: tree.value })
const snapshotForm = () => { _formSnapshot = _editSnapshot() }
const isDirty = computed(() => _formSnapshot && _editSnapshot() !== _formSnapshot)
const onEditBeforeClose = (done) => {
  if (isDirty.value) {
    ElMessageBox.confirm(t('launch.confirmDiscardMsg'), t('launch.closeConfirm'), { type: 'warning', confirmButtonText: t('common.discard'), cancelButtonText: t('launch.keepEditing') })
      .then(() => done()).catch(() => {})
  } else { done() }
}

// #1 保存前校验
const validationErrors = ref([])
const validateTemplate = () => {
  const errs = []
  const isReuse = form.value.post_source === 'reuse'
  if (!form.value.name?.trim()) errs.push(t('launch.fieldTplName'))
  if (!isReuse && !form.value.asset_id) errs.push(t('launch.fieldAssetAdTab'))
  if (isReuse && !form.value.reuse_post_ref) errs.push(t('launch.fieldReusePost'))
  errs.push(..._budgetErrors())
  if (!isReuse && !form.value.landing_url && !form.value.landing_page_id && !['OUTCOME_AWARENESS'].includes(form.value.objective))
    errs.push(t('launch.fieldLandingPickOrUrl'))
  return errs
}
// 完整性状态（编辑器顶栏 chip：按当前模式取平铺/树口径校验）
const editStatus = computed(() => {
  const errs = editMode.value === 'tree' ? validateTree() : validateTemplate()
  return errs.length ? { ready: false, missing: errs } : { ready: true, missing: [] }
})
// CBO 开关（budget_mode 语义映射：开=CBO 系列预算；关=ABO 组预算）
const cboOn = computed({
  get: () => (form.value.budget_mode || 'ABO').toUpperCase() === 'CBO',
  set: (v) => { form.value.budget_mode = v ? 'CBO' : 'ABO' },
})
// Advantage+ 版位派生态（蓝图 §4：非开关）：树模式=全部组卡 auto；平铺=无手动版位
const placementAutoAll = computed(() => editMode.value === 'tree'
  ? (tree.value.adsets || []).every(s => s.placement_mode !== 'manual')
  : !form.value.manual_placement)

// #5 部署历史
const historyOpen = ref(false)
const jobs = ref([])
const loadJobs = async () => { try { jobs.value = await GET('/launch-templates/jobs?limit=20') } catch {} }
const openHistory = async () => { historyOpen.value = true; await loadJobs() }
const openJob = async (jobId) => { historyOpen.value = false; openProgress(jobId) }

// 模板已部署清单（卡片「已部署 N」入口）
const openDeployments = async (tpl) => {
  depTpl.value = tpl; depOpen.value = true
  depJobs.value = []; depJobDetail.value = null; depLoading.value = true
  try { const r = await GET('/launch-templates/' + tpl.id + '/deployments'); depJobs.value = r.jobs || [] }
  catch (e) { showError(e, t('common.opFail')) }
  depLoading.value = false
}
// 展开/收起单次部署 → 拉 items（含 join ads_cache 的当前状态）
const toggleDepJob = async (j) => {
  if (depJobDetail.value?.id === j.id) { depJobDetail.value = null; return }
  depJobDetail.value = null; depItemsLoading.value = true
  try { depJobDetail.value = await GET(`/launch-templates/${depTpl.value.id}/deployments?job_id=${j.id}`) }
  catch (e) { showError(e, t('common.opFail')) }
  depItemsLoading.value = false
}
const copyAdId = (id) => { if (!id) return; navigator.clipboard?.writeText(id); ElMessage.success(t('launch.adIdCopied', { id })) }
const liveStatusColor = (s) => {
  const c = fbAdStatus(s).cls
  return c === 'ok' ? 'var(--success)' : c === 'err' ? 'var(--error)' : c === 'warn' ? 'var(--warning)' : 'var(--t3)'
}

// 受众库选择器
const loadAudiences = async () => { try { savedAudiences.value = await GET('/audiences') } catch {} }
const selectedSavedAud = computed(() => savedAudiences.value.find(a => a.id === form.value.audience_id) || null)
const hasManualAudience = computed(() =>
  (form.value.audience_countries || []).length > 0 || (form.value.audience_interests || []).length > 0)
const audienceChip = computed(() => {
  if (form.value.audience_id) {
    const a = selectedSavedAud.value
    return a ? a.name : `#${form.value.audience_id}`
  }
  const c = (form.value.audience_countries || []).join(',') || t('launch.defaultAudience')
  return `${c} · ${t('launch.interestCount', { n: (form.value.audience_interests || []).length })}`
})
// 手动定向一键存为受众（POST /audiences 现成端点），下次模板直接下拉选用
const saveAsAudience = async () => {
  try {
    const { value } = await ElMessageBox.prompt(t('launch.audSaveNamePh'), t('launch.saveAsAudience'), {
      confirmButtonText: t('common.save'), cancelButtonText: t('common.cancel'),
      inputPattern: /\S+/, inputErrorMessage: t('launch.audNameRequired'),
    })
    const name = value.trim()
    await POST('/audiences', {
      name,
      interests: form.value.audience_interests || [],
      countries: form.value.audience_countries || [],
      age_min: form.value.audience_age_min || 18,
      age_max: form.value.audience_age_max || 65,
      gender: form.value.audience_gender || 0,
    })
    await loadAudiences()
    ElMessage.success(t('launch.audSaved', { name }))
  } catch (e) { if (e !== 'cancel') showError(e, t('common.opFail')) }
}

// #3 预检结构化展示
const preflightResult = ref(null)
const preflightVisible = ref(false)
// 预检值友好化：targeting 展开已知子键（countries→国家名、age_min/max→"18-65"、genders→性别），
// 其余对象（geo_locations / attribution_spec / object_story_spec 等）保持 JSON 原样
const GENDER_TXT = { 0: 'genderAll', 1: 'genderMale', 2: 'genderFemale' }
const pfVal = (k, v) => {
  if (v === null || v === undefined || v === '') return '—'
  if (k === 'targeting' && v && typeof v === 'object' && !Array.isArray(v)) {
    const parts = []
    const geo = v.geo_locations || v.geo
    if (geo?.countries?.length) parts.push(t('launch.countries') + '：' + geo.countries.map(c => countryName(c) || c).join(' · '))
    else if (geo) parts.push('geo：' + JSON.stringify(geo))
    if (v.age_min != null || v.age_max != null) parts.push(t('launch.age') + '：' + (v.age_min ?? 18) + '-' + (v.age_max ?? 65))
    if (Array.isArray(v.genders) && v.genders.length) parts.push(t('launch.gender') + '：' + v.genders.map(g => t('launch.' + (GENDER_TXT[g] || 'genderAll'))).join('/'))
    const rest = { ...v }
    delete rest.geo_locations; delete rest.geo; delete rest.age_min; delete rest.age_max; delete rest.genders
    if (Object.keys(rest).length) parts.push(JSON.stringify(rest))
    return parts.join('  ·  ')
  }
  return JSON.stringify(v)
}
// 树模式预检：将消耗节点预览（前 5 + 省略号）+ 广告节点绑定摘要
const willSpendPreview = computed(() => {
  const w = preflightResult.value?.will_spend || []
  return w.length > 5 ? w.slice(0, 5).join('、') + ' …' : w.join('、')
})
const treeBindingsText = (b) => {
  if (!b) return ''
  const parts = []
  if (b.landing_page_id) parts.push('LP ' + b.landing_page_id)
  if (b.subcode_slug) parts.push('/' + b.subcode_slug)
  if (b.message_template_id) parts.push(t('launch.pfBindMsg') + ' ' + b.message_template_id)
  if (b.lead_form_template_id) parts.push(t('launch.pfBindForm') + ' ' + b.lead_form_template_id)
  return parts.join(' · ')
}
// 预检「预算与排期」行（批G）：日/总预算（本币换算）+ 排期区间 + 投放方式 + 出价 + ROAS + 特殊类别 + 描述
// 平铺用模板级键；树模式每组行传 tree[] 组对象（同名键）
const pfBudgetSegments = (r) => {
  const seg = []
  if (!r) return seg
  if ((r.budget_type || 'daily') === 'lifetime') {
    if (r.lifetime_budget_usd != null)
      seg.push(t('launch.pfLifetime', { v: r.lifetime_budget_usd }) + (r.lifetime_budget_fb != null ? ' → ' + r.lifetime_budget_fb : ''))
  } else if (r.budget_usd != null) {
    seg.push('$' + r.budget_usd + '/' + t('launch.perDay'))
  }
  if (r.schedule_start || r.schedule_end)
    seg.push((r.schedule_start || '—') + ' ~ ' + (r.schedule_end || '—'))
  if (r.pacing === 'accelerated') seg.push(t('launch.pacingAccelerated'))
  if (r.bid_amount_usd != null)
    seg.push(t('launch.pfBid', { v: r.bid_amount_usd }) + (r.bid_amount_fb != null ? ' → ' + r.bid_amount_fb : ''))
  if (r.minimum_roas != null) seg.push(t('launch.pfRoas', { v: r.minimum_roas }))
  if (r.spend_cap_usd != null)
    seg.push(t('launch.pfSpendCap', { v: r.spend_cap_usd }) + (r.spend_cap_fb != null ? ' → ' + r.spend_cap_fb : ''))
  const cats = Array.isArray(r.special_ad_categories) ? r.special_ad_categories : []
  if (cats.length) {
    const labels = cats.map(c => { const hit = SPECIAL_CATS.find(x => x.v === c); return hit ? t(hit.l) : c })
    seg.push(labels.join('/'))
  }
  if (r.link_description) seg.push(t('launch.pfDesc', { v: r.link_description }))
  return seg
}
// #4 per-account page/pixel loading
const accLoadingConfig = ref(new Set())
// 表单/消息模板
const formTemplates = ref([])
const msgTemplates = ref([])
// 子码（按选中落地页过滤）
const allSubcodes = ref([])
const subcodesForLanding = computed(() => {
  if (!form.value.landing_page_id) return []
  return allSubcodes.value.filter(s => s.page_id === form.value.landing_page_id)
})
const selectedFormTpl = ref(null)
const selectedMsgTpl = ref(null)
const formPreviewOpen = ref(false)
const msgPreviewOpen = ref(false)
const loadFormMsgTemplates = async () => {
  try { formTemplates.value = await GET('/form-templates/forms') } catch {}
  try { msgTemplates.value = await GET('/form-templates/messages') } catch {}
}
// 消息模板下拉 label：带类型 chip（Messenger/WhatsApp，产品名不译）；不做类型过滤（WHATSAPP 相关目标也允许复用任一模板文案）
const msgTplLabel = (m) => '[' + ((m.type || 'messenger') === 'whatsapp' ? 'WhatsApp' : 'Messenger') + '] ' + m.name + ' · ' + (m.welcome_text || '').slice(0, 20)
const onFormTplChange = (id) => {
  if (!id) { selectedFormTpl.value = null; form.value.lead_form_id = ''; form.value.lead_form_template_id = 0; return }
  const t = formTemplates.value.find(f => f.id === id)
  selectedFormTpl.value = t || null
  form.value.lead_form_template_id = id
  form.value.lead_form_id = t?.fb_form_id || ''  // 有fb_form_id的直接用，没有的部署时按模板config建
}
const onMsgTplChange = (id) => {
  if (!id) { selectedMsgTpl.value = null; form.value.message_template = ''; form.value.message_template_id = 0; return }
  const t = msgTemplates.value.find(m => m.id === id)
  selectedMsgTpl.value = t || null
  form.value.message_template_id = id
  // 存成 JSON（parse_message_template 兼容 JSON 串/纯文本/dict）
  form.value.message_template = t ? JSON.stringify({ text: t.welcome_text, ice_breakers: t.ice_breakers||[] }) : ''
}

const blankForm = () => ({
  name: '', description: '',
  platform: 'fb',   // fb / tt（TK P3：tt 走 TT 三件套部署链路）
  // 系列 Campaign
  objective: 'OUTCOME_TRAFFIC', conversion_goal: '', budget_mode: 'ABO',
  bid_strategy: 'LOWEST_COST_WITHOUT_CAP', budget_usd: 5, name_prefix: 'Tova Ads',
  // FB 创建流程 1:1（批G）：预算类型/总预算/排期/投放方式/出价额/最小ROAS/特殊类别/描述
  budget_type: 'daily', lifetime_budget_usd: null,
  schedule_start: '', schedule_end: '', pacing: '',
  bid_amount_usd: null, minimum_roas: null,
  special_ad_categories: '', link_description: '',
  // 1:1 尾巴小件（0091）：系列支出上限 + IG 身份
  spend_cap_usd: null, instagram_actor_id: '',
  // 批次I：Click-to-WhatsApp 显式号码（模板级列；仅 ENGAGEMENT 部署进 promoted_object）
  whatsapp_phone_number: '',
  // 组 AdSet
  optimization_goal: '', billing_event: 'IMPRESSIONS', destination_type: '',
  audience_id: 0,
  audience_countries: [], audience_interests: [], audience_age_min: 18, audience_age_max: 65,
  audience_gender: 0, audience_language: '',
  beneficiary: '', payer: '', advanced_config: '',
  // 广告 Ad
  asset_id: null, headline: '', body: '',
  page_id: '', pixel_id: '', landing_url: '', landing_page_id: null,
  cta_type: 'LEARN_MORE', subcode_slug: '', ad_language: '',
  message_template: '', lead_form_id: '',
  message_template_id: null, lead_form_template_id: null,
  manual_placement: false, placement_platforms: [], placement_devices: ['desktop','mobile'],
  facebook_positions: [], instagram_positions: [], messenger_positions: [], audience_network_positions: [],
  frequency_cap: 0,
  attribution_preset: '',
  daypart_enabled: false, daypart_cells: emptyGrid(), daypart_tz: '',
  post_source: 'new', reuse_post_ref: '',
})
const objLabel = (v) => t(OBJECTIVES.find(o => o.v === v)?.l || v)

// 跟帖 Post Picker
const postPickerOpen = ref(false)
const pickerPosts = ref([])
const postPickerLoading = ref(false)
const manualPostId = ref('')
const postResolving = ref(false)
const reusePostPreview = ref(null)       // {message, picture, permalink} 已选帖预览
const reusePreviewAvailable = computed(() => {  // 内容是否真的取到（区分"无内容"vs"取不到"）
  const p = reusePostPreview.value
  return !!(p && (p.message || p.picture || p.permalink))
})
const ctaLabel = (type) => {  // CTA 类型 → 友好标签（预览用）
  const c = CTAS.find(x => x.v === type)
  return c ? t(c.l) : type
}
const linkDomain = (url) => {  // URL → 域名+路径（完整链接，去 https/www）
  try { const u = new URL(url); return (u.hostname.replace(/^www\./, '') + u.pathname).replace(/\/$/, '') } catch { return '' }
}
const reuseNeedManualPage = ref(false)   // 识别失败→揭示手选主页
const manualPageForPost = ref('')        // 手选主页（兜底）
const openPostPicker = async () => {
  if (!form.value.page_id) return ElMessage.warning(t('launch.postPickerNeedPage'))
  postPickerOpen.value = true; postPickerLoading.value = true; pickerPosts.value = []
  try { const r = await GET(`/fb/pages/${form.value.page_id}/posts`); pickerPosts.value = r.posts || [] }
  catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  postPickerLoading.value = false
}
const _setReusePost = (postId, pageId, preview) => {
  form.value.reuse_post_ref = postId
  if (pageId) form.value.page_id = pageId  // 自动/手选主页回填
  reusePostPreview.value = preview || null
  reuseNeedManualPage.value = false; manualPageForPost.value = ''
}
const pickPost = (p) => {
  const pg = (p.id || '').includes('_') ? p.id.split('_')[0] : form.value.page_id
  // 结构模式：帖子引用写入当前选中的广告节点（跟帖强制单素材）
  if (editMode.value === 'tree' && treeSel.value.type === 'ad' && selAd.value) {
    const n = selAd.value
    n.post_source = 'reuse'; n.reuse_post_ref = p.id
    if (pg) form.value.page_id = pg
    if ((n.asset_ids || []).length > 1) { n.asset_ids = n.asset_ids.slice(0, 1); n.multi = false }
    applyNodePostPreview(n, { message: p.message, picture: p.picture, permalink_url: p.permalink_url })
    postPickerOpen.value = false; ElMessage.success(t('launch.postSelected'))
    return
  }
  _setReusePost(p.id, pg, { message: p.message, picture: p.picture, permalink: p.permalink_url, headline: '', cta_type: '' })
  postPickerOpen.value = false; ElMessage.success(t('launch.postSelected'))
}
const confirmManualPost = async () => {
  const raw = manualPostId.value.trim()
  if (!raw) return
  // 完整 {page}_{post} → 直接用（再拉内容预览）
  const m1 = raw.match(/(\d+_\d+)/)
  if (m1) { _setReusePost(m1[1], m1[1].split('_')[0], null); fetchReusePreview(m1[1]); ElMessage.success(t('launch.postSelected')); return }
  // 裸 ID / URL → 后端解析（本地 ads_cache 优先，FB 兜底）自动匹配主页 + 内容预览
  postResolving.value = true
  try {
    const r = await POST('/fb/resolve-post', { q: raw })
    _setReusePost(r.post_id, r.page_id, null)
    applyReuseResponse(r)
    ElMessage.success(t('launch.postSelected') + ' · ' + (r.source === 'local' ? t('launch.sourceLocal') : r.source === 'fb' ? 'FB' : ''))
  } catch (e) {
    // 识别不出 → 揭示手选主页，让用户手动拼 {page}_{post}
    reuseNeedManualPage.value = true
    manualPageForPost.value = form.value.page_id || ''
    ElMessage.warning(t('launch.resolveFailManual'))
  }
  postResolving.value = false
}
// 拉帖子内容预览（编辑已存跟帖模板/手选主页拼 ID 时用，让用户看到文案/图）
const fetchReusePreview = async (postId) => {
  if (!postId) return
  try {
    const r = await POST('/fb/resolve-post', { q: postId })
    applyReuseResponse(r)
  } catch { /* 取不到就只显 ID，不阻断 */ }
}
// 应用 resolve-post 响应：设内容预览 + 克隆源广告设置(受众/版位/目标) + 自动命名
const applyReuseResponse = (r) => {
  reusePostPreview.value = { message: r.message, picture: r.picture, permalink: r.permalink_url, headline: r.headline, cta_type: r.cta_type, link: r.link }
  const s = r.ad_settings
  if (s && Object.keys(s).length) {
    applyClonedSettings(s)
    if (!form.value.name?.trim()) {
      const h = (r.headline || '').trim()
      form.value.name = h ? `${t('launch.postSourceReuse')}·${h.slice(0, 14)}` : `${t('launch.postSourceReuse')} ${form.value.reuse_post_ref.split('_').pop().slice(-6)}`
    }
    snapshotForm()  // 重快照（含克隆+命名，避免一开就标 dirty）
  }
}
// 把克隆的源广告设置写进表单（系列目标/广告组受众+版位）
const applyClonedSettings = (s) => {
  const f = form.value
  if (s.objective) f.objective = s.objective
  if (s.optimization_goal) f.optimization_goal = s.optimization_goal
  if (s.billing_event) f.billing_event = s.billing_event
  if (s.destination_type) f.destination_type = s.destination_type
  if (s.bid_strategy) f.bid_strategy = s.bid_strategy
  if (s.audience_age_min) f.audience_age_min = s.audience_age_min
  if (s.audience_age_max) f.audience_age_max = s.audience_age_max
  if (s.audience_gender !== undefined && s.audience_gender !== 0) f.audience_gender = s.audience_gender
  if (s.audience_countries?.length) f.audience_countries = s.audience_countries
  if (s.audience_interests?.length) f.audience_interests = s.audience_interests
  if (s.manual_placement !== undefined) f.manual_placement = s.manual_placement
  if (s.placement_platforms?.length) f.placement_platforms = s.placement_platforms
  if (s.placement_devices?.length) f.placement_devices = s.placement_devices
  if (s.facebook_positions?.length) f.facebook_positions = s.facebook_positions
  advantage_audience.value = !(s.audience_interests?.length)  // 有手选兴趣→关 Advantage+
}
// 手选主页 + 裸帖子号 → 拼 {page}_{post}
const confirmManualPostWithPage = () => {
  const raw = manualPostId.value.trim(); const pg = manualPageForPost.value
  if (!pg) return ElMessage.warning(t('launch.postPickerNeedPage'))
  const m = raw.match(/(\d{10,})/)
  if (!m) return ElMessage.warning(t('launch.resolvePostFail'))
  _setReusePost(`${pg}_${m[1]}`, pg, null)
  fetchReusePreview(`${pg}_${m[1]}`)
  ElMessage.success(t('launch.postSelected'))
}
const setPostSource = (src) => {
  form.value.post_source = src
  if (src !== 'reuse') { reuseNeedManualPage.value = false; manualPageForPost.value = '' }
}
// 平台：编辑器内只读 chip（不可中途切——TT/FB 三件套结构不同，切平台=换链路）；
// 平台选择在两处：列表筛选 chip + 「+ 新建模板」下拉（openNew(p)）
const isTt = computed(() => form.value.platform === 'tt')
// 双平台表单交互核心：表单模板下拉按投放模板平台过滤（TT 模板只列 TT 表单模板，
// 平台编辑器内只读 → 不存在中途切平台后引用失效的问题）
const formTemplatesForPlat = computed(() =>
  formTemplates.value.filter(f => (f.platform || 'fb') === (form.value.platform || 'fb')))
const clearReusePost = () => { form.value.reuse_post_ref = ''; reusePostPreview.value = null; reuseNeedManualPage.value = false }
// 卡片完整性判断（列表用，不需打开编辑器）
const _tplMissing = (tpl) => {
  const m = []
  if (!tpl.name?.trim()) m.push(t('launch.fieldTplName'))
  if (!tpl.asset_id) m.push(t('launch.asset'))
  if (!tpl.budget_usd || tpl.budget_usd <= 0) m.push(t('launch.budget'))
  if (!tpl.landing_url && !['OUTCOME_AWARENESS'].includes(tpl.objective)) m.push(t('launch.landing'))
  return m
}
const _tplReady = (tpl) => _tplMissing(tpl).length === 0

// ── 1:1 三层结构模式（系列 → 广告组 → 广告 树）：与后端 _validate_structure 同形状 ──
// 节点字段空/0/null = 回退模板级（系列层平铺字段即默认值）；enabled 整链（组开+广告开）才消耗
const TREE_ADSETS_MAX = 10, TREE_ADS_PER_ADSET_MAX = 20, TREE_ASSETS_PER_NODE_MAX = 50, TREE_ADS_MAX = 200
const editMode = ref('flat')   // flat=平铺（旧路径，绑定不动）/ tree=结构
let _keySeq = 0
const _nk = (p) => `${p}_${++_keySeq}`
const tree = ref({ adsets: [] })
const treeSel = ref({ type: 'campaign', si: -1, ai: -1 })   // campaign / adset / ad（现仅作选择器目标锚点）
const expandedTreeKeys = ref(new Set())
// FB 创建流三段手风琴（campaign/adset/ad 各段可折叠，默认全展）
const secOpen = ref({ campaign: true, adset: true, ad: true })
const resetSecOpen = () => { secOpen.value = { campaign: true, adset: true, ad: true } }
const toggleSec = (k) => { secOpen.value = { ...secOpen.value, [k]: !secOpen.value[k] } }
// 广告小卡展开态（key=节点 key）；跟帖输入框按节点存（nodeReuseInputs）
const expandedAdKeys = ref(new Set())
const toggleAdExpand = (key) => {
  const s = new Set(expandedAdKeys.value)
  s.has(key) ? s.delete(key) : s.add(key)
  expandedAdKeys.value = s
}
const nodeReuseInputs = ref({})
// 特殊广告类别：表单存 JSON 数组串（后端口径），多选下拉双向映射
const specialCatsSel = computed({
  get: () => { try { const v = JSON.parse(form.value.special_ad_categories || '[]'); return Array.isArray(v) ? v : [] } catch { return [] } },
  set: (v) => { form.value.special_ad_categories = (v && v.length) ? JSON.stringify([...v].sort()) : '' },
})
// 已声明特殊广告类别 → 年龄/性别定向被 FB 强制忽略（组卡受众区警告 + 输入禁用）
const hasSpecialCats = computed(() => specialCatsSel.value.length > 0)
// 组节点内联受众（audience_json 的编辑态；保存时序列化回 audience_json 列）
const blankNodeAud = () => ({ countries: [], interests: [], age_min: 18, age_max: 65, gender: 0 })
const _audFromJson = (j) => {
  const a = blankNodeAud()
  try {
    const p = typeof j === 'string' ? JSON.parse(j || '{}') : (j || {})
    a.countries = Array.isArray(p.countries) ? p.countries : []
    a.interests = (Array.isArray(p.interests) ? p.interests : []).map(i => ({ id: String(i.id ?? ''), name: i.name || '' })).filter(i => i.id)
    a.age_min = p.age_min || 18
    a.age_max = p.age_max || 65
    a.gender = p.gender || 0
  } catch {}
  return a
}
const blankTreeAdset = () => ({
  key: _nk('as'), name: '', enabled: false, budget_usd: null,
  audience_id: 0, audience_json: '', optimization_goal: '', billing_event: '', advanced_config: '',
  conv_location: '', placement_mode: '', publisher_platforms: [], device_platforms: [],
  aud: blankNodeAud(),
  budget_type: 'daily', lifetime_budget_usd: null, schedule_start: '', schedule_end: '', pacing: '',
  bid_amount_usd: null, minimum_roas: null,
  ads: [],
})
const blankTreeAd = () => ({
  key: _nk('ad'), name: '', enabled: false, asset_ids: [],
  headline: '', body: '', cta_type: '', ad_language: '',
  landing_page_id: 0, landing_url: '', subcode_slug: '',
  message_template_id: 0, lead_form_template_id: 0, pixel_id: '',
  post_source: 'new', reuse_post_ref: '',
  link_description: '', multi: false,
})
// 存库 structure 回读时补默认值（后端保存已规范化，此处兜底脏数据）
const _numOrNull = (v) => (v === '' || v === null || v === undefined || isNaN(Number(v))) ? null : Number(v)
const normalizeTree = (adsets) => adsets.map(s => ({
  ...blankTreeAdset(), ...s,
  key: s.key || _nk('as'),
  enabled: !!s.enabled,
  budget_usd: s.budget_usd ?? null,
  lifetime_budget_usd: _numOrNull(s.lifetime_budget_usd),
  bid_amount_usd: _numOrNull(s.bid_amount_usd),
  minimum_roas: _numOrNull(s.minimum_roas),
  schedule_start: s.schedule_start || '', schedule_end: s.schedule_end || '',
  pacing: s.pacing === 'accelerated' ? 'accelerated' : '',
  budget_type: s.budget_type === 'lifetime' ? 'lifetime' : 'daily',
  audience_id: s.audience_id || 0,
  conv_location: (CONV_LOCATIONS_BY_OBJECTIVE[form.value.objective] || []).includes(s.conv_location) ? s.conv_location : '',
  placement_mode: s.placement_mode === 'manual' ? 'manual' : '',
  publisher_platforms: [...(s.publisher_platforms || [])],
  device_platforms: [...(s.device_platforms || [])],
  aud: _audFromJson(s.audience_json),
  ads: (s.ads || []).map(a => ({
    ...blankTreeAd(), ...a,
    key: a.key || _nk('ad'),
    enabled: !!a.enabled,
    asset_ids: [...(a.asset_ids || [])],
    landing_page_id: a.landing_page_id || 0,
    message_template_id: a.message_template_id || 0,
    lead_form_template_id: a.lead_form_template_id || 0,
    post_source: a.post_source === 'reuse' ? 'reuse' : 'new',
    link_description: a.link_description || '',
    multi: (a.asset_ids || []).length > 1,
  })),
}))
// 素材库（结构模式多选/预览用；懒加载一次）
const treeAssets = ref([])
let _treeAssetsLoaded = false
const ensureTreeAssets = async () => {
  if (_treeAssetsLoaded) return
  try { treeAssets.value = await GET('/assets'); _treeAssetsLoaded = true } catch {}
}
const treeAssetById = (id) => (id ? treeAssets.value.find(x => x.id === id) || null : null)
const selAdset = computed(() => (treeSel.value.type === 'adset' || treeSel.value.type === 'ad')
  ? (tree.value.adsets[treeSel.value.si] || null) : null)
const selAd = computed(() => (treeSel.value.type === 'ad' && selAdset.value)
  ? ((selAdset.value.ads || [])[treeSel.value.ai] || null) : null)
const adAsset0 = (a) => ((a && (a.asset_ids || []).length) ? treeAssetById(a.asset_ids[0]) : null)
const adsetNodeLabel = (s, si) => s.name || t('launch.treeGroupN', { n: si + 1 })
const adNodeLabel = (a, ai) => a.name || ((a.asset_ids || []).length > 1
  ? t('launch.treeAssetGroupN', { n: a.asset_ids.length }) : t('launch.treeAdN', { n: ai + 1 }))
// 完备度圆点：广告 绿=有素材/跟帖引用 黄=只有文案 灰=全空；组 绿=含绿广告 黄=有广告无绿 灰=无广告
const adDot = (a) => {
  if ((a.asset_ids || []).length || (a.post_source === 'reuse' && a.reuse_post_ref)) return 'g'
  if (a.headline || a.body || a.cta_type) return 'y'
  return 'c'
}
const adsetDot = (s) => {
  if (!(s.ads || []).length) return 'c'
  return (s.ads || []).some(a => adDot(a) === 'g') ? 'g' : 'y'
}
const _expNode = (ads) => (ads || []).reduce((m, a) => m + Math.max((a.asset_ids || []).length, 1), 0)
const treeExpandedTotal = () => tree.value.adsets.reduce((n, s) => n + _expNode(s.ads), 0)
const selectTreeNode = (type, si = -1, ai = -1) => { treeSel.value = { type, si, ai } }
const toggleTreeExpand = (key) => {
  const s = new Set(expandedTreeKeys.value)
  s.has(key) ? s.delete(key) : s.add(key)
  expandedTreeKeys.value = s
}
// 组卡「出价控制」折叠区（默认收起；已设覆盖值时标题行右侧显示当前值，防隐藏已有配置）
const bidOpenKeys = ref(new Set())
const toggleBidCtrl = (key) => {
  const s = new Set(bidOpenKeys.value)
  s.has(key) ? s.delete(key) : s.add(key)
  bidOpenKeys.value = s
}
const bidCtrlSummary = (s) => {
  const parts = []
  if (BID_NEEDS_AMOUNT.includes(form.value.bid_strategy) && s.bid_amount_usd !== null && s.bid_amount_usd !== '') parts.push('$' + s.bid_amount_usd)
  if (BID_NEEDS_ROAS.includes(form.value.bid_strategy) && s.minimum_roas !== null && s.minimum_roas !== '') parts.push('ROAS ' + s.minimum_roas)
  return parts.join(' · ')
}
// ── 组卡新区块（批次I）：受众折叠区（默认展开）/ 版位折叠区（默认收起）──
const audFoldKeys = ref(new Set())   // 有 key = 收起（默认展开——受众是 P0 必经设置，不藏）
const plOpenKeys = ref(new Set())    // 有 key = 展开（默认收起，同出价控制）
const toggleAudSec = (key) => {
  const s = new Set(audFoldKeys.value)
  s.has(key) ? s.delete(key) : s.add(key)
  audFoldKeys.value = s
}
const togglePlSec = (key) => {
  const s = new Set(plOpenKeys.value)
  s.has(key) ? s.delete(key) : s.add(key)
  plOpenKeys.value = s
}
// 受众摘要（折叠头 chip）：受众库名 / 国家·兴趣数 / 未设置（默认 US 警示色）
const nodeAudienceEmpty = (s) => !s.audience_id && !(s.aud?.countries || []).length && !(s.aud?.interests || []).length
const nodeAudSummary = (s) => {
  if (s.audience_id) {
    const a = savedAudiences.value.find(x => x.id === s.audience_id)
    return a ? a.name : '#' + s.audience_id
  }
  const c = (s.aud?.countries || []).join(',') || ''
  const n = (s.aud?.interests || []).length
  if (!c && !n) return ''
  return (c || '—') + ' · ' + t('launch.interestCount', { n })
}
// 版位摘要：自动（Advantage+）/ 手动 · N 平台
const nodePlSummary = (s) => s.placement_mode === 'manual'
  ? t('launch.plSumManual') + ' · ' + t('launch.plSumPlatforms', { n: (s.publisher_platforms || []).length })
  : t('launch.plSumAuto')
// 组节点版位勾选（平台/设备；auto 时省略全部版位键）
const toggleNodePlatform = (s, pv) => {
  const arr = s.publisher_platforms || []
  const i = arr.indexOf(pv)
  if (i >= 0) arr.splice(i, 1); else arr.push(pv)
  s.publisher_platforms = [...arr]
}
const toggleNodeDevice = (s, dv) => {
  const arr = s.device_platforms || []
  const i = arr.indexOf(dv)
  if (i >= 0) arr.splice(i, 1); else arr.push(dv)
  s.device_platforms = [...arr]
}
// 组节点兴趣搜索：查询词按节点存（nodeInterestQ），结果共享、只渲染在发起搜索的组卡
const nodeInterestQ = ref({})
const interestNodeKey = ref('')
const searchInterestsForNode = async (s) => {
  const q = (nodeInterestQ.value[s.key] || '').trim()
  if (!q) return
  interestNodeKey.value = s.key
  interestSearching.value = true
  try { interestResults.value = await GET('/audiences/search?q=' + encodeURIComponent(q) + '&limit=10') }
  catch (e) { showError(e, t('launch.interestSearchFail')) }
  interestSearching.value = false
}
const addNodeInterest = (s, it) => {
  if (!s.aud) s.aud = blankNodeAud()
  if (!s.aud.interests.some(x => x.id === String(it.id))) s.aud.interests.push({ id: String(it.id), name: it.name })
}
const removeNodeInterest = (s, i) => s.aud.interests.splice(i, 1)
const nodeInterestAdded = (s, id) => (s.aud?.interests || []).some(x => x.id === String(id))
const clearNodeInterestSearch = (s) => { interestNodeKey.value = ''; interestResults.value = []; nodeInterestQ.value = { ...nodeInterestQ.value, [s.key]: '' } }
const expandAllTree = () => { expandedTreeKeys.value = new Set(tree.value.adsets.map(s => s.key)) }
const addTreeAdset = () => {
  if (tree.value.adsets.length >= TREE_ADSETS_MAX) return ElMessage.warning(t('launch.treeErrAdsetsMax', { n: TREE_ADSETS_MAX }))
  tree.value.adsets.push(blankTreeAdset())
  const si = tree.value.adsets.length - 1
  expandedTreeKeys.value = new Set([...expandedTreeKeys.value, tree.value.adsets[si].key])
  selectTreeNode('adset', si)
}
const addTreeAd = (si) => {
  const s = tree.value.adsets[si]; if (!s) return
  if ((s.ads || []).length >= TREE_ADS_PER_ADSET_MAX) return ElMessage.warning(t('launch.treeErrAdsMax', { n: TREE_ADS_PER_ADSET_MAX }))
  if (treeExpandedTotal() >= TREE_ADS_MAX) return ElMessage.warning(t('launch.treeErrAdsTotalMax', { n: TREE_ADS_MAX }))
  const ad = blankTreeAd()
  s.ads = [...(s.ads || []), ad]
  expandedAdKeys.value = new Set([...expandedAdKeys.value, ad.key])
  selectTreeNode('ad', si, s.ads.length - 1)
}
const copyTreeAdset = (si) => {
  const src = tree.value.adsets[si]; if (!src) return
  if (tree.value.adsets.length >= TREE_ADSETS_MAX) return ElMessage.warning(t('launch.treeErrAdsetsMax', { n: TREE_ADSETS_MAX }))
  const c = JSON.parse(JSON.stringify(src))
  c.key = _nk('as')
  c.ads = (c.ads || []).map(a => ({ ...a, key: _nk('ad') }))
  if (treeExpandedTotal() + _expNode(c.ads) > TREE_ADS_MAX) return ElMessage.warning(t('launch.treeErrAdsTotalMax', { n: TREE_ADS_MAX }))
  tree.value.adsets.splice(si + 1, 0, c)
  expandedTreeKeys.value = new Set([...expandedTreeKeys.value, c.key])
  selectTreeNode('adset', si + 1)
}
const copyTreeAd = (si, ai) => {
  const s = tree.value.adsets[si]; if (!s) return
  if ((s.ads || []).length >= TREE_ADS_PER_ADSET_MAX) return ElMessage.warning(t('launch.treeErrAdsMax', { n: TREE_ADS_PER_ADSET_MAX }))
  const a = s.ads[ai]; if (!a) return
  if (treeExpandedTotal() + Math.max((a.asset_ids || []).length, 1) > TREE_ADS_MAX) return ElMessage.warning(t('launch.treeErrAdsTotalMax', { n: TREE_ADS_MAX }))
  const c = { ...JSON.parse(JSON.stringify(a)), key: _nk('ad') }
  s.ads.splice(ai + 1, 0, c)
  expandedAdKeys.value = new Set([...expandedAdKeys.value, c.key])
  selectTreeNode('ad', si, ai + 1)
}
const removeTreeAdset = async (si) => {
  const s = tree.value.adsets[si]; if (!s) return
  try {
    await ElMessageBox.confirm(t('launch.treeDelGroupConfirm', { name: adsetNodeLabel(s, si) }), t('common.confirm'),
      { type: 'warning', confirmButtonClass: 'el-button--danger' })
  } catch { return }
  tree.value.adsets.splice(si, 1)
  if (treeSel.value.si === si) selectTreeNode('campaign')
  else if (treeSel.value.si > si) treeSel.value = { ...treeSel.value, si: treeSel.value.si - 1 }
}
const removeTreeAd = (si, ai) => {
  const s = tree.value.adsets[si]; if (!s) return
  s.ads.splice(ai, 1)
  if (treeSel.value.type === 'ad' && treeSel.value.si === si) {
    if (!s.ads.length) selectTreeNode('adset', si)
    else if (treeSel.value.ai >= s.ads.length) treeSel.value = { type: 'ad', si, ai: s.ads.length - 1 }
  }
}
// 平铺 ↔ 结构 互转（平铺值↔第一组第一广告，防丢数据）
const adFromFlat = () => ({
  ...blankTreeAd(),
  asset_ids: form.value.asset_id ? [form.value.asset_id] : [],
  headline: form.value.headline || '', body: form.value.body || '', cta_type: form.value.cta_type || '',
  link_description: form.value.link_description || '',
  ad_language: form.value.ad_language || '',
  landing_page_id: form.value.landing_page_id || 0, landing_url: form.value.landing_url || '',
  subcode_slug: form.value.subcode_slug || '',
  message_template_id: form.value.message_template_id || 0, lead_form_template_id: form.value.lead_form_template_id || 0,
  pixel_id: form.value.pixel_id || '',
  post_source: form.value.post_source === 'reuse' ? 'reuse' : 'new', reuse_post_ref: form.value.reuse_post_ref || '',
})
const flatFromTree = () => {
  const s = tree.value.adsets[0]; if (!s) return
  form.value.audience_id = s.audience_id || 0
  if (s.optimization_goal) form.value.optimization_goal = s.optimization_goal
  if (s.billing_event) form.value.billing_event = s.billing_event
  if (s.budget_usd) form.value.budget_usd = s.budget_usd
  const a = (s.ads || [])[0]; if (!a) return
  form.value.asset_id = (a.asset_ids || [])[0] ?? null
  if (a.headline) form.value.headline = a.headline
  if (a.body) form.value.body = a.body
  if (a.cta_type) form.value.cta_type = a.cta_type
  if (a.link_description) form.value.link_description = a.link_description
  if (a.ad_language) form.value.ad_language = a.ad_language
  if (a.landing_page_id) form.value.landing_page_id = a.landing_page_id
  if (a.landing_url) form.value.landing_url = a.landing_url
  if (a.subcode_slug) form.value.subcode_slug = a.subcode_slug
  if (a.message_template_id) form.value.message_template_id = a.message_template_id
  if (a.lead_form_template_id) form.value.lead_form_template_id = a.lead_form_template_id
  if (a.pixel_id) form.value.pixel_id = a.pixel_id
  if (a.post_source === 'reuse' && a.reuse_post_ref) {
    form.value.post_source = 'reuse'; form.value.reuse_post_ref = a.reuse_post_ref
  }
}
const _synthTreeFromFlat = () => {
  const s = blankTreeAdset()
  s.audience_id = form.value.audience_id || 0
  s.aud = {
    countries: [...(form.value.audience_countries || [])],
    interests: [...(form.value.audience_interests || [])],
    age_min: form.value.audience_age_min || 18,
    age_max: form.value.audience_age_max || 65,
    gender: form.value.audience_gender || 0,
  }
  s.optimization_goal = form.value.optimization_goal || ''
  s.billing_event = form.value.billing_event || ''
  s.ads = [adFromFlat()]
  tree.value = { adsets: [s] }
  expandAllTree(); ensureTreeAssets()
  expandedAdKeys.value = new Set(tree.value.adsets.flatMap(x => (x.ads || []).map(a => a.key)))
  editMode.value = 'tree'
}
const onModeSwitch = async (nv) => {
  if (nv === 'tree') {
    if (!tree.value.adsets.length) {
      try { await ElMessageBox.confirm(t('launch.treeSwitchToTree'), t('common.confirm'), { type: 'warning' }) }
      catch { editMode.value = 'flat'; return }
      const s = blankTreeAdset()
      s.audience_id = form.value.audience_id || 0
      s.optimization_goal = form.value.optimization_goal || ''
      s.billing_event = form.value.billing_event || ''
      s.ads = [adFromFlat()]
      tree.value = { adsets: [s] }
      expandAllTree(); ensureTreeAssets()
      selectTreeNode('adset', 0)
    }
  } else if (tree.value.adsets.length) {
    try { await ElMessageBox.confirm(t('launch.treeSwitchToFlat'), t('common.confirm'), { type: 'warning' }) }
    catch { editMode.value = 'tree'; return }
    flatFromTree()
    tree.value = { adsets: [] }; expandedTreeKeys.value = new Set()
    selectTreeNode('campaign')
  }
}
// 保存前树净化：空输入的数字字段 '' → null（后端 float('') 会 400）+ 浅拷贝防中途变更；
// aud（内联受众编辑态）序列化回 audience_json；auto 版位省略全部版位键（Advantage+ 语义）
const _cleanTreeForSave = () => tree.value.adsets.map(s => {
  const { aud, ...rest } = s   // aud 是 UI 态，不入 structure
  const _manual = s.placement_mode === 'manual' && (s.publisher_platforms || []).length > 0
  return {
    ...rest,
    budget_usd: (s.budget_usd === '' || s.budget_usd === undefined) ? null : s.budget_usd,
    lifetime_budget_usd: _numOrNull(s.lifetime_budget_usd),
    bid_amount_usd: _numOrNull(s.bid_amount_usd),
    minimum_roas: _numOrNull(s.minimum_roas),
    schedule_start: s.schedule_start || '', schedule_end: s.schedule_end || '',
    pacing: s.pacing === 'accelerated' ? 'accelerated' : '',
    budget_type: s.budget_type === 'lifetime' ? 'lifetime' : 'daily',
    audience_id: s.audience_id || 0,
    // 选了受众库 → 清内联 audience_json（部署走 SavedAudience 分支）；否则内联生效
    audience_json: s.audience_id ? '' : JSON.stringify({
      countries: (aud?.countries || []), interests: (aud?.interests || []),
      age_min: (aud?.age_min || 18), age_max: (aud?.age_max || 65), gender: (aud?.gender || 0),
    }),
    conv_location: s.conv_location || '',
    placement_mode: _manual ? 'manual' : '',
    publisher_platforms: _manual ? [...(s.publisher_platforms || [])] : [],
    device_platforms: _manual ? [...(s.device_platforms || [])] : [],
    ads: (s.ads || []).map(a => {
      const { multi, ...arest } = a   // multi 是 UI 态，不入 structure
      return { ...arest, asset_ids: [...(a.asset_ids || [])] }
    }),
  }
})
// 模板级预算校验（批G）：日预算恒必填（部署守卫口径）；lifetime 另需金额与上限；出价额/ROAS 正数
const _budgetErrors = () => {
  const errs = []
  if (form.value.budget_type !== 'lifetime') {
    if (!form.value.budget_usd || Number(form.value.budget_usd) <= 0) errs.push(t('launch.fieldDailyBudget'))
    if (Number(form.value.budget_usd) > 5000) errs.push(t('launch.fieldBudgetCap', { n: 5000 }))
  }
  if (form.value.budget_type === 'lifetime') {
    if (!(Number(form.value.lifetime_budget_usd) > 0)) errs.push(t('launch.fieldLifetimeBudget'))
    if (Number(form.value.lifetime_budget_usd) > 50000) errs.push(t('launch.fieldLifetimeBudgetCap', { n: 50000 }))
  }
  if (form.value.bid_amount_usd !== null && form.value.bid_amount_usd !== '' && !(Number(form.value.bid_amount_usd) > 0))
    errs.push(t('launch.fieldBidAmount'))
  if (form.value.minimum_roas !== null && form.value.minimum_roas !== '' && !(Number(form.value.minimum_roas) > 0))
    errs.push(t('launch.fieldMinRoas'))
  return errs
}
// 结构模式保存前校验（与后端 _validate_structure 同口径，提前给清晰提示）
const validateTree = () => {
  const errs = []
  if (!form.value.name?.trim()) errs.push(t('launch.fieldTplName'))
  errs.push(..._budgetErrors())
  const adsets = tree.value.adsets
  if (!adsets.length) { errs.push(t('launch.treeErrNoAdset')); return errs }
  if (adsets.length > TREE_ADSETS_MAX) errs.push(t('launch.treeErrAdsetsMax', { n: TREE_ADSETS_MAX }))
  let total = 0
  adsets.forEach((s, si) => {
    if (!(s.ads || []).length) errs.push(t('launch.treeErrAdsetNeedsAd', { name: adsetNodeLabel(s, si) }))
    if ((s.ads || []).length > TREE_ADS_PER_ADSET_MAX) errs.push(t('launch.treeErrAdsMax', { n: TREE_ADS_PER_ADSET_MAX }))
    if (s.budget_usd !== null && s.budget_usd !== '' && !(Number(s.budget_usd) > 0))
      errs.push(t('launch.treeErrBudget', { name: adsetNodeLabel(s, si) }))
    if (s.budget_usd !== null && s.budget_usd !== '' && Number(s.budget_usd) > 5000)
      errs.push(t('launch.treeErrBudgetCap', { name: adsetNodeLabel(s, si), n: 5000 }))
    // 批G组节点：lifetime 必须带组级排期（后端保存 422 同口径）；出价额/ROAS 正数
    if (s.budget_type === 'lifetime') {
      if (!(s.schedule_start && s.schedule_end)) errs.push(t('launch.treeErrLifetimeSchedule', { name: adsetNodeLabel(s, si) }))
      if (s.lifetime_budget_usd !== null && s.lifetime_budget_usd !== '' && !(Number(s.lifetime_budget_usd) > 0))
        errs.push(t('launch.treeErrBudget', { name: adsetNodeLabel(s, si) }))
      if (Number(s.lifetime_budget_usd) > 50000)
        errs.push(t('launch.treeErrLifetimeCap', { name: adsetNodeLabel(s, si), n: 50000 }))
    }
    if (s.bid_amount_usd !== null && s.bid_amount_usd !== '' && !(Number(s.bid_amount_usd) > 0))
      errs.push(t('launch.treeErrBidAmount', { name: adsetNodeLabel(s, si) }))
    if (s.minimum_roas !== null && s.minimum_roas !== '' && !(Number(s.minimum_roas) > 0))
      errs.push(t('launch.treeErrMinRoas', { name: adsetNodeLabel(s, si) }))
    if (s.budget_usd !== null && s.budget_usd !== '' && Number(s.budget_usd) > 5000)
      errs.push(t('launch.treeErrBudgetCap', { name: adsetNodeLabel(s, si), n: 5000 }))
    // 批次I：转化位置 × 目标 / 手动版位至少一平台（后端保存 422 同口径，提前给清晰提示）
    if (s.conv_location && !convLocationsForObj.value.includes(s.conv_location))
      errs.push(t('launch.treeErrConvLoc', { name: adsetNodeLabel(s, si), loc: s.conv_location }))
    if (s.placement_mode === 'manual' && !(s.publisher_platforms || []).length)
      errs.push(t('launch.treeErrPlacement', { name: adsetNodeLabel(s, si) }))
    ;(s.ads || []).forEach(a => {
      if ((a.asset_ids || []).length > TREE_ASSETS_PER_NODE_MAX) errs.push(t('launch.treeErrAssetsMax', { n: TREE_ASSETS_PER_NODE_MAX }))
      total += Math.max((a.asset_ids || []).length, 1)
      if (a.post_source === 'reuse') {
        if (!a.reuse_post_ref) errs.push(t('launch.treeErrReuseRef'))
        if ((a.asset_ids || []).length > 1) errs.push(t('launch.treeErrReuseMulti'))
      }
    })
  })
  if (total > TREE_ADS_MAX) errs.push(t('launch.treeErrAdsTotalMax', { n: TREE_ADS_MAX }))
  return errs
}
// 广告节点辅助：子码过滤 / 落地页联动 / 模板下拉 / 跟帖
const subcodesForNode = (node) => {
  if (!node.landing_page_id) return []
  return allSubcodes.value.filter(s => s.page_id === node.landing_page_id)
}
const onNodeLandingChange = async (node) => {
  const p = landingPages.value.find(x => x.id === node.landing_page_id)
  if (p?.public_url) node.landing_url = p.public_url
  if (node.subcode_slug && !subcodesForNode(node).some(s => s.slug === node.subcode_slug)) node.subcode_slug = ''
  if (node.landing_page_id) {
    try {
      const r = await GET(`/subcodes?page_id=${node.landing_page_id}&status=all`)
      const others = allSubcodes.value.filter(s => s.page_id !== node.landing_page_id)
      allSubcodes.value = [...others, ...(r.items || [])]
    } catch {}
  }
}
const setNodeMsgTpl = (node, v) => { node.message_template_id = v || 0 }
const setNodeFormTpl = (node, v) => { node.lead_form_template_id = v || 0 }
const setNodePostSource = (node, src) => {
  node.post_source = src === 'reuse' ? 'reuse' : 'new'
  if (node.post_source === 'reuse' && (node.asset_ids || []).length > 1) {
    node.asset_ids = node.asset_ids.slice(0, 1)
    node.multi = false
    ElMessage.info(t('launch.treeReuseTruncated'))
  }
}
// 广告节点「多选素材」开关=节点字段 multi（UI 态，保存时剔除）；跟帖输入按节点存
const nodeResolving = ref(false)
const nodePostPreviews = ref({})    // {nodeKey: {message,picture,permalink}}
const applyNodePostPreview = (node, r) => {
  nodePostPreviews.value = { ...nodePostPreviews.value, [node.key]: { message: r.message, picture: r.picture, permalink: r.permalink_url } }
}
const fetchNodePostPreview = async (node) => {
  if (!node.reuse_post_ref) return
  try { applyNodePostPreview(node, await POST('/fb/resolve-post', { q: node.reuse_post_ref })) } catch {}
}
const confirmNodePost = async (node) => {
  const raw = (nodeReuseInputs.value[node.key] || '').trim()
  if (!raw) return
  const m1 = raw.match(/(\d+_\d+)/)
  if (m1) {
    node.reuse_post_ref = m1[1]
    if (!form.value.page_id) form.value.page_id = m1[1].split('_')[0]
    fetchNodePostPreview(node)
    ElMessage.success(t('launch.postSelected')); nodeReuseInputs.value = { ...nodeReuseInputs.value, [node.key]: '' }
    return
  }
  nodeResolving.value = true
  try {
    const r = await POST('/fb/resolve-post', { q: raw })
    node.reuse_post_ref = r.post_id
    if (r.page_id) form.value.page_id = r.page_id
    applyNodePostPreview(node, r)
    ElMessage.success(t('launch.postSelected')); nodeReuseInputs.value = { ...nodeReuseInputs.value, [node.key]: '' }
  } catch { ElMessage.warning(t('launch.resolveFailManual')) }
  nodeResolving.value = false
}
const clearNodePost = (node) => {
  node.reuse_post_ref = ''
  const m = { ...nodePostPreviews.value }; delete m[node.key]; nodePostPreviews.value = m
}
// 小卡内打开选择器：先把 treeSel 锚到该节点（pickAsset/pickPost 写 selAd）
const openAssetPickerForAd = (si, ai) => { selectTreeNode('ad', si, ai); openAssetPicker() }
const openPostPickerForAd = (si, ai) => { selectTreeNode('ad', si, ai); openPostPicker() }

// 编辑（openNew(p)：p='fb'/'tt' 建模板时定平台；缺省 fb=跟帖预填流用，不弹目标选择）
// 新建 FB 模板先弹目标选择（对齐 FB Objective Picker）；TT 新建与跟帖预填直接进编辑器
// 新建 FB 模板默认进结构模式（预建 1 空组 + 1 空广告节点）；TT 无结构链路 → 平铺
const objPickerOpen = ref(false)
const objPickSel = ref('OUTCOME_AWARENESS')
const objPickName = ref('')
const objNameShow = ref(false)
const objPickerFromEditor = ref(false)   // true=编辑器内点目标 chip 重开（不重开编辑器，只换目标）
const openNew = (p) => {
  if (p === 'fb') {   // 下拉显式建 FB → 先选目标（跟帖预填 openNew() 无参不进这里）
    objPickSel.value = 'OUTCOME_AWARENESS'
    objPickName.value = ''; objNameShow.value = false
    objPickerFromEditor.value = false
    objPickerOpen.value = true
    return
  }
  _startNew(p)
}
const _startNew = (p) => { editing.value = null; form.value = blankForm();
  advantage_creative.value = true; performance_goal_cpa.value = 0   // 全库审查P1：游离ref重置，防跨模板污染出价策略
  if (p) form.value.platform = p; editingAsset.value = null; validationErrors.value = []; editOpen.value = true
  expandedAdKeys.value = new Set(); bidOpenKeys.value = new Set()
  if ((p || 'fb') === 'tt') {
    editMode.value = 'flat'; tree.value = { adsets: [] }; expandedTreeKeys.value = new Set()
    selectTreeNode('campaign')
  } else {
    editMode.value = 'tree'
    const s = blankTreeAdset(); s.ads = [blankTreeAd()]
    tree.value = { adsets: [s] }; expandAllTree(); selectTreeNode('campaign')
    expandedAdKeys.value = new Set([s.ads[0].key])
    ensureTreeAssets()
  }
  resetSecOpen()
  snapshotForm() }
const objPickerContinue = async () => {
  if (!objPickSel.value) return
  objPickerOpen.value = false
  form.value.objective = objPickSel.value
  if (objPickName.value.trim()) form.value.name = objPickName.value.trim()
  objPickName.value = ''
  if (!objPickerFromEditor.value) {
    _startNew('fb')
    form.value.objective = objPickSel.value
    if (objPickName.value.trim()) form.value.name = objPickName.value.trim()
    await nextTick()
    snapshotForm()   // 目标弹窗带入值不标 dirty（objective watcher 默认填充在 nextTick 后落地）
  }
}
const objOpenFromEditor = () => {
  objPickSel.value = form.value.objective || 'OUTCOME_AWARENESS'
  objPickName.value = ''; objNameShow.value = false
  objPickerFromEditor.value = true
  objPickerOpen.value = true
}
const openEdit = async (tpl) => {
  advantage_creative.value = true; performance_goal_cpa.value = 0   // 全库审查P1：无条件归零（原仅在有配置时恢复，缺失时残留上一模板）
  editing.value = tpl
  const f = blankForm()
  Object.assign(f, tpl)
  // landing_page_id 后端对 NULL 返回 0；归一到 null 让 <select> 的「手动填 URL」选项（:value=null）能匹配选中
  if (!f.landing_page_id) f.landing_page_id = null
  if (tpl.audience_json) { try { const a = JSON.parse(tpl.audience_json); f.audience_countries = a.countries||[]; f.audience_interests = a.interests||[]; f.audience_age_min = a.age_min||18; f.audience_age_max = a.age_max||65; f.audience_gender = a.gender||0; f.audience_language = a.languages ? (Array.isArray(a.languages)?a.languages[0]||'':'') : '' } catch {} }
  // 从 advanced_config 恢复 Advantage+ / 版位 / 频次 / CPA（P0-3/P0-4 fix）
  if (tpl.advanced_config) {
    try {
      const adv = JSON.parse(tpl.advanced_config)
      advantage_creative.value = !!adv.is_dynamic_creative
      if (adv.targeting) {
        const tg = adv.targeting
        if (tg.publisher_platforms) { f.manual_placement = true; f.placement_platforms = tg.publisher_platforms }
        if (tg.device_platforms) f.placement_devices = tg.device_platforms
        for (const p of PLATFORMS) {
          const key = p.v + '_positions'
          if (tg[key]) f[key] = tg[key]
        }
      }
      if (adv.frequency_control_specs) f.frequency_cap = adv.frequency_control_specs[0]?.max_frequency || 0
      if (adv.bid_amount) performance_goal_cpa.value = adv.bid_amount / 100
      // 归因窗口：反推 preset（匹配常见组合，不匹配则留空）
      if (Array.isArray(adv.attribution_spec) && adv.attribution_spec.length) {
        const sig = adv.attribution_spec.map(x => `${x.event_type}:${x.window_days}`).sort().join(',')
        const map = { 'CLICK:1': '1d_click', 'CLICK:7': '7d_click',
          'CLICK:1,IMPRESSION:1': '1d_click_1d_view', 'CLICK:7,IMPRESSION:1': '7d_click_1d_view' }
        f.attribution_preset = map[sig] || ''
      }
      // Dayparting：有 day_parting_schedule 表示启用
      if (Array.isArray(adv.day_parting_schedule) && adv.day_parting_schedule.length) {
        f.daypart_enabled = true
        f.daypart_cells = scheduleToGrid(adv.day_parting_schedule)
      } else {
        f.daypart_enabled = false; f.daypart_cells = emptyGrid()
      }
    } catch {}
  }
  // Advantage+ 受众默认值：有手动兴趣 → 关（保留用户的手动定向）；无 → 开
  advantage_audience.value = (f.audience_interests || []).length === 0
  // 恢复表单/消息模板选中状态（P0-2 fix）
  if (f.lead_form_template_id) { try { selectedFormTpl.value = formTemplates.value.find(x => x.id === f.lead_form_template_id) || null } catch {} }
  if (f.message_template_id) { try { selectedMsgTpl.value = msgTemplates.value.find(x => x.id === f.message_template_id) || null } catch {} }
  form.value = f
  // post_source 兜底（旧模板无此字段 → 默认 new）
  if (!form.value.post_source) form.value.post_source = 'new'
  if (!form.value.reuse_post_ref) form.value.reuse_post_ref = ''
  // 跟帖模板：拉帖子内容预览（文案/图），让用户看到选的是啥
  if (form.value.post_source === 'reuse' && form.value.reuse_post_ref) {
    reusePostPreview.value = null; fetchReusePreview(form.value.reuse_post_ref)
  } else {
    reusePostPreview.value = null
  }
  editingAsset.value = null
  if (tpl.asset_id) { try { editingAsset.value = await GET('/assets/' + tpl.asset_id) } catch {} }
  // 已绑落地页 → 预拉子码（填充子码下拉）
  if (f.landing_page_id) {
    try {
      const r = await GET(`/subcodes?page_id=${f.landing_page_id}&status=all`)
      const others = allSubcodes.value.filter(s => s.page_id !== f.landing_page_id)
      allSubcodes.value = [...others, ...(r.items || [])]
    } catch {}
  }
  // 结构模式模板：structure（JSON 串）→ 解析进树 + 进结构模式（TT 模板不支持结构，强制平铺）
  tree.value = { adsets: [] }; expandedTreeKeys.value = new Set(); selectTreeNode('campaign')
  expandedAdKeys.value = new Set(); nodeReuseInputs.value = {}; bidOpenKeys.value = new Set()
  editMode.value = 'flat'
  if (tpl.structure && !isTt.value) {
    try {
      const parsed = JSON.parse(tpl.structure)
      if (parsed?.adsets?.length) {
        tree.value = { adsets: normalizeTree(parsed.adsets) }
        editMode.value = 'tree'
        expandAllTree(); ensureTreeAssets()
        expandedAdKeys.value = new Set(tree.value.adsets.flatMap(s => (s.ads || []).map(a => a.key)))
        // 预拉各广告节点绑定落地页的子码（填充节点子码下拉）
        for (const pid of [...new Set(tree.value.adsets.flatMap(s => (s.ads || []).map(a => a.landing_page_id).filter(Boolean)))]) {
          try {
            const r = await GET(`/subcodes?page_id=${pid}&status=all`)
            const others = allSubcodes.value.filter(s => s.page_id !== pid)
            allSubcodes.value = [...others, ...(r.items || [])]
          } catch {}
        }
        // 跟帖节点内容预览（卡内展示用；本地缓存优先，取不到不阻断）
        for (const n of tree.value.adsets.flatMap(s => (s.ads || []))) {
          if (n.post_source === 'reuse' && n.reuse_post_ref) fetchNodePostPreview(n)
        }
      }
    } catch {}
  }
  resetSecOpen()
  // FB 模板一律结构模式（平铺模式已移除；无 structure 的旧模板自动合成 1 组 1 广告视图，保存即升级）
  if (!isTt.value && editMode.value === 'flat') _synthTreeFromFlat()
  validationErrors.value = []; editOpen.value = true; snapshotForm()
}
const pickAsset = async (a) => {
  // 结构模式：素材写入当前选中的广告节点（单选=替换；多选开=追加；跟帖强制单素材）
  if (editMode.value === 'tree' && treeSel.value.type === 'ad' && selAd.value) {
    const n = selAd.value
    n.asset_ids = (n.post_source === 'reuse' || !n.multi)
      ? [a.id] : [...new Set([...(n.asset_ids || []), a.id])]
    if (!n.headline && a.ai_copy?.headlines?.[0]) n.headline = a.ai_copy.headlines[0]
    if (!n.body && a.ai_copy?.bodies?.[0]) n.body = a.ai_copy.bodies[0]
    assetPickerOpen.value = false
    return
  }
  form.value.asset_id = a.id
  editingAsset.value = a
  const hs = (a.ai_copy?.headlines || []); const bs = (a.ai_copy?.bodies || [])
  if (!form.value.headline && hs[0]) form.value.headline = hs[0]
  if (!form.value.body && bs[0]) form.value.body = bs[0]
  assetPickerOpen.value = false
}
const openAssetPicker = async () => {
  assetPickerOpen.value = true; pickerLoading.value = true
  try { pickerAssets.value = await GET('/assets') } catch {}
  pickerLoading.value = false
}
const openPreview = (a) => { previewAsset.value = a; previewOpen.value = true }
const fmtSize = (n) => { if (!n) return ''; if (n >= 1e9) return (n/1e9).toFixed(1)+'B'; if (n >= 1e6) return (n/1e6).toFixed(1)+'M'; if (n >= 1e3) return Math.floor(n/1e3)+'K'; return String(n) }
// 保存
const buildAudienceJson = () => {
  const a = { countries: form.value.audience_countries||[], interests: form.value.audience_interests||[], age_min: form.value.audience_age_min||18, age_max: form.value.audience_age_max||65, gender: form.value.audience_gender||0 }
  if (form.value.audience_language) a.languages = [form.value.audience_language]
  return JSON.stringify(a)
}
const saveTpl = async () => {
  if (editMode.value === 'tree') {
    // 结构模式：树口径校验（超规模/reuse 多素材等提前拦）+ 软提示（无素材节点不阻断）
    const treeErrs = validateTree()
    if (treeErrs.length) return ElMessage.warning(t('launch.pendingMissing', { fields: treeErrs.join('、') }))
    if (!tree.value.adsets.some(s => (s.ads || []).some(a => adDot(a) === 'g')))
      ElMessage.warning(t('launch.treeWarnNoContent'))
    validationErrors.value = []
  } else {
    validationErrors.value = validateTemplate()
    if (validationErrors.value.length) {
      return ElMessage.warning(t('launch.pendingMissing', { fields: validationErrors.value.join('、') }))
    }
  }
  saving.value = true
  try {
    const body = {
      name: form.value.name, description: form.value.description,
      platform: form.value.platform || 'fb',
      objective: form.value.objective, conversion_goal: form.value.conversion_goal,
      budget_mode: form.value.budget_mode, bid_strategy: form.value.bid_strategy,
      budget_usd: Number(form.value.budget_usd), name_prefix: form.value.name_prefix,
      // FB 创建流程 1:1（批G）：预算类型/总预算/排期/投放方式/出价额/最小ROAS/特殊类别/描述
      budget_type: form.value.budget_type === 'lifetime' ? 'lifetime' : 'daily',
      lifetime_budget_usd: _numOrNull(form.value.lifetime_budget_usd),
      schedule_start: form.value.schedule_start || '', schedule_end: form.value.schedule_end || '',
      pacing: form.value.pacing === 'accelerated' ? 'accelerated' : '',
      bid_amount_usd: _numOrNull(form.value.bid_amount_usd),
      minimum_roas: _numOrNull(form.value.minimum_roas),
      special_ad_categories: form.value.special_ad_categories || '',
      link_description: form.value.link_description || '',
      spend_cap_usd: _numOrNull(form.value.spend_cap_usd),
      instagram_actor_id: (form.value.instagram_actor_id || '').trim(),
      whatsapp_phone_number: (form.value.whatsapp_phone_number || '').trim(),
      optimization_goal: form.value.optimization_goal, billing_event: form.value.billing_event,
      destination_type: form.value.destination_type, audience_id: form.value.audience_id || 0,
      // 选了保存受众 → 清内联 audience_json，部署走 SavedAudience 分支（内联非空会优先生效）
      audience_json: form.value.audience_id ? '' : buildAudienceJson(),
      advanced_config: form.value.advanced_config,
      asset_id: form.value.asset_id, headline: form.value.headline, body: form.value.body,
      page_id: form.value.page_id, pixel_id: form.value.pixel_id,
      landing_url: form.value.landing_url, cta_type: form.value.cta_type,
      subcode_slug: form.value.subcode_slug, ad_language: form.value.ad_language,
      message_template: form.value.message_template, lead_form_id: form.value.lead_form_id,
      landing_page_id: form.value.landing_page_id || null,
      lead_form_template_id: form.value.lead_form_template_id || 0,
      message_template_id: form.value.message_template_id || 0,
      beneficiary: form.value.beneficiary, payer: form.value.payer,
      post_source: form.value.post_source, reuse_post_ref: form.value.reuse_post_ref,
      // 结构模式=树 JSON（后端校验/规范化+平铺双写）；平铺=空串
      structure: editMode.value === 'tree' ? JSON.stringify({ adsets: _cleanTreeForSave() }) : '',
    }
    // Advantage+ 设置 + 性能目标 + 版位 + 频次 合并进 advanced_config
    try {
      let adv = {}
      if (body.advanced_config) {
        try { adv = JSON.parse(body.advanced_config) }
        catch { ElMessage.warning(t('launch.advJsonInvalid')); adv = {} }
      }
      // 性能目标 CPA（COST_CAP 时生效）
      if (performance_goal_cpa.value > 0) {
        body.bid_strategy = 'COST_CAP'
        adv.bid_amount = Math.round(performance_goal_cpa.value * 100) // 美元→分
      } else {
        delete adv.bid_amount
      }
      // Advantage+ 受众（FB 默认开；关时用手动定向，不加 extra）
      // Advantage+ 创意（FB 默认开；传入 is_dynamic_creative 标志；关时移除）
      if (advantage_creative.value) {
        adv.is_dynamic_creative = true
      } else {
        delete adv.is_dynamic_creative
      }
      // 版位（关时清掉结构化版位键，避免残留进 payload）
      if (editMode.value === 'tree') {
        // 树模式：版位在组节点 structure（placement_mode/publisher_platforms/device_platforms），
        // advanced_config 残留版位键会在部署深合并时顶掉节点设置——一律剥离
        if (adv.targeting) {
          delete adv.targeting.publisher_platforms
          delete adv.targeting.device_platforms
          for (const p of PLATFORMS) delete adv.targeting[p.v + '_positions']
          if (!Object.keys(adv.targeting).length) delete adv.targeting
        }
      } else if (form.value.manual_placement) {
        adv.targeting = adv.targeting || {}
        const plats = form.value.placement_platforms || []
        if (plats.length) adv.targeting.publisher_platforms = plats
        if ((form.value.placement_devices||[]).length) adv.targeting.device_platforms = form.value.placement_devices
        for (const p of PLATFORMS) {
          const positions = form.value[p.v + '_positions']
          if (positions && positions.length) adv.targeting[p.v + '_positions'] = positions
        }
      } else if (adv.targeting) {
        delete adv.targeting.publisher_platforms
        delete adv.targeting.device_platforms
        for (const p of PLATFORMS) delete adv.targeting[p.v + '_positions']
      }
      // 频次控制（0/空 = 不限，清掉残留）
      if (form.value.frequency_cap && form.value.frequency_cap > 0) {
        adv.frequency_control_specs = [{
          event: 'IMPRESSIONS', interval_days: 1, max_frequency: form.value.frequency_cap, type: 'CAP'
        }]
      } else {
        delete adv.frequency_control_specs
      }
      // 归因窗口（清空 = 用 FB 默认，删 key）
      const aSpec = attributionToSpec(form.value.attribution_preset)
      if (aSpec) adv.attribution_spec = aSpec
      else delete adv.attribution_spec
      // 时段投放 Dayparting（FB 用广告账户时区，不传 timezone；关/空 = 删 key）
      if (form.value.daypart_enabled) {
        const sched = gridToSchedule(form.value.daypart_cells)
        if (sched.length) {
          adv.day_parting_schedule = sched
          adv.pacing_type = ['day_parting']
        } else {
          delete adv.day_parting_schedule
          delete adv.pacing_type
        }
      } else {
        delete adv.day_parting_schedule
        delete adv.pacing_type
      }
      body.advanced_config = Object.keys(adv).length ? JSON.stringify(adv) : ''
    } catch {}
    if (editing.value) { await PUT('/launch-templates/' + editing.value.id, body); ElMessage.success(t('common.saved')) }
    else { await POST('/launch-templates', body); ElMessage.success(t('launch.created')) }
    editOpen.value = false; await load(); snapshotForm()
  } catch (e) { showError(e, t('launch.saveTplFail')) }
  saving.value = false
}
const removeTpl = async (tpl) => {
  try {
    await ElMessageBox.confirm(t('launch.archiveConfirm', { name: tpl.name }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' })
    await DELETE('/launch-templates/' + tpl.id)
    ElMessage.success(t('launch.archived')); await load()
  } catch (e) { if (e !== 'cancel') showError(e, t('common.opFail')) }   // 真报错要提示（如 400 有运行中 job）
}
const copyTpl = async (tpl) => {
  try {
    const r = await POST('/launch-templates/' + tpl.id + '/copy', {})
    ElMessage.success(t('launch.copiedAs', { name: r.name }))
    await load()
  } catch (e) { showError(e, t('launch.copyFail')) }
}
// 卡片 ⋯ 下拉分发（部署保留主按钮，其余操作收进来）
const onCardCmd = (cmd, tpl) => {
  if (cmd === 'edit') openEdit(tpl)
  else if (cmd === 'copy') copyTpl(tpl)
  else if (cmd === 'preflight') preflight(tpl)
  else if (cmd === 'archive') removeTpl(tpl)
}
// 预检
const preflighting = ref(false)
const preflight = async (tpl) => {
  preflighting.value = true
  try {
    // accounts 只在部署抽屉打开时加载——独立入口先拉本租户账户，取第一个 managed 正常账户预检
    // （按模板平台过滤：tt 模板只能用 TT 账户预检，否则预算/像素换算口径就错了）
    const wantPlat = tpl.platform === 'tt' ? 'tt' : 'fb'
    let accs = accounts.value.length ? accounts.value.filter(a => (a.platform || 'fb') === wantPlat) : []
    if (!accs.length) { try { accs = (await GET('/fb/accounts')).filter(a => (a.platform || 'fb') === wantPlat) } catch {} }
    const target = accs.find(x => x.account_status === 1) || accs[0]
    if (!target) { ElMessage.warning(t('launch.preflightNoAccount')); preflighting.value = false; return }
    const r = await POST('/launch-templates/' + tpl.id + '/preflight', { act_id: target.act_id })
    preflightResult.value = r; preflightVisible.value = true
  } catch (e) { showError(e, t('launch.preflightFail')) }
  preflighting.value = false
}
// 部署
// 跟帖部署：按主页权限预过滤账户（权威判定走后端 /reuse-eligible，扫候选池不只绑定令牌）
const reuseEligibleActs = ref(new Set())
const reuseDeployPage = computed(() => {
  if (deployTpl.value?.post_source !== 'reuse') return ''
  return (deployTpl.value?.reuse_post_ref || '').split('_')[0] || ''  // {page}_{post} → page
})
const accManagesReusePage = (actId) => {
  if (!reuseDeployPage.value) return true  // 非跟帖模式不限制
  return reuseEligibleActs.value.has(actId)
}
// TT 模板：只列 TikTok 账户 + 像素下拉换 TT 像素库（landing-lib platform=tt）
const ttPixels = ref([])
// 结构模板：树概览（素材在树内 → 按素材批量整块隐藏；显示组数/展开广告数/启用链路/预算合计）
const deployTree = ref(null)
const deployTreeStats = computed(() => {
  if (!deployTree.value || !deployTpl.value) return null
  const isCbo = (deployTpl.value.budget_mode || 'ABO').toUpperCase() === 'CBO'
  let m = 0, chains = 0, aboTotal = 0
  for (const s of deployTree.value) {
    for (const a of (s.ads || [])) {
      const n = Math.max((a.asset_ids || []).length, 1)   // 素材组节点按素材数展开
      m += n
      if (s.enabled && a.enabled) chains += n             // 整链开启才消耗
    }
    if (!isCbo && s.enabled) aboTotal += Number(s.budget_usd || deployTpl.value.budget_usd || 0)
  }
  return { n: deployTree.value.length, m, chains, isCbo,
           isLifetime: isCbo && (deployTpl.value.budget_type || 'daily') === 'lifetime',
           perAcc: isCbo
             ? Number((deployTpl.value.budget_type === 'lifetime'
                 ? deployTpl.value.lifetime_budget_usd : deployTpl.value.budget_usd) || 0)
             : Math.round(aboTotal * 100) / 100 }
})
// 单模式每账户日预算口径（结构模板=启用组合计/CBO 系列预算；平铺=模板预算；lifetime 用总预算额）
const singlePerAcc = computed(() => {
  if (deployTreeStats.value) return deployTreeStats.value.perAcc
  const t0 = deployTpl.value
  if (!t0) return 0
  return Number((t0.budget_type === 'lifetime' ? t0.lifetime_budget_usd : t0.budget_usd) || 0)
})
const singleIsLifetime = computed(() =>
  (deployTpl.value?.budget_type || 'daily') === 'lifetime'
  && (deployTreeStats.value ? deployTreeStats.value.isCbo : true))
const openDeploy = async (tpl) => {
  deployTpl.value = tpl; deployOpen.value = true; selectedAccs.value = new Set(); deployItems.value = {}
  reuseEligibleActs.value = new Set()
  // 三件套状态复位（像素策略回默认；权限总览收起+清缓存——令牌权限可能已变化，每次抽屉打开重拉）
  pixelStrategy.value = 'template'
  pageOverviewOpen.value = false; permPages.value = []
  permPagesLoaded = false; permPagesLoading.value = false
  deployAsset.value = null
  deployMode.value = 'single'; batchAssetIds.value = new Set()
  deployTree.value = null
  if (tpl.structure) { try { deployTree.value = JSON.parse(tpl.structure).adsets || null } catch { deployTree.value = null } }
  if (tpl.asset_id) { try { deployAsset.value = await GET('/assets/' + tpl.asset_id) } catch {} }
  accLoading.value = true
  try {
    const all = await GET('/fb/accounts')
    accounts.value = (tpl.platform === 'tt') ? all.filter(a => a.platform === 'tt') : all.filter(a => (a.platform || 'fb') === 'fb')
  } catch (e) { showError(e, t('launch.loadAccFail')) }
  if (tpl.platform === 'tt') {
    try { const ps = await GET('/landing-lib/pixels'); ttPixels.value = (ps || []).filter(p => p.platform === 'tt') } catch { ttPixels.value = [] }
  }
  if (tpl.post_source === 'reuse' && tpl.id) {
    // 后端权威判定：候选池里有能管该帖主页的写令牌的账户才可选（多令牌同账户也覆盖）
    try { const r = await GET('/launch-templates/' + tpl.id + '/reuse-eligible'); reuseEligibleActs.value = new Set(r.eligible || []) }
    catch (e) { showError(e, t('launch.loadAccFail')) }
  }
  accLoading.value = false
}
// 选中账户后拉该账户可用的主页/像素（deployItems 填模板默认值）
const ensureAccConfig = async (id) => {
  // 默认值先行（accPages 早退在后）——openDeploy 每次重置 deployItems 但不清 accPages，
  // 二开抽屉再勾选已加载过主页的账户时若先早退，deployItems[id] 缺失 → 模板 v-model 直接崩
  deployItems.value[id] = { page_id: deployTpl.value.page_id || '', pixel_id: deployTpl.value.pixel_id || '' }
  if (accPages.value[id]) return
  const acc = accounts.value.find(a => a.act_id === id)
  const credId = acc?.fb_credential_id
  if (deployTpl.value?.platform === 'tt') {
    accPages.value[id] = []   // TT 无主页概念；像素下拉用共享 ttPixels（无 per-account 差异）
    return
  }
  if (credId) {
    accLoadingConfig.value.add(id); accLoadingConfig.value = new Set(accLoadingConfig.value)
    try {
      const [pages, pixels] = await Promise.all([
        GET('/fb/credentials/' + credId + '/pages').catch(() => []),
        GET('/fb/credentials/' + credId + '/pixels').catch(() => []),
      ])
      accPages.value[id] = pages; accPixels.value[id] = pixels
      // 策略为「随机用账户像素」时，新加载池的账户立即随机填入（与已选账户保持同策略）
      if (pixelStrategy.value === 'random') {
        const pid = randomPixelFor(id)
        if (pid) deployItems.value[id] = { ...(deployItems.value[id] || {}), pixel_id: pid }
      }
    } catch {}
    accLoadingConfig.value.delete(id); accLoadingConfig.value = new Set(accLoadingConfig.value)
  }
}
const toggleAcc = async (id) => {
  const s = new Set(selectedAccs.value); s.has(id) ? s.delete(id) : s.add(id); selectedAccs.value = s
  if (s.has(id)) await ensureAccConfig(id)
}
// 批量选择：跟帖模式排除无主页权限账户；并行拉各账户配置
const _selectableAccs = () => filteredDeployAccounts.value.filter(a => !reuseDeployPage.value || accManagesReusePage(a.act_id))
const deploySelectAll = () => {
  const s = new Set(_selectableAccs().map(a => a.act_id))
  selectedAccs.value = s
  _selectableAccs().forEach(a => ensureAccConfig(a.act_id))
}
const deploySelectActive = () => {
  const s = new Set(_selectableAccs().filter(a => a.account_status === 1).map(a => a.act_id))
  selectedAccs.value = s
  _selectableAccs().filter(a => s.has(a.act_id)).forEach(a => ensureAccConfig(a.act_id))
}
const deployClearSel = () => { selectedAccs.value = new Set() }
// 账户显示名（toast 明细用；名字缺失退回 act_id）
const accLabel = (id) => accounts.value.find(a => a.act_id === id)?.name || id
// 主页权限总览：首次展开懒拉一次（每页按令牌计数分权限面——后端 OR 合并 + 逐令牌计数）
const togglePageOverview = async () => {
  pageOverviewOpen.value = !pageOverviewOpen.value
  if (pageOverviewOpen.value && !permPagesLoaded) {
    permPagesLoading.value = true
    try { const r = await GET('/leads/pages'); permPages.value = r.pages || []; permPagesLoaded = true }
    catch (e) { showError(e, t('launch.pagePermLoadFail')) }
    permPagesLoading.value = false
  }
}
const permPageSummary = computed(() => {
  const p = permPages.value
  return {
    m: p.filter(x => (x.manage_tokens || 0) > 0).length,
    a: p.filter(x => !(x.manage_tokens || 0) && (x.advertise_only_tokens || 0) > 0).length,
    r: p.filter(x => !(x.manage_tokens || 0) && !(x.advertise_only_tokens || 0)).length,
  }
})
const subStateText = (v) => v === true ? t('launch.ppSubscribed') : v === false ? t('launch.ppNotSubscribed') : '—'
// 随机分配主页：对已选账户从各自 accPages 池随机选，全批去重（同一主页不给两个账户）；
// 池小账户先分配（贪心近似匹配，减少"大池先占小池唯一主页"的伪不足）；不足的留空并 toast 明细；
// 再点一次重摇（每次全新 used 集合 + 随机序）
const randomAssignPages = () => {
  const ids = [...selectedAccs.value]
  if (!ids.length) return ElMessage.warning(t('launch.selectAccFirst'))
  if (ids.some(id => accLoadingConfig.value.has(id)))
    return ElMessage.warning(t('launch.randPageLoading'))
  const used = new Set()
  const done = []
  const short = []
  const order = ids.map(id => ({
    id, r: Math.random(),
    n: (accPages.value[id] || []).filter(p => p.id).length,
  })).sort((a, b) => a.n - b.n || a.r - b.r)
  for (const { id } of order) {
    const pool = (accPages.value[id] || []).filter(p => p.id && !used.has(p.id))
    const pick = pool[Math.floor(Math.random() * pool.length)]
    if (!pick) {
      deployItems.value[id] = { ...(deployItems.value[id] || {}), page_id: '' }
      short.push(accLabel(id))
      continue
    }
    used.add(pick.id)
    deployItems.value[id] = { ...(deployItems.value[id] || {}), page_id: pick.id }
    done.push(id)
  }
  if (done.length) ElMessage.success(t('launch.randPageDone', { n: done.length }))
  if (short.length) ElMessage.warning(t('launch.randPageShort', { accs: short.join('、') }))
}
// 像素策略辅助：从该账户 accPixels 池随机取一个（池空返 ''）
const randomPixelFor = (id) => {
  const pool = (accPixels.value[id] || []).filter(p => p.id)
  return pool.length ? pool[Math.floor(Math.random() * pool.length)].id : ''
}
// 「随机用账户像素」：立即为全部已选账户随机填像素（之后仍可手改下拉）
const applyRandomPixels = () => {
  const ids = [...selectedAccs.value]
  if (!ids.length) return ElMessage.warning(t('launch.selectAccFirst'))
  if (ids.some(id => accLoadingConfig.value.has(id)))
    return ElMessage.warning(t('launch.randPageLoading'))
  const short = []
  for (const id of ids) {
    const pid = randomPixelFor(id)
    if (!pid) { short.push(accLabel(id)); continue }
    deployItems.value[id] = { ...(deployItems.value[id] || {}), pixel_id: pid }
  }
  if (short.length) ElMessage.warning(t('launch.psRandomShort', { accs: short.join('、') }))
  else ElMessage.success(t('launch.psRandomDone', { n: ids.length }))
}
const onPixelStrategyChange = () => {
  if (pixelStrategy.value === 'random') applyRandomPixels()
  // create 不在此建——部署确认后逐账户预创建（用户取消部署时不白建像素）
}
// 「每账户新建像素」预创建：逐账户顺序调（不并发打 FB），失败自动降级随机现有像素并 toast 说明；
// 降级也无池 → 保持空（部署走模板默认像素）。内部逐账户 catch，永不抛出
const precreatePixels = async () => {
  const created = []
  const fallback = []
  let firstErr = ''
  for (const id of [...selectedAccs.value]) {
    try {
      const r = await POST('/fb/accounts/' + id + '/create-pixel')
      deployItems.value[id] = { ...(deployItems.value[id] || {}), pixel_id: r.pixel_id }
      created.push(id)
    } catch (e) {
      const pid = randomPixelFor(id)
      if (pid) deployItems.value[id] = { ...(deployItems.value[id] || {}), pixel_id: pid }
      if (!firstErr) firstErr = e.message || ''
      fallback.push(accLabel(id))
    }
  }
  if (created.length) ElMessage.success(t('launch.psCreated', { n: created.length }))
  if (fallback.length)
    ElMessage.warning(t('launch.psCreateFallback', { accs: fallback.join('、'), err: (firstErr || '').slice(0, 120) }))
}
// 批量模式：懒加载素材库（仅图片/视频可参与批量生成系列）
const switchDeployMode = async (m) => {
  deployMode.value = m
  if (m === 'batch' && !batchAssets.value.length && !batchAssetsLoading.value) {
    batchAssetsLoading.value = true
    try { batchAssets.value = await GET('/assets') } catch (e) { showError(e, t('launch.loadAccFail')) }
    batchAssetsLoading.value = false
  }
}
const batchSelectable = computed(() => batchAssets.value.filter(a => a.type === 'image' || a.type === 'video'))
const toggleBatchAsset = (id) => {
  const s = new Set(batchAssetIds.value)
  if (s.has(id)) { s.delete(id) }
  else {
    if (s.size >= BATCH_ASSET_MAX) return ElMessage.warning(t('launch.batchMaxReached', { n: BATCH_ASSET_MAX }))
    s.add(id)
  }
  batchAssetIds.value = s
}
const batchSelectAllAssets = () => {
  batchAssetIds.value = new Set(batchSelectable.value.slice(0, BATCH_ASSET_MAX).map(a => a.id))
  if (batchSelectable.value.length > BATCH_ASSET_MAX) ElMessage.warning(t('launch.batchMaxReached', { n: BATCH_ASSET_MAX }))
}
const batchClearAssets = () => { batchAssetIds.value = new Set() }
// 批量预检：后端按第一个素材构建示例 payload（campaign 名=素材名）+ 返回 series_count
const batchPreflighting = ref(false)
const batchPreflight = async () => {
  if (!batchAssetIds.value.size) return ElMessage.warning(t('launch.batchNeedAssets'))
  const wantPlat = deployTpl.value?.platform === 'tt' ? 'tt' : 'fb'
  const accs = accounts.value.filter(a => (a.platform || 'fb') === wantPlat)
  const sel = [...selectedAccs.value]
  // 预检目标账户：优先已选且正常的 → 已选 → 未选但正常 → 第一个（payload 结构与账户无关，只影响币种/汇率展示）
  const target = accs.find(a => sel.includes(a.act_id) && a.account_status === 1)
    || accs.find(a => sel.includes(a.act_id)) || accs.find(a => a.account_status === 1) || accs[0]
  if (!target) return ElMessage.warning(t('launch.preflightNoAccount'))
  batchPreflighting.value = true
  try {
    const r = await POST('/launch-templates/' + deployTpl.value.id + '/preflight',
      { act_id: target.act_id, asset_ids: [...batchAssetIds.value], account_count: sel.length })
    preflightResult.value = r; preflightVisible.value = true
  } catch (e) { showError(e, t('launch.preflightFail')) }
  batchPreflighting.value = false
}
const startDeploy = async () => {
  if (!selectedAccs.value.size) return ElMessage.warning(t('launch.selectAccFirst'))
  // lifetime 总预算必须配排期才能部署（后端 _budget_guard_400 同口径，提前给出明确提示）
  if ((deployTpl.value?.platform || 'fb') !== 'tt'
    && deployTpl.value?.budget_type === 'lifetime'
    && !(deployTpl.value?.schedule_start && deployTpl.value?.schedule_end))
    return ElMessage.warning(t('launch.deployLifetimeNeedSchedule'))
  const isBatch = deployMode.value === 'batch'
  if (isBatch && !batchAssetIds.value.size) return ElMessage.warning(t('launch.batchNeedAssets'))
  // 批量部署直接产生花费——提交前二次确认（单模式列账户数；批量模式额外列系列总数与合计日预算；
  // 结构模板按树口径：有启用链路=立即消耗警示，全暂停=不消耗口径）
  const n = selectedAccs.value.size
  const m = isBatch ? batchAssetIds.value.size : 0
  const total = isBatch ? n * m : n
  const treeStats = deployTreeStats.value
  try {
    await ElMessageBox.confirm(
      treeStats
        ? (treeStats.chains > 0
            ? t('launch.treeConfirmMsg', { n, g: treeStats.n, m: treeStats.m, k: treeStats.chains })
            : t('launch.treeConfirmPausedMsg', { n, g: treeStats.n, m: treeStats.m }))
        : isBatch
        ? t('launch.batchConfirmMsg', { n, m, total, amt: (total * Number(deployTpl.value.budget_usd || 0)).toFixed(0) })
        : t('launch.deployConfirmMsg', { n }),
      t('launch.deployConfirmTitle'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
  } catch { return }
  deploying.value = true
  try {
    // 「每账户新建像素」：确认后才逐账户预创建（取消部署不白建）；失败自动降级随机现有并 toast
    if (pixelStrategy.value === 'create' && (deployTpl.value?.platform || 'fb') !== 'tt') {
      await precreatePixels()
    }
    const items = [...selectedAccs.value].map(id => ({ act_id: id, page_id: deployItems.value[id]?.page_id || '', pixel_id: deployItems.value[id]?.pixel_id || '' }))
    const body = { items }
    // 仅批量模式带 asset_ids——不带/空数组 = 后端单模板旧行为（完全向后兼容）
    if (isBatch) body.asset_ids = [...batchAssetIds.value]
    const r = await POST('/launch-templates/' + deployTpl.value.id + '/deploy', body)
    deployOpen.value = false
    ElMessage.success(r.tree
      ? t('launch.submittedTree', { n: r.total, g: r.tree.adsets,
          m: Math.max(1, Math.round((r.tree.ad_total || 0) / Math.max(r.total || 1, 1))) })
      : isBatch
      ? t('launch.batchSubmitted', { n: r.total, m, total: r.series_total ?? total })
      : t('launch.submitted', { n: r.total }))
    openProgress(r.job_id); await load()
  } catch (e) { showError(e, t('launch.deploySubmitFail')) }
  deploying.value = false
}
// 进度
const onProgressClose = () => { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null } }
const openProgress = async (jobId) => {
  progressOpen.value = true; activeJob.value = null
  await pollJob(jobId)
  if (pollTimer) clearTimeout(pollTimer)
  startPoll(jobId, 0)
}
// 前 12 次（30s）每 2.5s，之后每 10s；终态由 pollJob 停止
const startPoll = (jobId, n) => {
  const my = ++pollGen
  pollTimer = setTimeout(async () => {
    await pollJob(jobId)
    if (my === pollGen && pollTimer) startPoll(jobId, n + 1)
  }, n < 12 ? 2500 : 10000)
}
const pollJob = async (jobId) => {
  try {
    activeJob.value = await GET('/launch-templates/jobs/' + jobId)
    if (['completed','partial_failed','failed'].includes(activeJob.value.status)) { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null } }
  } catch {}
}
const retryItem = async (it) => {
  // partial（批量部分失败）重试确认（复审R2-P1）：批量重试=整个账户全部系列重跑，
  // 上轮已成功的系列会被重建（不走同名幂等）——必须像部署一样先确认
  if (it.error_code === 'partial') {
    try {
      await ElMessageBox.confirm(t('launch.retryPartialConfirm'), t('common.confirm'),
        { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
    } catch { return }
  }
  try { await POST(`/launch-templates/jobs/${activeJob.value.id}/retry/${it.id}`, {}); ElMessage.success(t('launch.retrySubmitted'))
    if (!pollTimer) startPoll(activeJob.value.id, 0) } catch (e) { showError(e, t('launch.retryFail')) }
}
const statusText = (s) => itemStatus(s).label
// 错误文案展示：partial（批量部分失败）汇总含「成功X/Y系列+失败明细」是决策信息——不截断、
// 允许换行；普通错误沿用截断（60/40 字，完整文案在 title 悬浮）。
// partial 必须直用 it.error（复审R2-P0）：fbErrorText 对未知 code 返回兜底翻译，
// 非空字符串会遮蔽 it.error——后端精心构造的「成功X/Y系列」汇总用户永远看不到
const itemErrText = (it, n) => {
  const txt = it.error_code === 'partial'
    ? (it.error || '')
    : (fbErrorText(it.error_code) || it.error || '')
  return it.error_code === 'partial' ? txt : txt.slice(0, n)
}
const statusColor = (s) => { const c = itemStatus(s).cls; return c === 'ok' ? 'var(--success)' : c === 'err' ? 'var(--error)' : c === 'warn' ? 'var(--ac)' : 'var(--t3)' }
const jobText = (s) => jobStatus(s).label
const fbAdsUrl = (actId, campId) => `https://www.facebook.com/adsmanager/manage/campaigns?act=${actId}&selected_campaign_ids=${campId}`
// TT 跳 TikTok Ads Manager（aadvid=广告主 ID）；plat 由调用点显式传（activeJob/depJobDetail 各自的平台，不共享状态）
const ttAdsUrl = (actId) => `https://ads.tiktok.com/am/manage/campaigns?aadvid=${actId}`
const adsUrl = (it, plat) => plat === 'tt' ? ttAdsUrl(it.act_id) : fbAdsUrl(it.act_id, it.campaign_id)
const adsLinkLabel = (plat) => plat === 'tt' ? t('launch.ttAds') : t('launch.fbAds')
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="ph-left">
        <h1 class="ph-title">{{ t('launch.title') }}</h1>
        <span class="ph-fresh">{{ t('launch.tplCount', { n: filteredList.length }) }}</span>
</div>
      <div class="ph-actions">
        <div class="seg plat-filter">
          <button :class="{on:platFilter==='all'}" @click="platFilter='all'">{{ t('common.all') }}</button>
          <button class="pf-fb" :class="{on:platFilter==='fb'}" @click="platFilter='fb'"><span class="pf-dot fb"></span>Facebook</button>
          <button class="pf-tt" :class="{on:platFilter==='tt'}" @click="platFilter='tt'"><span class="pf-dot tt"></span>TikTok</button>
</div>
        <button class="head-btn" @click="openHistory">{{ t('launch.deployHistory') }}</button>
        <el-dropdown trigger="click" @command="p => openNew(p)">
          <button class="head-btn primary">+ {{ t('launch.newTemplate') }} ▾</button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="fb">{{ t('launch.newTplFb') }}</el-dropdown-item>
              <el-dropdown-item command="tt">{{ t('launch.newTplTt') }}</el-dropdown-item>
</el-dropdown-menu>
</template>
</el-dropdown>
</div>
</header>
    <div class="d">{{ t('launch.subtitle') }}</div>

    <div class="grid" v-loading="loading">
      <div v-for="tpl in filteredList" :key="tpl.id" class="card">
        <div class="card-head">
          <span class="card-name"><span :class="['plat-chip', tpl.platform === 'tt' ? 'tt' : 'fb']">{{ tpl.platform === 'tt' ? 'TT' : 'FB' }}</span>{{ tpl.name }}</span>
          <span :class="['card-badge', _tplReady(tpl) ? 'ready' : 'pending']" :title="_tplMissing(tpl).join('、')">
            {{ _tplReady(tpl) ? '✓ ' + t('launch.ready') : t('launch.pending') }}
</span>
</div>
        <div class="card-meta">
          <span class="card-obj">{{ objLabel(tpl.objective) }}</span>
          <span>{{ tpl.budget_type === 'lifetime' ? t('launch.cardLifetime', { v: fmtUsd(tpl.lifetime_budget_usd) }) : fmtUsd(tpl.budget_usd) + '/' + t('launch.perDay') }}</span>
          <button v-if="tpl.deploy_count" class="card-dep" @click="openDeployments(tpl)" :title="t('launch.deployedListTitle', { name: tpl.name })">{{ t('launch.deployedList') }} {{ tpl.deploy_count }} ↗</button>
</div>
        <div v-if="!_tplReady(tpl)" class="card-warn">{{ t('launch.missing') }}：{{ _tplMissing(tpl).join('、') }}</div>
        <div class="card-ops">
          <button class="op primary" @click="openDeploy(tpl)">{{ t('launch.deploy') }}</button>
          <el-dropdown trigger="click" @command="cmd => onCardCmd(cmd, tpl)">
            <button class="op dots" @click.stop>⋯</button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="edit">{{ t('common.edit') }}</el-dropdown-item>
                <el-dropdown-item command="copy">{{ t('common.copy') }}</el-dropdown-item>
                <el-dropdown-item command="preflight" :disabled="preflighting">{{ t('launch.preflight') }}</el-dropdown-item>
                <el-dropdown-item command="archive" divided class="danger">{{ t('launch.archive') }}</el-dropdown-item>
</el-dropdown-menu>
</template>
</el-dropdown>
</div>
</div>
      <div v-if="!filteredList.length && !loading" class="empty">{{ list.length ? t('launch.noTemplatesForPlat') : t('launch.emptyHint') }}</div>
</div>

    <!-- 新建 FB 模板第一步：目标选择（对齐 FB Objective Picker；TT/跟帖预填不经过此弹窗） -->
    <el-dialog v-model="objPickerOpen" :title="t('launch.objpTitle')" width="620px" append-to-body :close-on-click-modal="false">
      <div class="objp">
        <div class="objp-list">
          <button v-for="o in OBJ_PICKER" :key="o.v" type="button" :class="['objp-item',{on:objPickSel===o.v}]" @click="objPickSel=o.v">
            <span class="objp-radio"></span>
            <span class="objp-name">{{ t(o.l) }}</span>
          </button>
        </div>
        <div class="objp-detail">
          <div class="objp-detail-name">{{ t(OBJECTIVES.find(o=>o.v===objPickSel)?.l || '') }}</div>
          <div class="objp-detail-desc">{{ t(OBJ_SCENES[objPickSel] || '') }}</div>
        </div>
      </div>
      <div class="objp-naming">
        <button type="button" class="objp-fold" @click="objNameShow=!objNameShow">
          <span class="t-arrow" :class="{open:objNameShow}">▶</span>{{ t('launch.objpNameOptional') }}
        </button>
        <input v-if="objNameShow" v-model="objPickName" class="inp" :placeholder="t('launch.objpNamePh')" />
      </div>
      <template #footer>
        <button class="btn" @click="objPickerOpen=false">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="!objPickSel" @click="objPickerContinue">{{ t('launch.objpContinue') }}</button>
      </template>
    </el-dialog>

    <!-- 编辑抽屉：系列/组/广告 三级 -->
    <el-drawer v-model="editOpen" :title="editing ? t('launch.editTemplate') : t('launch.newTemplate')" direction="rtl" size="680px" :destroy-on-close="true" :before-close="onEditBeforeClose">
      <div class="edit-body">
      <!-- 平台（建模板时已定，编辑器内只读展示——FB/TT 三件套链路不同，不可中途切） -->
      <div class="plat-ro-row">
        <span :class="['plat-ro', isTt ? 'tt' : 'fb']">{{ isTt ? 'TikTok' : 'Facebook' }}</span>
</div>
      <div v-if="isTt" class="tt-hint">ℹ {{ t('launch.ttSwitchNote') }}</div>
      <!-- 顶部：面包屑（系列 › 组 › 广告）+ 模板名/完备状态（FB 创建流单页三段） -->
      <div class="fb-top">
        <div class="fb-crumb">
          <span class="crumb-item">{{ t('launch.levelCampaign') }}</span>
          <span class="crumb-sep">›</span>
          <span class="crumb-item">{{ isTt ? t('launch.levelAdGroup') : t('launch.levelAdSet') }}</span>
          <span class="crumb-sep">›</span>
          <span class="crumb-item">{{ t('launch.levelAd') }}</span>
        </div>
        <span :class="['ss-status', editStatus.ready ? 'ready' : 'pending']" :title="editStatus.ready ? '' : editStatus.missing.join('、')">
          {{ editStatus.ready ? '✓ ' + t('launch.ready') : t('launch.pendingColon') + editStatus.missing.length }}
        </span>
      </div>
      <!-- 段1 广告系列（FB 创建流：目标/特殊类别/购买类型/CBO 预算/出价策略/前缀/主页） -->
      <div class="fb-sec">
        <div class="fb-sec-head" @click="toggleSec('campaign')">
          <span class="fb-sec-arrow" :class="{open:secOpen.campaign}">▶</span>
          <span class="fb-sec-title">{{ t('launch.levelCampaign') }}</span>
          <span class="fb-sec-meta">{{ form.name || t('launch.notSelected') }}</span>
</div>
        <div v-show="secOpen.campaign" class="fb-sec-body">

      <div class="form">
        <div class="row"><label>{{ t('launch.fieldTplName') }}</label><input v-model="form.name" class="inp" :placeholder="t('launch.tplNamePlaceholder')" /></div>
        <!-- objective: FB = read-only chip (click reopens the objective picker); TT = dropdown -->
        <div v-if="!isTt" class="row"><label>{{ t('launch.objective') }}</label>
          <button type="button" class="obj-chip" :title="t('launch.objpChange')" @click="objOpenFromEditor()">
            {{ objLabel(form.objective) }}<span class="obj-chip-edit">{{ t('launch.objpChange') }}</span>
          </button>
</div>
        <div v-else class="row"><label>{{ t('launch.objective') }}</label><el-select v-model="form.objective" style="width:100%" size="small"><el-option v-for="o in OBJECTIVES" :key="o.v" :value="o.v" :label="t(o.l)" /></el-select></div>
        <!-- FB：转化事件随组卡「转化位置=网站」出现（ad set 层 Conversion 面板）；TT 仍在系列段 -->
        <div class="row" v-if="isTt && convGoalsForObjective.length"><label>{{ t('launch.conversionGoal') }}</label>
          <el-select v-model="form.conversion_goal" style="width:100%" size="small" filterable clearable :placeholder="t('launch.selectConvEvent')">
            <el-option v-for="g in convGoalsForObjective" :key="g" :value="g" :label="t(CONV_GOAL_LABELS[g]||g) + ' (' + g + ')'" />
          </el-select>
</div>
        <!-- Advantage+ 系列派生态（蓝图 §4：无单一开关，由 预算/受众/版位 三项默认派生；只读展示不发字段） -->
        <div v-if="!isTt" class="advp-row">
          <span class="advp-label">{{ t('launch.advpSeries') }}</span>
          <span :class="['advp-chip', { on: cboOn }]" :title="t('launch.advpChipBudgetHint')">{{ t('launch.advpChipBudget') }}</span>
          <span :class="['advp-chip', { on: advantage_audience }]" :title="t('launch.advpChipAudienceHint')">{{ t('launch.advpChipAudience') }}</span>
          <span :class="['advp-chip', { on: placementAutoAll }]" :title="t('launch.advpChipPlacementHint')">{{ t('launch.advpChipPlacement') }}</span>
          <span class="advp-note">{{ t('launch.advpDerived') }}</span>
</div>
        <!-- Advantage+ 受众开关（模板级；原平铺组段迁入——控制上方受众 chip，不进部署 payload） -->
        <div v-if="!isTt" class="advantage-box">
          <div class="adv-row">
            <div class="adv-info">
              <span class="adv-title">{{ t('launch.advPlusAudience') }}</span>
              <span class="adv-desc">{{ t('launch.advPlusAudienceDesc') }}</span>
</div>
            <el-switch v-model="advantage_audience" active-color="#0a84ff" inactive-color="#3a3a5c" size="small" />
</div>
</div>
        <template v-if="!isTt">
        <!-- special ad categories (multi, empty = none) + buying type (read-only: auction) -->
        <div class="row"><label>{{ t('launch.specialAdCategory') }}</label>
          <el-select v-model="specialCatsSel" multiple filterable size="small" style="width:100%" :placeholder="t('launch.scat_none')">
            <el-option v-for="c in SPECIAL_CATS" :key="c.v" :value="c.v" :label="t(c.l)" />
          </el-select>
          <span class="hint">{{ t('launch.scatHint') }}</span>
</div>
        <div class="row"><label>{{ t('launch.buyType') }}</label><div class="ro-field">{{ t('launch.buyTypeAuction') }}</div></div>
        </template>
        <!-- CBO toggle: on = campaign-level budget below; off = budget lives on ad sets (section 2) -->
        <div class="row"><label>{{ t('launch.budgetMode') }}</label>
          <div class="cbo-row">
            <div class="seg cbo-seg">
              <button :class="{on:!cboOn}" @click="form.budget_mode='ABO'">{{ t('launch.abo') }}</button>
              <button :class="{on:cboOn}" @click="form.budget_mode='CBO'">{{ t('launch.cbo') }}</button>
            </div>
            <span v-if="cboOn" class="hint">{{ t('launch.cboHint') }}</span>
          </div>
</div>
        <div v-if="isTt" class="row"><label>{{ t('launch.dailyBudgetUsd') }}</label><input v-model.number="form.budget_usd" type="number" min="1" step="0.5" class="inp" /><span class="hint">{{ t('launch.budgetConvertHint') }}</span></div>
        <template v-else>
        <!-- FB CBO: campaign budget (type daily/lifetime + amount); lifetime keeps a valid daily budget for the deploy guard -->
        <template v-if="cboOn">
          <div class="row"><label>{{ t('launch.budgetType') }}</label>
            <div class="seg">
              <button :class="{on:form.budget_type!=='lifetime'}" @click="form.budget_type='daily'">{{ t('launch.btDaily') }}</button>
              <button :class="{on:form.budget_type==='lifetime'}" @click="form.budget_type='lifetime'">{{ t('launch.btLifetime') }}</button>
            </div>
</div>
          <div v-if="form.budget_type!=='lifetime'" class="row"><label>{{ t('launch.dailyBudgetUsd') }}</label><input v-model.number="form.budget_usd" type="number" min="1" step="0.5" class="inp" /><span class="hint">{{ t('launch.budgetConvertHint') }}</span></div>
          <template v-else>
          <div class="row"><label>{{ t('launch.lifetimeBudgetUsd') }}<span class="req-mark">*</span></label><input v-model.number="form.lifetime_budget_usd" type="number" min="1" step="0.5" class="inp" :placeholder="t('launch.lifetimeBudgetPh')" /><span class="hint">{{ t('launch.lifetimeScheduleHint') }}</span></div>
          <div class="row"><label>{{ t('launch.dailyBudgetUsd') }}</label><input v-model.number="form.budget_usd" type="number" min="1" max="5000" step="0.5" class="inp" :placeholder="t('launch.lifetimeDailyKeepPh')" /><span class="hint">{{ t('launch.lifetimeDailyKeepHint') }}</span></div>
          </template>
        </template>
        <!-- FB ABO structure mode: template default daily budget (nodes fall back to it) -->
        <div v-else-if="editMode==='tree'" class="row"><label>{{ t('launch.treeDefaultDailyBudget') }}</label><input v-model.number="form.budget_usd" type="number" min="1" step="0.5" class="inp" /><span class="hint">{{ t('launch.treeBudgetPh') }}</span></div>
        <!-- bid strategy (campaign-level) + bid amount / minimum ROAS (FB)：模板默认值，各广告组在组卡「出价控制」逐组覆盖（ABO/CBO 下 FB 出价额都在组级生效） -->
        <div class="row"><label>{{ t('launch.bidStrategy') }}</label><el-select v-model="form.bid_strategy" style="width:100%" size="small"><el-option v-for="b in BID_STRATEGIES" :key="b.v" :value="b.v" :label="t(b.l)" /></el-select></div>
        <div v-if="BID_NEEDS_AMOUNT.includes(form.bid_strategy)" class="row"><label>{{ t('launch.bidAmountUsd') }}</label><input v-model.number="form.bid_amount_usd" type="number" min="0" step="0.5" class="inp" :placeholder="t('launch.bidAmountPh')" /><span class="hint">{{ t('launch.budgetConvertHint') }}</span><span class="hint">{{ t('launch.bidDefaultHint') }}</span></div>
        <div v-if="BID_NEEDS_ROAS.includes(form.bid_strategy)" class="row"><label>{{ t('launch.minimumRoas') }}</label><input v-model.number="form.minimum_roas" type="number" min="0" step="0.1" class="inp" :placeholder="t('launch.minRoasPh')" /><span class="hint">{{ t('launch.bidDefaultHint') }}</span></div>
        <!-- 系列支出上限（0091）：达到即停整个系列——与预算（控制投放节奏）不同 -->
        <div class="row"><label>{{ t('launch.spendCapUsd') }}</label>
          <input v-model.number="form.spend_cap_usd" type="number" min="1" step="1" class="inp" :placeholder="t('launch.spendCapPh')" />
          <span class="hint">{{ t('launch.spendCapHint') }}</span>
</div>
        </template>
        <div class="row"><label>{{ t('launch.namePrefix') }}</label><input v-model="form.name_prefix" class="inp" /></div>
        <div v-if="!isTt" class="row"><label>{{ t('launch.pageId') }}</label>
          <el-select v-model="form.page_id" filterable clearable size="small" style="width:100%" :placeholder="t('launch.pageIdPh')" :disabled="editMode === 'flat' && form.post_source==='reuse'" :title="editMode === 'flat' && form.post_source==='reuse' ? t('launch.pageLockedByPost') : ''">
            <el-option v-for="p in tplPages" :key="p.id" :value="p.id" :label="(p.name||p.id) + ' (' + p.id + ')'" />
          </el-select>
          <span class="hint">{{ t('launch.pageIdHint') }}</span>
</div>
        <!-- Click-to-WhatsApp 显式号码（批次I）：仅互动目标部署进 promoted_object；其他目标随主页绑定号 -->
        <div v-if="!isTt && form.objective === 'OUTCOME_ENGAGEMENT'" class="row"><label>{{ t('launch.waPhoneLabel') }}</label>
          <input v-model.trim="form.whatsapp_phone_number" class="inp" :placeholder="t('launch.waPhonePh')" />
          <span class="hint">{{ t('launch.waPhoneHint') }}</span>
</div>
</div>
</div>
</div><!-- /sec1 -->

      <!-- section 2: ad sets -->
      <div class="fb-sec">
        <div class="fb-sec-head" @click="toggleSec('adset')">
          <span class="fb-sec-arrow" :class="{open:secOpen.adset}">▶</span>
          <span class="fb-sec-title">{{ isTt ? t('launch.levelAdGroup') : t('launch.levelAdSet') }}</span>
          <span v-if="editMode === 'tree'" class="fb-sec-meta">{{ t('launch.treeOverviewLine', { n: tree.adsets.length, m: treeExpandedTotal() }) }}</span>
</div>
        <div v-show="secOpen.adset" class="fb-sec-body">
          <!-- structure mode: one collapsible card per ad set -->
          <template v-if="editMode === 'tree'">
            <div v-for="(s, si) in tree.adsets" :key="s.key" class="as-card">
              <div class="as-card-head" @click="toggleTreeExpand(s.key)">
                <span class="t-arrow" :class="{ open: expandedTreeKeys.has(s.key) }">▶</span>
                <span @click.stop><el-switch v-model="s.enabled" size="small" /></span>
                <span :class="['tdot', adsetDot(s)]"></span>
                <span class="as-card-name">{{ adsetNodeLabel(s, si) }}</span>
                <span class="as-card-ops" @click.stop>
                  <button class="t-op" :title="t('launch.treeCopyNode')" @click="copyTreeAdset(si)"><el-icon><CopyDocument /></el-icon></button>
                  <button class="t-op danger" :title="t('launch.treeDelNode')" @click="removeTreeAdset(si)"><el-icon><Delete /></el-icon></button>
                </span>
              </div>
              <div v-if="expandedTreeKeys.has(s.key)" class="as-card-body form">
                <div class="row"><label>{{ t('launch.treeNodeName') }}</label><input v-model="s.name" class="inp" :placeholder="t('launch.treeNodeNamePh')" /></div>
                <!-- 转化设置（FB 广告组层）：转化位置（按目标出选项，批次I）→ 转化事件（网站位）→ 转化像素 -->
                <div class="sec-title">{{ t('launch.convSettingsTitle') }}</div>
                <div class="row"><label>{{ t('launch.convLocation') }}</label>
                  <div v-if="convLocationsForObj.length" class="convloc-opts">
                    <button type="button" :class="['convloc-opt', { on: !s.conv_location }]" @click="s.conv_location = ''">{{ t('launch.convLocAuto') }}</button>
                    <button v-for="l in convLocationsForObj" :key="l" type="button" :class="['convloc-opt', { on: s.conv_location === l }]" @click="s.conv_location = l">{{ t('launch.conv_loc_' + l) }}</button>
                  </div>
                  <div v-else class="ro-field">{{ t('launch.convLocNone') }}</div>
                  <span class="hint">{{ t('launch.convLocationHint') }}</span>
</div>
                <!-- 转化事件：转化位置=网站 且 SALES/LEADS（写系列级 conversion_goal → 部署映射 custom_event_type） -->
                <div v-if="s.conv_location === 'website' && convGoalsForObjective.length" class="row"><label>{{ t('launch.conversionGoal') }}</label>
                  <el-select v-model="form.conversion_goal" style="width:100%" size="small" filterable clearable :placeholder="t('launch.selectConvEvent')">
                    <el-option v-for="g in convGoalsForObjective" :key="g" :value="g" :label="t(CONV_GOAL_LABELS[g]||g) + ' (' + g + ')'" />
                  </el-select>
                  <span class="hint">{{ t('launch.convEventHint') }}</span>
</div>
                <!-- 像素（promoted_object，广告组层）：模板级默认值——部署链按 item.pixel_id > 模板取，绑定模板字段 -->
                <div class="row"><label>{{ t('launch.treePixelLabel') }}</label>
                  <el-input v-model="form.pixel_id" :placeholder="t('launch.pixelIdPh')" size="small" clearable />
                  <span class="hint">{{ t('launch.treePixelHint') }}</span>
</div>
                <!-- budget & schedule (ABO: per-set; CBO: budget sits on the campaign) -->
                <template v-if="!cboOn">
                <div class="row"><label>{{ t('launch.budgetType') }}</label>
                  <div class="seg">
                    <button :class="{on:s.budget_type!=='lifetime'}" @click="s.budget_type='daily'">{{ t('launch.btDaily') }}</button>
                    <button :class="{on:s.budget_type==='lifetime'}" @click="s.budget_type='lifetime'">{{ t('launch.btLifetime') }}</button>
                  </div>
</div>
                <div v-if="s.budget_type!=='lifetime'" class="row"><label>{{ t('launch.treeBudgetOverride') }}</label>
                  <input v-model.number="s.budget_usd" type="number" min="1" step="0.5" class="inp" :placeholder="t('launch.treeBudgetPh')" />
                  <span class="hint">{{ t('launch.budgetConvertHint') }}</span>
</div>
                <div v-else class="row"><label>{{ t('launch.treeLifetimeOverride') }}<span class="req-mark">*</span></label>
                  <input v-model.number="s.lifetime_budget_usd" type="number" min="1" step="0.5" class="inp" :placeholder="t('launch.treeFallbackHint')" />
                  <span class="hint">{{ t('launch.lifetimeScheduleHint') }}</span>
</div>
                </template>
                <div class="row"><label>{{ t('launch.scheduleLabel') }}<span v-if="s.budget_type==='lifetime' && !cboOn" class="req-mark">*</span></label>
                  <div class="sched-row">
                    <el-date-picker v-model="s.schedule_start" type="datetime" size="small" style="width:100%" format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DD HH:mm" :placeholder="t('launch.treeUseDefault')" />
                    <span class="sched-sep">—</span>
                    <el-date-picker v-model="s.schedule_end" type="datetime" size="small" style="width:100%" format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DD HH:mm" :placeholder="t('launch.treeUseDefault')" />
                  </div>
                  <span class="hint">{{ t('launch.treeFallbackHint') }}</span>
</div>
                <div class="row"><label>{{ t('launch.pacingMode') }}</label>
                  <div class="seg">
                    <button :class="{on:s.pacing!=='accelerated'}" @click="s.pacing=''">{{ t('launch.pacingStandard') }}</button>
                    <button :class="{on:s.pacing==='accelerated'}" @click="s.pacing='accelerated'">{{ t('launch.pacingAccelerated') }}</button>
                  </div>
</div>
                <!-- 出价控制覆盖（广告组层；ABO/CBO 下 FB 出价额都在组级生效，故两种模式都显示；默认收起） -->
                <div v-if="BID_NEEDS_AMOUNT.includes(form.bid_strategy) || BID_NEEDS_ROAS.includes(form.bid_strategy)" class="bid-ctrl">
                  <button type="button" class="bid-ctrl-head" @click="toggleBidCtrl(s.key)">
                    <span class="t-arrow" :class="{ open: bidOpenKeys.has(s.key) }">▶</span>
                    <span>{{ t('launch.bidControlTitle') }}</span>
                    <span v-if="bidCtrlSummary(s)" class="bid-ctrl-val">{{ bidCtrlSummary(s) }}</span>
                  </button>
                  <template v-if="bidOpenKeys.has(s.key)">
                  <div v-if="BID_NEEDS_AMOUNT.includes(form.bid_strategy)" class="row"><label>{{ t('launch.treeBidOverride') }}</label>
                    <input v-model.number="s.bid_amount_usd" type="number" min="0" step="0.5" class="inp" :placeholder="t('launch.treeFallbackHint')" />
                    <span class="hint">{{ t('launch.treeFallbackHint') }}</span>
</div>
                  <div v-if="BID_NEEDS_ROAS.includes(form.bid_strategy)" class="row"><label>{{ t('launch.treeRoasOverride') }}</label>
                    <input v-model.number="s.minimum_roas" type="number" min="0" step="0.1" class="inp" :placeholder="t('launch.treeFallbackHint')" />
                    <span class="hint">{{ t('launch.treeFallbackHint') }}</span>
</div>
                  </template>
</div>
                <!-- 受众区（批次I · 审计P0-1）：受众库下拉 + 内联编辑（国家/年龄/性别/兴趣）进组卡，节点级绑定 -->
                <div class="node-sec">
                  <button type="button" class="node-sec-head" @click="toggleAudSec(s.key)">
                    <span class="t-arrow" :class="{ open: !audFoldKeys.has(s.key) }">▶</span>
                    <span>{{ t('launch.audienceTargeting') }}</span>
                    <span :class="['node-sec-val', { warn: nodeAudienceEmpty(s) }]">{{ nodeAudSummary(s) || t('launch.audNotSet') }}</span>
                  </button>
                  <div v-show="!audFoldKeys.has(s.key)" class="node-sec-body">
                    <!-- 特殊广告类别已声明：受众定向被 FB 强制收窄 -->
                    <div v-if="hasSpecialCats" class="scat-warn">{{ t('launch.scatAudienceWarn') }}</div>
                    <div class="row"><label>{{ t('launch.audienceSource') }}</label>
                      <el-select v-model="s.audience_id" filterable size="small" style="width:100%">
                        <el-option :value="0" :label="t('launch.audienceCustom')" />
                        <el-option v-for="a in savedAudiences" :key="a.id" :value="a.id"
                          :label="a.name + (a.status !== 'active' ? ' · ' + t('launch.audInactive') : '')" />
                      </el-select>
                      <span class="hint">{{ t('launch.treeAudHint') }}</span>
</div>
                    <div v-if="s.audience_id && (savedAudiences.find(a => a.id === s.audience_id) || {}).status !== 'active'"
                      class="hint" style="color:var(--warning)">{{ t('launch.audInactiveWarn') }}</div>
                    <template v-if="!s.audience_id">
                    <div class="row"><label>{{ t('launch.countries') }}</label>
                      <el-select v-model="s.aud.countries" multiple filterable collapse-tags collapse-tags-tooltip
                        :placeholder="t('launch.countriesPlaceholder')" style="width:100%" size="small">
                        <el-option v-for="c in ALL_COUNTRIES" :key="c.code" :value="c.code" :label="c.label + ' (' + c.code + ')'" />
                      </el-select>
</div>
                    <div class="row"><label>{{ t('launch.age') }}</label><div class="age-row"><input v-model.number="s.aud.age_min" type="number" min="13" max="65" class="inp sm" :disabled="hasSpecialCats" :title="hasSpecialCats ? t('launch.scatFieldIgnored') : ''" /> — <input v-model.number="s.aud.age_max" type="number" min="13" max="65" class="inp sm" :disabled="hasSpecialCats" :title="hasSpecialCats ? t('launch.scatFieldIgnored') : ''" /></div></div>
                    <div class="row"><label>{{ t('launch.gender') }}</label><div class="seg"><button :class="{on:s.aud.gender===0}" :disabled="hasSpecialCats" :title="hasSpecialCats ? t('launch.scatFieldIgnored') : ''" @click="s.aud.gender=0">{{ t('launch.genderAll') }}</button><button :class="{on:s.aud.gender===1}" :disabled="hasSpecialCats" :title="hasSpecialCats ? t('launch.scatFieldIgnored') : ''" @click="s.aud.gender=1">{{ t('launch.genderMale') }}</button><button :class="{on:s.aud.gender===2}" :disabled="hasSpecialCats" :title="hasSpecialCats ? t('launch.scatFieldIgnored') : ''" @click="s.aud.gender=2">{{ t('launch.genderFemale') }}</button></div></div>
                    <div v-if="hasSpecialCats" class="hint" style="display:block;padding:0 0 4px">{{ t('launch.scatFieldIgnored') }}</div>
                    <div class="row"><label>{{ t('launch.interestLabel') }}</label>
                      <div class="interest-search">
                        <input v-model="nodeInterestQ[s.key]" class="inp" :placeholder="t('launch.interestPlaceholder')" @keyup.enter="searchInterestsForNode(s)" />
                        <button class="btn sm" :disabled="interestSearching" @click="searchInterestsForNode(s)">{{ interestSearching ? '…' : t('common.search') }}</button>
</div>
                      <div v-if="interestSearching && interestNodeKey === s.key" class="search-results"><div class="search-loading">{{ t('launch.searching') }}</div></div>
                      <div v-else-if="interestResults.length && interestNodeKey === s.key" class="search-results">
                        <div class="search-results-head"><span>{{ t('launch.searchResultsHint') }}</span><button class="clear-btn" @click="clearNodeInterestSearch(s)">{{ t('launch.clear') }} ✕</button></div>
                        <div v-for="r in interestResults" :key="r.id" :class="['search-item', { added: nodeInterestAdded(s, r.id) }]" @click="!nodeInterestAdded(s, r.id) && addNodeInterest(s, r)">
                          <span>{{ r.name }}</span>
                          <span class="sz">{{ fmtSize(r.audience_size_lower_bound || r.audience_size) }}</span>
                          <span class="add" v-if="!nodeInterestAdded(s, r.id)">+</span>
                          <span class="added-mark" v-else>✓</span>
</div>
</div>
</div>
                    <div class="row"><label>{{ t('launch.selectedInterests', { n: (s.aud.interests||[]).length }) }}</label>
                      <div class="interest-list">
                        <span v-for="(it,i) in (s.aud.interests||[])" :key="it.id" class="interest-chip">{{ it.name }} <button @click="removeNodeInterest(s, i)">✕</button></span>
                        <span v-if="!(s.aud.interests||[]).length" class="hint">{{ t('launch.addViaSearch') }}</span>
</div>
</div>
                    </template>
                    <div v-if="nodeAudienceEmpty(s)" class="aud-empty-warn">{{ t('launch.audEmptyWarn') }}</div>
                  </div>
                </div>
                <!-- 版位区（批次I）：自动版位（Advantage+）/ 手动（平台+设备）双卡；auto=省略全部版位键 -->
                <div class="node-sec">
                  <button type="button" class="node-sec-head" @click="togglePlSec(s.key)">
                    <span class="t-arrow" :class="{ open: plOpenKeys.has(s.key) }">▶</span>
                    <span>{{ t('launch.placement') }}</span>
                    <span class="node-sec-val">{{ nodePlSummary(s) }}</span>
                  </button>
                  <div v-show="plOpenKeys.has(s.key)" class="node-sec-body">
                    <div class="pl-cards">
                      <button type="button" :class="['pl-card', { on: s.placement_mode !== 'manual' }]" @click="s.placement_mode = ''">
                        <span class="pl-card-t">{{ t('launch.plModeAuto') }}</span>
                        <span class="pl-card-d">{{ t('launch.plModeAutoDesc') }}</span>
</button>
                      <button type="button" :class="['pl-card', { on: s.placement_mode === 'manual' }]" @click="s.placement_mode = 'manual'">
                        <span class="pl-card-t">{{ t('launch.plModeManual') }}</span>
                        <span class="pl-card-d">{{ t('launch.plModeManualDesc') }}</span>
</button>
</div>
                    <template v-if="s.placement_mode === 'manual'">
                      <div class="row"><label>{{ t('launch.plPlatformsLabel') }}</label>
                        <div class="platform-chips">
                          <label v-for="pv in PUB_PLATFORMS" :key="pv" class="platform-chip" :class="{on:(s.publisher_platforms||[]).includes(pv)}">
                            <input type="checkbox" :checked="(s.publisher_platforms||[]).includes(pv)" @change="toggleNodePlatform(s, pv)" /> {{ PUB_PLATFORM_LABELS[pv] }}
                          </label>
</div>
</div>
                      <div class="row"><label>{{ t('launch.device') }}</label>
                        <div class="platform-chips">
                          <label v-for="d in DEVICES" :key="d.v" class="platform-chip" :class="{on:(s.device_platforms||[]).includes(d.v)}">
                            <input type="checkbox" :checked="(s.device_platforms||[]).includes(d.v)" @change="toggleNodeDevice(s, d.v)" /> {{ t(d.l) }}
                          </label>
</div>
</div>
                      <div v-if="!(s.publisher_platforms||[]).length" class="hint" style="color:var(--warning)">{{ t('launch.plNeedPlatform') }}</div>
                    </template>
                  </div>
                </div>
                <!-- 优化目标覆盖：按 OPT_GOALS_BY_OBJECTIVE×objective 过滤（空=按转化位置矩阵自动） -->
                <div class="row"><label>{{ t('launch.treeOptOverride') }}</label>
                  <el-select v-model="s.optimization_goal" style="width:100%" size="small" filterable>
                    <el-option value="" :label="t('launch.optAutoByLoc')" />
                    <el-option v-for="g in optGoalsForObj" :key="g.v" :value="g.v" :label="t(g.l)" />
                  </el-select>
                  <span class="hint">{{ t('launch.treeFallbackHint') }}</span>
</div>
                <!-- 受益人/付款人披露（FB 广告组层 payload 字段 dsa_*；数据存模板级，所有组共用） -->
                <hr class="sep" />
                <div class="sec-title">{{ t('launch.disclosure') }}</div>
                <div class="row"><label>{{ t('launch.beneficiary') }}</label><input v-model="form.beneficiary" class="inp" :placeholder="t('launch.beneficiaryPlaceholder')" /><span class="hint">{{ t('launch.treeDisclosureHint') }}</span></div>
                <div class="row"><label>{{ t('launch.payer') }}</label><input v-model="form.payer" class="inp" /></div>
              </div>
            </div>
            <button class="t-add-adset" @click="addTreeAdset">{{ t('launch.treeAddGroup') }}</button>
          </template>
          <!-- flat mode: single card, no add/remove（FB 恒树模式——平铺卡仅 TT 可达；
               FB 组段能力（转化位置/受众/版位/预算排期/出价）已在组卡，此处只留 TT 定向/像素残壳） -->
          <div v-else class="as-card">
            <div class="as-card-body form">
        <div class="hint" style="padding:8px 10px;background:var(--bg3);border-radius:6px">{{ t('launch.ttOptimizeHint') }}</div>
        <!-- TikTok 像素（广告组层转化设置；FB 像素在组卡「转化设置」） -->
        <div class="row"><label>{{ t('launch.ttPixelId') }}</label>
          <el-input v-model="form.pixel_id" :placeholder="t('launch.ttPixelIdPh')" size="small" clearable />
          <span class="hint">{{ t('launch.ttPixelIdHint') }}</span>
</div>
        <hr class="sep" />
        <div class="sec-title">{{ t('launch.audienceTargeting') }}</div>
        <!-- 受众来源：保存的受众（SavedAudience，部署时用） / 自定义（下方手动定向）；
             FB 内联受众编辑已进组卡（受众编辑只留组卡一份），此处为 TT 定向残壳 -->
        <div class="row"><label>{{ t('launch.audienceSource') }}</label>
          <el-select v-model="form.audience_id" filterable size="small" style="width:100%" :placeholder="t('launch.audienceCustom')">
            <el-option :value="0" :label="t('launch.audienceCustom')" />
            <el-option v-for="a in savedAudiences" :key="a.id" :value="a.id"
              :label="a.name + (a.status !== 'active' ? ' · ' + t('launch.audInactive') : '')" />
</el-select>
          <span class="hint">{{ t('launch.audienceSourceHint') }}</span>
</div>
        <div v-if="selectedSavedAud" class="saved-aud-card">
          <div class="sa-head">
            <span class="sa-name">{{ selectedSavedAud.name }}</span>
            <span v-if="selectedSavedAud.status !== 'active'" class="sa-warn">{{ t('launch.audInactiveWarn') }}</span>
</div>
          <div v-if="selectedSavedAud.note" class="sa-note">{{ selectedSavedAud.note }}</div>
          <div class="sa-meta">{{ (selectedSavedAud.countries||[]).join(',') || t('launch.defaultAudience') }} · {{ selectedSavedAud.age_min }}-{{ selectedSavedAud.age_max }} · {{ t('launch.interestCount', { n: (selectedSavedAud.interests||[]).length }) }}</div>
</div>
        <div v-else class="aud-actions-row">
          <button class="btn sm ghost" :disabled="!hasManualAudience" :title="hasManualAudience ? '' : t('launch.saveAudNeedTargeting')" @click="saveAsAudience">{{ t('launch.saveAsAudience') }}</button>
</div>
        <template v-if="!form.audience_id">
        <div class="row"><label>{{ t('launch.countries') }}</label>
          <el-select v-model="form.audience_countries" multiple filterable collapse-tags collapse-tags-tooltip
            :placeholder="t('launch.countriesPlaceholder')" style="width:100%" size="small">
            <el-option v-for="c in ALL_COUNTRIES" :key="c.code" :value="c.code" :label="c.label + ' (' + c.code + ')'" />
</el-select>
</div>
        <div class="row"><label>{{ t('launch.age') }}</label><div class="age-row"><input v-model.number="form.audience_age_min" type="number" min="13" max="65" class="inp sm" :disabled="hasSpecialCats" :title="hasSpecialCats ? t('launch.scatFieldIgnored') : ''" /> — <input v-model.number="form.audience_age_max" type="number" min="13" max="65" class="inp sm" :disabled="hasSpecialCats" :title="hasSpecialCats ? t('launch.scatFieldIgnored') : ''" /></div></div>
        <div class="row"><label>{{ t('launch.gender') }}</label><div class="seg"><button :class="{on:form.audience_gender===0}" :disabled="hasSpecialCats" :title="hasSpecialCats ? t('launch.scatFieldIgnored') : ''" @click="form.audience_gender=0">{{ t('launch.genderAll') }}</button><button :class="{on:form.audience_gender===1}" :disabled="hasSpecialCats" :title="hasSpecialCats ? t('launch.scatFieldIgnored') : ''" @click="form.audience_gender=1">{{ t('launch.genderMale') }}</button><button :class="{on:form.audience_gender===2}" :disabled="hasSpecialCats" :title="hasSpecialCats ? t('launch.scatFieldIgnored') : ''" @click="form.audience_gender=2">{{ t('launch.genderFemale') }}</button></div></div>
        <div class="hint" style="padding:6px 10px;background:var(--bg3);border-radius:6px">{{ t('launch.ttAudienceHint') }}</div>
        </template>
        <hr class="sep" />
        <div class="sec-title">{{ t('launch.placement') }}</div>
        <div class="hint" style="padding:8px 10px;background:var(--bg3);border-radius:6px">{{ t('launch.ttPlacementHint') }}</div>
        <template v-if="!isTt">
        <div class="sec-title">{{ t('launch.disclosure') }}</div>
        <div class="row"><label>{{ t('launch.beneficiary') }}</label><input v-model="form.beneficiary" class="inp" :placeholder="t('launch.beneficiaryPlaceholder')" /></div>
        <div class="row"><label>{{ t('launch.payer') }}</label><input v-model="form.payer" class="inp" /></div>
        <hr class="sep" />
        <div class="sec-title">{{ t('launch.pacing') }}</div>
        <div class="row"><label>{{ t('launch.freqCapLabel') }}</label><input v-model.number="form.frequency_cap" type="number" min="0" class="inp" placeholder="0" /></div>
        <div class="row"><label>{{ t('launch.attributionWindow') }}</label>
          <el-select v-model="form.attribution_preset" style="width:100%" size="small" clearable :placeholder="t('launch.attr_default')">
            <el-option v-for="a in ATTRIBUTIONS" :key="a.v||'default'" :value="a.v" :label="t(a.l)" />
</el-select>
          <span class="hint">{{ t('launch.attributionHint') }}</span>
</div>
        <div class="row" style="flex-direction:column;align-items:stretch">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
            <label style="margin:0">{{ t('launch.daypartLabel') }}</label>
            <el-switch v-model="form.daypart_enabled" active-color="#0a84ff" inactive-color="#3a3a5c" size="small" />
</div>
          <template v-if="form.daypart_enabled">
            <div class="dpa-tools">
              <button type="button" class="op sm" @click="dpaFillAll">{{ t('launch.daypartAllDay') }}</button>
              <button type="button" class="op sm" @click="dpaFillWorkhours">{{ t('launch.daypartWorkhours') }}</button>
              <button type="button" class="op sm" @click="dpaClearAll">{{ t('launch.clear') }}</button>
              <span class="hint">{{ t('launch.daypartHint') }}</span>
</div>
            <div class="dpa-grid">
              <div class="dpa-corner"></div>
              <div class="dpa-hhdr"><span>0</span><span>6</span><span>12</span><span>18</span><span>23 {{ t('launch.hour') }}</span></div>
              <template v-for="di in 7" :key="'d'+di">
                <div class="dpa-rhdr">{{ t(DPA_DAYS[di-1]) }}</div>
                <div class="dpa-row">
                  <div v-for="h in 24" :key="di+'_'+h"
                       :class="['dpa-cell', form.daypart_cells[di-1][h-1] ? 'on' : '']"
                       :title="t(DPA_DAYS[di-1]) + ' ' + (h-1) + ':00'"
                       @click="toggleCell(di-1, h-1)"></div>
</div>
</template>
</div>
</template>
</div>
        <hr class="sep" />
        <div class="sec-title">{{ t('launch.advancedFieldsTitle') }}</div>
        <div class="row"><label>{{ t('launch.advancedSettings') }}</label><textarea v-model="form.advanced_config" class="inp ta" rows="3" :placeholder='t(&apos;launch.advancedPlaceholder&apos;)'></textarea><span class="hint">{{ t('launch.advancedHint') }}</span></div>
</template>
</div>
</div>
</div>
</div><!-- /sec2 -->

      <!-- section 3: ads -->
      <div class="fb-sec">
        <div class="fb-sec-head" @click="toggleSec('ad')">
          <span class="fb-sec-arrow" :class="{open:secOpen.ad}">▶</span>
          <span class="fb-sec-title">{{ t('launch.levelAd') }}</span>
</div>
        <div v-show="secOpen.ad" class="fb-sec-body">
        <!-- flat mode: creative source seg + follow-post card + single ad form -->
        <template v-if="editMode === 'flat'">
      <div v-if="!isTt" class="post-mode-seg">
        <button :class="['ps-btn',{on:form.post_source==='new'}]" @click="setPostSource('new')">{{ t('launch.postSourceNew') }}</button>
        <button :class="['ps-btn',{on:form.post_source==='reuse'}]" @click="setPostSource('reuse')">{{ t('launch.postSourceReuse') }}</button>
</div>
      <div v-if="!isTt && form.post_source==='reuse'" class="reuse-select-card">
        <div class="reuse-card-hint">{{ t('launch.reuseCardHint') }}</div>
        <div class="reuse-input-row">
          <input v-model="manualPostId" class="inp" :disabled="postResolving" :placeholder="t('launch.manualPostPh')" @keyup.enter="confirmManualPost" />
          <button class="btn sm primary" :disabled="postResolving || !manualPostId.trim()" @click="confirmManualPost">{{ postResolving ? t('launch.resolving') : t('launch.recognize') }}</button>
          <button class="btn sm" :disabled="!form.page_id" @click="openPostPicker">{{ t('launch.browsePosts') }}</button>
</div>
        <div v-if="reuseNeedManualPage" class="reuse-manual-page">
          <span class="hint">{{ t('launch.resolveFailManual') }}</span>
          <el-select v-model="manualPageForPost" filterable size="small" style="flex:1;min-width:160px" :placeholder="t('launch.pageIdPh')">
            <el-option v-for="p in tplPages" :key="p.id" :value="p.id" :label="(p.name||p.id) + ' (' + p.id + ')'" />
          </el-select>
          <button class="btn sm primary" :disabled="!manualPageForPost" @click="confirmManualPostWithPage">{{ t('common.confirm') }}</button>
</div>
        <div v-if="form.reuse_post_ref" class="reuse-selected-block">
          <div class="reuse-selected">
            <span class="reuse-post-id" :title="form.reuse_post_ref">{{ form.reuse_post_ref }}</span>
            <button class="btn sm ghost" @click="clearReusePost">{{ t('common.remove') }}</button>
</div>
          <div v-if="reusePreviewAvailable" class="reuse-mini-preview">
            <img v-if="reusePostPreview.picture" :src="reusePostPreview.picture" class="reuse-mini-thumb" />
            <div class="reuse-mini-text">{{ (reusePostPreview.message || '').slice(0,120) || t('launch.noPostText') }}</div>
</div>
          <div v-else-if="reusePostPreview" class="hint">{{ t('launch.postContentUnavailable') }}</div>
          <div v-else class="hint">{{ t('launch.loadingPreview') }}</div>
</div>
        <div v-else-if="!form.page_id" class="hint">{{ t('launch.reuseNoPageHint') }}</div>
</div>

      <div class="form">
        <!-- 跟帖：帖子内容只读预览（图/标题/文案/链接/CTA 全锁，来自帖子）-->
        <template v-if="form.post_source==='reuse'">
          <div class="reuse-preview-banner">{{ t('launch.reuseLockedHint') }}</div>
          <div v-if="form.reuse_post_ref && reusePreviewAvailable" class="ad-preview-card">
            <div class="ad-preview-top">
              <img v-if="reusePostPreview?.picture" :src="reusePostPreview.picture" class="ad-preview-thumb" />
              <div v-else class="ad-preview-thumb ad-preview-noimg">{{ t('launch.noImage') }}</div>
              <div class="ad-preview-topright">
                <div v-if="reusePostPreview?.headline" class="ad-preview-headline">{{ reusePostPreview.headline }}</div>
                <div v-if="linkDomain(reusePostPreview?.link)" class="ad-preview-domain" :title="reusePostPreview?.link">{{ linkDomain(reusePostPreview.link) }}</div>
</div>
</div>
            <div class="ad-preview-text">{{ (reusePostPreview?.message || '').slice(0,300) || t('launch.noPostText') }}</div>
            <div class="ad-preview-actions">
              <span v-if="reusePostPreview?.cta_type" class="ad-preview-cta">{{ ctaLabel(reusePostPreview.cta_type) }}</span>
              <a v-if="reusePostPreview?.permalink" :href="reusePostPreview.permalink" target="_blank" rel="noopener" class="ad-preview-link">{{ t('launch.viewOnFb') }} →</a>
</div>
</div>
          <div v-else-if="form.reuse_post_ref && reusePostPreview" class="post-readonly-preview">
            <div class="post-preview-text muted">{{ t('launch.postContentUnavailable') }}<br><code>{{ form.reuse_post_ref }}</code></div>
</div>
          <div v-else-if="form.reuse_post_ref" class="hint">{{ t('launch.loadingPreview') }}</div>
          <div v-else class="hint">{{ t('launch.reusePreviewEmpty') }}</div>
</template>
        <!-- 新建帖：创意字段（asset/文案/CTA/落地页/子码）-->
        <template v-else>
        <div class="row"><label>{{ t('launch.asset') }}</label>
          <div class="asset-pick">
            <div v-if="editingAsset" class="asset-chosen" @click="openPreview(editingAsset)" style="cursor:pointer">
              <img v-if="editingAsset.type==='image'" :src="editingAsset.public_url" class="asset-thumb" />
              <video v-else :src="editingAsset.public_url" class="asset-thumb" preload="metadata" />
              <span class="asset-name">{{ editingAsset.name }}（{{ t('launch.clickToPreview') }}）<template v-if="editingAsset.type==='video' && editingAsset.duration_sec"> · {{ t('launch.durationLabel') }} {{ editingAsset.duration_sec }}s</template></span>
</div>
            <button class="btn sm" :disabled="form.post_source==='reuse'" @click="openAssetPicker">{{ editingAsset ? t('launch.change') : t('launch.selectAsset') }}</button>
</div>
</div>
        <!-- Advantage+ 创意（对齐 FB Ads Manager；FB 专属） -->
        <div v-if="!isTt" class="advantage-box">
          <div class="adv-row">
            <div class="adv-info">
              <span class="adv-title">{{ t('launch.advPlusCreative') }}</span>
              <span class="adv-desc">{{ t('launch.advPlusCreativeDesc') }}</span>
</div>
            <el-switch v-model="advantage_creative" active-color="#0a84ff" inactive-color="#3a3a5c" size="small" />
</div>
</div>
        <div v-if="editingAsset && (editingAsset.ai_copy?.headlines||[]).length" class="ai-copy">
          <div class="ai-copy-t">{{ t('launch.aiCopyHint') }}</div>
          <div v-for="(h,i) in (editingAsset.ai_copy?.headlines||[])" :key="'h'+i" class="ai-pick" @click="form.headline=h"><span class="ai-tag">{{ t('launch.headlineN', { n: i+1 }) }}</span> {{ h }}</div>
          <div v-for="(b,i) in (editingAsset.ai_copy?.bodies||[])" :key="'b'+i" class="ai-pick" @click="form.body=b"><span class="ai-tag">{{ t('launch.bodyN', { n: i+1 }) }}</span> {{ b }}</div>
</div>
        <div class="row"><label>{{ t('launch.headlineLabel') }}</label><input v-model="form.headline" class="inp" :disabled="form.post_source==='reuse'" /></div>
        <div class="row"><label>{{ t('launch.bodyLabel') }}</label><textarea v-model="form.body" class="inp ta" rows="3" :disabled="form.post_source==='reuse'"></textarea></div>
        <div class="row"><label>{{ t('launch.descLabel') }}</label>
          <input v-model="form.link_description" class="inp" :disabled="form.post_source==='reuse'" :placeholder="t('launch.descPh')" />
          <span class="hint">{{ t('launch.descHint') }}</span>
</div>
        <div class="row"><label>{{ t('launch.ctaLabel') }}</label><el-select v-model="form.cta_type" style="width:100%" size="small" filterable><el-option v-for="c in CTAS" :key="c.v" :value="c.v" :label="t(c.l) + '（' + c.v + '）'" /></el-select></div>
        <div class="hint" style="padding:6px 10px;background:var(--bg3);border-radius:6px">{{ t('launch.pagePixelHint') }}</div>
        <div class="row"><label>{{ t('launch.landing') }}</label>
          <select v-model="form.landing_page_id" class="inp" @change="onLandingChange">
            <option :value="null">{{ t('launch.manualUrl') }}</option>
            <option v-for="p in landingPages" :key="p.id" :value="p.id">{{ p.title }}（{{ p.public_url || t('launch.noUrl') }}）</option>
</select>
</div>
        <div class="row"><label>{{ t('launch.landingUrl') }}</label><input v-model="form.landing_url" class="inp" placeholder="https://..." :title="t('launch.urlPhHint')" /></div>
        <div class="row"><label></label><span class="hint">{{ t('launch.urlPhHint') }}</span></div>
        <div class="row"><label>{{ t('launch.subcode') }}</label>
          <el-select v-model="form.subcode_slug" filterable clearable :placeholder="t('launch.subcodePlaceholder')" style="width:100%" size="small">
            <el-option v-for="s in subcodesForLanding" :key="s.slug" :value="s.slug" :label="s.slug + ' (' + subcodeStatus(s.status).label + ')'" />
</el-select>
          <span v-if="form.landing_page_id && !subcodesForLanding.length" class="hint">{{ t('launch.noSubcodeHint') }}</span>
</div>
        <!-- 消息类（ENGAGEMENT + 消息目标；FB Messenger 专属） -->
        <template v-if="form.objective === 'OUTCOME_ENGAGEMENT' && !isTt">
          <hr class="sep" /><div class="sec-title-row"><span class="sec-title">{{ t('launch.messageAd') }}</span>
            <router-link to="/form-templates" class="new-link">{{ t('launch.manageMsgTpl') }} →</router-link>
</div>
          <div class="row"><label>{{ t('launch.messengerWelcomeTpl') }}</label>
            <el-select v-model="form.message_template_id" style="width:100%" size="small" filterable clearable :placeholder="t('launch.selectMsgTpl')" @change="onMsgTplChange">
              <el-option v-for="m in msgTemplates" :key="m.id" :value="m.id" :label="msgTplLabel(m)" />
</el-select>
</div>
          <div v-if="selectedMsgTpl" class="tpl-preview-bar" @click="msgPreviewOpen = true">
            <span>{{ (selectedMsgTpl.welcome_text||'').slice(0,50) }}…</span>
            <span class="preview-link">{{ t('common.preview') }}</span>
</div>
</template>
        <!-- 表单类（LEADS + Instant Forms；FB/TT 双平台——下拉按模板平台过滤，payload 部署时按平台构建） -->
        <template v-if="form.objective === 'OUTCOME_LEADS' && !isTt">
          <hr class="sep" /><div class="sec-title-row"><span class="sec-title">Instant Form</span>
            <router-link to="/form-templates" class="new-link">{{ t('launch.manageFormTpl') }} →</router-link>
</div>
          <div class="row"><label>{{ t('launch.formTemplate') }}</label>
            <el-select v-model="form.lead_form_template_id" style="width:100%" size="small" filterable clearable :placeholder="t('launch.selectFormTpl')" @change="onFormTplChange">
              <el-option v-for="f in formTemplatesForPlat" :key="f.id" :value="f.id" :label="f.name + (f.fb_form_id ? ' ✓' : '')" />
</el-select>
            <span v-if="!formTemplatesForPlat.length" class="hint">{{ t('launch.noFormsForPlat', { plat: isTt ? 'TikTok' : 'Facebook' }) }}</span>
</div>
          <div v-if="selectedFormTpl" class="tpl-preview-bar" @click="formPreviewOpen = true">
            <span>{{ (selectedFormTpl.config||{}).form_title || selectedFormTpl.name }}</span>
            <span class="preview-link">{{ t('common.preview') }}</span>
</div>
</template>
</template>
        <!-- 像素已移至②广告组段「转化设置」（FB/TT 均为组层字段） -->
</div>
</template>
        <!-- structure mode: ad groups -> one collapsible mini-card per ad -->
        <template v-else>
          <template v-for="(s, si) in tree.adsets" :key="'grp'+s.key">
            <div class="ad-group-head">
              <span class="ad-group-name">{{ adsetNodeLabel(s, si) }}</span>
              <button class="op sm" @click="addTreeAd(si)">+ {{ t('launch.treeAddAd') }}</button>
            </div>
            <div v-for="(a, ai) in s.ads" :key="a.key" class="ad-card">
              <div class="ad-card-head" @click="toggleAdExpand(a.key)">
                <span class="t-arrow" :class="{ open: expandedAdKeys.has(a.key) }">▶</span>
                <span @click.stop><el-switch v-model="a.enabled" size="small" /></span>
                <span :class="['tdot', adDot(a)]"></span>
                <span class="ad-card-name">{{ adNodeLabel(a, ai) }}</span>
                <span class="as-card-ops" @click.stop>
                  <button class="t-op" :title="t('launch.treeCopyNode')" @click="copyTreeAd(si, ai)"><el-icon><CopyDocument /></el-icon></button>
                  <button class="t-op danger" :title="t('launch.treeDelNode')" @click="removeTreeAd(si, ai)"><el-icon><Delete /></el-icon></button>
                </span>
              </div>
              <div v-if="expandedAdKeys.has(a.key)" class="ad-card-body form">
                <div class="row"><label>{{ t('launch.treeNodeName') }}</label><input v-model="a.name" class="inp" :placeholder="t('launch.treeNodeNamePh')" /></div>
                <!-- 身份（FB 广告层）：主页在系列段选定；IG 为模板级全局身份（structure 无节点字段，不加节点级） -->
                <div class="sec-title">{{ t('launch.adIdentitySec') }}</div>
                <div class="row"><label>{{ t('launch.instagramActor') }}</label>
                  <input v-model.trim="form.instagram_actor_id" class="inp" :placeholder="t('launch.instagramActorPh')" />
                  <span class="hint">{{ t('launch.treeIgGlobalHint') }}</span>
</div>
                <div class="row"><label>{{ t('launch.treePostSource') }}</label>
                  <el-radio-group :model-value="a.post_source" size="small" @change="v => setNodePostSource(a, v)">
                    <el-radio-button value="new">{{ t('launch.postSourceNew') }}</el-radio-button>
                    <el-radio-button value="reuse">{{ t('launch.postSourceReuse') }}</el-radio-button>
                  </el-radio-group>
</div>
                <!-- follow-post: post ref + content preview (creative from the post) -->
                <template v-if="a.post_source === 'reuse'">
                <div class="row"><label>{{ t('launch.postSourceReuse') }}</label>
                  <div class="reuse-input-row">
                    <input v-model="nodeReuseInputs[a.key]" class="inp" :disabled="nodeResolving" :placeholder="t('launch.manualPostPh')" @keyup.enter="confirmNodePost(a)" />
                    <button class="btn sm primary" :disabled="nodeResolving || !(nodeReuseInputs[a.key]||'').trim()" @click="confirmNodePost(a)">{{ nodeResolving ? t('launch.resolving') : t('launch.recognize') }}</button>
                    <button class="btn sm" :disabled="!form.page_id" @click="openPostPickerForAd(si, ai)">{{ t('launch.browsePosts') }}</button>
                  </div>
</div>
                <div v-if="a.reuse_post_ref" class="reuse-selected-block">
                  <div class="reuse-selected">
                    <span class="reuse-post-id" :title="a.reuse_post_ref">{{ a.reuse_post_ref }}</span>
                    <button class="btn sm ghost" @click="clearNodePost(a)">{{ t('common.remove') }}</button>
</div>
                  <div v-if="nodePostPreviews[a.key]?.picture || nodePostPreviews[a.key]?.message" class="reuse-mini-preview">
                    <img v-if="nodePostPreviews[a.key].picture" :src="nodePostPreviews[a.key].picture" class="reuse-mini-thumb" />
                    <div class="reuse-mini-text">{{ (nodePostPreviews[a.key].message || '').slice(0,120) || t('launch.noPostText') }}</div>
</div>
                  <div v-else class="hint">{{ t('launch.loadingPreview') }}</div>
</div>
                <div v-else class="hint">{{ t('launch.reusePreviewEmpty') }}</div>
                </template>
                <!-- new post: assets / copy / landing / template bindings -->
                <template v-else>
                <div class="row"><label>{{ t('launch.treeMultiAsset') }}</label>
                  <div class="adv-row">
                    <div class="adv-info"><span class="hint">{{ t('launch.treeMultiAssetHint') }}</span></div>
                    <el-switch v-model="a.multi" active-color="#0a84ff" inactive-color="#3a3a5c" size="small" />
</div>
</div>
                <div v-if="a.multi" class="row">
                  <el-select v-model="a.asset_ids" multiple filterable collapse-tags collapse-tags-tooltip size="small" style="width:100%" :placeholder="t('launch.selectAsset')">
                    <el-option v-for="x in treeAssets" :key="x.id" :value="x.id" :label="x.name" />
                  </el-select>
</div>
                <div v-else class="row"><label>{{ t('launch.asset') }}</label>
                  <div class="asset-pick">
                    <div v-if="adAsset0(a)" class="asset-chosen" style="cursor:pointer" @click="openPreview(adAsset0(a))">
                      <img v-if="adAsset0(a).type==='image'" :src="adAsset0(a).public_url" class="asset-thumb" />
                      <video v-else :src="adAsset0(a).public_url" class="asset-thumb" preload="metadata" />
                      <span class="asset-name">{{ adAsset0(a).name }}</span>
</div>
                    <span v-else-if="(a.asset_ids||[]).length" class="asset-name">#{{ a.asset_ids[0] }}</span>
                    <button class="btn sm" @click="openAssetPickerForAd(si, ai)">{{ (a.asset_ids||[]).length ? t('launch.change') : t('launch.selectAsset') }}</button>
</div>
</div>
                <div v-if="(a.asset_ids||[]).length >= 2" class="hint">{{ t('launch.treeAssetGroupHint', { n: a.asset_ids.length }) }}</div>
                <div class="row"><label>{{ t('launch.headlineLabel') }}</label><input v-model="a.headline" class="inp" /></div>
                <div class="row"><label>{{ t('launch.bodyLabel') }}</label><textarea v-model="a.body" class="inp ta" rows="3"></textarea></div>
                <div class="row"><label>{{ t('launch.descLabel') }}</label>
                  <input v-model="a.link_description" class="inp" :placeholder="t('launch.descPh')" />
                  <span class="hint">{{ t('launch.descHint') }}</span>
</div>
                <div class="row"><label>{{ t('launch.ctaLabel') }}</label>
                  <el-select v-model="a.cta_type" style="width:100%" size="small" filterable clearable :placeholder="t('launch.treeUseDefault')">
                    <el-option v-for="c in CTAS" :key="c.v" :value="c.v" :label="t(c.l) + '（' + c.v + '）'" />
                  </el-select>
                  <span class="hint">{{ t('launch.treeFallbackHint') }}</span>
</div>
                <div class="row"><label>{{ t('launch.treeAdLang') }}</label>
                  <el-select v-model="a.ad_language" style="width:100%" size="small" filterable clearable :placeholder="t('launch.treeUseDefault')">
                    <el-option v-for="l in LANGS.filter(x=>x.v)" :key="l.v" :value="l.v" :label="t(l.l)" />
                  </el-select>
                  <span class="hint">{{ t('launch.treeFallbackHint') }}</span>
</div>
                <div class="row"><label>{{ t('launch.landing') }}</label>
                  <el-select :model-value="a.landing_page_id || 0" size="small" style="width:100%" @change="v => { a.landing_page_id = v || 0; onNodeLandingChange(a) }">
                    <el-option :value="0" :label="t('launch.manualUrl')" />
                    <el-option v-for="pg in landingPages" :key="pg.id" :value="pg.id" :label="pg.title + '（' + (pg.public_url || t('launch.noUrl')) + '）'" />
                  </el-select>
</div>
                <div class="row"><label>{{ t('launch.landingUrl') }}</label><input v-model="a.landing_url" class="inp" placeholder="https://..." :title="t('launch.urlPhHint')" /></div>
                <div class="row"><label>{{ t('launch.subcode') }}</label>
                  <el-select v-model="a.subcode_slug" filterable clearable size="small" style="width:100%" :placeholder="t('launch.subcodePlaceholder')">
                    <el-option v-for="sd in subcodesForNode(a)" :key="sd.slug" :value="sd.slug" :label="sd.slug + ' (' + subcodeStatus(sd.status).label + ')'" />
                  </el-select>
                  <span v-if="a.landing_page_id && !subcodesForNode(a).length" class="hint">{{ t('launch.noSubcodeHint') }}</span>
</div>
                <template v-if="form.objective === 'OUTCOME_ENGAGEMENT'">
                <hr class="sep" /><div class="sec-title">{{ t('launch.messageAd') }}</div>
                <div class="row"><label>{{ t('launch.messengerWelcomeTpl') }}</label>
                  <el-select :model-value="a.message_template_id || undefined" style="width:100%" size="small" filterable clearable :placeholder="t('launch.selectMsgTpl')" @change="v => setNodeMsgTpl(a, v)">
                    <el-option v-for="m in msgTemplates" :key="m.id" :value="m.id" :label="msgTplLabel(m)" />
                  </el-select>
</div>
                </template>
                <template v-if="form.objective === 'OUTCOME_LEADS'">
                <hr class="sep" /><div class="sec-title">Instant Form</div>
                <div class="row"><label>{{ t('launch.formTemplate') }}</label>
                  <el-select :model-value="a.lead_form_template_id || undefined" style="width:100%" size="small" filterable clearable :placeholder="t('launch.selectFormTpl')" @change="v => setNodeFormTpl(a, v)">
                    <el-option v-for="f in formTemplatesForPlat" :key="f.id" :value="f.id" :label="f.name + (f.fb_form_id ? ' ✓' : '')" />
                  </el-select>
</div>
                </template>
                </template>
              </div>
            </div>
          </template>
        </template>
        </div><!-- /sec3-body -->
      </div><!-- /sec3 -->
</div><!-- /edit-body -->

      <template #footer>
        <button class="btn" @click="onEditBeforeClose(() => { editOpen = false })">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="saving" @click="saveTpl">{{ saving ? t('launch.saving') : t('common.save') }}</button>
</template>
</el-drawer>

    <!-- 素材选择器 -->
    <el-drawer v-model="assetPickerOpen" :title="t('launch.selectAsset')" direction="rtl" size="560px" append-to-body>
      <div class="picker-grid" v-loading="pickerLoading">
        <div v-for="a in pickerAssets" :key="a.id" class="picker-card" @click="pickAsset(a)">
          <img v-if="a.type==='image'" :src="a.public_url" class="picker-thumb" />
          <video v-else :src="a.public_url" class="picker-thumb" preload="metadata" />
          <span class="picker-name">{{ a.name }}<template v-if="a.type==='video' && a.duration_sec"> · {{ a.duration_sec }}s</template></span>
</div>
</div>
</el-drawer>

    <!-- Post Picker（选已有主页帖 → 跟帖） -->
    <el-drawer v-model="postPickerOpen" :title="t('launch.postPickerTitle')" direction="rtl" size="560px" append-to-body>
      <div class="hint" style="margin-bottom:10px">{{ t('launch.postPickerHint') }}</div>
      <div class="picker-grid" v-loading="postPickerLoading">
        <div v-for="p in pickerPosts" :key="p.id" class="picker-card" @click="pickPost(p)">
          <img v-if="p.picture" :src="p.picture" class="picker-thumb" />
          <div v-else class="picker-thumb picker-no-img">{{ t('launch.noImage') }}</div>
          <span class="picker-name">{{ (p.message||'').slice(0,60) || p.id }}</span>
</div>
        <div v-if="!pickerPosts.length && !postPickerLoading" class="drawer-empty">{{ t('launch.noPosts') }}</div>
</div>
</el-drawer>

    <!-- 素材预览 -->
    <el-dialog v-model="previewOpen" :title="previewAsset?.name" width="700px" append-to-body>
      <div v-if="previewAsset" style="text-align:center">
        <img v-if="previewAsset.type==='image'" :src="previewAsset.public_url" style="max-width:100%;max-height:65vh;border-radius:8px" />
        <video v-else :src="previewAsset.public_url" controls style="max-width:100%;max-height:65vh;border-radius:8px" />
</div>
</el-dialog>

    <!-- 部署抽屉 -->
    <el-drawer v-model="deployOpen" :title="t('launch.deployTitle', { name: deployTpl?.name||'' })" direction="rtl" size="680px">
      <div class="d">{{ deployTpl?.platform === 'tt' ? t('launch.ttDeploySubtitle') : t('launch.deploySubtitle') }}</div>
      <!-- 主页权限总览（令牌×主页权限面；FB 专属，懒加载折叠面板） -->
      <div v-if="deployTpl?.platform !== 'tt'" class="pp-ov">
        <button type="button" class="pp-head" @click="togglePageOverview">
          <span>{{ t('launch.pagePermTitle') }}<template v-if="permPages.length"> · {{ t('launch.pagePermCount', { n: permPages.length }) }}</template></span>
          <span class="pp-arrow" :class="{ open: pageOverviewOpen }">▾</span>
        </button>
        <div v-if="pageOverviewOpen" class="pp-body" v-loading="permPagesLoading">
          <div class="pp-hint">{{ t('launch.pagePermHint') }}</div>
          <div v-if="permPages.length" class="pp-summary">{{ t('launch.ppSummary', { m: permPageSummary.m, a: permPageSummary.a, r: permPageSummary.r }) }}</div>
          <table v-if="permPages.length" class="pp-table">
            <thead>
              <tr>
                <th>{{ t('launch.page') }}</th>
                <th>{{ t('launch.ppColManage') }}</th>
                <th>{{ t('launch.ppColAdsOnly') }}</th>
                <th>{{ t('launch.ppColReadonly') }}</th>
                <th>{{ t('launch.ppColSubscribed') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in permPages" :key="p.page_id">
                <td>
                  <div class="pp-name">{{ p.page_name || p.page_id }}</div>
                  <div class="pp-pid">{{ p.page_id }}</div>
                </td>
                <td :class="{ ok: (p.manage_tokens || 0) > 0 }">{{ p.manage_tokens || 0 }}</td>
                <td>{{ p.advertise_only_tokens || 0 }}</td>
                <td>{{ p.read_only_tokens || 0 }}</td>
                <td :class="{ ok: p.subscribed === true, dim: p.subscribed !== true }">{{ subStateText(p.subscribed) }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="!permPagesLoading && !permPages.length" class="empty-sm">{{ t('launch.pagePermEmpty') }}</div>
        </div>
      </div>
      <!-- 结构模板：树概览（素材在树内按节点配 → 「按素材批量生成」整块隐藏，后端也 400 拦） -->
      <div v-if="deployTreeStats" class="deploy-tree-card">
        <div class="dtc-title">{{ t('launch.treeOverview') }}</div>
        <div class="dtc-line">{{ t('launch.treeOverviewLine', { n: deployTreeStats.n, m: deployTreeStats.m }) }}</div>
        <div class="dtc-line">{{ deployTreeStats.isCbo ? t(deployTreeStats.isLifetime ? 'launch.treeCboLifetimeBudget' : 'launch.treeCboBudget') : t('launch.treeAboTotal') }}：${{ deployTreeStats.perAcc }}<template v-if="!deployTreeStats.isLifetime">/{{ t('launch.perDay') }}</template></div>
        <div class="dtc-line" :class="{ warn: deployTreeStats.chains > 0 }">{{ deployTreeStats.chains > 0 ? t('launch.treeEnabledChains') + '：' + deployTreeStats.chains : t('launch.treeAllPaused') }}</div>
</div>
      <div v-if="!deployTreeStats" class="deploy-mode-row">
        <label class="dm-label">{{ t('launch.deployMode') }}</label>
        <div class="seg dm-seg">
          <button :class="{on:deployMode==='single'}" @click="deployMode='single'">{{ t('launch.modeSingle') }}</button>
          <button :class="{on:deployMode==='batch'}" @click="switchDeployMode('batch')">{{ t('launch.modeBatch') }}</button>
</div>
</div>
      <template v-if="deployMode==='batch' && !deployTreeStats">
        <div class="deploy-reuse-hint batch-hint">{{ t('launch.batchHint') }}</div>
        <div class="batch-bar">
          <span class="batch-count">{{ t('launch.batchAssetCount', { n: batchAssetIds.size }) }}</span>
          <button class="op sm" @click="batchSelectAllAssets">{{ t('launch.batchSelectAll') }}</button>
          <button class="op sm" @click="batchClearAssets">{{ t('launch.deployClear') }}</button>
          <button class="op sm" :disabled="batchPreflighting" @click="batchPreflight">{{ t('launch.preflight') }}</button>
</div>
        <div class="picker-grid batch-grid" v-loading="batchAssetsLoading">
          <div v-for="a in batchSelectable" :key="a.id" :class="['picker-card','batch-card',{on:batchAssetIds.has(a.id)}]" @click="toggleBatchAsset(a.id)">
            <img v-if="a.type==='image'" :src="a.public_url" class="picker-thumb" />
            <video v-else :src="a.public_url" class="picker-thumb" preload="metadata" />
            <span class="picker-name">{{ a.name }}<template v-if="a.type==='video' && a.duration_sec"> · {{ a.duration_sec }}s</template></span>
            <span class="batch-check">{{ batchAssetIds.has(a.id) ? '✓' : '' }}</span>
</div>
          <div v-if="!batchSelectable.length && !batchAssetsLoading" class="empty-sm">{{ t('launch.batchNoAssets') }}</div>
</div>
        <div v-if="batchPreview.n && batchPreview.m" class="batch-preview">{{ t('launch.batchPreview', { n: batchPreview.n, m: batchPreview.m, total: batchPreview.total }) }}</div>
</template>
      <div v-if="deployTpl?.post_source==='reuse'" class="deploy-reuse-hint">{{ t('launch.deployReuseHint') }}（{{ (deployTpl?.reuse_post_ref||'').split('_')[0] }}）</div>
      <div v-if="deployMode==='single' && deployAsset?.type==='video'" class="deploy-video-hint">{{ t('launch.deployVideoHint', { name: deployAsset.name || deployAsset.filename || '' }) }}<template v-if="deployAsset.duration_sec">（{{ t('launch.durationLabel') }} {{ deployAsset.duration_sec }}s）</template></div>
      <div class="deploy-search-row">
        <input v-model="deploySearch" class="inp" :placeholder="t('launch.searchAccountPlaceholder')" />
        <span class="acc-count-hint">{{ filteredDeployAccounts.length }} / {{ accounts.length }} {{ t('launch.accountsUnit') }}</span>
</div>
      <div class="acc-batch-row">
        <button class="op sm" @click="deploySelectAll">{{ t('launch.deploySelectAll') }}</button>
        <button class="op sm" @click="deploySelectActive">{{ t('launch.deploySelectActive') }}</button>
        <button class="op sm" @click="deployClearSel">{{ t('launch.deployClear') }}</button>
        <button v-if="deployTpl?.platform !== 'tt' && deployTpl?.post_source !== 'reuse'" class="op sm" :disabled="!selectedAccs.size" @click="randomAssignPages">{{ t('launch.randAssignPages') }}</button>
</div>
      <!-- 像素策略（FB 专属）：跟随模板 / 随机用账户像素 / 每账户新建像素（部署时预创建） -->
      <div v-if="deployTpl?.platform !== 'tt'" class="deploy-mode-row ps-row">
        <label class="dm-label">{{ t('launch.pixelStrategy') }}</label>
        <el-select v-model="pixelStrategy" size="small" style="width:200px" @change="onPixelStrategyChange">
          <el-option value="template" :label="t('launch.psTemplate')" />
          <el-option value="random" :label="t('launch.psRandom')" />
          <el-option value="create" :label="t('launch.psCreate')" />
        </el-select>
        <span v-if="pixelStrategy === 'create'" class="ps-hint">{{ t('launch.psCreateHint') }}</span>
      </div>
      <div v-if="deployTpl?.platform === 'tt' && !accLoading && !accounts.length" class="empty-sm">{{ t('launch.deployNoTtAccounts') }}</div>
      <div class="acc-list" v-loading="accLoading">
        <div v-for="a in filteredDeployAccounts" :key="a.act_id" :class="['acc-block', {disabled: reuseDeployPage && !accManagesReusePage(a.act_id)}]">
          <label class="acc-row" :class="{on:selectedAccs.has(a.act_id)}">
            <input type="checkbox" :checked="selectedAccs.has(a.act_id)" :disabled="reuseDeployPage && !accManagesReusePage(a.act_id)" @change="toggleAcc(a.act_id)" />
            <span class="acc-name">{{ a.name || a.act_id }}</span>
            <span class="acc-id">{{ a.act_id }} · {{ a.currency }}</span>
            <span :class="['acc-status', a.account_status === 1 ? 'ok' : 'warn']" :title="a.account_status === 1 ? t('launch.accNormal') : t('launch.accAbnormal')">{{ a.account_status === 1 ? t('launch.accNormal') : t('launch.accAbnormal') }}</span>
            <span v-if="reuseDeployPage && !accManagesReusePage(a.act_id)" class="acc-no-perm" :title="t('launch.noPagePermission')"></span>
</label>
          <div v-if="selectedAccs.has(a.act_id)" class="acc-config">
            <template v-if="accLoadingConfig.has(a.act_id)">
              <span class="config-loading">{{ t('launch.loadingPagePixel') }}</span>
</template>
            <template v-else-if="deployTpl?.platform === 'tt'">
              <label>{{ t('launch.ttPixelLabel') }}</label>
              <el-select v-model="deployItems[a.act_id].pixel_id" size="small" filterable style="width:100%">
                <el-option value="" :label="t('launch.defaultVal', { v: deployTpl?.pixel_id || t('launch.autoPick') })" />
                <el-option v-for="p in ttPixels" :key="p.id" :value="p.pixel_id" :label="(p.pixel_name || p.pixel_id) + ' (' + p.pixel_id + ')'" />
</el-select>
</template>
            <template v-else>
              <label>{{ t('launch.page') }}</label>
              <el-select v-model="deployItems[a.act_id].page_id" size="small" filterable style="width:100%">
                <el-option value="" :label="t('launch.defaultVal', { v: deployTpl?.page_id || t('launch.none') })" />
                <el-option v-for="p in (accPages[a.act_id]||[])" :key="p.id" :value="p.id" :label="p.name + ' (' + p.id + ')'" />
</el-select>
              <label>{{ t('launch.pixel') }}</label>
              <el-select v-model="deployItems[a.act_id].pixel_id" size="small" filterable style="width:100%">
                <el-option value="" :label="t('launch.defaultVal', { v: deployTpl?.pixel_id || t('launch.none') })" />
                <el-option v-for="p in (accPixels[a.act_id]||[])" :key="p.id" :value="p.id" :label="p.name + ' (' + p.id + ')'" />
</el-select>
</template>
</div>
</div>
</div>
      <template #footer>
        <span class="sel-count">{{ t('launch.selectedCount', { n: selectedAccs.size }) }}<template v-if="selectedAccs.size && deployTpl && deployMode==='single'"> · {{ singleIsLifetime ? t('launch.totalBudgetLifetimeHint', { total: (selectedAccs.size * singlePerAcc).toFixed(0), per: singlePerAcc }) : t('launch.totalBudgetHint', { total: (selectedAccs.size * singlePerAcc).toFixed(0), per: singlePerAcc }) }}</template><template v-else-if="selectedAccs.size && deployTpl && deployMode==='batch' && batchAssetIds.size"> · {{ t('launch.batchBudgetHint', { total: (selectedAccs.size * batchAssetIds.size * Number(deployTpl.budget_usd || 0)).toFixed(0), n: selectedAccs.size, m: batchAssetIds.size, per: Number(deployTpl.budget_usd || 0) }) }}</template></span>
        <button class="btn" @click="deployOpen=false">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="deploying||!selectedAccs.size||(deployMode==='batch'&&!batchAssetIds.size)" @click="startDeploy">{{ deploying ? t('launch.submitting') : t('launch.startDeploy') }}</button>
</template>
</el-drawer>

    <!-- 进度 -->
    <el-dialog v-model="progressOpen" :title="t('launch.deployProgress')" width="720px" :close-on-click-modal="false" @close="onProgressClose">
      <div v-if="activeJob" class="prog">
        <div class="prog-head">
          <span>{{ activeJob.template_name }}</span>
          <span class="prog-stat">{{ activeJob.succeeded }}✓ / {{ activeJob.failed }}✗ / {{ activeJob.total }}</span>
          <span :class="['prog-status',activeJob.status]">{{ jobText(activeJob.status) }}</span>
</div>
        <div class="prog-items">
          <div v-for="it in activeJob.items" :key="it.id" class="prog-item">
            <span class="dot" :style="{background:statusColor(it.status)}"></span>
            <span class="pi-act">{{ it.act_id }}</span>
            <span :class="['pi-status',it.status]">{{ statusText(it.status) }}</span>
            <a v-if="it.campaign_id" :href="adsUrl(it, activeJob?.platform)" target="_blank" class="pi-link">{{ adsLinkLabel(activeJob?.platform) }}→</a>
            <span v-if="it.error" :class="['pi-err',{wrap:it.error_code==='partial'}]" :title="it.error_code === 'partial' ? it.error : (fbErrorText(it.error_code) || it.error)">{{ itemErrText(it, 60) }}</span>
            <button v-if="it.status==='fail'" class="op primary sm" @click="retryItem(it)">{{ t('common.retry') }}</button>
</div>
</div>
</div>
</el-dialog>
    <!-- 预检结果（结构化展示） -->
    <el-dialog v-model="preflightVisible" :title="preflightResult?.platform === 'tt' ? t('launch.ttPreflightTitle') : t('launch.preflightTitle')" width="700px" append-to-body>
      <div v-if="preflightResult" class="preflight">
        <!-- 树模式：将消耗横幅 + 概览 + 结构树表（payload 样例沿用下方三段折叠渲染） -->
        <template v-if="preflightResult.mode === 'tree'">
          <div v-if="preflightResult.will_spend?.length" class="pf-banner warn">{{ t('launch.pfWillSpendBanner', { n: preflightResult.will_spend.length }) }}：{{ willSpendPreview }}</div>
          <div v-else class="pf-banner ok">{{ t('launch.pfAllPausedBanner') }}</div>
          <div class="pf-summary">
            <span>{{ t('launch.pfCurrency') }}：<b>{{ preflightResult.currency }}</b></span>
            <span>{{ t('launch.fxRate') }}：{{ preflightResult.fx_rate || t('launch.none') }}</span>
            <span>{{ t('launch.modeColon') }}{{ preflightResult.budget_mode }}</span>
            <span>{{ t('launch.pfAdsetCount') }}：<b>{{ preflightResult.adset_count }}</b> · {{ t('launch.pfAdTotal') }}：<b>{{ preflightResult.ad_total }}</b></span>
            <span>{{ t('launch.budgetColon') }}<b v-if="preflightResult.abo_total_usd != null">${{ preflightResult.abo_total_usd }}/{{ t('launch.perDay') }}（{{ t('launch.pfAboTotal') }}）</b><b v-else>${{ preflightResult.budget_usd }} → {{ preflightResult.camp_budget_fb }}（{{ t('launch.minorUnitHint') }}）</b></span>
</div>
          <div v-if="pfBudgetSegments(preflightResult).length" class="pf-bs-row">
            <span class="pf-bs-label">{{ t('launch.pfBudgetSchedule') }}</span>
            <span v-for="(sg, i) in pfBudgetSegments(preflightResult)" :key="i" class="pf-bs-seg">{{ sg }}</span>
          </div>
          <div class="pf-section">
            <div class="pf-title">{{ t('launch.pfTreeTitle') }}</div>
            <div class="pf-tree">
              <template v-for="(s, si) in preflightResult.tree" :key="si">
                <div class="pft-adset">
                  <span :class="['pft-state', s.enabled ? 'on' : 'off']">{{ s.enabled ? t('launch.treeStateOn') : t('launch.treeStatePaused') }}</span>
                  <span class="pft-name">{{ s.name }}</span>
                  <span class="pft-budget">${{ s.budget_usd ?? '—' }} → {{ s.budget_local_fb }}</span>
                  <span v-for="(sg, i) in pfBudgetSegments(s)" :key="'bs'+i" class="pft-meta">{{ sg }}</span>
</div>
                <div v-for="(a, ai) in s.ads" :key="ai" class="pft-ad">
                  <span :class="['pft-state', a.enabled ? 'on' : 'off']">{{ a.enabled ? t('launch.treeStateOn') : t('launch.treeStatePaused') }}</span>
                  <span class="pft-name">{{ a.name || (a.asset_count > 1 ? t('launch.treeAssetGroupN', { n: a.asset_count }) : t('launch.treeAdN', { n: ai + 1 })) }}</span>
                  <span v-if="a.asset_count" class="pft-meta">{{ t('launch.treeAssetCount', { n: a.asset_count }) }}</span>
                  <span v-if="a.post_source === 'reuse'" class="pft-meta">{{ t('launch.postSourceReuse') }}</span>
                  <span v-if="treeBindingsText(a.bindings)" class="pft-meta">{{ treeBindingsText(a.bindings) }}</span>
</div>
</template>
</div>
</div>
</template>
        <template v-else>
        <div v-if="preflightResult.subcode_warn_slug" style="color:var(--warning);padding:8px 0;font-size:13px">{{ t('launch.subcodeWarn', { slug: preflightResult.subcode_warn_slug }) }}</div>
        <div v-if="preflightResult.series_count" class="pf-series-count">{{ t('launch.batchSeriesCount', { n: preflightResult.series_count }) }}</div>
        <div v-if="preflightResult.asset?.type === 'video'" style="padding:4px 0;font-size:13px">{{ t('launch.videoAsset') }}：{{ preflightResult.asset.name || preflightResult.asset.filename }}<template v-if="preflightResult.asset.duration_sec"> · {{ t('launch.durationLabel') }} {{ preflightResult.asset.duration_sec }}s</template></div>
        <div class="pf-summary">
          <span>{{ t('launch.pfCurrency') }}：<b>{{ preflightResult.currency }}</b></span>
          <span>{{ t('launch.budgetColon') }}${{ preflightResult.budget_usd }} → <b>{{ preflightResult.daily_budget_fb }}</b>（{{ preflightResult.platform === 'tt' ? t('launch.ttUnitHint') : t('launch.minorUnitHint') }}）</span>
          <span>{{ t('launch.fxRate') }}：{{ preflightResult.fx_rate || t('launch.none') }}</span>
          <span>{{ t('launch.modeColon') }}{{ preflightResult.budget_mode }}</span>
</div>
        <div v-if="pfBudgetSegments(preflightResult).length" class="pf-bs-row">
          <span class="pf-bs-label">{{ t('launch.pfBudgetSchedule') }}</span>
          <span v-for="(sg, i) in pfBudgetSegments(preflightResult)" :key="i" class="pf-bs-seg">{{ sg }}</span>
        </div>
</template>
        <div class="pf-section">
          <div class="pf-title">{{ t('launch.pfCampaign') }}</div>
          <div class="pf-fields"><div v-for="(v,k) in preflightResult.campaign" :key="k" class="pf-field"><span class="pf-k">{{ k }}</span><span class="pf-v">{{ pfVal(k, v) }}</span></div></div>
</div>
        <div class="pf-section">
          <div class="pf-title">{{ preflightResult.platform === 'tt' ? t('launch.levelAdGroup') : t('launch.pfAdSet') }}</div>
          <div class="pf-fields"><div v-for="(v,k) in preflightResult.adset" :key="k" class="pf-field"><span class="pf-k">{{ k }}</span><span class="pf-v">{{ pfVal(k, v) }}</span></div></div>
</div>
        <div class="pf-section">
          <div class="pf-title">{{ t('launch.pfCreative') }}</div>
          <div class="pf-fields"><div v-for="(v,k) in preflightResult.creative" :key="k" class="pf-field"><span class="pf-k">{{ k }}</span><span class="pf-v">{{ pfVal(k, v) }}</span></div></div>
</div>
        <div v-if="preflightResult.notes" class="pf-notes">
          <div v-for="n in preflightResult.notes" :key="n" class="pf-note">· {{ n }}</div>
</div>
</div>
</el-dialog>

    <!-- 部署历史 -->
    <el-dialog v-model="historyOpen" :title="t('launch.deployHistory')" width="600px" append-to-body>
      <div class="history-list">
        <div v-for="j in jobs" :key="j.id" class="history-item" @click="openJob(j.id)">
          <div class="hi-main">
            <span class="hi-name">{{ j.template_name }}</span>
            <span :class="['hi-status', j.status]">{{ jobText(j.status) }}</span>
</div>
          <div class="hi-meta">{{ j.succeeded }}✓ / {{ j.failed }}✗ / {{ j.total }} · {{ fmtTime(j.created_at) }}</div>
</div>
        <div v-if="!jobs.length" class="empty-sm">{{ t('launch.noDeployRecords') }}</div>
</div>
</el-dialog>

    <!-- 模板已部署清单（卡片「已部署 N」入口；展开单次看明细+广告当前状态） -->
    <el-drawer v-model="depOpen" :title="t('launch.deployedListTitle', { name: depTpl?.name || '' })" direction="rtl" size="640px">
      <div v-loading="depLoading">
        <div v-for="j in depJobs" :key="j.id" class="dep-job">
          <div class="dep-job-head" @click="toggleDepJob(j)">
            <span class="dep-job-time">{{ fmtTime(j.created_at) }}</span>
            <span :class="['hi-status', j.status]">{{ jobText(j.status) }}</span>
            <span class="dep-job-counts">{{ j.succeeded }}✓ / {{ j.failed }}✗ / {{ j.total }}</span>
            <span class="dep-arrow" :class="{open: depJobDetail?.id === j.id}">▶</span>
</div>
          <div v-if="depJobDetail?.id === j.id" class="dep-items" v-loading="depItemsLoading">
            <div v-for="it in (depJobDetail.items||[])" :key="it.id" class="dep-item">
              <span class="dot" :style="{background:statusColor(it.status)}"></span>
              <span class="pi-act">{{ it.act_id }}</span>
              <span :class="['pi-status',it.status]">{{ statusText(it.status) }}</span>
              <span v-if="it.ad_id" class="dep-ad-id" :title="t('launch.clickCopyAdId')" @click="copyAdId(it.ad_id)">{{ it.ad_id }}</span>
              <span v-if="it.status === 'success'" class="dep-live" :style="{color: liveStatusColor(it.live_status)}" :title="t('launch.liveStatusHint')">
                {{ it.live_status ? fbAdStatus(it.live_status).label : t('launch.pendingSync') }}
</span>
              <a v-if="it.campaign_id" :href="adsUrl(it, depJobDetail?.platform)" target="_blank" class="pi-link">{{ adsLinkLabel(depJobDetail?.platform) }}→</a>
              <span v-if="it.error" :class="['pi-err',{wrap:it.error_code==='partial'}]" :title="it.error_code === 'partial' ? it.error : (fbErrorText(it.error_code) || it.error)">{{ itemErrText(it, 40) }}</span>
</div>
            <div v-if="!(depJobDetail.items||[]).length && !depItemsLoading" class="empty-sm">{{ t('launch.noJobItems') }}</div>
</div>
</div>
        <div v-if="!depJobs.length && !depLoading" class="empty-sm">{{ t('launch.noDeployRecords') }}</div>
</div>
</el-drawer>
    <!-- 表单预览 -->
    <el-dialog v-model="formPreviewOpen" :title="t('launch.formPreview')" width="400px" append-to-body>
      <div v-if="selectedFormTpl" class="phone-mockup">
        <div class="pm-screen">
          <div class="pm-header">{{ (selectedFormTpl.config||{}).form_title || selectedFormTpl.name }}</div>
          <div v-if="(selectedFormTpl.config||{}).description" class="pm-desc">{{ selectedFormTpl.config.description }}</div>
          <div v-for="(q,i) in ((selectedFormTpl.config||{}).custom_questions||[])" :key="i" class="pm-field">
            <span class="pm-label">{{ q.label }}</span>
            <div v-if="q.options&&q.options.length" class="pm-options"><span v-for="(o,oi) in q.options" :key="oi" class="pm-option">{{ o.value }}</span></div>
            <div v-else class="pm-input-mock">—</div>
</div>
</div>
</div>
</el-dialog>
    <!-- 消息预览 -->
    <el-dialog v-model="msgPreviewOpen" :title="t('launch.msgPreview')" width="380px" append-to-body>
      <div v-if="selectedMsgTpl" class="messenger-mockup">
        <div class="mm-bubble">{{ selectedMsgTpl.welcome_text }}</div>
        <div v-if="(selectedMsgTpl.ice_breakers||[]).length" class="mm-quick-replies">
          <span v-for="(ib,i) in selectedMsgTpl.ice_breakers" :key="i" class="mm-qr">{{ ib.title }}</span>
</div>
</div>
</el-dialog>
</div>
</template>

<style scoped>
.page{display:flex;flex-direction:column;gap:14px}
.bar{display:flex;justify-content:space-between;align-items:center}
.t{font-size:18px;font-weight:600;color:var(--t1)}
.d{font-size:12px;color:var(--t3);line-height:1.6}
.btn{padding:7px 14px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:6px;font-size:13px;cursor:pointer;font-family:inherit}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn.sm{padding:4px 10px;font-size:12px}
.btn.ghost{background:transparent;color:var(--t3)}
.btn:disabled{opacity:.5}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:var(--rs)   /* UI审计#8：容器圆角归一 */;padding:12px 14px;display:flex;flex-direction:column;gap:6px}
.card-head{display:flex;justify-content:space-between;align-items:baseline;gap:6px}
.card-name{font-size:14px;font-weight:600;color:var(--t1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-obj{font-size:11px;color:var(--ac);white-space:nowrap}
.card-badge{font-size:10px;padding:2px 8px;border-radius:8px;font-weight:600;white-space:nowrap;flex-shrink:0}
.card-badge.ready{color:var(--success);background:rgba(52,199,89,.13)}
.card-badge.pending{color:var(--warning);background:rgba(255,159,10,.13)}
.card-warn{font-size:11px;color:var(--warning);padding:2px 0}
.card-meta{display:flex;gap:10px;font-size:11px;color:var(--t3);flex-wrap:wrap;align-items:center}
.card-copy{font-size:11px;color:var(--t2);font-style:italic;max-height:32px;overflow:hidden}
/* 已部署清单入口（卡片 meta 行尾）+ 抽屉 */
.card-dep{background:none;border:none;color:var(--ac);font-size:11px;cursor:pointer;padding:0;font-family:inherit;margin-left:auto;white-space:nowrap}
.card-dep:hover{text-decoration:underline}
.dep-job{border:1px solid var(--bd);border-radius:8px;overflow:hidden;margin-bottom:8px}
.dep-job-head{display:flex;align-items:center;gap:10px;padding:8px 12px;cursor:pointer;background:var(--bg3)}
.dep-job-head:hover{background:var(--bg2)}
.dep-job-time{font-size:12px;color:var(--t1);font-variant-numeric:tabular-nums}
.dep-job-counts{font-size:11px;color:var(--t3);margin-left:auto}
.dep-arrow{font-size:10px   /* UI审计B：9px 中文笔画不可读 */;color:var(--t3);transition:transform .15s;display:inline-block}
.dep-arrow.open{transform:rotate(90deg)}
.dep-items{border-top:1px solid var(--bd);display:flex;flex-direction:column;gap:2px;padding:6px 0;max-height:40vh;overflow-y:auto}
.dep-item{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:4px 12px;font-size:12px}
.dep-ad-id{font-family:monospace;color:var(--ac);cursor:pointer;font-size:11px}
.dep-ad-id:hover{text-decoration:underline}
.dep-live{font-size:11px;white-space:nowrap}
/* 受众来源选择器 */
.saved-aud-card{border:1px solid var(--ac);background:rgba(10,132,255,.06);border-radius:8px;padding:8px 12px;display:flex;flex-direction:column;gap:4px}
.sa-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.sa-name{font-size:13px;font-weight:600;color:var(--ac)}
.sa-warn{font-size:11px;color:var(--warning)}
.sa-note{font-size:12px;color:var(--t2);line-height:1.5}
.sa-meta{font-size:11px;color:var(--t3)}
.aud-actions-row{display:flex;gap:6px}
.card-ops{display:flex;gap:3px;margin-top:4px}
.op{background:none;border:1px solid var(--bd);color:var(--t2);font-size:11px;cursor:pointer;padding:3px 8px;border-radius:4px}
.op.primary{color:var(--ac);border-color:var(--ac)}
.op.primary.sm{padding:2px 6px;font-size:10px}
.op.danger{color:var(--error)}
.op.dots{font-size:15px;line-height:1;padding:3px 10px}
.op:hover{background:var(--bg3)}
.empty{grid-column:1/-1;padding:40px;text-align:center;color:var(--t3);font-size:14px}

.form{display:flex;flex-direction:column;gap:12px}
.row{display:flex;flex-direction:column;gap:4px}
.row label{font-size:12px;color:var(--t3);font-weight:500}
.api-hint{font-size:10px;color:var(--t3);opacity:.6;font-family:'SF Mono',ui-monospace,monospace;font-weight:400}
.inp{padding:6px 10px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:13px;font-family:inherit}
.inp:focus{border-color:var(--ac);outline:none}
.inp.ta{resize:vertical}
.inp.sm{padding:4px 8px;font-size:12px}
.inp.multi{min-height:70px}
.hint{font-size:11px;color:var(--t3)}
/* 特殊广告类别受众警告条（组卡受众区）：FB 强制忽略年龄/性别/部分兴趣定向 */
.scat-warn{padding:7px 10px;border-radius:6px;font-size:12px;line-height:1.5;background:rgba(249,115,22,.1);color:var(--warning);border:1px solid rgba(249,115,22,.35)}
.seg{display:flex;gap:4px}
.seg button{flex:1;padding:6px;border:1px solid var(--bd);background:var(--bg3);color:var(--t3);border-radius:6px;cursor:pointer;font-size:12px;font-family:inherit}
.seg button.on{border-color:var(--ac);color:var(--ac);background:rgba(10,132,255,.1)}
.age-row{display:flex;align-items:center;gap:6px}
.age-row .inp.sm{width:80px}
.sep{border:none;border-top:1px solid var(--bd);margin:6px 0}
.sec-title{font-size:12px;color:var(--ac);font-weight:600;margin:-2px 0 2px}

.interest-search{display:flex;gap:6px}
.search-results{margin-top:4px;max-height:200px;overflow-y:auto;border:1px solid var(--bd);border-radius:6px}
.search-results-head{display:flex;justify-content:space-between;align-items:center;padding:4px 8px;font-size:10px;color:var(--t3);background:var(--bg3);border-bottom:1px solid var(--bd)}
.clear-btn{background:none;border:none;color:var(--t3);font-size:10px;cursor:pointer;padding:2px 6px}
.clear-btn:hover{color:var(--error)}
.search-item{display:flex;align-items:center;gap:6px;padding:6px 8px;font-size:12px;color:var(--t2);cursor:pointer;border-bottom:1px solid var(--bd)}
.search-item:last-child{border:none}
.search-item:hover{background:var(--bg3)}
.search-item.added{opacity:.5;cursor:default}
.search-loading{padding:12px;text-align:center;color:var(--t3);font-size:12px}
.added-mark{color:var(--success);font-weight:700}
.search-item .sz{color:var(--t3);font-size:10px;margin-left:auto}
.search-item .add{color:var(--ac);font-weight:700}
.interest-list{display:flex;gap:4px;flex-wrap:wrap}
.interest-chip{font-size:11px;padding:3px 8px;background:var(--acg);color:var(--ac);border-radius:var(--rs)   /* UI审计#8：容器圆角归一 */;display:flex;align-items:center;gap:4px}
.interest-chip button{background:none;border:none;color:var(--t3);cursor:pointer;font-size:10px;padding:0}

.asset-pick{display:flex;align-items:center;gap:10px}
.asset-chosen{display:flex;align-items:center;gap:6px;flex:1}
.asset-thumb{width:40px;height:40px;object-fit:cover;border-radius:6px}
.asset-name{font-size:12px;color:var(--t2)}
.ai-copy{background:var(--bg3);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column;gap:4px}
.ai-copy-t{font-size:11px;color:var(--t3);margin-bottom:2px}
.ai-pick{font-size:12px;color:var(--t2);cursor:pointer;padding:3px 6px;border-radius:4px;line-height:1.4}
.ai-pick:hover{background:var(--bg2);color:var(--t1)}
.ai-tag{font-size:10px   /* UI审计B：9px 中文笔画不可读 */;color:var(--ac);background:rgba(10,132,255,.15);padding:1px 4px;border-radius:3px;margin-right:4px}

.picker-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
.picker-card{background:var(--bg2);border:1px solid var(--bd);border-radius:8px;overflow:hidden;cursor:pointer;content-visibility:auto;contain-intrinsic-size:140px}
.picker-card:hover{border-color:var(--ac)}
.picker-thumb{width:100%;height:90px;object-fit:cover}
.picker-name{display:block;font-size:11px;color:var(--t2);padding:4px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.post-mode-seg{display:flex;gap:0;border-bottom:1px solid var(--bd);margin-bottom:14px}
.ps-btn{flex:none;padding:9px 18px;border:none;background:transparent;color:var(--t3);font-size:14px;cursor:pointer;font-family:inherit;border-bottom:2px solid transparent;margin-bottom:-1px;font-weight:500;transition:color .15s}
.ps-btn:hover{color:var(--t2)}
.ps-btn.on{color:var(--ac);border-bottom-color:var(--ac);font-weight:600}
/* 平台只读 chip（编辑器内；平台在建模板时定） */
.plat-ro-row{display:flex;align-items:center;margin-bottom:10px}
.plat-ro{display:inline-flex;align-items:center;gap:4px;padding:4px 14px;border-radius:8px;font-size:13px;font-weight:600;border:1px solid}
.plat-ro.fb{color:#5aa2ff;border-color:rgba(24,119,242,.35);background:rgba(24,119,242,.08)}
.plat-ro.tt{color:#ff6f8d;border-color:rgba(254,44,85,.35);background:rgba(254,44,85,.08)}
.plat-filter button{flex:none}
/* 平台筛选 chip 品牌样式：与全局平台上下文条同款（FB=品牌蓝 / TT=青粉） */
.plat-filter button{display:inline-flex;align-items:center;gap:6px}
.pf-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;background:var(--t3)}
.pf-dot.fb{background:#1877f2}
.pf-dot.tt{background:linear-gradient(135deg,#25f4ee 45%,#fe2c55 55%)}
.plat-filter .pf-fb.on{background:rgba(24,119,242,.15);border-color:rgba(24,119,242,.55);color:#5aa2ff}
.plat-filter .pf-tt.on{background:rgba(254,44,85,.12);border-color:rgba(254,44,85,.5);color:#ff6f8d}
.tt-hint{font-size:11px;color:var(--t3);padding:6px 10px;background:var(--bg3);border-radius:6px;margin-bottom:10px;line-height:1.5}
.reuse-selected{display:flex;align-items:center;gap:8px}
.reuse-selected-block{display:flex;flex-direction:column;gap:6px}
.reuse-mini-preview{display:flex;gap:8px;background:var(--bg2);border:1px solid var(--bd);border-radius:6px;padding:8px}
.reuse-mini-thumb{width:56px;height:56px;object-fit:cover;border-radius:4px;flex:none}
.reuse-mini-text{font-size:12px;color:var(--t2);line-height:1.4;white-space:pre-wrap;word-break:break-word;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.reuse-post-id{font-size:11px;color:var(--t2);font-family:monospace;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.picker-no-img{display:flex;align-items:center;justify-content:center;background:var(--bg3);color:var(--t3);font-size:11px}
.deploy-reuse-hint{padding:8px 12px;background:rgba(255,159,10,.1);border:1px solid rgba(255,159,10,.3);border-radius:6px;font-size:12px;color:var(--warning);margin:8px 0}
.deploy-video-hint{padding:8px 12px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;font-size:12px;color:var(--t2);margin:8px 0}
.reuse-select-card{background:rgba(10,132,255,.06);border:1px solid rgba(10,132,255,.2);border-radius:8px;padding:12px;margin-bottom:12px;display:flex;flex-direction:column;gap:8px}
.reuse-card-hint{font-size:12px;color:var(--t3);line-height:1.5}
.reuse-input-row{display:flex;gap:6px}
.reuse-input-row .inp{flex:1}
.reuse-manual-page{display:flex;align-items:center;gap:8px;flex-wrap:wrap;background:rgba(255,159,10,.08);border:1px solid rgba(255,159,10,.25);border-radius:6px;padding:8px}
.reuse-preview-banner{background:rgba(10,132,255,.06);border:1px solid rgba(10,132,255,.2);border-radius:8px;padding:10px 12px;font-size:12px;color:var(--ac);line-height:1.6;margin-bottom:12px}
.post-readonly-preview{display:flex;flex-direction:column;gap:8px;border:1px solid var(--bd);border-radius:8px;padding:12px;background:var(--bg2)}
.post-preview-text{font-size:13px;color:var(--t1);line-height:1.5;white-space:pre-wrap;word-break:break-word}
/* 跟帖预览：内容卡（缩略图+标题/域名 头部，文案，CTA）—— 宽敞不挤 */
.ad-preview-card{border:1px solid var(--bd);border-radius:var(--rs)   /* UI审计#8：容器圆角归一 */;background:var(--bg2);padding:14px 16px;display:flex;flex-direction:column;gap:12px}
.ad-preview-top{display:flex;gap:12px;align-items:flex-start}
.ad-preview-thumb{width:72px;height:72px;object-fit:cover;border-radius:8px;flex:none;background:var(--bg3)}
.ad-preview-noimg{display:flex;align-items:center;justify-content:center;font-size:10px;color:var(--t3)}
.ad-preview-topright{display:flex;flex-direction:column;gap:4px;min-width:0;flex:1}
.ad-preview-headline{font-size:15px;font-weight:600;color:var(--t1);line-height:1.4}
.ad-preview-domain{font-size:12px;color:var(--t3);word-break:break-all}
.ad-preview-text{font-size:13px;color:var(--t2);line-height:1.6;white-space:pre-wrap;word-break:break-word}
.ad-preview-actions{display:flex;align-items:center;gap:10px}
.ad-preview-cta{font-size:13px;font-weight:600;color:#fff;background:var(--ac);padding:8px 20px;border-radius:6px}
.ad-preview-link{font-size:12px;color:var(--ac);text-decoration:none;margin-left:auto}

.acc-list{display:flex;flex-direction:column;gap:6px;margin-top:10px}
.acc-batch-row{display:flex;gap:6px;margin-bottom:2px}
.acc-block{border:1px solid var(--bd);border-radius:8px;overflow:hidden}
.acc-row{display:flex;align-items:center;gap:8px;padding:8px 10px;cursor:pointer}
.acc-row.on{background:rgba(10,132,255,.08)}
.acc-name{font-size:13px;color:var(--t1);flex:1}
.acc-id{font-size:11px;color:var(--t3);font-family:monospace}
.acc-status{font-size:10px;padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap}
.acc-status.ok{color:var(--success);background:rgba(52,199,89,.13)}
.acc-status.warn{color:var(--warning);background:rgba(255,159,10,.13)}
.acc-block.disabled{opacity:.5}
.acc-block.disabled .acc-row{cursor:not-allowed}
.acc-no-perm{font-size:12px;cursor:help}
.acc-count-hint{font-size:11px;color:var(--t3);white-space:nowrap}
.deploy-search-row{display:flex;gap:8px;align-items:center;margin-bottom:8px }
/* 部署模式切换 + 批量生成系列（batch） */
.deploy-mode-row{display:flex;align-items:center;gap:10px;margin:10px 0 2px}
.dm-label{font-size:12px;color:var(--t3);flex:none}
.dm-seg{flex:none;width:280px}
.dm-seg button{flex:none;padding:5px 14px}
.batch-hint{margin:8px 0;background:rgba(10,132,255,.08);border-color:rgba(10,132,255,.25);color:var(--t2)}
.batch-bar{display:flex;gap:6px;align-items:center;margin:8px 0}
.batch-count{font-size:12px;color:var(--t2);margin-right:auto}
.batch-grid{max-height:300px;overflow-y:auto;padding:1px}
.batch-card{position:relative}
.batch-card.on{border-color:var(--ac);box-shadow:0 0 0 1px var(--ac) inset}
.batch-check{position:absolute;top:6px;right:6px;min-width:18px;height:18px;line-height:18px;text-align:center;border-radius:50%;background:var(--ac);color:#fff;font-size:11px}
.batch-preview{margin-top:8px;padding:8px 12px;background:rgba(10,132,255,.08);border:1px solid rgba(10,132,255,.25);border-radius:6px;font-size:12px;color:var(--t2)}
.pi-err.wrap{white-space:normal;overflow:visible;text-overflow:clip;flex-basis:100%;line-height:1.45;font-size:11px}
.pf-series-count{padding:8px 0 0;font-size:13px;color:var(--ac)}
.deploy-search-row .inp{flex:1}
.acc-config{padding:8px 10px;background:var(--bg3);display:grid;grid-template-columns:auto 1fr auto 1fr;gap:6px;align-items:center}
.acc-config label{font-size:11px;color:var(--t3)}
.sel-count{font-size:12px;color:var(--t3);margin-right:auto}
/* 主页权限总览（部署抽屉折叠面板）+ 像素策略 */
.pp-ov{border:1px solid var(--bd);border-radius:8px;margin:8px 0;overflow:hidden}
.pp-head{display:flex;width:100%;align-items:center;justify-content:space-between;background:var(--bg3);border:none;padding:8px 10px;font-size:12px;color:var(--t2);cursor:pointer}
.pp-head:hover{color:var(--t1)}
.pp-arrow{transition:transform .15s;color:var(--t3)}
.pp-arrow.open{transform:rotate(180deg)}
.pp-body{padding:8px 10px;max-height:280px;overflow-y:auto}
.pp-hint{font-size:11px;color:var(--t3);line-height:1.5;margin-bottom:6px}
.pp-summary{font-size:11px;color:var(--ac);margin-bottom:6px}
.pp-table{width:100%;border-collapse:collapse;font-size:11px}
.pp-table th{text-align:left;color:var(--t3);font-weight:500;padding:3px 6px;border-bottom:1px solid var(--bd);white-space:nowrap}
.pp-table td{padding:4px 6px;border-bottom:1px solid var(--bd);color:var(--t2);vertical-align:top}
.pp-table tr:last-child td{border-bottom:none}
.pp-name{color:var(--t1);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pp-pid{font-family:monospace;color:var(--t3);font-size:10px}
.pp-table td.ok{color:var(--success);font-weight:600}
.pp-table td.dim{color:var(--t3)}
.ps-row{gap:8px;flex-wrap:wrap}
.ps-hint{font-size:11px;color:var(--t3);line-height:1.4;min-width:0;flex:1}

.prog-head{display:flex;gap:14px;align-items:center;margin-bottom:10px;font-size:13px}
.prog-stat{color:var(--t2);font-variant-numeric:tabular-nums}
.prog-status{font-size:11px;padding:2px 8px;border-radius:var(--rs)   /* UI审计#8：容器圆角归一 */;font-weight:600}
.prog-status.completed{color:var(--success);background:rgba(52,199,89,.13)}
.prog-status.partial_failed{color:var(--warning);background:rgba(255,159,10,.13)}
.prog-status.running{color:var(--ac);background:rgba(10,132,255,.13)}
.prog-status.failed{color:var(--error);background:rgba(255,69,58,.13)}
.prog-items{display:flex;flex-direction:column;gap:2px;max-height:50vh;overflow-y:auto}
.prog-item{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:6px 8px;font-size:12px;border-bottom:1px solid var(--bd)}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.pi-act{font-family:monospace;color:var(--t2);width:130px}
.pi-status{font-size:11px;width:50px}
.pi-status.success{color:var(--success)}
.pi-status.fail{color:var(--error)}
.pi-link{color:var(--ac);text-decoration:none;font-size:11px}
.pi-err{color:var(--error);font-size:11px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* 预检结构化 */
.preflight{display:flex;flex-direction:column;gap:12px}
.pf-summary{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--t2);padding:10px;background:var(--bg3);border-radius:8px}
.pf-section{border:1px solid var(--bd);border-radius:8px;overflow:hidden}
.pf-title{font-size:12px;font-weight:600;color:var(--ac);padding:6px 10px;background:var(--bg3)}
.pf-fields{padding:4px 0}
.pf-field{display:flex;gap:8px;padding:3px 10px;font-size:11px;border-bottom:1px solid var(--bd)}
.pf-field:last-child{border:none}
.pf-k{color:var(--t3);min-width:160px;font-family:'SF Mono',ui-monospace,monospace;flex-shrink:0}
.pf-v{color:var(--t1);word-break:break-all}
.pf-notes{font-size:11px;color:var(--t3);padding:6px 0}
.pf-note{line-height:1.6}

/* 部署历史 */
.history-list{display:flex;flex-direction:column;gap:4px;max-height:50vh;overflow-y:auto}
.history-item{padding:10px;background:var(--bg3);border-radius:8px;cursor:pointer;border:1px solid transparent}
.history-item:hover{border-color:var(--ac)}
.hi-main{display:flex;justify-content:space-between;align-items:center}
.hi-name{font-size:13px;color:var(--t1);font-weight:500}
.hi-status{font-size:10px;padding:2px 6px;border-radius:8px;font-weight:600}
.hi-status.completed{color:var(--success);background:rgba(52,199,89,.13)}
.hi-status.partial_failed{color:var(--warning);background:rgba(255,159,10,.13)}
.hi-status.running{color:var(--ac);background:rgba(10,132,255,.13)}
.hi-status.failed{color:var(--error);background:rgba(255,69,58,.13)}
.hi-meta{font-size:11px;color:var(--t3);margin-top:3px}
.empty-sm{padding:30px;text-align:center;color:var(--t3);font-size:13px}

/* 部署加载 */
.config-loading{font-size:12px;color:var(--t3);padding:4px 8px}

/* 版位选择 */
.platform-chips{display:flex;gap:6px;flex-wrap:wrap}
.platform-chip{font-size:12px;padding:4px 10px;border:1px solid var(--bd);border-radius:6px;cursor:pointer;color:var(--t3);display:flex;align-items:center;gap:4px}
.platform-chip input{margin:0}
.platform-chip.on{border-color:var(--ac);color:var(--ac);background:rgba(10,132,255,.1)}

/* 兴趣区域加宽 */
.interest-search{display:flex;gap:6px;align-items:center}
.interest-search .inp{flex:1}
.interest-list{display:flex;gap:4px;flex-wrap:wrap;padding:4px 0}

/* #8 完备状态 chip（编辑器顶栏） */
.ss-status{font-size:11px;padding:2px 8px;border-radius:8px;font-weight:600;margin-left:auto}
.ss-status.ready{color:var(--success);background:rgba(52,199,89,.13)}
.ss-status.pending{color:var(--warning);background:rgba(255,159,10,.13)}

/* Advantage+ 盒子 */
.advantage-box{border:1px solid var(--ac);border-radius:var(--rs)   /* UI审计#8：容器圆角归一 */;padding:10px 14px;margin:4px 0;background:rgba(10,132,255,.05)}
.adv-row{display:flex;justify-content:space-between;align-items:center;gap:10px}
.adv-info{display:flex;flex-direction:column;gap:2px;flex:1}
.adv-title{font-size:13px;font-weight:600;color:var(--ac)}
.adv-desc{font-size:11px;color:var(--t3);line-height:1.5}

/* 版位树 */
.placement-chips{display:flex;gap:6px;flex-wrap:wrap}
/* Dayparting 时段网格 */
.dpa-tools{display:flex;align-items:center;gap:6px;margin-bottom:6px;flex-wrap:wrap}
.dpa-tools .op.sm{padding:2px 8px;font-size:11px}
.dpa-grid{display:grid;grid-template-columns:32px 1fr;grid-auto-rows:auto;gap:2px;border:1px solid var(--bd);border-radius:8px;padding:8px;background:var(--bg2);overflow-x:auto;min-width:0}
.dpa-row{grid-column:2;display:grid;grid-template-columns:repeat(24,minmax(14px,1fr));gap:2px}
.dpa-corner{grid-column:1;grid-row:1}
.dpa-hhdr{grid-column:2;grid-row:1;display:flex;justify-content:space-between;font-size:10px   /* UI审计B：9px 中文笔画不可读 */;color:var(--t3);padding:0 2px 3px}
.dpa-rhdr{grid-column:1;font-size:10px;color:var(--t3);display:flex;align-items:center;justify-content:center}
.dpa-cell{height:16px;border-radius:3px;background:var(--bg3);border:1px solid var(--bd);cursor:pointer;transition:background .1s}
.dpa-cell.on{background:var(--ac);border-color:var(--ac)}
.dpa-cell:hover{outline:1px solid var(--t3)}
.placement-chip{font-size:12px;padding:4px 10px;border:1px solid var(--bd);border-radius:6px;cursor:pointer;color:var(--t3);display:flex;align-items:center;gap:4px}
.placement-chip input{margin:0}
.placement-chip.on{border-color:var(--ac);color:var(--ac);background:rgba(10,132,255,.1)}
.placement-tree{display:flex;flex-direction:column;gap:2px;border:1px solid var(--bd);border-radius:8px;padding:4px}
.pt-node{border-radius:4px}
.pt-head{display:flex;align-items:center;gap:4px;padding:4px 6px;cursor:pointer}
.pt-head:hover{background:var(--bg3)}
.pt-arrow{font-size:10px   /* UI审计B：9px 中文笔画不可读 */;color:var(--t3);transition:transform .15s;display:inline-block;transform:rotate(0deg)}
.pt-arrow.open{transform:rotate(90deg)}
.pt-label{font-size:13px;color:var(--t2);display:flex;align-items:center;gap:4px;cursor:pointer;font-weight:500}
.pt-label input{margin:0}
.pt-label.on{color:var(--ac)}
.pt-positions{padding:4px 8px 6px 22px;display:flex;gap:4px;flex-wrap:wrap}
.pos-chip{font-size:11px;padding:2px 8px;border:1px solid var(--bd);border-radius:6px;cursor:pointer;color:var(--t3);display:flex;align-items:center;gap:3px}
.pos-chip input{margin:0;width:12px;height:12px}
.pos-chip.on{border-color:var(--ac);color:var(--ac);background:rgba(10,132,255,.08)}

/* 表单/消息模板选择 */
.new-link{font-size:11px;color:var(--ac);text-decoration:none;margin-left:auto}
.new-link:hover{text-decoration:underline}
.tpl-preview-bar{display:flex;justify-content:space-between;align-items:center;padding:6px 10px;background:var(--bg3);border-radius:6px;font-size:12px;color:var(--t2);cursor:pointer;margin-top:4px}
.tpl-preview-bar:hover{background:var(--bg2)}
.preview-link{color:var(--ac);font-size:11px}
.phone-mockup{max-width:320px;margin:0 auto;border:3px solid var(--bd);border-radius:20px;overflow:hidden;background:var(--bg2)}
.pm-screen{padding:14px;display:flex;flex-direction:column;gap:8px;max-height:55vh;overflow-y:auto}
.pm-header{font-size:15px;font-weight:700;color:var(--t1);text-align:center}
.pm-desc{font-size:11px;color:var(--t3);text-align:center}
.pm-field{display:flex;flex-direction:column;gap:2px}
.pm-label{font-size:11px;color:var(--t2)}
.pm-input-mock{background:var(--bg3);border:1px solid var(--bd);border-radius:4px;height:24px}
.pm-options{display:flex;gap:4px;flex-wrap:wrap}
.pm-option{font-size:10px;padding:2px 6px;background:var(--acg);color:var(--ac);border-radius:8px;border:1px solid var(--ac)}
.messenger-mockup{background:var(--bg3);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:8px}
.mm-bubble{background:var(--ac);color:#fff;padding:8px 12px;border-radius:12px;font-size:13px;align-self:flex-start;max-width:85%;line-height:1.5}
.mm-quick-replies{display:flex;gap:4px;flex-wrap:wrap}
.mm-qr{font-size:11px;padding:4px 10px;background:var(--bg2);border:1px solid var(--ac);color:var(--ac);border-radius:14px}

/* 1:1 三层结构模式：模式切换（树面板已并入三段手风琴） */
.tpl-mode-row{display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.tpl-mode-row label{font-size:12px;color:var(--t3);font-weight:500}
.tdot{width:8px;height:8px;border-radius:50%;flex:none}
.tdot.g{background:var(--success)}
.tdot.y{background:var(--warning)}
.tdot.c{background:var(--t3);opacity:.35}
.t-arrow{font-size:10px   /* UI审计B：9px 中文笔画不可读 */;color:var(--t3);flex:none;transition:transform .15s;display:inline-block;cursor:pointer;padding:2px}
.t-arrow.open{transform:rotate(90deg)}
.t-op{background:none;border:none;color:var(--t3);cursor:pointer;padding:2px;border-radius:4px;display:inline-flex;align-items:center}
.t-op:hover{color:var(--ac);background:var(--bg3)}
.t-op.danger:hover{color:var(--error)}
.t-add-adset{margin-top:4px;padding:6px;border:1px dashed var(--bd);background:none;color:var(--t3);border-radius:6px;font-size:12px;cursor:pointer;font-family:inherit}
.t-add-adset:hover{color:var(--ac);border-color:var(--ac)}
.bid-ctrl-head{display:flex;align-items:center;gap:6px;width:100%;background:none;border:none;color:var(--t3);font-size:12px;font-weight:600;padding:2px 0;cursor:pointer;font-family:inherit}
.bid-ctrl-head:hover{color:var(--ac)}
.bid-ctrl-val{margin-left:auto;font-weight:500;color:var(--ac)}

/* 部署抽屉：结构模板树概览卡 */
.deploy-tree-card{border:1px solid var(--ac);background:rgba(10,132,255,.06);border-radius:8px;padding:10px 12px;margin:8px 0;display:flex;flex-direction:column;gap:4px}
.dtc-title{font-size:12px;font-weight:600;color:var(--ac)}
.dtc-line{font-size:12px;color:var(--t2)}
.dtc-line.warn{color:var(--warning);font-weight:600}

/* 批次I：组卡转化位置单选组（按钮 chip，可换行） */
.convloc-opts{display:flex;flex-wrap:wrap;gap:6px}
.convloc-opt{padding:6px 12px;border:1px solid var(--bd);border-radius:6px;background:var(--bg3);color:var(--t3);font-size:12px;cursor:pointer;font-family:inherit}
.convloc-opt:hover{border-color:var(--ac);color:var(--ac)}
.convloc-opt.on{border-color:var(--ac);color:var(--ac);background:rgba(10,132,255,.1);font-weight:600}
/* 组卡折叠子区（受众/版位；受众默认展开=折叠集，版位默认收起=展开集，仿出价控制） */
.node-sec{border:1px solid var(--bd);border-radius:8px;padding:6px 10px;background:var(--bg3)}
.node-sec-head{display:flex;align-items:center;gap:6px;width:100%;background:none;border:none;color:var(--t3);font-size:12px;font-weight:600;padding:2px 0;cursor:pointer;font-family:inherit}
.node-sec-head:hover{color:var(--ac)}
.node-sec-val{margin-left:auto;font-weight:500;color:var(--ac);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:55%}
.node-sec-val.warn{color:var(--warning)}
.node-sec-body{padding:8px 0 2px;display:flex;flex-direction:column;gap:10px}
/* 版位双卡（自动=Advantage+ / 手动） */
.pl-cards{display:flex;gap:8px}
.pl-card{flex:1;text-align:left;border:1px solid var(--bd);border-radius:8px;padding:8px 10px;cursor:pointer;background:var(--bg2);display:flex;flex-direction:column;gap:2px;font-family:inherit}
.pl-card:hover{border-color:var(--ac)}
.pl-card.on{border-color:var(--ac);background:rgba(10,132,255,.08)}
.pl-card-t{font-size:12px;font-weight:600;color:var(--t1)}
.pl-card.on .pl-card-t{color:var(--ac)}
.pl-card-d{font-size:10px;color:var(--t3);line-height:1.4}
/* 受众未设置黄色警示（P0-1：空=FB 默认定向（US），不静默） */
.aud-empty-warn{padding:7px 10px;border-radius:6px;font-size:12px;line-height:1.5;background:rgba(255,159,10,.1);color:var(--warning);border:1px solid rgba(255,159,10,.3)}
/* Advantage+ 系列派生 chip 行（蓝图 §4：只读展示不发字段） */
.advp-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:8px 10px;border:1px dashed var(--bd);border-radius:8px}
.advp-label{font-size:12px;font-weight:600;color:var(--t2)}
.advp-chip{font-size:10px;padding:2px 8px;border-radius:8px;border:1px solid var(--bd);color:var(--t3);white-space:nowrap}
.advp-chip.on{color:var(--success);border-color:rgba(52,199,89,.45);background:rgba(52,199,89,.1);font-weight:600}
.advp-note{font-size:10px;color:var(--t3);margin-left:auto}
/* 预检：树模式横幅 + 结构树表 */
.pf-banner{padding:8px 12px;border-radius:6px;font-size:12px;line-height:1.6;border:1px solid}
.pf-banner.warn{color:var(--error);background:rgba(255,69,58,.08);border-color:rgba(255,69,58,.3)}
.pf-banner.ok{color:var(--success);background:rgba(52,199,89,.08);border-color:rgba(52,199,89,.3)}
.pf-tree{padding:2px 0}
.pft-adset,.pft-ad{display:flex;align-items:center;gap:8px;padding:4px 10px;font-size:12px;border-bottom:1px solid var(--bd)}
.pft-adset{color:var(--t1);font-weight:500}
.pft-ad{padding-left:26px;color:var(--t2)}
.pft-ad:last-child{border-bottom:none}
.pft-state{font-size:10px   /* UI审计B：9px 中文笔画不可读 */;padding:1px 6px;border-radius:4px;font-weight:600;flex:none}
.pft-state.on{color:var(--warning);background:rgba(255,159,10,.15)}
.pft-state.off{color:var(--t3);background:var(--bg3)}
.pft-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pft-budget{margin-left:auto;color:var(--t3);font-size:11px;white-space:nowrap;font-variant-numeric:tabular-nums;flex:none}
.pft-meta{color:var(--t3);font-size:11px;white-space:nowrap;flex:none}

/* FB 创建流：编辑器顶栏（面包屑 + 完备状态）+ 三段手风琴 */
.fb-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.fb-crumb{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--t2);font-weight:500;flex-wrap:wrap}
.crumb-sep{color:var(--t3);font-size:11px}
.fb-sec{border:1px solid var(--bd);border-radius:8px;background:var(--bg2);margin-bottom:12px;overflow:hidden}
.fb-sec-head{display:flex;align-items:center;gap:8px;padding:10px 12px;cursor:pointer;background:var(--bg3);user-select:none}
.fb-sec-head:hover{background:var(--bg2)}
.fb-sec-arrow{font-size:10px;color:var(--t3);transition:transform .15s;display:inline-block}
.fb-sec-arrow.open{transform:rotate(90deg)}
.fb-sec-title{font-size:13px;font-weight:600;color:var(--t1)}
.fb-sec-meta{font-size:11px;color:var(--t3);margin-left:auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:46%}
.fb-sec-body{padding:12px}
/* 目标只读 chip（点击重开目标弹窗）+ 只读字段 + CBO 行 + 必填标记 */
.obj-chip{display:inline-flex;align-items:center;gap:8px;padding:7px 12px;background:var(--bg3);border:1px solid var(--ac);color:var(--t1);border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;width:fit-content}
.obj-chip:hover{background:rgba(10,132,255,.08)}
.obj-chip-edit{font-size:10px;color:var(--ac);font-weight:500}
.ro-field{padding:7px 10px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;color:var(--t2);font-size:13px}
.cbo-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.cbo-seg button{flex:none;padding:5px 14px}
.req-mark{color:var(--error);font-weight:700;margin-left:2px}
/* 排期（datetime 起止） */
.sched-row{display:flex;align-items:center;gap:6px}
.sched-sep{color:var(--t3)}
/* 广告组卡 / 广告小卡（结构模式） */
.as-card{border:1px solid var(--bd);border-radius:8px;background:var(--bg2);margin-bottom:10px;overflow:hidden}
.as-card-head{display:flex;align-items:center;gap:8px;padding:8px 10px;cursor:pointer;background:var(--bg3)}
.as-card-head:hover{background:var(--bg2)}
.as-card-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:500;color:var(--t1)}
.as-card-ops{display:flex;gap:2px;flex:none}
.as-card-body{padding:12px}
.ad-group-head{display:flex;align-items:center;gap:8px;margin:2px 0 8px}
.ad-group-name{font-size:12px;font-weight:600;color:var(--t3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ad-card{border:1px solid var(--bd);border-radius:6px;background:var(--bg2);margin-bottom:8px;overflow:hidden}
.ad-card-head{display:flex;align-items:center;gap:8px;padding:6px 10px;cursor:pointer;background:var(--bg3)}
.ad-card-head:hover{background:var(--bg2)}
.ad-card-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:var(--t2)}
.ad-card-body{padding:10px}
/* 目标选择弹窗（FB Objective Picker 形态） */
.objp{display:flex;gap:14px}
.objp-list{flex:1;display:flex;flex-direction:column;gap:6px;min-width:0}
.objp-item{display:flex;align-items:center;gap:10px;padding:11px 12px;border:1px solid var(--bd);border-radius:8px;background:var(--bg2);color:var(--t2);font-size:14px;cursor:pointer;font-family:inherit;text-align:left}
.objp-item:hover{border-color:var(--ac);color:var(--t1)}
.objp-item.on{border-color:var(--ac);color:var(--ac);background:rgba(10,132,255,.08);font-weight:600}
.objp-radio{width:16px;height:16px;border-radius:50%;border:2px solid var(--bd);flex:none;box-sizing:border-box}
.objp-item.on .objp-radio{border-color:var(--ac);border-width:5px}
.objp-detail{flex:1;min-width:0;border-left:1px solid var(--bd);padding-left:14px;display:flex;flex-direction:column;gap:8px}
.objp-detail-name{font-size:15px;font-weight:600;color:var(--t1)}
.objp-detail-desc{font-size:13px;color:var(--t3);line-height:1.6}
.objp-naming{margin-top:14px;display:flex;flex-direction:column;gap:8px}
.objp-fold{display:inline-flex;align-items:center;gap:6px;background:none;border:none;color:var(--t3);font-size:12px;cursor:pointer;padding:2px 0;font-family:inherit}
.objp-fold:hover{color:var(--ac)}
/* 预检「预算与排期」行 */
.pf-bs-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--t2);padding:8px 10px;background:var(--bg3);border-radius:8px}
.pf-bs-label{font-weight:600;color:var(--ac);flex:none}
.pf-bs-seg{padding:2px 8px;background:var(--bg2);border-radius:var(--rs);white-space:nowrap}

/* #23 移动端适配（el-drawer 撑满 / el-dialog 92vw / .form .row 堆叠走 main.css 全局规则，此处只管本页结构） */
@media (max-width: 768px) {
  .grid{grid-template-columns:1fr !important}
  .picker-grid{grid-template-columns:1fr !important}
  .acc-config{grid-template-columns:1fr !important}
  /* 目标选择弹窗：左右 → 上下（列表+说明堆叠） */
  .objp{flex-direction:column}
  .objp-detail{border-left:none;padding-left:0;border-top:1px solid var(--bd);padding-top:10px}
  /* 排期起止纵向（datetime 输入已内联 width:100%；EP 面板 322px < 375px 屏宽不裁切） */
  .sched-row{flex-direction:column;align-items:stretch}
  .sched-sep{display:none}
  /* 三段手风琴段头：可点区域 ≥40px，元信息换行到第二行不与标题挤压 */
  .fb-sec-head{min-height:44px;flex-wrap:wrap}
  .fb-sec-meta{max-width:100%;flex-basis:100%}
  /* 组卡/广告卡头：点区 ≥40px；展开箭头/图标小钮放大可点 */
  .as-card-head{min-height:44px}
  .ad-card-head{min-height:40px}
  .t-arrow{padding:8px}
  .t-op{min-height:32px;min-width:32px;justify-content:center}
  /* 结构模式分组标题行：加广告按钮允许换行 */
  .ad-group-head{flex-wrap:wrap}
  /* 兴趣搜索行：输入独占一行，按钮换行（「从素材AI导入」长按钮不挤爆） */
  .interest-search{flex-wrap:wrap}
  .interest-search .inp{flex:1 1 100%}
  /* 部署模式行：label 与切换组堆叠，切换组撑满（dm-seg 定宽 280px 解除） */
  .deploy-mode-row{flex-wrap:wrap}
  .dm-seg{width:100%}
  .batch-bar,.acc-batch-row{flex-wrap:wrap}
  /* 权限总览折叠头 ≥40px 可点；表格列多，横向滚动不压扁 */
  .pp-head{min-height:40px}
  .pp-body{overflow-x:auto}
  .pp-table{min-width:460px}
  /* 已部署清单条目头 ≥40px */
  .dep-job-head{min-height:40px}
  /* 预检弹窗（92vw≈345px）：字段行 label 上置（对齐全局 .form .row 堆叠约定）；树表行换行不横向溢出 */
  .pf-field{flex-direction:column;gap:2px}
  .pf-k{min-width:0}
  .pft-adset,.pft-ad{flex-wrap:wrap}
  .pft-name{white-space:normal;word-break:break-all}
  /* 批次I 新区块：Advantage+ 派生行/版位双卡/组卡折叠子区头（可点区 ≥40px，元信息换行） */
  .advp-note{flex-basis:100%;margin-left:0}
  .pl-cards{flex-direction:column}
  .node-sec-head{min-height:40px;flex-wrap:wrap}
  .node-sec-val{max-width:100%;flex-basis:100%;text-align:left}
}
</style>
