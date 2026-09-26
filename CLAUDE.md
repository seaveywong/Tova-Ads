# ToveAds 2.0 — 项目入口（CLAUDE.md）

多平台（Facebook/TikTok）多租户广告管理 SaaS。Python FastAPI 后端（Vultr）+ Vue3/Element Plus 前端（Cloudflare Pages）。
**新会话/新 AI 先读此文件**，再按需读详细文档。改任何东西前看 auto-memory `toveads-dev-sop`（铁律+部署+坑）。

## 铁律（违反出事，详见 auto-memory）
1. **新功能/改动先经用户同意**（`must-approve-before-do`）——没叫做的别自作主张。
2. **改代码先 commit 再部署**（`git-commit-before-deploy`）——回滚安全网。repo 在 `toveads/` 级。
3. **restart 前 venv py_compile + `from app.main import app` 双门**（本机无 python，只能服务器跑）。
4. **通知 emit_notification 必带 dedup_recent**（`notify-dedup-mandatory`，否则 spam）。
5. 日期双基准不可混（`toveads-date-dual-basis`）；输入框不预填默认值。
6. **is_managed 软删**：当前操作只算 managed=true 账户；历史数据（perf_snapshots）保留全部。
7. **并行部署防护（多会话/多 AI 共仓时必做）**：① 前端 deploy 前 `git fetch && git pull --rebase`，确认无他人未提交/在途改动；② build 必须基于最新树（产物才包含他人 commit，不顶掉）；③ deploy 后 `curl -s https://app.tovaads.com/ | grep -oE 'index-[A-Za-z0-9_-]+\.js'` 比对 live hash == 本地 `dist/assets/index-*.js`，对不上 = 有人插队顶了你的部署，停下重收敛再 build+deploy，别盲目继续。后端同理：改前先 `git pull --rebase`，上传前确认目标文件未被他人动过。

## 查找纪律（省 token 核心）
**贵的不是文件大小，是探索（grep→读错→再读）。杀探索=省钱。**
- 先 Grep 定位行号，再 Read 窄窗口（±15 行），**别整文件读**。
- **Edit 后不重读验证**——Edit 匹配失败会报错，成功就生效。
- 多个小改批量一次部署（一次 backup→上传→门→restart→health→commit），别一改一部署。

## 后端结构（`backend/app/`）
| 层 | 目录 | 找什么 |
|---|---|---|
| 路由 | `routers/` | HTTP 端点。按职责分文件：`fb.py`(账户/令牌/载入/import) · `ads.py`(广告管理器) · `launch.py`(落地页CRUD+worker) · `launch_templates.py`(投放模板+部署runner) · `landing.py`(worker/route_next) · `landing_lib.py`(像素/域名) · `landing_events.py`(落地日志) · `subcodes.py`(子码) · `guard.py`(规则/哨兵/保活手动触发) · `dashboard.py`(看板) · `assets.py`+`ai.py`(素材+AI文案) · `form_templates.py`(表单/消息) · `fb_apps.py`+`fb_oauth.py`(App管理/OAuth) · `kpi.py` · `notify.py`+`tg_webhook.py` · `rbac.py` · `auth.py` · `settings.py` · `admin.py` · `tickets.py` · `compliance.py` · `backup.py` · `audiences.py` |
| 服务 | `services/` | 业务逻辑。`guard_engine.py`(巡检/哨兵/保活/落地屏蔽扫描,最大) · `ad_ops.py`(部署) · `account_sync.py`/`ads_cache_sync.py`/`fx_sync.py`(同步cron) · `budget_alerts.py` · `kpi_resolver.py` |
| 核心 | `core/` | `fb_client.py`+`fb_tokens.py`(FB API+多令牌RR轮换) · `ad_builder.py` · `page_post.py`(跟帖) · `database.py`(SuperSessionLocal/get_db/advisory lock) · `deps.py`(CurrentUser/权限) · `i18n.py`+`error_i18n.py` · `ai_client.py`+`ai_purposes.py` · `config.py` · `cf_client.py` · `kpi_mapping.py` · `notify_utils.py` |
| 模型 | `models/` | ORM 表（`__tablename__`）。文件名即分组：`fb.py`(credentials/accounts) · `launch.py`+`launch_template.py` · `landing_lib.py` · `guard.py` · `perf.py` · `auth.py` · `ads_cache.py` · `page_post.py` |
| 迁移 | `alembic/versions/` | `00xx_*.py`，revision 链，**末尾必 GRANT toveads_app + toveads_super** |

## 前端结构（`frontend/src/`）
- `views/` — 一文件一页：Dashboard/Landing/LandingLogs/LaunchTemplates/FormTemplates/Assets/Ads/AdManager/Tokens/Guard/Settings/AuditLog/Members/AdminTeams/KpiMapping/Login。
- `composables/` — `useStatus.js`(状态术语registry) · `useDateRange.js`(北京业务日) · `useLocale.js`(中英切换) · `useFbError.js`(FB错误翻译) · `useTheme/useTz/useError`。**改状态/日期标签先改 useStatus/useDateRange**。
- `locales/` — `zh.js`+`en.js` + `views/*.js`。**改文案两份同步，en 零 CJK**（详见 auto-memory `i18n-system`）。
- 部署：`cd frontend && npm run build`（须✓built）→ `wrangler pages deploy dist --project-name tovaads --branch master`（**master 不是 main**）。

## 部署速查（详见 `toveads-dev-sop`）
```
export MSYS_NO_PATHCONV=1 MIRA_SSH_HOST=45.76.177.37 MIRA_SSH_USER=root MIRA_SSH_PASS='2uC}7sAFC2nhu5zp'
cd /d/dev/Mira_One
node _putx.js toveads/backend/<file> /opt/toveads/backend/<file>
node _sshx.js 'cd /opt/toveads/backend && venv/bin/python -m py_compile <file> && venv/bin/python -c "from app.main import app" && echo OK && systemctl restart toveads && sleep 2 && systemctl is-active toveads && curl -s http://127.0.0.1:8000/health'
```
坑：`MSYS_NO_PATHCONV=1` 防 Git Bash 路径转换；cwd 漂移报 module not found 就 cd 回 `/d/dev/Mira_One`；前端 build cwd 必须在 frontend。

## i18n 裸键零容忍（2026-09-25 铁律）
- **禁止在 UI 上出现裸 i18n 键**（如 `adm.copiedVal`、`domains.tabBuy`）——用户已两次抓到（domains 命名空间嵌错层级 + adm.copiedVal 跨命名空间引用），**写进 AI 交接文档，违反=改动整体回退**。
- **验证必做**：①组件新增 `t('ns.key')` 时 grep 确认键存在于 zh.js/en.js（含嵌套对象路径）；②每批前端改动 build 后跑 `node /d/dev/Mira_One/_audit_ui_text.js`（17 路由×2 语言裸键/模板泄漏/CJK 反向泄漏零容忍）；③跨命名空间引用键（如 dashboard 组件里用 common.xxx）必须确认目标命名空间有该键——**别凭记忆写命名空间前缀**。
- 审计器路径：`D:/dev/Mira_One/_audit_ui_text.js`（页面级）+ `D:/dev/Mira_One/_chk_keys.cjs`（组件级 t() 键校验）。

## 标准化开发流程（2026-09-26 用户拍板——不做一半就上线）
**任何新功能必须走完四步才能部署：**
1. **调研**：FB API 能不能做？FB UI 怎么做的？完整功能地图（含周边可以一起做的）？→ 不做没调研过的功能
2. **CLI 实测**：在服务器用 Python 直调 FB API 验证真的能成功（不是猜参数）→ 实测不过不上代码
3. **复审**：做完后全维度检查（i18n 裸键/权限/NameError/端点 smoke/截图断言）→ 带 bug 的功能不上线
4. **文档**：TECH_REVIEW 追记 + CLAUDE.md 更新

**禁止行为：**
- 禁止只写代码不调 API 实测（BM 邀请 500 事故：写了邀请功能但 App 没过 Review——CLI 一测就知道）
- 禁止功能做一半上线（BM 只做了邀请没做资产分配）
- 禁止不跑审计器就交付（i18n 裸键两起事故）

## 多租户 / RLS
两套 session：`get_db`=RLS 受限（普通请求）/ `SuperSessionLocal`=BYPASSRLS（注册/平台级/定时任务）。`advisory lock`(acquire_run_lock) 防 gunicorn 多 worker 重复跑 cron，**锁号必须唯一**（现 101-119 已占，新增从 120 起）。

## 详细文档（按需读，别全读）
- `TECH_REVIEW.md` — 每次大改的复审记录（概述+变更表+迁移+结论+commit）。改完按 `tech-review-format` 追加。
- `TK_接入规划.md` — TikTok 接入方案（✅ P0-P4 已上线 2026-09-02，剩 sandbox 实测）。`TK_开发者申请指引.md` — 用户侧申请步骤。
- auto-memory：`toveads-dev-sop`(SOP全流程) · `review-standard`(主管复审6维度) · `i18n-system` · `page-post-follow-mode`(跟帖) · `keepalive-creative-fix`(保活code3) · `token-dispatch-planning`(多令牌) · `landing-pixel-pipeline`。
