<template>
  <div class="page">
    <div class="head">
      <div>
        <h2>FB App 管理</h2>
        <p class="sub">集中管理 Facebook App 凭据（App ID + Secret）。系统级 App 全租户共享（仅超管可建），团队 App 本租户私有。</p>
      </div>
      <button class="btn primary" @click="openEdit(null)">+ 添加 App</button>
    </div>

    <div v-loading="loading" class="grid">
      <div v-for="a in apps" :key="a.id" class="card">
        <div class="card-head">
          <span class="card-name">{{ a.name || '(未命名)' }}</span>
          <span :class="['tag', a.is_system ? 'sys' : 'team']">{{ a.is_system ? '系统级' : '团队' }}</span>
        </div>
        <div class="meta"><span>App ID</span><code>{{ a.app_id }}</code></div>
        <div class="meta"><span>Secret</span><code>••••••••（已加密保存）</code></div>
        <div class="ops">
          <button class="op" @click="openEdit(a)">编辑</button>
          <button class="op danger" @click="remove(a)">删除</button>
        </div>
      </div>
      <div v-if="!apps.length && !loading" class="empty">暂无 App，点「添加 App」录入。</div>
    </div>

    <el-dialog v-model="editOpen" :title="editing ? '编辑 App' : '添加 App'" width="460px">
      <div class="form">
        <div class="row"><label>名称</label><input v-model="form.name" class="inp" placeholder="如：主 App / 备用 App"></div>
        <div class="row"><label>App ID</label><input v-model="form.app_id" class="inp" placeholder="Facebook App ID（数字）"></div>
        <div class="row"><label>App Secret</label><input v-model="form.app_secret" class="inp" type="password" :placeholder="editing ? '留空=不修改' : 'Facebook App Secret'"></div>
        <div class="row" v-if="isSuper"><label>类型</label>
          <el-switch v-model="form.is_system" active-text="系统级（全租户）" inactive-text="团队私有" />
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="editOpen = false">取消</button>
        <button class="btn primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { GET, POST, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isSuperadminSync } from '../router'

const apps = ref([])
const loading = ref(true)
const editOpen = ref(false)
const editing = ref(null)
const saving = ref(false)
const isSuper = isSuperadminSync()
const blank = () => ({ name: '', app_id: '', app_secret: '', is_system: false })
const form = ref(blank())

const load = async () => {
  loading.value = true
  try { apps.value = await GET('/fb/apps') } catch (e) { ElMessage.error(e.message || '加载失败') }
  loading.value = false
}
const openEdit = (a) => {
  editing.value = a
  form.value = a ? { name: a.name || '', app_id: a.app_id, app_secret: '', is_system: !!a.is_system } : blank()
  editOpen.value = true
}
const save = async () => {
  if (!form.value.app_id.trim()) return ElMessage.warning('请填 App ID')
  if (!editing.value && !form.value.app_secret.trim()) return ElMessage.warning('请填 App Secret')
  saving.value = true
  try {
    if (editing.value) await POST('/fb/apps/' + editing.value.id, form.value)
    else await POST('/fb/apps', form.value)
    ElMessage.success(editing.value ? '已更新' : '已添加')
    editOpen.value = false
    await load()
  } catch (e) { ElMessage.error(e.message || '保存失败') }
  saving.value = false
}
const remove = async (a) => {
  try {
    await ElMessageBox.confirm(`删除 App「${a.name || a.app_id}」？`, '确认', { type: 'warning' })
    await DELETE('/fb/apps/' + a.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) { if (e === 'cancel') return }
}
onMounted(load)
</script>

<style scoped>
.page{padding:20px;max-width:980px}
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:18px}
.head h2{margin:0 0 4px;font-size:18px}
.sub{margin:0;font-size:12px;color:var(--t3);max-width:560px;line-height:1.5}
.btn{padding:7px 14px;border-radius:6px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);cursor:pointer;font-size:13px}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn:disabled{opacity:.6;cursor:not-allowed}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:8px;padding:12px 14px}
.card-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.card-name{font-weight:600;font-size:14px}
.tag{font-size:11px;padding:2px 8px;border-radius:4px}
.tag.sys{background:var(--ac);color:#fff}
.tag.team{background:var(--bg3);color:var(--t2)}
.meta{display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--t3);margin:4px 0;gap:8px}
.meta code{font-family:monospace;color:var(--t2);word-break:break-all;text-align:right}
.ops{display:flex;gap:6px;margin-top:8px}
.op{background:none;border:1px solid var(--bd);color:var(--t2);font-size:11px;cursor:pointer;padding:3px 8px;border-radius:4px}
.op:hover{background:var(--bg3)}
.op.danger{color:var(--error)}
.empty{grid-column:1/-1;padding:32px;text-align:center;color:var(--t3);font-size:13px}
.form{display:flex;flex-direction:column;gap:10px}
.form .row{display:flex;align-items:center;gap:10px}
.form label{width:84px;font-size:13px;color:var(--t2);flex-shrink:0}
.inp{flex:1;padding:7px 10px;border:1px solid var(--bd);border-radius:6px;background:var(--bg2);color:var(--t1);font-size:13px}
</style>
