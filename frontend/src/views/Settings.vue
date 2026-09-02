<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { GET, PATCH, PUT, POST, DELETE } from '../api'
import { isSuperadminSync } from '../router'
import { userTz, setUserTz } from '../composables/useTz'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fbErrorText } from '../composables/useFbError'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

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
  task_labels: {},   // 占位——真实标签走 taskLabel(k)（locale 响应，一次性求值会冻结）
})
const _TASK_LABEL_KEYS = { inspect: 'settings.taskInspect', watchdog: 'settings.taskWatchdog', account_sync: 'settings.taskAccountSync', budget: 'settings.taskBudget', reassociate: 'settings.taskReassociate', subcode: 'settings.taskSubcode', sentinel: 'settings.taskSentinel' }
const taskLabel = (k) => t(_TASK_LABEL_KEYS[k] || '') || k
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

// 巡检与告警调优（超管）—— 并发/学习期/风暴上限三旋钮
const gt = ref({ guard_concurrency: null, guard_learning_hours: null, notify_storm_cap: null, defaults: {} })
const gtSaving = ref(false)
const GT_ROWS = [
  { key: 'guard_concurrency', labelKey: 'settings.gtConc', hintKey: 'settings.gtConcHint', min: 1, max: 8 },
  { key: 'guard_learning_hours', labelKey: 'settings.gtLearn', hintKey: 'settings.gtLearnHint', min: 0, max: 720 },
  { key: 'notify_storm_cap', labelKey: 'settings.gtStorm', hintKey: 'settings.gtStormHint', min: 0, max: 1000 },
]
const loadGuardTuning = async () => {
  if (!isSuper.value) return
  try { gt.value = await GET('/settings/guard-tuning') } catch {}
}
const saveGuardTuning = async () => {
  for (const r of GT_ROWS) {
    const v = Number(gt.value[r.key])
    if (gt.value[r.key] === '' || gt.value[r.key] === null || Number.isNaN(v))
      return ElMessage.warning(t('settings.gtFillAll'))
    if (v < r.min || v > r.max) return ElMessage.warning(t('settings.gtRange', { min: r.min, max: r.max }))
  }
  gtSaving.value = true
  try {
    gt.value = await PUT('/settings/guard-tuning', {
      guard_concurrency: Number(gt.value.guard_concurrency),
      guard_learning_hours: Number(gt.value.guard_learning_hours),
      notify_storm_cap: Number(gt.value.notify_storm_cap),
    })
    ElMessage.success(t('common.saved'))
  } catch (e) { ElMessage.error(t('settings.saveFail', { msg: e.message || '' })) }
  gtSaving.value = false
}

// AI 配置（超管）
const AI_PRESETS = {
  'https://api.deepseek.com/v1': { label: 'DeepSeek', models: ['deepseek-v4-flash', 'deepseek-v4-pro', 'deepseek-chat', 'deepseek-reasoner'] },
  'https://api.openai.com/v1': { label: 'OpenAI', models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini'] },
  'https://generativelanguage.googleapis.com/v1beta/openai': { label: t('settings.aiPresetGemini'), models: ['gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-pro'] },
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
const emailOldPwd = ref('')   // 改登录邮箱需旧密码确认（防会话劫持接管）——后端必查
const pwdForm = ref({ old: '', new: '', confirm: '' })
const pwdSaving = ref(false)
const saveEmail = async () => {
  if (!acctEmail.value.trim() || !acctEmail.value.includes('@')) return ElMessage.warning(t('settings.invalidEmail'))
  if (!emailOldPwd.value) return ElMessage.warning(t('settings.fillOldPwdForEmail'))
  acctSaving.value = true
  try { await PATCH('/auth/me/email', { email: acctEmail.value.trim(), old_password: emailOldPwd.value }); ElMessage.success(t('settings.emailUpdated')); emailOldPwd.value = '' }
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
const cfCfg = ref({ cf_api_token_masked: '', cf_api_token_set: false, cf_account_id: '', cf_email_token_masked: '', cf_email_token_set: false })
const cfForm = ref({ cf_api_token: '', cf_account_id: '', cf_email_token: '' })
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
    if (cfForm.value.cf_email_token) body.cf_email_token = cfForm.value.cf_email_token
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
const whCfg = ref({ public_url: '', verify_token_masked: '', verify_token_set: false, verify_token_is_default: true, active_apps: 0, app_names: [] })
const whForm = ref({ verify_token: '' })
const whSaving = ref(false)
const loadWebhook = async () => {
  if (!isSuper.value) return
  try {
    whCfg.value = await GET('/settings/webhook')
    whForm.value = { verify_token: '' }
  } catch {}
}
const saveWebhook = async () => {
  whSaving.value = true
  try {
    await PUT('/settings/webhook', { verify_token: whForm.value.verify_token })
    ElMessage.success(t('common.saved'))
    await loadWebhook()
  } catch (e) { ElMessage.error(t('settings.saveFail', { msg: e.message || '' })) }
  whSaving.value = false
}
const resetWebhookToken = async () => {
  whSaving.value = true
  try {
    await PUT('/settings/webhook', { verify_token: '' })
    ElMessage.success(t('settings.whTokenReset'))
    await loadWebhook()
  } catch (e) { ElMessage.error(t('settings.saveFail', { msg: e.message || '' })) }
  whSaving.value = false
}

// 邮箱转发（超管）—— CF Email Routing：目的地邮箱（CF 发验证邮件）+ 别名映射
const em = ref({ domain: '', status: 'unconfigured', dns_ready: false, missing_dns: [], addresses: [], routes: [] })
const emLoading = ref(false)
const emEnabling = ref(false)
const emAddrForm = ref('')
const emAddrSaving = ref(false)
const emRouteForm = ref({ alias: '', destination_email: '' })
const emRouteSaving = ref(false)
const emVerifiedAddrs = computed(() => (em.value.addresses || []).filter(a => a.verified))
const emStatusMeta = computed(() => ({
  enabled: { cls: 'ok', label: t('settings.emStatusEnabled') },
  disabled: { cls: 'warn', label: t('settings.emStatusDisabled') },
}[em.value.status] || { cls: 'warn', label: t('settings.emStatusUnconfigured') }))
const loadEmailRouting = async () => {
  if (!isSuper.value) return
  emLoading.value = true
  try { em.value = await GET('/settings/email-routing') }
  catch (e) { ElMessage.error(e.message || t('common.fail')) }
  emLoading.value = false
}
const enableEmailRouting = async () => {
  emEnabling.value = true
  try {
    const r = await POST('/settings/email-routing/enable', {})
    ElMessage.success(t('settings.emEnabledMsg', { n: r.dns_added ?? 0 }))
    await loadEmailRouting()
  } catch (e) { ElMessage.error(e.message || t('common.fail')) }
  emEnabling.value = false
}
const addEmAddress = async () => {
  const email = emAddrForm.value.trim()
  if (!email || !email.includes('@')) return ElMessage.warning(t('settings.emAddrInvalid'))
  emAddrSaving.value = true
  try {
    const r = await POST('/settings/email-routing/destinations', { email })
    ElMessage[r.existed ? 'info' : 'success'](r.existed ? t('settings.emAddrExisted') : t('settings.emAddrAdded'))
    emAddrForm.value = ''
    await loadEmailRouting()
  } catch (e) { ElMessage.error(e.message || t('common.fail')) }
  emAddrSaving.value = false
}
const delEmAddress = async (a) => {
  try {
    await ElMessageBox.confirm(t('settings.emAddrDelConfirm', { email: a.email }), t('common.confirm'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
  } catch { return }
  try {
    await DELETE(`/settings/email-routing/destinations/${a.id}`)
    ElMessage.success(t('settings.emDeleted'))
    await loadEmailRouting()
  } catch (e) { ElMessage.error(e.message || t('common.fail')) }
}
const addEmRoute = async () => {
  const alias = emRouteForm.value.alias.trim().toLowerCase()
  if (!alias) return ElMessage.warning(t('settings.emAliasRequired'))
  if (!emRouteForm.value.destination_email) return ElMessage.warning(t('settings.emDestRequired'))
  emRouteSaving.value = true
  try {
    await POST('/settings/email-routing/routes', { alias, destination_email: emRouteForm.value.destination_email })
    ElMessage.success(t('settings.emRouteAdded'))
    emRouteForm.value = { alias: '', destination_email: '' }
    await loadEmailRouting()
  } catch (e) { ElMessage.error(e.message || t('common.fail')) }
  emRouteSaving.value = false
}
const toggleEmRoute = async (r) => {
  try { await PATCH(`/settings/email-routing/routes/${r.id}`, { enabled: !r.enabled }) }
  catch (e) { ElMessage.error(e.message || t('common.fail')) }
  await loadEmailRouting()
}
const delEmRoute = async (r) => {
  try {
    await ElMessageBox.confirm(t('settings.emRouteDelConfirm', { alias: r.alias_email }), t('common.confirm'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
  } catch { return }
  try {
    await DELETE(`/settings/email-routing/routes/${r.id}`)
    ElMessage.success(t('settings.emDeleted'))
    await loadEmailRouting()
  } catch (e) { ElMessage.error(e.message || t('common.fail')) }
}

onMounted(async () => { await Promise.all([loadSched(), loadAi(), loadCf(), loadWebhook(), loadRetention(), loadFx(), loadTg(), loadGuardTuning(), loadEmailRouting()]); applySectionFromUrl() })   // 并行——原 7 串行吃满 7 个 RTT；完成后按 URL ?sec= 定位分区

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
        t('settings.retentionShrinkTitle'), { type: 'warning', confirmButtonText: t('settings.confirmShrink'), cancelButtonText: t('common.cancel'), confirmButtonClass: 'el-button--danger' }
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
const kaRunning = ref(false)

// ── 锚点导航（sticky 横条，点跳对应卡片；滚动高亮当前区）──
const activeSection = ref('sec-account')
const anchorSections = computed(() => {
  const secs = [
    { id: 'sec-account', label: t('settings.accountTitle') },
    { id: 'sec-tz', label: t('settings.tzTitle') },
  ]
  if (isSuper.value) {
    secs.push({ id: 'sec-schedule', label: t('settings.scheduleTitle') })
    secs.push({ id: 'sec-guard-tuning', label: t('settings.gtTitle') })
    secs.push({ id: 'sec-ai', label: t('settings.aiTitle') })
    secs.push({ id: 'sec-cf', label: t('settings.cfTitle') })
    secs.push({ id: 'sec-email', label: t('settings.emTitle') })
    secs.push({ id: 'sec-webhook', label: t('settings.whTitle') })
    secs.push({ id: 'sec-retention', label: t('settings.retentionTitle') })
    secs.push({ id: 'sec-fx', label: t('settings.fxTitle') })
  }
  secs.push({ id: 'sec-tg', label: t('settings.tgTitle') })
  if (isSuper.value || (myPerms.value || []).includes('ads.pause')) secs.push({ id: 'sec-keepalive', label: t('settings.keepaliveTitle') })
  return secs
})
// 分组展示：个人（账户/时区/TG）vs 平台（其余超管/运营项）
const PERSONAL_SECTIONS = ['sec-account', 'sec-tz', 'sec-tg']
const anchorGroups = computed(() => [
  { key: 'personal', label: t('settings.grpPersonal'), items: anchorSections.value.filter(s => PERSONAL_SECTIONS.includes(s.id)) },
  { key: 'platform', label: t('settings.grpPlatform'), items: anchorSections.value.filter(s => !PERSONAL_SECTIONS.includes(s.id)) },
].filter(g => g.items.length))
// Tab 切换：点哪个显示哪个分区（Tab 模式，不再长页滚动 + IntersectionObserver）
const switchSection = (id) => {
  activeSection.value = id
  router.replace({ query: { ...route.query, sec: id } })   // 分区进 URL：可刷新还原/分享定位
}
// URL ?sec= → 当前分区。权限加载后校验（非超管带超管 sec 等），非法回落账户分区
const applySectionFromUrl = () => {
  const q = route.query.sec
  if (!q) return
  if (anchorSections.value.some(s => s.id === q)) { activeSection.value = q; return }
  activeSection.value = 'sec-account'
  if (q !== 'sec-account') router.replace({ query: { ...route.query, sec: 'sec-account' } })
}
watch(() => route.query.sec, () => applySectionFromUrl())
const kaResultOpen = ref(false)
const kaResult = ref(null)
const kaResMeta = (r) => ({
  success: { cls: 'ok', label: t('settings.kaSuccess') },
  skip: { cls: 'off', label: t('settings.kaSkip') },
  fail: { cls: 'err', label: t('settings.kaFail') },
}[r] || { cls: 'off', label: r })
const runKeepaliveNow = async () => {
  kaRunning.value = true
  try {
    const r = await POST('/guard/keepalive/run')
    kaRunning.value = false
    if (r.skipped === 'lock_busy') { ElMessage.warning(t('settings.kaLockBusy')); return }
    if (r.error) { ElMessage.error(t('settings.kaRunError', { msg: r.error })); return }
    kaResult.value = r
    kaResultOpen.value = true
  } catch (e) { ElMessage.error(e.message || t('common.opFail')); kaRunning.value = false }
}
</script>

<template>
  <div class="page">
    <!-- 分区导航：sticky 横条按「个人/平台」分组（移动端横向滚动） -->
    <div class="anchor-strip">
      <template v-for="(g, gi) in anchorGroups" :key="g.key">
        <span v-if="gi > 0" class="anchor-sep"></span>
        <span class="anchor-group-label">{{ g.label }}</span>
        <button v-for="s in g.items" :key="s.id" class="anchor-btn" :class="{ active: activeSection === s.id }" @click="switchSection(s.id)">{{ s.label }}</button>
      </template>
    </div>

    <div v-if="activeSection==='sec-account'" id="sec-account" class="card">
      <div class="t">{{ t('settings.accountTitle') }}</div>
      <div class="d">{{ t('settings.accountDesc') }}</div>
      <div class="form-l"><label>{{ t('settings.username') }}</label><input v-model="acctEmail" class="input" :placeholder="t('settings.loginEmailPh')" /></div>
      <div class="form-l"><label>{{ t('settings.oldPwd') }}</label><el-input v-model="emailOldPwd" type="password" autocomplete="current-password" show-password class="ep-input" :placeholder="t('settings.currentPwdPh')" /></div>
      <button class="btn primary" :disabled="acctSaving" @click="saveEmail">{{ t('settings.saveUsername') }}</button>
      <div class="acct-sep"></div>
      <div class="form-l"><label>{{ t('settings.oldPwd') }}</label><el-input v-model="pwdForm.old" type="password" autocomplete="current-password" show-password class="ep-input" :placeholder="t('settings.currentPwdPh')" /></div>
      <div class="form-l"><label>{{ t('settings.newPwd') }}</label><el-input v-model="pwdForm.new" type="password" autocomplete="new-password" show-password class="ep-input" :placeholder="t('settings.pwdMin8Ph')" /></div>
      <div class="form-l"><label>{{ t('settings.confirm') }}</label><el-input v-model="pwdForm.confirm" type="password" autocomplete="new-password" show-password class="ep-input" :placeholder="pwdForm.new && pwdForm.confirm && pwdForm.new !== pwdForm.confirm ? t('settings.pwdMismatchPh') : t('settings.reenterNewPwdPh')" /></div>
      <button class="btn primary" :disabled="pwdSaving" @click="savePwd">{{ t('settings.changePwd') }}</button>
    </div>

    <div v-if="activeSection==='sec-tz'" id="sec-tz" class="card">
      <div class="t">{{ t('settings.tzTitle') }}</div>
      <div class="d">{{ t('settings.tzDesc') }}</div>
      <el-select v-model="tz" filterable allow-create default-first-option
        :placeholder="t('settings.tzSearchPh')" style="width:100%" :disabled="saving" @change="pick">
        <el-option v-for="z in TZ_OPTIONS" :key="z.tz" :value="z.tz" :label="t('settings.tzOption', { label: z.label, tz: z.tz })" />
      </el-select>
    </div>

    <div v-if="isSuper && sched && activeSection==='sec-schedule'" id="sec-schedule" class="card">
      <div class="t">{{ t('settings.scheduleTitle') }}</div>
      <div class="d">{{ t('settings.scheduleDesc') }}</div>
      <div class="base-row">
        <span class="base-label">{{ t('settings.baseBeat') }}</span>
        <input v-model.number="sched.base_minutes" type="number" min="1" class="base-input" />
        <span class="base-unit">{{ t('settings.minutes') }}</span>
      </div>
      <div class="task-head"><span>{{ t('settings.taskCol') }}</span><span>{{ t('settings.multiplierCol') }}</span><span>{{ t('settings.effectiveCol') }}</span></div>
      <div v-for="k in TASK_ORDER" :key="k" class="task-row">
        <span class="task-name">{{ taskLabel(k) }}</span>
        <input v-model.number="sched.multipliers[k]" type="number" min="1" step="0.5" class="mult-input" />
        <span class="eff">{{ t('settings.minSuffix', { n: effOf(k) }) }}</span>
      </div>
      <div class="sentinel-sep"></div>
      <div class="task-row sentinel-row">
        <span class="task-name">{{ taskLabel('sentinel') }}</span>
        <input v-model.number="sched.sentinel_minutes" type="number" min="1" max="10" class="mult-input" />
        <span class="eff">{{ t('settings.minSuffix', { n: sched.sentinel_minutes }) }}</span>
      </div>
      <button class="btn primary" :disabled="schedSaving" @click="saveSched">{{ t('settings.saveAndApply') }}</button>
    </div>

    <div v-if="isSuper && activeSection==='sec-guard-tuning'" id="sec-guard-tuning" class="card">
      <div class="t">{{ t('settings.gtTitle') }}</div>
      <div class="d">{{ t('settings.gtDesc') }}</div>
      <template v-if="gt.guard_concurrency !== null">
        <div class="ret-head"><span>{{ t('settings.gtParamCol') }}</span><span>{{ t('settings.gtValueCol') }}</span><span>{{ t('settings.gtDescCol') }}</span></div>
        <div v-for="r in GT_ROWS" :key="r.key" class="ret-row" :class="{ forever: r.min === 0 && gt[r.key] === 0 }">
          <span class="ret-name">{{ t(r.labelKey) }}</span>
          <input v-model.number="gt[r.key]" type="number" :min="r.min" :max="r.max" step="1" class="ret-input" />
          <span class="ret-hint">{{ t(r.hintKey, { d: gt.defaults[r.key] }) }}</span>
        </div>
        <button class="btn primary" :disabled="gtSaving" @click="saveGuardTuning">{{ t('common.save') }}</button>
      </template>
    </div>

    <div v-if="isSuper && activeSection==='sec-ai'" id="sec-ai" class="card">
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

    <div v-if="isSuper && activeSection==='sec-cf'" id="sec-cf" class="card">
      <div class="t">{{ t('settings.cfTitle') }}</div>
      <div class="d">{{ t('settings.cfDesc') }}</div>
      <div class="form-l"><label>{{ t('settings.accountId') }}</label><input v-model="cfForm.cf_account_id" class="input" :placeholder="t('settings.accountId')" /></div>
      <div class="form-l"><label>API Token</label><input v-model="cfForm.cf_api_token" class="input" type="password" :placeholder="cfCfg.cf_api_token_set ? cfCfg.cf_api_token_masked : t('settings.fillNewTokenPh')" /></div>
      <div class="form-l"><label>{{ t('settings.cfEmailTokenLabel') }}</label><input v-model="cfForm.cf_email_token" class="input" type="password" :placeholder="cfCfg.cf_email_token_set ? cfCfg.cf_email_token_masked : t('settings.cfEmailTokenPh')" />
        <span class="field-hint">{{ t('settings.cfEmailTokenHint') }}</span></div>
      <button class="btn primary" :disabled="cfSaving" @click="saveCf">{{ t('common.save') }}</button>
    </div>

    <!-- 邮箱转发（超管）：状态行 + 目的地邮箱 + 别名映射 -->
    <div v-if="isSuper && activeSection==='sec-email'" id="sec-email" class="card">
      <div class="t">{{ t('settings.emTitle') }}</div>
      <div class="d">{{ t('settings.emDesc', { domain: em.domain || 'tovaads.com' }) }}</div>

      <!-- 状态行：Routing 状态 + DNS 就绪 + 启用/刷新 -->
      <div class="em-status-row">
        <span class="wh-chip" :class="emStatusMeta.cls">{{ emStatusMeta.label }}</span>
        <span v-if="em.status === 'enabled'" class="wh-chip" :class="em.dns_ready ? 'ok' : 'warn'">
          {{ em.dns_ready ? t('settings.emDnsReady') : t('settings.emDnsMissing', { n: (em.missing_dns || []).length }) }}
        </span>
        <button v-if="em.status !== 'enabled'" class="btn em-inline-btn" :disabled="emEnabling || emLoading" @click="enableEmailRouting">
          {{ emEnabling ? t('settings.emEnabling') : t('settings.emEnableBtn') }}
        </button>
        <button class="btn em-inline-btn" :disabled="emLoading" @click="loadEmailRouting">{{ t('common.refresh') }}</button>
      </div>
      <div v-if="em.status !== 'enabled'" class="em-hint">{{ t('settings.emEnableHint') }}</div>
      <div v-if="em.token_ok === false" class="em-hint" style="color:var(--warning)">{{ t('settings.emNeedUserToken') }}</div>

      <!-- 目的地邮箱 -->
      <div class="sub-t" style="margin-top:18px">{{ t('settings.emDestTitle') }}</div>
      <div class="d" style="margin-bottom:8px">{{ t('settings.emDestDesc') }}</div>
      <div class="em-list">
        <div v-for="a in (em.addresses || [])" :key="a.id" class="em-row">
          <span class="em-email">{{ a.email }}</span>
          <span class="wh-chip" :class="a.verified ? 'ok' : 'warn'">
            {{ a.verified ? t('settings.emAddrVerified') : t('settings.emAddrPending') }}
          </span>
          <button class="em-del" @click="delEmAddress(a)">{{ t('common.delete') }}</button>
        </div>
        <div v-if="!(em.addresses || []).length" class="em-empty">{{ t('settings.emNoAddrs') }}</div>
      </div>
      <div class="em-add-row">
        <input v-model="emAddrForm" class="input" :placeholder="t('settings.emAddrPh')" @keyup.enter="addEmAddress" />
        <button class="btn em-inline-btn" :disabled="emAddrSaving" @click="addEmAddress">
          {{ emAddrSaving ? t('common.loading') : t('common.add') }}
        </button>
      </div>

      <!-- 别名映射 -->
      <div class="sub-t" style="margin-top:18px">{{ t('settings.emRouteTitle') }}</div>
      <div class="d" style="margin-bottom:8px">{{ t('settings.emRouteDesc', { domain: em.domain || 'tovaads.com' }) }}</div>
      <div class="em-list">
        <div v-for="r in (em.routes || [])" :key="r.id" class="em-row">
          <code class="em-alias">{{ r.alias_email }}</code>
          <span class="em-arrow">→</span>
          <span class="em-email">{{ r.destination_email }}</span>
          <el-switch :model-value="r.enabled" active-color="#0a84ff" inactive-color="#3a3a5c" size="small" @change="toggleEmRoute(r)" />
          <button class="em-del" @click="delEmRoute(r)">{{ t('common.delete') }}</button>
        </div>
        <div v-if="!(em.routes || []).length" class="em-empty">{{ t('settings.emNoRoutes') }}</div>
      </div>
      <div class="em-add-row">
        <input v-model="emRouteForm.alias" class="input em-alias-input" :placeholder="t('settings.emAliasPh')" @keyup.enter="addEmRoute" />
        <span class="em-domain">@{{ em.domain || 'tovaads.com' }}</span>
        <el-select v-model="emRouteForm.destination_email" :placeholder="t('settings.emPickDestPh')" style="flex:1" size="default">
          <el-option v-for="a in emVerifiedAddrs" :key="a.id" :value="a.email" :label="a.email" />
        </el-select>
        <button class="btn em-inline-btn" :disabled="emRouteSaving" @click="addEmRoute">
          {{ emRouteSaving ? t('common.loading') : t('settings.emRouteAdd') }}
        </button>
      </div>
    </div>

    <div v-if="isSuper && activeSection==='sec-webhook'" id="sec-webhook" class="card">
      <div class="t">{{ t('settings.whTitle') }}</div>
      <div class="d">{{ t('settings.whDesc') }}</div>
      <div class="wh-url-row">
        <code class="wh-url">{{ whCfg.public_url }}</code>
        <button class="btn sm" @click="copyText(whCfg.public_url, t('settings.whUrlCopied'))">{{ t('settings.whCopyUrl') }}</button>
      </div>
      <div class="wh-status">
        <span class="wh-chip" :class="{ ok: whCfg.active_apps > 0, warn: !whCfg.active_apps }">
          {{ t('settings.whActiveApps', { n: whCfg.active_apps }) }}
        </span>
        <span v-if="whCfg.active_apps" class="wh-app-names">{{ (whCfg.app_names || []).join(' · ') }}</span>
      </div>
      <div class="d" style="margin:6px 0 4px">{{ t('settings.whTokenLabel') }}</div>
      <div class="form-l"><input v-model="whForm.verify_token" class="input" type="password" :placeholder="whCfg.verify_token_set ? whCfg.verify_token_masked + ' (' + (whCfg.verify_token_is_default ? t('settings.whDefault') : t('settings.whCustom')) + ')' : t('settings.whTokenPh')" /></div>
      <div class="d" style="font-size:11px;color:var(--t3);margin:4px 0 10px">{{ t('settings.whTokenHint') }}</div>
      <div style="display:flex;gap:8px">
        <button class="btn primary" :disabled="whSaving" @click="saveWebhook">{{ t('common.save') }}</button>
        <button v-if="whCfg.verify_token_set && !whCfg.verify_token_is_default" class="btn" :disabled="whSaving" @click="resetWebhookToken">{{ t('settings.whResetDefault') }}</button>
      </div>
    </div>

    <div v-if="isSuper && activeSection==='sec-retention'" id="sec-retention" class="card">
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

    <div v-if="isSuper && activeSection==='sec-fx'" id="sec-fx" class="card">
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

    <div v-if="activeSection==='sec-tg'" id="sec-tg" class="card">
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
        <!-- widget 打不开时的兜底：向 bot 发 /start 拿 chat_id 手动绑 -->
        <div class="tg-manual">
          <span class="tg-manual-hint">{{ t('settings.tgManualHint') }}</span>
          <div class="tg-manual-row">
            <input v-model="tgManual.chat_id" class="input tg-manual-input" :placeholder="t('settings.tgManualPh')" @keyup.enter="bindTgManual" />
            <button class="btn" :disabled="tgManual.saving" @click="bindTgManual">{{ tgManual.saving ? t('common.saving') : t('settings.tgManualBind') }}</button>
          </div>
        </div>
      </div>

      <!-- 验证 Bot 配置（owner/超管） -->
      <div v-if="(isSuper || (myPerms || []).includes('members.manage')) && tgBot.configured" class="tg-verify">
        <button class="btn" :disabled="testTgLoading" @click="testTenantTg">{{ testTgLoading ? t('settings.sending') : t('settings.verifyBotConfig') }}</button>
        <span class="tg-verify-hint">{{ t('settings.verifyBotHint') }}</span>
      </div>
    </div>

    <div v-if="(isSuper || (myPerms || []).includes('ads.pause')) && activeSection==='sec-keepalive'" id="sec-keepalive" class="card">
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
        <button v-if="isSuper" class="btn" :disabled="kaRunning" @click="runKeepaliveNow">{{ kaRunning ? t('common.loading') : t('settings.kaRunNow') }}</button>
      </div>
    </div>

    <!-- 保活扫描结果弹窗（每账户 success/skip/fail + 翻译原因） -->
    <el-dialog v-model="kaResultOpen" :title="t('settings.kaResultTitle')" width="560px" append-to-body>
      <div v-if="kaResult" class="ka-result">
        <div class="ka-summary">
          <span class="ok">✓ {{ t('settings.kaBuilt') }} {{ kaResult.created || 0 }}</span>
          <span class="off">⊘ {{ t('settings.kaSkipped') }} {{ kaResult.skipped || 0 }}</span>
          <span class="err">✗ {{ t('settings.kaFailed') }} {{ kaResult.failed || 0 }}</span>
        </div>
        <div class="ka-list">
          <div v-for="r in (kaResult.results || [])" :key="r.act_id" class="ka-row">
            <span class="ka-dot" :class="kaResMeta(r.result).cls"></span>
            <span class="ka-name" :title="r.name">{{ r.name }}</span>
            <span class="ka-st" :class="kaResMeta(r.result).cls">{{ kaResMeta(r.result).label }}</span>
            <span v-if="r.result !== 'success'" class="ka-reason" :title="fbErrorText(r.category) || r.reason">{{ fbErrorText(r.category) || r.reason }}</span>
          </div>
          <div v-if="!(kaResult.results||[]).length" class="ka-empty">{{ t('settings.kaNoAccounts') }}</div>
        </div>
      </div>
      <template #footer>
        <button class="btn primary" @click="kaResultOpen=false">{{ t('common.close') }}</button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page{display:flex;flex-direction:column;gap:14px}
/* 锚点导航 */
.anchor-strip{position:sticky;top:0;z-index:50;display:flex;gap:4px;overflow-x:auto;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--bd)}
.anchor-group-label{font-size:10px;color:var(--t3);align-self:center;padding:0 2px;white-space:nowrap;flex-shrink:0}
.anchor-sep{width:1px;align-self:stretch;background:var(--bd);margin:2px 4px;flex-shrink:0}
.anchor-btn{padding:4px 12px;background:transparent;color:var(--t3);border:1px solid transparent;border-radius:var(--rs);font-size:12px;cursor:pointer;white-space:nowrap;font-family:inherit}
.anchor-btn:hover{color:var(--t1);background:var(--bg2)}
.anchor-btn.active{background:var(--ac);color:#fff}
.card{scroll-margin-top:60px}
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
.tg-manual{margin-top:10px;padding-top:10px;border-top:1px dashed var(--bd);width:100%}
.tg-manual-hint{font-size:11px;color:var(--t3);display:block;margin-bottom:6px}
.tg-manual-row{display:flex;gap:8px;align-items:center}
.tg-manual-input{flex:1;min-width:0;max-width:240px}
@media (max-width:768px){.tg-manual-row{flex-direction:column;align-items:stretch}.tg-manual-input{max-width:none}}
.tg-verify{margin-top:10px;padding-top:10px;border-top:1px solid var(--bd);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tg-verify .btn{margin-top:0}
.tg-verify-hint{font-size:11px;color:var(--t3)}
/* 保活结果弹窗 */
.ka-result{display:flex;flex-direction:column;gap:10px}
.ka-summary{display:flex;gap:14px;font-size:13px;font-weight:600}
.ka-summary .ok{color:var(--success)}.ka-summary .off{color:var(--t3)}.ka-summary .err{color:var(--error)}
.ka-list{display:flex;flex-direction:column;gap:4px;max-height:340px;overflow-y:auto}
.ka-row{display:flex;align-items:center;gap:8px;padding:7px 10px;background:var(--bg3);border-radius:6px;font-size:12px}
.ka-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.ka-dot.ok{background:var(--success)}.ka-dot.off{background:var(--t3)}.ka-dot.err{background:var(--error)}
.ka-name{color:var(--t1);flex-shrink:0;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ka-st{font-size:11px;padding:1px 7px;border-radius:8px;flex-shrink:0}
.ka-st.ok{background:rgba(48,209,88,.13);color:var(--success)}
.ka-st.off{background:var(--bg2);color:var(--t3)}
.ka-st.err{background:rgba(255,69,58,.13);color:var(--error)}
.ka-reason{color:var(--t3);font-size:11px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ka-empty{text-align:center;color:var(--t3);padding:20px;font-size:13px}
.wh-url-row{display:flex;align-items:center;gap:8px;margin:8px 0 12px}
.wh-url{flex:1;font-family:monospace;font-size:12px;color:var(--ac);background:var(--bg3);padding:6px 10px;border-radius:6px;word-break:break-all}
.wh-status{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.wh-chip{font-size:11px;padding:2px 10px;border-radius:10px;font-weight:600}
.wh-chip.ok{background:rgba(48,209,97,.12);color:var(--success)}
.wh-chip.warn{background:rgba(255,159,10,.12);color:var(--warning)}
.wh-app-names{font-size:11px;color:var(--t3)}
/* 邮箱转发 */
.em-status-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.em-inline-btn{margin-top:0;padding:6px 12px;font-size:12px}
.em-hint{font-size:11px;color:var(--t3);margin-top:8px}
.field-hint{display:block;font-size:11px;color:var(--t3);margin-top:4px;line-height:1.5}
.em-list{display:flex;flex-direction:column;gap:4px}
.em-row{display:flex;align-items:center;gap:10px;padding:7px 10px;background:var(--bg3);border-radius:6px;font-size:13px}
.em-email{color:var(--t1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.em-alias{font-family:monospace;font-size:12px;color:var(--ac);flex-shrink:0}
.em-arrow{color:var(--t3);flex-shrink:0}
.em-row .wh-chip{flex-shrink:0}
.em-row .el-switch{flex-shrink:0;margin-left:auto}
.em-del{margin-left:8px;background:transparent;border:none;color:var(--t3);font-size:12px;cursor:pointer;font-family:inherit;flex-shrink:0}
.em-del:hover{color:var(--error)}
.em-empty{padding:12px;text-align:center;color:var(--t3);font-size:12px}
.em-add-row{display:flex;align-items:center;gap:8px;margin-top:10px}
.em-alias-input{max-width:150px;flex:0 1 150px}
.em-domain{color:var(--t3);font-size:12px;flex-shrink:0}
@media (max-width:768px){.em-add-row{flex-wrap:wrap}.em-alias-input{flex:1 1 100%;max-width:none}.em-domain{order:2}.em-add-row .el-select{order:3;flex:1 1 100%}}
</style>
