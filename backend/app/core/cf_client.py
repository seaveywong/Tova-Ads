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
        return r.json()

    def _post(self, path: str, **kwargs) -> dict:
        r = httpx.post(f"{CF_API_BASE}{path}", headers=self.headers, timeout=60, **kwargs)
        return r.json()

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

    def unbind_custom_domain(self, project_name: str, domain: str) -> bool:
        """解绑 Pages 自定义域名（改前缀/移除域名时清理旧子域名残留）。"""
        domains = self._get(f"/accounts/{self.account_id}/pages/projects/{project_name}/domains").get("result", [])
        did = next((d.get("id") for d in domains if d.get("name") == domain), None)
        if not did:
            return False
        r = httpx.delete(f"{CF_API_BASE}/accounts/{self.account_id}/pages/projects/{project_name}/domains/{did}",
                         headers=self.headers, timeout=30)
        logger.info(f"[CF] unbind {domain}: {r.status_code}")
        return r.json().get("success", False)
