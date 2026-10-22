#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ai-memory Web 控制台入口（v3.1，2026-10-13）。

用法
----
::

    python serve_web.py                 # 控制台 http://127.0.0.1:8811/
    python serve_web.py --with-mcp --core-dir <核心仓目录>
                                        # 顺带把 MCP HTTP 端点拉起来（配对进程）
    AI_MEMORY_WEB_PORT=8811 python serve_web.py

    # 局域网（必须给 token，否则拒绝启动）
    AI_MEMORY_WEB_HOST=0.0.0.0 AI_MEMORY_WEB_TOKEN=xxxx python serve_web.py

架构
----
两个进程、职责分离：

    浏览器 ──同源 fetch──▶ serve_web.py（本文件：控制台）
                              │ 后端代理（MCP 客户端，不带 Origin）
                              ▼
                        serve_http.py（ai-memory MCP 端点，唯一写者）

控制台**不 import server**：它对记忆库的一切读写都走 MCP 协议 ⇒ 天然满足 v3 的
两条判死项（不直连 vault、不进程内直调）。--with-mcp 只是把 serve_http.py 作为
**子进程**拉起，仍然是进程间调用，不破坏分层。

🔴 本文件**也不 import 核心仓的任何模块**（2026-10-16）：曾经这里 import 了一个
``core_path``，靠它上溯定位核心目录并注入 ``sys.path``，本仓才 import 得到
``memory_config`` / ``transport_http``。那条通道已整体拆除 —— 阈值改走 MCP 工具
``memory_config``，端点默认地址改成本仓字面常量。现在核心仓目录**只在 ``--with-mcp``
时需要**：用来找到 ``serve_http.py`` 这个入口文件，且必须**显式**给出（``--core-dir``
或 ``AI_MEMORY_CORE_DIR``），不再靠上溯猜。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import web_console  # noqa: E402  （装配层：starlette 应用 + MCP 代理 + 配置面）


def _core_entry(core_dir: str | None) -> Path | None:
    """定位核心仓里的 MCP 端点入口 ``serve_http.py``（仅 ``--with-mcp`` 需要）。

    **刻意不自动上溯**：本仓完全可以被单独克隆出来而不挂在核心仓里，猜出来的路径
    一旦猜错，后面的报错会指向一个无关的文件。唯一的说法是显式给出目录。
    """
    raw = (core_dir or os.environ.get("AI_MEMORY_CORE_DIR") or "").strip()
    if not raw:
        print("[web] --with-mcp 需要显式指定核心仓目录（含 serve_http.py）：\n"
              "      --core-dir D:\\path\\to\\ai-memory-template\n"
              "      或   set AI_MEMORY_CORE_DIR=D:\\path\\to\\ai-memory-template",
              file=sys.stderr)
        return None
    entry = Path(raw).expanduser() / "serve_http.py"
    if not entry.is_file():
        print(f"[web] {raw} 下找不到 serve_http.py，无法启动 MCP 端点。",
              file=sys.stderr)
        return None
    return entry


def _spawn_mcp(url: str, core_dir: str | None) -> subprocess.Popen | None:
    """把 ai-memory MCP HTTP 端点作为子进程拉起（仅 --with-mcp 时）。"""
    parsed = urlparse(url)
    host = parsed.hostname or web_console.DEFAULT_WEB_HOST
    port = str(parsed.port or 8700)
    path = parsed.path or "/mcp"
    entry = _core_entry(core_dir)
    if entry is None:
        return None

    env = dict(os.environ)
    env["AI_MEMORY_TRANSPORT"] = "http"
    env["AI_MEMORY_HTTP_HOST"] = host
    env["AI_MEMORY_HTTP_PORT"] = port
    env["AI_MEMORY_HTTP_PATH"] = path
    if not web_console.is_loopback(host) and not env.get(
            "AI_MEMORY_HTTP_ALLOWED_HOSTS"):
        print(f"[web] 提示：MCP 端点监听 {host!r}（非回环）却未设 "
              f"AI_MEMORY_HTTP_ALLOWED_HOSTS ⇒ 子进程会按设计拒绝启动。\n"
              f'      请补：AI_MEMORY_HTTP_ALLOWED_HOSTS="{host}:{port},localhost:{port}"',
              file=sys.stderr)

    print(f"[web] 启动 MCP 端点子进程：python serve_http.py  "
          f"({host}:{port}{path})")
    try:
        # cwd 落在 `serve_http.py` 旁边（核心目录），与拆分前的行为等价：
        # 被执行的脚本会把「自己所在目录」放进 sys.path[0]，故 server.py 等
        # 同级模块照常可导入。
        return subprocess.Popen([sys.executable, str(entry)],
                                cwd=str(entry.parent), env=env)
    except OSError as e:
        print(f"[web] 启动 MCP 子进程失败：{e}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="serve_web.py",
        description="ai-memory Web 控制台（v3.1）：调试台 + 配置面")
    ap.add_argument("--host", help="监听地址（默认环境变量 AI_MEMORY_WEB_HOST 或 127.0.0.1）")
    ap.add_argument("--port", type=int, help="监听端口（默认 8800）")
    ap.add_argument("--mcp", help="上游 MCP 端点 URL（默认 http://127.0.0.1:8700/mcp）")
    ap.add_argument("--with-mcp", action="store_true",
                    help="同时以子进程启动 serve_http.py（本机单机试用最省事）")
    ap.add_argument("--core-dir",
                    help="核心仓目录（含 serve_http.py）；仅 --with-mcp 需要，"
                         "也可用环境变量 AI_MEMORY_CORE_DIR")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    ap.add_argument("--check", action="store_true",
                    help="只做配置校验并打印摘要，不起服务（用于自检 / CI）")
    args = ap.parse_args(argv)

    if args.host:
        os.environ["AI_MEMORY_WEB_HOST"] = args.host
    if args.port:
        os.environ["AI_MEMORY_WEB_PORT"] = str(args.port)
    if args.mcp:
        os.environ["AI_MEMORY_WEB_MCP"] = args.mcp

    try:
        cfg = web_console.config()
    except web_console.WebConfigError as e:
        print(f"[web] 配置错误：{e}", file=sys.stderr)
        return 2

    print(f"[web] ai-memory 控制台 v{web_console.WEB_VERSION}")
    print(f"[web] {web_console.describe(cfg)}")
    if cfg["config_write"]:
        print("[web] 阈值写入：开启（仅写 vault 根的 memory.toml，绝不触碰 *.md）")
    else:
        print("[web] 阈值写入：关闭（只读模式）")
    # 提示语要跟真实的两道认证对齐（2026-10-22）：只判 auth_enabled（token）会把
    # 「0.0.0.0 + 账号登录」的容器误说成「仅回环可访问」，恰好与事实相反。
    if not cfg["auth_enabled"] and not cfg["login_enabled"]:
        print("[web] 未设 token 也未开登录：仅回环可访问；"
              "要暴露到局域网请设 AI_MEMORY_WEB_TOKEN 或账号登录")
    elif not cfg["auth_enabled"]:
        print("[web] 未设 token：/api/* 由账号登录（Cookie 会话）保护；"
              "给脚本调用再加 AI_MEMORY_WEB_TOKEN")
    if args.check:
        return 0

    child = _spawn_mcp(cfg["mcp"], args.core_dir) if args.with_mcp else None
    url = f"http://{cfg['host']}:{cfg['port']}/"
    if args.open:
        try:
            webbrowser.open(url)
        except Exception:                                         # noqa: BLE001
            pass

    try:
        import uvicorn
    except ImportError:
        if child is not None:
            child.terminate()
        print("[web] 缺少 uvicorn（mcp 的传递依赖，正常安装 mcp 即自带）。",
              file=sys.stderr)
        return 3

    try:
        uvicorn.run(web_console.create_app(cfg), host=cfg["host"],
                    port=cfg["port"], log_level="info")
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
