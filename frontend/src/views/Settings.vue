<script setup>
import { ref, computed, onMounted } from 'vue'
import { GET, PATCH, PUT, POST } from '../api'
import { userTz, setUserTz } from '../composables/useTz'
import { ElMessage, ElMessageBox } from 'element-plus'

// 时区
const TZ_OPTIONS = [
  { tz: 'Asia/Shanghai', label: '北京/上海' }, { tz: 'Asia/Hong_Kong', label: '香港' },
  { tz: 'Asia/Taipei', label: '台北' }, { tz: 'Asia/Tokyo', label: '东京' },
  { tz: 'Asia/Seoul', label: '首尔' }, { tz: 'Asia/Singapore', label: '新加坡' },
  { tz: 'Asia/Bangkok', label: '曼谷' }, { tz: 'Asia/Jakarta', label: '雅加达' },
  { tz: 'Asia/Kolkata', label: '孟买' }, { tz: 'America/Los_Angeles', label: '洛杉矶' },
  { tz: 'America/New_York', label: '纽约' }, { tz: 'America/Sao_Paulo', label: '圣保罗' },
  { tz: 'Europe/London', label: '伦敦' }, { tz: 'Europe/Paris', label: '巴黎' },
  { tz: 'Australia/Sydney', label: '悉尼' }, { tz: 'UTC', label: 'UTC' },
]
const tz = ref(userTz.value)
const saving = ref(false)
const pick = async (z) => {
  saving.value = true
  try { await PATCH('/auth/me', { timezone: z }); setUserTz(z); ElMessage.success('已切换，所有时间按此时区显示') }
  catch (e) { ElMessage.error('保存失败：' + (e.message || '')) }
  saving.value = false
}

// 调度（仅超管）
const isSuper = ref(localStorage.getItem('tova_super') === '1')
const sched = ref({
  base_minutes: 5,
  sentinel_minutes: 3,
  multipliers: { inspect: 1, watchdog: 2, account_sync: 6, budget: 3, reassociate: 24, subcode: 12 },
  effective: { inspect: 5, watchdog: 10, account_sync: 30, budget: 15, reassociate: 120, subcode: 60, sentinel: 3 },
  task_labels: {
    inspect: '巡检（止损评估）', watchdog: '令牌健康检查', account_sync: '账户状态/余额',
    budget: '预算进度告警', reassociate: '失效账户重绑', subcode: '子码自动绑定',
    sentinel: '哨兵巡逻',
  },
})
const schedSaving = ref(false)
const TASK_ORDER = ['inspect', 'watchdog', 'account_sync', 'budget', 'subcode', 'reassociate']
const effOf = (k) => {
  const base = Number(sched.value?.base_minutes) || 0
  const m = Number(sched.value?.multipliers?.[k])
  return (m && base) ? base * m : sched.value?.effective?.[k] ?? '—'
}
const loadSched = async () => {
  try {
    const me = await GET('/auth/me')
    isSuper.value = !!me.is_superadmin
    localStorage.setItem('tova_super', me.is_superadmin ? '1' : '0')
    setUserTz(me.timezone || 'Asia/Shanghai'); tz.value = me.timezone || 'Asia/Shanghai'
    acctEmail.value = me.email || ''
    if (isSuper.value) {
      try { sched.value = await GET('/settings/schedule') }
      catch { sched.value = null }
    }
  } catch {}
}
const saveSched = async () => {
  // dirty 判断：比对 effective 里的实际间隔值（inspect 是基准×乘数的结果）
  const e = sched.value?.effective || {}
  const effInspect = e.inspect ?? 0
  const curInspect = Math.round(Number(sched.value.base_minutes) * (sched.value.multipliers?.inspect || 1))
  if (Number(sched.value.sentinel_minutes) === (e.sentinel ?? 0) && curInspect === effInspect) {
    return ElMessage.info('无变更')
  }
  if (Number(sched.value.sentinel_minutes) !== (e.sentinel ?? 0)) {
    try {
      await ElMessageBox.confirm(
        `哨兵巡逻间隔将改为 ${sched.value.sentinel_minutes} 分钟，确认？`,
        '哨兵间隔变更', { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' }
      )
    } catch { return }
  }
  schedSaving.value = true
  try {
    const r = await PUT('/settings/schedule', {
      base_minutes: Number(sched.value.base_minutes),
      sentinel_minutes: Number(sched.value.sentinel_minutes),
      multipliers: sched.value.multipliers,
    })
    sched.value.effective = r.effective
    ElMessage.success('已保存')
  } catch (e) { ElMessage.error('保存失败：' + (e.message || '')) }
  schedSaving.value = false
}

// AI 配置（超管）
const AI_PRESETS = {
  'https://api.deepseek.com/v1': { label: 'DeepSeek', models: ['deepseek-v4-flash', 'deepseek-v4-pro', 'deepseek-chat', 'deepseek-reasoner'] },
  'https://api.openai.com/v1': { label: 'OpenAI', models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini'] },
  'https://generativelanguage.googleapis.com/v1beta/openai': { label: 'Gemini（OpenAI 兼容）', models: ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-2.5-pro'] },
}
const aiBaseOptions = Object.entries(AI_PRESETS).map(([url, p]) => ({ url, label: p.label }))
const aiCfg = ref({ ai_base_url: '', ai_api_key_masked: '', ai_api_key_set: false, ai_model: '' })
const aiForm = ref({ ai_base_url: '', ai_api_key: '', ai_model: '' })
const aiModelOptions = computed(() => AI_PRESETS[aiForm.value.ai_base_url]?.models || [])
const aiSaving = ref(false)
const aiTesting = ref(false)
const loadAi = async () => {
  if (!isSuper.value) return
  try {
    aiCfg.value = await GET('/settings/ai')
    aiForm.value = { ai_base_url: aiCfg.value.ai_base_url, ai_api_key: '', ai_model: aiCfg.value.ai_model }
  } catch {}
}
const saveAi = async () => {
  aiSaving.value = true
  try {
    const body = {}
    if (aiForm.value.ai_base_url && aiForm.value.ai_base_url !== aiCfg.value.ai_base_url) body.ai_base_url = aiForm.value.ai_base_url
    if (aiForm.value.ai_api_key) body.ai_api_key = aiForm.value.ai_api_key
    if (aiForm.value.ai_model && aiForm.value.ai_model !== aiCfg.value.ai_model) body.ai_model = aiForm.value.ai_model
    if (!Object.keys(body).length) { ElMessage.info('无变更'); aiSaving.value = false; return }
    await PUT('/settings/ai', body)
    ElMessage.success('已保存')
    await loadAi()
  } catch (e) { ElMessage.error('保存失败：' + (e.message || '')) }
  aiSaving.value = false
}
const testAi = async () => {
  aiTesting.value = true
  try {
    const r = await POST('/settings/ai/test', {})
    r.ok ? ElMessage.success('连接正常：' + r.detail) : ElMessage.error('连接失败：' + r.detail)
  } catch (e) { ElMessage.error('测试失败') }
  aiTesting.value = false
}

// 账户（用户名 + 改密码）
const acctEmail = ref('')
const acctSaving = ref(false)
const pwdForm = ref({ old: '', new: '', confirm: '' })
const pwdSaving = ref(false)
const saveEmail = async () => {
  if (!acctEmail.value.trim() || !acctEmail.value.includes('@')) return ElMessage.warning('填有效邮箱')
  acctSaving.value = true
  try { await PATCH('/auth/me/email', { email: acctEmail.value.trim() }); ElMessage.success('用户名已更新，下次登录用新邮箱') }
  catch (e) { ElMessage.error('失败：' + (e.message || '')) }
  acctSaving.value = false
}
const savePwd = async () => {
  if (!pwdForm.value.old || !pwdForm.value.new) return ElMessage.warning('填旧/新密码')
  if (pwdForm.value.new !== pwdForm.value.confirm) return ElMessage.error('两次新密码不一致')
  if (pwdForm.value.new.length < 8) return ElMessage.error('新密码至少 8 位')
  pwdSaving.value = true
  try { await PUT('/auth/me/password', { old_password: pwdForm.value.old, new_password: pwdForm.value.new }); ElMessage.success('密码已更新，请用新密码重新登录'); pwdForm.value = { old: '', new: '', confirm: '' } }
  catch (e) { ElMessage.error('失败：' + (e.message || '')) }
  pwdSaving.value = false
}
// 域名服务配置（超管）
const cfCfg = ref({ cf_api_token_masked: '', cf_api_token_set: false, cf_account_id: '' })
const cfForm = ref({ cf_api_token: '', cf_account_id: '' })
const cfSaving = ref(false)
const loadCf = async () => {
  if (!isSuper.value) return
  try {
    cfCfg.value = await GET('/settings/cf')
    cfForm.value = { cf_api_token: '', cf_account_id: cfCfg.value.cf_account_id }
  } catch {}
}
const saveCf = async () => {
  cfSaving.value = true
  try {
    const body = {}
    if (cfForm.value.cf_api_token) body.cf_api_token = cfForm.value.cf_api_token
    if (cfForm.value.cf_account_id && cfForm.value.cf_account_id !== cfCfg.value.cf_account_id) body.cf_account_id = cfForm.value.cf_account_id
    if (!Object.keys(body).length) { ElMessage.info('无变更'); cfSaving.value = false; return }
    await PUT('/settings/cf', body)
    ElMessage.success('已保存')
    await loadCf()
  } catch (e) { ElMessage.error('保存失败：' + (e.message || '')) }
  cfSaving.value = false
}
onMounted(async () => { await loadSched(); await loadAi(); await loadCf(); await loadRetention(); await loadFx() })

// 汇率（超管）—— 止损 to_usd 用，每日自动刷新
const fxRates = ref([])
const fxLoading = ref(false)
const loadFx = async () => {
  if (!isSuper.value) return
  try { const r = await GET('/settings/fx'); fxRates.value = r.rates || [] } catch {}
}
const runFx = async () => {
  fxLoading.value = true
  try { const r = await POST('/settings/fx/run'); ElMessage.success(`已更新 ${r.updated} 个币种汇率`); await loadFx() }
  catch (e) { ElMessage.error('拉取失败：' + (e.message || '')) }
  fxLoading.value = false
}
const fxFetched = computed(() => fxRates.value[0]?.fetched_at?.slice(0,16).replace('T',' ') || '')

// 数据保留（超管）—— 各表老数据保留天数，0=永久
const retention = ref({ tables: [], last_run: '' })
const retentionSaving = ref(false)
const retentionRunning = ref(false)
const loadRetention = async () => {
  if (!isSuper.value) return
  try { retention.value = await GET('/settings/retention') } catch {}
}
const saveRetention = async () => {
  retentionSaving.value = true
  try {
    const days = {}
    retention.value.tables.forEach(t => { days[t.key] = t.days })
    retention.value = await PUT('/settings/retention', { days })
    ElMessage.success('保留策略已保存（每日 4:33 自动清理）')
  } catch (e) { ElMessage.error('保存失败：' + (e.message || '')) }
  retentionSaving.value = false
}
const runRetentionNow = async () => {
  retentionRunning.value = true
  try {
    const r = await POST('/settings/retention/run')
    const parts = Object.entries(r).map(([t, v]) => `${t}:${v.deleted ?? 0}删`)
    ElMessage.success('清理完成 · ' + parts.join(' '))
    await loadRetention()
  } catch (e) { ElMessage.error('清理失败：' + (e.message || '')) }
  retentionRunning.value = false
}
</script>

<template>
  <div class="page">
    <div class="card">
      <div class="t">账户</div>
      <div class="d">登录用户名（邮箱）和密码。修改密码后需用新密码重新登录。</div>
      <div class="form-l"><label>用户名</label><input v-model="acctEmail" class="input" placeholder="登录邮箱" /></div>
      <button class="btn primary" :disabled="acctSaving" @click="saveEmail">保存用户名</button>
      <div class="acct-sep"></div>
      <div class="form-l"><label>旧密码</label><el-input v-model="pwdForm.old" type="password" show-password class="ep-input" placeholder="当前密码" /></div>
      <div class="form-l"><label>新密码</label><el-input v-model="pwdForm.new" type="password" show-password class="ep-input" placeholder="至少 8 位" /></div>
      <div class="form-l"><label>确认</label><el-input v-model="pwdForm.confirm" type="password" show-password class="ep-input" :placeholder="pwdForm.new && pwdForm.confirm && pwdForm.new !== pwdForm.confirm ? '两次不一致' : '再次输入新密码'" /></div>
      <button class="btn primary" :disabled="pwdSaving" @click="savePwd">修改密码</button>
    </div>

    <div class="card">
      <div class="t">系统显示时区</div>
      <div class="d">系统各项时间的显示时区。</div>
      <el-select v-model="tz" filterable allow-create default-first-option
        placeholder="搜索城市或输入时区名（如 Asia/Shanghai）" style="width:100%" :disabled="saving" @change="pick">
        <el-option v-for="z in TZ_OPTIONS" :key="z.tz" :value="z.tz" :label="`${z.label}（${z.tz}）`" />
      </el-select>
    </div>

    <div v-if="isSuper && sched" class="card">
      <div class="t">任务调度</div>
      <div class="d">各自动任务的执行频率。</div>
      <div class="base-row">
        <span class="base-label">基础节拍</span>
        <input v-model.number="sched.base_minutes" type="number" min="1" class="base-input" />
        <span class="base-unit">分钟</span>
      </div>
      <div class="task-head"><span>任务</span><span>倍数</span><span>生效</span></div>
      <div v-for="k in TASK_ORDER" :key="k" class="task-row">
        <span class="task-name">{{ sched.task_labels?.[k] || k }}</span>
        <input v-model.number="sched.multipliers[k]" type="number" min="1" step="0.5" class="mult-input" />
        <span class="eff">{{ effOf(k) }} 分钟</span>
      </div>
      <div class="sentinel-sep"></div>
      <div class="task-row sentinel-row">
        <span class="task-name">{{ sched.task_labels?.sentinel || '哨兵巡逻' }}</span>
        <input v-model.number="sched.sentinel_minutes" type="number" min="1" max="10" class="mult-input" />
        <span class="eff">{{ sched.sentinel_minutes }} 分钟</span>
      </div>
      <button class="btn primary" :disabled="schedSaving" @click="saveSched">保存并生效</button>
    </div>

    <div v-if="isSuper" class="card">
      <div class="t">AI 配置</div>
      <div class="d">系统 AI 服务（KPI 纠偏、文案生成等）。OpenAI 兼容接口，支持 DeepSeek / OpenAI / Gemini。</div>
      <div class="form-l"><label>服务商</label>
        <el-select v-model="aiForm.ai_base_url" filterable allow-create default-first-option
          placeholder="选服务商或填 Base URL" style="flex:1">
          <el-option v-for="o in aiBaseOptions" :key="o.url" :value="o.url" :label="`${o.label}（${o.url}）`" />
        </el-select>
      </div>
      <div class="form-l"><label>API Key</label><input v-model="aiForm.ai_api_key" class="input" type="password" :placeholder="aiCfg.ai_api_key_set ? aiCfg.ai_api_key_masked : '填新 key 覆盖'" /></div>
      <div class="form-l"><label>Model</label>
        <el-select v-model="aiForm.ai_model" filterable allow-create default-first-option
          placeholder="选模型或填模型名" style="flex:1">
          <el-option v-for="m in aiModelOptions" :key="m" :value="m" :label="m" />
        </el-select>
      </div>
      <div style="display:flex;gap:8px;margin-top:14px">
        <button class="btn primary" :disabled="aiSaving" @click="saveAi">保存</button>
        <button class="btn" :disabled="aiTesting" @click="testAi">测试连接</button>
      </div>
    </div>

    <div v-if="isSuper" class="card">
      <div class="t">域名服务配置</div>
      <div class="d">落地页发布、域名导入用的域名服务凭据。Token 需有 Pages 编辑 + Zone 读取权限。</div>
      <div class="form-l"><label>账户 ID</label><input v-model="cfForm.cf_account_id" class="input" placeholder="账户 ID" /></div>
      <div class="form-l"><label>API Token</label><input v-model="cfForm.cf_api_token" class="input" type="password" :placeholder="cfCfg.cf_api_token_set ? cfCfg.cf_api_token_masked : '填新 token 覆盖'" /></div>
      <button class="btn primary" :disabled="cfSaving" @click="saveCf">保存</button>
    </div>

    <div v-if="isSuper" class="card">
      <div class="t">数据保留</div>
      <div class="d">各表老数据的保留天数，到期自动清理（每日 4:33）。填 0 = 永久保留。账户/落地页/配置类不清理。</div>
      <div class="ret-head"><span>数据</span><span>保留天数</span><span>说明</span></div>
      <div v-for="t in retention.tables" :key="t.key" class="ret-row" :class="{forever: t.days===0}">
        <span class="ret-name">{{ t.label }}</span>
        <input v-model.number="t.days" type="number" min="0" step="10" class="ret-input" />
        <span class="ret-hint">{{ t.days === 0 ? '永久保留' : `${t.days} 天前删除` }} · {{ t.key }}</span>
      </div>
      <div v-if="retention.last_run" class="ret-lastrun">上次清理：{{ retention.last_run.slice(0,19).replace('T',' ') }}</div>
      <div style="display:flex;gap:8px;margin-top:14px">
        <button class="btn primary" :disabled="retentionSaving" @click="saveRetention">保存策略</button>
        <button class="btn" :disabled="retentionRunning" @click="runRetentionNow">{{ retentionRunning ? '清理中…' : '立即清理一次' }}</button>
      </div>
    </div>

    <div v-if="isSuper" class="card">
      <div class="t">汇率（止损换算）</div>
      <div class="d">止损阈值按 USD 比较，非美元账户用此汇率换算。每日 3:07 自动从开放 API 拉实时汇率（避免 VND/IDR 漂移致 $20 阈值误判）。</div>
      <div class="fx-grid">
        <div v-for="r in fxRates" :key="r.code" class="fx-cell">
          <span class="fx-code">{{ r.code }}</span>
          <span class="fx-rate">{{ r.rate < 2 ? r.rate.toFixed(4) : r.rate.toLocaleString(undefined,{maximumFractionDigits:2}) }}</span>
        </div>
      </div>
      <div v-if="fxFetched" class="ret-lastrun">上次同步：{{ fxFetched }} UTC</div>
      <button class="btn" :disabled="fxLoading" @click="runFx" style="margin-top:14px">{{ fxLoading ? '拉取中…' : '立即同步汇率' }}</button>
    </div>
  </div>
</template>

<style scoped>
.page{display:flex;flex-direction:column;gap:14px}
.ep-input{flex:1}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:10px;padding:18px}
.t{font-size:15px;font-weight:600;color:var(--t1);margin-bottom:6px}
.d{font-size:12px;color:var(--t3);line-height:1.6;margin-bottom:14px}
.d b{color:var(--t2)}
.btn{margin-top:14px;padding:8px 16px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:6px;font-size:13px;cursor:pointer}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn:disabled{opacity:.5}

/* 调度 */
.base-row{display:flex;align-items:center;gap:8px;margin-bottom:14px;padding:10px 12px;background:var(--bg3);border-radius:6px}
.base-label{font-size:13px;color:var(--t1);font-weight:500}
.base-input{width:70px;padding:5px 8px;background:var(--bg2);border:1px solid var(--bd);border-radius:5px;color:var(--t1);font-size:13px}
.base-unit{font-size:12px;color:var(--t3)}
.task-head{display:grid;grid-template-columns:1fr 80px 90px;gap:8px;padding:4px 12px;font-size:10px;color:var(--t3);text-transform:uppercase}
.task-row{display:grid;grid-template-columns:1fr 80px 90px;gap:8px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--bd);font-size:13px}
.task-row:last-of-type{border-bottom:none}
.sentinel-sep{height:1px;background:var(--bd);margin:12px 0 0}
.sentinel-row{background:rgba(255,159,10,.04)}
.task-name{color:var(--t1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mult-input{width:70px;padding:4px 8px;background:var(--bg3);border:1px solid var(--bd);border-radius:5px;color:var(--t1);font-size:13px}
.eff{color:var(--t2);font-variant-numeric:tabular-nums;text-align:right}
.task-row.fixed .task-name{color:var(--t3)}
.fixed-tag{font-size:10px;padding:1px 6px;background:var(--bg3);border-radius:4px;color:var(--t3);width:fit-content}
.acct-sep{height:1px;background:var(--bd);margin:14px 0}
.form-l{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.form-l > label{font-size:12px;color:var(--t3);width:72px;text-align:right;flex-shrink:0}
.input{flex:1;padding:7px 10px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:13px;font-family:inherit;box-sizing:border-box}
.input:focus{border-color:var(--ac);outline:none}

/* 数据保留 */
.ret-head{display:grid;grid-template-columns:1fr 110px 1.2fr;gap:8px;padding:4px 12px;font-size:10px;color:var(--t3);text-transform:uppercase}
.ret-row{display:grid;grid-template-columns:1fr 110px 1.2fr;gap:8px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--bd);font-size:13px}
.ret-row:last-of-type{border-bottom:none}
.ret-row.forever{background:rgba(10,132,255,.04)}
.ret-name{color:var(--t1)}
.ret-input{width:80px;padding:4px 8px;background:var(--bg3);border:1px solid var(--bd);border-radius:5px;color:var(--t1);font-size:13px}
.ret-hint{color:var(--t3);font-size:11px;font-variant-numeric:tabular-nums}
.ret-lastrun{margin-top:10px;font-size:11px;color:var(--t3)}
.fx-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:6px}
.fx-cell{display:flex;justify-content:space-between;padding:7px 11px;background:var(--bg3);border-radius:6px;font-size:12px}
.fx-code{color:var(--t3);font-weight:600}
.fx-rate{color:var(--t1);font-variant-numeric:tabular-nums}
</style>
