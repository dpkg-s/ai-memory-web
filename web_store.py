"""用户与访问令牌的持久化（2026-10-22）。

为什么单独一个模块
------------------
``web_auth.py`` 只负责**密码学原语**（哈希、签名、会话编解码），
``web_console.py`` 只负责**装配**（HTTP 路由、中间件）。
关系型数据（谁能登录、谁能用哪枚令牌）有自己的一套不变量 ——
「改口令要让旧会话失效」「吊销令牌要立刻生效」「计次要落盘」——
把它塞进任何一边都会让那一边开始关心对方的细节。

三个刻意的设计
--------------
1. **令牌只存哈希**（sha256 hex），明文仅在创建那一刻返回一次。
   这与口令哈希不同：token 是 32 字节随机串、搜索空间足够大，不需要慢哈希；
   但**必须**存哈希，否则 ``tokens.json`` 泄露就等于全部令牌泄露。

2. **会话靠 epoch 失效，不靠黑名单**。用户记录里有一个随机 ``epoch``，
   会话 payload 也带一份；改口令 / 改角色 / 禁用 / 删除时轮换 epoch，
   该用户所有旧会话立即作废。无状态会话因此也能做到「单点吊销」，
   代价只是一次字段比对。

3. **计次带去重窗口**。MCP 的 Streamable HTTP 一次工具调用会产生 2–3 个
   HTTP 请求（初始化 POST / SSE GET / 调用 POST）。若每个请求都算一次，
   用户设「限 100 次」实际只能调 30 来个工具。所以同一令牌在
   ``usage_window`` 秒内的重复请求只计 1 次 —— 语义贴近「能调多少次工具」。

写盘策略：内存里修改，``flush()`` 才落盘，且用「临时文件 + os.replace」保证原子性。
计次这类高频写走节流（默认每 5 秒或每 50 次），避免把 eMMC 写坏。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path

import web_auth

#: 角色 → 允许的 ``TOOL_GROUPS`` 键。``None`` 表示不限制。
#: 组定义在 ``web_console.TOOL_GROUPS``（唯一事实源），这里只引用它的键名。
ROLE_TOOLS = {
    "admin": None,                                  # 全部工具 + 管理面
    "operator": None,                               # 全部工具，不管人
    "viewer": {"search", "graph", "health"},        # 纯只读组
}

#: 角色强弱顺序，用于「不能给比自己更高的角色」这类判断。
ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}

#: 角色 → 默认的**数据视野**（MCP 的 clearance 档位）。这与「工具组」是正交的
#: 第二个维度：``ROLE_TOOLS`` 决定能调哪些工具，本表决定「即便能调，也只看得见
#: 哪些密级的记忆」。
#:
#: 为什么必须分开：控制台后端连 MCP 时如果一律走 ``/mcp``（owner 端点），那么
#: viewer 令牌虽然只能调 ``memory_search``，返回的却是全库 —— 含 sensitive /
#: secret。工具粒度收紧了、数据粒度没收紧，等于只锁了门没锁抽屉。
#:
#: 映射依据是各角色已有的语义，不新增概念：
#:   admin    全权          → owner
#:   operator 可写普通条目   → member（读 internal + sensitive）
#:   viewer   纯只读         → reader（读 internal，读不到 sensitive / secret）
ROLE_CLEARANCE = {
    "admin": "owner",
    "operator": "member",
    "viewer": "reader",
}

#: 数据视野强弱顺序。令牌可以声明比角色**更低**（更保守）的档位，但不得更高 ——
#: 与「不能签出比自己更高权限的令牌」同一条原则。
CLEARANCE_RANK = {"guest": 0, "reader": 1, "member": 2, "owner": 3}

#: 缺省视野（角色未知时的兜底）。取最保守的一档，脏数据只会「看不到」。
DEFAULT_CLEARANCE = "reader"

#: 读写模式（2026-10-26）。这是与视野**正交**的第二根轴：视野决定「看得见多少」，
#: 本字段决定「能不能改」。之所以不把「只读」做成第五个视野档位：档位 4 × 读写 2
#: = 8 种组合，用档位名表达会组合爆炸，且每加一档都要重算各档的读权关系。
#:
#: 服务端侧对应的判据是 `server.current_writable()`（档位允许写 AND 请求允许写），
#: 端点形态是 `/mcp/<档位>-ro`。这一层只负责把这个意图**记在令牌上**并传下去。
ACCESS_MODES = ("rw", "ro")

#: 角色默认读写模式。刻意保持 admin / operator 可写 —— 不改变任何存量令牌的行为；
#: viewer 本来就是只读视野，额外给写标志没有意义。**不给远程令牌默认只读**是
#: 有意的：那会让所有在线设备升级后突然写不进去，属于无声的行为变更。
ROLE_ACCESS = {"admin": "rw", "operator": "rw", "viewer": "ro"}
DEFAULT_ACCESS = "rw"


def access_of(role: str, access: str | None = None) -> str:
    """取实际生效的读写模式：显式声明优先，否则由角色推导。

    与 ``clearance_of`` 同一取向：非法值回落角色默认而不是抛错 —— 这层是读取
    路径，存量令牌没有该字段，读的时候不能因此炸掉。
    """
    if access in ACCESS_MODES:
        return access
    return ROLE_ACCESS.get(role, DEFAULT_ACCESS)


def clearance_of(role: str, clearance: str | None = None) -> str:
    """取实际生效的数据视野：显式声明优先，否则由角色推导。

    非法值一律回落到该角色的默认档，而不是抛错 —— 这一层是**读取**路径，
    存量令牌可能没有 clearance 字段，读的时候不能因此炸掉。
    """
    if clearance in CLEARANCE_RANK:
        return clearance
    return ROLE_CLEARANCE.get(role, DEFAULT_CLEARANCE)

#: 令牌明文前缀。带上它才能在日志/界面上与口令一眼区分开，也便于密钥扫描器识别。
TOKEN_PREFIX = "amt_"


class StoreError(Exception):
    """配置层错误：凭据文件损坏、参数非法等。调用方通常映射成 400。"""


def _now() -> float:
    return time.time()


def _atomic_write(path: Path, payload: dict) -> None:
    """临时文件 + ``os.replace``。直接 truncate 写会让断电留下半截 JSON。"""
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


def _read_json(path: Path, fallback: dict) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return fallback
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise StoreError(f"{path.name} 不是合法 JSON：{e}") from e
    if not isinstance(data, dict):
        raise StoreError(f"{path.name} 顶层必须是对象")
    return data


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 用户表
# ---------------------------------------------------------------------------
class UserStore:
    """用户表的读写与校验。

    ``bootstrap()`` 用于从旧版单用户配置（``AI_MEMORY_WEB_USER`` +
    ``AI_MEMORY_WEB_PASSWORD_HASH``）平滑迁移：文件不存在时自动建一个 admin。
    这样升级不需要手工迁移步骤，也不会出现「升完没账号进不去」。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = _read_json(self.path, {"version": 1, "users": []})
        self._data.setdefault("users", [])

    # -- 内部 --------------------------------------------------------------
    def _save(self) -> None:
        _atomic_write(self.path, self._data)

    def _find(self, name: str) -> dict | None:
        for u in self._data["users"]:
            if u.get("name") == name:
                return u
        return None

    @staticmethod
    def _public(u: dict) -> dict:
        """对外视图：**绝不带 hash 与 epoch**。"""
        return {
            "name": u.get("name", ""),
            "role": u.get("role", "viewer"),
            "enabled": bool(u.get("enabled", True)),
            "created_at": u.get("created_at"),
            "last_login_at": u.get("last_login_at"),
            "login_count": int(u.get("login_count") or 0),
        }

    # -- 读 -----------------------------------------------------------------
    def list(self) -> list[dict]:
        with self._lock:
            return [self._public(u) for u in self._data["users"]]

    def count(self) -> int:
        with self._lock:
            return len(self._data["users"])

    def get(self, name: str) -> dict | None:
        with self._lock:
            u = self._find(name)
            return dict(u) if u else None

    # -- 写 -----------------------------------------------------------------
    def bootstrap(self, name: str, stored_hash: str, role: str = "admin") -> bool:
        """仅在表为空时建号。返回是否真的建了。"""
        with self._lock:
            if self._data["users"]:
                return False
            self._data["users"].append({
                "name": name,
                "hash": stored_hash,
                "role": role,
                "enabled": True,
                "epoch": secrets.token_hex(8),
                "created_at": _now(),
                "last_login_at": None,
                "login_count": 0,
            })
            self._save()
            return True

    def create(self, name: str, password: str, role: str = "viewer") -> dict:
        name = (name or "").strip()
        if not name:
            raise StoreError("用户名不能为空")
        if len(name) > 32:
            raise StoreError("用户名最长 32 个字符")
        if not all(c.isalnum() or c in "-_." for c in name):
            raise StoreError("用户名只能包含字母、数字、点、下划线、短横线")
        if role not in ROLE_TOOLS:
            raise StoreError(f"未知角色：{role}")
        if len(password or "") < 8:
            raise StoreError("口令至少 8 位")
        with self._lock:
            if self._find(name):
                raise StoreError(f"用户 {name} 已存在")
            rec = {
                "name": name,
                "hash": web_auth.hash_password(password),
                "role": role,
                "enabled": True,
                "epoch": secrets.token_hex(8),
                "created_at": _now(),
                "last_login_at": None,
                "login_count": 0,
            }
            self._data["users"].append(rec)
            self._save()
            return self._public(rec)

    def update(self, name: str, *, password: str | None = None,
               role: str | None = None, enabled: bool | None = None) -> dict:
        """改口令 / 改角色 / 启停。

        **任何一项变化都轮换 epoch** —— 否则「禁用某人」后他手里的 Cookie
        还能继续用到过期，等于禁用没生效。
        """
        with self._lock:
            u = self._find(name)
            if not u:
                raise StoreError(f"用户 {name} 不存在")
            changed = False
            # 先算出「改完后还剩几个启用的 admin」，再决定能不能改。
            # 顺序不能反：改完之后再数，被降级的那个人已经不在数里了，
            # 就永远是 0，于是谁都改不了。
            others = sum(1 for x in self._data["users"]
                         if x is not u and x.get("role") == "admin"
                         and x.get("enabled", True))
            will_role = role if role is not None else u.get("role")
            will_enabled = enabled if enabled is not None else u.get("enabled", True)
            if not (will_role == "admin" and will_enabled) and others == 0:
                raise StoreError("至少要保留一个启用的管理员账号")

            if password is not None:
                if len(password) < 8:
                    raise StoreError("口令至少 8 位")
                u["hash"] = web_auth.hash_password(password)
                changed = True
            if role is not None:
                if role not in ROLE_TOOLS:
                    raise StoreError(f"未知角色：{role}")
                if role != u.get("role"):
                    u["role"] = role
                    changed = True
            if enabled is not None:
                if bool(enabled) != bool(u.get("enabled", True)):
                    u["enabled"] = bool(enabled)
                    changed = True
            if changed:
                u["epoch"] = secrets.token_hex(8)
                self._save()
            return self._public(u)

    def delete(self, name: str) -> None:
        with self._lock:
            u = self._find(name)
            if not u:
                raise StoreError(f"用户 {name} 不存在")
            if u.get("role") == "admin" and self._admin_count() <= 1:
                raise StoreError("至少要保留一个启用的管理员账号")
            self._data["users"] = [x for x in self._data["users"]
                                   if x.get("name") != name]
            self._save()

    def _admin_count(self) -> int:
        return sum(1 for u in self._data["users"]
                   if u.get("role") == "admin" and u.get("enabled", True))

    # -- 校验 ---------------------------------------------------------------
    def verify(self, name: str, password: str) -> dict | None:
        """成功返回用户记录（含 hash/epoch，**仅供内部使用**），失败 ``None``。

        与旧版的差别：旧版是「用户名比对 + 单条哈希校验」，现在要遍历表。
        为了不让「用户不存在」比「口令错」快一个数量级，未命中时也跑一次
        scrypt（对着一个占位哈希），把时间拉平。
        """
        with self._lock:
            u = self._find((name or "").strip())
            stored = u.get("hash") if u else _DUMMY_HASH
            ok = web_auth.verify_password(password or "", stored or "")
            if not u or not u.get("enabled", True):
                return None
            if not ok:
                return None
            # 参数升级：登录成功这一刻手里有明文，正好就地重算成当前参数。
            # 不做的话，提高 SCRYPT_N 对存量账号完全无效（它们仍按旧 n 验证）。
            if web_auth.needs_rehash(u.get("hash", "")):
                try:
                    u["hash"] = web_auth.hash_password(password)
                except (ValueError, TypeError):
                    pass                       # 升级失败不影响这次登录
            u["last_login_at"] = _now()
            u["login_count"] = int(u.get("login_count") or 0) + 1
            self._save()
            return dict(u)

    def session_valid(self, name: str, epoch: str) -> dict | None:
        """会话是否仍然有效：用户存在、启用、epoch 未轮换。"""
        with self._lock:
            u = self._find(name)
            if not u or not u.get("enabled", True):
                return None
            if not epoch or not hmac.compare_digest(str(u.get("epoch", "")), str(epoch)):
                return None
            return {"name": u["name"], "role": u.get("role", "viewer")}


#: 用户不存在时用来「陪跑」的哈希。口令故意不可能被猜到，只为消耗同样的时间。
_DUMMY_HASH = web_auth.hash_password("dummy-password-for-timing-equalization")


# ---------------------------------------------------------------------------
# 令牌表
# ---------------------------------------------------------------------------
class TokenStore:
    """访问令牌：创建、校验、吊销、计次。

    令牌是**能力凭证**而非身份凭证 —— 一枚令牌绑定一个 owner 与一个 role，
    校验通过后调用方得到的就是那个 role 的权限。
    """

    def __init__(self, path: str | Path, *, usage_window: float = 30.0,
                 flush_interval: float = 5.0, flush_every: int = 50) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = _read_json(self.path, {"version": 1, "tokens": []})
        self._data.setdefault("tokens", [])
        self.usage_window = float(usage_window)
        self.flush_interval = float(flush_interval)
        self.flush_every = int(flush_every)
        self._dirty = 0
        self._last_flush = _now()

    # -- 内部 --------------------------------------------------------------
    def _maybe_flush(self, force: bool = False) -> None:
        if not self._dirty:
            return
        now = _now()
        if force or self._dirty >= self.flush_every or (now - self._last_flush) >= self.flush_interval:
            self._save()
            self._dirty = 0
            self._last_flush = now

    def _save(self) -> None:
        _atomic_write(self.path, self._data)

    def _find(self, tid: str) -> dict | None:
        for t in self._data["tokens"]:
            if t.get("id") == tid:
                return t
        return None

    @staticmethod
    def _public(t: dict) -> dict:
        """对外视图：带 prefix（便于认人），**绝不带 hash**。"""
        return {
            "id": t.get("id", ""),
            "name": t.get("name", ""),
            "prefix": t.get("prefix", ""),
            "owner": t.get("owner", ""),
            "role": t.get("role", "operator"),
            "clearance": clearance_of(t.get("role", "operator"), t.get("clearance")),
            "access": access_of(t.get("role", "operator"), t.get("access")),
            "enabled": bool(t.get("enabled", True)),
            "created_at": t.get("created_at"),
            "expires_at": t.get("expires_at"),
            "max_uses": int(t.get("max_uses") or 0),
            "uses": int(t.get("uses") or 0),
            "last_used_at": t.get("last_used_at"),
        }

    # -- 读 -----------------------------------------------------------------
    def list(self, owner: str | None = None) -> list[dict]:
        with self._lock:
            rows = self._data["tokens"]
            if owner is not None:
                rows = [t for t in rows if t.get("owner") == owner]
            return [self._public(t) for t in sorted(rows, key=lambda x: x.get("created_at") or 0,
                                                    reverse=True)]

    # -- 写 -----------------------------------------------------------------
    def create(self, *, name: str, owner: str, role: str = "operator",
               clearance: str | None = None, access: str | None = None,
               expires_in: int | None = None, max_uses: int = 0) -> tuple[str, dict]:
        """建令牌，返回 ``(明文, 对外记录)``。**明文只在这一刻存在**。"""
        name = (name or "").strip()
        if not name:
            raise StoreError("令牌名称不能为空")
        if len(name) > 48:
            raise StoreError("令牌名称最长 48 个字符")
        if role not in ROLE_TOOLS:
            raise StoreError(f"未知角色：{role}")
        # 数据视野：显式值必须在档位表里，且不得高于角色上限。
        ceil = ROLE_CLEARANCE.get(role, DEFAULT_CLEARANCE)
        want = str(clearance or ceil).strip().lower()
        if want not in CLEARANCE_RANK:
            raise StoreError(
                f"未知数据视野：{want}（可选 {'/'.join(CLEARANCE_RANK)}）")
        if CLEARANCE_RANK[want] > CLEARANCE_RANK[ceil]:
            raise StoreError(
                f"数据视野不能高于角色上限（{want} > {ceil}）。要把令牌视野调到"
                f"{want}，得先给它 {role} 之上能覆盖该档的角色。")
        # 读写模式：只能比角色默认更保守。角色默认只读（viewer）时不允许声明 rw ——
        # 否则会签出一枚「界面上写着可写、实际因视野只读而写不进去」的令牌，
        # 那种表里不一比直接拒绝更难查。
        if access is None:
            want_access = ROLE_ACCESS.get(role, DEFAULT_ACCESS)
        else:
            want_access = str(access).strip().lower()
            if want_access not in ACCESS_MODES:
                raise StoreError(
                    f"未知读写模式：{want_access}（可选 {'/'.join(ACCESS_MODES)}）")
            if want_access == "rw" and ROLE_ACCESS.get(role, DEFAULT_ACCESS) != "rw":
                raise StoreError(
                    f"角色 {role} 的令牌不能声明可读写（该角色默认只读）。")
        if expires_in is not None:
            if int(expires_in) < 60:
                raise StoreError("有效期至少 60 秒")
            expires_in = int(expires_in)
        max_uses = int(max_uses or 0)
        if max_uses < 0:
            raise StoreError("可用次数不能为负")

        plain = TOKEN_PREFIX + secrets.token_urlsafe(32)
        with self._lock:
            rec = {
                "id": "t_" + secrets.token_hex(4),
                "name": name,
                "prefix": plain[:12],
                "hash": _digest(plain),
                "owner": owner,
                "role": role,
                "clearance": want,
                "access": want_access,
                "enabled": True,
                "created_at": _now(),
                "expires_at": (_now() + expires_in) if expires_in else None,
                "max_uses": max_uses,
                "uses": 0,
                "last_used_at": None,
                "last_counted_at": None,
            }
            self._data["tokens"].append(rec)
            self._save()
            return plain, self._public(rec)

    def revoke(self, tid: str, *, owner: str | None = None) -> None:
        with self._lock:
            t = self._find(tid)
            if not t:
                raise StoreError("令牌不存在")
            if owner is not None and t.get("owner") != owner:
                raise StoreError("令牌不属于当前用户")
            self._data["tokens"] = [x for x in self._data["tokens"] if x.get("id") != tid]
            self._save()

    def set_enabled(self, tid: str, enabled: bool, *, owner: str | None = None) -> dict:
        with self._lock:
            t = self._find(tid)
            if not t:
                raise StoreError("令牌不存在")
            if owner is not None and t.get("owner") != owner:
                raise StoreError("令牌不属于当前用户")
            t["enabled"] = bool(enabled)
            self._save()
            return self._public(t)

    # -- 校验 ---------------------------------------------------------------
    def has_digest(self, plain: str) -> bool:
        got = _digest(plain)
        with self._lock:
            return any(hmac.compare_digest(got, t.get("hash", ""))
                       for t in self._data["tokens"])

    def adopt(self, plain: str, *, name: str, owner: str = "system",
              role: str = "admin") -> dict | None:
        """把一枚**已经存在于 .env 的**明文令牌纳入表中，返回新记录（已存在则 ``None``）。

        为什么需要：升级到令牌表之后，``.env`` 里那两枚老令牌
        （``AI_MEMORY_WEB_TOKEN`` / ``AI_MEMORY_TOKEN``）如果不在表里，
        校验就会全部落空 —— 所有脚本和 MCP 客户端**同一秒**开始 401。
        由 config() 在启动时自动认领，是唯一不需要人工迁移的做法。

        认领出来的令牌角色固定 ``admin``、永不过期：它们本来就是「部署方手里的
        总钥匙」，语义不能因为改造而削弱。想收紧就去 .env 里换掉。
        """
        if not plain or self.has_digest(plain):
            return None
        with self._lock:
            rec = {
                "id": "t_" + secrets.token_hex(4),
                "name": name,
                "prefix": plain[:12],
                "hash": _digest(plain),
                "owner": owner,
                "role": role,
                # 认领来的老令牌（.env 总钥匙）按角色推导视野，默认 admin → owner，
                # 语义与改造前一致：它是部署方的总钥匙，不能因这次变更被削弱。
                "clearance": clearance_of(role),
                # 同理，读写模式也按角色推导（admin → rw）。老令牌升级后仍可写 ——
                # 这里若默认成 ro，等于在无人察觉的情况下收走了部署方的写权。
                "access": access_of(role),
                "enabled": True,
                "created_at": _now(),
                "expires_at": None,
                "max_uses": 0,
                "uses": 0,
                "last_used_at": None,
                "last_counted_at": None,
                "adopted": True,
            }
            self._data["tokens"].append(rec)
            self._save()
            return self._public(rec)

    def verify(self, plain: str) -> dict | None:
        """校验令牌并计次。有效返回 ``{name, owner, role, id}``，否则 ``None``。

        失败原因一律不区分（过期 / 次数用尽 / 已吊销 / 不存在）——
        对外只回「无效」，避免给攻击者一个进度条。
        """
        if not plain:
            return None
        # ⚠️ 这里**不能**再用 ``startswith(TOKEN_PREFIX)`` 做短路：
        # .env 里那两枚老令牌是 ``token_urlsafe(32)`` 生成的，没有 ``amt_`` 前缀，
        # 被 adopt 收进表后仍要能校验通过 —— 用前缀筛会把它们直接判死，
        # 症状是「升级后老 token 全 401」。
        got = _digest(plain)
        now = _now()
        with self._lock:
            for t in self._data["tokens"]:
                if not hmac.compare_digest(got, t.get("hash", "")):
                    continue
                if not t.get("enabled", True):
                    return None
                exp = t.get("expires_at")
                if exp is not None and now >= float(exp):
                    return None
                max_uses = int(t.get("max_uses") or 0)
                uses = int(t.get("uses") or 0)
                if max_uses and uses >= max_uses:
                    return None
                # 去重窗口：窗口内重复请求不重复计次
                last = t.get("last_counted_at")
                if not last or (now - float(last)) >= self.usage_window:
                    t["uses"] = uses + 1
                    t["last_counted_at"] = now
                    self._dirty += 1
                t["last_used_at"] = now
                self._maybe_flush()
                return {"id": t.get("id"), "name": t.get("name"),
                        "owner": t.get("owner"), "role": t.get("role", "operator"),
                        # 数据视野随令牌一起返回：调用方据此选 MCP 端点，而不是
                        # 一律打 /mcp（owner）。旧令牌没有该字段时按角色推导。
                        "clearance": clearance_of(t.get("role", "operator"),
                                                  t.get("clearance")),
                        # 读写模式同理：调用方据此决定打 /mcp/<档位> 还是
                        # /mcp/<档位>-ro。旧令牌没有该字段时按角色推导（rw）。
                        "access": access_of(t.get("role", "operator"),
                                            t.get("access"))}
        return None

    def flush(self) -> None:
        with self._lock:
            self._maybe_flush(force=True)


def role_allows_tool(role: str, group: str | None) -> bool:
    """该角色能否调用某工具组的工具。``group`` 为 ``None`` 表示未归类。

    未归类的工具按**最严**处理：只有 admin 能用。理由是新工具不会因为
    「忘记登记分组」而意外对只读用户开放。
    """
    allowed = ROLE_TOOLS.get(role, ROLE_TOOLS["viewer"])
    if allowed is None:
        return True
    if group is None:
        return role == "admin"
    return group in allowed
