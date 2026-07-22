<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import Chart from 'chart.js/auto'
import { GET, POST, DELETE } from '../api'
import { fmtTime, userTz } from '../composables/useTz'
import { useRouter } from 'vue-router'
import Fuse from 'fuse.js'
import { ElMessage } from 'element-plus'

const router = useRouter()
const loading = ref(true)
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
const spendCanvas = ref(null)
const convCanvas = ref(null)
const cpaCanvas = ref(null)
let _charts = []
const GRAN_OPTS = [
  { value: '5min', label: '5分钟' },
  { value: '30min', label: '30分钟' },
  { value: 'hour', label: '1小时' },
  { value: 'day', label: '按天' },
]
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
    trendData.value = await GET(`/dashboard/trend?${q}${actQ}&granularity=${trendGran.value}`)
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
      const parts = new Intl.DateTimeFormat('zh-CN', {
        timeZone: userTz.value, hour12: false,
        month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
      }).formatToParts(dt)
      const get = (t) => parts.find(p => p.type === t)?.value || ''
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
  mk(spendCanvas.value, '消耗', d.spend, 'rgb(10,132,255)')
  mk(convCanvas.value, '成效', d.conversions, 'rgb(48,209,88)')
  mk(cpaCanvas.value, 'CPA', d.cpa, 'rgb(245,158,11)')
}
watch(trendData, () => nextTick(renderTrendCharts))
watch(trendGran, () => loadTrend())
watch(datePreset, () => {
  const old = trendGran.value
  trendGran.value = autoGran()
  if (trendGran.value === old) loadTrend()  // 粒度没变也要重拉(日期变了)；粒度变则 trendGran watcher 触发
})

// ── 账户搜索（fuse.js 模糊搜索 name + act_id）──
const searchQuery = ref('')
const statusFilter = ref('all') // all / ok / error

const fuse = computed(() => new Fuse(data.value.accounts, {
  keys: ['name', 'act_id'],
  threshold: 0.3,
  ignoreLocation: true,
}))

const filteredAccounts = computed(() => {
  let accs = data.value.accounts
  // 状态筛选
  if (statusFilter.value === 'ok') accs = accs.filter(a => !a.error)
  else if (statusFilter.value === 'error') accs = accs.filter(a => a.error)
  // 模糊搜索
  if (searchQuery.value.trim()) {
    const ids = new Set(fuse.value.search(searchQuery.value).map(r => r.item.act_id))
    accs = accs.filter(a => ids.has(a.act_id))
  }
  return accs
})

const conversionCategory = ref('all')  // ① 转化分类（全部/购物/私信/线索/互动/流量）
const selectedActs = ref([])  // ③ 账户多选（act_id 列表）
const rangeQuery = () => {
  let q = (showCustom.value && customFrom.value && customTo.value)
    ? `date_from=${customFrom.value}&date_to=${customTo.value}`
    : `date_preset=${datePreset.value}`
  if (conversionCategory.value && conversionCategory.value !== 'all') q += `&conversion_category=${conversionCategory.value}`
  if (selectedActs.value.length) q += `&act_ids=${selectedActs.value.map(encodeURIComponent).join(',')}`
  return q
}
const activeTokens = ref(0)
const totalTokens = ref(0)
const lastUpdated = ref('')
const fmtAgo = (iso) => {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前'
  return Math.floor(diff / 3600000) + ' 小时前'
}
const loadDashboard = async (fresh = false) => {
  loading.value = true
  try {
    const [dash, notifs, creds] = await Promise.all([
      GET(`/dashboard?${rangeQuery()}${fresh ? '&fresh=true' : ''}`),
      GET(`/notifications?limit=50`).catch(() => []),
      GET('/fb/credentials').catch(() => []),
    ])
    data.value = dash
    lastUpdated.value = new Date().toISOString()
    recentNotifs.value = notifs
    const allCreds = creds || []
    activeTokens.value = allCreds.filter(c => c.status === 'active').length
    totalTokens.value = allCreds.length
    fetchLanding()
  } catch (e) {
    import('element-plus').then(m => m.ElMessage.error(e.message))
  } finally {
    loading.value = false
  }
}
const refreshData = () => loadDashboard(false)  // 刷新：只读库（跳 30s 缓存），不走 FB
const appLoading = computed(() => loading.value || refreshing.value || landingLoading.value)

// ── 落地页数据（访问/通过/屏蔽/CPC，按子码聚合）──
const landing = ref({ totals: {}, rows: [], block_detail: {} })
// 屏蔽原因 → 中文（对齐 worker evalProtection 的 check 名）
const BLOCK_REASON_ZH = {
  device_block: '设备拦截', required_query: '缺广告参数', country_allow: '地区未放行',
  country_block: '国家拦截', ua_block: 'UA拦截', referer_block: '来源拦截',
  query_block: '参数拦截', datacenter_block: '机房/VPN', frequency: '频次超限', dedup: '重复访客',
  pass: '通过',
}
// 国家码 → 中文（CF 给 2 字母 ISO）
const COUNTRY_ZH = {
  US:'美国',GB:'英国',CA:'加拿大',AU:'澳大利亚',NZ:'新西兰',IE:'爱尔兰',DE:'德国',FR:'法国',
  IT:'意大利',ES:'西班牙',PT:'葡萄牙',NL:'荷兰',BE:'比利时',CH:'瑞士',AT:'奥地利',SE:'瑞典',
  NO:'挪威',DK:'丹麦',FI:'芬兰',PL:'波兰',RU:'俄罗斯',TR:'土耳其',IL:'以色列',AE:'阿联酋',
  SA:'沙特',IN:'印度',ID:'印尼',TH:'泰国',VN:'越南',PH:'菲律宾',MY:'马来西亚',SG:'新加坡',
  JP:'日本',KR:'韩国',CN:'中国',HK:'香港',TW:'台湾',BR:'巴西',MX:'墨西哥',
}
const blockReasonLabel = (k) => BLOCK_REASON_ZH[k] || k
const countryLabel = (k) => { const zh = COUNTRY_ZH[String(k||'').toUpperCase()]; return zh ? `${zh} ${k}` : (k || '-') }
const landingSearch = ref('')
const landingFilter = ref('all')  // all / good / waste / watch
const landingLoading = ref(false)
const fetchLanding = async () => {
  landingLoading.value = true
  try { landing.value = await GET(`/dashboard/landing?${rangeQuery()}`) }
  catch (e) { /* 落地页加载失败不阻断主看板 */ }
  finally { landingLoading.value = false }
}
// 落地页 KPI 卡（可点击展开子码明细，参照广告版 KPI）
const landingKpiExpanded = ref(null)
const landingCards = computed(() => {
  const t = landing.value.totals || {}
  return [
    { label: '访问', value: fmt(t.visits), color: 'blue', mode: 'visits', clickable: true },
    { label: '通过', value: fmt(t.clicks), color: 'green', mode: 'clicks', clickable: true },
    { label: '屏蔽', value: fmt(t.blocked), color: 'red', mode: 'blocked', clickable: (t.blocked || 0) > 0 },
    { label: '通过率', value: fmtPct(t.pass_rate), color: 'cyan', mode: 'pass_rate', clickable: true },
    { label: '屏蔽率', value: fmtPct(t.block_rate), color: 'orange', mode: 'block_rate', clickable: (t.blocked || 0) > 0 },
    { label: '消耗', value: fmtUsd(t.spend_usd), color: 'purple', mode: 'spend', clickable: true },
    { label: '落地CPC', value: t.cpc ? '$'+t.cpc : '—', color: 'teal', mode: 'cpc', clickable: true },
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
  return { mode, title: card.label + ' · 各子码明细', rows }
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
const landingStateLabel = (s) => ({ good: '有效', waste: '空耗', watch: '观察', no_data: '—' }[s] || '—')
const barWidth = (count, arr) => {
  const mx = Math.max(...(arr || []).map(a => a.count), 1)
  return Math.max(4, (count / mx * 100)) + '%'
}

// 格式化
const fmt = (n) => n == null ? '—' : Number(n).toLocaleString()
const fmtUsd = (n) => n == null || n === 0 ? '—' : '$' + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmtPct = (n) => n == null || n === 0 ? '—' : Number(n).toFixed(2) + '%'
const fmtSpendDual = (native, usd, cur) => {
  if (native == null) return { native: '—', usd: '—' }
  if (cur === 'USD') return { native: fmtUsd(native), usd: '' }
  return { native: `${fmt(native)} ${cur}`, usd: `≈ ${fmtUsd(usd)}` }
}
// 计算列（CVR/CPM 前端派生）
const cvr = (acc) => acc.clicks > 0 ? (acc.conversions / acc.clicks * 100) : 0
const cpm = (acc) => acc.impressions > 0 && acc.spend_usd > 0 ? (acc.spend_usd / acc.impressions * 1000) : 0

// 任务卡
const expandedCard = ref(null)
const taskCards = computed(() => {
  const cards = []
  const accs = data.value.accounts
  const names = (arr) => arr.map(a => (a.name || '').slice(0, 15)).join('、')
  const _limited = (a) => a.balance_kind === 'limited' && !a.removed  // 已移除账户不进充值提醒（不可操作）
  const critical = accs.filter(a => _limited(a) && a.balance <= 0)
  if (critical.length) cards.push({ kind: 'danger', icon: 'CircleCloseFilled', title: `充值提醒 · ${critical.length} 个已阻断`, desc: `可用额度为 0：${names(critical)}`, detailAccounts: critical, detailColumns: ['name', 'balance', 'amount_spent_usd', 'spend_cap_usd'] })
  const recharge = accs.filter(a => _limited(a) && a.balance > 0 && a.balance <= 100)
  if (recharge.length) cards.push({ kind: 'warn', icon: 'WarningFilled', title: `建议充值 · ${recharge.length} 个账户`, desc: `可用额度低于 $100：${names(recharge)}`, detailAccounts: recharge, detailColumns: ['name', 'balance', 'amount_spent_usd', 'spend_cap_usd'] })
  if (!critical.length && !recharge.length) {
    const low = accs.filter(a => _limited(a) && a.balance > 100 && a.balance <= 300)
    if (low.length) cards.push({ kind: 'info', icon: 'InfoFilled', title: `额度偏低 · ${low.length} 个账户`, desc: `可用额度低于 $300：${names(low)}`, detailAccounts: low, detailColumns: ['name', 'balance', 'amount_spent_usd', 'spend_cap_usd'] })
  }
  // 真拉取异常（排除已分类的巡检未覆盖/跨时区/无数据）
  const fetchErrors = accs.filter(a => a.error && !a.error.includes('无数据') && !a.error.includes('巡检未覆盖') && !a.error.includes('跨时区'))
  if (fetchErrors.length) cards.push({ kind: 'danger', icon: 'CircleCloseFilled', title: `数据拉取异常 · ${fetchErrors.length} 个账户`, desc: `${names(fetchErrors)}：${fetchErrors[0]?.error || ''}`, detailAccounts: fetchErrors, detailColumns: ['name', 'error'] })
  // 巡检未覆盖（同日但无快照，需关注：可能 token 失效/巡检漏/新账户未跑到）
  const uncovered = accs.filter(a => a.error && a.error.includes('巡检未覆盖'))
  if (uncovered.length) cards.push({ kind: 'warn', icon: 'WarningFilled', title: `巡检未覆盖 · ${uncovered.length} 个账户`, desc: `今日无快照（可能 token 失效/巡检未跑到），点击展开账户列表`, detailAccounts: uncovered, detailColumns: ['name', 'error'] })
  const bleeding = accs.filter(a => !a.error && a.spend_usd > 5 && a.conversions === 0)
  if (bleeding.length) cards.push({ kind: 'warn', icon: 'TrendCharts', title: `空耗预警 · ${bleeding.length} 个账户`, desc: `${names(bleeding)}：花了 ${fmtUsd(bleeding.reduce((s, a) => s + a.spend_usd, 0))} 无转化，点击查看明细`, detailAccounts: bleeding, detailColumns: ['name', 'spend_usd', 'conversions', 'act_id'] })
  if (!cards.length) cards.push({ kind: 'ok', icon: 'CircleCheckFilled', title: '今日任务清爽', desc: '无充值、权限、状态或数据拉取风险', detailAccounts: [], detailColumns: [] })
  return cards.slice(0, 8)
})
const toggleCard = (i) => {
  const card = taskCards.value[i]
  if (!card.detailAccounts?.length) return
  expandedCard.value = expandedCard.value === i ? null : i
}
const columnLabels = { name: '账户', balance: '可用', amount_spent_usd: '已用', spend_cap_usd: '上限', spend_usd: '消耗 (USD)', conversions: '转化', error: '错误' }
// rule_type 英文 → 中文（自动止损明细 col2 中文化）
const RULE_TYPE_LABEL = {
  bleed_abs: '空耗止血', cpa_exceed: 'CPA超标', click_no_conv: '点击无转化',
  low_ctr_no_conv: '低CTR无转化', reach_no_conv: '触达无转化', trend_drop: '趋势下滑',
  budget_burn_fast: '预算猛烧', consecutive_bad: '连续超标',
}
const columnFmt = (col, acc) => {
  if (col === 'name') return acc.name
  if (col === 'balance') return fmtUsd(acc.balance)
  if (col === 'amount_spent_usd') return fmtUsd(acc.amount_spent_usd)
  if (col === 'spend_cap_usd') return fmtUsd(acc.spend_cap_usd)
  if (col === 'spend_usd') return fmtUsd(acc.spend_usd)
  if (col === 'conversions') return fmt(acc.conversions)
  if (col === 'error') return acc.error
  return acc[col]
}

// KPI 明细内搜索
const detailSearch = ref('')
const filteredKpiAccs = computed(() => {
  if (!kpiDetail.value || kpiDetail.value.type !== 'accounts') return []
  let accs = kpiDetail.value.accs
  // 余额/充值视图排除已移除账户（不可操作）；消耗/性能视图保留（历史数据要看）
  if (kpiDetail.value.mode === 'balance') accs = accs.filter(a => !a.removed)
  if (detailSearch.value.trim()) {
    const fuseAcc = new Fuse(accs, { keys: ['name', 'act_id'], threshold: 0.3 })
    accs = fuseAcc.search(detailSearch.value).map(r => r.item)
  }
  return accs
})

// 强制刷新（采集最新 FB 数据 + 巡检，跳过冷却）
const forceRefresh = async () => {
  refreshing.value = true
  try {
    await POST('/guard/inspect?force=true')
    ElMessage.success('数据已刷新')
    await loadDashboard()
    loadTrend()
  } catch (e) {
    ElMessage.error('刷新失败：' + e.message)
  } finally {
    refreshing.value = false
  }
}

// KPI 卡点击展开
const kpiExpanded = ref(null)
const cards = computed(() => [
  { label: '总消耗 (USD)', value: fmtUsd(data.value.total_spend), color: 'blue', mode: 'spend', clickable: true },
  { label: '总转化', value: fmt(data.value.total_conversions), color: 'green', mode: 'conv', clickable: true },
  { label: '平均 CPA', value: fmtUsd(data.value.total_cpa), color: 'orange', mode: 'cpa', clickable: true },
  { label: '平均 ROAS', value: data.value.total_roas ? data.value.total_roas + '×' : '—', color: 'purple', mode: 'roas', clickable: true },
  { label: '自动止损', value: fmt(data.value.pause_count), color: 'red', mode: 'pause', clickable: data.value.pause_count > 0 },
  { label: '今日放行', value: fmt(data.value.allowance_count), color: 'cyan', mode: 'allowance', clickable: data.value.allowance_count > 0 },
  { label: '可用额度 (USD)', value: fmtUsd(data.value.total_balance), color: 'teal', mode: 'balance', clickable: true },
  { label: '巡检覆盖', value: `${(data.value.accounts || []).filter(a => !a.error || (a.error && a.error.includes('跨时区'))).length}/${(data.value.accounts || []).length}`, sub: `令牌 ${activeTokens.value}可用·${totalTokens.value - activeTokens.value}停用`, color: 'indigo', mode: 'coverage', clickable: true },
])
const kpiDetail = computed(() => {
  if (kpiExpanded.value === null) return null
  const card = cards.value[kpiExpanded.value]
  if (!card?.clickable) return null
  const mode = card.mode

  // 止损明细：从 pause_details 构建（不是 accounts）
  if (mode === 'pause') {
    const logs = data.value.pause_details || []
    return {
      mode, title: card.label + ' · 明细',
      type: 'logs',
      logs: logs.map(l => ({
        col1: l.target_id || '—',
        col2: RULE_TYPE_LABEL[l.trigger_type] || l.trigger_type || '—',
        col3: l.detail || '',
        col4: fmtTime(l.time),
        act_id: l.act_id || '',
        ad_id: l.target_id || '',
      })),
      headers: ['广告 ID', '触发规则', '详情', '时间'],
    }
  }
  // 放行明细
  if (mode === 'allowance') {
    const logs = data.value.allowance_details || []
    return {
      mode, title: card.label + ' · 明细',
      type: 'logs',
      logs: logs.map(l => ({
        col1: l.account_name || l.act_id || '—',
        col2: l.act_id || '—',
        col3: l.ad_id || '—',
        col4: l.is_cross_tz ? `跨时区（${l.allowance_date}）` : '生效中',
        act_id: l.act_id || '',
        ad_id: l.ad_id || '',
      })),
      headers: ['账户', '账户 ID', '广告 ID', '状态'],
    }
  }

  if (mode === 'coverage') {
    const statusOrder = (a) => (a.error && a.error.includes('巡检未覆盖')) ? 0 : (a.error ? 1 : 2)  // 巡检未覆盖在上（紧急）→跨时区→可巡检
    const accs = [...(data.value.accounts || [])].sort((a, b) => statusOrder(a) - statusOrder(b) || (a.name || '').localeCompare(b.name || ''))
    return {
      mode, title: '巡检覆盖 · 账户明细', type: 'accounts', accs,
      cols: [
        { key: 'name', label: '账户', left: true },
        { key: 'tz', label: '本地时间', fmt: (v, a) => (a.error && a.error.includes('跨时区') ? '🕐 ' : '') + localTime(a.timezone) + ' ' + tzOffset(a.timezone) },
        { key: 'cov', label: '巡检状态', fmt: (v, a) => (a.error && a.error.includes('巡检未覆盖')) ? '❌ 巡检未覆盖' : '✅ 可巡检' },
      ],
    }
  }
  // 账户明细模式（spend/conv/cpa/roas/balance；balance 不 filter——余额是账户属性不依赖快照）
  let accs = mode === 'balance' ? [...data.value.accounts] : data.value.accounts.filter(a => !a.error)
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
  let cols = mode === 'balance'
    ? [{ key: 'name', label: '账户', left: true }, { key: 'balance', label: '可用', fmt: (v, a) => a.balance_kind === 'limited' ? fmtUsd(v) : '不限' }, { key: 'amount_spent_usd', label: '已用', fmt: fmtUsd }, { key: 'spend_cap_usd', label: '上限', fmt: fmtUsd }, { key: 'urgency', label: '紧急度', fmt: (v, a) => urgencyLabel(a) }]
    : [
        { key: 'name', label: '账户', left: true, bold: mode === 'spend' },
        { key: 'spend_dual', label: '消耗', fmt: (v, a) => fmtSpendDual(a.spend, a.spend_usd, a.currency).native, bold: mode === 'spend' },
        { key: 'spend_usd', label: 'USD', fmt: fmtUsd, bold: mode === 'spend' },
        { key: 'conversions', label: '转化', fmt: fmt, bold: mode === 'conv' },
        { key: 'cpa', label: 'CPA', fmt: fmtUsd, bold: mode === 'cpa' },
        { key: 'roas', label: 'ROAS', fmt: (v) => v ? v + '×' : '—', bold: mode === 'roas' },
      ]
  return { mode, accs, cols, title: card.label + ' · 各账户明细', type: 'accounts' }
})
const toggleKpi = (i) => {
  if (!cards.value[i]?.clickable) return
  if (kpiExpanded.value === i) {
    kpiExpanded.value = null
  } else {
    detailSearch.value = ''  // 切换卡片时清空搜索
    kpiExpanded.value = i
  }
}

const notifIcon = (level) => level === 'critical' ? '🔴' : level === 'warning' ? '🟡' : '🔵'
const goNotif = (n) => {
  if (n.trace_id) router.push({ path: '/guard', query: { trace_id: n.trace_id } })
  else router.push('/guard')
}
// 告警详情改用抽屉（el-drawer）展示——彻底避开 sticky 顶条遮挡（之前 inline 展开被顶部条挡）
const notifDrawerOpen = ref(false)
const activeNotif = ref(null)
const openNotifDrawer = (n) => {
  activeNotif.value = n
  notifDrawerOpen.value = true
}
// 从告警 body 解析某 key 的值（"账户：xxx（ID yyy）"→"xxx（ID yyy）"），供抽屉标题/突出展示
const notifField = (key) => {
  const n = activeNotif.value
  if (!n || !n.body) return ''
  const row = parseBody(n.body).find(r => r.key === key)
  return row ? row.val : ''
}
// 抽屉标题：动作 + 具体账户 + 广告（让用户一眼看到哪个账户哪个广告出问题、采取了什么动作）
const notifTitle = computed(() => activeNotif.value?.title || '告警详情')
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
  navigator.clipboard?.writeText(copy).then(() => ElMessage.success('已复制: ' + copy)).catch(() => {})
}
// 充值紧急度（4 档 + 建议，对齐 taskCards 阈值）
const urgencyLabel = (a) => {
  if (a.removed) return '— 已移除'
  if (a.balance_kind !== 'limited') return '🟢 不限'
  const b = a.balance || 0
  if (b <= 0) return '🔴 已阻断（立即充值）'
  if (b <= 100) return '🟠 紧急（尽快充值）'
  if (b <= 300) return '🟡 偏低（建议充值）'
  return '🟢 充足'
}
// 账户当前本地时间（用 timezone_name + Intl 算，对齐北京参考）
const copyIds = (accounts, label) => {
  const ids = (accounts || []).map(a => a.act_id).filter(Boolean).join('\n')
  if (!ids) { ElMessage.info('无可复制的 ID'); return }
  navigator.clipboard?.writeText(ids).then(() => ElMessage.success(`已复制 ${accounts.length} 个${label || 'ID'}`)).catch(() => {})
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
  if (!ids) { ElMessage.info('未勾选任何账户'); return }
  navigator.clipboard?.writeText(ids).then(() => ElMessage.success(`已复制 ${selectedIds.value.size} 个选中 ID`)).catch(() => {})
}
const localTime = (tz) => {
  if (!tz) return '—'
  try { return new Intl.DateTimeFormat('zh-CN', { timeZone: tz, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date()) }
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
  ElMessage.success('已确认')
  try {
    await POST('/notifications/read', { ids: [id] })
  } catch (e) {
    if (n) n.read = false  // 回滚
    ElMessage.error('确认失败：' + e.message)
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
    ElMessage.success('全部已读')
  } catch (e) { ElMessage.error('操作失败：' + (e.message || '')) }
}
const NOTIF_EVENT_LABEL = {
  rule_pause: '止损', coverage_lost: '覆盖丢失', account_permission_error: '权限',
  token_expired: '令牌失效', token_invalid: '令牌失效', token_expiring: '令牌将过期',
  token_rate_limited: '限流', orphan_account: '失联', inspection_stalled: '巡检停滞',
  budget_progress_50: '预算', budget_progress_75: '预算', budget_progress_90: '预算', budget_progress_98: '预算',
  account_status_change: '状态变更', sentinel_pause: '哨兵', landing_blocked: '落地页封禁',
}
const notifEventLabel = (et) => NOTIF_EVENT_LABEL[et] || ''

// 自定义日期
const showCustom = ref(false)
const customFrom = ref('')
const customTo = ref('')
const applyCustom = () => {
  if (!customFrom.value || !customTo.value) return
  loadDashboard()  // showCustom=true，rangeQuery 自动用 custom 范围
}

const dateOptions = [
  { label: '今日', value: 'today' },
  { label: '昨日', value: 'yesterday' },
  { label: '近2天', value: 'last_2d' },
  { label: '近7天', value: 'last_7d' },
  { label: '近30天', value: 'last_30d' },
]

// ── 下次巡检倒计时（前端三态机，随时间自动切换）──
// 巡检状态：用后端 inspection_heartbeat（action_logs）判断是否在跑。
// last_synced = 最近快照写入时间（有活跃广告才有新快照，0 广告时不更新≠巡检停了）。
// 心跳每 5min 写一条 → 有心跳=巡检正常（不管有没有快照/广告）。
const INSPECT_INTERVAL_MS = 5 * 60 * 1000
const parseSynced = (s) => {
  if (!s) return null
  let iso = String(s).replace(' ', 'T').split('.')[0]
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso)) iso += 'Z'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? null : d
}
const nextInspectionAt = computed(() => {
  const d = parseSynced(data.value.last_synced)
  return d ? new Date(d.getTime() + INSPECT_INTERVAL_MS) : null
})
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
  const times = accs.map(a => a.last_inspected_at).filter(Boolean).map(t => new Date(t.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(t) ? t : t + 'Z').getTime()).filter(n => !isNaN(n))
  if (!times.length) return ''
  const latest = new Date(Math.max(...times))
  return fmtTime(latest.toISOString())
})
const updateCountdown = () => {
  const state = inspectState.value
  if (state === 'idle') { countdown.value = '等待首次巡检'; return }
  if (state === 'running') { countdown.value = '巡检正常'; return }
  const hb = data.value.last_heartbeat
  const hbT = hb && new Date(hb.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(hb) ? hb : hb + 'Z').getTime()
  if (state === 'waiting' && hbT) {
    const ms = (hbT + INSPECT_INTERVAL_MS) - Date.now()
    if (ms > 0) { const m = Math.floor(ms / 60000); const s = Math.floor((ms % 60000) / 1000); countdown.value = `下次巡检 ${m}分${s}秒`; return }
  }
  if (state === 'stalled' && hbT) {
    const min = Math.floor((Date.now() - hbT) / 60000)
    countdown.value = `巡检停滞 · ${min}min`
    return
  }
  countdown.value = ''
}

// 分区锚点（上下分区 + sticky 顶栏跳转 + 滚动高亮当前区）
const activeSection = ref('ads')
let _anchorLock = false  // 点击跳转期间锁住高亮，防 smooth 滚动途中 observer 抢回
const scrollToSection = (id) => {
  activeSection.value = id  // 点击即高亮（用户明确意图，不等 observer）
  _anchorLock = true
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  setTimeout(() => { _anchorLock = false }, 800)
}
let _timer = null
let _refreshTimer = null
let _sectionObserver = null
const addAllowance = async (log) => {
  if (!log.act_id || !log.ad_id) return ElMessage.warning('缺少账户/广告 ID')
  try {
    await POST('/guard/allowance', { act_id: log.act_id, ad_id: log.ad_id })
    ElMessage.success('已放行，今日不再止损该广告')
    await loadDashboard(true)
    loadTrend()
    kpiExpanded.value = null
  } catch (e) { ElMessage.error('放行失败：' + (e.message || '')) }
}
const removeAllowance = async (log) => {
  try {
    await DELETE(`/guard/allowance?act_id=${log.act_id}&ad_id=${log.ad_id}`)
    ElMessage.success('已解除放行')
    await loadDashboard(true)
    loadTrend()
    kpiExpanded.value = null
  } catch (e) { ElMessage.error('解除失败：' + (e.message || '')) }
}

onMounted(() => {
  loadDashboard()
  loadTrend()
  updateCountdown()
  _timer = setInterval(updateCountdown, 1000)
  _refreshTimer = setInterval(() => {
    if (document.hidden) return
    // 用户正在操作（展开明细/勾选账户）时跳过自动刷新，避免打断
    if (selectedIds.value.size > 0 || kpiExpanded.value !== null || expandedCard.value !== null || landingKpiExpanded.value !== null) return
    loadDashboard()
  }, 60000)
  const obs = new IntersectionObserver((entries) => {
    // 锁定期间不抢高亮（点击跳转的 smooth 滚动中）；松开后才跟手动滚动
    if (_anchorLock) return
    entries.forEach(e => { if (e.isIntersecting) activeSection.value = e.target.id })
  }, { rootMargin: '-30% 0px -60% 0px', threshold: 0 })
  ;['ads', 'landing'].forEach(id => { const el = document.getElementById(id); if (el) obs.observe(el) })
  _sectionObserver = obs
})
onUnmounted(() => { if (_timer) clearInterval(_timer); if (_refreshTimer) clearInterval(_refreshTimer); if (_sectionObserver) _sectionObserver.disconnect(); _charts.forEach(c => c?.destroy()) })
</script>

<template>
  <div class="dashboard">
    <div class="top-loader" :class="{ active: appLoading }"><div class="top-loader-bar"></div></div>

    <div class="sticky-top">
    <div class="date-bar">
        <button v-for="opt in dateOptions" :key="opt.value" class="date-btn" :class="{ active: datePreset === opt.value && !showCustom }"
                @click="showCustom = false; datePreset = opt.value; loadDashboard()">{{ opt.label }}</button>
        <button class="date-btn" :class="{ active: showCustom }" @click="showCustom = !showCustom">自定义</button>
        <div v-if="showCustom" class="custom-range">
          <input type="date" v-model="customFrom" class="date-input" /><span class="date-sep">—</span>
          <input type="date" v-model="customTo" class="date-input" />
          <button class="date-btn apply" @click="applyCustom">查询</button>
        </div>
        <el-select v-model="conversionCategory" @change="loadDashboard()" size="small" class="filter-select"
                   title="转化分类筛选（只统计符合 KPI 类型的广告）">
          <el-option value="all" label="全部成效" />
          <el-option value="shopping" label="购物" />
          <el-option value="messaging" label="私信" />
          <el-option value="leads" label="线索" />
          <el-option value="engagement" label="互动" />
          <el-option value="traffic" label="流量" />
        </el-select>
        <el-select v-model="selectedActs" multiple filterable collapse-tags collapse-tags-tooltip clearable
                   @change="loadDashboard()" size="small" class="filter-select act-filter"
                   placeholder="全部账户" title="账户筛选（多选，模糊搜索）">
          <el-option v-for="a in (data.accounts || [])" :key="a.act_id" :value="a.act_id" :label="a.name" />
        </el-select>
        <div class="sys-info">
          <span v-if="lastUpdated" class="sync-time">数据更新 {{ fmtAgo(lastUpdated) }}</span>
          <span v-if="lastInspectedDisplay" class="sync-time">上次巡检 {{ lastInspectedDisplay }}</span>
          <span class="sync-time countdown" :class="inspectState">{{ countdown }}</span>
          <button class="refresh-btn" :disabled="loading" @click="refreshData">{{ loading ? '刷新中' : '刷新' }}</button>
          <button class="refresh-btn primary" :disabled="refreshing" @click="forceRefresh">{{ refreshing ? '采集中…' : '立即采集' }}</button>
        </div>
      </div>
    <div class="anchor-strip">
      <button class="anchor-btn" :class="{ active: activeSection === 'ads' }" @click="scrollToSection('ads')">广告数据</button>
      <button class="anchor-btn" :class="{ active: activeSection === 'landing' }" @click="scrollToSection('landing')">落地页数据</button>
    </div>
    </div>

    <section id="ads" class="dash-section ads">
      <div class="dash-head"><span class="dash-title">广告数据</span><span class="dash-sub">消耗 · 转化 · 守护</span></div>
      <div class="stat-grid" v-loading="loading">
        <div v-for="(card, i) in cards" :key="i" class="stat-card" :class="[card.color, { clickable: card.clickable, active: kpiExpanded === i }]" @click="toggleKpi(i)">
          <span class="stat-label">{{ card.label }}</span>
          <span class="stat-value">{{ card.value }}</span>
          <span v-if="card.sub" class="stat-sub">{{ card.sub }}</span>
          <el-icon v-if="card.clickable" class="stat-arrow" :class="{ rotated: kpiExpanded === i }"><ArrowDown /></el-icon>
        </div>
      </div>
      <div v-if="kpiDetail" class="kpi-detail-panel">
        <div class="detail-header">
          <span>{{ kpiDetail.title }}</span>
          <div class="detail-tools">
            <input v-if="kpiDetail.type === 'accounts'" v-model="detailSearch" class="detail-search" placeholder="搜索..." />
            <button v-if="kpiDetail.mode === 'spend'" class="copy-ids-btn" @click="copyIds(filteredKpiAccs.filter(a => (a.spend_usd || 0) > 0), '有消耗 ID')">复制有消耗 ID</button>
            <button v-if="kpiDetail.mode === 'balance'" class="copy-ids-btn" @click="copySelected()">复制选中 ({{ selectedIds.size }})</button>
            <el-icon class="detail-close" @click="kpiExpanded = null"><Close /></el-icon>
          </div>
        </div>
        <div v-if="kpiDetail.type === 'accounts'" class="table-scroll">
          <table class="detail-table">
            <thead><tr><th v-for="col in kpiDetail.cols" :key="col.key" :class="col.left ? 'left' : 'right'">{{ col.label }}</th></tr></thead>
            <tbody>
              <tr v-for="acc in filteredKpiAccs" :key="acc.act_id" :class="{ 'selected-row': selectedIds.has(acc.act_id), 'removed-row': acc.removed }" @click="acc.removed ? null : (kpiDetail.mode === 'balance' ? toggleSelect(acc.act_id) : router.push({ name: 'ad-manager', query: { act: acc.act_id } }))">
                <td v-for="col in kpiDetail.cols" :key="col.key" :class="col.left ? 'left' : 'right'" class="mono" :style="{ fontWeight: col.bold ? 600 : 400 }">
                  <template v-if="col.key === 'name'">{{ acc.removed ? `（已移除）${acc.act_id}` : acc.name }}</template>
                  <template v-else>{{ col.fmt(acc[col.key], acc) }}</template>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="!filteredKpiAccs.length" class="empty">未找到匹配</div>
        </div>
        <div v-else class="table-scroll">
          <table class="detail-table">
            <thead><tr>
              <th v-for="(h, i) in kpiDetail.headers" :key="i" :class="i === 0 ? 'left' : 'right'">{{ h }}</th>
              <th v-if="['pause','allowance'].includes(kpiDetail.mode)" class="right">操作</th>
            </tr></thead>
            <tbody>
              <tr v-for="(log, i) in kpiDetail.logs" :key="i">
                <td class="left mono">{{ log.col1 }}</td>
                <td v-for="j in kpiDetail.headers.length - 1" :key="j" class="right mono">{{ log['col' + (j + 1)] }}</td>
                <td v-if="kpiDetail.mode === 'pause'" class="right"><button class="allow-btn" @click="addAllowance(log)">今日放行</button></td>
                <td v-if="kpiDetail.mode === 'allowance'" class="right"><button class="allow-btn remove" @click="removeAllowance(log)">解除放行</button></td>
              </tr>
            </tbody>
          </table>
          <div v-if="!kpiDetail.logs.length" class="empty">暂无记录</div>
        </div>
      </div>
      <div class="trend-section">
        <div class="trend-bar">
          <span class="trend-title">趋势</span>
          <div class="trend-presets">
            <button v-for="o in GRAN_OPTS" :key="o.value" class="tp-btn" :class="{on:trendGran===o.value}" @click="trendGran=o.value">{{ o.label }}</button>
          </div>
        </div>
        <div class="trend-grid" v-if="trendData.labels?.length">
          <div class="trend-card"><div class="tc-label">消耗 $</div><div class="tc-canvas"><canvas ref="spendCanvas"></canvas></div></div>
          <div class="trend-card"><div class="tc-label">成效</div><div class="tc-canvas"><canvas ref="convCanvas"></canvas></div></div>
          <div class="trend-card"><div class="tc-label">CPA $</div><div class="tc-canvas"><canvas ref="cpaCanvas"></canvas></div></div>
        </div>
        <div v-else class="trend-empty">所选范围暂无数据</div>
      </div>
      <div v-show="!loading" class="task-block">
        <div class="block-title">待处理事项</div>
        <div class="task-grid">
          <div v-for="(card, i) in taskCards" :key="i" class="task-card" :class="[card.kind, { expanded: expandedCard === i, flat: !card.detailAccounts?.length }]" @click="toggleCard(i)">
            <div class="task-icon-wrap"><el-icon class="task-icon"><component :is="card.icon" /></el-icon></div>
            <div class="task-body"><div class="task-title">{{ card.title }}</div><div class="task-desc">{{ card.desc }}</div></div>
            <el-icon v-if="card.detailAccounts?.length" class="task-expand-icon" :class="{ rotated: expandedCard === i }"><ArrowDown /></el-icon>
          </div>
        </div>
        <div v-if="expandedCard !== null && taskCards[expandedCard]?.detailAccounts?.length" class="detail-panel">
          <div class="detail-header"><span>{{ taskCards[expandedCard].title }} · 明细</span><div class="detail-tools"><button class="copy-ids-btn" @click="copySelected()">复制选中 ({{ selectedIds.size }})</button><el-icon class="detail-close" @click="expandedCard = null"><Close /></el-icon></div></div>
          <table class="detail-table">
            <thead><tr><th v-for="col in taskCards[expandedCard].detailColumns" :key="col" :class="col === 'name' ? 'left' : 'right'">{{ columnLabels[col] }}</th></tr></thead>
            <tbody>
              <tr v-for="acc in taskCards[expandedCard].detailAccounts" :key="acc.act_id" :class="{ 'selected-row': selectedIds.has(acc.act_id) }" @click="toggleSelect(acc.act_id)">
                <td v-for="col in taskCards[expandedCard].detailColumns" :key="col" :class="col === 'name' ? 'left' : 'right'" class="mono">{{ columnFmt(col, acc) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="card notif-card">
        <div class="card-header">
          <span class="card-title">最近告警 <span v-if="unreadNotifCount" class="notif-unread-badge">{{ unreadNotifCount }}</span></span>
          <div class="status-tabs">
            <button class="status-tab" :class="{ active: notifFilter === 'all' }" @click="notifFilter = 'all'">全部</button>
            <button class="status-tab" :class="{ active: notifFilter === 'critical' }" @click="notifFilter = 'critical'">严重</button>
            <button class="status-tab" :class="{ active: notifFilter === 'warning' }" @click="notifFilter = 'warning'">警告</button>
            <button class="status-tab" :class="{ active: notifFilter === 'info' }" @click="notifFilter = 'info'">信息</button>
            <button v-if="unreadNotifCount" class="status-tab ack-all" @click="ackAllNotifs">全部已读</button>
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
              <button v-if="!n.read" class="ack-btn" @click.stop="ackNotif(n.id)">确认</button>
              <span v-else class="acked-tag">已确认</span>
            </div>
          </div>
          <div v-if="!filteredNotifs.length" class="empty">{{ notifFilter === 'all' ? '暂无告警' : '无该级别告警' }}</div>
        </div>
      </div>
    </section>

    <el-drawer v-model="notifDrawerOpen" :title="notifTitle" direction="rtl" size="480px" :destroy-on-close="true">
      <div v-if="activeNotif" class="notif-drawer">
        <div class="nd-head">
          <span class="nd-level" :class="activeNotif.level">{{ ({critical:'严重',warning:'警告',info:'信息'})[activeNotif.level] || activeNotif.level }}</span>
          <span v-if="activeNotif.event_type" class="nd-event">{{ ({rule_pause:'自动止损',account_permission_error:'权限不足',token_expired:'令牌失效',token_rate_limited:'令牌限流',orphan_account:'账户失联',inspection_stalled:'巡检停滞',coverage_lost:'覆盖丢失',budget_progress_50:'预算进度',budget_progress_75:'预算进度',budget_progress_90:'预算进度',budget_progress_98:'预算进度',account_status_change:'账户状态变更',sentinel_pause:'哨兵暂停'})[activeNotif.event_type] || activeNotif.event_type }}</span>
          <span class="nd-time">{{ fmtTime(activeNotif.created_at) }}</span>
        </div>
        <div class="nd-body">
          <div v-for="(row, i) in parseBody(activeNotif.body)" :key="i" class="nd-body-row">
            <span v-if="row.key" class="nd-body-key">{{ row.key }}</span>
            <span class="nd-body-val" @click="copyText(row.val)" title="点击复制">{{ row.val }}</span>
          </div>
          <div v-if="!activeNotif.body" class="nd-body-empty">（无详情内容）</div>
        </div>
      </div>
    </el-drawer>

    <section id="landing" class="dash-section landing">
      <div class="dash-head"><span class="dash-title">落地页数据</span><span class="dash-sub">访问 · 通过 · 屏蔽</span></div>
      <div v-if="landing.totals && landing.totals.visits != null" class="stat-grid">
        <div v-for="(card, i) in landingCards" :key="i" class="stat-card" :class="[card.color, { clickable: card.clickable, active: landingKpiExpanded === i }]" @click="toggleLandingKpi(i)">
          <span class="stat-label">{{ card.label }}</span>
          <span class="stat-value">{{ card.value }}</span>
          <span v-if="card.sub" class="stat-sub">{{ card.sub }}</span>
          <el-icon v-if="card.clickable" class="stat-arrow" :class="{ rotated: landingKpiExpanded === i }"><ArrowDown /></el-icon>
        </div>
      </div>
      <div v-if="landingKpiDetail" class="kpi-detail-panel">
        <div class="detail-header">
          <span>{{ landingKpiDetail.title }}</span>
          <div class="detail-tools">
            <el-icon class="detail-close" @click="landingKpiExpanded = null"><Close /></el-icon>
          </div>
        </div>
        <div class="table-scroll">
          <table class="detail-table">
            <thead><tr>
              <th class="left">子码</th><th class="left">域名</th>
              <th class="right">访问</th><th class="right">通过</th><th class="right">屏蔽</th>
              <th class="right">消耗</th><th class="right">CPC</th><th class="center">状态</th>
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
        <div v-if="!landingKpiDetail.rows.length" class="empty">暂无子码数据</div>
      </div>
      <div class="trend-placeholder"><el-icon><TrendCharts /></el-icon><span>访问 / 屏蔽 趋势折线 · 即将上线</span></div>
      <div class="card" v-loading="landingLoading">
        <div class="card-header">
          <span class="card-title">子码表现</span>
          <div class="table-tools">
            <input v-model="landingSearch" class="search-input" placeholder="搜索子码 / 广告ID / 域名..." />
            <div class="status-tabs">
              <button class="status-tab" :class="{ active: landingFilter === 'all' }" @click="landingFilter = 'all'">全部 {{ (landing.rows || []).length }}</button>
              <button class="status-tab" :class="{ active: landingFilter === 'good' }" @click="landingFilter = 'good'">有效</button>
              <button class="status-tab" :class="{ active: landingFilter === 'waste' }" @click="landingFilter = 'waste'">空耗</button>
              <button class="status-tab" :class="{ active: landingFilter === 'watch' }" @click="landingFilter = 'watch'">观察</button>
            </div>
          </div>
        </div>
        <div class="table-scroll">
          <table class="acc-table">
            <thead><tr>
              <th class="left">子码</th><th class="left">账户</th><th class="left">域名</th>
              <th class="right">访问</th><th class="right">通过</th><th class="right">屏蔽</th>
              <th class="right">通过率</th><th class="right">消耗</th><th class="right">CPC</th><th class="right">CVR</th><th class="center">状态</th>
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
        <div v-if="!filteredLanding.length" class="empty">暂无落地页访问数据</div>
      </div>
      <div v-if="landing.totals && landing.totals.blocked > 0" class="card block-detail">
        <div class="card-header"><span class="card-title">屏蔽分布</span></div>
        <div class="block-grid">
          <div class="block-col">
            <div class="block-col-title">按原因</div>
            <div v-for="b in (landing.block_detail.by_reason || [])" :key="'r' + b.key" class="bar-row">
              <span class="bar-label" :title="b.key">{{ blockReasonLabel(b.key) }}</span>
              <div class="bar-track"><div class="bar-fill danger" :style="{ width: barWidth(b.count, landing.block_detail.by_reason) }"></div></div>
              <span class="bar-val">{{ b.count }}</span>
            </div>
          </div>
          <div class="block-col">
            <div class="block-col-title">按国家 Top8</div>
            <div v-for="b in (landing.block_detail.by_country || [])" :key="'c' + b.key" class="bar-row">
              <span class="bar-label" :title="b.key">{{ countryLabel(b.key) }}</span>
              <div class="bar-track"><div class="bar-fill danger" :style="{ width: barWidth(b.count, landing.block_detail.by_country) }"></div></div>
              <span class="bar-val">{{ b.count }}</span>
            </div>
          </div>
          <div class="block-col">
            <div class="block-col-title">按平台</div>
            <div v-for="b in (landing.block_detail.by_platform || [])" :key="'p' + b.key" class="bar-row">
              <span class="bar-label" :title="b.key">{{ b.key }}</span>
              <div class="bar-track"><div class="bar-fill danger" :style="{ width: barWidth(b.count, landing.block_detail.by_platform) }"></div></div>
              <span class="bar-val">{{ b.count }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dashboard { display: block; }
.dashboard > * + * { margin-top: 16px; }

/* 日期栏 + 锚点（合并 sticky 容器，贴 topbar 下；margin:0 和板块同宽对齐）*/
.sticky-top { position: sticky; top: -24px; z-index: 100; background: var(--bg); padding: 12px 0 0; margin: 0; border-bottom: 1px solid var(--bd); }
.anchor-strip { display: flex; gap: 4px; padding: 8px 0 10px; }
.anchor-btn { padding: 5px 16px; background: transparent; color: var(--t3); border: 1px solid transparent; border-radius: var(--rs); font-size: 13px; cursor: pointer; transition: all 0.15s; }
.anchor-btn:hover { color: var(--t1); background: var(--bg2); }
.anchor-btn.active { background: var(--ac); color: #fff; }

/* 分区容器（广告版/落地页版，各自独立卡片组）*/
.dash-section { background: var(--bg2); border: 1px solid var(--bd); border-radius: 14px; padding: 20px 24px; display: flex; flex-direction: column; gap: 14px; scroll-margin-top: 160px; box-shadow: var(--shadow-card); }
.dash-head { display: flex; align-items: baseline; gap: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--bd); }
.dash-title { font-size: 18px; font-weight: 600; color: var(--t1); display: flex; align-items: center; gap: 10px; }
.dash-title::before { content: ''; width: 4px; height: 18px; border-radius: 2px; background: var(--ac); }
.dash-section.landing .dash-title::before { background: var(--success); }
.dash-sub { font-size: 12px; color: var(--t3); }

/* 趋势占位（第二批填充）*/
.trend-placeholder { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 28px; background: var(--bg3); border: 1px dashed var(--bd2, var(--bd)); border-radius: var(--rs); color: var(--t3); font-size: 13px; }
.trend-placeholder .el-icon { font-size: 20px; color: var(--ac); }
.trend-section { margin-bottom: 14px; }
.trend-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.trend-title { font-size: 13px; font-weight: 600; color: var(--t1); }
.trend-presets { display: flex; gap: 4px; }
.tp-btn { padding: 3px 10px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t3); border-radius: 4px; font-size: 11px; cursor: pointer; }
.tp-btn.on { background: var(--acg); color: var(--ac); border-color: var(--ac); }
.trend-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
@media (max-width: 768px) { .trend-grid { grid-template-columns: 1fr; } }
.trend-card { background: var(--bg2); border: 1px solid var(--bd); border-radius: 8px; padding: 10px; }
.tc-label { font-size: 11px; color: var(--t3); margin-bottom: 4px; }
.tc-canvas { height: 120px; }
.trend-empty { text-align: center; color: var(--t3); padding: 24px; font-size: 13px; background: var(--bg2); border: 1px dashed var(--bd); border-radius: 8px; }
.trend-chart { display: flex; align-items: center; gap: 10px; padding: 10px 16px; background: var(--bg2); border: 1px solid var(--bd); border-radius: 8px; margin-bottom: 12px; }
.trend-label { font-size: 11px; color: var(--t3); white-space: nowrap; }
.sparkline { flex: 1; height: 28px; }

/* 分区内子块标题（区别于分区大标题）*/
.block-title { font-size: 14px; font-weight: 600; color: var(--t1); }
.task-block { display: flex; flex-direction: column; gap: 8px; }

.date-bar { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
.date-bar .filter-select { width: 110px; }
.date-bar .act-filter { width: 180px; }
.date-btn { padding: 6px 14px; background: var(--bg2); color: var(--t2); border: 1px solid var(--bd); border-radius: var(--rs); font-size: 13px; cursor: pointer; transition: all 0.15s; }
.date-btn:hover { color: var(--t1); border-color: var(--bd2); }
.date-btn.active { background: var(--ac); color: #fff; border-color: var(--ac); }
.date-btn.apply { background: var(--ac); color: #fff; border-color: var(--ac); margin-left: 4px; }
.custom-range { display: flex; align-items: center; gap: 6px; margin-left: 8px; }
.date-input { background: var(--bg3); color: var(--t1); border: 1px solid var(--bd); border-radius: var(--rs); padding: 5px 10px; font-size: 13px; color-scheme: dark; }
.date-input:focus { outline: none; border-color: var(--ac); }
.date-sep { color: var(--t3); font-size: 13px; }
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

/* 系统信息区 */
.sys-info { display: flex; align-items: center; gap: 12px; margin-left: auto; }
.refresh-btn {
  padding: 5px 12px; background: var(--acg); color: var(--ac);
  border: 1px solid var(--ac); border-radius: var(--rs);
  font-size: 12px; cursor: pointer; transition: all 0.15s; white-space: nowrap;
}
.refresh-btn:hover { background: var(--ac); color: #fff; }
.refresh-btn:disabled { opacity: 0.6; cursor: wait; }
.refresh-btn.primary { background: var(--ac); color: #fff; border-color: var(--ac); }
.refresh-btn.primary:hover { filter: brightness(1.08); background: var(--ac); }
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

/* KPI 卡（auto-fit 自适应列数，8 张也不挤）*/
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(116px, 1fr)); gap: 10px; }
.stat-card { background: var(--bg2); border-radius: var(--rs); padding: 14px 16px; display: flex; flex-direction: column; gap: 4px; border: 1px solid var(--bd); position: relative; overflow: hidden; box-shadow: var(--shadow-card); transition: all 0.15s; }
.stat-card.clickable { cursor: pointer; }
.stat-card.clickable:hover { border-color: var(--ac); transform: translateY(-1px); }
.stat-card.active { border-color: var(--ac); background: var(--bg3); }
.stat-card::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; }
.blue::before { background: #0a84ff; } .green::before { background: #30d158; } .orange::before { background: #ff9f0a; }
.purple::before { background: #bf5af2; } .red::before { background: #ff453a; } .cyan::before { background: #64d2ff; } .teal::before { background: #5ac8fa; } .indigo::before { background: #5e5ce6; }
.stat-label { font-size: 11px; color: var(--t3); white-space: nowrap; }
.stat-value { font-size: 24px; font-weight: 600; color: var(--t1); letter-spacing: -0.02em; }
.stat-sub { font-size: 10px; color: var(--t3); margin-top: -2px; }
.stat-arrow { position: absolute; right: 10px; bottom: 10px; font-size: 14px; color: var(--t3); transition: transform 0.2s; }
.stat-arrow.rotated { transform: rotate(180deg); color: var(--ac); }

/* KPI 明细 */
.kpi-detail-panel { background: var(--bg2); border-radius: var(--rs); border: 1px solid var(--ac); overflow: hidden; box-shadow: var(--shadow-card); animation: slideDown 0.2s ease-out; }
.kpi-detail-panel .table-scroll { max-height: 400px; overflow-y: auto; }
.kpi-detail-panel .detail-header { padding: 12px 16px; border-bottom: 1px solid var(--bd); display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 500; color: var(--t1); }
.kpi-detail-panel .detail-table td { cursor: pointer; }
.kpi-detail-panel .detail-table tbody tr:hover { background: var(--bg3); }

/* section 容器（KPI/任务/落地页 统一：标题 + 内容，gap 10px）*/
.kpi-section, .task-section { display: flex; flex-direction: column; gap: 10px; }
.section-title { font-size: 16px; font-weight: 600; color: var(--t1); }
.task-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
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
.detail-table { width: 100%; border-collapse: collapse; }
.detail-table th { padding: 8px 16px; font-size: 12px; font-weight: 500; color: var(--t3); border-bottom: 1px solid var(--bd); white-space: nowrap; }
.detail-table th.left { text-align: left; } .detail-table th.right { text-align: right; }
.detail-table thead th { position: sticky; top: 0; background: var(--bg2); z-index: 1; }
.detail-table td { padding: 8px 16px; font-size: 13px; border-bottom: 1px solid var(--bd); white-space: nowrap; }
.detail-table td.left { text-align: left; } .detail-table td.right { text-align: right; }
.detail-table tbody tr:last-child td { border-bottom: none; }
.detail-table tbody tr.selected-row { background: var(--acg); }
.detail-table tbody tr.selected-row td { color: var(--ac); font-weight: 500; }

/* 落地页流量 */
.landing-section { display: flex; flex-direction: column; gap: 10px; }
/* 落地页汇总卡复用 .stat-grid/.stat-card（和广告版 KPI 卡同款）*/
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

/* 两列 */
.bottom-grid { display: grid; grid-template-columns: 1fr 340px; gap: 16px; align-items: start; }
.card { background: var(--bg2); border-radius: var(--rs); border: 1px solid var(--bd); overflow: hidden; box-shadow: var(--shadow-card); }
.card-header { padding: 14px 20px; border-bottom: 1px solid var(--bd); display: flex; justify-content: space-between; align-items: center; gap: 12px; }
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
.acc-table tbody tr.error-row { background: rgba(255,69,58,0.04); cursor: default; }
.acc-table tbody tr.removed-row { opacity: .55; cursor: default; }
.acc-table tbody tr.removed-row:hover { background: transparent; }
.acc-name { font-weight: 500; color: var(--t1); font-size: 13px; }
.acc-id { font-size: 10px; color: var(--t3); margin-top: 1px; }
.mono { font-family: 'SF Mono', 'Fira Code', monospace; color: var(--t2); }
.allow-btn { padding: 3px 10px; border: 1px solid var(--bd); background: transparent; color: var(--t2); border-radius: 4px; font-size: 11px; cursor: pointer; white-space: nowrap; }
.allow-btn:hover { color: var(--success); border-color: var(--success); }
.allow-btn.remove:hover { color: var(--error); border-color: var(--error); }
.usd-eq { color: var(--t3) !important; font-size: 12px; }
.pill { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 20px; font-size: 11px; white-space: nowrap; }
.pill.ok { background: rgba(48,209,88,0.1); color: var(--success); }
.pill.error { background: rgba(255,69,58,0.1); color: var(--error); }

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
.nd-meta { display: flex; flex-direction: column; gap: 5px; margin-bottom: 10px; }
.nd-meta div { font-size: 12px; color: var(--t3); display: flex; gap: 8px; }
.nd-meta label { color: var(--t3); min-width: 46px; }
.nd-meta code { font-family: 'SF Mono', monospace; color: var(--t2); }
.nd-actions { display: flex; gap: 8px; }
.nd-btn { padding: 5px 12px; background: var(--acg); color: var(--ac); border: 1px solid var(--ac); border-radius: var(--rs); font-size: 12px; cursor: pointer; transition: all 0.15s; }
.nd-btn:hover { background: var(--ac); color: #fff; }
.notif-dot { width: 9px; height: 9px; border-radius: 50%; margin-top: 6px; flex-shrink: 0; }
.notif-dot.critical { background: var(--error); }
.notif-dot.warning { background: var(--warning); }
.notif-dot.info { background: var(--ac); }
.notif-content { flex: 1; min-width: 0; }
.notif-text { font-size: 13.5px; color: var(--t1); line-height: 1.45; }
.notif-meta { font-size: 11px; color: var(--t3); margin-top: 5px; }
.notif-arrow { font-size: 14px; color: var(--t3); margin-top: 5px; transition: transform 0.2s; }
.notif-arrow.rotated { transform: rotate(180deg); }
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

@media (max-width: 1280px) { .stat-grid { grid-template-columns: repeat(4, 1fr); } .block-detail .block-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 768px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } .bottom-grid { grid-template-columns: 1fr; } .block-detail .block-grid { grid-template-columns: 1fr; } .landing-summary { gap: 14px; } }
</style>
