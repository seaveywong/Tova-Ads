<script setup>
// 部署进度弹窗（2026-09-26 从 LaunchTemplates 抽出组件化）：轮询 + 重试 + 换主页重试。
// 用法：<JobProgressDialog ref="jobRef" /> → jobRef.value.open(jobId)
import { ref, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { GET } from '../api'
import { fmtTime } from '../composables/useTz'
import { useLaunchJobs } from '../composables/useLaunchJobs'

const { t } = useI18n()
const {
  ensureAccNames, accName, accNameOrTail, statusText, jobText,
  jobElapsed, fmtDur, jobRunningCount, isItemNote, itemErrDisplay, itemErrTitle,
  itemCodeText, subcodeCount, progressAge, fmtAge, itemBadgeCls,
  adsUrl, adsLinkLabel, submitItemRetry,
} = useLaunchJobs()

const progressOpen = ref(false)
const activeJob = ref(null)
const pollError = ref('')
const activeJobId = ref('')
let pollTimer = null
let pollGen = 0   // 轮询代际——双开弹窗曾产生孤儿轮询链持续请求
let _pollFail = 0

// 前 12 次（30s）每 2.5s，之后每 10s；终态由 pollJob 停止
const startPoll = (jobId, n) => {
  const my = ++pollGen
  pollTimer = setTimeout(async () => {
    await pollJob(jobId)
    if (my === pollGen && pollTimer) startPoll(jobId, n + 1)
  }, n < 12 ? 2500 : 10000)
}
const pollJob = async (jobId) => {
  try {
    activeJob.value = await GET('/launch-templates/jobs/' + jobId)
    _pollFail = 0
    if (['completed','partial_failed','failed'].includes(activeJob.value.status)) { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null } }
  } catch (e) {
    // 轮询失败可见化：连续 4 次失败（~1min）→ 停轮询 + 弹窗显示错误（否则永卡「加载中」+ 无限空转）
    if (++_pollFail >= 4) {
      if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
      pollError.value = (e && e.message) || t('common.opFail')
    }
  }
}
const open = async (jobId) => {
  progressOpen.value = true; activeJob.value = null; pollError.value = ''; _pollFail = 0
  activeJobId.value = jobId
  ensureAccNames()   // 账户名映射（不阻塞轮询）
  await pollJob(jobId)
  if (pollTimer) clearTimeout(pollTimer)
  startPoll(jobId, 0)
}
const onProgressClose = () => { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null } }
const retryItem = async (it) => {
  if (await submitItemRetry(activeJob.value, it, {}) && !pollTimer) startPoll(activeJob.value.id, 0)
}
// 换主页重试（2026-09-14）：强绑主页账户部署失败（可推广对象不匹配）时，选账户实际
// 绑定的主页再试——后端 retry 的 body.page_id → item.page_id 优先于模板主页
const pagePickOpen = ref(false)
const pagePickItem = ref(null)
const pagePickPages = ref([])
const pagePickLoading = ref(false)
const pagePickSel = ref('')
const openPagePick = async (it) => {
  pagePickItem.value = it; pagePickSel.value = ''
  pagePickPages.value = []; pagePickLoading.value = true; pagePickOpen.value = true
  try { pagePickPages.value = await GET('/launch-templates/pages?act_id=' + encodeURIComponent(it.act_id)) }
  catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  pagePickLoading.value = false
}
const retryWithPage = async () => {
  if (!pagePickSel.value) return ElMessage.warning(t('launch.pagePickRequired'))
  if (await submitItemRetry(activeJob.value, pagePickItem.value, { page_id: pagePickSel.value })) {
    pagePickOpen.value = false
    if (!pollTimer) startPoll(activeJob.value.id, 0)
  }
}
onUnmounted(() => { if (pollTimer) clearTimeout(pollTimer); pollTimer = null; pollGen++ })
defineExpose({ open })
</script>

<template>
  <!-- 进度（表格式网格：账户/状态/创建物/原因/操作 定宽列对齐） -->
  <el-dialog v-model="progressOpen" :title="t('launch.progTitle', { name: activeJob?.template_name || '' })" width="880px" :close-on-click-modal="false" @close="onProgressClose">
    <div v-if="activeJob" class="prog">
      <div class="prog-sum">
        <span class="ps-job mono tnum" :title="t('launch.jobIdTip')">#{{ activeJob.id }}</span>
        <span :class="['prog-status', activeJob.status]">{{ jobText(activeJob.status) }}</span>
        <span class="ps-metric"><em>{{ t('launch.sumAccounts') }}</em><b class="tnum">{{ activeJob.total }}</b></span>
        <span class="ps-metric ok"><em>{{ t('launch.sumOk') }}</em><b class="tnum">{{ activeJob.succeeded }}</b></span>
        <span class="ps-metric err"><em>{{ t('launch.sumFail') }}</em><b class="tnum">{{ activeJob.failed }}</b></span>
        <span class="ps-metric run"><em>{{ t('launch.sumRunning') }}</em><b class="tnum">{{ jobRunningCount(activeJob) }}</b></span>
        <span class="ps-metric"><em>{{ t('launch.elapsed') }}</em><b class="tnum">{{ fmtDur(jobElapsed(activeJob)) }}</b></span>
      </div>
      <div class="ps-times tnum">
        <span>{{ t('launch.lastRunAt') }}：{{ fmtTime(activeJob.created_at) }}</span>
        <span v-if="activeJob.finished_at">{{ t('launch.finishedAt') }}：{{ fmtTime(activeJob.finished_at) }}</span>
      </div>
      <div class="pj-wrap">
        <div class="pj-grid pj-head">
          <span>{{ t('launch.colAccount') }}</span>
          <span>{{ t('launch.colStatus') }}</span>
          <span>{{ t('launch.colCreated') }}</span>
          <span>{{ t('launch.colReason') }}</span>
          <span class="pj-col-ops">{{ t('launch.colOps') }}</span>
        </div>
        <div class="prog-items">
          <div v-for="it in activeJob.items" :key="it.id" class="pj-grid pj-row">
            <div class="pj-acc" :title="accName(it.act_id) || it.act_id">
              <div class="pj-acc-name">{{ accNameOrTail(it.act_id) }}</div>
              <div class="pj-acc-id mono">{{ it.act_id }}</div>
              <div v-if="it.cred_name" class="pj-cred" :title="t('launch.credNameTip')">🔑 {{ it.cred_name }}</div>
            </div>
            <div><span :class="['pj-badge', itemBadgeCls(it, activeJob)]"><i v-if="itemBadgeCls(it, activeJob) === 'run'" class="pj-spin"></i>{{ itemBadgeCls(it, activeJob) === 'stuck' ? t('launch.itemStuck') : statusText(it.status) }}</span></div>
            <div class="pj-obj">
              <template v-if="it.campaign_id || it.adset_id || it.ad_id">
                <div class="pj-obj-line">
                  <span class="pj-obj-k">{{ t('launch.objCampaign') }}</span>
                  <a v-if="it.campaign_id" :href="adsUrl(it, activeJob?.platform)" target="_blank" class="pj-obj-id mono link" :title="adsLinkLabel(activeJob?.platform) + ' →'">{{ it.campaign_id }}</a>
                  <span v-else class="pj-obj-none">—</span>
                </div>
                <div class="pj-obj-line">
                  <span class="pj-obj-k">{{ t('launch.objAdset') }}</span>
                  <span v-if="it.adset_id" class="pj-obj-id mono">{{ it.adset_id }}</span>
                  <span v-else class="pj-obj-none">—</span>
                </div>
                <div class="pj-obj-line">
                  <span class="pj-obj-k">{{ t('launch.objAd') }}</span>
                  <span v-if="it.ad_id" class="pj-obj-id mono">{{ it.ad_id }}</span>
                  <span v-else class="pj-obj-none">—</span>
                </div>
                <div v-if="subcodeCount(it)" class="pj-obj-line sub" :title="it.subcode_slug">{{ t('launch.subcodesN', { n: subcodeCount(it) }) }}</div>
              </template>
              <span v-else class="pj-obj-none">—</span>
            </div>
            <div class="pj-reason-cell">
              <span v-if="it.status === 'creating' && it.progress" :class="['pj-progress', { stale: progressAge(it) > 120 }]">
                <i class="pj-spin"></i>{{ it.progress }}<em> · {{ fmtAge(progressAge(it)) }}</em>
                <b v-if="progressAge(it) > 120">{{ t('launch.progressStale') }}</b>
              </span>
              <span v-else-if="it.status === 'success' && it.progress" class="pj-progress done">{{ it.progress }}</span>
              <span v-else-if="it.error" :class="['pj-reason', { note: isItemNote(it), wrap: it.error_code === 'partial' }]" :title="itemErrTitle(it)">
                <span v-if="isItemNote(it) || itemCodeText(it)" :class="['pj-code', { note: isItemNote(it) }]">{{ isItemNote(it) ? t('launch.deployNote') : itemCodeText(it) }}</span>
                <span class="pj-reason-txt">{{ itemErrDisplay(it) }}</span>
              </span>
              <span v-else class="pj-obj-none">—</span>
            </div>
            <div class="pj-ops">
              <button v-if="it.status==='fail' || (['pending','creating'].includes(it.status) && !['pending','running'].includes(activeJob.status))" class="op primary sm" :title="it.status!=='fail' ? t('launch.retryStuckTip') : ''" @click="retryItem(it)">{{ t('common.retry') }}</button>
              <button v-if="it.status==='fail'" class="op sm" :title="t('launch.pagePickTip')" @click="openPagePick(it)">{{ t('launch.pagePickRetry') }}</button>
            </div>
          </div>
        </div>
      </div>
      <div v-if="!(activeJob.items||[]).length" class="empty-sm">{{ t('launch.noJobItems') }}</div>
    </div>
    <div v-else class="prog-loading">
      <template v-if="pollError">
        <div class="prog-err">{{ pollError }}</div>
        <button class="op primary sm" @click="open(activeJobId)">{{ t('common.retry') }}</button>
      </template>
      <template v-else>{{ t('launch.loadingJob') }}</template>
    </div>
  </el-dialog>
  <!-- 换主页重试弹窗：强绑主页账户「可推广对象不匹配」失败时选账户实际绑定主页再试 -->
  <el-dialog v-model="pagePickOpen" :title="t('launch.pagePickTitle')" width="460px" append-to-body>
    <div class="pp-hint">{{ t('launch.pagePickHint') }}</div>
    <div v-loading="pagePickLoading" class="pp-list">
      <label v-for="p in pagePickPages" :key="p.id" :class="['pp-row', { on: pagePickSel === p.id }]">
        <input type="radio" name="pp-sel" :value="p.id" v-model="pagePickSel" />
        <span class="pp-name">{{ p.name }}</span>
        <span v-if="p.via_cred" class="pp-via" :title="t('launch.pagePickVia')">{{ p.via_cred }}</span>
        <span :class="['pp-ad', p.can_advertise ? 'ok' : 'warn']">{{ p.can_advertise ? t('launch.pagePickAdOk') : t('launch.pagePickAdNo') }}</span>
        <span class="pp-fans">{{ p.fan_count || 0 }} {{ t('launch.pagePickFans') }}</span>
      </label>
      <div v-if="!pagePickPages.length && !pagePickLoading" class="empty-sm">{{ t('launch.pagePickNone') }}</div>
    </div>
    <template #footer>
      <button class="btn" @click="pagePickOpen = false">{{ t('common.cancel') }}</button>
      <button class="btn primary" :disabled="!pagePickSel" @click="retryWithPage">{{ t('launch.pagePickConfirm') }}</button>
    </template>
  </el-dialog>
</template>

<style scoped>
.btn{padding:7px 14px;border:1px solid var(--bd);background:var(--bg2);color:var(--t1);border-radius:6px;font-size:13px;cursor:pointer;font-family:inherit}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn:disabled{opacity:.5}
.op{background:none;border:1px solid var(--bd);color:var(--t2);font-size:12px;cursor:pointer;padding:4px 10px;border-radius:6px;font-family:inherit;white-space:nowrap;transition:all .15s}
.op.primary{color:var(--ac);border-color:rgba(10,132,255,.45);background:var(--acg);font-weight:600}
.op.primary:hover{background:var(--ac);color:#fff}
.op.primary.sm{padding:2px 8px;font-size:11px}
.op.sm{padding:2px 8px;font-size:11px}
.op:hover{color:var(--ac);border-color:var(--ac)}
.empty-sm{padding:30px;text-align:center;color:var(--t3);font-size:13px}
/* 部署进度弹窗：表格式网格（定宽列，行高统一，斑马纹） */
.prog-sum{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:10px 12px;margin-bottom:6px;background:var(--bg3);border:1px solid var(--bd);border-radius:var(--rs)}
.ps-job{font-size:12px;color:var(--t2);background:var(--bg2);border:1px solid var(--bd);border-radius:4px;padding:1px 7px;line-height:1.6;flex:none}
.prog-status{font-size:11px;padding:2px 10px;border-radius:var(--rs);font-weight:600;white-space:nowrap;flex:none}
.prog-status.completed{color:var(--success);background:rgba(52,199,89,.13)}
.prog-status.partial_failed{color:var(--warning);background:rgba(255,159,10,.13)}
.prog-status.running{color:var(--ac);background:rgba(10,132,255,.13)}
.prog-status.failed{color:var(--error);background:rgba(255,69,58,.13)}
.prog-status.pending{color:var(--t2);background:var(--bg2)}
.ps-metric{display:flex;align-items:baseline;gap:5px;white-space:nowrap}
.ps-metric em{font-style:normal;font-size:11px;color:var(--t3)}
.ps-metric b{font-size:14px;font-weight:600;color:var(--t1);font-variant-numeric:tabular-nums}
.ps-metric.ok b{color:var(--success)}
.ps-metric.err b{color:var(--error)}
.ps-metric.run b{color:var(--ac)}
.ps-times{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--t3);padding:0 2px 8px;font-variant-numeric:tabular-nums}
.pj-wrap{border:1px solid var(--bd);border-radius:var(--rs);overflow-x:auto}
.pj-grid{display:grid;grid-template-columns:minmax(150px,1.1fr) 96px minmax(200px,1.5fr) minmax(160px,1.7fr) auto;gap:8px 12px;align-items:center;padding:8px 12px;font-size:12px;min-width:700px}
.pj-head{background:var(--bg2);color:var(--t3);font-size:11px;font-weight:600;padding:6px 12px;border-bottom:1px solid var(--bd);white-space:nowrap}
.pj-col-ops{text-align:center}
.prog-items{max-height:52vh;overflow-y:auto}
.pj-row{border-bottom:1px solid var(--bd);font-variant-numeric:tabular-nums;min-height:56px}
.pj-row:last-child{border-bottom:none}
.pj-row:nth-child(even){background:color-mix(in srgb, var(--bg3) 55%, transparent)}
.pj-acc{min-width:0}
.pj-acc-name{font-size:13px;color:var(--t1);font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.5}
.pj-acc-id{font-family:var(--font-mono);font-size:11px;color:var(--t3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.5}
.pj-cred{font-size:11px;color:var(--ac);background:var(--acg);border-radius:4px;padding:0 6px;display:inline-block;line-height:1.6;margin-top:2px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* 状态徽标：成功=绿实心 / 失败=红描边 / 进行=中性转圈 / 卡死=橙 */
.pj-badge{display:inline-flex;align-items:center;gap:5px;height:20px;padding:0 9px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;line-height:1}
.pj-badge.ok{background:var(--success);color:#0b2916}
.pj-badge.err{color:var(--error);background:rgba(255,69,58,.13);border:1px solid rgba(255,69,58,.45)}
.pj-badge.run{color:var(--t2);background:var(--bg3);border:1px solid var(--bd)}
.pj-badge.stuck{color:var(--warning);background:rgba(255,159,10,.12);border:1px solid rgba(255,159,10,.5)}
.pj-spin{width:10px;height:10px;border-radius:50%;border:1.5px solid var(--bd2);border-top-color:var(--ac);animation:pjspin .8s linear infinite;flex:none}
.pj-progress{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--tx2);line-height:1.35}
.pj-progress em{font-style:normal;color:var(--tx3);white-space:nowrap}
.pj-progress.done{color:var(--tx3)}
.pj-progress.stale{color:#c07818;font-weight:500}
.pj-progress.stale .pj-spin{border-top-color:#c07818}
.pj-progress.stale b{font-weight:600}
@keyframes pjspin{to{transform:rotate(360deg)}}
/* 创建物列：系列/组/广告 ID 各一行（label 定宽，ID 用 mono 对齐） */
.pj-obj{display:flex;flex-direction:column;gap:1px;min-width:0}
.pj-obj-line{display:flex;align-items:baseline;gap:8px;min-width:0}
.pj-obj-k{font-size:11px;color:var(--t3);flex:none;width:60px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pj-obj-id{font-family:var(--font-mono);font-size:11px;color:var(--t2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-variant-numeric:tabular-nums}
a.pj-obj-id, .pj-obj-id.link{color:var(--ac);cursor:pointer}
.pj-obj-id.link:hover{text-decoration:underline}
.pj-obj-line.sub{font-size:11px;color:var(--t3)}
.pj-obj-none{font-size:12px;color:var(--t3);opacity:.6}
/* 原因列：error_code 徽标 + 文本截断（title 悬浮全文）；note=成功行的部署提示（中性，非红） */
.pj-reason-cell{min-width:0}
.pj-reason{display:flex;flex-direction:column;gap:3px;min-width:0}
.pj-code{align-self:flex-start;font-size:10px;padding:0 6px;border-radius:4px;line-height:1.6;font-weight:600;white-space:nowrap;color:var(--error);background:rgba(255,69,58,.12)}
.pj-code.note{color:var(--ac);background:rgba(10,132,255,.12)}
.pj-reason-txt{font-size:11px;color:var(--error);line-height:1.5;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;word-break:break-all}
.pj-reason.wrap .pj-reason-txt{-webkit-line-clamp:4}
.pj-reason.note .pj-reason-txt{color:var(--t2)}
.pj-ops{display:flex;justify-content:center;gap:4px;flex-wrap:nowrap;white-space:nowrap}
.prog-loading{padding:40px;text-align:center;color:var(--t3);font-size:13px}
.prog-err{color:var(--error);margin-bottom:12px;font-size:13px}
/* 换主页重试弹窗 */
.pp-hint{font-size:12px;color:var(--t3);line-height:1.5;margin-bottom:10px}
.pp-list{display:flex;flex-direction:column;max-height:320px;overflow-y:auto}
.pp-row{display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--bd);border-radius:8px;margin-bottom:6px;cursor:pointer;font-size:13px}
.pp-row:hover{border-color:var(--ac)}
.pp-row.on{border-color:var(--ac);background:color-mix(in srgb, var(--ac) 8%, transparent)}
.pp-name{flex:1;min-width:0;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pp-ad{font-size:10px;padding:1px 7px;border-radius:9px;flex-shrink:0}
.pp-ad.ok{color:var(--success);background:rgba(52,199,89,.13)}
.pp-ad.warn{color:var(--warning);background:rgba(255,159,10,.13)}
.pp-via{font-size:10px;color:var(--t3);background:var(--bg3);padding:1px 7px;border-radius:4px;max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex-shrink:0}
.pp-fans{font-size:11px;color:var(--t3);flex-shrink:0}
</style>
