<script setup>
import { ref, computed, onMounted } from 'vue'
import { GET, POST, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

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
  } catch (e) { ElMessage.error(e.message || '加载失败') }
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
  if (!roleForm.value.name.trim()) return ElMessage.warning('填角色名')
  try {
    if (editingRole.value) {
      await PUT(`/rbac/roles/${editingRole.value.id}`, roleForm.value)
      ElMessage.success('角色已更新')
    } else {
      await POST('/rbac/roles', roleForm.value)
      ElMessage.success('角色已创建')
    }
    roleOpen.value = false
    await load()
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
}
const removeRole = async (r) => {
  if (r.is_system) return ElMessage.warning('系统角色不可删除')
  if (r.member_count > 0) return ElMessage.warning('该角色下有成员，请先转移')
  try {
    await ElMessageBox.confirm(`删除角色「${roleLabel(r.name)}」？`, '确认', { type: 'warning' })
    await DELETE(`/rbac/roles/${r.id}`)
    ElMessage.success('已删除')
    await load()
  } catch {}
}

// 成员管理
const openInvite = () => { inviteForm.value = { email: '', password: '', role: 'operator' }; inviteOpen.value = true }
const submitInvite = async () => {
  if (!inviteForm.value.email.trim()) return ElMessage.warning('填邮箱')
  try {
    const r = await POST('/rbac/members/invite', inviteForm.value)
    ElMessage.success(r.default_password ? `已邀请，默认密码：${r.default_password}` : '已邀请')
    inviteOpen.value = false
    await load()
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
}
const changeRole = async (m, roleName) => {
  try {
    await PUT(`/rbac/members/${m.membership_id}/role`, { role: roleName })
    ElMessage.success('角色已更新')
    await load()
  } catch (e) { ElMessage.error('失败：' + (e.message || '')) }
}
const removeMember = async (m) => {
  try {
    await ElMessageBox.confirm(`移除成员「${m.email}」？`, '确认', { type: 'warning' })
    await DELETE(`/rbac/members/${m.membership_id}`)
    ElMessage.success('已移除')
    await load()
  } catch {}
}

const ROLE_ZH = { owner: '管理员', operator: '操作员', finance: '财务' }
const roleLabel = (name) => ROLE_ZH[name] || name
const permLabel = (key) => {
  const map = { 'ads.read':'看广告','ads.create':'建广告','ads.pause':'停广告','ads.resume':'开广告','ads.update':'改广告','ads.delete':'删广告','rules.read':'看规则','rules.create':'建规则','rules.edit':'改规则','landing.manage':'落地页','assets.manage':'素材库','billing.view':'看账单','billing.manage':'管账单','members.invite':'邀成员','members.manage':'管成员','audit.read':'审计' }
  return map[key] || key
}
</script>

<template>
  <div class="page">
    <div class="tabs">
      <div :class="['tab', { on: tab === 'members' }]" @click="tab = 'members'">团队成员</div>
      <div :class="['tab', { on: tab === 'roles' }]" @click="tab = 'roles'">角色权限</div>
    </div>

    <!-- 成员 -->
    <div v-if="tab === 'members'">
      <div class="bar">
        <span class="bar-l">{{ members.length }} 个成员</span>
        <button class="btn primary" @click="openInvite">+ 邀请成员</button>
      </div>
      <div class="tbl" v-loading="loading">
        <div class="row head"><div>成员</div><div>角色</div><div>状态</div><div></div></div>
        <div v-for="m in members" :key="m.membership_id" class="row">
          <div class="nm">{{ m.email }}<span v-if="m.is_you" class="you-tag">你</span></div>
          <div>
            <select class="role-sel" :value="m.role" :disabled="m.is_you && m.role === 'owner'"
                    @change="e => changeRole(m, e.target.value)">
              <option v-for="r in roles" :key="r.id" :value="r.name">{{ roleLabel(r.name) }}（{{ r.permissions.length }}权限）</option>
            </select>
          </div>
          <div><span class="st" :class="m.status === 'active' ? 'ok' : 'warn'">{{ m.status === 'active' ? '正常' : m.status }}</span></div>
          <div class="ops">
            <button v-if="!m.is_you" class="mb danger" @click="removeMember(m)">移除</button>
            <span v-else class="muted">—</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 角色 -->
    <div v-if="tab === 'roles'">
      <div class="bar">
        <span class="bar-l">{{ roles.length }} 个角色</span>
        <button class="btn primary" @click="openCreateRole">+ 新建角色</button>
      </div>
      <div class="role-list" v-loading="loading">
        <div v-for="r in roles" :key="r.id" class="role-card">
          <div class="role-head">
            <span class="role-name">{{ roleLabel(r.name) }}</span>
            <span v-if="r.is_system" class="sys-tag">系统</span>
            <span class="cnt-tag">{{ r.permissions.length }} 个权限</span>
            <span class="mem-tag">{{ r.member_count }} 人</span>
            <div class="role-ops">
              <button class="mb" @click="openEditRole(r)">编辑权限</button>
              <button v-if="!r.is_system" class="mb danger" @click="removeRole(r)">删除</button>
            </div>
          </div>
          <div class="perm-chips">
            <span v-for="p in r.permissions" :key="p" class="perm-chip">{{ permLabel(p) }}</span>
            <span v-if="!r.permissions.length" class="muted">无权限</span>
          </div>
          <div v-if="r.description" class="role-desc">{{ r.description }}</div>
        </div>
      </div>
    </div>

    <!-- 角色编辑弹窗 -->
    <div v-if="roleOpen" class="overlay" @click.self="roleOpen=false">
      <div class="modal role-modal">
        <div class="m-title">{{ editingRole ? '编辑角色' : '新建角色' }}</div>
        <div class="form-l"><label>角色名</label><input v-model="roleForm.name" class="input" :disabled="editingRole?.is_system" placeholder="如：落地页专员" /></div>
        <div class="form-l"><label>描述</label><input v-model="roleForm.description" class="input" placeholder="角色说明（可选）" /></div>
        <div class="perm-section">
          <div class="perm-title">权限矩阵（勾选该角色可以使用的模块）</div>
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
          <span class="perm-total">已选 {{ roleForm.permissions.length }} 个权限</span>
          <button class="btn" @click="roleOpen=false">取消</button>
          <button class="btn primary" @click="saveRole">{{ editingRole ? '保存' : '创建' }}</button>
        </div>
      </div>
    </div>

    <!-- 邀请弹窗 -->
    <div v-if="inviteOpen" class="overlay" @click.self="inviteOpen=false">
      <div class="modal">
        <div class="m-title">邀请成员</div>
        <div class="form-l"><label>邮箱</label><input v-model="inviteForm.email" class="input" placeholder="新成员邮箱" /></div>
        <div class="form-l"><label>密码</label><input v-model="inviteForm.password" class="input" type="password" placeholder="留空=默认 Welcome123!" /></div>
        <div class="form-l"><label>角色</label>
          <select v-model="inviteForm.role" class="input">
            <option v-for="r in roles" :key="r.id" :value="r.name">{{ r.name }}（{{ r.permissions.length }}权限）</option>
          </select>
        </div>
        <div class="m-foot"><button class="btn" @click="inviteOpen=false">取消</button><button class="btn primary" @click="submitInvite">邀请</button></div>
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
