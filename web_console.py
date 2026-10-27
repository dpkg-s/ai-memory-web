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

import hmac
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
from urllib.parse import quote, urlencode

import anyio
import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import (FileResponse, JSONResponse, Response,
                                StreamingResponse)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# 同目录模块（非第三方）。2026-10-21：账号登录与会话签名。
# 只用标准库实现，不给 requirements.txt 加任何依赖 —— 见 web_auth.py 顶部取舍说明。
# 2026-10-22：web_store 承载用户表与令牌表（多用户 + 可吊销令牌）。
import web_auth
import web_store

logger = logging.getLogger("ai-memory.web")

WEB_VERSION = "1.11.3"
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
_FNS_FIELDS = ("server", "account", "vault", "token", "exclude")
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
        "multi_user": multi_user,
        "internal_key": internal_key,
        "mcp": mcp,
        "allowed_hosts": allowed_hosts,
        "static": static,
        "config_path": config_path(),
        "config_write": _env_bool("AI_MEMORY_WEB_CONFIG_WRITE", DEFAULT_CONFIG_WRITE),
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
        for k in _FNS_FIELDS:
            v = fns.get(k, "")
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


def resolve_mcp(cfg: dict | None = None) -> str:
    """MCP 端点：JSON 配置里的值优先（前端可改），否则用环境变量默认。"""
    cfg = cfg or config()
    app_cfg = load_app_config()
    return app_cfg.get("mcp_endpoint") or cfg["mcp"]


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


def _client_ip(request: Request) -> str:
    """限流用的来源标识。

    **只认 TCP 对端，不认 ``X-Forwarded-For``**：这个控制台前面没有反向代理
    （8811 直连），而 XFF 是客户端可以任意伪造的 —— 采信它等于给攻击者一个
    「每试一次换个 IP」的开关，限流当场失效。将来真上了反代，应改成
    「只信任来自反代地址的 XFF」，而不是无条件读。
    """
    return request.client.host if request.client else "?"


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
        return JSONResponse({"ok": True, "app": saved,
                             "resolved": {"mcp_endpoint": resolve_mcp(self.cfg)}})

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
        return JSONResponse({"ok": True, **state})

    # -------- 调试台 --------
    async def call(self, request: Request) -> Response:
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
            return _err(403, f"角色 {role} 无权调用 {tool}（属于「{grp}」组）。")
        arguments = body.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _err(400, "arguments 必须是 JSON 对象。")

        endpoint = resolve_mcp(self.cfg)
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
            msg = "用户名或口令不正确。"
            if left:
                msg += f" 已连续失败，请 {left} 秒后再试。"
            return _err(401, msg, locked_for=left or 0)
        self._limiter.reset(ip)
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

    async def logout(self, request: Request) -> Response:
        """清除会话 Cookie。

        **不校验登录态**：登出必须永远成功。若要求先认证，那么「会话已过期但
        页面还挂着」时用户点登出会收到 401，比登不出去更让人困惑。
        """
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(web_auth.COOKIE_NAME, path="/")
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
        if supplied:
            hit = cfg["tokens"].verify(supplied)
            if hit:
                mode, user, role = "token", str(hit.get("owner") or ""), str(hit.get("role") or "")
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
        return JSONResponse({"ok": True})

    async def tokens_get(self, request: Request) -> Response:
        """管理员看全部，其他人只看自己的。"""
        if self._is_open_mode():
            return JSONResponse({"ok": True, "tokens": self.cfg["tokens"].list(),
                                 "self_only": False})
        role = getattr(request.state, "auth_role", "") or ""
        user = self._actor(request)
        rows = self.cfg["tokens"].list() if role == "admin" else self.cfg["tokens"].list(owner=user)
        return JSONResponse({"ok": True, "tokens": rows,
                             "self_only": role != "admin",
                             "max_expires": 365 * 86400})

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
                expires_in=(int(expires_in) if expires_in not in (None, "", 0) else None),
                max_uses=int(body.get("max_uses") or 0))
        except (web_store.StoreError, TypeError, ValueError) as e:
            return _err(400, str(e))
        logger.warning("令牌已签发：%s（owner=%s，role=%s，次数=%s，操作人=%s）",
                       rec["name"], rec["owner"], rec["role"],
                       rec["max_uses"] or "不限", actor)
        return JSONResponse({"ok": True, "token": plain, "record": rec,
                             "note": "这串明文只显示这一次，关闭后无法再取回；表里只存 sha256。"})

    async def token_delete(self, request: Request) -> Response:
        tid = str(request.path_params.get("tid") or "")
        actor = self._actor(request)
        role = getattr(request.state, "auth_role", "") or "admin"
        try:
            self.cfg["tokens"].revoke(tid, owner=(None if role == "admin" else actor))
        except web_store.StoreError as e:
            return _err(400, str(e))
        logger.warning("令牌已吊销：%s（操作人=%s）", tid, actor or "open-mode")
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
        target = resolve_mcp(self.cfg)
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

    # -------- 静态页面 --------
    async def index(self, request: Request) -> Response:
        return FileResponse(self.cfg["static"] / "index.html",
                            headers={"Cache-Control": "no-store"})


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
    PUBLIC = ("/api/login", "/api/logout", "/api/session")

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

        via, user, role = "", "", ""
        supplied = self._bearer(request)
        # 两条通道都走**恒定时间比较**：令牌在 TokenStore 里用 compare_digest 逐个比，
        # 会话靠签名校验（read_session 内部同样是 compare_digest）。
        if supplied:
            hit = self.cfg["tokens"].verify(supplied)
            if hit:
                via = "token"
                user = str(hit.get("owner") or "")
                role = str(hit.get("role") or "viewer")
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
            return _err(401, "未授权：请登录，或在请求头里带上访问令牌。",
                        auth_required=True)
        request.state.auth_via = via
        request.state.auth_user = user
        request.state.auth_role = role
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
        # 网关回调（不在 /api/ 前缀，鉴权中间件直接放行，处理器自己验内部密钥）
        Route(INTERNAL_VERIFY_PATH, console.internal_verify, methods=["GET"]),
        # MCP 反代（2026-10-22）：**必须**排在最末那条 catch-all 之前，
        # 否则 /mcp 会被前端 index.html 吃掉，表现为「MCP 客户端收到的是一坨 HTML」。
        Route(MCP_PROXY_PATH, console.mcp_proxy,
              methods=["GET", "POST", "DELETE", "OPTIONS"]),
        Mount("/assets", app=_NoCacheStatic(directory=str(cfg["static"])), name="assets"),
        Route("/", console.index),
        Route("/{path:path}", console.index),      # 前端用 hash 路由，任何路径都回 index
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
