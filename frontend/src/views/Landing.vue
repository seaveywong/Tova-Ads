<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import LandingLogs from './LandingLogs.vue'

const router = useRouter()
const route = useRoute()

// 落地页 内部 tab：管理 / 日志（日志归纳进来，不再是独立侧栏项）
const tab = ref(route.query.tab === 'logs' ? 'logs' : 'manage')
watch(() => route.query.tab, (t) => { if (t === 'logs' || t === 'manage') tab.value = t })

// ── 落地页列表 ──
const pages = ref([])
const loading = ref(true)
const loadPages = async () => {
  loading.value = true
  try { pages.value = await GET('/landing/pages') }
  catch (e) { ElMessage.error(e.message || '加载失败') }
  finally { loading.value = false }
}

// ── 资产库（发布抽屉选项）──
const pixels = ref([])
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
  custom_domain: '', custom_domains: [], pixel_ids: [], conversion_events: [],
  redirect_mode: 'display', block_enabled: false, preview_enabled: false, preview_url: '',
  subdomain_prefix: '', dedup_enabled: false, dedup_window_hours: 24,
  protection_rules: {}, block_target: '', block_html: '', template_key: '', template_id: null,
})
const form = ref(emptyForm())
const tplDesc = computed(() => {
  const t = templates.value.find(x => x.key === form.value.template_key)
  return t?.desc || ''
})
const convEventOptions = [
  { v: 'Purchase', l: '购买 (Purchase)' },
  { v: 'Contact', l: '联系 (Contact)' },
  { v: 'Lead', l: '潜在客户 (Lead)' },
  { v: 'AddToCart', l: '加入购物车 (AddToCart)' },
  { v: 'ViewContent', l: '查看内容 (ViewContent)' },
  { v: 'InitiateCheckout', l: '开始结账 (InitiateCheckout)' },
  { v: 'Subscribe', l: '订阅 (Subscribe)' },
  { v: 'CompleteRegistration', l: '完成注册 (CompleteRegistration)' },
]
const rotationOptions = [
  { v: 'first', l: '首个（first）' },
  { v: 'random', l: '随机（random）' },
  { v: 'sequential', l: '轮询（sequential）' },
]
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
      pixel_ids: detail.pixel_ids || [], conversion_events: detail.conversion_events || [],
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
  } catch (e) { ElMessage.error(e.message || '加载失败') }
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
  { key: 'bots', label: '屏蔽常见爬虫', rules: { ua_block: ['bot','crawler','spider','googlebot','bingbot','slurp','duckduckbot','baiduspider','yandexbot','facebookexternalhit','preview','debug'] } },
  { key: 'datacenter', label: '屏蔽机房/VPN', rules: { datacenter_block: datacenterAsns.value.map(d => d.asn) } },
  { key: 'us_only', label: '仅美国', rules: { country_allow: ['US'] } },
  { key: 'block_desktop', label: '屏蔽桌面', rules: { device_block: ['desktop'] } },
  { key: 'block_tablet', label: '屏蔽平板', rules: { device_block: ['tablet'] } },
  { key: 'block_preview', label: '拒预览/调试', rules: { referer_block: ['preview','debug'], query_block: ['preview','debug'] } },
  { key: 'require_ad', label: '必带广告参数', rules: { required_query: ['ad'] } },
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
  if (r.ua_block?.length) parts.push(`爬虫${r.ua_block.length}词`)
  if (r.datacenter_block?.length) parts.push(`机房/VPN ${r.datacenter_block.length}段`)
  if (r.country_allow?.length) parts.push(`仅${r.country_allow.join('/')}`)
  if (r.country_block?.length) parts.push(`拒${r.country_block.join('/')}`)
  if (r.device_block?.length) parts.push(`拒${r.device_block.join('/')}`)
  if (r.source_block?.length) parts.push(`拒来源${r.source_block.join('/')}`)
  if (r.referer_block?.length) parts.push(`拒referer`)
  if (r.query_block?.length) parts.push(`拒query`)
  if (r.required_query?.length) parts.push(`必带${r.required_query.join(',')}`)
  return parts.length ? parts.join(' · ') : ''
})
const ruleVal = (k) => form.value.protection_rules[k] || []
const setRule = (k, v) => {
  const r = { ...form.value.protection_rules }
  if (v && v.length) r[k] = v; else delete r[k]
  form.value.protection_rules = r
}

const save = async () => {
  if (!form.value.title.trim()) return ElMessage.warning('填标题')
  if (!form.value.custom_domains.length) return ElMessage.warning('请选择根域名（自动生成子域名，不能用根域名直接投放）')
  if (form.value.redirect_mode === 'redirect' && !form.value.target_urls.length) {
    return ElMessage.warning('填跳转地址')
  }
  if (form.value.redirect_mode === 'display' && !form.value.target_urls.length) {
    return ElMessage.warning('填至少一个目标 URL')
  }
  if (form.value.block_enabled && !form.value.block_target && !form.value.block_html) {
    return ElMessage.warning('防护已开启，必须配置屏蔽跳转链接或屏蔽页 HTML')
  }
  saving.value = true
  const rules = { ...form.value.protection_rules }
  if (form.value.block_target) rules.block_target = form.value.block_target
  if (form.value.block_html) rules.block_html = form.value.block_html
  const body = {
    title: form.value.title.trim(), description: form.value.description,
    target_urls: form.value.target_urls, rotation_mode: form.value.rotation_mode,
    custom_domains: form.value.custom_domains, pixel_ids: form.value.pixel_ids,
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
      ElMessage.success('已更新')
    } else {
      resp = await POST('/landing/publish', body)
      ElMessage.success('已发布')
    }
    drawerOpen.value = false
    await loadPages()
    if (resp && resp.self_check) showSelfCheck(resp.self_check, '发布后自检')
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
  saving.value = false
}

const archive = async (p) => {
  try {
    await ElMessageBox.confirm(`归档「${p.title}」？归档后不再显示，已发布页面保留。`, '确认', { type: 'warning' })
    await DELETE(`/landing/pages/${p.id}`); ElMessage.success('已归档'); await loadPages()
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
  const overallTxt = r.overall === 'pass' ? '✅ 全部通过' : (r.overall === 'fail' ? '❌ 有致命项（需处理）' : '⚠️ 有警告（可忽略若是配置选择）')
  const note = title === '发布后自检' ? '<div style="font-size:11px;color:var(--t3);margin-bottom:8px">发布后即时自检（域名/Worker/FB 用「自检」按钮完整重检）</div>' : ''
  ElMessageBox.alert(note + (lines || '无检查项'), `${title} · ${overallTxt}`, { dangerouslyUseHTMLString: true, confirmButtonText: '知道了', customClass: 'sc-alert' })
}
const checkHealth = async (p) => {
  healthCheckingId.value = p.id
  try {
    const r = await GET(`/landing/pages/${p.id}/health`)
    healthResult.value = r
    await loadPages()
    showSelfCheck(r, '自检')
  } catch (e) { ElMessage.error('自检失败：' + (e.message || '')) }
  healthCheckingId.value = null
}
const protTestResult = ref(null)
const protTesting = ref(false)
const runProtTest = async () => {
  protTesting.value = true
  try {
    const r = await POST('/landing/protection-test', { rules: form.value.protection_rules })
    protTestResult.value = r
  } catch (e) { ElMessage.error('测试失败：' + (e.message || '')) }
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
  catch (e) { ElMessage.error(e.message || '加载失败') }
  finally { subLoading.value = false }
}
const setSubStatus = (s) => { subStatus.value = s; loadSubcodes(subPage.value.id) }
const onSubSearch = () => loadSubcodes(subPage.value.id)
const archiveSub = async (s) => {
  try { await ElMessageBox.confirm(`归档子码 /a/${s.slug}？回收站可恢复。`, '确认归档', { type: 'warning' })
    await DELETE(`/subcodes/${s.id}`); ElMessage.success('已归档'); await loadSubcodes(subPage.value.id)
  } catch(e) {}
}
const restoreSub = async (s) => {
  try { await POST(`/subcodes/${s.id}/restore`); ElMessage.success('已恢复'); await loadSubcodes(subPage.value.id) }
  catch (e) { ElMessage.error('恢复失败：' + (e.message || '')) }
}
const hardDeleteSub = async (s) => {
  try { await ElMessageBox.confirm(`永久删除 /a/${s.slug}？将清空其配置（恢复后回退页级跳转）。`, '永久删除', { type: 'warning', confirmButtonText: '永久删除', confirmButtonClass: 'el-button--danger' })
    await DELETE(`/subcodes/${s.id}?hard=1`); ElMessage.success('已永久删除（回收站仍可恢复）'); await loadSubcodes(subPage.value.id)
  } catch(e) {}
}
const genSubcode = async () => {
  // act_id 可选（多账户页才填；空走页级像素）。autobind 绑广告时会自动回填真实账户。
  const count = Math.min(Math.max(Number(newSubCount.value) || 1, 1), 50)
  try {
    for (let i = 0; i < count; i++) {
      await POST('/subcodes/generate', { page_id: subPage.value.id })
    }
    ElMessage.success(`已生成 ${count} 条`); newSubCount.value = 1; await loadSubcodes(subPage.value.id)
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
}
const subTargetEdit = ref({})
const startEditTarget = (s) => { subTargetEdit.value = { [s.id]: s.target_urls || '' } }
const saveSubTarget = async (s) => {
  try {
    await PUT(`/subcodes/${s.id}`, { target_urls: subTargetEdit.value[s.id] || '' })
    ElMessage.success('已设置专属跳转'); delete subTargetEdit.value[s.id]; await loadSubcodes(subPage.value.id)
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
}
const copyUrl = (slug) => {
  // custom_domain = 该页绑定的子域名公开地址（如 gocal75.marketbriefnow.xyz）；
  // custom_domains = 根域名列表（仅兜底）。优先用子域名，避免投放到根域。
  const base = (subPage.value?.custom_domain || subPage.value?.custom_domains?.[0] || '').replace(/^https?:\/\//, '')
  if (!base) { ElMessage.warning('该落地页未绑定域名，请先绑定域名'); return }
  const url = `https://${base}/a/${slug}?ad={{ad.id}}`
  navigator.clipboard?.writeText(url)
  // 引导：说明 {{ad.id}} 占位符——FB 广告层级 URL 参数会自动替换成实际广告 ID，用于子码自动绑定
  ElMessage({
    message: `已复制：<code>${_esc(url)}</code><br><span style="opacity:.75;font-size:11px">投放时在广告「URL 参数」里填这个链接，FB 会把 <code>{{ad.id}}</code> 自动换成实际广告 ID（用于子码自动绑定/通过量统计）</span>`,
    dangerouslyUseHTMLString: true, type: 'success', duration: 6000,
  })
}
const subEvents = ref([])
const subEventsOpen = ref(false)
const subEventsLoading = ref(false)
const openSubEvents = async (s) => {
  subEventsOpen.value = true; subEventsLoading.value = true
  try { subEvents.value = await GET(`/subcodes/${subPage.value.id}/events?slug=${s.slug}&limit=200`) }
  catch (e) { ElMessage.error('加载失败') }
  subEventsLoading.value = false
}
// 联动：子码 → 落地页日志 tab（预筛该子码 + 所属页）
const goSubLogs = (s) => {
  subOpen.value = false
  tab.value = 'logs'
  router.replace({ name: 'landing', query: { tab: 'logs', slug: s.slug, page_id: subPage.value ? subPage.value.id : '' } })
}
const setTab = (t) => {
  tab.value = t
  router.replace({ name: 'landing', query: t === 'manage' ? {} : { tab: 'logs' } })
}
const copyText = (t, msg) => { navigator.clipboard?.writeText(t); ElMessage.success(msg || '已复制') }
const randomPrefix = () => 'go' + Math.random().toString(36).slice(2, 7)
const rootOf = (d) => { const h = (d || '').replace(/^https?:\/\//, '').split('/')[0]; const p = h.split('.'); return p.length >= 2 ? p.slice(-2).join('.') : h }
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
const pixelForm = ref({ id: null, pixel_id: '', pixel_name: '', note: '' })
const pixelSaving = ref(false)
const syncing = ref(false)
const openPixels = () => { pixelOpen.value = true; pixelForm.value = { id: null, pixel_id: '', pixel_name: '', note: '' } }
const syncPixels = async () => {
  syncing.value = true
  try { const r = await POST('/landing-lib/pixels/sync', {}); ElMessage.success(`同步新增 ${r.added || 0} 个`); await loadLib() }
  catch (e) { ElMessage.error('同步失败：' + (e.message || '')) }
  syncing.value = false
}
const editPixel = (p) => { pixelForm.value = { id: p.id, pixel_id: p.pixel_id, pixel_name: p.pixel_name || '', note: p.note || '' } }
const delPixel = async (p) => {
  try { await ElMessageBox.confirm(`删除像素 ${p.pixel_id}？`, '确认', { type: 'warning' }); await DELETE(`/landing-lib/pixels/${p.id}`); ElMessage.success('已删'); await loadLib() }
  catch {}
}
const savePixel = async () => {
  if (!pixelForm.value.pixel_id.trim()) return ElMessage.warning('填像素 ID')
  pixelSaving.value = true
  try {
    if (pixelForm.value.id) {
      await PUT(`/landing-lib/pixels/${pixelForm.value.id}`, { pixel_name: pixelForm.value.pixel_name, note: pixelForm.value.note })
      ElMessage.success('已更新')
    } else {
      await POST('/landing-lib/pixels', { pixel_id: pixelForm.value.pixel_id.trim(), pixel_name: pixelForm.value.pixel_name, note: pixelForm.value.note })
      ElMessage.success('已添加')
    }
    await loadLib()
    pixelForm.value = { id: null, pixel_id: '', pixel_name: '', note: '' }
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
  pixelSaving.value = false
}

// 域名管理（超管：从域名服务商导入）
const isSuper = ref(localStorage.getItem('tova_super') === '1')
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
  if (!tplForm.value.name.trim()) return ElMessage.warning('填模板名')
  if (!tplForm.value.file) return ElMessage.warning('选 zip 文件')
  tplUploading.value = true
  try {
    const fd = new FormData()
    fd.append('name', tplForm.value.name.trim()); fd.append('description', tplForm.value.description); fd.append('file', tplForm.value.file)
    const BASE = import.meta.env.VITE_API_BASE || 'https://api.tovaads.com'
    const r = await fetch(BASE + '/landing-lib/templates/upload', { method: 'POST', headers: { Authorization: 'Bearer ' + (localStorage.getItem('tova_token') || '') }, body: fd })
    if (r.status === 401) { localStorage.removeItem('tova_token'); location.hash = '#/login'; throw new Error('未登录，请重新登录') }
    const text = await r.text(); let data = {}; try { data = JSON.parse(text) } catch {}
    if (!r.ok) throw new Error(data.detail || '上传失败')
    ElMessage.success(`上传成功（${data.validation?.resources || 0} 资源）`)
    tplForm.value = { name: '', description: '', file: null }; if (tplFileInput.value) tplFileInput.value.value = ''; await loadLandingTemplates()
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
  tplUploading.value = false
}
const delLandingTpl = async (t) => {
  try { await ElMessageBox.confirm(`删除模板「${t.name}」？`, '确认', { type: 'warning' }); await DELETE(`/landing-lib/templates/${t.id}`); ElMessage.success('已删'); await loadLandingTemplates() } catch {}
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
  catch (e) { ElMessage.error(e.message || '加载失败') }
  finally { zonesLoading.value = false }
}
const importZones = async () => {
  const toImport = cfZones.value.filter(z => z._checked && !z.imported).map(z => z.name)
  if (!toImport.length) return ElMessage.warning('勾选要导入的域名')
  try {
    const r = await POST('/landing-lib/domains/import', { domains: toImport })
    ElMessage.success(`已导入 ${r.added} 个`); await loadLib(); await openDomains()
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
}
const delDomain = async (d) => {
  try { await DELETE(`/landing-lib/domains/${d.id}`); ElMessage.success('已删'); await loadLib(); await openDomains() }
  catch (e) { ElMessage.error('失败：' + (e.message || '')) }
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
      <div :class="['lp-tab', { on: tab === 'manage' }]" @click="setTab('manage')">落地页管理</div>
      <div :class="['lp-tab', { on: tab === 'logs' }]" @click="setTab('logs')">落地页日志</div>
    </div>
    <div v-show="tab === 'manage'">
    <div class="bar">
      <div class="bar-l">共 {{ pages.length }} 个落地页</div>
      <div class="bar-r">
        <button class="btn" @click="router.push('/dashboard')">查看数据</button>
        <button class="btn" @click="openPixels">像素库</button>
        <button v-if="isSuper" class="btn" @click="openDomains">域名管理</button>
        <button class="btn" @click="openLandingTemplates">模板</button>
        <button class="btn primary" @click="openCreate">+ 新建投放链接</button>
      </div>
    </div>

    <div class="list" v-loading="loading">
      <div v-for="p in pages" :key="p.id" class="lp-card">
        <div class="lp-head">
          <span class="st-tag" :class="p.status === 'published' ? 'ok' : 'off'">{{ p.status === 'published' ? '已发布' : (p.status === 'draft' ? '草稿' : p.status) }}</span>
          <span class="lp-title">{{ p.title }}</span>
          <span v-if="(p.custom_domains||[]).length" class="tag">{{ (p.custom_domains||[]).length }} 域名</span>
          <span class="tag">{{ (p.pixel_ids||[]).length }} 像素</span>
          <span class="health-dot" v-if="p.last_health_status" :class="p.last_health_status" :title="p.last_health_summary || ''"></span>
        </div>
        <div class="lp-body">
          {{ p.subcode_count }} 子码 · {{ p.visit_count||0 }} 访问 · {{ p.click_count||0 }} 转化
          <span v-if="p.last_health_status" class="health-text" :class="p.last_health_status">{{ p.last_health_summary }}</span>
        </div>
        <div class="lp-url" v-if="p.custom_domain">
          <span class="url-text" :title="p.custom_domain">🔗 {{ p.custom_domain }}</span>
          <button class="mb" @click="copyText(p.custom_domain, '公开链接已复制')">复制</button>
          <a class="mb" :href="p.custom_domain" target="_blank" rel="noopener">打开↗</a>
        </div>
        <div class="lp-foot">
          <a v-if="p.preview_url" class="mb" :href="p.preview_url" target="_blank" rel="noopener">预览</a>
          <button class="mb" @click="openSubcodes(p)">子码</button>
          <button class="mb" :disabled="healthCheckingId === p.id" @click="checkHealth(p)">{{ healthCheckingId === p.id ? '自检中…' : '自检' }}</button>
          <button class="mb" @click="openEdit(p)">编辑</button>
          <button class="mb danger" @click="archive(p)">归档</button>
        </div>
      </div>
      <div v-if="!pages.length && !loading" class="empty">暂无投放链接，点「+ 新建投放链接」创建。</div>
    </div>

    <el-drawer v-model="drawerOpen" :title="editingId ? '编辑投放链接' : '新建投放链接'" direction="rtl" size="580px" :destroy-on-close="true" :close-on-click-modal="false" v-loading="saving" :element-text="saving ? '正在部署到云端...' : ''">
      <div class="form-l"><label>标题</label><input v-model="form.title" class="input" placeholder="落地页标题" /></div>
      <div class="form-l"><label>访问模式</label>
        <el-radio-group v-model="form.redirect_mode">
          <el-radio value="display">落地页模式（展示页面内容）</el-radio>
          <el-radio value="redirect">跳转模式（直接跳转目标）</el-radio>
        </el-radio-group>
      </div>
      <div class="mode-hint" v-if="form.redirect_mode === 'display'">访客看到落地页内容，点击按钮再跳转目标地址</div>
      <div class="mode-hint" v-else>访客直接跳到目标地址，不展示落地页（适合第三方链接）</div>

      <div class="form-l"><label>{{ form.redirect_mode === 'redirect' ? '跳转地址' : '目标 URL' }}</label>
        <el-select v-model="form.target_urls" multiple filterable allow-create default-first-option
          :placeholder="form.redirect_mode === 'redirect' ? '填第三方链接（如 WhatsApp/Shopify）' : '可填多个（轮换），回车添加'" style="flex:1" />
      </div>
      <div class="form-l"><label>轮换模式</label>
        <select v-model="form.rotation_mode" class="input">
          <option v-for="o in rotationOptions" :key="o.v" :value="o.v">{{ o.l }}</option>
        </select>
      </div>
      <div class="form-l" v-if="form.custom_domain"><label>公开链接</label>
        <span class="url-text" style="flex:1">🔗 {{ form.custom_domain }}</span>
        <button class="mb" @click="copyText(form.custom_domain, '公开链接已复制')">复制</button>
      </div>
      <div class="form-l"><label>域名</label>
        <el-select v-model="form.custom_domains" multiple filterable allow-create default-first-option
          placeholder="可多选（一页绑多域），回车添加" style="flex:1">
          <el-option v-for="d in domains" :key="d.id" :value="d.domain" :label="d.domain + (d.label ? ' ('+d.label+')' : '')" />
        </el-select>
      </div>
      <div class="form-l"><label>子域名前缀</label>
        <input v-model="form.subdomain_prefix" class="input" placeholder="留空=自动 lp{编号}，或自定义（go/abc）" style="flex:1" />
        <button class="mb" type="button" @click="form.subdomain_prefix = randomPrefix()">🎲 随机</button>
      </div>
      <div class="pixel-hint" v-if="form.custom_domains.length">预览：{{ form.subdomain_prefix || 'lp{编号}' }}.{{ rootOf(form.custom_domains[0]) }}<span v-if="subdomainStatus==='ok'" style="color:var(--success)"> ✓ 可用</span><span v-else-if="subdomainStatus==='taken'" style="color:var(--error)"> ✗ 已被占用</span></div>

      <template v-if="form.redirect_mode === 'display'">
        <div class="form-l"><label>像素</label>
          <el-select v-model="form.pixel_ids" multiple filterable collapse-tags collapse-tags-tooltip
            placeholder="可选。不填则自动用子码所属账户的像素" style="flex:1">
            <el-option v-for="p in pixels" :key="p.id" :value="p.pixel_id"
              :label="p.pixel_name ? `${p.pixel_name} (${p.pixel_id})` : p.pixel_id" />
          </el-select>
        </div>
        <div class="pixel-hint">可选。不填则自动用子码所属账户的像素（推荐）。</div>
        <div class="form-l"><label>转化事件</label>
          <el-select v-model="form.conversion_events" multiple filterable allow-create default-first-option
            placeholder="CTA 点击时触发（可多选），留空=只 PageView" style="flex:1">
            <el-option v-for="o in convEventOptions" :key="o.v" :value="o.v" :label="o.l" />
          </el-select>
        </div>
        <div class="form-l"><label>落地页模板</label>
          <select v-model="form.template_id" class="input">
            <option :value="null">默认模板</option>
            <option v-for="t in landingTemplates" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </div>
      </template>

      <div class="sec-title">防重复访客 <el-switch v-model="form.dedup_enabled" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" style="margin-left:8px" /></div>
      <template v-if="form.dedup_enabled">
        <div class="form-l"><label>时间窗（小时）</label>
          <input v-model.number="form.dedup_window_hours" type="number" min="1" class="input" style="flex:1" />
        </div>
      </template>
      <div class="sec-title">防护规则 <el-switch v-model="form.block_enabled" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" style="margin-left:8px" /></div>
      <div class="form-l" v-if="form.block_enabled"><label>预览模式</label>
        <el-switch v-model="form.preview_enabled" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" />
        <span class="hint" style="margin-left:8px">开启后用预览链接跳过防护看真实页（关闭即失效）</span>
      </div>
      <div class="lp-url" v-if="form.preview_enabled && form.preview_url">
        <span class="url-text" :title="form.preview_url">👁 {{ form.preview_url }}</span>
        <button class="mb" @click="copyText(form.preview_url, '预览链接已复制')">复制预览链接</button>
        <a class="mb" :href="form.preview_url" target="_blank" rel="noopener">打开↗</a>
      </div>
      <template v-if="form.block_enabled">
        <div class="guard-grid">
          <button v-for="g in QUICK_GUARDS" :key="g.key"
            class="guard-btn" :class="{ on: guardActive(g) }"
            @click="toggleGuard(g)">{{ g.label }}</button>
        </div>
        <div v-if="guardSummary" class="guard-summary">当前生效：{{ guardSummary }}</div>
        <div class="prot-test">
          <button class="btn sm" :disabled="protTesting" @click="runProtTest">{{ protTesting ? '测试中...' : '防护模拟测试' }}</button>
          <span v-if="protTestResult" class="prot-test-summary">
            拦截 {{ protTestResult.blocked_count }} / 放行 {{ protTestResult.pass_count }}
          </span>
        </div>
        <div v-if="protTestResult" class="prot-test-result">
          <div v-for="(r, i) in protTestResult.profiles" :key="i" class="prot-profile">
            <span class="prot-label">{{ r.label }}</span>
            <span class="st-tag" :class="r.blocked ? 'warn' : 'ok'">{{ r.blocked ? '✗ 拦截' : '✓ 放行' }}</span>
            <span v-if="r.reason" class="prot-reason">{{ r.reason }}</span>
          </div>
        </div>
        <div class="adv-toggle" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? '▲ 收起高级' : '▼ 高级自定义' }}
        </div>
        <div v-if="showAdvanced" class="rules-grid">
          <div class="rule-row"><label>国家白名单</label>
            <el-select :model-value="ruleVal('country_allow')" @update:model-value="v=>setRule('country_allow',v)" multiple filterable allow-create default-first-option placeholder="输入国家代码，回车添加" style="flex:1"><el-option v-for="c in COUNTRIES" :key="c" :value="c" :label="c" /></el-select>
          </div>
          <div class="rule-row"><label>国家黑名单</label>
            <el-select :model-value="ruleVal('country_block')" @update:model-value="v=>setRule('country_block',v)" multiple filterable allow-create default-first-option placeholder="输入国家代码，回车添加" style="flex:1"><el-option v-for="c in COUNTRIES" :key="c" :value="c" :label="c" /></el-select>
          </div>
          <div class="rule-row"><label>来源白名单</label>
            <el-select :model-value="ruleVal('source_allow')" @update:model-value="v=>setRule('source_allow',v)" multiple allow-create default-first-option placeholder="输入来源，回车添加" style="flex:1"><el-option v-for="s in SOURCES" :key="s" :value="s" :label="s" /></el-select>
          </div>
          <div class="rule-row"><label>来源黑名单</label>
            <el-select :model-value="ruleVal('source_block')" @update:model-value="v=>setRule('source_block',v)" multiple allow-create default-first-option placeholder="输入来源，回车添加" style="flex:1"><el-option v-for="s in SOURCES" :key="s" :value="s" :label="s" /></el-select>
          </div>
          <div class="rule-row"><label>设备黑名单</label>
            <el-select :model-value="ruleVal('device_block')" @update:model-value="v=>setRule('device_block',v)" multiple allow-create default-first-option placeholder="输入设备类型，回车添加" style="flex:1"><el-option v-for="d in DEVICES" :key="d" :value="d" :label="d" /></el-select>
          </div>
          <div class="rule-row"><label>平台黑名单</label>
            <el-select :model-value="ruleVal('platform_block')" @update:model-value="v=>setRule('platform_block',v)" multiple filterable allow-create default-first-option placeholder="输入平台/系统/浏览器，回车添加" style="flex:1"><el-option v-for="p in PLATFORMS" :key="p" :value="p" :label="p" /></el-select>
          </div>
          <div class="rule-row"><label>UA 关键词</label>
            <el-select :model-value="ruleVal('ua_block')" @update:model-value="v=>setRule('ua_block',v)" multiple filterable allow-create default-first-option placeholder="如 bot/crawler，回车添加" style="flex:1" />
          </div>
          <div class="rule-row"><label>机房/VPN（ASN）</label>
            <el-select :model-value="ruleVal('datacenter_block')" @update:model-value="v=>setRule('datacenter_block',v)" multiple filterable allow-create default-first-option placeholder="选主流机房或输 ASN 数字，回车添加" style="flex:1">
              <el-option v-for="d in datacenterAsns" :key="d.asn" :value="d.asn" :label="`${d.asn} · ${d.label}`" />
            </el-select>
          </div>
          <div class="rule-row"><label>Referer 词</label>
            <el-select :model-value="ruleVal('referer_block')" @update:model-value="v=>setRule('referer_block',v)" multiple filterable allow-create default-first-option placeholder="如 preview，回车添加" style="flex:1" />
          </div>
          <div class="rule-row"><label>Query 词</label>
            <el-select :model-value="ruleVal('query_block')" @update:model-value="v=>setRule('query_block',v)" multiple filterable allow-create default-first-option placeholder="回车添加" style="flex:1" />
          </div>
          <div class="rule-row"><label>必带参数</label>
            <el-select :model-value="ruleVal('required_query')" @update:model-value="v=>setRule('required_query',v)" multiple filterable allow-create default-first-option placeholder="如 ad，回车添加" style="flex:1" />
          </div>
        </div>
        <div class="sec-title">屏蔽后处理（必填一项）</div>
        <div class="form-l"><label>屏蔽跳转</label><input v-model="form.block_target" class="input" placeholder="被屏蔽的访客跳转到此 URL" /></div>
        <div class="form-l"><label>屏蔽页 HTML</label><textarea v-model="form.block_html" class="input" rows="2" placeholder="可选：被屏蔽时显示的自定义 HTML（与屏蔽跳转二选一）"></textarea></div>
      </template>
      <div v-else class="block-off-hint">防护已关闭，所有访客放行</div>

      <template #footer>
        <button class="btn" @click="drawerOpen=false">取消</button>
        <button class="btn primary" :disabled="saving" @click="save">{{ saving ? '部署中…' : (editingId ? '保存' : '发布') }}</button>
      </template>
    </el-drawer>

    <el-drawer v-model="subOpen" :title="`子码 · ${subPage?.title||''}`" direction="rtl" size="520px" :destroy-on-close="true" :close-on-click-modal="false">
      <div class="sub-gen">
        <span class="sub-gen-lab">生成</span>
        <input v-model.number="newSubCount" type="number" min="1" max="50" class="sub-gen-input" />
        <span class="sub-gen-lab">个子码</span>
        <button class="btn primary" style="margin-left:auto" @click="genSubcode">批量生成</button>
      </div>
      <div class="sub-tabs">
        <div class="sub-tab-row">
          <span :class="['sub-tab', { on: subStatus === 'all' }]" @click="setSubStatus('all')">全部 <i>{{ subCounts.all || 0 }}</i></span>
          <span :class="['sub-tab', { on: subStatus === 'unbound' }]" @click="setSubStatus('unbound')">未绑 <i>{{ subCounts.unbound || 0 }}</i></span>
          <span :class="['sub-tab', { on: subStatus === 'active' }]" @click="setSubStatus('active')">投放中 <i>{{ subCounts.active || 0 }}</i></span>
          <span :class="['sub-tab trash', { on: subStatus === 'trash' }]" @click="setSubStatus('trash')">回收站 <i>{{ (subCounts.archived || 0) + (subCounts.deleted || 0) }}</i></span>
        </div>
        <div class="sub-filter-row">
          <input v-model="subQ" class="input sub-search" placeholder="搜 slug / 广告ID" @keyup.enter="onSubSearch" />
          <select v-model="subSort" class="sub-sort" @change="onSubSearch">
            <option value="created">按创建</option>
            <option value="visits">按访问</option>
          </select>
        </div>
      </div>
      <div class="sub-list" v-loading="subLoading">
        <div v-for="s in subcodes" :key="s.id" class="sub-item">
          <div class="sub-row">
            <code class="sub-slug">/a/{{ s.slug }}</code>
            <span class="sub-ad">{{ s.ad_count > 0 ? (s.ad_count + ' 广告' + (s.act_count > 1 ? ' · ' + s.act_count + ' 账户' : '')) : '未绑广告' }}</span>
            <span class="sub-pass" v-if="s.click_count > 0">{{ s.click_count }} 通过</span>
            <span class="st-tag" :class="s.status==='active'?'ok':(s.status==='reserved'?'off':(s.status==='deleted'?'err':'warn'))">{{ s.status }}</span>
            <span class="sub-stat">{{ s.visit_count||0 }}访/{{ s.click_count||0 }}转</span>
            <template v-if="subStatus !== 'trash'">
              <button class="mb" style="margin-left:auto" @click="goSubLogs(s)">日志</button>
              <button class="mb" @click="router.push({ name: 'ad-manager', query: { act: s.act_id || '' } })">广告</button>
              <button class="mb" @click="copyUrl(s.slug)">复制</button>
              <button class="mb danger" @click="archiveSub(s)">归档</button>
            </template>
            <template v-else>
              <button class="mb" style="margin-left:auto" @click="restoreSub(s)">恢复</button>
              <button class="mb danger" @click="hardDeleteSub(s)">永久删除</button>
            </template>
          </div>
          <div class="sub-target" v-if="subTargetEdit[s.id] !== undefined">
            <input v-model="subTargetEdit[s.id]" class="input sub-target-input" placeholder="专属跳转 URL（留空=用落地页默认）" />
            <button class="mb" @click="saveSubTarget(s)">保存</button>
            <button class="mb" @click="delete subTargetEdit[s.id]">取消</button>
          </div>
          <div class="sub-target-show" v-else-if="s.target_urls" @click="startEditTarget(s)">
            专属跳转：{{ s.target_urls }} <span class="edit-hint">点击修改</span>
          </div>
          <div class="sub-target-add" v-else-if="subStatus !== 'trash'" @click="startEditTarget(s)">+ 设置专属跳转</div>
        </div>
        <div v-if="!subcodes.length && !subLoading" class="empty">{{ subStatus === 'trash' ? '回收站为空' : '暂无子码，填数量生成' }}</div>
      </div>
    </el-drawer>

    <el-dialog v-model="subEventsOpen" title="子码访问日志" width="640px">
      <div v-loading="subEventsLoading" class="sub-list">
        <div v-for="e in subEvents" :key="e.id" class="sub-row" style="flex-wrap:wrap;gap:6px">
          <span class="st-tag" :class="e.event_type==='visit'?'ok':(e.event_type==='block'?'warn':'off')">{{ e.event_type }}</span>
          <span>{{ e.country }} {{ e.city }}</span>
          <span style="color:var(--t3);font-size:11px">{{ e.created_at }}</span>
          <span v-if="e.reason" style="color:var(--error);font-size:11px">{{ e.reason }}</span>
        </div>
        <div v-if="!subEvents.length && !subEventsLoading" class="empty">暂无日志</div>
      </div>
    </el-dialog>

    <el-drawer v-model="pixelOpen" title="像素库" direction="rtl" size="480px" :destroy-on-close="true" append-to-body>
      <button class="btn" :disabled="syncing" @click="syncPixels" style="margin-bottom:14px">{{ syncing ? '同步中...' : '从账户同步像素' }}</button>
      <div class="sec-title">{{ pixelForm.id ? '编辑像素' : '添加像素' }}</div>
      <div class="form-l"><label>像素 ID</label><input v-model="pixelForm.pixel_id" class="input" placeholder="FB 像素 ID" :disabled="!!pixelForm.id" /></div>
      <div class="form-l"><label>名称</label><input v-model="pixelForm.pixel_name" class="input" placeholder="备注名" /></div>
      <button class="btn primary" :disabled="pixelSaving" @click="savePixel">{{ pixelForm.id ? '保存' : '添加' }}</button>
      <div class="sec-title">像素列表</div>
      <div class="sub-list">
        <div v-for="p in pixels" :key="p.id" class="sub-row">
          <code>{{ p.pixel_id }}</code>
          <span v-if="p.act_id" class="tag">{{ String(p.act_id).slice(-6) }}</span>
          <span class="sub-ad">{{ p.pixel_name || '-' }}</span>
          <span class="tag">{{ p.usage_count }} 页</span>
          <button class="mb" style="margin-left:auto" @click="editPixel(p)">编辑</button>
          <button class="mb danger" @click="delPixel(p)">删除</button>
        </div>
        <div v-if="!pixels.length" class="empty">暂无像素，点上方同步或手动添加</div>
      </div>
    </el-drawer>

    <el-drawer v-if="isSuper" v-model="domainOpen" title="域名管理" direction="rtl" size="520px" :destroy-on-close="true" append-to-body>
      <div class="sec-title">可导入域名</div>
      <input v-model="zoneFilter" class="input" placeholder="搜索域名..." style="margin-bottom:8px;width:100%;box-sizing:border-box" />
      <div class="sub-list" v-loading="zonesLoading">
        <div v-for="z in filteredZones" :key="z.name" class="sub-row">
          <input type="checkbox" v-model="z._checked" :disabled="z.imported" style="margin-right:6px" />
          <code>{{ z.name }}</code>
          <span class="st-tag" :class="z.imported?'off':'ok'">{{ z.imported ? '已导入' : z.status }}</span>
        </div>
        <div v-if="!cfZones.length && !zonesLoading" class="empty">无可导入域名</div>
      </div>
      <button class="btn primary" style="margin-top:12px" @click="importZones">导入选中</button>
      <div class="sec-title">已导入域名</div>
      <div class="sub-list">
        <div v-for="d in domains" :key="d.id" class="sub-row">
          <code>{{ d.domain }}</code>
          <span class="sub-ad">{{ d.label || d.source }}</span>
          <button class="mb danger" @click="delDomain(d)">删除</button>
        </div>
        <div v-if="!domains.length" class="empty">尚未导入域名</div>
      </div>
    </el-drawer>

    <el-drawer v-model="tplOpen" title="落地页模板" direction="rtl" size="520px" :destroy-on-close="true" append-to-body>
      <button class="btn" @click="downloadTplRef" style="margin-bottom:14px">下载参考模板 zip</button>
      <div class="sec-title">上传新模板（zip）</div>
      <div class="form-l"><label>模板名</label><input v-model="tplForm.name" class="input" placeholder="如：简洁购买页" /></div>
      <div class="form-l"><label>说明</label><input v-model="tplForm.description" class="input" placeholder="可选" /></div>
      <div class="form-l"><label>zip 文件</label><input ref="tplFileInput" type="file" accept=".zip" @change="onTplFile" class="input" /></div>
      <button class="btn primary" :disabled="tplUploading" @click="uploadLandingTpl">{{ tplUploading ? '上传中...' : '上传并检测' }}</button>
      <div class="sec-title">已上传模板</div>
      <div class="sub-list">
        <div v-for="t in landingTemplates" :key="t.id" class="sub-row">
          <code>{{ t.name }}</code>
          <span v-if="t.has_resources" class="tag">多文件</span>
          <button class="mb danger" style="margin-left:auto" @click="delLandingTpl(t)">删除</button>
        </div>
        <div v-if="!landingTemplates.length" class="empty">暂无模板，下载参考改后上传</div>
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
</style>
