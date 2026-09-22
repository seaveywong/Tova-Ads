"""受众模板库路由：兴趣搜索 + 保存/列/改/删（doc 02 受众，审计项目16）。

v1 仅兴趣受众（search+save+use+edit，无 custom_audiences/lookalikes——v2）。
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission, require_owned as _ro
from ..core.encryption import decrypt
from ..core.fb_client import FbClient, FbApiError
from ..core.log_utils import write_log, new_trace_id
from ..models.fb import FbCredential
from ..models.audience import SavedAudience

router = APIRouter(prefix="/audiences", tags=["audiences"])


# ── 兴趣搜索（代理 FB adinterest；受众 1:1 批扩 type：行为/语言）──
@router.get("/search")
def search_interests(q: str, type: str = "interest", limit: int = 20,
                     user: CurrentUser = Depends(require_permission("ads.read")),
                     db: Session = Depends(get_db)):
    """FB 定向词搜索（审计项目16）。type=interest|behavior|locale。
    返 [{id,name,audience_size,path}, ...]，供前端选兴趣/行为 → audience_json。"""
    if not q or len(q) < 1:
        raise HTTPException(400, "查询词 q 不能为空")
    if type not in ("interest", "behavior", "locale"):
        raise HTTPException(400, "type 必须是 interest/behavior/locale")
    from ..core.fb_tokens import first_client
    fb = first_client(db, user.tenant_id)  # 定向搜索 token 无关，任一 active 即可
    if not fb:
        raise HTTPException(400, "未绑定 FB 凭证")
    try:
        if type == "behavior":
            return fb.search_behaviors(q, limit=limit)
        if type == "locale":
            return fb.search_locales(q, limit=limit)
        return fb.search_interests(q, limit=limit)
    except FbApiError as e:
        raise HTTPException(400, f"定向搜索失败：{e.friendly}")


@router.get("/geo-search")
def geo_search(q: str, countries: str = "", limit: int = 20,
               user: CurrentUser = Depends(require_permission("ads.read")),
               db: Session = Depends(get_db)):
    """FB 地理位置搜索（州/城市/邮编，type=adgeolocation）——受众 1:1 批。
    countries=逗号分隔 ISO 码（限定在已选国家内搜，如 US）。返 [{key,name,type,country_code}]。"""
    if not q or len(q) < 2:
        raise HTTPException(400, "查询词至少 2 个字符")
    from ..core.fb_tokens import first_client
    fb = first_client(db, user.tenant_id)
    if not fb:
        raise HTTPException(400, "未绑定 FB 凭证")
    cs = [c.strip().upper() for c in (countries or "").split(",") if c.strip()]
    try:
        return fb.search_geo(q, cs or None, limit=limit)
    except FbApiError as e:
        raise HTTPException(400, f"地理搜索失败：{e.friendly}")


_CJK_RE = None  # lazy re（顶部 import 保持最小）


def _has_cjk(s: str) -> bool:
    global _CJK_RE
    if _CJK_RE is None:
        import re
        _CJK_RE = re.compile(r"[一-鿿]")
    return bool(_CJK_RE.search(s or ""))


# 常用定向词中→英词库（2026-09-21 提速批）：受众搜索高频词内置映射，命中即免 AI
# （Grok 推理模型翻译一词 10-25s 是统一搜索慢的主因）。未命中走 AI + 缓存。
_LOCAL_TERM_MAP = {
    "美妆": ["Makeup", "Cosmetics", "Beauty"], "化妆": ["Makeup", "Cosmetics"],
    "护肤": ["Skincare", "Skin care"], "美容": ["Beauty", "Cosmetics"],
    "香水": ["Perfume", "Fragrance"], "口红": ["Lipstick"], "指甲": ["Nail art", "Manicure"],
    "购物": ["Shopping", "Online shopping"], "网购": ["Online shopping", "E-commerce"],
    "电商": ["E-commerce", "Online shopping"], "促销": ["Deals", "Discounts"],
    "时尚": ["Fashion", "Style"], "服装": ["Fashion", "Clothing"], "衣服": ["Clothing", "Fashion"],
    "鞋": ["Shoes", "Footwear"], "包": ["Handbags", "Bags"], "珠宝": ["Jewelry"],
    "手表": ["Watches"], "奢侈品": ["Luxury goods", "Luxury brands"],
    "健身": ["Fitness", "Gym", "Workout"], "减肥": ["Weight loss", "Fitness"],
    "瑜伽": ["Yoga"], "跑步": ["Running", "Jogging"], "游泳": ["Swimming"],
    "篮球": ["Basketball"], "足球": ["Soccer", "Football"], "高尔夫": ["Golf"],
    "滑雪": ["Skiing", "Snowboarding"], "露营": ["Camping"], "钓鱼": ["Fishing"],
    "户外": ["Outdoor recreation", "Hiking"], "登山": ["Hiking", "Mountaineering"],
    "骑行": ["Cycling", "Bicycles"], "运动": ["Sports", "Exercise"],
    "健康": ["Health", "Wellness"], "医疗": ["Healthcare", "Medical"],
    "医美": ["Cosmetic surgery", "Medical aesthetics"], "牙科": ["Dentistry", "Dental care"],
    "营养": ["Nutrition", "Supplements"], "维生素": ["Vitamins", "Supplements"],
    "母婴": ["Baby products", "Parenting"], "育儿": ["Parenting", "Childcare"],
    "儿童": ["Kids", "Children products"], "玩具": ["Toys"],
    "宠物": ["Pet food", "Pet supplies", "Pets"], "狗": ["Dogs", "Dog food"],
    "猫": ["Cats", "Cat food"], "养狗": ["Dogs", "Dog owners"], "养猫": ["Cats", "Cat owners"],
    "旅游": ["Travel", "Vacation"], "旅行": ["Travel", "Tourism"], "度假": ["Vacation", "Travel"],
    "酒店": ["Hotels", "Hospitality"], "机票": ["Air travel", "Flights"],
    "美食": ["Food", "Gourmet"], "食品": ["Food", "Grocery"], "零食": ["Snacks", "Sweets"],
    "咖啡": ["Coffee"], "茶": ["Tea"], "酒": ["Wine", "Alcoholic beverages"],
    "烹饪": ["Cooking", "Recipes"], "烘焙": ["Baking"], "烧烤": ["Barbecue", "Grilling"],
    "家居": ["Home decor", "Furniture"], "家具": ["Furniture"], "装修": ["Home improvement", "Interior design"],
    "建材": ["Building materials", "Construction"], "园艺": ["Gardening"],
    "清洁": ["Cleaning", "Home cleaning"], "洗衣": ["Laundry", "Laundry services"],
    "科技": ["Technology", "Gadgets"], "数码": ["Consumer electronics", "Gadgets"],
    "手机": ["Smartphones", "Mobile phones"], "电脑": ["Computers", "Laptops"],
    "耳机": ["Headphones", "Earbuds"], "电视": ["Televisions", "TV"],
    "游戏": ["Video games", "Gaming"], "电竞": ["Esports", "Gaming"],
    "动漫": ["Anime", "Manga"], "摄影": ["Photography"], "音乐": ["Music"],
    "电影": ["Movies", "Cinema"], "读书": ["Books", "Reading"], "阅读": ["Reading", "Books"],
    "教育": ["Education", "Online education"], "学习": ["Learning", "Education"],
    "英语学习": ["English learning", "Language learning"], "留学": ["Study abroad"],
    "金融": ["Finance", "Personal finance"], "投资": ["Investing", "Investments"],
    "理财": ["Personal finance", "Wealth management"], "股票": ["Stock market", "Stock trading"],
    "加密货币": ["Cryptocurrency", "Bitcoin"], "保险": ["Insurance"],
    "贷款": ["Loans", "Credit"], "信用卡": ["Credit cards"], "房贷": ["Mortgage", "Home loans"],
    "汽车": ["Cars", "Automotive"], "电动车": ["Electric vehicles", "EV"],
    "摩托车": ["Motorcycles"], "自行车": ["Bicycles", "Cycling"],
    "房产": ["Real estate", "Property"], "租房": ["Renting", "Apartment rentals"],
    "法律": ["Law", "Legal services"], "会计": ["Accounting", "Bookkeeping"],
    "招聘": ["Recruitment", "Job hunting"], "求职": ["Job hunting", "Careers"],
    "婚礼": ["Wedding", "Weddings"], "婚纱": ["Wedding dress", "Bridal"],
    "纹身": ["Tattoos"], "美发": ["Hair salon", "Hair care"], "理发": ["Haircuts", "Hair salon"],
    "太阳能": ["Solar energy", "Solar panels"], "新能源": ["Renewable energy", "Clean energy"],
    "无人机": ["Drones"], "智能手表": ["Smartwatches", "Wearables"],
    "礼品": ["Gifts", "Gift shopping"], "情人节": ["Valentines Day", "Romantic gifts"],
    "圣诞": ["Christmas", "Holiday shopping"], "万圣节": ["Halloween"],
    "感恩节": ["Thanksgiving"], "黑色星期五": ["Black Friday", "Shopping deals"],
    "家具装饰": ["Home decor", "Interior decorating"], "床垫": ["Mattresses", "Bedding"],
    "婴儿": ["Baby", "Baby products"], "孕妇": ["Pregnancy", "Maternity"],
    "老年": ["Seniors", "Elderly care"], "退休": ["Retirement", "Seniors"],
    "收藏": ["Collectibles", "Collecting"], "手工": ["Handmade crafts", "DIY crafts"],
    "绘画": ["Drawing", "Painting"], "舞蹈": ["Dancing", "Dance classes"],
    "唱歌": ["Singing", "Karaoke"], "乐器": ["Musical instruments"],
    "手机配件": ["Phone accessories", "Phone cases"], "汽车配件": ["Auto parts", "Car accessories"],
}
_TRANSLATE_CACHE: dict = {}   # {词: (ts, [英译])}——翻译不变，1h 缓存砍重复词的 10-20s AI 延迟


def _ai_translate_terms(q: str) -> list[str]:
    """中文 → FB 英文搜索词（最多 3 个）。FB 兴趣/地理库英文为主——中文直搜结果显著
    更少（实测：奥斯汀 1 条 vs Austin 5 条）。命中内置词库即返（秒回，免 AI 慢翻译）；
    AI 未配/失败 → 空列表（降级原文直搜）。"""
    import time as _t
    _local = _LOCAL_TERM_MAP.get(q.strip())
    if _local:
        return list(_local)
    _hit = _TRANSLATE_CACHE.get(q)
    if _hit and _t.time() - _hit[0] < 3600:
        return _hit[1]
    try:
        from ..core.ai_client import AiClient, AiError
        cli = AiClient()
        if not cli.is_configured():
            return []
        raw = cli.chat([
            {"role": "system", "content": "你是 Facebook 广告定向关键词翻译器。把用户输入翻译成最多 3 个最可能命中 FB 兴趣库的英文搜索词。只输出英文词，逗号分隔，不要任何解释。"},
            {"role": "user", "content": q},
        ], temperature=0.1, max_tokens=60, timeout=25)
        terms = [t.strip() for t in raw.replace("，", ",").split(",") if t.strip()]
        out = [t for t in terms if not _has_cjk(t)][:3]
        if len(_TRANSLATE_CACHE) > 2000:
            _TRANSLATE_CACHE.clear()
        _TRANSLATE_CACHE[q] = (_t.time(), out)
        return out
    except Exception:
        return []


_SEARCH_CACHE: dict = {}   # {(kind, term): (ts, rows)} 10min——同词搜索结果稳定


def _fb_search_cached(fb, kind: str, term: str, limit: int):
    import time as _t
    ck_ = (kind, term.lower())
    hit = _SEARCH_CACHE.get(ck_)
    if hit and _t.time() - hit[0] < 600:
        return hit[1]
    try:
        if kind == "interest":
            rows = fb.search_interests(term, limit=limit) or []
        elif kind == "behavior":
            rows = fb.search_behaviors(term, limit=limit) or []
        elif kind == "geo":
            rows = fb.search_geo(term, None, limit=5) or []
        elif kind == "locale":
            rows = fb.search_locales(term, limit=4) or []
        else:
            rows = []
    except Exception as e:
        raise
    if len(_SEARCH_CACHE) > 4000:
        _SEARCH_CACHE.clear()
    _SEARCH_CACHE[ck_] = (_t.time(), rows)
    return rows


@router.get("/search-all")
def search_all(q: str, countries: str = "", limit: int = 8, fast: int = 0,
               user: CurrentUser = Depends(require_permission("ads.read")),
               db: Session = Depends(get_db)):
    """统一定向搜索（受众交互批 2026-09-21；提速批 09-22 加 fast）：一个词并行搜
    兴趣/行为/地理(州·城市·邮编)/语言，中文自动英译双搜合并。
    fast=1（渐进一段）：中文且翻译未就绪时不等 AI——立即返原文结果 +
    translated_pending=true（后台线程翻译落缓存，前端 2.5s 后原参重查即得全量合并）。"""
    if not q or len(q.strip()) < 1:
        raise HTTPException(400, "查询词 q 不能为空")
    from ..core.fb_tokens import first_client
    fb = first_client(db, user.tenant_id)
    if not fb:
        raise HTTPException(400, "未绑定 FB 凭证")
    if not hasattr(fb, "search_interests"):
        # 复审 #5：纯 TT 租户 first_client 返 TtClient（无 search_*）——曾 AttributeError
        # 被逐线程吞掉，统一搜索静默空结果
        raise HTTPException(400, "定向搜索需要 FB 令牌（当前租户无可用 FB 令牌）")
    import json as _json
    from concurrent.futures import ThreadPoolExecutor
    cs = [c.strip().upper() for c in (countries or "").split(",") if c.strip()]

    translated: list[str] = []
    base_q = q.strip()
    queries = [base_q]

    _first_err: list = []   # 复审 #5：吞错改为收集——全线空结果且有错时 400 报因（曾静默空）

    def _run(kind: str, term: str):
        try:
            return _fb_search_cached(fb, kind, term, limit, ) if kind != "geo" else _run_geo(term)
        except Exception as e:
            if not _first_err:
                _first_err.append(str(e)[:150])
            return []

    def _run_geo(term: str):
        # geo 带 countries 限定（限定不同结果不同）——缓存键并入
        import time as _t
        ck_ = ("geo", term.lower(), ",".join(cs))
        hit = _SEARCH_CACHE.get(ck_)
        if hit and _t.time() - hit[0] < 600:
            return hit[1]
        try:
            rows = fb.search_geo(term, cs or None, limit=5) or []
        except Exception as e:
            if not _first_err:
                _first_err.append(str(e)[:150])
            return []
        _SEARCH_CACHE[ck_] = (_t.time(), rows)
        return rows

    jobs = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        # 原文四类搜索 + AI 英译并行（AI 慢时原文结果已就绪——翻译只为补英文库覆盖）
        for kind in ("interest", "behavior", "geo", "locale"):
            jobs.append((kind, base_q, ex.submit(_run, kind, base_q)))
        if _has_cjk(q):
            if fast and not _LOCAL_TERM_MAP.get(base_q) and not _TRANSLATE_CACHE.get(base_q):
                # 渐进一段：翻译不在词库/缓存 → 后台线程翻（落缓存），本请求立即返原文结果
                import threading as _th
                _pending = True

                def _bg():
                    try:
                        _ai_translate_terms(base_q)
                    except Exception:
                        pass
                _th.Thread(target=_bg, daemon=True).start()
            else:
                translated = ex.submit(_ai_translate_terms, base_q).result() or []
                queries += [t for t in translated if t.lower() not in q.lower()][:3]
        queries = list(dict.fromkeys(queries))[:4]
        for i, term in enumerate(queries[1:], 1):
            jobs.append(("interest", term, ex.submit(_run, "interest", term)))
            jobs.append(("behavior", term, ex.submit(_run, "behavior", term)))
            if i == 1:   # 地理/语言第一个英译词足够（避免调用爆炸）
                jobs.append(("geo", term, ex.submit(_run, "geo", term)))
                jobs.append(("locale", term, ex.submit(_run, "locale", term)))

    ints: list = []
    bhvs: list = []
    geo: list = []
    locs: list = []
    seen_i, seen_b, seen_g, seen_l = set(), set(), set(), set()
    for kind, term, fut in jobs:
        for x in fut.result() or []:
            if kind == "interest":
                k = str(x.get("id") or x.get("name"))
                if k and k not in seen_i:
                    seen_i.add(k); ints.append(x)
            elif kind == "behavior":
                k = str(x.get("id") or x.get("name"))
                if k and k not in seen_b:
                    seen_b.add(k); bhvs.append(x)
            elif kind == "geo":
                k = str(x.get("key") or x.get("name"))
                if k and k not in seen_g:
                    seen_g.add(k); geo.append(x)
            else:
                k = str(x.get("id") or x.get("name"))
                if k and k not in seen_l:
                    seen_l.add(k); locs.append(x)
    if not (ints or bhvs or geo or locs) and _first_err:
        # 全线空且真有错（令牌过期/限流等）→ 报因，不再 200 空结果（复审 #5）
        raise HTTPException(400, f"定向搜索失败：{_first_err[0]}")
    return {"interests": ints[:12], "behaviors": bhvs[:6], "geo": geo[:8],
            "locales": locs[:4], "translated": translated,
            "translated_pending": locals().get("_pending", False)}


@router.get("/custom-audiences")
def list_custom_audiences(act_id: str,
                          user: CurrentUser = Depends(require_permission("ads.read")),
                          db: Session = Depends(get_db)):
    """账户自定义受众列表（含 Lookalike）——受众 1:1 批。受众 id 是账户级的：
    模板里存名称/示例 id，部署时按名在本账户解析（跨账户同名匹配）。
    RBAC：只允许查询本人可见账户（operator=名下）。"""
    from ..models.fb import Account
    from ..core.deps import scope_account_query
    q = scope_account_query(db.query(Account), user)
    if not q.filter(Account.act_id == act_id).first():
        raise HTTPException(403, "该账户不在你的可见范围")
    from ..core.fb_tokens import client_for_account
    fb = client_for_account(db, user.tenant_id, act_id, "read")
    if not fb:
        raise HTTPException(400, f"账户 {act_id} 无可用读令牌")
    try:
        return fb.custom_audiences(act_id)
    except FbApiError as e:
        raise HTTPException(400, f"读取自定义受众失败：{e.friendly}")


# ── 受众模板 CRUD ──
class AudienceIn(BaseModel):
    name: str
    interests: list[dict] = []  # [{id,name}, ...]
    countries: list[str] = ["US"]
    age_min: int = 18
    age_max: int = 65
    gender: int = 0  # 0=all 1=male 2=female
    strategy: str = "broad_interest"  # broad_interest/broad_only/interest_only
    note: str = ""


class AudienceUpdate(BaseModel):
    name: str | None = None
    interests: list[dict] | None = None
    countries: list[str] | None = None
    age_min: int | None = None
    age_max: int | None = None
    gender: int | None = None
    strategy: str | None = None
    note: str | None = None
    status: str | None = None


def _row_dict(a: SavedAudience) -> dict:
    return {
        "id": a.id, "name": a.name,
        "interests": json.loads(a.interests_json or "[]"),
        "countries": json.loads(a.countries or "[]"),
        "age_min": a.age_min, "age_max": a.age_max, "gender": a.gender,
        "strategy": a.strategy, "status": a.status, "note": a.note,
    }


@router.get("")
def list_audiences(user: CurrentUser = Depends(require_permission("ads.read")),
                   db: Session = Depends(get_db)):
    _q = db.query(SavedAudience).filter(SavedAudience.tenant_id == user.tenant_id)
    if user.role == "operator":   # 批AG：operator 只看自己创建的
        _q = _q.filter(SavedAudience.created_by == user.id)
    rows = _q.order_by(SavedAudience.id.desc()).all()
    from ..models.auth import User as _U
    umap = {u.id: u.email for u in db.query(_U).filter(_U.id.in_(
        [a.created_by for a in rows if a.created_by] or [0])).all()}
    return [{**_row_dict(a), "created_by_name": umap.get(a.created_by, "")} for a in rows]


@router.post("")
def create_audience(body: AudienceIn, user: CurrentUser = Depends(require_permission("ads.create")),
                    db: Session = Depends(get_db)):
    if body.strategy not in ("broad_interest", "broad_only", "interest_only"):
        raise HTTPException(400, "strategy 必须是 broad_interest/broad_only/interest_only")
    if not (18 <= body.age_min <= 65) or not (18 <= body.age_max <= 65) or body.age_min > body.age_max:
        raise HTTPException(400, "age_min/age_max 范围无效（18-65，min<=max）")
    if body.gender not in (0, 1, 2):
        raise HTTPException(400, "gender 必须是 0/1/2")
    row = SavedAudience(
        tenant_id=user.tenant_id, created_by=user.id, name=body.name,
        interests_json=json.dumps(body.interests),
        countries=json.dumps(body.countries),
        age_min=body.age_min, age_max=body.age_max, gender=body.gender,
        strategy=body.strategy, note=body.note or None,
    )
    db.add(row)
    db.flush()
    rid = row.id
    trace_id = new_trace_id()
    write_log(db, tenant_id=user.tenant_id, trace_id=trace_id, actor_type="user",
              actor_user_id=user.id, target_type="audience", target_id=str(rid),
              action_type="create", source="user", result="success",
              metadata={"strategy": body.strategy, "interests": len(body.interests)})
    db.commit()
    return {"id": rid, "trace_id": trace_id, **_row_dict(row)}




