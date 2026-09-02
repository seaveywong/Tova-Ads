"""Cloudflare API 客户端：Pages 项目管理 + Direct Upload 部署 + DNS。

用 CF API Token 操作：
- 创建/查 Pages 项目
- Direct Upload（manifest + upload JWT + check-missing + upload + deploy）
- DNS CNAME 绑定自定义域名
"""
import hashlib
import logging
import httpx
from typing import Any

logger = logging.getLogger("toveads.cf")

CF_API_BASE = "https://api.cloudflare.com/client/v4"


class CfClient:
    def __init__(self, api_token: str, account_id: str):
        self.token = api_token
        self.account_id = account_id
        self.headers = {"Authorization": f"Bearer {api_token}"}

    def _get(self, path: str, **kwargs) -> dict:
        r = httpx.get(f"{CF_API_BASE}{path}", headers=self.headers, timeout=30, **kwargs)
        try:
            return r.json()
        except Exception:
            # CF 有些端点对不支持的 auth 方案返回纯文本（如 Email Routing 对账户级
            # token 返回 404 "page not found"）——不炸，返回可判定的错误形状
            return {"success": False, "errors": [{"code": r.status_code,
                     "message": f"CF returned non-JSON (HTTP {r.status_code}): {r.text[:120]}"}]}

    def _post(self, path: str, **kwargs) -> dict:
        r = httpx.post(f"{CF_API_BASE}{path}", headers=self.headers, timeout=60, **kwargs)
        try:
            return r.json()
        except Exception:
            return {"success": False, "errors": [{"code": r.status_code,
                     "message": f"CF returned non-JSON (HTTP {r.status_code}): {r.text[:120]}"}]}

    # ── Pages 项目 ──
    def list_projects(self) -> list:
        data = self._get(f"/accounts/{self.account_id}/pages/projects")
        return data.get("result", []) if data.get("success") else []

    def get_project(self, name: str) -> dict | None:
        data = self._get(f"/accounts/{self.account_id}/pages/projects/{name}")
        return data.get("result") if data.get("success") else None

    def create_project(self, name: str) -> dict:
        """创建 Pages 项目。"""
        data = self._post(
            f"/accounts/{self.account_id}/pages/projects",
            json={"name": name, "production_branch": "main"},
        )
        if not data.get("success"):
            errs = data.get("errors", [])
            # 已存在不算错
            if any("exists" in str(e).lower() for e in errs):
                return self.get_project(name) or {}
            raise RuntimeError(f"CF 创建项目失败: {errs}")
        return data["result"]

    def get_upload_token(self, project_name: str) -> dict:
        """获取 Direct Upload JWT + 相关信息。"""
        data = self._get(
            f"/accounts/{self.account_id}/pages/projects/{project_name}/upload_token"
        )
        if not data.get("success"):
            raise RuntimeError(f"获取 upload JWT 失败: {data.get('errors')}")
        return data["result"]

    def deploy_via_wrangler(self, project_name: str, files: dict[str, str]) -> dict:
        """用 wrangler CLI 部署 Pages（Direct Upload 的 upload_token JWT 接口已变，wrangler 更稳）。

        files = {"index.html": "...", "_worker.js": "..."}。写临时目录 → wrangler pages deploy。
        wrangler 用 CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID 环境变量。
        """
        import subprocess, tempfile, shutil, os, re
        # 确保项目存在（CF API；wrangler deploy 不自动建项目）
        if not self.get_project(project_name):
            try:
                self.create_project(project_name)
            except RuntimeError:
                pass  # 已存在/CF 错，wrangler 会再报
        tmp = tempfile.mkdtemp(prefix="tovaads_lp_")
        try:
            for path, content in files.items():
                full = os.path.join(tmp, path)
                parent = os.path.dirname(full)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(content)
            env = {**os.environ,
                   "CLOUDFLARE_API_TOKEN": self.token,
                   "CLOUDFLARE_ACCOUNT_ID": self.account_id}
            r = subprocess.run(
                ["wrangler", "pages", "deploy", tmp,
                 "--project-name", project_name, "--branch", "main"],
                capture_output=True, text=True, env=env, timeout=120,
            )
            out = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0:
                raise RuntimeError(f"wrangler deploy 失败 (rc={r.returncode}): {out[-500:]}")
            url = ""
            m = re.search(r"https://[\w.-]+\.pages\.dev", out)
            if m:
                url = m.group(0)
            logger.info(f"[CF] wrangler deployed {project_name} -> {url}")
            return {"url": url, "id": "", "raw": out[-300:]}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def deploy_files(self, project_name: str, files: dict[str, str]) -> dict:
        """Direct Upload 部署（manifest 模式）。

        files = {"index.html": "<html>...", "_worker.js": "addEventListener(...)", ...}
        """
        # 1. 算 hash
        file_hashes = {}
        for path, content in files.items():
            h = hashlib.sha1(content.encode()).hexdigest()
            file_hashes[path] = h

        # 2. 拿 JWT（result 可能是 str 或 dict）
        token_result = self.get_upload_token(project_name)
        if isinstance(token_result, dict):
            jwt = token_result.get("jwt", "")
        else:
            jwt = str(token_result)
        if not jwt:
            raise RuntimeError("upload JWT 为空")

        # 3. check-missing
        headers = {"Authorization": f"Bearer {jwt}"}
        check_payload = {"hashes": list(file_hashes.values())}
        check = httpx.post(
            f"https://api.cloudflare.com/client/v4/pages/assets/check-missing",
            headers=headers, json=check_payload, timeout=30,
        )
        missing_hashes = set(check.json().get("result", []))

        # 4. upload missing files
        for path, content in files.items():
            h = file_hashes[path]
            if h not in missing_hashes:
                continue
            httpx.post(
                f"https://api.cloudflare.com/client/v4/pages/assets/upload",
                headers={**headers, "Content-Type": "application/octet-stream"},
                params={"fileName": path, "id": h},
                content=content.encode(),
                timeout=60,
            )
            logger.info(f"[CF] uploaded {path}")

        # 5. create deployment
        manifest = {path: h for path, h in file_hashes.items()}
        deploy = httpx.post(
            f"https://api.cloudflare.com/client/v4/pages/assets/deploy",
            headers={**headers, "Content-Type": "application/json"},
            params={"projectName": project_name},
            json={"manifest": manifest, "branch": "main"},
            timeout=60,
        )
        result = deploy.json()
        if not result.get("success"):
            raise RuntimeError(f"CF deploy 失败: {result.get('errors')}")
        return result["result"]

    # ── DNS ──
    def get_zone_id(self, domain: str) -> str | None:
        """从域名找 Zone ID。"""
        # 提取根域名（如 a.example.com → example.com）
        parts = domain.rstrip(".").split(".")
        root = ".".join(parts[-2:]) if len(parts) >= 2 else domain
        data = self._get("/zones", params={"name": root})
        zones = data.get("result", [])
        return zones[0]["id"] if zones else None

    def list_zones(self) -> list:
        """列 CF 账户所有 zone（平台发现域名池用，落地页重做 ③）。自动翻页。"""
        out: list[dict] = []
        page = 1
        while page <= 20:  # 安全上限 20 页 = 1000 zone
            data = self._get("/zones", params={"per_page": 50, "page": page})
            result = data.get("result", []) if data.get("success") else []
            out.extend(result)
            if len(result) < 50:
                break
            page += 1
        return out

    def add_cname(self, zone_id: str, name: str, target: str) -> dict:
        """添加 CNAME 记录。"""
        data = self._post(
            f"/zones/{zone_id}/dns_records",
            json={"type": "CNAME", "name": name, "content": target, "proxied": True},
        )
        return data.get("result", {})

    def bind_custom_domain(self, project_name: str, domain: str) -> dict:
        """给 Pages 项目绑自定义域名 + 自动加 DNS CNAME。

        CF Pages 绑 custom domain 不会自动加 DNS 记录——缺 CNAME 则验证永远 pending、
        SSL 颁不下来、HTTP 不通（marketbriefnow.xyz 就是这个坑）。
        子域名 → CNAME 前缀；根域(apex) → @（CF CNAME flattening）。target=<project>.pages.dev。
        """
        data = self._post(
            f"/accounts/{self.account_id}/pages/projects/{project_name}/domains",
            json={"name": domain},
        )
        zone_id = self.get_zone_id(domain)
        if zone_id:
            parts = domain.rstrip(".").split(".")
            root = ".".join(parts[-2:]) if len(parts) >= 2 else domain
            # CNAME 记录名：子域名取前缀，根域用 @
            name = (domain[:-(len(root) + 1)].rstrip(".")
                    if (domain.endswith("." + root) and len(parts) > 2) else "@")
            target = f"{project_name}.pages.dev"
            try:
                self.add_cname(zone_id, name, target)
                logger.info(f"[CF] CNAME {name}.{root} → {target}")
            except Exception as e:
                logger.warning(f"[CF] add_cname {name}.{root} 可能已存在: {e}")
        return data.get("result", {})

    # ── Email Routing（平台域邮箱转发，tovaads.com 用）──
    # 权限模型（2026-09 实测）：规则/DNS 是 zone 级权限；目的地地址是 account 级权限
    # 且端点已迁到 /accounts/{acct}/email/routing/addresses（zone 老路径返回 403/404）。
    def get_email_routing(self, zone_id: str) -> dict | None:
        """Email Routing 设置（result.status: unconfigured/uninitialized/enabled/disabled）。

        未初始化时 CF 返回 success=false → None（视为 unconfigured）。
        用户级邮箱 token 缺 Zone Settings:Read 时状态端点 403 → 用 MX 记录兜底判定。
        """
        data = self._get(f"/zones/{zone_id}/email/routing")
        if data.get("success"):
            return data.get("result")
        try:
            mx = [r for r in self.list_dns_records(zone_id)
                  if r.get("type") == "MX" and "mx.cloudflare.net" in (r.get("content") or "")]
            if mx:
                return {"status": "ready", "enabled": True}
        except Exception:
            pass
        return None

    def enable_email_routing(self, zone_id: str) -> dict:
        data = self._post(f"/zones/{zone_id}/email/routing/enable")
        if not data.get("success"):
            raise RuntimeError(f"CF 启用 Email Routing 失败: {data.get('errors')}")
        return data.get("result", {})

    def get_email_dns(self, zone_id: str) -> list:
        """Email Routing 所需 DNS 记录（MX×3 + SPF TXT，含 priority/proxied）。

        dns 端点同样需要 Zone Settings:Read——失败时返回 CF 标准记录集兜底。
        """
        data = self._get(f"/zones/{zone_id}/email/routing/dns")
        if data.get("success"):
            return data.get("result", [])
        return [
            {"type": "MX", "name": "@", "content": "route1.mx.cloudflare.net", "priority": 13, "proxied": False},
            {"type": "MX", "name": "@", "content": "route2.mx.cloudflare.net", "priority": 86, "proxied": False},
            {"type": "MX", "name": "@", "content": "route3.mx.cloudflare.net", "priority": 89, "proxied": False},
            {"type": "TXT", "name": "@", "content": "v=spf1 include:_spf.mx.cloudflare.net ~all"},
        ]

    def list_dns_records(self, zone_id: str) -> list:
        """zone 全量 DNS 记录（自动翻页，对比 Email Routing 缺口用）。"""
        out: list[dict] = []
        page = 1
        while page <= 20:
            data = self._get(f"/zones/{zone_id}/dns_records",
                             params={"per_page": 100, "page": page})
            result = data.get("result", []) if data.get("success") else []
            out.extend(result)
            if len(result) < 100:
                break
            page += 1
        return out

    def add_dns_record(self, zone_id: str, record: dict) -> dict:
        """添加 DNS 记录（Email Routing 的 MX/TXT 补齐；proxied 传 False）。"""
        data = self._post(f"/zones/{zone_id}/dns_records", json=record)
        if not data.get("success"):
            raise RuntimeError(f"CF 添加 DNS 记录失败: {data.get('errors')}")
        return data.get("result", {})

    def list_email_addresses(self, zone_id: str) -> list:
        """目的地邮箱列表（含验证状态；自动翻页）。

        端点是 account 级（/accounts/{acct}/email/routing/addresses，地址属帐户共享）；
        zone_id 参数保留兼容签名，实际不参与路径。
        """
        out: list[dict] = []
        page = 1
        while page <= 10:
            data = self._get(f"/accounts/{self.account_id}/email/routing/addresses",
                             params={"per_page": 50, "page": page})
            result = data.get("result", []) if data.get("success") else []
            out.extend(result)
            if len(result) < 50:
                break
            page += 1
        return out

    def create_email_address(self, zone_id: str, email: str) -> dict:
        """添加目的地邮箱。CF 立即发验证邮件，verified=False 直到用户点链接。"""
        data = self._post(f"/accounts/{self.account_id}/email/routing/addresses",
                          json={"email": email})
        if not data.get("success"):
            raise RuntimeError(f"CF 添加目的地邮箱失败: {data.get('errors')}")
        return data.get("result", {})

    def delete_email_address(self, zone_id: str, address_id: str) -> bool:
        r = httpx.delete(f"{CF_API_BASE}/accounts/{self.account_id}/email/routing/addresses/{address_id}",
                         headers=self.headers, timeout=30)
        if r.status_code == 404:
            return False  # 本来就没有
        return r.json().get("success", False)

    def list_email_rules(self, zone_id: str) -> list:
        """转发规则列表。"""
        data = self._get(f"/zones/{zone_id}/email/routing/rules")
        return data.get("result", []) if data.get("success") else []

    def create_email_rule(self, zone_id: str, alias_email: str, destination_email: str) -> dict:
        """建转发规则：发往 alias_email 的邮件 → destination_email（须已在 CF 验证）。

        actions.value 引用的是目的地【邮箱地址】而非 address_id——传 id CF 报
        2007 "must specify forwarding emails"（2026-09 实测教训）。
        """
        data = self._post(
            f"/zones/{zone_id}/email/routing/rules",
            json={"name": f"toveads: {alias_email}",
                  "enabled": True,
                  "matchers": [{"type": "literal", "field": "to", "value": alias_email}],
                  "actions": [{"type": "forward", "value": [destination_email]}],
                  "priority": 0},
        )
        if not data.get("success"):
            raise RuntimeError(f"CF 创建转发规则失败: {data.get('errors')}")
        return data.get("result", {})

    def set_email_rule_enabled(self, zone_id: str, rule_id: str, enabled: bool) -> dict:
        """启停转发规则。先 PATCH；个别客户端不接受时回退 GET 原规则改 enabled 全量 PUT。"""
        r = httpx.patch(f"{CF_API_BASE}/zones/{zone_id}/email/routing/rules/{rule_id}",
                        headers={**self.headers, "Content-Type": "application/json"},
                        json={"enabled": enabled}, timeout=30)
        if r.status_code < 400:
            data = r.json()
            if data.get("success"):
                return data.get("result", {})
        cur = self._get(f"/zones/{zone_id}/email/routing/rules/{rule_id}")
        if not cur.get("success"):
            raise RuntimeError(f"CF 更新转发规则失败: {cur.get('errors')}")
        body = cur.get("result") or {}
        body["enabled"] = enabled
        r2 = httpx.put(f"{CF_API_BASE}/zones/{zone_id}/email/routing/rules/{rule_id}",
                       headers={**self.headers, "Content-Type": "application/json"},
                       json=body, timeout=30)
        data2 = r2.json()
        if not data2.get("success"):
            raise RuntimeError(f"CF 更新转发规则失败: {data2.get('errors')}")
        return data2.get("result", {})

    def delete_email_rule(self, zone_id: str, rule_id: str) -> bool:
        r = httpx.delete(f"{CF_API_BASE}/zones/{zone_id}/email/routing/rules/{rule_id}",
                         headers=self.headers, timeout=30)
        if r.status_code == 404:
            return False
        return r.json().get("success", False)

    def unbind_custom_domain(self, project_name: str, domain: str) -> bool:
        """解绑 Pages 自定义域名（改前缀/移除域名时清理旧子域名残留）。

        CF Pages domains API 的 DELETE key 是域名本身（name），不是列表返回的 uuid id——
        用 id 调永远 404（DB 侧移出了列表、CF 侧域名仍挂着）。
        """
        r = httpx.delete(f"{CF_API_BASE}/accounts/{self.account_id}/pages/projects/{project_name}/domains/{domain}",
                         headers=self.headers, timeout=30)
        logger.info(f"[CF] unbind {domain}: {r.status_code}")
        if r.status_code == 404:
            return False  # 本来就没绑
        return r.json().get("success", False)
