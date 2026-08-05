# FB App Review — Permissions SOP (10 Permissions)

> **Purpose**: This is the SOP for the FB App Review of all 10 permissions. For each permission you get: (1) the business reason, (2) the exact feature in ToveAds that uses it, (3) the FB Graph API endpoint called, (4) a step-by-step screencast script to record, (5) test steps a FB reviewer can reproduce. Follow the screencast scripts to record each demo, and use the rest to fill the App Review submission for each permission.

---

## App Overview (give this to the reviewer)

**ToveAds** (`https://tovaads.com`) is a multi-tenant SaaS that manages Facebook ad campaigns for ad-agency clients. Agencies connect their FB App + ad accounts + Pages, then the platform reads ad performance, builds/pauses ads, deploys Instant Lead Forms, retrieves leads, and receives real-time leadgen webhooks — all through the FB Marketing API under the connected App.

**Test login**: provided separately by Seavey.

---

## Permissions at a Glance (10 total)

| # | Permission | Group | What it's for in ToveAds |
|---|---|---|---|
| 1 | `ads_management` | Core | Build/pause/budget/delete ads, deploy from templates, auto-pause |
| 2 | `ads_read` | Core | List ad accounts + campaign/adset/ad structure |
| 3 | `business_management` | Core | List/manage Business Manager associations |
| 4 | `pages_show_list` | Core | List Pages the user manages (for deploy/form/page pickers) |
| 5 | `pages_read_engagement` | Core | Read Page posts (follow-post reuse picker) |
| 6 | `read_insights` | Advanced | Ad performance metrics (spend, conversions, ROAS) |
| 7 | `pages_manage_ads` | Advanced | Create ads that reference a Page (object_story_spec) |
| 8 | `pages_manage_posts` | Advanced | Create Page posts (link/photo posts for ad creatives) |
| 9 | `leads_retrieval` | Advanced | Retrieve Instant Lead Form leads |
| 10 | `pages_manage_metadata` | Advanced | Subscribe Pages to leadgen webhook (real-time leads) |

(`public_profile` is also requested but doesn't require review.)

---

# Core Permissions (1–5)

## 1. `ads_management` — 创建/管理广告 / Create & Manage Ads

**Why we need it**: To create, pause, resume, edit budget, delete, and duplicate ad campaigns/ad sets/ads — both manually (user clicks) and automatically (guard-rules auto-pause, keepalive).

**Where in our system**:
- Frontend: **Ad Manager** (广告管理) — pause/activate switch, edit budget, delete, duplicate on each row; **Launch Templates** (投放模板) — bulk deploy; **Guard** — auto-pause rules
- Backend: `routers/ads.py` (status/budget/delete/batch-status), `routers/launch_templates.py` (deploy), `services/ad_ops.py` (deploy runner), `services/guard_engine.py` (auto-pause)
- FB API calls (via `app/core/fb_client.py`):
  - Create: `POST /act_{account_id}/campaigns`, `/adsets`, `/ads`, `/adcreatives`
  - Update status: `POST /{node_id}` with `status=ACTIVE|PAUSED|ARCHIVED`
  - Update budget: `POST /{node_id}` with `daily_budget` / `lifetime_budget`
  - Delete: `DELETE /{node_id}`
  - Duplicate: `POST /{node_id}/copies`

**Screencast script**:
1. Log in → **Ad Manager** → Ad tab
2. Toggle the status switch on an ad (pause → activate, or vice versa) → show status changes
3. Click ✎ edit budget on an ad set → change value → save → show updated budget
4. ⋯ menu → duplicate an ad → show the copy appears
5. (Deploy) Go to **Launch Templates** → deploy a template to one account → show success + new ad in Ad Manager

**Reviewer test steps**:
1. Ad Manager → pause an ad → verify it shows PAUSED in FB Ads Manager too
2. Edit budget → verify new budget in FB Ads Manager
3. Launch Templates → deploy → verify the new ad/campaign exists in FB Ads Manager

---

## 2. `ads_read` — 读广告结构 / Read Ad Account & Structure

**Why we need it**: To list the ad accounts a user can manage, and read the campaign → ad set → ad tree so the user sees their full account structure in ToveAds.

**Where in our system**:
- Frontend: **Tokens** page (load/import ad accounts modal), **Ad Manager** (3-level tabs: Campaign / Ad Set / Ad)
- Backend: `routers/fb.py` (loadable-accounts, import), `routers/ads.py` (list), `services/ads_cache_sync.py` (15-min cache)
- FB API calls:
  - `GET /me/adaccounts` (fields: account_id, name, currency, balance, status)
  - `GET /act_{account_id}/campaigns`, `/adsets`, `/ads`
  - `GET /{node_id}?fields=...` (node details)

**Screencast script**:
1. Log in → **Tokens** page → open the "Load accounts" modal → show the list of ad accounts pulled from FB
2. Go to **Ad Manager** → show the three tabs (Campaign / Ad Set / Ad) populated with the user's structure
3. Drill down: click a Campaign → Ad Sets under it → click an Ad Set → Ads under it

**Reviewer test steps**:
1. Tokens → Load accounts → verify the accounts match those in business.facebook.com/settings/ad-accounts
2. Ad Manager → verify campaign/adset/ad tree matches FB Ads Manager

---

## 3. `business_management` — 管理 BM / Manage Business Manager

**Why we need it**: To list the Business Manager accounts the user can access, so we can associate the right BM with their tenant and derive their permission level (basic vs full).

**Where in our system**:
- Frontend: **Tokens** page (BM association display)
- Backend: `routers/fb.py` (BM association on token import)
- FB API call: `GET /me/businesses` (fields: id, name, permitted_tasks)

**Screencast script**:
1. Log in → **Tokens** page → show the connected token's Business Manager listed (BM name + id)
2. Point at the BM info derived from `permitted_tasks`

**Reviewer test steps**:
1. Tokens → verify the BM shown matches the user's BM in business.facebook.com/settings

---

## 4. `pages_show_list` — 显示主页列表 / Show Page List

**Why we need it**: To list the Pages the user manages, so they can pick which Page to use when deploying ads, building Instant Forms, or deriving Page access tokens.

**Where in our system**:
- Frontend: **Tokens** page (load/import Pages), **Launch Templates** deploy drawer (Page dropdown), **Form Templates** (which Page to build the form on)
- Backend: `routers/fb.py` (loadable pages, import)
- FB API calls:
  - `GET /me/accounts` (fields: id, name, category, tasks) — list Pages
  - `GET /me/accounts?fields=id,access_token` — derive Page access token

**Screencast script**:
1. Log in → **Tokens** → open Pages section → show the list of managed Pages
2. **Launch Templates** → Deploy drawer → show the Page dropdown populated from FB
3. **Form Templates** → show Page picker when creating a form

**Reviewer test steps**:
1. Tokens → verify the Page list matches facebook.com/pages the user manages
2. Launch Templates deploy → verify Page dropdown shows all the user's Pages

---

## 5. `pages_read_engagement` — 读主页互动 / Read Page Engagement (Posts)

**Why we need it**: To read a Page's published posts so the "follow-post" mode can let users reuse an existing Page post as an ad creative (instead of creating a new one).

**Where in our system**:
- Frontend: **Ad Manager** → ad row ⋯ menu → "📌 Reuse this post" → opens Launch Templates with a **Post Picker** that lists the Page's existing posts
- Backend: `routers/fb.py::list_page_posts` → `GET /{page_id}/published_posts` (Page token, fields: id, message, attachments, created_time)
- FB API call: `GET /{page_id}/published_posts`

**Screencast script**:
1. Log in → **Ad Manager** → find an ad → ⋯ menu → "📌 Reuse this post"
2. In the Launch Templates form → open the **Post Picker** → show the list of the Page's published posts pulled from FB (with thumbnails + message)
3. Select a post → show it's reused as the creative

**Reviewer test steps**:
1. Ad Manager → Reuse this post → Post Picker → verify the posts listed match the Page's Posts tab on facebook.com

---

# Advanced Permissions (6–10)

## 6. `read_insights` — 广告成效数据 / Ad Performance Insights

**Why we need it**: To display ad spend, impressions, clicks, conversions, ROAS, CPA in the dashboard and ad manager. Core reporting feature — every customer sees this daily.

**Where in our system**:
- Frontend: **Dashboard** (aggregate spend/coverage/conversion per account) + **Ad Manager** (per-ad Spend/CPA/Conversion/ROAS columns)
- Backend: `routers/dashboard.py`, `routers/ads.py`, `services/kpi_resolver.py`, `services/guard_engine.py`
- FB API call: `GET /act_{account_id}/insights` (account + ad level; fields: spend, impressions, clicks, ctr, cpc, reach, frequency, actions, purchase_roas)

**Screencast script**:
1. Log in → **Dashboard** → show spend / impressions / conversions per account
2. **Ad Manager** → switch Campaign / Ad Set / Ad tabs → point at Spend, CPA, Conversion, ROAS columns
3. (Optional) DevTools → Network → show `/ads/list` returning insights data

**Reviewer test steps**:
1. Dashboard → verify spend matches FB Ads Manager for the same date range
2. Ad Manager → verify per-ad metrics are non-empty for accounts with active ads

---

## 7. `pages_manage_ads` — 通过主页管理广告 / Manage Ads via Page

**Why we need it**: When deploying ad campaigns, the ad creative is built referencing a Page (object_story_spec / object_story_id). This permission lets our App create ads that reference the connected user's Pages — required for the deploy feature.

**Where in our system**:
- Frontend: **Launch Templates** → Deploy drawer (select Page + account) → deploy
- Backend: `routers/launch_templates.py` (deploy BackgroundTasks), `services/ad_ops.py`
- FB API calls: `POST /act_{account_id}/ads` with creative `object_story_spec` (Standard Access) or `object_story_id` (dev / follow-post mode)

**Screencast script**:
1. Log in → **Launch Templates** → open a template → **Deploy** → select account + Page → confirm
2. Show progress page ending ✓
3. **Ad Manager** → show the new ad (status ACTIVE), creative references the chosen Page

> ⚠️ Note: if the connected ad account is under a FB business policy restriction (ad creation blocked), record the deploy attempt + FB error, then show an already-deployed ad to demonstrate the feature works. Seavey resolves the restriction separately.

**Reviewer test steps**:
1. Launch Templates → deploy → verify the ad appears in Ad Manager + FB Ads Manager (ACTIVE)

---

## 8. `pages_manage_posts` — 建主页帖 / Create Page Posts

**Why we need it**: To create Page posts that ad creatives reference (link posts for landing-page ads, photo posts for Page-Like/keepalive ads). Two modes: **new post** via `object_story_spec`, or **reuse existing post** via `object_story_id`.

**Where in our system**:
- Frontend: **Launch Templates** deploy (new post), **Ad Manager** ⋯ → "📌 Reuse this post" (follow-post)
- Backend: `app/core/page_post.py::get_or_create_page_post` (caches "same page + asset + copy" to avoid duplicates)
- FB API calls:
  - Link post: `POST /{page_id}/feed` (message + link)
  - Photo post: `POST /{page_id}/photos` (url + message + published=true)
  - Ad creative built with `object_story_id` (created post) or `object_story_spec`

**Screencast script**:
1. Log in → **Launch Templates** → deploy a template (creates Page post + ad)
2. After ✓ → open the Page on facebook.com → show the new post in the Page's Posts tab
3. (Follow-post) **Ad Manager** → ad with existing post → ⋯ → "📌 Reuse this post" → form pre-filled with that post's `object_story_id`

**Reviewer test steps**:
1. Deploy template → verify the post appears on facebook.com/{page}/posts
2. Ad Manager → Reuse this post → verify form pre-filled with existing post id

---

## 9. `leads_retrieval` — 读潜客数据 / Retrieve Lead Form Leads

**Why we need it**: To pull lead data (name, email, phone, custom answers) submitted via Instant Lead Forms, so agencies see and export leads inside ToveAds instead of FB's Lead Center.

**Where in our system**:
- Frontend: **Ad Manager** → **Leads (潜客)** tab (4th tab) → lead list + **"⟳ Sync from FB"** button
- Backend: `routers/leads.py` — `GET /leads`, `POST /leads/sync`
- FB API call: `GET /{form_id}/leads` (fields: id, created_time, field_data, ad_id, form_id) — `fb_client.get_leads`

**Screencast script**:
1. Log in → **Ad Manager** → **Leads** tab
2. Click **"⟳ Sync from FB"** → success toast ("N synced")
3. Show the leads table — Name / Email / Phone / source columns + custom-field chips
4. (Optional) DevTools → Network → show `/leads/sync` + `/leads` calls

**Reviewer test steps**:
1. Ad Manager → Leads → Sync → verify leads appear (test Page needs a published Instant Form with submissions)
2. Cross-check lead count with FB Lead Center for that form

---

## 10. `pages_manage_metadata` — 订阅主页 Webhook / Subscribe to Page Webhooks

**Why we need it**: To receive **real-time leadgen callbacks** the moment a lead submits an Instant Form (instead of polling). The App subscribes to each Page's `leadgen` field; FB pushes new leads to our webhook endpoint, where we verify the X-Hub-Signature-256 HMAC with the App Secret, then store the lead.

**Where in our system**:
- Frontend:
  - **Settings → FB Webhook** card (superadmin): shows public Callback URL + Verify Token + count of configured Apps (HMAC source)
  - **Ad Manager → Leads tab → "🔔 Subscribe Page Webhook"**: subscribes all user's Pages to leadgen
- Backend:
  - `GET /fb/webhook` (FB subscription verification: echoes `hub.challenge`)
  - `POST /fb/webhook` (FB leadgen callback: verifies `X-Hub-Signature-256` HMAC against App Secrets, then stores the lead)
  - `POST /leads/subscribe` (iterates `me/accounts`, subscribes each Page)
- FB API call: `POST /{page_id}/subscribed_apps` with `subscribed_fields=leadgen`

**Webhook configuration (already done by Seavey)**:
- Callback URL: `https://api.tovaads.com/fb/webhook`
- Verify Token: configured in Settings → FB Webhook (matches FB App Dashboard)
- Subscribed field: `leadgen` ✓

**Screencast script**:
1. Log in → **Settings → FB Webhook** → show Callback URL (`https://api.tovaads.com/fb/webhook`), "N Apps configured" chip, Verify Token field
2. **Ad Manager → Leads tab** → click **"🔔 Subscribe Page Webhook"** → success toast ("Subscribed N/M pages")
3. (Real-time demo) Submit a test lead on the Page's Instant Form → back to Leads tab → Refresh → new lead appears (delivered via webhook)
4. (Optional) Show FB App Dashboard → Webhooks → Callback URL shows ✓ Verified, `leadgen` checked

**Reviewer test steps**:
1. Settings → FB Webhook: verify Callback URL is HTTPS + a Verify Token is set
2. Ad Manager → Leads → Subscribe → success toast shows Pages subscribed
3. Submit a test lead → verify it appears in Leads tab within seconds (webhook delivery)

---

## Security & Data Handling Notes (for reviewer)

- **App Secret storage**: encrypted at rest (Fernet) in the `fb_apps` table; webhook HMAC verification decrypts in memory only — never logged or returned to the frontend.
- **Webhook signature verification**: every `POST /fb/webhook` is verified via `X-Hub-Signature-256` HMAC-SHA256 against all active App Secrets (constant-time compare). Forged or unsigned requests → 403.
- **Lead data**: stored in a multi-tenant PostgreSQL DB with Row-Level Security; each tenant only sees leads whose `form_id` maps to their own `LeadFormTemplate`. Webhook resolves tenant via `form_id → LeadFormTemplate → tenant_id`; unmatched leads are discarded (not stored).
- **Verify Token**: stored in `system_settings`, editable only by superadmin, masked in the UI.
- **No data resale / no sharing with third parties**: all data (ad performance, leads, posts) is used solely by the agency that owns the connected ad account.

---

## Screencast Production Checklist (10 videos)

| # | Permission | Demo path | Est. duration |
|---|---|---|---|
| 1 | ads_management | Ad Manager (pause/budget/duplicate) + Launch Templates deploy | ~60s |
| 2 | ads_read | Tokens load accounts + Ad Manager 3-level drilldown | ~45s |
| 3 | business_management | Tokens page BM association | ~30s |
| 4 | pages_show_list | Tokens Pages + Launch Templates Page dropdown | ~40s |
| 5 | pages_read_engagement | Ad Manager → Reuse this post → Post Picker | ~40s |
| 6 | read_insights | Dashboard + Ad Manager data columns | ~45s |
| 7 | pages_manage_ads | Launch Templates deploy → Ad Manager shows new ad | ~60s |
| 8 | pages_manage_posts | Deploy creates post → show on facebook.com Page | ~45s |
| 9 | leads_retrieval | Ad Manager → Leads tab → Sync → leads appear | ~45s |
| 10 | pages_manage_metadata | Settings FB Webhook + Subscribe button + live lead | ~60s |

**Tip — recording order**:
- Permissions **2, 4, 6, 9, 10** don't need ad creation → record these first (works even with the current policy restriction).
- Permissions **1, 3, 5, 7, 8** need ad/post creation. If the connected business is under policy restriction, record what you can (load lists, show FB error) + show already-existing ads/posts as proof; redo the full demo after Seavey gets the restriction lifted.

---

## Open Items (Seavey to handle)

- [ ] Provide test login credentials (a user with a connected App + ad accounts + Pages) to Saurabh / FB reviewer
- [ ] Resolve the FB business policy restriction on the connected business (blocks ad-creation demos for permissions 1, 7, 8)
- [ ] Deploy at least one Instant Lead Form on the test Page (so permissions 9 & 10 have real leads to show)
- [ ] Confirm whether FB requires submitting the 10 permissions in batches or all at once (Saurabh to advise)
