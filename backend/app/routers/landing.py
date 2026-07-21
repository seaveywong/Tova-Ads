"""落地页路由：发布到 CF Pages + 绑定超管导入的域名。

POST /landing/publish → 创建/更新 Pages 项目 → Direct Upload → 返回 URL
GET /landing/pages → 列已发布的落地页
"""
import os
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.deps import CurrentUser, require_permission
from ..core.config import settings
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
LP_PIXELS.forEach(function(pid){if(pid){fbq('init',pid);fbq('trackSingle',pid,'PageView');}});
var _cta=document.getElementById('cta');if(_cta&&LP_TARGET_URL)_cta.href=LP_TARGET_URL;
</script>
</head>
<body style="margin:0;padding:0;font-family:sans-serif">
<div id="app" style="max-width:600px;margin:0 auto;padding:20px;text-align:center">
<h1>{{TITLE}}</h1>
<p>{{DESCRIPTION}}</p>
<a href="__LP_TARGET_URL__" id="cta" style="display:inline-block;padding:15px 40px;background:#0071e3;color:#fff;text-decoration:none;border-radius:8px;font-size:18px" onclick="return goNext(event)">立即购买</a>
</div>
<script>
function trackConversion(){if(!window.fbq||!Array.isArray(LP_PIXELS)||!LP_CONV.length)return;LP_PIXELS.forEach(function(pid){if(!pid)return;LP_CONV.forEach(function(evt){fbq('trackSingle',pid,evt);});});}
function goNext(ev){if(ev&&ev.preventDefault)ev.preventDefault();trackConversion();setTimeout(function(){window.location.href=LP_TARGET_URL;},300);return false;}
</script>
</body>
</html>
"""

# Worker 源码（常量，不含占位符；配置通过 JSON prepend 注入）
WORKER_SOURCE = """
function parseDev(u){u=(u||"").toLowerCase();let t="desktop";if(/ipad|tablet|playbook|silk/.test(u)||(/android/.test(u)&&!/mobile/.test(u)))t="tablet";else if(/mobile|iphone|ipod|android.*mobile|blackberry|opera mini/.test(u))t="mobile";return t;}
function matchAny(list,s){if(!Array.isArray(list)||!list.length)return false;s=(s||"").toLowerCase();return list.some(k=>s.includes(String(k).toLowerCase()));}
function evalProtection(request,url,cf){
  const rules=LP_CONFIG.rules;
  if(!rules||typeof rules!=="object"||Object.keys(rules).length===0)return{blocked:false};
  const ua=request.headers.get("user-agent")||"";
  const referer=request.headers.get("referer")||"";
  const country=(cf.country||"").toUpperCase();
  const dev=parseDev(ua);
  const asn=String(cf.asn||"");
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
    if(!url.pathname.startsWith("/a/"))return env.ASSETS.fetch(request);
    const cf=request.cf||{};
    const slug=url.pathname.replace("/a/","").split("?")[0];
    const adId=url.searchParams.get("ad")||url.searchParams.get("ad_id")||"";
    const actId=url.searchParams.get("act")||url.searchParams.get("act_id")||"";
    const fbclid=url.searchParams.get("fbclid")||"";
    const ip=request.headers.get("CF-Connecting-IP")||"";
    const ua=request.headers.get("user-agent")||"";
    const referer=request.headers.get("referer")||"";
    // 预览模式：?_pv=<token> 命中本页 token → 跳过所有防护（审核/测试用）
    const _pv=url.searchParams.get("_pv");
    const _isPreview=LP_CONFIG.preview_enabled&&_pv&&LP_CONFIG.preview_token&&_pv===LP_CONFIG.preview_token;
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
    const _d=btoa(unescape(encodeURIComponent(JSON.stringify({p:(rd.pixel_ids||[]).join(","),t:_target,c:(rd.conversion_events||[]).join(","),s:slug,a:adId,ai:actId}))));
    sendEvent("visit",{slug:slug,ad_id:adId,act_id:actId,fbclid:fbclid,pixel_ids:(rd.pixel_ids||[]).join(","),target_url:_target,decision:"display",country:cf.country||"",city:cf.city||"",asn:String(cf.asn||""),referer:referer,user_agent:ua,ip:ip},ctx);
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
    target_urls: list[str] = []                # 多目标轮换；空时 fallback target_url
    pixel_id: str = ""            # legacy 单像素
    pixel_ids: list[str] = []     # 多像素；空时 fallback 到 pixel_id
    conversion_event: str = ""    # Purchase/Contact/Lead（空=只 PageView）
    protection_rules: dict = {}   # 防护规则 10 key（空=不防护）
    template_id: int | None = None  # 落地页模板（zip 上传的；空=默认模板）
    project_name: str = "tovaads-landing"
    custom_domain: str = ""        # 兼容单域（custom_domains 优先）
    custom_domains: list[str] = [] # 多域名（一页绑多域）
    rotation_mode: str = "first"  # first|random|sequential
    redirect_mode: str = "display"  # display=落地页模式 / redirect=跳转模式
    conversion_events: list[str] = []  # 多转化事件（CTA 点击 forEach fire，替代单 conversion_event）
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


def _emit_landing_alert(project_name: str, msg: str, tenant_id: int = 1):
    """落地页 worker 异常告警（发布后 smoke 失败用）。"""
    try:
        from ..core.database import SuperSessionLocal
        from ..models.notify import Notification
        from datetime import datetime, timezone
        db = SuperSessionLocal()
        try:
            db.add(Notification(tenant_id=tenant_id, level="critical", event_type="landing_worker_error",
                                title=f"落地页 worker 异常 · {project_name}", body=msg,
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

    # 1. 确保项目存在
    if not cf.get_project(body.project_name):
        cf.create_project(body.project_name)

    # 2. 构造文件（existing 则保留 ingest_secret，避免旧 Worker 失效）
    pixels = body.pixel_ids or ([body.pixel_id] if body.pixel_id else [])
    targets = body.target_urls or ([body.target_url] if body.target_url else [])
    primary_target = targets[0] if targets else "https://tovaads.com"

    # 校验：防护开关开时必须有 block_target 或 block_html
    if body.block_enabled:
        rules = body.protection_rules or {}
        if not rules.get("block_target") and not rules.get("block_html"):
            raise HTTPException(400, "防护已开启，必须配置屏蔽跳转链接或屏蔽页 HTML（至少一项）")
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
    html = (template_html
            .replace("__LP_PIXELS_JSON__", _json.dumps(pixels))
            .replace("__LP_CONV_EVENT_JSON__", _json.dumps(body.conversion_events or []))
            .replace("__LP_TARGET_URL__", primary_target)
            .replace("{{TITLE}}", body.title)
            .replace("{{DESCRIPTION}}", body.description))
    # 注入 _d 解码脚本到 <head> 开头（FB 官方推荐位置，像素尽早加载；DOMContentLoaded 兜底按钮绑定）
    _d_decode = """<script>(function(){var _d=new URLSearchParams(location.search).get('_d');if(!_d)return;try{var info=JSON.parse(decodeURIComponent(escape(atob(_d))));var _pids=info.p?info.p.split(',').filter(Boolean):[];var _conv=info.c?info.c.split(',').filter(Boolean):[];if(!window.fbq){!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s);}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');}_pids.forEach(function(pid){fbq('init',pid);fbq('trackSingle',pid,'PageView');});if(info.t){try{if(typeof LP_TARGET_URL!=='undefined')LP_TARGET_URL=info.t;}catch(e){}window.__lp_target=info.t;}try{if(typeof LP_CONV!=='undefined')LP_CONV=_conv;}catch(e){}var _slug=info.s||'',_ad=info.a||'',_act=info.ai||'',_tgt=info.t||'';function _lpClick(){_pids.forEach(function(pid){_conv.forEach(function(evt){fbq('trackSingle',pid,evt);});});try{navigator.sendBeacon('/__events/ingest',JSON.stringify({event_type:'click',slug:_slug,ad_id:_ad,act_id:_act,target_url:_tgt,decision:'click'}));}catch(e){}}document.addEventListener('click',function(e){var el=e.target.closest('[onclick*=\"goNext\"],#cta,a[href]');if(el){_lpClick();}},{capture:true,once:true});if(info.t){document.addEventListener('DOMContentLoaded',function(){var cta=document.getElementById('cta')||document.querySelector('[onclick*=\"goNext\"]');if(cta)cta.href=info.t;try{if(typeof LP_TARGET_URL!=='undefined')LP_TARGET_URL=info.t;}catch(e){}});}}catch(e){}})();</script>"""
    if "<head" in html:
        html = re.sub(r"(<head[^>]*>)", r"\1" + _d_decode, html, count=1)
    elif "</body>" in html:
        html = html.replace("</body>", _d_decode + "\n</body>", 1)
    else:
        html = _d_decode + html
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



    # 4. 绑域名（每页独立子域名 lp{page_id}.{根域}——封禁隔离 + URL 独立；
    #    custom_domains 是用户选的根域名，绑的是派生子域名）
    roots = [d.rstrip("/") for d in (body.custom_domains or []) if d]
    if not roots and body.custom_domain:
        roots = [body.custom_domain.rstrip("/")]
    if not roots:
        lib = _pick_domain_from_lib(db, user.tenant_id)
        if lib:
            roots = [lib]
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
    # 解绑不再用的旧子域名（改前缀/移除域名时清理 CF 残留）
    if existing and existing.custom_domain:
        old_host = existing.custom_domain.split("://", 1)[-1].split("/")[0]
        if old_host and old_host not in bound:
            try: cf.unbind_custom_domain(body.project_name, old_host)
            except Exception: pass

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
            "custom_domains": _json.dumps(roots) if roots else existing.custom_domains,
            "target_urls": _json.dumps(targets) if targets else existing.target_urls,
            "rotation_mode": body.rotation_mode or existing.rotation_mode or "first",
            "pixel_id": body.pixel_id or existing.pixel_id,
            "pixel_ids": _json.dumps(pixels) if pixels else existing.pixel_ids,
            "conversion_event": body.conversion_event or existing.conversion_event,
            "protection_rules": _json.dumps(body.protection_rules) if body.protection_rules else existing.protection_rules,
            "template_id": body.template_id,
            "redirect_mode": body.redirect_mode or existing.redirect_mode or "display",
            "conversion_events": _json.dumps(body.conversion_events) if body.conversion_events else existing.conversion_events,
            "block_enabled": body.block_enabled,
            "ingest_secret": ingest_secret,  # 存量页更新也落 secret（否则 worker 带新 secret，DB 空→ingest 全 401）
            "preview_token": preview_token,
            "preview_enabled": preview_enabled,
            "subdomain_prefix": sub_prefix or existing.subdomain_prefix,
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
            publish_self_check = _run_self_check(_s2, page, include_fb=False, live_probe=False)
            page.last_health_status = publish_self_check["overall"]
            page.last_health_summary = publish_self_check["summary"]
            page.last_health_checked_at = _dt3.now(_tz3.utc)
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
        raise
    except Exception as e:
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
):
    """列 CF Pages 项目。"""
    from ..core.cf_client import CfClient
    cf_token = settings.cf_api_token
    cf_account = settings.cf_account_id
    if not cf_token or not cf_account:
        raise HTTPException(500, "CF 未配置")
    cf = CfClient(cf_token, cf_account)
    projects = cf.list_projects()
    return [{"name": p.get("name"), "subdomain": p.get("subdomain"),
             "domains": p.get("domains", [])} for p in projects]


# ── 落地页记录 CRUD（Phase A：列表/详情/改/归档）──
class PageUpdateIn(BaseModel):
    title: str | None = None
    description: str | None = None
    target_urls: list[str] | None = None
    pixel_ids: list[str] | None = None
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


def _page_to_dict(p, db: Session = None) -> dict:
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
    if db is not None:
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
    # 公开 URL（custom_domain 存的是子域名公开地址）+ 预览 URL（?_pv=token 跳过防护）
    pub_host = ""
    if p.custom_domain:
        pub_host = p.custom_domain.split("://", 1)[-1].split("/")[0]
    preview_url = (f"https://{pub_host}/?_pv={p.preview_token}"
                   if (p.preview_enabled and p.preview_token and pub_host) else "")
    visit_count = click_count = 0
    if db is not None:
        try:
            from ..models.landing_event import LandingEvent
            visit_count = db.query(LandingEvent).filter(LandingEvent.page_id == p.id, LandingEvent.event_type == "visit").count()
            click_count = db.query(LandingEvent).filter(LandingEvent.page_id == p.id, LandingEvent.event_type.in_(["click", "submit"])).count()
        except Exception:
            pass
    return {"id": p.id, "title": p.title, "status": p.status,
            "custom_domain": p.custom_domain, "custom_domains": cd_list,
            "target_urls": targets,
            "rotation_mode": p.rotation_mode, "pixel_ids": ids,
            "pixel_id": p.pixel_id, "conversion_event": p.conversion_event,
            "conversion_events": conv_events,
            "redirect_mode": p.redirect_mode or "display",
            "block_enabled": bool(p.block_enabled),
            "preview_enabled": bool(p.preview_enabled), "preview_url": preview_url,
            "subdomain_prefix": p.subdomain_prefix or "",
            "dedup_enabled": bool(p.dedup_enabled), "dedup_window_hours": p.dedup_window_hours or 24,
            "protection_rules": rules, "ingest_secret": p.ingest_secret, "template_id": p.template_id,
            "subcode_count": sub_count, "created_at": str(p.created_at or ""),
            "last_health_status": p.last_health_status,
            "last_health_summary": p.last_health_summary,
            "last_health_checked_at": str(p.last_health_checked_at or ""),
            "visit_count": visit_count, "click_count": click_count}


@router.get("/pages")
def list_landing_pages(
    user: CurrentUser = Depends(require_permission("ads.read")),
    db: Session = Depends(get_db),
):
    """列本租户落地页（status != archived），附 subcode_count。"""
    from ..models.launch import LandingPage
    rows = db.query(LandingPage).filter(
        LandingPage.tenant_id == user.tenant_id, LandingPage.status != "archived"
    ).order_by(LandingPage.id.desc()).all()
    return [_page_to_dict(p, db) for p in rows]


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
    subs = db.query(LandingAdLink).filter(
        LandingAdLink.page_id == pid, LandingAdLink.status != "archived"
    ).order_by(LandingAdLink.id.desc()).all()
    d["subcodes"] = [{"id": s.id, "slug": s.slug, "url": f"/a/{s.slug}",
                      "ad_id": s.ad_id, "act_id": s.act_id, "status": s.status} for s in subs]
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
        description=body.description or "Our product",
        target_url=cur_targets[0] if cur_targets else "https://tovaads.com",
        target_urls=body.target_urls if body.target_urls is not None else cur_targets,
        pixel_id=p.pixel_id or "",
        pixel_ids=body.pixel_ids if body.pixel_ids is not None else cur_pixels,
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
    user: CurrentUser = Depends(require_permission("ads.read")),
):
    """防护规则测试：6 类画像本地模拟（0 网络开销，瞬时返回）。"""
    rules = body.get("rules") or {}
    results = []
    for p in _PROTECTION_PROFILES:
        v = _eval_protection_py(rules, ua=p["ua"], country=p["country"], referer=p["referer"], query=p["query"])
        results.append({"label": p["label"], "blocked": v["blocked"], "reason": v["reason"]})
    blocked_count = sum(1 for r in results if r["blocked"])
    return {"profiles": results, "blocked_count": blocked_count, "pass_count": len(results) - blocked_count}


def _fb_ban_probe(db, tenant_id, url):
    """FB 平台封禁探测：调 Graph API URL scrape，判断 URL 是否被 FB 拉黑。

    返回 (status, detail)：
    - pass: FB 正常抓取（未封禁）
    - fail: 命中封禁关键词（blocked/spam/policy/violat 等）→ 疑似被封禁
    - warn: FB 爬不到（SSL/DNS/你的防护挡了 FB 爬虫）/ 令牌问题 / 无可用令牌（无法判定）
    """
    from ..core.fb_tokens import first_client
    from ..core.fb_client import FbApiError
    fb = first_client(db, tenant_id)
    if fb is None:
        return "warn", "无可用 FB 令牌，跳过封禁检测"
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


def _run_self_check(db, p, include_fb=True, live_probe=True):
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
    checks.append({"key": "status", "label": "发布状态",
                   "status": "pass" if p.status == "published" else "warn",
                   "detail": p.status or "draft"})
    # 2. 公开链接
    checks.append({"key": "url", "label": "公开链接", "status": "pass", "detail": base})
    # 3. 域名+SSL 可达（curl 根域，follow_redirects）—— live_probe=False 时跳过（发布后 CF 传播未完成会误报）
    if live_probe:
        try:
            resp = _httpx.get(base, timeout=6, follow_redirects=True,
                              headers={"User-Agent": "TovaHealthCheck/1.0"})
            ssl_ok = str(resp.url).startswith("https://")
            ok = resp.status_code < 500 and ssl_ok
            checks.append({"key": "domain", "label": "域名+SSL",
                           "status": "pass" if ok else "fail",
                           "detail": f"HTTP {resp.status_code}" + ("" if ssl_ok else " · SSL无效")})
        except Exception as e:
            checks.append({"key": "domain", "label": "域名+SSL", "status": "fail",
                           "detail": f"不可达: {str(e)[:60]}"})
    # 4. Worker 存活（/__health 无条件 200）—— live_probe=False 时跳过（已被发布 smoke 门验过）
    if live_probe:
        try:
            resp = _httpx.get(base.rstrip("/") + "/__health", timeout=6, follow_redirects=False,
                              headers={"User-Agent": "TovaHealthCheck/1.0"})
            checks.append({"key": "worker", "label": "Worker存活",
                           "status": "pass" if resp.status_code == 200 else "fail",
                           "detail": f"HTTP {resp.status_code}"})
        except Exception as e:
            checks.append({"key": "worker", "label": "Worker存活", "status": "fail",
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
                                    ad_id=sample_ad or "999999", act_id=""))
    except Exception:
        rd = None
    # 5. 像素（display 才查；redirect 模式设计上无像素=正常）
    if (p.redirect_mode or "display") == "redirect":
        checks.append({"key": "pixel", "label": "像素配置", "status": "pass",
                       "detail": "redirect 模式（无像素，正常）"})
    else:
        px = ((rd or {}).get("pixel_ids")) or []
        if px:
            _samp = f"（以广告 {sample_ad} 为样本）" if sample_ad else ""
            checks.append({"key": "pixel", "label": "像素配置", "status": "pass",
                           "detail": f"{len(px)} 个{_samp}：{','.join(str(x) for x in px)[:50]}"})
        else:
            checks.append({"key": "pixel", "label": "像素配置", "status": "warn",
                           "detail": "display 未解析到像素（页面不会 fire 转化；有意不带像素可忽略）"})
    # 6. 跳转目标（route_next 返回 + 可达性 HEAD）
    tgt = ((rd or {}).get("target_url")) or ""
    if not tgt:
        checks.append({"key": "target", "label": "跳转目标", "status": "fail", "detail": "未配置目标 URL"})
    else:
        try:
            tr = _httpx.head(tgt, timeout=5, follow_redirects=True)
            # 401/403/405 = 服务器有响应只是拒绝 HEAD（很多目标站这样）→ 算可达 pass
            reachable = tr.status_code < 400 or tr.status_code in (401, 403, 405)
            checks.append({"key": "target", "label": "跳转目标",
                           "status": "pass" if reachable else "warn",
                           "detail": f"{tgt[:40]} · HTTP {tr.status_code}"})
        except Exception as e:
            checks.append({"key": "target", "label": "跳转目标", "status": "warn",
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
        checks.append({"key": "protection", "label": "防护规则",
                       "status": "pass" if n else "warn",
                       "detail": f"已开 · {n} 条规则" if n else "已开但无规则"})
    else:
        checks.append({"key": "protection", "label": "防护规则", "status": "warn", "detail": "未开启"})
    # 8. FB 平台封禁（慢，发布时跳过）
    if include_fb:
        fb_status, fb_detail = _fb_ban_probe(db, p.tenant_id, base)
        checks.append({"key": "fb_ban", "label": "FB平台封禁", "status": fb_status, "detail": fb_detail})
    # 9. 预览模式（关=正常运营 pass；开=提醒审核完关掉 warn，避免每页都黄）
    checks.append({"key": "preview", "label": "预览模式",
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


@router.get("/pages/{pid}/health")
def health_check(
    pid: int,
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
    res = _run_self_check(db, p, include_fb=True)
    p.last_health_status = res["overall"]
    p.last_health_summary = res["summary"]
    p.last_health_checked_at = _dt.now(_tz.utc)
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
