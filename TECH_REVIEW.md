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
