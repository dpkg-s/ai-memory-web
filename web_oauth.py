"""OAuth 2.1 授权服务器（2026-10-26）。

为什么需要这一层
----------------
``/mcp`` 原本只认 ``amt_`` 访问令牌。这在桌面客户端里够用（能自己加
``Authorization`` 头），但**网页型 AI 产品**（ChatGPT 自定义 Connector 等）
的接入规范是 MCP Authorization：客户端不会让你粘贴令牌，它只会

  1. 打到 ``/mcp``，期望收到 ``401 + WWW-Authenticate: resource_metadata=...``；
  2. 读 ``/.well-known/oauth-protected-resource`` 找到授权服务器；
  3. 读授权服务器元数据、动态注册（RFC 7591）拿到 ``client_id``；
  4. 打开 ``/oauth/authorize`` 让**人**在浏览器里登录并同意；
  5. 用授权码 + PKCE 换 ``access_token``；
  6. 拿 ``access_token`` 调 ``/mcp``。

缺了这层，这类客户端 100% 停在第一步（表现为「401 未授权」，而且用户
无论怎么填令牌都无效——因为它压根没有填令牌的入口）。

一个让它变简单的决策：**access_token 就是一枚普通 ``amt_`` 令牌**
---------------------------------------------------------------
换令牌时直接调 ``TokenStore.create()``，于是：

* 鉴权中间件、``/api/call``、``/mcp`` 反代、数据视野、读写模式**零改动**；
* 面板的令牌列表里看得见、能一键吊销（``name`` 前缀 ``oauth:``）；
* 令牌盘点、限次、过期策略与手工签发的令牌完全同构，不需要第二套心智模型。

代价是 OAuth 的 ``scope`` 在这里不表达细粒度权限——权限由「谁在授权页
登录」决定（用户自己的角色）。这对单用户调试台是正确取舍：多一套 scope
映射只会让「授权后能做什么」变得难以预测。

三个安全约束（不满足就不发码）
------------------------------
1. **只接受 PKCE S256**。``plain`` 在公共客户端场景等于没校验。
2. **redirect_uri 必须与注册时逐字符相同**，且只能是 https 或回环 http ——
   否则就是一个开放重定向器，授权码会被送到攻击者服务器。
3. **授权码一次性、60 秒过期**。重放一律拒绝（消费即删除，非「标记已用」）。
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path

#: 授权码有效期（秒）。规范建议「短」，60 秒足够浏览器跳一个来回。
CODE_TTL = 60
#: 同时存活的授权码上限（防内存被刷爆）。
CODE_MAX = 256
#: 动态注册的客户端数量上限。公网可匿名调用 ``/oauth/register``，
#: 不设上限等于把 ``oauth_clients.json`` 变成一个可无限写入的磁盘。
CLIENT_MAX = 64
#: 换出来的 access_token 有效期（秒）。30 天：网页端重新授权一次不算负担，
#: 又不至于短到每次打开都要走一遍登录。
ACCESS_TTL = 30 * 86400
#: 客户端 ID 前缀。与令牌的 ``amt_``、用户的 ``u_`` 区分开，日志里一眼认得出。
CLIENT_PREFIX = "amc_"
#: 支持的授权类型 / 响应类型。刻意只列这两项：多列一个就多一条未测代码路径。
GRANT_TYPES = ("authorization_code",)
RESPONSE_TYPES = ("code",)
#: 令牌端点认证方式。ChatGPT 这类公共客户端没有 secret，必须允许 ``none``。
TOKEN_AUTH_METHODS = ("none", "client_secret_post")


class OAuthError(Exception):
    """授权流程里的可预期错误。``code`` 用于回给客户端的 ``error`` 字段。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


# ---------------------------------------------------------------------------
# 编码辅助
# ---------------------------------------------------------------------------
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def s256(verifier: str) -> str:
    """PKCE S256 变换：``BASE64URL(SHA256(ASCII(verifier)))``。"""
    return _b64e(hashlib.sha256(verifier.encode("ascii", "strict")).digest())


def _now() -> float:
    return time.time()


def _atomic_write(path: Path, payload: dict) -> None:
    """临时文件 + ``os.replace``，与 ``web_store`` 同一套落盘策略。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# redirect_uri 白名单
# ---------------------------------------------------------------------------
_LOOPBACK_PREFIXES = ("http://localhost", "http://127.0.0.1", "http://[::1]")


def redirect_uri_allowed(uri: str) -> bool:
    """注册阶段是否接受这个 ``redirect_uri``。

    规则刻意从紧：**https 或回环 http**。为什么不放 http 公网地址 ——
    授权码是明文查询参数，走 http 等于沿途广播；而放宽这条的唯一收益是
    「方便测试」，代价是把每个注册客户端都变成可被中间人截获的凭据源。
    """
    if not isinstance(uri, str) or not uri or " " in uri:
        return False
    low = uri.lower()
    if low.startswith("https://"):
        return True
    return any(low.startswith(p) for p in _LOOPBACK_PREFIXES)


# ---------------------------------------------------------------------------
# 动态客户端注册表（RFC 7591）
# ---------------------------------------------------------------------------
class ClientStore:
    """``oauth_clients.json``：匿名可写的注册表，因此每条都做严格校验。

    与 ``users.json`` / ``tokens.json`` 放同一目录（容器里是 ``/config``），
    一起进同一个卷，备份与迁移不需要记第二个路径。
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except (OSError, json.JSONDecodeError):
            obj = {}
        if not isinstance(obj, dict):
            obj = {}
        obj.setdefault("version", 1)
        obj.setdefault("clients", [])
        if not isinstance(obj["clients"], list):
            obj["clients"] = []
        return obj

    def _save(self) -> None:
        _atomic_write(self.path, self._data)

    # -- 读 ----------------------------------------------------------------
    def get(self, client_id: str) -> dict | None:
        if not client_id:
            return None
        with self._lock:
            for c in self._data["clients"]:
                if c.get("client_id") == client_id:
                    return dict(c)
        return None

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(c) for c in self._data["clients"]]

    def redirect_ok(self, client_id: str, redirect_uri: str) -> bool:
        """授权请求里的 ``redirect_uri`` 是否属于该客户端。

        **逐字符相等**，不做「前缀匹配」也不做「规范化后比较」：任何宽松比较
        都会引入 ``https://good.example.com.evil.tld`` 这类绕过。
        """
        c = self.get(client_id)
        if not c:
            return False
        return redirect_uri in (c.get("redirect_uris") or [])

    # -- 写 ----------------------------------------------------------------
    def register(self, *, redirect_uris: list, client_name: str = "",
                 token_endpoint_auth_method: str = "none") -> dict:
        if not isinstance(redirect_uris, list) or not redirect_uris:
            raise OAuthError("invalid_redirect_uri", "redirect_uris 不能为空。")
        cleaned: list[str] = []
        for uri in redirect_uris:
            if not redirect_uri_allowed(uri):
                raise OAuthError(
                    "invalid_redirect_uri",
                    f"redirect_uri 必须是 https:// 或回环 http://：{uri!r}")
            if uri not in cleaned:
                cleaned.append(uri)
        if token_endpoint_auth_method not in TOKEN_AUTH_METHODS:
            raise OAuthError("invalid_client_metadata",
                             f"不支持的 token_endpoint_auth_method：{token_endpoint_auth_method}")
        name = (client_name or "").strip()[:64] or "未命名客户端"
        now = _now()
        with self._lock:
            if len(self._data["clients"]) >= CLIENT_MAX:
                raise OAuthError("invalid_client_metadata",
                                 f"已注册客户端达到上限 {CLIENT_MAX}，请先在面板清理。")
            rec = {
                "client_id": CLIENT_PREFIX + secrets.token_hex(16),
                "client_name": name,
                "redirect_uris": cleaned,
                "token_endpoint_auth_method": token_endpoint_auth_method,
                "grant_types": list(GRANT_TYPES),
                "response_types": list(RESPONSE_TYPES),
                "created_at": now,
            }
            self._data["clients"].append(rec)
            self._save()
            return dict(rec)

    def revoke(self, client_id: str) -> bool:
        with self._lock:
            before = len(self._data["clients"])
            self._data["clients"] = [c for c in self._data["clients"]
                                     if c.get("client_id") != client_id]
            if len(self._data["clients"]) == before:
                return False
            self._save()
            return True


# ---------------------------------------------------------------------------
# 授权码（纯内存）
# ---------------------------------------------------------------------------
class CodeStore:
    """授权码仓库：**一次性**、短时、上限封顶。

    为什么不做持久化：授权码的寿命是 60 秒，跨重启存活没有任何意义，
    反而多一个「重启后旧码仍可用」的面。进程重启 = 正在进行的授权作废 =
    用户重试一次即可，这是可接受的失败模式。
    """

    def __init__(self, ttl: int = CODE_TTL, cap: int = CODE_MAX) -> None:
        self.ttl = int(ttl)
        self.cap = int(cap)
        self._lock = threading.Lock()
        self._codes: dict[str, dict] = {}

    def _prune(self, now: float) -> None:
        dead = [k for k, v in self._codes.items() if v["exp"] <= now]
        for k in dead:
            self._codes.pop(k, None)
        # 仍超限时按签发时间丢最旧的一批（正常路径不会走到这里，
        # 因为 prune 已经清掉过期项；留着是为了防止恶意刷码撑爆内存）。
        while len(self._codes) >= self.cap:
            oldest = min(self._codes, key=lambda k: self._codes[k]["iat"])
            self._codes.pop(oldest, None)

    def issue(self, *, client_id: str, redirect_uri: str, user: str, role: str,
              clearance: str, challenge: str, scope: str = "",
              resource: str = "") -> str:
        now = _now()
        code = secrets.token_urlsafe(32)
        with self._lock:
            self._prune(now)
            self._codes[code] = {
                "client_id": client_id, "redirect_uri": redirect_uri,
                "user": user, "role": role, "clearance": clearance,
                "challenge": challenge, "scope": scope, "resource": resource,
                "iat": now, "exp": now + self.ttl, "used": False,
            }
        return code

    def consume(self, code: str) -> dict | None:
        """取走授权码。**取出即删除** —— 重放时第二次必然拿到 ``None``。"""
        if not code:
            return None
        now = _now()
        with self._lock:
            rec = self._codes.pop(code, None)
        if not rec or rec["exp"] <= now:
            return None
        return rec


# ---------------------------------------------------------------------------
# 元数据（RFC 8414 / RFC 9728）
# ---------------------------------------------------------------------------
def protected_resource_metadata(base: str) -> dict:
    """``/.well-known/oauth-protected-resource``。

    ``resource`` 必须与客户端将要访问的 MCP 端点一致 —— 客户端会拿它做
    audience 校验；写错会让部分实现直接放弃授权。
    """
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        # 指向面板的「访问控制」页而不是某个 /docs 静态路径：后者本服务并不提供，
        # 发一个 404 链接过去只会让排查的人多绕一圈。
        "resource_documentation": f"{base}/#/access",
    }


def authorization_server_metadata(base: str) -> dict:
    """``/.well-known/oauth-authorization-server``。

    ``registration_endpoint`` 是网页类客户端的生死线：它们拿不到
    ``client_id`` 就无法发起授权。所以这里**必须**声明，且该端点免鉴权。
    """
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "grant_types_supported": list(GRANT_TYPES),
        "response_types_supported": list(RESPONSE_TYPES),
        "token_endpoint_auth_methods_supported": list(TOKEN_AUTH_METHODS),
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["mcp"],
        "service_documentation": f"{base}/#/access",
    }


# ---------------------------------------------------------------------------
# 授权页（服务端渲染，不依赖前端打包产物）
# ---------------------------------------------------------------------------
_PAGE_CSS = """
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#101318;color:#e6e9ef;font:15px/1.6 -apple-system,"Segoe UI",
"Microsoft YaHei",system-ui,sans-serif}
.card{width:min(440px,92vw);background:#171b22;border:1px solid #262c36;
border-radius:14px;padding:28px 26px 24px;box-shadow:0 18px 50px rgba(0,0,0,.45)}
h1{margin:0 0 6px;font-size:19px;font-weight:600;letter-spacing:.2px}
.sub{margin:0 0 20px;color:#8b94a3;font-size:13px}
.row{display:flex;gap:10px;padding:9px 0;border-bottom:1px solid #222833;font-size:13.5px}
.row:last-of-type{border-bottom:0}
.k{color:#8b94a3;min-width:78px;flex:0 0 auto}
.v{color:#d7dce5;word-break:break-all}
label{display:block;margin:16px 0 6px;font-size:13px;color:#9aa4b2}
input{width:100%;padding:10px 12px;border-radius:9px;border:1px solid #2c333f;
background:#0e1218;color:#e6e9ef;font-size:14px;outline:none}
input:focus{border-color:#4b7bec;box-shadow:0 0 0 3px rgba(75,123,236,.16)}
.actions{display:flex;gap:10px;margin-top:22px}
button{flex:1;padding:11px 14px;border-radius:9px;border:1px solid transparent;
font-size:14px;font-weight:600;cursor:pointer;font-family:inherit}
.ok{background:#3b6fe0;color:#fff}
.ok:hover{background:#4b7bec}
.no{background:transparent;color:#9aa4b2;border-color:#2c333f}
.no:hover{border-color:#3b434f;color:#c9d1dc}
.err{margin:14px 0 0;padding:10px 12px;border-radius:9px;background:#3a1d20;
border:1px solid #5c2a2f;color:#ffb3b8;font-size:13px}
.foot{margin:18px 0 0;color:#5f6875;font-size:11.5px;line-height:1.5}
"""


def error_page(title: str, message: str) -> str:
    """授权流程里的错误页（就地渲染，不做重定向）。

    **为什么错误也必须是页面而不是 302**：当 ``client_id`` 或
    ``redirect_uri`` 不可信时，把它当作跳转目标就是把本站变成一个开放
    重定向器 —— 攻击者可以借域名把用户送到任意站点。只有「已确认属于该
    客户端」的 ``redirect_uri`` 才允许被重定向（见 ``ClientStore.redirect_ok``）。
    """
    esc = html.escape
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{_PAGE_CSS}</style></head>
<body><div class="card"><h1>{esc(title)}</h1>
<p class="sub">{esc(message)}</p>
<p class="foot">若你是从某个客户端跳转过来的，请回到该客户端重新发起授权；
或在控制台「访问控制」页确认应用已正确注册。</p>
</div></body></html>"""


def authorize_page(*, client_name: str, redirect_uri: str, state: str,
                   scope: str, role: str, user: str = "",
                   need_login: bool = True, error: str = "",
                   hidden: dict[str, str] | None = None,
                   login_enabled: bool = True) -> str:
    """渲染授权页。

    ⚠️ ``client_name`` 来自**匿名可写**的注册表，必须转义后再进 HTML ——
    否则任何人都能注册一个名字为 ``<script>...</script>`` 的客户端，
    等在授权页上打到已登录用户面前（存储型 XSS）。
    """
    esc = html.escape
    rows = [
        ("应用", esc(client_name or "未命名客户端")),
        ("回跳", esc(redirect_uri)),
        ("权限", esc(f"{role}（继承你的账号权限）")),
    ]
    if scope:
        rows.append(("范围", esc(scope)))

    fields = []
    for k, v in (hidden or {}).items():
        fields.append(f'<input type="hidden" name="{esc(k)}" value="{esc(str(v))}">')

    if need_login and login_enabled:
        creds = (
            '<label for="u">用户名</label>'
            '<input id="u" name="username" autocomplete="username" autofocus>'
            '<label for="p">口令</label>'
            '<input id="p" name="password" type="password" '
            'autocomplete="current-password">'
        )
        title = "授权访问记忆库"
        sub = "请登录以确认这次授权。"
    elif need_login:
        creds = ""
        title = "无法授权"
        sub = "本控制台未开启账号登录，无法确认你的身份。"
    else:
        creds = ""
        title = "授权访问记忆库"
        sub = f"已登录为 {user}，确认授权后即可继续。"

    err_html = f'<p class="err">{esc(error)}</p>' if error else ""
    ok_disabled = "" if (not need_login or login_enabled) else " disabled"
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{_PAGE_CSS}</style></head>
<body><form class="card" method="post" action="/oauth/authorize">
<h1>{esc(title)}</h1><p class="sub">{esc(sub)}</p>
{"".join(f'<div class="row"><span class="k">{k}</span><span class="v">{v}</span></div>' for k, v in rows)}
{creds}{err_html}
<div class="actions">
<button class="ok" type="submit" name="decision" value="allow"{ok_disabled}>允许</button>
<button class="no" type="submit" name="decision" value="deny">拒绝</button>
</div>
<p class="foot">授权后将签发一枚 30 天有效的访问令牌，可在控制台「访问控制」页随时吊销。</p>
{"".join(fields)}
</form></body></html>"""
