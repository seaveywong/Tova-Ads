<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { showError } from '../composables/useError'

const { t } = useI18n()
const tab = ref('form')
const forms = ref([])
const messages = ref([])
const loading = ref(false)

// 表单编辑
const formOpen = ref(false)
const editingForm = ref(null)
const fCfg = ref({})
const fMeta = ref({ name: '', description: '', locale: 'en_US' })
const saving = ref(false)
// 平台（fb/tt）：建时选（openFormNew(p)），编辑跟随模板；payload 部署时按平台构建
const fPlat = ref('fb')
const isTtForm = computed(() => fPlat.value === 'tt')
// 新建表单 → 选平台弹窗（建后不可改；v-model 绑定）
const formPlatDialog = ref(false)
// 列表平台筛选（表单 tab；消息模板按 type 区分不过滤平台）
const formPlatFilter = ref('all')
const filteredForms = computed(() =>
  formPlatFilter.value === 'all' ? forms.value : forms.value.filter(f => (f.platform || 'fb') === formPlatFilter.value))
// 新增问题的默认题型（编辑器 UI 态；每张问题卡可单独切换）
const qStyle = ref('choice')
// 「更多字段」联系字段展开
const showMoreContact = ref(false)

// 消息编辑
const msgOpen = ref(false)
const editingMsg = ref(null)
const mCfg = ref({ name: '', type: 'messenger', welcome_text: '', ice_breakers: [] })
const isWaMsg = computed(() => mCfg.value.type === 'whatsapp')

// 预览
const previewOpen = ref(false)
const previewData = ref(null)
const previewType = ref('form')

// AI
const aiLoading = ref(false)
const assetPickerOpen = ref(false)
const pickerAssets = ref([])

const LOCALES = [
  {v:'en_US',l:'English (US)'},{v:'zh_TW',l:'繁體中文'},{v:'zh_CN',l:'简体中文'},
  {v:'vi_VN',l:'Tiếng Việt'},{v:'th_TH',l:'ภาษาไทย'},{v:'id_ID',l:'Bahasa Indonesia'},
  {v:'ja_JP',l:'日本語'},{v:'ko_KR',l:'한국어'},{v:'es_ES',l:'Español'},{v:'pt_BR',l:'Português'},
]
const contactFieldLabel = (v) => (CONTACT_FIELDS.value.find(x => x.v === v) || {}).l || v
const CONTACT_FIELDS = computed(() => [
  {v:'EMAIL',l:t('formtpl.contact.email')},{v:'PHONE',l:t('formtpl.contact.phone')},{v:'CITY',l:t('formtpl.contact.city')},{v:'STATE',l:t('formtpl.contact.state')},
  {v:'ZIP_CODE',l:t('formtpl.contact.zip')},{v:'COUNTRY',l:t('formtpl.contact.country')},{v:'DATE_OF_BIRTH',l:t('formtpl.contact.dob')},{v:'GENDER',l:t('formtpl.contact.gender')},
  {v:'MARITAL_STATUS',l:t('formtpl.contact.marital')},{v:'LAST_NAME',l:t('formtpl.contact.lastName')},
])
// 联系信息分区：电话/邮箱/城市 常驻复选，其余收进「更多字段」
const MAIN_CONTACTS = computed(() => CONTACT_FIELDS.value.filter(f => ['PHONE', 'EMAIL', 'CITY'].includes(f.v)))
const MORE_CONTACTS = computed(() => CONTACT_FIELDS.value.filter(f => !['PHONE', 'EMAIL', 'CITY'].includes(f.v)))

const load = async () => {
  loading.value = true
  try { [forms.value, messages.value] = await Promise.all([GET('/form-templates/forms'), GET('/form-templates/messages')]) }   // 互不依赖——并行
  catch (e) { showError(e, t('formtpl.loadFail')) }
  loading.value = false
}
onMounted(load)

// ── 表单 ──
const blankForm = () => ({
  form_title: '', description: '', privacy_url: '', privacy_link_text: 'Privacy Policy',
  target_countries: [], extra_contact_fields: ['EMAIL'],
  custom_questions: [], thank_you_title: '', thank_you_body: '',
  thank_you_button_type: 'none', thank_you_button_text: '', thank_you_website_url: '',
  whatsapp_number: '', whatsapp_msg_tpl_id: null,
  follow_up_url: '', context_card_title: '',
  is_optimized_for_quality: true,
  welcome_message: '', block_display_for_non_targeted: false,
})
const openFormNew = (p) => {
  editingForm.value = null; fPlat.value = p === 'tt' ? 'tt' : 'fb'
  fMeta.value = { name: '', description: '', locale: 'en_US' }; fCfg.value = blankForm(); formOpen.value = true
}
const openFormEdit = (tpl) => {
  editingForm.value = tpl; fPlat.value = (tpl.platform === 'tt') ? 'tt' : 'fb'
  fMeta.value = { name: tpl.name, description: tpl.description, locale: tpl.locale }
  const cfg = { ...blankForm(), ...(tpl.config || {}) }
  // _keyAuto：key 仍处自动态（服务端原值为空）时 label 改动可继续同步 slug
  cfg.custom_questions = (cfg.custom_questions || []).map(q => ({ ...q, options: q.options || [], _keyAuto: !q.key }))
  // 存量 config 无 button_type：文字+链接齐 → 视作 website（旧语义），否则无按钮
  if (!cfg.thank_you_button_type) {
    cfg.thank_you_button_type = (cfg.thank_you_button_text && cfg.thank_you_website_url) ? 'website' : 'none'
  }
  fCfg.value = cfg; formOpen.value = true
}

// ── 预览镜像（与后端 ad_builder.build_lead_form_payload 同源逻辑）──
// 电话优先国家：主联系字段路由 PHONE，否则 EMAIL
const PHONE_FIRST_COUNTRIES = ['PH', 'TH', 'ID', 'MY', 'VN', 'IN', 'BR', 'MX', 'NG', 'CO', 'EG', 'PK', 'BD']
const primaryOf = (cfg) => {
  const cs = cfg.target_countries || []
  return cs.some(c => PHONE_FIRST_COUNTRIES.includes(String(c).toUpperCase())) ? 'PHONE' : 'EMAIL'
}
// 联系字段 chip 列：姓名 + 主联系字段 + 勾选字段（去重），顺序同 payload questions
const contactsOf = (cfg) => {
  const out = [{ v: 'FIRST_NAME', l: t('formtpl.pmFirstName') }]
  const seen = new Set(['FIRST_NAME'])
  const add = (v) => { if (!seen.has(v)) { seen.add(v); out.push({ v, l: contactFieldLabel(v) }) } }
  add(primaryOf(cfg))
  for (const f of (cfg.extra_contact_fields || [])) add(String(f).toUpperCase())
  return out
}
// 主联系字段未被显式勾选 → 标「自动」（payload 兜底逻辑）
const isAutoContact = (cfg, v) => {
  const picked = (cfg.extra_contact_fields || []).map(x => String(x).toUpperCase())
  return v === primaryOf(cfg) && !picked.includes(v)
}
const tyBtnTypeOf = (cfg) => cfg.thank_you_button_type || ((cfg.thank_you_button_text && cfg.thank_you_website_url) ? 'website' : 'none')
const qIsChoice = (q) => Array.isArray(q.options) && q.options.length > 0

// ── 自定义问题卡 ──
const addQuestion = () => fCfg.value.custom_questions.push({
  key: '', label: '', placeholder: '',
  options: qStyle.value === 'choice' ? [{ key: '', value: '' }] : [],
  _keyAuto: true,
})
const removeQuestion = (i) => fCfg.value.custom_questions.splice(i, 1)
const moveQuestion = (i, d) => {
  const arr = fCfg.value.custom_questions
  const j = i + d
  if (j < 0 || j >= arr.length) return
  const [q] = arr.splice(i, 1)
  arr.splice(j, 0, q)
}
// 题型切换：开放式 ⇄ 选择题（转开放式且有已填选项 → 确认清空）
const setQType = async (q, v) => {
  if (v === 'choice') {
    if (!q.options || !q.options.length) q.options = [{ key: '', value: '' }]
    return
  }
  const hasText = (q.options || []).some(o => (o.value || '').trim())
  if (hasText) {
    try { await ElMessageBox.confirm(t('formtpl.qSwitchClear'), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' }) }
    catch { return }
  }
  q.options = []
}
// q.key 自动 slug：label 变化且 key 未被手改（_keyAuto）时同步生成英文 key；手改后不再覆盖
const slugifyKey = (label) => String(label || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40)
const syncQKey = (q) => { if (q._keyAuto) q.key = slugifyKey(q.label) }
const addOption = (q) => q.options.push({ key: '', value: '' })
const removeOption = (q, i) => q.options.splice(i, 1)

// ── 联系信息 / 感谢页 ──
const toggleContact = (v) => {
  const arr = fCfg.value.extra_contact_fields || []
  const i = arr.indexOf(v)
  if (i >= 0) arr.splice(i, 1); else arr.push(v)
}
// 感谢页按钮类型切换：清掉另一类型的字段（避免脏数据随 config 入库）
const onTyBtnType = (v) => {
  if (v === 'website') { fCfg.value.whatsapp_number = ''; fCfg.value.whatsapp_msg_tpl_id = null }
  else if (v === 'whatsapp') { fCfg.value.thank_you_website_url = '' }
  else { fCfg.value.thank_you_website_url = ''; fCfg.value.whatsapp_number = ''; fCfg.value.whatsapp_msg_tpl_id = null }
}
// WhatsApp 消息模板下拉：只列 whatsapp 型；当前选中若是别的类型也带上（用户改过类型时不丢引用）
const waMsgOptions = computed(() => {
  const was = messages.value.filter(m => (m.type || 'messenger') === 'whatsapp')
  const cur = messages.value.find(m => m.id === fCfg.value.whatsapp_msg_tpl_id)
  return (cur && !was.some(m => m.id === cur.id)) ? [...was, cur] : was
})

const saveForm = async () => {
  if (!fMeta.value.name.trim()) return ElMessage.warning(t('formtpl.needName'))
  if (!fCfg.value.form_title.trim()) return ElMessage.warning(t('formtpl.needFormTitle'))
  if (!fCfg.value.privacy_url.trim()) return ElMessage.warning(t('formtpl.needPrivacyUrl'))
  if (tyBtnTypeOf(fCfg.value) === 'website' && !fCfg.value.thank_you_website_url.trim()) return ElMessage.warning(t('formtpl.needBtnUrl'))
  if (tyBtnTypeOf(fCfg.value) === 'whatsapp' && !fCfg.value.whatsapp_number.trim()) return ElMessage.warning(t('formtpl.needWaNumber'))
  saving.value = true
  try {
    // 剥掉前端内部标记（_keyAuto）+ 净化：空问题不存、选择题空选项剔除（剩 0 个即开放式）
    const cfgOut = JSON.parse(JSON.stringify(fCfg.value))
    cfgOut.custom_questions = (cfgOut.custom_questions || [])
      .filter(q => (q.label || '').trim())
      .map(({ _keyAuto, ...q }) => ({ ...q, options: (q.options || []).filter(o => (o.value || '').trim()) }))
    const body = { name: fMeta.value.name, description: fMeta.value.description, locale: fMeta.value.locale, platform: fPlat.value, config: cfgOut }
    if (editingForm.value) { await PUT('/form-templates/forms/' + editingForm.value.id, body); ElMessage.success(t('common.saved')) }
    else { await POST('/form-templates/forms', body); ElMessage.success(t('common.createdOk')) }
    formOpen.value = false; await load()
  } catch (e) { showError(e, t('common.opFail')) }
  saving.value = false
}
const hardDelete = async (item, kind) => {
  const tip = kind === 'form' ? t('formtpl.delConfirm', { name: item.name }) : t('formtpl.delMsgConfirm', { name: item.name })
  try { await ElMessageBox.confirm(tip, t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' }) } catch { return }
  try {
    await DELETE(kind === 'form' ? '/form-templates/forms/' + item.id : '/form-templates/messages/' + item.id)
    ElMessage.success(t('common.savedOk'))
    if (kind === 'form') { forms.value = forms.value.filter(x => x.id !== item.id) }
    else { messages.value = messages.value.filter(x => x.id !== item.id) }
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
}
const removeForm = async (item) => {   // 参数曾用 t 遮蔽 i18n 导致归档坏死（全库审查 P0）
  try { await ElMessageBox.confirm(t('formtpl.archiveConfirm', { name: item.name }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' }); await DELETE('/form-templates/forms/' + item.id); ElMessage.success(t('formtpl.archived')); await load() }
  catch (e) { if (e !== 'cancel') ElMessage.error(e.message || t('common.opFail')) }   // 被引用等真报错要提示
}
const previewForm = (item) => { previewType.value = 'form'; previewData.value = item.config || {}; previewOpen.value = true }
// 卡片 ⋯ 菜单（归档/永久删除；与 Assets/LaunchTemplates 卡操作同模式）
const onFormCmd = (cmd, item) => cmd === 'delete' ? hardDelete(item, 'form') : removeForm(item)
const onMsgCmd = (cmd, item) => cmd === 'delete' ? hardDelete(item, 'msg') : removeMsg(item)

// ── AI 生成（表单/消息都从素材文案生成）──
const pickerMode = ref('form')  // 'form' | 'msg'：素材选择器服务哪个抽屉
const aiPurposeInput = ref('')  // 本次 AI 生成的「投放目的」（可选，像素材分析那样定向）
const openAssetPicker = async (mode) => {
  let purpose = ''
  try {
    const g = await ElMessageBox.prompt(t('formtpl.aiPurposePrompt'), t('formtpl.aiPurposeTitle'), {
      confirmButtonText: t('formtpl.aiPickAsset'), cancelButtonText: t('formtpl.aiPurposeSkip'),
      inputType: 'textarea', inputPlaceholder: t('formtpl.aiPurposePh'),
    })
    purpose = (g.value || '').trim()
  } catch { /* 跳过：不带目的直接生成 */ }
  aiPurposeInput.value = purpose
  pickerMode.value = mode || 'form'
  assetPickerOpen.value = true
  loadAssets()
}
const loadAssets = async () => {
  // 会话级守卫：已加载就不重拉全量素材（选素材只为取 AI 文案，不要求实时新上传）
  if (pickerAssets.value.length) return
  try { pickerAssets.value = await GET('/assets') } catch {}
}
const pickAsset = (a) => { pickerMode.value === 'msg' ? aiGenerateMsg(a) : aiGenerate(a) }
const aiGenerate = async (a) => {
  assetPickerOpen.value = false; aiLoading.value = true
  try {
    const r = await POST('/form-templates/forms/ai-generate', { asset_id: a.id, country: (fCfg.value.target_countries||[])[0] || '', locale: fMeta.value.locale || 'en_US', purpose: aiPurposeInput.value })
    const cfg = r.config || {}
    if (cfg.form_title) fCfg.value.form_title = cfg.form_title
    if (cfg.description) fCfg.value.description = cfg.description
    if (cfg.custom_questions) fCfg.value.custom_questions = cfg.custom_questions.map(q => ({ ...q, options: q.options || [], _keyAuto: !q.key }))
    if (cfg.extra_contact_fields) fCfg.value.extra_contact_fields = cfg.extra_contact_fields
    if (cfg.thank_you_title) fCfg.value.thank_you_title = cfg.thank_you_title
    if (cfg.thank_you_body) fCfg.value.thank_you_body = cfg.thank_you_body
    ElMessage.success(t('formtpl.aiGenerated'))
  } catch (e) { showError(e, t('formtpl.aiFail')) }
  aiLoading.value = false
}
const aiGenerateMsg = async (a) => {
  assetPickerOpen.value = false; aiLoading.value = true
  try {
    const r = await POST('/form-templates/messages/ai-generate', { asset_id: a.id, purpose: aiPurposeInput.value })
    if (r.welcome_text) mCfg.value.welcome_text = r.welcome_text
    if (r.ice_breakers && r.ice_breakers.length) mCfg.value.ice_breakers = r.ice_breakers
    ElMessage.success(t('formtpl.aiGenerated'))
  } catch (e) { showError(e, t('formtpl.aiFail')) }
  aiLoading.value = false
}

// ── 消息 ──
const openMsgNew = () => { editingMsg.value = null; mCfg.value = { name: '', type: 'messenger', welcome_text: '', ice_breakers: [] }; msgOpen.value = true }
const openMsgEdit = (tpl) => { editingMsg.value = tpl; mCfg.value = { name: tpl.name, type: tpl.type || 'messenger', welcome_text: tpl.welcome_text, ice_breakers: [...(tpl.ice_breakers||[])] }; msgOpen.value = true }
const addIB = () => mCfg.value.ice_breakers.push({ title: '', response: '' })
const removeIB = (i) => mCfg.value.ice_breakers.splice(i, 1)
const saveMsg = async () => {
  if (!mCfg.value.name.trim()) return ElMessage.warning(t('formtpl.needName'))
  if (!mCfg.value.welcome_text.trim()) return ElMessage.warning(t('formtpl.needWelcome'))
  saving.value = true
  try {
    const body = { name: mCfg.value.name, type: mCfg.value.type, welcome_text: mCfg.value.welcome_text, ice_breakers: mCfg.value.ice_breakers }
    if (editingMsg.value) { await PUT('/form-templates/messages/' + editingMsg.value.id, body); ElMessage.success(t('common.saved')) }
    else { await POST('/form-templates/messages', body); ElMessage.success(t('common.createdOk')) }
    msgOpen.value = false; await load()
  } catch (e) { showError(e, t('common.opFail')) }
  saving.value = false
}
const removeMsg = async (item) => {   // 同上：参数不遮蔽 i18n
  try { await ElMessageBox.confirm(t('formtpl.archiveConfirm', { name: item.name }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' }); await DELETE('/form-templates/messages/' + item.id); ElMessage.success(t('formtpl.archived')); await load() }
  catch (e) { if (e !== 'cancel') ElMessage.error(e.message || t('common.opFail')) }
}
const previewMsg = (item) => { previewType.value = 'msg'; previewData.value = item; previewOpen.value = true }
const isWaPreview = computed(() => previewType.value === 'msg' && (previewData.value?.type || 'messenger') === 'whatsapp')
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="ph-left">
        <h1 class="ph-title">{{ t('formtpl.pageTitle') }}</h1>
        <span class="ph-fresh">{{ t('formtpl.countSummary', { f: forms.length, m: messages.length }) }}</span>
      </div>
      <div class="ph-actions">
        <!-- 表单建时选平台（payload 按平台构建，建后不可改）；消息模板保持单按钮 -->
        <button v-if="tab==='form'" class="head-btn primary" @click="formPlatDialog = true">{{ t('formtpl.newBtn', { kind: t('formtpl.formUnit') }) }}</button>
        <button v-else class="head-btn primary" @click="openMsgNew()">{{ t('formtpl.newBtn', { kind: t('formtpl.msgUnit') }) }}</button>
      </div>
    </header>
    <div class="bar">
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <div class="tabs">
          <button :class="['tab',{on:tab==='form'}]" @click="tab='form'">{{ t('formtpl.tabForm') }}</button>
          <button :class="['tab',{on:tab==='msg'}]" @click="tab='msg'">{{ t('formtpl.tabMsg') }}</button>
        </div>
        <div v-if="tab==='form'" class="tabs">
          <button :class="['tab',{on:formPlatFilter==='all'}]" @click="formPlatFilter='all'">{{ t('common.all') }}</button>
          <button :class="['tab',{on:formPlatFilter==='fb'}]" @click="formPlatFilter='fb'">Facebook</button>
          <button :class="['tab',{on:formPlatFilter==='tt'}]" @click="formPlatFilter='tt'">TikTok</button>
        </div>
      </div>
    </div>

    <!-- Instant Form 列表 -->
    <div v-if="tab==='form'" class="grid" v-loading="loading">
      <div v-for="item in filteredForms" :key="item.id" class="card">
        <div class="card-head">
          <span class="card-name"><span :class="['plat-chip', item.platform==='tt'?'tt':'fb']">{{ (item.platform||'fb').toUpperCase() }}</span>{{ item.name }}</span>
          <span :class="['card-badge', item.fb_form_id ? 'ready' : 'draft']">{{ item.fb_form_id ? '✓ ' + t('formtpl.deployed') : t('formtpl.draft') }}</span>
        </div>
        <div class="card-copy">{{ (item.config||{}).form_title || '—' }}</div>
        <div class="card-meta">
          <span class="meta-chip">{{ t('formtpl.questionsCount', { n: ((item.config||{}).custom_questions||[]).length }) }}</span>
          <span class="meta-chip">{{ item.locale }}</span>
        </div>
        <div class="card-ops">
          <button class="op primary" @click="openFormEdit(item)">{{ t('common.edit') }}</button>
          <button class="op" @click="previewForm(item)">{{ t('common.preview') }}</button>
          <el-dropdown trigger="click" @command="cmd => onFormCmd(cmd, item)">
            <button class="op dots" @click.stop>⋯</button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="archive" class="danger">{{ t('formtpl.archive') }}</el-dropdown-item>
                <el-dropdown-item command="delete" divided class="danger">{{ t('common.delete') }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
      <div v-if="!filteredForms.length && !loading" class="empty">
        <div>{{ formPlatFilter==='all' || !forms.length ? t('formtpl.noForms') : t('formtpl.noFormsForPlat') }}</div>
        <button v-if="formPlatFilter==='all' || !forms.length" class="btn primary empty-cta" @click="formPlatDialog = true">{{ t('formtpl.emptyCtaForm') }}</button>
      </div>
    </div>

    <!-- 消息列表（Messenger / WhatsApp） -->
    <div v-if="tab==='msg'" class="grid" v-loading="loading">
      <div v-for="item in messages" :key="item.id" class="card">
        <div class="card-head">
          <span class="card-name"><span :class="['msg-chip', (item.type||'messenger')==='whatsapp'?'wa':'ms']">{{ (item.type||'messenger')==='whatsapp'?'WhatsApp':'Messenger' }}</span>{{ item.name }}</span>
        </div>
        <div class="card-copy">{{ (item.welcome_text||'').slice(0,60) }}{{ (item.welcome_text||'').length>60?'…':'' }}</div>
        <div class="card-meta"><span class="meta-chip">{{ t('formtpl.quickRepliesCount', { n: (item.ice_breakers||[]).length }) }}</span></div>
        <div class="card-ops">
          <button class="op primary" @click="openMsgEdit(item)">{{ t('common.edit') }}</button>
          <button class="op" @click="previewMsg(item)">{{ t('common.preview') }}</button>
          <el-dropdown trigger="click" @command="cmd => onMsgCmd(cmd, item)">
            <button class="op dots" @click.stop>⋯</button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="archive" class="danger">{{ t('formtpl.archive') }}</el-dropdown-item>
                <el-dropdown-item command="delete" divided class="danger">{{ t('common.delete') }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
      <div v-if="!messages.length && !loading" class="empty">
        <div>{{ t('formtpl.noMessages') }}</div>
        <button class="btn primary empty-cta" @click="openMsgNew()">{{ t('formtpl.emptyCtaMsg') }}</button>
      </div>
    </div>

    <!-- 表单编辑抽屉：左手机实时预览 + 右设置分区（Header=标题+平台/类型 chip，与投放模板编辑器一致） -->
    <el-drawer v-model="formOpen" direction="rtl" size="min(1120px, 96vw)" :destroy-on-close="true">
      <template #header>
        <div class="dr-head">
          <span class="dr-title">{{ editingForm ? t('formtpl.editForm') : t('formtpl.newForm') }}</span>
          <span :class="['plat-chip', isTtForm ? 'tt' : 'fb']">{{ isTtForm ? 'TT' : 'FB' }}</span>
          <span class="type-chip">{{ t('formtpl.chipForm') }}</span>
        </div>
      </template>
      <div class="fx-editor">
        <!-- 左：手机壳实时预览（与列表「预览」弹窗同结构，改一处记得同步另一处） -->
        <div class="fx-left">
          <div class="fx-left-head">{{ t('formtpl.editorPreview') }}</div>
          <div class="phone-mockup">
            <div class="pm-screen">
              <div class="pm-header" :class="{muted:!fCfg.form_title}">{{ fCfg.form_title || t('formtpl.pmFormTitle') }}</div>
              <div v-if="fCfg.description" class="pm-desc">{{ fCfg.description }}</div>
              <div class="pm-contact-head">{{ t('formtpl.pvContact') }}</div>
              <div class="pm-chips">
                <span v-for="c in contactsOf(fCfg)" :key="c.v" class="pm-chip">{{ c.l }}<em v-if="isAutoContact(fCfg, c.v)" class="pm-auto">{{ t('formtpl.pvAuto') }}</em></span>
              </div>
              <div v-for="(q,i) in (fCfg.custom_questions||[])" :key="'q'+i" class="pm-qcard">
                <div class="pm-label" :class="{muted:!q.label}">{{ q.label || t('formtpl.pmQuestion') }}</div>
                <div v-if="qIsChoice(q)" class="pm-options">
                  <span v-for="(o,oi) in q.options" :key="oi" class="pm-option">{{ o.value }}</span>
                </div>
                <div v-else class="pm-input-mock">{{ q.placeholder || '—' }}</div>
              </div>
              <button class="pm-submit">{{ t('formtpl.pmSubmit') }}</button>
              <a class="pm-privacy">{{ fCfg.privacy_link_text || 'Privacy Policy' }}</a>
              <div v-if="fCfg.thank_you_title || fCfg.thank_you_body || tyBtnTypeOf(fCfg) !== 'none'" class="pm-thankyou">
                <div class="pm-ty-head">{{ t('formtpl.pvThankYouHead') }}</div>
                <div v-if="fCfg.thank_you_title" class="pm-ty-title">{{ fCfg.thank_you_title }}</div>
                <div v-if="fCfg.thank_you_body" class="pm-ty-body">{{ fCfg.thank_you_body }}</div>
                <button v-if="tyBtnTypeOf(fCfg)==='website'" class="pm-btn">{{ fCfg.thank_you_button_text || t('formtpl.tyBtnWebsite') }}</button>
                <button v-else-if="tyBtnTypeOf(fCfg)==='whatsapp'" class="pm-btn wa">{{ fCfg.thank_you_button_text || t('formtpl.tyBtnWhatsapp') }}</button>
              </div>
            </div>
          </div>
        </div>
        <!-- 右：设置分区 -->
        <div class="fx-right">
          <div class="form">
            <button class="btn ai-top-btn" :disabled="aiLoading" @click="openAssetPicker('form')">{{ aiLoading?t('formtpl.aiGenerating'):t('formtpl.aiFromAssetForm') }}</button>
            <div class="sec-title">{{ t('formtpl.secBasic') }}</div>
            <div class="row"><label>{{ t('formtpl.tplName') }}</label><input v-model="fMeta.name" class="inp" :placeholder="t('formtpl.tplNamePh')" /></div>
            <div class="row">
              <label>{{ t('formtpl.platform') }}</label>
              <div><span :class="['plat-ro', isTtForm ? 'tt' : 'fb']">{{ isTtForm ? 'TikTok' : 'Facebook' }}</span></div>
              <span v-if="isTtForm" class="hint">{{ t('formtpl.ttFieldNote') }}</span>
            </div>
            <div class="row"><label>{{ t('formtpl.language') }}</label><el-select v-model="fMeta.locale" style="width:100%" size="small"><el-option v-for="l in LOCALES" :key="l.v" :value="l.v" :label="l.l" /></el-select></div>

            <hr class="sep" />
            <div class="sec-title">{{ t('formtpl.secContent') }}</div>
            <div class="row"><label>{{ t('formtpl.formTitle') }}</label><input v-model="fCfg.form_title" class="inp" :placeholder="t('formtpl.formTitlePh')" /></div>
            <div class="row"><label>{{ t('formtpl.formDesc') }}</label><input v-model="fCfg.description" class="inp" :placeholder="t('formtpl.formDescPh')" /></div>
            <div class="row"><label>{{ t('formtpl.qStyleLabel') }}</label>
              <el-radio-group v-model="qStyle" size="small">
                <el-radio-button value="open">{{ t('formtpl.qStyleOpen') }}</el-radio-button>
                <el-radio-button value="choice">{{ t('formtpl.qStyleChoice') }}</el-radio-button>
              </el-radio-group>
            </div>

            <hr class="sep" />
            <div class="sec-title">{{ t('formtpl.secContactFields') }}</div>
            <div class="chips">
              <label class="chip on fixed"><input type="checkbox" checked disabled /> {{ t('formtpl.contactFixedName') }}</label>
              <label v-for="f in MAIN_CONTACTS" :key="f.v" class="chip" :class="{on:(fCfg.extra_contact_fields||[]).includes(f.v)}">
                <input type="checkbox" :checked="(fCfg.extra_contact_fields||[]).includes(f.v)" @change="toggleContact(f.v)" /> {{ f.l }}
              </label>
            </div>
            <div class="hint">{{ t('formtpl.contactAutoHint') }}</div>
            <button class="link-btn" @click="showMoreContact=!showMoreContact">{{ showMoreContact ? t('formtpl.contactLess') : t('formtpl.contactMore') }}</button>
            <div v-if="showMoreContact" class="chips sm-mt">
              <label v-for="f in MORE_CONTACTS" :key="f.v" class="chip" :class="{on:(fCfg.extra_contact_fields||[]).includes(f.v)}">
                <input type="checkbox" :checked="(fCfg.extra_contact_fields||[]).includes(f.v)" @change="toggleContact(f.v)" /> {{ f.l }}
              </label>
            </div>

            <hr class="sep" />
            <div class="sec-title-row"><span class="sec-title">{{ t('formtpl.secCustomQuestions') }}</span><button class="btn sm" @click="addQuestion">{{ t('formtpl.addQuestion') }}</button></div>
            <div v-if="!(fCfg.custom_questions||[]).length" class="hint">{{ t('formtpl.qEmptyHint') }}</div>
            <div v-for="(q,i) in fCfg.custom_questions" :key="i" class="question-block">
              <div class="qb-head">
                <span>{{ t('formtpl.questionN', { n: i+1 }) }}</span>
                <span class="qb-ops">
                  <button class="mv-btn" :disabled="i===0" :title="t('formtpl.moveUp')" @click="moveQuestion(i,-1)">↑</button>
                  <button class="mv-btn" :disabled="i===fCfg.custom_questions.length-1" :title="t('formtpl.moveDown')" @click="moveQuestion(i,1)">↓</button>
                  <button class="del-btn" @click="removeQuestion(i)">✕</button>
                </span>
              </div>
              <el-radio-group :model-value="qIsChoice(q)?'choice':'open'" size="small" @change="v => setQType(q, v)">
                <el-radio-button value="open">{{ t('formtpl.qStyleOpen') }}</el-radio-button>
                <el-radio-button value="choice">{{ t('formtpl.qStyleChoice') }}</el-radio-button>
              </el-radio-group>
              <input v-model="q.label" class="inp sm-mt" :placeholder="t('formtpl.questionTextPh')" @input="syncQKey(q)" />
              <input v-if="!qIsChoice(q)" v-model="q.placeholder" class="inp sm-mt" :placeholder="t('formtpl.questionHintPh')" />
              <input v-model="q.key" class="inp sm-mt" :placeholder="t('formtpl.questionKeyPh')" @input="q._keyAuto = false" />
              <div v-if="qIsChoice(q)" class="options-list">
                <div v-for="(o,oi) in q.options" :key="oi" class="option-row">
                  <input v-model="o.value" class="inp sm" :placeholder="t('formtpl.optionTextPh')" />
                  <button class="del-btn sm" @click="removeOption(q,oi)">✕</button>
                </div>
                <button class="btn sm ghost" @click="addOption(q)">{{ t('formtpl.addOption') }}</button>
              </div>
            </div>

            <hr class="sep" />
            <div class="sec-title">{{ t('formtpl.secPrivacy') }}</div>
            <div class="row"><label>{{ t('formtpl.privacyUrl') }}</label><input v-model="fCfg.privacy_url" class="inp" :placeholder="t('formtpl.privacyUrlPh')" /></div>
            <div v-if="!isTtForm" class="row"><label>{{ t('formtpl.privacyLinkText') }}</label><input v-model="fCfg.privacy_link_text" class="inp" /></div>

            <hr class="sep" />
            <div class="sec-title">{{ t('formtpl.secThankYou') }}</div>
            <div class="row"><label>{{ t('formtpl.thankTitle') }}</label><input v-model="fCfg.thank_you_title" class="inp" :placeholder="t('formtpl.thankTitlePh')" /></div>
            <div class="row"><label>{{ t('formtpl.thankBody') }}</label><textarea v-model="fCfg.thank_you_body" class="inp ta" rows="2"></textarea></div>
            <!-- FB thank_you_page 按钮为 FB 专属 → TT 隐藏（TT 只支持成功页文案） -->
            <template v-if="!isTtForm">
              <div class="row"><label>{{ t('formtpl.tyBtnType') }}</label>
                <el-radio-group v-model="fCfg.thank_you_button_type" size="small" @change="onTyBtnType">
                  <el-radio-button value="none">{{ t('formtpl.tyBtnNone') }}</el-radio-button>
                  <el-radio-button value="website">{{ t('formtpl.tyBtnWebsite') }}</el-radio-button>
                  <el-radio-button value="whatsapp">{{ t('formtpl.tyBtnWhatsapp') }}</el-radio-button>
                </el-radio-group>
              </div>
              <div v-if="tyBtnTypeOf(fCfg)!=='none'" class="row"><label>{{ t('formtpl.buttonText') }}</label><input v-model="fCfg.thank_you_button_text" class="inp" :placeholder="t('formtpl.buttonTextPh')" /></div>
              <div v-if="tyBtnTypeOf(fCfg)==='website'" class="row"><label>{{ t('formtpl.buttonLink') }}</label><input v-model="fCfg.thank_you_website_url" class="inp" placeholder="https://..." /></div>
              <template v-if="tyBtnTypeOf(fCfg)==='whatsapp'">
                <div class="row"><label>{{ t('formtpl.waNumber') }}</label><input v-model="fCfg.whatsapp_number" class="inp" :placeholder="t('formtpl.waNumberPh')" /></div>
                <div class="row"><label>{{ t('formtpl.waMsgTpl') }}</label>
                  <el-select v-model="fCfg.whatsapp_msg_tpl_id" style="width:100%" size="small" clearable filterable :placeholder="t('formtpl.waMsgTplPh')">
                    <el-option v-for="m in waMsgOptions" :key="m.id" :value="m.id" :label="m.name" />
                  </el-select>
                </div>
                <div class="hint">{{ t('formtpl.waNote') }}</div>
              </template>
              <div class="row"><label>{{ t('formtpl.followUpLink') }}</label><input v-model="fCfg.follow_up_url" class="inp" placeholder="https://..." /></div>
            </template>

            <!-- 高级设置（FB 专属；TT 无对应概念 → 隐藏） -->
            <template v-if="!isTtForm">
              <hr class="sep" />
              <div class="sec-title">{{ t('formtpl.secAdvanced') }}</div>
              <div class="row"><label>{{ t('formtpl.formVisibility') }}</label>
                <el-select v-model="fCfg.is_optimized_for_quality" style="width:100%" size="small">
                  <el-option :value="true" :label="t('formtpl.visibilityRestricted')" />
                  <el-option :value="false" :label="t('formtpl.visibilityPublic')" />
                </el-select>
              </div>
              <div class="row"><label>{{ t('formtpl.welcomeMessage') }}</label><textarea v-model="fCfg.welcome_message" class="inp ta" rows="2" :placeholder="t('formtpl.welcomeMessagePh')"></textarea></div>
              <div class="row"><label>{{ t('formtpl.targetCountryOnly') }}</label>
                <el-switch v-model="fCfg.block_display_for_non_targeted" active-color="#0a84ff" inactive-color="#3a3a5c" size="small" />
                <span class="hint">{{ t('formtpl.targetCountryHint') }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="formOpen=false">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="saving" @click="saveForm">{{ saving?t('formtpl.saving'):t('common.save') }}</button>
      </template>
    </el-drawer>

    <!-- 消息编辑抽屉（Messenger / WhatsApp 按类型切换文案；宽度与投放模板资产选择器对齐） -->
    <el-drawer v-model="msgOpen" direction="rtl" size="min(560px, 100vw)" :destroy-on-close="true">
      <template #header>
        <div class="dr-head">
          <span class="dr-title">{{ editingMsg ? t('formtpl.editMsg') : t('formtpl.newMsg') }}</span>
          <span :class="['type-chip', isWaMsg ? 'wa' : 'ms']">{{ isWaMsg ? 'WhatsApp' : 'Messenger' }}</span>
        </div>
      </template>
      <div class="form">
        <button class="btn ai-top-btn" :disabled="aiLoading" @click="openAssetPicker('msg')">{{ aiLoading?t('formtpl.aiGenerating'):t('formtpl.aiFromAssetMsg') }}</button>
        <div class="row"><label>{{ t('formtpl.tplName') }}</label><input v-model="mCfg.name" class="inp" /></div>
        <div class="row"><label>{{ t('formtpl.msgType') }}</label>
          <el-radio-group v-model="mCfg.type" size="small">
            <el-radio-button value="messenger">{{ t('formtpl.msgTypeMessenger') }}</el-radio-button>
            <el-radio-button value="whatsapp">{{ t('formtpl.msgTypeWhatsapp') }}</el-radio-button>
          </el-radio-group>
        </div>
        <hr class="sep" />
        <div class="sec-title">{{ isWaMsg ? t('formtpl.secWelcomeWa') : t('formtpl.secWelcome') }}</div>
        <div class="row"><label>{{ isWaMsg ? t('formtpl.mainTextWa') : t('formtpl.mainText') }}</label>
          <textarea v-model="mCfg.welcome_text" class="inp ta" rows="3" :placeholder="isWaMsg ? t('formtpl.welcomeTextWaPh') : t('formtpl.welcomeTextPh')"></textarea>
        </div>
        <hr class="sep" />
        <div class="sec-title-row"><span class="sec-title">{{ t('formtpl.secQuickReplies') }}</span><button class="btn sm" @click="addIB">{{ t('formtpl.addOne') }}</button></div>
        <div v-for="(ib,i) in mCfg.ice_breakers" :key="i" class="ib-block">
          <div class="qb-head"><span>{{ t('formtpl.quickReplyN', { n: i+1 }) }}</span><button class="del-btn" @click="removeIB(i)">✕</button></div>
          <input v-model="ib.title" class="inp" :placeholder="t('formtpl.ibButtonTextPh')" />
          <textarea v-model="ib.response" class="inp ta sm-mt" rows="2" :placeholder="t('formtpl.ibResponsePh')"></textarea>
        </div>
        <div v-if="!mCfg.ice_breakers.length" class="hint">{{ isWaMsg ? t('formtpl.ibEmptyHintWa') : t('formtpl.ibEmptyHint') }}</div>
      </div>
      <template #footer>
        <button class="btn" @click="msgOpen=false">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="saving" @click="saveMsg">{{ saving?t('formtpl.saving'):t('common.save') }}</button>
      </template>
    </el-drawer>

    <!-- 素材选择器（AI 生成用） -->
    <el-drawer v-model="assetPickerOpen" :title="t('formtpl.pickerTitle')" direction="rtl" size="min(520px, 100vw)" append-to-body>
      <div class="hint" style="margin-bottom:10px">{{ t('formtpl.pickerHint') }}</div>
      <div class="picker-grid">
        <div v-for="a in pickerAssets" :key="a.id" class="picker-card" @click="pickAsset(a)">
          <img v-if="a.type==='image'" :src="a.public_url" class="picker-thumb" />
          <video v-else :src="a.public_url" class="picker-thumb" preload="metadata" />
          <span class="picker-name">{{ a.name }}</span>
        </div>
      </div>
    </el-drawer>

    <!-- 预览弹窗 -->
    <el-dialog v-model="previewOpen" :title="previewType==='form'?t('formtpl.previewFormTitle'):t('formtpl.previewMsgTitle')" width="420px" append-to-body>
      <!-- 表单预览：手机壳（与编辑器左侧实时预览同结构） -->
      <div v-if="previewType==='form' && previewData" class="phone-mockup">
        <div class="pm-screen">
          <div class="pm-header">{{ previewData.form_title || t('formtpl.pmFormTitle') }}</div>
          <div v-if="previewData.description" class="pm-desc">{{ previewData.description }}</div>
          <div class="pm-contact-head">{{ t('formtpl.pvContact') }}</div>
          <div class="pm-chips">
            <span v-for="c in contactsOf(previewData)" :key="c.v" class="pm-chip">{{ c.l }}<em v-if="isAutoContact(previewData, c.v)" class="pm-auto">{{ t('formtpl.pvAuto') }}</em></span>
          </div>
          <div v-for="(q,i) in (previewData.custom_questions||[])" :key="'q'+i" class="pm-qcard">
            <div class="pm-label">{{ q.label || t('formtpl.pmQuestion') }}</div>
            <div v-if="qIsChoice(q)" class="pm-options">
              <span v-for="(o,oi) in q.options" :key="oi" class="pm-option">{{ o.value }}</span>
            </div>
            <div v-else class="pm-input-mock">—</div>
          </div>
          <button class="pm-submit">{{ t('formtpl.pmSubmit') }}</button>
          <a class="pm-privacy">{{ previewData.privacy_link_text || 'Privacy Policy' }}</a>
          <div v-if="previewData.thank_you_title || previewData.thank_you_body || tyBtnTypeOf(previewData) !== 'none'" class="pm-thankyou">
            <div class="pm-ty-head">{{ t('formtpl.pvThankYouHead') }}</div>
            <div v-if="previewData.thank_you_title" class="pm-ty-title">{{ previewData.thank_you_title }}</div>
            <div v-if="previewData.thank_you_body" class="pm-ty-body">{{ previewData.thank_you_body }}</div>
            <button v-if="tyBtnTypeOf(previewData)==='website'" class="pm-btn">{{ previewData.thank_you_button_text || t('formtpl.tyBtnWebsite') }}</button>
            <button v-else-if="tyBtnTypeOf(previewData)==='whatsapp'" class="pm-btn wa">{{ previewData.thank_you_button_text || t('formtpl.tyBtnWhatsapp') }}</button>
          </div>
        </div>
      </div>
      <!-- 消息预览：Messenger / WhatsApp mockup -->
      <div v-if="previewType==='msg' && previewData" :class="['messenger-mockup', isWaPreview ? 'wa' : '']">
        <div class="mm-app">{{ isWaPreview ? 'WhatsApp' : 'Messenger' }}</div>
        <div class="mm-bubble">{{ previewData.welcome_text }}</div>
        <div v-if="(previewData.ice_breakers||[]).length" class="mm-quick-replies">
          <span v-for="(ib,i) in previewData.ice_breakers" :key="i" class="mm-qr">{{ ib.title }}</span>
        </div>
      </div>
    </el-dialog>
  </div>

    <!-- 新建表单 → 选平台弹窗（建后不可改） -->
    <el-dialog v-model="formPlatDialog" :title="t('formtpl.pickPlatTitle')" width="380px" append-to-body>
      <div style="display:flex;gap:12px">
        <button class="plat-pick fb" @click="formPlatDialog = false; openFormNew('fb')">
          <span class="pp-dot fb"></span>{{ t('formtpl.newFormFb') }}
        </button>
        <button class="plat-pick tt" @click="formPlatDialog = false; openFormNew('tt')">
          <span class="pp-dot tt"></span>{{ t('formtpl.newFormTt') }}
        </button>
      </div>
      <div class="pp-hint">{{ t('formtpl.pickPlatHint') }}</div>
    </el-dialog>
</template>

<style scoped>
.page{display:flex;flex-direction:column;gap:14px}
.bar{display:flex;justify-content:space-between;align-items:center}
.tabs{display:flex;gap:3px;background:var(--bg3);padding:3px;border-radius:8px}
.tab{padding:7px 16px;border:none;background:transparent;color:var(--t3);border-radius:6px;cursor:pointer;font-size:13px;font-family:inherit;font-weight:500}
.tab.on{background:var(--bg2);color:var(--t1)}
.btn{padding:7px 14px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:6px;font-size:13px;cursor:pointer;font-family:inherit}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn.sm{padding:4px 10px;font-size:12px}
.btn.ghost{background:transparent;color:var(--t3)}
.btn:disabled{opacity:.5}
/* 编辑器平台只读标（列表 chip 用 main.css 全局 .plat-chip；视觉对齐 LaunchTemplates .plat-ro） */
.plat-ro{display:inline-flex;align-items:center;gap:4px;font-size:13px;font-weight:600;padding:4px 14px;border-radius:8px;border:1px solid}
.plat-ro.fb{background:rgba(24,119,242,.08);color:#5aa2ff;border-color:rgba(24,119,242,.35)}
.plat-ro.tt{background:rgba(254,44,85,.08);color:#ff6f8d;border-color:rgba(254,44,85,.35)}
.ai-top-btn{width:100%;border-style:dashed;border-color:var(--ac);color:var(--ac);background:rgba(10,132,255,.06)}
.ai-top-btn:hover{background:rgba(10,132,255,.14)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:var(--rs)   /* UI审计#8：容器圆角归一 */;padding:12px 14px;display:flex;flex-direction:column;gap:8px;transition:border-color .15s,box-shadow .15s,transform .15s}
.card:hover{border-color:var(--bd2);box-shadow:var(--shadow-card);transform:translateY(-1px)}
.card-head{display:flex;justify-content:space-between;align-items:baseline;gap:6px}
.card-name{font-size:14px;font-weight:600;color:var(--t1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-copy{font-size:11px;color:var(--t2);line-height:1.5;font-style:italic;max-height:32px;overflow:hidden}
.card-meta{display:flex;gap:10px;font-size:11px;color:var(--t3);flex-wrap:wrap;align-items:center}
.card-badge{font-size:10px;padding:2px 8px;border-radius:8px;font-weight:600;white-space:nowrap;flex-shrink:0}
.card-badge.ready{color:var(--success);background:rgba(52,199,89,.13)}
.card-badge.draft{color:var(--t3);background:var(--bg3)}
.card-ops{display:flex;gap:5px;margin-top:auto;padding-top:8px}
.op{background:none;border:1px solid var(--bd);color:var(--t2);font-size:11px;cursor:pointer;padding:3px 8px;border-radius:4px}
.op.primary{color:var(--ac);border-color:var(--ac)}
.op.danger{color:var(--error)}
.op.dots{font-size:15px;line-height:1;padding:3px 10px}
.op:hover{background:var(--bg3)}
.empty{grid-column:1/-1;padding:40px;text-align:center;color:var(--t3);font-size:14px;display:flex;flex-direction:column;align-items:center;gap:14px}
.empty-cta{align-self:center}
/* 抽屉 Header：标题 + 平台/类型 chip（与投放模板编辑器头部一致；关闭钮为 EP 默认） */
.dr-head{display:flex;align-items:center;gap:8px;min-width:0;flex-wrap:wrap}
.dr-title{font-size:15px;font-weight:600;color:var(--t1)}
.type-chip{display:inline-block;font-size:10px;font-weight:600;padding:1px 7px;border-radius:8px;color:var(--t3);background:var(--bg3);border:1px solid var(--bd)}
.type-chip.ms{color:#5aa2ff;background:rgba(24,119,242,.12);border-color:rgba(24,119,242,.35)}
.type-chip.wa{color:#4ade80;background:rgba(37,211,102,.12);border-color:rgba(37,211,102,.4)}
/* 消息模板类型 chip（Messenger 蓝 / WhatsApp 绿） */
.msg-chip{display:inline-block;font-size:10px;font-weight:600;padding:1px 7px;border-radius:8px;margin-right:6px;vertical-align:1px}
.msg-chip.ms{color:#5aa2ff;background:rgba(24,119,242,.12);border:1px solid rgba(24,119,242,.35)}
.msg-chip.wa{color:#4ade80;background:rgba(37,211,102,.12);border:1px solid rgba(37,211,102,.4)}
/* 编辑器：左预览 + 右设置 */
.fx-editor{display:flex;gap:20px;align-items:flex-start}
.fx-left{flex:0 0 342px;position:sticky;top:0}
.fx-left-head{font-size:11px;color:var(--t3);text-align:center;margin-bottom:8px;font-weight:500}
.fx-right{flex:1;min-width:0}
.form{display:flex;flex-direction:column;gap:12px}
.row{display:flex;flex-direction:column;gap:4px}
.row label{font-size:12px;color:var(--t3);font-weight:500}
.inp{padding:6px 10px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:13px;font-family:inherit}
.inp:focus{border-color:var(--ac);outline:none}
.inp.ta{resize:vertical}
.inp.sm{padding:4px 8px;font-size:12px}
.sm-mt{margin-top:4px}
.sep{border:none;border-top:1px solid var(--bd);margin:6px 0}
.sec-title{font-size:12px;color:var(--ac);font-weight:600}
.sec-title-row{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.sec-title-row .sec-title{margin:0}
.hint{font-size:11px;color:var(--t3);padding:4px 0}
.chips{display:flex;gap:4px;flex-wrap:wrap}
.chip{font-size:12px;padding:4px 10px;border:1px solid var(--bd);border-radius:6px;cursor:pointer;color:var(--t3);display:flex;align-items:center;gap:3px}
.chip input{margin:0}
.chip.on{border-color:var(--ac);color:var(--ac);background:rgba(10,132,255,.1)}
.chip.fixed{opacity:.7;cursor:default}
.link-btn{background:none;border:none;color:var(--ac);font-size:11px;cursor:pointer;padding:2px 0;font-family:inherit;text-align:left}
.link-btn:hover{text-decoration:underline}
.question-block{background:var(--bg3);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column;gap:4px}
.qb-head{display:flex;justify-content:space-between;align-items:center;font-size:11px;color:var(--t3)}
.qb-ops{display:flex;gap:2px;align-items:center}
.mv-btn{background:none;border:1px solid var(--bd);color:var(--t3);cursor:pointer;font-size:11px;line-height:1;padding:3px 7px;border-radius:4px}
.mv-btn:hover:not(:disabled){color:var(--ac);border-color:var(--ac)}
.mv-btn:disabled{opacity:.3;cursor:default}
.del-btn{background:none;border:none;color:var(--t3);cursor:pointer;font-size:13px;padding:2px 6px}
.del-btn:hover{color:var(--error)}
.del-btn.sm{font-size:11px;padding:2px 4px}
.options-list{display:flex;flex-direction:column;gap:4px;margin-top:4px}
.option-row{display:flex;gap:4px;align-items:center}
.ib-block{background:var(--bg3);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column;gap:4px}
.picker-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px}
.picker-card{background:var(--bg2);border:1px solid var(--bd);border-radius:8px;overflow:hidden;cursor:pointer}
.picker-card:hover{border-color:var(--ac)}
.picker-thumb{width:100%;height:80px;object-fit:cover}
.picker-name{display:block;font-size:11px;color:var(--t2);padding:3px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* 表单预览 mockup（FB Instant Form 视觉顺序：标题→描述→联系字段→逐题→提交→隐私→感谢页） */
.phone-mockup{max-width:340px;margin:0 auto;border:3px solid var(--bd);border-radius:24px;overflow:hidden;background:var(--bg2)}
.pm-screen{padding:16px;display:flex;flex-direction:column;gap:10px;max-height:calc(100vh - 200px);overflow-y:auto}
.pm-header{font-size:16px;font-weight:700;color:var(--t1);text-align:center}
.pm-header.muted{color:var(--t3);font-weight:500}
.pm-desc{font-size:12px;color:var(--t3);text-align:center}
.pm-contact-head{font-size:11px;font-weight:600;color:var(--t2);margin-top:2px}
.pm-chips{display:flex;gap:4px;flex-wrap:wrap}
.pm-chip{font-size:10px;padding:3px 9px;background:var(--bg3);color:var(--t2);border:1px solid var(--bd);border-radius:10px;display:inline-flex;align-items:center;gap:4px}
.pm-auto{font-style:normal;font-size:9px;color:var(--t3);border-left:1px solid var(--bd);padding-left:4px}
.pm-qcard{display:flex;flex-direction:column;gap:3px;background:var(--bg3);border-radius:8px;padding:8px 10px}
.pm-label{font-size:11px;color:var(--t2);font-weight:500}
.pm-label.muted{color:var(--t3);font-weight:400}
.pm-input-mock{background:var(--bg2);border:1px solid var(--bd);border-radius:4px;height:26px;display:flex;align-items:center;padding:0 8px;color:var(--t3);font-size:11px;overflow:hidden;white-space:nowrap}
.pm-options{display:flex;gap:4px;flex-wrap:wrap}
.pm-option{font-size:10px;padding:2px 8px;background:var(--acg);color:var(--ac);border-radius:var(--rs)   /* UI审计#8：容器圆角归一 */;border:1px solid var(--ac)}
.pm-submit{padding:10px;background:var(--ac);color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:default;font-family:inherit}
.pm-privacy{font-size:10px;color:var(--t3);text-align:center;margin-top:4px;cursor:pointer}
.pm-thankyou{border-top:1px dashed var(--bd);padding-top:8px;margin-top:4px}
.pm-ty-head{font-size:9px;color:var(--t3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
.pm-ty-title{font-size:13px;font-weight:600;color:var(--success)}
.pm-ty-body{font-size:11px;color:var(--t2);margin-top:2px}
.pm-btn{margin-top:6px;padding:8px;background:var(--ac);color:#fff;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:default;font-family:inherit}
.pm-btn.wa{background:#25d366;color:#052e16}
/* Messenger / WhatsApp 预览 */
.messenger-mockup{max-width:340px;margin:0 auto;background:var(--bg3);border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:10px}
.mm-app{font-size:11px;font-weight:600;color:var(--t3);padding-bottom:6px;border-bottom:1px solid var(--bd)}
.mm-bubble{background:var(--ac);color:#fff;padding:10px 14px;border-radius:14px 14px 14px 4px;font-size:13px;line-height:1.5;align-self:flex-start;max-width:85%}
.mm-quick-replies{display:flex;gap:6px;flex-wrap:wrap}
.mm-qr{font-size:12px;padding:5px 12px;background:var(--bg2);border:1px solid var(--ac);color:var(--ac);border-radius:16px}
.messenger-mockup.wa .mm-bubble{background:#005c4b}
.messenger-mockup.wa .mm-qr{border-color:#25d366;color:#4ade80}
</style>

<style scoped>
.plat-pick { flex: 1; display: flex; align-items: center; justify-content: center; gap: 8px; padding: 18px 0; border: 1px solid var(--bd); border-radius: 10px; background: var(--bg2); cursor: pointer; font-size: 14px; font-family: inherit; color: var(--t1); transition: border-color .15s, background .15s; }
.plat-pick:hover { border-color: var(--ac); background: var(--bg3); }
.plat-pick.fb:hover { border-color: #1877f2; }
.plat-pick.tt:hover { border-color: #fe2c55; }
.pp-dot { width: 10px; height: 10px; border-radius: 50%; }
.pp-dot.fb { background: #1877f2; }
.pp-dot.tt { background: linear-gradient(135deg, #25f4ee 45%, #fe2c55 55%); }
.pp-hint { font-size: 11px; color: var(--t3); margin-top: 10px; line-height: 1.5; }
/* <900：编辑器左右 → 上下堆叠，左预览取消 sticky 跟随文档流（置于设置区下方） */
@media (max-width: 900px) {
  .fx-editor { flex-direction: column-reverse; }
  .fx-left { position: static; flex: none; width: 100%; }
  .fx-left .phone-mockup { max-width: 360px; }
}
/* 手机（<768，抽屉已被 main.css 全局规则撑满 100%）：预览壳 340px 居中缩放；
   问题卡 ↑↓/增删小钮放大到触屏可点，不挤出屏幕 */
@media (max-width: 768px) {
  .fx-editor { gap: 14px; }
  .fx-left .phone-mockup { max-width: 340px; }
  .mv-btn, .del-btn { min-height: 32px; min-width: 32px; }
  /* 列表卡片单列堆叠 + 卡操作按钮换行（对齐 LaunchTemplates 移动端） */
  .grid { grid-template-columns: 1fr !important; }
  .card-ops { flex-wrap: wrap; }
  .card-ops .op { min-height: 32px; }
  .card-head { flex-wrap: wrap; }
}
</style>
