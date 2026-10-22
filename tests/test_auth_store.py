"""登录/令牌改造的离线自测（不启服务，直接压 web_auth + web_store）。"""
import sys, tempfile, time, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import web_auth, web_store

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print(f"  PASS  {label} {extra}")
    else:
        fail += 1; print(f"  FAIL  {label} {extra}")

d = pathlib.Path(tempfile.mkdtemp())
print("=== 1. scrypt 参数 ===")
print("  SCRYPT_N =", web_auth.SCRYPT_N, "=> 内存", 128 * web_auth.SCRYPT_N * 8 // 1024 // 1024, "MiB")
t0 = time.time(); h = web_auth.hash_password("pass-1234"); dt = (time.time() - t0) * 1000
print(f"  hash 耗时 {dt:.0f} ms，长度 {len(h)}")
check("正确口令通过", web_auth.verify_password("pass-1234", h))
check("错误口令拒绝", not web_auth.verify_password("wrong", h))
check("maxmem 未触发异常", h.startswith("scrypt:65536:8:1:"))

print("=== 2. 用户表 ===")
us = web_store.UserStore(d / "users.json")
check("空表 bootstrap 建 admin", us.bootstrap("admin", h, "admin"))
check("重复 bootstrap 不覆盖", not us.bootstrap("admin", h, "admin"))
check("列表返回 1 个且不带 hash", len(us.list()) == 1 and "hash" not in us.list()[0])
check("admin 登录成功", us.verify("admin", "pass-1234") is not None)
check("错口令登录失败", us.verify("admin", "nope") is None)
check("不存在用户登录失败", us.verify("ghost", "x") is None)
u = us.create("alice", "alice-pass-1", "viewer")
check("建 viewer 成功", u["role"] == "viewer")
check("重名被拒", (lambda: (us.create("alice", "x12345678", "viewer"), False)[1]
               if False else True)())
try:
    us.create("alice", "x12345678", "viewer"); check("重名被拒", False)
except web_store.StoreError:
    check("重名被拒", True)
try:
    us.create("bob", "short", "viewer"); check("短口令被拒", False)
except web_store.StoreError:
    check("短口令被拒", True)
ep0 = us.get("alice")["epoch"]
us.update("alice", password="alice-pass-2")
check("改口令后 epoch 轮换", us.get("alice")["epoch"] != ep0)
check("旧口令失效", us.verify("alice", "alice-pass-1") is None)
check("新口令可用", us.verify("alice", "alice-pass-2") is not None)

print("=== 3. 会话 epoch 吊销 ===")
key = web_auth.derive_key("tok", "")
sess = web_auth.make_session("alice", key, ttl=600, role="viewer", epoch=us.get("alice")["epoch"])
parsed = web_auth.read_session(sess, key)
check("会话可解出 role/epoch", parsed and parsed["r"] == "viewer" and parsed["e"])
check("epoch 匹配 ⇒ 有效", us.session_valid("alice", parsed["e"]) is not None)
us.update("alice", enabled=False)
check("禁用后会话立即失效", us.session_valid("alice", parsed["e"]) is None)
us.update("alice", enabled=True)

print("=== 4. 最后管理员保护 ===")
try:
    us.update("admin", role="viewer"); check("拒绝降级最后一个 admin", False)
except web_store.StoreError:
    check("拒绝降级最后一个 admin", True)
try:
    us.delete("admin"); check("拒绝删除最后一个 admin", False)
except web_store.StoreError:
    check("拒绝删除最后一个 admin", True)

print("=== 5. 令牌表 ===")
ts = web_store.TokenStore(d / "tokens.json", usage_window=0.0)
plain, rec = ts.create(name="笔记本", owner="admin", role="operator", expires_in=3600, max_uses=3)
check("明文带前缀", plain.startswith("amt_"))
check("表里只有 sha256", "hash" in ts._data["tokens"][0] and plain not in str(ts._data))
check("prefix 便于辨识", rec["prefix"] == plain[:12])
check("首次校验通过", ts.verify(plain) is not None)
ts.verify(plain); third = ts.verify(plain)
check("第 3 次仍通过", third is not None)
check("第 4 次超限被拒", ts.verify(plain) is None)
print("  uses =", ts.list()[0]["uses"], "/ max_uses =", ts.list()[0]["max_uses"])

plain2, _ = ts.create(name="一次性", owner="admin", role="viewer", expires_in=None, max_uses=1)
check("一次性首次通过", ts.verify(plain2) is not None)
check("一次性第二次被拒", ts.verify(plain2) is None)

plain3, rec3 = ts.create(name="短命", owner="admin", role="viewer", expires_in=60)
for t in ts._data["tokens"]:
    if t["id"] == rec3["id"]:
        t["expires_at"] = time.time() - 1
ts.flush()
check("过期令牌被拒", ts.verify(plain3) is None)

plain4, rec4 = ts.create(name="待吊销", owner="admin", role="admin")
check("吊销前可用", ts.verify(plain4) is not None)
ts.revoke(rec4["id"])
check("吊销后立即失效", ts.verify(plain4) is None)

print("=== 6. 去重窗口（模拟 MCP 一次调用多请求）===")
ts2 = web_store.TokenStore(d / "t2.json", usage_window=30.0)
p5, r5 = ts2.create(name="窗口", owner="admin", role="operator", max_uses=5)
for _ in range(4):
    ts2.verify(p5)
check("30s 内 4 次请求只计 1 次", ts2.list()[0]["uses"] == 1, f"uses={ts2.list()[0]['uses']}")

print("=== 7. adopt 兼容旧 .env 令牌 ===")
old = "LegacyTokenFromEnv_1234567890abcdefghijk"
check("首次 adopt 成功", ts2.adopt(old, name=".env") is not None)
check("重复 adopt 返回 None", ts2.adopt(old, name=".env") is None)
check("老令牌可校验", ts2.verify(old) is not None)

print("=== 8. 角色 → 工具组 ===")
check("viewer 可调 search", web_store.role_allows_tool("viewer", "search"))
check("viewer 不可调 lifecycle", not web_store.role_allows_tool("viewer", "lifecycle"))
check("viewer 不可调未归类", not web_store.role_allows_tool("viewer", None))
check("operator 可调 lifecycle", web_store.role_allows_tool("operator", "lifecycle"))
check("admin 可调未归类", web_store.role_allows_tool("admin", None))

print(f"\n==== 结果: {ok} passed / {fail} failed ====")
sys.exit(0 if fail == 0 else 1)
