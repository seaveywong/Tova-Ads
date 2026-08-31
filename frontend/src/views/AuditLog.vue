<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { GET } from '../api'
import { isSuperadminSync } from '../router'
import { ElMessage } from 'element-plus'
import { fmtTime } from '../composables/useTz'
import { dateShortcuts, presetRange } from '../composables/useDateRange'
const { t } = useI18n()
// locale 响应：切语言时 shortcut 文案跟着变（dateShortcuts 内部 t 一次性求值会冻结）
const pickerShortcuts = computed(() => dateShortcuts())

const isSuper = ref(isSuperadminSync())

const tabs = [
  { key: 'all', label: 'audit.tabAll', params: {} },
  { key: 'user', label: 'audit.tabUser', params: { actor_type: 'user' } },
  { key: 'system', label: 'audit.tabSystem', params: { actor_type: 'system,sentinel,sync,warmup' } },
  { key: 'login', label: 'audit.tabLogin', params: { action_type: 'login,switch_tenant' } },
  { key: 'fail', label: 'audit.tabFail', params: { result: 'fail' } },
]
const tab = ref('all')

const logs = ref([])
const loading = ref(false)
const actors = ref([])
const fAction = ref('')
const fUser = ref(0)
const fTrace = ref('')
const expandedRowIds = ref([])
const PAGE_SIZE = 50
const page = ref(1)
const total = ref(0)
const dateRange = ref(presetRange('last_7d') || [])  // 默认近7天；清空=全部

const buildParams = (forCount = false) => {
  const t = tabs.find(x => x.key === tab.value)
  const p = { ...t.params }
  if (fTrace.value.trim()) {
    p.trace_id = fTrace.value.trim()
    if (!forCount) { p.limit = 200 }
    return p
  }
  if (fAction.value.trim()) p.action_type = fAction.value.trim()
  if (fUser.value) p.actor_user_id = fUser.value
  if (dateRange.value && dateRange.value.length === 2) {
    p.date_from = dateRange.value[0]; p.date_to = dateRange.value[1]
  }
  if (!forCount) { p.limit = PAGE_SIZE; p.offset = (page.value - 1) * PAGE_SIZE }
  return p
}
const totalPages = () => Math.max(1, Math.ceil(total.value / PAGE_SIZE))
const load = async () => {
  loading.value = true
  expandedRowIds.value = []
  try {
    const qs = new URLSearchParams(buildParams()).toString()
    const qsCount = new URLSearchParams(buildParams(true)).toString()
    const [rows, cnt] = await Promise.all([GET('/logs?' + qs), GET('/logs/count?' + qsCount)])
    logs.value = rows
    total.value = (cnt && cnt.count) || 0
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  loading.value = false
}
const loadActors = async () => { try { actors.value = await GET('/logs/actors') } catch {} }
onMounted(() => { load(); loadActors() })
const setTab = (k) => { tab.value = k; fTrace.value = ''; page.value = 1; load() }
const goPage = (n) => { page.value = Math.min(Math.max(1, n), totalPages()); jumpPage.value = ''; load() }
const jumpPage = ref('')
const doJump = () => {
  const n = parseInt(jumpPage.value, 10)
  if (isNaN(n)) return
  goPage(n)
}
const onDateChange = () => { page.value = 1; load() }

// 行内展开 trace（el-table expand）
const onExpandChange = async (row, expandedRows) => {
  if (!expandedRows.find(r => r.id === row.id)) return  // 收起，不处理
  if (row._traceLogs) return  // 已加载过
  row._traceLoading = true
  try {
    row._traceLogs = await GET('/logs?trace_id=' + row.trace_id + '&limit=50')
  } catch { row._traceLogs = [] }
  row._traceLoading = false
}

const TYPE_ZH = { user: 'audit.typeUser', system: 'audit.typeSystem', sentinel: 'audit.typeSentinel', sync: 'audit.typeSync', warmup: 'audit.typeWarmup' }
const ACTION_ZH = {
  inspection_heartbeat: 'audit.actionInspectionHeartbeat', pause: 'audit.actionPause', deploy: 'audit.actionDeploy', login: 'audit.actionLogin',
  switch_tenant: 'audit.actionSwitchTenant', account_permission_error: 'audit.actionAccountPermissionError', token_rate_limited: 'audit.actionTokenRateLimited',
  landing_health_alert: 'audit.actionLandingHealthAlert', coverage_lost: 'audit.actionCoverageLost', create: 'audit.actionCreate', update: 'audit.actionUpdate',
  delete: 'audit.actionDelete', archive: 'audit.actionArchive', rule_pause: 'audit.actionRulePause', sentinel_pause: 'audit.actionSentinelPause',
  emergency_pause: 'audit.actionEmergencyPause', token_expired: 'audit.actionTokenExpired', token_invalid: 'audit.actionTokenInvalid',
}
const TARGET_ZH = {
  scheduler: 'audit.targetScheduler', ad: 'audit.targetAd', account: 'audit.targetAccount', fb_credential: 'audit.targetFbCredential',
  landing_page: 'audit.targetLandingPage', launch_template: 'audit.targetLaunchTemplate', launch_job: 'audit.targetLaunchJob',
  form_template: 'audit.targetFormTemplate', user: 'audit.targetUser', team: 'audit.targetTeam', subcode: 'audit.targetSubcode', rule: 'audit.targetRule',
}
const SOURCE_ZH = {
  scheduled: 'audit.sourceScheduled', rule_engine: 'audit.sourceRuleEngine', fb_api: 'audit.sourceFbApi', guard: 'audit.sourceGuard',
  landing: 'audit.sourceLanding', launch: 'audit.sourceLaunch', sentinel: 'audit.sourceSentinel', watchdog: 'audit.sourceWatchdog',
  user: 'audit.sourceUser', warmup: 'audit.sourceWarmup', sync: 'audit.sourceSync',
}
const rowColor = (r) => r.result === 'fail' ? 'var(--error)' : 'var(--success)'
const resetFilters = () => { fAction.value = ''; fUser.value = 0; fTrace.value = ''; dateRange.value = []; page.value = 1; load() }
</script>

<template>
  <div class="page">
    <div class="card">
      <div class="head">
        <div class="tabs">
          <button v-for="tb in tabs" :key="tb.key" :class="['tab',{on:tab===tb.key}]" @click="setTab(tb.key)">{{ t(tb.label) }}</button>
        </div>
        <button class="btn" @click="load">{{ t('common.refresh') }}</button>
      </div>

      <div class="filters">
        <div class="filter-item">
          <span class="flabel">{{ t('audit.fieldAction') }}</span>
          <input v-model="fAction" class="input" :placeholder="t('audit.actionPlaceholder')" @keyup.enter="load" />
        </div>
        <div class="filter-item">
          <span class="flabel">{{ t('audit.fieldUser') }}</span>
          <select v-model="fUser" class="sel" @change="load">
            <option :value="0">{{ t('common.all') }}</option>
            <option v-for="a in actors" :key="a.id" :value="a.id">{{ a.email }}</option>
          </select>
        </div>
        <div class="filter-item">
          <span class="flabel">{{ t('audit.fieldTrace') }}</span>
          <input v-model="fTrace" class="input mono" :placeholder="t('audit.tracePlaceholder')" @keyup.enter="load" />
        </div>
        <div class="filter-item">
          <span class="flabel">{{ t('audit.fieldDate') }}</span>
          <el-date-picker v-model="dateRange" type="daterange" size="small" value-format="YYYY-MM-DD"
            :start-placeholder="t('audit.dateStart')" :end-placeholder="t('audit.dateEnd')" style="width:240px" :shortcuts="pickerShortcuts" @change="onDateChange" />
        </div>
        <button v-if="fAction || fUser || fTrace || (dateRange && dateRange.length)" class="clear" @click="resetFilters">{{ t('audit.clear') }}</button>
      </div>

      <div class="pager">
        <span class="pager-info">{{ t('audit.pagerInfo', { total: total, page: page, pages: totalPages() }) }}</span>
        <div class="pager-ops">
          <button class="btn" :disabled="page <= 1 || loading" @click="goPage(page - 1)">{{ t('audit.prevPage') }}</button>
          <input v-model="jumpPage" type="number" min="1" :max="totalPages()" class="jump-input" :placeholder="t('audit.jumpPh')" @keyup.enter="doJump" />
          <button class="btn" @click="doJump">{{ t('audit.jumpGo') }}</button>
          <button class="btn" :disabled="page >= totalPages() || loading" @click="goPage(page + 1)">{{ t('audit.nextPage') }}</button>
        </div>
      </div>

      <div class="tbl-wrap"><el-table :data="logs" v-loading="loading" style="width:100%" :empty-text="t('common.noData')" row-key="id" size="small"
                @expand-change="onExpandChange">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="trace-inline" v-loading="row._traceLoading">
              <div class="trace-head-inline">
                <span class="trace-label">{{ t('audit.traceLabel') }} <code>{{ row.trace_id }}</code></span>
                <span v-if="row._traceLogs" class="trace-count-inline">{{ t('audit.traceCount', { n: row._traceLogs.length }) }}</span>
              </div>
              <div class="trace-list-inline">
                <div v-for="l in (row._traceLogs || [])" :key="l.id" class="trace-row">
                  <span :class="['t-dot', l.result]"></span>
                  <span class="t-time">{{ (l.created_at || '').slice(11,19) }}</span>
                  <span :class="['tag sm', l.actor_type]">{{ TYPE_ZH[l.actor_type] ? t(TYPE_ZH[l.actor_type]) : l.actor_type }}</span>
                  <code class="t-act">{{ ACTION_ZH[l.action_type] ? t(ACTION_ZH[l.action_type]) : l.action_type }}</code>
                  <span v-if="l.target_type" class="t-tgt">{{ TARGET_ZH[l.target_type] ? t(TARGET_ZH[l.target_type]) : l.target_type }}<span v-if="l.target_id">#{{ l.target_id }}</span></span>
                  <span :style="{color:rowColor(l)}">{{ l.result === 'success' ? '✓' : '✗' }}</span>
                  <span v-if="l.friendly_error" class="t-err">{{ l.friendly_error }}</span>
                </div>
                <div v-if="row._traceLogs && !row._traceLogs.length && !row._traceLoading" class="trace-empty-inline">{{ t('audit.traceEmpty') }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('audit.colTime')" width="150">
          <template #default="{ row }"><span class="mute">{{ fmtTime(row.created_at) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('audit.colType')" width="74">
          <template #default="{ row }"><span :class="['tag', row.actor_type]">{{ TYPE_ZH[row.actor_type] ? t(TYPE_ZH[row.actor_type]) : row.actor_type }}</span></template>
        </el-table-column>
        <el-table-column :label="t('audit.colAction')" width="120">
          <template #default="{ row }"><code class="act">{{ ACTION_ZH[row.action_type] ? t(ACTION_ZH[row.action_type]) : row.action_type }}</code></template>
        </el-table-column>
        <el-table-column :label="t('audit.colTarget')" min-width="150">
          <template #default="{ row }">
            <span v-if="row.target_type" class="tgt">{{ TARGET_ZH[row.target_type] ? t(TARGET_ZH[row.target_type]) : row.target_type }}<span v-if="row.target_id" class="tid">#{{ row.target_id }}</span></span>
            <span v-else class="dash">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="isSuper" :label="t('audit.colTeam')" width="56" align="center">
          <template #default="{ row }"><span class="mute">#{{ row.tenant_id }}</span></template>
        </el-table-column>
        <el-table-column :label="t('audit.colResult')" width="68">
          <template #default="{ row }"><span :class="['res', row.result]">{{ row.result === 'success' ? t('audit.resultSuccess') : t('audit.resultFail') }}</span></template>
        </el-table-column>
        <el-table-column :label="t('common.detail')" min-width="200">
          <template #default="{ row }">
            <div class="detail-cell">
              <span v-if="row.source" class="src-tag">{{ SOURCE_ZH[row.source] ? t(SOURCE_ZH[row.source]) : row.source }}</span>
              <span v-if="row.friendly_error" class="err">{{ row.friendly_error }}</span>
              <span v-if="row.trigger_detail" class="trig">{{ row.trigger_detail }}</span>
              <span v-if="row.metadata" class="meta">
                <template v-for="(v, k) in row.metadata" :key="k">
                  <span v-if="v !== null && v !== '' && k !== 'campaign_id' && k !== 'adset_id'" class="meta-kv">{{ k }}={{ v }} </span>
                </template>
              </span>
              <span v-if="!row.friendly_error && !row.trigger_detail && !row.metadata" class="dash">—</span>
            </div>
          </template>
        </el-table-column>
      </el-table></div>
    </div>
  </div>
</template>

<style scoped>
.page{display:flex;flex-direction:column;gap:14px}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:12px;padding:20px}
.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;gap:12px;flex-wrap:wrap}
.tabs{display:flex;gap:3px;background:var(--bg3);padding:3px;border-radius:8px}
.tab{padding:6px 15px;border:none;background:transparent;color:var(--t3);border-radius:6px;font-size:12px;cursor:pointer;transition:all .15s;font-family:inherit;font-weight:500}
.tab:hover{color:var(--t1)}
.tab.on{background:var(--bg2);color:var(--t1);box-shadow:0 1px 2px rgba(0,0,0,.08)}
.btn{padding:6px 14px;border:1px solid var(--bd);background:var(--bg2);color:var(--t2);border-radius:7px;font-size:12px;cursor:pointer;font-family:inherit}
.btn:hover{color:var(--t1);border-color:var(--ac)}
.filters{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;align-items:center}
.pager{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:10px;flex-wrap:wrap}
.pager-info{font-size:12px;color:var(--t3)}
.pager-ops{display:flex;gap:6px;align-items:center}
.jump-input{width:64px;background:var(--bg3);color:var(--t1);border:1px solid var(--bd);border-radius:var(--rs);padding:5px 8px;font-size:12px}
.jump-input:focus{outline:none;border-color:var(--ac)}
.filter-item{display:flex;align-items:center;gap:6px}
.flabel{font-size:11px;color:var(--t3);font-weight:500}
.input{padding:6px 11px;background:var(--bg3);border:1px solid var(--bd);border-radius:7px;color:var(--t1);font-size:12px;font-family:inherit;box-sizing:border-box;min-width:180px;transition:border-color .15s}
.input:focus{border-color:var(--ac);outline:none}
.input::placeholder{color:var(--t3);opacity:.7}
.input.mono,.mono{font-family:'SF Mono',ui-monospace,monospace}
.sel{padding:6px 11px;background:var(--bg3);border:1px solid var(--bd);border-radius:7px;color:var(--t1);font-size:12px;min-width:170px;cursor:pointer}
.clear{background:transparent;border:none;color:var(--t3);font-size:11px;cursor:pointer;padding:4px 8px;text-decoration:underline}
.clear:hover{color:var(--error)}
.mute{color:var(--t3);font-size:11px;font-variant-numeric:tabular-nums}
.act{font-size:11px;color:var(--ac);font-family:'SF Mono',ui-monospace,monospace;font-weight:500}
.tgt{font-size:11px;color:var(--t2)}
.tid{color:var(--t3);font-family:'SF Mono',ui-monospace,monospace}
.dash{color:var(--t3);opacity:.5}
.err{font-size:11px;color:var(--error)}
.trig{font-size:11px;color:var(--t3)}
.detail-cell{display:flex;flex-direction:column;gap:2px}
.src-tag{font-size:9px;padding:1px 5px;border-radius:3px;background:var(--bg3);color:var(--t2);display:inline-block;width:fit-content}
.meta{font-size:10px;color:var(--t3);line-height:1.5}
.meta-kv{font-family:monospace;margin-right:4px}
.tag{display:inline-block;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:600;line-height:1.5}
.tag.sm{font-size:9px;padding:1px 6px}
.tag.user{color:var(--ac);background:var(--acg)}
.tag.system{color:#a855f7;background:rgba(168,85,247,.13)}
.tag.sentinel{color:var(--warning);background:rgba(255,159,10,.13)}
.tag.sync{color:#06b6d4;background:rgba(6,182,212,.13)}
.tag.warmup{color:var(--t3);background:var(--bg3)}
.res{display:inline-block;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:600}
.res.success{color:var(--success);background:rgba(52,199,89,.13)}
.res.fail{color:var(--error);background:rgba(255,69,58,.13)}

/* 行内 trace 展开 */
.trace-inline{padding:8px 16px 12px;background:var(--bg3);border-radius:8px}
.trace-head-inline{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.trace-head-inline .trace-label{font-size:11px;color:var(--t2)}
.trace-head-inline code{font-family:'SF Mono',ui-monospace,monospace;font-size:10px;color:var(--ac);background:var(--acg);padding:2px 7px;border-radius:4px}
.trace-count-inline{font-size:10px;color:var(--t3)}
.trace-list-inline{display:flex;flex-direction:column;gap:1px}
.trace-row{display:flex;align-items:center;gap:8px;padding:3px 8px;font-size:11px;border-radius:4px}
.trace-row:hover{background:var(--bg2)}
.t-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;background:var(--t3)}
.t-dot.success{background:var(--success)}
.t-dot.fail{background:var(--error)}
.t-time{color:var(--t3);font-variant-numeric:tabular-nums;font-family:'SF Mono',ui-monospace,monospace;width:60px}
.t-act{font-size:10px;color:var(--ac);font-family:'SF Mono',ui-monospace,monospace}
.t-tgt{color:var(--t2);font-size:10px}
.t-tgt span{color:var(--t3);font-family:'SF Mono',ui-monospace,monospace}
.t-err{color:var(--error);margin-left:auto;font-size:10px}
.trace-empty-inline{padding:10px;text-align:center;color:var(--t3);font-size:11px}

:deep(.el-table){font-size:12px}
:deep(.el-table th.el-table__cell){background:var(--bg3);color:var(--t2);font-weight:600;font-size:11px}
:deep(.el-table tr:hover > td){background:var(--bg3) !important}
:deep(.el-table__expanded-cell){padding:4px 8px !important}
.tbl-wrap{overflow-x:auto}
</style>
