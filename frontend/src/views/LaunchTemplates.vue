<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { showError } from '../composables/useError'

const list = ref([])
const loading = ref(false)
const editOpen = ref(false)
const editing = ref(null)
const form = ref({})
const saving = ref(false)
const editLevel = ref('campaign')  // 3 Tab: campaign / adset / ad
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

const OBJECTIVES = [
  { v: 'OUTCOME_SALES', l: '购物（转化）' },
  { v: 'OUTCOME_LEADS', l: '潜在客户（留资）' },
  { v: 'OUTCOME_TRAFFIC', l: '流量（点击）' },
  { v: 'OUTCOME_ENGAGEMENT', l: '互动（赞/消息）' },
  { v: 'OUTCOME_AWARENESS', l: '品牌认知' },
  { v: 'OUTCOME_APP_PROMOTION', l: '应用推广' },
]
const OPT_GOALS = [
  {v:'LINK_CLICKS',l:'链接点击'},{v:'LANDING_PAGE_VIEWS',l:'落地页浏览'},{v:'REACH',l:'覆盖人数'},
  {v:'IMPRESSIONS',l:'展示次数'},{v:'OFFSITE_CONVERSIONS',l:'网站转化'},{v:'LEAD_GENERATION',l:'潜在客户'},
  {v:'PAGE_LIKES',l:'主页赞'},{v:'POST_ENGAGEMENT',l:'帖子互动'},{v:'CONVERSATIONS',l:'消息会话'},
  {v:'THRUPLAY',l:'视频播放'},{v:'APP_INSTALLS',l:'应用安装'},{v:'VALUE',l:'价值'},
]
const BILLING_EVENTS = [
  {v:'IMPRESSIONS',l:'展示'},{v:'LINK_CLICKS',l:'链接点击'},{v:'APP_INSTALLS',l:'应用安装'},
  {v:'PAGE_LIKES',l:'主页赞'},{v:'POST_ENGAGEMENT',l:'帖子互动'},{v:'THRUPLAY',l:'视频播放'},
]
const DEST_TYPES = [
  {v:'WEBSITE',l:'网站'},{v:'ON_AD',l:'应用内'},{v:'ON_PAGE',l:'主页'},{v:'MESSENGER',l:'Messenger'},
  {v:'APP',l:'应用'},{v:'WHATSAPP',l:'WhatsApp'},{v:'INSTAGRAM_DIRECT',l:'Instagram 私信'},
]
// 转化目标（按 objective 联动）—— FB custom_event_type 枚举
const CONV_GOAL_LABELS = {
  Purchase:'购买', AddToCart:'加入购物车', InitiateCheckout:'发起结账', AddPaymentInfo:'填写支付信息',
  CompleteRegistration:'完成注册', Lead:'潜在客户', Subscribe:'订阅', Contact:'联系',
  StartTrial:'开始试用', Search:'搜索', APP_INSTALLS:'应用安装', LEVEL_ACHIEVED:'达成关卡',
  ACHIEVEMENT_UNLOCKED:'解锁成就', SPENT_CREDITS:'消费积分',
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
    {v:'feed',l:'动态消息'},{v:'video_feeds',l:'视频动态'},{v:'instream_video',l:'视频插播'},
    {v:'story',l:'快拍'},{v:'reels',l:'Reels'},{v:'marketplace',l:'市场'},
    {v:'right_hand_column',l:'右侧栏'},{v:'search',l:'搜索结果'},
  ]},
  { v: 'instagram', l: 'Instagram', positions: [
    {v:'stream',l:'动态'},{v:'story',l:'快拍'},{v:'explore',l:'探索'},
    {v:'reels',l:'Reels'},{v:'profile',l:'个人主页'},
  ]},
  { v: 'messenger', l: 'Messenger', positions: [
    {v:'messenger_home',l:'首页'},{v:'story',l:'快拍'},{v:'sponsored_messages',l:'推广消息'},
  ]},
  { v: 'audience_network', l: 'Audience Network', positions: [
    {v:'classic',l:'横幅/插屏'},{v:'instream_video',l:'视频插播'},{v:'rewarded_video',l:'激励视频'},
  ]},
]
const DEVICES = [{v:'desktop',l:'桌面'}, {v:'mobile',l:'移动'}]
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
  { v: 'LOWEST_COST_WITHOUT_CAP', l: '最低成本（无上限）' },
  { v: 'LOWEST_COST_WITH_BID_CAP', l: '最低成本（出价上限）' },
  { v: 'COST_CAP', l: '成本上限' },
]
const CTAS = [
  { v: 'SHOP_NOW', l: '立即购买' },{ v: 'SIGN_UP', l: '注册' },{ v: 'SUBSCRIBE', l: '订阅' },
  { v: 'LEARN_MORE', l: '了解详情' },{ v: 'DOWNLOAD', l: '下载' },{ v: 'CONTACT_US', l: '联系我们' },
  { v: 'GET_QUOTE', l: '获取报价' },{ v: 'BOOK_NOW', l: '立即预约' },{ v: 'ORDER_NOW', l: '立即下单' },
  { v: 'CALL_NOW', l: '立即致电' },{ v: 'MESSAGE_PAGE', l: '发消息' },{ v: 'WATCH_MORE', l: '观看更多' },
  { v: 'ADD_TO_CART', l: '加入购物车' },{ v: 'BUY_TICKETS', l: '购票' },
]
const SPECIAL_CATS = [
  { v: '', l: '无' },{ v: 'HOUSING', l: '住房' },{ v: 'EMPLOYMENT', l: '就业' },
  { v: 'CREDIT', l: '信贷' },{ v: 'ISSUES_ELECTIONS_POLITICS', l: '政治/选举' },
]
const COUNTRIES = [
  {v:'US',l:'美国'},{v:'VN',l:'越南'},{v:'TH',l:'泰国'},{v:'ID',l:'印尼'},{v:'PH',l:'菲律宾'},
  {v:'MY',l:'马来西亚'},{v:'TW',l:'台湾'},{v:'HK',l:'香港'},{v:'SG',l:'新加坡'},{v:'CN',l:'中国大陆'},
  {v:'BR',l:'巴西'},{v:'MX',l:'墨西哥'},{v:'IN',l:'印度'},{v:'JP',l:'日本'},{v:'KR',l:'韩国'},
  {v:'GB',l:'英国'},{v:'DE',l:'德国'},{v:'FR',l:'法国'},{v:'AE',l:'阿联酋'},{v:'SA',l:'沙特'},
  {v:'EG',l:'埃及'},{v:'KW',l:'科威特'},{v:'QA',l:'卡塔尔'},{v:'TR',l:'土耳其'},{v:'ES',l:'西班牙'},
  {v:'IT',l:'意大利'},{v:'CA',l:'加拿大'},{v:'AU',l:'澳洲'},{v:'NZ',l:'新西兰'},{v:'CL',l:'智利'},
  {v:'CO',l:'哥伦比亚'},{v:'PE',l:'秘鲁'},{v:'AR',l:'阿根廷'},{v:'ZA',l:'南非'},{v:'NG',l:'尼日利亚'},
  {v:'KE',l:'肯尼亚'},{v:'BD',l:'孟加拉'},{v:'PK',l:'巴基斯坦'},{v:'PL',l:'波兰'},{v:'NL',l:'荷兰'},
  {v:'BE',l:'比利时'},{v:'CH',l:'瑞士'},{v:'AT',l:'奥地利'},{v:'SE',l:'瑞典'},{v:'NO',l:'挪威'},
  {v:'DK',l:'丹麦'},{v:'FI',l:'芬兰'},{v:'PT',l:'葡萄牙'},{v:'GR',l:'希腊'},{v:'CZ',l:'捷克'},
  {v:'RO',l:'罗马尼亚'},{v:'HU',l:'匈牙利'},{v:'IL',l:'以色列'},{v:'IE',l:'爱尔兰'},{v:'RU',l:'俄罗斯'},
  {v:'UA',l:'乌克兰'},{v:'BY',l:'白俄罗斯'},{v:'KZ',l:'哈萨克斯坦'},{v:'UZ',l:'乌兹别克斯坦'},
  {v:'GH',l:'加纳'},{v:'TZ',l:'坦桑尼亚'},{v:'UG',l:'乌干达'},{v:'ET',l:'埃塞俄比亚'},{v:'MA',l:'摩洛哥'},
  {v:'DZ',l:'阿尔及利亚'},{v:'TN',l:'突尼斯'},{v:'IQ',l:'伊拉克'},{v:'JO',l:'约旦'},{v:'LB',l:'黎巴嫩'},
  {v:'BH',l:'巴林'},{v:'OM',l:'阿曼'},{v:'PS',l:'巴勒斯坦'},{v:'LK',l:'斯里兰卡'},{v:'NP',l:'尼泊尔'},
  {v:'MM',l:'缅甸'},{v:'KH',l:'柬埔寨'},{v:'LA',l:'老挝'},{v:'BN',l:'文莱'},{v:'MO',l:'澳门'},
  {v:'PY',l:'巴拉圭'},{v:'UY',l:'乌拉圭'},{v:'BO',l:'玻利维亚'},{v:'VE',l:'委内瑞拉'},{v:'EC',l:'厄瓜多尔'},
  {v:'PA',l:'巴拿马'},{v:'GT',l:'危地马拉'},{v:'DO',l:'多米尼加'},{v:'CR',l:'哥斯达黎加'},{v:'SV',l:'萨尔瓦多'},
  {v:'HN',l:'洪都拉斯'},{v:'JM',l:'牙买加'},{v:'TT',l:'特立尼达和多巴哥'},{v:'PR',l:'波多黎各'},
  {v:'IS',l:'冰岛'},{v:'LU',l:'卢森堡'},{v:'MT',l:'马耳他'},{v:'CY',l:'塞浦路斯'},{v:'HR',l:'克罗地亚'},
  {v:'SK',l:'斯洛伐克'},{v:'SI',l:'斯洛文尼亚'},{v:'BG',l:'保加利亚'},{v:'RS',l:'塞尔维亚'},{v:'LT',l:'立陶宛'},
  {v:'LV',l:'拉脱维亚'},{v:'EE',l:'爱沙尼亚'},{v:'AL',l:'阿尔巴尼亚'},{v:'BA',l:'波黑'},{v:'MD',l:'摩尔多瓦'},
]
const LANGS = [
  { v: '', l: '不限' },{ v: '24', l: '英语（美国）' },{ v: '6', l: '英语（英国）' },{ v: '37', l: '英语（所有）' },
  { v: '5', l: '中文（简体）' },{ v: '2', l: '中文（繁体）' },{ v: '1', l: '中文（所有）' },
  { v: '31', l: '越南语' },{ v: '34', l: '泰语' },{ v: '32', l: '印尼语' },{ v: '27', l: '日语' },
  { v: '28', l: '韩语' },{ v: '12', l: '西班牙语' },{ v: '14', l: '葡萄牙语' },{ v: '15', l: '阿拉伯语' },
]

const load = async () => {
  loading.value = true
  try { list.value = await GET('/launch-templates') } catch (e) { showError(e, '加载失败') }
  loading.value = false
}
const loadLandingPages = async () => { try { landingPages.value = await GET('/landing/pages') } catch {} }
onMounted(() => { load(); loadLandingPages(); loadFormMsgTemplates() })
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })

// #2 dirty-check：编辑抽屉关闭前确认
let _formSnapshot = ''
const snapshotForm = () => { _formSnapshot = JSON.stringify(form.value) }
const isDirty = computed(() => _formSnapshot && JSON.stringify(form.value) !== _formSnapshot)
const onEditBeforeClose = (done) => {
  if (isDirty.value) {
    ElMessageBox.confirm('有未保存的修改，确认丢弃？', '关闭确认', { type: 'warning', confirmButtonText: '丢弃', cancelButtonText: '继续编辑' })
      .then(() => done()).catch(() => {})
  } else { done() }
}

// #1 保存前校验
const validationErrors = ref([])
const validateTemplate = () => {
  const errs = []
  if (!form.value.name?.trim()) errs.push('模板名')
  if (!form.value.asset_id) errs.push('素材（广告 Tab）')
  if (!form.value.budget_usd || Number(form.value.budget_usd) <= 0) errs.push('每日预算')
  if (!form.value.landing_url && !form.value.landing_page_id && !['OUTCOME_AWARENESS'].includes(form.value.objective))
    errs.push('落地页（选已有或填URL）')
  return errs
}
// 完整性状态（UI 显示用）
const completionStatus = computed(() => {
  const errs = validateTemplate()
  if (!errs.length) return { ready: true, label: '就绪', missing: [] }
  return { ready: false, label: '待完善', missing: errs }
})

// #5 部署历史
const historyOpen = ref(false)
const jobs = ref([])
const loadJobs = async () => { try { jobs.value = await GET('/launch-templates/jobs?limit=20') } catch {} }
const openHistory = async () => { historyOpen.value = true; await loadJobs() }
const openJob = async (jobId) => { historyOpen.value = false; openProgress(jobId) }

// #3 预检结构化展示
const preflightResult = ref(null)
const preflightVisible = ref(false)
// #4 per-account page/pixel loading
const accLoadingConfig = ref(new Set())
// 表单/消息模板
const formTemplates = ref([])
const msgTemplates = ref([])
const selectedFormTpl = ref(null)
const selectedMsgTpl = ref(null)
const formPreviewOpen = ref(false)
const msgPreviewOpen = ref(false)
const loadFormMsgTemplates = async () => {
  try { formTemplates.value = await GET('/form-templates/forms') } catch {}
  try { msgTemplates.value = await GET('/form-templates/messages') } catch {}
}
const onFormTplChange = (id) => {
  if (!id) { selectedFormTpl.value = null; form.value.lead_form_id = ''; return }
  const t = formTemplates.value.find(f => f.id === id)
  selectedFormTpl.value = t || null
  form.value.lead_form_id = t?.fb_form_id || ''  // 有fb_form_id的直接用，没有的部署时建
}
const onMsgTplChange = (id) => {
  if (!id) { selectedMsgTpl.value = null; form.value.message_template = ''; return }
  const t = msgTemplates.value.find(m => m.id === id)
  selectedMsgTpl.value = t || null
  // 存成 JSON（parse_message_template 兼容 JSON 串/纯文本/dict）
  form.value.message_template = t ? JSON.stringify({ text: t.welcome_text, ice_breakers: t.ice_breakers||[] }) : ''
}

const blankForm = () => ({
  name: '', description: '',
  // 系列 Campaign
  objective: 'OUTCOME_TRAFFIC', conversion_goal: '', budget_mode: 'ABO',
  bid_strategy: 'LOWEST_COST_WITHOUT_CAP', budget_usd: 5, name_prefix: 'Tova Ads',
  special_ad_category: '',
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
})
const objLabel = (v) => OBJECTIVES.find(o => o.v === v)?.l || v
// 卡片完整性判断（列表用，不需打开编辑器）
const _tplMissing = (t) => {
  const m = []
  if (!t.name?.trim()) m.push('模板名')
  if (!t.asset_id) m.push('素材')
  if (!t.budget_usd || t.budget_usd <= 0) m.push('预算')
  if (!t.landing_url && !['OUTCOME_AWARENESS'].includes(t.objective)) m.push('落地页')
  return m
}
const _tplReady = (t) => _tplMissing(t).length === 0
const fmtUsd = (v) => v != null ? '$' + Number(v).toFixed(2) : '—'

// 编辑
const openNew = () => { editing.value = null; form.value = blankForm(); editingAsset.value = null; editLevel.value = 'campaign'; validationErrors.value = []; editOpen.value = true; snapshotForm() }
const openEdit = async (t) => {
  editing.value = t
  const f = blankForm()
  Object.assign(f, t)
  if (t.audience_json) { try { const a = JSON.parse(t.audience_json); f.audience_countries = a.countries||[]; f.audience_interests = a.interests||[]; f.audience_age_min = a.age_min||18; f.audience_age_max = a.age_max||65; f.audience_gender = a.gender||0; f.audience_language = a.languages ? (Array.isArray(a.languages)?a.languages[0]||'':'') : '' } catch {} }
  // 从 advanced_config 恢复 Advantage+ / 版位 / 频次 / CPA（P0-3/P0-4 fix）
  if (t.advanced_config) {
    try {
      const adv = JSON.parse(t.advanced_config)
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
    } catch {}
  }
  // Advantage+ 受众默认值：有手动兴趣 → 关（保留用户的手动定向）；无 → 开
  advantage_audience.value = (f.audience_interests || []).length === 0
  // 恢复表单/消息模板选中状态（P0-2 fix）
  if (f.lead_form_template_id) { try { selectedFormTpl.value = formTemplates.value.find(x => x.id === f.lead_form_template_id) || null } catch {} }
  if (f.message_template_id) { try { selectedMsgTpl.value = msgTemplates.value.find(x => x.id === f.message_template_id) || null } catch {} }
  form.value = f
  editingAsset.value = null
  if (t.asset_id) { try { editingAsset.value = await GET('/assets/' + t.asset_id) } catch {} }
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
  catch (e) { showError(e, '兴趣搜索失败') }
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
  if (!editingAsset.value?.ai_audience?.interests?.length) return ElMessage.warning('该素材无 AI 兴趣词')
  let added = 0
  for (const kw of editingAsset.value.ai_audience.interests) {
    try {
      const r = await GET('/audiences/search?q=' + encodeURIComponent(kw) + '&limit=1')
      if (r[0]) { if (!form.value.audience_interests.find(x => x.id === String(r[0].id))) { form.value.audience_interests.push({ id: String(r[0].id), name: r[0].name }); added++ } }
    } catch {}
  }
  ElMessage.success(`从 AI 导入 ${added} 个兴趣`)
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
    return ElMessage.warning('待完善：缺 ' + validationErrors.value.join('、'))
  }
  saving.value = true
  try {
    const body = {
      name: form.value.name, description: form.value.description,
      objective: form.value.objective, conversion_goal: form.value.conversion_goal,
      budget_mode: form.value.budget_mode, bid_strategy: form.value.bid_strategy,
      budget_usd: Number(form.value.budget_usd), name_prefix: form.value.name_prefix,
      optimization_goal: form.value.optimization_goal, billing_event: form.value.billing_event,
      destination_type: form.value.destination_type, audience_id: form.value.audience_id,
      audience_json: buildAudienceJson(), advanced_config: form.value.advanced_config,
      asset_id: form.value.asset_id, headline: form.value.headline, body: form.value.body,
      page_id: form.value.page_id, pixel_id: form.value.pixel_id,
      landing_url: form.value.landing_url, cta_type: form.value.cta_type,
      subcode_slug: form.value.subcode_slug, ad_language: form.value.ad_language,
      message_template: form.value.message_template, lead_form_id: form.value.lead_form_id,
      beneficiary: form.value.beneficiary, payer: form.value.payer,
    }
    // Advantage+ 设置 + 性能目标 + 版位 + 频次 合并进 advanced_config
    try {
      let adv = {}
      if (body.advanced_config) {
        try { adv = JSON.parse(body.advanced_config) }
        catch { ElMessage.warning('高级设置 JSON 格式错误，已忽略'); adv = {} }
      }
      // 性能目标 CPA（COST_CAP 时生效）
      if (performance_goal_cpa.value > 0) {
        body.bid_strategy = 'COST_CAP'
        adv.bid_amount = Math.round(performance_goal_cpa.value * 100) // 美元→分
      }
      // Advantage+ 受众（FB 默认开；关时用手动定向，不加 extra）
      // Advantage+ 创意（FB 默认开；传入 is_dynamic_creative 标志）
      if (advantage_creative.value) {
        adv.is_dynamic_creative = true
      }
      // 版位
      if (form.value.manual_placement) {
        adv.targeting = adv.targeting || {}
        const plats = form.value.placement_platforms || []
        if (plats.length) adv.targeting.publisher_platforms = plats
        if ((form.value.placement_devices||[]).length) adv.targeting.device_platforms = form.value.placement_devices
        for (const p of PLATFORMS) {
          const positions = form.value[p.v + '_positions']
          if (positions && positions.length) adv.targeting[p.v + '_positions'] = positions
        }
      }
      // 频次控制
      if (form.value.frequency_cap && form.value.frequency_cap > 0) {
        adv.frequency_control_specs = [{
          event: 'IMPRESSIONS', interval_days: 1, max_frequency: form.value.frequency_cap, type: 'CAP'
        }]
      }
      body.advanced_config = Object.keys(adv).length ? JSON.stringify(adv) : ''
    } catch {}
    if (editing.value) { await PUT('/launch-templates/' + editing.value.id, body); ElMessage.success('已保存') }
    else { await POST('/launch-templates', body); ElMessage.success('已创建') }
    editOpen.value = false; await load(); snapshotForm()
  } catch (e) { showError(e, '保存模板失败') }
  saving.value = false
}
const removeTpl = async (t) => {
  try { await ElMessageBox.confirm(`归档模板「${t.name}」？`, '确认', { type: 'warning' }); await DELETE('/launch-templates/' + t.id); ElMessage.success('已归档'); await load() }
  catch (e) { if (e === 'cancel') return }
}
// 预检
const preflighting = ref(false)
const preflight = async (t) => {
  preflighting.value = true
  try {
    const r = await POST('/launch-templates/' + t.id + '/preflight', { act_id: accounts.value[0]?.act_id || '' })
    preflightResult.value = r; preflightVisible.value = true
  } catch (e) { showError(e, '预检失败') }
  preflighting.value = false
}
// 部署
const openDeploy = async (t) => {
  deployTpl.value = t; deployOpen.value = true; selectedAccs.value = new Set(); deployItems.value = {}
  accLoading.value = true
  try { accounts.value = await GET('/fb/accounts') } catch (e) { showError(e, '加载账户失败') }
  accLoading.value = false
}
const toggleAcc = async (id) => {
  const s = new Set(selectedAccs.value); s.has(id) ? s.delete(id) : s.add(id); selectedAccs.value = s
  if (s.has(id) && !accPages.value[id]) {
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
}
const startDeploy = async () => {
  if (!selectedAccs.value.size) return ElMessage.warning('先选账户')
  const items = [...selectedAccs.value].map(id => ({ act_id: id, page_id: deployItems.value[id]?.page_id || '', pixel_id: deployItems.value[id]?.pixel_id || '' }))
  deploying.value = true
  try {
    const r = await POST('/launch-templates/' + deployTpl.value.id + '/deploy', { items })
    deployOpen.value = false; ElMessage.success(`已提交：${r.total} 个账户`); openProgress(r.job_id); await load()
  } catch (e) { showError(e, '部署提交失败') }
  deploying.value = false
}
// 进度
const openProgress = async (jobId) => {
  progressOpen.value = true; activeJob.value = null
  await pollJob(jobId)
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(() => pollJob(jobId), 2500)
}
const pollJob = async (jobId) => {
  try {
    activeJob.value = await GET('/launch-templates/jobs/' + jobId)
    if (['completed','partial_failed','failed'].includes(activeJob.value.status)) { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } }
  } catch {}
}
const retryItem = async (it) => {
  try { await POST(`/launch-templates/jobs/${activeJob.value.id}/retry/${it.id}`, {}); ElMessage.success('已提交重试')
    if (!pollTimer) pollTimer = setInterval(() => pollJob(activeJob.value.id), 2500) } catch (e) { showError(e, '重试失败') }
}
const statusText = (s) => ({ success:'✓ 成功', fail:'✗ 失败', creating:'创建中', pending:'等待' }[s] || s)
const statusColor = (s) => s === 'success' ? 'var(--success)' : s === 'fail' ? 'var(--error)' : s === 'creating' ? 'var(--ac)' : 'var(--t3)'
const fbAdsUrl = (actId, campId) => `https://www.facebook.com/adsmanager/manage/campaigns?act=${actId}&selected_campaign_ids=${campId}`
</script>

<template>
  <div class="page">
    <div class="bar">
      <div class="t">投放模板</div>
      <div style="display:flex;gap:8px">
        <button class="btn" @click="openHistory">部署历史</button>
        <button class="btn primary" @click="openNew">+ 新建模板</button>
      </div>
    </div>
    <div class="d">选模板 + 选账户 → 一键批量部署到多账户。</div>

    <div class="grid" v-loading="loading">
      <div v-for="t in list" :key="t.id" class="card">
        <div class="card-head">
          <span class="card-name">{{ t.name }}</span>
          <span :class="['card-badge', _tplReady(t) ? 'ready' : 'pending']" :title="_tplMissing(t).join('、')">
            {{ _tplReady(t) ? '✓ 就绪' : '待完善' }}
          </span>
        </div>
        <div class="card-meta"><span class="card-obj">{{ objLabel(t.objective) }}</span><span>{{ fmtUsd(t.budget_usd) }}/天</span></div>
        <div v-if="!_tplReady(t)" class="card-warn">缺：{{ _tplMissing(t).join('、') }}</div>
        <div class="card-ops">
          <button class="op primary" @click="openDeploy(t)">部署</button>
          <button class="op" @click="openEdit(t)">编辑</button>
          <button class="op danger" @click="removeTpl(t)">归档</button>
        </div>
      </div>
      <div v-if="!list.length && !loading" class="empty">暂无模板，点「+ 新建模板」。</div>
    </div>

    <!-- 编辑抽屉：系列/组/广告 三级 -->
    <el-drawer v-model="editOpen" :title="editing ? '编辑模板' : '新建模板'" direction="rtl" size="680px" :destroy-on-close="true" :before-close="onEditBeforeClose">
      <div class="level-tabs">
        <button :class="['ltab',{on:editLevel==='campaign'}]" @click="editLevel='campaign'">① 系列 Campaign</button>
        <button :class="['ltab',{on:editLevel==='adset'}]" @click="editLevel='adset'">② 广告组 Ad Set</button>
        <button :class="['ltab',{on:editLevel==='ad'}]" @click="editLevel='ad'">③ 广告 Ad</button>
      </div>
      <!-- #8 summary strip：跨级概览 -->
      <div class="summary-strip">
        <span class="ss-chip" @click="editLevel='campaign'" title="点击跳到系列">目标：{{ OBJECTIVES.find(o=>o.v===form.objective)?.l || form.objective }}</span>
        <span class="ss-chip" @click="editLevel='adset'" title="点击跳到广告组">受众：{{ (form.audience_countries||[]).join(',') || '默认' }} · {{ (form.audience_interests||[]).length }}兴趣</span>
        <span class="ss-chip" @click="editLevel='ad'" title="点击跳到广告">素材：{{ editingAsset?.name || '未选' }}</span>
        <span :class="['ss-status', completionStatus.ready ? 'ready' : 'pending']" :title="completionStatus.missing.join('、')">
          {{ completionStatus.ready ? '✓ 就绪' : '待完善：' + completionStatus.missing.join('、') }}
        </span>
      </div>

      <!-- ① 系列 -->
      <div v-if="editLevel==='campaign'" class="form">
        <div class="row"><label>模板名</label><input v-model="form.name" class="inp" placeholder="如 US-shopping-夏季" /></div>
        <div class="row"><label>广告目标</label><el-select v-model="form.objective" style="width:100%" size="small"><el-option v-for="o in OBJECTIVES" :key="o.v" :value="o.v" :label="o.l" /></el-select></div>
        <div class="row" v-if="convGoalsForObjective.length"><label>转化目标</label>
          <el-select v-model="form.conversion_goal" style="width:100%" size="small" filterable clearable placeholder="选择转化事件">
            <el-option v-for="g in convGoalsForObjective" :key="g" :value="g" :label="(CONV_GOAL_LABELS[g]||g) + ' (' + g + ')'" />
          </el-select>
        </div>
        <div class="row"><label>预算模式</label><div class="seg"><button :class="{on:form.budget_mode==='ABO'}" @click="form.budget_mode='ABO'">广告组预算</button><button :class="{on:form.budget_mode==='CBO'}" @click="form.budget_mode='CBO'">Advantage+ 系列预算</button></div>
          <span v-if="form.budget_mode==='CBO'" class="hint">FB AI 自动在各广告组间分配预算，最大化整体效果</span>
        </div>
        <div class="row"><label>每日预算（美元）</label><input v-model.number="form.budget_usd" type="number" min="1" step="0.5" class="inp" /><span class="hint">部署时按账户本币自动换算</span></div>
        <div class="row"><label>出价策略</label><el-select v-model="form.bid_strategy" style="width:100%" size="small"><el-option v-for="b in BID_STRATEGIES" :key="b.v" :value="b.v" :label="b.l" /></el-select></div>
        <div class="row"><label>特殊广告类别</label><el-select v-model="form.special_ad_category" style="width:100%" size="small"><el-option v-for="s in SPECIAL_CATS" :key="s.v" :value="s.v" :label="s.l" /></el-select></div>
        <div class="row"><label>广告命名前缀</label><input v-model="form.name_prefix" class="inp" /></div>
      </div>

      <!-- ② 广告组 -->
      <div v-if="editLevel==='adset'" class="form">
        <div class="row"><label>优化目标</label><el-select v-model="form.optimization_goal" style="width:100%" size="small" filterable><el-option value="" label="自动（按目标推）" /><el-option v-for="g in OPT_GOALS" :key="g.v" :value="g.v" :label="g.l" /></el-select></div>
        <div class="row"><label>计费事件</label><el-select v-model="form.billing_event" style="width:100%" size="small"><el-option v-for="b in BILLING_EVENTS" :key="b.v" :value="b.v" :label="b.l" /></el-select></div>
        <div class="row"><label>转化目的地</label><el-select v-model="form.destination_type" style="width:100%" size="small" filterable><el-option value="" label="自动" /><el-option v-for="d in DEST_TYPES" :key="d.v" :value="d.v" :label="d.l" /></el-select></div>
        <hr class="sep" />
        <div class="sec-title">性能目标（可选）</div>
        <div class="row"><label>每次结果成本目标（美元，0=不限）</label>
          <input v-model.number="performance_goal_cpa" type="number" min="0" step="0.5" class="inp" placeholder="如 5.0（留空=最低成本）" />
          <span class="hint">设了目标后出价策略自动切"成本上限"，FB 按此 CPA 优化</span>
        </div>
        <hr class="sep" />
        <div class="sec-title">受众定向</div>
        <!-- Advantage+ 受众开关（对齐 FB Ads Manager 默认行为） -->
        <div class="advantage-box">
          <div class="adv-row">
            <div class="adv-info">
              <span class="adv-title">Advantage+ 受众</span>
              <span class="adv-desc">开启后，FB AI 会根据你的素材和转化数据自动扩展兴趣受众。年龄/性别/语言仍可设置作为基础约束。</span>
            </div>
            <el-switch v-model="advantage_audience" active-color="#0a84ff" inactive-color="#3a3a5c" size="small" />
          </div>
        </div>
        <div class="row"><label>国家/地区</label>
          <el-select v-model="form.audience_countries" multiple filterable collapse-tags collapse-tags-tooltip
            placeholder="搜索选择国家/地区（可多选）" style="width:100%" size="small">
            <el-option v-for="c in COUNTRIES" :key="c.v" :value="c.v" :label="c.l + ' (' + c.v + ')'" />
          </el-select>
        </div>
        <div class="row"><label>年龄</label><div class="age-row"><input v-model.number="form.audience_age_min" type="number" min="13" max="65" class="inp sm" /> — <input v-model.number="form.audience_age_max" type="number" min="13" max="65" class="inp sm" /></div></div>
        <div class="row"><label>性别</label><div class="seg"><button :class="{on:form.audience_gender===0}" @click="form.audience_gender=0">全部</button><button :class="{on:form.audience_gender===1}" @click="form.audience_gender=1">男</button><button :class="{on:form.audience_gender===2}" @click="form.audience_gender=2">女</button></div></div>
        <div class="row"><label>语言（定向说此语言的人）</label>
          <el-select v-model="form.audience_language" filterable clearable placeholder="不限语言" style="width:100%" size="small">
            <el-option v-for="l in LANGS.filter(x=>x.v)" :key="l.v" :value="l.v" :label="l.l" />
          </el-select>
        </div>
        <template v-if="!advantage_audience">
        <div class="row"><label>兴趣关键词（FB adinterest 搜索）</label>
          <div class="interest-search">
            <input v-model="interestQ" class="inp" placeholder="如 Shopping / 美妆 / 投资" @keyup.enter="searchInterests" />
            <button class="btn sm" :disabled="interestSearching" @click="searchInterests">{{ interestSearching ? '…' : '搜索' }}</button>
            <button class="btn sm ghost" @click="importAiInterests" v-if="editingAsset?.ai_audience?.interests?.length">从素材AI导入</button>
          </div>
          <div v-if="interestSearching" class="search-results"><div class="search-loading">搜索中…</div></div>
          <div v-else-if="interestResults.length" class="search-results">
            <div class="search-results-head"><span>搜索结果（点击 + 添加，可连续选多个）</span><button class="clear-btn" @click="clearInterestSearch">清空 ✕</button></div>
            <div v-for="r in interestResults" :key="r.id" :class="['search-item', { added: isInterestAdded(r.id) }]" @click="!isInterestAdded(r.id) && addInterest(r)">
              <span>{{ r.name }}</span>
              <span class="sz">{{ fmtSize(r.audience_size_lower_bound || r.audience_size) }}</span>
              <span class="add" v-if="!isInterestAdded(r.id)">+</span>
              <span class="added-mark" v-else>✓</span>
            </div>
          </div>
        </div>
        <div class="row"><label>已选兴趣（{{ form.audience_interests.length }}）</label>
          <div class="interest-list">
            <span v-for="(it,i) in form.audience_interests" :key="it.id" class="interest-chip">{{ it.name }} <button @click="removeInterest(i)">✕</button></span>
            <span v-if="!form.audience_interests.length" class="hint">点上方搜索添加</span>
          </div>
        </div>
        </template>
        <hr class="sep" />
        <div class="sec-title">版位</div>
        <div class="row"><label>投放版位</label>
          <div class="seg">
            <button :class="{on:!form.manual_placement}" @click="form.manual_placement=false">Advantage+（自动推荐）</button>
            <button :class="{on:form.manual_placement}" @click="form.manual_placement=true">手动选择</button>
          </div>
        </div>
        <div v-if="form.manual_placement">
          <div class="row"><label>设备</label>
            <div class="placement-chips">
              <label v-for="d in DEVICES" :key="d.v" class="placement-chip" :class="{on:(form.placement_devices||[]).includes(d.v)}">
                <input type="checkbox" :checked="(form.placement_devices||[]).includes(d.v)" @change="toggleDevice(d.v)" /> {{ d.l }}
              </label>
            </div>
          </div>
          <div class="row"><label>平台和版位</label>
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
                    <input type="checkbox" :checked="isPosOn(p.v,pos.v)" @change="togglePos(p.v,pos.v)" /> {{ pos.l }}
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="sec-title">披露（部分国家强制）</div>
        <div class="row"><label>受益人 beneficiary</label><input v-model="form.beneficiary" class="inp" placeholder="EU/泰国/印度/巴西/台湾/澳洲/新加坡等必填" /></div>
        <div class="row"><label>付款人</label><input v-model="form.payer" class="inp" /></div>
        <hr class="sep" />
        <div class="sec-title">频次控制</div>
        <div class="row"><label>频次上限（次 / 天，0=不限）</label><input v-model.number="form.frequency_cap" type="number" min="0" class="inp" placeholder="0" /></div>
        <hr class="sep" />
        <div class="sec-title">高级（JSON，可选）</div>
        <div class="row"><label>高级设置</label><textarea v-model="form.advanced_config" class="inp ta" rows="3" placeholder='如 {"bid_amount":500}'></textarea><span class="hint">可选，进阶 FB API 字段（JSON），部署时合并</span></div>
      </div>

      <!-- ③ 广告 -->
      <div v-if="editLevel==='ad'" class="form">
        <div class="row"><label>素材</label>
          <div class="asset-pick">
            <div v-if="editingAsset" class="asset-chosen" @click="openPreview(editingAsset)" style="cursor:pointer">
              <img v-if="editingAsset.type==='image'" :src="editingAsset.public_url" class="asset-thumb" />
              <video v-else :src="editingAsset.public_url" class="asset-thumb" preload="metadata" />
              <span class="asset-name">{{ editingAsset.name }}（点击预览）</span>
            </div>
            <button class="btn sm" @click="openAssetPicker">{{ editingAsset ? '换' : '选择素材' }}</button>
          </div>
        </div>
        <!-- Advantage+ 创意（对齐 FB Ads Manager） -->
        <div class="advantage-box">
          <div class="adv-row">
            <div class="adv-info">
              <span class="adv-title">Advantage+ 创意</span>
              <span class="adv-desc">开启后，FB 将自动为你的素材生成文案变体、裁切比例、添加音乐，提升表现</span>
            </div>
            <el-switch v-model="advantage_creative" active-color="#0a84ff" inactive-color="#3a3a5c" size="small" />
          </div>
        </div>
        <div v-if="editingAsset && (editingAsset.ai_copy?.headlines||[]).length" class="ai-copy">
          <div class="ai-copy-t">AI 文案（点选填充）</div>
          <div v-for="(h,i) in (editingAsset.ai_copy?.headlines||[])" :key="'h'+i" class="ai-pick" @click="form.headline=h"><span class="ai-tag">标题{{i+1}}</span> {{ h }}</div>
          <div v-for="(b,i) in (editingAsset.ai_copy?.bodies||[])" :key="'b'+i" class="ai-pick" @click="form.body=b"><span class="ai-tag">正文{{i+1}}</span> {{ b }}</div>
        </div>
        <div class="row"><label>标题 headline</label><input v-model="form.headline" class="inp" /></div>
        <div class="row"><label>正文 body</label><textarea v-model="form.body" class="inp ta" rows="3"></textarea></div>
        <div class="row"><label>行动号召 CTA</label><el-select v-model="form.cta_type" style="width:100%" size="small" filterable><el-option v-for="c in CTAS" :key="c.v" :value="c.v" :label="c.l + '（' + c.v + '）'" /></el-select></div>
        <div class="hint" style="padding:6px 10px;background:var(--bg3);border-radius:6px">主页和像素在部署时按账户选择（不同账户的主页/像素不同）</div>
        <div class="row"><label>落地页</label>
          <select v-model="form.landing_page_id" class="inp" @change="form.landing_url = (landingPages.find(p=>p.id==form.landing_page_id)?.public_url || form.landing_url)">
            <option :value="null">手动填 URL</option>
            <option v-for="p in landingPages" :key="p.id" :value="p.id">{{ p.title }}（{{ p.public_url || '无URL' }}）</option>
          </select>
        </div>
        <div class="row"><label>落地页 URL</label><input v-model="form.landing_url" class="inp" placeholder="https://..." /></div>
        <div class="row"><label>子码 slug</label><input v-model="form.subcode_slug" class="inp" placeholder="留空=不绑子码" /></div>
        <!-- 消息类（ENGAGEMENT + 消息目标） -->
        <template v-if="form.objective === 'OUTCOME_ENGAGEMENT'">
          <hr class="sep" /><div class="sec-title-row"><span class="sec-title">消息广告</span>
            <router-link to="/form-templates" class="new-link">管理消息模板 →</router-link>
          </div>
          <div class="row"><label>Messenger 欢迎语模板</label>
            <el-select v-model="form.message_template_id" style="width:100%" size="small" filterable clearable placeholder="选消息模板（留空=不设）" @change="onMsgTplChange">
              <el-option v-for="m in msgTemplates" :key="m.id" :value="m.id" :label="m.name + ' · ' + (m.welcome_text||'').slice(0,20)" />
            </el-select>
          </div>
          <div v-if="selectedMsgTpl" class="tpl-preview-bar" @click="msgPreviewOpen = true">
            <span>{{ (selectedMsgTpl.welcome_text||'').slice(0,50) }}…</span>
            <span class="preview-link">预览</span>
          </div>
        </template>
        <!-- 表单类（LEADS + Instant Forms） -->
        <template v-if="form.objective === 'OUTCOME_LEADS'">
          <hr class="sep" /><div class="sec-title-row"><span class="sec-title">Instant Form</span>
            <router-link to="/form-templates" class="new-link">管理表单模板 →</router-link>
          </div>
          <div class="row"><label>表单模板</label>
            <el-select v-model="form.lead_form_template_id" style="width:100%" size="small" filterable clearable placeholder="选表单模板" @change="onFormTplChange">
              <el-option v-for="f in formTemplates" :key="f.id" :value="f.id" :label="f.name + (f.fb_form_id ? ' ✓' : '')" />
            </el-select>
          </div>
          <div v-if="selectedFormTpl" class="tpl-preview-bar" @click="formPreviewOpen = true">
            <span>{{ (selectedFormTpl.config||{}).form_title || selectedFormTpl.name }}</span>
            <span class="preview-link">预览</span>
          </div>
        </template>
        <div class="row"><label>广告语言</label>
          <el-select v-model="form.ad_language" filterable clearable placeholder="自动（按素材语言）" style="width:100%" size="small">
            <el-option v-for="l in LANGS.filter(x=>x.v)" :key="l.v" :value="l.v" :label="l.l" />
          </el-select>
        </div>
      </div>

      <template #footer>
        <button class="btn" @click="editOpen=false">取消</button>
        <button class="btn primary" :disabled="saving" @click="saveTpl">{{ saving ? '保存中…' : '保存' }}</button>
      </template>
    </el-drawer>

    <!-- 素材选择器 -->
    <el-drawer v-model="assetPickerOpen" title="选择素材" direction="rtl" size="560px" append-to-body>
      <div class="picker-grid" v-loading="pickerLoading">
        <div v-for="a in pickerAssets" :key="a.id" class="picker-card" @click="pickAsset(a)">
          <img v-if="a.type==='image'" :src="a.public_url" class="picker-thumb" />
          <video v-else :src="a.public_url" class="picker-thumb" preload="metadata" />
          <span class="picker-name">{{ a.name }}</span>
        </div>
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
    <el-drawer v-model="deployOpen" :title="`部署 · ${deployTpl?.name||''}`" direction="rtl" size="680px">
      <div class="d">勾选账户。每账户的主页/像素从下拉选（默认填模板值）。</div>
      <div class="deploy-search-row">
        <input v-model="deploySearch" class="inp" placeholder="搜索账户名/ID（模糊）" />
        <span class="acc-count-hint">{{ filteredDeployAccounts.length }} / {{ accounts.length }} 个账户</span>
      </div>
      <div class="acc-list" v-loading="accLoading">
        <div v-for="a in filteredDeployAccounts" :key="a.act_id" class="acc-block">
          <label class="acc-row" :class="{on:selectedAccs.has(a.act_id)}">
            <input type="checkbox" :checked="selectedAccs.has(a.act_id)" @change="toggleAcc(a.act_id)" />
            <span class="acc-name">{{ a.name || a.act_id }}</span>
            <span class="acc-id">{{ a.act_id }} · {{ a.currency }}</span>
            <span :class="['acc-status', a.account_status === 1 ? 'ok' : 'warn']" :title="a.account_status === 1 ? '正常' : '异常'">{{ a.account_status === 1 ? '正常' : '异常' }}</span>
          </label>
          <div v-if="selectedAccs.has(a.act_id)" class="acc-config">
            <template v-if="accLoadingConfig.has(a.act_id)">
              <span class="config-loading">加载主页/像素…</span>
            </template>
            <template v-else>
              <label>主页</label>
              <select v-model="deployItems[a.act_id].page_id" class="inp sm">
                <option value="">默认({{ deployTpl?.page_id || '无' }})</option>
                <option v-for="p in (accPages[a.act_id]||[])" :key="p.id" :value="p.id">{{ p.name }} ({{ p.id }})</option>
              </select>
              <label>像素</label>
              <select v-model="deployItems[a.act_id].pixel_id" class="inp sm">
                <option value="">默认({{ deployTpl?.pixel_id || '无' }})</option>
                <option v-for="p in (accPixels[a.act_id]||[])" :key="p.id" :value="p.id">{{ p.name }} ({{ p.id }})</option>
              </select>
            </template>
          </div>
        </div>
      </div>
      <template #footer>
        <span class="sel-count">已选 {{ selectedAccs.size }}</span>
        <button class="btn" @click="deployOpen=false">取消</button>
        <button class="btn primary" :disabled="deploying||!selectedAccs.size" @click="startDeploy">{{ deploying?'提交中…':'开始部署' }}</button>
      </template>
    </el-drawer>

    <!-- 进度 -->
    <el-dialog v-model="progressOpen" title="部署进度" width="720px" :close-on-click-modal="false" @close="if(pollTimer){clearInterval(pollTimer);pollTimer=null}">
      <div v-if="activeJob" class="prog">
        <div class="prog-head">
          <span>{{ activeJob.template_name }}</span>
          <span class="prog-stat">{{ activeJob.succeeded }}✓ / {{ activeJob.failed }}✗ / {{ activeJob.total }}</span>
          <span :class="['prog-status',activeJob.status]">{{ activeJob.status }}</span>
        </div>
        <div class="prog-items">
          <div v-for="it in activeJob.items" :key="it.id" class="prog-item">
            <span class="dot" :style="{background:statusColor(it.status)}"></span>
            <span class="pi-act">{{ it.act_id }}</span>
            <span :class="['pi-status',it.status]">{{ statusText(it.status) }}</span>
            <a v-if="it.campaign_id" :href="fbAdsUrl(it.act_id,it.campaign_id)" target="_blank" class="pi-link">FB广告→</a>
            <span v-if="it.error" class="pi-err" :title="it.error">{{ it.error.slice(0,50) }}</span>
            <button v-if="it.status==='fail'" class="op primary sm" @click="retryItem(it)">重试</button>
          </div>
        </div>
      </div>
    </el-dialog>
    <!-- 预检结果（结构化展示） -->
    <el-dialog v-model="preflightVisible" title="预检 · 即将发给 FB 的参数" width="700px" append-to-body>
      <div v-if="preflightResult" class="preflight">
        <div class="pf-summary">
          <span>账户币种：<b>{{ preflightResult.currency }}</b></span>
          <span>预算：$${{ preflightResult.budget_usd }} → <b>{{ preflightResult.daily_budget_fb }}</b>（本币最小单位）</span>
          <span>汇率：{{ preflightResult.fx_rate || '无' }}</span>
          <span>模式：{{ preflightResult.budget_mode }}</span>
        </div>
        <div class="pf-section">
          <div class="pf-title">系列 Campaign</div>
          <div class="pf-fields"><div v-for="(v,k) in preflightResult.campaign" :key="k" class="pf-field"><span class="pf-k">{{ k }}</span><span class="pf-v">{{ JSON.stringify(v) }}</span></div></div>
        </div>
        <div class="pf-section">
          <div class="pf-title">广告组 Ad Set</div>
          <div class="pf-fields"><div v-for="(v,k) in preflightResult.adset" :key="k" class="pf-field"><span class="pf-k">{{ k }}</span><span class="pf-v">{{ JSON.stringify(v) }}</span></div></div>
        </div>
        <div class="pf-section">
          <div class="pf-title">广告创意 Creative</div>
          <div class="pf-fields"><div v-for="(v,k) in preflightResult.creative" :key="k" class="pf-field"><span class="pf-k">{{ k }}</span><span class="pf-v">{{ JSON.stringify(v) }}</span></div></div>
        </div>
        <div v-if="preflightResult.notes" class="pf-notes">
          <div v-for="n in preflightResult.notes" :key="n" class="pf-note">· {{ n }}</div>
        </div>
      </div>
    </el-dialog>

    <!-- 部署历史 -->
    <el-dialog v-model="historyOpen" title="部署历史" width="600px" append-to-body>
      <div class="history-list">
        <div v-for="j in jobs" :key="j.id" class="history-item" @click="openJob(j.id)">
          <div class="hi-main">
            <span class="hi-name">{{ j.template_name }}</span>
            <span :class="['hi-status', j.status]">{{ j.status }}</span>
          </div>
          <div class="hi-meta">{{ j.succeeded }}✓ / {{ j.failed }}✗ / {{ j.total }} · {{ (j.created_at||'').slice(0,16) }}</div>
        </div>
        <div v-if="!jobs.length" class="empty-sm">暂无部署记录</div>
      </div>
    </el-dialog>
    <!-- 表单预览 -->
    <el-dialog v-model="formPreviewOpen" title="表单预览" width="400px" append-to-body>
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
    <el-dialog v-model="msgPreviewOpen" title="消息预览" width="380px" append-to-body>
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

.acc-list{display:flex;flex-direction:column;gap:6px;margin-top:10px}
.acc-block{border:1px solid var(--bd);border-radius:8px;overflow:hidden}
.acc-row{display:flex;align-items:center;gap:8px;padding:8px 10px;cursor:pointer}
.acc-row.on{background:rgba(10,132,255,.08)}
.acc-name{font-size:13px;color:var(--t1);flex:1}
.acc-id{font-size:11px;color:var(--t3);font-family:monospace}
.acc-status{font-size:10px;padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap}
.acc-status.ok{color:var(--success);background:rgba(52,199,89,.13)}
.acc-status.warn{color:var(--warning);background:rgba(255,159,10,.13)}
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
