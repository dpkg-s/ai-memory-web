# ai-memory-web

**ai-memory 记忆库的 Web 控制台。**

浏览器里的记忆库控制面：概览、记忆库、调试台、配置四页。纯静态前端、**零构建步骤** —— 原生 ES 模块 + 本地 vendor，`git clone` 后即可运行。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Frontend](https://img.shields.io/badge/build-none%20(vanilla%20ESM)-blue)]()
[![Vue](https://img.shields.io/badge/Vue-3.4.38-42b883)](https://vuejs.org/)
[![Console](https://img.shields.io/badge/console-v3.1-informational)]()

---

## 这是什么

「ai 融合记忆库」（[ai-memory-template](https://github.com/dpkg-s/ai-memory-template)）的浏览器控制台前端。本仓库由该仓库的 `web/` 目录拆分而来，成为可独立部署、独立演进的前端仓库。

一条硬约束决定了它的形态：**浏览器不直连 MCP**。前端只与同源 HTTP API（`/api/*`）通信，由后端代理到 MCP 端点。

## 与 ai-memory-template 的关系

| 层 | 所在仓库 |
| --- | --- |
| MCP 服务端（24 工具 / 7 模块 / Markdown vault） | [ai-memory-template](https://github.com/dpkg-s/ai-memory-template) |
| Web 后端（`serve_web.py` + `web_console.py`：API 层 + 静态托管） | [ai-memory-template](https://github.com/dpkg-s/ai-memory-template) |
| **Web 前端（本仓库）** | **ai-memory-web** |

拆分基线：`ai-memory-template@98f27b4`。

## 快速开始

### 方式一：对接真实后端（推荐）

后端通过 `AI_MEMORY_WEB_STATIC` 指向本仓库根目录，其余零改动：

```bash
# 在 ai-memory-template 目录下执行
AI_MEMORY_WEB_STATIC=/path/to/ai-memory-web \
  python serve_web.py --port 8811 --mcp http://127.0.0.1:8700/mcp
```

打开 <http://127.0.0.1:8811/>

### 方式二：仅预览界面（无数据）

```bash
python -m http.server 8080 --directory .
```

此模式下 `/api/*` 全部 404，数据区为空或报错 —— 仅用于布局与视觉检查。

## URL 约定

| 路径 | 去向 |
| --- | --- |
| `/` | `index.html` |
| `/assets/*` | 本仓库根（`css/`、`js/`、`vendor/`） |
| `/api/*` | 后端 API（同源 fetch，可选 `Bearer` Token） |

后端使用的接口：`/api/health`、`/api/overview`、`/api/tools`、`/api/call`、`/api/thresholds`、`/api/config`、`/api/update`、`/api/update/restart`。

## 页面

| Hash 路由 | 页面 | 职责 |
| --- | --- | --- |
| `#/dashboard` | 概览 | 条目统计、类型/作用域分布、写入趋势、近期活动 |
| `#/console` | 调试台 | 24 个 MCP 工具的调用台（按用途分 6 组，参数表单 + 结果面板） |
| `#/library` | 记忆库 | 条目浏览、搜索、阅读 |
| `#/settings` | 配置 | 连接、阈值、FNS 导入、关于与更新 |

## 目录结构

```
├── index.html              # 入口：主题预置脚本 + vendor 同步加载 + ESM 入口 js/main.js
├── css/                    # 8 片；CSS 无显式依赖，层叠顺序即加载顺序（不可调换）
│   ├── 1-tokens.css        # 设计令牌（颜色 / 间距 / 动效时长）
│   ├── 2-layout.css        # 外壳骨架（sidebar / 三栏 / grid）
│   ├── 3-components.css    # 基础组件
│   ├── 4-console.css       # 调试台
│   ├── 5-overlays.css      # 模态 / Toast
│   ├── 6-anim.css          # 动画与过渡
│   ├── 7-views.css         # 各页面样式
│   └── 8-responsive.css    # 响应式分档
├── js/
│   ├── main.js             # 入口：挂载 Vue 应用
│   ├── core/               # 核心层：api / store / router / data / theme / icons / util / anim
│   ├── components/         # 14 个基础组件（XCard / XStat / XKv / XPill / XSkel / …）
│   ├── features/           # 功能层：console / library / settings / update / fnsImport
│   └── views/              # 页面层：Root / Dashboard / ConsolePage / LibraryPage / SettingsPage
└── vendor/                 # 本地化第三方库（无 CDN、无 npm）
    ├── vue.esm-browser.prod.js   # Vue 3.4.38（ESM 具名导入，比 global 版小 126 KB）
    ├── marked.min.js             # Markdown 渲染 12.0.2（UMD → window.marked）
    ├── purify.min.js             # DOMPurify 3.1.6（HTML 消毒）
    ├── gsap.min.js               # GSAP 3.13.0
    └── Flip.min.js               # GSAP Flip 3.13.0
```

## 开发约定

1. **零构建**：没有打包器、没有 npm 依赖、没有产物目录。改完刷新浏览器即生效。
2. **CSS 分片顺序不可变**：CSS 没有 `import` 那样的显式依赖，层叠顺序就是加载顺序，因此 `index.html` 中的 8 个 `<link>` 顺序不可调换、不可改为按需加载。
3. **模块加载次序**：vendor 的 UMD 脚本（`marked` / `DOMPurify` / `gsap` / `Flip`）为同步普通脚本，先于 ESM 入口执行；模块顶层读取 `window.marked` 等一定拿得到值。
4. **主题**：`data-theme`（解析后的实际值）+ `data-theme-pref`（用户偏好）；早于首帧生效以避免闪烁。`?theme=light|dark|auto` 可作深链覆盖，并写回 `localStorage`。
5. **hash 路由**：`#/dashboard` 等，不依赖服务端路由重写。

## 许可

MIT © 2026 dpkg-s
