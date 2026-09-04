<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import Chart from 'chart.js/auto'
import { GET, POST, DELETE, downloadFile } from '../api'
import { useLatest } from '../composables/useLatest'
import { fmtTime, userTz } from '../composables/useTz'
import { DATE_PRESETS } from '../composables/useDateRange'
import { usePlatform, platformQuery } from '../composables/usePlatform'
import { useRouter } from 'vue-router'
import { isSuperadminSync } from '../router'
const isSuper = isSuperadminSync()
import Fuse from 'fuse.js'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import DatePresetBar from '../components/DatePresetBar.vue'
import TgManager from '../components/TgManager.vue'

const { t, locale } = useI18n()
const router = useRouter()
const loading = ref(true)
const _dashGuard = useLatest()
const refreshing = ref(false)
const datePreset = ref('today')
const data = ref({
  total_spend: 0, total_conversions: 0, total_cpa: 0, total_roas: 0,
  pause_count: 0, allowance_count: 0, total_balance: 0,
  total_impressions: 0, total_reach: 0, total_clicks: 0,
  accounts_count: 0, accounts: [], last_synced: null
})
const recentNotifs = ref([])
const trendData = ref({ labels: [], spend: [], conversions: [], cpa: [], granularity: 'day' })
const trendGran = ref('day')  // 颗粒度：5min / 30min / hour / day
const trendCanvas = ref(null)
// 主趋势图（全宽单图 + 指标切换）：后端趋势只有 spend/conversions/cpa 三条序列
const trendMetric = ref('spend')
const TREND_SERIES = computed(() => [
  { key: 'spend', label: t('dashboard.seriesSpend'), color: 'rgb(10,132,255)' },
  { key: 'conversions', label: t('dashboard.seriesConv'), color: 'rgb(48,209,88)' },
  { key: 'cpa', label: t('dashboard.seriesCpa'), color: 'rgb(245,158,11)' },
])
let _charts = []
const GRAN_OPTS = computed(() => [
  { value: '5min', label: t('dashboard.gran5min') },
  { value: '30min', label: t('dashboard.gran30min') },
  { value: 'hour', label: t('dashboard.gran1hour') },
  { value: 'day', label: t('dashboard.granByDay') },
])
// 按看板时间范围自动推荐颗粒度
const autoGran = () => {
  const p = showCustom.value ? 'custom' : datePreset.value
  if (p === 'today') return '5min'
  if (p === 'last_2d') return 'hour'
  return 'day'
}
const loadTrend = async () => {
  try {
    const q = showCustom.value
      ? `date_from=${customFrom.value}&date_to=${customTo.value}`
      : `date_preset=${datePreset.value}`
    const actQ = selectedActs.value.length ? `&act_ids=${selectedActs.value.map(encodeURIComponent).join(',')}` : ''
    const cq = conversionCategory.value !== 'all' ? `&conversion_category=${conversionCategory.value}` : ''   // KPI 卡收窄时趋势线同步
    trendData.value = await GET(`/dashboard/trend?${q}${platformQuery()}${actQ}${cq}&granularity=${trendGran.value}`)
  } catch { trendData.value = { labels: [], spend: [], conversions: [], cpa: [], granularity: trendGran.value } }
}
const renderTrendCharts = () => {
  _charts.forEach(c => c?.destroy())
  _charts = []
  const d = trendData.value
  if (!d.labels?.length) return
  const dark = document.documentElement.dataset.theme !== 'light'
  const gridColor = dark ? 'rgba(255,255,255,.05)' : 'rgba(0,0,0,.05)'
  const textColor = dark ? '#8e8e93' : '#6c6c70'
  const mk = (canvas, label, data, color) => {
    if (!canvas) return
    // X 轴标签：后端返 UTC ISO 时间戳 → 前端用 fmtTime 按用户显示时区转
    const fmtTrendLabel = (iso) => {
      if (!iso || iso === '?') return '?'
      const gran = d.granularity
      // 日粒度：后端返 YYYY-MM-DD，直接截 MM-DD
      if (gran === 'day') return iso.length >= 10 ? iso.slice(5, 10) : iso
      // tick 粒度：后端返 UTC ISO → 转用户时区，用 Date 方法格式化（避免 toLocaleString 不稳定）
      const dt = new Date(iso)
      if (isNaN(dt)) return iso
      // 按用户时区取各部分
      const parts = new Intl.DateTimeFormat(locale.value === 'en' ? 'en-US' : 'zh-CN', {
        timeZone: userTz.value, hour12: false,
        month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
      }).formatToParts(dt)
      const get = (tt) => parts.find(p => p.type === tt)?.value || ''
      const md = `${get('month')}-${get('day')}`
      const hm = `${get('hour')}:${get('minute')}`
      if (gran === 'hour') return `${md} ${get('hour')}:00`
      return hm  // 5min/30min → HH:MM
    }
    const labels = d.labels.map(fmtTrendLabel)
    _charts.push(new Chart(canvas, {
      type: 'line',
      data: { labels, datasets: [{ label, data, borderColor: color,
        backgroundColor: color.replace(')', ',.08)').replace('rgb', 'rgba'),
        fill: true, tension: 0.4, pointRadius: 3, borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: { y: { grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 } } },
                  x: { grid: { display: false }, ticks: { color: textColor, font: { size: 10 }, maxRotation: 45 } } },
        plugins: { legend: { display: false } } },
    }))
  }
  const s = TREND_SERIES.value.find(x => x.key === trendMetric.value)
  if (s) mk(trendCanvas.value, s.label, d[s.key] || [], s.color)
}
watch(trendData, () => nextTick(renderTrendCharts))
// 主题切换：图表初始化时读主题色，切主题后需重建才能更新网格/文字颜色
const _themeObserver = new MutationObserver(() => nextTick(renderTrendCharts))
_themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
watch(trendGran, () => loadTrend())
watch(trendMetric, () => nextTick(renderTrendCharts))   // 指标切换只重画图，不重拉数据
watch(datePreset, () => {
  const old = trendGran.value
  trendGran.value = autoGran()
  if (trendGran.value === old) loadTrend()  // 粒度没变也要重拉(日期变了)；粒度变则 trendGran watcher 触发
})

const conversionCategory = ref('all')  // ① 转化分类（全部/购物/私信/线索/互动/流量）
const selectedActs = ref([])  // ③ 账户多选（act_id 列表）
const mobileFilters = ref(false)  // 移动端：日期+筛选行折叠开关（桌面恒展开）
const mainTab = ref('data')     // 数据看板 / 落地页数据 两个 Tab（用户点名）
const { platform } = usePlatform()
// 分区范围 chip：平台≠all 时显示 "Facebook · N 账户"（后端已按平台过滤 accounts，直接取长度）
const scopeChip = computed(() => {
  if (platform.value === 'all') return ''
  const plat = platform.value === 'fb' ? 'Facebook' : 'TikTok'
  const _m = (data.value.accounts || []).filter(a => a.is_managed !== false).length
  return `${plat} · ${t('dashboard.scopeAccounts', { n: _m })}`
})
watch(platform, () => {
  // 平台切换：所选账户可能不属于新平台——先清再拉，防"选中但永不匹配"的空数据
  if (platform.value !== 'all' && selectedActs.value.length) {
    const n = selectedActs.value.length
    selectedActs.value = []
    ElMessage.info(t('dashboard.clearedActs', { n }))
  }
  loadDashboard()
  loadTrend()
})
const rangeQuery = () => {
  let q = (showCustom.value && customFrom.value && customTo.value)
    ? `date_from=${customFrom.value}&date_to=${customTo.value}`
    : `date_preset=${datePreset.value}`
  if (conversionCategory.value && conversionCategory.value !== 'all') q += `&conversion_category=${conversionCategory.value}`
  if (selectedActs.value.length) q += `&act_ids=${selectedActs.value.map(encodeURIComponent).join(',')}`
  q += platformQuery()   // fb/tt 才附加（all 不带参，请求与旧版一致）
  return q
}
const activeTokens = ref(0)
const totalTokens = ref(0)
const lastUpdated = ref('')
const fmtAgo = (iso) => {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60000) return t('dashboard.justNow')
  if (diff < 3600000) return t('dashboard.minutesAgo', { n: Math.floor(diff / 60000) })
  return t('dashboard.hoursAgo', { n: Math.floor(diff / 3600000) })
}
// 账户 error：后端返 code（uncovered/cross_tz），按 locale 映射显示；其余（FB 错误等）原样
const ERR_LABEL = { uncovered: 'dashboard.covUncovered', cross_tz: 'dashboard.covCrossTz' }
const mapErr = (e) => (e && ERR_LABEL[e]) ? t(ERR_LABEL[e]) : (e || '')
// 账户平台小标（fb/tt；已移除账户 platform=null 不标）
const platChip = (a) => (a && (a.platform === 'tt' || a.platform === 'fb')) ? a.platform : ''
// 按 act_id 反查平台（账户多选已选 tag 内渲染平台色 chip 用；#label slot 只拿得到 value）
const platChipOfAct = (actId) => platChip((data.value.accounts || []).find(a => a.act_id === actId))
const loadDashboard = async (fresh = false) => {
  const isLatest = _dashGuard.next()
  loading.value = true
  try {
    const [dash, notifs, creds] = await Promise.all([
      GET(`/dashboard?${rangeQuery()}${fresh ? '&fresh=true' : ''}`),
      GET(`/notifications?limit=50${platformQuery()}`).then(r => Array.isArray(r) ? r : (r?.items || [])).catch(() => []),
      GET('/fb/credentials').catch(() => []),
    ])
    if (!isLatest()) return   // 快速切日期/60s 自动刷新并发时旧响应后到——丢弃
    data.value = dash
    // 后端 is_managed → 前端 removed（is_managed=false = 已移除纳管）
    if (data.value.accounts) {
      data.value.accounts = data.value.accounts.map(a => ({ ...a, removed: a.is_managed === false }))
    }
    lastUpdated.value = new Date().toISOString()
    recentNotifs.value = notifs
    const allCreds = creds || []
    activeTokens.value = allCreds.filter(c => c.status === 'active').length
    totalTokens.value = allCreds.length
    fetchLanding()
  } catch (e) {
    if (isLatest()) import('element-plus').then(m => m.ElMessage.error(e.message))
  } finally {
    loading.value = false
  }
}
const refreshData = () => loadDashboard(false)  // 刷新：只读库（跳 30s 缓存），不走 FB
const appLoading = computed(() => loading.value || refreshing.value || landingLoading.value)

// ── 落地页数据（访问/通过/屏蔽/CPC，按子码聚合）──
const landing = ref({ totals: {}, rows: [], block_detail: {} })
// 屏蔽原因 → i18n key（对齐 worker evalProtection 的 check 名）
const BLOCK_REASON_KEY = {
  device_block: 'dashboard.brDeviceBlock', required_query: 'dashboard.brRequiredQuery', country_allow: 'dashboard.brCountryAllow',
  country_block: 'dashboard.brCountryBlock', ua_block: 'dashboard.brUaBlock', referer_block: 'dashboard.brRefererBlock',
  query_block: 'dashboard.brQueryBlock', datacenter_block: 'dashboard.brDatacenterBlock', frequency: 'dashboard.brFrequency', dedup: 'dashboard.brDedup',
  pass: 'dashboard.kpiPass',
}
// 国家码 → 国名（中央 useCountries registry）
import { countryLabel as _countryLabel } from '../composables/useCountries'
const blockReasonLabel = (k) => { const key = BLOCK_REASON_KEY[k]; return key ? t(key) : k }
const countryLabel = (k) => _countryLabel(k)
const landingSearch = ref('')
const landingFilter = ref('all')  // all / good / waste / watch
const landingLoading = ref(false)
const fetchLanding = async () => {
  landingLoading.value = true
  try {
    const _aq = selectedActs.value.length ? `&act_ids=${selectedActs.value.map(encodeURIComponent).join(',')}` : ''
    landing.value = await GET(`/dashboard/landing?${rangeQuery()}${_aq}`)   // 账户筛选与广告区同口径
  }
  catch (e) { /* 落地页加载失败不阻断主看板 */ }
  finally { landingLoading.value = false }
  loadLandingTrend()
}
// 落地页 KPI 卡（可点击展开子码明细，参照广告版 KPI）
const landingKpiExpanded = ref(null)
const landingCards = computed(() => {
  const tk = landing.value.totals || {}
  return [
    { label: t('dashboard.kpiVisits'), value: fmt(tk.visits), color: 'blue', mode: 'visits', clickable: true },
    { label: t('dashboard.kpiPass'), value: fmt(tk.clicks), color: 'green', mode: 'clicks', clickable: true },
    { label: t('dashboard.kpiBlocked'), value: fmt(tk.blocked), color: 'red', mode: 'blocked', clickable: (tk.blocked || 0) > 0 },
    { label: t('dashboard.kpiPassRate'), value: fmtPct(tk.pass_rate), color: 'gray', mode: 'pass_rate', clickable: true },
    { label: t('dashboard.kpiBlockRate'), value: fmtPct(tk.block_rate), color: 'orange', mode: 'block_rate', clickable: (tk.blocked || 0) > 0 },
    { label: t('dashboard.kpiSpend'), value: fmtUsd(tk.spend_usd), color: 'blue', mode: 'spend', clickable: true },
    { label: t('dashboard.kpiCpc'), value: tk.cpc ? '$'+tk.cpc : '—', color: 'gray', mode: 'cpc', clickable: true },
  ]
})
const toggleLandingKpi = (i) => {
  if (!landingCards.value[i]?.clickable) return
  landingKpiExpanded.value = landingKpiExpanded.value === i ? null : i
}
// 子码明细（按点击的指标排序，需关注在上）
const landingKpiDetail = computed(() => {
  if (landingKpiExpanded.value === null) return null
  const card = landingCards.value[landingKpiExpanded.value]
  if (!card?.clickable) return null
  const mode = card.mode
  let rows = [...(landing.value.rows || [])]
  if (mode === 'visits') rows.sort((a, b) => (b.visits || 0) - (a.visits || 0))           // 高在上
  else if (mode === 'clicks') rows.sort((a, b) => (a.clicks || 0) - (b.clicks || 0))       // 低在上（无通过关注）
  else if (mode === 'blocked') rows.sort((a, b) => (b.blocked || 0) - (a.blocked || 0))    // 高在上
  else if (mode === 'pass_rate') rows.sort((a, b) => (a.pass_rate || 0) - (b.pass_rate || 0)) // 低在上
  else if (mode === 'block_rate') rows.sort((a, b) => (b.block_rate || 0) - (a.block_rate || 0)) // 高在上
  else if (mode === 'spend') rows.sort((a, b) => (b.spend_usd || 0) - (a.spend_usd || 0))  // 高在上
  else if (mode === 'cpc') rows.sort((a, b) => (b.cpc || 0) - (a.cpc || 0))              // 高在上
  return { mode, title: card.label + ' · ' + t('dashboard.detailBySubcode'), rows }
})
const landingFuse = computed(() => new Fuse(landing.value.rows || [], {
  keys: ['slug', 'ad_id', 'domain'], threshold: 0.3, ignoreLocation: true,
}))
const filteredLanding = computed(() => {
  let rows = landing.value.rows || []
  if (landingFilter.value !== 'all') rows = rows.filter(r => r.state === landingFilter.value)
  if (landingSearch.value.trim()) {
    const want = new Set(landingFuse.value.search(landingSearch.value).map(r => r.item.slug + '|' + (r.item.ad_id || '')))
    rows = rows.filter(r => want.has(r.slug + '|' + (r.ad_id || '')))
  }
  // state 排序：空耗 > 观察 > 有效 > 无数据（需关注的在前），同 state 按 visits 降序
  const stateOrder = { waste: 0, watch: 1, good: 2, no_data: 3 }
  return [...rows].sort((a, b) => {
    const so = (stateOrder[a.state] ?? 9) - (stateOrder[b.state] ?? 9)
    return so !== 0 ? so : (b.visits || 0) - (a.visits || 0)
  })
})
const landingStateLabel = (s) => ({ good: t('dashboard.stateGood'), waste: t('dashboard.stateWaste'), watch: t('dashboard.stateWatch'), no_data: '—' }[s] || '—')
// ── KPI 本币/USD 切换（localStorage 持久，默认 USD）──
const spendUnit = ref(localStorage.getItem('dash_spend_unit') || 'usd')
watch(spendUnit, (v) => localStorage.setItem('dash_spend_unit', v))
const multiCurrency = computed(() => new Set((data.value.accounts || []).map(a => a.currency).filter(Boolean)).size > 1)
// 本币汇总：多币种直接相加（仅供粗略参考，hover 有提示）；USD 用后端换算值
const totalSpendNative = computed(() => (data.value.accounts || []).reduce((s, a) => s + (a.spend || 0), 0))
const kpiSpendDisplay = computed(() => spendUnit.value === 'usd'
  ? fmtUsd(data.value.total_spend)
  : fmt(totalSpendNative.value))
const barWidth = (count, arr) => {
  const mx = Math.max(...(arr || []).map(a => a.count), 1)
  return Math.max(4, (count / mx * 100)) + '%'
}

// ── 落地页趋势（单图 + 指标 chip 切换 访问/通过/屏蔽，GET /dashboard/landing-trend；与数据 Tab 趋势卡同语言）──
const landingTrend = ref({ labels: [], visits: [], clicks: [], blocked: [] })
const landingTrendMetric = ref('visits')
const LT_SERIES = computed(() => [
  { key: 'visits', label: t('dashboard.kpiVisits'), color: 'rgb(10,132,255)' },
  { key: 'clicks', label: t('dashboard.kpiPass'), color: 'rgb(48,209,88)' },
  { key: 'blocked', label: t('dashboard.kpiBlocked'), color: 'rgb(255,69,58)' },
])
const ltCanvas = ref(null)
let _ltCharts = []
const loadLandingTrend = async () => {
  try {
    let q = (showCustom.value && customFrom.value && customTo.value)
      ? `date_from=${customFrom.value}&date_to=${customTo.value}`
      : `date_preset=${datePreset.value}`
    landingTrend.value = await GET(`/dashboard/landing-trend?${q}`)   // 落地事件跨平台，不做 platform 过滤
  } catch { landingTrend.value = { labels: [], visits: [], clicks: [], blocked: [] } }
}
const renderLandingTrend = () => {
  _ltCharts.forEach(c => c?.destroy())
  _ltCharts = []
  const d = landingTrend.value
  if (!d.labels?.length) return
  const dark = document.documentElement.dataset.theme !== 'light'
  const gridColor = dark ? 'rgba(255,255,255,.05)' : 'rgba(0,0,0,.05)'
  const textColor = dark ? '#8e8e93' : '#6c6c70'
  const mk = (canvas, label, data, color) => {
    if (!canvas) return
    _ltCharts.push(new Chart(canvas, {
      type: 'line',
      data: { labels: d.labels.map(x => x.length >= 10 ? x.slice(5, 10) : x), datasets: [{ label, data, borderColor: color,
        backgroundColor: color.replace(')', ',.08)').replace('rgb', 'rgba'),
        fill: true, tension: 0.4, pointRadius: 3, borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: { y: { grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 } } },
                  x: { grid: { display: false }, ticks: { color: textColor, font: { size: 10 }, maxRotation: 45 } } },
        plugins: { legend: { display: false } } },
    }))
  }
  const s = LT_SERIES.value.find(x => x.key === landingTrendMetric.value)
  if (s) mk(ltCanvas.value, s.label, d[s.key] || [], s.color)
}
watch(landingTrend, () => nextTick(renderLandingTrend))
watch(landingTrendMetric, () => nextTick(renderLandingTrend))   // 指标切换只重画图，不重拉数据
const _ltThemeObserver = new MutationObserver(() => nextTick(renderLandingTrend))
_ltThemeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

// 格式化：数字走中央 useFormat.fmtNum；金额保留 0→'—'（"该范围内无消耗"提示语义，真零≠无数据场景不适用于消耗列）
import { fmtNum, fmtUsd as _fmtUsdRaw } from '../composables/useFormat'
const fmt = fmtNum
const fmtUsd = (n) => (n == null || n === 0) ? '—' : _fmtUsdRaw(n)
const fmtPct = (n) => n == null ? '—' : Number(n).toFixed(2) + '%'   // 0 是真信号（如通过率0%=全被屏蔽），只有 null 才是"无数据"
const fmtSpendDual = (native, usd, cur) => {
  if (native == null) return { native: '—', usd: '—' }
  if (cur === 'USD') return { native: fmtUsd(native), usd: '' }
  return { native: `${fmt(native)} ${cur}`, usd: `≈ ${fmtUsd(usd)}` }
}
// 计算列（CVR 前端派生）
const cvr = (acc) => acc.clicks > 0 ? (acc.conversions / acc.clicks * 100) : 0

// 任务卡
const expandedCard = ref(null)
const taskCards = computed(() => {
  const cards = []
  const accs = data.value.accounts
  const names = (arr) => arr.map(a => (a.name || '').slice(0, 15)).join(t('dashboard.nameSep'))
  // 令牌失效=最高优先级红卡（其覆盖账户全部失明：巡检/止损/看板都停——FBInsider 对标）
  const badTokens = data.value.token_alerts || []
  if (badTokens.length) cards.push({ kind: 'danger', icon: 'CircleCloseFilled', title: t('dashboard.taskTokenDead', { n: badTokens.length }), desc: t('dashboard.taskTokenDeadDesc', { names: badTokens.map(x => x.alias).join(t('dashboard.nameSep')) }), toTokens: true, detailAccounts: [], detailColumns: [] })
  const _limited = (a) => a.balance_kind === 'limited' && !a.removed  // 已移除账户不进充值提醒（不可操作）
  const critical = accs.filter(a => _limited(a) && a.balance <= 0)
  if (critical.length) cards.push({ kind: 'danger', icon: 'CircleCloseFilled', title: t('dashboard.taskRechargeCritical', { n: critical.length }), desc: t('dashboard.taskRechargeCriticalDesc', { names: names(critical) }), detailAccounts: critical, detailColumns: ['name', 'balance', 'amount_spent_usd', 'spend_cap_usd'] })
  const recharge = accs.filter(a => _limited(a) && a.balance > 0 && a.balance <= 100)
  if (recharge.length) cards.push({ kind: 'warn', icon: 'WarningFilled', title: t('dashboard.taskRechargeAdvice', { n: recharge.length }), desc: t('dashboard.taskRechargeAdviceDesc', { names: names(recharge) }), detailAccounts: recharge, detailColumns: ['name', 'balance', 'amount_spent_usd', 'spend_cap_usd'] })
  if (!critical.length && !recharge.length) {
    const low = accs.filter(a => _limited(a) && a.balance > 100 && a.balance <= 300)
    if (low.length) cards.push({ kind: 'info', icon: 'InfoFilled', title: t('dashboard.taskBalanceLow', { n: low.length }), desc: t('dashboard.taskBalanceLowDesc', { names: names(low) }), detailAccounts: low, detailColumns: ['name', 'balance', 'amount_spent_usd', 'spend_cap_usd'] })
  }
  // 真拉取异常（排除已分类的巡检未覆盖/跨时区/无数据）
  const fetchErrors = accs.filter(a => a.error && a.error !== 'uncovered' && a.error !== 'cross_tz' && a.error !== '无数据')
  if (fetchErrors.length) cards.push({ kind: 'danger', icon: 'CircleCloseFilled', title: t('dashboard.taskFetchError', { n: fetchErrors.length }), desc: t('dashboard.taskFetchErrorDesc', { names: names(fetchErrors), msg: fetchErrors[0]?.error || '' }), detailAccounts: fetchErrors, detailColumns: ['name', 'error'] })
  // 巡检未覆盖（同日但无快照，需关注：可能 token 失效/巡检漏/新账户未跑到）
  const uncovered = accs.filter(a => a.error && a.error === 'uncovered')
  if (uncovered.length) cards.push({ kind: 'warn', icon: 'WarningFilled', title: t('dashboard.taskUncovered', { n: uncovered.length }), desc: t('dashboard.taskUncoveredDesc'), detailAccounts: uncovered, detailColumns: ['name', 'error'] })
  const bleeding = accs.filter(a => !a.error && a.spend_usd > 5 && a.conversions === 0)
  if (bleeding.length) cards.push({ kind: 'warn', icon: 'TrendCharts', title: t('dashboard.taskBleeding', { n: bleeding.length }), desc: t('dashboard.taskBleedingDesc', { names: names(bleeding), spend: fmtUsd(bleeding.reduce((s, a) => s + a.spend_usd, 0)) }), detailAccounts: bleeding, detailColumns: ['name', 'spend_usd', 'conversions', 'act_id'] })
  if (!cards.length) cards.push({ kind: 'ok', icon: 'CircleCheckFilled', title: t('dashboard.taskClean'), desc: t('dashboard.taskCleanDesc'), detailAccounts: [], detailColumns: [] })
  return cards.slice(0, 8)
})
const toggleCard = (i) => {
  const card = taskCards.value[i]
  if (card.toTokens) { router.push('/tokens'); return }   // 令牌失效卡 → 直达令牌页处理
  if (!card.detailAccounts?.length) return
  // 切换展开面板时清空勾选——selectedIds 是各面板共享的，残留会让"复制选中"带出旧选择
  if (expandedCard.value !== i) selectedIds.value = new Set()
  expandedCard.value = expandedCard.value === i ? null : i
}
const columnLabel = (col) => ({
  name: t('dashboard.colAccount'),
  balance: t('dashboard.colAvailable'),
  amount_spent_usd: t('dashboard.colUsed'),
  spend_cap_usd: t('dashboard.colCap'),
  spend_usd: t('dashboard.colSpendUsd'),
  conversions: t('dashboard.colConversions'),
  error: t('dashboard.colError'),
}[col] || col)
// rule_type 英文 → i18n（自动止损明细 col2 中文化）
const RULE_TYPE_LABEL_KEY = {
  bleed_abs: 'dashboard.ruleBleedAbs', cpa_exceed: 'dashboard.ruleCpaExceed', click_no_conv: 'dashboard.ruleClickNoConv',
  low_ctr_no_conv: 'dashboard.ruleLowCtrNoConv', reach_no_conv: 'dashboard.ruleReachNoConv', trend_drop: 'dashboard.ruleTrendDrop',
  budget_burn_fast: 'dashboard.ruleBudgetBurnFast', consecutive_bad: 'dashboard.ruleConsecutiveBad',
}
const columnFmt = (col, acc) => {
  if (col === 'name') return acc.name
  if (col === 'balance') return fmtUsd(acc.balance)
  if (col === 'amount_spent_usd') return fmtUsd(acc.amount_spent_usd)
  if (col === 'spend_cap_usd') return fmtUsd(acc.spend_cap_usd)
  if (col === 'spend_usd') return fmtUsd(acc.spend_usd)
  if (col === 'conversions') return fmt(acc.conversions)
  if (col === 'error') return mapErr(acc.error)
  return acc[col]
}

// KPI/账户明细内搜索
const detailSearch = ref('')

// ── KPI 分层重排：4 核心大卡（点击=账户明细表切到该指标视角）+ 4 次要小卡 ──
const accountView = ref('spend')  // 账户明细表视角：spend/conv/cpa/roas/balance
const setAccountView = (mode) => {
  accountView.value = mode
  detailSearch.value = ''          // 切视角清空搜索（不同视角行集不同，残留会误过滤）
  selectedIds.value = new Set()    // 勾选是余额视角专用，残留会带出旧选择
}
// 核心卡迷你趋势线（SVG polyline，复用趋势接口序列；不足 2 点不画）
const sparkPoints = (arr) => {
  const a = (arr || []).filter(v => typeof v === 'number' && !isNaN(v))
  if (a.length < 2) return ''
  const w = 100, h = 26, pad = 3
  const min = Math.min(...a), max = Math.max(...a)
  const span = (max - min) || 1
  return a.map((v, i) => `${((i / (a.length - 1)) * w).toFixed(1)},${(h - pad - ((v - min) / span) * (h - pad * 2)).toFixed(1)}`).join(' ')
}
const coreCards = computed(() => [
  { label: t('dashboard.kpiTotalSpend'), value: kpiSpendDisplay.value, mode: 'spend', spark: sparkPoints(trendData.value.spend), unit: true, sub: spendUnit.value === 'native' && multiCurrency.value ? t('dashboard.multiCurHint') : (datePreset.value === 'today' ? t('dashboard.todayLiveHint') : '') },
  { label: t('dashboard.kpiTotalConv'), value: fmt(data.value.total_conversions), mode: 'conv', spark: sparkPoints(trendData.value.conversions) },
  { label: t('dashboard.kpiAvgCpa'), value: fmtUsd(data.value.total_cpa), mode: 'cpa', spark: sparkPoints(trendData.value.cpa) },
  { label: t('dashboard.kpiAvgRoas'), value: data.value.total_roas ? data.value.total_roas + '×' : '—', mode: 'roas', spark: '' },  // 趋势接口无 ROAS 序列，不画
])
const ctrDisplay = computed(() => data.value.total_impressions > 0 ? ((data.value.total_clicks / data.value.total_impressions) * 100).toFixed(2) + '%' : '—')
const rechargeAlertCount = computed(() => (data.value.accounts || []).filter(a => a.balance_kind === 'limited' && !a.removed && (a.balance || 0) <= 100).length)
const subCards = computed(() => [
  { label: t('dashboard.kpiImpressions'), value: fmt(data.value.total_impressions) },
  { label: t('dashboard.kpiClicks'), value: fmt(data.value.total_clicks) },
  { label: t('dashboard.kpiCtr'), value: ctrDisplay.value },
  { label: t('dashboard.kpiBalance'), value: fmtUsd(data.value.total_balance), mode: 'balance', alert: rechargeAlertCount.value },
])

// ── 守护概览 3 格（自动止损/今日放行/巡检覆盖；点击展开对应明细面板）──
const kpiMode = ref(null)  // pause / allowance / coverage
const coverageText = computed(() => { const m = (data.value.accounts || []).filter(a => a.is_managed !== false); return `${m.filter(a => !a.error || a.error === 'cross_tz').length}/${m.length}` })
const guardCells = computed(() => [
  { mode: 'pause', label: t('dashboard.kpiAutoPause'), value: fmt(data.value.pause_count), danger: data.value.pause_count > 0 },
  { mode: 'allowance', label: t('dashboard.kpiAllowance'), value: fmt(data.value.allowance_count) },
  { mode: 'coverage', label: t('dashboard.kpiCoverage'), value: coverageText.value, sub: t('dashboard.kpiCoverageSub', { active: activeTokens.value, stopped: totalTokens.value - activeTokens.value }) },
])
const toggleKpiMode = (mode) => {
  kpiMode.value = kpiMode.value === mode ? null : mode
  if (kpiMode.value !== null) { selectedIds.value = new Set(); detailSearch.value = '' }  // 勾选/搜索各面板共享，切换时清空
}

// ── 账户明细表（原 KPI accounts 明细分支常驻化，五视角）──
const VIEW_TABS = computed(() => [
  { mode: 'spend', label: t('dashboard.viewSpend') },
  { mode: 'conv', label: t('dashboard.viewConv') },
  { mode: 'cpa', label: t('dashboard.viewCpa') },
  { mode: 'roas', label: t('dashboard.viewRoas') },
  { mode: 'balance', label: t('dashboard.viewBalance') },
])
const accountsTable = computed(() => {
  const mode = accountView.value
  // balance 是账户属性不依赖快照（看全部）；性能视角只看无异常账户（error 账户去守护格看）
  let accs = mode === 'balance' ? [...(data.value.accounts || [])] : (data.value.accounts || []).filter(a => !a.error)
  if (mode === 'spend') accs.sort((a, b) => (b.spend_usd || 0) - (a.spend_usd || 0))
  else if (mode === 'conv') accs.sort((a, b) => (a.conversions || 0) - (b.conversions || 0))  // 低在上（无转化需关注）
  else if (mode === 'cpa') accs.sort((a, b) => (b.cpa || 0) - (a.cpa || 0))  // 高在上（成本高需关注）
  else if (mode === 'roas') accs.sort((a, b) => (a.roas || 0) - (b.roas || 0))  // 低在上（ROAS差需关注）
  else if (mode === 'balance') accs.sort((a, b) => {
    // unlimited/very_high_limit 排最后（不紧急）；limited 内 0 优先 → 低到高（越低越紧急）
    const aLim = a.balance_kind === 'limited', bLim = b.balance_kind === 'limited'
    if (aLim && !bLim) return -1
    if (bLim && !aLim) return 1
    const av = a.balance || 0, bv = b.balance || 0
    if (av <= 0 && bv > 0) return -1
    if (bv <= 0 && av > 0) return 1
    return av - bv
  })
  const cols = mode === 'balance'
    ? [{ key: 'name', label: t('dashboard.colAccount'), left: true }, { key: 'balance', label: t('dashboard.colAvailable'), fmt: (v, a) => a.balance_kind === 'limited' ? fmtUsd(v) : t('dashboard.unlimited') }, { key: 'amount_spent_usd', label: t('dashboard.colUsed'), fmt: fmtUsd }, { key: 'spend_cap_usd', label: t('dashboard.colCap'), fmt: fmtUsd }, { key: 'urgency', label: t('dashboard.colUrgency'), fmt: (v, a) => urgencyLabel(a) }]
    : [
        { key: 'name', label: t('dashboard.colAccount'), left: true, bold: mode === 'spend' },
        { key: 'spend_dual', label: t('dashboard.colSpend'), fmt: (v, a) => fmtSpendDual(a.spend, a.spend_usd, a.currency).native, bold: mode === 'spend' },
        { key: 'spend_usd', label: t('dashboard.colUsd'), fmt: fmtUsd, bold: mode === 'spend' },
        { key: 'conversions', label: t('dashboard.colConversions'), fmt: fmt, bold: mode === 'conv' },
        { key: 'cpa', label: t('dashboard.colCpa'), fmt: fmtUsd, bold: mode === 'cpa' },
        { key: 'roas', label: t('dashboard.colRoas'), fmt: (v) => v ? v + '×' : '—', bold: mode === 'roas' },
      ]
  return { mode, accs, cols }
})
const hasManagedAccs = computed(() => accountsTable.value.accs.some(a => !a.removed))
const showRemoved = ref(false)  // 明细表默认只显示纳管账户——当前在管表现是主场景，历史在 KPI 汇总已有
const filteredAccounts = computed(() => {
  let accs = accountsTable.value.accs
  // 已移除默认不显示（可开「含已移除」）；余额视图强制排除（不可操作）
  if (!showRemoved.value || accountsTable.value.mode === 'balance') accs = accs.filter(a => !a.removed)
  if (detailSearch.value.trim()) {
    // 搜索只做过滤、保持表的既有排序（消耗降序等）——
    // 曾直接用 fuse.search().map，结果按匹配相关度重排，把消耗排序打乱
    const fuseAcc = new Fuse(accs, { keys: ['name', 'act_id'], threshold: 0.3 })
    const hits = new Set(fuseAcc.search(detailSearch.value).map(r => r.item.act_id))
    accs = accs.filter(a => hits.has(a.act_id))
  }
  return accs
})

// 强制刷新（采集最新 FB 数据 + 巡检，跳过冷却）
const lastForceTs = ref(0)
const forceRefresh = async () => {
  const now = Math.floor(Date.now() / 1000)
  const left = 60 - (now - lastForceTs.value)
  if (lastForceTs.value && left > 0) {
    return ElMessage.warning(t('dashboard.forceCooldown', { n: left }))
  }
  try {
    await ElMessageBox.confirm(t('dashboard.forceConfirmMsg'), t('dashboard.forceConfirmTitle'),
      { type: 'warning', confirmButtonText: t('dashboard.forceConfirmBtn'), cancelButtonText: t('common.cancel') })
  } catch { return }
  refreshing.value = true
  lastForceTs.value = now
  try {
    await POST('/guard/inspect?force=true')
    ElMessage.success(t('dashboard.forceSuccess'))
    await loadDashboard(true)
    loadTrend()
  } catch (e) {
    ElMessage.error(t('dashboard.forceFail') + e.message)
  } finally {
    refreshing.value = false
  }
}

// 守护明细面板（自动止损/今日放行=日志表；巡检覆盖=账户状态表；账户五视角明细在左侧常驻表）
const kpiDetail = computed(() => {
  const mode = kpiMode.value
  if (!mode) return null
  const label = { pause: t('dashboard.kpiAutoPause'), allowance: t('dashboard.kpiAllowance'), coverage: t('dashboard.kpiCoverage') }[mode]

  // 止损明细：从 pause_details 构建（不是 accounts）
  if (mode === 'pause') {
    const logs = data.value.pause_details || []
    return {
      mode, title: label + ' · ' + t('dashboard.detailTitle'),
      type: 'logs',
      logs: logs.map(l => ({
        col1: l.target_id || '—',
        col2: (RULE_TYPE_LABEL_KEY[l.trigger_type] ? t(RULE_TYPE_LABEL_KEY[l.trigger_type]) : (l.trigger_type || '—')),
        col3: l.detail || '',
        col4: fmtTime(l.time),
        act_id: l.act_id || '',
        ad_id: l.target_id || '',
      })),
      headers: [t('dashboard.colAdId'), t('dashboard.colTriggerRule'), t('common.detail'), t('dashboard.colTime')],
    }
  }
  // 放行明细
  if (mode === 'allowance') {
    const logs = data.value.allowance_details || []
    return {
      mode, title: label + ' · ' + t('dashboard.detailTitle'),
      type: 'logs',
      logs: logs.map(l => ({
        col1: l.account_name || l.act_id || '—',
        col2: l.act_id || '—',
        col3: l.ad_id || '—',
        col4: l.is_cross_tz ? t('dashboard.allowanceCrossTz', { date: l.allowance_date }) : t('dashboard.allowanceActive'),
        act_id: l.act_id || '',
        ad_id: l.ad_id || '',
      })),
      headers: [t('dashboard.colAccount'), t('dashboard.colAccountId'), t('dashboard.colAdId'), t('common.status')],
    }
  }

  if (mode === 'coverage') {
    const statusOrder = (a) => (a.error === 'uncovered') ? 0 : (a.error ? 1 : 2)  // 巡检未覆盖在上（紧急）→跨时区→可巡检
    const accs = [...(data.value.accounts || [])].filter(a => a.is_managed !== false).sort((a, b) => statusOrder(a) - statusOrder(b) || (a.name || '').localeCompare(b.name || ''))
    return {
      mode, title: t('dashboard.kpiCoverage') + ' · ' + t('dashboard.coverageByAccount'), type: 'accounts', accs,
      cols: [
        { key: 'name', label: t('dashboard.colAccount'), left: true },
        { key: 'tz', label: t('dashboard.colLocalTime'), fmt: (v, a) => (a.error === 'cross_tz' ? '🕐 ' : '') + localTime(a.timezone) + ' ' + tzOffset(a.timezone) },
        { key: 'cov', label: t('dashboard.colInspectStatus'), fmt: (v, a) => (a.error === 'uncovered') ? '❌ ' + t('dashboard.covUncovered') : '✅ ' + t('dashboard.covOk') },
      ],
    }
  }
  return null
})
// 巡检覆盖明细搜索（与账户表共用 detailSearch，开面板时已清空）
const filteredCoverageAccs = computed(() => {
  if (kpiDetail.value?.type !== 'accounts') return []
  let accs = kpiDetail.value.accs
  if (detailSearch.value.trim()) {
    // 搜索只做过滤、保持表的既有排序（消耗降序等）——
    // 曾直接用 fuse.search().map，结果按匹配相关度重排，把消耗排序打乱
    const fuseAcc = new Fuse(accs, { keys: ['name', 'act_id'], threshold: 0.3 })
    const hits = new Set(fuseAcc.search(detailSearch.value).map(r => r.item.act_id))
    accs = accs.filter(a => hits.has(a.act_id))
  }
  return accs
})

// 告警详情改用抽屉（el-drawer）展示——彻底避开 sticky 顶条遮挡（之前 inline 展开被顶部条挡）
const notifDrawerOpen = ref(false)
const activeNotif = ref(null)
const openNotifDrawer = (n) => {
  activeNotif.value = n
  notifDrawerOpen.value = true
}
// 抽屉标题：动作 + 具体账户 + 广告（让用户一眼看到哪个账户哪个广告出问题、采取了什么动作）
const notifTitle = computed(() => activeNotif.value?.title || t('dashboard.notifDetail'))
// body 结构化：解析 "key：value" 行，key 突出 label，value 正文（无 key 行整行做 value）
const parseBody = (body) => {
  if (!body) return []
  const clean = body.replace(/<[^>]+>/g, '')  // 剥 HTML 标签（TG 的 <code> 等）
  return clean.split('\n').filter(l => l.trim()).map(line => {
    const m = line.match(/^([^：:]+)[：:]\s*(.+)$/)
    return m ? { key: m[1].trim(), val: m[2].trim() } : { key: '', val: line.trim() }
  })
}
const copyText = (text) => {
  if (!text) return
  const ids = String(text).match(/\d{10,}/g)
  const copy = ids ? ids[0] : String(text)
  navigator.clipboard?.writeText(copy).then(() => ElMessage.success(t('dashboard.copiedVal', { val: copy }))).catch(() => {})
}
// 充值紧急度（4 档 + 建议，对齐 taskCards 阈值）
const urgencyLabel = (a) => {
  if (a.removed) return '— ' + t('dashboard.urgencyRemoved')
  if (a.balance_kind !== 'limited') return '🟢 ' + t('dashboard.urgencyUnlimited')
  const b = a.balance || 0
  if (b <= 0) return '🔴 ' + t('dashboard.urgencyBlocked')
  if (b <= 100) return '🟠 ' + t('dashboard.urgencyUrgent')
  if (b <= 300) return '🟡 ' + t('dashboard.urgencyLow')
  return '🟢 ' + t('dashboard.urgencySufficient')
}
// 复制有消耗的账户 ID（当前日期范围）
const copySpendActIds = () => {
  const accs = (data.value.accounts || []).filter(a => (a.spend_usd || 0) > 0)
  const ids = accs.map(a => a.act_id).filter(Boolean).join('\n')
  if (!ids) { ElMessage.info(t('dashboard.noSpendAccounts')); return }
  navigator.clipboard?.writeText(ids).then(() => ElMessage.success(t('dashboard.copiedSpendIds', { n: accs.length }))).catch(() => {})
}
// CSV 导出（账户汇总/落地页子码，当前日期范围；列头语言走 X-Locale）
const exporting = ref(false)
const exportAccounts = async () => {
  exporting.value = true
  try { await downloadFile(`/dashboard/export?source=accounts&${rangeQuery()}`) }
  catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  exporting.value = false
}
const exportLandingBusy = ref(false)
const exportLanding = async () => {
  if (exportLandingBusy.value) return   // 双击防重
  exportLandingBusy.value = true
  try { await downloadFile(`/dashboard/export?source=landing&${rangeQuery()}`) }
  catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  exportLandingBusy.value = false
}
// 复选框选中（充值/余额明细用：勾选账户 → 复制选中 ID）
const selectedIds = ref(new Set())
const toggleSelect = (act_id) => {
  const s = new Set(selectedIds.value)
  if (s.has(act_id)) s.delete(act_id)
  else s.add(act_id)
  selectedIds.value = s
}
const copySelected = () => {
  const ids = [...selectedIds.value].filter(Boolean).join('\n')
  if (!ids) { ElMessage.info(t('dashboard.noSelection')); return }
  navigator.clipboard?.writeText(ids).then(() => ElMessage.success(t('dashboard.copiedSelected', { n: selectedIds.value.size }))).catch(() => {})
}
const localTime = (tz) => {
  if (!tz) return '—'
  try { return new Intl.DateTimeFormat(locale.value === 'en' ? 'en-US' : 'zh-CN', { timeZone: tz, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date()) }
  catch { return '—' }
}
const tzOffset = (tz) => {
  if (!tz) return ''
  try {
    const d = new Date()
    const local = new Date(d.toLocaleString('en-US', { timeZone: tz }))
    const utc = new Date(d.toLocaleString('en-US', { timeZone: 'UTC' }))
    const off = Math.round((local - utc) / 3600000)
    return 'UTC' + (off >= 0 ? '+' : '') + off
  } catch { return '' }
}
const ackNotif = async (id) => {
  const n = (recentNotifs.value || []).find(x => x.id === id)
  if (!n || n.read) return  // 防重入：已确认/不存在不重复 POST
  n.read = true  // 乐观：立即 UI 反馈，不等 POST
  ElMessage.success(t('dashboard.acked'))
  try {
    await POST('/notifications/read', { ids: [id] })
  } catch (e) {
    if (n) n.read = false  // 回滚
    ElMessage.error(t('dashboard.ackFail') + e.message)
  }
}
const notifFilter = ref('all')  // all / critical / warning
const filteredNotifs = computed(() => {
  const list = recentNotifs.value || []
  if (notifFilter.value === 'all') return list
  return list.filter(n => n.level === notifFilter.value)
})
const unreadNotifCount = computed(() => (recentNotifs.value || []).filter(n => !n.read).length)
const ackAllNotifs = async () => {
  try {
    await POST('/notifications/read', {})
    ;(recentNotifs.value || []).forEach(n => { n.read = true })
    ElMessage.success(t('dashboard.allRead'))
  } catch (e) { ElMessage.error(t('common.opFail') + (e.message || '')) }
}
const NOTIF_EVENT_LABEL_KEY = {
  rule_pause: 'dashboard.evPause', coverage_lost: 'dashboard.evCoverageLost', account_permission_error: 'dashboard.evPermission',
  token_expired: 'dashboard.evTokenInvalid', token_invalid: 'dashboard.evTokenInvalid', token_expiring_soon: 'dashboard.evTokenExpiring',
  token_rate_limited: 'dashboard.evThrottled', orphan_account: 'dashboard.evOrphan', inspection_stalled: 'dashboard.evInspectStalled',
  budget_progress_50: 'dashboard.evBudget', budget_progress_75: 'dashboard.evBudget', budget_progress_90: 'dashboard.evBudget', budget_progress_98: 'dashboard.evBudget',
  account_status_change: 'dashboard.evStatusChange', account_status_recovered: 'dashboard.evStatusRecovered', sentinel_pause: 'dashboard.evSentinel',
  landing_blocked: 'dashboard.evLandingBlocked', landing_health: 'dashboard.evLandingBlocked', landing_worker_error: 'dashboard.evLandingBlocked',
  leads_new: 'dashboard.evLeadsNew', leads_sync_failed: 'dashboard.evLeadsFail',
  subcode_cleanup: 'dashboard.evSubcodeCleanup',
}
const notifEventLabel = (et) => (NOTIF_EVENT_LABEL_KEY[et] ? t(NOTIF_EVENT_LABEL_KEY[et]) : '')

// 自定义日期
const showCustom = ref(false)
const customFrom = ref('')
const customTo = ref('')
const applyCustom = () => {
  if (!customFrom.value || !customTo.value) return
  loadDashboard()  // showCustom=true，rangeQuery 自动用 custom 范围
  loadTrend()      // 趋势图同步用 custom 范围（原漏刷 → 图表与 KPI 卡脱钩）
}
// DatePresetBar 自定义区间回调
const onCustomRange = ({ from, to }) => {
  customFrom.value = from; customTo.value = to; showCustom.value = true
  applyCustom()
}

const dateOptions = computed(() => DATE_PRESETS.map(p => ({ label: p.label, key: p.key })))

// ── 下次巡检倒计时（前端三态机，随时间自动切换）──
// 巡检状态：用后端 inspection_heartbeat（action_logs）判断是否在跑。
// last_synced = 最近快照写入时间（有活跃广告才有新快照，0 广告时不更新≠巡检停了）。
// 心跳每 5min 写一条 → 有心跳=巡检正常（不管有没有快照/广告）。
const INSPECT_INTERVAL_MS = 5 * 60 * 1000
// 巡检状态：基于巡检心跳（每轮巡检必写 inspection_heartbeat，不受广告/快照影响）
// —— 比基于 last_synced（快照，0 广告时不写）稳健，0 广告也不会误报停滞
const inspectState = computed(() => {
  const hb = data.value.last_heartbeat
  if (!hb) return 'idle'  // 从未巡检
  const hbT = new Date(hb.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(hb) ? hb : hb + 'Z').getTime()
  if (isNaN(hbT)) return 'running'
  const ms = (hbT + INSPECT_INTERVAL_MS) - Date.now()  // 距下次预期巡检
  if (ms > 0) return 'waiting'  // 还没到下次巡检
  if (ms > -INSPECT_INTERVAL_MS * 2) return 'running'  // 过点<10min（拉 FB 慢/巡检中，正常）
  return 'stalled'  // 过点>10min 无新心跳 = 真停滞
})
const countdown = ref('')
// 最近巡检时间（取所有账户中最新的 last_inspected_at）
const lastInspectedDisplay = computed(() => {
  const accs = data.value.accounts || []
  const times = accs.map(a => a.last_inspected_at).filter(Boolean).map(iso => new Date(iso.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z').getTime()).filter(n => !isNaN(n))
  if (!times.length) return ''
  const latest = new Date(Math.max(...times))
  return fmtTime(latest.toISOString())
})
// 页头时间 tooltip：数据更新 + 上次巡检完整时间
const phTimesTitle = computed(() => [
  lastUpdated.value ? `${t('dashboard.dataUpdated')} ${fmtAgo(lastUpdated.value)}` : '',
  lastInspectedDisplay.value ? `${t('dashboard.lastInspect')} ${lastInspectedDisplay.value}` : '',
].filter(Boolean).join('\n'))
const updateCountdown = () => {
  const state = inspectState.value
  if (state === 'idle') { countdown.value = t('dashboard.cdWaitingFirst'); return }
  if (state === 'running') { countdown.value = t('dashboard.cdNormal'); return }
  const hb = data.value.last_heartbeat
  const hbT = hb && new Date(hb.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(hb) ? hb : hb + 'Z').getTime()
  if (state === 'waiting' && hbT) {
    const ms = (hbT + INSPECT_INTERVAL_MS) - Date.now()
    if (ms > 0) { const m = Math.floor(ms / 60000); const s = Math.floor((ms % 60000) / 1000); countdown.value = t('dashboard.cdNext', { m, s }); return }
  }
  if (state === 'stalled' && hbT) {
    const min = Math.floor((Date.now() - hbT) / 60000)
    countdown.value = t('dashboard.cdStalled', { n: min })
    return
  }
  countdown.value = ''
}

let _timer = null
let _refreshTimer = null
const addAllowance = async (log) => {
  if (!log.act_id || !log.ad_id) return ElMessage.warning(t('dashboard.missingActAdId'))
  try {
    await POST('/guard/allowance', { act_id: log.act_id, ad_id: log.ad_id })
    ElMessage.success(t('dashboard.allowanceAdded'))
    await loadDashboard(true)
    loadTrend()
    kpiMode.value = null
  } catch (e) { ElMessage.error(t('dashboard.allowanceAddFail') + (e.message || '')) }
}
const removeAllowance = async (log) => {
  try {
    await DELETE(`/guard/allowance?act_id=${log.act_id}&ad_id=${log.ad_id}`)
    ElMessage.success(t('dashboard.allowanceRemoved'))
    await loadDashboard(true)
    loadTrend()
    kpiMode.value = null
  } catch (e) { ElMessage.error(t('dashboard.allowanceRemoveFail') + (e.message || '')) }
}

// TG 绑定提示：未绑 TG 顶部引导横幅 + 工具栏铃铛红点；绑定管理弹窗（TgManager 组件）
const tgBanner = ref(false)
const tgUnbound = ref(false)
const tgMgr = ref(null)
const loadTgBanner = async () => {
  try {
    const r = await GET('/notifications/tg/user-binding')
    tgUnbound.value = !r?.bound
    tgBanner.value = tgUnbound.value && localStorage.getItem('tova_tg_banner_off') !== '1'
  } catch {}
}
const dismissTgBanner = () => { tgBanner.value = false; localStorage.setItem('tova_tg_banner_off', '1') }
const openTgMgr = () => tgMgr.value?.open()

onMounted(() => {
  loadDashboard()
  loadTgBanner()
  loadTrend()
  updateCountdown()
  _timer = setInterval(updateCountdown, 1000)
  _refreshTimer = setInterval(() => {
    if (document.hidden) return
    // 用户正在操作（展开明细/勾选账户）时跳过自动刷新，避免打断
    if (selectedIds.value.size > 0 || kpiMode.value !== null || expandedCard.value !== null || landingKpiExpanded.value !== null) return
    loadDashboard()
  }, 60000)
})
onUnmounted(() => { if (_timer) clearInterval(_timer); if (_refreshTimer) clearInterval(_refreshTimer); _themeObserver.disconnect(); _ltThemeObserver.disconnect(); _charts.forEach(c => c?.destroy()); _ltCharts.forEach(c => c?.destroy()) })
</script>

<template>
  <div class="dashboard">
    <div class="top-loader" :class="{ active: appLoading }"><div class="top-loader-bar"></div></div>

    <!-- 页头（不 sticky）：标题 + 数据新鲜度 ｜ 巡检倒计时 + 复制/导出/刷新 -->
    <header class="page-head">
      <div class="ph-left">
        <h1 class="ph-title">{{ t('dashboard.pageTitle') }}</h1>
        <span v-if="lastUpdated || lastInspectedDisplay" class="ph-fresh" :title="phTimesTitle">
          <template v-if="lastUpdated">{{ t('dashboard.dataUpTo', { ago: fmtAgo(lastUpdated) }) }}</template>
          <template v-if="lastUpdated && lastInspectedDisplay"> · </template>
          <template v-if="lastInspectedDisplay">{{ t('dashboard.lastInspect') }} {{ lastInspectedDisplay }}</template>
        </span>
      </div>
      <div class="ph-actions">
        <span class="sync-time countdown" :class="inspectState">{{ countdown }}</span>
        <button class="head-btn tg-mgr-btn" @click="openTgMgr" :title="t('dashboard.tgMgrTitle')">
          <el-icon><Bell /></el-icon><span v-if="tgUnbound" class="tg-dot"></span>
        </button>
        <button class="head-btn" @click="copySpendActIds" :title="t('dashboard.copySpendTitle')">
          <el-icon><Document /></el-icon><span class="btn-txt">{{ t('dashboard.copySpendBtn') }}</span>
        </button>
        <button class="head-btn" :disabled="exporting" @click="exportAccounts" :title="t('common.exportCsv')">
          <el-icon><Download /></el-icon><span class="btn-txt">{{ exporting ? t('common.loading') : t('common.exportCsv') }}</span>
        </button>
        <button class="head-btn primary" :disabled="loading" @click="refreshData" :title="t('dashboard.refreshTitle')">
          <el-icon><Refresh /></el-icon><span class="btn-txt">{{ loading ? t('dashboard.refreshing') : t('common.refresh') }}</span>
        </button>
        <button v-if="isSuper" class="head-btn force" :disabled="refreshing" @click="forceRefresh" :title="t('dashboard.forceTitle')">{{ refreshing ? t('dashboard.collecting') : t('dashboard.collectNow') }}</button>
      </div>
    </header>

    <!-- TG 未绑定引导（可关闭）：告警第一时间到 TG -->
    <div v-if="tgBanner" class="tg-banner">
      <span class="tg-banner-txt">{{ t('dashboard.tgBannerText') }}</span>
      <button class="head-btn primary" @click="openTgMgr">{{ t('dashboard.tgBannerGo') }}</button>
      <button class="tg-banner-x" @click="dismissTgBanner" :title="t('common.close')">×</button>
    </div>

    <!-- 工具栏（sticky 单行）：日期预设 + 转化分类 + 账户多选；贴顶前后样式恒定（无视觉切换=无抖动） -->
    <div class="toolbar">
      <button class="head-btn mobile-filter-btn" @click="mobileFilters = !mobileFilters">
        <el-icon><Filter /></el-icon>{{ t('dashboard.filters') }}
      </button>
      <div class="tb-row tb-filters" :class="{ open: mobileFilters }">
        <DatePresetBar :presets="dateOptions" v-model="datePreset" @preset="() => { showCustom = false; loadDashboard() }" @custom="onCustomRange" />
        <div class="labeled-select">
          <span class="ls-label">{{ t('dashboard.convCat') }}</span>
          <el-select v-model="conversionCategory" @change="loadDashboard()" size="small" class="filter-select"
                     :placeholder="t('dashboard.convCat')" :title="t('dashboard.convCatTitle')">
            <el-option value="all" :label="t('dashboard.convAll')" />
            <el-option value="shopping" :label="t('dashboard.convShopping')" />
            <el-option value="messaging" :label="t('dashboard.convMessaging')" />
            <el-option value="leads" :label="t('dashboard.convLeads')" />
            <el-option value="engagement" :label="t('dashboard.convEngagement')" />
            <el-option value="traffic" :label="t('dashboard.convTraffic')" />
          </el-select>
        </div>
        <div class="labeled-select grow">
          <span class="ls-label">{{ t('dashboard.accountLabel') }}</span>
          <el-select v-model="selectedActs" multiple filterable collapse-tags collapse-tags-tooltip clearable
                     @change="loadDashboard(); loadTrend()" size="small" class="filter-select act-filter"
                     :placeholder="t('dashboard.allAccounts')" :title="t('dashboard.accountFilterTitle')">
            <template #label="{ label, value }">
              <span v-if="platChipOfAct(value)" :class="['plat-chip', platChipOfAct(value)]">{{ platChipOfAct(value).toUpperCase() }}</span>{{ label }}
            </template>
            <el-option v-for="a in (data.accounts || [])" :key="a.act_id" :value="a.act_id" :label="a.name">
              <span v-if="platChip(a)" :class="['plat-chip', platChip(a)]">{{ platChip(a).toUpperCase() }}</span>{{ a.name }}
            </el-option>
          </el-select>
        </div>
      </div>
    </div>

    <!-- 主内容双 Tab：数据看板 / 落地页数据（用户点名分离） -->
    <div class="main-tabs">
      <button class="main-tab" :class="{ on: mainTab === 'data' }" @click="mainTab = 'data'">{{ t('dashboard.tabData') }}</button>
      <button class="main-tab" :class="{ on: mainTab === 'landing' }" @click="mainTab = 'landing'">{{ t('dashboard.tabLanding') }}</button>
    </div>

    <!-- KPI 层：4 核心大卡（大数字 + 迷你趋势线；点击=账户明细表切到该指标视角）+ 4 次要小卡 -->
    <div v-show="mainTab === 'data'" class="kpi-zone" v-loading="loading">
      <div class="kpi-core-grid">
        <div v-for="card in coreCards" :key="card.mode" class="kpi-card" :class="{ active: accountView === card.mode }" @click="setAccountView(card.mode)">
          <div class="kpi-card-top">
            <span class="kpi-label">{{ card.label }}</span>
            <span v-if="card.unit" class="unit-mini" :title="multiCurrency && spendUnit === 'native' ? t('dashboard.multiCurHint') : ''">
              <button class="um-btn" :class="{ on: spendUnit === 'usd' }" @click.stop="spendUnit = 'usd'">{{ t('dashboard.unitUsd') }}</button>
              <button class="um-btn" :class="{ on: spendUnit === 'native' }" @click.stop="spendUnit = 'native'">{{ t('dashboard.unitNative') }}</button>
            </span>
          </div>
          <span class="kpi-value">{{ card.value }}</span>
          <span v-if="card.sub" class="kpi-sub">{{ card.sub }}</span>
          <svg v-if="card.spark" class="kpi-spark" viewBox="0 0 100 26" preserveAspectRatio="none" aria-hidden="true">
            <polyline :points="card.spark" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
      </div>
      <div class="kpi-strip">
        <div v-for="card in subCards" :key="card.label" class="strip-metric" :class="{ clickable: !!card.mode, active: !!card.mode && accountView === card.mode, alert: card.alert > 0 }" @click="card.mode && setAccountView(card.mode)">
          <span class="km-value">{{ card.value }}</span>
          <span class="km-label">{{ card.label }}</span>
          <span v-if="card.alert > 0" class="km-badge">{{ t('dashboard.balanceAlertCount', { n: card.alert }) }}</span>
        </div>
      </div>
    </div>

    <!-- 趋势（主视觉）：全宽单图 + 指标切换 + 颗粒度 + 平台范围回显 -->
    <div v-show="mainTab === 'data'" class="card trend-main">
      <div class="card-header">
        <div class="tm-title-wrap">
          <span class="card-title">{{ t('dashboard.trend') }}</span>
          <span v-if="scopeChip" class="scope-chip">{{ scopeChip }}</span>
        </div>
        <div class="tm-controls">
          <div class="status-tabs">
            <button v-for="s in TREND_SERIES" :key="s.key" class="status-tab" :class="{ active: trendMetric === s.key }" @click="trendMetric = s.key">{{ s.label }}</button>
          </div>
          <div class="trend-presets">
            <button v-for="o in GRAN_OPTS" :key="o.value" class="tp-btn" :class="{ on: trendGran === o.value }" @click="trendGran = o.value">{{ o.label }}</button>
          </div>
        </div>
      </div>
      <div v-if="trendData.labels?.length" class="trend-main-canvas"><canvas ref="trendCanvas"></canvas></div>
      <div v-else class="trend-empty">{{ t('dashboard.noTrendData') }}</div>
    </div>

    <div v-show="mainTab === 'data'" class="main-split" :class="{ 'no-accs': !hasManagedAccs }">
      <!-- 左：账户明细（常驻表；视角=消耗/转化/CPA/ROAS/余额，行点击跳广告管理器）-->
      <div v-if="!hasManagedAccs" class="card accounts-card accounts-empty" v-loading="loading">
        <div class="acc-empty-banner">
          <span class="acc-empty-icon">📊</span>
          <div class="acc-empty-text">
            <div class="acc-empty-title">{{ t('dashboard.noManagedTitle') }}</div>
            <div class="acc-empty-sub">{{ t('dashboard.noManagedHint') }}</div>
          </div>
          <router-link to="/ads" class="acc-empty-btn">{{ t('dashboard.goImport') }}</router-link>
        </div>
      </div>
      <div v-else class="card accounts-card" v-loading="loading">
        <div class="card-header accounts-head">
          <span class="card-title">{{ t('dashboard.accountsTitle') }}</span>
          <div class="table-tools">
            <div class="status-tabs">
              <button v-for="v in VIEW_TABS" :key="v.mode" class="status-tab" :class="{ active: accountView === v.mode }" @click="setAccountView(v.mode)">{{ v.label }}</button>
            </div>
            <input v-model="detailSearch" class="search-input" :placeholder="t('dashboard.searchPh')" />
            <button v-if="accountView === 'balance'" class="copy-ids-btn" @click="copySelected()">{{ t('dashboard.copySelected') }} ({{ selectedIds.size }})</button>
              <el-switch v-if="accountView !== 'balance'" :model-value="showRemoved" size="small" @update:model-value="v => showRemoved = v" :active-text="t('dashboard.showRemoved')" style="margin-left:10px" />
          </div>
        </div>
        <div class="table-scroll acc-scroll">
          <table class="detail-table accounts-table">
            <thead><tr><th v-for="col in accountsTable.cols" :key="col.key" :class="col.left ? 'left' : 'right'">{{ col.label }}</th></tr></thead>
            <tbody>
              <tr v-for="acc in filteredAccounts" :key="acc.act_id" :class="{ 'selected-row': selectedIds.has(acc.act_id), 'removed-row': acc.removed }" @click="acc.removed ? null : (accountView === 'balance' ? toggleSelect(acc.act_id) : router.push({ name: 'ad-manager', query: { act: acc.act_id } }))">
                <td v-for="col in accountsTable.cols" :key="col.key" :class="col.left ? 'left' : 'right'" class="mono" :style="{ fontWeight: col.bold ? 600 : 400 }">
                  <template v-if="col.key === 'name'"><span v-if="platChip(acc)" :class="['plat-chip', platChip(acc)]">{{ platChip(acc) }}</span>{{ acc.removed ? `（${t('dashboard.removedTag')}）${acc.act_id}` : acc.name }}</template>
                  <template v-else>{{ col.fmt(acc[col.key], acc) }}</template>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="!filteredAccounts.length && !accountsTable.accs.some(a=>!a.removed)" class="empty" style="padding:40px 20px;text-align:center">
            <div style="font-size:15px;font-weight:600;margin-bottom:8px">{{ t('dashboard.noManagedTitle') }}</div>
            <div style="font-size:12px;color:var(--t3);margin-bottom:16px">{{ t('dashboard.noManagedHint') }}</div>
            <router-link to="/ads" style="color:var(--ac);font-size:13px;text-decoration:none;border:1px solid var(--ac);padding:6px 16px;border-radius:6px">{{ t('dashboard.goImport') }}</router-link>
          </div>
          <div v-else-if="!filteredAccounts.length" class="empty">{{ t('dashboard.noMatch') }}</div>
        </div>
      </div>

      <!-- 右：守护概览 + 待处理事项 + 最近告警（纵向堆叠）-->
      <div class="side-stack">
        <div class="card guard-card">
          <div class="card-header"><span class="card-title">{{ t('dashboard.guardTitle') }}</span></div>
          <div class="guard-grid">
            <div v-for="cell in guardCells" :key="cell.mode" class="guard-cell" :class="{ active: kpiMode === cell.mode, danger: cell.danger }" @click="toggleKpiMode(cell.mode)">
              <span class="gc-value" :class="{ 'text-danger': cell.danger }">{{ cell.value }}</span>
              <span class="gc-label">{{ cell.label }}</span>
              <span v-if="cell.sub" class="gc-sub">{{ cell.sub }}</span>
            </div>
          </div>
          <div v-if="kpiDetail" class="kpi-detail-panel guard-detail">
            <div class="detail-header">
              <span>{{ kpiDetail.title }}</span>
              <div class="detail-tools">
                <input v-if="kpiDetail.type === 'accounts'" v-model="detailSearch" class="detail-search" :placeholder="t('dashboard.searchPh')" />
                <el-icon class="detail-close" @click="kpiMode = null"><Close /></el-icon>
              </div>
            </div>
            <div v-if="kpiDetail.type === 'accounts'" class="table-scroll">
              <table class="detail-table">
                <thead><tr><th v-for="col in kpiDetail.cols" :key="col.key" :class="col.left ? 'left' : 'right'">{{ col.label }}</th></tr></thead>
                <tbody>
                  <tr v-for="acc in filteredCoverageAccs" :key="acc.act_id" @click="router.push({ name: 'ad-manager', query: { act: acc.act_id } })">
                    <td v-for="col in kpiDetail.cols" :key="col.key" :class="col.left ? 'left' : 'right'" class="mono">
                      <template v-if="col.key === 'name'"><span v-if="platChip(acc)" :class="['plat-chip', platChip(acc)]">{{ platChip(acc) }}</span>{{ acc.name }}</template>
                      <template v-else>{{ col.fmt(acc[col.key], acc) }}</template>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div v-if="!filteredCoverageAccs.length" class="empty">{{ t('dashboard.noMatch') }}</div>
            </div>
            <div v-else class="table-scroll">
              <table class="detail-table">
                <thead><tr>
                  <th v-for="(h, i) in kpiDetail.headers" :key="i" :class="i === 0 ? 'left' : 'right'">{{ h }}</th>
                  <th v-if="['pause','allowance'].includes(kpiDetail.mode)" class="right">{{ t('common.operation') }}</th>
                </tr></thead>
                <tbody>
                  <tr v-for="(log, i) in kpiDetail.logs" :key="i">
                    <td class="left mono">{{ log.col1 }}</td>
                    <td v-for="j in kpiDetail.headers.length - 1" :key="j" class="right mono log-cell">{{ log['col' + (j + 1)] }}</td>
                    <td v-if="kpiDetail.mode === 'pause'" class="right"><button class="allow-btn" @click="addAllowance(log)">{{ t('dashboard.allowToday') }}</button></td>
                    <td v-if="kpiDetail.mode === 'allowance'" class="right"><button class="allow-btn remove" @click="removeAllowance(log)">{{ t('dashboard.removeAllowance') }}</button></td>
                  </tr>
                </tbody>
              </table>
              <div v-if="!kpiDetail.logs.length" class="empty">{{ t('dashboard.noRecords') }}</div>
            </div>
          </div>
        </div>

        <div v-show="!loading" class="card todo-card">
          <div class="card-header"><span class="card-title">{{ t('dashboard.todoTitle') }}</span></div>
          <div class="task-list">
            <div v-for="(card, i) in taskCards" :key="i" class="task-card" :class="[card.kind, { expanded: expandedCard === i, flat: !card.detailAccounts?.length && !card.toTokens }]" @click="toggleCard(i)">
              <div class="task-icon-wrap"><el-icon class="task-icon"><component :is="card.icon" /></el-icon></div>
              <div class="task-body"><div class="task-title">{{ card.title }}</div><div class="task-desc">{{ card.desc }}</div></div>
              <span v-if="card.toTokens" class="task-go">{{ t('dashboard.taskTokenGo') }} →</span>
              <el-icon v-if="card.detailAccounts?.length" class="task-expand-icon" :class="{ rotated: expandedCard === i }"><ArrowDown /></el-icon>
            </div>
          </div>
          <div v-if="expandedCard !== null && taskCards[expandedCard]?.detailAccounts?.length" class="detail-panel task-detail">
            <div class="detail-header"><span>{{ taskCards[expandedCard].title }} · {{ t('dashboard.detailTitle') }}</span><div class="detail-tools"><button class="copy-ids-btn" @click="copySelected()">{{ t('dashboard.copySelected') }} ({{ selectedIds.size }})</button><el-icon class="detail-close" @click="expandedCard = null"><Close /></el-icon></div></div>
            <table class="detail-table">
              <thead><tr><th v-for="col in taskCards[expandedCard].detailColumns" :key="col" :class="col === 'name' ? 'left' : 'right'">{{ columnLabel(col) }}</th></tr></thead>
              <tbody>
                <tr v-for="acc in taskCards[expandedCard].detailAccounts" :key="acc.act_id" :class="{ 'selected-row': selectedIds.has(acc.act_id) }" @click="toggleSelect(acc.act_id)">
                  <td v-for="col in taskCards[expandedCard].detailColumns" :key="col" :class="col === 'name' ? 'left' : 'right'" class="mono"><span v-if="col === 'name' && platChip(acc)" :class="['plat-chip', platChip(acc)]">{{ platChip(acc) }}</span>{{ columnFmt(col, acc) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="card notif-card">
          <div class="card-header">
            <span class="card-title">{{ t('dashboard.recentNotifs') }}<span v-if="platform !== 'all'" class="scope-chip" style="margin-left:8px">{{ platform === 'tt' ? 'TikTok' : 'Facebook' }}</span><span v-if="unreadNotifCount" class="notif-unread-badge">{{ unreadNotifCount }}</span></span>
            <div class="status-tabs">
              <button class="status-tab" :class="{ active: notifFilter === 'all' }" @click="notifFilter = 'all'">{{ t('common.all') }}</button>
              <button class="status-tab" :class="{ active: notifFilter === 'critical' }" @click="notifFilter = 'critical'">{{ t('dashboard.levelCritical') }}</button>
              <button class="status-tab" :class="{ active: notifFilter === 'warning' }" @click="notifFilter = 'warning'">{{ t('dashboard.levelWarning') }}</button>
              <button class="status-tab" :class="{ active: notifFilter === 'info' }" @click="notifFilter = 'info'">{{ t('dashboard.levelInfo') }}</button>
              <button v-if="unreadNotifCount" class="status-tab ack-all" @click="ackAllNotifs">{{ t('dashboard.markAllRead') }}</button>
            </div>
          </div>
          <div class="notif-list">
            <div v-for="n in filteredNotifs" :key="n.id" class="notif-row-wrap">
              <div class="notif-row" :class="{ acked: n.read }" @click="openNotifDrawer(n)">
                <span class="notif-dot" :class="n.level"></span>
                <div class="notif-content">
                  <div class="notif-text"><span v-if="notifEventLabel(n.event_type)" class="notif-etype" :class="n.level">{{ notifEventLabel(n.event_type) }}</span>{{ n.title }}</div>
                  <div class="notif-meta">{{ fmtTime(n.created_at) }}</div>
                </div>
                <button v-if="!n.read" class="ack-btn" @click.stop="ackNotif(n.id)">{{ t('common.confirm') }}</button>
                <span v-else class="acked-tag">{{ t('dashboard.ackedTag') }}</span>
              </div>
            </div>
            <div v-if="!filteredNotifs.length" class="empty">{{ notifFilter === 'all' ? t('dashboard.noNotifs') : t('dashboard.noNotifsLevel') }}</div>
          </div>
        </div>
      </div>
    </div>

    <el-drawer v-model="notifDrawerOpen" :title="notifTitle" direction="rtl" size="480px" :destroy-on-close="true">
      <div v-if="activeNotif" class="notif-drawer">
        <div class="nd-head">
          <span class="nd-level" :class="activeNotif.level">{{ ({critical:t('dashboard.levelCritical'),warning:t('dashboard.levelWarning'),info:t('dashboard.levelInfo')})[activeNotif.level] || t('dashboard.levelNotice') }}</span>
          <span v-if="activeNotif.event_type" class="nd-event">{{ notifEventLabel(activeNotif.event_type) || activeNotif.event_type }}</span>
          <span class="nd-time">{{ fmtTime(activeNotif.created_at) }}</span>
        </div>
        <div class="nd-body">
          <div v-for="(row, i) in parseBody(activeNotif.body)" :key="i" class="nd-body-row">
            <span v-if="row.key" class="nd-body-key">{{ row.key }}</span>
            <span class="nd-body-val" @click="copyText(row.val)" :title="t('dashboard.clickToCopy')">{{ row.val }}</span>
          </div>
          <div v-if="!activeNotif.body" class="nd-body-empty">（{{ t('dashboard.noDetailContent') }}）</div>
        </div>
      </div>
    </el-drawer>

    <!-- 落地页 Tab：与数据 Tab 同语言——平级卡片，无大盒套小卡 -->
    <div v-show="mainTab === 'landing'" v-if="landing.totals && landing.totals.visits != null" class="stat-grid">
        <div v-for="(card, i) in landingCards" :key="i" class="stat-card" :class="[card.color, { clickable: card.clickable, active: landingKpiExpanded === i }]" @click="toggleLandingKpi(i)">
          <span class="stat-label">{{ card.label }}</span>
          <span class="stat-value">{{ card.value }}</span>
          <span v-if="card.sub" class="stat-sub">{{ card.sub }}</span>
          <el-icon v-if="card.clickable" class="stat-arrow" :class="{ rotated: landingKpiExpanded === i }"><ArrowDown /></el-icon>
        </div>
      </div>
      <div v-show="mainTab === 'landing'" v-if="landingKpiDetail" class="kpi-detail-panel">
        <div class="detail-header">
          <span>{{ landingKpiDetail.title }}</span>
          <div class="detail-tools">
            <el-icon class="detail-close" @click="landingKpiExpanded = null"><Close /></el-icon>
          </div>
        </div>
        <div class="table-scroll">
          <table class="detail-table">
            <thead><tr>
              <th class="left">{{ t('dashboard.colSubcode') }}</th><th class="left">{{ t('dashboard.colDomain') }}</th>
              <th class="right">{{ t('dashboard.kpiVisits') }}</th><th class="right">{{ t('dashboard.kpiPass') }}</th><th class="right">{{ t('dashboard.kpiBlocked') }}</th>
              <th class="right">{{ t('dashboard.colSpend') }}</th><th class="right">{{ t('dashboard.colCpc') }}</th><th class="center">{{ t('common.status') }}</th>
            </tr></thead>
            <tbody>
              <tr v-for="r in landingKpiDetail.rows" :key="(r.slug||'')+(r.ad_id||'')">
                <td class="left"><div class="acc-name">{{ r.slug }}</div><div class="acc-id">{{ r.ad_id }}</div></td>
                <td class="left mono">{{ r.domain || '—' }}</td>
                <td class="right mono">{{ fmt(r.visits) }}</td>
                <td class="right mono">{{ fmt(r.clicks) }}</td>
                <td class="right mono" :class="{ 'text-danger': r.blocked > 0 }">{{ fmt(r.blocked) }}</td>
                <td class="right mono">{{ fmtUsd(r.spend_usd) }}</td>
                <td class="right mono">{{ r.cpc ? '$'+r.cpc : '—' }}</td>
                <td class="center"><span class="pill" :class="r.state">{{ landingStateLabel(r.state) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!landingKpiDetail.rows.length" class="empty">{{ t('dashboard.noSubcodeData') }}</div>
      </div>
    <div v-show="mainTab === 'landing'" class="card trend-main">
      <div class="card-header">
        <div class="tm-title-wrap">
          <span class="card-title">{{ t('dashboard.landingTrendTitle') }}</span>
          <span v-if="scopeChip" class="scope-chip">{{ scopeChip }}</span>
        </div>
        <div class="tm-controls">
          <div class="status-tabs">
            <button v-for="s in LT_SERIES" :key="s.key" class="status-tab" :class="{ active: landingTrendMetric === s.key }" @click="landingTrendMetric = s.key">{{ s.label }}</button>
          </div>
        </div>
      </div>
      <div v-if="landingTrend.labels?.length" class="trend-main-canvas lt"><canvas ref="ltCanvas"></canvas></div>
      <div v-else class="trend-empty">{{ t('dashboard.noLandingTrendData') }}</div>
    </div>
      <div v-show="mainTab === 'landing'" class="card" v-loading="landingLoading">
        <div class="card-header">
          <span class="card-title">{{ t('dashboard.subcodePerformance') }}</span>
          <div class="table-tools">
            <input v-model="landingSearch" class="search-input" :placeholder="t('dashboard.searchLandingPh')" />
            <div class="status-tabs">
              <button class="status-tab" :class="{ active: landingFilter === 'all' }" @click="landingFilter = 'all'">{{ t('common.all') }} {{ (landing.rows || []).length }}</button>
              <button class="status-tab" :class="{ active: landingFilter === 'good' }" @click="landingFilter = 'good'">{{ t('dashboard.stateGood') }}</button>
              <button class="status-tab" :class="{ active: landingFilter === 'waste' }" @click="landingFilter = 'waste'">{{ t('dashboard.stateWaste') }}</button>
              <button class="status-tab" :class="{ active: landingFilter === 'watch' }" @click="landingFilter = 'watch'">{{ t('dashboard.stateWatch') }}</button>
            </div>
            <button class="head-btn" :disabled="exportLandingBusy" @click="exportLanding" :title="t('common.exportCsv')">
              <el-icon><Download /></el-icon><span class="btn-txt">{{ exportLandingBusy ? t('common.loading') : t('common.exportCsv') }}</span>
            </button>
          </div>
        </div>
        <div class="table-scroll">
          <table class="acc-table">
            <thead><tr>
              <th class="left">{{ t('dashboard.colSubcode') }}</th><th class="left">{{ t('dashboard.colAccount') }}</th><th class="left">{{ t('dashboard.colDomain') }}</th>
              <th class="right">{{ t('dashboard.kpiVisits') }}</th><th class="right">{{ t('dashboard.kpiPass') }}</th><th class="right">{{ t('dashboard.kpiBlocked') }}</th>
              <th class="right">{{ t('dashboard.kpiPassRate') }}</th><th class="right">{{ t('dashboard.colSpend') }}</th><th class="right">{{ t('dashboard.colCpc') }}</th><th class="right">CVR</th><th class="center">{{ t('common.status') }}</th>
            </tr></thead>
            <tbody>
              <tr v-for="r in filteredLanding" :key="(r.slug || '') + (r.ad_id || '')">
                <td class="left"><div class="acc-name">{{ r.slug }}</div><div class="acc-id">{{ r.ad_id }}</div></td>
                <td class="left"><div class="acc-name">{{ r.account || '—' }}</div><div class="acc-id">{{ r.act_id || '' }}</div></td>
                <td class="left mono">{{ r.domain || '—' }}</td>
                <td class="right mono">{{ fmt(r.visits) }}</td>
                <td class="right mono">{{ fmt(r.clicks) }}</td>
                <td class="right mono" :class="{ 'text-danger': r.blocked > 0 }">{{ fmt(r.blocked) }}</td>
                <td class="right mono">{{ fmtPct(r.pass_rate) }}</td>
                <td class="right mono">{{ fmtUsd(r.spend_usd) }}</td>
                <td class="right mono">{{ r.cpc ? '$' + r.cpc : '—' }}</td>
                <td class="right mono">{{ fmtPct(r.cvr) }}</td>
                <td class="center"><span class="pill" :class="r.state">{{ landingStateLabel(r.state) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!filteredLanding.length" class="empty">{{ t('dashboard.noLandingData') }}</div>
      </div>
      <div v-show="mainTab === 'landing'" v-if="landing.totals && landing.totals.blocked > 0" class="card block-detail">
        <div class="card-header"><span class="card-title">{{ t('dashboard.blockDist') }}</span></div>
        <div class="block-grid">
          <div class="block-col">
            <div class="block-col-title">{{ t('dashboard.byReason') }}</div>
            <div v-for="b in (landing.block_detail.by_reason || [])" :key="'r' + b.key" class="bar-row">
              <span class="bar-label" :title="b.key">{{ blockReasonLabel(b.key) }}</span>
              <div class="bar-track"><div class="bar-fill danger" :style="{ width: barWidth(b.count, landing.block_detail.by_reason) }"></div></div>
              <span class="bar-val">{{ b.count }}</span>
            </div>
          </div>
          <div class="block-col">
            <div class="block-col-title">{{ t('dashboard.byCountry') }}</div>
            <div v-for="b in (landing.block_detail.by_country || [])" :key="'c' + b.key" class="bar-row">
              <span class="bar-label" :title="b.key">{{ countryLabel(b.key) }}</span>
              <div class="bar-track"><div class="bar-fill danger" :style="{ width: barWidth(b.count, landing.block_detail.by_country) }"></div></div>
              <span class="bar-val">{{ b.count }}</span>
            </div>
          </div>
          <div class="block-col">
            <div class="block-col-title">{{ t('dashboard.byPlatform') }}</div>
            <div v-for="b in (landing.block_detail.by_platform || [])" :key="'p' + b.key" class="bar-row">
              <span class="bar-label" :title="b.key">{{ b.key }}</span>
              <div class="bar-track"><div class="bar-fill danger" :style="{ width: barWidth(b.count, landing.block_detail.by_platform) }"></div></div>
              <span class="bar-val">{{ b.count }}</span>
            </div>
          </div>
        </div>
      </div>
    <TgManager ref="tgMgr" />
</div>
</template>

<style scoped>
.dashboard { display: block; max-width: 1680px; margin: 0 auto; }
.dashboard > * + * { margin-top: 16px; }

/* ── 页头（非 sticky）：标题 + 数据新鲜度 ｜ 巡检倒计时 + 动作按钮 ── */
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 48px; flex-wrap: wrap; }
.ph-left { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.ph-title { margin: 0; font-size: 22px; font-weight: 700; color: var(--t1); letter-spacing: -0.01em; }
.ph-fresh { font-size: 12px; color: var(--t3); }
.ph-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
/* 页头/工具栏通用按钮（比旧 refresh-btn 更克制：描边为主，仅刷新用强调色） */
.head-btn {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 6px 12px; background: var(--bg2); color: var(--t2);
  border: 1px solid var(--bd); border-radius: var(--rs);
  font-size: 12px; cursor: pointer; transition: all 0.15s; white-space: nowrap; font-family: inherit;
}
.head-btn .el-icon { font-size: 14px }
.head-btn:hover { color: var(--t1); border-color: var(--bd2); }
.head-btn:disabled { opacity: 0.6; cursor: wait; }
.head-btn.primary { background: var(--acg); color: var(--ac); border-color: var(--ac); }
.head-btn.primary:hover { background: var(--ac); color: #fff; }
.head-btn.force { color: var(--warning); border-color: rgba(255,159,10,.5); background: transparent; }
.head-btn.force:hover { background: rgba(255,159,10,.12); border-color: var(--warning); }
.head-btn.force:disabled { opacity: .6; }

/* ── 工具栏（sticky 单行）：日期预设 + 转化分类 + 账户多选 ── */
.main-tabs { display: flex; gap: 4px; margin: 14px 0 2px; }
.main-tab { padding: 8px 20px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t2); border-radius: 8px; font-size: 14px; font-weight: 500; cursor: pointer; font-family: inherit; }
.main-tab.on { background: var(--acg); color: var(--ac); border-color: var(--ac); }
/* sticky 基准是 .content 滚动区顶缘（平台上下文条在其外常驻），top:0 即紧贴平台条 */
.tg-mgr-btn { position: relative; }
.tg-dot { position: absolute; top: 6px; right: 6px; width: 8px; height: 8px; border-radius: 50%; background: var(--el-color-danger, #f56c6c); box-shadow: 0 0 0 2px var(--bg, #fff); }
.tg-banner { display: flex; align-items: center; gap: 12px; padding: 8px 14px; margin-bottom: 10px; border: 1px solid var(--el-color-warning, #e6a23c); background: var(--el-color-warning-light-9, #fdf6ec); border-radius: 8px; font-size: 13px; }
.tg-banner-txt { flex: 1; }
.tg-banner-x { border: none; background: none; font-size: 18px; line-height: 1; cursor: pointer; color: var(--tx-3, #999); padding: 2px 6px; }
/* 贴顶前后样式恒定（圆角/阴影/边框不变）——视觉切换=滚动抖动源，已彻底移除 stuck 态 */
.toolbar { position: sticky; top: 0; z-index: 100; display: flex; flex-direction: column; background: var(--bg); border: 1px solid var(--bd); border-radius: var(--rs); box-shadow: var(--shadow-card); overflow: hidden; }
.tb-row { display: flex; align-items: center; gap: 12px; padding: 8px 14px; flex-wrap: wrap; }
.tb-filters .labeled-select.grow { margin-left: auto; }
.tb-filters .labeled-select.grow .act-filter { width: 220px; }
.labeled-select { display: flex; align-items: center; gap: 6px; flex-shrink: 0 }
.ls-label { font-size: 12px; color: var(--t3); white-space: nowrap }
.tb-filters .filter-select { width: 120px; }
.mobile-filter-btn { display: none; }

/* 平台范围 chip（平台≠all 时显示 "Facebook · N 账户"） */
.scope-chip { display: inline-flex; align-items: center; align-self: center; height: 20px; padding: 0 9px; border-radius: 10px; background: var(--bg3); color: var(--t2); font-size: 11px; white-space: nowrap; }
/* KPI 本币/USD 切换（收进总消耗卡右上角，迷你两键） */
.unit-mini { display: inline-flex; gap: 2px; }
.um-btn { padding: 1px 7px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t3); border-radius: 4px; font-size: 10px; cursor: pointer; line-height: 16px; font-family: inherit; }
.um-btn.on { background: var(--acg); color: var(--ac); border-color: var(--ac); }

/* 趋势主图（全宽单图 + 指标 tabs + 颗粒度；数据/落地页两 Tab 共用） */
.tm-title-wrap { display: flex; align-items: center; gap: 10px; min-width: 0; }
.tm-controls { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.trend-presets { display: flex; gap: 4px; }
.tp-btn { padding: 3px 10px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t3); border-radius: 4px; font-size: 11px; cursor: pointer; }
.tp-btn.on { background: var(--acg); color: var(--ac); border-color: var(--ac); }
.trend-main-canvas { height: 320px; padding: 12px 16px 16px; }
.trend-main-canvas.lt { height: 240px; }   /* 落地页趋势：矮一档，与指标 chip 同卡 */
.trend-empty { text-align: center; color: var(--t3); padding: 48px; font-size: 13px; }

/* 任务列表（右列卡片内，单列堆叠；水平内边距与其他卡统一 16px） */
.task-list { display: flex; flex-direction: column; gap: 8px; padding: 12px 16px; }

.sync-time { font-size: 11px; color: var(--t3); }
.sync-time.countdown {
  font-family: 'SF Mono', 'Fira Code', monospace; font-variant-numeric: tabular-nums;
  color: var(--t2); letter-spacing: 0.02em; transition: color 0.2s; white-space: nowrap;
}
.sync-time.countdown.idle { color: var(--t3); }
.sync-time.countdown.waiting { color: var(--t2); }
.sync-time.countdown.running { color: var(--ac); }
.sync-time.countdown.stalled {
  color: var(--error); cursor: pointer; font-weight: 600;
  animation: stall-blink 1.4s ease-in-out infinite;
}
@keyframes stall-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }

/* 移动端：页头按钮收图标 + 筛选行收进「筛选」按钮（桌面恒展开） */
@media (max-width: 768px) {
  .ph-actions .btn-txt { display: none }
  .ph-actions .head-btn { padding: 6px 8px }
  .mobile-filter-btn { display: inline-flex; align-self: flex-start; margin: 8px 14px; }
  .tb-row.tb-filters { display: none; }
  .tb-row.tb-filters.open { display: flex; }
}
/* 顶部加载进度条（数据加载/采集时显示，仿 1.0）*/
.top-loader { position: fixed; top: 0; left: 0; right: 0; height: 2px; z-index: 9999; pointer-events: none; opacity: 0; transition: opacity 0.25s; }
.top-loader.active { opacity: 1; }
.top-loader-bar { height: 100%; width: 0; background: linear-gradient(90deg, var(--ac), #64d2ff); border-radius: 0 2px 2px 0; animation: topload 1.1s ease-in-out infinite; }
@keyframes topload { 0% { width: 0; } 50% { width: 65%; } 100% { width: 96%; } }

/* KPI 明细内搜索 */
.detail-tools { display: flex; align-items: center; gap: 8px; }
.copy-ids-btn { padding: 3px 10px; background: var(--acg); color: var(--ac); border: 1px solid var(--ac); border-radius: 4px; font-size: 12px; cursor: pointer; white-space: nowrap; }
.copy-ids-btn:hover { background: var(--ac); color: #fff; }
.detail-search {
  background: var(--bg3); color: var(--t1); border: 1px solid var(--bd);
  border-radius: var(--rs); padding: 5px 12px; font-size: 13px; width: 140px;
  font-family: var(--font); transition: border-color 0.15s;
}
.detail-search:focus { outline: none; border-color: var(--ac); }
.detail-search::placeholder { color: var(--t3); }

/* ── KPI 分层：核心 4 大卡 + 次要 4 小卡 ── */
.kpi-zone { display: flex; flex-direction: column; gap: 10px; }
.kpi-core-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.kpi-card {
  position: relative; background: var(--bg2); border: 1px solid var(--bd); border-radius: var(--rs);
  padding: 14px 16px 8px; display: flex; flex-direction: column; gap: 2px;
  cursor: pointer; transition: all 0.15s; box-shadow: var(--shadow-card); overflow: hidden;
}
.kpi-card::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: transparent; transition: background 0.15s; }
.kpi-card:hover { border-color: var(--bd2); transform: translateY(-1px); }
.kpi-card.active { border-color: var(--ac); background: var(--acg); box-shadow: inset 0 0 0 1px var(--ac), var(--shadow-card); }
.kpi-card.active::before { background: var(--ac); }
.kpi-card.active .kpi-label { color: var(--ac); font-weight: 600; }
.kpi-card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 20px; }
.kpi-label { font-size: 12px; color: var(--t3); white-space: nowrap; }
.kpi-value { font-size: 26px; font-weight: 650; color: var(--t1); letter-spacing: -0.02em; line-height: 1.25; font-variant-numeric: tabular-nums; }
.kpi-sub { font-size: 10px; color: var(--t3); }
.kpi-spark { width: 100%; height: 26px; color: var(--ac); opacity: 0.55; margin-top: 4px; display: block; }
/* 次要 4 指标：一张细条卡内 4 个 inline 指标（无卡套卡），竖分隔线分列 */
.kpi-strip { display: grid; grid-template-columns: repeat(4, 1fr); background: var(--bg2); border: 1px solid var(--bd); border-radius: var(--rs); box-shadow: var(--shadow-card); }
.strip-metric { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; row-gap: 2px; padding: 11px 16px; border-left: 1px solid var(--bd); min-width: 0; }
.strip-metric:nth-child(4n+1) { border-left: none; }
.strip-metric.clickable { cursor: pointer; transition: background 0.15s; }
.strip-metric.clickable:hover { background: var(--bg3); }
.strip-metric.active { background: var(--acg); box-shadow: inset 0 0 0 1px var(--ac); }
.strip-metric.active .km-value { color: var(--ac); }
.strip-metric.alert .km-value { color: var(--warning); }
.km-value { font-size: 16px; font-weight: 600; color: var(--t1); font-variant-numeric: tabular-nums; }
.km-label { font-size: 11px; color: var(--t3); white-space: nowrap; }
.km-badge { margin-left: auto; font-size: 10px; padding: 1px 7px; border-radius: 8px; background: rgba(255,159,10,.15); color: var(--warning); white-space: nowrap; }

/* ── 主区两列：账户明细（左 62%）+ 守护/任务/告警（右 38%）── */
.main-split { display: grid; grid-template-columns: 62fr 38fr; gap: 16px; align-items: start; }
.main-split.no-accs { grid-template-columns: 1fr; }
.accounts-empty { padding: 0; }
.acc-empty-banner { display: flex; align-items: center; gap: 14px; padding: 20px 24px; }
.acc-empty-icon { font-size: 28px; }
.acc-empty-text { flex: 1; }
.acc-empty-title { font-size: 14px; font-weight: 600; color: var(--t1); }
.acc-empty-sub { font-size: 12px; color: var(--t3); margin-top: 2px; }
.acc-empty-btn { color: var(--ac); font-size: 13px; text-decoration: none; border: 1px solid var(--ac); padding: 6px 18px; border-radius: 6px; white-space: nowrap; }
.side-stack { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.accounts-card { min-width: 0; }
.accounts-table tbody tr { cursor: pointer; }
.accounts-table tbody tr:hover { background: var(--bg3); }
.accounts-table tbody tr.removed-row { opacity: .55; cursor: default; }
.accounts-table tbody tr.removed-row:hover { background: transparent; }
/* 左列表格不裁剪：内容不足保持基线高度（与右列平衡），超出随内容自然长高 */
.acc-scroll { min-height: 560px; }

/* 守护概览 3 格（自动止损/今日放行/巡检覆盖）；水平内边距与其他卡统一 16px */
.guard-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding: 12px 16px; }
.guard-cell {
  display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 10px 6px;
  background: var(--bg3); border: 1px solid var(--bd); border-radius: 8px;
  cursor: pointer; transition: all 0.15s; text-align: center;
}
.guard-cell:hover { border-color: var(--bd2); }
.guard-cell.active { border-color: var(--ac); background: var(--acg); }
.gc-value { font-size: 20px; font-weight: 600; color: var(--t1); font-variant-numeric: tabular-nums; }
.guard-cell.danger .gc-value { color: var(--error); }
.gc-label { font-size: 11px; color: var(--t3); white-space: nowrap; }
.gc-sub { font-size: 10px; color: var(--t3); margin-top: 2px; }
.guard-detail { margin: 0 16px 16px; }
.task-detail { margin: 0 16px 16px; }

/* KPI 汇总小卡（落地页 KPI 行：固定 4 列） */
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.stat-card { background: var(--bg2); border-radius: var(--rs); padding: 14px 16px; display: flex; flex-direction: column; gap: 4px; border: 1px solid var(--bd); position: relative; overflow: hidden; box-shadow: var(--shadow-card); transition: all 0.15s; }
.stat-card.clickable { cursor: pointer; }
.stat-card.clickable:hover { border-color: var(--ac); transform: translateY(-1px); }
.stat-card.active { border-color: var(--ac); background: var(--acg); box-shadow: inset 0 0 0 1px var(--ac); }
.stat-card.active .stat-label { color: var(--ac); }
.stat-card::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; }
/* KPI 卡语义 3 色条：蓝=--ac 中性、绿=正向、橙=警告、红=危险、灰=其余中性 */
.blue::before { background: var(--ac); } .green::before { background: var(--success); } .orange::before { background: var(--warning); }
.red::before { background: var(--error); } .gray::before { background: var(--bd2); }
.stat-label { font-size: 11px; color: var(--t3); white-space: nowrap; }
.stat-value { font-size: 24px; font-weight: 600; color: var(--t1); letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
.stat-sub { font-size: 10px; color: var(--t3); margin-top: -2px; }
.stat-arrow { position: absolute; right: 10px; bottom: 10px; font-size: 14px; color: var(--t3); transition: transform 0.2s; }
.stat-arrow.rotated { transform: rotate(180deg); color: var(--ac); }

/* KPI 明细 */
.kpi-detail-panel { background: var(--bg2); border-radius: var(--rs); border: 1px solid var(--ac); overflow: hidden; box-shadow: var(--shadow-card); animation: slideDown 0.2s ease-out; }
.kpi-detail-panel .table-scroll { max-height: 400px; overflow-y: auto; }
.kpi-detail-panel .detail-header { padding: 12px 16px; border-bottom: 1px solid var(--bd); display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 500; color: var(--t1); }
.kpi-detail-panel .detail-table td { cursor: pointer; }
.kpi-detail-panel .detail-table tbody tr:hover { background: var(--bg3); }
.detail-panel .detail-table tbody tr:hover { background: var(--bg3); }

/* 任务卡（右列 task-list 内单列） */
.task-card {
  display: flex; align-items: flex-start; gap: 12px; padding: 14px 16px;
  background: var(--bg2); border-radius: var(--rs); border: 1px solid var(--bd);
  border-left: 3px solid var(--bd); cursor: pointer; transition: all 0.15s;
  box-shadow: var(--shadow-card); position: relative;
}
.task-card:hover { border-color: var(--bd2); transform: translateY(-1px); }
.task-card.expanded { border-color: var(--ac); border-left-color: var(--ac); background: var(--bg3); }
.task-card.flat { cursor: default; }
.task-card.flat:hover { transform: none; border-color: var(--bd); }
/* kind：左边强调色 + 图标底色 */
.task-card.danger { border-left-color: var(--error); }
.task-card.warn { border-left-color: var(--warning); }
.task-card.info { border-left-color: var(--ac); }
.task-card.ok { border-left-color: var(--success); }
.task-icon-wrap {
  width: 36px; height: 36px; border-radius: 10px; flex-shrink: 0; margin-top: 1px;
  display: flex; align-items: center; justify-content: center;
}
.task-card.danger .task-icon-wrap { background: rgba(255,69,58,0.12); }
.task-card.warn .task-icon-wrap { background: rgba(255,159,10,0.12); }
.task-card.info .task-icon-wrap { background: rgba(10,132,255,0.12); }
.task-card.ok .task-icon-wrap { background: rgba(48,209,88,0.12); }
.task-icon { font-size: 20px; }
.task-card.danger .task-icon { color: var(--error); }
.task-card.warn .task-icon { color: var(--warning); }
.task-card.info .task-icon { color: var(--ac); }
.task-card.ok .task-icon { color: var(--success); }
.task-body { flex: 1; min-width: 0; }
.task-title { font-size: 13.5px; font-weight: 600; color: var(--t1); line-height: 1.3; }
.task-desc {
  font-size: 12px; color: var(--t3); margin-top: 4px; line-height: 1.45;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.task-expand-icon { font-size: 14px; color: var(--t3); flex-shrink: 0; margin-top: 11px; transition: transform 0.2s; }
.task-expand-icon.rotated { transform: rotate(180deg); color: var(--ac); }

/* 明细面板（通用） */
.detail-panel { background: var(--bg2); border-radius: var(--rs); border: 1px solid var(--bd); overflow-x: hidden; overflow-y: auto; max-height: 400px; box-shadow: var(--shadow-card); animation: slideDown 0.2s ease-out; }
@keyframes slideDown { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
.detail-header { padding: 12px 16px; border-bottom: 1px solid var(--bd); display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 500; color: var(--t1); }
.detail-close { cursor: pointer; color: var(--t3); font-size: 18px; }
.detail-close:hover { color: var(--t1); }
/* 平台小标（plat-chip）已收敛到 main.css 全局类 */
.detail-table { width: 100%; border-collapse: collapse; }
.detail-table th { padding: 8px 16px; font-size: 12px; font-weight: 500; color: var(--t3); border-bottom: 1px solid var(--bd); white-space: nowrap; }
.detail-table th.left { text-align: left; } .detail-table th.right { text-align: right; }
.detail-table thead th { position: sticky; top: 0; background: var(--bg2); z-index: 1; }
.detail-table td { padding: 8px 16px; font-size: 13px; border-bottom: 1px solid var(--bd); white-space: nowrap; }
.task-go { flex: none; font-size: 13px; font-weight: 600; color: var(--ac); }
.detail-table td.log-cell { max-width: 260px; white-space: normal; word-break: break-all; }
.detail-table td.left { text-align: left; } .detail-table td.right { text-align: right; }
.detail-table tbody tr:last-child td { border-bottom: none; }
.detail-table tbody tr.selected-row { background: var(--acg); }
.detail-table tbody tr.selected-row td { color: var(--ac); font-weight: 500; }

/* 落地页流量：汇总卡复用 .stat-grid/.stat-card（和广告版 KPI 卡同款）*/
.text-danger { color: var(--error) !important; }
.pill.good { background: rgba(48,209,88,0.1); color: var(--success); }
.pill.waste { background: rgba(255,69,58,0.1); color: var(--error); }
.pill.watch { background: rgba(255,159,10,0.1); color: var(--warning); }
.pill.no_data { background: var(--bg3); color: var(--t3); }
/* 屏蔽分布（纯 CSS 横向条形，不引图表库）*/
.block-detail .block-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; padding: 16px 20px; }
.block-col { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.block-col-title { font-size: 12px; color: var(--t3); margin-bottom: 2px; }
.bar-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.bar-label { width: 96px; color: var(--t2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex-shrink: 0; }
.bar-track { flex: 1; height: 8px; background: var(--bg3); border-radius: 4px; overflow: hidden; min-width: 40px; }
.bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.bar-fill.danger { background: var(--error); }
.bar-val { width: 44px; text-align: right; color: var(--t1); font-family: 'SF Mono', 'Fira Code', monospace; flex-shrink: 0; }

/* 卡片 */
.card { background: var(--bg2); border-radius: var(--rs); border: 1px solid var(--bd); overflow: hidden; box-shadow: var(--shadow-card); }
.card-header { padding: 14px 20px; border-bottom: 1px solid var(--bd); display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; row-gap: 8px; }
.card-title { font-size: 16px; font-weight: 600; color: var(--t1); white-space: nowrap; }

/* 表格工具栏（搜索 + 状态 tab）*/
.table-tools { display: flex; gap: 8px; align-items: center; }
.search-input {
  background: var(--bg3); color: var(--t1); border: 1px solid var(--bd);
  border-radius: var(--rs); padding: 5px 12px; font-size: 13px; width: 180px;
  font-family: var(--font); transition: border-color 0.15s;
}
.search-input:focus { outline: none; border-color: var(--ac); }
.search-input::placeholder { color: var(--t3); }
.status-tabs { display: flex; gap: 2px; }
.status-tab {
  padding: 4px 10px; background: transparent; color: var(--t3);
  border: 1px solid transparent; border-radius: 4px; font-size: 12px;
  cursor: pointer; transition: all 0.15s; white-space: nowrap;
}
.status-tab:hover { color: var(--t1); }
.status-tab.active { background: var(--acg); color: var(--ac); }

/* 表格 */
.table-scroll { overflow-x: auto; }
.acc-table { width: 100%; border-collapse: collapse; min-width: 900px; }
.acc-table th { padding: 10px 12px; font-size: 11px; font-weight: 500; color: var(--t3); border-bottom: 1px solid var(--bd); white-space: nowrap; }
.acc-table th.left { text-align: left; } .acc-table th.right { text-align: right; } .acc-table th.center { text-align: center; }
.acc-table td { padding: 8px 12px; font-size: 13px; border-bottom: 1px solid var(--bd); height: 44px; white-space: nowrap; }
.acc-table td.left { text-align: left; } .acc-table td.right { text-align: right; } .acc-table td.center { text-align: center; }
.acc-table tbody tr { cursor: pointer; transition: background 0.1s; }
.acc-table tbody tr:hover { background: var(--bg3); }
.acc-table tbody tr.removed-row { opacity: .55; cursor: default; }
.acc-table tbody tr.removed-row:hover { background: transparent; }
.acc-name { font-weight: 500; color: var(--t1); font-size: 13px; }
.acc-id { font-size: 10px; color: var(--t3); margin-top: 1px; }
.mono { font-family: 'SF Mono', 'Fira Code', monospace; color: var(--t2); }
.allow-btn { padding: 3px 10px; border: 1px solid var(--bd); background: transparent; color: var(--t2); border-radius: 4px; font-size: 11px; cursor: pointer; white-space: nowrap; }
.allow-btn:hover { color: var(--success); border-color: var(--success); }
.allow-btn.remove:hover { color: var(--error); border-color: var(--error); }
.pill { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 20px; font-size: 11px; white-space: nowrap; }

/* 告警 */
.notif-list { padding: 6px 4px; max-height: 280px; overflow-y: auto; }
.notif-row-wrap { border-bottom: 1px solid var(--bd); }
.notif-row-wrap:last-child { border-bottom: none; }
.notif-row { display: flex; align-items: center; gap: 12px; padding: 14px 20px; cursor: pointer; transition: background 0.1s; }
.notif-row:hover { background: var(--bg3); }
.notif-drawer { padding: 0; }   /* el-drawer body 自带 padding，详情容器不额外加，避免空白 */
.nd-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.nd-level { font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 10px; }
.nd-level.critical { background: rgba(255,69,58,0.15); color: var(--error); }
.nd-level.warning { background: rgba(255,214,10,0.15); color: var(--warning); }
.nd-level.info { background: rgba(10,132,255,0.15); color: var(--ac); }
.nd-event { font-size: 12px; color: var(--t2); font-family: 'SF Mono', monospace; }
.nd-time { font-size: 11px; color: var(--t3); margin-left: auto; }
.nd-body { margin: 4px 0 16px; }   /* 去方框，行式分列 */
.nd-body-row { display: flex; gap: 12px; padding: 10px 4px; font-size: 13px; line-height: 1.5; border-bottom: 1px solid var(--bd); align-items: flex-start; }
.nd-body-key { color: var(--t3); flex-shrink: 0; min-width: 52px; font-weight: 500; }
.nd-body-val { color: var(--t1); word-break: break-word; cursor: pointer; transition: color 0.15s; }
.nd-body-val:hover { color: var(--ac); }
.nd-body-empty { padding: 8px; color: var(--t3); }
.notif-dot { width: 9px; height: 9px; border-radius: 50%; margin-top: 6px; flex-shrink: 0; }
.notif-dot.critical { background: var(--error); }
.notif-dot.warning { background: var(--warning); }
.notif-dot.info { background: var(--ac); }
.notif-content { flex: 1; min-width: 0; }
.notif-text { font-size: 13.5px; color: var(--t1); line-height: 1.45; }
.notif-meta { font-size: 11px; color: var(--t3); margin-top: 5px; }
.ack-btn { padding: 3px 12px; background: var(--acg); color: var(--ac); border: 1px solid var(--ac); border-radius: var(--rs); font-size: 11px; cursor: pointer; flex-shrink: 0; margin-top: 2px; transition: all 0.15s; }
.ack-btn:hover { background: var(--ac); color: #fff; }
.acked-tag { font-size: 11px; color: var(--t3); flex-shrink: 0; margin-top: 4px; }
.notif-row.acked .notif-text { color: var(--t3); }
.notif-row.acked .notif-dot { opacity: 0.4; }
.notif-unread-badge { display: inline-block; min-width: 18px; padding: 0 5px; margin-left: 6px; font-size: 11px; background: var(--error); color: #fff; border-radius: 9px; text-align: center; line-height: 16px; }
.status-tab.ack-all { color: var(--ac); border-color: var(--ac); }
.notif-etype { display: inline-block; font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 4px; margin-right: 6px; vertical-align: middle; }
.notif-etype.critical { background: rgba(255,69,58,.15); color: var(--error); }
.notif-etype.warning { background: rgba(255,159,10,.15); color: var(--warning); }
.notif-etype.info { background: rgba(10,132,255,.15); color: var(--ac); }

.empty { padding: 40px; text-align: center; color: var(--t3); font-size: 14px; }

@media (max-width: 1280px) { .block-detail .block-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 768px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .block-detail .block-grid { grid-template-columns: 1fr; }
  .kpi-core-grid { grid-template-columns: repeat(2, 1fr); }   /* 核心 KPI 2×2 */
  .kpi-strip { grid-template-columns: repeat(2, 1fr); }       /* 细条卡 2×2，分隔线随行重排 */
  .strip-metric:nth-child(odd) { border-left: none; }
  .strip-metric:nth-child(n+3) { border-top: 1px solid var(--bd); }
  .trend-main-canvas { height: 240px; }
  /* 单列重排（堆叠是布局不是折叠）：KPI → 待处理事项 → 趋势 → 账户明细 → 守护 → 告警 */
  .dashboard { display: flex; flex-direction: column; }
  .main-split, .side-stack { display: contents; }
  .kpi-zone { order: 1; }
  .todo-card { order: 2; }
  .trend-main { order: 3; }
  .accounts-card { order: 4; }
  .guard-card { order: 5; }
  .notif-card { order: 6; }
  .card-header .search-input { width: 120px; }
  .ph-title { font-size: 18px; }
}
</style>
