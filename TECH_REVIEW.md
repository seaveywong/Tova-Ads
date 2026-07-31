# 技术变更复审文档

> 每次大改完按此格式更新。技术专家复审用。
> 格式 = 概述 + 按commit/功能的变更表(含文件+验证状态) + DB迁移 + 生产环境变更(非代码) + 复审结论(已知限制/风险) + commit列表 + 关联memory。

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
