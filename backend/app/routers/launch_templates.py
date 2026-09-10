"""投放模板 + 批量部署路由。

模板 = 可复用的广告结构 + 素材 + 文案（[[auto-launch-architecture-plan]] 模块 2）。
部署 = 选模板 + 选 N 账户 → BackgroundTasks 异步逐账户建广告（Campaign→AdSet→Ad），per-item 状态。
"""
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional
from ..core.database import get_db, SessionLocal, SuperSessionLocal, acquire_run_lock, release_run_lock
from ..core.deps import CurrentUser, require_permission, require_owned as _ro
from ..core.log_utils import write_log, new_trace_id
from ..core.fb_tokens import client_for_account, client_for_account_page
from ..core.fb_client import FbApiError
from ..core.ad_builder import (build_targeting, build_campaign, build_adset, build_creative,
                               resolve_adset_destination, is_messaging_destination,
                               normalize_objective, CONV_LOCATIONS_BY_OBJECTIVE,
                               OPT_GOALS_BY_OBJECTIVE, OPT_GOALS_BY_LOCATION)
from ..core.ad_ops import (deploy_one_account, ensure_image_hash_for_account,
                           ensure_video_id_for_account, ensure_video_thumb_hash,
                           usd_to_fb_amount, pick_cta,
                           bind_link_ad_id, post_adset_resilient as _post_adset_with_fallback)
from ..core.tt_client import TtApiError
from ..models.launch_template import LaunchTemplate, LaunchJob, LaunchJobItem
from ..models.launch import Asset, LandingAdLink, LandingPage
from ..models.audience import SavedAudience
from ..models.ads_cache import AdsCache
from ..models.fb import Account
from ..models.perf import CurrencyRate
import os

router = APIRouter(prefix="/launch-templates", tags=["launch-templates"])

ASSET_DIR = os.environ.get("ASSET_DIR", "/opt/toveads/assets")

# 部署预算安全上限（美元/日）：模板保存（TemplateIn 校验）与部署端点共用；
# 超限拒绝——大额预算走分步调整（services/ad_ops.set_budget 另有旧值×5 步进上限）
_BUDGET_MAX_USD = 5000.0
# 批G（0089）：总预算上限（多日累积）/特殊广告类别白名单/排期格式（模块级——pydantic 类内下划线属性会被当 ModelPrivateAttr）
_BUDGET_MAX_LIFETIME_USD = 50000.0
# 尾巴小件（0091）：系列支出上限（累计花到达即停整系列；与预算不同量纲，安全上限同总预算档）
_SPEND_CAP_MAX_USD = 100000.0
_SPECIAL_CATS = {"CREDIT", "EMPLOYMENT", "HOUSING",
                 "SOCIAL_ISSUES_ELECTIONS_POLITICS", "FINANCIAL_PRODUCTS"}
_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?(Z|[+-]\d{2}:?\d{2})?$")


def _tpl_dict(t: LaunchTemplate) -> dict:
    return {
        "id": t.id, "name": t.name, "description": t.description or "",
        "platform": t.platform or "fb",
        "objective": t.objective, "conversion_goal": t.conversion_goal or "",
        "budget_mode": t.budget_mode, "bid_strategy": t.bid_strategy,
        "daily_budget": t.daily_budget, "budget_usd": t.budget_usd, "name_prefix": t.name_prefix,
        "optimization_goal": t.optimization_goal or "", "billing_event": t.billing_event or "",
        "destination_type": t.destination_type or "",
        "audience_id": t.audience_id or 0, "audience_json": t.audience_json or "",
        "advanced_config": t.advanced_config or "",
        "asset_id": t.asset_id,
        "headline": t.headline or "", "body": t.body or "",
        "page_id": t.page_id or "", "pixel_id": t.pixel_id or "",
        "landing_url": t.landing_url or "", "cta_type": t.cta_type or "",
        "subcode_slug": t.subcode_slug or "", "ad_language": t.ad_language or "",
        "message_template": t.message_template or "", "lead_form_id": t.lead_form_id or "",
        "landing_page_id": t.landing_page_id or 0,
        "lead_form_template_id": t.lead_form_template_id or 0,
        "message_template_id": t.message_template_id or 0,
        "beneficiary": t.beneficiary or "", "payer": t.payer or "",
        "post_source": t.post_source or "new", "reuse_post_ref": t.reuse_post_ref or "",
        "structure": t.structure or "",
        "budget_type": t.budget_type or "daily", "lifetime_budget_usd": t.lifetime_budget_usd,
        "schedule_start": t.schedule_start or "", "schedule_end": t.schedule_end or "",
        "pacing": t.pacing or "", "bid_amount_usd": t.bid_amount_usd,
        "minimum_roas": t.minimum_roas, "special_ad_categories": t.special_ad_categories or "",
        "link_description": t.link_description or "",
        "spend_cap_usd": t.spend_cap_usd, "instagram_actor_id": t.instagram_actor_id or "",
        "whatsapp_phone_number": t.whatsapp_phone_number or "",
        "status": t.status, "deploy_count": t.deploy_count or 0,
        "created_at": str(t.created_at) if t.created_at else "",
    }


# ── 1:1 三层结构（0088）：校验/解析/平铺双写 ──
# 规模上限：防一次部署失控（10 组 × 20 节点 × 50 素材理论上限远超 FB 单账户健康度；
# 展开总数另有部署门 _TREE_ADS_MAX 兜底）
_TREE_ADSETS_MAX = 10
_TREE_ADS_PER_ADSET_MAX = 20
_TREE_ASSETS_PER_NODE_MAX = 50
# 每账户展开广告总数硬顶（素材组节点展开计入；超 = 400 快失败——FB 单账户上百条
# 新广告既炸账户结构也炸部署时长/reap 心跳窗口）
_TREE_ADS_MAX = 200

# ── 批次I：转化位置/版位（组节点字段校验用枚举；矩阵本体在 ad_builder）──
_CONV_LOC_ALL = ("website", "on_ad", "on_ad_messenger", "messenger", "whatsapp",
                 "instagram_direct", "phone_call", "on_page")
_PLACEMENT_PLATFORMS = ("facebook", "instagram", "messenger", "audience_network")  # threads P1
_PLACEMENT_DEVICES = ("desktop", "mobile")
# 细分版位白名单（批次III）：key=平台（须在 _PLACEMENT_PLATFORMS 内），value=该平台合法位置
# 枚举来源 = FB v25.0 targeting-spec 官方文档（messenger_home 为 1.0 生产验证值，官方现文档未列，
# 真投放实测校准）。省略某平台的 positions = 该平台全部位置（FB 官方默认语义）。
_PLACEMENT_POSITIONS = {
    "facebook": ("feed", "right_hand_column", "marketplace", "video_feeds", "story",
                 "search", "instream_video", "facebook_reels", "facebook_reels_overlay",
                 "profile_feed", "notification"),
    "instagram": ("stream", "story", "explore", "explore_home", "reels",
                  "profile_feed", "ig_search", "profile_reels"),
    "messenger": ("messenger_home", "sponsored_messages", "story"),
}
_SLUG_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _node_placements(snode: dict) -> dict | None:
    """组节点 → 结构化版位 dict（build_adset placements 形参）。
    placement_mode=manual 才产出；auto/空 = None（省略全部版位键 = Advantage+ 自动版位）。"""
    if (snode.get("placement_mode") or "") != "manual":
        return None
    out: dict = {}
    pp = [p for p in (snode.get("publisher_platforms") or []) if p]
    if pp:
        out["publisher_platforms"] = pp
    dp = [d for d in (snode.get("device_platforms") or []) if d]
    if dp:
        out["device_platforms"] = dp
    # 细分版位（批次III）：空数组=省略（该平台全部位置）
    for plat, pos_key in (("facebook", "facebook_positions"),
                          ("instagram", "instagram_positions"),
                          ("messenger", "messenger_positions")):
        vals = [x for x in (snode.get(pos_key) or []) if x]
        if vals and plat in pp:
            out[pos_key] = vals
    return out or None


# ── 批次I：部署时自动建链（每广告一子码；方案_落地页自动链接 §4 + 用户拍板 P2=每广告）──

def _auto_slug_base(tpl_id: int, node_key: str, asset, act_id: str) -> str:
    """语义 slug 基底：lt{模板id}-{节点key}-{素材id|s}-{账户尾4}（总方案：模板短码-节点key-账户尾4位）。
    字符集限 [A-Za-z0-9_-]（guard 创意反查正则口径），长度 ≤44（<64 上限，留碰撞后缀位）。"""
    key = _SLUG_SAFE_RE.sub("", str(node_key or ""))[:20]
    disc = str(asset.id) if asset is not None else "s"
    act4 = re.sub(r"\D", "", str(act_id or ""))[-4:] or "0"
    return f"lt{tpl_id}-{key or 'node'}-{disc}-{act4}"[:44]


def _create_auto_subcode(sdb, tenant_id: int, landing_page_id: int, act_id: str, base_slug: str):
    """自动建链：建 reserved LandingAdLink（复用 subcodes 生成语义——tenant/page/act/status）。
    语义 slug 碰撞加 -N 后缀（N≤9），语义位耗尽退随机 6 位（subcodes._gen_slug 同源字符集）。"""
    import secrets
    import string as _string
    slug = ""
    for i in range(10):
        cand = base_slug if i == 0 else f"{base_slug[:40]}-{i}"
        if not sdb.query(LandingAdLink).filter(LandingAdLink.slug == cand).first():
            slug = cand
            break
    if not slug:
        for _ in range(10):
            cand = "".join(secrets.choice(_string.ascii_lowercase + _string.digits)
                           for _ in range(6))
            if not sdb.query(LandingAdLink).filter(LandingAdLink.slug == cand).first():
                slug = cand
                break
    if not slug:
        raise RuntimeError("自动建链 slug 生成碰撞过多")
    link = LandingAdLink(tenant_id=tenant_id, slug=slug, act_id=act_id,
                         page_id=landing_page_id, status="reserved")
    sdb.add(link)
    sdb.flush()
    return link


def _resolve_landing_base(sdb, tenant_id: int, landing_page_id: int) -> tuple[str, object]:
    """落地页行 → (公网 base, 页对象)。口径=subcodes._resolve_page_base（自动建链不信
    landing_url 快照——方案 B5：页换域名/加子域后快照死链）。"""
    from .subcodes import _resolve_page_base
    return _resolve_page_base(sdb, tenant_id, landing_page_id)


class _LandingBlockedError(Exception):
    """落地页所有绑定域名均被 FB 屏蔽——部署硬拦截（批S）。调用方不得降级直投。"""


def _fb_domain_probe(db, tenant_id: int, url: str, _cache: dict | None = None) -> str:
    """FB 域名封禁探测（批S；返 pass/warn/fail，口径同落地页自检）。
    warn（无令牌/爬虫被挡/探测异常）不构成拦截依据——探测不可用不能误杀部署。"""
    if _cache is not None and url in _cache:
        return _cache[url]
    from .landing import _fb_ban_probe_batch
    try:
        st, _detail = _fb_ban_probe_batch(db, tenant_id, [url])[0]
    except Exception:
        st = "warn"
    if _cache is not None:
        _cache[url] = st
    return st


def _healthy_landing_base(sdb, tenant_id: int, landing_page_id: int,
                          _cache: dict | None = None) -> tuple[str, object, str]:
    """落地 base + FB 封禁健康门（批S，FB 部署链专用；TT 不走此门）。

    域名池 = 页绑定的全部域名（custom_domain 优先 + custom_domains 其余，现状顺序）。
    - 首选域探测 pass/warn → 沿用（健康路径零行为变化）
    - 首选域 fail（被 FB 屏蔽）→ 依序探测其余绑定域：取第一个 pass；无 pass 有 warn 用 warn
    - 全部 fail → err 非空（含域名数），调用方 item 失败拒投，不得降级
    """
    import json as _json
    from ..models.launch import LandingPage
    p = sdb.query(LandingPage).filter(
        LandingPage.id == landing_page_id, LandingPage.tenant_id == tenant_id).first()
    if not p:
        return "", None, "落地页不存在"
    hosts: list[str] = []

    def _add(h):
        h = (h or "").strip().rstrip("/")
        if h.startswith("https://"):
            h = h[8:]
        elif h.startswith("http://"):
            h = h[7:]
        if h and h not in hosts:
            hosts.append(h)

    _add(p.custom_domain)
    try:
        for d in _json.loads(p.custom_domains or "[]"):
            _add(d)
    except Exception:
        pass
    if not hosts:
        return f"https://tovaads-landing-{p.id}.pages.dev", p, ""
    warn_base = ""
    for i, h in enumerate(hosts):
        base = "https://" + h
        st = _fb_domain_probe(sdb, tenant_id, base, _cache)
        if st == "pass":
            return base, p, ""
        if st == "warn":
            if i == 0:
                return base, p, ""   # 首选域探测不可判定 → 沿用现状
            warn_base = warn_base or base
    if warn_base:
        return warn_base, p, ""
    return "https://" + hosts[0], p, (
        f"落地页「{(p.title or '')[:24] or p.id}」所有绑定域名均被 FB 屏蔽（已探测 {len(hosts)} 个），"
        "已阻止部署——请到落地页换绑健康域名后重试")


def _flat_auto_subcode(sdb, tpl: LaunchTemplate, item: LaunchJobItem, asset):
    """平铺链自动建链（单模板/批量逐系列/重试共用；FB only）：绑了落地页且未手选子码 →
    建 reserved 子码，返 (slug, link, base_url, warn)。
    base_url 非空 = 调用方应以它作 landing_url（deploy_one_account 会拼 /a/{slug}?ad={{ad.id}}，
    不信 landing_url 快照——方案 B5）；warn 非空 = 建链失败已降级直投（调用方写 item 留痕，不静默）。
    前提门已在 deploy/preflight 端点拦（未发布/redirect 页 400），此处 except 兜运行期失败。"""
    slug, link, base, warn = "", None, "", ""
    if (not tpl.subcode_slug) and (tpl.landing_page_id or 0):
        try:
            # 批S 域名健康门：全封 → _LandingBlockedError 穿透（下方 except 不吞，调用方 item 失败）
            _base, _lp, _blk = _healthy_landing_base(sdb, tpl.tenant_id, int(tpl.landing_page_id))
            if _blk:
                raise _LandingBlockedError(_blk)
            if not (_lp and (_lp.status or "") == "published"
                    and (_lp.redirect_mode or "display") == "display" and _base):
                raise ValueError("落地页未发布或为直接跳转模式")
            link = _create_auto_subcode(sdb, tpl.tenant_id, _lp.id, item.act_id,
                                        _auto_slug_base(tpl.id, "", asset, item.act_id))
            slug = link.slug
            sdb.commit()
            base = _base
            item.subcode_slug = slug   # 激活死列（B10）
        except _LandingBlockedError:
            raise   # 全封硬拦——降级直投等于把广告指向死链
        except Exception as e:
            sdb.rollback()
            warn = f"自动建链失败降级直投：{str(e)[:120]}"
            write_log(sdb, tenant_id=tpl.tenant_id, trace_id=new_trace_id(), actor_type="system",
                      target_type="ad", target_id="", action_type="deploy", source="launch",
                      result="fail", friendly_error=f"自动建链失败：{str(e)[:180]}",
                      metadata={"act_id": item.act_id, "template_id": tpl.id, "stage": "auto_subcode"})
    return slug, link, base, warn


def _auto_landing_gate(db, adsets: list, tenant_id: int) -> None:
    """自动建链前提门（deploy/preflight 共用，400 快失败）：绑了落地页且未手选子码的广告节点——
    页必须存在/已发布/display 模式。redirect 页建链无意义（方案 B11：跳转模式不 fire 像素），
    未发布页不该进 FB——提交前拦，而不是部署中途逐广告失败 N 轮。树节点与平铺模板同口径。
    平铺模板由调用方包成单节点 adsets 传入。"""
    from ..models.launch import LandingPage
    bad: list[str] = []
    seen_lp: set[int] = set()
    for s in adsets:
        for ad in (s.get("ads") or []):
            lpid = int(ad.get("landing_page_id") or 0)
            if not lpid or ad.get("subcode_slug"):
                continue
            if lpid not in seen_lp:
                seen_lp.add(lpid)
                lp = db.query(LandingPage).filter(
                    LandingPage.id == lpid, LandingPage.tenant_id == tenant_id).first()
                if not lp:
                    bad.append(f"落地页 #{lpid} 不存在")
                elif (lp.status or "") != "published":
                    bad.append(f"落地页「{lp.title}」未发布")
                elif (lp.redirect_mode or "display") != "display":
                    bad.append(f"落地页「{lp.title}」为直接跳转模式（建链无追踪意义）")
    if bad:
        raise HTTPException(400, "自动建链前提不满足：" + "；".join(bad[:3])
                            + ("…" if len(bad) > 3 else "")
                            + "（发布落地页/改为展示模式，或手动选择子码）")


# _post_adset_with_fallback 已下沉 core/ad_ops.post_adset_resilient（批AZ 统一：
# 平铺/手动/批量/树全部署路径共用同一 1870227+1487429 降级，不再各写一份）


def _bind_pixel_to_landing_page(sdb, tenant_id: int, landing_page_id: int, pixel_id: str,
                                act_id: str = "") -> bool:
    """像素回写落地页（批Z，转化闭环的关键一环）。

    worker fire 的像素来自页自己的 pixel_ids（LP_CONFIG）——投放链只把像素给 adset
    而页不 fire，FB 就永远收不到转化 → 止损规则按"花钱零转化"正确关广告（2026-09-09
    实例：LP6 pixel_ids 空，广告组优化 Tova 像素，页一个事件都没发）。
    解析出的广告组像素若不在页配置里 → 追加（幂等；独立 session 防 RLS SET LOCAL 坑）。
    返回是否新增绑定（调用方留痕）。"""
    if not (landing_page_id and pixel_id):
        return False
    from ..models.launch import LandingPage as _LP
    reg = SuperSessionLocal()
    try:
        p = reg.query(_LP).filter(_LP.id == landing_page_id,
                                  _LP.tenant_id == tenant_id).first()
        if not p:
            return False
        try:
            ids = json.loads(p.pixel_ids or "[]")
        except Exception:
            ids = []
        if pixel_id in ids:
            return False
        ids.append(pixel_id)
        p.pixel_ids = json.dumps(ids)
        reg.commit()
        write_log(reg, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                  target_type="landing_page", target_id=str(landing_page_id),
                  action_type="bind_pixel", source="launch", result="success",
                  friendly_error=f"部署回写像素 {pixel_id} 到落地页（转化闭环）",
                  metadata={"act_id": act_id, "pixel_id": pixel_id})
        return True
    except Exception as e:
        try:
            reg.rollback()
        except Exception:
            pass
        logging.getLogger("toveads.launch").warning(
            f"[Launch] 像素回写落地页失败 lp={landing_page_id}: {e}")
        return False
    finally:
        reg.close()


def _landing_page_first_pixel(sdb, tenant_id: int, landing_page_id: int) -> str:
    """落地页已配 FB 像素第一个（批Z：绑了页的组优先用页的像素——页是运营配置源，
    adset 与 worker fire 同源才有转化闭环）。"""
    if not landing_page_id:
        return ""
    try:
        p = sdb.query(LandingPage).filter(LandingPage.id == landing_page_id,
                                          LandingPage.tenant_id == tenant_id).first()
        if not p:
            return ""
        ids = json.loads(p.pixel_ids or "[]")
        return str(ids[0]) if ids else ""
    except Exception:
        return ""


def _resolve_tree_pixel(sdb, tenant_id: int, act_id: str, val: str) -> str:
    """组像素解析（批O-3）：值=random → 从该账户已绑像素随机轮换一个（多像素分摊防单像素过热）；
    其余（自动=空/指定 ID）原样返回走既有链路（节点 > 部署抽屉按账户 > 模板默认）。"""
    if (val or "").strip().lower() != "random":
        return val
    import random as _random
    from ..models.landing_lib import LandingPixel
    rows = sdb.query(LandingPixel).filter(
        LandingPixel.tenant_id == tenant_id, LandingPixel.act_id == act_id,
        LandingPixel.platform == "fb", LandingPixel.status == "active").all()
    return str(_random.choice(rows).pixel_id) if rows else ""


def _account_pixel_ids(sdb, tenant_id: int, act_id: str) -> list[str]:
    """该账户已绑（=已核权）的 FB 像素列表——像素库 act 维度（sync/deploy 来源均经
    act/adspixels 实测入档，是账户权限的地面真相缓存）。"""
    from ..models.landing_lib import LandingPixel
    return [str(r.pixel_id) for r in sdb.query(LandingPixel).filter(
        LandingPixel.tenant_id == tenant_id, LandingPixel.act_id == act_id,
        LandingPixel.platform == "fb", LandingPixel.status == "active").all()]


def _landing_page_pixel_ids(sdb, tenant_id: int, landing_page_id: int) -> list[str]:
    """落地页已配 FB 像素全列表（first_pixel 的全量版——权限比对需要逐个）。"""
    if not landing_page_id:
        return []
    try:
        p = sdb.query(LandingPage).filter(LandingPage.id == landing_page_id,
                                          LandingPage.tenant_id == tenant_id).first()
        if not p:
            return []
        return [str(x) for x in json.loads(p.pixel_ids or "[]")]
    except Exception:
        return []


def _pick_group_pixel(sdb, tenant_id: int, act_id: str, explicit_px: str,
                      landing_page_id: int, fb, allow_create: bool = True) -> tuple[str, str]:
    """组像素统一解析（批BR 终版，用户拍板「优先账户自己能关联到的」——2026-09-11 …142 实证：
    页/模板像素令牌可见 → 创建不报错，但账户未被 assign → 投放侧拦截，「部署成功广告失败」
    静默雷）。优先级：
      ① 显式指定（节点>抽屉>模板）且该账户有权（∈像素库 act 绑定）→ 原样尊重
      ② 账户已绑像素随机（主位策略——自己能关联到的永不错；多像素分摊沿用批O-3）
      ③ 库空 → 自愈：拉 FB act/adspixels 入档（零像素且 allow_create 则自动建）后按 ②
    返回 (pixel_id, note)：note 非空=发生了自动换（调用方留痕）；pixel_id 空=真无解（fail-fast）。
    选中像素账户必有权限；调用方须回写落地页 fire（_bind_pixel_to_landing_page，追加不顶——
    页上主像素继续收全量事件，账户像素管优化归因）。"""
    explicit_px = (explicit_px or "").strip()
    lib = _account_pixel_ids(sdb, tenant_id, act_id)
    if not lib:
        _ensure_account_pixel(sdb, tenant_id, act_id, fb, allow_create=allow_create)
        lib = _account_pixel_ids(sdb, tenant_id, act_id)
    if not lib:
        return "", ""
    if explicit_px and explicit_px in lib:
        return explicit_px, ""
    page_ids = _landing_page_pixel_ids(sdb, tenant_id, landing_page_id)
    want = explicit_px or (page_ids[0] if page_ids else "")
    picked = _resolve_tree_pixel(sdb, tenant_id, act_id, "random") or lib[0]
    note = "" if (not want or picked == want) else \
        f"像素 {want} 该账户无权限，已自动换为账户像素 {picked}"
    return picked, note


def _ensure_account_pixel(sdb, tenant_id: int, act_id: str, fb, allow_create: bool = True) -> str:
    """像素自愈（批U2）：像素库无该账户像素时的兜底——
    ① 拉 FB 账户既有像素（只读），取第一个入库存档后返回（库存档后以后走库，零 FB 调用）
    ② 账户零像素 → POST act/adspixels 自动建 Tova-时间戳（权限实测系统用户令牌可建；
       FB 每账户限 1 个自有像素 6200 → 恰好天然只建一次）
    ③ FB 调用失败返空串（调用方走原 ValueError/fail 路径，不静默瞎猜）。
    预检传 allow_create=False（预检不写 FB：能绑既有就用，不能就给占位符）。"""
    from datetime import datetime as _dt, timezone as _tz
    try:
        rows = sdb.query(LandingPixel).filter(
            LandingPixel.tenant_id == tenant_id, LandingPixel.act_id == act_id,
            LandingPixel.platform == "fb", LandingPixel.status == "active").all()
        if rows:
            return str(rows[0].pixel_id)
        if fb is None:
            return ""
        px = fb.get_pixels(act_id)
        pid, name = "", ""
        if px:
            pid = str(px[0].get("id") or "")
            name = (px[0].get("name") or "")[:100]
        elif allow_create:
            name = "Tova-" + _dt.now(_tz.utc).strftime("%Y%m%d%H%M%S")
            r = fb.post(f"act_{act_id}/adspixels", {"name": name})
            pid = str(r.get("id") or "")
        if not pid:
            return ""
        # 入库用独立 SuperSession（RLS 坑：在请求 session 上 commit 会结束事务带走 SET LOCAL
        # 租户上下文 → 之后访问调用方 ORM 对象刷新时 RLS 查不到行 → ObjectDeletedError）
        _reg = SuperSessionLocal()
        try:
            if not _reg.query(LandingPixel).filter(
                    LandingPixel.tenant_id == tenant_id, LandingPixel.pixel_id == pid,
                    LandingPixel.platform == "fb").first():
                _reg.add(LandingPixel(tenant_id=tenant_id, act_id=act_id, platform="fb",
                                      pixel_id=pid, pixel_name=name, status="active", source="deploy"))
                _reg.commit()
        except Exception:
            _reg.rollback()
        finally:
            _reg.close()
        return pid
    except Exception as e:
        logging.getLogger("toveads.launch").warning(
            f"[Launch] pixel self-heal failed act_{act_id}: {e}")
        return ""


def _validate_structure(raw) -> tuple[dict, str]:
    """结构 JSON 形状校验 + 规范化。返 (规范化 dict, 错误信息)。错误信息空 = 通过。

    规范化：补默认值（enabled=False 等安全默认）、素材去重保序、名字截断、
    未知键丢弃（存库的是干净形状——下游部署/前端渲染不用处处防脏键）。
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("adsets"), list) or not raw["adsets"]:
        return {}, "结构需为 {\"adsets\": [...]} 且至少含 1 个广告组"
    if len(raw["adsets"]) > _TREE_ADSETS_MAX:
        return {}, f"广告组最多 {_TREE_ADSETS_MAX} 个"
    out_adsets = []
    for si, adset in enumerate(raw["adsets"], 1):
        if not isinstance(adset, dict):
            return {}, f"广告组 #{si} 形状错误"
        name = str(adset.get("name") or "").strip()[:100]
        budget = adset.get("budget_usd")
        if budget is not None:
            try:
                budget = float(budget)
            except (TypeError, ValueError):
                return {}, f"广告组「{name or si}」预算需为数字"
            if not (0 < budget <= _BUDGET_MAX_USD):
                return {}, f"广告组「{name or si}」预算需在 0-{_BUDGET_MAX_USD:.0f} USD"
        ads_raw = adset.get("ads")
        if not isinstance(ads_raw, list) or not ads_raw:
            return {}, f"广告组「{name or si}」至少含 1 个广告"
        if len(ads_raw) > _TREE_ADS_PER_ADSET_MAX:
            return {}, f"广告组「{name or si}」广告节点最多 {_TREE_ADS_PER_ADSET_MAX} 个"
        out_ads = []
        for ai, ad in enumerate(ads_raw, 1):
            if not isinstance(ad, dict):
                return {}, f"广告组「{name or si}」广告 #{ai} 形状错误"
            # 素材清单：去重保序 + 全 int（素材组节点 = 部署时每素材展开一个广告）
            asset_ids, seen = [], set()
            for a in (ad.get("asset_ids") or []):
                try:
                    aid = int(a)
                except (TypeError, ValueError):
                    return {}, f"广告 #{ai} 素材 ID 非法：{a!r}"
                if aid not in seen:
                    seen.add(aid); asset_ids.append(aid)
            if len(asset_ids) > _TREE_ASSETS_PER_NODE_MAX:
                return {}, f"广告「{str(ad.get('name') or ai)[:30]}」素材最多 {_TREE_ASSETS_PER_NODE_MAX} 个"
            post_source = "reuse" if ad.get("post_source") == "reuse" else "new"
            reuse_ref = str(ad.get("reuse_post_ref") or "").strip()
            if post_source == "reuse":
                if not reuse_ref:
                    return {}, f"广告 #{ai} 跟帖模式必须填帖子引用（page_id_post_id）"
                if len(asset_ids) > 1:
                    return {}, f"广告 #{ai} 跟帖模式不支持多素材（多素材会全部指向同一条帖子）"
            ad_url = str(ad.get("landing_url") or "")
            try:
                _check_url_placeholders(ad_url)
            except ValueError as e:
                return {}, f"广告 #{ai}：{e}"
            out_ads.append({
                "key": str(ad.get("key") or f"ad_{si}_{ai}")[:40],
                "name": str(ad.get("name") or "").strip()[:100],
                "enabled": bool(ad.get("enabled")),
                "asset_ids": asset_ids,
                "headline": str(ad.get("headline") or "")[:200],
                "body": str(ad.get("body") or "")[:600],
                "cta_type": str(ad.get("cta_type") or ""),
                "ad_language": str(ad.get("ad_language") or ""),
                "landing_page_id": int(ad.get("landing_page_id") or 0),
                "landing_url": ad_url,
                "subcode_slug": str(ad.get("subcode_slug") or ""),
                "message_template_id": int(ad.get("message_template_id") or 0),
                "lead_form_template_id": int(ad.get("lead_form_template_id") or 0),
                "pixel_id": str(ad.get("pixel_id") or ""),
                "page_id": str(ad.get("page_id") or "")[:64],   # 批O-2：FB 身份在广告层——节点级主页
                "post_source": post_source,
                "reuse_post_ref": reuse_ref,
                "link_description": str(ad.get("link_description") or "")[:200],
            })
        aud_id = adset.get("audience_id")
        # ── 批次I：转化位置 + 版位（组节点结构化字段；conv_location×objective 兼容在
        # TemplateIn 模型级校验——此处不知 objective，只做枚举/形状白名单）──
        conv_loc = str(adset.get("conv_location") or "").strip().lower()
        if conv_loc and conv_loc not in _CONV_LOC_ALL:
            return {}, f"广告组「{name or si}」转化位置「{conv_loc}」非法（可用：{list(_CONV_LOC_ALL)}）"
        placement_mode = str(adset.get("placement_mode") or "").strip().lower()
        if placement_mode not in ("", "auto", "manual"):
            return {}, f"广告组「{name or si}」版位模式非法（auto/manual）"
        pp_raw = adset.get("publisher_platforms") or []
        dp_raw = adset.get("device_platforms") or []
        if not isinstance(pp_raw, list) or not isinstance(dp_raw, list):
            return {}, f"广告组「{name or si}」版位平台/设备需为数组"
        pp = []
        for p in pp_raw:
            if p not in _PLACEMENT_PLATFORMS:
                return {}, f"广告组「{name or si}」版位平台非法：{p!r}（可用：{list(_PLACEMENT_PLATFORMS)}）"
            if p not in pp:
                pp.append(p)
        dp = []
        for d in dp_raw:
            if d not in _PLACEMENT_DEVICES:
                return {}, f"广告组「{name or si}」设备平台非法：{d!r}（可用：{list(_PLACEMENT_DEVICES)}）"
            if d not in dp:
                dp.append(d)
        # 细分版位（批次III）：数组白名单校验；位置已选但平台未勾选 = 矛盾组合 400（省略=该平台全位置）
        pos_out = {}
        for plat, pos_key in (("facebook", "facebook_positions"),
                              ("instagram", "instagram_positions"),
                              ("messenger", "messenger_positions")):
            raw = adset.get(pos_key) or []
            if not isinstance(raw, list):
                return {}, f"广告组「{name or si}」{pos_key} 需为数组"
            vals = []
            for x in raw:
                if x not in _PLACEMENT_POSITIONS[plat]:
                    return {}, (f"广告组「{name or si}」平台 {plat} 版位位置非法：{x!r}"
                                f"（可用：{list(_PLACEMENT_POSITIONS[plat])}）")
                if x not in vals:
                    vals.append(x)
            if vals and placement_mode == "manual" and plat not in pp:
                return {}, f"广告组「{name or si}」选了 {plat} 的细分位置但未勾选 {plat} 平台（先勾平台或清空细分位置）"
            if vals:
                pos_out[pos_key] = vals
        # auto/空 = 省略全部版位键（Advantage+ 自动版位官方语义）——残留的勾选值清掉防歧义
        if placement_mode != "manual":
            pp, dp = [], []
            pos_out = {}
        elif not pp:
            return {}, f"广告组「{name or si}」手动版位必须至少选择一个平台"
        out_adsets.append({
            "key": str(adset.get("key") or f"as_{si}")[:40],
            "name": name,
            "enabled": bool(adset.get("enabled")),
            "budget_usd": budget,
            "pixel_id": str(adset.get("pixel_id") or ""),
            "audience_id": int(aud_id) if aud_id else 0,
            "audience_json": str(adset.get("audience_json") or ""),
            "optimization_goal": str(adset.get("optimization_goal") or ""),
            "billing_event": str(adset.get("billing_event") or ""),
            "advanced_config": str(adset.get("advanced_config") or ""),
            "conv_location": conv_loc,
            # 批P1 修2：白名单漏了这个键——保存时被"未知键丢弃"策略剥掉，
            # 存库树永远无此键 → 部署回退默认开 → 兴趣受众撞 FB 1870227。三态保留（None=未设）
            "advantage_audience": (bool(adset["advantage_audience"])
                                   if adset.get("advantage_audience") is not None else None),
            "placement_mode": (placement_mode if placement_mode == "manual" else ""),
            "publisher_platforms": pp,
            "device_platforms": dp,
            "facebook_positions": pos_out.get("facebook_positions", []),
            "instagram_positions": pos_out.get("instagram_positions", []),
            "messenger_positions": pos_out.get("messenger_positions", []),
            "budget_type": ("lifetime" if str(adset.get("budget_type") or "").lower() == "lifetime" else "daily"),
            "lifetime_budget_usd": (float(adset["lifetime_budget_usd"])
                                    if adset.get("lifetime_budget_usd") not in (None, "", 0) else None),
            "schedule_start": str(adset.get("schedule_start") or "")[:25],
            "schedule_end": str(adset.get("schedule_end") or "")[:25],
            "pacing": ("accelerated" if str(adset.get("pacing") or "").lower() == "accelerated" else ""),
            "bid_amount_usd": (float(adset["bid_amount_usd"])
                               if adset.get("bid_amount_usd") not in (None, "", 0) else None),
            "minimum_roas": (float(adset["minimum_roas"])
                             if adset.get("minimum_roas") not in (None, "", 0) else None),
            "ads": out_ads,
        })
        # 组级总预算必须配排期（FB 硬约束：lifetime_budget 需 start/end）；排期格式粗校验
        if out_adsets[-1]["budget_type"] == "lifetime":
            _ss, _se = out_adsets[-1]["schedule_start"], out_adsets[-1]["schedule_end"]
            if not (_ss and _se):
                return {}, f"广告组「{name or len(out_adsets)}」总预算必须设置排期（开始+结束时间）"
            if _ss > _se:
                return {}, f"广告组「{name or len(out_adsets)}」排期开始晚于结束"
    # 展开总数（每账户）硬顶：素材组节点按 len(asset_ids) 计，无素材节点按 1 计
    expanded = sum(max(len(a["asset_ids"]), 1) for s in out_adsets for a in s["ads"])
    if expanded > _TREE_ADS_MAX:
        return {}, f"展开后广告总数 {expanded} 超上限 {_TREE_ADS_MAX}（素材组节点按素材数展开计入）"
    return {"adsets": out_adsets}, ""


def _parse_structure(t: LaunchTemplate) -> list[dict]:
    """模板 → 结构节点列表（部署/预检共用）。空/损坏 → []（平铺模式 / 容错降级）。"""
    if not t.structure:
        return []
    try:
        data = json.loads(t.structure)
        return data.get("adsets") or []
    except Exception:
        return []


def _sync_flat_from_structure(t: LaunchTemplate, db: Session = None) -> None:
    """平铺双写（0088）：结构模式保存时把「第一组第一广告」回写平铺列——
    旧读方（部署清单/保活/批量母版视图）不感知 structure 也能拿到合理值。
    节点空值 = 回退模板级（覆盖只发生在节点显式配置时）。
    asset_id 带 FK——节点素材可能已被删（结构允许保存悬挂引用，部署端点另有校验），
    落库前查存在性，不存在就不写（防 ForeignKeyViolation 500）。"""
    adsets = _parse_structure(t)
    if not adsets:
        return
    first_adset, ads = adsets[0], (adsets[0].get("ads") or [])
    if first_adset.get("budget_usd"):
        t.budget_usd = float(first_adset["budget_usd"])
    if first_adset.get("audience_id"):
        t.audience_id = int(first_adset["audience_id"])
    if first_adset.get("audience_json"):
        t.audience_json = first_adset["audience_json"]
    if first_adset.get("optimization_goal"):
        t.optimization_goal = first_adset["optimization_goal"]
    if first_adset.get("billing_event"):
        t.billing_event = first_adset["billing_event"]
    if not ads:
        return
    ad = ads[0]
    if ad.get("asset_ids") and db is not None:
        _aid = int(ad["asset_ids"][0])
        if db.query(Asset).filter(Asset.id == _aid, Asset.tenant_id == t.tenant_id).first():
            t.asset_id = _aid
    for col in ("headline", "body", "cta_type", "ad_language", "landing_url",
                "subcode_slug", "pixel_id"):
        if ad.get(col):
            setattr(t, col, ad[col])
    for col in ("landing_page_id", "message_template_id", "lead_form_template_id"):
        if ad.get(col):
            setattr(t, col, int(ad[col]))
    if ad.get("post_source") == "reuse" and ad.get("reuse_post_ref"):
        t.post_source = "reuse"
        t.reuse_post_ref = ad["reuse_post_ref"]


def _validate_tree_assets(db, adsets: list, tenant_id: int) -> None:
    """树素材存在性/类型校验（deploy/preflight 共用，对齐 _validate_batch_assets 口径）：
    素材被删/跨租户/非图片视频 → 400 快失败。结构允许保存悬挂引用（编辑期素材可能
    后删），部署是最后一道门——坏素材进 job 会逐账户重复失败 N 轮。"""
    ids = {int(a) for s in adsets for ad in (s.get("ads") or []) for a in (ad.get("asset_ids") or [])}
    if not ids:
        return
    rows = db.query(Asset).filter(Asset.id.in_(ids), Asset.tenant_id == tenant_id).all()
    found = {r.id: r for r in rows}
    missing = sorted(ids - set(found))
    if missing:
        raise HTTPException(400, f"结构引用的素材不存在或已删除：{missing[:8]}（请在模板编辑器更新广告节点素材）")
    bad = [f"{r.id}({r.type})" for r in rows if (r.type or "image") not in ("image", "video")]
    if bad:
        raise HTTPException(400, f"结构引用的素材类型不支持（需图片/视频）：{bad[:8]}")


# ── 模板 CRUD ──
class TemplateIn(BaseModel):
    name: str
    description: str = ""
    platform: str = "fb"          # fb / tt（tt 部署走 TT 三件套链路，TK P3）
    objective: str = "OUTCOME_SALES"
    conversion_goal: str = ""
    budget_mode: str = "ABO"
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP"
    daily_budget: int = 0
    budget_usd: Optional[float] = None
    name_prefix: str = "Tova Ads"
    optimization_goal: str = ""
    billing_event: str = ""
    destination_type: str = ""
    audience_id: int = 0
    audience_json: str = ""
    advanced_config: str = ""
    asset_id: Optional[int] = None
    headline: str = ""
    body: str = ""
    page_id: str = ""
    pixel_id: str = ""
    landing_url: str = ""
    cta_type: str = ""
    subcode_slug: str = ""
    ad_language: str = ""
    message_template: str = ""
    lead_form_id: str = ""
    landing_page_id: Optional[int] = None
    lead_form_template_id: int = 0
    message_template_id: int = 0
    beneficiary: str = ""
    payer: str = ""
    post_source: str = "new"
    reuse_post_ref: str = ""
    structure: str = ""   # 1:1 三层结构 JSON（空 = 平铺模式；校验/规范化见 _validate_structure）
    # FB 创建流程 1:1（0089 批G）
    budget_type: str = "daily"          # daily / lifetime
    lifetime_budget_usd: Optional[float] = None
    schedule_start: str = ""
    schedule_end: str = ""
    pacing: str = ""                    # ''=匀速 / accelerated
    bid_amount_usd: Optional[float] = None
    minimum_roas: Optional[float] = None
    special_ad_categories: str = ""     # JSON 数组串（CREDIT/EMPLOYMENT/HOUSING/...）
    link_description: str = ""
    # 1:1 尾巴小件（0091）
    spend_cap_usd: Optional[float] = None   # 系列支出上限（USD；达到即停整系列，区别于预算）
    instagram_actor_id: str = ""            # IG 账号 ID（空=用主页关联 IG）
    # 批次I：Click-to-WhatsApp 显式号码（仅 ENGAGEMENT 下发 promoted_object；Traffic/Sales 随主页不传）
    whatsapp_phone_number: str = ""



    @field_validator("budget_type")
    @classmethod
    def _norm_budget_type(cls, v: str) -> str:
        v = (v or "daily").strip().lower()
        return v if v in ("daily", "lifetime") else "daily"

    @field_validator("pacing")
    @classmethod
    def _norm_pacing(cls, v: str) -> str:
        v = (v or "").strip().lower()
        return v if v in ("", "accelerated") else ""

    @field_validator("lifetime_budget_usd")
    @classmethod
    def _cap_lifetime(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v > _BUDGET_MAX_LIFETIME_USD:
            raise ValueError(f"总预算超安全上限 ${_BUDGET_MAX_LIFETIME_USD:.0f}，请分系列分步投放")
        return v

    @field_validator("schedule_start", "schedule_end")
    @classmethod
    def _check_dt(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not _DT_RE.match(v):
            raise ValueError("排期时间格式应为 YYYY-MM-DD 或 YYYY-MM-DD HH:mm")
        return v

    @field_validator("special_ad_categories")
    @classmethod
    def _check_cats(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            return ""
        try:
            cats = json.loads(v)
        except Exception:
            raise ValueError("特殊广告类别需为 JSON 数组（如 [\"CREDIT\"]）")
        if not isinstance(cats, list) or any(c not in _SPECIAL_CATS for c in cats):
            raise ValueError(f"特殊广告类别仅支持：{sorted(_SPECIAL_CATS)}")
        return json.dumps(sorted(set(cats)))

    @field_validator("structure")
    @classmethod
    def _norm_structure(cls, v: str) -> str:
        """结构 JSON 门卫：非法形状在保存时就 400（不能等部署时才炸）。
        通过则返规范化 JSON 串（补默认值/去重素材/截断名字）。"""
        v = (v or "").strip()
        if not v:
            return ""
        try:
            parsed, err = _validate_structure(json.loads(v))
        except Exception:
            raise ValueError("结构(JSON) 解析失败")
        if err:
            raise ValueError(err)
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))

    @field_validator("platform")
    @classmethod
    def _norm_platform(cls, v: str) -> str:
        """平台白名单：只接受 fb/tt（脏值回落 fb——存量 FB 部署链路是默认安全侧）。"""
        v = (v or "fb").strip().lower()
        return v if v in ("fb", "tt") else "fb"

    @field_validator("budget_usd")
    @classmethod
    def _cap_budget_usd(cls, v: Optional[float]) -> Optional[float]:
        """日预算安全上限：模板保存时即拦（部署端点/预算换算再兜底，口径同一常量）。"""
        if v is not None and v > _BUDGET_MAX_USD:
            raise ValueError(f"日预算超安全上限 ${_BUDGET_MAX_USD:.0f}/日，请调低（大额预算分步上调）")
        return v

    @field_validator("spend_cap_usd")
    @classmethod
    def _check_spend_cap(cls, v: Optional[float]) -> Optional[float]:
        """系列支出上限（可选）：>0 且 ≤$100000（安全上限，与总预算同量级）。"""
        if v is not None and not (0 < v <= _SPEND_CAP_MAX_USD):
            raise ValueError(f"支出上限需在 0-{_SPEND_CAP_MAX_USD:.0f} USD（留空=不限）")
        return v

    @field_validator("instagram_actor_id")
    @classmethod
    def _check_ig_actor(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not v.isdigit():
            raise ValueError("Instagram 账号 ID 应为数字（如 17841400000000）")
        return v

    @field_validator("whatsapp_phone_number")
    @classmethod
    def _check_wa_number(cls, v: str) -> str:
        """CTW 号码：带国家码的完整号码（E.164 宽松口径——+8613800138000 / 8613800138000）。
        留空=不传（随主页绑定号）。位数 8-15（E.164 上限），多余分隔符清掉。"""
        v = (v or "").strip()
        if not v:
            return ""
        digits = re.sub(r"\D", "", v)
        if not (8 <= len(digits) <= 15):
            raise ValueError("WhatsApp 号码应为带国家码的完整号码（8-15 位数字，如 +85512345678）")
        return ("+" if v.startswith("+") else "") + digits

    @model_validator(mode="after")
    def _check_conv_matrix(self):
        """转化位置/优化目标 × 目标 兼容校验（批次I；蓝图 §2.1/§2.2/§5.2 矩阵）。
        _validate_structure 只做形状白名单（不知 objective），这里在模型级拿到 objective 后逐组校验：
        ① conv_location 必须在该 objective 的合法集合（蓝图转化位置全表）；
        ② 组 optimization_goal 覆盖必须与 objective 兼容（审计 S8/C4：旧 UI 全集下拉可选出 FB 必拒组合）；
        ③ 两者都显式时交叉校验（方案 §4.1：显式 conv_location 优先，不兼容的优化目标 400/422）。"""
        obj = normalize_objective(self.objective or "")
        allowed_goal = OPT_GOALS_BY_OBJECTIVE.get(obj, set())
        # 模板级 optimization_goal 兜底（批次II 修审计 C4 残留侧）：平铺模式与树节点回退共用
        # 此字段，前端 watcher 切目标会清但历史残留/旧数据直写仍可送达——非空且不在该目标
        # 白名单时 422 带可用清单（组级覆盖在下方逐组校验，双保险）
        _tpl_og = (self.optimization_goal or "").strip().upper()
        if _tpl_og and _tpl_og not in allowed_goal:
            raise ValueError(f"优化目标「{_tpl_og}」与目标 {self.objective} 不兼容"
                             f"（可用：{sorted(allowed_goal)}）")
        if not self.structure:
            return self
        try:
            data = json.loads(self.structure)
        except Exception:
            return self  # 形状错误由 structure 字段校验器拦
        allowed_loc = CONV_LOCATIONS_BY_OBJECTIVE.get(obj, set())
        for si, s in enumerate(data.get("adsets") or [], 1):
            nm = s.get("name") or f"组{si}"
            loc = (s.get("conv_location") or "").strip().lower()
            og = (s.get("optimization_goal") or "").strip().upper()
            if loc and loc not in allowed_loc:
                raise ValueError(f"广告组「{nm}」转化位置「{loc}」不适用于目标 {self.objective}"
                                 + (f"（可用：{sorted(allowed_loc)}）" if allowed_loc else "（该目标无可选转化位置）"))
            if og and og not in allowed_goal:
                raise ValueError(f"广告组「{nm}」优化目标「{og}」与目标 {self.objective} 不兼容"
                                 f"（可用：{sorted(allowed_goal)}）")
            if loc and og:
                loc_ok = OPT_GOALS_BY_LOCATION.get(loc, set())
                if og not in loc_ok:
                    raise ValueError(f"广告组「{nm}」转化位置「{loc}」下优化目标「{og}」不兼容"
                                     f"（该位置可用：{sorted(loc_ok & allowed_goal) or ['无']}）")
        return self


@router.get("")
def list_templates(user: CurrentUser = Depends(require_permission("ads.create")),
                   db: Session = Depends(get_db)):
    _q = db.query(LaunchTemplate).filter(
        LaunchTemplate.tenant_id == user.tenant_id,
        LaunchTemplate.status != "archived",
    )
    if user.role == "operator":   # 批AG：operator 只看自己创建的（与账户/数据口径一致）
        _q = _q.filter(LaunchTemplate.created_by == user.id)
    rows = _q.order_by(LaunchTemplate.id.desc()).all()
    return [_tpl_dict(t) for t in rows]


@router.post("")
def create_template(body: TemplateIn,
                    user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    try:
        _check_url_placeholders(body.landing_url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    t = LaunchTemplate(tenant_id=user.tenant_id, created_by=user.id, status="draft", **body.model_dump())
    _sync_flat_from_structure(t, db)   # 结构模式 → 平铺列双写（旧读方不炸；asset 查存在性防 FK500）
    db.add(t)
    db.flush()
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="launch_template", target_id=str(t.id),
              action_type="create", source="user", result="success", metadata={"name": body.name})
    db.commit()
    return _tpl_dict(t)


@router.put("/{tid}")
def update_template(tid: int, body: TemplateIn,
                    user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    t = db.query(LaunchTemplate).filter(LaunchTemplate.id == tid, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    _ro(user, t)   # 批AJ：operator 只能操作自己创建的
    try:
        _check_url_placeholders(body.landing_url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    _sync_flat_from_structure(t, db)   # 结构模式 → 平铺列双写（旧读方不炸；asset 查存在性防 FK500）
    db.commit()
    return _tpl_dict(t)


@router.delete("/{tid}/hard")
def hard_delete_template(tid: int, force: int = 0,
                         user: CurrentUser = Depends(require_permission("ads.create")),
                         db: Session = Depends(get_db)):
    """永久删除模板（真删行，非归档）。

    无部署历史直接删；有历史的需 force=1——部署 job 行保留（投放记录不丢，job 自带
    template_name 快照），仅把 template_id 解除关联后删模板。
    """
    t = db.query(LaunchTemplate).filter(
        LaunchTemplate.id == tid, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    _ro(user, t)   # 批AJ：operator 只能操作自己创建的
    _jobs = db.query(LaunchJob).filter(
        LaunchJob.template_id == tid, LaunchJob.tenant_id == user.tenant_id).all()
    if _jobs and not force:
        raise HTTPException(400, f"该模板有 {len(_jobs)} 次部署历史——确认删除请带 force=1（部署记录保留，仅解除关联）；或改用「归档」")
    detached = 0
    if _jobs:
        for j in _jobs:
            j.template_id = None   # job 保留 template_name 快照，历史不丢
            detached += 1
    db.delete(t)
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="launch_template", target_id=str(tid),
              action_type="hard_delete", source="user", result="success",
              metadata={"name": t.name, "force": bool(force), "jobs_detached": detached})
    db.commit()
    return {"id": tid, "deleted": True, "jobs_detached": detached}


@router.delete("/{tid}")
def delete_template(tid: int, user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    t = db.query(LaunchTemplate).filter(LaunchTemplate.id == tid, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    _ro(user, t)   # 批AJ：operator 只能操作自己创建的
    t.status = "archived"  # 软删（保留部署历史）
    db.commit()
    return {"id": tid, "archived": True}


# 复制的字段（不含 id/tenant_id/created_by/status/deploy_count/时间戳；不含 lead_form_id——
# 它是 page 绑定的具体 FB form_id，复制后部署到别的 page 会失效，留给 lead_form_template_id 按页重建）
_COPY_COLS = [
    "name", "description", "platform", "objective", "conversion_goal", "budget_mode", "bid_strategy",
    "daily_budget", "budget_usd", "name_prefix", "optimization_goal", "billing_event",
    "destination_type", "audience_id", "audience_json", "advanced_config", "asset_id",
    "headline", "body", "page_id", "pixel_id", "landing_url", "cta_type", "subcode_slug",
    "ad_language", "message_template", "landing_page_id",
    "lead_form_template_id", "message_template_id", "beneficiary", "payer",
    "post_source", "reuse_post_ref", "structure",
    "budget_type", "lifetime_budget_usd", "schedule_start", "schedule_end", "pacing",
    "bid_amount_usd", "minimum_roas", "special_ad_categories", "link_description",
    "spend_cap_usd", "instagram_actor_id", "whatsapp_phone_number",
]


@router.post("/{tid}/copy")
def copy_template(tid: int, user: CurrentUser = Depends(require_permission("ads.create")),
                  db: Session = Depends(get_db)):
    """复制模板（建变体用）：拷贝全部配置字段，名加「 副本」，deploy_count 归零。"""
    src = db.query(LaunchTemplate).filter(
        LaunchTemplate.id == tid, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not src:
        raise HTTPException(404, "模板不存在")
    _ro(user, src)   # 批AJ
    new = LaunchTemplate(tenant_id=user.tenant_id, created_by=user.id, status="draft", deploy_count=0)
    for col in _COPY_COLS:
        setattr(new, col, getattr(src, col))
    new.name = (src.name or "未命名") + " 副本"
    db.add(new)
    db.flush()
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
              actor_user_id=user.id, target_type="launch_template", target_id=str(new.id),
              action_type="create", source="user", result="success",
              metadata={"copied_from": tid, "name": new.name})
    db.commit()
    return _tpl_dict(new)


# ── 部署 ──
class DeployItem(BaseModel):
    act_id: str
    page_id: str = ""
    pixel_id: str = ""


class DeployIn(BaseModel):
    items: list[DeployItem]
    # 按素材批量生成系列（对标 FBInsider batchGenerate）：空 = 单模板旧行为（完全向后兼容）；
    # 非空 = 批量模式——模板当母版，忽略 tpl.asset_id，每个选中素材克隆一个完整系列
    # （campaign+adset+ad），系列名/广告名 = 素材名
    asset_ids: list[int] = []


@router.post("/{tid}/deploy")
def deploy_template(tid: int, body: DeployIn, bg: BackgroundTasks,
                    user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    """部署模板到多账户（异步）：建 job + items，BackgroundTasks 逐账户建广告。立即返 job_id。

    守卫：① 同模板已有 pending/running job 拒绝（双击=双份广告双份预算）
         ② 目标账户必须 managed 且属于本租户（未纳管账户建广告=违反显式导入+无止损覆盖）
         ③ items 去重（同账户重复提交）。"""
    t = db.query(LaunchTemplate).filter(LaunchTemplate.id == tid, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    _ro(user, t)   # 批AJ：operator 只能操作自己创建的
    if not body.items:
        raise HTTPException(400, "至少选一个账户")
    if t.status == "archived":
        raise HTTPException(400, "模板已归档")
    # 结构模式守卫（0088）：树内自带素材组节点/组预算，与平铺批量互斥；TT 链路本期不支持
    _is_tree = bool(_parse_structure(t))
    if _is_tree:
        if (t.platform or "fb") == "tt":
            raise HTTPException(400, "结构模式暂不支持 TikTok 模板（TT 仍用平铺模式部署）")
        if body.asset_ids:
            raise HTTPException(400, "结构模板的素材已在树内按广告节点配置，不支持再叠加「按素材批量生成系列」")
        _validate_tree_assets(db, _parse_structure(t), user.tenant_id)
    _budget_guard_400(t)
    # 自动建链前提门（批次I，方案_落地页自动链接 §4.1）：绑了落地页且未选子码的广告 → 部署时
    # 会自动建链，页须已发布+展示模式。树=逐节点检查；平铺=模板级三件套同口径。提交前 400，
    # 不让坏前提进 job 逐广告失败 N 轮
    if (t.platform or "fb") == "fb":
        if _is_tree:
            _auto_landing_gate(db, _parse_structure(t), user.tenant_id)
        elif (not t.subcode_slug) and (t.landing_page_id or 0):
            _auto_landing_gate(db, [{"name": t.name or "模板", "ads": [
                {"landing_page_id": int(t.landing_page_id or 0), "subcode_slug": ""}]}],
                user.tenant_id)
    # 账户归属 + managed 校验 + 去重（保序）
    seen, clean_items = set(), []
    for it in body.items:
        if it.act_id in seen:
            continue
        seen.add(it.act_id)
        acc = db.query(Account).filter(
            Account.tenant_id == user.tenant_id, Account.act_id == it.act_id,
            Account.is_managed == True,  # noqa: E712
        ).first()
        if not acc:
            raise HTTPException(400, f"账户 {it.act_id} 不在已纳管列表（先在令牌页载入并勾选导入）")
        # 平台匹配守卫（TK P3）：TT 模板只能部署 TT 账户（反之亦然）——错平台走下去会撞
        # FB 令牌分发 fail-fast，不如在提交前 400 把话说清楚
        if (acc.platform or "fb") != (t.platform or "fb"):
            acc_side = "TikTok" if (acc.platform or "fb") == "tt" else "FB"
            tpl_side = "TikTok" if (t.platform or "fb") == "tt" else "FB"
            raise HTTPException(400, f"账户 {it.act_id} 是 {acc_side} 账户，与 {tpl_side} 模板平台不匹配")
        # 跟帖页一致性（P2-3）：reuse_post_ref={page}_{post}，帖子不能跨主页引用——
        # item/模板解析出的主页与 ref 前缀不一致 → 400（部署中 FB 会拒或归因到错误主页）
        if (t.post_source or "new") == "reuse" and t.reuse_post_ref:
            _ref_page = (t.reuse_post_ref or "").split("_", 1)[0]
            _item_page = it.page_id or t.page_id or ""
            if _ref_page and _item_page and _ref_page != _item_page:
                raise HTTPException(400, f"账户 {it.act_id} 的部署主页 {_item_page} 与跟帖帖子主页 {_ref_page} 不一致（帖子不能跨主页引用）")
        clean_items.append(it)
    body.items = clean_items
    # 批量模式素材校验（deploy/preflight 共用口径）：失败 400 快失败——坏素材放进 job 会
    # 逐账户重复失败 N 次，浪费一整轮部署还污染进度列表
    batch_assets = _validate_batch_assets(db, body.asset_ids, user.tenant_id) if body.asset_ids else []
    # 占位符校验（复审R2-P1）：create/update/preflight 拦的是"保存时"；部署是最后一道门——
    # ⑥ 上线前保存的存量模板可能带脏占位符，插值会静默清空（追踪参数无声丢失）→ 400 快失败
    try:
        _check_url_placeholders(t.landing_url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # 跟帖(reuse)模板不支持批量（复审R2-P2）：reuse 分支固定引用同一帖子——M 个系列全部
    # 指向同一帖（创意零差异、预算×M），还白做 M 次素材上传
    if batch_assets and (t.post_source or "new") == "reuse":
        raise HTTPException(400, "跟帖（复用帖子）模板不支持按素材批量：批量模式会创建多个系列但全部引用同一条帖子（创意无差异、预算翻倍）。请先在模板编辑器切换为「新建帖子」模式")
    # 防重竞态（P1-1）：原「查 running → 建 job」两步在并发提交下都查空 → 双 job 双份广告。
    # advisory lock 115 把 查重→建 job→commit 串成原子段；拿不到锁=另一请求正在提交，409 快失败。
    _dlock = acquire_run_lock(115)
    if not _dlock:
        raise HTTPException(409, "部署正在提交中，请稍候重试")
    try:
        running = db.query(LaunchJob).filter(
            LaunchJob.tenant_id == user.tenant_id, LaunchJob.template_id == tid,
            LaunchJob.status.in_(("pending", "running")),
        ).first()
        if running:
            raise HTTPException(409, f"该模板已有进行中的部署任务(#{running.id})，等它完成再发（防重复建广告）")
        job = LaunchJob(tenant_id=user.tenant_id, template_id=t.id, template_name=t.name,
                        status="pending", total=len(body.items), created_by=user.id)
        db.add(job)
        db.flush()
        for it in body.items:
            db.add(LaunchJobItem(job_id=job.id, tenant_id=user.tenant_id, act_id=it.act_id,
                                 page_id=it.page_id, pixel_id=it.pixel_id, status="pending"))
        write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(), actor_type="user",
                  actor_user_id=user.id, target_type="launch_job", target_id=str(job.id),
                  action_type="deploy", source="user", result="success",
                  # 批量素材清单存日志 metadata：launch_jobs 无专用列（加列需迁移，超出本次
                  # 改动范围），_run_deploy_job/_retry_one 用 _job_batch_assets 从这里回读
                  # （与 job 同事务写入，可靠；见其注释）
                  metadata={"template_id": t.id, "accounts": len(body.items),
                            **({"asset_ids": [a.id for a in batch_assets]} if batch_assets else {})})
        db.commit()
    finally:
        release_run_lock(_dlock, 115)
    bg.add_task(_run_deploy_job, job.id, user.tenant_id, t.id)
    # series_total = 账户数 × 素材数（仅批量模式带）；结构模式带树统计（每账户 1 系列
    # N 组 M 广告，ad_total 为展开后广告数 × 账户数）；单模板模式响应形状与原来完全一致
    _tree = _parse_structure(t)
    return {"job_id": job.id, "total": len(body.items),
            **({"series_total": len(body.items) * len(batch_assets)} if batch_assets else {}),
            **({"tree": {"adsets": len(_tree),
                         "ad_total": len(body.items) * _tree_expanded_count(_tree)}}
               if _tree else {})}


def _validate_batch_assets(db, asset_ids: list[int], tenant_id: int) -> list:
    """批量模式素材校验（deploy/preflight 共用）：去重保序 + 存在 + 本租户 + image/video + 有文件。
    任一不满足 → 400 快失败（带具体素材名，用户能直接定位修哪个）。"""
    if len(asset_ids) > 200:
        # 上限 200：一个 item（账户）内最多 200 系列已是极端用法，再多单 job 跑不完且
        # 出错面太大（与前端 BATCH_ASSET_MAX 一致，更多请分批部署）
        raise HTTPException(400, "批量素材最多 200 个（更多请分批部署）")
    seen, ids = set(), []
    for aid in asset_ids:
        if aid in seen:
            continue
        seen.add(aid)
        ids.append(aid)
    rows = db.query(Asset).filter(Asset.id.in_(ids), Asset.tenant_id == tenant_id).all()
    by_id = {a.id: a for a in rows}
    out = []
    for aid in ids:
        a = by_id.get(aid)
        if not a:
            raise HTTPException(400, f"素材 #{aid} 不存在或不属于本团队")
        _n = a.name or a.filename or str(aid)
        if (a.type or "") not in ("image", "video"):
            raise HTTPException(400, f"素材「{_n}」类型不支持（批量生成仅支持图片/视频）")
        if not a.storage_key:
            raise HTTPException(400, f"素材「{_n}」缺少源文件，不能部署")
        out.append(a)
    return out


def _write_fb_with_fallback(sdb, tenant_id: int, act_id: str):
    """写令牌候选兜底（批AK）：逐候选返回 FbClient 列表——裸 Invalid parameter（无
    error_data，跨 App/无写权限令牌的伪装形态，2026-09-09 批量部署 3 账户失败实例）
    时调用方换下一个候选重试。首轮即 client_for_account 选中的那个（保持现有 RR）。"""
    from ..core.fb_tokens import _account_write_candidates
    from ..core.encryption import decrypt
    cands = _account_write_candidates(sdb, tenant_id, act_id, "write")
    first = client_for_account(sdb, tenant_id, act_id, "write")
    if first is None:
        return None, cands
    out, seen = [first], set()
    for c in cands:
        if c.id in seen:
            continue
        seen.add(c.id)
        try:
            out.append(FbClient(decrypt(c.access_token_enc)))
        except Exception:
            continue
    # 去重保持序（first 可能等于某候选）。批AU 修：FbClient 的令牌属性名是 token——
    # 原来读 _access_token（不存在）→ getattr 落空 → 全部候选被清空 → 恒返回空表，
    # 「未绑定写令牌」从批AK 起就是这条假兜底造成的（从未真正生效）
    uniq, ids = [], set()
    for f in out:
        tok = getattr(f, "token", None) or getattr(f, "_access_token", None) or ""
        if tok and tok not in ids:
            ids.add(tok)
            uniq.append(f)
    return uniq, cands


def _is_bare_invalid_param(e) -> bool:
    """裸 Invalid parameter（无 error_data）——FB 对无权限令牌的伪装报错形态。"""
    return (getattr(e, "category", "") == "invalid_param"
            and not getattr(e, "error_data", None))


def _series_name(tpl: LaunchTemplate, asset, idx: int) -> str:
    """批量模式系列名（campaign/adset/ad 共用的 name_prefix）= 素材名；素材名空回退
    母版前缀+序号（FB/TT campaign 名不能为空）。截 100 字符——FB 上限 400，留余量保证各处列表可读。"""
    n = (asset.name or asset.filename or "").strip()
    return (n or f"{tpl.name_prefix}-{idx + 1}")[:100]


# ── 追踪参数通用插值（FBInsider 对标 #10）：落地 URL 静态白名单占位符，部署时逐账户取值 ──
# 白名单只收「部署时已知」的静态值；{{ad.id}} 明确拒绝（FB 建广告前拿不到 ad id，
# 且子码绑 {{ad.id}} 占位符曾有像素不 fire 的事故——见 subcode-placeholder-binding-bug）
_URL_PLACEHOLDERS = {"campaign.name", "adset.name", "account.name", "account.id",
                     "asset.name", "template.name", "platform"}
# 宽匹配（复审R2-P2）：吃任何 {{...}}（含带空格/连字符等非法写法）——窄正则会漏检
# `{{campaign name}}`，check 放行 + interp 原样保留 = 字面垃圾 URL 直达 FB
_URL_PH_RE = re.compile(r"\{\{([^{}]*)\}\}")


def _check_url_placeholders(url: str):
    """校验 landing_url 占位符：白名单外一律拒绝（快失败，不留部署时静默产垃圾 URL）。"""
    if not url or "{{" not in url:
        return
    for m in _URL_PH_RE.finditer(url):
        key = m.group(1).strip()
        if key == "ad.id":
            raise ValueError(
                "落地页 URL 不支持 {{ad.id}}：FB 建广告前拿不到广告 ID（子码绑此占位符曾导致像素不 fire）。"
                "请改用 {{campaign.name}} / {{account.id}} 等静态值")
        if key not in _URL_PLACEHOLDERS:
            raise ValueError(f"未知占位符 {{{{{key}}}}}，支持：{', '.join(sorted(_URL_PLACEHOLDERS))}")
    # 宽正则吃不到的残留（如 {{{x}}} 嵌套）也算脏占位符——任何 {{ 走到部署即垃圾 URL
    _rest = _URL_PH_RE.sub("", url)
    if "{{" in _rest:
        raise ValueError("落地页 URL 含无法解析的占位符写法（检查 {{ }} 配对）")


def _interp_landing_url(url: str, *, campaign_name: str = "", account_name: str = "",
                        account_id: str = "", asset_name: str = "",
                        template_name: str = "", platform: str = "fb",
                        adset_name: str = "") -> str:
    """把白名单占位符替换为部署时实值（URL 编码——名字含空格/中文/& 不会打断 query）。
    adset 名与 campaign 同源（平铺部署链恒为 `{系列名} 组`）；结构模式传真实组名
    （adset_name 非空优先）。无占位符原样返回（旧模板零开销）。"""
    if not url or "{{" not in url:
        return url
    from urllib.parse import quote
    if not adset_name:
        adset_name = f"{campaign_name} 组" if campaign_name else ""
    vals = {"campaign.name": campaign_name, "adset.name": adset_name,
            "account.name": account_name, "account.id": account_id,
            "asset.name": asset_name, "template.name": template_name, "platform": platform}

    def _sub(m):
        v = str(vals.get(m.group(1).strip()) or "")
        return quote(v, safe="") if v else ""
    return _URL_PH_RE.sub(_sub, url)


def _stable_landing_url(url: str, template_name: str, platform: str = "fb") -> str:
    """跨系列/跨账户复用场景（Instant Form 感谢页、跟帖链接——按 page/asset 缓存共享）的
    稳定插值（复审R2-P2）：只解 template.name/platform，系列/账户/素材级占位符剥离为空
    ——把某个系列名烧进共享表单会错误归因其他系列，字面 {{xxx}} 直接上线更是垃圾 URL。"""
    return _interp_landing_url(url, template_name=template_name, platform=platform)


@router.get("/{tid}/reuse-eligible")
def reuse_eligible_accounts(tid: int,
                            user: CurrentUser = Depends(require_permission("ads.create")),
                            db: Session = Depends(get_db)):
    """跟帖模式：列令牌能管该帖主页的账户（部署抽屉预过滤用，权威判定）。
    解析 reuse_post_ref({page}_{post}) → page_id；managed 账户候选池里有能管 page_id 的写令牌则可选。
    多令牌同账户：扫整个候选池（不只绑定/priority最高），任一能管主页即算可用。"""
    tpl = db.query(LaunchTemplate).filter(
        LaunchTemplate.id == tid, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not tpl:
        raise HTTPException(404, "模板不存在")
    _ro(user, tpl)   # 批AJ
    ref = tpl.reuse_post_ref or ""
    page_id = ref.split("_", 1)[0] if "_" in ref else (tpl.page_id or "")
    if not page_id:
        return {"page_id": "", "eligible": []}
    accs = db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.is_managed == True  # noqa: E712
    ).all()
    cache: dict = {}  # cred_id → 能管 page? 跨账户复用（多账户共享令牌只查一次 FB）
    eligible = [a.act_id for a in accs
                if client_for_account_page(db, user.tenant_id, a.act_id, page_id, "write", cache)]
    return {"page_id": page_id, "eligible": eligible}


class PreflightIn(BaseModel):
    act_id: str
    page_id: str = ""
    pixel_id: str = ""
    # 批量模式预检（部署抽屉「按素材批量生成系列」）：asset_ids 非空时忽略 tpl.asset_id，
    # 示例 payload 用第一个素材构建（campaign 名=素材名，直观展示每系列长什么样）；
    # account_count = 抽屉已选账户数，series_count = 素材数 × 账户数（预检本身只构建单账户 payload）
    asset_ids: list[int] = []
    account_count: int = 0


@router.post("/{tid}/preflight")
def preflight_deploy(tid: int, body: PreflightIn,
                     user: CurrentUser = Depends(require_permission("ads.create")),
                     db: Session = Depends(get_db)):
    """预检：构建（不发送）即将发给 FB 的完整 payload，供核对参数对应。

    返回 campaign/adset/creative 三个 dict + 预算本币换算明细 + 解析后的 targeting。
    不调 FB、不花钱、不建广告。用于真部署前核对每个字段是否和 FB 期望对得上。
    """
    t = db.query(LaunchTemplate).filter(LaunchTemplate.id == tid, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    _ro(user, t)   # 批AJ：operator 只能操作自己创建的
    _budget_guard_400(t)
    # 结构模式预检（0088）：整树概览 + 逐组预算本币换算 + 将消耗节点横幅（FBInsider 同款）
    _tree = _parse_structure(t)
    if _tree:
        if (t.platform or "fb") == "tt":
            raise HTTPException(400, "结构模式暂不支持 TikTok 模板（TT 仍用平铺模式部署）")
        if body.asset_ids:
            raise HTTPException(400, "结构模板的素材已在树内按广告节点配置，不支持叠加批量生成")
        _validate_tree_assets(db, _tree, user.tenant_id)
        return _preflight_tree_fb(db, t, _tree, body, user.tenant_id)
    # 批量模式：先校验选中素材（与 deploy 同口径），示例 payload 改用第一个素材
    batch_assets = _validate_batch_assets(db, body.asset_ids, user.tenant_id) if body.asset_ids else []
    # TikTok 模板走 TT 预检（TK P3）：payload 构建器/预算单位/像素解析全不同
    if (t.platform or "fb") == "tt":
        return _preflight_tt(db, t, body, user.tenant_id, batch_assets)
    # 子码存在性预检：拼错/已归档的 slug 部署时静默丢追踪（runner 查不到 link 就不带 /a/{slug}），
    # 部署"成功"但归因链路全断——最阴的隐性事故，预检必须提前拦
    subcode_warn_slug = None
    if t.subcode_slug:
        _link = db.query(LandingAdLink).filter(
            LandingAdLink.tenant_id == user.tenant_id, LandingAdLink.slug == t.subcode_slug,
            LandingAdLink.status.in_(["reserved", "active"]),
        ).first()
        if not _link:
            subcode_warn_slug = t.subcode_slug  # 前端按 i18n 渲染完整提示
    # 自动建链前提门 + 预告（批次I）：绑了落地页且未选子码 → 部署时每广告自动建子码（FB 平铺口径）
    auto_subcode = False
    if (not t.subcode_slug) and (t.landing_page_id or 0):
        _auto_landing_gate(db, [{"name": t.name or "模板", "ads": [
            {"landing_page_id": int(t.landing_page_id or 0), "subcode_slug": ""}]}], user.tenant_id)
        auto_subcode = True
    # 汇率预检：非 USD 账户缺汇率时 _resolve_budget_fb 抛 ValueError——
    # 原在 try 之外直接 500，预检该给友好 400（部署 runner 同异常是 fail item）
    try:
        daily_budget_fb = (0 if (t.budget_type or "daily") == "lifetime"
                           else _resolve_budget_fb(db, body.act_id, t, user.tenant_id))
    except ValueError as e:
        logging.getLogger("toveads.launch").warning(f"preflight budget resolve failed: {e}")
        raise HTTPException(400, "预算换算失败：账户币种缺少汇率，请在系统设置配置汇率或改用 USD 模板")
    targeting = _resolve_targeting(db, t.audience_id, t.audience_json or "")
    advanced = _parse_advanced(t)
    page_id = body.page_id or t.page_id
    # 批U2 像素自愈（预检侧）：手选 > 模板 > 只读绑定账户既有像素；仍无 → 占位符（部署时自建，
    # 预检不写 FB）——原行为是 400 硬拦，但部署链已能自建，预检不该拦住一条能成的部署
    pixel_id = body.pixel_id or t.pixel_id
    if not pixel_id:
        # 批U2：与部署 runner 同序——抽屉/模板 > 账户像素库随机 > 只读绑定既有 > 占位符
        pixel_id = _resolve_tree_pixel(db, user.tenant_id, body.act_id, "random")
    if not pixel_id:
        try:
            pixel_id = _ensure_account_pixel(
                db, user.tenant_id, body.act_id,
                client_for_account(db, user.tenant_id, body.act_id, "read"),
                allow_create=False) or "<部署时自动绑定/创建>"
        except Exception:
            pixel_id = "<部署时自动绑定/创建>"
    # 批量模式：示例系列用第一个素材（系列名=素材名，与部署 runner 的 _series_name 同口径）
    asset = (batch_assets[0] if batch_assets else
             (db.query(Asset).filter(Asset.id == t.asset_id, Asset.tenant_id == user.tenant_id).first()
              if t.asset_id else None))
    _prefix = _series_name(t, asset, 0) if batch_assets else t.name_prefix
    # 文案样例与部署 runner 同口径（预检=所见即所发）：批量=素材 AI 优先，单模板=模板手填优先
    from ..core.ad_ops import pick_ad_copy as _pf_pick_copy
    if batch_assets:
        _pf_head, _pf_body = _pf_pick_copy(asset, "", "", t.headline or "", t.body or "")
    else:
        _pf_head, _pf_body = _pf_pick_copy(asset, t.headline or "", t.body or "")
    acc = db.query(Account).filter(Account.act_id == body.act_id).first()
    currency = (acc.currency if acc else "USD") or "USD"
    cr = db.query(CurrencyRate).filter(CurrencyRate.code == currency.upper()).first()
    # 追踪参数插值：预检就按示例系列/账户解出真实 URL（用户核对的就是这个）；
    # 占位符非法在这里快失败，不等到部署
    try:
        _check_url_placeholders(t.landing_url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _lp_url = _interp_landing_url(
        t.landing_url, campaign_name=_prefix,
        account_name=(acc.name if acc else ""), account_id=body.act_id,
        asset_name=((asset.name or asset.filename or "") if asset else ""),
        template_name=t.name, platform="fb")
    # 落地 URL 跟随（批次II 修 B9/B5）：绑了落地页 → 用页行实时解析的 base（与部署 runner 同口径，
    # 预检=所见即所发）；页不存在/解析失败回落插值快照
    if t.landing_page_id:
        try:
            # 批S 域名健康门（预检=所见即所发）：全封 → 400 预拦，别等部署才炸
            _pf_base, _pf_lp, _pf_err = _healthy_landing_base(db, user.tenant_id, int(t.landing_page_id))
            if _pf_err:
                raise HTTPException(400, _pf_err)
            if _pf_base:
                _lp_url = _pf_base
        except HTTPException:
            raise
        except Exception:
            pass
    try:
        _p_btype = (t.budget_type or "daily").lower()
        # 金额换算统一走 _usd_to_account_minor（批次III：缺汇率 raise→400，与部署管道同口径；
        # 原内联 cr.rate if cr else 1.0 是静默 1.0 兜底——预算路径先 raise 掩盖了它，换算收敛为单一管道）
        _p_lifetime_fb = (_usd_to_account_minor(db, body.act_id, float(t.lifetime_budget_usd), user.tenant_id)
                          if (_p_btype == "lifetime" and t.lifetime_budget_usd) else None)
        _p_bid_fb = (_usd_to_account_minor(db, body.act_id, float(t.bid_amount_usd), user.tenant_id)
                     if t.bid_amount_usd else None)
        _p_spend_cap_fb = (_usd_to_account_minor(db, body.act_id, float(t.spend_cap_usd), user.tenant_id)
                           if t.spend_cap_usd else None)
        try:
            _p_cats = json.loads(t.special_ad_categories or "[]")
        except Exception:
            _p_cats = []
        campaign_payload = build_campaign(
            name=_prefix, objective=t.objective,
            daily_budget=(daily_budget_fb if (t.budget_mode.upper() == "CBO" and not _p_lifetime_fb) else None),
            lifetime_budget=_p_lifetime_fb,
            budget_mode=t.budget_mode, bid_strategy=t.bid_strategy,
            special_ad_categories=_p_cats,
            spend_cap=_p_spend_cap_fb,
        )
        adset_payload = build_adset(
            name=f"{_prefix} 组", campaign_id="<FB 创建 campaign 后返回>",
            daily_budget=daily_budget_fb, objective=t.objective,
            conversion_goal=t.conversion_goal, page_id=page_id, pixel_id=pixel_id,
            landing_url=_lp_url, bid_strategy=t.bid_strategy, budget_mode=t.budget_mode,
            targeting=targeting, dsa_beneficiary=t.beneficiary or "", dsa_payor=t.payer or "",
            optimization_goal=t.optimization_goal or "", billing_event=t.billing_event or "",
            destination_type_override=t.destination_type or "",
            extra=_strip_adv_bid(advanced, _p_bid_fb),   # 出价单一管道（G2②）：与部署 runner 同口径
            advantage_audience=not bool((targeting or {}).get("flexible_spec")),  # 平铺启发式：手动兴趣=原始受众
            budget_type=_p_btype, lifetime_budget=_p_lifetime_fb,
            start_time=(t.schedule_start or ""), end_time=(t.schedule_end or ""),
            pacing=(t.pacing or ""), bid_amount=_p_bid_fb,
            minimum_roas=(t.minimum_roas if t.minimum_roas else None),
        )
        if asset and asset.type == "video":
            creative_payload = build_creative(
                page_id=page_id, objective=t.objective, conversion_goal=t.conversion_goal,
                landing_url=_lp_url, headline=_pf_head, body=_pf_body,
                cta_type=t.cta_type, video_id="<部署时按账户上传缓存>",
                instagram_actor_id=(t.instagram_actor_id or ""),
            )
        else:
            creative_payload = build_creative(
                page_id=page_id, objective=t.objective, conversion_goal=t.conversion_goal,
                landing_url=_lp_url, headline=_pf_head, body=_pf_body,
                cta_type=t.cta_type, image_hash="<部署时按账户上传缓存>",
                instagram_actor_id=(t.instagram_actor_id or ""),
            )
    except ValueError as e:
        # build_adset 对缺 pixel/page 等抛 ValueError —— 预检就该把这个告诉用户
        raise HTTPException(400, f"参数校验失败：{e}")
    out = {
        "act_id": body.act_id, "platform": "fb", "currency": currency,
        "budget_usd": t.budget_usd, "fx_rate": (cr.rate if cr else None),
        "daily_budget_fb": daily_budget_fb, "budget_mode": t.budget_mode,
        "subcode_warn_slug": subcode_warn_slug,
        "auto_subcode": auto_subcode,
        "budget_type": (t.budget_type or "daily"),
        "lifetime_budget_usd": t.lifetime_budget_usd, "lifetime_budget_fb": _p_lifetime_fb,
        "schedule_start": (t.schedule_start or ""), "schedule_end": (t.schedule_end or ""),
        "pacing": (t.pacing or ""), "bid_amount_usd": t.bid_amount_usd,
        "bid_amount_fb": _p_bid_fb, "minimum_roas": t.minimum_roas,
        "special_ad_categories": _p_cats, "link_description": (t.link_description or ""),
        "spend_cap_usd": t.spend_cap_usd, "spend_cap_fb": _p_spend_cap_fb,
        "instagram_actor_id": (t.instagram_actor_id or ""),
        "asset": {
            "type": (asset.type if asset else ""),
            "name": (asset.name or asset.filename or "") if asset else "",
            "filename": (asset.filename or "") if asset else "",
            "duration_sec": (asset.duration_sec or 0) if asset else 0,
        },
        "objective": t.objective, "optimization_goal": adset_payload.get("optimization_goal"),
        "billing_event": adset_payload.get("billing_event"),
        "targeting_resolved": targeting,
        "campaign": campaign_payload, "adset": adset_payload, "creative": creative_payload,
        "notes": [
            "image_hash/video_id 部署时按目标账户上传并缓存",
            "campaign_id / adset_id 部署时由 FB 返回填入",
            "成功判定：FB 返回 id→success；抛错或无 id→fail（item 记 campaign_id）",
        ],
    }
    if batch_assets:
        # 批量模式附加：将生成的系列总数 + 素材清单（account_count 未传按 1 账户口径）
        out["series_count"] = len(batch_assets) * max(body.account_count or 0, 1)
        out["batch_assets"] = [{"id": a.id, "name": _series_name(t, a, i), "type": a.type}
                               for i, a in enumerate(batch_assets)]
    return out


def _preflight_tree_fb(db, t: LaunchTemplate, adsets: list, body: "PreflightIn", tenant_id: int) -> dict:
    """结构模式预检（0088）：整树概览（组/广告/开关/绑定）+ 逐组预算按目标账户本币换算
    + 将消耗节点清单（FBInsider 预检横幅同款）+ 首组首广告 payload 样例。不调 FB、不花钱。"""
    from types import SimpleNamespace
    # 自动建链前提门（批次I）：绑了落地页未选子码的节点 → 页须已发布+展示模式（与 deploy 端点同口径）
    _auto_landing_gate(db, adsets, tenant_id)
    _auto_nodes = [ad for s in adsets for ad in (s.get("ads") or [])
                   if (ad.get("landing_page_id") or 0) and not ad.get("subcode_slug")]
    acc = db.query(Account).filter(Account.tenant_id == tenant_id,
                                   Account.act_id == body.act_id).first()
    currency = (acc.currency if acc else "USD") or "USD"
    cr = db.query(CurrencyRate).filter(CurrencyRate.code == currency.upper()).first()
    try:
        camp_budget_fb = _resolve_budget_fb(db, body.act_id, t, tenant_id)
    except ValueError as e:
        raise HTTPException(400, f"预算换算失败：{e}")
    is_cbo = (t.budget_mode or "ABO").upper() == "CBO"
    import secrets as _sec
    from datetime import datetime as _dtn
    campaign_name = f"{t.name_prefix or t.name or 'Tova Ads'} {_dtn.now().strftime('%m%d-%H%M')}-{_sec.token_hex(2)}"[:100]
    # 系列支出上限（0091）：模板 USD → 该账户本币 minor units（与部署 runner 同管道；
    # 批次III 统一缺汇率口径：_usd_to_account_minor 缺汇率 raise→调用处 400，不再静默 1.0 兜底）
    try:
        _p_spend_cap_fb = (_usd_to_account_minor(db, body.act_id, float(t.spend_cap_usd), tenant_id)
                           if t.spend_cap_usd else None)
    except ValueError as e:
        raise HTTPException(400, f"支出上限换算失败：{e}")

    def _view(**ov):
        d = {c.name: getattr(t, c.name) for c in t.__table__.columns}
        d.update(ov)
        return SimpleNamespace(**d)

    tree_out, will_spend, abo_total_usd = [], [], 0.0
    # 素材名映射（will_spend 按展开口径：素材组节点每素材一条，名字=素材名——与部署抽屉
    # 「启用链路数」和真实建出的广告一一对应，前端两个数字不会对不上）
    _asset_names = {}
    _all_aids = {int(a) for s in adsets for an in (s.get("ads") or []) for a in (an.get("asset_ids") or [])}
    if _all_aids:
        for _a in db.query(Asset).filter(Asset.id.in_(_all_aids),
                                         Asset.tenant_id == tenant_id).all():
            _asset_names[_a.id] = ((_a.name or _a.filename or "") or f"素材{_a.id}")[:60]
    for si, snode in enumerate(adsets, 1):
        sname = (snode.get("name") or f"{campaign_name} 组{si}")[:100]
        s_enabled = bool(snode.get("enabled"))
        # 逐组预算：节点 USD → 该账户本币 minor units（与部署 runner 同管道）
        node_b = snode.get("budget_usd")
        try:
            adset_budget_fb = _resolve_budget_fb(
                db, body.act_id,
                _view(budget_usd=float(node_b) if node_b else t.budget_usd,
                      daily_budget=t.daily_budget if not node_b else 0),
                tenant_id) if not is_cbo else camp_budget_fb
        except ValueError as e:
            raise HTTPException(400, f"组「{sname}」预算换算失败：{e}")
        if not is_cbo and s_enabled:
            abo_total_usd += float(node_b or t.budget_usd or 0)
        ads_out = []
        for ai, anode in enumerate(snode.get("ads") or [], 1):
            a_enabled = bool(anode.get("enabled")) and s_enabled
            asset_ids = anode.get("asset_ids") or []
            if a_enabled:
                _names = [_asset_names.get(int(x), f"素材{x}") for x in asset_ids] or \
                         [anode.get("name") or f"广告{ai}"]
                for _n in _names:
                    will_spend.append(f"{sname}/{_n}")
            ads_out.append({
                "name": anode.get("name") or "",
                "enabled": a_enabled,
                "asset_count": len(asset_ids),
                "post_source": anode.get("post_source") or "new",
                "landing_url": anode.get("landing_url") or "",
                "bindings": {
                    "message_template_id": anode.get("message_template_id") or 0,
                    "lead_form_template_id": anode.get("lead_form_template_id") or 0,
                    "landing_page_id": anode.get("landing_page_id") or 0,
                    "subcode_slug": anode.get("subcode_slug") or "",
                },
            })
        tree_out.append({
            "name": sname, "enabled": s_enabled,
            "budget_usd": float(node_b) if node_b else (t.budget_usd if not is_cbo else None),
            "budget_local_fb": adset_budget_fb,
            "budget_type": (snode.get("budget_type") or t.budget_type or "daily"),
            "lifetime_budget_usd": (snode.get("lifetime_budget_usd") or t.lifetime_budget_usd),
            "schedule_start": (snode.get("schedule_start") or t.schedule_start or ""),
            "schedule_end": (snode.get("schedule_end") or t.schedule_end or ""),
            "pacing": (snode.get("pacing") or t.pacing or ""),
            "bid_amount_usd": (snode.get("bid_amount_usd") or t.bid_amount_usd),
            "minimum_roas": (snode.get("minimum_roas") or t.minimum_roas),
            "audience_id": snode.get("audience_id") or 0,
            "optimization_goal": snode.get("optimization_goal") or "",
            # 批次I：转化位置/版位（组节点结构化字段，前端树概览展示用）；批次III：细分位置透出
            "conv_location": (snode.get("conv_location") or ""),
            "placement_mode": ("manual" if (snode.get("placement_mode") or "") == "manual" else ""),
            "publisher_platforms": (snode.get("publisher_platforms") or []),
            "device_platforms": (snode.get("device_platforms") or []),
            "facebook_positions": (snode.get("facebook_positions") or []),
            "instagram_positions": (snode.get("instagram_positions") or []),
            "messenger_positions": (snode.get("messenger_positions") or []),
            "ads": ads_out,
        })
    # 首组首广告 payload 样例（与部署 runner 同构；占位符在保存时已校验）
    first_ad = (adsets[0].get("ads") or [{}])[0]
    first_asset = None
    if first_ad.get("asset_ids"):
        first_asset = db.query(Asset).filter(
            Asset.id == int(first_ad["asset_ids"][0]), Asset.tenant_id == tenant_id).first()
    # 文案样例与部署 runner 同口径（预检=所见即所发）：素材组节点=素材 AI 优先，单素材=节点手填优先
    from ..core.ad_ops import pick_ad_copy as _pf_pick_copy
    if len(first_ad.get("asset_ids") or []) > 1:
        _pf_head, _pf_body = _pf_pick_copy(
            first_asset, "", "",
            (first_ad.get("headline") or t.headline or ""),
            (first_ad.get("body") or t.body or ""))
    else:
        _pf_head, _pf_body = _pf_pick_copy(
            first_asset, first_ad.get("headline") or "", first_ad.get("body") or "",
            t.headline or "", t.body or "")
    try:
        _lp_url = _interp_landing_url(
            (first_ad.get("landing_url") or t.landing_url or ""), campaign_name=campaign_name,
            adset_name=tree_out[0]["name"], account_name=(acc.name if acc else ""),
            account_id=body.act_id,
            asset_name=((first_asset.name or first_asset.filename or "") if first_asset else ""),
            template_name=t.name or "", platform="fb")
        # 落地 URL 跟随（批次II 修 B9/B5）：首广告绑了落地页 → 用页行实时 base（与部署 runner
        # 同口径）；页不存在/解析失败回落插值快照
        if first_ad.get("landing_page_id"):
            try:
                # 批S 域名健康门（树预检）：全封 → 400 预拦
                _pf_lp_base, _pf_pg, _pf_lperr = _healthy_landing_base(db, tenant_id, int(first_ad["landing_page_id"]))
                if _pf_lperr:
                    raise HTTPException(400, _pf_lperr)
                if _pf_lp_base:
                    _lp_url = _pf_lp_base
            except HTTPException:
                raise
            except Exception:
                pass
        # 出价额样例（G2② 单管道口径）：首组 bid_amount_usd（组级 > 模板级）→ 目标账户本币 minor units
        # （批次III 统一：换算走 _usd_to_account_minor，缺汇率 raise 由外层 try→400）
        _pf_bid_usd = adsets[0].get("bid_amount_usd")
        if _pf_bid_usd in (None, ""):
            _pf_bid_usd = t.bid_amount_usd
        _pf_bid_fb = (_usd_to_account_minor(db, body.act_id, float(_pf_bid_usd), tenant_id)
                      if _pf_bid_usd else None)
        campaign_payload = build_campaign(
            name=campaign_name, objective=t.objective,
            daily_budget=camp_budget_fb if is_cbo else None,
            budget_mode=t.budget_mode, bid_strategy=t.bid_strategy,
            spend_cap=_p_spend_cap_fb)
        _pf_t = _resolve_targeting(db, adsets[0].get("audience_id") or t.audience_id,
                                   (adsets[0].get("audience_json") or t.audience_json or ""))
        # 批BR 像素统一链（同部署口径——所见即所发）：显式且有权 > 账户自有随机 > 只读自愈；
        # 预检不建像素（allow_create=False）；仍无 → 占位符
        try:
            _pf_lpid = int(((adsets[0].get("ads") or [{}])[0].get("landing_page_id")) or 0)
        except Exception:
            _pf_lpid = 0
        _pf_px, _ = _pick_group_pixel(
            db, tenant_id, body.act_id, (body.pixel_id or t.pixel_id or ""),
            _pf_lpid, None, allow_create=False)
        if not _pf_px:
            _pf_px = "<部署时自动绑定/创建>"
        # 批P1 修2 同口径：未设 advantage_audience 的存量节点按兴趣词启发式（预检=所见即所发）
        _pf_adv = adsets[0].get("advantage_audience")
        if _pf_adv is None:
            _pf_adv = not bool((_pf_t or {}).get("flexible_spec"))
        adset_payload = build_adset(
            name=tree_out[0]["name"], campaign_id="<FB 创建 campaign 后返回>",
            daily_budget=tree_out[0]["budget_local_fb"], objective=t.objective,
            conversion_goal=t.conversion_goal, page_id=(body.page_id or t.page_id or ""),
            pixel_id=_pf_px, landing_url=_lp_url,
            bid_strategy=t.bid_strategy, budget_mode=t.budget_mode,
            targeting=_pf_t,
            dsa_beneficiary=t.beneficiary or "", dsa_payor=t.payer or "",
            optimization_goal=(adsets[0].get("optimization_goal") or t.optimization_goal or ""),
            billing_event=(adsets[0].get("billing_event") or t.billing_event or ""),
            destination_type_override=t.destination_type or "",
            # 出价单一管道（G2②）：首组样例与部署 runner 同口径——组级 bid_amount_usd 换算值
            # 非空时剥离 adv.bid_amount（美分原始值不再覆盖换算值）
            extra=_strip_adv_bid(_parse_advanced(t), _pf_bid_fb),
            # 批次I：组节点转化位置/版位/CTW 号码（与部署 runner 同构；destination_type_override
            # 在 conv_location 非空时被 builder 忽略——隐患A 修复同口径）
            conv_location=(adsets[0].get("conv_location") or ""),
            placements=_node_placements(adsets[0] or {}),
            whatsapp_phone_number=(t.whatsapp_phone_number or ""),
            advantage_audience=_pf_adv,
            bid_amount=_pf_bid_fb)
        creative_payload = build_creative(
            page_id=(body.page_id or t.page_id or ""), objective=t.objective,
            conversion_goal=t.conversion_goal, landing_url=_lp_url,
            headline=_pf_head,
            body=_pf_body,
            cta_type=(first_ad.get("cta_type") or t.cta_type or ""),
            video_id="<部署时按账户上传缓存>" if (first_asset and first_asset.type == "video")
                    else None,
            image_hash=None if (first_asset and first_asset.type == "video")
                    else "<部署时按账户上传缓存>",
            instagram_actor_id=(t.instagram_actor_id or ""))
    except ValueError as e:
        raise HTTPException(400, f"参数校验失败：{e}")
    # 树预检子码存在性（平铺有、树没有——审计/落地页调研双实锤）：坏 slug 部署静默丢追踪
    _bad_slugs = []
    _all_slugs = {ad.get("subcode_slug") for s2 in adsets for ad in (s2.get("ads") or []) if ad.get("subcode_slug")}
    for _slug in _all_slugs:
        if not db.query(LandingAdLink).filter(
                LandingAdLink.tenant_id == tenant_id, LandingAdLink.slug == _slug,
                LandingAdLink.status.in_(["reserved", "active"])).first():
            _bad_slugs.append(_slug)
    if _bad_slugs:
        raise HTTPException(400, f"树内引用的子码不存在或已归档：{_bad_slugs[:5]}（部署会静默丢追踪，请更新广告节点的子码）")
    return {
        "act_id": body.act_id, "platform": "fb", "mode": "tree",
        "currency": currency, "fx_rate": (cr.rate if cr else None),
        "budget_mode": t.budget_mode,
        "budget_usd": t.budget_usd,
        "camp_budget_fb": camp_budget_fb,
        "abo_total_usd": (round(abo_total_usd, 2) if not is_cbo else None),
        "spend_cap_usd": t.spend_cap_usd, "spend_cap_fb": _p_spend_cap_fb,
        "instagram_actor_id": (t.instagram_actor_id or ""),
        "adset_count": len(adsets),
        "ad_total": _tree_expanded_count(adsets),
        "account_count": max(body.account_count or 0, 1),
        "tree": tree_out,
        "will_spend": will_spend,   # 整链开启（部署后立即消耗）的节点；空 = 全部暂停建好待开
        "auto_subcode_nodes": len(_auto_nodes),   # 将自动建链（每广告一子码）的节点数（批次I）
        "objective": t.objective, "conversion_goal": t.conversion_goal or "",
        "campaign": campaign_payload, "adset": adset_payload, "creative": creative_payload,
        "notes": [
            "结构模式：每账户建 1 系列 → N 广告组 → M 广告（素材组节点按素材数展开）",
            "开关关闭的组/广告照建但为 PAUSED（整链开启才开始消耗）",
            "image_hash/video_id 部署时按目标账户上传并缓存",
        ],
    }


def _resolve_targeting(sdb, audience_id: int, audience_json: str = "", sdb_tenant_id: int = 0):
    """解析受众 → targeting dict。优先 audience_json（内联编辑），其次 SavedAudience，None=FB 默认。
    SuperSession（BYPASSRLS）路径必须传 sdb_tenant_id 做 SavedAudience 归属过滤。"""
    # 1. 内联 audience_json（投放模板编辑器直接编辑的受众）
    if audience_json and audience_json.strip():
        try:
            a = json.loads(audience_json)
            countries = a.get("countries") or []
            interests = a.get("interests") or []
            if isinstance(interests, dict):
                interests = [interests]
            if not isinstance(interests, list):
                interests = []
            resolved = [i for i in interests if isinstance(i, dict) and i.get("id")]
            if countries or resolved:
                t = build_targeting(
                    countries=countries, interests=resolved,
                    age_min=a.get("age_min") or 18, age_max=a.get("age_max") or 65,
                    gender=a.get("gender") or 0, strategy=a.get("strategy") or "broad_interest",
                )
                # 用户指定语言（FB targeting.languages：[{id,name}] 或 [id] 透传）
                langs = a.get("languages") or []
                if langs and isinstance(langs, list):
                    t["languages"] = langs
                return t
            # 内联受众空（无国家无兴趣）→ 落到 SavedAudience：显式选了受众的优先，
            # 否则旧数据里残留的空 audience_json 会把 SavedAudience 静默顶掉（都不空=FB 默认）
        except Exception:
            pass
    # 2. SavedAudience
    if not audience_id:
        return None
    aud = sdb.query(SavedAudience).filter(
        SavedAudience.id == audience_id, SavedAudience.tenant_id == sdb_tenant_id,
        SavedAudience.status == "active").first()
    if not aud:
        return None
    return build_targeting(
        countries=json.loads(aud.countries or "[]"),
        interests=json.loads(aud.interests_json or "[]"),
        age_min=aud.age_min, age_max=aud.age_max, gender=aud.gender,
        strategy=aud.strategy or "broad_interest",
    )


def _budget_guard_400(t: LaunchTemplate) -> None:
    """预算守卫（端点层，P0-10/P1-3）：未配置预算 / budget_usd 超安全上限 → 400。
    与 _resolve_budget_fb/_resolve_budget_tt 的 ValueError 同口径（那是后台 runner 兜底，
    这里给部署/预检端点即时 400，避免整 job 建出来全 item fail）。
    结构模式（0088）：CBO 校系列预算（上方两查已覆盖）；ABO 求和所有启用组的日预算
    （组无覆盖用模板默认值；停用组不建不花不算）——N 组各 $X 部署 = 每账户日烧 N×X。"""
    _lt_mode = (t.budget_type or "daily") == "lifetime"
    if not _lt_mode and not ((t.budget_usd or 0) > 0 or (t.daily_budget or 0) > 0):
        raise HTTPException(400, "模板未配置预算，请先在模板编辑器填写日预算再部署")
    if _lt_mode and not ((t.lifetime_budget_usd or 0) > 0 or (t.budget_usd or 0) > 0):
        raise HTTPException(400, "总预算模式未填写总预算金额")
    if (t.budget_usd or 0) > _BUDGET_MAX_USD:
        raise HTTPException(400, f"模板日预算 ${t.budget_usd:.0f} 超安全上限 ${_BUDGET_MAX_USD:.0f}/日，请调低后分步部署")
    # lifetime（总预算）口径：必须有排期 + 上限 $50000（TemplateIn 已拦保存，此处兜底直改库的行）
    if (t.budget_type or "daily") == "lifetime":
        if not ((t.lifetime_budget_usd or 0) > 0):
            raise HTTPException(400, "总预算模式必须填写总预算金额")
        if not (t.schedule_start and t.schedule_end):
            # 树模式排期打通（批次I，审计 C1/P0-3）：树模式没有模板级排期输入（组级排期不回写
            # 模板列），原先报错指向一个不存在的字段=可存不可部署死路。语义：排期随组下发
            # （build_adset 逐组带 start/end），守卫放宽为「任一启用组带完整排期」即视为满足。
            _tree = _parse_structure(t)
            _grp_sched = any(s.get("enabled") and s.get("schedule_start") and s.get("schedule_end")
                             for s in _tree)
            if not _grp_sched:
                raise HTTPException(400, "总预算必须设置排期（开始+结束时间）——FB 硬约束。"
                                          "树模式请在「启用广告组」的预算排期里填开始+结束时间"
                                          "（任一启用组带完整排期即可），或改用单日预算")
        if t.lifetime_budget_usd > 50000:
            raise HTTPException(400, "总预算超安全上限 $50000")
    if (t.budget_mode or "ABO").upper() != "ABO":
        return
    adsets = _parse_structure(t)
    if not adsets:
        return
    _def = float(t.budget_usd or 0)
    total = 0.0
    for s in adsets:
        if not s.get("enabled"):
            continue
        total += float(s.get("budget_usd") or _def)
    if total > _BUDGET_MAX_USD:
        raise HTTPException(
            400, f"结构模式 ABO 求和日预算 ${total:.0f}（{len([s for s in adsets if s.get('enabled')])} 个启用组）"
                 f"超安全上限 ${_BUDGET_MAX_USD:.0f}/日，请调低组预算或停用部分组")


def _resolve_budget_fb(sdb, act_id: str, tpl: LaunchTemplate, tenant_id: int = 0) -> int:
    """模板预算 → 该账户本币最小单位（FB daily_budget）。
    优先 budget_usd（美元，按账户 currency + 汇率转）；无则用 legacy daily_budget。
    空预算不再回退 $2000——静默兜底=钱上瞎猜，直接 ValueError（端点层 _budget_guard_400 先行 400）。
    legacy daily_budget 也过 $5000 USD 等值上限（复审C P2：曾三处守卫都只看 budget_usd，裸透传绕护栏）。"""
    if not ((tpl.budget_usd or 0) > 0 or (tpl.daily_budget or 0) > 0):
        raise ValueError("模板未配置预算（budget_usd/daily_budget 均为空），请填写日预算后再部署")
    if (tpl.budget_usd or 0) > _BUDGET_MAX_USD:
        raise ValueError(f"模板日预算 ${tpl.budget_usd:.0f} 超安全上限 ${_BUDGET_MAX_USD:.0f}/日，请调低后分步部署")
    q = sdb.query(Account).filter(Account.tenant_id == tenant_id,   # 全库审查 P2：SuperSession 绕 RLS 曾无租户过滤
                                                Account.act_id == act_id)
    if tenant_id:
        q = q.filter(Account.tenant_id == tenant_id)
    acc = q.first()
    currency = (acc.currency if acc else "USD") or "USD"
    cr = sdb.query(CurrencyRate).filter(CurrencyRate.code == currency.upper()).first()
    if not cr and currency.upper() != "USD":
        raise ValueError(f"缺少 {currency} 汇率（fx_sync 未同步该币种），无法转换预算。请在系统设置手动配置或先 USD 部署")
    rate = cr.rate if cr else 1.0
    if tpl.budget_usd and tpl.budget_usd > 0:
        return usd_to_fb_amount(tpl.budget_usd, currency, rate)
    _usd_eq = (tpl.daily_budget or 0) / 100.0 / rate   # FB minor units 本币 → major 本币 → USD
    if _usd_eq > _BUDGET_MAX_USD:
        raise ValueError(f"模板 legacy 日预算约 ${_usd_eq:.0f} 超安全上限 ${_BUDGET_MAX_USD:.0f}/日，请改用预算(USD)字段并调低")
    return tpl.daily_budget


def _usd_to_account_minor(sdb, act_id: str, usd: float, tenant_id: int) -> int:
    """USD 金额 → 该账户本币最小单位（预算/出价额换算共用——与 _resolve_budget_fb 同汇率管道）。
    缺汇率抛 ValueError（调用方消化为组级/广告级失败）。"""
    acc = sdb.query(Account).filter(Account.tenant_id == tenant_id,
                                    Account.act_id == act_id).first()
    currency = (acc.currency if acc else "USD") or "USD"
    cr = sdb.query(CurrencyRate).filter(CurrencyRate.code == currency.upper()).first()
    if not cr and currency.upper() != "USD":
        raise ValueError(f"缺少 {currency} 汇率（fx_sync 未同步该币种）")
    return usd_to_fb_amount(float(usd), currency, cr.rate if cr else 1.0)


# ── TikTok 分支 helper（TK P3；platform='tt' 才会走到，FB 路径零改动）──

def _resolve_budget_tt(sdb, act_id: str, tpl: LaunchTemplate, tenant_id: int = 0) -> int:
    """模板预算 → 该账户本币**整数**（TT 预算无 FB 的 minor units ×100）。
    优先 budget_usd（按账户 currency + 汇率转）；legacy daily_budget 是 FB 最小单位 → /100 回整本币。"""
    from ..core.tt_ad_builder import usd_to_tt_amount
    if not ((tpl.budget_usd or 0) > 0 or (tpl.daily_budget or 0) > 0):
        raise ValueError("模板未配置预算（budget_usd/daily_budget 均为空），请填写日预算后再部署")
    if (tpl.budget_usd or 0) > _BUDGET_MAX_USD:
        raise ValueError(f"模板日预算 ${tpl.budget_usd:.0f} 超安全上限 ${_BUDGET_MAX_USD:.0f}/日，请调低后分步部署")
    q = sdb.query(Account).filter(Account.tenant_id == tenant_id,   # 全库审查 P2：SuperSession 绕 RLS 曾无租户过滤
                                                Account.act_id == act_id)
    if tenant_id:
        q = q.filter(Account.tenant_id == tenant_id)
    acc = q.first()
    currency = (acc.currency if acc else "USD") or "USD"
    cr = sdb.query(CurrencyRate).filter(CurrencyRate.code == currency.upper()).first()
    if not cr and currency.upper() != "USD":
        raise ValueError(f"缺少 {currency} 汇率（fx_sync 未同步该币种），无法转换预算。请在系统设置手动配置或先 USD 部署")
    if tpl.budget_usd and tpl.budget_usd > 0:
        return usd_to_tt_amount(tpl.budget_usd, currency, cr.rate if cr else 1.0)
    _usd_eq = (tpl.daily_budget or 0) / 100.0 / (cr.rate if cr else 1.0)   # 同 FB：legacy 也过 USD 等值上限（复审C P2）
    if _usd_eq > _BUDGET_MAX_USD:
        raise ValueError(f"模板 legacy 日预算约 ${_usd_eq:.0f} 超安全上限 ${_BUDGET_MAX_USD:.0f}/日，请改用预算(USD)字段并调低")
    return max(1, int(round(tpl.daily_budget / 100)))


def _resolve_tt_targeting(sdb, audience_id: int, audience_json: str = "", sdb_tenant_id: int = 0) -> dict:
    """解析受众 → TT targeting（countries/age/gender）。

    数据源与 FB 的 _resolve_targeting 同（内联 audience_json / SavedAudience），但只迁移
    地理+人口维度——FB adinterest 兴趣 ID 与 TT 兴趣词库（/tool/interest_category/）不互通，
    迁移错 ID 会静默错定向，宁可不带。TT 兴趣词库接入后走 interest_category_ids。
    """
    from ..core.tt_ad_builder import build_tt_targeting
    a: dict = {}
    if audience_json and audience_json.strip():
        try:
            a = json.loads(audience_json)
        except Exception:
            a = {}
    if not (a.get("countries") or []) and audience_id:
        aud = sdb.query(SavedAudience).filter(
            SavedAudience.id == audience_id, SavedAudience.tenant_id == sdb_tenant_id,
            SavedAudience.status == "active").first()
        if aud:
            a = {"countries": json.loads(aud.countries or "[]"), "age_min": aud.age_min,
                 "age_max": aud.age_max, "gender": aud.gender}
    return build_tt_targeting(
        countries=a.get("countries") or [], age_min=a.get("age_min") or 18,
        age_max=a.get("age_max") or 65, gender=a.get("gender") or 0)


def _resolve_tt_pixel(sdb, tenant_id: int, tpl: LaunchTemplate, item_pixel: str = "",
                      act_id: str = "") -> str:
    """TT 像素 code 解析（TT 转化绑定的是像素 code，不是 FB 的 pixel_id 数字串语义）。

    优先级：部署 item 手选 > 模板手填 > 落地页 tt_pixel_ids[0] > 像素库 platform='tt'
    （绑定了目标广告主 act_id 的优先，否则任一 active TT 像素）。解析不到返空串
    （web 转化目标由 _deploy_item_tt 预检拦截报清晰错）。
    """
    if item_pixel:
        return item_pixel
    if tpl.pixel_id:
        return tpl.pixel_id
    if tpl.landing_page_id:
        lp = sdb.query(LandingPage).filter(
            LandingPage.id == tpl.landing_page_id, LandingPage.tenant_id == tenant_id).first()
        if lp and lp.tt_pixel_ids:
            try:
                ids = json.loads(lp.tt_pixel_ids)
                if ids:
                    return str(ids[0])
            except Exception:
                pass
    from ..models.landing_lib import LandingPixel
    rows = sdb.query(LandingPixel).filter(
        LandingPixel.tenant_id == tenant_id, LandingPixel.platform == "tt",
        LandingPixel.status != "archived",
    ).order_by(LandingPixel.id.desc()).all()
    if not rows:
        return ""
    if act_id:
        for r in rows:
            if (r.act_id or "") == act_id:
                return r.pixel_id
    return rows[0].pixel_id


def _deploy_item_tt(sdb, job, item: LaunchJobItem, tpl: LaunchTemplate, asset, tenant_id: int,
                    link, is_retry: bool = False, name_prefix_override: str = "") -> None:
    """单账户 TT 部署（_run_deploy_job / _retry_one 的 TT 分支共用）。

    链路：纳管复查 → tt_client_for_account（TT 令牌不走 FB 令牌池）→ 素材 file_id
    （按广告主上传+行锁缓存）→ 预算本币整数 → 像素 code → deploy_one_account_tt 三件套。
    错误消化为 item fail（TtApiError.category 进 error_code 供前端 i18n），不外抛。
    name_prefix_override：批量模式由 _deploy_item_tt_batch 传入（系列名=素材名）；
    空 = 单模板模式沿用 tpl.name_prefix。job=None 时只写 item 状态不动 job 计数（批量汇总用）。
    """
    from ..core.ad_ops import (deploy_one_account_tt, ensure_tt_file_id_for_account,
                               tt_client_for_account)
    from ..core.tt_ad_builder import normalize_tt_objective
    try:
        from ..models.fb import Account as _AccT
        _acc = sdb.query(_AccT).filter(
            _AccT.tenant_id == tenant_id, _AccT.act_id == item.act_id,
            _AccT.is_managed == True,  # noqa: E712
        ).first()
        if not _acc:
            raise TtApiError("no_id", "该账户已移除纳管，跳过（移除后建广告无止损覆盖）")
        tt = tt_client_for_account(sdb, tenant_id, item.act_id)
        if not tt:
            raise TtApiError("no_id", f"账户 {item.act_id} 无可用 TikTok 令牌（TT 账户走 tt_credentials 绑定/候选池）")
        # per-advertiser 素材 file_id 缓存（首次上传可能耗时：视频大文件分块）
        image_file_id = ""
        video_file_id = ""
        if asset and asset.type in ("image", "video"):
            filepath = os.path.join(ASSET_DIR, asset.storage_key)
            if not os.path.exists(filepath):
                raise TtApiError("no_id", f"素材文件丢失: {asset.storage_key}")
            fid = ensure_tt_file_id_for_account(tt, sdb, asset, item.act_id, filepath)
            if asset.type == "video":
                video_file_id = fid
            else:
                image_file_id = fid
            sdb.commit()  # 持久化 file_id 缓存（后续部署同广告主直接命中）
        daily_budget_tt = _resolve_budget_tt(sdb, item.act_id, tpl, tenant_id)
        pixel_code = _resolve_tt_pixel(sdb, tenant_id, tpl, item.pixel_id or "", item.act_id)
        if not pixel_code and normalize_tt_objective(tpl.objective) == "WEB_CONVERSIONS":
            raise TtApiError("invalid_param",
                             "未解析到 TikTok 像素 code（转化类目标必填）：部署抽屉选 TT 像素 / 模板填像素 code / 像素库添加 platform=tt 像素")
        # 文案优先级（批次II 修审计 A3，与 FB 链同口径）：单模板=模板手填 > 素材 AI 随机；
        # 批量模式（name_prefix_override=素材名，逐素材克隆系列）=素材 AI > 模板文案兜底——
        # 多素材各用各的文案（TT 创意只有 ad_text 无独立标题，headline 仅作兜底文案源）
        from ..core.ad_ops import pick_ad_copy
        if name_prefix_override:
            _tt_head, _body = pick_ad_copy(asset, "", "", tpl.headline or "", tpl.body or "")
        else:
            _tt_head, _body = pick_ad_copy(asset, tpl.headline or "", tpl.body or "")
        # 追踪参数插值（与 FB 链同口径）：{{campaign.name}}=系列名（批量=素材名）
        _tt_sn = name_prefix_override or tpl.name_prefix
        _lp_url = _interp_landing_url(
            tpl.landing_url, campaign_name=_tt_sn,
            account_name=(_acc.name if _acc else ""), account_id=item.act_id,
            asset_name=((asset.name or asset.filename or "") if asset else ""),
            template_name=tpl.name, platform="tt")
        r = deploy_one_account_tt(
            tt, advertiser_id=item.act_id, objective=tpl.objective,
            conversion_goal=tpl.conversion_goal, pixel_code=pixel_code,
            landing_url=_lp_url, daily_budget=daily_budget_tt,
            budget_mode=tpl.budget_mode, name_prefix=name_prefix_override or tpl.name_prefix,
            headline=_tt_head, body=_body, cta_type=tpl.cta_type,
            image_file_id=image_file_id, video_file_id=video_file_id,
            subcode_slug=tpl.subcode_slug, subcode_link=link,
            targeting=_resolve_tt_targeting(sdb, tpl.audience_id, tpl.audience_json or "", tenant_id),
        )
        item.campaign_id = r["campaign_id"]; item.adset_id = r["adgroup_id"]; item.ad_id = r["ad_id"]
        item.status = "success"; item.error = None
        if job:
            job.succeeded = (job.succeeded or 0) + 1
            if is_retry and (job.failed or 0) > 0:
                job.failed -= 1  # 重试成功：撤销原 fail 计数（与 FB _retry_one 口径一致）
        write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                  target_type="ad", target_id=str(r.get("ad_id", "")),
                  action_type="deploy", source="launch", result="success",
                  metadata={"act_id": item.act_id, "campaign_id": r.get("campaign_id"),
                            "adgroup_id": r.get("adgroup_id"), "template_id": tpl.id, "platform": "tt"})
    except TtApiError as e:
        item.status = "fail"; item.error = (e.friendly or str(e))[:300]; item.error_code = e.category
        if job and not is_retry:
            job.failed = (job.failed or 0) + 1  # 重试失败：原 fail 已计数过，不重复加
        write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                  target_type="ad", target_id="", action_type="deploy", source="launch",
                  result="fail", friendly_error=(e.friendly or str(e))[:200],
                  metadata={"act_id": item.act_id, "template_id": tpl.id, "platform": "tt"})
    except Exception as e:
        item.status = "fail"; item.error = str(e)[:300]; item.error_code = "error"
        if job and not is_retry:
            job.failed = (job.failed or 0) + 1
        write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                  target_type="ad", target_id="", action_type="deploy", source="launch",
                  result="fail", friendly_error=str(e)[:200],
                  metadata={"act_id": item.act_id, "template_id": tpl.id, "platform": "tt"})


def _preflight_tt(db, t: LaunchTemplate, body: PreflightIn, tenant_id: int, batch_assets: list = None) -> dict:
    """TT 模板预检：构建（不发送）campaign/adgroup/creative payload + 预算换算 + 像素解析。
    不调 TT、不花钱；sandbox 校准期最有价值的核对工具。批量模式（batch_assets 非空）：
    示例 payload 用第一个素材（系列名=素材名）+ 附 series_count。"""
    from ..core.tt_ad_builder import build_tt_campaign, build_tt_adgroup, build_tt_creative
    batch_assets = batch_assets or []
    try:
        daily_budget_tt = _resolve_budget_tt(db, body.act_id, t, tenant_id)
    except ValueError as e:
        logging.getLogger("toveads.launch").warning(f"preflight tt budget resolve failed: {e}")
        raise HTTPException(400, "预算换算失败：账户币种缺少汇率，请在系统设置配置汇率或改用 USD 模板")
    targeting = _resolve_tt_targeting(db, t.audience_id, t.audience_json or "", tenant_id)
    pixel_code = _resolve_tt_pixel(db, tenant_id, t, body.pixel_id or "", body.act_id)
    asset = (batch_assets[0] if batch_assets else
             (db.query(Asset).filter(Asset.id == t.asset_id, Asset.tenant_id == tenant_id).first()
              if t.asset_id else None))
    _prefix = _series_name(t, asset, 0) if batch_assets else t.name_prefix
    # 文案样例与部署 runner 同口径（预检=所见即所发）：批量=素材 AI 优先，单模板=模板手填优先
    from ..core.ad_ops import pick_ad_copy as _pf_pick_copy
    if batch_assets:
        _pf_head, _pf_body = _pf_pick_copy(asset, "", "", t.headline or "", t.body or "")
    else:
        _pf_head, _pf_body = _pf_pick_copy(asset, t.headline or "", t.body or "")
    acc = db.query(Account).filter(Account.act_id == body.act_id).first()
    currency = (acc.currency if acc else "USD") or "USD"
    cr = db.query(CurrencyRate).filter(CurrencyRate.code == currency.upper()).first()
    # 追踪参数插值（与 FB 预检同口径）：非法占位符快失败 + 示例解值
    try:
        _check_url_placeholders(t.landing_url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _lp_url = _interp_landing_url(
        t.landing_url, campaign_name=_prefix,
        account_name=(acc.name if acc else ""), account_id=body.act_id,
        asset_name=((asset.name or asset.filename or "") if asset else ""),
        template_name=t.name, platform="tt")
    try:
        campaign_payload = build_tt_campaign(
            name=_prefix, objective=t.objective,
            daily_budget=daily_budget_tt if t.budget_mode.upper() == "CBO" else None,
            budget_mode=t.budget_mode)
        adgroup_payload = build_tt_adgroup(
            name=f"{_prefix} 组", campaign_id="<TT 创建 campaign 后返回>",
            daily_budget=daily_budget_tt, objective=t.objective,
            conversion_goal=t.conversion_goal,
            pixel_code=pixel_code or "<部署时从 TT 像素库解析>",
            budget_mode=t.budget_mode, targeting=targeting)
        creative_payload = build_tt_creative(
            ad_text=_pf_body, cta_type=t.cta_type, landing_url=_lp_url,
            video_file_id="<部署时按广告主上传缓存>" if (asset and asset.type == "video") else "",
            image_file_id="<部署时按广告主上传缓存>" if (asset and asset.type == "image") else "")
    except ValueError as e:
        raise HTTPException(400, f"参数校验失败：{e}")
    # daily_budget_fb 键名沿用（前端预检弹窗按此键渲染；TT 值为本币整数，notes 里说明单位差异）
    out = {
        "act_id": body.act_id, "platform": "tt", "currency": currency,
        "budget_usd": t.budget_usd, "fx_rate": (cr.rate if cr else None),
        "daily_budget_fb": daily_budget_tt, "budget_mode": t.budget_mode,
        "asset": {
            "type": (asset.type if asset else ""),
            "name": (asset.name or asset.filename or "") if asset else "",
            "filename": (asset.filename or "") if asset else "",
            "duration_sec": (asset.duration_sec or 0) if asset else 0,
        },
        "objective": t.objective, "optimization_goal": adgroup_payload.get("optimization_goal"),
        "targeting_resolved": targeting,
        "campaign": campaign_payload, "adset": adgroup_payload, "creative": creative_payload,
        "notes": [
            "TT 预算单位=当地币种整数（无 FB 的最小货币单位 ×100）",
            "file_id（video_id/image_id）部署时按目标广告主上传并缓存到素材行",
            "广告出生暂停（operation_status=DISABLE），TT 审核通过后手动开启",
            "campaign_id / adgroup_id 部署时由 TT 返回填入",
        ],
    }
    if batch_assets:
        out["series_count"] = len(batch_assets) * max(body.account_count or 0, 1)
        out["batch_assets"] = [{"id": a.id, "name": _series_name(t, a, i), "type": a.type}
                               for i, a in enumerate(batch_assets)]
    return out


def _parse_advanced(tpl: LaunchTemplate) -> dict | None:
    """解析模板的 advanced_config JSON（高级 FB 字段）。"""
    if not tpl.advanced_config or not tpl.advanced_config.strip():
        return None
    try:
        cfg = json.loads(tpl.advanced_config)
        return cfg if isinstance(cfg, dict) else None
    except Exception:
        return None


def _strip_adv_bid(adv: dict | None, bid_fb) -> dict | None:
    """出价单一管道（批次II 修审计 G2②）：模板出价控制（bid_amount_usd 按账户本币换算的
    bid_fb）非空时，从 advanced_config 剥离 adv.bid_amount——它是旧 CPA 性能目标存的美分
    原始值，深合并会覆盖换算值（非 USD 账户出价额错一个汇率量级）。模板出价优先；
    两者都空时原样返回（adv.bid_amount 直通=旧行为）。返回剥离后的浅拷贝，不动调用方 dict。"""
    if not adv or bid_fb is None or "bid_amount" not in adv:
        return adv
    return {k: v for k, v in adv.items() if k != "bid_amount"}


def _resolve_lead_form(fb, sdb, tpl: LaunchTemplate, asset: Asset, page_id: str, landing_url: str,
                       post_content: dict = None, tt=None, act_id: str = "") -> str:
    """部署时解析 Instant Form ID（page/advertiser-aware）。优先级：
    1. tpl.lead_form_template_id（选了表单模板）→ 同载体有 form_id 复用；否则按 config 建到「目标载体」
    2. tpl.lead_form_id（手填的已建 form_id）→ 直接用（用户自负；可能跨载体失效）
    3. 都没有 → AI 从素材文案自动生成 + 建（_ai_auto_create_form）

    注意：form_id 与载体绑定（FB 校验 form 属于 adset 的 page）。表单模板路径按目标载体
    解析，所以多账户不同载体部署每个都拿到正确的 form；手填 lead_form_id 路径不校验载体，
    仅当未选模板时兜底。

    平台分发：tpl.platform='tt' 走 TT Instant Form（载体=advertiser_id，TT 令牌 tt +
    act_id 由调用方传；FB 令牌 fb 不用）；platform='fb'（含存量默认）走下方 FB 原路零改动。
    """
    # ── TikTok 分支（TT Instant Form；tt/act_id 缺齐时逐级降级到手填→AI，仍绝不触 FB 链路）──
    if (tpl.platform or "fb") == "tt":
        from ..core.ad_builder import build_tt_lead_form_payload, tt_lead_form_id_from_result
        # 1. 表单模板（advertiser-aware；编辑器 config 与 FB 共用一套，TT builder 映射枚举）
        if tpl.lead_form_template_id:
            from ..models.lead_form_template import LeadFormTemplate
            ft = sdb.query(LeadFormTemplate).filter(
                LeadFormTemplate.id == tpl.lead_form_template_id,
                LeadFormTemplate.tenant_id == tpl.tenant_id).first()
            if ft and tt and act_id:
                # 复用仅限 tt 模板缓存的 TT form_id（fb 模板缓存的是 FB id，语义不同不复用）
                if (ft.platform or "fb") == "tt" and ft.fb_form_id and ft.fb_page_id == act_id:
                    return ft.fb_form_id
                cfg = {}
                if ft.config_json:
                    try: cfg = json.loads(ft.config_json)
                    except: cfg = {}
                try:
                    payload = build_tt_lead_form_payload(
                        form_title=cfg.get("form_title", ft.name),
                        privacy_url=cfg.get("privacy_url", "https://tovaads.com/privacy"),
                        target_countries=cfg.get("target_countries", []),
                        description=cfg.get("description", ""),
                        custom_questions=cfg.get("custom_questions", []),
                        extra_contact_fields=cfg.get("extra_contact_fields", ["EMAIL"]),
                        thank_you_title=cfg.get("thank_you_title", ""),
                        thank_you_body=cfg.get("thank_you_body", ""),
                        name_prefix="Tova",
                    )
                    result = tt.post("lead/form/create/", {**payload, "advertiser_id": act_id})
                    form_id = tt_lead_form_id_from_result(result)
                    if form_id:
                        # 缓存到模板（同 advertiser 下次复用；不同 advertiser 每个重建）
                        if not ft.fb_form_id or ft.fb_page_id != act_id:
                            ft.fb_form_id = form_id; ft.fb_page_id = act_id
                        return form_id
                except Exception:
                    pass  # 落到手填/AI 兜底
        # 2. 手填 lead_form_id
        if tpl.lead_form_id:
            return tpl.lead_form_id
        # 3. AI 兜底（有素材 OR 跟帖有帖内容；fb 参数传 None——TT 链路不用）
        if tt and act_id and (asset or (post_content and (post_content.get("message") or post_content.get("headline")))):
            return _ai_auto_create_form(None, sdb, asset, act_id, landing_url, post_content=post_content,
                                        platform="tt", tt=tt, act_id=act_id)
        return ""
    # ── FB 原路（platform='fb' 零改动）──
    # 1. 表单模板（page-aware）
    if tpl.lead_form_template_id:
        from ..models.lead_form_template import LeadFormTemplate
        ft = sdb.query(LeadFormTemplate).filter(
            LeadFormTemplate.id == tpl.lead_form_template_id,
            LeadFormTemplate.tenant_id == tpl.tenant_id).first()
        if ft:
            # 已部署到同 page → 复用
            if ft.fb_form_id and ft.fb_page_id == page_id:
                return ft.fb_form_id
            cfg = {}
            if ft.config_json:
                try: cfg = json.loads(ft.config_json)
                except: cfg = {}
            from ..core.ad_builder import build_lead_form_payload, lead_form_safe_payload
            # 感谢页按钮：显式选了 website 才带；whatsapp/none 是本地配置不进 FB payload
            # （否则 landing_url 兜底会把 whatsapp 选择变成 FB VIEW_WEBSITE 按钮）。见 0090 批。
            _ty_btn_type = str(cfg.get("thank_you_button_type", "") or "").strip()
            _btn_website = (_ty_btn_type == "website") if _ty_btn_type else True
            payload = build_lead_form_payload(
                form_title=cfg.get("form_title", ft.name),
                privacy_url=cfg.get("privacy_url", "https://tovaads.com/privacy"),
                locale=cfg.get("locale", ft.locale or "en_US"),
                target_countries=cfg.get("target_countries", []),
                description=cfg.get("description", ""),
                custom_questions=cfg.get("custom_questions", []),
                extra_contact_fields=cfg.get("extra_contact_fields", ["EMAIL"]),
                privacy_link_text=cfg.get("privacy_link_text", "Privacy Policy"),
                thank_you_title=cfg.get("thank_you_title", ""),
                thank_you_body=cfg.get("thank_you_body", ""),
                thank_you_button_text=cfg.get("thank_you_button_text", "") if _btn_website else "",
                thank_you_website_url=cfg.get("thank_you_website_url", landing_url) if _btn_website else "",
                follow_up_url=cfg.get("follow_up_url", landing_url),
                context_card_title=cfg.get("context_card_title", ""),
                name_prefix="Tova",
                is_optimized_for_quality=bool(cfg.get("is_optimized_for_quality", False)),
                welcome_message=cfg.get("welcome_message", ""),
                only_visible_to_target_countries=bool(cfg.get("only_visible_to_target_countries", False)),
            )
            try:
                result = fb.post(f"{page_id}/leadgen_forms", payload)
                form_id = result.get("id")
                if not form_id:
                    safe = lead_form_safe_payload(payload)
                    result = fb.post(f"{page_id}/leadgen_forms", safe)
                    form_id = result.get("id")
                if form_id:
                    # 缓存到模板（同 page 下次复用）。不同 page 的 form 不缓存（每页重建，保证 page 正确）
                    if not ft.fb_form_id or ft.fb_page_id != page_id:
                        ft.fb_form_id = form_id; ft.fb_page_id = page_id
                    return form_id
            except Exception:
                pass  # 落到手填/AI 兜底
    # 2. 手填 lead_form_id（不校验 page；仅未选模板时用）
    if tpl.lead_form_id:
        return tpl.lead_form_id
    # 3. AI 兜底（有素材 OR 跟帖有帖内容）
    if page_id and (asset or (post_content and (post_content.get("message") or post_content.get("headline")))):
        return _ai_auto_create_form(fb, sdb, asset, page_id, landing_url, post_content=post_content)
    return ""


def _ai_auto_create_form(fb, sdb, asset: Asset, page_id: str, landing_url: str, post_content: dict = None,
                         platform: str = "fb", tt=None, act_id: str = "") -> str:
    """没选表单模板时，从素材 AI 文案（跟帖无素材→用帖内容）自动生成 Instant Form + 建到平台。返 form_id。

    平台分发：platform='tt' → build_tt_lead_form_payload + tt 令牌建到 advertiser（act_id）；
    platform='fb'（默认）→ 原路 build_lead_form_payload + fb 令牌建到 page，零改动。
    """
    from ..core.ad_builder import build_lead_form_payload, lead_form_safe_payload
    from ..core.ai_client import AiClient, AiError
    ai = AiClient()
    if not ai.is_configured():
        return ""
    ai_copy = json.loads(asset.ai_copy_json or "{}") if (asset and asset.ai_copy_json) else {}
    headlines = ai_copy.get("headlines", [])
    bodies = ai_copy.get("bodies", [])
    # 跟帖无素材 → 用帖内容（headline/message）作 AI 输入
    if not headlines and not bodies and post_content:
        headlines = [post_content.get("headline", "")] if post_content.get("headline") else []
        bodies = [post_content.get("message", "")] if post_content.get("message") else []
    is_tt = platform == "tt"
    sys_msg = (f"你是 {'TikTok' if is_tt else 'FB'} Instant Form 设计专家。"
               "根据广告素材信息设计潜在客户表单。严格只返回 JSON。")
    prompt = (
        f"广告标题参考：{headlines[:3]}\n广告正文参考：{bodies[:2]}\n\n"
        "生成 Instant Form 配置 JSON：\n"
        '{"form_title":"表单标题","description":"表单说明",'
        '"custom_questions":[{"key":"q1","label":"问题","placeholder":"提示"}],'
        '"extra_contact_fields":["EMAIL"],"thank_you_title":"感谢标题","thank_you_body":"感谢正文"}\n'
        "生成 2-3 个有意义的自定义问题。follow_up_url 不用填。"
    )
    data = ai.chat_json([{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}],
                        temperature=0.7, max_tokens=2048)
    # TikTok 分支：shared config → TT payload → lead/form/create/（sandbox 校准点）
    if is_tt:
        if not (tt and act_id):
            return ""
        from ..core.ad_builder import build_tt_lead_form_payload, tt_lead_form_id_from_result
        try:
            payload = build_tt_lead_form_payload(
                form_title=data.get("form_title", (asset.name if asset else None) or (post_content or {}).get("headline") or "Lead Form"),
                privacy_url="https://tovaads.com/privacy",
                target_countries=[], description=data.get("description", ""),
                custom_questions=data.get("custom_questions", []),
                extra_contact_fields=data.get("extra_contact_fields", ["EMAIL"]),
                thank_you_title=data.get("thank_you_title", ""),
                thank_you_body=data.get("thank_you_body", ""),
                name_prefix="AI",
            )
            result = tt.post("lead/form/create/", {**payload, "advertiser_id": act_id})
            return tt_lead_form_id_from_result(result) or ""
        except Exception:
            return ""
    payload = build_lead_form_payload(
        form_title=data.get("form_title", (asset.name if asset else None) or (post_content or {}).get("headline") or "Lead Form"),
        privacy_url="https://tovaads.com/privacy",
        locale="en_US", target_countries=[], description=data.get("description", ""),
        custom_questions=data.get("custom_questions", []),
        extra_contact_fields=data.get("extra_contact_fields", ["EMAIL"]),
        thank_you_title=data.get("thank_you_title", ""),
        thank_you_body=data.get("thank_you_body", ""),
        thank_you_button_text="Visit Website" if landing_url else "",
        thank_you_website_url=landing_url,
        follow_up_url=landing_url,
        name_prefix="AI",
    )
    try:
        result = fb.post(f"{page_id}/leadgen_forms", payload)
        form_id = result.get("id")
        if not form_id:
            safe = lead_form_safe_payload(payload)
            result = fb.post(f"{page_id}/leadgen_forms", safe)
            form_id = result.get("id")
        return form_id or ""
    except Exception:
        return ""


def _resolve_page_post(sdb, fb, tenant_id: int, tpl: LaunchTemplate, asset, page_id: str, body: str = "") -> str:
    """返 page_post_id 供 deploy_one_account 走 object_story_id（引用主页帖）。
    - 跟帖(reuse + reuse_post_ref)：直接引用已存在帖，object_story_id。
      引用已存在帖不建新帖，不依赖 dev 模式——Live/standard App 也可用（已冒烟验证 creative 建成）。
    - 新建帖(dev app only)：建主页帖拿 post_id；standard App 建 new post 撞 code3 → 返空走 object_story_spec。"""
    # 1) 跟帖复用：引用已存在帖（object_story_id），前置——不依赖 dev 模式
    if (tpl.post_source or "new") == "reuse" and tpl.reuse_post_ref and page_id:
        ref_page = tpl.reuse_post_ref.split("_", 1)[0]
        if ref_page and ref_page != page_id:
            raise FbApiError("invalid_param",
                             f"跟帖帖子属主页 {ref_page}，与部署目标主页 {page_id} 不一致（帖子不能跨主页引用）")
        return tpl.reuse_post_ref
    # 2) 新建帖路径仅 dev 模式（standard 建 new post 撞 code3）
    from ..routers.fb_apps import FbApp
    from ..core.page_post import get_or_create_page_post
    app = sdb.query(FbApp).filter(FbApp.tenant_id == tenant_id, FbApp.status == "active").first()
    if not app:
        app = sdb.query(FbApp).filter(FbApp.tenant_id.is_(None), FbApp.status == "active").first()
    if (getattr(app, "access_level", "dev") or "dev").lower() != "dev":
        return ""
    if not (page_id and asset and asset.type == "image"):
        return ""
    # 帖子按 (page,asset) 缓存跨账户共享 → 链接只解稳定占位符（复审R2-P2）：
    # 系列/账户级变量剥离为空，避免字面 {{xxx}} 进帖子链接
    _lp = _stable_landing_url(tpl.landing_url or "", tpl.name or "")
    return get_or_create_page_post(sdb, fb, tenant_id, page_id, asset.id, body or tpl.body or "", _lp, asset.public_url or "")


def _reap_stale_jobs():
    """回收孤儿 job：重启/崩溃后 BackgroundTask 全死，pending/running 是孤儿
    （FB 侧广告可能已建在花钱）→ 标 failed 提示重试。
    判据 = 心跳超时（runner 每 item touch created_at）：超 10 分钟无心跳才算死——
    单 worker 崩溃重启不会误杀其他 worker 正在跑的长任务（误杀 → 用户重试 = 双份广告）。
    startup 即跑一次 + 每 5min 由 scheduler 巡检（main.py）；advisory lock 116 多 worker 单飞。"""
    _lock = acquire_run_lock(116)
    if not _lock:
        return  # 其他 worker 正在回收
    sdb = SuperSessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        stale = sdb.query(LaunchJob).filter(
            LaunchJob.status.in_(("pending", "running")),
            LaunchJob.created_at < cutoff,
        ).all()
        for j in stale:
            j.status = "failed"
            j.finished_at = datetime.now(timezone.utc)
            sdb.query(LaunchJobItem).filter(
                LaunchJobItem.job_id == j.id,
                LaunchJobItem.status.in_(("pending", "creating")),
            ).update({"status": "fail", "error": "job 中断（服务重启），请检查 FB 后台并重试",
                      "progress": None},
                     synchronize_session=False)
        if stale:
            sdb.commit()
            logging.getLogger("toveads.launch").warning(
                f"[Launch] 回收 {len(stale)} 个中断 job: {[j.id for j in stale]}")
    finally:
        sdb.close()
        release_run_lock(_lock, 116)


def _refresh_ads_cache_after_deploy(tenant_id: int, act_ids: list[str]):
    """部署收尾对账：逐账户拉最新 campaigns/adsets/ads → upsert ads_cache。

    部署清单的 live_status 与广告管理器的「刚部署即可见」都依赖它。在 job 已置终态
    后调用（本函数失败不影响 job 结果）；单账户失败跳过——15min 的 run_ads_cache_sync
    cron 兜底。复用 ads.py._sync_one 的 upsert 逻辑（同一缓存格式）。"""
    if not act_ids:
        return
    from ..routers.ads import _sync_one
    sdb = SuperSessionLocal()
    try:
        for act_id in sorted(set(act_ids)):
            try:
                fb = client_for_account(sdb, tenant_id, act_id, "read")
                if fb and _sync_one(sdb, tenant_id, act_id, fb):
                    sdb.commit()
            except Exception:
                sdb.rollback()
                logging.getLogger("toveads.launch").warning(
                    f"[Launch] 部署对账刷新 ads_cache 失败: act_{act_id}", exc_info=True)
    finally:
        sdb.close()


def _job_batch_assets(sdb, job_id: int, tenant_id: int) -> list:
    """回读 job 的批量素材清单。launch_jobs 没有素材清单列（加列需迁移，超出本次改动
    范围），deploy 端点把 asset_ids 存进 action_logs.metadata（与 job 同事务提交，
    target_id=job.id 唯一定位）。查不到/空 = 单模板模式（旧 job 一律走这里，天然兼容）。
    素材行已被删的静默剔除——重试时素材可能已删，剩余素材照跑（少建对应系列好过硬建失败）。"""
    from ..models.log import ActionLog
    try:
        row = sdb.query(ActionLog).filter(
            ActionLog.tenant_id == tenant_id, ActionLog.target_type == "launch_job",
            ActionLog.target_id == str(job_id), ActionLog.action_type == "deploy",
            ActionLog.result == "success",
        ).order_by(ActionLog.id.desc()).first()
        if not row or not row.metadata_:
            return []
        ids = json.loads(row.metadata_).get("asset_ids") or []
    except Exception as e:
        # 复审R2-P1：这里静默 return [] 会把批量 job 降级成单模板部署（少建系列且无感）——
        # 必须留痕；仍返回 [] 兜底（旧 job 本来就是单模板语义，15min 对账/清单可核）
        logging.getLogger("toveads.launch").warning(
            f"batch assets 回读失败(job={job_id})，按单模板处理: {e}")
        return []
    if not ids:
        return []
    rows = sdb.query(Asset).filter(Asset.id.in_(ids), Asset.tenant_id == tenant_id).all()
    by = {a.id: a for a in rows}
    return [by[i] for i in ids if i in by]


def _item_note(sdb, item: LaunchJobItem, note: str) -> None:
    """item 实时进度注记（批BQ）：写 progress + touch job/item 心跳（一条原生 UPDATE + commit）。
    部署中任意时刻进度弹窗可见「正在哪一步、多久没动」——creating 只有转圈的时代结束
    （用户 09-11 实测：12 广告树跑 1 分钟全黑盒被当「卡住」）。原生 UPDATE 避开 ORM
    残留态（批AM StaleDataError 教训）；item.created_at 即「最后更新」时间戳（前端显龄）。"""
    from sqlalchemy import text as _t
    sdb.execute(_t("UPDATE launch_job_items SET progress = :p, created_at = now() WHERE id = :i"),
                {"p": (note or "")[:200], "i": item.id})
    sdb.execute(_t("UPDATE launch_jobs SET created_at = now() WHERE id = :j"), {"j": item.job_id})
    sdb.commit()


def _apply_batch_result(job, item: LaunchJobItem, total: int, ok: int, fails: list,
                        last: Optional[dict], is_retry: bool = False, unit: str = "系列") -> None:
    """批量 item（=账户）汇总落账：全部成功 = success/error=None；任一失败 = fail +
    error_code="partial" + 汇总文案（成功 X/Y + 前 3 条「名字:原因」，300 字内）。
    item 的 campaign/adset/ad id 存最后一个成功对象——已部署清单的跳转/live_status 至少
    能对账一个，全量明细看 error 汇总与平台后台（200 个塞 item 字段既没列也不可读）。
    计数口径与单模板模式一致：item 是计数单位（成功+1 / 失败+1），不是按对象计。
    unit：批量生成=系列（默认）；结构模式=广告。"""
    if last:
        item.campaign_id = str(last.get("campaign_id") or "")
        item.adset_id = str(last.get("adset_id") or "")
        item.ad_id = str(last.get("ad_id") or "")
        if last.get("page_post_id"):
            item.page_post_id = str(last["page_post_id"])
    item.progress = f"完成：成功 {ok}/{total} {unit}"   # 批BQ：终态进度行（失败明细在 error）
    if not fails:
        item.status = "success"; item.error = None; item.error_code = None
        if job:
            job.succeeded = (job.succeeded or 0) + 1
            if is_retry and (job.failed or 0) > 0:
                job.failed -= 1  # 重试成功：撤销原 fail 计数（与单模板 _retry_one 口径一致）
        return
    item.status = "fail"; item.error_code = "partial"
    shown = "；".join(fails[:3]) + ("…" if len(fails) > 3 else "")
    item.error = f"成功 {ok}/{total} {unit}：{shown}"[:300]
    if job and not is_retry:
        job.failed = (job.failed or 0) + 1  # 重试仍失败：原 fail 已计过，不重复加


def _deploy_series_fb(sdb, fb, item: LaunchJobItem, tpl: LaunchTemplate, asset, tenant_id: int,
                      link, targeting, advanced, post_content: dict, series_name: str = "") -> dict:
    """单系列 FB 部署（原 _run_deploy_job/_retry_one 的素材相关内联块抽成公共函数，行为不变）：
    per-asset 缓存（image_hash/video_id 按账户隔离）→ 预算 → Instant Form 解析 → AI 消息兜底 →
    随机文案 → 主页帖 → deploy_one_account 三件套。批量模式逐素材调用（series_name=素材名
    覆盖系列名），单模板模式 series_name 空 = 沿用 tpl.name_prefix。成功返 r dict；失败外抛
    （调用方消化为 item/系列级失败）。"""
    # per-account 素材缓存（FB image_hash / video_id 都按账户隔离）
    image_hash = ""
    video_id = ""
    video_thumb_hash = ""
    if asset and asset.type in ("image", "video"):
        filepath = os.path.join(ASSET_DIR, asset.storage_key)
        if not os.path.exists(filepath):
            raise FbApiError("no_id", f"素材文件丢失: {asset.storage_key}")
        _item_note(sdb, item, f"素材上传/缓存：{(asset.name or asset.filename or '')[:40]}")   # 批BQ：视频上传是长步骤
        if asset.type == "image":
            image_hash = ensure_image_hash_for_account(fb, sdb, asset, item.act_id, filepath)
        else:
            video_id = ensure_video_id_for_account(fb, sdb, asset, item.act_id, filepath)
            video_thumb_hash = ensure_video_thumb_hash(fb, sdb, asset, item.act_id, filepath)
        sdb.commit()  # 持久化 hash/video_id 缓存
    page_id = item.page_id or tpl.page_id
    # 批BR：统一走「优先账户自有像素」链（同树模式）；批BU：按 item 记忆——多素材多系列
    # 只在第一条核对（第一系列定了正确像素，后续直接复用，不逐条重复提示）
    _px_key = (item.pixel_id or tpl.pixel_id or "").strip()
    _px_cache = getattr(item, "_px_cache", None) or {}
    if _px_key in _px_cache:
        pixel_id, _px_note = _px_cache[_px_key], ""
    else:
        pixel_id, _px_note = _pick_group_pixel(
            sdb, tenant_id, item.act_id, _px_key, int(tpl.landing_page_id or 0), fb)
        _px_cache[_px_key] = pixel_id
        item._px_cache = _px_cache   # ORM 非列属性，仅本 item 生命周期内缓存
    if not pixel_id:
        raise FbApiError("no_id", "该账户无可用像素（BM 未分配且自动创建失败）——请先在 BM 给账户分配像素")
    if _px_note:
        _item_note(sdb, item, f"像素核对：{_px_note[:70]}")
    if (tpl.landing_page_id or 0) and pixel_id:
        # 批Z：回写页（页没配这个像素就补上）——否则 worker 不 fire，FB 零转化
        _bind_pixel_to_landing_page(sdb, tenant_id, int(tpl.landing_page_id), pixel_id, item.act_id)
    # lifetime 模式不解析日预算（无 budget_usd 也能部署；总预算在下方换算）
    daily_budget_fb = (0 if (tpl.budget_type or "daily") == "lifetime"
                       else _resolve_budget_fb(sdb, item.act_id, tpl, tenant_id))
    # 解析 Instant Form ID：表单模板 > 已建 form_id > AI 自动生成（LEADS 目标）
    lead_form_id = ""
    if tpl.objective == "OUTCOME_LEADS" and page_id:
        try:
            lead_form_id = _resolve_lead_form(fb, sdb, tpl, asset, page_id,
                                              _stable_landing_url(tpl.landing_url or "", tpl.name or ""),
                                              post_content=post_content)
        except Exception:
            pass  # 表单解析/创建失败不阻断主流程（FB 会用默认表单或报错）
    # 没选消息模板 → AI 从素材文案生成欢迎语（ENGAGEMENT+消息目标）；跟帖无素材→用帖内容
    message_template = tpl.message_template or ""
    if not message_template and tpl.objective == "OUTCOME_ENGAGEMENT":
        _msg_body = ""
        if asset:
            try:
                ai_copy = json.loads(asset.ai_copy_json or "{}") if asset.ai_copy_json else {}
                _msg_body = (ai_copy.get("bodies") or [""])[0]
            except Exception:
                pass
        elif post_content.get("message"):
            _msg_body = post_content["message"]  # 跟帖：用帖子文案当欢迎语
        if _msg_body:
            message_template = json.dumps({"text": _msg_body[:500], "ice_breakers": []})
    # 文案优先级：单模板模式（series_name 空）维持「模板手填 > 素材 AI」（批次II 修审计 A3）
    # ——编辑器表单显示什么就发什么；批量模式（series_name=素材名，逐素材克隆系列）反过来
    # 「素材 AI > 模板文案兜底」——多素材必须各用各的文案，模板文案只兜住没生成过 AI 文案的素材
    from ..core.ad_ops import pick_ad_copy
    if series_name:
        _headline, _body = pick_ad_copy(asset, "", "", tpl.headline or "", tpl.body or "")
    else:
        _headline, _body = pick_ad_copy(asset, tpl.headline or "", tpl.body or "")
    page_post_id = _resolve_page_post(sdb, fb, tenant_id, tpl, asset, page_id, body=_body)
    if page_post_id:
        sdb.commit()  # 持久化 page_posts 缓存
    # 追踪参数插值：逐系列/逐账户解出真实 URL（{{campaign.name}}=系列名，批量模式=素材名）
    _sn = series_name or tpl.name_prefix
    _acc = sdb.query(Account).filter(Account.tenant_id == tenant_id,   # 全库审查 P2
                                                        Account.act_id == item.act_id).first()
    _lp_url = _interp_landing_url(
        tpl.landing_url, campaign_name=_sn,
        account_name=(_acc.name if _acc else ""), account_id=item.act_id,
        asset_name=((asset.name or asset.filename or "") if asset else ""),
        template_name=tpl.name, platform="fb")
    # 批G 新字段：总预算/出价额按账户本币换算（排期/投放方式/ROAS/类别/描述直传）
    _btype = (tpl.budget_type or "daily").lower()
    _lifetime_fb = (_usd_to_account_minor(sdb, item.act_id, float(tpl.lifetime_budget_usd), tenant_id)
                    if _btype == "lifetime" and tpl.lifetime_budget_usd else None)
    _bid_fb = (_usd_to_account_minor(sdb, item.act_id, float(tpl.bid_amount_usd), tenant_id)
               if tpl.bid_amount_usd else None)
    # 系列支出上限（0091）：USD → 该账户本币 minor units（缺汇率抛 ValueError=系列级失败，
    # 不能静默丢上限——那是资金安全字段）
    _spend_cap_fb = (_usd_to_account_minor(sdb, item.act_id, float(tpl.spend_cap_usd), tenant_id)
                     if tpl.spend_cap_usd else None)
    try:
        _cats = json.loads(tpl.special_ad_categories or "[]")
    except Exception:
        _cats = []
    # 自动建链（批次I，每广告一子码——平铺/批量口径同树）：绑了落地页且未手选子码 → 本系列
    # 自动建 reserved 子码，base 用落地页行解析；失败降级直投 + warn（不静默）。
    # 落地 URL 跟随（批次II 修 B9/B5）：绑了落地页的模板一律用页行实时 base（含手选子码/
    # 自动建链失败降级场景），不再信编辑时 landing_url 快照
    _a_slug, _a_link, _a_base, _a_warn = _flat_auto_subcode(sdb, tpl, item, asset)
    if not _a_base and (tpl.landing_page_id or 0):
        try:
            _hb, _hp, _herr = _healthy_landing_base(sdb, tpl.tenant_id, int(tpl.landing_page_id))
            if _herr:
                raise _LandingBlockedError(_herr)
            _a_base = _hb or ""
        except _LandingBlockedError:
            raise
        except Exception:
            _a_base = ""
    if _a_base:
        _lp_url = _a_base
    r = deploy_one_account(
        fb, act_id=item.act_id, objective=tpl.objective, conversion_goal=tpl.conversion_goal,
        page_id=page_id, pixel_id=pixel_id, landing_url=_lp_url,
        daily_budget=daily_budget_fb, budget_mode=tpl.budget_mode, bid_strategy=tpl.bid_strategy,
        name_prefix=series_name or tpl.name_prefix, headline=_headline, body=_body, cta_type=tpl.cta_type,
        image_hash=image_hash, video_id=video_id, video_thumb_hash=video_thumb_hash,
        subcode_slug=(_a_slug or tpl.subcode_slug), subcode_link=(_a_link if _a_slug else link),
        targeting=targeting, ad_language=tpl.ad_language,
        dsa_beneficiary=tpl.beneficiary or "", dsa_payor=tpl.payer or "",
        optimization_goal=tpl.optimization_goal or "", billing_event=tpl.billing_event or "",
        destination_type_override=tpl.destination_type or "",
        page_post_id=page_post_id,
        advanced_config=advanced,
        lead_form_id=lead_form_id, message_template=message_template,
        budget_type=_btype, lifetime_budget=_lifetime_fb,
        start_time=(tpl.schedule_start or ""), end_time=(tpl.schedule_end or ""),
        pacing=(tpl.pacing or ""), bid_amount=_bid_fb,
        minimum_roas=(tpl.minimum_roas if tpl.minimum_roas else None),
        special_ad_categories=_cats, description=(tpl.link_description or ""),
        spend_cap=_spend_cap_fb, instagram_actor_id=(tpl.instagram_actor_id or ""),
        whatsapp_phone_number=(tpl.whatsapp_phone_number or ""),
    )
    if _a_warn:
        r["auto_subcode_warn"] = _a_warn   # 调用方在 item 上留痕（success 也会带 error）
    if r.get("pixel_swapped"):
        # 平铺/批量像素自愈留痕（批AZ 统一）：模板像素令牌无权 → 已换账户可用像素；
        # 落地页同步回写新像素（worker fire 页自身像素，只换 adset=FB 零转化）
        _px_w = f"[像素] 所配像素（模板/落地页）当前令牌无权使用，已自动换为账户可用像素 {r['pixel_swapped']}"
        r["auto_subcode_warn"] = (f"{r['auto_subcode_warn']}；{_px_w}"
                                  if r.get("auto_subcode_warn") else _px_w)
        if (tpl.landing_page_id or 0):
            try:
                _bind_pixel_to_landing_page(sdb, tenant_id, int(tpl.landing_page_id),
                                            r["pixel_swapped"], item.act_id)
            except Exception:
                pass
    return r


def _deploy_item_fb_batch(sdb, job, item: LaunchJobItem, tpl: LaunchTemplate, assets: list,
                          tenant_id: int, link, targeting, advanced, post_content: dict, fb,
                          is_retry: bool = False) -> None:
    """批量模式 FB：item(=账户) 内逐素材克隆系列（模板=母版，系列名=素材名）。
    单系列失败不中断后续（收集失败清单，_apply_batch_result 汇总 partial）。
    每系列 touch job 心跳——200 素材×视频上传远超 reap 的 10min 无心跳窗口，
    不 touch 会被判孤儿标 failed → 用户重试 = 已建系列再建一份（双份预算）。"""
    from sqlalchemy import text as _t
    ok, fails, last = 0, [], None
    for i, a in enumerate(assets):
        name = _series_name(tpl, a, i)
        # 心跳+进度注记（批BQ）：视频上传可能>10min，不提交的话 reap 在别的事务里看不到未提交心跳
        _item_note(sdb, item, f"系列 {i+1}/{len(assets)}：{(name or '')[:40]}")
        try:
            r = _deploy_series_fb(sdb, fb, item, tpl, a, tenant_id, link,
                                  targeting, advanced, post_content, series_name=name)
            ok += 1; last = r
            write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                      target_type="ad", target_id=str(r.get("ad_id", "")),
                      action_type="deploy", source="launch", result="success",
                      metadata={"act_id": item.act_id, "campaign_id": r.get("campaign_id"),
                                "template_id": tpl.id, "series_name": name})
        except FbApiError as e:
            fails.append(f"{name}: {(e.friendly or str(e))[:120]}")
            write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                      target_type="ad", target_id="", action_type="deploy", source="launch",
                      result="fail", friendly_error=(e.friendly or str(e))[:200],
                      metadata={"act_id": item.act_id, "template_id": tpl.id, "series_name": name})
        except Exception as e:
            fails.append(f"{name}: {str(e)[:120]}")
            write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                      target_type="ad", target_id="", action_type="deploy", source="launch",
                      result="fail", friendly_error=str(e)[:200],
                      metadata={"act_id": item.act_id, "template_id": tpl.id, "series_name": name})
    _apply_batch_result(job, item, len(assets), ok, fails, last, is_retry=is_retry)


def _tree_expanded_count(adsets: list) -> int:
    """树展开后广告总数（每账户）：素材组节点按 len(asset_ids) 计，无素材节点按 1 计。"""
    return sum(max(len(a.get("asset_ids") or []), 1) for s in adsets for a in (s.get("ads") or []))


def _deploy_item_fb_tree(sdb, job, item: LaunchJobItem, tpl: LaunchTemplate, adsets: list,
                         tenant_id: int, fb, is_retry: bool = False) -> None:
    """结构模式 FB 部署（0088）：1 系列 → N 广告组 → M 广告（素材组节点逐素材展开为多个广告）。

    粒度与失败语义（对齐批量模式 partial）：系列建失败 = 整 item 失败（外抛）；组级失败
    （预算/受众/参数被 FB 拒）= 该组全部广告记失败后继续下一组；单广告失败不中断。
    预算：节点存 USD，逐账户经 _resolve_budget_fb 按目标账户 currency + 当日汇率换算本币
    （与平铺链完全同一管道——多货币账户自动转换）。
    激活语义（用户决策 2026-09-08）：campaign 恒 ACTIVE；组开关 → adset ACTIVE/PAUSED；
    广告开关且所属组开 → ad ACTIVE/PAUSED；整链开启才消耗。
    心跳：每广告 touch job（素材上传/建广告序列长，防 reap 误判孤儿）。"""
    from types import SimpleNamespace

    def _view(**ov):
        """节点视图：拷贝模板全部列 + 节点覆盖——_resolve_* 系 helper 只读属性，
        SimpleNamespace 保证兼容（不用改名函数签名，平铺链零改动）。"""
        d = {c.name: getattr(tpl, c.name) for c in tpl.__table__.columns}
        d.update(ov)
        return SimpleNamespace(**d)

    # 批BO：系列名唯一化——日期(MMDD)+时刻(HHMM)+4 位随机（同模板一天多次部署/重试/多账户
    # 都不重名；FB 系列名仅账户内需唯一，但这套后缀跨场景也唯一，追溯部署来源更方便）
    import secrets as _sec
    from datetime import datetime as _dtn
    _suffix = _dtn.now().strftime("%m%d-%H%M") + "-" + _sec.token_hex(2)
    campaign_name = f"{tpl.name_prefix or tpl.name or 'Tova Ads'} {_suffix}"[:100]
    is_cbo = (tpl.budget_mode or "ABO").upper() == "CBO"
    _cats = []
    try:
        _cats = json.loads(tpl.special_ad_categories or "[]")
    except Exception:
        pass
    # 系列预算：CBO lifetime 用总预算（换算本币），否则日预算管道
    _tpl_btype = (tpl.budget_type or "daily").lower()
    if is_cbo and _tpl_btype == "lifetime":
        if not tpl.lifetime_budget_usd:
            raise FbApiError("no_id", "CBO 总预算模式未填总预算金额")
        _camp_lifetime_fb = _usd_to_account_minor(sdb, item.act_id, float(tpl.lifetime_budget_usd), tenant_id)
        camp_budget_fb = _camp_lifetime_fb
    else:
        _camp_lifetime_fb = None
        camp_budget_fb = _resolve_budget_fb(sdb, item.act_id, tpl, tenant_id)
    # 系列支出上限（0091）：USD → 该账户本币 minor units。缺汇率=整 item 失败
    # （静默丢上限继续建 = 资金安全字段半接线，不允许）。
    _spend_cap_fb = None
    if tpl.spend_cap_usd:
        try:
            _spend_cap_fb = _usd_to_account_minor(sdb, item.act_id, float(tpl.spend_cap_usd), tenant_id)
        except ValueError as e:
            raise FbApiError("no_id", f"支出上限换算失败：{e}")
    _item_note(sdb, item, "创建系列…")   # 批BQ：分步进度可见
    camp_payload = build_campaign(
        name=campaign_name, objective=tpl.objective,
        daily_budget=(camp_budget_fb if (is_cbo and not _camp_lifetime_fb) else None),
        lifetime_budget=_camp_lifetime_fb,
        budget_mode=tpl.budget_mode, bid_strategy=tpl.bid_strategy,
        special_ad_categories=_cats, spend_cap=_spend_cap_fb)
    camp = fb.post(f"act_{item.act_id}/campaigns", camp_payload)
    campaign_id = camp.get("id")
    if not campaign_id:
        raise FbApiError("no_id", f"FB 创建 campaign 未返回 id（响应：{str(camp)[:200]}）")

    ok, fails, last = 0, [], None
    _acc = sdb.query(Account).filter(
        Account.tenant_id == tenant_id, Account.act_id == item.act_id).first()
    _acc_name = (_acc.name if _acc else "") or ""
    _tpl_adv = _parse_advanced(tpl) or {}
    _subcode_cache: dict = {}
    _lp_base_cache: dict = {}      # landing_page_id → 公网 base（自动建链用，页行解析）
    _lp_probe_cache: dict = {}     # url → FB 封禁探测结果（批S；同 item 内去重 FB Graph 调用）
    _auto_slugs: list[str] = []    # 本 item 自动建的子码（落 item.subcode_slug + 成功日志）
    auto_warns: list[str] = []     # 自动建链失败降级记录（不静默）
    _page_id = item.page_id or tpl.page_id or ""
    # 主页自动识别（批O-2）：抽屉/模板都没指定且非跟帖 → 该账户可用主页里选第一个有广告权限的
    # （me/accounts tasks 含 ADVERTISE；拉不到不阻断——空主页会在下游原错误路径暴露）
    if not _page_id and (tpl.post_source or "new") != "reuse":
        try:
            _pgs = fb.get_pages()
            _adv_pgs = [p for p in _pgs if "ADVERTISE" in (p.get("tasks") or [])] or _pgs
            if _adv_pgs:
                _page_id = str(_adv_pgs[0].get("id") or "")
        except Exception:
            pass

    def _fail_group(sname: str, snode: dict, msg: str):
        nonlocal fails
        for ai, anode in enumerate(snode.get("ads") or [], 1):
            aname = anode.get("name") or f"广告{ai}"
            for k in range(max(len(anode.get("asset_ids") or []), 1)):
                fails.append(f"{sname}/{aname}: {msg[:110]}")

    _ads_total = _tree_expanded_count(adsets)
    _ad_no = 0
    _px_memo: dict = {}   # 批BU：像素核对按 item 记忆——同账户第一组定了正确像素，后续组直接复用
    _px_noted = False      # 「已自动换」提示只弹一次（组组重复弹=用户实测噪音）
    for si, snode in enumerate(adsets, 1):
        sname = ((snode.get("name") or f"{campaign_name} 组{si}"))[:100]
        _item_note(sdb, item, f"组 {si}/{len(adsets)}：{sname[:36]}")   # 批BQ
        s_enabled = bool(snode.get("enabled"))
        # 组预算（ABO）：节点 USD 覆盖 > 模板默认；节点/模板可选 lifetime（总预算须排期，
        # 保存端已校验节点级；模板级 lifetime 在 _budget_guard_400 已拦无排期）。
        # CBO 组不带预算（系列级）。排期/投放方式/出价额/ROAS 节点覆盖 > 模板默认。
        node_btype = (snode.get("budget_type") or tpl.budget_type or "daily").lower()
        node_lt_usd = snode.get("lifetime_budget_usd") or tpl.lifetime_budget_usd
        adset_lifetime_fb = None
        try:
            if is_cbo:
                adset_budget_fb = camp_budget_fb
            elif node_btype == "lifetime":
                if not node_lt_usd:
                    _fail_group(sname, snode, "总预算模式未填总预算金额")
                    continue
                adset_lifetime_fb = _usd_to_account_minor(sdb, item.act_id, float(node_lt_usd), tenant_id)
                adset_budget_fb = 0
            else:
                node_b = snode.get("budget_usd")
                adset_budget_fb = _resolve_budget_fb(
                    sdb, item.act_id,
                    _view(budget_usd=float(node_b) if node_b else tpl.budget_usd,
                          daily_budget=tpl.daily_budget if not node_b else 0),
                    tenant_id)
        except ValueError as e:
            _fail_group(sname, snode, f"预算换算失败：{e}")
            continue
        s_sched_start = snode.get("schedule_start") or tpl.schedule_start or ""
        s_sched_end = snode.get("schedule_end") or tpl.schedule_end or ""
        s_pacing = snode.get("pacing") or tpl.pacing or ""
        _bid_usd = snode.get("bid_amount_usd")
        if _bid_usd in (None, ""):
            _bid_usd = tpl.bid_amount_usd
        try:
            s_bid_fb = (_usd_to_account_minor(sdb, item.act_id, float(_bid_usd), tenant_id)
                        if _bid_usd else None)
        except ValueError as e:
            _fail_group(sname, snode, f"出价额换算失败：{e}")
            continue
        s_min_roas = snode.get("minimum_roas")
        if s_min_roas in (None, ""):
            s_min_roas = tpl.minimum_roas
        try:
            targeting = _resolve_targeting(
                sdb, snode.get("audience_id") or tpl.audience_id,
                (snode.get("audience_json") or tpl.audience_json or ""),
                sdb_tenant_id=tenant_id)
        except Exception as e:
            _fail_group(sname, snode, f"受众解析失败：{e}")
            continue
        adv_node = {}
        if snode.get("advanced_config"):
            try:
                adv_node = json.loads(snode["advanced_config"]) or {}
            except Exception:
                adv_node = {}
        merged_adv = _strip_adv_bid({**_tpl_adv, **adv_node}, s_bid_fb)
        # 组级转化位置/成效目标派生（批次I 统一链）：is_messaging 门、消息分流、CTA app_destination
        # 都以此为准；destination_type_override 传模板残留值——builder 在 conv_location 非空时
        # 忽略它（修隐患A：覆盖派生 MESSENGER 后被 ON_PAGE 顶掉）
        s_conv_loc = (snode.get("conv_location") or "").strip().lower()
        s_opt_goal = (snode.get("optimization_goal") or tpl.optimization_goal or "")
        try:
            grp_dest, grp_opt = resolve_adset_destination(tpl.objective, s_conv_loc,
                                                          tpl.conversion_goal, s_opt_goal)
        except ValueError as e:
            _fail_group(sname, snode, f"转化位置解析失败：{e}")
            continue
        grp_is_msg = is_messaging_destination(grp_dest, grp_opt)
        # 批P1 修2：advantage_audience 三态——节点显式设置用节点的；未设（存量模板）按平铺链
        # 同款启发式兜底：受众含兴趣词(flexible_spec)=原始受众(关)，纯宽定向=Advantage+(开)。
        # 旧行为 is not False 把未设当开 → 兴趣受众+Advantage+ 开 → FB 1870227 拒收整个 adset
        _adv_aud = snode.get("advantage_audience")
        if _adv_aud is None:
            _adv_aud = not bool((targeting or {}).get("flexible_spec"))
        # 组像素链（批BR 终版，用户拍板「优先账户自己能关联到的」）：显式指定且有权 → 尊重；
        # 否则账户已绑像素随机（号商账户永不错——…142 实证页像素创建成功但投放被拦的静默雷
        # 从源头消除）；无权自动换+留痕；选定即回写页 fire（追加不顶，主像素继续收全量事件）。
        _first_ad = (snode.get("ads") or [{}])[0]
        _grp_lpid = int(_first_ad.get("landing_page_id") or 0)
        _px_key = str(snode.get("pixel_id") or "") or item.pixel_id or tpl.pixel_id or ""
        if _px_key in _px_memo:
            _grp_pixel = _px_memo[_px_key]   # 批BU：已核对过直接复用（不重复查库/不重复提示）
            _px_note = ""
        else:
            _grp_pixel, _px_note = _pick_group_pixel(sdb, tenant_id, item.act_id, _px_key, _grp_lpid, fb)
            _px_memo[_px_key] = _grp_pixel
        if not _grp_pixel:
            _fail_group(sname, snode, "该账户无可用像素（BM 未分配且自动创建失败）——请先在 BM 给账户分配像素")
            continue
        if _px_note and not _px_noted:
            auto_warns.append(f"[像素] {_px_note}（本账户全部组已复用）")
            _item_note(sdb, item, f"像素核对：{_px_note[:70]}")
            _px_noted = True
        if _grp_lpid and _grp_pixel:
            # 批Z：回写页（页没配这个像素就补上）——否则 worker 不 fire，FB 零转化
            _bind_pixel_to_landing_page(sdb, tenant_id, _grp_lpid, _grp_pixel, item.act_id)
        try:
            adset_payload = build_adset(
                name=sname, campaign_id=campaign_id, daily_budget=adset_budget_fb,
                objective=tpl.objective, conversion_goal=tpl.conversion_goal,
                page_id=_page_id,
                pixel_id=_grp_pixel,
                landing_url=_stable_landing_url(_first_ad.get("landing_url") or tpl.landing_url or "",
                                                tpl.name or "", "fb"),
                bid_strategy=tpl.bid_strategy, budget_mode=tpl.budget_mode,
                targeting=targeting, dsa_beneficiary=tpl.beneficiary or "", dsa_payor=tpl.payer or "",
                optimization_goal=s_opt_goal,
                billing_event=(snode.get("billing_event") or tpl.billing_event or ""),
                destination_type_override=tpl.destination_type or "",
                extra=merged_adv or None,
                budget_type=node_btype, lifetime_budget=adset_lifetime_fb,
                start_time=s_sched_start, end_time=s_sched_end, pacing=s_pacing,
                advantage_audience=_adv_aud,
                bid_amount=s_bid_fb,
                minimum_roas=(float(s_min_roas) if s_min_roas else None),
                conv_location=s_conv_loc,
                placements=_node_placements(snode),
                whatsapp_phone_number=(tpl.whatsapp_phone_number or ""))
        except ValueError as e:
            _fail_group(sname, snode, f"参数校验失败：{e}")
            continue
        adset_payload["status"] = "ACTIVE" if s_enabled else "PAUSED"
        try:
            adset = _post_adset_with_fallback(fb, item.act_id, adset_payload)
            if adset.get("_advantage_forced"):
                # 受众被强制 Advantage+：窄定向（年龄/性别/兴趣）被剥为纯 geo+AI 扩展——留痕不静默
                auto_warns.append(f"[受众] {sname}: 受众被强制 Advantage+（App 未过审无经典定向权限），"
                                  f"已按国家+AI 扩展投放")
            _sw_px = adset.get("_pixel_swapped")
            if _sw_px:
                # 像素自愈留痕（批AZ）：模板像素令牌无权 → 已换账户可用像素；落地页必须同步
                # 回写新像素（worker fire 页自身的 pixel_ids——只换 adset 页还发旧像素=FB 零转化）
                auto_warns.append(f"[像素] {sname}: 所配像素（模板/落地页）当前令牌无权使用(1487429)，"
                                  f"已自动换为账户可用像素 {_sw_px}")
                _grp_pixel = _sw_px
                if _grp_lpid:
                    _bind_pixel_to_landing_page(sdb, tenant_id, _grp_lpid, _sw_px, item.act_id)
        except FbApiError as e:
            _fail_group(sname, snode, (e.friendly or str(e)))
            continue
        adset_id = adset.get("id")
        if not adset_id:
            _fail_group(sname, snode, f"FB 创建 adset 未返回 id（{str(adset)[:120]}）")
            continue

        for ai, anode in enumerate(snode.get("ads") or [], 1):
            a_enabled = bool(anode.get("enabled")) and s_enabled   # 整链开启才消耗
            node_post = "reuse" if anode.get("post_source") == "reuse" else "new"
            # 素材清单：素材组节点逐素材展开（无素材=跟帖/AI 兜底场景单广告）
            assets = [None]
            if anode.get("asset_ids"):
                assets = [sdb.query(Asset).filter(
                    Asset.id == int(a), Asset.tenant_id == tenant_id).first()
                    for a in anode["asset_ids"]]
            post_content = {}
            if node_post == "reuse" and anode.get("reuse_post_ref"):
                try:
                    from ..routers.fb import _fetch_post_content
                    post_content = _fetch_post_content(sdb, tenant_id, anode["reuse_post_ref"]) or {}
                except Exception:
                    post_content = {}
            # 节点级子码链接（缓存复用；status 过滤 reserved/active——archived/deleted 的 slug
            # 不再被解析使用（批次I 修 B4，口径=平铺预检）；无效 slug 预检已拦）
            node_slug = anode.get("subcode_slug") or ""
            node_link = None
            if node_slug:
                if node_slug not in _subcode_cache:
                    _subcode_cache[node_slug] = sdb.query(LandingAdLink).filter(
                        LandingAdLink.slug == node_slug,
                        LandingAdLink.tenant_id == tenant_id,
                        LandingAdLink.status.in_(["reserved", "active"])).first()
                node_link = _subcode_cache[node_slug]
            # 落地 URL 跟随（批次II 修 B9/B5）：绑了落地页的节点一律从落地页行实时解析 base
            # （custom_domain/bound_subdomains/pages.dev 兜底），不再用编辑时的 landing_url 快照——
            # 页换域名/加子域后快照变死链。自动建链（未手选 slug）同一数据源。
            node_lpid = int(anode.get("landing_page_id") or 0)
            node_lp_base = ""
            if node_lpid:
                if node_lpid not in _lp_base_cache:
                    # 批S 域名健康门：全封 → 缓存哨兵 "__BLOCKED__"，下方整 item 失败拒投
                    _hb, _hp, _herr = _healthy_landing_base(sdb, tenant_id, node_lpid, _lp_probe_cache)
                    _lp_base_cache[node_lpid] = "__BLOCKED__" if _herr else (_hb or "")
                if _lp_base_cache[node_lpid] == "__BLOCKED__":
                    raise _LandingBlockedError(
                        f"落地页(#{node_lpid})所有绑定域名均被 FB 屏蔽，已阻止部署——请换绑健康域名")
                node_lp_base = _lp_base_cache[node_lpid]
            aname_base = (anode.get("name") or "").strip()

            for asset in assets:
                _ad_no += 1
                # 广告名：节点名 > 素材名（素材组展开的每个广告用素材名，对齐批量生成命名）
                if aname_base:
                    ad_name = aname_base
                else:
                    ad_name = ((asset.name or asset.filename or "") if asset else "") or f"{sname} 广告{ai}"
                ad_name = ad_name[:100]
                # 心跳+进度注记（批BQ，原裸 job touch）：素材上传耗时 > reap 窗口，commit 后轮询立即可见
                _item_note(sdb, item, f"广告 {_ad_no}/{_ads_total}：{ad_name[:36]}")
                try:
                    if asset is None and not (node_post == "reuse" and anode.get("reuse_post_ref")):
                        raise FbApiError("no_id", "广告节点未选素材或素材已被删除（跟帖模式可无素材）")
                    if asset is not None and (asset.type or "image") not in ("image", "video"):
                        raise FbApiError("no_id", f"素材「{asset.name or asset.id}」不是图片/视频")
                    # 素材上传缓存（FB image_hash / video_id 按账户隔离）
                    image_hash, video_id, video_thumb_hash = "", "", ""
                    if asset is not None:
                        filepath = os.path.join(ASSET_DIR, asset.storage_key)
                        if not os.path.exists(filepath):
                            raise FbApiError("no_id", f"素材文件丢失: {asset.storage_key}")
                        if asset.type == "image":
                            image_hash = ensure_image_hash_for_account(fb, sdb, asset, item.act_id, filepath)
                        else:
                            video_id = ensure_video_id_for_account(fb, sdb, asset, item.act_id, filepath)
                            video_thumb_hash = ensure_video_thumb_hash(fb, sdb, asset, item.act_id, filepath)
                        sdb.commit()
                    # 节点视图（表单/消息/跟帖/落地按节点覆盖，空 = 回退模板级）
                    vtpl = _view(
                        lead_form_template_id=(int(anode.get("lead_form_template_id") or 0)
                                               or (tpl.lead_form_template_id or 0)),
                        lead_form_id=(tpl.lead_form_id or ""),
                        landing_url=(anode.get("landing_url") or tpl.landing_url or ""),
                        post_source=node_post,
                        reuse_post_ref=(anode.get("reuse_post_ref") or ""),
                        message_template=(tpl.message_template or ""),
                    )
                    # Instant Form（LEADS）：节点表单模板 > 模板级 > AI 自动生成
                    # 批O-2：广告身份用节点级主页（无=基础链：抽屉/模板/账户自动识别）
                    _ad_page = str(anode.get("page_id") or "") or _page_id
                    lead_form_id = ""
                    if tpl.objective == "OUTCOME_LEADS" and _ad_page:
                        try:
                            lead_form_id = _resolve_lead_form(
                                fb, sdb, vtpl, asset, _ad_page,
                                _stable_landing_url(vtpl.landing_url or "", tpl.name or ""),
                                post_content=post_content)
                        except Exception:
                            pass  # 表单解析/创建失败不阻断主流程（FB 会用默认表单或报错）
                    # 消息模板：节点选的 MessageTemplate > 模板级 raw JSON > AI 从素材文案生成
                    message_template = ""
                    _mt_type = "messenger"   # MessageTemplate.type（批次I 消费位：whatsapp 分流）
                    _mt_id = int(anode.get("message_template_id") or 0)
                    if _mt_id:
                        from ..models.lead_form_template import MessageTemplate
                        mt = sdb.query(MessageTemplate).filter(
                            MessageTemplate.id == _mt_id,
                            MessageTemplate.tenant_id == tenant_id).first()
                        if mt:
                            _mt_type = (mt.type or "messenger")
                            try:
                                _ibs = json.loads(mt.ice_breakers_json or "[]")
                            except Exception:
                                _ibs = []
                            message_template = json.dumps(
                                {"text": mt.welcome_text or "", "ice_breakers": _ibs},
                                ensure_ascii=False)
                    if not message_template:
                        message_template = (tpl.message_template or "")
                    if not message_template and tpl.objective == "OUTCOME_ENGAGEMENT":
                        _msg_body = ""
                        if asset is not None:
                            try:
                                ai_copy = json.loads(asset.ai_copy_json or "{}") if asset.ai_copy_json else {}
                                _msg_body = (ai_copy.get("bodies") or [""])[0]
                            except Exception:
                                pass
                        elif post_content.get("message"):
                            _msg_body = post_content["message"]
                        if _msg_body:
                            message_template = json.dumps({"text": _msg_body[:500], "ice_breakers": []})
                    # 文案优先级（批次II 修审计 A3 基础上按素材数分流）：单素材节点=节点手填 >
                    # 素材 AI > 模板兜底（节点表单显示什么就发什么）；素材组节点（多素材展开
                    # 多广告）=素材 AI > 节点/模板文案兜底——多素材必须各用各的文案，一份节点
                    # 文案盖住 N 个素材正是多素材文案混用的树侧根源
                    from ..core.ad_ops import pick_ad_copy
                    if len(assets) > 1:
                        _headline, _body = pick_ad_copy(
                            asset, "", "",
                            (anode.get("headline") or tpl.headline or ""),
                            (anode.get("body") or tpl.body or ""))
                    else:
                        _headline, _body = pick_ad_copy(
                            asset, anode.get("headline") or "", anode.get("body") or "",
                            tpl.headline or "", tpl.body or "")
                    # 主页帖（new=每素材建 / reuse=节点引用帖）——_ad_page 已在表单解析前定义
                    page_post_id = _resolve_page_post(sdb, fb, tenant_id, vtpl, asset, _ad_page, body=_body)
                    if page_post_id:
                        sdb.commit()
                    # 落地 URL：节点占位符逐组/逐账户解值（组名真实传入）；绑了落地页的节点
                    # 用页行实时解析的 base 覆盖（快照仅作未绑页时的占位符容器）
                    _lp_url = _interp_landing_url(
                        vtpl.landing_url or "", campaign_name=campaign_name,
                        adset_name=sname, account_name=_acc_name, account_id=item.act_id,
                        asset_name=((asset.name or asset.filename or "") if asset is not None else ""),
                        template_name=tpl.name or "", platform="fb")
                    if node_lp_base:
                        _lp_url = node_lp_base
                    # 子码 effective_url（与 deploy_one_account 同构；base 同源=落地页行实时解析；
                    # 无可用 base 快失败，不再兜底 tovaads.com 死链——批次II 修 B5）
                    effective_url = _lp_url
                    auto_link, auto_slug = None, ""
                    if node_slug and node_link is not None:
                        if not _lp_url:
                            raise FbApiError("no_id", f"{ad_name}: 已选子码「{node_slug}」但缺少可用落地 URL"
                                                     "（节点未绑落地页且 URL 为空），请绑定落地页或填写落地 URL")
                        effective_url = f"{_lp_url}/a/{node_slug}?ad=" + "{{ad.id}}"
                    elif node_lp_base:
                        # 自动建链（每广告）：建 reserved LandingAdLink → URL 立即进 FB（先 commit，
                        # worker 必须能查到）；失败降级裸 URL 直投 + 记录（不静默——铁律）
                        try:
                            _sb = _auto_slug_base(tpl.id, anode.get("key") or "", asset, item.act_id)
                            auto_link = _create_auto_subcode(sdb, tenant_id, node_lpid, item.act_id, _sb)
                            auto_slug = auto_link.slug
                            sdb.commit()
                            effective_url = f"{node_lp_base}/a/{auto_slug}?ad=" + "{{ad.id}}"
                            _auto_slugs.append(auto_slug)
                        except Exception as e:
                            sdb.rollback()
                            auto_warns.append(f"{ad_name}: 自动建链失败降级直投（{str(e)[:80]}）")
                            write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(),
                                      actor_type="system", target_type="ad", target_id="",
                                      action_type="deploy", source="launch", result="fail",
                                      friendly_error=f"自动建链失败：{str(e)[:180]}",
                                      metadata={"act_id": item.act_id, "template_id": tpl.id,
                                                "landing_page_id": node_lpid, "stage": "auto_subcode"})
                    # 欢迎语 + 主页 messaging 能力检查（批次I 门统一：按派生目的地/成效目标判定——
                    # 旧门查 conversion_goal 词表 = UI 永远给不出 = 死链（盘点 A1）；
                    # MessageTemplate.type/conv_location 分流 Messenger（ice_breakers）与 WA（预填））
                    from ..core.ad_builder import parse_message_template
                    welcome_msg = None
                    if grp_is_msg and _ad_page:
                        if grp_dest == "MESSENGER":
                            try:
                                pf = fb.get(_ad_page, {"fields": "messaging_feature_status"})
                                mfs = (pf.get("messaging_feature_status") or {})
                                if (mfs.get("USER_MESSAGING") or "").upper() != "ENABLED":
                                    raise FbApiError("no_id", "主页未开启 messaging，无法投放私信广告")
                            except FbApiError:
                                raise
                            except Exception:
                                pass
                        _msg_channel = ("whatsapp" if (grp_dest == "WHATSAPP"
                                                       or _mt_type == "whatsapp") else "messenger")
                        welcome_msg = parse_message_template(message_template, allow_cjk=True,
                                                             channel=_msg_channel)
                    creative = build_creative(
                        page_id=_ad_page, objective=tpl.objective, conversion_goal=tpl.conversion_goal,
                        landing_url=effective_url, headline=_headline, body=_body,
                        cta_type=(anode.get("cta_type") or tpl.cta_type or ""),
                        image_hash=image_hash, video_id=video_id, video_thumb_hash=video_thumb_hash,
                        lead_form_id=lead_form_id, welcome_message=welcome_msg,
                        description=(anode.get("link_description") or tpl.link_description or ""),
                        instagram_actor_id=(tpl.instagram_actor_id or ""),
                        app_destination=(grp_dest if grp_is_msg else ""))
                    if page_post_id:
                        _cta_t = (anode.get("cta_type") or tpl.cta_type or "") or pick_cta(_body, tpl.objective)
                        _cta_val = ({"page": _ad_page} if _cta_t == "LIKE_PAGE"
                                    else {"link": effective_url or f"https://facebook.com/{_ad_page}"})
                        cr = fb.post(f"act_{item.act_id}/adcreatives", {
                            "name": f"{ad_name} creative", "object_story_id": page_post_id,
                            "call_to_action": json.dumps({"type": _cta_t, "value": _cta_val}),
                        })
                        creative_id = cr.get("id")
                        if not creative_id:
                            raise FbApiError("no_id", f"建 creative(object_story_id) 未返回 id：{str(cr)[:150]}")
                        ad = fb.post(f"act_{item.act_id}/ads", {
                            "name": ad_name, "adset_id": adset_id,
                            "status": "ACTIVE" if a_enabled else "PAUSED",
                            "creative": {"creative_id": creative_id}})
                    else:
                        ad = fb.post(f"act_{item.act_id}/ads", {
                            "name": ad_name, "adset_id": adset_id,
                            "status": "ACTIVE" if a_enabled else "PAUSED",
                            "creative": creative})
                    ad_id = ad.get("id")
                    if not ad_id:
                        raise FbApiError("no_id", f"FB 创建 ad 未返回 id（响应：{str(ad)[:150]}）")
                    # 子码标注广告名 + 回绑 ad_id（deploy_one_account 同构；手动选的与自动建的同一模式；
                    # last-wins 守卫（批次III）：已绑不同广告不覆盖，item 留痕）
                    if node_slug and node_link is not None:
                        try:
                            fb.post(ad_id, {"name": f"[子码:{node_slug}] {ad_name}"})
                        except Exception:
                            pass
                        if not bind_link_ad_id(node_link, ad_id):
                            write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                                      target_type="subcode", target_id=str(node_link.slug or node_slug),
                                      action_type="bind", source="launch", result="skip",
                                      friendly_error=f"子码已绑广告 {getattr(node_link, 'ad_id', '')}，跳过回绑 {ad_id}（last-wins 守卫）",
                                      metadata={"act_id": item.act_id, "ad_id": str(ad_id),
                                                "subcode_slug": node_slug, "tree": f"{sname}/{ad_name}"})
                    elif auto_link is not None:
                        try:
                            fb.post(ad_id, {"name": f"[子码:{auto_slug}] {ad_name}"})
                        except Exception:
                            pass
                        if not bind_link_ad_id(auto_link, ad_id):
                            write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                                      target_type="subcode", target_id=str(getattr(auto_link, "slug", "") or auto_slug),
                                      action_type="bind", source="launch", result="skip",
                                      friendly_error=f"子码已绑广告 {getattr(auto_link, 'ad_id', '')}，跳过回绑 {ad_id}（last-wins 守卫）",
                                      metadata={"act_id": item.act_id, "ad_id": str(ad_id),
                                                "subcode_slug": auto_slug, "tree": f"{sname}/{ad_name}"})
                    ok += 1
                    last = {"campaign_id": campaign_id, "adset_id": adset_id, "ad_id": ad_id,
                            "page_post_id": page_post_id}
                    write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                              target_type="ad", target_id=str(ad_id),
                              action_type="deploy", source="launch", result="success",
                              metadata={"act_id": item.act_id, "campaign_id": campaign_id,
                                        "adset_id": adset_id, "template_id": tpl.id,
                                        "subcode_slug": (auto_slug or node_slug or ""),
                                        "tree": f"{sname}/{ad_name}"})
                except FbApiError as e:
                    fails.append(f"{sname}/{ad_name}: {(e.friendly or str(e))[:110]}")
                    write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                              target_type="ad", target_id="", action_type="deploy", source="launch",
                              result="fail", friendly_error=(e.friendly or str(e))[:200],
                              metadata={"act_id": item.act_id, "template_id": tpl.id,
                                        "tree": f"{sname}/{ad_name}"})
                except Exception as e:
                    fails.append(f"{sname}/{ad_name}: {str(e)[:110]}")
                    write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                              target_type="ad", target_id="", action_type="deploy", source="launch",
                              result="fail", friendly_error=str(e)[:200],
                              metadata={"act_id": item.act_id, "template_id": tpl.id,
                                        "tree": f"{sname}/{ad_name}"})
    if _auto_slugs:
        item.subcode_slug = ",".join(_auto_slugs)[:250]   # 激活死列（B10）：本 item 自动建的子码清单
    _apply_batch_result(job, item, _tree_expanded_count(adsets), ok, fails, last,
                        is_retry=is_retry, unit="广告")
    if auto_warns and item.status == "success":
        # 降级不静默（铁律 bare-except-silent-failure）：广告照建（裸 URL 直投），item 留痕
        item.error = f"部署提示 {len(auto_warns)} 条：{'；'.join(w[:110] for w in auto_warns[:2])}"[:300]
        item.error_code = "auto_subcode_degraded"


def _deploy_item_tt_batch(sdb, job, item: LaunchJobItem, tpl: LaunchTemplate, assets: list,
                          tenant_id: int, link, is_retry: bool = False) -> None:
    """批量模式 TT：item 内逐素材克隆系列。_deploy_item_tt 当「单系列执行器」用——
    传 job=None 关掉它内部的 job 计数（每系列各加一次 succeeded/failed 会把计数翻倍），
    由 _apply_batch_result 统一汇总；系列名经 name_prefix_override 传入（=素材名）。"""
    from sqlalchemy import text as _t
    ok, fails, last = 0, [], None
    for i, a in enumerate(assets):
        name = _series_name(tpl, a, i)
        _item_note(sdb, item, f"系列 {i+1}/{len(assets)}：{(name or '')[:40]}")   # 心跳+进度（批BQ）
        try:
            _deploy_item_tt(sdb, None, item, tpl, a, tenant_id, link,
                            name_prefix_override=name)
            if item.status == "success" and item.campaign_id:
                ok += 1
                last = {"campaign_id": item.campaign_id, "adset_id": item.adset_id,
                        "ad_id": item.ad_id}
            else:
                fails.append(f"{name}: {item.error or '未知错误'}")
        except Exception as e:  # 双保险：_deploy_item_tt 理论上自消化不外抛
            fails.append(f"{name}: {str(e)[:120]}")
    _apply_batch_result(job, item, len(assets), ok, fails, last, is_retry=is_retry)


def _run_deploy_job(job_id: int, tenant_id: int, template_id: int):
    """后台逐账户建广告。独立 SuperSessionLocal（bypass RLS，显式 tenant_id 过滤，避开 BackgroundTask 无请求上下文的 SET LOCAL 坑）。"""
    sdb = SuperSessionLocal()
    try:
        job = sdb.query(LaunchJob).filter(LaunchJob.id == job_id, LaunchJob.tenant_id == tenant_id).first()
        if not job:
            return
        tpl = sdb.query(LaunchTemplate).filter(
            LaunchTemplate.id == template_id, LaunchTemplate.tenant_id == tenant_id).first()
        if not tpl:
            job.status = "failed"; job.finished_at = datetime.now(timezone.utc); sdb.commit(); return
        job.status = "running"; sdb.commit()
        asset = (sdb.query(Asset).filter(Asset.id == tpl.asset_id, Asset.tenant_id == tenant_id).first()
                 if tpl.asset_id else None)
        # 批量模式素材清单（deploy 端点存日志 metadata，这里回读；空 = 单模板旧行为）
        batch_assets = _job_batch_assets(sdb, job_id, tenant_id)
        targeting = _resolve_targeting(sdb, tpl.audience_id, tpl.audience_json or "", sdb_tenant_id=tenant_id)
        advanced = _parse_advanced(tpl)
        # 子码链接（一个 slug 共享多广告，{{ad.id}} 宏区分）
        link = None
        if tpl.subcode_slug:
            link = sdb.query(LandingAdLink).filter(
                LandingAdLink.slug == tpl.subcode_slug,
                LandingAdLink.tenant_id == tenant_id).first()
        items = sdb.query(LaunchJobItem).filter(LaunchJobItem.job_id == job_id).all()
        # 跟帖模式：预取帖子内容（表单/消息 AI 生成 + 标题/文案兜底用，无素材时以帖内容代）
        post_content = {}
        if (tpl.post_source or "new") == "reuse" and tpl.reuse_post_ref:
            try:
                from ..routers.fb import _fetch_post_content
                post_content = _fetch_post_content(sdb, tenant_id, tpl.reuse_post_ref) or {}
            except Exception:
                post_content = {}
        for item in items:
            try:
                # 心跳：每 item 开工时 touch job 创建时间——reap 按"无心跳超时"判孤儿，
                # 单 worker 崩溃重启时其他 worker 正在跑的长任务不会被误标 failed
                from sqlalchemy import text as _t
                sdb.execute(_t("UPDATE launch_jobs SET created_at = now() WHERE id = :jid"),
                            {"jid": job_id})
                item.status = "creating"; sdb.commit()
                # TikTok 分支（TK P3）：TT 三件套走 _deploy_item_tt（内部含纳管复查/错误消化）；
                # platform='fb'（含存量行 server_default）走的下方 FB 路径零改动。
                # 批量模式：item 内逐素材克隆系列（partial 汇总语义见 _apply_batch_result）
                if (tpl.platform or "fb") == "tt":
                    if batch_assets:
                        _deploy_item_tt_batch(sdb, job, item, tpl, batch_assets, tenant_id, link)
                    else:
                        _deploy_item_tt(sdb, job, item, tpl, asset, tenant_id, link)
                    sdb.commit()
                    continue
                # 纳管复查（部署请求后到本 item 执行间隙账户可能被移除——同 retry 守卫理由）
                from ..models.fb import Account as _Acc3
                _acc3 = sdb.query(_Acc3).filter(
                    _Acc3.tenant_id == tenant_id, _Acc3.act_id == item.act_id,
                    _Acc3.is_managed == True,  # noqa: E712
                ).first()
                if not _acc3:
                    raise FbApiError("no_id", "该账户已移除纳管，跳过（移除后建广告无止损覆盖）")
                # 跟帖(reuse)：选能管该帖主页的写令牌（多令牌场景扫候选池，不只 priority 最高）
                is_reuse = (tpl.post_source or "new") == "reuse" and bool(tpl.reuse_post_ref)
                _page_for_token = (item.page_id or tpl.page_id or "") if is_reuse else ""
                if is_reuse and _page_for_token:
                    fb = client_for_account_page(sdb, tenant_id, item.act_id, _page_for_token, "write")
                    if not fb:
                        raise FbApiError("no_id", f"act_{item.act_id} 无访问主页 {_page_for_token} 的写令牌（跟帖模式）")
                else:
                    _fb_list, _ = _write_fb_with_fallback(sdb, tenant_id, item.act_id)
                    if not _fb_list:
                        raise FbApiError("no_id", f"act_{item.act_id} 未绑定写令牌")
                    fb = _fb_list[0]
                # 批量模式（按素材批量生成系列）：item 内逐素材克隆系列，单素材失败不中断后续
                # （partial 汇总）。item = 账户 的粒度不变——job.total / 前端进度轮询 / 重试入口零改动
                if batch_assets:
                    _deploy_item_fb_batch(sdb, job, item, tpl, batch_assets, tenant_id, link,
                                          targeting, advanced, post_content, fb)
                    sdb.commit()
                    continue
                # 结构模式（0088）：1 系列 → N 组 → M 广告（整树克隆到该账户；
                # 素材组节点逐素材展开。上方 batch_assets/单模板分支都不适用）
                tree_adsets = _parse_structure(tpl)
                if tree_adsets:
                    # 批AK：裸 Invalid parameter 换下一写令牌候选整树重试（跨App令牌伪装错）
                    _tree_err = None
                    for _fb_cand in (_fb_list or [fb]):
                        try:
                            _deploy_item_fb_tree(sdb, job, item, tpl, tree_adsets, tenant_id, _fb_cand)
                            _tree_err = None
                            break
                        except FbApiError as _fe:
                            if _is_bare_invalid_param(_fe) and _fb_cand is not (_fb_list or [fb])[-1]:
                                _tree_err = _fe
                                sdb.rollback()
                                continue
                            raise
                    if _tree_err is not None:
                        raise _tree_err
                    sdb.commit()
                    continue
                # 单模板模式：一个系列（原内联块抽为 _deploy_series_fb，行为不变）
                r = _deploy_series_fb(sdb, fb, item, tpl, asset, tenant_id, link,
                                      targeting, advanced, post_content)
                item.campaign_id = r["campaign_id"]; item.adset_id = r["adset_id"]; item.ad_id = r["ad_id"]
                item.page_post_id = r.get("page_post_id") or ""
                item.status = "success"
                # 自动建链降级留痕（批次I）：success item 也可带 error note（不静默铁律）
                item.error = (r.get("auto_subcode_warn") or None)
                item.error_code = ("auto_subcode_degraded" if r.get("auto_subcode_warn") else None)
                job.succeeded = (job.succeeded or 0) + 1
                write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                          target_type="ad", target_id=str(r.get("ad_id","")),
                          action_type="deploy", source="launch", result="success",
                          metadata={"act_id": item.act_id, "campaign_id": r.get("campaign_id"),
                                    "adset_id": r.get("adset_id"), "template_id": template_id})
            except FbApiError as e:
                item.status = "fail"; item.error = (e.friendly or str(e))[:300]; item.error_code = e.category
                job.failed = (job.failed or 0) + 1
                write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                          target_type="ad", target_id="",
                          action_type="deploy", source="launch", result="fail",
                          friendly_error=(e.friendly or str(e))[:200],
                          metadata={"act_id": item.act_id, "template_id": template_id})
            except Exception as e:
                item.status = "fail"; item.error = str(e)[:300]; item.error_code = "error"
                job.failed = (job.failed or 0) + 1
                write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                          target_type="ad", target_id="",
                          action_type="deploy", source="launch", result="fail",
                          friendly_error=str(e)[:200],
                          metadata={"act_id": item.act_id, "template_id": template_id})
            sdb.commit()
        # deploy_count 语义=建出的系列数（卡片「已部署 N」）：单模板 1 账户=1 系列；
        # 批量模式 1 账户=M 系列，按系列数累计才不虚标
        tpl.deploy_count = (tpl.deploy_count or 0) + len(items) * (len(batch_assets) or 1)
        job.status = "partial_failed" if job.failed else "completed"
        job.finished_at = datetime.now(timezone.utc)
        sdb.commit()
        # 部署后对账：拉成功账户的最新广告实体进 ads_cache（清单 live_status / 管理器立即可见；
        # 只刷建出广告的账户，失败账户无新实体）。失败仅告警，不动 job 终态。
        # TT 模板不对账：ads_cache 刷新走 FB 客户端，TT 广告缓存同步由 P4（巡检/看板平台化）接。
        if (tpl.platform or "fb") != "tt":
            try:
                _refresh_ads_cache_after_deploy(
                    tenant_id, [it.act_id for it in items if it.status == "success"])
            except Exception:
                logging.getLogger("toveads.launch").warning("[Launch] 部署后 ads_cache 对账失败", exc_info=True)
    except Exception as e:
        try:
            job = sdb.query(LaunchJob).filter(LaunchJob.id == job_id).first()
            if job:
                job.status = "failed"; job.finished_at = datetime.now(timezone.utc); sdb.commit()
        except Exception:
            pass
    finally:
        sdb.close()


# ── Job 查询 ──
def _item_dict(it: LaunchJobItem) -> dict:
    return {
        "id": it.id, "act_id": it.act_id, "page_id": it.page_id or "", "pixel_id": it.pixel_id or "",
        "status": it.status, "campaign_id": it.campaign_id or "", "adset_id": it.adset_id or "",
        "ad_id": it.ad_id or "", "subcode_slug": it.subcode_slug or "", "error": it.error or "",
        "error_code": it.error_code or "", "page_post_id": it.page_post_id or "",
        "progress": it.progress or "",                    # 批BQ：实时进度注记
        "updated_at": str(it.created_at) if it.created_at else "",   # 心跳时间戳（=最后更新）
    }


@router.get("/jobs")
def list_jobs(user: CurrentUser = Depends(require_permission("ads.create")),
              db: Session = Depends(get_db), limit: int = 20):
    rows = db.query(LaunchJob).filter(LaunchJob.tenant_id == user.tenant_id) \
        .order_by(LaunchJob.id.desc()).limit(min(max(limit, 1), 100)).all()
    return [{
        "id": j.id, "template_id": j.template_id, "template_name": j.template_name or "",
        "status": j.status, "total": j.total, "succeeded": j.succeeded, "failed": j.failed,
        "created_at": str(j.created_at) if j.created_at else "",
        "finished_at": str(j.finished_at) if j.finished_at else "",
    } for j in rows]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, user: CurrentUser = Depends(require_permission("ads.create")),
            db: Session = Depends(get_db)):
    j = db.query(LaunchJob).filter(LaunchJob.id == job_id, LaunchJob.tenant_id == user.tenant_id).first()
    if not j:
        raise HTTPException(404, "job 不存在")
    items = db.query(LaunchJobItem).filter(LaunchJobItem.job_id == job_id).all()
    # 模板平台（前端按平台跳 FB/TT 广告后台；模板可能已归档但软删不物理删，查询安全）
    _tpl_platform = (db.query(LaunchTemplate.platform).filter(
        LaunchTemplate.id == j.template_id).scalar() or "fb")
    return {
        "id": j.id, "template_id": j.template_id, "template_name": j.template_name or "",
        "platform": _tpl_platform,
        "status": j.status, "total": j.total, "succeeded": j.succeeded, "failed": j.failed,
        "created_at": str(j.created_at) if j.created_at else "",
        "finished_at": str(j.finished_at) if j.finished_at else "",
        "items": [_item_dict(it) for it in items],
    }


# ── 模板已部署清单（模板维度聚合）──
def _job_dict(j: LaunchJob) -> dict:
    return {
        "id": j.id, "template_id": j.template_id, "template_name": j.template_name or "",
        "status": j.status, "total": j.total, "succeeded": j.succeeded, "failed": j.failed,
        "created_at": str(j.created_at) if j.created_at else "",
        "finished_at": str(j.finished_at) if j.finished_at else "",
    }


def _live_status_map(db: Session, tenant_id: int, act_ids: list[str]) -> dict[str, str]:
    """ads_cache → {ad_id: effective_status}（按 items 的账户集取缓存，全状态）。
    缓存无该广告 → 不入 map，前端显「待同步」而非空白。"""
    out: dict[str, str] = {}
    ids = sorted({a for a in act_ids if a})
    if not ids:
        return out
    for row in db.query(AdsCache).filter(
        AdsCache.tenant_id == tenant_id, AdsCache.act_id.in_(ids)).all():
        try:
            for ad in json.loads(row.ads_json or "[]"):
                aid = str(ad.get("id")) if isinstance(ad, dict) and ad.get("id") else ""
                if aid:
                    out[aid] = ad.get("effective_status") or ""
        except Exception:
            continue
    return out


@router.get("/{tid}/deployments")
def template_deployments(tid: int, job_id: int = 0,
                         user: CurrentUser = Depends(require_permission("ads.create")),
                         db: Session = Depends(get_db)):
    """模板已部署清单。无 job_id = jobs 概览（时间/账户数/成败计数，近 50 次）；
    ?job_id= = 单次部署明细（items + join ads_cache 的当前 effective_status——
    广告以 PAUSED 出生，用户/规则后来开停在这里能看到活状态，与创建时状态对账）。"""
    t = db.query(LaunchTemplate).filter(
        LaunchTemplate.id == tid, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    _ro(user, t)   # 批AJ：operator 只能操作自己创建的
    if job_id:
        j = db.query(LaunchJob).filter(
            LaunchJob.id == job_id, LaunchJob.tenant_id == user.tenant_id,
            LaunchJob.template_id == tid).first()
        if not j:
            raise HTTPException(404, "部署任务不存在")
        items = db.query(LaunchJobItem).filter(LaunchJobItem.job_id == job_id).all()
        live = _live_status_map(db, user.tenant_id, [it.act_id for it in items])
        return {**_job_dict(j), "platform": t.platform or "fb",
                "items": [{**_item_dict(it), "live_status": live.get(it.ad_id or "", "")}
                          for it in items]}
    jobs = db.query(LaunchJob).filter(
        LaunchJob.tenant_id == user.tenant_id, LaunchJob.template_id == tid,
    ).order_by(LaunchJob.id.desc()).limit(50).all()
    return {"template_id": tid, "platform": t.platform or "fb",
            "deploy_count": t.deploy_count or 0,
            "jobs": [_job_dict(j) for j in jobs]}


class RetryIn(BaseModel):
    page_id: str = ""
    pixel_id: str = ""


@router.post("/jobs/{job_id}/retry/{item_id}")
def retry_item(job_id: int, item_id: int, body: RetryIn, bg: BackgroundTasks,
               user: CurrentUser = Depends(require_permission("ads.create")),
               db: Session = Depends(get_db)):
    """重试一个失败 item（重置为 pending，再跑一次）。

    守卫：① job 必须 failed/partial（running 中的重试=与原循环并发跑同账户→双份广告）
         ② item 必须 fail（success 重试=重复部署；creating/pending 在跑中）。"""
    j = db.query(LaunchJob).filter(LaunchJob.id == job_id, LaunchJob.tenant_id == user.tenant_id).first()
    if not j:
        raise HTTPException(404, "job 不存在")
    if j.status in ("pending", "running"):
        raise HTTPException(409, f"任务进行中(#{j.id})，不能重试（防并发重复建广告）")
    # 模板归档守卫（P2-2）：deploy 端点已拒归档模板，retry 补齐口径——
    # 归档模板的重试=让已废弃的结构再建半程广告（花钱且不在任何管理预期内）
    _tpl = db.query(LaunchTemplate).filter(
        LaunchTemplate.id == j.template_id, LaunchTemplate.tenant_id == user.tenant_id).first()
    if not _tpl or _tpl.status == "archived":
        raise HTTPException(400, "模板已归档，不能重试（恢复模板或复制新模板后再部署）")
    # 占位符校验（复审R2-P1，与 deploy 端点同口径）：拦截 ⑥ 上线前的存量脏占位符
    try:
        _check_url_placeholders(_tpl.landing_url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    it = db.query(LaunchJobItem).filter(LaunchJobItem.id == item_id, LaunchJobItem.job_id == job_id).first()
    if not it:
        raise HTTPException(404, "item 不存在")
    # 批AP：pending/creating 也放行——job 已终态（上面守卫挡了 running）时它们=上次重试
    # 中断的卡死行（09-09 job32 item33/34 卡 pending：按钮永远不出现、error 空、无原因）。
    # 放行=用户自我修复入口
    if it.status not in ("fail", "pending", "creating"):
        raise HTTPException(400, f"只能重试失败或卡住的 item（当前 {it.status}）")
    # 结构模式部分成功守卫（0088）：item 已建出系列（部分广告失败）时整树重试 =
    # 已成功的广告再建一份双份预算。全败（系列未建成，campaign_id 空）才允许整树重跑。
    if _parse_structure(_tpl) and (it.campaign_id or ""):
        raise HTTPException(400, "该账户已建出系列（部分广告失败）——整树重试会重复已成功的广告。请到广告管理器核查已建内容；需要补投请复制模板裁剪后再部署")
    # 账户纳管守卫（与 deploy_template 同款）——retry 原先没有：账户移除后重试，
    # cred 兜底会走全租户 RR 令牌，只要令牌还能管该 act_id 就真建广告花钱且无止损覆盖
    from ..models.fb import Account as _Acc
    _acc = db.query(_Acc).filter(
        _Acc.tenant_id == user.tenant_id, _Acc.act_id == it.act_id, _Acc.is_managed == True,  # noqa: E712
    ).first()
    if not _acc:
        raise HTTPException(400, "该账户已移除纳管，不能重试（重新导入后再部署）")
    # 原子抢占：UPDATE ... WHERE status='fail' 判 rowcount——双击并发时只有一个请求能置 pending
    # （原 check-then-write：两请求都读到 fail 都通过 → 两个后台任务 = 同账户两份广告）
    from sqlalchemy import text as _text
    # 清残留 ids（复审R2-P2）：批量全败重试时 item 还带着上一轮旧系列的 campaign/ad id——
    # 失败期间清单页显示旧系列跳转链接会误导"去 FB 后台核对"；重试成功会覆盖，全败则保持空
    # 批AP：error_code 一并清（残留 'partial' 会在 pending 行误显旧失败）；
    # WHERE 扩到 pending/creating（job 终态守卫已挡 running，此处命中=回收上次中断的卡死行）
    claimed = db.execute(
        _text("UPDATE launch_job_items SET status='pending', error=NULL, error_code=NULL, "
              "campaign_id=NULL, adset_id=NULL, ad_id=NULL, progress=NULL "
              "WHERE id=:id AND status IN ('fail','pending','creating')"),
        {"id": item_id},
    ).rowcount
    db.commit()
    if not claimed:
        raise HTTPException(409, "该 item 正在被其他请求重试")
    if body.page_id:
        it.page_id = body.page_id
    if body.pixel_id:
        it.pixel_id = body.pixel_id
    # job 置回 running + 清 finished_at——原状态停在 partial_failed/failed，
    # 前端进度轮询首拍即判终态停表，重试结果永不回显且再试被 job 终态守卫放行后 item 又 400
    # 批AM：job 行状态更新用原生 UPDATE——ORM 对象曾撞 StaleDataError
    # （UPDATE expected 1 row 0 matched：后台 reaper/并发请求已动过该行，内存对象谓词失配
    #  → retry 直接 500 无详情）。原生 UPDATE 无版本谓词，幂等。
    db.execute(_text("UPDATE launch_jobs SET status='running', finished_at=NULL WHERE id=:jid"),
               {"jid": j.id})
    j = db.query(LaunchJob).filter(LaunchJob.id == j.id).first() or j
    # 心跳 touch：重试 job 的 created_at 是原创建时间（几乎必然 >10min 前），而批量重试可能
    # 跑几十分钟——不 touch 会被 5min 一次的 _reap_stale_jobs 判孤儿标 failed → 用户再重试 =
    # 已建系列再建一份（双份预算）。touch 后与 runner「无心跳 10min 才算死」口径一致
    # （副作用：job 列表的创建时间显示为最近一次重试时间，可接受——runner 本就把它当心跳用）
    db.execute(_text("UPDATE launch_jobs SET created_at=now() WHERE id=:jid"), {"jid": j.id})
    db.commit()
    bg.add_task(_retry_one, job_id, user.tenant_id, j.template_id, item_id)
    return {"job_id": job_id, "item_id": item_id, "retrying": True}


def _find_existing_campaign(fb, act_id: str, name_prefix: str, prefer_id: str = "") -> str:
    """查账户下可复用的 campaign（部署链 campaign 名=name_prefix 原样透传，见 deploy_one_account）。
    命中返回 campaign_id，未命中返空串。campaigns edge 不支持 name 等值 filtering →
    拉 id+name 本地比对（get_paged 自动翻页）。查询失败返空串（不阻断重试，保持原行为）。
    复审C P1：只认「非 ARCHIVED/DELETED 且下面挂了 adset」的 campaign——上次 attempt 建完
    campaign 在 adset/ad 撞错失败的裸 campaign、或用户已归档的同名旧 campaign，命中即标
    success 会假成功（用户以为在投，实际零广告在跑）。多只候选时优先上次 attempt 已存的 id。"""
    if not (name_prefix or "").strip() and not prefer_id:
        return ""
    try:
        camps = fb.get_paged(f"act_{act_id}/campaigns", {"fields": "id,name,effective_status"})
    except Exception:
        return ""
    _dead = {"ARCHIVED", "DELETED"}
    cands: list[str] = []
    for c in camps:
        cid = str(c.get("id") or "")
        if not cid or str(c.get("effective_status") or "").upper() in _dead:
            continue
        if prefer_id and cid == str(prefer_id):
            cands.insert(0, cid)  # 上次 attempt 的 id 最优先
        elif (c.get("name") or "") == name_prefix:
            cands.append(cid)
    for cid in cands:
        try:
            adsets = fb.get(f"{cid}/adsets", {"fields": "id", "limit": 5})
        except Exception:
            continue   # 查询失败不认（不能确认有广告链就不赌）
        if (adsets.get("data") or []):
            return cid
    return ""


def _close_job_if_done(sdb, job_id: int):
    """重试收口：按 items 表实况重算 job 终态。

    批AP 前的问题：①失败分支无条件把 job 标完——并发重试多个 item 时，先结束的把
    job 关门、还在跑的 item 状态永远落不进进度（09-09 job32 就此卡死）；②succeeded/
    failed 计数器在并发会话上互相丢更新。改为：无 pending/creating item 才收口，
    计数以 items 表 FILTER 聚合为准（幂等，可重复调）。"""
    from sqlalchemy import text as _text
    # session autoflush=False（database.py 全局）——item 的终态先在 ORM 内存里，不 flush
    # 聚合 SQL 读到的是 DB 旧值（creating）→ 误判 in-flight 永不收口（实测 job32 抓到）
    try:
        sdb.flush()
    except Exception:
        pass
    row = sdb.execute(_text("""
        SELECT count(*) FILTER (WHERE status IN ('pending','creating')) AS inflight,
               count(*) FILTER (WHERE status = 'success') AS nok,
               count(*) FILTER (WHERE status = 'fail') AS nfail
        FROM launch_job_items WHERE job_id = :jid
    """), {"jid": job_id}).first()
    if not row or (row.inflight or 0) > 0:
        return
    sdb.execute(_text("""
        UPDATE launch_jobs SET succeeded = :nok, failed = :nfail,
            status = CASE WHEN :nfail > 0 THEN 'partial_failed' ELSE 'completed' END,
            finished_at = now()
        WHERE id = :jid
    """), {"nok": row.nok, "nfail": row.nfail, "jid": job_id})


def _retry_one(job_id: int, tenant_id: int, template_id: int, item_id: int):
    """后台重跑单个 item（复用 deploy 逻辑，只跑这一个账户）。BYPASSRLS → 全部查询显式 tenant 过滤。"""
    sdb = SuperSessionLocal()
    try:
        tpl = sdb.query(LaunchTemplate).filter(
            LaunchTemplate.id == template_id, LaunchTemplate.tenant_id == tenant_id).first()
        if not tpl:
            # 批AP：原样 return 会把 item 永远留在 pending、job 永远 running（部署 409 锁死
            # 到重启）——必须落 fail 带原因（不静默铁律）
            from sqlalchemy import text as _t2
            sdb.execute(_t2(
                "UPDATE launch_job_items SET status='fail', error='模板不存在或已删除"
                "（job 引用失效），无法重试', error_code='no_id' WHERE id=:iid"),
                {"iid": item_id})
            _close_job_if_done(sdb, job_id)
            sdb.commit()
            return
        # 临时建一个只含该 item 的"job 视图"——直接调 deploy_one_account，更新该 item
        it = sdb.query(LaunchJobItem).filter(
            LaunchJobItem.id == item_id).first()
        if not it or it.tenant_id != tenant_id:
            logging.getLogger("toveads.launch").warning(
                f"[retry] item {item_id} 不存在或跨租户，仅收口 job {job_id}")
            _close_job_if_done(sdb, job_id)
            sdb.commit()
            return
        # 借用 _run_deploy_job 的单账户逻辑：把 job 的 total 固定，succeeded/failed 增量
        asset = (sdb.query(Asset).filter(Asset.id == tpl.asset_id, Asset.tenant_id == tenant_id).first()
                 if tpl.asset_id else None)
        # 批量模式素材清单回读（与 _run_deploy_job 同源：日志 metadata；空 = 单模板重试）
        batch_assets = _job_batch_assets(sdb, job_id, tenant_id)
        targeting = _resolve_targeting(sdb, tpl.audience_id, tpl.audience_json or "", sdb_tenant_id=tenant_id)
        advanced = _parse_advanced(tpl)
        link = (sdb.query(LandingAdLink).filter(
            LandingAdLink.slug == tpl.subcode_slug, LandingAdLink.tenant_id == tenant_id).first()
            if tpl.subcode_slug else None)
        # 跟帖：预取帖子内容（表单/消息 AI 生成兜底，与 _run_deploy_job 一致）
        post_content = {}
        if (tpl.post_source or "new") == "reuse" and tpl.reuse_post_ref:
            try:
                from ..routers.fb import _fetch_post_content
                post_content = _fetch_post_content(sdb, tenant_id, tpl.reuse_post_ref) or {}
            except Exception:
                post_content = {}
        job = sdb.query(LaunchJob).filter(LaunchJob.id == job_id).first()
        # TikTok 分支（TK P3）：TT 三件套重试（复用 _deploy_item_tt，含纳管复查）；FB 路径零改动
        if (tpl.platform or "fb") == "tt":
            try:
                it.status = "creating"; sdb.commit()
                if batch_assets:
                    _deploy_item_tt_batch(sdb, job, it, tpl, batch_assets, tenant_id, link, is_retry=True)
                else:
                    _deploy_item_tt(sdb, job, it, tpl, asset, tenant_id, link, is_retry=True)
            except Exception:
                pass  # 执行器内部已消化为 item fail
            _close_job_if_done(sdb, job_id)   # 批AP：按 items 实况收口（并发重试不提前关门）
            sdb.commit()
            return  # TT 不做 ads_cache 对账（P4 接）
        try:
            it.status = "creating"; sdb.commit()
            # 后台二次纳管校验（请求时已查，这里防请求→执行间隙账户被移除——
            # cred 兜底全租户 RR 会让已移除账户继续建广告花钱且无止损覆盖）
            from ..models.fb import Account as _Acc2
            _acc2 = sdb.query(_Acc2).filter(
                _Acc2.tenant_id == tenant_id, _Acc2.act_id == it.act_id,
                _Acc2.is_managed == True,  # noqa: E712
            ).first()
            if not _acc2:
                raise FbApiError("no_id", "该账户已移除纳管，跳过重试")
            # 跟帖(reuse)：选能管该帖主页的写令牌（与 _run_deploy_job 一致）
            is_reuse = (tpl.post_source or "new") == "reuse" and bool(tpl.reuse_post_ref)
            _page_for_token = (it.page_id or tpl.page_id or "") if is_reuse else ""
            if is_reuse and _page_for_token:
                fb = client_for_account_page(sdb, tenant_id, it.act_id, _page_for_token, "write")
                if not fb:
                    raise FbApiError("no_id", f"act_{it.act_id} 无访问主页 {_page_for_token} 的写令牌（跟帖模式）")
            else:
                _fb_list, _ = _write_fb_with_fallback(sdb, tenant_id, it.act_id)
                if not _fb_list:
                    raise FbApiError("no_id", f"act_{it.act_id} 未绑定写令牌")
                fb = _fb_list[0]
            # 结构模式重试（0088）：整树重跑（仅全败 item——部分成功在端点层已拒）；
            # 不走 _find_existing_campaign 幂等捷径（树有多组多名，同名命中无法确认归属）
            tree_adsets = _parse_structure(tpl)
            if tree_adsets:
                _deploy_item_fb_tree(sdb, job, it, tpl, tree_adsets, tenant_id, fb, is_retry=True)
                _close_job_if_done(sdb, job_id)
                sdb.commit()
                if it.status == "success" and it.ad_id:
                    try:
                        _refresh_ads_cache_after_deploy(tenant_id, [it.act_id])
                    except Exception:
                        pass
                return
            # 批量模式重试 = 整个 item 重跑（全部素材重建）。不走下方 _find_existing_campaign
            # 同名幂等捷径——它只对单模板模式可靠：批量系列名=素材名，与账户里既有的同名
            # campaign 无法区分是否本次 job 所建（素材名撞已有系列名时误命中=假成功漏建系列）。
            # 注意：partial 重试会把上次已成功的系列再建一份（重试前先按 error 汇总核对 FB 后台）
            if batch_assets:
                _deploy_item_fb_batch(sdb, job, it, tpl, batch_assets, tenant_id, link,
                                      targeting, advanced, post_content, fb, is_retry=True)
                _close_job_if_done(sdb, job_id)
                sdb.commit()
                if it.status == "success" and it.ad_id:
                    try:
                        _refresh_ads_cache_after_deploy(tenant_id, [it.act_id])
                    except Exception:
                        pass
                return
            # 幂等防重（P0-9）：上次 attempt 可能已把广告建进 FB（超时/读响应失败误标 fail），
            # 盲重试=同账户再建一份双份预算。先查同名 campaign（名=name_prefix，且必须挂着
            # adset 的才认——裸 campaign 假 success 见 _find_existing_campaign 注释），命中→
            # 复用已存在 id 标 success 跳过重建；未命中→正常重建。
            _dup_camp = _find_existing_campaign(fb, it.act_id, tpl.name_prefix,
                                                prefer_id=(it.campaign_id or ""))
            if _dup_camp:
                it.campaign_id = _dup_camp
                it.status = "success"; it.error = None; it.error_code = None
                _close_job_if_done(sdb, job_id)
                write_log(sdb, tenant_id=tenant_id, trace_id=new_trace_id(), actor_type="system",
                          target_type="ad", target_id="", action_type="deploy", source="launch",
                          result="success",
                          metadata={"act_id": it.act_id, "campaign_id": _dup_camp,
                                    "template_id": template_id, "reused_existing": True})
                sdb.commit()
                return
            image_hash = ""
            video_id = ""
            video_thumb_hash = ""
            if asset and asset.type in ("image", "video"):
                filepath = os.path.join(ASSET_DIR, asset.storage_key)
                if not os.path.exists(filepath):
                    raise FbApiError("no_id", f"素材文件丢失: {asset.storage_key}")
                if asset.type == "image":
                    image_hash = ensure_image_hash_for_account(fb, sdb, asset, it.act_id, filepath)
                else:
                    video_id = ensure_video_id_for_account(fb, sdb, asset, it.act_id, filepath)
                    video_thumb_hash = ensure_video_thumb_hash(fb, sdb, asset, it.act_id, filepath)
                sdb.commit()
            _page_id = it.page_id or tpl.page_id
            _px_id = it.pixel_id or tpl.pixel_id
            if not _px_id:
                _px_id = _ensure_account_pixel(sdb, tenant_id, it.act_id, fb)
            # 与 _run_deploy_job 保持一致：表单模板 page-aware 解析 + AI 消息兜底（重试要等价于全新部署，否则 LEADS/ENGAGEMENT 重试拿到错误/缺失的 form/message）
            lead_form_id = ""
            if tpl.objective == "OUTCOME_LEADS" and _page_id:
                try:
                    lead_form_id = _resolve_lead_form(fb, sdb, tpl, asset, _page_id,
                                                      _stable_landing_url(tpl.landing_url or "", tpl.name or ""),
                                                      post_content=post_content)
                except Exception:
                    pass
            # 没选消息模板 → AI 生成（ENGAGEMENT+消息）；跟帖无素材→用帖内容
            message_template = tpl.message_template or ""
            if not message_template and tpl.objective == "OUTCOME_ENGAGEMENT":
                _msg_body = ""
                if asset:
                    try:
                        ai_copy = json.loads(asset.ai_copy_json or "{}") if asset.ai_copy_json else {}
                        _msg_body = (ai_copy.get("bodies") or [""])[0]
                    except Exception:
                        pass
                elif post_content.get("message"):
                    _msg_body = post_content["message"]
                if _msg_body:
                    message_template = json.dumps({"text": _msg_body[:500], "ice_breakers": []})
            from ..core.ad_ops import pick_ad_copy
            _headline, _body = pick_ad_copy(asset, tpl.headline or "", tpl.body or "")
            page_post_id = _resolve_page_post(sdb, fb, tenant_id, tpl, asset, _page_id, body=_body)
            if page_post_id:
                sdb.commit()
            # 追踪参数插值（retry 单模板路径；批量 retry 走 _deploy_item_fb_batch→_deploy_series_fb 已接）
            _rt_acc = sdb.query(Account).filter(Account.tenant_id == tenant_id,   # 全库审查 P2
                                                        Account.act_id == it.act_id).first()
            _lp_url = _interp_landing_url(
                tpl.landing_url, campaign_name=tpl.name_prefix,
                account_name=(_rt_acc.name if _rt_acc else ""), account_id=it.act_id,
                asset_name=((asset.name or asset.filename or "") if asset else ""),
                template_name=tpl.name, platform="fb")
            # 自动建链（批次I，与 _deploy_series_fb 同口径；重试=全新部署等价）+ URL 跟随（批次II）
            _a_slug, _a_link, _a_base, _a_warn = _flat_auto_subcode(sdb, tpl, it, asset)
            if not _a_base and (tpl.landing_page_id or 0):
                try:
                    _hb, _hp, _herr = _healthy_landing_base(sdb, tpl.tenant_id, int(tpl.landing_page_id))
                    if _herr:
                        raise _LandingBlockedError(_herr)
                    _a_base = _hb or ""
                except _LandingBlockedError:
                    raise
                except Exception:
                    _a_base = ""
            if _a_base:
                _lp_url = _a_base
            r = deploy_one_account(
                fb, act_id=it.act_id, objective=tpl.objective, conversion_goal=tpl.conversion_goal,
                page_id=_page_id, pixel_id=_px_id,
                landing_url=_lp_url,
                daily_budget=(0 if (tpl.budget_type or "daily") == "lifetime"
                              else _resolve_budget_fb(sdb, it.act_id, tpl, tenant_id)),
                budget_mode=tpl.budget_mode, bid_strategy=tpl.bid_strategy, name_prefix=tpl.name_prefix,
                headline=_headline, body=_body, cta_type=tpl.cta_type, image_hash=image_hash,
                video_id=video_id,
                video_thumb_hash=video_thumb_hash,
                subcode_slug=(_a_slug or tpl.subcode_slug), subcode_link=(_a_link if _a_slug else link),
                targeting=targeting, ad_language=tpl.ad_language,
                dsa_beneficiary=tpl.beneficiary or "", dsa_payor=tpl.payer or "",
                optimization_goal=tpl.optimization_goal or "", billing_event=tpl.billing_event or "",
                destination_type_override=tpl.destination_type or "",
                page_post_id=page_post_id,
                advanced_config=advanced,
                lead_form_id=lead_form_id, message_template=message_template,
                spend_cap=(_usd_to_account_minor(sdb, it.act_id, float(tpl.spend_cap_usd), tenant_id)
                           if tpl.spend_cap_usd else None),
                instagram_actor_id=(tpl.instagram_actor_id or ""),
                # 批G字段补齐（重试=等价于全新部署，agent 复审抓的既有缺口）
                budget_type=(tpl.budget_type or "daily"),
                lifetime_budget=(_usd_to_account_minor(sdb, it.act_id, float(tpl.lifetime_budget_usd), tenant_id)
                                 if (tpl.budget_type or "daily") == "lifetime" and tpl.lifetime_budget_usd else None),
                start_time=(tpl.schedule_start or ""), end_time=(tpl.schedule_end or ""),
                pacing=(tpl.pacing or ""),
                bid_amount=(_usd_to_account_minor(sdb, it.act_id, float(tpl.bid_amount_usd), tenant_id)
                            if tpl.bid_amount_usd else None),
                minimum_roas=(tpl.minimum_roas if tpl.minimum_roas else None),
                special_ad_categories=(json.loads(tpl.special_ad_categories or "[]")
                                       if tpl.special_ad_categories else None),
                description=(tpl.link_description or ""),
                whatsapp_phone_number=(tpl.whatsapp_phone_number or ""),
            )
            it.campaign_id = r["campaign_id"]; it.adset_id = r["adset_id"]; it.ad_id = r["ad_id"]
            it.page_post_id = r.get("page_post_id") or page_post_id
            it.status = "success"
            # 自动建链降级留痕（批次I）+ 像素自愈留痕（批AZ 统一：平铺重试同树路径口径）
            _px_w = (f"[像素] 所配像素（模板/落地页）当前令牌无权使用，已自动换为账户可用像素 {r['pixel_swapped']}"
                     if r.get("pixel_swapped") else "")
            it.error = ("；".join(w for w in (_a_warn, _px_w) if w) or None)
            it.error_code = ("auto_subcode_degraded" if (_a_warn or _px_w) else None)
            if r.get("pixel_swapped") and (tpl.landing_page_id or 0):
                try:
                    _bind_pixel_to_landing_page(sdb, tenant_id, int(tpl.landing_page_id),
                                                r["pixel_swapped"], it.act_id)
                except Exception:
                    pass
        except FbApiError as e:
            it.status = "fail"; it.error = (e.friendly or str(e))[:300]; it.error_code = e.category
        except Exception as e:
            it.status = "fail"; it.error = str(e)[:300]; it.error_code = "error"
        # 批AP：收口统一走 _close_job_if_done——失败也收（防 running 永停 409 锁死部署），
        # 但还有并发重试的 item 在跑时不提前关门
        _close_job_if_done(sdb, job_id)
        sdb.commit()
        # 重试成功也做对账（新 ad_id 要进 ads_cache 才能在清单看到活状态）
        if it.status == "success" and it.ad_id:
            try:
                _refresh_ads_cache_after_deploy(tenant_id, [it.act_id])
            except Exception:
                pass
    finally:
        sdb.close()
