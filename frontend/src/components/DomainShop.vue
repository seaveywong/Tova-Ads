<script setup>
// 域名商店（2026-09-24 并入投放链接页第三 Tab）：买域名 / 我的域名 / 订单。
// 订单含 USDT 到账监听态（payment_detected：TronGrid 链上检测 → 超管一键确认 → 自动注册）。
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { GET, POST } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { isSuperadminSync } from '../router'
import QRCode from 'qrcode'

const isSuper = isSuperadminSync()
const { t } = useI18n()
const sec = ref('buy')

// ── 买域名：候选推送（指定/智能/随机 × 后缀多选 × 价格段；价目表驱动秒回，下单实时核验） ──
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
const shopPriceMax = ref(0)
const SHOP_PRICE_OPTS = computed(() => [
  { v: 0, label: t('landing.shopPriceAny') },
  { v: 2, label: '≤$2' }, { v: 5, label: '≤$5' }, { v: 10, label: '≤$10' }, { v: 20, label: '≤$20' },
])
const shopResults = ref([])
const shopSuggesting = ref(false)
const shopSearchedOnce = ref(false)
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
    shopSearchedOnce.value = true
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  shopSuggesting.value = false
}
const shopOrdering = ref('')
const orderDomain = async (d) => {
  if (shopOrdering.value) return
  shopOrdering.value = d
  try {
    const q = await GET('/domains-shop/check?domain=' + encodeURIComponent(d), 30000)
    if (!q.available) {
      ElMessage.warning(t('domains.takenNow', { d }))
      shopResults.value = shopResults.value.filter(r => r.domain !== d)
      return
    }
    await ElMessageBox.confirm(t('landing.shopOrderConfirm', { d }), t('landing.shopOrderBtn'), { type: 'info', confirmButtonText: t('landing.shopOrderBtn'), cancelButtonText: t('common.cancel') })
    const r = await POST('/domains-shop/orders', { domain: d, years: 1 })
    sec.value = 'orders'
    await loadOrders()
    const no = (orders.value || []).find(x => x.id === r.id)
    if (no) await openPayPanel(no)
    else ElMessage.success(t('domains.orderedPay', { v: r.pay_amount || r.total_usd }))
  } catch (e) { if (e !== 'cancel') ElMessage.error(e.message || t('common.opFail')) }
  shopOrdering.value = ''
}

// ── 我的域名：已购 + 外部自有合并 ──
const myDomains = ref([])
const myLoading = ref(false)
const loadMyDomains = async () => {
  myLoading.value = true
  try { myDomains.value = await GET('/landing-lib/domains') } catch {}
  myLoading.value = false
}
const srcLabel = (s) => s === 'purchased' ? t('domains.srcPurchased') : t('domains.srcOwn')

// ── 域名工作台（批TT）：域视角展开——子域清单×在用页×健康 ──
const expandedDomain = ref('')
const toggleDomain = (d) => { expandedDomain.value = expandedDomain.value === d.domain ? '' : d.domain }
const hasSubs = (d) => (d.subdomains || []).length > 0
const zoneTxt = (d) => d.cf_zone_status === 'active' ? t('domains.zoneActive')
  : d.cf_zone_status ? `${t('domains.zonePending')} (${d.cf_zone_status})` : '—'

// ── 订单：USDT 监听态 + 超管确认 ──
const orders = ref([])
const payInfo = ref({})
const ordersLoading = ref(false)
const orderBusy = ref(0)
const loadOrders = async () => {
  ordersLoading.value = true
  try { const r = await GET('/domains-shop/orders'); orders.value = r.orders || []; payInfo.value = r.payment || {} } catch {}
  ordersLoading.value = false
}
const stLabel = (st) => ({ pending_payment: t('landing.shStPending'), payment_detected: t('domains.stDetected'), approved: t('landing.shStApproved'), registering: t('landing.shStReg'), registered: t('landing.shStRegd'), bound: t('landing.shStBound'), failed: t('landing.shStFailed'), cancelled: t('landing.shStCancel') }[st] || st)
const stClass = (st) => st === 'bound' ? 'bound' : st === 'failed' ? 'failed' : ['pending_payment', 'approved', 'registering', 'payment_detected'].includes(st) ? (st === 'payment_detected' ? 'detected' : 'wait') : ''
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
// ── 支付面板（业界发票模式：唯一金额+二维码+复制+状态轮询）──
const payPanel = ref(null)   // { id, domain, pay_amount, txid, status }
const payQr = ref('')
const openPayPanel = async (o) => {
  payPanel.value = { id: o.id, domain: o.domain, pay_amount: o.pay_amount, payment_txid: o.payment_txid, status: o.status,
                     payment_address: o.payment_address || payInfo.value.address || '' }
  // TRON URI（TokenPocket/TronLink 扫码识别）：tron:地址?token=USDT&amount=应付
  // 地址用本单池分配的专属地址（多地址收款池——分散资金流+防串单）
  const uri = `tron:${payPanel.value.payment_address}?token=USDT&amount=${o.pay_amount}`
  try { payQr.value = await QRCode.toDataURL(uri, { width: 190, margin: 1 }) } catch { payQr.value = '' }
}
const copyVal = (v, label) => {
  navigator.clipboard?.writeText(String(v))
  ElMessage.success(label)
}
let _payTimer = null
const _armPoll = () => {   // 有待付/待确认单时 8s 轮询（到账监听 2min 一轮，前端更快感知）
  const need = (orders.value || []).some(o => ['pending_payment', 'payment_detected'].includes(o.status))
  if (need && !_payTimer) _payTimer = setInterval(loadOrders, 8000)
  else if (!need && _payTimer) { clearInterval(_payTimer); _payTimer = null }
}
watch(orders, _armPoll, { deep: false })
watch(orders, () => {   // 轮询刷新后同步面板状态（到账自动变绿）
  if (!payPanel.value) return
  const o = (orders.value || []).find(x => x.id === payPanel.value.id)
  if (o) { payPanel.value.status = o.status; payPanel.value.pay_amount = o.pay_amount; payPanel.value.payment_txid = o.payment_txid }
}, { deep: false })
onUnmounted(() => { if (_payTimer) clearInterval(_payTimer) })
const copyPay = () => {
  navigator.clipboard?.writeText((payPanel.value?.payment_address) || payInfo.value.address || '')
  ElMessage.success(t('domains.payCopied'))
}
const pendingCount = computed(() => (orders.value || []).filter(o => ['pending_payment', 'payment_detected'].includes(o.status)).length)
onMounted(() => { loadOrders(); loadMyDomains() })
</script>

<template>
  <div class="dshop">
    <div class="list-bar">
      <div class="seg-bar">
        <button class="seg-btn" :class="{ on: sec === 'buy' }" @click="sec = 'buy'">{{ t('domains.tabBuy') }}</button>
        <button class="seg-btn" :class="{ on: sec === 'mine' }" @click="sec = 'mine'; loadMyDomains()">{{ t('domains.tabMine') }} <i v-if="myDomains.length" class="seg-cnt">{{ myDomains.length }}</i></button>
        <button class="seg-btn" :class="{ on: sec === 'orders' }" @click="sec = 'orders'; loadOrders()">{{ t('domains.tabOrders') }} <i v-if="pendingCount" class="seg-cnt hot">{{ pendingCount }}</i></button>
      </div>
    </div>

    <!-- 买域名 -->
    <div v-if="sec === 'buy'" class="card">
      <div class="ds-search">
        <input v-model="shopDomain" class="ds-input" :placeholder="t('landing.shopPh')" @keyup.enter="suggestDomains" />
        <button class="ctrl-btn primary" :disabled="shopSuggesting" @click="suggestDomains">{{ shopSuggesting ? t('common.loading') : t('landing.shopSearch') }}</button>
      </div>
      <div class="ds-filters">
        <div class="seg-bar">
          <button v-for="m in SHOP_MODES" :key="m.id" class="seg-btn" :class="{ on: shopMode === m.id }" @click="shopMode = m.id">{{ m.label }}</button>
        </div>
        <div class="ds-chip-row">
          <button v-for="tl in SHOP_TLD_POOL" :key="tl" :class="['tld-chip', { on: shopTlds.includes(tl) }]" @click="toggleTld(tl)">.{{ tl }}</button>
        </div>
        <div class="ds-chip-row">
          <span class="ds-label">{{ t('landing.shopPrice') }}</span>
          <button v-for="o in SHOP_PRICE_OPTS" :key="o.v" :class="['tld-chip', { on: shopPriceMax === o.v }]" @click="shopPriceMax = o.v">{{ o.label }}</button>
        </div>
      </div>
      <div v-loading="shopSuggesting" class="ds-results">
        <div v-for="r in shopResults" :key="r.domain" class="ds-row">
          <span class="ds-dom">{{ r.domain }}</span>
          <span class="ds-price"><b>${{ r.total_usd }}</b><i v-if="isSuper" class="ds-cost-brk" :title="t('domains.costBrkTip')">（${{ r.cost_usd }}+${{ r.fee_usd }}）</i></span>
          <button class="ctrl-btn sm primary" :disabled="shopOrdering === r.domain" @click="orderDomain(r.domain)">{{ shopOrdering === r.domain ? t('common.loading') : t('landing.shopOrderBtn') }}</button>
        </div>
        <div v-if="!shopSuggesting && shopResults.length" class="ds-note">{{ t('domains.listNote') }}</div>
        <div v-else-if="!shopSuggesting && !shopResults.length" class="ds-empty">{{ shopSearchedOnce ? t('landing.shopEmpty') : t('landing.shopIntro') }}</div>
      </div>
    </div>

    <!-- 我的域名（域名工作台·域视角：每域展开看子域×页×健康） -->
    <div v-if="sec === 'mine'" class="card" v-loading="myLoading">
      <div v-for="d in myDomains" :key="d.id" class="dom-wb" :class="{ open: expandedDomain === d.domain }">
        <div class="dom-wb-head" @click="toggleDomain(d)">
          <span class="dw-caret">{{ expandedDomain === d.domain ? '▾' : '▸' }}</span>
          <span class="ds-dom">{{ d.domain }}</span>
          <span :class="['src-tag', d.source]">{{ srcLabel(d.source) }}</span>
          <span :class="['zone-chip', d.cf_zone_status === 'active' ? 'ok' : 'warn']">{{ zoneTxt(d) }}</span>
          <span v-if="d.blocked" class="zone-chip fb-block">FB 屏蔽</span>
          <span class="ds-usage">{{ t('domains.usedBy', { n: d.usage_count || 0 }) }}</span>
          <span v-if="hasSubs(d)" class="dw-sub-count">{{ (d.subdomains || []).length }} 子域</span>
        </div>
        <div v-if="expandedDomain === d.domain" class="dom-wb-body">
          <div v-if="hasSubs(d)" class="dw-subs">
            <div v-for="sub in d.subdomains" :key="sub.host" class="dw-sub-row" @click="$router.push({ name: 'landing', query: { edit: sub.page_id } })">
              <span class="dw-host mono">{{ sub.host }}</span>
              <span class="dw-arrow">→</span>
              <span class="dw-page">{{ sub.page_title }}</span>
            </div>
          </div>
          <div v-if="d.usage_count && !hasSubs(d)" class="dw-pages-fallback">
            <span v-for="u in (d.used_by || [])" :key="u.id" class="ds-pages">{{ u.title }}</span>
          </div>
          <div v-if="!d.usage_count" class="dw-no-use">{{ t('domains.noUse') }}</div>
          <div class="dw-actions">
            <button class="ctrl-btn sm" @click.stop="sec = 'buy'">{{ t('domains.goBuy') }}</button>
          </div>
        </div>
      </div>
      <div v-if="!myDomains.length && !myLoading" class="ds-empty">{{ t('domains.noMine') }}<button class="ctrl-btn sm" style="margin-left:10px" @click="sec = 'buy'">{{ t('domains.goBuy') }}</button></div>
    </div>

    <!-- 订单 -->
    <div v-if="sec === 'orders'" class="card" v-loading="ordersLoading">
      <div v-if="payInfo.address && !payPanel" class="pay-box">
        <span class="pay-label">{{ t('domains.payTo') }}</span>
        <span v-if="(payInfo.addresses?.length || 1) > 1" class="pay-addr mono">{{ t('domains.payPoolN', { n: payInfo.addresses.length }) }}</span>
        <span v-else class="pay-addr mono" @click="copyPay">{{ payInfo.chain }} · {{ payInfo.address }}</span>
        <button v-if="(payInfo.addresses?.length || 1) === 1" class="ctrl-btn sm" @click="copyPay">{{ t('common.copy') }}</button>
      </div>
      <div v-if="payPanel" class="invoice">
        <div class="inv-qr-wrap">
          <img v-if="payQr" :src="payQr" class="inv-qr" alt="QR" />
          <div class="inv-qr-hint">{{ t('domains.scanPay') }}</div>
        </div>
        <div class="inv-body">
          <div class="inv-row"><span class="inv-k">{{ t('domains.payDomain') }}</span><b>{{ payPanel.domain }}</b></div>
          <div class="inv-row"><span class="inv-k">{{ t('domains.payAmtLabel') }}</span>
            <b class="inv-amt" @click="copyVal(payPanel.pay_amount, t('domains.amtCopied'))" :title="t('domains.payAmtTip')">${{ payPanel.pay_amount }} <i>⧉</i></b></div>
          <div class="inv-row"><span class="inv-k">{{ t('settings.rgPayAddr') }}</span>
            <span class="pay-addr mono" @click="copyPay">{{ payPanel.payment_address || payInfo.address }}</span>
            <button class="ctrl-btn sm" @click="copyPay">{{ t('common.copy') }}</button></div>
          <div v-if="payInfo.pay_note" class="inv-note">{{ payInfo.pay_note }}</div>
          <div :class="['inv-status', stClass(payPanel.status)]">{{ ['pending_payment', 'payment_detected'].includes(payPanel.status) ? (payPanel.status === 'payment_detected' ? t('domains.stDetected') : t('domains.waitingPay')) : stLabel(payPanel.status) }}</div>
          <a v-if="payPanel.payment_txid" class="ds-tx mono" :href="'https://tronscan.org/#/transaction/' + payPanel.payment_txid" target="_blank">TXID ↗</a>
          <div class="inv-note">{{ t('domains.payAutoDetect') }}</div>
          <button class="ctrl-btn sm" style="margin-top:6px" @click="payPanel = null">{{ t('common.close') }}</button>
        </div>
      </div>
      <div v-for="o in orders" :key="o.id" class="ds-row dom">
        <span class="ds-dom">{{ o.domain }}</span>
        <span v-if="isSuper && o.team" class="ds-team" :title="o.created_by_name">{{ o.team }}<template v-if="o.created_by_name"> · {{ o.created_by_name.split('@')[0] }}</template></span>
        <span :class="['st-chip', stClass(o.status)]">{{ stLabel(o.status) }}</span>
        <span class="ds-pay" :title="t('domains.payAmtTip')">{{ ['pending_payment', 'payment_detected'].includes(o.status) ? t('domains.payAmt', { v: o.pay_amount }) : '$' + o.total_usd }}</span>
        <a v-if="o.payment_txid" class="ds-tx mono" :href="'https://tronscan.org/#/transaction/' + o.payment_txid" target="_blank" :title="o.payment_txid">TXID ↗</a>
        <span class="ds-time">{{ o.created_at }}</span>
        <button v-if="['pending_payment', 'payment_detected'].includes(o.status)" class="ctrl-btn sm" @click="openPayPanel(o); payPanel.status = o.status; payPanel.payment_txid = o.payment_txid">{{ t('domains.payBtn') }}</button>
        <button v-if="['pending_payment', 'payment_detected', 'failed'].includes(o.status) && isSuper" class="ctrl-btn sm primary" :disabled="orderBusy === o.id" @click="approveOrder(o)">{{ orderBusy === o.id ? t('common.loading') : t('domains.approve') }}</button>
        <button v-if="o.status === 'pending_payment'" class="ctrl-btn sm" @click="cancelOrder(o)">{{ t('common.cancel') }}</button>
        <span v-if="o.status === 'failed' && o.error" class="ds-err" :title="o.error">⚠</span>
      </div>
      <div v-if="!orders.length && !ordersLoading" class="ds-empty">{{ t('landing.shopNoOrders') }}<button class="ctrl-btn sm" style="margin-left:10px" @click="sec = 'buy'">{{ t('domains.goBuy') }}</button></div>
    </div>
  </div>
</template>

<style scoped>
.dshop { display: flex; flex-direction: column; gap: 12px; }
.card { background: var(--bg2); border: 1px solid var(--bd); border-radius: 10px; padding: 16px 18px; }
.ds-search { display: flex; gap: 8px; align-items: center; }
.ds-input { flex: 1; background: var(--bg3); color: var(--t1); border: 1px solid var(--bd); border-radius: 8px; padding: 8px 14px; font-size: 13px; font-family: var(--font); }
.ds-input:focus { outline: none; border-color: var(--ac); }
.ds-filters { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
.ds-chip-row { display: flex; gap: 5px; flex-wrap: wrap; align-items: center; }
.ds-label { font-size: 11px; color: var(--t3); margin-right: 3px; }
.tld-chip { padding: 2px 9px; border: 1px solid var(--bd); background: var(--bg2); color: var(--t3); border-radius: 10px; font-size: 11px; cursor: pointer; font-family: inherit; transition: all .12s; }
.tld-chip:hover { color: var(--t1); border-color: var(--bd2); }
.tld-chip.on { background: var(--acg); color: var(--ac); border-color: var(--ac); }
.ds-results { margin-top: 8px; min-height: 60px; }
.ds-row { display: flex; gap: 14px; align-items: center; padding: 10px 6px; border-bottom: 1px solid var(--bd); font-size: 13px; flex-wrap: wrap; }
.ds-team { font-size: 11px; color: var(--t3); background: var(--bg3); border-radius: 6px; padding: 1px 8px; white-space: nowrap; max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.ds-cost-brk { font-style: normal; font-size: 10px; color: var(--t3); margin-left: 2px }
.ds-row:last-child { border-bottom: none; }
.ds-dom { font-weight: 600; color: var(--t1); font-size: 14px; flex: 1; min-width: 160px; }
.ds-price { color: var(--t3); font-variant-numeric: tabular-nums; }
.ds-price i { font-style: normal; font-size: 11px; }
.ds-price b { color: var(--t1); }
.ds-note { padding: 8px 4px 2px; font-size: 11px; color: var(--t3); }
.ds-empty { text-align: center; color: var(--t3); font-size: 13px; padding: 26px 10px; }
.src-tag { font-size: 10px; padding: 1px 8px; border-radius: 9px; }
.src-tag.purchased { background: rgba(10,132,255,.12); color: var(--ac); }
.src-tag.custom { background: var(--bg3); color: var(--t3); }
.zone-chip { font-size: 11px; padding: 1px 8px; border-radius: 9px; }
.zone-chip.ok { background: rgba(48,209,88,.13); color: var(--success); }
.zone-chip.warn { background: rgba(255,159,10,.13); color: var(--warning); }
.ds-usage { font-size: 12px; color: var(--t2); }
.ds-pages { font-size: 11px; color: var(--t3); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.st-chip { font-size: 11px; padding: 1px 8px; border-radius: 9px; background: var(--bg3); color: var(--t2); white-space: nowrap; }
.st-chip.bound { background: rgba(48,209,88,.13); color: var(--success); }
.st-chip.failed { background: rgba(255,69,58,.13); color: var(--error); }
.st-chip.wait { background: rgba(255,159,10,.13); color: var(--warning); }
.st-chip.detected { background: rgba(10,132,255,.15); color: var(--ac); font-weight: 600; }
.ds-pay { font-variant-numeric: tabular-nums; color: var(--t1); font-weight: 600; }
.ds-tx { font-size: 11px; color: var(--ac); text-decoration: none; }
.ds-tx:hover { text-decoration: underline; }
.ds-time { font-size: 11px; color: var(--t3); margin-left: auto; }
.ds-err { color: var(--error); cursor: help; }
.pay-box { display: flex; gap: 10px; align-items: center; padding: 8px 10px; margin-bottom: 10px; background: rgba(10,132,255,.06); border: 1px solid rgba(10,132,255,.25); border-radius: 8px; flex-wrap: wrap; }
.pay-label { font-size: 12px; font-weight: 600; color: var(--t1); }
.dom-wb { border-bottom: 1px solid var(--bd); }
.dom-wb:last-child { border-bottom: none; }
.dom-wb-head { display: flex; gap: 12px; align-items: center; padding: 10px 6px; cursor: pointer; flex-wrap: wrap; }
.dom-wb-head:hover { background: var(--bg3); }
.dw-caret { color: var(--t3); font-size: 11px; width: 14px; flex: none; }
.dw-sub-count { font-size: 11px; color: var(--ac); }
.dom-wb-body { padding: 0 6px 12px 28px; display: flex; flex-direction: column; gap: 8px; }
.dw-subs { display: flex; flex-direction: column; gap: 2px; }
.dw-sub-row { display: flex; gap: 10px; align-items: center; padding: 5px 8px; border-radius: 6px; cursor: pointer; font-size: 12px; }
.dw-sub-row:hover { background: var(--acg); }
.dw-host { color: var(--ac); min-width: 200px; }
.dw-arrow { color: var(--t3); }
.dw-page { color: var(--t1); }
.dw-pages-fallback { display: flex; gap: 8px; flex-wrap: wrap; }
.dw-no-use { font-size: 12px; color: var(--t3); }
.dw-actions { display: flex; gap: 8px; }
.zone-chip.fb-block { background: var(--error); color: #fff; }
.pay-addr { font-size: 12px; color: var(--ac); word-break: break-all; cursor: pointer; }
.invoice { display: flex; gap: 18px; padding: 14px; margin-bottom: 10px; background: var(--bg3); border: 1px solid var(--bd); border-radius: 10px; flex-wrap: wrap; }
.inv-qr-wrap { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.inv-qr { width: 190px; height: 190px; background: #fff; border-radius: 8px; padding: 6px; }
.inv-qr-hint { font-size: 11px; color: var(--t3); }
.inv-body { flex: 1; min-width: 260px; display: flex; flex-direction: column; gap: 8px; justify-content: center; }
.inv-row { display: flex; gap: 10px; align-items: center; font-size: 13px; flex-wrap: wrap; }
.inv-k { font-size: 12px; color: var(--t3); min-width: 64px; }
.inv-amt { color: var(--t1); font-size: 18px; cursor: pointer; font-variant-numeric: tabular-nums; }
.inv-amt i { font-style: normal; font-size: 12px; color: var(--ac); }
.inv-note { font-size: 11px; color: var(--t3); }
.inv-status { font-size: 12px; font-weight: 600; padding: 4px 10px; border-radius: 9px; align-self: flex-start; background: rgba(255,159,10,.13); color: var(--warning); }
.inv-status.payment_detected { background: rgba(10,132,255,.15); color: var(--ac); }
.inv-status.bound { background: rgba(48,209,88,.13); color: var(--success); }
.inv-status.failed { background: rgba(255,69,58,.13); color: var(--error); }
.inv-status.cancelled { background: var(--bg3); color: var(--t3); }
/* 按钮（.ctrl-btn 全局无定义，本组件自绘——修复所有按钮渲染成浏览器默认白底样式） */
.ctrl-btn { height: 32px; padding: 0 12px; line-height: 30px; font-size: 13px; background: var(--bg2); color: var(--t2); border: 1px solid var(--bd); border-radius: var(--rs); cursor: pointer; box-sizing: border-box; white-space: nowrap; transition: all .15s; font-family: inherit; }
.ctrl-btn:hover { border-color: var(--bd2); color: var(--t1); }
.ctrl-btn.primary { background: var(--ac); color: #fff; border-color: var(--ac); }
.ctrl-btn.primary:hover { filter: brightness(1.08); }
.ctrl-btn.primary:disabled { opacity: .5; cursor: wait; }
.ctrl-btn.sm { padding: 0 8px; font-size: 12px; }
</style>
