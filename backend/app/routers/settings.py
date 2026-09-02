"""系统设置路由：调度配置 + AI 配置。平台级，超管才能改。"""
import json
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_superadmin, require_permission
from ..core.schedule_config import (get_schedule_config, save_schedule_config,
                                     effective_intervals, DEFAULT_SCHEDULE)
from ..core.retention import (get_retention_config, save_retention_config,
                              run_data_retention, get_last_run, DEFAULT_RETENTION)
from ..core.config import settings
from ..core.log_utils import write_log, new_trace_id
from ..models.system import SystemSetting

router = APIRouter(prefix="/settings", tags=["settings"])


class ScheduleIn(BaseModel):
    base_minutes: int = DEFAULT_SCHEDULE["base_minutes"]
    sentinel_minutes: int | None = None
    multipliers: dict = {}


@router.get("/schedule")
def get_schedule(user: CurrentUser = Depends(require_superadmin), db: Session = Depends(get_db)):
    cfg = get_schedule_config(db)
    eff = effective_intervals(cfg)
    return {
        "base_minutes": cfg["base_minutes"],
        "sentinel_minutes": cfg["sentinel_minutes"],
        "multipliers": cfg["multipliers"],
        "effective": eff,
        "task_labels": {
            "inspect": "巡检（止损评估）", "watchdog": "令牌健康检查",
            "account_sync": "账户状态/余额", "budget": "预算进度告警",
            "reassociate": "失效账户重绑", "subcode": "子码自动绑定",
            "sentinel": "哨兵巡逻",
        },
    }


@router.put("/schedule")
def set_schedule(body: ScheduleIn, user: CurrentUser = Depends(require_superadmin),
                 db: Session = Depends(get_db)):
    base = body.base_minutes if body.base_minutes and body.base_minutes >= 1 else DEFAULT_SCHEDULE["base_minutes"]
    sm = body.sentinel_minutes if body.sentinel_minutes and 1 <= body.sentinel_minutes <= 10 else None
    save_schedule_config(db, base, body.multipliers, sm)
    cfg = {"base_minutes": base, "sentinel_minutes": sm or DEFAULT_SCHEDULE["sentinel_minutes"],
           "multipliers": body.multipliers}
    from ..main import reschedule_jobs
    reschedule_jobs(cfg)
    return {"effective": effective_intervals(cfg)}


# ── 巡检与告警调优（超管）──
# 三个系统旋钮（平台级，system_settings.value 存 JSON 数字）：
#   guard_concurrency    巡检并发 1-8（guard_engine._max_workers 每轮现读，下一轮生效）
#   guard_learning_hours 学习期保护小时数，0=关（guard_engine 每轮现读）
#   notify_storm_cap     每租户每事件当日告警上限，0=不封顶（notify_utils 60s TTL 缓存，保存后主动失效）
class GuardTuningIn(BaseModel):
    guard_concurrency: int
    guard_learning_hours: int
    notify_storm_cap: int


def _setting_num(db: Session, key: str, default: float) -> float:
    """读 system_settings 数值（value 存 JSON）。缺省/脏值 → default（与 guard_engine._sys_float 同语义）。"""
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row and row.value not in (None, ""):
            return float(json.loads(row.value))
    except Exception:
        pass
    return default


@router.get("/guard-tuning")
def get_guard_tuning(user: CurrentUser = Depends(require_superadmin), db: Session = Depends(get_db)):
    """三键当前生效值 + 默认值。生效值按读方口径钳制（并发 1-8、风暴上限 ≥0）。"""
    from ..services.guard_engine import DEFAULT_CONCURRENCY, DEFAULT_LEARNING_HOURS
    from ..core.notify_utils import DEFAULT_STORM_CAP
    conc = max(1, min(int(_setting_num(db, "guard_concurrency", DEFAULT_CONCURRENCY)), 8))
    learn = _setting_num(db, "guard_learning_hours", DEFAULT_LEARNING_HOURS)
    storm = max(0, int(_setting_num(db, "notify_storm_cap", DEFAULT_STORM_CAP)))
    return {
        "guard_concurrency": conc,
        "guard_learning_hours": int(learn) if learn == int(learn) else learn,
        "notify_storm_cap": storm,
        "defaults": {
            "guard_concurrency": int(DEFAULT_CONCURRENCY),
            "guard_learning_hours": int(DEFAULT_LEARNING_HOURS),
            "notify_storm_cap": int(DEFAULT_STORM_CAP),
        },
    }


@router.put("/guard-tuning")
def set_guard_tuning(body: GuardTuningIn, user: CurrentUser = Depends(require_superadmin),
                     db: Session = Depends(get_db)):
    """写三键（value 存 JSON 数字）。storm_cap 写后失效 TTL 缓存立即生效；另两键下一轮巡检现读。"""
    if not 1 <= body.guard_concurrency <= 8:
        raise HTTPException(400, "巡检并发需为 1-8 的整数")
    if not 0 <= body.guard_learning_hours <= 720:
        raise HTTPException(400, "学习期保护需为 0-720 的整数（0=关闭）")
    if not 0 <= body.notify_storm_cap <= 1000:
        raise HTTPException(400, "告警风暴上限需为 0-1000 的整数（0=不封顶）")
    for key, val in (("guard_concurrency", body.guard_concurrency),
                     ("guard_learning_hours", body.guard_learning_hours),
                     ("notify_storm_cap", body.notify_storm_cap)):
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row:
            row.value = json.dumps(val)
        else:
            db.add(SystemSetting(key=key, value=json.dumps(val)))
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="system_setting", target_id="guard_tuning",
              action_type="update", source="user", result="success",
              metadata={"guard_concurrency": body.guard_concurrency,
                        "guard_learning_hours": body.guard_learning_hours,
                        "notify_storm_cap": body.notify_storm_cap})
    db.commit()
    from ..core.notify_utils import reset_storm_cap_cache
    reset_storm_cap_cache()
    return get_guard_tuning(user=user, db=db)


# ── AI 配置（超管）──
# 文案/KPI 走 ai_*（DeepSeek），素材看图走 ai_vision_*（Gemini）。两组都在此 UI 配。
# ENV 变量名 → settings 属性名（写 .env + 运行时热重载用）
_AI_ENV_ATTR = {
    "AI_BASE_URL": "ai_base_url", "AI_API_KEY": "ai_api_key", "AI_MODEL": "ai_model",
    "AI_VISION_BASE_URL": "ai_vision_base_url",
    "AI_VISION_API_KEY": "ai_vision_api_key",
    "AI_VISION_MODEL": "ai_vision_model",
}


def _sanitize_env_value(v) -> str:
    """env 值清洗：去首尾空白；含换行直接拒（一行一个 KEY=VALUE，换行会破坏整个文件）。"""
    v = str(v).strip()
    if "\n" in v or "\r" in v:
        raise HTTPException(status_code=400, detail="配置值不能包含换行")
    return v


def _write_env_and_reload(updates: dict):
    """写 .env（更新已有行或追加）+ 运行时 settings 热重载。updates = {ENV_KEY: value}。"""
    from pathlib import Path
    updates = {k: _sanitize_env_value(v) for k, v in updates.items()}
    env_path = Path("/opt/toveads/backend/.env")
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updated_lines, found = [], set()
    for line in lines:
        stripped = line.strip()
        if "=" in stripped:
            k = stripped.split("=", 1)[0]
            if k in updates:
                updated_lines.append(f"{k}={updates[k]}")
                found.add(k)
                continue
        updated_lines.append(line)
    for k, v in updates.items():
        if k not in found:
            updated_lines.append(f"{k}={v}")
    env_path.write_text("\n".join(updated_lines) + "\n")
    for env_key, val in updates.items():
        attr = _AI_ENV_ATTR.get(env_key)
        if attr:
            setattr(settings, attr, val)


def _mask(s: str) -> str:
    s = s or ""
    return s[:6] + "***" + s[-4:] if len(s) > 10 else ("***" if s else "")


class AiConfigIn(BaseModel):
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_vision_base_url: str = ""
    ai_vision_api_key: str = ""
    ai_vision_model: str = ""


@router.get("/ai")
def get_ai_config(user: CurrentUser = Depends(require_superadmin)):
    """返回当前 AI 配置（文案 + 视觉，key 脱敏）。"""
    return {
        "ai_base_url": settings.ai_base_url or "",
        "ai_api_key_masked": _mask(settings.ai_api_key),
        "ai_api_key_set": bool(settings.ai_api_key),
        "ai_model": settings.ai_model or "",
        "ai_vision_base_url": settings.ai_vision_base_url or "",
        "ai_vision_api_key_masked": _mask(settings.ai_vision_api_key),
        "ai_vision_api_key_set": bool(settings.ai_vision_api_key),
        "ai_vision_model": settings.ai_vision_model or "",
    }


@router.put("/ai")
def set_ai_config(body: AiConfigIn, user: CurrentUser = Depends(require_superadmin),
                  db: Session = Depends(get_db)):
    """更新 AI 配置（文案/视觉）→ 写 .env + 热重载 settings。空字段=不改。"""
    field_to_env = {
        "ai_base_url": "AI_BASE_URL", "ai_api_key": "AI_API_KEY", "ai_model": "AI_MODEL",
        "ai_vision_base_url": "AI_VISION_BASE_URL",
        "ai_vision_api_key": "AI_VISION_API_KEY",
        "ai_vision_model": "AI_VISION_MODEL",
    }
    updates = {}
    for field, env_key in field_to_env.items():
        val = getattr(body, field)
        if val:
            updates[env_key] = val
    if not updates:
        return {"saved": False, "detail": "无变更"}
    _write_env_and_reload(updates)
    changed = sorted(k for k in updates if "KEY" in k)
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="system_setting", target_id="ai_config",
              action_type="update", source="user", result="success",
              metadata={"changed_fields": sorted(updates.keys()), "key_fields_changed": changed})
    return {"saved": True}


@router.post("/ai/test")
def test_ai(vision: bool = False, user: CurrentUser = Depends(require_superadmin)):
    """测试 AI 连接。vision=False 测文案(DeepSeek)，vision=True 测视觉(Gemini 看图)。"""
    from ..core.ai_client import AiClient, vision_client
    client = vision_client() if vision else AiClient()
    label = "视觉" if vision else "文案"
    if not client.is_configured():
        return {"ok": False, "detail": f"{label} AI 未配置（key 为空）"}
    try:
        # max_tokens 留够：gemini-2.5-flash 是 thinking 模型，10 token 会被推理吃光→空 content
        resp = client.chat([{"role": "user", "content": "回复 OK"}], temperature=0, max_tokens=64)
        return {"ok": True, "detail": resp[:50]}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:120]}


def _get_sys_setting(key: str) -> str | None:
    from ..models.system import SystemSetting
    from ..core.database import SuperSessionLocal
    sdb = SuperSessionLocal()
    try:
        row = sdb.query(SystemSetting).filter(SystemSetting.key == key).first()
        return (row.value or "").strip().strip('"') if row and row.value else None
    finally:
        sdb.close()


def _set_sys_setting(key: str, value: str) -> None:
    from ..models.system import SystemSetting
    from ..core.database import SuperSessionLocal
    sdb = SuperSessionLocal()
    try:
        row = sdb.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row:
            row.value = json.dumps(value)
        else:
            sdb.add(SystemSetting(key=key, value=json.dumps(value)))
        sdb.commit()
    finally:
        sdb.close()


# ── CF 配置（超管）──
class CfConfigIn(BaseModel):
    cf_api_token: str = ""
    cf_account_id: str = ""
    cf_email_token: str = ""  # 用户级 token（Email Routing 地址/规则管理专用，可选）


@router.get("/cf")
def get_cf_config(user: CurrentUser = Depends(require_superadmin)):
    """返回当前 CF 配置（token 脱敏）。"""
    token = settings.cf_api_token or ""
    masked = token[:6] + "***" + token[-4:] if len(token) > 10 else ("***" if token else "")
    etok = _get_sys_setting("cf_email_token") or ""
    emasked = etok[:6] + "***" + etok[-4:] if len(etok) > 10 else ("***" if etok else "")
    return {
        "cf_api_token_masked": masked,
        "cf_api_token_set": bool(token),
        "cf_account_id": settings.cf_account_id or "",
        "cf_email_token_masked": emasked,
        "cf_email_token_set": bool(etok),
    }


def _clean_token(v: str) -> str:
    """token/ID 清洗：去首尾空白 + 去成对包裹引号（复制粘贴常带）。"""
    v = (v or "").strip()
    for q in ('"', "'"):
        if len(v) >= 2 and v.startswith(q) and v.endswith(q):
            v = v[1:-1].strip()
    return v


@router.put("/cf")
def set_cf_config(body: CfConfigIn, user: CurrentUser = Depends(require_superadmin)):
    """更新 CF 配置 → 写 .env + 更新运行时 settings（即时生效，免重启）。"""
    from pathlib import Path
    env_path = Path("/opt/toveads/backend/.env")
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updates = {}
    if body.cf_api_token:
        updates["CF_API_TOKEN"] = _clean_token(body.cf_api_token)
    if body.cf_account_id:
        updates["CF_ACCOUNT_ID"] = _clean_token(body.cf_account_id)
    if body.cf_email_token:
        _set_sys_setting("cf_email_token", _clean_token(body.cf_email_token))  # SystemSetting（不入 .env）
    if not updates:
        return {"saved": False, "detail": "无变更"}
    updated_lines, found = [], set()
    for line in lines:
        s = line.strip()
        if "=" in s:
            k = s.split("=", 1)[0]
            if k in updates:
                updated_lines.append(f"{k}={updates[k]}"); found.add(k); continue
        updated_lines.append(line)
    for k, v in updates.items():
        if k not in found:
            updated_lines.append(f"{k}={v}")
    env_path.write_text("\n".join(updated_lines) + "\n")
    if "CF_API_TOKEN" in updates:
        settings.cf_api_token = updates["CF_API_TOKEN"]
    if "CF_ACCOUNT_ID" in updates:
        settings.cf_account_id = updates["CF_ACCOUNT_ID"]
    return {"saved": True}


# ── 数据保留（超管）── 各表老数据保留天数，0=永久
class RetentionIn(BaseModel):
    days: dict = {}  # {table: days}，缺省用默认


@router.get("/retention")
def get_retention(user: CurrentUser = Depends(require_superadmin), db: Session = Depends(get_db)):
    cfg = get_retention_config(db)
    return {
        "tables": [{"key": t, "label": m["label"], "days": m["days"], "col": m["col"]} for t, m in cfg.items()],
        "last_run": get_last_run(db),
    }


@router.put("/retention")
def set_retention(body: RetentionIn, user: CurrentUser = Depends(require_superadmin),
                  db: Session = Depends(get_db)):
    save_retention_config(db, body.days)
    return get_retention(user=user, db=db)


@router.post("/retention/run")
def run_retention_now(user: CurrentUser = Depends(require_superadmin)):
    """手动触发一次清理（不等每日 cron）。"""
    return run_data_retention()


@router.get("/fx")
def get_fx(user: CurrentUser = Depends(require_superadmin), db: Session = Depends(get_db)):
    """当前汇率快照（止损 to_usd 用）。"""
    from ..models.perf import CurrencyRate
    rows = db.query(CurrencyRate).order_by(CurrencyRate.code).all()
    return {"rates": [{"code": r.code, "rate": r.rate, "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None} for r in rows],
            "count": len(rows)}


@router.post("/fx/run")
def run_fx_now(user: CurrentUser = Depends(require_superadmin)):
    """手动拉一次实时汇率（不等每日 cron）。"""
    from ..services.fx_sync import run_fx_sync
    return run_fx_sync()


@router.get("/keepalive")
def get_keepalive(user: CurrentUser = Depends(require_permission("ads.pause")), db: Session = Depends(get_db)):
    from ..core.keepalive_config import get_keepalive_config
    return get_keepalive_config(db, user.tenant_id)


@router.put("/keepalive")
def set_keepalive(body: dict, user: CurrentUser = Depends(require_permission("ads.pause")),
                  db: Session = Depends(get_db)):
    from ..core.keepalive_config import save_keepalive_config
    return save_keepalive_config(db, user.tenant_id, body)


# ── FB Webhook 配置（超管）── verify_token 存 system_settings，App Secret 复用 fb_apps 表
class WebhookIn(BaseModel):
    verify_token: str = ""


@router.get("/webhook")
def get_webhook(user: CurrentUser = Depends(require_superadmin), db: Session = Depends(get_db)):
    """返回 webhook 配置：公开 URL（只读）+ verify_token（脱敏）+ active App 数。"""
    from ..core.webhook_config import get_webhook_config
    from ..models.fb_app import FbApp
    cfg = get_webhook_config(db)
    vt = cfg["verify_token"]
    masked = (vt[:4] + "***" + vt[-3:]) if vt and len(vt) > 8 else ("***" if vt else "")
    apps = db.query(FbApp).filter(FbApp.status == "active").all()
    return {
        "public_url": cfg["public_url"],
        "verify_token_masked": masked,
        "verify_token_set": bool(vt),
        "verify_token_is_default": vt == "toveads_webhook_verify",
        "active_apps": len(apps),
        "app_names": [a.name or f"App {a.app_id}" for a in apps],
    }


@router.put("/webhook")
def set_webhook(body: WebhookIn, user: CurrentUser = Depends(require_superadmin),
                db: Session = Depends(get_db)):
    """更新 verify_token（空=恢复默认值）。DB 即时生效，免重启。"""
    from ..core.webhook_config import save_webhook_config
    save_webhook_config(db, body.verify_token)
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="system_setting", target_id="fb_webhook",
              action_type="update", source="user", result="success",
              metadata={"field": "verify_token"})
    return {"saved": True}


# ── 邮箱转发（超管）── CF Email Routing 产品化：平台域（tovaads.com）别名 → 目的地邮箱
# 库表 email_routes（系统级，tenant_id 恒 NULL）照 tt_apps 先例；写路径走 super session
# （BYPASSRLS——0075 收紧后 RLS 会话写不了系统行）。
# CF 侧模型：目的地邮箱（addresses，CF 发验证邮件）→ 转发规则（rules，matchers=收件地址
# literal，actions=forward 到 address_id）。规则只能指向已验证的 address_id。
import re as _re
from urllib.parse import urlparse as _urlparse

from ..core.database import get_system_db
from ..core.cf_client import CfClient
from ..models.system import EmailRoute

_ALIAS_RE = _re.compile(r"^[a-z0-9._-]+$")
_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _em_domain() -> str:
    """平台主域（Email Routing 的 zone，从 frontend_base_url 取 host）。"""
    host = _urlparse(settings.frontend_base_url or "https://tovaads.com").hostname or ""
    return host.lower().strip()


def _em_ctx() -> tuple[CfClient, str, str]:
    """邮箱转发专用 CfClient：优先用户级 cf_email_token（Email Routing 的地址/规则
    端点只支持用户级 token；账户级 cfat_ 会 404/10405），无则回退主 token（能做
    启用/DNS，做不了地址/规则）。"""
    acct = _clean_token(os.environ.get("CF_ACCOUNT_ID") or settings.cf_account_id or "")
    token = _clean_token(_get_sys_setting("cf_email_token")
                         or os.environ.get("CF_API_TOKEN")
                         or settings.cf_api_token or "")
    if not token or not acct:
        raise HTTPException(500, "CF 未配置，请先在「域名服务配置」填 Token 和账户 ID")
    cf = CfClient(token, acct)
    domain = _em_domain()
    # zone_id 优先取缓存（查 zone 需要 Zone:Read——用户级邮箱 token 通常没配这个，
    # 但 Email Routing 端点只需要 zone_id 在 URL 路径里，不需要 Zone:Read）
    zid = _get_sys_setting(f"cf_zone_id_{domain}")
    if not zid:
        zid = cf.get_zone_id(domain)
        if zid:
            _set_sys_setting(f"cf_zone_id_{domain}", zid)  # 缓存，后续 token 不再需要 Zone:Read
    if not zid:
        raise HTTPException(400, "CF 上找不到平台域名的 Zone（域名须托管在 CF，或主 Token 缺 Zone:Read 权限——可先用主 Token 访问一次邮箱转发页自动缓存）")
    return cf, zid, domain


def _addr_verified(a: dict) -> bool:
    """CF 目的地地址是否已验证（verified 布尔 / status 字符串两种返回形状都兼容）。"""
    v = a.get("verified")
    if isinstance(v, bool):
        return v
    return str(a.get("status", "")).lower() == "verified"


def _dns_key(rec: dict) -> tuple:
    """DNS 记录比对键（type+name+content 归一：大小写/尾点/引号不敏感）。
    TXT 超 255 字符时 zone 里是两段带引号拼接（\"...\" \"...\"），而
    get_email_dns 返回连续串——剥掉全部引号+内部空白后比对才命中。"""
    content = str(rec.get("content", "")).rstrip(".").lower().strip()
    content = content.replace('"', " ").replace(" ", "")
    return (str(rec.get("type", "")).upper().strip(),
            str(rec.get("name", "")).rstrip(".").lower().strip(),
            content)


def _em_missing_dns(cf: CfClient, zid: str) -> list:
    """Email Routing 所需 DNS 与现有记录对比，返回缺口（MX/TXT）。"""
    need = cf.get_email_dns(zid)
    have_keys = {_dns_key(r) for r in cf.list_dns_records(zid)}
    return [rec for rec in need if _dns_key(rec) not in have_keys]


def _route_dict(r: EmailRoute, domain: str, cf_rules: dict) -> dict:
    cf_enabled = (cf_rules.get(r.rule_id) or {}).get("enabled") if r.rule_id else None
    return {"id": r.id, "alias": r.alias, "alias_email": f"{r.alias}@{domain}",
            "destination_email": r.destination_email, "enabled": bool(r.enabled),
            "cf_enabled": cf_enabled,
            "created_at": r.created_at.isoformat() if r.created_at else None}


@router.get("/email-routing")
def get_email_routing(user: CurrentUser = Depends(require_superadmin),
                      db: Session = Depends(get_system_db)):
    """CF 实时状态（routing 状态/DNS 缺口/目的地邮箱）+ 本地映射 join CF 规则启停。"""
    cf, zid, domain = _em_ctx()
    routing = cf.get_email_routing(zid) or {}
    # CF status: uninitialized/unconfigured/ready/enabled/disabled——ready 即已启用且 DNS 就绪
    raw_status = routing.get("status") or "unconfigured"
    status = "enabled" if raw_status == "ready" else raw_status
    missing = _em_missing_dns(cf, zid) if status in ("enabled", "disabled") else []
    # 地址/规则端点只支持用户级 token——账户级会 404/10405（非 JSON 响应→JSONDecodeError）
    token_ok = True
    addresses: list = []
    cf_rules: dict = {}
    if status in ("enabled", "disabled"):
        try:
            addresses = cf.list_email_addresses(zid)
        except Exception as e:
            token_ok = _get_sys_setting("cf_email_token") is not None  # 已配用户级仍失败=真错
            if token_ok:
                raise HTTPException(502, f"CF 读取目的地邮箱失败：{str(e)[:150]}")
        if status == "enabled" and token_ok:
            try:
                cf_rules = {r.get("id"): r for r in cf.list_email_rules(zid)}
            except Exception as e:
                raise HTTPException(502, f"CF 读取转发规则失败：{str(e)[:150]}")
    rows = db.query(EmailRoute).order_by(EmailRoute.alias).all()
    return {
        "domain": domain,
        "status": status,
        "dns_ready": status == "enabled" and not missing,
        "token_ok": token_ok,
        "missing_dns": [{"type": m.get("type"), "name": m.get("name"), "content": m.get("content")}
                        for m in missing],
        "addresses": [{"id": a.get("id"), "email": a.get("email"), "verified": _addr_verified(a)}
                      for a in addresses],
        "routes": [_route_dict(r, domain, cf_rules) for r in rows],
    }


@router.post("/email-routing/enable")
def enable_email_routing(user: CurrentUser = Depends(require_superadmin),
                         db: Session = Depends(get_system_db)):
    """启用 Email Routing + 自动补缺失 DNS（MX/TXT；域名 DNS 在 CF 托管可自动写）。"""
    cf, zid, domain = _em_ctx()
    try:
        cf.enable_email_routing(zid)
    except RuntimeError as e:
        raise HTTPException(502, str(e)[:300])
    added = 0
    for rec in _em_missing_dns(cf, zid):
        try:
            cf.add_dns_record(zid, {"type": rec.get("type"), "name": rec.get("name"),
                                    "content": rec.get("content"),
                                    "priority": rec.get("priority", 0),
                                    "proxied": bool(rec.get("proxied", False))})
            added += 1
        except RuntimeError as e:
            # 幂等：CF 81058=identical record already exists（比对归一后仍可能因
            # 拆段/格式差异未命中）——已存在就是我们要的终态，跳过不炸
            if "81058" in str(e) or "identical record" in str(e).lower():
                continue
            raise HTTPException(502, f"DNS 记录补齐失败（已补 {added} 条）：{str(e)[:200]}")
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="system_setting", target_id="email_routing",
              action_type="update", source="user", result="success",
              metadata={"action": "enable", "dns_added": added, "domain": domain})
    db.commit()
    return {"status": "enabled", "dns_added": added}


class EmailDestinationIn(BaseModel):
    email: str


@router.post("/email-routing/destinations")
def add_email_destination(body: EmailDestinationIn,
                          user: CurrentUser = Depends(require_superadmin),
                          db: Session = Depends(get_system_db)):
    """添加目的地邮箱。CF 立即发验证邮件（pending → 用户点链接后 verified）。幂等：已存在直接返回。"""
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "目的地邮箱格式不正确")
    cf, zid, _ = _em_ctx()
    # 地址列表端点对账户级 token 返回非 JSON（404）——cf_client 已容错为 success=False，
    # 此处给用户级 token 引导而非 500
    try:
        existing = [a for a in cf.list_email_addresses(zid)
                    if str(a.get("email", "")).lower() == email]
    except Exception as e:
        existing = []
    if existing:
        a = existing[0]
        return {"id": a.get("id"), "email": a.get("email", email),
                "verified": _addr_verified(a), "existed": True}
    try:
        a = cf.create_email_address(zid, email)
    except RuntimeError as e:
        _msg = str(e)
        if "10405" in _msg or "404" in _msg or "not found" in _msg.lower():
            raise HTTPException(400, "当前 CF Token 不支持邮箱地址管理（账户级 token 的限制）。请到「域名服务配置 → 邮箱管理 Token」填入用户级 API Token 后重试")
        raise HTTPException(502, _msg[:300])
    # create 返回 success=False（如 405/404 = 账户级 token 不支持此端点）→ 引导配用户级
    if not a.get("id") and not a.get("email"):
        _errs = str(a.get("errors", ""))
        if "404" in _errs or "405" in _errs or "10405" in _errs or "not found" in _errs.lower():
            raise HTTPException(400, "当前 CF Token 不支持邮箱地址管理（账户级 token 的限制）。请到「域名服务配置 → 邮箱管理 Token」填入用户级 API Token 后重试")
        raise HTTPException(502, f"CF 添加目的地邮箱失败：{_errs[:200]}")
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="system_setting", target_id="email_routing",
              action_type="create", source="user", result="success",
              metadata={"destination": email})
    db.commit()
    return {"id": a.get("id"), "email": a.get("email", email),
            "verified": _addr_verified(a), "existed": False}


@router.delete("/email-routing/destinations/{address_id}")
def delete_email_destination(address_id: str, user: CurrentUser = Depends(require_superadmin),
                             db: Session = Depends(get_system_db)):
    """删目的地邮箱。被本地映射引用时 400（先删映射）。"""
    cf, zid, _ = _em_ctx()
    target = next((a for a in cf.list_email_addresses(zid) if a.get("id") == address_id), None)
    if not target:
        raise HTTPException(404, "目的地邮箱不存在或已删除")
    email = str(target.get("email", "")).lower()
    used = db.query(EmailRoute).filter(
        func.lower(EmailRoute.destination_email) == email).count()
    if used:
        raise HTTPException(400, "该邮箱已被转发映射引用，请先删除对应映射")
    cf.delete_email_address(zid, address_id)
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="system_setting", target_id="email_routing",
              action_type="delete", source="user", result="success",
              metadata={"destination": email})
    db.commit()
    return {"deleted": True}


class EmailRouteIn(BaseModel):
    alias: str
    destination_email: str


@router.post("/email-routing/routes")
def create_email_route(body: EmailRouteIn, user: CurrentUser = Depends(require_superadmin),
                       db: Session = Depends(get_system_db)):
    """建转发映射：alias@平台域 → 目的地邮箱。目的地必须已验证（CF 规则只收 verified address_id）。"""
    alias = body.alias.strip().lower()
    if not alias or not _ALIAS_RE.match(alias):
        raise HTTPException(400, "别名只允许小写字母、数字和 . _ - ")
    if db.query(EmailRoute).filter(EmailRoute.alias == alias).first():
        raise HTTPException(400, "别名已存在，请换一个")
    email = body.destination_email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "目的地邮箱格式不正确")
    cf, zid, domain = _em_ctx()
    routing = cf.get_email_routing(zid) or {}
    if routing.get("status") not in ("enabled", "ready"):
        raise HTTPException(400, "Email Routing 未启用，请先启用")
    target = next((a for a in cf.list_email_addresses(zid)
                   if str(a.get("email", "")).lower() == email), None)
    if not target:
        raise HTTPException(400, "目的地邮箱未添加，请先在目的地邮箱区添加")
    if not _addr_verified(target):
        raise HTTPException(400, "目的地邮箱待验证：请先到该邮箱点开 CF 验证邮件")
    alias_email = f"{alias}@{domain}"
    try:
        rule = cf.create_email_rule(zid, alias_email, target["id"])
    except RuntimeError as e:
        raise HTTPException(502, str(e)[:300])
    row = EmailRoute(alias=alias, destination_email=email, rule_id=rule.get("id"), enabled=True)
    db.add(row)
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="system_setting", target_id="email_routing",
              action_type="create", source="user", result="success",
              metadata={"alias": alias_email, "destination": email, "cf_rule_id": rule.get("id")})
    db.commit()
    return _route_dict(row, domain, {rule.get("id"): rule} if rule.get("id") else {})


class EmailRoutePatch(BaseModel):
    enabled: bool


@router.patch("/email-routing/routes/{route_id}")
def toggle_email_route(route_id: int, body: EmailRoutePatch,
                       user: CurrentUser = Depends(require_superadmin),
                       db: Session = Depends(get_system_db)):
    """启停映射（CF 规则 + 本地行双写）。"""
    row = db.get(EmailRoute, route_id)
    if not row:
        raise HTTPException(404, "映射不存在")
    cf, zid, _ = _em_ctx()
    if row.rule_id:
        try:
            cf.set_email_rule_enabled(zid, row.rule_id, body.enabled)
        except RuntimeError as e:
            raise HTTPException(502, str(e)[:300])
    row.enabled = body.enabled
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="system_setting", target_id="email_routing",
              action_type="update", source="user", result="success",
              metadata={"alias": row.alias, "enabled": body.enabled})
    db.commit()
    return {"id": row.id, "alias": row.alias, "enabled": bool(row.enabled)}


@router.delete("/email-routing/routes/{route_id}")
def delete_email_route(route_id: int, user: CurrentUser = Depends(require_superadmin),
                       db: Session = Depends(get_system_db)):
    """删映射：先删 CF 规则（404=已不存在，放行）再删本地行。"""
    row = db.get(EmailRoute, route_id)
    if not row:
        raise HTTPException(404, "映射不存在")
    cf, zid, _ = _em_ctx()
    if row.rule_id:
        try:
            cf.delete_email_rule(zid, row.rule_id)
        except Exception as e:
            raise HTTPException(502, f"CF 删除规则失败：{str(e)[:200]}")
    db.delete(row)
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="system_setting", target_id="email_routing",
              action_type="delete", source="user", result="success",
              metadata={"alias": row.alias, "destination": row.destination_email})
    db.commit()
    return {"deleted": True}
