<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { showError } from '../composables/useError'
import { jobStatus, itemStatus, fbAdStatus } from '../composables/useStatus'
import { fbErrorText } from '../composables/useFbError'
import { fmtUsd } from '../composables/useFormat'
import { COUNTRIES as ALL_COUNTRIES } from '../composables/useCountries'

const { t } = useI18n()
const route = useRoute()

const list = ref([])
const loading = ref(false)
const editOpen = ref(false)
const editing = ref(null)
const form = ref({})
const saving = ref(false)
const editLevel = ref('campaign')  // 3 Tab: campaign / adset / ad
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
// 兴趣搜索
const interestQ = ref('')
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
// 落地页
const landingPages = ref([])
// 进度
const progressOpen = ref(false)
const activeJob = ref(null)
let pollTimer = null
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
const OPT_GOALS = [
  {v:'LINK_CLICKS',l:'launch.opt_link_clicks'},{v:'LANDING_PAGE_VIEWS',l:'launch.opt_landing_page_views'},{v:'REACH',l:'launch.opt_reach'},
  {v:'IMPRESSIONS',l:'launch.opt_impressions'},{v:'OFFSITE_CONVERSIONS',l:'launch.opt_offsite_conversions'},{v:'LEAD_GENERATION',l:'launch.opt_lead_generation'},
  {v:'PAGE_LIKES',l:'launch.opt_page_likes'},{v:'POST_ENGAGEMENT',l:'launch.opt_post_engagement'},{v:'CONVERSATIONS',l:'launch.opt_conversations'},
  {v:'THRUPLAY',l:'launch.opt_thruplay'},{v:'APP_INSTALLS',l:'launch.opt_app_installs'},{v:'VALUE',l:'launch.opt_value'},
]
const BILLING_EVENTS = [
  {v:'IMPRESSIONS',l:'launch.bill_impressions'},{v:'LINK_CLICKS',l:'launch.bill_link_clicks'},{v:'APP_INSTALLS',l:'launch.bill_app_installs'},
  {v:'PAGE_LIKES',l:'launch.bill_page_likes'},{v:'POST_ENGAGEMENT',l:'launch.bill_post_engagement'},{v:'THRUPLAY',l:'launch.bill_thruplay'},
]
const DEST_TYPES = [
  {v:'WEBSITE',l:'launch.dest_website'},{v:'ON_AD',l:'launch.dest_on_ad'},{v:'ON_PAGE',l:'launch.dest_on_page'},{v:'MESSENGER',l:'launch.dest_messenger'},
  {v:'APP',l:'launch.dest_app'},{v:'WHATSAPP',l:'launch.dest_whatsapp'},{v:'INSTAGRAM_DIRECT',l:'launch.dest_instagram_direct'},
]
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
  if (!form.value.conversion_goal || form.value.conversion_goal === oldD?.conv)
    form.value.conversion_goal = d.conv
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
// 展开的平台
const expandedPlatforms = ref(new Set(['facebook']))
const togglePlatformExpand = (v) => {
  const s = new Set(expandedPlatforms.value)
  s.has(v) ? s.delete(v) : s.add(v)
  expandedPlatforms.value = s
}
// 平台选中（全选/取消整平台）
const isPlatformOn = (pv) => (form.value.placement_platforms||[]).includes(pv)
const togglePlatformSel = (pv) => {
  const arr = form.value.placement_platforms || []
  const i = arr.indexOf(pv)
  if (i >= 0) {
    arr.splice(i, 1)
    // 移除该平台的所有 positions
    const key = pv + '_positions'
    form.value[key] = []
  } else {
    arr.push(pv)
    expandedPlatforms.value.add(pv); expandedPlatforms.value = new Set(expandedPlatforms.value)
  }
  form.value.placement_platforms = [...arr]
}
// 版位选中
const posKey = (pv) => pv + '_positions'
const isPosOn = (pv, posv) => {
  const arr = form.value[posKey(pv)] || []
  return arr.includes(posv)
}
const togglePos = (pv, posv) => {
  const key = posKey(pv)
  const arr = form.value[key] || []
  const i = arr.indexOf(posv)
  if (i >= 0) arr.splice(i, 1); else arr.push(posv)
  form.value[key] = [...arr]
}
// 设备
const toggleDevice = (dv) => {
  const arr = form.value.placement_devices || []
  const i = arr.indexOf(dv)
  if (i >= 0) arr.splice(i, 1); else arr.push(dv)
  form.value.placement_devices = [...arr]
}
const BID_STRATEGIES = [
  { v: 'LOWEST_COST_WITHOUT_CAP', l: 'launch.bid_lowest_without_cap' },
  { v: 'LOWEST_COST_WITH_BID_CAP', l: 'launch.bid_lowest_with_cap' },
  { v: 'COST_CAP', l: 'launch.bid_cost_cap' },
]
const CTAS = [
  { v: 'SHOP_NOW', l: 'launch.cta_shop_now' },{ v: 'SIGN_UP', l: 'launch.cta_sign_up' },{ v: 'SUBSCRIBE', l: 'launch.cta_subscribe' },
  { v: 'LEARN_MORE', l: 'launch.cta_learn_more' },{ v: 'DOWNLOAD', l: 'launch.cta_download' },{ v: 'CONTACT_US', l: 'launch.cta_contact_us' },
  { v: 'GET_QUOTE', l: 'launch.cta_get_quote' },{ v: 'BOOK_NOW', l: 'launch.cta_book_now' },{ v: 'ORDER_NOW', l: 'launch.cta_order_now' },
  { v: 'CALL_NOW', l: 'launch.cta_call_now' },{ v: 'MESSAGE_PAGE', l: 'launch.cta_message_page' },{ v: 'WATCH_MORE', l: 'launch.cta_watch_more' },
  { v: 'ADD_TO_CART', l: 'launch.cta_add_to_cart' },{ v: 'BUY_TICKETS', l: 'launch.cta_buy_tickets' },
]
const LANGS = [
  { v: '', l: 'launch.lang_any' },{ v: '24', l: 'launch.lang_en_us' },{ v: '6', l: 'launch.lang_en_gb' },{ v: '37', l: 'launch.lang_en_all' },
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
    form.value.post_source = 'reuse'
    form.value.reuse_post_ref = String(rp)
    form.value.page_id = String(rp).split('_')[0]  // {page}_{post} → page
    fetchReusePreview(String(rp))  // 拉帖子内容预览
    editLevel.value = 'ad'  // 直达广告 Tab 显示跟帖锁卡
    snapshotForm()  // 重新快照（含预填值，避免一开就标 dirty）
    ElMessage.info(t('launch.reusePrefilled'))
  }
})
const loadTplPages = async () => { try { const r = await GET('/fb/assets'); tplPages.value = r.pages || [] } catch {} }
onUnmounted(() => { if (pollTimer) clearTimeout(pollTimer) })

// #2 dirty-check：编辑抽屉关闭前确认
let _formSnapshot = ''
const snapshotForm = () => { _formSnapshot = JSON.stringify(form.value) }
const isDirty = computed(() => _formSnapshot && JSON.stringify(form.value) !== _formSnapshot)
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
  if (!form.value.budget_usd || Number(form.value.budget_usd) <= 0) errs.push(t('launch.fieldDailyBudget'))
  if (!isReuse && !form.value.landing_url && !form.value.landing_page_id && !['OUTCOME_AWARENESS'].includes(form.value.objective))
    errs.push(t('launch.fieldLandingPickOrUrl'))
  return errs
}
// 完整性状态（UI 显示用）
const completionStatus = computed(() => {
  const errs = validateTemplate()
  if (!errs.length) return { ready: true, label: t('launch.ready'), missing: [] }
  return { ready: false, label: t('launch.pending'), missing: errs }
})

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
  // 系列 Campaign
  objective: 'OUTCOME_TRAFFIC', conversion_goal: '', budget_mode: 'ABO',
  bid_strategy: 'LOWEST_COST_WITHOUT_CAP', budget_usd: 5, name_prefix: 'Tova Ads',
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

// 编辑
const openNew = () => { editing.value = null; form.value = blankForm(); editingAsset.value = null; editLevel.value = 'campaign'; validationErrors.value = []; editOpen.value = true; snapshotForm() }
const openEdit = async (tpl) => {
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
  validationErrors.value = []; editOpen.value = true; snapshotForm()
}
const pickAsset = async (a) => {
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
// 兴趣搜索
const searchInterests = async () => {
  if (!interestQ.value.trim()) return
  interestSearching.value = true
  try { interestResults.value = await GET('/audiences/search?q=' + encodeURIComponent(interestQ.value.trim()) + '&limit=10') }
  catch (e) { showError(e, t('launch.interestSearchFail')) }
  interestSearching.value = false
}
const addInterest = (it) => {
  if (!form.value.audience_interests.find(x => x.id === String(it.id))) form.value.audience_interests.push({ id: String(it.id), name: it.name })
  // 不清结果——用户可能要连续选多个相关兴趣
}
const removeInterest = (i) => form.value.audience_interests.splice(i, 1)
const clearInterestSearch = () => { interestResults.value = []; interestQ.value = '' }
const isInterestAdded = (id) => form.value.audience_interests.some(x => x.id === String(id))
const togglePlatform = (v) => {
  const arr = form.value.placement_platforms || []
  const i = arr.indexOf(v)
  if (i >= 0) arr.splice(i, 1); else arr.push(v)
  form.value.placement_platforms = [...arr]
}
const fmtSize = (n) => { if (!n) return ''; if (n >= 1e9) return (n/1e9).toFixed(1)+'B'; if (n >= 1e6) return (n/1e6).toFixed(1)+'M'; if (n >= 1e3) return Math.floor(n/1e3)+'K'; return String(n) }
const importAiInterests = async () => {
  if (!editingAsset.value?.ai_audience?.interests?.length) return ElMessage.warning(t('launch.noAiInterests'))
  let added = 0
  for (const kw of editingAsset.value.ai_audience.interests) {
    try {
      const r = await GET('/audiences/search?q=' + encodeURIComponent(kw) + '&limit=1')
      if (r[0]) { if (!form.value.audience_interests.find(x => x.id === String(r[0].id))) { form.value.audience_interests.push({ id: String(r[0].id), name: r[0].name }); added++ } }
    } catch {}
  }
  ElMessage.success(t('launch.importedInterests', { n: added }))
}
// 保存
const buildAudienceJson = () => {
  const a = { countries: form.value.audience_countries||[], interests: form.value.audience_interests||[], age_min: form.value.audience_age_min||18, age_max: form.value.audience_age_max||65, gender: form.value.audience_gender||0 }
  if (form.value.audience_language) a.languages = [form.value.audience_language]
  return JSON.stringify(a)
}
const saveTpl = async () => {
  validationErrors.value = validateTemplate()
  if (validationErrors.value.length) {
    return ElMessage.warning(t('launch.pendingMissing', { fields: validationErrors.value.join('、') }))
  }
  saving.value = true
  try {
    const body = {
      name: form.value.name, description: form.value.description,
      objective: form.value.objective, conversion_goal: form.value.conversion_goal,
      budget_mode: form.value.budget_mode, bid_strategy: form.value.bid_strategy,
      budget_usd: Number(form.value.budget_usd), name_prefix: form.value.name_prefix,
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
      if (form.value.manual_placement) {
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
// 预检
const preflighting = ref(false)
const preflight = async (tpl) => {
  preflighting.value = true
  try {
    // accounts 只在部署抽屉打开时加载——独立入口先拉本租户账户，取第一个 managed 正常账户预检
    let accs = accounts.value
    if (!accs.length) { try { accs = await GET('/fb/accounts') } catch {} }
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
const openDeploy = async (tpl) => {
  deployTpl.value = tpl; deployOpen.value = true; selectedAccs.value = new Set(); deployItems.value = {}
  reuseEligibleActs.value = new Set()
  deployAsset.value = null
  if (tpl.asset_id) { try { deployAsset.value = await GET('/assets/' + tpl.asset_id) } catch {} }
  accLoading.value = true
  try { accounts.value = await GET('/fb/accounts') } catch (e) { showError(e, t('launch.loadAccFail')) }
  if (tpl.post_source === 'reuse' && tpl.id) {
    // 后端权威判定：候选池里有能管该帖主页的写令牌的账户才可选（多令牌同账户也覆盖）
    try { const r = await GET('/launch-templates/' + tpl.id + '/reuse-eligible'); reuseEligibleActs.value = new Set(r.eligible || []) }
    catch (e) { showError(e, t('launch.loadAccFail')) }
  }
  accLoading.value = false
}
// 选中账户后拉该账户可用的主页/像素（deployItems 填模板默认值）
const ensureAccConfig = async (id) => {
  if (accPages.value[id]) return
  const acc = accounts.value.find(a => a.act_id === id)
  const credId = acc?.fb_credential_id
  deployItems.value[id] = { page_id: deployTpl.value.page_id || '', pixel_id: deployTpl.value.pixel_id || '' }
  if (credId) {
    accLoadingConfig.value.add(id); accLoadingConfig.value = new Set(accLoadingConfig.value)
    try {
      const [pages, pixels] = await Promise.all([
        GET('/fb/credentials/' + credId + '/pages').catch(() => []),
        GET('/fb/credentials/' + credId + '/pixels').catch(() => []),
      ])
      accPages.value[id] = pages; accPixels.value[id] = pixels
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
const startDeploy = async () => {
  if (!selectedAccs.value.size) return ElMessage.warning(t('launch.selectAccFirst'))
  const items = [...selectedAccs.value].map(id => ({ act_id: id, page_id: deployItems.value[id]?.page_id || '', pixel_id: deployItems.value[id]?.pixel_id || '' }))
  deploying.value = true
  try {
    const r = await POST('/launch-templates/' + deployTpl.value.id + '/deploy', { items })
    deployOpen.value = false; ElMessage.success(t('launch.submitted', { n: r.total })); openProgress(r.job_id); await load()
  } catch (e) { showError(e, t('launch.deploySubmitFail')) }
  deploying.value = false
}
// 进度
const openProgress = async (jobId) => {
  progressOpen.value = true; activeJob.value = null
  await pollJob(jobId)
  if (pollTimer) clearTimeout(pollTimer)
  startPoll(jobId, 0)
}
// 前 12 次（30s）每 2.5s，之后每 10s；终态由 pollJob 停止
const startPoll = (jobId, n) => {
  pollTimer = setTimeout(async () => {
    await pollJob(jobId)
    if (pollTimer) startPoll(jobId, n + 1)
  }, n < 12 ? 2500 : 10000)
}
const pollJob = async (jobId) => {
  try {
    activeJob.value = await GET('/launch-templates/jobs/' + jobId)
    if (['completed','partial_failed','failed'].includes(activeJob.value.status)) { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null } }
  } catch {}
}
const retryItem = async (it) => {
  try { await POST(`/launch-templates/jobs/${activeJob.value.id}/retry/${it.id}`, {}); ElMessage.success(t('launch.retrySubmitted'))
    if (!pollTimer) startPoll(activeJob.value.id, 0) } catch (e) { showError(e, t('launch.retryFail')) }
}
const statusText = (s) => itemStatus(s).label
const statusColor = (s) => { const c = itemStatus(s).cls; return c === 'ok' ? 'var(--success)' : c === 'err' ? 'var(--error)' : c === 'warn' ? 'var(--ac)' : 'var(--t3)' }
const jobText = (s) => jobStatus(s).label
const fbAdsUrl = (actId, campId) => `https://www.facebook.com/adsmanager/manage/campaigns?act=${actId}&selected_campaign_ids=${campId}`
</script>

<template>
  <div class="page">
    <div class="bar">
      <div class="t">{{ t('launch.title') }}</div>
      <div style="display:flex;gap:8px">
        <button class="btn" @click="openHistory">{{ t('launch.deployHistory') }}</button>
        <button class="btn primary" @click="openNew">+ {{ t('launch.newTemplate') }}</button>
      </div>
    </div>
    <div class="d">{{ t('launch.subtitle') }}</div>

    <div class="grid" v-loading="loading">
      <div v-for="tpl in list" :key="tpl.id" class="card">
        <div class="card-head">
          <span class="card-name">{{ tpl.name }}</span>
          <span :class="['card-badge', _tplReady(tpl) ? 'ready' : 'pending']" :title="_tplMissing(tpl).join('、')">
            {{ _tplReady(tpl) ? '✓ ' + t('launch.ready') : t('launch.pending') }}
          </span>
        </div>
        <div class="card-meta"><span class="card-obj">{{ objLabel(tpl.objective) }}</span><span>{{ fmtUsd(tpl.budget_usd) }}/{{ t('launch.perDay') }}</span></div>
        <button v-if="tpl.deploy_count" class="card-dep" @click="openDeployments(tpl)" :title="t('launch.deployedListTitle', { name: tpl.name })">{{ t('launch.deployedList') }} {{ tpl.deploy_count }} ↗</button>
        <div v-if="!_tplReady(tpl)" class="card-warn">{{ t('launch.missing') }}：{{ _tplMissing(tpl).join('、') }}</div>
        <div class="card-ops">
          <button class="op primary" @click="openDeploy(tpl)">{{ t('launch.deploy') }}</button>
          <button class="op" @click="openEdit(tpl)">{{ t('common.edit') }}</button>
          <button class="op" @click="copyTpl(tpl)" :title="t('launch.copyVariant')">{{ t('common.copy') }}</button>
          <button class="op" :disabled="preflighting" @click="preflight(tpl)" :title="t('launch.preflightTitle')">{{ t('launch.preflight') }}</button>
          <button class="op danger" @click="removeTpl(tpl)">{{ t('launch.archive') }}</button>
        </div>
      </div>
      <div v-if="!list.length && !loading" class="empty">{{ t('launch.emptyHint') }}</div>
    </div>

    <!-- 编辑抽屉：系列/组/广告 三级 -->
    <el-drawer v-model="editOpen" :title="editing ? t('launch.editTemplate') : t('launch.newTemplate')" direction="rtl" size="680px" :destroy-on-close="true" :before-close="onEditBeforeClose">
      <!-- 顶层模式切换：新建帖 / 跟帖(复用已有帖) —— 决定 ③ 广告 Tab 含义，故置顶 -->
      <div class="post-mode-seg">
        <button :class="['ps-btn',{on:form.post_source==='new'}]" @click="setPostSource('new')">📝 {{ t('launch.postSourceNew') }}</button>
        <button :class="['ps-btn',{on:form.post_source==='reuse'}]" @click="setPostSource('reuse')">📌 {{ t('launch.postSourceReuse') }}</button>
      </div>
      <!-- 跟帖：置顶选帖卡（解决"不知在哪输入帖子ID"的发现性） -->
      <div v-if="form.post_source==='reuse'" class="reuse-select-card">
        <div class="reuse-card-hint">{{ t('launch.reuseCardHint') }}</div>
        <div class="reuse-input-row">
          <input v-model="manualPostId" class="inp" :disabled="postResolving" :placeholder="t('launch.manualPostPh')" @keyup.enter="confirmManualPost" />
          <button class="btn sm primary" :disabled="postResolving || !manualPostId.trim()" @click="confirmManualPost">{{ postResolving ? t('launch.resolving') : t('launch.recognize') }}</button>
          <button class="btn sm" :disabled="!form.page_id" @click="openPostPicker">{{ t('launch.browsePosts') }}</button>
        </div>
        <!-- 识别失败 → 手选主页兜底 -->
        <div v-if="reuseNeedManualPage" class="reuse-manual-page">
          <span class="hint">⚠ {{ t('launch.resolveFailManual') }}</span>
          <el-select v-model="manualPageForPost" filterable size="small" style="flex:1;min-width:160px" :placeholder="t('launch.pageIdPh')">
            <el-option v-for="p in tplPages" :key="p.id" :value="p.id" :label="(p.name||p.id) + ' (' + p.id + ')'" />
          </el-select>
          <button class="btn sm primary" :disabled="!manualPageForPost" @click="confirmManualPostWithPage">{{ t('common.confirm') }}</button>
        </div>
        <!-- 已选帖 + 内容预览（让用户看到选的是啥） -->
        <div v-if="form.reuse_post_ref" class="reuse-selected-block">
          <div class="reuse-selected">
            📌 <span class="reuse-post-id" :title="form.reuse_post_ref">{{ form.reuse_post_ref }}</span>
            <button class="btn sm ghost" @click="clearReusePost">{{ t('common.remove') }}</button>
          </div>
          <div v-if="reusePreviewAvailable" class="reuse-mini-preview">
            <img v-if="reusePostPreview.picture" :src="reusePostPreview.picture" class="reuse-mini-thumb" />
            <div class="reuse-mini-text">{{ (reusePostPreview.message || '').slice(0,120) || t('launch.noPostText') }}</div>
          </div>
          <div v-else-if="reusePostPreview" class="hint">⚠ {{ t('launch.postContentUnavailable') }}</div>
          <div v-else class="hint">{{ t('launch.loadingPreview') }}</div>
        </div>
        <div v-else-if="!form.page_id" class="hint">{{ t('launch.reuseNoPageHint') }}</div>
      </div>

      <div class="level-tabs">
        <button :class="['ltab',{on:editLevel==='campaign'}]" @click="editLevel='campaign'">① {{ t('launch.levelCampaign') }}</button>
        <button :class="['ltab',{on:editLevel==='adset'}]" @click="editLevel='adset'">② {{ t('launch.levelAdSet') }}</button>
        <button :class="['ltab',{on:editLevel==='ad'}]" @click="editLevel='ad'">③ {{ t('launch.levelAd') }}</button>
      </div>
      <!-- #8 summary strip：跨级概览 -->
      <div class="summary-strip">
        <span class="ss-chip" @click="editLevel='campaign'" :title="t('launch.gotoCampaign')">{{ t('launch.objColon') }}{{ t(OBJECTIVES.find(o=>o.v===form.objective)?.l || form.objective) }}</span>
        <span class="ss-chip" @click="editLevel='adset'" :title="t('launch.gotoAdSet')">{{ t('launch.audienceColon') }}{{ audienceChip }}</span>
        <span class="ss-chip" @click="editLevel='ad'" :title="t('launch.gotoAd')">{{ t('launch.assetColon') }}{{ editingAsset?.name || t('launch.notSelected') }}</span>
        <span class="ss-chip" @click="editLevel='ad'" :title="t('launch.gotoAd')">{{ t('launch.sourceColon') }}{{ form.post_source==='reuse' ? t('launch.postSourceReuse') : t('launch.postSourceNew') }}</span>
        <span :class="['ss-status', completionStatus.ready ? 'ready' : 'pending']" :title="completionStatus.missing.join('、')">
          {{ completionStatus.ready ? '✓ ' + t('launch.ready') : t('launch.pendingColon') + completionStatus.missing.join('、') }}
        </span>
      </div>

      <!-- ① 系列 -->
      <div v-if="editLevel==='campaign'" class="form">
        <div class="row"><label>{{ t('launch.fieldTplName') }}</label><input v-model="form.name" class="inp" :placeholder="t('launch.tplNamePlaceholder')" /></div>
        <div class="row"><label>{{ t('launch.objective') }}</label><el-select v-model="form.objective" style="width:100%" size="small"><el-option v-for="o in OBJECTIVES" :key="o.v" :value="o.v" :label="t(o.l)" /></el-select></div>
        <div class="row" v-if="convGoalsForObjective.length"><label>{{ t('launch.conversionGoal') }}</label>
          <el-select v-model="form.conversion_goal" style="width:100%" size="small" filterable clearable :placeholder="t('launch.selectConvEvent')">
            <el-option v-for="g in convGoalsForObjective" :key="g" :value="g" :label="t(CONV_GOAL_LABELS[g]||g) + ' (' + g + ')'" />
          </el-select>
        </div>
        <div class="row"><label>{{ t('launch.budgetMode') }}</label><div class="seg"><button :class="{on:form.budget_mode==='ABO'}" @click="form.budget_mode='ABO'">{{ t('launch.abo') }}</button><button :class="{on:form.budget_mode==='CBO'}" @click="form.budget_mode='CBO'">{{ t('launch.cbo') }}</button></div>
          <span v-if="form.budget_mode==='CBO'" class="hint">{{ t('launch.cboHint') }}</span>
        </div>
        <div class="row"><label>{{ t('launch.dailyBudgetUsd') }}</label><input v-model.number="form.budget_usd" type="number" min="1" step="0.5" class="inp" /><span class="hint">{{ t('launch.budgetConvertHint') }}</span></div>
        <div class="row"><label>{{ t('launch.bidStrategy') }}</label><el-select v-model="form.bid_strategy" style="width:100%" size="small"><el-option v-for="b in BID_STRATEGIES" :key="b.v" :value="b.v" :label="t(b.l)" /></el-select></div>
        <div class="row"><label>{{ t('launch.namePrefix') }}</label><input v-model="form.name_prefix" class="inp" /></div>
        <div class="row"><label>{{ t('launch.pageId') }}</label>
          <el-select v-model="form.page_id" filterable clearable size="small" style="width:100%" :placeholder="t('launch.pageIdPh')" :disabled="form.post_source==='reuse'" :title="form.post_source==='reuse' ? t('launch.pageLockedByPost') : ''">
            <el-option v-for="p in tplPages" :key="p.id" :value="p.id" :label="(p.name||p.id) + ' (' + p.id + ')'" />
          </el-select>
          <span class="hint">{{ t('launch.pageIdHint') }}</span>
        </div>
        <div class="row"><label>{{ t('launch.pixelId') }}</label>
          <el-input v-model="form.pixel_id" :placeholder="t('launch.pixelIdPh')" size="small" clearable />
          <span class="hint">{{ t('launch.pixelIdHint') }}</span>
        </div>
      </div>

      <!-- ② 广告组 -->
      <div v-if="editLevel==='adset'" class="form">
        <div class="row"><label>{{ t('launch.optimizationGoal') }}</label><el-select v-model="form.optimization_goal" style="width:100%" size="small" filterable><el-option value="" :label="t('launch.autoByObj')" /><el-option v-for="g in OPT_GOALS" :key="g.v" :value="g.v" :label="t(g.l)" /></el-select></div>
        <div class="row"><label>{{ t('launch.billingEvent') }}</label><el-select v-model="form.billing_event" style="width:100%" size="small"><el-option v-for="b in BILLING_EVENTS" :key="b.v" :value="b.v" :label="t(b.l)" /></el-select></div>
        <div class="row"><label>{{ t('launch.conversionDest') }}</label><el-select v-model="form.destination_type" style="width:100%" size="small" filterable><el-option value="" :label="t('launch.autoOpt')" /><el-option v-for="d in DEST_TYPES" :key="d.v" :value="d.v" :label="t(d.l)" /></el-select></div>
        <hr class="sep" />
        <div class="sec-title">{{ t('launch.perfGoalOptional') }}</div>
        <div class="row"><label>{{ t('launch.cpaGoalLabel') }}</label>
          <input v-model.number="performance_goal_cpa" type="number" min="0" step="0.5" class="inp" :placeholder="t('launch.cpaGoalPlaceholder')" />
          <span class="hint">{{ t('launch.cpaGoalHint') }}</span>
        </div>
        <hr class="sep" />
        <div class="sec-title">{{ t('launch.audienceTargeting') }}</div>
        <!-- 受众来源：保存的受众（SavedAudience，部署时用） / 自定义（下方手动定向） -->
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
            <span v-if="selectedSavedAud.status !== 'active'" class="sa-warn">⚠ {{ t('launch.audInactiveWarn') }}</span>
          </div>
          <div v-if="selectedSavedAud.note" class="sa-note">{{ selectedSavedAud.note }}</div>
          <div class="sa-meta">{{ (selectedSavedAud.countries||[]).join(',') || t('launch.defaultAudience') }} · {{ selectedSavedAud.age_min }}-{{ selectedSavedAud.age_max }} · {{ t('launch.interestCount', { n: (selectedSavedAud.interests||[]).length }) }}</div>
        </div>
        <div v-else class="aud-actions-row">
          <button class="btn sm ghost" :disabled="!hasManualAudience" :title="hasManualAudience ? '' : t('launch.saveAudNeedTargeting')" @click="saveAsAudience">{{ t('launch.saveAsAudience') }}</button>
        </div>
        <template v-if="!form.audience_id">
        <!-- Advantage+ 受众开关（对齐 FB Ads Manager 默认行为） -->
        <div class="advantage-box">
          <div class="adv-row">
            <div class="adv-info">
              <span class="adv-title">{{ t('launch.advPlusAudience') }}</span>
              <span class="adv-desc">{{ t('launch.advPlusAudienceDesc') }}</span>
            </div>
            <el-switch v-model="advantage_audience" active-color="#0a84ff" inactive-color="#3a3a5c" size="small" />
          </div>
        </div>
        <div class="row"><label>{{ t('launch.countries') }}</label>
          <el-select v-model="form.audience_countries" multiple filterable collapse-tags collapse-tags-tooltip
            :placeholder="t('launch.countriesPlaceholder')" style="width:100%" size="small">
            <el-option v-for="c in ALL_COUNTRIES" :key="c.code" :value="c.code" :label="c.label + ' (' + c.code + ')'" />
          </el-select>
        </div>
        <div class="row"><label>{{ t('launch.age') }}</label><div class="age-row"><input v-model.number="form.audience_age_min" type="number" min="13" max="65" class="inp sm" /> — <input v-model.number="form.audience_age_max" type="number" min="13" max="65" class="inp sm" /></div></div>
        <div class="row"><label>{{ t('launch.gender') }}</label><div class="seg"><button :class="{on:form.audience_gender===0}" @click="form.audience_gender=0">{{ t('launch.genderAll') }}</button><button :class="{on:form.audience_gender===1}" @click="form.audience_gender=1">{{ t('launch.genderMale') }}</button><button :class="{on:form.audience_gender===2}" @click="form.audience_gender=2">{{ t('launch.genderFemale') }}</button></div></div>
        <div class="row"><label>{{ t('launch.languageLabel') }}</label>
          <el-select v-model="form.audience_language" filterable clearable :placeholder="t('launch.langAny')" style="width:100%" size="small">
            <el-option v-for="l in LANGS.filter(x=>x.v)" :key="l.v" :value="l.v" :label="t(l.l)" />
          </el-select>
        </div>
        <template v-if="!advantage_audience">
        <div class="row"><label>{{ t('launch.interestLabel') }}</label>
          <div class="interest-search">
            <input v-model="interestQ" class="inp" :placeholder="t('launch.interestPlaceholder')" @keyup.enter="searchInterests" />
            <button class="btn sm" :disabled="interestSearching" @click="searchInterests">{{ interestSearching ? '…' : t('common.search') }}</button>
            <button class="btn sm ghost" @click="importAiInterests" v-if="editingAsset?.ai_audience?.interests?.length">{{ t('launch.importFromAssetAi') }}</button>
          </div>
          <div v-if="interestSearching" class="search-results"><div class="search-loading">{{ t('launch.searching') }}</div></div>
          <div v-else-if="interestResults.length" class="search-results">
            <div class="search-results-head"><span>{{ t('launch.searchResultsHint') }}</span><button class="clear-btn" @click="clearInterestSearch">{{ t('launch.clear') }} ✕</button></div>
            <div v-for="r in interestResults" :key="r.id" :class="['search-item', { added: isInterestAdded(r.id) }]" @click="!isInterestAdded(r.id) && addInterest(r)">
              <span>{{ r.name }}</span>
              <span class="sz">{{ fmtSize(r.audience_size_lower_bound || r.audience_size) }}</span>
              <span class="add" v-if="!isInterestAdded(r.id)">+</span>
              <span class="added-mark" v-else>✓</span>
            </div>
          </div>
        </div>
        <div class="row"><label>{{ t('launch.selectedInterests', { n: form.audience_interests.length }) }}</label>
          <div class="interest-list">
            <span v-for="(it,i) in form.audience_interests" :key="it.id" class="interest-chip">{{ it.name }} <button @click="removeInterest(i)">✕</button></span>
            <span v-if="!form.audience_interests.length" class="hint">{{ t('launch.addViaSearch') }}</span>
          </div>
        </div>
        </template>
        </template>
        <hr class="sep" />
        <div class="sec-title">{{ t('launch.placement') }}</div>
        <div class="row"><label>{{ t('launch.adPlacement') }}</label>
          <div class="seg">
            <button :class="{on:!form.manual_placement}" @click="form.manual_placement=false">{{ t('launch.advPlusPlacement') }}</button>
            <button :class="{on:form.manual_placement}" @click="form.manual_placement=true">{{ t('launch.manualSelect') }}</button>
          </div>
        </div>
        <div v-if="form.manual_placement">
          <div class="row"><label>{{ t('launch.device') }}</label>
            <div class="placement-chips">
              <label v-for="d in DEVICES" :key="d.v" class="placement-chip" :class="{on:(form.placement_devices||[]).includes(d.v)}">
                <input type="checkbox" :checked="(form.placement_devices||[]).includes(d.v)" @change="toggleDevice(d.v)" /> {{ t(d.l) }}
              </label>
            </div>
          </div>
          <div class="row"><label>{{ t('launch.platformsAndPlacements') }}</label>
            <div class="placement-tree">
              <div v-for="p in PLATFORMS" :key="p.v" class="pt-node">
                <div class="pt-head" @click="togglePlatformExpand(p.v)">
                  <span class="pt-arrow" :class="{open:expandedPlatforms.has(p.v)}">▶</span>
                  <label class="pt-label" :class="{on:isPlatformOn(p.v)}" @click.stop="togglePlatformSel(p.v)">
                    <input type="checkbox" :checked="isPlatformOn(p.v)" @change="togglePlatformSel(p.v)" /> {{ p.l }}
                  </label>
                </div>
                <div v-if="expandedPlatforms.has(p.v) && isPlatformOn(p.v)" class="pt-positions">
                  <label v-for="pos in p.positions" :key="pos.v" class="pos-chip" :class="{on:isPosOn(p.v,pos.v)}">
                    <input type="checkbox" :checked="isPosOn(p.v,pos.v)" @change="togglePos(p.v,pos.v)" /> {{ t(pos.l) }}
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>
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
      </div>

      <!-- ③ 广告 -->
      <div v-if="editLevel==='ad'" class="form">
        <!-- 跟帖：帖子内容只读预览（图/标题/文案/链接/CTA 全锁，来自帖子）-->
        <template v-if="form.post_source==='reuse'">
          <div class="reuse-preview-banner">🔒 {{ t('launch.reuseLockedHint') }}</div>
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
            <div class="post-preview-text muted">⚠ {{ t('launch.postContentUnavailable') }}<br><code>{{ form.reuse_post_ref }}</code></div>
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
        <!-- Advantage+ 创意（对齐 FB Ads Manager） -->
        <div class="advantage-box">
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
        <div class="row"><label>{{ t('launch.ctaLabel') }}</label><el-select v-model="form.cta_type" style="width:100%" size="small" filterable><el-option v-for="c in CTAS" :key="c.v" :value="c.v" :label="t(c.l) + '（' + c.v + '）'" /></el-select></div>
        <div class="hint" style="padding:6px 10px;background:var(--bg3);border-radius:6px">{{ t('launch.pagePixelHint') }}</div>
        <div class="row"><label>{{ t('launch.landing') }}</label>
          <select v-model="form.landing_page_id" class="inp" @change="onLandingChange">
            <option :value="null">{{ t('launch.manualUrl') }}</option>
            <option v-for="p in landingPages" :key="p.id" :value="p.id">{{ p.title }}（{{ p.public_url || t('launch.noUrl') }}）</option>
          </select>
        </div>
        <div class="row"><label>{{ t('launch.landingUrl') }}</label><input v-model="form.landing_url" class="inp" placeholder="https://..." /></div>
        <div class="row"><label>{{ t('launch.subcode') }}</label>
          <el-select v-model="form.subcode_slug" filterable clearable :placeholder="t('launch.subcodePlaceholder')" style="width:100%" size="small">
            <el-option v-for="s in subcodesForLanding" :key="s.slug" :value="s.slug" :label="s.slug + (s.status ? ' ('+s.status+')' : '')" />
          </el-select>
          <span v-if="form.landing_page_id && !subcodesForLanding.length" class="hint">{{ t('launch.noSubcodeHint') }}</span>
        </div>
        <!-- 消息类（ENGAGEMENT + 消息目标） -->
        <template v-if="form.objective === 'OUTCOME_ENGAGEMENT'">
          <hr class="sep" /><div class="sec-title-row"><span class="sec-title">{{ t('launch.messageAd') }}</span>
            <router-link to="/form-templates" class="new-link">{{ t('launch.manageMsgTpl') }} →</router-link>
          </div>
          <div class="row"><label>{{ t('launch.messengerWelcomeTpl') }}</label>
            <el-select v-model="form.message_template_id" style="width:100%" size="small" filterable clearable :placeholder="t('launch.selectMsgTpl')" @change="onMsgTplChange">
              <el-option v-for="m in msgTemplates" :key="m.id" :value="m.id" :label="m.name + ' · ' + (m.welcome_text||'').slice(0,20)" />
            </el-select>
          </div>
          <div v-if="selectedMsgTpl" class="tpl-preview-bar" @click="msgPreviewOpen = true">
            <span>{{ (selectedMsgTpl.welcome_text||'').slice(0,50) }}…</span>
            <span class="preview-link">{{ t('common.preview') }}</span>
          </div>
        </template>
        <!-- 表单类（LEADS + Instant Forms） -->
        <template v-if="form.objective === 'OUTCOME_LEADS'">
          <hr class="sep" /><div class="sec-title-row"><span class="sec-title">Instant Form</span>
            <router-link to="/form-templates" class="new-link">{{ t('launch.manageFormTpl') }} →</router-link>
          </div>
          <div class="row"><label>{{ t('launch.formTemplate') }}</label>
            <el-select v-model="form.lead_form_template_id" style="width:100%" size="small" filterable clearable :placeholder="t('launch.selectFormTpl')" @change="onFormTplChange">
              <el-option v-for="f in formTemplates" :key="f.id" :value="f.id" :label="f.name + (f.fb_form_id ? ' ✓' : '')" />
            </el-select>
          </div>
          <div v-if="selectedFormTpl" class="tpl-preview-bar" @click="formPreviewOpen = true">
            <span>{{ (selectedFormTpl.config||{}).form_title || selectedFormTpl.name }}</span>
            <span class="preview-link">{{ t('common.preview') }}</span>
          </div>
        </template>
        </template>
      </div>

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
      <div class="d">{{ t('launch.deploySubtitle') }}</div>
      <div v-if="deployTpl?.post_source==='reuse'" class="deploy-reuse-hint">⚠ {{ t('launch.deployReuseHint') }}（{{ (deployTpl?.reuse_post_ref||'').split('_')[0] }}）</div>
      <div v-if="deployAsset?.type==='video'" class="deploy-video-hint">{{ t('launch.deployVideoHint', { name: deployAsset.name || deployAsset.filename || '' }) }}<template v-if="deployAsset.duration_sec">（{{ t('launch.durationLabel') }} {{ deployAsset.duration_sec }}s）</template></div>
      <div class="deploy-search-row">
        <input v-model="deploySearch" class="inp" :placeholder="t('launch.searchAccountPlaceholder')" />
        <span class="acc-count-hint">{{ filteredDeployAccounts.length }} / {{ accounts.length }} {{ t('launch.accountsUnit') }}</span>
      </div>
      <div class="acc-batch-row">
        <button class="op sm" @click="deploySelectAll">{{ t('launch.deploySelectAll') }}</button>
        <button class="op sm" @click="deploySelectActive">{{ t('launch.deploySelectActive') }}</button>
        <button class="op sm" @click="deployClearSel">{{ t('launch.deployClear') }}</button>
      </div>
      <div class="acc-list" v-loading="accLoading">
        <div v-for="a in filteredDeployAccounts" :key="a.act_id" :class="['acc-block', {disabled: reuseDeployPage && !accManagesReusePage(a.act_id)}]">
          <label class="acc-row" :class="{on:selectedAccs.has(a.act_id)}">
            <input type="checkbox" :checked="selectedAccs.has(a.act_id)" :disabled="reuseDeployPage && !accManagesReusePage(a.act_id)" @change="toggleAcc(a.act_id)" />
            <span class="acc-name">{{ a.name || a.act_id }}</span>
            <span class="acc-id">{{ a.act_id }} · {{ a.currency }}</span>
            <span :class="['acc-status', a.account_status === 1 ? 'ok' : 'warn']" :title="a.account_status === 1 ? t('launch.accNormal') : t('launch.accAbnormal')">{{ a.account_status === 1 ? t('launch.accNormal') : t('launch.accAbnormal') }}</span>
            <span v-if="reuseDeployPage && !accManagesReusePage(a.act_id)" class="acc-no-perm" :title="t('launch.noPagePermission')">🔒</span>
          </label>
          <div v-if="selectedAccs.has(a.act_id)" class="acc-config">
            <template v-if="accLoadingConfig.has(a.act_id)">
              <span class="config-loading">{{ t('launch.loadingPagePixel') }}</span>
            </template>
            <template v-else>
              <label>{{ t('launch.page') }}</label>
              <select v-model="deployItems[a.act_id].page_id" class="inp sm">
                <option value="">{{ t('launch.defaultVal', { v: deployTpl?.page_id || t('launch.none') }) }}</option>
                <option v-for="p in (accPages[a.act_id]||[])" :key="p.id" :value="p.id">{{ p.name }} ({{ p.id }})</option>
              </select>
              <label>{{ t('launch.pixel') }}</label>
              <select v-model="deployItems[a.act_id].pixel_id" class="inp sm">
                <option value="">{{ t('launch.defaultVal', { v: deployTpl?.pixel_id || t('launch.none') }) }}</option>
                <option v-for="p in (accPixels[a.act_id]||[])" :key="p.id" :value="p.id">{{ p.name }} ({{ p.id }})</option>
              </select>
            </template>
          </div>
        </div>
      </div>
      <template #footer>
        <span class="sel-count">{{ t('launch.selectedCount', { n: selectedAccs.size }) }}<template v-if="selectedAccs.size && deployTpl"> · {{ t('launch.totalBudgetHint', { total: (selectedAccs.size * Number(deployTpl.budget_usd || 0)).toFixed(0), per: Number(deployTpl.budget_usd || 0) }) }}</template></span>
        <button class="btn" @click="deployOpen=false">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="deploying||!selectedAccs.size" @click="startDeploy">{{ deploying ? t('launch.submitting') : t('launch.startDeploy') }}</button>
      </template>
    </el-drawer>

    <!-- 进度 -->
    <el-dialog v-model="progressOpen" :title="t('launch.deployProgress')" width="720px" :close-on-click-modal="false" @close="if(pollTimer){clearTimeout(pollTimer);pollTimer=null}">
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
            <a v-if="it.campaign_id" :href="fbAdsUrl(it.act_id,it.campaign_id)" target="_blank" class="pi-link">{{ t('launch.fbAds') }}→</a>
            <span v-if="it.error" class="pi-err" :title="fbErrorText(it.error_code) || it.error">{{ (fbErrorText(it.error_code) || it.error).slice(0,60) }}</span>
            <button v-if="it.status==='fail'" class="op primary sm" @click="retryItem(it)">{{ t('common.retry') }}</button>
          </div>
        </div>
      </div>
    </el-dialog>
    <!-- 预检结果（结构化展示） -->
    <el-dialog v-model="preflightVisible" :title="t('launch.preflightTitle')" width="700px" append-to-body>
      <div v-if="preflightResult" class="preflight">
        <div v-if="preflightResult.subcode_warn_slug" style="color:var(--warning);padding:8px 0;font-size:13px">⚠ {{ t('launch.subcodeWarn', { slug: preflightResult.subcode_warn_slug }) }}</div>
        <div v-if="preflightResult.asset?.type === 'video'" style="padding:4px 0;font-size:13px">{{ t('launch.videoAsset') }}：{{ preflightResult.asset.name || preflightResult.asset.filename }}<template v-if="preflightResult.asset.duration_sec"> · {{ t('launch.durationLabel') }} {{ preflightResult.asset.duration_sec }}s</template></div>
        <div class="pf-summary">
          <span>{{ t('launch.pfCurrency') }}：<b>{{ preflightResult.currency }}</b></span>
          <span>{{ t('launch.budgetColon') }}${{ preflightResult.budget_usd }} → <b>{{ preflightResult.daily_budget_fb }}</b>（{{ t('launch.minorUnitHint') }}）</span>
          <span>{{ t('launch.fxRate') }}：{{ preflightResult.fx_rate || t('launch.none') }}</span>
          <span>{{ t('launch.modeColon') }}{{ preflightResult.budget_mode }}</span>
        </div>
        <div class="pf-section">
          <div class="pf-title">{{ t('launch.pfCampaign') }}</div>
          <div class="pf-fields"><div v-for="(v,k) in preflightResult.campaign" :key="k" class="pf-field"><span class="pf-k">{{ k }}</span><span class="pf-v">{{ JSON.stringify(v) }}</span></div></div>
        </div>
        <div class="pf-section">
          <div class="pf-title">{{ t('launch.pfAdSet') }}</div>
          <div class="pf-fields"><div v-for="(v,k) in preflightResult.adset" :key="k" class="pf-field"><span class="pf-k">{{ k }}</span><span class="pf-v">{{ JSON.stringify(v) }}</span></div></div>
        </div>
        <div class="pf-section">
          <div class="pf-title">{{ t('launch.pfCreative') }}</div>
          <div class="pf-fields"><div v-for="(v,k) in preflightResult.creative" :key="k" class="pf-field"><span class="pf-k">{{ k }}</span><span class="pf-v">{{ JSON.stringify(v) }}</span></div></div>
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
          <div class="hi-meta">{{ j.succeeded }}✓ / {{ j.failed }}✗ / {{ j.total }} · {{ (j.created_at||'').slice(0,16) }}</div>
        </div>
        <div v-if="!jobs.length" class="empty-sm">{{ t('launch.noDeployRecords') }}</div>
      </div>
    </el-dialog>

    <!-- 模板已部署清单（卡片「已部署 N」入口；展开单次看明细+广告当前状态） -->
    <el-drawer v-model="depOpen" :title="t('launch.deployedListTitle', { name: depTpl?.name || '' })" direction="rtl" size="640px">
      <div v-loading="depLoading">
        <div v-for="j in depJobs" :key="j.id" class="dep-job">
          <div class="dep-job-head" @click="toggleDepJob(j)">
            <span class="dep-job-time">{{ (j.created_at||'').slice(0,19).replace('T',' ') }}</span>
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
              <a v-if="it.campaign_id" :href="fbAdsUrl(it.act_id,it.campaign_id)" target="_blank" class="pi-link">{{ t('launch.fbAds') }}→</a>
              <span v-if="it.error" class="pi-err" :title="fbErrorText(it.error_code) || it.error">{{ (fbErrorText(it.error_code) || it.error).slice(0,40) }}</span>
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
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:6px}
.card-head{display:flex;justify-content:space-between;align-items:baseline;gap:6px}
.card-name{font-size:14px;font-weight:600;color:var(--t1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-obj{font-size:11px;color:var(--ac);white-space:nowrap}
.card-badge{font-size:10px;padding:2px 8px;border-radius:8px;font-weight:600;white-space:nowrap}
.card-badge.ready{color:var(--success);background:rgba(52,199,89,.13)}
.card-badge.pending{color:var(--warning);background:rgba(255,159,10,.13)}
.card-warn{font-size:11px;color:var(--warning);padding:2px 0}
.card-meta{display:flex;gap:10px;font-size:11px;color:var(--t3);flex-wrap:wrap}
.card-copy{font-size:11px;color:var(--t2);font-style:italic;max-height:32px;overflow:hidden}
/* 已部署清单入口（卡片）+ 抽屉 */
.card-dep{align-self:flex-start;background:none;border:none;color:var(--ac);font-size:11px;cursor:pointer;padding:0;font-family:inherit}
.card-dep:hover{text-decoration:underline}
.dep-job{border:1px solid var(--bd);border-radius:8px;overflow:hidden;margin-bottom:8px}
.dep-job-head{display:flex;align-items:center;gap:10px;padding:8px 12px;cursor:pointer;background:var(--bg3)}
.dep-job-head:hover{background:var(--bg2)}
.dep-job-time{font-size:12px;color:var(--t1);font-variant-numeric:tabular-nums}
.dep-job-counts{font-size:11px;color:var(--t3);margin-left:auto}
.dep-arrow{font-size:9px;color:var(--t3);transition:transform .15s;display:inline-block}
.dep-arrow.open{transform:rotate(90deg)}
.dep-items{border-top:1px solid var(--bd);display:flex;flex-direction:column;gap:2px;padding:6px 0;max-height:40vh;overflow-y:auto}
.dep-item{display:flex;align-items:center;gap:8px;padding:4px 12px;font-size:12px}
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
.op:hover{background:var(--bg3)}
.empty{grid-column:1/-1;padding:40px;text-align:center;color:var(--t3);font-size:14px}

.level-tabs{display:flex;gap:4px;margin-bottom:16px;background:var(--bg3);padding:3px;border-radius:8px}
.ltab{flex:1;padding:8px;border:none;background:transparent;color:var(--t3);border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;font-family:inherit}
.ltab.on{background:var(--bg2);color:var(--ac)}
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
.interest-chip{font-size:11px;padding:3px 8px;background:var(--acg);color:var(--ac);border-radius:10px;display:flex;align-items:center;gap:4px}
.interest-chip button{background:none;border:none;color:var(--t3);cursor:pointer;font-size:10px;padding:0}

.asset-pick{display:flex;align-items:center;gap:10px}
.asset-chosen{display:flex;align-items:center;gap:6px;flex:1}
.asset-thumb{width:40px;height:40px;object-fit:cover;border-radius:6px}
.asset-name{font-size:12px;color:var(--t2)}
.ai-copy{background:var(--bg3);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column;gap:4px}
.ai-copy-t{font-size:11px;color:var(--t3);margin-bottom:2px}
.ai-pick{font-size:12px;color:var(--t2);cursor:pointer;padding:3px 6px;border-radius:4px;line-height:1.4}
.ai-pick:hover{background:var(--bg2);color:var(--t1)}
.ai-tag{font-size:9px;color:var(--ac);background:rgba(10,132,255,.15);padding:1px 4px;border-radius:3px;margin-right:4px}

.picker-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
.picker-card{background:var(--bg2);border:1px solid var(--bd);border-radius:8px;overflow:hidden;cursor:pointer;content-visibility:auto;contain-intrinsic-size:140px}
.picker-card:hover{border-color:var(--ac)}
.picker-thumb{width:100%;height:90px;object-fit:cover}
.picker-name{display:block;font-size:11px;color:var(--t2);padding:4px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.post-mode-seg{display:flex;gap:0;border-bottom:1px solid var(--bd);margin-bottom:14px}
.ps-btn{flex:none;padding:9px 18px;border:none;background:transparent;color:var(--t3);font-size:14px;cursor:pointer;font-family:inherit;border-bottom:2px solid transparent;margin-bottom:-1px;font-weight:500;transition:color .15s}
.ps-btn:hover{color:var(--t2)}
.ps-btn.on{color:var(--ac);border-bottom-color:var(--ac);font-weight:600}
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
.ad-preview-card{border:1px solid var(--bd);border-radius:10px;background:var(--bg2);padding:14px 16px;display:flex;flex-direction:column;gap:12px}
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
.deploy-search-row .inp{flex:1}
.acc-config{padding:8px 10px;background:var(--bg3);display:grid;grid-template-columns:auto 1fr auto 1fr;gap:6px;align-items:center}
.acc-config label{font-size:11px;color:var(--t3)}
.sel-count{font-size:12px;color:var(--t3);margin-right:auto}

.prog-head{display:flex;gap:14px;align-items:center;margin-bottom:10px;font-size:13px}
.prog-stat{color:var(--t2);font-variant-numeric:tabular-nums}
.prog-status{font-size:11px;padding:2px 8px;border-radius:10px;font-weight:600}
.prog-status.completed{color:var(--success);background:rgba(52,199,89,.13)}
.prog-status.partial_failed{color:var(--warning);background:rgba(255,159,10,.13)}
.prog-status.running{color:var(--ac);background:rgba(10,132,255,.13)}
.prog-status.failed{color:var(--error);background:rgba(255,69,58,.13)}
.prog-items{display:flex;flex-direction:column;gap:2px;max-height:50vh;overflow-y:auto}
.prog-item{display:flex;align-items:center;gap:8px;padding:6px 8px;font-size:12px;border-bottom:1px solid var(--bd)}
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

/* #8 summary strip */
.summary-strip{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;padding:6px 10px;background:var(--bg3);border-radius:8px}
.ss-chip{font-size:11px;color:var(--t2);padding:2px 8px;background:var(--bg2);border-radius:10px;cursor:pointer;transition:color .15s}
.ss-chip:hover{color:var(--ac)}
.ss-status{font-size:11px;padding:2px 8px;border-radius:8px;font-weight:600;margin-left:auto}
.ss-status.ready{color:var(--success);background:rgba(52,199,89,.13)}
.ss-status.pending{color:var(--warning);background:rgba(255,159,10,.13)}

/* Advantage+ 盒子 */
.advantage-box{border:1px solid var(--ac);border-radius:10px;padding:10px 14px;margin:4px 0;background:rgba(10,132,255,.05)}
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
.dpa-hhdr{grid-column:2;grid-row:1;display:flex;justify-content:space-between;font-size:9px;color:var(--t3);padding:0 2px 3px}
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
.pt-arrow{font-size:9px;color:var(--t3);transition:transform .15s;display:inline-block;transform:rotate(0deg)}
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

/* #23 移动端适配 */
@media (max-width: 768px) {
  .grid{grid-template-columns:1fr !important}
  .picker-grid{grid-template-columns:1fr !important}
  .acc-config{grid-template-columns:1fr !important}
  .level-tabs{flex-direction:column}
  .summary-strip{flex-direction:column}
}
</style>
