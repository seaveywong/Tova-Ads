"""落地流量「真人」判定的单一来源：爬虫条件（ASN + UA）。

消费方（改这里全站同步，别在别处另抄一份）：
- routers/landing.py        日志来源归因/筛选（_classify_source 与此同义）
- routers/ads.py            管理器落地聚合（访问/通过）+ 广告诊断面板
- services/guard_engine.py  规则引擎转化口径（爬虫访问不算转化、不豁免空耗）

口径（用户定义）：综合转化只计「真正从广告进入的真人」——爬虫/审核机器人
（Meta IP 池、搜索爬虫 UA）一律不计。
"""

# 爬虫 UA 特征 token（小写子串匹配）。AS 32934（Meta 审核爬虫出口集群）单独判。
CRAWLER_UA_TOKENS = ("facebookexternalhit", "facebot", "meta-externalagent", "googlebot", "bingbot",
                     "baiduspider", "bytespider", "yandexbot", "duckduckbot", "crawler", "spider")
CRAWLER_ASN = "32934"

_CRAWLER_RE = "|".join(CRAWLER_UA_TOKENS)


def crawler_not_sql(prefix: str = "") -> str:
    """raw SQL 的「非爬虫」条件（供 AND 嵌入）。prefix 给列加表前缀，如 'landing_events.'。"""
    asn = f"{prefix}asn"
    ua = f"{prefix}user_agent"
    return f"({asn} IS DISTINCT FROM '{CRAWLER_ASN}' AND COALESCE({ua}, '') !~* '({_CRAWLER_RE})')"


def crawler_filter_cond(model):
    """SQLAlchemy 爬虫条件（与 crawler_not_sql 同义）；取反 ~ 即「非爬虫」。"""
    from sqlalchemy import or_
    return or_(model.asn == CRAWLER_ASN, *[model.user_agent.ilike(f"%{t}%") for t in CRAWLER_UA_TOKENS])
