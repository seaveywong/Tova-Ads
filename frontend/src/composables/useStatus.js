// 中央状态术语 registry。所有"状态枚举 → 翻译 key + 样式类"集中在此，
// 页面只消费、不自定义映射。新增状态只改这里，全局生效。
// label 字段存的是 i18n key；resolver 在返回时调 t() 解析，故 locale 切换实时生效，
// 且调用方无需改动（仍用 xxxStatus(s).label）。
// cls 约定：ok(绿/正常) / warn(黄/注意) / off(灰/停用) / err(红/异常)
import i18n from '../i18n'
const t = i18n.global.t

// FB 广告 / 系列 / 组 effective_status
export const FB_AD_STATUS = {
  ACTIVE:            { key: 'status.adActive',          cls: 'ok' },
  PAUSED:            { key: 'status.adPaused',           cls: 'off' },
  CAMPAIGN_PAUSED:   { key: 'status.adCampaignPaused',   cls: 'off' },
  ADSET_PAUSED:      { key: 'status.adsetPaused',        cls: 'off' },
  ARCHIVED:          { key: 'status.adArchived',         cls: 'off' },
  DELETED:           { key: 'status.adDeleted',          cls: 'off' },
  DISAPPROVED:       { key: 'status.adDisapproved',      cls: 'err' },
  PENDING_REVIEW:    { key: 'status.adReview',           cls: 'warn' },
  REVIEW_IN_PROGRESS:{ key: 'status.adReview',           cls: 'warn' },
  PREVIEW:           { key: 'status.adPreview',          cls: 'warn' },
  IN_PROCESS:        { key: 'status.adInProcess',        cls: 'warn' },
  WITH_ISSUES:       { key: 'status.adWithIssues',       cls: 'warn' },
}
export const fbAdStatus = (s) => {
  const e = FB_AD_STATUS[s]
  return e ? { label: t(e.key), cls: e.cls } : { label: s || '—', cls: 'off' }
}

// TikTok 广告状态（TT ad/get 的 status / opt_status；对照 core/tt_client.py 的
// _STATUS_MAP{ACTIVE→STATUS_ENABLE, PAUSED→STATUS_DISABLE, ARCHIVED/DELETED→STATUS_DELETE}
// 与 _OPT_STATUS{ENABLE/DISABLE/DELETE}。未知枚举原样透传）
export const TT_AD_STATUS = {
  STATUS_ENABLE:        { key: 'status.ttEnable',       cls: 'ok' },
  STATUS_DISABLE:       { key: 'status.ttDisable',      cls: 'off' },
  STATUS_DELETE:        { key: 'status.ttDelete',       cls: 'off' },
  STATUS_COMPLETE:      { key: 'status.ttComplete',     cls: 'off' },
  STATUS_BUDGET_EXCEED: { key: 'status.ttBudgetExceed', cls: 'warn' },
  IN_PROCESS:           { key: 'status.ttInProcess',    cls: 'warn' },
  // opt_status（写操作回读/管理器直显）
  ENABLE:  { key: 'status.ttEnable',  cls: 'ok' },
  DISABLE: { key: 'status.ttDisable', cls: 'off' },
  DELETE:  { key: 'status.ttDelete',  cls: 'off' },
}
export const ttAdStatus = (s) => {
  const e = TT_AD_STATUS[s]
  return e ? { label: t(e.key), cls: e.cls } : { label: s || '—', cls: 'off' }
}

// TikTok 审核展示状态（ad 的 show_status；SHOW_STATUS_* 家族，其余原样透传）
export const TT_SHOW_STATUS = {
  SHOW_STATUS_YES:       { key: 'status.ttShowYes',      cls: 'ok' },
  SHOW_STATUS_NOT_START: { key: 'status.ttShowNotStart', cls: 'warn' },
  SHOW_STATUS_NO:        { key: 'status.ttShowNo',       cls: 'err' },
}
export const ttShowStatus = (s) => {
  const e = TT_SHOW_STATUS[s]
  return e ? { label: t(e.key), cls: e.cls } : { label: s || '—', cls: 'off' }
}

// 账户 account_status（FB 数字码）
export const ACCOUNT_STATUS = {
  1:   { key: 'status.accActive',       cls: 'ok' },
  2:   { key: 'status.accDisabled',     cls: 'off' },
  3:   { key: 'status.accUnsettled',    cls: 'warn' },
  7:   { key: 'status.accBanned',       cls: 'err' },
  9:   { key: 'status.accPendingClose', cls: 'warn' },
  100: { key: 'status.accPendingClose', cls: 'warn' },
  101: { key: 'status.accClosed',       cls: 'off' },
}
export const accountStatus = (code) => {
  const e = ACCOUNT_STATUS[Number(code)]
  return e ? { label: t(e.key), cls: e.cls } : { label: '—', cls: 'off' }
}

// 部署任务状态
export const JOB_STATUS = {
  pending:        { key: 'status.jobPending',   cls: 'off' },
  running:        { key: 'status.jobRunning',   cls: 'warn' },
  completed:      { key: 'status.jobCompleted', cls: 'ok' },
  partial_failed: { key: 'status.jobPartial',   cls: 'warn' },
  failed:         { key: 'status.jobFailed',    cls: 'err' },
}
export const jobStatus = (s) => {
  const e = JOB_STATUS[s]
  return e ? { label: t(e.key), cls: e.cls } : { label: s || '—', cls: 'off' }
}

// 部署单项状态
export const ITEM_STATUS = {
  pending:  { key: 'status.itemPending',  cls: 'off' },
  creating: { key: 'status.itemCreating', cls: 'warn' },
  success:  { key: 'status.itemSuccess',  cls: 'ok' },
  fail:     { key: 'status.itemFail',     cls: 'err' },
}
export const itemStatus = (s) => {
  const e = ITEM_STATUS[s]
  return e ? { label: t(e.key), cls: e.cls } : { label: s || '—', cls: 'off' }
}

// 子码状态
export const SUBCODE_STATUS = {
  active:   { key: 'status.subActive',   cls: 'ok' },
  reserved: { key: 'status.subReserved', cls: 'off' },
  archived: { key: 'status.subArchived', cls: 'off' },
  deleted:  { key: 'status.subDeleted',  cls: 'err' },
}
export const subcodeStatus = (s) => {
  const e = SUBCODE_STATUS[s]
  return e ? { label: t(e.key), cls: e.cls } : { label: s || '—', cls: 'off' }
}

// 落地页状态
export const LP_STATUS = {
  published: { key: 'status.lpPublished', cls: 'ok' },
  draft:     { key: 'status.lpDraft',     cls: 'off' },
  archived:  { key: 'status.lpArchived',  cls: 'off' },
}
export const lpStatus = (s) => {
  const e = LP_STATUS[s]
  return e ? { label: t(e.key), cls: e.cls } : { label: s || '—', cls: 'off' }
}

// 租户 / 成员状态
export const TENANT_STATUS = {
  active:    { key: 'status.tenantActive',    cls: 'ok' },
  invited:   { key: 'status.tenantInvited',   cls: 'warn' },
  suspended: { key: 'status.tenantSuspended', cls: 'off' },
  archived:  { key: 'status.tenantArchived',  cls: 'off' },
}
export const tenantStatus = (s) => {
  const e = TENANT_STATUS[s]
  return e ? { label: t(e.key), cls: e.cls } : { label: s || '—', cls: 'off' }
}

// 素材 AI 分析状态
export const AI_STATUS = {
  pending:   { key: 'status.aiPending',   cls: 'off' },
  analyzing: { key: 'status.aiAnalyzing', cls: 'warn' },
  done:      { key: 'status.aiDone',      cls: 'ok' },
  failed:    { key: 'status.aiFailed',    cls: 'err' },
}
export const aiStatus = (s) => {
  const e = AI_STATUS[s]
  return e ? { label: t(e.key), cls: e.cls } : { label: t('status.aiNone'), cls: 'off' }
}
