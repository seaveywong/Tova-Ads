<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { GET, POST } from '../api'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { DATE_PRESETS, presetRange } from '../composables/useDateRange'
import { useLatest } from '../composables/useLatest'
import { fmtTime as tzFmtTime } from '../composables/useTz'
import { usePlatform } from '../composables/usePlatform'
import { countryLabel as _countryLabel } from '../composables/useCountries'
import DatePresetBar from '../components/DatePresetBar.vue'

const { t } = useI18n()
const route = useRoute()

const EVENT_TYPES = computed(() => [
  { v: '', l: t('lplogs.actionAll') }, { v: 'visit', l: t('lplogs.actionVisit') }, { v: 'click', l: t('lplogs.actionClick') },
  { v: 'submit', l: t('lplogs.actionSubmit') }, { v: 'redirect', l: t('lplogs.actionRedirect') }, { v: 'block', l: t('lplogs.actionBlock') },
])
// decision 实际落库值域（worker 写入）：display=进落地页 / redirect=直跳 / click=CTA 点击（block 事件 decision 为空）
const DECISIONS = computed(() => [
  { v: '', l: t('lplogs.resultAll') }, { v: 'display', l: t('lplogs.actionDisplay') },
  { v: 'click', l: t('lplogs.actionClick') }, { v: 'redirect', l: t('lplogs.actionRedirect') },
])

// 原因 → 中文
const REASON_LABEL = computed(() => ({
  pass: t('lplogs.reasonPass'), device_block: t('lplogs.reasonDeviceBlock'), ua_block: t('lplogs.reasonUaBlock'),
  country_block: t('lplogs.reasonCountryBlock'), country_allow: t('lplogs.reasonCountryAllow'), dedup: t('lplogs.reasonDedup'),
}))
const reasonLabel = (r) => REASON_LABEL.value[r] || r || ''

// 国家码 → 国名：中央 useCountries registry（zh/en 双语，未知码原样返回）
const countryLabel = (c) => (c ? _countryLabel(c) : '')
// 设备类型（英文通用）
const DEVICE = { desktop: 'Desktop', tablet: 'Tablet', mobile: 'Mobile' }
const PLATFORM_ZH = { android: 'Android', ios: 'iOS', windows: 'Win', mac: 'Mac', linux: 'Linux', chrome: 'ChromeOS' }
const deviceLabel = (e) => {
  const dev = DEVICE[e.device_type] || e.device_type || ''
  const pf = PLATFORM_ZH[(e.platform || '').toLowerCase()] || e.platform || ''
  const br = e.browser || ''
  const parts = [dev, pf, br].filter(Boolean)
  return parts.length ? parts.join('·') : '-'
}
// 来源（referrer）短显：提取域名 + FB 识别
const refLabel = (ref) => {
  if (!ref) return ''
  try {
    const h = new URL(ref).hostname.replace(/^www\./, '').replace(/^m\./, 'm.')
    if (h.includes('facebook') || h.includes('fbclid') || h.includes('instagram')) return 'FB/IG'
    return h
  } catch { return ref.slice(0, 24) }
}
// 来源平台中文（可扩展：加 TikTok/Google 时在此加一行）
const SRC_PLATFORM_ZH = { facebook: 'FB', tiktok: 'TikTok', google: 'Google' }
const trim = (s) => String(s).replace(/\s+/g, ' ').trim()
// 来源类型 → 中文标签（含 detail：爬虫名/应用内/机房）
const srcLabel = (e) => {
  const pf = SRC_PLATFORM_ZH[e.source_platform] || ''
  const d = e.source_detail || ''
  if (e.source_type === 'crawler') return d || t('lplogs.srcCrawler')
  if (e.source_type === 'controlled') return trim(`${t('lplogs.adPrefix')}·${t('lplogs.srcControlled')} ${d} ${pf}`)
  if (e.source_type === 'external') return trim(`${t('lplogs.adPrefix')}·${t('lplogs.srcExternal')} ${d} ${pf}`)
  if (e.source_type === 'placeholder') return trim(`${t('lplogs.srcPlaceholder')} ${pf}`)
  if (e.source_platform === 'facebook') return t('lplogs.fbNoAd')  // 有 fbclid 无 ad_id
  if (e.referrer) return refLabel(e.referrer)
  return t('lplogs.directAccess')
}
const srcClass = (e) => {
  if (e.source_type === 'controlled') return 'src-ok'
  if (e.source_type === 'external') return 'src-bad'
  if (e.source_type === 'placeholder') return 'src-warn'
  if (e.source_type === 'crawler') return 'src-bot'
  if (e.source_platform === 'facebook') return 'src-fb'
  return 'muted'
}
const srcTitle = (e) => {
  const pf = SRC_PLATFORM_ZH[e.source_platform] || e.source_platform || ''
  if (e.source_type === 'crawler') return trim(`${e.source_detail || t('lplogs.srcCrawler')} · ${e.asn_name || ''} AS${e.asn || '?'}`)
  if (e.source_type === 'controlled') return trim(`${pf} · ${t('lplogs.srcControlledTitle', { adId: e.ad_id })}${e.source_detail ? '· ' + e.source_detail : ''}`)
  if (e.source_type === 'external') return trim(`${pf} · ${t('lplogs.srcExternalTitle', { adId: e.ad_id })}${e.source_detail ? '· ' + e.source_detail : ''}`)
  if (e.source_type === 'placeholder') return `${pf} · ${t('lplogs.srcPlaceholderTitle', { adId: e.ad_id })}`
  if (e.source_platform === 'facebook') return t('lplogs.srcFbTitle')
  if (e.referrer) return t('lplogs.sourceLabel') + ': ' + e.referrer
  return t('lplogs.directUnknown')
}
// ASN 展示：名称优先，机房标红（机房=非真人可疑：爬虫/刷量/VPN）
const asnDisplay = (e) => e.asn_name || (e.asn ? 'AS' + e.asn : '-')
const asnTitle = (e) => {
  const label = { platform: t('lplogs.asnPlatform'), datacenter: t('lplogs.asnDatacenter'), isp: t('lplogs.asnIsp') }[e.asn_type] || t('lplogs.asnUnknown')
  return trim(`${e.asn_name || t('lplogs.asnUnknown')} · AS${e.asn || '?'} · ${label}`)
}
// 像素短显：单像素显示完整ID，多像素显示第一个+数量（真实 fire 的，不推断；空=未记录）
const pixelLabel = (e) => {
  const ids = (e.fired_pixel_ids || '').split(',').filter(Boolean)
  if (!ids.length) return ''
  return ids.length === 1 ? ids[0] : `${ids[0]} +${ids.length - 1}`
}
// 是否真发生了跳转/点击（visit 只是到达，没跳）
const hasRedirect = (e) => ['redirect', 'click'].includes(e.event_type)

const fPage = ref('')
const fAct = ref('')
const fSlug = ref('')
const fAd = ref('')
const fEvent = ref('')
const fDecision = ref('')
const fSource = ref('')
const fFrom = ref('')
const fTo = ref('')
const fQ = ref('')

// 平台切换：只预筛账户下拉（行不过滤——落地事件跨平台，保持既定口径）
const { platform } = usePlatform()
const platChip = (a) => (a && (a.platform === 'tt' || a.platform === 'fb')) ? a.platform : ''
const platAccounts = computed(() => platform.value === 'all' ? accounts.value : accounts.value.filter(a => (a.platform || 'fb') === platform.value))
watch(platform, () => {
  if (fAct.value && !platAccounts.value.some(a => a.act_id === fAct.value)) { fAct.value = ''; search() }
})

const pages = ref([])
const accounts = ref([])
const items = ref([])
const total = ref(0)
const offset = ref(0)
const limit = 50
const loading = ref(false)
const _logGuard = useLatest()

const loadPages = async () => {
  try { pages.value = await GET('/landing/pages') } catch (e) {}
}
const loadAccounts = async () => {
  try { accounts.value = await GET('/fb/accounts') } catch (e) {}
}
const buildParams = () => {
  const p = { offset: offset.value, limit }
  if (fPage.value) p.page_id = fPage.value
  if (fAct.value) p.act_id = fAct.value
  if (fSlug.value) p.slug = fSlug.value
  if (fAd.value) p.ad_id = fAd.value
  if (fEvent.value) p.event_type = fEvent.value
  if (fDecision.value) p.decision = fDecision.value
  if (fSource.value) p.source_type = fSource.value
  if (fFrom.value) p.date_from = fFrom.value
  if (fTo.value) p.date_to = fTo.value
  if (fQ.value) p.q = fQ.value
  return p
}
// 来源分布统计（chip 条）：受控/外部/爬虫/占位符/未知 + 机房数。点 chip 即筛选
const stats = ref(null)
const statChips = computed(() => [
  { key: 'controlled', label: t('lplogs.srcControlled'), cls: 'src-ok' },
  { key: 'external', label: t('lplogs.srcExternal'), cls: 'src-bad' },
  { key: 'crawler', label: t('lplogs.srcCrawlerShort'), cls: 'src-bot' },
  { key: 'placeholder', label: t('lplogs.srcPlaceholder'), cls: 'src-warn' },
  { key: 'unknown', label: t('lplogs.direct'), cls: 'muted' },
])
const buildStatsParams = () => {
  const p = {}
  if (fPage.value) p.page_id = fPage.value
  if (fAct.value) p.act_id = fAct.value
  if (fSlug.value) p.slug = fSlug.value
  if (fEvent.value) p.event_type = fEvent.value
  if (fDecision.value) p.decision = fDecision.value
  if (fFrom.value) p.date_from = fFrom.value
  if (fTo.value) p.date_to = fTo.value
  if (fQ.value) p.q = fQ.value
  return p
}
const loadStats = async () => {
  try { stats.value = await GET('/landing/logs/source-stats?' + new URLSearchParams(buildStatsParams()).toString()) }
  catch (e) { /* 静默：分布是辅助信息，失败不阻断 */ }
}
const toggleSource = (k) => { fSource.value = (fSource.value === k ? '' : k); search() }
const load = async () => {
  const isLatest = _logGuard.next()
  loading.value = true
  loadStats()  // 并行刷新分布（非阻塞）
  try {
    const r = await GET('/landing/logs?' + new URLSearchParams(buildParams()).toString())
    if (!isLatest()) return   // 筛选连点时旧响应后到——丢弃
    items.value = r.items || []
    total.value = r.total || 0
  } catch (e) { if (isLatest()) ElMessage.error(e.message || t('common.opFail')) }
  if (isLatest()) loading.value = false
}
const search = () => { offset.value = 0; load() }
// 文本框 300ms debounce 即搜（回车立即搜）
let _debTimer = null
const debounceSearch = () => {
  if (_debTimer) clearTimeout(_debTimer)
  _debTimer = setTimeout(() => search(), 300)
}
onUnmounted(() => { if (_debTimer) clearTimeout(_debTimer) })
const reset = () => {
  fPage.value = ''; fAct.value = ''; fSlug.value = ''; fAd.value = ''; fEvent.value = ''; fDecision.value = ''; fSource.value = ''
  fFrom.value = ''; fTo.value = ''; fQ.value = ''; preset.value = ''; offset.value = 0; load()
}
// 日期快捷（按北京业务日，和后端查询基准对齐）；自定义区间收进 DatePresetBar
const preset = ref('')
const setPreset = (k) => {
  const r = presetRange(k)
  if (r) { fFrom.value = r[0]; fTo.value = r[1] }
  preset.value = k; offset.value = 0; load()
}
const onCustomRange = ({ from, to }) => { fFrom.value = from; fTo.value = to; offset.value = 0; load() }
const prev = () => { if (offset.value > 0) { offset.value = Math.max(0, offset.value - limit); load() } }
const next = () => { if (offset.value + limit < total.value) { offset.value += limit; load() } }
const jumpTo = ref('')
const goPage = () => {
  const n = parseInt(jumpTo.value, 10)
  if (!n || n < 1) return
  const maxPage = Math.ceil(total.value / limit)
  offset.value = Math.min(n, maxPage - 1) * limit
  jumpTo.value = ''
  load()
}

// 时间显示走用户显示时区（useTz，设置页可切换），不再硬编码 Asia/Shanghai
const fmtTime = (iso) => iso ? tzFmtTime(iso) : '-'
const goSlug = (slug) => { fSlug.value = slug; offset.value = 0; load() }
const goAct = (actId) => { if (!actId) return; fAct.value = actId; offset.value = 0; load() }
const goAd = (adId) => { if (!adId) return; fAd.value = adId; offset.value = 0; load() }
// 广告级跳转链接（就近在日志里给某条广告设专属跳转）
const redirectMap = ref({})
const redirectDialog = ref(false)
const redirectAd = ref('')
const redirectInput = ref('')
const loadRedirectMap = async () => { try { redirectMap.value = await GET('/ads/redirects/map') } catch (e) {} }
const openRedirect = (adId) => { redirectAd.value = adId; redirectInput.value = redirectMap.value[adId] || ''; redirectDialog.value = true }
const redirectSaving = ref(false)
const saveRedirect = async () => {
  if (redirectSaving.value) return   // 防双击重复 POST
  redirectSaving.value = true
  try { await POST('/ads/redirects', { ad_id: redirectAd.value, target_url: redirectInput.value.trim() })
    if (redirectInput.value.trim()) redirectMap.value = { ...redirectMap.value, [redirectAd.value]: redirectInput.value.trim() }
    else { const m = { ...redirectMap.value }; delete m[redirectAd.value]; redirectMap.value = m }
    ElMessage.success(redirectInput.value.trim() ? t('lplogs.redirectSet') : t('lplogs.redirectReset')); redirectDialog.value = false
  } catch (e) { ElMessage.error(t('common.fail') + ': ' + (e.message || '')) }
  redirectSaving.value = false
}
const eventLabel = (v) => EVENT_TYPES.value.find(x => x.v === v)?.l || v || '-'
const decisionLabel = (v) => DECISIONS.value.find(x => x.v === v)?.l || v || ''
const decisionClass = (d, et) => et === 'block' ? 'err' : (d === 'display' || et === 'visit' ? 'ok' : 'warn')
const pageTitle = () => {
  const p = pages.value.find(x => String(x.id) === String(fPage.value))
  return p ? p.title : t('lplogs.allLandingPages')
}

onMounted(async () => {
  if (route.query.slug) fSlug.value = route.query.slug
  if (route.query.page_id) fPage.value = String(route.query.page_id)
  if (route.query.ad_id) fAd.value = String(route.query.ad_id)   // AdManager「查看落地日志」深链
  await loadPages()
  await loadAccounts()
  await loadRedirectMap()
  setPreset('today')  // 默认今日（与其他看板一致；之前无默认=加载全量）
})
watch(() => route.query, (q) => {
  // 进日志 tab：有 slug/page_id/ad_id 就预筛，没有就清空（避免残留上次子码过滤）
  if (q.tab === 'logs') {
    fSlug.value = q.slug || ''
    fPage.value = q.page_id ? String(q.page_id) : ''
    fAd.value = q.ad_id ? String(q.ad_id) : ''
    offset.value = 0; load()
  }
})
</script>

<template>
  <div class="page">
    <div class="ctrl-bar">
      <h2 class="title">{{ t('lplogs.pageTitle') }} <span class="cnt">{{ total }}</span> <span v-if="fPage" class="pg-title">· {{ pageTitle() }}</span> <span v-if="fSlug" class="pg-slug">/a/{{ fSlug }}</span></h2>
      <DatePresetBar :presets="DATE_PRESETS" v-model="preset" @preset="setPreset" @custom="onCustomRange" />
      <el-select v-model="fPage" class="fl-sel" filterable :placeholder="t('lplogs.allLandingPages')" @change="search">
        <el-option :value="''" :label="t('lplogs.allLandingPages')" />
        <el-option v-for="p in pages" :key="p.id" :value="p.id" :label="p.title" />
      </el-select>
      <el-select v-model="fAct" class="fl-sel" filterable :placeholder="t('lplogs.allAccounts')" @change="search">
        <el-option :value="''" :label="t('lplogs.allAccounts')" />
        <el-option v-for="a in platAccounts" :key="a.act_id" :value="a.act_id" :label="(platChip(a) ? platChip(a).toUpperCase() + ' · ' : '') + a.name" />
      </el-select>
      <el-select v-model="fEvent" class="fl-sel" @change="search">
        <el-option v-for="o in EVENT_TYPES" :key="o.v" :value="o.v" :label="o.l" />
      </el-select>
      <el-select v-model="fDecision" class="fl-sel" @change="search">
        <el-option v-for="o in DECISIONS" :key="o.v" :value="o.v" :label="o.l" />
      </el-select>
      <el-select v-model="fSource" class="fl-sel" @change="search">
        <el-option :value="''" :label="t('lplogs.allSources')" />
        <el-option value="controlled" :label="t('lplogs.adPrefix') + '·' + t('lplogs.srcControlled')" />
        <el-option value="external" :label="t('lplogs.adPrefix') + '·' + t('lplogs.srcExternal')" />
        <el-option value="crawler" :label="t('lplogs.srcCrawlerShort')" />
        <el-option value="placeholder" :label="t('lplogs.srcPlaceholder')" />
        <el-option value="unknown" :label="t('lplogs.directAccess')" />
      </el-select>
      <input v-model="fSlug" class="txt" :placeholder="t('lplogs.subcode')" @input="debounceSearch" @keyup.enter="search" />
      <input v-model="fAd" class="txt" :placeholder="t('lplogs.adId')" @input="debounceSearch" @keyup.enter="search" />
      <input v-model="fQ" class="txt q" :placeholder="t('lplogs.searchPlaceholder')" @input="debounceSearch" @keyup.enter="search" />
      <button class="ctrl-btn" @click="reset">{{ t('lplogs.reset') }}</button>
    </div>
    <div class="stats-bar" v-if="stats">
      <span class="stats-label">{{ t('lplogs.sourceDistribution') }}<span class="stats-win">{{ stats.window === 'today' ? t('common.today') : t('lplogs.selectedRange') }} · {{ stats.total }}</span></span>
      <button v-for="c in statChips" :key="c.key" class="stat-chip" :class="[c.cls, { on: fSource === c.key }]" @click="toggleSource(c.key)">
        {{ c.label }} <b>{{ stats[c.key] || 0 }}</b>
      </button>
      <span v-if="stats.datacenter" class="stat-chip static src-bad" :title="t('lplogs.datacenterHint')">⚠ {{ t('lplogs.datacenter') }} {{ stats.datacenter }}</span>
    </div>
    <div class="tbl" v-loading="loading">
      <div class="row head">
        <div>{{ t('lplogs.colTime') }}</div><div>{{ t('lplogs.subcode') }}</div><div>{{ t('lplogs.colAccount') }}</div><div>{{ t('lplogs.adId') }}</div><div>{{ t('lplogs.colPixel') }}</div><div>{{ t('lplogs.colDevice') }}</div><div>{{ t('lplogs.colRegion') }}</div><div>ASN</div><div>{{ t('lplogs.colAction') }}</div><div>{{ t('lplogs.colReason') }}</div><div>{{ t('lplogs.colSourceDest') }}</div>
      </div>
      <div v-for="e in items" :key="e.id" class="row">
        <div class="t-time">{{ fmtTime(e.created_at) }}</div>
        <div><code class="slug" @click="goSlug(e.slug)" :title="t('lplogs.clickFilterSubcode', { slug: e.slug })">/a/{{ e.slug }}</code></div>
        <div class="t-act" :class="{ clk: e.act_id }" :title="e.act_id ? t('lplogs.clickFilterAccount', { name: e.act_name }) : ''" @click="goAct(e.act_id)">{{ e.act_name || (e.act_id ? e.act_id.slice(-8) : '-') }}</div>
        <div class="t-ad" :title="(e.act_name || e.act_id || '') + (e.fbclid ? '\n' + t('lplogs.fbClickId') + ': ' + e.fbclid : '')"><span class="ad-id" :class="{ clk: e.ad_id }" :title="e.ad_id ? t('lplogs.clickFilterAd', { adId: e.ad_id }) : ''" @click="goAd(e.ad_id)">{{ e.ad_id || '-' }}</span><button v-if="e.ad_id" class="rd-link" :class="{on: redirectMap[e.ad_id]}" @click="openRedirect(e.ad_id)" :title="redirectMap[e.ad_id] ? t('lplogs.redirectSetTitle', { url: redirectMap[e.ad_id] }) : t('lplogs.setRedirect')">{{ t('lplogs.redirectShort') }}</button></div>
        <div class="t-px" :title="e.fired_pixel_ids ? t('lplogs.firedPixelHint', { ids: e.fired_pixel_ids }) : t('lplogs.pixelNotRecorded')">
          <code v-if="e.fired_pixel_ids">{{ pixelLabel(e) }}</code>
          <span v-else class="muted">—</span>
        </div>
        <div class="t-dev" :title="e.user_agent || deviceLabel(e)">{{ deviceLabel(e) }}</div>
        <div class="t-geo"><span class="geo-c">{{ countryLabel(e.country) || '-' }}</span> <span class="geo-city">{{ e.city || '' }}</span></div>
        <div class="t-asn" :class="{ 'asn-dc': e.asn_type === 'datacenter' }" :title="asnTitle(e)">{{ asnDisplay(e) }}</div>
        <div>
          <span class="ev" :class="decisionClass(e.decision, e.event_type)">{{ eventLabel(e.event_type) }}</span>
          <span v-if="e.decision && e.decision !== e.event_type" class="dec">·{{ decisionLabel(e.decision) }}</span>
        </div>
        <div class="t-reason" :title="e.reason || ''">{{ reasonLabel(e.reason) || '-' }}</div>
        <div class="t-src">
          <template v-if="hasRedirect(e)">
            <a v-if="e.target_url" :href="e.target_url" target="_blank" rel="noopener" :title="t('lplogs.redirectTargetTitle', { url: e.target_url })">{{ e.target_url }}</a>
            <span v-else class="muted">-</span>
          </template>
          <span v-else :class="srcClass(e)" :title="srcTitle(e)">{{ srcLabel(e) }}</span>
        </div>
      </div>
      <div v-if="!items.length && !loading" class="empty">{{ fSlug ? t('lplogs.emptyWithSubcode', { slug: fSlug }) : t('lplogs.empty') }}</div>
    </div>
    <div v-if="total > limit" class="pager">
      <button class="ctrl-btn sm" :disabled="offset === 0" @click="prev">{{ t('lplogs.prevPage') }}</button>
      <span class="pg-info">{{ offset + 1 }}–{{ Math.min(offset + limit, total) }} / {{ t('lplogs.totalUnit', { n: total }) }}</span>
      <button class="ctrl-btn sm" :disabled="offset + limit >= total" @click="next">{{ t('lplogs.nextPage') }}</button>
      <input v-model="jumpTo" class="jump-inp" type="number" min="1" :max="Math.ceil(total/limit)" :placeholder="t('audit.jumpPh')" @keyup.enter="goPage" />
      <button class="ctrl-btn sm" @click="goPage">{{ t('audit.jumpGo') }}</button>
    </div>

    <el-dialog v-model="redirectDialog" :title="t('lplogs.redirectDialogTitle', { adId: redirectAd })" width="440px" :close-on-click-modal="false" :destroy-on-close="true" append-to-body>
      <div style="display:flex;flex-direction:column;gap:8px">
        <label style="font-size:12px;color:var(--t3)">{{ t('lplogs.redirectDialogHint') }}</label>
        <input v-model.trim="redirectInput" class="txt" style="width:100%" placeholder="https://..." />
        <div style="font-size:11px;color:var(--t3);line-height:1.5">{{ t('lplogs.redirectDialogDesc') }}</div>
      </div>
      <template #footer>
        <button class="ctrl-btn" :disabled="redirectSaving" @click="redirectDialog = false">{{ t('common.cancel') }}</button>
        <button v-if="redirectMap[redirectAd]" class="ctrl-btn" :disabled="redirectSaving" @click="redirectInput=''; saveRedirect()">{{ t('lplogs.resetDefault') }}</button>
        <button class="ctrl-btn primary" :disabled="redirectSaving" @click="saveRedirect">{{ redirectSaving ? t('common.saving') + '…' : t('common.save') }}</button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ctrl-bar { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 12px }
.title { font-size: 18px; margin-right: auto }
.cnt { font-size: 13px; color: var(--t3); font-weight: 400 }
.pg-title { font-size: 14px; color: var(--t2); font-weight: 500 }
.pg-slug { font-size: 12px; color: var(--ac); font-family: monospace }
.txt { height: 32px; padding: 0 10px; background: var(--bg2); color: var(--t1); border: 1px solid var(--bd); border-radius: var(--rs); font-size: 13px; box-sizing: border-box; color-scheme: dark }
.txt { width: 96px }
.txt.q { width: 180px }
.txt:focus { outline: none; border-color: var(--ac) }
.txt::placeholder { color: var(--t3) }
/* el-select 筛选（与 .txt 同 32px 高，默认尺寸；5 个下拉统一宽度） */
.fl-sel { width: 140px; min-width: 130px; flex-shrink: 0 }
.fl-sel :deep(.el-input__wrapper) { height: 32px; min-height: 32px; border-radius: var(--rs); box-shadow: 0 0 0 1px var(--bd) inset; background: var(--bg2) }
.fl-sel :deep(.el-input__inner) { height: 32px; line-height: 30px; font-size: 13px }
.ctrl-btn { height: 32px; padding: 0 14px; line-height: 30px; font-size: 13px; background: var(--bg2); color: var(--t2); border: 1px solid var(--bd); border-radius: var(--rs); cursor: pointer; box-sizing: border-box; white-space: nowrap }
.ctrl-btn:hover { color: var(--t1); border-color: var(--bd2) }
.ctrl-btn.primary { background: var(--ac); color: #fff; border-color: var(--ac) }
.ctrl-btn.sm { padding: 0 10px; font-size: 12px }
.ctrl-btn.on { background: var(--ac); color: #fff; border-color: var(--ac) }
.ctrl-btn:disabled { opacity: .5; cursor: not-allowed }
.tbl { display: flex; flex-direction: column; border: 1px solid var(--bd); border-radius: 10px; overflow-x: auto }
.row { display: grid; grid-template-columns: 140px 76px 130px 132px 86px 110px 112px 68px 80px 78px minmax(80px,1fr); gap: 8px; padding: 7px 12px; align-items: center; font-size: 12px; border-bottom: 1px solid var(--bd); min-width: 1160px }
.row.head { background: var(--bg2); color: var(--t3); font-size: 11px; font-weight: 600 }
.row:last-child { border-bottom: none }
.row:hover { background: var(--bg2) }
.t-time { color: var(--t2); white-space: nowrap; font-variant-numeric: tabular-nums }
.slug { color: var(--ac); cursor: pointer; font-size: 11px; font-family: monospace }
.slug:hover { text-decoration: underline }
.t-ad { color: var(--t3); font-size: 11px; display: flex; align-items: center; gap: 4px; min-width: 0; font-variant-numeric: tabular-nums }
.ad-id { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex: 1 1 auto }
.ad-id.clk { color: var(--ac); cursor: pointer }
.ad-id.clk:hover { text-decoration: underline }
.t-act { color: var(--t2); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.t-act.clk { color: var(--ac); cursor: pointer }
.t-act.clk:hover { text-decoration: underline }
.rd-link { font-size: 10px; padding: 1px 5px; border: 1px solid var(--bd); background: transparent; color: var(--t3); border-radius: 4px; cursor: pointer; flex-shrink: 0 }
.rd-link:hover { color: var(--ac); border-color: var(--ac) }
.rd-link.on { color: var(--ac); border-color: var(--ac); background: rgba(10,132,255,.1) }
.t-dev { color: var(--t2); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.t-px { overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.t-px code { font-family: monospace; font-size: 10px; color: var(--ac); font-variant-numeric: tabular-nums }
.t-asn { color: var(--t3); font-size: 11px; font-family: monospace; font-variant-numeric: tabular-nums }
.asn-dc { color: var(--error); font-weight: 600 }
.ev { font-size: 11px; padding: 1px 6px; border-radius: 4px; background: var(--bg3); color: var(--t2); white-space: nowrap }
.ev.ok { color: var(--success) } .ev.warn { color: var(--warning) } .ev.err { color: var(--error) }
.dec { color: var(--t3); font-size: 11px }
.t-geo, .t-reason { color: var(--t2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.geo-c { color: var(--t1) }
.geo-city { color: var(--t3); font-size: 10px }
.t-src { overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.t-src a { color: var(--ac); font-size: 11px }
.t-src a:hover { text-decoration: underline }
.src-ok { color: var(--success); font-size: 11px; font-weight: 500 }
.src-bad { color: var(--error); font-size: 11px; font-weight: 600 }
.src-warn { color: var(--warning); font-size: 11px; font-weight: 500 }
.src-fb { color: var(--ac); font-size: 11px; font-weight: 500 }
.src-bot { color: #a78bfa; font-size: 11px; font-weight: 500 }
.muted { color: var(--t3) }
.empty { padding: 40px; text-align: center; color: var(--t3); font-size: 13px }
.pager { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 12px; flex-wrap: wrap }
.pg-info { font-size: 12px; color: var(--t3) }
.jump-inp{width:64px;background:var(--bg3);color:var(--t1);border:1px solid var(--bd);border-radius:var(--rs);padding:5px 8px;font-size:12px}
.stats-bar { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; padding: 7px 10px; background: var(--bg2); border: 1px solid var(--bd); border-radius: 8px }
.stats-label { font-size: 12px; color: var(--t3); margin-right: 4px }
.stats-win { color: var(--t2); margin-left: 4px }
.stat-chip { height: 24px; padding: 0 9px; line-height: 22px; font-size: 11px; background: var(--bg3); color: var(--t2); border: 1px solid var(--bd); border-radius: 12px; cursor: pointer; white-space: nowrap; box-sizing: border-box }
.stat-chip b { font-weight: 600; margin-left: 3px; color: var(--t1) }
.stat-chip:hover { border-color: var(--bd2) }
.stat-chip.on { background: var(--ac); color: #fff; border-color: var(--ac) }
.stat-chip.on b { color: #fff }
.stat-chip.static { cursor: default; background: transparent; border-color: rgba(255,107,107,.4); color: var(--error) }
.stat-chip.src-ok { color: var(--success) } .stat-chip.src-bad { color: var(--error) }
.stat-chip.src-warn { color: var(--warning) } .stat-chip.src-bot { color: #a78bfa }
.stat-chip.on.src-ok, .stat-chip.on.src-bad, .stat-chip.on.src-warn, .stat-chip.on.src-bot { color: #fff }
</style>
