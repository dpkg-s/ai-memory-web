> 本页由仓库主页拆分而来，内容与拆分前逐字一致。返回 [主页](../README.md)。

# OAuth 授权（网页型 MCP 客户端怎么连）

`/mcp` 原本只认 `amt_` 访问令牌。桌面客户端能自己加 `Authorization` 头，所以够用；
但**网页型产品**（ChatGPT 自定义 Connector、部分在线 IDE）没有「填令牌」的入口，
它们只走标准 OAuth 授权流。本页说明这条通道怎么开、怎么用、边界在哪。

## 一句话原理

```
客户端 → POST /mcp（无凭据）
       ← 401 + WWW-Authenticate: Bearer resource_metadata="…"
客户端 → GET /.well-known/oauth-protected-resource   （该向谁要令牌）
       → GET /.well-known/oauth-authorization-server （授权/换令牌/注册端点）
       → POST /oauth/register                        （动态注册，拿 client_id）
人在浏览器 → GET/POST /oauth/authorize               （登录 + 同意）
客户端 → POST /oauth/token                           （code + PKCE 换令牌）
客户端 → POST /mcp（Authorization: Bearer amt_…）     ✅
```

**关键设计**：换出来的 `access_token` 就是一枚普通 `amt_` 令牌，`name` 为
`oauth:<客户端名>`。所以鉴权中间件、`/api/call`、`/mcp` 反代、数据视野与读写模式
**一行都没改**；它在面板的「访问控制 → 令牌」里看得见、能一键吊销。

## 端点清单

| 路径 | 方法 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `/.well-known/oauth-protected-resource` | GET | 免 | RFC 9728，声明 `resource` 与授权服务器 |
| `/.well-known/oauth-authorization-server` | GET | 免 | RFC 8414，含 `registration_endpoint` |
| `/oauth/register` | POST | 免 | RFC 7591 动态注册，返回 `client_id` |
| `/oauth/authorize` | GET | 免（页内登录） | 授权页；未登录时同一页登录 |
| `/oauth/authorize` | POST | 免（页内登录） | 同意/拒绝，成功则 302 回 `redirect_uri` |
| `/oauth/token` | POST | 免 | `authorization_code` + PKCE 换令牌 |

这五个都在 `AuthMiddleware.PUBLIC` 里放行——它们服务的正是「还没有凭据」的客户端。
授权页自己的身份判断（Cookie 会话或表单账号口令）在处理器内部完成。

## 客户端怎么配

### ChatGPT（自定义 Connector）

1. 设置 → Connectors → 新建，类型选 **MCP / 自定义**；
2. URL 填 `https://<你的域名>/mcp`——**不要**带 `?token=`；
3. 认证方式选 **OAuth**（不要选「无认证」）；
4. 保存后它会自动走上面那条链路，浏览器弹出本站授权页，用控制台账号登录并点「允许」。

若客户端要求手填端点，按上表填 `<域名>` 开头的绝对地址即可。

### 桌面客户端（Claude Desktop / Cherry Studio / Cline / Cursor）

这些**不需要** OAuth：直接用 `Authorization: Bearer amt_…`，或在只有 URL 一个输入框
时用 `/mcp?token=amt_…`。

## 安全边界（三条硬约束）

1. **只收 PKCE S256**。`plain` 在公共客户端场景等于没校验，一律 400。
2. **`redirect_uri` 必须与注册值逐字符相同**，且注册时只能是 `https://` 或回环
   `http://localhost` / `127.0.0.1`。任何宽松比较都会打开重定向漏洞；
   不合法时**就地渲染错误页，绝不 302**（否则本站就成了开放重定向器）。
3. **授权码一次性、60 秒过期**，取出即删（`pop` 而非「标记已用」），重放必失败。

另外：`client_name` 来自匿名可写的注册表，进 HTML 前一律转义（防存储型 XSS）；
注册客户端数量封顶 64 个，防止有人把 `oauth_clients.json` 写到磁盘满。

## 配置项

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `AI_MEMORY_WEB_OAUTH` | `1` | 总开关。没有 token 也没有账号登录时自动关闭（无人可授权） |
| `AI_MEMORY_WEB_PUBLIC_URL` | 空 | **公网基址**，如 `https://console.example.com`。留空则从 `X-Forwarded-Proto/Host` 推导 |
| `AI_MEMORY_WEB_OAUTH_CLIENTS` | `<config>/oauth_clients.json` | 注册表落盘位置 |

> ⚠️ `AI_MEMORY_WEB_PUBLIC_URL` 建议显式配。控制台只绑回环，经 Cloudflare Tunnel
> 转发后本地看到的 scheme 恒为 `http`、host 恒为 `127.0.0.1:8890`；虽然代码会优先
> 采信 `X-Forwarded-*`，但显式配置能免掉一整类「issuer 校验失败」。

## 排障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 客户端拿不到 `client_id` | 元数据没暴露 `registration_endpoint`，或该路径被鉴权拦了 | 确认 `/oauth/register` 免鉴权可达 |
| 授权页打不开 / issuer 不匹配 | 元数据里的基址是内网地址 | 配 `AI_MEMORY_WEB_PUBLIC_URL` |
| 换令牌返回 `invalid_grant` | 码过期（>60s）、已用过、verifier 错、`redirect_uri` 不一致 | 重新发起一次授权 |
| 换到令牌仍 401 | 令牌被吊销，或 `oauth_clients.json` 里的客户端已被清 | 面板「访问控制」核对 |
| 浏览器直接打开 `/mcp` 看到 406/400 | 正常。MCP 端点不是网页，`GET` 只回协议错误 | 不要在浏览器里测它 |

## 日志与可观测性

排障这条通道时，日志比代码更先被翻。本节记录它与启动方式绑定的几个事实，
**改动前请先读完**——这些不是风格偏好，而是踩过的坑。

### 在哪里初始化

`ai-memory.web` 这个 logger 由 `web_console.create_app()` 的**首行**初始化
（`_ensure_app_logging()`），不在 `serve_web.py`。原因是一条调用链事实：
`create_app()` 有四个调用方——`serve_web.py`（生产入口）、`tests/test_oauth.py`、
`tests/test_web.py`、`_probe_clearance_e2e.py`。后三者都**不经过 `serve_web.py`**，
若把初始化放在入口，这些路径上日志会全丢，而丢的方式恰好是「代码里有、
运行时没有」——正是当初这个 logger 一个 handler 都没有的那种哑炮。
只放在入口的写法还要求插在 `config()` 之前，漏一行就丢早期日志。

同一仓库里 `server.py` 也是模块级自行 `addHandler`，故这不是新惯例。

### 输出到哪、怎么被采集

`StreamHandler(sys.stderr)`。生产启动器用 `Popen(..., stdout=logf, stderr=STDOUT)`
把子进程的两个流都重定向进 `~/.ai-memory-web/logs/<tag>_<时间戳>.log`，
所以 `stderr` 就是那个日志文件。

两条例外必须知道：

- **`sys.stderr is None` 时函数直接返回**，不挂 handler。`pythonw.exe` 无重定向下
  `StreamHandler(None)` 会得到 `stream=None`，`emit()` 抛 `AttributeError` 被
  `handleError` 吞掉——不崩溃，但也一行都写不出来，反而制造「已配置」的错觉。
- **日志文件编码是 GBK（cp936），不是 UTF-8**。用 `grep "鉴权失败"` 直接搜会
  匹配不到（模式是 UTF-8 字节）。要么 `iconv -f gbk -t utf-8`，要么按 GBK 读。

### `propagate = False` 的取舍

它让记录不再向父级 `ai-memory` / root 传播，避免将来有人同时配了父级后产生
重复行；代价是**任何依赖 root 聚合的采集方案都收不到这些日志**。当前控制台进程
不 import `server.py`（`--with-mcp` 是把 `serve_http.py` 拉成子进程），所以父级
handler 本就不存在，这个开关目前是防御性的。宿主若要接管日志，**必须在本进程
首次 `create_app()` 之前**挂好自己的 handler——已挂则先判早退，不改级别也不重复添加；
晚挂则会出现重复行。

### 现在会多出哪些行

补齐 handler 之后，此前被 `logging.lastResort` 丢掉的 INFO 会开始落盘，包括
**用户名**（创建/修改/删除用户）、**`redirect_uris`**（第三方回调地址）、
OAuth 各阶段事件与 401 的失败原因分类。这些属正常运维信息，但确实意味着
「写进磁盘的东西变多了」：日志文件的**访问权限应限本人、保留周期应有上限**，
不要长期堆积。

### 明确不记录的内容

`Authorization` 头、Cookie、令牌明文或前缀、授权码（`code`）、PKCE 的
`code_verifier`、任何密钥都不会进日志。鉴权失败只记**原因分类**
（`no_credential` / `token_rejected` / `session_stale`）与来源 IP；
`/oauth/token` 失败只记**错误码**，不记请求体。新增日志时请沿用这条边界。

## 与令牌体系的关系

| | 手工令牌 | OAuth 换来的令牌 |
| --- | --- | --- |
| 形态 | `amt_…` | `amt_…`（同一种） |
| 名字 | 自定义 | `oauth:<客户端名>` |
| 默认有效期 | 签发时指定（可永不过期） | 30 天 |
| 次数限制 | 可选 `max_uses` | 不限次 |
| 吊销 | 面板一键 | 面板一键（同表） |
| 刷新令牌 | — | 暂不发，到期重新授权 |
