<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { GET, POST } from '../api'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { DATE_PRESETS, presetRange } from '../composables/useDateRange'

const { t, locale } = useI18n()
const route = useRoute()

const EVENT_TYPES = computed(() => [
  { v: '', l: t('lplogs.actionAll') }, { v: 'visit', l: t('lplogs.actionVisit') }, { v: 'click', l: t('lplogs.actionClick') },
  { v: 'submit', l: t('lplogs.actionSubmit') }, { v: 'redirect', l: t('lplogs.actionRedirect') }, { v: 'block', l: t('lplogs.actionBlock') },
  { v: 'pass', l: t('lplogs.actionPass') }, { v: 'error', l: t('lplogs.actionError') },
])
const DECISIONS = computed(() => [
  { v: '', l: t('lplogs.resultAll') }, { v: 'allow', l: t('lplogs.actionPass') },
  { v: 'block', l: t('lplogs.actionBlock') }, { v: 'redirect', l: t('lplogs.actionRedirect') },
])

// 原因 → 中文
const REASON_LABEL = computed(() => ({
  pass: t('lplogs.reasonPass'), device_block: t('lplogs.reasonDeviceBlock'), ua_block: t('lplogs.reasonUaBlock'),
  country_block: t('lplogs.reasonCountryBlock'), country_allow: t('lplogs.reasonCountryAllow'), dedup: t('lplogs.reasonDedup'),
}))
const reasonLabel = (r) => REASON_LABEL.value[r] || r || ''

// 国家码 → 国名（CF 给的是 2 字母 ISO 码；国名英文通用，zh/en 共用）
const COUNTRY = {
  US: 'United States', GB: 'United Kingdom', CA: 'Canada', AU: 'Australia', NZ: 'New Zealand', IE: 'Ireland',
  DE: 'Germany', FR: 'France', IT: 'Italy', ES: 'Spain', PT: 'Portugal', NL: 'Netherlands', BE: 'Belgium',
  CH: 'Switzerland', AT: 'Austria', SE: 'Sweden', NO: 'Norway', DK: 'Denmark', FI: 'Finland', PL: 'Poland',
  RO: 'Romania', GR: 'Greece', CZ: 'Czechia', HU: 'Hungary', BG: 'Bulgaria', RU: 'Russia', UA: 'Ukraine',
  TR: 'Turkey', IL: 'Israel', AE: 'UAE', SA: 'Saudi Arabia', QA: 'Qatar', KW: 'Kuwait', EG: 'Egypt',
  ZA: 'South Africa', NG: 'Nigeria', KE: 'Kenya', GH: 'Ghana', MA: 'Morocco',
  BR: 'Brazil', MX: 'Mexico', AR: 'Argentina', CL: 'Chile', CO: 'Colombia', PE: 'Peru', VE: 'Venezuela',
  IN: 'India', PK: 'Pakistan', BD: 'Bangladesh', LK: 'Sri Lanka', NP: 'Nepal',
  ID: 'Indonesia', TH: 'Thailand', VN: 'Vietnam', PH: 'Philippines', MY: 'Malaysia', SG: 'Singapore', KH: 'Cambodia',
  MM: 'Myanmar', LA: 'Laos', JP: 'Japan', KR: 'South Korea', CN: 'China', HK: 'Hong Kong', TW: 'Taiwan', MO: 'Macao',
}
const countryLabel = (c) => {
  if (!c) return ''
  const name = COUNTRY[String(c).toUpperCase()]
  return name ? `${name} ${c}` : c
}
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
  if (e.referrer) return t('lplogs.sourceLabel') + '：' + e.referrer
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

const pages = ref([])
const accounts = ref([])
const items = ref([])
const total = ref(0)
const offset = ref(0)
const limit = 50
const loading = ref(false)

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
  loading.value = true
  loadStats()  // 并行刷新分布（非阻塞）
  try {
    const r = await GET('/landing/logs?' + new URLSearchParams(buildParams()).toString())
    items.value = r.items || []
    total.value = r.total || 0
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  loading.value = false
}
const search = () => { offset.value = 0; load() }
const reset = () => {
  fPage.value = ''; fAct.value = ''; fSlug.value = ''; fAd.value = ''; fEvent.value = ''; fDecision.value = ''; fSource.value = ''
  fFrom.value = ''; fTo.value = ''; fQ.value = ''; preset.value = ''; offset.value = 0; load()
}
// 日期快捷（按北京业务日，和后端查询基准对齐）
const preset = ref('')
const setPreset = (k) => {
  const r = presetRange(k)
  if (r) { fFrom.value = r[0]; fTo.value = r[1] }
  preset.value = k; offset.value = 0; load()
}
const onDateManual = () => { preset.value = '' }  // 手动改日期 → 取消快捷高亮
const prev = () => { if (offset.value > 0) { offset.value = Math.max(0, offset.value - limit); load() } }
const next = () => { if (offset.value + limit < total.value) { offset.value += limit; load() } }

const fmtTime = (iso) => {
  if (!iso) return '-'
  try { return new Date(iso).toLocaleString(locale.value === 'en' ? 'en-US' : 'zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) }
  catch (e) { return iso }
}
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
const saveRedirect = async () => {
  try { await POST('/ads/redirects', { ad_id: redirectAd.value, target_url: redirectInput.value.trim() })
    if (redirectInput.value.trim()) redirectMap.value = { ...redirectMap.value, [redirectAd.value]: redirectInput.value.trim() }
    else { const m = { ...redirectMap.value }; delete m[redirectAd.value]; redirectMap.value = m }
    ElMessage.success(redirectInput.value.trim() ? t('lplogs.redirectSet') : t('lplogs.redirectReset')); redirectDialog.value = false
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
}
const eventLabel = (v) => EVENT_TYPES.value.find(x => x.v === v)?.l || v || '-'
const decisionLabel = (v) => DECISIONS.value.find(x => x.v === v)?.l || v || ''
const decisionClass = (d, et) => d === 'block' || et === 'block' ? 'err' : (d === 'allow' || et === 'visit' ? 'ok' : 'warn')
const pageTitle = () => {
  const p = pages.value.find(x => String(x.id) === String(fPage.value))
  return p ? p.title : t('lplogs.allLandingPages')
}

onMounted(async () => {
  if (route.query.slug) fSlug.value = route.query.slug
  if (route.query.page_id) fPage.value = String(route.query.page_id)
  await loadPages()
  await loadAccounts()
  await loadRedirectMap()
  setPreset('today')  // 默认今日（与其他看板一致；之前无默认=加载全量）
})
watch(() => route.query, (q) => {
  // 进日志 tab：有 slug/page_id 就预筛，没有就清空（避免残留上次子码过滤）
  if (q.tab === 'logs') {
    fSlug.value = q.slug || ''
    fPage.value = q.page_id ? String(q.page_id) : ''
    offset.value = 0; load()
  }
})
</script>

<template>
  <div class="page">
    <div class="ctrl-bar">
      <h2 class="title">{{ t('lplogs.pageTitle') }} <span class="cnt">{{ total }}</span> <span v-if="fPage" class="pg-title">· {{ pageTitle() }}</span> <span v-if="fSlug" class="pg-slug">/a/{{ fSlug }}</span></h2>
      <button v-for="opt in DATE_PRESETS" :key="opt.key" class="ctrl-btn sm" :class="{ on: preset === opt.key }" @click="setPreset(opt.key)">{{ opt.label }}</button>
      <input type="date" v-model="fFrom" class="date-input" @change="onDateManual" />
      <span class="sep">—</span>
      <input type="date" v-model="fTo" class="date-input" @change="onDateManual" />
      <select v-model="fPage" class="sel" @change="search">
        <option value="">{{ t('lplogs.allLandingPages') }}</option>
        <option v-for="p in pages" :key="p.id" :value="p.id">{{ p.title }}</option>
      </select>
      <select v-model="fAct" class="sel" @change="search">
        <option value="">{{ t('lplogs.allAccounts') }}</option>
        <option v-for="a in accounts" :key="a.act_id" :value="a.act_id">{{ a.name }}</option>
      </select>
      <select v-model="fEvent" class="sel" @change="search">
        <option v-for="o in EVENT_TYPES" :key="o.v" :value="o.v">{{ o.l }}</option>
      </select>
      <select v-model="fDecision" class="sel" @change="search">
        <option v-for="o in DECISIONS" :key="o.v" :value="o.v">{{ o.l }}</option>
      </select>
      <select v-model="fSource" class="sel" @change="search">
        <option value="">{{ t('lplogs.allSources') }}</option>
        <option value="controlled">{{ t('lplogs.adPrefix') }}·{{ t('lplogs.srcControlled') }}</option>
        <option value="external">{{ t('lplogs.adPrefix') }}·{{ t('lplogs.srcExternal') }}</option>
        <option value="crawler">{{ t('lplogs.srcCrawlerShort') }}</option>
        <option value="placeholder">{{ t('lplogs.srcPlaceholder') }}</option>
        <option value="unknown">{{ t('lplogs.directAccess') }}</option>
      </select>
      <input v-model="fSlug" class="txt" :placeholder="t('lplogs.subcode')" @keyup.enter="search" />
      <input v-model="fAd" class="txt" :placeholder="t('lplogs.adId')" @keyup.enter="search" />
      <input v-model="fQ" class="txt q" :placeholder="t('lplogs.searchPlaceholder')" @keyup.enter="search" />
      <button class="ctrl-btn primary" @click="search">{{ t('common.search') }}</button>
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
    </div>

    <el-dialog v-model="redirectDialog" :title="t('lplogs.redirectDialogTitle', { adId: redirectAd })" width="440px" :close-on-click-modal="false" :destroy-on-close="true" append-to-body>
      <div style="display:flex;flex-direction:column;gap:8px">
        <label style="font-size:12px;color:var(--t3)">{{ t('lplogs.redirectDialogHint') }}</label>
        <input v-model.trim="redirectInput" class="txt" style="width:100%" placeholder="https://..." />
        <div style="font-size:11px;color:var(--t3);line-height:1.5">{{ t('lplogs.redirectDialogDesc') }}</div>
      </div>
      <template #footer>
        <button class="ctrl-btn" @click="redirectDialog = false">{{ t('common.cancel') }}</button>
        <button v-if="redirectMap[redirectAd]" class="ctrl-btn" @click="redirectInput=''; saveRedirect()">{{ t('lplogs.resetDefault') }}</button>
        <button class="ctrl-btn primary" @click="saveRedirect">{{ t('common.save') }}</button>
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
.date-input, .sel, .txt { height: 32px; padding: 0 10px; background: var(--bg2); color: var(--t1); border: 1px solid var(--bd); border-radius: var(--rs); font-size: 13px; box-sizing: border-box; color-scheme: dark }
.sel { min-width: 96px }
.txt { width: 96px }
.txt.q { width: 180px }
.date-input:focus, .sel:focus, .txt:focus { outline: none; border-color: var(--ac) }
.sep { color: var(--t3); font-size: 12px }
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
.pager { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 12px }
.pg-info { font-size: 12px; color: var(--t3) }
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
