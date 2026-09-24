<script setup>
import { ref, computed, onMounted } from 'vue'
import { GET, POST } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { isSuperadminSync } from '../router'

const isSuper = isSuperadminSync()
const { t } = useI18n()
const tab = ref('buy')

// ── 买域名：候选推送（指定/智能/随机 × 后缀多选 × 价格段；2026-09-24 从落地页弹窗整体迁入独立页） ──
const shopDomain = ref('')
const shopMode = ref('smart')
const SHOP_MODES = computed(() => [
  { id: 'exact', label: t('landing.shopModeExact') },
  { id: 'smart', label: t('landing.shopModeSmart') },
  { id: 'random', label: t('landing.shopModeRandom') },
])
const SHOP_TLD_POOL = ['com', 'net', 'xyz', 'top', 'online', 'site', 'shop', 'store', 'icu', 'cfd', 'link', 'fun', 'rest', 'world', 'live', 'click']
const shopTlds = ref(['com', 'net', 'xyz', 'top', 'online', 'site', 'shop', 'store'])
const toggleTld = (tl) => {
  const s = new Set(shopTlds.value)
  s.has(tl) ? s.delete(tl) : s.add(tl)
  shopTlds.value = [...s]
}
const shopPriceMax = ref(0)   // 0=不限
const SHOP_PRICE_OPTS = computed(() => [
  { v: 0, label: t('landing.shopPriceAny') },
  { v: 2, label: '≤$2' }, { v: 5, label: '≤$5' }, { v: 10, label: '≤$10' }, { v: 20, label: '≤$20' },
])
const shopResults = ref([])
const shopSuggesting = ref(false)
const shopSearchedOnce = ref(false)
const shopStats = ref({ searched: 0, taken: 0 })
const shopOrdering = ref('')
const suggestDomains = async () => {
  if (shopSuggesting.value) return
  if (shopMode.value !== 'random' && !shopDomain.value.trim()) return ElMessage.warning(t('landing.shopNeedWord'))
  if (!shopTlds.value.length) return ElMessage.warning(t('landing.shopNeedTld'))
  shopSuggesting.value = true; shopResults.value = []
  try {
    const p = new URLSearchParams({ q: shopDomain.value.trim(), mode: shopMode.value, tlds: shopTlds.value.join(','), limit: '30' })
    if (shopPriceMax.value) p.set('price_max', String(shopPriceMax.value))
    const r = await GET('/domains-shop/suggest?' + p.toString(), 90000)
    shopResults.value = r.results || []
    shopStats.value = { searched: r.searched || 0, taken: r.taken || 0 }
    shopSearchedOnce.value = true
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  shopSuggesting.value = false
}
const orderDomain = async (d) => {
  if (shopOrdering.value) return
  try {
    await ElMessageBox.confirm(t('landing.shopOrderConfirm', { d, v: '' }), t('landing.shopOrderBtn'), { type: 'info', confirmButtonText: t('landing.shopOrderBtn'), cancelButtonText: t('common.cancel') })
  } catch { return }
  shopOrdering.value = d
  try {
    await POST('/domains-shop/orders', { domain: d, years: 1 })
    ElMessage.success(t('landing.shopOrdered'))
    tab.value = 'orders'
    await loadOrders()
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  shopOrdering.value = ''
}

// ── 我的域名：已购 + 外部自有合并视图（交付状态/zone 状态/使用情况一体） ──
const myDomains = ref([])
const myLoading = ref(false)
const loadMyDomains = async () => {
  myLoading.value = true
  try { myDomains.value = await GET('/landing-lib/domains') } catch {}
  myLoading.value = false
}
const srcLabel = (s) => s === 'purchased' ? t('domains.srcPurchased') : t('domains.srcOwn')
const zoneTxt = (d) => d.cf_zone_status === 'active' ? t('domains.zoneActive')
  : d.cf_zone_status ? `${t('domains.zonePending')} (${d.cf_zone_status})` : '—'

// ── 订单：状态机时间线 + 超管确认收款 + 取消 ──
const orders = ref([])
const ordersLoading = ref(false)
const orderBusy = ref(0)
const loadOrders = async () => {
  ordersLoading.value = true
  try { orders.value = await GET('/domains-shop/orders') } catch {}
  ordersLoading.value = false
}
const stLabel = (st) => ({ pending_payment: t('landing.shStPending'), approved: t('landing.shStApproved'), registering: t('landing.shStReg'), registered: t('landing.shStRegd'), bound: t('landing.shStBound'), failed: t('landing.shStFailed'), cancelled: t('landing.shStCancel') }[st] || st)
const stClass = (st) => ['pending_payment', 'approved', 'registering'].includes(st) ? 'wait' : st
const cancelOrder = async (o) => {
  try {
    await ElMessageBox.confirm(t('landing.shCancelConfirm', { d: o.domain }), t('common.confirm'), { type: 'warning' })
    await POST('/domains-shop/orders/' + o.id + '/cancel', {})
    await loadOrders()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e.message || t('common.opFail')) }
}
const approveOrder = async (o) => {
  orderBusy.value = o.id
  try {
    const r = await POST('/domains-shop/orders/' + o.id + '/approve', {}, 120000)
    ElMessage.success(t('domains.approveOk', { d: r.domain || o.domain }))
    await Promise.all([loadOrders(), loadMyDomains()])
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  orderBusy.value = 0
}
const pendingCount = computed(() => (orders.value || []).filter(o => o.status === 'pending_payment').length)

onMounted(() => { loadOrders(); loadMyDomains() })
</script>

<template>
  <div class="page">
    <div class="lp-tabs">
      <div :class="['lp-tab', { on: tab === 'buy' }]" @click="tab = 'buy'">{{ t('domains.tabBuy') }}</div>
      <div :class="['lp-tab', { on: tab === 'mine' }]" @click="tab = 'mine'; loadMyDomains()">{{ t('domains.tabMine') }}<span v-if="myDomains.length" class="tab-cnt">{{ myDomains.length }}</span></div>
      <div :class="['lp-tab', { on: tab === 'orders' }]" @click="tab = 'orders'; loadOrders()">{{ t('domains.tabOrders') }}<span v-if="pendingCount" class="tab-cnt warn">{{ pendingCount }}</span></div>
    </div>

    <!-- 买域名 -->
    <div v-if="tab === 'buy'" class="card buy-card">
      <div class="shop-search">
        <input v-model="shopDomain" class="shop-input" :placeholder="t('landing.shopPh')" @keyup.enter="suggestDomains" />
        <button class="btn primary" :disabled="shopSuggesting" @click="suggestDomains">{{ shopSuggesting ? t('common.loading') : t('landing.shopSearch') }}</button>
      </div>
      <div class="shop-filters">
        <div class="seg-bar">
          <button v-for="m in SHOP_MODES" :key="m.id" :class="['seg-btn', { on: shopMode === m.id }]" @click="shopMode = m.id">{{ m.label }}</button>
        </div>
        <div class="chip-row">
          <button v-for="tl in SHOP_TLD_POOL" :key="tl" :class="['tld-chip', { on: shopTlds.includes(tl) }]" @click="toggleTld(tl)">.{{ tl }}</button>
        </div>
        <div class="chip-row">
          <span class="sf-label">{{ t('landing.shopPrice') }}</span>
          <button v-for="o in SHOP_PRICE_OPTS" :key="o.v" :class="['tld-chip', { on: shopPriceMax === o.v }]" @click="shopPriceMax = o.v">{{ o.label }}</button>
        </div>
      </div>
      <div v-loading="shopSuggesting" class="shop-results">
        <div v-for="r in shopResults" :key="r.domain" class="shop-row">
          <span class="sr-dom">{{ r.domain }}</span>
          <span class="sr-via">{{ r.via_cred }}</span>
          <span class="sr-price">${{ r.cost_usd }} <i>+ ${{ r.fee_usd }}</i> = <b>${{ r.total_usd }}</b></span>
          <button class="btn sm primary" :disabled="shopOrdering === r.domain" @click="orderDomain(r.domain)">{{ shopOrdering === r.domain ? t('common.loading') : t('landing.shopOrderBtn') }}</button>
        </div>
        <div v-if="!shopSuggesting && shopResults.length" class="shop-stats">{{ t('landing.shopStats', { s: shopStats.searched, a: shopResults.length }) }}</div>
        <div v-else-if="!shopSuggesting && !shopResults.length" class="shop-empty">{{ shopSearchedOnce ? t('landing.shopEmpty') : t('landing.shopIntro') }}</div>
      </div>
    </div>

    <!-- 我的域名 -->
    <div v-if="tab === 'mine'" class="card" v-loading="myLoading">
      <div v-for="d in myDomains" :key="d.id" class="dom-row">
        <span class="dom-name">{{ d.domain }}</span>
        <span :class="['src-tag', d.source]">{{ srcLabel(d.source) }}</span>
        <span :class="['zone-chip', d.cf_zone_status === 'active' ? 'ok' : 'warn']">{{ zoneTxt(d) }}</span>
        <span class="dom-usage">{{ t('domains.usedBy', { n: d.usage_count || 0 }) }}</span>
        <span v-if="d.usage_count" class="dom-pages" :title="(d.used_by || []).map(u => u.title).join('、')">{{ (d.used_by || []).map(u => u.title).slice(0, 3).join('、') }}{{ (d.used_by || []).length > 3 ? '…' : '' }}</span>
      </div>
      <div v-if="!myDomains.length && !myLoading" class="shop-empty">{{ t('domains.noMine') }}<button class="btn sm" style="margin-left:10px" @click="tab = 'buy'">{{ t('domains.goBuy') }}</button></div>
    </div>

    <!-- 订单 -->
    <div v-if="tab === 'orders'" class="card" v-loading="ordersLoading">
      <div v-for="o in orders" :key="o.id" class="dom-row">
        <span class="dom-name">{{ o.domain }}</span>
        <span :class="['st-chip', stClass(o.status)]">{{ stLabel(o.status) }}</span>
        <span class="sr-price">${{ o.total_usd }}</span>
        <span class="dom-time">{{ o.created_at }}</span>
        <button v-if="o.status === 'pending_payment' && isSuper" class="btn sm primary" :disabled="orderBusy === o.id" @click="approveOrder(o)">{{ orderBusy === o.id ? t('common.loading') : t('domains.approve') }}</button>
        <button v-if="o.status === 'pending_payment'" class="btn sm" @click="cancelOrder(o)">{{ t('common.cancel') }}</button>
        <span v-if="o.status === 'failed' && o.error" class="dom-err" :title="o.error">⚠</span>
      </div>
      <div v-if="!orders.length && !ordersLoading" class="shop-empty">{{ t('landing.shopNoOrders') }}</div>
    </div>
  </div>
</template>

<style scoped>
.page { width: 100%; }
.lp-tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--bd); margin-bottom: 14px; padding-left: 4px; }
.lp-tab { padding: 7px 16px; font-size: 13px; color: var(--t3); cursor: pointer; border-bottom: 2px solid transparent; display: flex; align-items: center; gap: 5px; }
.lp-tab.on { color: var(--t1); border-bottom-color: var(--ac); font-weight: 600; }
.lp-tab:hover { color: var(--t1); }
.tab-cnt { font-size: 10px; padding: 0 6px; border-radius: 8px; background: var(--bg3); color: var(--t3); line-height: 16px; }
.tab-cnt.warn { background: var(--warning); color: #fff; }
.card { background: var(--bg2); border: 1px solid var(--bd); border-radius: 10px; padding: 16px 18px; }
.buy-card { display: flex; flex-direction: column; gap: 12px; }
.shop-search { display: flex; gap: 8px; align-items: center; }
.shop-input { flex: 1; background: var(--bg3); color: var(--t1); border: 1px solid var(--bd); border-radius: 8px; padding: 9px 14px; font-size: 14px; font-family: var(--font); }
.shop-input:focus { outline: none; border-color: var(--ac); }
.shop-filters { display: flex; flex-direction: column; gap: 8px; }
.chip-row { display: flex; gap: 5px; flex-wrap: wrap; align-items: center; }
.sf-label { font-size: 11px; color: var(--t3); margin-right: 3px; }
.tld-chip { padding: 2px 9px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t3); border-radius: 10px; font-size: 11px; cursor: pointer; font-family: inherit; transition: all .12s; }
.tld-chip:hover { color: var(--t1); border-color: var(--bd2); }
.tld-chip.on { background: var(--acg); color: var(--ac); border-color: var(--ac); }
.shop-results { min-height: 80px; }
.shop-row { display: flex; gap: 14px; align-items: center; padding: 10px 6px; border-bottom: 1px solid var(--bd); font-size: 13px; }
.shop-row:last-of-type { border-bottom: none; }
.sr-dom { font-weight: 600; color: var(--t1); font-size: 14px; flex: 1; min-width: 0; }
.sr-via { font-size: 11px; color: var(--t3); background: var(--bg3); padding: 1px 8px; border-radius: 4px; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sr-price { color: var(--t3); font-variant-numeric: tabular-nums; }
.sr-price i { font-style: normal; font-size: 11px; }
.sr-price b { color: var(--t1); }
.shop-stats { padding: 8px 4px 2px; font-size: 11px; color: var(--t3); }
.shop-empty { text-align: center; color: var(--t3); font-size: 13px; padding: 30px 10px; }
.dom-row { display: flex; gap: 12px; align-items: center; padding: 10px 6px; border-bottom: 1px solid var(--bd); font-size: 13px; flex-wrap: wrap; }
.dom-row:last-child { border-bottom: none; }
.dom-name { font-weight: 600; color: var(--t1); font-size: 14px; min-width: 180px; }
.src-tag { font-size: 10px; padding: 1px 8px; border-radius: 9px; }
.src-tag.purchased { background: rgba(10,132,255,.12); color: var(--ac); }
.src-tag.custom { background: var(--bg3); color: var(--t3); }
.zone-chip { font-size: 11px; padding: 1px 8px; border-radius: 9px; }
.zone-chip.ok { background: rgba(48,209,88,.13); color: var(--success); }
.zone-chip.warn { background: rgba(255,159,10,.13); color: var(--warning); }
.dom-usage { font-size: 12px; color: var(--t2); }
.dom-pages { font-size: 11px; color: var(--t3); max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.st-chip { font-size: 11px; padding: 1px 8px; border-radius: 9px; background: var(--bg3); color: var(--t2); white-space: nowrap; }
.st-chip.bound { background: rgba(48,209,88,.13); color: var(--success); }
.st-chip.failed { background: rgba(255,69,58,.13); color: var(--error); }
.st-chip.wait { background: rgba(255,159,10,.13); color: var(--warning); }
.dom-time { font-size: 11px; color: var(--t3); margin-left: auto; }
.dom-err { color: var(--error); cursor: help; }
.btn { padding: 6px 14px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t1); border-radius: 6px; font-size: 13px; cursor: pointer; white-space: nowrap; font-family: inherit; }
.btn:hover { background: var(--bg3); }
.btn.primary { background: var(--ac); color: #fff; border-color: var(--ac); }
.btn.sm { padding: 3px 10px; font-size: 12px; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
</style>
