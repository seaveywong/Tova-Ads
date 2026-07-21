# Tove Ads 2.0

多租户 SaaS Facebook 广告管理系统：自动止损（规则引擎）、落地页管理（CF Workers + 像素追踪）、广告管理、RBAC 权限、FB OAuth 连接。

## 技术栈

- **后端**：Python 3.12 + FastAPI + SQLAlchemy 2.0 + PostgreSQL 16（RLS 行级安全做多租户隔离）+ Alembic 迁移 + APScheduler 定时巡检
- **前端**：Vue 3 + Vite + Element Plus
- **落地页**：Cloudflare Pages + Workers（Worker 源码在后端 `landing.py` 的 `WORKER_SOURCE` 常量里，发布时注入 JSON 配置）
- **部署**：Gunicorn（4 worker）+ Cloudflare Tunnel

## 目录结构

```
backend/          # FastAPI 后端
  app/
    core/         # 配置(config.py)、数据库(database.py)、JWT、加密、FB API 客户端
    models/       # SQLAlchemy ORM 模型
    routers/      # API 路由（fb/ads/landing/guard/rbac/settings 等）
    services/     # 业务逻辑（guard_engine 止损引擎、巡检、汇率同步等）
  alembic/        # 数据库迁移
  requirements.txt
frontend/         # Vue 3 前端
  src/views/      # 页面（Dashboard/Tokens/Ads/Landing/Guard/Members/Settings 等）
  src/api/        # API 封装（fetch + 30s 超时 + 401 自动跳登录）
db/init.sql       # PostgreSQL 角色+库初始化
.env.example      # 全量环境变量模板
```

## 从零搭建（新服务器）

### 1. 安装依赖
```bash
# Python 3.12 + pip + venv
# PostgreSQL 16
# Node.js 20+
```

### 2. 初始化数据库
```bash
sudo -u postgres psql -f db/init.sql          # 建角色 + 库（先改密码）
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# 配 .env
cp ../.env.example ../backend/.env             # 填入 DB 密码/JWT_SECRET/FB_CRED_KEY 等
# 生成 FB_CRED_KEY: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 跑迁移（建表 + RLS 策略 + 种子数据）
./venv/bin/alembic upgrade head
# 跑 catch-all GRANT（防个别迁移漏 GRANT → permission denied）
sudo -u postgres psql -d toveads -c "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO toveads_app,toveads_super; GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO toveads_app,toveads_super;"
```

### 3. 启动后端
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000    # 开发模式
# 或 gunicorn（生产）：gunicorn app.main:app -w 4 -b 127.0.0.1:8000
```

### 4. 构建前端
```bash
cd frontend
npm install
# 改 VITE_API_BASE 指向你的后端地址
echo "VITE_API_BASE=https://your-api-domain.com" > .env
npm run build     # 产物在 dist/
# 用 nginx 或 CF Pages 部署 dist/
```

## 核心架构要点

### 多租户隔离（RLS）
- 所有业务表有 `tenant_id` 列 + RLS 策略 `tenant_iso`（USING = `tenant_id = current_setting('app.tenant_id')`）
- 每个请求：`get_current_user`（deps.py）在 DB session 里 `SET LOCAL app.tenant_id`
- 超管（`is_superadmin`）用 `toveads_super` 角色（BYPASSRLS）
- **注意**：手动开 session 查 RLS 表前必须 `SET LOCAL app.tenant_id`，否则查到 0 行

### FB 令牌管理
- 用户通过 OAuth（`/fb/oauth/start` + `/fb/oauth/callback`）或手动粘贴 access token 连接 FB
- 令牌加密存储（Fernet，`FB_CRED_KEY`）
- 多令牌 fallback（令牌失效/限流时自动轮换其他 active 令牌）
- 令牌类型：operate（写+读）、manage（读+暂停）、user（只读）

### 落地页系统
- 每个落地页独立 CF Pages 项目 + Worker（Worker 源码在 `landing.py` 的 `WORKER_SOURCE`）
- Display 模式：访客看落地页 → 像素 fire → 点按钮 → 跳转目标
- Redirect 模式：直接 302 跳转（无像素）
- 防护：国家/设备/UA/ASN/数据中心/频率/去重
- 自检矩阵（9 项）：发布/链接/域名SSL/Worker/像素/目标/防护/FB封禁/预览

### 自动止损（规则引擎）
- 定时巡检（每小时）拉 FB insights → 评估规则（bleed_abs/cpa_exceed/consecutive_bad）
- 超阈值自动暂停广告 + Telegram 告警
- 转化口径 `either`：max(FB 转化, 落地页点击量)

## 需要修改的硬编码

新环境部署时检查这些文件里的 URL/域名：
- `backend/app/routers/fb_oauth.py` 的 `FRONTEND_URL`（OAuth 回调后跳转的前端地址）
- `backend/app/main.py` 的 CORS `allow_origins`（前端域名）
- 前端 `src/api/index.js` 的 `BASE`（后端 API 地址，或用 `VITE_API_BASE` 环境变量）

## FB App Review 权限

OAuth 授权需要 5 个 FB scope（在 `fb_oauth.py` 的 `OAUTH_SCOPES`）：
`ads_management, ads_read, read_insights, business_management, pages_show_list`

需在 FB 开发者后台注册 OAuth 回调 URL：`{PUBLIC_BASE_URL}/fb/oauth/callback`

## License

Private / Internal Use
