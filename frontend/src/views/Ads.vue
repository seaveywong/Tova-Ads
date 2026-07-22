<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { GET, POST, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()
const accounts = ref([])
const loading = ref(true)
const isSuper = ref(localStorage.getItem('tova_super') === '1')

const datePreset = ref('today')
const showCustom = ref(false)
const customFrom = ref('')
const customTo = ref('')
const dateOptions = [
  { label: '今天', value: 'today' },
  { label: '昨天', value: 'yesterday' },
  { label: '近2天', value: 'last_2d' },
  { label: '近7天', value: 'last_7d' },
]
const _fmtD = (d) => d.toISOString().slice(0, 10)
const rangeLabel = computed(() => {
  if (showCustom.value && customFrom.value) return `${customFrom.value.slice(5)}~${(customTo.value || customFrom.value).slice(5)}`
  return dateOptions.find(o => o.value === datePreset.value)?.label || '近2天'
})
const curRange = computed(() => {
  if (showCustom.value && customFrom.value) return { date_from: customFrom.value, date_to: customTo.value || customFrom.value }
  const today = new Date()
  if (datePreset.value === 'today') return { date_from: _fmtD(today), date_to: _fmtD(today) }
  if (datePreset.value === 'yesterday') { const y = new Date(Date.now() - 86400000); return { date_from: _fmtD(y), date_to: _fmtD(y) } }
  const days = { last_2d: 2, last_7d: 7 }[datePreset.value] || 2
  return { date_from: _fmtD(new Date(Date.now() - days * 86400000)), date_to: _fmtD(today) }
})

const loadOpen = ref(false)
const loadables = ref([])
const loadLoading = ref(false)
const importing = ref(false)

const STATUS_LABEL = { 1: '正常', 2: '禁用', 3: '支付失败', 7: '政策违规', 9: '宽限期', 100: '待关闭', 101: '已关闭' }
const statusDot = (s) => s === 1 ? 'ok' : ([2, 101].includes(s) ? 'off' : ([3, 7, 9].includes(s) ? 'err' : 'warn'))
const selectedAccs = ref(new Set())
const accLoading = ref(false)
const toggleAcc = (id) => { selectedAccs.value.has(id) ? selectedAccs.value.delete(id) : selectedAccs.value.add(id); selectedAccs.value = new Set(selectedAccs.value) }
const selectAllAccs = () => { if (selectedAccs.value.size === accounts.value.length) { selectedAccs.value.clear() } else { selectedAccs.value = new Set(accounts.value.map(a => a.act_id)) }; selectedAccs.value = new Set(selectedAccs.value) }
const isAccSelected = (id) => selectedAccs.value.has(id)
const batchRemove = async () => {
  if (!selectedAccs.value.size) return ElMessage.warning('先勾选账户')
  try {
    await ElMessageBox.confirm(`移除 ${selectedAccs.value.size} 个账户纳管？（历史数据保留）`, '确认', { type: 'warning' })
    accLoading.value = true
    for (const actId of selectedAccs.value) { await DELETE(`/fb/accounts/${actId}`) }
    ElMessage.success('已移除 ' + selectedAccs.value.size + ' 个账户'); selectedAccs.value.clear(); await load()
  } catch(e) {} finally { accLoading.value = false }
}
const batchSync = async () => {
  if (!selectedAccs.value.size) return ElMessage.warning('先勾选账户')
  accLoading.value = true
  let ok = 0
  for (const a of accounts.value) {
    if (!selectedAccs.value.has(a.act_id) || !a.fb_credential_id) continue
    try { await POST('/fb/credentials/' + a.fb_credential_id + '/refresh-accounts'); ok++ } catch (e) {}
  }
  ElMessage.success(`已刷新 ${ok} 个账户`); selectedAccs.value.clear(); await load()
  accLoading.value = false
}
const balKindLabel = (k) => k === 'limited' ? '有限' : (k === 'unlimited' ? '不限' : '高限')
const cpa = (a) => (a.recent_conversions > 0) ? (a.recent_spend / a.recent_conversions).toFixed(2) : '-'

const load = async () => {
  loading.value = true
  try {
    const ps = new URLSearchParams(curRange.value)
    accounts.value = await GET('/fb/accounts?' + ps.toString())
  } catch (e) { ElMessage.error(e.message || '加载失败') }
  loading.value = false
}
const openLoad = async () => {
  loadOpen.value = true; loadLoading.value = true
  try { loadables.value = (await GET('/fb/credentials/loadable-accounts')).map(a => ({ ...a, _checked: false })) }
  catch (e) { ElMessage.error(e.message || '加载失败') }
  loadLoading.value = false
}
const doImport = async () => {
  const ids = loadables.value.filter(a => a._checked && !a.imported).map(a => a.account_id).filter(Boolean)
  if (!ids.length) return ElMessage.warning('勾选要导入的账户')
  importing.value = true
  try {
    const r = await POST('/fb/import', { account_ids: ids })
    ElMessage.success(`已导入 ${r.count || 0} 个（跳过已存在 ${r.skipped_existing || 0}）`)
    loadOpen.value = false; await load()
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
  importing.value = false
}
const copyId = (id) => { navigator.clipboard?.writeText(id); ElMessage.success('ID 已复制：' + id) }
const onCmd = async (cmd, a) => {
  if (cmd === 'manager') router.push({ name: 'ad-manager', query: { act: a.act_id } })
  else if (cmd === 'sync') {
    if (!a.fb_credential_id) return ElMessage.warning('该账户未绑定令牌')
    try { await POST(`/fb/credentials/${a.fb_credential_id}/refresh-accounts`); ElMessage.success('已刷新'); await load() }
    catch (e) { ElMessage.error('失败：' + (e.message || '')) }
  } else if (cmd === 'remove') {
    try {
      await ElMessageBox.confirm(`移除「${a.name}」纳管？（历史数据保留）`, '确认', { type: 'warning' })
      await DELETE(`/fb/accounts/${a.act_id}`); ElMessage.success('已移除'); await load()
    } catch(e) {}
  }
}
const fmtMoney = (v, cur) => (v == null) ? '-' : `${(cur || '').replace('USD', '$')} ${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`

onMounted(async () => {
  await load()
  try { const me = await GET('/auth/me'); isSuper.value = !!me.is_superadmin; localStorage.setItem('tova_super', me.is_superadmin ? '1' : '0') } catch(e) {}
})
</script>

<template>
  <div class="page">
    <div class="date-bar">
      <h2 class="title">广告账户 <span class="cnt">{{ accounts.length }}</span></h2>
      <button v-for="opt in dateOptions" :key="opt.value" class="date-btn"
        :class="{ active: datePreset === opt.value && !showCustom }"
        @click="showCustom = false; datePreset = opt.value; load()">{{ opt.label }}</button>
      <button class="date-btn" :class="{ active: showCustom }" @click="showCustom = !showCustom">自定义</button>
      <div v-if="showCustom" class="custom-range">
        <input type="date" v-model="customFrom" class="date-input" /><span class="date-sep">—</span>
        <input type="date" v-model="customTo" class="date-input" />
        <button class="date-btn apply" @click="load">查询</button>
      </div>
      <button class="refresh-btn primary" @click="openLoad">载入账户</button>
    </div>
    <div v-if="selectedAccs.size" class="batch-bar">
      <span class="batch-count">已选 {{ selectedAccs.size }}</span>
      <button class="batch-btn" @click="batchSync" :disabled="accLoading">批量同步</button>
      <button class="batch-btn danger" @click="batchRemove" :disabled="accLoading">批量移除</button>
      <button class="batch-btn" @click="selectedAccs.clear()">取消</button>
    </div>
    <div class="tbl" v-loading="loading || accLoading">
      <div class="row head">
        <div><input type="checkbox" :checked="selectedAccs.size === accounts.length && accounts.length > 0" @click="selectAllAccs" /></div>
        <div>状态</div><div>账户</div><div>余额</div><div>可用额度</div>
        <div>消耗 <span class="rng">{{ rangeLabel }}</span></div><div>转化</div><div>CPA</div><div>绑令牌</div><div></div>
      </div>
      <div v-for="a in accounts" :key="a.act_id" class="row">
        <div @click.stop><input type="checkbox" :checked="isAccSelected(a.act_id)" @change="toggleAcc(a.act_id)" /></div>
        <div><span class="dot" :class="statusDot(a.account_status)"></span>{{ STATUS_LABEL[a.account_status] || a.account_status }}</div>
        <div class="acc">
          <div class="acc-name">{{ a.name }}</div>
          <div class="acc-id" @click="copyId(a.act_id)">{{ a.act_id }}</div>
        </div>
        <div>{{ fmtMoney(a.balance, a.currency) }}<span v-if="a.balance_usd != null && a.currency !== 'USD'" class="sub"> ≈${{ a.balance_usd }}</span></div>
        <div>
          <span v-if="a.available_usd != null">${{ a.available_usd }}</span>
          <span v-else class="tag">{{ balKindLabel(a.balance_kind) }}</span>
        </div>
        <div>{{ fmtMoney(a.recent_spend, a.currency) }}</div>
        <div>{{ a.recent_conversions || 0 }}</div>
        <div>{{ cpa(a) }}</div>
        <div><span class="tag" :class="a.bound_available ? 'ok' : (a.bound_alias ? 'warn' : 'off')">{{ a.bound_alias || '未绑' }}</span></div>
        <div class="ops">
          <el-dropdown trigger="click" @command="cmd => onCmd(cmd, a)" placement="bottom-end">
            <button class="more-btn">⚙</button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="manager">在广告管理器查看</el-dropdown-item>
                <el-dropdown-item command="sync">同步状态/余额</el-dropdown-item>
                <el-dropdown-item command="remove" divided>移除纳管</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
      <div v-if="!accounts.length && !loading" class="empty">暂无广告账户，点「载入账户」导入</div>
    </div>

    <div v-if="loadOpen" class="overlay" @click.self="loadOpen = false">
      <div class="modal">
        <div class="modal-title">载入账户 <button class="mb" @click="loadOpen = false">✕</button></div>
        <div class="load-list" v-loading="loadLoading">
          <div v-for="a in loadables" :key="a.account_id" class="load-row">
            <input type="checkbox" v-model="a._checked" :disabled="a.imported" />
            <span class="lm-name">{{ a.name }}</span>
            <code>{{ a.account_id }}</code>
            <span class="tag" :class="a.imported ? 'off' : 'ok'">{{ a.imported ? '已导入' : '可导入' }}</span>
          </div>
          <div v-if="!loadables.length && !loadLoading" class="empty">无可载入账户（先在 Facebook 授权页绑定令牌）</div>
        </div>
        <button class="btn primary" :disabled="importing" style="margin-top:12px" @click="doImport">{{ importing ? '导入中…' : '导入选中' }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.date-bar { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; margin-bottom: 14px }
.title { margin-right: auto; font-size: 18px }
.date-btn { padding: 0 14px; height: 32px; line-height: 30px; background: var(--bg2); color: var(--t2); border: 1px solid var(--bd); border-radius: var(--rs); font-size: 13px; cursor: pointer; transition: all .15s; box-sizing: border-box }
.date-btn:hover { color: var(--t1); border-color: var(--bd2) }
.date-btn.active { background: var(--ac); color: #fff; border-color: var(--ac) }
.date-btn.apply { background: var(--ac); color: #fff; border-color: var(--ac); margin-left: 4px }
.custom-range { display: flex; align-items: center; gap: 6px; margin-left: 4px }
.date-input { background: var(--bg3); color: var(--t1); border: 1px solid var(--bd); border-radius: var(--rs); padding: 5px 10px; font-size: 13px; color-scheme: dark }
.date-input:focus { outline: none; border-color: var(--ac) }
.date-sep { color: var(--t3); font-size: 13px }
.refresh-btn { padding: 0 16px; height: 32px; line-height: 30px; background: var(--ac); color: #fff; border: 1px solid var(--ac); border-radius: var(--rs); font-size: 13px; cursor: pointer; box-sizing: border-box }
.refresh-btn:hover { filter: brightness(1.08) }
.cnt { font-size: 13px; color: var(--t3); font-weight: 400 }
.rng { color: var(--t3); font-weight: 400; font-size: 11px }
.tbl { display: flex; flex-direction: column; border: 1px solid var(--bd); border-radius: 10px; overflow: hidden }
.row { display: grid; grid-template-columns: 30px 0.8fr 1.7fr 1fr 0.8fr 1fr 0.5fr 0.7fr 1fr 44px; gap: 6px; padding: 8px 12px; align-items: center; font-size: 13px; border-bottom: 1px solid var(--bd) }
.row.head { background: var(--bg2); color: var(--t3); font-size: 12px; font-weight: 600 }
.row:last-child { border-bottom: none }
.acc-name { font-weight: 600; color: var(--t1) }
.acc-id { font-size: 11px; color: var(--t3); cursor: pointer }
.sub { color: var(--t3); font-size: 11px }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 5px; background: var(--t3); vertical-align: middle }
.dot.ok { background: var(--success) } .dot.warn { background: var(--warning) } .dot.err { background: var(--error) } .dot.off { background: var(--t3); opacity: .5 }
.tag { font-size: 11px; padding: 1px 6px; border-radius: 4px; background: var(--bg3); color: var(--t2) }
.tag.ok { color: var(--success) } .tag.warn { color: var(--warning) } .tag.off { color: var(--t3) }
.ops { display: flex; justify-content: flex-end }
.more-btn { width: 26px; height: 24px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t2); font-size: 13px; cursor: pointer; border-radius: 4px; padding: 0; line-height: 22px; text-align: center }
.more-btn:hover { background: var(--ac); color: #fff; border-color: var(--ac) }
.empty { padding: 40px; text-align: center; color: var(--t3) }
.batch-bar { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; padding: 6px 12px; background: var(--bg2); border: 1px solid var(--ac); border-radius: var(--rs) }
.batch-count { font-size: 12px; color: var(--ac); font-weight: 600; margin-right: 4px }
.batch-btn { font-size: 12px; padding: 4px 12px; height: 28px; border-radius: var(--rs); border: 1px solid var(--ac); background: rgba(10,132,255,.1); color: var(--ac); cursor: pointer; box-sizing: border-box }
.batch-btn:hover { background: var(--ac); color: #fff }
.batch-btn.danger { border-color: var(--error); color: var(--error); background: rgba(239,68,68,.1) }
.batch-btn.danger:hover { background: var(--error); color: #fff }
.batch-btn:disabled { opacity: .5; cursor: wait }
.overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, .5); display: flex; align-items: center; justify-content: center; z-index: 2500 }
.modal { background: var(--bg2); border: 1px solid var(--bd); border-radius: 12px; padding: 20px; width: 540px; max-height: 80vh; overflow: auto }
.modal-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-weight: 600 }
.load-list { max-height: 360px; overflow: auto }
.load-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--bd); font-size: 13px }
.lm-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.load-row code { color: var(--t3); font-size: 11px }
</style>
