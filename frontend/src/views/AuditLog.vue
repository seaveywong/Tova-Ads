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
const fAction = ref('')      // 动作类型筛选
const fUser = ref(0)         // 用户活动筛选
const fTrace = ref('')       // trace_id 拉全链路

const buildParams = () => {
  const t = tabs.find(x => x.key === tab.value)
  const p = { ...t.params, limit: 200 }
  // trace_id 模式：只按链路查，忽略其他筛选
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
const setTab = (k) => { tab.value = k; load() }

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
const rowColor = (r) => r.result === 'fail' ? 'var(--error)' : 'var(--success)'
</script>

<template>
  <div class="page">
    <div class="card">
      <div class="head">
        <div class="tabs">
          <button v-for="t in tabs" :key="t.key" :class="['tab',{on:tab===t.key}]" @click="setTab(t.key)">{{ t.label }}</button>
        </div>
        <button class="btn" @click="load">刷新</button>
      </div>
      <div class="filters">
        <input v-model="fAction" class="input" placeholder="动作类型（login/pause/upsert/create…）" @keyup.enter="load" />
        <select v-model="fUser" class="sel" @change="load">
          <option :value="0">全部用户</option>
          <option v-for="a in actors" :key="a.id" :value="a.id">{{ a.email }}</option>
        </select>
        <input v-model="fTrace" class="input" placeholder="trace_id 拉全链路" @keyup.enter="load" />
      </div>
      <el-table :data="logs" v-loading="loading" style="width:100%" empty-text="暂无日志" row-key="id" size="small">
        <el-table-column label="时间" width="150">
          <template #default="{ row }"><span class="mute">{{ fmtTime(row.created_at) }}</span></template>
        </el-table-column>
        <el-table-column label="类型" width="70">
          <template #default="{ row }"><span class="type">{{ TYPE_ZH[row.actor_type] || row.actor_type }}</span></template>
        </el-table-column>
        <el-table-column label="动作" width="130">
          <template #default="{ row }"><code class="act">{{ row.action_type }}</code></template>
        </el-table-column>
        <el-table-column label="对象" min-width="140">
          <template #default="{ row }">
            <span v-if="row.target_type" class="tgt">{{ row.target_type }}<span v-if="row.target_id"> #{{ row.target_id }}</span></span>
            <span v-else class="mute">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="isSuper" label="团队" width="60" align="center">
          <template #default="{ row }"><span class="mute">{{ row.tenant_id }}</span></template>
        </el-table-column>
        <el-table-column label="结果" width="60">
          <template #default="{ row }"><span :style="{color:rowColor(row)}">{{ row.result === 'success' ? '成功' : '失败' }}</span></template>
        </el-table-column>
        <el-table-column label="详情" min-width="180">
          <template #default="{ row }">
            <span v-if="row.friendly_error" class="err">{{ row.friendly_error }}</span>
            <span v-else-if="row.trigger_type" class="mute">{{ row.trigger_type }}{{ row.trigger_detail ? ' · ' + row.trigger_detail : '' }}</span>
            <span v-else class="mute">—</span>
          </template>
        </el-table-column>
        <el-table-column label="链路" width="70">
          <template #default="{ row }">
            <button class="link" @click="toggleTrace(row.trace_id)">{{ expandedTrace === row.trace_id ? '收起' : '展开' }}</button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="expandedTrace" class="trace-panel" v-loading="traceLoading">
        <div class="trace-head">链路 <code>{{ expandedTrace }}</code> · 共 {{ traceLogs.length }} 条</div>
        <div v-for="l in traceLogs" :key="l.id" class="trace-row">
          <span class="mute">{{ (l.created_at || '').slice(11,19) }}</span>
          <span class="type">{{ TYPE_ZH[l.actor_type] || l.actor_type }}</span>
          <code class="act">{{ l.action_type }}</code>
          <span v-if="l.target_type" class="tgt">{{ l.target_type }} #{{ l.target_id }}</span>
          <span :style="{color:rowColor(l)}">{{ l.result === 'success' ? '✓' : '✗' }}</span>
          <span v-if="l.friendly_error" class="err">{{ l.friendly_error }}</span>
        </div>
        <div v-if="!traceLogs.length && !traceLoading" class="empty">该链路无更多记录</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page{display:flex;flex-direction:column;gap:14px}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:10px;padding:18px}
.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:12px;flex-wrap:wrap}
.tabs{display:flex;gap:4px;flex-wrap:wrap}
.tab{padding:6px 14px;border:1px solid var(--bd);background:var(--bg2);color:var(--t2);border-radius:6px;font-size:12px;cursor:pointer}
.tab.on{background:var(--acg);color:var(--ac);border-color:var(--ac)}
.btn{padding:6px 14px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:6px;font-size:12px;cursor:pointer}
.filters{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.input{flex:1;min-width:180px;padding:6px 10px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:12px;font-family:inherit;box-sizing:border-box}
.input:focus{border-color:var(--ac);outline:none}
.sel{padding:6px 10px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:12px;min-width:160px}
.mute{color:var(--t3);font-size:11px;font-variant-numeric:tabular-nums}
.type{font-size:11px;color:var(--t2)}
.act{font-size:11px;color:var(--ac);font-family:'SF Mono',monospace}
.tgt{font-size:11px;color:var(--t2)}
.err{font-size:11px;color:var(--error)}
.link{background:none;border:none;color:var(--ac);font-size:11px;cursor:pointer;padding:0}
.link:hover{text-decoration:underline}
.trace-panel{margin-top:14px;padding:12px;background:var(--bg3);border-radius:8px;border:1px solid var(--bd)}
.trace-head{font-size:12px;color:var(--t2);margin-bottom:8px}
.trace-head code{font-family:'SF Mono',monospace;color:var(--ac)}
.trace-row{display:flex;gap:8px;align-items:center;padding:4px 0;font-size:11px;border-bottom:1px solid var(--bd)}
.trace-row:last-child{border-bottom:none}
.empty{padding:14px;text-align:center;color:var(--t3);font-size:12px}
</style>
