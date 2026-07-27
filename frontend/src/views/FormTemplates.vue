<script setup>
import { ref, onMounted } from 'vue'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { showError } from '../composables/useError'
import { useRouter } from 'vue-router'

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
const CONTACT_FIELDS = [
  {v:'EMAIL',l:'邮箱'},{v:'PHONE',l:'电话'},{v:'CITY',l:'城市'},{v:'STATE',l:'州/省'},
  {v:'ZIP_CODE',l:'邮编'},{v:'COUNTRY',l:'国家'},{v:'DATE_OF_BIRTH',l:'生日'},{v:'GENDER',l:'性别'},
  {v:'MARITAL_STATUS',l:'婚姻状况'},{v:'LAST_NAME',l:'姓'},
]

const load = async () => {
  loading.value = true
  try { forms.value = await GET('/form-templates/forms'); messages.value = await GET('/form-templates/messages') }
  catch (e) { showError(e, '加载失败') }
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
const openFormNew = () => { editingForm.value = null; fMeta.value = { name: '', description: '', locale: 'en_US' }; fCfg.value = blankForm(); formOpen.value = true }
const openFormEdit = (t) => { editingForm.value = t; fMeta.value = { name: t.name, description: t.description, locale: t.locale }; fCfg.value = { ...blankForm(), ...(t.config||{}) }; formOpen.value = true }
const addQuestion = () => fCfg.value.custom_questions.push({ key: '', label: '', placeholder: '', options: [] })
const removeQuestion = (i) => fCfg.value.custom_questions.splice(i, 1)
const addOption = (q) => q.options.push({ key: '', value: '' })
const removeOption = (q, i) => q.options.splice(i, 1)
const toggleContact = (v) => {
  const arr = fCfg.value.extra_contact_fields || []
  const i = arr.indexOf(v)
  if (i >= 0) arr.splice(i, 1); else arr.push(v)
}
const saveForm = async () => {
  if (!fMeta.value.name.trim()) return ElMessage.warning('填模板名')
  if (!fCfg.value.form_title.trim()) return ElMessage.warning('填表单标题')
  if (!fCfg.value.privacy_url.trim()) return ElMessage.warning('填隐私政策 URL')
  saving.value = true
  try {
    const body = { name: fMeta.value.name, description: fMeta.value.description, locale: fMeta.value.locale, config: fCfg.value }
    if (editingForm.value) { await PUT('/form-templates/forms/' + editingForm.value.id, body); ElMessage.success('已保存') }
    else { await POST('/form-templates/forms', body); ElMessage.success('已创建') }
    formOpen.value = false; await load()
  } catch (e) { showError(e, '保存失败') }
  saving.value = false
}
const removeForm = async (t) => {
  try { await ElMessageBox.confirm(`归档「${t.name}」？`, '确认', { type: 'warning' }); await DELETE('/form-templates/forms/' + t.id); ElMessage.success('已归档'); await load() }
  catch (e) { if (e === 'cancel') return }
}
const previewForm = (t) => { previewType.value = 'form'; previewData.value = t.config || {}; previewOpen.value = true }

// ── AI 生成 ──
const openAssetPicker = () => { assetPickerOpen.value = true; loadAssets() }
const loadAssets = async () => { try { pickerAssets.value = await GET('/assets') } catch {} }
const aiGenerate = async (a) => {
  assetPickerOpen.value = false; aiLoading.value = true
  try {
    const r = await POST('/form-templates/forms/ai-generate', { asset_id: a.id, country: (fCfg.value.target_countries||[])[0] || '' })
    const cfg = r.config || {}
    if (cfg.form_title) fCfg.value.form_title = cfg.form_title
    if (cfg.description) fCfg.value.description = cfg.description
    if (cfg.custom_questions) fCfg.value.custom_questions = cfg.custom_questions
    if (cfg.extra_contact_fields) fCfg.value.extra_contact_fields = cfg.extra_contact_fields
    if (cfg.thank_you_title) fCfg.value.thank_you_title = cfg.thank_you_title
    if (cfg.thank_you_body) fCfg.value.thank_you_body = cfg.thank_you_body
    ElMessage.success('AI 已生成表单配置（可修改后保存）')
  } catch (e) { showError(e, 'AI 生成失败') }
  aiLoading.value = false
}

// ── 消息 ──
const openMsgNew = () => { editingMsg.value = null; mCfg.value = { name: '', welcome_text: '', ice_breakers: [] }; msgOpen.value = true }
const openMsgEdit = (t) => { editingMsg.value = t; mCfg.value = { name: t.name, welcome_text: t.welcome_text, ice_breakers: [...(t.ice_breakers||[])] }; msgOpen.value = true }
const addIB = () => mCfg.value.ice_breakers.push({ title: '', response: '' })
const removeIB = (i) => mCfg.value.ice_breakers.splice(i, 1)
const saveMsg = async () => {
  if (!mCfg.value.name.trim()) return ElMessage.warning('填模板名')
  if (!mCfg.value.welcome_text.trim()) return ElMessage.warning('填欢迎语')
  saving.value = true
  try {
    const body = { name: mCfg.value.name, welcome_text: mCfg.value.welcome_text, ice_breakers: mCfg.value.ice_breakers }
    if (editingMsg.value) { await PUT('/form-templates/messages/' + editingMsg.value.id, body); ElMessage.success('已保存') }
    else { await POST('/form-templates/messages', body); ElMessage.success('已创建') }
    msgOpen.value = false; await load()
  } catch (e) { showError(e, '保存失败') }
  saving.value = false
}
const removeMsg = async (t) => {
  try { await ElMessageBox.confirm(`归档「${t.name}」？`, '确认', { type: 'warning' }); await DELETE('/form-templates/messages/' + t.id); ElMessage.success('已归档'); await load() }
  catch (e) { if (e === 'cancel') return }
}
const previewMsg = (t) => { previewType.value = 'msg'; previewData.value = t; previewOpen.value = true }
</script>

<template>
  <div class="page">
    <div class="bar">
      <div class="tabs">
        <button :class="['tab',{on:tab==='form'}]" @click="tab='form'">Instant Form</button>
        <button :class="['tab',{on:tab==='msg'}]" @click="tab='msg'">Messenger 消息</button>
      </div>
      <button class="btn primary" @click="tab==='form'?openFormNew():openMsgNew()">+ 新建{{ tab==='form'?'表单':'消息' }}</button>
    </div>

    <!-- Instant Form 列表 -->
    <div v-if="tab==='form'" class="grid" v-loading="loading">
      <div v-for="t in forms" :key="t.id" class="card">
        <div class="card-head"><span class="card-name">{{ t.name }}</span><span v-if="t.fb_form_id" class="badge ok">已部署</span></div>
        <div class="card-meta">
          <span>{{ (t.config||{}).form_title || '—' }}</span>
          <span>{{ ((t.config||{}).custom_questions||[]).length }} 个问题</span>
          <span>{{ t.locale }}</span>
        </div>
        <div class="card-ops">
          <button class="op" @click="previewForm(t)">预览</button>
          <button class="op" @click="openFormEdit(t)">编辑</button>
          <button class="op danger" @click="removeForm(t)">归档</button>
        </div>
      </div>
      <div v-if="!forms.length && !loading" class="empty">暂无表单模板</div>
    </div>

    <!-- Messenger 列表 -->
    <div v-if="tab==='msg'" class="grid" v-loading="loading">
      <div v-for="t in messages" :key="t.id" class="card">
        <div class="card-head"><span class="card-name">{{ t.name }}</span></div>
        <div class="card-msg-preview">{{ (t.welcome_text||'').slice(0,60) }}{{ (t.welcome_text||'').length>60?'…':'' }}</div>
        <div class="card-meta"><span>{{ (t.ice_breakers||[]).length }} 个快捷回复</span></div>
        <div class="card-ops">
          <button class="op" @click="previewMsg(t)">预览</button>
          <button class="op" @click="openMsgEdit(t)">编辑</button>
          <button class="op danger" @click="removeMsg(t)">归档</button>
        </div>
      </div>
      <div v-if="!messages.length && !loading" class="empty">暂无消息模板</div>
    </div>

    <!-- 表单编辑抽屉 -->
    <el-drawer v-model="formOpen" :title="editingForm?'编辑表单':'新建表单'" direction="rtl" size="640px" :destroy-on-close="true">
      <div class="form">
        <div class="row"><label>模板名</label><input v-model="fMeta.name" class="inp" placeholder="如 购物线索-通用" /></div>
        <hr class="sep" />
        <div class="sec-title">表单信息</div>
        <div class="row"><label>表单标题</label><input v-model="fCfg.form_title" class="inp" placeholder="用户看到的表单标题" /></div>
        <div class="row"><label>表单描述</label><input v-model="fCfg.description" class="inp" placeholder="一句话说明" /></div>
        <div class="row"><label>语言</label><el-select v-model="fMeta.locale" style="width:100%" size="small"><el-option v-for="l in LOCALES" :key="l.v" :value="l.v" :label="l.l" /></el-select></div>
        <div class="row"><label>隐私政策 URL</label><input v-model="fCfg.privacy_url" class="inp" placeholder="https://...（必填）" /></div>
        <div class="row"><label>隐私链接文字</label><input v-model="fCfg.privacy_link_text" class="inp" /></div>
        <div class="row"><label>表单可见性</label>
          <el-select v-model="fCfg.is_optimized_for_quality" style="width:100%" size="small">
            <el-option :value="true" label="限制提交（过滤低质量线索，FB 会评估用户行为）" />
            <el-option :value="false" label="公开（任何人都能提交）" />
          </el-select>
        </div>
        <div class="row"><label>表单欢迎语（用户打开表单前看到）</label><textarea v-model="fCfg.welcome_message" class="inp ta" rows="2" placeholder="如：感谢您的兴趣！请花 1 分钟填写以下信息，我们将尽快联系您。"></textarea></div>
        <div class="row"><label>仅目标国家可见</label>
          <el-switch v-model="fCfg.block_display_for_non_targeted" active-color="#0a84ff" inactive-color="#3a3a5c" size="small" />
          <span class="hint">开启后，非目标国家用户看不到此表单</span>
        </div>
        <hr class="sep" />
        <div class="sec-title">联系字段（用户需填写的信息）</div>
        <div class="chips">
          <label v-for="f in CONTACT_FIELDS" :key="f.v" class="chip" :class="{on:(fCfg.extra_contact_fields||[]).includes(f.v)}">
            <input type="checkbox" :checked="(fCfg.extra_contact_fields||[]).includes(f.v)" @change="toggleContact(f.v)" /> {{ f.l }}
          </label>
        </div>
        <hr class="sep" />
        <div class="sec-title-row"><span class="sec-title">自定义问题</span><button class="btn sm" @click="addQuestion">+ 加问题</button>
          <button class="btn sm ghost" @click="openAssetPicker" :disabled="aiLoading" style="margin-left:auto">{{ aiLoading?'智能生成中…':'根据素材智能生成问题' }}</button>
        </div>
        <div v-for="(q,i) in fCfg.custom_questions" :key="i" class="question-block">
          <div class="qb-head"><span>问题 {{i+1}}</span><button class="del-btn" @click="removeQuestion(i)">✕</button></div>
          <input v-model="q.label" class="inp" placeholder="问题文本（如：您想了解哪类产品？）" />
          <input v-model="q.placeholder" class="inp sm-mt" placeholder="输入提示（选填）" />
          <input v-model="q.key" class="inp sm-mt" placeholder="字段 key（英文，如 product_interest）" />
          <div v-if="q.options && q.options.length" class="options-list">
            <div v-for="(o,oi) in q.options" :key="oi" class="option-row">
              <input v-model="o.value" class="inp sm" placeholder="选项文本" />
              <button class="del-btn sm" @click="removeOption(q,oi)">✕</button>
            </div>
          </div>
          <button class="btn sm ghost" @click="addOption(q)" v-if="!q.options || !q.options.length">+ 加选项（变选择题）</button>
          <button class="btn sm ghost" @click="addOption(q)" v-else>+ 加选项</button>
        </div>
        <hr class="sep" />
        <div class="sec-title">感谢页（提交后显示）</div>
        <div class="row"><label>感谢标题</label><input v-model="fCfg.thank_you_title" class="inp" placeholder="如：感谢您的提交！" /></div>
        <div class="row"><label>感谢正文</label><textarea v-model="fCfg.thank_you_body" class="inp ta" rows="2"></textarea></div>
        <div class="row"><label>按钮文字</label><input v-model="fCfg.thank_you_button_text" class="inp" placeholder="如：访问网站" /></div>
        <div class="row"><label>按钮链接</label><input v-model="fCfg.thank_you_website_url" class="inp" placeholder="https://..." /></div>
        <div class="row"><label>跟进链接</label><input v-model="fCfg.follow_up_url" class="inp" placeholder="https://..." /></div>
      </div>
      <template #footer>
        <button class="btn" @click="formOpen=false">取消</button>
        <button class="btn primary" :disabled="saving" @click="saveForm">{{ saving?'保存中…':'保存' }}</button>
      </template>
    </el-drawer>

    <!-- 消息编辑抽屉 -->
    <el-drawer v-model="msgOpen" :title="editingMsg?'编辑消息':'新建消息'" direction="rtl" size="560px" :destroy-on-close="true">
      <div class="form">
        <div class="row"><label>模板名</label><input v-model="mCfg.name" class="inp" /></div>
        <hr class="sep" />
        <div class="sec-title">欢迎语</div>
        <div class="row"><label>主文本</label><textarea v-model="mCfg.welcome_text" class="inp ta" rows="3" placeholder="用户点广告进 Messenger 后自动发的第一条消息"></textarea></div>
        <hr class="sep" />
        <div class="sec-title-row"><span class="sec-title">快捷回复（Ice Breakers）</span><button class="btn sm" @click="addIB">+ 加一条</button></div>
        <div v-for="(ib,i) in mCfg.ice_breakers" :key="i" class="ib-block">
          <div class="qb-head"><span>快捷回复 {{i+1}}</span><button class="del-btn" @click="removeIB(i)">✕</button></div>
          <input v-model="ib.title" class="inp" placeholder="按钮文字（如：了解价格）" />
          <textarea v-model="ib.response" class="inp ta sm-mt" rows="2" placeholder="点按钮后自动回复的内容"></textarea>
        </div>
        <div v-if="!mCfg.ice_breakers.length" class="hint">快捷回复是用户在欢迎语下方看到的按钮，点击后自动回复预设内容。</div>
      </div>
      <template #footer>
        <button class="btn" @click="msgOpen=false">取消</button>
        <button class="btn primary" :disabled="saving" @click="saveMsg">{{ saving?'保存中…':'保存' }}</button>
      </template>
    </el-drawer>

    <!-- 素材选择器（AI 生成用） -->
    <el-drawer v-model="assetPickerOpen" title="选择素材 → 自动生成表单问题" direction="rtl" size="520px" append-to-body>
      <div class="hint" style="margin-bottom:10px">系统会根据素材的 AI 文案内容，自动推荐 2-4 个相关的问题（如"您对哪类产品感兴趣？"），生成后可自由修改。</div>
      <div class="picker-grid">
        <div v-for="a in pickerAssets" :key="a.id" class="picker-card" @click="aiGenerate(a)">
          <img v-if="a.type==='image'" :src="a.public_url" class="picker-thumb" />
          <video v-else :src="a.public_url" class="picker-thumb" preload="metadata" />
          <span class="picker-name">{{ a.name }}</span>
        </div>
      </div>
    </el-drawer>

    <!-- 预览弹窗 -->
    <el-dialog v-model="previewOpen" :title="previewType==='form'?'表单预览':'消息预览'" width="420px" append-to-body>
      <!-- 表单预览：手机 mockup -->
      <div v-if="previewType==='form' && previewData" class="phone-mockup">
        <div class="pm-screen">
          <div class="pm-header">{{ previewData.form_title || '表单标题' }}</div>
          <div v-if="previewData.description" class="pm-desc">{{ previewData.description }}</div>
          <div class="pm-fields">
            <div class="pm-field"><span class="pm-label">名</span><div class="pm-input-mock">—</div></div>
            <div v-for="f in (previewData.extra_contact_fields||[])" :key="f" class="pm-field"><span class="pm-label">{{ f }}</span><div class="pm-input-mock">—</div></div>
            <div v-for="(q,i) in (previewData.custom_questions||[])" :key="'q'+i" class="pm-field">
              <span class="pm-label">{{ q.label || '问题' }}</span>
              <div v-if="q.options && q.options.length" class="pm-options">
                <span v-for="(o,oi) in q.options" :key="oi" class="pm-option">{{ o.value }}</span>
              </div>
              <div v-else class="pm-input-mock">—</div>
            </div>
          </div>
          <button class="pm-submit">提交</button>
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
