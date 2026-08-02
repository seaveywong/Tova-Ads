# TK 像素落地页支持 — 实施规划（5 点 + Agent 复审）

> 范围：2.0 落地页支持 TK 像素 + FB/TK 像素"键入 ID"编辑 + 旧页 .zip 更新 + TK 事件须 fire 才能选。
> 基于当前架构实测（Explore agent 全量映射）+ `TK_接入规划.md` §4。本文件是**落地页/像素子集**的施工规划，不重复 TK 全量接入（令牌/账户/止损等见 TK_接入规划.md）。

## 当前架构（关键事实，决定改法）

**像素两段式**：
- **页面级 fallback**（发布时烤进 HTML）：`LANDING_TEMPLATE`/模板 HTML 的 `__LP_PIXELS_JSON__` 占位 → `_do_publish` 替换 → 烤进静态页（直访兜底）。
- **访问级真值**（广告流量实际 fire）：CF Worker `/a/{slug}` → `route_next`（landing_events.py）按 **adset 的 `promoted_object.pixel_id`**（ads_cache 真值）解析 → base64 编进 `_d` → 302 → 页面 `_d_decode` 脚本 fire。**广告流量的像素以访问级为准**。

**像素存储**：`landing_pages.pixel_id`(legacy 单) + `pixel_ids`(JSON 数组)；`landing_pixels`(像素库,无 platform 列)；`launch_templates.pixel_id`(FB adset 像素)。

**编辑=重发**：`PUT /landing/pages/{pid}`（PageUpdateIn.pixel_ids）→ 调 `_do_publish` → **整页 wrangler 重部署**（无"只改库不重发"路径）。

**.zip 模板**：`upload_template`(landing_lib.py) → `landing_page_templates` 表(html+resources_meta)；页引用 `template_id`。换模板 = PUT 页带新 `template_id` = 重发。

**🔴 已存隐患（与本规划强相关，须先修）**：`list_credential_pixels`(fb.py:670) **缺 `@router.get` 装饰器** → `GET /fb/credentials/{id}/pixels` 是死路由 → 部署抽屉的"按账户像素下拉"**永远空**（前端 `.catch(()=>[])` 吞了 404），一直回退模板默认像素。FB 像素选择其实**从来没真正工作过**。

---

## 点 1：FB 像素"键入 ID"（投放链接编辑 + 新建落地页）

### 现状
- 投放模板编辑器 `form.pixel_id`（launch_templates）**存在字段但编辑器里无可见输入**；只在部署抽屉按账户选（且下拉坏的，恒空）。
- 新建落地页 `PublishIn.pixel_id/pixel_ids` 支持设，但 Landing.vue 前端是否暴露输入待确认。

### 改法
1. **修 `list_credential_pixels` 路由**（fb.py:670 加 `@router.get("/credentials/{cred_id}/pixels")`）——像素下拉先能工作。
2. **投放模板编辑器加像素输入**（LaunchTemplates.vue）：③ 广告 Tab（新建帖模式）+ 部署抽屉，像素改为**下拉 + 手动键入二合一**（el-select `allow-create filterable`，可从账户像素选、也可直接打 ID）。`form.pixel_id` 存键入/选择的 ID。
3. **新建落地页加像素输入**（Landing.vue 发布表单）：pixel_ids 支持"手动键入多个 + 从像素库选"。键入的 ID 入 `pixel_ids` JSON 数组。
4. **校验**：键入的像素 ID 部署前做一次 `GET /act_{id}/adspixels?ids={pixel_id}`（或 debug）确认存在+可访问，失败给清晰提示（避免无效 ID 静默上线）。**放在部署 runner（launch_templates.py 的 adset 创建前），不是 cf.deploy_via_wrangler 前（那是落地页部署，跟 FB 像素无关）。**

### 验收
- 投放模板：③ Tab 能直接打 FB 像素 ID 或从账户选；保存→部署→adset `promoted_object.pixel_id` 正确写入（FB Ads Manager 能看到）。
- 新建落地页：发布表单能键入像素 ID；发布后页面 fallback 像素正确（自检矩阵像素项 pass）。

---

## 点 2：TK 像素入预设模板（新落地页支持）

### 数据层（迁移）
- `landing_pixels` 加 `platform` 列（fb/tt，默认 fb）——同一像素库双平台。
- `landing_pages` 加 `tt_pixel_ids`（Text，JSON 数组）——**与 FB `pixel_ids` 分列**（比"JSON 内打 platform tag"更易查询/索引；route_next 解析简单）。
- `landing_events` 加 `fired_tt_pixel_ids`（Text）——与 `fired_pixel_ids`(FB) 对应，地面真相分平台记录。

### Worker / 模板层（landing.py）—— ⚠️ 三处都要改（缺一则 ttq 不 fire）
- `LANDING_TEMPLATE`（L44-77）+ 自定义模板：`<head>` 加 **ttq loader 段**（与 fbq 并列）。
- **`_d_decode` 注入脚本（L296）**：当前只解码 `info.p`；**必须加 `info.tp` 解码 + ttq init/track 分发**。这脚本注入每个发布页 `<head>`，漏了则默认/老模板的 ttq 全不 fire。
- `WORKER_SOURCE`（L80-183）：`_d` 编码（L172）加 `tp`(tt 像素数组) 字段（与现有 `p`/fb 并列；**纯加法，老 worker 解码忽略未知键，向后兼容**）。display 模式 fire 分发：fb→fbq，tt→ttq。
- `.zip` 占位校验（landing_lib.py:332）：**新起 `OPTIONAL_PLACEHOLDERS = ['__LP_TT_PIXELS_JSON__']`**（与 REQUIRED 分离！塞进 REQUIRED 会导致所有老 .zip 上传 400）。TK 模板含该占位则注入 ttq loader。
- `route_next`（landing_events.py:317-368）加 TT 像素源：TK adset 的像素（未来 tt_ads_cache 或 launch_templates.tt_pixel_id）→ 返 `tt_pixel_ids` → worker 编进 `_d.tp`。
- **ORGANIC（无 adset）TK 像素**：route_next 不处理 TK（只 FB）；ORGANIC 的 TK 像素走**页级 fallback**（`landing_pages.tt_pixel_ids` 烤进 HTML 的 `__LP_TT_PIXELS_JSON__`），与 FB 现策略一致。

### 前端
- 像素库 UI（Landing.vue）显 platform icon（fb/tt）。
- 新建/编辑落地页表单：FB 像素 + **TK 像素**两栏（各自可键入/选）。

### 验收
- 新建一个带 TK 像素的落地页 → 发布 → 访问 `/a/{slug}` → 页面同时 fire fbq + ttq（Network 可见 ttq 请求）→ `fired_tt_pixel_ids` 记录正确。

---

## 点 3：旧落地页 .zip 更新（换模板不重建）

### 现状
机制已具备：`PUT /landing/pages/{pid}` 带 `template_id` → `_do_publish(existing=p)` 重发。换 .zip = 上传新模板（upload_template 入 landing_page_templates）→ PUT 页指向新 template_id。

### 改法（补 UX）
- 前端 Landing.vue 落地页列表/编辑：**"更新模板"入口**——选/上传 .zip → 调 `upload_template`（upsert 模板）→ `PUT /landing/pages/{pid}` 带 `template_id` → 重发（含 smoke+回滚）。
- 后端 `upload_template` 支持**按 name upsert**（同名模板覆盖 html/resources），避免模板表堆积。
- 确认 PUT 重发路径对"只换模板不换像素"也工作（pixel_ids 保持原值传回）。

### 验收
- 旧落地页（老 FB 模板）→ 上传含 ttq loader 的新 .zip → 更新 → 重发 → 访问页面加载新模板（ttq 可用），像素/子码不变。

---

## 点 4：TK 像素"键入 ID"

### 改法（同点 1 的 TK 版）
- 投放模板编辑器 + 部署抽屉：加 **TK 像素输入**（`tt_pixel_id` 字段）。`launch_templates` 加 `tt_pixel_id` 列（迁移）。
- TK 像素下拉来源：TK 像素库（`landing_pixels` where platform=tt）+ 手动键入。
- 新建/编辑落地页：TK 像素栏可键入。
- 部署：TK adset 用 `tt_pixel_id`（TK API 的 pixel_id 字段）。

### 验收
- 投放模板能键入 TK 像素 ID → 部署 TK 广告 → adset pixel_id 正确。

---

## 点 5：TK"事件须 fire 过才能选优化目标"

### TK 硬约束
TK Ads Manager 的转化目标下拉**只列像素已收到的事件**；新像素全灰，须先收到 ≥1 个事件 + ≤2h 处理才可选。

### 方案（TK_接入规划.md §4 已定）
**主路：后端 Events API S2S 点亮事件**。
- 后端调 TK Events API（`POST /events/...`）发一个带 `test_event_code` 的事件（如 `CompletePayment`/`PlaceAnOrder`）→ TK Events Manager 收到 → 该事件进入可选库。
- 触发时机：用户在系统里"绑定 TK 像素 + 选优化目标"时，若事件未点亮 → 自动 S2S 发一次点亮（异步，提示"事件点亮中，≤2h 后可选"）。
- 常规投放走浏览器 ttq Pixel（+ S2S 同 event_id 去重双发，见下）。

### 🔴 event_id 去重（双发强制，TK 规定）—— 真相源在后端，不在 worker
浏览器 Pixel + 后端 Events API 双发同一事件**必须同 `event_id`（UUID）**，否则转化翻倍。
- **后端 route_next 预生成 `tt_event_id`（UUID）** → 编入 `_d.tp`（浏览器从 `_d` 读出）**同时**入 `landing_events.tt_event_id`（visit 事件即记，不等 beacon）。
- 浏览器：`ttq.track(evt, {event_id: <从_d读出的UUID>})`。
- 后端 Events API：用**同一个 route_next 生成的 UUID** 发 S2S（从 visit 事件取，不依赖 beacon 回传）。
- **单点真相 = 后端 route_next**。beacon 丢不丢，S2S 都能用同一 UUID（从 visit 记录取）。worker 只是消费者，不是真相源。
- `landing_events` 加 `tt_event_id`（Text）—— route_next 时就写（visit 行），排查+去重双用。

### ttclid 归因
- TK 广告点击带 `ttclid`（类比 FB fbc）。Worker 捕获 URL ttclid → 透传 Events API。`landing_events` 加 `ttclid` 列。

### 验收
- 新建 TK 像素 → 系统 S2S 点亮事件 → ≤2h 后 TK Ads Manager 该事件可选 → 配优化目标部署。

---

## 迁移清单（DB）
| 表 | 改动 |
|---|---|
| `landing_pixels` | + `platform`(Text, fb/tt, 默认 fb) |
| `landing_pages` | + `tt_pixel_ids`(Text JSON) |
| `launch_templates` | + `tt_pixel_id`(Text) |
| `landing_events` | + `fired_tt_pixel_ids`(Text) + `tt_event_id`(Text) + `ttclid`(Text) |
末尾 GRANT toveads_app + toveads_super（铁律）。**⚠️ 参照 0055-0057 的 GRANT 段，勿参照 0058（0058 漏了 GRANT，是反面教材）。**

## 代码改动清单
| 文件 | 改动 |
|---|---|
| `routers/fb.py` | 修 `list_credential_pixels` 路由装饰器（点1前置） |
| `routers/landing.py` | LANDING_TEMPLATE + **`_d_decode` 注入脚本(L296)** + WORKER_SOURCE 三处加 ttq loader+_d.tp；_do_publish 注入 tt_pixel_ids+__LP_TT_PIXELS_JSON__ |
| `routers/landing_lib.py` | 新起 OPTIONAL_PLACEHOLDERS=['__LP_TT_PIXELS_JSON__']（与 REQUIRED 分离）；upload_template 新写 tenant_id+name 查询做 upsert |
| `routers/landing_events.py` | route_next 预生成 tt_event_id(UUID)+加 TT 像素源+返 tt_pixel_ids；ingest 记 fired_tt_pixel_ids/tt_event_id/ttclid |
| `routers/launch_templates.py` | TemplateIn/PageUpdateIn 加 tt_pixel_id；部署传 TK adset pixel |
| TK Events API client（新） | S2S 发事件（点亮 + 常规去重双发） |
| `frontend Landing.vue` | 像素库 platform icon + 新建/编辑双像素栏 + .zip 更新入口 |
| `frontend LaunchTemplates.vue` | 像素下拉+键入二合一（FB）；加 TK 像素输入 |

## 顺序（建议）
1. **P0 前置**：修 `list_credential_pixels` 路由（FB 像素下拉先活）。
2. **点1**：FB 像素键入（编辑器+新建）+ preflight 校验。
3. **点3**：.zip 更新 UX（机制已在，补前端入口）。
4. **数据层迁移**：landing_pixels.platform + tt_pixel_ids + tt_pixel_id + landing_events 三列。
5. **点2**：Worker/模板 ttq loader + _d.tp + route_next TT 源（新落地页支持 TK）。
6. **点4**：TK 像素键入（同点1 TK 版）。
7. **点5**：TK Events API client（S2S 点亮 + event_id 去重双发 + ttclid）。

## 风险 / 开放问题
- ~~**event_id 双发一致性**~~ → **已解**：真相源放后端 route_next（预生成 UUID），beacon 丢不丢都不翻倍。
- **TK 像素 ID 来源**：TK 像素不像 FB 能从 adset promoted_object 拿（TK 结构不同）。route_next 的 TT 像素源现阶段 = `launch_templates.tt_pixel_id`（用户键入/模板）；ORGANIC = 页级 fallback。tt_ads_cache 成熟后再加自动解析。
- **.zip 模板兼容**：老 FB .zip 无 ttq loader → 加 TK 像素后 ttq 不 fire（只 fire fbq）。须用含 ttq loader 的新模板（点3 的 .zip 更新正是为此）。**OPTIONAL 占位分离确保老 .zip 仍能上传。**
- **preflight 像素校验**对 TK 像素怎么做（TK API 校验像素归属）——待 TK Events/Pixel API 定。

## Agent 复审结论（已并入本规划）
- ✅ 5 条核心声明全经代码核验为真（含 P0 死路由发现）。
- P0 已修：补 `_d_decode` 脚本（G1）+ event_id 真相源改后端（点5）。
- P1 已修：OPTIONAL 占位分离（G5）+ 迁移 GRANT 参照（G2）+ preflight 位置（点1）。
- P2 已修：ORGANIC TK 像素策略澄清（G3）+ upsert 细节（G4）。
