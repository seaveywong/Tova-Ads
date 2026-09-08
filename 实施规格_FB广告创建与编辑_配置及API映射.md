# FB 广告创建与编辑：完整配置层级、API 映射与实施验收

更新日期：2026-09-09。用途：交给下一位 AI 实现 ToveAds 的 FB 创建/编辑流程。

**结论：常规三层创建、读取、部分字段编辑、素材/创意关联、表单关联和预览，有公开 API 路径；但不能保证 FB 界面全部功能都能通过当前账户的 API 实现。** 预订购买、部分 Advantage+ 功能、原生评分、实验、特殊目的地等必须单独核验，不能画一个开关就声称支持。

本文是配置与实施规格，不是已完成报告。本次仅做文档和只读核对，没有修改应用代码、创建广告或部署。

## 0. 证据等级和使用方法

每个选项必须区分四件事：**Meta 有无接口 → 当前 API 版本支持什么 → 当前账户/资产有无权限 → ToveAds 是否已接通并实测**。

| 标记 | 含义 | 开发处理 |
|---|---|---|
| A：接口已找到 | Meta 官方 SDK 有相关对象/方法/字段，并非本账户实测成功 | 实施字段级和账户级验证后才能开放 |
| B：条件能力 | 受目标、版本、账户资格、身份、版位或素材影响 | 条件展示；写明不可用原因；没有支持证据不能默认启用 |
| C：本地实现 | 草稿、面包屑、排序、布局等由 ToveAds 自己实现 | 不冒充 Meta 原生云端状态 |
| D：待核实 | 本轮没有找到足够的稳定公开接口证据 | 保留能力缺口，不发明参数，不做假保存 |

本轮直接访问 Meta Campaign/AdSet/Creative 开发者参考页均收到 HTTP 429，不能声称读到了这些页面最新全文。已改用 **Meta 官方 Python Business SDK 源码**核对创建与更新参数，并与仓库 `ad_builder.py`、创建蓝图交叉检查。官方 SDK `main` 是滚动版本，**不能直接当成项目 v25.0 的字段白名单**；本项目 `backend/app/core/fb_client.py` 固定 `GRAPH_VERSION = "v25.0"`，实施时需固定匹配版本/SDK提交并做实测。

旧蓝图的历史存档、第三方界面描述仅作参考。发现冲突要记录，不能默默合并成“官方确认”。

先读 [HANDOFF](HANDOFF.md)、[最新收尾交接](交接_广告管理器本轮收尾_20260909.md)、[1:1执行提示词](PROMPT_广告管理器重构.md)、[创建流蓝图](蓝图_FB广告管理器创建流.md)。本文不授权变更数据库 schema、重写资金执行引擎或操作1.0。

## 1. 完整界面层级

```text
创建 / 编辑广告
├── 顶栏
│   ├── 广告账户（显示币种、时区、权限）
│   ├── 草稿 / 未保存 / 保存中 / 已保存 / 发布结果
│   └── 关闭、放弃更改、检查并发布
├── 左侧对象树
│   └── 系列 → 广告组 → 广告
│       ├── 新增下级、复制、重命名
│       └── 未完成标记、错误数、选中项
├── 中间编辑区
│   ├── 系列
│   │   ├── 名称
│   │   ├── 购买类型
│   │   ├── 目标
│   │   ├── 特殊广告类别
│   │   ├── 预算归属、预算类型、金额
│   │   ├── 出价策略〔条件显示〕
│   │   ├── 系列支出上限〔条件显示〕
│   │   └── A/B测试、Advantage+相关配置〔条件显示〕
│   ├── 广告组
│   │   ├── 名称
│   │   ├── 转化位置
│   │   ├── 成效目标
│   │   ├── 数据集/像素/应用、转化事件
│   │   ├── 主页及消息身份〔条件显示〕
│   │   ├── 预算与排期
│   │   ├── 受众控制、受众建议
│   │   ├── 自动/手动版位
│   │   ├── 出价/费用/价值控制〔条件显示〕
│   │   ├── 归因设置〔条件显示〕
│   │   └── 受益人/付款人、品牌安全〔适用时〕
│   └── 广告
│       ├── 名称
│       ├── 身份：主页、Instagram、WhatsApp〔条件显示〕
│       ├── 创建广告 / 使用现有帖子
│       ├── 格式：单图/视频、轮播、精选集等〔条件显示〕
│       ├── 素材、裁剪、版位素材〔条件显示〕
│       ├── 正文、标题、描述、行动号召
│       ├── 网站 / 表单 / 消息 / 应用 / 即时体验
│       ├── 创意增强〔条件显示〕
│       └── 事件追踪、URL参数
├── 右侧预览与检查
│   ├── 按平台/版位预览
│   ├── 配置摘要
│   ├── 必填与兼容性错误
│   └── 本地检查建议（不冒充Meta评分）
└── 发布结果
    ├── 成功创建/更新对象及ID
    ├── 部分成功、失败阶段和可重试项
    ├── 配置回读结果
    └── 审核/投放状态（与发布请求成功分开）
```

前三层是用户界面；API 还包含独立 **Creative** 对象：`Campaign → AdSet → Ad → Creative引用`。树导航、草稿和批量编辑属于本地产品逻辑，不是直接照搬一条 Meta 接口。[官方账户创建方法](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adaccount.py)

## 2. 先选什么：用户配置顺序

1. **选账户**：确定可用资产、币种、时区和权限。换账户后，重新验证主页、像素、素材、表单等归属，不沿用失效ID。
2. **选业务目标**：想获得访问、表单、消息、购买或应用事件；不能仅凭素材类型猜目标。
3. **选转化位置**：网站、即时表单、消息应用等。它决定后面需要像素、表单还是消息身份。
4. **选成效目标/事件**：想优化点击、落地页浏览、线索还是购买。目标相同也可能允许不同优化方式。
5. **定预算归属与排期**：系列预算或广告组预算；日预算或总预算；按账户币种填写。
6. **配置受众和版位**：使用账户/目标允许的选项，不把所有 SDK 枚举直接堆成下拉菜单。
7. **配置广告身份、素材、文案和目的地**：即时表单和消息模板在这里关联，不能只保存本地模板ID。
8. **检查、预览、发布、回读**：区分草稿保存、API接受、审核通过、正在投放四种结果。

输入框遵循项目规则：不预填默认金额/文本。必填项没有值就阻止发布；可选项为空时通常省略字段，**不把空值自动转成0、空字符串或清空线上配置**。后端有默认策略时，在摘要中显示实际解析结果和来源。

## 3. 系列 Campaign：配置与接口

创建：`POST /v25.0/act_{account_id}/campaigns`。读取：`GET /v25.0/{campaign_id}`。更新：`POST /v25.0/{campaign_id}`。各调用字段白名单不同；不能把读取对象完整回传。

| 面板 | 用户怎样配置 | API映射/等级 | 编辑规则与校验 |
|---|---|---|---|
| 名称 | 填写能区分市场、产品、策略的名称 | `name`；A | 可更新，提交后回读；不强加固定命名模板 |
| 购买类型 | 通常使用竞价；预订仅对有资格账户开放 | `buying_type`；竞价A，预订B | 不保证已建系列能转换；预订不是换个枚举即可接通 |
| 目标 | 从六个业务目标中选择 | `objective`；A | 编辑已有目标视为受限操作，先核对版本/状态，不承诺任意更改 |
| 特殊类别 | 按实际业务选择，无适用类别才明确选择“无” | `special_ad_categories`及适用国家；B | 联动受众限制；枚举按版本/地区，不猜名称 |
| 预算归属 | “系列统一分配”或“各广告组分别设置” | 本地预算模式映射对应对象字段；A/C | 当前项目用CBO/ABO；不是名为budget_mode的Meta通用字段 |
| 日/总预算 | 选择类型后填账户本币金额 | `daily_budget` / `lifetime_budget`；A | 不同时设置；转换为账户规定的最小单位，不能所有币种一律×100 |
| 出价策略 | 最高数量、费用/竞价限制、价值相关策略等，按能力开放 | `bid_strategy`及相关字段；B | 预算归属决定字段落点；费用和ROAS不能混为同一数值 |
| 支出上限 | 可选，限制整个系列累计支出 | `spend_cap`；B | 与日/总预算含义不同；清除上限必须是明确动作 |
| A/B测试 | 选择比较变量、范围、实验预算/周期 | 独立实验能力；B/D | 本轮未核验完整实验接口；禁止只存is_ab_test并宣称已建实验 |
| Advantage+系列体验 | 按目标和实际能力组合配置 | 多个字段/系统资格；B | 不存在本文可确认的万能advantage_plus=true开关 |
| 原生评分/建议 | 仅在取得真实来源时展示 | 与完整创建评分对应关系D | 可做本地检查列表，但不能伪造Meta机会分数 |

六目标映射（本仓库构建器与旧蓝图一致，实施需继续验组合）：知名度 `OUTCOME_AWARENESS`；流量 `OUTCOME_TRAFFIC`；互动 `OUTCOME_ENGAGEMENT`；潜在客户 `OUTCOME_LEADS`；应用推广 `OUTCOME_APP_PROMOTION`；销量 `OUTCOME_SALES`。旧目标可为历史数据显示，不自动开放旧枚举新建。

更新参数存在不代表每种线上状态均允许修改；官方 SDK 的 Campaign 创建与更新列表也并不相同。[官方 Campaign 源码](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/campaign.py)

## 4. 广告组 AdSet：配置与接口

创建：`POST /v25.0/act_{account_id}/adsets`。读取/更新对象：`/{adset_id}`；请求携带既有 `campaign_id`，不能因编辑把实体悄悄移到另一系列。

| 面板 | 用户怎样配置 | API载体/等级 | 必须执行的联动 |
|---|---|---|---|
| 名称/父级 | 命名并确认所属系列 | `name`、`campaign_id`；A | 父级、账户、租户严格一致 |
| 转化位置 | 网站/表单/消息/应用等 | `destination_type`与关联参数；B | 使用目标兼容矩阵，不照中文直译枚举 |
| 成效目标 | 选希望系统优化的结果 | `optimization_goal`；B | 与目标、位置、事件及计费方式一起验证 |
| 计费方式 | 常规用户可由已验证策略解析，高级用户按能力选择 | `billing_event`；B | 点击优化不等于必须按点击计费 |
| 像素/事件 | 网站转化时选择有权限的数据源及事件 | `promoted_object`；B | pixel_id、标准事件或custom_conversion_id按场景组装，不同时乱塞 |
| 应用 | 选择应用和应用目的地/事件 | `promoted_object`及应用配置；B | SDK、应用权限、商店及归因能力另验 |
| 消息/主页身份 | 选择主页和已关联消息资产 | `promoted_object`及目的地配置；B | 必须与广告创意身份一致 |
| 预算 | ABO在此设置；CBO展示系列来源 | 日/总预算字段；A | 不在两个层级重复提交相同预算；组花费上下限另作条件能力 |
| 开始/结束 | 按账户时区选择；总预算必须明确排期策略 | `start_time`、`end_time`；A | 开始早于结束；显式处理偏移/DST，不能直接用浏览器本地时区 |
| 分时排期 | 选择星期和时段，仅兼容模式开放 | `adset_schedule`等；B | 受预算、购买类型和版本约束，非法组合前置拦截 |
| 受众 | 地区、年龄、性别、语言、已有受众等 | `targeting`；A/B | 目标和特殊类别收窄选项；详见下一节 |
| 版位 | 自动分发，或明确手动选择 | `targeting`的版位字段；B | 手动模式至少有合法版位；自动模式不能伪装为冻结的“全部枚举” |
| 成本/竞价/价值 | 根据策略填费用或比率 | `bid_amount`、`bid_constraints`等；B | 账户币种金额与ROAS比率分别处理，不做任意透传 |
| 归因 | 从账户/目标支持的点击/浏览窗口中选择 | `attribution_spec`等；B | 不预填全目标通用窗口；报告与FB对账使用同一口径 |
| 受益人/付款人 | 按所投地区填写实际主体 | `dsa_beneficiary`、`dsa_payor`等；B | 地区要求以当期政策/API为准；不拿租户名称静默替代 |
| 品牌安全 | 按可用清单/库存控制设置 | 对应品牌安全/定向字段；B | 有字段也需资产权限及版位支持 |
| 动态素材/自动化 | 按实际版本和组合开放 | 与素材/目标多字段关联；B | 不把动态素材、Advantage+受众、创意增强合成同一个开关 |

字段级参考：[官方 AdSet 创建/更新模型](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adset.py)。本轮确认有预算、定向、排期、归因、出价和提升对象相关参数，未执行本账户远端写验证。

### 4.1 受众和版位怎么配置

| 控件 | 配置方式 | 开发注意 |
|---|---|---|
| 地点 | 搜索国家/地区/城市，区分包含和排除 | 使用Meta认可的地理标识；不是把城市中文名直接传入 |
| 年龄/性别 | 仅开放当前目标/特殊类别允许值 | Advantage+下部分值可能是建议，UI必须区分硬限制与建议 |
| 语言 | 搜索并选择语言 | 语言locale ID不是国家代码 |
| 自定义受众 | 从当前账户有权限列表选择 | 用外部受众ID；受众仍处理中/不可用时阻止错误引用 |
| 类似受众 | 选已有对象，或走独立创建流程 | 不能把“相似1%”作为普通targeting字符串 |
| 兴趣/详细定位 | 搜索可用对象后选择 | 不把SDK历史排除字段视为当前仍支持的功能 |
| 自动版位 | 显示自动策略及其限制 | 由版本适配器组装，避免残留手动字段 |
| 手动版位 | 平台→设备→版位逐层勾选 | Facebook/Instagram等各自positions与publisher_platforms一致；无权使用的身份/版位不可选 |

`targeting` 官方模型中可见地理、年龄、性别、受众、语言和版位载体，但其中枚举不构成任意组合可用的保证。[官方 Targeting 源码](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/targeting.py)

## 5. 广告与创意：配置与接口

通常先创建 Creative：`POST /v25.0/act_{account_id}/adcreatives`，取得 creative_id；再创建 Ad：`POST /v25.0/act_{account_id}/ads`，关联广告组和创意。

| 面板 | 用户怎样配置 | 映射/等级 | 注意 |
|---|---|---|---|
| 广告名称 | 输入名称 | Ad的`name`；A | 与Creative内部名称分开 |
| Facebook身份 | 选择实际投放主页 | `object_story_spec.page_id`；A/B | 验证当前广告账户可使用，不只验证主页存在 |
| Instagram身份 | 选择关联且有权使用的身份 | story spec身份字段；B | **版本冲突待核验**：本地使用instagram_actor_id，官方SDK main出现instagram_user_id，不能盲改或两字段全传 |
| WhatsApp身份 | 选择与主页关联的业务号码 | 组/创意对应字段；B | 不是任意电话号码输入框；号码格式与绑定都要核验 |
| 创建广告 | 独立填写素材与文案 | `object_story_spec`等；A | 单图、视频各自使用对应分支 |
| 使用现有帖子 | 从可访问帖子列表选取 | `object_story_id`；A/B | 与新建story spec互斥；不能声称原地改了原帖正文 |
| 单图 | 选择/上传图片 | image hash及link data；A | 素材属于正确账户；已删除/失效素材需明确报错 |
| 视频 | 上传或选视频，等处理就绪 | video ID及video data；A/B | 上传接受不等于编码完成、可投放 |
| 轮播 | 添加卡片，每张配置素材/标题/链接 | link data子卡片等；B | 数量、混用、排序和目的地约束另验；本轮未远端验证 |
| 精选集/目录/即时体验 | 选择相应目录/体验资产 | 额外对象链；B | 不是单图加一个format字段；单独实现验收 |
| 正文/标题/描述 | 按格式填写，版位预览实际显示位置 | link/video data，或多素材结构；A/B | 某版位不展示描述时不意味着提交失败 |
| 行动号召 | 从当前目的地允许值选择 | `call_to_action`；B | 网站、表单、消息的value形状不同 |
| 网站目的地 | 输入最终URL，可带受支持参数 | link data、CTA和`url_tags`等；A/B | 展示链接不是实际跳转地址；拒绝空/非法协议 |
| 即时表单 | 选同主页已发布表单，或先创建发布 | CTA关联外部form_id；A/B | 本地模板ID不能当Meta表单ID；详见§6 |
| 消息模板 | 根据Messenger/IG/WhatsApp选择模板 | `page_welcome_message`等；B | 不同渠道结构不同，不能一套JSON通吃 |
| 创意增强 | 逐项选择明确支持的增强 | `degrees_of_freedom_spec`等；B | SDK字段存在不等于所有增强项仍可写；旧整包参数不能直接复制 |
| 追踪 | 设置事件数据源、URL参数 | 组的提升对象 + 创意/广告追踪字段；B | 发送像素/CAPI事件是另一条集成链，不能只填pixel_id就宣称已通 |
| 预览 | 切平台/版位看结果 | preview相关接口；A/B | 官方预览失败时明确显示本地模拟，不冒充实际投放渲染 |

身份结构证据：[官方 ObjectStorySpec](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adcreativeobjectstoryspec.py)。创意字段及修改范围：[官方 Creative](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adcreative.py)。

### 5.1 关键：创建和编辑不是同一套表单提交

| 更改 | 推荐处理 | 不允许的处理 |
|---|---|---|
| 名称、允许更新的预算/排期/状态 | 读取线上原值，构造允许字段diff，调用既有执行函数并回读 | 把整份GET结果POST回去 |
| 图片、视频、正文、标题、CTA、目的地等创意内容 | 默认按“创建新Creative→关联已有Ad”的受控流程实现；具体广告形态需实测 | 向Creative原对象随意POST所有内容字段 |
| 原帖广告的内容 | 提示编辑范围；必要时新建创意/广告并明确变化 | 宣称保留原帖互动且任意改正文一定可行 |
| 系列目标、购买类型、预算模式、组归属等结构变化 | 标明受限，校验是否允许；不允许时提供明确的复制/新建流程 | API拒绝后偷偷新建或移动对象，UI还说原地保存成功 |
| 清空可选字段 | 单独定义clear动作及API语义 | 空输入统一变0或null覆盖线上值 |

本轮官方Creative更新方法仅列出少数元信息；Ad更新参数包含creative关联。因此“新建Creative后更换关联”是实施路径，**不是所有内容不可变或所有广告都一定能替换的绝对承诺**。[官方 Ad 更新接口模型](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/ad.py)

## 6. 目的地分支：表单、消息、网站和应用

### 6.1 即时表单

配置顺序：选择主页 → 选择表单模板/新建 → 设置语言和表单内容 → 发布到该主页 → 取得Meta form_id → 关联广告。

表单编辑子菜单：

```text
即时表单
├── 名称、语言
├── 表单类型/质量选项〔条件显示〕
├── 简介：标题、说明、封面
├── 联系信息字段
├── 自定义问题：文本/选择题〔按支持类型〕
├── 隐私政策链接、免责声明〔适用时〕
├── 完成页：标题、说明、后续操作
├── 预览
└── 保存本地模板 / 发布到主页
```

官方 SDK 提供 `POST /{page_id}/leadgen_forms`，有名称、语言、问题、隐私政策、简介和完成页等创建载体。更多数量/更高意向/富创意不能未经核验就映射成自造的 `form_type` 枚举；表单发布后的编辑限制需单独处理。[官方 Page 表单创建方法](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/page.py)

项目当前关联路径在 `build_creative()`：`call_to_action.value.lead_gen_form_id`。这是仓库已有路径，本轮未实际创建/回读新表单；应同时验证主页归属、lead权限、表单状态和真实线索回传。**创建表单、读取线索、订阅Webhook是三个不同能力**，不能只因表单创建200就全部打勾。

### 6.2 Messenger / Instagram Direct / WhatsApp

- 用户先在广告组选转化位置，再在广告层选择对应身份与模板。显示渠道专属编辑器，不让WhatsApp模板误挂到Messenger。
- 普通欢迎语、快速问题、Messenger线索问答、WhatsApp预填消息及WhatsApp业务主动发送模板是不同概念。
- 当前仓库有 `build_welcome_message()`、`build_wa_welcome_message()`、`parse_message_template()`；下一位先读取实现和蓝图证据，不另写一套执行链。
- 多目的地组合、特殊问答结构、消息转化优化均为B；未核验到的渠道模板功能标D。参考旧蓝图§4、§5，其历史存档证据不能代替本账户当前实测。

### 6.3 网站与应用

- 网站点击/浏览场景不应强制所有用户选购买事件；网站转化场景需数据源和兼容事件。
- 应用场景需应用ID、商店/应用目的地与对应事件能力；网页像素不能当应用事件源。
- 网站+应用、网站+店铺等混合目的地为条件能力，必须单独配置/验证，不拼接两个字符串假装支持。

## 7. 场景配置示例（指导用户选择，不是自动预填）

| 想达到的效果 | 系列选择 | 广告组配置 | 广告层配置 | API判断 |
|---|---|---|---|---|
| 把人带到网站 | 流量 | 网站位置；选支持的点击/落地页浏览目标；受众与预算 | 主页+图片/视频+网站URL+CTA | 常规链路A/B，需校验优化组合 |
| 收集站内表单线索 | 潜在客户 | 即时表单位置；兼容线索优化；主页 | 同主页已发布即时表单+素材+CTA | 表单与广告均有接口；关联/权限需实测 |
| 收集网站线索 | 潜在客户 | 网站；像素/自定义转化；兼容线索事件 | 真实线索页面URL | 需确认事件确实收到，不用页面浏览冒充Lead |
| 网站购买 | 销量 | 网站；有权使用的像素；Purchase等合法事件 | 商品/落地页URL+素材 | 需确认实际购买事件及归因口径 |
| 获取WhatsApp对话 | 兼容的互动等目标 | WhatsApp位置；关联主页/号码；支持的消息优化 | 消息CTA、对应欢迎/预填配置 | B，不能只改URL为wa.me就声称完整消息广告 |
| 推广应用 | 应用推广 | 应用与受支持优化/事件 | 商店或应用目的地、素材 | B，应用资产和测量链另验 |

这些是起始方案，不是账户投放建议或保证效果。未知业务信息保持空输入，由用户决定预算、受众、目标和是否投放。

## 8. API 请求链与示意载荷

### 8.1 网站流量单图：展示对象关系

以下是**结构示意，不是复制即可执行的最终payload**。尖括号需替换；预算字符串需换成账户最小单位整数字符串；必填/优化组合需由当前版本适配器完成。没有包含凭据。

```json
{
  "campaign": {
    "name": "<用户填写系列名>",
    "objective": "OUTCOME_TRAFFIC",
    "buying_type": "AUCTION",
    "special_ad_categories": [],
    "status": "PAUSED"
  },
  "adset": {
    "name": "<用户填写组名>",
    "campaign_id": "<前一步返回ID>",
    "daily_budget": "<账户本币最小单位正整数>",
    "billing_event": "IMPRESSIONS",
    "optimization_goal": "LINK_CLICKS",
    "destination_type": "WEBSITE",
    "targeting": {"geo_locations": {"countries": ["<用户选择的国家代码>"]}},
    "status": "PAUSED"
  },
  "creative": {
    "name": "<创意名称>",
    "object_story_spec": {
      "page_id": "<有权使用的主页ID>",
      "link_data": {
        "image_hash": "<该账户可用图片hash>",
        "link": "https://example.com/product",
        "message": "<用户正文>",
        "name": "<用户标题>",
        "call_to_action": {"type": "LEARN_MORE", "value": {"link": "https://example.com/product"}}
      }
    }
  },
  "ad": {
    "name": "<用户广告名>",
    "adset_id": "<组创建结果ID>",
    "creative": {"creative_id": "<创意创建结果ID>"},
    "status": "PAUSED"
  }
}
```

外层四个对象是本文便于阅读的包装，**不是Meta支持的一次提交格式**。实际顺序是：准备素材 → 创建系列 → 创建组 → 创建Creative → 创建Ad，各自取得ID再传下一步。每步均可能失败，不能把最后一步失败当成前面没创建。

示例的PAUSED仅用于显式测试/草稿场景说明，不是学习期或保护期。**当前仓库构建器会产生ACTIVE，不能直接执行示例所述现有部署函数做“安全测试”**；必须先确认测试专用入口能保证各层暂停。未提供明确测试账户时，仅进行mock/只读/预检，不为了验证而改真实投放。

### 8.2 编辑示意

```text
读取当前Ad及Creative
→ 用户修改正文
→ 服务端只白名单提取可用于创建的Creative内容
→ 创建新Creative并拿到ID
→ 通过已验证/审核后的关联路径更新Ad的creative引用
→ 回读Ad引用与新Creative正文
→ 成功、部分成功、未核验分别显示
```

失败时保留已知对象ID与阶段；不要盲目重发整个创建请求造成重复系列/广告。不要假设Meta有适用于所有写请求的通用幂等键；复用本项目任务/锁/重试去重机制。

## 9. ToveAds 当前代码：哪些能复用，哪些还要查

| 位置 | 本轮确认到的内容 | 下一位要做什么 |
|---|---|---|
| `backend/app/core/fb_client.py` | v25.0、通用GET/POST、状态/预算与对象读取 | 不从前端直接传Meta token；保留账户选令牌路径 |
| `backend/app/core/ad_builder.py` | `build_campaign`、`build_adset`、`build_creative`、目标/转化位置矩阵、表单/消息构建器 | 优先复用；区分构建payload与实际请求成功 |
| `backend/app/routers/launch_templates.py` | `/{tid}/preflight`、`/{tid}/deploy`、任务查询及重试；树部署已创建系列/组/创意/广告 | 读完整守卫和执行逻辑；不要重复实现资金链 |
| `backend/app/routers/form_templates.py` | 本地表单/消息模板CRUD与表单部署 | 模板ID、外部表单ID和版本关联不能混用 |
| `backend/app/routers/ads.py` | 管理列表、改名/状态/预算等；本轮未部署的表格配套改动 | 新编辑器先验证能复用哪些路由；不能假设已有全字段编辑接口 |
| `frontend/src/views/LaunchTemplates.vue` | 既有三层模板入口，旧交接称已接结构创建 | 本轮未完整审查该页面，需实测后再给完成标记 |
| `frontend/src/views/AdManager.vue` | 当前本地合并表格等改动来自f8dc294，尚未上线验收 | 和创建编辑入口贯通；不能以本规格替代前一批验收 |

本轮发现的具体待核对点：

1. 本地Instagram身份键和官方SDK main不同，先锁定v25规则，不盲改。
2. 构建器某些出价别名/归一化存在多种分支，要检查是否保留用户选择，不能遇到非法值默默换成另一投放策略。
3. 后端已有目标/受众等fallback，但用户不预填规则要求明确显示解析来源；目标切换后的旧字段不能经深合并泄漏。
4. 现有蓝图“Creative创建后不可改”过于绝对，应按§5.1区分元信息更新与内容替换。
5. 旧蓝图及SDK所列枚举包含历史或新版本能力，不能全部作为当前UI可选项。

## 10. 给实施AI的架构建议（建议，不是已存在接口）

在现有架构内拆成四个职责，避免一个Vue文件维护全部条件：

- **能力与约束解析**：输入账户、版本、目标、转化位置、资产权限，返回可选项、必填项、受限原因及证据等级。优先静态验证矩阵+真实资产读接口；不要假设有一个万能Meta能力API。
- **编辑状态**：区分用户输入、继承值、后端默认、线上值和待发布diff；切换目标/预算归属时清理或明确提示失效字段。
- **预检与发布编排**：调用现有构建器及任务体系，输出可读摘要、错误路径、对象数量、预算归属和发布状态；不重写已验证执行函数。
- **结果读取**：以外部对象回读为准；本地optimistic更新不能冒充Meta生效，预览和审核状态另列。

UI字段至少维护：字段路径、中文/英文label、控件类型、显示条件、必填条件、读取映射、创建映射、更新映射、金额/时间单位、清空语义、兼容版本、权限要求、测试证据。不要用一个raw JSON输入框代替完整编辑器。

## 11. API 可实现性验证清单

### 11.1 只读和权限

- [ ] 记录当前项目API版本与所用SDK标签/提交；不直接升级版本。
- [ ] 验证令牌访问当前广告账户和写入能力；常见ads_read/ads_management与业务/主页/线索权限按端点核实，不一次索要所有权限。
- [ ] 验证主页、IG/WA、像素/应用、表单、素材确实属于可用授权范围；多租户不能借其他租户的资产或令牌。
- [ ] 凭据只由后端持有；文档、日志、前端、测试报告不落明文token。

### 11.2 不花钱的本地验证

- [ ] mock目标×转化位置矩阵，断言合法组合与非法组合；前后端使用一致规则。
- [ ] 断言ABO/CBO字段落点、日/总预算互斥、特殊币种换算、排期时区、清空语义。
- [ ] 图片/视频/帖子/表单/消息分别断言payload，不用一个素材案例代表全部。
- [ ] 模拟部分成功、超时未知、重试、回读失败、身份失效，不允许重复创建或假成功。
- [ ] 某些端点支持`execution_options`校验模式，但逐端点核实；不能假设所有调用都有通用dry-run。

### 11.3 受控平台验收

仅在明确测试对象/授权范围内执行写操作，禁止拿生产投放随意测试。

- [ ] 先验证各层测试状态能保持PAUSED，再用当前版本创建最小链路。
- [ ] 回读系列目标/预算、组定向/事件/排期、广告创意引用；断言具体值，不只检查id存在。
- [ ] 测试改名、预算及创意替换路径的可编辑性；不支持的操作给准确说明。
- [ ] 表单发布后回读且归属正确；线索回传需要独立测试。
- [ ] 预览API输出与界面身份、素材、目的地一致；审核和投放状态单独显示。
- [ ] 测試对象和资源按原计划恢复/清理，保留必要审计证据，不能误删真实对象。

### 11.4 对标和上线

- [ ] 固定FB参考账户/目标/语言/视口，逐面板对照截图与操作；未见到的功能不标“已1:1”。
- [ ] 矩阵逐项标注：A/B/C/D → 本地已接 → 测试账户验证 → 生产验收；四级不能混写。
- [ ] 遵循HANDOFF：本地门检、commit、备份与源码差异核对、部署双门、restart/health、数据断言smoke、journal检查、push、TECH_REVIEW。
- [ ] 交付已验证功能清单及API受限清单。接口不开放的功能要准确呈现，不能用模拟评分、静态开关或永远success替代。

## 12. 下一位AI可直接执行的提示词

```text
接手ToveAds 2.0的FB广告创建与编辑1:1复刻。
先读HANDOFF和最新收尾交接，再完整阅读《实施规格_FB广告创建与编辑_配置及API映射.md》。
目标是系列→广告组→广告的完整创建与编辑体验，真实后端/API接通，按文档逐字段实现配置、依赖、权限、预检、发布、回读和错误反馈。

先核对当前v25.0与官方资料/对应SDK版本；字段存在不等于当前账户可用，创建支持不等于编辑支持。
复用现有ad_builder、模板/任务/表单体系，保留已验证资金执行函数，不另造部署链，不动1.0或schema。
先浏览器审查已有页面，再用字段映射表和对标证据矩阵推进。补完常规路径后验证消息、表单、应用、轮播及其他条件能力。
创意内容更改优先按新建Creative并更换Ad关联的受控流程处理，不能把所有字段POST给旧Creative。
测试不随意操作真实投放；先mock和只读检查，需要远端写验证时使用明确测试对象并保证各层暂停。
遵循zh/en同步、英文零CJK、输入不预填、无彩色emoji、无学习/保护期、通知dedup及先commit后部署等规则。
持续完成实际浏览器、数据断言、部署和上线回归；不能用build或HTTP200宣称1:1完成。
最后交付逐项完成/API条件限制/未验证清单及证据，更新TECH_REVIEW和交接。现在执行，不停在计划。
```

## 13. 核对来源

以下官方源码于本轮读取成功；main会变化，执行AI需要固定提交并核对v25.0。

- [Meta官方SDK：账户创建入口与预览](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adaccount.py)
- [Meta官方SDK：Campaign](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/campaign.py)
- [Meta官方SDK：AdSet](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adset.py)
- [Meta官方SDK：Ad](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/ad.py)
- [Meta官方SDK：Creative](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adcreative.py)
- [Meta官方SDK：身份与Story结构](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adcreativeobjectstoryspec.py)
- [Meta官方SDK：Targeting](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/targeting.py)
- [Meta官方SDK：Page表单入口](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/page.py)
- [项目既有创建蓝图及历史来源](蓝图_FB广告管理器创建流.md)

本轮直接访问以下开发者页返回429，列出用于后续核验，**不将其作为本轮已读证据**：[Campaign创建](https://developers.facebook.com/docs/marketing-api/reference/ad-account/campaigns/)、[AdSet创建](https://developers.facebook.com/docs/marketing-api/reference/ad-account/adsets/)、[Creative参考](https://developers.facebook.com/docs/marketing-api/reference/ad-creative/)。
