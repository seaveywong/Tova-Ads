# 广告管理器对标矩阵（批H · 2026-09-09）

按《实施规格_FB广告创建与编辑_配置及API映射.md》§0 的证据分级对 ToveAds 广告管理器逐项验证。
分级含义：**A**=接口已找到并本地接通；**B**=条件能力（受目标/版本/账户资格限制）；**C**=本地实现（非 Meta 云端状态）；**D**=待核实（无稳定公开接口证据）。
标注「批H」= 本批已改；「FB实测」= 需 FB 解封后真投放验收。

## 1. 界面层级对标（规格 §1 → AdManager.vue）

| 规格条目 | FB 行为 | 我们现状 | 等级 |
|---|---|---|---|
| 顶栏：广告账户（币种/时区/权限） | 账户选择器显币种时区 | 账户多选（含平台 chip/脱管禁用态/单选显账户名）；币种在列头/预算行内按本币显 | C |
| 顶栏：数据新鲜度 | Ads Manager 顶栏无对应（侧栏账户状态） | 数据更新至 X + 缓存龄 chip + 行内快照标（三档） | C |
| ＋创建按钮（工具条首位） | 绿色 ＋ 创建 进编辑器 | **批H 已加**：绿色 ＋创建 → 投放模板编辑器 | C |
| 工具条顺序 | 创建→筛选→搜索→细分→列｜日期→刷新 | **批H 已重排**：＋创建→账户→日期→筛选→搜索→列→⚡核验→跳转链接→缓存龄 | C |
| 左侧对象树 → 三层 Tab | 系列→组→广告 钻取 | Tab（系列/组/广告/潜客）+ 名称钻取 + 面包屑（全部系列›系列›组）——顺序与 FB 一致 | C |
| 表格列默认顺序 | 成效→消耗→单次成效费用→… | **批H 已改**：成效(FB)→消耗→单次成效费用→预算→综合转化；列可配置+localStorage 记忆 | C |
| 细分（Breakdown） | 按投放：年龄/性别/版位；按操作：转化位置 | 年龄/性别/版位 + **批H 新增转化位置**（action_breakdowns=conversion_destination，只拆成效，同 FB 口径） | A（待 FB实测） |
| 批量选择/确认/逐项反馈 | 勾选→批量开关→逐项结果 | 批量开关（确认弹窗）+ 逐项成功/失败/未核验明细 + 失败选择保留 | C |
| 状态开关/改名/预算行内编辑 | 行内 | 开关（回读核验/假停警示）、改名、日/总预算统一行内（未核验不显示成功） | A（已实测：暂停核验 PASS） |
| 实时核验 | FB 无对应（其数据即实时） | ⚡ Live Verify 广告层秒级直读 patch 本地行 | A（生产实测 PASS） |
| 发布结果回读 | 创建/更新对象及 ID、部分成功 | 部署 job 进度轮询 + 部署后对账（ads_cache 刷新 + live join） | A（创建链已实测；/ads 终步被 FB policy 拦） |

## 2. 转化发生位置矩阵对标（规格 §4 → ad_builder.py，官方矩阵 2035196643270）

| 目标 | FB 官方选项 | 我们 | 等级 |
|---|---|---|---|
| 销量 | 网站、应用、网站和应用、网站和实体店、网站和通话、Messenger、WhatsApp | website/messenger/whatsapp（**批H 移除错误单独通话位**）；组合位与 D | B |
| 流量 | 网站、应用、Messenger、WhatsApp、通话、Instagram 主页 | website/messenger/whatsapp/**instagram_profile**(批H 新增，INSTAGRAM_PROFILE+VISIT_INSTAGRAM_PROFILE)/phone_call | B |
| 潜客 | 网站、组合位、即时表单、Messenger、Instagram、通话、WhatsApp | website/on_ad/on_ad_messenger/messenger/**instagram_direct→LEAD_FROM_IG_DIRECT**(批H 修正)/phone_call→**QUALITY_CALL**(批H 修正) | B |
| 互动 | 广告中、消息应用（多渠道）、网站、应用、公共主页 | website/on_page/messenger/whatsapp/instagram_direct；「广告中」与多渠道合并= D | B |
| 认知 | 广告中（自动唯一） | 无选项自动 | B |
| 应用推广 | 应用（自动） | 不支持（应用链路未建，scope 外） | D |

文案已统一官方叫法：转化发生位置／Instagram 主页／Instagram／通话／Facebook 公共主页。

## 3. 明确缓项（不在本批）

| 项 | 原因 | 等级 |
|---|---|---|
| 「消息应用」多渠道一个广告组 | API 用 4 个 MESSAGING_* 组合值 + 创意层 DOF 素材流（asset_feed_spec），专项工程 | B/D |
| 组合位（网站和通话/网站和即时表单/网站和应用/网站和实体店） | API 单字段表达官方未写明（未确认） | D |
| 应用位（application_id/object_store_url 全链） | 原有 scope 外决定 | D |
| 店铺/目录（SHOP_AUTOMATIC/产品目录） | 同上 | D |
| Instagram 身份键（instagram_actor_id vs instagram_user_id） | v25 规则待锁（规格 §9.1） | D |
| 创意内容编辑（新建 Creative 换 Ad 关联） | 规格 §5.1 受控流程，独立批 | B |

## 4. 验证记录（批H）

- `_smoke_batch_h.py`：33/33 ALL_PASS（矩阵自洽/新组合 payload/旧组合拒绝/resolve 一致/回归）
- 双门：py_compile + `from app.main import app` PASS；restart 后 health ok、journal 4min 零 err
- 前端：`node --test adManagerView.test.js` 5/5；build 产物含 conversion_location/create-btn/instagram_profile 后才部署 CF
- 生产模板扫描：182 个模板 0 个使用 conv_location → 矩阵收紧零存量影响
- commit f17f02d（前后端+smoke），已 push；线上 version 1.3.5

## 5. 外部依赖（用户侧）

- FB business policy 限制未解：真投放创建 /ads 终步被拦（campaign/adset/creative 均可建）→ 解封后跑细分/真投放验收
- Roly-V21-41 令牌过期：管理器时间戳被其冻结快照钉死（重新授权或停止管理）
