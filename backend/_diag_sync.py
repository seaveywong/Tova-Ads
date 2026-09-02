"""诊断 ads_cache 19 天未更新：cron 空转 vs 真挂。每查询独立 session 防 InFailedSqlTransaction。"""
from datetime import datetime, timezone
from sqlalchemy import text
from app.core.database import SuperSessionLocal


def q(sql):
    db = SuperSessionLocal()
    try:
        return db.execute(text(sql)).scalar()
    except Exception as e:
        return f"ERR {str(e)[:80]}"
    finally:
        db.close()


now = datetime.now(timezone.utc)
managed = q("SELECT count(*) FROM accounts WHERE is_managed = true")
managed_ok = q("SELECT count(*) FROM accounts WHERE is_managed = true AND account_status = 1")
print(f"纳管账户: {managed}（status=1 的: {managed_ok}）")

creds = q("SELECT count(*) FROM fb_credentials")
print(f"FB 凭证: {creds}")

tok = q("SELECT max(expires_at) FROM fb_credentials WHERE revoked_at IS NULL")
if hasattr(tok, "tzinfo") and tok:
    age_days = (now - tok).days
    print(f"凭证最晚过期时间: {tok}（{'已过期 ' + str(-age_days) + ' 天' if age_days < 0 else '剩余 ' + str(age_days) + ' 天'}）")

rows = q("SELECT count(*) FROM ads_cache")
print(f"ads_cache 行数: {rows}")

# 手动跑一次同步看实时行为（不改任何数据——同步本身是幂等 upsert）
from app.services.ads_cache_sync import run_ads_cache_sync
r = run_ads_cache_sync()
print(f"手动触发同步返回: {r}")
after = q("SELECT max(updated_at) FROM ads_cache")
print(f"同步后 ads_cache 最晚更新: {after}")
