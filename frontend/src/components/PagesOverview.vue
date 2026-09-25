<script setup>
// 统一主页总览（批OO）：全租户主页一张表——归属令牌/粉丝/可投/在投广告数/模板引用 + 行内改名/分类
import { ref, computed, onMounted } from 'vue'
import { GET, POST } from '../api'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
const rows = ref([])
const loading = ref(true)
const search = ref('')
const load = async () => {
  loading.value = true
  try { rows.value = await GET('/fb/pages-overview', 60000) } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  loading.value = false
}
onMounted(load)
const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter(r => (r.name || '').toLowerCase().includes(q) || r.id.includes(q) || (r.via_cred || '').toLowerCase().includes(q))
})
const editing = ref(null)   // {id, field, value, cred_id}
const startEdit = (r, field) => {
  if (editing.value) return
  editing.value = { id: r.id, field, value: field === 'name' ? r.name : '', cred_id: r.via_cred_id, orig: field === 'name' ? r.name : '' }
}
const saveEdit = async () => {
  const ed = editing.value
  if (!ed) return
  if (ed.field === 'category' && !ed.value.trim()) { editing.value = null; return }
  try {
    const body = ed.field === 'name' ? { page_id: ed.id, name: ed.value.trim() } : { page_id: ed.id, category: ed.value.trim() }
    await POST(`/fb/credentials/${ed.cred_id}/pages/${ed.field === 'name' ? 'rename' : 'category'}`, body)
    const r = rows.value.find(x => x.id === ed.id)
    if (r && ed.field === 'name') r.name = ed.value.trim()
    ElMessage.success(t('common.saved'))
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  editing.value = null
}
const copyId = (id) => { navigator.clipboard?.writeText(id); ElMessage.success(t('dashboard.copiedVal', { val: id })) }
</script>

<template>
  <div class="pgov">
    <div class="list-bar">
      <input v-model="search" class="bar-search" :placeholder="t('pg.searchPh')" />
      <button class="ctrl-btn" :disabled="loading" @click="load">{{ loading ? t('common.loading') : t('common.refresh') }}</button>
      <span class="pg-count">{{ t('pg.total', { n: filtered.length }) }}</span>
    </div>
    <div class="card" v-loading="loading">
      <div class="pg-row pg-head-row">
        <span class="pg-name">{{ t('pg.colPage') }}</span>
        <span class="pg-col">{{ t('pg.colVia') }}</span>
        <span class="pg-col">{{ t('pg.colFans') }}</span>
        <span class="pg-col">{{ t('pg.colAds') }}</span>
        <span class="pg-col">{{ t('pg.colTpl') }}</span>
      </div>
      <div v-for="r in filtered" :key="r.id" class="pg-row">
        <span class="pg-name">
          <template v-if="editing && editing.id === r.id && editing.field === 'name'">
            <input v-model="editing.value" class="pg-edit" @keyup.enter="saveEdit" @keyup.esc="editing = null" />
            <button class="ctrl-btn sm primary" @click="saveEdit">{{ t('common.save') }}</button>
          </template>
          <template v-else>
            <span class="pg-title" :title="r.name" @dblclick="startEdit(r, 'name')" @click="copyId(r.id)">{{ r.name }}</span>
            <span class="pg-id mono" @click="copyId(r.id)" :title="t('pg.copyId')">{{ r.id }}</span>
          </template>
        </span>
        <span class="pg-col"><span class="pg-via">{{ r.via_cred }}</span></span>
        <span class="pg-col tnum">{{ r.fan_count ? r.fan_count.toLocaleString() : '—' }}</span>
        <span class="pg-col tnum" :class="{ ok: r.live_ads > 0 }">{{ r.live_ads || '—' }}</span>
        <span class="pg-col pg-tpl" :title="(r.tpl_refs || []).join('、')">
          {{ r.tpl_ref_count ? t('pg.tplN', { n: r.tpl_ref_count }) + '：' + (r.tpl_refs || []).join('、') : '—' }}
        </span>
      </div>
      <div v-if="!filtered.length && !loading" class="pg-empty">{{ search ? t('pg.noMatch') : t('pg.none') }}</div>
    </div>
  </div>
</template>

<style scoped>
.pgov { display: flex; flex-direction: column; gap: 12px; }
.card { background: var(--bg2); border: 1px solid var(--bd); border-radius: 10px; padding: 6px 14px; }
.pg-row { display: flex; gap: 12px; align-items: center; padding: 9px 4px; border-bottom: 1px solid var(--bd); font-size: 13px; }
.pg-row:last-child { border-bottom: none; }
.pg-head-row { color: var(--t3); font-size: 11px; text-transform: uppercase; letter-spacing: .03em; border-bottom: 1px solid var(--bd); }
.pg-name { flex: 1; min-width: 200px; display: flex; flex-direction: column; gap: 1px; cursor: pointer; }
.pg-title { font-weight: 600; color: var(--t1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 340px; }
.pg-id { font-size: 10px; color: var(--t3); }
.pg-col { width: 110px; flex: none; color: var(--t2); }
.pg-via { font-size: 11px; background: var(--bg3); padding: 1px 8px; border-radius: 4px; color: var(--t3); max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; }
.tnum { font-variant-numeric: tabular-nums; }
.tnum.ok { color: var(--success); font-weight: 600; }
.pg-tpl { width: 260px; font-size: 11px; color: var(--t3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pg-edit { background: var(--bg3); color: var(--t1); border: 1px solid var(--ac); border-radius: 6px; padding: 4px 8px; font-size: 13px; width: 220px; font-family: var(--font); }
.pg-count { font-size: 12px; color: var(--t3); }
.pg-empty { text-align: center; color: var(--t3); font-size: 13px; padding: 30px; }
</style>
