#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OAuth 2.1 授权服务器测试（2026-10-26）。

覆盖：
  A  元数据：RFC 9728 受保护资源 / RFC 8414 授权服务器（含 registration_endpoint）
  B  401 挑战头：无凭据访问 /mcp 必须带 WWW-Authenticate: Bearer resource_metadata
  C  动态注册（RFC 7591）：正常注册 / 拒绝公网 http 回调 / 拒绝空回调 /
     拒绝声明 client_secret_post（本 AS 不签发也不校验 secret）
  D  授权页：未登录渲染登录表单；非法 client_id / redirect_uri / 缺 PKCE 就地报错
     （**绝不重定向**）
  E  端到端：账号口令 + 同意 → 授权码 → PKCE 换令牌 → 该令牌能访问 /api/config
  F  失败路径：码重放 / 错误 verifier / redirect_uri 不一致 / 未 knowngrant_type

运行:
    python tests/test_oauth.py      # 退出码 0=全绿, 1=有失败
依赖:
    需在装有 mcp 的 venv 里跑（starlette / httpx 是其传递依赖，零新增）。
    全程使用临时目录，绝不触碰真实记忆库与真实 users/tokens 表。
"""
from __future__ import annotations

import asyncio
import os
import secrets
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

# ---- 先把环境指到临时目录, 再 import 被测模块 ---------------------------
_TMP = Path(tempfile.mkdtemp(prefix="ai-memory-oauth-"))
os.environ["AI_MEMORY_DIR"] = str(_TMP / "vault")
(_TMP / "vault").mkdir(parents=True, exist_ok=True)
os.environ["AI_MEMORY_WEB_CONFIG"] = str(_TMP / "config.json")
os.environ["AI_MEMORY_WEB_TOKEN"] = "oauth-test-token"
os.environ["AI_MEMORY_WEB_USER"] = "admin"
os.environ["AI_MEMORY_WEB_PASSWORD"] = "pw-oauth-test"
os.environ["AI_MEMORY_WEB_USERS"] = str(_TMP / "users.json")
os.environ["AI_MEMORY_WEB_TOKENS"] = str(_TMP / "tokens.json")
os.environ["AI_MEMORY_WEB_OAUTH_CLIENTS"] = str(_TMP / "oauth_clients.json")
os.environ.pop("AI_MEMORY_WEB_PUBLIC_URL", None)

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import httpx          # noqa: E402
import web_console    # noqa: E402
import web_oauth      # noqa: E402

_passed: list[str] = []
_failed: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        _passed.append(name)
        print(f"  PASS  {name}")
    else:
        _failed.append(name)
        print(f"  FAIL  {name}   {detail}")


def section(name: str) -> None:
    print(f"\n== {name} ==")


_CFG = web_console.config()
_APP = web_console.create_app(_CFG)
_TRANSPORT = httpx.ASGITransport(app=_APP)


async def req(method: str, path: str, **kw) -> httpx.Response:
    async with httpx.AsyncClient(transport=_TRANSPORT, base_url="http://t",
                                 follow_redirects=False, timeout=20) as c:
        return await c.request(method, path, **kw)


def call(method: str, path: str, **kw) -> httpx.Response:
    return asyncio.run(req(method, path, **kw))


# =====================================================================
section("A 元数据（RFC 9728 / RFC 8414）")
_r = call("GET", "/.well-known/oauth-protected-resource")
_m = _r.json() if _r.status_code == 200 else {}
check("A1 受保护资源元数据 200 且 resource 指向 /mcp",
      _r.status_code == 200 and str(_m.get("resource", "")).endswith("/mcp"),
      f"status={_r.status_code} body={_r.text[:160]}")
check("A2 声明 authorization_servers",
      bool(_m.get("authorization_servers")), str(_m)[:160])

_r = call("GET", "/.well-known/oauth-authorization-server")
_as = _r.json() if _r.status_code == 200 else {}
check("A3 授权服务器元数据 200", _r.status_code == 200, f"status={_r.status_code}")
check("A4 必须声明 registration_endpoint（网页类客户端的生死线）",
      str(_as.get("registration_endpoint", "")).endswith("/oauth/register"),
      str(_as)[:200])
check("A5 只声明 S256 作为 PKCE 方法",
      _as.get("code_challenge_methods_supported") == ["S256"],
      str(_as.get("code_challenge_methods_supported")))
check("A6 grant_type 只含 authorization_code",
      _as.get("grant_types_supported") == ["authorization_code"],
      str(_as.get("grant_types_supported")))
# A7（2026-10-27 增补）：这个字段是 RFC 8414 §2 的**承诺**，不是能力清单。
# 声明了 client_secret_post 就必须能签发并校验 secret；做不到就不要声明，
# 否则符合规范的客户端会照它去带 secret，带不上再在别处以看不懂的方式失败。
check("A7 令牌端点认证方式只声明 none（无 secret 可发，就不许承诺）",
      _as.get("token_endpoint_auth_methods_supported") == ["none"],
      str(_as.get("token_endpoint_auth_methods_supported")))

# =====================================================================
section("B 401 挑战头")
_r = call("POST", "/mcp", headers={"Accept": "application/json, text/event-stream",
                                   "Content-Type": "application/json"},
          content=b'{"jsonrpc":"2.0","id":1,"method":"initialize"}')
_wa = _r.headers.get("www-authenticate", "")
check("B1 无凭据访问 /mcp ⇒ 401", _r.status_code == 401, f"status={_r.status_code}")
check("B2 401 带 WWW-Authenticate: Bearer resource_metadata",
      "resource_metadata" in _wa and "oauth-protected-resource" in _wa, _wa[:160])

# B3~B5（2026-10-26 增补）：挑战头必须**可被消费**。
# 只断言「有个头」是不够的 —— 客户端会拿这个头里的 URL 去取元数据，再把
# 元数据里的 resource 与实际请求的 URL 做全等比较（RFC 9728 §3.3 第二种情形）。
# 这两步任一断开，客户端都会静默放弃授权，而服务端日志只有一条 401。
_r = call("GET", "/mcp", headers={"Accept": "text/html"})
_wa_get = _r.headers.get("www-authenticate", "")
check("B3 无凭据 GET /mcp ⇒ 401 且同样带 WWW-Authenticate",
      _r.status_code == 401 and "resource_metadata" in _wa_get,
      f"status={_r.status_code} wa={_wa_get[:120]}")

_md_url = _wa.split("resource_metadata=", 1)[1].strip().strip('"') \
    if "resource_metadata=" in _wa else ""
_md_path = urlsplit(_md_url).path or "/none"
_r = call("GET", _md_path)
_md = _r.json() if _r.status_code == 200 else {}
check("B4 挑战头指名的元数据 URL 可取（200 + JSON）",
      _r.status_code == 200
      and _md_path.endswith("/oauth-protected-resource"),
      f"path={_md_path} status={_r.status_code} body={_r.text[:120]}")

# 这一条的**方向**很关键：resource 必须等于客户端实际请求的那个资源 URL
# （/mcp），而不是裸 base。哪天有人「为了符合根路径语义」把 resource 改成
# base，B5 会立刻红 —— 那正是会打断目前唯一合规信道的改法。
check("B5 该元数据的 resource 与资源的实际请求 URL 一致（以 /mcp 结尾）",
      str(_md.get("resource", "")).endswith("/mcp"),
      f"resource={_md.get('resource')!r}")

# B6：有鉴权形态下，未知 /api/ 路径仍先被中间件拦成 401，而不是落到路由层 404。
# 判据是**顺序**（鉴权 > 路由）；若哪天中间件判据被放宽，这条会红。
_r = call("GET", "/api/nope")
check("B6 未知 /api/ 路径在无凭据时仍 401（鉴权优先于路由 404）",
      _r.status_code == 401, f"status={_r.status_code} body={_r.text[:120]}")

# =====================================================================
section("C 动态客户端注册（RFC 7591）")
_CB = "https://chat.example.com/connector/oauth/callback"
_r = call("POST", "/oauth/register",
          json={"redirect_uris": [_CB], "client_name": "ChatGPT Connector"})
_reg = _r.json() if _r.status_code == 201 else {}
CID = _reg.get("client_id", "")
check("C1 正常注册 ⇒ 201 且发 client_id", _r.status_code == 201 and CID.startswith("amc_"),
      f"status={_r.status_code} body={_r.text[:200]}")
check("C2 回显 redirect_uris 与 token_endpoint_auth_method=none",
      _reg.get("redirect_uris") == [_CB]
      and _reg.get("token_endpoint_auth_method") == "none", str(_reg)[:200])

_r = call("POST", "/oauth/register",
          json={"redirect_uris": ["http://evil.example.com/cb"]})
check("C3 拒绝公网 http 回调（授权码会沿途广播）",
      _r.status_code == 400 and _r.json().get("error") == "invalid_redirect_uri",
      f"status={_r.status_code} body={_r.text[:160]}")

_r = call("POST", "/oauth/register", json={"redirect_uris": []})
check("C4 拒绝空 redirect_uris", _r.status_code == 400, f"status={_r.status_code}")

_r = call("POST", "/oauth/register",
          json={"redirect_uris": ["http://localhost:33418/callback"],
                "client_name": "本地调试"})
check("C5 接受回环 http 回调（本机客户端场景）", _r.status_code == 201,
      f"status={_r.status_code} body={_r.text[:160]}")

# C6~C7（2026-10-27 增补）：A7 把声明收窄到 none 之后，这两条锁住「收窄」的
# 两个方向 —— 声明外的值必须在**注册口**就拒掉（否则声明与行为各说各话），
# 默认路径必须干净成功且**不发 secret**。C6 同时核三处计数：内存中的客户端表、
# 重新从磁盘读出来的客户端表。拒得干净的标准是「连一行都不落盘」。
_clients_before = len(_CFG["oauth_clients"].list())
_r = call("POST", "/oauth/register",
          json={"redirect_uris": [_CB], "client_name": "要 secret 的客户端",
                "token_endpoint_auth_method": "client_secret_post"})
_clients_after = len(_CFG["oauth_clients"].list())
_clients_on_disk = len(
    web_oauth.ClientStore(os.environ["AI_MEMORY_WEB_OAUTH_CLIENTS"]).list())
check("C6 注册声明 client_secret_post ⇒ 400 invalid_client_metadata 且不落盘",
      _r.status_code == 400
      and _r.json().get("error") == "invalid_client_metadata"
      and _clients_after == _clients_before
      and _clients_on_disk == _clients_before,
      f"status={_r.status_code} before={_clients_before} "
      f"after={_clients_after} disk={_clients_on_disk} body={_r.text[:160]}")

_r = call("POST", "/oauth/register",
          json={"redirect_uris": [_CB], "client_name": "默认注册"})
_reg_default = _r.json() if _r.status_code == 201 else {}
check("C7 默认注册 ⇒ 201、认证方式回落 none、响应不含 client_secret",
      _r.status_code == 201
      and _reg_default.get("token_endpoint_auth_method") == "none"
      and "client_secret" not in _reg_default,
      f"status={_r.status_code} keys={sorted(_reg_default)} body={_r.text[:160]}")

# =====================================================================
section("D 授权页与入参校验")
_VERIFIER = secrets.token_urlsafe(32)
_CHALLENGE = web_oauth.s256(_VERIFIER)
_AZ = {"client_id": CID, "redirect_uri": _CB, "response_type": "code",
       "code_challenge": _CHALLENGE, "code_challenge_method": "S256",
       "state": "st-123", "scope": "mcp"}


def _qs(d: dict) -> str:
    from urllib.parse import urlencode
    return urlencode(d)


_r = call("GET", "/oauth/authorize?" + _qs(_AZ))
check("D1 未登录 ⇒ 200 登录表单页",
      _r.status_code == 200 and 'name="password"' in _r.text,
      f"status={_r.status_code}")
check("D2 授权页显示客户端名（转义后）", "ChatGPT Connector" in _r.text, "")

_evil = dict(_AZ, redirect_uri="https://evil.example.com/cb")
_r = call("GET", "/oauth/authorize?" + _qs(_evil))
check("D3 redirect_uri 与注册值不一致 ⇒ 400 且**不重定向**",
      _r.status_code == 400 and "location" not in {k.lower() for k in _r.headers},
      f"status={_r.status_code} loc={_r.headers.get('location')}")

_r = call("GET", "/oauth/authorize?" + _qs(dict(_AZ, client_id="amc_不存在")))
check("D4 未知 client_id ⇒ 400", _r.status_code == 400, f"status={_r.status_code}")

_no_pkce = {k: v for k, v in _AZ.items()
            if k not in ("code_challenge", "code_challenge_method")}
_r = call("GET", "/oauth/authorize?" + _qs(_no_pkce))
check("D5 缺 code_challenge ⇒ 400（强制 PKCE）", _r.status_code == 400,
      f"status={_r.status_code}")

_plain = dict(_AZ, code_challenge_method="plain")
_r = call("GET", "/oauth/authorize?" + _qs(_plain))
check("D6 code_challenge_method=plain ⇒ 400（只收 S256）", _r.status_code == 400,
      f"status={_r.status_code}")

# =====================================================================
section("E 端到端授权（账号口令 + 同意 → 换令牌 → 用令牌）")


def _get_code(verifier: str = _CHALLENGE, redirect: str = _CB,
              password: str = "pw-oauth-test") -> tuple[str, httpx.Response]:
    form = dict(_AZ, code_challenge=verifier, redirect_uri=redirect,
                decision="allow", username="admin", password=password)
    r = call("POST", "/oauth/authorize", data=form)
    code = ""
    if r.status_code == 302:
        code = (parse_qs(urlsplit(r.headers.get("location", "")).query)
                .get("code", [""])[0])
    return code, r


_CODE, _r = _get_code()
check("E1 登录+同意 ⇒ 302 回 redirect_uri 并带 code 与 state",
      _r.status_code == 302 and bool(_CODE)
      and "state=st-123" in _r.headers.get("location", ""),
      f"status={_r.status_code} loc={_r.headers.get('location','')[:120]}")

_r = call("POST", "/oauth/token",
          data={"grant_type": "authorization_code", "code": _CODE,
                "client_id": CID, "redirect_uri": _CB,
                "code_verifier": _VERIFIER})
_tok = _r.json() if _r.status_code == 200 else {}
_TOK = _tok.get("access_token", "")
check("E2 用 code + 正确 verifier ⇒ 200 且发 amt_ 令牌",
      _r.status_code == 200 and _TOK.startswith("amt_"),
      f"status={_r.status_code} body={_r.text[:200]}")
check("E3 token_type=Bearer 且 expires_in 为正",
      _tok.get("token_type") == "Bearer" and int(_tok.get("expires_in") or 0) > 0,
      str(_tok)[:160])
check("E4 响应带 Cache-Control: no-store",
      "no-store" in _r.headers.get("cache-control", ""),
      _r.headers.get("cache-control", ""))

_r = call("GET", "/api/config", headers={"Authorization": f"Bearer {_TOK}"})
check("E5 换来的令牌能访问受保护接口（/api/config ⇒ 200）",
      _r.status_code == 200, f"status={_r.status_code} body={_r.text[:160]}")

_rows = [t for t in _CFG["tokens"].list() if str(t.get("name", "")).startswith("oauth:")]
check("E6 令牌出现在令牌表里且名字带 oauth: 前缀（可在面板吊销）",
      bool(_rows) and _rows[0]["role"] == "admin" and _rows[0].get("owner") == "admin",
      str(_rows)[:200])

# E7（2026-10-27 增补）：RFC 6749 §3.2 要求令牌端点**忽略**未识别的参数。
# 声明收窄到 none 之后，老客户端仍可能惯性带上 client_secret —— 它必须被
# 忽略而不是被拒，否则「收紧声明」会顺带变成一次可用性回归。
# 断言里先核 payload 确实带了该键，避免这条测试退化成一个纯 200 检查。
_code_extra, _ = _get_code()
_payload_extra = {"grant_type": "authorization_code", "code": _code_extra,
                  "client_id": CID, "redirect_uri": _CB,
                  "code_verifier": _VERIFIER, "client_secret": "probe-value"}
_r = call("POST", "/oauth/token", data=_payload_extra)
_tok_extra = _r.json() if _r.status_code == 200 else {}
check("E7 换码多带 client_secret ⇒ 被忽略且仍 200（RFC 6749 §3.2）",
      "client_secret" in _payload_extra
      and _r.status_code == 200
      and str(_tok_extra.get("access_token", "")).startswith("amt_"),
      f"status={_r.status_code} body={_r.text[:160]}")

# =====================================================================
section("F 失败路径")
_r = call("POST", "/oauth/token",
          data={"grant_type": "authorization_code", "code": _CODE,
                "client_id": CID, "redirect_uri": _CB,
                "code_verifier": _VERIFIER})
check("F1 授权码重放 ⇒ invalid_grant（码取出即删）",
      _r.status_code == 400 and _r.json().get("error") == "invalid_grant",
      f"status={_r.status_code} body={_r.text[:160]}")

_code2, _ = _get_code()
_r = call("POST", "/oauth/token",
          data={"grant_type": "authorization_code", "code": _code2,
                "client_id": CID, "redirect_uri": _CB,
                "code_verifier": secrets.token_urlsafe(32)})
check("F2 错误 code_verifier ⇒ invalid_grant（PKCE 生效）",
      _r.status_code == 400 and _r.json().get("error") == "invalid_grant",
      f"status={_r.status_code} body={_r.text[:160]}")

_code3, _ = _get_code()
_r = call("POST", "/oauth/token",
          data={"grant_type": "authorization_code", "code": _code3,
                "client_id": CID, "redirect_uri": "https://chat.example.com/other",
                "code_verifier": _VERIFIER})
check("F3 redirect_uri 不一致 ⇒ invalid_grant",
      _r.status_code == 400 and _r.json().get("error") == "invalid_grant",
      f"status={_r.status_code} body={_r.text[:160]}")

_r = call("POST", "/oauth/token", data={"grant_type": "password"})
check("F4 不支持的 grant_type ⇒ unsupported_grant_type",
      _r.status_code == 400 and _r.json().get("error") == "unsupported_grant_type",
      f"status={_r.status_code} body={_r.text[:160]}")

_code4, _ = _get_code()
_r = call("POST", "/oauth/token",
          data={"grant_type": "authorization_code", "code": _code4,
                "client_id": "amc_别人的", "redirect_uri": _CB,
                "code_verifier": _VERIFIER})
check("F5 client_id 与授权码不匹配 ⇒ invalid_grant",
      _r.status_code == 400 and _r.json().get("error") == "invalid_grant",
      f"status={_r.status_code} body={_r.text[:160]}")

_r = call("POST", "/oauth/authorize",
          data=dict(_AZ, decision="deny", username="admin", password="pw-oauth-test"))
check("F6 拒绝授权 ⇒ 302 带 error=access_denied",
      _r.status_code == 302 and "access_denied" in _r.headers.get("location", ""),
      f"status={_r.status_code} loc={_r.headers.get('location','')[:120]}")

_, _r = _get_code(password="wrong-password")
check("F7 授权页口令错误 ⇒ 401 且仍是登录页（不放行）",
      _r.status_code == 401 and 'name="password"' in _r.text,
      f"status={_r.status_code}")

# =====================================================================
print(f"\n{'=' * 60}\n通过 {len(_passed)} / 共 {len(_passed) + len(_failed)}")
if _failed:
    print("失败项：")
    for n in _failed:
        print("  -", n)
    sys.exit(1)
print("全部通过")
sys.exit(0)
