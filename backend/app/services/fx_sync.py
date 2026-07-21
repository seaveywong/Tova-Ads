"""汇率同步：每日从开放 API 拉 USD→各币种实时汇率，upsert currency_rates。

CurrencyRate.rate 约定：1 USD = rate × 本币（如 VND=25400 = 1美元值25400越南盾）。
止损 to_usd 读这张表（替代硬编码字典，避免 VND/IDR 漂移致 $20 阈值误判）。

源：open.er-api.com（免费、无 key、稳定）。失败保留旧汇率（不覆盖成 0）。
"""
import logging
from datetime import datetime, timezone
import urllib.request, json

logger = logging.getLogger("toveads.fx")

# 关心的币种（覆盖投放地区 + 主要货币）；open.er-api.com 返回的是 {code: rate vs USD}
TARGET_CODES = [
    "USD", "VND", "IDR", "THB", "PHP", "MYR", "SGD", "TWD", "CNY", "HKD",
    "INR", "BRL", "MXN", "EUR", "GBP", "JPY", "KRW", "AUD", "CAD", "NZD",
]


def run_fx_sync() -> dict:
    """拉实时汇率 → upsert currency_rates。返回 {updated, skipped, source}。"""
    from ..core.database import SuperSessionLocal
    from ..models.perf import CurrencyRate
    try:
        req = urllib.request.Request("https://open.er-api.com/v6/latest/USD",
                                     headers={"User-Agent": "toveads-fx/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rates = data.get("rates") or {}
    except Exception as e:
        logger.warning(f"[FX] 拉汇率失败，保留旧汇率: {e}")
        return {"updated": 0, "skipped": 0, "error": str(e)[:80]}

    now = datetime.now(timezone.utc)
    db = SuperSessionLocal()
    updated, skipped = 0, 0
    try:
        existing = {r.code.upper(): r for r in db.query(CurrencyRate).all()}
        for code in TARGET_CODES:
            rate = rates.get(code)
            if rate is None or rate <= 0:
                skipped += 1
                continue
            cu = code.upper()
            if cu in existing:
                existing[cu].rate = float(rate)
                existing[cu].fetched_at = now
            else:
                db.add(CurrencyRate(code=cu, rate=float(rate), fetched_at=now))
            updated += 1
        db.commit()
        # 清 to_usd 缓存，下一轮巡检立刻用新汇率
        try:
            from .guard_engine import reset_fx_cache
            reset_fx_cache()
        except Exception:
            pass
    except Exception as e:
        db.rollback()
        logger.warning(f"[FX] upsert 失败: {e}")
        return {"updated": 0, "skipped": skipped, "error": str(e)[:80]}
    finally:
        db.close()
    logger.info(f"[FX] 汇率同步: 更新 {updated} 个币种, 跳过 {skipped}")
    return {"updated": updated, "skipped": skipped, "fetched_at": now.isoformat()}
