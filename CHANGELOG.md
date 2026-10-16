# 更新日志

本仓由 [ai-memory-template](https://github.com/dpkg-s/ai-memory-template) 的 Web 控制台部分拆分而来，自拆分起独立维护。

## [1.1.0] - 2026-10-16

> 主题：**拆掉「第二条腿」** —— 本仓不再 import 核心仓的任何模块，对核心仓的关系只剩「连接 MCP」。

### Changed

- **删除 `core_path.py`**（原 100 行）：它的唯一职责是运行时定位 `ai-memory-template` 目录、`sys.path.insert` 注入，好让本仓 import 得到 `memory_config` / `transport_http`。这条通道被整体拆除，文件随之删除，`UPDATE_BACKEND_FILES` 由 3 项收敛为 2 项。
- **阈值配置面改走 MCP 工具 `memory_config`**（新增于核心仓 v3.0.0）：
  - 读：`GET /api/thresholds` → `memory_config(action="get", output_format="json")`；
  - 写：`POST /api/thresholds` → `memory_config(action="set", …)`，键集校验 / 写前备份 / 原子替换 / 失效缓存全部在服务端完成。
  - 本模块删掉 `render_toml()` / `_toml_scalar()` / `_threshold_source()` 以及基于 `memory_config` 的 `thresholds_state()` / `write_thresholds()` 实现，改为两个 `async` 版本（只做「转前端契约 JSON」与「施加本台只读开关」）。
  - 前端契约**未变**（`vault` / `config_path` / `file_exists` / `writable` / `ttl` / `last_error` / `keys{value,default,type,source,env,label,desc}`），前端零改动。
- **`DEFAULT_MCP_URL` 改为本仓字面常量**（原为 `transport_http.DEFAULT_HOST/PORT/PATH` 拼装）。它本就只是个可被 `AI_MEMORY_WEB_MCP` 覆盖的默认值，为它维持一条跨仓 import 通道不划算。
- **`serve_web.py --with-mcp` 必须显式指定核心仓目录**（新增 `--core-dir`，或 `AI_MEMORY_CORE_DIR`）：不再自动上溯猜路径。未给出时明确报错并打印可照抄的命令。
- `AI_MEMORY_WEB_CONFIG_WRITE=0` 的只读语义保持在**本侧**（本台自己的策略开关）；`writable` 现在是「服务端认得 vault」与「本台未关写入」的**与**。
- 工具分组表新增 `memory_config` → `maintain`（它写盘、改变全库行为，与 `memory_heat_suggest` 同类，不是只读报告工具）。
- 前端文案更正：阈值备份的位置已从「vault 之外的 `~/.ai-memory-web/backups/`」变为**同目录 `memory.toml.bak.<时间戳>`**（保留最近 10 份，命中 vault 自带 `.gitignore` 的 `*.bak.*`）。

### Added

- `tests/test_web.py` C 段新增 **C2**：导入控制台后 `sys.modules` 里**不得**出现 `memory_config` / `transport_http` / `core_path` —— 把「无跨仓 import」钉成机器守卫（比 C1 的 `server` 更严：核心仓的**任何**模块进内存都意味着两份事实源）。
- G 段的 AST 扫描器支持 `@mcp.tool(name="…")` 名称覆盖：`memory_config` 的 Python 函数名是 `_memory_config_tool`（避免遮蔽同名的 `memory_config` 模块），只取函数名会误判成「分组表有陈旧键」。

### Fixed

- **阈值整状态写会把 `body_truncate_chars` 写坏**：核心仓 `memory_config` 工具最初把 `values` 标注成 `dict[str, float]`，SDK 的入参校验据此把 `8000` **强转成 `8000.0`**，而该键期望 int ⇒ 一次正常保存被服务端判成类型错误（端到端 F9b 当场 400：`配置 body_truncate_chars：期望整数，得到 8000.0`）。标注放宽为 `dict[str, Any]`，类型校验仍由核心仓按 `_SPEC` 做（int/float 分开、拒 bool），比 JSON Schema 的 number 更严。
- `serve_web.py` 模块 docstring 里的 Windows 路径示例触发 `SyntaxWarning: invalid escape sequence`。

### Tests

- 本仓 **72 断言全绿**（1.0.0 基线 68；+C2 四条 + 端到端计数 24→25），退出码 0。
- 端到端仍在真起的 `serve_http` + `serve_web` 上跑完阈值**写→读往返**，并验证 vault 里的 `*.md` 逐字节未动。

## [1.0.0] - 2026-10-16

### 独立成仓

- 从 `ai-memory-template@98f27b4` 拆出 Web 控制台，本仓自此承载**前端 + 后端**：`serve_web.py`（入口）、`web_console.py`（Starlette 装配层）、`web/`（前端静态资源）。
- 新增 `core_path.py`：定位 ai-memory 核心模块目录（`memory_config` / `transport_http`）并注入 `sys.path`。核心模块的唯一事实源仍在 `ai-memory-template`，本仓**不复制、不派生**。
- `web_console.UPDATE_BACKEND_FILES` 由 11 项（含 `server.py` 等 MCP 文件）收敛为本仓的 3 项。
- `tests/test_web.py` 随控制台迁入本仓。

### 版本口径

`web_console.WEB_VERSION` 是后端常量（`1.0.0`）；对外称「控制台 v3.1」指的是它随 ai-memory v3 阶段引入，两者不是同一个编号体系。
