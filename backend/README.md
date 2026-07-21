# Tove Ads 后端（FastAPI）

> 2.0 SaaS 后端。规划源：`D:\dev\Mira_One\Mira_2.0_docs\`。

## 技术栈
FastAPI + SQLAlchemy 2.0（sync）+ PostgreSQL 16（RLS 多租户）+ Alembic 迁移。

## 项目结构
```
backend/
├── app/
│   ├── main.py          # FastAPI 入口 + CORS + /health
│   └── core/
│       ├── config.py    # 配置中心（pydantic-settings，SSOT）
│       └── database.py  # 引擎 + 会话 + RLS tenant_ctx
├── requirements.txt
├── .env.example         # 复制为 .env 填值（不进 git）
└── README.md
```

## 本地跑起来（开发）
```bash
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # 填 DATABASE_URL / JWT_SECRET 等
uvicorn app.main:app --reload --port 8000
# 访问 http://localhost:8000/health
```

## 服务器部署
```bash
# 127.0.0.1:8000，gunicorn + uvicorn worker，systemd 守护（见 11 运维）
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000
```

## 接下来（按文档建）
- [ ] Alembic 初始化 + 第一次迁移（建核心表：tenants/users/memberships/invitations + RLS）—— doc 01/10
- [ ] 认证模块（注册/登录/JWT/RBAC）—— doc 01
- [ ] FB 集成（fb_client + 凭证加密 + token_health）—— doc 02/08
- [ ] 守护引擎（巡检/哨兵/预热）—— doc 03
- [ ] ... 其余模块照 10 个设计文档
