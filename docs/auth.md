> 本页由仓库主页拆分而来，内容与拆分前逐字一致。返回 [主页](../README.md)。

# 鉴权与首次登录

控制台有**两种**可独立使用的凭证，按部署方的配置自动决定首屏弹什么。**不设默认口令**——
这是有意的：内置口令等于给所有人发同一把钥匙。

| 部署配置 | 首屏行为 | 怎么进 |
| --- | --- | --- |
| 什么都不配，且只监听回环 | 直接进界面 | 不用登（`auth_required=false`）。**仅限本机**：非回环且无 token 会拒绝启动 |
| 只配 `AI_MEMORY_WEB_TOKEN` | 弹「输入访问令牌」 | 粘贴该 token |
| 只配 `AI_MEMORY_WEB_USER` + `AI_MEMORY_WEB_PASSWORD_HASH` | 弹「登录」 | 用户名 + 口令 |
| 两者都配 | 弹「登录」，底部有「改用访问令牌」 | 任选其一 |

### 第一次装好之后（账号登录，推荐）

```bash
# 1) 生成哈希（交互输入，不回显；也可 python make_password.py "口令" 但会进 shell 历史）
python make_password.py
#    输出两行：
#      AI_MEMORY_WEB_USER=admin
#      AI_MEMORY_WEB_PASSWORD_HASH=scrypt:16384:8:1:<salt>:<hash>

# 2) 把这两行写进部署环境（.env / docker -e / compose environment 皆可）

# 3) 重启进程让配置生效
#    裸跑：Ctrl+C 后重新 python serve_web.py
#    容器：必须**重建容器**（docker rm -f && docker run …）。
#          `docker restart` 无效 —— `-e` 在建容器那一刻就固化了，
#          且配置在进程启动时只读一次。
```

然后浏览器打开 `http://<host>:8811/`，输入这对账号口令。

### 两种「半配」会被直接拒绝启动

不是警告、不是静默降级，而是**拒绝启动**并给出可照抄的修复命令。理由是半配会让人
以为「已经开了登录」，实际上门是开着的：

- 给了 `AI_MEMORY_WEB_USER` 却没给 `PASSWORD_HASH` / `PASSWORD` → 「登录配置不完整」；
- 监听非回环地址却没给 `AI_MEMORY_WEB_TOKEN` → 局域网内任何人可打开调试台执行破坏性操作。

### 会话语义（容易误判的地方）

- 登录成功下发 **HttpOnly + SameSite=Lax** 的签名 Cookie（`am_session`），页面脚本读不到。
- 有效期 `AI_MEMORY_WEB_SESSION_TTL`，默认 **12 小时**，`exp` 在签发时写死，**不做滑动续期**；
  到期需重新登录。
- **改口令现在会踢掉该用户的全部会话**（1.6.0 起）。会话里带一个 `epoch`，改口令 / 改角色 /
  禁用 / 删号都轮换它 —— 这是无状态会话也能「单点吊销」的机制。
  （1.5.0 及更早不会踢：那时签名密钥只派生自 token，与口令无关。）
- 要一次性踢掉**所有人**：换 `AI_MEMORY_WEB_TOKEN`（或设过 `AI_MEMORY_WEB_SECRET` 时换它）。
- 登录失败限流：同一来源 IP **5 次 / 5 分钟**内超过即锁 5 分钟（纯内存，重启清零）。
  用户名错与口令错返回同一句话，且都真实计算一次 scrypt —— 否则时间差可枚举用户名。

### 多用户与访问令牌（1.6.0 起）

单用户模型已升级为**用户表 + 令牌表**，两张表都在 `AI_MEMORY_WEB_CONFIG` 同目录
（容器里是 `/config/users.json`、`/config/tokens.json`），**不在 `.env`** ——
账号要能在线增删，而改 `.env` 需要重建容器。

| 角色 | 能做什么 |
| --- | --- |
| `admin` | 全部工具 + 管人 + 管令牌 |
| `operator` | 全部工具，不能管人 |
| `viewer` | 只能调只读工具组（`search` / `graph` / `health`） |

未归类的工具**按最严处理**（只有 admin），新工具不会因为忘了登记分组而对只读账号敞开。

令牌支持**限时**与**限次**：

```bash
# 用管理员会话签发一枚 7 天 / 100 次的令牌（明文只返回这一次）
curl -b jar.txt -X POST http://host:8811/api/tokens \
     -H 'Content-Type: application/json' \
     -d '{"name":"同事-只读","role":"viewer","expires_in":604800,"max_uses":100}'
# → {"ok":true,"token":"amt_xxx…","record":{…}}

# 吊销：立刻失效，无需重启
curl -b jar.txt -X DELETE http://host:8811/api/tokens/t_abcd1234
```

**限次的计数口径**：带 30 秒去重窗口。一次 MCP 工具调用会产生 2–3 个 HTTP 请求
（初始化 / SSE / 调用），逐请求计数会让「限 100 次」实际只能调 30 来个工具；
同一令牌在窗口内的重复请求只计 1 次。

管理面路由：

| 路由 | 方法 | 权限 |
| --- | --- | --- |
| `/api/users` | GET / POST | admin |
| `/api/users/{name}` | PATCH / DELETE | admin（删除会连带吊销其全部令牌） |
| `/api/tokens` | GET / POST | GET：admin 看全部、其他人看自己；POST：admin / operator |
| `/api/tokens/{id}` | DELETE | admin，或令牌属主 |
| `/api/password` | POST | 任何登录用户改自己的口令 |
| `/internal/token/verify` | GET | **仅容器内网**，凭 `X-Internal-Key`；网关 `auth_request` 用 |
| `/mcp` | GET / POST / DELETE | 令牌或会话，口径同 `/api/*`；反代到上游 MCP（见下） |

### MCP 客户端怎么连（v1.7.0）

控制台自己在同一端口上挂了 `/mcp`，鉴权后流式反代到 `AI_MEMORY_WEB_MCP`：

```
# 方式一：URL 里带令牌（配置项只让填 URL 的客户端用这个）
http://<host>:8811/mcp?token=amt_xxxxxxxx

# 方式二：自定义 header（推荐 —— 令牌不会进访问日志与浏览器历史）
URL:    http://<host>:8811/mcp
Header: Authorization: Bearer amt_xxxxxxxx
```

为什么不让客户端直连 8700：上游 MCP 端点**不鉴权**、只绑回环。它前面的鉴权要么
交给这层反代，要么交给外层网关（`/internal/token/verify` + `auth_request`）。
反代是**流式**的（SSE 逐帧透传），`Mcp-Session-Id` 原样透传；本控制台自己的
`Authorization` / `Cookie` 不会转给上游。


`.env` 里那两枚老令牌（`AI_MEMORY_WEB_TOKEN` / `AI_MEMORY_TOKEN`）会在启动时被自动
认领进令牌表（admin / 永不过期），老脚本与老 MCP 客户端无需改动。

### 脚本/CI 怎么访问

两种方式都行，令牌方式无需登录流程：

```bash
# 令牌（推荐给脚本）—— 可以是 .env 里的总钥匙，也可以是签发的限时令牌
curl -H "Authorization: Bearer $AI_MEMORY_WEB_TOKEN" http://host:8811/api/overview

# 账号口令换 Cookie（浏览器同款）
curl -c jar.txt -X POST http://host:8811/api/login \
     -H 'Content-Type: application/json' \
     -d '{"username":"admin","password":"…"}'
curl -b jar.txt http://host:8811/api/thresholds
```
