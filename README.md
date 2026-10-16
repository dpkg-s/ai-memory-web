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

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `AI_MEMORY_CORE_DIR` | （空） | 核心仓目录；**仅** `--with-mcp` 需要（用于找 `serve_http.py`），不再用于 import |
| `AI_MEMORY_WEB_HOST` | `127.0.0.1` | 监听地址；非回环**必须**配 token，否则拒绝启动 |
| `AI_MEMORY_WEB_PORT` | `8811` | 监听端口 |
| `AI_MEMORY_WEB_TOKEN` | （空） | 设了之后 `/api/*` 需 `Authorization: Bearer <token>` |
| `AI_MEMORY_WEB_MCP` | `http://127.0.0.1:8700/mcp` | 上游 MCP 端点 |
| `AI_MEMORY_WEB_STATIC` | `<本仓根>/web` | 前端静态资源目录 |
| `AI_MEMORY_WEB_CONFIG` | `~/.ai-memory-web/config.json` | 配置面存储 |
| `AI_MEMORY_WEB_CONFIG_WRITE` | `1` | `0` = 阈值只读 |

## URL 约定

| 路径 | 去向 |
| --- | --- |
| `/` | `web/index.html` |
| `/assets/*` | `web/` 目录（`css/`、`js/`、`vendor/`） |
| `/api/*` | 后端代理到 MCP（可选 `Bearer` Token） |

后端接口：`/api/health`、`/api/overview`、`/api/tools`、`/api/call`、`/api/thresholds`、`/api/config`、`/api/update`、`/api/update/restart`。

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
