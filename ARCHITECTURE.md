# ToveAds 2.0 — 系统架构地图（2026-09-05，从代码自动核实）

> 配套 `HANDOFF.md`（操作手册）+ `CLAUDE.md`（目录速查）阅读。本文 = 架构全景 + 数据流 + 历史。
> 数字来源：脚本扫描 `backend/app/`（models/routers/main.py），非人工记忆。

---

## 1. 一图看懂数据流

```
                          ┌─────────── FB / TikTok Graph API ───────────┐
                          │  OAuth · adaccounts · insights · ads CRUD    │
                          └───────▲───────────────────────────▲─────────┘
                                  │读(5min巡检)               │写(部署/暂停/预算)
┌─────────────┐  授权    ┌────────┴─────────┐       ┌─────────┴──────────┐
│ Tokens 页    │────────▶│ fb_credentials   │       │ launch_templates    │
│ (OAuth+多令牌)│         │ tt_credentials   │       │ (模板=母版→批量系列) │
└─────────────┘         │ accounts(纳管)    │       └─────────┬──────────┘
                        └────────┬─────────┘                 │deploy job(异步)
                                 │RR轮换选令牌                 ▼
┌─────────────┐  素材    ┌────────┴─────────────────────────────────┐
│ Assets 素材库│────────▶│ guard_engine(巡检引擎,最大服务)             │
│ +AI文案/视觉 │         │  · 规则评估(止损/扩量10类)                  │
└─────────────┘         │  · 哨兵巡逻(3min kill-switch)              │
                        │  · watchdog/watchkeepalive/落地屏蔽扫描     │
┌─────────────┐  发布    │  └─命中→ pause(升级链+核验) / set_budget    │
│ Landing 落地页│────────▶│      ↓写 action_logs + emit_notification  │
│ (防护/像素/子码│         └────────┬─────────────────────────────────┘
│  /自检/子域名) │                  │快照
└─────────────┘         ┌──────────▼───────────┐     ┌──────────────┐
                        │ perf_snapshots(+tick) │────▶│ Dashboard 看板│──▶ 用户/TG告警
   landing_events(访问日志) + leads(潜客) ────────▶    │ 告警中心/潜客CRM│
                        └───────────────────────┘     └──────────────┘
```

## 2. 技术栈与运行形态

| 层 | 技术 | 部署 |
|---|---|---|
| 后端 | FastAPI + SQLAlchemy + APScheduler，Python 3.12 | Vultr `/opt/toveads/backend`，gunicorn 4 worker，systemd `toveads` |
| DB | PostgreSQL，**RLS 多租户**（tenant_id 行级隔离） | 同机，库名 `toveads`，双角色 `toveads_app`（应用）/`toveads_super`（运维） |
| 前端 | Vue3 + Element Plus + vue-i18n(zh/en) + Chart.js + Fuse.js | Cloudflare Pages 项目 `tovaads`，branch **master** |
| 迁移 | Alembic，链 0001→**0085**（head） | `venv/bin/python -m alembic upgrade head` |
| 外部 | FB Graph API v25.0（dev App 审核中）· TikTok Marketing API v1.3（等开发者审批）· Cloudflare DNS · Gemini/DeepSeek(AI) · Telegram Bot | |

**两种 session（关键机制）**：`get_db`=RLS 受限（普通请求，自动带租户）；`SuperSessionLocal`=BYPASSRLS
（cron/平台级操作，代码里显式过滤 tenant_id）。**跨 worker 状态必须进 DB**（advisory lock 101-116 /
system_settings 标记 / action_logs dedup），进程内 dict 在 gunicorn 4 worker 下不共享。

## 3. 数据模型全景（45 表，按域分组）

### 租户与权限（auth 域）
| 表 | 模型 | 说明 |
|---|---|---|
| tenants / users / tenant_memberships / invitations / roles | Tenant/User/... | 多团队多租户 + RBAC 自定义角色；user 可属多团队（switch-tenant 换 token） |

### 平台资产（fb/tt/fb_app 域）
| 表 | 说明 |
|---|---|
| fb_credentials (19列) | FB 令牌（加密存储，priority 绑定 + RR 轮换池，cooldown/状态机） |
| tt_credentials / tt_apps | TT 令牌（24h 过期+refresh 轮换）与 App |
| fb_apps | FB App 登记（dev/standard access_level，webhook 配置） |
| **accounts (25列)** | 广告账户核心表：act_id/platform/is_managed 软删/account_status/**group_label/disable_reason**(0084)/sentinel_armed/warmup_state/last_inspected_at/owner... |
| account_fb_credentials / account_tt_credentials | 账户↔令牌多对多（RR 轮换的数据基础） |
| token_health | watchdog 主动健康检查留痕 |

### 投放生产线（launch 域）
| 表 | 说明 |
|---|---|
| assets (34列) | 素材库：storage_key/AI 分析(JSON)/用途/语言/image_hash 缓存 |
| landing_pages (34列) | 落地页：display/redirect 双模式、防护配置(JSON)、自检结果、子域名、状态机 |
| landing_page_templates / landing_ad_links / ad_redirect_overrides | 页模板 / 广告↔子码链接 / 单广告重定向覆盖 |
| landing_pixels / landing_domains | 像素库(platform 维度) / 域名池(CNAME 联动) |
| **launch_templates (41列)** | 投放模板（母版）：目标/预算/受众/高级配置/占位符 landing_url/批量字段 |
| launch_jobs / launch_job_items | 部署任务（异步 BackgroundTasks + 进度轮询 + partial 重试 + 心跳防 reap） |
| lead_form_templates / message_templates | Instant Form 与 Messenger 消息模板（AI 生成） |
| page_posts | 跟帖模式的主页帖缓存（object_story_id 复用） |
| saved_audiences | 受众库（模板引用） |

### 运行与观测（perf/guard/log 域）
| 表 | 说明 |
|---|---|
| **perf_snapshots (22列)** + perf_snapshot_ticks | 每日每广告快照（账户本地日 + 5min tick 轨迹）——看板与规则的数据底座 |
| guard_rules / guard_ad_allowances | 10 类规则（8 止损+2 扩量）/ 当日加白（账户本地日） |
| **action_logs (17列)** | 全系统操作审计：source(rule_engine/sentinel/launch/user...)、metadata、
|  | trigger_type——**dedup_recent 的查询基础（通知去重靠它）** |
| notifications / tenant_tg_bindings / user_tg_bindings(+prefs 0085) | 站内告警 / TG 租户级+用户级绑定（级别偏好矩阵） |
| landing_events (28列) | 落地页访问日志（来源归因/屏蔽原因/fired 像素地面真相） |
| leads | 潜客（轮询 10min + webhook 双通道；轻 CRM 状态） |
| ads_cache | 广告结构缓存（三层 JSON：campaigns/adsets/ads；15min 同步 + 部署后对账） |
| kpi_configs | 租户 KPI 目标（target_cpa 等进规则评估） |

### 支撑
currency_rates（汇率，fx_sync 每日）/ system_settings（KV 配置+运行标记）/ email_routes /
tickets + ticket_messages（工单）/ certified_pages（合规认证页）

## 4. 路由全景（265 个端点，27 个文件）

按文件→职责（端点前缀即模块）：
- **auth/rbac/admin/backup**：登录/换团队/权限/超管租户管理/备份下载（~25）
- **fb / fb_apps / fb_oauth / tt_oauth**：令牌 OAuth 全生命周期、账户导入纳管、loadable-accounts、
  分组 PUT /fb/accounts/group、disable_reason 透传（~35）
- **ads**：广告管理器（三层读 + 状态/预算/改名/删除写 + 重定向 + diagnose 诊断）（~19）
- **launch / launch_templates**：落地页 CRUD+发布+自检+worker、模板 CRUD+**部署 job+重试+进度+清单**（~40）
- **landing_lib / landing_events / subcodes**：像素/域名库、落地日志查询、子码生成绑定清理（~25）
- **guard**：规则 CRUD、加白、哨兵 arm/disarm、紧急暂停+轮询状态、手动巡检（超管）（~15）
- **dashboard**：看板 summary/trend/ads/landing/landing-trend/export CSV（6）
- **assets / ai**：素材 CRUD+AI 分析+文案生成（~15）
- **form_templates / audiences / kpi / notify / settings / tickets / compliance**：各配置域（~40）
- **tg_webhook / fb_webhook**：TG 绑定回调 / FB leads webhook（HMAC 验签）（2）

## 5. 定时任务全景（16 个，APScheduler，advisory lock 防多 worker 重复）

| job | 频率 | 职责 | 锁 |
|---|---|---|---|
| run_inspection | 5min(可配) | **主巡检**：多租户→账户并行→insights→规则评估→止损/扩量 | 101 |
| run_sentinel_patrol | 3min | 哨兵：armed 账户 ACTIVE 系列全停（kill-switch，含权限退避） | 106 |
| run_budget_alerts | 15min | 日预算进度分档告警（50/75/90/98%） | 102 |
| run_watchdog | 10min | 心跳停滞/单账户停滞(30min)/令牌 debug_token 健康 | 103 |
| run_reassociate | 2h | 孤儿账户重绑令牌 + still_orphan 告警 | 104 |
| run_subcode_autobind | - | 子码从 creative URL 反向绑定 ad_id | 105 |
| run_account_status_sync | 30min | /me/adaccounts 拉状态+余额+disable_reason | 110 |
| run_ads_cache_sync | 15min | 广告结构三层缓存全量刷新 | 111 |
| run_leads_poll | 10min | 潜客轮询（webhook 之外的兜底通道，2h 滚动窗） | 117* |
| run_subcode_cleanup | 每日 4:17 | 子码自动清理 | 108 |
| run_keepalive | 每日 2:17 | 防休眠扫描（建 $5 主页赞，当前禁用待 FB 过审） | 109 |
| run_landing_block_scan | 60min | 落地页 FB 屏蔽探测（scrape）+告警 | 107 |
| run_data_retention | 每日 4:33 | 数据保留清理（可配） | - |
| run_fx_sync | 每日 3:07 | 汇率表刷新 | - |
| run_tt_token_refresh | 6h | TT 令牌 24h 过期前轮换 | 114 |
| _reap_launch_stale | 5min | 部署孤儿 job 回收（心跳>10min 判死） | 116 |

*leads_poll 锁号以代码为准（101-116 已占，新增从 117 起）。

## 6. 核心机制深读（改前必懂的 6 件事）

### 6.1 守护引擎（guard_engine.py ≈3000 行，最大服务）
- **评估集**：今日 insights ∩ live ACTIVE 广告（live 拉失败落 ads_cache 兜底并计降级 streak）
- **规则**（10 类）：bleed_abs/cpa_exceed/click_no_conv/low_ctr_no_conv/reach_no_conv/trend_drop/
  consecutive_bad/budget_burn_fast（止损）+ slow_scale/roas_scale（扩量）；conversion_source
  fb/landing/either 口径；BLEED_ABORT 宽泛转化守卫防误杀；KPI 异常跳过评估+告警
- **暂停可靠性**：ad→adset→campaign 三级升级链 + 每级回读核验（假停检测）+ 失败 5min 重试 +
  权限永久错误 24h 退避 + 成功回写 ads_cache（根除 coverage_lost 自误报）
- **多级防线**：主巡检(5min) / 哨兵(3min) / watchdog(10min) / 紧急全停(手动) / 权限退避自愈

### 6.2 令牌系统（fb_tokens.py）
- 读=候选池 **RR 轮换**分摊；写=绑死 priority 最高（防孤儿对象+FB 一致性）
- cooldown 状态机：rate_limited 30min 出池→过期自动回池；token_expired/permissions 走 fallback 链
- `run_with_fallback`：仅读/幂等操作换令牌重试；写操作绝不换（防同对象双写）

### 6.3 部署链（launch_templates.py ≈2100 行）
- 单模板 / **按素材批量**（母版×M素材=M系列，系列名=素材名）双模式
- job/items 异步模型：409 防重（advisory lock 115 原子段）→ BackgroundTasks → 进度轮询 →
  partial 一等状态（成功X/Y）→ retry（批量=整 item 重跑，有确认弹窗）→ 部署后对账（刷 cache）
- **追踪参数插值**：landing_url 7 个静态白名单占位符（{{campaign.name}} 等，URL 编码；
  {{ad.id}} 显式拒绝——历史像素不 fire 事故）

### 6.4 落地页工厂
- display（中间页）/redirect（直跳）双模式；每页子域名 lp{id}.根域 + CNAME 联动
- 防护引擎（设备/UA/频次/机房等 10 类规则）+ 访问日志（来源归因 4 层 + fired 像素地面真相）
- 发布自检矩阵 9 项（含 FB scrape 封禁探测）；每小时屏蔽扫描
- 子码体系：slug→像素/广告绑定；自动绑定（巡检反向匹配）+ 自动清理

### 6.5 通知体系（notify_utils.py）
- `emit_notification` = 站内信(必落) + TG(按角色订阅路由) + dedup_recent(action_logs 查询) +
  风暴上限(per tenant/event/日 cap=30，critical 豁免清单 NO_CAP_EVENTS)
- 用户级 TG 偏好：warning/info 可关，**critical 恒推**；fail-open（解析失败=全推）

### 6.6 平台维度（FB/TT 双平台）
- accounts.platform 列贯穿全链（令牌/客户端/部署/巡检/看板切换器）
- 分发点：`client_for_account`/`cred_for_account_op` 内按 platform 分发；TtClient duck-type FbClient
- TT 特性：令牌 24h+refresh 轮换、素材先传文件库拿 file_id、限流自计数退避、adgroup 层定向

## 7. 前端结构（16 个 view）

Dashboard（看板+告警中心+TG入口）/ Ads（账户列表+分组+禁用原因）/ AdManager（三层广告管理+诊断+潜客）/
Tokens（FB+TT 令牌）/ Assets（素材+AI）/ Landing（落地页工作台）/ LandingLogs（访问日志）/
LaunchTemplates（模板+部署抽屉）/ FormTemplates / Guard（规则+哨兵+暂停记录）/ Members / Settings /
AuditLog / AdminTeams / KpiMapping / Login。

中央 composables：**useStatus**（状态术语 registry——改状态文案先改这）/ useDateRange（北京业务日）/
usePlatform（平台切换 localStorage）/ useLocale / useFbError / useTz / useCountries / useFormat。
样式约定：CSS 变量 `--ac/--bd/--bg2/--bg3/--t1..t3`（`--p/--border` 是未定义陷阱）；移动端
外壳抽屉+`.form-l` 堆叠已全局就位。

## 8. 历史演进速览（详见 TECH_REVIEW.md 按批记录）

- **2026-07**：V1 对齐 1.0 → RBAC/多团队 → 素材 AI → 投放模板+部署 job → 落地页工厂全套 → i18n 全站
- **2026-08**：FB webhook/leads → Graph v25 → 全系统审计两批修复 → TK 调研
- **2026-09 上旬**：TK 平台接入 P0-P4 全量（platform 维度贯穿）→ 批R 资金安全审计 P0×13 +
  哨兵 dedup 根因 → 潜客轮询+leads 计入转化口径 → 看板/告警中心多轮重构
- **2026-09-05**：批F（FBInsider 对标：批量生成/分组/禁用原因/TG偏好/插值 + 巡检5项）→ 3-Agent 复审
  全清（P0×1+P1×5+P2×9）→ 哨兵权限退避 → 引擎可靠性批（1.0 对比 P0×3+P1×4）
- **产品方向**（已规划未实施）：`极简操作与自动驾驶规划.md`（L0-L5）；竞品拆解 `FBInsider_对标学习.md`

## 9. 文档地图（新 AI 的阅读顺序）

| 读什么 | 文件 |
|---|---|
| ① 怎么干活不踩雷（铁律/部署/恢复） | `toveads/HANDOFF.md` |
| ② 系统全景（本文） | `toveads/ARCHITECTURE.md` |
| ③ 目录速查 | `toveads/CLAUDE.md` |
| ④ 变更历史（每批 why+验证+commit） | `toveads/TECH_REVIEW.md` |
| ⑤ 设计渊源（00-12 章原始设计，部分已漂移以代码为准） | 根目录 `Mira_2.0_docs/` |
| ⑥ 产品方向（自动驾驶规划/竞品/TK 接入） | `toveads/极简操作与自动驾驶规划.md` · `FBInsider_对标学习.md` · `TK_接入规划.md` |
| ⑦ 1.0 旧系统（bug-fix-only，别碰） | 根目录 `Mira_System_Map_v2.md` + `CLAUDE.md` |

---
*本文数字由脚本扫描代码生成（`toveads/_gen_arch.py` 可重跑刷新）；叙述部分人工校准 2026-09-05。*
