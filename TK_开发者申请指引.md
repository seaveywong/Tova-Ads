# TikTok 开发者账号申请指引（Track A）

> 给：Seavey。目标：拿到 **app_id + app_secret + sandbox advertiser_id**，交给开发接真环境。
> 预计耗时：注册建 App 半小时；Marketing API 权限审核 1-2 周（期间 sandbox 全功能可用，开发不被阻塞）。
> ⚠️ 入口是 **business-api.tiktok.com/portal**（TikTok 商业 API 门户）。**不是** developers.tiktok.com——那是 Login Kit/分享体系的开发者后台，走错了拿不到 Marketing API。

---

## 第 1 步：注册开发者账号（~15 分钟）

1. 浏览器打开 `https://business-api.tiktok.com/portal`
2. 用你现有的 TikTok 广告账户（Ads Manager）账号登录——**用同一主体/邮箱**，后续 app 与广告账户关联最顺
3. 填开发者资料：
   - 公司/主体名称：**乳源瑶族自治县星航互动传媒店**（必须与 TT 广告账户主体一致，不一致会被拒；可能要求上传营业执照）
   - 联系邮箱：**dev@tovaads.com**（2026-09-03 起邮箱转发已通，验证邮件自动转到你的 Gmail——填个人邮箱容易被判非企业）
   - 网址：`https://tovaads.com`（company 页就是为企业认证准备的）
4. 邮箱验证 → 进入 portal

**注意**：调研中「大陆主体准入」没有找到成文规定。你已经开通过 TT 广告账户说明主体本身能过；若开发者注册被拒，联系你的 TT 出海代理/客户经理加白（这是最快路径）。

## 第 2 步：创建 App（~10 分钟）

1. portal → **Apps** → **Create App**（或 "Connect an app"）
2. 填：App name（如 `TovaAds`）、描述（广告管理工具：管理 campaign/报表/素材）、行业类别选 Marketing/Advertising 相关
   - **用途描述（英文，直接粘贴）**：
     > Our SaaS platform helps advertisers manage their own TikTok ad accounts. Via OAuth-authorized access, we use the Marketing API to sync campaign performance reports (spend, impressions, clicks, conversions), create/edit/pause ads and adjust budgets at the owner's instruction, upload creative assets, and run advertiser-configured automated optimization rules. No user data is collected; all data belongs to the authorizing advertiser.
3. 创建后进 App 详情页，记下：
   - **App ID**（数字）
   - **App Secret**（Show 后复制，只显示一次，存好）
4. **Sanbox advertisers**：App 详情里有 sandbox advertiser（测试广告账户，自动分配）——记下 **advertiser_id**

## 第 3 步：配置 OAuth 回调（开发会给你要的）

App 详情 → **Login products / OAuth** 配置：
- **Redirect URL** 填（我们后端的回调，部署后生效）：
  ```
  https://api.tovaads.com/tt/oauth/callback
  ```
- 开启 **Marketing API** 相关 scope/权限申请

## 第 4 步：申请 Marketing API 权限（审核 1-2 周）

App 详情 → **Apply for products / permissions**，产品列表**只勾这 6 个**（对应我们已实现的功能；少选=审核快=被拒率低）：

| ✅ 勾 | 产品 | 用途 |
|---|---|---|
| ✅ | 广告账号管理 | OAuth 授权、载入 advertiser |
| ✅ | 广告管理 | 建/改/停广告、预算、删除 |
| ✅ | 数据报表 | 消耗/转化回拉（看板+巡检）|
| ✅ | 创意管理 | 素材上传拿 file_id |
| ✅ | 受众管理 | 定向受众 |
| ✅ | Pixel 管理 | 像素 + Events API（确认 Events 能力含在此下，不含则单独勾）|

**不勾**：自动规则（我们有自己的守护引擎，平台原生规则做不了跨平台/落地页数据/学习期保护，且双系统混乱）、DPA 商品库、Reach & Frequency、潜在客户管理（TT 表单将来接了再补申）、应用管理、Payment、TTO/Creator、其余全部。将来要新的随时追加申请，不影响已批的。

- 有分级（basic → more access）：先申请基础级，够 MVP 用
- 提交后等审——**期间 sandbox 权限已可用，开发照常进行**

## 第 5 步：Events Manager（Events API 前置，可与审核并行）

1. 打开 `https://events.tiktok.com`（用同一账号）
2. **域名验证**：Assets → Web Events → 域名验证——把落地页用的域名加进去验证（tovaads.com + lp 子域所在根域）。验证方式二选一：HTML meta 标签 / 上传验证文件（给我们域名的验证码，开发帮你放到落地页或 company 页）
3. **建 Pixel**：Web Events → Manage → Create Pixel → 拿到 **Pixel Code**（一串字母数字）——给开发
4. Pixel 设置里可拿 **S2S access token**（Events API 服务端发送用）——给开发

## 第 6 步：把这几样交给开发

| 东西 | 在哪拿 |
|---|---|
| App ID + App Secret | App 详情页 |
| sandbox advertiser_id | App 详情 → sandbox advertisers |
| Pixel Code + S2S token | Events Manager |
| 域名验证状态截图 | Events Manager |

拿到前两个，开发就能连 sandbox 跑通「连 token→导账户→建广告」全链路；后两个用于转化事件 S2S。

---

## 常见坑
- **走错门户**：developers.tiktok.com 是 Login Kit 体系（抖音登录那种），Marketing API 在 business-api.tiktok.com
- **Secret 只显示一次**：忘了就得 regenerate（会踢掉旧 token）
- **sandbox 数据是假的**：报表数字/审核状态都是模拟，正式上线前要切 production app（类比 FB dev→standard，但 TT sandbox 能真建广告结构）
- **权限分级**：申请被拒通常是描述不清——写明「内部使用的广告管理工具，管理自有客户的广告投放与报表」这类，别写成数据抓取
- **token 24h 过期**：这是 TK 机制不是你配错——我们的系统会自动刷新，不用管
