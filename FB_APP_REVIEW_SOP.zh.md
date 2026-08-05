# FB App Review — 权限 SOP（10 个权限）· 中文审阅版

> **这份是给你（Seavey）审校用的**。英文版 `FB_APP_REVIEW_SOP.md` 是交付给 Saurabh 的最终文档（他拿去操作系统 + 录屏 + 填审核申请）。
>
> 这份中文版让你**快速校对**：每个权限在我系统里的映射对不对、FB API 写对没有、录屏步骤合不合理。**有不对的地方告诉我，我改英文版**。
>
> 技术名词（FB API 端点、代码文件路径、字段名）保留英文（怕翻译失真），描述/操作用中文。

---

## App 概述（给审核员的）

**ToveAds**（`https://tovaads.com`）是一个多租户 SaaS，帮广告代理客户管理 Facebook 广告。代理连接他们的 FB App + 广告账户 + 主页后，平台读取广告成效、建/暂停广告、部署 Instant Lead Form（即时表单）、拉取潜客、接收实时 leadgen webhook——全部通过 FB Marketing API。

**测试登录**：Seavey 另行提供测试账号。

---

## 权限一览（共 10 个）

| # | 权限 | 分组 | 在 ToveAds 里干什么 |
|---|---|---|---|
| 1 | `ads_management` | 基础 | 建/暂停/改预算/删广告、模板批量部署、自动止损暂停 |
| 2 | `ads_read` | 基础 | 列广告账户 + campaign/adset/ad 三层结构 |
| 3 | `business_management` | 基础 | 列/关联 Business Manager |
| 4 | `pages_show_list` | 基础 | 列用户管理的主页（部署/表单/主页选择器用）|
| 5 | `pages_read_engagement` | 基础 | 读主页已发帖（跟帖模式选帖用）|
| 6 | `read_insights` | 高级 | 广告成效数据（消耗/转化/ROAS）|
| 7 | `pages_manage_ads` | 高级 | 建引用主页的广告（object_story_spec）|
| 8 | `pages_manage_posts` | 高级 | 建主页帖（链接帖/照片帖给创意用）|
| 9 | `leads_retrieval` | 高级 | 读 Instant Form 潜客数据 |
| 10 | `pages_manage_metadata` | 高级 | 订阅主页 leadgen webhook（实时收潜客）|

（`public_profile` 也申请，但无需审核。）

---

# 基础权限（1–5）

## 1. `ads_management` — 创建/管理广告

**为什么需要**：建/暂停/启用/改预算/删/复制 campaign/adset/ad——既有用户手动操作，也有自动操作（规则止损暂停、保活建广告）。

**系统哪里在用**：
- 前端：**广告管理**（AdManager）——每行的暂停/启用开关、改预算、删除、复制；**投放模板**（LaunchTemplates）——批量部署；**Guard**（止损规则）——自动暂停
- 后端：`routers/ads.py`（status/budget/delete/batch-status）、`routers/launch_templates.py`（部署）、`services/ad_ops.py`（部署 runner）、`services/guard_engine.py`（自动暂停）
- FB API 调用（经 `app/core/fb_client.py`）：
  - 建：`POST /act_{account_id}/campaigns`、`/adsets`、`/ads`、`/adcreatives`
  - 改状态：`POST /{node_id}` 带 `status=ACTIVE|PAUSED|ARCHIVED`
  - 改预算：`POST /{node_id}` 带 `daily_budget` / `lifetime_budget`
  - 删：`DELETE /{node_id}`
  - 复制：`POST /{node_id}/copies`

**录屏脚本**：
1. 登录 → **广告管理** → 广告 tab
2. 点某条广告的状态开关（暂停 → 启用，或反过来）→ 显示状态变化
3. 点某广告组的 ✎ 改预算 → 改值 → 保存 → 显示新预算
4. ⋯ 菜单 → 复制广告 → 显示复制体出现
5.（部署）**投放模板** → 部署一个模板到某账户 → 成功 + 广告管理里出现新广告

**审核员测试步骤**：
1. 广告管理 → 暂停一条广告 → 在 FB Ads Manager 里也确认是 PAUSED
2. 改预算 → 在 FB Ads Manager 确认预算变了
3. 投放模板 → 部署 → 在 FB Ads Manager 确认新广告/系列存在

---

## 2. `ads_read` — 读广告账户 & 结构

**为什么需要**：列出用户能管的广告账户，读 campaign → ad set → ad 树，让用户在 ToveAds 看到完整账户结构。

**系统哪里在用**：
- 前端：**令牌**页（载入/导入广告账户弹窗）、**广告管理**（三层 tab：系列/广告组/广告）
- 后端：`routers/fb.py`（loadable-accounts、import）、`routers/ads.py`（list）、`services/ads_cache_sync.py`（15 分钟缓存）
- FB API 调用：
  - `GET /me/adaccounts`（字段：account_id, name, currency, balance, status）
  - `GET /act_{account_id}/campaigns`、`/adsets`、`/ads`
  - `GET /{node_id}?fields=...`（节点详情）

**录屏脚本**：
1. 登录 → **令牌**页 → 打开"载入账户"弹窗 → 显示从 FB 拉来的广告账户列表
2. 进 **广告管理** → 显示三个 tab（系列/广告组/广告）填了用户的结构
3. 下钻：点系列 → 下面的广告组 → 点广告组 → 下面的广告

**审核员测试步骤**：
1. 令牌 → 载入账户 → 确认账户和 business.facebook.com/settings/ad-accounts 一致
2. 广告管理 → 确认系列/广告组/广告树和 FB Ads Manager 一致

---

## 3. `business_management` — 管理 BM

**为什么需要**：列出用户能访问的 Business Manager，以便把对的 BM 关联到他的租户 + 推导权限级别（基本/完全）。

**系统哪里在用**：
- 前端：**令牌**页（BM 关联展示）
- 后端：`routers/fb.py`（导 token 时关联 BM）
- FB API 调用：`GET /me/businesses`（字段：id, name, permitted_tasks）

**录屏脚本**：
1. 登录 → **令牌**页 → 显示连接 token 的 BM（名称 + id）
2. 指出从 `permitted_tasks` 推导的 BM 信息

**审核员测试步骤**：
1. 令牌 → 确认显示的 BM 和 business.facebook.com/settings 里的一致

---

## 4. `pages_show_list` — 显示主页列表

**为什么需要**：列出用户管理的主页，以便部署广告、建 Instant Form、派生主页 token 时选主页。

**系统哪里在用**：
- 前端：**令牌**页（载入/导入主页）、**投放模板**部署抽屉（主页下拉）、**表单模板**（表单建在哪个主页）
- 后端：`routers/fb.py`（loadable pages、import）
- FB API 调用：
  - `GET /me/accounts`（字段：id, name, category, tasks）——列主页
  - `GET /me/accounts?fields=id,access_token`——派生主页 access token

**录屏脚本**：
1. 登录 → **令牌** → 打开主页区 → 显示管理的主页列表
2. **投放模板** → 部署抽屉 → 显示主页下拉是从 FB 拉的
3. **表单模板** → 建表单时显示主页选择器

**审核员测试步骤**：
1. 令牌 → 确认主页列表和 facebook.com/pages 用户管理的一致
2. 投放模板部署 → 确认主页下拉显示用户所有主页

---

## 5. `pages_read_engagement` — 读主页互动（已发帖）

**为什么需要**：读主页已发的帖子，让"跟帖模式"能复用已存在的主页帖作为广告创意（而不是新建）。

**系统哪里在用**：
- 前端：**广告管理** → 广告行 ⋯ 菜单 → "📌 复用此帖" → 打开投放模板的 **Post Picker（选帖器）**，列主页已发帖
- 后端：`routers/fb.py::list_page_posts` → `GET /{page_id}/published_posts`（主页 token，字段：id, message, attachments, created_time）
- FB API 调用：`GET /{page_id}/published_posts`

**录屏脚本**：
1. 登录 → **广告管理** → 找一条广告 → ⋯ → "📌 复用此帖"
2. 投放模板表单 → 打开 **选帖器** → 显示从 FB 拉的主页已发帖（带缩略图 + 文案）
3. 选一帖 → 显示作为创意复用

**审核员测试步骤**：
1. 广告管理 → 复用此帖 → 选帖器 → 确认列的帖子和 facebook.com 主页的 Posts tab 一致

---

# 高级权限（6–10）

## 6. `read_insights` — 广告成效数据

**为什么需要**：在看板和广告管理显示消耗/展示/点击/转化/ROAS/CPA。核心报表功能，每个客户每天都看。

**系统哪里在用**：
- 前端：**数据看板**（Dashboard，每账户聚合消耗/覆盖/转化）+ **广告管理**（每条广告的 消耗/CPA/转化/ROAS 列）
- 后端：`routers/dashboard.py`、`routers/ads.py`、`services/kpi_resolver.py`、`services/guard_engine.py`
- FB API 调用：`GET /act_{account_id}/insights`（账户级 + 广告级；字段：spend, impressions, clicks, ctr, cpc, reach, frequency, actions, purchase_roas）

**录屏脚本**：
1. 登录 → **数据看板** → 显示每账户消耗/展示/转化
2. **广告管理** → 切 系列/广告组/广告 tab → 指 消耗/CPA/转化/ROAS 列
3.（可选）DevTools → Network → 显示 `/ads/list` 返回 insights 数据

**审核员测试步骤**：
1. 看板 → 确认消耗和 FB Ads Manager 同日期范围一致
2. 广告管理 → 确认有活跃广告的账户每条广告数据非空

---

## 7. `pages_manage_ads` — 通过主页管理广告

**为什么需要**：部署广告时，创意要引用主页（object_story_spec / object_story_id）。这权限让我们的 App 能建引用用户主页的广告——部署功能必需。

**系统哪里在用**：
- 前端：**投放模板** → 部署抽屉（选主页 + 账户）→ 部署
- 后端：`routers/launch_templates.py`（部署 BackgroundTasks）、`services/ad_ops.py`
- FB API 调用：`POST /act_{account_id}/ads`，创意用 `object_story_spec`（Standard Access）或 `object_story_id`（dev / 跟帖模式）

**录屏脚本**：
1. 登录 → **投放模板** → 打开模板 → **部署** → 选账户 + 主页 → 确认
2. 显示进度页最终 ✓
3. **广告管理** → 显示新广告（ACTIVE），创意引用了选的主页

> ⚠️ 注意：如果连接的广告账户当前被 FB business policy 限制（建不了广告），录部署尝试 + FB 报错，再展示一个已部署的广告证明功能可用。Seavey 会另行解封。

**审核员测试步骤**：
1. 投放模板 → 部署 → 确认广告出现在广告管理 + FB Ads Manager（ACTIVE）

---

## 8. `pages_manage_posts` — 建主页帖

**为什么需要**：建引用给创意的主页帖（落地页广告用链接帖、Page Like/保活广告用照片帖）。两种模式：**新建帖**（object_story_spec）或**复用已存在帖**（object_story_id）。

**系统哪里在用**：
- 前端：**投放模板**部署（新建帖）、**广告管理** ⋯ → "📌 复用此帖"（跟帖）
- 后端：`app/core/page_post.py::get_or_create_page_post`（缓存"同主页+同素材+同文案"避免重复建）
- FB API 调用：
  - 链接帖：`POST /{page_id}/feed`（message + link）
  - 照片帖：`POST /{page_id}/photos`（url + message + published=true）
  - 创意用 `object_story_id`（建的帖）或 `object_story_spec` 建

**录屏脚本**：
1. 登录 → **投放模板** → 部署模板（建主页帖 + 广告）
2. ✓ 后 → 在 facebook.com 打开主页 → 主页的 Posts tab 显示新帖
3.（跟帖）**广告管理** → 有帖的广告 → ⋯ → "📌 复用此帖" → 表单预填该帖的 `object_story_id`

**审核员测试步骤**：
1. 部署模板 → 确认帖子出现在 facebook.com/{page}/posts
2. 广告管理 → 复用此帖 → 确认表单预填了已存在帖 id

---

## 9. `leads_retrieval` — 读潜客数据

**为什么需要**：拉 Instant Form 提交的潜客数据（姓名/邮箱/电话/自定义答案），让代理在 ToveAds 内看/导出潜客，不用去 FB Lead Center。

**系统哪里在用**：
- 前端：**广告管理** → **潜客** tab（第 4 个 tab）→ 潜客列表 + **"⟳ 从 FB 同步"** 按钮
- 后端：`routers/leads.py`——`GET /leads`、`POST /leads/sync`
- FB API 调用：`GET /{form_id}/leads`（字段：id, created_time, field_data, ad_id, form_id）——`fb_client.get_leads`

**录屏脚本**：
1. 登录 → **广告管理** → **潜客** tab
2. 点 **"⟳ 从 FB 同步"** → 成功提示（"已同步 N 条"）
3. 显示潜客表——姓名/邮箱/电话/来源列 + 自定义字段 chip
4.（可选）DevTools → Network → 显示 `/leads/sync` + `/leads` 调用

**审核员测试步骤**：
1. 广告管理 → 潜客 → 同步 → 确认潜客出现（测试主页要有部署的 Instant Form + 提交记录）
2. 和 FB Lead Center 该表单的潜客数对一下

---

## 10. `pages_manage_metadata` — 订阅主页 Webhook

**为什么需要**：潜客提交 Instant Form 的**瞬间实时收到回调**（而不是轮询）。App 订阅每个主页的 `leadgen` 字段；FB 把新潜客推到我们 webhook，我们用 App Secret 验 X-Hub-Signature-256 HMAC，然后存潜客。

**系统哪里在用**：
- 前端：
  - **设置 → FB Webhook** 卡片（超管）：显示公网回调 URL + Verify Token + 已配 App 数（HMAC 验签源）
  - **广告管理 → 潜客 tab → "🔔 订阅主页 webhook"**：订阅用户所有主页的 leadgen
- 后端：
  - `GET /fb/webhook`（FB 订阅验证：回 `hub.challenge`）
  - `POST /fb/webhook`（FB leadgen 回调：用 App Secrets 验 `X-Hub-Signature-256` HMAC，然后存潜客）
  - `POST /leads/subscribe`（遍历 `me/accounts`，逐主页订阅）
- FB API 调用：`POST /{page_id}/subscribed_apps` 带 `subscribed_fields=leadgen`

**Webhook 配置（Seavey 已完成）**：
- 回调 URL：`https://api.tovaads.com/fb/webhook`
- Verify Token：在 设置 → FB Webhook 里设的（和 FB App Dashboard 一致）
- 订阅字段：`leadgen` ✓

**录屏脚本**：
1. 登录 → **设置 → FB Webhook** → 显示回调 URL（`https://api.tovaads.com/fb/webhook`）、"已配 N 个 App"chip、Verify Token 框
2. **广告管理 → 潜客 tab** → 点 **"🔔 订阅主页 webhook"** → 成功提示（"已订阅 N/M 个主页"）
3.（实时演示）在主页的 Instant Form 提交一条测试潜客 → 回潜客 tab → 刷新 → 新潜客出现（webhook 推送）
4.（可选）显示 FB App Dashboard → Webhooks → 回调 URL ✓ Verified、`leadgen` 勾选

**审核员测试步骤**：
1. 设置 → FB Webhook：确认回调 URL 是 HTTPS + 设了 Verify Token
2. 广告管理 → 潜客 → 订阅 → 成功提示显示订阅的主页数
3. 提交一条测试潜客 → 确认几秒内出现在潜客 tab（webhook 投递）

---

## 安全 & 数据处理声明（给审核员）

- **App Secret 存储**：Fernet 加密存 `fb_apps` 表；webhook HMAC 验签只在内存解密——绝不记日志、绝不返回前端。
- **Webhook 签名校验**：每个 `POST /fb/webhook` 用 `X-Hub-Signature-256` HMAC-SHA256 对照所有 active App Secret 校验（恒定时间比较）。伪造/无签名请求 → 403。
- **潜客数据**：存多租户 PostgreSQL，启用 Row-Level Security；每个租户只能看到 `form_id` 映射到自己 `LeadFormTemplate` 的潜客。webhook 用 `form_id → LeadFormTemplate → tenant_id` 反查租户；匹配不上的潜客丢弃（不存）。
- **Verify Token**：存 `system_settings`，仅超管可改，UI 脱敏显示。
- **不转卖/不分享给第三方**：所有数据（广告成效、潜客、帖子）只给拥有该广告账户的代理使用。

---

## 录屏制作清单（10 条视频）

| # | 权限 | 演示路径 | 预估时长 |
|---|---|---|---|
| 1 | ads_management | 广告管理（暂停/预算/复制）+ 投放模板部署 | ~60s |
| 2 | ads_read | 令牌载入账户 + 广告管理三层下钻 | ~45s |
| 3 | business_management | 令牌页 BM 关联 | ~30s |
| 4 | pages_show_list | 令牌主页 + 投放模板主页下拉 | ~40s |
| 5 | pages_read_engagement | 广告管理 → 复用此帖 → 选帖器 | ~40s |
| 6 | read_insights | 数据看板 + 广告管理数据列 | ~45s |
| 7 | pages_manage_ads | 投放模板部署 → 广告管理显示新广告 | ~60s |
| 8 | pages_manage_posts | 部署建帖 → facebook.com 主页看 | ~45s |
| 9 | leads_retrieval | 广告管理 → 潜客 tab → 同步 → 潜客出现 | ~45s |
| 10 | pages_manage_metadata | 设置 FB Webhook + 订阅按钮 + 实时 lead | ~60s |

**录屏顺序建议**：
- **2、4、6、9、10** 不需要建广告 → 先录这些（不受当前 policy 限制影响）。
- **1、3、5、7、8** 需要建广告/帖。如果连接的 business 被 policy 限制，先录能录的（拉列表、显示 FB 报错）+ 用已存在的广告/帖证明功能；Seavey 解封后再重录完整演示。

---

## 你（Seavey）要处理的事项

- [ ] 给 Saurabh / FB 审核员**测试登录账号**（已连接 App + 广告账户 + 主页的用户）
- [ ] **解 FB business policy 限制**（解封后才能录 1、7、8 那些建广告的权限）
- [ ] 在测试主页**部署至少一个 Instant Lead Form**（让 9、10 有真潜客可看）
- [ ] 问 Saurabh：FB 这 10 个权限**一次提交还是分批**（他专业，让他定）
