#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ai-memory Web 控制台测试（v3.1，2026-10-13）。

覆盖：
  A  配置校验 / fail-fast（`serve_web.py --check` 的**进程级退出码**，不是看文案）
  B  前端静态资源完整性（挂载点 + 本地 vendor 三件 + app/style 非空）
  C  分层：导入控制台**不得**把 server 拉进 sys.modules（v3 判死项「不进程内直调」），
     且**不得**把核心仓任何模块（memory_config / transport_http）拉进来（2026-10-16
     拆掉跨仓 import 通道后的新不变量）
  D  鉴权中间件（httpx ASGI transport，无需端口）：无 token 401 / Bearer /
     X-Auth-Token / 静态资源不校验 / OPTIONS 204
  E  写保护：AI_MEMORY_WEB_CONFIG_WRITE=0 ⇒ POST /api/thresholds 被拒（400）
  F  端到端（真起 serve_http + serve_web）：health / tools(27) / overview /
     thresholds(8 键) / index 回落 / assets 可达 / /api/call 真往返 / 阈值写读往返
  H  更新面（2026-10-15 建立；2026-10-16 扩为 web + core 双目标）：白名单安全边界 /
     行首状态位回归 / 三点 diff 语义 / restarter 与 AI_MEMORY_CORE_DIR 的显式失败
     （H1~H10 静态，F11~F11d 走真服务）

运行:
    python tests/test_web.py       # 退出码 0=全绿, 1=有失败
依赖:
    需在装有 mcp 的 venv 里跑（starlette / uvicorn / httpx / anyio 全是 mcp 的
    传递依赖，零新增）。全程把 AI_MEMORY_DIR 指向临时目录，绝不触碰真实记忆库。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---- 先把 MEMORY_DIR 指到临时目录, 再 import 被测模块 -------------------
_TMP = Path(tempfile.mkdtemp(prefix="ai-memory-web-"))
os.environ["AI_MEMORY_DIR"] = str(_TMP / "vault")
(_TMP / "vault").mkdir(parents=True, exist_ok=True)
_VAULT = _TMP / "vault"
for _n in ["笔记A", "笔记B", "笔记C"]:
    (_VAULT / f"{_n}.md").write_text(
        "---\n"
        f"title: {_n}\ntags: [test]\ntype: project\ntier: warm\n"
        "created: 2026-10-13 10:00\nupdated: 2026-10-13 10:00\n"
        "confidence: high\nverified: true\n---\n\n"
        f"# {_n}\n\n这是 {_n}。\n\n- 列表项\n- **加粗**\n",
        encoding="utf-8", newline="\n")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import web_console  # noqa: E402

# 核心仓目录：端到端段要真起 serve_http.py（它属于核心仓，不在本仓）。
# 2026-10-16 起本仓**不再有**自动上溯逻辑（那是已删除的 core_path.py 的职责），
# 故这里由测试自己解析：显式 AI_MEMORY_CORE_DIR > submodule 布局（本仓的上一级）。
# 两者都不成立时**大声退出** —— 端到端段是本文件的主要价值，静默跳过比失败更糟。
_CORE = None
_core_env = (os.environ.get("AI_MEMORY_CORE_DIR") or "").strip()
for _cand in ([Path(_core_env)] if _core_env else []) + [_ROOT.parent]:
    if (_cand / "server.py").is_file() and (_cand / "serve_http.py").is_file():
        _CORE = _cand.resolve()
        break
if _CORE is None:
    print("[F] 找不到核心仓（需含 server.py + serve_http.py）。\n"
          "    请把本仓作为 submodule 挂在 ai-memory-template 下，或设 "
          "AI_MEMORY_CORE_DIR 指向它。", file=sys.stderr)
    sys.exit(2)

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


_ENV_KEYS = ["AI_MEMORY_WEB_HOST", "AI_MEMORY_WEB_PORT", "AI_MEMORY_WEB_MCP",
             "AI_MEMORY_WEB_TOKEN", "AI_MEMORY_WEB_ALLOWED_HOSTS",
             "AI_MEMORY_WEB_CONFIG", "AI_MEMORY_WEB_CONFIG_WRITE",
             "AI_MEMORY_WEB_STATIC",
             # 账号登录：必须一并净化 —— 否则宿主机的 .env 会漏进「无认证」用例里，
             # 把 A3「裸奔 ⇒ 拒绝启动」测成放行。
             "AI_MEMORY_WEB_USER", "AI_MEMORY_WEB_PASSWORD",
             "AI_MEMORY_WEB_PASSWORD_HASH",
             "AI_MEMORY_WEB_USERS", "AI_MEMORY_WEB_TOKENS",
             # 审计（2026-10-27）：不净化就会写进宿主机的 ~/.ai-memory-web。
             "AI_MEMORY_WEB_AUDIT",
             # FNS 同步事件（2026-11-05）：同理，指向宿主机上的路径会让
             # 「无数据源」用例读到真实文件，测出来的结论是假的。
             "AI_MEMORY_WEB_FNS_LOG"]
_BASELINE = {k: os.environ.get(k) for k in _ENV_KEYS}


def _clean_env(**kw) -> dict:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)          # 净化：沙箱链会注入 shim 猴补丁
    for k in _ENV_KEYS:
        env.pop(k, None)
    env["AI_MEMORY_DIR"] = str(_VAULT)
    env["PYTHONUNBUFFERED"] = "1"
    env.update({k: str(v) for k, v in kw.items()})
    return env


def _check_rc(env: dict) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(_ROOT / "serve_web.py"), "--check"],
                       cwd=str(_ROOT), env=env, capture_output=True, timeout=90)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_port(port, secs=45) -> bool:
    t0 = time.time()
    while time.time() - t0 < secs:
        s = socket.socket()
        s.settimeout(2)
        try:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        finally:
            s.close()
        time.sleep(0.4)
    return False


# =====================================================================
section("A 配置校验 / fail-fast（进程级退出码）")
check("A1 is_loopback 判定",
      web_console.is_loopback("127.0.0.1") and web_console.is_loopback("localhost")
      and web_console.is_loopback("::1")
      and not web_console.is_loopback("0.0.0.0")
      and not web_console.is_loopback("192.168.1.5"), "")

rc, out = _check_rc(_clean_env())
check("A2 合法配置 --check 退出 0", rc == 0, f"rc={rc} out={out[-200:]}")

rc, out = _check_rc(_clean_env(AI_MEMORY_WEB_HOST="0.0.0.0"))
check("A3 非回环且无 token ⇒ 拒绝启动（rc=2）", rc == 2, f"rc={rc} out={out[-200:]}")

rc, out = _check_rc(_clean_env(AI_MEMORY_WEB_HOST="0.0.0.0",
                               AI_MEMORY_WEB_TOKEN="s3cret"))
check("A4 非回环 + token ⇒ 放行（rc=0）", rc == 0, f"rc={rc} out={out[-200:]}")

# ---- 容器标准形态：HOST=0.0.0.0 + 账号登录、不给 token（2026-10-22 补）--------
# v1.11.0 的镜像正是这个形态，但旧守卫只认 token ⇒ 容器启动即 exit 2。
# 这一组用例钉住「两道认证任一成立即放行」，同时确认初始 admin 真被落盘。
_ACC = _TMP / "acc"
_ACC.mkdir(exist_ok=True)
_ACC_ENV = dict(AI_MEMORY_WEB_HOST="0.0.0.0",
                AI_MEMORY_WEB_USER="admin",
                AI_MEMORY_WEB_PASSWORD="password",
                AI_MEMORY_WEB_CONFIG=str(_ACC / "config.json"),
                AI_MEMORY_WEB_USERS=str(_ACC / "users.json"),
                AI_MEMORY_WEB_TOKENS=str(_ACC / "tokens.json"))

rc, out = _check_rc(_clean_env(**_ACC_ENV))
check("A3b 非回环 + 账号登录（无 token）⇒ 放行（容器标准形态，rc=0）",
      rc == 0, f"rc={rc} out={out[-300:]}")

_users_file = _ACC / "users.json"
try:
    _users_txt = _users_file.read_text(encoding="utf-8")
except OSError:
    _users_txt = ""
check("A3c 首次启动把初始 admin 落盘（users.json 含 admin 且不含明文口令）",
      "admin" in _users_txt and "scrypt" in _users_txt.lower()
      and "password" not in _users_txt,
      f"exists={_users_file.is_file()} len={len(_users_txt)}")

# 二次启动：表里已有账号，不再重写（bootstrap 只在空表时建号）
_before = _users_txt
rc, out = _check_rc(_clean_env(**_ACC_ENV))
check("A3d 二次启动不重建账号（users.json 内容不变）",
      rc == 0 and _users_file.read_text(encoding="utf-8") == _before,
      f"rc={rc}")

rc, out = _check_rc(_clean_env(AI_MEMORY_WEB_HOST="0.0.0.0",
                               AI_MEMORY_WEB_USER="admin",
                               AI_MEMORY_WEB_CONFIG=str(_ACC / "c2.json"),
                               AI_MEMORY_WEB_USERS=str(_ACC / "u2.json"),
                               AI_MEMORY_WEB_TOKENS=str(_ACC / "t2.json")))
check("A3e 非回环 + 只给 USER（半配）⇒ 仍拒绝启动（rc=2）",
      rc == 2, f"rc={rc} out={out[-200:]}")

rc, out = _check_rc(_clean_env(AI_MEMORY_WEB_PORT="70000"))
check("A5 端口越界 ⇒ 拒绝启动（rc=2）", rc == 2, f"rc={rc}")

rc, out = _check_rc(_clean_env(AI_MEMORY_WEB_MCP="not-a-url"))
check("A6 MCP 端点非 http(s) ⇒ 拒绝启动（rc=2）", rc == 2, f"rc={rc}")

_empty = _TMP / "empty_static"
_empty.mkdir(exist_ok=True)
rc, out = _check_rc(_clean_env(AI_MEMORY_WEB_STATIC=str(_empty)))
check("A7 前端静态目录缺 index.html ⇒ 拒绝启动（rc=2）", rc == 2, f"rc={rc}")

# =====================================================================
section("B 前端静态资源完整性（本地化、零 CDN、零构建）")
_static = _ROOT / "web"
# ⚠️ 2026-10-15 前端重构后判据**重述**（不是放宽）：
#   · 入口由单文件 app.js 变为 js/main.js（import 图 30+ 模块）
#   · 样式由单文件 style.css 变为 css/1..8 共 8 片（引入顺序 = 层叠顺序）
#   · Vue 由 global 构建换为 ESM 构建（150,058 B，比 global 版小 126 KB）
#   · 新增 GSAP 3.13 + Flip 插件（UMD，供 core/anim.js 取用）
#   旧判据钉的是「三件套文件名」，重构后必红 —— 故改为「入口存在 +
#   模块树非空 + 分片齐备 + vendor 齐备」，这组更能抓到真问题
#   （入口在但 import 图断链、CSS 片漏引）。
for _f, _min in [("index.html", 800),
                 ("js/main.js", 200),
                 ("js/core/anim.js", 1500),
                 ("css/1-tokens.css", 2000),
                 ("css/8-responsive.css", 2000),
                 ("vendor/vue.esm-browser.prod.js", 50000),
                 ("vendor/gsap.min.js", 30000),
                 ("vendor/Flip.min.js", 10000),
                 ("vendor/marked.min.js", 10000),
                 ("vendor/purify.min.js", 8000)]:
    _p = _static / _f
    check(f"B {_f} 存在且非空(>{_min}B)",
          _p.is_file() and _p.stat().st_size > _min,
          f"size={_p.stat().st_size if _p.is_file() else '缺失'}")

# 模块树：core / components / views 三类都要有料（防「入口在、图断了」）
for _d, _n in [("js/core", 8), ("js/components", 12), ("js/views", 5)]:
    _got = len(list((_static / _d).glob("*.js")))
    check(f"B {_d}/ 模块数 ≥ {_n}", _got >= _n, f"实际 {_got}")

# CSS 分片必须齐 8 片且编号连续 —— 漏一片会静默丢一层样式
_css = sorted(p.name for p in (_static / "css").glob("*.css"))
check("B css/ 恰好 8 片且编号 1..8 连续",
      len(_css) == 8 and [n[0] for n in _css] == list("12345678"),
      f"实际 {_css}")

_html = (_static / "index.html").read_text(encoding="utf-8")
check("B index.html 有 Vue 挂载点 #app", 'id="app"' in _html, "")
check("B index.html 按序引用 8 片 CSS",
      all(f"/assets/css/{n}" in _html for n in _css), "")
check("B index.html 走 ESM 入口 /assets/js/main.js",
      "/assets/js/main.js" in _html and 'type="module"' in _html, "")
check("B index.html 引用本地 vendor（无 CDN）",
      all(x in _html for x in ["/assets/vendor/marked.min.js",
                               "/assets/vendor/purify.min.js",
                               "/assets/vendor/gsap.min.js",
                               "/assets/vendor/Flip.min.js"])
      and "http://cdn" not in _html and "https://unpkg" not in _html
      and "jsdelivr" not in _html, "")
check("B index.html 已不再引用旧单文件 app.js / style.css",
      "/assets/app.js" not in _html and "/assets/style.css" not in _html, "")
_main = (_static / "js" / "main.js").read_text(encoding="utf-8")
check("B main.js 以 ESM 具名导入 Vue（非 global 构建）",
      "../vendor/vue.esm-browser.prod.js" in _main
      and "{ createApp" in _main, "")

# =====================================================================
section("C 分层：控制台不得把 server 拉进内存")
check("C1 import web_console 后 sys.modules 里没有 server",
      "server" not in sys.modules,
      f"被拉入 ⇒ 控制台有进程内直调风险；modules={'server' in sys.modules}")

# C2/C3 钉的是 2026-10-16 拆掉的「第二条腿」：本仓曾 import core_path 定位核心目录、
# 再 import memory_config / transport_http。现在对核心仓的关系只剩「连接 MCP」，
# 所以导入控制台后，**核心仓的模块一个都不该出现在内存里** —— 这条比 C1 更严：
# server 只是核心仓的一个文件，import memory_config 同样意味着两份事实源。
for _core_mod in ("memory_config", "transport_http", "core_path", "web_console_core"):
    check(f"C2 import web_console 后 sys.modules 里没有 {_core_mod}（无跨仓 import）",
          _core_mod not in sys.modules, "被拉入 ⇒ 跨仓 import 通道又回来了")


# =====================================================================
section("D 鉴权中间件（ASGI，无需端口）")
def _asgi(cfg: dict):
    import httpx
    return httpx.ASGITransport(app=web_console.create_app(cfg))


async def _req(cfg, method, path, headers=None, json_body=None):
    import httpx
    async with httpx.AsyncClient(transport=_asgi(cfg), base_url="http://t") as c:
        return await c.request(method, path, headers=headers or {}, json=json_body)


_cfg_auth = None
# 2026-10-27：进程内 config() 的落盘位置必须钉到临时目录。此前这段只设了
# TOKEN，其余走默认 ⇒ 写进宿主机 ~/.ai-memory-web（B1 凭据盘点里那枚
# s3cret 就是这么进去的）。审计文件是新增的第四个落盘点，一并钉住。
_WEBCFG = _TMP / "webcfg-d"
_WEBCFG.mkdir(exist_ok=True)
os.environ["AI_MEMORY_WEB_TOKEN"] = "s3cret"
os.environ["AI_MEMORY_WEB_CONFIG"] = str(_WEBCFG / "config.json")
os.environ["AI_MEMORY_WEB_USERS"] = str(_WEBCFG / "users.json")
os.environ["AI_MEMORY_WEB_TOKENS"] = str(_WEBCFG / "tokens.json")
os.environ["AI_MEMORY_WEB_AUDIT"] = str(_WEBCFG / "audit.jsonl")
_cfg_auth = web_console.config()
check("D0 设 token 后 auth_enabled=True", _cfg_auth["auth_enabled"], "")

_r = asyncio.run(_req(_cfg_auth, "GET", "/api/config"))
_body = json.loads(_r.text) if _r.text else {}
check("D1 无 token ⇒ 401 且标记 auth_required",
      _r.status_code == 401 and _body.get("auth_required") is True,
      f"status={_r.status_code} body={_r.text[:120]}")

_r = asyncio.run(_req(_cfg_auth, "GET", "/api/config",
                      {"Authorization": "Bearer s3cret"}))
check("D2 Authorization: Bearer 正确 token ⇒ 200", _r.status_code == 200,
      f"status={_r.status_code}")

_r = asyncio.run(_req(_cfg_auth, "GET", "/api/config",
                      {"X-Auth-Token": "s3cret"}))
check("D3 X-Auth-Token 亦被接受 ⇒ 200", _r.status_code == 200,
      f"status={_r.status_code}")

_r = asyncio.run(_req(_cfg_auth, "GET", "/api/config",
                      {"Authorization": "Bearer wrong"}))
check("D4 token 错误 ⇒ 401", _r.status_code == 401, f"status={_r.status_code}")

_r = asyncio.run(_req(_cfg_auth, "GET", "/"))
check("D5 静态资源不校验 token（GET / ⇒ 200）", _r.status_code == 200,
      f"status={_r.status_code}")

_r = asyncio.run(_req(_cfg_auth, "OPTIONS", "/api/config"))
check("D6 OPTIONS 预检 ⇒ 204", _r.status_code == 204, f"status={_r.status_code}")

# D7~D9：v1.7.0 的两个新面 —— ?token= 第三通道 与 /mcp 反代的鉴权口径。
_r = asyncio.run(_req(_cfg_auth, "GET", "/api/config?token=s3cret"))
check("D7 ?token= 查询参数亦被接受 ⇒ 200", _r.status_code == 200,
      f"status={_r.status_code}")

_r = asyncio.run(_req(_cfg_auth, "POST", "/mcp"))
check("D8 /mcp 无凭据 ⇒ 401（与 /api/* 同一口径）", _r.status_code == 401,
      f"status={_r.status_code} body={_r.text[:120]}")

# 鉴权通过后失败点必须落在「上游不可达」（502），而不是继续 401 ——
# 这条能区分「门没开」与「门开了但屋里没人」，是反代最常被写错的一处。
_dead = dict(_cfg_auth, mcp=f"http://127.0.0.1:{free_port()}/mcp")
_r = asyncio.run(_req(_dead, "POST", "/mcp", {"Authorization": "Bearer s3cret"}))
check("D9 /mcp 凭据正确但上游不可达 ⇒ 502（不再 401）", _r.status_code == 502,
      f"status={_r.status_code} body={_r.text[:140]}")

# D10~D14（2026-10-27）：``/mcp`` 的「人类探测」降级。
# 在浏览器 / 网页读取工具里打开 ``/mcp?token=…``，上游按 MCP 协议回 406
# 「Client must accept text/event-stream」—— 那是**协议协商**，不是令牌失效，
# 但在浏览器里读起来就是「这链接取不到值」。现在 GET + Accept 没点名 MCP 两种
# 类型 ⇒ 回 200 自证报文；真客户端（POST / 带 event-stream 的 GET）行为不变。
# 全部跑在 ``_dead``（上游不可达）上：能回 200 就证明降级发生在转发之前。
_BROWSER = {"Authorization": "Bearer s3cret",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
_r = asyncio.run(_req(_dead, "GET", "/mcp", _BROWSER))
_card = json.loads(_r.text) if _r.text else {}
check("D10 GET /mcp（浏览器 Accept）⇒ 200 自证报文，不再 406/502",
      _r.status_code == 200 and _card.get("kind") == "mcp-streamable-http",
      f"status={_r.status_code} body={_r.text[:160]}")
check("D11 自证报文含 auth 身份与 how_to 接法",
      isinstance(_card.get("auth"), dict) and bool(_card["auth"].get("role"))
      and "headers" in (_card.get("how_to") or {}),
      f"body={_r.text[:200]}")
check("D12 自证报文不回显令牌明文", "s3cret" not in _r.text,
      "令牌明文出现在降级报文里")

_r = asyncio.run(_req(_dead, "POST", "/mcp", {"Authorization": "Bearer s3cret",
                                              "Accept": "*/*"}))
check("D13 POST /mcp 不降级（照旧转发上游）⇒ 502", _r.status_code == 502,
      f"status={_r.status_code} body={_r.text[:140]}")

_r = asyncio.run(_req(_dead, "GET", "/mcp", {"Authorization": "Bearer s3cret",
                                             "Accept": "text/event-stream"}))
check("D14 GET /mcp 带 event-stream ⇒ 不降级（照旧转发上游）⇒ 502",
      _r.status_code == 502, f"status={_r.status_code} body={_r.text[:140]}")

# D15~D19（2026-10-27）：GET 版**只读**调用（地址栏传参查库）。
# 安全契约只有一条 —— 写操作永远不开放 GET，所以白名单是硬边界而不是过滤。
check("D15 GET 只读白名单与写工具集不相交",
      not (web_console.GET_READONLY_TOOLS & web_console.WRITE_TOOLS),
      f"交集={sorted(web_console.GET_READONLY_TOOLS & web_console.WRITE_TOOLS)}")
check("D16 白名单里的工具名都已登记功能分组（防手滑写错名）",
      all(n in web_console._TOOL_GROUP_OF for n in web_console.GET_READONLY_TOOLS),
      f"未登记={sorted(n for n in web_console.GET_READONLY_TOOLS if n not in web_console._TOOL_GROUP_OF)}")

_r = asyncio.run(_req(_dead, "GET", "/mcp?tool=memory_write&title=x",
                      {"Authorization": "Bearer s3cret", "Accept": "*/*"}))
check("D17 GET 调写工具 ⇒ 403（白名单在转发前就挡住）", _r.status_code == 403,
      f"status={_r.status_code} body={_r.text[:160]}")

_r = asyncio.run(_req(_dead, "GET", "/mcp?tool=memory_search&args=not-json",
                      {"Authorization": "Bearer s3cret", "Accept": "*/*"}))
check("D18 GET args 不是 JSON ⇒ 400（不静默当空参数跑）",
      _r.status_code == 400, f"status={_r.status_code} body={_r.text[:160]}")

_r = asyncio.run(_req(_dead, "GET", "/mcp?tool=memory_search&keyword=x",
                      {"Authorization": "Bearer s3cret", "Accept": "*/*"}))
check("D19 白名单内的只读工具 ⇒ 真转发上游（此处不可达 ⇒ 502）",
      _r.status_code == 502, f"status={_r.status_code} body={_r.text[:140]}")

# D20~D28（2026-11-05）：**令牌生命周期 × /mcp 入口**。
# D7~D9 只证明「有没有送凭据」。这条链上真正会出事的是另一半：**有凭据但已失效
# 仍被放行到上游** —— 那等于令牌页上的「吊销」按钮只是个摆设。统一判别式：
#   502 = 鉴权过了、只是屋里没人（被放行）；401 = 拦在转发之前（期望）。
# 为什么全部打 _dead（上游不可达）：这样「被放行」会以 502 显形，不会因为上游
# 恰好能连而伪装成「功能正常」。
_ts = _cfg_auth["tokens"]

# 吊销：先证明新令牌真的能用，再吊销，再打必须 401。
_e_plain, _e_rec = _ts.create(name="e2e-revoke", owner="probe", role="viewer")
_e_hdr = {"Authorization": f"Bearer {_e_plain}"}
_r = asyncio.run(_req(_dead, "POST", "/mcp", _e_hdr))
check("D20 新签令牌可用（鉴权通过 -> 上游 502，不是 401）",
      _r.status_code == 502, f"status={_r.status_code} body={_r.text[:140]}")
_ts.revoke(_e_rec["id"])
_r = asyncio.run(_req(_dead, "POST", "/mcp", _e_hdr))
check("D21 吊销后立即 401（不必重连、不靠缓存过期）",
      _r.status_code == 401, f"status={_r.status_code} body={_r.text[:140]}")

# 过期：直接把记录里的 expires_at 拨到过去。等 60 秒会把这条测试变慢，而慢测试
# 迟早会被跳过 —— 那就等于没测。
_p_exp, _r_exp = _ts.create(name="e2e-expire", owner="probe", role="viewer",
                            expires_in=60)
for _t in _ts._data["tokens"]:
    if _t.get("id") == _r_exp["id"]:
        _t["expires_at"] = time.time() - 1
_r = asyncio.run(_req(_dead, "POST", "/mcp", {"Authorization": f"Bearer {_p_exp}"}))
check("D22 过期令牌 -> 401（有效期不是只写在 UI 上）",
      _r.status_code == 401, f"status={_r.status_code} body={_r.text[:140]}")

# 停用：吊销之外还有「暂时关掉」，语义不同，同样必须立即生效。
_p_off, _r_off = _ts.create(name="e2e-disabled", owner="probe", role="viewer")
_ts.set_enabled(_r_off["id"], False)
_r = asyncio.run(_req(_dead, "POST", "/mcp", {"Authorization": f"Bearer {_p_off}"}))
check("D23 停用令牌 -> 401", _r.status_code == 401,
      f"status={_r.status_code} body={_r.text[:140]}")

# 次数耗尽：必须用 usage_window=0 的独立 Store —— 默认 30s 去重窗口内重复请求
# **不重复计次**（那是给正常客户端突发请求的保护），拿默认值测这条路必然误判。
import web_store as _ws  # noqa: E402
_ts0 = _ws.TokenStore(str(_WEBCFG / "e2e-uses.json"), usage_window=0)
_p_use, _r_use = _ts0.create(name="e2e-uses", owner="probe", role="viewer",
                             max_uses=2)
_cfg0 = dict(_dead, tokens=_ts0)
_codes = []
for _i in range(3):
    _r = asyncio.run(_req(_cfg0, "POST", "/mcp", {"Authorization": f"Bearer {_p_use}"}))
    _codes.append(_r.status_code)
check("D24 次数耗尽 -> 前两次放行(502)、第三次 401", _codes == [502, 502, 401],
      f"codes={_codes}")

# ?token= 第三通道同样受生命周期约束：否则「换个参数位」就是绕过吊销的后门。
_r = asyncio.run(_req(_dead, "POST", f"/mcp?token={_e_plain}"))
check("D25 被吊销令牌走 ?token= 同样 401（不能换通道绕过）",
      _r.status_code == 401, f"status={_r.status_code} body={_r.text[:140]}")

# 视野 / 读写落点：令牌权限必须真的落到端点，而不是只存在控制台界面上。
check("D26 owner + 只读令牌 -> /mcp/owner-ro",
      web_console.resolve_mcp(_cfg_auth, level="owner",
                              writable=False).endswith("/mcp/owner-ro"),
      web_console.resolve_mcp(_cfg_auth, level="owner", writable=False))
check("D27 reader 档不重复加 -ro（该档本身只读）",
      web_console.resolve_mcp(_cfg_auth, level="reader",
                              writable=False).endswith("/mcp/reader"),
      web_console.resolve_mcp(_cfg_auth, level="reader", writable=False))
check("D28 writable 缺省不清空写权（None 不等于 False）",
      web_console.resolve_mcp(_cfg_auth, level="reader",
                              writable=None).endswith("/mcp/reader"),
      web_console.resolve_mcp(_cfg_auth, level="reader", writable=None))

# =====================================================================
section("T 访问日志（audit.jsonl + /api/audit）")
import web_audit  # noqa: E402

_ap = _TMP / "unit-audit.jsonl"
_alog = web_audit.AuditLog(_ap, max_bytes=4096, keep_entries=5)
_alog.append({"kind": "auth", "action": "login.ok", "actor": "dpkg"})
_alog.append({"kind": "tool", "action": "tool.call", "actor": "dpkg",
              "target": "memory_search"})
_alog.append({"kind": "tool", "action": "tool.call", "actor": "bot",
              "target": "memory_write", "ok": False})
_rows = _alog.tail(limit=10)
check("T1 append 自动补时间且新→旧", len(_rows) == 3
      and all(isinstance(r.get("t"), float) for r in _rows)
      and _rows[0].get("target") == "memory_write",
      f"rows={_rows}")
check("T2 按 kind 过滤", len(_alog.tail(kind="tool")) == 2
      and len(_alog.tail(kind="auth")) == 1, "")
check("T3 按 actor 过滤", len(_alog.tail(actor="bot")) == 1, "")
check("T4 按 action 前缀过滤", len(_alog.tail(action="tool.")) == 2, "")

# 凭据类字段必须**在入库前**被丢掉 —— 这是这张卡敢展示给别人看的前提。
_alog.append({"kind": "auth", "action": "login.ok", "actor": "x",
              "token": "amt_LEAK", "password": "pw-LEAK", "detail": "正常"})
_raw = _ap.read_text(encoding="utf-8")
check("T5 令牌与口令字段不入库", "amt_LEAK" not in _raw and "pw-LEAK" not in _raw,
      "凭据写进了审计文件")

# T5b（2026-10-28）：令牌**标识**必须活着穿过滤网。
# 这条与 T5 是一对反向约束：T5 证明「凭据进不去」，T5b 证明「标签没被一起
# 误杀」。危险点很具体 —— 若有人日后把 _SECRET_KEYS 的精确匹配改成前缀
# 匹配（"token" 命中 "token_name"），审计里就再也看不到是哪枚令牌干的，
# 而界面上只会安静地显示「旧记录」，没有任何报错。
# 刻意用**独立实例**而不是复用 _alog：T6 拿 _alog 的条数做断言，往里多写
# 一条会让「坏行被跳过」那条用例的计数失真。
_ap_tok = _TMP / "unit-audit-tokenid.jsonl"
_alog_tok = web_audit.AuditLog(_ap_tok)
_alog_tok.append({"kind": "token", "action": "token.issue", "actor": "dpkg",
                  "token_id": "t_probe", "token_name": "WorkBuddy"})
_last = _alog_tok.tail(limit=1)[0]
check("T5b token_id / token_name 不被凭据过滤误伤",
      _last.get("token_name") == "WorkBuddy" and _last.get("token_id") == "t_probe",
      f"row={_last}")

# ---- U 审计字段端到端（2026-10-28）----------------------------------------
# 为什么必须走「用令牌再签一枚令牌」：只有 via=token 才会写 token_id /
# token_name，用总钥匙（s3cret 是 adopt 进来的 admin 令牌，但请求头里带的是
# 明文、服务端照样判 via=token —— 所以这里刻意用**新签**的令牌，让期望值
# 是一个我们自己写下的名字，而不是 adopt 那枚的默认名。
_r = asyncio.run(_req(_cfg_auth, "POST", "/api/tokens",
                      {"Authorization": "Bearer s3cret"},
                      {"name": "Probe", "role": "operator"}))
_probe_plain = ""
if _r.status_code == 200:
    _probe_plain = str(json.loads(_r.text).get("token") or "")
_r = asyncio.run(_req(_cfg_auth, "POST", "/api/tokens",
                      {"Authorization": f"Bearer {_probe_plain}"},
                      {"name": "Probe2", "role": "viewer"}))
_ok2 = _r.status_code == 200
_r = asyncio.run(_req(_cfg_auth, "GET", "/api/audit?kind=token",
                      {"Authorization": "Bearer s3cret"}))
_ev = [e for e in (json.loads(_r.text).get("events") or [])
       if e.get("via") == "token"]
check("U1 令牌通道审计带 token_id + token_name（快照）",
      _ok2 and bool(_ev) and _ev[0].get("token_name") == "Probe"
      and bool(_ev[0].get("token_id")),
      f"ok2={_ok2} ev={_ev[:1]}")

# 坏行（半截 JSON）只能让**那条**消失，不能整段读取失败。
with _ap.open("a", encoding="utf-8") as _fh:
    _fh.write("{半截坏行\n")
check("T6 坏行被跳过而不是整段失败", len(_alog.tail(limit=10)) == 4, "")

# 有界：写满就压缩，不能无限增长。
for _i in range(300):
    _alog.append({"kind": "tool", "action": "tool.call", "actor": "x",
                  "target": f"t{_i}" + "y" * 20})
_size = _ap.stat().st_size
_total = len(_alog.tail(limit=500))
check("T7 超过大小上限自动压缩（保持有界）",
      0 < _total < 300 and _size < 4096 * 3,
      f"entries={_total} size={_size}")

# -- 接口：admin 专属 --------------------------------------------------
_r = asyncio.run(_req(_cfg_auth, "GET", "/api/audit"))
check("T8 /api/audit 无凭据 ⇒ 401", _r.status_code == 401,
      f"status={_r.status_code}")

_r = asyncio.run(_req(_cfg_auth, "GET", "/api/audit",
                      {"Authorization": "Bearer s3cret"}))
_j = json.loads(_r.text) if _r.text.startswith("{") else {}
check("T9 /api/audit 管理员 ⇒ 200 且带 events/kinds/stats",
      _r.status_code == 200 and isinstance(_j.get("events"), list)
      and {k["key"] for k in (_j.get("kinds") or [])} >= {"auth", "tool", "access"}
      and isinstance(_j.get("stats"), dict),
      f"status={_r.status_code} body={_r.text[:200]}")

_viewer_plain, _viewer_rec = _cfg_auth["tokens"].create(
    name="t-viewer", owner="probe", role="viewer")
_r = asyncio.run(_req(_cfg_auth, "GET", "/api/audit",
                      {"Authorization": f"Bearer {_viewer_plain}"}))
check("T10 /api/audit 只读账号 ⇒ 403（日志本身是侦察地图）",
      _r.status_code == 403, f"status={_r.status_code} body={_r.text[:160]}")

# T8 那次 401 必须自己也被记进来 —— 这是「拒绝也审计」的端到端证据。
_ev = _cfg_auth["audit"].tail(limit=30)
check("T11 鉴权失败被记入审计（auth.denied）",
      any(e.get("action") == "auth.denied" for e in _ev),
      f"actions={[e.get('action') for e in _ev][:8]}")
check("T12 审计文件里没有令牌明文",
      "s3cret" not in Path(_cfg_auth["audit_path"]).read_text(encoding="utf-8"),
      "令牌明文出现在审计文件里")

# -- 导出（2026-10-27）--------------------------------------------------
# 三个判据缺一不可：能下（200 + 附件头）、能读（BOM + 表头 + 行数对得上）、
# 权限同口径（viewer 403）。少第三条就是一个「谁都能把整份日志带走」的洞。
# 行数基准必须**在导出前**取：导出会先读、后记 ``audit.export``，于是导出的
# 那份快照天然不含「导出自己」这一条 —— 事后再取 stats() 就会多 1（T14 首版
# 就是在这儿对不上：6 行 vs 库内 6 条）。
_total_before = _cfg_auth["audit"].stats()["total"]
_r = asyncio.run(_req(_cfg_auth, "GET", "/api/audit/export",
                      {"Authorization": "Bearer s3cret"}))
_txt = _r.text
_lines = [ln for ln in _txt.splitlines() if ln.strip()]
check("T13 导出 CSV ⇒ 200 + 附件头 + UTF-8 BOM",
      _r.status_code == 200
      and "attachment;" in _r.headers.get("content-disposition", "")
      and _r.headers.get("content-disposition", "").endswith('.csv"')
      and _txt.startswith("\ufeff"),
      f"status={_r.status_code} cd={_r.headers.get('content-disposition')!r} "
      f"head={_txt[:40]!r}")
check("T14 CSV 表头含 IP 与操作人列，且行数 = 导出前库内条数 + 1",
      _lines
      and all(k in _lines[0] for k in ("时间", "操作人", "IP", "对象", "结果"))
      and len(_lines) == _total_before + 1,
      f"表头={_lines[0] if _lines else None} 行数={len(_lines)} "
      f"导出前={_total_before}")

_r = asyncio.run(_req(_cfg_auth, "GET", "/api/audit/export?format=json",
                      {"Authorization": "Bearer s3cret"}))
_j = json.loads(_r.text)
check("T15 导出 JSON ⇒ 结构与 /api/audit 的 events 一致",
      _r.status_code == 200 and isinstance(_j.get("events"), list)
      and _j.get("count") == len(_j["events"]) and _j["count"] > 0,
      f"status={_r.status_code} keys={list(_j)[:6]} count={_j.get('count')}")

_r = asyncio.run(_req(_cfg_auth, "GET", "/api/audit/export",
                      {"Authorization": f"Bearer {_viewer_plain}"}))
check("T16 导出 只读账号 ⇒ 403（能导出等于能整份带走）",
      _r.status_code == 403, f"status={_r.status_code} body={_r.text[:160]}")

_r = asyncio.run(_req(_cfg_auth, "GET", "/api/audit/export?format=xlsx",
                      {"Authorization": "Bearer s3cret"}))
check("T17 未知格式 ⇒ 400（不猜、不静默回落到 csv）", _r.status_code == 400,
      f"status={_r.status_code} body={_r.text[:160]}")

# 导出**这件事本身**必须留痕：谁把整份清单带走过，是这份日志里最该被记的动作。
_ev = _cfg_auth["audit"].tail(limit=40, action="audit.export")
check("T18 导出动作被记入审计（audit.export）",
      any(e.get("action") == "audit.export" for e in _ev),
      f"actions={[e.get('action') for e in _ev][:8]}")

# =====================================================================
section("V 日志页（访问日志 + FNS 同步事件，2026-11-05）")
import web_synclog  # noqa: E402

# 独立的一套 cfg：日志页的用例会**往文件里写事件**，复用 _cfg_auth 会把
# T 段的条目数搅乱（T6/T7 都拿条数做断言）。
_vdir = _TMP / "logcfg"
_vdir.mkdir(exist_ok=True)
os.environ["AI_MEMORY_WEB_AUDIT"] = str(_vdir / "audit.jsonl")
os.environ["AI_MEMORY_WEB_FNS_LOG"] = str(_vdir / "sync-events.jsonl")
_cfg_logs = web_console.config()
_vpath = Path(_cfg_logs["fns_log_path"])
_now = time.time()
# 事件模拟 Go 侧的产出：毫秒时间戳、title 可缺（由 path 现推）、中间夹一行坏行。
_vpath.write_text(
    json.dumps({"t": int((_now - 30) * 1000), "kind": "note", "action": "download",
                "path": "工具/记忆库MCP.md", "size": 1234}, ensure_ascii=False) + "\n"
    + "{半截坏行\n"
    + json.dumps({"t": int((_now - 20) * 1000), "kind": "note", "action": "upload",
                  "path": "偏好/口味.md", "size": 88}, ensure_ascii=False) + "\n",
    encoding="utf-8")
_cfg_logs["audit"].append({"t": _now - 25, "kind": "tool", "action": "tool.call",
                           "actor": "dpkg", "target": "memory_read",
                           "note": "记忆库MCP"})

_sl = web_synclog.SyncEventLog(_vpath)
_tail = _sl.tail(limit=10)
check("V1 FNS 事件：毫秒归一成秒 + 标题由路径现推 + 坏行跳过",
      len(_tail) == 2 and _tail[0]["title"] == "口味"
      and abs(float(_tail[0]["t"]) - (_now - 20)) < 2
      and _tail[1]["action"] == "download" and _tail[1]["title"] == "记忆库MCP",
      f"tail={_tail}")
check("V2 按动作过滤（upload 只有一条）",
      [r["action"] for r in _sl.tail(action="upload")] == ["upload"], "")
_st = _sl.status()
check("V3 status 报告可用性与体积（界面据此区分「没数据源」与「真没有」）",
      _st["available"] is True and _st["size"] > 0
      and str(_st["path"]).endswith("sync-events.jsonl"), f"status={_st}")
_missing = web_synclog.SyncEventLog(_TMP / "nope" / "sync-events.jsonl")
check("V4 没有事件文件 ⇒ available=False（状态而非异常）",
      _missing.available() is False and _missing.tail() == []
      and _missing.status()["available"] is False, "")
check("V5 path→title：去掉目录与 .md，其余原样",
      web_synclog.path_to_title("a/b/笔记.md") == "笔记"
      and web_synclog.path_to_title("无扩展名") == "无扩展名"
      and web_synclog.path_to_title("") == "", "")

# -- 接口：合并、排序、权限 ---------------------------------------------
_r = asyncio.run(_req(_cfg_logs, "GET", "/api/logs"))
check("V6 /api/logs 无凭据 ⇒ 401", _r.status_code == 401, f"status={_r.status_code}")

_r = asyncio.run(_req(_cfg_logs, "GET", "/api/logs",
                      {"Authorization": "Bearer s3cret"}))
_j = json.loads(_r.text) if _r.text.startswith("{") else {}
_evs = _j.get("events") or []
_ts = [e.get("t") for e in _evs]
check("V7 /api/logs 合并两类事件且按时间倒序",
      _r.status_code == 200 and len(_evs) >= 3
      and _ts == sorted(_ts, reverse=True)
      and {e.get("source") for e in _evs} == {"access", "fns"},
      f"status={_r.status_code} events={_evs[:3]}")
check("V8 counts / fns 状态随数据下发",
      _j.get("counts", {}).get("fns") == 2
      and _j.get("counts", {}).get("access", 0) >= 1
      and _j.get("fns", {}).get("available") is True,
      f"counts={_j.get('counts')} fns={_j.get('fns')}")
check("V8b /api/logs 带访问日志落点（in_vault / writable / path）",
      isinstance(_j.get("access"), dict)
      and _j["access"].get("writable") is True
      and _j["access"].get("in_vault") is False
      and str(_j["access"].get("path") or "").endswith("audit.jsonl"),
      f"access={_j.get('access')}")

_r = asyncio.run(_req(_cfg_logs, "GET", "/api/logs?source=fns",
                      {"Authorization": "Bearer s3cret"}))
_j2 = json.loads(_r.text) if _r.text.startswith("{") else {}
check("V9 source=fns ⇒ 只回同步事件",
      all(e.get("source") == "fns" for e in (_j2.get("events") or []))
      and len(_j2.get("events") or []) == 2, f"body={_r.text[:160]}")

_r = asyncio.run(_req(_cfg_logs, "GET", "/api/logs",
                      {"Authorization": f"Bearer {_viewer_plain}"}))
check("V10 /api/logs 只读账号 ⇒ 403（同步事件也是数据流向图）",
      _r.status_code == 403, f"status={_r.status_code}")

# -- 导出：能下、能读、权限同口径 ---------------------------------------
_r = asyncio.run(_req(_cfg_logs, "GET", "/api/logs/export?format=csv",
                      {"Authorization": "Bearer s3cret"}))
_txt = _r.text
_lines = [ln for ln in _txt.splitlines() if ln.strip()]
check("V11 导出 CSV ⇒ 200 + 附件头 + UTF-8 BOM + 表头含来源/大小",
      _r.status_code == 200
      and "attachment;" in _r.headers.get("content-disposition", "")
      and _txt.startswith("\ufeff")
      and "来源" in _lines[0] and "大小" in _lines[0]
      and len(_lines) >= 4,
      f"status={_r.status_code} head={_lines[:1]} rows={len(_lines)}")

_ev = _cfg_logs["audit"].tail(limit=10)
check("V12 导出行为本身被记入审计（logs.export）",
      any(e.get("action") == "logs.export" for e in _ev),
      f"actions={[e.get('action') for e in _ev][:6]}")

_r = asyncio.run(_req(_cfg_logs, "GET", "/api/logs/export?format=csv",
                      {"Authorization": f"Bearer {_viewer_plain}"}))
check("V13 导出同样卡 admin（viewer ⇒ 403）", _r.status_code == 403,
      f"status={_r.status_code}")

# -- 记忆库排序 ---------------------------------------------------------
_r = asyncio.run(_req(_cfg_logs, "GET", "/api/library?sort=bogus",
                      {"Authorization": "Bearer s3cret"}))
check("V14 /api/library 非法 sort ⇒ 400（不静默当默认序）",
      _r.status_code == 400, f"status={_r.status_code} body={_r.text[:160]}")

_entries = [
    {"title": "b", "created": "2026-10-02", "tier": "cold", "reads": 1, "path": "b.md"},
    {"title": "a", "created": "2026-10-05", "tier": "hot", "reads": 9, "path": "a.md"},
    {"title": "c", "created": "2026-10-01", "tier": "warm", "reads": 5, "path": "c.md"},
]
_ordered = {
    k: [e["title"] for e in web_console.sort_library_entries(_entries, k, "")]
    for k in ("title", "created", "tier", "reads", "path")
}
check("V15 排序四口径（标题升 / 创建降 / 热度 hot 在前 / 读取多在前）",
      _ordered["title"] == ["a", "b", "c"]
      and _ordered["created"] == ["a", "b", "c"]
      and _ordered["tier"] == ["a", "c", "b"]
      and _ordered["reads"] == ["a", "c", "b"]
      and _ordered["path"] == ["a", "b", "c"],
      f"ordered={_ordered}")
_asc = [e["title"] for e in web_console.sort_library_entries(_entries, "created", "asc")]
check("V16 order=asc 覆盖默认方向（最老的在前）", _asc == ["c", "b", "a"], f"asc={_asc}")
check("V17 sort 为空时保持服务端原序（不偷偷重排）",
      [e["title"] for e in web_console.sort_library_entries(_entries, "", "")] == ["b", "a", "c"], "")

# -- 审计的「对象」口径 -------------------------------------------------
check("V18 审计记标题但不记关键词（memory_search 的 keyword 不入库）",
      web_console.audit_note_title("memory_read", {"title": "记忆库MCP"}) == "记忆库MCP"
      and web_console.audit_note_title("memory_search", {"keyword": "秘密"}) == ""
      and web_console.audit_note_title("memory_list", {}) == "",
      "")

# =====================================================================
section("Vb 日志自身的同步事件（hide_self）与 before 翻页（2026-11-09）")

# 为什么另起一套**独立 vault**：自事件判据依赖「日志落点是否在库内」（只有
# 落在库里才会被 FNS 同步），把日志真正扔进一个库里的附件目录是最贴近现场的
# 形态；同时避免污染主测试库（别的段落拿条数做断言）。
_SV = _TMP / "selfvault"
(_SV / "附件" / "日志").mkdir(parents=True, exist_ok=True)
_SFNS = _SV / "附件" / "日志" / "sync-events.jsonl"
_ENV_BAK = {k: os.environ.get(k) for k in
            ("AI_MEMORY_DIR", "AI_MEMORY_WEB_AUDIT", "AI_MEMORY_WEB_FNS_LOG")}
os.environ["AI_MEMORY_DIR"] = str(_SV)
os.environ["AI_MEMORY_WEB_AUDIT"] = str(_SV / "附件" / "日志" / "audit.jsonl")
os.environ["AI_MEMORY_WEB_FNS_LOG"] = str(_SFNS)
_cfg_self = web_console.config()
_t0 = time.time()
# 事件里报的是 **vault 相对**路径（FNS 的 Go 侧只知道库内路径）；
# 落点配置给的是绝对路径 —— 两种形态都要能认出来，这正是判据最容易漏的地方。
_SELF_REL = "附件/日志/audit.jsonl"
_SELF_ABS = str(_SV / "附件" / "日志" / "audit.jsonl").replace("\\", "/")


def _sync_ev(dt, path, action="upload", kind="file"):
    return json.dumps({"t": int((_t0 - dt) * 1000), "kind": kind,
                       "action": action, "path": path, "size": 215900},
                      ensure_ascii=False)


_SFNS.write_text("\n".join([
    _sync_ev(50, _SELF_REL),                       # 访问日志自己（相对形态）
    _sync_ev(45, _SELF_ABS),                       # 同一文件的绝对形态
    _sync_ev(40, "偏好/口味.md", kind="note"),      # 普通笔记
    _sync_ev(30, "其它/audit.jsonl"),              # 同名不同路径：**不能**当自事件
    _sync_ev(20, "工具/记忆库MCP.md", kind="note", action="download"),
]) + "\n", encoding="utf-8")
_cfg_self["audit"].append({"t": _t0 - 5, "kind": "tool", "action": "tool.call",
                           "actor": "dpkg", "target": "memory_read"})
_h_admin = {"Authorization": "Bearer s3cret"}

# -- 判据本体（helper 层）：错杀比漏杀难发现，故逐条钉住 ------------------
check("V19 _is_self_sync_event 认得两种路径形态（相对 / 绝对 / 反斜杠 / ./）",
      web_console._is_self_sync_event(_SELF_REL, _SELF_REL, _SELF_ABS)
      and web_console._is_self_sync_event(_SELF_ABS, _SELF_REL, _SELF_ABS)
      and web_console._is_self_sync_event("\\附件\\日志\\audit.jsonl",
                                          _SELF_REL, _SELF_ABS)
      and web_console._is_self_sync_event("./附件/日志/audit.jsonl  ",
                                          _SELF_REL, _SELF_ABS), "")
check("V20 _is_self_sync_event 不误伤：同名不同路径 / 根目录同名 / 普通笔记 / 空",
      not web_console._is_self_sync_event("其它/audit.jsonl", _SELF_REL, _SELF_ABS)
      and not web_console._is_self_sync_event("audit.jsonl", _SELF_REL, _SELF_ABS)
      and not web_console._is_self_sync_event("偏好/口味.md", _SELF_REL, _SELF_ABS)
      and not web_console._is_self_sync_event("", _SELF_REL, _SELF_ABS), "")
check("V21 落点未知时才退化为按文件名判（不是无条件认文件名）",
      web_console._is_self_sync_event("附件/日志/audit.jsonl", "", "")
      and web_console._is_self_sync_event("x/sync-events.jsonl", "", "")
      and not web_console._is_self_sync_event("x/其它.md", "", ""), "")

# -- 接口：默认隐藏、计数如实、全量口径另报 ------------------------------
_r = asyncio.run(_req(_cfg_self, "GET", "/api/logs", _h_admin))
_j = json.loads(_r.text) if _r.text.startswith("{") else {}
_paths = [e.get("path") for e in (_j.get("events") or [])]
check("V22 默认 hide_self=1：自事件被藏掉，但 counts.self 如实上报",
      _r.status_code == 200
      and _SELF_REL not in _paths and _SELF_ABS not in _paths
      and "其它/audit.jsonl" in _paths
      and _j.get("self_hidden") is True
      and _j.get("counts", {}).get("self") == 2
      and _j.get("counts", {}).get("fns") == 3
      and _j.get("total") == 4 and len(_paths) == 4,
      f"status={_r.status_code} counts={_j.get('counts')} paths={_paths}")
check("V23 total/counts 是过滤后可口径，stats.fns 仍是全量 + stats.fns_self",
      _j.get("counts", {}).get("access") == 1
      and _j.get("stats", {}).get("fns", {}).get("total") == 5
      and _j.get("stats", {}).get("fns_self") == 2,
      f"counts={_j.get('counts')} stats={_j.get('stats')}")

_r = asyncio.run(_req(_cfg_self, "GET", "/api/logs?hide_self=0", _h_admin))
_j = json.loads(_r.text) if _r.text.startswith("{") else {}
_paths = [e.get("path") for e in (_j.get("events") or [])]
check("V24 hide_self=0 ⇒ 自事件回来，self_hidden=False，counts.self 不变",
      len(_paths) == 6 and _j.get("self_hidden") is False
      and _j.get("counts", {}).get("self") == 2
      and _j.get("counts", {}).get("fns") == 5
      and _j.get("total") == 6,
      f"counts={_j.get('counts')} n={len(_paths)}")

_r = asyncio.run(_req(_cfg_self, "GET", "/api/logs?limit=1", _h_admin))
_j = json.loads(_r.text) if _r.text.startswith("{") else {}
check("V25 has_more：还有更早的命中项 ⇒ True（按过滤后口径算）",
      _j.get("has_more") is True and _j.get("total") == 4
      and len(_j.get("events") or []) == 1,
      f"body={_r.text[:160]}")

# -- before 翻页：开区间，与 hide_self / since 叠加 ----------------------
_cursor = _t0 - 25
_r = asyncio.run(_req(_cfg_self, "GET", f"/api/logs?before={_cursor}", _h_admin))
_j = json.loads(_r.text) if _r.text.startswith("{") else {}
_ts = [e.get("t") for e in (_j.get("events") or [])]
check("V26 before 只回更早的事件（开区间，不含游标本身）",
      _r.status_code == 200 and len(_ts) == 2 and all(t < _cursor for t in _ts)
      and _j.get("counts", {}).get("fns") == 2 and _j.get("total") == 2,
      f"status={_r.status_code} ts={_ts} counts={_j.get('counts')}")
_r = asyncio.run(_req(_cfg_self, "GET", "/api/logs?before=abc", _h_admin))
check("V27 before 非数字 ⇒ 400（不静默当没传）", _r.status_code == 400,
      f"status={_r.status_code} body={_r.text[:120]}")

# -- 导出：同一把尺子，且仍是「命中项全量」------------------------------
_r1 = asyncio.run(_req(_cfg_self, "GET", "/api/logs/export?format=json", _h_admin))
_r2 = asyncio.run(_req(_cfg_self,
                       "GET", "/api/logs/export?format=json&hide_self=0", _h_admin))
_j1 = json.loads(_r1.text) if _r1.text.startswith("{") else {}
_j2 = json.loads(_r2.text) if _r2.text.startswith("{") else {}
_p1 = [e.get("path") for e in (_j1.get("events") or [])]
_p2 = [e.get("path") for e in (_j2.get("events") or [])]
check("V28 导出默认同样隐藏自事件；hide_self=0 时它们回到导出里",
      _r1.status_code == 200 and _r2.status_code == 200
      and _SELF_REL not in _p1 and "其它/audit.jsonl" in _p1
      and _p2.count(_SELF_REL) == 1 and _SELF_ABS in _p2
      and _j1.get("count") == 4 and _j2.get("count") >= 6,
      f"n1={_j1.get('count')} n2={_j2.get('count')} p1={_p1}")

# 环境复原：后续段落仍按「日志落点在临时目录、不在库里」的形态跑。
for _k, _v in _ENV_BAK.items():
    if _v is None:
        os.environ.pop(_k, None)
    else:
        os.environ[_k] = _v

# =====================================================================
section("E 写保护（AI_MEMORY_WEB_CONFIG_WRITE=0）")
_cfg_ro = web_console.config()
_cfg_ro = dict(_cfg_ro, config_write=False)
_r = asyncio.run(_req(_cfg_ro, "POST", "/api/thresholds",
                      {"Authorization": "Bearer s3cret"},
                      json_body={"values": {"heat_hot_min": 5}}))
_ok = _r.status_code == 400 and "只读" in _r.text
check("E1 只读模式下写阈值 ⇒ 400 且提示只读", _ok,
      f"status={_r.status_code} body={_r.text[:140]}")

# =====================================================================
section("F 端到端（真起 serve_http + serve_web）")
mcp_port, web_port = free_port(), free_port()
env = _clean_env(AI_MEMORY_TRANSPORT="http", AI_MEMORY_HTTP_HOST="127.0.0.1",
                 AI_MEMORY_HTTP_PORT=str(mcp_port), AI_MEMORY_HTTP_PATH="/mcp",
                 AI_MEMORY_RESTART="0", AI_MEMORY_METRICS="0")
lf = open(_TMP / "mcp.log", "wb")
p_mcp = subprocess.Popen([sys.executable, str(_CORE / "serve_http.py")],
                         cwd=str(_CORE), env=env, stdout=lf, stderr=subprocess.STDOUT)
wenv = _clean_env(AI_MEMORY_WEB_HOST="127.0.0.1", AI_MEMORY_WEB_PORT=str(web_port),
                  AI_MEMORY_WEB_MCP=f"http://127.0.0.1:{mcp_port}/mcp",
                  AI_MEMORY_WEB_CONFIG=str(_TMP / "webcfg" / "config.json"))
lf2 = open(_TMP / "web.log", "wb")
p_web = subprocess.Popen([sys.executable, str(_ROOT / "serve_web.py")],
                         cwd=str(_ROOT), env=wenv, stdout=lf2, stderr=subprocess.STDOUT)
base = f"http://127.0.0.1:{web_port}"


# 时间/日期形状判据（F3b 用）——写在模块级，避免每次都重新编译
_HHMM_RE = re.compile(r"\d{2}:\d{2}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _http(path, method="GET", body=None, timeout=60):
    req = urllib.request.Request(base + path, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:                # noqa: PERF203
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:                             # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
section("G 工具功能分组（方案 B，2026-10-15）")
# G1~G5 是**静态守卫**：`server.py` 里 `@mcp.tool` 注册的工具名 ↔
# `web_console._TOOL_GROUP_OF` 双向一致 —— 不重、不漏、无陈旧键、无空组。
# 🔴 为什么必须有：把分组表放服务端，正是为了不让前端变成「会随工具数增长而
# 失配的第二事实源」；但表本身仍会与工具定义脱节（新增工具忘登记 / 删了工具
# 留下陈旧键）。两个方向的失配都靠这里钉住，而不是靠人记得同步改。
import ast as _ast  # noqa: E402

_srv_py = _CORE / "server.py"
_registered: set[str] = set()
for _node in _ast.walk(_ast.parse(_srv_py.read_text(encoding="utf-8"))):
    if not isinstance(_node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
        continue
    for _dec in _node.decorator_list:
        if not isinstance(_dec, _ast.Call):
            _f, _kw = _dec, {}
        else:
            _f, _kw = _dec.func, {k.arg: k.value for k in _dec.keywords}
        if getattr(_f, "attr", None) != "tool":
            continue
        # `@mcp.tool(name="x")` 可以把注册名与函数名解耦（memory_config 就是这么做的：
        # 函数名叫 _memory_config_tool，免得遮蔽同名的 memory_config 模块）。
        # 只取 _node.name 会把这类工具记成函数名 ⇒ G3 立刻报「分组表有陈旧键」。
        _nm = _kw.get("name")
        _registered.add(_nm.value if isinstance(_nm, _ast.Constant) and isinstance(_nm.value, str)
                        else _node.name)

_mapped = set(web_console._TOOL_GROUP_OF)
_group_keys = {g["key"] for g in web_console.TOOL_GROUPS}
_used_keys = set(web_console._TOOL_GROUP_OF.values())

check("G1 server.py 注册了 27 个 @mcp.tool 工具",
      len(_registered) == 27, f"实际 {len(_registered)} 个")
check("G2 分组表无遗漏（每个已注册工具都有归属）",
      not (_registered - _mapped), ", ".join(sorted(_registered - _mapped)))
check("G3 分组表无陈旧键（没有已不存在的工具）",
      not (_mapped - _registered), ", ".join(sorted(_mapped - _registered)))
check("G4 归属值都落在 TOOL_GROUPS 的 key 内",
      _used_keys <= _group_keys,
      ", ".join(sorted(_used_keys - _group_keys)))
check("G5 每个分组都至少有 1 个工具（无空组）",
      _group_keys <= _used_keys, ", ".join(sorted(_group_keys - _used_keys)))


# ---------------------------------------------------------------------------
section("H 更新面（2026-10-15）")
# H1/H2 钉的是**安全边界**：白名单决定「更新」能覆盖哪些文件。少了控制台后端或
# 前端目录，功能就名不副实；混进 *.md / *.db，就会碰到 vault 数据。
_wl = set(web_console.UPDATE_PATHS)
# ⚠️ 3.10 兼容（2026-10-19）：f-string 的替换字段里**不能换行**（PEP 701 是 3.12
# 才放开）。本机 3.13 跑得通，但 CI 矩阵含 3.10/3.11 —— 在那两个版本上这是
# SyntaxError，会让整个测试文件连编译都过不去。故表达式先算出来再插值。
_wl_need = {"web_console.py", "serve_web.py", web_console.UPDATE_FRONTEND_DIR}
_wl_missing = sorted(_wl_need - _wl)
check("H1 白名单覆盖本仓后端两件 + 前端目录",
      _wl_need <= _wl,
      f"缺={_wl_missing}")
check("H2 白名单不含数据类文件（.md / .db / .sqlite）",
      not any(str(p).endswith((".md", ".db", ".sqlite", ".sqlite3")) for p in _wl),
      ", ".join(sorted(_wl)))


def _mk_repo(path: Path, files: dict) -> None:
    """造一个最小真仓库并提交一轮 —— H3/H4 要在真 git 输出上验证解析，而非打桩。"""
    path.mkdir(parents=True, exist_ok=True)
    for cmd in (["init", "-q"], ["config", "user.email", "t@example.invalid"],
                ["config", "user.name", "t"], ["config", "core.autocrlf", "false"]):
        subprocess.run(["git", *cmd], cwd=str(path), capture_output=True, timeout=30)
    for name, text in files.items():
        (path / name).write_text(text, encoding="utf-8", newline="\n")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, timeout=30)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=str(path),
                   capture_output=True, timeout=30)


# H3 回归保护：`_whitelist_dirty` 曾因 `_git` 整包 strip 吞掉**行首状态位**，
#    把 `memory_config.py` 读成 `emory_config.py`（少一个字符）。这里刻意只改
#    工作区、不 add，让 porcelain 首行是 ` M 路径`。
_repo = _TMP / "h_repo"
_mk_repo(_repo, {"first.py": "x = 1\n", "second.py": "y = 1\n"})
(_repo / "first.py").write_text("x = 2\n", encoding="utf-8", newline="\n")
_dirt = web_console._whitelist_dirty(_repo, ("first.py", "second.py"))
check("H3 _whitelist_dirty 保留首行完整路径（行首状态位不被吞）",
      _dirt == ["first.py"], f"得到 {_dirt!r}")

# H4 三点语义：本地领先时 `HEAD..ref` 会把**本地已提交的新文件**列成待删除。
#    造「本地新增 third.py 并提交、ref 指上一提交」的局面 —— 两点会报 D，
#    三点（merge-base..ref）必须为空。
(_repo / "third.py").write_text("z = 1\n", encoding="utf-8", newline="\n")
subprocess.run(["git", "add", "."], cwd=str(_repo), capture_output=True, timeout=30)
subprocess.run(["git", "commit", "-qm", "second"], cwd=str(_repo),
               capture_output=True, timeout=30)
_two_point = subprocess.run(["git", "diff", "--name-status", "HEAD..HEAD~1",
                             "--", "third.py"], cwd=str(_repo),
                            capture_output=True, timeout=30).stdout.decode()
_three_point, _ = web_console._diff_head_to(_repo, "HEAD~1", ("third.py",))
check("H4 _diff_head_to 用三点语义（本地新增不被误列成待删除）",
      _three_point == [] and _two_point.strip().startswith("D"),
      f"三点={_three_point!r} 两点={_two_point.strip()!r}")

# H5 restarter 的配置失败必须显式：设了不存在的路径就返回空串，不静默回落桌面
#    —— 否则「为什么不能重启」会变得不可复现。
_keep_env = os.environ.get("AI_MEMORY_RESTARTER")
os.environ["AI_MEMORY_RESTARTER"] = str(_TMP / "no-such-helper.py")
_got_restarter = web_console.restarter_path()
if _keep_env is None:
    os.environ.pop("AI_MEMORY_RESTARTER", None)
else:
    os.environ["AI_MEMORY_RESTARTER"] = _keep_env
check("H5 AI_MEMORY_RESTARTER 指向不存在文件时返回空串（不静默回落）",
      _got_restarter == "", f"得到 {_got_restarter!r}")

# H6~H8 双目标（2026-10-16）：核心白名单的**安全边界**。少了它，「更新核心」要么
#    名不副实（漏掉 server.py 就永远更不到 MCP 本体），要么越界（把安装器 / CI /
#    模板数据页一起覆盖）。
_cwl = set(web_console.CORE_PROGRAM_FILES)
_core_must = {"server.py", "serve_http.py", "memory_config.py"}
check("H6 核心白名单覆盖 MCP 运行时三件（server / serve_http / memory_config）",
      _core_must <= _cwl, f"缺={sorted(_core_must - _cwl)}")
check("H7 核心白名单不含数据类文件（.md / .db / .sqlite）",
      not any(str(p).endswith((".md", ".db", ".sqlite", ".sqlite3")) for p in _cwl),
      ", ".join(sorted(_cwl)))
check("H8 核心白名单不含安装器 / CI / 模板数据（那不是运行面）",
      not any(p.startswith(("install", "template/", "setup/", ".github/"))
              for p in _cwl) and "ai_memory_setup.py" not in _cwl,
      ", ".join(sorted(_cwl)))

# H9 核心根定位：显式设了 AI_MEMORY_CORE_DIR 却无效时**必须报错而非静默回落**
#    —— 静默回落会让「更新了错误的目录」变成不可复现的事故（口径同 H5）。
_keep_core = os.environ.get(web_console.CORE_ROOT_ENV)
try:
    os.environ[web_console.CORE_ROOT_ENV] = str(_TMP / "definitely-not-a-core-repo")
    _bad_root, _bad_err = web_console.core_root()
finally:
    if _keep_core is None:
        os.environ.pop(web_console.CORE_ROOT_ENV, None)
    else:
        os.environ[web_console.CORE_ROOT_ENV] = _keep_core
check("H9 AI_MEMORY_CORE_DIR 设错时报错且不回落",
      _bad_root is None and web_console.CORE_ROOT_ENV in (_bad_err or ""),
      f"root={_bad_root} err={_bad_err!r}")

# H10 可移植断言：core_root() 要么返回 None，要么返回**真**核心仓（含全部标记
#     文件）。本机是 submodule 布局（父目录即核心仓），但这条不能依赖本机布局。
_ok_root, _ok_err = web_console.core_root()
check("H10 core_root() 成功时必为真核心仓（含全部标记文件）",
      _ok_root is None
      or all((_ok_root / m).is_file() for m in web_console.CORE_ROOT_MARKERS),
      f"root={_ok_root} err={_ok_err!r}")

# H11~H13 前端更新面（2026-10-19）：「进 web 自动检测 + 有更新提示」与「远端版本
#   三态文案」全在前端，后端接口测不到，所以沿用 H1~H5 的源码守卫手法钉契约。
#   H11 守的是本轮真正修掉的回归 —— 进「关于」页发的 `?fetch=0` 不含 remote_*，
#   若无条件合并，会把刚联网拿到的 v1.1.0 抹回「（未检查）」，即主人报的「读不到」。
_upd_js = (_static / "js" / "features" / "update.js").read_text(encoding="utf-8")
_root_js = (_static / "js" / "views" / "Root.js").read_text(encoding="utf-8")
_set_js = (_static / "js" / "views" / "SettingsPage.js").read_text(encoding="utf-8")

check("H11 离线状态不覆盖已联网的远端结论（mergeTargets 降级保护）",
      "REMOTE_KEYS" in _upd_js
      and "t.checked === false && p.checked === true" in _upd_js
      and '"remote_version"' in _upd_js,
      "缺降级保护：?fetch=0 会把远端版本抹成『未检查』")

check("H12 进 web 自动检测更新（mounted 调 autoCheckUpdates + 导航圆点）",
      "function autoCheckUpdates" in _upd_js
      and "autoCheckUpdates()" in _root_js
      and "pendingCount()" in _root_js
      and "nav-dot" in _root_js,
      "自动检测未接线：Root.mounted 或导航圆点缺失")

check("H13 远端版本三态文案（未检查 / 检查失败 / 有提交号）",
      "检查失败（原因见下方）" in _set_js
      and "已检查，未取到提交号" in _set_js
      and "（未检查）" in _set_js,
      "remoteLabel 仍把『没联网』与『联网失败』压成同一句")


try:
    check("F0 MCP 端点起来", wait_port(mcp_port), "")
    check("F0 控制台起来", wait_port(web_port), "")

    st, txt = _http("/api/health")
    j = json.loads(txt) if st == 200 else {}
    check("F1 /api/health 200 且 ok",
          st == 200 and j.get("ok") is True and j.get("server"),
          f"status={st} body={txt[:160]}")

    st, txt = _http("/api/tools")
    j = json.loads(txt) if st == 200 else {}
    names = {t.get("name") for t in j.get("tools", [])} if j else set()
    check("F2 /api/tools 返回 27 个工具且含关键项",
          st == 200 and j.get("count") == 27 and {"memory_batch_tag",
                                                  "memory_config",
                                                  "memory_access_suggest",
                                                  "memory_orphans"} <= names,
          f"status={st} count={j.get('count')}")

    # F2b~F2d 工具功能分组（方案 B，2026-10-15）。
    # G 段已静态证明「表本身自洽」，这里证明它**真的经 MCP 协议 + /api/tools
    # 走到了前端** —— 控制台不 import server，两段缺一不可。
    _gkeys = [g.get("key") for g in j.get("groups", [])] if j else []
    _gtools = j.get("tools", []) if j else []
    check("F2b /api/tools 下发 6 个功能组且首组为 content",
          st == 200 and len(_gkeys) == 6 and _gkeys[0] == "content",
          f"groups={_gkeys}")
    check("F2c 27 项工具全部带 group，且值都在组定义内",
          st == 200 and len(_gtools) == 27
          and all(t.get("group") in _gkeys for t in _gtools),
          ", ".join(sorted({str(t.get("group")) for t in _gtools} - set(_gkeys))))
    check("F2d 没有工具落入 other 兜底组（映射表无遗漏）",
          st == 200 and all(t.get("group") != "other" for t in _gtools), "")

    st, txt = _http("/api/overview")
    j = json.loads(txt) if st == 200 else {}
    check("F3 /api/overview 200 且带 stats/recent/list",
          st == 200 and j.get("ok") is True and isinstance(j.get("stats"), dict)
          and "recent" in j and "list" in j, f"status={st} keys={list(j)[:6]}")

    # F3b /api/activity —— 概览「最近更新」热力日历的数据面（2026-10-15 新增）。
    #     这一条的存在理由：该端点**必须**是「按天聚合的紧凑结构」而不是原始条目列表。
    #     走 /api/call 直接拿 memory_recent 的写法已被实测否决 —— `_clip`
    #     （_THUMB = 40000 字符）会把 120 天的 JSON（约 13 万字符）截断成非法 JSON，
    #     前端 JSON.parse 必然抛错。所以这里钉住聚合契约：
    #       ① total == sum(counts)；
    #       ② items 的键必须都在 counts 里（不许出现「有明细没计数」的天）；
    #       ③ 每行必须是 [HH:MM, 标题, 摘要]，且时刻是**本地**格式 ——
    #          回归保护：曾按 UTC 直接切前 10 位，会让本地凌晨写的条目整体差一天；
    #       ④ today 必须是合法日期串（前端拿它标「今天」，不再自己算日期）。
    st, txt = _http("/api/activity?days=120")
    j = json.loads(txt) if st == 200 else {}
    counts = j.get("counts") or {}
    items = j.get("items") or {}
    orphan_keys = [k for k in items if k not in counts]
    bad_rows = [k for k, rows in items.items() for r in rows
                if not (isinstance(r, list) and len(r) == 3
                        and _HHMM_RE.fullmatch(str(r[0]))
                        and str(r[1]).strip())]
    check("F3b /api/activity 按天聚合且 counts/items/total 自洽",
          st == 200 and j.get("ok") is True
          and isinstance(counts, dict) and isinstance(items, dict)
          and j.get("total") == sum(counts.values())
          and not orphan_keys and not bad_rows
          and bool(_DATE_RE.fullmatch(str(j.get("today") or ""))),
          f"status={st} total={j.get('total')} "
          f"sum(counts)={sum(counts.values()) if counts else 0} "
          f"孤儿键={orphan_keys[:3]} 坏行={bad_rows[:3]} today={j.get('today')!r}")

    st2, txt2 = _http("/api/activity?days=abc")
    j2 = json.loads(txt2) if st2 == 200 else {}
    st3, txt3 = _http("/api/activity?days=99999")
    j3 = json.loads(txt3) if st3 == 200 else {}
    st4, txt4 = _http("/api/activity?days=0")
    j4 = json.loads(txt4) if st4 == 200 else {}
    check("F3c days 参数非法/越界会被夹住（非法→120，上限 365，下限 1）",
          st2 == 200 and j2.get("days") == 120
          and st3 == 200 and j3.get("days") == 365
          and st4 == 200 and j4.get("days") == 1,
          f"abc->{j2.get('days')} 99999->{j3.get('days')} 0->{j4.get('days')}")

    # F3d~F3f /api/library —— 记忆库页「滚动续载」的分页数据面（2026-10-29 新增）。
    #     存在理由：核心仓的 memory_list **没有 offset**，而整包 JSON（416 条约 10 万
    #     字符）过 `_clip`（_THUMB = 40000）会被截断成非法 JSON ⇒ 切片只能落在服务端。
    #     这里钉三件事：
    #       ① 契约字段齐全，count 是**过滤后总数**（不随本页 limit 变）；
    #       ② 相邻两页**不重叠** —— 证明 offset 真的生效，而不是把第一页再回一遍
    #          （最早的实现若忽略 offset，这条会立刻红）；
    #       ③ 越界 offset 回空页而非 500、非法参数被夹住 —— 前端「滚到底」
    #          必然问到边界，这里不能靠运气。
    st, txt = _http("/api/library?offset=0&limit=5")
    p1 = json.loads(txt) if st == 200 else {}
    st_b, txt_b = _http("/api/library?offset=5&limit=5")
    p2 = json.loads(txt_b) if st_b == 200 else {}
    k1 = [str(it.get("path") or it.get("title")) for it in (p1.get("items") or [])]
    k2 = [str(it.get("path") or it.get("title")) for it in (p2.get("items") or [])]
    total = p1.get("count") or 0
    check("F3d /api/library 分页契约齐全且 count 为过滤后总数",
          st == 200 and p1.get("ok") is True
          and p1.get("offset") == 0 and p1.get("limit") == 5
          and p1.get("shown") == len(k1) and len(k1) <= 5
          and total >= len(k1),
          f"status={st} count={total} shown={p1.get('shown')} got={len(k1)}")
    check("F3e /api/library 相邻两页不重叠（offset 真的生效）",
          st_b == 200 and set(k1).isdisjoint(k2),
          f"p1={k1[:2]} p2={k2[:2]} 交集={sorted(set(k1) & set(k2))[:3]}")

    st_c, txt_c = _http(f"/api/library?offset={total + 500}&limit=5")
    p3 = json.loads(txt_c) if st_c == 200 else {}
    st_d, txt_d = _http("/api/library?offset=abc&limit=99999")
    p4 = json.loads(txt_d) if st_d == 200 else {}
    check("F3f 越界 offset 回空页、参数越界被夹住（abc→0，99999→200）",
          st_c == 200 and (p3.get("items") or []) == []
          and p3.get("count") == total
          and st_d == 200 and p4.get("offset") == 0 and p4.get("limit") == 200,
          f"越界 status={st_c} items={(p3.get('items') or [])[:2]} "
          f"abc→{p4.get('offset')} 99999→{p4.get('limit')}")

    st, txt = _http("/api/thresholds")
    j = json.loads(txt) if st == 200 else {}
    keys = set((j.get("keys") or {}).keys())
    want = {"dup_title_jaccard", "dup_body_jaccard", "body_truncate_chars",
            "lock_timeout", "heat_cold_max", "heat_demote_hot_max",
            "heat_hot_min", "heat_decay_lambda"}
    check("F4 /api/thresholds 列出 8 个内置阈值键且可写",
          st == 200 and want <= keys and j.get("writable") is True,
          f"status={st} missing={sorted(want - keys)} writable={j.get('writable')}")

    # 接线断言：文案的唯一事实源是核心仓 memory_config.META，控制台已不再 import 它
    # ⇒ 文案只能**经 MCP 工具 memory_config 传过来**。这条因此同时证明了两件事：
    # 服务端把文案带出来了，且控制台确实在走 MCP 而不是偷偷 import。
    # 断言口径是「**每个**键都非空」，而不是「至少有一个」—— 后者在 7 个键都空时照样绿。
    _no_meta = [k for k, v in (j.get("keys") or {}).items()
                if not str(v.get("label") or "").strip()
                or not str(v.get("desc") or "").strip()]
    check("F4b 每个阈值键都随接口下发 label/desc（界面据此渲染作用说明）",
          st == 200 and not _no_meta, f"缺文案的键={_no_meta}")

    # F11 更新面端点（2026-10-15 建立；2026-10-16 扩为**双目标**）。
    #     只读本地状态这条必须是**真不联网**：`?fetch=0` 是打开配置页「关于」时的
    #     默认路径，它若能联网，就会在每次进页面时静默跑一次可能耗时几十秒的
    #     git fetch。
    #     契约（2026-10-16 起）：{"ok", "checked", "targets":[…]}
    #     —— 定位不到的目标**也必须占位**并带 error，否则界面会把「核心没找到」
    #     误读成「核心已是最新」。
    st, txt = _http("/api/update?fetch=0")
    j = json.loads(txt) if st == 200 else {}
    _ts = {t.get("target"): t for t in (j.get("targets") or [])}
    _wj = _ts.get("web") or {}
    _cj = _ts.get("core") or {}
    check("F11 GET /api/update?fetch=0 两个目标都占位且 checked=false",
          st == 200 and j.get("checked") is False
          and set(_ts) == set(web_console.UPDATE_TARGET_KEYS)
          and all(t.get("checked") is False for t in _ts.values()),
          f"status={st} checked={j.get('checked')} targets={sorted(_ts)}")
    check("F11b web 目标带本地状态与白名单（白名单 = 本仓程序文件）",
          _wj.get("is_repo") is True and bool(_wj.get("local_sha"))
          and isinstance(_wj.get("whitelist"), list)
          # 用**精确集合包含**而不是「长度 >= N」：长度断言分辨不出「混进了不该
          # 覆盖的文件」与「漏了本仓文件」，两者都能凑够数量。
          and {"web_console.py", "serve_web.py",
               web_console.UPDATE_FRONTEND_DIR} <= set(_wj.get("whitelist") or []),
          f"is_repo={_wj.get('is_repo')} whitelist={_wj.get('whitelist')}")
    check("F11c core 目标占位、带核心白名单，定位失败时给出可读原因",
          isinstance(_cj.get("available"), bool)
          and set(web_console.CORE_PROGRAM_FILES) <= set(_cj.get("whitelist") or [])
          # 可用 ⇒ 必须真解析到一个仓库（有 root 与 local_sha）；
          # 不可用 ⇒ 必须给出非空原因，且**不得**同时声称「已是最新」。
          and (_cj.get("available") is not True
               or (bool(_cj.get("root")) and bool(_cj.get("local_sha"))))
          and (_cj.get("available") is True
               or (isinstance(_cj.get("error"), str) and bool(_cj.get("error").strip())))
          and not (_cj.get("available") is False and _cj.get("up_to_date") is True),
          f"available={_cj.get('available')} root={_cj.get('root')!r} "
          f"local_sha={_cj.get('local_sha')!r} error={_cj.get('error')!r}")
    st, txt = _http("/api/update?target=nope&fetch=0")
    check("F11d 未知 target 返回 400（不静默回落成 web）", st == 400, f"status={st}")

    st, txt = _http("/")
    check("F5 GET / 返回 index.html（含 #app）", st == 200 and 'id="app"' in txt,
          f"status={st} len={len(txt)}")

    st, txt = _http("/assets/js/main.js")
    check("F6 /assets/js/main.js 可达且非空", st == 200 and len(txt) > 200,
          f"status={st} len={len(txt)}")

    # ESM 拆分后必须有这一条：入口可达 ≠ import 图完整。任一模块取不到，
    # 整棵树都不会执行（页面停在 4 秒兜底），而只测入口的判据照样绿。
    _mods = ["/assets/js/core/anim.js", "/assets/js/core/store.js",
             "/assets/js/components/AnimatedNumber.js",
             "/assets/js/views/Root.js", "/assets/js/core/router.js"]
    _bad = []
    for _m in _mods:
        st_m, txt_m = _http(_m)
        if st_m != 200 or len(txt_m) < 100:
            _bad.append("%s(%s)" % (_m, st_m))
    check("F6b import 图内 5 个代表模块均可取",
          not _bad, f"取不到: {_bad}")

    _css_bad = []
    for _i in range(1, 9):
        _p = sorted((_ROOT / "web" / "css").glob(f"{_i}-*.css"))
        if not _p:
            _css_bad.append(f"{_i}-*")
            continue
        st_c, txt_c = _http("/assets/css/" + _p[0].name)
        if st_c != 200 or len(txt_c) < 500:
            _css_bad.append("%s(%s)" % (_p[0].name, st_c))
    check("F6c 8 片 CSS 均可取且非空", not _css_bad, f"异常: {_css_bad}")

    st, txt = _http("/some/deep/hash/route")
    check("F7 未知路径回落 index.html（hash 路由）",
          st == 200 and 'id="app"' in txt, f"status={st}")

    # F7b（2026-10-26 故障回归锁）：机器接口命名空间下的未知路径必须 404 JSON。
    # 当时这四个 GET 全部返回 200 + 5013 B HTML —— 对浏览器无害，对 MCP / OAuth
    # 客户端是「状态码成功、解析失败」的哑火，现场只表现为「网页 AI 连不上」。
    for _p in ("/api/nope", "/.well-known/nope", "/oauth/nope", "/mcp/reader"):
        st_x, txt_x = _http(_p)
        check(f"F7b 未知机器接口 {_p} ⇒ 404 JSON（不回 index.html）",
              st_x == 404 and txt_x.lstrip().startswith("{")
              and "<!doctype" not in txt_x.lower(),
              f"status={st_x} body={txt_x[:120]}")

    # F7c：同一路径的 POST 仍是 405（catch-all 默认只 GET）。这是**基线锁**：
    # 若将来把 catch-all 放开成全方法，F7c 会红，提醒复核「未知路径是否会写盘」。
    st_p, _ = _http("/mcp/reader", "POST", {})
    check("F7c 未知档位路径的 POST ⇒ 405（catch-all 未被放开成全方法）",
          st_p == 405, f"status={st_p}")

    # F7f：非机器前缀的深路径**必须仍然回落首页** —— 与 F7b 成对，防止改过头，
    # 把 hash 路由的「刷新不 404」一并改坏。用 /console 这种「像页面但不存在」
    # 的路径，贴近「用户收藏了一个早已改名的页面」的真实场景。
    st_f, txt_f = _http("/console")
    check("F7f 非机器前缀深路径仍回落 index.html（hash 路由不回归）",
          st_f == 200 and 'id="app"' in txt_f, f"status={st_f}")

    # F12：v1.7.0 的 /mcp 反代 —— 真上游、真 SSE。裸 HTTP 直发 initialize，
    # 断言拿到 ai-memory 的 serverInfo。这是「MCP 客户端只填一个 URL 就能连上」
    # 最低限度的真实证据：不 mock、不进程内直调（v3 的两条判死项都守住）。
    _req_mcp = urllib.request.Request(
        base + "/mcp", method="POST",
        data=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "1"}},
        }).encode("utf-8"))
    _req_mcp.add_header("Content-Type", "application/json")
    _req_mcp.add_header("Accept", "application/json, text/event-stream")
    try:
        with urllib.request.urlopen(_req_mcp, timeout=60) as _r_m:
            st_m, txt_m = _r_m.status, _r_m.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as _e_m:
        st_m, txt_m = _e_m.code, _e_m.read().decode("utf-8", "replace")
    check("F12 POST /mcp 经反代完成 MCP initialize（真上游 + SSE）",
          st_m == 200 and '"protocolVersion"' in txt_m and "ai-memory" in txt_m,
          f"status={st_m} body={txt_m[:200]}")

    # F12b~F12d（2026-10-27）：GET 版只读调用**真往返**。D15~D19 只证明边界，
    # 这里证明「地址栏传参」真的能拿到工具结果 —— 两者缺一：只有边界会变成
    # 「安全但不可用」，只有往返会变成「能用但没边界」。
    import urllib.parse as _up
    st_g, txt_g = _http("/mcp?tool=memory_stats")
    jg = json.loads(txt_g) if st_g == 200 else {}
    check("F12b GET /mcp?tool=memory_stats 真往返（只读调用可用）",
          st_g == 200 and jg.get("ok") is True and jg.get("tool") == "memory_stats"
          and bool(str(jg.get("text") or "").strip()),
          f"status={st_g} body={txt_g[:200]}")

    st_t, txt_t = _http("/mcp?tool=memory_stats&format=text")
    _want_text = str(jg.get("text") or "").strip()
    check("F12c GET &format=text 与 JSON 里的 text 字段逐字一致（纯文本出口）",
          st_t == 200 and bool(_want_text) and txt_t.strip() == _want_text,
          f"status={st_t} 长度={len(txt_t)} 期望={len(_want_text)}")

    _args = _up.quote(json.dumps({"keyword": "测试", "limit": 1}, ensure_ascii=False))
    st_a, txt_a = _http(f"/mcp?tool=memory_search&args={_args}")
    ja = json.loads(txt_a) if st_a == 200 else {}
    check("F12d GET args=<JSON> 传类型化参数（search 真往返）",
          st_a == 200 and ja.get("ok") is True
          and ja.get("arguments") == {"keyword": "测试", "limit": 1},
          f"status={st_a} body={txt_a[:200]}")

    # F13b（2026-10-27）：访问日志真跑一轮 —— 先调一次工具，再确认它被记下来。
    # 这条不能只靠 D/T 段：那两段用的是假上游，只能证明「写入路径对」，
    # 证明不了「真实调用真的落进 audit.jsonl」。
    st_l, txt_l = _http("/api/audit?limit=50")
    jl = json.loads(txt_l) if st_l == 200 else {}
    check("F13b /api/audit 在真实例上可用且返回结构化事件",
          st_l == 200 and jl.get("ok") is True
          and isinstance(jl.get("events"), list) and bool(jl.get("kinds")),
          f"status={st_l} body={txt_l[:200]}")

    st, txt = _http("/api/call", "POST", {"tool": "memory_stats", "arguments": {}})
    j = json.loads(txt) if st == 200 else {}
    check("F8 POST /api/call 真往返 memory_stats",
          st == 200 and j.get("ok") is True and j.get("tool") == "memory_stats",
          f"status={st} body={txt[:160]}")

    st_l2, txt_l2 = _http("/api/audit?limit=50&kind=tool")
    jl2 = json.loads(txt_l2) if st_l2 == 200 else {}
    _tool_ev = [e for e in (jl2.get("events") or [])
                if e.get("target") == "memory_stats" and e.get("action") == "tool.call"]
    check("F13c 刚才那次 /api/call 被记进审计（谁·何时·干了什么）",
          st_l2 == 200 and bool(_tool_ev)
          and bool(_tool_ev[0].get("actor")) and bool(_tool_ev[0].get("t")),
          f"status={st_l2} events={[e.get('action') for e in (jl2.get('events') or [])][:5]}")

    # F13d（2026-10-28）：耗时必须是**数值字段**，并且 detail 里不再重复它。
    # 前半句保「界面能排序/着色」，后半句防「两边都写」—— 那样耗时会出现两次，
    # 而第二次是被拼进 detail 的字符串，正则一改就错位。
    check("F13d tool.call 审计带数值 ms，detail 不再拼耗时",
          bool(_tool_ev) and isinstance(_tool_ev[0].get("ms"), (int, float))
          and _tool_ev[0]["ms"] > 0
          and "ms" not in str(_tool_ev[0].get("detail") or ""),
          f"ms={(_tool_ev[0] if _tool_ev else {}).get('ms')!r} "
          f"detail={(_tool_ev[0] if _tool_ev else {}).get('detail')!r}")

    # F13e（2026-10-29）：记忆库改走 /api/library 后，审计**不能静默断掉**。
    #      换端点的风险不是报错，而是「读取行为从访问日志里消失」—— 改之前浏览
    #      记忆库每次都是 /api/call ⇒ 一条 tool.call(target=memory_list)，改完若不补
    #      就一条都没有，而界面照常工作，没人会发现。
    #      这里同时钉住取舍：**首页记一条、翻页零增量**（545 条要翻 14 页，
    #      每页一条会把日志刷满）。用「增量」而不是「绝对条数」断言，是为了不受
    #      本文件前面 F3d/F3f 已经打过几次首页请求影响。
    def _lib_audit_n() -> int:
        _st, _tx = _http("/api/audit?limit=100&kind=tool")
        _j = json.loads(_tx) if _st == 200 else {}
        return len([e for e in (_j.get("events") or [])
                    if e.get("target") == "memory_list"
                    and "分页读取" in str(e.get("detail") or "")])

    _n0 = _lib_audit_n()
    _http("/api/library?offset=5&limit=5")
    _http("/api/library?offset=10&limit=5")
    _n1 = _lib_audit_n()
    _http("/api/library?offset=0&limit=5")
    _n2 = _lib_audit_n()
    check("F13e 记忆库分页审计：首页记一条、翻页零增量",
          _n1 == _n0 and _n2 == _n0 + 1,
          f"翻页前={_n0} 两次翻页后={_n1} 再来一次首页={_n2}")

    # 契约：阈值是**整状态写**（前端 saveThresholds 也把 draft 的全部键一起提交）。
    # 因此「只给一个键」必须被明确拒绝，而不是静默写半份配置。
    st, txt = _http("/api/thresholds")
    all_keys = {k: v["value"] for k, v in json.loads(txt)["keys"].items()}
    st_p, txt_p = _http("/api/thresholds", "POST",
                        {"values": {"heat_hot_min": 7}})
    check("F9a 不完整键集 ⇒ 400 且明确列出缺失键（整状态写契约）",
          st_p == 400 and "缺少配置键" in txt_p,
          f"status={st_p} body={txt_p[:160]}")

    st, txt = _http("/api/thresholds", "POST",
                    {"values": dict(all_keys, heat_hot_min=7, lock_timeout=12)})
    j = json.loads(txt) if st == 200 else {}
    st2, txt2 = _http("/api/thresholds")
    kk = (json.loads(txt2).get("keys") or {}) if st2 == 200 else {}
    got, got2 = kk.get("heat_hot_min", {}).get("value"), kk.get("lock_timeout", {}).get("value")
    check("F9b 阈值写→读往返（heat_hot_min=7 / lock_timeout=12）",
          st == 200 and j.get("ok") is True and got == 7 and got2 == 12
          and (_TMP / "vault" / "memory.toml").is_file(),
          f"status={st} read_back=({got},{got2}) body={txt[:140]}")
    check("F10 阈值只写 memory.toml，vault 里 *.md 未被改动",
          len(list(_VAULT.glob("*.md"))) == 3
          and all("heat_hot_min" not in p.read_text(encoding="utf-8")
                  for p in _VAULT.glob("*.md")), "")
finally:
    for p in (p_web, p_mcp):
        try:
            p.terminate(); p.wait(timeout=8)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    try:
        lf.close(); lf2.close()
    except Exception:
        pass

# =====================================================================
section("W 访问日志落点（放进记忆库当附件，2026-11-08）")

# 绝对路径：与老行为完全一致，老部署零影响。
_abs_audit = _TMP / "abs-audit" / "audit.jsonl"
os.environ["AI_MEMORY_WEB_AUDIT"] = str(_abs_audit)
check("W1 绝对路径原样使用（老部署零影响）",
      web_console.resolve_audit_path(_vdir) == _abs_audit,
      repr(web_console.resolve_audit_path(_vdir)))

# 相对路径：按 vault 解析 —— 这一行就是「日志进记忆库、随 FNS 同步」。
os.environ["AI_MEMORY_DIR"] = str(_VAULT)
os.environ["AI_MEMORY_WEB_AUDIT"] = "附件/日志/audit.jsonl"
_rel_audit = _VAULT / "附件" / "日志" / "audit.jsonl"
check("W2 相对路径按 AI_MEMORY_DIR（vault）解析",
      web_console.resolve_audit_path(_vdir) == _rel_audit,
      repr(web_console.resolve_audit_path(_vdir)))

_meta_rel = web_console.audit_path_report(_rel_audit)
check("W3 落点预检：识别「在记忆库内」且可写",
      _meta_rel["in_vault"] is True and _meta_rel["writable"] is True
      and "fns-sync" in _meta_rel["note"], f"meta={_meta_rel}")

# 相对路径但 vault 未配置：退回配置目录，并且必须在日志里说清楚 ——
# 静默改落点比直接报错更难查。
os.environ.pop("AI_MEMORY_DIR", None)
check("W4 相对路径但无 vault ⇒ 退回配置目录",
      web_console.resolve_audit_path(_vdir) == _vdir / "audit.jsonl",
      repr(web_console.resolve_audit_path(_vdir)))

# 父路径是普通文件 ⇒ 往上探到的祖先不是目录，预检必须判不可写。
_blocked = _TMP / "blocked-audit"
_blocked.write_text("x", encoding="utf-8")
_meta_bad = web_console.audit_path_report(_blocked / "audit.jsonl")
check("W5 父路径是普通文件 ⇒ 预检判为不可写且给出原因",
      _meta_bad["writable"] is False and "丢弃" in _meta_bad["note"],
      f"meta={_meta_bad}")

# 恢复：后续用例与收尾还原都依赖这两个变量回到 V 段的口径。
os.environ["AI_MEMORY_DIR"] = str(_VAULT)
os.environ["AI_MEMORY_WEB_AUDIT"] = str(_vdir / "audit.jsonl")

# =====================================================================
for k, v in _BASELINE.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v
shutil.rmtree(_TMP, ignore_errors=True)

print(f"\n==== 结果: {len(_passed)} passed / {len(_failed)} failed ====")
if _failed:
    print("失败项:")
    for f in _failed:
        print(f"  - {f}")
    sys.exit(1)
sys.exit(0)
