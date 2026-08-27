<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isSuperadminSync } from '../router'
const isSuper = isSuperadminSync()

const { t } = useI18n()

// 规则类型元数据：label + 默认分类 + 参数 schema（key/label/默认/单位）
const RULE_TYPES = computed(() => ({
  bleed_abs: { label: t('guard.rt.bleed_abs'), category: t('guard.cat.bleed'), params: [
    { key: 'spend_threshold', label: t('guard.param.spend_gte'), def: 20, unit: 'USD' },
  ]},
  cpa_exceed: { label: t('guard.rt.cpa_exceed'), category: t('guard.cat.cost'), params: [
    { key: 'cpa_target', label: t('guard.param.cpa_target'), def: 8, unit: 'USD' },
    { key: 'ratio', label: t('guard.param.ratio'), def: 1.3, unit: 'x' },
  ]},
  // trend_drop（ROAS 下滑）暂不做：依赖 purchase_roas，只对电商/价值类广告有效，非电商恒 0 会误导
  // trend_drop: { label: 'ROAS 下滑', category: '效果下滑', params: [
  //   { key: 'drop_threshold', label: '下滑≥', def: 40, unit: '%' },
  // ]},
  consecutive_bad: { label: t('guard.rt.consecutive_bad'), category: t('guard.cat.decline'), params: [
    { key: 'param_days', label: t('guard.param.days'), def: 2, unit: t('guard.unit.day') },
    { key: 'cpa_target', label: t('guard.param.cpa_target'), def: 8, unit: 'USD' },
    { key: 'ratio', label: t('guard.param.ratio'), def: 1.3, unit: 'x' },
  ]},
  click_no_conv: { label: t('guard.rt.click_no_conv'), category: t('guard.cat.bleed'), params: [
    { key: 'min_clicks', label: t('guard.param.clicks_gte'), def: 50, unit: t('guard.unit.times') },
  ]},
  reach_no_conv: { label: t('guard.rt.reach_no_conv'), category: t('guard.cat.bleed'), params: [
    { key: 'reach_threshold', label: t('guard.param.reach_gte'), def: 1000, unit: t('guard.unit.people') },
    { key: 'min_spend', label: t('guard.param.spend_gte'), def: 10, unit: 'USD' },
  ]},
  low_ctr_no_conv: { label: t('guard.rt.low_ctr_no_conv'), category: t('guard.cat.bleed'), params: [
    { key: 'min_spend', label: t('guard.param.spend_gte'), def: 10, unit: 'USD' },
    { key: 'max_ctr', label: t('guard.param.ctr_lte'), def: 0.5, unit: '%' },
  ]},
  budget_burn_fast: { label: t('guard.rt.budget_burn_fast'), category: t('guard.cat.bleed'), params: [
    { key: 'threshold_abs', label: t('guard.param.delta_gte'), def: 20, unit: 'USD' },
  ]},
}))
const ACTIONS = computed(() => ({ observe: t('guard.action.observe'), pause: t('guard.action.pause'), default: t('guard.action.pause'), pause_adset: t('guard.action.pause_adset'), pause_campaign: t('guard.action.pause_campaign') }))
const CONV_SRC = computed(() => ({ fb: t('guard.conv.fb'), either: t('guard.conv.either'), landing: t('guard.conv.landing') }))
const LANDING_METRIC = computed(() => ({ pass: t('guard.lm.pass_short'), visit: t('guard.lm.visit_short') }))
// category 显示翻译表（DB 存的是建规则时的语言文本，按已知值映射到当前 locale；映射不到原样显示）
const CAT_LABELS = computed(() => [
  [t('guard.cat.bleed'), 'bleed'], [t('guard.cat.cost'), 'cost'], [t('guard.cat.decline'), 'decline'],
])
const catLabel = (c) => {
  if (!c) return ''
  const zh = { '空耗止损': 'bleed', '成本超标': 'cost', '效果下滑': 'decline' }
  const key = zh[c] || CAT_LABELS.value.find(([label]) => label === c)?.[1]
  const en = { bleed: 'Bleed', cost: 'Cost', decline: 'Decline' }
  // 显示当前语言；后端仍按原文匹配（_evaluate_rule 用 category 前缀分类）
  const cur = { bleed: t('guard.cat.bleed'), cost: t('guard.cat.cost'), decline: t('guard.cat.decline') }
  return cur[key] || c
}

const rules = ref([])
const loading = ref(true)
const editOpen = ref(false)
const editing = ref(null)
const form = ref({})
const inspecting = ref(false)
const accountsList = ref([])

const load = async () => {
  loading.value = true
  try {
    rules.value = await GET('/guard/rules')
    accountsList.value = await GET('/fb/accounts').catch(() => [])
  } catch (e) { ElMessage.error(e.message || t('guard.loadFail')) }
  loading.value = false
}
onMounted(load)

const currentSchema = computed(() => RULE_TYPES.value[form.value.rule_type] || { params: [] })
const paramsSummary = (r) => {
  const schema = RULE_TYPES.value[r.rule_type]
  if (!schema) return ''
  return schema.params.map(sp => `${sp.label}${r.params?.[sp.key] ?? sp.def}${sp.unit ? ' ' + sp.unit : ''}`).join('  ·  ')
}
// 说人话：把规则类型+参数+动作拼成一句大白话（"消耗≥$20 且 无转化 → 停广告"）
const p = (r, k) => r.params?.[k]  // 空值=用后端默认，这里只回显已填的
const HUMAN = {
  bleed_abs: r => t('guard.human.bleed_abs', { n: p(r,'spend_threshold')||20 }),
  cpa_exceed: r => t('guard.human.cpa_exceed', { target: p(r,'cpa_target')||8, ratio: p(r,'ratio')||1.3 }),
  consecutive_bad: r => t('guard.human.consecutive_bad', { days: p(r,'param_days')||2, target: p(r,'cpa_target')||8, ratio: p(r,'ratio')||1.3 }),
  click_no_conv: r => t('guard.human.click_no_conv', { n: p(r,'min_clicks')||50 }),
  reach_no_conv: r => t('guard.human.reach_no_conv', { reach: fmtN(p(r,'reach_threshold')||1000), spend: p(r,'min_spend')||10 }),
  low_ctr_no_conv: r => t('guard.human.low_ctr_no_conv', { spend: p(r,'min_spend')||10, ctr: p(r,'max_ctr')||0.5 }),
  budget_burn_fast: r => t('guard.human.budget_burn_fast', { n: p(r,'threshold_abs')||20 }),
}
const fmtN = (n) => Number(n).toLocaleString()
const humanText = (r) => (HUMAN[r.rule_type] ? HUMAN[r.rule_type](r) : paramsSummary(r))
// 命中时间格式化
const hitLabel = (r) => {
  const h = r.hits
  if (!h || !h.count) return null
  let s = t('guard.hitCount', { n: h.count })
  if (h.last_at) {
    const dt = new Date(h.last_at)
    const now = new Date()
    const diff = (now - dt) / 3600000
    s += diff < 1 ? t('guard.ago.minutes', { n: Math.round(diff*60) }) : diff < 24 ? t('guard.ago.hours', { n: Math.round(diff) }) : t('guard.ago.date', { d: dt.toLocaleDateString() })
  }
  return s
}

const onTypeChange = () => {
  const schema = RULE_TYPES.value[form.value.rule_type]
  form.value.params = {}  // 不预填：输入框留空，空值=用后端默认（避免预埋值误导）
  if (schema) form.value.category = schema.category
}
const openCreate = () => {
  editing.value = null
  form.value = { name: '', rule_type: 'bleed_abs', category: t('guard.cat.bleed'), params: {}, conversion_source: 'either', landing_metric: 'pass', action: 'pause', scope_act_ids: [] }
  onTypeChange()
  editOpen.value = true
}
const openEdit = (r) => {
  editing.value = r.id
  const rawParams = Object.fromEntries(Object.entries(r.params || {}).map(([k, v]) => [k, v == null ? v : Number(v)]))
  // landing_metric 藏在 params 里（后端从 params 读），UI 上单独取出来
  const landingMetric = rawParams.landing_metric || 'pass'
  delete rawParams.landing_metric
  form.value = {
    name: r.name, rule_type: r.rule_type, category: r.category,
    params: rawParams, conversion_source: r.conversion_source || 'either',
    landing_metric: landingMetric,
    action: r.action,
    scope_act_ids: r.scope_act_id ? r.scope_act_id.split(',').map(s => s.trim()).filter(Boolean) : [],
  }
  editOpen.value = true
}
const save = async () => {
  if (!form.value.name.trim()) return ElMessage.warning(t('guard.nameRequired'))
  const cleanParams = {}
  Object.entries(form.value.params || {}).forEach(([k, v]) => {
    if (v !== '' && v !== null && v !== undefined) cleanParams[k] = v
  })
  // landing_metric 作为 params 子键随规则存（后端 _evaluate_rule 从 params 取）
  if (form.value.conversion_source !== 'fb') cleanParams.landing_metric = form.value.landing_metric || 'pass'
  const body = {
    name: form.value.name.trim(), rule_type: form.value.rule_type, category: form.value.category,
    params: cleanParams, conversion_source: form.value.conversion_source,
    action: form.value.action, scope_act_id: (form.value.scope_act_ids || []).join(','),
  }
  try {
    if (editing.value) await PUT(`/guard/rules/${editing.value}`, body)
    else await POST('/guard/rules', body)
    ElMessage.success(editing.value ? t('common.savedOk') : t('guard.created'))
    editOpen.value = false
    await load()
  } catch (e) { ElMessage.error(t('common.opFail') + '：' + (e.message || '')) }
}
const onToggle = async (r, val) => {
  // v-model 已先翻转 r.enabled；PUT 失败则回滚
  if (!val) {
    try { await ElMessageBox.confirm(t('guard.disableConfirm', { name: r.name }), t('guard.disableTitle'), { type: 'warning', confirmButtonText: t('common.disable'), cancelButtonText: t('common.cancel') }) }
    catch { r.enabled = true; return }  // 取消 → 回滚开关
  }
  try { await PUT(`/guard/rules/${r.id}`, { enabled: val }) }
  catch (e) { r.enabled = !val; ElMessage.error(t('guard.toggleFail') + '：' + (e.message || '')) }
}
const remove = async (r) => {
  try { await ElMessageBox.confirm(t('guard.delConfirm', { name: r.name }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' }); await DELETE(`/guard/rules/${r.id}`); ElMessage.success(t('guard.deleted')); await load() }
  catch {}
}
const doInspect = async (force = false) => {
  if (force) {
    try {
      await ElMessageBox.confirm(t('guard.forceConfirm'), t('guard.forceTitle'),
        { type: 'warning', confirmButtonText: t('guard.forceContinue'), cancelButtonText: t('common.cancel') })
    } catch { return }
  }
  inspecting.value = true
  try {
    const r = await POST(`/guard/inspect${force ? '?force=true' : ''}`, {})
    const summary = t('guard.inspectSummary', { evaluated: r.evaluated ?? 0, hits: r.hits ?? 0, paused: r.paused ?? 0 })
    if (r.details && r.details.length) {
      const names = r.details.slice(0, 3).map(d => d.ad_name || d.ad_id).join('、')
      ElMessage.success(t('guard.inspectSummaryDetail', { summary, names, more: r.details.length > 3 ? t('guard.andMore') : '' }))
    } else {
      ElMessage.success(summary)
    }
    await load()  // 巡检后刷新规则命中数
  } catch (e) { ElMessage.error(t('guard.inspectFail') + '：' + (e.message || '')) }
  inspecting.value = false
}
</script>

<template>
  <div class="page">
    <div class="bar">
      <div class="bar-l"></div>
      <div class="bar-r">
        <button v-if="isSuper" class="btn" :disabled="inspecting" @click="doInspect(false)" :title="t('guard.inspectNowTip')">{{ t('guard.inspectNow') }}</button>
        <button v-if="isSuper" class="btn btn-warn" :disabled="inspecting" @click="doInspect(true)" :title="t('guard.forceTip')">{{ t('guard.force') }}</button>
        <button class="btn primary" @click="openCreate">{{ t('guard.newRule') }}</button>
      </div>
    </div>

    <div class="list" v-loading="loading">
      <div v-for="r in rules" :key="r.id" class="rule-card" :class="{ off: !r.enabled }">
        <div class="rule-head">
          <span class="rule-name">{{ r.name }}</span>
          <span class="cat-tag">{{ catLabel(r.category) }}</span>
          <span class="scope-tag">{{ r.scope_act_id ? t('guard.scopeAccounts', { n: r.scope_act_id.split(',').length }) : t('guard.scopeGlobal') }}</span>
          <span class="action-tag">{{ ACTIONS[r.action] || r.action }}</span>
          <el-switch v-model="r.enabled" @change="(val) => onToggle(r, val)" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" />
        </div>
        <div class="rule-body">
          <span class="rule-cond">{{ humanText(r) }} <span class="rule-arrow">→</span> <span class="rule-do">{{ ACTIONS[r.action] || r.action }}</span></span>
          <span v-if="hitLabel(r)" class="rule-hit" :class="{ active: r.hits?.count > 0 }">{{ hitLabel(r) }}</span>
          <span v-else class="rule-hit idle">{{ t('guard.noHits') }}</span>
        </div>
        <div class="rule-foot">
          <span class="conv">{{ t('guard.convLabel') }}{{ CONV_SRC[r.conversion_source] || r.conversion_source }}<span v-if="r.conversion_source !== 'fb'" class="conv-lm"> · {{ t('guard.landingMetricLabel') }}{{ LANDING_METRIC[r.params?.landing_metric] || t('guard.lm.pass_short') }}</span></span>
          <div class="rule-ops">
            <button class="mb" @click="openEdit(r)">{{ t('common.edit') }}</button>
            <button class="mb danger" @click="remove(r)">{{ t('common.delete') }}</button>
          </div>
        </div>
      </div>
      <div v-if="!rules.length && !loading" class="empty empty-cta">
        <div class="empty-title">{{ t('guard.emptyTitle') }}</div>
        <div class="empty-step">{{ t('guard.emptyStep') }}</div>
        <button class="btn primary empty-cta-btn" @click="openCreate">{{ t('guard.newRule') }}</button>
      </div>
    </div>

    <div v-if="editOpen" class="overlay" @click.self="editOpen=false">
      <div class="modal">
        <div class="m-title">{{ editing ? t('guard.editTitle') : t('guard.createTitle') }}</div>
        <div class="form-l"><label>{{ t('guard.ruleName') }}</label><input v-model="form.name" class="input" :placeholder="t('guard.ruleNamePh')" /></div>
        <div class="form-l"><label>{{ t('guard.type') }}</label>
          <select v-model="form.rule_type" class="input" @change="onTypeChange">
            <option v-for="(meta, key) in RULE_TYPES" :key="key" :value="key">{{ meta.label }}</option>
          </select>
        </div>
        <div class="form-l" v-if="currentSchema.params.length"><label>{{ t('guard.threshold') }}</label>
          <div class="params-grid">
            <div v-for="sp in currentSchema.params" :key="sp.key" class="param-row">
              <span class="param-label">{{ sp.label }}</span>
              <input v-model.number="form.params[sp.key]" type="number" class="input param-input" />
              <span class="param-unit">{{ sp.unit }}</span>
            </div>
          </div>
        </div>
        <div class="form-l"><label>{{ t('guard.actionLabel') }}</label>
          <select v-model="form.action" class="input">
            <option value="observe">{{ t('guard.action.observe_opt') }}</option>
            <option value="pause">{{ t('guard.action.pause') }}</option>
            <option value="pause_adset">{{ t('guard.action.pause_adset') }}</option>
            <option value="pause_campaign">{{ t('guard.action.pause_campaign') }}</option>
          </select>
        </div>
        <div class="form-l"><label>{{ t('guard.convLabelOpt') }}</label>
          <select v-model="form.conversion_source" class="input">
            <option value="either">{{ t('guard.conv.either') }}</option>
            <option value="fb">{{ t('guard.conv.fb') }}</option>
            <option value="landing">{{ t('guard.conv.landing') }}</option>
          </select>
        </div>
        <div class="form-l" v-if="form.conversion_source !== 'fb'"><label>{{ t('guard.landingMetricOpt') }}</label>
          <select v-model="form.landing_metric" class="input">
            <option value="pass">{{ t('guard.lm.pass') }}</option>
            <option value="visit">{{ t('guard.lm.visit') }}</option>
          </select>
        </div>
        <div class="form-l"><label>{{ t('guard.scopeAccountsLabel') }}</label>
          <el-select v-model="form.scope_act_ids" multiple filterable collapse-tags collapse-tags-tooltip
            :placeholder="t('guard.scopeAccountsPh')" style="width:100%">
            <el-option v-for="a in accountsList" :key="a.act_id" :value="a.act_id" :label="`${a.name}（${a.act_id}）`" />
          </el-select>
        </div>
        <div class="m-foot"><button class="btn" @click="editOpen=false">{{ t('common.cancel') }}</button><button class="btn primary" @click="save">{{ editing ? t('common.save') : t('common.create') }}</button></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page{width:100%}
.bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;gap:8px}
.bar-l{font-size:11px;color:var(--t3);flex:1}
.bar-r{display:flex;gap:8px}
.btn{padding:6px 14px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:6px;font-size:13px;cursor:pointer;white-space:nowrap;transition:.15s}
.btn:hover{background:var(--bg3)}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn.btn-warn{color:var(--warning);border-color:rgba(255,159,10,.5);background:transparent}
.btn.btn-warn:hover{background:rgba(255,159,10,.12);border-color:var(--warning)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.mb{padding:3px 10px;border:1px solid var(--bd);background:transparent;color:var(--t2);border-radius:4px;font-size:11px;cursor:pointer}
.mb:hover{color:var(--ac);border-color:var(--ac)}
.mb.danger:hover{color:var(--error);border-color:var(--error)}

.list{display:flex;flex-direction:column;gap:10px}
.rule-card{background:var(--bg2);border:1px solid var(--bd);border-radius:8px;padding:12px 14px;transition:opacity .15s}
.rule-card.off{opacity:.55}
.rule-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.rule-name{font-size:14px;font-weight:600;color:var(--t1)}
.cat-tag,.scope-tag,.action-tag{font-size:10px;padding:1px 7px;border-radius:9px;white-space:nowrap;line-height:1.5}
.cat-tag{background:rgba(10,132,255,.12);color:var(--ac)}
.scope-tag{background:var(--bg3);color:var(--t3)}
.action-tag{background:rgba(255,159,10,.12);color:var(--warning)}
.rule-head .el-switch{margin-left:auto}
.rule-body{display:flex;align-items:center;gap:10px;margin-top:8px;font-size:12px;flex-wrap:wrap}
.rule-type{color:var(--t2)}
.rule-params{color:var(--t1);font-variant-numeric:tabular-nums}
.rule-cond{color:var(--t1);font-size:12.5px}
.rule-arrow{color:var(--t3);margin:0 4px}
.rule-do{color:var(--warning);font-weight:500}
.rule-hit{font-size:11px;padding:1px 7px;border-radius:9px;background:var(--bg3);color:var(--t3);font-variant-numeric:tabular-nums}
.rule-hit.active{background:rgba(255,69,58,.12);color:var(--error)}
.rule-hit.idle{opacity:.6}
.rule-foot{display:flex;justify-content:space-between;align-items:center;margin-top:8px;padding-top:8px;border-top:1px solid var(--bd)}
.conv{font-size:11px;color:var(--t3)}
.rule-ops{display:flex;gap:6px}
.empty{text-align:center;color:var(--t3);padding:32px;font-size:13px;line-height:1.6;background:var(--bg2);border:1px dashed var(--bd);border-radius:8px}
.empty-cta{padding:50px 30px}
.empty-title{font-size:15px;color:var(--t2);font-weight:600;margin-bottom:10px}
.empty-step{font-size:13px;line-height:1.7}
.empty-cta-btn{margin-top:16px}

.overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:2500;display:flex;align-items:center;justify-content:center}
.modal{background:var(--bg2);border-radius:12px;padding:20px;width:480px;max-width:90vw;box-shadow:var(--shadow-dropdown);max-height:88vh;overflow-y:auto}
.m-title{font-size:15px;font-weight:600;color:var(--t1);margin-bottom:14px}
.form-l{display:flex;align-items:flex-start;gap:8px;margin-bottom:10px}
.form-l > label{font-size:12px;color:var(--t3);width:72px;text-align:right;flex-shrink:0;padding-top:7px}
.input{width:100%;padding:7px 10px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:13px;font-family:inherit;box-sizing:border-box}
.input:focus{border-color:var(--ac);outline:none}
.params-grid{display:flex;flex-direction:column;gap:6px;flex:1}
.param-row{display:flex;align-items:center;gap:6px}
.param-label{font-size:12px;color:var(--t2);width:84px;flex-shrink:0}
.param-input{width:100px}
.param-unit{font-size:11px;color:var(--t3)}
.m-foot{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}
</style>
