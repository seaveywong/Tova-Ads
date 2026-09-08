# 总方案 v2 — FB 广告管理器 1:1 对齐（2026-09-08 深夜调研合成）

> 依据六份调研：`蓝图_FB广告管理器创建流.md`(c761230) · `盘点_编辑器现状矩阵.md`(0a88345) · `审计_编辑器UX与逻辑.md`(137e860) · `方案_版位与转化位置.md`(7334b0c) · `方案_落地页自动链接.md`(12664d5) · `系统串联全景.md`(c54bd61)。
> 状态：**待用户批准，零代码**。备份已做（DB `toveads_db_20260908_0127.dump.gz` + 代码 b127641）。

## 拍板点（醒后一次拍完）
| # | 决策 | 推荐 |
|---|---|---|
| P1 | 转化位置范围：A=网站/即时表单/Messenger/主页(已验证) vs B=全开(+WhatsApp/电话/IG私信，蓝图实证 Leads 有 7 个转化位置含组合位) | **B**（蓝图已实证组合矩阵，风险=WA号前置配置，做前置校验+引导） |
| P2 | 自动建链粒度：每广告/每组/每账户 | **每广告**（对齐1.0生产模型，封禁爆炸半径最小） |
| P3 | Leads「即时表单+Messenger」组合位（分流类，蓝图假设1实证存在）进不进批次 I | 进（否则 Leads 1:1 缺角） |
| P4 | 批次范围：0+I 先做，II/III 后续批 | 是 |

## 批次 0 — P0 止血（改动极小，批准当天可上）
1. **`{ad.id}`→`{{ad.id}}` 宏修复**（ad_ops.py:226 + launch_templates.py:2220 两处一行）——2.0 子码归因可能从未跑通，一切自动建链的前置
2. **lock 117 撞号分离**（leads_poll × stale_page_cleanup）+ CLAUDE.md 锁段更新为「新锁从 119 起」
3. **树预检补子码存在性校验**（平铺有、树没有，2113 注释失实）

## 批次 I — 1:1 核心对齐（主战役）
1. **受众编辑进组卡**（国家/年龄/性别/兴趣内联+受众库）——现状树模式无受众入口，静默投 US（审计 P0）
2. **转化位置动态单选**：组节点 conv_location 按蓝图目标矩阵出选项（含 Leads 组合位 P3、WhatsApp/电话按 P1）；**conversion_goal 三套词表归一**（UI/API/is_messaging 门），custom_event_type 真实生效（修恒 PURCHASE/LEAD）
3. **版位双卡**：自动（省略版位键=Advantage+官方语义）/手动（平台级+设备勾选；P1 细分位置进批次 III）；不走 advanced_config（避浅合并坑）
4. **消息模板死链修复**（词表归一后 is_messaging 门自然通）+ **WhatsApp 真链路**：type 消费位 + promoted_object.whatsapp_phone_number 按目标建模（蓝图：Engagement=广告级 Accounts 区显式选号；Traffic/Sales=主页绑定号隐式）
5. **表单选择器层级校正**：Instant Form 在**广告层 Destination 区**（非组层；API 挂 creative CTA value——现状已对，UI 摆位对齐蓝图）
6. **CBO+lifetime 树模式排期打通**（加模板级排期或守卫读组级）
7. **2 个部署 bug**：destination_type_override 顶掉 MESSENGER；SALES+非转化优化目标缺 promoted_object
8. **优化目标兼容校验**（按蓝图 performance goal×目标矩阵约束下拉）
9. **Advantage+ 家族按派生语义展示**（非开关：CBO 默认开/受众 Advantage+ 默认开/自动版位默认开，UI 标注派生状态）

## 批次 II — P1 资金与断层
出价双管道资金 bug（美分覆盖本币换算）· AI 随机文案不覆盖手填 · 落地页 URL 跟随（landing_page_id 部署消费）· 无自定义域回填落空（public_url 兜底死链）· TT 动态像素按账户解析 · 保存错误定位到字段 · TT Instant Form 门矛盾 · 目标切换 optimization_goal 残留

## 批次 III — P2/清理
平铺组段死代码清理 · 细分版位位置 · redirect 模式 fire 像素 · TT event_id · link.ad_id last-wins · spend_cap 预检缺汇率兜底统一

## 自动建链工作流（P2 拍板后并入批次 I 尾部或独立批）
模板选落地页 → 部署时**每广告自动建子码**（slug=模板短码-节点key-账户尾4位；复用既有回收站/清理）→ 未绑落地页=自定义 URL 直投。验收=方案文档 A1-A11 逐环节像素断言 smoke（worker 注入→fire 像素来源→S2S event_id 去重→归因回绑）。

## 验证策略
每批次：语法门+迁移门+断言 smoke（树 29 + 批G 26 + 新增 A1-A11）→ 部署。**批次 I 完成后做一次真投放实测**（用户授权花钱）：验证 {{ad.id}} 宏替换/转化位置/promoted_object/版位/自动建链/像素 fire 全链——这是 2.0 投放链首次真金白银验证。

## 蓝图三大纠偏（写进实现，防再犯）
1. 表单×消息非互斥（Leads 组合位存在）；表单选择器在广告层
2. Advantage+ campaign 无单一开关字段，是预算/受众/版位三默认派生态
3. WhatsApp 号码位置随目标变（Engagement 显式选/其他随主页），API 在 adset promoted_object
