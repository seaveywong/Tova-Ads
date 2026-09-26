// 部署任务展示/重试共享逻辑（2026-09-26 抽屉组件化：LaunchTemplates 已部署清单 /
// JobProgressDialog / DeployDrawer 三方共用——单一实现，勿在组件里复制）
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { GET, POST } from '../api'
import { showError } from './useError'
import { jobStatus, itemStatus, fbAdStatus } from './useStatus'
import { fbErrorText } from './useFbError'

export function useLaunchJobs() {
  const { t } = useI18n()

  // 账户名映射：懒拉全量账户建 {act_id: name}（复用 /fb/accounts，不加接口）
  const accNames = ref({})
  let _accNamesLoaded = false
  const ensureAccNames = async () => {
    if (_accNamesLoaded) return
    try {
      const all = await GET('/fb/accounts')
      const m = {}
      for (const a of (all || [])) if (a.act_id) m[a.act_id] = a.name || ''
      accNames.value = m; _accNamesLoaded = true
    } catch {}
  }
  const accName = (actId) => accNames.value[actId] || ''
  // 账户列主行：有名字用名字；没名字退 act_id 尾 4 位（全 ID 固定在副行）
  const accNameOrTail = (actId) => accName(actId) || 'act ' + String(actId).replace(/^act_/, '').slice(-4)

  const statusText = (s) => itemStatus(s).label
  const jobText = (s) => jobStatus(s).label

  // 时间解析（与 useTz.fmtTime 同规则：裸 "YYYY-MM-DD HH:MM:SS" 当 UTC）
  const parseTime = (s) => {
    if (!s) return null
    let d = new Date(s)
    if (isNaN(d) && typeof s === 'string') {
      const hasTz = s.endsWith('Z') || /[+-]\d\d:?\d\d$/.test(s)
      d = new Date(s.replace(' ', 'T') + (hasTz ? '' : 'Z'))
    }
    return isNaN(d) ? null : d
  }
  // 耗时：finished_at - created_at。后端重试会刷新 created_at（语义=最近一次执行），
  // 所以 finished_at 有值时=最近一轮耗时；未完成=距最近一次执行的已耗时（渲染时静态快照）
  const jobElapsed = (j) => {
    const s = parseTime(j?.created_at); if (!s) return null
    const e = parseTime(j?.finished_at) || new Date()
    const ms = e - s
    return ms < 0 ? 0 : ms
  }
  const fmtDur = (ms) => {
    if (ms == null) return '—'
    const sec = Math.round(ms / 1000)
    if (sec < 60) return sec + 's'
    const m = Math.floor(sec / 60)
    if (m < 60) return m + 'm ' + (sec % 60) + 's'
    return Math.floor(m / 60) + 'h ' + (m % 60) + 'm'
  }
  const jobRunningCount = (j) => (j?.items || []).filter(it => ['pending', 'creating'].includes(it.status)).length

  // 成功但带 error = 部署提示留痕（[像素]自愈/[受众]降级等）——info 级，别染成失败红
  const isItemNote = (it) => it.status === 'success' && !!it.error
  // 提示类 error_code/前缀（非失败）：直用 it.error 原文，不走 FB 译表
  const isNoteCode = (it) => it.error_code === 'auto_subcode_degraded' || /^\[(像素|受众)\]/.test(it.error || '')
  // 已知失败类 error_code：有真翻译才走译表（fbErrorText 对未知 code 返回 generic 兜底
  // 「Facebook 返回错误」非空串会掩盖真实原因——auto_subcode_degraded 提示被盖即是此坑）
  const FB_KNOWN_ERR_CODES = new Set(['cert_required', 'invalid_param', 'bid_required', 'regulated_opt', 'regulated_missing',
    'audience', 'audience_size', 'abuse', 'dev_mode', 'rate_limited', 'has_spend', 'no_write_token',
    'has_keepalive', 'no_page', 'no_page_token', 'no_asset', 'asset_missing'])
  // 原因列文案：partial/提示类直用原文；失败类仅已知 code 翻译；未知 code（含 'error'）
  // 显示 it.error 原文——翻译不到宁可不译，不给 generic 兜底
  const itemErrDisplay = (it) => {
    if (!it.error) return ''
    if (it.error_code === 'partial' || isNoteCode(it)) return it.error
    if (FB_KNOWN_ERR_CODES.has(it.error_code)) return fbErrorText(it.error_code) || it.error
    return it.error
  }
  // 悬浮全文：一律 it.error 原文（显示列可能已是翻译，title 补原始完整信息）
  const itemErrTitle = (it) => it.error || ''
  const itemCodeText = (it) => it.error_code === 'partial' ? t('launch.errPartial')
    : it.error_code === 'auto_subcode_degraded' ? t('launch.errDegrade')
    : it.error_code === 'no_id' ? t('launch.errNoId') : (it.error_code || '')
  const subcodeCount = (it) => (it.subcode_slug || '').split(',').filter(Boolean).length
  // 实时进度龄（item.updated_at = runner 心跳时间戳）——超 2 分钟无更新橙显「进程可能已中断」
  const progressAge = (it) => {
    if (!it.updated_at) return 0
    const ts = new Date(it.updated_at).getTime()
    return Number.isFinite(ts) ? Math.max(0, Math.round((Date.now() - ts) / 1000)) : 0
  }
  const fmtAge = (s) => s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60}s`
  // 状态徽标：ok=绿实心✓ / err=红 / run=中性转圈 / stuck=橙（job 已终态还停 pending/creating）
  const itemBadgeCls = (it, job) => {
    if (it.status === 'success') return 'ok'
    if (it.status === 'fail') return 'err'
    return ['pending', 'running'].includes(job?.status) ? 'run' : 'stuck'
  }
  const fbAdsUrl = (actId, campId) => `https://www.facebook.com/adsmanager/manage/campaigns?act=${actId}&selected_campaign_ids=${campId}`
  // TT 跳 TikTok Ads Manager（aadvid=广告主 ID）；plat 由调用点显式传（各自的平台，不共享状态）
  const ttAdsUrl = (actId) => `https://ads.tiktok.com/am/manage/campaigns?aadvid=${actId}`
  const adsUrl = (it, plat) => plat === 'tt' ? ttAdsUrl(it.act_id) : fbAdsUrl(it.act_id, it.campaign_id)
  const adsLinkLabel = (plat) => plat === 'tt' ? t('launch.ttAds') : t('launch.fbAds')
  const copyAdId = (id) => { if (!id) return; navigator.clipboard?.writeText(id); ElMessage.success(t('launch.adIdCopied', { id })) }
  const liveStatusColor = (s) => {
    const c = fbAdStatus(s).cls
    return c === 'ok' ? 'var(--success)' : c === 'err' ? 'var(--error)' : c === 'warn' ? 'var(--warning)' : 'var(--t3)'
  }

  // 重试 POST（partial 先确认——批量重试=整账户全部系列重跑，上轮已成功的会被重建）。
  // 返 true=已提交（调用方负责重启轮询）；false=取消/失败（已 toast）
  const submitItemRetry = async (job, it, body = {}) => {
    if (it.error_code === 'partial') {
      try {
        await ElMessageBox.confirm(t('launch.retryPartialConfirm'), t('common.confirm'),
          { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
      } catch { return false }
    }
    try {
      await POST(`/launch-templates/jobs/${job.id}/retry/${it.id}`, body)
      ElMessage.success(t('launch.retrySubmitted'))
      return true
    } catch (e) { showError(e, t('launch.retryFail')); return false }
  }

  return {
    accNames, ensureAccNames, accName, accNameOrTail,
    statusText, jobText, parseTime, jobElapsed, fmtDur, jobRunningCount,
    isItemNote, isNoteCode, itemErrDisplay, itemErrTitle, itemCodeText,
    subcodeCount, progressAge, fmtAge, itemBadgeCls,
    fbAdsUrl, ttAdsUrl, adsUrl, adsLinkLabel, copyAdId, liveStatusColor,
    submitItemRetry,
  }
}
