<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { GET, POST, DELETE } from '../api'
import { isSuperadminSync } from '../router'
import { accountStatus } from '../composables/useStatus'
import { DATE_PRESETS, presetRange } from '../composables/useDateRange'
import { useLatest } from '../composables/useLatest'
import { ElMessage, ElMessageBox } from 'element-plus'
import { showError } from '../composables/useError'
import { usePlatform } from '../composables/usePlatform'
import Fuse from 'fuse.js'
import DatePresetBar from '../components/DatePresetBar.vue'

const { t } = useI18n()
const router = useRouter()
const _reqGuard = useLatest()
const accounts = ref([])
const loading = ref(true)
const isSuper = ref(isSuperadminSync())

// 平台切换（纯前端过滤列表）+ 账户搜索（Fuse 模糊，照 Dashboard fuseAcc 用法）
const { platform } = usePlatform()
const searchQ = ref('')
const platAccounts = computed(() => platform.value === 'all' ? accounts.value : accounts.value.filter(a => (a.platform || 'fb') === platform.value))
const filteredAccounts = computed(() => {
  if (!searchQ.value.trim()) return platAccounts.value
  const fuseAcc = new Fuse(platAccounts.value, { keys: ['name', 'act_id'], threshold: 0.3 })
  return fuseAcc.search(searchQ.value.trim()).map(r => r.item)
})
// 展示行（platform=all 时按 FB/TT 分段：段头「Facebook (N)」+ 数据行；单平台时纯数据行）
const displayRows = computed(() => {
  const row = (a) => ({ type: 'row', a })
  if (platform.value !== 'all') return filteredAccounts.value.map(row)
  const fb = filteredAccounts.value.filter(a => (a.platform || 'fb') === 'fb')
  const tt = filteredAccounts.value.filter(a => (a.platform || 'fb') === 'tt')
  const out = []
  if (fb.length) out.push({ type: 'grp', key: 'fb', label: 'Facebook', n: fb.length })
  fb.forEach(a => out.push(row(a)))
  if (tt.length) out.push({ type: 'grp', key: 'tt', label: 'TikTok', n: tt.length })
  tt.forEach(a => out.push(row(a)))
  return out
})
// 切平台：勾选里已不可见的账户清掉（防批量操作打到隐藏行）
watch(platform, () => {
  const ids = new Set(platAccounts.value.map(a => a.act_id))
  selectedAccs.value = new Set([...selectedAccs.value].filter(id => ids.has(id)))
})

const datePreset = ref('today')
const showCustom = ref(false)
const customFrom = ref('')
const customTo = ref('')
const rangeLabel = computed(() => {
  if (showCustom.value && customFrom.value) return `${customFrom.value.slice(5)}~${(customTo.value || customFrom.value).slice(5)}`
  return DATE_PRESETS.find(o => o.key === datePreset.value)?.label || t('common.today')
})
const curRange = computed(() => {
  if (showCustom.value && customFrom.value) return { date_from: customFrom.value, date_to: customTo.value || customFrom.value }
  const r = presetRange(datePreset.value)
  return r ? { date_from: r[0], date_to: r[1] } : { date_from: '', date_to: '' }
})

const loadOpen = ref(false)
const loadables = ref([])
const loadLoading = ref(false)
const importing = ref(false)

const statusLabel = (s) => accountStatus(s).label
const statusDot = (s) => accountStatus(s).cls
const selectedAccs = ref(new Set())
const accLoading = ref(false)
const toggleAcc = (id) => { selectedAccs.value.has(id) ? selectedAccs.value.delete(id) : selectedAccs.value.add(id); selectedAccs.value = new Set(selectedAccs.value) }
const selectAllAccs = () => { if (selectedAccs.value.size === filteredAccounts.value.length) { selectedAccs.value.clear() } else { selectedAccs.value = new Set(filteredAccounts.value.map(a => a.act_id)) }; selectedAccs.value = new Set(selectedAccs.value) }
const isAccSelected = (id) => selectedAccs.value.has(id)
const batchRemove = async () => {
  if (!selectedAccs.value.size) return ElMessage.warning(t('ads.selectAccountsFirst'))
  try {
    await ElMessageBox.confirm(t('ads.batchRemoveConfirm', { n: selectedAccs.value.size }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' })
  } catch { return }
  accLoading.value = true
  const errs = []; let ok = 0
  for (const actId of selectedAccs.value) {
    try { await DELETE(`/fb/accounts/${actId}`); ok++ }
    catch (e) { errs.push(`${actId}: ${e.message || e}`) }
  }
  selectedAccs.value.clear()
  await load()   // 无论部分失败与否都刷新（被删的和残留的都要如实显示）
  accLoading.value = false
  if (errs.length) showError(t('ads.batchRemoveResult', { ok, fail: errs.length, errs: errs.join('\n') }), t('ads.batchSyncFailDetail'))
  else ElMessage.success(t('ads.removed', { n: ok }))
}
const batchSyncBase = computed(() => t('ads.batchSync'))   // locale 响应
const batchSyncLabel = ref('')
const batchSync = async () => {
  if (!selectedAccs.value.size) return ElMessage.warning(t('ads.selectAccountsFirst'))
  accLoading.value = true
  const targets = accounts.value.filter(a => selectedAccs.value.has(a.act_id) && a.fb_credential_id)
  const total = targets.length
  let ok = 0, fail = 0, done = 0
  const errs = []
  for (const a of targets) {
    batchSyncLabel.value = t('ads.syncing', { done, total })
    try { await POST('/fb/credentials/' + a.fb_credential_id + '/refresh-accounts'); ok++ }
    catch (e) { fail++; errs.push(`${a.act_id} (${a.name || ''}): ${e.message || e}`) }
    done++
  }
  batchSyncLabel.value = ''
  if (fail) {
    showError(t('ads.batchSyncResult', { ok, fail, errs: errs.join('\n') }), t('ads.batchSyncFailDetail'))
  } else if (!ok && !total) {
    ElMessage.warning(t('ads.batchSyncNoToken'))   // 全跳过=选中的都没绑令牌，不是"刷新成功 0 个"
  } else {
    ElMessage.success(t('ads.refreshed', { n: ok }))
  }
  selectedAccs.value.clear(); await load()
  accLoading.value = false
}
const balKindLabel = (k) => k === 'limited' ? t('ads.balLimited') : (k === 'unlimited' ? t('ads.balUnlimited') : t('ads.balHighLimited'))
// 平台 chip（照 AdManager platChip：仅显式 fb/tt，未知平台不标）
const platChip = (a) => (a && (a.platform === 'tt' || a.platform === 'fb')) ? a.platform : ''
const boundTokenTitle = (a) => {
  const alias = a.bound_alias || t('ads.unbound')
  const state = a.bound_available ? t('ads.tokenOk') : t('ads.tokenAbnormal')
  const pool = a.pool_aliases ? ' · ' + t('ads.rotatingToken', { aliases: a.pool_aliases }) : ''
  return `${alias} · ${state}${pool}`
}
const cpa = (a) => (a.recent_conversions > 0) ? fmtMoney((a.recent_spend / a.recent_conversions), a.currency) : '-'

const load = async () => {
  const isLatest = _reqGuard.next()
  loading.value = true
  try {
    const ps = new URLSearchParams(curRange.value)
    const r = await GET('/fb/accounts?' + ps.toString())
    if (!isLatest()) return   // 快速切日期时旧响应后到——丢弃
    accounts.value = r
  } catch (e) { if (isLatest()) ElMessage.error(e.message || t('common.opFail')) }
  if (isLatest()) loading.value = false
}
const openLoad = async () => {
  loadOpen.value = true; loadLoading.value = true
  // 平台分流：FB 勾选清单 + TT 授权未纳管账户并拉（一侧失败不影响另一侧展示）
  const rows = []
  const [fb, tt] = await Promise.allSettled([
    GET('/fb/credentials/loadable-accounts'),
    GET('/tt/loadable-accounts'),
  ])
  if (fb.status === 'fulfilled') for (const a of fb.value) rows.push({ ...a, platform: 'fb', _checked: false })
  if (tt.status === 'fulfilled') for (const a of tt.value) rows.push({ account_id: a.act_id, name: a.name || a.act_id, platform: 'tt', _checked: false })
  if (fb.status === 'rejected' && tt.status === 'rejected') ElMessage.error(fb.reason?.message || t('common.opFail'))
  loadables.value = rows
  loadLoading.value = false
}
const doImport = async () => {
  const fbIds = loadables.value.filter(a => a._checked && a.platform !== 'tt' && !a.imported).map(a => a.account_id).filter(Boolean)
  const ttIds = loadables.value.filter(a => a._checked && a.platform === 'tt').map(a => a.account_id).filter(Boolean)
  if (!fbIds.length && !ttIds.length) return ElMessage.warning(t('ads.selectToImport'))
  importing.value = true
  try {
    let ok = 0, skipped = 0
    if (fbIds.length) {
      const r = await POST('/fb/import', { account_ids: fbIds })
      ok += r.count || 0; skipped += r.skipped_existing || 0
    }
    if (ttIds.length) {
      const r = await POST('/tt/import', { act_ids: ttIds })
      ok += (r.imported || []).length; skipped += r.skipped_existing || 0
    }
    ElMessage.success(t('ads.imported', { n: ok, skipped }))
    loadOpen.value = false; await load()
  } catch (e) { ElMessage.error(t('ads.opFailMsg', { msg: e.message || '' })) }
  importing.value = false
}
const copyId = (id) => { navigator.clipboard?.writeText(id); ElMessage.success(t('ads.idCopied', { id })) }
const onCmd = async (cmd, a) => {
  if (cmd === 'manager') router.push({ name: 'ad-manager', query: { act: a.act_id } })
  else if (cmd === 'sync') {
    if (!a.fb_credential_id) return ElMessage.warning(t('ads.noBoundToken'))
    try { await POST(`/fb/credentials/${a.fb_credential_id}/refresh-accounts`); ElMessage.success(t('ads.refreshedSimple')); await load() }
    catch (e) { ElMessage.error(t('ads.opFailMsg', { msg: e.message || '' })) }
  } else if (cmd === 'warmup') {
    await toggleWarmup([a.act_id], a.warmup_state !== 'warming')
  } else if (cmd === 'remove') {
    try {
      await ElMessageBox.confirm(t('ads.removeConfirm', { name: a.name }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' })
      await DELETE(`/fb/accounts/${a.act_id}`); ElMessage.success(t('ads.removedSimple')); await load()
    } catch(e) {}
  }
}
const fmtMoney = (v, cur) => (v == null) ? '-' : `${(cur || '').replace('USD', '$')} ${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
const toggleWarmup = async (actIds, arm) => {
  accLoading.value = true
  let ok = 0
  for (const actId of actIds) {
    try { await POST(`/guard/warmup/${arm ? 'arm' : 'disarm'}`, { act_ids: [actId] }); ok++ }
    catch (e) { ElMessage.error(`${actId}: ${e.message || t('common.fail')}`) }
  }
  if (ok) ElMessage.success(t('ads.warmupToggled', { label: arm ? t('ads.warmupArm') : t('ads.warmupDisarm'), n: ok }))
  accLoading.value = false; await load()
}
const batchWarmup = async (arm) => {
  if (!selectedAccs.value.size) return ElMessage.warning(t('ads.selectAccountsFirst'))
  await toggleWarmup([...selectedAccs.value], arm)
  selectedAccs.value.clear()
}

const syncing = ref(false)
const syncCampaigns = async () => {
  syncing.value = true
  try {
    await POST('/ads/sync-cache')   // 后台异步采集（advisory lock 111，已在跑则自动跳过），立即返回
    ElMessage.success(t('ads.syncBgStarted'))
    setTimeout(() => { load() }, 60000)   // 同步约 1-2 分钟，60s 后自动刷新一次
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  syncing.value = false
}

onMounted(async () => {
  await load()
  try { const me = await GET('/auth/me'); isSuper.value = !!me.is_superadmin; localStorage.setItem('tova_super', me.is_superadmin ? '1' : '0') } catch(e) {}
})
</script>

<template>
  <div class="page">
    <div class="date-bar">
      <h2 class="title">{{ t('ads.title') }} <span class="cnt">{{ filteredAccounts.length }}</span></h2>
      <DatePresetBar :presets="DATE_PRESETS" v-model="datePreset" @preset="() => { showCustom = false; load() }" @custom="({from,to}) => { customFrom = from; customTo = to; showCustom = true; load() }" />
      <input v-model="searchQ" class="acc-search" :placeholder="t('ads.searchPh')" />
      <button class="refresh-btn primary" @click="openLoad">{{ t('ads.loadAccounts') }}</button>
      <button class="refresh-btn" :disabled="syncing" @click="syncCampaigns">{{ syncing ? t('common.loading') : t('ads.syncCampaigns') }}</button>
    </div>
    <div v-if="selectedAccs.size" class="batch-bar">
      <span class="batch-count">{{ t('ads.selected', { n: selectedAccs.size }) }}</span>
      <button class="batch-btn" @click="batchSync" :disabled="accLoading">{{ batchSyncLabel || batchSyncBase }}</button>
      <button class="batch-btn" @click="batchWarmup(true)" :disabled="accLoading">{{ t('ads.warmupArm') }}</button>
      <button class="batch-btn" @click="batchWarmup(false)" :disabled="accLoading">{{ t('ads.warmupDisarm') }}</button>
      <button class="batch-btn danger" @click="batchRemove" :disabled="accLoading">{{ t('ads.batchRemove') }}</button>
      <button class="batch-btn" @click="selectedAccs.clear()">{{ t('common.cancel') }}</button>
    </div>
    <div class="tbl" v-loading="loading || accLoading">
      <div class="row head">
        <div><input type="checkbox" :checked="selectedAccs.size === filteredAccounts.length && filteredAccounts.length > 0" @click="selectAllAccs" /></div>
        <div>{{ t('common.status') }}</div><div>{{ t('ads.account') }}</div><div>{{ t('ads.balance') }}</div><div>{{ t('ads.availableCredit') }}</div>
        <div>{{ t('ads.spend') }} <span class="rng">{{ rangeLabel }}</span></div><div>{{ t('ads.conversions') }}</div><div>CPA</div><div>{{ t('ads.activeToken') }}</div><div></div>
      </div>
      <template v-for="d in displayRows" :key="d.type === 'grp' ? 'grp-' + d.key : d.a.act_id">
        <div v-if="d.type === 'grp'" class="grp-title" :class="d.key"><span class="grp-dot" :class="d.key"></span>{{ d.label }} <span class="grp-n">({{ d.n }})</span></div>
        <div v-else class="row">
        <div @click.stop><input type="checkbox" :checked="isAccSelected(d.a.act_id)" @change="toggleAcc(d.a.act_id)" /></div>
        <div><span class="dot" :class="statusDot(d.a.account_status)"></span>{{ statusLabel(d.a.account_status) }}<span v-if="d.a.warmup_state === 'warming'" class="warmup-badge" :title="t('ads.warmupBadgeTip')">{{ t('ads.warmupShort') }}</span></div>
        <div class="acc">
          <div class="acc-name clk" :title="t('ads.openAdManager')" @click="router.push({ name: 'ad-manager', query: { act: d.a.act_id } })"><span v-if="platChip(d.a)" :class="['plat-chip', platChip(d.a)]">{{ platChip(d.a).toUpperCase() }}</span>{{ (d.a.name && d.a.name !== d.a.act_id) ? d.a.name : t('ads.unnamedAccount') }}</div>
          <div class="acc-id" @click="copyId(d.a.act_id)">{{ d.a.act_id }}</div>
        </div>
        <div>{{ fmtMoney(d.a.balance, d.a.currency) }}<span v-if="d.a.balance_usd != null && d.a.currency !== 'USD'" class="sub"> ≈${{ d.a.balance_usd }}</span></div>
        <div>
          <span v-if="d.a.available_usd != null">${{ d.a.available_usd }}</span>
          <span v-else class="tag">{{ balKindLabel(d.a.balance_kind) }}</span>
        </div>
        <div>{{ fmtMoney(d.a.recent_spend, d.a.currency) }}</div>
        <div>{{ d.a.recent_conversions || 0 }}</div>
        <div>{{ cpa(d.a) }}</div>
        <div>
          <span class="tag" :class="d.a.bound_available ? 'ok' : (d.a.bound_alias ? 'warn' : 'off')"
                :title="boundTokenTitle(d.a)">
            {{ d.a.bound_alias || t('ads.unbound') }}
          </span>
          <span v-if="(d.a.pool_count||0) > 1" class="pool-n" :title="d.a.pool_aliases || t('ads.poolTooltip', { n: d.a.pool_count })">+{{ (d.a.pool_count||0) - 1 }}</span>
        </div>
        <div class="ops">
          <el-dropdown trigger="click" @command="cmd => onCmd(cmd, d.a)" placement="bottom-end">
            <button class="more-btn">⚙</button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="manager">{{ t('ads.viewInManager') }}</el-dropdown-item>
                <el-dropdown-item command="sync">{{ t('ads.syncStatusBalance') }}</el-dropdown-item>
                <el-dropdown-item command="warmup" divided>{{ d.a.warmup_state === 'warming' ? t('ads.warmupDisarm') : t('ads.warmupArm') }}</el-dropdown-item>
                <el-dropdown-item command="remove">{{ t('ads.removeManaged') }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        </div>
      </template>
      <div v-if="!filteredAccounts.length && !loading" class="empty" :class="{ 'empty-cta': !accounts.length }">
        <template v-if="accounts.length">
          <div class="empty-title">{{ t('ads.noMatch') }}</div>
        </template>
        <template v-else>
          <div class="empty-title">{{ t('ads.emptyTitle') }}</div>
          <template v-if="platform === 'tt'">
            <div class="empty-step">{{ t('ads.emptyStep1Tt') }} <router-link to="/tokens" class="empty-link">{{ t('ads.emptyLinkTt') }}</router-link></div>
          </template>
          <template v-else>
            <div class="empty-step">{{ t('ads.emptyStep1') }} <router-link to="/tokens" class="empty-link">{{ t('ads.emptyLink') }}</router-link> {{ t('ads.emptyStep1b') }}</div>
            <div class="empty-step">{{ t('ads.emptyStep2') }}</div>
          </template>
        </template>
      </div>
    </div>

    <div v-if="loadOpen" class="overlay" @click.self="loadOpen = false">
      <div class="modal">
        <div class="modal-title">{{ t('ads.loadAccounts') }} <button class="mb" @click="loadOpen = false">✕</button></div>
        <div class="load-list" v-loading="loadLoading">
          <div v-for="a in loadables" :key="a.platform + ':' + a.account_id" class="load-row">
            <input type="checkbox" v-model="a._checked" :disabled="a.imported" />
            <span v-if="platChip(a)" :class="['plat-chip', platChip(a)]">{{ platChip(a).toUpperCase() }}</span>
            <span class="lm-name">{{ a.name }}</span>
            <code>{{ a.account_id }}</code>
            <span class="tag" :class="a.imported ? 'off' : 'ok'">{{ a.imported ? t('ads.importedTag') : t('ads.importableTag') }}</span>
          </div>
          <div v-if="!loadables.length && !loadLoading" class="empty">{{ t('ads.noLoadable') }}</div>
        </div>
        <button class="btn primary" :disabled="importing" style="margin-top:12px" @click="doImport">{{ importing ? t('ads.importing') : t('ads.importSelected') }}</button>
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
/* 按钮方言：默认=描边（次要动作），.primary=实心（唯一主行动「载入账户」） */
.refresh-btn { padding: 0 16px; height: 32px; line-height: 30px; background: transparent; color: var(--ac); border: 1px solid var(--ac); border-radius: var(--rs); font-size: 13px; cursor: pointer; box-sizing: border-box }
.refresh-btn:hover { background: var(--ac); color: #fff }
.refresh-btn.primary { background: var(--ac); color: #fff; border-color: var(--ac) }
.refresh-btn.primary:hover { filter: brightness(1.08); background: var(--ac) }
.cnt { font-size: 13px; color: var(--t3); font-weight: 400 }
.rng { color: var(--t3); font-weight: 400; font-size: 11px }
.acc-search { height: 32px; padding: 0 10px; background: var(--bg2); color: var(--t1); border: 1px solid var(--bd); border-radius: var(--rs); font-size: 13px; box-sizing: border-box; color-scheme: dark; width: 150px }
.acc-search:focus { outline: none; border-color: var(--ac) }
.acc-search::placeholder { color: var(--t3) }
.tbl { display: flex; flex-direction: column; border: 1px solid var(--bd); border-radius: 10px; overflow-x: auto }
.row { display: grid; grid-template-columns: 30px 0.8fr 1.7fr 1fr 0.8fr 1fr 0.5fr 0.7fr 1fr 44px; gap: 6px; padding: 8px 12px; align-items: center; font-size: 13px; border-bottom: 1px solid var(--bd); min-width: 1080px; font-variant-numeric: tabular-nums }
.row.head { background: var(--bg2); color: var(--t3); font-size: 12px; font-weight: 600 }
.row:last-child { border-bottom: none }
.row:not(.head):hover { background: var(--bg2) }
/* platform=all 时 FB/TT 分段标题：品牌点 + 粗体 + 底色带；TT 段头上加分割线与段间距 */
.grp-title { display: flex; align-items: center; gap: 7px; padding: 10px 12px 8px; font-size: 12px; font-weight: 700; color: var(--t1); border-bottom: 1px solid var(--bd); letter-spacing: 0.03em; background: var(--bg2) }
.grp-title.tt { border-top: 1px solid var(--bd2); margin-top: 6px }
.grp-n { color: var(--t3); font-weight: 500 }
.grp-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--t3) }
.grp-dot.fb { background: #1877f2 }
.grp-dot.tt { background: linear-gradient(135deg, #25f4ee 45%, #fe2c55 55%) }
.acc-name { font-weight: 600; color: var(--t1) }
.acc-name.clk { cursor: pointer }
.acc-name.clk:hover { color: var(--ac); text-decoration: underline }
.acc-id { font-size: 11px; color: var(--t3); cursor: pointer }
.sub { color: var(--t3); font-size: 11px }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 5px; background: var(--t3); vertical-align: middle }
.dot.ok { background: var(--success) } .dot.warn { background: var(--warning) } .dot.err { background: var(--error) } .dot.off { background: var(--t3); opacity: .5 }
.tag { font-size: 11px; padding: 1px 6px; border-radius: 4px; background: var(--bg3); color: var(--t2) }
.tag.ok { color: var(--success) } .tag.warn { color: var(--warning) } .tag.off { color: var(--t3) }
.pool-n { font-size: 10px; color: var(--success); margin-left: 2px; font-weight: 600 }
.ops { display: flex; justify-content: flex-end }
.more-btn { width: 26px; height: 24px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t2); font-size: 13px; cursor: pointer; border-radius: 4px; padding: 0; line-height: 22px; text-align: center }
.more-btn:hover { background: var(--ac); color: #fff; border-color: var(--ac) }
.empty { padding: 40px; text-align: center; color: var(--t3) }
.empty-cta { padding: 50px 30px; }
.empty-title { font-size: 15px; color: var(--t2); font-weight: 600; margin-bottom: 14px; }
.empty-step { font-size: 13px; color: var(--t3); line-height: 1.8; }
.empty-link { color: var(--ac); text-decoration: none; }
.empty-link:hover { text-decoration: underline; }
.batch-bar { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; padding: 6px 12px; background: var(--bg2); border: 1px solid var(--ac); border-radius: var(--rs) }
.batch-count { font-size: 12px; color: var(--ac); font-weight: 600; margin-right: 4px }
.batch-btn { font-size: 12px; padding: 4px 12px; height: 28px; border-radius: var(--rs); border: 1px solid var(--ac); background: rgba(10,132,255,.1); color: var(--ac); cursor: pointer; box-sizing: border-box }
.batch-btn:hover { background: var(--ac); color: #fff }
.batch-btn.danger { border-color: var(--error); color: var(--error); background: rgba(239,68,68,.1) }
.batch-btn.danger:hover { background: var(--error); color: #fff }
.batch-btn:disabled { opacity: .5; cursor: wait }
.warmup-badge { font-size: 9px; padding: 1px 5px; border-radius: 3px; background: rgba(249,115,22,.15); color: #f97316; margin-left: 4px; font-weight: 600; vertical-align: middle }
.overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, .5); display: flex; align-items: center; justify-content: center; z-index: 2500 }
.modal { background: var(--bg2); border: 1px solid var(--bd); border-radius: 12px; padding: 20px; width: 540px; max-width: 92vw; max-height: 80vh; overflow: auto }
.modal-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-weight: 600 }
.load-list { max-height: 360px; overflow: auto }
.load-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--bd); font-size: 13px }
.lm-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.load-row code { color: var(--t3); font-size: 11px }
/* 平台 chip 用 main.css 全局 .plat-chip */
</style>
