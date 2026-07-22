<script setup>
import { ref, computed, onMounted } from 'vue'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

// 规则类型元数据：label + 默认分类 + 参数 schema（key/label/默认/单位）
const RULE_TYPES = {
  bleed_abs: { label: '空耗止损（消耗无转化）', category: '空耗止损', params: [
    { key: 'spend_threshold', label: '消耗≥', def: 20, unit: 'USD' },
  ]},
  cpa_exceed: { label: 'CPA 超标', category: '成本超标', params: [
    { key: 'cpa_target', label: '目标CPA', def: 8, unit: 'USD' },
    { key: 'ratio', label: '超标倍数', def: 1.3, unit: 'x' },
  ]},
  // trend_drop（ROAS 下滑）暂不做：依赖 purchase_roas，只对电商/价值类广告有效，非电商恒 0 会误导
  // trend_drop: { label: 'ROAS 下滑', category: '效果下滑', params: [
  //   { key: 'drop_threshold', label: '下滑≥', def: 40, unit: '%' },
  // ]},
  consecutive_bad: { label: '连续恶化', category: '效果下滑', params: [
    { key: 'param_days', label: '连续天数', def: 2, unit: '天' },
    { key: 'cpa_target', label: '目标CPA', def: 8, unit: 'USD' },
    { key: 'ratio', label: '超标倍数', def: 1.3, unit: 'x' },
  ]},
  click_no_conv: { label: '点击无转化', category: '空耗止损', params: [
    { key: 'min_clicks', label: '点击≥', def: 50, unit: '次' },
  ]},
  reach_no_conv: { label: '覆盖无转化', category: '空耗止损', params: [
    { key: 'reach_threshold', label: '覆盖≥', def: 1000, unit: '人' },
    { key: 'min_spend', label: '消耗≥', def: 10, unit: 'USD' },
  ]},
  low_ctr_no_conv: { label: '低 CTR 无转化', category: '空耗止损', params: [
    { key: 'min_spend', label: '消耗≥', def: 10, unit: 'USD' },
    { key: 'max_ctr', label: 'CTR≤', def: 0.5, unit: '%' },
  ]},
  budget_burn_fast: { label: '瞬烧制止（增量）', category: '空耗止损', params: [
    { key: 'threshold_abs', label: '增量≥', def: 20, unit: 'USD' },
  ]},
}
const ACTIONS = { observe: '只告警', pause: '停广告', default: '停广告', pause_adset: '停广告组', pause_campaign: '停广告系列' }
const CONV_SRC = { fb: '仅 Facebook', either: '综合（落地页 + Facebook）' }
const LANDING_METRIC = { pass: '通过量（点击按钮）', visit: '访问量（到达落地页）' }

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
  } catch (e) { ElMessage.error(e.message || '加载失败') }
  loading.value = false
}
onMounted(load)

const currentSchema = computed(() => RULE_TYPES[form.value.rule_type] || { params: [] })
const paramsSummary = (r) => {
  const schema = RULE_TYPES[r.rule_type]
  if (!schema) return ''
  return schema.params.map(sp => `${sp.label}${r.params?.[sp.key] ?? sp.def}${sp.unit ? ' ' + sp.unit : ''}`).join('  ·  ')
}
// 说人话：把规则类型+参数+动作拼成一句大白话（"消耗≥$20 且 无转化 → 停广告"）
const p = (r, k) => r.params?.[k]  // 空值=用后端默认，这里只回显已填的
const HUMAN = {
  bleed_abs: r => `消耗≥$${p(r,'spend_threshold')||20} 且 无转化`,
  cpa_exceed: r => `CPA > 目标$${p(r,'cpa_target')||8}×${p(r,'ratio')||1.3}（超标）`,
  consecutive_bad: r => `连续${p(r,'param_days')||2}天 CPA超标（目标$${p(r,'cpa_target')||8}×${p(r,'ratio')||1.3}）`,
  click_no_conv: r => `点击≥${p(r,'min_clicks')||50} 且 无转化`,
  reach_no_conv: r => `覆盖≥${fmtN(p(r,'reach_threshold')||1000)} 且 消耗≥$${p(r,'min_spend')||10} 无转化`,
  low_ctr_no_conv: r => `消耗≥$${p(r,'min_spend')||10} 且 CTR≤${p(r,'max_ctr')||0.5}% 无转化`,
  budget_burn_fast: r => `单轮增量消耗≥$${p(r,'threshold_abs')||20}（瞬烧）`,
}
const fmtN = (n) => Number(n).toLocaleString()
const humanText = (r) => (HUMAN[r.rule_type] ? HUMAN[r.rule_type](r) : paramsSummary(r))
// 命中时间格式化
const hitLabel = (r) => {
  const h = r.hits
  if (!h || !h.count) return null
  let s = `命中 ${h.count} 次`
  if (h.last_at) {
    const dt = new Date(h.last_at)
    const now = new Date()
    const diff = (now - dt) / 3600000
    s += diff < 1 ? ` · ${Math.round(diff*60)}分钟前` : diff < 24 ? ` · ${Math.round(diff)}小时前` : ` · ${dt.toLocaleDateString('zh-CN')}`
  }
  return s
}

const onTypeChange = () => {
  const schema = RULE_TYPES[form.value.rule_type]
  form.value.params = {}  // 不预填：输入框留空，空值=用后端默认（避免预埋值误导）
  if (schema) form.value.category = schema.category
}
const openCreate = () => {
  editing.value = null
  form.value = { name: '', rule_type: 'bleed_abs', category: '空耗止损', params: {}, conversion_source: 'either', landing_metric: 'pass', action: 'pause', scope_act_ids: [] }
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
  if (!form.value.name.trim()) return ElMessage.warning('填规则名')
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
    ElMessage.success(editing.value ? '已更新' : '已创建')
    editOpen.value = false
    await load()
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
}
const onToggle = async (r, val) => {
  // v-model 已先翻转 r.enabled；PUT 失败则回滚
  if (!val) {
    try { await ElMessageBox.confirm(`停用规则「${r.name}」？该规则将停止评估，名下广告失去此条保护。`, '确认停用', { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' }) }
    catch { r.enabled = true; return }  // 取消 → 回滚开关
  }
  try { await PUT(`/guard/rules/${r.id}`, { enabled: val }) }
  catch (e) { r.enabled = !val; ElMessage.error('开关失败：' + (e.message || '')) }
}
const remove = async (r) => {
  try { await ElMessageBox.confirm(`删除规则「${r.name}」？`, '确认', { type: 'warning' }); await DELETE(`/guard/rules/${r.id}`); ElMessage.success('已删'); await load() }
  catch {}
}
const doInspect = async (force = false) => {
  inspecting.value = true
  try {
    const r = await POST(`/guard/inspect${force ? '?force=true' : ''}`, {})
    const summary = `评估 ${r.evaluated ?? 0} 条 · 命中 ${r.hits ?? 0} · 暂停 ${r.paused ?? 0}`
    if (r.details && r.details.length) {
      const names = r.details.slice(0, 3).map(d => d.ad_name || d.ad_id).join('、')
      ElMessage.success(`${summary}（已停：${names}${r.details.length > 3 ? ' 等' : ''}）`)
    } else {
      ElMessage.success(summary)
    }
    await load()  // 巡检后刷新规则命中数
  } catch (e) { ElMessage.error('巡检失败：' + (e.message || '')) }
  inspecting.value = false
}
</script>

<template>
  <div class="page">
    <div class="bar">
      <div class="bar-l"></div>
      <div class="bar-r">
        <button class="btn" :disabled="inspecting" @click="doInspect(false)">立即巡检</button>
        <button class="btn" :disabled="inspecting" @click="doInspect(true)">强制重检</button>
        <button class="btn primary" @click="openCreate">+ 新建规则</button>
      </div>
    </div>

    <div class="list" v-loading="loading">
      <div v-for="r in rules" :key="r.id" class="rule-card" :class="{ off: !r.enabled }">
        <div class="rule-head">
          <span class="rule-name">{{ r.name }}</span>
          <span class="cat-tag">{{ r.category }}</span>
          <span class="scope-tag">{{ r.scope_act_id ? '账户 ' + r.scope_act_id.split(',').length + ' 个' : '全局' }}</span>
          <span class="action-tag">{{ ACTIONS[r.action] || r.action }}</span>
          <el-switch v-model="r.enabled" @change="(val) => onToggle(r, val)" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" />
        </div>
        <div class="rule-body">
          <span class="rule-cond">{{ humanText(r) }} <span class="rule-arrow">→</span> <span class="rule-do">{{ ACTIONS[r.action] || r.action }}</span></span>
          <span v-if="hitLabel(r)" class="rule-hit" :class="{ active: r.hits?.count > 0 }">{{ hitLabel(r) }}</span>
          <span v-else class="rule-hit idle">未命中过</span>
        </div>
        <div class="rule-foot">
          <span class="conv">转化口径：{{ CONV_SRC[r.conversion_source] || r.conversion_source }}<span v-if="r.conversion_source !== 'fb'" class="conv-lm"> · 落地指标：{{ LANDING_METRIC[r.params?.landing_metric] || '通过量' }}</span></span>
          <div class="rule-ops">
            <button class="mb" @click="openEdit(r)">编辑</button>
            <button class="mb danger" @click="remove(r)">删除</button>
          </div>
        </div>
      </div>
      <div v-if="!rules.length && !loading" class="empty">暂无规则，点「+ 新建规则」创建。</div>
    </div>

    <div v-if="editOpen" class="overlay" @click.self="editOpen=false">
      <div class="modal">
        <div class="m-title">{{ editing ? '编辑规则' : '新建规则' }}</div>
        <div class="form-l"><label>规则名</label><input v-model="form.name" class="input" placeholder="如：VND 账户止血" /></div>
        <div class="form-l"><label>类型</label>
          <select v-model="form.rule_type" class="input" @change="onTypeChange">
            <option v-for="(meta, key) in RULE_TYPES" :key="key" :value="key">{{ meta.label }}</option>
          </select>
        </div>
        <div class="form-l" v-if="currentSchema.params.length"><label>阈值</label>
          <div class="params-grid">
            <div v-for="sp in currentSchema.params" :key="sp.key" class="param-row">
              <span class="param-label">{{ sp.label }}</span>
              <input v-model.number="form.params[sp.key]" type="number" class="input param-input" />
              <span class="param-unit">{{ sp.unit }}</span>
            </div>
          </div>
        </div>
        <div class="form-l"><label>动作</label>
          <select v-model="form.action" class="input">
            <option value="observe">只告警（观察）</option>
            <option value="pause">停广告</option>
            <option value="pause_adset">停广告组</option>
            <option value="pause_campaign">停广告系列</option>
          </select>
        </div>
        <div class="form-l"><label>转化口径</label>
          <select v-model="form.conversion_source" class="input">
            <option value="either">综合（落地页 + Facebook）</option>
            <option value="fb">仅 Facebook</option>
            <option value="landing">仅落地页</option>
          </select>
        </div>
        <div class="form-l" v-if="form.conversion_source !== 'fb'"><label>落地页指标</label>
          <select v-model="form.landing_metric" class="input">
            <option value="pass">通过量（点击按钮次数）</option>
            <option value="visit">访问量（到达落地页次数）</option>
          </select>
        </div>
        <div class="form-l"><label>作用账户</label>
          <el-select v-model="form.scope_act_ids" multiple filterable collapse-tags collapse-tags-tooltip
            placeholder="留空=名下全部账户；可多选指定账户" style="width:100%">
            <el-option v-for="a in accountsList" :key="a.act_id" :value="a.act_id" :label="`${a.name}（${a.act_id}）`" />
          </el-select>
        </div>
        <div class="m-foot"><button class="btn" @click="editOpen=false">取消</button><button class="btn primary" @click="save">{{ editing ? '保存' : '创建' }}</button></div>
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
