# ToveAds 2.0 — AI 交接文档（2026-09-05 BUG修复/UX 任务用）

> **给接手的 AI**：本文档自包含，请先完整读完再动手。项目所有者（用户）对流程有硬性要求（§3 铁律），
> 违反任何一条都会导致你的改动被整体回滚。做完任何一批修改，按 §6 验证 + §5.6 收尾流程走完才算完成。
>
> **本次任务范围**：BUG 修复 + UX/UI 优化。**不要**做新功能规划落地、不要重构引擎、不要动数据库 schema
> （除非用户当场明确要求）。

---

## 1. 系统是什么

**ToveAds 2.0** — 多平台（Facebook/TikTok）多租户广告管理 SaaS：
- **后端**：Python FastAPI + SQLAlchemy + PostgreSQL（RLS 多租户）+ APScheduler（16 个 cron）
- **前端**：Vue3 + Element Plus + vue-i18n（中英双语）+ Chart.js
- **部署**：后端在 Vultr（systemd 服务 `toveads`，gunicorn 4 worker）；前端在 Cloudflare Pages
- **业务链**：令牌授权 → 账户纳管 → 素材库(AI 文案) → 落地页工厂(防护/像素/子码/自检) → 投放模板
  → 批量部署 → 守护引擎（止损/扩量/哨兵，5min 巡检）→ 看板/告警(TG+站内) → 潜客 CRM

一句话：帮投放团队管几十个 FB/TT 广告账户，自动止损、自动告警、数据回流一站看。

## 2. 仓库与环境

```
D:\dev\Mira_One\                    ← 本地仓库根（Windows，Git Bash）
├── toveads/                        ← ★ 2.0 的全部（独立 git，remote=github.com:seaveywong/Tova-Ads.git）
│   ├── backend/app/                ← FastAPI（routers/services/core/models）
│   │   └── alembic/versions/       ← 迁移链 0001→0085（见 §2.2）
│   ├── frontend/src/               ← Vue3（views/ 一文件一页，composables/，locales/）
│   ├── CLAUDE.md                   ← 项目结构速查（先读）
│   ├── HANDOFF.md                  ← 本文
│   ├── TECH_REVIEW.md              ← 历次大改复审记录（改完要追加，见 §5.6）
│   └── _smoke_batch_f.py           ← 端到端断言 smoke（§6）
├── server_src/                     ← 1.0 Mira（旧系统，bug-fix-only，本任务别碰）
├── _sshx.js / _putx.js             ← SSH 执行/上传脚本（凭据走环境变量）
└── _deploy_*.sh                    ← 1.0 部署脚本（本任务别碰）
```

### 2.2 关键数字（2026-09-05 现状）
| 项 | 值 |
|---|---|
| git HEAD | `4c5b187`（main），tag **`backup-20260905-pre-handoff`** ← 本次任务前的完整恢复点 |
| 迁移链 | 0085 = head（0084 accounts.group_label/disable_reason，0085 user_tg_bindings.prefs）|
| advisory lock | 101-116 已占，**新增从 117 起** |
| API 版本 | v1.3.5，Graph API v25.0 |
| 登录 | seavey@tovaads.com（超管/tenant 1 owner） |

### 2.3 服务器与凭据
**所有凭据（SSH/CF token/登录账号）在 `toveads/CREDENTIALS.local.md`**——该文件不进 git
（secret scanning 会拦，凭据也绝不该进 git 历史），交接时直接打开给它。

- **ToveAds 后端**：Vultr（IP 见凭据文件），代码在 `/opt/toveads/backend`，venv 同目录，
  服务 `systemctl restart toveads`，DB=PostgreSQL 库名 `toveads`
- **前端 CF**：项目名 `tovaads`，**branch 是 `master` 不是 main**
- **SSH 脚本用法**（在 `D:\dev\Mira_One` 下，密码/IP 从凭据文件取）：
  ```
  export MSYS_NO_PATHCONV=1 MIRA_SSH_HOST=<ip> MIRA_SSH_USER=<user> MIRA_SSH_PASS='<pass>'
  node _putx.js toveads/backend/<file> /opt/toveads/backend/<file>     # 上传
  node _sshx.js '<shell 命令>'                                          # 远程执行
  ```
  ⚠️ 坑：每次 Bash 调用 env 不持久，每条命令都要带 export；cwd 漂移报 module not found 就 `cd /d/dev/Mira_One`；heredoc 内中文/引号会被 mangle——中文脚本用 `_putx.js` 传文件再跑。

## 3. 铁律（用户硬性要求，违反=回滚）

1. **所有新增功能/修改先经用户同意**——用户没叫做的千万别自作主张。拿不准就问。
2. **不允许任何保护期**：学习期/宽限/冷静类默认一律 0/关。止损优先于 FB 学习期（曾因默认 24h 学习期空耗 $51）。
3. **改代码必须先 git commit 再部署**（回滚安全网）。本地改完 → commit → push → 再部署。
4. **新功能必须带数据断言的端到端 smoke**——不能只验"不报错"。裸 except + 新功能 = 生产静默归零
   （3 处实证：UnboundLocalError / PG 42803 / regex 不匹配，全被 except 吞了半年没人知道）。
   现成模板：`toveads/_smoke_batch_f.py`（登录→调真端点→断言→清理，照抄结构）。
5. **通知 `emit_notification` 必带 `dedup_recent`**，否则 TG 刷屏（曾 1449 条事故）。
6. **i18n 双语**：改任何文案 zh/en 两份同步（`locales/zh.js`+`en.js` 或 `locales/views/*.js`），
   **en 零 CJK**。新加后端 400/409 消息要进 `core/error_i18n.py` 译表。
7. **输入框永远不预填默认值**（空=用后端默认）；卡片展示未填字段可显默认值。
8. **is_managed 软删**：当前操作只算 managed=true 账户；历史数据（perf_snapshots）保留全部。
9. **账户只显式导入**：令牌能管但没显式导入的账户绝不自动纳管（/fb/import 是唯一入口）。
10. **日期双基准不可混**：看数据=北京业务日（snapshot 按账户本地日字符串存）；账户级操作=账户本地当日。
11. **UI 不放架构 tagline**；代码注释只留技术性，去工作笔记口吻。
12. 每个新需求/文档标注"进文档" vs "当下做"。

## 4. 部署全流程（照抄即可）

### 4.1 后端
```bash
cd /d/dev/Mira_One
export MSYS_NO_PATHCONV=1 MIRA_SSH_HOST=<ip> MIRA_SSH_USER=<user> MIRA_SSH_PASS='<pass>'   # ← 从 CREDENTIALS.local.md 取
# 改完的每个文件先本地 py_compile（本机有 python 3.12）
python -m py_compile toveads/backend/app/<改的文件>
node _putx.js toveads/backend/app/<改的文件> /opt/toveads/backend/app/<改的文件>
# 服务器双门 + 重启 + health（多文件一次批量）
node _sshx.js 'cd /opt/toveads/backend && venv/bin/python -m py_compile <files> && venv/bin/python -c "from app.main import app" && echo GATE_OK && systemctl restart toveads && sleep 3 && systemctl is-active toveads && curl -s http://127.0.0.1:8000/health'
```
### 4.2 数据库迁移（如涉及）
```bash
node _sshx.js 'cd /opt/toveads/backend && venv/bin/python -m alembic upgrade head && venv/bin/python -m alembic current'
```
迁移文件规范：`00xx_名字.py`，revision 链接前一个，**末尾必 GRANT toveads_app + toveads_super 两角色**（+序列如有）。
### 4.3 前端
```bash
cd /d/dev/Mira_One/toveads/frontend && npm run build    # 必须 ✓built；cwd 必须在 frontend
CLOUDFLARE_API_TOKEN=<cf_token> npx wrangler pages deploy dist --project-name tovaads --branch master   # ← token 从 CREDENTIALS.local.md 取
```
### 4.4 日志排查
```bash
node _sshx.js 'journalctl -u toveads --since "1 hour ago" --no-pager | grep -iE "error|warning|traceback" | tail -30'
```

## 5. 工作流约定

### 5.1 探索纪律（省 token，也防改错）
大文件**永不整读**：先 Grep 拿行号 → Read 窄窗口（±15 行）。`guard_engine.py`≈3000 行、
`launch_templates.py`≈2100 行、`Dashboard.vue`≈2000 行。Edit 成功就生效，不重读验证。
多个小改批量一次部署，别一改一部署。

### 5.2 改前必查
- `toveads/CLAUDE.md`（结构速查）
- 相关模块的既有模式（如：告警→`emit_notification`+dedup；状态文案→`useStatus.js`；
  日期→`useDateRange.js`；FB 错误→`useFbError.js`+`error_i18n.py`）

### 5.3 完成定义（DoD）
1. 本地 py_compile / `npm run build` 过
2. 服务器双门过 + restart + `/health` ok
3. 断言 smoke 过（改什么断言什么——见 §6）
4. journalctl 无新 error
5. git commit + push（message 说明 why）
6. `TECH_REVIEW.md` 追加一段（概述+变更+验证+commit）

### 5.4 前端样式约定
- CSS 变量：`--ac`(主色)/`--bd`(边框)/`--bg2/--bg3`/`--t1/t2/t3`；**不要用 `--p`/`--border`（未定义陷阱）**
- 移动端：外壳抽屉 + `.form-l` 堆叠 + 表格横向滚动已就位，新页面沿用
- 表格排序原则：需关注/紧急在上，越往下优先级越低

### 5.5 已知大坑（勿重复踩）
| 坑 | 说明 |
|---|---|
| 裸 except | 吞 NameError/PG 错误半年不显形——新代码每个 try/except 自问会不会吞新引用 |
| RLS `set_config` | `is_local=false` 会随事务 rollback 回滚——RLS 冒烟每用例新 session |
| FastAPI 惰性 `_IncludedRouter` | `app.routes` 不展开子路由——用 HTTP 探测 404 vs 401 验证注册 |
| PG 聚合 | 子查询裸列+聚合必 42803——用 `query(func.count()).scalar()` 单值 |
| gunicorn 4 worker | 进程内状态（dict/全局变量）不共享——跨 worker 状态必须进 DB（streak/锁/RR 皆如此）|
| CF Pages | production 分支是 **master** |
| 花钱链 | 部署/暂停/预算全走已验证函数（`deploy_one_account`/`set_budget`/升级链），只加前置校验，**不要重写执行体** |
| 批量重试 | 批量模式 retry=整 item 重跑（不走同名幂等）——partial 汇总是唯一决策信息，勿遮蔽 |

### 5.6 收尾
每批改动：commit + push GitHub（冷备份即 git）→ TECH_REVIEW.md 追加。**用户会拿你的改动做 6 维度复审**
（对齐/SOP/i18n/FB API/数据层/坑），P0 会打回。

## 6. 验证工具

**现成断言 smoke**：`toveads/_smoke_batch_f.py`（服务器上跑）：
```bash
node _putx.js toveads/_smoke_batch_f.py /opt/toveads/backend/_smoke_batch_f.py
node _sshx.js 'cd /opt/toveads/backend && venv/bin/python _smoke_batch_f.py'
```
覆盖：分组标签 set/clear、TG 偏好 PUT、批量 preflight series_count、插值占位符拒绝、心跳。
**改了什么就在这个文件里加对应断言**，跑完 `SMOKE_RESULT: ALL_PASS` 才算过。

看板/前端改动：build 过 + 部署后人工开页面确认（用户会看）。

## 7. 备份与恢复（本次交接的保险）

| 层 | 位置 | 恢复方法 |
|---|---|---|
| git（代码） | GitHub `seaveywong/Tova-Ads`，tag `backup-20260905-pre-handoff`（=HEAD `4c5b187`） | `git checkout backup-20260905-pre-handoff` 或 `git reset --hard 4c5b187` 后重传服务器 |
| 服务器代码快照 | `/root/backups/toveads-code-20260905-pre-handoff.tar.gz`（59M，排除 venv） | `tar xzf ... -C /opt && systemctl restart toveads` |
| 数据库快照 | `/root/backups/toveads-db-20260905-pre-handoff.dump`（1.8M，pg_dump -Fc） | `sudo -u postgres pg_restore --clean -d toveads /root/backups/toveads-db-20260905-pre-handoff.dump` |
| MD5 校验 | `/root/backups/toveads-20260905-pre-handoff.md5` | `md5sum -c` 先验完整性 |

⚠️ DB restore 会清掉备份点之后的新数据（巡检快照/通知），只在代码回滚不够时用。优先 git 回滚。

**灾难恢复顺序**：① `git reset --hard 4c5b187` → ② 逐文件 `_putx.js` 重传（或 tar 恢复）→ ③ 双门+restart+health → ④ 跑 smoke → ⑤ 若 DB 也坏了才 pg_restore。

## 8. 当前系统状态快照（2026-09-05）

- 服务 active，health ok，24h journal 无未处理错误
- **两个 FB 账户（BSCH-TD-O336/O338）写权限被收回**——哨兵已自动进 24h 退避（`sentinel_perm_deny_*`
  标记），发过「写权限丢失」告警；用户会自行移除纳管。这不是 bug，别"修"它。
- FB App 在 dev 模式审核中（部分写操作受限）、TT 在等用户申请开发者——外部解锁前投放/保活实测做不了
- 近期已上线大批（详见 TECH_REVIEW.md 尾部）：批F（批量生成/分组/禁用原因/TG偏好/插值+巡检5项）、
  3-Agent 复审修复（P0×1+P1×5+P2×9）、哨兵权限退避、引擎可靠性批（脏数据沙箱/扩量核验/限流统一冷却/
  KPI 异常跳过告警/暂停链权限退避/scheduler 线程池）
- 规划文档已存档待用户讨论：`极简操作与自动驾驶规划.md`（**不要**开始实现，用户说"先存起来下次讨论"）

## 9. 本次任务建议工作法

1. 先跑一遍 `_smoke_batch_f.py` 确认基线 ALL_PASS
2. BUG 修复：用户会报具体问题；先 journalctl/DB 取证定位根因，再修（别猜）
3. UX：遵循 `交互好/数据清楚/逻辑显式` 标杆；列表排序"需关注在上"；改文案先看双语约定
4. 每完成一小批就走 §5.3 DoD；不确定的就停下来问用户
5. **绝对不要**：动 guard_engine 的执行语义（暂停/预算/止损逻辑刚做完可靠性加固+复审）、
   重新设计告警体系、改迁移链历史、删任何"看不懂"的防御性代码——那些几乎都是事故换来的

---
*生成：2026-09-05，by 主会话 AI（完整上下文在 auto-memory；本文档已浓缩全部关键约定）。*
