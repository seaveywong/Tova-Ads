"""HTTPException detail 的中→英译表。全局异常处理器对 en-locale 请求按此把中文 detail 换成英文。"""

# key = 后端代码里 raise HTTPException(..., "中文") 的【精确】detail 字符串
# value = 英文翻译
#
# 收录规则：
#   - 仅收录【静态字符串字面量】（纯字面量、字面量拼接）。
#   - 跳过含 {var} 的 f-string 与含变量的拼接——全局处理器按精确匹配无法命中，留待后续模板化处理。
#   - 部分条目是 dict.get(key, "默认值") 的默认值（如 ads.py 的 "操作失败"/"删除失败"），
#     当上游未提供 error 时该默认值会被原样抛出，故一并收录。
#   - 重复的 detail（多处复用，如 "未绑定 FB 凭证"）只在表里出现一次。
ERROR_ZH_EN: dict[str, str] = {
    # ---- auth.py / 登录注册 / 账号 ----
    "邀请码无效或已使用": "Invitation code is invalid or already used",
    "邀请码已过期": "Invitation code has expired",
    "邮箱已注册": "Email already registered",
    "邮箱或密码错误": "Incorrect email or password",
    "用户已停用": "Account is disabled",
    "该用户未加入任何团队，请联系管理员": "You are not a member of any team. Please contact the administrator.",
    "你不属于该团队": "You do not belong to this team",
    "邮箱格式不正确": "Invalid email format",
    "该邮箱已被占用": "This email is already taken",
    "用户不存在": "User does not exist",
    "新密码至少 8 位": "New password must be at least 8 characters",
    "旧密码错误": "Incorrect old password",

    # ---- core/deps.py / 鉴权依赖 ----
    "无效或过期 token": "Invalid or expired token",
    "token 类型错误": "Wrong token type",
    "用户不可用": "User is unavailable",
    "需要平台超管权限": "Platform super-admin permission required",

    # ---- admin.py / rbac.py / 团队·角色·成员 ----
    "无当前团队": "No current team",
    "团队名不能为空": "Team name cannot be empty",
    "团队名已存在": "Team name already exists",
    "团队不存在或已停用": "Team does not exist or is disabled",
    "团队不存在": "Team does not exist",
    "租户不存在或已停用": "Tenant does not exist or is disabled",
    "分配记录不存在": "Assignment record does not exist",
    "owner 邮箱格式不对": "Owner email format is invalid",
    "邮箱格式不对": "Invalid email format",
    "该用户已是本团队成员": "This user is already a member of the team",
    "成员不存在": "Member does not exist",
    "不能取消自己的 owner 角色": "You cannot revoke your own owner role",
    "不能移除自己": "You cannot remove yourself",
    "团队至少保留一个 owner": "A team must keep at least one owner",
    "status 只能是 active/suspended/archived": "status must be one of active / suspended / archived",
    "主团队不可停用/归档": "The primary team cannot be suspended or archived",
    "角色名不能为空": "Role name cannot be empty",
    "该名称为系统保留": "This name is reserved by the system",
    "角色名已存在": "Role name already exists",
    "角色不存在": "Role does not exist",
    "owner 角色必须保留全部权限": "The owner role must keep all permissions",
    "系统角色不可删除": "System roles cannot be deleted",
    "该角色下仍有成员，请先转移或移除": "This role still has members. Please reassign or remove them first.",

    # ---- fb.py / 令牌·凭证·账户 ----
    "令牌不存在": "Token does not exist",
    "access_token 不能为空": "access_token cannot be empty",
    "凭证不存在": "Credential does not exist",
    "未绑定 FB 凭证": "No Facebook credential is bound",
    "未绑定有效 FB 凭证": "No valid Facebook credential is bound",
    "账户未纳管": "Account is not under management",
    "账户未纳管或已移除": "Account is not under management or has been removed",

    # ---- ads.py / 广告操作 ----
    "批量操作上限 100 条": "Batch operations are limited to 100 items",
    "缺 ad_id": "Missing ad_id",
    "跳转链接必须以 http:// 或 https:// 开头": "The redirect URL must start with http:// or https://",
    "广告不在缓存中，请先刷新广告列表": "Ad is not in the cache. Please refresh the ad list first.",
    "操作失败": "Operation failed",
    "删除失败": "Deletion failed",

    # ---- launch.py / 投放 ----
    "主页未开启 messaging，无法投放私信广告（请在 FB 主页设置开启）": (
        "The Page has not enabled messaging, so Messenger ads cannot be launched "
        "(please enable it in the Facebook Page settings)."
    ),

    # ---- launch_templates.py / 投放模板 ----
    "模板不存在": "Template does not exist",
    "至少选一个账户": "Please select at least one account",
    "job 不存在": "Job does not exist",
    "item 不存在": "Item does not exist",

    # ---- landing.py / 落地页 ----
    "CF API Token 或 Account ID 未配置": "Cloudflare API token or Account ID is not configured",
    "防护已开启，必须配置屏蔽跳转链接或屏蔽页 HTML（至少一项）": (
        "Protection is enabled. You must configure either a block redirect URL or a block page HTML (at least one)."
    ),
    "CF 未配置": "Cloudflare is not configured",
    "落地页不存在": "Landing page does not exist",

    # ---- landing_lib.py / 像素·域名·素材包 ----
    "该像素已在库中": "This pixel is already in the library",
    "像素不存在": "Pixel does not exist",
    "域名服务未配置": "Domain service is not configured",
    "域名不存在": "Domain does not exist",
    "只支持 .zip 文件": "Only .zip files are supported",
    "zip 超过 10MB 限制": "The zip file exceeds the 10MB limit",
    "zip 内文件数超过 100": "The zip archive contains more than 100 files",
    "解压内容超过 50MB": "The extracted content exceeds 50MB",
    "损坏的 zip 文件": "Corrupted zip file",
    "zip 内未找到 index.html": "index.html was not found inside the zip",
    "内置模板不可删": "Built-in templates cannot be deleted",

    # ---- landing_events.py / 事件上报 ----
    "无效的 ingest secret": "Invalid ingest secret",

    # ---- form_templates.py / 表单·消息模板 ----
    "表单模板不存在": "Form template does not exist",
    "消息模板不存在": "Message template does not exist",
    "page_id 必填": "page_id is required",
    "AI 未配置（缺 ai_api_key）": "AI is not configured (missing ai_api_key)",
    "AI 未配置（.env 缺 ai_api_key）": "AI is not configured (.env is missing ai_api_key)",
    "AI 未配置": "AI is not configured",
    "素材不存在": "Asset does not exist",

    # ---- assets.py / 素材库 ----
    "名称不能为空": "Name cannot be empty",
    "FB image_hash 仅支持图片素材": "FB image_hash is only supported for image assets",
    "素材文件丢失": "Asset file is missing",
    "视觉 AI 未配置（缺 ai_vision_api_key，去 设置→AI配置→视觉模型 配）": (
        "Vision AI is not configured (missing ai_vision_api_key). "
        "Configure it under Settings → AI Settings → Vision Model."
    ),

    # ---- subcodes.py / 子码 ----
    "子码不存在": "Subcode does not exist",
    "仅归档/硬删的子码可恢复": "Only archived or hard-deleted subcodes can be restored",

    # ---- launch_templates.py / 投放模板·部署 ----
    "预算换算失败：账户币种缺少汇率，请在系统设置配置汇率或改用 USD 模板": (
        "Budget conversion failed: exchange rate missing for the account currency. "
        "Configure the rate in Settings or deploy with a USD template"
    ),
    "该账户已移除纳管，不能重试（重新导入后再部署）": (
        "This ad account is no longer managed; retry is disabled (re-import it to deploy again)"
    ),

    # ---- settings.py / 巡检与告警旋钮 ----
    "巡检并发需为 1-8 的整数": "Inspection concurrency must be an integer between 1 and 8",
    "学习期保护需为 0-720 的整数（0=关闭）": (
        "Learning-phase protection must be an integer between 0 and 720 (0 = disabled)"
    ),
    "告警风暴上限需为 0-1000 的整数（0=不封顶）": (
        "Alert storm cap must be an integer between 0 and 1000 (0 = uncapped)"
    ),

    # ---- settings.py / 邮箱转发（CF Email Routing）----
    "配置值不能包含换行": "Config value must not contain line breaks",
    "CF 未配置，请先在「域名服务配置」填 Token 和账户 ID": (
        "Cloudflare is not configured; fill in the token and account ID under "
        "'Domain Service Configuration' first"
    ),
    "CF 上找不到平台域名的 Zone（域名须托管在 CF，或主 Token 缺 Zone:Read 权限——可先用主 Token 访问一次邮箱转发页自动缓存）": (
        "Cloudflare Zone for the platform domain not found (domain must be hosted on CF, or the "
        "main token lacks Zone:Read — visit the Email Forwarding page once with the main token "
        "to cache it automatically)"
    ),
    "目的地邮箱格式不正确": "Invalid destination email address",
    "当前 CF Token 不支持邮箱地址管理（账户级 token 的限制）。请到「域名服务配置 → 邮箱管理 Token」填入用户级 API Token 后重试": (
        "The current Cloudflare token cannot manage email addresses (account-level token "
        "limitation). Enter a user-level API token under 'Domain Service → Email Management "
        "Token' and retry"
    ),
    "目的地邮箱不存在或已删除": "Destination email does not exist or has been deleted",
    "该邮箱已被转发映射引用，请先删除对应映射": (
        "This email address is referenced by a forwarding rule; delete the rule first"
    ),
    "别名只允许小写字母、数字和 . _ - ": "Alias allows only lowercase letters, digits and . _ -",
    "别名已存在，请换一个": "Alias already exists; pick another one",
    "Email Routing 未启用，请先启用": "Email Routing is not enabled; enable it first",
    "目的地邮箱未添加，请先在目的地邮箱区添加": (
        "Destination email not added yet; add it in the destination addresses section first"
    ),
    "目的地邮箱待验证：请先到该邮箱点开 CF 验证邮件": (
        "Destination email is pending verification: open the Cloudflare verification email in "
        "that mailbox first"
    ),
    "映射不存在": "Forwarding rule does not exist",

    # ---- audiences.py / 受众 ----
    "查询词 q 不能为空": "Query parameter q cannot be empty",
    "strategy 必须是 broad_interest/broad_only/interest_only": (
        "strategy must be one of broad_interest / broad_only / interest_only"
    ),
    "age_min/age_max 范围无效（18-65，min<=max）": (
        "Invalid age_min/age_max range (18-65, min <= max)"
    ),
    "gender 必须是 0/1/2": "gender must be 0, 1, or 2",
    "受众模板不存在": "Audience template does not exist",
    "strategy 无效": "Invalid strategy",

    # ---- guard.py / 止损规则 ----
    "规则不存在": "Rule does not exist",
    "账户不存在": "Account does not exist",

    # ---- kpi.py / KPI ----
    "KPI 配置不存在": "KPI configuration does not exist",

    # ---- notify.py / TG 通知 ----
    "未绑定 TG": "Telegram is not bound",
    "你未绑定 TG（POST /notifications/tg/user-binding）": (
        "You have not bound Telegram (POST /notifications/tg/user-binding)"
    ),
    "管理员未配置 TG Bot": "The administrator has not configured a Telegram bot",
    "管理员未配置 TG Bot（联系管理员先绑租户 TG）": (
        "The administrator has not configured a Telegram bot "
        "(please ask the administrator to bind the tenant Telegram first)."
    ),
    "获取 Bot 信息失败": "Failed to fetch bot information",
    "Bot username 为空": "Bot username is empty",
    "TG 验证失败（hash 不匹配）": "Telegram verification failed (hash mismatch)",
    "TG 登录已过期（超过 24h）": "Telegram login has expired (older than 24h)",

    # ---- fb_oauth.py / fb_apps.py / FB App ----
    "App 不存在或已停用": "App does not exist or is disabled",
    "App 不存在": "App does not exist",
    "仅超管可创建系统级 App": "Only super-admins can create system-level apps",
    "仅超管可编辑系统级 App": "Only super-admins can edit system-level apps",
    "仅超管可删除系统级 App": "Only super-admins can delete system-level apps",

    # ---- tg_webhook.py / TG Webhook ----
    "未配置 TG bot（tenant_tg_binding 空）": "Telegram bot is not configured (tenant_tg_binding is empty)",
    "未配置 TG bot": "Telegram bot is not configured",

    # ---- compliance.py / 合规认证 ----
    "beneficiary_identity_id 必须是数字（FB 拒绝文本名）": (
        "beneficiary_identity_id must be a number (Facebook rejects text names)"
    ),
    "beneficiary_identity_id 必须是数字": "beneficiary_identity_id must be a number",
    "payer_identity_id 必须是数字": "payer_identity_id must be a number",
    "认证记录不存在": "Verification record does not exist",

    # ---- tickets.py / 工单 ----
    "工单不存在": "Ticket does not exist",
    "工单已关闭": "Ticket is already closed",

    # ---- backup.py / 数据库备份 ----
    "无法解析数据库连接串": "Failed to parse the database connection string",
    "pg_dump 超时（300s）": "pg_dump timed out (300s)",

    # ---- settings.py / 设置（200 响应里的 detail，非错误，但前端可能照原样展示） ----
    "无变更": "No changes",

    # ---- TikTok（tt_client TT_ERROR_MAP 静态 friendly + services/ad_ops TT 写操作错误。
    #      动态 f-string（"TikTok 返回错误（code …）"/"网络错误：…"）不收录，无法精确匹配；
    #      未知 code 走 friendly 原样透传 ----
    "请求参数错误": "Invalid request parameters",
    "请求参数缺失": "Missing request parameters",
    "请求格式错误": "Invalid request format",
    "授权码无效或已过期（10 分钟内有效），请重新授权": (
        "The authorization code is invalid or expired (valid for 10 minutes). Please re-authorize."
    ),
    "缺少 Access Token": "Missing access token",
    "Access Token 无效或已过期，需刷新或重新授权": (
        "The access token is invalid or expired and needs to be refreshed or re-authorized."
    ),
    "Refresh Token 无效或已过期，需重新走 TikTok 授权": (
        "The refresh token is invalid or expired. Please redo the TikTok authorization."
    ),
    "对象不存在": "Object not found",
    "无权操作该对象（权限不足或对象不属于该广告主）": (
        "No permission to operate this object (insufficient permission, "
        "or the object does not belong to this advertiser)"
    ),
    "Scope 权限不足，请在 TikTok 开发者后台申请": (
        "Insufficient TikTok scope. Please apply for it in the TikTok developer console."
    ),
    "请求过于频繁，请稍后重试": "Too many requests. Please try again later.",
    "TikTok 拒绝了请求参数（金额过低/字段不合法）": (
        "TikTok rejected the request parameters (amount too low or an invalid field)"
    ),
    "TikTok 仅支持在广告组层级修改预算": (
        "TikTok only supports changing budgets at the ad group level"
    ),

    # ---- FB/TT 共用浮出的写操作 detail（原 FB 路径就有的字符串，此处一并补齐 en 配对）----
    "无可用写令牌（operate/manage）": "No available write token (operate/manage)",
    "该广告正在被其他操作处理": "This ad is being processed by another operation",
    "预算必须大于 0": "Budget must be greater than 0",
    "该对象使用日预算，不支持改总预算": (
        "This object uses a daily budget; changing to a lifetime budget is not supported"
    ),
    "该对象使用总预算(lifetime)，不支持改日预算": (
        "This object uses a lifetime budget; changing to a daily budget is not supported"
    ),
}


def translate_error(detail, locale: str) -> str:
    """locale=='en' 且 detail 命中译表 → 返回英文；否则原样返回。"""
    if locale != "en" or not detail:
        return detail
    return ERROR_ZH_EN.get(detail, detail)
