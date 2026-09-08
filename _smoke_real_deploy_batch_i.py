# -*- coding: utf-8 -*-
"""真投放实测脚本（批次 I+III 全链验证）——⚠️ 真金白银脚本，不自动跑，用户授权后手动执行。

验证目标（《总方案_v2_FB对齐》验证策略）：2.0 投放链首次真 FB 部署——
  {{ad.id}} 宏写入 / FB 回读 / 转化位置矩阵（website+自动建链 / messenger）/ promoted_object /
  细分版位（facebook_positions）/ 子码自动建链回绑 / ads_cache 归因对账 / 全链 PAUSED 零消耗。

用法（服务器 /opt/toveads/backend 下执行；需批次 III 代码已部署 restart 后）：
  venv/bin/python _smoke_real_deploy_batch_i.py \
      --act act_XXXXXXXX           # 必填：测试广告账户
      --lp 6                        # 必填：已发布 display 模式落地页 ID（组1 自动建链用）
      --asset 123                   # 必填：图片素材 ID（两组共用）
      --page 111111                 # 必填：FB 主页 ID（messenger 组 promoted_object 用）
      --pixel 999888                # 必填：FB 像素 ID（组1 website 转化用）
      [--msg-tpl 5]                 # 可选：Messenger 欢迎语模板 ID
      [--budget 2]                  # 可选：每组日预算 USD（默认 2 → 两组 $4/日，仅手动激活后消耗）
      [--country US]                # 可选：两组受众国家（默认 US）
      [--base http://127.0.0.1:8000]  # 可选：API 地址
      [--keep]                      # 可选：保留测试模板（默认保留并打印 id；--no-keep 归档）

预算与资金安全（铁律 no-protection-periods / 用户授权花钱）：
  - 两组节点 enabled=false → 部署后 FB 侧 adset/ad 全 PAUSED，campaign ACTIVE 但零消耗；
  - 部署前断言 will_spend=[]（预检口径）+ 部署后 FB 回读两条 ad 均 PAUSED（本脚本硬断言）；
  - 默认每组 $2/日（两组合计 $4/日/账户）——只有用户在 FB 后台/管理器手动激活广告才开始花钱；
  - 本脚本不激活任何广告、不修改已有广告、不删除任何对象；建出的对象 ID 全部落报告留痕。
"""
import argparse
import json
import sys
import time

import httpx

FAILS = []
REPORT = []   # (status, line) 全链留痕


def check(name, cond, detail=""):
    line = ("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail else "")
    print(line)
    REPORT.append(line)
    if not cond:
        FAILS.append(name)


def info(msg):
    print("INFO " + msg)
    REPORT.append("INFO " + msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--act", required=True, help="测试广告账户 act_XXX")
    ap.add_argument("--lp", type=int, required=True, help="已发布 display 模式落地页 ID")
    ap.add_argument("--asset", type=int, required=True, help="图片素材 ID")
    ap.add_argument("--page", required=True, help="FB 主页 ID")
    ap.add_argument("--pixel", required=True, help="FB 像素 ID")
    ap.add_argument("--msg-tpl", type=int, default=0, help="Messenger 欢迎语模板 ID（可选）")
    ap.add_argument("--budget", type=float, default=2.0, help="每组日预算 USD（默认 2）")
    ap.add_argument("--country", default="US", help="受众国家（默认 US）")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--keep", dest="keep", action="store_true", default=True)
    ap.add_argument("--no-keep", dest="keep", action="store_false")
    args = ap.parse_args()

    # ── 鉴权（owner token，批次 I smoke 同口径）──
    from app.core.database import SuperSessionLocal
    from app.models.auth import User
    from app.core.security import create_access_token
    db = SuperSessionLocal()
    u = db.query(User).filter(User.email == "seavey@tovaads.com").first()
    TOK = create_access_token(user_id=u.id, email=u.email, tenant_id=1,
                              role="owner", is_superadmin=u.is_superadmin)
    H = {"Authorization": f"Bearer {TOK}"}

    def _aud(country):
        return json.dumps({"countries": [country], "interests": [],
                           "age_min": 18, "age_max": 65, "gender": 0})

    # ── 1. 建最小树模板：2 组 × 各 1 广告（组1 website+落地页自动建链+细分版位；组2 messenger）──
    _g1_ad = {"key": "wa", "name": "W-自动建链", "enabled": False,
              "asset_ids": [args.asset], "headline": "RealDeploy A", "body": "website conv_location + auto subcode",
              "cta_type": "SHOP_NOW", "landing_page_id": args.lp, "subcode_slug": ""}
    _g2_ad = {"key": "ms", "name": "M-私信", "enabled": False,
              "asset_ids": [args.asset], "headline": "RealDeploy B", "body": "messenger conv_location",
              "cta_type": "MESSAGE_PAGE"}
    if args.msg_tpl:
        _g2_ad["message_template_id"] = args.msg_tpl
    structure = json.dumps({"adsets": [
        {"key": "g_web", "name": "G1-Website", "enabled": False, "budget_usd": args.budget,
         "conv_location": "website", "audience_json": _aud(args.country),
         "placement_mode": "manual", "publisher_platforms": ["facebook"],
         "device_platforms": ["mobile", "desktop"], "facebook_positions": ["feed"],
         "ads": [_g1_ad]},
        {"key": "g_msg", "name": "G2-Messenger", "enabled": False, "budget_usd": args.budget,
         "conv_location": "messenger", "audience_json": _aud(args.country),
         "ads": [_g2_ad]},
    ]})
    body = {
        "name": "REALDEPLOY-III", "platform": "fb", "objective": "OUTCOME_SALES",
        "budget_mode": "ABO", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "budget_usd": args.budget, "name_prefix": "RealDeploy3",
        "page_id": args.page, "pixel_id": args.pixel,
        "headline": "RealDeploy A", "body": "fallback body", "cta_type": "SHOP_NOW",
        "structure": structure,
    }
    r = httpx.post(f"{args.base}/launch-templates", headers=H, json=body, timeout=60)
    check("1.建模板 200", r.status_code == 200, r.text[:200])
    if r.status_code != 200:
        print("模板创建失败，中止（无 FB 副作用）")
        sys.exit(1)
    TID = r.json()["id"]
    info(f"模板 id={TID}")

    # ── 2. 预检断言（payload 结构 + 全 PAUSED + 自动建链节点数）──
    r = httpx.post(f"{args.base}/launch-templates/{TID}/preflight", headers=H,
                   json={"act_id": args.act, "page_id": args.page, "pixel_id": args.pixel,
                         "account_count": 1}, timeout=120)
    check("2.预检 200", r.status_code == 200, r.text[:200])
    pf = r.json() if r.status_code == 200 else {}
    tree = pf.get("tree") or []
    check("2.预检: 树模式 2 组", pf.get("mode") == "tree" and pf.get("adset_count") == 2,
          str({k: pf.get(k) for k in ("mode", "adset_count")}))
    check("2.预检: 组1 website + 细分版位 feed",
          (tree[0].get("conv_location") if tree else "") == "website"
          and (tree[0].get("facebook_positions") if tree else None) == ["feed"],
          str(tree[0] if tree else {}))
    check("2.预检: 组2 messenger", (tree[1].get("conv_location") if len(tree) > 1 else "") == "messenger",
          str(tree[1] if len(tree) > 1 else {}))
    _cmp = pf.get("campaign") or {}
    check("2.预检: campaign objective=SALES", _cmp.get("objective") == "OUTCOME_SALES", str(_cmp.get("objective")))
    _asd = pf.get("adset") or {}
    check("2.预检: 首组 destination_type=WEBSITE（矩阵派生）",
          _asd.get("destination_type") == "WEBSITE", str(_asd.get("destination_type")))
    _po = _asd.get("promoted_object") or {}
    check("2.预检: 首组 promoted_object.pixel_id", str(_po.get("pixel_id")) == str(args.pixel), str(_po))
    _tg = _asd.get("targeting") or {}
    check("2.预检: 首组 targeting.facebook_positions=['feed']",
          _tg.get("facebook_positions") == ["feed"], str(_tg.get("facebook_positions")))
    check("2.预检: 全 PAUSED（will_spend 空）——零消耗前置断言", pf.get("will_spend") == [],
          str(pf.get("will_spend")))
    check("2.预检: 自动建链节点数=1（组1 广告）", pf.get("auto_subcode_nodes") == 1,
          str(pf.get("auto_subcode_nodes")))
    _crt = pf.get("creative") or {}
    info(f"预检 creative 样例 keys: {sorted(_crt.keys())[:8]}")

    # ── 3. 部署（真 FB 调用）──
    r = httpx.post(f"{args.base}/launch-templates/{TID}/deploy", headers=H,
                   json={"items": [{"act_id": args.act, "page_id": args.page, "pixel_id": args.pixel}]},
                   timeout=60)
    check("3.部署提交 200", r.status_code == 200, r.text[:200])
    if r.status_code != 200:
        print("部署提交失败，中止（无 FB 对象创建）")
        sys.exit(1)
    JOB = r.json().get("job_id")
    info(f"job id={JOB}")
    job = {}
    for _ in range(120):
        time.sleep(3)
        jr = httpx.get(f"{args.base}/launch-templates/jobs/{JOB}", headers=H, timeout=30)
        job = jr.json() if jr.status_code == 200 else {}
        if job.get("status") in ("completed", "partial_failed", "failed"):
            break
    check("3.部署 job 完成（非超时）", job.get("status") == "completed",
          str({k: job.get(k) for k in ("status", "total", "succeeded", "failed")}))
    items = job.get("items") or []
    it = next((x for x in items if x.get("act_id") == args.act), None)
    check("3.item success", it and it.get("status") == "success", str(it)[:300])
    if not it or it.get("status") != "success":
        _dump_tail(db, JOB)
        sys.exit(1)
    CAMP_ID = it.get("campaign_id") or ""
    info(f"FB 对象：campaign={CAMP_ID} adset={it.get('adset_id')} ad={it.get('ad_id')} "
         f"subcodes={it.get('subcode_slug')}")
    check("3.item.subcode_slug 非空（自动建链落账 B10）", bool(it.get("subcode_slug")), str(it.get("subcode_slug")))

    # ── 4. FB 回读断言（结构字段/版位/宏/PAUSED）──
    from app.core.fb_tokens import client_for_account
    fb = client_for_account(db, 1, args.act, "read")
    check("4.FB 客户端可用", fb is not None)
    if fb is None:
        sys.exit(1)
    camp = fb.get(CAMP_ID, {"fields": "objective,status,effective_status,daily_budget"}) or {}
    check("4.回读 campaign objective=SALES + ACTIVE", camp.get("objective") == "OUTCOME_SALES"
          and camp.get("status") == "ACTIVE", str(camp))
    adsets = (fb.get(f"{CAMP_ID}/adsets",
                     {"fields": "name,destination_type,promoted_object,targeting,optimization_goal,"
                                "daily_budget,status,effective_status", "limit": 10}) or {}).get("data") or []
    check("4.回读 adsets=2", len(adsets) == 2, str([a.get("name") for a in adsets]))
    _web = next((a for a in adsets if a.get("destination_type") == "WEBSITE"), {})
    _msg = next((a for a in adsets if a.get("destination_type") == "MESSENGER"), {})
    check("4.回读 组1 WEBSITE + OFFSITE_CONVERSIONS + pixel + 细分版位",
          _web.get("optimization_goal") == "OFFSITE_CONVERSIONS"
          and str((_web.get("promoted_object") or {}).get("pixel_id")) == str(args.pixel)
          and ((_web.get("targeting") or {}).get("facebook_positions")) == ["feed"],
          json.dumps({"og": _web.get("optimization_goal"),
                      "po": _web.get("promoted_object"),
                      "fp": (_web.get("targeting") or {}).get("facebook_positions")}, ensure_ascii=False)[:300])
    check("4.回读 组1 adset PAUSED（零消耗）", _web.get("status") == "PAUSED", str(_web.get("status")))
    check("4.回读 组2 MESSENGER + MESSAGING_PURCHASE_CONVERSION + page",
          _msg.get("optimization_goal") == "MESSAGING_PURCHASE_CONVERSION"
          and str((_msg.get("promoted_object") or {}).get("page_id")) == str(args.page),
          json.dumps({"og": _msg.get("optimization_goal"), "po": _msg.get("promoted_object")}, ensure_ascii=False)[:300])
    check("4.回读 组2 adset PAUSED（零消耗）", _msg.get("status") == "PAUSED", str(_msg.get("status")))
    _mpo = _msg.get("promoted_object") or {}
    if "whatsapp_phone_number" in _mpo:
        info(f"⚠️ 组2 promoted_object 带 whatsapp_phone_number={_mpo.get('whatsapp_phone_number')}（SALES+messenger 不应带，报告复审）")
    ads = (fb.get(f"{CAMP_ID}/ads", {"fields": "name,status,effective_status,creative", "limit": 10})
           or {}).get("data") or []
    check("4.回读 ads=2 且全 PAUSED（零消耗硬断言）",
          len(ads) == 2 and all(a.get("effective_status") == "PAUSED" for a in ads),
          str([(a.get("name"), a.get("effective_status")) for a in ads]))
    _slug = (it.get("subcode_slug") or "").split(",")[0]
    _linkad = next((a for a in ads if _slug and _slug in str(a.get("name") or "")), None)
    check("4.回读 自动建链广告名带 [子码: 标注", _linkad is not None,
          str([a.get("name") for a in ads]))
    # creative 链接宏：读回 object_story_spec.link_data.link，断言 /a/{slug}?ad= 与 {{ad.id}} 或数字
    _macro_line = "（未取到）"
    if _linkad:
        _cid = ((_linkad.get("creative") or {}).get("id") or "")
        _cr = fb.get(_cid, {"fields": "object_story_spec"}) or {}
        _link = (((_cr.get("object_story_spec") or {}).get("link_data") or {}).get("link")) or ""
        _macro_line = _link[:160]
        check("4.回读 creative 链接含 /a/{slug}?ad=",
              f"/a/{_slug}?ad=" in _link, _macro_line)
        check("4.回读 {{ad.id}} 宏被 FB 存留或已替换为数字 ad id",
              "{{ad.id}}" in _link or _link.split("?ad=")[-1].split("&")[0].isdigit(),
              _macro_line)
        info(f"creative link={_macro_line}")
    else:
        check("4.回读 creative 链接宏", False, "自动建链广告未找到，无法断言宏")

    # ── 5. 子码 + ads_cache 归因断言 ──
    from app.models.launch import LandingAdLink
    link_row = db.query(LandingAdLink).filter(LandingAdLink.slug == _slug).first() if _slug else None
    check("5.子码 active + ad_id 回绑 + page 归属",
          link_row is not None and link_row.status == "active"
          and str(link_row.ad_id or "").isdigit() and link_row.page_id == args.lp,
          str({"slug": _slug, "status": getattr(link_row, "status", None),
               "ad_id": getattr(link_row, "ad_id", None), "page_id": getattr(link_row, "page_id", None)}))
    from app.models.ads_cache import AdsCache
    cache = db.query(AdsCache).filter(AdsCache.act_id == args.act).first()
    _found = None
    if cache:
        for _ad in json.loads(cache.ads_json or "[]"):
            if str(_ad.get("id")) == str(link_row.ad_id if link_row else it.get("ad_id")):
                _found = _ad
                break
    check("5.ads_cache 归因对账：新 ad 在缓存且带 adset_id（route_next 动态像素数据前提）",
          _found is not None and bool(_found.get("adset_id")),
          str({"found": bool(_found), "adset_id": (_found or {}).get("adset_id")}))

    # ── 6. 收尾报告 ──
    if not args.keep:
        httpx.delete(f"{args.base}/launch-templates/{TID}", headers=H, timeout=30)
        info(f"测试模板 {TID} 已归档（FB 对象保留，全 PAUSED 零消耗）")
    else:
        info(f"测试模板 {TID} 保留（FB 后台搜索 RealDeploy3；确认无误后手动归档模板）")
    db.close()
    print()
    print("═" * 30 + " 全链报告 " + "═" * 30)
    for ln in REPORT:
        print(ln)
    print("═" * 70)
    print(f"FB campaign={CAMP_ID}（ads 全 PAUSED，零消耗；手动激活才开始花钱）")
    print(f"{'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)} ({len(FAILS)} fail)")
    sys.exit(1 if FAILS else 0)


def _dump_tail(db, job_id):
    """失败时打出最近部署日志（留痕定位，不静默）——bare-except 铁律。"""
    try:
        from sqlalchemy import text as _t
        rows = db.execute(_t(
            "SELECT result, friendly_error, metadata FROM action_logs "
            "WHERE source='launch' AND created_at > now() - interval '1 hour' "
            "ORDER BY id DESC LIMIT 8")).fetchall()
        for r in rows[:8]:
            print("LOG", str(r)[:260])
    except Exception as e:
        print(f"log dump fail: {e}")


if __name__ == "__main__":
    main()
