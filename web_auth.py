"""控制台登录与会话（2026-10-21，方案 A：账号密码 + 签名 Cookie）。

为什么不用 passlib / bcrypt / itsdangerous
------------------------------------------
控制台镜像的 ``requirements.txt`` 只有 ``mcp`` 一个依赖（其余全是它的传递依赖）。
在这台设备上 ``pip install`` 受容器 DNS 影响会直接失败（2026-10-20 踩过，
NameResolutionError），所以**新增任何依赖都是一次部署风险**。
所需能力标准库全有：``hashlib.scrypt`` 做口令哈希、``hmac`` 做签名、
``secrets`` 做随机数、``base64`` 做编码。

三个设计取舍
------------
1. **会话是无状态签名 Cookie**，服务端不存 session 表 ⇒ 控制台重启不踢人，
   也不需要清理过期项。代价是「单独踢掉某一个会话」做不到 —— 只能换密钥
   （即全场失效）。单人使用的调试台，这个代价可接受。
2. **签名密钥优先取 ``AI_MEMORY_WEB_SECRET``，缺省从 ``AI_MEMORY_WEB_TOKEN``
   派生**。这样不新增必填配置；而「换掉 token」天然等于「所有会话立即失效」，
   是一个不需要额外操作的应急手段。
3. **Cookie 的 ``Secure`` 属性跟随部署形态**（确认走 HTTPS 才加）。在纯 HTTP 下
   加 ``Secure`` 不是更安全，而是浏览器直接不存 —— 登录功能整个失效。

Cookie 里只放 ``{u, iat, exp}``，不含密码、不含 token、不含任何权限位。
权限模型是「登录了就全通」，与既有单 token 模型一致（本次不引入多用户/角色）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time

# scrypt 参数：n 必须是 2 的幂。
#
# 2026-10-22 由 2^14 提到 **2^16**：原值只占 16 MiB，是 OWASP 推荐区间的下沿，
# 在有公网入口 + 多用户之后不够。2^16 / r=8 占 64 MiB，接近 OWASP 首选档
# （2^17 要 128 MiB，本设备装不下：容器上限 + 基础占用会 OOM）。
#
# ⚠️ **必须显式给 maxmem**：``hashlib.scrypt`` 的 maxmem 默认 0 表示「用 OpenSSL
#    的默认上限 32 MiB」，而 2^16/r=8 需要 64 MiB ⇒ 不提就抛
#    ``ValueError: memory limit exceeded``，且是在**登录时**才炸。
SCRYPT_N = 2 ** 16
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16

#: 单次 scrypt 的内存需求 + 1 MiB 余量（公式见 RFC 7914：128 * n * r）。
def scrypt_maxmem(n: int, r: int) -> int:
    return 128 * int(n) * int(r) + (1 << 20)


#: 并发闸：每次校验最多占 64 MiB。若不限并发，4 个同时登录就是 256 MiB，
#: 直接越过容器上限被 OOM kill（整个控制台跟着死）。闸门值 2 意味着
#: 最坏 128 MiB + Python 基础占用，仍在 256 MiB 上限内；多出来的请求排队，
#: 表现为「登录慢一点」而不是「服务没了」。
_SCRYPT_GATE = threading.BoundedSemaphore(2)

#: 会话有效期（秒）。12 小时：覆盖一个工作日的使用，又不至于长期挂着。
SESSION_TTL = 12 * 3600
#: Cookie 名。不用 ``session`` 这种烂大街的名字，避免与反代/框架默认值撞车。
COOKIE_NAME = "am_session"


# ---------------------------------------------------------------------------
# 编码辅助：统一用去 padding 的 urlsafe base64，可直接放进 Cookie / URL
# ---------------------------------------------------------------------------
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


# ---------------------------------------------------------------------------
# 口令哈希
# ---------------------------------------------------------------------------
def hash_password(password: str, *, n: int = SCRYPT_N, r: int = SCRYPT_R,
                  p: int = SCRYPT_P) -> str:
    """把明文口令哈希成可入库的字符串。

    格式 ``scrypt:n:r:p:salt_b64:hash_b64`` —— 参数随哈希一起存，
    将来提高 n 时旧哈希仍能验证（按它自己记录的那组参数重算）。

    ⚠️ 分隔符用 ``:`` 而**不是** ``$``：哈希要写进 ``.env``，而部署脚本是
    ``set -a; . ./.env`` —— 在 shell 里 ``scrypt$16384$8$1$...`` 会被当成变量
    引用展开（``$16384`` 未定义 ⇒ 变成空串），哈希当场损坏，而且**只在登录时
    才暴露成「口令永远不对」**，极难联想回 .env。``:`` 与 urlsafe-base64 的
    字符集不冲突，也不会被任何 shell 解释。``verify_password`` 仍兼容旧的
    ``$`` 格式，防止已经生成过的人卡住。
    """
    if not password:
        raise ValueError("口令不能为空")
    salt = secrets.token_bytes(SALT_BYTES)
    with _SCRYPT_GATE:
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=n, r=r, p=p, dklen=SCRYPT_DKLEN,
                            maxmem=scrypt_maxmem(n, r))
    return f"scrypt:{n}:{r}:{p}:{_b64e(salt)}:{_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    """校验口令。**任何解析失败都返回 False**，不抛异常 —— 调用方只需要「过没过」。"""
    if not password or not stored:
        return False
    try:
        sep = "$" if "$" in stored else ":"
        parts = stored.split(sep)
        if len(parts) != 6:
            return False
        algo, n_s, r_s, p_s, salt_s, hash_s = parts
        if algo != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt, expected = _b64d(salt_s), _b64d(hash_s)
        with _SCRYPT_GATE:
            got = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                                 n=n, r=r, p=p, dklen=len(expected),
                                 maxmem=scrypt_maxmem(n, r))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


def needs_rehash(stored: str) -> bool:
    """存量哈希是否弱于当前参数。

    为什么必须有：把 ``SCRYPT_N`` 从 2^14 提到 2^16 只影响**新**哈希，
    已经存在的账号（含从旧版 ``.env`` 迁移过来的那个 admin）仍然按 2^14 验证。
    不提就是「参数改了，实际强度没变」—— 而且完全无声。
    """
    if not stored:
        return True
    try:
        sep = "$" if "$" in stored else ":"
        parts = stored.split(sep)
        if len(parts) != 6 or parts[0] != "scrypt":
            return True
        return int(parts[1]) < SCRYPT_N or int(parts[2]) < SCRYPT_R
    except (ValueError, TypeError):
        return True


# ---------------------------------------------------------------------------
# 会话：签名 Cookie
# ---------------------------------------------------------------------------
def derive_key(token: str, secret: str = "") -> bytes:
    """得出会话签名密钥。

    显式给了 ``secret`` 就用它；否则从 token 派生。派生时带一个用途标签，
    避免「同一把密钥被两个用途共用」——那样一处泄露会波及另一处。
    """
    base = (secret or token or "").encode("utf-8")
    if not base:
        # 没有密钥时不能签出任何有效会话：返回全零会让所有签名都相等。
        # 调用方应在此之前就判定「登录不可用」；这里抛错是为了快速失败。
        raise ValueError("缺少会话签名密钥（AI_MEMORY_WEB_SECRET / AI_MEMORY_WEB_TOKEN 均为空）")
    return hmac.new(base, b"ai-memory-web/session/v1", hashlib.sha256).digest()


def _sign(payload_b64: str, key: bytes) -> str:
    return _b64e(hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).digest())


def make_session(user: str, key: bytes, *, ttl: int = SESSION_TTL,
                 role: str = "", epoch: str = "",
                 now: float | None = None) -> str:
    """签发会话串：``<payload_b64>.<sig_b64>``。

    payload 从 2026-10-22 起多两个字段：

    * ``r`` = 角色。放进签名 payload 而非每次查表，是为了让中间件不必
      对每个请求都读一次 ``users.json``；真伪由签名保证。
    * ``e`` = 用户 epoch。**这是「单点吊销」的全部机制** —— 服务端拿它和
      ``users.json`` 里的当前值比对，不等就作废。改口令 / 改角色 / 禁用 /
      删号都会轮换 epoch，于是该用户的旧 Cookie 立刻失效（无状态会话也能踢人）。

    旧版 Cookie 没有这两个字段，会因 ``e`` 为空而被拒 ⇒ **升级后需要重新登录一次**，
    这是刻意的，不是 bug。
    """
    ts = int(now if now is not None else time.time())
    payload = json.dumps({"u": user, "iat": ts, "exp": ts + int(ttl),
                          "r": role, "e": epoch},
                         separators=(",", ":"), ensure_ascii=False)
    p = _b64e(payload.encode("utf-8"))
    return f"{p}.{_sign(p, key)}"


def read_session(cookie: str, key: bytes, *, now: float | None = None) -> dict | None:
    """校验并解出会话。**无效一律返回 None**（过期也算无效）。

    先验签再解析 payload —— 顺序不能反：先解析等于把不可信 JSON 送进 json.loads。
    """
    if not cookie or "." not in cookie:
        return None
    p, _, sig = cookie.rpartition(".")
    if not p or not sig:
        return None
    try:
        expect = _sign(p, key)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        data = json.loads(_b64d(p).decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    ts = now if now is not None else time.time()
    try:
        if int(data.get("exp", 0)) <= ts:
            return None
    except (TypeError, ValueError):
        return None
    if not data.get("u"):
        return None
    return data


# ---------------------------------------------------------------------------
# 登录失败限流
# ---------------------------------------------------------------------------
class LoginLimiter:
    """按来源 IP 计失败次数的滑动窗口限流。

    为什么必须有：口令可以短（人记得住的），没有限流就等于把爆破成本降到
    「脚本跑一晚上」。这条与 token 不同 —— 32 hex 的 token 不需要限流，
    因为它的搜索空间本身就够大；短口令则需要。

    纯内存实现：控制台是单进程，够用。重启后计数清零（可接受：重启本身
    不是攻击者能触发的）。表大小设上限，防止被大量伪造源 IP 撑爆内存。
    """

    def __init__(self, max_fails: int = 5, window: float = 300.0,
                 lock_for: float = 300.0, max_entries: int = 512) -> None:
        self.max_fails = max_fails
        self.window = window
        self.lock_for = lock_for
        self.max_entries = max_entries
        # ip -> [窗口内的失败时间戳, 锁定截止时间]
        self._state: dict[str, list] = {}

    def _prune(self, ip: str, now: float) -> list:
        rec = self._state.get(ip)
        if not rec:
            return [0.0, []]
        locked_until, stamps = rec[0], rec[1]
        stamps = [t for t in stamps if now - t < self.window]
        # 只有在「窗口内确实没有失败」**且**「不在锁定期」时才丢记录。
        # 早期版本漏了后半句：锁定瞬间 stamps 已被清空，下一次调用就把
        # locked_until 一并删掉，于是第 4 次尝试又能试 —— 限流形同虚设。
        if not stamps and locked_until <= now:
            self._state.pop(ip, None)
            return [0.0, []]
        return [locked_until, stamps]

    def blocked_for(self, ip: str, now: float | None = None) -> int:
        """剩余锁定秒数；0 表示可以尝试。"""
        now = now if now is not None else time.time()
        rec = self._state.get(ip)
        if not rec:
            return 0
        left = int(rec[0] - now)
        return left if left > 0 else 0

    def fail(self, ip: str, now: float | None = None) -> int:
        """记一次失败，返回剩余锁定秒数（0 = 还没锁）。"""
        now = now if now is not None else time.time()
        locked_until, stamps = self._prune(ip, now)
        stamps.append(now)
        if len(stamps) >= self.max_fails:
            locked_until = now + self.lock_for
            stamps = []          # 锁定后清空窗口，解锁时重新开始计数
        if len(self._state) >= self.max_entries and ip not in self._state:
            # 粗暴但够用：丢掉最早插入的一条，避免内存无界增长。
            self._state.pop(next(iter(self._state)), None)
        self._state[ip] = [locked_until, stamps]
        left = int(locked_until - now)
        return left if left > 0 else 0

    def reset(self, ip: str) -> None:
        self._state.pop(ip, None)
