<script setup>
// 全局搜索 Ctrl+K（2026-09-15 便捷性批）：命令面板——搜索账户/模板/落地页/表单/子码，
// 选中跳转对应页面并预筛。轻量列表在面板打开时懒拉（页面各自已有端点，不加新端点）。
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { GET } from '../api'

const { t } = useI18n()
const router = useRouter()
const open = ref(false)
const q = ref('')
const loading = ref(false)
const selIdx = ref(0)
const inputEl = ref(null)

// 数据池（打开时拉一次，本次打开期间缓存）
const pool = ref([])
const loadPool = async () => {
  if (pool.value.length) return
  loading.value = true
  const [accounts, lps, tpls, forms] = await Promise.all([
    GET('/fb/accounts').catch(() => []),
    GET('/landing/pages').catch(() => []),
    GET('/launch-templates').catch(() => []),
    GET('/form-templates/forms').catch(() => []),
  ])
  const items = []
  for (const a of (accounts || [])) {
    items.push({ icon: '📱', label: a.name || a.act_id, sub: a.act_id, type: 'account',
      go: () => router.push({ name: 'ads', query: { q: a.name || a.act_id } }) })
    items.push({ icon: '📱', label: `${a.name || a.act_id} → 广告管理器`, sub: a.act_id, type: 'adm',
      go: () => router.push({ name: 'ad-manager', query: { act: a.act_id } }) })
  }
  for (const p of (lps || [])) {
    items.push({ icon: '🔗', label: p.title, sub: (p.bound_subdomains||[])[0] || p.custom_domain || '', type: 'lp',
      go: () => router.push({ name: 'landing' }) })
  }
  for (const tp of (tpls || [])) {
    items.push({ icon: '📋', label: tp.name, sub: tp.objective || '', type: 'tpl',
      go: () => router.push({ name: 'launch-templates' }) })
  }
  for (const f of (forms || [])) {
    items.push({ icon: '📝', label: f.name, sub: '表单', type: 'form',
      go: () => router.push({ name: 'form-templates' }) })
  }
  // 快捷动作（固定条目）
  items.push({ icon: '＋', label: t('nav.dashboard'), sub: 'page', type: 'nav',
    go: () => router.push({ name: 'dashboard' }) })
  items.push({ icon: '＋', label: t('nav.landing'), sub: 'page', type: 'nav',
    go: () => router.push({ name: 'landing' }) })
  items.push({ icon: '＋', label: t('nav.tokens'), sub: 'page', type: 'nav',
    go: () => router.push({ name: 'tokens' }) })
  pool.value = items
  loading.value = false
}

const results = computed(() => {
  const s = q.value.trim().toLowerCase()
  if (!s) return pool.value.filter(x => x.type === 'nav').slice(0, 5)
  return pool.value.filter(x =>
    (x.label || '').toLowerCase().includes(s) || (x.sub || '').toLowerCase().includes(s)
  ).slice(0, 12)
})

const openPalette = () => {
  open.value = true; q.value = ''; selIdx.value = 0
  loadPool()
  nextTick(() => inputEl.value?.focus())
}
const close = () => { open.value = false }
const pick = (item) => { if (!item) return; close(); item.go() }
const onKey = (e) => {
  if (!open.value) return
  if (e.key === 'ArrowDown') { e.preventDefault(); selIdx.value = Math.min(selIdx.value + 1, results.value.length - 1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); selIdx.value = Math.max(selIdx.value - 1, 0) }
  else if (e.key === 'Enter') { e.preventDefault(); pick(results.value[selIdx.value]) }
  else if (e.key === 'Escape') close()
}
const onGlobalKey = (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); open.value ? close() : openPalette() }
}
watch(q, () => { selIdx.value = 0 })
onMounted(() => document.addEventListener('keydown', onGlobalKey))
onUnmounted(() => document.removeEventListener('keydown', onGlobalKey))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="cmdk-overlay" @click.self="close">
      <div class="cmdk">
        <div class="cmdk-head">
          <span class="cmdk-icon">🔍</span>
          <input ref="inputEl" v-model="q" class="cmdk-input" :placeholder="t('cmdk.placeholder')"
                 @keydown="onKey" />
          <span class="cmdk-esc">ESC</span>
        </div>
        <div class="cmdk-body" v-loading="loading">
          <div v-for="(r, i) in results" :key="i" :class="['cmdk-row', { sel: i === selIdx }]"
               @click="pick(r)" @mouseenter="selIdx = i">
            <span class="cmdk-row-icon">{{ r.icon }}</span>
            <span class="cmdk-row-label">{{ r.label }}</span>
            <span class="cmdk-row-sub">{{ r.sub }}</span>
          </div>
          <div v-if="!results.length && !loading && q.trim()" class="cmdk-empty">{{ t('cmdk.noResults') }}</div>
          <div v-if="!q.trim() && !loading" class="cmdk-hint">{{ t('cmdk.hint') }}</div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.cmdk-overlay { position: fixed; inset: 0; z-index: 3000; background: rgba(0,0,0,.45); display: flex; align-items: flex-start; justify-content: center; padding-top: 12vh; }
.cmdk { width: min(560px, 92vw); background: var(--bg2, #1a1b23); border: 1px solid var(--bd, #2a2e39); border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,.5); overflow: hidden; }
.cmdk-head { display: flex; align-items: center; gap: 10px; padding: 14px 16px; border-bottom: 1px solid var(--bd, #2a2e39); }
.cmdk-icon { font-size: 16px; color: var(--t3) }
.cmdk-input { flex: 1; background: transparent; border: none; outline: none; color: var(--t1, #e8eaed); font-size: 15px; font-family: inherit }
.cmdk-input::placeholder { color: var(--t3) }
.cmdk-esc { font-size: 10px; color: var(--t3); border: 1px solid var(--bd); border-radius: 4px; padding: 2px 6px; white-space: nowrap }
.cmdk-body { max-height: 380px; overflow-y: auto; padding: 6px }
.cmdk-row { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 8px; cursor: pointer; }
.cmdk-row:hover, .cmdk-row.sel { background: rgba(10,132,255,.12) }
.cmdk-row-icon { font-size: 14px; flex: none; width: 20px; text-align: center }
.cmdk-row-label { font-size: 13px; color: var(--t1, #e8eaed); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.cmdk-row-sub { font-size: 11px; color: var(--t3); white-space: nowrap; max-width: 160px; overflow: hidden; text-overflow: ellipsis }
.cmdk-empty { padding: 24px; text-align: center; color: var(--t3); font-size: 13px }
.cmdk-hint { padding: 12px; text-align: center; color: var(--t3); font-size: 11px }
</style>
