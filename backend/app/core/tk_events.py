"""S2S 转化事件发送层 —— TK Events API + FB Conversions API。

后端直发转化事件（绕广告拦截），配合浏览器端双发 + event_id 去重。
核心约束：浏览器端 fire（ttq.track(evt, {event_id}) / fbq('trackSingle', pid, evt, {eventID})）
和后端 S2S 必须用同一个 event_id（UUID），否则平台重复计数。event_id 由 route_next
在 visit 时生成（单点真相在后端），经 _d.eid 带到浏览器。FB 与 TK 共用同一 UUID：
各平台各自按 event_id 去重，跨平台共用无影响。
"""
import time
import httpx
import logging

logger = logging.getLogger(__name__)
TK_TRACK_URL = "https://business-api.tiktok.com/open_api/v1.3/event/track/"


class TkEventsClient:
    """单个 TK 像素的 S2S 事件发送。每次调用发一个事件。"""

    def __init__(self, pixel_code: str, access_token: str):
        self.pixel_code = pixel_code
        self.access_token = access_token

    def send(self, event: str, event_id: str, ttclid: str = "",
             test_event_code: str = "", currency: str = "", value: float = 0) -> dict:
        """发送一个 S2S 事件到 TK Events API。

        Args:
            event: TK 标准事件名（CompletePayment/SubmitForm/Contact 等）
            event_id: UUID——必须和浏览器 ttq.track 的 event_id 相同（去重）
            ttclid: TK 点击归因参数（从 URL 透传）
            test_event_code: 测试模式（事件进 Test Events 标签，不计生产）
            currency/value: 转化金额（可选）
        Returns:
            TK API 响应 dict
        """
        event_obj = {
            "event": event,
            "event_time": int(time.time()),
            "event_id": event_id,
        }
        # ttclid 归因（类比 FB fbc）
        if ttclid:
            event_obj["user"] = {"ttclid": ttclid}
            event_obj["context"] = {"ad": {"callback": ttclid}}
        if currency and value:
            event_obj["properties"] = {"currency": currency, "value": value}

        payload = {
            "pixel_code": self.pixel_code,
            "events": [event_obj],
        }
        if test_event_code:
            payload["test_event_code"] = test_event_code

        try:
            resp = httpx.post(
                TK_TRACK_URL,
                json=payload,
                headers={
                    "Access-Token": self.access_token,
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("code") == 0:
                logger.info(f"[TK S2S] {self.pixel_code} {event} event_id={event_id[:8]}… → OK")
            else:
                logger.warning(f"[TK S2S] {self.pixel_code} {event} → {data.get('code')}: {data.get('message', '')[:100]}")
            return data
        except Exception as e:
            logger.error(f"[TK S2S] {self.pixel_code} {event} → EXC {e}")
            return {"code": -1, "message": str(e)}


def send_tt_s2s_for_visit(db, tenant_id: int, tt_pixel_ids: list[str],
                          tt_conversion_events: list[str], event_id: str,
                          ttclid: str = "") -> list[dict]:
    """为一次访问的 TK 像素批量发 S2S 事件。
    遍历 tt_pixel_ids → 查 landing_pixels 找 token → 逐个发。
    无 token 的像素跳过（只靠浏览器端 fire）。
    Returns: 每个像素的 S2S 响应列表（失败也记）。
    """
    from ..models.landing_lib import LandingPixel
    from .encryption import decrypt
    results = []
    if not tt_pixel_ids or not tt_conversion_events:
        return results
    for pid in tt_pixel_ids:
        row = db.query(LandingPixel).filter(
            LandingPixel.tenant_id == tenant_id,
            LandingPixel.pixel_id == pid,
            LandingPixel.platform == "tt",
        ).first()
        if not row or not row.tt_access_token_enc:
            # 像素不在库或没配 token → 只靠浏览器端，不发 S2S
            continue
        try:
            token = decrypt(row.tt_access_token_enc)
        except Exception:
            continue
        client = TkEventsClient(pid, token)
        for evt in tt_conversion_events:
            r = client.send(event=evt, event_id=event_id, ttclid=ttclid)
            results.append({"pixel": pid, "event": evt, "result": r})
    return results


class FbCapiClient:
    """单个 FB 像素的 Conversions API 事件发送（POST /{pixel_id}/events）。"""

    def __init__(self, pixel_id: str, access_token: str):
        self.pixel_id = pixel_id
        self.access_token = access_token

    def send(self, event: str, event_id: str, test_event_code: str = "",
             currency: str = "", value: float = 0) -> dict:
        """发送一个 S2S 事件到 FB CAPI。

        Args:
            event: FB 标准事件名（Purchase/Contact/Lead/CompleteRegistration 等）——
                   必须与浏览器 fbq('trackSingle') fire 的事件名一致
                   （FB 按 event_id + event_name 双匹配去重）
            event_id: UUID——必须和浏览器 fbq trackSingle 的 eventID 相同（去重）
            test_event_code: 测试模式（事件进 Events Manager Test Events 标签，不计生产）
            currency/value: 转化金额（可选，进 custom_data）
        Returns:
            FB Graph API 响应 dict（成功含 events_received=1）
        """
        event_obj = {
            "event_name": event,
            "event_time": int(time.time()),
            "event_id": event_id,
            "action_source": "website",
        }
        if currency and value:
            event_obj["custom_data"] = {"currency": currency, "value": value}
        payload = {"data": [event_obj], "access_token": self.access_token}
        if test_event_code:
            payload["test_event_code"] = test_event_code

        from .fb_client import GRAPH_BASE  # 惰性导入：Graph 版本升级单点跟随 fb_client
        try:
            resp = httpx.post(f"{GRAPH_BASE}/{self.pixel_id}/events", json=payload, timeout=10)
            data = resp.json()
            if resp.status_code == 200 and data.get("events_received") == 1:
                logger.info(f"[FB CAPI] {self.pixel_id} {event} event_id={event_id[:8]}… → OK")
            else:
                _msg = (data.get("error") or {}).get("message", str(data))[:150]
                logger.warning(f"[FB CAPI] {self.pixel_id} {event} → {resp.status_code}: {_msg}")
            return data
        except Exception as e:
            logger.error(f"[FB CAPI] {self.pixel_id} {event} → EXC {e}")
            return {"error": {"message": str(e)}}


def send_s2s(platform: str, pixel_id: str, access_token: str, event: str, event_id: str,
             ttclid: str = "", test_event_code: str = "",
             currency: str = "", value: float = 0) -> dict:
    """通用 S2S 发送入口：按平台分发（tt → TikTok Events API，fb → FB Conversions API）。"""
    if platform == "tt":
        return TkEventsClient(pixel_id, access_token).send(
            event=event, event_id=event_id, ttclid=ttclid,
            test_event_code=test_event_code, currency=currency, value=value)
    if platform == "fb":
        return FbCapiClient(pixel_id, access_token).send(
            event=event, event_id=event_id,
            test_event_code=test_event_code, currency=currency, value=value)
    return {"error": {"message": f"unknown platform: {platform}"}}


def send_fb_capi_for_visit(db, tenant_id: int, fb_pixel_ids: list[str],
                           conversion_events: list[str], event_id: str) -> list[dict]:
    """为一次访问的 FB 像素批量发 CAPI 事件（灰度：仅 fb_capi_enabled=true 的像素发送）。

    遍历 fb_pixel_ids → 查 landing_pixels 复核灰度开关 → 解析 FB 令牌 → 逐事件发送。
    事件名直接用 conversion_events（与浏览器 fire 同名，去重按 event_id+event_name 双匹配）。
    FB 令牌解析：像素绑定账户(act_id)的 cred 优先（cred_for_account）；
    像素无 act_id（手填）或解析不到 → 回退租户任一 active cred；都没有则跳过该像素。
    Returns: 每个像素的 CAPI 响应列表（失败也记）。
    """
    from ..models.landing_lib import LandingPixel
    from ..models.fb import FbCredential
    from .encryption import decrypt
    results = []
    if not fb_pixel_ids or not conversion_events:
        return results
    for pid in fb_pixel_ids:
        row = db.query(LandingPixel).filter(
            LandingPixel.tenant_id == tenant_id,
            LandingPixel.pixel_id == pid,
            LandingPixel.platform == "fb",
        ).first()
        if not row or not row.fb_capi_enabled:
            # 灰度开关没开（或像素不在库）→ 只靠浏览器端，不发 S2S
            continue
        token = ""
        try:
            from .fb_tokens import cred_for_account
            cred = cred_for_account(db, tenant_id, row.act_id) if row.act_id else None
            if not cred:
                cred = db.query(FbCredential).filter(
                    FbCredential.tenant_id == tenant_id,
                    FbCredential.status == "active",
                ).first()
            if cred:
                token = decrypt(cred.access_token_enc)
        except Exception as e:
            logger.warning(f"[FB CAPI] {pid} 令牌解析失败: {e}")
        if not token:
            logger.warning(f"[FB CAPI] {pid} 无可用 FB 令牌，跳过 S2S（只靠浏览器端）")
            continue
        for evt in conversion_events:
            r = send_s2s("fb", pid, token, event=evt, event_id=event_id)
            results.append({"pixel": pid, "event": evt, "result": r})
    return results
