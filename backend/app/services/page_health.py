# -*- coding: utf-8 -*-
"""主页健康扫描（2026-09-27）：主页挂了/禁用的感知 + 影响面告警。

判据（CLI 实测定案，2026-09-27 服务器真实令牌验证）：
- /me/accounts 的 is_published=False = 未发布/下架（job82 部署失败实证页 Mebrelablo
  Plogordmire 返 False；管理员令牌可读、无需新权限）
- promotion_eligible=False = 不可投广告（伴随未发布出现）
- 页从全部令牌列表消失 → 单页 GET 复核：error code 100/subcode 33 = 已删/不可达
- FB Page webhook 无状态字段可订阅（官方字段表核实）——只能轮询；每令牌每轮 1 次调用

影响面：ads_cache 每广告 creative.effective_object_story_id 前缀即 page_id（与资产页
「关联广告数」同源，fb.py pages-overview），叠加在投状态过滤 + 账户聚合。
告警：critical + dedup_recent 6h/page（notify-dedup-mandatory 铁律）+ NO_CAP_EVENTS。
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import text as _t

from ..core.database import SuperSessionLocal, acquire_run_lock, release_run_lock
from ..core.encryption import decrypt
from ..core.fb_client import FbClient
from ..core.log_utils import new_trace_id, write_log
from ..core.notify_utils import emit_notification, dedup_recent
from ..models.fb import FbCredential, PageHealth

logger = logging.getLogger("toveads.page_health")

# 在投状态（影响面只数真正在跑的广告——DISAPPROVED/PAUSED 不算）
_LIVE_STATUSES = ("ACTIVE", "IN_PROCESS", "LEARNING", "LEARNING_COMPLETED")


def page_impact(db, tenant_id: int, page_id: str) -> dict:
    """主页 → 影响面：{ads_total, ads_live, live_acts, live_names}。
    解析 ads_cache.ads_json 的 creative.effective_object_story_id（{page_id}_{post_id}），
    前缀匹配 + 在投状态过滤 + 账户去重（与 pages-overview 的 live_ads 同源，口径补状态过滤）。
    by_owner：在投广告按账户归属人分组（告警归属路由用——2026-09-27 用户确认推归属人）；
    total_owners：关联广告（任意状态）的归属人集合（恢复通知路由用）。"""
    total = live = 0
    live_acts: set = set()
    live_names: list = []
    owner_of: dict = {}   # act_id → owner_user_id
    acc_names: dict = {}  # act_id → 账户名（告警清单用）
    total_owners: set = set()
    rows = db.execute(_t(
        "SELECT act_id, ads_json FROM ads_cache WHERE tenant_id = :t AND platform = 'fb' "
        "AND ads_json IS NOT NULL"), {"t": tenant_id}).fetchall()
    owner_rows = db.execute(_t(
        "SELECT act_id, owner_user_id FROM accounts WHERE tenant_id = :t"), {"t": tenant_id}).fetchall()
    for aid, ou, nm in db.execute(_t(
            "SELECT act_id, owner_user_id, name FROM accounts WHERE tenant_id = :t"),
            {"t": tenant_id}).fetchall():
        owner_of[aid] = ou
        acc_names[aid] = nm or aid
    prefix = f"{page_id}_"
    by_owner: dict = {}
    for act_id, blob in rows:
        try:
            import json
            ads = json.loads(blob or "[]")
        except Exception:
            continue
        for ad in ads:
            story = str(((ad.get("creative") or {}).get("effective_object_story_id")) or "")
            if not story.startswith(prefix):
                continue
            total += 1
            if owner_of.get(act_id):
                total_owners.add(owner_of[act_id])
            if str(ad.get("effective_status") or "") in _LIVE_STATUSES:
                live += 1
                live_acts.add(act_id)
                if len(live_names) < 5:
                    live_names.append(str(ad.get("name") or "")[:40])
                ou = owner_of.get(act_id)
                if ou:
                    ent = by_owner.setdefault(ou, {"acts": set(), "ads": 0, "names": [],
                                                   "campaigns": {}})   # cid → cname（处置用）
                    ent["acts"].add(act_id)
                    ent["ads"] += 1
                    if len(ent["names"]) < 5:
                        ent["names"].append(str(ad.get("name") or "")[:40])
                _cid = str(ad.get("campaign_id") or "")
                if _cid and str(ad.get("effective_status") or "") in _LIVE_STATUSES:
                    for _oe in by_owner.values():
                        if act_id in _oe["acts"]:
                            _oe["campaigns"].setdefault(_cid, str(ad.get("name") or "")[:40])
    return {"ads_total": total, "ads_live": live, "live_acts": live_acts,
            "live_names": live_names, "by_owner": by_owner, "total_owners": total_owners,
            "acc_names": acc_names}


def _fmt_impact(imp: dict) -> str:
    """影响面文案：在投广告 N 个 / M 个账户（+前 5 个广告名）；无在投时给关联总数。"""
    if imp["ads_live"]:
        names = "、".join(n for n in imp["live_names"] if n)
        return (f"影响 {imp['ads_live']} 个在投广告 / {len(imp['live_acts'])} 个账户"
                + (f"（{names}…）" if names else ""))
    return f"当前无在投广告（关联广告 {imp['ads_total']} 个）"


def _fmt_owner_impact(ent: dict, acc_names: dict | None = None) -> str:
    acts = "、".join(f"{(acc_names or {}).get(a, a)}（act_{a}）" for a in list(ent["acts"])[:5])
    return (f"影响你名下 {ent['ads']} 个在投广告 / {len(ent['acts'])} 个账户"
            + (f"：{acts}" + ("等" if len(ent["acts"]) > 5 else "") if acts else ""))


def _quarantine_page_campaigns(db, tenant_id: int, imp: dict) -> dict:
    """主页挂了自动处置（用户拍板 2026-09-27）：受影响在投广告所在系列——改名加
    《主页不可用》标记 + 暂停（止血）+ 回读确认（资金操作二次回读铁律）。
    恢复不自动还原（开启+改名留人工，告警有提示）。
    返 {"paused": [(act,cid,cname)], "failed": ["act/cid: 原因"]}。"""
    from ..core.fb_tokens import _account_write_candidates
    from ..core.encryption import decrypt
    paused, failed, seen = [], [], set()
    for ent in (imp.get("by_owner") or {}).values():
        for cid, cname in (ent.get("campaigns") or {}).items():
            if cid in seen:
                continue
            act_id = next(iter(ent["acts"]), "")
            seen.add(cid)
            try:
                cands = _account_write_candidates(db, tenant_id, act_id, "write")
                if not cands:
                    failed.append(f"{act_id}/{cid}: 无可用写令牌")
                    continue
                fb = FbClient(decrypt(cands[0].access_token_enc))
                cur_name = str((fb.get(f"/{cid}", params={"fields": "name"}) or {}).get("name") or cname)
                if "《主页不可用》" not in cur_name:
                    fb.rename_node(cid, f"{cur_name[:360]}《主页不可用》")
                fb.update_status(cid, "PAUSED")
                chk = fb.get(f"/{cid}", params={"fields": "effective_status"})
                if str(chk.get("effective_status") or "") != "PAUSED":
                    failed.append(f"{act_id}/{cid}: 回读非 PAUSED（{chk.get('effective_status')}）")
                    continue
                paused.append((act_id, cid, cur_name[:40]))
            except Exception as e:
                failed.append(f"{act_id}/{cid}: {(getattr(e, 'friendly', None) or str(e))[:80]}")
    if paused or failed:
        logger.info(f"[PageHealth] 处置: 暂停 {len(paused)} 系列, 失败 {len(failed)}")
    return {"paused": paused, "failed": failed}


def _emit_page_alert(db, tenant_id: int, ph: PageHealth, level: str, event_type: str,
                     title: str, body: str, imp: dict | None = None) -> None:
    """告警 + dedup 锚点 + 留痕（dedup 6h/page；NO_CAP_EVENTS 见 notify_utils）。
    归属路由（2026-09-27 用户确认推归属人，不广播）：有受影响在投广告 → 逐归属人
    发（body 带该人名下影响面，站内信/TG 均只达本人）；无在投 → owner 角色广播
    （团队 owner 知悉即可，不扰 operator）。dedup_recent 返回 True=近期已发应跳过
    （此处曾写反致告警永不发出——smoke 断言抓出）。
    窗口 24h（用户拍板 2026-09-27「同一主页推一次就够」——曾 6h）。"""
    if dedup_recent(db, tenant_id, event_type, str(ph.page_id), 1440):
        return
    targets: list = []   # [(user_id|None, body)]
    if imp and imp.get("by_owner"):
        for ou, ent in imp["by_owner"].items():
            q_note = ""
            q = imp.get("quarantine") or {}
            if q.get("paused"):
                q_note += f"\n✅ 已自动暂停并标记《主页不可用》：{len(q['paused'])} 个系列"
            if q.get("failed"):
                q_note += f"\n⚠️ 处置失败 {len(q['failed'])} 项：{'；'.join(q['failed'][:2])}"
            targets.append((ou, f"{body}\n⚠️ {_fmt_owner_impact(ent, imp.get('acc_names'))}{q_note}"))
    elif imp and imp.get("total_owners"):
        for ou in imp["total_owners"]:   # 恢复/挂但无在投：按关联归属人路由
            targets.append((ou, body))
    else:
        targets.append((None, body))   # 无任何关联 → owner 角色广播
    for uid, b in targets:
        try:
            emit_notification(db, tenant_id=tenant_id, level=level, event_type=event_type,
                              title=title, body=b, user_id=uid, roles=["owner"],
                              trace_id=new_trace_id(), target_type="fb_page",
                              target_id=str(ph.page_id), force_tg=(level == "critical"))
        except Exception as e:
            logger.warning(f"[PageHealth] 告警发送失败 page {ph.page_id} uid={uid}: {e}")
    write_log(db, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
              target_type="fb_page", target_id=str(ph.page_id), action_type=event_type,
              # 锚点 action_type 必须与 dedup 键一致（复审 P1：曾写 "page_health" → 6h 去重永不命中）
              source="page_health", result="alerted",
              trigger_detail=title[:120], metadata={"page_id": ph.page_id,
                                                    "is_published": ph.is_published,
                                                    "owners": sorted((imp or {}).get("by_owner") or [])})


def run_page_health_scan() -> dict:
    """主页健康扫描（cron 每 1h，advisory lock 120）：
    逐租户逐令牌拉 /me/accounts（带 is_published）→ 聚合 per (tenant, page) →
    upsert 快照对比旧值 → 翻转告警（挂=critical / 恢复=info / 删除=critical）。
    多令牌可见同一页：任一令牌读到即 seen；is_published 取该页任一读数（页属性与令牌无关）。
    全部令牌都读不到 → 单页 GET 复核（100/33=已删；能读=更新）。"""
    lock = acquire_run_lock(122)   # 复审 P1：120 与 asset_scoring/domain_renewal 三撞（锁号唯一铁律）
    if not lock:
        return {"skipped": True}
    db = SuperSessionLocal()
    now = datetime.now(timezone.utc)
    alerted = recovered_cnt = upserted = 0
    try:
        creds = db.query(FbCredential).filter(
            FbCredential.status.in_(("active", "rate_limited")),
        ).all()   # FB 令牌表本身就是 FB 域（TT 在独立表），无平台列
        # (tenant, page_id) → 观测聚合
        seen_map: dict = {}
        cred_by_id = {c.id: c for c in creds}
        for c in creds:
            try:
                pages = FbClient(decrypt(c.access_token_enc)).get_pages() or []
            except Exception as e:
                from ..core.fb_tokens import mark_expired_on_auth_error
                mark_expired_on_auth_error(db, c, e)   # 批JJ：过期判死（非过期错 no-op）
                logger.warning(f"[PageHealth] cred {c.id} 拉主页失败: {str(e)[:90]}")
                continue
            for p in pages:
                pid = str(p.get("id") or "")
                if not pid:
                    continue
                ent = seen_map.setdefault((c.tenant_id, pid), {
                    "name": p.get("name") or pid, "cred_id": c.id,
                    "is_published": p.get("is_published", True) is not False,
                    "promotion_eligible": p.get("promotion_eligible")})
                # 任一令牌读到 published=True 即以 true 为准（页属性，读数应一致；防单令牌毛刺）
                if ent["is_published"] is False and p.get("is_published") is True:
                    ent["is_published"] = True
                    ent["cred_id"] = c.id
        # 对比 + upsert
        existing = {(ph.tenant_id, ph.page_id): ph for ph in db.query(PageHealth).all()}
        for (tenant_id, pid), obs in seen_map.items():
            ph = existing.get((tenant_id, pid))
            imp = None
            if ph is None:
                db.add(PageHealth(tenant_id=tenant_id, page_id=pid, name=obs["name"],
                                  via_cred_id=obs["cred_id"], is_published=obs["is_published"],
                                  promotion_eligible=obs["promotion_eligible"],
                                  seen=True, checked_at=now))
                upserted += 1
                continue   # 首轮建基线不告警（存量未发布页已知，不追溯轰炸）
            was_pub, now_pub = bool(ph.is_published), obs["is_published"]
            ph.name = obs["name"]; ph.via_cred_id = obs["cred_id"]
            ph.promotion_eligible = obs["promotion_eligible"]
            ph.seen = True; ph.checked_at = now
            if was_pub and not now_pub:
                imp = page_impact(db, tenant_id, pid)
                ph.is_published = False
                # 自动处置（用户拍板 2026-09-27）：受影响系列改名《主页不可用》+ 暂停 + 回读；
                # 结果进告警（恢复主页后开启+改名留人工）
                imp["quarantine"] = _quarantine_page_campaigns(db, tenant_id, imp)
                _emit_page_alert(
                    db, tenant_id, ph, "critical", "page_unavailable",
                    f"主页不可用 · {obs['name']}",
                    f"主页：{obs['name']}（{pid}）\n状态：<b>已取消发布/不可用</b>\n"
                    + (f"⚠️ {_fmt_impact(imp)}\n" if imp and not imp.get("by_owner") else "")
                    + "该主页下的广告可能被拒/无法投放，部署也会失败——请到 FB 恢复主页或换绑主页"
                    + ("；受影响系列已自动暂停并标记《主页不可用》，恢复主页后请手动开启并改名" if (imp.get("quarantine") or {}).get("paused") else ""),
                    imp=imp)
                alerted += 1
            elif not was_pub and now_pub:
                ph.is_published = True
                _emit_page_alert(
                    db, tenant_id, ph, "info", "page_recovered",
                    f"主页已恢复 · {obs['name']}",
                    f"主页：{obs['name']}（{pid}）\n状态：已重新发布，可正常投放",
                    imp=page_impact(db, tenant_id, pid))
                recovered_cnt += 1
            else:
                ph.is_published = now_pub
            upserted += 1
        # 消失页复核：上轮 seen 且本轮不可见 → 单页 GET（100/33=已删告警；能读=更新快照）
        for (tenant_id, pid), ph in existing.items():
            if (tenant_id, pid) in seen_map or not ph.seen:
                continue
            cred = cred_by_id.get(ph.via_cred_id or 0)
            fb = FbClient(decrypt(cred.access_token_enc)) if cred else None
            if not fb:
                # 复审 P2（高险）：探测令牌不可用时曾误判全部页 gone → 逐页 critical TG 风暴。
                # 跳过复核保留 seen 旧值（下轮令牌恢复再看），只记日志
                logger.warning(f"[PageHealth] page {pid} 复核跳过（探测令牌 #{ph.via_cred_id} 不可用）")
                continue
            gone = True
            if fb:
                try:
                    r = fb.get(f"/{pid}", params={"fields": "id,name,is_published"})
                    if r.get("id"):
                        gone = False
                        ph.seen = True; ph.checked_at = now
                        ph.is_published = r.get("is_published", ph.is_published) is not False
                        ph.name = r.get("name") or ph.name
                except Exception:
                    gone = True
            if gone:
                ph.seen = False; ph.checked_at = now
                imp = page_impact(db, tenant_id, pid)
                _emit_page_alert(
                    db, tenant_id, ph, "critical", "page_unavailable",
                    f"主页不可达 · {ph.name}",
                    f"主页：{ph.name}（{pid}）\n状态：<b>已删除或令牌失去访问</b>\n"
                    + (f"⚠️ {_fmt_impact(imp)}\n" if imp and imp.get("ads_live") and not imp.get("by_owner") else "")
                    + "请检查令牌授权或该主页是否已被删除",
                    imp=imp)
                alerted += 1
            upserted += 1
        db.commit()
        logger.info(f"[PageHealth] 扫描 {len(seen_map)} 页，告警 {alerted}，恢复 {recovered_cnt}")
        return {"pages": len(seen_map), "alerted": alerted,
                "recovered": recovered_cnt, "upserted": upserted}
    except Exception:
        logger.exception("[PageHealth] 扫描异常")
        db.rollback()
        return {"error": True}
    finally:
        db.close()
        release_run_lock(lock, 122)
