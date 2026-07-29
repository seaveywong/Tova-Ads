<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { GET, PATCH, PUT, POST } from '../api'
import { isSuperadminSync } from '../router'
import { userTz, setUserTz } from '../composables/useTz'
import { ElMessage, ElMessageBox } from 'element-plus'

const { t } = useI18n()

// 时区
const TZ_OPTIONS = computed(() => [
  { tz: 'Asia/Shanghai', label: t('settings.tzShanghai') }, { tz: 'Asia/Hong_Kong', label: t('settings.tzHongKong') },
  { tz: 'Asia/Taipei', label: t('settings.tzTaipei') }, { tz: 'Asia/Tokyo', label: t('settings.tzTokyo') },
  { tz: 'Asia/Seoul', label: t('settings.tzSeoul') }, { tz: 'Asia/Singapore', label: t('settings.tzSingapore') },
  { tz: 'Asia/Bangkok', label: t('settings.tzBangkok') }, { tz: 'Asia/Jakarta', label: t('settings.tzJakarta') },
  { tz: 'Asia/Kolkata', label: t('settings.tzMumbai') }, { tz: 'America/Los_Angeles', label: t('settings.tzLosAngeles') },
  { tz: 'America/New_York', label: t('settings.tzNewYork') }, { tz: 'America/Sao_Paulo', label: t('settings.tzSaoPaulo') },
  { tz: 'Europe/London', label: t('settings.tzLondon') }, { tz: 'Europe/Paris', label: t('settings.tzParis') },
  { tz: 'Australia/Sydney', label: t('settings.tzSydney') }, { tz: 'UTC', label: 'UTC' },
])
const tz = ref(userTz.value)
const saving = ref(false)
const pick = async (z) => {
  saving.value = true
  try { await PATCH('/auth/me', { timezone: z }); setUserTz(z); ElMessage.success(t('settings.tzSwitched')) }
  catch (e) { ElMessage.error(t('settings.saveFail', { msg: e.message || '' })) }
  saving.value = false
}

// 调度（仅超管）
const isSuper = ref(isSuperadminSync())
const myPerms = ref([])
const copyText = async (text, tip) => {
  try { await navigator.clipboard.writeText(text); ElMessage.success(tip || t('common.copied')) }
  catch { ElMessage.error(t('settings.copyFailManual')) }
}
const sched = ref({
  base_minutes: 5,
  sentinel_minutes: 3,
  multipliers: { inspect: 1, watchdog: 2, account_sync: 6, budget: 3, reassociate: 24, subcode: 12 },
  effective: { inspect: 5, watchdog: 10, account_sync: 30, budget: 15, reassociate: 120, subcode: 60, sentinel: 3 },
  task_labels: {
    inspect: t('settings.taskInspect'), watchdog: t('settings.taskWatchdog'), account_sync: t('settings.taskAccountSync'),
    budget: t('settings.taskBudget'), reassociate: t('settings.taskReassociate'), subcode: t('settings.taskSubcode'),
    sentinel: t('settings.taskSentinel'),
  },
})
const schedSaving = ref(false)
const ka = ref({ enabled: false, budget_usd: 5, idle_days: 3, asset_prefix: 'YR' })
const kaSaving = ref(false)
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
    myPerms.value = me.permissions || []
    localStorage.setItem('tova_super', me.is_superadmin ? '1' : '0')
    setUserTz(me.timezone || 'Asia/Shanghai'); tz.value = me.timezone || 'Asia/Shanghai'
    acctEmail.value = me.email || ''
    if (isSuper.value) {
      try { sched.value = await GET('/settings/schedule') }
      catch { sched.value = null }
    }
    // 保活配置：有 ads.pause 权限就能看（团队 owner/operator）
    if ((myPerms.value || []).includes('ads.pause') || isSuper.value) {
      try { ka.value = await GET('/settings/keepalive') }
      catch { ka.value = { enabled: false, budget_usd: 5, idle_days: 3, asset_prefix: 'YR' } }
    }
  } catch {}
}
const saveSched = async () => {
  // P0 fix: 原 dirty 判断只看 inspect+sentinel，忽略 watchdog/account_sync/budget 等倍数变更 → 静默丢失
  // 移除 buggy dirty check，直接 PUT（后端幂等，无变更也不影响）
  const e = sched.value?.effective || {}
  if (Number(sched.value.sentinel_minutes) !== (e.sentinel ?? 0)) {
    try {
      await ElMessageBox.confirm(
        t('settings.sentinelChangeMsg', { n: sched.value.sentinel_minutes }),
        t('settings.sentinelChangeTitle'), { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') }
      )
    } catch { return }
  }
  // base_minutes 是所有任务频率的主基数（巡检/预算/看门狗/令牌都 = base × multiplier），改它影响全局
  if (Number(sched.value.base_minutes) !== Number(e.base ?? sched.value.base_minutes) && Number(e.base) > 0) {
    try {
      await ElMessageBox.confirm(
        t('settings.baseChangeMsg', { n: sched.value.base_minutes }),
        t('settings.baseChangeTitle'), { type: 'warning', confirmButtonText: t('settings.confirmChange'), cancelButtonText: t('common.cancel') }
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
    ElMessage.success(t('common.saved'))
  } catch (e) { ElMessage.error(t('settings.saveFail', { msg: e.message || '' })) }
  schedSaving.value = false
}

// AI 配置（超管）
const AI_PRESETS = {
  'https://api.deepseek.com/v1': { label: 'DeepSeek', models: ['deepseek-v4-flash', 'deepseek-v4-pro', 'deepseek-chat', 'deepseek-reasoner'] },
  'https://api.openai.com/v1': { label: 'OpenAI', models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini'] },
  'https://generativelanguage.googleapis.com/v1beta/openai': { label: t('settings.aiPresetGemini'), models: ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-2.5-pro'] },
}
const aiBaseOptions = Object.entries(AI_PRESETS).map(([url, p]) => ({ url, label: p.label }))
const aiCfg = ref({ ai_base_url: '', ai_api_key_masked: '', ai_api_key_set: false, ai_model: '',
                    ai_vision_base_url: '', ai_vision_api_key_masked: '', ai_vision_api_key_set: false, ai_vision_model: '' })
const aiForm = ref({ ai_base_url: '', ai_api_key: '', ai_model: '',
                     ai_vision_base_url: '', ai_vision_api_key: '', ai_vision_model: '' })
const aiModelOptions = computed(() => AI_PRESETS[aiForm.value.ai_base_url]?.models || [])
const aiVisionModelOptions = computed(() => AI_PRESETS[aiForm.value.ai_vision_base_url]?.models || [])
const aiSaving = ref(false)
const aiTesting = ref(false)
const aiVisionTesting = ref(false)
const loadAi = async () => {
  if (!isSuper.value) return
  try {
    aiCfg.value = await GET('/settings/ai')
    aiForm.value = {
      ai_base_url: aiCfg.value.ai_base_url, ai_api_key: '', ai_model: aiCfg.value.ai_model,
      ai_vision_base_url: aiCfg.value.ai_vision_base_url, ai_vision_api_key: '', ai_vision_model: aiCfg.value.ai_vision_model,
    }
  } catch {}
}
const saveAi = async () => {
  aiSaving.value = true
  try {
    const body = {}
    if (aiForm.value.ai_base_url && aiForm.value.ai_base_url !== aiCfg.value.ai_base_url) body.ai_base_url = aiForm.value.ai_base_url
    if (aiForm.value.ai_api_key) body.ai_api_key = aiForm.value.ai_api_key
    if (aiForm.value.ai_model && aiForm.value.ai_model !== aiCfg.value.ai_model) body.ai_model = aiForm.value.ai_model
    if (aiForm.value.ai_vision_base_url && aiForm.value.ai_vision_base_url !== aiCfg.value.ai_vision_base_url) body.ai_vision_base_url = aiForm.value.ai_vision_base_url
    if (aiForm.value.ai_vision_api_key) body.ai_vision_api_key = aiForm.value.ai_vision_api_key
    if (aiForm.value.ai_vision_model && aiForm.value.ai_vision_model !== aiCfg.value.ai_vision_model) body.ai_vision_model = aiForm.value.ai_vision_model
    if (!Object.keys(body).length) { ElMessage.info(t('settings.noChange')); aiSaving.value = false; return }
    await PUT('/settings/ai', body)
    ElMessage.success(t('common.saved'))
    await loadAi()
  } catch (e) { ElMessage.error(t('settings.saveFail', { msg: e.message || '' })) }
  aiSaving.value = false
}
const testAi = async () => {
  aiTesting.value = true
  try {
    const r = await POST('/settings/ai/test', {})
    r.ok ? ElMessage.success(t('settings.textModelOk', { detail: r.detail })) : ElMessage.error(t('settings.textModelFail', { detail: r.detail }))
  } catch (e) { ElMessage.error(t('settings.testFail')) }
  aiTesting.value = false
}
const testVisionAi = async () => {
  aiVisionTesting.value = true
  try {
    const r = await POST('/settings/ai/test?vision=true', {})
    r.ok ? ElMessage.success(t('settings.visionModelOk', { detail: r.detail })) : ElMessage.error(t('settings.visionModelFail', { detail: r.detail }))
  } catch (e) { ElMessage.error(t('settings.testFail')) }
  aiVisionTesting.value = false
}

// 账户（用户名 + 改密码）
const acctEmail = ref('')
const acctSaving = ref(false)
const pwdForm = ref({ old: '', new: '', confirm: '' })
const pwdSaving = ref(false)
const saveEmail = async () => {
  if (!acctEmail.value.trim() || !acctEmail.value.includes('@')) return ElMessage.warning(t('settings.invalidEmail'))
  acctSaving.value = true
  try { await PATCH('/auth/me/email', { email: acctEmail.value.trim() }); ElMessage.success(t('settings.emailUpdated')) }
  catch (e) { ElMessage.error(t('settings.opFail', { msg: e.message || '' })) }
  acctSaving.value = false
}
const savePwd = async () => {
  if (!pwdForm.value.old || !pwdForm.value.new) return ElMessage.warning(t('settings.fillOldNewPwd'))
  if (pwdForm.value.new !== pwdForm.value.confirm) return ElMessage.error(t('settings.pwdMismatch'))
  if (pwdForm.value.new.length < 8) return ElMessage.error(t('settings.pwdMinLen'))
  pwdSaving.value = true
  try { await PUT('/auth/me/password', { old_password: pwdForm.value.old, new_password: pwdForm.value.new }); ElMessage.success(t('settings.pwdUpdatedRelogin')); pwdForm.value = { old: '', new: '', confirm: '' } }
  catch (e) { ElMessage.error(t('settings.opFail', { msg: e.message || '' })) }
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
    if (!Object.keys(body).length) { ElMessage.info(t('settings.noChange')); cfSaving.value = false; return }
    await PUT('/settings/cf', body)
    ElMessage.success(t('common.saved'))
    await loadCf()
  } catch (e) { ElMessage.error(t('settings.saveFail', { msg: e.message || '' })) }
  cfSaving.value = false
}
// TG OAuth 通知绑定
const tgBot = ref({ configured: false, bot_username: '' })
const userTg = ref({ bound: false })
const testTgLoading = ref(false)
const tgManual = ref({ chat_id: '', saving: false })
const tgBindLink = ref('')
const loadTg = async () => {
  try {
    const [botInfo, userBinding] = await Promise.all([
      GET('/notifications/tg/bot-info'),
      GET('/notifications/tg/user-binding'),
    ])
    tgBot.value = botInfo
    userTg.value = userBinding
    if (botInfo.configured && !userBinding.bound) {
      try { const r = await GET('/notifications/tg/bind-link'); tgBindLink.value = r.url } catch {}
      if (botInfo.bot_username) {
        nextTick(() => {
          const el = document.getElementById('tg-widget')
          if (!el || el.firstChild) return
          const s = document.createElement('script')
          s.async = true
          s.src = 'https://telegram.org/js/telegram-widget.js?22'
          s.setAttribute('data-telegram-login', botInfo.bot_username)
          s.setAttribute('data-size', 'large')
          s.setAttribute('data-onauth', 'onTelegramAuth(user)')
          s.setAttribute('data-request-access', 'write')
          el.appendChild(s)
          window.onTelegramAuth = async (u) => {
            try {
              await POST('/notifications/tg/oauth-callback', u)
              ElMessage.success(t('settings.tgBindOk', { name: u.username || u.id }))
              userTg.value = await GET('/notifications/tg/user-binding')
            } catch (e) { ElMessage.error(e.message || t('settings.tgBindFail')) }
          }
        })
      }
    }
  } catch {}
}
const testUserTg = async () => {
  testTgLoading.value = true
  try { await POST('/notifications/tg/user-test'); ElMessage.success(t('settings.tgTestSentUser')) }
  catch (e) { ElMessage.error(e.message || t('settings.sendFail')) }
  testTgLoading.value = false
}
const testTenantTg = async () => {
  testTgLoading.value = true
  try { await POST('/notifications/tg/test'); ElMessage.success(t('settings.tgTestSentTenant')) }
  catch (e) { ElMessage.error(e.message || t('settings.tgTestFailTenant')) }
  testTgLoading.value = false
}
const bindTgManual = async () => {
  if (!tgManual.value.chat_id.trim()) return ElMessage.warning(t('settings.fillChatId'))
  tgManual.value.saving = true
  try {
    await POST('/notifications/tg/user-binding', { bot_token: '__use_tenant_bot__', chat_id: tgManual.value.chat_id.trim() })
    ElMessage.success(t('settings.bound'))
    tgManual.value.chat_id = ''
    userTg.value = await GET('/notifications/tg/user-binding')
  } catch (e) { ElMessage.error(e.message || t('settings.bindFail')) }
  tgManual.value.saving = false
}
const unbindTg = async () => {
  try {
    await ElMessageBox.confirm(t('settings.tgUnbindConfirm'), t('common.confirm'), { type: 'warning' })
    // 用空 chat_id 触发后端删除/解绑（或直接 DELETE，但后端没有 DELETE 端点，用空值覆盖）
    await POST('/notifications/tg/user-binding', { bot_token: '__use_tenant_bot__', chat_id: '' })
    ElMessage.success(t('settings.tgUnbound'))
    userTg.value = await GET('/notifications/tg/user-binding')
  } catch (e) { if (e !== 'cancel') ElMessage.error(e.message || t('common.fail')) }
}
onMounted(async () => { await loadSched(); await loadAi(); await loadCf(); await loadRetention(); await loadFx(); await loadTg() })

// 汇率（超管）—— 止损 to_usd 用，每日自动刷新
const fxRates = ref([])
const fxLoading = ref(false)
const loadFx = async () => {
  if (!isSuper.value) return
  try { const r = await GET('/settings/fx'); fxRates.value = r.rates || [] } catch {}
}
const runFx = async () => {
  fxLoading.value = true
  try { const r = await POST('/settings/fx/run'); ElMessage.success(t('settings.fxUpdated', { n: r.updated })); await loadFx() }
  catch (e) { ElMessage.error(t('settings.fetchFail', { msg: e.message || '' })) }
  fxLoading.value = false
}
const fxFetched = computed(() => fxRates.value[0]?.fetched_at?.slice(0,16).replace('T',' ') || '')

// 数据保留（超管）—— 各表老数据保留天数，0=永久
const retention = ref({ tables: [], last_run: '' })
const retentionSaving = ref(false)
const retentionRunning = ref(false)
const origDays = ref({})  // 原始保留天数快照，用于检测"缩小=删数据"
const loadRetention = async () => {
  if (!isSuper.value) return
  try {
    retention.value = await GET('/settings/retention')
    origDays.value = {}; (retention.value.tables || []).forEach(t => { origDays.value[t.key] = t.days })
  } catch {}
}
const saveRetention = async () => {
  // 检测"缩小保留天数"——下次清理会删掉超龄数据（破坏性）
  const shrunk = (retention.value.tables || []).filter(t => {
    const o = origDays.value[t.key]; return o !== undefined && Number(t.days) < Number(o) && Number(o) > 0
  })
  if (shrunk.length) {
    const detail = shrunk.map(tb => t('settings.retentionShrinkItem', { label: tb.label, from: origDays.value[tb.key], to: tb.days })).join('、')
    try {
      await ElMessageBox.confirm(
        t('settings.retentionShrinkMsg', { detail }),
        t('settings.retentionShrinkTitle'), { type: 'warning', confirmButtonText: t('settings.confirmShrink'), cancelButtonText: t('common.cancel') }
      )
    } catch { return }
  }
  retentionSaving.value = true
  try {
    const days = {}
    retention.value.tables.forEach(tb => { days[tb.key] = tb.days })
    retention.value = await PUT('/settings/retention', { days })
    origDays.value = {}; (retention.value.tables || []).forEach(tb => { origDays.value[tb.key] = tb.days })
    ElMessage.success(t('settings.retentionSaved'))
  } catch (e) { ElMessage.error(t('settings.saveFail', { msg: e.message || '' })) }
  retentionSaving.value = false
}
const runRetentionNow = async () => {
  retentionRunning.value = true
  try {
    const r = await POST('/settings/retention/run')
    const parts = Object.entries(r).map(([k, v]) => t('settings.retentionCleanItem', { table: k, n: v.deleted ?? 0 }))
    ElMessage.success(t('settings.retentionCleanDone', { detail: parts.join(' ') }))
    await loadRetention()
  } catch (e) { ElMessage.error(t('settings.cleanFail', { msg: e.message || '' })) }
  retentionRunning.value = false
}
const saveKeepalive = async () => {
  kaSaving.value = true
  try {
    ka.value = await PUT('/settings/keepalive', { ...ka.value })
    ElMessage.success(ka.value.enabled ? t('settings.keepaliveEnabled') : t('common.saved'))
  } catch (e) { ElMessage.error(t('settings.saveFail', { msg: e.message || '' })) }
  kaSaving.value = false
}
</script>

<template>
  <div class="page">
    <div class="card">
      <div class="t">{{ t('settings.accountTitle') }}</div>
      <div class="d">{{ t('settings.accountDesc') }}</div>
      <div class="form-l"><label>{{ t('settings.username') }}</label><input v-model="acctEmail" class="input" :placeholder="t('settings.loginEmailPh')" /></div>
      <button class="btn primary" :disabled="acctSaving" @click="saveEmail">{{ t('settings.saveUsername') }}</button>
      <div class="acct-sep"></div>
      <div class="form-l"><label>{{ t('settings.oldPwd') }}</label><el-input v-model="pwdForm.old" type="password" autocomplete="current-password" show-password class="ep-input" :placeholder="t('settings.currentPwdPh')" /></div>
      <div class="form-l"><label>{{ t('settings.newPwd') }}</label><el-input v-model="pwdForm.new" type="password" autocomplete="new-password" show-password class="ep-input" :placeholder="t('settings.pwdMin8Ph')" /></div>
      <div class="form-l"><label>{{ t('settings.confirm') }}</label><el-input v-model="pwdForm.confirm" type="password" autocomplete="new-password" show-password class="ep-input" :placeholder="pwdForm.new && pwdForm.confirm && pwdForm.new !== pwdForm.confirm ? t('settings.pwdMismatchPh') : t('settings.reenterNewPwdPh')" /></div>
      <button class="btn primary" :disabled="pwdSaving" @click="savePwd">{{ t('settings.changePwd') }}</button>
    </div>

    <div class="card">
      <div class="t">{{ t('settings.tzTitle') }}</div>
      <div class="d">{{ t('settings.tzDesc') }}</div>
      <el-select v-model="tz" filterable allow-create default-first-option
        :placeholder="t('settings.tzSearchPh')" style="width:100%" :disabled="saving" @change="pick">
        <el-option v-for="z in TZ_OPTIONS" :key="z.tz" :value="z.tz" :label="t('settings.tzOption', { label: z.label, tz: z.tz })" />
      </el-select>
    </div>

    <div v-if="isSuper && sched" class="card">
      <div class="t">{{ t('settings.scheduleTitle') }}</div>
      <div class="d">{{ t('settings.scheduleDesc') }}</div>
      <div class="base-row">
        <span class="base-label">{{ t('settings.baseBeat') }}</span>
        <input v-model.number="sched.base_minutes" type="number" min="1" class="base-input" />
        <span class="base-unit">{{ t('settings.minutes') }}</span>
      </div>
      <div class="task-head"><span>{{ t('settings.taskCol') }}</span><span>{{ t('settings.multiplierCol') }}</span><span>{{ t('settings.effectiveCol') }}</span></div>
      <div v-for="k in TASK_ORDER" :key="k" class="task-row">
        <span class="task-name">{{ sched.task_labels?.[k] || k }}</span>
        <input v-model.number="sched.multipliers[k]" type="number" min="1" step="0.5" class="mult-input" />
        <span class="eff">{{ t('settings.minSuffix', { n: effOf(k) }) }}</span>
      </div>
      <div class="sentinel-sep"></div>
      <div class="task-row sentinel-row">
        <span class="task-name">{{ sched.task_labels?.sentinel || t('settings.taskSentinel') }}</span>
        <input v-model.number="sched.sentinel_minutes" type="number" min="1" max="10" class="mult-input" />
        <span class="eff">{{ t('settings.minSuffix', { n: sched.sentinel_minutes }) }}</span>
      </div>
      <button class="btn primary" :disabled="schedSaving" @click="saveSched">{{ t('settings.saveAndApply') }}</button>
    </div>

    <div v-if="isSuper" class="card">
      <div class="t">{{ t('settings.aiTitle') }}</div>
      <div class="d">{{ t('settings.aiDesc') }}</div>
      <div class="sub-t">{{ t('settings.aiTextModelTitle') }}</div>
      <div class="form-l"><label>{{ t('settings.provider') }}</label>
        <el-select v-model="aiForm.ai_base_url" filterable allow-create default-first-option
          :placeholder="t('settings.providerPh')" style="flex:1">
          <el-option v-for="o in aiBaseOptions" :key="o.url" :value="o.url" :label="t('settings.providerOpt', { label: o.label, url: o.url })" />
        </el-select>
      </div>
      <div class="form-l"><label>API Key</label><input v-model="aiForm.ai_api_key" class="input" type="password" autocomplete="new-password" :placeholder="aiCfg.ai_api_key_set ? aiCfg.ai_api_key_masked : t('settings.fillNewKeyPh')" /></div>
      <div class="form-l"><label>Model</label>
        <el-select v-model="aiForm.ai_model" filterable allow-create default-first-option
          :placeholder="t('settings.modelPh')" style="flex:1">
          <el-option v-for="m in aiModelOptions" :key="m" :value="m" :label="m" />
        </el-select>
      </div>
      <div class="sub-t" style="margin-top:18px">{{ t('settings.aiVisionModelTitle') }}</div>
      <div class="d" style="margin-bottom:6px">{{ t('settings.aiVisionDesc') }}</div>
      <div class="form-l"><label>{{ t('settings.provider') }}</label>
        <el-select v-model="aiForm.ai_vision_base_url" filterable allow-create default-first-option
          :placeholder="t('settings.providerPh')" style="flex:1">
          <el-option v-for="o in aiBaseOptions" :key="o.url" :value="o.url" :label="t('settings.providerOpt', { label: o.label, url: o.url })" />
        </el-select>
      </div>
      <div class="form-l"><label>API Key</label><input v-model="aiForm.ai_vision_api_key" class="input" type="password" autocomplete="new-password" :placeholder="aiCfg.ai_vision_api_key_set ? aiCfg.ai_vision_api_key_masked : t('settings.fillNewKeyPh')" /></div>
      <div class="form-l"><label>Model</label>
        <el-select v-model="aiForm.ai_vision_model" filterable allow-create default-first-option
          :placeholder="t('settings.modelPh')" style="flex:1">
          <el-option v-for="m in aiVisionModelOptions" :key="m" :value="m" :label="m" />
        </el-select>
      </div>
      <div style="display:flex;gap:8px;margin-top:14px">
        <button class="btn primary" :disabled="aiSaving" @click="saveAi">{{ t('common.save') }}</button>
        <button class="btn" :disabled="aiTesting" @click="testAi">{{ t('settings.testText') }}</button>
        <button class="btn" :disabled="aiVisionTesting" @click="testVisionAi">{{ t('settings.testVision') }}</button>
      </div>
    </div>

    <div v-if="isSuper" class="card">
      <div class="t">{{ t('settings.cfTitle') }}</div>
      <div class="d">{{ t('settings.cfDesc') }}</div>
      <div class="form-l"><label>{{ t('settings.accountId') }}</label><input v-model="cfForm.cf_account_id" class="input" :placeholder="t('settings.accountId')" /></div>
      <div class="form-l"><label>API Token</label><input v-model="cfForm.cf_api_token" class="input" type="password" :placeholder="cfCfg.cf_api_token_set ? cfCfg.cf_api_token_masked : t('settings.fillNewTokenPh')" /></div>
      <button class="btn primary" :disabled="cfSaving" @click="saveCf">{{ t('common.save') }}</button>
    </div>

    <div v-if="isSuper" class="card">
      <div class="t">{{ t('settings.retentionTitle') }}</div>
      <div class="d">{{ t('settings.retentionDesc') }}</div>
      <div class="ret-head"><span>{{ t('settings.retDataCol') }}</span><span>{{ t('settings.retDaysCol') }}</span><span>{{ t('settings.retDescCol') }}</span></div>
      <div v-for="row in retention.tables" :key="row.key" class="ret-row" :class="{forever: row.days===0}">
        <span class="ret-name">{{ row.label }}</span>
        <input v-model.number="row.days" type="number" min="0" step="10" class="ret-input" />
        <span class="ret-hint">{{ row.days === 0 ? t('settings.foreverKeep') : t('settings.delBefore', { n: row.days }) }} · {{ row.key }}</span>
      </div>
      <div v-if="retention.last_run" class="ret-lastrun">{{ t('settings.lastClean', { ts: retention.last_run.slice(0,19).replace('T',' ') }) }}</div>
      <div style="display:flex;gap:8px;margin-top:14px">
        <button class="btn primary" :disabled="retentionSaving" @click="saveRetention">{{ t('settings.savePolicy') }}</button>
        <button class="btn" :disabled="retentionRunning" @click="runRetentionNow">{{ retentionRunning ? t('settings.cleaning') : t('settings.cleanNow') }}</button>
      </div>
    </div>

    <div v-if="isSuper" class="card">
      <div class="t">{{ t('settings.fxTitle') }}</div>
      <div class="d">{{ t('settings.fxDesc') }}</div>
      <div class="fx-grid">
        <div v-for="r in fxRates" :key="r.code" class="fx-cell">
          <span class="fx-code">{{ r.code }}</span>
          <span class="fx-rate">{{ r.rate < 2 ? r.rate.toFixed(4) : r.rate.toLocaleString(undefined,{maximumFractionDigits:2}) }}</span>
        </div>
      </div>
      <div v-if="fxFetched" class="ret-lastrun">{{ t('settings.lastSync', { ts: fxFetched }) }}</div>
      <button class="btn" :disabled="fxLoading" @click="runFx" style="margin-top:14px">{{ fxLoading ? t('settings.fetching') : t('settings.syncFxNow') }}</button>
    </div>

    <div class="card">
      <div class="t">{{ t('settings.tgTitle') }}</div>
      <div class="d" style="margin-bottom:10px">{{ t('settings.tgDesc') }}</div>

      <!-- 已绑定 -->
      <div v-if="userTg.bound" class="tg-status">
        <span class="tg-bound-badge">{{ t('settings.tgBoundBadge', { id: userTg.chat_id_masked }) }}</span>
        <button class="btn" :disabled="testTgLoading" @click="testUserTg">{{ testTgLoading ? t('settings.sending') : t('settings.sendTestMsg') }}</button>
        <button class="btn tg-unbind-btn" @click="unbindTg">{{ t('settings.unbind') }}</button>
      </div>

      <!-- 未绑定 -->
      <div v-else class="tg-bind-area">
        <a v-if="tgBindLink" :href="tgBindLink" target="_blank" rel="noopener" class="btn primary tg-bind-btn">{{ t('settings.bindTelegram') }}</a>
        <span v-if="tgBindLink" class="tg-copy-link" @click="copyText(tgBindLink, t('settings.bindLinkCopied'))">{{ t('settings.cannotOpenCopy') }}</span>
        <span v-if="!tgBot.configured" class="tg-warn">{{ t('settings.tgBotNotConfigured') }}</span>
      </div>

      <!-- 验证 Bot 配置（owner/超管） -->
      <div v-if="(isSuper || (myPerms || []).includes('members.manage')) && tgBot.configured" class="tg-verify">
        <button class="btn" :disabled="testTgLoading" @click="testTenantTg">{{ testTgLoading ? t('settings.sending') : t('settings.verifyBotConfig') }}</button>
        <span class="tg-verify-hint">{{ t('settings.verifyBotHint') }}</span>
      </div>
    </div>

    <div v-if="isSuper || (myPerms || []).includes('ads.pause')" class="card">
      <div class="t">{{ t('settings.keepaliveTitle') }}</div>
      <div class="d">{{ t('settings.keepaliveDesc') }}</div>
      <div class="ka-switch-row">
        <el-switch v-model="ka.enabled" active-color="#0a84ff" inactive-color="#3a3a5c" size="small" />
        <span class="ka-switch-label">{{ ka.enabled ? t('settings.kaOnLabel') : t('settings.kaOffLabel') }}</span>
      </div>
      <div class="ka-grid">
        <div class="ka-field"><label>{{ t('settings.kaBudget') }}</label><div class="ka-input-wrap"><input v-model.number="ka.budget_usd" type="number" min="1" step="1" class="ka-input" /><span class="ka-unit">$</span></div></div>
        <div class="ka-field"><label>{{ t('settings.kaTriggerDays') }}</label><div class="ka-input-wrap"><input v-model.number="ka.idle_days" type="number" min="1" step="1" class="ka-input" /><span class="ka-unit">{{ t('settings.days') }}</span></div></div>
        <div class="ka-field"><label>{{ t('settings.kaAssetPrefix') }}</label><div class="ka-input-wrap"><input v-model="ka.asset_prefix" class="ka-input" style="width:100px" /></div></div>
      </div>
      <div class="ka-actions">
        <button class="btn primary" :disabled="kaSaving" @click="saveKeepalive">{{ kaSaving ? t('settings.saving') : t('common.save') }}</button>
      </div>
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
.sub-t{font-size:13px;font-weight:600;color:var(--t2);margin-bottom:8px;padding-left:8px;border-left:2px solid var(--ac)}
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

/* 保活配置 */
.ka-switch-row{display:flex;align-items:center;gap:8px;margin-bottom:14px;padding:10px 12px;background:var(--bg3);border-radius:8px}
.ka-switch-label{font-size:13px;color:var(--t2)}
.ka-grid{display:flex;gap:20px;flex-wrap:wrap;align-items:flex-end}
.ka-field{display:flex;flex-direction:column;gap:4px}
.ka-field label{font-size:11px;color:var(--t3)}
.ka-input-wrap{display:flex;align-items:center;gap:4px}
.ka-input{width:70px;padding:6px 8px;border:1px solid var(--bd);border-radius:6px;background:var(--bg2);color:var(--t1);font-size:13px}
.ka-unit{font-size:12px;color:var(--t3)}
.ka-actions{margin-top:16px}

/* Telegram 通知 */
.tg-status{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:4px}
.tg-bind-area{margin-top:4px;display:flex;flex-direction:column;gap:6px;align-items:flex-start}
.tg-bind-btn{text-decoration:none;margin-top:0}
.tg-copy-link{font-size:12px;color:var(--ac);cursor:pointer;text-decoration:underline}
.tg-copy-link:hover{opacity:.8}
.tg-bound-badge{color:var(--success);font-size:13px;font-weight:500}
.tg-unbind-btn{color:var(--error);border-color:var(--error)}
.tg-warn{color:var(--warning);font-size:12px}
.tg-verify{margin-top:10px;padding-top:10px;border-top:1px solid var(--bd);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tg-verify .btn{margin-top:0}
.tg-verify-hint{font-size:11px;color:var(--t3)}
</style>
