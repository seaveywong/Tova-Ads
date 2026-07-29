<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { tenantStatus } from '../composables/useStatus'
const { t } = useI18n()
const memberStatus = (s) => tenantStatus(s)

const tab = ref('members')
const roles = ref([])
const members = ref([])
const permGroups = ref([])
const loading = ref(false)

// 角色编辑
const roleOpen = ref(false)
const editingRole = ref(null)
const roleForm = ref({ name: '', description: '', permissions: [] })

// 邀请
const inviteOpen = ref(false)
const inviteForm = ref({ email: '', password: '', role: 'operator' })

const load = async () => {
  loading.value = true
  try {
    const [r, m, p] = await Promise.all([
      GET('/rbac/roles'),
      GET('/rbac/members'),
      GET('/rbac/permission-groups'),
    ])
    roles.value = r
    members.value = m
    permGroups.value = p.groups || []
  } catch (e) { ElMessage.error(e.message || t('members.loadFail')) }
  loading.value = false
}
onMounted(load)

// 权限勾选
const togglePerm = (key) => {
  const idx = roleForm.value.permissions.indexOf(key)
  if (idx >= 0) roleForm.value.permissions.splice(idx, 1)
  else roleForm.value.permissions.push(key)
}
const hasPerm = (key) => roleForm.value.permissions.includes(key)
const groupCheckedCount = (group) => group.keys.filter(k => roleForm.value.permissions.includes(k)).length

// 角色 CRUD
const openCreateRole = () => {
  editingRole.value = null
  roleForm.value = { name: '', description: '', permissions: [] }
  roleOpen.value = true
}
const openEditRole = (r) => {
  editingRole.value = r
  roleForm.value = { name: r.name, description: r.description, permissions: [...r.permissions] }
  roleOpen.value = true
}
const saveRole = async () => {
  if (!roleForm.value.name.trim()) return ElMessage.warning(t('members.roleNameRequired'))
  try {
    if (editingRole.value) {
      await PUT(`/rbac/roles/${editingRole.value.id}`, roleForm.value)
      ElMessage.success(t('members.roleUpdated'))
    } else {
      await POST('/rbac/roles', roleForm.value)
      ElMessage.success(t('members.roleCreated'))
    }
    roleOpen.value = false
    await load()
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
}
const removeRole = async (r) => {
  if (r.is_system) return ElMessage.warning(t('members.systemRoleNoDelete'))
  if (r.member_count > 0) return ElMessage.warning(t('members.roleHasMembers'))
  try {
    await ElMessageBox.confirm(t('members.delRoleConfirm', { name: roleLabel(r.name) }), t('common.confirm'), { type: 'warning' })
    await DELETE(`/rbac/roles/${r.id}`)
    ElMessage.success(t('common.delete') + t('members.doneSuffix'))
    await load()
  } catch {}
}

// 成员管理
const inviteSaving = ref(false)
const openInvite = () => { inviteForm.value = { email: '', password: '', role: 'operator' }; inviteOpen.value = true }
const submitInvite = async () => {
  if (!inviteForm.value.email.trim()) return ElMessage.warning(t('members.emailRequired'))
  inviteSaving.value = true
  try {
    const r = await POST('/rbac/members/invite', inviteForm.value)
    inviteOpen.value = false
    await load()
    await ElMessageBox.alert(
      r.default_password ? t('members.invitedWithPwd', { pwd: r.default_password }) : t('members.invited'),
      t('members.inviteSuccess'), { confirmButtonText: t('common.ok'), type: 'success' })
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
  inviteSaving.value = false
}
const changeRole = async (m, roleName) => {
  if (roleName === m.role) return
  const fromOwner = m.role === 'owner'
  try {
    const msg = fromOwner
      ? t('members.changeRoleFromOwner', { email: m.email, role: roleLabel(roleName) })
      : t('members.changeRole', { email: m.email, role: roleLabel(roleName) })
    await ElMessageBox.confirm(msg, t('members.roleChange'), { type: fromOwner ? 'warning' : 'info', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
  } catch { return }  // 取消则 select 自动回弹到 m.role（受控）
  try {
    await PUT(`/rbac/members/${m.membership_id}/role`, { role: roleName })
    ElMessage.success(t('members.roleUpdated'))
    await load()
  } catch (e) { ElMessage.error(t('common.fail') + '：' + (e.message || '')) }
}
const removeMember = async (m) => {
  try {
    await ElMessageBox.confirm(t('members.removeMemberConfirm', { email: m.email }), t('common.confirm'), { type: 'warning' })
    await DELETE(`/rbac/members/${m.membership_id}`)
    ElMessage.success(t('members.removed'))
    await load()
  } catch {}
}

const ROLE_KEY = { owner: 'role.owner', operator: 'role.operator', finance: 'role.finance', superadmin: 'role.superadmin', super: 'role.super' }
const roleLabel = (name) => ROLE_KEY[name] ? t(ROLE_KEY[name]) : name
const permLabel = (key) => {
  const map = { 'ads.read':'members.perm.adsRead','ads.create':'members.perm.adsCreate','ads.pause':'members.perm.adsPause','ads.resume':'members.perm.adsResume','ads.update':'members.perm.adsUpdate','ads.delete':'members.perm.adsDelete','rules.read':'members.perm.rulesRead','rules.create':'members.perm.rulesCreate','rules.edit':'members.perm.rulesEdit','landing.manage':'members.perm.landingManage','assets.manage':'members.perm.assetsManage','billing.view':'members.perm.billingView','billing.manage':'members.perm.billingManage','members.invite':'members.perm.membersInvite','members.manage':'members.perm.membersManage','audit.read':'members.perm.auditRead' }
  return map[key] ? t(map[key]) : key
}
</script>

<template>
  <div class="page">
    <div class="tabs">
      <div :class="['tab', { on: tab === 'members' }]" @click="tab = 'members'">{{ t('members.tabMembers') }}</div>
      <div :class="['tab', { on: tab === 'roles' }]" @click="tab = 'roles'">{{ t('members.tabRoles') }}</div>
    </div>

    <!-- 成员 -->
    <div v-if="tab === 'members'">
      <div class="bar">
        <span class="bar-l">{{ t('members.memberCount', { n: members.length }) }}</span>
        <button class="btn primary" @click="openInvite">+ {{ t('members.inviteMember') }}</button>
      </div>
      <div class="tbl" v-loading="loading">
        <div class="row head"><div>{{ t('members.colMember') }}</div><div>{{ t('members.colRole') }}</div><div>{{ t('common.status') }}</div><div></div></div>
        <div v-for="m in members" :key="m.membership_id" class="row">
          <div class="nm">{{ m.email }}<span v-if="m.is_you" class="you-tag">{{ t('members.you') }}</span></div>
          <div>
            <select class="role-sel" :value="m.role" :disabled="m.is_you && m.role === 'owner'"
                    @change="e => changeRole(m, e.target.value)">
              <option v-for="r in roles" :key="r.id" :value="r.name">{{ roleLabel(r.name) }}（{{ t('members.permCount', { n: r.permissions.length }) }}）</option>
            </select>
          </div>
          <div><span class="st" :class="memberStatus(m.status).cls">{{ memberStatus(m.status).label }}</span></div>
          <div class="ops">
            <button v-if="!m.is_you" class="mb danger" @click="removeMember(m)">{{ t('common.remove') }}</button>
            <span v-else class="muted">—</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 角色 -->
    <div v-if="tab === 'roles'">
      <div class="bar">
        <span class="bar-l">{{ t('members.roleCount', { n: roles.length }) }}</span>
        <button class="btn primary" @click="openCreateRole">+ {{ t('members.createRole') }}</button>
      </div>
      <div class="role-list" v-loading="loading">
        <div v-for="r in roles" :key="r.id" class="role-card">
          <div class="role-head">
            <span class="role-name">{{ roleLabel(r.name) }}</span>
            <span v-if="r.is_system" class="sys-tag">{{ t('members.systemTag') }}</span>
            <span class="cnt-tag">{{ t('members.permCountLabel', { n: r.permissions.length }) }}</span>
            <span class="mem-tag">{{ t('members.memberCountLabel', { n: r.member_count }) }}</span>
            <div class="role-ops">
              <button class="mb" @click="openEditRole(r)">{{ t('members.editPerms') }}</button>
              <button v-if="!r.is_system" class="mb danger" @click="removeRole(r)">{{ t('common.delete') }}</button>
            </div>
          </div>
          <div class="perm-chips">
            <span v-for="p in r.permissions" :key="p" class="perm-chip">{{ permLabel(p) }}</span>
            <span v-if="!r.permissions.length" class="muted">{{ t('members.noPerms') }}</span>
          </div>
          <div v-if="r.description" class="role-desc">{{ r.description }}</div>
        </div>
      </div>
    </div>

    <!-- 角色编辑弹窗 -->
    <div v-if="roleOpen" class="overlay" @click.self="roleOpen=false">
      <div class="modal role-modal">
        <div class="m-title">{{ editingRole ? t('members.editRole') : t('members.createRole') }}</div>
        <div class="form-l"><label>{{ t('members.roleName') }}</label><input v-model="roleForm.name" class="input" :disabled="editingRole?.is_system" :placeholder="t('members.roleNamePlaceholder')" /></div>
        <div class="form-l"><label>{{ t('members.description') }}</label><input v-model="roleForm.description" class="input" :placeholder="t('members.descriptionPlaceholder')" /></div>
        <div class="perm-section">
          <div class="perm-title">{{ t('members.permMatrixTitle') }}</div>
          <div v-for="g in permGroups" :key="g.label" class="perm-group">
            <div class="pg-head" @click="() => { const all = g.keys.every(k => hasPerm(k)); g.keys.forEach(k => { if (all) togglePerm(k); else if (!hasPerm(k)) togglePerm(k) }) }">
              <span class="pg-name">{{ g.label }}</span>
              <span class="pg-count">{{ groupCheckedCount(g) }}/{{ g.keys.length }}</span>
            </div>
            <div class="pg-items">
              <label v-for="k in g.keys" :key="k" class="pg-item" :class="{ on: hasPerm(k) }">
                <input type="checkbox" :checked="hasPerm(k)" @change="togglePerm(k)" />
                <span>{{ permLabel(k) }}</span>
                <code class="pk">{{ k }}</code>
              </label>
            </div>
          </div>
        </div>
        <div class="m-foot">
          <span class="perm-total">{{ t('members.selectedPerms', { n: roleForm.permissions.length }) }}</span>
          <button class="btn" @click="roleOpen=false">{{ t('common.cancel') }}</button>
          <button class="btn primary" @click="saveRole">{{ editingRole ? t('common.save') : t('common.create') }}</button>
        </div>
      </div>
    </div>

    <!-- 邀请弹窗 -->
    <div v-if="inviteOpen" class="overlay" @click.self="inviteOpen=false">
      <div class="modal">
        <div class="m-title">{{ t('members.inviteMember') }}</div>
        <div class="form-l"><label>{{ t('members.email') }}</label><input v-model="inviteForm.email" class="input" :placeholder="t('members.emailPlaceholder')" /></div>
        <div class="form-l"><label>{{ t('members.password') }}</label><input v-model="inviteForm.password" class="input" type="password" autocomplete="new-password" :placeholder="t('members.passwordPlaceholder')" /></div>
        <div class="form-l"><label>{{ t('members.colRole') }}</label>
          <select v-model="inviteForm.role" class="input">
            <option v-for="r in roles" :key="r.id" :value="r.name">{{ r.name }}（{{ t('members.permCount', { n: r.permissions.length }) }}）</option>
          </select>
        </div>
        <div class="m-foot"><button class="btn" @click="inviteOpen=false">{{ t('common.cancel') }}</button><button class="btn primary" :disabled="inviteSaving" @click="submitInvite">{{ inviteSaving ? t('members.inviting') : t('members.invite') }}</button></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { width: 100% }
.tabs { display: flex; gap: 2px; margin-bottom: 16px; border-bottom: 1px solid var(--bd); padding-left: 4px }
.tab { padding: 7px 16px; font-size: 14px; color: var(--t3); cursor: pointer; border-bottom: 2px solid transparent }
.tab.on { color: var(--t1); border-bottom-color: var(--ac); font-weight: 600 }
.bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; gap: 8px }
.bar-l { font-size: 13px; color: var(--t3) }
.btn { padding: 7px 16px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t1); border-radius: 6px; font-size: 13px; cursor: pointer; white-space: nowrap }
.btn:hover { background: var(--bg3) }
.btn.primary { background: var(--ac); color: #fff; border-color: var(--ac) }

.tbl { border: 1px solid var(--bd); border-radius: 8px; overflow-x: auto }
.row { display: grid; grid-template-columns: 1fr 200px 100px 80px; gap: 8px; padding: 9px 16px; align-items: center; font-size: 13px; border-bottom: 1px solid var(--bd) }
.row.head { background: var(--bg2); color: var(--t3); font-size: 11px; font-weight: 600 }
.row:last-child { border-bottom: none }
.nm { color: var(--t1); font-weight: 500 }
.you-tag { font-size: 10px; padding: 1px 6px; background: var(--acg); color: var(--ac); border-radius: 4px; margin-left: 6px }
.role-sel { padding: 5px 8px; background: var(--bg3); border: 1px solid var(--bd); border-radius: 5px; color: var(--t1); font-size: 12px; width: 100%; box-sizing: border-box }
.st { font-size: 11px; padding: 2px 8px; border-radius: 4px }
.st.ok { background: rgba(48,209,97,.12); color: var(--success) }
.st.warn { background: rgba(255,159,10,.12); color: var(--warning) }
.ops { text-align: right }
.mb { padding: 3px 10px; border: 1px solid var(--bd); background: transparent; color: var(--t2); border-radius: 4px; font-size: 11px; cursor: pointer }
.mb:hover { color: var(--ac); border-color: var(--ac) }
.mb.danger:hover { color: var(--error); border-color: var(--error) }
.muted { color: var(--t3) }

.role-list { display: flex; flex-direction: column; gap: 10px }
.role-card { background: var(--bg2); border: 1px solid var(--bd); border-radius: 8px; padding: 14px 16px }
.role-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap }
.role-name { font-size: 15px; font-weight: 600; color: var(--t1) }
.sys-tag { font-size: 10px; padding: 1px 7px; border-radius: 9px; background: var(--bg3); color: var(--t3) }
.cnt-tag, .mem-tag { font-size: 11px; padding: 1px 7px; border-radius: 9px }
.cnt-tag { background: rgba(10,132,255,.12); color: var(--ac) }
.mem-tag { background: rgba(48,209,97,.1); color: var(--success) }
.role-ops { margin-left: auto; display: flex; gap: 6px }
.perm-chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px }
.perm-chip { font-size: 10px; padding: 2px 7px; border-radius: 4px; background: var(--bg3); color: var(--t2) }
.role-desc { font-size: 12px; color: var(--t3); margin-top: 6px }

.overlay { position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 2500; display: flex; align-items: center; justify-content: center }
.modal { background: var(--bg2); border-radius: 12px; padding: 20px; width: 560px; max-width: 92vw; max-height: 88vh; overflow-y: auto; box-shadow: var(--shadow-dropdown) }
.role-modal { width: 640px }
.m-title { font-size: 16px; font-weight: 600; color: var(--t1); margin-bottom: 14px }
.form-l { display: flex; align-items: center; gap: 8px; margin-bottom: 10px }
.form-l > label { font-size: 12px; color: var(--t3); width: 60px; text-align: right; flex-shrink: 0 }
.input { flex: 1; padding: 7px 10px; background: var(--bg3); border: 1px solid var(--bd); border-radius: 6px; color: var(--t1); font-size: 13px; box-sizing: border-box }
.input:focus { border-color: var(--ac); outline: none }

.perm-section { margin-top: 14px; border-top: 1px solid var(--bd); padding-top: 12px }
.perm-title { font-size: 13px; font-weight: 600; color: var(--t2); margin-bottom: 10px }
.perm-group { margin-bottom: 12px }
.pg-head { display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; background: var(--bg3); border-radius: 6px; cursor: pointer; margin-bottom: 6px }
.pg-head:hover { background: var(--bgh) }
.pg-name { font-size: 12px; font-weight: 600; color: var(--t1) }
.pg-count { font-size: 11px; color: var(--t3) }
.pg-items { display: flex; flex-wrap: wrap; gap: 6px; padding-left: 4px }
.pg-item { display: flex; align-items: center; gap: 4px; padding: 4px 8px; border: 1px solid var(--bd); border-radius: 5px; font-size: 11px; color: var(--t3); cursor: pointer; transition: .12s }
.pg-item.on { color: var(--ac); border-color: var(--ac); background: rgba(10,132,255,.06) }
.pg-item input { margin: 0; accent-color: var(--ac) }
.pk { font-size: 9px; color: var(--t3); opacity: .5 }

.m-foot { display: flex; justify-content: flex-end; align-items: center; gap: 8px; margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--bd) }
.perm-total { margin-right: auto; font-size: 12px; color: var(--t3) }
</style>
