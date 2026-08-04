<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { GET, POST, PUT, DELETE } from '../api'
import { isSuperadminSync } from '../router'
import { lpStatus, subcodeStatus } from '../composables/useStatus'
import { ElMessage, ElMessageBox } from 'element-plus'
import LandingLogs from './LandingLogs.vue'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()

// 落地页 内部 tab：管理 / 日志（日志归纳进来，不再是独立侧栏项）
const tab = ref(route.query.tab === 'logs' ? 'logs' : 'manage')
watch(() => route.query.tab, (tv) => { if (tv === 'logs' || tv === 'manage') tab.value = tv })

// ── 落地页列表 ──
const pages = ref([])
const loading = ref(true)
// 异常置顶：FB屏蔽 > 通过率低(有量) > 屏蔽数多 > 其余（需关注的在上）
const sortedPages = computed(() => {
  return [...pages.value].sort((a, b) => {
    const fb = (x) => (x.last_fb_status === 'fail' ? 0 : x.last_fb_status === 'warn' ? 1 : 2)
    if (fb(a) !== fb(b)) return fb(a) - fb(b)
    const rate = (x) => ((x.visit_count||0) >= 10 ? (x.pass_rate||0) : 999)  // 有量才看通过率，没量排后
    if (rate(a) !== rate(b)) return rate(a) - rate(b)
    return (b.block_count||0) - (a.block_count||0)
  })
})
const loadPages = async () => {
  loading.value = true
  try { pages.value = await GET('/landing/pages') }
  catch (e) { ElMessage.error(e.message || t('landing.loadFail')) }
  finally { loading.value = false }
}

// ── 资产库（发布抽屉选项）──
const pixels = ref([])
const ttPixels = computed(() => pixels.value.filter(p => (p.platform || 'fb') === 'tt'))
const domains = ref([])
const templates = ref([])
const loadLib = async () => {
  const [p, d, t] = await Promise.all([
    GET('/landing-lib/pixels').catch(() => []),
    GET('/landing-lib/domains').catch(() => []),
    GET('/landing-lib/protection-templates').catch(() => []),
  ])
  pixels.value = p; domains.value = d; templates.value = t
}

// ── 发布/编辑抽屉 ──
const drawerOpen = ref(false)
const editingId = ref(null)
const saving = ref(false)
const emptyForm = () => ({
  title: '', description: '', target_urls: [], rotation_mode: 'first',
  custom_domain: '', custom_domains: [], bound_subdomains: [], pixel_ids: [], tt_pixel_ids: [], conversion_events: [], tt_conversion_events: [],
  redirect_mode: 'display', block_enabled: false, preview_enabled: false, preview_url: '',
  subdomain_prefix: '', dedup_enabled: false, dedup_window_hours: 24,
  protection_rules: {}, block_target: '', block_html: '', template_key: '', template_id: null,
})
const form = ref(emptyForm())
const tplDesc = computed(() => {
  const tpl = templates.value.find(x => x.key === form.value.template_key)
  return tpl?.desc || ''
})
const convEventOptions = computed(() => [
  { v: 'Purchase', l: t('landing.convPurchase') },
  { v: 'Contact', l: t('landing.convContact') },
  { v: 'Lead', l: t('landing.convLead') },
  { v: 'AddToCart', l: t('landing.convAddToCart') },
  { v: 'ViewContent', l: t('landing.convViewContent') },
  { v: 'InitiateCheckout', l: t('landing.convInitiateCheckout') },
  { v: 'Subscribe', l: t('landing.convSubscribe') },
  { v: 'CompleteRegistration', l: t('landing.convCompleteRegistration') },
])
const ttConvEventOptions = computed(() => [
  { v: 'CompletePayment', l: t('landing.convCompletePayment') },
  { v: 'PlaceAnOrder', l: t('landing.convPlaceAnOrder') },
  { v: 'SubmitForm', l: t('landing.convSubmitForm') },
  { v: 'Contact', l: t('landing.convContact') },
  { v: 'AddToCart', l: t('landing.convAddToCart') },
  { v: 'CompleteRegistration', l: t('landing.convCompleteRegistration') },
  { v: 'ViewContent', l: t('landing.convViewContent') },
  { v: 'InitiateCheckout', l: t('landing.convInitiateCheckout') },
])
const rotationOptions = computed(() => [
  { v: 'first', l: t('landing.rotFirst') },
  { v: 'random', l: t('landing.rotRandom') },
  { v: 'sequential', l: t('landing.rotSequential') },
])
const openCreate = () => {
  editingId.value = null
  form.value = emptyForm()
  // 新页默认开「屏蔽机房/VPN」（用平台集中清单）+ 屏蔽爬虫 + 必带广告参数——新页统一规范
  form.value.protection_rules = {
    datacenter_block: datacenterAsns.value.map(d => d.asn),
    ua_block: ['bot','crawler','spider','googlebot','bingbot','facebookexternalhit','preview','debug'],
    required_query: ['ad'],
  }
  form.value.block_enabled = true
  drawerOpen.value = true
}
const openEdit = async (p) => {
  editingId.value = p.id
  try {
    const detail = await GET(`/landing/pages/${p.id}`)
    form.value = {
      title: detail.title || '', description: detail.description || '', custom_domain: detail.custom_domain || '',
      target_urls: detail.target_urls || [], rotation_mode: detail.rotation_mode || 'first',
      custom_domains: detail.custom_domains || (detail.custom_domain ? [detail.custom_domain.replace(/^https?:\/\//,'')] : []),
      pixel_ids: detail.pixel_ids || [], tt_pixel_ids: detail.tt_pixel_ids || [], conversion_events: detail.conversion_events || [], tt_conversion_events: detail.tt_conversion_events || [], bound_subdomains: detail.bound_subdomains || [],
      redirect_mode: detail.redirect_mode || 'display',
      block_enabled: !!detail.block_enabled,
      preview_enabled: !!detail.preview_enabled, preview_url: detail.preview_url || '',
      subdomain_prefix: detail.subdomain_prefix || '', dedup_enabled: !!detail.dedup_enabled, dedup_window_hours: detail.dedup_window_hours || 24,
      protection_rules: { ...(detail.protection_rules || {}) },
      block_target: detail.protection_rules?.block_target || '',
      block_html: detail.protection_rules?.block_html || '',
      template_key: '',
      template_id: detail.template_id || null,
    }
    drawerOpen.value = true
  } catch (e) { ElMessage.error(e.message || t('landing.loadFail')) }
}

// ── 防护规则编辑器（快速 toggle + 高级自定义）──
const COUNTRIES = ['US','GB','CA','AU','DE','FR','JP','KR','SG','MY','TH','VN','ID','PH','BR','MX','IN','AE','SA','EG','ZA','NG','KE','HK','TW']
const SOURCES = ['facebook','instagram','google','tiktok','other']
const DEVICES = ['desktop','tablet','mobile']
const PLATFORMS = ['desktop','mobile','windows','ios','android','mac','linux','chrome','safari','edge','firefox','other']
// 主流机房/云/VPS ASN（CF cf.asn 给纯数字，这里存数字字符串）。VPN/抓取农场多跑在这些段上。
// 机房/VPN ASN 清单：从后端拉（平台级集中维护，改后端 → 这里自动更新 → 新页/预设用最新）
const datacenterAsns = ref([])
const loadAsnBlocklist = async () => {
  try { const r = await GET('/landing/asn-blocklist'); datacenterAsns.value = r.asns || [] }
  catch {}
}
const showAdvanced = ref(false)
const QUICK_GUARDS = computed(() => [
  { key: 'bots', label: t('landing.guardBots'), rules: { ua_block: ['bot','crawler','spider','googlebot','bingbot','slurp','duckduckbot','baiduspider','yandexbot','facebookexternalhit','preview','debug'] } },
  { key: 'datacenter', label: t('landing.guardDatacenter'), rules: { datacenter_block: datacenterAsns.value.map(d => d.asn) } },
  { key: 'us_only', label: t('landing.guardUsOnly'), rules: { country_allow: ['US'] } },
  { key: 'block_desktop', label: t('landing.guardBlockDesktop'), rules: { device_block: ['desktop'] } },
  { key: 'block_tablet', label: t('landing.guardBlockTablet'), rules: { device_block: ['tablet'] } },
  { key: 'block_preview', label: t('landing.guardBlockPreview'), rules: { referer_block: ['preview','debug'], query_block: ['preview','debug'] } },
  { key: 'require_ad', label: t('landing.guardRequireAd'), rules: { required_query: ['ad'] } },
])
const guardActive = (g) => Object.entries(g.rules).every(([k, vals]) => {
  const cur = form.value.protection_rules[k] || []
  return vals.every(v => cur.includes(v))
})
const toggleGuard = (g) => {
  const r = { ...form.value.protection_rules }
  if (guardActive(g)) {
    Object.entries(g.rules).forEach(([k, vals]) => {
      const cur = (r[k] || []).filter(v => !vals.includes(v))
      if (cur.length) r[k] = cur; else delete r[k]
    })
  } else {
    Object.entries(g.rules).forEach(([k, vals]) => {
      r[k] = [...new Set([...(r[k] || []), ...vals])]
    })
  }
  form.value.protection_rules = r
}
const guardSummary = computed(() => {
  const r = form.value.protection_rules
  const parts = []
  if (r.ua_block?.length) parts.push(t('landing.sumBots', { n: r.ua_block.length }))
  if (r.datacenter_block?.length) parts.push(t('landing.sumDatacenter', { n: r.datacenter_block.length }))
  if (r.country_allow?.length) parts.push(t('landing.sumCountryAllow', { v: r.country_allow.join('/') }))
  if (r.country_block?.length) parts.push(t('landing.sumCountryBlock', { v: r.country_block.join('/') }))
  if (r.device_block?.length) parts.push(t('landing.sumDeviceBlock', { v: r.device_block.join('/') }))
  if (r.source_block?.length) parts.push(t('landing.sumSourceBlock', { v: r.source_block.join('/') }))
  if (r.referer_block?.length) parts.push(t('landing.sumReferer'))
  if (r.query_block?.length) parts.push(t('landing.sumQuery'))
  if (r.required_query?.length) parts.push(t('landing.sumRequired', { v: r.required_query.join(',') }))
  return parts.length ? parts.join(' · ') : ''
})
const ruleVal = (k) => form.value.protection_rules[k] || []
const setRule = (k, v) => {
  const r = { ...form.value.protection_rules }
  if (v && v.length) r[k] = v; else delete r[k]
  form.value.protection_rules = r
}

const save = async () => {
  if (!form.value.title.trim()) return ElMessage.warning(t('landing.warnTitle'))
  if (!form.value.custom_domains.length) return ElMessage.warning(t('landing.warnDomain'))
  if (form.value.redirect_mode === 'redirect' && !form.value.target_urls.length) {
    return ElMessage.warning(t('landing.warnRedirectUrl'))
  }
  if (form.value.redirect_mode === 'display' && !form.value.target_urls.length) {
    return ElMessage.warning(t('landing.warnTargetUrl'))
  }
  if (form.value.block_enabled && !form.value.block_target && !form.value.block_html) {
    return ElMessage.warning(t('landing.warnBlockConfig'))
  }
  saving.value = true
  const rules = { ...form.value.protection_rules }
  if (form.value.block_target) rules.block_target = form.value.block_target
  if (form.value.block_html) rules.block_html = form.value.block_html
  const body = {
    title: form.value.title.trim(), description: form.value.description,
    target_urls: form.value.target_urls, rotation_mode: form.value.rotation_mode,
    custom_domains: form.value.custom_domains, pixel_ids: form.value.pixel_ids, tt_pixel_ids: form.value.tt_pixel_ids, tt_conversion_events: form.value.tt_conversion_events,
    conversion_events: form.value.conversion_events || [],
    redirect_mode: form.value.redirect_mode, block_enabled: form.value.block_enabled,
    preview_enabled: form.value.preview_enabled,
    subdomain_prefix: form.value.subdomain_prefix, dedup_enabled: form.value.dedup_enabled, dedup_window_hours: form.value.dedup_window_hours,
    protection_rules: rules, template_id: form.value.template_id,
  }
  try {
    let resp
    if (editingId.value) {
      resp = await PUT(`/landing/pages/${editingId.value}`, body)
      ElMessage.success(t('common.saved'))
    } else {
      resp = await POST('/landing/publish', body)
      ElMessage.success(t('landing.published'))
    }
    drawerOpen.value = false
    await loadPages()
    if (resp && resp.self_check) showSelfCheck(resp.self_check, t('landing.scPostPublishTitle'))
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
  saving.value = false
}

const archive = async (p) => {
  try {
    await ElMessageBox.confirm(t('landing.archiveConfirm', { title: p.title }), t('common.confirm'), { type: 'warning' })
    await DELETE(`/landing/pages/${p.id}`); ElMessage.success(t('landing.archived')); await loadPages()
  } catch {}
}

// ── 落地页自检 ──
const healthResult = ref(null)
const healthCheckingId = ref(null)
// 自检报告弹窗（checkHealth 手动 + 发布后自动 共用）
const _esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
const showSelfCheck = (r, title) => {
  if (!r || !r.checks) return
  const lines = r.checks.map(c => {
    const ic = c.status === 'pass' ? '✅' : (c.status === 'warn' ? '⚠️' : '❌')
    const col = c.status === 'pass' ? 'var(--success)' : (c.status === 'warn' ? 'var(--warning)' : 'var(--error)')
    // detail 含用户可控的域名/目标URL，必须转义防 XSS
    return `<div style="margin:6px 0;line-height:1.5"><span style="color:${col};font-weight:600">${ic}</span> <b>${_esc(c.label)}</b>：<span style="color:var(--t3)">${_esc(c.detail)}</span></div>`
  }).join('')
  const overallTxt = r.overall === 'pass' ? t('landing.scOverallPass') : (r.overall === 'fail' ? t('landing.scOverallFail') : t('landing.scOverallWarn'))
  const note = title === t('landing.scPostPublishTitle') ? `<div style="font-size:11px;color:var(--t3);margin-bottom:8px">${t('landing.scPostPublishNote')}</div>` : ''
  ElMessageBox.alert(note + (lines || t('landing.scNoChecks')), `${title} · ${overallTxt}`, { dangerouslyUseHTMLString: true, confirmButtonText: t('landing.gotIt'), customClass: 'sc-alert' })
}
const checkHealth = async (p) => {
  healthCheckingId.value = p.id
  try {
    const r = await GET(`/landing/pages/${p.id}/health`)
    healthResult.value = r
    await loadPages()
    showSelfCheck(r, t('landing.scTitle'))
  } catch (e) { ElMessage.error(t('landing.scFail') + '：' + (e.message || '')) }
  healthCheckingId.value = null
}
const protTestResult = ref(null)
const protTesting = ref(false)
const runProtTest = async () => {
  protTesting.value = true
  try {
    const r = await POST('/landing/protection-test', { rules: form.value.protection_rules })
    protTestResult.value = r
  } catch (e) { ElMessage.error(t('landing.testFail') + '：' + (e.message || '')) }
  protTesting.value = false
}

// ── 子码抽屉 ──
const subOpen = ref(false)
const subPage = ref(null)
const subcodes = ref([])
const subLoading = ref(false)
const subCounts = ref({})
const subStatus = ref('all')   // all / unbound / active / trash
const subQ = ref('')
const subSort = ref('created')
const newSubCount = ref(1)
const openSubcodes = async (p) => {
  subPage.value = p; subOpen.value = true; newSubCount.value = 1
  subStatus.value = 'all'; subQ.value = ''; subSort.value = 'created'
  await loadSubcodes(p.id)
}
const loadSubcodes = async (pid) => {
  subLoading.value = true
  try {
    const ps = new URLSearchParams({ status: subStatus.value, sort: subSort.value })
    if (subQ.value.trim()) ps.set('q', subQ.value.trim())
    const r = await GET(`/subcodes?page_id=${pid}&${ps.toString()}`)
    subcodes.value = r.items || []
    subCounts.value = r.counts || {}
  }
  catch (e) { ElMessage.error(e.message || t('landing.loadFail')) }
  finally { subLoading.value = false }
}
const setSubStatus = (s) => { subStatus.value = s; loadSubcodes(subPage.value.id) }
const onSubSearch = () => loadSubcodes(subPage.value.id)
const archiveSub = async (s) => {
  try { await ElMessageBox.confirm(t('landing.subArchiveConfirm', { slug: s.slug }), t('landing.subArchiveTitle'), { type: 'warning' })
    await DELETE(`/subcodes/${s.id}`); ElMessage.success(t('landing.archived')); await loadSubcodes(subPage.value.id)
  } catch(e) { if (e !== 'cancel' && e?.message) ElMessage.error(t('landing.archiveFail') + '：' + e.message) }
}
const restoreSub = async (s) => {
  try { await POST(`/subcodes/${s.id}/restore`); ElMessage.success(t('landing.restored')); await loadSubcodes(subPage.value.id) }
  catch (e) { ElMessage.error(t('landing.restoreFail') + '：' + (e.message || '')) }
}
const hardDeleteSub = async (s) => {
  try { await ElMessageBox.confirm(t('landing.subHardDeleteConfirm', { slug: s.slug }), t('landing.hardDelete'), { type: 'warning', confirmButtonText: t('landing.hardDelete'), confirmButtonClass: 'el-button--danger' })
    await DELETE(`/subcodes/${s.id}?hard=1`); ElMessage.success(t('landing.hardDeleted')); await loadSubcodes(subPage.value.id)
  } catch(e) { if (e !== 'cancel' && e?.message) ElMessage.error(t('landing.deleteFail') + '：' + e.message) }
}
const subGenerating = ref(false)
const genSubcode = async () => {
  if (subGenerating.value) return
  const count = Math.min(Math.max(Number(newSubCount.value) || 1, 1), 50)
  subGenerating.value = true
  try {
    for (let i = 0; i < count; i++) {
      await POST('/subcodes/generate', { page_id: subPage.value.id })
    }
    ElMessage.success(t('landing.subGenerated', { n: count })); newSubCount.value = 1; await loadSubcodes(subPage.value.id)
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
  subGenerating.value = false
}
const subTargetEdit = ref({})
const startEditTarget = (s) => { subTargetEdit.value = { [s.id]: s.target_urls || '' } }
const saveSubTarget = async (s) => {
  try {
    await PUT(`/subcodes/${s.id}`, { target_urls: subTargetEdit.value[s.id] || '' })
    ElMessage.success(t('landing.subTargetSet')); delete subTargetEdit.value[s.id]; await loadSubcodes(subPage.value.id)
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
}
const copyUrl = (slug) => {
  // custom_domain = 该页绑定的子域名公开地址（如 gocal75.marketbriefnow.xyz）；
  // custom_domains = 根域名列表（仅兜底）。优先用子域名，避免投放到根域。
  const base = (subPage.value?.custom_domain || subPage.value?.custom_domains?.[0] || '').replace(/^https?:\/\//, '')
  if (!base) { ElMessage.warning(t('landing.copyUrlNoDomain')); return }
  const url = `https://${base}/a/${slug}?ad={{ad.id}}`
  navigator.clipboard?.writeText(url)
  // 引导：说明 {{ad.id}} 占位符——FB 广告层级 URL 参数会自动替换成实际广告 ID，用于子码自动绑定
  ElMessage({
    message: t('landing.copiedHtml', { url: _esc(url), macro: '{{ad.id}}' }),
    dangerouslyUseHTMLString: true, type: 'success', duration: 6000,
  })
}
// 子码 FB 封禁检测（单个 + 批量）
const subFbStatus = ref({})  // {slug: {status, detail, loading}}
const checkSubFb = async (s) => {
  subFbStatus.value[s.slug] = { loading: true }
  try {
    const r = await POST('/subcodes/fb-check', { page_id: subPage.value.id, slug: s.slug })
    subFbStatus.value[s.slug] = { status: r.status, detail: r.detail }
    if (r.status === 'fail') ElMessage.error(t('landing.fbBlockedMsg', { slug: s.slug }))
    else if (r.status === 'pass') ElMessage.success(t('landing.fbNormal', { slug: s.slug }))
    else ElMessage.warning(t('landing.fbResult', { slug: s.slug, detail: r.detail }))
  } catch (e) { subFbStatus.value[s.slug] = { status: 'warn', detail: e.message || t('common.fail') }; ElMessage.error(t('landing.fbCheckFail')) }
}
const subFbBatchLoading = ref(false)
const checkAllSubFb = async () => {
  if (!subcodes.value.length) return ElMessage.warning(t('landing.noSubcodes'))
  subFbBatchLoading.value = true
  try {
    const r = await POST('/subcodes/fb-check-batch', { page_id: subPage.value.id })
    const m = {}
    for (const item of r.results) m[item.slug] = { status: item.status, detail: item.detail }
    subFbStatus.value = m
    if (r.blocked > 0) ElMessage.error(t('landing.fbBatchBlocked', { blocked: r.blocked, total: r.total }))
    else ElMessage.success(t('landing.fbBatchAllNormal', { total: r.total }))
  } catch (e) { ElMessage.error(t('landing.fbBatchFail') + '：' + (e.message || '')) }
  subFbBatchLoading.value = false
}
const subEvents = ref([])
const subEventsOpen = ref(false)
const subEventsLoading = ref(false)
const openSubEvents = async (s) => {
  subEventsOpen.value = true; subEventsLoading.value = true
  try { subEvents.value = await GET(`/subcodes/${subPage.value.id}/events?slug=${s.slug}&limit=200`) }
  catch (e) { ElMessage.error(t('landing.loadFail')) }
  subEventsLoading.value = false
}
// 联动：子码 → 落地页日志 tab（预筛该子码 + 所属页）
const goSubLogs = (s) => {
  subOpen.value = false
  tab.value = 'logs'
  router.replace({ name: 'landing', query: { tab: 'logs', slug: s.slug, page_id: subPage.value ? subPage.value.id : '' } })
}
const setTab = (tv) => {
  tab.value = tv
  router.replace({ name: 'landing', query: tv === 'manage' ? {} : { tab: 'logs' } })
}
const copyText = (txt, msg) => { navigator.clipboard?.writeText(txt); ElMessage.success(msg || t('common.copied')) }
const randomPrefix = () => 'go' + Math.random().toString(36).slice(2, 7)
const rootOf = (d) => { const h = (d || '').replace(/^https?:\/\//, '').split('/')[0]; const p = h.split('.'); return p.length >= 2 ? p.slice(-2).join('.') : h }
// 子域名管理
const newSubPrefix = ref('')
const subAdding = ref(false)
const addSubdomain = async () => {
  const p = newSubPrefix.value.trim().toLowerCase()
  if (!p) return ElMessage.warning(t('landing.subPrefixRequired'))
  if (!editingId.value) return ElMessage.warning(t('landing.saveFirst'))
  subAdding.value = true
  try {
    const r = await POST(`/landing/pages/${editingId.value}/subdomains`, { prefix: p })
    form.value.bound_subdomains = r.bound_subdomains || []
    newSubPrefix.value = ''
    ElMessage.success(t('landing.subAdded', { sub: r.subdomain }))
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  subAdding.value = false
}
const removeSubdomain = async (host) => {
  try {
    await ElMessageBox.confirm(t('landing.subDelConfirm', { host }), t('common.confirm'), { type: 'warning' })
    const r = await DELETE(`/landing/pages/${editingId.value}/subdomains/${host}`)
    form.value.bound_subdomains = r.bound_subdomains || []
    ElMessage.success(t('common.done'))
  } catch (e) { if (e !== 'cancel') ElMessage.error(e.message || t('common.opFail')) }
}
const subdomainStatus = ref('')
let _subTimer = null
watch([() => form.value.subdomain_prefix, () => form.value.custom_domains], () => {
  clearTimeout(_subTimer)
  const prefix = (form.value.subdomain_prefix || '').trim().toLowerCase()
  const root = form.value.custom_domains[0] || ''
  if (!prefix || !root) { subdomainStatus.value = ''; return }
  _subTimer = setTimeout(async () => {
    try {
      const r = await GET(`/landing/pages/check-subdomain?prefix=${encodeURIComponent(prefix)}&root=${encodeURIComponent(rootOf(root))}&pid=${editingId.value || 0}`)
      subdomainStatus.value = r.available ? 'ok' : 'taken'
    } catch { subdomainStatus.value = '' }
  }, 400)
})

// ── 像素库管理 ──
const pixelOpen = ref(false)
const pixelForm = ref({ id: null, pixel_id: '', pixel_name: '', note: '', platform: 'fb', tt_access_token: '' })
const pixelSaving = ref(false)
const syncing = ref(false)
const openPixels = () => { pixelOpen.value = true; pixelForm.value = { id: null, pixel_id: '', pixel_name: '', note: '', platform: 'fb', tt_access_token: '' } }
const syncPixels = async () => {
  syncing.value = true
  try { const r = await POST('/landing-lib/pixels/sync', {}); ElMessage.success(t('landing.pixelSynced', { n: r.added || 0 })); await loadLib() }
  catch (e) { ElMessage.error(t('landing.syncFail') + '：' + (e.message || '')) }
  syncing.value = false
}
const editPixel = (p) => { pixelForm.value = { id: p.id, pixel_id: p.pixel_id, pixel_name: p.pixel_name || '', note: p.note || '', platform: p.platform || 'fb', tt_access_token: '' } }
const delPixel = async (p) => {
  try { await ElMessageBox.confirm(t('landing.delPixelConfirm', { id: p.pixel_id }), t('common.confirm'), { type: 'warning' }); await DELETE(`/landing-lib/pixels/${p.id}`); ElMessage.success(t('common.done')); await loadLib() }
  catch {}
}
const savePixel = async () => {
  if (!pixelForm.value.pixel_id.trim()) return ElMessage.warning(t('landing.warnPixelId'))
  pixelSaving.value = true
  try {
    if (pixelForm.value.id) {
      await PUT(`/landing-lib/pixels/${pixelForm.value.id}`, { pixel_name: pixelForm.value.pixel_name, note: pixelForm.value.note, platform: pixelForm.value.platform, tt_access_token: pixelForm.value.tt_access_token || undefined })
      ElMessage.success(t('common.saved'))
    } else {
      await POST('/landing-lib/pixels', { pixel_id: pixelForm.value.pixel_id.trim(), pixel_name: pixelForm.value.pixel_name, note: pixelForm.value.note, platform: pixelForm.value.platform, tt_access_token: pixelForm.value.tt_access_token || undefined })
      ElMessage.success(t('common.done'))
    }
    await loadLib()
    pixelForm.value = { id: null, pixel_id: '', pixel_name: '', note: '', platform: 'fb', tt_access_token: '' }
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
  pixelSaving.value = false
}

// 域名管理（超管：从域名服务商导入）
const isSuper = ref(isSuperadminSync())
const domainOpen = ref(false)
const cfZones = ref([])
const zonesLoading = ref(false)
// 落地页模板（租户 zip 上传）
const landingTemplates = ref([])
const tplFileInput = ref(null)
const tplOpen = ref(false)
const tplForm = ref({ name: '', description: '', file: null })
const tplUploading = ref(false)
const loadLandingTemplates = async () => { try { landingTemplates.value = await GET('/landing-lib/templates') } catch {} }
const openLandingTemplates = () => { tplOpen.value = true; loadLandingTemplates() }
const onTplFile = (e) => { tplForm.value.file = e.target.files[0] }
const uploadLandingTpl = async () => {
  if (!tplForm.value.name.trim()) return ElMessage.warning(t('landing.warnTplName'))
  if (!tplForm.value.file) return ElMessage.warning(t('landing.warnZipFile'))
  tplUploading.value = true
  try {
    const fd = new FormData()
    fd.append('name', tplForm.value.name.trim()); fd.append('description', tplForm.value.description); fd.append('file', tplForm.value.file)
    const BASE = import.meta.env.VITE_API_BASE || 'https://api.tovaads.com'
    const r = await fetch(BASE + '/landing-lib/templates/upload', { method: 'POST', headers: { Authorization: 'Bearer ' + (localStorage.getItem('tova_token') || '') }, body: fd })
    if (r.status === 401) { localStorage.removeItem('tova_token'); location.hash = '#/login'; throw new Error(t('landing.notLoggedIn')) }
    const text = await r.text(); let data = {}; try { data = JSON.parse(text) } catch {}
    if (!r.ok) throw new Error(data.detail || t('landing.uploadFail'))
    ElMessage.success(t('landing.uploadOk', { n: data.validation?.resources || 0 }))
    tplForm.value = { name: '', description: '', file: null }; if (tplFileInput.value) tplFileInput.value.value = ''; await loadLandingTemplates()
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
  tplUploading.value = false
}
const delLandingTpl = async (tpl) => {
  try { await ElMessageBox.confirm(t('landing.delTplConfirm', { name: tpl.name }), t('common.confirm'), { type: 'warning' }); await DELETE(`/landing-lib/templates/${tpl.id}`); ElMessage.success(t('common.done')); await loadLandingTemplates() } catch {}
}
const downloadTplRef = () => {
  const BASE = import.meta.env.VITE_API_BASE || 'https://api.tovaads.com'
  fetch(BASE + '/landing-lib/templates/reference', { headers: { Authorization: 'Bearer ' + (localStorage.getItem('tova_token') || '') } })
    .then(r => r.blob()).then(b => { const url = URL.createObjectURL(b); const a = document.createElement('a'); a.href = url; a.download = 'template-reference.zip'; a.click(); URL.revokeObjectURL(url) })
}
const zoneFilter = ref('')
const filteredZones = computed(() => { const k = zoneFilter.value.trim().toLowerCase(); return k ? cfZones.value.filter(z => z.name.toLowerCase().includes(k)) : cfZones.value })
const openDomains = async () => {
  domainOpen.value = true; zonesLoading.value = true; zoneFilter.value = ''
  try { cfZones.value = (await GET('/landing-lib/cf-zones')).map(z => ({ ...z, _checked: false })) }
  catch (e) { ElMessage.error(e.message || t('landing.loadFail')) }
  finally { zonesLoading.value = false }
}
const importZones = async () => {
  const toImport = cfZones.value.filter(z => z._checked && !z.imported).map(z => z.name)
  if (!toImport.length) return ElMessage.warning(t('landing.warnCheckDomain'))
  try {
    const r = await POST('/landing-lib/domains/import', { domains: toImport })
    ElMessage.success(t('landing.imported', { n: r.added })); await loadLib(); await openDomains()
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
}
const delDomain = async (d) => {
  try { await DELETE(`/landing-lib/domains/${d.id}`); ElMessage.success(t('common.done')); await loadLib(); await openDomains() }
  catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
}

const init = async () => {
  await Promise.all([loadPages(), loadLib()]); loadLandingTemplates()
  try {
    const me = await GET('/auth/me')
    isSuper.value = !!me.is_superadmin
    localStorage.setItem('tova_super', me.is_superadmin ? '1' : '0')
  } catch {}
}
onMounted(async () => { await loadAsnBlocklist(); await init() })
</script>

<template>
  <div class="page">
    <div class="lp-tabs">
      <div :class="['lp-tab', { on: tab === 'manage' }]" @click="setTab('manage')">{{ t('landing.tabManage') }}</div>
      <div :class="['lp-tab', { on: tab === 'logs' }]" @click="setTab('logs')">{{ t('landing.tabLogs') }}</div>
    </div>
    <div v-show="tab === 'manage'">
    <div class="bar">
      <div class="bar-l">{{ t('landing.totalPages', { n: pages.length }) }}</div>
      <div class="bar-r">
        <button class="btn" @click="router.push('/dashboard')">{{ t('landing.viewData') }}</button>
        <button class="btn" @click="openPixels">{{ t('landing.pixelLib') }}</button>
        <button v-if="isSuper" class="btn" @click="openDomains">{{ t('landing.domainMgmt') }}</button>
        <button class="btn" @click="openLandingTemplates">{{ t('landing.templates') }}</button>
        <button class="btn primary" @click="openCreate">+ {{ t('landing.newLink') }}</button>
      </div>
    </div>

    <div class="list" v-loading="loading">
      <div v-for="p in sortedPages" :key="p.id" class="lp-card">
        <div class="lp-head">
          <span class="st-tag" :class="lpStatus(p.status).cls">{{ lpStatus(p.status).label }}</span>
          <span class="lp-title">{{ p.title }}</span>
          <span v-if="p.last_fb_status==='fail'" class="tag" style="background:var(--error);color:#fff" :title="t('landing.fbBlockedTip', { summary: p.last_health_summary || '' })">{{ t('landing.fbBlocked') }}</span>
          <span v-else-if="p.last_fb_status==='warn'" class="tag" style="background:var(--warning);color:#fff" :title="p.last_health_summary || t('landing.fbWarnTip')">{{ t('landing.fbPending') }}</span>
          <span v-if="(p.custom_domains||[]).length" class="tag">{{ (p.custom_domains||[]).length }} {{ t('landing.domainsUnit') }}</span>
          <span class="tag">{{ (p.pixel_ids||[]).length }} {{ t('landing.pixelsUnit') }}</span>
          <span class="health-dot" v-if="p.last_health_status" :class="p.last_health_status" :title="p.last_health_summary || ''"></span>
        </div>
        <div class="lp-body">
          {{ t('landing.cardStats', { sub: p.subcode_count, visit: p.visit_count||0, click: p.click_count||0, rate: p.pass_rate||0 }) }}<span v-if="(p.block_count||0) > 0" style="color:var(--warning);margin-left:4px">{{ t('landing.blockedCount', { n: p.block_count }) }}</span>
          <span v-if="p.last_health_status" class="health-text" :class="p.last_health_status">{{ p.last_health_summary }}</span>
        </div>
        <div class="lp-url" v-if="p.custom_domain">
          <span class="url-text" :title="p.custom_domain">🔗 {{ p.custom_domain }}</span>
          <button class="mb" @click="copyText(p.custom_domain, t('landing.publicUrlCopied'))">{{ t('common.copy') }}</button>
          <a class="mb" :href="p.custom_domain" target="_blank" rel="noopener">{{ t('landing.open') }}↗</a>
        </div>
        <div class="lp-foot">
          <a v-if="p.preview_url" class="mb" :href="p.preview_url" target="_blank" rel="noopener">{{ t('common.preview') }}</a>
          <button class="mb" @click="openSubcodes(p)">{{ t('landing.subcodes') }}</button>
          <button class="mb" :disabled="healthCheckingId === p.id" @click="checkHealth(p)">{{ healthCheckingId === p.id ? t('landing.checking') : t('landing.selfCheck') }}</button>
          <button class="mb" @click="openEdit(p)">{{ t('common.edit') }}</button>
          <button class="mb danger" @click="archive(p)">{{ t('landing.archive') }}</button>
        </div>
      </div>
      <div v-if="!pages.length && !loading" class="empty">{{ t('landing.emptyCreate') }}</div>
    </div>

    <el-drawer v-model="drawerOpen" :title="editingId ? t('landing.editTitle') : t('landing.createTitle')" direction="rtl" size="580px" :destroy-on-close="true" :close-on-click-modal="false" v-loading="saving" :element-text="saving ? t('landing.deployingCloud') : ''">
      <div class="form-l"><label>{{ t('landing.fTitle') }}</label><input v-model="form.title" class="input" :placeholder="t('landing.fTitlePh')" /></div>
      <div class="form-l"><label>{{ t('landing.accessMode') }}</label>
        <el-radio-group v-model="form.redirect_mode">
          <el-radio value="display">{{ t('landing.modeDisplay') }}</el-radio>
          <el-radio value="redirect">{{ t('landing.modeRedirect') }}</el-radio>
        </el-radio-group>
      </div>
      <div class="mode-hint" v-if="form.redirect_mode === 'display'">{{ t('landing.modeHintDisplay') }}</div>
      <div class="mode-hint" v-else>{{ t('landing.modeHintRedirect') }}</div>

      <div class="form-l"><label>{{ form.redirect_mode === 'redirect' ? t('landing.fRedirectUrl') : t('landing.fTargetUrl') }}</label>
        <el-select v-model="form.target_urls" multiple filterable allow-create default-first-option
          :placeholder="form.redirect_mode === 'redirect' ? t('landing.fRedirectUrlPh') : t('landing.fTargetUrlPh')" style="flex:1" />
      </div>
      <div class="form-l"><label>{{ t('landing.fRotation') }}</label>
        <select v-model="form.rotation_mode" class="input">
          <option v-for="o in rotationOptions" :key="o.v" :value="o.v">{{ o.l }}</option>
        </select>
      </div>
      <div class="form-l" v-if="form.custom_domain"><label>{{ t('landing.fPublicUrl') }}</label>
        <span class="url-text" style="flex:1">🔗 {{ form.custom_domain }}</span>
        <button class="mb" @click="copyText(form.custom_domain, t('landing.publicUrlCopied'))">{{ t('common.copy') }}</button>
      </div>
      <div class="form-l"><label>{{ t('landing.fDomain') }}</label>
        <el-select v-model="form.custom_domains" multiple filterable allow-create default-first-option
          :placeholder="t('landing.fDomainPh')" style="flex:1">
          <el-option v-for="d in domains" :key="d.id" :value="d.domain" :label="d.domain + (d.label ? ' ('+d.label+')' : '')" />
        </el-select>
      </div>
      <!-- 已绑定子域名列表（多域名管理） -->
      <div class="form-l" v-if="form.bound_subdomains && form.bound_subdomains.length">
        <label>{{ t('landing.boundSubs') }}</label>
        <div class="subdomain-tags" style="flex:1">
          <span v-for="sub in form.bound_subdomains" :key="sub" class="subdomain-tag">
            <a :href="'https://'+sub" target="_blank" rel="noopener" class="sub-link">🔗 {{ sub }}</a>
            <button v-if="form.bound_subdomains.length > 1" class="sub-del" @click="removeSubdomain(sub)" :title="t('common.delete')">✕</button>
          </span>
        </div>
      </div>
      <!-- 添加新子域名 -->
      <div class="form-l">
        <label>{{ t('landing.addSub') }}</label>
        <input v-model="newSubPrefix" class="input" :placeholder="t('landing.addSubPh')" style="flex:1" @keyup.enter="addSubdomain" />
        <button class="mb" type="button" @click="newSubPrefix = randomPrefix()">🎲</button>
        <button class="btn sm primary" :disabled="subAdding || !newSubPrefix.trim() || !editingId" @click="addSubdomain">{{ subAdding ? '…' : t('common.add') }}</button>
      </div>
      <div class="pixel-hint" v-if="form.custom_domains.length">{{ t('landing.addSubHint') }}</div>

      <template v-if="form.redirect_mode === 'display'">
        <!-- Facebook 像素区块 -->
        <div class="pixel-section fb-section">
          <div class="pixel-section-header">📘 Facebook</div>
          <div class="form-l"><label>{{ t('landing.fPixel') }}</label>
            <el-select v-model="form.pixel_ids" multiple filterable allow-create collapse-tags collapse-tags-tooltip
              :placeholder="t('landing.fPixelPh')" style="flex:1">
              <el-option v-for="p in pixels" :key="p.id" :value="p.pixel_id"
                :label="p.pixel_name ? `${p.pixel_name} (${p.pixel_id})` : p.pixel_id" />
            </el-select>
          </div>
          <div class="form-l"><label>{{ t('landing.fConversionEvent') }}</label>
            <el-select v-model="form.conversion_events" multiple filterable allow-create default-first-option
              :placeholder="t('landing.fConversionEventPh')" style="flex:1">
              <el-option v-for="o in convEventOptions" :key="o.v" :value="o.v" :label="o.l" />
            </el-select>
          </div>
        </div>
        <!-- TikTok 像素区块 -->
        <div class="pixel-section tt-section">
          <div class="pixel-section-header">🎵 TikTok</div>
          <div class="form-l"><label>{{ t('landing.fTtPixel') }}</label>
            <el-select v-model="form.tt_pixel_ids" multiple filterable allow-create collapse-tags collapse-tags-tooltip
              :placeholder="t('landing.fTtPixelPh')" style="flex:1">
              <el-option v-for="p in ttPixels" :key="p.id" :value="p.pixel_id"
                :label="p.pixel_name ? `${p.pixel_name} (${p.pixel_id})` : p.pixel_id" />
            </el-select>
          </div>
          <div class="form-l"><label>{{ t('landing.fTtConvEvent') }}</label>
            <el-select v-model="form.tt_conversion_events" multiple filterable allow-create default-first-option
              :placeholder="t('landing.fTtConvEventPh')" style="flex:1">
              <el-option v-for="o in ttConvEventOptions" :key="o.v" :value="o.v" :label="o.l" />
            </el-select>
          </div>
        </div>
        <div class="pixel-hint">{{ t('landing.pixelHint') }}</div>
        <div class="form-l"><label>{{ t('landing.fLandingTpl') }}</label>
          <select v-model="form.template_id" class="input">
            <option :value="null">{{ t('landing.defaultTpl') }}</option>
            <option v-for="tpl in landingTemplates" :key="tpl.id" :value="tpl.id">{{ tpl.name }}</option>
          </select>
        </div>
      </template>

      <div class="sec-title">{{ t('landing.dedup') }} <el-switch v-model="form.dedup_enabled" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" style="margin-left:8px" /></div>
      <template v-if="form.dedup_enabled">
        <div class="form-l"><label>{{ t('landing.fDedupWindow') }}</label>
          <input v-model.number="form.dedup_window_hours" type="number" min="1" class="input" style="flex:1" />
        </div>
      </template>
      <div class="sec-title">{{ t('landing.protectionRules') }} <el-switch v-model="form.block_enabled" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" style="margin-left:8px" /></div>
      <div class="form-l" v-if="form.block_enabled"><label>{{ t('landing.fPreviewMode') }}</label>
        <el-switch v-model="form.preview_enabled" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" />
        <span class="hint" style="margin-left:8px">{{ t('landing.previewModeHint') }}</span>
      </div>
      <div class="lp-url" v-if="form.preview_enabled && form.preview_url">
        <span class="url-text" :title="form.preview_url">👁 {{ form.preview_url }}</span>
        <button class="mb" @click="copyText(form.preview_url, t('landing.previewUrlCopied'))">{{ t('landing.copyPreviewUrl') }}</button>
        <a class="mb" :href="form.preview_url" target="_blank" rel="noopener">{{ t('landing.open') }}↗</a>
      </div>
      <template v-if="form.block_enabled">
        <div class="guard-grid">
          <button v-for="g in QUICK_GUARDS" :key="g.key"
            class="guard-btn" :class="{ on: guardActive(g) }"
            @click="toggleGuard(g)">{{ g.label }}</button>
        </div>
        <div v-if="guardSummary" class="guard-summary">{{ t('landing.activeNow') }}：{{ guardSummary }}</div>
        <div class="prot-test">
          <button class="btn sm" :disabled="protTesting" @click="runProtTest">{{ protTesting ? t('landing.testing') : t('landing.protSimTest') }}</button>
          <span v-if="protTestResult" class="prot-test-summary">
            {{ t('landing.protBlocked', { n: protTestResult.blocked_count }) }} / {{ t('landing.protPassed', { n: protTestResult.pass_count }) }}
          </span>
        </div>
        <div v-if="protTestResult" class="prot-test-result">
          <div v-for="(r, i) in protTestResult.profiles" :key="i" class="prot-profile">
            <span class="prot-label">{{ r.label }}</span>
            <span class="st-tag" :class="r.blocked ? 'warn' : 'ok'">{{ r.blocked ? t('landing.protBlockedTag') : t('landing.protPassedTag') }}</span>
            <span v-if="r.reason" class="prot-reason">{{ r.reason }}</span>
          </div>
        </div>
        <div class="adv-toggle" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? t('landing.collapseAdvanced') : t('landing.advancedCustom') }}
        </div>
        <div v-if="showAdvanced" class="rules-grid">
          <div class="rule-row"><label>{{ t('landing.ruleCountryAllow') }}</label>
            <el-select :model-value="ruleVal('country_allow')" @update:model-value="v=>setRule('country_allow',v)" multiple filterable allow-create default-first-option :placeholder="t('landing.phCountryCode')" style="flex:1"><el-option v-for="c in COUNTRIES" :key="c" :value="c" :label="c" /></el-select>
          </div>
          <div class="rule-row"><label>{{ t('landing.ruleCountryBlock') }}</label>
            <el-select :model-value="ruleVal('country_block')" @update:model-value="v=>setRule('country_block',v)" multiple filterable allow-create default-first-option :placeholder="t('landing.phCountryCode')" style="flex:1"><el-option v-for="c in COUNTRIES" :key="c" :value="c" :label="c" /></el-select>
          </div>
          <div class="rule-row"><label>{{ t('landing.ruleSourceAllow') }}</label>
            <el-select :model-value="ruleVal('source_allow')" @update:model-value="v=>setRule('source_allow',v)" multiple allow-create default-first-option :placeholder="t('landing.phSource')" style="flex:1"><el-option v-for="s in SOURCES" :key="s" :value="s" :label="s" /></el-select>
          </div>
          <div class="rule-row"><label>{{ t('landing.ruleSourceBlock') }}</label>
            <el-select :model-value="ruleVal('source_block')" @update:model-value="v=>setRule('source_block',v)" multiple allow-create default-first-option :placeholder="t('landing.phSource')" style="flex:1"><el-option v-for="s in SOURCES" :key="s" :value="s" :label="s" /></el-select>
          </div>
          <div class="rule-row"><label>{{ t('landing.ruleDeviceBlock') }}</label>
            <el-select :model-value="ruleVal('device_block')" @update:model-value="v=>setRule('device_block',v)" multiple allow-create default-first-option :placeholder="t('landing.phDevice')" style="flex:1"><el-option v-for="d in DEVICES" :key="d" :value="d" :label="d" /></el-select>
          </div>
          <div class="rule-row"><label>{{ t('landing.rulePlatformBlock') }}</label>
            <el-select :model-value="ruleVal('platform_block')" @update:model-value="v=>setRule('platform_block',v)" multiple filterable allow-create default-first-option :placeholder="t('landing.phPlatform')" style="flex:1"><el-option v-for="p in PLATFORMS" :key="p" :value="p" :label="p" /></el-select>
          </div>
          <div class="rule-row"><label>{{ t('landing.ruleUaBlock') }}</label>
            <el-select :model-value="ruleVal('ua_block')" @update:model-value="v=>setRule('ua_block',v)" multiple filterable allow-create default-first-option :placeholder="t('landing.phUa')" style="flex:1" />
          </div>
          <div class="rule-row"><label>{{ t('landing.ruleDatacenterBlock') }}</label>
            <el-select :model-value="ruleVal('datacenter_block')" @update:model-value="v=>setRule('datacenter_block',v)" multiple filterable allow-create default-first-option :placeholder="t('landing.phDatacenter')" style="flex:1">
              <el-option v-for="d in datacenterAsns" :key="d.asn" :value="d.asn" :label="`${d.asn} · ${d.label}`" />
            </el-select>
          </div>
          <div class="rule-row"><label>{{ t('landing.ruleRefererBlock') }}</label>
            <el-select :model-value="ruleVal('referer_block')" @update:model-value="v=>setRule('referer_block',v)" multiple filterable allow-create default-first-option :placeholder="t('landing.phReferer')" style="flex:1" />
          </div>
          <div class="rule-row"><label>{{ t('landing.ruleQueryBlock') }}</label>
            <el-select :model-value="ruleVal('query_block')" @update:model-value="v=>setRule('query_block',v)" multiple filterable allow-create default-first-option :placeholder="t('landing.phEnterAdd')" style="flex:1" />
          </div>
          <div class="rule-row"><label>{{ t('landing.ruleRequiredQuery') }}</label>
            <el-select :model-value="ruleVal('required_query')" @update:model-value="v=>setRule('required_query',v)" multiple filterable allow-create default-first-option :placeholder="t('landing.phRequiredQuery')" style="flex:1" />
          </div>
        </div>
        <div class="sec-title">{{ t('landing.blockHandlerTitle') }}</div>
        <div class="form-l"><label>{{ t('landing.fBlockRedirect') }}</label><input v-model="form.block_target" class="input" :placeholder="t('landing.fBlockRedirectPh')" /></div>
        <div class="form-l"><label>{{ t('landing.fBlockHtml') }}</label><textarea v-model="form.block_html" class="input" rows="2" :placeholder="t('landing.fBlockHtmlPh')"></textarea></div>
      </template>
      <div v-else class="block-off-hint">{{ t('landing.protectionOff') }}</div>

      <template #footer>
        <button class="btn" @click="drawerOpen=false">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="saving" @click="save">{{ saving ? t('landing.deploying') : (editingId ? t('common.save') : t('landing.publish')) }}</button>
      </template>
    </el-drawer>

    <el-drawer v-model="subOpen" :title="t('landing.subDrawerTitle', { title: subPage?.title || '' })" direction="rtl" size="520px" :destroy-on-close="true" :close-on-click-modal="false">
      <div class="sub-gen">
        <span class="sub-gen-lab">{{ t('landing.subGen') }}</span>
        <input v-model.number="newSubCount" type="number" min="1" max="50" class="sub-gen-input" />
        <span class="sub-gen-lab">{{ t('landing.subGenUnit') }}</span>
        <button class="btn primary" style="margin-left:auto" :disabled="subGenerating" @click="genSubcode">{{ subGenerating ? t('landing.subGenerating') : t('landing.subBatchGen') }}</button>
      </div>
      <div class="sub-tabs">
        <div class="sub-tab-row">
          <span :class="['sub-tab', { on: subStatus === 'all' }]" @click="setSubStatus('all')">{{ t('common.all') }} <i>{{ subCounts.all || 0 }}</i></span>
          <span :class="['sub-tab', { on: subStatus === 'unbound' }]" @click="setSubStatus('unbound')">{{ t('landing.subUnbound') }} <i>{{ subCounts.unbound || 0 }}</i></span>
          <span :class="['sub-tab', { on: subStatus === 'active' }]" @click="setSubStatus('active')">{{ t('landing.subActive') }} <i>{{ subCounts.active || 0 }}</i></span>
          <span :class="['sub-tab trash', { on: subStatus === 'trash' }]" @click="setSubStatus('trash')">{{ t('landing.subTrash') }} <i>{{ (subCounts.archived || 0) + (subCounts.deleted || 0) }}</i></span>
        </div>
        <div class="sub-filter-row">
          <input v-model="subQ" class="input sub-search" :placeholder="t('landing.subSearchPh')" @keyup.enter="onSubSearch" />
          <select v-model="subSort" class="sub-sort" @change="onSubSearch">
            <option value="created">{{ t('landing.subSortCreated') }}</option>
            <option value="visits">{{ t('landing.subSortVisits') }}</option>
          </select>
          <button v-if="subStatus !== 'trash'" class="btn sm" :disabled="subFbBatchLoading" @click="checkAllSubFb" :title="t('landing.subFbBatchTip')">{{ subFbBatchLoading ? t('landing.subFbChecking') : t('landing.subFbBatch') }}</button>
        </div>
      </div>
      <div class="sub-list" v-loading="subLoading">
        <div v-for="s in subcodes" :key="s.id" class="sub-item">
          <div class="sub-row">
            <code class="sub-slug">/a/{{ s.slug }}</code>
            <span class="sub-ad">{{ s.ad_count > 0 ? t('landing.subAds', { ads: s.ad_count, acts: s.act_count }) : t('landing.subUnboundAd') }}</span>
            <span class="sub-pass" v-if="s.click_count > 0">{{ t('landing.subPassed', { n: s.click_count }) }}</span>
            <span class="st-tag" :class="subcodeStatus(s.status).cls">{{ subcodeStatus(s.status).label }}</span>
            <span class="sub-stat">{{ t('landing.subStat', { visit: s.visit_count||0, click: s.click_count||0 }) }}</span>
            <span v-if="subFbStatus[s.slug] && !subFbStatus[s.slug].loading" class="fb-badge" :class="subFbStatus[s.slug].status" :title="subFbStatus[s.slug].detail">{{ subFbStatus[s.slug].status === 'pass' ? t('landing.fbOk') : (subFbStatus[s.slug].status === 'fail' ? t('landing.fbBanned') : t('landing.fbUnknown')) }}</span>
            <template v-if="subStatus !== 'trash'">
              <div class="sub-ops">
                <button class="mb" @click="goSubLogs(s)">{{ t('landing.logsBtn') }}</button>
                <button class="mb" @click="copyUrl(s.slug)">{{ t('common.copy') }}</button>
                <el-dropdown trigger="click" @command="cmd => {
                  if (cmd === 'fb') checkSubFb(s)
                  else if (cmd === 'ad') router.push({ name: 'ad-manager', query: { act: s.act_id || '' } })
                  else if (cmd === 'archive') archiveSub(s)
                }">
                  <button class="mb" :class="{ spin: subFbStatus[s.slug]?.loading }" :title="t('landing.moreOps')">⋯</button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="fb" :disabled="subFbStatus[s.slug]?.loading">{{ subFbStatus[s.slug]?.loading ? t('landing.fbChecking') : t('landing.fbBanCheck') }}</el-dropdown-item>
                      <el-dropdown-item command="ad">{{ t('landing.adMgmt') }}</el-dropdown-item>
                      <el-dropdown-item command="archive" divided>{{ t('landing.archive') }}</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </template>
            <template v-else>
              <div class="sub-ops">
                <button class="mb" @click="restoreSub(s)">{{ t('landing.restore') }}</button>
                <button class="mb danger" @click="hardDeleteSub(s)">{{ t('landing.hardDelete') }}</button>
              </div>
            </template>
          </div>
          <div class="sub-target" v-if="subTargetEdit[s.id] !== undefined">
            <input v-model="subTargetEdit[s.id]" class="input sub-target-input" :placeholder="t('landing.subTargetPh')" />
            <button class="mb" @click="saveSubTarget(s)">{{ t('common.save') }}</button>
            <button class="mb" @click="delete subTargetEdit[s.id]">{{ t('common.cancel') }}</button>
          </div>
          <div class="sub-target-show" v-else-if="s.target_urls" @click="startEditTarget(s)">
            {{ t('landing.subTargetShow') }}：{{ s.target_urls }} <span class="edit-hint">{{ t('landing.clickToEdit') }}</span>
          </div>
          <div class="sub-target-add" v-else-if="subStatus !== 'trash'" @click="startEditTarget(s)">+ {{ t('landing.subTargetAdd') }}</div>
        </div>
        <div v-if="!subcodes.length && !subLoading" class="empty">{{ subStatus === 'trash' ? t('landing.trashEmpty') : t('landing.subEmpty') }}</div>
      </div>
    </el-drawer>

    <el-dialog v-model="subEventsOpen" :title="t('landing.subEventsTitle')" width="640px">
      <div v-loading="subEventsLoading" class="sub-list">
        <div v-for="e in subEvents" :key="e.id" class="sub-row" style="flex-wrap:wrap;gap:6px">
          <span class="st-tag" :class="e.event_type==='visit'?'ok':(e.event_type==='block'?'warn':'off')">{{ e.event_type }}</span>
          <span>{{ e.country }} {{ e.city }}</span>
          <span style="color:var(--t3);font-size:11px">{{ e.created_at }}</span>
          <span v-if="e.reason" style="color:var(--error);font-size:11px">{{ e.reason }}</span>
        </div>
        <div v-if="!subEvents.length && !subEventsLoading" class="empty">{{ t('landing.noLogs') }}</div>
      </div>
    </el-dialog>

    <el-drawer v-model="pixelOpen" :title="t('landing.pixelLibTitle')" direction="rtl" size="480px" :destroy-on-close="true" append-to-body>
      <button class="btn" :disabled="syncing" @click="syncPixels" style="margin-bottom:14px">{{ syncing ? t('landing.pixelSyncing') : t('landing.pixelSync') }}</button>
      <div class="sec-title">{{ pixelForm.id ? t('landing.pixelEdit') : t('landing.pixelAdd') }}</div>
      <div class="form-l"><label>{{ t('landing.fPixelId') }}</label><input v-model="pixelForm.pixel_id" class="input" :placeholder="t('landing.fPixelIdPh')" :disabled="!!pixelForm.id" /></div>
      <div class="form-l"><label>{{ t('landing.fPixelPlatform') }}</label>
        <select v-model="pixelForm.platform" class="input">
          <option value="fb">📘 Facebook</option>
          <option value="tt">🎵 TikTok</option>
        </select>
      </div>
      <div class="form-l"><label>{{ t('common.name') }}</label><input v-model="pixelForm.pixel_name" class="input" :placeholder="t('landing.pixelNamePh')" /></div>
      <div class="form-l" v-if="pixelForm.platform === 'tt'"><label>{{ t('landing.fTtToken') }}</label><input v-model="pixelForm.tt_access_token" class="input" type="password" :placeholder="t('landing.fTtTokenPh')" /></div>
      <div class="pixel-hint" v-if="pixelForm.platform === 'tt'" style="margin:0 0 10px">{{ t('landing.fTtTokenHint') }}</div>
      <button class="btn primary" :disabled="pixelSaving" @click="savePixel">{{ pixelForm.id ? t('common.save') : t('common.add') }}</button>
      <div class="sec-title">{{ t('landing.pixelList') }}</div>
      <div class="sub-list">
        <div v-for="p in pixels" :key="p.id" class="sub-row">
          <span class="plat-badge" :class="p.platform || 'fb'">{{ p.platform === 'tt' ? '🎵' : '📘' }}</span>
          <code>{{ p.pixel_id }}</code>
          <span v-if="p.act_id" class="tag">{{ String(p.act_id).slice(-6) }}</span>
          <span class="sub-ad">{{ p.pixel_name || '-' }}</span>
          <span v-if="p.platform === 'tt'" class="tag" :class="p.tt_has_token ? 'ok' : 'warn'">{{ p.tt_has_token ? '✓ Token' : '⚠ 无Token' }}</span>
          <span class="tag">{{ t('landing.pixelPages', { n: p.usage_count }) }}</span>
          <button class="mb" style="margin-left:auto" @click="editPixel(p)">{{ t('common.edit') }}</button>
          <button class="mb danger" @click="delPixel(p)">{{ t('common.delete') }}</button>
        </div>
        <div v-if="!pixels.length" class="empty">{{ t('landing.pixelEmpty') }}</div>
      </div>
    </el-drawer>

    <el-drawer v-if="isSuper" v-model="domainOpen" :title="t('landing.domainMgmt')" direction="rtl" size="520px" :destroy-on-close="true" append-to-body>
      <div class="sec-title">{{ t('landing.importableDomains') }}</div>
      <input v-model="zoneFilter" class="input" :placeholder="t('landing.searchDomains')" style="margin-bottom:8px;width:100%;box-sizing:border-box" />
      <div class="sub-list" v-loading="zonesLoading">
        <div v-for="z in filteredZones" :key="z.name" class="sub-row">
          <input type="checkbox" v-model="z._checked" :disabled="z.imported" style="margin-right:6px" />
          <code>{{ z.name }}</code>
          <span class="st-tag" :class="z.imported?'off':'ok'">{{ z.imported ? t('landing.zoneImported') : (z.status === 'available' ? t('landing.zoneAvailable') : (z.status === 'taken' ? t('landing.zoneTaken') : (z.status === 'error' ? t('landing.zoneQueryFail') : '—'))) }}</span>
        </div>
        <div v-if="!cfZones.length && !zonesLoading" class="empty">{{ t('landing.noImportableDomains') }}</div>
      </div>
      <button class="btn primary" style="margin-top:12px" @click="importZones">{{ t('landing.importSelected') }}</button>
      <div class="sec-title">{{ t('landing.importedDomains') }}</div>
      <div class="sub-list">
        <div v-for="d in domains" :key="d.id" class="sub-row">
          <code>{{ d.domain }}</code>
          <span class="sub-ad">{{ d.label || d.source }}</span>
          <button class="mb danger" @click="delDomain(d)">{{ t('common.delete') }}</button>
        </div>
        <div v-if="!domains.length" class="empty">{{ t('landing.noDomainsImported') }}</div>
      </div>
    </el-drawer>

    <el-drawer v-model="tplOpen" :title="t('landing.tplDrawerTitle')" direction="rtl" size="520px" :destroy-on-close="true" append-to-body>
      <button class="btn" @click="downloadTplRef" style="margin-bottom:14px">{{ t('landing.downloadRefTpl') }}</button>
      <div class="sec-title">{{ t('landing.uploadNewTpl') }}</div>
      <div class="form-l"><label>{{ t('landing.fTplName') }}</label><input v-model="tplForm.name" class="input" :placeholder="t('landing.fTplNamePh')" /></div>
      <div class="form-l"><label>{{ t('landing.fTplDesc') }}</label><input v-model="tplForm.description" class="input" :placeholder="t('common.optional')" /></div>
      <div class="form-l"><label>{{ t('landing.fZipFile') }}</label><input ref="tplFileInput" type="file" accept=".zip" @change="onTplFile" class="input" /></div>
      <button class="btn primary" :disabled="tplUploading" @click="uploadLandingTpl">{{ tplUploading ? t('landing.uploading') : t('landing.uploadAndCheck') }}</button>
      <div class="sec-title">{{ t('landing.uploadedTpls') }}</div>
      <div class="sub-list">
        <div v-for="tpl in landingTemplates" :key="tpl.id" class="sub-row">
          <code>{{ tpl.name }}</code>
          <span v-if="tpl.has_resources" class="tag">{{ t('landing.multiFile') }}</span>
          <button class="mb danger" style="margin-left:auto" @click="delLandingTpl(tpl)">{{ t('common.delete') }}</button>
        </div>
        <div v-if="!landingTemplates.length" class="empty">{{ t('landing.tplEmpty') }}</div>
      </div>
    </el-drawer>
    </div>
    <LandingLogs v-if="tab === 'logs'" />
  </div>
</template>

<style scoped>
.page{width:100%}
.lp-tabs{display:flex;gap:2px;border-bottom:1px solid var(--bd);margin-bottom:14px;padding-left:4px}
.lp-tab{padding:7px 16px;font-size:13px;color:var(--t3);cursor:pointer;border-bottom:2px solid transparent}
.lp-tab.on{color:var(--t1);border-bottom-color:var(--ac);font-weight:600}
.lp-tab:hover{color:var(--t1)}
.bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;gap:8px}
.bar-l{font-size:13px;color:var(--t2)}
.bar-r{display:flex;gap:8px}
.btn{padding:6px 14px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:6px;font-size:13px;cursor:pointer;white-space:nowrap}
.btn:hover{background:var(--bg3)}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.list{display:flex;flex-direction:column;gap:10px}
.lp-card{background:var(--bg2);border:1px solid var(--bd);border-radius:8px;padding:12px 14px}
.lp-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.lp-title{font-size:14px;font-weight:600;color:var(--t1)}
.tag{font-size:10px;padding:1px 7px;border-radius:9px;background:var(--bg3);color:var(--t3)}
.st-tag{font-size:10px;padding:1px 7px;border-radius:9px}
.st-tag.ok{background:rgba(48,209,88,.15);color:var(--success)}
.st-tag.off{background:var(--bg3);color:var(--t3)}
.st-tag.warn{background:rgba(255,159,10,.15);color:var(--warning)}
.lp-body{font-size:12px;color:var(--t3);margin-top:6px}
.lp-foot{display:flex;gap:6px;margin-top:8px;padding-top:8px;border-top:1px solid var(--bd)}
.mb{padding:3px 10px;border:1px solid var(--bd);background:transparent;color:var(--t2);border-radius:4px;font-size:11px;cursor:pointer}
.mb:hover{color:var(--ac);border-color:var(--ac)}
.mb.danger{color:var(--error);border-color:rgba(239,68,68,.4)}
.mb.danger:hover{color:#fff;background:var(--error);border-color:var(--error)}
.sub-gen{display:flex;align-items:center;gap:8px;margin-bottom:14px}
.sub-gen-lab{font-size:12px;color:var(--t3)}
.sub-gen-input{width:60px;padding:6px 8px;text-align:center;background:var(--bg3);color:var(--t1);border:1px solid var(--bd);border-radius:6px;font-size:13px;box-sizing:border-box}
.sub-gen-input:focus{outline:none;border-color:var(--ac)}
.sub-tabs{margin-bottom:8px}
.sub-tab-row{display:flex;gap:2px;background:var(--bg3);border-radius:8px;padding:3px;margin-bottom:8px}
.sub-filter-row{display:flex;gap:6px;align-items:center}
.sub-tab{flex:1;text-align:center;font-size:12px;color:var(--t3);padding:6px 4px;border-radius:6px;cursor:pointer;white-space:nowrap;transition:all .15s}
.sub-tab i{font-style:normal;color:var(--t3);margin-left:3px;font-size:10px}
.sub-tab:hover{color:var(--t1)}
.sub-tab.on{background:var(--ac);color:#fff}
.sub-tab.on i{color:#fff}
.sub-tab.trash.on{background:var(--error)}
.sub-search{flex:1;min-width:0;padding:6px 10px;font-size:12px}
.sub-sort{padding:6px 8px;font-size:12px;background:var(--bg2);color:var(--t2);border:1px solid var(--bd);border-radius:6px}
.empty{text-align:center;color:var(--t3);padding:32px;font-size:13px;background:var(--bg2);border:1px dashed var(--bd);border-radius:8px}
.form-l{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.form-l > label{font-size:12px;color:var(--t3);width:84px;text-align:right;flex-shrink:0}
.opt-hint{font-size:10px;color:var(--t3);opacity:.7;font-weight:400}
.input{flex:1;padding:7px 10px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:13px;font-family:inherit;box-sizing:border-box}
.input:focus{border-color:var(--ac);outline:none}
.sec-title{font-size:12px;color:var(--ac);margin:18px 0 10px;font-weight:600}
.tpl-desc{font-size:11px;color:var(--t3);margin:-4px 0 10px 92px;line-height:1.5}
.mode-hint{font-size:11px;color:var(--t3);margin:-6px 0 12px 92px;line-height:1.5}
.pixel-hint{font-size:11px;color:var(--t3);margin:-6px 0 10px 92px;line-height:1.5}
.pixel-section{border:1px solid var(--bd);border-radius:8px;padding:10px 12px;margin-bottom:10px}
.pixel-section-header{font-size:13px;font-weight:600;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid var(--bd)}
.fb-section{border-color:rgba(24,119,242,.3);background:rgba(24,119,242,.03)}
.fb-section .pixel-section-header{color:#1877f2}
.tt-section{border-color:rgba(0,0,0,.15);background:rgba(254,44,85,.02)}
.tt-section .pixel-section-header{color:#fe2c55}
.subdomain-tags{display:flex;flex-wrap:wrap;gap:6px}
.subdomain-tag{display:inline-flex;align-items:center;gap:4px;background:var(--bg3);border-radius:6px;padding:3px 8px;font-size:12px}
.sub-link{color:var(--ac);text-decoration:none;font-family:monospace}
.sub-del{background:none;border:none;color:var(--error);cursor:pointer;font-size:11px;padding:0 2px}
.plat-badge{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:4px;font-size:13px;flex:none}
.plat-badge.fb{background:rgba(24,119,242,.12)}
.plat-badge.tt{background:rgba(254,44,85,.1)}
.tag.ok{color:var(--success);background:rgba(52,199,89,.13)}
.tag.warn{color:var(--warning);background:rgba(255,159,10,.13)}
.block-off-hint{font-size:12px;color:var(--t3);padding:8px 0;line-height:1.5}
.guard-grid{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.guard-btn{padding:6px 12px;border:1px solid var(--bd);background:var(--bg3);color:var(--t2);border-radius:6px;font-size:12px;cursor:pointer;transition:.15s}
.guard-btn:hover{border-color:var(--ac);color:var(--ac)}
.guard-btn.on{background:var(--acg);color:var(--ac);border-color:var(--ac)}
.guard-summary{font-size:11px;color:var(--t3);padding:6px 10px;background:var(--bg3);border-radius:6px;margin-bottom:8px;line-height:1.5}
.adv-toggle{font-size:12px;color:var(--ac);cursor:pointer;padding:6px 0;margin-bottom:6px;user-select:none}
.health-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-left:4px;flex-shrink:0}
.health-dot.pass{background:var(--success)}
.health-dot.warn{background:var(--warning)}
.health-dot.fail{background:var(--error)}
.health-text{font-size:10px;margin-left:6px}
.health-text.pass{color:var(--success)}
.health-text.warn{color:var(--warning)}
.health-text.fail{color:var(--error)}
.lp-url{display:flex;align-items:center;gap:6px;margin:4px 0 8px;font-size:11px}
.url-text{color:var(--t2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}
.hint{font-size:11px;color:var(--t3)}
.btn.sm{padding:4px 10px;font-size:11px}
.prot-test{display:flex;align-items:center;gap:8px;margin:8px 0}
.prot-test-summary{font-size:12px;color:var(--t2)}
.prot-test-result{background:var(--bg3);border-radius:6px;padding:8px 10px;margin-bottom:8px}
.prot-profile{display:flex;align-items:center;gap:8px;padding:3px 0;font-size:12px}
.prot-label{color:var(--t2);min-width:160px}
.prot-reason{font-size:10px;color:var(--t3)}
.rules-grid{display:flex;flex-direction:column;gap:6px}
.rule-row{display:flex;align-items:center;gap:8px}
.rule-row > label{font-size:11px;color:var(--t2);width:84px;flex-shrink:0;text-align:right}
.sub-list{display:flex;flex-direction:column;gap:0;margin-top:8px}
.sub-row{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--bd);font-size:12px}
.sub-item{padding:4px 0;border-bottom:1px solid var(--bd)}
.sub-target{display:flex;gap:6px;align-items:center;padding:6px 0}
.sub-target-input{flex:1}
.sub-target-show{font-size:11px;color:var(--ac);padding:4px 0;cursor:pointer}
.edit-hint{color:var(--t3);font-size:10px;margin-left:4px}
.sub-target-add{font-size:11px;color:var(--t3);padding:4px 0;cursor:pointer}
.sub-target-add:hover{color:var(--ac)}
.sub-slug{color:var(--ac);font-family:'SF Mono',monospace}
.sub-ad{color:var(--t3);font-family:'SF Mono',monospace;font-size:11px}
.sub-pass{color:var(--success);font-size:11px;font-weight:600}
.fb-badge{font-size:10px;font-weight:500;padding:2px 6px;border-radius:4px;white-space:nowrap}
.fb-badge.pass{color:var(--success);background:rgba(52,199,89,.1)}
.fb-badge.fail{color:var(--error);background:rgba(255,69,58,.1)}
.fb-badge.warn{color:var(--warning);background:rgba(255,159,10,.1)}
.sub-ops{display:flex;gap:4px;align-items:center;margin-left:auto;flex-shrink:0}
.mb.spin{opacity:.5;pointer-events:none}
</style>
