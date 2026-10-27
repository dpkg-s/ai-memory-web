"""日志初始化与脱敏的回归测试（L1~L5）。

为什么单独成文件，不并进 ``test_web.py`` / ``test_oauth.py``：
那两个文件是**端到端**测试（真起进程、真发 HTTP），本文件测的是
``_ensure_app_logging()`` 这一个纯函数的行为边界 —— 包括「主机没配好」
这类端到端跑不出来的分支（``sys.stderr is None``）。混进去会让那两份
测试的语义变模糊，也会让它们的断言被迫依赖 logging 的全局状态。

⚠️ logging 是**进程级全局状态**。本文件的每条用例都在 ``try/finally`` 里
保存并恢复 ``handlers`` / ``level`` / ``propagate`` / ``sys.stderr``，
跑完不留痕，避免污染同一进程内的其他测试。

``tests/test_oauth.py`` 会先 import 本模块的同名父包？不会 —— 各测试文件
独立进程运行，互不影响；但为防「将来被打包一起跑」，隔离仍然照做。

用法：``python tests/test_logging.py``，退出码 0 = 全绿。
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
import tempfile
from pathlib import Path

# ---- 先把环境指到临时目录，再 import 被测模块（与 test_oauth.py 同法）----
_TMP = Path(tempfile.mkdtemp(prefix="ai-memory-logging-"))
os.environ["AI_MEMORY_DIR"] = str(_TMP / "vault")
(_TMP / "vault").mkdir(parents=True, exist_ok=True)
os.environ["AI_MEMORY_WEB_CONFIG"] = str(_TMP / "config.json")
os.environ["AI_MEMORY_WEB_TOKEN"] = "log-test-owner-token"
os.environ["AI_MEMORY_WEB_USER"] = "admin"
os.environ["AI_MEMORY_WEB_PASSWORD"] = "pw-log-test"
os.environ["AI_MEMORY_WEB_USERS"] = str(_TMP / "users.json")
os.environ["AI_MEMORY_WEB_TOKENS"] = str(_TMP / "tokens.json")
os.environ["AI_MEMORY_WEB_OAUTH_CLIENTS"] = str(_TMP / "oauth_clients.json")
os.environ.pop("AI_MEMORY_WEB_PUBLIC_URL", None)

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import httpx          # noqa: E402
import web_console    # noqa: E402

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


_LOGGER = logging.getLogger("ai-memory.web")

#: 起点状态。NOTSET(0) 是 ``logging.getLogger`` 拿到新 logger 时的默认值 ——
#: 用 0 而不是 INFO，才能让 L1 的「设置成 INFO」有可观测的变化。
_BASE_LEVEL = logging.NOTSET
_BASE_PROPAGATE = True


class _State:
    """保存/恢复 logger 全局状态 + ``sys.stderr``。

    写成上下文管理器而不是 ``setUp/tearDown``：本文件是脚本式测试
    （与另两个测试文件保持一致），没有 pytest 的生命周期可用。
    """

    def __enter__(self) -> _State:
        self._handlers = list(_LOGGER.handlers)
        self._level = _LOGGER.level
        self._propagate = _LOGGER.propagate
        self._stderr = sys.stderr
        return self

    def reset(self) -> None:
        """把 logger 清到「从未被配置」的状态，供每条用例独立起跑。"""
        _LOGGER.handlers.clear()
        _LOGGER.setLevel(_BASE_LEVEL)
        _LOGGER.propagate = _BASE_PROPAGATE

    def __exit__(self, *exc) -> None:
        sys.stderr = self._stderr
        _LOGGER.handlers.clear()
        for h in self._handlers:
            _LOGGER.addHandler(h)
        _LOGGER.setLevel(self._level)
        _LOGGER.propagate = self._propagate


# =====================================================================
section("L 日志初始化")

# L1 幂等：连续三次调用只能有一个 handler。
# 判据是 ``len(handlers) == 1``，不是「不报错」—— 重复添加不报错，
# 只会让每行日志打印三遍，属于最难察觉的一类退化。
with _State() as st:
    st.reset()
    for _ in range(3):
        web_console._ensure_app_logging()
    check("L1 连续三次调用 ⇒ 只挂一个 handler",
          len(_LOGGER.handlers) == 1, f"handlers={len(_LOGGER.handlers)}")
    check("L1 级别被设为 INFO、propagate 关掉",
          _LOGGER.level == logging.INFO and _LOGGER.propagate is False,
          f"level={_LOGGER.level} propagate={_LOGGER.propagate}")

# L2 宿主优先：宿主已挂 handler 且开着 DEBUG 时，不得覆盖。
# 「不覆盖级别」是这条用例的核心 —— 只测「不重复添加」会漏掉
# 「handler 没多，但 DEBUG 被压成 INFO」这种更隐蔽的越权。
with _State() as st:
    st.reset()
    host = logging.StreamHandler(io.StringIO())
    host.setFormatter(logging.Formatter("HOST|%(message)s"))
    _LOGGER.addHandler(host)
    _LOGGER.setLevel(logging.DEBUG)
    web_console._ensure_app_logging()
    check("L2 宿主已挂 handler ⇒ 不再添加",
          len(_LOGGER.handlers) == 1, f"handlers={len(_LOGGER.handlers)}")
    check("L2 宿主的 DEBUG 级别未被改成 INFO",
          _LOGGER.level == logging.DEBUG, f"level={_LOGGER.level}")
    check("L2 宿主的 propagate 未被改动",
          _LOGGER.propagate is True, f"propagate={_LOGGER.propagate}")

# L3 无 stderr：pythonw 未重定向的真实分支。
# 期望「三不」：不崩溃、不添加无效 handler、不改任何配置。
# 这里刻意先把 level 设成 WARNING、propagate 设成 True，再看它们有没有被动过。
with _State() as st:
    st.reset()
    _LOGGER.setLevel(logging.WARNING)
    _LOGGER.propagate = True
    sys.stderr = None
    crashed = False
    try:
        web_console._ensure_app_logging()
        _LOGGER.info("这条不应写出，也不应抛异常")
    except Exception as e:                                   # noqa: BLE001
        crashed = True
        check("L3 sys.stderr 为 None ⇒ 不抛异常", False,
              f"{type(e).__name__}: {e}")
    if not crashed:
        check("L3 sys.stderr 为 None ⇒ 不抛异常", True)
    check("L3 未添加无效 handler",
          len(_LOGGER.handlers) == 0, f"handlers={len(_LOGGER.handlers)}")
    check("L3 未改动级别与 propagate",
          _LOGGER.level == logging.WARNING and _LOGGER.propagate is True,
          f"level={_LOGGER.level} propagate={_LOGGER.propagate}")
    sys.stderr = st._stderr        # 立刻还原，后续用例要用

# L4 装配生效：走真实入口 ``create_app()``，而不是直接调内部函数。
# 这条锁的是「调用点还在」。哪天有人把 :3115 那行删了，L1~L3 仍全绿，
# 只有 L4 会红 —— 它测的是接线，不是实现。
with _State() as st:
    st.reset()
    # 刻意**不传 cfg**：生产也是 ``create_app()`` 无参调用，config() 在日志
    # 初始化之后才执行。若这里写成 ``create_app(web_console.config())``，
    # config() 会先跑，掩盖掉「初始化必须早于首次 logger.*」这条顺序约束。
    app = web_console.create_app()
    handlers = list(_LOGGER.handlers)
    check("L4 create_app() 后 logger 已挂 handler",
          len(handlers) == 1, f"handlers={len(handlers)}")
    check("L4 挂的是写往 stderr 的 StreamHandler",
          bool(handlers) and isinstance(handlers[0], logging.StreamHandler)
          and handlers[0].stream is sys.stderr,
          f"type={type(handlers[0]).__name__ if handlers else None}")
    check("L4 应用对象可正常构造（未因日志初始化而破坏装配）",
          app is not None, "create_app 返回 None")

    # L5 脱敏：用**伪造**令牌打一次 401，抓真实 handler 的输出检查。
    # 手法是把已有 handler 的 stream 临时换成 StringIO —— 不去 addHandler，
    # 否则会改变被测对象本身（且 _ensure_app_logging 也不会再跑）。
    _FAKE = "amt_FAKE_LOG_PROBE_9f3c1d7e5b2a4c60"
    _REAL = os.environ["AI_MEMORY_WEB_TOKEN"]
    buf = io.StringIO()
    orig_stream = handlers[0].stream if handlers else None
    try:
        if handlers:
            handlers[0].stream = buf

        async def _one() -> int:
            tr = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=tr, base_url="http://t",
                                         timeout=20) as c:
                r = await c.post("/mcp", headers={
                    "Authorization": f"Bearer {_FAKE}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"},
                    content=b'{"jsonrpc":"2.0","id":1,"method":"initialize"}')
                return r.status_code

        status = asyncio.run(_one())
    finally:
        if handlers and orig_stream is not None:
            handlers[0].stream = orig_stream

    out = buf.getvalue()
    check("L5 伪令牌请求 /mcp ⇒ 401（前置条件成立）", status == 401,
          f"status={status}")
    check("L5 失败原因被记录为 token_rejected",
          "reason=token_rejected" in out, f"out={out[:160]!r}")
    check("L5 日志不含伪令牌明文", _FAKE not in out,
          "日志里出现了 Authorization 里的令牌")
    check("L5 日志不含真实令牌明文", _REAL not in out,
          "日志里出现了环境变量里的真实令牌")
    check("L5 日志不含 Authorization 头文本",
          "Authorization" not in out and "Bearer" not in out,
          f"out={out[:160]!r}")

# =====================================================================
print()
print("=" * 60)
print(f"通过 {len(_passed)} / 共 {len(_passed) + len(_failed)}")
if _failed:
    print("失败用例：")
    for n in _failed:
        print("  -", n)
    sys.exit(1)
print("全部通过")
sys.exit(0)
