// 权限键 → i18n 键映射（2026-09-27 审计 P1 修复：权限键是点分形（ads.read），i18n 是驼峰
// （members.perm.adsRead）——直拼 t('members.perm.' + k) 会显示裸键。Members/AdminTeams 共用，勿复制）
export const PERM_I18N_MAP = {
  'ads.read': 'members.perm.adsRead', 'ads.create': 'members.perm.adsCreate',
  'ads.pause': 'members.perm.adsPause', 'ads.resume': 'members.perm.adsResume',
  'ads.update': 'members.perm.adsUpdate', 'ads.delete': 'members.perm.adsDelete',
  'rules.read': 'members.perm.rulesRead', 'rules.create': 'members.perm.rulesCreate',
  'rules.edit': 'members.perm.rulesEdit', 'landing.manage': 'members.perm.landingManage',
  'assets.manage': 'members.perm.assetsManage', 'billing.view': 'members.perm.billingView',
  'billing.manage': 'members.perm.billingManage', 'members.invite': 'members.perm.membersInvite',
  'members.manage': 'members.perm.membersManage', 'audit.read': 'members.perm.auditRead',
}
