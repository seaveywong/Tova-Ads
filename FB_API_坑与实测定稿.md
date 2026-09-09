# FB Marketing API 坑与实测定稿（2026-09-09 全链路打通日）

> 本文档记录 2026-09-08/09 真部署链路排障中实证的全部 FB API 坑。每条都有真实 API 调用证据（PAUSED 即删零消耗验证法）。
> 新人改广告链路前必读；与 TECH_REVIEW.md 批U/U2/U3/V/W/X 互为索引。

## 铁律（排障方法论）

1. **UI 能做的 API 必能做**——报"FB 不支持"前先怀疑自己的 payload（本次 1870227 曾被错误归因为"账户被锁 Advantage+"，实为字段位置错误）。
2. **真链路必须真打 FB**：FakeFb 捕 payload → 真 FB 重放（建 PAUSED 即删）→ 字段二分。静态 smoke/全暂停断言发现不了 FB 校验层问题。
3. **FB 报错先看 raw**：friendly 翻译口径定位不了字段级问题；fb_client 已带 raw message/error_data 进日志。`error_user_msg` 常直接点名缺失字段。
4. **FB 读回（GET 创建的对象）是最强线索来源**——targeting_automation 的嵌套位置就是从读回结构里发现的。

## 坑清单

### 1. targeting_automation 必须嵌在 targeting 内（v23.0+，1870227/1870188）
- 顶层发 `targeting_automation` 被**静默丢弃**，FB 默认 Advantage+=1 → 任何手动收窄（自定义年龄/性别/兴趣/受众）全拒
- 官方规则（2025-06 博客）：**非默认定向必须显式 `targeting.targeting_automation.advantage_audience=0`**；显式 1 + 非默认也拒（1870188）
- 本仓定稿（ad_builder.build_adset）：开关关 **或** targeting 含任何非默认收窄（age≠18/65、genders∉(None,[],[0,1,2])、flexible_spec/custom_audiences/behaviors 等）→ 强制 0；仅默认宽定向 → 1
- 写入位置在 advanced_config 深合并**之后**（防残留键顶掉）
- 仅影响**新建** adset；更新旧 adset 不受影响

### 2. is_dynamic_creative 残留（1885702）
- 模板 advanced_config 残留 `{"is_dynamic_creative":true}` → adset 建成但 **ads 全灭**（DC 组要求多素材创意，本链恒单素材）
- build_adset 现一律剥该键

### 3. Instant Form（leadgen_forms）
- questions 项合法键：`type/key/label/options`——**name、placeholder 都是非法键**（#100 Invalid keys）
- **`follow_up_url` 是 v25 必填**（缺了报 1892085 Missing Fields: FollowUpActionURL）
- 表单**不能 API 删除**（code 33），归档用 `POST {id} {"status": "ARCHIVED"}`
- 页级查询/操作须 **Page Access Token**（#190）

### 4. 像素（adspixels）
- 端点拼写是 `act_x/adspixels`（不是 adpixels/addatasets——v25 后两者 2500 Unknown path）
- **每个广告账户只能有 1 个自有像素**（code 6200），天然只建一次
- 系统用户令牌可建（实测 cred25 建成过）

### 5. 令牌 scope ≠ App 权限（批X 核心教训）
- App Review 批了权限 ≠ 令牌带着——**OAuth 授权 URL 没要的 scope 永远没有**
- cred25 曾只有 7/9：缺 leads_retrieval（潜客拉取）+ pages_manage_metadata（页 webhook 订阅），两条链全瘫
- OAUTH_SCOPES 已补齐 8 权限全集；advanced 权限必须过审后才能进 OAuth（否则 Invalid Scopes）
- 自查令牌真实 scope：app token（app_secret 换 client_credentials）→ `GET /debug_token?input_token=...`

### 6. 其他实测确认
- `{{ad.id}}` 宏可放 creative 链接里（A0 实测建成）；也可走 creative.url_tags
- Advantage+ 受众墙的三个错误归因全被推翻：没过审（假，8 权限 Approved/Renewed）、dev 模式（假，App 是 Live）、账户级锁（假，UI 一直能设）——真相是坑 1
- 1870227 无 error_data，raw 只有 "Invalid parameter"——必须靠二分实验定位
- leadgen webhook 是页级订阅（subscribed_apps，需 Page Access Token + pages_manage_metadata）；App 级 callback 配置在 Dashboard（本仓已配 api.tovaads.com/fb/webhook 且 active）

## 事故复盘索引

- 四层根因链 + 真部署打通：TECH_REVIEW.md 批U/U2/U3
- targeting_automation 嵌套修复：TECH_REVIEW.md 批V
- API 全面重审（含 leadgen 修复）：TECH_REVIEW.md 批W
- 潜客/webhook 断链与 OAuth scope 补齐：TECH_REVIEW.md 批X

### 7. webhook 订阅字段权限（批Y 补）
- `subscribed_apps` 的 `subscribed_fields` 带 `messages` 需 **pages_messaging**（未申请）；`leadgen`/`feed` 只需 pages_manage_metadata
- 重授权弹窗 8 个权限 + 自动附加的 public_profile = 后台 9 个，非缺失

### 8. 转化闭环：adset 像素 ≠ 落地页 fire 像素（批Z）
- worker fire 的像素来自落地页自己的 pixel_ids（display 模式经 router/next 请求时动态下发）——投放链只给 adset 配像素、页不 fire = FB 永远零转化 → 止损按"花钱零转化"正确关广告
- 修复：部署链解析像素后回写页 pixel_ids + 页像素进解析链；改页 pixel_ids 须重发布（LP_CONFIG 发布时注入）
- 验证口径：POST /landing-pages/router/next（页的 ingest_secret+slug）看 pixel_ids，与 adset promoted_object 对账
