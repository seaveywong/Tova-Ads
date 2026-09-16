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
// 模式筛选（链接管理内二级 tab：全部 / 落地页 / 短链）。display 含历史缺省值
const modeFilter = ref('lp')   // tab=类别互斥（用户 2026-09-15：不同 tab 存放不同类别，不做混排「全部」）
// 创建人筛选（2026-09-16 用户要求：owner 看全团队时按人过滤）
const ownerFilter = ref('')
const ownerOptions = computed(() => {
  const seen = new Map()
  for (const p of pages.value) {
    if (p.owner_email && !seen.has(p.owner_email)) {
      seen.set(p.owner_email, {
        email: p.owner_email,
        label: p.owner_email.split('@')[0] + ' (' + p.owner_email + ')',
      })
    }
  }
  return [...seen.values()]
})
const isLp = (p) => p.redirect_mode !== 'redirect'
const cntAll = computed(() => pages.value.length)
const cntLp = computed(() => pages.value.filter(isLp).length)
const cntShort = computed(() => cntAll.value - cntLp.value)
const visiblePages = computed(() => {
  let arr = modeFilter.value === 'short'
    ? sortedPages.value.filter(p => !isLp(p))
    : sortedPages.value.filter(isLp)
  if (ownerFilter.value) {
    arr = arr.filter(p => p.owner_email === ownerFilter.value)
  }
  return arr
})
// 批2：落地页/短链分流渲染——短链走行式（目标URL为主信息，无像素/自检等无关项）
const visibleLpPages = computed(() => visiblePages.value.filter(isLp))
const visibleShortPages = computed(() => visiblePages.value.filter(p => !isLp(p)))
const rotLabel = (m) => { const o = rotationOptions.value.find(x => x.v === (m || 'first')); return o ? o.l : (m || 'first') }
const emptyText = computed(() => ownerFilter.value
  ? t('landing.emptyOwnerFiltered', { owner: ownerFilter.value.split('@')[0] })
  : (modeFilter.value === 'short' ? t('landing.emptyNoShort') : t('landing.emptyNoLp')))

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
  protTestResult.value = null; showAdvanced.value = false   // 会话残留清理（复审P1：A页防护模拟结果曾带进B页/新建）
  // 新页默认开「屏蔽机房/VPN」（用平台集中清单）+ 屏蔽爬虫 + 必带广告参数——新页统一规范
  form.value.protection_rules = {
    datacenter_block: datacenterAsns.value.map(d => d.asn),
    ua_block: ['bot','crawler','spider','googlebot','bingbot','facebookexternalhit','preview','debug'],
    required_query: ['ad'],
  }
  form.value.block_enabled = true
  drawerOpen.value = true
  _lpSnap()
}
const openEdit = async (p) => {
  editingId.value = p.id
  protTestResult.value = null; showAdvanced.value = false   // 会话残留清理
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
    _lpSnap()
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

// 批CK：编辑抽屉 dirty-guard——最长表单（域名/像素/防护）曾无守卫，ESC 一键全丢
let _lpSnapshot = ''
const _lpSnap = () => { _lpSnapshot = JSON.stringify(form.value) }
const onLpBeforeClose = (done) => {
  if (JSON.stringify(form.value) === _lpSnapshot) return done()
  ElMessageBox.confirm(t('formtpl.discardConfirm'), t('formtpl.closeConfirm'),
    { type: 'warning', confirmButtonText: t('common.discard'), cancelButtonText: t('formtpl.keepEditing') })
    .then(() => done()).catch(() => {})
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
    _lpSnap()
    await loadPages()
    // 域名绑定失败不再静默（后端 bind_errors 带回）：逐条 toast，否则「发布成功但域名没绑上」无从排查
    if (resp && resp.bind_errors && resp.bind_errors.length) {
      resp.bind_errors.forEach((w) => ElMessage.warning(w))
    }
    if (resp && resp.self_check) showSelfCheck(resp.self_check, t('landing.scPostPublishTitle'))
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
  saving.value = false
}

const archive = async (p) => {
  try {
    await ElMessageBox.confirm(t('landing.archiveConfirm', { title: p.title }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' })
    await DELETE(`/landing/pages/${p.id}`); ElMessage.success(t('landing.archived')); await loadPages()
  } catch (e) { if (e !== 'cancel' && e?.message) ElMessage.error(e.message) }
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
    // 自检含 FB 封禁探测（域级+全部子码）可达数十秒——放宽到 120s，避免 30s 全局超时误报「请求超时」
    const r = await GET(`/landing/pages/${p.id}/health`, 120000)
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
  subFbStatus.value = {}; subTargetEdit.value = {}   // 换页清残留（复审P2：旧页单项检测结果曾带进新页）
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
  try { await ElMessageBox.confirm(t('landing.subArchiveConfirm', { slug: s.slug }), t('landing.subArchiveTitle'), { type: 'warning', confirmButtonClass: 'el-button--danger' })
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
    // 原地更新（单字段改动）——省掉子码分页全量重拉
    s.target_urls = subTargetEdit.value[s.id] || ''
    delete subTargetEdit.value[s.id]
    ElMessage.success(t('landing.subTargetSet'))
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
}
const copyUrl = (slug) => {
  // 旧版兼容（仅 FB 宏链接）
  const base = (subPage.value?.custom_domain || subPage.value?.custom_domains?.[0] || '').replace(/^https?:\/\//, '')
  if (!base) { ElMessage.warning(t('landing.copyUrlNoDomain')); return }
  const url = `https://${base}/a/${slug}?ad={{ad.id}}`
  navigator.clipboard?.writeText(url)
  ElMessage({ message: t('landing.copiedHtml', { url: _esc(url), macro: '{{ad.id}}' }), dangerouslyUseHTMLString: true, type: 'success', duration: 6000 })
}
const _subBase = () => {
  // 优先用 bound_subdomains[0]（实际绑定的子域名如 lp6.xxx.com），其次 custom_domain
  const raw = subPage.value?.bound_subdomains?.[0] || subPage.value?.custom_domain || ''
  const base = raw.replace(/^https?:\/\//, '').split('/')[0]
  if (!base) { ElMessage.warning(t('landing.copyUrlNoDomain')); return null }
  return base
}
const copyFbLink = async (slug) => {
  const base = _subBase(); if (!base) return
  const url = `https://${base}/a/${slug}?ad={{ad.id}}`
  const ok = await _copyRaw(url)
  if (ok) ElMessage({ message: t('landing.copiedFb', { url: _esc(url) }), dangerouslyUseHTMLString: true, type: 'success', duration: 6000 })
}
const copyTtLink = async (slug) => {
  const base = _subBase(); if (!base) return
  const url = `https://${base}/a/${slug}`
  await copyText(url, t('landing.copiedTt'))
}
const previewTestUrl = (slug) => {
  const base = _subBase(); if (!base) return ''
  if (!subPage.value?.preview_enabled) return ''
  const token = subPage.value?.preview_token || ''
  if (!token) return ''
  return `https://${base}/a/${slug}?_pv=${token}&ad=test123`
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
    if (r.capped) ElMessage.warning(t('landing.fbBatchCapped'))   // 后端限 50 个/批（超时会撞网关 + FB 限流）
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
const _copyRaw = async (txt) => {
  // clipboard 兜底（复审P1：非安全上下文/权限拒绝时曾「未复制却报成功」——广告链接贴错是真金白银）
  let ok = false
  try { await navigator.clipboard?.writeText(txt); ok = true } catch {}
  if (!ok) {
    try {
      const ta = document.createElement('textarea')
      ta.value = txt; ta.style.position = 'fixed'; ta.style.opacity = '0'
      document.body.appendChild(ta); ta.select()
      ok = document.execCommand('copy')
      ta.remove()
    } catch {}
  }
  if (!ok) ElMessage.error(t('landing.copyFail'))
  return ok
}
const openPreview = (url) => { if (url) window.open(url, '_blank', 'noopener') }
const copyText = async (txt, msg) => {
  const ok = await _copyRaw(txt)
  if (ok) ElMessage.success(msg || t('common.copied'))
}
const randomPrefix = () => 'go' + Math.random().toString(36).slice(2, 7)
const rootOf = (d) => { const h = (d || '').replace(/^https?:\/\//, '').split('/')[0]; const p = h.split('.'); return p.length >= 2 ? p.slice(-2).join('.') : h }
// 子域名管理
const newSubPrefix = ref('')
const newSubRoot = ref('')
const subAdding = ref(false)
const addSubdomain = async () => {
  const p = newSubPrefix.value.trim().toLowerCase()
  if (!p) return ElMessage.warning(t('landing.subPrefixRequired'))
  if (!editingId.value) return ElMessage.warning(t('landing.saveFirst'))
  subAdding.value = true
  try {
    const r = await POST(`/landing/pages/${editingId.value}/subdomains`, { prefix: p, root: newSubRoot.value || undefined })
    form.value.bound_subdomains = r.bound_subdomains || []
    newSubPrefix.value = ''
    ElMessage.success(t('landing.subAdded', { sub: r.subdomain }))
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  subAdding.value = false
}
const removeSubdomain = async (host) => {
  try {
    await ElMessageBox.confirm(t('landing.subDelConfirm', { host }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' })
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
      const r = await GET(`/landing/subdomain-check?prefix=${encodeURIComponent(prefix)}&root=${encodeURIComponent(rootOf(root))}&pid=${editingId.value || 0}`)
      subdomainStatus.value = r.available ? 'ok' : 'taken'
    } catch { subdomainStatus.value = '' }
  }, 400)
})

// ── 像素库管理 ──
const pixelOpen = ref(false)
const pixelForm = ref({ id: null, pixel_id: '', pixel_name: '', note: '', platform: 'fb', tt_access_token: '', test_event_code: '', fb_capi_enabled: false })
const pixelSaving = ref(false)
const syncing = ref(false)
const pixelChecking = ref(false)
const checkPixels = async () => {
  pixelChecking.value = true
  try {
    // 逐账户比对 FB 实况，多账户可达数十秒——放宽到 120s
    const r = await POST('/landing-lib/pixels/health-check', {}, 120000)
    if (r.dead?.length) {
      ElMessage.warning(t('landing.pixelCheckDead', { n: r.dead.length, acts: r.checked_acts }))
      await loadLib()
    } else {
      ElMessage.success(t('landing.pixelCheckClean', { alive: r.alive || 0, acts: r.checked_acts }))
      if (r.skipped_acts) ElMessage.info(t('landing.pixelCheckSkipped', { n: r.skipped_acts }))
    }
  } catch (e) { ElMessage.error(t('landing.syncFail') + '：' + (e.message || '')) }
  pixelChecking.value = false
}
const pixelTesting = ref(false)
const openPixels = () => { pixelOpen.value = true; pixelForm.value = { id: null, pixel_id: '', pixel_name: '', note: '', platform: 'fb', tt_access_token: '', test_event_code: '', fb_capi_enabled: false } }
const syncPixels = async () => {
  syncing.value = true
  try { const r = await POST('/landing-lib/pixels/sync', {}); ElMessage.success(t('landing.pixelSynced', { n: r.added || 0 })); await loadLib() }
  catch (e) { ElMessage.error(t('landing.syncFail') + '：' + (e.message || '')) }
  syncing.value = false
}
const editPixel = (p) => { pixelForm.value = { id: p.id, pixel_id: p.pixel_id, pixel_name: p.pixel_name || '', note: p.note || '', platform: p.platform || 'fb', tt_access_token: '', test_event_code: p.test_event_code || '', fb_capi_enabled: !!p.fb_capi_enabled } }
const delPixel = async (p) => {
  try { await ElMessageBox.confirm(t('landing.delPixelConfirm', { id: p.pixel_id }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' }); await DELETE(`/landing-lib/pixels/${p.id}`); ElMessage.success(t('common.done')); await loadLib() }
  catch (e) { if (e !== 'cancel' && e?.message) ElMessage.error(e.message) }
}
const savePixel = async () => {
  if (!pixelForm.value.pixel_id.trim()) return ElMessage.warning(t('landing.warnPixelId'))
  pixelSaving.value = true
  try {
    if (pixelForm.value.id) {
      await PUT(`/landing-lib/pixels/${pixelForm.value.id}`, { pixel_name: pixelForm.value.pixel_name, note: pixelForm.value.note, platform: pixelForm.value.platform, tt_access_token: pixelForm.value.tt_access_token || undefined, test_event_code: pixelForm.value.test_event_code || undefined, fb_capi_enabled: pixelForm.value.platform === 'fb' ? pixelForm.value.fb_capi_enabled : false })
      ElMessage.success(t('common.saved'))
    } else {
      const r = await POST('/landing-lib/pixels', { pixel_id: pixelForm.value.pixel_id.trim(), pixel_name: pixelForm.value.pixel_name, note: pixelForm.value.note, platform: pixelForm.value.platform, tt_access_token: pixelForm.value.tt_access_token || undefined, test_event_code: pixelForm.value.test_event_code || undefined })
      if (r?.auto_test?.attempted) {
        if (r.auto_test.ok) ElMessage.success(t('landing.autoLitOk'))
        else ElMessage.warning(t('landing.autoLitFail', { msg: r.auto_test.message || `code ${r.auto_test.code}` }))
      } else {
        ElMessage.success(t('common.done'))
      }
    }
    await loadLib()
    pixelForm.value = { id: null, pixel_id: '', pixel_name: '', note: '', platform: 'fb', tt_access_token: '', test_event_code: '', fb_capi_enabled: false }
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
  pixelSaving.value = false
}
const testS2s = async () => {
  if (!pixelForm.value.id) return ElMessage.warning(t('landing.testSaveFirst'))
  pixelTesting.value = true
  try {
    const r = await POST(`/landing-lib/pixels/${pixelForm.value.id}/test-s2s`)
    if (r.ok) ElMessage.success(r.hint || 'OK')
    else ElMessage.error(`TK API ${r.code}: ${r.message}`)
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  pixelTesting.value = false
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
const tplInlineUpload = ref(null)
const tplInlineUploading = ref(false)
const loadLandingTemplates = async () => { try { landingTemplates.value = await GET('/landing-lib/templates') } catch {} }
const onTplInline = async (e) => {
  const file = e.target.files?.[0]
  if (!file) return
  // 文件名（去 .zip 扩展名）作为模板名
  const tplName = file.name.replace(/\.zip$/i, '')
  tplInlineUploading.value = true
  try {
    const fd = new FormData()
    fd.append('name', tplName)
    fd.append('description', '')
    fd.append('file', file)
    const BASE = import.meta.env.VITE_API_BASE || 'https://api.tovaads.com'   // 全库审查P2：与下方 uploadLandingTpl/downloadTplRef 的 BASE 取法统一（原 '/api' 兜底打错端点）
    const r = await fetch(BASE + '/landing-lib/templates/upload', {
      method: 'POST', headers: { Authorization: 'Bearer ' + (localStorage.getItem('tova_token') || ''), 'X-Locale': localStorage.getItem('tova_locale') || 'zh' }, body: fd
    }).then(r => r.json())
    if (r.id) {
      await loadLandingTemplates()
      form.value.template_id = r.id  // 自动选中新模板
      ElMessage.success(t('landing.tplUploaded', { name: tplName, action: r.action === 'update' ? t('landing.tplUpdated') : t('landing.tplCreated') }))
      // 上传 warning 逐条提示（资源文件不会上线/硬编码像素等，不拦截）
      ;(r.warnings || []).forEach((w) => ElMessage.warning(w))
    } else {
      ElMessage.error(r.detail || t('common.opFail'))
    }
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  tplInlineUploading.value = false
  e.target.value = ''  // 清空 input 允许重复选同一文件
}
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
    const r = await fetch(BASE + '/landing-lib/templates/upload', { method: 'POST', headers: { Authorization: 'Bearer ' + (localStorage.getItem('tova_token') || ''), 'X-Locale': localStorage.getItem('tova_locale') || 'zh' }, body: fd })
    if (r.status === 401) { localStorage.removeItem('tova_token'); location.hash = '#/login'; throw new Error(t('landing.notLoggedIn')) }
    const text = await r.text(); let data = {}; try { data = JSON.parse(text) } catch {}
    if (!r.ok) throw new Error(data.detail || t('landing.uploadFail'))
    ElMessage.success(t('landing.uploadOk'))
    // 上传 warning 逐条提示（资源文件不会上线/硬编码像素等，不拦截）
    ;(data.warnings || []).forEach((w) => ElMessage.warning(w))
    tplForm.value = { name: '', description: '', file: null }; if (tplFileInput.value) tplFileInput.value.value = ''; await loadLandingTemplates()
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
  tplUploading.value = false
}
const delLandingTpl = async (tpl) => {
  try { await ElMessageBox.confirm(t('landing.delTplConfirm', { name: tpl.name }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' }); await DELETE(`/landing-lib/templates/${tpl.id}`); ElMessage.success(t('common.done')); await loadLandingTemplates() } catch (e) { if (e !== 'cancel' && e?.message) ElMessage.error(e.message) }
}
// ── 页面规范（对外文档，2026-09-14）：只讲「怎么写」，不讲内部实现。
// 交付方（外包/开发者）照此写页面 → zip 上传 → 严校验（不符规范拒传，报错引用条目）。
const SPEC_GUARD_CODE = `var _d=new URLSearchParams(location.search).get('_d');
var LP_PIXELS=(_d)?[]:(__LP_PIXELS_JSON__||[]);
var LP_CONV=(_d)?[]:(__LP_CONV_EVENT_JSON__||[]);
var LP_TT_PIXELS=(_d)?[]:(__LP_TT_PIXELS_JSON__||[]);
var LP_TT_CONV=(_d)?[]:(__LP_TT_CONV_JSON__||[]);
var LP_TARGET_URL="__LP_TARGET_URL__";`
const SPEC_TABLE = computed(() => [
  { ph: '{{TITLE}}', req: true, desc: t('landing.specPhTitle') },
  { ph: '__LP_TARGET_URL__', req: true, desc: t('landing.specPhTarget') },
  { ph: '__LP_PIXELS_JSON__', req: true, desc: t('landing.specPhPixels') },
  { ph: '{{DESCRIPTION}}', req: false, desc: t('landing.specPhDesc') },
  { ph: '__LP_CONV_EVENT_JSON__', req: false, desc: t('landing.specPhConv') },
  { ph: '__LP_TT_PIXELS_JSON__', req: false, desc: t('landing.specPhTtPixels') },
  { ph: '__LP_TT_CONV_JSON__', req: false, desc: t('landing.specPhTtConv') },
])
const SPEC_SECTIONS = computed(() => [
  { key: 'file', title: t('landing.specSecFile'), lines: [t('landing.specFileL1'), t('landing.specFileL2')] },
  { key: 'ph', title: t('landing.specSecPh'), table: true },
  { key: 'guard', title: t('landing.specSecGuard'), lines: [t('landing.specGuardL1'), t('landing.specGuardL2')], code: SPEC_GUARD_CODE },
  { key: 'pixel', title: t('landing.specSecPixel'), lines: [t('landing.specPixelL1')] },
  { key: 'link', title: t('landing.specSecLink'), lines: [t('landing.specLinkL1'), t('landing.specLinkL2')] },
  { key: 'zip', title: t('landing.specSecZip'), lines: [t('landing.specZipL1'), t('landing.specZipL2')] },
  { key: 'check', title: t('landing.specSecCheck'), lines: [t('landing.specChk1'), t('landing.specChk2'), t('landing.specChk3'), t('landing.specChk4')] },
])
const copySpecCode = () => { navigator.clipboard?.writeText(SPEC_GUARD_CODE); ElMessage.success(t('common.copied')) }
// 下载已上传模板（zip 打包回本地——可改后经上传同名覆盖传回；用户 2026-09-12 要求）
const downloadLandingTpl = async (tpl) => {
  const BASE = import.meta.env.VITE_API_BASE || 'https://api.tovaads.com'
  try {
    const r = await fetch(BASE + `/landing-lib/templates/${tpl.id}/download`, { headers: { Authorization: 'Bearer ' + (localStorage.getItem('tova_token') || '') } })
    if (!r.ok) throw new Error(`${r.status}`)
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `${tpl.name || ('template-' + tpl.id)}.zip`
    document.body.appendChild(a); a.click()
    setTimeout(() => { URL.revokeObjectURL(url); a.remove() }, 800)
    ElMessage.success(t('landing.tplDlStarted', { name: tpl.name }))
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
}
// 模板改名/描述（内容更新走上传同名 zip 覆盖）
const tplRenameId = ref(null)
const tplRenameForm = ref({ name: '', description: '' })
const tplRenameSaving = ref(false)
const openTplRename = (tpl) => {
  tplRenameId.value = tpl.id
  tplRenameForm.value = { name: tpl.name, description: tpl.description || '' }
}
const saveTplRename = async () => {
  if (!tplRenameForm.value.name.trim()) return ElMessage.warning(t('landing.warnTplName'))
  tplRenameSaving.value = true
  try {
    await PUT(`/landing-lib/templates/${tplRenameId.value}/meta`, {
      name: tplRenameForm.value.name.trim(),
      description: tplRenameForm.value.description.trim(),
    })
    ElMessage.success(t('common.saved'))
    tplRenameId.value = null
    await loadLandingTemplates()
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  tplRenameSaving.value = false
}
const downloadTplRef = () => {
  const BASE = import.meta.env.VITE_API_BASE || 'https://api.tovaads.com'
  fetch(BASE + '/landing-lib/templates/reference', { headers: { Authorization: 'Bearer ' + (localStorage.getItem('tova_token') || ''), 'X-Locale': localStorage.getItem('tova_locale') || 'zh' } })
    .then(r => r.blob()).then(b => { const url = URL.createObjectURL(b); const a = document.createElement('a'); a.href = url; a.download = 'template-reference.zip'; a.click(); URL.revokeObjectURL(url) })
}
const zoneFilter = ref('')
const filteredZones = computed(() => { const k = zoneFilter.value.trim().toLowerCase(); return k ? cfZones.value.filter(z => z.name.toLowerCase().includes(k)) : cfZones.value })
// CF zone 状态术语（active/pending；服务商原始值兜底显示）
const zoneStatusLabel = (s) => s === 'active' ? t('landing.zoneActive') : (s === 'pending' ? t('landing.zonePending') : (s || '—'))
// 已导入域名行的 DNS 实况：抽屉里 cfZones 就是同一账户的全量 zone，按名对上即得（库里的 cf_zone_status 旧行没存）
const dnsLive = (d) => (cfZones.value.find(z => z.name === d.domain) || {}).status || d.cf_zone_status || ''
const zoneSelCount = computed(() => cfZones.value.filter(z => z._checked && !z.imported).length)
const domainStats = ref({})
const openDomains = async () => {
  domainOpen.value = true; zonesLoading.value = true; zoneFilter.value = ''
  try { cfZones.value = (await GET('/landing-lib/cf-zones')).map(z => ({ ...z, _checked: false })) }
  catch (e) { ElMessage.error(e.message || t('landing.loadFail')) }
  finally { zonesLoading.value = false }
  try { domainStats.value = {}; for (const r of (await GET('/landing-lib/domains/stats')) || []) domainStats.value[r.domain] = r }
  catch {}   // 统计是辅助信息，失败不阻断
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
  // 批BW：全页唯一裸删 → 补确认（删的是线上域名：解析与 /a/ 链接即时受影响）
  try {
    await ElMessageBox.confirm(t('landing.domainDelConfirm', { d: d.domain }), t('common.delConfirm'), { type: 'warning', confirmButtonText: t('common.delConfirm'), confirmButtonClass: 'el-button--danger' })
  } catch { return }
  try { await DELETE(`/landing-lib/domains/${d.id}`); ElMessage.success(t('common.done')); await loadLib(); await openDomains() }
  catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
}

const init = async () => {
  await Promise.all([loadPages(), loadLib()]); loadLandingTemplates()
  // 超管标志读 MainLayout 挂载时写入的 localStorage（省一次 /auth/me）
  isSuper.value = localStorage.getItem('tova_super') === '1'
}
onMounted(async () => { loadAsnBlocklist(); await init() })   // ASN 清单仅新建表单用——并行不阻塞首屏
</script>

<template>
  <div class="page">
    <div class="lp-tabs">
      <div :class="['lp-tab', { on: tab === 'manage' }]" @click="setTab('manage')">{{ t('landing.tabManage') }}</div>
      <div :class="['lp-tab', { on: tab === 'logs' }]" @click="setTab('logs')">{{ t('landing.tabLogs') }}</div>
    </div>
    <div v-show="tab === 'manage'">
    <header class="page-head">
      <div class="ph-left">
        <h1 class="ph-title">{{ t('landing.pageTitle') }}</h1>
        <span class="ph-fresh">{{ t('landing.headMeta', { n: pages.length, blocked: pages.filter(p => p.last_fb_status === 'fail').length }) }}</span>
      </div>
      <div class="ph-actions">
        <button class="head-btn" @click="openPixels">{{ t('landing.pixelLib') }}</button>
        <button v-if="isSuper" class="head-btn" @click="openDomains">{{ t('landing.domainMgmt') }}</button>
        <el-dropdown trigger="click" @command="cmd => { if(cmd==='templates')openLandingTemplates(); }">
          <button class="head-btn">{{ t('landing.tools') }} ▾</button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="templates">{{ t('landing.templates') }}</el-dropdown-item>
                          </el-dropdown-menu>
          </template>
        </el-dropdown>
        <button class="head-btn primary" @click="openCreate">+ {{ t('landing.newLink') }}</button>
      </div>
    </header>

    <!-- 统一工具栏：模式筛选 + 创建人筛选（owner 看全团队时按人过滤）+ 计数 -->
    <div class="list-bar">
      <div class="seg-bar">
        <button class="seg-btn" :class="{ on: modeFilter === 'lp' }" @click="modeFilter = 'lp'">📄 {{ t('landing.tabLpOnly') }} <i class="seg-cnt">{{ cntLp }}</i></button>
        <button class="seg-btn" :class="{ on: modeFilter === 'short' }" @click="modeFilter = 'short'">🔗 {{ t('landing.tabShortOnly') }} <i class="seg-cnt">{{ cntShort }}</i></button>
      </div>
      <el-select v-if="ownerOptions.length > 1" v-model="ownerFilter" clearable size="small"
                 :placeholder="t('landing.filterByOwner')" style="width:160px;margin-left:auto"
                 :title="t('landing.filterByOwnerTip')">
        <el-option v-for="o in ownerOptions" :key="o.email" :value="o.email" :label="o.label" />
      </el-select>
    </div>

    <!-- 表头（2026-09-16 重设计：列表升为表格语义——列有名、列对齐、密度受控；
         域名从「按钮堆」降为文本属性（主域+N），操作收敛为 2 常驻 + ⋯ 菜单 -->
    <div v-if="visibleLpPages.length" class="lp-thead">
      <span>{{ t('landing.lpColStatus') }}</span>
      <span>{{ t('landing.lpColLink') }}</span>
      <span>{{ t('landing.fDomain') }}</span>
      <span>{{ t('landing.stSubcodes') }}</span>
      <span>{{ t('landing.stVisits') }}·{{ t('landing.todayShort') }}</span>
      <span>{{ t('landing.stPass') }}·{{ t('landing.todayShort') }}</span>
      <span>{{ t('landing.stBlocked') }}·{{ t('landing.todayShort') }}</span>
      <span>FB</span>
      <span></span>
    </div>
    <div class="list" v-loading="loading">
      <!-- 落地页行式（2026-09-15 重大重构）：卡退场——行=状态+标题+域名+子码·像素+今日三指标+标记+操作；
           7天/累计/通过率全部收进 hover，编辑/子码/自检进抽屉 -->
      <div v-if="visibleLpPages.length" class="short-list">
        <div v-for="p in visibleLpPages" :key="p.id" :class="['short-row', 'lp-row2', p.last_fb_status === 'fail' ? 'alert-fail' : '']">
          <span class="st-tag" :class="lpStatus(p.status).cls">{{ lpStatus(p.status).label }}</span>
          <span class="lp-name">
            <span class="short-title" :title="p.title">{{ p.title }}</span>
            <span v-if="p.owner_email" class="owner-chip clickable" :title="t('landing.createdBy') + ': ' + p.owner_email + ' · ' + t('landing.clickToFilter')"
                  @click.stop="ownerFilter = (ownerFilter === p.owner_email ? '' : p.owner_email)">{{ p.owner_email.split('@')[0] }}</span>
          </span>
          <span class="lp-dom" v-if="p.bound_subdomains && p.bound_subdomains.length"
                :title="p.bound_subdomains.join('\n') + ' · ' + t('common.copy')"
                @click.stop="copyText('https://' + p.bound_subdomains[0], t('landing.publicUrlCopied'))">
            {{ p.bound_subdomains[0] }}<i v-if="p.bound_subdomains.length > 1"> +{{ p.bound_subdomains.length - 1 }}</i>
          </span>
          <span v-else class="lp-dom muted">—</span>
          <span class="lp-subcount" :title="(p.pixel_ids||[]).length + ' ' + t('landing.pixelsUnit')">{{ p.subcode_count || 0 }}</span>
          <span class="short-stat" :title="t('landing.stVisitsTip') + ' · ' + t('landing.stMore', { v: p.last7d_visit || 0, a: p.visit_count || 0 })">{{ p.today_visit || 0 }}<i>{{ t('landing.stVisits') }}·{{ t('landing.todayShort') }}</i></span>
          <span class="short-stat" :title="t('landing.stPassTip') + ' · ' + t('landing.stMore', { v: p.last7d_click || 0, a: p.click_count || 0 })">{{ p.today_click || 0 }}<i>{{ t('landing.stPass') }}·{{ t('landing.todayShort') }}</i></span>
          <span class="short-stat" :title="t('landing.stBlockedTip') + ' · ' + t('landing.stMore', { v: p.last7d_block || 0, a: p.block_count || 0 }) + ' · ' + t('landing.stPassRateTip') + ' ' + (p.pass_rate || 0) + '%（累计）'">{{ p.today_block || 0 }}<i>{{ t('landing.stBlocked') }}·{{ t('landing.todayShort') }}</i></span>
          <span v-if="p.last_fb_status==='fail'" class="tag fb-block" :title="t('landing.fbBlockedTip', { summary: p.last_health_summary || '' })">⛔ {{ t('landing.fbBlocked') }}</span>
          <span v-else-if="p.last_fb_status==='warn'" class="tag fb-warn" :title="p.last_health_summary || t('landing.fbWarnTip')">{{ t('landing.fbPending') }}</span>
          <span v-else-if="p.last_health_status" class="health-dot" :class="p.last_health_status" :title="p.last_health_summary || ''"></span>
          <span v-else class="lp-fb-empty"></span>
          <div class="short-ops">
            <button class="mb" @click="openSubcodes(p)">{{ t('landing.subcodes') }}</button>
            <button class="mb" @click="openEdit(p)">{{ t('common.edit') }}</button>
            <el-dropdown trigger="click" @command="cmd => { if (cmd==='check') checkHealth(p); else if (cmd==='preview') openPreview(p.preview_url); else if (cmd==='archive') archive(p) }">
              <button class="mb" :title="t('landing.moreOps')">⋯</button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="check" :disabled="healthCheckingId === p.id">{{ healthCheckingId === p.id ? t('landing.checking') : t('landing.selfCheck') }}</el-dropdown-item>
                  <el-dropdown-item command="preview" :disabled="!p.preview_url">{{ t('common.preview') }}</el-dropdown-item>
                  <el-dropdown-item command="archive" divided>{{ t('landing.archive') }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </div>
      <div v-if="visibleShortPages.length" class="lp-thead">
        <span>{{ t('landing.lpColStatus') }}</span>
        <span>{{ t('landing.lpColLink') }}</span>
        <span>{{ t('landing.lpColTarget') }}</span>
        <span>{{ t('landing.stSubcodes') }}</span>
        <span>{{ t('landing.stVisits') }}·{{ t('landing.todayShort') }}</span>
        <span>{{ t('landing.stPass') }}·{{ t('landing.todayShort') }}</span>
        <span>{{ t('landing.stBlocked') }}·{{ t('landing.todayShort') }}</span>
        <span>FB</span>
        <span></span>
      </div>
    <!-- 短链行式（2026-09-16 重设计：与落地页同表结构） -->
      <div v-if="visibleShortPages.length" class="short-list">
        <div v-for="p in visibleShortPages" :key="'s'+p.id" :class="['short-row', 'lp-row2', p.last_fb_status === 'fail' ? 'alert-fail' : '']">
          <span class="st-tag" :class="lpStatus(p.status).cls">{{ lpStatus(p.status).label }}</span>
          <span class="lp-name">
            <span class="short-title" :title="p.title">{{ p.title }}</span>
            <span v-if="p.owner_email" class="owner-chip clickable" :title="t('landing.createdBy') + ': ' + p.owner_email + ' · ' + t('landing.clickToFilter')"
                  @click.stop="ownerFilter = (ownerFilter === p.owner_email ? '' : p.owner_email)">{{ p.owner_email.split('@')[0] }}</span>
          </span>
          <span class="lp-dom" :title="(p.target_urls||[]).join('\n') + ' · ' + t('common.copy')"
                @click.stop="copyText((p.target_urls||[])[0] || '', t('common.copied'))">
            {{ (p.target_urls||[])[0] || '—' }}<i v-if="(p.target_urls||[]).length > 1"> +{{ p.target_urls.length - 1 }}</i>
          </span>
          <span class="lp-subcount">{{ p.subcode_count || 0 }}</span>
          <span class="short-stat" :title="t('landing.stVisitsTip')">{{ p.today_visit || 0 }}<i>{{ t('landing.stVisits') }}·{{ t('landing.todayShort') }}</i></span>
          <span class="short-stat" :title="t('landing.stPassTip')">{{ p.today_click || 0 }}<i>{{ t('landing.stPass') }}·{{ t('landing.todayShort') }}</i></span>
          <span class="short-stat" :title="t('landing.stMore', { v: p.last7d_block || 0, a: p.block_count || 0 })">{{ p.today_block || 0 }}<i>{{ t('landing.stBlocked') }}·{{ t('landing.todayShort') }}</i></span>
          <span class="lp-fb-empty"></span>
          <div class="short-ops">
            <button class="mb" @click="openSubcodes(p)">{{ t('landing.subcodes') }}</button>
            <button class="mb" @click="openEdit(p)">{{ t('common.edit') }}</button>
            <el-dropdown trigger="click" @command="cmd => { if (cmd==='archive') archive(p) }">
              <button class="mb" :title="t('landing.moreOps')">⋯</button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="archive">{{ t('landing.archive') }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </div>
      <div v-if="!visiblePages.length && !loading" class="empty">
        <div>{{ emptyText }}</div>
        <button v-if="ownerFilter" class="btn" @click="ownerFilter = ''">{{ t('landing.clearOwnerFilter') }}</button>
        <button v-else class="btn primary empty-cta-btn" @click="openCreate">+ {{ t('landing.newLink') }}</button>
      </div>
    </div>

    <el-drawer v-model="drawerOpen" :title="editingId ? t('landing.editTitle') : t('landing.createTitle')" direction="rtl" size="580px" :destroy-on-close="true" :close-on-click-modal="false" :before-close="onLpBeforeClose" v-loading="saving" :element-loading-text="saving ? t('landing.deployingCloud') : ''">
      <div class="lp-section">
        <div class="lp-section-title">{{ t('landing.secBasic') }}</div>
        <div class="lp-section-body">
      <div class="form-l"><label>{{ t('landing.fTitle') }}</label><input v-model="form.title" class="input" :placeholder="t('landing.fTitlePh')" /></div>
      <div class="form-l"><label>{{ t('landing.accessMode') }}</label>
        <div class="mode-picker">
          <div :class="['mode-card', { on: form.redirect_mode === 'display' }]" @click="form.redirect_mode = 'display'">
            <div class="mode-card-title">📄 {{ t('landing.modeDisplay') }}</div>
            <div class="mode-card-desc">{{ t('landing.modeHintDisplay') }}</div>
          </div>
          <div :class="['mode-card', { on: form.redirect_mode === 'redirect' }]" @click="form.redirect_mode = 'redirect'">
            <div class="mode-card-title">🔗 {{ t('landing.modeRedirect') }}</div>
            <div class="mode-card-desc">{{ t('landing.modeHintRedirect') }}</div>
          </div>
        </div>
      </div>

      <div class="form-l"><label>{{ form.redirect_mode === 'redirect' ? t('landing.fRedirectUrl') : t('landing.fTargetUrl') }}</label>
        <el-select v-model="form.target_urls" multiple filterable allow-create default-first-option
          :placeholder="form.redirect_mode === 'redirect' ? t('landing.fRedirectUrlPh') : t('landing.fTargetUrlPh')" style="flex:1" />
      </div>
      <div class="form-l"><label>{{ t('landing.fRotation') }}</label>
        <select v-model="form.rotation_mode" class="input">
          <option v-for="o in rotationOptions" :key="o.v" :value="o.v">{{ o.l }}</option>
        </select>
      </div>
      <div class="form-l" v-if="form.redirect_mode === 'display'"><label>{{ t('landing.fLandingTpl') }}</label>
        <select v-model="form.template_id" class="input" style="flex:1">
          <option :value="null">{{ t('landing.defaultTpl') }}</option>
          <option v-for="tpl in landingTemplates" :key="tpl.id" :value="tpl.id">{{ tpl.name }}</option>
        </select>
        <button class="btn sm" @click="tplInlineUpload.click()" :title="t('landing.uploadTplHint')" :disabled="tplInlineUploading">📤</button>
        <input ref="tplInlineUpload" type="file" accept=".zip" @change="onTplInline" style="display:none" />
      </div>
      <div class="pixel-hint" v-if="form.redirect_mode === 'display' && form.template_id" style="margin:0 0 6px">
        <a href="#" @click.prevent="openLandingTemplates" style="color:var(--ac)">{{ t('landing.tplMgmt') }}</a>
        <span v-if="tplInlineUploading" style="margin-left:8px">{{ t('landing.uploading') }}</span>
      </div>
        </div>
      </div>

      <div class="lp-section">
        <div class="lp-section-title">{{ t('landing.secDomain') }}</div>
        <div class="lp-section-body">
      <div class="form-l"><label>{{ t('landing.fDomain') }}</label>
        <el-select v-model="form.custom_domains" multiple filterable allow-create default-first-option
          :placeholder="t('landing.fDomainPh')" style="flex:1">
          <el-option v-for="d in domains" :key="d.id" :value="d.domain" :disabled="d.blocked"
                     :label="d.domain + (d.label ? ' ('+d.label+')' : '') + (d.blocked ? ' ⛔' : '')" />
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
        <select v-model="newSubRoot" class="input" style="width:160px;flex:none" v-if="(form.custom_domains||[]).length > 1">
          <option v-for="d in form.custom_domains" :key="d" :value="d">{{ rootOf(d) }}</option>
        </select>
        <button class="mb" type="button" @click="newSubPrefix = randomPrefix()">🎲</button>
        <button class="btn sm primary" :disabled="subAdding || !newSubPrefix.trim() || !editingId" @click="addSubdomain">{{ subAdding ? '…' : t('common.add') }}</button>
      </div>
      <div class="pixel-hint" v-if="form.custom_domains.length">{{ t('landing.addSubHint') }}</div>
      <div class="form-l" v-if="form.custom_domain"><label>{{ t('landing.fPublicUrl') }}</label>
        <span class="url-text" style="flex:1">🔗 {{ form.custom_domain }}</span>
        <button class="mb" @click="copyText(form.custom_domain, t('landing.publicUrlCopied'))">{{ t('common.copy') }}</button>
      </div>
        </div>
      </div>

      <div class="lp-section" v-if="form.redirect_mode === 'display'">
        <div class="lp-section-title">{{ t('landing.secPixel') }}</div>
        <div class="lp-section-body">

      <template v-if="form.redirect_mode === 'display'">
        <!-- Facebook 像素区块 -->
        <div class="pixel-section fb-section">
          <div class="pixel-section-header brand-fb">Facebook</div>
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
          <div class="pixel-section-header brand-tt">TikTok</div>
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
      </template>
        </div>
      </div>

      <div class="lp-section">
        <div class="lp-section-title">{{ t('landing.secProtection') }}</div>
        <div class="lp-section-body">

      <div class="sec-title">{{ t('landing.dedup') }} <el-switch v-model="form.dedup_enabled" size="small" style="margin-left:8px" /></div>
      <template v-if="form.dedup_enabled">
        <div class="form-l"><label>{{ t('landing.fDedupWindow') }}</label>
          <input v-model.number="form.dedup_window_hours" type="number" min="1" class="input" style="flex:1" />
        </div>
      </template>
      <div class="sec-title">{{ t('landing.protectionRules') }} <el-switch v-model="form.block_enabled" size="small" style="margin-left:8px" /></div>
      <div class="form-l" v-if="form.block_enabled"><label>{{ t('landing.fPreviewMode') }}</label>
        <el-switch v-model="form.preview_enabled" size="small" />
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
        </div>
      </div>

      <template #footer>
        <button class="btn" @click="onLpBeforeClose(() => drawerOpen=false)">{{ t('common.cancel') }}</button>
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
            <span class="sub-stat" :title="t('landing.subStatTodayTip')">{{ t('landing.subStat', { visit: s.visit_count||0, click: s.click_count||0 }) }}<i style="font-style:normal;color:var(--t3);font-size:10px;margin-left:2px">{{ t('landing.todayShort') }}</i></span>
            <span v-if="subFbStatus[s.slug] && !subFbStatus[s.slug].loading" class="fb-badge" :class="subFbStatus[s.slug].status" :title="subFbStatus[s.slug].detail">{{ subFbStatus[s.slug].status === 'pass' ? t('landing.fbOk') : (subFbStatus[s.slug].status === 'fail' ? t('landing.fbBanned') : t('landing.fbUnknown')) }}</span>
            <template v-if="subStatus !== 'trash'">
              <div class="sub-ops">
                <button class="mb" @click="goSubLogs(s)">{{ t('landing.logsBtn') }}</button>
                <button class="mb" :title="t('landing.subEventsTip')" @click="openSubEvents(s)">{{ t('landing.subEventsBtn') }}</button>
                <button class="btn-link fb" @click="copyFbLink(s.slug)" :title="t('landing.copyFbLink')">f FB</button>
                <button class="btn-link tt" @click="copyTtLink(s.slug)" :title="t('landing.copyTtLink')">♪ TK</button>
                <a v-if="previewTestUrl(s.slug)" class="btn-link preview" :href="previewTestUrl(s.slug)" target="_blank" rel="noopener" :title="t('landing.previewTestLink')">👁</a>
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
      <div style="margin-bottom:14px;display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn" :disabled="syncing" @click="syncPixels">{{ syncing ? t('landing.pixelSyncing') : t('landing.pixelSync') }}</button>
        <button class="btn" :disabled="pixelChecking" :title="t('landing.pixelCheckTip')" @click="checkPixels">{{ pixelChecking ? t('landing.pixelChecking') : t('landing.pixelCheckBtn') }}</button>
      </div>
      <div class="sec-title">{{ pixelForm.id ? t('landing.pixelEdit') : t('landing.pixelAdd') }}</div>
      <div class="form-l"><label>{{ t('landing.fPixelId') }}</label><input v-model="pixelForm.pixel_id" class="input" :placeholder="t('landing.fPixelIdPh')" :disabled="!!pixelForm.id" /></div>
      <div class="form-l"><label>{{ t('landing.fPixelPlatform') }}</label>
        <select v-model="pixelForm.platform" class="input">
          <option value="fb">Facebook</option>
          <option value="tt">TikTok</option>
        </select>
      </div>
      <div class="form-l"><label>{{ t('common.name') }}</label><input v-model="pixelForm.pixel_name" class="input" :placeholder="t('landing.pixelNamePh')" /></div>
      <div class="form-l" v-if="pixelForm.platform === 'fb' && pixelForm.id"><label>{{ t('landing.fbCapiLabel') }}</label>
        <el-switch v-model="pixelForm.fb_capi_enabled" size="small" />
      </div>
      <div class="pixel-hint" v-if="pixelForm.platform === 'fb' && pixelForm.id" style="margin:0 0 10px">{{ t('landing.fbCapiHint') }}</div>
      <div class="form-l" v-if="pixelForm.platform === 'tt'"><label>{{ t('landing.fTtToken') }}</label><input v-model="pixelForm.tt_access_token" class="input" type="password" :placeholder="t('landing.fTtTokenPh')" /></div>
      <div class="form-l" v-if="pixelForm.platform === 'tt'"><label>{{ t('landing.fTestCode') }}</label><input v-model="pixelForm.test_event_code" class="input" :placeholder="t('landing.fTestCodePh')" /></div>
      <div class="pixel-hint" v-if="pixelForm.platform === 'tt'" style="margin:0 0 10px">{{ t('landing.fTtTokenHint') }}</div>
      <button class="btn" v-if="pixelForm.platform === 'tt' && pixelForm.id" :disabled="pixelTesting" @click="testS2s" style="margin-bottom:12px">{{ pixelTesting ? '…' : t('landing.testS2sBtn') }}</button>
      <button class="btn primary" :disabled="pixelSaving" @click="savePixel">{{ pixelForm.id ? t('common.save') : t('common.add') }}</button>
      <div class="sec-title">{{ t('landing.pixelList') }}</div>
      <div class="sub-list">
        <div v-for="p in pixels" :key="p.id" class="sub-row">
          <span :class="['plat-chip', p.platform || 'fb']">{{ (p.platform || 'fb').toUpperCase() }}</span>
          <code>{{ p.pixel_id }}</code>
          <span v-if="p.status === 'dead'" class="fb-badge fail" :title="t('landing.pixelDeadTip')">⛔ {{ t('landing.pixelDead') }}</span>
          <span class="sub-ad">{{ p.pixel_name || '-' }}</span>
          <span v-if="p.platform === 'tt'" class="tag" :class="p.tt_has_token ? 'ok' : 'warn'">{{ p.tt_has_token ? t('landing.hasToken') : t('landing.noToken') }}</span>
          <span v-if="(p.platform || 'fb') === 'fb' && p.fb_capi_enabled" class="tag ok" :title="t('landing.fbCapiLabel')">{{ t('landing.fbCapiTag') }}</span>
          <span class="tag">{{ t('landing.pixelPages', { n: p.usage_count }) }}</span>
          <button class="mb" style="margin-left:auto" @click="editPixel(p)">{{ t('common.edit') }}</button>
          <button class="mb danger" @click="delPixel(p)">{{ t('common.delete') }}</button>
        </div>
        <div v-if="!pixels.length" class="empty">{{ t('landing.pixelEmpty') }}</div>
      </div>
    </el-drawer>

    <el-drawer v-if="isSuper" v-model="domainOpen" :title="t('landing.domainMgmt')" direction="rtl" size="560px" :destroy-on-close="true" append-to-body>
      <div class="dm-sec-title">{{ t('landing.importableDomains') }} <i>{{ filteredZones.filter(z => !z.imported).length }}</i></div>
      <input v-model="zoneFilter" class="input" :placeholder="t('landing.searchDomains')" style="margin-bottom:8px;width:100%;box-sizing:border-box" />
      <div class="zone-list" v-loading="zonesLoading">
        <label v-for="z in filteredZones" :key="z.name" class="zone-row" :class="{ imported: z.imported }">
          <input type="checkbox" v-model="z._checked" :disabled="z.imported" />
          <code>{{ z.name }}</code>
          <span class="st-tag" :class="z.imported ? 'off' : (z.status === 'active' ? 'ok' : 'warn')">{{ z.imported ? t('landing.zoneImported') : zoneStatusLabel(z.status) }}</span>
        </label>
        <div v-if="!cfZones.length && !zonesLoading" class="empty">{{ t('landing.noImportableDomains') }}</div>
      </div>
      <div class="zone-import-bar">
        <span class="zone-sel-hint">{{ t('landing.zonesSelected', { n: zoneSelCount }) }}</span>
        <button class="btn primary" :disabled="!zoneSelCount" @click="importZones">{{ t('landing.importSelected') }}</button>
      </div>
      <div class="dm-sec-title">{{ t('landing.importedDomains') }} <i>{{ domains.length }}</i></div>
      <div class="dm-table">
        <div class="dm-row dm-head-row">
          <span>{{ t('landing.fDomain') }}</span><span>DNS</span><span>{{ t('landing.dmUsage') }}</span>
          <span>{{ t('landing.stVisits') }}·{{ t('landing.todayShort') }}</span><span>{{ t('landing.stPass') }}·{{ t('landing.todayShort') }}</span><span></span>
        </div>
        <div v-for="d in domains" :key="d.id" class="dm-row">
          <span class="dm-name"><code>{{ d.domain }}</code><span v-if="d.blocked" class="dm-blocked" :title="t('landing.fbBlocked')">⛔</span></span>
          <span :class="['tag', dnsLive(d) === 'active' ? 'ok' : (dnsLive(d) ? 'warn' : '')]" :title="dnsLive(d)">{{ zoneStatusLabel(dnsLive(d)) }}</span>
          <span class="sub-ad">{{ d.usage_count || 0 }} {{ t('landing.pagesUnit') }}<i v-if="d.label"> · {{ d.label }}</i></span>
          <span class="dm-num" :title="t('landing.stMore', { v: (domainStats[d.domain] || {}).last7d_visits || 0, a: (domainStats[d.domain] || {}).visits || 0 })">{{ (domainStats[d.domain] || {}).today_visits ?? '—' }}</span>
          <span class="dm-num" :title="t('landing.stMore', { v: (domainStats[d.domain] || {}).last7d_pass || 0, a: (domainStats[d.domain] || {}).pass || 0 })">{{ (domainStats[d.domain] || {}).today_pass ?? '—' }}</span>
          <button class="mb danger" @click="delDomain(d)">{{ t('common.delete') }}</button>
        </div>
        <div v-if="!domains.length" class="empty">{{ t('landing.noDomainsImported') }}</div>
      </div>
    </el-drawer>

    <el-drawer v-model="tplOpen" :title="t('landing.tplDrawerTitle')" direction="rtl" size="600px" :destroy-on-close="true" append-to-body>
      <!-- ① 页面规范（对外文档：只讲怎么写；交付方照此交付，上传严校验引用条目号） -->
      <div class="sec-title">{{ t('landing.specTitle') }}</div>
      <button class="btn" @click="downloadTplRef" style="margin-bottom:10px">{{ t('landing.downloadRefTpl') }}</button>
      <div v-for="sec in SPEC_SECTIONS" :key="sec.key" class="spec-sec">
        <div class="spec-t">{{ sec.title }}</div>
        <div v-for="(ln, i) in (sec.lines || [])" :key="i" class="spec-ln">{{ ln }}</div>
        <table v-if="sec.table" class="spec-table">
          <tr v-for="r in SPEC_TABLE" :key="r.ph">
            <td><code>{{ r.ph }}</code></td>
            <td class="spec-req"><span class="tag" :class="r.req ? 'ok' : ''">{{ r.req ? t('landing.specReq') : t('landing.specOpt') }}</span></td>
            <td class="spec-desc">{{ r.desc }}</td>
          </tr>
        </table>
        <div v-if="sec.code" class="spec-code-wrap">
          <pre class="spec-code">{{ sec.code }}</pre>
          <button class="mb" @click="copySpecCode">{{ t('common.copy') }}</button>
        </div>
      </div>

      <!-- ② 上传（严校验：不符规范直接拒传，报错会指明违反的条目） -->
      <div class="sec-title">{{ t('landing.uploadNewTpl') }}</div>
      <div class="form-l"><label>{{ t('landing.fTplName') }}</label><input v-model="tplForm.name" class="input" :placeholder="t('landing.fTplNamePh')" /></div>
      <div class="form-l"><label>{{ t('landing.fTplDesc') }}</label><input v-model="tplForm.description" class="input" :placeholder="t('common.optional')" /></div>
      <div class="form-l"><label>{{ t('landing.fZipFile') }}</label><input ref="tplFileInput" type="file" accept=".zip" @change="onTplFile" class="input" /></div>
      <button class="btn primary" :disabled="tplUploading" @click="uploadLandingTpl">{{ tplUploading ? t('landing.uploading') : t('landing.uploadAndCheck') }}</button>
      <!-- ③ 已传列表 -->
      <div class="sec-title">{{ t('landing.uploadedTpls') }}</div>
      <div class="sub-list">
        <div v-for="tpl in landingTemplates" :key="tpl.id" class="sub-row tpl-row">
          <template v-if="tplRenameId !== tpl.id">
            <div class="tpl-info">
              <code :title="tpl.name">{{ tpl.name }}</code>
              <span v-if="tpl.created_by_name" class="owner-chip" :title="tpl.created_by_name">{{ tpl.created_by_name.split('@')[0] }}</span>
              <span v-if="tpl.is_builtin" class="tag">{{ t('landing.tplBuiltin') }}</span>
              <span v-if="tpl.has_resources" class="tag" :title="t('landing.multiFileTip')">{{ t('landing.multiFile') }}</span>
              <span v-if="tpl.description" class="tpl-desc" :title="tpl.description">{{ tpl.description }}</span>
            </div>
            <div class="tpl-ops">
              <button class="mb" :title="t('landing.tplDlTip')" @click="downloadLandingTpl(tpl)">{{ t('landing.tplDl') }}</button>
              <button v-if="!tpl.is_builtin" class="mb" @click="openTplRename(tpl)">{{ t('common.rename') }}</button>
              <button v-if="!tpl.is_builtin" class="mb danger" @click="delLandingTpl(tpl)">{{ t('common.delete') }}</button>
            </div>
          </template>
          <template v-else>
            <div class="tpl-rename">
              <input v-model="tplRenameForm.name" class="input" :placeholder="t('landing.fTplNamePh')" />
              <input v-model="tplRenameForm.description" class="input" :placeholder="t('landing.fTplDescPh')" />
              <div class="tpl-rename-ops">
                <button class="btn" @click="tplRenameId = null">{{ t('common.cancel') }}</button>
                <button class="btn primary" :disabled="tplRenameSaving" @click="saveTplRename">{{ tplRenameSaving ? t('common.saving') : t('common.save') }}</button>
              </div>
            </div>
          </template>
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
/* 异常卡片整体标红/标黄（FB屏蔽>待复查 置顶，左侧色条一眼可见） */
.lp-card.alert-fail{border-color:rgba(255,69,58,.6);box-shadow:inset 3px 0 0 var(--error)}
.lp-card.alert-warn{border-color:rgba(255,159,10,.55);box-shadow:inset 3px 0 0 var(--warning)}
.lp-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.lp-title{font-size:14px;font-weight:600;color:var(--t1)}
.tag{font-size:10px;padding:1px 7px;border-radius:9px;background:var(--bg3);color:var(--t3)}
.tag.fb-block{background:var(--error);color:#fff;font-weight:600}
.tag.fb-warn{background:var(--warning);color:#fff;font-weight:600}
.st-tag{font-size:10px;padding:2px 8px;border-radius:9px;display:inline-flex;align-items:center;justify-content:center;line-height:1.2;white-space:nowrap}
.st-tag.ok{background:rgba(48,209,88,.15);color:var(--success)}
.st-tag.off{background:var(--bg3);color:var(--t3)}
.st-tag.warn{background:rgba(255,159,10,.15);color:var(--warning)}
.lp-body{font-size:12px;color:var(--t3);margin-top:6px}
.lp-foot{display:flex;gap:6px;margin-top:8px;padding-top:8px;border-top:1px solid var(--bd)}
.lp-dom-chips{display:none}   /* 旧域名按钮堆已废弃（重设计为 .lp-dom 文本属性）——占位防残留引用 */
.lp-sub-row{display:flex;align-items:center;gap:4px;margin-bottom:2px}
.lp-sub-more{font-size:11px;color:var(--ac);cursor:pointer;padding:2px 0}
.lp-sub-more:hover{text-decoration:underline}
.mb{padding:3px 10px;border:1px solid var(--bd);background:transparent;color:var(--t2);border-radius:4px;font-size:11px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;line-height:1.3;white-space:nowrap}
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
.empty{text-align:center;color:var(--t3);padding:32px;font-size:13px;background:var(--bg2);border:1px dashed var(--bd);border-radius:8px;display:flex;flex-direction:column;align-items:center;gap:14px}
.empty-cta-btn{margin-top:2px}
.form-l{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.form-l > label{font-size:12px;color:var(--t3);width:84px;text-align:right;flex-shrink:0}
.opt-hint{font-size:10px;color:var(--t3);opacity:.7;font-weight:400}
.input{flex:1;padding:7px 10px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:13px;font-family:inherit;box-sizing:border-box}
.input:focus{border-color:var(--ac);outline:none}
.sec-title{font-size:12px;color:var(--ac);margin:18px 0 10px;font-weight:600}
.tpl-desc{font-size:11px;color:var(--t3);margin:-4px 0 10px 92px;line-height:1.5}
.mode-hint{font-size:11px;color:var(--t3);margin:-6px 0 12px 92px;line-height:1.5}
/* 双模式卡片选择器（落地页/短链 完全分离的入口） */
.mode-picker{display:flex;gap:10px;flex:1}
.mode-card{flex:1;padding:10px 12px;border:1.5px solid var(--bd);border-radius:10px;cursor:pointer;transition:border-color .15s,background .15s}
.mode-card:hover{border-color:var(--ac)}
.mode-card.on{border-color:var(--ac);background:color-mix(in srgb, var(--ac) 7%, transparent)}
.mode-card-title{font-size:13px;font-weight:600;margin-bottom:3px}
.mode-card-desc{font-size:11px;color:var(--t3);line-height:1.4}
/* 列表卡模式徽标 */
.mode-chip{flex:none;font-size:11px;font-weight:600;padding:2px 8px;border-radius:6px}
.mode-chip.display{background:rgba(10,132,255,.12);color:var(--ac)}
.mode-chip.redirect{background:rgba(52,199,89,.14);color:var(--success)   /* UI审计#10b */}
/* 卡片统计数字块（替代原灰色 prose） */
.lp-stats{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.stat-num b{font-size:16px;font-variant-numeric:tabular-nums;margin-right:4px}
.stat-num span{font-size:11px;color:var(--t3)}
.stat-num.warn b,.stat-num.warn span{color:var(--warning)}
/* 2026-09-14：主数=北京业务日今日，副行=7天/累计 */
.stat-num .st-main{display:flex;align-items:baseline;gap:4px}
.stat-num .st-sub{font-style:normal;font-size:10px;color:var(--ac);margin-left:2px}
.stat-num .st-more{display:block;font-style:normal;font-size:10px;color:var(--t3);margin-top:2px;font-variant-numeric:tabular-nums}
.seg-cnt{font-style:normal;margin-left:2px;font-size:10px;opacity:.75}
/* 页面规范文档（模板抽屉） */
.spec-sec{margin-bottom:12px}
.spec-t{font-size:12px;font-weight:700;color:var(--t1);margin-bottom:4px}
.spec-ln{font-size:12px;color:var(--t2);line-height:1.7}
.spec-table{width:100%;border-collapse:collapse;margin:6px 0}
.spec-table td{border:1px solid var(--bd);padding:4px 8px;font-size:11px;vertical-align:top}
.spec-table code{color:var(--ac);font-family:var(--font-mono)}
.spec-req .tag.ok{color:var(--success);background:rgba(52,199,89,.13)}
.spec-code-wrap{position:relative;margin:6px 0}
.spec-code{background:var(--bg3);border:1px solid var(--bd);border-radius:6px;padding:10px;font-size:11px;line-height:1.6;overflow-x:auto;font-family:var(--font-mono);margin:0}
.spec-code-wrap .mb{position:absolute;top:6px;right:6px}
/* 页卡 hover（对齐全局 card-base 手感） */
.lp-card{transition:border-color .15s,box-shadow .15s,transform .15s}
.lp-card:hover{border-color:var(--bd2);box-shadow:var(--shadow-card);transform:translateY(-1px)}
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
/* 像素库平台标识统一用 main.css 全局 .plat-chip */
.tag.ok{color:var(--success);background:rgba(52,199,89,.13)}
.tag.warn{color:var(--warning);background:rgba(255,159,10,.13)}
/* 品牌标识 */
.brand-fb{display:inline-flex;align-items:center;gap:5px;font-weight:600;font-size:13px;color:#1877f2}
.brand-fb::before{content:"f";display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:4px;background:#1877f2;color:#fff;font-size:11px;font-weight:700;font-family:Arial,sans-serif}
.brand-tt{display:inline-flex;align-items:center;gap:5px;font-weight:600;font-size:13px;color:#fe2c55}
.brand-tt::before{content:"♪";display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:4px;background:#000;color:#fff;font-size:12px;font-weight:700}
/* 子码复制链接按钮 */
.btn-link{border:1px solid var(--bd);background:var(--bg2);padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;cursor:pointer;text-decoration:none;white-space:nowrap;transition:opacity .15s}
.btn-link:hover{opacity:.8}
.btn-link.fb{color:#1877f2;border-color:rgba(24,119,242,.3)}
.btn-link.tt{color:#fe2c55;border-color:rgba(254,44,85,.3)}
.btn-link.preview{color:var(--t3);border-color:var(--bd)}
/* 编辑器分区 */
.lp-section{border:1px solid var(--bd);border-radius:10px;margin-bottom:14px;overflow:hidden}
.lp-section-title{padding:8px 14px;font-size:13px;font-weight:600;background:var(--bg3);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:6px}
.lp-section-body{padding:12px 14px}
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
.sub-row{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--bd);font-size:12px;flex-wrap:wrap;row-gap:4px}
/* 模板管理行（2026-09-12 重构：信息/操作两栏 + 行内改名） */
.tpl-row{justify-content:space-between;align-items:center}
.tpl-info{display:flex;align-items:center;gap:6px;min-width:0;flex-wrap:wrap}
.tpl-info code{font-size:12px;color:var(--t1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:200px}
.tpl-desc{font-size:11px;color:var(--t3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:160px}
.tpl-ops{display:flex;gap:4px;flex-shrink:0}
.tpl-ops .mb{border:1px solid var(--bd);border-radius:4px;padding:2px 8px;font-size:11px;background:var(--bg2);color:var(--t2);cursor:pointer}
.tpl-ops .mb:hover{color:var(--t1);border-color:var(--bd2)}
.tpl-ops .mb.danger{color:var(--error);border-color:var(--error)}
.tpl-rename{display:flex;flex-direction:column;gap:6px;flex:1;min-width:0;padding:4px 0}
.tpl-rename-ops{display:flex;gap:8px;justify-content:flex-end}
.sub-item{padding:4px 0;border-bottom:1px solid var(--bd)}
.sub-target{display:flex;gap:6px;align-items:center;padding:6px 0}
.sub-target-input{flex:1}
.sub-target-show{font-size:11px;color:var(--ac);padding:4px 0;cursor:pointer}
.edit-hint{color:var(--t3);font-size:10px;margin-left:4px}
.sub-target-add{font-size:11px;color:var(--t3);padding:4px 0;cursor:pointer}
.sub-target-add:hover{color:var(--ac)}
.sub-slug{color:var(--ac);font-family:'SF Mono',monospace;white-space:nowrap}
.sub-ad{color:var(--t3);font-family:'SF Mono',monospace;font-size:11px;white-space:nowrap}
.sub-pass{color:var(--success);font-size:11px;font-weight:600;white-space:nowrap}
.fb-badge{font-size:10px;font-weight:500;padding:2px 6px;border-radius:4px;white-space:nowrap}
.fb-badge.pass{color:var(--success);background:rgba(52,199,89,.1)}
.fb-badge.fail{color:var(--error);background:rgba(255,69,58,.1)}
.fb-badge.warn{color:var(--warning);background:rgba(255,159,10,.1)}
.sub-ops{display:flex;gap:5px;align-items:center;margin-left:auto;flex-shrink:0;flex-wrap:wrap;row-gap:4px}
.mb.spin{opacity:.5;pointer-events:none}

.lp-sec-label{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--t2);margin:6px 0 8px}
.lp-sec-label i{font-style:normal;font-size:10px;color:var(--t3);background:var(--bg3);border-radius:9px;padding:1px 8px}
.list + .lp-sec-label{margin-top:16px}
/* 短链行式（批2） */
.short-list{display:flex;flex-direction:column;gap:8px;margin-bottom:10px}
.short-row{display:grid;grid-template-columns:70px minmax(110px,1fr) auto minmax(160px,1.5fr) 80px repeat(3,minmax(80px,.7fr)) auto;gap:10px;align-items:center;background:var(--bg2);border:1px solid var(--bd);border-radius:8px;padding:10px 14px;font-size:12px;transition:border-color .15s,box-shadow .15s}
.short-row:hover{border-color:var(--bd2);box-shadow:var(--shadow-card)}
.short-row.alert-fail{box-shadow:inset 3px 0 0 var(--error)}
.short-title{font-weight:600;color:var(--t1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.short-url{color:var(--ac);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}
.short-url i{font-style:normal;color:var(--t3);margin-left:3px}
.short-rot{color:var(--t3);font-size:11px;white-space:nowrap}
.short-stat{font-variant-numeric:tabular-nums;color:var(--t1);font-size:13px;white-space:nowrap}
.short-stat i{font-style:normal;font-size:10px;color:var(--t3);margin-left:3px}
/* 表格式行（2026-09-16 重设计）：表头+行同 grid 模板 → 跨行严格对齐；域名=文本属性（主域+N）；
   名称列内联 owner chip；操作收敛 2 常驻 + ⋯ 菜单 */
.lp-thead,.lp-row2{grid-template-columns:64px minmax(200px,1fr) minmax(150px,210px) 56px 78px 78px 78px 60px auto;gap:10px;align-items:center}
.lp-thead{display:grid;padding:4px 14px;font-size:11px;font-weight:600;color:var(--t3);border-bottom:1px solid var(--bd);margin-bottom:6px}
.lp-name{display:flex;align-items:center;gap:8px;min-width:0}
.lp-dom{font-size:12px;color:var(--ac);font-family:var(--font-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;min-width:0}
.lp-dom:hover{text-decoration:underline}
.lp-dom i{font-style:normal;color:var(--t3);margin-left:3px}
.lp-dom.muted{color:var(--t3);cursor:default}
.lp-subcount{font-variant-numeric:tabular-nums;color:var(--t1);font-size:13px;text-align:right;cursor:default}
.lp-fb-empty{display:inline-block;width:1px}
.owner-cell{min-width:0;overflow:hidden}   /* 恒渲染占位（复审P2：无 owner_email 的行 9 列只填 8 列，操作键不齐右）；固定列宽保各行对齐 */
.owner-chip{font-size: 11px; color: var(--t3); background: none; padding: 0; border-radius: 0; white-space: nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis;display:inline-flex;align-items:center;line-height:1.2}
.owner-chip.clickable{cursor:pointer;transition:all .15s}
.owner-chip.clickable:hover{color:var(--ac);background:var(--acg)}
.short-meta{font-size:11px;color:var(--t3);white-space:nowrap}
@media(max-width:900px){
  .lp-thead{display:none}
  .lp-row2{grid-template-columns:64px 1fr 56px auto;row-gap:6px}
  .lp-name{grid-column:2}
  .lp-dom{grid-column:1 / -1}
  .lp-fb-empty{display:none}
  .short-ops{flex-wrap:wrap;justify-content:flex-end}
}
.short-ops{display:flex;gap:5px}
.st-tag.err{background:rgba(255,69,58,.12);color:var(--error)}   /* subcodeStatus('deleted') 曾无样式渲染成裸文本 */


/* 域名管理表格（批2） */
.dm-table{margin-top:0}
.dm-row{display:grid;grid-template-columns:minmax(160px,1.6fr) 76px minmax(120px,1fr) 90px 90px auto;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid var(--bd);font-size:12px}
.dm-head-row{color:var(--t3);font-size:11px;font-weight:600}
.dm-row code{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dm-name{display:flex;align-items:center;gap:5px;min-width:0}
.dm-blocked{flex-shrink:0;cursor:help}
.dm-num{font-variant-numeric:tabular-nums;color:var(--t1);cursor:default}
/* 域名抽屉两段结构：区块标题 + 可导入 zone 行 + 导入操作条 */
.dm-sec-title{display:flex;align-items:center;font-size:12px;font-weight:600;color:var(--t1);margin:16px 0 8px}
.dm-sec-title:first-child{margin-top:0}
.dm-sec-title i{font-style:normal;font-size:10px;color:var(--t3);background:var(--bg3);border-radius:9px;padding:1px 8px;margin-left:4px}
.zone-list{display:flex;flex-direction:column;gap:6px;max-height:280px;overflow-y:auto}
.zone-row{display:grid;grid-template-columns:20px minmax(0,1fr) 88px;gap:8px;align-items:center;padding:7px 10px;background:var(--bg2);border:1px solid var(--bd);border-radius:6px;font-size:12px;cursor:pointer}
.zone-row:hover{border-color:var(--bd2)}
.zone-row.imported{opacity:.55;cursor:default}
.zone-row code{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.zone-import-bar{display:flex;align-items:center;justify-content:space-between;margin:10px 0 2px}
.zone-sel-hint{font-size:11px;color:var(--t3)}
.sub-ad i{font-style:normal;color:var(--t3)}
</style>
