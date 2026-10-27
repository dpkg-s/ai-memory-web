# -*- coding: utf-8 -*-
"""端到端验证：令牌的数据视野是否真的改变了打到 MCP 的端点路径。

为什么不用单元测试代替：单测只能证明 ROLE_CLEARANCE 表里写着 reader，
证明不了「请求最终走的是 /mcp/reader」。中间还隔着 AuthMiddleware →
request.state.auth_clearance → /api/call → resolve_mcp 四跳，任何一跳断掉，
单测全绿而线上仍打 owner 端点 —— 那是最危险的一种「绿」。

做法：起一个**假上游**只做两件事 —— 记录收到的请求路径、回 400。
不碰真实 vault、不碰真实 MCP（临时目录 + 临时库）。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="web-cleare2e-"))
_VAULT = _TMP / "vault"
_VAULT.mkdir()

os.environ["AI_MEMORY_DIR"] = str(_VAULT)
os.environ["AI_MEMORY_WEB_USERS"] = str(_TMP / "users.json")
os.environ["AI_MEMORY_WEB_TOKENS"] = str(_TMP / "tokens.json")
os.environ["AI_MEMORY_WEB_CONFIG"] = str(_TMP / "config.json")
os.environ["AI_MEMORY_WEB_TOKEN"] = "admin-bootstrap-token-for-probe"
os.environ["AI_MEMORY_SOURCE_CONTEXT"] = "web-e2e"

HITS: list[tuple[str, str]] = []


class _Recorder(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):                                  # noqa: N802
        HITS.append(("POST", self.path))
        body = b'{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"probe"}}'
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                   # noqa: N802
        HITS.append(("GET", self.path))
        self.send_response(400)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):                          # 静音
        pass


def main() -> int:
    srv = HTTPServer(("127.0.0.1", 0), _Recorder)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    os.environ["AI_MEMORY_WEB_MCP"] = f"http://127.0.0.1:{port}/mcp"

    sys.path.insert(0, r"D:\ai-memory-template-work\web-console")
    import web_console

    cfg = web_console.config()
    app = web_console.create_app(cfg)

    from starlette.testclient import TestClient

    ok = fail = 0

    def check(label, cond, extra=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  PASS  {label} {extra}")
        else:
            fail += 1
            print(f"  FAIL  {label} {extra}")

    admin = "admin-bootstrap-token-for-probe"
    with TestClient(app) as c:
        # 1) admin 令牌的会话视野
        r = c.get("/api/session", headers={"Authorization": f"Bearer {admin}"})
        sess = r.json() if r.status_code == 200 else {}
        check("admin 会话 role=admin", sess.get("role") == "admin", str(sess.get("role")))
        check("admin 会话视野=owner", sess.get("clearance") == "owner",
              str(sess.get("clearance")))

        # 2) 用 admin 签发 viewer 令牌
        r = c.post("/api/tokens", headers={"Authorization": f"Bearer {admin}"},
                   json={"name": "probe-viewer", "role": "viewer", "expires_in": 3600})
        tok = ""
        if r.status_code == 200:
            body = r.json()
            tok = body.get("token") or (body.get("data") or {}).get("token") or ""
        check("签发 viewer 令牌成功", bool(tok), f"HTTP {r.status_code}")

        # 3) 越权：viewer 令牌不能签 member 视野
        r = c.post("/api/tokens", headers={"Authorization": f"Bearer {admin}"},
                   json={"name": "probe-bad", "role": "viewer", "clearance": "owner"})
        check("viewer 令牌要 owner 视野被拒", r.status_code == 400, f"HTTP {r.status_code}")

        # 4) 核心：viewer 令牌调工具，看实际打到哪个路径
        HITS.clear()
        r = c.post("/api/call", headers={"Authorization": f"Bearer {tok}"},
                   json={"tool": "memory_search", "arguments": {"keyword": "x"}})
        paths = [p for _, p in HITS]
        check("viewer 调用到达上游（非 403）", r.status_code != 403,
              f"HTTP {r.status_code}")
        check("viewer 打到 /mcp/reader（不是 /mcp）",
              any(p.startswith("/mcp/reader") for p in paths), str(paths))

        # 5) 反向：admin 令牌仍打 /mcp
        HITS.clear()
        c.post("/api/call", headers={"Authorization": f"Bearer {admin}"},
               json={"tool": "memory_search", "arguments": {"keyword": "x"}})
        apaths = [p for _, p in HITS]
        check("admin 打到 /mcp（owner 端点）",
              any(p.rstrip("/") == "/mcp" for p in apaths), str(apaths))

        # 6) viewer 不能用写工具（工具组拦截仍在）
        r = c.post("/api/call", headers={"Authorization": f"Bearer {tok}"},
                   json={"tool": "memory_write", "arguments": {"title": "x", "content": "y"}})
        check("viewer 调写工具被 403", r.status_code == 403, f"HTTP {r.status_code}")

        # 7) 只读模式（2026-10-26）：admin 身份 + owner 视野 + ro。
        #    这是主人最常用的形态 —— 别的设备能读完整库，不许改。
        #    验证同样要落到「实际打哪个路径」上：/mcp/owner-ro 才是硬边界，
        #    而 /api/call 那层 403 只是友好提示。
        r = c.post("/api/tokens", headers={"Authorization": f"Bearer {admin}"},
                   json={"name": "probe-ro", "role": "admin",
                         "clearance": "owner", "access": "ro", "expires_in": 3600})
        rotok = ""
        if r.status_code == 200:
            rb = r.json()
            rotok = rb.get("token") or (rb.get("data") or {}).get("token") or ""
        check("签发 owner 视野 + 只读的令牌成功", bool(rotok), f"HTTP {r.status_code}")

        r = c.get("/api/session", headers={"Authorization": f"Bearer {rotok}"})
        rsess = r.json() if r.status_code == 200 else {}
        check("只读令牌会话带 access=ro", rsess.get("access") == "ro",
              str(rsess.get("access")))
        check("只读令牌会话 writable=false", rsess.get("writable") is False,
              str(rsess.get("writable")))
        check("只读令牌视野仍是 owner（读得全）", rsess.get("clearance") == "owner",
              str(rsess.get("clearance")))

        HITS.clear()
        c.post("/api/call", headers={"Authorization": f"Bearer {rotok}"},
               json={"tool": "memory_search", "arguments": {"keyword": "x"}})
        rpaths = [p for _, p in HITS]
        check("只读令牌的读工具打 /mcp/owner-ro（不是 /mcp）",
              any(p.startswith("/mcp/owner-ro") for p in rpaths), str(rpaths))

        r = c.post("/api/call", headers={"Authorization": f"Bearer {rotok}"},
                   json={"tool": "memory_write", "arguments": {"title": "x", "content": "y"}})
        check("只读令牌调写工具被 403", r.status_code == 403, f"HTTP {r.status_code}")

        # 8) MCP 反代同样要带 -ro：别的设备的 AI 客户端直连的是 /mcp，
        #    如果这一步丢了只读意图，前面的 /api/call 拦得再严也白搭。
        HITS.clear()
        c.post("/mcp", headers={"Authorization": f"Bearer {rotok}"},
               json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        mpaths = [p for _, p in HITS]
        check("只读令牌的 /mcp 反代打 /mcp/owner-ro",
              any(p.startswith("/mcp/owner-ro") for p in mpaths), str(mpaths))

    srv.shutdown()
    print(f"\n==== 结果: {ok} passed / {fail} failed ====")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
