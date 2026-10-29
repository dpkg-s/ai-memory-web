# ai-memory-web

**ai-memory 记忆库的浏览器控制台 —— 前端 + 后端。**

概览 / 记忆库 / 调试台 / 配置四页。前端纯静态、**零构建**（无 npm、无打包器）；后端是一个 Starlette 应用，同源托管前端并把 `/api/*` 代理到 MCP 端点。

[![Release](https://img.shields.io/github/v/release/dpkg-s/ai-memory-web?label=release&color=blue)](https://github.com/dpkg-s/ai-memory-web/releases/latest)
[![Vue](https://img.shields.io/badge/Vue-3.4.38-42b883)](https://vuejs.org/)
[![Frontend](https://img.shields.io/badge/build-none-blue)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 三个仓的关系

本产品拆成三仓，各自独立发布 —— **按你要做的事选一个**。

| 仓 | 职责 | 适用场景 |
| --- | --- | --- |
| MCP 服务端 / 安装器 | [ai-memory-template](https://github.com/dpkg-s/ai-memory-template) | 装服务端、调 `memory.toml`、查 25 个工具的签名 |
| **Web 控制台**（本仓） | 浏览器界面 + Starlette 后端 | 想在浏览器里看记忆库、调工具、改阈值 |
| 容器与编排 | [ai-memory-docker](https://github.com/dpkg-s/ai-memory-docker) | 想一条 `docker compose up` 跑全套（含默认账号） |

## 版本对照

三个仓版本号**不同轨**，各自按自己的节奏升，不要靠数字大小推断兼容性。

| 组件 | 当前版本 | 说明 |
| --- | --- | --- |
| ai-memory-template | [![v](https://img.shields.io/github/v/release/dpkg-s/ai-memory-template?label=&color=blue)](https://github.com/dpkg-s/ai-memory-template/releases/latest) | 提供 MCP 端点，必须先有它 |
| ai-memory-web | [![v](https://img.shields.io/github/v/release/dpkg-s/ai-memory-web?label=&color=blue)](https://github.com/dpkg-s/ai-memory-web/releases/latest) | 浏览器控制台 |
| ai-memory-docker | [![v](https://img.shields.io/github/v/release/dpkg-s/ai-memory-docker?label=&color=blue)](https://github.com/dpkg-s/ai-memory-docker/releases/latest) | 镜像里打包了控制台 |

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

## 下载什么

Release 提供控制台源码包与 Windows 安装器。v1.11.3 及更早版本尚无校验文件；下一次由新工作流发布的版本起，
两个附件都会各自附同名 `.sha256`，可用 `sha256sum -c <文件名>.sha256` 校验：

| 附件 | 用途 |
| --- | --- |
| `web-console-v<X.Y.Z>.tgz` | 控制台源码包，不想用 git clone 时下载它 |
| `ai-memory-setup.exe` | Windows 图形化安装器（装的是 MCP 服务端，与控制台无关） |

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
镜像依赖三个约定，改部署时对齐它们即可：

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

## 独立部署

控制台**不依赖核心仓的任何文件**，只需要一个可达的 MCP 端点 —— 可以单独 clone、单独升级，
把界面放在一台机器上、MCP 服务端放在另一台上。

唯一例外是 `--with-mcp`：它要把核心仓的 `serve_http.py` 拉起为子进程，因此需要 `--core-dir`。

对记忆库的一切读写都走 MCP 协议，不直连 vault、不进程内直调 —— 所以控制台换掉 MCP 实现
（换成另一套同协议的服务端）也能照常工作。

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
| `#/settings` | 配置 | 连接、阈值、FNS 同步、关于与更新 |

## 配置页 · FNS 同步

「配置 → FNS 同步」是给 [Fast Note Sync Service](https://github.com/haierkeys/fast-note-sync-service)（FNS）
同步链路备料的地方。控制台**不参与同步本身**，只负责三件事：存配置、验连通、下发。

### 五个字段

| 字段 | 说明 |
| --- | --- |
| `server` | 服务地址，形如 `https://host:58889` |
| `client_type` | 客户端标识。FNS 没有「账号」这个维度，它对应令牌里的 `c:` 维度；旧配置里的 `account` 读取时自动迁移 |
| `vault` | 目标 vault 名 |
| `token` | 服务端签发的 JWT，通常以 `eyJ` 开头 |
| `exclude` | 额外排除规则，与内置的 `.git` / `.obsidian` / `.trash` / `ai-memory` 合并去重 |

写盘时按这张白名单过滤，不落未知字段。**凭据落在 vault 之外** —— 这几项写进
`AI_MEMORY_WEB_CONFIG` 指向的 `config.json`，不写进记忆库目录：写进 vault 会被同步链路原样上传。
前端也不回显完整 token，只保留掩码。

### 粘贴 JSON 自动识别

FNS 客户端 `config.json` 的键名（`api` / `apiToken` / `vault` / `client`）与本页字段不一致，
而 token 是一长串 JWT，手抄四个字段极易出错。点「快速导入」粘贴整段 JSON 即可：键名归一化
（小写、去 `_ - .` 空格）后按别名表匹配，兼容嵌套对象与 ` ```json ` 围栏，认不出的键会原样列出，
不静默吞掉。识别结果**只填表、不落盘**，仍要点「保存」。

### 体检看的是业务码，不是 HTTP 状态码

FNS 的业务失败同样是 HTTP 200 + `code != 1`，所以「测试」按钮解析的是 `code`：

| `code` | 含义 |
| --- | --- |
| `1` | 成功 |
| `304` | 该接口在这台服务端上不存在（版本过旧，或根本不是 FNS） |
| `308` | 令牌已吊销或不存在 —— 到 FNS 后台重新签发一枚 |
| `315` | 权限不足 —— 通常是 vault 未加入该令牌的白名单 |

体检打的是 FNS 自己的 `/api/health` 与 `/api/vault`，能区分「连不上」「令牌废了」「vault 名拼错」
「令牌没这个库的权限」，而不是只报一个「连接失败」。

### 配置下发：容器反向拉取

容器里的 `fns-sync` 启动时向控制台要一份渲染好的 YAML（`GET /internal/fns/config.yaml`），
拿不到才回退它自带的兜底模板。这样不必给同步容器任何写权限，也不用把 token 复制两份 ——
配置真源只有控制台这一处。

该端点的鉴权走容器间共享密钥 `X-Internal-Key`（`AI_MEMORY_WEB_INTERNAL_KEY`，为空即关闭该端点），
三种失败各自可辨：**404** 功能未启用、**401** 密钥错、**503** 配置不全（附缺失项）。
响应头 `X-Fns-Config-Revision` 是内容摘要，容器据此判断要不要重启自己 —— 比时间戳可靠。

缺 `server` / `token` / `vault` 时**不生成**配置而是回 503：拿一份空令牌的 YAML 去启动，
故障会推迟到 WebSocket 握手阶段才暴露，那是最难定位的一种。

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

## 参与开发

零构建约束、CSS 分片顺序、分层守卫、测试命令、发版流程与版本号规则见
**[CONTRIBUTING.md](CONTRIBUTING.md)**。

## 许可

MIT © 2026 dpkg-s
