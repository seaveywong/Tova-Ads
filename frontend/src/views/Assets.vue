<script setup>
import { ref, computed, onMounted } from 'vue'
import { GET, PUT, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const assets = ref([])
const loading = ref(false)
// 筛选
const fType = ref('')
const fTag = ref('')
const fSearch = ref('')
// 上传
const uploadOpen = ref(false)
const uploadFiles = ref([])  // [{file, name, tags, progress, status}]
const uploadSaving = ref(false)
// 重命名 inline
const editingId = ref(0)
const editingName = ref('')

const BASE = 'https://api.tovaads.com'

const load = async () => {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (fType.value) params.set('type', fType.value)
    if (fTag.value) params.set('tag', fTag.value)
    if (fSearch.value.trim()) params.set('search', fSearch.value.trim())
    assets.value = await GET('/assets?' + params.toString())
  } catch (e) { ElMessage.error(e.message || '加载失败') }
  loading.value = false
}
onMounted(load)

const typeChips = [
  { key: '', label: '全部' },
  { key: 'image', label: '图片' },
  { key: 'video', label: '视频' },
]
const setType = (t) => { fType.value = t; load() }

// 所有标签（从素材列表提取）
const allTags = computed(() => {
  const s = new Set()
  assets.value.forEach(a => (a.tags || []).forEach(t => s.add(t)))
  return [...s].sort()
})

// 上传
const openUpload = () => { uploadFiles.value = []; uploadOpen.value = true }
const onFileChange = (e) => {
  const files = Array.from(e.target.files || [])
  files.forEach(f => uploadFiles.value.push({ file: f, name: f.name, tags: [], progress: 0, status: 'pending' }))
}
const onDrop = (e) => {
  e.preventDefault()
  const files = Array.from(e.dataTransfer.files || [])
  files.forEach(f => uploadFiles.value.push({ file: f, name: f.name, tags: [], progress: 0, status: 'pending' }))
}
const removeUploadItem = (i) => uploadFiles.value.splice(i, 1)

const submitUpload = async () => {
  if (!uploadFiles.value.length) return ElMessage.warning('先选择文件')
  uploadSaving.value = true
  let ok = 0, fail = 0
  for (const item of uploadFiles.value) {
    item.status = 'uploading'
    try {
      const fd = new FormData()
      fd.append('file', item.file)
      fd.append('name', item.name || item.file.name)
      fd.append('tags', JSON.stringify(item.tags || []))
      const r = await fetch(BASE + '/assets/upload', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + (localStorage.getItem('tova_token') || '') },
        body: fd,
      })
      if (r.status === 401) { localStorage.removeItem('tova_token'); throw new Error('未登录') }
      const text = await r.text()
      const data = JSON.parse(text)
      if (!r.ok) throw new Error(data.detail || '上传失败')
      item.status = 'done'
      ok++
    } catch (e) {
      item.status = 'fail'
      fail++
    }
  }
  uploadSaving.value = false
  if (ok) { ElMessage.success(`${ok} 个素材上传成功`); uploadOpen.value = false; await load() }
  if (fail) ElMessage.error(`${fail} 个失败`)
}

// 重命名（inline）
const startRename = (a) => { editingId.value = a.id; editingName.value = a.name }
const saveRename = async (a) => {
  const n = editingName.value.trim()
  editingId.value = 0
  if (!n || n === a.name) return
  try {
    const r = await PUT('/assets/' + a.id, { name: n })
    Object.assign(a, r)
    ElMessage.success('已重命名')
  } catch (e) { ElMessage.error(e.message || '重命名失败') }
}

// 改标签
const editTags = async (a) => {
  try {
    const { value } = await ElMessageBox.prompt('标签（逗号分隔）', `标签 · ${a.name}`, {
      inputValue: (a.tags || []).join(', '),
      confirmButtonText: '保存', cancelButtonText: '取消',
    })
    const tags = value.split(',').map(t => t.trim()).filter(Boolean)
    const r = await PUT('/assets/' + a.id, { tags })
    Object.assign(a, r)
    ElMessage.success('标签已更新')
  } catch (e) { if (e !== 'cancel' && e?.message) ElMessage.error(e.message) }
}

// 删除（硬删）
const remove = async (a) => {
  try {
    const usage = a.usage_count > 0 ? `\n\n⚠ 该素材被 ${a.usage_count} 个投放模板引用，删除后需重新选素材。` : ''
    await ElMessageBox.confirm(`确定删除「${a.name}」？\n服务器文件 + 记录一起删除（不可恢复）。${usage}`, '硬删确认',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' })
    await DELETE('/assets/' + a.id)
    ElMessage.success('已删除')
    assets.value = assets.value.filter(x => x.id !== a.id)
  } catch (e) {
    if (e === 'cancel') return
    ElMessage.error(e.message || '删除失败')
  }
}

const fmtSize = (bytes) => {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(0) + 'KB'
  return (bytes / 1048576).toFixed(1) + 'MB'
}
const fmtDuration = (sec) => {
  if (!sec) return ''
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return m > 0 ? `${m}:${String(s).padStart(2, '0')}` : `${s}s`
}
</script>

<template>
  <div class="page">
    <!-- 工具栏 -->
    <div class="bar">
      <div class="bar-l">
        <div class="type-segs">
          <button v-for="tc in typeChips" :key="tc.key" :class="['seg', { on: fType === tc.key }]" @click="setType(tc.key)">{{ tc.label }}</button>
        </div>
        <el-select v-if="allTags.length" v-model="fTag" placeholder="标签" clearable size="small" style="width:140px" @change="load">
          <el-option v-for="t in allTags" :key="t" :value="t" :label="t" />
        </el-select>
        <input v-model="fSearch" class="search-input" placeholder="搜索名称" @keyup.enter="load" />
      </div>
      <button class="btn primary" @click="openUpload">+ 上传素材</button>
    </div>

    <!-- 网格 -->
    <div class="grid" v-loading="loading">
      <div v-for="a in assets" :key="a.id" class="card">
        <div class="thumb-wrap">
          <img v-if="a.type === 'image'" :src="a.public_url" :alt="a.name" class="thumb" loading="lazy" />
          <video v-else-if="a.type === 'video'" :src="a.public_url" class="thumb" preload="metadata" />
          <span v-if="a.type === 'video' && a.duration_sec" class="dur-badge">{{ fmtDuration(a.duration_sec) }}</span>
          <span class="type-badge">{{ a.type === 'video' ? '视频' : '图片' }}</span>
        </div>
        <div class="card-body">
          <!-- 名称（双击编辑） -->
          <div v-if="editingId === a.id" class="name-edit">
            <input v-model="editingName" class="name-input" @keyup.enter="saveRename(a)" @blur="saveRename(a)" ref="renameInput" />
          </div>
          <div v-else class="name" :title="a.name" @dblclick="startRename(a)">{{ a.name }}</div>
          <!-- 标签 -->
          <div class="tag-row">
            <span v-for="t in (a.tags || []).slice(0,2)" :key="t" class="tag-chip">{{ t }}</span>
            <span v-if="(a.tags || []).length > 2" class="tag-more">+{{ a.tags.length - 2 }}</span>
            <span v-if="a.fb_image_hash" class="fb-mark" title="已上传到 FB">FB</span>
          </div>
          <div class="card-meta">
            <span class="meta-size">{{ fmtSize(a.file_size) }}</span>
            <span v-if="a.width" class="meta-dim">{{ a.width }}×{{ a.height }}</span>
            <span class="meta-id">#{{ a.id }}</span>
          </div>
        </div>
        <div class="card-ops">
          <button class="op" @click="startRename(a)">重命名</button>
          <button class="op" @click="editTags(a)">标签</button>
          <button class="op danger" @click="remove(a)">删除</button>
        </div>
      </div>
      <div v-if="!assets.length && !loading" class="empty">暂无素材，点「+ 上传素材」添加。</div>
    </div>

    <!-- 上传抽屉 -->
    <el-drawer v-model="uploadOpen" title="上传素材" direction="rtl" size="520px" :destroy-on-close="true">
      <div class="drop-zone" @dragover.prevent @drop="onDrop">
        <div class="drop-text">拖拽文件到此</div>
        <div class="drop-or">或</div>
        <label class="file-btn">选择文件<input type="file" accept="image/*,video/*" multiple @change="onFileChange" hidden /></label>
        <div class="drop-hint">支持图片（jpg/png/webp）和视频（mp4/mov）</div>
      </div>
      <div v-if="uploadFiles.length" class="upload-list">
        <div v-for="(item, i) in uploadFiles" :key="i" class="upload-item">
          <div class="upload-item-info">
            <span class="upload-name">{{ item.file.name }}</span>
            <span class="upload-size">{{ fmtSize(item.file.size) }}</span>
            <button class="upload-remove" @click="removeUploadItem(i)">✕</button>
          </div>
          <input v-model="item.name" class="upload-name-input" placeholder="素材名称（默认文件名）" />
          <input v-model="item.uploadTagsStr" class="upload-tags-input" placeholder="标签（逗号分隔，选填）" @change="item.tags = (item.uploadTagsStr || '').split(',').map(t=>t.trim()).filter(Boolean)" />
          <span v-if="item.status === 'done'" class="upload-status done">✓ 完成</span>
          <span v-if="item.status === 'fail'" class="upload-status fail">✗ 失败</span>
          <span v-if="item.status === 'uploading'" class="upload-status uploading">上传中…</span>
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="uploadOpen = false">取消</button>
        <button class="btn primary" :disabled="uploadSaving || !uploadFiles.length" @click="submitUpload">{{ uploadSaving ? '上传中…' : `上传 ${uploadFiles.length} 个` }}</button>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 14px; }

/* 工具栏 */
.bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.bar-l { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.type-segs { display: flex; gap: 2px; background: var(--bg3); border-radius: 7px; padding: 2px; }
.seg { padding: 5px 12px; border: none; background: transparent; color: var(--t3); font-size: 12px; border-radius: 5px; cursor: pointer; font-family: inherit; }
.seg.on { background: var(--bg2); color: var(--t1); }
.seg:hover { color: var(--t1); }
.search-input { padding: 5px 10px; background: var(--bg3); border: 1px solid var(--bd); border-radius: 6px; color: var(--t1); font-size: 12px; width: 160px; }
.search-input:focus { border-color: var(--ac); outline: none; }

.btn { padding: 7px 14px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t1); border-radius: 6px; font-size: 13px; cursor: pointer; font-family: inherit; }
.btn.primary { background: var(--ac); color: #fff; border-color: var(--ac); }
.btn:disabled { opacity: .5; }

/* 网格 */
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; min-height: 200px; }
.card { background: var(--bg2); border: 1px solid var(--bd); border-radius: 10px; overflow: hidden; transition: border-color .15s; }
.card:hover { border-color: var(--ac); }
.thumb-wrap { position: relative; width: 100%; height: 130px; background: var(--bg3); display: flex; align-items: center; justify-content: center; }
.thumb { max-width: 100%; max-height: 100%; object-fit: cover; width: 100%; height: 100%; }
.dur-badge { position: absolute; bottom: 4px; right: 4px; background: rgba(0,0,0,.7); color: #fff; font-size: 10px; padding: 1px 6px; border-radius: 4px; }
.type-badge { position: absolute; top: 4px; left: 4px; background: rgba(0,0,0,.6); color: #fff; font-size: 9px; padding: 1px 5px; border-radius: 4px; }
.card-body { padding: 8px 10px; }
.name { font-size: 13px; color: var(--t1); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: text; }
.name-edit { display: flex; }
.name-input { width: 100%; padding: 3px 6px; background: var(--bg3); border: 1px solid var(--ac); border-radius: 4px; color: var(--t1); font-size: 13px; }
.tag-row { display: flex; gap: 3px; margin-top: 4px; flex-wrap: wrap; }
.tag-chip { font-size: 10px; padding: 1px 6px; background: var(--bg3); color: var(--t2); border-radius: 8px; }
.tag-more { font-size: 10px; padding: 1px 5px; color: var(--t3); }
.fb-mark { font-size: 9px; padding: 1px 5px; background: rgba(10,132,255,.15); color: var(--ac); border-radius: 4px; font-weight: 600; }
.card-meta { display: flex; gap: 6px; margin-top: 4px; }
.meta-size, .meta-dim, .meta-id { font-size: 10px; color: var(--t3); font-variant-numeric: tabular-nums; }
.card-ops { display: flex; gap: 2px; padding: 4px 10px 8px; }
.op { background: none; border: none; color: var(--t3); font-size: 11px; cursor: pointer; padding: 2px 6px; border-radius: 4px; }
.op:hover { background: var(--bg3); color: var(--t1); }
.op.danger:hover { color: var(--error); }
.empty { grid-column: 1 / -1; padding: 40px; text-align: center; color: var(--t3); font-size: 14px; }

/* 上传抽屉 */
.drop-zone { border: 2px dashed var(--bd); border-radius: 10px; padding: 30px; text-align: center; margin-bottom: 14px; transition: border-color .15s; }
.drop-zone:hover { border-color: var(--ac); }
.drop-text { font-size: 14px; color: var(--t2); }
.drop-or { font-size: 12px; color: var(--t3); margin: 4px 0; }
.file-btn { display: inline-block; padding: 6px 14px; background: var(--ac); color: #fff; border-radius: 6px; font-size: 13px; cursor: pointer; }
.drop-hint { font-size: 11px; color: var(--t3); margin-top: 6px; }
.upload-list { display: flex; flex-direction: column; gap: 8px; }
.upload-item { background: var(--bg3); border-radius: 8px; padding: 8px 10px; }
.upload-item-info { display: flex; align-items: center; gap: 6px; }
.upload-name { font-size: 12px; color: var(--t1); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.upload-size { font-size: 10px; color: var(--t3); }
.upload-remove { background: none; border: none; color: var(--t3); cursor: pointer; font-size: 14px; }
.upload-name-input, .upload-tags-input { width: 100%; margin-top: 4px; padding: 4px 8px; background: var(--bg2); border: 1px solid var(--bd); border-radius: 5px; color: var(--t1); font-size: 12px; box-sizing: border-box; }
.upload-name-input:focus, .upload-tags-input:focus { border-color: var(--ac); outline: none; }
.upload-status { font-size: 11px; }
.upload-status.done { color: var(--success); }
.upload-status.fail { color: var(--error); }
.upload-status.uploading { color: var(--ac); }
</style>
