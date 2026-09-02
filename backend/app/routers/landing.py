"""落地页路由：发布到 CF Pages + 绑定超管导入的域名。

POST /landing/publish → 创建/更新 Pages 项目 → Direct Upload → 返回 URL
GET /landing/pages → 列已发布的落地页
"""
import os
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.config import settings
from ..core.i18n import req_locale, tenant_locale, L
from ..core.log_utils import write_log, new_trace_id
from pydantic import BaseModel

router = APIRouter(prefix="/landing", tags=["landing"])


# 机房/VPN ASN 拦截清单（平台级单一来源，前端下拉 + 新页默认 + 预设都读这里）
# 新页默认勾「屏蔽机房/VPN」时填这份；改这里 → 前端拉新清单 → 新页/重发页用最新。
DEFAULT_ASN_BLOCKLIST = [
    {"asn": "16509", "label": "AWS 亚马逊"}, {"asn": "14618", "label": "AWS(AES)"},
    {"asn": "15169", "label": "Google 云"}, {"asn": "396982", "label": "Google 云(2)"},
    {"asn": "8075", "label": "Microsoft Azure"}, {"asn": "14061", "label": "DigitalOcean"},
    {"asn": "20473", "label": "Vultr / Choopa"}, {"asn": "63949", "label": "Linode / Akamai"},
    {"asn": "16276", "label": "OVH"}, {"asn": "24940", "label": "Hetzner"},
    {"asn": "31898", "label": "Oracle 云"}, {"asn": "51167", "label": "Contabo"},
    {"asn": "60626", "label": "Leaseweb"}, {"asn": "9009", "label": "M247"},
    {"asn": "12876", "label": "Scaleway"}, {"asn": "45102", "label": "阿里云"},
    {"asn": "153371", "label": "BACK WAVES（VPN宿主）"}, {"asn": "134972", "label": "某 HK VPN 段"},
    {"asn": "32934", "label": "Facebook（爬虫）"},
]


@router.get("/asn-blocklist")
def get_asn_blocklist(user: CurrentUser = Depends(require_permission("landing.manage"))):
    """平台级机房/VPN ASN 清单（前端下拉 + 新页默认 + 「屏蔽机房/VPN」预设都读这里）。"""
    return {"asns": DEFAULT_ASN_BLOCKLIST}


# 默认落地页 HTML 模板（双模式适配：_d 解码 + 多转化 + 动态 target）
LANDING_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{TITLE}}</title>
<script>
!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;
n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,
document,'script','https://connect.facebook.net/en_US/fbevents.js');
var _d=new URLSearchParams(location.search).get('_d');var _info={};try{_info=JSON.parse(decodeURIComponent(escape(atob(_d))))}catch(e){}
var LP_PIXELS=(_info.p&&_info.p.length)?_info.p.split(',').filter(Boolean):(__LP_PIXELS_JSON__||[]);
var LP_TARGET_URL=_info.t||"__LP_TARGET_URL__";
var _rc=_info.c?_info.c.split(','):(__LP_CONV_EVENT_JSON__||[]);
var LP_CONV=(Array.isArray(_rc)?_rc:[_rc]).filter(Boolean);
var LP_TT_CONV=__LP_TT_CONV_JSON__||[];
var _eid=_info.eid||'';
LP_PIXELS.forEach(function(pid){if(pid){fbq('init',pid);fbq('trackSingle',pid,'PageView');}});
var LP_TT_PIXELS=(_d)?[]:(__LP_TT_PIXELS_JSON__||[]);if(LP_TT_PIXELS.length){!function(w,d,t){w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie"];ttq.setAndDefer=function(t,e){t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);ttq.load=function(e){var i="https://analytics.tiktok.com/i18n/pixel/events.js";ttq._i=ttq._i||{};ttq._i[e]=[];ttq._i[e]._u=i;ttq._t=ttq._t||{};ttq._t[e]=+new Date;ttq._o=ttq._o||{};ttq._o[e]={};var o=d.createElement("script");o.type="text/javascript";o.async=!0;o.src=i+"?sdkid="+e+"&lib="+t;var a=d.getElementsByTagName("script")[0];a.parentNode.insertBefore(o,a);};LP_TT_PIXELS.forEach(function(pid){if(pid)ttq.load(pid);});ttq.page();}(window,document,'ttq');}
</script>
</head>
<body style="margin:0;padding:0;font-family:sans-serif">
<div id="app" style="max-width:600px;margin:0 auto;padding:20px;text-align:center">
<h1>{{TITLE}}</h1>
<p>{{DESCRIPTION}}</p>
<a href="__LP_TARGET_URL__" id="cta" style="display:inline-block;padding:15px 40px;background:#0071e3;color:#fff;text-decoration:none;border-radius:8px;font-size:18px" onclick="return goNext(event)">立即购买</a>
</div>
<script>
function trackConversion(){if(window.fbq&&Array.isArray(LP_PIXELS)&&LP_CONV.length){LP_PIXELS.forEach(function(pid){if(!pid)return;LP_CONV.forEach(function(evt){fbq('trackSingle',pid,evt,_eid?{eventID:_eid}:undefined);});});}if(window.ttq&&Array.isArray(LP_TT_CONV)&&LP_TT_CONV.length){LP_TT_CONV.forEach(function(evt){ttq.track(evt);});}}
function goNext(ev){if(ev&&ev.preventDefault)ev.preventDefault();trackConversion();setTimeout(function(){window.location.href=LP_TARGET_URL;},300);return false;}
</script>
</body>
</html>
"""

# Worker 源码（常量，不含占位符；配置通过 JSON prepend 注入）
WORKER_SOURCE = r"""
function parseDev(u){u=(u||"").toLowerCase();let t="desktop";if(/ipad|tablet|playbook|silk/.test(u)||(/android/.test(u)&&!/mobile/.test(u)))t="tablet";else if(/mobile|iphone|ipod|android.*mobile|blackberry|opera mini/.test(u))t="mobile";return t;}
function matchAny(list,s){if(!Array.isArray(list)||!list.length)return false;s=(s||"").toLowerCase();return list.some(k=>s.includes(String(k).toLowerCase()));}
function evalProtection(request,url,cf){
  const rules=(LP_CONFIG.rules&&typeof LP_CONFIG.rules==="object")?LP_CONFIG.rules:{};
  const ua=request.headers.get("user-agent")||"";
  const referer=request.headers.get("referer")||"";
  const country=(cf.country||"").toUpperCase();
  const dev=parseDev(ua);
  const asn=String(cf.asn||"");
  // 内置爬虫拦截（无需用户手配 ua_block；FB/TK/Google/Bing 等爬虫一律挡）
  const _BOT_UA=["facebookexternalhit","facebot","meta-externalagent","googlebot","googleother","googleweblight","bingbot","baiduspider","bytespider","yandexbot","duckduckbot","applebot","twitterbot","linkedinbot","telegrambot","whatsapp","semrushbot","ahrefsbot","mj12bot","petalbot","slurp","crawler","spider","bot/","bot;"];
  const uaLow=ua.toLowerCase();
  for(const b of _BOT_UA){if(uaLow.includes(b)){return{blocked:true,reason:"crawler_block",country,device:dev,asn};}}
  const checks=[
    ["country_allow",()=>Array.isArray(rules.country_allow)&&rules.country_allow.length&&!rules.country_allow.map(c=>String(c).toUpperCase()).includes(country)],
    ["country_block",()=>Array.isArray(rules.country_block)&&rules.country_block.map(c=>String(c).toUpperCase()).includes(country)],
    ["device_block",()=>Array.isArray(rules.device_block)&&rules.device_block.includes(dev)],
    ["ua_block",()=>matchAny(rules.ua_block,ua)],
    ["referer_block",()=>matchAny(rules.referer_block,referer)],
    ["query_block",()=>matchAny(rules.query_block,url.search)],
    ["required_query",()=>Array.isArray(rules.required_query)&&rules.required_query.length&&!rules.required_query.some(k=>{const v=url.searchParams.get(k);return v&&!v.includes("{{");})],
    ["datacenter_block",()=>Array.isArray(rules.datacenter_block)&&rules.datacenter_block.length&&rules.datacenter_block.map(String).includes(asn)]
  ];
  for(const[name,fn]of checks){try{if(fn())return{blocked:true,reason:name,country,device:dev,asn};}catch(e){}}
  return{blocked:false};
}
function sendEvent(etype,data,ctx){
  try{ctx.waitUntil(fetch(LP_CONFIG.ingest_url,{method:"POST",headers:{"Content-Type":"application/json","X-Edge-Secret":LP_CONFIG.secret},body:JSON.stringify(Object.assign({event_type:etype},data))}).catch(()=>{}));}catch(e){}
}
export default{
  async fetch(request,env,ctx){
    const url=new URL(request.url);
    if(url.pathname==="/__health")return new Response("OK",{status:200});
    if(url.pathname==="/__events/ingest"){
      try{
        // 浏览器 click beacon 不带设备/地理（只有 event_type/slug/ad_id），
        // worker 从 cf + 请求头补全后再转发，让 click 事件也有真实设备/国家/ASN（否则后端 _parse_ua(空) 误判桌面）
        const _cf=request.cf||{};
        const _orig=JSON.parse(await request.text());
        const _enriched=Object.assign({country:_cf.country||"",city:_cf.city||"",asn:String(_cf.asn||""),user_agent:request.headers.get("user-agent")||"",ip:request.headers.get("CF-Connecting-IP")||""},_orig);
        const resp=await fetch(LP_CONFIG.ingest_url,{method:"POST",headers:{"Content-Type":"application/json","X-Edge-Secret":LP_CONFIG.secret},body:JSON.stringify(_enriched)});
        return new Response(await resp.text(),{status:resp.status});
      }catch(e){return new Response('{"ok":false}',{status:500});}
    }
    // 公共上下文先声明（防 TDZ：根路径分支也要用 _isPreview/cf/ua/ip，必须在引用前声明）
    const cf=request.cf||{};
    const ip=request.headers.get("CF-Connecting-IP")||"";
    const ua=request.headers.get("user-agent")||"";
    const _pv=url.searchParams.get("_pv");
    const _isPreview=LP_CONFIG.preview_enabled&&_pv&&LP_CONFIG.preview_token&&_pv===LP_CONFIG.preview_token;
    if(!url.pathname.startsWith("/a/")){
      // 非子码路径（根路径 / 等）：防护开启时也评估规则（防止直访绕过）
      const _hasD=url.searchParams.get("_d");
      const _isAsset=/\.(css|js|png|jpg|jpeg|gif|svg|ico|woff2?|ttf|map|webp|mp4)(\?|$)/i.test(url.pathname);
      if(LP_CONFIG.block_enabled&&!_isPreview&&!_hasD&&!_isAsset){
        const v2=evalProtection(request,url,cf);
        if(v2.blocked){
          sendEvent("block",{path:url.pathname,reason:"root_"+v2.reason,country:cf.country||"",asn:String(cf.asn||""),user_agent:ua,ip:ip},ctx);
          return Response.redirect(LP_CONFIG.rules.block_target||LP_CONFIG.block_target||"https://whatsapp.com",302);
        }
      }
      return env.ASSETS.fetch(request);
    }
    const slug=url.pathname.replace("/a/","").split("?")[0];
    const adId=url.searchParams.get("ad")||url.searchParams.get("ad_id")||"";
    const actId=url.searchParams.get("act")||url.searchParams.get("act_id")||"";
    const fbclid=url.searchParams.get("fbclid")||"";
    const referer=request.headers.get("referer")||"";
    const verdict=(LP_CONFIG.block_enabled&&!_isPreview)?evalProtection(request,url,cf):{blocked:false};
    if(verdict.blocked){
      sendEvent("block",{slug:slug,reason:verdict.reason,country:cf.country||"",city:cf.city||"",asn:String(cf.asn||""),referer:referer,user_agent:ua,ip:ip},ctx);
      return Response.redirect(LP_CONFIG.rules.block_target||LP_CONFIG.block_target||"https://whatsapp.com",302);
    }
    if(LP_CONFIG.rules.frequency&&LP_CONFIG.rules.frequency.max){
      try{
        const fr=await fetch(LP_CONFIG.frequency_url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({secret:LP_CONFIG.secret,ip:ip,max:LP_CONFIG.rules.frequency.max,window_min:LP_CONFIG.rules.frequency.window_min||60})});
        const fd=await fr.json();
        if(fd.exceeded){
          sendEvent("block",{slug:slug,reason:"frequency",country:cf.country||"",city:cf.city||"",asn:String(cf.asn||""),referer:referer,user_agent:ua,ip:ip},ctx);
          return Response.redirect(LP_CONFIG.rules.block_target||LP_CONFIG.block_target||"https://whatsapp.com",302);
        }
      }catch(e){}
    }
    if(LP_CONFIG.dedup_enabled&&!_isPreview){
      try{
        const drc=await fetch(LP_CONFIG.dedup_url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({secret:LP_CONFIG.secret,ip:ip})});
        const dd=await drc.json();
        if(dd.repeat){
          sendEvent("block",{slug:slug,reason:"dedup",country:cf.country||"",city:cf.city||"",asn:String(cf.asn||""),referer:referer,user_agent:ua,ip:ip},ctx);
          return Response.redirect(LP_CONFIG.rules.block_target||LP_CONFIG.block_target||"https://whatsapp.com",302);
        }
      }catch(e){}
    }
    if(LP_CONFIG.redirect_mode==="redirect"){
      sendEvent("redirect",{slug:slug,ad_id:adId,act_id:actId,fbclid:fbclid,target_url:LP_CONFIG.target,decision:"redirect",country:cf.country||"",city:cf.city||"",asn:String(cf.asn||""),referer:referer,user_agent:ua,ip:ip},ctx);
      const dest=new URL(LP_CONFIG.target);
      url.searchParams.forEach((v,k)=>{if(!k.startsWith("_")&&!dest.searchParams.has(k))dest.searchParams.set(k,v);});
      return Response.redirect(dest.toString(),302);
    }
    // display 模式：调 route_next 拿像素+目标 → 编码 _d → 302 到落地页
    let rd={};
    try{
      const rr=await fetch(LP_CONFIG.route_next_url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({secret:LP_CONFIG.secret,slug:slug,ad_id:adId,act_id:actId})});
      rd=await rr.json();
    }catch(e){rd={};}
    const _target=rd.target_url||LP_CONFIG.target;
    const _ttclid=new URL(request.url).searchParams.get("ttclid")||"";
    const _d=btoa(unescape(encodeURIComponent(JSON.stringify({p:(rd.pixel_ids||[]).join(","),tp:(rd.tt_pixel_ids||[]).join(","),tc:(rd.tt_conversion_events||[]).join(","),eid:(rd.tt_event_id||""),t:_target,c:(rd.conversion_events||[]).join(","),s:slug,a:adId,ai:actId}))));
    sendEvent("visit",{slug:slug,ad_id:adId,act_id:actId,fbclid:fbclid,pixel_ids:(rd.pixel_ids||[]).join(","),tt_pixel_ids:(rd.tt_pixel_ids||[]).join(","),tt_conversion_events:(rd.tt_conversion_events||[]).join(","),tt_event_id:(rd.tt_event_id||""),ttclid:_ttclid,target_url:_target,decision:"display",country:cf.country||"",city:cf.city||"",asn:String(cf.asn||""),referer:referer,user_agent:ua,ip:ip},ctx);
    const lp=new URL(request.url);
    lp.pathname="/";
    const q=new URLSearchParams();
    q.set("_d",_d);
    if(fbclid)q.set("fbclid",fbclid);
    lp.search="?"+q.toString();
    return Response.redirect(lp.toString(),302);
  }
};
"""




class PublishIn(BaseModel):
    title: str = ""
    description: str = "Our product"
    target_url: str = "https://tovaads.com"   # legacy 单值（兼容，target_urls 优先）
    target_urls: list[str] | None = None  # 多目标轮换；None=未传(legacy target_url 兜底)，[]=显式清空
    pixel_id: str = ""            # legacy 单像素
    pixel_ids: list[str] | None = None  # FB 多像素；None=未传(legacy pixel_id 兜底)，[]=显式清空
    tt_pixel_ids: list[str] | None = None  # TK 多像素；None=未传，[]=显式清空
    tt_conversion_events: list[str] | None = None  # TK 转化事件（CompletePayment/SubmitForm 等）；None=未传，[]=显式清空
    conversion_event: str = ""    # Purchase/Contact/Lead（空=只 PageView）
    protection_rules: dict | None = None  # 防护规则 10 key；None=未传，{}=显式清空
    template_id: int | None = None  # 落地页模板（zip 上传的；空=默认模板）
    project_name: str = "tovaads-landing"
    custom_domain: str = ""        # 兼容单域（custom_domains 优先）
    custom_domains: list[str] | None = None  # 多域名（一页绑多域）；None=未传，[]=显式清空
    rotation_mode: str = "first"  # first|random|sequential
    redirect_mode: str = "display"  # display=落地页模式 / redirect=跳转模式
    conversion_events: list[str] | None = None  # 多转化事件（CTA 点击 forEach fire，替代单 conversion_event）；None=未传，[]=显式清空
    block_enabled: bool = False    # 防护开关：false=不评估规则全放行
    preview_enabled: bool = False  # 预览开关：true=可用 ?_pv=<token> 跳过防护看真实页
    subdomain_prefix: str = ""     # 子域名前缀（空=默认 lp{id}）
    dedup_enabled: bool = False    # 防重复访客开关
    dedup_window_hours: int = 24   # 防重时间窗（小时）


def _pick_domain_from_lib(db: Session, tenant_id: int):
    """域名库回退：取该租户第一个 active 域名（发布时 custom_domain 未指定时用）。"""
    from ..models.landing_lib import LandingDomain
    d = db.query(LandingDomain).filter(
        LandingDomain.tenant_id == tenant_id, LandingDomain.status == "active"
    ).order_by(LandingDomain.id.desc()).first()
    return d.domain if d else None


def _domain_root(domain: str) -> str:
    """取根域（如 a.example.com → example.com），用于 CF zone 查找。"""
    if not domain:
        return ""
    host = domain.rstrip("/").split(":")[0].lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _page_meta_path(page_id) -> str:
    """页面 sidecar meta 路径：description 无 DB 列（只写进部署 HTML），
    发布时同步落此文件，供 GET /pages/{pid} 回显 + PUT 未填时保住现值。"""
    import os as _os
    return _os.path.join("/opt/toveads/worker-backups", f"tovaads-landing-{page_id}.meta.json")


def _read_page_description(page_id) -> str:
    """读页面当前生效描述（发布时写的 sidecar）；老页无文件/读失败返空串。"""
    import json as _json
    try:
        with open(_page_meta_path(page_id), "r", encoding="utf-8") as f:
            return ((_json.load(f) or {}).get("description") or "")
    except Exception:
        return ""


def _emit_landing_alert(project_name: str, msg: str, tenant_id: int = 1):
    """落地页 worker 异常告警（发布后 smoke 失败用）。"""
    try:
        from ..core.database import SuperSessionLocal
        from ..models.notify import Notification
        from datetime import datetime, timezone
        db = SuperSessionLocal()
        try:
            _loc = tenant_locale(db, tenant_id)
            db.add(Notification(tenant_id=tenant_id, level="critical", event_type="landing_worker_error",
                                title=L(_loc, "landing.workerError", project=project_name), body=msg,
                                created_at=datetime.now(timezone.utc)))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def _do_publish(db: Session, user: CurrentUser, body: PublishIn, existing=None, is_new: bool = False) -> dict:
    """CF 部署 + 落库。existing=更新(upsert)，None=新建。publish 与 PUT 共用。"""
    import json as _json, secrets as _secrets
    from ..core.cf_client import CfClient
    from ..models.launch import LandingPage

    cf_token = settings.cf_api_token
    cf_account = settings.cf_account_id
    if not cf_token or not cf_account:
        raise HTTPException(500, "CF API Token 或 Account ID 未配置")
    cf = CfClient(cf_token, cf_account)
    trace_id = new_trace_id()

    # 0. project_name 规范化：强制 tovaads-landing-{id} 前缀（防用户传任意名在平台 CF 账户建/撞项目）
    import re as _re
    if not _re.fullmatch(r"tovaads-landing-\d+", body.project_name or ""):
        body.project_name = f"tovaads-landing-{body.project_name}".replace("tovaads-landing-tovaads-landing-", "tovaads-landing-")
        if not _re.fullmatch(r"tovaads-landing-[a-z0-9-]+", body.project_name):
            raise HTTPException(400, "项目名仅允许小写字母/数字/连字符")

    # 1. 确保项目存在
    if not cf.get_project(body.project_name):
        cf.create_project(body.project_name)

    # 2. 构造文件（existing 则保留 ingest_secret，避免旧 Worker 失效）
    #    列表字段 None=未传（legacy 单值兜底）；[]=显式清空——必须保留空列表，否则 PUT 清空被静默吞掉
    pixels = body.pixel_ids if body.pixel_ids is not None else ([body.pixel_id] if body.pixel_id else [])
    targets = body.target_urls if body.target_urls is not None else ([body.target_url] if body.target_url else [])
    primary_target = targets[0] if targets else "https://tovaads.com"

    # 校验：防护开关开时必须有 block_target（worker 只实现跳转；block_html 从不渲染，配了也无效）
    if body.block_enabled:
        rules = body.protection_rules or {}
        if not rules.get("block_target"):
            if rules.get("block_html"):
                raise HTTPException(400, "当前版本屏蔽页 HTML 不生效，请填屏蔽跳转链接（block_target）")
            raise HTTPException(400, "防护已开启，必须配置屏蔽跳转链接（block_target）")
    ingest_secret = (existing.ingest_secret if existing and existing.ingest_secret
                     else _secrets.token_urlsafe(32))
    preview_token = (existing.preview_token if existing and existing.preview_token
                     else _secrets.token_urlsafe(48))
    preview_enabled = bool(body.preview_enabled)
    # 模板 HTML（template_id 用租户 zip 上传的，否则默认 LANDING_TEMPLATE）
    template_html = LANDING_TEMPLATE
    if body.template_id:
        from ..models.launch import LandingTemplate
        tpl = db.query(LandingTemplate).filter(
            LandingTemplate.id == body.template_id, LandingTemplate.tenant_id == user.tenant_id
        ).first()
        if tpl:
            template_html = tpl.html
    tt_pixels = body.tt_pixel_ids or []
    html = (template_html
            .replace("__LP_PIXELS_JSON__", _json.dumps(pixels))
            .replace("__LP_TT_PIXELS_JSON__", _json.dumps(tt_pixels))
            .replace("__LP_CONV_EVENT_JSON__", _json.dumps(body.conversion_events or []))
            .replace("__LP_TT_CONV_JSON__", _json.dumps(body.tt_conversion_events or []))
            .replace("__LP_TARGET_URL__", primary_target)
            .replace("{{TITLE}}", body.title)
            .replace("{{DESCRIPTION}}", body.description))
    # 注入 _d 解码脚本到 <head> 开头（FB 官方推荐位置，像素尽早加载；DOMContentLoaded 兜底按钮绑定）
    _d_decode = """<script>(function(){var _d=new URLSearchParams(location.search).get('_d');if(!_d)return;try{var info=JSON.parse(decodeURIComponent(escape(atob(_d))));var _pids=info.p?info.p.split(',').filter(Boolean):[];var _conv=info.c?info.c.split(',').filter(Boolean):[];if(!window.fbq){!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s);}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');}_pids.forEach(function(pid){fbq('init',pid);fbq('trackSingle',pid,'PageView');});if(info.t){try{if(typeof LP_TARGET_URL!=='undefined')LP_TARGET_URL=info.t;}catch(e){}window.__lp_target=info.t;}try{if(typeof LP_CONV!=='undefined')LP_CONV=_conv;}catch(e){}var _slug=info.s||'',_ad=info.a||'',_act=info.ai||'',_tgt=info.t||'',_eid=info.eid||'';function _lpClick(){_pids.forEach(function(pid){_conv.forEach(function(evt){fbq('trackSingle',pid,evt,_eid?{eventID:_eid}:undefined);});});try{navigator.sendBeacon('/__events/ingest',JSON.stringify({event_type:'click',slug:_slug,ad_id:_ad,act_id:_act,target_url:_tgt,decision:'click'}));}catch(e){}}document.addEventListener('click',function(e){var el=e.target.closest('[onclick*=\"goNext\"],#cta,a[href]');if(el){_lpClick();}},{capture:true,once:true});if(info.t){document.addEventListener('DOMContentLoaded',function(){var cta=document.getElementById('cta')||document.querySelector('[onclick*=\"goNext\"]');if(cta)cta.href=info.t;try{if(typeof LP_TARGET_URL!=='undefined')LP_TARGET_URL=info.t;}catch(e){}});}}catch(e){}})();</script>"""
    # TK 像素解码脚本（独立于 FB，从 _d.tp 读取 TK 像素并 fire ttq；event_id 从 _d.eid 取，和后端 S2S 同 UUID 去重）
    _d_decode_tt = """<script>(function(){var _d=new URLSearchParams(location.search).get('_d');if(!_d)return;try{var info=JSON.parse(decodeURIComponent(escape(atob(_d))));var _tpids=info.tp?info.tp.split(',').filter(Boolean):[];if(!_tpids.length)return;var _tconv=info.tc?info.tc.split(',').filter(Boolean):[];var _eid=info.eid||'';!function(w,d,t){w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie"];ttq.setAndDefer=function(t,e){t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);ttq.load=function(e){var i="https://analytics.tiktok.com/i18n/pixel/events.js";ttq._i=ttq._i||{};ttq._i[e]=[];ttq._i[e]._u=i;ttq._t=ttq._t||{};ttq._t[e]=+new Date;ttq._o=ttq._o||{};ttq._o[e]={};var o=d.createElement("script");o.type="text/javascript";o.async=!0;o.src=i+"?sdkid="+e+"&lib="+t;var a=d.getElementsByTagName("script")[0];a.parentNode.insertBefore(o,a);};_tpids.forEach(function(pid){ttq.load(pid);});ttq.page();}(window,document,'ttq');document.addEventListener('click',function(e){var el=e.target.closest('[onclick*=\"goNext\"],#cta,a[href]');if(el){try{var _props=_eid?{event_id:_eid}:{};if(_tconv.length){_tconv.forEach(function(evt){ttq.track(evt,_props);});}else{ttq.track('ClickButton',_props);}}catch(err){}}},{capture:true,once:true});}catch(e){}})();</script>"""
    _full_decode = _d_decode + _d_decode_tt
    if "<head" in html:
        html = re.sub(r"(<head[^>]*>)", r"\1" + _full_decode, html, count=1)
    elif "</body>" in html:
        html = html.replace("</body>", _full_decode + "\n</body>", 1)
    else:
        html = _full_decode + html
    # Worker 配置：JSON prepend（对齐 1.0 EDGE_CONFIG，不用占位符）
    _rules = body.protection_rules or {}
    _lp_config = {
        "secret": ingest_secret,
        "target": primary_target,
        "redirect_mode": body.redirect_mode or "display",
        "route_next_url": "https://api.tovaads.com/landing-pages/router/next",
        "block_enabled": bool(body.block_enabled),
        "block_target": _rules.get("block_target") or "https://whatsapp.com",
        "rules": _rules,
        "ingest_url": "https://api.tovaads.com/landing-pages/events/ingest",
        "frequency_url": "https://api.tovaads.com/landing-pages/frequency-check",
        "preview_enabled": bool(preview_enabled),
        "preview_token": preview_token or "",
        "dedup_enabled": bool(body.dedup_enabled),
        "dedup_url": "https://api.tovaads.com/landing-pages/dedup-check",
    }
    files = {
        "index.html": html,
        "_worker.js": "const LP_CONFIG = " + _json.dumps(_lp_config, ensure_ascii=False) + ";\n" + WORKER_SOURCE,
    }

    # 2.5 发布前 worker 校验门（语法 + 运行时 dry-run）——坏 worker 绝不上线
    #     防 $4000/referer 类事故：改坏 WORKER_SOURCE → 这里拦下，不部署。
    _worker_js = files["_worker.js"]
    import tempfile as _tf, os as _os, subprocess as _sp
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _check_script = _os.path.join(_here, "..", "_worker_check.mjs")  # landing.py 在 app/routers/，脚本在 app/
    with _tf.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as _tfh:
        _tfh.write(_worker_js)
        _worker_tmp = _tfh.name
    try:
        # 先语法门（快）：node --check
        _r1 = _sp.run(["node", "--check", _worker_tmp], capture_output=True, text=True, timeout=15)
        if _r1.returncode != 0:
            raise HTTPException(500, f"worker JS 语法错误，已拦截部署：\n{_r1.stderr[:500]}")
        # 再运行时门（dry-run 跑一遍 /a/ 请求，捕获 ReferenceError 等）
        if _os.path.exists(_check_script):
            _r2 = _sp.run(["node", _check_script, _worker_tmp], capture_output=True, text=True, timeout=20)
            if _r2.returncode != 0:
                raise HTTPException(500, f"worker 运行时错误，已拦截部署：\n{_r2.stderr[:600]}")
    finally:
        try: _os.unlink(_worker_tmp)
        except Exception: pass

    # 3. 部署（wrangler CLI）
    result = cf.deploy_via_wrangler(body.project_name, files)
    pages_url = result.get("url", f"https://{body.project_name}.pages.dev")
    deployment_id = result.get("id", "")

    # 3.5 发布后线上 smoke + 自动回滚
    #     curl 真实 /a/，非 302/200 = worker 异常 → 自动重发"上次正常"版本回滚 + critical 告警
    #     这样非技术用户发布出错也不会卡死线上（自动回到上个能用版）
    import os as _os2
    _backup_dir = "/opt/toveads/worker-backups"
    _backup_path = _os2.path.join(_backup_dir, f"{body.project_name}.js")
    _smoke_ok = False
    try:
        import subprocess as _sp2, time as _time2
        _time2.sleep(3)  # 等 CF 部署生效
        _smoke_url = f"https://{body.project_name}.pages.dev/a/__smoke__?ad=999999"
        _sr = _sp2.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                        "-A", "Mozilla/5.0 (Linux; Android 10) Chrome/120 Mobile", _smoke_url],
                       capture_output=True, text=True, timeout=15)
        _code = (_sr.stdout or "").strip()
        _smoke_ok = _code in ("200", "302")
        if not _smoke_ok:
            # 自动回滚：重发上次正常的 worker
            _rolled = False
            if _os2.path.exists(_backup_path):
                try:
                    with open(_backup_path, "r", encoding="utf-8") as _bf:
                        _old_worker = _bf.read()
                    cf.deploy_via_wrangler(body.project_name, {"index.html": html, "_worker.js": _old_worker})
                    _rolled = True
                except Exception as _re:
                    _emit_landing_alert(body.project_name, f"worker smoke 失败({_code})且回滚异常: {_re}", tenant_id=user.tenant_id)
            _emit_landing_alert(
                body.project_name,
                f"worker 发布后 smoke 失败（/a/ 返回 {_code}）。" + ("已自动回滚到上个正常版本，页面仍可用。" if _rolled else "无历史备份可回滚，请检查！"),
                tenant_id=user.tenant_id)
    except Exception:
        pass
    # smoke 通过 → 存当前 worker 为"上次正常"备份（下次回滚用）
    if _smoke_ok:
        try:
            _os2.makedirs(_backup_dir, exist_ok=True)
            with open(_backup_path, "w", encoding="utf-8") as _bf:
                _bf.write(files["_worker.js"])
        except Exception:
            pass

    # 3.6 描述 sidecar：description 只存在于部署 HTML（无 DB 列），落 meta.json 供编辑回显；
    #     PUT 未填描述时靠它保住现值，不再静默重置为默认文案
    try:
        import json as _json2
        _os2.makedirs(_backup_dir, exist_ok=True)
        with open(_page_meta_path(existing.id), "w", encoding="utf-8") as _mf:
            _json2.dump({"description": body.description or "Our product"}, _mf, ensure_ascii=False)
    except Exception:
        pass



    # 4. 绑域名（每页独立子域名 lp{page_id}.{根域}——封禁隔离 + URL 独立；
    #    custom_domains 是用户选的根域名，绑的是派生子域名）
    if body.custom_domains is not None:
        # 显式传了列表（含 []=清空域名）：不再兜底 custom_domain / 域名库
        roots = [d.rstrip("/") for d in body.custom_domains if d]
    else:
        roots = [body.custom_domain.rstrip("/")] if body.custom_domain else []
        if not roots:
            lib = _pick_domain_from_lib(db, user.tenant_id)
            if lib:
                roots = [lib]
    # 域名白名单校验：请求指定的每个根域必须属于本租户域名库（active）——
    # 否则可传平台域名/他租户域名到 get_zone_id 命中后绑定（跨租户接管/钓鱼载体）
    if roots:
        from ..models.landing_lib import LandingDomain as _LD
        allowed = {_domain_root(r.domain) for r in db.query(_LD).filter(
            _LD.tenant_id == user.tenant_id, _LD.status == "active").all()}
        bad = [_domain_root(r) for r in roots if _domain_root(r) not in allowed]
        if bad:
            raise HTTPException(400, f"域名不在本团队域名库中：{', '.join(sorted(set(bad)))}")
    bound = []
    sub_prefix = (body.subdomain_prefix or "").strip().lower()
    for root in roots:
        if not root:
            continue
        # 子域名 = 前缀.{根域}（自定义前缀优先，否则默认 lp{id}）
        prefix = sub_prefix or f"lp{existing.id}"
        sub = f"{prefix}.{_domain_root(root)}"
        # 冲突检查：子域名全局唯一（排除自己）
        clash = db.query(LandingPage).filter(
            LandingPage.custom_domain == f"https://{sub}",
            LandingPage.id != existing.id
        ).first()
        if clash:
            raise HTTPException(400, f"子域名 {sub} 已被「{clash.title}」占用，请换一个")
        try:
            if cf.get_zone_id(_domain_root(sub)):
                cf.bind_custom_domain(body.project_name, sub)
                bound.append(sub)
        except Exception:
            pass
    cd_clean = f"https://{bound[0]}" if bound else None
    # 多域名：合并已有 bound_subdomains + 新绑定的（不删旧的，用户手动管理）
    all_subs = set(bound)
    if existing and existing.bound_subdomains:
        try:
            old_subs = _json.loads(existing.bound_subdomains)
            all_subs.update(old_subs)
        except Exception:
            pass
    # 如果新前缀生成了新域名，确保也绑定到 CF（可能已在 all_subs 但未实际绑定）
    all_subs_list = sorted(all_subs)

    # 5. 落库（existing 更新 else 新建）+ 发布后自检。**用独立 SessionLocal 持久化**：
    #    主 session 在上面长 wrangler 部署（10-20s 子进程）后连接可能失效重连，丢 SET LOCAL
    #    app.tenant_id → RLS UPDATE 命中 0 行（预存"PUT 编辑落地页失败"bug 根因）。
    #    独立 session 强制新鲜连接 + 显式 SET LOCAL，绕开该坑。字段逻辑与原实现一致。
    from ..core.database import SessionLocal as _SLF
    from sqlalchemy import text as _text
    action = "create" if is_new else "update"
    page_id = existing.id if existing else None
    _fields = None
    if existing:
        _fields = {
            "title": body.title,
            "custom_domain": cd_clean or existing.custom_domain,
            # 列表/字典字段 is not None 语义：显式 []/{} 清空（存 "[]"/"{}"），None=未传保留现值
            "custom_domains": _json.dumps(roots) if body.custom_domains is not None else existing.custom_domains,
            "target_urls": _json.dumps(targets) if body.target_urls is not None else existing.target_urls,
            "rotation_mode": body.rotation_mode or existing.rotation_mode or "first",
            "pixel_id": body.pixel_id or existing.pixel_id,
            "pixel_ids": _json.dumps(pixels) if body.pixel_ids is not None else existing.pixel_ids,
            "tt_pixel_ids": _json.dumps(body.tt_pixel_ids) if body.tt_pixel_ids is not None else (existing.tt_pixel_ids or ""),
            "tt_conversion_events": _json.dumps(body.tt_conversion_events) if body.tt_conversion_events is not None else (existing.tt_conversion_events or ""),
            "conversion_event": body.conversion_event or existing.conversion_event,
            "protection_rules": _json.dumps(body.protection_rules) if body.protection_rules is not None else existing.protection_rules,
            "template_id": body.template_id,
            "redirect_mode": body.redirect_mode or existing.redirect_mode or "display",
            "conversion_events": _json.dumps(body.conversion_events) if body.conversion_events is not None else existing.conversion_events,
            "block_enabled": body.block_enabled,
            "ingest_secret": ingest_secret,  # 存量页更新也落 secret（否则 worker 带新 secret，DB 空→ingest 全 401）
            "preview_token": preview_token,
            "preview_enabled": preview_enabled,
            "subdomain_prefix": sub_prefix or existing.subdomain_prefix,
            "bound_subdomains": _json.dumps(all_subs_list),
            "dedup_enabled": bool(body.dedup_enabled),
            "dedup_window_hours": body.dedup_window_hours or 24,
            "status": "published",
        }
    publish_self_check = None
    _s2 = _SLF()
    try:
        _s2.execute(_text("SET LOCAL app.tenant_id = :tid"), {"tid": str(user.tenant_id)})
        _s2.execute(_text("SET LOCAL app.is_superadmin = :s"), {"s": "true" if user.is_superadmin else "false"})
        if existing:
            page = _s2.query(LandingPage).filter(LandingPage.id == page_id).first()
            for _k, _v in _fields.items():
                setattr(page, _k, _v)
        else:
            page = LandingPage(
                tenant_id=user.tenant_id, owner_user_id=user.id, title=body.title,
                custom_domain=cd_clean,
                custom_domains=_json.dumps(roots) if roots else None,
                target_urls=_json.dumps(targets),
                rotation_mode=body.rotation_mode or "first",
                pixel_id=body.pixel_id or None,
                pixel_ids=_json.dumps(pixels) if pixels else None,
                conversion_event=body.conversion_event or None,
                conversion_events=_json.dumps(body.conversion_events) if body.conversion_events else None,
                redirect_mode=body.redirect_mode or "display",
                block_enabled=body.block_enabled,
                preview_token=preview_token,
                preview_enabled=preview_enabled,
                subdomain_prefix=sub_prefix or None,
                bound_subdomains=_json.dumps(all_subs_list),
                dedup_enabled=bool(body.dedup_enabled),
                dedup_window_hours=body.dedup_window_hours or 24,
                ingest_secret=ingest_secret,
                protection_rules=_json.dumps(body.protection_rules) if body.protection_rules else None,
                template_id=body.template_id,
                status="published",
            )
            _s2.add(page)
        write_log(_s2, tenant_id=user.tenant_id, trace_id=trace_id,
                  actor_type="user", actor_user_id=user.id,
                  target_type="landing_page", target_id=body.project_name,
                  action_type=action, source="cf_api", result="success",
                  metadata={"pages_url": pages_url, "deployment_id": deployment_id,
                            "custom_domain": cd_clean, "custom_domains": roots, "subdomains": bound})
        _s2.commit()
        page_id = page.id  # 新建页 commit 后拿 id；存量页本就有
        # 6. 发布后自动自检（配置项矩阵：像素/目标/防护/预览，跳过实时 curl+FB 避免 CF 传播期误报+拖慢）。
        #    commit 后 SET LOCAL 已清（事务级），重设跑自检。自检是 best-effort（失败不阻断发布）。
        try:
            from datetime import datetime as _dt3, timezone as _tz3
            _s2.execute(_text("SET LOCAL app.tenant_id = :tid"), {"tid": str(user.tenant_id)})
            _s2.execute(_text("SET LOCAL app.is_superadmin = :s"), {"s": "true" if user.is_superadmin else "false"})
            publish_self_check = _run_self_check(_s2, page, include_fb=False, live_probe=False, loc=getattr(user, "locale", "zh"))
            page.last_health_status = publish_self_check["overall"]
            page.last_health_summary = publish_self_check["summary"]
            page.last_health_checked_at = _dt3.now(_tz3.utc)
            _emit_health_alert(_s2, page, publish_self_check)
            _s2.commit()
        except Exception:
            try:
                _s2.rollback()
            except Exception:
                pass
    finally:
        _s2.close()
    return {"status": "published", "pages_url": pages_url,
            "custom_domain": cd_clean, "custom_domains": roots, "subdomains": bound,
            "deployment_id": deployment_id, "trace_id": trace_id, "id": page_id,
            "self_check": publish_self_check}


@router.post("/publish")
def publish_landing(
    body: PublishIn,
    user: CurrentUser = Depends(require_permission("landing.manage")),
    db: Session = Depends(get_db),
):
    """发布落地页（upsert：同租户同标题=更新，否则新建；每页独立 CF 项目 tovaads-landing-{id}）。"""
    from ..models.launch import LandingPage
    existing = db.query(LandingPage).filter(
        LandingPage.tenant_id == user.tenant_id, LandingPage.title == body.title
    ).first()
    is_new = not existing  # 本次是否首次发布（决定 action_log 记 create 还是 update）
    if not existing:
        existing = LandingPage(tenant_id=user.tenant_id, owner_user_id=user.id,
                               title=body.title, status="draft")
        db.add(existing); db.flush()  # 拿 id → 定唯一 project_name
        db.commit()  # 提交 draft：_do_publish 用独立 session 更新时跨事务要能看到该行（否则不可见→回退主db路径）
    body.project_name = f"tovaads-landing-{existing.id}"
    try:
        return _do_publish(db, user, body, existing=existing, is_new=is_new)
    except HTTPException:
        db.rollback()
        # 新建发布失败 → 删幽灵 draft 行（列表不留未部署坏页；重发走全新建路径）
        if is_new:
            try:
                db.query(LandingPage).filter(LandingPage.id == existing.id).delete()
                db.commit()
            except Exception:
                db.rollback()
        raise
    except Exception as e:
        db.rollback()
        if is_new:
            try:
                db.query(LandingPage).filter(LandingPage.id == existing.id).delete()
                db.commit()
            except Exception:
                db.rollback()
        write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(),
                  actor_type="user", actor_user_id=user.id,
                  target_type="landing_page", action_type="create",
                  source="cf_api", result="fail", friendly_error=str(e))
        db.commit()
        raise HTTPException(500, f"发布失败: {e}")


@router.get("/projects")
def list_cf_projects(
    user: CurrentUser = Depends(require_permission("landing.manage")),
    db: Session = Depends(get_db),
):
    """列 CF Pages 项目——只返回本租户落地页对应的 CF 项目（原返回全平台项目+全部域名）。

    CF 项目名发布时按 tovaads-landing-{页id} 规范生成（页记录无 project_name 列，按 id 推导）。
    domains 剥掉：那是 CF 侧项目级信息，含其他租户绑定的域名。"""
    from ..core.cf_client import CfClient
    from ..models.launch import LandingPage as _LP
    cf_token = settings.cf_api_token
    cf_account = settings.cf_account_id
    if not cf_token or not cf_account:
        raise HTTPException(500, "CF 未配置")
    my_names = {f"tovaads-landing-{r.id}" for r in db.query(_LP.id).filter(
        _LP.tenant_id == user.tenant_id).all()}
    cf = CfClient(cf_token, cf_account)
    projects = cf.list_projects()
    return [{"name": p.get("name"), "subdomain": p.get("subdomain")}
            for p in projects if p.get("name") in my_names]


# ── 落地页记录 CRUD（Phase A：列表/详情/改/归档）──
class PageUpdateIn(BaseModel):
    title: str | None = None
    description: str | None = None
    target_urls: list[str] | None = None
    pixel_ids: list[str] | None = None
    tt_pixel_ids: list[str] | None = None
    tt_conversion_events: list[str] | None = None
    conversion_event: str | None = None
    protection_rules: dict | None = None
    custom_domain: str | None = None
    custom_domains: list[str] | None = None
    rotation_mode: str | None = None
    redirect_mode: str | None = None
    conversion_events: list[str] | None = None
    block_enabled: bool | None = None
    preview_enabled: bool | None = None
    template_id: int | None = None
    subdomain_prefix: str | None = None
    dedup_enabled: bool | None = None
    dedup_window_hours: int | None = None


def _page_to_dict(p, db: Session = None, stats: dict = None) -> dict:
    """stats（列表调用方可传）= {"sub_counts": {pid: n}, "event_counts": {(pid, event_type): n}}
    —— 批量预取，替代每页 4 条 COUNT（N+1）；单页调用不传则逐项查（原行为）。"""
    import json as _json
    from ..models.launch import LandingAdLink
    ids, rules, targets = [], {}, []
    try:
        if p.pixel_ids: ids = _json.loads(p.pixel_ids)
    except Exception:
        pass
    try:
        if p.protection_rules: rules = _json.loads(p.protection_rules)
    except Exception:
        pass
    try:
        if p.target_urls: targets = _json.loads(p.target_urls)
    except Exception:
        targets = []
    sub_count = 0
    if stats is not None:
        sub_count = stats["sub_counts"].get(p.id, 0)
    elif db is not None:
        sub_count = db.query(LandingAdLink).filter(
            LandingAdLink.page_id == p.id, LandingAdLink.status != "archived"
        ).count()
    cd_list = []
    try:
        if p.custom_domains: cd_list = _json.loads(p.custom_domains)
    except Exception:
        cd_list = [p.custom_domain] if p.custom_domain else []
    conv_events = []
    try:
        if p.conversion_events: conv_events = _json.loads(p.conversion_events)
    except Exception:
        pass
    if not conv_events and p.conversion_event:
        conv_events = [p.conversion_event]
    tt_ids, tt_conv = [], []
    try:
        if p.tt_pixel_ids: tt_ids = _json.loads(p.tt_pixel_ids)
    except Exception:
        pass
    try:
        if p.tt_conversion_events: tt_conv = _json.loads(p.tt_conversion_events)
    except Exception:
        pass
    bound_subs = []
    try:
        if p.bound_subdomains: bound_subs = _json.loads(p.bound_subdomains)
    except Exception:
        pass
    # 兜底：如果 bound_subdomains 为空但 custom_domain 有值，用它
    if not bound_subs and p.custom_domain:
        host = p.custom_domain.split("://", 1)[-1].split("/")[0]
        if host:
            bound_subs = [host]
    # 公开 URL（custom_domain 存的是子域名公开地址）+ 预览 URL（?_pv=token 跳过防护）
    pub_host = ""
    if p.custom_domain:
        pub_host = p.custom_domain.split("://", 1)[-1].split("/")[0]
    preview_url = (f"https://{pub_host}/?_pv={p.preview_token}"
                   if (p.preview_enabled and p.preview_token and pub_host) else "")
    visit_count = click_count = block_count = 0
    if stats is not None:
        ec = stats["event_counts"]
        visit_count = ec.get((p.id, "visit"), 0)
        click_count = ec.get((p.id, "click"), 0) + ec.get((p.id, "submit"), 0)
        block_count = ec.get((p.id, "block"), 0)
    elif db is not None:
        try:
            from ..models.landing_event import LandingEvent
            visit_count = db.query(LandingEvent).filter(LandingEvent.page_id == p.id, LandingEvent.event_type == "visit").count()
            click_count = db.query(LandingEvent).filter(LandingEvent.page_id == p.id, LandingEvent.event_type.in_(["click", "submit"])).count()
            block_count = db.query(LandingEvent).filter(LandingEvent.page_id == p.id, LandingEvent.event_type == "block").count()
        except Exception:
            pass
    pass_rate = round(click_count / visit_count * 100, 1) if visit_count else 0
    return {"id": p.id, "title": p.title, "status": p.status,
            "public_url": p.custom_domain or "",
            "custom_domain": p.custom_domain, "custom_domains": cd_list,
            "target_urls": targets,
            "rotation_mode": p.rotation_mode, "pixel_ids": ids,
            "tt_pixel_ids": tt_ids,
            "pixel_id": p.pixel_id, "conversion_event": p.conversion_event,
            "conversion_events": conv_events, "tt_conversion_events": tt_conv,
            "redirect_mode": p.redirect_mode or "display",
            "block_enabled": bool(p.block_enabled),
            "preview_enabled": bool(p.preview_enabled), "preview_url": preview_url,
            "preview_token": p.preview_token or "",
            "subdomain_prefix": p.subdomain_prefix or "",
            "bound_subdomains": bound_subs,
            "dedup_enabled": bool(p.dedup_enabled), "dedup_window_hours": p.dedup_window_hours or 24,
            "protection_rules": rules, "ingest_secret": p.ingest_secret, "template_id": p.template_id,
            "subcode_count": sub_count, "created_at": str(p.created_at or ""),
            "last_health_status": p.last_health_status,
            "last_health_summary": p.last_health_summary,
            "last_health_checked_at": str(p.last_health_checked_at or ""),
            "last_fb_status": p.last_fb_status,          # FB屏蔽探测 pass/fail/warn（fail=被屏，看板红标）
            "last_fb_checked_at": str(p.last_fb_checked_at or ""),
            "visit_count": visit_count, "click_count": click_count,
            "block_count": block_count, "pass_rate": pass_rate}


@router.get("/pages")
def list_landing_pages(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """列本租户落地页（status != archived），附 subcode_count。"""
    from ..models.launch import LandingPage, LandingAdLink
    from ..models.landing_event import LandingEvent
    from sqlalchemy import func as _f
    rows = db.query(LandingPage).filter(
        LandingPage.tenant_id == user.tenant_id, LandingPage.status != "archived"
    ).order_by(LandingPage.id.desc()).all()
    # 计数批量预取（原每页 4 条 COUNT = N+1）
    pids = [p.id for p in rows]
    sub_counts, event_counts = {}, {}
    if pids:
        sub_counts = dict(db.query(
            LandingAdLink.page_id, _f.count(LandingAdLink.id)
        ).filter(
            LandingAdLink.page_id.in_(pids), LandingAdLink.status != "archived"
        ).group_by(LandingAdLink.page_id).all())
        event_counts = {
            (pid_, et): c for pid_, et, c in db.query(
                LandingEvent.page_id, LandingEvent.event_type, _f.count(LandingEvent.id)
            ).filter(
                LandingEvent.page_id.in_(pids),
                LandingEvent.event_type.in_(["visit", "click", "submit", "block"]),
            ).group_by(LandingEvent.page_id, LandingEvent.event_type).all()
        }
    stats = {"sub_counts": sub_counts, "event_counts": event_counts}
    return [_page_to_dict(p, db, stats) for p in rows]


@router.get("/pages/{pid}")
def get_landing_page(
    pid: int,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """单条详情 + 关联子码列表。"""
    from ..models.launch import LandingPage, LandingAdLink
    p = db.query(LandingPage).filter(
        LandingPage.id == pid, LandingPage.tenant_id == user.tenant_id
    ).first()
    if not p:
        raise HTTPException(404, "落地页不存在")
    d = _page_to_dict(p, db)
    d["description"] = _read_page_description(pid)
    subs = db.query(LandingAdLink).filter(
        LandingAdLink.page_id == pid, LandingAdLink.status != "archived"
    ).order_by(LandingAdLink.id.desc()).all()
    d["subcodes"] = [{"id": s.id, "slug": s.slug, "url": f"/a/{s.slug}",
                      "ad_id": s.ad_id, "act_id": s.act_id, "status": s.status,
                      "target_urls": s.target_urls or ""} for s in subs]
    return d


@router.put("/pages/{pid}")
def update_landing_page(
    pid: int,
    body: PageUpdateIn,
    user: CurrentUser = Depends(require_permission("landing.manage")),
    db: Session = Depends(get_db),
):
    """改落地页（资产字段变更→触发重新部署；Phase A 统一重发，Phase C 再分运行时/资产）。"""
    import json as _json
    from ..models.launch import LandingPage
    p = db.query(LandingPage).filter(
        LandingPage.id == pid, LandingPage.tenant_id == user.tenant_id
    ).first()
    if not p:
        raise HTTPException(404, "落地页不存在")
    cur_targets = []
    try:
        cur_targets = _json.loads(p.target_urls) if p.target_urls else []
    except Exception:
        cur_targets = [p.target_urls] if p.target_urls else []
    cur_pixels = []
    try:
        cur_pixels = _json.loads(p.pixel_ids) if p.pixel_ids else ([p.pixel_id] if p.pixel_id else [])
    except Exception:
        pass
    cur_rules = {}
    try:
        cur_rules = _json.loads(p.protection_rules) if p.protection_rules else {}
    except Exception:
        pass
    cur_domains = []
    try:
        cur_domains = _json.loads(p.custom_domains) if p.custom_domains else ([p.custom_domain] if p.custom_domain else [])
    except Exception:
        cur_domains = [p.custom_domain] if p.custom_domain else []
    pub = PublishIn(
        title=body.title if body.title is not None else p.title,
        # 未填描述=保住当前生效值（sidecar），不再静默重置为 "Our product"
        description=(body.description if (body.description or "").strip()
                     else (_read_page_description(p.id) or "Our product")),
        target_url=cur_targets[0] if cur_targets else "https://tovaads.com",
        target_urls=body.target_urls if body.target_urls is not None else cur_targets,
        pixel_id=p.pixel_id or "",
        pixel_ids=body.pixel_ids if body.pixel_ids is not None else cur_pixels,
        tt_pixel_ids=body.tt_pixel_ids if body.tt_pixel_ids is not None else (_json.loads(p.tt_pixel_ids) if p.tt_pixel_ids else []),
        tt_conversion_events=body.tt_conversion_events if body.tt_conversion_events is not None else (_json.loads(p.tt_conversion_events) if p.tt_conversion_events else []),
        conversion_event=body.conversion_event if body.conversion_event is not None else (p.conversion_event or ""),
        conversion_events=body.conversion_events if body.conversion_events is not None else (_json.loads(p.conversion_events) if p.conversion_events else ([p.conversion_event] if p.conversion_event else [])),
        redirect_mode=body.redirect_mode if body.redirect_mode is not None else (p.redirect_mode or "display"),
        block_enabled=body.block_enabled if body.block_enabled is not None else bool(p.block_enabled),
        preview_enabled=body.preview_enabled if body.preview_enabled is not None else bool(p.preview_enabled),
        protection_rules=body.protection_rules if body.protection_rules is not None else cur_rules,
        project_name=f"tovaads-landing-{p.id}",
        custom_domain=body.custom_domain if body.custom_domain is not None else (p.custom_domain or ""),
        custom_domains=body.custom_domains if body.custom_domains is not None else cur_domains,
        rotation_mode=body.rotation_mode if body.rotation_mode is not None else (p.rotation_mode or "first"),
        template_id=body.template_id if body.template_id is not None else p.template_id,
        subdomain_prefix=body.subdomain_prefix if body.subdomain_prefix is not None else (p.subdomain_prefix or ""),
        dedup_enabled=body.dedup_enabled if body.dedup_enabled is not None else bool(p.dedup_enabled),
        dedup_window_hours=body.dedup_window_hours if body.dedup_window_hours is not None else (p.dedup_window_hours or 24),
    )
    try:
        return _do_publish(db, user, pub, existing=p)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        raise HTTPException(500, f"更新失败: {e}")


@router.delete("/pages/{pid}")
def archive_landing_page(
    pid: int,
    user: CurrentUser = Depends(require_permission("landing.manage")),
    db: Session = Depends(get_db),
):
    """归档落地页（软删 status=archived，保留历史；CF 项目不解绑）。"""
    from ..models.launch import LandingPage
    p = db.query(LandingPage).filter(
        LandingPage.id == pid, LandingPage.tenant_id == user.tenant_id
    ).first()
    if not p:
        raise HTTPException(404, "落地页不存在")
    p.status = "archived"
    write_log(db, tenant_id=user.tenant_id, trace_id=new_trace_id(),
              actor_type="user", actor_user_id=user.id,
              target_type="landing_page", target_id=str(pid),
              action_type="archive", source="user", result="success")
    db.commit()
    return {"id": pid, "status": "archived"}


# ── 落地页自检（健康检查 + 防护测试）──
def _eval_protection_py(rules, ua="", country="", referer="", query=""):
    """Python 版防护评估（1:1 对齐 Worker evalProtection 检查顺序）。"""
    if not rules or not isinstance(rules, dict) or not rules:
        return {"blocked": False, "reason": ""}
    u = (ua or "").lower()
    ref = (referer or "").lower()
    q = (query or "").lower()
    # device
    dev_type = "desktop"
    if "/mobile/iphone/ipod/android.*mobile/blackberry/opera mini/".find(u) >= 0 or any(k in u for k in ["mobile", "iphone", "ipod"]):
        dev_type = "mobile"
    elif any(k in u for k in ["ipad", "tablet", "playbook", "silk"]) or ("android" in u and "mobile" not in u):
        dev_type = "tablet"
    # source
    src = ""
    if any(k in ref for k in ["facebook", "fb.com", "m.me"]): src = "facebook"
    elif "instagram" in ref: src = "instagram"
    elif "google" in ref: src = "google"
    elif "tiktok" in ref: src = "tiktok"
    elif ref: src = "other"

    def _list_hit(lst, s):
        if not isinstance(lst, list) or not lst: return False
        return any(str(k).lower() in (s or "").lower() for k in lst)

    checks = [
        ("country_allow", isinstance(rules.get("country_allow"), list) and len(rules["country_allow"]) and country not in rules["country_allow"]),
        ("country_block", isinstance(rules.get("country_block"), list) and country in rules.get("country_block", [])),
        ("source_allow", isinstance(rules.get("source_allow"), list) and len(rules["source_allow"]) and src not in rules["source_allow"]),
        ("source_block", isinstance(rules.get("source_block"), list) and src in rules.get("source_block", [])),
        ("device_block", isinstance(rules.get("device_block"), list) and dev_type in rules.get("device_block", [])),
        ("ua_block", _list_hit(rules.get("ua_block"), ua)),
        ("referer_block", _list_hit(rules.get("referer_block"), referer)),
        ("query_block", _list_hit(rules.get("query_block"), query)),
    ]
    for name, hit in checks:
        if hit: return {"blocked": True, "reason": name}
    return {"blocked": False, "reason": ""}


_PROTECTION_PROFILES = [
    {"label": "桌面浏览器（美国）", "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0", "country": "US", "referer": "", "query": ""},
    {"label": "移动端（美国）", "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4) Safari/605.1", "country": "US", "referer": "", "query": ""},
    {"label": "Googlebot 爬虫", "ua": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", "country": "US", "referer": "", "query": ""},
    {"label": "非允许国（中国）", "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0", "country": "CN", "referer": "", "query": ""},
    {"label": "带调试参数", "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4) Safari/605.1", "country": "US", "referer": "", "query": "?preview=1"},
    {"label": "调试来源 Referer", "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4) Safari/605.1", "country": "US", "referer": "https://debug.example.com/preview", "query": ""},
]


@router.post("/protection-test")
def protection_test(
    body: dict,
    request: Request,
    user: CurrentUser = Depends(require_permission("ads.read")),
):
    """防护规则测试：6 类画像本地模拟（0 网络开销，瞬时返回）。"""
    loc = req_locale(request)
    # profile label → i18n code（_PROTECTION_PROFILES 顺序固定：桌面/移动/Googlebot/非允许国/调试参数/调试来源）
    _label_codes = [
        "landing.protSampleDesktop", "landing.protSampleMobile", "landing.protSampleGooglebot",
        "landing.protSampleBlockedCountry", "landing.protSampleDebugQuery", "landing.protSampleDebugReferer",
    ]
    rules = body.get("rules") or {}
    results = []
    for idx, p in enumerate(_PROTECTION_PROFILES):
        v = _eval_protection_py(rules, ua=p["ua"], country=p["country"], referer=p["referer"], query=p["query"])
        results.append({"label": L(loc, _label_codes[idx]), "blocked": v["blocked"], "reason": v["reason"]})
    blocked_count = sum(1 for r in results if r["blocked"])
    return {"profiles": results, "blocked_count": blocked_count, "pass_count": len(results) - blocked_count}


def _fb_scrape_once(fb, url: str):
    """单 URL 的 FB scrape 判定（纯读）。FbClient 无会话状态（每请求独立 httpx 调用），可跨线程。"""
    from ..core.fb_client import FbApiError
    try:
        resp = fb.post("", {"id": url, "scrape": "true"})
        title = ""
        og = resp.get("og_object") if isinstance(resp, dict) else None
        if isinstance(og, dict):
            title = og.get("title") or ""
        if not title and isinstance(resp, dict):
            title = resp.get("title") or ""
        return "pass", "FB 抓取正常（未封禁）" + (f"：{title[:40]}" if title else "")
    except FbApiError as e:
        msg = ((e.raw or {}).get("message", "") or "").lower()
        cat = e.category
        if cat in ("token_expired", "permissions", "permission_denied"):
            return "warn", f"令牌不可用：{e.friendly[:50]}"
        if cat == "rate_limited":
            return "warn", f"FB 限流：{e.friendly[:50]}"
        ban_kw = ("blocked", "spam", "malicious", "unsafe", "security",
                  "violat", "policy", "abusive", "blacklist", "forbidden", "banned")
        if any(k in msg for k in ban_kw):
            return "fail", f"疑似被 FB 封禁：{e.friendly[:50]}"
        unreachable_kw = ("could not resolve", "could not retrieve", "could not be fetched",
                          "could not be crawled", "ssl", "certificate", "timeout", "connection",
                          "redirect", "failed to connect", "unreachable", "dns")
        if any(k in msg for k in unreachable_kw):
            return "warn", f"FB 爬取失败（防护挡爬虫/SSL/DNS）：{e.friendly[:50]}"
        return "warn", f"FB 返回异常：{e.friendly[:50]}"
    except Exception as e:
        return "warn", f"检测异常：{str(e)[:50]}"


def _fb_ban_probe(db, tenant_id, url):
    """FB 平台封禁探测：调 Graph API URL scrape，判断 URL 是否被 FB 拉黑。

    返回 (status, detail)：
    - pass: FB 正常抓取（未封禁）
    - fail: 命中封禁关键词（blocked/spam/policy/violat 等）→ 疑似被封禁
    - warn: FB 爬不到（SSL/DNS/你的防护挡了 FB 爬虫）/ 令牌问题 / 无可用令牌（无法判定）
    """
    from ..core.fb_tokens import first_client
    fb = first_client(db, tenant_id)
    if fb is None:
        return "warn", "无可用 FB 令牌，跳过封禁检测"
    return _fb_scrape_once(fb, url)


def _fb_ban_probe_batch(db, tenant_id, urls, max_workers: int = 5, per_call_timeout: float = 10.0):
    """批量 FB 封禁探测：5 并发 + 单调用 10s 超时兜底（串行 N 个 × 30s 必撞网关超时）。

    first_client 只在主线程调（SQLAlchemy Session 非线程安全）；FbClient 线程安全（见 _fb_scrape_once）。
    返回与 urls 同序的 [(status, detail), ...]；单调用超时按 warn 处理不阻断整体。
    """
    from ..core.fb_tokens import first_client
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout
    if not urls:
        return []
    fb = first_client(db, tenant_id)
    if fb is None:
        return [("warn", "无可用 FB 令牌，跳过封禁检测") for _ in urls]

    def _one(u):
        # 单调用独立线程 + result(10s)：兜住 fb_client 内置 30s 超时（fb_client 不在本次改动范围）
        _ex = ThreadPoolExecutor(max_workers=1)
        try:
            return _ex.submit(_fb_scrape_once, fb, u).result(timeout=per_call_timeout)
        except _FutTimeout:
            return "warn", f"FB 检测超时（{int(per_call_timeout)}s），已跳过"
        except Exception as e:
            return "warn", f"检测异常：{str(e)[:50]}"
        finally:
            _ex.shutdown(wait=False, cancel_futures=True)  # 不等慢调用：线程稍后自行结束

    with ThreadPoolExecutor(max_workers=max_workers) as _pool:
        return list(_pool.map(_one, urls))


@router.post("/pages/{pid}/subdomains")
def add_subdomain(pid: int, body: dict,
                  user: CurrentUser = Depends(require_permission("landing.manage")),
                  db: Session = Depends(get_db)):
    """添加一个新子域名到已有落地页（CF 绑定 + 入 bound_subdomains，不触发重部署）。"""
    import json as _json
    from ..models.launch import LandingPage
    prefix = (body.get("prefix") or "").strip().lower()
    if not prefix:
        raise HTTPException(400, "请输入子域名前缀")
    import re as _re
    if not _re.match(r'^[a-z0-9][a-z0-9-]{0,30}$', prefix):
        raise HTTPException(400, "前缀只能含小写字母、数字、连字符（2-31 字符）")
    p = db.query(LandingPage).filter(LandingPage.id == pid, LandingPage.tenant_id == user.tenant_id).first()
    if not p:
        raise HTTPException(404, "落地页不存在")
    # 取根域名
    roots = []
    try:
        if p.custom_domains: roots = _json.loads(p.custom_domains)
    except Exception:
        pass
    if not roots and p.custom_domain:
        host = p.custom_domain.split("://", 1)[-1].split("/")[0]
        parts = host.split(".", 1)
        if len(parts) > 1: roots = [parts[1]]
    if not roots:
        raise HTTPException(400, "落地页没有配置根域名")
    # 多根域：前端可指定 root，否则用第一个
    _root = body.get("root") or ""
    if _root:
        _root = _domain_root(_root)
        if _root not in [_domain_root(r) for r in roots]:
            raise HTTPException(400, f"根域名 {_root} 不在该落地页配置中")
        selected_root = _root
    else:
        selected_root = _domain_root(roots[0])
    sub = f"{prefix}.{selected_root}"
    # 冲突检查
    clash = db.query(LandingPage).filter(
        LandingPage.custom_domain == f"https://{sub}",
        LandingPage.id != pid
    ).first()
    if clash:
        raise HTTPException(400, f"子域名 {sub} 已被「{clash.title}」占用")
    # CF 绑定
    cf_token = settings.cf_api_token
    cf_account = settings.cf_account_id
    if cf_token and cf_account:
        from ..core.cf_client import CfClient
        cf = CfClient(cf_token, cf_account)
        try:
            if cf.get_zone_id(_domain_root(sub)):
                cf.bind_custom_domain(f"tovaads-landing-{p.id}", sub)
        except Exception as e:
            raise HTTPException(400, f"CF 绑定失败: {e}")
    # 加入 bound_subdomains
    subs = []
    try:
        if p.bound_subdomains: subs = _json.loads(p.bound_subdomains)
    except Exception:
        pass
    if not subs and p.custom_domain:
        host = p.custom_domain.split("://", 1)[-1].split("/")[0]
        if host: subs = [host]
    if sub not in subs:
        subs.append(sub)
    p.bound_subdomains = _json.dumps(subs)
    db.commit()
    return {"ok": True, "subdomain": sub, "url": f"https://{sub}", "bound_subdomains": subs}


@router.delete("/pages/{pid}/subdomains/{hostname}")
def delete_subdomain(pid: int, hostname: str,
                     user: CurrentUser = Depends(require_permission("landing.manage")),
                     db: Session = Depends(get_db)):
    """删除一个绑定的子域名（CF 解绑 + 移出 bound_subdomains）。不删最后一个。"""
    import json as _json
    from ..models.launch import LandingPage
    p = db.query(LandingPage).filter(LandingPage.id == pid, LandingPage.tenant_id == user.tenant_id).first()
    if not p:
        raise HTTPException(404, "落地页不存在")
    subs = []
    try:
        if p.bound_subdomains: subs = _json.loads(p.bound_subdomains)
    except Exception:
        pass
    # 兜底：从 custom_domain 补
    if not subs and p.custom_domain:
        host = p.custom_domain.split("://", 1)[-1].split("/")[0]
        if host: subs = [host]
    if hostname not in subs:
        raise HTTPException(404, f"子域名 {hostname} 不在绑定列表中")
    if len(subs) <= 1:
        raise HTTPException(400, "至少保留一个子域名，不能删除最后一个")
    # CF 解绑
    cf_token = settings.cf_api_token
    cf_account = settings.cf_account_id
    if cf_token and cf_account:
        from ..core.cf_client import CfClient
        cf = CfClient(cf_token, cf_account)
        try: cf.unbind_custom_domain(f"tovaads-landing-{p.id}", hostname)
        except Exception: pass
    # 移出列表
    subs.remove(hostname)
    p.bound_subdomains = _json.dumps(subs)
    # 如果删的是 custom_domain，换到第一个
    if p.custom_domain and hostname in p.custom_domain:
        p.custom_domain = f"https://{subs[0]}" if subs else p.custom_domain
    db.commit()
    return {"ok": True, "bound_subdomains": subs}


@router.get("/pages/check-subdomain")
def check_subdomain(prefix: str = "", root: str = "", pid: int = 0,
                    user: CurrentUser = Depends(require_permission("ads.read")),
                    db: Session = Depends(get_db)):
    """子域名冲突实时检查（前端输入时 debounce 查）。"""
    from ..models.launch import LandingPage
    p = (prefix or "").strip().lower()
    if not p or not root:
        return {"available": True, "subdomain": ""}
    sub = f"{p}.{_domain_root(root)}"
    q = db.query(LandingPage).filter(
        LandingPage.custom_domain == f"https://{sub}",
        LandingPage.tenant_id == user.tenant_id)
    if pid:
        q = q.filter(LandingPage.id != pid)
    clash = q.first()
    return {"available": not clash, "subdomain": sub, "clash_with": (clash.title if clash else "")}


def _run_self_check(db, p, include_fb=True, live_probe=True, loc: str = "zh"):
    """落地页全功能自检矩阵。返回 {overall, summary, checks:[{key,label,status,detail}]}。

    status 三级：pass / warn(配置选择,可见不拦) / fail(真坏:worker/域名/SSL/目标死链)。
    像素=warn 不 fail（display 模式可合法不带像素）。route_next 用真实绑的广告测全链路像素解析。
    include_fb=False：跳过 FB Graph scrape（慢；发布时用 False，standalone /health 用 True）。
    live_probe=False：跳过域名/Worker 实时 curl（发布后 CF 传播未完成会误报；且 Worker 已被 smoke 门验过。
                     发布时用 False 只跑配置项，standalone /health 用 True）。
    """
    import httpx as _httpx
    import json as _j
    from datetime import datetime as _dt, timezone as _tz
    checks = []
    # 公开 URL 解析
    base = ""
    if p.custom_domain:
        base = p.custom_domain if p.custom_domain.startswith("http") else f"https://{p.custom_domain}"
    elif p.custom_domains:
        try:
            ds = _j.loads(p.custom_domains)
            if ds:
                base = ds[0] if ds[0].startswith("http") else f"https://{ds[0]}"
        except Exception:
            pass
    if not base:
        base = f"https://tovaads-landing-{p.id}.pages.dev"
    # 1. 发布状态
    checks.append({"key": "status", "label": L(loc, "landing.scStatus"),
                   "status": "pass" if p.status == "published" else "warn",
                   "detail": p.status or "draft"})
    # 2. 公开链接
    checks.append({"key": "url", "label": L(loc, "landing.scUrl"), "status": "pass", "detail": base})
    # 3. 域名+SSL 可达（curl 根域，follow_redirects）—— live_probe=False 时跳过（发布后 CF 传播未完成会误报）
    if live_probe:
        try:
            resp = _httpx.get(base, timeout=6, follow_redirects=True,
                              headers={"User-Agent": "TovaHealthCheck/1.0"})
            ssl_ok = str(resp.url).startswith("https://")
            ok = resp.status_code < 500 and ssl_ok
            checks.append({"key": "domain", "label": L(loc, "landing.scDomain"),
                           "status": "pass" if ok else "fail",
                           "detail": f"HTTP {resp.status_code}" + ("" if ssl_ok else " · SSL无效")})
        except Exception as e:
            checks.append({"key": "domain", "label": L(loc, "landing.scDomain"), "status": "fail",
                           "detail": f"不可达: {str(e)[:60]}"})
    # 4. Worker 存活（/__health 无条件 200）—— live_probe=False 时跳过（已被发布 smoke 门验过）
    if live_probe:
        try:
            resp = _httpx.get(base.rstrip("/") + "/__health", timeout=6, follow_redirects=False,
                              headers={"User-Agent": "TovaHealthCheck/1.0"})
            checks.append({"key": "worker", "label": L(loc, "landing.scWorker"),
                           "status": "pass" if resp.status_code == 200 else "fail",
                           "detail": f"HTTP {resp.status_code}"})
        except Exception as e:
            checks.append({"key": "worker", "label": L(loc, "landing.scWorker"), "status": "fail",
                           "detail": f"无响应: {str(e)[:60]}"})
    # 取一个真实绑的广告（测 route_next 全链路像素解析；无则用 __smoke__ 占位）
    sample_slug, sample_ad = "", ""
    try:
        from ..models.launch import LandingAdLink
        link = db.query(LandingAdLink).filter(
            LandingAdLink.page_id == p.id, LandingAdLink.ad_id.isnot(None),
            LandingAdLink.ad_id != "", ~LandingAdLink.ad_id.like("%{{%")
        ).first()
        if link:
            sample_slug, sample_ad = link.slug, link.ad_id
    except Exception:
        pass
    rd = None
    try:
        from .landing_events import route_next, RouteNextIn
        rd = route_next(RouteNextIn(secret=p.ingest_secret or "",
                                    slug=sample_slug or "__smoke__",
                                    ad_id=sample_ad or "999999", act_id=""), dry_run=True)
    except Exception:
        rd = None
    # 5. 像素（display 才查；redirect 模式设计上无像素=正常）
    if (p.redirect_mode or "display") == "redirect":
        checks.append({"key": "pixel", "label": L(loc, "landing.scPixel"), "status": "pass",
                       "detail": "redirect 模式（无像素，正常）"})
    else:
        px = ((rd or {}).get("pixel_ids")) or []
        if px:
            _samp = f"（以广告 {sample_ad} 为样本）" if sample_ad else ""
            checks.append({"key": "pixel", "label": L(loc, "landing.scPixel"), "status": "pass",
                           "detail": f"{len(px)} 个{_samp}：{','.join(str(x) for x in px)[:50]}"})
        else:
            checks.append({"key": "pixel", "label": L(loc, "landing.scPixel"), "status": "warn",
                           "detail": "display 未解析到像素（页面不会 fire 转化；有意不带像素可忽略）"})
    # 6. 跳转目标（route_next 返回 + 可达性 HEAD）
    tgt = ((rd or {}).get("target_url")) or ""
    if not tgt:
        checks.append({"key": "target", "label": L(loc, "landing.scTarget"), "status": "fail", "detail": "未配置目标 URL"})
    else:
        try:
            tr = _httpx.head(tgt, timeout=5, follow_redirects=True)
            # 401/403/405 = 服务器有响应只是拒绝 HEAD（很多目标站这样）→ 算可达 pass
            reachable = tr.status_code < 400 or tr.status_code in (401, 403, 405)
            checks.append({"key": "target", "label": L(loc, "landing.scTarget"),
                           "status": "pass" if reachable else "warn",
                           "detail": f"{tgt[:40]} · HTTP {tr.status_code}"})
        except Exception as e:
            checks.append({"key": "target", "label": L(loc, "landing.scTarget"), "status": "warn",
                           "detail": f"{tgt[:40]} · 不可达: {str(e)[:30]}"})
    # 7. 防护规则（数 worker 真评估/拦截的项；block_target=跳转目标不算，block_html=worker不渲染不算）
    if p.block_enabled:
        try:
            rules = _j.loads(p.protection_rules) if p.protection_rules else {}
        except Exception:
            rules = {}
        _rule_keys = ("country_allow", "country_block", "device_block", "ua_block",
                      "referer_block", "query_block", "required_query", "datacenter_block")
        n = sum(1 for k in _rule_keys if rules.get(k))
        # frequency/dedup 是 worker evalProtection 外的独立真拦截路径，单独计入
        if isinstance(rules.get("frequency"), dict) and rules["frequency"].get("max"):
            n += 1
        if p.dedup_enabled:
            n += 1
        checks.append({"key": "protection", "label": L(loc, "landing.scProtection"),
                       "status": "pass" if n else "warn",
                       "detail": f"已开 · {n} 条规则" if n else "已开但无规则"})
    else:
        checks.append({"key": "protection", "label": L(loc, "landing.scProtection"), "status": "warn", "detail": "未开启"})
    # 8. FB 平台封禁（慢，发布时跳过）——域名级 + 子码级
    if include_fb:
        fb_status, fb_detail = _fb_ban_probe(db, p.tenant_id, base)
        checks.append({"key": "fb_ban", "label": L(loc, "landing.scFbBan"), "status": fb_status, "detail": fb_detail})
        # 子码级 FB 封禁检测（扫描所有 active 子码）
        from ..models.launch import LandingAdLink
        _active_links = db.query(LandingAdLink).filter(
            LandingAdLink.page_id == p.id, LandingAdLink.tenant_id == p.tenant_id,
            LandingAdLink.status == "active"
        ).all()
        if _active_links:
            # 并发 scrape（串行 N×30s 会撞网关超时）；结果与 links 同序
            _probe_res = _fb_ban_probe_batch(
                db, p.tenant_id, [f"{base.rstrip('/')}/a/{_link.slug}" for _link in _active_links])
            _blocked_slugs = [_link.slug for _link, (_st, _d)
                              in zip(_active_links, _probe_res) if _st == "fail"]
            if _blocked_slugs:
                checks.append({"key": "fb_subcode", "label": L(loc, "landing.scFbSubcode"),
                               "status": "fail",
                               "detail": f"{len(_blocked_slugs)}/{len(_active_links)} 个子码被封：{','.join(_blocked_slugs[:5])}"})
            else:
                checks.append({"key": "fb_subcode", "label": L(loc, "landing.scFbSubcode"),
                               "status": "pass",
                               "detail": f"{len(_active_links)} 个子码全部正常"})
    # 9. 预览模式（关=正常运营 pass；开=提醒审核完关掉 warn，避免每页都黄）
    checks.append({"key": "preview", "label": L(loc, "landing.scPreview"),
                   "status": "warn" if p.preview_enabled else "pass",
                   "detail": "已启用（审核/测试完记得关）" if p.preview_enabled else "未启用"})
    # 聚合
    has_fail = any(c["status"] == "fail" for c in checks)
    has_warn = any(c["status"] == "warn" for c in checks)
    overall = "fail" if has_fail else ("warn" if has_warn else "pass")
    _non_pass = [c for c in checks if c["status"] != "pass"]
    summary = (("；".join(c["label"] for c in _non_pass))[:100].rstrip("；")) if _non_pass else "全部检查通过"
    return {"overall": overall, "summary": summary, "checks": checks,
            "checked_at": _dt.now(_tz.utc).isoformat()}


def _emit_health_alert(db, p, res):
    """自检不通过/被FB屏蔽 → 告警（6h dedup per page；owner+operator）。

    发布后自检(include_fb=False)覆盖配置项 fail；手动 /health(include_fb=True) 覆盖 FB 封禁(critical)。
    """
    from ..core.notify_utils import emit_notification, dedup_recent
    if (res.get("overall") or "pass") == "pass":
        return
    if dedup_recent(db, p.tenant_id, "landing_health_alert", str(p.id), 360):
        return  # 6h 内已发过，避免 spam
    _tid = new_trace_id()
    _checks = res.get("checks") or []
    _fb_blocked = any(c.get("status") == "fail" and c.get("key") in ("fb_ban", "fb_subcode") for c in _checks)
    if _fb_blocked:
        _level, _prefix = "critical", "🔴 落地页被FB屏蔽"
    elif res["overall"] == "fail":
        _level, _prefix = "warning", "⚠️ 落地页自检未通过"
    else:
        _level, _prefix = "info", "落地页自检有提醒"
    # 受影响广告数：该页 active/reserved 子码里已绑广告的（屏蔽影响面，告知用，不做自动切换）
    try:
        from ..models.launch import LandingAdLink
        _affected = db.query(LandingAdLink).filter(
            LandingAdLink.page_id == p.id,
            LandingAdLink.tenant_id == p.tenant_id,
            LandingAdLink.status.in_(["active", "reserved"]),
            LandingAdLink.ad_id.isnot(None),
            LandingAdLink.ad_id != "",
        ).count()
    except Exception:
        _affected = 0
    _body = (res.get("summary") or "").strip()
    if _affected:
        _body = (f"影响 {_affected} 个已绑广告。" + _body).strip()
    write_log(db, tenant_id=p.tenant_id, trace_id=_tid, actor_type="system",
              action_type="landing_health_alert", source="landing",
              target_type="landing_page", target_id=str(p.id), result="success",
              metadata={"overall": res["overall"], "summary": (res.get("summary") or "")[:100], "affected_ads": _affected})
    emit_notification(db, tenant_id=p.tenant_id, level=_level,
                      event_type="landing_health", trace_id=_tid,
                      target_type="landing_page", target_id=str(p.id),
                      roles=["owner", "operator"],
                      title=f"{_prefix}：{p.title}",
                      body=_body[:200], platform="fb")


@router.get("/pages/{pid}/health")
def health_check(
    pid: int,
    request: Request,
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """落地页全功能自检（9 项矩阵：发布/链接/域名SSL/Worker/像素/目标/防护/FB封禁/预览）。存库。"""
    from datetime import datetime as _dt, timezone as _tz
    from ..models.launch import LandingPage
    p = db.query(LandingPage).filter(
        LandingPage.id == pid, LandingPage.tenant_id == user.tenant_id).first()
    if not p:
        raise HTTPException(404, "落地页不存在")
    res = _run_self_check(db, p, include_fb=True, loc=req_locale(request))
    p.last_health_status = res["overall"]
    p.last_health_summary = res["summary"]
    p.last_health_checked_at = _dt.now(_tz.utc)
    _emit_health_alert(db, p, res)
    db.commit()
    return {"success": res["overall"] != "fail", **res}


_CONTROLLED_CACHE = {}  # tenant_id -> (时间戳, ad_id集合)；per-worker，30s TTL（一次页面加载 logs+stats 并行只解析一次）
_CONTROLLED_TTL = 30


def _controlled_ad_ids(db, tenant_id):
    """本租户所有 ads_cache 里的 ad_id 快照集合（查询时算：新增/移除账户不影响历史判定）。30s 缓存。"""
    import time as _t
    now = _t.time()
    cached = _CONTROLLED_CACHE.get(tenant_id)
    if cached and (now - cached[0]) < _CONTROLLED_TTL:
        return cached[1]
    import json as _j
    from ..models.ads_cache import AdsCache
    out = set()
    for (_ads_json,) in db.query(AdsCache.ads_json).filter(AdsCache.tenant_id == tenant_id).all():
        try:
            for _ad in _j.loads(_ads_json or "[]"):
                _aid = _ad.get("id")
                if _aid:
                    out.add(str(_aid))
        except Exception:
            continue
    _CONTROLLED_CACHE[tenant_id] = (now, out)
    return out


# —— 来源归因信号层（全部查询时算，基于已有数据，无外部 API/无迁移）——

# ASN 知识库：AS号 → (中文名, 类型)。类型：platform=平台自有 / datacenter=机房VPS(非真人,可疑) / isp=家宽(真人)
_ASN_KB = {
    # 平台自有（爬虫/CDN/基础设施）
    "32934": ("Facebook", "platform"), "15169": ("Google", "platform"), "8075": ("Microsoft", "platform"),
    "13335": ("Cloudflare", "platform"), "20940": ("Akamai", "platform"), "4837": ("中国联通", "isp"),
    # 云/机房/VPS（命中即"非真人"：爬虫/自动化/ad fraud/VPN 常用地）
    "14618": ("Amazon AWS", "datacenter"), "16509": ("Amazon AWS", "datacenter"),
    "396982": ("Google Cloud", "datacenter"), "20473": ("Vultr", "datacenter"),
    "14061": ("DigitalOcean", "datacenter"), "16276": ("OVH", "datacenter"),
    "24940": ("Hetzner", "datacenter"), "45102": ("阿里云", "datacenter"),
    "132203": ("腾讯云", "datacenter"), "55960": ("Linode", "datacenter"),
    "63949": ("Linode", "datacenter"), "31898": ("Oracle Cloud", "datacenter"),
    "30633": ("Leaseweb", "datacenter"), "36352": ("ColoCrossing", "datacenter"),
    "60068": ("Datacamp", "datacenter"), "24961": ("myLocate", "datacenter"),
    "62567": ("DigitalOcean", "datacenter"), "395974": ("BgPunter", "datacenter"),
    # 主要家宽 ISP（真人为主）
    "4134": ("中国电信", "isp"), "4812": ("上海电信", "isp"), "4809": ("中国联通", "isp"),
    "9808": ("中国移动", "isp"), "58453": ("中国移动", "isp"), "3462": ("中华电信", "isp"),
    "9318": ("SK Telecom", "isp"), "4766": ("韩国电信", "isp"), "2516": ("KDDI", "isp"),
    "17676": ("SoftBank", "isp"), "4713": ("NTT", "isp"), "3320": ("德国电信", "isp"),
    "3215": ("Orange", "isp"), "3269": ("意大利电信", "isp"), "3352": ("西班牙电信", "isp"),
    "7922": ("Comcast", "isp"), "701": ("Verizon", "isp"), "7018": ("AT&T", "isp"), "33287": ("Comcast", "isp"),
}

# 爬虫 UA 特征 → 中文名（顺序敏感：FB 先判）。与 _crawler_filter_cond 的 SQL 同源
_CRAWLER_MAP = [
    (("facebookexternalhit", "facebot", "meta-externalagent"), "Facebook爬虫"),
    (("googlebot",), "Google爬虫"), (("bingbot",), "Bing爬虫"), (("baiduspider",), "百度爬虫"),
    (("bytespider",), "字节爬虫"), (("yandexbot",), "Yandex爬虫"), (("duckduckbot",), "DuckDuckGo爬虫"),
]
_ALL_CRAWLER_TOKENS = ("facebookexternalhit", "facebot", "meta-externalagent", "googlebot", "bingbot",
                       "baiduspider", "bytespider", "yandexbot", "duckduckbot", "crawler", "spider")


def _detect_crawler(asn, ua):
    """爬虫中文名（""=非爬虫）。AS32934 单独判 Facebook。"""
    u = (ua or "").lower()
    if str(asn or "") == "32934":
        return "Facebook爬虫"
    for tokens, name in _CRAWLER_MAP:
        if any(t in u for t in tokens):
            return name
    if "crawler" in u or "spider" in u:
        return "未知爬虫"
    return ""


def _is_crawler(asn, ua):
    return bool(_detect_crawler(asn, ua))


def _detect_in_app(ua):
    """应用内浏览器（真人移动端强信号）：FB/IG/TikTok。"""
    u = (ua or "").lower()
    if "fban" in u or "fbav" in u or "fb_iab" in u:
        return "FB应用内"
    if "instagram" in u:
        return "IG应用内"
    if "tiktok" in u:
        return "TikTok应用内"
    return ""


def _crawler_filter_cond():
    """爬虫的 SQLAlchemy 过滤条件（供 source_type 筛选用，与 _is_crawler 同源）。"""
    from sqlalchemy import or_
    from ..models.landing_event import LandingEvent as _LE
    return or_(_LE.asn == "32934", *[_LE.user_agent.ilike(f"%{t}%") for t in _ALL_CRAWLER_TOKENS])


def _classify_source(ad_id, fbclid, asn, user_agent, controlled):
    """多层来源归因。返回 (source_type, source_platform, source_detail, asn_name, asn_type)。

    source_type: crawler(爬虫优先) / controlled(本系统广告) / external(数字ad_id不在系统,疑似盗用)
                 / placeholder(ad_id含{{或非数字) / unknown(无ad_id)
    source_platform: facebook/google/""（可扩展：加 TikTok/Google 需 worker 转发 click 参数 + 加列 + 映射）
    source_detail: 人类可读细节（爬虫名 / 应用内 / 机房标记）
    asn_name/asn_type: ASN 解析（datacenter=机房非真人可疑）
    """
    ua = (user_agent or "").lower()
    asn_s = str(asn) if asn else ""
    asn_name, asn_type = _ASN_KB.get(asn_s, ("", ""))
    crawler = _detect_crawler(asn, user_agent)
    in_app = _detect_in_app(user_agent)
    # 平台
    if asn_s == "32934" or "facebookexternalhit" in ua or "facebot" in ua or "meta-externalagent" in ua \
            or "fbav" in ua or "fban" in ua or fbclid:
        platform = "facebook"
    elif "googlebot" in ua:
        platform = "google"
    elif ad_id:
        platform = "facebook"
    else:
        platform = ""
    # 类型（爬虫优先）。numeric 用 isascii()+isdigit() 与 SQL '^[0-9]+$' 严格对齐（排除全角数字/带空格）
    if crawler:
        st = "crawler"
    elif not ad_id:
        st = "unknown"
    else:
        a = str(ad_id or "")
        numeric = a.isascii() and a.isdigit()
        st = "placeholder" if ("{{" in a or not numeric) else ("controlled" if a in controlled else "external")
    # 细节
    if crawler:
        detail = crawler
    else:
        parts = []
        if in_app:
            parts.append(in_app)
        if asn_type == "datacenter":
            parts.append(f"机房·{asn_name or '未知'}")
        detail = " ".join(parts)
    return st, platform, detail, asn_name, asn_type


def _apply_source_filter(qb, source_type, controlled):
    """source_type SQL 层筛选（保证分页正确）。规则与 _classify_source 严格对齐。"""
    from sqlalchemy import text
    from ..models.landing_event import LandingEvent as _LE
    crawl = _crawler_filter_cond()
    numeric = _LE.ad_id.op("~")(r"^[0-9]+$")
    has_ad = (_LE.ad_id.isnot(None)) & (_LE.ad_id != "")
    if source_type == "crawler":
        return qb.filter(crawl)
    if source_type == "controlled":
        if not controlled:
            return qb.filter(text("false"))
        return qb.filter((~crawl) & has_ad & numeric & _LE.ad_id.in_(list(controlled)))
    if source_type == "external":
        base = qb.filter((~crawl) & has_ad & numeric)
        return base.filter(~_LE.ad_id.in_(list(controlled))) if controlled else base
    if source_type == "placeholder":
        return qb.filter((~crawl) & has_ad & (~numeric))
    if source_type == "unknown":
        return qb.filter((~crawl) & (~has_ad))
    return qb


@router.get("/logs")
def landing_logs(
    user: CurrentUser = Depends(require_permission("ads.read")),
    page_id: int | None = None,
    slug: str = "",
    ad_id: str = "",
    act_id: str = "",
    event_type: str = "",
    decision: str = "",
    source_type: str = "",
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    offset: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """落地页访问日志（landing_events）：筛选 + 分页 + 跳转链接(target_url) + 多层来源归因。

    与子码联动：slug/ad_id/page_id 可预筛（从子码抽屉"查看日志"跳来）。
    日期按业务日(北京 UTC+8)边界转 UTC 查询（和看板同基准，避免跨时区错位）。
    source_type：受控/外部/爬虫/占位符/未知 分类筛选（SQL 层，与 _classify_source 对齐）。
    """
    from ..models.landing_event import LandingEvent
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    BUSINESS_TZ = _tz(_td(hours=8))
    _controlled = _controlled_ad_ids(db, user.tenant_id)
    qb = db.query(LandingEvent).filter(LandingEvent.tenant_id == user.tenant_id)
    if page_id:
        qb = qb.filter(LandingEvent.page_id == page_id)
    if slug:
        qb = qb.filter(LandingEvent.slug == slug)
    if ad_id:
        qb = qb.filter(LandingEvent.ad_id == ad_id)
    if act_id:
        qb = qb.filter(LandingEvent.act_id == act_id)
    if event_type:
        qb = qb.filter(LandingEvent.event_type == event_type)
    if decision:
        qb = qb.filter(LandingEvent.decision == decision)
    if date_from:
        try:
            start = _dt.strptime(date_from, "%Y-%m-%d").replace(tzinfo=BUSINESS_TZ)
            qb = qb.filter(LandingEvent.created_at >= start.astimezone(_tz.utc))
        except ValueError:
            pass
    if date_to:
        try:
            end = _dt.strptime(date_to, "%Y-%m-%d").replace(tzinfo=BUSINESS_TZ) + _td(days=1)
            qb = qb.filter(LandingEvent.created_at < end.astimezone(_tz.utc))
        except ValueError:
            pass
    if q:
        like = f"%{q}%"
        qb = qb.filter(LandingEvent.country.ilike(like) | LandingEvent.city.ilike(like)
                       | LandingEvent.referrer.ilike(like) | LandingEvent.slug.ilike(like)
                       | LandingEvent.ad_id.ilike(like) | LandingEvent.act_id.ilike(like))
    if source_type:
        qb = _apply_source_filter(qb, source_type, _controlled)
    total = qb.count()
    limit = min(max(int(limit or 50), 1), 500)
    offset = max(int(offset or 0), 0)
    rows = qb.order_by(LandingEvent.created_at.desc()).offset(offset).limit(limit).all()
    # 批量解析账户名（act_id → name）
    from ..models.fb import Account
    _acts = {e.act_id for e in rows if e.act_id}
    _act_names = {a.act_id: a.name for a in db.query(Account).filter(
        Account.tenant_id == user.tenant_id, Account.act_id.in_(_acts)).all()} if _acts else {}
    _src = {e.id: _classify_source(e.ad_id, e.fbclid, e.asn, e.user_agent, _controlled) for e in rows}
    items = [{
        "id": e.id, "event_type": e.event_type, "slug": e.slug, "ad_id": e.ad_id,
        "act_id": e.act_id, "act_name": _act_names.get(e.act_id, ""),
        "page_id": e.page_id, "fbclid": e.fbclid, "fired_pixel_ids": e.fired_pixel_ids or "",
        "path": e.path, "target_url": e.target_url,
        "decision": e.decision, "reason": e.reason,
        "country": e.country, "city": e.city, "platform": e.platform,
        "device_type": e.device_type, "browser": e.browser, "asn": e.asn,
        "asn_name": _src[e.id][3], "asn_type": _src[e.id][4],
        "referrer": e.referrer, "user_agent": (e.user_agent or "")[:120],
        "created_at": e.created_at.isoformat() if e.created_at else "",
        "source_type": _src[e.id][0],
        "source_platform": _src[e.id][1],
        "source_detail": _src[e.id][2],
    } for e in rows]
    return {"total": total, "offset": offset, "limit": limit, "items": items}


@router.get("/logs/source-stats")
def landing_log_source_stats(
    user: CurrentUser = Depends(require_permission("ads.read")),
    page_id: int | None = None,
    slug: str = "",
    act_id: str = "",
    event_type: str = "",
    decision: str = "",
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    db: Session = Depends(get_db),
):
    """来源分布统计（受控/外部/爬虫/占位符/未知 + 机房数）。默认今日（北京业务日），有日期则按日期。

    供前端"来源分布"chip 条：一眼看今日各类流量占比，点 chip 即筛选。
    只取归因所需瘦列（ad_id/fbclid/asn/user_agent），避免大 SELECT。
    """
    from ..models.landing_event import LandingEvent
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    BUSINESS_TZ = _tz(_td(hours=8))
    controlled = _controlled_ad_ids(db, user.tenant_id)
    # 无日期 → 默认今日（绑定扫描量，避免全表）
    window = "custom"
    if not date_from and not date_to:
        today = _dt.now(BUSINESS_TZ).strftime("%Y-%m-%d")
        date_from = date_to = today
        window = "today"
    # 日期上限保护：超大范围会让全量分类跑数十秒→前端超时。超过 90 天自动截到最近 90 天
    try:
        _df = _dt.strptime(date_from, "%Y-%m-%d").replace(tzinfo=BUSINESS_TZ)
        _dt_to = _dt.strptime(date_to, "%Y-%m-%d").replace(tzinfo=BUSINESS_TZ)
        if (_dt_to - _df).days > 90:
            date_from = (_dt_to - _td(days=90)).strftime("%Y-%m-%d")
            window = "truncated-90d"
    except ValueError:
        pass
    qb = db.query(LandingEvent).filter(LandingEvent.tenant_id == user.tenant_id)
    if page_id:
        qb = qb.filter(LandingEvent.page_id == page_id)
    if slug:
        qb = qb.filter(LandingEvent.slug == slug)
    if act_id:
        qb = qb.filter(LandingEvent.act_id == act_id)
    if event_type:
        qb = qb.filter(LandingEvent.event_type == event_type)
    if decision:
        qb = qb.filter(LandingEvent.decision == decision)
    if date_from:
        try:
            start = _dt.strptime(date_from, "%Y-%m-%d").replace(tzinfo=BUSINESS_TZ)
            qb = qb.filter(LandingEvent.created_at >= start.astimezone(_tz.utc))
        except ValueError:
            pass
    if date_to:
        try:
            end = _dt.strptime(date_to, "%Y-%m-%d").replace(tzinfo=BUSINESS_TZ) + _td(days=1)
            qb = qb.filter(LandingEvent.created_at < end.astimezone(_tz.utc))
        except ValueError:
            pass
    if q:
        like = f"%{q}%"
        qb = qb.filter(LandingEvent.country.ilike(like) | LandingEvent.city.ilike(like)
                       | LandingEvent.referrer.ilike(like) | LandingEvent.slug.ilike(like)
                       | LandingEvent.ad_id.ilike(like) | LandingEvent.act_id.ilike(like))
    rows = qb.with_entities(LandingEvent.ad_id, LandingEvent.fbclid, LandingEvent.asn,
                            LandingEvent.user_agent).all()
    counts = {"controlled": 0, "external": 0, "crawler": 0, "placeholder": 0, "unknown": 0}
    dc = 0
    for ad_id, fbclid, asn, ua in rows:
        st, _plat, _detail, _name, asn_type = _classify_source(ad_id, fbclid, asn, ua, controlled)
        if st in counts:
            counts[st] += 1
        if asn_type == "datacenter":
            dc += 1
    return {"total": len(rows), "window": window,
            "controlled": counts["controlled"], "external": counts["external"],
            "crawler": counts["crawler"], "placeholder": counts["placeholder"],
            "unknown": counts["unknown"], "datacenter": dc}
