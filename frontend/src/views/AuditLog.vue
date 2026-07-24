<script setup>
import { ref, onMounted } from 'vue'
import { GET } from '../api'
import { isSuperadminSync } from '../router'
import { ElMessage } from 'element-plus'
import { fmtTime } from '../composables/useTz'

const isSuper = ref(isSuperadminSync())

// tab 预设筛选（actor_type/action_type 支持逗号多值）
const tabs = [
  { key: 'all', label: '全部', params: {} },
  { key: 'user', label: '操作', params: { actor_type: 'user' } },
  { key: 'system', label: '系统', params: { actor_type: 'system,sentinel,sync,warmup' } },
  { key: 'login', label: '登录', params: { action_type: 'login,switch_tenant' } },
  { key: 'fail', label: '失败', params: { result: 'fail' } },
]
const tab = ref('all')

const logs = ref([])
const loading = ref(false)
const actors = ref([])
const fAction = ref('')
const fUser = ref(0)
const fTrace = ref('')

const buildParams = () => {
  const t = tabs.find(x => x.key === tab.value)
  const p = { ...t.params, limit: 200 }
  if (fTrace.value.trim()) return { trace_id: fTrace.value.trim(), limit: 200 }
  if (fAction.value.trim()) p.action_type = fAction.value.trim()
  if (fUser.value) p.actor_user_id = fUser.value
  return p
}
const load = async () => {
  loading.value = true
  try { logs.value = await GET('/logs?' + new URLSearchParams(buildParams()).toString()) }
  catch (e) { ElMessage.error(e.message || '加载失败') }
  loading.value = false
}
const loadActors = async () => { try { actors.value = await GET('/logs/actors') } catch {} }
onMounted(() => { load(); loadActors() })
const setTab = (k) => { tab.value = k; fTrace.value = ''; load() }

// trace 链路展开
const expandedTrace = ref('')
const traceLogs = ref([])
const traceLoading = ref(false)
const toggleTrace = async (tid) => {
  if (expandedTrace.value === tid) { expandedTrace.value = ''; traceLogs.value = []; return }
  expandedTrace.value = tid
  traceLoading.value = true
  try { traceLogs.value = await GET('/logs?trace_id=' + tid + '&limit=50') }
  catch { traceLogs.value = [] }
  traceLoading.value = false
}

const TYPE_ZH = { user: '用户', system: '系统', sentinel: '哨兵', sync: '同步', warmup: '预热' }
const resetFilters = () => { fAction.value = ''; fUser.value = 0; fTrace.value = ''; load() }
</script>

<template>
  <div class="page">
    <div class="card">
      <!-- tab + 刷新 -->
      <div class="head">
        <div class="tabs">
          <button v-for="t in tabs" :key="t.key" :class="['tab',{on:tab===t.key}]" @click="setTab(t.key)">{{ t.label }}</button>
        </div>
        <button class="btn" @click="load"><span class="refresh">↻</span> 刷新</button>
      </div>

      <!-- 筛选条 -->
      <div class="filters">
        <div class="filter-item">
          <span class="flabel">动作</span>
          <input v-model="fAction" class="input" placeholder="如 login / pause / upsert" @keyup.enter="load" />
        </div>
        <div class="filter-item">
          <span class="flabel">用户</span>
          <select v-model="fUser" class="sel" @change="load">
            <option :value="0">全部</option>
            <option v-for="a in actors" :key="a.id" :value="a.id">{{ a.email }}</option>
          </select>
        </div>
        <div class="filter-item">
          <span class="flabel">链路</span>
          <input v-model="fTrace" class="input mono" placeholder="trace_id 拉全链路" @keyup.enter="load" />
        </div>
        <button v-if="fAction || fUser || fTrace" class="clear" @click="resetFilters">清除</button>
      </div>

      <el-table :data="logs" v-loading="loading" style="width:100%" empty-text="暂无日志" row-key="id" size="small">
        <el-table-column label="时间" width="150">
          <template #default="{ row }"><span class="mute">{{ fmtTime(row.created_at) }}</span></template>
        </el-table-column>
        <el-table-column label="类型" width="74">
          <template #default="{ row }"><span :class="['tag', row.actor_type]">{{ TYPE_ZH[row.actor_type] || row.actor_type }}</span></template>
        </el-table-column>
        <el-table-column label="动作" width="120">
          <template #default="{ row }"><code class="act">{{ row.action_type }}</code></template>
        </el-table-column>
        <el-table-column label="对象" min-width="150">
          <template #default="{ row }">
            <span v-if="row.target_type" class="tgt">{{ row.target_type }}<span v-if="row.target_id" class="tid">#{{ row.target_id }}</span></span>
            <span v-else class="dash">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="isSuper" label="团队" width="56" align="center">
          <template #default="{ row }"><span class="mute">#{{ row.tenant_id }}</span></template>
        </el-table-column>
        <el-table-column label="结果" width="68">
          <template #default="{ row }"><span :class="['res', row.result]">{{ row.result === 'success' ? '✓ 成功' : '✗ 失败' }}</span></template>
        </el-table-column>
        <el-table-column label="详情" min-width="170">
          <template #default="{ row }">
            <span v-if="row.friendly_error" class="err">{{ row.friendly_error }}</span>
            <span v-else-if="row.trigger_type" class="trig">{{ row.trigger_type }}<span v-if="row.trigger_detail"> · {{ row.trigger_detail }}</span></span>
            <span v-else class="dash">—</span>
          </template>
        </el-table-column>
        <el-table-column label="链路" width="64" align="center">
          <template #default="{ row }">
            <button class="trace-btn" :class="{on: expandedTrace === row.trace_id}" @click="toggleTrace(row.trace_id)">展开</button>
          </template>
        </el-table-column>
      </el-table>

      <!-- trace 链路面板 -->
      <transition name="fade">
        <div v-if="expandedTrace" class="trace-panel" v-loading="traceLoading">
          <div class="trace-head">
            <span class="trace-icon">⇆</span>
            <span class="trace-label">链路追踪</span>
            <code class="trace-id">{{ expandedTrace }}</code>
            <span class="trace-count">{{ traceLogs.length }} 条事件</span>
          </div>
          <div class="trace-list">
            <div v-for="l in traceLogs" :key="l.id" class="trace-row">
              <span :class="['t-dot', l.result]"></span>
              <span class="t-time">{{ (l.created_at || '').slice(11,19) }}</span>
              <span :class="['tag sm', l.actor_type]">{{ TYPE_ZH[l.actor_type] || l.actor_type }}</span>
              <code class="t-act">{{ l.action_type }}</code>
              <span v-if="l.target_type" class="t-tgt">{{ l.target_type }}<span v-if="l.target_id">#{{ l.target_id }}</span></span>
              <span v-if="l.friendly_error" class="t-err">{{ l.friendly_error }}</span>
            </div>
            <div v-if="!traceLogs.length && !traceLoading" class="trace-empty">该链路无更多记录</div>
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<style scoped>
.page{display:flex;flex-direction:column;gap:14px}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:12px;padding:20px}

/* head: tabs + 刷新 */
.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;gap:12px;flex-wrap:wrap}
.tabs{display:flex;gap:3px;background:var(--bg3);padding:3px;border-radius:8px}
.tab{padding:6px 15px;border:none;background:transparent;color:var(--t3);border-radius:6px;font-size:12px;cursor:pointer;transition:all .15s;font-family:inherit;font-weight:500}
.tab:hover{color:var(--t1)}
.tab.on{background:var(--bg2);color:var(--t1);box-shadow:0 1px 2px rgba(0,0,0,.08)}
.refresh{display:inline-block;font-size:13px}
.btn{display:flex;align-items:center;gap:5px;padding:6px 14px;border:1px solid var(--bd);background:var(--bg2);color:var(--t2);border-radius:7px;font-size:12px;cursor:pointer;font-family:inherit}
.btn:hover{color:var(--t1);border-color:var(--ac)}

/* 筛选条 */
.filters{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;align-items:center}
.filter-item{display:flex;align-items:center;gap:6px}
.flabel{font-size:11px;color:var(--t3);font-weight:500}
.input{padding:6px 11px;background:var(--bg3);border:1px solid var(--bd);border-radius:7px;color:var(--t1);font-size:12px;font-family:inherit;box-sizing:border-box;min-width:180px;transition:border-color .15s}
.input:focus{border-color:var(--ac);outline:none}
.input::placeholder{color:var(--t3);opacity:.7}
.input.mono,.mono{font-family:'SF Mono',ui-monospace,monospace}
.sel{padding:6px 11px;background:var(--bg3);border:1px solid var(--bd);border-radius:7px;color:var(--t1);font-size:12px;min-width:170px;cursor:pointer}
.clear{background:transparent;border:none;color:var(--t3);font-size:11px;cursor:pointer;padding:4px 8px;text-decoration:underline}
.clear:hover{color:var(--error)}

/* 表格内 */
.mute{color:var(--t3);font-size:11px;font-variant-numeric:tabular-nums}
.act{font-size:11px;color:var(--ac);font-family:'SF Mono',ui-monospace,monospace;font-weight:500}
.tgt{font-size:11px;color:var(--t2)}
.tid{color:var(--t3);font-family:'SF Mono',ui-monospace,monospace}
.dash{color:var(--t3);opacity:.5}
.err{font-size:11px;color:var(--error)}
.trig{font-size:11px;color:var(--t3)}

/* 类型 tag（分色） */
.tag{display:inline-block;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:600;line-height:1.5}
.tag.sm{font-size:9px;padding:1px 6px}
.tag.user{color:var(--ac);background:var(--acg)}
.tag.system{color:#a855f7;background:rgba(168,85,247,.13)}
.tag.sentinel{color:var(--warning);background:rgba(255,159,10,.13)}
.tag.sync{color:#06b6d4;background:rgba(6,182,212,.13)}
.tag.warmup{color:var(--t3);background:var(--bg3)}

/* 结果 tag */
.res{display:inline-block;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:600}
.res.success{color:var(--success);background:rgba(52,199,89,.13)}
.res.fail{color:var(--error);background:rgba(255,69,58,.13)}

/* 链路按钮 */
.trace-btn{background:transparent;border:1px solid var(--bd);color:var(--t3);font-size:10px;padding:3px 9px;border-radius:5px;cursor:pointer;font-family:inherit;transition:all .15s}
.trace-btn:hover{color:var(--ac);border-color:var(--ac)}
.trace-btn.on{background:var(--ac);color:#fff;border-color:var(--ac)}

/* trace 面板（时间线） */
.trace-panel{margin-top:16px;background:var(--bg3);border:1px solid var(--bd);border-radius:9px;overflow:hidden}
.trace-head{display:flex;align-items:center;gap:8px;padding:11px 14px;border-bottom:1px solid var(--bd);background:var(--bg2)}
.trace-icon{color:var(--ac);font-size:14px}
.trace-label{font-size:12px;color:var(--t2);font-weight:600}
.trace-id{font-family:'SF Mono',ui-monospace,monospace;font-size:11px;color:var(--ac);background:var(--acg);padding:2px 8px;border-radius:5px}
.trace-count{font-size:11px;color:var(--t3);margin-left:auto}
.trace-list{padding:6px 0}
.trace-row{display:flex;align-items:center;gap:9px;padding:5px 14px;font-size:11px;position:relative}
.trace-row::before{content:'';position:absolute;left:20px;top:0;bottom:0;width:1px;background:var(--bd)}
.trace-row:first-child::before{top:50%}
.trace-row:last-child::before{bottom:50%}
.t-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;z-index:1;background:var(--t3)}
.t-dot.success{background:var(--success)}
.t-dot.fail{background:var(--error)}
.t-time{color:var(--t3);font-variant-numeric:tabular-nums;font-family:'SF Mono',ui-monospace,monospace;width:64px}
.t-act{font-size:11px;color:var(--ac);font-family:'SF Mono',ui-monospace,monospace}
.t-tgt{color:var(--t2)}
.t-tgt span{color:var(--t3);font-family:'SF Mono',ui-monospace,monospace}
.t-err{color:var(--error);margin-left:auto}
.trace-empty{padding:20px;text-align:center;color:var(--t3);font-size:12px}

/* 表格整体 */
:deep(.el-table){font-size:12px}
:deep(.el-table th.el-table__cell){background:var(--bg3);color:var(--t2);font-weight:600;font-size:11px}
:deep(.el-table tr:hover > td){background:var(--bg3) !important}

.fade-enter-active,.fade-leave-active{transition:opacity .2s}
.fade-enter-from,.fade-leave-to{opacity:0}
</style>
