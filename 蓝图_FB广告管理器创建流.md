# FB 广告管理器「创建广告」全流程权威蓝图

> **调研产出** · 2026-09-08 · 基于 Meta 官方帮助中心（Wayback 渲染快照原文）+ Marketing API v25.0 开发者文档（2025-08~2026-06 存档）+ 第三方权威佐证（Jon Loomer 等）。本文件只调研不改代码。
>
> **信源可靠性分级**：〔官快〕= 官方帮助中心文章完整正文（Wayback 渲染快照，注明快照日期）｜〔官API〕= developers.facebook.com v25.0 文档原文（Wayback 快照）｜〔官摘〕= 官方文章摘要/og:description（正文未能抓到全文）｜〔三方〕= 第三方权威转载/评测。凡未能核实的条目一律标 **未查证/推断**。

---

## 0. 速览：三层结构与一次创建的骨架

```
Ads Manager → + Create（+ 创建）
 └─ ① 营销活动 Campaign：买型 → 目标(6选1) → 活动设置 → 名称 → 特殊类别 → 预算(活动/广告组) → A/B 测试
     └─ ② 广告组 Ad Set：转化位置 → 转化事件 → 成效目标 → 主页 → 预算与排期 → 受众(Advantage+) → 版位(Advantage+)
         └─ ③ 广告 Ad：身份(主页/IG/WA号) → 广告设置(格式) → 广告创意(素材/文案/CTA) → 目的地/模板调用位 → Advantage+ creative → 追踪 → 发布
```

三层职责（官方〔官API〕campaign-structure，2024-09 快照）：

| 层级 | 负责 | API 端点 |
|---|---|---|
| Campaign 营销活动 | 目标 objective | `/campaigns`（API 对象 AdCampaignGroup） |
| Ad Set 广告组 | 预算、排期、出价、定向（受众+版位） | `/adsets` |
| Ad 广告 | 创意 | `/ads` |
| （API 第4层）Creative | 纯视觉元素，创建后不可改 | `/adcreatives` |

> 界面三层 = API 四层：Creative 在 Ads Manager 里内嵌于广告层。〔官API〕

---

## 1. 第一层：营销活动（Campaign）逐面板字段表

来源〔官快〕"Create ad campaigns in Meta Ads Manager"（help 621956575422138，2025-05-05 快照；该文前身即 "What are the advertising levels"）。

**流程：+ Create campaign →**

| # | 面板/步骤 | 中文界面用词 | 字段与选项 | 默认值/规则 |
|---|---|---|---|---|
| 1 | Buying type 购买类型 | 购买类型 | `Auction 竞价` / `Reservation 预订`（部分账户可见） | Auction；选 Reservation 走单独流程 |
| 2 | Campaign objective 营销目标 | 选择营销活动目标 | 6 个：`Awareness 品牌知名度`、`Traffic 流量`、`Engagement 互动`、`Leads 潜在客户`、`App promotion 应用推广`、`Sales 销售` | 必选；旧 11 目标 2024-01 起不可新建〔官快 CTW 文，2024-11〕 |
| 3 | Campaign score 广告系列评分 | 广告系列评分 | 发布前预测优化程度，可采纳建议 | 仅展示，随设置实时变化〔官快 2025-05〕 |
| 4 | Campaign setup 活动设置 | 选择营销活动设置 | `Advantage+（推荐）` vs `Manual 手动` 二选一 | **2025-06 起 Sales/Leads/App promotion 已无此二选**，直接进精简 Advantage+ 创建（见 §6.1）〔三方 Jon Loomer 2025-06-23〕 |
| 5 | Campaign name | 营销活动名称 | 文本 | 自动生成（目标+日期），可改 |
| 6 | Special Ad Categories 特殊广告类别 | 特殊广告类别 | 住房/就业/金融产品与服务/社会议题/选举与政治/无 | 无；选了会限制定向选项 |
| 7 | Budget 预算 | 预算 | `Campaign budget 广告系列预算`（= Advantage+ campaign budget，CBO）或 `Ad set budget 广告组预算`；再选 `Daily 每日` / `Lifetime 总预算` + 金额 | Advantage+ 创建流程中**广告系列预算默认开**〔三方 Jon Loomer〕；选活动级预算后出价/预算排期设置上移到系列层 |
| 8 | A/B test | A/B 测试 | 开/关；发布后配置对照实验变量 | 关 |

**API 侧（campaign 必填）**〔官API AdCampaignGroup 参考，2026-03 快照；CTW/CTM 指南 2026 年版〕：`name`、`objective`（枚举含 6 个 `OUTCOME_*` + 全部旧值仅供存量读取，v17 起旧目标废弃）、`special_ad_categories`（`[]`/`NONE` 或类别数组）、`status`（建议 `PAUSED`）、`buying_type`（`AUCTION` 默认）。示例即 `POST /act_<id>/campaigns`。

**objective 全枚举**（v25 AdCampaignGroup.reference）：
`APP_INSTALLS, BRAND_AWARENESS, CONVERSIONS, EVENT_RESPONSES, LEAD_GENERATION, LINK_CLICKS, LOCAL_AWARENESS, MESSAGES, OFFER_CLAIMS, OUTCOME_APP_PROMOTION, OUTCOME_AWARENESS, OUTCOME_ENGAGEMENT, OUTCOME_LEADS, OUTCOME_SALES, OUTCOME_TRAFFIC, PAGE_LIKES, POST_ENGAGEMENT, PRODUCT_CATALOG_SALES, REACH, STORE_VISITS, VIDEO_VIEWS`（前 15 个旧值已废弃，仅历史对象可见）。

---

## 2. 第二层：广告组（Ad Set）逐面板字段表

来源〔官快〕创建系列文（2025-05）+ 潜客广告文（help 375478503258484，2024-11 快照）。**面板顺序**（6 目标时代现行版）：`广告组名称 → 转化（Conversion）→ 成效目标（Performance goal）→ Facebook 主页 → 动态素材 → 预算与排期 → 受众控制+Advantage+ 受众 → 版位`。

### 2.1 转化位置 Conversion location（按目标全集）⭐

来源〔官快〕"Available conversion locations and events by objective"（help 2035196646663270，2024-11-21 快照）——官方原文全表：

| 目标 | 可选转化位置 | 转化事件 |
|---|---|---|
| **Awareness** | 「在你的广告上」（On your ad，无需选择） | 无需转化事件 |
| **Traffic** | Website 网站 / App 应用 / Messenger / WhatsApp / Calls 通话 / Instagram profile Instagram 主页 | 无需转化事件 |
| **Engagement** | ① On your ad（选互动类型：Video views 视频观看 / Post engagement 帖子互动 / Event response 活动回应）② Messaging apps 消息应用（选 Messenger / WhatsApp / Instagram Direct）③ Website ④ App ⑤ Facebook Page | ①②⑤ 无需事件；③ 网站事件 13 种（Add to wishlist/Contact/Customize product/Donate/Find location/Schedule/Search/Start trial/Submit application/Subscribe/View content）；④ 应用事件 17 种（含 In-app ad click/impression、Rate、Spent credits、Unlock achievement 等网站没有的） |
| **Leads** | Website / **Instant forms 即时型表单** / Messenger / **Instant forms and Messenger（二选一自动分配）** / Instagram / Calls / App | Instant forms、Messenger、Instagram、Calls 无需事件；Website 事件 10 种（Complete registration/Contact/Find location/Lead/Schedule/Search/Start trial/Submit application/Subscribe/View content）；App 9 种 |
| **App promotion** | App（自动选中） | 全部应用事件（标准+自定义） |
| **Sales** | Website / App / **Website and app 网站+应用** / Messenger / WhatsApp / **Website and shop 网站+店铺** | Website·App·Messenger·WhatsApp 各 11 种（Add payment info/Add to cart/Add to wishlist/Complete registration/Donate/Initiate checkout/Purchase/Search/Start trial/Subscribe/View content；App 版含 In-app ad click/impression/Spent credits）；Website and app 10 种；**Website and shop 仅 4 种：View content、Add to cart、Initiate checkout、Purchase** |

补充（快照后新增，需注意时效）：
- **Website and Instant forms（网站+即时表单）**：Leads 目标新转化位置，一条广告按系统判断分流到网站或表单；创建广告时需同时给网站 URL 和表单。〔三方 Jon Loomer 2025-04/05；官快正文未含（2024-11 快照），**快照原文未证**〕
- Website and shop：单图/单视频格式的网站广告可自动优化去向网站或店铺〔官快 ad destinations 2024-11〕。
- Leads 的转化位置在潜客广告文（2024-11）中列出 7 项：Website、Instant forms、Messenger、Instant forms and Messenger、Instagram、Calls、App——与上表一致。Messenger/Instagram 方式=「自动问答流程」（automated question-and-answer flow）。

### 2.2 成效目标 Performance goal（按目标全集）⭐

来源〔官快〕"About Performance Goals"（help 355670007911605，2025-02-01 快照）——官方原文全表（成效目标≠目标：Sales 系列下也可优化链接点击）：

| 目标 | 可选成效目标（英文界面原文 → 中文） |
|---|---|
| **Awareness** | Maximize reach of ads 最大限度扩大覆盖人数 · Maximize number of impressions 展示次数 · Maximize ad recall lift 广告回想度提升 · Maximize ThruPlay views ThruPlay 播放量 · Maximize 2-second continuous video views 2 秒连续视频播放量 |
| **Traffic** | Maximize number of landing page views 落地页浏览量 · Maximize number of link clicks 链接点击 · Maximize daily unique reach 每日独立覆盖 · Maximize number of conversations 对话/会话数 · Maximize number of impressions · Maximize number of Instagram profile visits Instagram 主页访问 · Maximize number of calls 通话数 |
| **Engagement** | Maximize number of conversations · link clicks · impressions · ThruPlay views · 2-second continuous video views · Maximize engagement with a post 帖子互动 · Maximize daily unique reach · Maximize number of event responses 活动回应 · Maximize number of conversions 转化量 · Maximize number of landing page views · Maximize number of app events 应用事件 · Maximize reminders set 提醒设置 · Maximize number of calls · Maximize number of page likes 公共主页赞 |
| **Leads** | Maximize number of conversions · landing page views · link clicks · daily unique reach · impressions · **Maximize number of leads 潜在客户数（表单线索）** · **Maximize number of conversion leads 转化潜在客户数（需 CRM 回传，推荐先接 CRM）** · Maximize number of calls · Maximize number of app events |
| **App promotion** | Maximize number of app events · Maximize number of app installs 应用安装量 · Maximize value of conversions 转化价值（in-app purchases/ads；in-app ad impressions 仅 Android） · Maximize number of link clicks |
| **Sales** | Maximize number of conversions · Maximize value of conversions · landing page views ·（快照截断，另有 link clicks 等常规项）**部分截断未全录** |

规则：某成效目标是否可用取决于 目标×转化位置 组合（help 416997652473726 有完整矩阵，正文未能抓取——**矩阵逐格未查证**）；"Maximize number of conversions" 部分场景仅支持 Purchase 事件+点击归因〔官摘〕。潜客广告文中 Leads 流程的成效目标下拉实际只列 Maximize number of leads / conversion leads 两个（Instant forms 场景）〔官快 2024-11〕。

### 2.3 Facebook 主页 / 动态素材

| 面板 | 字段 | 规则 |
|---|---|---|
| Facebook Page | 选择代表业务的主页 | 广告层身份会自动沿用此选择；潜客线索归属该主页〔官API lead-ads〕；首次跑潜客需勾选 Lead Ads 条款 |
| Dynamic creative 动态素材 | 开/关 | 开启后广告层不能再按版位手动定制素材；**2024-06 起 Sales/App promotion 不再提供**，官方建议用 Flexible ad format 灵活广告格式〔官快 2025-05〕 |

### 2.4 预算与排期 Budget & schedule

来源〔官快〕创建文 + 〔官API〕Budgets（2025-11-11 快照）：

| 字段 | 说明 |
|---|---|
| Daily budget 每日预算 / Lifetime budget 总预算 | 二选一；广告组层（未开活动预算时）。日预算按周平滑，**单日可超 25%**（$10 → 最多 $12.50）；总预算需设结束日期 |
| Schedule 排期 | 开始日期（默认立即）；结束日期可选；不设结束=持续跑到手动关 |
| Show more options 更多选项 | `Budget scheduling 预算排期`（仅日预算，按日加权）+ `Ad scheduling 广告排期`（仅总预算，按小时段投放） |
| 金额单位 | API 传最小货币单位（美分）；bid/budget 同〔官API〕 |

### 2.5 受众 Audience（Advantage+ 受众）

来源〔官快〕创建文（2025-05）+〔三方〕Jon Loomer 2025-06 +〔官摘〕help 273363992030035（正文未抓到，快照无渲染版）：

- 面板名：「Audience controls 受众控制」+「Advantage+ audience（Advantage+ 受众）」两个区块合并为一个 Audience 节。
- **Audience controls（硬约束，永远生效）**：Locations 位置 / Minimum age 最低年龄 / Custom audience exclusions 自定义受众排除 / Languages 语言。
- **Advantage+ audience（建议信号，可扩量）**：Custom audiences 自定义受众 / Lookalike audiences 类似受众 / Age range 年龄 / Gender 性别 / Detailed targeting 细分定位，作为「建议」喂给 AI，**投放可超出该范围**。
- 关闭方式：旧版按钮「switch to original audiences 切换到原始受众」→ 新版改为「further limit the reach of your ads 进一步限制广告覆盖人数」，切换后可逐项选择年龄/性别/自定义/细分是「建议」还是「硬约束」；取消建议勾选即关掉 Advantage+ 受众。
- Advantage+ 受众默认**开**（Advantage+ 创建流程中）。〔三方 Jon Loomer〕

### 2.6 版位 Placements

来源同上：

| 模式 | 说明 |
|---|---|
| **Advantage+ placements（Advantage+ 版位）** | 默认开（= 原 Automatic placements 自动版位）：系统在 Facebook/Instagram/Messenger/Audience Network/Threads 全版位自动分配预算 |
| Manual placements 手动版位 | 悬停 Advantage+ placements → `Edit 编辑` 进入；分组：Platforms 平台（Facebook/Instagram/Messenger/Audience Network/Threads）、Devices & OS 设备与系统、具体 Placements 版位（Feed/Stories/Reels/Marketplace/右栏…）、Skippable 可跳过、Brand safety 品牌安全 |
| 与消息目的地的联动 | CTM 广告可投 Facebook+Messenger+Instagram；Click-to-Instagram 仅 Instagram；CTW 仅 Facebook+Instagram〔官快 CTM about 2024-11〕 |

### 2.7 出价策略 Bid strategy（广告组层「优化与投放」；开活动预算时上移至系列层）

〔官摘〕About Meta Bid Strategies（help 1619591734742116）+〔官API〕消息广告文档（v25）：

- 界面 5 项：`Highest Volume 最高成交量`（原 Lowest Cost）/ `Highest Value 最高价值` / `Cost Per Result Goal 单次成效目标费用`（Cost Cap）/ `ROAS Goal 广告支出回报率目标` / `Bid Cap 出价上限`。
- API `bid_strategy`（消息广告文档明确列出 3 值）：`LOWEST_COST_WITHOUT_CAP`、`LOWEST_COST_WITH_BID_CAP`、`COST_CAP`；用后两者需给 `bid_amount`。ROAS/价值出价在其它文档定义，本轮回取文档未含——**API 侧 ROAS 枚举未查证**。
- 开着 Advantage+ campaign budget 时，广告组层不能再设 Cost Per Result Goal（上移到系列层）〔三方〕。

---

## 3. 第三层：广告（Ad）逐面板字段表 ⭐用户重点

来源〔官快〕创建文（2025-05）+ 潜客文（2024-11）+ CTW 文（2024-11）+ ad destinations（2024-11）。**面板顺序**：`广告名称 → 身份 Identity → 广告设置 Ad setup → 广告创意 Ad creative → 目的地 Destination → （消息模板/表单调用位）→ Advantage+ creative → 追踪 Tracking → 发布 Publish`。（2024-09 起创意区改版逐步推出：手动设置+单静态素材时步骤顺序有变，功能不变〔官快〕。）

### 3.1 身份 Identity

| 字段 | 选项 | 规则 |
|---|---|---|
| Facebook Page 公共主页 | 下拉选（广告组层已选则自动带出） | 必选 |
| Instagram account Instagram 帐户 | 下拉或 `Connect account 关联帐户` 新增 | 可选（无 IG 账号不能投 IG 版位） |
| WhatsApp 号码 | **不在身份区本体**：Engagement 目标走「Accounts 帐户」区选 WA 号码；Traffic/Sales 目标用「与主页绑定的 WA 号」（选主页即隐式选定） | 可用「连接到主页」或「连接到 Business Manager」两种方式绑号〔官快 CTW 2024-11〕 |

### 3.2 广告设置 Ad setup（格式）

| 选项 | 中文 | 说明 |
|---|---|---|
| Single image or video | 单图或单视频 | 手动传素材 |
| Carousel | 轮播 | ≥2 卡片，每卡可独立 URL（卡片级目的地） |
| Collection | 精品栏 | 需商品目录；默认以 Instant Experience 即时体验为目的地，目的地字段在创建 IE 时填 |
| Use existing post | 使用现有帖子 | 引用已发布帖子（object_story_id 路线） |
| Use Creative Hub mockup | 使用 Creative Hub 样机 | 从 mockup 创建 |
| Advantage+ creative for catalog | Advantage+ 目录创意 | **本区的开关**（非创意区）；用目录自动个性化组合格式+素材+去向〔官快 ad destinations〕 |

### 3.3 广告创意 Ad creative

- 素材：Media 下拉 `Add image/Add video` 上传或选历史素材；`Edit → Turn into video` 图转视频；轮播 `Add card` 加卡。
- 文案：Primary text 主文案 / Headline 标题 / Description 描述 / Call to action 行动号召（CTA 按钮）。
- 预览：右侧 Ad preview 开关，按版位缩略图切换查看。
- （消息类广告在创意区挂欢迎语/模板，见 §4。）

### 3.4 目的地 Destination（与转化位置的联动）⭐

来源〔官快〕ad destinations（help 1174990279685960，2024-11）：

- **常规**：广告级「Destination 目的地」区在选完创意后出现；选项由广告组的**转化位置**决定：website / website and shop / app and website / app / Instant Experience / Facebook event。
- **特例规则（官方原文）**：
  - **Engagement 目标**：需勾选 `Add a destination 添加目的地` 或选一个 CTA，才出现目的地区（可加 Instant Experience 或网站链接）。
  - **Awareness 目标**：需勾选 `Add a destination` 才出现（加网站链接）。
  - **Messenger/WhatsApp 作为转化位置**：目的地=转化位置，**广告级无需再选目的地**。
  - 轮播：每卡可独立 URL + 末卡可选主页头像「See more」卡。
  - 精品栏：目的地=Instant Experience（在 IE 里填）。
  - Website 转化位置+单图/视频：可同时投网站+店铺自动分流。

### 3.5 追踪 Tracking

`Set up 设置` → 三类事件数据集：`Website events 网站事件`（Pixel/数据集）、`CRM events CRM 事件`（转化线索回传）、`App Events 应用事件`。潜客广告文另含追踪参数设置入口。〔官快 2024-11/2025-05〕

### 3.6 发布与审核

`Publish 发布`（或 `Close 保存草稿`）。发布后自动进入 `In Review 审核中`，Delivery 列显示状态；审核依 Advertising Standards。〔官快〕

---

## 4. 模板调用位矩阵（目标 × 表单/消息/WhatsApp 调用位）⭐用户重点

### 4.1 界面侧调用位在哪

| 调用位 | 位置（面板路径） | 出现条件 | 界面叫法（中/英） |
|---|---|---|---|
| **Instant Form 即时型表单** | 广告组层「Conversion 转化」选 **Instant forms 即时型表单**（或 Website and Instant forms）→ 广告层 **Destination 目的地** 区选/建表单 | Leads 目标 | 「Instant form 即时型表单」；表单选择器在广告层目的地区：`Create new form 新建表单`/选现有表单（`+ Create`/Use existing）〔官快 lead ad 2024-11；三方 media-beats〕 |
| **Instant Form（Messenger 问答版）** | 广告组层转化位置选 **Messenger** 或 **Instant forms and Messenger** → 广告层消息区配置「自动问答流程」 | Leads 目标 | 「automated question-and-answer flow 自动问答流程」＝Messenger lead gen chat template〔官快 lead ad；官API messaging-ads〕 |
| **Messenger 欢迎语/模板（普通 CTM）** | 广告级创意区 CTA 后的消息设置：greeting 欢迎语 + 自动回复/FAQ | Engagement/Traffic/Sales 的 Messaging 转化位置 | 「Welcome text 欢迎语」「Automated responses 自动回复」；模板最多 **5 条**连续消息〔官API CTM〕 |
| **Messenger lead 模板（问题流）** | 广告层 `+ Create` 创建对话模板（提问/不合格问题/disqualifying questions） | Leads+Messenger | 「Create questions for your leads campaign 为潜客营销活动创建问题」〔帮助中心栏目名〕 |
| **WhatsApp 欢迎语/预填消息** | 广告层（Engagement 路径：Accounts 区选 WA 号后）→ 消息设置；或 `+ Create` 建 flow | Engagement/Traffic/Sales/Leads 的 WhatsApp 转化位置 | 「greeting message 问候消息」「pre-filled message 预填消息」（help 687252309996046）；「Flows 流程」（WhatsApp Flows，help 1216541683817423）〔官快 CTW 2024-11：第 10 步 "Click + Create to create your flow"〕 |
| **CTM 模板库（跨 Messenger/WA）** | 广告层消息区：`Create a new template 创建新模板` / `Select an existing template 选择现有模板` | 消息类广告 | help 287043621933356（Create a new template for ads that click to Messenger or WhatsApp）〔官摘；正文未抓到，**具体字段未查证**〕 |
| **多目的地消息** | 广告组转化位置选 Messaging apps → 勾多个应用 | Engagement（multidestination） | help 1192884166182156〔官摘〕 |

### 4.2 API 侧对应（v25.0 实证）

| 界面调用位 | API 载体 | 实证 |
|---|---|---|
| CTM 欢迎语/模板 | creative `object_story_spec.{link_data\|video_data\|photo_data\|text_data}.page_welcome_message`（欢迎语文本）；模板消息≤5 条；CTA `MESSAGE_PAGE` + `value.app_destination=MESSENGER` | 〔官API〕Ads that Click to Messenger（2026-02 更新） |
| Messenger lead 问答模板 | 先建模板（`/page_id/messenger_lead_forms` 列表；创建时自动生成关联 fblead_form），creative 里 `page_welcome_message = {"ctm_lead_gen_template_id": <id>}`；需 `privacy_url` | 〔官API〕同上 |
| WhatsApp 欢迎语+预填 | creative `page_welcome_message` VISUAL_EDITOR v2：`landing_screen_type=welcome_message`、`customer_action_type=autofill_message`、`autofill_message.content`（预填句）、`automated_greeting_message_cta`（call/url/catalog/**flows** 四种按钮） | 〔官API〕Click to WhatsApp（2026-06 快照） |
| WhatsApp 号码 | adset `promoted_object.whatsapp_phone_number`（可选，page_id 必填） | 〔官API〕同上 |
| Instant Form（表单线索） | 先建 lead form 拿 form_id，广告关联之；leads 归属 Page。**我们代码路线**：creative `link_data.call_to_action = {type: SIGN_UP, value: {lead_gen_form_id: <id>}}`（toveads `app/core/ad_builder.py` §不变量10） | 〔官API lead-ads 指南 2026-04（"associate the form ID"，未给字段名）+ 本仓库实现交叉验证；**v25 文档原文的挂载字段未直接读到 → 半实证**〕 |
| 多目的地消息 | adset `destination_type` = `MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP` / `MESSAGING_INSTAGRAM_DIRECT_MESSENGER` / `MESSAGING_MESSENGER_WHATSAPP` / `MESSAGING_INSTAGRAM_DIRECT_WHATSAPP`；`optimization_goal` 必须 `CONVERSATIONS` | 〔官API〕Multidestination（2026-05） |

### 4.3 Instant Form 三种表单类型（表单编辑器内）

〔官摘〕help 252352181957512（About Instant Form Types）+〔三方〕：

| 类型 | 英文 | 特点 | 默认 |
|---|---|---|---|
| 更多询盘 | More volume | 预填+步数最少，量大质低 | **默认类型** |
| 更高质量 | Higher intent | 提交前多一步「确认回顾」，量降质升 | — |
| 创意样式 | Rich creative | 自定义排版/品牌视觉的表单 | — |

表单构成：Form type 表单类型 / Introduction 介绍 / Questions 问题（含 conditional 条件逻辑）/ Completion 完成页（含 CTA）；单账户最多存 **100** 个即时表单〔三方 media-beats〕。

---

## 5. 动态逻辑：objective → conversion location → optimization/performance goal → promoted_object 链

### 5.1 界面联动规则表（选完目标后什么出现/隐藏/必填）

| 选择 | 联动 |
|---|---|
| 选 Awareness | 无转化位置；广告层需勾「Add a destination」才有目的地区 |
| 选 Traffic | 转化位置 6 选；无需转化事件；成效目标随转化位置变 |
| 选 Engagement | 转化位置含「消息应用」与「广告上」两类；勾「Add a destination」/选 CTA 才出现目的地区 |
| 选 Leads | 转化位置含 Instant forms（默认推荐）；选 Instant forms→广告层目的地区=表单选择器；选 Messenger→消息模板区；选 Calls→无表单；成效目标只剩 leads/conversion leads 两个（表单场景） |
| 选 App promotion | 转化位置自动=App；App name 必填 |
| 选 Sales | 转化位置最多（含 Website and app/shop）；Pixel/目录随事件选择联动 |
| 转化位置=Messenger/WhatsApp | 广告层目的地区消失（目的地=转化位置） |
| 开 Advantage+ campaign budget | 广告组层预算/出价控件上移系列层；广告组层不能设 Cost Per Result Goal |
| 消息目的地 | 版位受限（CTM=FB+MSG+IG；CTI=仅 IG；CTW=FB+IG）；EU/日/韩部分消息优化不可用 |
| Dynamic creative 开 | 广告层按版位定制素材功能锁定 |

### 5.2 API 链路实证表（v25.0，消息/线索类）

**Ads that Click to Messenger**〔官API 2026-02〕：

| 项 | 值 |
|---|---|
| campaign.objective | `OUTCOME_TRAFFIC`（CTS）/ `OUTCOME_LEADS`（Messenger Ads for Leads）/ `OUTCOME_ENGAGEMENT, OUTCOME_SALES, OUTCOME_TRAFFIC`（普通 CTM） |
| adset.destination_type | `MESSENGER` |
| adset.optimization_goal | `CONVERSATIONS` / `CONVERSIONS`（CTM/CTS）；`LEAD_GENERATION` / `QUALITY_LEAD`（线索版，QUALITY_LEAD 可在 promoted_object 加 pixel_id 做质量优化） |
| adset.billing_event | 必须 `IMPRESSIONS` |
| adset.promoted_object | `page_id`（必填） |
| creative | object_story_spec.*_data + `page_welcome_message`；线索版 `{"ctm_lead_gen_template_id":...}` + `privacy_url`；`standard_enhancements.enroll_status` |

**Ads that Click to WhatsApp**〔官API 2026-06〕：

| 项 | 值 |
|---|---|
| campaign.objective | `OUTCOME_ENGAGEMENT` / `OUTCOME_LEADS` / `OUTCOME_SALES` / `OUTCOME_TRAFFIC`（带通话提示 call prompts 必须 `OUTCOME_ENGAGEMENT`） |
| adset.destination_type | `WHATSAPP` |
| adset.optimization_goal（按目标） | ENGAGEMENT→`CONVERSATIONS`,`LINK_CLICKS`；SALES→`CONVERSATIONS`,`OFFSITE_CONVERSIONS`,`LINK_CLICKS`,`IMPRESSIONS`,`REACH`；TRAFFIC→`CONVERSATIONS`,`LANDING_PAGE_VIEWS`,`LINK_CLICKS`,`IMPRESSIONS`,`REACH`,`POST_ENGAGEMENT`；LEADS→`CONVERSATIONS` |
| adset.billing_event | 必须 `IMPRESSIONS` |
| adset.promoted_object | `page_id` 必填；`whatsapp_phone_number` 可选 |
| creative | object_story_spec（link/photo/text/video_data）+ `page_welcome_message`（VISUAL_EDITOR v2：欢迎语/预填/CTA）+ `degrees_of_freedom_spec`（Advantage+ creative） |

**Multidestination**〔官API 2026-05〕：destination_type 四值（见 §4.2）；optimization_goal 必须 `CONVERSATIONS`；promoted_object `page_id`；含 WhatsApp 需主页绑 WA 商业号、含 IG 需绑 IG 商业账户。

**Website ads click to message（网站广告带消息 CTA）**：独立指南存在〔官API 2026-06 存档〕，正文窗口未摘全——**具体组合未查证**。

---

## 6. Advantage+ 家族：开关、位置、默认值

### 6.1 Advantage+ campaign（系列体验）

〔三方 Jon Loomer 2025-06-23〕+〔官摘〕help 1292656978738967（About the Advantage+ Campaign Experience）+ help 1302408121002612（Advantage+ Leads 创建）：

| 项 | 内容 |
|---|---|
| 适用目标 | 仅 **Sales / Leads / App promotion**（其余目标仍走旧手动/定制流程） |
| 入口 | 2025 起这几个目标不再问「自动 vs 手动」，直接进精简 Advantage+ 创建；系列上标「Advantage+ on」 |
| 三要素 | **预算 / 受众 / 版位** ——不大幅改这三样，Advantage+ 保持 on |
| 预算 | Advantage+ campaign budget（CBO）**默认开**；切到广告组预算且建多个广告组 → off |
| 受众 | Advantage+ audience **默认开**（controls=硬约束；suggestions=软建议）；点「进一步限制广告覆盖人数」并取消建议勾选 → off |
| 版位 | Advantage+ placements **默认开**（界面不再显示该名，仅标 Advantage+ on）；「see more settings 查看更多设置」里的多数定制 → off（例外：仅 Android+WiFi、移除 Threads、排除可跳过视频等少数不关） |
| Advantage+ Shopping 关系 | Advantage+ Sales = Advantage+ Shopping 改名，但旧 ASC 的「无定向输入/不可改版位/单广告组/150 素材组合」限制全部取消，等同手动系列+保默认；≤50 广告/组（建议 ≤6） |

### 6.2 Advantage+ creative（创意）

〔官快〕About Advantage+ creative（help 297506218282224，2025-04-05 快照）+〔官API〕Get Started with Advantage+ Creative（2026-02-03 快照）：

- 位置：广告层创意区 → `Set up creative 设置创意 → Enhancements 增强功能`，逐项开关；**部分默认开**。
- 单图/单视频可用增强（官方清单）：Adjust brightness and contrast 调整亮度和对比度 / Add catalog items 添加目录商品 / Add details to ad layout 广告版面添加详情 / Add overlays 添加叠加文字 / Enhance CTA 增强行动号召 / Expand image 扩展图片 / Image animation 图片动画 / Music 音乐 / Relevant comments 相关评论 / Store locations 店铺位置 / Text improvements 文字改进 / Video effects 视频效果 / Visual touch-ups 视觉微调 / 3D animation。
- 轮播增强：Adapt multi-image format 适应多图格式 / Add details to ad layout / Dynamic description 动态描述 / Highlight carousel card 突出轮播卡片 / Info labels 信息标签 / Music / Profile end card 主页结束卡片 / Relevant comments / Text improvements / Visual touch-ups。
- GenAI：Image generation 图像生成（Backgrounds 背景 / Full images 全图）、Background generation（目录广告）、Expand image、Image animation、Text generation 文本生成（≤5 组主文案+标题变体）、Text improvements。
- 时效注：standard enhancements 增强组合包 2025-01-24 起在 UI 不再以整包提供；API 自 v22 起整包 opt-in 废弃，改 `creative_features_spec` 单项 `OPT_IN/OPT_OUT`（如 `image_touchups`/`inline_comment`/`image_template`；`adapt_to_placement` 默认 OPT_IN）。关闭入口：help 1082295769403815。

### 6.3 其余 Advantage+ 名词速查

| 名词 | 是什么 | 默认 |
|---|---|---|
| Advantage+ campaign budget（Budget with Advantage+ on） | 系列预算 CBO（help 343242619559352） | Advantage+ 流程中默认开 |
| Advantage+ audience | AI 受众找量（原 Advantage detailed targeting/lookalike/custom audience 扩散统一） | 默认开 |
| Advantage+ placements | 自动版位（原 Automatic placements） | 默认开 |
| Advantage+ creative | 创意自动增强 | 部分项默认开 |
| Advantage+ creative for catalog / Advantage+ catalog ads | 目录创意/目录广告（Ad setup 区开关） | 需目录，默认关 |
| Advantage+ sales/leads/app campaigns | 见 §6.1（ASC 更名+放开限制） | 三目标默认进 Advantage+ 流程 |

---

## 7. 与 ToveAds 现有实现的对照（顺手核对，非改动）

- `app/core/ad_builder.py`：CTA `SIGN_UP`+`value.lead_gen_form_id`（即时表单线索广告）、`page_welcome_message` VISUAL_EDITOR（消息广告欢迎语）——与本蓝图 §4.2 API 载体一致。
- 「1:1 三层投放模板」（memory tree-launch-templates）对应本蓝图 §1/§2/§3 的系列/组/广告三层；TT 不支持结构投放的差异仍成立（TT API 无 campaign 结构模板概念）。

---

## 8. 信源清单

### 8.1 官方帮助中心（facebook.com/business/help，经 Wayback 渲染快照读全文）

| 文章 | ID | 快照日期 | 用途 |
|---|---|---|---|
| Available conversion locations and events by objective | 2035196646663270 | 2024-11-21 | §2.1 全表 |
| About Performance Goals | 355670007911605 | 2025-02-01 | §2.2 全表 |
| Create ad campaigns in Meta Ads Manager（原 advertising levels） | 621956575422138 | 2025-05-05 | §0/§1/§2/§3 主干流程 |
| How to create a lead ad using Meta Ads Manager | 375478503258484 | 2024-11-05 | §2.1 Leads 7 转化位置、§3 广告层顺序 |
| Create ads that click to WhatsApp in Ads Manager | 447934475640650 | 2024-11-06 | §3.1 WA 号位置、§4.1 WhatsApp 调用位 |
| About ads that click to message | 1816962591668838 | 2024-11-15 | §2.6 版位联动、§4.1 |
| About ad destinations | 1174990279685960 | 2024-11-15 | §3.4 目的地特例 |
| About Advantage+ creative | 297506218282224 | 2025-04-05 | §6.2 增强清单 |

### 8.2 官方帮助中心（仅标题/摘要级：正文无渲染快照，标〔官摘〕）

- About the Advantage+ Campaign Experience — 1292656978738967
- Create Advantage+ Leads campaigns — 1302408121002612（"Budget 区默认 Advantage+ on/Campaign budget"）
- Set up Advantage+ campaign budget — 343242619559352
- Performance goals available by objective and conversion location — 416997652473726（**完整矩阵未读到正文**）
- About Advantage+ audience — 273363992030035
- About Instant Form types — 252352181957512
- About lead ads with instant form — 761812391313386
- Create a lead ad with instant form — 791294492679966
- About performance goals for lead ads — 782657799338685
- Create an ad that clicks to multiple message destinations — 1192884166182156
- How to create pre-filled messages for CTW — 687252309996046
- About WhatsApp Flows on CTW ads — 1216541683817423
- Create a new template for ads that click to Messenger or WhatsApp — 287043621933356
- About Meta bid strategies — 1619591734742116
- Turn off Advantage+ creative enhancements — 1082295769403815

### 8.3 Marketing API v25.0 开发者文档（Wayback 快照全文）

| 文档（developers.facebook.com/…） | 快照 | 用途 |
|---|---|---|
| …/ad-creative/messaging-ads/click-to-messenger（Updated 2026-02-11） | 2026-04 | §4.2/§5.2 CTM 链路、Messenger lead 模板 |
| …/messaging-ads/click-to-whatsapp | 2026-06 | §4.2/§5.2 CTW 链路、VISUAL_EDITOR 欢迎语 |
| …/messaging-ads/click-to-multidestination | 2026-05 | §5.2 多目的地 destination_type |
| …/messaging-ads/website-ads-click-to-message | 2026-06 | 存在性（正文未摘全） |
| …/messaging-ads（Overview，Updated 2025-08-19） | 2026-05 | 消息广告类型学（CTM/CTM-leads/CTM product extensions/click-to-subscribe/CTI/CTW/CTMD） |
| …/bidding/overview/budgets（Updated 2025-11-11） | 2026-05 | §2.4 预算规则 |
| …/creative/advantage-creative/get-started（Updated 2026-02-03） | 2026-05 | §6.2 API 单项 opt-in |
| …/get-started/basic-ad-creation/create-an-ad-creative | 2026-05 | §3.3 creative 结构 |
| /docs/marketing-api/reference/ad-campaign-group（AdCampaignGroup） | 2026-03 | objective 全枚举、promoted_object |
| /docs/marketing-api/reference/adgroup（Ad） | 2026-04 | 广告对象/creative 引用 |
| /docs/marketing-api/guides/lead-ads/ | 2026-04 | lead ads 前提/取数/CRM |
| /docs/marketing-api/campaign-structure | 2024-09 | §0 三层职责表 |

### 8.4 第三方佐证（〔三方〕，均为可达原文）

- Jon Loomer — Advantage+ Campaign Creation: A Complete Guide（2025-06-23）：§6.1 三开关/默认值/关断条件。
- Jon Loomer — Website and Instant Forms conversion location（2025-05）：§2.1 补充。
- media-beats.com — Create Lead Ads with Instant Forms（2026-05 更新）：§4.3 表单构成/100 上限。
- 1ClickReport / AdNabu / Socioh（2025-2026）：Advantage+ 默认化的旁证。

### 8.5 未查证/推断清单（使用本蓝图时须注意）

1. **Performance goal × 转化位置 完整矩阵**（416997652473726）——只有文章级摘要，逐格组合未读原文。
2. **Instant Form 挂载字段**：v25 lead-ads 指南只说 "associate the form ID"；`lead_gen_form_id` 挂 creative CTA value 的具体字段来自本仓库 ad_builder.py 的已验证实现+旧版 API 记忆，未从本轮原文复核。
3. **API 侧 ROAS Goal/Value 出价枚举**（`bid_strategy` 完整枚举）——消息文档只列 3 值。
4. **Website and instant forms 转化位置**——Jon Loomer 实测存在（2025-04），官方快照（2024-11）无此项；上线状态以账户实际为准。
5. **Create campaign in Ads Manager 独立文章**（1658289035439772）正文未读到；§1 主干取自同内容的「Create ad campaigns」文（2025-05 快照），两文疑为同源改版。
6. **消息模板 5 条上限、CTM 模板库 287043621933356 的具体步骤字段**——API 文档确认「≤5 template messages」；帮助中心逐步字段未读到。
7. Advantage+ campaign experience 官方正文（1292656978738967）未读到，§6.1 默认值以 Jon Loomer 2025-06 实测 + 官方文章摘要交叉。
8. Sales 目标成效目标清单在 2025-02 快照文本截断（"Maximize number of landing page views" 后缺尾部）。
9. 快照时效：帮助中心正文快照集中在 2024-11~2025-05，界面微调（措辞/分区顺序）可能与 2026-09 现版有出入；API 文档快照 2026 年较新，可信度高。
