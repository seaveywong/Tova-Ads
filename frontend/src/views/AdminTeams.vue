<script setup>
import { ref, onMounted } from 'vue'
import { GET, POST, PUT, PATCH } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const ROLE_ZH = { owner: '管理员', operator: '操作员', finance: '财务' }
const STATUS_ZH = { active: '正常', suspended: '已停用', archived: '已归档' }

const teams = ref([])
const loading = ref(false)
const load = async () => {
  loading.value = true
  try { teams.value = await GET('/admin/tenants/detail') }
  catch (e) { ElMessage.error(e.message || '加载失败') }
  loading.value = false
}
onMounted(load)

// 建团队
const createOpen = ref(false)
const createForm = ref({ name: '', owner_email: '', owner_password: '' })
const createSaving = ref(false)
const openCreate = () => { createForm.value = { name: '', owner_email: '', owner_password: '' }; createOpen.value = true }
const submitCreate = async () => {
  if (!createForm.value.name.trim()) return ElMessage.warning('填团队名')
  if (createForm.value.owner_email.trim() && !createForm.value.owner_email.includes('@')) return ElMessage.warning('管理员邮箱格式不对')
  createSaving.value = true
  try {
    const r = await POST('/admin/tenants', {
      name: createForm.value.name.trim(),
      owner_email: createForm.value.owner_email.trim(),
      owner_password: createForm.value.owner_password.trim(),
    })
    let msg = `团队「${r.name}」已创建`
    if (r.owner_email && r.owner_existing) msg += `，已指定现有用户 ${r.owner_email} 为管理员`
    else if (r.owner_email) msg += `，管理员 ${r.owner_email} 初始密码：${r.owner_password}（请告知对方首次登录后修改）`
    else msg += '（空团队，稍后可加成员）'
    ElMessage.success(msg)
    createOpen.value = false
    load()
  } catch (e) { ElMessage.error(e.message || '创建失败') }
  createSaving.value = false
}

// 改名
const rename = async (t) => {
  try {
    const { value } = await ElMessageBox.prompt('新团队名', `改名 · ${t.name}`, {
      inputValue: t.name, confirmButtonText: '保存', cancelButtonText: '取消',
      inputValidator: (v) => (v && v.trim()) ? true : '不能为空',
    })
    await PUT(`/admin/tenants/${t.id}`, { name: value.trim() })
    ElMessage.success('已改名')
    load()
  } catch (e) { if (e !== 'cancel' && e?.message) ElMessage.error(e.message) }
}

// 状态变更（归档/恢复/停用/激活）
const setStatus = async (t, status) => {
  const word = STATUS_ZH[status]
  try {
    await ElMessageBox.confirm(`确定将「${t.name}」设为${word}？`, '确认',
      { type: status === 'archived' ? 'warning' : 'info', confirmButtonText: '确认', cancelButtonText: '取消' })
    await PATCH(`/admin/tenants/${t.id}/status`, { status })
    ElMessage.success('已更新')
    load()
  } catch (e) { if (e !== 'cancel' && e?.message) ElMessage.error(e.message) }
}

// 加成员（超管跨团队加）
const memberOpen = ref(false)
const memberForm = ref({ tid: 0, name: '', email: '', role: 'operator', password: '' })
const memberSaving = ref(false)
const openMember = (t) => { memberForm.value = { tid: t.id, name: t.name, email: '', role: 'operator', password: '' }; memberOpen.value = true }
const submitMember = async () => {
  if (!memberForm.value.email.trim()) return ElMessage.warning('填邮箱')
  if (!memberForm.value.email.includes('@')) return ElMessage.warning('邮箱格式不对')
  memberSaving.value = true
  try {
    const r = await POST(`/admin/tenants/${memberForm.value.tid}/members`, {
      email: memberForm.value.email.trim(),
      role: memberForm.value.role,
      password: memberForm.value.password.trim(),
    })
    ElMessage.success(r.existing_user
      ? `已把现有用户 ${r.email} 加入团队（角色：${ROLE_ZH[r.role] || r.role}）`
      : `已创建 ${r.email}，初始密码：${r.password}（请告知对方首次登录后修改）`)
    memberOpen.value = false
    load()
  } catch (e) { ElMessage.error(e.message || '添加失败') }
  memberSaving.value = false
}
</script>

<template>
  <div class="page">
    <div class="card">
      <div class="head">
        <div>
          <div class="t">团队管理</div>
          <div class="d">平台所有团队（租户）。建团队时自动创建 3 个系统角色，可指定首任管理员。归档后团队隐藏但数据保留。</div>
        </div>
        <button class="btn primary" @click="openCreate">+ 建团队</button>
      </div>
      <el-table :data="teams" v-loading="loading" style="width:100%" empty-text="暂无团队">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column label="团队名" min-width="180">
          <template #default="{ row }">
            <span class="name">{{ row.name }}</span>
            <span v-if="row.id === 1" class="tag-main">主团队</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span :class="['status', row.status]">{{ STATUS_ZH[row.status] || row.status }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="members" label="成员" width="70" align="center" />
        <el-table-column prop="accounts" label="广告账户" width="90" align="center" />
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }"><span class="mute">{{ (row.created_at || '').slice(0,19).replace('T',' ') }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="290" fixed="right">
          <template #default="{ row }">
            <button class="link" @click="rename(row)">改名</button>
            <button class="link" @click="openMember(row)">加成员</button>
            <button v-if="row.status === 'active' && row.id !== 1" class="link warn" @click="setStatus(row, 'suspended')">停用</button>
            <button v-if="row.status === 'suspended'" class="link ok" @click="setStatus(row, 'active')">激活</button>
            <button v-if="row.status !== 'archived' && row.id !== 1" class="link warn" @click="setStatus(row, 'archived')">归档</button>
            <button v-if="row.status === 'archived'" class="link ok" @click="setStatus(row, 'active')">恢复</button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 建团队弹窗 -->
    <el-dialog v-model="createOpen" title="建团队" width="460px">
      <div class="d">建团队同时种 3 个系统角色（管理员/操作员/财务）。可选指定首任管理员（自动建用户并加入）。</div>
      <div class="form-l"><label>团队名</label><input v-model="createForm.name" class="input" placeholder="如：客户A 投放团队" /></div>
      <div class="form-l"><label>管理员邮箱</label><input v-model="createForm.owner_email" class="input" placeholder="选填，留空=先建空团队" /></div>
      <div class="form-l"><label>管理员密码</label><input v-model="createForm.owner_password" class="input" type="password" placeholder="选填，留空=系统随机生成" /></div>
      <template #footer>
        <button class="btn" @click="createOpen = false">取消</button>
        <button class="btn primary" :disabled="createSaving" @click="submitCreate">{{ createSaving ? '创建中…' : '创建' }}</button>
      </template>
    </el-dialog>

    <!-- 加成员弹窗 -->
    <el-dialog v-model="memberOpen" :title="`加成员 · ${memberForm.name}`" width="460px">
      <div class="form-l"><label>邮箱</label><input v-model="memberForm.email" class="input" placeholder="新成员邮箱（已存在则直接加入）" /></div>
      <div class="form-l"><label>角色</label>
        <el-select v-model="memberForm.role" style="flex:1">
          <el-option v-for="(zh, k) in ROLE_ZH" :key="k" :value="k" :label="zh" />
        </el-select>
      </div>
      <div class="form-l"><label>密码</label><input v-model="memberForm.password" class="input" type="password" placeholder="选填，留空=系统随机生成" /></div>
      <template #footer>
        <button class="btn" @click="memberOpen = false">取消</button>
        <button class="btn primary" :disabled="memberSaving" @click="submitMember">{{ memberSaving ? '添加中…' : '添加' }}</button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page{display:flex;flex-direction:column;gap:14px}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:10px;padding:18px}
.head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;gap:12px}
.t{font-size:15px;font-weight:600;color:var(--t1);margin-bottom:4px}
.d{font-size:12px;color:var(--t3);line-height:1.6;margin-bottom:14px}
.btn{padding:8px 16px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:6px;font-size:13px;cursor:pointer}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn:disabled{opacity:.5}
.link{background:none;border:none;color:var(--ac);font-size:12px;cursor:pointer;padding:2px 6px;margin-right:2px}
.link.warn{color:var(--warning)}
.link.ok{color:var(--success)}
.link:hover{text-decoration:underline}
.name{color:var(--t1);font-weight:500}
.tag-main{font-size:10px;padding:1px 6px;background:var(--acg);color:var(--ac);border-radius:4px;margin-left:6px}
.status{font-size:12px}
.status.active{color:var(--success)}
.status.suspended{color:var(--warning)}
.status.archived{color:var(--t3)}
.mute{color:var(--t3);font-size:12px;font-variant-numeric:tabular-nums}
.form-l{display:flex;align-items:center;gap:8px;margin-bottom:12px}
.form-l > label{font-size:12px;color:var(--t3);width:82px;text-align:right;flex-shrink:0}
.input{flex:1;padding:7px 10px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;color:var(--t1);font-size:13px;font-family:inherit;box-sizing:border-box}
.input:focus{border-color:var(--ac);outline:none}
</style>
