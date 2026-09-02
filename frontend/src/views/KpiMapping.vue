<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { GET, PUT } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const { t } = useI18n()

const mapping = ref(null)
const loading = ref(true)
const tab = ref('matrix')

const load = async () => {
  loading.value = true
  try { mapping.value = await GET('/kpi/mapping') }
  catch (e) { ElMessage.error(e.message || t('kpi.loadFail')) }
  loading.value = false
}
onMounted(load)

const FIELD_LABEL = (f) => mapping.value?.field_labels?.[f] || f

// 矩阵 → 按 objective 分组
const matrixGrouped = ref({})
const refreshGroups = () => {
  const groups = {}
  Object.entries(mapping.value?.matrix || {}).forEach(([k, v]) => {
    const [obj, og] = k.split('|')
    if (!groups[obj]) groups[obj] = []
    groups[obj].push({ og: og || '-', field: v, label: FIELD_LABEL(v) })
  })
  matrixGrouped.value = groups
}
watch(() => mapping.value, () => { if (mapping.value) refreshGroups() })
const hasMatrix = computed(() => Object.keys(matrixGrouped.value).length > 0)

const resetDefault = async () => {
  try {
    await ElMessageBox.confirm(t('kpi.resetConfirm'), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' })
    await PUT('/kpi/mapping', { matrix: {}, by_objective: {}, fallback_priority: [], poor_fallback_types: [], field_labels: {} })
    ElMessage.success(t('kpi.resetDone'))
    await load()
  } catch {}
}
</script>

<template>
  <div class="page">
    <div class="tabs">
      <button v-for="tabKey in ['matrix','objective','fallback','poor','labels']" :key="tabKey"
        class="tab" :class="{on:tab===tabKey}" @click="tab=tabKey">
        {{ {matrix:t('kpi.tabMatrix'),objective:t('kpi.tabObjective'),fallback:t('kpi.tabFallback'),poor:t('kpi.tabPoor'),labels:t('kpi.tabLabels')}[tabKey] }}
      </button>
      <button class="reset-btn" @click="resetDefault">{{ t('kpi.resetDefault') }}</button>
    </div>

    <div v-loading="loading">
      <div v-if="tab==='matrix'" class="tab-content">
        <div class="plat-head"><span class="plat-dot fb"></span>Facebook</div>
        <div v-if="!hasMatrix" class="empty-state">{{ t('kpi.matrixEmpty') }}</div>
        <div v-for="(items, obj) in matrixGrouped" :key="obj" class="obj-group">
          <div class="obj-head">{{ obj }}</div>
          <div v-for="item in items" :key="item.og" class="obj-row">
            <span class="og">{{ item.og }}</span>
            <span class="arrow">→</span>
            <span class="field">{{ item.field }}</span>
            <span class="field-label">{{ item.label }}</span>
          </div>
        </div>
        <div class="hint tt-note">{{ t('kpi.ttNoMatrix') }}</div>
      </div>

      <div v-if="tab==='objective'" class="tab-content">
        <div class="plat-head"><span class="plat-dot fb"></span>Facebook</div>
        <div v-for="(v, k) in mapping?.by_objective" :key="k" class="kv-readonly">
          <span class="kv-key">{{ k }}</span>
          <span class="arrow">→</span>
          <span class="kv-val">{{ v }}</span>
          <span class="kv-label">{{ FIELD_LABEL(v) }}</span>
        </div>
        <!-- TikTok 目标映射（tt_by_objective；TT 巡检转化口径）-->
        <div class="plat-head" style="margin-top:20px"><span class="plat-dot tt"></span>TikTok</div>
        <div class="hint" style="margin-bottom:8px">{{ t('kpi.ttObjectiveHint') }}</div>
        <div v-for="(v, k) in mapping?.tt_by_objective" :key="k" class="kv-readonly">
          <span class="kv-key">{{ k }}</span>
          <span class="arrow">→</span>
          <span class="kv-val">{{ v }}</span>
          <span class="kv-label">{{ FIELD_LABEL(v) }}</span>
        </div>
      </div>

      <div v-if="tab==='fallback'" class="tab-content">
        <div class="plat-head"><span class="plat-dot fb"></span>Facebook</div>
        <div class="hint">{{ t('kpi.fallbackHint') }}</div>
        <div v-for="(f, i) in mapping?.fallback_priority" :key="i" class="list-item">
          <span class="num">{{ i + 1 }}</span>
          <span class="field">{{ f }}</span>
          <span class="field-label">{{ FIELD_LABEL(f) }}</span>
        </div>
        <div class="hint tt-note">{{ t('kpi.ttNoFallback') }}</div>
      </div>

      <div v-if="tab==='poor'" class="tab-content">
        <div class="plat-head"><span class="plat-dot fb"></span>Facebook</div>
        <div class="hint">{{ t('kpi.poorHint') }}</div>
        <div class="tag-cloud">
          <span v-for="f in mapping?.poor_fallback_types" :key="f" class="poor-tag">{{ f }}</span>
        </div>
        <div class="hint tt-note">{{ t('kpi.ttNoPoor') }}</div>
      </div>

      <div v-if="tab==='labels'" class="tab-content">
        <div class="hint">{{ t('kpi.labelsHint') }}</div>
        <div v-for="(v, k) in mapping?.field_labels" :key="k" class="kv-readonly">
          <code class="kv-key">{{ k }}</code>
          <span class="arrow">→</span>
          <span class="kv-label">{{ v }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page{width:100%}
.tabs{display:flex;gap:4px;margin-bottom:14px;flex-wrap:wrap;align-items:center}
.plat-head{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;color:var(--t2);margin-bottom:10px}
.plat-dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.plat-dot.fb{background:#1877f2}
.plat-dot.tt{background:linear-gradient(135deg,#25f4ee 45%,#fe2c55 55%)}
.tt-note{margin-top:16px;padding-top:10px;border-top:1px dashed var(--bd)}
.tab{padding:6px 12px;border:1px solid var(--bd);background:var(--bg2);color:var(--t2);border-radius:6px;font-size:12px;cursor:pointer}
.tab.on{background:var(--acg);color:var(--ac);border-color:var(--ac)}
.reset-btn{margin-left:auto;padding:6px 12px;border:1px solid var(--error);background:transparent;color:var(--error);border-radius:6px;font-size:12px;cursor:pointer}
.reset-btn:hover{background:rgba(255,69,58,.08)}
.tab-content{background:var(--bg2);border:1px solid var(--bd);border-radius:8px;padding:14px}
.hint{font-size:11px;color:var(--t3);margin-bottom:12px}
.empty-state{text-align:center;color:var(--t3);font-size:12px;padding:28px 0}

.obj-group{margin-bottom:14px}
.obj-head{font-size:13px;font-weight:600;color:var(--ac);margin-bottom:6px;padding-bottom:4px;border-bottom:1px solid var(--bd)}
.obj-row{display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12px}
.og{color:var(--t3);min-width:160px;font-family:'SF Mono',monospace}
.arrow{color:var(--t3)}
.field{color:var(--t1);font-family:'SF Mono',monospace}
.field-label{color:var(--t2);margin-left:auto}

.kv-readonly{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--bd);font-size:12px}
.kv-key{color:var(--t1);font-family:'SF Mono',monospace;min-width:280px}
.kv-val{color:var(--t1);font-family:'SF Mono',monospace}
.kv-label{color:var(--t2);margin-left:auto}
.arrow{color:var(--t3)}

.list-item{display:flex;align-items:center;gap:8px;padding:5px 0;font-size:12px;border-bottom:1px solid var(--bd)}
.num{width:20px;height:20px;border-radius:50%;background:var(--acg);color:var(--ac);display:flex;align-items:center;justify-content:center;font-size:10px;flex-shrink:0}

.tag-cloud{display:flex;flex-wrap:wrap;gap:6px}
.poor-tag{font-size:11px;padding:3px 8px;background:rgba(255,159,10,.08);border:1px solid rgba(255,159,10,.2);border-radius:4px;color:var(--warning);font-family:'SF Mono',monospace}
</style>
