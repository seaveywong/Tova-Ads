<script setup>
// 通用列表管理器（批PP）：批量导入弹窗（换行分隔自动识别）+ 列表行内编辑/删除
// 用于投放链接的目标 URL、自定义域名等自由输入列表——曾 el-select 手输标签，量大难管。
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  type: { type: String, default: 'url' },   // url | domain
  placeholder: { type: String, default: '' },
  buttonOnly: { type: Boolean, default: false },   // true=只渲染「批量导入」按钮+弹窗（用于已有选择器/列表旁挂导入）
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()

const importOpen = ref(false)
const importText = ref('')
const importPreview = ref(null)   // { valid: [], dup: [], invalid: [{line, reason}] }

const normalize = (raw) => {
  let s = raw.trim()
  if (!s || s.startsWith('#')) return { v: '', skip: true }
  if (props.type === 'url') {
    if (!/^https?:\/\//i.test(s)) s = 'https://' + s
    try {
      const u = new URL(s)
      if (!u.hostname.includes('.')) return { v: '', invalid: 'no-host' }
      return { v: s }
    } catch {
      return { v: '', invalid: 'bad-url' }
    }
  }
  // domain：剥 scheme/路径，小写，合法域名校验
  s = s.replace(/^https?:\/\//i, '').split('/')[0].toLowerCase()
  if (!/^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/.test(s)) return { v: '', invalid: 'bad-domain' }
  return { v: s }
}
const parseImport = () => {
  const lines = importText.value.split(/[\n\r]+/)
  const valid = [], dup = [], invalid = []
  const existing = new Set(props.modelValue)
  const seen = new Set()
  for (const ln of lines) {
    const r = normalize(ln)
    if (r.skip) continue
    if (r.invalid) { invalid.push({ line: ln.trim().slice(0, 60), reason: t('lm.bad' + (props.type === 'url' ? 'Url' : 'Domain')) }); continue }
    if (existing.has(r.v) || seen.has(r.v)) { dup.push(r.v); continue }
    seen.add(r.v); valid.push(r.v)
  }
  importPreview.value = { valid, dup: dup.length, invalid }
}
const openImport = () => { importOpen.value = true; importText.value = ''; importPreview.value = null }
const doImport = () => {
  if (!importPreview.value?.valid.length) return
  emit('update:modelValue', [...props.modelValue, ...importPreview.value.valid])
  importOpen.value = false
  ElMessage.success(t('lm.imported', { n: importPreview.value.valid.length }))
}

const editing = ref('')   // 正在编辑的原始值（空=无）
const editDraft = ref('')
const startEdit = (v) => { editing.value = v; editDraft.value = v }
const saveEdit = () => {
  const r = normalize(editDraft.value)
  if (!r.v) { editing.value = ''; return }
  const list = props.modelValue.map(x => (x === editing.value ? r.v : x)).filter((x, i, a) => a.indexOf(x) === i)
  emit('update:modelValue', list)
  editing.value = ''
}
const removeItem = (v) => emit('update:modelValue', props.modelValue.filter(x => x !== v))
const addItem = () => {
  const list = [...props.modelValue, props.type === 'url' ? 'https://' : '']
  emit('update:modelValue', list)
  editing.value = list[list.length - 1]
  editDraft.value = list[list.length - 1]
}
const label = computed(() => props.type === 'url' ? t('lm.itemUrl') : t('lm.itemDomain'))
</script>

<template>
  <div class="lm">
    <div v-if="buttonOnly" class="lm-inline">
      <button class="ctrl-btn sm" @click="openImport">{{ t('lm.batchImport') }}</button>
    </div>
    <div v-if="!buttonOnly" class="lm-toolbar">
      <button class="ctrl-btn sm" @click="openImport">{{ t('lm.batchImport') }}</button>
      <button class="ctrl-btn sm" @click="addItem">{{ t('lm.addOne') }}</button>
      <span v-if="modelValue.length" class="lm-count">{{ t('lm.count', { n: modelValue.length }) }}</span>
      <span v-else class="lm-count lm-empty-hint">{{ placeholder }}</span>
    </div>
    <div v-if="!buttonOnly && modelValue.length" class="lm-list">
      <div v-for="(v, i) in modelValue" :key="v + i" class="lm-row">
        <span class="lm-idx">{{ i + 1 }}</span>
        <template v-if="editing === v">
          <input v-model="editDraft" class="lm-edit" @keyup.enter="saveEdit" @keyup.esc="editing = ''" @blur="saveEdit" />
        </template>
        <template v-else>
          <span class="lm-val" :title="v" @dblclick="startEdit(v)">{{ v }}</span>
          <button class="lm-del" @click="startEdit(v)" :title="t('lm.edit')">✎</button>
          <button class="lm-del" @click="removeItem(v)" :title="t('common.delete')">✕</button>
        </template>
      </div>
    </div>

    <el-dialog v-model="importOpen" :title="t('lm.batchImport')" width="560px" append-to-body :close-on-click-modal="false">
      <div class="lm-tip">{{ t('lm.tip' + (type === 'url' ? 'Url' : 'Domain')) }}</div>
      <textarea v-model="importText" class="lm-ta" rows="9" :placeholder="t('lm.taPh')" @input="importPreview = null"></textarea>
      <button class="ctrl-btn sm" style="margin-top:8px" :disabled="!importText.trim()" @click="parseImport">{{ t('lm.recognize') }}</button>
      <div v-if="importPreview" class="lm-prev">
        <div class="lm-prev-ok">{{ t('lm.found', { n: importPreview.valid.length }) }}
          <template v-if="importPreview.dup"> · {{ t('lm.dupSkipped', { n: importPreview.dup }) }}</template>
        </div>
        <div v-if="importPreview.invalid.length" class="lm-prev-bad">
          {{ t('lm.invalidN', { n: importPreview.invalid.length }) }}
          <div v-for="(b, i) in importPreview.invalid.slice(0, 5)" :key="i" class="lm-bad-line">{{ b.line }} — {{ b.reason }}</div>
        </div>
        <div v-if="importPreview.valid.length" class="lm-prev-list">
          <div v-for="(v, i) in importPreview.valid.slice(0, 8)" :key="i" class="lm-prev-item">✓ {{ v }}</div>
          <div v-if="importPreview.valid.length > 8" class="lm-bad-line">… +{{ importPreview.valid.length - 8 }}</div>
        </div>
      </div>
      <template #footer>
        <button class="ctrl-btn" @click="importOpen = false">{{ t('common.cancel') }}</button>
        <button class="ctrl-btn primary" :disabled="!importPreview?.valid.length" @click="doImport">{{ t('lm.importBtn', { n: importPreview?.valid.length || 0 }) }}</button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.lm { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.lm-inline { flex: none; }
.lm-toolbar { display: flex; gap: 8px; align-items: center; }
.lm-count { font-size: 11px; color: var(--t3); }
.lm-empty-hint { font-style: normal; }
.lm-list { border: 1px solid var(--bd); border-radius: 8px; max-height: 220px; overflow-y: auto; background: var(--bg2); }
.lm-row { display: flex; gap: 8px; align-items: center; padding: 5px 8px; border-bottom: 1px solid var(--bd); font-size: 12px; }
.lm-row:last-child { border-bottom: none; }
.lm-idx { color: var(--t3); font-size: 10px; width: 18px; text-align: right; flex: none; font-variant-numeric: tabular-nums; }
.lm-val { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--t1); font-family: 'SF Mono', Consolas, monospace; font-size: 11px; }
.lm-del { border: none; background: none; color: var(--t3); cursor: pointer; font-size: 12px; padding: 2px 4px; flex: none; }
.lm-del:hover { color: var(--ac); }
.lm-edit { flex: 1; background: var(--bg3); color: var(--t1); border: 1px solid var(--ac); border-radius: 6px; padding: 4px 8px; font-size: 12px; font-family: 'SF Mono', Consolas, monospace; }
.lm-tip { font-size: 12px; color: var(--t3); margin-bottom: 8px; }
.lm-ta { width: 100%; background: var(--bg3); color: var(--t1); border: 1px solid var(--bd); border-radius: 8px; padding: 10px; font-size: 12px; font-family: 'SF Mono', Consolas, monospace; resize: vertical; }
.lm-ta:focus { outline: none; border-color: var(--ac); }
.lm-prev { margin-top: 10px; border-top: 1px dashed var(--bd); padding-top: 8px; }
.lm-prev-ok { font-size: 13px; color: var(--success); font-weight: 600; }
.lm-prev-bad { font-size: 12px; color: var(--warning); margin-top: 4px; }
.lm-bad-line { font-size: 11px; color: var(--t3); font-family: 'SF Mono', Consolas, monospace; }
.lm-prev-list { margin-top: 6px; max-height: 140px; overflow-y: auto; }
.lm-prev-item { font-size: 11px; color: var(--t2); font-family: 'SF Mono', Consolas, monospace; padding: 1px 0; }
/* 按钮（.ctrl-btn 全局无定义，本组件自绘——修复批量导入/添加一条等按钮渲染成浏览器默认白底） */
.ctrl-btn { height: 32px; padding: 0 12px; line-height: 30px; font-size: 13px; background: var(--bg2); color: var(--t2); border: 1px solid var(--bd); border-radius: var(--rs); cursor: pointer; box-sizing: border-box; white-space: nowrap; transition: all .15s; font-family: inherit; }
.ctrl-btn:hover { border-color: var(--bd2); color: var(--t1); }
.ctrl-btn.primary { background: var(--ac); color: #fff; border-color: var(--ac); }
.ctrl-btn.primary:hover { filter: brightness(1.08); }
.ctrl-btn.primary:disabled { opacity: .5; cursor: wait; }
.ctrl-btn.sm { padding: 0 8px; font-size: 12px; }
</style>
