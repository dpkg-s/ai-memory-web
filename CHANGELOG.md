# 更新日志

本仓由 [ai-memory-template](https://github.com/dpkg-s/ai-memory-template) 的 Web 控制台部分拆分而来，自拆分起独立维护。

## [1.0.0] - 2026-10-16

### 独立成仓

- 从 `ai-memory-template@98f27b4` 拆出 Web 控制台，本仓自此承载**前端 + 后端**：`serve_web.py`（入口）、`web_console.py`（Starlette 装配层）、`web/`（前端静态资源）。
- 新增 `core_path.py`：定位 ai-memory 核心模块目录（`memory_config` / `transport_http`）并注入 `sys.path`。核心模块的唯一事实源仍在 `ai-memory-template`，本仓**不复制、不派生**。
- `web_console.UPDATE_BACKEND_FILES` 由 11 项（含 `server.py` 等 MCP 文件）收敛为本仓的 3 项。
- `tests/test_web.py` 随控制台迁入本仓。

### 版本口径

`web_console.WEB_VERSION` 是后端常量（`1.0.0`）；对外称「控制台 v3.1」指的是它随 ai-memory v3 阶段引入，两者不是同一个编号体系。
