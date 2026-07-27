// 中央状态术语 registry。所有"状态枚举 → 中文标签 + 样式类"集中在此，
// 页面只消费、不自定义映射。新增状态只改这里，全局生效。
// cls 约定：ok(绿/正常) / warn(黄/注意) / off(灰/停用) / err(红/异常)

// FB 广告 / 系列 / 组 effective_status
export const FB_AD_STATUS = {
  ACTIVE:            { label: '投放中', cls: 'ok' },
  PAUSED:            { label: '已暂停', cls: 'off' },
  CAMPAIGN_PAUSED:   { label: '系列暂停', cls: 'off' },
  ADSET_PAUSED:      { label: '组暂停', cls: 'off' },
  ARCHIVED:          { label: '已归档', cls: 'off' },
  DELETED:           { label: '已删除', cls: 'off' },
  DISAPPROVED:       { label: '被拒', cls: 'err' },
  PENDING_REVIEW:    { label: '审核中', cls: 'warn' },
  REVIEW_IN_PROGRESS:{ label: '审核中', cls: 'warn' },
  PREVIEW:           { label: '预览', cls: 'warn' },
  IN_PROCESS:        { label: '处理中', cls: 'warn' },
  WITH_ISSUES:       { label: '有问题', cls: 'warn' },
}
export const fbAdStatus = (s) => FB_AD_STATUS[s] || { label: s || '—', cls: 'off' }

// 账户 account_status（FB 数字码）
export const ACCOUNT_STATUS = {
  1:   { label: '可用',   cls: 'ok' },
  2:   { label: '已禁用', cls: 'off' },
  3:   { label: '未结算', cls: 'warn' },
  7:   { label: '被封',   cls: 'err' },
  9:   { label: '待关闭', cls: 'warn' },
  100: { label: '待关闭', cls: 'warn' },
  101: { label: '已关闭', cls: 'off' },
}
export const accountStatus = (code) => ACCOUNT_STATUS[Number(code)] || { label: '—', cls: 'off' }

// 部署任务状态
export const JOB_STATUS = {
  pending:        { label: '等待', cls: 'off' },
  running:        { label: '运行中', cls: 'warn' },
  completed:      { label: '已完成', cls: 'ok' },
  partial_failed: { label: '部分失败', cls: 'warn' },
  failed:         { label: '失败', cls: 'err' },
}
export const jobStatus = (s) => JOB_STATUS[s] || { label: s || '—', cls: 'off' }

// 部署单项状态
export const ITEM_STATUS = {
  pending:  { label: '等待', cls: 'off' },
  creating: { label: '创建中', cls: 'warn' },
  success:  { label: '✓ 成功', cls: 'ok' },
  fail:     { label: '✗ 失败', cls: 'err' },
}
export const itemStatus = (s) => ITEM_STATUS[s] || { label: s || '—', cls: 'off' }

// 子码状态
export const SUBCODE_STATUS = {
  active:   { label: '投放中', cls: 'ok' },
  reserved: { label: '保留',   cls: 'off' },
  archived: { label: '已归档', cls: 'off' },
  deleted:  { label: '已删除', cls: 'err' },
}
export const subcodeStatus = (s) => SUBCODE_STATUS[s] || { label: s || '—', cls: 'off' }

// 落地页状态
export const LP_STATUS = {
  published: { label: '已发布', cls: 'ok' },
  draft:     { label: '草稿',   cls: 'off' },
  archived:  { label: '已归档', cls: 'off' },
}
export const lpStatus = (s) => LP_STATUS[s] || { label: s || '—', cls: 'off' }

// 租户 / 成员状态
export const TENANT_STATUS = {
  active:    { label: '正常',   cls: 'ok' },
  invited:   { label: '已邀请', cls: 'warn' },
  suspended: { label: '已停用', cls: 'off' },
  archived:  { label: '已归档', cls: 'off' },
}
export const tenantStatus = (s) => TENANT_STATUS[s] || { label: s || '—', cls: 'off' }

// 素材 AI 分析状态
export const AI_STATUS = {
  pending:  { label: '待分析', cls: 'off' },
  analyzing:{ label: '分析中', cls: 'warn' },
  done:     { label: '✓ 已分析', cls: 'ok' },
  failed:   { label: '✗ 失败',   cls: 'err' },
}
export const aiStatus = (s) => AI_STATUS[s] || { label: '未分析', cls: 'off' }
