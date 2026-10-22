# ai-memory-web

**ai-memory 记忆库的浏览器控制台 —— 前端 + 后端。**

概览 / 记忆库 / 调试台 / 配置四页。前端纯静态、**零构建**（无 npm、无打包器）；后端是一个 Starlette 应用，同源托管前端并把 `/api/*` 代理到 MCP 端点。

[![Release](https://img.shields.io/github/v/release/dpkg-s/ai-memory-web?label=release&color=blue)](https://github.com/dpkg-s/ai-memory-web/releases/latest)
[![Vue](https://img.shields.io/badge/Vue-3.4.38-42b883)](https://vuejs.org/)
[![Frontend](https://img.shields.io/badge/build-none-blue)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 三个仓的关系

本产品拆成三仓，各自独立发版。你当前在 **ai-memory-web**。

| 仓 | 职责 | 何时来这个仓 |
| --- | --- | --- |
| MCP 服务端 / 安装器 | [ai-memory-template](https://github.com/dpkg-s/ai-memory-template) | 装服务端、调 `memory.toml`、查 25 个工具的签名 |
| **Web 控制台**（本仓） | 浏览器界面 + Starlette 后端 | 想在浏览器里看记忆库、调工具、改阈值 |
| 容器与编排 | [ai-memory-docker](https://github.com/dpkg-s/ai-memory-docker) | 想一条 `docker compose up` 跑全套（含默认账号） |

```
ai-memory-docker
  └── template/ (submodule) ── dpkg-s/ai-memory-template
        └── web-console/ (submodule) ── dpkg-s/ai-memory-web   ← 本仓
```

## 版本对照

三个仓版本号**不同轨**，靠下表对照，不靠数字大小推断兼容性。

| 组件 | 当前版本 | 兼容说明 |
| --- | --- | --- |
| ai-memory-template | **3.1.2** | 提供 MCP 端点；本仓只连它，不 import 它 |
| ai-memory-web | **1.11.3** | 需 MCP 端点可达（`AI_MEMORY_WEB_MCP`） |
| ai-memory-docker | **1.1.1** | 本仓源码被 `Dockerfile.web` 直接 COPY 进镜像 |

版本号规则：major 位不动，**只叠加** —— 修 bug / 文档 / CI 记 `+0.0.1`，用户可见的新能力记 `+0.1`。
本仓的机器可读版本源是 `web_console.py` 的 `WEB_VERSION`，发版时由 `release.yml` 校验
`tag == WEB_VERSION == CHANGELOG 首条`，三者不一致直接判红。

发版顺序是硬约束：**ai-memory-template 先 → 本仓后**。本仓 Release 从核心仓 latest
转挂同一个安装器 exe，反序会发出上一版的安装器。

> 历史版本 `1.3.0`–`1.7.0` **未单独发布**，内容已并入 `1.8.0` 及之后，逐版记录见 [CHANGELOG.md](CHANGELOG.md)。
> 不补发：GitHub 不允许修改 `published_at`，补发旧版会让 Releases 页面出现「旧版本比新版本更晚」的倒挂。

## 快速开始

需要先有一个可达的 MCP 端点（`http://127.0.0.1:8700/mcp` 或你自己的地址）。

### 形态一：作为 submodule（推荐，零配置）

```bash
git clone --recursive git@github.com:dpkg-s/ai-memory-template.git
cd ai-memory-template/web-console
python serve_web.py --port 8811 --mcp http://127.0.0.1:8700/mcp
```

### 形态二：独立 clone

```bash
git clone git@github.com:dpkg-s/ai-memory-web.git
cd ai-memory-web
python serve_web.py --port 8811 --mcp http://127.0.0.1:8700/mcp
```

本形态**不需要** `AI_MEMORY_CORE_DIR` —— 控制台已不 import 核心仓任何模块。该变量只在
`--with-mcp`（让控制台替你拉起 MCP 端点）时才需要。

### 形态三：一条命令拉起前后端（单机试用最省事）

```bash
export AI_MEMORY_CORE_DIR=/path/to/ai-memory-template   # Windows: set AI_MEMORY_CORE_DIR=D:\path\to\ai-memory-template
python serve_web.py --with-mcp
```

`--with-mcp` 把核心仓的 `serve_http.py` 作为**子进程**拉起（仍是进程间调用，不破坏分层）。
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

## 发布产物

每个 Release 带两个二进制附件，各自附 `.sha256`：

| 附件 | 来源 | 说明 |
| --- | --- | --- |
| `web-console-v<X.Y.Z>.tgz` | 本仓 `git archive` 现场打包（排除 `.github/`、`tests/`） | 控制台源码包 |
| `ai-memory-setup.exe` | 从核心仓 latest Release 转挂 | Windows 快捷安装器，**与核心仓同一个字节** |

## 容器运行

本仓**只提供控制台源码，不自带容器定义**（`Dockerfile` / `compose.yaml` / `.dockerignore` 已迁出）。
全栈编排统一在 <https://github.com/dpkg-s/ai-memory-docker>：

```bash
git clone --recurse-submodules https://github.com/dpkg-s/ai-memory-docker.git
cd ai-memory-docker
docker compose up -d --build     # ai-memory(8700) + ai-memory-web(8811)
```

打开 <http://127.0.0.1:8811>，默认账号 `admin` / `password`（首次启动的种子，改过即失效）。

镜像构建、卷布局、默认口令语义、`421 Invalid Host header` 的成因与放行、多架构与 healthcheck
细节，全部见 docker 仓 README 与 Releases。本仓只保证「源码能被那个 `Dockerfile.web` 直接 COPY 进去」：

- 入口 `serve_web.py`，监听 `AI_MEMORY_WEB_PORT`（默认 `8811`）
- 状态落在 `AI_MEMORY_WEB_CONFIG_DIR`（默认 `/config`），**必须持久化**
- 上游 MCP 由 `AI_MEMORY_WEB_MCP` 指向，镜像内不含 MCP 服务端

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
| `AI_MEMORY_WEB_INTERNAL_KEY` | （空） | 网关回调 `/internal/token/verify` 的容器间共享密钥。**空 = 关闭该端点** |
| `AI_MEMORY_WEB_MCP` | `http://127.0.0.1:8700/mcp` | 上游 MCP 端点 |
| `AI_MEMORY_WEB_STATIC` | `<本仓根>/web` | 前端静态资源目录 |
| `AI_MEMORY_WEB_CONFIG` | `~/.ai-memory-web/config.json` | 配置面存储 |
| `AI_MEMORY_WEB_CONFIG_WRITE` | `1` | `0` = 阈值只读 |

## 鉴权

控制台有**两种**可独立使用的凭证（访问令牌、账号登录），按部署配置自动决定首屏弹什么。
**不设默认口令** —— 内置口令等于给所有人发同一把钥匙。

| 部署配置 | 首屏行为 | 怎么进 |
| --- | --- | --- |
| 什么都不配，且只监听回环 | 直接进界面 | 不用登（`auth_required=false`）。**仅限本机** |
| 只配 `AI_MEMORY_WEB_TOKEN` | 弹「输入访问令牌」 | 粘贴该 token |
| 只配 `AI_MEMORY_WEB_USER` + `AI_MEMORY_WEB_PASSWORD_HASH` | 弹「登录」 | 用户名 + 口令 |
| 两者都配 | 弹「登录」，底部有「改用访问令牌」 | 任选其一 |

首次生成哈希：`python make_password.py`（交互输入、不回显，输出两行可直接粘进环境）。

**「半配」会被直接拒绝启动**（不是警告）：给了 `USER` 却没给口令哈希，或监听非回环却没给
token 或账号登录 —— 后者等于局域网内任何人都能打开调试台写记忆库。

角色的会话语义（`admin` / `operator` / `viewer`、会话 epoch 吊销、登录限流、令牌限时限次）
全部见 **[docs/auth.md](docs/auth.md)**。

## 与核心仓的关系

**本仓不 import 核心仓的任何模块，对核心仓的关系只有一种：连接。**（2026-10-16 收敛）

| 曾经要 import 的东西 | 现在怎么拿 |
| --- | --- |
| `memory_config.py`（读写 vault 根的 `memory.toml`） | MCP 工具 **`memory_config`**（唯一实现在核心仓，服务端与本台共用同一份） |
| `transport_http.py`（MCP 端点默认地址常量） | 本仓字面常量 `DEFAULT_MCP_URL`（可被 `AI_MEMORY_WEB_MCP` 覆盖） |
| `core_path.py`（定位核心目录 + 注入 `sys.path`） | **已删除**；仅 `--with-mcp` 需要核心仓目录，且必须显式给出 |

为什么值得拆：跨仓 import 意味着「`memory.toml` 怎么读、怎么写、怎么校验」在两侧各有一份实现，
任一侧改动都可能让两边对不上。现在这三件事只有一处实现，本仓只负责「转成前端契约的 JSON」
和「施加本台的只读开关」。`tests/test_web.py` 的 C 段把这条钉成了断言：导入控制台后
`sys.modules` 里**不得**出现 `memory_config` / `transport_http` / `core_path` / `server`。

## URL 约定

| 路径 | 去向 |
| --- | --- |
| `/` | `web/index.html` |
| `/assets/*` | `web/` 目录（`css/`、`js/`、`vendor/`） |
| `/api/*` | 后端代理到 MCP（可选 `Bearer` Token） |

后端接口：`/api/health`、`/api/overview`、`/api/tools`、`/api/call`、`/api/thresholds`、`/api/config`、
`/api/update`、`/api/update/restart`、`/api/session`、`/api/login`、`/api/logout`。

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
├── make_password.py        # 生成 AI_MEMORY_WEB_PASSWORD_HASH（首次装完登录用）
├── requirements.txt        # mcp>=1.30,<2（starlette / uvicorn / httpx / anyio 均为其传递依赖）
├── web/                    # 前端（静态根；后端把它挂在 /assets）
│   ├── index.html          # 入口：主题预置脚本 + vendor 同步加载 + ESM 入口 js/main.js
│   ├── css/                # 8 片；CSS 无显式依赖，层叠顺序即加载顺序（不可调换）
│   ├── js/                 # main.js + core/ + components/ + features/ + views/
│   └── vendor/             # 本地化第三方库（无 CDN、无 npm）：Vue / marked / DOMPurify / GSAP
├── docs/auth.md            # 鉴权详解（角色、会话、令牌、限流）
├── LICENSE
└── README.md
```

## 开发约定

1. **零构建**：前端没有打包器、没有 npm 依赖、没有产物目录，改完刷新浏览器即生效。
2. **CSS 分片顺序不可变**：CSS 没有 `import` 那样的显式依赖，层叠顺序就是加载顺序，因此 `web/index.html` 中 8 个 `<link>` 的顺序不可调换、不可改为按需加载。
3. **核心模块不复制、也不 import**：阈值一律经 MCP 工具 `memory_config` 读写；需要新能力时**先加 MCP 工具**，而不是在仓内新增一份核心逻辑的副本 —— 那会让两仓各自漂移。
4. **分层**：控制台不 import `server`，也不 import 核心仓任何模块；对记忆库的一切读写都走 MCP 协议（不直连 vault、不进程内直调）。`tests/test_web.py` C 段机器守卫这两条。
5. **主题**：`data-theme`（解析值）+ `data-theme-pref`（用户偏好），早于首帧生效以避免闪烁；`?theme=light|dark|auto` 可作深链覆盖并写回 `localStorage`。
6. **hash 路由**：`#/dashboard` 等，不依赖服务端路由重写。
7. **发版**：改版本时 `web_console.py` 的 `WEB_VERSION` 与 `CHANGELOG.md` 顶部必须同改，否则 `release.yml` 的版本门禁直接判红。

## 许可

MIT © 2026 dpkg-s
