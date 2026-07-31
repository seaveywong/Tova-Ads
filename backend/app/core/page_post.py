"""主页帖缓存 + 建帖（object_story_id 模式基础设施）。

dev app 不能用 object_story_spec（code3）→ 改为先建主页帖(/{page}/photos 或 /feed)拿 post_id，
再 creative 用 object_story_id 引用。本模块缓存"同页同素材同文案"的帖，避免重复建。

- 有 link（投放/购物，要落地页）→ /{page}/feed 链接帖（link + picture + message）
- 无 link（保活 Page Like）→ /{page}/photos 照片帖（url + message）
"""
import hashlib
from .fb_client import FbClient, FbApiError
from ..models.page_post import PagePost


def _body_hash(asset_id, message, link):
    h = hashlib.sha1()
    h.update(str(asset_id or "").encode()); h.update(b"|")
    h.update((message or "").encode()); h.update(b"|")
    h.update((link or "").encode())
    return h.hexdigest()


def get_or_create_page_post(db, fb: FbClient, tenant_id: int, page_id: str,
                            asset_id, message: str, link: str, image_url: str) -> str:
    """取或建该 (page, asset, message, link) 的主页帖 → 返 post_id（给 object_story_id 用）。

    同页同素材同文案复用一帖（page_posts 去重，body_hash=sha1(asset|message|link)）。
    需 fb（user token）能管该主页（get_page_access_token 拿得到 page token）。
    """
    bh = _body_hash(asset_id, message, link)
    existing = db.query(PagePost).filter(
        PagePost.tenant_id == tenant_id, PagePost.page_id == page_id, PagePost.body_hash == bh,
    ).first()
    if existing:
        return existing.post_id

    page_token = fb.get_page_access_token(page_id)
    if not page_token:
        raise FbApiError(f"拿不到主页 {page_id} 的 access token（令牌不管该页或缺 pages_manage_posts）", 0)
    pfb = FbClient(page_token)
    if link:
        # 链接帖（投放/保活：链接 + 文案；picture 在 /feed 会 invalid_param → 不传，FB 用链接 OG 图）
        r = pfb.post(f"{page_id}/feed", {"message": message or "", "link": link})
        post_id = r.get("id")
    else:
        # 照片帖（保活 Page Like：图 + 文案）
        r = pfb.post(f"{page_id}/photos", {"url": image_url, "message": message or "", "published": "true"})
        post_id = r.get("post_id") or r.get("id")
    if not post_id:
        raise FbApiError(f"建主页帖未返回 id：{str(r)[:200]}", 0)
    db.add(PagePost(tenant_id=tenant_id, page_id=page_id, post_id=post_id,
                    asset_id=asset_id, message=message, link=link, body_hash=bh))
    db.flush()
    return post_id
