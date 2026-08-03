"""TikTok Events API S2S client —— 后端直发转化事件到 TK（绕广告拦截，配合浏览器 ttq 双发 + event_id 去重）。

核心约束：浏览器 ttq.track(evt, {event_id: uuid}) 和后端 S2S 必须用同一个 event_id（UUID），
否则 TK 重复计数。event_id 由 route_next 在 visit 时生成（单点真相在后端）。
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
