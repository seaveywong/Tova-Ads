# TikTok (TK) 平台接入规划

> 状态：**规划中（进文档），未启动**。FB 体系完善 + 过审后启动。
> 架构方向（2026-07 决策，本轮细化）：**多平台聚合**，platform 作维度贯穿数据/落地页/巡检/看板/UI，**不单独开 TK 板块**。
> 关联记忆：`tiktok-platform-plan`。本文是详细方案，记忆浓缩 + 指向本文。

---

## 0. 核心决策（已定，不再讨论）

| 项 | 决策 |
|---|---|
| 架构 | **聚合**：platform 维度（fb/tt），不是 silo。落地页层已朝聚合走（`pixel_ids` 多像素数组 + `landing_events.platform`），延续此方向 |
| 范围 | FB 同等：创建+部署+止损巡检+数据看板+落地页双像素+令牌管理+表单 |
| 路径 | 增量、零 FB 风险：FB 表/代码不动，平行建 TT，分发器按 `account.platform` 路由 |
| UX | 不加新一级 nav；现有页顶加**平台切换/筛选**（复用 team 切换器模式）；TK 文案中英 i18n 同步 |
| 启动前提 | FB 过审 + Standard Access；TT 开发者账号过审（1-2 周，比 FB 快，sandbox 可建广告） |

---

## 1. TK vs FB 差异全景（决定工作量分布）

| 模块 | FB 现状 | TK 差异 | 影响 |
|---|---|---|---|
| **令牌** | 长效 token（60天/system user） | **access_token 24h 过期**，refresh_token ~365 天 | 🔴 必须后台 cron 刷新 job（<24h），新子系统 |
| **像素** | 浏览器 fire（fbevents.js） | Pixel + Events API 双发，**event_id 去重强制** | 🔴 双发必须同 UUID，否则转化翻倍 |
| **像素测试** | Test Events | **事件须先 fire 才能选优化目标**（≤2h 处理） | 🟡 用 Events API S2S 后端发一次点亮 |
| **点击归因** | fbp/fbc | **ttclid**（URL 参数） | 🟡 落地页捕获 + 透传 |
| **广告结构** | Campaign→AdSet→Ad | Campaign→Ad Group→Ad（同三级，术语不同） | 🟢 平行 builder |
| **创意** | image_hash/object_story_spec | image/video + text + cta；**Spark Ads 独有** | 🟡 Spark Ads MVP 跳过（见 §6） |
| **定向** | detailed_targeting/lookalike | 兴趣/行为/hashtag/Actalent 达人/Lookalike | 🟡 AI 受众映射单独做 |
| **转化/KPI** | offsite_conversion | TT conversion 字段 + 归因窗口(点击1/7/14+浏览1/7) | 🟡 KPI resolver 加 TT 映射 |
| **数据回拉** | insights API | reporting API（字段结构不同） | 🟡 perf 同步适配 |
| **审核** | review_status | TT 广告审核状态字段 + 内容政策不同 | 🟢 状态 registry 加 TT |
| **币种** | account currency | 同（USD/CNY…），spend 口径 | 🟢 currency_rates 覆盖 |
| **限流/错误** | FB rate limit + 错误码 | TT 独立体系 | 🟢 错误 i18n 加 TT |

---

## 2. 数据层方案（关键：复合键加 platform）

🔴 **最大坑**：`perf_snapshots`/`ads_cache`/`guard_ad_allowances` 现按 `act_id` 维度。FB/TT 的 act_id 是不同空间（理论上不撞），但 **ad_id/campaign_id 跨平台会撞**（都是平台自增 ID）。**必须给这些表加 `platform` 列进唯一键**，否则跨平台数据串。

### 迁移（additive，零 FB 风险）
| 表 | 改动 | FB 影响 |
|---|---|---|
| `accounts` | 加 `platform` 列（default `'fb'`，存量回填 fb）+ 加 `tt_credential_id` FK | 零（additive） |
| `tt_credentials`（新） | access_token_enc + **refresh_token_enc + expires_at + advertiser_id** | — |
| `account_tt_credentials`（新） | 多令牌池（照 `account_fb_credentials`） | — |
| `landing_pixels` | 加 `platform` 列（fb/tt） | 零 |
| `launch_templates` | 加 `platform` 列（决定走 fb_builder/tt_builder） | 零 |
| `ads_cache` | 加 `platform` 列，唯一键加 platform | 零（FB 行 platform=fb） |
| `perf_snapshots` | 加 `platform` 列，唯一键 (tenant, platform, act_id, ad_id, date) | 零 |
| `guard_ad_allowances` | 加 `platform` 列（同账户只属一平台，act_id 租户内仍唯一，platform 双保险） | 零 |
| `fb_apps` → 通用化（可选） | 或新建 `tt_apps`（照 fb_apps，存 TT app 配置） | — |

> 所有迁移末尾必 `GRANT ... TO toveads_app; GRANT ... TO toveads_super;`（SOP §8 坑）。

### 分发器
`client_for_account(db, tenant, act, scope)` 改：先查 `account.platform` → fb 用 `fb_client`（不变），tt 用新 `tt_client`。`cred_for_account_op` 多令牌轮换同理分发。

---

## 3. 令牌子系统（🔴 TK 独有最大坑）

TT token **24h 过期**，必须后台刷，否则连接断、巡检/部署全挂。FB 没这问题（长效 token）。

### 后端
- 新建 `services/tt_token_refresh.py`：cron job（每 **6h** 跑一次，留足余量），扫所有 `tt_credentials`，对 `expires_at < now+12h` 的用 refresh_token 换新 access_token，更新 expires_at。
- `tt_client.py`：每次请求前查 expires_at，临近过期触发刷新（双保险）。
- refresh_token 也可能过期（~365 天）→ `token_health` 加 TT 行，监控 refresh_token 寿命，临过期发告警（"请重新授权 TikTok"）。
- 锁号（见已修的 lock 机制）：tt_token_refresh 用新唯一锁号（如 **112**，避开 101-111）。

### UX（Tokens 页）
- FB / TT 分区（tab 或分组卡片）。
- TT 卡片显示：**距 access_token 过期 xx 小时**（实时倒计时感）+ 自动刷新状态（"已自动刷新"时间戳）+ refresh_token 剩余天数。
- refresh_token 临过期（< 30 天）红标 + "重新授权"按钮。
- "连接 TikTok" OAuth 按钮（scope: TT Marketing API + TikTok 账户数据）。

---

## 4. 落地页 / 像素（已规划详细，本轮新增 event_id 去重）

### worker 模板（`LANDING_TEMPLATE`，landing.py:44-77）
现状：`<head>` 写死 fbevents.js loader + `LP_PIXELS`/`LP_CONV` 动态注入（`_d` base64 或占位符）。

改动（**1 文件 + JS**，不大改）：
1. `<head>` 加 **ttq loader 段**（和 fbq 并列；官方 1 段 loader + 多次 `ttq.load(pid)` 支持多像素）。
2. `LP_PIXELS` 从 `["fb1","fb2"]` → **带平台标记** `[{"id":"fb1","p":"fb"},{"id":"tt1","p":"tt"}]`。
3. init 分发：fb→`fbq('init',pid)`，tt→`ttq.load(pid); ttq.page()`。
4. `trackConversion()` 分发：fb→`fbq('trackSingle',pid,evt)`，tt→`ttq.track(evt,props)`。
5. `_d` 编码扩展：`p` 字段升级为带平台的结构（或拆 `fp`(fb 像素)/`tp`(tt 像素)）。

### 🔴 event_id 去重（双发强制）
我们走**浏览器 Pixel + 后端 Events API 双发**（S2S 更稳，不怕拦截/JS 失败）。TK 规定：同一事件双发必须传**相同 `event_id`**（UUID），否则重复计数。

实现：
- 落地页 worker 生成 `event_id`（UUID），fire Pixel 时带 `ttq.track(evt, {event_id})`。
- worker beacon 把 `event_id` 回传后端（和现有"beacon fire 子码像素=地面真相"模式一致）。
- 后端 Events API 用**同一个 event_id** 发 S2S → TK 去重为 1 次。
- FB 同理可补 CAPI（我们 FB 现在没做，TK 先做对）。

### ttclid 捕获（归因）
TT 广告点击带 `ttclid` 参数（类比 FB fbc）。落地页 worker 捕获 URL 的 ttclid → 透传 Events API → 提升归因准确度。landing_events 可记 ttclid 便于排查。

### Advanced Matching（可选，提升归因）
TT 支持 SHA256 邮箱/手机号高级匹配。MVP 可跳过，Phase 2 加（表单提交时采集）。

### 像素测试（绕"事件先 fire 才能选"）
TK 硬约束：转化目标下拉只列 Pixel 已收到的事件，新像素全灰，先收到 ≥1 个 + ≤2h 处理才可选。
- **主路（Events API S2S）**：后端 POST 一个带 `test_event_code` 的事件 → Events Manager 收到 → 事件可选。最贴我们架构。
- **兜底（手动）**：上线后人肉访问落地页点一次按钮，真实 fire，等 2h。
- 推荐组合：S2S 点亮事件库 → 配优化目标 → 常规走浏览器 Pixel（+ S2S 去重）。

---

## 5. 广告 / 创意 / 定向

### 结构
TT 三级 Campaign→Ad Group→Ad，照 FB 平行建 `tt_ad_builder.py`。

### 创意
- image / video + text + call_to_action + landing_page_url。
- 素材库：加 TT 视频规格标注（9:16 竖屏为主，时长/大小限制 ≠ FB）。Asset 模型可加 `platforms`（适用平台）字段，或按规格筛选。
- **Spark Ads（TK 独有）**：用现有 TK 视频/达人内容投流。**MVP 决策：跳过**（复杂、需达人授权链路），Phase 2 再做。规划文档记为待定决策。

### 定向
- MVP：地区 + 年龄/性别 + 基础兴趣 + 自定义受众（Custom Audience）。
- AI 受众分析（现 FB 口径）：TT 定向维度不同，单独做 `tt_audience_mapping`。
- Phase 2：Lookalike + Actalent 达人。

---

## 6. 转化 / KPI / 归因

- KPI resolver（现 FB 口径，5 级级联）：加 **TT 映射层**。TT 指标字段（conversion/converted/value/conversion_type）≠ FB offsite_conversion。
- 归因窗口：TT 点击 1/7/14 天 + 浏览 1/7 天（KPI 解析时注意口径）。
- Reporting API 回拉（≠ FB insights）：新建 `services/tt_perf_sync.py`，写 perf_snapshots（platform='tt'）。
- 守护止损：TT 账户"转化"判断用 TT KPI resolver 结果。

---

## 7. 巡检 / 止损 / 看板

### guard_engine 加 TT 分支
- pause TT 广告 = 不同 API（`tt_client.pause_ad`）。
- 预算/余额计算：`currency_rates` 覆盖 TT 币种，`to_usd` 统一。
- 哨兵/保活：TT 账户参与巡检（platform 分发），保活种子帖 TK 无对应（Spark Ads 外无"复用帖"概念），TK 保活用普通新创意。

### 看板
- dashboard 加 **platform 维度**：平台切换/筛选 chip + 跨平台汇总视图（总消耗/总转化/总 ROAS）。
- 排序原则（[[dashboard-sort-principle]]）跨平台统一适用。

---

## 8. UX 规范（用户硬要求：UX 必须做好）

### 平台切换/筛选（全局模式）
- **不加新一级 nav**。topbar 加**平台切换器**（复用已有 team 切换器交互模式）：全部 / Facebook / TikTok。
- 各列表页（广告管理/看板/Tokens/投放模板）受切换器影响 + 独立 platform 筛选 chip。

### 各页适配
| 页 | 适配 |
|---|---|
| 广告管理 | platform 筛选 chip；跨平台汇总视图；TT 广告状态术语进 `useStatus` registry |
| 看板 | platform 维度切换 + 跨平台汇总 |
| 投放模板 | 建模板选 platform（决定 fb_builder/tt_builder + 定向/创意字段集） |
| 落地页 | 像素库显示 platform icon（fb/tt 区分）；多像素列表 |
| Tokens | FB/TT 分区；TT 显 access_token 倒计时 + refresh_token 寿命 + 自动刷新状态 |
| 素材库 | TT 视频规格标注/筛选 |
| 状态术语 | TT 广告状态（审核中/被拒/active 等）进 `useStatus`，中英 i18n |
| 文案 | **所有 TK 文案 zh.js + en.js 同步**（[[i18n-system]]），en 零 CJK |

### 质量（沿用既有标准）
- t() key 全解析 + en 零 CJK + const 物化扫描（SOP §6 三脚本）。
- 交互好/数据清楚/逻辑显式（[[ux-clarity-bar]]）。

---

## 9. 审核与上线

- TT 开发者审核 1-2 周（比 FB 快），**sandbox 可建广告**（不像 FB dev mode 拦创建）。
- sandbox 数据是假的，上线前切 production app（类比 FB dev→standard）。
- TT 内容政策对品类限制不同（酒精/减肥/金融等），AI 文案合规规则（[[ai-copy-rework-todo]]）加 TT 规则。

---

## 10. 分阶段待办（启动后照做）

| Phase | 内容 | 估时 |
|---|---|---|
| **P0 数据层** | 全部迁移（accounts.platform + tt_credentials/account_tt_credentials + ads_cache/perf/allowances 加 platform + landing_pixels/launch_templates platform）+ 分发器 client_for_account | 1.5d |
| **P1 令牌** | tt OAuth + tt_token_refresh cron(6h) + token_health TT + Tokens 页 TT 分区（含倒计时/刷新状态 UX） | 1.5d |
| **P2 落地页/像素** | worker ttq loader + LP_PIXELS 带平台 + event_id 去重双发 + ttclid + Events API S2S + 像素测试（S2S 点亮） + landing_pixels.platform UI | 2d |
| **P3 广告** | tt_ad_builder + 部署 runner TT 分支 + 定向 MVP + Reporting API 回拉 + KPI resolver TT 映射 | 2d |
| **P4 巡检/看板/UX** | guard TT 分支 + dashboard platform 维度 + 平台切换器 + 状态术语 registry + i18n 中英 + 三脚本校验 + smoke | 1.5d |

合计 ~8.5 天（比 2026-07 估的 6 天多——新增令牌刷新子系统 + event_id 去重的真实成本）。

---

## 11. 待查 / 启动时确认（避免凭记忆出错）

- [ ] TT OAuth 具体 scope 列表 + 回调流程（照 FB OAuth 实现，但 scope 完全不同）
- [ ] TT Events API payload 结构（字段名：event/time/event_id/properties/user（ttclid/advanced matching））
- [ ] TT Reporting API 字段（conversion/value/attribution window 参数）
- [ ] TT 广告审核状态枚举完整值
- [ ] TT rate limit 头（X-RateLimit-* 类似？）→ 限流冷却策略（[[rule-engine-kpi-gap-analysis]] 提的 1.0 成熟机制）
- [ ] Spark Ads API 链路（Phase 2 决策依据）
- [ ] TT 创意视频规格精确值（分辨率/时长/码率上限）

---

## 12. 决策（已定 ✅ 2026-08-02 用户批准最佳实践）

1. **Spark Ads**：MVP **跳过**，Phase 2 再做。（TK 独有，需达人授权链路，复杂）
2. **Advanced Matching**：MVP **跳过**，Phase 2 再做。（需表单采集 PII，合规成本）
3. **FB 补 CAPI**：TK 接入时**一起补** FB CAPI（统一双发去重架构）。
4. **平台切换器默认值**：默认**"全部"**（跨平台汇总视图），可切单平台。

> 启动前提：FB 过审 + Standard Access + TT 开发者过审。
> ⚠️ **状态：规划完成，未启动。无用户明确指令不动一代码。**

---

## 关联
`tiktok-platform-plan`(记忆) · `launch-templates-module` · `auto-launch-architecture-plan` · `i18n-system` · `toveads-dev-sop` · `keepalive-creative-fix` · `page-post-follow-mode`
