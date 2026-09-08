# 广告管理器重构提示词 — 2026-09-09

> **2026-09-09 续接提示**：本轮已有未部署改动，先读 [交接_广告管理器本轮收尾_20260909.md](交接_广告管理器本轮收尾_20260909.md)。含已通过检查、真实完成范围和待验收缺口；不能按本文旧现状直接部署。

## 你的任务

把 ToveAds 2.0 的广告管理器（AdManager）做到 **1:1 Facebook 广告管理器**，后端能通、数据准确、交互一致。**先看现状→找不足→直接改或重构**。不要只列问题不动手。

## 必读文件（按序）

1. `交接_广告管理器现状.md` — 完整现状 + 已知 11 条不完美 + 代码位置
2. `蓝图_FB广告管理器创建流.md` — FB 官方逐面板字段表（Wayback+API v25 实证）
3. `系统串联全景.md` — 全系统数据流（看「巡检→ads_cache→管理器」链路）
4. `frontend/src/views/AdManager.vue` — 主文件（~1000行）
5. `backend/app/routers/ads.py` — 后端 API
6. `backend/app/services/ads_cache_sync.py` — 数据同步

## 1:1 对标基准（FB Ads Manager 2025-2026）

FB 广告管理器的核心交互（你要对齐的）：

| FB 功能 | 我们现状 | 差距 |
|---|---|---|
| 三层浏览（系列/组/广告） | ✅ 有 | 面包屑不直觉、列太多挤压 |
| 状态开关 | ✅ 有 | 脱管账户开关应禁用+提示 |
| 批量操作 | ✅ 有 | 无确认反馈汇总 |
| 预算编辑 | ✅ 有 | 日/总不一致（内联 vs 弹窗） |
| 改名 | ✅ 有 | - |
| 日期筛选 | ✅ 有 | - |
| 搜索 | ✅ 有 | 只搜名称/ID，不搜跨层 |
| 排序 | ✅ 有 | 不记忆 |
| 列自定义 | ❌ 没有 | FB 可选显示/隐藏列 |
| 细分（Breakdowns）| ❌ 没有 | 按年龄/性别/地区/版位/设备拆解 |
| 规则直接在行内创建 | ❌ 没有 | FB 可从广告行直接建自动化规则 |
| 系列嵌套组嵌套广告 | ✅ 有 | 钻取不够直觉 |
| 数据列 | ✅ 有 | 成效(FB口径)/综合转化 双列刚上线 |
| 脱管/被禁标注 | ✅ 有 | 刚上线，需验证 |
| 实时核验 | ✅ 有 | FB 没有，我们独创（保留） |
| 潜客 Tab | ✅ 有 | FB 没有，我们独创（保留） |

## 已知 11 条不完美（从交接文档）

### P1（先修）
1. 脱管行没有时间戳标注（用户不知道数据是几点几分的快照）
2. 成效双列刚上线，`results_fb` 数据要下一轮巡检才有值
3. 三层导航面包屑不直觉
4. 广告层列太多（8列），小屏幕挤压
5. 搜索只搜当前层名称/ID

### P2（该修）
6. 批量操作无确认反馈
7. 创意预览不稳定、触发不直觉
8. 日预算内联编辑 vs 总预算弹窗不一致
9. 排序不记忆

### P3（可后）
10. ads_cache 15min vs 巡检 5min 双数据流不一致
11. 脱管账户数据无过期标注

## 你应该做的

1. **逐条对齐 FB**：打开 [ads.facebook.com](https://ads.facebook.com) 看 FB 的广告管理器长什么样（如果你能访问的话），或者参照 `蓝图_FB广告管理器创建流.md` 的逐面板字段表
2. **修复 P1 所有 5 条**——这些都是用户直接感知的体验缺口
3. **实现列自定义**——FB 的核心 UX 特性，用户可以选显示/隐藏哪些列
4. **统一编辑交互**——日/总预算都用内联编辑，消除不一致
5. **加面包屑导航**——系列 › 组 › 广告，点击任意层返回
6. **如果发现代码结构问题**——直接重构，不要绕着走
7. **后端必须能通**——改完后部署，验证 API 返回 200 且数据正确

## 铁律（违反出事）

1. **改代码先 git commit 再部署**（回滚安全网）
2. **build 后必须 `grep` 验证产物包含新代码再部署**（build 失败不报错只部署旧版——今天踩过 3 次）
3. **Vue 模板用 `{{ }}` 双花括号**（单花括号/三花括号都不渲染）
4. **i18n zh/en 成对、en 零 CJK、无字面 `{{`**（vue-i18n 编译 throw，build 不报错但功能坏死）
5. **无保护期**（学习期默认 0，止损优先）
6. **资金操作必须二次回读**（暂停后回读 effective_status）
7. **不要预填输入框默认值**（空=用后端默认）
8. **UI 不放彩色 emoji**

## 部署命令

```bash
# 前端
cd /d/dev/Mira_One/toveads/frontend
npm run build
# 验证产物
grep -c "你的新功能关键词" dist/assets/AdManager-*.js
# 部署
CLOUDFLARE_API_TOKEN=<CF_TOKEN> npx wrangler pages deploy dist --project-name tovaads --branch master

# 后端
cd /d/dev/Mira_One
export MSYS_NO_PATHCONV=1 MIRA_SSH_HOST=45.76.177.37 MIRA_SSH_USER=root MIRA_SSH_PASS=<SSH_PASS>
node _putx.js toveads/backend/<file> /opt/toveads/backend/<file>
node _sshx.js 'cd /opt/toveads/backend && venv/bin/python -m py_compile <file> && venv/bin/python -c "from app.main import app" && systemctl restart toveads && sleep 2 && curl -s http://127.0.0.1:8000/health'
```

## 项目结构

```
toveads/
├── frontend/src/views/AdManager.vue    ← 主文件
├── frontend/src/views/Ads.vue          ← 广告账户页
├── frontend/src/composables/           ← useStatus/useDateRange/useLocale
├── frontend/src/locales/zh.js, en.js  ← i18n（改文案两份同步）
├── backend/app/routers/ads.py         ← API 路由
├── backend/app/services/ads_cache_sync.py ← 缓存同步
├── backend/app/services/guard_engine.py   ← 巡检（回写 ads_cache）
├── backend/app/models/ads_cache.py    ← ORM
└── backend/alembic/versions/          ← 迁移（新迁移从 0094 起，末尾必 GRANT）
```
