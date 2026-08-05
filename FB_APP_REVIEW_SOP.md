# FB App Review — Batch 2 Permissions SOP

> **中文导读（给 Seavey）**：这份文档给 Saurabh（reviewer）和 FB 审核员看。下面 5 个权限，每个都写清楚了：**我们为什么需要它 → 系统里哪个功能在用 → 调的 FB API → 录屏怎么录 → 审核员怎么测**。Saurabh 拿着这份就能写审核申请 + 录屏。文档主体英文（给他和审核员），每节标题带中文方便你定位。
>
> **How to use this doc (for Saurabh)**: For each of the 5 permissions below, you get (1) the business reason, (2) the exact feature in our app that uses it, (3) the FB Graph API endpoint called, (4) a step-by-step screencast script to record, and (5) test steps a FB reviewer can reproduce. Use this to fill the App Review submission and record the demos.

---

## App Overview (give this to the reviewer)

**ToveAds** is a multi-tenant SaaS that manages Facebook ad campaigns for ad-agency clients. Agencies connect their FB App + ad accounts, then the platform reads ad performance, builds/pauses ads, deploys Instant Lead Forms, and retrieves leads — all through the FB Marketing API under the connected App.

**Login URL for testing**: `https://tovaads.com` (test credentials provided separately by Seavey).

---

## 1. `read_insights` — 广告成效数据 / Ad Performance Insights

**Why we need it**: To display ad spend, impressions, clicks, conversions, ROAS, CPA in the dashboard and ad manager. Core reporting feature — every customer sees this data daily.

**Where in our system**:
- Frontend: **Dashboard** page (aggregate spend/coverage/conversion per account) + **Ad Manager** page (per-ad spend/CPA/conversion columns)
- Backend endpoints: `GET /dashboard/summary`, `GET /ads/list`
- FB API call: `GET /act_{account_id}/insights` (account + ad level, fields: spend, impressions, clicks, ctr, cpc, reach, frequency, actions, purchase_roas)

**Screencast script** (record this):
1. Log in to `https://tovaads.com` → land on the **Dashboard** (数据看板)
2. Show the dashboard populated with spend / impressions / conversions per ad account (point to the numbers)
3. Click into **Ad Manager** (广告管理) → switch between Campaign / Ad Set / Ad tabs
4. Point at the Spend, CPA, Conversion, ROAS columns — explain these come from FB Insights
5. (Optional) Open browser DevTools → Network → show the `/ads/list` request returning insights data

**Reviewer test steps**:
1. Log in with the test account
2. Open Dashboard → verify spend numbers match what's in the connected ad account's FB Ads Manager
3. Open Ad Manager → verify per-ad metrics are non-empty for accounts with active ads

---

## 2. `pages_manage_ads` — 通过主页管理广告 / Manage Ads via Page

**Why we need it**: When deploying ad campaigns from a template, the ad creative is built using a Page (object_story_spec / object_story_id). This permission lets our App create/manage ads that reference the connected user's Pages — required for the bulk-deploy feature.

**Where in our system**:
- Frontend: **Launch Templates** (投放模板) page → select template → **Deploy** drawer → choose accounts + Page → deploy
- Backend endpoint: `POST /launch-templates/{id}/deploy` (async BackgroundTasks, per-account)
- FB API calls: `POST /act_{account_id}/ads` (create ad), `POST /act_{account_id}/adsets`, `POST /act_{account_id}/campaigns` — creative references the Page via `object_story_spec` or `object_story_id`

**Screencast script**:
1. Log in → go to **Launch Templates** (投放模板)
2. Open an existing template (or create one: name + objective + budget + creative asset)
3. Click **Deploy** (部署) → select one ad account + one Page → confirm
4. Show the progress page (per-account success/fail) ending in ✓
5. Open **Ad Manager** → show the newly created campaign/ad set/ad (status ACTIVE)

> ⚠️ Note: if the connected ad account is currently under a FB business policy restriction (ad creation blocked), record the deploy attempt showing the FB error response, then show an **already-deployed** ad from a previous successful deploy to demonstrate the feature works. Seavey will resolve the policy restriction separately.

**Reviewer test steps**:
1. Log in → Launch Templates → deploy a template to the test account
2. Verify the ad appears in Ad Manager with ACTIVE status
3. Cross-check the ad exists in the test account's FB Ads Manager

---

## 3. `pages_manage_posts` — 建主页帖 / Create Page Posts

**Why we need it**: To create Page posts that ad creatives reference (link posts for landing-page ads, photo posts for Page-Like/keepalive ads). Two modes: **new post** via `object_story_spec` (Standard Access) or **reuse existing post** via `object_story_id` (our "follow-post" mode).

**Where in our system**:
- Frontend: **Launch Templates** deploy (new post) + **Ad Manager** ad row ⋯ menu → "📌 Reuse this post" (follow-post)
- Backend: `app/core/page_post.py` → `get_or_create_page_post` (caches "same page + same asset + same copy" to avoid duplicate posts)
- FB API calls:
  - Link post: `POST /{page_id}/feed` (message + link)
  - Photo post: `POST /{page_id}/photos` (url + message + published=true)
  - Ad creative built with `object_story_id` referencing the created post, or `object_story_spec` for direct creation

**Screencast script**:
1. Log in → **Launch Templates** → deploy a template (this creates the Page post + the ad)
2. After deploy ✓ → open the Page on facebook.com → show the new post in the Page's Posts tab
3. (Follow-post mode) Go to **Ad Manager** → find an ad with an existing post → ⋯ menu → "📌 Reuse this post" → show it jumps to Launch Templates pre-filled with that post's `object_story_id`

**Reviewer test steps**:
1. Deploy a template → verify the post appears on the connected Page (facebook.com/{page}/posts)
2. In Ad Manager, trigger "Reuse this post" → verify the Launch Templates form is pre-filled with the existing post id

---

## 4. `leads_retrieval` — 读潜客数据 / Retrieve Lead Form Leads

**Why we need it**: To pull the lead data (name, email, phone, custom answers) submitted via Instant Lead Forms, so agencies see and export their leads inside ToveAds instead of FB's Lead Center.

**Where in our system**:
- Frontend: **Ad Manager** → **Leads (潜客)** tab (4th tab) → shows lead list (submitted time, name, email, phone, source, custom fields) + **"Sync from FB"** button
- Backend endpoints: `GET /leads` (list local), `POST /leads/sync` (pull from FB)
- FB API call: `GET /{form_id}/leads` (fields: id, created_time, field_data, ad_id, form_id) — `app/core/fb_client.py::get_leads`

**Screencast script**:
1. Log in → **Ad Manager** → click the **Leads (潜客)** tab
2. Click **"⟳ Sync from FB"** (从 FB 同步) button → wait for the success toast ("N synced")
3. Show the populated leads table — point at Name / Email / Phone columns + the "source" column (which form/ad)
4. (Optional) DevTools → Network → show the `/leads/sync` POST + the `/leads` GET returning the data

**Reviewer test steps**:
1. Log in → Ad Manager → Leads tab → click Sync
2. Verify leads appear (if the test Page has a published Instant Form with test submissions)
3. Cross-check lead count roughly matches FB's Lead Center for that form

---

## 5. `pages_manage_metadata` — 订阅主页 Webhook / Subscribe to Page Webhooks

**Why we need it**: To receive **real-time leadgen callbacks** the moment a lead submits an Instant Form (instead of polling). The App subscribes to each Page's `leadgen` field; FB pushes new leads to our webhook endpoint, where we verify the X-Hub-Signature-256 HMAC with the App Secret, then store the lead.

**Where in our system**:
- Frontend:
  - **Settings → FB Webhook** card (superadmin): shows the public Callback URL + Verify Token + count of configured Apps (HMAC verify source)
  - **Ad Manager → Leads tab → "🔔 Subscribe Page Webhook"** button: subscribes all the user's Pages to leadgen
- Backend endpoints:
  - `GET /fb/webhook` (FB subscription verification: `hub.mode=subscribe` + `hub.verify_token` → echoes `hub.challenge`)
  - `POST /fb/webhook` (FB leadgen callback: verifies `X-Hub-Signature-256` HMAC against App Secrets, then stores the lead)
  - `POST /leads/subscribe` (iterates `me/accounts`, subscribes each Page)
- FB API calls:
  - `POST /{page_id}/subscribed_apps` with `subscribed_fields=leadgen` (per-Page subscription, uses Page access token)

**Webhook configuration (already done by Seavey)**:
- Callback URL: `https://api.tovaads.com/fb/webhook`
- Verify Token: configured in Settings → FB Webhook (matches FB App Dashboard)
- Subscribed field: `leadgen`

**Screencast script**:
1. Log in → **Settings** → scroll to **FB Webhook** card → show the Callback URL (`https://api.tovaads.com/fb/webhook`), "N Apps configured (verify source)" chip, and Verify Token field
2. Go to **Ad Manager → Leads tab** → click **"🔔 Subscribe Page Webhook"** → show success toast ("Subscribed N/M pages")
3. Show a lead arriving in real time: submit a test lead on the connected Page's Instant Form → return to the Leads tab → click Refresh → the new lead appears (delivered via webhook)
4. (Optional) Show FB App Dashboard → Webhooks → the Callback URL shows ✓ Verified, `leadgen` field checked

**Reviewer test steps**:
1. Log in → Settings → FB Webhook: verify Callback URL is HTTPS and a Verify Token is set
2. Ad Manager → Leads tab → Subscribe → verify success toast shows Pages subscribed
3. Submit a test lead on the test Page's Instant Form → verify it appears in the Leads tab within a few seconds (webhook delivery)

---

## Security & Data Handling Notes (for reviewer)

- **App Secret storage**: encrypted at rest (Fernet) in the `fb_apps` table; webhook HMAC verification decrypts in memory only, never logged or returned to frontend.
- **Webhook signature verification**: every `POST /fb/webhook` is verified via `X-Hub-Signature-256` HMAC-SHA256 against all active App Secrets (constant-time compare). Forged or unsigned requests → 403.
- **Lead data**: stored in a multi-tenant DB with Row-Level Security; each tenant can only see leads whose `form_id` maps to their own `LeadFormTemplate`. Webhook looks up tenant via `form_id → LeadFormTemplate → tenant_id`; unmatched leads are discarded (not stored).
- **Verify Token**: stored in `system_settings`, editable only by superadmin, masked in the UI.
- **No data resale / no sharing with third parties**: leads are used solely by the agency that owns the connected ad account.

---

## Screencast Production Checklist

| Permission | Demo path | Min duration |
|---|---|---|
| read_insights | Dashboard + Ad Manager data columns | ~45s |
| pages_manage_ads | Launch Templates → deploy → Ad Manager shows new ad | ~60s |
| pages_manage_posts | Deploy creates Page post → show on facebook.com Page | ~45s |
| leads_retrieval | Ad Manager → Leads tab → Sync → leads appear | ~45s |
| pages_manage_metadata | Settings FB Webhook + Subscribe button + (ideally) live lead | ~60s |

**Tip**: record all 5 in one sitting if the connected account is healthy (no policy restriction). If ad creation is blocked, record 1/4/5 first (they don't need ad creation), and do 2/3 after the policy restriction is lifted.

---

## Open Items (Seavey to handle, not blocking doc)

- [ ] First batch of 5 permissions (ads_management etc.) — confirm approval status before submitting batch 2
- [ ] Resolve FB business policy restriction on the connected business (blocks ad-creation demos for permissions 2 & 3)
- [ ] Provide test login credentials to Saurabh / FB reviewer
- [ ] (Optional) Deploy at least one Instant Lead Form so permissions 4 & 5 have real leads to show
