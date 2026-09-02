<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { showError } from '../composables/useError'
import { useRouter } from 'vue-router'

const { t } = useI18n()
const router = useRouter()
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
// 列表平台筛选（表单 tab；消息模板为 FB Messenger 专属不过滤）
const formPlatFilter = ref('all')
const filteredForms = computed(() =>
  formPlatFilter.value === 'all' ? forms.value : forms.value.filter(f => (f.platform || 'fb') === formPlatFilter.value))

// 消息编辑
const msgOpen = ref(false)
const editingMsg = ref(null)
const mCfg = ref({ name: '', welcome_text: '', ice_breakers: [] })

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
const CONTACT_FIELDS = computed(() => [
  {v:'EMAIL',l:t('formtpl.contact.email')},{v:'PHONE',l:t('formtpl.contact.phone')},{v:'CITY',l:t('formtpl.contact.city')},{v:'STATE',l:t('formtpl.contact.state')},
  {v:'ZIP_CODE',l:t('formtpl.contact.zip')},{v:'COUNTRY',l:t('formtpl.contact.country')},{v:'DATE_OF_BIRTH',l:t('formtpl.contact.dob')},{v:'GENDER',l:t('formtpl.contact.gender')},
  {v:'MARITAL_STATUS',l:t('formtpl.contact.marital')},{v:'LAST_NAME',l:t('formtpl.contact.lastName')},
])

const load = async () => {
  loading.value = true
  try { forms.value = await GET('/form-templates/forms'); messages.value = await GET('/form-templates/messages') }
  catch (e) { showError(e, t('formtpl.loadFail')) }
  loading.value = false
}
onMounted(load)

// ── 表单 ──
const blankForm = () => ({
  form_title: '', description: '', privacy_url: '', privacy_link_text: 'Privacy Policy',
  target_countries: [], extra_contact_fields: ['EMAIL'],
  custom_questions: [], thank_you_title: '', thank_you_body: '',
  thank_you_button_text: '', thank_you_website_url: '', follow_up_url: '', context_card_title: '',
  is_optimized_for_quality: true,
  welcome_message: '', block_display_for_non_targeted: false,
})
const openFormNew = (p) => {
  editingForm.value = null; fPlat.value = p === 'tt' ? 'tt' : 'fb'
  fMeta.value = { name: '', description: '', locale: 'en_US' }; fCfg.value = blankForm(); formOpen.value = true
}
const openFormEdit = (t) => {
  editingForm.value = t; fPlat.value = (t.platform === 'tt') ? 'tt' : 'fb'
  fMeta.value = { name: t.name, description: t.description, locale: t.locale }
  const cfg = { ...blankForm(), ...(t.config || {}) }
  // _keyAuto：key 仍处自动态（服务端原值为空）时 label 改动可继续同步 slug
  cfg.custom_questions = (cfg.custom_questions || []).map(q => ({ ...q, _keyAuto: !q.key }))
  fCfg.value = cfg; formOpen.value = true
}
const addQuestion = () => fCfg.value.custom_questions.push({ key: '', label: '', placeholder: '', options: [], _keyAuto: true })
const removeQuestion = (i) => fCfg.value.custom_questions.splice(i, 1)
// q.key 自动 slug：label 变化且 key 未被手改（_keyAuto）时同步生成英文 key；手改后不再覆盖
const slugifyKey = (label) => String(label || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40)
const syncQKey = (q) => { if (q._keyAuto) q.key = slugifyKey(q.label) }
const addOption = (q) => q.options.push({ key: '', value: '' })
const removeOption = (q, i) => q.options.splice(i, 1)
const toggleContact = (v) => {
  const arr = fCfg.value.extra_contact_fields || []
  const i = arr.indexOf(v)
  if (i >= 0) arr.splice(i, 1); else arr.push(v)
}
const saveForm = async () => {
  if (!fMeta.value.name.trim()) return ElMessage.warning(t('formtpl.needName'))
  if (!fCfg.value.form_title.trim()) return ElMessage.warning(t('formtpl.needFormTitle'))
  if (!fCfg.value.privacy_url.trim()) return ElMessage.warning(t('formtpl.needPrivacyUrl'))
  saving.value = true
  try {
    // 剥掉前端内部标记（_keyAuto），不进 config 存储/FB 请求
    const cfgOut = JSON.parse(JSON.stringify(fCfg.value))
    cfgOut.custom_questions = (cfgOut.custom_questions || []).map(({ _keyAuto, ...q }) => q)
    const body = { name: fMeta.value.name, description: fMeta.value.description, locale: fMeta.value.locale, platform: fPlat.value, config: cfgOut }
    if (editingForm.value) { await PUT('/form-templates/forms/' + editingForm.value.id, body); ElMessage.success(t('common.saved')) }
    else { await POST('/form-templates/forms', body); ElMessage.success(t('common.create') + t('common.success')) }
    formOpen.value = false; await load()
  } catch (e) { showError(e, t('common.opFail')) }
  saving.value = false
}
const removeForm = async (t) => {
  try { await ElMessageBox.confirm(t('formtpl.archiveConfirm', { name: t.name }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' }); await DELETE('/form-templates/forms/' + t.id); ElMessage.success(t('formtpl.archived')); await load() }
  catch (e) { if (e !== 'cancel') ElMessage.error(e.message || t('common.opFail')) }   // 被引用等真报错要提示
}
const previewForm = (t) => { previewType.value = 'form'; previewData.value = t.config || {}; previewOpen.value = true }

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
const loadAssets = async () => { try { pickerAssets.value = await GET('/assets') } catch {} }
const pickAsset = (a) => { pickerMode.value === 'msg' ? aiGenerateMsg(a) : aiGenerate(a) }
const aiGenerate = async (a) => {
  assetPickerOpen.value = false; aiLoading.value = true
  try {
    const r = await POST('/form-templates/forms/ai-generate', { asset_id: a.id, country: (fCfg.value.target_countries||[])[0] || '', locale: fMeta.value.locale || 'en_US', purpose: aiPurposeInput.value })
    const cfg = r.config || {}
    if (cfg.form_title) fCfg.value.form_title = cfg.form_title
    if (cfg.description) fCfg.value.description = cfg.description
    if (cfg.custom_questions) fCfg.value.custom_questions = cfg.custom_questions.map(q => ({ ...q, _keyAuto: !q.key }))
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
const openMsgNew = () => { editingMsg.value = null; mCfg.value = { name: '', welcome_text: '', ice_breakers: [] }; msgOpen.value = true }
const openMsgEdit = (t) => { editingMsg.value = t; mCfg.value = { name: t.name, welcome_text: t.welcome_text, ice_breakers: [...(t.ice_breakers||[])] }; msgOpen.value = true }
const addIB = () => mCfg.value.ice_breakers.push({ title: '', response: '' })
const removeIB = (i) => mCfg.value.ice_breakers.splice(i, 1)
const saveMsg = async () => {
  if (!mCfg.value.name.trim()) return ElMessage.warning(t('formtpl.needName'))
  if (!mCfg.value.welcome_text.trim()) return ElMessage.warning(t('formtpl.needWelcome'))
  saving.value = true
  try {
    const body = { name: mCfg.value.name, welcome_text: mCfg.value.welcome_text, ice_breakers: mCfg.value.ice_breakers }
    if (editingMsg.value) { await PUT('/form-templates/messages/' + editingMsg.value.id, body); ElMessage.success(t('common.saved')) }
    else { await POST('/form-templates/messages', body); ElMessage.success(t('common.create') + t('common.success')) }
    msgOpen.value = false; await load()
  } catch (e) { showError(e, t('common.opFail')) }
  saving.value = false
}
const removeMsg = async (t) => {
  try { await ElMessageBox.confirm(t('formtpl.archiveConfirm', { name: t.name }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' }); await DELETE('/form-templates/messages/' + t.id); ElMessage.success(t('formtpl.archived')); await load() }
  catch (e) { if (e !== 'cancel') ElMessage.error(e.message || t('common.opFail')) }
}
const previewMsg = (t) => { previewType.value = 'msg'; previewData.value = t; previewOpen.value = true }
</script>

<template>
  <div class="page">
    <div class="bar">
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <div class="tabs">
          <button :class="['tab',{on:tab==='form'}]" @click="tab='form'">Instant Form</button>
          <button :class="['tab',{on:tab==='msg'}]" @click="tab='msg'">{{ t('formtpl.tabMsg') }}</button>
        </div>
        <div v-if="tab==='form'" class="tabs">
          <button :class="['tab',{on:formPlatFilter==='all'}]" @click="formPlatFilter='all'">{{ t('common.all') }}</button>
          <button :class="['tab',{on:formPlatFilter==='fb'}]" @click="formPlatFilter='fb'">Facebook</button>
          <button :class="['tab',{on:formPlatFilter==='tt'}]" @click="formPlatFilter='tt'">TikTok</button>
        </div>
      </div>
      <!-- 表单建时选平台（payload 按平台构建，建后不可改）；消息模板保持单按钮 -->
      <button v-if="tab==='form'" class="btn primary" @click="formPlatDialog = true">+ {{ t('formtpl.newBtn', { kind: t('formtpl.formUnit') }) }}</button>
      <button v-else class="btn primary" @click="openMsgNew()">{{ t('formtpl.newBtn', { kind: t('formtpl.msgUnit') }) }}</button>
    </div>

    <!-- Instant Form 列表 -->
    <div v-if="tab==='form'" class="grid" v-loading="loading">
      <div v-for="item in filteredForms" :key="item.id" class="card">
        <div class="card-head">
          <span class="card-name"><span :class="['plat-chip', item.platform==='tt'?'tt':'fb']">{{ (item.platform||'fb').toUpperCase() }}</span>{{ item.name }}</span>
          <span v-if="item.fb_form_id" class="badge ok">{{ t('formtpl.deployed') }}</span>
        </div>
        <div class="card-meta">
          <span>{{ (item.config||{}).form_title || '—' }}</span>
          <span>{{ t('formtpl.questionsCount', { n: ((item.config||{}).custom_questions||[]).length }) }}</span>
          <span>{{ item.locale }}</span>
        </div>
        <div class="card-ops">
          <button class="op" @click="previewForm(item)">{{ t('common.preview') }}</button>
          <button class="op" @click="openFormEdit(item)">{{ t('common.edit') }}</button>
          <button class="op danger" @click="removeForm(item)">{{ t('formtpl.archive') }}</button>
        </div>
      </div>
      <div v-if="!filteredForms.length && !loading" class="empty">{{ formPlatFilter==='all' || !forms.length ? t('formtpl.noForms') : t('formtpl.noFormsForPlat') }}</div>
    </div>

    <!-- Messenger 列表 -->
    <div v-if="tab==='msg'" class="grid" v-loading="loading">
      <div v-for="item in messages" :key="item.id" class="card">
        <div class="card-head"><span class="card-name">{{ item.name }}</span></div>
        <div class="card-msg-preview">{{ (item.welcome_text||'').slice(0,60) }}{{ (item.welcome_text||'').length>60?'…':'' }}</div>
        <div class="card-meta"><span>{{ t('formtpl.quickRepliesCount', { n: (item.ice_breakers||[]).length }) }}</span></div>
        <div class="card-ops">
          <button class="op" @click="previewMsg(item)">{{ t('common.preview') }}</button>
          <button class="op" @click="openMsgEdit(item)">{{ t('common.edit') }}</button>
          <button class="op danger" @click="removeMsg(item)">{{ t('formtpl.archive') }}</button>
        </div>
      </div>
      <div v-if="!messages.length && !loading" class="empty">{{ t('formtpl.noMessages') }}</div>
    </div>

    <!-- 表单编辑抽屉 -->
    <el-drawer v-model="formOpen" :title="editingForm?t('formtpl.editForm'):t('formtpl.newForm')" direction="rtl" size="640px" :destroy-on-close="true">
      <div class="form">
        <button class="btn ai-top-btn" :disabled="aiLoading" @click="openAssetPicker('form')">{{ aiLoading?t('formtpl.aiGenerating'):t('formtpl.aiFromAssetForm') }}</button>
        <div class="row"><label>{{ t('formtpl.tplName') }}</label><input v-model="fMeta.name" class="inp" :placeholder="t('formtpl.tplNamePh')" /></div>
        <div class="row">
          <label>{{ t('formtpl.platform') }}</label>
          <div><span :class="['plat-ro', isTtForm ? 'tt' : 'fb']">{{ isTtForm ? '🎵 TikTok' : '📘 Facebook' }}</span></div>
          <span v-if="isTtForm" class="hint">{{ t('formtpl.ttFieldNote') }}</span>
        </div>
        <hr class="sep" />
        <div class="sec-title">{{ t('formtpl.secFormInfo') }}</div>
        <div class="row"><label>{{ t('formtpl.formTitle') }}</label><input v-model="fCfg.form_title" class="inp" :placeholder="t('formtpl.formTitlePh')" /></div>
        <div class="row"><label>{{ t('formtpl.formDesc') }}</label><input v-model="fCfg.description" class="inp" :placeholder="t('formtpl.formDescPh')" /></div>
        <div class="row"><label>{{ t('formtpl.language') }}</label><el-select v-model="fMeta.locale" style="width:100%" size="small"><el-option v-for="l in LOCALES" :key="l.v" :value="l.v" :label="l.l" /></el-select></div>
        <div class="row"><label>{{ t('formtpl.privacyUrl') }}</label><input v-model="fCfg.privacy_url" class="inp" :placeholder="t('formtpl.privacyUrlPh')" /></div>
        <!-- 以下为 FB Instant Form 专属设置，TT 表单无对应概念 → 隐藏 -->
        <div v-if="!isTtForm" class="row"><label>{{ t('formtpl.privacyLinkText') }}</label><input v-model="fCfg.privacy_link_text" class="inp" /></div>
        <div v-if="!isTtForm" class="row"><label>{{ t('formtpl.formVisibility') }}</label>
          <el-select v-model="fCfg.is_optimized_for_quality" style="width:100%" size="small">
            <el-option :value="true" :label="t('formtpl.visibilityRestricted')" />
            <el-option :value="false" :label="t('formtpl.visibilityPublic')" />
          </el-select>
        </div>
        <div v-if="!isTtForm" class="row"><label>{{ t('formtpl.welcomeMessage') }}</label><textarea v-model="fCfg.welcome_message" class="inp ta" rows="2" :placeholder="t('formtpl.welcomeMessagePh')"></textarea></div>
        <div v-if="!isTtForm" class="row"><label>{{ t('formtpl.targetCountryOnly') }}</label>
          <el-switch v-model="fCfg.block_display_for_non_targeted" active-color="#0a84ff" inactive-color="#3a3a5c" size="small" />
          <span class="hint">{{ t('formtpl.targetCountryHint') }}</span>
        </div>
        <hr class="sep" />
        <div class="sec-title">{{ t('formtpl.secContactFields') }}</div>
        <div class="chips">
          <label v-for="f in CONTACT_FIELDS" :key="f.v" class="chip" :class="{on:(fCfg.extra_contact_fields||[]).includes(f.v)}">
            <input type="checkbox" :checked="(fCfg.extra_contact_fields||[]).includes(f.v)" @change="toggleContact(f.v)" /> {{ f.l }}
          </label>
        </div>
        <hr class="sep" />
        <div class="sec-title-row"><span class="sec-title">{{ t('formtpl.secCustomQuestions') }}</span><button class="btn sm" @click="addQuestion">{{ t('formtpl.addQuestion') }}</button></div>
        <div v-for="(q,i) in fCfg.custom_questions" :key="i" class="question-block">
          <div class="qb-head"><span>{{ t('formtpl.questionN', { n: i+1 }) }}</span><button class="del-btn" @click="removeQuestion(i)">✕</button></div>
          <input v-model="q.label" class="inp" :placeholder="t('formtpl.questionTextPh')" @input="syncQKey(q)" />
          <input v-model="q.placeholder" class="inp sm-mt" :placeholder="t('formtpl.questionHintPh')" />
          <input v-model="q.key" class="inp sm-mt" :placeholder="t('formtpl.questionKeyPh')" @input="q._keyAuto = false" />
          <div v-if="q.options && q.options.length" class="options-list">
            <div v-for="(o,oi) in q.options" :key="oi" class="option-row">
              <input v-model="o.value" class="inp sm" :placeholder="t('formtpl.optionTextPh')" />
              <button class="del-btn sm" @click="removeOption(q,oi)">✕</button>
            </div>
          </div>
          <button class="btn sm ghost" @click="addOption(q)" v-if="!q.options || !q.options.length">{{ t('formtpl.addOptionMakeChoice') }}</button>
          <button class="btn sm ghost" @click="addOption(q)" v-else>{{ t('formtpl.addOption') }}</button>
        </div>
        <hr class="sep" />
        <div class="sec-title">{{ t('formtpl.secThankYou') }}</div>
        <div class="row"><label>{{ t('formtpl.thankTitle') }}</label><input v-model="fCfg.thank_you_title" class="inp" :placeholder="t('formtpl.thankTitlePh')" /></div>
        <div class="row"><label>{{ t('formtpl.thankBody') }}</label><textarea v-model="fCfg.thank_you_body" class="inp ta" rows="2"></textarea></div>
        <!-- FB thank_you_page 按钮/跟进链接为 FB 专属 → TT 隐藏 -->
        <template v-if="!isTtForm">
          <div class="row"><label>{{ t('formtpl.buttonText') }}</label><input v-model="fCfg.thank_you_button_text" class="inp" :placeholder="t('formtpl.buttonTextPh')" /></div>
          <div class="row"><label>{{ t('formtpl.buttonLink') }}</label><input v-model="fCfg.thank_you_website_url" class="inp" placeholder="https://..." /></div>
          <div class="row"><label>{{ t('formtpl.followUpLink') }}</label><input v-model="fCfg.follow_up_url" class="inp" placeholder="https://..." /></div>
        </template>
      </div>
      <template #footer>
        <button class="btn" @click="formOpen=false">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="saving" @click="saveForm">{{ saving?t('formtpl.saving'):t('common.save') }}</button>
      </template>
    </el-drawer>

    <!-- 消息编辑抽屉 -->
    <el-drawer v-model="msgOpen" :title="editingMsg?t('formtpl.editMsg'):t('formtpl.newMsg')" direction="rtl" size="560px" :destroy-on-close="true">
      <div class="form">
        <button class="btn ai-top-btn" :disabled="aiLoading" @click="openAssetPicker('msg')">{{ aiLoading?t('formtpl.aiGenerating'):t('formtpl.aiFromAssetMsg') }}</button>
        <div class="row"><label>{{ t('formtpl.tplName') }}</label><input v-model="mCfg.name" class="inp" /></div>
        <hr class="sep" />
        <div class="sec-title">{{ t('formtpl.secWelcome') }}</div>
        <div class="row"><label>{{ t('formtpl.mainText') }}</label><textarea v-model="mCfg.welcome_text" class="inp ta" rows="3" :placeholder="t('formtpl.welcomeTextPh')"></textarea></div>
        <hr class="sep" />
        <div class="sec-title-row"><span class="sec-title">{{ t('formtpl.secQuickReplies') }}</span><button class="btn sm" @click="addIB">{{ t('formtpl.addOne') }}</button></div>
        <div v-for="(ib,i) in mCfg.ice_breakers" :key="i" class="ib-block">
          <div class="qb-head"><span>{{ t('formtpl.quickReplyN', { n: i+1 }) }}</span><button class="del-btn" @click="removeIB(i)">✕</button></div>
          <input v-model="ib.title" class="inp" :placeholder="t('formtpl.ibButtonTextPh')" />
          <textarea v-model="ib.response" class="inp ta sm-mt" rows="2" :placeholder="t('formtpl.ibResponsePh')"></textarea>
        </div>
        <div v-if="!mCfg.ice_breakers.length" class="hint">{{ t('formtpl.ibEmptyHint') }}</div>
      </div>
      <template #footer>
        <button class="btn" @click="msgOpen=false">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="saving" @click="saveMsg">{{ saving?t('formtpl.saving'):t('common.save') }}</button>
      </template>
    </el-drawer>

    <!-- 素材选择器（AI 生成用） -->
    <el-drawer v-model="assetPickerOpen" :title="t('formtpl.pickerTitle')" direction="rtl" size="520px" append-to-body>
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
      <!-- 表单预览：手机 mockup -->
      <div v-if="previewType==='form' && previewData" class="phone-mockup">
        <div class="pm-screen">
          <div class="pm-header">{{ previewData.form_title || t('formtpl.pmFormTitle') }}</div>
          <div v-if="previewData.description" class="pm-desc">{{ previewData.description }}</div>
          <div class="pm-fields">
            <div class="pm-field"><span class="pm-label">{{ t('formtpl.pmFirstName') }}</span><div class="pm-input-mock">—</div></div>
            <div v-for="f in (previewData.extra_contact_fields||[])" :key="f" class="pm-field"><span class="pm-label">{{ f }}</span><div class="pm-input-mock">—</div></div>
            <div v-for="(q,i) in (previewData.custom_questions||[])" :key="'q'+i" class="pm-field">
              <span class="pm-label">{{ q.label || t('formtpl.pmQuestion') }}</span>
              <div v-if="q.options && q.options.length" class="pm-options">
                <span v-for="(o,oi) in q.options" :key="oi" class="pm-option">{{ o.value }}</span>
              </div>
              <div v-else class="pm-input-mock">—</div>
            </div>
          </div>
          <button class="pm-submit">{{ t('formtpl.pmSubmit') }}</button>
          <a class="pm-privacy">{{ previewData.privacy_link_text || 'Privacy Policy' }}</a>
          <div v-if="previewData.thank_you_title" class="pm-thankyou">
            <div class="pm-ty-title">{{ previewData.thank_you_title }}</div>
            <div v-if="previewData.thank_you_body" class="pm-ty-body">{{ previewData.thank_you_body }}</div>
          </div>
        </div>
      </div>
      <!-- 消息预览：Messenger mockup -->
      <div v-if="previewType==='msg' && previewData" class="messenger-mockup">
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
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:6px}
.card-head{display:flex;justify-content:space-between;align-items:center;gap:6px}
.card-name{font-size:14px;font-weight:600;color:var(--t1)}
.card-meta{display:flex;gap:10px;font-size:11px;color:var(--t3);flex-wrap:wrap}
.card-msg-preview{font-size:12px;color:var(--t2);line-height:1.5;font-style:italic;max-height:40px;overflow:hidden}
.badge{font-size:10px;padding:2px 8px;border-radius:8px;font-weight:600}
.badge.ok{color:var(--success);background:rgba(52,199,89,.13)}
.card-ops{display:flex;gap:3px}
.op{background:none;border:1px solid var(--bd);color:var(--t2);font-size:11px;cursor:pointer;padding:3px 8px;border-radius:4px}
.op.danger{color:var(--error)}
.op:hover{background:var(--bg3)}
.empty{grid-column:1/-1;padding:40px;text-align:center;color:var(--t3);font-size:14px}
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
.question-block{background:var(--bg3);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column;gap:4px}
.qb-head{display:flex;justify-content:space-between;align-items:center;font-size:11px;color:var(--t3)}
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
/* 表单预览 mockup */
.phone-mockup{max-width:340px;margin:0 auto;border:3px solid var(--bd);border-radius:24px;overflow:hidden;background:var(--bg2)}
.pm-screen{padding:16px;display:flex;flex-direction:column;gap:10px;max-height:60vh;overflow-y:auto}
.pm-header{font-size:16px;font-weight:700;color:var(--t1);text-align:center}
.pm-desc{font-size:12px;color:var(--t3);text-align:center}
.pm-fields{display:flex;flex-direction:column;gap:8px}
.pm-field{display:flex;flex-direction:column;gap:2px}
.pm-label{font-size:11px;color:var(--t2);font-weight:500}
.pm-input-mock{background:var(--bg3);border:1px solid var(--bd);border-radius:4px;height:28px;display:flex;align-items:center;padding:0 8px;color:var(--t3);font-size:11px}
.pm-options{display:flex;gap:4px;flex-wrap:wrap}
.pm-option{font-size:10px;padding:2px 8px;background:var(--acg);color:var(--ac);border-radius:10px;border:1px solid var(--ac)}
.pm-submit{padding:10px;background:var(--ac);color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:default;font-family:inherit}
.pm-privacy{font-size:10px;color:var(--t3);text-align:center;margin-top:4px;cursor:pointer}
.pm-thankyou{border-top:1px solid var(--bd);padding-top:8px;margin-top:4px}
.pm-ty-title{font-size:13px;font-weight:600;color:var(--success)}
.pm-ty-body{font-size:11px;color:var(--t2);margin-top:2px}
/* Messenger 预览 */
.messenger-mockup{max-width:340px;margin:0 auto;background:var(--bg3);border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:10px}
.mm-bubble{background:var(--ac);color:#fff;padding:10px 14px;border-radius:14px 14px 14px 4px;font-size:13px;line-height:1.5;align-self:flex-start;max-width:85%}
.mm-quick-replies{display:flex;gap:6px;flex-wrap:wrap}
.mm-qr{font-size:12px;padding:5px 12px;background:var(--bg2);border:1px solid var(--ac);color:var(--ac);border-radius:16px}
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
</style>
