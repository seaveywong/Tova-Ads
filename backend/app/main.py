"""Tove Ads API 入口。"""
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from sqlalchemy.orm import Session
from .core.config import settings
from .core.database import get_db
from .core.deps import get_current_user, CurrentUser, require_permission
from .core.log_utils import new_trace_id
from .routers.auth import router as auth_router
from .routers.fb import router as fb_router
from .routers.subcodes import router as subcodes_router
from .routers.launch import router as launch_router
from .routers.guard import router as guard_router
from .routers.notify import router as notify_router
from .routers.tickets import router as tickets_router
from .routers.dashboard import router as dashboard_router
from .routers.landing import router as landing_router
from .routers.compliance import router as compliance_router
from .routers.audiences import router as audiences_router
from .routers.ai import router as ai_router
from .routers.landing_lib import router as landing_lib_router
from .routers.admin import router as admin_router
from .routers.kpi import router as kpi_router
from .routers.landing_events import router as landing_events_router
from .routers.tg_webhook import router as tg_webhook_router
from .routers.assets import router as assets_router
from .routers.backup import router as backup_router
from .routers.fb_apps import router as fb_apps_router
from .routers.fb_oauth import router as fb_oauth_router
from .routers.ads import router as ads_router
from .routers.settings import router as settings_router
from .routers.rbac import router as rbac_router

app = FastAPI(title="Tove Ads API", version="1.3.5")


# ── trace_id 中间件（总则3：每个请求一个 trace_id）──
class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or new_trace_id()
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

# CORS —— 生产放 tovaads.com（主域 + www + pages.dev 默认域）；本地开发加 localhost:5173（Vite 默认端口）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",         # 本地开发（Vite）
        "https://tovaads.com",           # 生产前端（主域）
        "https://www.tovaads.com",       # 生产前端（带 www）
        "https://tovaads.pages.dev",     # CF Pages 默认域（自定义域名生效前 / 冒烟测试）
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-New-Token"],  # 滑动续期：前端读新 token
)


@app.middleware("http")
async def sliding_renew_middleware(request: Request, call_next):
    """滑动续期：带合法 token 的请求 → 响应头返新 token，前端存它 → 活跃用永不掉线。"""
    resp = await call_next(request)
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            from .core.security import renew_token
            new_tok = renew_token(auth[7:])
            if new_tok:
                resp.headers["X-New-Token"] = new_tok
        except Exception:
            pass
    return resp


app.add_middleware(TraceIdMiddleware)

app.include_router(auth_router)
app.include_router(fb_router)
app.include_router(subcodes_router)
app.include_router(launch_router)
app.include_router(guard_router)
app.include_router(notify_router)
app.include_router(tickets_router)
app.include_router(dashboard_router)
app.include_router(landing_router)
app.include_router(compliance_router)
app.include_router(audiences_router)
app.include_router(ai_router)
app.include_router(landing_lib_router)
app.include_router(tg_webhook_router)
app.include_router(admin_router)
app.include_router(rbac_router)
app.include_router(kpi_router)
app.include_router(landing_events_router)
app.include_router(assets_router)
app.include_router(backup_router)
app.include_router(fb_apps_router)
app.include_router(fb_oauth_router)
app.include_router(ads_router)
app.include_router(settings_router)

# ── APScheduler（定时巡检）──
from apscheduler.schedulers.background import BackgroundScheduler
_scheduler = BackgroundScheduler()


@app.on_event("startup")
def _start_scheduler():
    from .services.guard_engine import run_inspection, run_watchdog, run_reassociate, run_subcode_autobind, run_sentinel_patrol, run_subcode_cleanup
    from .services.budget_alerts import run_budget_alerts
    from .services.account_sync import run_account_status_sync
    from .services.ads_cache_sync import run_ads_cache_sync
    from .core.schedule_config import get_schedule_config, effective_intervals
    from .core.database import SessionLocal
    _db = SessionLocal()
    try:
        _cfg = get_schedule_config(_db)
    finally:
        _db.close()
    _eff = effective_intervals(_cfg)
    _scheduler.add_job(run_inspection, "interval", minutes=_eff["inspect"], id="guard_inspect")
    _scheduler.add_job(run_budget_alerts, "interval", minutes=_eff["budget"], id="budget_alerts")
    _scheduler.add_job(run_watchdog, "interval", minutes=_eff["watchdog"], id="system_watchdog")
    _scheduler.add_job(run_reassociate, "interval", minutes=_eff["reassociate"], id="reassociate_orphans")
    _scheduler.add_job(run_subcode_autobind, "interval", minutes=_eff["subcode"], id="subcode_autobind")
    _scheduler.add_job(run_sentinel_patrol, "interval", minutes=_eff["sentinel"], id="sentinel_patrol")
    _scheduler.add_job(run_account_status_sync, "interval", minutes=_eff["account_sync"], id="account_status_sync")
    _scheduler.add_job(run_ads_cache_sync, "interval", minutes=15, id="ads_cache_sync")
    _scheduler.add_job(run_subcode_cleanup, "cron", hour=4, minute=17, id="subcode_cleanup")
    # 数据保留：每日 4:33 按配置清理老数据（perf/events/审计/告警等）
    from .core.retention import run_data_retention
    _scheduler.add_job(run_data_retention, "cron", hour=4, minute=33, id="data_retention")
    # 汇率同步：每日 3:07 拉实时汇率（止损 to_usd 用，避免 VND/IDR 漂移致阈值误判）
    from .services.fx_sync import run_fx_sync
    _scheduler.add_job(run_fx_sync, "cron", hour=3, minute=7, id="fx_sync")
    _scheduler.start()
    print(f"[Scheduler] 已启动，间隔(分钟)={_eff}")


def reschedule_jobs(cfg: dict):
    """调度配置变更后 live 重排所有任务（PUT /settings/schedule 调，无需重启）。"""
    from .core.schedule_config import effective_intervals, JOB_IDS
    eff = effective_intervals(cfg)
    for key, jid in JOB_IDS.items():
        if key in eff:
            try:
                _scheduler.reschedule_job(jid, trigger="interval", minutes=eff[key])
            except Exception:
                pass


@app.on_event("shutdown")
def _stop_scheduler():
    _scheduler.shutdown(wait=False)


@app.get("/health")
def health():
    """健康检查（前端启动同步版本号用）。"""
    return {
        "status": "ok",
        "service": "toveads-api",
        "env": settings.app_env,
        "version": app.version,
    }


@app.get("/protected-test")
def protected_test(user: CurrentUser = Depends(require_permission("ads.read"))):
    """测试 RBAC + RLS 接线（需登录 + 有 ads.read 权限）。"""
    return {
        "ok": True,
        "who": user.email,
        "tenant_id": user.tenant_id,
        "role": user.role,
        "permissions": sorted(user.permissions),
    }


@app.get("/logs")
def list_logs(
    actor_type: str = "",       # user/system/sentinel/warmup/sync —— 三视图用
    actor_user_id: int = 0,     # 用户活动视图按人筛
    action_type: str = "",
    target_type: str = "",
    result: str = "",           # success/fail（只看失败用）
    trace_id: str = "",         # 按链路拉全Trace
    limit: int = 100,
    user: CurrentUser = Depends(require_permission("audit.read")),
    db: Session = Depends(get_db),
):
    """查 action_logs。超管看全部团队（SuperSessionLocal bypass RLS）；普通用户受 RLS 只看本团队。
    三视图（决策⑤）：操作=actor_type=user / 系统=system / 用户活动=actor_user_id。"""
    from .models.log import ActionLog
    from .core.database import SuperSessionLocal
    sdb = SuperSessionLocal() if user.is_superadmin else db
    try:
        q = sdb.query(ActionLog)
        if actor_type:
            _types = [t.strip() for t in actor_type.split(',') if t.strip()]
            if _types:
                q = q.filter(ActionLog.actor_type.in_(_types))
        if actor_user_id > 0:
            q = q.filter(ActionLog.actor_user_id == actor_user_id)
        if action_type:
            _types = [t.strip() for t in action_type.split(',') if t.strip()]
            if _types:
                q = q.filter(ActionLog.action_type.in_(_types))
        if target_type:
            q = q.filter(ActionLog.target_type == target_type)
        if result:
            q = q.filter(ActionLog.result == result)
        if trace_id:
            q = q.filter(ActionLog.trace_id == trace_id)
        logs = q.order_by(ActionLog.created_at.desc()).limit(min(max(limit, 1), 500)).all()
        return [
            {"id": l.id, "trace_id": l.trace_id, "actor_type": l.actor_type,
             "actor_user_id": l.actor_user_id, "action_type": l.action_type,
             "target_type": l.target_type, "target_id": l.target_id, "result": l.result,
             "trigger_type": l.trigger_type, "friendly_error": l.friendly_error,
             "tenant_id": l.tenant_id, "created_at": str(l.created_at)}
            for l in logs
        ]
    finally:
        if user.is_superadmin:
            sdb.close()


@app.get("/logs/actors")
def list_log_actors(
    user: CurrentUser = Depends(require_permission("audit.read")),
    db: Session = Depends(get_db),
):
    """用户活动视图的"人"下拉：近 30 天有操作的用户（id+email）。超管看全部团队。"""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import distinct
    from .models.log import ActionLog
    from .models.auth import User
    from .core.database import SuperSessionLocal
    sdb = SuperSessionLocal() if user.is_superadmin else db
    try:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        uids = [r[0] for r in sdb.query(distinct(ActionLog.actor_user_id)).filter(
            ActionLog.actor_user_id.isnot(None),
            ActionLog.created_at >= since,
        ).all()]
        out = []
        for uid in uids:
            u = sdb.get(User, uid)
            if u:
                out.append({"id": u.id, "email": u.email})
        return out
    finally:
        if user.is_superadmin:
            sdb.close()

