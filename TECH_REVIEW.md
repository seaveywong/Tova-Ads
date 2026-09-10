# 技术变更复审文档

> 每次大改完按此格式更新。技术专家复审用。
> 格式 = 概述 + 按commit/功能的变更表(含文件+验证状态) + DB迁移 + 生产环境变更(非代码) + 复审结论(已知限制/风险) + commit列表 + 关联memory。

---

## 2026-09-08 — 批次 III：P2/清理与低频补齐（细分版位/redirect fire 像素/TT event_id/last-wins/死块清理/spend_cap 汇率统一）

### 概述
《总方案_v2_FB对齐》批次 III 全 7 项 + 总方案批III清单中的 spend_cap 汇率兜底统一（后端 4 文件 + 前端 2 文件，零迁移）。服务器备份 /opt/toveads/backups/batchIII_0908/（4 后端文件）。**已上传服务器+双门过+全量 smoke，未 restart（用户统一部署）**。另交付真投放实测脚本 `_smoke_real_deploy_batch_i.py`（不自动跑，用户授权后手动执行）。

### 变更表
| 项 | 文件 | 变更 | 验证 |
|---|---|---|---|
| 1 细分版位 | `ad_builder.py` + `launch_templates.py` + `LaunchTemplates.vue` + `launch.js` | ①组卡版位手动模式加二级勾选（facebook_positions/instagram_positions/messenger_positions；枚举=FB v25.0 官方 targeting-spec 白名单，前端 PLATFORMS.positions 镜像 backend `_PLACEMENT_POSITIONS`；audience_network 可勾平台但无细分层=该平台全位置）②后端 `_validate_structure` 白名单+校验：非法值 422 带可用清单/位置给了但平台未勾=矛盾组合拒绝/auto 清残留/去重；空数组=省略=该平台全部位置（FB 官方语义）③`_node_placements` 透传（平台勾了才带键）④build_adset 位置进 targeting（extra 深合并前）⑤树预检 tree 概览+adset payload 样例透出 | smoke 11 断言（白名单/422/auto 清残留/node_placements/build_adset 两形态/树预检两处透出/will_spend）全过 |
| 2 redirect fire 像素（B11） | `landing.py` | ①LP_CONFIG 增 pixel_ids/tt_pixel_ids/conversion_events/tt_conversion_events（页配置级）②redirect 分支改「跳转桥页」：200 HTML fire FB PageView+转化事件 / TT page+tt 转化事件（同口径）→ 300ms location.replace（像素加载不阻塞跳转）+ meta refresh 兜底 + 可见 Continue 链接；redirect 事件 beacon 照旧（waitUntil 不阻塞）；query 合并逻辑不变 | node 实跑 worker 桥页 6 断言（200 HTML/FB 像素+PageView+Purchase/TT 像素+CompletePayment/replace+refresh+cta/utm 合并/node --check）+ display 模式回归（仍 302 /?_d=） |
| 3 TT event_id（B8 收口） | `landing.py` | 默认页模板 trackConversion 的 TT 分支 `ttq.track(evt, {event_id:_eid})`（与 FB 分支同 _eid；原无 id 的那次 fire 是重复计数来源——_d_decode_tt 的点击 fire 已带 id，模板函数未带） | smoke：模板串断言 + _d_decode_tt/worker eid 契约回归 + route_next 同一 UUID 进 TT S2S 与 FB CAPI（monkeypatch 捕获实测） |
| 4 link.ad_id last-wins（B7 收口） | `ad_ops.py` + `launch_templates.py` | 新 `bind_link_ad_id(link, ad_id)` 守卫：已绑不同 ad_id → 跳过不覆盖（返 False）+树 runner write_log skip 留痕 / 平铺+TT 链 logging.warning；同 ad_id 重绑（重试/重部署）照常。四个部署回绑点（FB 平铺/TT/树手动 slug/树自动建链）全收口；ingest 首绑路径本就不覆盖（回归断言补证） | smoke 7 断言（首绑/同 id 重绑/异 id 拒绝/None 安全/守卫存在/源码无绕过直写/ingest 并发回归） |
| 5 平铺卡尾死块清理 | `LaunchTemplates.vue` + `launch.js` | 平铺卡 FB-only 尾块整删（披露[已在组卡]/频次/归因/Dayparting/高级 JSON[纯死]）——FB 恒树模式这些块不可达；频次/归因/Dayparting 迁组卡新「高级」折叠区（默认收起，摘要 chip 显示已配值），绑节点 advanced_config（UI 态 advx_*，保存序列化/加载反解，未知键保留）；openEdit 旧模板模板级配置一次性迁入首组节点；保存流模板级一律剥 frequency_control_specs/attribution_spec/day_parting_schedule/pacing_type 残留键（节点级才是生效层，部署浅合并 `{**tpl_adv,**adv_node}` 节点覆盖模板） | build ✓；i18n zh/en 566/566 对称（新增 12 组删 6 组死键）；vue 引用 536 键全命中 |
| 6 跟帖克隆值落树节点 | `LaunchTemplates.vue` | `applyClonedSettings`：树模式受众（国家/年龄/性别/兴趣）写首组节点内联编辑态（aud+清受众库引用）、版位写首组节点（placement_mode/publisher_platforms/device_platforms/facebook_positions 白名单过滤+平台勾选对齐）；模板级目标/出价策略仍写 form；平铺（TT）路径不变 | build ✓（FB 恒树模式下克隆受众/版位不再只进 form 静默丢） |
| 7 真投放实测准备 | `_smoke_real_deploy_batch_i.py`（新，不自动跑） | 建 1 棵最小树（2 组×1 广告：组1 SALES+website+落地页自动建链+细分版位 feed、组2 SALES+messenger）→ 预检断言（矩阵派生/版位/全 PAUSED will_spend=[]/自动建链节点数）→ 真部署到 --act 指定账户 → FB 回读断言（campaign objective+ACTIVE/adsets 2 条 WEBSITE+MESSENGER+promoted_object+facebook_positions/ads 2 条全 PAUSED 零消耗/自动建链广告名 [子码: 标注/creative 链接 /a/{slug}?ad= 与 {{ad.id}} 宏）→ 子码回绑+ads_cache 归因对账 → 全链留痕报告。头注释写明用法/预算（默认 $2/组/日=两组合计 $4/日，全 PAUSED 手动激活才花钱） | py_compile ✓（真跑待用户授权，跑前需批次 III 已 restart） |
| 8 spend_cap 预检汇率统一（总方案批III清单） | `launch_templates.py` | 平铺/树预检的 spend_cap/lifetime/bid 样例换算从内联 `cr.rate if cr else 1.0`（静默 1.0 兜底）统一走 `_usd_to_account_minor`（缺汇率 ValueError→400，与部署管道同口径）；预算路径本就先 raise，此改消除旁路静默换算 | 双门 ✓ + 全量回归（batchI/II/tree/G） |

### DB 迁移
- 无（纯代码批次；细分版位存进既有 structure JSON，conv_location 空=存量行为不变）。

### 生产环境变更
- **代码已上传**（4 后端文件 + 2 smoke 脚本），py_compile+import 双门 ✓，**服务未 restart**（生产仍跑批次I内存代码，磁盘为批次II+III——用户统一部署 restart 即生效）。备份 /opt/toveads/backups/batchIII_0908/。
- 验证方式：8011 临时 uvicorn（新代码）+ in-process 混合跑：批次III 31/31 + 批次I 54 + 批次II 32 + 树 29 + 批G 26 回归全 PASS；smoke 测试行零残留（templates/links/pixels/pages 全 0）；8011 已关；前端 build ✓ 未部署 CF。
- **注意**：landing.py 的 LP_CONFIG 变更（redirect 桥页）对**已发布页不自动生效**——worker 在发布时固化进 CF Pages，存量 redirect 页需重发（PUT 重发布）才拿到像素桥页；新发布页即时生效。

### 复审结论（已知限制/风险）
- **messenger_home 不在 FB v25.0 官方文档枚举**（官方现列 sponsored_messages/story）但保留在白名单（1.0 生产验证值 + Ads Manager 仍展示 Inbox）——若 FB 拒绝，部署报 invalid targeting 快失败可定位；真投放实测覆盖此点。
- redirect 桥页语义变化：/a/{slug} 在 redirect 模式由裸 302 变 200 HTML（像素加载 300ms 窗口）——对用户感知为极短过渡页；无 JS 爬虫走 meta refresh 3s；防护/频次/防重链路不变。存量 redirect 页不重发=维持旧行为（不 fire 像素），见上。
- TT event_id 只覆盖 _d 路径（route_next 已调）的点击转化；直访落地页（无 _d）无 S2S 配对、无需去重（维持现状）。
- 树节点 advanced_config 仍是自由 JSON 容器：高级折叠区只管频次/归因/Dayparting 三键，其余键（如手改过的 targeting 残留）原样保留原样下发——高级 JSON 输入框删除后无 UI 编辑入口（API 仍可写）。
- 跟帖克隆受众写「首组节点」：树为空（TT/异常态）回退 form 写入（旧行为）。
- `_smoke_real_deploy_batch_i.py` 组2（SALES+messenger）会真调 FB 建 campaign/adset/ad+creative（全 PAUSED 零消耗）；跑之前确认批次 III 已 restart（脚本走 8000）。

### commit
- （见本 commit）批次III：清理与低频补齐——细分版位+redirect fire 像素+TT event_id+last-wins 守卫+死块迁组卡+真投放实测脚本（已 push）

关联：[[tree-launch-templates]] [[bare-except-silent-failure]] [[tech-review-format]] [[landing-pixel-pipeline]] [[toveads-pause-state-2026-09]]

---


## 2026-09-08 — 批次 II：P1 资金与断层（出价双管道/AI文案/URL跟随/TT像素/错误定位）

### 概述
《总方案_v2_FB对齐》批次 II 全 7 项（后端 4 文件 + 前端 2 文件，零迁移）。两个 commit（35996ba + 8a4e8c7），回退点 = 93bb6e0（批次I前端补漏）+ 服务器备份 /opt/toveads/backups/batchII_0908/（4 后端文件）。**已上传服务器+双门过，未 restart（用户统一部署）**。

### 变更表
| 项 | 文件 | 变更 | 验证 |
|---|---|---|---|
| 1 出价双管道（G2②，资金） | `ad_ops.py` + `launch_templates.py` | adv.bid_amount（旧 CPA 性能目标=美分原始值）深合并覆盖 bid_amount_usd 本币换算值（非 USD 账户错一个汇率量级）。保守修法=模板出价控制非空时剥离：`_strip_adv_bid()`（浅拷贝不动共享 dict）用于树 runner merged_adv/平铺预检/树预检三处 + deploy_one_account 内联剥离（平铺/批量/重试三链单点）；两者都空维持旧行为（adv 直通）；树预检补 bid_amount 形参使其与 runner 同构 | smoke：未剥离基线复现覆盖行为 + 剥离后换算值生效 + fake-Fb 端到端 adsets payload 断言 + 调用方 dict 未篡改 |
| 2 AI 文案不覆盖手填（A3） | `ad_ops.py` + `launch_templates.py` | 新 `pick_ad_copy(asset, manual, fallback)` 统一优先级 手填>素材AI随机>模板兜底；树节点/平铺/重试/TT 四链全部改用（旧序 AI>手填 静默顶掉用户文案）；TT 链 pick_random_copy 死 import 清理 | smoke 4 断言（手填胜/空白AI填/无AI兜底/半填混合） |
| 3 落地 URL 跟随（B9/B5） | `launch_templates.py` + `landing.py` + `ad_ops.py` | ①树 runner：绑落地页节点一律从页行实时解析 base（原仅自动建链分支解析），`_lp_url` 被页行 base 覆盖（快照仅作占位符容器）；平铺/重试链同口径（manual slug/降级场景也跟随）；平铺+树预检同口径跟随（预检=所见即所发）②`_page_to_dict` public_url 回退链 custom_domain>bound_subdomains[0]>pages.dev（无自定义域页回填不再空串）③禁 tovaads.com 死链兜底：deploy_one_account/树 runner 手选 slug 无 base 时 FbApiError 快失败（文案指明补救） | smoke：public_url 三级回退 + resolve base pages.dev + 树预检 creative URL=页行 base 且不含快照 + 死链 raise 且 payload 无 tovaads.com/a/ |
| 4 TT 三级像素（方案 B6） | `landing_events.py` | 新 `_resolve_tt_pixel_ids(db, page, link, ad_id, explicit_act)`：候选账户（ads_cache 反查 ad 所在 act > ?act= > link.act_id）的 platform='tt' active 像素 > 页级 tt_pixel_ids（对齐 FB 三级分流；TT 无 adset pixel 层——绑的是 code 非 FB 数字 id）；route_next 接线替换原页级-only 块 | smoke 5 断言（显式/反查/link/页级回退/fb 像素不串台）；**补丁 commit 修 _json 局部导入 NameError 被裸 except 吞（smoke 实测抓出，铁律再实证）** |
| 5 保存错误定位（G1） | `LaunchTemplates.vue` | validateTree/validateTemplate 结构化（`{msg, sec, key}`：sec=三段手风琴、key=组/广告卡）；树广告级错误补节点名（treeErrReuseRef/ReuseMulti/AssetsMax 三键 zh/en 加 {name}）；保存失败=组卡/广告卡红边(.err)+展开段与双层折叠卡+滚动到首个出错对象；后端 422 文案按「节点名」回锚（_anchorBackendSaveErrs）；编辑器重开/保存成功清锚 | build ✓（i18n 扫描 zh/en 2874=2874 对称，无新增问题项） |
| 6 TT Instant Form 门（盘点 A2） | `LaunchTemplates.vue` | 去掉 `!isTt` 门（后端 _resolve_lead_form TT 分支现成）；新增 formTplPlatScope 平台范围标注（平铺+树节点两处下拉） | build ✓；**未尽：TT 部署链（deploy_one_account_tt）尚未消费 lead_form（creative 无表单挂点）——见结论** |
| 7 og 残留兜底（C4 后端侧） | `launch_templates.py` | TemplateIn 模型级：模板级 optimization_goal 非空且不在 OPT_GOALS_BY_OBJECTIVE[objective] → ValueError 422 带可用清单；置于 structure 早退之前（平铺模式也覆盖；组级校验已有，防回归断言保留） | smoke 4 断言（TRAFFIC+VALUE 拒+清单/合法过/组级防回归） |

### DB 迁移
- 无（纯代码批次）。

### 生产环境变更
- **代码已上传**（4 后端文件 + `_smoke_batch_ii.py`），py_compile+import 双门 ✓，**服务未 restart**（生产仍跑批次I代码，磁盘为批次II——用户统一部署时 restart 即生效）。备份 /opt/toveads/backups/batchII_0908/（4 文件）。
- 验证方式：8011 端口临时起第二 uvicorn 实例（新代码）跑全套 smoke 后已关：批次II 32/32 + 批次I 回归 + 树 29 回归 + 批G 26 回归全 PASS；smoke 测试行零残留（pages/pixels/ads_cache/templates/links 全 0）；前端 build ✓ 未部署 CF。

### 复审结论（已知限制/风险）
- 出价双管道保守口径：仅模板出价控制（bid_amount_usd）非空时剥离 adv.bid_amount；只填 CPA（前端写美分进 adv.bid_amount）+无 bid_amount_usd 的存量组合维持旧行为——USD 账户正确、非 USD 账户仍是美分直通（单管道化留给后续批，需前端 CPA 也走 USD 输入）。
- URL 跟随的降级语义：页行已删/解析失败 → 回落 landing_url 快照（最后手段）；手选 slug+无任何 URL → 该广告 fail 留痕（不再静默死链）。
- TT Instant Form：UI 门已开但 TT 部署链未消费 lead_form_template_id（deploy_one_account_tt 无表单参数，build_tt_creative 无挂点）——TT 真链路消费待 TT sandbox 实测批；_resolve_lead_form TT 分支可直调已验证（批次I smoke）。
- 保存错误定位的 422 回锚按「节点名」精确匹配（后端文案含名字），无名字的模板级 422 只 toast 不锚（行为同旧）。
- 批次III 遗留（本批未动）：平铺组段死代码/细分版位/redirect fire 像素/TT event_id/link.ad_id last-wins/spend_cap 汇率兜底。

### commit
- `35996ba` 批次II：P1 资金与断层——出价双管道剥离+AI文案手填优先+落地URL跟随+TT三级像素+保存错误定位（已 push）
- `8a4e8c7` 批次II补丁：_resolve_tt_pixel 命中 NameError 被裸 except 吞掉（_json 模块级化）（已 push）

关联：[[tree-launch-templates]] [[bare-except-silent-failure]] [[tech-review-format]] [[landing-pixel-pipeline]] [[toveads-pause-state-2026-09]]

---


## 2026-09-08 — 批次 I 后端：FB 广告管理器 1:1 对齐（转化位置矩阵/版位/WhatsApp/自动建链）

### 概述
《总方案_v2_FB对齐》批次 I 后端部分（前端下一批）。一个 commit（bd57b79），回退点 = 9efdba6（批次0）+ 服务器备份 /opt/toveads/backups/batchI_09080813/。用户已批：转化位置全开（含 WhatsApp/电话/IG 私信/Leads 组合位）、自动建链=每广告。
核心：**一套「转化位置→成效目标」矩阵**（ad_builder）替换三套互不相交的旧词表（_OPT_GOAL_MAP 目的地语义 key / UI custom_event_type 词表 / is_messaging 门），conv_location 空 = 存量行为逐字不变（零迁移兼容）。

### 变更表
| 文件 | 变更 | 验证 |
|---|---|---|
| `backend/app/core/ad_builder.py` | ①新映射族：`CONV_LOCATIONS_BY_OBJECTIVE`（按 objective 合法转化位置，蓝图 §2.1）+ `_CONV_MATRIX`（21 行 (obj,loc)→(destination_type, 默认成效目标, promoted_object 形态)，蓝图 §5.2 CTM/CTW 实证）+ `OPT_GOALS_BY_OBJECTIVE`/`OPT_GOALS_BY_LOCATION`（成效目标兼容校验表）+ `_LEGACY_DEST`（conv_location 空的存量推导，含消息类覆盖组合补全）+ `_CUSTOM_EVENT_MAP`（UI 词表→custom_event_type）；②`custom_event_from_goal()`：conversion_goal（AddToCart/add_to_cart/ADD_TO_CART 统一）真实进 promoted_object.custom_event_type（修恒 PURCHASE/LEAD，盘点 C2）；③`resolve_adset_destination()`+`is_messaging_destination()`：门统一按派生目的地判定（修 A1 死链——组覆盖 CONVERSATIONS 现在也开欢迎语门）；④build_adset 新参 conv_location/placements/whatsapp_phone_number：矩阵派生 destination/promoted_object（CTW 号码仅 ENGAGEMENT 进 promoted_object）；**修 bugA**：destination_type_override 仅 conv_location 空时生效；**修 bugB**：SALES 任何成效目标必带 promoted_object（消息类兜底 page_id，缺则 ValueError）+消息类目的地兜底；版位进 targeting（extra 深合并前）；MESSENGER 版位并入去重（不再整体覆盖）；⑤`build_wa_welcome_message()`（VISUAL_EDITOR autofill_message 预填形态）+ `parse_message_template(channel=)` 分流；⑥build_creative 新参 app_destination：消息类目的地且未显式选 CTA → WHATSAPP_MESSAGE/MESSAGE_PAGE + value.app_destination | 本机功能断言 24 项全过 + 服务器 smoke |
| `backend/app/core/ad_ops.py` | deploy_one_account 新参 conv_location/whatsapp_phone_number/placements 透传 build_adset；is_messaging 改 resolve_adset_destination 派生（删旧 conversion_goal 词表门）；WA/CTM 欢迎语 channel 分流；消息类 CTA app_destination | py_compile ✓ 双门 ✓ |
| `backend/app/routers/launch_templates.py` | ①`_validate_structure`：组节点白名单+规范化 +conv_location/placement_mode/publisher_platforms/device_platforms（枚举/子集/manual 需非空平台/auto 清残留勾选）；②TemplateIn：whatsapp_phone_number（E.164 宽松校验）+ model_validator 按矩阵校验 conv_location×objective、optimization_goal×objective、交叉兼容（非法 422，审计 S8/C4 门）；③`_budget_guard_400`：lifetime 无模板级排期时接受「任一启用组带完整排期」（树排期随组下发，修审计 C1 可存不可部署死路）；④自动建链族：`_auto_slug_base`（lt{模板id}-{节点key}-{素材id|s}-{账户尾4}，[A-Za-z0-9_-] ≤44）+ `_create_auto_subcode`（reserved LandingAdLink，碰撞 -N 后缀，语义位耗尽退随机 6 位）+ `_flat_auto_subcode`（平铺/批量/重试共用）+ `_auto_landing_gate`（deploy/preflight 前提门：页已发布+display 模式，redirect 建链无意义 B11）；⑤树 runner：组级派生 grp_dest/grp_opt → build_adset 接线 + 消息门 + WA 分流（`mt.type` 消费）+ CTA app_destination；每展开广告自动建链（base=页行解析不信快照 B5）+回绑 active+广告名[子码:]标注+失败降级直投且 item error/action_log 留痕；树 slug 查询过滤 reserved/active（B4）；`LaunchJobItem.subcode_slug` 激活（B10）；⑥树预检：payload 样例带 conv_location/placements/whatsapp + tree 概览带版位/转化位置 + `auto_subcode_nodes` 计数；平铺预检 `auto_subcode` 标志 | 服务器 smoke 54 断言 + 树/batchG 回归全过 |
| `backend/app/models/launch_template.py` | LaunchTemplate + whatsapp_phone_number Text 列 | py_compile ✓ |
| `backend/alembic/versions/0092_launch_tpl_whatsapp_number.py` | 迁移 0092：列 + GRANT toveads_app/toveads_super | 服务器已跑：COL ✓ VER=0092 ✓ GRANTS ✓✓ |
| `_smoke_batch_i.py` | 批次I smoke：词表归一（AddToCart→ADD_TO_CART/旧 key 兼容/空→默认）、conv_location 4 类 422、版位 auto/manual payload、WhatsApp promoted_object（ENGAGEMENT 带号码/TRAFFIC 不带）、Leads 组合位、CBO+lifetime 组排期守卫、自动建链建/查/碰撞/门/降级/清理、bugA/B 回归、0088 树 smoke 回归 | **54/54 PASS**（服务器生产实测） |

### 新映射表摘要（矩阵要点）
- **合法转化位置**：SALES=website/messenger/whatsapp/phone_call；LEADS=+on_ad/on_ad_messenger（组合位→ON_AD+LEAD_GENERATION，分流在 FB 投放侧）/instagram_direct；TRAFFIC=website/messenger/whatsapp/instagram_direct/phone_call；ENGAGEMENT=website/on_page/messenger/whatsapp/instagram_direct；AWARENESS/APP_PROMOTION=无（后者链路未建，C3）。
- **派生链示例**：SALES+website→WEBSITE/OFFSITE_CONVERSIONS/pixel+事件；SALES+messenger→MESSENGER/MESSAGING_PURCHASE_CONVERSION/page；ENGAGEMENT+whatsapp→WHATSAPP/CONVERSATIONS/page(ENGAGEMENT 才带显式号码)；LEADS+on_ad→ON_AD/LEAD_GENERATION/page；TRAFFIC+website→WEBSITE/LINK_CLICKS/无。
- **❓未实测**（蓝图无逐格矩阵，真投放校准）：phone_call/instagram_direct 的成效目标组合、WA autofill_message 键名、组合位创意层挂法。

### DB 迁移
- 0092：launch_templates.whatsapp_phone_number（Text，空=不传）。GRANT 两角色 ✓。存量 structure JSON 零迁移（conv_location 空=现状）。

### 生产环境变更
- 服务器已执行（为跑 smoke 的验证部署，非最终上线）：备份 4 文件 → 上传 5 文件 → py_compile+import 双门 ✓ → alembic 0092 ✓ → restart+health ✓（v1.3.5 active）→ smoke batchI 54/54 + batchG 回归 + 0088 树回归全过 → smoke 数据零残留（lp/link/active-tpl=0/0/0）。无 .env/FB 侧/数据操作。

### 复审结论（已知限制/风险）
- conv_location/版位/whatsapp 号码的 UI 还没有（前端下一批）——后端字段就绪，存量行为不变；optimization_goal 兼容门是新校验：存量模板若存过非法组合（旧 UI 全集下拉可存），下次保存会 422（消息里带可用清单，属预期门）。
- 自动建链降级语义：建链失败（DB/碰撞耗尽）→ 广告照建、裸 URL 直投、item error+action_log 留痕（error_code=auto_subcode_degraded）；未发布/redirect 页在 deploy/preflight 提交即 400 不进 job。
- WhatsApp 欢迎语 text_format/autofill_message 键名、phone_call/IG 私信成效目标组合未经真金白银验证——批次 I 完成后的真投放实测（用户授权花钱）覆盖：{{ad.id}} 宏替换/转化位置/promoted_object/版位/自动建链/像素 fire 全链。
- 树模式自动建链对「组停用/广告停用」无差别建链（链接建了广告 PAUSED 也回绑 active）——广告 PAUSED 时 slug 已 active 归属该广告，语义正确；孤儿 reserved 由既有 14d 清理回收。
- TT 部署链未动（TT 模板恒平铺，自动建链仅 FB）。

### commit
- `bd57b79` 批次I后端：FB 对齐核心——转化位置矩阵统一三套词表+conv_location/版位组节点字段+WhatsApp真链路+每广告自动建链（已 push GitHub）

关联：[[tree-launch-templates]] [[bare-except-silent-failure]] [[tech-review-format]] [[toveads-pause-state-2026-09]]

---

## 2026-09-04 — 落地页整套集成验证（拖欠项 #25/#187 关闭）+ app 域上线 + 官网备用

### 概述
用户 /goal「打磨完善，不改功能可回退」。三件事：①app.tovaads.com 管理界面上线（CORS+Pages 域）②官网建好停临时域（FB 审核后绑定，暂缓决策）③落地页 E2E 13/13 全通（产品代码零改动，纯验证+清理）。

### 落地页 E2E 结论（13/13 ✅，生产实测）
建页→CF发布(21s)→DB落库(FB+TT双像素)→可达(预览令牌200+双像素注入)→防护拦截(302→block_target 按设计)→子码生成+router/next(目标+子码级像素)→防护6画像(拦2/6)→自检矩阵(9/10 pass)→落地日志(入库+归因)→编辑重发布(18.5s)→预览模式(开关+令牌)→归档→清理。

**三个假警报（查明均非产品 bug，是测试方法问题）**：
1. SSL handshake failure = 每部署子域证书签发时序（部署后秒级探测）
2. HTTP 404 = **防护正确拦截**——机房 IP 国家不在白名单 → 302 → block_target(example.com/blocked 404)
3. 预览 404 = preview_enabled 未开（按设计令牌失效）

### 清理（顺手修复的存量问题）
- 5 个孤儿 CF 项目 tovaads-landing-11~15（历史 E2E 残留）+ 4 条 lp12-15.marketbriefnow.xyz DNS 记录
- DB 垃圾页 #7（ZZZ-AUDIT-TEST）/ #10（_verify187 残留）+ 测试子码 3 条 + 测试事件 8 条
- 最终状态：仅产品页 #6(RH-Signals, published) + 归档测试页 #15

### app.tovaads.com 上线（零影响验证过）
Pages 项目 tovaads 加自定义域+CNAME；后端 CORS 加新域（commit 前文）。FB 三登记 URL（回调=api 域/App Domains/隐私政策）零改动。官网已建好停 tovaads-site.pages.dev 待 FB 审核全过后绑定（决策存档 memory domain-architecture-decisions）。

---

## 2026-09-03（二）— 两轮复审：断层与假实现清剿

### 概述
用户 /goal「复审2次看最近修改有没有断层和功能没真正实现的」。R1=原作者沿调用链+生产实测；R2=独立 Agent 新鲜视角扫前后端一致性。共发现 **1 P1 + 9 P2，全部修复**。commit `f0f22c2`(R1)+`39134f7`(R2)。

### R1 发现（自审+实测未覆盖路径）
| # | 问题 | 修复 | 验证 |
|---|---|---|---|
| 1 | enable 端点邮箱专用令牌 403(10000)——「启用」按钮对新域名必挂 | enable 走主令牌客户端（幂等实测） | PASS |
| 2 | zid 缓存读取无清洗（历史脏值就是带引号进的缓存） | `_clean_token` 包裹 | 代码级 |
| 3 | 缓存 miss 时仅邮箱令牌查 zone（缺 Zone:Read 直接 400，主令牌有权限却不兜底） | 主令牌兜底查+缓存 | 代码级 |
| 4 | toggle 响应缺 cf_enabled | 补齐 | 代码级 |
| ✅ | apex("@) DNS 写 / 映射建-停-启-删全生命周期 | — | 实测全 PASS |

### R2 发现（独立 Agent）
| # | 级别 | 问题 | 修复 |
|---|---|---|---|
| 1 | **P1** | guard.py 紧急暂停(FB组)读 ads_cache 无 platform 过滤——0081 后同 act_id 双平台行共存，撞号时 FB client 去停 TT 广告 id→真 FB 广告漏停（资金安全） | 补 `platform=="fb"` |
| 2 | P2 | ads.py diagnose 反查账户同样缺 platform | _ad_act_lookup 值改 (act_id, platform) 元组 |
| 3 | P2 | fb_apps update_app 系统行走 sdb 后返回旧对象（expire_on_commit=False） | db.refresh(app) |
| 4 | P2 | enabled 态 DNS 有缺口时 UI 无任何修复入口（启用按钮隐藏、无独立补齐端点） | 前端按钮条件扩展：enabled+缺口也显示「补齐 DNS」（复用幂等 enable）+zh/en key |
| 5 | P2 | error_i18n 漏「CF 未配置，请先在…」key（en 用户裸中文） | 补录 |
| 6 | P2 | CF 删目的地/删规则 success=false 被吞（本地照删、CF 残留=转发仍生效而 UI 显示已删） | cf_client 两删除方法改抛错 + settings 捕获 502 |
| 7 | P2 | ads_cache 模型 docstring 唯一键描述过时 | 更新 |
| 8 | P2 | _round1_live.py 误入库 | 删除 |

### R2 同时核实通过项
邮箱转发前后端 7 端点一一对应无 stub、响应字段全一致、zh/en 210 key 成对；PRODUCT_MANUAL 第十章无假宣称；0080 policy 对 OAuth/webhook 读路径无影响；0081 无 ON CONFLICT 破坏面、sync 已带 platform；R1 三项修复确已生效。

### 生产验证
后端 restart+health OK；前端 CF Pages 部署成功（`f731bf3a.tovaads.pages.dev`）；enable 幂等复测 PASS。

---

## 2026-09-03 — 邮箱转发全线打通（CF 权限模型纠偏 + 4 层根因 + 令牌体系重建）

### 概述
用户在 CF UI 建不出正确权限的令牌（「电子邮件路由地址」藏在**帐户**类别下，与规则所在的区域类别不同），改走 API 通道：用用户已配的管理令牌（API Tokens Write）直接 `POST /user/tokens` 建出专用令牌。commit `2aa1f0c`+`b400c6a`+`33554f6`+`a27d969`。

### 根因链（4 层，逐层挖出）
| # | 根因 | 修复 |
|---|---|---|
| 1 | 用户粘贴令牌带双引号 → Authorization 头 6003/6111 | 保存/读取自动去引号+空白（_clean_token） |
| 2 | 缓存 zone_id 坏（带引号+少2字符，30 位） | 从帐内 Tunnel token policy 提取权威 32 位值重写 |
| 3 | **CF 权限模型**：Email Routing Addresses=帐户级组、Rules/DNS=区域级；且地址端点已迁 `/accounts/{acct}/email/routing/addresses`（zone 老路径 403） | API 建令牌（帐户策略挂地址组+区域策略挂规则/DNS）；cf_client 三方法切帐户路径 |
| 4 | 建规则 actions.value 传了 address_id → CF 2007 "must specify forwarding emails" | 改传目的地邮箱地址（实测建+删全通） |

### 附带兜底
- get_email_routing 状态端点 403（缺 Zone Settings:Read）→ MX 记录兜底判 ready
- get_email_dns 失败 → CF 标准 MX×3+SPF TXT 兜底；_em_missing_dns 双键匹配（"@" vs 全域名）

### 令牌体系（最终）
| 令牌 | 用途 | 存储 |
|---|---|---|
| cfat_…753c6（用户建，帐户级） | 主令牌：Pages/DNS/zone（DNS 写实测✅） | .env CF_API_TOKEN |
| tovaads-email-routing（API 建） | 邮箱转发专用（规则+DNS 区域级+地址帐户级） | SystemSetting cf_email_token |
| Tovaads（用户级管理令牌） | 令牌铸造用 | .env CF_ADMIN_TOKEN |
| tovaads-main（API 建，热备） | 主令牌备份（Pages/DNS/ZoneRead/ZoneSettingsRead） | 仅存于 CF，未入配置 |

### 生产验证
邮箱转发 Tab 全链路：状态 enabled（MX 兜底）/ DNS 缺口 0 / 目的地 1 个 verified / 映射建+删实测通过（smokemap99 建后即清）。落地页发布链路随主令牌复活。

### 教训留档
- CF 用户令牌 policy 资源键格式：`com.cloudflare.api.account.zone.<zid>` / `com.cloudflare.api.account.<acct>`（老式 `Zone:<id>` 已拒）
- 建令牌响应明文在 `result.value`；PUT 改 policy 不换明文
- 帐户令牌过不了 `user/tokens/verify`（401 属正常），验证帐户令牌用实际端点探测

---

## 2026-09-02（七·晚）— P1 加固批：fb_apps policy 收紧 + ads_cache 唯一键补 platform + .env 清洗 + 邮箱转发 i18n

### 概述
「其他逻辑还有没有要改」扫描定出的 4 个 P1 全修。commit `c00516a`。迁移 0079→0081。

### 变更表
| 变更 | 说明 | 验证 |
|---|---|---|
| 0080 fb_apps policy WITH CHECK 收紧 | 0023 遗留（0075 只修了 tt_apps，fb_apps 留档）——租户会话可写 tenant_id NULL 系统行。收紧后系统行只走 BYPASSRLS | 6 用例 RLS 冒烟全过（见下） |
| fb_apps.py 系统行写改 SuperSession | **0080 的前置**：create(is_system)/update/delete 系统行原本走 get_db（RLS 受限），收紧后会被 WITH CHECK 拒 → 系统行写路径切 SuperSessionLocal（对齐 tt_oauth 模式）；租户行仍走 get_db | c6 SuperSession 建+软删系统行 PASS |
| 0081 ads_cache 唯一索引加 platform | (tenant,act)→(tenant,act,platform)，防跨平台 act_id 撞号互覆写（纯防御——FB act_ 前缀 vs TT 纯数字实际不撞） | 存量 3 行全保留，alembic head=0081 |
| ads.py rename cache patch 补 platform='fb' | 同类查漏：该 lookup 缺 platform 过滤（FB 分支 patch 错行风险） | py_compile+import 门 |
| settings.py .env 值清洗 | _write_env_and_reload 值含换行会破坏整个 .env → strip+400 拒（「配置值不能包含换行」） | 语法门 |
| error_i18n 邮箱转发段 13 条 | Zone 未找到/10405 引导/别名/验证等 zh→en，en 用户不再裸中文 | 表加载=app 启动 ✓ |

### RLS 冒烟结论（服务器实跑）
每用例独立 session（还原真实单请求生命周期）：租户建自己 App ✓ / 租户建系统行 **被拒** ✓ / 租户改系统行 **被拒** ✓ / 租户改+软删自己行 ✓ / SuperSession 建系统行+软删 ✓。

### 关键发现（留档）
- **set_config(is_local=false) 在事务内执行后，rollback 会把它一并回滚**（commit 才固化）。请求中途捕获异常 rollback 再继续写 → 该连接 RLS 上下文蒸发 → 写被拒/读 0 行。这是**全系统既有行为**（旧 policy 同样拒），非本批引入；正常请求路径（deps 设上下文→写→commit）不受影响。
- pg_dump 用 `.env` 的 `DATABASE_SUPER_URL` 提取密码；`-w` 防 PGPASSWORD 没接上时挂死（本次 0 字节挂 10 分钟教训）。

### 生产变更
- alembic 0080+0081 已应用；备份 `/root/backup_db_0080.sql.gz`（pre-migration 全量）。
- 服务 restart 后 health ok，journal 无 ERR（4 条 gunicorn 重启噪音）。

---

## 2026-09-02（六~七）— 交付打磨批：品牌中立化/Settings Tab 化/全站 UX 重做/邮箱转发修复/告警平台隔离

### 概述
用户 /goal「正式交付前完善体」。6 个 commit（d8dfe19/304ce7e/a2f1b85/3f9a50b/12013ef + email fix）。迁移 0077→0078。零 FB 风险红线全程保持。

### 变更（按主题）
| 主题 | 内容 |
|---|---|
| 品牌中立化 | 登录页副标题去平台名（广告智能管理平台）；功能性 FB 指代文案保留 |
| Settings Tab 化 | 12 卡长页→真 Tab（用户建议）；🔴修 sSuper 未定义（超管 9 Tab 白屏）+保活 v-if 优先级；Tab 进 URL；个人/平台分组 |
| 全站 UX/UI 重做 | 两路审查（数据 4 页+运营 11 页）→两路实施：PlatformSeg 全局组件（平台切换唯一入口=数据页内，删顶栏下拉）；Dashboard 两行式 sticky+KPI 3 语义色+移动端收纳；Ads/AdManager 表格 min-width+汇总行+异常档+搜索；LandingLogs 筛选重组；Tokens/Guard/LaunchTemplates/Assets 等 11 页交互打磨（批量 AI 单次弹窗/双向 dirty-guard/平台筛选 chip）；--t3 对比度 4.5:1；全局按钮三态+plat-chip |
| 🔴 邮箱转发修复 | Failed to fetch 三连根因：DKIM TXT>255 拆两段引号→比对失配重复添加（81058）；CF status=ready 未归一；账户级 token 不支持地址/规则端点。修：归一+幂等+ready→enabled+CF 卡新增「邮箱管理 Token」字段（用户级）；enable 实测 200+DNS 就绪 |
| 告警平台隔离 | 迁移 0078 notifications.platform；emit_notification 加 platform 参数（17 站点全标注真实平台）；/notifications?platform= 过滤；Dashboard 告警面板随平台切换器联动 |

### 复审（用户点名×2）
locale 语法 P0（vue-i18n @ 保留字符+我方修复引入的 JS 语法错）+ P1×3（扩量 TT 汇率对称/手动刷新按凭证 app_id/止损冷却平台隔离）全部当场修；i18n 保留字符扫描器 _scan_i18n.cjs 入库。

### 遗留
- 邮箱转发：等用户创建**用户级 CF Token**（CF→My Profile→API Tokens，Zone·tovaads.com 的 Email Routing Addresses·Edit + DNS·Edit + Zone·Read）填入「域名服务配置→邮箱管理 Token」→ 即可加 seaveywong@gmail.com 目的地+别名映射
- LaunchTemplates blankForm 预填默认值（budget 5 等）违反 no-prefill 规范——需用户拍板口径
- 审查 P2 清单（双币种约定统一/emoji→icon/页面标题双轨等）

---

## 2026-09-02（五）— TikTok 平台接入 P0-P4 全量（两波+复审修复）+ 落地页发布 2×P0

### 概述
用户批准 TK 现在启动（不等 FB 过审，sandbox 可建广告）。commit `516883b`（波1 P0/P1/P2）+ `0461595`（波2 P3/P4）+ 复审修复（本 commit）。迁移 0070-0074（5 个）。**硬红线=零 FB 风险**——复审逐路径验证成立（纯 FB 生产态全等价），并清掉 3 个「一连 TT 即炸」的 P0。

### 变更（按 Phase）
| Phase | 内容 |
|---|---|
| P0 数据层 | accounts.platform + tt_credentials/account_tt_credentials/tt_apps（RLS fail-closed+DML/序列 GRANT）+ perf/ads_cache/allowances/templates 加 platform（perf 唯一键重建）+ 分发器 |
| P1 令牌 | tt_client（v1.3+自计数限流器+duck-type FbClient 方法面）+ OAuth（轮换 token 原子写回）+ tt_token_refresh cron 6h（锁 114）+ Tokens 页 FB/TT 分区（倒计时/寿命红标）|
| P2 像素 | FB CAPI 补齐（**默认关**、同 event_id 三发去重、landing 模板最小 diff 只加 eventID）+ TT 像素建时自动 S2S 点亮 |
| P3 广告 | tt_ad_builder + 素材 file_id 管道（行锁缓存，0073）+ runner/preflight TT 分支（平台守卫/像素 code 解析/出生 DISABLE）+ kpi_mapping TT 映射 + 前端平台切换+TT 术语 |
| P4 平台化 | 巡检入口含 TT 租户+worker TT 分支（KPI 防误杀护栏/observe-only 扩量）+ dashboard platform 参数（all==fb 等价实证）+ topbar 平台切换器（usePlatform）+ useStatus TT 枚举 + Assets TK 9:16 徽标 |

### 复审修复（当场）
- 🔴 P0-1 混合租户 FB 导入 500：iter_tenant_clients 的 TtClient 补 app_id + fb.py 聚合循环 except 扩 TtApiError
- 🔴 P0-2 TT 账户无纳管路径（整链不可达）：/tt/loadable-accounts + /tt/import（显式纳管铁律，未授权一律 not_found）
- 🔴 P0-3 perf 唯一键跨租户撞号腐蚀：0074 键加 tenant_id + upsert 查询补租户过滤
- P1-4 ads_cache_sync platform 过滤（TT 未接前防错标）；删调试残留 .tmp_check.mjs

### 遗留（记录）
- TT 紧急暂停缺位（真烧钱只能 TT 后台手停）——连 sandbox 后优先补
- FB CAPI 防双计技术闸（现仅 UI 提示"先重发布再开"）；Tokens 页 TT 导入 UI（后端就绪）；ads_cache TT 实体映射；ActionLog 无 platform 列；tt_apps policy WITH CHECK 收紧（连同 fb_apps）；TT 扩量真 set_budget
- sandbox 校准点：objective 枚举/分块上传字段/ad operation_status——拿到 app_id 实测后修

### 验证
smoke20 19/19（迁移/RLS×3/序列/回填/fb_capi 全 off/FB 六端点红线回归）+ smoke21 12/12（dashboard 三态等价/TT 模板 CRUD+preflight/KPI 映射）+ 修复后 7/7（perf 新键/tt import/FB 回归）。真 sandbox E2E 等用户 app_id（指引：TK_开发者申请指引.md）。

---

## 2026-09-02（四）— 留档清账三波：Settings旋钮UI + 令牌页4项 + P2大池分级 + #187落地页集成验证

### 概述
用户"留档未做的都做"。3+1 agent：commit `3d47955`（wave3）+ 落地页验证修复（本 commit）。#217/#219/#187 三笔挂账清零。

### 变更（按主题）
| 主题 | 内容 |
|---|---|
| Settings 旋钮 | GET/PUT /settings/guard-tuning（并发/学习期/风暴上限，写后即生效）+ 超管卡片；error_i18n +3 |
| #217 令牌页 | token_type 分流核实已做（补 fb-upload 漏网点：上传是写操作原按 read 选令牌）；data-health 8 类诊断 + data-clean 幂等清理 + Tokens 页超管 modal；孤儿通知核实已做；low_balance 余额告警（口径同看板，6h dedup，阈值可调）|
| #219 P2 大池 | 36 子项：11 已修失效 / 13 修（CORS 生产拦 localhost、/logs 北京业务日+400、last_7d 口径、compliance 枚举、重复路由装饰器、N+1×4、_CACHE 上限、OAuth 死 nonce、FRONTEND_URL 配置化、Dashboard 死代码×6）/ 13 记录（AdsCache 倒排索引/PyJWT/占用文件 4/产品决策 3/评估不修 5——含 total_roas 核实 1.0 同款）|
| #187 落地页验证 | 9/9 矩阵全过（建页→发布→子码→日志→防护→编辑重发→FB扫描→删除）。🔴挖出 2 个 P0：worker const 重赋值（V8 不报 esbuild 才拦，发布 500 **两个月**）+ 域名白名单 NameError（绑域发布必炸）；均当场修复；_worker_check.mjs 加变体趟防再发。P1 cf_client 解绑用 uuid id 调 CF（应传域名）→ 404 假成功，已修 |

### 验证
- smoke19 17/17（旋钮 GET/PUT/no-op/越界、data-health 幂等、CORS 生产无 localhost 头、logs 坏日期 400、9 端点回归）
- 落地页 E2E 9/9（_verify187.py 可复跑）；测试数据/CF 孤儿项目全清，生产页 6 未动复查健康
- 语法门×2 轮 / health 1.3.5 / 前端 CF Pages

### 遗留
- AdsCache 倒排索引表（P2 架构级）、PyJWT 换库、占用文件 4 条 P2（.env 转义/refresh is_managed/tenant_locale N+1/Tokens 排序）
- FB 解封后实测清单（视频上传/扩量/学习期）+ 保活 #188

---

## 2026-09-02（三）— 全清单两波：视频链路/规则引擎4项/素材治理/潜客CRM/受众打通/清单对账 + 复审

### 概述
用户批准全做 8 项 → 两波 3+2 agent 并行（文件分区零冲突）。commit `879e3ec`（波1）+ `f1e063a`（波2）+ 复审修复（本 commit）。迁移 0068（assets.fb_video_ids）+ 0069（leads 轻CRM 三列）。独立复审无 P0，P1×2+P2×6 当场修 4 项。

### 变更（按主题）
| 主题 | 内容 |
|---|---|
| 视频部署链路 | upload_video(advideos,600s,非幂等不重试)+ensure_video_id_for_account+runner/retry/preflight 三分支+前端解锁；迁移 0068；顺手修 CJK multipart 崩溃+retry 缺文件检查 |
| 扩量规则 | slow_scale/roas_scale（1.0 语义移植）：KPI 感知 CPA/ROAS 阈值/步长/日预算上限/连续天数；24h 冷却三道防重复闸；observe 模式；前端参数 schema 与后端契约逐字段对齐（复审验证）|
| 学习期保护 | guard_learning_hours(默认24h) 新广告不动作；get_ads 补拉 created_time 数据源 |
| 告警风暴上限 | notify_storm_cap(30/日,0=关) per(tenant,event_type)；9 类 critical 豁免；dedup 之上第二道闸 |
| 巡检并发 | guard_concurrency(1-8,默认4) ThreadPoolExecutor；线程私有 SuperSessionLocal+SimpleNamespace 纯数据 ctx+暂停/扩量 events 收口主线程回放；复审逐行核验线程安全成立 |
| 素材治理 | 上传去重 md5→409 指明已存在；unmanage+prune 清 hash 死缓存（复审后扩到 video_id 列）；孤儿文件 asset_gc（SuperSessionLocal 防跨租户 RLS 误判）；顺手修 fb-upload 只写遗留单列 bug |
| 潜客轻CRM | Lead+status/note/status_updated_at(0069)；PATCH+筛选+CSV 两列；前端状态下拉(4 语义色)+备注弹窗+筛选组 |
| 受众打通 | 编辑器来源选择器+存为受众入库入口+停用警示；🔴修 _resolve_targeting 优先级坑（非空 json 顶掉 SavedAudience/空 json 直接 None）|
| 清单+对账 | GET /{tid}/deployments(jobs+?job_id= items)；job 完成/retry 后自动刷 ads_cache（原无任何刷新）+live_status join；前端已部署抽屉 |
| 顺手真bug | guard CreateRuleIn 缺 enabled（静默忽略+响应硬编码）；🔴leads_id_seq 无 USAGE（SuperSessionLocal 插 lead permission denied，疑预存）postgres 手工 GRANT+补 0069 |

### 复审修复（同日）
- P1-2：super_engine pool 5→10（并发8+扩量峰值 17>15 会池等待）
- P2-4：fb_image_hashes/fb_video_ids 写回改行锁合并（_merge_asset_cache FOR UPDATE+populate_existing，防并发 job 丢缓存→重复上传）
- P2-5：unmanage/prune 扩到 fb_video_ids 列（视频缓存原零清理入口）
- P2-6：PerfSnapshot 历史查询补 tenant 过滤（双租户同 ad_id 竞态）

### 验证
- 语法门×3 轮 / IMPORT_OK / active / health 1.3.5；前端 build ✓ CF Pages×2
- smoke17 17/17（图片 preflight 回归/扩量规则 CRUD/去重 409/orphans/prune/storm/5 端点）
- smoke18 8/8 + 18b 11/11（lead PATCH 全流程 seed 验证/deployments 两模式/live_status/受众建删+SavedAudience 解析/enabled=false 生效）
- 复审后回归 5/5（prune 两列重构/池=10）

### 复审结论（已知限制）
- 无 P0；并发改造核心论证成立。未修 P2：Settings 无 3 旋钮 UI（guard_concurrency/learning_hours/storm_cap 只能 psql）；受众选择保存清空内联定向无确认；storm TOCTOU 有界超发；P3 三条
- FB 解封后待实测：advideos 真上传、扩量 set_budget 回读 verified、学习期新广告不动作、视频+OUTCOME_LEADS 组合
- 生产观察：多 cron×guard 并发的池等待（已扩池）；journalctl 应见"巡检 N 个账户，并发 4"

---

## 2026-09-02（二）— 5模块深扫修复（账户生命周期+告警正确性+AdManager）+ 切Tab + 复审收尾

### 概述
三 commit（`b89b011` 切Tab / `73ccb2e` 模块深扫 14 项 / `b4f98c9` 复审 P1+P2×3），17+7 文件。3 agent 并行深扫（告警逻辑/规则引擎/素材库/投放模板/广告管理器+账户增删生命周期）→ 全部实现 → 独立复审（无 P0，P1×1 i18n + P2 若干）→ 复审修复批。

### 变更（按主题）
| 主题 | 内容 |
|---|---|
| 🔴 账户生命周期 P0 | retry 对已移除账户会真往 FB 建广告花钱（cred 兜底走全租户 RR 令牌，无止损覆盖）→ retry_item 请求层原子声明（UPDATE WHERE status='fail' 判 rowcount）+ 纳管守卫 400 + _retry_one/_run_deploy_job 后台二次守卫；unmanage 先数 ACTIVE 广告再删缓存，确认文案明示"广告不会停、止损失效"+移除后提示剩 N 条在投；dashboard 已移除账户不再误报"巡检未覆盖" |
| 告警/规则正确性 | observe 规则 TG 消息加"⚠ 仅告警（观察模式）"+action_type=observe_alert+冷却 in_ 扩键；token_expired 按 cred 分键去重；cpa_exceed/consecutive_bad 强制 FB 转化数（原 either 稀释→CPA 被落地点击拉低→漏停；cs=landing 无 actions 时规则不适用）；landing_visits IP 去重；budget 98% 升 critical；sentinel/warmup 全租户 arm 过滤 unmanaged |
| AdManager | 跨币种消耗：perf_snapshots.spend 已是 USD（models/perf.py:13 实证）→ 后端双列 spend/spend_usd，混选折 USD 展示+排序，单币种本币；cached_at=最旧账户+前端超 1h 橙标；拒审原因弹窗（review_feedback）+creative 缩略图；POST /ads/rename（三层改名，md5 锁+审计+缓存补丁） |
| preflight | 子码 slug 存在性预检（拼错=部署成功但归因全断）→ subcode_warn_slug 前端 i18n 渲染；汇率缺失 500→400 静态文案入译表 |
| 切Tab 修复 | 路由 chunk 空闲预取（MainLayout 挂载时，未登录不拉）+ KeepAlive 缓存重数据页（exclude 4 个 query 深链页：AdManager/Landing/LaunchTemplates/Tokens）|
| 复审 P1+P2 | ERROR_ZH_EN +2 条（预算换算失败/移除纳管重试）EN 自动译；_ASSETS_SUMMARY_CACHE 签名加纳管账户数（unmanage 后不再给 1h 旧计数）|

### 验证
- 语法门 ✓ / 服务 active ✓ / health 1.3.5 ✓ / 前端 CF Pages ✓
- smoke（_smoke16）11 PASS / 0 FAIL / 5xx=0：retry 移除守卫 404、preflight 404、guard/status、ads/list cached_at+spend_usd+currency、rename 路由 405、dashboard/fb/guard/budget-check 回归
- 复审 smoke：译表×3 命中（en 译出/zh 原样）、preflight 404、assets-summary 200×2 缓存命中（fresh=1.3s→cached=0.0s）

### 复审结论（已知限制）
- 6 个维度通过；关键独立验证：spend=USD 假设成立（guard_engine.py:682 写入侧实证）、retry 原子声明并发安全、unmanage 先数后删
- 遗留 P2（未做）：runner 内 2 条 FbApiError 静态中文（job item error 无翻译层，EN 用户可见中文，罕见竞态路径）；rename 并发 last-write-wins（15min 同步自愈，预存模式）；pre-迁移0020 旧快照 spend_native=NULL 兜底可能错标币种；被缓存页切回静默旧数据（仅 Dashboard 有自动刷新）

### 生产变更
无 DB 迁移。后端 12 文件部署 + 前端两次 CF Pages。

---

## 2026-08-17（二）— 审计第二批修复（P1 剩余 16 项）

### 概述
commit `1ad6fec`，11 文件 +225/-30 + 迁移 0066。部署链路守卫 + 保活 lifetime + 落地页 5 项 + ingest 防灌 + 表单 config_hash + RBAC/AI 配额。

### 变更（按主题）
| 主题 | 内容 |
|---|---|
| 部署守卫 | 同模板 running job 409 / 账户 managed+归属校验 / items 去重 / archived 拒部署 / retry 只许 fail item+非 running job / startup 回收 >30min 中断 job（FB 侧花钱可见）|
| 保活 | daily_budget→lifetime_budget（原 $5/天无上限烧钱）+ Asset 查询补 tenant |
| 落地页 | Worker 爬虫拦截先行（rules 空也挡）/ block_html 校验明确报错 / 幽灵 draft 失败即删 / CF project_name 强制前缀 / TK S2S dry_run（自检不再发假转化）|
| ingest | event_type 白名单 + 字段 500 钳制 + 每 IP 600/min 限速 |
| 表单 | config_hash 列（迁移 0066，config 变更强制重建 FB 表单）+ AI 生成 20/h 租户配额 + asset 归属 |
| 其他 | rbac 最后 owner 保护 / subcode {{}} 拒绑+status 枚举 / check_credential generic 连续 3 次才判死 / _fetch_post_content 补 tenant |

### 验证
- alembic 0066 head ✓，IMPORT_OK ✓，服务 active ✓
- smoke 13 PASS + 1 假 FAIL（/dashboard/summary 是我拼错路径；真实 /dashboard + /dashboard/trend 均 200）
- ingest 白名单/401、部署守卫 404、subcode 校验（无子码环境跳过）✓


## 2026-08-17 — 全系统审计 + 第一批修复（P0×8 + 关键 P1）

### 概述
8 并行 agent 深度审计全库（routers×3/services/core/安全/多租户/前端），发现 P0×8/P1×47/P2×111（报告 AUDIT_2026-08-17.md）。本批修复全部 P0 + 第一批 P1，端到端 smoke 9/9 PASS。

### 变更
| commit | 内容 | 验证 |
|---|---|---|
| `234fef8` | P0×8：RLS set_config 会话级（救批量写/紧急暂停/refresh）/冷却自动恢复（rate_limited+过期=可用）/JWT membership+role 复查+TG tg_bind 专用 token/Worker TDZ（声明提前）/预算告警补 get_adset_insights/部署 runner tenant 过滤×6/上传白名单+200MB/AI KPI 1h 缓存+tick 去重调用。P1：effective_status/opt_goal 字段补齐（trend_drop+L4 矩阵复活）/FbApiError raw 默认值/POST 超时不重试/creative_links 翻页/coverage_lost 按租户分桶/leads form_id 归属校验/manual_inspect force 参数化/bindparam 顶层/nosniff+DENY 头/迁移 0065（9 表补 RLS）/前端 ElMessageBox+copyIds+趋势图 3 处同步+Assets BASE env | smoke 部分过（见下行修复）|
| `0625dfe` | 补充：cf-zones+domains/import 超管门/登录限速 429+恒定时差/改邮箱要旧密码 | ✓ |
| `1384431` | 关键修复：membership 复查移到 set_config 之后（RLS 表在上下文未设时查 0 行 → 全员误 401） | **9/9 PASS** |

### 关键教训
membership 复查（新加的安全检查）踩了 RLS 自家的坑——tenant_memberships 是 RLS 表，检查放在 RLS 上下文设置前 = 自己把自己锁死。审计修复也要过全链路 smoke。

### 生产验证
- alembic 0065 head ✓，9/9 表 RLS+policy 生效 ✓
- 9/9 smoke：登录限速 429/demo 登录/auth/me/fb accounts(RLS+commit)/dashboard/leads list/伪造 form_id 403/svg 上传 400/cf-zones 403/伪造租户 token 401
- nosniff+DENY 头 ✓，无 SyntaxWarning ✓


## 2026-08-06 — FB Graph API v22→v25 升级

### 概述
FB 平台当前 v25（App Dashboard 确认），系统原 v22 落后（fb_client.py:14）。升级 GRAPH_VERSION + 修 v25 breaking。改前探测 9 核心端点确保安全，0 真实版本 breaking（published_posts 报 code12 是 attachments 聚合字段 v3.3+ 废弃，跨版本都有）。

### 变更
| commit | 内容 | 文件 | 验证 |
|---|---|---|---|
| `5b35f8f` | GRAPH_VERSION v22.0→v25.0（所有 FB 调用统一版本） | core/fb_client.py | 探测 9 端点 8/9 过（published_posts 报210 是 page-token 要求非版本）；7 核心读方法 smoke 全过（accounts/pages/businesses/campaigns/adsets/ads/insights）|
| `217d473` | published_posts 去 deprecated `attachments` 聚合字段→`picture`（v25 下 code12，跟帖 Post Picker 会挂）| routers/fb.py (list_page_posts) | published_posts v25 不报 code12 ✓，picture 字段取到 ✓ |

### 背景：ad policy 顺带验证
换新 App "Tova Ads Manager" 后测 business policy 是否解了：v25 下 campaign/adset/creative 全建成功，ad 失败是 post 不可推广（subcode 1487472，有明确 error_user_msg，**非 policy "didn't comply"**）。结论：business policy 在写操作层没拦，倾向已解；100% 铁证需 page 可推广 post（当前唯一 post 属不可推广类型，如 cover/profile 类）。

### 生产变更
无（纯代码：GRAPH_VERSION 一行 + fb.py 字段适配）。ad_builder.py 参数早就是 v25 风格（LOWEST_COST_WITHOUT_CAP/special_ad_categories），升级无需改。

---

## 2026-08-05 会话 — FB leadgen 潜客 + webhook（FB App Review 第二批权限交付）

### 概述
为 FB App Review 第二批 5 权限中的 `leads_retrieval` + `pages_manage_metadata` 交付完整功能：潜客数据存取 + 实时 webhook 回调。2 个 commit（`8416907` 后端 + `5402e68` 前端），1 个 DB 迁移（0064），后端 + 前端均已部署上线。

### 一、后端：leads 取数 + webhook 回调 + 订阅

| commit | 内容 | 文件 | 验证 |
|---|---|---|---|
| `8416907` | Lead 模型 + leads 表(迁移0064, `lead_id` 唯一去重 + tenant/form 索引)；`GET /leads` 本地列表(page/ad/form 筛选)；`POST /leads/sync` 从 FB `GET /{form_id}/leads` 拉取 + **回填 webhook stub 的 field_data**；`POST /leads/subscribe` 订阅租户所有主页 leadgen webhook；`GET/POST /fb/webhook` 验证 + leadgen 回调(form_id→LeadFormTemplate→tenant 反查) | lead.py, 0064_leads.py, leads.py, fb_webhook.py, fb_client.py, main.py | smoke 全通✓ |

**审计修的 bug**（部署后复审发现并修）：
1. 🔴 `fb_webhook` `created_time` 是 **Unix 时间戳(int)** 存进 `DateTime` 列会错值 → `_parse_created_time` 兼容 int/ISO 两种格式转 datetime。
2. 🟡 `sync` 原去重 `lead_id 存在就 skip` → webhook 先存的 stub（field_data 空）永远补不全答案 → 改 upsert：存在且 field_data 空 → 回填。
3. 🟡 webhook 无 `X-Hub-Signature-256` HMAC 校验 → 加 `_verify_signature`（`FB_APP_SECRET` 配了才启用，未配跳过=dev 模式）。
4. 🟢 `subscribe_page_webhook` 冗余 self-import + 两次 POST → 单次 POST（FB 覆盖式订阅）。
5. 🟢 缺订阅触发点 → 加 `POST /leads/subscribe`（遍历 `me/accounts` 逐页订阅）。
6. 🔴 **`FB_APP_SECRET`/`FB_WEBHOOK_VERIFY_TOKEN` 读不到**（commit `c0e1e2b`）：原 `os.environ.get()` 永远 fallback 默认值——pydantic `BaseSettings(env_file=".env")` 只把 .env 加载到 `settings` 对象，**不注入 os.environ**，systemd 也不用 EnvironmentFile。改为 `settings.fb_app_secret` / `settings.fb_webhook_verify_token`（config.py 加两字段）。**否则用户在 .env 配了也不生效**。prod 实测验证：临时加 secret → 合法签名 200 / 伪造签名 403 / 还原后 200（HMAC 又跳过）✓。

### 二、前端：潜客 tab

| commit | 内容 | 文件 | 验证 |
|---|---|---|---|
| `5402e68` | AdManager 第 4 个 tab「潜客」：列表(提交时间/姓名/邮箱/电话/来源/其他字段 chip)；「从 FB 同步」按钮(`/leads/sync`) + 「订阅主页 webhook」按钮(`/leads/subscribe`)；field_data 解析(标准字段映射中文 label + 自定义字段 chip)；i18n zh+en 两份同步 | AdManager.vue, zh.js, en.js | build ✓ + CF Pages 部署 ✓ |

### DB 迁移
- `0064_leads`：`leads` 表（id/tenant_id/page_id/ad_id/form_id/lead_id 唯一/field_data_json/created_time/fetched_at）+ idx_leads_tenant + idx_leads_form + GRANT。`alembic current` = 0064 head ✓。

### 生产环境变更（非代码）
> **更新（同日重构）**：App Secret + verify_token 已全部挪前端，**不再需要改 .env**。下面是最终方案。

- ✅ **App Secret（HMAC 验签）**：复用 `fb_apps` 表（前端「App 管理」已配的 App Secret，加密存）。webhook POST 遍历所有 active App secret 逐一验签——**用户在前端建/改 App 即自动生效，零 .env 配置**。commit `f...`（refactor）。prod 实测：2 个 active App，真 secret 签名→200 / 伪造→403 ✓。
- ✅ **Verify Token**：存 `system_settings['fb_webhook']`（前端「系统设置 → FB Webhook」卡片改，DB 即时生效免重启）。默认 `toveads_webhook_verify`，建议改强随机值。
- ❌ **不再用** `FB_APP_SECRET` / `FB_WEBHOOK_VERIFY_TOKEN`（已从 config.py 删除；.env 不需要这俩 key）。
- 📋 **FB App Dashboard 一次性手动步骤**（程序做不了自己）：Webhooks → Edit Callback URL → URL `https://api.tovaads.com/fb/webhook` + Verify Token（和前端系统设置里填的同一值）+ 勾 `leadgen` field。公网 GET 验证已通（200）✓。

### 复审结论
- **已知限制**：webhook 回调只带 leadgen_id/form_id/ad_id/created_time（不带 field_data 答案）→ webhook 入 stub，`/leads/sync` 补全答案（已实现回填）。webhook 找不到归属租户的 lead（form_id 未部署过）跳过不入库（避免孤儿）。
- **安全**：HMAC 未启用期间，任何人可 POST 假潜客 → 影响：伪造 lead 因 form_id→tenant 反查失败被丢（无 LeadFormTemplate 匹配），**不会污染真实租户数据**；启用 FB_APP_SECRET 后彻底封死。
- **OAuth 集成**：`subscribe_page_webhook` 已就绪但**未自动接入 OAuth callback**（遵循「显式纳管」原则：用户点「订阅」按钮触发）。
- **真数据测试**：blocked on FB App Review 通过 + 账户导入（FB business policy 限制，无法建 Instant Form 跑真 lead）。webhook GET 验证 + 路由 401 + HMAC 跳过逻辑均已 smoke。

### commit 列表
- `8416907` feat(leads): FB leadgen 取潜客 + webhook 实时回调 + 订阅
- `5402e68` feat(leads): 前端潜客 tab + 同步/订阅按钮
- `c0e1e2b` fix(webhook): FB_APP_SECRET/VERIFY_TOKEN 改读 settings（原 os.environ 读不到 .env）—— *后被 f10be53 重构取代（挪前端）*
- (refactor) App Secret 复用 fb_apps 表 + verify_token 挪 system_settings：FbApp ORM 挪 models + core/webhook_config.py + fb_webhook 遍历验签 + settings.py webhook 段 + config.py 删两字段
- `f10be53` feat(webhook): Settings 页加 FB Webhook 卡片（前端配 verify_token）
- `fbba89c` fix(webhook): 复审 P0/P1 修复（异常返 500 让 FB 重推 + IntegrityError 幂等兜底；GET verify_token 改 compare_digest；/leads total 用真实 count）

### 独立 Agent 审计 + 人工裁决（fbba89c）
审 fb_webhook/webhook_config/leads/settings webhook 段。Agent 报 4 P0 + 6 P1/P2。人工裁决：
- **修**：异常返 200→500（丢 lead 风险，P0）；GET verify_token `==`→`compare_digest`（一致性）；/leads total=真实 count（前端展示错，P1）；单条 IntegrityError 兜底（并发重推幂等）。
- **不改（裁决理由）**：① 默认 verify_token 公开——Agent 方案 b「默认值时 GET 返 403」会致 FB 验证过不了（鸡生蛋），当前用前端「默认」标识提示改强值 + FB App Dashboard 受保护（知道 token 也利用不了）缓解，接受。② 跨租户验签混淆（团队 App secret 在池）——prod 2 个 App 全 `is_system=False`，改 `is_system=True` 过滤会致验签池空=全 403 break；且 form_id 反查才是真租户隔离屏障（fb_form_id 不可猜），当前单租户无实际威胁，未来多租户再加「签名 App 租户 == form_id 租户」一致性校验。

### 关联
- 为 FB App Review 第二批权限（leads_retrieval + pages_manage_metadata + read_insights + pages_manage_ads + pages_manage_posts）交付。SOP 文档 + 录屏给 reviewer Saurabh（**用户明确推迟**）。

---

## 2026-07-30 ~ 31 会话

### 概述
9 个功能/修复领域，17 个 commit（`ce1e860` → `1795bbd`），2 个 DB 迁移（0057/0058），7+ 个前端部署。回退点 tag `rollback/ai-copy-rework-20260730`。

### 一、AI 文案系统重构

| commit | 内容 | 文件 | 验证 |
|---|---|---|---|
| `ce1e860` | 删13预设用途→通用prompt+自由文本「投放目的」；depth/style持久化；表单/消息据素材AI文案生成；文案模型切Gemini；`/ai-purposes`→`/ai-options` | ai_purposes.py, ai_client.py, assets.py, form_templates.py, config.py, ai.py, Assets.vue, FormTemplates.vue, Settings.vue, assets.js, formtpl.js, zh.js, en.js | HTTP端到端✓ |
| `35bb203` | Gemini thinking JSON截断修复：`_extract_json`兜底+max_tokens上调 | ai_client.py, form_templates.py, ai.py | 表单/消息HTTP 200✓ |
| `4a404f8` | headline卡40字；analysis/audience_note跟随ai_language；表单/消息加可选投放目的 | ai_purposes.py, assets.py, form_templates.py, FormTemplates.vue, formtpl.js, zh.js, en.js | analyze 54→29字✓ CJK=0✓ |

**生产操作**：`.env` AI_API_KEY/AI_BASE_URL/AI_MODEL 改 Gemini（复用vision key）；备份 `backup_ai_env_20260730.txt`。

### 二、令牌刷新不刷资产 bug

| commit | 内容 | 文件 | 验证 |
|---|---|---|---|
| `55acdc5` | refreshAll 清assetCache+loadSummary+重拉抽屉；保活NameError(SystemSetting/DEFAULT_KEEPALIVE)修复 | Tokens.vue, guard_engine.py, fb_tokens.py | 非消耗验证warming=8✓ |

### 三、保活(keepalive)——多轮修复

| commit | 内容 | 文件 | 验证 |
|---|---|---|---|
| `6713a47` | 4个FB API bug(campaign/adset字段)+creative image_hash+daily_budget+_ka_rollback | guard_engine.py | 单账户全链路✓(cert前撞墙) |
| `e7193b6` | **Phase1跟帖**：object_story_spec code3→object_story_id(先建主页帖)。新建page_posts表+get_or_create_page_post+get_page_access_token+deploy_one_account分流 | 0057迁移, page_post.py(model+core), fb_client.py, ad_ops.py, guard_engine.py, launch_templates.py, models(fb/launch_template/fb_apps) | 全链路成功✓ 568/569建ACTIVE保活广告 |
| `005eef5` | keepalive文案从硬编码"Follow us!"→素材AI随机文案 | guard_engine.py | 重建568/569✓ follow-page文案 |
| `1795bbd` | pick_random_copy随机headline+body组合(保活+投放共用) | ad_ops.py, guard_engine.py, launch_templates.py | 重建✓ |

**最终**：保活真建广告成功(568/569 ACTIVE $1/day)。生产 keepalive:1 enabled=true budget_usd=1。

### 四、OAuth / 令牌UI修复

| commit | 内容 | 文件 | 验证 |
|---|---|---|---|
| `57b6f5d` | OAUTH_SCOPES加pages_manage_posts删read_insights；fb.py drawer/summary加is_managed过滤 | fb_oauth.py, fb.py | OAuth不再拒✓ 计数统一✓ |
| `1d68fae` | onMounted补loadApps；startOAuth弹窗显示URL+复制/打开 | Tokens.vue | UI验证✓ |
| `d63267e` | OAuth App行双按钮：复制授权链接+在本浏览器打开 | Tokens.vue, zh.js, en.js | UI验证✓ |
| `b635efd` | 授权回调_redirect(302落登录页)→_done_page(HTMLResponse完成页,免登录) | fb_oauth.py | 用户实操通过✓ |

### 五、仪表盘数据bug(3个真bug)

| commit | 内容 | 文件 | 验证 |
|---|---|---|---|
| `995c41c` | account_sync每30min崩(pixel重复INSERT→UniqueViolation→事务回滚→余额/状态全不更新)。修：begin_nested savepoint | landing_lib.py | synced=12不崩✓ 564=$179.58✓ 567=禁用✓ |
| `3b9394d` | 转化900+虚高(poor_fallback_types漏video_view→兜底当转化)。修：补video_view/like/thruplay | kpi_mapping.py | 977→21✓ 回填7行 |
| `47cc67a` | 规则引擎拿不到真实KPI(_campaign_objectives请求optimization_goal=AdSet字段→invalid_param→objective全空→走兜底)。修：fields改id,objective | guard_engine.py | 3个购物campaign返OUTCOME_SALES✓ L4→purchase |

**已知限制**：optimization_goal不取(AdSet字段)→matrix(obj×og)不命中→by_obj推。购物→purchase正确；私信线索可能取lead_grouped(低风险，当前无此类广告)。

### 六、任务进度UI + FB错误中英翻译

| commit | 内容 | 文件 | 验证 |
|---|---|---|---|
| `e06fef4` | 迁移0058(error_code)；run_keepalive返每账户results；useFbError.js(category→i18n)；Settings保活结果弹窗；投放错误翻译 | 0058迁移, guard_engine.py, launch_templates.py, useFbError.js, Settings.vue, LaunchTemplates.vue, zh.js, en.js | smoke: 568/569 success, 564/565/566 skip has_spend✓ |

### 七、随机素材文案+标题组合 + 广告管理器采集

| commit | 内容 | 文件 | 验证 |
|---|---|---|---|
| `1795bbd` | pick_random_copy随机(保活+投放每账户不同)；POST /ads/sync-cache端点+Ads.vue采集按钮 | ad_ops.py, guard_engine.py, launch_templates.py, ads.py, Ads.vue, zh.js, en.js | 568/569重建✓ ads_cache sync=5✓ 缓存有保活系列✓ |

### DB迁移

| 迁移 | 内容 |
|---|---|
| `0057` | page_posts表(tenant,page_id,post_id,asset_id,message,link,body_hash unique) + accounts.keepalive_post_id + fb_apps.access_level(default dev) + launch_templates.post_source/reuse_post_ref + launch_job_items.page_post_id + sequence GRANT |
| `0058` | launch_job_items.error_code(FB错误category，前端i18n翻译用) |

### 生产环境变更(非代码)

| 项目 | 变更 |
|---|---|
| .env AI配置 | 改Gemini(复用vision key)；备份backup_ai_env_20260730.txt |
| keepalive:1 | enabled=true, budget_usd=1 |
| FB App | 发布live；OAUTH_SCOPES加pages_manage_posts删read_insights |
| FB非歧视认证 | 用户已完成 |
| FB广告 | 568/569各1条ACTIVE保活广告($1/day Page Like) |
| 账户 | 2个未纳管账户硬删；6个managed |

### 复审结论

- **无关键bug**。
- **1个已知精度限制**：_campaign_objectives不取optimization_goal(AdSet字段)→KPI matrix不命中→by_obj推。购物→purchase正确；私信线索可能取lead_grouped(低风险)。
- 所有迁移已部署+验证。前端build✓+CF Pages master部署✓。后端语法门+import门+/health 200。

### commit列表

```
1795bbd feat: 随机素材文案+标题组合 + 广告管理器手动采集按钮
005eef5 fix(keepalive): 文案用素材AI生成文案(非硬编码Follow us!)
e06fef4 feat(任务进度): 保活结果弹窗 + FB错误原因中英翻译
e7193b6 feat(跟帖模式Phase1): 建帖→object_story_id
47cc67a fix(rule-engine): _campaign_objectives拿不到objective
3b9394d fix(kpi): 转化虚高——video_view当兜底转化
995c41c fix(account_sync): pixel重复插入致事务回滚
b635efd fix(oauth): 授权回调改返回完成页
d63267e fix(tokens): OAuth App行双按钮
1d68fae fix(tokens): OAuth两个UI bug
4f09615 fix(fb): OAuth加pages_manage_posts+is_managed过滤
57b6f5d fix(fb): OAuth加pages_manage_posts+is_managed过滤
5de8449 fix(tokens): reassociate不再自动纳管
6713a47 fix(keepalive): 4处FB API bug+失败回滚
55acdc5 fix: 令牌刷新连带刷资产+保活NameError
4a404f8 feat(ai): headline卡40字+analysis跟随语言+表单/消息加目的
35bb203 fix(ai): Gemini后JSON截断
ce1e860 feat(ai-copy): 表单/消息据素材+Gemini+删预设改自由文本
```

### 关联memory
- `ai-copy-rework-todo.md`、`keepalive-creative-fix.md`、`fb-app-review-scopes.md`、`dashboard-spend-coverage-bugs.md`、`page-post-follow-mode.md`、`tokens-oauth-ui-bugs.md`、`token-asset-refresh-bug.md`、`account-import-explicit-only.md`、`warmup-keepalive-plan.md`

---

## 2026-07-31 主管复审（自主会话，用户睡觉期间）

复审人=主管AI。按 `review-standard` 6 维度复审上面 17 commit（产出方自审已写，此为独立复核）。

### 通过的维度

| 维度 | 验证点 | 结果 |
|---|---|---|
| 1. 对齐规划 | object_story_id 绕过（page_post.py + ad_ops.py 分流）/ 保活种子帖 per 账户复用 / access_level=dev→建帖 standard→spec / 跟帖锁定矩阵 Phase1 后端就绪（Phase2 UI 待） | ✅ 对齐 [[page-post-follow-mode]] [[keepalive-creative-fix]] |
| 2. SOP 合规 | 后端 6 文件 py_compile + `from app.main import app` 双门 OK；migration 0057/0058 alembic current=0058 head；0057 含 `GRANT ... ON ALL TABLES/SEQUENCES`；服务 active + /health 200 + version 1.3.5；前端 build ✓（767ms）+ CF master 已上线（资源 hash 与本地 dist 完全一致） | ✅ |
| 3. i18n | EN 块零 CJK（唯一命中 `langToZh:'切换到中文'` = 切换目标语言按钮，by-design 设计如此，非 bug）；无 v-for="t" 遮蔽；无 const 物化 t()（AdManager 的 OBJ_MAP/OPT_MAP 是 computed，Settings/Assets 的 t() 在 handler 内动态求值）；fbError 命名空间 zh/en 齐全 | ✅ |
| 4. FB API 正确性 | object_story_id 格式 `{page_id}_{post_id}` 正确（生产 2 账户已存 `157129407483651_122239976978092338`）；get_page_access_token 走 me/accounts 派生；OAUTH_SCOPES 含 pages_manage_posts（建帖必需），去 read_insights（非登录 scope，FB 拒） | ✅ |
| 5. 数据层 | account_sync pixel dup 修：begin_nested savepoint 隔离单条，外层 commit 正常；kpi_mapping DEFAULT_POOR_FALLBACK_TYPES 补 video_view/like/thruplay（生产 system_settings 无 kpi_mapping 行 → 走代码默认 = 已含修复）；_campaign_objectives fields=id,objective（optimization_goal 不取=已知精度限制）；perf_snapshots per-ad upsert 正常（无重复 sum） | ✅ |
| 6. 坑 | 无 v-for="t" / 无 const 物化 / 后端返 code 前端 fbErrorText(category) 走 registry 不靠 .includes(中文)；pick_random_copy 物料化正确 | ✅ |

### 复审结论：无 P0/P1，未改任何代码

- **P0**：无。服务 active、/health 200、建广告链路生产实测过（2 账户 keepalive_post_id + page_posts 4 行）、数据层无重复/不崩。
- **P1**：无。
- **P2（只报告不修，非阻断）**：
  1. **migration 0058 缺 GRANT**（0058_launch_item_error_code.py 仅 `add_column`）。功能无影响：0057 已 `GRANT ... ON ALL TABLES` 覆盖 launch_job_items，新列继承表权限；error_code 列生产可读写已验证。属 SOP "每个 migration 末尾 GRANT" 的流程偏差，非功能 bug。后续 migration 建议仍带 GRANT（防御性）。
  2. **get_or_create_page_post 并发竞态**：query→miss→build→flush 序列在并发部署（多 BackgroundTask job 同时跑）下两 worker 可能同时 miss → 同时 INSERT → DB unique(uq_page_posts_tenant_page_hash) 冲突。当前单 job 内逐账户串行、保活也是串行，触发概率低；且 launch 部署 per-item try/except 捕获 FbApiError，最坏单账户失败不崩 job。可选硬化：INSERT ... ON CONFLICT (tenant_id,page_id,body_hash) DO NOTHING 后重查。低优先。
  3. **OAuth 完成页 `_done_page` 硬编码中文**（"授权成功"/"令牌已导入"）。属 [[i18n-system]] 已记 Phase2（报错 f-string 模板化/TG/落地 worker 同批未做），非阻断。
  4. **_campaign_objectives 不取 optimization_goal**（AdSet 字段，请求会 invalid_param）→ KPI matrix(obj×og) 不命中 → by_objective 推。购物→purchase 正确；私信线索可能取 lead_grouped（低风险，当前无此类广告）。产出方已记。

### 修了什么
**无**。17 commit 复审通过，后端已部署且 active，前端已上 CF master。无需改动、无需重新部署。

### 还有什么风险 / 待跟进
- **Phase 2 跟帖 UI**（[[page-post-follow-mode]] §1-6）：③ 广告 Tab segmented 切换 + Post Picker + 只读锁定卡 + 部署抽屉账户预过滤（管同主页）+ 广告列表"复用此帖铺放"。后端就绪，纯前端工作。
- **object_story_id 帖属同主页约束**：当前选帖/部署两处未做"令牌能管该主页"的账户预过滤（Phase2 才做）；跨主页部署会在建帖/get_page_access_token 阶段报错（已 raise FbApiError，不会静默错）。
- **Marketing API Standard Access App Review**：过审后 fb_apps.access_level 改 'standard' 自动回 object_story_spec（更干净，不用预建帖）。
- P2 四项见上，按需处理。

---
<!-- 后续会话在此分隔线下方追加，格式同上 -->

## 2026-07-31 Phase 2 跟帖铺放 UI + CTA 修复（4 节点串行 + 复审）

### 概述
Phase 2 前端跟帖 UI + CTA 修复 + Phase 2.1。4 commit（`b9d28c5` → `d1899aa`）。回退点 `rollback/phase2-fixes-start-20260731`。

### 变更表

| commit | 内容 | 文件 | 验证 |
|---|---|---|---|
| `b9d28c5` | Phase 2 核心：③广告Tab segmented(新建帖/复用已有帖)+Post Picker(el-drawer)+锁卡(🔒)+blankForm/saveTpl加post_source+后端GET /pages/{id}/posts+i18n 14key | LaunchTemplates.vue, launch.js, fb.py | build✓ |
| `1393364` | CTA修复：LIKE_PAGE value要{page}非{link}(FB 2446128)。pick_cta智能选CTA(ENGAGEMENT→LIKE_PAGE/SALES+shop→SHOP_NOW)。 | ad_ops.py, guard_engine.py | 568/569重建success✓ |
| `232f1df` | TemplateIn+_tpl_dict+_COPY_COLS补post_source/reuse_post_ref（Pydantic不再丢弃）；openEdit null兜底；复用帖主页提示+跳转；手动帖URL解析改进 | launch_templates.py, LaunchTemplates.vue, launch.js | build✓ TemplateIn含新字段✓ |
| `d1899aa` | Phase2.1：部署抽屉reuse模式⚠提示"只选管该帖主页的账户"+主页ID | LaunchTemplates.vue, launch.js | build✓ |

### 生产变更
- YR素材重分析"吸引男性用户点赞或关注主页"（male audience ✓）
- 568/569保活重建（follow-page男性文案+LIKE_PAGE CTA value.page）
- launch_templates.py部署（TemplateIn+_tpl_dict含post_source/reuse_post_ref）

### 复审结论：无 bug
- TemplateIn post_source/reuse_post_ref 补齐（前端发→后端存→_tpl_dict返，全链路通）
- pick_cta LIKE_PAGE value={page}（其他CTA value={link}），两类结构正确
- openEdit null兜底；手动帖URL解析3种格式（{page}_{post}/FB URL/纯数字）；部署抽屉reuse提示
- i18n zh+en 齐全（goSelectPage/manualPostNeedPage/deployReuseHint/postSourceNew/postSourceReuse/selectPost/changePost/postPickerTitle/postPickerHint/postPickerNeedPage/postSelected/lockHint/manualPostId/manualPostPh/noPosts/noImage）
- Ads.vue「复用此帖铺放」入口 = Phase 2.2（后续）

### commit 列表
```
d1899aa feat(Phase2.1): 部署抽屉跟帖提示
232f1df fix(跟帖Phase2): TemplateIn补post_source/reuse_post_ref+复用帖主页入口+手动帖URL解析
1393364 fix(cta): LIKE_PAGE CTA value 要 {page} 不是 {link}
b9d28c5 feat(跟帖模式Phase2): 新建/复用帖切换+Post Picker+锁卡+主页帖端点
```

### 补充：CTA + object_story_spec 迭代（App Live 后回归 1.0 模式）

| commit | 内容 | 验证 |
|---|---|---|
| `8e46200` | object_story_id creative 加 call_to_action（顶层字段）；投放+保活 CTA 补齐 | API 测试 creative 创建成功✓ |
| `40c32ef` | 保活照片帖→链接帖试 CTA 渲染（/feed 不传 picture）；后回退 | /feed 无 picture 可用✓ 但 CTA 渲染仍不明显 |
| `7ca546e` | 链接帖不传 picture（/feed invalid_param 修复） | /feed 成功✓ |
| `4bb0297` | **回照片帖+去掉显式CTA**（让原生 Like 按钮从 PAGE_LIKES 显示） | 568/569 重建 ACTIVE✓ 但用户仍看不到 CTA+文案 |
| `32a79d3` | **回归 object_story_spec**（App Live 后可用，1.0 模式：完整 link_data{image_hash+message+name+link+call_to_action{LIKE_PAGE}}）；access_level→standard | **568/569 creative 含 body+title+CTA+image，用户确认可见✓** |

**根因**：object_story_spec（1.0 模式，完整内容）被 dev 模式 code3 → 改 object_story_id（薄引用，无内容/CTA）→ App Live 后 object_story_spec 恢复 → 回归 1.0 → 完整内容+CTA 可见。

**最终方案**：保活用 object_story_spec（image_hash+AI 文案+AI 标题+page link+LIKE_PAGE CTA）；投放标准路径(build_creative)也用 object_story_spec；跟帖复用(post_source=reuse)仍走 object_story_id（引用已有帖）。fb_apps.access_level=standard。

### 额外 commit
```
32a79d3 fix(keepalive): 回归 object_story_spec（App Live 后可用）— 完整内容+CTA
4bb0297 fix(keepalive): 回照片帖+去掉显式CTA(让原生Like按钮显示)
7ca546e fix(keepalive): 链接帖不传picture(/feed invalid_param)+保活改链接帖(CTA渲染)
40c32ef fix(keepalive): 照片帖→链接帖(CTA才渲染)
8e46200 fix(跟帖): object_story_id creative 加 CTA（call_to_action 顶层字段）
005eef5 fix(keepalive): 文案用素材AI生成文案(非硬编码Follow us!)
1795bbd feat: 随机素材文案+标题组合 + 广告管理器手动采集按钮
```

---

## 2026-07-31 主管复审 Phase 2 跟帖 UI（自主会话，用户睡觉期间）

复审人=主管AI Phase2。按 `review-standard` 6 维度独立复审 Phase 2 跟帖 UI（产出方自审见上方「2026-07-31 Phase 2 跟帖铺放 UI + CTA 修复」段，此为复核）。复审范围 = commits `b9d28c5`→`d1899aa`→`232f1df`→`d1899aa`（+ 后续 CTA 迭代 `8e46200`/`1393364`，跟帖 UI 相关）。

### 通过的维度

| 维度 | 验证点 | 结果 |
|---|---|---|
| 1. 对齐规划 | ③广告 Tab 顶部 segmented 新建/复用单一切换点（L955-958）/ 锁卡 lockHint + reuse-box（L960-968）/ Post Picker 主页必选门（openPostPicker 检 form.page_id，L422）+ 图/文案预览 + 手动 post_id 3 格式解析（{page}_{post}/FB URL/纯数字，L432-441）/ 部署抽屉 reuse 提示+主页 ID（L1091）/ 后端 _resolve_page_post reuse 短路返 reuse_post_ref（launch_templates.py L473-474）+ deploy_one_account 收 page_post_id 走 object_story_id | ✅ 对齐 [[page-post-follow-mode]] §1-5 |
| 2. SOP 合规 | 前端 build ✓ 本地 dist hash=`index-D6P2InbS.js` = 生产 `https://tovaads.com/` 抓到的 hash（**完全一致=已上 CF master**）；后端生产 launch_templates.py 含 post_source/reuse_post_ref（L51/90/91/151）+ _resolve_page_post 分流（L461-474）= 与本地源码逐字一致 = 已部署；/health 200 version 1.3.5；服务 active；Phase 2 文件 git 干净（无未提交漂移） | ✅ |
| 3. i18n | launch.js（Phase2 文件）en 块零 CJK✓；新增 17 跟帖 key zh/en 同步齐（postSourceNew/postSourceReuse/postPickerTitle/postPickerHint/postPickerNeedPage/postSelected/lockHint/manualPostId/manualPostPh/noPosts/noImage/goSelectPage/manualPostNeedPage/deployReuseHint/selectPost/changePost）；LaunchTemplates.vue 全部 launch.* 静态 t() key 解析通过（脚本扫零 missing）；fbErrorText(it.error_code) 走 registry 不靠 .includes(中文) | ✅ |
| 4. FB API 正确性 | object_story_id 复用（reuse_post_ref）→ creative 引用已有帖；page token 走 iter_tenant_clients × get_page_access_token 派生（fb.py L364-372）；published_posts 字段 id/message/attachments{media}/created_time/permalink_url 合理；pickPost(p) 用 p.id（{page}_{post} 格式）→ 后端 _resolve_page_post 直返，不再建帖 | ✅ |
| 5. 数据层 | reuse 模式 deploy_one_account 收 page_post_id → 走 object_story_id 分支（不传 object_story_spec，跳过 image_hash/headline/body/cta 的 spec 字段）；item.page_post_id 持久化（launch_job_items.page_post_id，迁移0057已加）；page_posts 表 body_hash 去重复用（reuse 短路不触发 INSERT，无并发竞态） | ✅ |
| 6. 坑 | 无 v-for="t" 遮蔽（全文件扫零命中）；无 const 物化 t()（pickPost/confirmManualPost 内的 t() 在 handler 动态求值，切语言实时）；无 .includes(中文) 断裂；fbErrorText(code) 走 registry | ✅ |

### 复审结论：无 P0/P1，未改任何代码

- **P0**：无。前端已上线且 hash 对齐；后端已部署且 /health 200；无白屏风险（无遮蔽/物化/缺 key）；reuse 路径生产端到端可走（_resolve_page_post 短路 + deploy_one_account 分流）。
- **P1**：无。
- **P2（只报告不修，非阻断，按 SOP 自主会话不修）**：
  1. **部署抽屉跟帖账户预过滤（§3 未完全对齐）**：规划要求「管主页 A 的可选，其他**灰禁**+提示」。当前实现只有提示（L1091 文字⚠+主页ID），未做 disabled 过滤。数据其实已具备（toggleAcc 已按账户拉 accPages[id]），预过滤只需在 reuse 模式比对 `accPages[act_id]` 是否含 `reuse_post_ref.split('_')[0]`。功能不阻断：后端 `_resolve_page_post`/`get_page_access_token` 对无权账户会 raise FbApiError（明确失败，不静默错），单账户失败不崩 job。
  2. **锁卡未对表单字段做只读/灰化（§2 矩阵 UI 体现不完整）**：规划「图/文案/CTA/链接/落地页/子码 🔒只读」。当前 reuse-box 只用一段 lockHint 文字说明锁定，未对下方 asset/headline/body/cta/landing/subcode 输入框设 :disabled。功能正确（设了 page_post_id 后这些字段 deploy 时被忽略），但 UX 上用户仍能改这些「无效」字段，可能误导。建议 reuse 模式给这些 input 加 `:disabled="form.post_source==='reuse'"` + 视觉置灰。
  3. **summary strip 缺来源 chip**：编辑抽屉顶部 summary strip（L786-793）显示 obj/audience/asset 三 chip，规划要求显示「新建/复用」来源 chip。当前无。低优先。
  4. **广告列表「复用此帖铺放」入口（§6）未做**：Ads.vue 无 page_post_id/reuse_post 引用（grep 零命中）。产出方自审已记为 Phase 2.2（后续）。属快捷入口，不影响模板编辑器主路径。

### 修了什么
**无**。4 commit Phase 2 UI 复审通过，前端已上 CF master（hash 对齐），后端已部署（/health 200），无 P0/P1。未改代码、未重新部署。

### 还有什么风险 / 待跟进
- **Phase 2.2**：广告列表 ♂「复用此帖铺放」入口（§6）+ 部署抽屉账户预过滤硬过滤（§3）+ 锁卡字段灰化（§2）+ summary 来源 chip —— 上述 P2 四项，下次会话按需做。
- **reuse 帖属同主页约束**：当前仅文字提示，跨主页部署会在 get_page_access_token 阶段报错（已 raise，不静默）。Phase 2.2 预过滤后消除误选。
- **landing.js en 块全中文**（既存，非 Phase2 引入，commit 1628b51 i18n 基线）：landing 页 en 完全未译。本次范围外，建议单独排期译 landing.js en 块。

---

## 2026-07-31 主管深度逐行复审（ad6cbf7..HEAD 全量，改 3 处）

复审人=主管 AI。这次不是 6 维度浅审，是**逐文件逐行逻辑深审**（每行分支/边界/前后端字段对接）。范围 = `git log ad6cbf7..HEAD`（新 AI 这批所有 commit，含 i18n 基线/AI 文案重构/保活多轮/跟帖 Phase1+2/OAuth/仪表盘 3 bug）。读完所有目标文件全文（不只 diff）。

### 深审方法
- 后端：逐函数读 page_post.py / ad_ops.py / guard_engine.py(run_keepalive+_campaign_objectives) / launch_templates.py(_resolve_page_post+_run_deploy_job+_retry_one) / account_sync.py / landing_lib.py / fb_oauth.py / kpi_mapping.py / fb_client.py(get_page_access_token) / ad_builder.build_creative。
- 前端：逐行读 LaunchTemplates.vue(1465行) / AdManager.vue / useFbError.js / useStatus.js + 跑 3 个 i18n 校验脚本。
- 生产：py_compile + import 双门 + 服务 active + /health 200 + alembic 0058 head + 前端 hash 比对 + DB 状态(access_level/keepalive/kpi_mapping/page_posts)。

### 逐文件结论

| 文件 | 逻辑 | 发现 |
|---|---|---|
| **page_post.py** `_body_hash`/`get_or_create_page_post` | ✅ 正确 | hash = sha1(asset_id\|message\|link) **含 asset_id**——brief 担心的"换图不建新帖"bug **不存在**（asset_id 变→hash 变→建新帖）。/feed(link 帖)/photos(保活照片帖)两路径字段对。page_posts upsert 用 flush（竞态见 P2.3）。 |
| **ad_ops.deploy_one_account** | ⚠ P2 dead work | L170-175 即使 page_post_id 非空仍调 build_creative(...) 建完整 object_story_spec dict，但该 dict 在 page_post_id 分支(L176-190)从未使用（分支自己 POST /adcreatives）。纯浪费+误导。**但生产 access_level=standard→_resolve_page_post 返""→page_post_id 恒空→object_story_id 分支整体 dead code**，不影响生产。不改（动核心建广告文件风险高且分支已死）。 |
| **guard_engine.run_keepalive** | ✅ 正确 | 已回归 object_story_spec(commit 32a79d3，App Live 后)。完整 link_data{image_hash+message+name+link+LIKE_PAGE CTA}。失败 _ka_rollback 回滚。pick_random_copy 空文案兜底 "Welcome!"。status=ACTIVE（区别 deploy 的 PAUSED）正确。keepalive_post_id/page_post 路径已废弃（spec 直建），一致。 |
| **guard_engine._campaign_objectives** | ✅ 正确 | batch 用 fields=id,objective（不含 optimization_goal=AdSet 字段，避免 invalid_param）。L71/L79 读 optimization_goal 恒""（未请求字段），harmless dead parse。已知精度限制（by_objective 推）已记。 |
| **launch_templates._resolve_page_post** | ✅ 正确 | access_level≠dev→返""；reuse+reuse_post_ref→短路返 ref；否则建帖。传 asset.id 进 hash（含 asset）。 |
| **launch_templates._run_deploy_job** | ✅ 正确 | 表单模板 page-aware 解析 + AI 消息兜底 + pick_random_copy + page_post 解析 + item.page_post_id 持久化。 |
| **launch_templates._retry_one** | ❌ P2（已修） | 与 _run_deploy_job **分歧**：重试用 tpl.lead_form_id（原始）不调 _resolve_lead_form，跳过 AI 消息兜底。LEADS/ENGAGEMENT 重试拿到错误/缺失 form/message。**已改为与 deploy 一致**。 |
| **launch_templates._tpl_dict/TemplateIn/_COPY_COLS** | ✅ 正确 | post_source/reuse_post_ref 三处齐全（返/收/复制）。复制跨主页旧帖失效由用户自负（reuse_post_ref 原样拷）。 |
| **account_sync.py** pixel dup | ✅ 正确 | sync_pixels_for_act 用 begin_nested savepoint 隔离单条 UniqueViolation，外层 commit 正常。 |
| **fb_oauth.py** | ✅ 正确 | OAUTH_SCOPES 含 pages_manage_posts 去 read_insights。_done_page 完成页（硬编码中文=P2，i18n Phase2）。state HMAC 验签+TTL。callback 换 code→long token→建凭证。 |
| **kpi_mapping.DEFAULT_POOR_FALLBACK_TYPES** | ✅ 正确 | 补 video_view/like/thruplay。生产 system_settings **无 kpi_mapping 行**→走代码默认（含修复）。 |
| **fb_client.get_page_access_token** | ✅ 正确 | me/accounts?fields=id,access_token 派生 page token（正斜杠，非之前误读的反斜杠）。无权限→空串→上游 raise FbApiError。 |
| **LaunchTemplates.vue** openEdit | ❌ P1（已修） | **L470 `t.advanced_config`**：openEdit 参数从 `t` 重命名为 `tpl`（commit 范围内）后这行漏改，`t` 现解析为 i18n t() 函数(L10)→`t.advanced_config`=undefined→`JSON.parse(undefined)` 抛 SyntaxError→被 L497 `catch{}` 吞→**编辑已有模板时 Advantage+/版位/频次/CPA/归因/Dayparting 全部无法恢复**（用户重编辑这些设置丢失）。**已改回 tpl.advanced_config**。 |
| **LaunchTemplates.vue** 跟帖锁卡 | ⚠ P2（不改，自主会话） | reuse 模式 asset/headline/body/cta/landing/subcode 输入框未 :disabled（只有 lockHint 文字）。功能正确（设 page_post_id 后 deploy 忽略这些字段）但 UX 误导。与上轮复审 P2.2 同。 |
| **LaunchTemplates.vue** confirmManualPost | ✅ 正确 | 3 格式解析（{page}\_{post}正则/FB URL 末段数字/纯数字）覆盖全。post_source 切换保留 reuse_post_ref（不丢）。 |
| **Assets.vue** L203 | ❌ P1（已修） | `t('assets.analyze')` 字典无此 key→确认钮显示原始串 'assets.analyze'。**assets.js zh/en 补 analyze key（分析/Analyze）**。 |
| **AdManager.vue** | ✅ 正确 | OBJ_MAP/OPT_MAP 是 computed（切语言实时）。§6「复用此帖铺放」入口=Phase2.2 未做（已知，非 bug）。 |
| **useFbError.js / useStatus.js** | ✅ 正确 | fbError 19 key（18 category+generic）zh/en 齐。useStatus t() 在 resolver 期求值（渲染期）→切语言实时。无 v-for="t" 遮蔽。 |

### i18n 校验（3 脚本全跑）
- **en 零 CJK**：launch/dashboard/assets/formtpl/guard/landing/lplogs 全 0 CJK（landing.js en 块**已译**——上轮复审"landing.js en 全中文"备注过时，本次扫证实干净，纠正之）。en.js 唯一命中 `langToZh:'切换到中文'`=切换目标语言钮 by-design。
- **t() key 解析**：1917 leaf key，10 个"missing"全是误报（params.set/get()/.split/ createElement 等非 i18n 调用）。**唯一真 missing = `assets.analyze`（已修）**。
- **const 物化 t()**：LandingLogs L102/Guard L72 HUMAN 是函数内/map-of-arrow-fn，t() 在调用期求值，切语言正常。无真物化。
- **v-for="t" 遮蔽**：0 命中。

### P0/P1/P2 清单 + 修复状态
- **P0**：无（服务 active/health 200/前端 hash 对齐/建广告链路 access_level=standard 走 spec 实测过/i18n en 干净）。
- **P1**（已修 2）：
  1. LaunchTemplates.vue:470 `t.advanced_config`→`tpl.advanced_config`（编辑恢复丢失，已部署）。
  2. assets.js 补 `analyze` key zh/en（确认钮显原始串，已部署）。
- **P2**（已修 1）：
  3. _retry_one 与 _run_deploy_job 分歧（LEADS/ENGAGEMENT 重试 form/message 错），已对齐（已部署）。
- **P2（不改，报告）**：
  - 跟帖锁卡字段未 :disabled（UX 误导，功能正确）。
  - deploy_one_account page_post_id 分支建未用 creative（dead work，生产分支整体 dead）。
  - OAuth _done_page 硬编码中文（i18n Phase2）。

### 生产部署验证
- 后端：launch_templates.py 上传→py_compile + import OK→DB 备份(backup_review_20260731.sql 2.9MB)→restart→active→/health 200 v1.3.5。
- 前端：build ✓(743ms)→wrangler --branch master→生产 hash `index-gG1i9Go2.js` = 本地 dist 完全一致。
- git：commit `4dd2f79` push GitHub。

### 风险 / 待跟进（不改，报告）
- **🔴 锁 ID 冲突（既存，范围外）**：account_sync 用锁 107 = guard_engine.run_landing_block_scan 的 107；ads_cache_sync 用 108 = guard_engine.run_subcode_cleanup 的 108。两对同锁→同时触发时一方 `lock_busy` 静默跳过（account_sync 30min / landing_block_scan 60min / ads_cache_sync 15min / subcode_cleanup 每天4:17）。**本次范围外**（account_sync 未改；guard_engine 改的是 keepalive/objectives 非 lock 行），自主会话不扩散改。建议下批给 landing_block_scan 改锁 110、subcode_cleanup 改锁 111（唯一 ID）。
- **page_post 子系统生产已 dead**（access_level=standard）：page_posts 表 9 行历史遗留；object_story_id 路径恒不触发。等下次 dev 切换/过审回退时复活，届时需验 dead-code 分支。
- **_campaign_objectives 不取 optimization_goal**（已知精度限制，购物→purchase 正确，私信线索低风险）。
- **Phase 2.2**（上轮已记）：广告列表「复用此帖铺放」入口 + 部署抽屉账户硬预过滤 + 锁卡字段灰化 + summary 来源 chip。

---

## 2026-07-31 修后台任务锁号撞车（上轮记的既存隐患，本次落地）

### 概述
上轮深度复审把「锁 ID 冲突」列为范围外既存隐患并建议改唯一 ID。本次落地：`account_sync` 107→110、`ads_cache_sync` 108→111，guard 块 101-109 不动。纯代码（4 个字面整数），无 schema、无功能/逻辑变化。

### 变更表
| 文件 | 改动 |
|---|---|
| services/account_sync.py | acquire+release 锁号 `107→110`（原与 `run_landing_block_scan` 撞） |
| services/ads_cache_sync.py | acquire+release 锁号 `108→111`（原与 `run_subcode_cleanup` 撞） |

> 上轮建议「landing_block_scan→110 / subcode_cleanup→111」（改 guard 侧）；本次改对立侧（standalone service），目的相同 = 11 个固定锁号全唯一。保留 guard 块 101-109 连续段更整洁。

### DB 迁移
无（纯代码，不动表）。

### 生产环境变更
仅上传 2 文件 + restart。无 .env/配置/FB 操作/数据操作。回退点 `git tag backup-pre-lockid-fix`（= c9d53fa）。

### 复审结论
- **影响**：两对任务时段重叠时不再互相 `lock_busy` 静默跳过。属轻微自愈型隐患（下一轮会补上），本次清根因。
- **锁号唯一性**：本地 + 服务器双校验，11 个固定锁号（101-111）各出现 1 次；`ad_ops` 用随机化 hash 锁号（PYTHONHASHSEED 每进程不同），与固定小整数碰撞概率≈0，不动。
- **无 bug**：py_compile + import 门过，/health 200。

### commit 列表
- `5bc0465` fix(cron): 修后台任务锁号撞车(107/108 各两任务共用→静默漏跑) — 已 push GitHub

### 生产部署验证
- 上传 2 文件 → py_compile + `from app.main import app` `IMPORT_OK` → restart → `active` → /health 200 v1.3.5。
- 服务器 grep 复核：`account_sync=110` / `ads_cache_sync=111`，11 锁号全唯一。

关联：[[tech-review-format]] [[toveads-dev-sop]] [[review-standard]]

---

## 2026-07-31 跟帖模式复活 + Phase 2.2 跟帖铺放 UI（sourcemap / 后端复活 / 4 项前端 / Bug1 定位）

### 概述
用户定方向：1-2 继续做、3 锁冲突复查。本轮：
1. **Point 1**：开 sourcemap（生产 Vue 报错之前全 minified 无法定位行号）。
2. **跟帖模式复活（后端，关键发现）**：冒烟发现跟帖在生产是 dead code——`_resolve_page_post` 的 access_level 门挡在 reuse 短路前（standard→返""→reuse_post_ref 被静默忽略）；另发现 `get_paged` 强写 limit=200 致 Post Picker（published_posts FB 上限 100）从未生效。两处都修，冒烟+单测验证。
3. **Phase 2.2 前端**（c 锁卡灰化 / d 来源 chip / b 部署账户预过滤 / a 广告列表入口）。
4. **Point 3**：锁号撞车已确认修复（`account_sync=110` / `ads_cache_sync=111`，11 号全唯一，见上节）。

### 冒烟铁证（生产，Live App `access_level=standard`）
- `act_1015999284712319` + page `157129407483651` + 已存在帖 `..._122240015186092338` → `POST adcreatives{object_story_id}` → creative 建成（id `3098005883741798`）→ 删除。**结论：object_story_id 在 Live App 可用，跟帖复活可行。**
- `published_posts` limit=200 → `#100 The 'limit' parameter should not exceed 100`；limit=100 → 9 帖。
- token scopes 含 `pages_manage_posts` / `pages_read_engagement`（权限够）。

### 变更表

| commit | 文件 | 变更 | 验证 |
|---|---|---|---|
| `75d68e6` | frontend/vite.config.js | 开 `build.sourcemap` | build ✓ 已部署 |
| `a0edd43` | launch_templates.py `_resolve_page_post` | reuse 短路前置（引用已存在帖不依赖 dev 模式）；新建帖路径仍仅 dev（standard 建 new post 撞 code3） | 单测：standard 下 reuse→返 post_id ✅，new→"" ✅ |
| `a0edd43` | fb_client.py `get_paged` | `base[limit]=limit` 覆盖调用方 → 改为仅未指定才填默认 | 冒烟 published_posts 返 9 帖 ✅ |
| `a0edd43` | fb.py `list_page_posts` | published_posts 显式 `limit=100` | 同上 |
| `d6b6d87` | LaunchTemplates.vue | (c) reuse 模式 disable asset/headline/body + validateTemplate 放宽 reuse 不强求 asset；(d) summary 加来源 chip；(b) 部署抽屉 reuse 解析帖主页→灰禁无权限账户+🔒tooltip+预加载 pages；(a 入口侧) onMounted 读 `?reuse_post=` 预填跟帖模板 | build ✓ |
| `d6b6d87` | AdManager.vue | 广告行 ⚙ 加「📌 复用此帖铺放」（ad 有 object_story_id 时显）→ `launch-templates?reuse_post=` | build ✓ |
| `d6b6d87` | ads.py `/ads/list` | 提取 `creative.effective_object_story_id` → 顶层 `object_story_id`（兼容 `{data:[...]}`） | py_compile + import ✓ |
| `d6b6d87` | locales (launch.js / zh.js / en.js) | `sourceColon`/`noPagePermission`/`reusePrefilled`/`adm.reuseThisPost` zh+en；`lockHint` 文案更正 | build ✓ |

### DB 迁移
无（`post_source` / `reuse_post_ref` / `object_story_id` 均无 schema 变更；`object_story_id` 是 `/ads/list` 运行时富化，不入库）。

### 生产环境变更（非代码）
- DB 备份：`/root/backups/pre_reuse_revive.sql`（2.9MB）。**坑**：pg_dump 需 `sed 's|+psycopg2||'` 去 SQLAlchemy 方言，否则报 `role "root" does not exist`（URL 被忽略走默认 socket/用户）。
- 后端（reuse 三件套）：3 文件上传 → py_compile + import OK → restart → active → /health 200 v1.3.5。
- 后端（ads.py）：上传 → py_compile + import OK → restart → active → /health 200。
- 前端：build ✓；**部署遇 Cloudflare Pages API 522（CF 侧宕机，非代码问题），后台重试中**。

### 复审结论（6 维度）
- **对齐规划**：Phase 2.2 计划(c)(d)(b)(a) 全落地；后端复活是冒烟发现的前置（非计划内，但属"复活跟帖"题中之义）。
- **SOP**：备份 ✓ / commit 先于 deploy ✓ / 语法门(py_compile+import) ✓ / i18n zh+en ✓。
- **i18n**：4 新 key zh+en 齐；lockHint 双语更正；en 零 CJK。
- **FB API**：object_story_id 冒烟过；published_posts limit≤100；get_paged 不再覆盖调用方 limit。
- **数据层**：_resolve_page_post 重排（reuse 前置）逻辑正确，无 schema 变更。
- **坑**：见下「已知限制」。

### 已知限制 / 风险
- **P0**：无。
- **(b)** 部署抽屉 reuse 模式开抽屉时为所有账户并发拉 pages（N 次 API）→ 账户多时略慢（有 spinner）。某账户 pages 拉失败 → `accPages=[]` → 判无权限而灰禁（保守安全，重开抽屉可重试）。
- **(a)** reuse_post 来自 AdManager 的 `effective_object_story_id`（恒 `{page}_{post}` 格式）；LaunchTemplates 内手动输入纯 post id（无页前缀）会让 `page_id` 误设为整串——仅影响手动输入路径，AdManager 入口不受影响。
- **(c)** reuse 模式 asset 选择器 disabled；validateTemplate 对 reuse 不再强求 asset（避免死路）。cta/落地页/子码保持可配置（deploy object_story_id 分支确实用到——lockHint 文案已据此更正，纠正上轮"全锁"的误述）。
- 跟帖 deploy 仍走 PAUSED（`deploy_one_account` object_story_id 分支 status=PAUSED），与新建帖一致。
- **前端部署 pending**（CF 522 宕机）；后端已 live。CF 恢复后需验前端 4 项。
- **Bug 1（AdSet tab 崩溃）**：当前源码静态审计（逐常量/函数/ref）+ 生产 build 均无缺陷；用户当时测的是旧构建（6221601 部署前）。已开 sourcemap，若复现可定位行号。

### commit 列表
- `75d68e6` build(frontend): 开 sourcemap——生产 Vue 报错可直接定位行号
- `a0edd43` fix(launch): 复活跟帖模式 + 修 Post Picker limit 崩溃
- `d6b6d87` feat(launch): Phase 2.2 跟帖铺放 UI（锁卡灰化+来源chip+账户预过滤+广告入口）

关联：[[tech-review-format]] [[toveads-dev-sop]] [[review-standard]] [[page-post-follow-mode]] [[keepalive-creative-fix]] [[must-approve-before-do]]

---

## 2026-07-31 跟帖多令牌主页权限修正（用户指出缺口）

### 概述
Phase 2.2 部署预过滤上线后，用户指出：**多令牌同主页但不同账户**时，原预过滤用账户"绑定令牌"判主页权限、部署却用候选池里 priority 最高的写令牌——两者可能不是同一个，导致假阳性（预过滤可选→部署用的令牌没主页权限→`object_story_id` 建 creative 失败）/ 假阴性（候选池里某令牌有主页权限但非绑定/最高→账户被灰禁其实能用）。完整修（后端权威 + 前端可用性端点）。

### 变更表
| commit | 文件 | 变更 | 验证 |
|---|---|---|---|
| `65d7221` | fb_tokens.py | 新增 `_account_write_candidates`（pool→bound→tenant-wide 去重 priority 序）+ `cred_for_account_page`（扫候选池取第一个 `get_page_access_token(page)≠空` 的写令牌，带 `_cache` 跨账户复用）+ `client_for_account_page` | 生产验证：6 账户 pool 各 2 写令牌→全命中 cred 10→**仅 1 次 FB 调用**（cache 生效）✅ |
| `65d7221` | launch_templates.py | GET `/{id}/reuse-eligible`：解析 reuse_post_ref→page_id，遍历 managed 账户用 client_for_account_page(_cache 共享) 判定，返 `{page_id, eligible:[act_ids]}`；`_run_deploy_job` + `_retry_one` reuse 模式改用 client_for_account_page，选不到清晰报错"无访问该主页的写令牌" | py_compile + import OK；/health 200 |
| `65d7221` | LaunchTemplates.vue | openDeploy reuse 调 /reuse-eligible→`reuseEligibleActs` Set；`accManagesReusePage` 用 eligible set（替掉绑定令牌 accPages 近似 + 删 preloadAccPagesForReuse） | build ✓ 已部署 |

### 冒烟铁证（生产）
- 测试页 `157129407483651`：6 managed 账户候选池各 2 写令牌 → 全部 eligible（命中 cred 10）。
- cache size=1：6 账户共享同 2 令牌，首个(priority 最高 cred 10)即管该页→后续账户命中 cache，**总 FB 调用 = 1**（不爆炸）。

### DB 迁移
无（纯逻辑；account_fb_credentials 候选池表既有）。

### 生产环境变更
- 后端：2 文件上传→py_compile + import OK→restart→active→/health 200。
- 前端：build ✓→wrangler deploy（CF 已恢复）→生产 hash 上线。

### 复审结论
- **多令牌正确性**：部署选令牌现按"能管该帖主页"扫整个候选池（不只 priority 最高/绑定），与预过滤（同源 /reuse-eligible 端点）一致 → 假阳性/假阴性双消。
- **性能**：候选池 cred 的主页判定带跨账户 cache，多账户共享令牌时 FB 调用 ≈ 去重 cred 数（实测 6 账户/2 令牌→1 调用）。
- **风险**：`_account_write_candidates` 含 tenant-wide 兜底（候选池空时）——极端情况下租户内任一能管该页的写令牌都会让账户 eligible，可能比"仅绑定池"更宽松；但与 deploy 实际选令牌一致（deploy 也会回退 tenant-wide），故预过滤与结果仍自洽。
- 未做：reuse 模式 per-account 主页 `<select>` 仍可改（toggleAcc 懒加载 accPages）；deploy 实际 page_id 取 item.page_id or tpl.page_id，reuse 下应锁帖主页——属次要 UX，本轮不动。

### commit 列表
- `65d7221` fix(launch): 跟帖多令牌主页权限——主页感知选 token + 可用性端点

关联：[[tech-review-format]] [[toveads-dev-sop]] [[review-standard]] [[page-post-follow-mode]] [[token-dispatch-planning]]

---

## 2026-07-31 修广告组 Tab 崩溃真因（vue-i18n 消息花括号 SyntaxError）

### 概述
用户三次报"新建模板点②广告组 Tab → 弹窗消失只剩蒙版"。静态审计模板逻辑多次判定干净（确无代码缺陷）。靠新加的 `app.config.errorHandler` + sourcemap 抓到真错：`vue-i18n message-compiler SyntaxError @ LaunchTemplates.vue:815`。**根因是 i18n 消息串里的花括号，不是模板代码。**

### 根因
`launch.advancedPlaceholder`（zh/en）原值含 `{"bid_amount":500}`。vue-i18n 消息编译器把 `{` 当插值占位符开头，`"bid_amount":500` 非合法占位符语法 → `SyntaxError` → 组件渲染崩溃 → 抽屉面板销毁、蒙版残留。
- vue-i18n 默认 **JIT 编译**（首次 `t()` 访问才编译）。
- 该 key 仅**广告组 Tab 底部"高级设置" textarea** 用 → ①系列 Tab 不访问它正常，②广告组一渲染就崩。完美解释"只有广告组崩"。
- 这类 bug 对模板逻辑静态分析隐形（它是消息串不是代码）。

### 修复
| commit | 文件 | 改动 |
|---|---|---|
| `5e39fd5` | main.js | 加 `app.config.errorHandler`：Vue 渲染/生命周期错误默认只进 console 不弹窗，现捕获并 showError 回显（含 info+组件名）。诊断利器。 |
| `9cd1bdb` | locales/launch.js | `advancedPlaceholder` 去花括号：zh `'JSON 选填，例：bid_amount:500'` / en `'JSON optional, e.g. bid_amount:500'`。 |

### 验证
- build ✓ 部署（`c1f66a35`）。用户硬刷后点广告组 Tab 应不再崩（待用户确认）。
- 全 locale 扫 `\{[^a-zA-Z_@:':}]`：launch.js 仅此一处（已修）；manualPostPh `{page}_{post}` 是合法双占位符（编译通过，只是无参渲染为空）。
- **🔴 潜在同类风险（Landing 视图，用户未报，未动）**：landing.js `subdomainAuto:'lp{编号}'`（`{编号}` CJK 占位符名）、`copiedHtml:'...{{ad.id}}...'`（双花括号）。vue-i18n 对 CJK 占位符名/`{{` 的容忍度未验；若 Landing 子域名预览/复制 HTML 崩溃，同因。**待验**（用户重度用 Landing 却未报，可能 JIT 未触发或编译器容忍）。

### 教训
- vue-i18n 消息串**不能含裸 `{ }`**（除非合法占位符）；JSON/代码示例入文案要去花括号或用转义。
- Vue 渲染错误**不触发 window error**，必须有 `app.config.errorHandler` 才弹窗——之前只接 Promise/window 错误，漏了渲染错误。

### commit 列表
- `5e39fd5` fix(diag): 加 app.config.errorHandler——Vue 渲染崩溃弹窗回显
- `9cd1bdb` fix(i18n): launch.advancedPlaceholder 花括号致广告组Tab崩溃

关联：[[tech-review-format]] [[toveads-dev-sop]] [[i18n-system]] [[ux-clarity-bar]]

---

## 2026-08-01 Landing 花括号崩溃扫灭 + 帖子 ID 自动匹配主页

### 概述
广告组 Tab 崩溃修后，用户确认生效。继续：(1) 用 vue-i18n 运行时全字典扫，挖出并修 Landing 三处同类花括号崩溃；(2) 实现"帖子 ID/URL 自动匹配主页"（用户的点子：本地 ads_cache 优先，零 FB 调用）。

### 变更表
| commit | 文件 | 变更 | 验证 |
|---|---|---|---|
| `8a0658a` | locales/landing.js + Landing.vue | (1) `subdomainAuto`/`fSubdomainPrefixPh` zh `{编号}`→`（编号）`（CJK 占位符名编译 THROW）；(2) `copiedHtml` `{{ad.id}}`→`{macro}` 占位符 + 调用点传 `macro:'{{ad.id}}'`（`{{` 嵌套 THROW，zh/en 都中） | vue-i18n 运行时全 view 字典复扫 **TOTAL THROW: 0** |
| `0e6fec6` | fb.py | 新增 `POST /fb/resolve-post {q}` + `_local_resolve_post`：完整 `{page}_{post}` 直接拆；裸号/URL → 本地 ads_cache 后缀匹配(零 FB) → FB 遍历令牌兜底 | 冒烟：真帖 `...730089638` → 秒回 page `156015644262452`(local)；假号→None |
| `0e6fec6` | LaunchTemplates.vue + launch.js | `confirmManualPost` 改 async 调 `/fb/resolve-post`：裸 ID/URL 自动回填主页+帖子（不再要求先选主页）；`postResolving` 加载态；i18n `resolving`/`sourceLocal`/`resolvePostFail` + `manualPostPh` 更新 | build ✓ |

### 怎么挖到 Landing 的崩溃
vue-i18n 默认 JIT 编译，`createI18n` 后 `t(key)` 才编译消息；写了运行时扫脚本（createI18n + 逐 key t()）→ 直接抛的就是坏消息。三处：
- `subdomainAuto: 'lp{编号}'` → "Invalid token in placeholder: '编号'"（占位符名必须 ASCII 标识符，CJK 非法）。
- `copiedHtml: '...{{ad.id}}...'` → "Not allowed nest placeholder"（`{{` 嵌套）。
- 注：en `lp{index}` 编译通过（ASCII 占位符），只 zh `{编号}` 崩；`copiedHtml` zh/en 都崩。

### 复审结论
- **崩溃类已扫净**：全 view 字典 runtime 复扫 0 THROW。main zh.js/en.js 内联命名空间 grep 复查仅合法 `{ascii占位符}`。
- **resolve-post 本地优先**命中用户场景（铺过广告的帖）：零 FB、秒回。未铺过的帖走 FB 兜底（GET /{post_num} 遍历令牌，best-effort——裸号 FB 可能要求 {page}_{post} 格式，失败则 404）。
- **风险**：FB 兜底对"裸号 + 未铺过广告"的帖可能 404（FB 裸号解析依赖令牌上下文）；但跟帖主流场景（复用已跑的帖）走本地，覆盖绝大多数。

### commit 列表
- `8a0658a` fix(i18n): landing 三处花括号致 vue-i18n 编译崩溃
- `0e6fec6` feat(reuse): 帖子 ID/URL 自动匹配主页（本地 ads_cache 优先）

关联：[[tech-review-format]] [[toveads-dev-sop]] [[i18n-system]] [[page-post-follow-mode]] [[ux-clarity-bar]]

---

## 2026-08-01 跟帖 UX 重构（切换置顶+选帖卡+③只读）+ 实测撞 FB business 限制

### 概述
用户 UX 反馈：① [新建/跟帖]切换埋在③广告Tab太深、看不到在哪输入帖子ID；② 切换应置顶（系列之前）；③ 跟帖把固定内容（文案/链接）固化。要求查实跟帖可改/不可改边界（实测或 Agent），1/2/4 一起做。

### 跟帖(object_story_id)可改/不可改 —— 实测+Agent 双确认
- **冒烟（真建 creative）**：object_story_id 单独✓ / +CTA(SHOP_NOW/LIKE_PAGE/LEARN_MORE)✓ 都建成；object_story_spec 覆写文案 → FB 拒(code100 Invalid parameter)。
- **Agent 查 FB v26.0 文档**：`call_to_action` 字段文档明确"existing **Instagram** post"——对复用 **FB 主页帖静默忽略**（请求不拒但 CTA/value.link 不生效，帖子自带链接/CTA 才是最终展示）。
- **边界**：跟帖模式图/标题/文案/链接/CTA **全锁**（来自帖，FB 忽略覆写）；可配仅 creative.name(内部)/url_tags(往帖URL追加UTM)+①目标/预算+②受众/版位。
- 据此 UX：跟帖 ③广告Tab **整块只读**（帖子预览），创意字段全隐藏。

### 变更表
| commit | 文件 | 变更 |
|---|---|---|
| `d314059` | LaunchTemplates.vue | (1) [新建/跟帖]segmented 移抽屉最顶；(2) 跟帖置顶选帖卡(input URL/ID/裸号→`/fb/resolve-post`自动识别主页；识别失败→揭示手选主页兜底拼`{page}_{post}`)；(3) ③广告Tab重构：跟帖整块只读(帖子图/文/FB链接预览)，新建帖原创意字段；validateTemplate 跟帖不要求 asset/落地页,要求 reuse_post_ref；(4) ①主页跟帖锁定；(5) Post Picker 去重复手动输入 |
| `d314059` | launch.js | lockHint/reuseLockedHint 据实(用帖自带链接不走落地页/子码追踪)；新 key recognize/browsePosts/resolveFailManual/reuseCardHint/reusePreviewEmpty/viewOnFb/pageLockedByPost/fieldReusePost zh+en。sweep 0 THROW |

### DB 迁移
无。

### 生产环境变更
- 前端 build✓ 部署（`95c1fc3e`）。
- 后端无改动（resolve-post/get_paged 等上一批已上线）。

### 🔴 B/C 实测撞 FB business policy 限制（关键发现）
跟帖端到端实测（deploy_one_account page_post_id 全链路）：
- campaign 创建 ✓（active 账户，2/2 都能建 campaign）。
- adcreative(object_story_id) ✓（早先冒烟）。
- **ad 创建 ✗**：所有账户×主页组合报 `permission_denied`："This business account didn't comply with our Advertising Policies or other standards."
- **结论**：用户 business account 被 FB policy 限制（非代码问题）。跟帖/保活/投放所有真建 ad 都受阻，**需用户在 FB 侧申诉/修复 business 资质**。代码层验证通过（FB 允许的环节都对）。详见 [[fb-business-policy-restriction]]。

### D 债清扫 —— 无可执行项
- 债 1（多 token .first() 7处）/债 2（token fallback）：2026-07-06 已修。
- 债 3（系统事件 tenant_id=1）：当前单租户正确（id=1），仅多租户下需改，属设计决策待定。
- 债 4（landing stub）：landing.py 已建满(600+行)，memory 过时。

### 复审结论
- **跟帖 UX 重构完成**（用户反馈三点全落地：切换置顶+选帖卡发现性+③只读边界据实）。i18n 干净。
- **跟帖代码链路验证通过**（至 FB 允许的上限）。
- **🔴 阻塞**：FB business policy 限制 → 跟帖/保活/投放实测都需用户先修复 FB business 资质。
- **待用户**：① 硬刷验跟帖新UX；② FB 侧修 business 限制（解 B/C/投放实测）。

### commit 列表
- `d314059` feat(reuse): 跟帖UX重构——切换置顶+选帖卡+③只读(事实定边界)

关联：[[tech-review-format]] [[toveads-dev-sop]] [[i18n-system]] [[page-post-follow-mode]] [[fb-business-policy-restriction]] [[ux-clarity-bar]]

---

## 2026-08-02 跟帖(复用帖)功能 6 维度复审 + 优化

用户："复审优化 开启"。跟帖功能本轮反复迭代（resolve-post/内容拉取/前端预览），扫一遍清债。

### 功能现状（已上线）
跟帖模式 = 复用已有帖(object_story_id)投放。支持输入 **帖号 / permalink URL / 广告ID / {page}_{post}** 自动解析主页 + 拉内容预览。
- 后端 `fb.py`: `_local_resolve_post`(本地 ads_cache 反查,支持帖号+广告ID) → `_fetch_post_content`(page_posts→ads_cache 实时 creative→published_posts 边三路) → `_content_from_creative`(统一提取) → `resolve-post` 端点(统一返 message/headline/picture/cta_type/link/permalink)。
- 前端 `LaunchTemplates.vue`: 顶层[新建/跟帖]Tab + 选帖卡(识别/手选主页兜底/浏览) + ③广告Tab 内容卡预览(缩略图+标题+完整域名+文案+CTA按钮)。

### 6 维度复审结论

**① FB API 正确性** ✅
- object_story_id 引用已存在帖：实测 Live App creative 建成（早先冒烟）。
- 暗帖内容：ads_cache 同步带 object_story_spec + thumbnail_url；实时 GET /{creative_id} 兜底（缓存常缺 thumbnail）。
- 视频帖缩略图：FB 给签名 64×64（stp=p64x64，改尺寸 403）—— 平台硬限制，显原生尺寸不放大。
- CTA/链接：object_story_spec.link_data/video_data.call_to_action 提取（图/标题/文案/链接/CTA 全锁，FB 对复用帖忽略覆写，符合事实）。

**② 数据层** ✅
- resolve_post 纯读，无写入。_local_resolve_post 扫 ads_cache（零 FB）。
- 无 schema 变更。

**③ 前端逻辑** ✅
- reusePreviewAvailable computed 区分 loading/无内容/取不到。
- linkDomain 返完整 hostname+pathname（含子码路径）。
- validateTemplate：跟帖不强求 asset/落地页，要求 reuse_post_ref。
- ①主页跟帖锁定；Post Picker 去重复手动输入（移置顶卡）。

**④ i18n** ✅
- launch.js sweep 0 THROW（vue-i18n 编译全过）。
- 新 key zh+en 齐（recognize/browsePosts/reuseLockedHint/postContentUnavailable/loadingPreview/fieldReusePost 等）。

**⑤ 一致性** ⚠→✅（本次修）
- **已修**：_fetch_post_content 路径①③兜底返 dict 补 link（统一形状）；去 _json 冗余 import；docstring 更新；删死 CSS（reuse-box/reuse-hint/manual-post/reuse-need-page/post-preview-thumb,noimg,link）。

**⑥ 坑** 
- 🔴 **FB business policy 限制**（[[fb-business-policy-restriction]]）：建 ad 被拦，跟帖/保活/投放实测都受阻，需用户 FB 侧修复。
- **本会话曾踩的 bug（均已修）**：i18n 花括号 SyntaxError（advancedPlaceholder/CJK占位符/{{ad.id}}）、_resolve_page_post access_level 门挡 reuse 短路、get_paged limit200 覆盖、resolve_post URL 误取页ID、_content_from_creative 作用域 NameError、resolve_post return 漏 headline/cta/link。

### P0/P1/P2 清单
- **P0**：无。
- **P1**：无（曾经的 NameError/return漏字段/i18n崩溃均已修）。
- **P2（本次修）**：
  1. _fetch_post_content 返字段统一（补 link）。
  2. 去 _json 冗余 + docstring 更新。
  3. 删 7 处死 CSS。
- **P2（不改，报告）**：
  - 死 i18n key（manualPostId/lockHint/manualPostNeedPage/goSelectPage）—— 留着无害，密集行编辑风险>收益。
  - 视频帖缩略图 64×64 —— FB 平台限制，无法改。
  - _fetch_post_content 路径②每次实时 GET creative（手动输入场景，可接受；非高频）。

### 生产部署验证
- 后端 fb.py：py_compile + import OK → restart → /health 200 v1.3.5。
- 前端：build ✓ → 部署（8a37a0ef）。
- i18n sweep：launch.js zh/en 0 THROW。

### commit 列表（本轮复审优化）
- `3e3c2b7` refactor(reuse): 复审优化——返字段统一+去 _json+删死CSS+docstring

关联：[[tech-review-format]] [[toveads-dev-sop]] [[i18n-system]] [[page-post-follow-mode]] [[fb-business-policy-restriction]] [[ux-clarity-bar]] [[review-standard]]

---

## 批R（2026-09-04）：资金安全五维审计全量修复 + 哨兵漏网根因 + 看板/链接/管理器重构 + 两轮对抗复审

### 概述
用户哨兵实测漏网（09:05 arm 20 账户 + 故意开广告，3 分钟巡逻未停）触发全面资金安全审计（5 Agent，P0×13/P1×19）→ 批R 全量修复（6 Agent 并行 + 集成收尾）→ 部署 + **哨兵生产实测 PASS** → **第一轮对抗复审（4 Agent，新发现 P0×1+P1×8+P2×10）→ 全修 → 部署** → **第二轮复审（2 Agent：验证一轮修复 + 全局回归）**。

### 哨兵漏网根因与生产实证
根因：dedup 键 = 1h 内 ActionLog 有 pause 日志即跳过，**不看 FB 实际状态**（pause 虚报成功/停后被重启 → 日志在 → 整小时不再停）。
修复：dedup 命中 → 回读 effective_status → 仍 ACTIVE（或回读失败）→ 重停。
生产实测（用户测试案例完整复现）：arm 测试账户 1816188396040295 → 巡逻一轮 `{"sentinel_paused": 1}` → FB 回读 **PAUSED ✅** → 二轮巡逻 dedup 正确跳过（实际已停）✅ → critical TG 送达 → 恢复 disarm。

### 变更表（批R 主体 95191a0 + 8621251）
| 层 | 变更 |
|---|---|
| 数据口径 | burn_fast 双重换算修复（spend 已 USD）/ to_usd 未知币返 None / ZERO_DECIMAL 23→25 币统一 core/ad_ops 真相源（PYG/XPF 回补） |
| 哨兵/巡检 | dedup 回读实况 / armed 不跳快照 / status 黑名单 (2,8,100,101) 宽限9受限7未结清3 继续管 / 假停核验三级 / sentinel_failure critical / TT 分支删日志去重（get_active_ads 即地面真相）+ 通知 1h 去重 / FB 批停通知 30min 去重 |
| 部署器 | 重试同名 campaign 幂等（须非死状态+挂 adset 才认）/ 预算 $5000 上限+5x 步进 FB+TT 共用 _budget_guard_check / legacy daily_budget 同口径 USD 等值上限 / advisory lock 115/116 |
| 告警 | TG 3 次重试+通道故障 critical（streak 键 (bot,chat)）/ critical join 在职 membership（防离职泄漏）/ NO_CAP 补 rule_pause+budget98 / storm 压制计数可见 / sync_stalled critical + dedup 24h（曾 60 天） |
| 广告管理 | /ads/live-status 10s 缓存+写后失效（LIVE_STALE_MARKS）/ 4 端点 is_managed 门 / unmanage 在投告警+留痕 platform |
| 前端 | 看板方案B重构（stuck 体系全删=抖动根治/平级卡片/1680 收口/移动端 gap+order）/ 投放链接模式 tab / 管理器缓存龄+⚡实时核验+预算确认 / zh tabLanding 英文泄漏修复 |

### 迁移
无（零迁移批，纯代码）。

### 生产变更
- 后端 3 次部署（16+1 文件 → tt_client 循环引用修复 → 11 文件一轮复审修复），全门（py_compile/IMPORT_OK/restart/health v1.3.5）
- 前端 3 次 CF Pages 部署（master 分支）
- 事故发现途中修复：core/ad_ops ↔ core/tt_client 循环引用（tt_client 改函数内延迟导入）

### 两轮复审结论
**第一轮（4 Agent 对抗）**：P0×1（to_usd float×None=TypeError 非 None，全部 None 防护是死代码）+ P1×8 + P2×10 —— 全修（320d812）。亮点发现：emergency_done 通知自 b1cc565 起因 ImportError 静默死亡、离职成员 TG 绑定持续收 critical、ZERO_DECIMAL 丢 PYG、sync_stalled dedup 写成 60 天。
**第二轮（2 Agent）**：验证一轮修复本身 + 全局回归（import 环/i18n 键/锁号/dedup 配对/to_usd 全调用点/locale parity/DB 兼容）。
生产冒烟：to_usd(100,COP)=None ✅（P0 实证）/ 哨兵巡逻回归正常 / journalctl 零错误。

### commit 列表
- `95191a0` feat: 批R——五维审计P0全量修复+哨兵根因+看板/链接/管理器重构
- `8621251` fix: tt_client 延迟导入防循环引用
- `320d812` fix: 第一轮复审修复——P0×1+P1×8+P2×10

### 遗留（已知不改，下批复核）
- lock 115 全局锁跨租户假 409（低频毫秒窗）/ patch_account_cache_status 死代码清理 / budget_alerts date_preset→time_range 对齐 / AdManager 实时核验仅广告 Tab 生效 / 看板 7 卡 4 列残行 / TG 阻塞重试拖慢同步请求（请求路径不重试或后台线程化）

关联：[[sentinel-dedup-incident-2026-09]] [[tech-review-format]] [[toveads-dev-sop]] [[review-standard]] [[notify-dedup-mandatory]]

---

## 可靠性体检（2026-09-04 下午）

### 概述
/goal 系统可靠性全维度体检：运行时 + 未复审新码对抗审查 + 数据面 + 修复验证。

### 体检结论
- ✅ 服务 active、journal 零错误、巡检心跳 1min 前、16 个 cron 全注册（journal Added job 实证，含新 leads_poll/reaper）、锁号 101-117 无冲突、近 1h 无 fail 日志、哨兵 0 armed
- ✅ 巡检覆盖稳定：评估 25-32 条 / 跳过 0（10:40 的 7 条跳过 = 与 ads_cache 同步竞态，下轮自愈；告警已带名单）

### 抓出并热修（审查 Agent + 体检双轨，commit dda160c/0459ab6）
| 级别 | 问题 | 后果 |
|---|---|---|
| P0 | guard leads_map `_f` UnboundLocalError 被 except 吞 | leads 口径死代码 |
| P1 | dashboard 潜客 COUNT 子查询裸列+聚合 PG 42803 | 潜客 KPI 恒 0 |
| P1 | leads_poll 北京日 vs 账户本地日 | GMT-8 账户每天 16h 不轮询 |
| P1 | 轮询 join 无租户 + lead_id 全局唯一 | 跨租户同 act_id 撞唯一键炸整轮 |
| P1 | 待处理直跳 regex 对 rule_pause body 永不命中 | 功能对主场景无效 |
| P2×4 | 轮询截断无序/status NULL/coverage 名单未 _esc/CPL 口径 | 详见 commit |
| 可观测性 | root logger=WARNING 吞所有 cron INFO | 排障靠猜 → basicConfig INFO |

### 端到端验证（插测试 lead → 三链 → 清理）
- dashboard KPI total_leads 显示 ✅；guard leads_map={ad:1} ✅；轮询全局去重不炸 ✅
- **生产实证：leads 表已积累 20 条真实潜客**（轮询管道下午拉到）——潜客闭环全通

### 遗留（用户决策项）
- TopProperty.eco（act 853297941506126）：纳管+活跃但零令牌关联，8-14 起未巡检——需配令牌或取消纳管（数据卫生）
- 教训入库：裸 except + 新功能 = 生产静默归零；新功能必须带断言 smoke

关联：[[sentinel-dedup-incident-2026-09]] [[no-protection-periods]] [[tech-review-format]]

## 批F：FBInsider 对标四项 + 1.0 差异巡检五项（2026-09-05）

### 概述
/goal 全做：FBInsider ①按素材批量生成系列 ③账户分组 ⑤禁用原因副行 ④TG偏好矩阵 + 1.0 巡检差异 5 缺口修复。4 Agent 并行分片（文件严格分区）+ 集成收口，单次部署。

### 变更表（commit 4d58233，22 文件 +1271/-118）
| 分片 | 内容 | 关键落点 |
|---|---|---|
| F2 batchGenerate | DeployIn.asset_ids 批量模式：模板=母版，每素材克隆完整系列（campaign 名=素材名），FB+TT 双链 | launch_templates.py：抽 `_deploy_series_fb` 单/批共用；partial 汇总（成功X/Y+失败前3）；批量素材清单存 action_logs.metadata；每系列 touch created_at 即 commit（防 `_reap_stale_jobs` 误杀→双份广告资金事故）；retry=整 item 重跑（撞名误命中 `_find_existing_campaign`=假成功，故不走幂等）。前端抽屉 mode radio+素材多选+N×M 预览 |
| F3 分组+禁用原因 | 迁移 0084：accounts.group_label(Text)+disable_reason(Integer) | PUT /fb/accounts/group（批量、空串=清除、>500 拒、FB/TT 混批按平台分行 write_log）；account_sync 4 处落库（**显式判 None——0=恢复正常，or 兜底会让旧原因永远清不掉**）；Ads.vue 分组列/列头聚合排序/筛选/单+批量编辑；useStatus FB_DISABLE_REASON 全枚举+disableReason()；状态徽标禁用原因副行；Dashboard 分组 chip+账户可用明细原因行 |
| F4 TG偏好矩阵 | 迁移 0085：user_tg_bindings.prefs(JSON)；**critical 恒推不受限（用户确认），warning/info 可关；NULL=全推 fail-open（宁多推不漏推）** | GET/PUT /notifications/tg/prefs（未绑 400；一人多绑定全行同步写）；`_send_tg_by_role` 发送前门控——只挡 TG 层，站内信不受影响；TgManager「通知范围」节（critical 🔒 锁定行） |
| F1 巡检可靠性 | 1.0 差异 5 缺口 | ①**暂停回写 ads_cache**：`_patch_cache_after_pause` 三层 JSON 置 PAUSED，campaign 级**级联旗下 adset/ad**（哨兵恒 campaign 级停而 coverage_lost 查广告行——只改 campaign 行照样误报，级联才是根治）；3 调用点（规则链/FB 哨兵/TT 哨兵）②watchdog per-account 停滞（managed+status=1 且 >30min 未巡→critical 聚合，6h dedup）③每轮跳过账户聚合告警（无令牌/insights 失败分类，warning 6h dedup）④心跳带原因（evaluated=0 时区分「哨兵armed全跳过」vs「live清单空」；跳过 N 账户(M无令牌,K失败)；兜底 N 账户）⑤live /ads 降级兜底 streak≥3→warning。i18n 3 键 zh+en |
| 集成（主线） | act_id 通知关联 | emit_notification act_id→映射既有 target_type/target_id 列（零迁移）+ guard 4 处账户级调用接线（unsupported_currency/permission_error/spend_spike/TT sentinel_pause）——前端 notiActId 正则提取是脆弱路径，落库后可直接按列过滤；dashboard 账户行带 group_label/disable_reason；locale 收口（status.dr\*×20+tg.prefs×7+views/ads.js 片段注册进 zh/en） |

### 生产变更
- 迁移 0084/0085 已 upgrade head（列+GRANT 验证）；服务重启 health ok；前端 CF Pages 已部署

### 断言 smoke（_smoke_batch_f.py，ALL_PASS）
- F3：group 设→/fb/accounts 读回→dashboard 透传→清除 全链 ✓；两键暴露 ✓
- F4：GET 默认全 true（bound）→ PUT info=false 落库 → 恢复 ✓
- F2：临时模板（预算+假pixel）→ preflight asset_ids=[2素材] account_count=2 → **series_count=4 断言过** → 模板已删
- F1：force inspect→心跳写入 ✓（本轮 evaluated=7 无 0 条条件=不加后缀，正确行为；机制 F1 已 7 用例单测）

### 遗留
- batchGenerate 真部署（花钱）待用户：建议 1 账户×2 素材验证「成功2/2系列」+FB 后台系列名=素材名；partial 重试会重建已成功系列（UI 确认弹窗已警示）
- 通知 target_type/target_id 前端尚未消费（后续告警中心可按账户过滤）
- FBInsider 未做项保持不做清单（草稿树/列管理/BM归属/persona池/授权倒计时）

### 批F补遗：⑥ 追踪参数通用插值（commit a573544）
- 白名单 7 占位符（部署时已知静态值）：`{{campaign.name}}`（批量模式=素材名）`{{adset.name}}` `{{account.name}}` `{{account.id}}` `{{asset.name}}` `{{template.name}}` `{{platform}}`；值 URL 编码（名字含空格/中文/& 不打断 query）
- **`{{ad.id}}` 显式拒绝**（400 带历史事故说明：FB 建广告前拿不到 ad id + 子码绑此占位符曾像素不 fire）；未知占位符同样 400 快失败——不留部署时静默产垃圾 URL
- 六点接线：模板 create/update 校验；FB/TT preflight 插值（用户核对的就是解值后的真实 URL）；`_deploy_series_fb`（单/批共用）/TT 部署/retry 直连三处逐账户解值
- 前端：模板编辑器落地 URL 输入框白名单提示（zh/en）
- smoke 增 4 断言全过：ad.id 拒 400 / 未知占位符拒 400 / 预检 payload 无残留 `{{` / 含 account.id+p=fb
- 附带生产实证：本轮心跳「评估0条广告…（哨兵armed-全部跳过）」——F1 心跳带原因 suffix 真实落地

### 批F 主管复审（2026-09-05，/goal 复审 优化）——3 Agent 对抗性复审 + 全清修复（commit aeb1386）

**复审方式**：R1（巡检可靠性链 F1+F4）/ R2（花钱链 F2+⑥）/ R3（分组/前端/i18n F3+集成）并行，按 6 维度逐条取证（文件:行号）。**结论：P0×1 + P1×5 + P2×16，全部修复并部署；未修项均为文档化接受（见下）。**

| 级别 | 问题 | 修法 |
|---|---|---|
| **P0** | `itemErrText` 里 `fbErrorText('partial')` 兜底翻译**遮蔽 it.error**——后端构造的「成功X/Y系列」汇总（重试前唯一决策信息）用户永不可见（R2，资金链信息断裂） | partial 直用 it.error（正文+title 两处 3 个模板点） |
| P1 | watchdog 停滞账户集 `account_status==1` 与巡检死状态集口径矛盾——受限/未结清/NULL 仍在花钱的账户被挡在 critical 告警外（R1，漏报向） | 镜像巡检过滤 `or_(is_(None), notin_([2,8,100,101]))` |
| P1 | 批量 partial retry 零确认一键重建已成功系列（R2） | `retryPartialConfirm` 确认弹窗（zh/en） |
| P1 | deploy/retry 端点缺占位符校验——⑥ 前存量模板脏占位符部署时静默清空（R2） | 两端点补 `_check_url_placeholders` → 400 |
| P1 | `_job_batch_assets` 裸 except return [] 可把批量 job 静默降级单模板（R2） | logger.warning 留痕（保留 [] 兜底） |
| P1 | FB_DISABLE_REASON 1-8 官方语义错位——支付失败(2)标成「广告诚信」danger，用户走错补救路径（R3；10-19 已证吻合只修头部） | 重排 1=诚信政策/2=支付失败/3+5=灰号/4=支付风险/7=不活跃/8=待定 + 3 新键 -4 废弃键 |
| P2 | 暂停回写 rollback 会丢调用方挂起写+零日志（R1） | SAVEPOINT + logger.warning |
| P2 | live streak 进程内计数多 worker 失真（R1） | 改从心跳 trigger_detail 数连续「兜底」（跨进程真相源） |
| P2 | 新 TG 绑定行 prefs=NULL 悄悄恢复用户关闸（R1） | 建绑定两处继承既有 prefs |
| P2 | prefs 400 中文未入译表（R1） | ERROR_ZH_EN 补条目 |
| P2 | `{{campaign name}}` 类非法写法漏检直达 FB（R2） | 宽 regex + 残留 `{{` 兜底拒 |
| P2 | LEADS 表单/跟帖链接吃字面 `{{xxx}}`（R2） | `_stable_landing_url`（只解 template.name/platform，系列/账户级剥离） |
| P2 | reuse 跟帖模板可进批量（全系列同帖、预算×M）（R2） | deploy 400 |
| P2 | 批量 retry 残留旧系列 campaign_id/ad_id 误导核对（R2） | claim 时清三 id |
| P2 | Ads 批量清除分组无确认（R3） | confirm 弹窗 |
| P2 | TgManager Promise.all prefs 失败拖垮弹窗（R3） | allSettled + prefs 单独回退默认 |

**复审确认无损的关键面**（原文取证）：暂停回写级联字段名与 FB/TT 存储行逐字段一致、三新告警 dedup↔write_log 严格配对、F4 fail-open 三态+critical 恒推+站内信不受影响、act_id 映射不覆盖 rule_pause 既有 target、迁移 0084/0085 链+GRANT 幂等、launch.js 388/388 键成对 en 零 CJK、PUT group 走 ORM 逐行无 bulk-update 越权面、views/ads.js spread 与内联 62 键零冲突、抽屉 409/锁 115 唯一/心跳提交守卫骨架完好。

**文档化接受（不修，均有 reason）**：①四类通知对同一无令牌账户叠加（各类 dedup 独立，6h/24h 窗口下量可控）②聚合告警 platform="fb" 硬编码（TT 未投产，投产后升 P1）③legacy daily_budget 模板确认弹窗金额 $0（budget_usd 是主路径）④批量+LEADS 未选表单模板的 AI 生成风暴（低频）⑤reap 并发窗口超大视频上传心跳粒度（存量）⑥子码+query URL 拼接变形（存量）⑦已移除账户行缺两键（前端 falsy 安全）⑧⑨ dashboard.py:278 与 notify.py 权限粒度（无实际触发面）。

**验证**：4 后端文件 py_compile+import 门 → restart → health ok → 全量 smoke 回归 **ALL_PASS**（含心跳「哨兵armed-全部跳过」后缀仍落地=streak 改造未破坏主链）→ 前端 build ✓ + CF 已部署 → commit aeb1386 已推送。

### 哨兵权限退避（2026-09-05 00:30，commit 98b3384）——用户报"权限不足"+「已停用账户没必要再关」
- **根因（四段生产诊断）**：BSCH-TD-O336/O338 两账户的令牌（Sagar Bos，scope 全齐含 ads_management）读 insights/系列正常、**写 pause 被 FB 拒**——BM 广告账户角色被降/收回或账户被供应商回收（账户级永久错误）。哨兵每 3 分钟重试必然再失败，journal 刷"停系列失败"+sentinel_failure 告警。
- **修复**：停系列遇 permissions → 写 `sentinel_perm_deny_{act_id}` 标记（24h）+ 发一条 critical（含处理指引）+ break 跳过该账户剩余系列；巡逻开头查标记 <24h 整账户静默跳过，**过期自动重试探权限恢复**（恢复即正常巡逻，未恢复再退避）。
- **生产验证**：手动巡逻 → 2 标记落库 + 2 告警发出 → 下一轮 cron（armed=20）停 0 系列、**0 条失败日志**（刷屏消失）。
- 遗留决策（用户）：这两账户若确认不再使用 → 取消纳管（历史数据保留）或解除哨兵 armed；若还要用 → BM 里恢复该用户广告投放及以上角色。

### AI 额度耗尽：长退避 + 告警（2026-09-06，commit d046e12，/goal 修BUG）
- **根因（生产实测）**：Gemini 返回 `prepayment credits are depleted`（**余额耗尽**，非限流）——每轮巡检 17 账户逐个撞 AI、每次 dump 原始 JSON 刷 journal，且完全静默（AI 功能全停无人知晓）。接手 AI 的 429 跨 worker 5min 退避（1574b12）方向对但**未部署**，且 5min 对余额耗尽语义错误（充值前重试必然再失败）。
- **修复（在其骨架上补齐并一并部署 5 文件）**：AiError 加 `quota` 标记 → quota=True 走 **6h 长退避**（充值后改 AI 配置即换键立即恢复）+ 首次发 `ai_quota_exhausted` warning（24h dedup，文案含充值指引）+ 前端事件翻译。
- **生产断言**：强制巡检后 `kpi_ai_retry:* quota=True retry_in_min=360` ✓ / notifications 1 条「🟡 AI 服务额度已耗尽」✓ / 5min 后 journal `prepayment credits` 出现 0 次（刷屏消失）✓。
- **用户行动项**：Gemini 余额充值（ai.studio → Billing）。

### 真投放最终验收 + 错误精确识别（2026-09-07，0ac194b/a87d4a9/c789bc9）
- **第一条真实广告上线**：job#16 completed（Roly-V21 × RH-Signals × YR-001素材 × TRAFFIC $5/天），FB 核实 ad 120249455794040413 存在、IN_PROCESS 审核中。全链 8 秒建成。
- **沿途抓出并修复 3 个真 bug**：①写令牌同 priority 时 manage 恒排前→建广告全撞管理号（tiebreaker: operate 优先）②App Live 后发主页帖被 pages_manage_posts 挡成死路（发帖被拒自动回退 object_story_spec 内嵌——standard access 正确路径）③FB 原始错误码被吞只留英文摘要（code31→account_checkpoint 安全锁定分类 + 未知错误保留 FB error_user_title/user_msg 中文原文——#3858385 风控锁定一眼定位）。
- **投放前置的 FB 侧知识沉淀**（实测矩阵探针）：账户写权/主页可推广对象/页权限三者独立——错误码分别对应 account_write(33)/1815645 可推广对象不匹配/code31 安全检查点(#3858385 异地登录风控，需号主本人验证)。
- 限流状态列（888d1fe）+ webhook 12 页订阅全通 + 巡检 6.1s/轮同批完成。

### 告警收敛 + 巡检独家供数 + 主页受控（2026-09-08，e6a83b8/0f3693c/f0956db/9e231b3/8cd4b6b/5053066）
- **告警链收敛到两条**（用户决策）：一次令牌故障只报「令牌失效」(根因) +「数据同步已停」(持续)。inspection_skipped 剔除 token_expired 类（同轮根因告警已发）、watchdog 单账户停滞在租户全平台无活跃凭证时让位 sync_stalled——同因抑制而非时间窗抑制，叠加故障（另一账户别的原因丢覆盖）不吞。streak 匹配改机器记号 `fb_fallback=`（曾被解释文案「见兜底计数」撞词误报，同一处咬两次的教训）。
- **巡检独家供数批**（9e231b3，省 API）：FB 巡检改拉全状态 /ads（本地过滤 ACTIVE 语义等价，复审四疑点全核验）+ 回写 ads_cache.ads_json——管理器广告层数据源从 15min cron 变 5min 巡检；ads_cache_sync 不再拉 /ads（include_ads=False）；budget_alerts ACTIVE adsets 走缓存。/ads edge 16→12 调/h·账户。
- **数据源断链可见化**（f0956db）：/ads/list 加 token_status（纯 DB）→ 页头警示条 + 行内「快照」角标 + 状态开关禁用——令牌失效后「投放中」是最后快照而非实时。
- **双层时间戳**（8cd4b6b，迁移 0086）：ads_cache.ads_updated_at 独立列（巡检回写/手动全量刷；结构层 sync 不再冒充广告层新鲜）——修「缓存不到1分钟配陈旧广告数据」误导（令牌切换间隙实测）。管理器三时间戳全按 ads 层取。
- **按页订阅 + 主页受控视图**（8cd4b6b+5053066）：GET /leads/pages（每页权限面 可管理/仅广告/只读 + subscribed_apps 实况按 App id 匹配，多令牌同页权限 OR 合并与订阅语义一致）；subscribe 加 page_ids；前端「主页与订阅」面板勾选订阅。生产实证：Gim Jim 令牌 10 页 0 可管理/4 仅广告/6 只读——OAuth 复制权限不能放大，权限三层独立（账户写✓/页广告✗/页管理✗）再获实证。
- **复审修复**（5053066）：P1×2（TtCredential import 错模块被 except 静默吞→TT 租户停滞告警失效；受控面板「首个即锁」弱令牌误判只读）+ P2×4（token_status TT 恒 True；缩略图 @error 永久隐藏；docstring 矛盾；budget freshness 需第三列记录不做）。
- 用户侧挂账：Gim Jim 需 BM 补「管理主页」+「广告」任务（10 页当前 0 订阅能力）；Gemini 充值；极简操作规划待讨论。

### 全库逐行审查+修复（2026-09-08，6db2507/89be592/184ce2b/eb6f85e/2c83bce）
- **审查规模**：5-agent 对抗审查（26路由+20服务+26core/模型逐行 + 前端17.2k行全读），发现 P0×4/P1×13/P2×30+/P3 若干。
- **P0 全修**：webhook tenant_id 未定义先引用（leadgen 全断500）；fb.py write_log 未导入（改名/类型切换 NameError，FB侧已成功但审计丢）；权限退避标记非armed账户永不过期（止损无限期静默禁用，违反无保护期铁律）；前端归档参数 t 遮蔽 i18n（100%坏死）。
- **P1 全修**：TT 暂停 API advertiser_id 列表→标量（全链路40001）；限流令牌永不回池+回退绕过 tiebreaker；TG 1200 裸截断劈HTML→400 通知丢；页归属闸部分集合缓存→潜客永久丢；投放模板 CPA/Advantage 残留污染新模板出价策略；TT 冷却键跨广告主撞号；route_next 无效secret信息泄漏；Dashboard/LaunchTemplates 竞态与孤儿轮询。
- **复审抓回归2**（本批自引入）：TT 加白写侧无platform（读侧过滤后永不命中）；rule_pause_notified 标记键与 dedup 读键不同式（TT 每5min重发TG）——均已修；TG 400 降级纯文本重发根治截断家族。
- **剩余 P2/P3 全修**：batch_get 顶层error/get_paged 实际limit/fb去重按source/RLS set_config固化/usd_to_fb_amount缺汇率raise/config弱密钥默认门/ad_ops platform消歧/auth限速淘汰最旧/audiences update校验/zip炸弹限额/keepalive币种感知——24文件 ast.parse 全过。
- **性能**：kpi_mapping 60s 缓存（巡检每广告1查→每分钟1查）+写入失效钩子；前端 KeepAlive 失活暂停轮询/TgManager懒加载/竞态守卫×4。
- **未修记录**（外部依赖或 by-design）：debug_token 需 app token（观察项，watchdog 预警链在 BM 拥有 App 前不生效）；landing_events 热路径 ad→act 全表扫（有 30s 缓存样板可套，待事件量上来再做）；Guard.vue category 入库存 locale（跨语言协作项，需迁移改 key）；subcodes 无分页（量小）。

### 1:1 FB 三层投放模板体系（2026-09-08，8dd36ba/3591174/5f8a03d/fb71c47/40cf19c，迁移 0088）
- **用户需求**：FB 铺广告做成 1:1 FB 广告管理器的系列/组/广告，每个转化目标绑定对应模板（消息/表单），一次配置多次投放，参照 FBInsider 草稿树。两个决策点（AskUserQuestion）：激活语义=**默认暂停+节点开关显式激活**（整链开启才消耗）；batchGenerate 与结构模式=**合并（树内广告节点支持素材组，部署时每素材展开一广告）**。
- **数据层（0088）**：`launch_templates.structure` JSON 列（空=平铺模式全兼容，旧模板/TT 链路零改动）。形状与后端 `_validate_structure`/前端 `normalizeTree` 三方逐字段对齐：组{name,enabled,budget_usd,audience_id,optimization_goal,billing_event,audience_json,advanced_config,ads[]}、广告{name,enabled,asset_ids[],headline,body,cta_type,landing_page_id/landing_url,subcode_slug,message_template_id,lead_form_template_id,pixel_id,post_source,reuse_post_ref}。校验门：组≤10/每组节点≤20/每节点素材≤50/展开≤200/跟帖必单素材/占位符白名单。**平铺双写**：保存时第一组第一广告回写平铺列（旧读方不炸；asset 落库前查存在性防 FK 500）。
- **部署 runner（`_deploy_item_fb_tree`）**：每账户 1 系列→N 组→M 广告（素材组逐素材展开，广告名=素材名）；SimpleNamespace 节点视图复用全部 `_resolve_*` 积木（预算/受众/表单/跟帖/插值）；**组级预算 USD 按目标账户 currency+当日汇率换算本币**（`_resolve_budget_fb` 同管道，多货币自动转换）；节点空=回退模板级（表单/消息/落地，曾硬置0截断回退链已修）；文案=素材AI随机>节点>模板；子码逐节点解析+回绑；每广告心跳 touch 防 reap 误判。单广告失败 partial（`_apply_batch_result` 加 unit 参数，批量模式语义不变）。
- **激活/资金安全**：campaign 恒 ACTIVE；组开关→adset、组开+广告开→ad（关=PAUSED 建好待开）。四道闸：ABO 启用组预算求和>$5000 部署 400；预检 will_spend 横幅（展开口径，素材组按素材列名）+全暂停绿色提示；`_validate_tree_assets` 部署/预检校验素材存在/类型（删素材悬挂引用保存允许、部署拦）；retry 部分成功（有 campaign_id）拒整树重跑防重复广告。
- **守卫**：structure+platform=tt → 400（TT 本期不支持，仍平铺）；structure+DeployIn.asset_ids → 400（素材已在树内）。
- **前端（fb71c47，LaunchTemplates.vue +726 行 / launch.js +62 键×2）**：编辑器平铺/结构 radio 切换（TT 隐藏；平铺↔结构双向合成+确认防丢数据；新建 FB 模板默认结构模式，跟帖预填流保持平铺）；左树（220px sticky，<768px 堆叠：启用小开关/完备度圆点绿黄灰/复制删除/+组+广告/选中高亮）右表单（系列=现有区块 v-show 复用；组=名称/启用/ABO预算覆盖/受众库/优化目标覆盖；广告=素材单选+多选开关（≥2 素材组提示，reuse 强制单素材）/文案/落地页联动子码过滤/消息·表单模板按 objective 显隐/跟帖浏览选帖）；保存客户端预校验同后端口径+组预算 '' 净化为 null；部署抽屉树概览卡（N组×M展开/ABO 启用组合计/启用链路数/两口径确认弹窗）；预检 mode:'tree' 渲染（will_spend 红横幅/树表含预算 USD→本币/payload 样例复用）。
- **smoke（`_smoke_tree_tpl.py`，29 断言生产全 PASS）**：迁移列+GRANT(has_table_privilege 口径)/合法结构规范化回显（素材去重保序）/平铺双写/6 类非法拒绝/复制带树/ABO 求和 $5010 拦截/叠加批量拦/TT 拦/树预检（mode/adset_count/展开数=6/will_spend 空/本币换算 20→2000 minor/abo_total 停用组不计）/启用链路横幅列出。真部署（花钱）待用户授权后实测。
- **遗留（如实）**：组级 billing_event/audience_json/advanced_config 数据形状透传但无编辑 UI（空=回退模板级）；结构模板+首节点跟帖时部署抽屉按该帖主页预过滤账户（偏保守）；TT 结构模式未做（后续单独立项）。

---

## 2026-09-08 — 表单模板页 1:1 FB Instant Form 编辑器 + WhatsApp 消息模板类型（迁移 0090）

### 概述
用户需求两条：①表单编辑器重做为「左侧手机壳实时预览 + 右侧设置分区」的 1:1 FB 形态（预览按 config 实时渲染，FB Instant Form 视觉顺序）；②消息模板支持 type=messenger|whatsapp（WhatsApp 开场白+快捷回复），投放模板消息下拉透出类型 chip。未部署（本地 commit）。

### 变更表
| 文件 | 变更 | 验证 |
|---|---|---|
| `frontend/src/views/FormTemplates.vue` | 编辑器重构：左 342px sticky 手机壳（标题/描述/联系字段 chip 列（镜像 payload 顺序+「自动」标注）/逐题卡片（选择题=选项 pill、开放式=输入 mock）/提交钮/隐私链/感谢页区块（website/whatsapp 按钮 mockup））；右分区=基本信息/内容（提问方式 radio=新问题默认题型）/联系信息（姓名固定+电话/邮箱/城市+「更多字段」折叠）/自定义问题卡（题型切换+↑↓排序+增删）/隐私政策/感谢页（按钮类型三态 none/website/whatsapp，whatsapp=号码+消息模板下拉+「FB 侧后续接入」旁注）/高级（FB 专属：可见性/欢迎语/仅目标国家）；存量 config 无 button_type 时按旧语义推导 website；保存净化空问题/空选项；顺手修 2 个存量 bug（消息卡硬删按钮引用未定义 `m` + `msgs.value` 未定义） | build ✓；142 key 半接线自查 ✓ |
| `frontend/src/locales/views/formtpl.js` | 重写：+40 键×2（分区/题型/按钮类型/whatsapp/消息类型/预览），删 addOptionMakeChoice；zh/en 严格成对 | 运行时 vue-i18n 编译 284/284 PASS；en 零 CJK；键差集 0/0 |
| `frontend/src/views/LaunchTemplates.vue` | 消息模板下拉 label 加 [WhatsApp]/[Messenger] chip（模板级+树广告节点两处；不过滤类型——最小实现） | build ✓ |
| `backend/app/models/lead_form_template.py` | MessageTemplate + `type` 列（server_default 'messenger'） | py_compile ✓ |
| `backend/alembic/versions/0090_message_templates_type.py` | 迁移 0090：message_templates.type + GRANT 两角色 | py_compile ✓（链 0089→0090→0091 线性，0091 为并行会话所建） |
| `backend/app/routers/form_templates.py` | MsgTemplateIn +type 白名单校验（脏值回落 messenger）；_msg_dict/save/update 透传 type；deploy_form 感谢页按钮门（显式 website 才带按钮字段，存量 config 保持旧语义） | py_compile ✓ |
| `backend/app/routers/launch_templates.py` | 树 runner `_resolve_lead_form` 同款按钮门（防 landing_url 兜底把 whatsapp 选择变成 FB VIEW_WEBSITE） | 随并行会话 c9f7a36 入库；py_compile ✓ |
| `_scan_i18n.cjs` | 删过时 fixup（源码已修正为合法 `{'@'}` 串法，旧 fixup 反把扫描副本改出语法错） | 全量扫描恢复可用 |

### 部署链语义（如实）
- WhatsApp 感谢页按钮（thank_you_button_type/whatsapp_number/whatsapp_msg_tpl_id）**仅本地存储+预览**——FB leadgen_forms payload 不带（FB 侧需额外 API 字段，UI 旁注明后续接入）。两处 payload 构建点都加了门：显式选 website 才带按钮，whatsapp/none 不带（launch runner 的 landing_url 兜底也会被门拦下）。
- config 变更（含 whatsapp 字段）会变 config_hash → 下次部署重建 FB 表单（复用机制既有语义，按钮 NONE 时实际内容不变也会重建，可接受）。
- whatsapp 型消息模板现有消费者只有表单编辑器下拉；Messenger 投放链不区分 type（welcome_text/ice_breakers 结构相同，混用不炸但语义由用户自己把关——下拉有 chip 提示）。

### 生产环境变更
无（未部署、未跑迁移）。上线需：迁移 0090（注意 0091 由并行会话引入，alembic head 应为 0091）→ 后端 3 文件 → 前端 build+Pages。

### 复审结论（已知限制/风险）
- 表单编辑器双 mockup（抽屉实时预览/列表预览弹窗）为同构重复模板，改一处需同步另一处（模板内有注释标记）。
- 预览联系字段按本地镜像的 phone-first 国家表推导主联系字段，与后端 `_PHONE_FIRST_COUNTRIES` 是两份拷贝（后端改国家表预览会漂移）。
- 感谢页 WhatsApp 按钮是显式半接线（旁注声明），复审时勿当假实现清剿——是用户拍板的最小实现。
- target_countries 仍无编辑 UI（预览「自动」chip 依赖 config 既有值，通常来自 AI 生成时的 country 入参）。

### commit
- 本批：表单模板 1:1 FB 编辑器 + WhatsApp 消息类型（0090）
- launch_templates.py 按钮门随并行会话 `c9f7a36` 入库（并行会话宽 add 捎带，代码归属本批）

关联：[[form-templates-module]] [[tech-review-format]] [[i18n-system]]


---

## 2026-09-09 — 广告管理器表格/成效数据重构（用户要求收尾，未部署）

**状态：开发中保存，未完成整批上线定义。** 起点 daae3d7。用户因额度要求收尾并补文档，因此保留经过本地检查的改动，未上传应用代码、未重启、未部署前端。

- 合并三层表格，增加可选列和分层排序记忆、父层/账户搜索、面包屑、快照及过期标注，日/总预算统一空输入行内编辑；补预算未核验警告、批量结果明细和缩略图回退。
- 后端按平台/账户/广告聚合 FB 成效，与综合转化分列，返回单次成效费用和每行时间。结构真实采集时间写既有JSON；guard仅补更新已有表现快照的updated_at一行，不改资金执行链或schema。
- 线上旧版基线完整 ALL_PASS（含KPI 11项），临时分组和TG偏好finally恢复；本地Node4/4、Python数据断言2/2、py_compile、前端build、新增36条locale runtime compile通过。产物命中AdManager-TIaGBDbP.js。
- 全库locale扫描仍有5项存量告警；浏览器/窄屏和新版生产API对账、部署门检均未完成。历史 results_fb=0来源区分、跨父层搜索边界、批量后端逐项隔离、Live Verify层级语义、Breakdowns、实体行内规则等仍待续。不能宣称1:1完成或已上线。

文件级变更、操作记录、测试命令和下一步清单见 [本轮收尾交接](交接_广告管理器本轮收尾_20260909.md)。后续部署必须重新做备份和源码一致性检查，禁止直接上传本轮dist。


### 2026-09-09 补充：后续AI执行建议与1:1验收目标

按用户要求重写 `PROMPT_广告管理器重构.md`，将目标明确为FB广告管理器视觉/交互/真实数据/部署闭环，新增对标证据矩阵、推荐执行顺序、16项最低覆盖范围与严格成功定义；在本轮收尾交接追加历史0、reach去重、异目标成效汇总、实体规则范围等风险建议。代码检查点仍为f8dc294，应用代码与部署状态不变；本次仅文档更新。


---

## 2026-09-09 — 广告管理器深化批：FB口径可用标记 + 批量逐项隔离 + 细分(Breakdowns)弹窗（已上线）

**状态：已部署验证。** 基线 f8dc294（前一AI重构，未部署）之上深化，不推翻其工作。commit 8559b5c + 2eddb20。

### 概述
1. **FB口径可用标记**：`/ads/list` 每行新增 `results_fb_available`。0093 前（迁移 server_default=0）与 TT 行（报表 actions 非 FB 格式，恒 0）不冒充实测——前端成效(FB)列按缺失呈现 '—'，tooltip 指引看综合转化列。
2. **批量逐项异常隔离**：`/ads/batch-status` 单条失败/异常不拖垮整批；统一返回 act_id/node_id/level/success/verified；异常 rollback 后**重设 RLS 租户上下文**（set_config(is_local=false) 在事务内执行时随 rollback 回滚，曾致同请求后续查询静默丢租户——rls-setconfig-rollback-pitfall）。
3. **细分端点**：`GET /ads/insights/breakdown`（age/gender/placement），单广告 FB insights breakdowns 直连，60s 内存缓存 + refresh=1 绕过；date_from/to（time_range）优先，否则 date_preset 白名单；TT 账户 400。成效列走 resolve_kpi 同口径（objective 从 AdsCache campaigns 反查，不请求 insights 的 objective 字段——本代码库无此先例，guard/1.0 均从 campaign 节点取）。
4. **前端**：广告行「···」下拉新增「细分」（仅 FB 行）→ 弹窗维度切换(年龄/性别/版位)+刷新+表格；成效列缺失成因区分 tooltip（fbNotCollected vs fbMissing）；预算未核验换专用 budgetUnverified 文案（状态切换保留 fakePauseWarn 假停语义）。
5. **修复 locale 死代码**：`views/admanager.js` 曾有重复 zh/en 键（JS 对象字面量后者覆盖前者），budgetUnverified 实际未生效——已合并。

### 判定口径（availability epoch）
`_FB_RESULTS_EPOCH = 2026-09-08T16:00Z`（0093 部署时刻，0e1f61d 2026-09-08 23:46 CST）。行级：非零 → 可用；否则要求 min(updated_at) ≥ epoch（巡检每轮滚动刷新近 7 天行并 bump updated_at，故旧区间自然落入不可用）。父层(系列/组) AND 传播。**与用户口头 spec 的偏差**：原话"metrics_updated_at 非空则 true"在实现上是恒真（快照行 updated_at 恒非空，标记失去区分力），故改为 epoch 判定——语义仍是"有真实采集则 true"，并在 TT 行上显式恒 False。

### 生产变更
- 后端：ads.py（+guard_engine.py 1行 updated_at bump，随批上传）上传 /opt/toveads/backend，py_compile + from app.main import app 双门过，restart，health ok（v1.3.5）。
- 备份：/opt/toveads/backup_20260909/{ads.py,guard_engine.py}.bak。
- 前端：CF Pages 部署成功，tovaads.com 已服务新产物 AdManager-BICcs9Pv.js（HTTP 200 验证）。
- journal 干净（仅 gunicorn 重启 socket-close 噪音，无 traceback）。

### 验证
- node --test adManagerView.test.js：5/5（新增"采集前 0 值不冒充实测"）。
- _smoke_ad_manager.py（隔离 venv + 服务器）：3/3（新增 availability：旧零行/naive 旧零行/新 0 行/旧非零行/TT 行）。
- _smoke_ad_manager_live.py（服务器真实数据）：ALL_PASS——三层均带 results_fb_available；非零行必可用；09-02~03 旧零行全部不可用（128 行 min(updated_at)=09-03 < epoch，7 行非零）。细分端点真数据 SKIP（当前 cache 无 FB 广告——FB policy 限制未解，见 fb-business-policy-restriction）。
- 路由注册验证：无鉴权 curl /ads/insights/breakdown → 401（非 404）。
- i18n 门：zh/en 各 2931 键差集 0，en 0 CJK（layout.langToZh 一并修正）；剩余 4 项 BRACE 告警为存量合法转义。
- build 产物 grep 命中 insights/breakdown / results_fb_available / budgetUnverified / fbNotCollected 后才部署。

### 结论与遗留
- 资金执行函数（暂停/预算/删除）零改动，仅批量入口包异常隔离。
- 遗留：①细分端点未在真 FB 广告上跑通（账户侧无 FB 广告），FB 解封后需人工开一次弹窗验收；②跨 worker 的 LIVE_STALE_MARKS/refresh-status 进程内状态仍未修（沿用交接#7）；③浏览器人工验收（列记忆刷新/面包屑/窄屏）仍建议用户过一遍——本批已做代码级核对（curList 分层过滤/localStorage 键 admanager-view-v1 深度watch/潜客Tab完整/实时核验只 patch 广告层）。

### commit
- 8559b5c 广告管理器深化：FB口径可用标记+批量逐项隔离+细分弹窗
- 2eddb20 线上数据断言 smoke


### 2026-09-09 补充：创建与编辑配置及API可实现性规格

新增 [实施规格_FB广告创建与编辑_配置及API映射.md](实施规格_FB广告创建与编辑_配置及API映射.md)，涵盖三层面板、Creative对象、逐字段配置与API映射、网站/表单/消息/应用分支、编辑限制、受控验证清单及交给其他AI的提示词。只读核对本地v25.0构建器、模板和表单路由，以及Meta官方Python SDK源码；开发者参考页429已如实标注。明确SDK main不等于v25可用、Instagram身份键差异、现有构建器ACTIVE测试风险。文档结构、JSON示例和本地链接检查通过。无应用代码修改、无广告写入、无部署。

### 2026-09-09 批H：转化发生位置矩阵对齐 Meta 官方 + 管理器菜单顺序照 FB（已上线）

**概述**：合并《实施规格》与 Meta 官方转化位置矩阵调研（business/help/2035196643270 + AdSet reference v25 + Call Ads v26），修正三处错位、补一缺失位；广告管理器工具条与列默认顺序照 FB Ads Manager 重排；细分新增转化位置维度。完整对标矩阵见 [对标矩阵_广告管理器_批H.md](对标矩阵_广告管理器_批H.md)。

**变更**：
| 文件 | 改动 |
|---|---|
| backend/app/core/ad_builder.py | 销量移除单独通话位；流量 instagram_direct→instagram_profile（INSTAGRAM_PROFILE+VISIT_INSTAGRAM_PROFILE）；潜客 instagram_direct 优化目标 CONVERSATIONS→LEAD_FROM_IG_DIRECT；潜客通话位→QUALITY_CALL；OPT_GOALS_BY_OBJECTIVE/LOCATION 同步扩枚举 |
| backend/app/routers/ads.py | /ads/insights/breakdown 新增 dimension=conversion_location（action_breakdowns=conversion_destination；只拆成效，消耗/展示置空——与 FB 按操作细分同口径） |
| frontend AdManager.vue | 工具条重排照 FB（＋创建→账户→日期→筛选→搜索→列→⚡核验→跳转链接→缓存龄）；细分弹窗加转化位置（含中文映射+口径说明）；绿色创建按钮跳投放模板 |
| frontend adManagerView.js | 列默认序照 FB：成效→消耗→单次成效费用→预算→综合转化 |
| frontend LaunchTemplates.vue + launch.js/admanager.js | 矩阵镜像同步；文案官方叫法（转化发生位置/Instagram 主页/Instagram/通话/Facebook 公共主页）+3 个新优化目标标签（zh/en 成对，en 零 CJK） |

**迁移**：无 schema 变更。生产 182 个模板扫描确认 0 个使用 conv_location（批次I 昨日刚上线），矩阵收紧零存量影响。

**生产变更**：后端 restart（双门过）；前端 CF Pages 部署（构建产物 grep 验证含新代码后才上传）。

**验证**：_smoke_batch_h.py 33/33 ALL_PASS（矩阵自洽/新组合 payload/旧组合拒绝/回归）；adManagerView 5/5；health ok；journal 部署后零 err。

**结论**：A 级错位（销量假通话位/流量假 IG 私信/潜客 IG 错优化目标）已修；细分四维与 FB 按投放+按操作对齐；菜单顺序照 FB。多渠道合并广告组/组合位/应用/店铺维持缓项（矩阵文档 §3）。commit f17f02d。

### 2026-09-09 批I+J：成效口径按组优化目标 + 模板删除/上传（已上线）

**批I（P0 数据口径）**：生产实证——系列 Te（BSCH-TD-O324，OUTCOME_TRAFFIC）旗下 6 组全为 CONVERSATIONS/WHATSAPP（Click-to-WhatsApp），FB「成效」=WhatsApp 会话数（今日=1），旧口径按系列目标数成链接点击（=6），直接污染 CPA 止损判定。修复：kpi_resolver 新增 `_OPT_GOAL_FIELD_DEFAULTS` 确定性映射层（矩阵 obj|og 之后、objective fallback 之前：CONVERSATIONS→messaging_conversation_started_7d / LINK_CLICKS→link_click / LANDING_PAGE_VIEWS→landing_page_view / LEAD_GENERATION|QUALITY_LEAD→lead_grouped / PAGE_LIKES→like）；guard_engine 新增 `_adset_optgoals`（ads_cache adsets_json，零额外 API 调用）三处 resolve_kpi 调用点传组 optimization_goal；ads.py 细分/诊断端点同步。smoke（生产真实 acts 断言）8/8：CONVERSATIONS→1 会话、og 空=旧行为回归、系列汇总=FB 对齐 1。下一轮巡检（5min）起快照/管理器成效自动纠正。
**批J（功能）**：①已部署模板 force 删除——DELETE /{tid}/hard?force=1：job 行保留（template_name 快照在）仅解除关联，投放记录不丢；无 force 仍 400 拒删。smoke 5/5（临时模板+job 自建自清）。②投放模板素材选择器内直传：抽屉顶部「↑ 上传素材」（多文件，复用 /assets/upload 白名单+去重），上传完成自动选中新素材。i18n zh/en 成对。
生产：后端 restart 双门过 health ok journal 零 err；前端 CF 部署（产物 grep 验证）。commit b1aa032。

### 2026-09-09 批K：时间戳不被死令牌账户钉死 + 批I 重启事故复盘（已上线）

**批K**：/ads/list 的 cached_at/last_sync 与前端「缓存 X 分钟前」只统计令牌可用的账户——令牌断掉的账户 cache 恒冻结（拉不动），把它算进「数据更新至」会让整页时间戳被僵尸账户钉死（Roly-V21 令牌过期后页头停在 9/8 06:36，用户多次误解为系统不更新）。死令牌账户的冻结状态继续由行内「快照」标+顶部警示条表达；全部账户都死时回退全量。token_status 计算前移（cached_at 需要它）。

**批I 复盘（重启静默失败）**：批I+J 上传后 commit 命令在 toveads/ 目录下执行 `node _sshx.js`（模块在仓库根）→ Node 报错退出，但 git commit 已成功、错误被误读——**服务实际没重启，跑了 40 分钟旧代码**，成效口径修复延迟生效。教训已固化：部署重启命令必须与上传同 cwd 执行，且重启后用行为证据（journal 新行为/进程时间）验证，health ok 不代表加载了新代码。修复后 21:55 巡检实证：Te 系列 3 广告 kpi 全部切到 messaging_conversation_started_7d，系列成效 6→**1**（与 FB 一致）；广告实况 CAMPAIGN_PAUSED/DISAPPROVED，评估 0 为正确过滤非盲区。

生产：双门过、restart×2（21:49/21:50）、health ok；前端 CF 部署。commit 见 git log。

---

## 批O — 投放编辑器对齐 FB 操作逻辑（7 点）｜2026-09-09

### 概述
用户 7 点指令：①组预算放组里 ②主页不该在系列层、要能自动识别 ③像素要自动/随机/指定三态 ④落地页子码/广告ID参数/S2S/动态像素链路确认 ⑤真浏览器验证 ⑥整体对齐 FB 操作逻辑 ⑦复审到自认无问题。

### 变更表
| 文件 | 变更 |
|---|---|
| launch_templates.py（后端） | 树 runner 身份链：`_ad_page = anode.page_id ‖ item.page_id ‖ tpl.page_id ‖ 自动识别`（fb.get_pages 取首个 ADVERTISE task，非跟帖才自动）；out_ads 透传 page_id；`_resolve_tree_pixel(sdb,tenant,act,val)`——''=部署抽屉/模板默认、'random'=该账户已绑 LandingPixel 轮换、指定=直用；adset promoted_object.pixel_id 包一层 |
| LaunchTemplates.vue | 系列段主页行移除（FB 身份在广告层）；广告卡新增「身份」节：主页下拉（''=自动识别 + tplPages）；组卡像素改 el-select 三态（allow-create 保留手输）；browse-posts disabled 条件改 `a.page_id ‖ form.page_id`；openPostPickerForAd 同步节点→表单主页 |
| locales/views/launch.js | adPageLabel/adPageAuto/adPageHint/pixelAutoOpt/pixelRandomOpt（zh/en 成对）；treeBudgetOverride 改「日预算（本组）USD」；treeDefaultDailyBudget 改「ABO 兜底值」语义；treePixelHint 三态说明 |

### 链路核验（O4，代码证据）
- 子码自动生成：节点绑落地页未选子码 → `_create_auto_subcode` 每广告预留 LandingAdLink（先 commit 后调 FB，worker 可见）→ `effective_url={base}/a/{slug}?ad={{ad.id}}`（launch_templates.py:2694-2703）；失败降级直投+审计日志（不静默）
- 广告 ID 参数：FB 建广告返回 ad_id → `bind_link_ad_id(link, ad_id)` 回绑 + 广告名标 `[子码:{slug}]` + last-wins 守卫（:2773-2790）；手动选子码同构
- 动态像素：worker display 模式调 route_next（landing_events.py:335）→ pixel 优先级 = **adset promoted_object.pixel_id（ads_cache，即部署时真实写入 FB 的那个）** > LandingPixel by act_id > 页级——像素跟随部署选择动态解析，非写死
- S2S：TT Events API 默认开（tk_events.py）；FB CAPI 按像素 `fb_capi_enabled` 灰度（**默认 false**，同 event_id 浏览器端去重）

### 真浏览器验证（O5，Playwright 1.61.1 + Chromium 打生产 tovaads.com）
17/17 断言 PASS、0 JS 错误。流程：注入超管 JWT（addInitScript——hash 路由+模块级 _token 必须页面前注入，load 后 evaluate 无效）→ /#/launch-templates → 新建→Facebook 模板→目标弹窗(销售)→继续 → 编辑抽屉：系列 Tab 无主页字段+ABO 兜底值文案；组卡字段序=名称→转化发生位置→优化目标→转化事件→转化像素→预算类型→日预算（本组）→排期→投放方式（截图视觉复核）；像素下拉展开含 自动/随机轮换/像素库；广告卡 身份(主页=自动识别)+IG+素材+文案+落地页；/#/ad-manager ＋创建+「数据 X 分钟前」相对时间+无「数据更新至」页头。截图 _pw/shots/1-8。
验证脚本迭代修的 3 个自身问题（非产品 bug）：hash 路由导航、广告 Tab 需全标签匹配（'广告 Ad'，否则匹配到'广告组'）、像素选项在下拉需展开读。

### 复审（O7）
代码面：组卡像素 v-show=website（与 FB 仅网站转化位有像素一致）；跟帖模式不受自动主页影响（非 reuse 才 auto）；模板级 page_id 保留向后兼容。视觉面：截图逐张复核，视觉模型报的「素材：auto×3 重复」经 DOM 核实为误读（广告卡头无链路文本）。遗留已知项：部署真花钱链路（结构树真部署）仍待用户授权实测。

生产：批O 后端已随 1dd47e0 部署（双门+restart+health ok），前端 CF Pages 已部署。commit：1dd47e0（已推送）。

---

## 批P — Advantage+ 受众归位 + 编辑器降噪 + 数据龄双层 chip｜2026-09-09

### 概述
用户三指令：①Advantage+ 受众该在组里（验证 FB 管理器位置）+ 编辑器去花哨 ②数据龄 chip 按最优解（省 API）。

**FB 实况核实**：Advantage+ 受众开关在 **Ad Set 层受众区顶部**（开=国家/年龄/性别为基础约束+AI 扩展；关=原始受众完整手动定向，API=`targeting_automation:{"advantage_audience":0}`）。我们此前放系列 Tab 且**从未发过该字段**（纯 UI 摆设——本次一并修掉）。

### 变更表
| 位置 | 变更 |
|---|---|
| ad_builder.build_adset | 新参 advantage_audience=True；仅显式 False 发 `targeting_automation={"advantage_audience":0}`（FB 默认开=省略） |
| launch_templates 树 runner/树预检 | per-set `snode.advantage_audience`（仅显式 False 关）；平铺预检/ad_ops 平铺部署：`not flexible_spec` 启发式（手动兴趣=原始受众） |
| LaunchTemplates.vue | 系列Tab开关盒移除；组卡受众区顶部加开关（per-set）；开=兴趣行隐藏；advp 系列 chip 改派生（树=所有组全开）；树节点结构 JSON 加 advantage_audience（旧节点按"有手动兴趣→关"启发式回填）；平铺→树转换带入 |
| 风格降噪（18 处） | 信息类容器（advantage-box/saved-aud/reuse 卡/批量提示/结构树卡/msg-hint）蓝框蓝底→中性 --bg2/--bd；选中态 6 种浓度→统一 --acg；节标题去蓝→--t2；el-switch 3 处剥硬编码色。警告色（scat/aud-empty）与状态绿保留——语义色不删 |
| AdManager.vue | chip 改双层：「广告 X 分钟前 · 系列/组 Y 分钟前」——广告层=/ads last_sync（存活账户最新，巡检 5min）；结构层=存活账户 campaign/adset snapshot_at 最新（15min 同步）。不随 Tab 暗变、不取最旧行（修"14 分钟前"误解根因）；stale 判定挂广告层 |

### 结构最优解（用户拍板"省 API 不怕麻烦"）
保留 5min 巡检（广告层，花钱数据）+ 15min 结构同步（系列/组，变得少 99% 调用拉回一样数据），chip 双层诚实表达两层的真实新鲜度——既不浪费 API 也不误导。结构同步保持 15min 的另一理由：部署后已有即时 cache 刷新对账兜底。

### 验证
- 后端 smoke：build_adset 默认省略/显式关发 0/旧调用不变（TRAFFIC 目标）✓
- 真浏览器 7/7 PASS 0 JS 错：系列Tab开关已移除；组卡受众区开关在顶部（idx 18<受众来源 83）；开=兴趣隐藏/关=出现；chip 双层「广告 7 分钟前 · 系列/组 17 分钟前」；风格目检（中性为主、选中才蓝、无花哨色块）
- 已知项：平铺模式无开关（FB 默认开；有手动兴趣自动发 0）；树预检 payload 展示同口径

生产：后端 3 文件双门+restart+health ok；前端 CF 部署。commit fb64f36（已推送）。

---

## 批Q — 广告管理器 UI 降噪（对抗自查）｜2026-09-09

### 背景
用户二次点名"管理器 UI 太花里胡哨"——批P2 只做了投放模板编辑器，管理器本体漏了。对抗流程：真浏览器全景截图 → 视觉模型苛刻审查点名 → 逐项代码核实（剔除误报）→ 修改 → 重截图+颜色密度断言终验。

### 视觉审查点名 vs 代码核实
| 审查点名 | 核实 | 处置 |
|---|---|---|
| 创建按钮绿实底 | ✓ .create-btn success 绿 | → 主色蓝（全屏唯一实底主操作） |
| 状态筛选/日期选中实底蓝 | ✓ .ctrl-btn.on 实底 | → acg 轻tint+accent 文字（与编辑器统一语言） |
| 行名链接蓝×6 | ✓ .entity-name 全蓝 | → 白字 hover 蓝+下划线 |
| 落地页链接绿 | ✓ .lp success | → 链接蓝 |
| 跳转计数徽章实底蓝 | ✓ .rd-badge | → 中性 chip |
| 侧边栏选中蓝/紧急暂停红/角色橙 | 全局 chrome（非管理器文件） | 保留——语义/导航，改全站另立项 |
| 状态绿/警告黄/危险红 | 语义色 | 保留 |

### 终验（数据断言非目测）
可见实底蓝（bg=#0a84ff）= 创建按钮×1 + 行启用开关控件态×3；行名蓝=0/6；选中 chip 背景=rgba(10,132,255,.12) tint；绿色装饰文本=0。语义色只剩表格状态区。视觉复查评分 7.5→收敛"一屏一重点"。

生产：纯前端，CF 部署 ×2。commit 8c675c6 + 补充（entity-name）。

---

## 批S — 部署链落地页域名健康门（FB 侧）｜2026-09-09

### 背景
用户需求：落地页绑定的域名被 FB 封禁时部署应报错拦截而非投死链；多域名绑定自动切换健康域；部署触发时实时检测（TT 暂不做）。此前 FB 屏蔽扫描仅每小时看板告警，部署链完全不查。

### 实现（launch_templates.py，纯后端）
| 组件 | 说明 |
|---|---|
| `_fb_domain_probe` | 复用落地页自检的 `_fb_ban_probe`（Graph scrape，pass/warn/fail）+ url→结果缓存（item 内去重 FB 调用） |
| `_healthy_landing_base` | 域名池=custom_domain+custom_domains（归一 https:// 前缀，现状顺序）；首选 pass/warn→沿用（健康路径零行为变化）；首选 fail→依序探测备用取 pass（无 pass 用 warn）；全 fail→返回错误 |
| `_LandingBlockedError` | 全封硬拦异常——专门穿透自动建链的降级 except（降级直投=广告指向死链，比失败更糟） |
| 接线 6 处 | 平铺预检(400 预拦)、树预检(400)、平铺自动建链、平铺 base 兜底×2、树 runner base 缓存（`__BLOCKED__` 哨兵，整 item 失败）、重试路径 |
| 不误杀设计 | warn（无令牌/爬虫被挡/探测异常）一律放行——探测不可用不能挡部署；TT 部署链完全不走此门 |

item 失败消息示例：`落地页「RH-Signals US」所有绑定域名均被 FB 屏蔽（已探测 2 个），已阻止部署——请到落地页换绑健康域名后重试`

### 验证
- 批S smoke 6/6：①首选 pass 沿用 ②首选 fail 备 pass **自动切换**（goosvk6→marketbriefnow 实证）③全 fail 报错拒投（消息含页名/探测数/指引）④全 warn 不拦截 ⑤live 探测真实返回 pass（当前域名健康）
- 回归 154 断言全绿（tree35+I54+II35+III30）；双门过、restart、health ok

### 已知边界
已投出去的广告 URL 写死在 FB，切换只对**新部署**生效（老广告需人工重投）——这是 FB 侧约束非系统限制。

commit 43466f8。

## 批T：模板编辑器 UI 重构（2026-09-09）

### 概述
用户要求「完全不要现在 UI，突出和颜色不直观」——编辑器抽屉整体视觉重构：去 emoji 化、层级清晰化、选中态统一。视觉模型 6 项评估全达标（含补丁）。

### 变更
| 文件 | 变更 |
|---|---|
| frontend/src/views/LaunchTemplates.vue | 抽屉 680→760px；▶/▼ emoji 全灭→CSS border 画 chevron（.open 旋转）；字段行 label-top（标签小号 600 上置）；三层 Tab→分段控件（井底+选中浮起）；组卡/广告卡左状态条纹（3px，err 红）；卡头背景透明化+名字 600；转化位置→pill 按钮组（选中实底蓝白字）；节标题小型大写+虚线分隔；.t-op/.tdot 直角化去装饰 |

### 验证
- Playwright 真浏览器截图（编辑 US 45+ 卡→广告组 Tab）→ 视觉模型评估：宽度✅ 组卡干净卡头✅ 标签上置✅ pill 选中态✅ 整体克制无花哨✅；容器底短板项已补（井底 rgba(0,0,0,.22)+inset 描边，30cf6cf）
- 构建 ✓ / CF Pages 部署两次（916f9f1e / 855ae3ac）

### Commit
456d676（重构主体）· 30cf6cf（分段控件井底补丁）

## 批U/U2/U3：真部署链路四层根因修复（2026-09-09）

### 概述
用户真部署「US 45+ 购物通用」到 O322 连续失败。真浏览器+真 FB 重放二分定位出**四层叠加根因**，逐层修复后**全链路真跑通**（campaign/adset/ad/子码/回绑全成，广告 PENDING_REVIEW）。

### 四层根因与修复
| # | 根因 | 现象 | 修复 |
|---|---|---|---|
| 1 | `_validate_structure` 白名单漏 `advantage_audience` 键（保存时被未知键丢弃策略剥掉） | 编辑器开关永远失效 | 白名单三态保留（1b4ad31） |
| 2 | 树 runner/预检回退把「未设」当「开」 | 兴趣受众+Advantage+ 开 → FB 1870227 | 未设时按 flexible_spec 启发式（对齐平铺链） |
| 3 | **dev App 无 Standard Access → FB 强制 Advantage+**：年龄/性别/兴趣全拒，显式 =0 也无视（v19/v22/v25 同、O322/O324 同；纯 geo+ta=1 可建） | 任何经典受众字段 1870227 | `_post_adset_with_fallback`：1870227 自动降级纯 geo+Advantage+ 重试，item 留痕「受众被强制 Advantage+」 |
| 4 | 模板 advanced_config 残留 `{"is_dynamic_creative":true}` 经 extra 深合并进 adset | adset 建成但 ads 全灭 1885702（DC 组要求多素材创意） | build_adset 一律剥 is_dynamic_creative |

### 附带
- 批U2 像素自愈：库无该账户像素 → 绑账户既有入库存档 → 零像素自动建 Tova-*（实测 cred25 可建；FB 每账户限 1 自有像素 6200）。预检只读绑定不写 FB，占位符不再 400 硬拦
- 批U2修 RLS 坑：请求 session 上 commit 带走 SET LOCAL 租户上下文 → ObjectDeletedError；像素入库改独立 SuperSession
- 批U3b fb_client 错误日志带 raw message/error_data（翻译口径定位不了字段级问题）
- 排障方法论：FakeFb 捕获 payload → 真 FB 重放 → 字段二分（V0-V15/A0-A2/B1-B4），每变体建 PAUSED 即删零消耗

### 验证
- 真浏览器（Playwright+生产前端）：⋯菜单预检 200 → 部署抽屉选 O322 → 确认弹窗 → job success
- FB 实况：campaign 120252335778050220 / adset 120252335778560220 / ad 120252335779720220（名含 [子码:lt197-ad_2-6-2605-3]，configured ACTIVE，PENDING_REVIEW）
- 预检 payload：targeting_automation={advantage_audience:0} + 真像素 1394346206205535

### 遗留（已知未修）
- 用户主页 1302132919641404 对 cred25 无广告权限（3858749）——1302 需在 BM 给系统用户授权；自动识别选中的 1295587800300315 可用
- O322 孤儿系列 5 个（2×Tova Ads 空 + 3×RealDeploy3 各1 adset）待清理
- 精确受众（45+/男/兴趣）需 App Review 拿 Standard Access 后恢复——当前一律降级 Advantage+（有留痕）

## 批V：1870227 终版根因——targeting_automation 嵌套位置（2026-09-09）

### 概述
批U3 的"账户级强制 Advantage+"归因被用户实锤推翻（UI 一直能设 45+ 定投、App 是 Live+8 权限全批）。补全实验矩阵发现：ta=1+默认 18-65 可建、任何自定义收窄被拒 → 怀疑字段本身没送达。**FB 读回 targeting 时 `targeting_automation` 嵌在 targeting 内** → 验证嵌套发送 → V23 全量受众建成保真。

### 根因与修复
v23.0 起 `targeting_automation` 必须作为 `targeting` 的子键发送；顶层发送被静默丢弃，FB 默认 Advantage+=1 拒收一切手动收窄（1870227/1487079）。修复：`build_adset` 在 extra 深合并后写 `payload["targeting"]["targeting_automation"]={"advantage_audience":0}`（显式关时），开时清除残留键；`_post_adset_with_fallback` 降级路径同改嵌套。

### 验证
- V23 重放：嵌套 ta=0 + 45-65+男+4兴趣+FB/mobile/feed 版位 → CREATED，FB 读回一字不差
- 真浏览器全链路：模板 197 → O322 → job success → FB 读回 `age=45-65 gender=[1] interests=4 ta={"advantage_audience":0}`
- 附带清理：删错受众旧广告+5 调试孤儿系列；重部署广告 PENDING_REVIEW（configured ACTIVE，$288.88/天 CBO）

### 附加发现
- Playwright 选部署抽屉账户行：`.first()` 匹配 `.acc-list` 容器点中心=中间行（列表顺序会变→时好时坏）；正确做法 `getByText(act_id).locator('xpath=ancestor::label[1]')` + 选区状态断言（`.acc-row.on`）
- 读回 adset 时顶层字段 `targeting_automation` 不可读（nested in targeting）

## 批W：FB API 全面重审（官方 changelog 对照 + 真打实测，2026-09-09）

### 概述
按用户要求把全部 FB 写路径 × 现行 API 规则重审一遍（官方 2025-06 Advantage+ 行为变更博客 + 逐字段真打验证），修三类问题。

### 审计范围
ad_ops/guard_engine 保活/launch_templates 三处建广告链、build_campaign/build_adset/build_creative/build_lead_form_payload、adspixels、page_post(/feed /photos)、leadgen_forms(3 调用点)、leads 拉取、subscribed_apps、FB scrape

### 修复
| # | 问题 | 修复 |
|---|---|---|
| 1 | 非默认定向（自定义年龄/性别/兴趣/受众）下 Advantage+ 开（显式 1 或不发键）→ FB 拒（1870227/1870188 实测）；官方博客：非默认必须显式 0 | build_adset 终局规则：开关关**或** targeting 含任何非默认收窄 → 嵌套 advantage_audience=0；仅默认宽定向 → 1。双分支真建验证（45-65+男 → 0 保真；18-65 宽 → 1） |
| 2 | leadgen 表单创建从未真通过：questions 含非法键 name/placeholder（v25 #100 Invalid keys） | name→key；placeholder 剥除（编辑器本地概念）。**真建成功**（补 follow_up_url 后，v25 必填 FollowUpActionURL，部署链已传）；探测表单已归档 |
| 3 | leads 轮询对失效令牌账户每轮空打 N 次 API（journal 刷屏） | 权限类错误跳过本账户剩余广告（单条日志） |

### 实测结论（全部真建 PAUSED 即删，零消耗）
- T1b 开关开+自定义年龄：builder 强制 ta=0 → FB 建成，age=45-65 gender=[1] 一字不差
- T1c 默认宽定向：ta=1 → 正常
- T3 leadgen：修复后建成（1997233864326843，已归档）；API 不支持删表单（33），归档可用
- 确认项：guard 保活 payload 用默认 18-65 定向（自动 opt-in 合规，无需改）；copies/delivery_estimate 未使用

### 待用户侧动作
- **cred25 令牌缺 leads_retrieval scope**（App 已批但令牌未带；O322 自家广告读 leads 报 #100 Requires pages_manage_ads or leads_retrieval）→ BM→系统用户→重新生成令牌勾选 leads_retrieval，换进 2.0 后潜客轮询恢复
- page_post /feed 发帖需 pages_manage_posts（未在已批权限单里）→ 下一轮 App Review 补申请；现有 object_story_spec 内嵌链路不受影响

## 批X：潜客/webhook 断链诊断与补齐（2026-09-09）

### 诊断链（铁证）
- debug_token（app token 自查）列出 cred25 真实 scope=7 个：**缺 leads_retrieval + pages_manage_metadata**
- 根因不在 FB 侧（App 8 权限全过审，用户后台实况），在**我们 OAuth 授权 URL 的 scope 清单**：pages_manage_metadata 曾因未过审期 Invalid Scopes 被摘、leads_retrieval 从未入列——授权时没要的 scope 令牌永远没有
- 影响面（同一根因两条链）：①潜客拉取 GET /{ad|form}/leads → #200 Requires leads_retrieval ②页级 webhook 订阅 subscribed_apps → #200 Requires pages_manage_metadata

### webhook 链路盘点
| 环节 | 状态 |
|---|---|
| App 级 callback 配置 | ✅ api.tovaads.com/fb/webhook, active（GET /{app}/subscriptions 实证） |
| 端点公网可达 | ✅ 错 token 返回 403（行为正确） |
| X-Hub-Signature-256 验签 | ✅ app_secret 已存库，遍历 active App 比对 |
| 页级 leadgen 订阅 | ❌ 令牌缺 pages_manage_metadata（唯一断点） |
| webhook 收后回填 leads | ❌ 令牌缺 leads_retrieval |

### 修复
fb_oauth.py OAUTH_SCOPES 补 leads_retrieval + pages_manage_metadata（8 权限已过审，OAuth 放行合法）

### 恢复步骤（用户侧一步）
令牌页对 Kritins Rae 走「重新授权」（OAuth 现带全 scope）→ 新令牌替换后：leads 轮询/同步自动恢复；POST /leads/subscribe 订阅页 leadgen webhook

## 批Y：重授权后潜客/webhook 全链打通（2026-09-09 夜）

### 8 vs 9 权限之谜（用户问）
授权弹窗 8 个 = OAuth 主动申请的 8 个；第 9 个 `public_profile` 是 **FB 自动附加的默认权限**（不需申请、不在弹窗显示，但每个令牌都带）。debug_token 实测重授权后 cred25 = **9 scope 全齐**（leads_retrieval + pages_manage_metadata 均到位）。

### 全链验证（夜班实测）
| 环节 | 结果 |
|---|---|
| 新令牌 scope（debug_token） | ✅ 9/9 |
| GET /{ad_id}/leads（此前 #200） | ✅ 200（潜客数为 0 正常，无消耗广告） |
| 页级 webhook 订阅 | ✅ leadgen+feed 已订阅（subscribed_apps 读回确认） |
| webhook 回调验签+处理 | ✅ 合法 HMAC 模拟回调 200 EVENT_RECEIVED |
| App 级 callback | ✅ 早已配置 active |

潜客双通道（webhook 实时 + 10min 轮询兜底）全部在线。

### 新坑（追加到坑文档）
- 订阅字段带 `messages` 需 `pages_messaging`（未申请）——leadgen/feed 不需要；正式端点 leads.py 只订 leadgen，本来就对（测试脚本踩的）

## 批Z：转化闭环断裂修复——投放像素与落地页 fire 不同源（2026-09-09）

### 事故
真投广告花钱后被止损规则正确关闭（花钱零转化）。根因不是"没建像素"：广告组优化的是 Tova 像素（库随机解析），但**落地页 6 的 pixel_ids 是空的**——worker fire 的像素来自页自己的 LP_CONFIG/router_next，页没配就一个事件都不发 → FB 零转化 → 止损触发。投放链（给 adset）与落地页（给 worker）是两套独立配置，中间从没接线。

### 修复
1. **部署链回写**（launch_templates 树/平铺 runner）：解析出像素后 `_bind_pixel_to_landing_page` 写回绑定的落地页 pixel_ids（幂等，独立 SuperSession 防 RLS 坑，write_log 留痕）
2. **像素链插入页优先级**：节点 > 抽屉 > 模板 > **落地页已配像素** > 库随机 > 自愈建
3. **数据修复 LP6**：补绑 1394346206205535 + PUT 重发布（LP_CONFIG 是发布时注入，改库必须重发布；自检 pass，域名/子码不变）
4. **验证**：POST /landing-pages/router/next（worker 的真实取数端点）→ pixel_ids=['1394346206205535'] = 广告组优化像素，闭环闭合

### 坑（已记坑文档）
- display 模式像素在请求时经 worker→后端 router/next 动态下发（非烤进页面）——验证像素链路要调 router/next，别 grep 页面 HTML
- 落地页改 pixel_ids 后必须重发布才进 LP_CONFIG（worker 侧）；router/next 则即时生效

## 批AA：四项核查+LEADS E2E 测试（2026-09-09）

### 四项核查结论
1. **数据集空（用户报告，归因修正）**：router/next 像素解析第一优先级=ads_cache 反查广告组 promoted_object.pixel_id（非页配置）——beacon 显示 04:36 起 worker 一直下发正确像素（1394...）。真正断点=**旧发布页面模板缺 _d 像素解码段**（不执行 fbq）；批Z 重发布后实测带 _d 页面含 fbq×6。空数据集=修复前流量的历史遗留+广告 06:19 起暂停无新流量。批Z 的部署回写+页优先级仍有价值（页级兜底+配置一致性）
2. **子码**：功能全对（FB 链接完整/归因 ad_id 正确/beacon 记录）。格式=设计内语义 slug（lt{模板}-{节点}-{素材}-{账户尾4}-{序}，≤44 字符），与手动 6 位随机共存
3. **规则综合转化**：规则1 conversion_source=either 实测生效；空耗类 `conversions=max(FB转化,落地通过量,潜客数)`（guard_engine 330 行）。本次停广告判断正确：$27.13、5 点击、1 落地通过、0 转化
4. **FB 拉数实况**：$27.13 spend / 105 imps / 7 clicks / 0 conversion actions——与用户所见一致

### LEADS E2E 测试（①-④ 之②，全 PAUSED 零消耗）
模板 253 建成→部署→campaign/adset 走通→**广告创建被 FB 拦：主页 1295 未接受 Lead Generation Terms**（页面设置一次性操作，需页面管理员）。代码链路验证到此门为止，错误翻译清晰。**已清理**：FB 系列 DELETE、模板 253 硬删（job 解除关联）、无残留表单。LEADS 后续待用户在页设置接受条款后即可真跑。

## 批AB：令牌缩水事故——OAuth 加 auth_type=rerequest（2026-09-09）

### 事故
用户报告「组 120252336030520220 没有像素 Fire 不了」→ 排查发现组本身像素一直在（promoted_object 读回正常），真因是 **cred25 令牌从 9 个 scope 缩到 2 个**（只剩 pages_manage_metadata+public_profile）。FB 把无权限的 adset GET 报成「对象不存在」——**#200/#100 权限错误会伪装成 not exist**。

### 根因
用户此前重新授权过：已授权的 App 再走 OAuth 时 **FB 跳过权限确认页，按「用户当前已授予」发令牌**——用户在 FB 业务集成里收走过权限，令牌就缩水，且无任何报错。

### 修复
`fb_oauth.py` 授权 URL 加 `auth_type=rerequest`：强制 FB 重弹权限勾选页，缺的 scope 当场补回。用户重授权后 debug_token 实测 9/9 恢复。排障铁律入坑文档：**FB 报 not exist 先 debug_token 排除令牌，再怀疑对象**。

## 批AC：AdManager 广告组级「转化像素」列（2026-09-09）

### 背景
用户问「为什么前端我看不到像素」——后端 /ads/list 一直透传 adsets_json（含 promoted_object），但前端组级列没有像素列。

### 变更
- `adManagerView.js`：METRIC_COLUMNS 加 `{ id: 'pixel', label: 'colPixel', levels: ['adset'] }`；defaultColumns('adset') 含 pixel（默认显示）
- `AdManager.vue` metricText：pixel 分支解析 promoted_object（缓存可能存字符串形态，JSON.parse 兜底）取 pixel_id
- i18n zh/en：colPixel=转化像素/Pixel

### 验证（真实浏览器）
广告组 Tab 列头出现「转化像素」，Tova Ads 组1（120252336030520220）单元格显示 `1394346206205535`（= FB promoted_object.pixel_id）。注意：已保存过列偏好的浏览器（localStorage admanager-view-v1）默认不显示新列，需在「列」勾选或清偏好——normalizeViewPreferences 只滤非法 id 不补新默认。

## 批AD：部署抽屉加载提速 + 像素体检（2026-09-10）

### 慢因定位（比预估更深）
「部分账户的主页/像素仍在加载」的真凶不止无缓存——`/fb/credentials/{id}/pixels` 全量模式**先拉令牌下全部广告账户再逐户拉像素**：几百户令牌一次下拉 = 几百次 FB 调用。前端本就并行（forEach 不 await），瓶颈全在后端调用量。

### 变更
1. **pixels 端点加 `act_id` 单账户模式**（1 次 FB 调用；空=原全量兼容）：部署抽屉逐账户下拉改传 act_id
2. **pages/pixels 5min 进程内缓存**（`_ASSET_CACHE`，fresh=1 绕过）——主页授权/像素集合变化频率极低
3. **前端同令牌 pages 请求共享**（`_credPagesReq`，页面级）——主页列表是令牌级，N 个同令牌账户原先打 N 次同一 /me/accounts
4. **像素体检**（`POST /landing-lib/pixels/health-check`）：库里 active FB 像素按账户分组，逐账户拉 FB 实况 diff，不在实况集的标 `status='dead'`（random 轮换/_ensure_account_pixel 只选 active，死像素不再被选中）。**保守原则：令牌拉不动的账户跳过不标记**（拿不到实况不冤杀）。像素库面板加「像素体检」按钮（Landing.vue，120s 超时）
5. api() 超时参数透传到 POST/PUT/PATCH（此前只有 GET）

### 实测（生产，真 FB）
- pixels 单账户 0.44s；缓存命中 0.02s（20×）
- 体检：10 账户 12 像素全活、0 死亡、15 无令牌账户正确跳过

### 顺带回答（用户问）
- 空像素部署链：抽屉>模板>落地页像素>自愈（绑账户既有；零像素自动建 Tova-*，FB 每账户限 1 自有像素天然只建一次）；转化类目标必须像素，流量类不用
- 抽屉像素下拉是 FB 实时拉取（死像素不出现）；死像素风险在像素库（已由体检覆盖）

## 批AE：交互减 API 批（2026-09-10，双 agent 审计驱动）

### 审计
两 agent 并行：前端 16 视图冗余 HTTP 调用（Top 15）+ 后端交互端点 FB 直调（Top 10）。共同最大发现：**写响应已带完整对象却全量重拉**模式遍布两个最高频页面（同文件都有原地 patch 先例可照抄）。

### 前端（原地 patch / 并行 / 守卫 / 降频）
1. **AdManager**：batchStatus 按响应逐项 patch effective_status（省全量 /ads/list——全站最重 GET）；deleteItem 本地移除+级联（删系列连带组/广告）；mount 链 load()/loadRedirectMap() 并行
2. **LaunchTemplates**：saveTpl/copyTpl 用写响应原地 upsert/insert；archive/hardDelete 本地移除；openDeploy 三路 Promise.all（原串行 3 RTT）；素材选择器会话守卫（已加载不重拉全量 /assets）
3. **Tokens**：主页改名/改类目原地 patch（省抽屉 3-GET 重拉）；max-accounts 原地（照 changeTokenType 模式）
4. **Landing**：子码 target_urls 原地更新（省分页重拉）
5. **MainLayout**：通知轮询 30s→60s（visibilitychange 回前台即时补偿保留）
6. **FormTemplates**：AI 选素材抽屉会话守卫

### 后端（_ASSET_CACHE 扩展，均 fresh=1 绕过 + 写路径失效）
1. `/fb/credentials/{id}/assets`（令牌抽屉，原每次 4+ 次 FB）整响应 5min 缓存；rename/category/refresh-accounts 写入失效
2. `/fb/assets`（模板编辑器主页下拉，原每 cred 2 次×N）整响应按租户 5min
3. `/leads/pages`（受控视图，原 N_creds+N_pages≈15 次/打开）整响应按租户 5min；subscribe/unsubscribe 写入失效

### 实测
- assets 抽屉：2.3s → **0.025s**（93×）
- leads/pages：8-12s → **0.01s**（冷 worker 一次性填充；多 worker 各持缓存，≤1 冷/worker/5min）

### 未做（审计结论留档）
后端 #4 ads/refresh 按新鲜度跳过 include_ads（3→2 次/账户）、#7 resolve-post 帖子内容缓存、#8 diagnose 读快照；前端 #7 /auth/me 共享 store、#8 Dashboard 通知去重、#12 批量移除并发化、#13/#15 低频管理页——价值中低或改动面大，待后续。

## 批AF：四项大改（2026-09-10，双 agent 研究驱动）

### ① 数据龄双层统一（用户问"为什么广告 1 分钟/系列组 30 分钟"）
研究结论：巡检只写广告层，结构层由 15min cron 供数——分层是历史设计非必要。**方案 A**：guard 巡检顺带刷结构层（复用 `_sync_one` include_ads=False，函数级 import 防循环，try/except 隔离绝不碰止损主路径）；cron 撤 FB 部分（只剩 TT+停更探测）。成本 +16 次/h·账户（与提频 cron 相同）换结构层 5min 新鲜+并发自愈。前端 chip 简化为单层龄（取两层更旧者，cacheAgeSingle）。**生产验证**：FB 行结构层/广告层同一轮 5.0/5.1min。

### ② 换素材跟随（编辑器显示与部署结果不一致是主坑）
- 文案/标题「未自定义才跟随」：当前值为空或=旧素材 AI 首条 → 跟新素材（手改过永不覆盖）；树/平铺两模式
- 受众国家跟随：组内联受众国家为空或=旧素材国家集 → 跟新素材国家（受众保真）
- **AI 建议兴趣 chips**：组受众区展示素材 ai_audience.interests（自由文本），点击经 /audiences/search 解析成 FB 受众实体才入列——用户逐个确认，不自动注入

### ③ 规则引擎对齐 1.0 KPI 细化（agent 全量研究 1.0 rules.py/guard_engine 4333 行）
2.0 原有 10 类确认（研究纠正：trend_drop 已有、broader_conv 防误杀已有）。新增 4 类：
- `cpm_high` 展示成本过高（默认 spend≥$10 + CPM>$15 + 0转化，imps≥1000 防噪声）
- `cpc_high` 点价过高（spend≥$10 + CPC>$1 + 0转化，clicks≥20）
- `click_fraud` 刷量嫌疑（clicks≥100 且去重点击占比≤50% 且 0转化——总点击高去重低=同批人反复点；1.0 unique_ctr 信号维度重定义）
- `fast_scale` 激进扩量（1.0 原参数：0.7×目标/5转化/当日即扩/+25%，走通用 SCALE_RULE_TYPES 执行链）
insights 字段补 cpm/unique_clicks。Guard.vue 类型/参数/human 卡片/i18n/AdManager 诊断 RULE_ZH 全套。**smoke 8/8**（四类型正反用例）。
未做留档：账户级聚合规则、kpi_filter 按广告类型切片、reduce_budget 动作、静默时段（价值中低/改动面大，下批）。

### ④ 批AE 遗留清账（用户点名"价值低的也一起做"）
后端：_sync_one 广告层 <5min 跳过 /ads（3→2 次/账户）；resolve-post 帖子内容 1h 缓存（树编辑器逐节点解析不再重复打 FB）；diagnose 整响应 60s 缓存。
前端：Ads 批量移除并发化（5/批+成功本地移除）；Members 改角色/移除原地；Settings email-routing 删/翻转本地；Ads/Landing 超管标志读 localStorage（省 /auth/me）；LandingLogs/FormTemplates mount 并行。
未做：Dashboard 通知去重（需 store 重构，MainLayout 60s 已减半）。

## 批AG：权鉴修正——operator 数据/资源面全面隔离（2026-09-10，P0 安全）

### 事故（用户报告）
VV（operator，租户1）登录后：数据看板有全租户消耗、广告管理器有全租户广告；广告账户页却为空（该页有 owner 过滤）。三页口径不一致 = 权鉴漏洞。扩展排查发现投放模板/素材/表单/落地页/规则/受众库同样对 operator 全量可见。

### 根因
权限模型本意「operator 只看名下」（/fb/accounts 注释明示），但只有账户页实现了 owner_user_id 过滤；dashboard/ads/六类资源列表全部只按 tenant 过滤。另发现两处次生漏洞：
- **dashboard 30s 内存缓存键只含租户**：owner 的同参缓存结果会直接喂给 operator（缓存层泄漏）
- **perf 聚合 SQL 在无筛选时全租户聚合**：operator 空 act_ids 落入"不过滤"分支

### 修复（三道统一闸 + 六资源过滤）
1. `core/deps.py` 新增 `scope_account_query()`（账户查询归属过滤）+ `account_operable()`（单账户判定）
2. **数据面**（14 处）：/ads/list、refresh、live-status、breakdown、diagnose、写操作×6（status/batch/budget/delete/rename）、dashboard 主聚合、trend、ad_breakdown、export——operator 只看名下账户；名下为空时聚合强制空集（哨兵 act_id）
3. **看板缓存键加用户域**：operator 键含 u{id}，杜绝缓存串读；operator 名下为空提前返回空
4. **资源面**（7 处列表）：投放模板/素材/表单 forms+messages/落地页/规则/受众库——operator 只看自己创建（created_by/owner_user_id 列均已存在，唯 guard_rules 缺列）
5. **迁移 0094**：guard_rules 加 created_by + 回填租户 owner（迁移内联 UPDATE 未生效，已脚本补齐）；create 端点写 created_by
6. 引擎行为不变：巡检仍评估全部规则（团队安全网归 owner 责任），仅 UI 可见性隔离

### 实测矩阵（真 token）
- **VV(operator)**：9 类资源 + 看板全部 0/空 —— 14/14 PASS
- **owner 回归**：账户 7 / 广告 48 / 模板 / 落地页 / 规则 / 看板 $4228 —— 4/4 PASS
- **跨租户（租户4 owner）**：5 类列表无租户1行 + 账户交集空 + 看板正常 —— 7/7 PASS
- **email 唯一**：无重复（同名邮箱不可能两个账号）
- **越权写**：VV 对非名下账户 rename/delete → 404

### 模型说明（写给后续）
- owner/超管：全租户；operator：名下账户的数据 + 自己创建的资源；finance：billing + ads.read（无账户归属=看板空）
- 资源 create 时全部写归属列；巡检/cron 走 SuperSession 不受影响

## 批AH：规则按转化类型设阈值（kpi_scope）（2026-09-10）

### 用户澄清的真实需求
批AF 加的 CPM/CPC 规则不是重点——核心是「**不同转化类型的合理成本天差地别**（对话 $8 vs 购物 $40），要能按具体转化类型分别做规则」，一条规则一个阈值管全部类型必然误杀/漏判。

### 实现
- 规则 params 加 `kpi_scope`（购物/私信对话/线索/互动/流量，空=全部类型兼容存量）——存 params JSON 零迁移
- `_evaluate_rule` 开头按广告 resolved KPI 字段对 KPI_CATEGORY 分类过滤：类型不符直接不适用；KPI 未解析（未知）不适用（宁漏判不误杀）
- 工厂调用点传 `kpi_field=(kpi).kpi_field`（resolver 结果已在作用域，0 额外查询）
- 前端：规则表单「适用转化类型」下拉（阈值区上方，六选项）+ 编辑回填（从 params 抽出）+ 规则卡片 `[类型]` 前缀 + i18n zh/en

### smoke（6/6 + 2 修正用例）
对话规则命中对话广告、不误杀购物广告（CPA$50 也不停）；购物规则 $40 阈值 CPA$50 命中/$20 不命中；KPI 未知限定规则不适用；存量规则（无 scope）全类型照旧。

### 典型用法
建两条 cpa_exceed：`[私信对话] 目标$8×1.3` + `[购物成交] 目标$40×1.3`——各自只管各自类型。

## 批AI：跳转覆盖验证 + 跳转 UI 重排 + 层级状态联动（2026-09-10）

### ① 广告 120252336031670220 跳转覆盖端到端验证（真生效）
DB 覆盖行（WhatsApp 号）→ route_next 实测：带该 ad_id 返回 `mode=ad_override` + WhatsApp URL（最高优先级：广告级覆盖 > 子码专属 > 页轮换）；不带 ad_id 对照走子码默认。覆盖行更新即生效（router/next 每次点击实时查库，无缓存）。

### ② 跳转管理 UI 两处
- 工具条「跳转链接 N」角标：改自包含胶囊（inline-flex 居中 + 15px 定高 + line-height:1）——修数字 1 占满按钮（原 inline-block 行高继承按钮 32px）
- 管理弹窗行：长数字 ID 改双行卡（上行缩小 ID、下行域名短标如 api.whatsapp.com），URL 变主列弹性展示

### ③ 层级状态联动（FB effective_status 语义）
用户报告：广告停了但所属系列仍显示「投放中」。修：`childPausedMap` computed 按 ads_cache 三层数据推导——广告全停 ⇒ 所属组显示已暂停；组全停 ⇒ 所属系列显示已暂停。单向推导（父 ACTIVE 但子全停 = 实质停投才降级显示）；父已停/被拒等 FB 真实态不覆盖。开关仍控制自身配置态（父层开关打开不代表子层开）。状态筛选（已暂停/投放中）同步按推导态匹配。

## 批AJ：今日改动复审修复批（2026-09-10，agent 8 维度审计）

### 审计范围与结论
批AD-AI 全部改动（11 commit）。PASS 项：_managed_account 8 处替换全落位、__none__ 哨兵/_tnow 顺序、guard_engine _sync_one 线程 session 与时间戳解耦、kpi_scope 双重解析、迁移 0094 GRANT、created_by NULL 语义。发现 **10 类问题全修**：

**高危 5（权鉴/功能死）**
1. diagnose `_DIAG_CACHE` 键只有 tenant:ad_id 且缓存命中在归属检查前——owner 60s 内诊断过，operator 直接拿到完整面板（+ locale 互串）。修：键加 u{user.id}
2. diagnose TT 分支漏归属闸（FB 分支过闸 TT 沿用旧查询）；_managed_account 补 platform 过滤（双平台同 act_id 取错行）
3. ad_breakdown / dashboard_export「设 None 后继续执行」——operator 拿他人账户广告级明细。修：deny 直接 404
4. landing_overview 完全无 operator 过滤（落地/消耗全租户泄漏）。修：_op_own_acts 交集 + 空集哨兵
5. **前端层级状态联动两个 bug 导致功能全死**：集合存对象却按 id find（"[object Object]" 恒不匹配）→ 广告全停⇒组暂停永不生效；campaign 推导误写 adsetAllPaused 键 → 组全停⇒系列暂停永不生效。修：对象直存 + 键改写

**中危 5**
6. cpm_high/cpc_high 拿 FB 本币值直接比 USD 阈值（JPY 恒触发/EUR 漏触发）。修：to_usd 先折算
7. create_account_pixel 真建像素后不失效缓存（5min 内下拉看不到新像素）。修：drop(pixels=True, act_id) + fbassets 键
8. diagnose 评估未传 kpi_field——kpi_scope 限定规则面板按全类型评估与引擎不一致。修：补传
9. redirects 五端点零归属（map/list 全租户泄漏、reset 可清全租户）。修：归属过滤+闸+reset 限名下
10. 六资源写路径（改/删）只有 list 过滤——知道 id 即可跨用户写。修：require_owned 通用闸贯穿模板 7/素材 6/受众 2/表单 3+消息 2/落地页 6/规则 2 共 28 处

**低危**：landing operator 分支补排序+tenant 过滤一致性

### 实测（真 token，7/7）
VV 落地看板 0 消耗 / redirects map 0 / owner 三页回归有数据 / VV 改他人规则 404 / **owner 诊断热缓存后 VV 同广告诊断 404**（缓存不喂）。生产 health ok、巡检正常、近 2h 无新增错误。

### 教训（写入 memory 的根因模式）
- 「deny 后继续执行」「缓存先于鉴权」是权鉴修复批的同根遗漏——deny 必须立即 return/raise，缓存键必须含用户域
- 前端推导 computed 要有单测式冒烟（两个 bug 都是"看起来对但恒 false"）

## 批AK：六问排查与四修（2026-09-10）

### ① 「冤杀」文案——改大白话
像素体检的"不冤杀"= 技术注释口吻漏进了 UI。改为「{n} 个账户的令牌暂时用不了，本次未检查（不会误标失效）」。含义：令牌失效时拿不到 FB 实况，此时标记像素"失效"可能是错的（拿不到证据 ≠ 像素死了），所以跳过。

### ③ 批量部署 3 账户失败根因（探针二分定位）
逐层复刻昨晚 payload（campaign→adset→全字段含 45-65/男/7兴趣/手动版位/DC extra）在失败账户**全部成功**——payload 无罪。真因：**写令牌候选池（cred26 Gia Reyno / cred25 Kritins Rae）是外部 App 授权的 OAuth 令牌**（watchdog 同期 debug_token #100 "must be owner/developer of the app"），FB 对这类令牌的写请求报**裸 "Invalid parameter" 无 error_data**（权限错伪装成参数错，与批AB not-exist 伪装同族）。多令牌 RR 轮换：命中好令牌的账户成功、命中外部令牌的失败。
**修复**：部署 runner（主+重试两处）写令牌候选兜底——裸 invalid_param（无 error_data）自动 rollback 换下一候选整树重试。该类令牌建议后续在令牌页清理或重授权（本库 App=1583686816811436 签发的才有完整写权限）。

### ④ 管理器综合转化显示口径
conversions 列改 either=max(FB, 落地通过)——与规则引擎完全同口径（规则侧批AA 已验：landing_clicks 按 ad_id 精确归因+IP 去重，FB 回传延迟时用落地通过兜底不误停）。成效(FB) 列保持 FB 原值可辨。

### ② 系列名重名
树/平铺部署 campaign 名统一加日期后缀（MMDD）：`Tova Ads 0910`。前缀来自模板 name_prefix（建模板时填的），后缀之前没加。

### ⑤⑥ 无需改动
动态像素/S2S 已实证生效（昨日验证）；权鉴大白话解释见对话（VV=同团队 operator 只能看自己名下+自建，owner 全租户）。

## 批AM：五问处置（2026-09-10）

### ① 历史遗留账户的像素行——已一次性清 12 行
级联清理其实已上线（批299：unmanage 清像素绑定+TT file_ids；批300：删令牌清 token_health）。这 12 行是级联上线**之前**移除的账户遗留的。已删。顺带审计：子码无孤儿、ads_cache 2 行属软删设计内（历史保留）。

### ③ 重试 500 无详情——StaleDataError 已修
根因：retry_item 里 job ORM 对象 commit 时 UPDATE 0 行匹配（后台 reaper/并发请求已动过该行，内存对象谓词失配）→ 500。修：job 状态/心跳更新改原生 UPDATE（幂等无版本谓词）。「Facebook 返回错误」无详情 = 外部 App 令牌的裸 Invalid parameter（批AK 根因），换令牌兜底已在。

### ③' 为什么会用外部令牌
写候选池按「绑定优先+RR」排序，两条令牌（cred25/26）都是用户 OAuth 授权进来的——FB 上一个用户可给多个 App 授权，授权时选了别的 App（22 manager 时期授权的），token_source=oauth 但不是本 App 签发。候选池不区分 App 归属，轮到它就失败。批AK 兜底（失败换下一候选）已上线；彻底除根 = 这两条令牌用本 App 重新授权或删除。

### ④ 综合转化口径——改为访问量（用户定义）
管理器 conversions = max(FB, 落地访问)；「落地通过」列（点击量）默认展示于广告层。规则引擎 either = max(FB, 访问, 通过, leads) 同步。220 广告实测：今日 19 visit + 2 click（去重）——管理器现在显示 19。

### ⑤⑥ 爱尔兰直跳 + O337 之谜——完整时间线取证
爱尔兰那条 click（id 14188）前后事件：21:25:35 Boardman×2 block（FB审核爬虫被拦）→ 21:26:08 同一秒 5 连 US visit（Springfield/Gallatin/Social Circle，**全部 ASN 32934 = Meta**）→ 21:26:25 IE Clonee click（**也是 ASN 32934**，Clonee 是 Meta 爱尔兰数据中心）。
**结论**：这是 **FB 广告审核机器人的同一个会话**——Meta 集群内部 IP 池出口轮换（US→IE），它加载了落地页（US 出口时过白名单），然后在页面上点了 CTA（审核必做，验证目标页），click beacon 记录的是当时的 IE 出口 IP。「只有点击没有访问」因为 visit beacon 在页面加载时已用 US IP 记了（就是那 5 条）。**防护没洞：worker 层白名单工作正常，IE 出口的直接访问会被拦。**
**O337 纠偏**：我上一轮说错了——O337（=1052568664219129，就是部署成功那个账户）事件 8 条**全部带广告归因**（has_ad=6 visit + 2 click），不是爬虫无归因。它进的**落地页本体**（decision=display，非屏蔽页）。「全是爬虫」的印象来自日志来源标签把 Meta IP 集群标成"Facebook爬虫"——那是 FB 审核流量（真人流量未起来前先到）。

## 批AO：综合转化真人口径 + cred25/26 疑团终审（2026-09-10）

### ① 综合转化=真人落地访问（爬虫/审核机器人不计）
用户定义收紧：只认真人从广告进入的。新建 `core/landing_source.py`（11 个 UA token + AS32934 单一清单），四处消费同源：landing.py 日志归因 / ads.py 管理器聚合(_agg_cached) / ads.py 诊断面板(landing_clicks+landing_visits) / guard_engine 规则口径（爬虫访问不再豁免空耗）。诊断面板顶层综合转化从点击口径对齐为访问口径（每条规则仍按自身 landing_metric）。
实测（9/9-9/10 窗口）：广告…1670220 访问 19→8（11 条爬虫剔除）、通过 2→1；O337 批次 7 条广告访问 2-4 条/条 **全部是爬虫**（剔后归零——用户「全是爬虫」直觉正确）。

### ② 「前端没改」根因：批AM 带病 commit
adManagerView.js `defaultColumns` 少收尾 `]`（PARSE_ERROR）——批AM 起前端 build 即失败，**批AM/AJ/AK 的全部前端改动从未上过 CF**。已修复并重新 build+deploy（含 landing_pass 默认列、conversions 列 hover 口径说明）。教训：前端 commit 前必须过 build 门。

### ③ cred25/26 终审：不是 22manager 残留（纠正批AK「外部App令牌」误判）
铁证：①fb_apps 时间线——22manager(id=1) 07-30 已删，Tova Ads Manager(id=3) 08-05 起唯一 active；②OAuth code 兑换必须用 active App 的 client_secret（FB 校验 code 与 App 配对），09-07/09-09 建的 cred25/26 只能是 app 3 签发；③两令牌前缀同为 EAAWgWtImyawBS=同 App。批AK 的「外部App」证据（debug_token #100）实为自检限制：非 App 开发者用户 token 自 inspect 恒 #100（permission_snapshot=None 同理，所有 oauth 令牌皆然）——当时批量部署失败的真因是 BM/主页权限墙（用户已修）+ targeting_automation 嵌套（批P1 已修），候选兜底重试保留作安全网。两条令牌各绑 5 个 active 账户=正常在用，无需清理。

### 部署
后端 4 文件（双门+restart+health OK）+ 行为验证（新模块加载+新旧口径对比 SQL）+ 前端 build✓ + CF deploy。commit：b49dffe、a5de053。

## 批AP：部署重试彻底修复（本人 E2E 实测）+ Watchdog/OAuth 令牌检查修正（2026-09-10）

### ① 重试"失败无原因"根因链（全部修复+实测）
- **卡死态**：09-09 job32 重试时 item33/34 的后台任务没执行（无任何日志），item 永远 pending、error 空、按钮消失=用户看到的"失败没具体原因"。修复：retry 端点放行回收终态 job 里的 pending/creating 卡死行（claim WHERE 扩三态+清 error_code）；前端对卡死行显示重试按钮（带说明 tooltip）。
- **提前关门**：并发重试时先结束的 item 无条件把 job 标完（succeeded/failed 计数器还会互相丢更新）。修复：`_close_job_if_done`——按 items 表 FILTER 聚合收口，无 in-flight 才关；替换 _retry_one 全部 5 处收口点。
- **autoflush 坑（实测抓到）**：session autoflush=False，item 终态在 ORM 内存、聚合 SQL 读 DB 旧值→误判 in-flight 永不收口（item34 终态但 job 停 running）。修复：helper 先 flush。
- **静默 return（不静默铁律）**：_retry_one 模板/item 查不到直接走人→item 永远 pending+job 永远 running（部署 409 锁死）。修复：落 fail 带原因+收口。
- **僵尸自愈**：既有 _reap_stale_jobs（10min 心跳+5min 巡检）实测 23:32:15 正确回收 job32。

### ② 本人 E2E 实测（零 FB 写入/零花费——三账户本就无写令牌）
铸 owner JWT→POST retry item33（200，僵尸回收✓）→立刻得明确原因「act_1381683294159318 未绑定写令牌」；等 reaper 回收 item34（✓ 日志为证）→再重试 item34（200✓）→同因明确报错；flush 修复前抓到 job 停 running→修复后直接调 helper 收口成功（partial_failed 1/3）。

### ③ Watchdog debug_token + OAuth 权限快照（App 令牌 inspect）
自检 debug_token 对非开发者用户令牌恒 #100：Watchdog 每 5min 误报"token debug 失败"（cred25/26）且过期预警全瞎；OAuth callback permission_snapshot 恒 None。修复：新增 `core/fb_tokens.active_app_access_token` + `core/fb_client.debug_token_with_app_token`，两处改用 App 令牌 inspect（无 App 配置时 Watchdog 退回 /me 存活检查）。实测 cred26：**app_id=1583686816811436（Tova Ads Manager，22manager 疑团又一实锤）**、valid=True、9 scopes。今后重新授权即存快照。
探针还抓到 FbApp import 路径错（models/fb_app 非 models/fb）——import 门测不到函数内 lazy import，运行时探针的又一次价值。

### 部署
后端 3 轮（双门+restart+health 全绿）+ 前端 CF。commit：3ae7c15、4c6f8a5、(flush 修复)。

## 批AR+批AS：素材文案联动 + 全站真人口径 + 时区修复（2026-09-10，3 Agent 并行）

### 批AR 素材↔文案联动（Agent④改/主会话复审）
现状核实：批AF 只做了前端「未自定义才跟随」，下发端多素材从未按素材分流。修复：①换素材立即跟随新素材 AI 文案（手改被覆盖时 toast 告知；无 AI 文案素材不动）②多素材各用各的：批量（series_name 非空）/树素材组节点（len>1）/TT 批量=素材 AI 优先，模板/节点文案只兜无 AI 文案的素材 ③三处预检样例与 runner 同口径。单素材维持手填优先 WYSIWYG（表单显示什么发什么）。

### 批AS 全站落地指标真人口径（Agent③改/主会话复审）
落地页卡片/子码统计/看板（overview+趋势+屏蔽分布）统一：访问=visit+redirect，通过=click+redirect 按 ip 去重，爬虫/审核机器人剔除（core/landing_source 单一清单）。顺手修短链（redirect 模式）访问计数恒 0 缺口；前端标签统一「通过」术语+hover 口径提示；i18n 补 en 缺失 key。

### 批AS 时区表达式修复（Agent①取证实证）
landing_events.created_at（timestamptz）双重 AT TIME ZONE 实际算出 UTC-8h 日期：北京时间 0~16 点的落地访问全错进前一日桶、当天巡检数不到（广告 220 的 4 访问实测落错桶）。guard 规则/诊断面板/看板趋势三处改单次转换。验证：新分桶 09-10=7 visit 行（旧代码会把其中北京时间 0-16 点的扔 09-09）。

### 部署与验证
后端 6 文件（双门+restart+health）+前端 CF。验证：/ads/list 广告 220 综合转化 8=访问 8（出口覆盖修复未回归）；落地页 page6 真人访问 8/通过 1/屏蔽 102（口径生效）；子码今日统计正常。commit：e812d42、5cf9896、6b1584f。

## 批AT-AZ+BA：部署链五连修 + 真FB下发验收 + 残骸清理（2026-09-10 深夜）

### 根因链（每层服务器实测钉死）
① 假兜底(批AU)：_write_fb_with_fallback 去重读 f._access_token(属性名是 token)→候选恒空→所有「未绑定写令牌」
② 检测误杀(批AT)：令牌页检测用自检 debug_token(非开发者恒#100)→把有效令牌判 expired——用户两条令牌"突然失效"真相；重授权后新令牌快照已存(App令牌 inspect)
③ 错误裸奔(批AZ)：error_user_title/msg 被吞成「请求参数错误」→现在直接显示 FB 人话(如「Pixel 无法使用」)
④ 像素无权 1487429(终根因)：重授权新令牌用不了模板引用的共享BM像素→adset 全拒；**像素自愈**：撞 1487429 自动换账户可用像素重试+留痕+落地页回写
⑤ 路径分歧(批AZ补,用户实测发现)：平铺/手动/批量的 adset 裸 POST 无任何降级(手动能成批量死的根源)→1870227+1487429 自愈下沉 core/ad_ops.post_adset_resilient 全路径统一
+ 限流 subcode 2446079 分类(部署清单「Facebook 返回错误」→人话)

### 验收（用户标准：任务成功下发 FB+亲眼读回）
item36 重试 → job33 completed 1✓0✗：campaign 120251523565770604 + 6 adset + **6 广告**(FB 实读,PENDING_REVIEW/ACTIVE,子码自动建链 lt197-*)；像素自愈×6 留痕。

### 残骸清理（用户指示）
归档 8 个测试系列：O337×2(含验收系列=同时消除花费风险)、O339×5(Tova Ads×3+probe-tree×2)、O338×1；保留厂商 M-SALE 系列+用户 O340 手动部署。探测像素 1376744804140068 删除失败(需像素属主权限,无害遗留)。

### 其他
「只有系列没广告」=今晚调试打满 O337 API 配额→ads_cache 同步失败,限流恢复后 15min cron 自动补;commit: d1d595c/8682fb4/9f4d6a0/940cf2b/d30112c

## 批BC-BG：部署UI精细化 + 文案/状态修正（2026-09-10）

- **批BC** 部署 UI 精细化（Agent 改/主会话复审）：进度弹窗五列网格（真实账户名+ID 两行/统一徽标含卡死橙标/创建物系列组广告 ID+子码计数/原因分级显示/重试）、汇总条（#job+状态+计数+耗时实时+最近执行/完成时间）、部署抽屉 grid 对齐+可用额度列、已部署清单同款网格+广告 ID 复制、部署历史加时间四件套、--font-mono 全站 mono 真相源+tabular-nums、修提示被 generic 翻译掩盖 bug（auto_subcode_degraded 显原文蓝提示标；未知 code 不译不兜底）。commit 39cc81b
- **批BE** 像素自愈文案『模板像素』→『所配像素（模板/落地页）』。d800065
- **批BG** ①系列层全停判定改用电组生效态（原生 status 不随广告停导致广告全停后系列仍显示投放中）+状态开关同步生效态 ②删「综合转化（访问）」列（后端口径保留给规则引擎）。4ebf319+测试对齐（列迁移漏更断言，5/5 绿）
- 备份：toveads_db_20260910_0151.dump.gz（1.7M 可读）

## 批BH：落地页模板体系改造 + 交叉审核（2026-09-10）

六项：①默认模板 FB 侧像素/转化 fallback 补 (_d)?[] 守卫（注入脚本 _d_decode 对 _d 流量 PageView+CTA 转化全 fire，模板不守卫=双发数据翻倍；TT 历史有守卫 FB 漏——同文件不对称即 bug；实现 Agent 正确拒绝任务书里仍会双发的 (_info.p) 公式改用 (_d)?[]）②参考模板重写（守卫范式+README 五章）③上传校验 warning 四检测（资源文件不上线/硬编码像素含 TT C 前缀/写死外链排除占位符/缺 TT 占位符）+supports_tt ④error 级入口精确匹配（根目录 index.html，index.htm 不再认——行为收紧已知）⑤前端诚实化（去 n 资源炫耀/警告逐条 toast/含资源文件标签+tooltip）⑥spec 追加更新段。
服务器真实代码路径 smoke 全绿：坏 zip 恰 4 警告/参考 zip 2 文件 5 守卫 7 占位符/回传恰 1 警告(README=资源)/好 zip 0 警告 supports_tt/子目录 400/SMOK 模板已清。commit 6ab30cb。交叉审核（独立 Agent 零起点核对）进行中，结论见后续。

### 批BH 交叉审核结论 + 全部修复（同日）

**独立交叉审核（Agent 零起点核对，本地=生产 md5 一致）**：6 项需求 4✅2⚠️；三流量推演确认守卫语义正确（有效 _d 单轮带 eventID/直访单轮/畸形 _d 零轮零报错）。抓出：
- **P0-1 存量模板 RH-Signals(模板#2/页#6)线上双发（正在发生）**——已修：模板 html 补守卫（2 处占位符行+注入 _d 定义）+ 页 #6 重发布，线上实测 `?_d=` 数组为空 ✓；顺带清掉探针期间误绑页 6 的测试像素 1376744804140068
- **P1-2 TT 硬编码像素正则对真实 ID 恒不匹配**——已修（C 前缀+字母数字）
- **P1-3 上传 raw fetch 缺 X-Locale（英文界面收中文 warning）**——已修（3 处）
- **P2-5 缺守卫无检测**——已修（第 5 条 warning，新人删守卫行当场提示）
- P2-4 index.htm 收紧（已接受）/P2-6 点击选择器过宽（既有，记录）/P2-7 spec 旧段小误（新段已覆盖）
审核终答：处理 P0+P1 后，参考模板→改→上传链路对新人闭环安全。commit 4855e54。

### 批BI：注入脚本点击判定修复（P2-6 升级处置，2026-09-10）

交叉审核 P2-6 实测比报告更糟：once:true 在**任意点击**（含非链接空白处）即消耗监听→真 CTA 点击全丢转化+丢 click beacon。修复：FB/TT 两注入脚本改「仅 CTA 命中才 fire + 手动 _fired 开关（非 CTA 点击不消耗）」；CTA 判定 = goNext/#cta 或链接 href 指向目标 URL（去 query 比对，__lp_target 兜底 LP_TARGET_URL，无目标时保持宽匹配防漏报）。注入 JS 提取 node --check 双过；页 6 重发布线上验证 _isCta 在/once:true 无。commit 35560a5。

## 批BO：视频缩略图必填补齐 + 系列名唯一化（2026-09-10）

① **视频缩略图**：FB API 建视频创意必填 video_data.image_hash——缺失=「缺少视频缩略图」整广告被拒（用户 12 条视频广告全失败实证）。新 ad_ops.ensure_video_thumb_hash：ffmpeg 抽首帧 JPG 落盘 .thumb.jpg（一次抽取多账户/多部署复用）→ 按账户上传 adimages 拿 hash（缓存 fb_image_hashes）→ build_creative video_data.image_hash。三部署链路（树/平铺批量/重试）全接线。两个 smoke 抓的坑：上传文件名必须 .jpg（带视频的 .mp4 名 → FB 拒参数错）；探针进程需完整模型注册（FK 解析）。终版 smoke：真实视频素材抽帧 39KB → hash 387a6eff… → creative 结构验证 PASS。
② **系列名唯一化**：MMDD → MMDD-HHMM+4位随机（同模板多次部署/重试/多账户都不重名）；树+预检两处同步。commit eec6a9a + 文件名修复。

## 批BP：613 并发限流人话化 + 系列层「访问/通过」列（2026-09-11）

① **613 错误分类**：用户批量启动广告撞 FB #613（subcode 4841018，写操作 30 秒窗口并发限流），此前落 generic 显示英文原文。FB_ERROR_MAP 加 613→rate_concurrent；_classify_write_error 加 613 分支（注意 subcode-first 取到 4841018，code 须另查 e.raw）；useFbError/zh/en 同步译文。被拒那次调用未生效（UI 失败行保留勾选便于重试），等 ~30s 重试即可，非数据/逻辑问题。IN_PROCESS 警告=FB 暂态（状态已写入、生效态传播中），非错误。
② **系列层「访问/通过」列**：ads.py 批AQ 块扩 rollup——子广告 landing_visits/landing_pass 按系列聚合（与综合转化同 key 口径）；前端列 levels 扩 campaign、默认列加入、_COLS_MIGRATION v3 给已保存配置补列；排序/合计行自动生效（sumMetric 白名单已有）。无子广告行的系列显示 —（缓存广告层未含，诚实缺省）。
smoke（服务器真码直调 list_ads）：19 系列 78 广告，5 个有数据系列 rollup 全对（如 访问=13 通过=4），广告层总和 61=系列层总和 61，真实失败 0；单测 5/5。
commit 2067608。部署：后端 3 文件双门+restart+health 绿；前端 build✓+CF master。

## 批BQ：部署进度透明化——卡住不再是黑盒（2026-09-11）

背景：用户 12 广告树部署跑 1 分钟全程只有「creating」转圈被判「卡住」（真实原因=主页绑定 1815645 全拒，但过程中不可见）。落地：
- **迁移 0095**：launch_job_items 加 progress 列
- **runner 分步注记**（_item_note：原生 UPDATE 写 progress + touch job/item 心跳，防 StaleDataError）：树链「创建系列→组 i/N→广告 k/M：素材名」；平铺/单模板链「系列 i/N」「素材上传/缓存」（视频上传长步骤）；TT 批量同款。终态 _apply_batch_result 写「完成：成功 X/Y」
- **_item_dict** 回传 progress + updated_at（心跳时间戳）；retry 抢占与回收器清 progress 防残留
- **前端**：creating 行实时显进度 + 「· Xs 前」龄；超 2 分钟无更新橙显「进程可能已中断（如服务重启），稍后自动标记失败可重试」；成功行显终态汇总
- **部署 SOP 强化**：restart 前必查 launch_jobs 在跑任务（本次批BP restart 杀掉用户在跑部署的事故防再犯，已入 auto-memory）

smoke：DB 写入/还原 ✓、fresh 查询（=get_job 真实路径）回传 progress/updated_at ✓、迁移列存在 ✓、health 绿、前端 build✓+CF。commit aeff0d0。
坑：探针先载 ORM 再原生 UPDATE 会读到旧快照——端点是写入后新查询，无此问题。

## 批BR：像素统一链——优先账户自有像素（2026-09-11）

事故：…142(BSCH-TD-O324) 部署成功但广告投放被拦——adset 用了落地页#6 第一个像素 1394346206205535，令牌可见创建不报错，账户未被 assign 投放侧拦截（「部署成功广告失败」静默雷；1487429 创建自愈因此不触发）。
用户拍板策略反转：**优先账户自己能关联到的像素**。落地 `_pick_group_pixel`（canonical，树/平铺/预检三链统一）：① 显式指定（节点>抽屉>模板）且 ∈ 账户像素库 → 尊重；② 账户库内随机（批O-3 分摊沿用）；③ 库空 → _ensure_account_pixel 拉 act/adspixels 入档（零像素自动建，预检 allow_create=False）。无权自动换+留痕（auto_warns+progress 注记），真无解 fail-fast 人话报错。选中即回写页 fire（追加不顶——主像素继续收全量事件）。
副产物：①预检与部署像素口径拉齐（此前预检库优先/部署页优先，所见非所发）；②像素库探针垃圾像素 1048060468035628(toveads-probe-delete-me) 标 inactive（曾在 …142 库内被随机选中）。
smoke（服务器真库）：…142→1065622819185646+换痕 ✓；…2605 有权集内 ✓；显式无权→换+痕 ✓；显式有权→尊重 ✓。commit e32e6ca。

## 批BS：运营三页 UI 升级——投放模板/表单模板/素材库（2026-09-11）

用户反馈「总体简陋」+ 点名隐藏按钮取舍。落地（延续批P2 干净降噪基调，靠层次感不加装饰）：
- **卡片升级（三页）**：hover 边框亮+阴影+上浮 1px（.15s transition）；卡片分区间距节奏统一（gap 6→8、ops 区 margin-top:auto 沉底）；meta 行 chip 化（新全局 .meta-chip/.meta-chip.accent 进 main.css，两主题自适应——目标/预算/问题数/语言从纯文本变细边框 chip）；模板/表单卡 240→260px
- **按钮曝光（用户点名）**：模板卡「编辑」放出（部署+编辑可见，⋯ 剩复制/预检/归档/硬删）；素材卡「文案/受众」放出、「详情」收进 ⋯（缩略图点击即预览，按钮冗余——onCardCmd 加 detail 分支）；表单卡不动（编辑+预览已合理）
- **布局补强**：投放模板加搜索框（此前完全没有，按名称 computed 过滤+清空钮）；空态加「+ 新建模板」CTA；素材 AI 参数条吸顶（top=平台上下文条下方+投影，滚动不粘连；batch-bar 不吸顶——与 ai-bar 会叠位且选中态就近操作）
- **放弃项**：FormTemplates .tab 改名 .seg——实查两套 CSS 视觉完全同款（bg3 容器+bg2 选中），改名零收益 churn
- i18n：launch.searchPh zh/en 成对，en 零 CJK 校验过；复用现有 assets.copyAudience 零新 key

build ✓ + CF master 部署完成。commit 本批（见 git log）。回归点：模板卡 ⋯ 各命令、素材选中批量条、表单双 tab、深浅主题。

## 批BT：AI 分析读超时三修 + 待办清算（2026-09-11）

用户实测「AI 分析异常：The read operation timed out + Vue runtime-5」。根因：视频/深度多帧分析超 vision 90s 读超时→500 原文透传；前端 analyze rethrow（批量计数用）冒进 Vue errorHandler 出渲染警告。三修：①ai_client vision timeout 90→180s（chat_with_images + json 版两处）；②analyze 端点超时识别人话化（504「AI 服务响应超时——稍后重试或换标准深度」）；③前端 analyze 改返 boolean，批量按返回值计数——rethrow 消失，Vue 警告根除。

**FB 残件删除失败→真相**：两 BSCH 账户（…322/…324）**均已被 FB 停用**（account_status=2, disable_reason=1）——8 条 DISAPPROVED、像素访问异常、归档写入被拒（4841021）同源。号已废，需号商换号；系统侧 account_sync 会同步 status=2，看板账户明细状态列（批BN）自动标。

**待办清算（用户拍板）**：主像素共享号商 BM——不做（维持账户自有像素逻辑）；FB policy 申诉——不管；C 组（像素零提示/保活实测/AuditLog mono）——全部移除待办。

## 批BU：像素核对记忆 + 「无在投广告」诚实状态 + 安全守护 UI 实测（2026-09-11）

① **像素核对按 item 记忆（用户点名「第一组定了后面还逐个过太麻烦」）**：树 runner 加 _px_memo（同 explicit 只解析一次，提示只弹一次+注明全组复用）；平铺/重试链 _deploy_series_fb 挂 item._px_cache。同账户一次部署 N 组/系列 → 1 次核对。
② **系列/组「无在投广告」态（用户点名「没 Active 广告别显示投放中」）**：AdManager childPausedMap 扩 adsetActiveAds/campActiveAds（子广告 effective===ACTIVE 计数）；effectiveStatusOf 在容器 ACTIVE 但零生效广告时返 NO_ACTIVE_ADS（useStatus 新条目，灰态）；状态筛选「投放中」自动排除；悬浮说明「容器开启但无在投广告——不消耗」。覆盖全停 PAUSED（批BG）之外的新场景：审核中/被拒混合。
③ **安全守护 UI 实测（Agent 截图 6 张 + API 快筛）**：三层全正常未复现「看不到」——暂停记录 tab 150 条、侧栏面板/移动端抽屉正常、日志中心 emergency 筛选 2 条（默认 7 天窗）。用户看不到的最可能原因：守护页默认在「规则配置」tab；日志中心被巡检心跳刷屏需筛选；时区显示+8h。另抓到 dashboard/landing 422（缺 platform 参数，另行处理）。
smoke：build✓、i18n 成对+en零CJK、单测过、后端双门+health 绿。部署：后端 launch_templates.py + 前端 CF master。
