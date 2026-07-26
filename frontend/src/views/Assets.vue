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
// AI 识别开关（per-user；关=只手填，开=显示 AI分析按钮）
const aiOn = ref(localStorage.getItem('tova_ai_on') === '1')
const toggleAi = (v) => { aiOn.value = v; localStorage.setItem('tova_ai_on', v ? '1' : '0') }
// 上传
const uploadOpen = ref(false)
const uploadFiles = ref([])  // [{file, name, tags, country, uploadTagsStr, countryStr, status}]
const uploadSaving = ref(false)
// 预览大图/视频
const previewAsset = ref(null)
const openPreview = (a) => { previewAsset.value = a }
const closePreview = () => { previewAsset.value = null }

// 重命名 inline
const editingId = ref(0)
const editingName = ref('')

// AI 分析中集合（即时反馈，不等列表刷新）
const analyzingIds = ref(new Set())

// AI 文案/受众编辑弹窗
const editOpen = ref(false)
const editAsset = ref(null)
const editForm = ref({ primary_text: '', headline: '', description: '', interestsStr: '', countriesStr: '' })
const editSaving = ref(false)

const BASE = 'https://api.tovaads.com'

const COUNTRIES = [
  { code: 'US', label: '美国' }, { code: 'VN', label: '越南' }, { code: 'TH', label: '泰国' },
  { code: 'ID', label: '印尼' }, { code: 'PH', label: '菲律宾' }, { code: 'MY', label: '马来西亚' },
  { code: 'TW', label: '台湾' }, { code: 'HK', label: '香港' }, { code: 'SG', label: '新加坡' },
  { code: 'CN', label: '中国大陆' }, { code: 'BR', label: '巴西' }, { code: 'MX', label: '墨西哥' },
  { code: 'IN', label: '印度' }, { code: 'JP', label: '日本' }, { code: 'KR', label: '韩国' },
  { code: 'GB', label: '英国' }, { code: 'DE', label: '德国' }, { code: 'FR', label: '法国' },
]

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
  files.forEach(f => uploadFiles.value.push({ file: f, name: f.name, uploadTagsStr: '', countryStr: '', status: 'pending' }))
}
const onDrop = (e) => {
  e.preventDefault()
  const files = Array.from(e.dataTransfer.files || [])
  files.forEach(f => uploadFiles.value.push({ file: f, name: f.name, uploadTagsStr: '', countryStr: '', status: 'pending' }))
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
      const tags = (item.uploadTagsStr || '').split(',').map(t => t.trim()).filter(Boolean)
      fd.append('tags', JSON.stringify(tags))
      fd.append('country', item.countryStr || '')
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

// AI 分析（raw fetch，绕 30s 超时——视频抽帧+视觉可能更久）
const analyze = async (a) => {
  analyzingIds.value.add(a.id)
  try {
    const r = await fetch(BASE + '/assets/' + a.id + '/analyze', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + (localStorage.getItem('tova_token') || '') },
    })
    const text = await r.text()
    const data = JSON.parse(text)
    if (!r.ok) throw new Error(data.detail || '分析失败')
    Object.assign(a, data)
    ElMessage.success('AI 分析完成')
  } catch (e) {
    ElMessage.error(e.message || 'AI 分析失败')
    // 失败也刷新拿 ai_status=failed + ai_error
    try { Object.assign(a, await GET('/assets/' + a.id)) } catch {}
  } finally {
    analyzingIds.value.delete(a.id)
  }
}

// 打开 AI 文案/受众编辑（AI 结果可改，或手动键入）
const openEdit = (a) => {
  editAsset.value = a
  const copy = a.ai_copy || {}
  const aud = a.ai_audience || {}
  editForm.value = {
    primary_text: copy.primary_text || '',
    headline: copy.headline || '',
    description: copy.description || '',
    interestsStr: (aud.interests || []).join(', '),
    countriesStr: (aud.countries || []).join(', '),
  }
  editOpen.value = true
}
const saveEdit = async () => {
  if (!editAsset.value) return
  editSaving.value = true
  try {
    const body = {
      primary_text: editForm.value.primary_text,
      headline: editForm.value.headline,
      description: editForm.value.description,
      interests: editForm.value.interestsStr.split(',').map(t => t.trim()).filter(Boolean),
      countries: editForm.value.countriesStr.split(',').map(t => t.trim().toUpperCase()).filter(Boolean),
    }
    const r = await PUT('/assets/' + editAsset.value.id + '/ai', body)
    Object.assign(editAsset.value, r)
    ElMessage.success('已保存')
    editOpen.value = false
  } catch (e) { ElMessage.error(e.message || '保存失败') }
  editSaving.value = false
}

// 改国家（影响 AI 文案语言）
const changeCountry = async (a, code) => {
  try {
    const r = await PUT('/assets/' + a.id, { country: code })
    Object.assign(a, r)
  } catch (e) { ElMessage.error(e.message || '改国家失败') }
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

const aiStatusText = (a) => {
  if (analyzingIds.value.has(a.id)) return '分析中'
  const s = a.ai_status
  if (s === 'done') return '✓ 已分析'
  if (s === 'failed') return '✗ 失败'
  if (s === 'analyzing') return '分析中'
  return '未分析'
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
const countryLabel = (code) => {
  const c = COUNTRIES.find(x => x.code === code)
  return c ? c.label : code
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
      <div class="bar-r">
        <div class="ai-toggle" :title="aiOn ? 'AI 识别开：点 AI分析 自动生成文案/受众' : 'AI 识别关：手动键入文案/受众'">
          <span class="ai-toggle-label">AI 识别</span>
          <el-switch :model-value="aiOn" @change="toggleAi" size="small" active-color="#0a84ff" inactive-color="#3a3a5c" />
        </div>
        <button class="btn primary" @click="openUpload">+ 上传素材</button>
      </div>
    </div>

    <!-- 网格 -->
    <div class="grid" v-loading="loading">
      <div v-for="a in assets" :key="a.id" class="card">
        <div class="thumb-wrap" @click="openPreview(a)" style="cursor:pointer">
          <img v-if="a.type === 'image'" :src="a.public_url" :alt="a.name" class="thumb" loading="lazy" />
          <video v-else-if="a.type === 'video'" :src="a.public_url" class="thumb" preload="metadata" />
          <span v-if="a.type === 'video' && a.duration_sec" class="dur-badge">{{ fmtDuration(a.duration_sec) }}</span>
          <span class="type-badge">{{ a.type === 'video' ? '视频' : '图片' }}</span>
          <span v-if="a.country" class="country-badge" :title="'目标投放：' + countryLabel(a.country)">{{ a.country }}</span>
        </div>
        <div class="card-body">
          <!-- 名称（双击编辑） -->
          <div v-if="editingId === a.id" class="name-edit">
            <input v-model="editingName" class="name-input" @keyup.enter="saveRename(a)" @blur="saveRename(a)" />
          </div>
          <div v-else class="name" :title="a.name" @dblclick="startRename(a)">{{ a.name }}</div>
          <!-- 标签 -->
          <div class="tag-row">
            <span v-for="t in (a.tags || []).slice(0,2)" :key="t" class="tag-chip">{{ t }}</span>
            <span v-if="(a.tags || []).length > 2" class="tag-more">+{{ a.tags.length - 2 }}</span>
            <span v-if="a.fb_image_hash" class="fb-mark" title="已上传到 FB">FB</span>
            <span v-if="a.ai_status === 'done'" class="ai-mark" title="AI 已分析">AI</span>
          </div>
          <div class="card-meta">
            <span class="meta-size">{{ fmtSize(a.file_size) }}</span>
            <span v-if="a.width" class="meta-dim">{{ a.width }}×{{ a.height }}</span>
            <span class="meta-id">#{{ a.id }}</span>
          </div>
        </div>
        <div class="card-ops">
          <button v-if="aiOn" class="op primary-op" :disabled="analyzingIds.has(a.id)" @click="analyze(a)">
            {{ analyzingIds.has(a.id) ? '分析中…' : 'AI分析' }}
          </button>
          <button class="op" @click="openEdit(a)">文案/受众</button>
          <button class="op" @click="startRename(a)">重命名</button>
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
          <select v-model="item.countryStr" class="upload-country-select">
            <option value="">投放国家（选填，驱动 AI 文案语言）</option>
            <option v-for="c in COUNTRIES" :key="c.code" :value="c.code">{{ c.label }} ({{ c.code }})</option>
          </select>
          <input v-model="item.uploadTagsStr" class="upload-tags-input" placeholder="标签（逗号分隔，选填）" />
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

    <!-- AI 文案/受众编辑弹窗 -->
    <el-dialog v-model="editOpen" :title="`文案 / 受众 · ${editAsset?.name || ''}`" width="560px" append-to-body :close-on-click-modal="false">
      <div v-if="editAsset" class="edit-form">
        <div class="edit-row">
          <label>目标国家</label>
          <select :value="editAsset.country || ''" class="edit-country" @change="changeCountry(editAsset, $event.target.value)">
            <option value="">未指定（英文）</option>
            <option v-for="c in COUNTRIES" :key="c.code" :value="c.code" :selected="editAsset.country === c.code">{{ c.label }} ({{ c.code }})</option>
          </select>
          <span class="edit-hint">驱动 AI 文案语言</span>
        </div>
        <div class="edit-row">
          <label>标题 headline</label>
          <input v-model="editForm.headline" class="edit-input" placeholder="广告标题（30字内）" maxlength="40" />
        </div>
        <div class="edit-row">
          <label>正文 primary text</label>
          <textarea v-model="editForm.primary_text" class="edit-textarea" rows="3" placeholder="广告正文（80字内）" maxlength="200"></textarea>
        </div>
        <div class="edit-row">
          <label>描述 description</label>
          <input v-model="editForm.description" class="edit-input" placeholder="描述（30字内）" maxlength="40" />
        </div>
        <div class="edit-row">
          <label>兴趣 interests</label>
          <input v-model="editForm.interestsStr" class="edit-input" placeholder="兴趣标签（逗号分隔）" />
        </div>
        <div class="edit-row">
          <label>国家 countries</label>
          <input v-model="editForm.countriesStr" class="edit-input" placeholder="投放国家代码（逗号分隔，如 US,VN）" />
        </div>
        <div v-if="aiOn" class="edit-tip">点「AI分析」可自动填充以上字段（基于素材视觉内容）。</div>
        <div v-else class="edit-tip">AI 识别已关，请手动键入。打开右上「AI 识别」开关可自动生成。</div>
      </div>
      <template #footer>
        <button class="btn" @click="editOpen = false">取消</button>
        <button class="btn primary" :disabled="editSaving" @click="saveEdit">{{ editSaving ? '保存中…' : '保存' }}</button>
      </template>
    </el-dialog>

    <!-- 预览弹窗 -->
    <el-dialog v-model="previewAsset" :title="previewAsset?.name" width="800px" @close="closePreview" append-to-body>
      <div v-if="previewAsset" style="text-align:center">
        <img v-if="previewAsset.type === 'image'" :src="previewAsset.public_url" style="max-width:100%;max-height:70vh;border-radius:8px" />
        <video v-else-if="previewAsset.type === 'video'" :src="previewAsset.public_url" controls style="max-width:100%;max-height:70vh;border-radius:8px" />
        <div style="margin-top:10px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
          <span class="meta-info">{{ previewAsset.type === 'video' ? '视频' : '图片' }}</span>
          <span v-if="previewAsset.file_size" class="meta-info">{{ fmtSize(previewAsset.file_size) }}</span>
          <span v-if="previewAsset.width" class="meta-info">{{ previewAsset.width }}×{{ previewAsset.height }}</span>
          <span v-if="previewAsset.country" class="meta-info">{{ countryLabel(previewAsset.country) }}</span>
          <span class="meta-info">#{{ previewAsset.id }}</span>
        </div>
        <div v-if="previewAsset.ai_status === 'done'" class="preview-ai">
          <div class="preview-ai-title">AI 文案</div>
          <div v-if="previewAsset.ai_copy?.headline" class="preview-ai-line"><b>标题：</b>{{ previewAsset.ai_copy.headline }}</div>
          <div v-if="previewAsset.ai_copy?.primary_text" class="preview-ai-line"><b>正文：</b>{{ previewAsset.ai_copy.primary_text }}</div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 14px; }

/* 工具栏 */
.bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.bar-l { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.bar-r { display: flex; align-items: center; gap: 12px; }
.ai-toggle { display: flex; align-items: center; gap: 6px; padding: 4px 10px; background: var(--bg3); border-radius: var(--rs); }
.ai-toggle-label { font-size: 12px; color: var(--t2); }
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
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; min-height: 200px; }
.card { background: var(--bg2); border: 1px solid var(--bd); border-radius: 10px; overflow: hidden; transition: border-color .15s; display: flex; flex-direction: column; }
.card:hover { border-color: var(--ac); }
.thumb-wrap { position: relative; width: 100%; height: 130px; background: var(--bg3); display: flex; align-items: center; justify-content: center; }
.thumb { max-width: 100%; max-height: 100%; object-fit: cover; width: 100%; height: 100%; }
.dur-badge { position: absolute; bottom: 4px; right: 4px; background: rgba(0,0,0,.7); color: #fff; font-size: 10px; padding: 1px 6px; border-radius: 4px; }
.type-badge { position: absolute; top: 4px; left: 4px; background: rgba(0,0,0,.6); color: #fff; font-size: 9px; padding: 1px 5px; border-radius: 4px; }
.country-badge { position: absolute; top: 4px; right: 4px; background: rgba(10,132,255,.85); color: #fff; font-size: 9px; padding: 1px 5px; border-radius: 4px; font-weight: 600; }
.card-body { padding: 8px 10px; flex: 1; }
.name { font-size: 13px; color: var(--t1); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: text; }
.name-edit { display: flex; }
.name-input { width: 100%; padding: 3px 6px; background: var(--bg3); border: 1px solid var(--ac); border-radius: 4px; color: var(--t1); font-size: 13px; }
.tag-row { display: flex; gap: 3px; margin-top: 4px; flex-wrap: wrap; align-items: center; }
.tag-chip { font-size: 10px; padding: 1px 6px; background: var(--bg3); color: var(--t2); border-radius: 8px; }
.tag-more { font-size: 10px; padding: 1px 5px; color: var(--t3); }
.fb-mark { font-size: 9px; padding: 1px 5px; background: rgba(10,132,255,.15); color: var(--ac); border-radius: 4px; font-weight: 600; }
.ai-mark { font-size: 9px; padding: 1px 5px; background: rgba(48,209,88,.15); color: var(--success); border-radius: 4px; font-weight: 600; }
.card-meta { display: flex; gap: 6px; margin-top: 4px; }
.meta-size, .meta-dim, .meta-id { font-size: 10px; color: var(--t3); font-variant-numeric: tabular-nums; }
.card-ops { display: flex; gap: 2px; padding: 4px 10px 8px; flex-wrap: wrap; }
.op { background: none; border: none; color: var(--t3); font-size: 11px; cursor: pointer; padding: 2px 6px; border-radius: 4px; }
.op:hover { background: var(--bg3); color: var(--t1); }
.op.danger:hover { color: var(--error); }
.op.primary-op { color: var(--ac); }
.op.primary-op:hover { background: rgba(10,132,255,.12); }
.op:disabled { opacity: .5; cursor: wait; }
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
.upload-name-input, .upload-tags-input, .upload-country-select { width: 100%; margin-top: 4px; padding: 4px 8px; background: var(--bg2); border: 1px solid var(--bd); border-radius: 5px; color: var(--t1); font-size: 12px; box-sizing: border-box; }
.upload-name-input:focus, .upload-tags-input:focus, .upload-country-select:focus { border-color: var(--ac); outline: none; }
.upload-status { font-size: 11px; }
.upload-status.done { color: var(--success); }
.upload-status.fail { color: var(--error); }
.upload-status.uploading { color: var(--ac); }
.meta-info { font-size: 12px; color: var(--t3); }

/* AI 编辑弹窗 */
.edit-form { display: flex; flex-direction: column; gap: 12px; }
.edit-row { display: flex; flex-direction: column; gap: 4px; }
.edit-row label { font-size: 12px; color: var(--t3); font-weight: 500; }
.edit-row .edit-hint { font-size: 11px; color: var(--t3); }
.edit-input, .edit-country, .edit-textarea { width: 100%; padding: 6px 10px; background: var(--bg3); border: 1px solid var(--bd); border-radius: 6px; color: var(--t1); font-size: 13px; font-family: inherit; box-sizing: border-box; }
.edit-input:focus, .edit-country:focus, .edit-textarea:focus { border-color: var(--ac); outline: none; }
.edit-textarea { resize: vertical; }
.edit-tip { font-size: 11px; color: var(--t3); padding: 8px 10px; background: var(--bg3); border-radius: 6px; }
.preview-ai { margin-top: 14px; padding: 10px; background: var(--bg3); border-radius: 8px; text-align: left; }
.preview-ai-title { font-size: 12px; color: var(--t3); margin-bottom: 6px; }
.preview-ai-line { font-size: 13px; color: var(--t1); margin-top: 4px; line-height: 1.5; }
</style>
