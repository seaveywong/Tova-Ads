<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { GET, POST } from '../api'
import { ElMessage } from 'element-plus'

const route = useRoute()

const EVENT_TYPES = [
  { v: '', l: '全部动作' }, { v: 'visit', l: '访问' }, { v: 'click', l: '点击' },
  { v: 'submit', l: '提交' }, { v: 'redirect', l: '跳转' }, { v: 'block', l: '拦截' },
  { v: 'pass', l: '放行' }, { v: 'error', l: '错误' },
]
const DECISIONS = [
  { v: '', l: '全部结果' }, { v: 'allow', l: '放行' },
  { v: 'block', l: '拦截' }, { v: 'redirect', l: '跳转' },
]

// 原因 → 中文
const REASON_LABEL = {
  pass: '通过', device_block: '设备拦截', ua_block: 'UA拦截',
  country_block: '国家拦截', country_allow: '地区未放行', dedup: '重复访客',
}
const reasonLabel = (r) => REASON_LABEL[r] || r || ''

// 国家码 → 中文（CF 给的是 2 字母 ISO 码）
const COUNTRY_ZH = {
  US: '美国', GB: '英国', CA: '加拿大', AU: '澳大利亚', NZ: '新西兰', IE: '爱尔兰',
  DE: '德国', FR: '法国', IT: '意大利', ES: '西班牙', PT: '葡萄牙', NL: '荷兰', BE: '比利时',
  CH: '瑞士', AT: '奥地利', SE: '瑞典', NO: '挪威', DK: '丹麦', FI: '芬兰', PL: '波兰',
  RO: '罗马尼亚', GR: '希腊', CZ: '捷克', HU: '匈牙利', BG: '保加利亚', RU: '俄罗斯', UA: '乌克兰',
  TR: '土耳其', IL: '以色列', AE: '阿联酋', SA: '沙特', QA: '卡塔尔', KW: '科威特', EG: '埃及',
  ZA: '南非', NG: '尼日利亚', KE: '肯尼亚', GH: '加纳', MA: '摩洛哥',
  BR: '巴西', MX: '墨西哥', AR: '阿根廷', CL: '智利', CO: '哥伦比亚', PE: '秘鲁', VE: '委内瑞拉',
  IN: '印度', PK: '巴基斯坦', BD: '孟加拉', LK: '斯里兰卡', NP: '尼泊尔',
  ID: '印尼', TH: '泰国', VN: '越南', PH: '菲律宾', MY: '马来西亚', SG: '新加坡', KH: '柬埔寨',
  MM: '缅甸', LA: '老挝', JP: '日本', KR: '韩国', CN: '中国', HK: '香港', TW: '台湾', MO: '澳门',
}
const countryLabel = (c) => {
  if (!c) return ''
  const zh = COUNTRY_ZH[String(c).toUpperCase()]
  return zh ? `${zh} ${c}` : c
}
// 设备类型 → 中文
const DEVICE_ZH = { desktop: '桌面', tablet: '平板', mobile: '手机' }
const PLATFORM_ZH = { android: 'Android', ios: 'iOS', windows: 'Win', mac: 'Mac', linux: 'Linux', chrome: 'ChromeOS' }
const deviceLabel = (e) => {
  const dev = DEVICE_ZH[e.device_type] || e.device_type || ''
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
  if (e.source_type === 'crawler') return d || '爬虫'
  if (e.source_type === 'controlled') return trim(`广告·受控 ${d} ${pf}`)
  if (e.source_type === 'external') return trim(`广告·外部 ${d} ${pf}`)
  if (e.source_type === 'placeholder') return trim(`占位符 ${pf}`)
  if (e.source_platform === 'facebook') return 'FB·无广告'  // 有 fbclid 无 ad_id
  if (e.referrer) return refLabel(e.referrer)
  return '直接访问'
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
  if (e.source_type === 'crawler') return trim(`${e.source_detail || '爬虫'} · ${e.asn_name || ''} AS${e.asn || '?'}`)
  if (e.source_type === 'controlled') return trim(`${pf} · 受控账户广告（ad_id ${e.ad_id} 在本系统）${e.source_detail ? '· ' + e.source_detail : ''}`)
  if (e.source_type === 'external') return trim(`${pf} · 外部账户（ad_id ${e.ad_id} 不在本系统，可能盗用）${e.source_detail ? '· ' + e.source_detail : ''}`)
  if (e.source_type === 'placeholder') return `${pf} · 占位符未替换（${e.ad_id}）`
  if (e.source_platform === 'facebook') return 'Facebook 点击但无广告参数（fbclid）'
  if (e.referrer) return '来源：' + e.referrer
  return '直接访问或来源未知'
}
// ASN 展示：名称优先，机房标红（机房=非真人可疑：爬虫/刷量/VPN）
const asnDisplay = (e) => e.asn_name || (e.asn ? 'AS' + e.asn : '-')
const asnTitle = (e) => {
  const t = { platform: '平台自有', datacenter: '机房/VPS（非真人，可疑：爬虫/刷量/VPN）', isp: '家宽ISP（真人）' }[e.asn_type] || '未收录'
  return trim(`${e.asn_name || '(未收录ASN)'} · AS${e.asn || '?'} · ${t}`)
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
const statChips = [
  { key: 'controlled', label: '受控', cls: 'src-ok' },
  { key: 'external', label: '外部', cls: 'src-bad' },
  { key: 'crawler', label: '爬虫', cls: 'src-bot' },
  { key: 'placeholder', label: '占位符', cls: 'src-warn' },
  { key: 'unknown', label: '直接', cls: 'muted' },
]
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
  } catch (e) { ElMessage.error(e.message || '加载失败') }
  loading.value = false
}
const search = () => { offset.value = 0; load() }
const reset = () => {
  fPage.value = ''; fAct.value = ''; fSlug.value = ''; fAd.value = ''; fEvent.value = ''; fDecision.value = ''; fSource.value = ''
  fFrom.value = ''; fTo.value = ''; fQ.value = ''; preset.value = ''; offset.value = 0; load()
}
// 日期快捷（按北京业务日，和后端查询基准对齐）
const preset = ref('')
const bjDate = (off = 0) => new Date(Date.now() + off * 86400000).toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' })
const setPreset = (k) => {
  if (k === 'today') { fFrom.value = bjDate(0); fTo.value = bjDate(0) }
  else if (k === 'yesterday') { fFrom.value = bjDate(-1); fTo.value = bjDate(-1) }
  else if (k === 'last2') { fFrom.value = bjDate(-1); fTo.value = bjDate(0) }
  preset.value = k; offset.value = 0; load()
}
const onDateManual = () => { preset.value = '' }  // 手动改日期 → 取消快捷高亮
const prev = () => { if (offset.value > 0) { offset.value = Math.max(0, offset.value - limit); load() } }
const next = () => { if (offset.value + limit < total.value) { offset.value += limit; load() } }

const fmtTime = (iso) => {
  if (!iso) return '-'
  try { return new Date(iso).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) }
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
    ElMessage.success(redirectInput.value.trim() ? '跳转链接已设' : '已恢复默认'); redirectDialog.value = false
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
}
const eventLabel = (v) => EVENT_TYPES.find(x => x.v === v)?.l || v || '-'
const decisionLabel = (v) => DECISIONS.find(x => x.v === v)?.l || v || ''
const decisionClass = (d, et) => d === 'block' || et === 'block' ? 'err' : (d === 'allow' || et === 'visit' ? 'ok' : 'warn')
const pageTitle = () => {
  const p = pages.value.find(x => String(x.id) === String(fPage.value))
  return p ? p.title : '全部落地页'
}

onMounted(async () => {
  if (route.query.slug) fSlug.value = route.query.slug
  if (route.query.page_id) fPage.value = String(route.query.page_id)
  await loadPages()
  await loadAccounts()
  await loadRedirectMap()
  await load()
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
      <h2 class="title">落地页日志 <span class="cnt">{{ total }}</span> <span v-if="fPage" class="pg-title">· {{ pageTitle() }}</span> <span v-if="fSlug" class="pg-slug">/a/{{ fSlug }}</span></h2>
      <button class="ctrl-btn sm" :class="{ on: preset === 'today' }" @click="setPreset('today')">今日</button>
      <button class="ctrl-btn sm" :class="{ on: preset === 'yesterday' }" @click="setPreset('yesterday')">昨日</button>
      <button class="ctrl-btn sm" :class="{ on: preset === 'last2' }" @click="setPreset('last2')">近2天</button>
      <input type="date" v-model="fFrom" class="date-input" @change="onDateManual" />
      <span class="sep">—</span>
      <input type="date" v-model="fTo" class="date-input" @change="onDateManual" />
      <select v-model="fPage" class="sel" @change="search">
        <option value="">全部落地页</option>
        <option v-for="p in pages" :key="p.id" :value="p.id">{{ p.title }}</option>
      </select>
      <select v-model="fAct" class="sel" @change="search">
        <option value="">全部账户</option>
        <option v-for="a in accounts" :key="a.act_id" :value="a.act_id">{{ a.name }}</option>
      </select>
      <select v-model="fEvent" class="sel" @change="search">
        <option v-for="o in EVENT_TYPES" :key="o.v" :value="o.v">{{ o.l }}</option>
      </select>
      <select v-model="fDecision" class="sel" @change="search">
        <option v-for="o in DECISIONS" :key="o.v" :value="o.v">{{ o.l }}</option>
      </select>
      <select v-model="fSource" class="sel" @change="search">
        <option value="">全部来源</option>
        <option value="controlled">广告·受控</option>
        <option value="external">广告·外部</option>
        <option value="crawler">爬虫</option>
        <option value="placeholder">占位符</option>
        <option value="unknown">直接访问</option>
      </select>
      <input v-model="fSlug" class="txt" placeholder="子码" @keyup.enter="search" />
      <input v-model="fAd" class="txt" placeholder="广告 ID" @keyup.enter="search" />
      <input v-model="fQ" class="txt q" placeholder="搜索 国家/城市/来源" @keyup.enter="search" />
      <button class="ctrl-btn primary" @click="search">查询</button>
      <button class="ctrl-btn" @click="reset">重置</button>
    </div>
    <div class="stats-bar" v-if="stats">
      <span class="stats-label">来源分布<span class="stats-win">{{ stats.window === 'today' ? '今日' : '所选范围' }} · {{ stats.total }}</span></span>
      <button v-for="c in statChips" :key="c.key" class="stat-chip" :class="[c.cls, { on: fSource === c.key }]" @click="toggleSource(c.key)">
        {{ c.label }} <b>{{ stats[c.key] || 0 }}</b>
      </button>
      <span v-if="stats.datacenter" class="stat-chip static src-bad" title="机房/VPS IP 来的访问（非真人：爬虫/刷量/VPN）">⚠ 机房 {{ stats.datacenter }}</span>
    </div>
    <div class="tbl" v-loading="loading">
      <div class="row head">
        <div>时间</div><div>子码</div><div>账户</div><div>广告</div><div>像素</div><div>设备</div><div>地区</div><div>ASN</div><div>动作</div><div>原因</div><div>来源 / 去向</div>
      </div>
      <div v-for="e in items" :key="e.id" class="row">
        <div class="t-time">{{ fmtTime(e.created_at) }}</div>
        <div><code class="slug" @click="goSlug(e.slug)" :title="'点击过滤子码 ' + e.slug">/a/{{ e.slug }}</code></div>
        <div class="t-act" :class="{ clk: e.act_id }" :title="e.act_id ? '点击过滤账户 ' + e.act_name : ''" @click="goAct(e.act_id)">{{ e.act_name || (e.act_id ? e.act_id.slice(-8) : '-') }}</div>
        <div class="t-ad" :title="(e.act_name || e.act_id || '') + (e.fbclid ? '\nFB点击ID: ' + e.fbclid : '')"><span class="ad-id" :class="{ clk: e.ad_id }" :title="e.ad_id ? '点击过滤广告 ' + e.ad_id : ''" @click="goAd(e.ad_id)">{{ e.ad_id || '-' }}</span><button v-if="e.ad_id" class="rd-link" :class="{on: redirectMap[e.ad_id]}" @click="openRedirect(e.ad_id)" :title="redirectMap[e.ad_id] ? '已设：' + redirectMap[e.ad_id] : '设跳转链接'">跳</button></div>
        <div class="t-px" :title="e.fired_pixel_ids ? '真实 fire 的像素：' + e.fired_pixel_ids : '未记录（worker 旧版 / redirect 模式 / 未 fire）——不推断'">
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
            <a v-if="e.target_url" :href="e.target_url" target="_blank" rel="noopener" :title="'跳转目标：' + e.target_url">{{ e.target_url }}</a>
            <span v-else class="muted">-</span>
          </template>
          <span v-else :class="srcClass(e)" :title="srcTitle(e)">{{ srcLabel(e) }}</span>
        </div>
      </div>
      <div v-if="!items.length && !loading" class="empty">暂无访问日志{{ fSlug ? '（子码 ' + fSlug + '）' : '' }}</div>
    </div>
    <div v-if="total > limit" class="pager">
      <button class="ctrl-btn sm" :disabled="offset === 0" @click="prev">上一页</button>
      <span class="pg-info">{{ offset + 1 }}–{{ Math.min(offset + limit, total) }} / 共 {{ total }}</span>
      <button class="ctrl-btn sm" :disabled="offset + limit >= total" @click="next">下一页</button>
    </div>

    <el-dialog v-model="redirectDialog" :title="`跳转链接 · 广告 ${redirectAd}`" width="440px" :close-on-click-modal="false" :destroy-on-close="true" append-to-body>
      <div style="display:flex;flex-direction:column;gap:8px">
        <label style="font-size:12px;color:var(--t3)">该广告的专属跳转链接（留空=用落地页默认）</label>
        <input v-model.trim="redirectInput" class="txt" style="width:100%" placeholder="https://..." />
        <div style="font-size:11px;color:var(--t3);line-height:1.5">设了之后这条广告的访客都跳这；其他广告不变。</div>
      </div>
      <template #footer>
        <button class="ctrl-btn" @click="redirectDialog = false">取消</button>
        <button v-if="redirectMap[redirectAd]" class="ctrl-btn" @click="redirectInput=''; saveRedirect()">恢复默认</button>
        <button class="ctrl-btn primary" @click="saveRedirect">保存</button>
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
