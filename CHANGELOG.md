# 更新日志

本仓由 [ai-memory-template](https://github.com/dpkg-s/ai-memory-template) 的 Web 控制台部分拆分而来，自拆分起独立维护。

## [1.2.0] - 2026-10-19

> 主题：**让「有更新」自己浮出来** —— 更新面扩为双目标，进台即检；并把「远端版本读不到」这一整类观感问题从三处堵掉。

### Added

- **更新面扩为双目标**（2026-10-16）：`web`（本仓）与 `core`（`ai-memory-template` 的 MCP 运行时）各查各的、各更各的。后端拆出 `CORE_PROGRAM_FILES`（12 项运行时/依赖）+ `core_root()`（`AI_MEMORY_CORE_DIR` → 本文件父目录 → `~/.workbuddy/mcp-servers/ai-memory`，**设错不回落**），`/api/update` 支持 `?target=web|core|all` 并恒返 `{ok, checked, targets:[…]}`（**定位不到的目标也占位**，不静默少一张卡）；前端改为双卡 + 旧契约 `normalize()` 兜底。
- **进 web 自动检测更新**（2026-10-19）：`Root.mounted` 调 `autoCheckUpdates()` —— 后台跑一次 `?fetch=1`，**不阻塞首屏、失败静默**（`loadUpdate(..., quiet)`，原因仍在关于页 banner）。一次页面会话只联网一次（`S.update.autoStarted`）。
- **「有可用更新」提示**：有更新时发一条 `warn` toast（目标名 + 远端版本，9 s），并在侧栏「配置」右上角留一个 `.nav-dot` 圆点，直到更新完成或再检测为最新。判据只认服务端 `behind > 0 || changed_count > 0`（`pendingOf()`）——**不拿版本号差异当判据**，本地领先远端时那样会误报。
- **CI 与自动发布**：新增 `.github/workflows/ci.yml`（Python 3.10~3.13 矩阵 + `ruff`）与 `release.yml`（推 `v*` tag：先跑全量回归，再 `gh release create --generate-notes`）。测试套的端到端段需要核心仓的 `serve_http.py`，故 CI 额外检出 `dpkg-s/ai-memory-template` 并导出 `AI_MEMORY_CORE_DIR` —— 本仓首次具备可独立运行的 CI 与 Release。

### Fixed

- **离线状态覆盖已联网的远端结论**：`?fetch=0` 的 payload 不含任何 `remote_*` 字段，而 `mergeTargets()` 原本无条件替换 ⇒ 刚联网拿到的 `v1.1.0  94e0521` 会在进「关于」页或点「只读本地」时瞬间退回「（未检查）」，看起来像远端版本读不到。现按 `REMOTE_KEYS` 做降级保护（`checked === false` 且旧值 `checked === true` 时保留旧远端结论），本地字段仍照常更新。
- **「远端版本」三态文案**：原来只判 `!remote_sha`，把「压根没联网」和「联网失败」显示成同一句「（未检查）」。现在区分 **`（未检查）` / `检查失败（原因见下方）` / `已检查，未取到提交号`**，有提交号时正常显示 `vX.Y.Z  <短 sha>`；`remote_version` 为空会附注「CHANGELOG 首段非 `## [x.y.z]`」。

### Tests

- 本仓 **83 断言全绿**（1.1.0 为 72，双目标扩到 80，本次 +3），退出码 0。
- 新增源码守卫：**H11** 离线状态不覆盖联网结论（`REMOTE_KEYS` 降级保护）、**H12** 自动检测接线 + 导航圆点、**H13** 三态文案。
- 端到端真起 `serve_http` + `serve_web`，`/api/update?fetch=0` 两目标均占位且 `checked=false`；真机 `?fetch=1` 联网检查两目标均 `ok`。

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
