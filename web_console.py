# -*- coding: utf-8 -*-
"""ai-memory Web 控制台后端（v3.1，2026-10-13）。

定位
----
给「人」用的管理界面，两件事：

1. **调试台** —— 像 API 调试一样直接调用 25 个 MCP 工具（查询/检索/看图）。
2. **配置面** —— FNS 同步配置 + 运行时阈值（``memory.toml``），不再靠手改文件。

本模块**不是** MCP 服务端，而是 MCP 的**外部客户端**：它通过 Streamable HTTP
连到 ai-memory 端点（默认 ``127.0.0.1:8700/mcp``）。因此它天然满足 v3 的两条判死项
——不直连 vault、不进程内 import 直调 —— 所有对记忆库的读写都走完整 MCP 协议。

🔴 本模块**不 import 核心仓的任何模块**（2026-10-16 收敛）
--------------------------------------------------------
曾经这里有一个 ``core_path.ensure_core_on_path()``：运行时定位 ``ai-memory-template``
目录并注入 ``sys.path``，好让本仓 ``import memory_config`` / ``import transport_http``。
那是**第二条腿** —— 除了「连 MCP」，Web 还要跨仓 import 核心模块。代价是两侧各持一份
「memory.toml 怎么读、怎么写、怎么校验」的知识，任一侧改动都可能让两边对不上；定位
逻辑本身还要维护一套上溯/回落规则。

现在这条腿已彻底拆掉：

* 阈值读写 ⇒ MCP 工具 ``memory_config``（唯一实现：核心仓 ``memory_config.py``）；
* MCP 端点默认地址 ⇒ 本文件里的字面常量（它本来就只是个默认值）。

⇒ 本仓对核心仓的关系**只剩「连接」一种**。副作用是分层守卫更强了：本仓导入后
``sys.modules`` 里有 ``mcp`` / ``starlette``，但**不会有任何核心仓模块**。

🔴 为什么必须「同源页面 + 后端代理」，而不是浏览器直连 MCP
----------------------------------------------------------
三条路都真起服务端实测过（`_v3_web_browser_probe.py` / `_v3_web_proxy_probe.py`）：

* **后端代理**（本模块采用）：后端用 SDK 客户端连 MCP（服务端→服务端，**不发
  ``Origin`` 头**）⇒ 实测 initialize / 25 工具 / memory_stats 全通，**MCP 端零配置
  改动**。
* **浏览器直连**（不可行）：``TransportSecuritySettings.allowed_origins`` 默认是空
  列表 ⇒ 任何带 ``Origin`` 头的请求一律 **403 Invalid Origin header**（这是刻意
  的 fail-closed 默认，不是缺陷）。即便把 Origin 写进白名单，SDK 也**不返回 CORS
  头**、``OPTIONS`` 预检返 **405** ⇒ 仍要自写 CORS 中间件才可用。
* **同进程 mount**：``streamable_http_app()`` 返回 Starlette，可以 mount，但会破坏
  「Web 台 = 独立一层」的分层，且把 MCP 端点与 Web 面绑成一个进程。

⇒ 定稿：浏览器只与 Web 台**同源**通信（普通 ``fetch`` + JSON，无 CORS），MCP 调用
一律在后端完成。

安全（回环默认 + 非回环必须有认证）
-----------------------------------
* 监听地址默认 ``127.0.0.1``（宿主机局域网看不到）。
* 一旦监听非回环地址且**既无 token 也无账号登录** ⇒ **拒绝启动**（fail-fast）。
  理由是「全放行调试台」= 对记忆库具备完整破坏能力的写入口，裸奔暴露在局域网上
  不可接受。判据是**两道认证任一成立**即放行（2026-10-22 修：原判据只认 token，
  导致「容器 = HOST=0.0.0.0 + USER/PASSWORD」这一标准形态被自家守卫打回 exit 2）。
* 配了 token 后，``/api/*`` 必须带 ``Authorization: Bearer <token>``（或
  ``X-Auth-Token``）；静态资源不校验（里面没有秘密）。前端把 token 存在
  ``sessionStorage``，**不进 URL、不进 bundle**。
* ``AI_MEMORY_WEB_ALLOWED_HOSTS``（可选）启用 Starlette ``TrustedHostMiddleware``
  —— DNS rebinding 并不依赖公网暴露，局域网下同样值得挡。

配置面口径
----------
* **FNS 凭据/配置**写进 **vault 之外**的 JSON（``AI_MEMORY_WEB_CONFIG``）——
  写进 vault 会被 fns-sync 同步出去（v3 红线 1）。
* **运行时阈值**读写一律经 MCP 工具 ``memory_config``（2026-10-16 起）：本模块
  **不解析、不渲染、不写盘** ``memory.toml`` —— 那三件事的唯一实现在核心仓
  ``memory_config.py``。整状态写（缺键即拒）、写前备份、原子替换都在服务端完成。
  ``AI_MEMORY_WEB_CONFIG_WRITE=0`` 仍在**本侧**关成只读（本台自己的策略开关）。
* **绝不触碰 ``*.md``**。

更新面（2026-10-15）
--------------------
* 「更新」= 从 git 远端把**白名单内**的文件取到当前工作区（后端运行时模块 +
  ``web/``），清单见 ``UPDATE_PATHS``。
* 用 ``git restore --source=<ref> --worktree``：只写工作区，不碰 HEAD、不碰 index；
  **行尾转换交给 git**（本机 ``core.autocrlf=true``，前端 ``.js``/``.css``/``.html``
  在工作区是 CRLF，任何"读对象再自己写盘"的实现都会把行尾改错）。
* 白名单内**未纳入版本控制**的文件，远端不会有它们 ⇒ 界面显式报「N 个文件未入库」，
  而不是显示「已是最新」。
* 重启后端由桌面 launcher 接手（``ai_memory_web.py restart``）：控制台在把响应写回
  浏览器之后自退，助手先 sleep 再动手 —— 顺序理由见 ``update_restart``。

环境变量
--------
========================================  =====================  ========================
变量                                       默认值                 说明
========================================  =====================  ========================
``AI_MEMORY_WEB_HOST``                    ``127.0.0.1``          监听地址
``AI_MEMORY_WEB_PORT``                    ``8811``               监听端口
``AI_MEMORY_WEB_MCP``                     ``http://127.0.0.1:8700/mcp``  上游 MCP 端点
``AI_MEMORY_WEB_TOKEN``                   （空）                 非回环必填；空=不鉴权
``AI_MEMORY_WEB_ALLOWED_HOSTS``           （空）                 TrustedHost 白名单
``AI_MEMORY_WEB_CONFIG``                  ``~/.ai-memory-web/config.json``  配置面存储
``AI_MEMORY_WEB_CONFIG_WRITE``            ``1``                  0=阈值只读
``AI_MEMORY_WEB_STATIC``                  ``<本文件同级>/web``    前端静态资源目录
``AI_MEMORY_CORE_DIR``                    （空）                 核心仓目录；**仅** ``--with-mcp`` 拉起 MCP 端点时需要（不再用于 import）
``AI_MEMORY_DIR``                         （空）                 vault 位置（仅用于界面显示；阈值走服务端自己的 vault）
``AI_MEMORY_RESTARTER``                   （空）                 重启助手路径；默认探测桌面 launcher
========================================  =====================  ========================
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import anyio
import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import (FileResponse, HTMLResponse, JSONResponse,
                                RedirectResponse, Response, StreamingResponse)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# 同目录模块（非第三方）。2026-10-21：账号登录与会话签名。
# 只用标准库实现，不给 requirements.txt 加任何依赖 —— 见 web_auth.py 顶部取舍说明。
# 2026-10-22：web_store 承载用户表与令牌表（多用户 + 可吊销令牌）。
# 2026-10-26：web_oauth 承载 OAuth 2.1 授权服务器（网页型 MCP 客户端的接入前提）。
import web_audit
import web_auth
import web_oauth
import web_store

logger = logging.getLogger("ai-memory.web")

#: 2026-10-26：这个 logger 此前**从未配置过 handler**。没有 handler 时只有
#: ``logging.lastResort`` 会放行 WARNING 及以上（无时间戳、无级别、无模块名），
#: 于是全仓所有 ``logger.info`` 在生产与测试中都静默丢弃。
#: 本轮排障正依赖 INFO 级的「鉴权失败原因 / OAuth 阶段」，不补配置等于写了个哑炮。
#:
#: 只做**最小**配置，边界明确：
#:   * 只挂 ``stderr``（启动器已把 stderr 重定向进 ~/.ai-memory-web/logs/）；
#:   * 只挂在本 logger 上，**不动 root、不动 uvicorn 的 handler**（否则访问日志
#:     会翻倍）；
#:   * ``propagate = False`` 防止将来有人配了 root 之后出现重复行；
#:   * 已有 handler 就直接返回 —— 宿主应用（如 pytest 的 caplog）可以自行接管。
_APP_LOG_FMT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def _ensure_app_logging() -> None:
    """给 ``ai-memory.web`` 挂上 stderr handler（幂等）。

    两道早退，**顺序不可颠倒**：

    1. **无 stderr 就不做**。``pythonw.exe`` 下未经重定向时 ``sys.stderr`` 是
       ``None``，``StreamHandler(None)`` 会得到 ``stream=None``：``emit()`` 抛
       ``AttributeError`` 被 ``handleError`` 吞掉 —— **不崩，但一行也写不出去**。
       那比不配置更坏：它会让人以为「已经挂上 handler 了」，排障时把「日志没
       出现」误判成「故障没发生」。
    2. **宿主已接管就不碰**。不只是不重复加 handler，连 ``setLevel`` /
       ``propagate`` 都不改 —— 宿主可能故意开着 ``DEBUG``，被我们压回 ``INFO``
       等于替别人做了降噪决定。

    正常路径（stderr 有效、无人接管）：挂一个 handler，级别 ``INFO``，
    ``propagate=False``。其余一概不动（不改 root、不改 uvicorn、改格式另议）。
    """
    if getattr(sys, "stderr", None) is None:
        return
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_APP_LOG_FMT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


WEB_VERSION = "1.12.0"
# ⚠️ 2026-10-22：此常量是控制台**唯一**的机器可读版本源，release.yml 会校验
#   `tag == WEB_VERSION == CHANGELOG 首条`。历史上一度停在 1.11.1 而 tag 已到
#   v1.11.3（漂了两个版本），界面「关于」显示的是旧号 —— 改版本时必须同改三处。
DEFAULT_WEB_HOST = "127.0.0.1"
# ⚠️ 本机实测（2026-10-13，Windows）：8800/8801/8802 均被系统保留（bind 报
# WinError 10013），故默认改用 8811 段。可选：8811-8820。
DEFAULT_WEB_PORT = 8811
# 上游 MCP 端点默认值。**刻意写成字面常量**而不是从核心仓 ``transport_http``
# 取（2026-10-16）：本仓不再 import 核心模块，而这里本来就只是个可被
# ``AI_MEMORY_WEB_MCP`` 覆盖的默认值 —— 为它维持一条跨仓 import 通道不划算。
DEFAULT_MCP_URL = "http://127.0.0.1:8700/mcp"
DEFAULT_CONFIG_PATH = Path.home() / ".ai-memory-web" / "config.json"
DEFAULT_CONFIG_WRITE = True

#: 登录启用时，若既无 token 也无 AI_MEMORY_WEB_SECRET，用它签会话。
#: 这种组合只出现在「回环地址 + 无 token」——本来就不需要鉴权，会话稳定性无意义；
#: 用进程内随机值即可，重启后自然失效。
_FALLBACK_SESSION_KEY = secrets.token_bytes(32)
#: 明文口令形态（AI_MEMORY_WEB_PASSWORD）的哈希缓存：scrypt 一次约 180 ms，
#: 而 config() 会在启动时被多次调用，不缓存就是几十次无谓的慢哈希。
_LOGIN_HASH_CACHE: str = ""
MAX_BODY_BYTES = 2 * 1024 * 1024          # 请求体上限 2 MiB（拒绝无脑大包）
MCP_TIMEOUT = 90.0                        # 单次会话总超时（秒）
MCP_HEALTH_TIMEOUT = 20.0
# 回传浏览器的文本封顶。**不能太小**：`memory_list` / `memory_recent` 支持的
# `output_format="json"` 是一条 JSON 字符串，截断会让它直接解析失败（探针踩过）。
# 40k 字符足够容纳「列表 50 条 + 笔记正文」，又能挡住病态大包。
_THUMB = 40000

#: 网关回调本服务的内部校验端点（nginx ``auth_request`` 用）。
#: 不在 ``/api/`` 前缀下 —— 它走的是容器间内网，凭据是 ``X-Internal-Key``
#: 而不是用户会话；放错前缀会被用户鉴权中间件拦死。
INTERNAL_VERIFY_PATH = "/internal/token/verify"

#: MCP 反代入口（2026-10-22，v1.7.0）。控制台自己挂一个 ``/mcp``，鉴权后
#: 流式转发到 ``resolve_mcp()`` 指向的上游（默认 ``127.0.0.1:8700/mcp``）。
#: 存在的理由：上游 MCP 端点**根本不鉴权**（只绑回环），而令牌表只在控制台这边；
#: 想让「另一台设备拿一枚限时令牌就能连 MCP」成立，必须有一个既认令牌又能
#: 转发流式响应的门口。控制台本来就在这个位置上，加一层是零新增依赖。
MCP_PROXY_PATH = "/mcp"

#: **机器接口命名空间**：这些前缀下的未知路径必须回 404 JSON，绝不回落
#: ``index.html``（2026-10-26 诊断）。
#:
#: 为什么必须分开：catch-all 对浏览器是「刷新不 404」的便利，对机器客户端却是
#: 毒药 —— 实测 ``GET /.well-known/oauth-protected-resource/mcp`` 与
#: ``GET /mcp/reader`` 都返回 **200 + 5013 B HTML**，客户端按 JSON / JSON-RPC
#: 解析后只报「格式错误」，而这条线索根本推不回路由层（200 看起来是成功的）。
#:
#: 只列**非浏览器**的四个前缀。前端是纯 hash 路由（``web/js/core/router.js``
#: 只读 ``location.hash``，全仓无 ``pushState``），页面路径恒为 ``/``，所以
#: ``/some/deep/path`` 这类深路径仍应回落首页。
#:
#: ⚠️ 将来若启用 history 路由，这里要把页面 id 加进白名单，否则那些页面会 404。
MACHINE_PATH_PREFIXES = ("api/", ".well-known/", "oauth/", "mcp/")

#: 反代时**不转发**的请求头：跳数头 + 我们自己的凭据（令牌是给本控制台的，
#: 不该漏给上游；上游也不需要 Cookie）。
_PROXY_DROP_REQ = frozenset({
    "host", "content-length", "connection", "transfer-encoding", "keep-alive",
    "upgrade", "te", "trailer", "proxy-authorization", "proxy-connection",
    "authorization", "x-auth-token", "cookie",
})

#: 反代时**不回传**的响应头：长度与编码由本层重新决定（httpx 已解压，若再
#: 带上游的 content-encoding，客户端会把明文当 gzip 解，直接报错）。
_PROXY_DROP_RESP = frozenset({
    "content-length", "content-encoding", "transfer-encoding", "connection",
    "keep-alive",
})


def token_from_request(request: Request) -> str:
    """从请求里取令牌：``Authorization: Bearer`` > ``X-Auth-Token`` > ``?token=``。

    ``?token=`` 是 2026-10-22 新增的第三通道，只为「MCP 客户端只让填一个 URL」
    这类场景 —— 多数 MCP 客户端支持自定义 header，但配置项常常只暴露 URL 一项。
    **代价必须说清**：令牌写进 URL 会进 uvicorn 的访问日志、浏览器历史和反代日志，
    所以它适合内网/本机，不适合暴露到公网；能配 header 就用 header。
    """
    raw = request.headers.get("Authorization", "")
    if raw.lower().startswith("bearer "):
        got = raw[7:].strip()
        if got:
            return got
    got = request.headers.get("X-Auth-Token", "").strip()
    if got:
        return got
    return str(request.query_params.get("token") or "").strip()


_TRUTHY = {"1", "true", "yes", "on", "y", "t"}

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}

# FNS 配置允许的字段（写盘时按此白名单过滤 —— 不落未知字段，避免手滑把秘密写歪）
#
# ⚠️ 2026-10-23：``account`` → ``client_type``。FNS **没有「账号」这个维度**：
#   令牌的三维是 `p:` 协议 / `c:` 客户端 / `Vaults` 库白名单，其中 `c:` 对应的
#   就是客户端 config 里的 ``client_type``（旧标签「账号」会让人填登录名，然后
#   WS 握手 315）。旧配置里的 ``account`` 键读取时自动迁移，见 ``_FNS_LEGACY``。
_FNS_FIELDS = ("server", "client_type", "vault", "token", "exclude")
_FNS_LEGACY = {"account": "client_type"}
_EXCLUDE_MAX = 200


class WebConfigError(RuntimeError):
    """Web 控制台配置不合法 —— fail-fast，绝不带着危险默认值启动。"""


# ---------------------------------------------------------------------------
# 环境变量
# ---------------------------------------------------------------------------
def _env_str(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return default if v is None else v.strip()


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in _TRUTHY


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v.strip())
    except (TypeError, ValueError):
        raise WebConfigError(f"{name}={v!r} 不是整数。")


def is_loopback(host: str) -> bool:
    return host.strip().lower() in _LOOPBACK_HOSTS


def static_dir() -> Path:
    """前端静态资源目录（``AI_MEMORY_WEB_STATIC`` 可覆盖）。"""
    raw = _env_str("AI_MEMORY_WEB_STATIC")
    return Path(raw) if raw else (Path(__file__).resolve().parent / "web")


def config_path() -> Path:
    raw = _env_str("AI_MEMORY_WEB_CONFIG")
    return Path(raw).expanduser() if raw else DEFAULT_CONFIG_PATH


#: 用户表 / 令牌表的进程内单例，按用户表路径做键。
#: **必须是单例**：``TokenStore`` 在内存里攒计次增量与「上次落盘时间」，
#: 重复实例化会让同一枚令牌的每一次请求都读到旧的 uses 值 —— 限次直接失效。
_STORES: dict[str, tuple] = {}


def _get_stores(users_path: Path, tokens_path: Path):
    key = str(users_path)
    got = _STORES.get(key)
    if got is None:
        got = (web_store.UserStore(users_path), web_store.TokenStore(tokens_path))
        _STORES[key] = got
    return got


_AUDITS: dict[str, web_audit.AuditLog] = {}


def _get_audit(path: Path) -> web_audit.AuditLog:
    """审计流按路径缓存（与 ``_get_stores`` 同一取向）。

    缓存不是为了省对象，而是为了让**同一个文件只对应一个写者**：``AuditLog``
    自带进程内锁，若每请求新建实例，锁就形同虚设，两条并发的追加可能交错写
    同一行（JSONL 一旦半行损坏，那条记录就只能被跳过）。
    """
    key = str(path)
    got = _AUDITS.get(key)
    if got is None:
        got = web_audit.AuditLog(path)
        _AUDITS[key] = got
    return got


_OAUTH_CLIENTS: dict[str, web_oauth.ClientStore] = {}
_OAUTH_CODES: web_oauth.CodeStore | None = None
_OAUTH_LOCK = threading.Lock()


def _get_oauth_clients(path: Path) -> web_oauth.ClientStore:
    """客户端注册表按路径缓存（**一个进程内同一文件只允许有一个写者**）。

    为什么必须缓存：``ClientStore`` 把 ``oauth_clients.json`` 读进内存、每次
    注册后整体重写。如果每个请求都新建实例，两个实例各持一份快照，后写的一方
    会把先写的一方**静默覆盖** —— 现象是「刚注册的客户端过一会儿就不认识了」。
    与 ``_get_stores`` 同一取向。
    """
    key = str(path)
    got = _OAUTH_CLIENTS.get(key)
    if got is None:
        got = web_oauth.ClientStore(path)
        _OAUTH_CLIENTS[key] = got
    return got


def _get_oauth_codes() -> web_oauth.CodeStore:
    """授权码仓库：进程级单例（纯内存，重启即清空，见 web_oauth.CodeStore）。"""
    global _OAUTH_CODES
    with _OAUTH_LOCK:
        if _OAUTH_CODES is None:
            _OAUTH_CODES = web_oauth.CodeStore()
        return _OAUTH_CODES


def _accepts_mcp(request: Request) -> bool:
    """这个请求的 ``Accept`` 是否点名要了 MCP 的两种类型之一。

    MCP Streamable HTTP 要求客户端 ``Accept`` 里**同时**有
    ``application/json`` 与 ``text/event-stream``（POST 只带后者、GET 只带前者
    上游都会 406）。判据取「含其一」而非「含其二」，是为了让**半对的真客户端**
    照旧打到上游、由上游自己报那条精确的协议错误 —— 这里只负责把「人类探测」
    （浏览器 / curl / 网页读取工具）分出来。
    """
    accept = (request.headers.get("accept") or "").lower()
    return "text/event-stream" in accept or "application/json" in accept


def _public_base(request: Request, cfg: dict) -> str:
    """本次请求对应的**外部可见**基址（不带尾斜杠）。

    优先级：显式 ``AI_MEMORY_WEB_PUBLIC_URL`` > 反代头 > 请求自身。

    为什么不能只用 ``request.base_url``：控制台只绑回环，经 Cloudflare Tunnel
    转发后本地看到的 scheme 恒为 ``http``、host 恒为 ``127.0.0.1:8890``。
    把这两个直接拼进 OAuth 元数据，客户端拿到的授权地址会指向它自己的内网
    ⇒ 表现为「授权页打不开」或「issuer 校验失败」。cloudflared 会带
    ``X-Forwarded-Proto`` / ``X-Forwarded-Host``，优先采信它们。
    """
    fixed = str(cfg.get("public_url") or "").strip().rstrip("/")
    if fixed:
        return fixed
    proto = (request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
             or request.url.scheme or "http")
    host = (request.headers.get("x-forwarded-host", "").split(",")[0].strip()
            or request.headers.get("host", "") or request.url.netloc)
    if not host:
        return ""
    return f"{proto}://{host}"


def config() -> dict:
    """解析运行时配置（含全部校验）。危险组合一律抛错，不静默兜底。"""
    host = _env_str("AI_MEMORY_WEB_HOST", DEFAULT_WEB_HOST) or DEFAULT_WEB_HOST
    port = _env_int("AI_MEMORY_WEB_PORT", DEFAULT_WEB_PORT)
    if not (1 <= port <= 65535):
        raise WebConfigError(f"AI_MEMORY_WEB_PORT={port} 不在 1..65535。")

    token = _env_str("AI_MEMORY_WEB_TOKEN")
    # 非回环监听的认证守卫**移到登录配置解析之后**（见下方 2026-10-22 的修）：
    # 判据是「token 或账号登录至少有一道」，而不是「必须有 token」。

    mcp = _env_str("AI_MEMORY_WEB_MCP", DEFAULT_MCP_URL) or DEFAULT_MCP_URL
    if not re.match(r"^https?://", mcp):
        raise WebConfigError(f"AI_MEMORY_WEB_MCP={mcp!r} 必须是 http(s):// URL。")

    allowed_hosts = [x.strip() for x in _env_str("AI_MEMORY_WEB_ALLOWED_HOSTS").split(",")
                     if x.strip()]
    static = static_dir()
    if not (static / "index.html").is_file():
        raise WebConfigError(
            f"前端静态资源缺失：{static / 'index.html'} 不存在。"
            "请确认 web/ 目录已随仓库就位（2026-10-15 起为模块化结构："
            "index.html + js/ （ESM 模块树，入口 js/main.js）"
            " + css/ （按层 1..8 共 8 片，引入顺序即层叠顺序）"
            " + vendor/ （vue/marked/purify/gsap/Flip）），"
            "或用 AI_MEMORY_WEB_STATIC 指定目录。")

    # ---- 账号登录（2026-10-21，方案 A） ---------------------------------
    # 三种配置形态，**半配即拒**：
    #   · USER + PASSWORD_HASH → 标准形态（.env 里只存 scrypt 哈希）
    #   · USER + PASSWORD      → 便捷形态（明文留在 .env，启动时现场哈希）
    #   · 只给其一             → 拒绝启动：半配等于没配，却会让人以为已开启登录
    global _LOGIN_HASH_CACHE
    login_user = _env_str("AI_MEMORY_WEB_USER")
    login_hash = _env_str("AI_MEMORY_WEB_PASSWORD_HASH")
    login_plain = _env_str("AI_MEMORY_WEB_PASSWORD")
    if bool(login_user) != bool(login_hash or login_plain):
        raise WebConfigError(
            "登录配置不完整：AI_MEMORY_WEB_USER 必须与 "
            "AI_MEMORY_WEB_PASSWORD_HASH（或 AI_MEMORY_WEB_PASSWORD）同时给出。"
            "生成哈希：python make_password.py（本仓根目录，交互输入不回显），"
            "把它输出的两行一起填上。")
    login_enabled = bool(login_user and (login_hash or login_plain))
    if login_enabled and not login_hash:
        if not _LOGIN_HASH_CACHE:
            _LOGIN_HASH_CACHE = web_auth.hash_password(login_plain)
        login_hash = _LOGIN_HASH_CACHE

    # ---- 非回环监听的认证守卫（2026-10-22 修）----------------------------
    # 原判据只认 ``AI_MEMORY_WEB_TOKEN``，而容器的标准形态是
    # ``HOST=0.0.0.0`` + ``USER/PASSWORD``（令牌不给用户看）——于是容器**一启动
    # 就被自家守卫打回 exit 2**，v1.11.0 的镜像根本起不来（冒烟测试逮到）。
    # 守卫要防的是「裸奔：局域网内谁都能打开调试台写记忆库」，令牌与账号登录
    # 都构成一道认证，任一成立即不算裸奔。
    if not is_loopback(host) and not token and not login_enabled:
        raise WebConfigError(
            f"监听非回环地址 {host!r} 时至少要有一道认证："
            "AI_MEMORY_WEB_TOKEN，或账号登录（AI_MEMORY_WEB_USER + 口令）。"
            "两者都没有时，局域网内任何人都能打开调试台并对记忆库执行破坏性操作。"
            '示例：AI_MEMORY_WEB_TOKEN="$(openssl rand -hex 16)"')

    secret = _env_str("AI_MEMORY_WEB_SECRET")
    # 会话密钥：显式 secret 优先；否则从 token 派生（换 token = 全场会话立即失效）。
    # 两者都空只会出现在「回环 + 无 token」——用进程内随机值，重启即失效。
    session_key = (web_auth.derive_key(token, secret)
                   if (token or secret) else _FALLBACK_SESSION_KEY)
    session_ttl = _env_int("AI_MEMORY_WEB_SESSION_TTL", web_auth.SESSION_TTL)
    if session_ttl < 60:
        raise WebConfigError(
            f"AI_MEMORY_WEB_SESSION_TTL={session_ttl} 太短（至少 60 秒）。")

    # ---- 多用户与访问令牌（2026-10-22）-----------------------------------
    # 两张表与 config.json 同目录（容器里是 /config，bind 到 web-config 卷）。
    # **刻意不放进 .env**：账号要能在线增删改，而改 .env 需要重建容器才生效
    # （-e 在建容器时固化），那样「管理员给同事开个号」就变成了停机操作。
    cfg_dir = config_path().parent
    users_path = Path(_env_str("AI_MEMORY_WEB_USERS") or (cfg_dir / "users.json"))
    tokens_path = Path(_env_str("AI_MEMORY_WEB_TOKENS") or (cfg_dir / "tokens.json"))
    users, tokens = _get_stores(users_path, tokens_path)

    # 审计流（2026-10-27）：访问控制页「访问日志」卡的数据面。
    # 默认落在配置目录旁边，与 users/tokens 同级 —— 它是**同一份运维事实**的一部分，
    # 不该跟日志文件混在 logs/ 里（那里的东西可被清、可被外部轮转）。
    audit_path = Path(_env_str("AI_MEMORY_WEB_AUDIT") or (cfg_dir / "audit.jsonl"))
    audit = _get_audit(audit_path)

    # 从旧版单用户配置平滑迁移：表为空时把 .env 里那组 USER + HASH 变成 admin。
    # 没有这一步，升级后 users.json 是空的 —— 谁都登不进去，只能进容器手改文件。
    if login_enabled and users.bootstrap(login_user, login_hash, "admin"):
        logger.warning("用户表为空，已用 AI_MEMORY_WEB_USER=%s 建立初始管理员", login_user)

    # 只要表里有账号，就必须开登录面 —— 否则「users.json 有 5 个人」而
    # login_enabled 为 False，中间件不挂、人人免登录，是最危险的一种静默失配。
    multi_user = users.count() > 0
    if multi_user and not login_enabled:
        logger.info("用户表已有账号，登录面自动启用")
        login_enabled = True
    if not multi_user and not login_enabled:
        logger.warning("用户表为空且未配置账号登录：只有令牌通道可用，无法管理用户。")

    # 内部校验密钥：网关（nginx auth_request）回调本服务时必带。
    # 空 = 关闭内部端点（退回单 token 精确匹配的老路子），便于灰度与回滚。
    internal_key = _env_str("AI_MEMORY_WEB_INTERNAL_KEY")

    # 🔴 向后兼容：把 .env 里两枚老令牌认领进表。
    # 不做这一步，升级后它们不在表里 ⇒ 校验全部落空 ⇒ 脚本与 MCP 客户端
    # **在同一秒**集体 401，而且现象是「token 明明没改却失效了」。
    # AI_MEMORY_TOKEN 是网关那枚：容器里本来没有这个环境变量，
    # deploy 脚本改造后才会传进来（不传则跳过，不影响控制台自身）。
    if token:
        if tokens.adopt(token, name=".env AI_MEMORY_WEB_TOKEN",
                        owner=login_user or "system"):
            logger.info("已把 AI_MEMORY_WEB_TOKEN 纳入令牌表（admin / 永不过期）")
    gw_token = _env_str("AI_MEMORY_TOKEN")
    if gw_token:
        if tokens.adopt(gw_token, name=".env AI_MEMORY_TOKEN（网关）",
                        owner=login_user or "system"):
            logger.info("已把 AI_MEMORY_TOKEN 纳入令牌表（admin / 永不过期）")

    # ---- OAuth 2.1 授权服务器（2026-10-26）--------------------------------
    # 解决的是「网页型 AI 产品无法粘贴令牌」这一特定问题：这类客户端只走
    # MCP Authorization（401 → 元数据 → 动态注册 → 授权页 → 换令牌）。
    # 默认跟随认证形态开启：纯回环裸跑时既没有 token 也没有账号，没人可授权，
    # 开着只会凭空多两个匿名端点。
    oauth_enabled = (bool(_env_bool("AI_MEMORY_WEB_OAUTH", True))
                     and bool(token or login_enabled))
    # 公网基址。元数据里必须是**外部可见**的绝对 URL，否则 issuer 校验必失败；
    # 能显式配就显式配，推导逻辑见 _public_base（依赖反代头）。
    public_url = (_env_str("AI_MEMORY_WEB_PUBLIC_URL") or "").rstrip("/")
    if public_url and not re.match(r"^https?://", public_url):
        raise WebConfigError(
            f"AI_MEMORY_WEB_PUBLIC_URL={public_url!r} 必须是 http(s):// URL。")
    oauth_clients_path = Path(_env_str("AI_MEMORY_WEB_OAUTH_CLIENTS")
                              or (cfg_dir / "oauth_clients.json"))
    oauth_clients = _get_oauth_clients(oauth_clients_path)

    return {
        "host": host,
        "port": port,
        "token": token,
        "auth_enabled": bool(token),
        "login_enabled": login_enabled,
        "login_user": login_user,
        "login_hash": login_hash,
        "session_key": session_key,
        "session_ttl": session_ttl,
        "cookie_secure": _env_bool("AI_MEMORY_WEB_COOKIE_SECURE", False),
        "users_path": str(users_path),
        "tokens_path": str(tokens_path),
        "users": users,
        "tokens": tokens,
        "audit_path": str(audit_path),
        "audit": audit,
        "multi_user": multi_user,
        "internal_key": internal_key,
        "mcp": mcp,
        "allowed_hosts": allowed_hosts,
        "static": static,
        "config_path": config_path(),
        "config_write": _env_bool("AI_MEMORY_WEB_CONFIG_WRITE", DEFAULT_CONFIG_WRITE),
        # OAuth 面（2026-10-26）
        "oauth_enabled": oauth_enabled,
        "oauth_clients": oauth_clients,
        "oauth_clients_path": str(oauth_clients_path),
        "oauth_codes": _get_oauth_codes(),
        "public_url": public_url,
    }


def describe(cfg: dict | None = None) -> str:
    cfg = cfg or config()
    modes = []
    if cfg["auth_enabled"]:
        modes.append("token")
    if cfg["login_enabled"]:
        modes.append(f"登录:{cfg['login_user']}")
    auth = "+".join(modes) if modes else "关（仅回环）"
    return (f"http://{cfg['host']}:{cfg['port']}/  →  MCP {cfg['mcp']}  "
            f"auth={auth}  config={cfg['config_path']}")


# ---------------------------------------------------------------------------
# 配置面：vault 之外的 JSON（FNS 凭据等）
# ---------------------------------------------------------------------------
def _blank_app_config() -> dict:
    return {
        "mcp_endpoint": "",
        "vault_dir": "",
        "fns": {k: "" for k in _FNS_FIELDS},
        "ui": {"theme": "auto"},
        "updated": "",
    }


def _sanitize_app_config(raw: Any) -> dict:
    """把任意输入收敛成合法结构（不信任前端来的东西）。"""
    out = _blank_app_config()
    if not isinstance(raw, dict):
        return out
    out["mcp_endpoint"] = str(raw.get("mcp_endpoint") or "").strip()[:500]
    out["vault_dir"] = str(raw.get("vault_dir") or "").strip()[:500]
    fns = raw.get("fns")
    if isinstance(fns, dict):
        src = dict(fns)
        # 旧键迁移：只有当新键为空时才搬，避免覆盖用户刚写的新值。
        for old, new in _FNS_LEGACY.items():
            if src.get(old) and not src.get(new):
                src[new] = src[old]
        for k in _FNS_FIELDS:
            v = src.get(k, "")
            if k == "exclude":
                if isinstance(v, str):
                    items = [x.strip() for x in re.split(r"[\r\n,]+", v) if x.strip()]
                elif isinstance(v, list):
                    items = [str(x).strip() for x in v if str(x).strip()]
                else:
                    items = []
                out["fns"][k] = items[:_EXCLUDE_MAX]
            else:
                out["fns"][k] = str(v or "").strip()[:2000]
    ui = raw.get("ui")
    if isinstance(ui, dict):
        theme = str(ui.get("theme") or "auto")
        out["ui"]["theme"] = theme if theme in ("auto", "light", "dark") else "auto"
    out["updated"] = str(raw.get("updated") or "")
    return out


def load_app_config() -> dict:
    p = config_path()
    if not p.is_file():
        return _blank_app_config()
    try:
        return _sanitize_app_config(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        logger.warning("读取 %s 失败（用空配置）：%s", p, e)
        return _blank_app_config()


def save_app_config(raw: dict) -> dict:
    """原子写（同目录 tmp + replace）。配置目录不在 vault 内，故 fns token 不会被同步出去。"""
    cfg = _sanitize_app_config(raw)
    cfg["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    os.replace(str(tmp), str(p))
    return cfg


# ---------------------------------------------------------------------------
# 配置面 · FNS 连通性探针（2026-10-23）
#
# 为什么需要：配置页 FNS 卡此前只做**落账**（把 server/client_type/vault/token 写进
# vault 之外的 JSON），控制台从不与服务端说过一句话 ⇒ 填错地址、令牌被吊销、
# vault 白名单没放行，界面上全都长得一样：保存成功。排查只能靠人肉 curl，
# 于是「获取不到配置」永远指向不了真正的原因。
#
# 这里用 FNS 自己的两个公开端点做一次**语义化体检**：
#   ① ``GET /api/health``  —— 无鉴权，只看服务在不在、版本多少；
#   ② ``GET /api/vault``   —— 有鉴权，考「协议 p: / 客户端 c: / 库白名单 Vaults」
#      三个维度（见 [[FNS令牌三维scope与vault白名单取证20261020]]）。
# 返回的 ``code`` 是 FNS 的业务码（1 成功 / 308 令牌吊销 / 315 权限不足），
# 前端按码着色并给出**可执行**的提示 —— 不再让人猜。
#
# 安全边界：探针只向「用户在配置里填的 server」发请求，路径写死；不跟随重定向
# （避免被引到别的主机）。控制台本身只绑内网/回环，且该端点要求已登录。
# ---------------------------------------------------------------------------
FNS_PROBE_TIMEOUT = 6.0
#: ``x-client`` 候选：令牌的 ``c:`` 维度必须与之匹配（小写比较）。先试配置里的
#: client_type，再按常见值兜底 —— 命不中就说明 ``c:`` 维度写的是别的串。
FNS_PROBE_CLIENTS = ("GoFastNoteSync", "gofastnotesync", "obsidian",
                     "ObsidianPlugin", "mobile", "desktop")

_FNS_CODE_HINT = {
    1: "",
    304: "该接口在这台服务端上不存在（版本过旧或不是 FNS）",
    305: "请求参数不合法",
    308: "令牌已吊销或不存在 —— 需要到 FNS 后台重新签发一枚",
    314: "未登录或凭据缺失",
    315: "令牌无权限 —— 协议(p:) / 客户端(c:) / 库白名单(Vaults) 三者之一未放行",
}


def _fns_server(raw: Any) -> str:
    """规范化并校验服务地址（只要 http/https + 有主机名）。"""
    s = str(raw or "").strip().rstrip("/")
    if not s:
        raise WebConfigError("请先填写 FNS 服务地址（形如 https://host:58889）。")
    parts = urlsplit(s)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise WebConfigError(f"服务地址不合法：{s}（需要 http:// 或 https:// 开头）")
    return s


def _fns_get(base: str, path: str, token: str = "",
             client: str = "") -> tuple[int, dict]:
    """请求 FNS 的一个 GET 端点，返回 ``(http_status, json)``。

    FNS 的业务失败也是 HTTP 200 + ``code != 1``，所以调用方**必须看 code**，
    不能只看状态码。自签证书很常见（NAS/内网），故不对证书做校验。
    """
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if client:
        headers["x-client"] = client
    # 代理环境变量（http_proxy/https_proxy）会把**内网**地址也送去代理，得到
    # 一个和真相无关的 502 —— 本机实测踩到过（ProxyError 冒充「服务不可达」）。
    # 故先直连；直连不通再退回走环境代理，覆盖「只有代理能出网」的部署形态。
    last_exc: Exception | None = None
    first_exc: Exception | None = None
    for trust_env in (False, True):
        try:
            with httpx.Client(timeout=FNS_PROBE_TIMEOUT, verify=False,
                              follow_redirects=False,
                              trust_env=trust_env) as c:
                r = c.get(base + path, headers=headers)
            break
        except httpx.HTTPError as e:
            last_exc = e
            if first_exc is None:
                first_exc = e
    else:
        # 报**直连**那次的错误：代理错误（502）说的是代理，不指向用户填的地址。
        exc = first_exc or last_exc
        raise WebConfigError(f"连不上 {base}：{exc.__class__.__name__}"
                             f"（{str(exc)[:120]}）") from exc
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:300]}
    if not isinstance(body, dict):
        body = {"raw": body}
    return r.status_code, body


def fns_probe(server: Any, token: Any, vault: Any = "",
              client: Any = "") -> dict:
    """FNS 体检。返回可直接给前端渲染的结构（不抛业务错误）。"""
    base = _fns_server(server)
    tok = str(token or "").strip()
    want = str(vault or "").strip()
    want_client = str(client or "").strip()

    result: dict[str, Any] = {
        "server": base, "vault": want, "reachable": False, "version": "",
        "client": "", "code": None, "message": "", "details": "",
        "hint": "", "vaults": [], "vault_found": False, "note_count": None,
        "token_present": bool(tok),
    }

    # ① 服务在不在（/api/health 不需要鉴权）
    try:
        _st, health = _fns_get(base, "/api/health")
    except WebConfigError as e:
        result["message"] = str(e)
        result["hint"] = "检查地址、端口与网络连通性；内网设备需同一网段。"
        return result
    result["reachable"] = True
    hdata = health.get("data") if isinstance(health.get("data"), dict) else {}
    result["version"] = str(hdata.get("version") or "")

    if not tok:
        result["message"] = "未填写令牌"
        result["hint"] = "令牌是 FNS 后台签发的那串 JWT，通常以 eyJ 开头。"
        return result

    # ② 鉴权 + 库列表：逐个 client 候选，第一个 code==1 即命中
    tried: list[str] = []
    for cand in ([want_client] if want_client else []) + list(FNS_PROBE_CLIENTS):
        if cand in tried:
            continue
        tried.append(cand)
        try:
            _st, body = _fns_get(base, "/api/vault", tok, cand)
        except WebConfigError as e:
            result["message"] = str(e)
            return result
        code = body.get("code")
        if code == 1:
            result["client"] = cand
            result["code"] = 1
            result["message"] = str(body.get("message") or "Success")
            # 命中即清空：先前候选失败留下的 details 会把人引向已经排掉的假设。
            result["details"] = ""
            rows = body.get("data") if isinstance(body.get("data"), list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                result["vaults"].append({
                    "vault": str(row.get("vault") or ""),
                    "note_count": row.get("noteCount"),
                    "file_count": row.get("fileCount"),
                    "updated_at": row.get("updatedAt"),
                })
            break
        result["code"] = code
        result["message"] = str(body.get("message") or "")
        result["details"] = str(body.get("details") or "")

    if result["code"] != 1:
        result["hint"] = _FNS_CODE_HINT.get(
            result["code"],
            "服务可达但拒绝了请求 —— 看 details 里的原文。")
        if result["details"]:
            result["hint"] += f"（服务端原文：{result['details']}）"
        return result

    if want:
        hit = next((v for v in result["vaults"] if v["vault"] == want), None)
        result["vault_found"] = hit is not None
        result["note_count"] = hit["note_count"] if hit else None
        if hit is None:
            result["hint"] = ("令牌可用，但这枚令牌看不到该库 —— 库名区分大小写；"
                              "若确认拼写正确，去 FNS 后台把该库加进令牌的 Vaults 白名单。")
        elif not hit["note_count"]:
            result["hint"] = "库已存在但还没有笔记（首次同步会自动建库/灌入）。"
    return result


# ---------------------------------------------------------------------------
# 配置下发 · 把 FNS 配置渲染成 fns-sync 的 config.yaml（2026-10-23，方案 C）
#
# 为什么要有：控制台此前只是「记事本」——它写自己的 config.json，fns-sync 读自己
# 的 config.yaml，两者永不照面（2026-10-23 排障时实测：改完控制台，容器毫无反应）。
# 方案 C 的方向是**容器反向拉取**：fns-sync 启动时向控制台要一份渲染好的 YAML，
# 拿不到才回退它自带的模板。好处是不用给容器任何写权限，也不破 ``:ro`` 红线。
#
# 键名逐条对照 upstream ``internal/config/config.go``，与中心部署包的模板同源；
# 改了这里必须同步 ``fns-sync/config.yaml`` 的兜底模板，否则两条路会漂。
# ---------------------------------------------------------------------------
FNS_CONFIG_PATH = "/internal/fns/config.yaml"

#: 结构默认值（不随部署变的那些）。可被控制台容器的环境变量覆盖。
_FNS_YAML_HEAD = """\
# ⚠️ 由 ai-memory Web 控制台生成，请勿手改 —— 容器下次拉取会整份覆盖。
# 配置真源 = 控制台「配置 → FNS 同步」（落盘在 vault 之外的 config.json）。
# 生成时间：{stamp}
# 修订号：{revision}
"""


def _yaml_str(v: Any) -> str:
    """标量转 YAML 双引号字符串。

    JSON 字符串字面量与 YAML 双引号标量同构（``\\"`` 与 ``\\\\`` 的转义规则一致），
    直接借 ``json.dumps`` 的输出即可，不必手写一套容易漏掉边界字符的转义表。
    """
    return json.dumps(str(v if v is not None else ""), ensure_ascii=False)


def fns_sync_config(app_fns: dict) -> tuple[str, list[str]]:
    """渲染 fns-sync 的 config.yaml，返回 ``(文本, 缺失项)``。

    缺失 ``server`` / ``token`` / ``vault`` 时**不生成**（返回空串 + 缺失项列表）：
    让调用方回 503，容器据此回退到自己的兜底模板。拿一份空令牌的 YAML 去启动，
    故障会推迟到 WS 握手阶段才炸，那是最难定位的一种。
    """
    server = str(app_fns.get("server") or "").strip()
    token = str(app_fns.get("token") or "").strip()
    vault = str(app_fns.get("vault") or "").strip()
    client = str(app_fns.get("client_type") or "").strip() or "GoFastNoteSync"
    extra = [str(x).strip() for x in (app_fns.get("exclude") or []) if str(x).strip()]

    missing = [k for k, v in (("server", server), ("token", token),
                              ("vault", vault)) if not v]
    if missing:
        return "", missing

    # 排除表 = 不可协商的四个 + 用户在控制台加的；保序去重。
    folders: list[str] = []
    for item in (".git", ".obsidian", ".trash", "ai-memory") + tuple(extra):
        if item not in folders:
            folders.append(item)
    extensions = [".db", ".tmp", ".lock", ".json", ".syncbak"]

    vault_path = _env_str("AI_MEMORY_FNS_VAULT_PATH") or "/vault"
    state_file = _env_str("AI_MEMORY_FNS_STATE_FILE") or "/state/state.json"

    lines: list[str] = []
    lines.append(_FNS_YAML_HEAD.format(
        stamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        revision="-（见响应头 X-Fns-Config-Revision）"))
    lines.append(f"api: {_yaml_str(server)}")
    lines.append(f"api_token: {_yaml_str(token)}")
    lines.append(f"vault: {_yaml_str(vault)}")
    lines.append(f"vault_path: {_yaml_str(vault_path)}")
    lines.append(f"client_type: {_yaml_str(client)}")
    lines.append("")
    lines.append("sync_enabled: true")
    # 🔴 默认 true 会把 .obsidian/data.json 一类配置回灌，必须显式关掉
    lines.append("config_sync_enabled: false")
    # 🔴 实测语义 = 双向静默（不是「只拉不推」），设 true 会连上传一起断掉
    lines.append("readonly_sync_enabled: false")
    lines.append("offline_delete_sync_enabled: false")
    lines.append("manual_sync_enabled: false")
    lines.append("")
    lines.append("sync_update_delay: 500")
    lines.append("startup_delay: 60")
    lines.append("sync_timeout_seconds: 120")
    lines.append("binary_sync_limit_enabled: true")
    lines.append("concurrency_control_enabled: true")
    lines.append("max_concurrent_uploads: 3")
    lines.append("")
    lines.append("sync_exclude_folders:")
    lines.extend(f"  - {_yaml_str(x)}" for x in folders)
    lines.append("")
    lines.append("sync_exclude_extensions:")
    lines.extend(f"  - {_yaml_str(x)}" for x in extensions)
    lines.append("")
    lines.append(f"state_file: {_yaml_str(state_file)}")
    return "\n".join(lines) + "\n", []


#: 本来就只读的视野档。服务端不为它们生成 `-ro` 变体（等价路径等于白送一个
#: 可绕过的口子），所以拼端点时也不能加后缀。
_READONLY_LEVELS = frozenset({"guest", "reader"})


def resolve_mcp(cfg: dict | None = None, level: str | None = None,
                writable: bool | None = None) -> str:
    """MCP 端点：JSON 配置里的值优先（前端可改），否则用环境变量默认。

    ``level``（2026-10-26）：**数据视野**档位。给定非 owner 档时把路径改成
    ``<base>/<level>``（``/mcp`` → ``/mcp/reader``）。这是「令牌权限」真正落地
    的地方 —— 同一台上游、同一份 vault，不同视野打不同端点，由 MCP 侧的
    ClearanceRouter 决定这条连接能看见哪些密级的条目。

    ``writable``（2026-10-26）：读写模式，与视野**正交**。``False`` 时给路径加
    ``-ro`` 后缀（``/mcp/owner-ro``）—— 这样「全库可读、一字不许改」在传输层
    就成了硬边界，而不是靠调用方自觉不动写工具。

    两个刻意的细节：

    1. **只读必须显式落到 -ro**，绝不回落到无后缀的 base。反之则会「静默丢掉
       只读意图」，而那正是最难发现的一类权限漏洞。
    2. ``writable is None``（调用方没给）按可写处理，与改造前行为一致；只有明确
       传 ``False`` 才降级。用 ``if not writable`` 会把 ``None`` 当成只读，
       存量调用点全部变成只读 —— 这类「默认值写反」是权限逻辑里最常见的翻车点。

    为什么不在这里做过滤：密级判定的事实源在 MCP 侧（security/clearance 两个
    frontmatter 字段 + 各工具内部的 _can_read）。控制台如果自己再过滤一遍，
    就变成两套口径，迟早对不上 —— 而这类不一致只会往「多看到」的方向错。
    """
    cfg = cfg or config()
    app_cfg = load_app_config()
    base = app_cfg.get("mcp_endpoint") or cfg["mcp"]
    lvl = level or "owner"
    want_ro = writable is False
    if lvl == "owner":
        # owner 的可写形态就是 base 本身（服务端不为 owner 开别名）
        return (base.rstrip("/") + "/owner-ro") if want_ro else base
    if want_ro and lvl not in _READONLY_LEVELS:
        return base.rstrip("/") + "/" + lvl + "-ro"
    return base.rstrip("/") + "/" + lvl


def resolve_vault() -> Path | None:
    """vault 位置：环境变量 AI_MEMORY_DIR > JSON 配置 vault_dir > 无。"""
    raw = _env_str("AI_MEMORY_DIR")
    if raw:
        return Path(raw).expanduser()
    v = load_app_config().get("vault_dir") or ""
    return Path(v).expanduser() if v else None


# ---------------------------------------------------------------------------
# 配置面：运行时阈值（vault 根的 memory.toml）
#
# 2026-10-16 起**全部经 MCP 工具 memory_config**：本模块不再 import memory_config、
# 不再自己解析/渲染/写盘。那三件事的唯一实现在核心仓 memory_config.py（server.py 的
# memory_config 工具走的也是它），故两侧不存在"对不上"的可能。
# 本模块只剩两件属于自己的事：① 转成前端契约的 JSON；② 施加本台的只读开关。
# ---------------------------------------------------------------------------
async def _mcp_json(cfg: dict, tool: str, arguments: dict) -> dict:
    """调一个 MCP 工具，把它返回的 JSON 文本解析成 dict。

    ``clip=False``：给**服务端自己**消费的包不能被 ``_THUMB`` 截断 —— 截断后的
    JSON 必然解析失败，而那会伪装成「上游返回格式不对」，把排查引向错误方向。

    上游工具沿本仓约定用「``错误：…``」**文本**表达业务错误（不使用 isError），
    故两种形态都要识别，并把消息**原样**上抛给调用方转 400。
    """
    endpoint = resolve_mcp(cfg)
    results = await mcp_session_calls(endpoint, [(tool, arguments)], clip=False)
    res = results[0]
    text = str(res.get("text") or "")
    if res.get("isError"):
        raise WebConfigError(text.strip() or "上游 MCP 返回错误。")
    try:
        payload = json.loads(text)
    except ValueError:
        if text.strip().startswith("错误"):
            raise WebConfigError(text.strip()) from None
        raise WebConfigError(f"{tool} 返回的不是合法 JSON：{text[:120]!r}") from None
    if not isinstance(payload, dict):
        raise WebConfigError(f"{tool} 返回的不是 JSON 对象。")
    return payload


async def thresholds_state(cfg: dict | None = None) -> dict:
    """当前生效值 + 每键来源 + 可否写入（数据源 = MCP 工具 ``memory_config``）。"""
    cfg = cfg or config()
    st = await _mcp_json(cfg, "memory_config",
                         {"action": "get", "output_format": "json"})
    # writable 是**两侧的与**：服务端要认得 vault（定位得到 memory.toml），本台要
    # 没被 AI_MEMORY_WEB_CONFIG_WRITE=0 关掉。少任何一半，界面都不该显示可编辑。
    st["writable"] = bool(cfg["config_write"] and st.get("config_path"))
    return st


async def write_thresholds(values: dict, cfg: dict | None = None) -> dict:
    """整状态写阈值（键集校验 / 备份 / 原子替换都在服务端），返回写入后的快照。"""
    cfg = cfg or config()
    if not cfg["config_write"]:
        raise WebConfigError("阈值写入已被 AI_MEMORY_WEB_CONFIG_WRITE=0 关闭（只读模式）。")
    if not isinstance(values, dict):
        raise WebConfigError("需要 {'values': {键: 值}}。")
    st = await _mcp_json(cfg, "memory_config",
                         {"action": "set", "values": values, "output_format": "json"})
    st["writable"] = bool(cfg["config_write"] and st.get("config_path"))
    return st


# ---------------------------------------------------------------------------
# MCP 客户端（后端代理）
# ---------------------------------------------------------------------------
def _serialize_result(res: Any) -> dict:
    content: list[dict] = []
    for item in (getattr(res, "content", None) or []):
        if hasattr(item, "model_dump"):
            content.append({k: v for k, v in item.model_dump().items() if v is not None})
        elif isinstance(item, dict):
            content.append(item)
        else:
            content.append({"type": "unknown", "text": str(item)})
    text = "\n".join(str(c.get("text", "")) for c in content
                     if isinstance(c.get("text"), str))
    structured = getattr(res, "structuredContent", None)
    return {
        "isError": bool(getattr(res, "isError", False)),
        "content": content,
        "text": text,
        "structured": structured,
        "chars": len(text),
    }


def _clip(res: dict) -> dict:
    """给浏览器的文本封顶（MCP 端单项可达数万字符，不宜整包回传）。"""
    if len(res.get("text", "")) > _THUMB:
        res = dict(res)
        res["text"] = res["text"][:_THUMB] + f"\n…（已截断，原文 {res['chars']} 字符）"
        res["truncated"] = True
    return res


def _bounded_int(raw: Any, default: int, lo: int, hi: int) -> int:
    """查询串里的整数参数：解析失败回落默认值，并夹在 [lo, hi] 内。"""
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _local_stamp(iso: Any) -> tuple[str, str]:
    """ISO 时间戳 → **本机时区**下的 ``("YYYY-MM-DD", "HH:MM")``。

    ``memory_recent`` 给的是 ``2026-10-15T08:31:07+00:00``。直接切前 10 位会在
    UTC+8 下把「本地凌晨写的」整条挪到前一天 —— 日历格子与用户挂钟就会差一整天。
    换算只在这里做一次（前端不再做日期数学），双份口径的隐患随之消失。
    解析失败返回空串，调用方跳过该条（**不猜**）。
    """
    try:
        dt = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return "", ""
    dt = dt.astimezone()          # 无 tz 的裸时间按本机时区解释
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


async def mcp_session_calls(endpoint: str, calls: list[tuple[str, dict]],
                            timeout: float = MCP_TIMEOUT,
                            clip: bool = True) -> list[dict]:
    """一次会话里顺序执行多次工具调用（省掉 N 次握手）。

    后端→MCP 是服务端到服务端调用，**不带 Origin 头** ⇒ 不受 allowed_origins 限制。

    ``clip=False`` 取消 ``_THUMB`` 文本封顶 —— 只给**服务端自己消费**的调用用
    （如 ``/api/activity`` 要在后端解析 memory_recent 的整包 JSON）。
    给浏览器的调用**必须**保持默认 ``clip=True``，否则大包会整坨回传到前端。
    """
    out: list[dict] = []
    with anyio.fail_after(timeout):
        async with streamablehttp_client(endpoint) as (read, write, _cb):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for tool, arguments in calls:
                    res = await session.call_tool(tool, arguments or {})
                    item = _serialize_result(res)
                    out.append(_clip(item) if clip else item)
    return out


def _mcp_error_text(exc: BaseException) -> str:
    """把 anyio / httpx 的嵌套异常压成**一句能照着做**的话。

    🔴 ``streamablehttp_client`` 抛的通常就是
    ``ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)`` ——
    真正的原因（连接被拒、421 Invalid Host header、超时…）全藏在子异常里，
    直接 ``str(e)`` 只会让界面显示这句废话，用户无从下手。
    这里逐层下钻到叶子异常；对容器场景最常见的 421 额外补一句怎么放行。
    """
    chain: list[str] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        chain.append(f"{type(cur).__name__}: {cur}")
        subs = getattr(cur, "exceptions", None) or ()
        nxt = subs[0] if subs else None
        if nxt is None:
            nxt = cur.__cause__ or cur.__context__
        cur = nxt
    text = chain[-1]
    if len(chain) > 1 and type(exc).__name__ not in text:
        text = f"{type(exc).__name__} → {text}"
    low = " ".join(chain).lower()
    if "421" in low or "invalid host" in low:
        text += ("（上游 MCP 的 DNS rebinding 防护拒了这个 Host。把它的 host:port 写进"
                 " MCP 侧的 AI_MEMORY_HTTP_ALLOWED_HOSTS —— 该变量是**替换**默认值，"
                 "记得同时带上 127.0.0.1:* 与 localhost:*）")
    return text


def _content_text(res: dict) -> str:
    """把 MCP 工具结果里的 text 片段拼成一整段（浏览器/纯文本模式用）。

    MCP 的 ``content`` 是**片段数组**（可能同时有 text / image / resource），
    这里只取 text —— 图片走 URL 没有意义，混进来只会让地址栏返回一坨 base64。
    """
    parts = []
    for item in (res.get("content") or []):
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(parts)


async def mcp_health(endpoint: str, timeout: float = MCP_HEALTH_TIMEOUT) -> dict:
    """连通性探针：握手 + 工具清单。失败返回 ``ok=False`` 而不是抛错。"""
    t0 = time.perf_counter()
    try:
        with anyio.fail_after(timeout):
            async with streamablehttp_client(endpoint) as (read, write, _cb):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    tools = await session.list_tools()
        info = getattr(init, "serverInfo", None)
        return {
            "ok": True,
            "endpoint": endpoint,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "server": {
                "name": getattr(info, "name", None),
                "version": getattr(info, "version", None),
            },
            "protocol": getattr(init, "protocolVersion", None),
            "tools_count": len(getattr(tools, "tools", []) or []),
            "error": None,
        }
    except Exception as e:                                        # noqa: BLE001
        return {
            "ok": False,
            "endpoint": endpoint,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "server": None,
            "protocol": None,
            "tools_count": 0,
            "error": _mcp_error_text(e),
        }


# ---------------------------------------------------------------------------
# 工具功能分组（2026-10-15）
#
# 🔴 为什么必须显式声明、且必须声明在服务端：
#   · MCP 的 `ToolAnnotations` 只有四个标准字段（readOnlyHint / destructiveHint /
#     idempotentHint / openWorldHint），描述的是**操作危险等级**、不是**功能用途**。
#     按危险等级分组时「只读」一组吃到 24 个里的 14 个（58%），而「非幂等」只有 2 个
#     （最大:最小 = 7:1）—— 分组这一层几乎不产生收益；且用户找工具的心智是
#     「我要干什么」而不是「这操作危不危险」。
#   · 归属无法从注解自动派生（需要人的判断），所以必须显式声明。
#   · **不能放前端**：`tests/test_web.py` 有断言钉住控制台进程 `sys.modules` 里没有
#     `server`，`/api/tools` 是走 MCP 协议取的清单 ⇒ 前端拿不到工具定义处的上下文；
#     把表放前端就会变成「随工具数增长而失配的第二事实源」。
#   · 「不重、不漏、无陈旧键」由 `tests/test_web.py` 的守卫断言钉死。
#
# 注意：本表**不是**危险等级的替代 —— 危险等级仍由 `ToolAnnotations` 派生，
# 在前端降级为工具行内的小徽章与顶部筛选条（见 `web/js/features/console.js`）。
# ---------------------------------------------------------------------------
TOOL_GROUPS = [
    {"key": "content", "label": "内容读写", "desc": "取用与落盘单条记忆"},
    {"key": "search", "label": "检索", "desc": "按关键词、相似度或时间找条目"},
    {"key": "graph", "label": "图谱结构", "desc": "双向链接拓扑与孤立条目"},
    {"key": "health", "label": "体检诊断", "desc": "全库体检、对账与统计"},
    {"key": "maintain", "label": "库维护", "desc": "索引重建、批量标签与热度调整"},
    {"key": "lifecycle", "label": "生命周期与系统", "desc": "归档、恢复、删除与热重启"},
]
# 兜底组：新增工具若忘记登记，会落到这里并在左栏显式出现 —— 静默失配比报错更难发现。
TOOL_GROUP_OTHER = {"key": "other", "label": "未归类", "desc": "尚未登记分组的新工具"}

_TOOL_GROUP_OF = {
    # 内容读写
    "memory_read": "content",
    "memory_write": "content",
    "memory_update_metadata": "content",
    # 2026-10-25：memory_commit 是 core 侧后加的统一写入口（带当日时间线与项目
    # 状态同步），此前的分组表没跟上 ⇒ 它会落进「未归类」兜底组。补登为内容读写。
    "memory_commit": "content",
    # 检索
    "memory_search": "search",
    "memory_smart_search": "search",
    "memory_list": "search",
    "memory_recent": "search",
    "memory_context": "search",
    # 图谱结构
    "memory_graph": "graph",
    "memory_orphans": "graph",
    # 体检诊断
    "memory_audit": "health",
    "memory_doctor": "health",
    "memory_schema_diff": "health",
    "memory_stats": "health",
    # 库维护
    "memory_index_draft": "maintain",
    "memory_rebuild_links": "maintain",
    "memory_heat_suggest": "maintain",
    "memory_batch_tier": "maintain",
    "memory_batch_tag": "maintain",
    # 2026-10-16：运行时阈值（memory.toml）纳入 MCP。归「库维护」而非「体检诊断」
    # —— 它写盘、改变全库行为（去重阈值/热度阈值/正文预算），不是只读的报告工具；
    # 与 memory_heat_suggest 同类（都是"默认只报、可显式落盘"的调参口）。
    "memory_config": "maintain",
    # 生命周期与系统
    "memory_archive": "lifecycle",
    "memory_archive_old": "lifecycle",
    "memory_restore": "lifecycle",
    "memory_delete": "lifecycle",
    "memory_restart": "lifecycle",
}

#: 会**改动库或机器行为**的工具（2026-10-26，配合令牌的只读模式）。
#:
#: 为什么需要这张表而不是按 ``TOOL_GROUPS`` 的组来判：``content`` 组里既有
#: ``memory_read``（读）也有 ``memory_write``（写），按组判会把读工具一起封掉。
#: 组是给界面分栏用的，写权边界必须逐工具声明。
#:
#: 这是**友好报错层**，不是硬边界 —— 硬边界在 MCP 侧（``/mcp/<档位>-ro`` 端点
#: 上的 ``_owner_gate`` / ``_readonly_endpoint``）。这里提前拦一下，是为了让
#: 只读令牌拿到「该端点为只读」而不是等上游返回之后的半截错误；即便有人绕过
#: 这一层直接打 MCP 端点，也改不动东西。
#: 新增写工具时若忘记登记，最坏结果是「多绕一次上游拒绝」，不会变成放行。
WRITE_TOOLS = frozenset({
    "memory_write", "memory_commit", "memory_update_metadata",
    "memory_delete", "memory_archive", "memory_restore", "memory_archive_old",
    "memory_batch_tag", "memory_batch_tier", "memory_heat_suggest",
    "memory_config", "memory_restart",
})

#: GET（URL 传参）方式允许调用的工具（2026-10-27，主人要求「地址栏传参查库」）。
#:
#: 为什么是**白名单**而不是「WRITE_TOOLS 的补集」：黑名单只挡住现在已知的写工具，
#: 将来 core 新增一个会落盘的工具就自动放行。白名单下漏登记的后果是「查不到」，
#: 不是「能写库」—— 两种失败方向的安全性差一个量级。
#:
#: 准入只有两条：**不改库、不改机器行为**。因此 ``WRITE_TOOLS`` 全体出局，
#: ``memory_index_draft`` / ``memory_rebuild_links`` 虽未列入 ``WRITE_TOOLS``
#: （它们不动记忆正文），但会落盘索引与链接，同样出局。
#: 写操作的正门是 ``POST /mcp`` 与 ``POST /api/call``。
GET_READONLY_TOOLS = frozenset({
    "memory_read", "memory_search", "memory_smart_search", "memory_list",
    "memory_recent", "memory_context", "memory_graph", "memory_orphans",
    "memory_audit", "memory_doctor", "memory_schema_diff", "memory_stats",
})

#: GET 调用的查询串里**不算**业务参数的键（其余键按字符串参数收集）。
GET_CALL_RESERVED = frozenset({"token", "tool", "args", "format"})

#: ``args`` 走 URL，长度必须收口 —— 一条浏览器地址栏装不下更多，也不该装。
GET_CALL_ARGS_MAX = 4096


async def mcp_tools(endpoint: str, timeout: float = MCP_TIMEOUT) -> list[dict]:
    with anyio.fail_after(timeout):
        async with streamablehttp_client(endpoint) as (read, write, _cb):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.list_tools()
    out = []
    ungrouped = []
    for t in (getattr(res, "tools", None) or []):
        ann = getattr(t, "annotations", None)
        name = getattr(t, "name", "")
        group = _TOOL_GROUP_OF.get(name)
        if group is None:
            group = TOOL_GROUP_OTHER["key"]
            ungrouped.append(name)
        out.append({
            "name": name,
            "title": getattr(t, "title", None),
            "description": getattr(t, "description", "") or "",
            "inputSchema": getattr(t, "inputSchema", None) or {"type": "object"},
            "annotations": (ann.model_dump() if hasattr(ann, "model_dump")
                            else (ann if isinstance(ann, dict) else None)),
            "group": group,
        })
    out.sort(key=lambda x: x["name"])
    if ungrouped:
        logger.warning("工具未登记功能分组，已归入 %r：%s",
                       TOOL_GROUP_OTHER["key"], ", ".join(ungrouped))
    return out


# ---------------------------------------------------------------------------
# 更新面：从 git 远端拉取「仅程序」白名单（2026-10-15）
#
# 为什么不用 `git pull`
#   程序目录**同时就是 git 工作副本**。`pull` 会做合并、可能移动 HEAD，并与
#   本地未提交改动冲突 —— 对「工作副本即运行目录」的部署形态不可接受。
#
# 为什么不用 `git checkout <ref> -- <path>`
#   它虽然只动指定路径，但**会改写 index**（被覆盖的文件变成 staged），对仓库
#   状态产生额外副作用。改用 `git restore --source=<ref> --worktree`：只写工作区，
#   不碰 HEAD、不碰 index。
#
# 为什么必须让 git 自己写文件
#   本机 `core.autocrlf=true`，而 `.gitattributes` 只对 py/json/toml/sh/txt/yml
#   锁了 LF，`.js` / `.css` / `.html` 不在其列 ⇒ 前端文件在工作区是 CRLF。
#   任何「读 git 对象、再自己写盘」的实现都会把整个 web/ 的行尾改错。
#
# 范围（「仅程序」）
#   后端运行时模块 + `web/` 静态资源。vault 数据在程序目录之外（D:\ai记忆），
#   `*.md` / `*.db` 天然不参与；`.ai-memory-backup/` 亦在白名单之外。
#
# 诚实原则
#   白名单内的文件若**未被版本控制**，远端永远不会有它们 —— 这时界面必须显式
#   报「N 个文件不在版本库」，而不是显示「已是最新」。本机在 2026-10-15 之前
#   前端与控制台后端正处于这个状态（内存记录「评估_记忆库GitHub分发更新可行性」）。
# ---------------------------------------------------------------------------
# 本仓只含 Web 侧代码 ⇒ **web 目标**的白名单 = 本仓全部程序文件。
# 2026-10-16：`core_path.py` 随「Web 不再 import 核心模块」一并删除，白名单同步收敛。
UPDATE_BACKEND_FILES = (
    "web_console.py",
    "serve_web.py",
    "web_auth.py",
)
UPDATE_FRONTEND_DIR = "web"
UPDATE_WEB_PATHS = UPDATE_BACKEND_FILES + (UPDATE_FRONTEND_DIR,)

# 🔴 2026-10-16（晚）：更新面扩为**双目标** —— 核心（MCP）与 Web 分属两个仓、
# 两个目录（`dpkg-s/ai-memory-template` vs `dpkg-s/ai-memory-web`），各有独立
# 远端与独立白名单，**不能共用** `update_root()`。
#
# 核心白名单口径与 Web 侧一致：只含「程序」—— 运行时模块 + 依赖声明。
# 刻意**不含**安装器（ai_memory_setup.py / install.*）、CI、Dockerfile、文档与
# `template/` 数据页：它们不是运行面，混进来会把「更新」变成一次全仓覆盖。
CORE_PROGRAM_FILES = (
    "server.py",
    "serve_http.py",
    "transport_http.py",
    "memory_config.py",
    "memory_index.py",
    "metrics.py",
    "locks.py",
    "text_utils.py",
    "yaml_io.py",
    "requirements.txt",
    "requirements-dev.txt",
    "ruff.toml",
)
#: 核心仓的识别标记 —— 两个文件同时存在才算「像核心仓」，避免把碰巧同名的
#: 目录当成核心，从而对错误的仓执行 restore。
CORE_ROOT_MARKERS = ("serve_http.py", "server.py")
CORE_ROOT_ENV = "AI_MEMORY_CORE_DIR"

#: 目标登记表：key → (显示名, 白名单)。顺序即界面顺序。
UPDATE_TARGET_KEYS = ("web", "core")
UPDATE_TARGET_NAMES = {"web": "Web 控制台", "core": "核心（MCP）"}

#: 兼容旧引用（既有调用点与测试 H1/H2）：裸名 = web 目标。
UPDATE_PATHS = UPDATE_WEB_PATHS

UPDATE_TIMEOUT = 90.0                       # 单条 git 命令超时（秒）
UPDATE_BACKUP_DIR = ".ai-memory-backup"
UPDATE_META_NAME = ".ai-memory-install.json"
UPDATE_LOG_DIR = Path.home() / ".ai-memory-web" / "logs"
RESTARTER_ENV = "AI_MEMORY_RESTARTER"       # 覆盖重启助手路径
RESTARTER_NAME = "ai_memory_web.py"         # 桌面 launcher 的默认文件名

# 重启时序（理由见 update_restart 的文档串）：
#   助手先睡 WEB_RESTART_DELAY 秒，再执行 launcher 的 restart；
#   控制台在把 HTTP 响应写回浏览器后，WEB_RESTART_EXIT_DELAY 秒自杀。
# 两者的先后关系是这个功能安全性的**全部依据**，不能互换。
WEB_RESTART_DELAY = 3.0
WEB_RESTART_EXIT_DELAY = 0.4

_UPDATE_LOCK = threading.Lock()
_VERSION_HEAD_RE = re.compile(r"^##\s*\[(\d+\.\d+(?:\.\d+)?)\]", re.MULTILINE)


def update_root() -> Path:
    """被更新的程序目录 —— 本文件所在目录。"""
    return Path(__file__).resolve().parent


def restarter_path() -> str:
    """重启助手（桌面 launcher）的路径；找不到返回空串。

    找不到时调用方必须**拒绝**重启 —— 绝不能「先自杀、再发现没人接手」。

    显式设了 ``AI_MEMORY_RESTARTER`` 却指向不存在的文件时**返回空串**，不回落
    桌面：配置写错要立刻暴露，不能被静默兜底掩盖（这也会让「无法重启」变得不可复现）。
    """
    raw = _env_str(RESTARTER_ENV)
    if raw:
        return raw if Path(raw).is_file() else ""
    cand = Path.home() / "Desktop" / RESTARTER_NAME
    return str(cand) if cand.is_file() else ""


def _ok_core_root(p: Path) -> bool:
    try:
        return all((p / m).is_file() for m in CORE_ROOT_MARKERS)
    except OSError:
        return False


def core_root() -> tuple[Path | None, str]:
    """定位核心（MCP）仓目录，返回 ``(目录, 错误说明)``；成功时错误说明为空串。

    与 `restarter_path()` 同一原则：**显式设了 ``AI_MEMORY_CORE_DIR`` 却无效时
    绝不静默回落** —— 否则「更新了错误的目录」这类事故会变得不可复现。

    候选顺序：
      1. 环境变量 ``AI_MEMORY_CORE_DIR``（桌面 launcher 起 Web 进程时注入）
      2. 本文件所在目录的**父目录** —— submodule 布局下即核心仓根
      3. ``~/.workbuddy/mcp-servers/ai-memory``
    """
    markers = " / ".join(CORE_ROOT_MARKERS)
    explicit = (os.environ.get(CORE_ROOT_ENV) or "").strip()
    if explicit:
        p = Path(explicit)
        if _ok_core_root(p):
            return p, ""
        return None, (f"{CORE_ROOT_ENV} 指向的目录不像核心仓（缺 {markers}）：{explicit}")

    for cand in (update_root().parent,
                 Path.home() / ".workbuddy" / "mcp-servers" / "ai-memory"):
        if _ok_core_root(cand):
            return cand, ""
    return None, (f"未找到核心仓目录（需同时含 {markers}）。"
                  f"可设环境变量 {CORE_ROOT_ENV} 显式指定。")


def update_target(key: str) -> tuple[Path | None, tuple[str, ...], str]:
    """``key`` → ``(目录, 白名单, 错误说明)``。未知 key 返回空目录 + 错误。"""
    if key == "web":
        return update_root(), UPDATE_WEB_PATHS, ""
    if key == "core":
        root, err = core_root()
        return root, CORE_PROGRAM_FILES, err
    return None, (), f"未知更新目标：{key}"


# 🔴 2026-10-21：容器部署下的两条报错（「程序目录不是 git 仓库：/app」/
# 「未找到核心仓目录」）不是故障，而是**设计上的不可用** —— 镜像里的 /app 是
# `COPY` 出来的构建产物，没有 `.git`，python:slim 基座里也没有 git 二进制；
# 而 `core_root()` 的候选目录刻意不含 `/app` 自身（见该函数注释）。
#
# 在容器里做 `git restore` 有两重危害：① 必然失败并留下半截状态；
# ② 即使失败也会先尝试 `git fetch`（联网 + 阻塞事件循环几十秒）。
# 所以这里把「容器」这个事实显式建模成一个**独立的不可用原因**，
# 让界面显示「部署形态不支持」，而不是含糊的「找不到 / 不是仓库」——
# 后者会让人以为配错了路径，从而反复折腾一个本来就不该存在的目录。
CONTAINER_UPDATE_MSG = (
    "容器部署不支持在线更新：镜像内的 /app 是构建产物（无 .git，基座镜像也没有 git 二进制），"
    "且 core_root() 的候选目录刻意不含 /app。"
    "请在构建机完成更新：重新构建镜像 → 传输 → docker load → 重建容器。"
)
#: 部署形态开关：``container`` / ``docker`` / ``podman`` 强制判为容器，
#: ``host`` 强制判为裸机（用于把镜像当裸机环境跑的罕见场景）。
DEPLOY_MODE_ENV = "AI_MEMORY_DEPLOY_MODE"


def _in_container() -> bool:
    """是否运行在容器里。显式环境变量优先，其次看两个公认的运行时痕迹。"""
    flag = (os.environ.get(DEPLOY_MODE_ENV) or "").strip().lower()
    if flag:
        return flag in ("container", "docker", "podman")
    if Path("/.dockerenv").exists():
        return True
    try:
        text = Path("/proc/1/cgroup").read_text(errors="ignore")
    except OSError:
        return False
    return any(t in text for t in ("docker", "kubepods", "containerd"))


def update_unsupported() -> str:
    """当前部署形态是否从根上不支持在线更新；是则返回原因，否则返回空串。"""
    return CONTAINER_UPDATE_MSG if _in_container() else ""


def _git(args: list[str], cwd: Path, timeout: float = UPDATE_TIMEOUT) -> tuple[int, str]:
    """执行一次 git 子命令，返回 ``(返回码, 合并后的输出)``。

    **永不抛异常**：git 缺失、超时、无法启动都收敛成非零返回码，并把真实原因
    放进输出 —— 调用方据此原样回传浏览器，不吞错。
    """
    exe = shutil.which("git")
    if not exe:
        return 127, "PATH 里找不到 git 可执行文件。"
    env = dict(os.environ)
    # 绝不进入交互：无人值守场景下挂在密码 / 主机密钥提示上就是永久卡死。
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    env.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes")
    try:
        proc = subprocess.run(
            [exe, *args], cwd=str(cwd), capture_output=True, timeout=timeout,
            env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return 124, f"git {' '.join(args)} 超时（超过 {timeout:g} 秒）。"
    except OSError as e:                                        # noqa: BLE001
        return 126, f"无法启动 git：{type(e).__name__}: {e}"
    # ⚠️ 只裁行尾，**绝不能 strip 整包**：`status --porcelain` 的每行是
    # `XY 路径`，首行的行首空格是有意义的状态位（` M` = 工作区已改）。
    # 整包 strip 会把首行变成 `M 路径`，随后按固定宽度取路径就少一个字符
    # —— 实测把 `memory_config.py` 读成 `emory_config.py`。
    out = (proc.stdout or b"").decode("utf-8", "replace").rstrip("\r\n")
    err = (proc.stderr or b"").decode("utf-8", "replace").rstrip("\r\n")
    return proc.returncode, "\n".join(x for x in (out, err) if x)


def _version_from_changelog(root: Path, ref: str | None = None) -> str:
    """版本号只认 CHANGELOG 首个小节。

    程序本身不自报版本（无 ``__version__`` / ``VERSION`` 文件），所以「有没有
    新版」只能靠提交号 + CHANGELOG 版本段两路呈现，而不是读一个常量。
    """
    text = ""
    if ref:
        rc, out = _git(["show", f"{ref}:CHANGELOG.md"], root, timeout=30)
        text = out if rc == 0 else ""
    else:
        path = root / "CHANGELOG.md"
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
    m = _VERSION_HEAD_RE.search(text)
    return m.group(1) if m else ""


def _whitelist_tracking(root: Path,
                        paths: tuple[str, ...] | None = None) -> tuple[list[str], list[str]]:
    """白名单内的 ``(已入库, 未入库)`` 两组路径。

    未入库 = 文件在工作区存在、git 却不认识它们 ⇒ 远端不会有它们。这个事实必须
    显式呈现，否则界面会用「已是最新」掩盖「一半文件根本没被跟踪」。

    ``paths`` 可覆盖白名单 —— 双目标下每个目标各有自己的白名单。
    """
    spec = tuple(paths) if paths else UPDATE_PATHS
    rc, out = _git(["ls-files", "--", *spec], root, timeout=60)
    tracked = sorted({x for x in out.splitlines() if x}) if rc == 0 else []
    rc, out = _git(["ls-files", "--others", "--exclude-standard", "--", *spec],
                   root, timeout=60)
    untracked = sorted({x for x in out.splitlines() if x}) if rc == 0 else []
    return tracked, untracked


def _whitelist_dirty(root: Path, paths: tuple[str, ...] | None = None) -> list[str]:
    """工作区相对 HEAD 有改动的文件（含未跟踪）。``-uall`` 展开目录。

    ``paths`` 可覆盖白名单 —— 测试用它在一个**真仓库**上钉住「行首状态位不被吞」
    这条回归（见 tests/test_web.py 的 H 段）。
    """
    spec = tuple(paths) if paths else UPDATE_PATHS
    rc, out = _git(["status", "--porcelain", "-uall", "--", *spec], root, timeout=60)
    if rc != 0:
        return []
    paths: list[str] = []
    for line in out.splitlines():
        if len(line) < 3:
            continue
        # 固定宽度取路径（2 字符状态位 + 分隔空白），并对行首空白免疫 ——
        # 双保险：即便上游哪天又 strip 了整包，这里也不会错位。
        body = line[2:].lstrip()
        if " -> " in body:                  # 重命名：只记新路径
            body = body.split(" -> ", 1)[1]
        paths.append(body.strip().strip('"'))
    return sorted(set(paths))


def _diff_head_to(root: Path, ref: str,
                  paths: tuple[str, ...] | None = None) -> tuple[list[dict], str]:
    """「远端自共同祖先以来的变更」在白名单内的清单。

    用**三点** `HEAD...ref`（等价于 `merge-base(HEAD, ref)..ref`），而不是
    `HEAD..ref`：后者在「本地领先远端」时会算成「从本地回退到远端」，把本地已
    提交的新文件整批列成待删除。三点只描述远端独有的前进量，正是要应用的部分。

    重命名拆成「删除旧 + 新增新」两条，应用时才有确定的动作。

    ``paths`` 可覆盖白名单 —— 测试用它在真仓库上钉住三点语义（H 段）。
    """
    spec = tuple(paths) if paths else UPDATE_PATHS
    rc, out = _git(["diff", "--name-status", f"HEAD...{ref}", "--", *spec],
                   root, timeout=60)
    if rc != 0:
        return [], out
    items: list[dict] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()
        if status.startswith("R") and len(parts) >= 3:
            items.append({"status": "D", "path": parts[1]})
            items.append({"status": "A", "path": parts[2]})
        else:
            items.append({"status": status[:1], "path": parts[-1]})
    items.sort(key=lambda x: x["path"])
    return items, ""


def update_status(root: Path | None = None,
                  paths: tuple[str, ...] | None = None,
                  key: str = "web") -> dict:
    """**单个目标**的仓库基本面（纯本地，不联网）。

    ``root`` / ``paths`` 省略时退回 web 目标，保持既有调用点与测试可用。
    """
    spec = tuple(paths) if paths else UPDATE_PATHS
    root = root or update_root()
    info: dict = {
        "target": key,
        "target_name": UPDATE_TARGET_NAMES.get(key, key),
        "root": str(root),
        "is_repo": False,
        "branch": "",
        "remote_url": "",
        "local_sha": "",
        "local_short": "",
        "version": "",
        "tracked": [],
        "untracked": [],
        "dirty": [],
        "restarter": restarter_path(),
        "backup_dir": str(root / UPDATE_BACKUP_DIR),
        "whitelist": list(spec),
    }
    rc, _ = _git(["rev-parse", "--is-inside-work-tree"], root, timeout=20)
    if rc != 0:
        return info
    info["is_repo"] = True
    # 单值输出在这里必须自己 strip（_git 已不再整包 strip）。
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root, timeout=20)[1].strip()
    info["branch"] = "" if branch in ("HEAD", "origin/HEAD") else branch
    info["local_sha"] = _git(["rev-parse", "HEAD"], root, timeout=20)[1].strip()
    info["local_short"] = info["local_sha"][:7]
    rc_url, url = _git(["remote", "get-url", "origin"], root, timeout=20)
    info["remote_url"] = url.strip() if rc_url == 0 else ""
    info["version"] = _version_from_changelog(root)
    info["tracked"], info["untracked"] = _whitelist_tracking(root, spec)
    info["dirty"] = _whitelist_dirty(root, spec)
    return info


def update_check(root: Path | None = None,
                 paths: tuple[str, ...] | None = None,
                 key: str = "web",
                 timeout: float = UPDATE_TIMEOUT) -> dict:
    """联网检查：``git fetch`` → 比对白名单 → 给出可执行性判断。**只读不写盘**。"""
    spec = tuple(paths) if paths else UPDATE_PATHS
    root = root or update_root()
    unsup = update_unsupported()
    if unsup:
        # 容器里连 status 都不必算：不管 git 在不在，结论都是「不可更新」。
        return {"target": key, "root": str(root), "available": False,
                "unsupported": True, "is_repo": False, "checked": True,
                "ok": False, "fetched": False, "error": unsup,
                "whitelist": list(spec), "tracked": [], "untracked": [], "dirty": []}
    state = update_status(root, spec, key)
    if not state["is_repo"]:
        return {**state, "ok": False, "fetched": False,
                "error": f"程序目录不是 git 仓库：{state['root']}"}
    if not state["branch"]:
        return {**state, "ok": False, "fetched": False,
                "error": "当前处于游离 HEAD，无法确定要跟随的分支。"}

    ref = f"origin/{state['branch']}"
    rc, out = _git(["fetch", "--prune", "origin", state["branch"]], root, timeout=timeout)
    if rc != 0:
        return {**state, "ok": False, "fetched": False, "ref": ref,
                "error": "从远端拉取失败（下面是 git 的原话，未经改写）。",
                "stderr": out}

    remote_sha = _git(["rev-parse", ref], root, timeout=20)[1].strip()
    changed, diff_err = _diff_head_to(root, ref, spec)
    _, counts = _git(["rev-list", "--left-right", "--count", f"HEAD...{ref}"],
                     root, timeout=30)
    ahead = behind = 0
    parts = counts.split()
    if len(parts) == 2:
        try:
            ahead, behind = int(parts[0]), int(parts[1])
        except ValueError:
            ahead = behind = 0

    untracked = state["untracked"]
    conflicts = sorted(set(state["dirty"]) & {c["path"] for c in changed})
    if untracked:
        blocked = (f"白名单内仍有 {len(untracked)} 个文件未纳入版本控制，"
                   "远端不会有它们 —— 这些文件不会被更新。")
    elif ahead > 0 and behind > 0:
        blocked = (f"本地有 {ahead} 个未推送的提交、远端也有 {behind} 个新提交"
                   "⇒ 两侧已分叉。覆盖会丢掉本地提交，请先处理本地提交。")
    elif conflicts:
        blocked = (f"白名单内有 {len(conflicts)} 个文件存在未提交改动，"
                   "覆盖会丢弃这些改动。")
    elif behind == 0:
        blocked = "已是最新。"
    else:
        blocked = None

    return {
        **state,
        "ok": True,
        "fetched": True,
        "ref": ref,
        "remote_sha": remote_sha,
        "remote_short": remote_sha[:7],
        "remote_version": _version_from_changelog(root, ref),
        "ahead": ahead,
        "behind": behind,
        "changed": changed,
        "changed_count": len(changed),
        "conflicts": conflicts,
        "diff_error": diff_err,
        "up_to_date": behind == 0,
        "can_apply": bool(behind > 0 and not conflicts and not untracked),
        "blocked_reason": blocked,
    }


def update_apply(root: Path | None = None,
                 paths: tuple[str, ...] | None = None,
                 key: str = "web",
                 force: bool = False, ref: str = "",
                 expected_sha: str = "", timeout: float = UPDATE_TIMEOUT) -> dict:
    """执行**单个目标**的更新：备份 → 按白名单 restore → 记录元数据（进程内互斥）。"""
    spec = tuple(paths) if paths else UPDATE_PATHS
    root = root or update_root()
    unsup = update_unsupported()
    if unsup:
        return {"ok": False, "unsupported": True, "target": key, "error": unsup}
    if not _UPDATE_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "已有一次更新正在执行，请稍后再试。"}
    try:
        return _update_apply_locked(root, spec, key, force, ref, expected_sha, timeout)
    finally:
        _UPDATE_LOCK.release()


def _update_apply_locked(root: Path, spec: tuple[str, ...], key: str,
                         force: bool, ref: str,
                         expected_sha: str, timeout: float) -> dict:
    state = update_status(root, spec, key)
    if not state["is_repo"]:
        return {"ok": False, "error": f"程序目录不是 git 仓库：{state['root']}"}

    target = ref or (f"origin/{state['branch']}" if state["branch"] else "")
    if not target:
        return {"ok": False, "error": "无法确定要跟进的远端分支。"}

    # TOCTOU：检查与执行之间远端可能又前进了。提交号对不上就要求重新检查。
    cur_sha = _git(["rev-parse", target], root, timeout=20)[1].strip()
    if expected_sha and cur_sha and cur_sha != expected_sha:
        return {"ok": False, "remote_sha": cur_sha, "error": (
            f"远端提交已变化（检查时 {expected_sha[:7]}，现在 {cur_sha[:7]}），"
            "请重新检查更新。")}

    changed, diff_err = _diff_head_to(root, target, spec)
    if diff_err:
        return {"ok": False, "target": key, "error": "无法计算差异。", "stderr": diff_err}
    if not changed:
        return {"ok": True, "up_to_date": True, "target": key,
                "target_name": UPDATE_TARGET_NAMES.get(key, key),
                "ref": target, "written": [],
                "removed": [], "backed_up": [], "backup": None,
                "message": "已是最新，未改动任何文件。"}

    conflicts = sorted(set(state["dirty"]) & {c["path"] for c in changed})
    if conflicts and not force:
        return {"ok": False, "conflicts": conflicts, "error": (
            f"白名单内有 {len(conflicts)} 个文件存在未提交改动，覆盖会丢弃它们。"
            "确认覆盖请以 force=true 重试（覆盖前会先备份）。")}

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = root / UPDATE_BACKUP_DIR / stamp

    written: list[str] = []
    removed: list[str] = []
    backed_up: list[str] = []
    for item in changed:
        rel, status = item["path"], item["status"]
        cur = root / rel
        if cur.is_file():                   # 覆盖前一律原样备份
            dst = backup_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(cur), str(dst))
            backed_up.append(rel)
        if status == "D":
            if cur.exists():
                cur.unlink()
                removed.append(rel)
        else:
            written.append(rel)

    restore_failed = ""
    if written:
        rc, out = _git(["restore", f"--source={target}", "--worktree", "--", *written],
                       root, timeout=timeout)
        if rc != 0:
            restore_failed = out

    meta_file = root / UPDATE_META_NAME
    meta: Any = {}
    if meta_file.is_file():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            meta = {}
    if isinstance(meta, dict):
        # 双目标后按目标分键。`last_web_update` 是 2026-10-16 之前的旧键，
        # web 目标继续写一份，避免既有读取方（若有）突然读空。
        entry = {
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "ref": target,
            "expected_sha": expected_sha,
            "written": len(written),
            "removed": len(removed),
            "backup": str(backup_root) if backed_up else "",
        }
        meta[f"last_update_{key}"] = entry
        if key == "web":
            meta["last_web_update"] = entry
        try:
            meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8", newline="\n")
        except OSError as e:
            logger.warning("写更新元数据失败：%s", e)

    result = {
        "ok": not restore_failed,
        "up_to_date": False,
        "target": key,
        "target_name": UPDATE_TARGET_NAMES.get(key, key),
        "ref": target,
        "remote_sha": expected_sha,
        "remote_short": expected_sha[:7],
        "written": written,
        "removed": removed,
        "backed_up": backed_up,
        "backup": str(backup_root) if backed_up else None,
        "force_overrode": conflicts if (conflicts and force) else [],
        "restart_required": any(p.endswith(".py") for p in written + removed),
        "untracked_left": state["untracked"],
    }
    if restore_failed:
        result["error"] = "git restore 失败，文件可能只更新了一部分。"
        result["stderr"] = restore_failed
    return result


def update_restart() -> dict:
    """拉起重启助手执行「停 → 起」；控制台随后自退。

    时序是这个功能安全性的全部依据，顺序不能换：
      助手若与控制台同处一棵进程树，launcher 的 ``taskkill /T`` 会把它一并带走
      —— 结果是端口停了却没人重启。所以助手的第一个动作是 ``sleep``（等控制台
      先死），控制台则在把 HTTP 响应写回浏览器之后自杀。

    ``sys.executable`` 就是控制台自己的解释器（launcher 已用
    ``serve_web.py --check`` 验证过依赖齐全），不必重新探测。
    """
    helper = restarter_path()
    if not helper:
        return {"ok": False, "error": (
            f"未找到重启助手。请设置环境变量 {RESTARTER_ENV}，"
            f"或把 launcher（{RESTARTER_NAME}）放在桌面。")}
    root = update_root()
    py = sys.executable
    if not py or not Path(py).is_file():
        return {"ok": False, "error": f"当前解释器不可用：{py!r}"}

    UPDATE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = UPDATE_LOG_DIR / f"restart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    # 助手先睡再动手。用 -c 内联而非落临时脚本：不留残骸。
    # 路径经 repr() 注入 ⇒ 引号与反斜杠由 Python 自己转义，不经任何 shell。
    code = (f"import subprocess, sys, time; time.sleep({WEB_RESTART_DELAY!r}); "
            f"subprocess.run([sys.executable, {helper!r}, 'restart'])")
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        with open(log, "wb") as fh:
            proc = subprocess.Popen([py, "-c", code], cwd=str(root), stdout=fh,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=flags, close_fds=True)
    except OSError as e:                                        # noqa: BLE001
        return {"ok": False, "error": f"无法拉起重启助手：{type(e).__name__}: {e}"}

    threading.Timer(WEB_RESTART_EXIT_DELAY, lambda: os._exit(0)).start()
    return {"ok": True, "pid": proc.pid, "helper": helper, "log": str(log),
            "delay": WEB_RESTART_DELAY, "exit_delay": WEB_RESTART_EXIT_DELAY}


# ---------------------------------------------------------------------------
# HTTP 处理器
# ---------------------------------------------------------------------------
def _err(status: int, message: str, **extra: Any) -> JSONResponse:
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return JSONResponse(payload, status_code=status)


async def _json_body(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise WebConfigError(f"请求体超过 {MAX_BODY_BYTES // 1024} KiB。")
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise WebConfigError(f"请求体不是合法 JSON：{e}")
    if not isinstance(data, dict):
        raise WebConfigError("请求体必须是 JSON 对象。")
    return data


#: 采信 ``CF-Connecting-IP`` 的 TCP 对端白名单。
#: 控制台只监听回环，能打进来的只有本机进程与 cloudflared —— 外部无法直连伪造。
_LOOPBACK_PEERS = frozenset({"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"})


def _client_ip(request: Request) -> str:
    """限流用的来源标识。

    **Cloudflare Tunnel 场景（2026-10-26 起）**：所有公网请求的 TCP 对端都是
    回环地址，直接取 ``request.client.host`` 会让全世界的失败登录共用一个限流桶
    —— 攻击者连试 5 次即可把站长本人锁在门外 5 分钟（DoS，而非爆破成功）。
    因此当对端是回环时，改用 ``CF-Connecting-IP`` 还原真实来源。

    **只信 ``CF-Connecting-IP``，绝不信 ``X-Forwarded-For``**：前者由 Cloudflare
    边缘**覆盖写入**（客户端自带的值会被替换掉，无法伪造）；后者是**追加**的
    （客户端可以预先塞入任意内容），采信 XFF 等于送攻击者一个「每次换个 IP」
    的开关，限流当场失效。

    本机直连（浏览器访问 127.0.0.1:8890）不带该头，自然回落到 TCP 对端。
    """
    peer = request.client.host if request.client else ""
    if peer in _LOOPBACK_PEERS:
        cf = (request.headers.get("cf-connecting-ip") or "").strip()
        if cf:
            return cf
    return peer or "?"


class WebConsole:
    """把配置与处理器收在一起，便于测试注入 stub。"""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or config()
        # 登录失败限流器：进程内单例（控制台是单进程）。5 次失败锁 5 分钟。
        # 口令可以短到人能记住的程度，没有这条就等于把爆破成本降到「跑一晚上」。
        self._limiter = web_auth.LoginLimiter(max_fails=5, window=300.0, lock_for=300.0)

    # -------- 只读接口 --------
    async def health(self, request: Request) -> Response:
        endpoint = resolve_mcp(self.cfg)
        return JSONResponse(await mcp_health(endpoint))

    async def tools(self, request: Request) -> Response:
        endpoint = resolve_mcp(self.cfg)
        try:
            items = await mcp_tools(endpoint)
        except Exception as e:                                    # noqa: BLE001
            return _err(502, f"无法获取工具清单：{_mcp_error_text(e)}",
                        endpoint=endpoint)
        groups = list(TOOL_GROUPS)
        if any(i.get("group") == TOOL_GROUP_OTHER["key"] for i in items):
            groups.append(TOOL_GROUP_OTHER)
        return JSONResponse({"ok": True, "endpoint": endpoint,
                             "count": len(items), "groups": groups,
                             "tools": items})

    async def overview(self, request: Request) -> Response:
        """一次会话取齐概览所需数据（避免 N 次握手）。"""
        endpoint = resolve_mcp(self.cfg)
        try:
            stats, recent, listing = await mcp_session_calls(endpoint, [
                ("memory_stats", {}),
                ("memory_recent", {"days": 30, "limit": 12, "output_format": "json"}),
                ("memory_list", {"limit": 14, "output_format": "json"}),
            ])
        except Exception as e:                                    # noqa: BLE001
            return _err(502, f"无法获取概览：{_mcp_error_text(e)}",
                        endpoint=endpoint)
        return JSONResponse({"ok": True, "endpoint": endpoint,
                             "stats": stats, "recent": recent, "list": listing})

    async def activity(self, request: Request) -> Response:
        """概览右栏「最近更新」热力日历的数据面：**服务端按天聚合**（2026-10-15）。

        为什么不复用 ``overview`` 里那条 ``memory_recent``：
          ① 那条是 30 天 / 12 条口径，只够铺一两天，撑不起按月着色的日历；
          ② 任何回传浏览器的工具结果都要过 ``_clip``（``_THUMB`` = 40000 字符），
             而 120 天的 ``memory_recent`` JSON 约 **13 万字符** ⇒ 前端拿到的是
             **残缺 JSON**，``JSON.parse`` 必然抛错（本轮先按「前端走 /api/call」
             实现时实测踩到，页面只落到空态）。⇒ 聚合只能在后端做，
             并且这一步要显式 ``clip=False``。

        回传的是紧凑结构，不是原始条目列表：
        ``{"ok","days","total","today","counts":{"YYYY-MM-DD":n},
        "items":{"YYYY-MM-DD":[["HH:MM","标题","摘要"], …]}}``
        —— 日期由 key 给出，行里只留时刻，摘要已在 ``memory_recent`` 侧截到 80 字。
        """
        days = _bounded_int(request.query_params.get("days"), 120, 1, 365)
        endpoint = resolve_mcp(self.cfg)
        try:
            results = await mcp_session_calls(
                endpoint,
                # limit 要给足：memory_recent 用 entries[:limit] 截取，传 0 会得到空表。
                [("memory_recent", {"days": days, "limit": 5000,
                                    "output_format": "json"})],
                clip=False,
            )
        except Exception as e:                                    # noqa: BLE001
            return _err(502, f"无法读取更新日历：{_mcp_error_text(e)}")
        try:
            payload = json.loads(results[0].get("text") or "{}")
        except Exception as e:                                    # noqa: BLE001
            return _err(502, f"更新日历数据不是合法 JSON：{_mcp_error_text(e)}")

        counts: dict[str, int] = {}
        items: dict[str, list[list[str]]] = {}
        for entry in (payload.get("entries") or []):
            if not isinstance(entry, dict):
                continue
            day, hhmm = _local_stamp(entry.get("updated"))
            if not day:
                continue
            counts[day] = counts.get(day, 0) + 1
            items.setdefault(day, []).append([
                hhmm, str(entry.get("title") or ""), str(entry.get("summary") or ""),
            ])
        for rows in items.values():       # 组内新的在上（外层已是倒序，这里只稳一次）
            rows.sort(key=lambda r: r[0], reverse=True)
        return JSONResponse({
            "ok": True,
            "days": days,
            "total": sum(counts.values()),
            "today": _local_stamp(datetime.now())[0],
            "counts": counts,
            "items": items,
        })

    async def config_get(self, request: Request) -> Response:
        app_cfg = load_app_config()
        vault = resolve_vault()
        return JSONResponse({
            "ok": True,
            "app": app_cfg,
            "resolved": {
                "mcp_endpoint": resolve_mcp(self.cfg),
                "mcp_default": self.cfg["mcp"],
                "vault": str(vault) if vault else None,
                "vault_from_env": bool(_env_str("AI_MEMORY_DIR")),
                "config_path": str(config_path()),
                "config_write": self.cfg["config_write"],
                "auth_enabled": self.cfg["auth_enabled"],
                "static": str(self.cfg["static"]),
                "version": WEB_VERSION,
                "host": self.cfg["host"],
                "port": self.cfg["port"],
            },
        })

    async def config_post(self, request: Request) -> Response:
        try:
            body = await _json_body(request)
        except WebConfigError as e:
            return _err(400, str(e))
        saved = save_app_config(body)
        self._audit(request, "config", "config.write",
                    detail="字段：" + "/".join(sorted(k for k in body
                                                    if k != "token")) or "（空）")
        return JSONResponse({"ok": True, "app": saved,
                             "resolved": {"mcp_endpoint": resolve_mcp(self.cfg)}})

    async def fns_probe(self, request: Request) -> Response:
        """配置页「测试 FNS 连接」：一次问清可达性、令牌有效性与库是否存在。

        入参可只给**要测的那几项**（前端把草稿值送来，不必先保存）；缺项回落到
        已保存的配置 —— 但**显式传空串不回退**，否则「测一下空令牌会怎样」永远
        测不到，而那种情况恰恰是最常见的配置事故。
        """
        try:
            body = await _json_body(request)
        except WebConfigError as e:
            return _err(400, str(e))
        saved = load_app_config().get("fns") or {}

        def pick(key: str) -> Any:
            if key in body and body[key] is not None:
                return body[key]
            return saved.get(key)

        try:
            probe = await anyio.to_thread.run_sync(
                lambda: fns_probe(pick("server"), pick("token"),
                                  pick("vault"), pick("client_type")))
        except WebConfigError as e:
            return _err(400, str(e))
        return JSONResponse({"ok": True, "probe": probe})

    async def thresholds_get(self, request: Request) -> Response:
        try:
            state = await thresholds_state(self.cfg)
        except WebConfigError as e:
            return _err(400, str(e))
        except Exception as e:                                    # noqa: BLE001
            return _err(502, f"读取阈值失败：{_mcp_error_text(e)}")
        return JSONResponse({"ok": True, **state})

    async def thresholds_post(self, request: Request) -> Response:
        try:
            body = await _json_body(request)
            values = body.get("values")
            if not isinstance(values, dict):
                raise WebConfigError("需要 {'values': {键: 值}}。")
            state = await write_thresholds(values, self.cfg)
        except WebConfigError as e:
            return _err(400, str(e))
        except Exception as e:                                    # noqa: BLE001
            return _err(502, f"写入阈值失败：{_mcp_error_text(e)}")
        self._audit(request, "config", "config.thresholds",
                    detail="键：" + "/".join(sorted(values)))
        return JSONResponse({"ok": True, **state})

    # -------- 调试台 --------
    async def call(self, request: Request) -> Response:
        request.state.audit_channel = "调试台"
        try:
            body = await _json_body(request)
        except WebConfigError as e:
            return _err(400, str(e))
        tool = str(body.get("tool") or "").strip()
        if not tool:
            return _err(400, "缺少 tool 字段。")
        # 工具级权限：viewer 只能碰只读工具组。
        # 分组用现成的 TOOL_GROUPS 表（唯一事实源），未登记的工具按最严处理 ——
        # 新工具不会因为「忘了登记」而对只读账号意外敞开。
        role = getattr(request.state, "auth_role", "") or ""
        if role and not web_store.role_allows_tool(role, _TOOL_GROUP_OF.get(tool)):
            grp = _TOOL_GROUP_OF.get(tool) or "未归类"
            self._audit(request, "access", "tool.denied", target=tool, ok=False,
                        detail=f"角色 {role} 无权调用「{grp}」组")
            return _err(403, f"角色 {role} 无权调用 {tool}（属于「{grp}」组）。")
        arguments = body.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _err(400, "arguments 必须是 JSON 对象。")

        # 数据视野（2026-10-26）：工具粒度之外的第二道 —— 打哪个端点决定这条
        # 连接能看见哪些密级的条目。缺 auth_clearance（本机无鉴权形态）时
        # 保持 owner，行为与改造前一致。
        clearance = getattr(request.state, "auth_clearance", "") or "owner"
        writable = getattr(request.state, "auth_writable", True) is not False
        # 只读令牌碰写工具直接拒。硬边界在 MCP 端点上（见 WRITE_TOOLS 注释），
        # 这里是「提前把话说清楚」：否则前端会收到一句来自上游的服务端措辞，
        # 用户看着像 bug 而不像权限设定。
        if not writable and tool in WRITE_TOOLS:
            self._audit(request, "access", "tool.denied", target=tool, ok=False,
                        detail="令牌为只读，写工具被拒")
            return _err(403, f"当前令牌为只读，不能调用 {tool}。")
        endpoint = resolve_mcp(self.cfg, level=clearance, writable=writable)
        t0 = time.perf_counter()
        try:
            results = await mcp_session_calls(endpoint, [(tool, arguments)])
        except Exception as e:                                    # noqa: BLE001
            return _err(502, f"调用失败：{_mcp_error_text(e)}")
        res = dict(results[0])
        res["tool"] = tool
        res["arguments"] = arguments
        res["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        res["ok"] = not res["isError"]
        self._audit(request, "tool", "tool.call", target=tool,
                    ok=bool(res["ok"]),
                    detail=f"{res['elapsed_ms']}ms · {self._caller_hint(request)}")
        return JSONResponse(res)

    # -------- 更新面 --------
    async def update_get(self, request: Request) -> Response:
        """检查更新。

        ``?target=web|core|all``（缺省 ``all``）；``?fetch=0`` 只回本地状态。
        返回恒为 ``{"ok", "checked", "targets":[...]}`` —— 每个元素是一个目标的
        完整 payload。**定位不到的目标也占一个位置**（带 error），不静默消失，
        否则界面会把「核心没找到」误读成「核心已是最新」。
        """
        raw_key = (request.query_params.get("target") or "all").strip().lower()
        keys = list(UPDATE_TARGET_KEYS) if raw_key in ("", "all") else [raw_key]
        bad = [k for k in keys if k not in UPDATE_TARGET_KEYS]
        if bad:
            return _err(400, f"未知更新目标：{bad[0]}（可用："
                             f"{', '.join(UPDATE_TARGET_KEYS)}, all）")
        raw = (request.query_params.get("fetch") or "1").strip().lower()
        online = raw not in ("0", "false", "no", "off")

        targets: list[dict] = []
        # 容器部署：两个目标一律「形态不支持」，且不触网（fetch 会在容器里白等几十秒）。
        unsup = update_unsupported()
        for key in keys:
            base = {"target": key, "target_name": UPDATE_TARGET_NAMES[key]}
            root, paths, err = update_target(key)
            if unsup:
                targets.append({**base, "root": str(root or ""), "available": False,
                                "unsupported": True, "is_repo": False,
                                "checked": False, "ok": False, "fetched": False,
                                "error": unsup, "whitelist": list(paths),
                                "tracked": [], "untracked": [], "dirty": []})
                continue
            if root is None:
                targets.append({**base, "root": "", "available": False,
                                "is_repo": False, "checked": False, "ok": False,
                                "fetched": False, "error": err,
                                "whitelist": list(paths),
                                "tracked": [], "untracked": [], "dirty": []})
                continue
            try:
                if online:
                    # git fetch 同步阻塞且可能跑几十秒 —— 必须挪出事件循环。
                    data = await anyio.to_thread.run_sync(
                        lambda r=root, p=paths, k=key: update_check(r, p, k))
                    data["checked"] = True
                else:
                    data = {"ok": True, "checked": False, **update_status(root, paths, key)}
                data["available"] = True
            except Exception as e:                                # noqa: BLE001
                data = {**base, "root": str(root), "available": True, "is_repo": True,
                        "checked": False, "ok": False, "fetched": False,
                        "whitelist": list(paths),
                        "error": f"检查更新失败：{type(e).__name__}: {e}"}
            targets.append(data)

        return JSONResponse({"ok": all(t.get("ok") for t in targets),
                             "checked": online, "targets": targets})

    async def update_post(self, request: Request) -> Response:
        try:
            body = await _json_body(request)
        except WebConfigError as e:
            return _err(400, str(e))
        key = str(body.get("target") or "web").strip().lower()
        root, paths, err = update_target(key)
        if root is None:
            return _err(400, err or f"未知更新目标：{key}")
        force = bool(body.get("force"))
        ref = str(body.get("ref") or "").strip()
        expected_sha = str(body.get("expected_sha") or "").strip()
        try:
            data = await anyio.to_thread.run_sync(
                lambda: update_apply(root, paths, key, force, ref, expected_sha))
        except Exception as e:                                    # noqa: BLE001
            return _err(500, f"更新失败：{type(e).__name__}: {e}")
        return JSONResponse(data, status_code=200 if data.get("ok") else 409)

    async def restart(self, request: Request) -> Response:
        """重启服务（MCP 上游 + Web 控制台）。控制台随后自退，由助手接手。"""
        try:
            data = await anyio.to_thread.run_sync(update_restart)
        except Exception as e:                                    # noqa: BLE001
            return _err(500, f"重启失败：{type(e).__name__}: {e}")
        return JSONResponse(data, status_code=200 if data.get("ok") else 409)

    # -------- 登录与会话（2026-10-21，方案 A） --------
    async def login(self, request: Request) -> Response:
        """账号密码 → 下发 ``HttpOnly`` 会话 Cookie。

        两点刻意的设计：
          * **用户名错与口令错返回同一句话**，且两者都用恒定时间比较、都真正跑一次
            scrypt（用位与 ``&`` 而非短路 ``and``）—— 否则时间差与文案差会把
            「这个用户名存不存在」暴露给枚举。
          * **失败次数不告诉调用方还剩几次**：那等于免费送一个爆破进度条。
        """
        cfg = self.cfg
        if not cfg["login_enabled"]:
            return _err(400, "未启用账号登录：请设置 AI_MEMORY_WEB_USER 与口令。")
        ip = _client_ip(request)
        left = self._limiter.blocked_for(ip)
        if left:
            return _err(429, f"尝试过于频繁，请 {left} 秒后再试。", retry_after=left)
        try:
            body = await _json_body(request)
        except WebConfigError as e:
            return _err(400, str(e))
        user = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        # 校验交给用户表：它内部对「用户不存在」也跑一次 scrypt（陪跑哈希），
        # 所以时间差与文案差都不会泄露「这个用户名存不存在」。
        rec = cfg["users"].verify(user, password)
        if not rec:
            left = self._limiter.fail(ip)
            # 失败也记：审计的价值一半在「谁进来了」，另一半在「谁没进来」。
            self._audit(request, "auth", "login.fail", actor=user or "(空)",
                        ok=False, detail=f"锁定 {left}s" if left else "")
            msg = "用户名或口令不正确。"
            if left:
                msg += f" 已连续失败，请 {left} 秒后再试。"
            return _err(401, msg, locked_for=left or 0)
        self._limiter.reset(ip)
        self._audit(request, "auth", "login.ok", actor=rec["name"],
                    detail=f"角色 {rec.get('role', 'viewer')}")
        ttl = int(cfg["session_ttl"])
        # role 与 epoch 都签进 Cookie：role 省掉每请求查表，epoch 是「单点吊销」的钩子。
        value = web_auth.make_session(rec["name"], cfg["session_key"], ttl=ttl,
                                      role=rec.get("role", "viewer"),
                                      epoch=rec.get("epoch", ""))
        resp = JSONResponse({"ok": True, "user": rec["name"],
                             "role": rec.get("role", "viewer"),
                             "mode": "session", "expires_in": ttl})
        resp.set_cookie(
            web_auth.COOKIE_NAME, value, max_age=ttl, path="/",
            httponly=True,                 # JS 读不到 ⇒ XSS 偷不走
            samesite="lax",                # 跨站 POST 不带 ⇒ 挡住大部分 CSRF
            secure=bool(cfg["cookie_secure"]),
        )
        return resp

    # -- OAuth 2.1 授权服务器（2026-10-26）---------------------------------
    # 这一组端点是给**网页型 MCP 客户端**用的：它们没有「填令牌」的入口，
    # 只能走标准授权流。access_token 最终仍是一枚 oauth: 前缀的 ``amt_`` 令牌，
    # 所以 /mcp 反代、中间件、视野与读写模式这条链路一行都不用改。
    def _oauth_base(self, request: Request) -> str:
        return _public_base(request, self.cfg)

    async def oauth_prm(self, request: Request) -> Response:
        """RFC 9728 受保护资源元数据：告诉客户端「令牌该向谁要」。"""
        if not self.cfg["oauth_enabled"]:
            return _err(404, "未启用 OAuth。")
        return JSONResponse(
            web_oauth.protected_resource_metadata(self._oauth_base(request)))

    async def oauth_as(self, request: Request) -> Response:
        """RFC 8414 授权服务器元数据。

        ``registration_endpoint`` 是网页类客户端的生死线 —— 拿不到
        ``client_id`` 就无法发起授权，所以这个端点必须存在且免鉴权。
        """
        if not self.cfg["oauth_enabled"]:
            return _err(404, "未启用 OAuth。")
        return JSONResponse(
            web_oauth.authorization_server_metadata(self._oauth_base(request)))

    async def oauth_register(self, request: Request) -> Response:
        """RFC 7591 动态客户端注册。**免鉴权**：这是客户端的第一个请求，
        此时它还没有任何凭据。

        正因为匿名可写，校验必须严格（见 ``web_oauth.redirect_uri_allowed``），
        并且客户端数量封顶 —— 否则任何人都能把磁盘写满。
        """
        cfg = self.cfg
        if not cfg["oauth_enabled"]:
            return _err(404, "未启用 OAuth。")
        try:
            body = await _json_body(request)
        except WebConfigError as e:
            return _err(400, str(e))
        try:
            rec = cfg["oauth_clients"].register(
                redirect_uris=body.get("redirect_uris") or [],
                client_name=str(body.get("client_name") or ""),
                token_endpoint_auth_method=str(
                    body.get("token_endpoint_auth_method") or "none"))
        except web_oauth.OAuthError as e:
            return JSONResponse({"error": e.code, "error_description": e.message},
                                status_code=400)
        logger.info("OAuth 客户端注册：%s %s", rec["client_name"], rec["redirect_uris"])
        return JSONResponse({
            "client_id": rec["client_id"],
            "client_id_issued_at": int(rec["created_at"]),
            "client_name": rec["client_name"],
            "redirect_uris": rec["redirect_uris"],
            "grant_types": rec["grant_types"],
            "response_types": rec["response_types"],
            "token_endpoint_auth_method": rec["token_endpoint_auth_method"],
        }, status_code=201)

    def _oauth_authorize_ctx(self, params) -> dict:
        """校验授权请求里的**全部**不可信入参，返回已净化的上下文。

        任何一项不合法都抛 ``OAuthError``。调用方必须注意：``client_id`` /
        ``redirect_uri`` 不可信时**不能**重定向回去（那等于开放重定向），
        只能就地渲染错误页。
        """
        cfg = self.cfg
        get = params.get
        client_id = str(get("client_id") or "").strip()
        redirect_uri = str(get("redirect_uri") or "").strip()
        rec = cfg["oauth_clients"].get(client_id)
        if not rec:
            raise web_oauth.OAuthError("invalid_client", "未知的 client_id。")
        if not cfg["oauth_clients"].redirect_ok(client_id, redirect_uri):
            raise web_oauth.OAuthError(
                "invalid_request", f"redirect_uri 与该客户端注册值不一致：{redirect_uri}")
        if str(get("response_type") or "") != "code":
            raise web_oauth.OAuthError("unsupported_response_type",
                                       "只支持 response_type=code。")
        challenge = str(get("code_challenge") or "").strip()
        if not challenge:
            raise web_oauth.OAuthError("invalid_request",
                                       "缺少 code_challenge：本服务只接受 PKCE 授权请求。")
        if str(get("code_challenge_method") or "").strip() != "S256":
            raise web_oauth.OAuthError("invalid_request",
                                       "只支持 code_challenge_method=S256。")
        state = str(get("state") or "")
        scope = str(get("scope") or "")
        resource = str(get("resource") or "")
        return {
            "client_id": client_id,
            "client_name": rec.get("client_name") or client_id,
            "redirect_uri": redirect_uri,
            "state": state, "scope": scope, "resource": resource,
            "challenge": challenge,
            "hidden": {
                "client_id": client_id, "redirect_uri": redirect_uri,
                "response_type": "code", "code_challenge": challenge,
                "code_challenge_method": "S256", "state": state,
                "scope": scope, "resource": resource,
            },
        }

    def _oauth_session_user(self, request: Request) -> dict | None:
        """当前浏览器里的有效登录会话（用于「已登录就直接确认」）。"""
        cfg = self.cfg
        if not cfg["session_key"]:
            return None
        sess = web_auth.read_session(
            request.cookies.get(web_auth.COOKIE_NAME, ""), cfg["session_key"])
        if not sess:
            return None
        live = cfg["users"].session_valid(str(sess.get("u") or ""),
                                          str(sess.get("e") or ""))
        if not live:
            return None
        return {"user": live["name"], "role": live.get("role", "viewer")}

    async def _oauth_form(self, request: Request) -> dict:
        """解析入参：**表单与 JSON 都收**。

        规范只要求 ``application/x-www-form-urlencoded``，但实测有客户端
        图省事发 JSON。刻意不用 ``request.form()`` —— 那会引入
        ``python-multipart`` 依赖，而本仓的部署原则是「不加任何新依赖」
        （见 web_auth.py 顶部）。urlencoded 用标准库解析即可。
        """
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise WebConfigError(f"请求体超过 {MAX_BODY_BYTES // 1024} KiB。")
        text = raw.decode("utf-8", "replace")
        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype == "application/json":
            try:
                obj = json.loads(text or "{}")
            except ValueError:
                return {}
            return ({str(k): str(v) for k, v in obj.items()}
                    if isinstance(obj, dict) else {})
        return {k: v[0] for k, v in parse_qs(text, keep_blank_values=True).items()}

    @staticmethod
    def _oauth_redirect(uri: str, params: dict) -> Response:
        """回到**已确认属于该客户端**的 ``redirect_uri``，带上结果参数。"""
        qs = urlencode({k: v for k, v in params.items() if v})
        if not qs:
            return RedirectResponse(uri, status_code=302)
        sep = "&" if "?" in uri else "?"
        return RedirectResponse(f"{uri}{sep}{qs}", status_code=302)

    async def oauth_authorize_get(self, request: Request) -> Response:
        """授权页（GET）。未登录则在同一页上让用户登录并确认。"""
        cfg = self.cfg
        if not cfg["oauth_enabled"]:
            return HTMLResponse(web_oauth.error_page("未启用", "本控制台未启用 OAuth。"),
                                status_code=404)
        try:
            ctx = self._oauth_authorize_ctx(request.query_params)
        except web_oauth.OAuthError as e:
            return HTMLResponse(web_oauth.error_page("授权请求无效", e.message),
                                status_code=400)
        sess = self._oauth_session_user(request)
        return HTMLResponse(web_oauth.authorize_page(
            client_name=ctx["client_name"], redirect_uri=ctx["redirect_uri"],
            state=ctx["state"], scope=ctx["scope"],
            role=(sess or {}).get("role") or "viewer",
            user=(sess or {}).get("user") or "",
            need_login=not sess,
            login_enabled=bool(cfg["login_enabled"]),
            hidden=ctx["hidden"]))

    async def oauth_authorize_post(self, request: Request) -> Response:
        """授权页提交：登录（若需要）+ 同意/拒绝 → 签发授权码。"""
        cfg = self.cfg
        if not cfg["oauth_enabled"]:
            return HTMLResponse(web_oauth.error_page("未启用", "本控制台未启用 OAuth。"),
                                status_code=404)
        form = await self._oauth_form(request)
        try:
            ctx = self._oauth_authorize_ctx(form)
        except web_oauth.OAuthError as e:
            return HTMLResponse(web_oauth.error_page("授权请求无效", e.message),
                                status_code=400)
        if str(form.get("decision") or "") != "allow":
            # 拒绝也是排障事实：授权页点错一次，客户端侧只会说「授权失败」。
            logger.info("OAuth 授权被拒绝：client=%s", ctx["client_id"])
            return self._oauth_redirect(
                ctx["redirect_uri"], {"error": "access_denied", "state": ctx["state"]})

        sess = self._oauth_session_user(request)
        if not sess:
            ip = _client_ip(request)
            left = self._limiter.blocked_for(ip)
            if left:
                return HTMLResponse(
                    web_oauth.error_page("尝试过于频繁", f"请 {left} 秒后再试。"),
                    status_code=429)
            rec = cfg["users"].verify(str(form.get("username") or "").strip(),
                                      str(form.get("password") or ""))
            if not rec:
                left = self._limiter.fail(ip)
                # 只记客户端与来源 IP，**不记用户名/口令**（用户名属 PII，
                # 口令更是绝对禁区）。这一条是「授权页卡住」最直接的证据。
                logger.warning("OAuth 授权页登录失败：client=%s ip=%s",
                               ctx["client_id"], ip)
                msg = "用户名或口令不正确。"
                if left:
                    msg += f" 请 {left} 秒后再试。"
                return HTMLResponse(web_oauth.authorize_page(
                    client_name=ctx["client_name"], redirect_uri=ctx["redirect_uri"],
                    state=ctx["state"], scope=ctx["scope"], role="", user="",
                    need_login=True, login_enabled=bool(cfg["login_enabled"]),
                    hidden=ctx["hidden"], error=msg), status_code=401)
            self._limiter.reset(ip)
            sess = {"user": rec["name"], "role": rec.get("role", "viewer")}

        role = sess.get("role") or "viewer"
        code = cfg["oauth_codes"].issue(
            client_id=ctx["client_id"], redirect_uri=ctx["redirect_uri"],
            user=sess["user"], role=role, clearance=web_store.clearance_of(role),
            challenge=ctx["challenge"], scope=ctx["scope"], resource=ctx["resource"])
        logger.info("OAuth 授权通过：client=%s user=%s role=%s",
                    ctx["client_id"], sess["user"], role)
        return self._oauth_redirect(ctx["redirect_uri"],
                                    {"code": code, "state": ctx["state"]})

    async def oauth_token(self, request: Request) -> Response:
        """授权码 + PKCE → 一枚 ``amt_`` 访问令牌（复用令牌表，可吊销）。"""
        cfg = self.cfg

        def bad(code: str, msg: str, status: int = 400) -> Response:
            # 只记**错误码**，不记 code / code_verifier / redirect_uri：前者是
            # 一次性凭据，后两者会把完整的回调地址与校验器写进日志。
            logger.info("OAuth 换令牌失败：error=%s status=%s", code, status)
            return JSONResponse({"error": code, "error_description": msg},
                                status_code=status,
                                headers={"Cache-Control": "no-store"})

        if not cfg["oauth_enabled"]:
            return bad("invalid_request", "未启用 OAuth。", 404)
        form = await self._oauth_form(request)
        if str(form.get("grant_type") or "") != "authorization_code":
            return bad("unsupported_grant_type", "只支持 authorization_code。")

        # 先消费再校验：无论后续哪一步失败，这个码都不能再用（防重放）。
        rec = cfg["oauth_codes"].consume(str(form.get("code") or ""))
        if not rec:
            return bad("invalid_grant", "授权码无效、已被使用或已过期。")
        client_id = str(form.get("client_id") or "")
        if client_id and client_id != rec["client_id"]:
            return bad("invalid_grant", "client_id 与授权码不匹配。")
        if str(form.get("redirect_uri") or "") != rec["redirect_uri"]:
            return bad("invalid_grant", "redirect_uri 与授权时不一致。")
        verifier = str(form.get("code_verifier") or "")
        if not verifier:
            return bad("invalid_request", "缺少 code_verifier。")
        try:
            got = web_oauth.s256(verifier)
        except (UnicodeEncodeError, ValueError):
            return bad("invalid_request", "code_verifier 含非 ASCII 字符。")
        if not hmac.compare_digest(got, rec["challenge"]):
            return bad("invalid_grant", "PKCE 校验失败。")

        client = cfg["oauth_clients"].get(rec["client_id"]) or {}
        label = client.get("client_name") or rec["client_id"][:12]
        try:
            plain, pub = cfg["tokens"].create(
                name=f"oauth:{label}", owner=rec["user"], role=rec["role"],
                clearance=rec["clearance"] or None,
                expires_in=web_oauth.ACCESS_TTL, max_uses=0)
        except web_store.StoreError as e:
            logger.warning("OAuth 签发令牌失败：%s", e)
            return bad("server_error", f"签发令牌失败：{e}", 500)
        # 字段名从 ``token=`` 改成 ``id=``：这里记的是令牌表记录号（``t_…``），
        # 不是令牌本身。沿用 ``token=`` 会让后来读日志的人以为泄露了凭据。
        logger.info("OAuth 换令牌：user=%s client=%s id=%s",
                    rec["user"], rec["client_id"], pub.get("id"))
        return JSONResponse({
            "access_token": plain,
            "token_type": "Bearer",
            "expires_in": web_oauth.ACCESS_TTL,
            "scope": rec.get("scope") or "",
        }, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    async def logout(self, request: Request) -> Response:
        """清除会话 Cookie。

        **不校验登录态**：登出必须永远成功。若要求先认证，那么「会话已过期但
        页面还挂着」时用户点登出会收到 401，比登不出去更让人困惑。
        """
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(web_auth.COOKIE_NAME, path="/")
        # 登出走的是免鉴权路径（见上），``request.state`` 里没有身份 —— 但 Cookie
        # 还在请求上，就地解一次会话即可拿到「是谁登出的」，比记成 anonymous 有用。
        actor = ""
        if self.cfg["session_key"]:
            sess = web_auth.read_session(
                request.cookies.get(web_auth.COOKIE_NAME, ""), self.cfg["session_key"])
            actor = str((sess or {}).get("u") or "")
        self._audit(request, "auth", "logout", actor=actor)
        return resp

    async def session(self, request: Request) -> Response:
        """当前认证状态。前端启动时先问这一句，决定弹登录框还是直接进界面。"""
        cfg = self.cfg
        mode, user = "none", ""
        supplied = ""
        raw = request.headers.get("Authorization", "")
        if raw.lower().startswith("bearer "):
            supplied = raw[7:].strip()
        if not supplied:
            supplied = request.headers.get("X-Auth-Token", "").strip()
        role = ""
        clearance = ""
        access = ""
        if supplied:
            hit = cfg["tokens"].verify(supplied)
            if hit:
                mode, user, role = "token", str(hit.get("owner") or ""), str(hit.get("role") or "")
                clearance = str(hit.get("clearance") or "")
                access = str(hit.get("access") or "")
        # ⚠️ 这里必须是 ``mode == "none"`` 而不能写 ``not mode``：
        # mode 的初值是字符串 "none"（真值），``not mode`` 恒为 False，
        # 于是会话分支整段不会执行 —— 表现是「登录成功但立刻问状态又说没登录」。
        if mode == "none" and cfg["session_key"]:
            sess = web_auth.read_session(
                request.cookies.get(web_auth.COOKIE_NAME, ""), cfg["session_key"])
            if sess:
                # 会话有效不等于**用户**仍然有效：可能已被禁用、改口令或删号。
                # epoch 比对就是这一步（旧版 Cookie 没有 e 字段 ⇒ 这里必然落空，
                # 于是升级后要求重新登录一次，是刻意的）。
                live = cfg["users"].session_valid(
                    str(sess.get("u") or ""), str(sess.get("e") or ""))
                if live:
                    mode, user, role = "session", live["name"], live["role"]
        need = bool(cfg["auth_enabled"] or cfg["login_enabled"])
        return JSONResponse({
            "ok": mode != "none",
            "auth_required": need and mode == "none",
            "mode": mode,
            "user": user,
            "role": role,
            # 当前连接的数据视野（2026-10-26）。前端据此显示「能看见哪些密级」，
            # 与 /api/call 实际使用的端点是同一个值，不会各说各话。
            "clearance": (clearance if clearance in web_store.CLEARANCE_RANK
                          else (web_store.clearance_of(role) if role else "")),
            # 读写模式（2026-10-26）。前端据此把写入口置灰；真正的拦截在
            # /api/call 与 MCP 只读端点上，不依赖这条字段。
            "access": (web_store.access_of(role, access) if role else ""),
            "writable": (web_store.access_of(role, access) == "rw") if role else True,
            "can_manage": role == "admin",
            "multi_user": bool(cfg["multi_user"]),
            "login_enabled": bool(cfg["login_enabled"]),
            "session_ttl": int(cfg["session_ttl"]),
        })

    # -------- 管理面：用户与令牌（2026-10-22）----------------------------
    #
    # 权限模型：admin 能管人管令牌；operator 能调全部工具但不能管人；
    # viewer 只能调只读工具组。单令牌时代「登录了就全通」的假设在这里结束。
    #
    # 一个刻意的细节：**本地无鉴权模式（回环 + 既无 token 又无账号）视为 admin**。
    # 那种形态本来就是「谁打开谁全通」，若这里再要求 role 反而会让本地调试
    # 完全无法管理 —— 安全增益为零（能打开界面的人本来就能调工具），
    # 却把可用性打掉。

    def _is_open_mode(self) -> bool:
        cfg = self.cfg
        return not (cfg["auth_enabled"] or cfg["login_enabled"])

    def _need_admin(self, request: Request) -> Response | None:
        if self._is_open_mode():
            return None
        role = getattr(request.state, "auth_role", "") or ""
        if role != "admin":
            return _err(403, "需要管理员权限：当前账号是 {}".format(role or "未知角色"))
        return None

    def _actor(self, request: Request) -> str:
        return getattr(request.state, "auth_user", "") or ""

    def _audit(self, request: Request, kind: str, action: str, *,
               target: str = "", ok: bool = True, detail: str = "",
               actor: str = "") -> None:
        """记一条审计事件（访问控制页「访问日志」卡的唯一写入口）。

        两条刻意的设计：

        * **永不抛错**：审计写盘失败（磁盘满、文件被占用）不该让业务请求跟着失败。
          代价是「日志有洞」，收益是「服务不因日志而不可用」—— 这个取舍在本场景
          是明确的：日志是旁证，不是业务的一部分。
        * **不自己拼字符串**：``actor`` / ``role`` / ``via`` / ``ip`` 全部独立成字段，
          让前端与后续筛选能按维度处理，而不是回头拿正则去切一段人写的句子。
        """
        try:
            self.cfg["audit"].append({
                "kind": kind,
                "action": action,
                "actor": actor or self._actor(request) or "",
                "role": getattr(request.state, "auth_role", "") or "",
                "via": getattr(request.state, "auth_via", "") or "",
                "ip": _client_ip(request),
                "target": target,
                "ok": bool(ok),
                "detail": detail,
            })
        except Exception:                                    # noqa: BLE001
            logger.warning("审计写入失败（%s/%s），已忽略", kind, action, exc_info=True)

    @staticmethod
    def _caller_hint(request: Request) -> str:
        """这条调用是从哪个口进来的（调试台 / 地址栏 / MCP 反代）。

        三个入口都能调同一个工具，但「谁在什么地方调的」是审计的核心信息 ——
        只看工具名的话，分不清是人在界面里点的、还是某个脚本拿 URL 打的。
        """
        return str(getattr(request.state, "audit_channel", "") or "")


    async def password_post(self, request: Request) -> Response:
        """自己改自己的口令。改完 epoch 轮换 ⇒ 所有旧会话失效，需要重新登录。"""
        if self._is_open_mode():
            return _err(400, "未启用账号系统：本地无鉴权模式没有口令可改。")
        user = self._actor(request)
        if not user:
            return _err(400, "当前是令牌通道，没有账号口令可改。")
        try:
            body = await _json_body(request)
        except WebConfigError as e:
            return _err(400, str(e))
        old = str(body.get("old_password") or "")
        new = str(body.get("new_password") or "")
        if not self.cfg["users"].verify(user, old):
            return _err(401, "原口令不正确。")
        try:
            self.cfg["users"].update(user, password=new)
        except web_store.StoreError as e:
            return _err(400, str(e))
        self._audit(request, "account", "password.change", target=user)
        resp = JSONResponse({"ok": True, "relogin": True})
        resp.delete_cookie(web_auth.COOKIE_NAME, path="/")
        return resp

    async def users_get(self, request: Request) -> Response:
        if (bad := self._need_admin(request)) is not None:
            return bad
        return JSONResponse({"ok": True, "users": self.cfg["users"].list(),
                             "roles": list(web_store.ROLE_TOOLS.keys())})

    async def users_post(self, request: Request) -> Response:
        if (bad := self._need_admin(request)) is not None:
            return bad
        try:
            body = await _json_body(request)
        except WebConfigError as e:
            return _err(400, str(e))
        try:
            rec = self.cfg["users"].create(
                name=str(body.get("name") or ""),
                password=str(body.get("password") or ""),
                role=str(body.get("role") or "viewer"))
        except web_store.StoreError as e:
            return _err(400, str(e))
        logger.info("用户已创建：%s（role=%s，操作人=%s）",
                    rec["name"], rec["role"], self._actor(request) or "open-mode")
        self._audit(request, "account", "account.create", target=rec["name"],
                    detail=f"角色 {rec['role']}")
        return JSONResponse({"ok": True, "user": rec})

    async def user_patch(self, request: Request) -> Response:
        if (bad := self._need_admin(request)) is not None:
            return bad
        name = str(request.path_params.get("name") or "")
        try:
            body = await _json_body(request)
        except WebConfigError as e:
            return _err(400, str(e))
        try:
            rec = self.cfg["users"].update(
                name,
                password=(str(body["password"]) if body.get("password") else None),
                role=(str(body["role"]) if body.get("role") else None),
                enabled=(bool(body["enabled"]) if "enabled" in body else None))
        except web_store.StoreError as e:
            return _err(400, str(e))
        logger.info("用户已修改：%s（操作人=%s）", name, self._actor(request) or "open-mode")
        changed = [k for k in ("password", "role", "enabled") if k in body]
        self._audit(request, "account", "account.update", target=name,
                    detail="改动：" + "/".join(changed))
        return JSONResponse({"ok": True, "user": rec})

    async def user_delete(self, request: Request) -> Response:
        if (bad := self._need_admin(request)) is not None:
            return bad
        name = str(request.path_params.get("name") or "")
        try:
            self.cfg["users"].delete(name)
        except web_store.StoreError as e:
            return _err(400, str(e))
        # 连带吊销他的令牌：删号却留着令牌等于「删了个寂寞」。
        for t in self.cfg["tokens"].list(owner=name):
            try:
                self.cfg["tokens"].revoke(t["id"])
            except web_store.StoreError:
                pass
        logger.info("用户已删除：%s（操作人=%s）", name, self._actor(request) or "open-mode")
        self._audit(request, "account", "account.delete", target=name)
        return JSONResponse({"ok": True})

    async def tokens_get(self, request: Request) -> Response:
        """管理员看全部，operator 只看自己的，**只读账号整条路不通**。

        2026-10-26 主人指令：只读账号连「访问控制」页都不该进。入口已从侧栏
        移除，服务端在这里同步收紧 —— 只藏 UI 不拦接口，等于给出一条
        「知道 URL 就能用」的后门，而这类后门恰恰是最容易被忘掉的那种。
        """
        if self._is_open_mode():
            return JSONResponse({"ok": True, "tokens": self.cfg["tokens"].list(),
                                 "self_only": False})
        role = getattr(request.state, "auth_role", "") or ""
        if role == "viewer":
            return _err(403, "只读账号不具备令牌管理能力。")
        user = self._actor(request)
        rows = self.cfg["tokens"].list() if role == "admin" else self.cfg["tokens"].list(owner=user)
        return JSONResponse({"ok": True, "tokens": rows,
                             "self_only": role != "admin",
                             "max_expires": 365 * 86400})

    async def audit_get(self, request: Request) -> Response:
        """访问日志（2026-10-27）。admin 专属，读 ``audit.jsonl``。

        为什么连**只读接口**也要卡 admin：这份日志是「谁进过门、动过什么」的完整
        清单，本身就是一张侦察地图 —— operator 能翻别人的动作，等于白送一份
        「哪些账号什么时候活跃、谁签过令牌」的画像。而它对只读账号毫无用处。
        """
        if (bad := self._need_admin(request)) is not None:
            return bad
        qp = request.query_params
        since = None
        raw_since = str(qp.get("since") or "").strip()
        if raw_since:
            try:
                since = float(raw_since)
            except ValueError:
                return _err(400, "since 必须是 unix 秒（数字）。")
        rows = self.cfg["audit"].tail(
            limit=_bounded_int(qp.get("limit"), 40, 1, 500),
            kind=str(qp.get("kind") or "").strip(),
            actor=str(qp.get("actor") or "").strip(),
            action=str(qp.get("action") or "").strip(),
            since=since)
        return JSONResponse({"ok": True, "events": rows,
                             "kinds": web_audit.kind_labels(),
                             "stats": self.cfg["audit"].stats()})

    async def audit_export(self, request: Request) -> Response:
        """导出访问日志（2026-10-27 主人：「再添加个 ip 显示,和导出日志」）。

        与 ``audit_get`` 同一权限口径（admin 专属），区别只在**量的口径**：
        界面看最近 N 条（分页式「刷新」），导出拿**全部命中项** —— 只导一屏
        40 条没有任何意义，那不是「导出日志」，是「截图」。

        两种格式，理由分别写清：

        * ``csv``（默认）：给人和 Excel 用。带 UTF-8 BOM —— Excel 在中文
          Windows 上默认按 GBK 解无 BOM 的 UTF-8，没有 BOM 会整片乱码
          （本机 2026-10-27 已踩过一次同类坑）。
        * ``json``：给脚本与后续分析用，结构与 ``/api/audit`` 的 ``events``
          完全一致，可以直接喂给同一套下游代码。

        导出行为本身也记一条审计（``audit.export``）：把整份「谁进过门」的
        清单一次性带走，是这份日志里**最该被记录**的动作之一。
        它归入 ``config`` 类而不是新开一类 —— 右侧卡片宽 344px，筛选 chip
        刚好一行放下 7 个，多一个就会被挤成两行（第二行只剩一个，像漏了一格）。
        """
        if (bad := self._need_admin(request)) is not None:
            return bad
        qp = request.query_params
        fmt = str(qp.get("format") or "csv").strip().lower()
        if fmt not in ("csv", "json"):
            return _err(400, "format 只能是 csv 或 json。")
        since = None
        raw_since = str(qp.get("since") or "").strip()
        if raw_since:
            try:
                since = float(raw_since)
            except ValueError:
                return _err(400, "since 必须是 unix 秒（数字）。")
        kind = str(qp.get("kind") or "").strip()
        rows = self.cfg["audit"].dump(
            kind=kind,
            actor=str(qp.get("actor") or "").strip(),
            action=str(qp.get("action") or "").strip(),
            since=since)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"ai-memory-audit-{stamp}.{fmt}"
        self._audit(request, "config", "audit.export",
                    target=f"{fmt} · {len(rows)} 条",
                    detail=("筛选 " + kind) if kind else "全量")
        if fmt == "json":
            body = json.dumps({"ok": True, "count": len(rows),
                               "exported_at": round(time.time(), 3),
                               "events": rows},
                              ensure_ascii=False, indent=2)
            media = "application/json; charset=utf-8"
        else:
            buf = io.StringIO()
            # newline="" 的意义：csv 模块自己写 \r\n，若外层再转一次会变成 \r\r\n，
            # Excel 打开时每行多一个空行。
            writer = csv.writer(buf, lineterminator="\r\n")
            writer.writerow(["时间", "类型", "动作", "操作人", "角色",
                             "通道", "IP", "对象", "结果", "详情"])
            labels = {k: v for k, v in web_audit.AUDIT_KINDS}
            for r in rows:
                writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S",
                                  time.localtime(float(r.get("t") or 0))),
                    labels.get(str(r.get("kind") or ""), str(r.get("kind") or "")),
                    str(r.get("action") or ""),
                    str(r.get("actor") or ""),
                    str(r.get("role") or ""),
                    str(r.get("via") or ""),
                    str(r.get("ip") or ""),
                    str(r.get("target") or ""),
                    "成功" if r.get("ok") is not False else "失败",
                    str(r.get("detail") or ""),
                ])
            # BOM 是给 Excel 的信号，不是编码的一部分：少了它，中文按 GBK 解。
            body = "\ufeff" + buf.getvalue()
            media = "text/csv; charset=utf-8"
        return Response(
            body,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{name}"',
                     # 审计导出不该被任何中间层缓存：这份文件是「此刻的完整
                     # 清单」，缓存一份旧的就是在骗人。
                     "Cache-Control": "no-store"})

    async def tokens_post(self, request: Request) -> Response:
        """建令牌。**明文只在这个响应里出现一次**，之后表里只有 sha256。"""
        if self._is_open_mode():
            pass                                     # 本地模式不限
        else:
            role = getattr(request.state, "auth_role", "") or ""
            if role not in ("admin", "operator"):
                return _err(403, "只读账号不能创建令牌。")
        try:
            body = await _json_body(request)
        except WebConfigError as e:
            return _err(400, str(e))

        actor = self._actor(request) or "local"
        actor_role = getattr(request.state, "auth_role", "") or "admin"
        want_role = str(body.get("role") or "operator")
        # 不能签出比自己更高的权限：operator 不能造 admin 令牌。
        if (web_store.ROLE_RANK.get(want_role, 0)
                > web_store.ROLE_RANK.get(actor_role, 0) and not self._is_open_mode()):
            return _err(403, f"不能创建权限高于自己的令牌（{want_role} > {actor_role}）。")
        expires_in = body.get("expires_in")
        try:
            plain, rec = self.cfg["tokens"].create(
                name=str(body.get("name") or ""),
                owner=actor,
                role=want_role,
                # 数据视野：不传则由角色推导（viewer→reader / operator→member /
                # admin→owner）；传了必须 ≤ 角色上限，越界由 TokenStore 拒绝。
                clearance=(str(body.get("clearance")).strip()
                           if body.get("clearance") else None),
                # 读写模式（2026-10-26）：不传则由角色推导（admin/operator→rw、
                # viewer→ro）；传 ro 永远允许（更保守），传 rw 时若角色默认只读
                # 会被 TokenStore 拒 —— 不签「表里不一」的令牌。
                access=(str(body.get("access")).strip()
                        if body.get("access") else None),
                expires_in=(int(expires_in) if expires_in not in (None, "", 0) else None),
                max_uses=int(body.get("max_uses") or 0))
        except (web_store.StoreError, TypeError, ValueError) as e:
            return _err(400, str(e))
        logger.warning("令牌已签发：%s（owner=%s，role=%s，次数=%s，操作人=%s）",
                       rec["name"], rec["owner"], rec["role"],
                       rec["max_uses"] or "不限", actor)
        self._audit(request, "token", "token.issue", target=rec["name"],
                    detail=(f"角色 {rec['role']} · 视野 {rec['clearance']} · "
                            f"读写 {rec['access']} · 次数 {rec['max_uses'] or '不限'}"))
        return JSONResponse({"ok": True, "token": plain, "record": rec,
                             "note": "这串明文只显示这一次，关闭后无法再取回；表里只存 sha256。"})

    async def token_delete(self, request: Request) -> Response:
        tid = str(request.path_params.get("tid") or "")
        actor = self._actor(request)
        role = getattr(request.state, "auth_role", "") or "admin"
        # 与 tokens_get 同一口径：只读账号不参与令牌管理（含吊销自己的）。
        if role == "viewer" and not self._is_open_mode():
            return _err(403, "只读账号不具备令牌管理能力。")
        try:
            self.cfg["tokens"].revoke(tid, owner=(None if role == "admin" else actor))
        except web_store.StoreError as e:
            return _err(400, str(e))
        logger.warning("令牌已吊销：%s（操作人=%s）", tid, actor or "open-mode")
        self._audit(request, "token", "token.revoke", target=tid)
        return JSONResponse({"ok": True})

    async def internal_verify(self, request: Request) -> Response:
        """给 nginx ``auth_request`` 用：校验令牌 → 204，否则 401。

        凭据是容器间的 ``X-Internal-Key``，不是用户会话 —— 网关手里没有 Cookie。
        未配置该密钥时返回 **404**（功能关闭），而不是 401：这样「没启用」和
        「密钥错」在日志里能分开，排查时不用猜。
        """
        cfg = self.cfg
        key = cfg.get("internal_key") or ""
        if not key:
            return Response(status_code=404)
        got = request.headers.get("X-Internal-Key", "")
        if not got or not hmac.compare_digest(got, key):
            return Response(status_code=401)
        raw = request.headers.get("Authorization", "")
        supplied = raw[7:].strip() if raw.lower().startswith("bearer ") else ""
        hit = cfg["tokens"].verify(supplied) if supplied else None
        if not hit:
            return Response(status_code=401)
        # header 值只能是 latin-1：中文令牌名直接塞会抛 UnicodeEncodeError。
        q = quote
        return Response(status_code=204, headers={
            "X-Token-Owner": q(str(hit.get("owner") or ""), safe=""),
            "X-Token-Name": q(str(hit.get("name") or ""), safe=""),
            "X-Token-Role": q(str(hit.get("role") or ""), safe=""),
        })

    async def internal_fns_config(self, request: Request) -> Response:
        """给 fns-sync 容器拉配置（方案 C，2026-10-23）。

        鉴权与网关回调同一条通道：``X-Internal-Key``。三种失败码各有含义 ——
        **404** 功能未启用（没配密钥）、**401** 密钥错、**503** 控制台里的 FNS
        配置还不全（附缺失项）。容器对这三者统一动作：回退自带模板，但日志里
        能一眼分清是「没开」还是「没填」。
        """
        key = self.cfg.get("internal_key") or ""
        if not key:
            return Response(status_code=404)
        got = request.headers.get("X-Internal-Key", "")
        if not got or not hmac.compare_digest(got, key):
            return Response(status_code=401)

        app_cfg = load_app_config()
        text, missing = fns_sync_config(app_cfg.get("fns") or {})
        if missing:
            return JSONResponse(
                {"ok": False, "missing": missing,
                 "error": "控制台里的 FNS 配置还缺：" + "、".join(missing)},
                status_code=503)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        # 修订号随内容变：容器据此判断「要不要重启自己」，比时间戳可靠。
        return Response(text, media_type="text/yaml; charset=utf-8", headers={
            "X-Fns-Config-Revision": digest,
            "Cache-Control": "no-store",
        })

    # -------- MCP 反代（2026-10-22，v1.7.0）-----------------------------
    async def mcp_proxy(self, request: Request) -> Response:
        """把 ``/mcp`` 流式转发到上游 MCP 端点。

        为什么必须**流式**：MCP Streamable HTTP 的 POST 可能直接回
        ``text/event-stream``（进度/通知），GET 则是一条长活的 SSE 通道。
        任何「先读完整个 body 再回包」的写法都会把 SSE 变成「等服务器关闭才
        吐第一帧」，客户端表现为**连接成功却永远收不到消息** —— 这是最难从
        日志里看出来的一类故障，所以这里一律 stream。

        为什么每个请求新建一个 ``httpx.AsyncClient``：流的存活期与请求同寿，
        共享 client 就得在「最后一个流结束」时关闭它，生命周期管理比省下的
        那点连接复用更贵；上游在回环，建连成本可忽略。

        鉴权已经在 ``AuthMiddleware`` 里做完（``/mcp`` 与 ``/api/*`` 同一口径），
        这里只负责转发；本控制台自己的凭据（Authorization / Cookie）**不往上游带**。
        """
        clearance = getattr(request.state, "auth_clearance", "") or "owner"
        writable = getattr(request.state, "auth_writable", True) is not False
        # 2026-10-27（主人报「令牌取不到值」）：在浏览器 / 网页读取工具里打开
        # `/mcp?token=…` 时，上游按 MCP 协议回 **406 Client must accept
        # text/event-stream** —— 那是**协议协商**，不是令牌失效，可人在浏览器里
        # 只看到一段 406 报文，读起来就是「这链接取不到值」。
        # 这里只对「GET 且 Accept 没点名 MCP 两种类型」的**人类探测**降级成
        # 200 + 可读自证报文（这地址是什么 / 这枚令牌是谁 / 正确的接法）。
        # 边界收得很窄：POST（客户端发消息）与带 event-stream 的 GET（开 SSE）
        # 一律照旧转发，协议行为一个字不变。
        if request.method == "GET" and not _accepts_mcp(request):
            # 带 ``tool=`` ⇒ 只读调用（地址栏传参查库）；不带 ⇒ 自证报文。
            if str(request.query_params.get("tool") or "").strip():
                return await self._mcp_get_call(request)
            return self._mcp_browse_card(request)
        target = resolve_mcp(self.cfg, level=clearance, writable=writable)
        # 我们自己认的 ?token= 不往上游带：它不该多传一跳。
        params = [(k, v) for k, v in request.query_params.multi_items()
                  if k != "token"]
        url = target
        if params:
            url += ("&" if "?" in target else "?") + urlencode(params)

        headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in _PROXY_DROP_REQ}
        body = await request.body()

        client = httpx.AsyncClient(timeout=None, follow_redirects=False)
        upstream = client.build_request(request.method, url,
                                        headers=headers, content=body)
        try:
            resp = await client.send(upstream, stream=True)
        except httpx.HTTPError as e:
            await client.aclose()
            logger.warning("MCP 反代失败：%s %s -> %s（%s: %s）",
                           request.method, target, url, type(e).__name__, e)
            return _err(502, f"MCP 上游不可达：{_mcp_error_text(e)}")

        # 审计（档 3：全量工具调用）。放在**拿到上游状态码之后** —— 这样 ok 是
        # 真实结果，而不是「我猜它成功了」。SSE 正文不回读：流一旦开始读，
        # 转发就必须自己再拼一遍，代价远大于收益。
        if request.method == "POST":
            request.state.audit_channel = "MCP 反代"
            self._audit_rpc(request, body, ok=resp.status_code < 400)

        out_headers = {k: v for k, v in resp.headers.items()
                       if k.lower() not in _PROXY_DROP_RESP}

        async def _close() -> None:
            try:
                await resp.aclose()
            finally:
                await client.aclose()

        return StreamingResponse(resp.aiter_raw(), status_code=resp.status_code,
                                 headers=out_headers,
                                 background=BackgroundTask(_close))

    async def _mcp_get_call(self, request: Request) -> Response:
        """GET 版**只读**调用：``/mcp?token=…&tool=memory_search&keyword=…``。

        三种参数写法，按需选一种：

        1. 松散：``?tool=memory_search&keyword=令牌&limit=2`` —— 除保留键外
           的查询参数逐个当**字符串**参数（不猜类型，避免「123」被悄悄变成
           数字，需要真类型就用第 2 种）；
        2. 规范：``?tool=memory_search&args={"keyword":"令牌","limit":2}``
           （JSON 必须 URL 编码，这是**唯一**能传数字/布尔/嵌套的写法）；
        3. 可读输出：加 ``&format=text`` 直接回纯文本，适合手机浏览器。

        为什么只放只读：GET 会进浏览器历史、隧道日志与访问日志，写操作一旦走
        这条路就不可撤销——撤不回「谁在什么时候写了什么」。所以工具必须落在
        ``GET_READONLY_TOOLS`` 白名单内，写工具连参数都解析不到就先被挡。
        """
        params = request.query_params
        tool = str(params.get("tool") or "").strip()
        if tool not in GET_READONLY_TOOLS:
            request.state.audit_channel = "地址栏"
            self._audit(request, "access", "tool.denied", target=tool, ok=False,
                        detail="URL 调用白名单外")
            return _err(
                403,
                f"URL 传参只允许只读工具：{tool or '未指定工具'} 不在白名单内。"
                " 写操作请用 POST /mcp 或 POST /api/call。",
                readonly_tools=sorted(GET_READONLY_TOOLS))
        role = getattr(request.state, "auth_role", "") or ""
        group = _TOOL_GROUP_OF.get(tool)
        if role and not web_store.role_allows_tool(role, group):
            return _err(403, f"角色 {role} 无权调用 {tool}"
                             f"（属于「{group or '未归类'}」组）。")

        request.state.audit_channel = "地址栏"
        raw = params.get("args")
        arguments: dict[str, Any] = {}
        if raw:
            if len(raw) > GET_CALL_ARGS_MAX:
                return _err(400, f"args 过长（上限 {GET_CALL_ARGS_MAX} 字符）。")
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                return _err(400, "args 必须是 URL 编码后的 JSON 对象。")
            if not isinstance(parsed, dict):
                return _err(400, "args 必须是 JSON 对象。")
            arguments = parsed
        else:
            for key, val in params.multi_items():
                if key not in GET_CALL_RESERVED:
                    arguments[key] = val

        clearance = getattr(request.state, "auth_clearance", "") or "owner"
        writable = getattr(request.state, "auth_writable", True) is not False
        endpoint = resolve_mcp(self.cfg, level=clearance, writable=writable)
        t0 = time.perf_counter()
        try:
            results = await mcp_session_calls(endpoint, [(tool, arguments)])
        except Exception as e:                                    # noqa: BLE001
            return _err(502, f"调用失败：{_mcp_error_text(e)}")
        res = dict(results[0])
        text = _content_text(res)
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        self._audit(request, "tool", "tool.call", target=tool,
                    ok=not res.get("isError"),
                    detail=f"{elapsed}ms · 地址栏")
        if str(params.get("format") or "").strip().lower() in ("text", "plain", "txt"):
            return Response(text or "(空)", media_type="text/plain; charset=utf-8",
                            headers={"Cache-Control": "no-store"})
        return JSONResponse({
            "ok": not res.get("isError"),
            "tool": tool,
            "arguments": arguments,
            "elapsed_ms": elapsed,
            "text": text,
            "content": res.get("content") or [],
        })

    def _audit_rpc(self, request: Request, body: bytes, *, ok: bool) -> None:
        """从 JSON-RPC 请求体里认出「谁调了哪个工具」。

        只认 ``tools/call`` 与 ``initialize`` 两种：其余方法（ping / 通知 /
        tools/list）量大事小，记下来只会把日志淹掉。

        **刻意不记参数内容** —— 关键词、正文、标题一律不入库。审计要回答的是
        「谁动了什么」，把记忆正文抄进日志等于在别处复制了一份更疏于保护的数据。
        """
        if not body or len(body) > 65536:
            return
        try:
            msg = json.loads(body)
        except (TypeError, ValueError):
            return
        items = msg if isinstance(msg, list) else [msg]
        for item in items:
            if not isinstance(item, dict):
                continue
            method = str(item.get("method") or "")
            params = item.get("params") or {}
            if method == "tools/call":
                name = str(params.get("name") or "")
                if name:
                    self._audit(request, "tool", "tool.call", target=name,
                                ok=ok, detail="MCP 反代")
            elif method == "initialize":
                client = ""
                if isinstance(params, dict):
                    client = str((params.get("clientInfo") or {}).get("name") or "")
                self._audit(request, "tool", "mcp.connect", ok=ok,
                            detail=f"客户端 {client}" if client else "MCP 客户端接入")

    def _mcp_browse_card(self, request: Request) -> Response:
        """``/mcp`` 的**人类探测**降级报文：给人读，也当「令牌自证」用。

        回答三件事，不答第四件：

        1. 这个地址是什么（MCP 端点，不是网页）；
        2. 你手里这枚令牌是谁 —— 名称 / 前缀 / 角色 / 数据视野 / 读写 / 过期 /
           已用次数与剩余次数。这正是「令牌取不到值」缺的那一半信息：鉴权只
           回答「能不能进」，元数据要看令牌表。
        3. 正确的接法（header 与 ``?token=`` 两种，附一条可复制的 curl）。

        刻意**不回显令牌明文**：表里只有 sha256，物理上取不回来，假装能展示只会
        误导；要一串可用的新令牌就走控制台「访问 → 令牌」签发或重发。
        """
        via = getattr(request.state, "auth_via", "") or ""
        role = getattr(request.state, "auth_role", "") or ""
        clearance = getattr(request.state, "auth_clearance", "") or ""
        writable = getattr(request.state, "auth_writable", True) is not False

        token_info: dict | None = None
        hit = getattr(request.state, "auth_token", None) or None
        if via == "token" and hit:
            rec: dict | None = None
            try:
                rec = self.cfg["tokens"].describe(str(hit.get("id") or ""))
            except Exception:            # 纯展示路径：读失败不该把探测请求也打挂
                rec = None
            rec = rec or {}
            exp = rec.get("expires_at")
            try:
                left = int(float(exp) - time.time()) if exp else None
            except (TypeError, ValueError):
                left = None
            max_uses = int(rec.get("max_uses") or 0)
            uses = int(rec.get("uses") or 0)
            token_info = {
                "name": rec.get("name") or hit.get("name") or "",
                "prefix": rec.get("prefix") or "",
                "owner": rec.get("owner") or hit.get("owner") or "",
                "role": rec.get("role") or hit.get("role") or role,
                "clearance": rec.get("clearance") or hit.get("clearance") or clearance,
                "access": rec.get("access") or hit.get("access")
                          or ("rw" if writable else "ro"),
                "expires_at": exp,
                "expires_in": left,
                "max_uses": max_uses,
                "uses": uses,
                "uses_left": (max(0, max_uses - uses) if max_uses else None),
                "last_used_at": rec.get("last_used_at"),
            }

        base = _public_base(request, self.cfg) or ""
        endpoint = f"{base}{MCP_PROXY_PATH}" if base else str(request.url.path)
        payload = {
            "ok": True,
            "kind": "mcp-streamable-http",
            "message": ("这是记忆库的 MCP 端点。浏览器 / 普通 HTTP 工具打开时只会看到"
                        "这段说明 —— 完整调用要由 MCP 客户端完成：POST 一条 "
                        "JSON-RPC 消息，Accept 同时带上 application/json 与 "
                        "text/event-stream。想直接在地址栏查库，加 tool= 走只读调用"
                        "（见 how_to.readonly_call），写操作永远不开放 GET。"),
            "auth": {
                "via": via or "open-mode",
                "user": getattr(request.state, "auth_user", "") or "",
                "role": role,
                "clearance": clearance,
                "access": "rw" if writable else "ro",
            },
            "token": token_info,
            "token_note": ("明文只在签发那一刻返回过一次，令牌表里只有 sha256，故此处"
                           "无法回显。需要一串可用的新令牌：控制台 →「访问 → 令牌」"
                           "签发（或在对应行点「重发」）。"),
            "how_to": {
                "endpoint": endpoint,
                "transport": "streamable-http",
                "headers": {
                    "Authorization": "Bearer <令牌明文>",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                "token_in_query": ("也支持把 ?token=<令牌明文> 拼在 URL 上（给只让填一个"
                                   "URL 的客户端用）；代价是令牌会进访问日志与浏览器"
                                   "历史，公网入口能配 header 就别用这条。"),
                "readonly_call": {
                    "desc": ("地址栏直接跑**只读**工具：把 ?tool=<工具名> 拼在同一个 URL 上，"
                             "其余查询参数即工具参数（按字符串传）。写工具在这里一律 403。"),
                    "example": f"{endpoint}?token=<令牌明文>&tool=memory_search&keyword=令牌",
                    "typed_args": ("需要数字 / 布尔 / 嵌套时用 args=<URL 编码的 JSON>："
                                   f"{endpoint}?token=<令牌明文>&tool=memory_search"
                                   "&args=%7B%22keyword%22%3A%22%E4%BB%A4%E7%89%8C%22%2C%22limit%22%3A5%7D"),
                    "plain_text": "再加 &format=text 回纯文本（手机浏览器最省事）",
                    "tools": sorted(GET_READONLY_TOOLS),
                },
                "curl": (
                    f"curl -N -X POST '{endpoint}' "
                    "-H 'Authorization: Bearer <令牌明文>' "
                    "-H 'Accept: application/json, text/event-stream' "
                    "-H 'Content-Type: application/json' "
                    "-d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\","
                    "\"params\":{\"protocolVersion\":\"2024-11-05\","
                    "\"capabilities\":{},\"clientInfo\":{\"name\":\"probe\","
                    "\"version\":\"1\"}}}'"),
            },
            "docs": "完整的客户端接法见控制台「访问 → 令牌」签发后的连接串卡片。",
        }
        return Response(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            status_code=200,
            media_type="application/json; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    # -------- 静态页面 --------
    async def index(self, request: Request) -> Response:
        return FileResponse(self.cfg["static"] / "index.html",
                            headers={"Cache-Control": "no-store"})

    async def index_or_404(self, request: Request) -> Response:
        """catch-all：机器接口前缀回 404 JSON，其余回落首页。

        2026-10-26：此前 catch-all 对所有未知路径一律回 ``index.html``，
        于是 ``GET /mcp/reader``、``GET /.well-known/oauth-*`` 的响应是
        ``200 text/html`` —— 对浏览器无感，对 MCP / OAuth 客户端就是「解析
        失败但状态码成功」，现场表现为「网页 AI 连不上，服务端日志却一片绿」。

        为什么复用 ``_err()`` 的形状（``{"ok": false, "error": ...}``）：前端
        ``core/util.js`` 的 fetch 包装本就把非 2xx 当 ``ok:false``，两类错误
        同形，页面不会因为拿到 HTML 而抛 ``Unexpected token '<'``。

        为什么只认前缀、不认「有没有 Accept: text/html」：Accept 可以伪造，
        而路径前缀是确定的。按前缀分流，判据只有一处、可被测试直接引用。

        ⚠️ 这里**不得**出现任何写盘或转发上游的动作 —— 它接的是任意未知
        路径，任何副作用都等于给陌生人开一个入口。
        """
        rel = request.url.path.lstrip("/")
        if rel.startswith(MACHINE_PATH_PREFIXES):
            return _err(404, f"未知接口：/{rel}")
        return await self.index(request)


#: **只有 admin 能碰的写接口**（2026-10-26 主人指令：可修改的配置也要按角色收口）。
#:
#: 为什么放在中间件而不是逐个处理器里：这些接口此前**一条角色判定都没有** ——
#: 任何登录账号（含只读）都能改阈值、改连接、触发更新与重启。逐个补判定时
#: 只要漏一个，缺口就原样存在；集中在鉴权层做，新增写接口登记一行就自动受保护。
#:
#: 刻意只收「改机器行为」的那几个：`/api/password` 是改**自己**的密码（人人该有）、
#: `/api/call` 由工具组权限管（viewer 只能调只读组）、`/api/update` 的 GET 只是查。
#: 键是 ``(方法, 路径)``，路径按 ``rstrip("/")`` 归一后再比。
ADMIN_ONLY = frozenset({
    ("POST", "/api/config"),
    ("POST", "/api/thresholds"),
    ("POST", "/api/fns/probe"),
    ("POST", "/api/update"),
    ("POST", "/api/update/restart"),
})


class AuthMiddleware(BaseHTTPMiddleware):
    """``/api/*`` 的鉴权：Bearer 令牌 **或** 登录会话 Cookie，任一有效即放行。

    两条通道并存是刻意的：
      · **令牌走 header**，给脚本、curl、MCP 客户端用 —— 无状态、不依赖 Cookie；
      · **会话走 Cookie**，给浏览器用 —— ``HttpOnly``，页面 JS 读不到，XSS 也偷不走
        （这正是它比「把 token 放 sessionStorage」强的地方）。

    ``/api/login``、``/api/logout``、``/api/session`` 不校验：前两个是登录入口本身，
    第三个要能在**未登录时**回答「现在什么状态、该不该弹登录框」。

    静态资源始终不校验（里面没有秘密）。任何人能打开界面，但未登录时只看得到
    登录框 —— 数据一律在 ``/api/*`` 后面。
    """

#: 免鉴权的 API 路径。**精确匹配**而非前缀匹配 —— 否则 `/api/sessionXXX`
#: 这类路径会白拿一张免死金牌。
    PUBLIC = ("/api/login", "/api/logout", "/api/session",
              # OAuth 面（2026-10-26）：这五个端点**必须在鉴权之前**可达 ——
              # 客户端正是「没有凭据」才来走这条路的。授权页自己的身份判断
              # （Cookie 会话 / 表单账号口令）在处理器内部完成。
              "/.well-known/oauth-protected-resource",
              "/.well-known/oauth-authorization-server",
              "/oauth/register", "/oauth/authorize", "/oauth/token")
    def __init__(self, app, cfg: dict, header: str = "Authorization"):
        super().__init__(app)
        self.cfg = cfg
        self.header = header

    def _bearer(self, request: Request) -> str:
        """兼容旧调用点：令牌的三个来源统一由模块级 ``token_from_request`` 决定。"""
        return token_from_request(request)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # 内部端点（网关回调）不在 /api/ 前缀下，由处理器自己验 X-Internal-Key。
        # 必须在这里直接放行，否则网关永远过不了鉴权 —— 它手里没有用户 Cookie。
        if path == INTERNAL_VERIFY_PATH:
            return await call_next(request)
        # 2026-10-22：``/mcp`` 反代与 ``/api/*`` 同一口径 —— 它会把全部工具
        # 暴露给调用方，宽松度不能比 API 更高。注意本中间件只在「有 token 或
        # 开了账号登录」时才被挂上；本机回环无鉴权形态压根没有这一层。
        if not (path.startswith("/api/") or path.rstrip("/") == MCP_PROXY_PATH):
            return await call_next(request)
        if request.method == "OPTIONS":
            return Response(status_code=204)
        if path.rstrip("/") in self.PUBLIC:
            return await call_next(request)

        via, user, role, clearance, access = "", "", "", "", ""
        supplied = self._bearer(request)
        hit: dict | None = None
        # 两条通道都走**恒定时间比较**：令牌在 TokenStore 里用 compare_digest 逐个比，
        # 会话靠签名校验（read_session 内部同样是 compare_digest）。
        if supplied:
            hit = self.cfg["tokens"].verify(supplied)
            if hit:
                via = "token"
                user = str(hit.get("owner") or "")
                role = str(hit.get("role") or "viewer")
                clearance = str(hit.get("clearance") or "")
                access = str(hit.get("access") or "")
        if not via and self.cfg["session_key"]:
            sess = web_auth.read_session(
                request.cookies.get(web_auth.COOKIE_NAME, ""), self.cfg["session_key"])
            if sess:
                live = self.cfg["users"].session_valid(
                    str(sess.get("u") or ""), str(sess.get("e") or ""))
                if live:
                    via = "session"
                    user = live["name"]
                    role = live["role"]
        if not via:
            # 401 的**原因只在这一处可判**：返回之后，下游只剩「未授权」三个字，
            # 而令牌过期 / 次数耗尽 / 已吊销 / 从未送达在报文上逐字节相同。
            # 刻意只记分类，不记凭据片段 —— 令牌明文与前缀、Cookie、
            # Authorization 头一律不落日志（2026-10-26 指令）。
            # 细分到上面那四种原因需要 TokenStore.verify 回传理由，属 API
            # 变更，另行评审；本轮只做「有没有送、送来了认不认」。
            if supplied:
                reason = "token_rejected"
            elif request.cookies.get(web_auth.COOKIE_NAME):
                reason = "session_stale"
            else:
                reason = "no_credential"
            logger.info("鉴权失败：%s %s（reason=%s，ip=%s）",
                        request.method, request.url.path, reason,
                        _client_ip(request))
            # 拒绝也要进卡片：主人要的「谁什么时候干了什么」里，
            # 「谁试过但没进去」和「谁进去了」同等重要。
            try:
                self.cfg["audit"].append({
                    "kind": "access", "action": "auth.denied",
                    "ip": _client_ip(request), "ok": False,
                    "target": path, "detail": f"{request.method} {path} · {reason}",
                })
            except Exception:                                # noqa: BLE001
                pass
            resp = _err(401, "未授权：请登录，或在请求头里带上访问令牌。",
                        auth_required=True)
            # MCP Authorization（2026-10-26）：**没有这个响应头，网页型客户端
            # 永远不会去发起授权** —— 它靠 401 的 WWW-Authenticate 才知道
            # 该读哪份受保护资源元数据、该向哪个授权服务器要令牌。
            base = _public_base(request, self.cfg)
            if base and self.cfg.get("oauth_enabled"):
                resp.headers["WWW-Authenticate"] = (
                    'Bearer resource_metadata="'
                    f'{base}/.well-known/oauth-protected-resource"')
            return resp
        request.state.auth_via = via
        request.state.auth_user = user
        request.state.auth_role = role
        # 令牌命中记录（含 id / prefix 之外的元数据入口）：供 /mcp 的浏览器降级
        # 报文自证「这枚令牌是谁、还能用几次」。**明文不在里面**（只有 sha256）。
        request.state.auth_token = hit if via == "token" else None
        # 数据视野（2026-10-26）：令牌自带就用它，会话路径则按角色推导。
        # 它是**这条连接能看见哪些密级记忆**的唯一依据，供 /api/call 与 /mcp
        # 反代选端点；没有它，令牌只在「工具粒度」上生效，数据粒度仍全开。
        request.state.auth_clearance = (
            clearance if clearance in web_store.CLEARANCE_RANK
            else web_store.clearance_of(role))
        # 读写模式（2026-10-26）：与视野正交的第二根轴。同样是「令牌自带就用它，
        # 会话路径则按角色推导」。供 /api/call 决定是否放行写工具，并供 /mcp 反代
        # 选 `/mcp/<档位>-ro` 端点 —— 后者才是硬边界。
        request.state.auth_writable = (
            web_store.access_of(role, access) == "rw")
        # 管理员专属写接口：非 admin 一律 403。放在这里是**唯一收口点** ——
        # 见 ADMIN_ONLY 上方的注释（此前这些接口没有任何角色判定）。
        if role != "admin" and (request.method.upper(), path.rstrip("/")) in ADMIN_ONLY:
            return _err(403, "只有管理员可以修改配置。")
        return await call_next(request)


class _NoCacheStatic(StaticFiles):
    """静态资源强制回源校验。

    `StaticFiles` 默认只发 ETag / Last-Modified，**不发 Cache-Control** ——
    浏览器于是对 /assets 走「启发式缓存」，改了 js/css 后仍可能拿旧文件，
    界面上看起来就是「新功能怎么没有？」（2026-10-20 主人踩过一次）。
    这里统一补 `no-cache`：语义是「可以存，但每次必须回来验一下」——
    没改就是 304（照样快），改了立刻生效，不牺牲任何性能。
    """

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def create_app(cfg: dict | None = None) -> Starlette:
    # 幂等；必须在任何 logger.* 之前生效，否则前几条 INFO 会被 lastResort 丢掉。
    _ensure_app_logging()
    cfg = cfg or config()
    console = WebConsole(cfg)

    routes = [
        # 认证面（2026-10-21）：这三个在 AuthMiddleware 里免鉴权
        Route("/api/session", console.session, methods=["GET"]),
        Route("/api/login", console.login, methods=["POST"]),
        Route("/api/logout", console.logout, methods=["POST"]),
        Route("/api/health", console.health, methods=["GET"]),
        Route("/api/tools", console.tools, methods=["GET"]),
        Route("/api/overview", console.overview, methods=["GET"]),
        Route("/api/activity", console.activity, methods=["GET"]),
        Route("/api/call", console.call, methods=["POST"]),
        Route("/api/config", console.config_get, methods=["GET"]),
        Route("/api/config", console.config_post, methods=["POST"]),
        Route("/api/fns/probe", console.fns_probe, methods=["POST"]),
        Route("/api/thresholds", console.thresholds_get, methods=["GET"]),
        Route("/api/thresholds", console.thresholds_post, methods=["POST"]),
        # 更新面（2026-10-15）：白名单 = 后端运行时模块 + web/ 静态资源
        Route("/api/update", console.update_get, methods=["GET"]),
        Route("/api/update", console.update_post, methods=["POST"]),
        Route("/api/update/restart", console.restart, methods=["POST"]),
        # 管理面（2026-10-22）：用户与令牌。
        # 注意 /api/password 是「改自己的」，其余都要 admin。
        Route("/api/password", console.password_post, methods=["POST"]),
        Route("/api/users", console.users_get, methods=["GET"]),
        Route("/api/users", console.users_post, methods=["POST"]),
        Route("/api/users/{name}", console.user_patch, methods=["PATCH"]),
        Route("/api/users/{name}", console.user_delete, methods=["DELETE"]),
        Route("/api/tokens", console.tokens_get, methods=["GET"]),
        Route("/api/tokens", console.tokens_post, methods=["POST"]),
        Route("/api/tokens/{tid}", console.token_delete, methods=["DELETE"]),
        # 访问日志（2026-10-27）：只读接口，但处理器内部卡 admin（见 audit_get）。
        Route("/api/audit", console.audit_get, methods=["GET"]),
        # 导出（2026-10-27）：同样卡 admin；同一条路径按 format= 分流 csv / json。
        # 注意**顺序**：Starlette 按注册顺序匹配，`/api/audit` 是精确路径、
        # `/api/audit/export` 多一段，两者互不遮蔽；但仍把它紧挨着写字，
        # 是为了让「谁会读这个文件」一眼看全。
        Route("/api/audit/export", console.audit_export, methods=["GET"]),
        # OAuth 2.1 授权服务器（2026-10-26）。五个端点都在 AuthMiddleware.PUBLIC
        # 里放行 —— 它们服务的是「还没有凭据」的客户端。
        Route("/.well-known/oauth-protected-resource", console.oauth_prm,
              methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", console.oauth_as,
              methods=["GET"]),
        Route("/oauth/register", console.oauth_register, methods=["POST"]),
        Route("/oauth/authorize", console.oauth_authorize_get, methods=["GET"]),
        Route("/oauth/authorize", console.oauth_authorize_post, methods=["POST"]),
        Route("/oauth/token", console.oauth_token, methods=["POST"]),
        # 网关回调（不在 /api/ 前缀，鉴权中间件直接放行，处理器自己验内部密钥）
        Route(INTERNAL_VERIFY_PATH, console.internal_verify, methods=["GET"]),
        Route(FNS_CONFIG_PATH, console.internal_fns_config, methods=["GET"]),
        # MCP 反代（2026-10-22）：**必须**排在最末那条 catch-all 之前，
        # 否则 /mcp 会被前端 index.html 吃掉，表现为「MCP 客户端收到的是一坨 HTML」。
        Route(MCP_PROXY_PATH, console.mcp_proxy,
              methods=["GET", "POST", "DELETE", "OPTIONS"]),
        Mount("/assets", app=_NoCacheStatic(directory=str(cfg["static"])), name="assets"),
        Route("/", console.index),
        # 前端用 hash 路由 ⇒ 页面路径恒为 "/"；catch-all 只服务「手输的深路径」
        # 与**机器接口的未知路径**。后者必须回 404 JSON（见 MACHINE_PATH_PREFIXES），
        # 否则 MCP / OAuth 客户端会拿到 200 + HTML（2026-10-26 实测）。
        Route("/{path:path}", console.index_or_404),
    ]

    middleware: list[Middleware] = []
    if cfg["allowed_hosts"]:
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        middleware.append(Middleware(TrustedHostMiddleware,
                                     allowed_hosts=cfg["allowed_hosts"]))
    # 只要「配了 token」**或**「开了账号登录」，就必须挂鉴权中间件 ——
    # 早期版本只看 token，导致「只开登录、不配 token」时中间件根本不装配，
    # 会话 Cookie 也就没人校验（等于全放行）。
    if cfg["auth_enabled"] or cfg["login_enabled"]:
        middleware.append(Middleware(AuthMiddleware, cfg=cfg))

    return Starlette(routes=routes, middleware=middleware, debug=False)


__all__ = [
    "WEB_VERSION", "DEFAULT_WEB_HOST", "DEFAULT_WEB_PORT", "DEFAULT_MCP_URL",
    "WebConfigError", "config", "describe", "create_app", "WebConsole",
    "is_loopback", "static_dir", "config_path",
    "load_app_config", "save_app_config", "resolve_mcp", "resolve_vault",
    "thresholds_state", "write_thresholds",
    "mcp_health", "mcp_tools", "mcp_session_calls",
    "TOOL_GROUPS", "TOOL_GROUP_OTHER",
    "UPDATE_PATHS", "UPDATE_BACKEND_FILES", "UPDATE_FRONTEND_DIR",
    "update_root", "restarter_path", "update_status", "update_check",
    "update_apply", "update_restart",
]
