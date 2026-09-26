<script setup>
// 部署抽屉（2026-09-26 从 LaunchTemplates 抽出组件化）：选账户/主页/像素/令牌/批量素材
// → 提交部署。LaunchTemplates（卡片部署）与 AdManager（创建按钮弹窗选模板）共用。
// 用法：<DeployDrawer ref="ddRef" @submitted="onSubmitted" /> → ddRef.value.open(tpl)
// 提交成功后 emit('submitted', job_id) 由宿主页打开 JobProgressDialog。
// showPreflight(result) 供宿主页「预检」菜单借用弹窗（抽屉无需打开）。
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { GET, POST } from '../api'
import { showError } from '../composables/useError'
import { accountStatus } from '../composables/useStatus'
import { countryName } from '../composables/useCountries'

const { t } = useI18n()
const emit = defineEmits(['submitted'])

// ── 抽屉状态 ──
const deployOpen = ref(false)
const deployTpl = ref(null)
const deployAsset = ref(null)
const accounts = ref([])
const accLoading = ref(false)
const deploySearch = ref('')
const filteredDeployAccounts = computed(() => {
  const q = deploySearch.value.trim().toLowerCase()
  if (!q) return accounts.value
  return accounts.value.filter(a =>
    (a.name || '').toLowerCase().includes(q) || (a.act_id || '').includes(q)
  )
})
const selectedAccs = ref(new Set())
const accPages = ref({})  // {act_id: [pages]}
const accPixels = ref({}) // {act_id: [pixels]}
const deployItems = ref({})  // {act_id: {page_id, pixel_id}}
const deploying = ref(false)
// 模板树内指定了主页的广告节点（部署抽屉提示用——让「部署分配 vs 节点指定」优先级显式可见，
// 修复背景：节点烘焙主页曾静默压掉部署分配；现部署分配优先，跟帖节点除外）
const tplNodePages = computed(() => {
  try {
    const st = deployTpl.value?.structure ? JSON.parse(deployTpl.value.structure) : null
    if (!st?.adsets) return []
    const set = new Set()
    for (const s of st.adsets) for (const a of (s.ads || [])) if (a.page_id) set.add(a.page_id)
    return [...set]
  } catch { return [] }
})
// 像素策略（部署抽屉）：template=跟随模板（旧行为）/ random=随机用账户像素 / create=每账户新建像素
const pixelStrategy = ref('template')
// 主页权限总览（部署抽屉顶部折叠面板；懒加载——展开才拉 /leads/pages）
const pageOverviewOpen = ref(false)
const permPages = ref([])
const permPagesLoading = ref(false)
let permPagesLoaded = false
// 按素材批量生成系列（对标 FBInsider batchGenerate）：模板=母版，每个选中素材克隆一个
// 完整系列（campaign+adset+ad），系列名/广告名=素材名；模板自带素材在批量模式下被忽略
const deployMode = ref('single')   // single=单模板部署（默认，旧行为） / batch=按素材批量生成系列
const BATCH_ASSET_MAX = 200        // 批量素材上限（与后端 _validate_batch_assets 一致）
const batchAssets = ref([])        // 素材库（批量选择卡片；懒加载——首次切到批量模式才拉）
const batchAssetsLoading = ref(false)
const batchAssetIds = ref(new Set())
const batchPreview = computed(() => ({
  n: selectedAccs.value.size, m: batchAssetIds.value.size,
  total: selectedAccs.value.size * batchAssetIds.value.size,
}))
// 批量预检
const batchPreflighting = ref(false)
// 进度提示（抽屉关闭后由宿主页弹 JobProgressDialog，本组件不持有进度状态）

// ── 预检结果弹窗（本组件持有；宿主页卡片「预检」菜单借 showPreflight 用）──
const preflightResult = ref(null)
const preflightVisible = ref(false)
const showPreflight = (r) => { preflightResult.value = r; preflightVisible.value = true }

// ── 跟帖部署：按主页权限预过滤账户 ──
const reuseEligibleActs = ref(new Set())
const reuseDeployPage = computed(() => {
  if (deployTpl.value?.post_source !== 'reuse') return ''
  return (deployTpl.value?.reuse_post_ref || '').split('_')[0] || ''  // {page}_{post} → page
})
const accManagesReusePage = (actId) => reuseEligibleActs.value.has(actId)
const ttPixels = ref([])
// 结构模板：树概览（素材在树内 → 按素材批量整块隐藏；显示组数/展开广告数/启用链路/预算合计）
const deployTree = ref(null)
const deployTreeStats = computed(() => {
  if (!deployTree.value || !deployTpl.value) return null
  const isCbo = (deployTpl.value.budget_mode || 'ABO').toUpperCase() === 'CBO'
  let m = 0, chains = 0, aboTotal = 0
  for (const s of deployTree.value) {
    for (const a of (s.ads || [])) {
      const n = Math.max((a.asset_ids || []).length, 1)   // 素材组节点按素材数展开
      m += n
      if (s.enabled && a.enabled) chains += n             // 整链开启才消耗
    }
    if (!isCbo && s.enabled) aboTotal += Number(s.budget_type === 'lifetime' ? (s.lifetime_budget_usd || 0) : (s.budget_usd || deployTpl.value.budget_usd || 0))
  }
  return { n: deployTree.value.length, m, chains, isCbo,
           isLifetime: isCbo ? (deployTpl.value.budget_type || 'daily') === 'lifetime' : deployTree.value.some(s => s.enabled && s.budget_type === 'lifetime'),
           perAcc: isCbo
             ? Number((deployTpl.value.budget_type === 'lifetime'
                 ? deployTpl.value.lifetime_budget_usd : deployTpl.value.budget_usd) || 0)
             : Math.round(aboTotal * 100) / 100 }
})
// 单模式每账户日预算口径（结构模板=启用组合计/CBO 系列预算；平铺=模板预算；lifetime 用总预算额）
const singlePerAcc = computed(() => {
  if (deployTreeStats.value) return deployTreeStats.value.perAcc
  const t0 = deployTpl.value
  if (!t0) return 0
  return Number((t0.budget_type === 'lifetime' ? t0.lifetime_budget_usd : t0.budget_usd) || 0)
})
const singleIsLifetime = computed(() =>
  (deployTpl.value?.budget_type || 'daily') === 'lifetime'
  && (deployTreeStats.value ? deployTreeStats.value.isCbo : true))

// ── 打开抽屉 ──
const open = async (tpl) => {
  deployTpl.value = tpl; deployOpen.value = true; selectedAccs.value = new Set(); deployItems.value = {}
  reuseEligibleActs.value = new Set()
  // 三件套状态复位（像素策略回默认；权限总览收起+清缓存——令牌权限可能已变化，每次抽屉打开重拉）
  pixelStrategy.value = 'template'
  pageOverviewOpen.value = false; permPages.value = []
  permPagesLoaded = false; permPagesLoading.value = false
  deployAsset.value = null
  deployMode.value = 'single'; batchAssetIds.value = new Set()
  deployTree.value = null
  if (tpl.structure) { try { deployTree.value = JSON.parse(tpl.structure).adsets || null } catch { deployTree.value = null } }
  accLoading.value = true
  // 三路互不依赖——并行（原先串行 3 RTT）
  const [, allAccounts, ttPx] = await Promise.all([
    tpl.asset_id ? GET('/assets/' + tpl.asset_id).then(r => { deployAsset.value = r }).catch(() => {}) : Promise.resolve(),
    GET('/fb/accounts').catch(e => { showError(e, t('launch.loadAccFail')); return [] }),
    tpl.platform === 'tt' ? GET('/landing-lib/pixels').catch(() => []) : Promise.resolve(null),
  ])
  accounts.value = (tpl.platform === 'tt') ? (allAccounts || []).filter(a => a.platform === 'tt') : (allAccounts || []).filter(a => (a.platform || 'fb') === 'fb')
  if (tpl.platform === 'tt') ttPixels.value = (ttPx || []).filter(p => p.platform === 'tt')
  if (tpl.post_source === 'reuse' && tpl.id) {
    // 后端权威判定：候选池里有能管该帖主页的写令牌的账户才可选（多令牌同账户也覆盖）
    try { const r = await GET('/launch-templates/' + tpl.id + '/reuse-eligible'); reuseEligibleActs.value = new Set(r.eligible || []) }
    catch (e) { showError(e, t('launch.loadAccFail')) }
  }
  accLoading.value = false
}

// 同令牌主页请求共享（组件级）：主页列表是令牌级，同令牌多账户各拉一遍 = 同一 /me/accounts
// 被打 N 次；共享一个 Promise 后只发一次（后端另有 5min 缓存兜底跨会话）
const _credPagesReq = {}
const fetchCredPages = (credId) => {
  if (!_credPagesReq[credId]) _credPagesReq[credId] = GET(`/fb/credentials/${credId}/pages`).catch(() => [])
  return _credPagesReq[credId]
}
// 选中账户后拉该账户可用的主页/像素/令牌池（deployItems 填模板默认值）
const accCreds = ref({})   // {act_id: [{id, alias, available}]}——「指定令牌」下拉（2026-09-24 控制面）
const accLoadingConfig = ref(new Set())
const ensureAccConfig = async (id) => {
  // 默认值先行（accPages 早退在后）——open 每次重置 deployItems 但不清 accPages，
  // 二开抽屉再勾选已加载过主页的账户时若先早退，deployItems[id] 缺失 → 模板 v-model 直接崩
  deployItems.value[id] = { page_id: deployTpl.value.page_id || '', pixel_id: deployTpl.value.pixel_id || '', cred_id: 0 }
  if (accPages.value[id]) return
  const acc = accounts.value.find(a => a.act_id === id)
  const credId = acc?.fb_credential_id
  if (deployTpl.value?.platform === 'tt') {
    accPages.value[id] = []   // TT 无主页概念；像素下拉用共享 ttPixels（无 per-account 差异）
    return
  }
  if (credId) {
    accLoadingConfig.value.add(id); accLoadingConfig.value = new Set(accLoadingConfig.value)
    try {
      // 主页走令牌池并集端点（2026-09-24 三层完善：曾只拉绑定主令牌的页——池内其他令牌
      // 独占的主页在部署抽屉根本选不到，Roly-V21-81 案）；每页带 via_cred 归属标注
      const [pages, pixels, creds] = await Promise.all([
        GET('/launch-templates/pages?act_id=' + encodeURIComponent(id)).catch(() => []),
        GET('/fb/credentials/' + credId + '/pixels?act_id=' + encodeURIComponent(id)).catch(() => []),
        GET('/launch-templates/creds?act_id=' + encodeURIComponent(id)).catch(() => []),
      ])
      accPages.value[id] = pages; accPixels.value[id] = pixels; accCreds.value[id] = creds
      // 策略为「随机用账户像素」时，新加载池的账户立即随机填入（与已选账户保持同策略）
      if (pixelStrategy.value === 'random') {
        const pid = randomPixelFor(id)
        if (pid) deployItems.value[id] = { ...(deployItems.value[id] || {}), pixel_id: pid }
      }
    } catch {}
    accLoadingConfig.value.delete(id); accLoadingConfig.value = new Set(accLoadingConfig.value)
  }
}
// 指定令牌 → 主页下拉只显示该令牌能管的页（约束住「令牌×主页」错误组合）
const pageOptsFor = (id) => {
  const pages = accPages.value[id] || []
  const pin = deployItems.value[id]?.cred_id || 0
  return pin ? pages.filter(p => p.via_cred_id === pin) : pages
}
// 主页权限预检（第三层，懒加载手动触发）：模板主页 × 已选账户，逐账户判定池内有无令牌能管
const covOpen = ref(false)
const covLoading = ref(false)
const covRows = ref([])
const runCoverage = async () => {
  covOpen.value = !covOpen.value
  if (!covOpen.value) return
  const pid = deployTpl.value?.page_id || ''
  if (!pid || !selectedAccs.value.size) { covRows.value = []; return }
  covLoading.value = true
  try {
    covRows.value = await GET('/launch-templates/page-coverage?page_id=' + encodeURIComponent(pid)
      + '&act_ids=' + encodeURIComponent([...selectedAccs.value].join(',')), 60000)
  } catch (e) { ElMessage.error(e.message || t('common.opFail')); covOpen.value = false }
  covLoading.value = false
}
const accNameOf = (id) => accounts.value.find(a => a.act_id === id)?.name || id
const toggleAcc = async (id) => {
  const s = new Set(selectedAccs.value); s.has(id) ? s.delete(id) : s.add(id); selectedAccs.value = s
  if (s.has(id)) await ensureAccConfig(id)
}
// 批量选择：排除异常账户（account_status≠1 建 广告必失败）+ 跟帖模式排除无主页权限账户
const _selectableAccs = () => filteredDeployAccounts.value.filter(a => a.account_status === 1 && (!reuseDeployPage.value || accManagesReusePage(a.act_id)))
const accAbnormal = (a) => a.account_status !== 1
const deploySelectAll = () => {
  // 全选=只选可选集（正常账户；异常账户 checkbox 本就禁用——「只选正常账户」按钮曾与其
  // 语义重复，复审P2 已删）
  const s = new Set(_selectableAccs().map(a => a.act_id))
  selectedAccs.value = s
  _selectableAccs().forEach(a => ensureAccConfig(a.act_id))
}
const deployClearSel = () => { selectedAccs.value = new Set() }
// 账户显示名（toast 明细用；名字缺失退回 act_id）
const accLabel = (id) => accounts.value.find(a => a.act_id === id)?.name || id
// 主页权限总览：首次展开懒拉一次（每页按令牌计数分权限面——后端 OR 合并 + 逐令牌计数）
const togglePageOverview = async () => {
  pageOverviewOpen.value = !pageOverviewOpen.value
  if (pageOverviewOpen.value && !permPagesLoaded) {
    permPagesLoading.value = true
    try { const r = await GET('/leads/pages'); permPages.value = r.pages || []; permPagesLoaded = true }
    catch (e) { showError(e, t('launch.pagePermLoadFail')) }
    permPagesLoading.value = false
  }
}
const permPageSummary = computed(() => {
  const p = permPages.value
  return {
    m: p.filter(x => (x.manage_tokens || 0) > 0).length,
    a: p.filter(x => !(x.manage_tokens || 0) && (x.advertise_only_tokens || 0) > 0).length,
    r: p.filter(x => !(x.manage_tokens || 0) && !(x.advertise_only_tokens || 0)).length,
  }
})
const subStateText = (v) => v === true ? t('launch.ppSubscribed') : v === false ? t('launch.ppNotSubscribed') : '—'
// 随机分配主页：对已选账户从各自 accPages 池随机选，全批去重（同一主页不给两个账户）；
// 池小账户先分配（贪心近似匹配，减少"大池先占小池唯一主页"的伪不足）；不足的留空并 toast 明细；
// 再点一次重摇（每次全新 used 集合 + 随机序）
const randomAssignPages = () => {
  const ids = [...selectedAccs.value]
  if (!ids.length) return ElMessage.warning(t('launch.selectAccFirst'))
  if (ids.some(id => accLoadingConfig.value.has(id)))
    return ElMessage.warning(t('launch.randPageLoading'))
  const used = new Set()
  const done = []
  const short = []
  const order = ids.map(id => ({
    id, r: Math.random(),
    n: (accPages.value[id] || []).filter(p => p.id).length,
  })).sort((a, b) => a.n - b.n || a.r - b.r)
  for (const { id } of order) {
    const pool = (accPages.value[id] || []).filter(p => p.id && !used.has(p.id))
    const pick = pool[Math.floor(Math.random() * pool.length)]
    if (!pick) {
      deployItems.value[id] = { ...(deployItems.value[id] || {}), page_id: '' }
      short.push(accLabel(id))
      continue
    }
    used.add(pick.id)
    deployItems.value[id] = { ...(deployItems.value[id] || {}), page_id: pick.id }
    done.push(id)
  }
  if (done.length) ElMessage.success(t('launch.randPageDone', { n: done.length }))
  if (short.length) ElMessage.warning(t('launch.randPageShort', { accs: short.join('、') }))
}
// 像素策略辅助：从该账户 accPixels 池随机取一个（池空返 ''）
const randomPixelFor = (id) => {
  const pool = (accPixels.value[id] || []).filter(p => p.id)
  return pool.length ? pool[Math.floor(Math.random() * pool.length)].id : ''
}
// 「随机用账户像素」：立即为全部已选账户随机填像素（之后仍可手改下拉）
const applyRandomPixels = () => {
  const ids = [...selectedAccs.value]
  if (!ids.length) return ElMessage.warning(t('launch.selectAccFirst'))
  if (ids.some(id => accLoadingConfig.value.has(id)))
    return ElMessage.warning(t('launch.randPageLoading'))
  const short = []
  for (const id of ids) {
    const pid = randomPixelFor(id)
    if (!pid) { short.push(accLabel(id)); continue }
    deployItems.value[id] = { ...(deployItems.value[id] || {}), pixel_id: pid }
  }
  if (short.length) ElMessage.warning(t('launch.psRandomShort', { accs: short.join('、') }))
  else ElMessage.success(t('launch.psRandomDone', { n: ids.length }))
}
const onPixelStrategyChange = () => {
  if (pixelStrategy.value === 'random') applyRandomPixels()
  // create 不在此建——部署确认后逐账户预创建（用户取消部署时不白建像素）
}
// 「每账户新建像素」预创建：逐账户顺序调（不并发打 FB），失败自动降级随机现有像素并 toast 说明；
// 降级也无池 → 保持空（部署走模板默认像素）。内部逐账户 catch，永不抛出
const precreatePixels = async () => {
  const created = []
  const fallback = []
  let firstErr = ''
  for (const id of [...selectedAccs.value]) {
    try {
      const r = await POST('/fb/accounts/' + id + '/create-pixel')
      deployItems.value[id] = { ...(deployItems.value[id] || {}), pixel_id: r.pixel_id }
      created.push(id)
    } catch (e) {
      const pid = randomPixelFor(id)
      if (pid) deployItems.value[id] = { ...(deployItems.value[id] || {}), pixel_id: pid }
      if (!firstErr) firstErr = e.message || ''
      fallback.push(accLabel(id))
    }
  }
  if (created.length) ElMessage.success(t('launch.psCreated', { n: created.length }))
  if (fallback.length)
    ElMessage.warning(t('launch.psCreateFallback', { accs: fallback.join('、'), err: (firstErr || '').slice(0, 120) }))
}
// 批量模式：懒加载素材库（仅图片/视频可参与批量生成系列）
const switchDeployMode = async (m) => {
  deployMode.value = m
  if (m === 'batch' && !batchAssets.value.length && !batchAssetsLoading.value) {
    batchAssetsLoading.value = true
    try { batchAssets.value = await GET('/assets') } catch (e) { showError(e, t('launch.loadAccFail')) }
    batchAssetsLoading.value = false
  }
}
const batchSelectable = computed(() => batchAssets.value.filter(a => a.type === 'image' || a.type === 'video'))
const toggleBatchAsset = (id) => {
  const s = new Set(batchAssetIds.value)
  if (s.has(id)) { s.delete(id) }
  else {
    if (s.size >= BATCH_ASSET_MAX) return ElMessage.warning(t('launch.batchMaxReached', { n: BATCH_ASSET_MAX }))
    s.add(id)
  }
  batchAssetIds.value = s
}
const batchSelectAllAssets = () => {
  batchAssetIds.value = new Set(batchSelectable.value.slice(0, BATCH_ASSET_MAX).map(a => a.id))
  if (batchSelectable.value.length > BATCH_ASSET_MAX) ElMessage.warning(t('launch.batchMaxReached', { n: BATCH_ASSET_MAX }))
}
const batchClearAssets = () => { batchAssetIds.value = new Set() }
// 批量预检：后端按第一个素材构建示例 payload（campaign 名=素材名）+ 返回 series_count
const batchPreflight = async () => {
  if (!batchAssetIds.value.size) return ElMessage.warning(t('launch.batchNeedAssets'))
  const wantPlat = deployTpl.value?.platform === 'tt' ? 'tt' : 'fb'
  const accs = accounts.value.filter(a => (a.platform || 'fb') === wantPlat)
  const sel = [...selectedAccs.value]
  // 预检目标账户：优先已选且正常的 → 已选 → 未选但正常 → 第一个（payload 结构与账户无关，只影响币种/汇率展示）
  const target = accs.find(a => sel.includes(a.act_id) && a.account_status === 1)
    || accs.find(a => sel.includes(a.act_id)) || accs.find(a => a.account_status === 1) || accs[0]
  if (!target) return ElMessage.warning(accs.length ? t('launch.preflightAllAbnormal') : t('launch.preflightNoAccount'))
  batchPreflighting.value = true
  try {
    const r = await POST('/launch-templates/' + deployTpl.value.id + '/preflight',
      { act_id: target.act_id, asset_ids: [...batchAssetIds.value], account_count: sel.length })
    showPreflight(r)
  } catch (e) { showError(e, t('launch.preflightFail')) }
  batchPreflighting.value = false
}
const startDeploy = async () => {
  if (!selectedAccs.value.size) return ElMessage.warning(t('launch.selectAccFirst'))
  // lifetime 总预算必须配排期才能部署（后端 _budget_guard_400 同口径，提前给出明确提示）
  if ((deployTpl.value?.platform || 'fb') !== 'tt'
    && deployTpl.value?.budget_type === 'lifetime'
    && !(deployTpl.value?.schedule_start && deployTpl.value?.schedule_end))
    return ElMessage.warning(t('launch.deployLifetimeNeedSchedule'))
  const isBatch = deployMode.value === 'batch'
  if (isBatch && !batchAssetIds.value.size) return ElMessage.warning(t('launch.batchNeedAssets'))
  // 批量部署直接产生花费——提交前二次确认（单模式列账户数；批量模式额外列系列总数与合计日预算；
  // 结构模板按树口径：有启用链路=立即消耗警示，全暂停=不消耗口径）
  const n = selectedAccs.value.size
  const m = isBatch ? batchAssetIds.value.size : 0
  const total = isBatch ? n * m : n
  const treeStats = deployTreeStats.value
  try {
    await ElMessageBox.confirm(
      treeStats
        ? (treeStats.chains > 0
            ? t('launch.treeConfirmMsg', { n, g: treeStats.n, m: treeStats.m, k: treeStats.chains })
            : t('launch.treeConfirmPausedMsg', { n, g: treeStats.n, m: treeStats.m }))
        : isBatch
        ? t('launch.batchConfirmMsg', { n, m, total, amt: (total * Number(deployTpl.value.budget_usd || 0)).toFixed(0) })
        : t('launch.deployConfirmMsg', { n }),
      t('launch.deployConfirmTitle'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
  } catch { return }
  deploying.value = true
  try {
    // 「每账户新建像素」：确认后才逐账户预创建（取消部署不白建）；失败自动降级随机现有并 toast
    if (pixelStrategy.value === 'create' && (deployTpl.value?.platform || 'fb') !== 'tt') {
      await precreatePixels()
    }
    const items = [...selectedAccs.value].map(id => ({ act_id: id, page_id: deployItems.value[id]?.page_id || '', pixel_id: deployItems.value[id]?.pixel_id || '', cred_id: deployItems.value[id]?.cred_id || 0 }))
    const body = { items }
    // 仅批量模式带 asset_ids——不带/空数组 = 后端单模板旧行为（完全向后兼容）
    if (isBatch) body.asset_ids = [...batchAssetIds.value]
    const r = await POST('/launch-templates/' + deployTpl.value.id + '/deploy', body)
    deployOpen.value = false
    ElMessage.success(r.tree
      ? t('launch.submittedTree', { n: r.total, g: r.tree.adsets,
          m: Math.max(1, Math.round((r.tree.ad_total || 0) / Math.max(r.total || 1, 1))) })
      : isBatch
      ? t('launch.batchSubmitted', { n: r.total, m, total: r.series_total ?? total })
      : t('launch.submitted', { n: r.total }))
    emit('submitted', r.job_id)   // 宿主页开 JobProgressDialog（+ 刷新模板列表）
  } catch (e) { showError(e, t('launch.deploySubmitFail')) }
  deploying.value = false
}

// ── 预检弹窗渲染辅助 ──
const SPECIAL_CATS = [
  { v: 'CREDIT', l: 'launch.scat_credit' },
  { v: 'EMPLOYMENT', l: 'launch.scat_employment' },
  { v: 'HOUSING', l: 'launch.scat_housing' },
  { v: 'SOCIAL_ISSUES_ELECTIONS_POLITICS', l: 'launch.scat_politics' },
  { v: 'FINANCIAL_PRODUCTS', l: 'launch.scat_financial' },
]
// 预检值友好化：targeting 展开已知子键（countries→国家名、age_min/max→"18-65"、genders→性别），
// 其余对象（geo_locations / attribution_spec / object_story_spec 等）保持 JSON 原样
const GENDER_TXT = { 0: 'genderAll', 1: 'genderMale', 2: 'genderFemale' }
const pfVal = (k, v) => {
  if (v === null || v === undefined || v === '') return '—'
  if (k === 'targeting' && v && typeof v === 'object' && !Array.isArray(v)) {
    const parts = []
    const geo = v.geo_locations || v.geo
    if (geo?.countries?.length) parts.push(t('launch.countries') + '：' + geo.countries.map(c => countryName(c) || c).join(' · '))
    else if (geo) parts.push('geo：' + JSON.stringify(geo))
    if (v.age_min != null || v.age_max != null) parts.push(t('launch.age') + '：' + (v.age_min ?? 18) + '-' + (v.age_max ?? 65))
    if (Array.isArray(v.genders) && v.genders.length) parts.push(t('launch.gender') + '：' + v.genders.map(g => t('launch.' + (GENDER_TXT[g] || 'genderAll'))).join('/'))
    const rest = { ...v }
    delete rest.geo_locations; delete rest.geo; delete rest.age_min; delete rest.age_max; delete rest.genders
    if (Object.keys(rest).length) parts.push(JSON.stringify(rest))
    return parts.join('  ·  ')
  }
  return JSON.stringify(v)
}
// 树模式预检：将消耗节点预览（前 5 + 省略号）+ 广告节点绑定摘要
const willSpendPreview = computed(() => {
  const w = preflightResult.value?.will_spend || []
  return w.length > 5 ? w.slice(0, 5).join('、') + ' …' : w.join('、')
})
const treeBindingsText = (b) => {
  if (!b) return ''
  const parts = []
  if (b.landing_page_id) parts.push('LP ' + b.landing_page_id)
  if (b.subcode_slug) parts.push('/' + b.subcode_slug)
  if (b.message_template_id) parts.push(t('launch.pfBindMsg') + ' ' + b.message_template_id)
  if (b.lead_form_template_id) parts.push(t('launch.pfBindForm') + ' ' + b.lead_form_template_id)
  return parts.join(' · ')
}
// 预检「预算与排期」行（批G）：日/总预算（本币换算）+ 排期区间 + 投放方式 + 出价 + ROAS + 特殊类别 + 描述
// 平铺用模板级键；树模式每组行传 tree[] 组对象（同名键）
const pfBudgetSegments = (r) => {
  const seg = []
  if (!r) return seg
  if ((r.budget_type || 'daily') === 'lifetime') {
    if (r.lifetime_budget_usd != null)
      seg.push(t('launch.pfLifetime', { v: r.lifetime_budget_usd }) + (r.lifetime_budget_fb != null ? ' → ' + r.lifetime_budget_fb : ''))
  } else if (r.budget_usd != null) {
    seg.push('$' + r.budget_usd + '/' + t('launch.perDay'))
  }
  if (r.schedule_start || r.schedule_end)
    seg.push((r.schedule_start || '—') + ' ~ ' + (r.schedule_end || '—'))
  if (r.pacing === 'accelerated') seg.push(t('launch.pacingAccelerated'))
  if (r.bid_amount_usd != null)
    seg.push(t('launch.pfBid', { v: r.bid_amount_usd }) + (r.bid_amount_fb != null ? ' → ' + r.bid_amount_fb : ''))
  if (r.minimum_roas != null) seg.push(t('launch.pfRoas', { v: r.minimum_roas }))
  if (r.spend_cap_usd != null)
    seg.push(t('launch.pfSpendCap', { v: r.spend_cap_usd }) + (r.spend_cap_fb != null ? ' → ' + r.spend_cap_fb : ''))
  const cats = Array.isArray(r.special_ad_categories) ? r.special_ad_categories : []
  if (cats.length) {
    const labels = cats.map(c => { const hit = SPECIAL_CATS.find(x => x.v === c); return hit ? t(hit.l) : c })
    seg.push(labels.join('/'))
  }
  if (r.link_description) seg.push(t('launch.pfDesc', { v: r.link_description }))
  return seg
}

defineExpose({ open, showPreflight })
</script>

<template>
  <el-drawer v-model="deployOpen" :title="t('launch.deployTitle', { name: deployTpl?.name||'' })" direction="rtl" size="min(760px, 96vw)">
    <div class="d">{{ deployTpl?.platform === 'tt' ? t('launch.ttDeploySubtitle') : t('launch.deploySubtitle') }}</div>
    <!-- 主页权限总览（令牌×主页权限面；FB 专属，懒加载折叠面板） -->
    <div v-if="deployTpl?.platform !== 'tt'" class="pp-ov">
      <button type="button" class="pp-head" @click="togglePageOverview">
        <span>{{ t('launch.pagePermTitle') }}<template v-if="permPages.length"> · {{ t('launch.pagePermCount', { n: permPages.length }) }}</template></span>
        <span class="pp-arrow" :class="{ open: pageOverviewOpen }">▾</span>
      </button>
      <div v-if="pageOverviewOpen" class="pp-body" v-loading="permPagesLoading">
        <div class="pp-hint">{{ t('launch.pagePermHint') }}</div>
        <div v-if="permPages.length" class="pp-summary">{{ t('launch.ppSummary', { m: permPageSummary.m, a: permPageSummary.a, r: permPageSummary.r }) }}</div>
        <table v-if="permPages.length" class="pp-table">
          <thead>
            <tr>
              <th>{{ t('launch.page') }}</th>
              <th>{{ t('launch.ppColManage') }}</th>
              <th>{{ t('launch.ppColAdsOnly') }}</th>
              <th>{{ t('launch.ppColReadonly') }}</th>
              <th>{{ t('launch.ppColSubscribed') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in permPages" :key="p.page_id">
              <td>
                <div class="pp-name">{{ p.page_name || p.page_id }}</div>
                <div class="pp-pid">{{ p.page_id }}</div>
              </td>
              <td :class="{ ok: (p.manage_tokens || 0) > 0 }">{{ p.manage_tokens || 0 }}</td>
              <td>{{ p.advertise_only_tokens || 0 }}</td>
              <td>{{ p.read_only_tokens || 0 }}</td>
              <td :class="{ ok: p.subscribed === true, dim: p.subscribed !== true }">{{ subStateText(p.subscribed) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!permPagesLoading && !permPages.length" class="empty-sm">{{ t('launch.pagePermEmpty') }}</div>
      </div>
    </div>
    <!-- 结构模板：树概览（素材在树内按节点配 → 「按素材批量生成」整块隐藏，后端也 400 拦） -->
    <div v-if="deployTreeStats" class="deploy-tree-card">
      <div class="dtc-title">{{ t('launch.treeOverview') }}</div>
      <div class="dtc-line">{{ t('launch.treeOverviewLine', { n: deployTreeStats.n, m: deployTreeStats.m }) }}</div>
      <div class="dtc-line">{{ deployTreeStats.isCbo ? t(deployTreeStats.isLifetime ? 'launch.treeCboLifetimeBudget' : 'launch.treeCboBudget') : t('launch.treeAboTotal') }}：${{ deployTreeStats.perAcc }}<template v-if="!deployTreeStats.isLifetime">/{{ t('launch.perDay') }}</template></div>
      <div class="dtc-line" :class="{ warn: deployTreeStats.chains > 0 }">{{ deployTreeStats.chains > 0 ? t('launch.treeEnabledChains') + '：' + deployTreeStats.chains : t('launch.treeAllPaused') }}</div>
    </div>
    <div v-if="!deployTreeStats" class="deploy-mode-row">
      <label class="dm-label">{{ t('launch.deployMode') }}</label>
      <div class="seg dm-seg">
        <button :class="{on:deployMode==='single'}" @click="deployMode='single'">{{ t('launch.modeSingle') }}</button>
        <button :class="{on:deployMode==='batch'}" @click="switchDeployMode('batch')">{{ t('launch.modeBatch') }}</button>
      </div>
    </div>
    <template v-if="deployMode==='batch' && !deployTreeStats">
      <div class="deploy-reuse-hint batch-hint">{{ t('launch.batchHint') }}</div>
      <div class="batch-bar">
        <span class="batch-count">{{ t('launch.batchAssetCount', { n: batchAssetIds.size }) }}</span>
        <button class="op sm" @click="batchSelectAllAssets">{{ t('launch.batchSelectAll') }}</button>
        <button class="op sm" @click="batchClearAssets">{{ t('launch.deployClear') }}</button>
        <button class="op sm" :disabled="batchPreflighting" @click="batchPreflight">{{ t('launch.preflight') }}</button>
      </div>
      <div class="picker-grid batch-grid" v-loading="batchAssetsLoading">
        <div v-for="a in batchSelectable" :key="a.id" :class="['picker-card','batch-card',{on:batchAssetIds.has(a.id)}]" @click="toggleBatchAsset(a.id)">
          <img v-if="a.type==='image'" :src="a.public_url" class="picker-thumb" />
          <video v-else :src="a.public_url" class="picker-thumb" preload="metadata" />
          <span class="picker-name">{{ a.name }}<template v-if="a.type==='video' && a.duration_sec"> · {{ a.duration_sec }}s</template></span>
          <span class="batch-check">{{ batchAssetIds.has(a.id) ? '✓' : '' }}</span>
        </div>
        <div v-if="!batchSelectable.length && !batchAssetsLoading" class="empty-sm">{{ t('launch.batchNoAssets') }}</div>
      </div>
      <div v-if="batchPreview.n && batchPreview.m" class="batch-preview">{{ t('launch.batchPreview', { n: batchPreview.n, m: batchPreview.m, total: batchPreview.total }) }}</div>
    </template>
    <div v-if="deployTpl?.post_source==='reuse'" class="deploy-reuse-hint">{{ t('launch.deployReuseHint') }}（{{ (deployTpl?.reuse_post_ref||'').split('_')[0] }}）</div>
    <div v-if="deployMode==='single' && deployAsset?.type==='video'" class="deploy-video-hint">{{ t('launch.deployVideoHint', { name: deployAsset.name || deployAsset.filename || '' }) }}<template v-if="deployAsset.duration_sec">（{{ t('launch.durationLabel') }} {{ deployAsset.duration_sec }}s）</template></div>
    <div class="deploy-search-row">
      <el-input v-model="deploySearch" clearable :placeholder="t('launch.searchAccountPlaceholder')" />
      <span class="acc-count-hint">{{ filteredDeployAccounts.length }} / {{ accounts.length }} {{ t('launch.accountsUnit') }}</span>
    </div>
    <div class="acc-batch-row">
      <button class="op sm" @click="deploySelectAll">{{ t('launch.deploySelectAll') }}</button>
      <button class="op sm" @click="deployClearSel">{{ t('launch.deployClear') }}</button>
      <button v-if="deployTpl?.platform !== 'tt' && deployTpl?.post_source !== 'reuse'" class="op sm" :disabled="!selectedAccs.size" @click="randomAssignPages">{{ t('launch.randAssignPages') }}</button>
    </div>
    <!-- 像素策略（FB 专属）：跟随模板 / 随机用账户像素 / 每账户新建像素（部署时预创建） -->
    <div v-if="deployTpl?.platform !== 'tt'" class="deploy-mode-row ps-row">
      <label class="dm-label">{{ t('launch.pixelStrategy') }}</label>
      <el-select v-model="pixelStrategy" size="small" style="width:200px" @change="onPixelStrategyChange">
        <el-option value="template" :label="t('launch.psTemplate')" />
        <el-option value="random" :label="t('launch.psRandom')" />
        <el-option value="create" :label="t('launch.psCreate')" />
      </el-select>
      <span v-if="pixelStrategy === 'create'" class="ps-hint">{{ t('launch.psCreateHint') }}</span>
    </div>
    <div v-if="deployTpl?.platform === 'tt' && !accLoading && !accounts.length" class="empty-sm">{{ t('launch.deployNoTtAccounts') }}</div>
    <!-- 跟帖模式提示：账户灰化的原因显式说清（不让人猜）——可勾选数实时 -->
    <div v-if="deployTpl?.post_source === 'reuse'" class="msg-aud-hint" style="margin-bottom:8px">
      {{ t('launch.reuseAccHint', { n: filteredDeployAccounts.filter(a => accManagesReusePage(a.act_id)).length, m: filteredDeployAccounts.length }) }}
    </div>
    <!-- 节点指定主页提示：部署分配的主页将优先（跟帖节点除外）——优先级显式化不静默 -->
    <div v-if="tplNodePages.length" class="msg-aud-hint" style="margin-bottom:8px">
      {{ t('launch.nodePageHint', { n: tplNodePages.length }) }}
    </div>
    <div class="acc-list" v-loading="accLoading">
      <div v-for="a in filteredDeployAccounts" :key="a.act_id" :class="['acc-block', {disabled: (deployTpl?.post_source === 'reuse' && !accManagesReusePage(a.act_id)) || accAbnormal(a)}]">
        <label class="acc-row" :class="{on:selectedAccs.has(a.act_id)}">
          <input type="checkbox" :checked="selectedAccs.has(a.act_id)" :disabled="(deployTpl?.post_source === 'reuse' && !accManagesReusePage(a.act_id)) || accAbnormal(a)" @change="toggleAcc(a.act_id)" />
          <span class="acc-main">
            <span class="acc-name">{{ a.name || a.act_id }}</span>
            <span class="acc-sub"><span class="acc-id mono">{{ a.act_id }}</span><span class="acc-cur">{{ a.currency }}</span></span>
          </span>
          <!-- 可用额度（花费上限−历史总消耗，USD）；无上限账户显示 ∞；未知币种算不出则不显示。
               曾拿 balance_usd（FB 未结欠款）兜底冒充可用额度——口径错误已移除 -->
          <span v-if="a.balance_kind !== 'unlimited' && a.balance_kind !== 'very_high_limit' && a.available_usd != null" class="acc-bal tnum" :title="t('launch.accAvailable')">${{ a.available_usd }}</span>
          <span v-else-if="a.balance_kind === 'unlimited' || a.balance_kind === 'very_high_limit'" class="acc-bal" :title="t('launch.accAvailable') + ' · ' + t('launch.accUnlimited')">∞</span>
          <span :class="['acc-status', a.account_status === 1 ? 'ok' : 'warn']" :title="a.account_status === 1 ? t('launch.accNormal') : (accountStatus(a.account_status).label + ' · ' + t('launch.accAbnormalNoDeploy'))">{{ a.account_status === 1 ? t('launch.accNormal') : accountStatus(a.account_status).label }}</span>
          <span v-if="deployTpl?.post_source === 'reuse' && !accManagesReusePage(a.act_id)" class="acc-no-perm" :title="t('launch.noPagePermission')"></span>
        </label>
        <div v-if="selectedAccs.has(a.act_id)" class="acc-config">
          <template v-if="accLoadingConfig.has(a.act_id)">
            <span class="config-loading">{{ t('launch.loadingPagePixel') }}</span>
          </template>
          <template v-else-if="deployTpl?.platform === 'tt'">
            <label>{{ t('launch.ttPixelLabel') }}</label>
            <el-select v-model="deployItems[a.act_id].pixel_id" size="small" filterable style="width:100%">
              <el-option value="" :label="t('launch.defaultVal', { v: deployTpl?.pixel_id || t('launch.autoPick') })" />
              <el-option v-for="p in ttPixels" :key="p.id" :value="p.pixel_id" :label="(p.pixel_name || p.pixel_id) + ' (' + p.pixel_id + ')'" />
            </el-select>
          </template>
          <template v-else>
            <label>{{ t('launch.page') }}</label>
            <el-select v-model="deployItems[a.act_id].page_id" size="small" filterable style="width:100%">
              <el-option value="" :label="t('launch.defaultVal', { v: deployTpl?.page_id || t('launch.none') })" />
              <el-option v-for="p in pageOptsFor(a.act_id)" :key="p.id" :value="p.id"
                         :label="p.name + ' (' + p.id + ')' + (p.via_cred ? ' · ' + p.via_cred : '') + (p.can_advertise ? '' : ' · ' + t('launch.pgNoAd'))"
                         :disabled="!p.can_advertise" />
            </el-select>
            <label>{{ t('launch.credLabel') }}</label>
            <el-select v-model="deployItems[a.act_id].cred_id" size="small" style="width:100%" :title="t('launch.credHint')">
              <el-option :value="0" :label="t('launch.credAuto')" />
              <el-option v-for="c in (accCreds[a.act_id]||[])" :key="c.id" :value="c.id"
                         :label="c.alias + (c.available ? '' : ' · ' + t('launch.credCooling'))" :disabled="!c.available" />
            </el-select>
            <label>{{ t('launch.pixel') }}</label>
            <el-select v-model="deployItems[a.act_id].pixel_id" size="small" filterable style="width:100%">
              <el-option value="" :label="t('launch.defaultVal', { v: deployTpl?.pixel_id || t('launch.none') })" />
              <el-option v-for="p in (accPixels[a.act_id]||[])" :key="p.id" :value="p.id" :label="p.name + ' (' + p.id + ')'" />
            </el-select>
          </template>
        </div>
      </div>
    </div>
    <!-- 主页权限预检（2026-09-24 第三层：新帖模式，懒加载手动触发——对标跟帖预过滤） -->
    <div v-if="deployTpl && (deployTpl.platform||'fb')!=='tt' && (deployTpl.post_source||'new')!=='reuse'" class="cov-bar">
      <button class="btn" :disabled="covLoading || !selectedAccs.size" @click="runCoverage">{{ covLoading ? t('common.loading') : t('launch.covBtn') }}</button>
      <span v-if="!selectedAccs.size" class="cov-hint">{{ t('launch.covNeedAcc') }}</span>
      <span v-else-if="!deployTpl.page_id" class="cov-hint">{{ t('launch.covNoPage') }}</span>
    </div>
    <div v-if="covOpen && covRows.length" class="cov-list" v-loading="covLoading">
      <div v-for="r in covRows" :key="r.act_id" :class="['cov-row', r.ok ? 'ok' : 'bad']">
        <span class="cov-mark">{{ r.ok ? '✓' : '✗' }}</span>
        <span class="cov-acc">{{ accNameOf(r.act_id) }}</span>
        <span class="cov-via">{{ r.ok ? t('launch.covVia', { v: r.via }) : r.reason }}</span>
      </div>
    </div>
    <template #footer>
      <span class="sel-count">{{ t('launch.selectedCount', { n: selectedAccs.size }) }}<template v-if="selectedAccs.size && deployTpl && deployMode==='single'"> · {{ singleIsLifetime ? t('launch.totalBudgetLifetimeHint', { total: (selectedAccs.size * singlePerAcc).toFixed(0), per: singlePerAcc }) : t('launch.totalBudgetHint', { total: (selectedAccs.size * singlePerAcc).toFixed(0), per: singlePerAcc }) }}</template><template v-else-if="selectedAccs.size && deployTpl && deployMode==='batch' && batchAssetIds.size"> · {{ t('launch.batchBudgetHint', { total: (selectedAccs.size * batchAssetIds.size * Number(deployTpl.budget_usd || 0)).toFixed(0), n: selectedAccs.size, m: batchAssetIds.size, per: Number(deployTpl.budget_usd || 0) }) }}</template></span>
      <button class="btn" @click="deployOpen=false">{{ t('common.cancel') }}</button>
      <button class="btn primary" :disabled="deploying||!selectedAccs.size||(deployMode==='batch'&&!batchAssetIds.size)" @click="startDeploy">{{ deploying ? t('launch.submitting') : t('launch.startDeploy') }}</button>
    </template>
  </el-drawer>

  <!-- 预检结果（结构化展示） -->
  <el-dialog v-model="preflightVisible" :title="preflightResult?.platform === 'tt' ? t('launch.ttPreflightTitle') : t('launch.preflightTitle')" width="700px" append-to-body>
    <div v-if="preflightResult" class="preflight">
      <!-- 树模式：将消耗横幅 + 概览 + 结构树表（payload 样例沿用下方三段折叠渲染） -->
      <template v-if="preflightResult.mode === 'tree'">
        <div v-if="preflightResult.will_spend?.length" class="pf-banner warn">{{ t('launch.pfWillSpendBanner', { n: preflightResult.will_spend.length }) }}：{{ willSpendPreview }}</div>
        <div v-else class="pf-banner ok">{{ t('launch.pfAllPausedBanner') }}</div>
        <div class="pf-summary">
          <span>{{ t('launch.pfCurrency') }}：<b>{{ preflightResult.currency }}</b></span>
          <span>{{ t('launch.fxRate') }}：{{ preflightResult.fx_rate || t('launch.none') }}</span>
          <span>{{ t('launch.modeColon') }}{{ preflightResult.budget_mode }}</span>
          <span>{{ t('launch.pfAdsetCount') }}：<b>{{ preflightResult.adset_count }}</b> · {{ t('launch.pfAdTotal') }}：<b>{{ preflightResult.ad_total }}</b></span>
          <span>{{ t('launch.budgetColon') }}<b v-if="preflightResult.abo_total_usd != null">${{ preflightResult.abo_total_usd }}/{{ t('launch.perDay') }}（{{ t('launch.pfAboTotal') }}）</b><b v-else>${{ preflightResult.budget_usd }} → {{ preflightResult.camp_budget_fb }}（{{ t('launch.minorUnitHint') }}）</b></span>
        </div>
        <div v-if="pfBudgetSegments(preflightResult).length" class="pf-bs-row">
          <span class="pf-bs-label">{{ t('launch.pfBudgetSchedule') }}</span>
          <span v-for="(sg, i) in pfBudgetSegments(preflightResult)" :key="i" class="pf-bs-seg">{{ sg }}</span>
        </div>
        <div class="pf-section">
          <div class="pf-title">{{ t('launch.pfTreeTitle') }}</div>
          <div class="pf-tree">
            <template v-for="(s, si) in preflightResult.tree" :key="si">
              <div class="pft-adset">
                <span :class="['pft-state', s.enabled ? 'on' : 'off']">{{ s.enabled ? t('launch.treeStateOn') : t('launch.treeStatePaused') }}</span>
                <span class="pft-name">{{ s.name }}</span>
                <span class="pft-budget">${{ s.budget_usd ?? '—' }} → {{ s.budget_local_fb }}</span>
                <span v-for="(sg, i) in pfBudgetSegments(s)" :key="'bs'+i" class="pft-meta">{{ sg }}</span>
              </div>
              <div v-for="(a, ai) in s.ads" :key="ai" class="pft-ad">
                <span :class="['pft-state', a.enabled ? 'on' : 'off']">{{ a.enabled ? t('launch.treeStateOn') : t('launch.treeStatePaused') }}</span>
                <span class="pft-name">{{ a.name || (a.asset_count > 1 ? t('launch.treeAssetGroupN', { n: a.asset_count }) : t('launch.treeAdN', { n: ai + 1 })) }}</span>
                <span v-if="a.asset_count" class="pft-meta">{{ t('launch.treeAssetCount', { n: a.asset_count }) }}</span>
                <span v-if="a.post_source === 'reuse'" class="pft-meta">{{ t('launch.postSourceReuse') }}</span>
                <span v-if="treeBindingsText(a.bindings)" class="pft-meta">{{ treeBindingsText(a.bindings) }}</span>
              </div>
            </template>
          </div>
        </div>
      </template>
      <template v-else>
        <div v-if="preflightResult.subcode_warn_slug" style="color:var(--warning);padding:8px 0;font-size:13px">{{ t('launch.subcodeWarn', { slug: preflightResult.subcode_warn_slug }) }}</div>
        <div v-if="preflightResult.series_count" class="pf-series-count">{{ t('launch.batchSeriesCount', { n: preflightResult.series_count }) }}</div>
        <div v-if="preflightResult.asset?.type === 'video'" style="padding:4px 0;font-size:13px">{{ t('launch.videoAsset') }}：{{ preflightResult.asset.name || preflightResult.asset.filename }}<template v-if="preflightResult.asset.duration_sec"> · {{ t('launch.durationLabel') }} {{ preflightResult.asset.duration_sec }}s</template></div>
        <div class="pf-summary">
          <span>{{ t('launch.pfCurrency') }}：<b>{{ preflightResult.currency }}</b></span>
          <span>{{ t('launch.budgetColon') }}${{ preflightResult.budget_usd }} → <b>{{ preflightResult.daily_budget_fb }}</b>（{{ preflightResult.platform === 'tt' ? t('launch.ttUnitHint') : t('launch.minorUnitHint') }}）</span>
          <span>{{ t('launch.fxRate') }}：{{ preflightResult.fx_rate || t('launch.none') }}</span>
          <span>{{ t('launch.modeColon') }}{{ preflightResult.budget_mode }}</span>
        </div>
        <div v-if="pfBudgetSegments(preflightResult).length" class="pf-bs-row">
          <span class="pf-bs-label">{{ t('launch.pfBudgetSchedule') }}</span>
          <span v-for="(sg, i) in pfBudgetSegments(preflightResult)" :key="i" class="pf-bs-seg">{{ sg }}</span>
        </div>
      </template>
      <div class="pf-section">
        <div class="pf-title">{{ t('launch.pfCampaign') }}</div>
        <div class="pf-fields"><div v-for="(v,k) in preflightResult.campaign" :key="k" class="pf-field"><span class="pf-k">{{ k }}</span><span class="pf-v">{{ pfVal(k, v) }}</span></div></div>
      </div>
      <div class="pf-section">
        <div class="pf-title">{{ preflightResult.platform === 'tt' ? t('launch.levelAdGroup') : t('launch.pfAdSet') }}</div>
        <div class="pf-fields"><div v-for="(v,k) in preflightResult.adset" :key="k" class="pf-field"><span class="pf-k">{{ k }}</span><span class="pf-v">{{ pfVal(k, v) }}</span></div></div>
      </div>
      <div class="pf-section">
        <div class="pf-title">{{ t('launch.pfCreative') }}</div>
        <div class="pf-fields"><div v-for="(v,k) in preflightResult.creative" :key="k" class="pf-field"><span class="pf-k">{{ k }}</span><span class="pf-v">{{ pfVal(k, v) }}</span></div></div>
      </div>
      <div v-if="preflightResult.notes" class="pf-notes">
        <div v-for="n in preflightResult.notes" :key="n" class="pf-note">· {{ n }}</div>
      </div>
    </div>
  </el-dialog>
</template>

<style scoped>
.d{font-size:12px;color:var(--t3);line-height:1.6}
.btn{padding:7px 14px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:6px;font-size:13px;cursor:pointer;font-family:inherit}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn:disabled{opacity:.5}
.op{background:none;border:1px solid var(--bd);color:var(--t2);font-size:12px;cursor:pointer;padding:4px 10px;border-radius:6px;font-family:inherit;white-space:nowrap;transition:all .15s}
.op.sm{padding:2px 8px;font-size:11px}
.op:hover{color:var(--ac);border-color:var(--ac)}
.op:disabled{opacity:.5;cursor:not-allowed}
.empty-sm{padding:30px;text-align:center;color:var(--t3);font-size:13px}
.seg{display:flex;gap:4px}
.seg button{flex:1;padding:6px;border:1px solid var(--bd);background:var(--bg3);color:var(--t3);border-radius:6px;cursor:pointer;font-size:12px;font-family:inherit}
.seg button.on{border-color:var(--ac);color:var(--ac);background:var(--acg)}
.msg-aud-hint{padding:7px 10px;border-radius:6px;font-size:12px;line-height:1.5;background:var(--bg2);color:var(--t2);border:1px solid var(--bd)}
/* 主页权限总览（折叠面板） */
.pp-ov{border:1px solid var(--bd);border-radius:8px;margin:8px 0;overflow:hidden}
.pp-head{display:flex;width:100%;align-items:center;justify-content:space-between;background:var(--bg3);border:none;padding:8px 10px;font-size:12px;color:var(--t2);cursor:pointer}
.pp-head:hover{color:var(--t1)}
.pp-arrow{transition:transform .15s;color:var(--t3)}
.pp-arrow.open{transform:rotate(180deg)}
.pp-body{padding:8px 10px;max-height:280px;overflow-y:auto}
.pp-hint{font-size:11px;color:var(--t3);line-height:1.5;margin-bottom:6px}
.pp-summary{font-size:11px;color:var(--ac);margin-bottom:6px}
.pp-table{width:100%;border-collapse:collapse;font-size:11px}
.pp-table th{text-align:left;color:var(--t3);font-weight:500;padding:3px 6px;border-bottom:1px solid var(--bd);white-space:nowrap}
.pp-table td{padding:4px 6px;border-bottom:1px solid var(--bd);color:var(--t2);vertical-align:top}
.pp-table tr:last-child td{border-bottom:none}
.pp-name{color:var(--t1);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pp-pid{font-family:var(--font-mono);color:var(--t3);font-size:11px}
.pp-table td.ok{color:var(--success);font-weight:600}
.pp-table td.dim{color:var(--t3)}
/* 像素策略行 */
.ps-row{gap:8px;flex-wrap:wrap}
.ps-hint{font-size:11px;color:var(--t3);line-height:1.4;min-width:0;flex:1}
/* 部署抽屉：结构模板树概览卡 */
.deploy-tree-card{border:1px solid var(--bd);background:var(--bg2);border-radius:8px;padding:10px 12px;margin:8px 0;display:flex;flex-direction:column;gap:4px}
.dtc-title{font-size:12px;font-weight:600;color:var(--ac)}
.dtc-line{font-size:12px;color:var(--t2)}
.dtc-line.warn{color:var(--warning);font-weight:600}
/* 部署模式切换 + 批量生成系列 */
.deploy-mode-row{display:flex;align-items:center;gap:10px;margin:10px 0 2px}
.dm-label{font-size:12px;color:var(--t3);flex:none}
.dm-seg{flex:none;width:280px}
.dm-seg button{flex:none;padding:5px 14px}
.batch-hint{margin:8px 0;background:var(--bg2);border-color:var(--bd);color:var(--t2)}
.batch-bar{display:flex;gap:6px;align-items:center;margin:8px 0}
.batch-count{font-size:12px;color:var(--t2);margin-right:auto}
.batch-grid{max-height:300px;overflow-y:auto;padding:1px}
.batch-card{position:relative}
.batch-card.on{border-color:var(--ac);box-shadow:0 0 0 1px var(--ac) inset}
.batch-check{position:absolute;top:6px;right:6px;min-width:18px;height:18px;line-height:18px;text-align:center;border-radius:50%;background:var(--ac);color:#fff;font-size:11px}
.batch-preview{margin-top:8px;padding:8px 12px;background:var(--bg2);border:1px solid var(--bd);border-radius:6px;font-size:12px;color:var(--t2)}
.picker-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
.picker-card{background:var(--bg2);border:1px solid var(--bd);border-radius:8px;overflow:hidden;cursor:pointer;content-visibility:auto;contain-intrinsic-size:140px}
.picker-card:hover{border-color:var(--ac)}
.picker-thumb{width:100%;height:90px;object-fit:cover}
.picker-name{display:block;font-size:11px;color:var(--t2);padding:4px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.deploy-reuse-hint{padding:8px 12px;background:rgba(255,159,10,.1);border:1px solid rgba(255,159,10,.3);border-radius:6px;font-size:12px;color:var(--warning);margin:8px 0}
.deploy-video-hint{padding:8px 12px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;font-size:12px;color:var(--t2);margin:8px 0}
.deploy-search-row{display:flex;gap:8px;align-items:center;margin-bottom:8px }
.deploy-search-row .el-input{flex:1}
/* 账户列表 */
.acc-list{display:flex;flex-direction:column;gap:6px;margin-top:10px}
.acc-batch-row{display:flex;gap:6px;margin-bottom:2px}
.acc-block{border:1px solid var(--bd);border-radius:var(--rs);overflow:hidden}
.acc-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto auto auto;gap:10px;align-items:center;padding:8px 12px;cursor:pointer}
.acc-row.on{background:var(--acg)}
.acc-main{min-width:0;display:flex;flex-direction:column;gap:1px}
.acc-name{font-size:13px;color:var(--t1);font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.acc-sub{display:flex;gap:8px;align-items:baseline;font-size:11px;color:var(--t3);min-width:0}
.acc-id{font-family:var(--font-mono);font-variant-numeric:tabular-nums;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.acc-bal{font-size:12px;color:var(--t2);white-space:nowrap;font-variant-numeric:tabular-nums}
.acc-status{font-size:11px;padding:1px 8px;border-radius:var(--rs);font-weight:600;white-space:nowrap;line-height:1.5}
.acc-status.ok{color:var(--success);background:rgba(52,199,89,.13)}
.acc-status.warn{color:var(--warning);background:rgba(255,159,10,.13)}
.acc-block.disabled{opacity:.5}
.acc-block.disabled .acc-row{cursor:not-allowed}
.acc-no-perm{font-size:12px;cursor:help}
.acc-count-hint{font-size:11px;color:var(--t3);white-space:nowrap}
/* 账户行内主页/像素配置：label 定宽对齐（FB 双下拉 / TT 单下拉共用） */
.acc-config{padding:8px 12px;background:var(--bg3);display:grid;grid-template-columns:40px minmax(0,1fr) 40px minmax(0,1fr) 40px minmax(0,1fr);gap:6px 8px;align-items:center}
.acc-config label{font-size:12px;color:var(--t3)}
.config-loading{font-size:12px;color:var(--t3);padding:4px 8px;grid-column:1/-1}   /* 跨全列——曾塞进首列 40px 宽导致中文逐字竖排 */
.sel-count{font-size:12px;color:var(--t3);margin-right:auto}
/* 主页权限预检面板（2026-09-24 第三层） */
.cov-bar{display:flex;gap:10px;align-items:center;margin:10px 0 0;padding-top:10px;border-top:1px dashed var(--bd)}
.cov-hint{font-size:11px;color:var(--t3)}
.cov-list{margin-top:8px;max-height:180px;overflow-y:auto;border:1px solid var(--bd);border-radius:8px;padding:4px 10px}
.cov-row{display:flex;gap:8px;align-items:center;padding:5px 2px;border-bottom:1px solid var(--bd);font-size:12px}
.cov-row:last-child{border-bottom:none}
.cov-mark{flex:none;font-weight:700}
.cov-row.ok .cov-mark{color:var(--success)}
.cov-row.bad .cov-mark{color:var(--error)}
.cov-acc{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--t1)}
.cov-via{font-size:11px;color:var(--t3)}
.cov-row.bad .cov-via{color:var(--error)}
/* 预检结构化 */
.preflight{display:flex;flex-direction:column;gap:12px}
.pf-summary{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--t2);padding:10px;background:var(--bg3);border-radius:8px}
.pf-section{border:1px solid var(--bd);border-radius:8px;overflow:hidden}
.pf-title{font-size:12px;font-weight:600;color:var(--ac);padding:6px 10px;background:var(--bg3)}
.pf-fields{padding:4px 0}
.pf-field{display:flex;gap:8px;padding:3px 10px;font-size:11px;border-bottom:1px solid var(--bd)}
.pf-field:last-child{border:none}
.pf-k{color:var(--t3);min-width:160px;font-family:var(--font-mono);flex-shrink:0}
.pf-v{color:var(--t1);word-break:break-all}
.pf-notes{font-size:11px;color:var(--t3);padding:6px 0}
.pf-note{line-height:1.6}
.pf-series-count{padding:8px 0 0;font-size:13px;color:var(--ac)}
/* 预检：树模式横幅 + 结构树表 + 预算排期行 */
.pf-banner{padding:8px 12px;border-radius:6px;font-size:12px;line-height:1.6;border:1px solid}
.pf-banner.warn{color:var(--error);background:rgba(255,69,58,.08);border-color:rgba(255,69,58,.3)}
.pf-banner.ok{color:var(--success);background:rgba(52,199,89,.08);border-color:rgba(52,199,89,.3)}
.pf-tree{padding:2px 0}
.pft-adset,.pft-ad{display:flex;align-items:center;gap:8px;padding:4px 10px;font-size:12px;border-bottom:1px solid var(--bd)}
.pft-adset{color:var(--t1);font-weight:500}
.pft-ad{padding-left:26px;color:var(--t2)}
.pft-ad:last-child{border-bottom:none}
.pft-state{font-size:10px;padding:1px 6px;border-radius:4px;font-weight:600;flex:none}
.pft-state.on{color:var(--warning);background:rgba(255,159,10,.15)}
.pft-state.off{color:var(--t3);background:var(--bg3)}
.pft-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pft-budget{margin-left:auto;color:var(--t3);font-size:11px;white-space:nowrap;font-variant-numeric:tabular-nums;flex:none}
.pft-meta{color:var(--t3);font-size:11px;white-space:nowrap;flex:none}
.pf-bs-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--t2);padding:8px 10px;background:var(--bg3);border-radius:8px}
.pf-bs-label{font-weight:600;color:var(--ac);flex:none}
.pf-bs-seg{padding:2px 8px;background:var(--bg2);border-radius:var(--rs);white-space:nowrap}
/* 移动端：账户配置堆叠 */
@media (max-width: 768px) {
  .acc-config{grid-template-columns:1fr !important}
  .acc-config > .el-select{grid-column:1 !important}
}
</style>
