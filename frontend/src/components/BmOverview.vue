<script setup>
// 跨令牌 BM 总览（批QQ 资产中心）：BM 表 + 行点击懒加载成员/资产详情（复用令牌抽屉同款端点）
import { ref, computed, onMounted } from 'vue'
import { GET, POST, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isSuperadminSync } from '../router'
import { getToken } from '../api'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
const props = defineProps({ tokenFilter: { type: Object, default: null } })
const emit = defineEmits(['clear-filter'])
const isSuperSync = isSuperadminSync()
const _role = (() => { try { return JSON.parse(atob((getToken() || '').split('.')[1] || '').replace(/-/g, '+').replace(/_/g, '/')).role || '' } catch { return '' } })()
const isOwner = _role === 'owner'
// 后端另有权威校验（_cred_manageable：超管/owner/created_by），此处仅控制 UI 显隐
const rows = ref([])
const loading = ref(true)
const filteredRows = computed(() => props.tokenFilter ? rows.value.filter(r => r.via_cred_id === props.tokenFilter.id) : rows.value)
const load = async () => {
  loading.value = true
  try {
    const r = await GET('/fb/bm-overview', 60000)
    rows.value = (r && r.bms) || r || []
    writeOk.value = r?.write_ok !== false
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  loading.value = false
}
const writeOk = ref(true)   // App 没过 business_management Review 时隐藏邀请/移除（批WW）
onMounted(load)

const detailOpen = ref(false)
const detail = ref(null)   // { row, members?, assets?, tab }
const detailLoading = ref(false)
const openDetail = async (r) => {
  detail.value = { row: r, members: null, assets: null, tab: 'members' }
  detailOpen.value = true
  detailLoading.value = true
  try {
    const [m, a] = await Promise.all([
      GET(`/fb/credentials/${r.via_cred_id}/bm/${r.id}/members`, 30000).catch(() => null),
      GET(`/fb/credentials/${r.via_cred_id}/bm/${r.id}/assets`, 30000).catch(() => null),
    ])
    detail.value.members = m
    detail.value.assets = a
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  detailLoading.value = false
}
const roleClass = (r) => (r === '完全' || r === 'ADMIN' || String(r).toLowerCase().includes('admin')) ? 'full' : 'basic'
const roleLabel = (r) => /ADMIN|完全/i.test(r || '') ? t('bm.roleFull') : (/EMPLOYEE|普通/i.test(r || '') ? t('bm.roleEmployee') : (r || '—'))
const copyId = (id) => { navigator.clipboard?.writeText(id)?.catch(() => {}); ElMessage.success(t('dashboard.copiedVal', { val: id })) }

// ── 成员管理（owner+令牌创建者，批SS）：邀请（邮箱+角色，ADMIN 二次确认）/ 移除 ──
const canManage = () => isSuperSync || isOwner
const inviteForm = ref({ email: '', role: 'EMPLOYEE' })
const inviting = ref(false)
const doInvite = async () => {
  const d = detail.value
  if (!d?.row || inviting.value) return
  if (!inviteForm.value.email.trim()) return ElMessage.warning(t('bm.needEmail'))
  if (inviteForm.value.role === 'ADMIN') {
    try { await ElMessageBox.confirm(t('bm.adminConfirm'), t('common.confirm'), { type: 'warning' }) }
    catch { return }
  }
  inviting.value = true
  try {
    await POST(`/fb/credentials/${d.row.via_cred_id}/bm/${d.row.id}/members`, { email: inviteForm.value.email.trim(), role: inviteForm.value.role })
    ElMessage.success(t('bm.invited'))
    inviteForm.value = { email: '', role: 'EMPLOYEE' }
    const m = await GET(`/fb/credentials/${d.row.via_cred_id}/bm/${d.row.id}/members`, 30000).catch(() => null)
    detail.value.members = m
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  inviting.value = false
}
const removing = ref('')
const doRemove = async (m) => {
  const d = detail.value
  if (!d?.row) return
  try {
    await ElMessageBox.confirm(t('bm.removeConfirm', { n: m.title || m.buid }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' })
  } catch { return }
  removing.value = m.buid
  try {
    await DELETE(`/fb/credentials/${d.row.via_cred_id}/bm/${d.row.id}/members/${m.buid}`)
    ElMessage.success(t('common.done'))
    const mm = await GET(`/fb/credentials/${d.row.via_cred_id}/bm/${d.row.id}/members`, 30000).catch(() => null)
    detail.value.members = mm
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  removing.value = ''
}
</script>

<template>
  <div class="bmov">
    <div v-if="tokenFilter" class="filter-chip">
      <span>{{ t('common.filterByToken', { name: tokenFilter.name }) }}</span>
      <button class="filter-x" @click="$emit('clear-filter')" :title="t('common.clearFilter')">✕</button>
    </div>
    <div class="list-bar">
      <button class="ctrl-btn" :disabled="loading" @click="load">{{ loading ? t('common.loading') : t('common.refresh') }}</button>
      <span class="bm-count">{{ t('bm.total', { n: filteredRows.length }) }}</span>
    </div>
    <div class="card" v-loading="loading">
      <div class="bm-row bm-head-row">
        <span class="bm-name">{{ t('bm.colBm') }}</span>
        <span class="bm-col">{{ t('bm.colVia') }}</span>
        <span class="bm-col">{{ t('bm.colRole') }}</span>
      </div>
      <div v-for="r in filteredRows" :key="r.id" class="bm-row link" @click="openDetail(r)">
        <span class="bm-name">
          <span class="bm-title">{{ r.name || r.id }}</span>
          <span class="bm-id mono" @click.stop="copyId(r.id)" :title="t('pg.copyId')">{{ r.id }}</span>
        </span>
        <span class="bm-col"><span class="bm-via">{{ (r.via_creds || []).join(' / ') }}</span></span>
        <span class="bm-col"><span :class="['bm-role', roleClass(r.role)]">{{ roleLabel(r.role) }}</span></span>
      </div>
      <div v-if="!filteredRows.length && !loading" class="bm-empty">{{ t('bm.none') }}</div>
    </div>

    <el-dialog v-model="detailOpen" :title="detail?.row?.name || ''" width="640px" append-to-body>
      <div v-loading="detailLoading" class="bm-detail">
        <div class="seg-bar" style="margin-bottom:10px">
          <button class="seg-btn" :class="{ on: detail.tab === 'members' }" @click="detail.tab = 'members'">{{ t('bm.tabMembers') }}</button>
          <button class="seg-btn" :class="{ on: detail.tab === 'assets' }" @click="detail.tab = 'assets'">{{ t('bm.tabAssets') }}</button>
        </div>
        <template v-if="detail.tab === 'members'">
          <div v-for="(m, i) in (Array.isArray(detail.members) ? detail.members : [])" :key="i" class="bm-member">
            <span class="bm-m-name">{{ m.title || m.buid }}</span>
            <span class="bm-m-role">{{ roleLabel(m.role) }}</span>
            <button v-if="canManage() && writeOk" class="lm-x" :disabled="removing === m.buid" @click="doRemove(m)" :title="t('common.delete')">✕</button>
          </div>
          <div v-if="canManage() && !writeOk" class="bm-write-blocked">
            {{ t('bm.writeBlocked') }}
          </div>
          <div v-if="canManage() && writeOk" class="bm-invite">
            <input v-model="inviteForm.email" class="bm-inv-email" :placeholder="t('bm.emailPh')" @keyup.enter="doInvite" />
            <select v-model="inviteForm.role" class="bm-inv-role">
              <option value="EMPLOYEE">{{ t('bm.roleEmployee') }}</option>
              <option value="ADMIN">{{ t('bm.roleFull') }}</option>
            </select>
            <button class="ctrl-btn sm primary" :disabled="inviting" @click="doInvite">{{ inviting ? t('common.loading') : t('bm.invite') }}</button>
          </div>
          <div v-if="!(Array.isArray(detail.members) ? detail.members : []).length && !detailLoading" class="bm-empty">{{ t('bm.noMembers') }}</div>
        </template>
        <template v-else>
          <div class="bm-asset-sum">
            <span>{{ t('bm.accCount', { n: (detail.assets?.accounts || []).length }) }}</span>
            <span>{{ t('bm.pgCount', { n: (detail.assets?.pages || []).length }) }}</span>
          </div>
          <div v-for="(a, i) in (detail.assets?.accounts || [])" :key="'a' + i" class="bm-member">
            <span class="bm-m-name">{{ a.name || a.act_id }}</span>
            <span class="bm-m-role mono">{{ a.act_id }}</span>
          </div>
          <div v-if="detail.assets?.pages?.length" class="bm-sub-t">{{ t('bm.colPage') }}</div>
          <div v-for="(pg, i) in (detail.assets?.pages || [])" :key="'p' + i" class="bm-member">
            <span class="bm-m-name">{{ pg.name || pg.id }}</span>
          </div>
          <div v-if="!(detail.assets?.accounts || []).length && !(detail.assets?.pages || []).length && !detailLoading" class="bm-empty">{{ t('bm.noAssets') }}</div>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.bmov { display: flex; flex-direction: column; gap: 12px; }
.card { background: var(--bg2); border: 1px solid var(--bd); border-radius: 10px; padding: 6px 14px; overflow-x: auto; }
.bm-row { display: flex; gap: 12px; align-items: center; padding: 10px 4px; border-bottom: 1px solid var(--bd); font-size: 13px; min-width: 620px; }
.bm-row:last-child { border-bottom: none; }
.bm-head-row { color: var(--t3); font-size: 11px; text-transform: uppercase; }
.bm-row.link { cursor: pointer; }
.bm-row.link:hover { background: var(--bg3); }
.bm-name { flex: 1; min-width: 200px; display: flex; flex-direction: column; gap: 1px; }
.bm-title { font-weight: 600; color: var(--t1); }
.bm-id { font-size: 10px; color: var(--t3); cursor: pointer; }
.bm-col { width: 220px; flex: none; }
.bm-via { font-size: 11px; background: var(--bg3); padding: 1px 8px; border-radius: 4px; color: var(--t3); }
.bm-role { font-size: 11px; padding: 1px 8px; border-radius: 9px; }
.bm-role.full { background: rgba(48,209,88,.13); color: var(--success); }
.bm-role.basic { background: var(--bg3); color: var(--t3); }
.bm-count { font-size: 12px; color: var(--t3); }
.bm-empty { text-align: center; color: var(--t3); font-size: 13px; padding: 30px; }
.filter-chip { display: inline-flex; align-items: center; gap: 8px; padding: 4px 10px; background: var(--acg); color: var(--ac); border: 1px solid rgba(10,132,255,.35); border-radius: 999px; font-size: 12px; width: fit-content; }
.filter-x { border: none; background: transparent; color: var(--ac); cursor: pointer; font-size: 12px; line-height: 1; padding: 0 2px; }
.filter-x:hover { color: var(--error); }
.bm-detail { min-height: 120px; max-height: 60vh; overflow-y: auto; }
.bm-member { display: flex; justify-content: space-between; gap: 10px; padding: 6px 2px; border-bottom: 1px solid var(--bd); font-size: 13px; }
.bm-member:last-child { border-bottom: none; }
.bm-m-name { color: var(--t1); }
.bm-m-role { color: var(--t3); font-size: 11px; }
.bm-asset-sum { display: flex; gap: 16px; font-size: 12px; color: var(--t2); margin-bottom: 8px; }
.bm-write-blocked { padding: 10px; margin-top: 8px; background: rgba(255,159,10,.08); border: 1px dashed rgba(255,159,10,.4); border-radius: 8px; font-size: 12px; color: var(--warning); line-height: 1.6; }
.bm-invite { display: flex; gap: 8px; margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--bd); }
.bm-inv-email { flex: 1; background: var(--bg3); color: var(--t1); border: 1px solid var(--bd); border-radius: 6px; padding: 5px 10px; font-size: 12px; font-family: var(--font); }
.bm-inv-email:focus { outline: none; border-color: var(--ac); }
.bm-inv-role { background: var(--bg3); color: var(--t1); border: 1px solid var(--bd); border-radius: 6px; padding: 5px 6px; font-size: 12px; }
.lm-x { border: none; background: none; color: var(--t3); cursor: pointer; font-size: 12px; padding: 0 3px; }
.lm-x:hover { color: var(--error); }
.bm-sub-t { font-size: 11px; color: var(--t3); margin: 10px 0 2px; text-transform: uppercase; }
.ctrl-btn { height: 32px; padding: 0 12px; line-height: 30px; font-size: 13px; background: var(--bg2); color: var(--t2); border: 1px solid var(--bd); border-radius: var(--rs); cursor: pointer; box-sizing: border-box; white-space: nowrap; transition: all .15s; }
.ctrl-btn:hover { color: var(--t1); border-color: var(--bd2); }
.ctrl-btn.primary { background: var(--ac); color: #fff; border-color: var(--ac); }
.ctrl-btn.primary:hover { filter: brightness(1.08); }
.ctrl-btn.primary:disabled { opacity: .5; cursor: wait; }
.ctrl-btn.sm { padding: 0 8px; font-size: 12px; }
.ctrl-btn:disabled { opacity: .5; cursor: not-allowed; }
</style>
