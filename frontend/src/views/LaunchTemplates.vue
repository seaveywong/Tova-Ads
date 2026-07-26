<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fmtTime } from '../composables/useTz'
import { showError } from '../composables/useError'

const list = ref([])
const loading = ref(false)
// 编辑抽屉
const editOpen = ref(false)
const editing = ref(null)  // null=新建
const form = ref({})
const saving = ref(false)
// 素材选择器
const assetPickerOpen = ref(false)
const pickerAssets = ref([])
const pickerLoading = ref(false)
// 部署抽屉
const deployOpen = ref(false)
const deployTpl = ref(null)
const accounts = ref([])
const accLoading = ref(false)
const selectedAccs = ref(new Set())
const deploying = ref(false)
// 进度
const progressOpen = ref(false)
const activeJob = ref(null)
let pollTimer = null

const OBJECTIVES = [
  { v: 'OUTCOME_SALES', l: '购物（转化）' },
  { v: 'OUTCOME_LEADS', l: '潜在客户（表单/留资）' },
  { v: 'OUTCOME_TRAFFIC', l: '流量（点击）' },
  { v: 'OUTCOME_ENGAGEMENT', l: '互动（主页赞/消息）' },
  { v: 'OUTCOME_AWARENESS', l: '品牌认知' },
  { v: 'OUTCOME_APP_PROMOTION', l: '应用推广' },
]
const CTAS = ['SHOP_NOW', 'SIGN_UP', 'SUBSCRIBE', 'LEARN_MORE', 'DOWNLOAD', 'CONTACT_US', 'GET_QUOTE', 'BOOK_NOW']
const audiences = ref([])
const editTab = ref('struct')

const BASE = 'https://api.tovaads.com'

const load = async () => {
  loading.value = true
  try { list.value = await GET('/launch-templates') } catch (e) { ElMessage.error(e.message || '加载失败') }
  loading.value = false
}
const loadAudiences = async () => { try { audiences.value = await GET('/audiences') } catch {} }
onMounted(() => { load(); loadAudiences() })
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })

const blankForm = () => ({
  name: '', description: '', objective: 'OUTCOME_SALES', conversion_goal: '',
  budget_mode: 'ABO', bid_strategy: 'LOWEST_COST_WITHOUT_CAP', daily_budget: 200000,
  name_prefix: 'Tova Ads', audience_id: 0, asset_id: null,
  headline: '', body: '', page_id: '', pixel_id: '', landing_url: '',
  cta_type: 'SHOP_NOW', subcode_slug: '', ad_language: '',
})
const objLabel = (v) => OBJECTIVES.find(o => o.v === v)?.l || v
const audLabel = (id) => { const a = audiences.value.find(x => x.id === id); return a ? a.name : '默认定向' }
const assetOf = (id) => list.value.find(() => true) // placeholder; we fetch asset info on edit
const editingAsset = ref(null)

const openNew = () => { editing.value = null; form.value = blankForm(); editingAsset.value = null; editOpen.value = true }
const openEdit = async (t) => {
  editing.value = t
  form.value = { ...blankForm(), ...t }
  editingAsset.value = null
  if (t.asset_id) { try { editingAsset.value = await GET('/assets/' + t.asset_id) } catch {} }
  editOpen.value = true
}
const pickAsset = async (a) => {
  form.value.asset_id = a.id
  editingAsset.value = a
  // 自动带出 AI 文案（第一条）
  const hs = (a.ai_copy?.headlines || [])
  const bs = (a.ai_copy?.bodies || [])
  if (!form.value.headline && hs[0]) form.value.headline = hs[0]
  if (!form.value.body && bs[0]) form.value.body = bs[0]
  assetPickerOpen.value = false
}
const saveTpl = async () => {
  if (!form.value.name.trim()) return ElMessage.warning('填模板名')
  if (!form.value.asset_id) return ElMessage.warning('选一个素材')
  saving.value = true
  try {
    const body = { ...form.value, daily_budget: Number(form.value.daily_budget) }
    if (editing.value) {
      await PUT('/launch-templates/' + editing.value.id, body); ElMessage.success('已保存')
    } else {
      await POST('/launch-templates', body); ElMessage.success('已创建')
    }
    editOpen.value = false; await load()
  } catch (e) { showError(e, '保存模板失败') }
  saving.value = false
}
const removeTpl = async (t) => {
  try {
    await ElMessageBox.confirm(`归档模板「${t.name}」？（部署历史保留）`, '确认', { type: 'warning' })
    await DELETE('/launch-templates/' + t.id); ElMessage.success('已归档'); await load()
  } catch (e) { if (e === 'cancel') return }
}

// 素材选择器
const openAssetPicker = async () => {
  assetPickerOpen.value = true; pickerLoading.value = true
  try { pickerAssets.value = await GET('/assets') } catch {}
  pickerLoading.value = false
}

// 部署
const openDeploy = async (t) => {
  deployTpl.value = t; deployOpen.value = true; selectedAccs.value = new Set()
  accLoading.value = true
  try { accounts.value = await GET('/fb/accounts') } catch (e) { showError(e, '加载账户失败') }
  accLoading.value = false
}
const toggleAcc = (id) => { const s = new Set(selectedAccs.value); s.has(id) ? s.delete(id) : s.add(id); selectedAccs.value = s }
const startDeploy = async () => {
  if (!selectedAccs.value.size) return ElMessage.warning('先选账户')
  const items = accounts.value.filter(a => selectedAccs.value.has(a.act_id)).map(a => ({
    act_id: a.act_id,
    page_id: deployTpl.value.page_id || '',
    pixel_id: deployTpl.value.pixel_id || '',
  }))
  deploying.value = true
  try {
    const r = await POST('/launch-templates/' + deployTpl.value.id + '/deploy', { items })
    deployOpen.value = false
    ElMessage.success(`已提交部署：${r.total} 个账户`)
    openProgress(r.job_id)
    await load()
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
    if (['completed', 'partial_failed', 'failed'].includes(activeJob.value.status)) {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    }
  } catch {}
}
const retryItem = async (it) => {
  try {
    await POST(`/launch-templates/jobs/${activeJob.value.id}/retry/${it.id}`, {})
    ElMessage.success('已提交重试')
    if (!pollTimer) pollJob(activeJob.value.id)  // 重新轮询
    if (!pollTimer) pollTimer = setInterval(() => pollJob(activeJob.value.id), 2500)
  } catch (e) { showError(e, '重试提交失败') }
}
const statusColor = (s) => s === 'success' ? 'var(--success)' : s === 'fail' ? 'var(--error)' : s === 'creating' ? 'var(--ac)' : 'var(--t3)'
const statusText = (s) => ({ success: '✓ 成功', fail: '✗ 失败', creating: '创建中', pending: '等待' }[s] || s)
const fbAdsUrl = (actId, campId) => `https://www.facebook.com/adsmanager/manage/campaigns?act=${actId}&selected_campaign_ids=${campId}`

const fmtBudget = (cents) => '$' + (cents / 100).toFixed(0)
</script>

<template>
  <div class="page">
    <div class="bar">
      <div class="t">投放模板</div>
      <button class="btn primary" @click="openNew">+ 新建模板</button>
    </div>
    <div class="d">把一套广告结构（素材+文案+受众+预算）存成模板，一键部署到多个账户。</div>

    <div class="grid" v-loading="loading">
      <div v-for="t in list" :key="t.id" class="card">
        <div class="card-head">
          <span class="card-name" :title="t.name">{{ t.name }}</span>
          <span class="card-obj">{{ objLabel(t.objective) }}</span>
        </div>
        <div class="card-meta">
          <span>{{ fmtBudget(t.daily_budget) }}/天 · {{ t.budget_mode }}</span>
          <span>{{ audLabel(t.audience_id) }}</span>
        </div>
        <div v-if="t.headline" class="card-copy" :title="t.body">“{{ t.headline }}”</div>
        <div class="card-foot">
          <span class="deployed">已部署 {{ t.deploy_count }} 次</span>
          <div class="card-ops">
            <button class="op primary" @click="openDeploy(t)">部署</button>
            <button class="op" @click="openEdit(t)">编辑</button>
            <button class="op danger" @click="removeTpl(t)">归档</button>
          </div>
        </div>
      </div>
      <div v-if="!list.length && !loading" class="empty">暂无模板，点「+ 新建模板」创建第一个。</div>
    </div>

    <!-- 编辑抽屉 -->
    <el-drawer v-model="editOpen" :title="editing ? '编辑模板' : '新建模板'" direction="rtl" size="640px" :destroy-on-close="true">
      <div class="tabs-bar">
        <button :class="['tab', { on: editTab === 'struct' }]" @click="editTab = 'struct'">结构</button>
        <button :class="['tab', { on: editTab === 'asset' }]" @click="editTab = 'asset'">素材</button>
      </div>
      <!-- 结构 Tab -->
      <div v-if="editTab === 'struct'" class="form">
        <div class="row"><label>模板名</label><input v-model="form.name" class="inp" placeholder="如 US-shopping-夏季" /></div>
        <div class="row"><label>目标</label>
          <select v-model="form.objective" class="inp">
            <option v-for="o in OBJECTIVES" :key="o.v" :value="o.v">{{ o.l }}</option>
          </select>
        </div>
        <div class="row"><label>转化目标</label><input v-model="form.conversion_goal" class="inp" placeholder="如 Purchase（购物目标用）" /></div>
        <div class="row"><label>预算模式</label>
          <div class="seg"><button :class="{on: form.budget_mode==='ABO'}" @click="form.budget_mode='ABO'">ABO（组预算）</button><button :class="{on: form.budget_mode==='CBO'}" @click="form.budget_mode='CBO'">CBO（系列预算）</button></div>
        </div>
        <div class="row"><label>每日预算（美分）</label><input v-model.number="form.daily_budget" type="number" class="inp" /> <span class="hint">≈ {{ fmtBudget(form.daily_budget) }}</span></div>
        <div class="row"><label>受众</label>
          <select v-model="form.audience_id" class="inp">
            <option :value="0">默认定向</option>
            <option v-for="a in audiences" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </div>
        <div class="row"><label>主页 ID</label><input v-model="form.page_id" class="inp" placeholder="FB Page ID" /></div>
        <div class="row"><label>像素 ID</label><input v-model="form.pixel_id" class="inp" placeholder="FB Pixel ID" /></div>
        <div class="row"><label>落地页 URL</label><input v-model="form.landing_url" class="inp" placeholder="https://..." /></div>
        <div class="row"><label>CTA</label>
          <select v-model="form.cta_type" class="inp"><option v-for="c in CTAS" :key="c" :value="c">{{ c }}</option></select>
        </div>
        <div class="row"><label>广告名前缀</label><input v-model="form.name_prefix" class="inp" /></div>
      </div>
      <!-- 素材 Tab -->
      <div v-if="editTab === 'asset'" class="form">
        <div class="row"><label>素材</label>
          <div class="asset-pick">
            <div v-if="editingAsset" class="asset-chosen">
              <img v-if="editingAsset.type==='image'" :src="editingAsset.public_url" class="asset-thumb" />
              <span class="asset-name">{{ editingAsset.name }}</span>
            </div>
            <button class="btn" @click="openAssetPicker">{{ editingAsset ? '换一个' : '选择素材' }}</button>
          </div>
        </div>
        <!-- AI 文案快选 -->
        <div v-if="editingAsset && (editingAsset.ai_copy?.headlines||[]).length" class="ai-copy">
          <div class="ai-copy-t">AI 文案（点选填充）</div>
          <div v-for="(h, i) in (editingAsset.ai_copy?.headlines||[])" :key="'h'+i" class="ai-pick" @click="form.headline = h">
            <span class="ai-tag">H{{i+1}}</span> {{ h }}
          </div>
          <div v-for="(b, i) in (editingAsset.ai_copy?.bodies||[])" :key="'b'+i" class="ai-pick" @click="form.body = b">
            <span class="ai-tag">B{{i+1}}</span> {{ b }}
          </div>
        </div>
        <div class="row"><label>标题 headline</label><input v-model="form.headline" class="inp" /></div>
        <div class="row"><label>正文 body</label><textarea v-model="form.body" class="inp ta" rows="3"></textarea></div>
        <div class="row"><label>子码 slug</label><input v-model="form.subcode_slug" class="inp" placeholder="留空=不绑子码" /></div>
        <div class="row"><label>语言</label><input v-model="form.ad_language" class="inp" placeholder="en/zh（控 CJK 守卫）" /></div>
      </div>
      <template #footer>
        <button class="btn" @click="editOpen = false">取消</button>
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

    <!-- 部署抽屉 -->
    <el-drawer v-model="deployOpen" :title="`部署 · ${deployTpl?.name || ''}`" direction="rtl" size="560px">
      <div class="d">选要部署到的账户。主页/像素用模板默认（{{ deployTpl?.page_id || '未设' }} / {{ deployTpl?.pixel_id || '未设' }}）。</div>
      <div class="acc-list" v-loading="accLoading">
        <label v-for="a in accounts" :key="a.act_id" class="acc-row" :class="{ on: selectedAccs.has(a.act_id) }">
          <input type="checkbox" :checked="selectedAccs.has(a.act_id)" @change="toggleAcc(a.act_id)" />
          <span class="acc-name">{{ a.name || a.act_id }}</span>
          <span class="acc-id">{{ a.act_id }}</span>
        </label>
        <div v-if="!accounts.length && !accLoading" class="empty">无可用账户（先在广告账户页载入）</div>
      </div>
      <template #footer>
        <span class="sel-count">已选 {{ selectedAccs.size }}</span>
        <button class="btn" @click="deployOpen = false">取消</button>
        <button class="btn primary" :disabled="deploying || !selectedAccs.size" @click="startDeploy">{{ deploying ? '提交中…' : '开始部署' }}</button>
      </template>
    </el-drawer>

    <!-- 进度弹窗 -->
    <el-dialog v-model="progressOpen" title="部署进度" width="720px" :close-on-click-modal="false" @close="if (pollTimer) { clearInterval(pollTimer); pollTimer = null }">
      <div v-if="activeJob" class="prog">
        <div class="prog-head">
          <span>模板：{{ activeJob.template_name }}</span>
          <span class="prog-stat">{{ activeJob.succeeded }}✓ / {{ activeJob.failed }}✗ / {{ activeJob.total }}</span>
          <span :class="['prog-status', activeJob.status]">{{ activeJob.status }}</span>
        </div>
        <div class="prog-items">
          <div v-for="it in activeJob.items" :key="it.id" class="prog-item">
            <span class="dot" :style="{ background: statusColor(it.status) }"></span>
            <span class="pi-act">{{ it.act_id }}</span>
            <span :class="['pi-status', it.status]">{{ statusText(it.status) }}</span>
            <a v-if="it.campaign_id" :href="fbAdsUrl(it.act_id, it.campaign_id)" target="_blank" class="pi-link">FB广告 →</a>
            <span v-if="it.error" class="pi-err" :title="it.error">{{ it.error.slice(0, 50) }}</span>
            <button v-if="it.status==='fail'" class="op primary sm" @click="retryItem(it)">重试</button>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 14px; }
.bar { display: flex; justify-content: space-between; align-items: center; }
.t { font-size: 18px; font-weight: 600; color: var(--t1); }
.d { font-size: 12px; color: var(--t3); line-height: 1.6; }
.btn { padding: 7px 14px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t1); border-radius: 6px; font-size: 13px; cursor: pointer; font-family: inherit; }
.btn.primary { background: var(--ac); color: #fff; border-color: var(--ac); }
.btn:disabled { opacity: .5; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
.card { background: var(--bg2); border: 1px solid var(--bd); border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; }
.card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 6px; }
.card-name { font-size: 14px; font-weight: 600; color: var(--t1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-obj { font-size: 11px; color: var(--ac); white-space: nowrap; }
.card-meta { display: flex; gap: 10px; font-size: 11px; color: var(--t3); flex-wrap: wrap; }
.card-copy { font-size: 11px; color: var(--t2); font-style: italic; line-height: 1.4; max-height: 32px; overflow: hidden; }
.card-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 4px; }
.deployed { font-size: 10px; color: var(--t3); }
.card-ops { display: flex; gap: 3px; }
.op { background: none; border: 1px solid var(--bd); color: var(--t2); font-size: 11px; cursor: pointer; padding: 3px 8px; border-radius: 4px; }
.op.primary { color: var(--ac); border-color: var(--ac); }
.op.primary.sm { padding: 2px 6px; font-size: 10px; }
.op.danger { color: var(--error); }
.op:hover { background: var(--bg3); }
.empty { grid-column: 1 / -1; padding: 40px; text-align: center; color: var(--t3); font-size: 14px; }

.tabs-bar { display: flex; gap: 4px; margin-bottom: 16px; background: var(--bg3); padding: 3px; border-radius: 8px; }
.tab { flex: 1; padding: 7px; border: none; background: transparent; color: var(--t3); border-radius: 6px; cursor: pointer; font-size: 13px; font-family: inherit; }
.tab.on { background: var(--bg2); color: var(--t1); }
.form { display: flex; flex-direction: column; gap: 12px; }
.row { display: flex; flex-direction: column; gap: 4px; }
.row label { font-size: 12px; color: var(--t3); font-weight: 500; }
.inp { padding: 6px 10px; background: var(--bg3); border: 1px solid var(--bd); border-radius: 6px; color: var(--t1); font-size: 13px; font-family: inherit; }
.inp:focus { border-color: var(--ac); outline: none; }
.ta { resize: vertical; }
.hint { font-size: 11px; color: var(--t3); }
.seg { display: flex; gap: 4px; }
.seg button { flex: 1; padding: 6px; border: 1px solid var(--bd); background: var(--bg3); color: var(--t3); border-radius: 6px; cursor: pointer; font-size: 12px; font-family: inherit; }
.seg button.on { border-color: var(--ac); color: var(--ac); background: rgba(10,132,255,.1); }

.asset-pick { display: flex; align-items: center; gap: 10px; }
.asset-chosen { display: flex; align-items: center; gap: 6px; flex: 1; }
.asset-thumb { width: 36px; height: 36px; object-fit: cover; border-radius: 6px; }
.asset-name { font-size: 12px; color: var(--t2); }
.ai-copy { background: var(--bg3); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; }
.ai-copy-t { font-size: 11px; color: var(--t3); margin-bottom: 2px; }
.ai-pick { font-size: 12px; color: var(--t2); cursor: pointer; padding: 3px 6px; border-radius: 4px; line-height: 1.4; }
.ai-pick:hover { background: var(--bg2); color: var(--t1); }
.ai-tag { font-size: 9px; color: var(--ac); background: rgba(10,132,255,.15); padding: 1px 4px; border-radius: 3px; margin-right: 4px; }

.picker-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
.picker-card { background: var(--bg2); border: 1px solid var(--bd); border-radius: 8px; overflow: hidden; cursor: pointer; }
.picker-card:hover { border-color: var(--ac); }
.picker-thumb { width: 100%; height: 90px; object-fit: cover; }
.picker-name { display: block; font-size: 11px; color: var(--t2); padding: 4px 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.acc-list { display: flex; flex-direction: column; gap: 4px; margin-top: 10px; }
.acc-row { display: flex; align-items: center; gap: 8px; padding: 7px 10px; background: var(--bg3); border-radius: 6px; cursor: pointer; }
.acc-row.on { background: rgba(10,132,255,.1); }
.acc-name { font-size: 13px; color: var(--t1); flex: 1; }
.acc-id { font-size: 11px; color: var(--t3); font-family: monospace; }
.sel-count { font-size: 12px; color: var(--t3); margin-right: auto; }

.prog-head { display: flex; gap: 14px; align-items: center; margin-bottom: 10px; font-size: 13px; }
.prog-stat { color: var(--t2); font-variant-numeric: tabular-nums; }
.prog-status { font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 600; }
.prog-status.completed { color: var(--success); background: rgba(52,199,89,.13); }
.prog-status.partial_failed { color: var(--warning); background: rgba(255,159,10,.13); }
.prog-status.running { color: var(--ac); background: rgba(10,132,255,.13); }
.prog-status.failed { color: var(--error); background: rgba(255,69,58,.13); }
.prog-items { display: flex; flex-direction: column; gap: 2px; max-height: 50vh; overflow-y: auto; }
.prog-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; font-size: 12px; border-bottom: 1px solid var(--bd); }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.pi-act { font-family: monospace; color: var(--t2); width: 130px; }
.pi-status { font-size: 11px; width: 50px; }
.pi-status.success { color: var(--success); }
.pi-status.fail { color: var(--error); }
.pi-link { color: var(--ac); text-decoration: none; font-size: 11px; }
.pi-err { color: var(--error); font-size: 11px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
