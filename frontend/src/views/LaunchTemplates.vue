<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { showError } from '../composables/useError'

const list = ref([])
const loading = ref(false)
const editOpen = ref(false)
const editing = ref(null)
const form = ref({})
const saving = ref(false)
const editLevel = ref('campaign')  // campaign / adset / ad
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
const OPT_GOALS = ['LINK_CLICKS','LANDING_PAGE_VIEWS','REACH','IMPRESSIONS','OFFSITE_CONVERSIONS','LEAD_GENERATION','PAGE_LIKES','POST_ENGAGEMENT','CONVERSATIONS','THRUPLAY','AP_INSTALLS','VALUE']
const BILLING_EVENTS = ['IMPRESSIONS','LINK_CLICKS','APP_INSTALLS','PAGE_LIKES','POST_ENGAGEMENT','THRUPLAY']
const DEST_TYPES = ['WEBSITE','ON_AD','ON_PAGE','MESSENGER','APP','WHATSAPP','INSTAGRAM_DIRECT']
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
const COUNTRIES = ['US','VN','TH','ID','PH','MY','TW','HK','SG','CN','BR','MX','IN','JP','KR','GB','DE','FR','AE','SA','EG','KW','QA','TR','ES','IT','CA','AU','NZ']
const LANGS = [
  { v: '', l: '不限' },{ v: 'en', l: '英语' },{ v: 'zh', l: '中文(简)' },{ v: 'zh-tw', l: '中文(繁)' },
  { v: 'vi', l: '越南语' },{ v: 'th', l: '泰语' },{ v: 'id', l: '印尼语' },{ v: 'ja', l: '日语' },
  { v: 'ko', l: '韩语' },{ v: 'es', l: '西语' },{ v: 'pt', l: '葡语' },{ v: 'ar', l: '阿语' },
]

const load = async () => {
  loading.value = true
  try { list.value = await GET('/launch-templates') } catch (e) { showError(e, '加载失败') }
  loading.value = false
}
const loadLandingPages = async () => { try { landingPages.value = await GET('/landing/pages') } catch {} }
onMounted(() => { load(); loadLandingPages() })
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })

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
})
const objLabel = (v) => OBJECTIVES.find(o => o.v === v)?.l || v
const fmtUsd = (v) => v != null ? '$' + Number(v).toFixed(2) : '—'

// 编辑
const openNew = () => { editing.value = null; form.value = blankForm(); editingAsset.value = null; editLevel.value = 'campaign'; editOpen.value = true }
const openEdit = async (t) => {
  editing.value = t
  const f = blankForm()
  Object.assign(f, t)
  // 解析 audience_json
  if (t.audience_json) { try { const a = JSON.parse(t.audience_json); f.audience_countries = a.countries||[]; f.audience_interests = a.interests||[]; f.audience_age_min = a.age_min||18; f.audience_age_max = a.age_max||65; f.audience_gender = a.gender||0; f.audience_language = a.languages||'' } catch {} }
  form.value = f
  editingAsset.value = null
  if (t.asset_id) { try { editingAsset.value = await GET('/assets/' + t.asset_id) } catch {} }
  editLevel.value = 'campaign'; editOpen.value = true
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
  if (!form.value.audience_interests.find(x => x.id === it.id)) form.value.audience_interests.push({ id: String(it.id), name: it.name })
}
const removeInterest = (i) => form.value.audience_interests.splice(i, 1)
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
  if (!form.value.name.trim()) return ElMessage.warning('填模板名')
  if (!form.value.asset_id) return ElMessage.warning('广告层级需选素材')
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
      beneficiary: form.value.beneficiary, payer: form.value.payer,
    }
    if (editing.value) { await PUT('/launch-templates/' + editing.value.id, body); ElMessage.success('已保存') }
    else { await POST('/launch-templates', body); ElMessage.success('已创建') }
    editOpen.value = false; await load()
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
    const summary = `币种:${r.currency} 预算:$${r.budget_usd}→${r.daily_budget_fb}(本币最小单位)\n目标:${r.objective} 优化:${r.optimization_goal} 计费:${r.billing_event}\n\nCampaign: ${JSON.stringify(r.campaign)}\n\nAdSet: ${JSON.stringify(r.adset)}\n\nCreative: ${JSON.stringify(r.creative)}`
    ElMessageBox.alert(summary, '预检 · 即将发给 FB 的参数', { customClass: 'preflight-modal', confirmButtonText: '关闭' })
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
    if (credId) {
      try { accPages.value[id] = await GET('/fb/credentials/' + credId + '/pages') } catch {}
      try { accPixels.value[id] = await GET('/fb/credentials/' + credId + '/pixels') } catch {}
    }
    deployItems.value[id] = { page_id: deployTpl.value.page_id || '', pixel_id: deployTpl.value.pixel_id || '' }
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
      <button class="btn primary" @click="openNew">+ 新建模板</button>
    </div>
    <div class="d">模板按 FB Ads Manager 三级结构（系列→组→广告）组织。选模板+选账户→一键批量部署。</div>

    <div class="grid" v-loading="loading">
      <div v-for="t in list" :key="t.id" class="card">
        <div class="card-head"><span class="card-name">{{ t.name }}</span><span class="card-obj">{{ objLabel(t.objective) }}</span></div>
        <div class="card-meta"><span>{{ fmtUsd(t.budget_usd) }}/天 · {{ t.budget_mode }}</span><span>{{ t.deploy_count }} 次部署</span></div>
        <div v-if="t.headline" class="card-copy">{{ t.headline }}</div>
        <div class="card-ops">
          <button class="op primary" @click="openDeploy(t)">部署</button>
          <button class="op" :disabled="preflighting" @click="preflight(t)">预检</button>
          <button class="op" @click="openEdit(t)">编辑</button>
          <button class="op danger" @click="removeTpl(t)">归档</button>
        </div>
      </div>
      <div v-if="!list.length && !loading" class="empty">暂无模板，点「+ 新建模板」。</div>
    </div>

    <!-- 编辑抽屉：系列/组/广告 三级 -->
    <el-drawer v-model="editOpen" :title="editing ? '编辑模板' : '新建模板'" direction="rtl" size="680px" :destroy-on-close="true">
      <div class="level-tabs">
        <button :class="['ltab',{on:editLevel==='campaign'}]" @click="editLevel='campaign'">① 系列 Campaign</button>
        <button :class="['ltab',{on:editLevel==='adset'}]" @click="editLevel='adset'">② 广告组 Ad Set</button>
        <button :class="['ltab',{on:editLevel==='ad'}]" @click="editLevel='ad'">③ 广告 Ad</button>
      </div>

      <!-- ① 系列 -->
      <div v-if="editLevel==='campaign'" class="form">
        <div class="row"><label>模板名</label><input v-model="form.name" class="inp" placeholder="如 US-shopping-夏季" /></div>
        <div class="row"><label>广告目标</label><select v-model="form.objective" class="inp"><option v-for="o in OBJECTIVES" :key="o.v" :value="o.v">{{ o.l }}</option></select></div>
        <div class="row"><label>转化目标 conversion_goal</label><input v-model="form.conversion_goal" class="inp" placeholder="如 Purchase（购物/线索用）" /></div>
        <div class="row"><label>预算模式</label><div class="seg"><button :class="{on:form.budget_mode==='ABO'}" @click="form.budget_mode='ABO'">ABO 组预算</button><button :class="{on:form.budget_mode==='CBO'}" @click="form.budget_mode='CBO'">CBO 系列预算</button></div></div>
        <div class="row"><label>每日预算（美元）</label><input v-model.number="form.budget_usd" type="number" min="1" step="0.5" class="inp" /><span class="hint">部署时按账户本币自动换算</span></div>
        <div class="row"><label>出价策略</label><select v-model="form.bid_strategy" class="inp"><option v-for="b in BID_STRATEGIES" :key="b.v" :value="b.v">{{ b.l }}</option></select></div>
        <div class="row"><label>特殊广告类别</label><select v-model="form.special_ad_category" class="inp"><option v-for="s in SPECIAL_CATS" :key="s.v" :value="s.v">{{ s.l }}</option></select></div>
        <div class="row"><label>广告命名前缀</label><input v-model="form.name_prefix" class="inp" /></div>
      </div>

      <!-- ② 广告组 -->
      <div v-if="editLevel==='adset'" class="form">
        <div class="row"><label>优化目标 optimization_goal</label><select v-model="form.optimization_goal" class="inp"><option value="">自动（按目标推）</option><option v-for="g in OPT_GOALS" :key="g" :value="g">{{ g }}</option></select></div>
        <div class="row"><label>计费事件 billing_event</label><select v-model="form.billing_event" class="inp"><option v-for="b in BILLING_EVENTS" :key="b" :value="b">{{ b }}</option></select></div>
        <div class="row"><label>转化目的地 destination_type</label><select v-model="form.destination_type" class="inp"><option value="">自动</option><option v-for="d in DEST_TYPES" :key="d" :value="d">{{ d }}</option></select></div>
        <hr class="sep" />
        <div class="sec-title">受众定向</div>
        <div class="row"><label>国家/地区</label>
          <div class="chips-input">
            <select v-model="form.audience_countries" multiple class="inp multi">
              <option v-for="c in COUNTRIES" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
        </div>
        <div class="row"><label>年龄</label><div class="age-row"><input v-model.number="form.audience_age_min" type="number" min="13" max="65" class="inp sm" /> — <input v-model.number="form.audience_age_max" type="number" min="13" max="65" class="inp sm" /></div></div>
        <div class="row"><label>性别</label><div class="seg"><button :class="{on:form.audience_gender===0}" @click="form.audience_gender=0">全部</button><button :class="{on:form.audience_gender===1}" @click="form.audience_gender=1">男</button><button :class="{on:form.audience_gender===2}" @click="form.audience_gender=2">女</button></div></div>
        <div class="row"><label>语言（定向说此语言的人）</label><select v-model="form.audience_language" class="inp"><option v-for="l in LANGS" :key="l.v" :value="l.v">{{ l.l }}</option></select></div>
        <div class="row"><label>兴趣关键词（FB adinterest 搜索）</label>
          <div class="interest-search">
            <input v-model="interestQ" class="inp" placeholder="如 Shopping / 美妆 / 投资" @keyup.enter="searchInterests" />
            <button class="btn sm" :disabled="interestSearching" @click="searchInterests">{{ interestSearching ? '…' : '搜索' }}</button>
            <button class="btn sm ghost" @click="importAiInterests" v-if="editingAsset?.ai_audience?.interests?.length">从素材AI导入</button>
          </div>
          <div v-if="interestResults.length" class="search-results">
            <div v-for="r in interestResults" :key="r.id" class="search-item" @click="addInterest(r)"><span>{{ r.name }}</span><span class="sz">{{ r.audience_size ? Math.floor(r.audience_size/1e6)+'M' : '' }}</span><span class="add">+</span></div>
          </div>
        </div>
        <div class="row"><label>已选兴趣（{{ form.audience_interests.length }}）</label>
          <div class="interest-list">
            <span v-for="(it,i) in form.audience_interests" :key="it.id" class="interest-chip">{{ it.name }} <button @click="removeInterest(i)">✕</button></span>
            <span v-if="!form.audience_interests.length" class="hint">点上方搜索添加</span>
          </div>
        </div>
        <hr class="sep" />
        <div class="sec-title">披露（部分国家强制）</div>
        <div class="row"><label>受益人 beneficiary</label><input v-model="form.beneficiary" class="inp" placeholder="EU/泰国/印度/巴西/台湾/澳洲/新加坡等必填" /></div>
        <div class="row"><label>付款人 payer</label><input v-model="form.payer" class="inp" /></div>
        <hr class="sep" />
        <div class="sec-title">高级（JSON，可选）</div>
        <div class="row"><label>advanced_config（bid_amount/attribution_spec/placements/dayparting…）</label><textarea v-model="form.advanced_config" class="inp ta" rows="3" placeholder='如 {"bid_amount":500}'></textarea></div>
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
        <div v-if="editingAsset && (editingAsset.ai_copy?.headlines||[]).length" class="ai-copy">
          <div class="ai-copy-t">AI 文案（点选填充）</div>
          <div v-for="(h,i) in (editingAsset.ai_copy?.headlines||[])" :key="'h'+i" class="ai-pick" @click="form.headline=h"><span class="ai-tag">标题{{i+1}}</span> {{ h }}</div>
          <div v-for="(b,i) in (editingAsset.ai_copy?.bodies||[])" :key="'b'+i" class="ai-pick" @click="form.body=b"><span class="ai-tag">正文{{i+1}}</span> {{ b }}</div>
        </div>
        <div class="row"><label>标题 headline</label><input v-model="form.headline" class="inp" /></div>
        <div class="row"><label>正文 body</label><textarea v-model="form.body" class="inp ta" rows="3"></textarea></div>
        <div class="row"><label>行动号召 CTA</label><select v-model="form.cta_type" class="inp"><option v-for="c in CTAS" :key="c.v" :value="c.v">{{ c.l }}（{{ c.v }}）</option></select></div>
        <div class="row"><label>主页 page_id</label><input v-model="form.page_id" class="inp" placeholder="默认值（部署时每账户下拉选）" /></div>
        <div class="row"><label>像素 pixel_id</label><input v-model="form.pixel_id" class="inp" placeholder="购物/线索目标必填" /></div>
        <div class="row"><label>落地页</label>
          <select v-model="form.landing_page_id" class="inp" @change="form.landing_url = (landingPages.find(p=>p.id==form.landing_page_id)?.public_url || form.landing_url)">
            <option :value="null">手动填 URL</option>
            <option v-for="p in landingPages" :key="p.id" :value="p.id">{{ p.title }}（{{ p.public_url || '无URL' }}）</option>
          </select>
        </div>
        <div class="row"><label>落地页 URL</label><input v-model="form.landing_url" class="inp" placeholder="https://..." /></div>
        <div class="row"><label>子码 slug</label><input v-model="form.subcode_slug" class="inp" placeholder="留空=不绑子码" /></div>
        <div class="row"><label>广告语言</label><select v-model="form.ad_language" class="inp"><option value="">自动</option><option v-for="l in LANGS.filter(x=>x.v)" :key="l.v" :value="l.v">{{ l.l }}</option></select></div>
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
    <el-drawer v-model="deployOpen" :title="`部署 · ${deployTpl?.name||''}`" direction="rtl" size="600px">
      <div class="d">勾选账户。每账户的主页/像素从下拉选（默认填模板值）。</div>
      <div class="acc-list" v-loading="accLoading">
        <div v-for="a in accounts" :key="a.act_id" class="acc-block">
          <label class="acc-row" :class="{on:selectedAccs.has(a.act_id)}">
            <input type="checkbox" :checked="selectedAccs.has(a.act_id)" @change="toggleAcc(a.act_id)" />
            <span class="acc-name">{{ a.name || a.act_id }}</span>
            <span class="acc-id">{{ a.act_id }} · {{ a.currency }}</span>
          </label>
          <div v-if="selectedAccs.has(a.act_id)" class="acc-config">
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
.search-results{margin-top:4px;max-height:160px;overflow-y:auto;border:1px solid var(--bd);border-radius:6px}
.search-item{display:flex;align-items:center;gap:6px;padding:5px 8px;font-size:12px;color:var(--t2);cursor:pointer;border-bottom:1px solid var(--bd)}
.search-item:last-child{border:none}
.search-item:hover{background:var(--bg3)}
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
.picker-card{background:var(--bg2);border:1px solid var(--bd);border-radius:8px;overflow:hidden;cursor:pointer}
.picker-card:hover{border-color:var(--ac)}
.picker-thumb{width:100%;height:90px;object-fit:cover}
.picker-name{display:block;font-size:11px;color:var(--t2);padding:4px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

.acc-list{display:flex;flex-direction:column;gap:6px;margin-top:10px}
.acc-block{border:1px solid var(--bd);border-radius:8px;overflow:hidden}
.acc-row{display:flex;align-items:center;gap:8px;padding:8px 10px;cursor:pointer}
.acc-row.on{background:rgba(10,132,255,.08)}
.acc-name{font-size:13px;color:var(--t1);flex:1}
.acc-id{font-size:11px;color:var(--t3);font-family:monospace}
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
</style>
