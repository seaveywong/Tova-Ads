"""Tove Ads API 入口。"""
import json
from fastapi import FastAPI, Depends, HTTPException
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
from .routers.tt_oauth import router as tt_oauth_router
from .routers.ads import router as ads_router
from .routers.settings import router as settings_router
from .routers.rbac import router as rbac_router
from .routers.launch_templates import router as launch_templates_router
from .routers.form_templates import router as form_templates_router

app = FastAPI(title="Tove Ads API", version="1.3.5")


# ── trace_id 中间件（总则3：每个请求一个 trace_id）──
class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or new_trace_id()
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

# CORS —— 生产放 tovaads.com（官网期）+ app.tovaads.com（管理界面）；localhost 仅非生产环境放行
_origins = [
    "https://tovaads.com",           # 前端主域（官网化过渡期仍直连管理界面）
    "https://www.tovaads.com",       # www 别名
    "https://app.tovaads.com",       # 管理界面正式域
    "https://tovaads.pages.dev",     # CF Pages 默认域（自定义域名生效前 / 冒烟测试）
]
if settings.app_env != "production":
    _origins.append("http://localhost:5173")  # 本地开发（Vite 默认端口）
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-New-Token"],  # 滑动续期：前端读新 token
)


@app.middleware("http")
async def sliding_renew_middleware(request: Request, call_next):
    """滑动续期：带合法 token 的请求 → 响应头返新 token，前端存它 → 活跃用永不掉线。

    错误响应绝不续期：renew_token 只验签名不验 pwd_changed_at——若 401（凭证已变更）
    也续期，被盗 token 在受害者改密后仍能拿到 iat=now 的新 token，失效机制被整体绕过。"""
    resp = await call_next(request)
    if resp.status_code >= 400:
        return resp
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


# ── 安全响应头（素材同源静态服务需 nosniff 防存储型 XSS 内容嗅探）──
@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


# ── 报错 i18n：en-locale 请求把中文 HTTPException detail 译成英文（不动各 router）──
from fastapi import HTTPException as _HTTPException
from fastapi.responses import JSONResponse as _JSONResponse

@app.exception_handler(_HTTPException)
async def _i18n_http_exception_handler(request, exc: _HTTPException):
    detail = exc.detail
    if isinstance(detail, str):
        try:
            from .core.error_i18n import translate_error
            detail = translate_error(detail, (request.headers.get("x-locale") or "").lower())
        except Exception:
            pass
    return _JSONResponse(
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
        content={"detail": detail},
    )

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
from .routers.leads import router as leads_router
from .routers.fb_webhook import router as fb_webhook_router
app.include_router(leads_router)
app.include_router(fb_webhook_router)
app.include_router(fb_oauth_router)
app.include_router(tt_oauth_router)
app.include_router(ads_router)
app.include_router(settings_router)
app.include_router(launch_templates_router)
app.include_router(form_templates_router)

# ── 静态文件服务（素材库图片/视频，api.tovaads.com/static-assets/{filename}）──
import os as _os
from fastapi.staticfiles import StaticFiles as _StaticFiles
_ASSET_DIR = _os.environ.get("ASSET_DIR", "/opt/toveads/assets")
_os.makedirs(_ASSET_DIR, exist_ok=True)
app.mount("/static-assets", _StaticFiles(directory=_ASSET_DIR), name="static-assets")

# ── APScheduler（定时巡检）──
from apscheduler.schedulers.background import BackgroundScheduler
_scheduler = BackgroundScheduler()


@app.on_event("startup")
def _start_scheduler():
    from .services.guard_engine import run_inspection, run_watchdog, run_reassociate, run_subcode_autobind, run_sentinel_patrol, run_subcode_cleanup, run_landing_block_scan, run_keepalive
    # 回收上次重启遗留的中断部署 job（FB 侧可能已建广告在花钱，标 failed 让用户看到并核查）
    try:
        from .routers.launch_templates import _reap_stale_jobs
        _reap_stale_jobs()
    except Exception as _e:
        print(f"[Startup] stale job 回收失败(非致命): {_e}")
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
    # 保活扫描：每日 2:17 查 warming 账户，3天无消耗→建$5 lifetime Page Like
    _scheduler.add_job(run_keepalive, "cron", hour=2, minute=17, id="keepalive_scan")
    # 落地页 FB 屏蔽自动探测：每 1h 扫所有 published 页（Graph scrape），屏蔽→critical 告警 + 看板红标
    _scheduler.add_job(run_landing_block_scan, "interval", minutes=60, id="landing_block_scan")
    # 数据保留：每日 4:33 按配置清理老数据（perf/events/审计/告警等）
    from .core.retention import run_data_retention
    _scheduler.add_job(run_data_retention, "cron", hour=4, minute=33, id="data_retention")
    # 汇率同步：每日 3:07 拉实时汇率（止损 to_usd 用，避免 VND/IDR 漂移致阈值误判）
    from .services.fx_sync import run_fx_sync
    _scheduler.add_job(run_fx_sync, "cron", hour=3, minute=7, id="fx_sync")
    # TikTok 令牌自动续期：access_token 24h 过期，每 6h 刷剩 <12h 的凭证（refresh 即轮换，原子写回）
    from .services.tt_token_refresh import run_tt_token_refresh
    _scheduler.add_job(run_tt_token_refresh, "interval", hours=6, id="tt_token_refresh")
    # 中断部署 job 回收：startup 已跑一次（上方），再加每 5min 巡检——原仅启动跑一次，
    # 长跑进程中的孤儿 job（worker 崩溃遗留）要等下次重启才被回收。内部 advisory lock 116 多 worker 单飞。
    try:
        from .routers.launch_templates import _reap_stale_jobs as _reap_launch_stale
        _scheduler.add_job(_reap_launch_stale, "interval", minutes=5, id="reap_stale_jobs")
    except Exception as _e:
        print(f"[Scheduler] reap_stale_jobs 注册失败(非致命): {_e}")
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


def _apply_log_filters(q, *, actor_type="", actor_user_id=0, action_type="",
                       target_type="", result="", trace_id="",
                       date_from="", date_to=""):
    """日志筛选公共逻辑（/logs 和 /logs/count 共用）。"""
    from .models.log import ActionLog
    from datetime import datetime, timezone, timedelta
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
    # 日期范围：纯日期 YYYY-MM-DD 按北京业务日解释（与前端 useDateRange / notify.py 同基准），
    # 转 UTC 窗口过滤；带时间的 ISO 串按自身时区（无时区当 UTC）。格式错 → 400（原静默忽略整段筛选）。
    BIZ_TZ = timezone(timedelta(hours=8))
    if date_from:
        s = date_from.strip()
        try:
            if "T" in s:
                df = datetime.fromisoformat(s)
                if df.tzinfo is None:
                    df = df.replace(tzinfo=timezone.utc)
            else:
                df = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=BIZ_TZ).astimezone(timezone.utc)
        except ValueError:
            raise HTTPException(400, "date_from 格式应为 YYYY-MM-DD")
        q = q.filter(ActionLog.created_at >= df)
    if date_to:
        s = date_to.strip()
        try:
            if "T" in s:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=BIZ_TZ).astimezone(timezone.utc) + timedelta(days=1)
        except ValueError:
            raise HTTPException(400, "date_to 格式应为 YYYY-MM-DD")
        q = q.filter(ActionLog.created_at < dt)
    return q


@app.get("/logs")
def list_logs(
    actor_type: str = "",       # user/system/sentinel/warmup/sync —— 三视图用
    actor_user_id: int = 0,     # 用户活动视图按人筛
    action_type: str = "",
    target_type: str = "",
    result: str = "",           # success/fail（只看失败用）
    trace_id: str = "",         # 按链路拉全Trace
    date_from: str = "",        # YYYY-MM-DD（含）
    date_to: str = "",          # YYYY-MM-DD（含当天）
    limit: int = 100,
    offset: int = 0,
    user: CurrentUser = Depends(require_permission("audit.read")),
    db: Session = Depends(get_db),
):
    """查 action_logs。超管看全部团队（SuperSessionLocal bypass RLS）；普通用户受 RLS 只看本团队。
    三视图（决策⑤）：操作=actor_type=user / 系统=system / 用户活动=actor_user_id。
    支持 offset 分页 + date_from/date_to 日期范围。"""
    from .models.log import ActionLog
    from .core.database import SuperSessionLocal
    sdb = SuperSessionLocal() if user.is_superadmin else db
    try:
        q = _apply_log_filters(sdb.query(ActionLog), actor_type=actor_type,
                               actor_user_id=actor_user_id, action_type=action_type,
                               target_type=target_type, result=result, trace_id=trace_id,
                               date_from=date_from, date_to=date_to)
        logs = q.order_by(ActionLog.created_at.desc()) \
                .offset(max(offset, 0)).limit(min(max(limit, 1), 500)).all()
        return [
            {"id": l.id, "trace_id": l.trace_id, "actor_type": l.actor_type,
             "actor_user_id": l.actor_user_id, "action_type": l.action_type,
             "target_type": l.target_type, "target_id": l.target_id, "result": l.result,
             "trigger_type": l.trigger_type, "friendly_error": l.friendly_error,
             "trigger_detail": l.trigger_detail, "source": l.source,
             "raw_error": l.raw_error,
             "metadata": json.loads(l.metadata_) if l.metadata_ else None,
             "tenant_id": l.tenant_id, "created_at": str(l.created_at)}
            for l in logs
        ]
    finally:
        if user.is_superadmin:
            sdb.close()


@app.get("/logs/count")
def count_logs(
    actor_type: str = "", actor_user_id: int = 0, action_type: str = "",
    target_type: str = "", result: str = "", trace_id: str = "",
    date_from: str = "", date_to: str = "",
    user: CurrentUser = Depends(require_permission("audit.read")),
    db: Session = Depends(get_db),
):
    """日志总数（同 /logs 筛选条件），给前端分页用。"""
    from .models.log import ActionLog
    from .core.database import SuperSessionLocal
    from sqlalchemy import func as _func
    sdb = SuperSessionLocal() if user.is_superadmin else db
    try:
        q = _apply_log_filters(sdb.query(_func.count(ActionLog.id)), actor_type=actor_type,
                               actor_user_id=actor_user_id, action_type=action_type,
                               target_type=target_type, result=result, trace_id=trace_id,
                               date_from=date_from, date_to=date_to)
        return {"count": int(q.scalar() or 0)}
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
        # 批量取用户（原逐 uid sdb.get = N+1）
        users = sdb.query(User).filter(User.id.in_(uids)).all() if uids else []
        return [{"id": u.id, "email": u.email} for u in users]
    finally:
        if user.is_superadmin:
            sdb.close()

