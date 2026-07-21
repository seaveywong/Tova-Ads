"""守护真停验证 v2：长等待读回（FB IN_PROCESS 需更长沉淀）。用完即删。"""
import sys, time
sys.path.insert(0, "/opt/toveads/backend")
from app.core.database import SuperSessionLocal
from app.core.encryption import decrypt
from app.core.fb_client import FbClient, FbApiError
from app.models.fb import FbCredential

AD_ID = "120249790508110363"

def read_status(fb):
    return fb.get(AD_ID, {"fields": "effective_status"}).get("effective_status")

def settle(fb, expect, tries=6, delay=8):
    """轮询直到 effective_status 进入期望态或稳定。"""
    last = None
    for i in range(tries):
        last = read_status(fb)
        if last == expect:
            return last, True
        time.sleep(delay)
    return last, False

def main():
    db = SuperSessionLocal()
    cred = db.query(FbCredential).filter(FbCredential.alias == "1111", FbCredential.status == "active").first()
    if not cred:
        print("NO_1111"); return
    fb = FbClient(decrypt(cred.access_token_enc))
    # 先等当前 IN_PROCESS 沉淀到 ACTIVE
    s, _ = settle(fb, "ACTIVE", tries=4, delay=8)
    print("settled_before:", s)
    # pause
    fb.pause_ad(AD_ID)
    print("pause call: ok")
    sp, ok_p = settle(fb, "PAUSED", tries=6, delay=8)
    print("after_pause:", sp, "reached_PAUSED:", ok_p)
    # resume
    fb.post(AD_ID, {"status": "ACTIVE"})
    print("resume call: ok")
    sr, ok_r = settle(fb, "ACTIVE", tries=6, delay=8)
    print("after_resume:", sr, "reached_ACTIVE:", ok_r)
    verdict = "PASS" if (ok_p and ok_r) else ("PASS_PAUSE_ONLY" if ok_p else "CHECK")
    print("VERDICT:", verdict)

if __name__ == "__main__":
    main()
