<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { GET, POST, PUT, PATCH, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { tenantStatus } from '../composables/useStatus'

const { t } = useI18n()

const ROLE_KEY = { owner: 'role.owner', operator: 'role.operator', finance: 'role.finance' }
const statusLabel = (s) => tenantStatus(s).label

const teams = ref([])
const loading = ref(false)
const load = async () => {
  loading.value = true
  try { teams.value = await GET('/admin/tenants/detail') }
  catch (e) { ElMessage.error(e.message || t('teams.loadFail')) }
  loading.value = false
}
onMounted(load)

// 建团队
const createOpen = ref(false)
const createForm = ref({ name: '', owner_email: '', owner_password: '' })
const createSaving = ref(false)
const openCreate = () => { createForm.value = { name: '', owner_email: '', owner_password: '' }; createOpen.value = true }
const submitCreate = async () => {
  if (!createForm.value.name.trim()) return ElMessage.warning(t('teams.nameRequired'))
  if (createForm.value.owner_email.trim() && !createForm.value.owner_email.includes('@')) return ElMessage.warning(t('teams.ownerEmailInvalid'))
  createSaving.value = true
  try {
    const r = await POST('/admin/tenants', {
      name: createForm.value.name.trim(),
      owner_email: createForm.value.owner_email.trim(),
      owner_password: createForm.value.owner_password.trim(),
    })
    let msg = t('teams.createdTeam', { name: r.name })
    if (r.owner_email && r.owner_existing) msg += t('teams.ownerExisting', { email: r.owner_email })
    else if (r.owner_email) msg += t('teams.ownerNew', { email: r.owner_email, password: r.owner_password })
    else msg += t('teams.emptyTeam')
    createOpen.value = false
    load()
    await ElMessageBox.alert(msg, t('teams.createdTitle'), { confirmButtonText: t('common.ok'), type: 'success' })
  } catch (e) { ElMessage.error(e.message || t('teams.createFail')) }
  createSaving.value = false
}

// 改名
const rename = async (row) => {
  try {
    const { value } = await ElMessageBox.prompt(t('teams.newName'), t('teams.renameTitle', { name: row.name }), {
      inputValue: row.name, confirmButtonText: t('common.save'), cancelButtonText: t('common.cancel'),
      inputValidator: (v) => (v && v.trim()) ? true : t('teams.cannotEmpty'),
    })
    await PUT(`/admin/tenants/${row.id}`, { name: value.trim() })
    ElMessage.success(t('teams.renamed'))
    load()
  } catch (e) { if (e !== 'cancel' && e?.message) ElMessage.error(e.message) }
}

// 状态变更
const setStatus = async (row, status) => {
  const word = statusLabel(status)
  try {
    await ElMessageBox.confirm(t('teams.confirmStatus', { name: row.name, status: word }), t('common.confirm'),
      { type: status === 'archived' ? 'warning' : 'info', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
    await PATCH(`/admin/tenants/${row.id}/status`, { status })
    ElMessage.success(t('teams.statusUpdated'))
    load()
  } catch (e) { if (e !== 'cancel' && e?.message) ElMessage.error(e.message) }
}
const handleOp = (cmd, row) => {
  const map = { suspend: 'suspended', activate: 'active', archive: 'archived', restore: 'active' }
  setStatus(row, map[cmd])
}
const hasMore = (row) => {
  if (row.id === 1) return false
  if (row.status === 'active') return true
  if (row.status === 'suspended') return true
  if (row.status === 'archived') return true
  return false
}

// 成员管理（列表/改角色/移除/加成员，超管跨租户）
const memberOpen = ref(false)
const membersTid = ref(0)
const membersName = ref('')
const memberList = ref([])
const memberLoading = ref(false)
const memberAdd = ref({ email: '', role: 'operator', password: '' })
const memberAddSaving = ref(false)
const openMembers = async (row) => {
  membersTid.value = row.id
  membersName.value = row.name
  memberAdd.value = { email: '', role: 'operator', password: '' }
  memberOpen.value = true
  await loadMembers()
}
const loadMembers = async () => {
  memberLoading.value = true
  try { memberList.value = await GET(`/admin/tenants/${membersTid.value}/members`) }
  catch (e) { ElMessage.error(e.message || t('teams.loadMembersFail')) }
  memberLoading.value = false
}
const changeMemberRole = async (m, role) => {
  if (role === m.role) return
  try {
    await PUT(`/admin/tenants/${membersTid.value}/members/${m.membership_id}/role`, { role })
    ElMessage.success(t('teams.roleChanged', { email: m.email, role: t(ROLE_KEY[role] || role) }))
    m.role = role
  } catch (e) { ElMessage.error(e.message || t('teams.changeRoleFail')); await loadMembers() }
}
const removeMemberRow = async (m) => {
  try {
    await ElMessageBox.confirm(t('teams.removeMemberConfirm', { email: m.email }), t('common.confirm'), { type: 'warning', confirmButtonText: t('common.remove'), cancelButtonText: t('common.cancel'), confirmButtonClass: 'el-button--danger' })
    await DELETE(`/admin/tenants/${membersTid.value}/members/${m.membership_id}`)
    ElMessage.success(t('teams.memberRemoved', { email: m.email }))
    memberList.value = memberList.value.filter(x => x.membership_id !== m.membership_id)
    load()
  } catch (e) { if (e !== 'cancel' && e?.message) ElMessage.error(e.message) }
}
const submitMemberAdd = async () => {
  if (!memberAdd.value.email.trim()) return ElMessage.warning(t('teams.emailRequired'))
  if (!memberAdd.value.email.includes('@')) return ElMessage.warning(t('teams.emailInvalid'))
  memberAddSaving.value = true
  try {
    const r = await POST(`/admin/tenants/${membersTid.value}/members`, {
      email: memberAdd.value.email.trim(),
      role: memberAdd.value.role,
      password: memberAdd.value.password.trim(),
    })
    const addMsg = r.existing_user
      ? t('teams.addedExisting', { email: r.email })
      : t('teams.addedNew', { email: r.email, password: r.password })
    memberAdd.value = { email: '', role: 'operator', password: '' }
    await loadMembers()
    load()
    await ElMessageBox.alert(addMsg, t('teams.addSuccess'), { confirmButtonText: t('common.ok'), type: 'success' })
  } catch (e) { ElMessage.error(e.message || t('teams.addFail')) }
  memberAddSaving.value = false
}
</script>

<template>
  <div class="page">
    <div class="card">
      <div class="head">
        <div class="head-text">
          <div class="t">{{ t('teams.title') }}</div>
          <div class="d">{{ t('teams.desc') }}</div>
        </div>
        <button class="btn primary" @click="openCreate"><span class="plus">+</span> {{ t('teams.createTeam') }}</button>
      </div>

      <div class="tbl-wrap"><el-table :data="teams" v-loading="loading" style="width:100%" :empty-text="t('teams.noTeams')" row-key="id">
        <el-table-column prop="id" label="ID" width="56" align="center" />
        <el-table-column :label="t('teams.teamName')" min-width="180">
          <template #default="{ row }">
            <span class="name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.status')" width="96">
          <template #default="{ row }">
            <span :class="['status', row.status]"><i class="sdot"></i>{{ statusLabel(row.status) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('teams.members')" width="68" align="center">
          <template #default="{ row }">
            <span :class="['num', { zero: row.members === 0 }]">{{ row.members }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('teams.adAccounts')" width="88" align="center">
          <template #default="{ row }">
            <span :class="['num', { zero: row.accounts === 0 }]">{{ row.accounts }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('teams.createdAt')" width="160">
          <template #default="{ row }"><span class="mute">{{ (row.created_at || '').slice(0,16).replace('T',' ') }}</span></template>
        </el-table-column>
        <el-table-column :label="t('common.operation')" width="172" fixed="right">
          <template #default="{ row }">
            <div class="ops">
              <button class="op primary" @click="openMembers(row)">{{ t('teams.members') }}</button>
              <button class="op" @click="rename(row)">{{ t('teams.rename') }}</button>
              <el-dropdown v-if="hasMore(row)" trigger="click" @command="c => handleOp(c, row)">
                <button class="op more" :title="t('common.more')">⋯</button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="row.status === 'active'" command="suspend">{{ t('teams.suspend') }}</el-dropdown-item>
                    <el-dropdown-item v-if="row.status === 'suspended'" command="activate">{{ t('teams.activate') }}</el-dropdown-item>
                    <el-dropdown-item v-if="row.status !== 'archived'" command="archive" divided class="danger">{{ t('teams.archive') }}</el-dropdown-item>
                    <el-dropdown-item v-if="row.status === 'archived'" command="restore">{{ t('teams.restore') }}</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table></div>
    </div>

    <!-- 建团队弹窗 -->
    <el-dialog v-model="createOpen" :title="t('teams.createTeam')" width="460px">
      <div class="dlg-d">{{ t('teams.createDesc') }}</div>
      <div class="form-l"><label>{{ t('teams.teamName') }}</label><input v-model="createForm.name" class="input" :placeholder="t('teams.teamNamePlaceholder')" /></div>
      <div class="form-l"><label>{{ t('teams.ownerEmail') }}</label><input v-model="createForm.owner_email" class="input" :placeholder="t('teams.ownerEmailPlaceholder')" /></div>
      <div class="form-l"><label>{{ t('teams.ownerPassword') }}</label><input v-model="createForm.owner_password" class="input" type="password" autocomplete="new-password" :placeholder="t('teams.ownerPasswordPlaceholder')" /></div>
      <template #footer>
        <button class="btn" @click="createOpen = false">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="createSaving" @click="submitCreate">{{ createSaving ? t('teams.creating') : t('common.create') }}</button>
      </template>
    </el-dialog>

    <!-- 成员管理弹窗 -->
    <el-dialog v-model="memberOpen" :title="t('teams.memberManageTitle', { name: membersName })" width="560px">
      <div v-loading="memberLoading">
        <div class="mem-section-title">{{ t('teams.currentMembers', { n: memberList.length }) }}</div>
        <div class="mem-list">
          <div v-for="m in memberList" :key="m.membership_id" class="mem-row">
            <span class="mem-email">{{ m.email }}<span v-if="m.is_you" class="mem-you">{{ t('teams.you') }}</span></span>
            <select class="mem-role-sel" :value="m.role" :disabled="m.is_you && m.role === 'owner'"
                    @change="e => changeMemberRole(m, e.target.value)">
              <option v-for="(rk, k) in ROLE_KEY" :key="k" :value="k">{{ t(rk) }}</option>
            </select>
            <button v-if="!m.is_you" class="mem-rm" @click="removeMemberRow(m)">{{ t('common.remove') }}</button>
            <span v-else class="mem-self">—</span>
          </div>
          <div v-if="!memberList.length && !memberLoading" class="mem-empty">{{ t('teams.noMembers') }}</div>
        </div>

        <div class="mem-divider"></div>
        <div class="mem-section-title">{{ t('teams.addNewMember') }}</div>
        <div class="form-l"><label>{{ t('teams.email') }}</label><input v-model="memberAdd.email" class="input" :placeholder="t('teams.memberEmailPlaceholder')" /></div>
        <div class="form-l"><label>{{ t('teams.role') }}</label>
          <select v-model="memberAdd.role" class="input">
            <option v-for="(rk, k) in ROLE_KEY" :key="k" :value="k">{{ t(rk) }}</option>
          </select>
        </div>
        <div class="form-l"><label>{{ t('teams.password') }}</label><input v-model="memberAdd.password" class="input" type="password" autocomplete="new-password" :placeholder="t('teams.memberPasswordPlaceholder')" /></div>
        <button class="btn primary mem-add-btn" :disabled="memberAddSaving" @click="submitMemberAdd">{{ memberAddSaving ? t('teams.adding') : t('teams.addMember') }}</button>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.page{display:flex;flex-direction:column;gap:14px}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:12px;padding:20px}
.head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px;gap:16px}
.head-text{flex:1;min-width:0}
.t{font-size:16px;font-weight:600;color:var(--t1);margin-bottom:5px}
.d{font-size:12px;color:var(--t3);line-height:1.6}

.btn{padding:8px 16px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:7px;font-size:13px;cursor:pointer;transition:all .15s;font-family:inherit}
.btn:hover{border-color:var(--ac)}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn.primary:hover{filter:brightness(1.08)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.plus{font-weight:600;margin-right:2px}

.name{color:var(--t1);font-weight:500}
.status{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:500}
.status .sdot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.status.active{color:var(--success)}
.status.active .sdot{background:var(--success);box-shadow:0 0 0 3px rgba(52,199,89,.15)}
.status.suspended{color:var(--warning)}
.status.suspended .sdot{background:var(--warning);box-shadow:0 0 0 3px rgba(255,159,10,.15)}
.status.archived{color:var(--t3)}
.status.archived .sdot{background:var(--t3)}

.num{color:var(--t1);font-variant-numeric:tabular-nums;font-weight:500}
.num.zero{color:var(--t3);font-weight:400}
.mute{color:var(--t3);font-size:12px;font-variant-numeric:tabular-nums}

.ops{display:flex;align-items:center;gap:4px}
.op{background:transparent;border:1px solid transparent;color:var(--t2);font-size:12px;cursor:pointer;padding:5px 10px;border-radius:6px;transition:all .15s;font-family:inherit;white-space:nowrap}
.op:hover{background:var(--bg3);color:var(--t1)}
.op.primary{color:var(--ac);font-weight:500}
.op.primary:hover{background:var(--acg)}
.op.more{padding:5px 9px;font-size:15px;line-height:1;letter-spacing:-1px}
:deep(.danger){color:var(--error)}

.dlg-d{font-size:12px;color:var(--t3);line-height:1.6;margin-bottom:16px;padding:10px 12px;background:var(--bg3);border-radius:7px}
.form-l{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.form-l > label{font-size:12px;color:var(--t3);width:82px;text-align:right;flex-shrink:0}
.input{flex:1;padding:8px 11px;background:var(--bg3);border:1px solid var(--bd);border-radius:7px;color:var(--t1);font-size:13px;font-family:inherit;box-sizing:border-box;transition:border-color .15s}
.input:focus{border-color:var(--ac);outline:none}
.input::placeholder{color:var(--t3);opacity:.7}

/* 成员管理 */
.mem-section-title{font-size:13px;font-weight:600;color:var(--t1);margin-bottom:10px}
.mem-list{border:1px solid var(--bd);border-radius:8px;overflow:hidden}
.mem-row{display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid var(--bd);font-size:13px}
.mem-row:last-child{border-bottom:none}
.mem-email{flex:1;color:var(--t1);font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mem-you{font-size:10px;padding:1px 6px;background:var(--acg);color:var(--ac);border-radius:4px;margin-left:6px}
.mem-role-sel{padding:4px 8px;background:var(--bg3);border:1px solid var(--bd);border-radius:5px;color:var(--t1);font-size:12px;cursor:pointer;font-family:inherit}
.mem-rm{background:none;border:none;color:var(--error);font-size:12px;cursor:pointer;padding:2px 6px;white-space:nowrap}
.mem-rm:hover{text-decoration:underline}
.mem-self{color:var(--t3);font-size:12px;width:36px;text-align:center}
.mem-empty{padding:20px;text-align:center;color:var(--t3);font-size:13px}
.mem-divider{height:1px;background:var(--bd);margin:16px 0}
.mem-add-btn{margin-top:4px}

:deep(.el-table){font-size:13px}
:deep(.el-table th.el-table__cell){background:var(--bg3);color:var(--t2);font-weight:600;font-size:12px}
:deep(.el-table tr:hover > td){background:var(--bg3) !important}
.tbl-wrap{overflow-x:auto}
</style>
