<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { GET, POST, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

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
const drillCampaign = ref('')
const drillAdset = ref('')
const statusFilter = ref('all')
const sortKey = ref('spend')
const sortDir = ref('desc')
const searchQ = ref('')

const dateOptions = [
  { label: '今天', value: 'today' },
  { label: '昨天', value: 'yesterday' },
  { label: '近2天', value: 'last_2d' },
  { label: '近7天', value: 'last_7d' },
]
const _fmt = (d) => d.toISOString().slice(0, 10)
const curRange = computed(() => {
  if (showCustom.value && customFrom.value) return { date_from: customFrom.value, date_to: customTo.value || customFrom.value }
  const today = new Date()
  if (datePreset.value === 'today') return { date_from: _fmt(today), date_to: _fmt(today) }
  if (datePreset.value === 'yesterday') { const y = new Date(Date.now() - 86400000); return { date_from: _fmt(y), date_to: _fmt(y) } }
  const days = { last_2d: 2, last_7d: 7 }[datePreset.value] || 2
  return { date_from: _fmt(new Date(Date.now() - days * 86400000)), date_to: _fmt(today) }
})

const STATUS_MAP = { ACTIVE: '投放中', PAUSED: '已暂停', CAMPAIGN_PAUSED: '系列暂停', ADSET_PAUSED: '组暂停', ARCHIVED: '已归档', DELETED: '已删除', DISAPPROVED: '被拒', PENDING_REVIEW: '审核中', PREVIEW: '预览', IN_PROCESS: '处理中', WITH_ISSUES: '有问题', REVIEW_IN_PROGRESS: '审核中' }
const statusLabel = (s) => STATUS_MAP[s] || s || '-'
const statusDot = (s) => s === 'ACTIVE' ? 'ok' : (['DISAPPROVED', 'DELETED', 'WITH_ISSUES'].includes(s) ? 'err' : (s && s.includes('PAUSED') ? 'warn' : (s === 'ARCHIVED' ? 'off' : 'warn')))
const OBJ_MAP = { OUTCOME_SALES: '销量', OUTCOME_TRAFFIC: '流量', OUTCOME_ENGAGEMENT: '互动', OUTCOME_AWARENESS: '品牌认知', OUTCOME_LEAD_GENERATION: '线索', LINK_CLICKS: '流量', CONVERSIONS: '销量', MESSAGES: '消息', PAGE_LIKES: '主页赞', POST_ENGAGEMENT: '互动', VIDEO_VIEWS: '视频观看', BRAND_AWARENESS: '品牌认知', REACH: '覆盖' }
const objLabel = (o) => OBJ_MAP[o] || o || '-'
const OPT_MAP = { OFFSITE_CONVERSIONS: '转化', LINK_CLICKS: '链接点击', LANDING_PAGE_VIEWS: '落地页浏览', POST_ENGAGEMENT: '互动', REACH: '覆盖', IMPRESSIONS: '展示', VIDEO_VIEWS: '视频观看', APP_INSTALLS: '应用安装', LEAD_GENERATION: '潜在客户', MESSAGING_CONVERSATIONS: '消息对话', VALUE: '价值' }
const optLabel = (o) => OPT_MAP[o] || o || '-'

const _idOf = (v) => (v && typeof v === 'object') ? v.id : v
const fmtMoney = (v) => (v == null) ? '-' : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
const fmtNum = (v) => (v == null || v === 0) ? '-' : Number(v).toLocaleString()
const fmtBudget = (a, ctx) => {
  if (a.daily_budget_amount != null) return `${fmtMoney(a.daily_budget_amount)}/日`
  if (a.lifetime_budget_amount != null) return `${fmtMoney(a.lifetime_budget_amount)} 总`
  return ctx === 'campaign' ? '组预算' : '系列预算'
}
const hasBudget = (a) => a.daily_budget_amount != null || a.lifetime_budget_amount != null

const cols = computed(() => tab.value === 'ad'
  ? '0.95fr 1.5fr 0.7fr 0.5fr 0.5fr 0.5fr 0.5fr 0.5fr 0.5fr 0.55fr 0.5fr 28px'
  : '0.95fr 1.5fr 0.6fr 0.65fr 0.6fr 0.5fr 0.5fr 0.6fr 0.5fr 28px')
const rowStyle = computed(() => ({ gridTemplateColumns: cols.value }))

const loadAccounts = async () => {
  try { accounts.value = await GET('/fb/accounts'); const q = route.query.act; if (q) selectedActs.value = [q]; await load(); await loadRedirectMap() }
  catch (e) { ElMessage.error(e.message || '加载账户失败') }
}
const load = async () => {
  loading.value = true
  try { const params = new URLSearchParams(curRange.value); data.value = await GET(`/ads/list?${params.toString()}`); drillCampaign.value = ''; drillAdset.value = '' }
  catch (e) { ElMessage.error(e.message || '加载失败') }
  loading.value = false
}
const statusMatch = (s) => statusFilter.value === 'all' ? true : (statusFilter.value === 'active' ? s === 'ACTIVE' : (s === 'PAUSED' || (s && s.includes('PAUSED'))))
const actMatch = (item) => !selectedActs.value.length ? true : selectedActs.value.includes(item.act_id)
const sortBy = (key) => { if (sortKey.value === key) sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'; else { sortKey.value = key; sortDir.value = 'desc' } }
const _rankMap = { ACTIVE: 0, PAUSED: 1, CAMPAIGN_PAUSED: 2, ADSET_PAUSED: 3, PENDING_REVIEW: 4, WITH_ISSUES: 5, DISAPPROVED: 6, ARCHIVED: 7, DELETED: 8 }
const statusRank = (s) => _rankMap[s] ?? 9
const sortIcon = (key) => sortKey.value === key ? (sortDir.value === 'desc' ? '▼' : '▲') : ''

const curList = computed(() => {
  let arr
  if (tab.value === 'campaign') arr = data.value.campaigns || []
  else if (tab.value === 'adset') { arr = data.value.adsets || []; if (drillCampaign.value) arr = arr.filter(a => _idOf(a.campaign_id) === drillCampaign.value) }
  else { arr = data.value.ads || []; if (drillAdset.value) arr = arr.filter(a => _idOf(a.adset_id) === drillAdset.value) }
  arr = arr.filter(a => actMatch(a) && statusMatch(a.effective_status))
  if (searchQ.value.trim()) {
    const q = searchQ.value.trim().toLowerCase()
    arr = arr.filter(a => (a.name || '').toLowerCase().includes(q) || String(a.id || '').includes(q))
  }
  return arr.slice().sort((a, b) => {
    if (sortKey.value === '_status_rank') { const d = statusRank(a.effective_status) - statusRank(b.effective_status); return sortDir.value === 'desc' ? d : -d }
    const sa = statusRank(a.effective_status), sb = statusRank(b.effective_status)
    if (sa !== sb) return sa - sb
    let va = Number(a[sortKey.value] || 0), vb = Number(b[sortKey.value] || 0)
    return sortDir.value === 'desc' ? vb - va : va - vb
  })
})
const drillName = computed(() => {
  if (tab.value === 'adset' && drillCampaign.value) { const c = (data.value.campaigns || []).find(x => x.id === drillCampaign.value); return c ? `系列：${c.name}` : '' }
  if (tab.value === 'ad' && drillAdset.value) { const s = (data.value.adsets || []).find(x => x.id === drillAdset.value); return s ? `组：${s.name}` : '' }
  return ''
})
const drillToAdset = (c) => { drillCampaign.value = c.id; tab.value = 'adset'; if (c.act_id && !selectedActs.value.includes(c.act_id)) selectedActs.value = [c.act_id] }
const drillToAd = (s) => { drillAdset.value = s.id; tab.value = 'ad'; if (s.act_id && !selectedActs.value.includes(s.act_id)) selectedActs.value = [s.act_id] }
const clearDrill = () => { drillCampaign.value = ''; drillAdset.value = '' }
onMounted(loadAccounts)

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
  try { const r = await POST('/ads/status', { act_id: item.act_id, node_id: item.id, level: curLevel(), status: ns }); if (r.success) { item.effective_status = r.effective_status || ns; item.status = ns; ElMessage.success(ns === 'ACTIVE' ? '已开启' : '已暂停') } else ElMessage.error(r.error || '操作失败') } catch (e) { ElMessage.error(e.message || '操作失败') }
  opLoading.value = false
}
const openBudget = (item) => {
  const isLifetime = item.lifetime_budget_amount != null
  budgetTarget.value = { act_id: item.act_id, node_id: item.id, level: curLevel(), name: item.name, budget_type: isLifetime ? 'lifetime' : 'daily' }
  budgetInput.value = Number(item.lifetime_budget_amount ?? (item.daily_budget_amount || 0))
  budgetDialog.value = true
}
const saveBudget = async () => {
  if (!budgetInput.value || budgetInput.value <= 0) return ElMessage.warning('预算必须大于 0')
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
      ElMessage.success('预算已更新'); budgetDialog.value = false
    } else ElMessage.error(r.error || '操作失败')
  } catch (e) { ElMessage.error(e.message || '操作失败') }
  opLoading.value = false
}
const budgetQuick = (m) => { budgetInput.value = Math.round(budgetInput.value * m * 100) / 100 }
const deleteItem = async (item) => {
  try { await ElMessageBox.confirm(`删除「${item.name}」？删除后不可恢复。`, '确认删除', { type: 'warning', confirmButtonText: '确认删除', confirmButtonClass: 'el-button--danger' }); opLoading.value = true; const r = await POST('/ads/delete', { act_id: item.act_id, node_id: item.id }); if (r.success) { ElMessage.success('已删除'); await load() } else ElMessage.error(r.error || '删除失败') } catch(e) { /* cancelled */ }
  opLoading.value = false
}
const batchStatus = async (status) => {
  if (!selected.value.size) return ElMessage.warning('先点选广告行')
  if (status === 'PAUSED') {
    try { await ElMessageBox.confirm(`批量暂停 ${selected.value.size} 条广告？`, '确认批量暂停', { type: 'warning', confirmButtonText: '暂停', cancelButtonText: '取消' }) }
    catch { return }
  }
  const items = []; for (const id of selected.value) { const it = curList.value.find(x => x.id === id); if (it) items.push({ act_id: it.act_id, node_id: it.id, level: curLevel(), status }) }
  opLoading.value = true
  try { const r = await POST('/ads/batch-status', { items }); ElMessage.success(`${r.success_count}/${items.length} 成功`); await load(); selected.value = new Set() } catch (e) { ElMessage.error(e.message || '批量操作失败') }
  opLoading.value = false
}
const onAction = (cmd, item) => { if (cmd === 'toggle') toggleStatus(item); else if (cmd === 'budget') openBudget(item); else if (cmd === 'delete') deleteItem(item); else if (cmd === 'redirect') openRedirect(item); else if (cmd === 'logs') router.push({ name: 'landing', query: { tab: 'logs', ad_id: item.id } }); else if (cmd === 'diagnose') openDiagnose(item) }

// 广告诊断
const diagOpen = ref(false)
const diagLoading = ref(false)
const diagData = ref(null)
const openDiagnose = async (item) => {
  diagOpen.value = true; diagLoading.value = true; diagData.value = null
  try { diagData.value = await GET('/ads/' + item.id + '/diagnose') }
  catch (e) { ElMessage.error('诊断失败：' + (e.message || '')) }
  diagLoading.value = false
}
const RULE_ZH = { bleed_abs: '空耗止损', cpa_exceed: 'CPA超标', consecutive_bad: '连续恶化', click_no_conv: '点击无转化', reach_no_conv: '覆盖无转化', low_ctr_no_conv: '低CTR无转化', budget_burn_fast: '瞬烧制止' }
const CS_ZH = { fb: '仅Facebook', landing: '仅落地页', either: '综合（取大）' }
const goLandingLogs = (slug, adId) => { router.push({ name: 'landing', query: { tab: 'logs', slug, ad_id: adId } }) }
const loadRedirectMap = async () => { try { redirectMap.value = await GET('/ads/redirects/map') } catch (e) {} }
const openRedirect = (item) => { redirectTarget.value = { id: item.id, name: item.name }; redirectInput.value = redirectMap.value[item.id] || ''; redirectDialog.value = true }
const saveRedirect = async () => {
  const adId = redirectTarget.value.id
  try { await POST('/ads/redirects', { ad_id: adId, target_url: redirectInput.value.trim() })
    if (redirectInput.value.trim()) { redirectMap.value = { ...redirectMap.value, [adId]: redirectInput.value.trim() } }
    else { const m = { ...redirectMap.value }; delete m[adId]; redirectMap.value = m }
    ElMessage.success(redirectInput.value.trim() ? '跳转链接已设' : '已恢复默认跳转'); redirectDialog.value = false
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
}
const openRedirectMgmt = async () => { redirectMgmtOpen.value = true; try { redirectList.value = await GET('/ads/redirects') } catch (e) {} }
const removeRedirect = async (adId) => { try { await DELETE('/ads/redirects/' + adId); const m = { ...redirectMap.value }; delete m[adId]; redirectMap.value = m; redirectList.value = redirectList.value.filter(r => r.ad_id !== adId); ElMessage.success('已恢复默认') } catch (e) {} }
const resetRedirects = async () => {
  try { await ElMessageBox.confirm('清空所有广告跳转覆盖？所有广告将恢复落地页默认跳转。', '确认', { type: 'warning' })
    const r = await POST('/ads/redirects/reset', {}); redirectMap.value = {}; redirectList.value = []; ElMessage.success('已清空 ' + (r.cleared || 0) + ' 条')
  } catch (e) {}
}
const toggleSelect = (id) => { const s = new Set(selected.value); s.has(id) ? s.delete(id) : s.add(id); selected.value = s }
const selectAll = () => { selected.value = selected.value.size === curList.value.length ? new Set() : new Set(curList.value.map(x => x.id)) }
const isSelected = (id) => selected.value.has(id)
</script>

<template>
  <div class="page">
    <div class="ctrl-bar">
      <button v-for="opt in dateOptions" :key="opt.value" class="ctrl-btn" :class="{ active: datePreset === opt.value && !showCustom }" @click="showCustom = false; datePreset = opt.value; load()">{{ opt.label }}</button>
      <button class="ctrl-btn" :class="{ active: showCustom }" @click="showCustom = !showCustom">自定义</button>
      <div v-if="showCustom" class="custom-range"><input type="date" v-model="customFrom" class="date-input" /><span class="sep">—</span><input type="date" v-model="customTo" class="date-input" /><button class="ctrl-btn apply" @click="load">查询</button></div>
      <el-select v-model="selectedActs" multiple filterable collapse-tags collapse-tags-tooltip clearable placeholder="全部账户" class="act-filter" style="width:180px"><el-option v-for="a in accounts" :key="a.act_id" :value="a.act_id" :label="a.name" /></el-select>
      <div class="sf-group"><button class="ctrl-btn sm" :class="{ on: statusFilter === 'all' }" @click="statusFilter = 'all'">全部</button><button class="ctrl-btn sm" :class="{ on: statusFilter === 'active' }" @click="statusFilter = 'active'">投放中</button><button class="ctrl-btn sm" :class="{ on: statusFilter === 'paused' }" @click="statusFilter = 'paused'">暂停</button></div>
      <input v-model="searchQ" class="ctrl-btn search-input" placeholder="搜索广告名/ID" />
      <button class="ctrl-btn" @click="openRedirectMgmt">跳转链接<span v-if="Object.keys(redirectMap).length" class="rd-badge">{{ Object.keys(redirectMap).length }}</span></button>
      <button class="ctrl-btn primary" :disabled="loading" @click="load" style="margin-left:auto">{{ loading ? '加载中…' : '刷新' }}</button>
    </div>
    <transition name="slide">
      <div v-if="selected.size" class="batch-bar">
        <span class="batch-count">已选 {{ selected.size }} 条</span>
        <button class="ctrl-btn sm" @click="selectAll">全选/取消</button>
        <button class="ctrl-btn sm" @click="batchStatus('ACTIVE')" :disabled="opLoading">批量开启</button>
        <button class="ctrl-btn sm" @click="batchStatus('PAUSED')" :disabled="opLoading">批量暂停</button>
        <button class="ctrl-btn sm ghost" @click="selected = new Set()">取消选择</button>
      </div>
    </transition>
    <div class="tabs">
      <div :class="['tab', { on: tab === 'campaign' }]" @click="tab = 'campaign'; clearDrill(); selected = new Set()">广告系列</div>
      <div :class="['tab', { on: tab === 'adset' }]" @click="tab = 'adset'; selected = new Set()">广告组</div>
      <div :class="['tab', { on: tab === 'ad' }]" @click="tab = 'ad'; selected = new Set()">广告</div>
      <div v-if="drillName" class="drill-tag">{{ drillName }} <span @click="clearDrill">✕</span></div>
    </div>
    <div class="tbl" v-loading="loading">
      <template v-if="tab === 'campaign'">
        <div class="row head" :style="rowStyle"><div class="so" @click="sortBy('_status_rank')">状态{{ sortIcon('_status_rank') }}</div><div>系列</div><div>目标</div><div class="so" @click="sortBy('daily_budget_amount')">预算{{ sortIcon('daily_budget_amount') }}</div><div class="so" @click="sortBy('spend')">消耗{{ sortIcon('spend') }}</div><div class="so" @click="sortBy('conversions')">转化{{ sortIcon('conversions') }}</div><div class="so" @click="sortBy('cpa')">CPA{{ sortIcon('cpa') }}</div><div class="so" @click="sortBy('reach')">覆盖{{ sortIcon('reach') }}</div><div class="so" @click="sortBy('frequency')">频次{{ sortIcon('frequency') }}</div><div></div></div>
        <div v-for="c in curList" :key="c.id" class="row" :class="{ sel: isSelected(c.id) }" :style="rowStyle" @click="toggleSelect(c.id)">
          <div class="status-cell" @click.stop><el-switch :model-value="c.effective_status === 'ACTIVE'" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" @change="toggleStatus(c)" :disabled="opLoading" /><span class="dot" :class="statusDot(c.effective_status)"></span>{{ statusLabel(c.effective_status) }}</div>
          <div class="nm clk" @click.stop="drillToAdset(c)">{{ c.name }}<div class="sid">{{ c.account_name }} · {{ c.id }}</div></div>
          <div>{{ objLabel(c.objective) }}</div>
          <div class="budget-cell" :class="{ editable: hasBudget(c) }" @click.stop="hasBudget(c) && openBudget(c)">{{ fmtBudget(c, 'campaign') }}</div>
          <div>{{ fmtMoney(c.spend) }}</div><div>{{ c.conversions || 0 }}</div><div>{{ c.cpa ? fmtMoney(c.cpa) : '-' }}</div><div>{{ fmtNum(c.reach) }}</div><div>{{ c.frequency || '-' }}</div>
          <div class="ops" @click.stop><el-dropdown trigger="click" @command="cmd => onAction(cmd, c)" placement="bottom-end"><button class="more-btn" :disabled="opLoading">⚙</button><template #dropdown><el-dropdown-menu><el-dropdown-item command="toggle">{{ c.effective_status === 'ACTIVE' ? '暂停' : '开启' }}</el-dropdown-item><el-dropdown-item v-if="hasBudget(c)" command="budget">改预算</el-dropdown-item><el-dropdown-item command="delete" divided style="color:var(--error)">删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
        </div>
      </template>
      <template v-else-if="tab === 'adset'">
        <div class="row head" :style="rowStyle"><div class="so" @click="sortBy('_status_rank')">状态{{ sortIcon('_status_rank') }}</div><div>广告组</div><div>优化目标</div><div class="so" @click="sortBy('daily_budget_amount')">预算{{ sortIcon('daily_budget_amount') }}</div><div class="so" @click="sortBy('spend')">消耗{{ sortIcon('spend') }}</div><div class="so" @click="sortBy('conversions')">转化{{ sortIcon('conversions') }}</div><div class="so" @click="sortBy('cpa')">CPA{{ sortIcon('cpa') }}</div><div class="so" @click="sortBy('reach')">覆盖{{ sortIcon('reach') }}</div><div class="so" @click="sortBy('frequency')">频次{{ sortIcon('frequency') }}</div><div></div></div>
        <div v-for="s in curList" :key="s.id" class="row" :class="{ sel: isSelected(s.id) }" :style="rowStyle" @click="toggleSelect(s.id)">
          <div class="status-cell" @click.stop><el-switch :model-value="s.effective_status === 'ACTIVE'" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" @change="toggleStatus(s)" :disabled="opLoading" /><span class="dot" :class="statusDot(s.effective_status)"></span>{{ statusLabel(s.effective_status) }}</div>
          <div class="nm clk" @click.stop="drillToAd(s)">{{ s.name }}<div class="sid">{{ s.account_name }} · {{ s.id }}</div></div>
          <div>{{ optLabel(s.optimization_goal) }}</div>
          <div class="budget-cell" :class="{ editable: hasBudget(s) }" @click.stop="hasBudget(s) && openBudget(s)">{{ fmtBudget(s, 'adset') }}</div>
          <div>{{ fmtMoney(s.spend) }}</div><div>{{ s.conversions || 0 }}</div><div>{{ s.cpa ? fmtMoney(s.cpa) : '-' }}</div><div>{{ fmtNum(s.reach) }}</div><div>{{ s.frequency || '-' }}</div>
          <div class="ops" @click.stop><el-dropdown trigger="click" @command="cmd => onAction(cmd, s)" placement="bottom-end"><button class="more-btn" :disabled="opLoading">⚙</button><template #dropdown><el-dropdown-menu><el-dropdown-item command="toggle">{{ s.effective_status === 'ACTIVE' ? '暂停' : '开启' }}</el-dropdown-item><el-dropdown-item v-if="hasBudget(s)" command="budget">改预算</el-dropdown-item><el-dropdown-item command="delete" divided style="color:var(--error)">删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
        </div>
      </template>
      <template v-else>
        <div class="row head" :style="rowStyle"><div class="so" @click="sortBy('_status_rank')">状态{{ sortIcon('_status_rank') }}</div><div>广告</div><div>子码</div><div class="so" @click="sortBy('spend')">消耗{{ sortIcon('spend') }}</div><div class="so" @click="sortBy('conversions')">转化{{ sortIcon('conversions') }}</div><div class="so" @click="sortBy('cpa')">CPA{{ sortIcon('cpa') }}</div><div class="so" @click="sortBy('landing_visits')">访问{{ sortIcon('landing_visits') }}</div><div class="so" @click="sortBy('landing_pass')">通过{{ sortIcon('landing_pass') }}</div><div>通过率</div><div class="so" @click="sortBy('reach')">覆盖{{ sortIcon('reach') }}</div><div class="so" @click="sortBy('ctr')">CTR{{ sortIcon('ctr') }}</div><div></div></div>
        <div v-for="a in curList" :key="a.id" class="row" :class="{ sel: isSelected(a.id) }" :style="rowStyle" @click="toggleSelect(a.id)">
          <div class="status-cell" @click.stop><el-switch :model-value="a.effective_status === 'ACTIVE'" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" @change="toggleStatus(a)" :disabled="opLoading" /><span class="dot" :class="statusDot(a.effective_status)"></span>{{ statusLabel(a.effective_status) }}</div>
          <div class="nm">{{ a.name }}<span v-if="redirectMap[a.id]" class="rd-mark" @click.stop="openRedirect(a)" :title="'已设跳转：' + redirectMap[a.id] + '（点击修改）'">跳转</span><div class="sid">{{ a.account_name }} · {{ a.id }}</div></div>
          <div class="slug-cell"><code v-if="a.slug" class="ad-slug" @click.stop="goLandingLogs(a.slug, a.id)" :title="'/a/' + a.slug + ' · 该广告通过 ' + (a.landing_pass||0) + '（点击查日志）'">/a/{{ a.slug }}</code><span v-else class="muted" title="该广告暂无落地流量（访客点 /a/子码?ad= 后自动绑定）">未铺</span></div>
          <div>{{ fmtMoney(a.spend) }}</div><div>{{ a.conversions || 0 }}</div><div>{{ a.cpa ? fmtMoney(a.cpa) : '-' }}</div><div class="lv" :title="'落地访问量（visit+redirect）'">{{ a.landing_visits || '-' }}</div><div class="lp" :title="'通过量=按钮点击+跳转（按IP去重）'">{{ a.landing_pass || '-' }}</div><div class="lpr" :title="a.landing_visits ? '通过 ' + (a.landing_pass||0) + ' / 访问 ' + a.landing_visits : '无访问'">{{ a.landing_visits ? Math.round((a.landing_pass || 0) / a.landing_visits * 100) + '%' : '-' }}</div><div>{{ fmtNum(a.reach) }}</div><div>{{ a.ctr ? a.ctr + '%' : '-' }}</div>
          <div class="ops" @click.stop><el-dropdown trigger="click" @command="cmd => onAction(cmd, a)" placement="bottom-end"><button class="more-btn" :disabled="opLoading">⚙</button><template #dropdown><el-dropdown-menu><el-dropdown-item command="toggle">{{ a.effective_status === 'ACTIVE' ? '暂停' : '开启' }}</el-dropdown-item><el-dropdown-item command="redirect">跳转链接{{ redirectMap[a.id] ? ' · 已设' : '' }}</el-dropdown-item><el-dropdown-item command="logs">查看落地日志</el-dropdown-item><el-dropdown-item command="diagnose">🔍 广告诊断</el-dropdown-item><el-dropdown-item command="delete" divided style="color:var(--error)">删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
        </div>
      </template>
      <div v-if="!curList.length && !loading" class="empty">暂无数据</div>
    </div>
    <el-dialog v-model="budgetDialog" :title="`改预算 · ${budgetTarget?.name || ''}`" width="360px" :close-on-click-modal="false" :destroy-on-close="true" append-to-body>
      <div class="budget-form">
        <label>{{ budgetTarget?.budget_type === 'lifetime' ? '总预算（本币）' : '日预算（本币）' }}</label>
        <input v-model.number="budgetInput" type="number" min="1" step="0.01" class="budget-input" />
        <div class="quick-btns"><button v-for="m in [1, 1.2, 1.5, 2]" :key="m" class="ctrl-btn sm" @click="budgetQuick(m)">×{{ m }}</button></div>
      </div>
      <template #footer><button class="ctrl-btn" @click="budgetDialog = false">取消</button><button class="ctrl-btn primary" :disabled="opLoading" @click="saveBudget">{{ opLoading ? '保存中…' : '保存' }}</button></template>
    </el-dialog>

    <el-dialog v-model="redirectDialog" :title="`跳转链接 · ${redirectTarget?.name || ''}`" width="440px" :close-on-click-modal="false" :destroy-on-close="true" append-to-body>
      <div class="rd-form">
        <label>该广告的专属跳转链接</label>
        <input v-model.trim="redirectInput" class="budget-input" placeholder="https://...（留空=用落地页默认）" />
        <div class="rd-hint">设了之后，这条广告的访客都跳到这个链接；其他广告不受影响。留空保存 = 恢复落地页默认。</div>
      </div>
      <template #footer>
        <button class="ctrl-btn" @click="redirectDialog = false">取消</button>
        <button v-if="redirectMap[redirectTarget?.id]" class="ctrl-btn" @click="redirectInput=''; saveRedirect()">恢复默认</button>
        <button class="ctrl-btn primary" @click="saveRedirect">保存</button>
      </template>
    </el-dialog>

    <el-dialog v-model="redirectMgmtOpen" title="广告跳转链接管理" width="640px" :destroy-on-close="true" append-to-body>
      <div class="rd-mgmt-bar">
        <span class="rd-cnt">共 {{ redirectList.length }} 条已设跳转</span>
        <button class="ctrl-btn sm" :disabled="!redirectList.length" @click="resetRedirects">全部恢复默认</button>
      </div>
      <div class="rd-mgmt-list" v-loading="false">
        <div v-for="r in redirectList" :key="r.ad_id" class="rd-mgmt-row">
          <code class="rd-mid">{{ r.ad_id }}</code>
          <span class="rd-murl" :title="r.target_url">{{ r.target_url }}</span>
          <button class="ctrl-btn sm" @click="removeRedirect(r.ad_id)">移除</button>
        </div>
        <div v-if="!redirectList.length" class="empty" style="padding:30px">暂无广告设了专属跳转（都走落地页默认）</div>
      </div>
    </el-dialog>

    <el-drawer v-model="diagOpen" title="广告诊断" direction="rtl" size="520px" :destroy-on-close="true">
      <div v-loading="diagLoading" class="diag-body">
        <template v-if="diagData">
          <div v-if="diagData.fb_error" class="diag-warn">⚠ {{ diagData.fb_error }}</div>
          <div class="diag-sec">
            <div class="diag-sec-title">基础信息</div>
            <div class="diag-grid">
              <div><span class="dl">账户</span><span class="dv">{{ diagData.account_name }}</span></div>
              <div><span class="dl">广告ID</span><span class="dv">{{ diagData.ad_id }}</span></div>
              <div><span class="dl">子码</span><span class="dv">{{ diagData.subcode || '未绑' }}</span></div>
              <div><span class="dl">FB状态</span><span class="dv">{{ diagData.fb_status || '—' }}</span></div>
            </div>
          </div>
          <div class="diag-sec">
            <div class="diag-sec-title">今日数据（{{ diagData.account_timezone }}）</div>
            <div class="diag-grid">
              <div><span class="dl">消耗</span><span class="dv">{{ diagData.spend_usd ? '$' + diagData.spend_usd : '—' }}</span></div>
              <div><span class="dl">曝光</span><span class="dv">{{ diagData.impressions || 0 }}</span></div>
              <div><span class="dl">点击</span><span class="dv">{{ diagData.clicks || 0 }}</span></div>
              <div><span class="dl">覆盖</span><span class="dv">{{ diagData.reach || 0 }}</span></div>
              <div><span class="dl">FB转化</span><span class="dv">{{ diagData.fb_conversions }} <span class="dsub">{{ diagData.fb_kpi_source }}</span></span></div>
              <div><span class="dl">落地点击</span><span class="dv">{{ diagData.landing_clicks }} <span class="dsub">去重IP</span></span></div>
              <div><span class="dl">落地访问</span><span class="dv">{{ diagData.landing_visits }}</span></div>
              <div><span class="dl">有效转化</span><span class="dv hl">{{ diagData.effective_conversions }} <span class="dsub">{{ CS_ZH[diagData.conversion_source] || diagData.conversion_source }}</span></span></div>
            </div>
          </div>
          <div class="diag-sec" v-if="diagData.rules.length">
            <div class="diag-sec-title">规则评估</div>
            <div v-for="r in diagData.rules" :key="r.rule_id" class="diag-rule" :class="{ hit: r.hit }">
              <span class="rule-icon">{{ r.hit ? '🔴' : '🟢' }}</span>
              <div class="rule-info">
                <div class="rule-title">{{ r.rule_name }} <span class="rule-type">{{ RULE_ZH[r.rule_type] || r.rule_type }}</span></div>
                <div class="rule-detail" v-if="r.detail">{{ r.detail }}</div>
                <div class="rule-meta">
                  <span>CPA={{ r.cpa != null ? '$' + r.cpa : '—' }}</span>
                  <span>FB={{ r.fb_conversions }} 落地={{ r.landing_clicks }} 有效={{ r.effective_conversions }}</span>
                </div>
              </div>
            </div>
          </div>
          <div class="diag-sec" v-if="!diagData.rules.length && !diagData.fb_error">
            <div class="diag-empty">暂无启用规则</div>
          </div>
          <div class="diag-sec" v-if="diagData.cooldown">
            <div class="diag-sec-title">冷却状态</div>
            <div class="diag-cooldown">
              🔒 规则「{{ diagData.cooldown.rule }}」在 {{ diagData.cooldown.remaining_min }} 分钟前暂停了此广告，冷却中（剩余 {{ diagData.cooldown.remaining_min }} 分钟）
            </div>
          </div>
          <div class="diag-sec" v-if="diagData.whitelisted">
            <div class="diag-warn" style="background:rgba(48,209,97,.08);color:var(--success)">✓ 今日已加白（巡检跳过此广告）</div>
          </div>
          <div class="diag-sec" v-if="diagData.recent_actions && diagData.recent_actions.length">
            <div class="diag-sec-title">最近操作</div>
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
</style>
