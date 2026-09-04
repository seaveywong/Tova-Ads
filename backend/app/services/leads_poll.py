# -*- coding: utf-8 -*-
"""潜客轮询（并行 webhook 路径，1.0 同款模式）。

背景：webhook 卡 FB 审核（pages_manage_metadata + 回调配置），轮询走 /{ad_id}/leads
（leads_retrieval scope，现有令牌已具备——2026-08-05 smoke 过）不依赖审核。
范围：managed FB 账户今日有消耗的广告（花钱的才可能有 lead，控 API 量）；
FB 后台直接建的表单也覆盖（按广告拉，不依赖 LeadFormTemplate 登记）。
窗口：近 2h 滚动（10 分钟一轮，12 倍重叠），lead_id 去重幂等；停摆 >2h 由手动 /leads/sync 兜底。
通知：新 lead 聚合一条，1h dedup（防轮询 spam，leads.py 同款模式）。
"""
import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import func as _f

from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
from ..core.fb_tokens import client_for_account
from ..core.fb_client import FbApiError
from ..core.encryption import decrypt
from ..models.lead import Lead
from ..models.perf import PerfSnapshot
from ..routers.leads import _parse_created_time   # created_time 解析（FB ISO → datetime）

logger = logging.getLogger("toveads.leads_poll")

LOCK_KEY = 117            # 101-116 已占（见 TECH_REVIEW 锁号表）
POLL_WINDOW_HOURS = 2     # 滚动窗口（与 10 分钟轮询重叠 12 倍）
MAX_ADS_PER_TICK = 150    # API 量上限；超限跳过（下轮再拉，窗口重叠保证不丢）


def _leads_notify(db, tenant_id: int, synced: int, ads_hit: int) -> None:
    """新潜客聚合通知（1h dedup + write_log 配对——dedup 查 action_logs，无配对永不命中）."""
    from ..core.notify_utils import emit_notification, dedup_recent
    from ..core.log_utils import write_log, new_trace_id
    try:
        if dedup_recent(db, tenant_id, "leads_new", None, 60):
            return
        _tid = new_trace_id()
        write_log(db, tenant_id=tenant_id, trace_id=_tid, actor_type="system",
                  action_type="leads_new", source="leads_poll",
                  target_type="lead", result="success",
                  metadata={"synced": synced, "ads": ads_hit})
        emit_notification(
            db, tenant_id=tenant_id, level="info",
            event_type="leads_new",
            title=f"新潜客 × {synced}",
            body=f"轮询同步到 {synced} 条新潜客（{ads_hit} 个在投广告）。\n到 AdManager → 潜客 查看或导出。",
            roles=["owner", "operator"], trace_id=_tid, platform="fb")
    except Exception:
        pass   # 通知失败不阻断轮询


def run_leads_poll():
    """每 10 分钟：对今日有消耗的 FB 广告拉近 2h 潜客，新 lead 入库（lead_id 去重）。"""
    lock = acquire_run_lock(LOCK_KEY)
    if not lock:
        return {"skipped": "lock_busy"}
    db = SuperSessionLocal()
    since = datetime.now(timezone.utc) - timedelta(hours=POLL_WINDOW_HOURS)
    total_synced = 0
    synced_by_tenant: dict = {}
    ads_polled = 0
    skipped_over_cap = 0
    try:
        # 今日有消耗广告（按 账户业务日快照；spend>0 才可能产生 lead）
        from ..models.fb import Account
        biz_like_today = datetime.now(timezone.utc).astimezone(
            timezone(timedelta(hours=8))).strftime("%Y-%m-%d")   # 北京业务日（快照口径）
        rows = db.query(
            PerfSnapshot.tenant_id, PerfSnapshot.act_id, PerfSnapshot.ad_id
        ).join(Account, Account.act_id == PerfSnapshot.act_id).filter(
            PerfSnapshot.snapshot_date == biz_like_today,
            PerfSnapshot.spend > 0,
            PerfSnapshot.platform == "fb",
            Account.is_managed.is_(True),
            Account.account_status.notin_([2, 8, 100, 101]),
        ).distinct().all()
        if len(rows) > MAX_ADS_PER_TICK:
            skipped_over_cap = len(rows) - MAX_ADS_PER_TICK
            rows = rows[:MAX_ADS_PER_TICK]
        # 按租户+账户分组取 token
        by_tenant: dict = {}
        for r in rows:
            by_tenant.setdefault((r[0], r[1]), []).append(r[2])
        for (tenant_id, act_id), ad_ids in by_tenant.items():
            fb = client_for_account(db, tenant_id, act_id, "read")
            if not fb:
                continue
            for ad_id in ad_ids:
                ads_polled += 1
                try:
                    leads_data = fb.get_leads(ad_id, limit=100, since_ts=since)
                except FbApiError as e:
                    logger.warning("[LeadsPoll] ad=%s 拉取失败: %s", ad_id, e.friendly)
                    continue
                for ld in leads_data:
                    lid = ld.get("id")
                    if not lid:
                        continue
                    try:
                        _ct = _parse_created_time(ld.get("created_time"))
                    except Exception:
                        _ct = None
                    if _ct and _ct < since:
                        continue   # 窗口外（FB 过滤失效兜底）
                    exists = db.query(Lead.id).filter(
                        Lead.tenant_id == tenant_id, Lead.lead_id == lid).first()
                    if exists:
                        continue
                    db.add(Lead(
                        tenant_id=tenant_id,
                        ad_id=str(ld.get("ad_id")) if ld.get("ad_id") else str(ad_id),
                        form_id=str(ld.get("form_id")) if ld.get("form_id") else None,
                        lead_id=lid,
                        field_data_json=json.dumps(ld.get("field_data", [])),
                        created_time=_ct,
                    ))
                    total_synced += 1
                    synced_by_tenant[tenant_id] = synced_by_tenant.get(tenant_id, 0) + 1
            # 每账户一 commit（粒度小，失败影响面小）
            db.commit()
        # 新潜客通知：按租户各自计数聚合
        for tid, n in synced_by_tenant.items():
            _leads_notify(db, tid, n, ads_polled)
        if synced_by_tenant:
            db.commit()
        res = {"polled": ads_polled, "synced": total_synced, "skipped_over_cap": skipped_over_cap}
        logger.info("[LeadsPoll] %s", res)
        return res
    except Exception:
        db.rollback()
        logger.exception("[LeadsPoll] 轮询异常")
        return {"error": "poll_failed"}
    finally:
        db.close()
        release_run_lock(lock, LOCK_KEY)
