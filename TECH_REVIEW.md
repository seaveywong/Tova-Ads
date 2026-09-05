# 技术变更复审文档

> 每次大改完按此格式更新。技术专家复审用。
> 格式 = 概述 + 按commit/功能的变更表(含文件+验证状态) + DB迁移 + 生产环境变更(非代码) + 复审结论(已知限制/风险) + commit列表 + 关联memory。

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
