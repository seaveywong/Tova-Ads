# 落地页模板规范（landing_template_spec.md）

> 改你的真实落地页 HTML 时照这个规范来。系统发布时自动替换占位符 + 注入像素脚本。

## 必填占位符（缺一不可，.zip 上传时校验）

| 占位符 | 位置 | 替换为 | 说明 |
|---|---|---|---|
| `{{TITLE}}` | `<title>` | 落地页标题 | SEO + 浏览器标签 |
| `__LP_TARGET_URL__` | CTA 按钮的 `href` | 目标跳转链接 | 用户点按钮跳到这 |
| `__LP_PIXELS_JSON__` | `<script>` 内 | `["像素ID1","像素ID2"]` | FB 像素 ID 数组 |

## 可选占位符（不填 = 该功能不 fire，不影响发布）

| 占位符 | 替换为 | 说明 |
|---|---|---|
| `{{DESCRIPTION}}` | 页面描述 | SEO meta description |
| `__LP_CONV_EVENT_JSON__` | `["Purchase","Contact"]` | FB 转化事件 |
| `__LP_TT_PIXELS_JSON__` | `["C111","C222"]` | TK 像素 ID 数组 |
| `__LP_TT_CONV_JSON__` | `["CompletePayment","SubmitForm"]` | TK 转化事件 |

## CTA 按钮规范

按钮**必须**带 `onclick="return goNext(event)"` 或 `id="cta"`：

```html
<!-- 方式一（推荐）-->
<a href="__LP_TARGET_URL__" id="cta" onclick="return goNext(event)">立即购买</a>

<!-- 方式二 -->
<a href="__LP_TARGET_URL__" onclick="return goNext(event)">立即购买</a>
```

系统注入的脚本会：
1. 把 `href` 替换为 route_next 返回的真实目标 URL
2. 点击时 fire 所有配置的像素转化事件（FB + TK）
3. 300ms 后跳转

## 像素脚本（系统自动注入，模板里不用写）

系统在发布时往 `<head>` 注入两段脚本：

### FB 像素解码（`_d_decode`）
- 从 URL 参数 `_d` 读取动态像素（广告流量）
- 无 `_d` 时用 `__LP_PIXELS_JSON__`（直访 fallback）
- fire `fbq('init')` + `fbq('trackSingle', 'PageView')`
- 点击 CTA → `fbq('trackSingle', 事件)` per 像素 × 事件

### TK 像素解码（`_d_decode_tt`）
- 从 URL 参数 `_d` 读取 `tp`（TK 像素）+ `tc`（转化事件）+ `eid`（event_id）
- 无 `_d` 时用 `__LP_TT_PIXELS_JSON__`（直访 fallback）
- fire `ttq.load()` + `ttq.page()`
- 点击 CTA → `ttq.track(事件, {event_id})` per 事件
- event_id 和后端 S2S 同 UUID → TK 去重

## 最简模板示例

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{TITLE}}</title>
<script>
// FB 像素（直访 fallback；广告流量由系统注入的 _d_decode 覆盖）
var LP_PIXELS=__LP_PIXELS_JSON__||[];
var LP_TT_PIXELS=__LP_TT_PIXELS_JSON__||[];
var LP_CONV=__LP_CONV_EVENT_JSON__||[];
var LP_TT_CONV=__LP_TT_CONV_JSON__||[];
var LP_TARGET_URL="__LP_TARGET_URL__";

// FB Pixel loader
!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;
n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,
document,'script','https://connect.facebook.net/en_US/fbevents.js');
LP_PIXELS.forEach(function(pid){if(pid){fbq('init',pid);fbq('trackSingle',pid,'PageView');}});

// TK Pixel loader（有 TK 像素才加载）
if(LP_TT_PIXELS.length){
!function(w,d,t){w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];
ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie"];
ttq.setAndDefer=function(t,e){t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};
for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);
ttq.load=function(e){var i="https://analytics.tiktok.com/i18n/pixel/events.js";
ttq._i=ttq._i||{};ttq._i[e]=[];ttq._i[e]._u=i;ttq._t=ttq._t||{};ttq._t[e]=+new Date;
ttq._o=ttq._o||{};ttq._o[e]={};
var o=d.createElement("script");o.type="text/javascript";o.async=!0;o.src=i+"?sdkid="+e+"&lib="+t;
var a=d.getElementsByTagName("script")[0];a.parentNode.insertBefore(o,a);};
LP_TT_PIXELS.forEach(function(pid){if(pid)ttq.load(pid);});
ttq.page();
}(window,document,'ttq');
}

// 转化追踪（点击 CTA 时 fire）
function trackConversion(){
  if(window.fbq&&LP_PIXELS.length&&LP_CONV.length)
    LP_PIXELS.forEach(function(pid){LP_CONV.forEach(function(evt){fbq('trackSingle',pid,evt);});});
  if(window.ttq&&LP_TT_CONV.length)
    LP_TT_CONV.forEach(function(evt){ttq.track(evt);});
}
function goNext(ev){if(ev&&ev.preventDefault)ev.preventDefault();trackConversion();
  setTimeout(function(){window.location.href=LP_TARGET_URL;},300);return false;}
</script>
</head>
<body>
<h1>{{TITLE}}</h1>
<p>{{DESCRIPTION}}</p>
<a href="__LP_TARGET_URL__" id="cta" onclick="return goNext(event)">立即购买</a>
</body>
</html>
```

## .zip 上传要求
- 压缩包内必须有 `index.html`
- `index.html` 必须含 3 个必填占位符
- 总大小 ≤ 10MB，解压后 ≤ 50MB
- 文件数 ≤ 100
- TK 占位符可选（不写 = TK 直访不 fire，广告流量仍 fire）

## 子码 URL 规范

广告 URL 参数：
```
https://lp6.xxx.com/a/{子码}?ad={ad_id}&act={act_id}
```

- FB 广告：填 `?ad={{ad.id}}` （FB 宏自动替换）
- TK 广告：填 `?ad=<你的TK广告ID>` （TK 无宏，手填或脚本填）
- 系统提取 `ad` 参数用于子码绑定 + 追踪
- **无 ad 参数也能访问**（ad_id 为空，仍正常展示落地页 + fire 像素）
