# 审计报告：投放模板编辑器（FB 三段手风琴）UX 与逻辑

- 日期：2026-09-08 · 性质：**只审计不改代码**（未动任何源文件、未部署）
- 对象：`frontend/src/views/LaunchTemplates.vue`（3465 行）— FB 三段手风琴（系列/组/广告）+ 目标选择弹窗 + 部署抽屉 + 预检弹窗
- 交叉核对：`backend/app/routers/launch_templates.py`（结构校验/部署 runner/预检/预算守卫）、`backend/app/core/ad_builder.py`（FB payload 构造）、`backend/app/core/ad_ops.py`（deploy_one_account/pick_random_copy）、`frontend/src/locales/views/launch.js`（文案）
- 基准：FB Ads Manager 2025 创建流（ODAX 六目标、Advantage+ campaign budget/audience/creative、组层 performance goal/placements/bid control、广告层 identity/creative/Instant Form/欢迎语）
- 前提事实：**FB 模板一律强制结构（树）模式**（`openEdit` 末尾 `_synthTreeFromFlat`，LaunchTemplates.vue:1281），模式切换控件已从 UI 移除（`onModeSwitch`/`flatFromTree` 定义于 :971 但模板无引用）——大量「平铺 FB」分支实为不可达死代码。TT 模板仍走平铺。

---

## 一、系列段（Campaign）

**字段清单 → FB 对应层**：模板名、目标（只读 chip 点击重开 picker）→ FB Objective；转化目标 → FB Performance Goal 的转化事件；特殊广告类别 → Special Ad Categories（✓ 5 枚举与后端一致）；购买类型（只读=竞价）→ Buying Type；预算模式 ABO/CBO → Advantage+ Campaign Budget（✓）；预算类型+日/总额 → Budget（✓）；出价策略/出价额/最小 ROAS → Bid Strategy（✓ 五枚举对齐）；支出上限 → Campaign Spending Limit（✓）；命名前缀/主页（⚠ 主页属 FB 广告层「身份」）。

| # | 问题 | 严重度 | FB 基准对照 | 建议（不动代码） |
|---|---|---|---|---|
| C1 | **CBO+总额预算在树模式是死路**：部署守卫 `_budget_guard_400` 查模板级 `schedule_start/end`（launch_templates.py:1126），前端 `startDeploy` 同口径拦截（:1766-1769）；但树模式**没有任何模板级排期输入**（组级排期 `s.schedule_start` 不回写模板列，`_sync_flat_from_structure` 不含排期），保存也放行（TemplateIn 不校验）→ 可保存、不可部署，报错「必须设置排期」指向一个不存在的字段。提示语 `lifetimeScheduleHint`（"在下方广告组段设置"）在树模式是错的 | **P0** | FB：lifetime 预算必配排期，且排期与预算同屏 | CBO 选中时隐藏「总额」选项（树模式）；或系列段在 CBO+lifetime 时显示模板级排期输入；短期至少把守卫报错改为可行动文案（指明回编辑器切单日预算） |
| C2 | **「转化目标」下拉对部署 payload 基本无效**：`_deploy_item_fb_tree`/`deploy_one_account` 均不把 `conversion_goal` 传给 `conversion_event`，`build_adset` 里 `custom_event_type` 恒为 `'PURCHASE'`（SALES）/`'LEAD'`（LEADS-网站，ad_builder.py:230-254）；`_OPT_GOAL_MAP` 的 key 词表（`offsite_conversions/lead_generation/...`）与前端选项（`Purchase/AddToCart/...`）完全不匹配，选什么都走 fallback | **P1** | FB：转化事件选择直接决定 `promoted_object.custom_event_type` | 接通 `conversion_goal→conversion_event`；或下拉旁标注「仅影响优化方向参考，转化事件按目标默认 Purchase/Lead 下发」并在预检明示 |
| C3 | **APP_PROMOTION 目标可选但链路不支持**：目标 picker 提供该选项（含转化事件 APP_INSTALLS 等），但编辑器无 app_id/application 字段，`build_adset` 无 `OUTCOME_APP_PROMOTION` 分支（无 promoted_object）→ 部署必被 FB 拒 | **P1** | FB：应用目标必须选应用/商店 | picker 中禁用该选项并注明「暂不支持」，或补应用绑定字段 |
| C4 | **目标切换后 optimization_goal/conversion_goal 残留**：watch 只在「空值或等于旧目标默认值」时覆盖（:171-185），手选值跨目标残留。例：SALES 手选 `VALUE` → 切 TRAFFIC 仍 `VALUE`，经 `optimization_goal` 显式覆盖直达 FB payload → FB 400；conversion_goal 残留则在下拉里显示一个不在选项集内的裸值，切到 TRAFFIC/ENGAGEMENT/AWARENESS 时选择框整个消失但值照常保存 | **P1** | FB 切换目标会重置 Performance Goal 并按新目标过滤可选项 | 换目标时强制按新目标白名单重算（保留提示）；保存前按 objective 过滤这两个字段 |
| C5 | 主页放在系列段：FB 的 Page/IG 身份在**广告层**；树模式全局单一 `page_id`，不同广告不能各用各的主页 | P2 | FB：identity per ad | 接受简化，但系列段主页处加 hint「所有广告共用此主页」；长期把身份下沉到广告节点 |
| C6 | 空白表单预填默认值（`budget_usd:5`、`name_prefix:'Tova Ads'`、`cta_type:'LEARN_MORE'`，:575-606），违反「输入框不预填默认值（空=用后端默认）」的项目约定 | P2 | — | 与用户确认后改为空 + placeholder 说明 |
| C7 | 编辑器内换目标无二次确认、无下游影响提示（LEADS/ENGAGEMENT 的绑定区块随之隐藏且值静默保留）；目标弹窗里填了名字会直接覆盖已有模板名（`objPickerContinue`） | P2 | FB 换目标有确认弹层 | 换目标时 toast 提示「已按新目标重置优化默认值；表单/消息绑定保留但不再生效」 |

系列段判定：字段集与 FB campaign 层**一致性整体良好**（目标/特殊类别/CBO/支出上限/出价策略均对得上，支出上限 hint 把「与预算的语义区别」说清了）；缺 A/B 实验、品牌安全（可接受的简化）；**核心问题是 C1 死路与 C2 摆设字段**。

---

## 二、组段（Ad Set）

**字段清单（树组卡）→ FB 对应层**：转化位置（只读自动）→ Conversion Location（✓ 但只读）；转化像素 → FB 组层 promoted_object（⚠ 绑的是模板级全局值）；预算与排期（ABO 组级日/总额+排期+投放方式）→ Budget & Schedule（✓）；出价控制折叠 → Bid Control（✓ 折叠+当前值摘要，做得好）；受众覆盖（仅 SavedAudience 下拉）→ Audience（✗ 缺内联）；优化目标覆盖 → Performance Goal；披露 beneficiary/payer → DSA（✓ 且标明模板级共用）。

| # | 问题 | 严重度 | FB 基准对照 | 建议（不动代码） |
|---|---|---|---|---|
| S1 | **树模式没有任何受众编辑路径，不选受众=静默投美国**：组卡只有 SavedAudience 下拉（0=「用模板默认」）；而内联受众（国家/年龄/性别/语言/兴趣搜索/Advantage+ 受众开关）全部只存在于**不可达的平铺分支**（:2224-2295）。后端 `_resolve_targeting` 返 None 时 `build_adset` 静默兜底 `{countries:["US"],18-65}`（ad_builder.py:192）。文案还反向暗示没事：`audienceSourceHint`「都不填=FB 默认最宽定向」、`treeAudienceDefault`「用模板默认」——实际是 **US-only**，全程无提示 | **P0** | FB：受众（含国家）是创建流必经步骤，绝无静默国家默认 | 组卡补内联受众区（国家/年龄/性别最少集），或系列段加模板级受众；短期先把两处文案改为「不选受众=投美国（后端默认）」并在预检组行显示实际国家 |
| S2 | **FB 平铺组段整套死代码/能力不可达**：模式切换控件已移除，FB 恒树模式 → 内联受众、版位（手动/Advantage+）、设备、频次上限、归因窗口、Dayparting、Advantage+ 受众开关、性能目标 CPA、模板级优化/计费/目的地、高级 JSON，**对 FB 模板全部无法编辑**（仅 TT 用平铺残壳）。这些设置随旧数据恢复并在保存时回写（openEdit/saveTpl 均处理），但用户看不到也改不了 | **P0** | FB：placements/dayparting/attribution 均为组层常规设置 | 把版位/频次/归因/Dayparting/CPA 以「系列级默认（组可覆盖）」形态挂进树模式（后端 `_parse_advanced` 消费链已就绪）；或明确下架并清理死分支 |
| S3 | **CBO↔组预算残留**：切 CBO 后组卡正确隐藏预算输入，但 `budget_usd/budget_type/lifetime_budget_usd/schedule_*` 残留值原样保存进 structure；切回 ABO 时复活——若残留是 lifetime 而无排期，保存时突然报「组X 总预算必须设置排期」，指向用户没填过的字段 | **P1** | FB：切 CBO 时组预算 UI 置灰并保留值，切回可见 | 切 CBO 时对组预算字段显示「（已由 CBO 接管，值保留）」或折叠可见；保存时 CBO 下忽略组预算字段 |
| S4 | **像素输入框出现在每张组卡里，实为全局模板值**：绑 `form.pixel_id`（:2085-2088），三张组卡三个像素框改的是同一个值；FB 的 promoted_object 像素是**组级**字段，后端 structure 也支持 `snode.pixel_id`（部署链 :2073 有取值），编辑器却不写它。hint（`treePixelHint`「模板级，所有广告组共用；逐组像素暂不支持」）算补救，但 UI 形态仍是误导 | **P1** | FB：pixel per ad set | 把像素移到系列段（与主页并列，明示全局）；或做成真正的组级字段（后端已支持） |
| S5 | 排除受众/自定义受众/相似受众完全缺失，且无任何说明（`build_targeting` v1 仅国家+兴趣，注释自知） | P1 | FB：audience 有 included/excluded/custom/lookalike | 至少在受众区加一行「当前版本仅支持 国家+年龄+性别+兴趣」 |
| S6 | **enabled 开关语义在编辑器不可发现**：组/广告卡头是裸 `el-switch`，无 label、无 tooltip；`treeEnable`/`treeEnableHint`（"整链开启才消耗；默认建出为暂停"）文案键已写好但**未挂到模板**（死键）。语义要到部署抽屉树概览/确认弹窗才首次解释 | P2 | FB：开关=开跑/暂停，语义自明 | switch 旁加 hover tooltip（文案现成）；组卡头加状态 chip「暂停/投放」 |
| S7 | 停用的 SavedAudience 在组卡下拉可选（仅加「· 停用」后缀），部署时 `_resolve_targeting` 要求 status=active 否则回落 → **静默回 US 默认**；平铺的 `audInactiveWarn` 警示在树组卡没有 | P2 | FB 会阻止或明示 | 组卡选中停用受众时显示与平铺同款警示条 |
| S8 | 优化目标覆盖下拉列全部 12 个 OPT_GOALS、不按 objective 过滤（TRAFFIC 组可选 VALUE/CONVERSATIONS）→ FB 400 风险；且组覆盖值与上方只读「转化位置」可能矛盾（组选 OFFSITE_CONVERSIONS，位置仍显示目标推荐值） | P2 | FB：Performance Goal 选项随目标/转化位置联动过滤 | 按 objective 过滤选项；覆盖了优化目标时转化位置行同步显示推断值 |
| S9 | billing_event 实际恒为 IMPRESSIONS（树模式不可编辑，节点/模板均空 → build_adset 默认），无任何说明；新版 FB 大多数场景也锁展示计费，属可接受简化但应说破 | P2 | FB：billing 基本固定 IMPRESSIONS | 组卡移除概念或加只读行「计费：展示（固定）」 |

组段判定：预算/排期/出价控制的呈现是全编辑器**最接近 FB 的部分**（覆盖+回退 hint、折叠+摘要都做了）；**受众是最大空洞**（S1/S2 连锁），像素错位（S4）。

---

## 三、广告段（Ad）

**字段清单（树广告节点）→ FB 对应层**：节点名 → Ad Name；IG 身份（全局输入框）→ Identity（⚠ 裸 ID 非 IG 账号选择器）；创意来源 新建/跟帖 → Use existing post（✓ 链路完整：ID/URL 识别→主页兜底→预览→权限预过滤账户）；多选素材→素材组展开（✓ 与部署口径一致）；标题/正文/描述/CTA/广告语言 → Primary Text/Headline/Description/CTA（✓）；落地页+URL+子码 → Destination（✓ 联动：选页填 URL、换页清子码、按页过滤子码）；消息模板（ENGAGEMENT）/Instant Form（LEADS）→ Messenger 欢迎语 / Lead Form（⚠ 见 A1/A2）。

| # | 问题 | 严重度 | FB 基准对照 | 建议（不动代码） |
|---|---|---|---|---|
| A1 | **消息模板绑定是死链**：节点可绑 Messenger 欢迎语模板（ENGAGEMENT），但部署侧 `is_messaging` 要求 `tpl.conversion_goal ∈ {conversations, messaging_purchase_conversion, messaging_appointment_conversion}`（launch_templates.py:2224-2226 / ad_ops.py:230-232）——前端 `CONV_GOALS.OUTCOME_ENGAGEMENT` 为空数组，conversion_goal 永远不可能等于这些值 → `welcome_message` 永不注入，选了模板等于摆设（连 AI 兜底欢迎语也被同一门挡掉） | **P1** | FB：消息目的地广告按模板设欢迎语 | `is_messaging` 判定改看 optimization_goal（节点可覆盖为 CONVERSATIONS）或 destination_type；或 UI 暂下架该区块 |
| A2 | **Instant Form 对 TT 隐藏，与后端自相矛盾**：`v-if="form.objective==='OUTCOME_LEADS' && !isTt"`（:2514）但同块注释写「FB/TT 双平台」、下拉按平台过滤（`formTemplatesForPlat`）、空态文案 `noFormsForPlat` 支持 {plat:TikTok}、后端 `_resolve_lead_form` 明确实现 `build_tt_lead_form_payload`（TT 表单模板按模板 id 建到广告主）→ TT LEADS 模板无法绑表单，只能走 AI 自动生成 | **P1** | TT Ads Manager：可绑 Instant Form | 去掉 `!isTt` 条件（三处准备都已就位）；若确要隐藏，删掉后端 TT 表单分支并改注释 |
| A3 | **手填文案被素材 AI 随机文案静默覆盖**：部署链 `_rh or anode.headline or tpl.headline`（:2201-2205），`pick_random_copy(asset)` 优先级**高于**节点手填标题/正文 → 用户精心写的文案部署时被随机 AI 变体顶掉，编辑器无任何提示 | **P1** | FB：手动输入优先；自动变体属于 Advantage+ creative 且需 opt-in | 优先级反转为 手填 > AI；或仅当 Advantage+ 创意开着才允许 AI 覆盖；至少在文案框 hint 注明「素材带 AI 文案时部署将随机替换」 |
| A4 | 完备度圆点（绿=有素材/跟帖、黄=只有文案、灰=全空）无图例、无 tooltip，规则只活在代码注释里 | P2 | — | 圆点加 title + 顶部一行图例 |
| A5 | 多素材节点展开后若填了节点名，每条广告同名（`if aname_base: ad_name=aname_base` 对每个素材都用，:2130-2133）；与批量模式「系列/广告名=素材名」的命名约定不一致，部署清单里难区分 | P2 | FB 允许重名但列表难用 | 节点名 + 素材名拼接（如 `名-素材`），或 hint 提醒 |
| A6 | 节点 CTA/广告语言空值显示「默认（用模板）」，但模板级 `cta_type/ad_language` 在树模式**无输入框**（平铺死分支里）→ 回退到的「默认」用户看不见也改不了（cta_type 只能用 OBJ 默认或旧值） | P2 | FB：默认值在创建流可见 | 系列段或节点处显示当前模板级默认值（卡片展示未填字段显默认值的项目惯例） |
| A7 | CTA 下拉 label 拼「（SHOP_NOW）」暴露技术枚举（i18n 已有中文名）；IG 身份是裸数字 ID 输入框，FB 是 IG 账号选择下拉 | P2 | FB：identity 选择器 | label 去掉枚举尾巴；IG 换成下拉（接口允许时）或保留输入但加格式说明（后端已校验纯数字） |

广告段判定：跟帖链路（识别/兜底/预览/截断提示）与落地页-子码联动是**完成度最高**的部分；创意文案链（A3）与目标绑定的两条死链（A1/A2）是硬伤。

---

## 四、部署抽屉 + 预检弹窗

**信息流实序**：副标题 → 主页权限总览（折叠懒加载）→ 树概览卡 → 部署模式（树模板隐藏批量，正确）→ 批量素材选择 → 跟帖/视频 hint → 账户搜索 → 全选/只选正常/清空/随机分配主页 → 像素策略 → 账户列表（勾选后展开 per-account 主页/像素）→ footer 合计预算 + 开始部署 → 确认弹窗。整体顺序合理（概览在前、配置在中、确认在后）。

| # | 问题 | 严重度 | FB 基准对照 | 建议（不动代码） |
|---|---|---|---|---|
| D1 | **树预检把 CBO+总额显示成日预算**：`_preflight_tree_fb` 的 `build_campaign` 不传 lifetime_budget、daily_budget 走日预算管道（:1010-1014）→ 预检 payload 展示 `daily_budget`，而真实部署发 `lifetime_budget`（:1966-1987）——预检与部署口径漂移，用户核对预算时看到错的字段 | **P1** | 预检=所见即所发 | 预检与 runner 同构传 lifetime；弹窗「预算与排期」行树模式补总额/排期段（`pfBudgetSegments` 顶层键树模式没填） |
| D2 | **树预检缺子码存在性校验**：`subcode_warn_slug` 只在平铺预检分支返回/渲染（:2902 在 `<template v-else>` 内），`_preflight_tree_fb` 返回体无此键 → 部署代码注释自称「无效 slug 静默丢追踪，预检已拦」（:2113），实际树模式**没拦**，无效子码照丢追踪 | **P1** | — | `_preflight_tree_fb` 汇总全树 subcode 校验；树预检弹窗补警示条 |
| D3 | 单模板（平铺/TT）确认弹窗只说「立即开始投放（产生花费）」**不带金额**；批量/树模式都有金额与规模 → 资金确认口径不齐 | P2 | FB 发布前摘要含预算 | 单模板确认文案加「合计 ≈ $X/天（每账户 $Y）」（footer 已算好，复用即可） |
| D4 | 像素策略切回「跟随模板」不重置已随机填入的 per-account 像素（改 A 没改 B）；「随机」即时生效 vs「新建」延迟到确认后，两种时机不一致（有 psCreateHint 解释，勉强） | P2 | — | 切回 template 时把空模板值恢复为默认项；或三种策略统一「选择→点应用」 |
| D5 | 预检入口自动挑「第一个正常账户」，用户不可选；预检弹窗也不显示用的是哪个账户（只能从币种反推） | P2 | — | 预检弹窗头部显示 `账户名 (act_id)` |
| D6 | TT 模板若历史数据带 structure，部署抽屉仍渲染树概览卡（`openDeploy` 不分平台解析 structure），点了开始部署才被后端 400「结构模式暂不支持 TikTok」——前端先误导 | P2 | — | openDeploy 解析 structure 前加平台判断 |

**两口径（立即消耗/全暂停）醒目度**：树概览卡「启用链路 N（warn 色）/全部建为暂停」+ 确认弹窗文案分叉 + 预检 will_spend 横幅，三处一致、口径同源（`chains` 与后端 `will_spend` 同算法定义）——这块做得好；扣分项仅在 D3 的金额缺失。

---

## 五、全局（保存校验 / 回显 / TT 隔离 / 交互）

| # | 问题 | 严重度 | 说明与建议 |
|---|---|---|---|
| G1 | **保存校验错误不可定位**：错误只出现在 ①toast 文本列表（`pendingMissing`）②顶栏 chip 计数（完整列表仅在 hover title）。不滚动、不高亮出错字段、不自动展开被折叠的段/组卡——三段手风琴+组卡双层折叠下，出错字段大概率不在视口 | **P1** | 保存失败时展开并滚动到第一个出错对象（段级）；错误文案按「段名 · 字段」组织（树校验已有组名，方向对） |
| G2 | **回显/保存的数据丢失与双口径**：① 自定义归因组合（非 4 预设）打开显示「默认」，且保存时 `adv.attribution_spec` 被 delete（:1442-1445）→ 数据丢失；② CPA 性能目标（`adv.bid_amount`=美分整数）与 `bid_amount_usd` 两条管道同写 FB `bid_amount`：树部署先按账户本币换算 `s_bid_fb`，随后 `merged_adv` 深合并用 `adv.bid_amount`（=cpa×100 美分）**覆盖**换算值 → USD 账户凑巧对、**非 USD 账户出价额金额错**（500=500 本币单位 ≈ 错一个汇率量级）；③ 树保存时模板级 `message_template` 原始 JSON 不随节点更新，部署回退时可能用旧文案 | **P1** | ②资金相关最优先：CPA 与 bid_amount_usd 单一来源化，adv.bid_amount 统一走本币换算管道；①自定义归因保留原文或显示「自定义（已保留）」；③树模式禁用模板级 message_template 回退 |
| G3 | 面包屑纯展示不可点（`gotoCampaign/gotoAdSet/gotoAd` 文案键已存在但未用）；三段折叠无记忆（每次打开全展）；树模式段→组卡→广告卡三层嵌套在 680px 抽屉里滚动极长，无锚点 | P2 | 面包屑做成锚点跳转（文案键现成）；折叠状态记忆到模板或会话 |
| G4 | 顶栏「待完善 N」完整清单仅 hover title 可见，移动端/触屏不可达 | P2 | 点击 chip 弹出清单 popover |
| G5 | **TT 分支隔离总体干净**（平台只读 chip、目标下拉替换 picker、表单模板按平台过滤、像素走 TT 库、后端 400 拦 TT structure）——遗留仅 D6（抽屉树卡）与 A2（Instant Form 矛盾）两处 | — | 见 D6/A2 |
| G6 | 死文案键/死代码清单（清理项）：`treeEnable/treeEnableHint`、`gotoCampaign/gotoAdSet/gotoAd`、`onModeSwitch/flatFromTree/_synthTreeFromFlat`(仅跟帖预填用)、平铺 FB 组段/广告段整块、`tplMode/modeFlat/modeTree` | P2 | 随 S2 的能力回迁一并处置，避免下轮审计再当活代码读 |

**回显完整性正面确认**：dirty 快照含 form+mode+tree（关抽屉确认不丢）；Advantage+ 创意/频次/归因/Dayparting 从 advanced_config 反解；树模板子码/跟帖预览预拉；表单/消息模板选中态恢复；landing_page_id 的 0/null 归一处理——除 G2 三点外回显质量较高。

---

## 六、逻辑断层专项汇总（「改了 A 没改 B」）

| 断层 | 改的 A | 没跟的 B | 后果 | 编号 |
|---|---|---|---|---|
| 目标切换 | objective | optimization_goal/conversion_goal 按新目标白名单重置 | 非法 optimization_goal 直达 FB payload → 400；conversion_goal 残留显示裸值 | C4 |
| 预算模式切换 | budget_mode=CBO | 组预算/budget_type/lifetime+排期清理 | 残留值保存；切回 ABO 复活并触发用户没填过的校验报错 | S3 |
| CBO+总额 | budget_type=lifetime（树模式） | 模板级排期（无处可填） | 可存不可部署，守卫死循环 | C1 |
| 目标切换（反向） | objective 从 LEADS/ENGAGEMENT 切走 | 节点 lead_form/message 模板绑定 | UI 隐藏不可清除，脏数据残留（部署侧目标门挡住，无害但误导回显） | C7 |
| 选素材（带 AI 文案） | asset | 节点手填 headline/body | 部署时 AI 随机文案优先覆盖手填 | A3 |
| 绑消息模板 | message_template_id | conversion_goal（is_messaging 门） | 欢迎语永不生效 | A1 |
| 设 CPA 性能目标 | performance_goal_cpa | adv.bid_amount 与 bid_amount_usd 同字段双写 | 非 USD 账户出价额错量级 | G2② |
| 预检 | 模板 lifetime/子码 | 预检 payload 同构 | 预检显示与真实部署不一致/漏拦 | D1/D2 |
| 像素策略切回 | pixelStrategy=template | per-account 已随机填入值 | 表面跟随模板实际仍是随机值 | D4 |
| TT 历史带 structure | — | 抽屉树卡仍渲染 | 前端展示与后端 400 矛盾 | D6 |

---

## 七、TOP 10 修复优先级

1. **S1 树模式受众路径缺失 + 静默 US 兜底**（P0）：组卡补内联受众（国家最少集）或系列级受众区；先把 `audienceSourceHint`/`treeAudienceDefault` 文案改真（"不选=投美国"）。
2. **C1 CBO+总额树模式死路**（P0）：CBO 下隐藏「总额」或补模板级排期输入；守卫报错改可行动文案。
3. **G2② 出价额双口径非 USD 错额**（P1，资金安全）：CPA 与 bid_amount_usd 单一来源，adv.bid_amount 走本币换算管道。
4. **C2 转化目标摆设**（P1）：接通 conversion_goal→custom_event_type，或 UI 明示「转化事件固定 Purchase/Lead」。
5. **A3 AI 随机文案覆盖手填**（P1）：优先级反转为 手填 > AI（或仅 Advantage+ 创意开时随机）。
6. **A1 消息模板死链**（P1）：is_messaging 改看 optimization_goal/destination，或下架 ENGAGEMENT 消息区块。
7. **C4 目标切换残留**（P1）：换目标时按白名单重置 optimization/conversion goal，保存前再过滤一道。
8. **D2 树预检补子码校验 + D1 lifetime 口径对齐**（P1）：预检与 runner 同构。
9. **A2 TT Instant Form 矛盾**（P1）：放开 `!isTt`（后端已支持）或后端下架 TT 表单分支。
10. **G1 校验错误可定位 + S2 死代码/能力回迁**（P1/P0）：保存失败展开滚动到出错段；平铺 FB 组段的版位/频次/归因/Dayparting/CPA 以系列级默认形态回迁树模式。

---

## 八、统计

| 段 | P0 | P1 | P2 | 小计 |
|---|---|---|---|---|
| 系列段 | 1 | 3 | 3 | 7 |
| 组段 | 2 | 3 | 4 | 9 |
| 广告段 | 0 | 3 | 4 | 7 |
| 部署抽屉/预检 | 0 | 2 | 4 | 6 |
| 全局 | 0 | 2 | 2 | 4 |
| **合计** | **3** | **13** | **17** | **33** |

（S2 与 S1 有因果耦合、G6 为清理项计入 P2；断层专项表为交叉引用，不重复计数。）
