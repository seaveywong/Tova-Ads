"""KPI resolver（审计项目10/11）——给定广告 → 解析其 KPI 转化字段 + 计数。

v1 三级：L0 手动（kpi_configs）→ L4 规则（objective×opt_goal 矩阵）→ L5 语义兜底。
完整 5 级（L3 历史 + L1/L2 AI 矫正）见 v2（1.0 kpi_resolver.py 1131 行）。

为什么需要：FB Ads Manager "成效" = 广告优化目标的 action。PAGE_LIKES→like，购物→purchase。
之前 _extract_conversions 只认 purchase/lead → PAGE_LIKES 回传 0（实际 19）。resolver 按目标解析。
"""
import hashlib
import json
import logging
import time
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..core.ai_client import AiClient, AiError
from ..core.database import SuperSessionLocal
from ..models.kpi import KpiConfig
from ..models.system import SystemSetting

logger = logging.getLogger("toveads.kpi")

# AI KPI 纠偏结果缓存：{配置摘要|objective|opt_goal: (field, ts)}，1h TTL（防热路径 token 失控）
_AI_KPI_CACHE: dict = {}

# 118：可选 KPI AI 请求互斥；117 已由 leads_poll 占用。失败状态跨 worker 存 DB。
_AI_KPI_LOCK = 118
_AI_KPI_RETRY_SECONDS = 300


def _ai_retry_key(client: AiClient) -> str:
    # 配置变更后立即使用新服务；DB 只存摘要，不存 API key 或广告数据。
    config = json.dumps([client.base_url, client.api_key, client.model])
    return "kpi_ai_retry:" + hashlib.sha256(config.encode()).hexdigest()


def _kpi_ai_json(client: AiClient, messages: list) -> Optional[dict]:
    """429 后每 5 分钟只探测一次 AI；其间 KPI 继续走原有规则/语义兜底。"""
    # 独立事务避免提交/回滚调用者待写的快照；事务锁在 commit/close 时自动释放。
    with SuperSessionLocal() as sdb:
        if not sdb.execute(text("SELECT pg_try_advisory_xact_lock(:key)"),
                           {"key": _AI_KPI_LOCK}).scalar():
            return None  # 其他 worker 正在请求 AI，当前广告直接使用确定性兜底。
        key = _ai_retry_key(client)
        row = sdb.get(SystemSetting, key)
        if row and row.value:
            try:
                retry_after = float(json.loads(row.value)["retry_after"])
            except (ValueError, TypeError, KeyError):
                logger.warning("Invalid KPI AI retry state; retrying provider")
            else:
                if retry_after > time.time():
                    return None
        try:
            data = client.chat_json(messages, temperature=0.1, max_tokens=800)
        except AiError as exc:
            if exc.status == 429:
                value = json.dumps({"retry_after": time.time() + _AI_KPI_RETRY_SECONDS,
                                    "status": 429})
                if row:
                    row.value = value
                else:
                    sdb.add(SystemSetting(key=key, value=value))
                sdb.commit()
            raise
        if row:
            sdb.delete(row)
            sdb.commit()
        return data

# 辅助/上游字段（AI 应避免选择；L5 排除）—— 照 1.0 kpi_resolver
_AUXILIARY_FIELDS = {
    "messaging_welcome_message_view",
    "onsite_conversion.messaging_first_reply",
}
# 高优先级字段（防 AI 幻觉：AI 推辅助字段时替换为 actions 里有的高优先级）
_HIGH_PRIORITY_FIELDS = [
    "onsite_conversion.messaging_conversation_started_7d",
    "offsite_conversion.fb_pixel_purchase",
    "onsite_conversion.lead_grouped",
    "app_install",
]
# 劣质字段 + 标签已迁移到 kpi_mapping.py（DB 可配）。此处保留 _ai_correct_kpi 用的硬编码兜底。
_POOR_FALLBACK_TYPES = {
    "link_click", "view_content", "landing_page_view", "post_engagement", "page_engagement",
}
SOURCE_LABELS = {"manual": "手动", "rule": "规则", "ai": "AI", "fallback": "兜底", "default": "默认", "error": "错误"}


def _action_count(actions: list, field: str) -> int:
    for a in actions:
        if a.get("action_type") == field:
            try:
                return int(float(a.get("value", 0)))
            except Exception:
                return 0
    return 0


def _ai_correct_kpi(objective: str, opt_goal: str, actions: list) -> Optional[str]:
    """AI 纠偏（L1/L2）：规则推出辅助字段、或 L5 兜底时，AI 推断更准的 KPI 字段。
    用 AiClient（配置化，DeepSeek/OpenAI 兼容，换 key 改 .env 不动代码）。失败非致命返 None。
    照 1.0 kpi_resolver._l1_ai_sync（防幻觉：AI 推辅助字段→替换为 actions 里有的高优先级）。

    成功结果缓存 1h；429 的重试门控跨 worker 共享，避免每条广告重复请求失败服务。
    不缓存时 5min 一轮 × N 广告 = AI token 失控 + 60s 超时拖死巡检。"""
    client = AiClient()
    if not client.is_configured():
        return None
    cache_key = f"{_ai_retry_key(client)}|{(objective or '').upper()}|{(opt_goal or '').upper()}"
    now = time.time()
    hit = _AI_KPI_CACHE.get(cache_key)
    if hit and now - hit[1] < 3600:
        return hit[0]
    try:
        sorted_actions = sorted(actions, key=lambda x: float(x.get("value", 0)), reverse=True)[:15]
        actions_summary = "\n".join(f"  - {a.get('action_type')}: {a.get('value')}" for a in sorted_actions) or "  暂无数据"
        prompt = f"""你是 Facebook 广告 KPI 分析专家。判断该广告的核心 KPI 字段。

广告配置：
- 活动目标 (objective): {objective or '未知'}
- 优化目标 (optimization_goal): {opt_goal or '未知'}

近7日 Actions（按数量降序）：
{actions_summary}

判断规则：
1. 私信类选 onsite_conversion.messaging_conversation_started_7d
2. 电商/转化类选 offsite_conversion.fb_pixel_purchase
3. 线索类选 onsite_conversion.lead_grouped
4. 避免辅助字段（messaging_welcome_message_view, onsite_conversion.messaging_first_reply）和劣质字段（link_click/view_content/landing_page_view/post_engagement 等浏览互动类，它们不是真实转化）
5. 优先选数量最多的核心转化字段

只返回 JSON：{{"field": "字段名", "reason": "简短理由"}}"""
        data = _kpi_ai_json(client, [{"role": "user", "content": prompt}])
        if data is None:
            return None
        field = (data.get("field") or "").strip()
        if not field:
            return None
        # 防幻觉：AI 推辅助/劣质字段 → 替换为 actions 里有的高优先级
        if field in _AUXILIARY_FIELDS or field in _POOR_FALLBACK_TYPES:
            action_fields = {a.get("action_type") for a in actions}
            for hp in _HIGH_PRIORITY_FIELDS:
                if hp in action_fields:
                    _AI_KPI_CACHE[cache_key] = (hp, time.time())
                    return hp
            return None
        _AI_KPI_CACHE[cache_key] = (field, time.time())
        return field
    except Exception as e:
        logger.warning(f"AI KPI 纠偏失败（非致命）: {e}")
        return None


def resolve_kpi(db: Session, tenant_id: int, campaign_id: str, objective: str,
                opt_goal: str = "", actions: list | None = None) -> dict:
    """返回 {kpi_field, kpi_label, conversions, source, target_cpa}。

    L0 手动（kpi_configs）→ L4 矩阵（DB 映射，objective×opt_goal）→ L5 语义兜底（DB 映射）。
    映射配置从 system_settings['kpi_mapping'] 读（超管可编辑），fallback 硬编码默认。
    """
    from ..core.kpi_mapping import get_kpi_mapping, field_label, is_poor_fallback
    mapping = get_kpi_mapping(db)
    actions = actions or []
    obj = (objective or "").upper()
    og = (opt_goal or "").upper()

    # L0：手动配置（kpi_field + target_cpa）
    manual = None
    if campaign_id:
        manual = db.query(KpiConfig).filter(
            KpiConfig.tenant_id == tenant_id,
            KpiConfig.target_type == "campaign",
            KpiConfig.target_id == campaign_id,
            KpiConfig.enabled == True,  # noqa: E712
        ).first()
    target_cpa = (manual.target_cpa if manual and manual.target_cpa else None)

    if manual and manual.kpi_field:
        return {"kpi_field": manual.kpi_field, "kpi_label": field_label(manual.kpi_field, mapping),
                "conversions": _action_count(actions, manual.kpi_field),
                "source": "manual", "target_cpa": target_cpa}

    # L4：objective × opt_goal 矩阵（DB 映射）→ objective fallback（DB 映射）
    matrix = mapping.get("matrix", {})
    by_obj = mapping.get("by_objective", {})
    field = matrix.get(f"{obj}|{og}") or by_obj.get(obj)
    if field:
        # L1/L2 AI 纠偏：规则推出辅助字段时，AI 推断更准
        if field in _AUXILIARY_FIELDS:
            ai = _ai_correct_kpi(objective, opt_goal, actions)
            if ai:
                return {"kpi_field": ai, "kpi_label": field_label(ai, mapping),
                        "conversions": _action_count(actions, ai),
                        "source": "ai", "target_cpa": target_cpa}
        return {"kpi_field": field, "kpi_label": field_label(field, mapping),
                "conversions": _action_count(actions, field),
                "source": "rule", "target_cpa": target_cpa}

    # L5：语义兜底——找第一个非零 action（跳过劣质字段），AI 纠偏只调一次。
    # actions 只含本次 insights 返回的字段——L5 候选若不在 actions 里，计数必为 0，
    # 不能因此把 conversions 判 0（click_no_conv 误停）：L4 有 field 但 actions 缺时按 field 返回 0 计数，
    # L5 全 miss 时也返回 rule 字段而非空（调用方规则仍可判定"无数据"而非"零转化"）。
    poor_set = set(mapping.get("poor_fallback_types", []))
    first_hit = None
    for f in mapping.get("fallback_priority", []):
        if f in poor_set:
            continue
        cnt = _action_count(actions, f)
        if cnt > 0:
            first_hit = (f, cnt)
            break  # 只取第一个命中，不遍历后续
    if first_hit:
        f, cnt = first_hit
        ai = _ai_correct_kpi(objective, opt_goal, actions)
        if ai:
            return {"kpi_field": ai, "kpi_label": field_label(ai, mapping),
                    "conversions": _action_count(actions, ai),
                    "source": "ai", "target_cpa": target_cpa}
        return {"kpi_field": f, "kpi_label": field_label(f, mapping),
                "conversions": cnt, "source": "fallback",
                "target_cpa": target_cpa}
    # L5 无非零命中：若 L4 objective 维度有 field，退回它（计数 0 但字段可信，
    # 语义好过 kpi_field=""——规则层至少知道在盯什么）；否则真空。
    obj_fallback = by_obj.get(obj)
    if obj_fallback:
        return {"kpi_field": obj_fallback, "kpi_label": field_label(obj_fallback, mapping),
                "conversions": 0, "source": "rule", "target_cpa": target_cpa}
    return {"kpi_field": "", "kpi_label": "未知",
            "conversions": 0, "source": "default",
            "target_cpa": target_cpa}


def target_cpa_for(db: Session, tenant_id: int, campaign_id: str) -> Optional[float]:
    """取 campaign 的手动 target_cpa（cpa_exceed/consecutive_bad 用，无则 None→用规则自带）。"""
    if not campaign_id:
        return None
    r = db.query(KpiConfig).filter(
        KpiConfig.tenant_id == tenant_id,
        KpiConfig.target_type == "campaign",
        KpiConfig.target_id == campaign_id,
        KpiConfig.enabled == True,  # noqa: E712
    ).first()
    return (r.target_cpa if r and r.target_cpa else None)
