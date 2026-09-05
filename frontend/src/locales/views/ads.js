// Ads 命名空间扩展片段（广告账户页：分组标签 + 禁用原因副行）。zh/en 同文件。
// 注：ads 命名空间主体仍内联在 locales/zh.js / locales/en.js（本文件只承载新增键，
// 避免整段搬迁）；注册方式——zh.js 顶部 `import adsExtra from './views/ads'`，
// 并在 `ads: {` 花括号内首行插入 `...adsExtra.zh,`（en.js 同理用 adsExtra.en）。
// 新键与内联键无重名，先注册先被内联键覆盖也不会冲突（取并集）。
export default {
  zh: {
    groupCol: '分组',
    groupAll: '全部分组',
    groupFilterTip: '按分组筛选账户（选项=当前账户用到的分组）',
    groupSortTip: '点击按分组聚合（同组相邻，无分组沉底）；再点恢复默认排序',
    groupEditTitle: '设置分组',
    groupBatchTitle: '批量设置分组（{n} 个账户）',
    groupBatchNote: '将为选中的全部账户设置同一分组标签；留空并保存 = 清除分组。',
    groupPh: '如：主投组 / 测试组（留空=清除）',
    groupSet: '设分组',
    groupSaved: '已更新 {n} 个账户的分组',
    groupClearConfirm: '即将清除 {n} 个账户的分组标签（留空保存=清除）。确认清除？',
    drPrefix: '原因：',
  },
  en: {
    groupCol: 'Group',
    groupAll: 'All groups',
    groupFilterTip: 'Filter accounts by group (options come from groups in use)',
    groupSortTip: 'Click to cluster rows by group (ungrouped sink to bottom); click again to restore default order',
    groupEditTitle: 'Set group',
    groupBatchTitle: 'Set group for {n} accounts',
    groupBatchNote: 'Applies one group label to all selected accounts; saving with empty input clears the group.',
    groupPh: 'e.g. Main / Test (empty = clear)',
    groupSet: 'Set group',
    groupSaved: 'Group updated for {n} account(s)',
    groupClearConfirm: 'This will clear the group label of {n} account(s) (saving empty = clear). Confirm?',
    drPrefix: 'Reason: ',
  },
}
