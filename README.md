# ai-memory-web

**ai-memory 记忆库的扩展： Web 控制台 —— 前端 + 后端。**

浏览器里的记忆库控制面：概览、记忆库、调试台、配置四页。前端纯静态、**零构建**；后端是一个 Starlette 应用，同源托管前端并把 `/api/*` 代理到 MCP 端点。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Frontend](https://img.shields.io/badge/build-none-blue)]()
[![Vue](https://img.shields.io/badge/Vue-3.4.38-42b883)](https://vuejs.org/)
[![Console](https://img.shields.io/badge/console-v3.1-informational)]()

---

## 这是什么

「ai 融合记忆库」（[ai-memory-template](https://github.com/dpkg-s/ai-memory-template)）的浏览器控制台，由一个入口脚本（`serve_web.py`）、一个装配层（`web_console.py`）和一套前端（`web/`）组成。

一条硬约束决定它的形态：**浏览器不直连 MCP**。MCP 端点的 `allowed_origins` 默认为空，任何带 `Origin` 头的请求一律 403，且 SDK 不返回 CORS 头、`OPTIONS` 预检返 405。因此前端只与**同源** HTTP API 通信，由后端用 MCP SDK 完成上游调用。

## 与 ai-memory-template 的关系（先读这条）

**本仓不 import 核心仓的任何模块，对核心仓的关系只有一种：连接。**（2026-10-16 收敛）

历史形态是两条腿：「连 MCP」+「通过 `core_path.py` 上溯定位核心目录、注入 `sys.path`，再 `import memory_config` / `transport_http`」。第二条腿已于 2026-10-16 整体拆除：

| 曾经要 import 的东西 | 现在怎么拿 |
| --- | --- |
| `memory_config.py`（读写 vault 根的 `memory.toml`） | MCP 工具 **`memory_config`**（唯一实现在核心仓，MCP 服务端与 Web 台共用同一份） |
| `transport_http.py`（MCP 端点默认地址常量） | 本仓字面常量 `DEFAULT_MCP_URL`（它本来就只是个可被 `AI_MEMORY_WEB_MCP` 覆盖的默认值） |
| `core_path.py`（定位核心目录 + 注入 `sys.path`） | **已删除**；仅 `serve_web.py --with-mcp` 需要核心仓目录（找 `serve_http.py` 入口），且必须显式给 `--core-dir` / `AI_MEMORY_CORE_DIR` |

为什么值得拆：跨仓 import 意味着「`memory.toml` 怎么读、怎么写、怎么校验」在两侧各有一份实现，任一侧改动都可能让两边对不上；而定位逻辑本身还得维护一套上溯/回落规则。现在这三件事只有一处实现，本仓只负责「转成前端契约的 JSON」和「施加本台的只读开关」。

`tests/test_web.py` 的 C 段把这条钉成了断言：导入控制台后 `sys.modules` 里**不得**出现 `memory_config` / `transport_http` / `core_path` / `server`。

| 层 | 所在仓库 |
| --- | --- |
| MCP 服务端（25 工具 / Markdown vault） | [ai-memory-template](https://github.com/dpkg-s/ai-memory-template) |
| 核心模块（`server.py` / `memory_config.py` / `transport_http.py` / `serve_http.py` …） | [ai-memory-template](https://github.com/dpkg-s/ai-memory-template) |
| **Web 控制台：前端 + 后端（本仓）** | **ai-memory-web** |

> 拆分为两个仓的意义：Web 控制台可以独立演进、独立发版，而不必牵动 MCP 服务端的版本节奏。

## 快速开始

### 形态一：作为 submodule（推荐，零配置）

本仓挂在 `ai-memory-template/web-console/`，与核心仓同处一个工作副本：

```bash
git clone --recursive git@github.com:dpkg-s/ai-memory-template.git
cd ai-memory-template/web-console
python serve_web.py --port 8811 --mcp http://127.0.0.1:8700/mcp
```

### 形态二：独立 clone

```bash
git clone git@github.com:dpkg-s/ai-memory-web.git
cd ai-memory-web

# 只要有一个可达的 MCP 端点即可，不需要核心仓目录
python serve_web.py --port 8811 --mcp http://127.0.0.1:8700/mcp
```

本形态**不需要** `AI_MEMORY_CORE_DIR`——控制台已不 import 核心仓任何模块。该变量只在
`--with-mcp`（要让控制台替你拉起 MCP 端点）时才需要。

### 形态三：一条命令拉起前后端（单机试用最省事）

```bash
# Windows: set AI_MEMORY_CORE_DIR=D:\path\to\ai-memory-template
export AI_MEMORY_CORE_DIR=/path/to/ai-memory-template
python serve_web.py --with-mcp
```

`--with-mcp` 会把核心仓的 `serve_http.py` 作为**子进程**拉起（仍是进程间调用，不破坏分层）。
核心仓目录**必须显式给出**（`--core-dir` 或 `AI_MEMORY_CORE_DIR`）：本仓可能被单独克隆，
自动上溯猜出来的路径一旦猜错，报错会指向一个无关的文件。未给出时进程**明确报错并打印
可照抄的修复命令**，不会静默回落。

### 其他

```bash
python serve_web.py --check   # 只校验配置并打印摘要，不起服务（自检 / CI）
python serve_web.py --open    # 启动后自动打开浏览器

# 只看界面、无后端（/api/* 会 404，仅用于布局与视觉检查）
python -m http.server 8080 --directory web
```

## 容器运行（Docker）

本仓**只提供控制台源码，不再自带容器定义**（`Dockerfile` / `compose.yaml` / `.dockerignore`
已迁出）。全栈编排统一在 **<https://github.com/dpkg-s/ai-memory-docker>**：

```bash
git clone --recurse-submodules https://github.com/dpkg-s/ai-memory-docker.git
cd ai-memory-docker
docker compose up -d --build     # 起 ai-memory(8700) + ai-memory-web(8811)
```

打开 <http://127.0.0.1:8811>，默认账号 `admin` / `password`（首次启动的种子，改过即失效）。

镜像构建、卷布局、默认口令语义、`421 Invalid Host header` 的成因与放行方式、
多架构与 healthcheck 细节，全部见 docker 仓 README 与 Releases ——
本仓只保证「源码能被那个 `Dockerfile.web` 直接 COPY 进去」，即：

- 入口是 `serve_web.py`，监听 `AI_MEMORY_WEB_PORT`（默认 `8811`）
- 状态落在 `AI_MEMORY_WEB_CONFIG_DIR`（默认 `/config`），**必须持久化**
- 上游 MCP 由 `AI_MEMORY_WEB_MCP` 指向，镜像内不含 MCP 服务端

> 容器里连宿主机 MCP 会先撞 `421`，那是 MCP 侧 `Host` 白名单的问题，不是控制台的问题。
> 解法写在 docker 仓 README 的「连宿主机上的 MCP」一节。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `AI_MEMORY_CORE_DIR` | （空） | 核心仓目录；**仅** `--with-mcp` 需要（用于找 `serve_http.py`），不再用于 import |
| `AI_MEMORY_WEB_HOST` | `127.0.0.1` | 监听地址；非回环**必须**有 token 或账号登录，否则拒绝启动 |
| `AI_MEMORY_WEB_PORT` | `8811` | 监听端口 |
| `AI_MEMORY_WEB_TOKEN` | （空） | 设了之后 `/api/*` 需 `Authorization: Bearer <token>` |
| `AI_MEMORY_WEB_USER` | （空） | 账号登录的用户名。**必须**与下面二者之一同时给出，否则拒绝启动 |
| `AI_MEMORY_WEB_PASSWORD_HASH` | （空） | 口令的 scrypt 哈希，由 `python make_password.py` 生成（推荐） |
| `AI_MEMORY_WEB_PASSWORD` | （空） | 明文口令，启动时现场哈希。图省事才用：明文会留在环境里 |
| `AI_MEMORY_WEB_SESSION_TTL` | `43200`（12h） | 会话有效期（秒），下限 60 |
| `AI_MEMORY_WEB_SECRET` | （空） | 会话签名密钥；不设则从 token 派生 ⇒ **换 token 会让所有会话立即失效** |
| `AI_MEMORY_WEB_COOKIE_SECURE` | `0` | 置 `1` 给 Cookie 加 `Secure`。**纯 HTTP 下不要开**，否则浏览器不存 Cookie、登录整个失效 |
| `AI_MEMORY_WEB_USERS` | `<CONFIG 同目录>/users.json` | 用户表路径（1.6.0）。**不用配**，除非要把表放到别的卷 |
| `AI_MEMORY_WEB_TOKENS` | `<CONFIG 同目录>/tokens.json` | 令牌表路径（1.6.0）。同上 |
| `AI_MEMORY_WEB_INTERNAL_KEY` | （空） | 网关回调 `/internal/token/verify` 的容器间共享密钥。**空 = 关闭该端点**；容器部署必填，否则网关无法校验令牌 |
| `AI_MEMORY_WEB_MCP` | `http://127.0.0.1:8700/mcp` | 上游 MCP 端点 |
| `AI_MEMORY_WEB_STATIC` | `<本仓根>/web` | 前端静态资源目录 |
| `AI_MEMORY_WEB_CONFIG` | `~/.ai-memory-web/config.json` | 配置面存储 |
| `AI_MEMORY_WEB_CONFIG_WRITE` | `1` | `0` = 阈值只读 |

## 鉴权与首次登录

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

## URL 约定

| 路径 | 去向 |
| --- | --- |
| `/` | `web/index.html` |
| `/assets/*` | `web/` 目录（`css/`、`js/`、`vendor/`） |
| `/api/*` | 后端代理到 MCP（可选 `Bearer` Token） |

后端接口：`/api/health`、`/api/overview`、`/api/tools`、`/api/call`、`/api/thresholds`、`/api/config`、`/api/update`、`/api/update/restart`、`/api/session`、`/api/login`、`/api/logout`。

其中 `/api/session`、`/api/login`、`/api/logout` 三个**免鉴权**（精确匹配，无前缀绕过）：
`/api/session` 供前端启动时判断「要不要弹登录框」，`/api/logout` 永远返回 200 ——
若要求先认证，「会话已过期但页面还挂着」时点登出会收到 401，比登不出去更让人困惑。

## 页面

| Hash 路由 | 页面 | 职责 |
| --- | --- | --- |
| `#/dashboard` | 概览 | 条目统计、类型/作用域分布、写入趋势、近期活动 |
| `#/console` | 调试台 | 25 个 MCP 工具的调用台（按用途分 6 组，参数表单 + 结果面板） |
| `#/library` | 记忆库 | 条目浏览、搜索、阅读 |
| `#/settings` | 配置 | 连接、阈值、FNS 导入、关于与更新 |

## 目录结构

```
├── serve_web.py            # 后端入口：参数解析 + 配置校验 + 拉起 uvicorn
├── web_console.py          # 后端装配层：Starlette 应用 + /api/* 代理 + 配置面 + 鉴权
├── web_auth.py             # 凭证原语：scrypt 口令哈希 / 签名会话 Cookie / 登录限流（纯标准库）
├── web_store.py            # 用户表与令牌表：CRUD / 限时限次 / epoch 吊销（纯标准库）
├── make_password.py        # 生成 AI_MEMORY_WEB_PASSWORD_HASH（首次装完登录用，见「鉴权与首次登录」）
├── requirements.txt        # mcp>=1.30,<2（starlette / uvicorn / httpx / anyio 均为其传递依赖）
├── web/                    # 前端（静态根；后端把它挂在 /assets）
│   ├── index.html          # 入口：主题预置脚本 + vendor 同步加载 + ESM 入口 js/main.js
│   ├── css/                # 8 片；CSS 无显式依赖，层叠顺序即加载顺序（不可调换）
│   │   ├── 1-tokens.css    #   设计令牌（颜色 / 间距 / 动效时长）
│   │   ├── 2-layout.css    #   外壳骨架（sidebar / 三栏 / grid）
│   │   ├── 3-components.css#   基础组件
│   │   ├── 4-console.css   #   调试台
│   │   ├── 5-overlays.css  #   模态 / Toast
│   │   ├── 6-anim.css      #   动画与过渡
│   │   ├── 7-views.css     #   各页面样式
│   │   └── 8-responsive.css#   响应式分档
│   ├── js/
│   │   ├── main.js         #   入口：挂载 Vue 应用
│   │   ├── core/           #   核心层：api / store / router / data / theme / icons / util / anim
│   │   ├── components/     #   14 个基础组件（XCard / XStat / XKv / XPill / XSkel / …）
│   │   ├── features/       #   功能层：console / library / settings / update / fnsImport
│   │   └── views/          #   页面层：Root / Dashboard / ConsolePage / LibraryPage / SettingsPage
│   └── vendor/             #   本地化第三方库（无 CDN、无 npm）
│       ├── vue.esm-browser.prod.js   # Vue 3.4.38（ESM 具名导入）
│       ├── marked.min.js             # Markdown 渲染 12.0.2
│       ├── purify.min.js             # DOMPurify 3.1.6
│       ├── gsap.min.js               # GSAP 3.13.0
│       └── Flip.min.js               # GSAP Flip 3.13.0
├── LICENSE
└── README.md
```

## 开发约定

1. **零构建**：前端没有打包器、没有 npm 依赖、没有产物目录，改完刷新浏览器即生效。
2. **CSS 分片顺序不可变**：CSS 没有 `import` 那样的显式依赖，层叠顺序就是加载顺序，因此 `web/index.html` 中 8 个 `<link>` 的顺序不可调换、不可改为按需加载。
3. **核心模块不复制、也不 import**：阈值一律经 MCP 工具 `memory_config` 读写；需要新能力时**先加 MCP 工具**，而不是在仓内新增一份核心逻辑的副本或副本式 import——那会让两仓各自漂移。
4. **分层**：控制台不 import `server`，也不 import 核心仓任何模块（`memory_config` / `transport_http` / `core_path`）；对记忆库的一切读写都走 MCP 协议（不直连 vault、不进程内直调）。`tests/test_web.py` C 段机器守卫这两条。
5. **主题**：`data-theme`（解析值）+ `data-theme-pref`（用户偏好），早于首帧生效以避免闪烁；`?theme=light|dark|auto` 可作深链覆盖并写回 `localStorage`。
6. **hash 路由**：`#/dashboard` 等，不依赖服务端路由重写。

## 许可

MIT © 2026 dpkg-s
