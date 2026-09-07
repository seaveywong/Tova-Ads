# 收尾盘点：令牌/账户/素材/落地页/模板/App secret 现状（投放前置检查）
from app.core.database import SuperSessionLocal
from app.models.fb import FbCredential, Account
from app.models.fb_app import FbApp
from app.models.launch import Asset, LandingPage
from app.models.launch_template import LaunchTemplate
from app.core.encryption import decrypt
from app.core.fb_client import FbClient

db = SuperSessionLocal()
try:
    print("== 令牌 ==")
    for c in db.query(FbCredential).order_by(FbCredential.id.desc()).limit(6).all():
        fb = FbClient(decrypt(c.access_token_enc))
        try:
            me = fb.get("me", {"fields": "id,name"})
            print(f"  cred#{c.id} {c.alias or me.get('name')}: ALIVE({me.get('name')}) status={c.status} cooldown_until={getattr(c,'cooldown_until',None)}")
        except Exception as e:
            print(f"  cred#{c.id} {c.alias}: {str(e)[:60]} status={c.status}")

    print("== 纳管账户（前10）==")
    accs = db.query(Account).filter(Account.is_managed == True, Account.platform != "tt").limit(10).all()
    for a in accs:
        print(f"  {a.act_id} {a.name} acc_status={a.account_status} cred_id={a.fb_credential_id}")
    print(f"  total managed(fb): {db.query(Account).filter(Account.is_managed == True, Account.platform != 'tt').count()}")

    print("== 素材 ==")
    for x in db.query(Asset).limit(5).all():
        print(f"  #{x.id} {x.name or x.filename} type={x.type} storage={'Y' if x.storage_key else 'N'}")

    print("== 已发布落地页 ==")
    for p in db.query(LandingPage).filter(LandingPage.status == "published").limit(5).all():
        print(f"  #{p.id} {p.name or p.slug} url={getattr(p, 'public_url', '') or ''}")

    print("== 投放模板 ==")
    for t in db.query(LaunchTemplate).limit(5).all():
        print(f"  #{t.id} {t.name} status={t.status} platform={t.platform} asset={t.asset_id} budget={t.daily_budget} landing={t.landing_url or t.landing_page_id}")

    print("== FB App secret 配置 ==")
    for a in db.query(FbApp).all():
        print(f"  app {a.app_id} secret={'已配' if a.app_secret_enc else '未配!'} status={a.status} access_level={getattr(a,'access_level',None)}")
finally:
    db.close()
