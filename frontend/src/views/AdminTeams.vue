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

// 状态变更（归档/恢复/停用/激活，统一入口）
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
// 操作下拉分发
const handleOp = (cmd, t) => {
  const map = { suspend: 'suspended', activate: 'active', archive: 'archived', restore: 'active' }
  setStatus(t, map[cmd])
}
// 该行是否还有「更多」操作（主团队只有 active 且不可改状态 → 没更多）
const hasMore = (row) => {
  if (row.id === 1) return false
  if (row.status === 'active') return true   // 可停用/归档
  if (row.status === 'suspended') return true // 可激活/归档
  if (row.status === 'archived') return true  // 可恢复
  return false
}

// 加成员
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
        <div class="head-text">
          <div class="t">团队管理</div>
          <div class="d">平台所有团队（租户）。建团队时自动创建 3 个系统角色，可指定首任管理员。归档后团队隐藏但数据保留。</div>
        </div>
        <button class="btn primary" @click="openCreate"><span class="plus">+</span> 建团队</button>
      </div>

      <el-table :data="teams" v-loading="loading" style="width:100%" empty-text="暂无团队" row-key="id">
        <el-table-column prop="id" label="ID" width="56" align="center" />
        <el-table-column label="团队名" min-width="200">
          <template #default="{ row }">
            <div class="name-cell">
              <span class="name">{{ row.name }}</span>
              <span v-if="row.id === 1" class="badge-main">主团队</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <span :class="['status', row.status]"><i class="sdot"></i>{{ STATUS_ZH[row.status] || row.status }}</span>
          </template>
        </el-table-column>
        <el-table-column label="成员" width="68" align="center">
          <template #default="{ row }">
            <span :class="['num', { zero: row.members === 0 }]">{{ row.members }}</span>
          </template>
        </el-table-column>
        <el-table-column label="广告账户" width="88" align="center">
          <template #default="{ row }">
            <span :class="['num', { zero: row.accounts === 0 }]">{{ row.accounts }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }"><span class="mute">{{ (row.created_at || '').slice(0,16).replace('T',' ') }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="172" fixed="right">
          <template #default="{ row }">
            <div class="ops">
              <button class="op primary" @click="openMember(row)">加成员</button>
              <button class="op" @click="rename(row)">改名</button>
              <el-dropdown v-if="hasMore(row)" trigger="click" @command="c => handleOp(c, row)">
                <button class="op more" title="更多">⋯</button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="row.status === 'active'" command="suspend">停用</el-dropdown-item>
                    <el-dropdown-item v-if="row.status === 'suspended'" command="activate">激活</el-dropdown-item>
                    <el-dropdown-item v-if="row.status !== 'archived'" command="archive" divided class="danger">归档</el-dropdown-item>
                    <el-dropdown-item v-if="row.status === 'archived'" command="restore">恢复</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 建团队弹窗 -->
    <el-dialog v-model="createOpen" title="建团队" width="460px">
      <div class="dlg-d">建团队同时创建 3 个系统角色（管理员/操作员/财务）。可选指定首任管理员（自动建用户并加入）。</div>
      <div class="form-l"><label>团队名</label><input v-model="createForm.name" class="input" placeholder="如：客户A 投放团队" /></div>
      <div class="form-l"><label>管理员邮箱</label><input v-model="createForm.owner_email" class="input" placeholder="选填，留空 = 先建空团队" /></div>
      <div class="form-l"><label>管理员密码</label><input v-model="createForm.owner_password" class="input" type="password" placeholder="选填，留空 = 系统随机生成" /></div>
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
      <div class="form-l"><label>密码</label><input v-model="memberForm.password" class="input" type="password" placeholder="选填，留空 = 系统随机生成" /></div>
      <template #footer>
        <button class="btn" @click="memberOpen = false">取消</button>
        <button class="btn primary" :disabled="memberSaving" @click="submitMember">{{ memberSaving ? '添加中…' : '添加' }}</button>
      </template>
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

/* 按钮 */
.btn{padding:8px 16px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:7px;font-size:13px;cursor:pointer;transition:all .15s;font-family:inherit}
.btn:hover{border-color:var(--ac)}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn.primary:hover{filter:brightness(1.08)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.plus{font-weight:600;margin-right:2px}

/* 表格内 */
.name-cell{display:flex;align-items:center;gap:8px}
.name{color:var(--t1);font-weight:500}
.badge-main{font-size:10px;padding:2px 7px;background:var(--acg);color:var(--ac);border-radius:10px;font-weight:600;letter-spacing:.02em}

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

/* 操作列 */
.ops{display:flex;align-items:center;gap:4px}
.op{background:transparent;border:1px solid transparent;color:var(--t2);font-size:12px;cursor:pointer;padding:5px 10px;border-radius:6px;transition:all .15s;font-family:inherit;white-space:nowrap}
.op:hover{background:var(--bg3);color:var(--t1)}
.op.primary{color:var(--ac);font-weight:500}
.op.primary:hover{background:var(--acg)}
.op.more{padding:5px 9px;font-size:15px;line-height:1;letter-spacing:-1px}
:deep(.danger){color:var(--error)}

/* 弹窗 */
.dlg-d{font-size:12px;color:var(--t3);line-height:1.6;margin-bottom:16px;padding:10px 12px;background:var(--bg3);border-radius:7px}
.form-l{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.form-l > label{font-size:12px;color:var(--t3);width:82px;text-align:right;flex-shrink:0}
.input{flex:1;padding:8px 11px;background:var(--bg3);border:1px solid var(--bd);border-radius:7px;color:var(--t1);font-size:13px;font-family:inherit;box-sizing:border-box;transition:border-color .15s}
.input:focus{border-color:var(--ac);outline:none}
.input::placeholder{color:var(--t3);opacity:.7}

/* 表格整体微调 */
:deep(.el-table){font-size:13px}
:deep(.el-table th.el-table__cell){background:var(--bg3);color:var(--t2);font-weight:600;font-size:12px}
:deep(.el-table tr:hover > td){background:var(--bg3) !important}
</style>
