# 更新日志

本仓由 [ai-memory-template](https://github.com/dpkg-s/ai-memory-template) 的 Web 控制台部分拆分而来，自拆分起独立维护。

## [1.9.0] - 2026-10-22

> 主题：**撤掉圆形扩散，回到单时钟**。1.8.0 的扩散本身好看，但它与开关动画在物理上无法同步 —— View Transition 期间整页是一张静态快照，开关被冻在快照里，扩散期间不存在任何可见的活体动画。于是只剩两条路：跳帧（1.8.0 之前）或错后（1.8.0）。实测错后 671ms，比跳帧更像不同步。这一次把页面换色和开关放回同一条时钟：**同帧起跑、同帧收尾**。

### Changed

- **主题切换改回单时钟渐变**（`core/theme.js` 重写 + `6-anim.css` 末段重写）—— 页面换色 0.45s、缓动 `--ease-in-out`，与开关 timeline 的滑块首段（0.45s、`power2.inOut`）**完全一致**，两者同一帧起跑。没有快照 ⇒ 没有冻结 ⇒ 既无跳帧也无滞后。
  - **为什么放弃 View Transitions**：VT 期间原 DOM 不可见。让 timeline 照常跑 ⇒ 揭示完成瞬间画面从第 0 帧跳到第 0.55s 帧（滑块像被抽了一下）；让 timeline 暂停等 ⇒ 页面先换完、开关 0.55s 后才补演。探针实测（真实时钟）：页面 `t≈108ms` 已换、滑块 `t≈779ms` 才起跑，**错位 671ms**。整页快照下「有扩散」与「有同步」不可兼得。
  - **`html.theming *` 而非容器白名单**：只过渡容器的话，文字色会先在旧底色上跳到新色，那 0.2s 里白底白字。代价是 0.51s 内全站元素的 transition 属性列表被改写 —— 因此门控 `.tsw[data-anim="1"]`（特异性 0,2,0 > 0,1,1）必须压住本规则，否则开关收窄的 `width` 过渡被顶掉、变成瞬跳。
  - **一切延迟归零**：1.8.0 降级路径的三层错峰（0/60/80/140ms）已删除 —— 错峰本身就是「不同步」。
- **门控点 0.65s → 0.45s**（`ThemeSwitch.js`）—— 0.65s 里的 0.2s 余量是留给 VT 的，VT 撤掉后一并去掉。点击到可收纳 **1.35s → 0.6s**。

### Removed

- **`core/theme.js` 的 `vtBusy()` / `whenVtDone()` / `setOrigin()` / `resolveOrigin()`** 与 `--vt-x/--vt-y/--vt-r` 三个 CSS 变量、`::view-transition-*` 与 `@keyframes theme-reveal` —— 一并删除，不留死代码。
- `applyTheme(pref, origin, silent)` 的 `origin` 参数（圆形扩散的圆心，已无用途）；`ThemeSwitch.toggle()` / `followSystem()` 不再计算按钮矩形。

## [1.8.0] - 2026-10-22

> 主题：**让两套时钟不再抢同一个画面**。三件事：① 主题开关的「收纳」与「点击切换」原本是两条互不知情的时钟，现在串行；② 主题切换从「一帧换完」改成从开关圆心扩散；③ 修掉一个 Vue 反模式 —— 手动加的类会被 `:class` 的 patch 静默抹掉。

### Fixed

- **主题开关收纳与切换打架**（`ThemeSwitch.js` + `3-components.css` §16）—— 症状是点击后稍一移开鼠标，月亮被切成一半再滑出来；连点两次还会错位叠加。根因不是「谁太快」，是两条时钟抢同一个视觉结果：
  - 收窄走 CSS 过渡（`.tsw` 的 `width`、`.tsw-box` 的 `left`），切换走 GSAP timeline（滑块 0→0.95s，云/星尾巴到 2.55s）；
  - 而 `.tsw.night .tsw-box { left: -59s }` 是**类切换即生效**的终态值，不看 timeline 播到第几帧 ⇒ 窗口先左移 42.48px，滑块还在半路，收窄后那 30.24px 窗口里只剩空天空。
  - 解法：门控串行。timeline 播放期间锁 `data-anim="1"`，窗口锁定为全展开并禁用过渡；滑块**第一段**落定（0.65s）后解禁，再延 150ms 摘锁。
    - 为什么不等第二段（0.45→0.95 的 66→63 微调）：门控要防的是「窗口按终态左移 42.48px 而滑块还在半路」，0.45s 后滑块已在 66、占 66~102，收窄窗口覆盖 59~101 ⇒ 月亮完整在窗内，3px 微调不会跑出窗口。多等半秒纯属白等。
- **`lock()` 加的类被 Vue 抹掉**（本轮实测抓到的真坑）—— 模板是 `class="tsw" :class="{night: night}"`，Vue 3 的 options watch 默认 `flush:'pre'`：watch 先跑（加类成功），紧接着本组件的 patch 重算 `:class` 并把整个 class 属性覆写，手动类被静默抹掉。探针证据：`classList.add("animating")` 调用过 1 次，60ms 后 classList 里没有它，`MutationObserver` 只看到 `tsw > tsw > tsw`。改用 `data-anim` 属性（不在 diff 目标里）后，同一探针读到 `w=72px / left=0px / data-anim=true`。

### Added

- **主题切换圆形扩散**（`core/theme.js` + `6-anim.css` 末段）—— 用 View Transitions 把「改 data-theme」包进快照过渡，新主题以开关中心为圆心 `clip-path: circle()` 扩张揭示，0.55s。
  - 圆心由 `ThemeSwitch.toggle()` 传入（按钮中心），半径按「圆心到四角最远距离」算，写进 `--vt-x` / `--vt-y` / `--vt-r`。
  - **与开关动画串行**：VT 期间整页是静态快照，原 DOM 不可见，timeline 若照常起跑，观众看到「定格 → 揭示完成瞬间跳到第 0.55s 帧」，滑块像被抽了一下。所以扩散在跑时 timeline 以 `paused` 创建，扩散结束（含 rejected / 超时兜底）后由 `whenVtDone()` 放行。
  - **0.55s 与滑块首段 0.45s 同频**，缓动也同族（`power2.inOut` ≈ `cubic-bezier(.65,0,.35,1)`）—— 一快一慢会让「页面已换完、开关还在爬」，这是「不融洽」的另一半来源。
  - **降级不丢**：不支持 VT（或 `prefers-reduced-motion`）时回落到三层错峰 —— 顶栏 0ms / 侧栏 60ms / 状态栏 80ms / 主区 140ms 颜色过渡，460ms 后摘 `.theming`。两套互斥，绝不并行（叠加会让新快照抓到中间色，比生硬更脏）。
  - 首屏那次一律不演（样式表可能还没应用完，演出来只会闪一下）；系统主题自动变化也不演（用户没操作，突然一圈扩散会很突兀）。

### Changed

- **收窄时长 0.5s → 0.62s、`ease-in-out` → `ease-expo`** —— 原值「抽得太急」，与滑块 1.5s 的节奏差 3 倍；expo 起步快、尾段长，收窄时尾部有自然收势。
- **开关时间轴整体压缩**（滑块 0.6+0.9 → 0.45+0.5，天空 0.6→0.5，云/星/月同步收紧，光晕 0.6+0.7 → 0.5+0.5）—— 原时序是 WPF 原文 1:1 移植，本次按主人要求加快；比例关系（首段/回弹段）保持不变，只是整体更利落。

## [1.7.0] - 2026-10-22

> 主题：**让清单自己长出表单，让令牌自己长出地址**。两件事：① 访问控制页从「双栏常驻表单」改成「清单行内展开」—— 旧版点第 1 行的「重置口令」，输入框从第 8 行下面冒出来，这是本页最大的信息错位；② 新增 `/mcp` 流式反代，令牌从此能拼成一条可直接粘进 MCP 客户端的 URL，而不是只能贴进 header。

### Added

- **`/mcp` 流式反代**（`web_console.py`）—— 控制台在自己的端口上挂 `/mcp`，鉴权后反代到 `AI_MEMORY_WEB_MCP` 指向的上游。
  - 为什么需要它：上游 MCP 端点**根本不鉴权**（只绑回环），而令牌表只在控制台这边。要让「另一台设备拿一枚限时令牌就能连 MCP」成立，必须有一个既认令牌、又能转发流式响应的门口。
  - **必须流式**：POST 可能直接回 `text/event-stream`，GET 是长活 SSE 通道。任何「读完 body 再回包」的写法都会把 SSE 变成「等服务器关闭才吐第一帧」，客户端表现为「连上了但永远收不到消息」。
  - 透传 `Mcp-Session-Id`；不向上游转发本控制台自己的 `Authorization` / `Cookie`（令牌是给控制台的，不该多传一跳）。
  - 鉴权口径与 `/api/*` 完全一致：未登录且无令牌 ⇒ 401；凭据有效但上游不可达 ⇒ **502**（不是继续 401）。
- **`?token=` 第三通道**（`token_from_request`）—— `Authorization: Bearer` > `X-Auth-Token` > 查询参数，三选一。只因为「多数 MCP 客户端只暴露一个 URL 字段」。
  - 代价写进了代码注释与界面提示：URL 里的令牌会进 uvicorn 访问日志、浏览器历史、反代日志 ⇒ 内网适用，公网请用 header。
- **访问控制页行内展开**（`AccessPage.js` + `7-views.css` §20）：
  - 清单底部一条虚线「**+ 新建账号 / + 签发令牌**」，点击就地展开表单（不再占右栏常驻地）。
  - 行按钮「**改密码**」在该行**正下方**展开一行输入，不再跑到卡片尾部。
  - 令牌行新增「**重发**」：吊销旧令牌 + 同参数（角色/次数/剩余时长）新签一枚，明文回到顶部卡片。
  - 签发成功后给出**连接串卡片**：明文令牌 + 可编辑主机（域名 / IP / 带不带端口都行）+ `…/mcp?token=…` 一键复制 + `Authorization: Bearer …` 一键复制。

### Changed

- **右栏只剩「我的账号」**。写操作全部搬进左栏行内表单后，右栏不再需要为新表单留位置；身份管理仍贴着页头身份标签（1.6.0 的定案不变）。
- 令牌 Tab 的「一次性明文横幅」升级为「明文 + 连接串」卡片，顺序固定为「先给令牌，再给怎么用它」。
- **页头的「访问控制」大标题已删**（主人指令）。左侧面包屑本来就是「ai-memory › 访问控制」，页内再重复一行 24px 粗标题属同义冗余。
  - `.ac-head` 因此从 `space-between`（标题左 / 标签右，两列）改为 `flex-end`（只剩标签，右对齐贴在「我的账号」卡上方）；≤899px 塌单列时回退为左对齐，否则标签会孤零零浮在右上角。
- **身份标签并进分段控件那一行**（`.ac-bar`）—— 标题删掉后它独占一整行只为放两个 chip，纵向白吃约 40px。现在是「左：账号 / 令牌分段，右：当前身份」，一行说完「在看哪一类」与「以什么身份看」。原 `.page-head.ac-head` 规则随之删除，`.ac-seg` 的 `margin-bottom` 在工具条内归零。
- **右栏「我的账号」只对非管理员显示**（`.ac-grid.ac-solo`）。两个改口令入口不是重复：
  - 行内「改密码」走 `PATCH /api/users/{name}` —— **admin 专属、不验原口令**，用于重置他人（忘口令、给新人设口令）。
  - 右栏「修改口令」走 `POST /api/password` —— **任何登录用户、必须验原口令**，改完 epoch 轮换。
  - `operator` / `viewer` **看不到账号清单**（`GET /api/users` 是 admin 专属）⇒ 行内按钮对他们根本不存在，右栏那张卡是他们唯一的入口，必须留。
  - 管理员则相反：身份已在工具条标签里，改自己口令走行内即可，留一张几乎空的卡没有意义。收掉后清单占满整宽。

### Fixed

- **账号清单恒空**（本轮探针实测抓到）：`main.js` 直接 mount，`/api/session` 是异步的 ⇒ 本页首帧拿到的 `canManage` 还是 `false`，`refresh()` 走非管理员分支，权限到位后不重取，表现是「账号 0 个、只有一个 + 新建账号」，必须整页刷新。改为 `watch: isAdmin` 翻转时补拉一次。
- **`.conn` 类名冲突**：顶栏「已连接 12ms」连接指示器已占用 `.conn`，新样式会污染它。连接串改用 `.ac-conn` / `.ac-conn-row`。
- **`.select` 的 `width:100%` 撑断行内动作组**：账号行里 4 个控件被挤成上下两排、行高一倍。`.ac-acts .select` 收回自动宽度并对齐 `.btn-sm` 的 31px。

### Tests

- `tests/test_web.py` **83 → 87 断言**：D7（`?token=` 通道）、D8（`/mcp` 无凭据 401）、D9（凭据有效但上游不可达 502）、F12（真上游 + 真 SSE 完成 MCP `initialize`）。
- `tests/test_auth_store.py` 41 断言保持全绿。

## [1.6.0] - 2026-10-22

> 主题：**从「一把钥匙」到「发钥匙的人」** —— 1.5.0 只解决了「怎么进门」，没解决「谁能进、能进多久、能做什么、走了怎么收回」。面向公网入口，三个硬伤无法再用文档规避：token 永久有效且无法单独吊销、一枚 token 通吃全部工具、scrypt 参数停在推荐区间下沿。本轮引入用户表与令牌表，网关改为回调查询。

### Added

- **多用户账号表**（`web_store.py` + `config/users.json`）—— 管理员在线增删改账号，不必重建容器。
  - 三种角色：`admin`（管人管令牌）/ `operator`（全部工具）/ `viewer`（只读工具组）。
  - 从 1.5.0 单用户配置**自动迁移**：表为空时把 `.env` 里的 `USER` + `PASSWORD_HASH` 变成 admin，升级后不用手工建号。
  - 「至少保留一个启用的管理员」是硬约束 —— 否则管理面会被锁死在门外。
- **访问令牌表**（`config/tokens.json`）—— 每人一枚，可单独吊销。
  - **限时**：`expires_in` 到期自动失效。
  - **限次**：`max_uses` 用满即废；带 **30 秒去重窗口** —— 一次 MCP 工具调用会产生 2–3 个 HTTP 请求，逐请求计数会让「限 100 次」实际只能调 30 来个工具。
  - 明文只在创建响应里出现一次，表里只存 `sha256`；列表只回 `prefix` 供辨认。
- **`/api/users`、`/api/tokens`、`/api/password`** 三条管理面路由，以及 `/internal/token/verify`（网关回调）。
- **「访问控制」页**（`web/js/views/AccessPage.js`，导航第 4 项，快捷键 `4`）—— 一个页面两个 Tab：**账号**（增删改、改角色、重置口令、启停）与**令牌**（签发、限时、限次、吊销）。
  - **布局为「双栏工作台」**：左栏是只读清单（账号表 / 令牌表，含一次性明文横幅与行内重置），右栏是写操作（新建账号 / 签发令牌 / 我的账号）。读写并置后全流程一屏完成，不必从列表底部滚到独立的新建卡；右栏 sticky 跟随，≤899px 整块塌成单列。
  - 「修改我的口令」收进右栏「我的账号」卡并**默认收起** —— 它属于身份管理，应贴着页面右上角的身份标签，而不是被 Tab 隔开甩在页尾。
  - 页头只留标题与当前身份标签（`admin` / 角色 / 令牌通道），原「账号决定谁能登、令牌决定程序以什么身份调工具」那句说明已删。
  - 用户与令牌合并成一页而不是拆两项：两者回答的是同一个问题「谁有权限、以什么身份、到什么时候为止」，分成两页会让侧栏变成 6 项，而它们从不同时使用。
  - 签发后**明文只显示一次**，界面用醒目横幅提示「关闭后无法取回」，并给一键复制。
  - 界面上的角色下拉会按当前身份收窄（`operator` 看不到 `admin` 选项）—— 藏 UI 不是权限，只是别让人填完才吃 403。
- **网关改 `auth_request`**（`nginx` 模板）—— 从「和单个 token 字符串精确比对」改成每次回调控制台查表。这是「单独吊销 / 限时限次 / 按人分权」能成立的前提：字符串比对无法表达任何动态状态。

### Changed

- **scrypt 参数 2^14 → 2^16**（16 MiB → 64 MiB）。原值处于 OWASP 推荐区间下沿，在多用户 + 公网入口下不够。
  - 必须显式给 `maxmem`：`hashlib.scrypt` 默认只批 32 MiB，不提会抛 `memory limit exceeded`，且**只在登录时**才炸。
  - 加 **并发闸（最多 2 个）**：单次占 64 MiB，不限并发则 4 个同时登录 = 256 MiB，直接越过容器上限被 OOM kill。
  - 存量哈希**登录即升级**（`needs_rehash` + 就地重算）—— 只改参数不改存量，"提升强度"对老账号等于没提。
- **会话 payload 增加 `r`（角色）与 `e`（epoch）**。无状态会话因此也能**单点吊销**：改口令 / 改角色 / 禁用 / 删号都轮换 epoch，旧 Cookie 立刻作废。
- **容器内存上限 192m → 256m**（`deploy-center.sh`），配合上面的 64 MiB × 2 并发。

### Security

- `viewer` 角色在 `/api/call` 被工具组拦截（用现有 `TOOL_GROUPS` 表判定）；**未归类的工具按最严处理**，只有 admin 可用 —— 新工具不会因为「忘了登记分组」而对只读账号意外敞开。
- 令牌校验失败一律回 401，不区分「过期 / 超次 / 已吊销 / 不存在」，不给爆破进度条。
- 删除账号时**连带吊销其全部令牌** —— 删号却留着令牌等于没删。
- `operator` 不能签发权限高于自己的令牌。
- 内部校验端点要求容器间共享密钥 `X-Internal-Key`；未配置时返回 **404**（功能关闭）而不是 401，便于把「没启用」与「密钥错」在日志里分开。

### Fixed

- **老令牌兼容**：`.env` 里那两枚老 token 是 `token_urlsafe(32)` 生成的、没有 `amt_` 前缀。升级后若按前缀做校验短路，它们会被直接判死 —— 现象是「token 明明没改却全 401」。现由 `config()` 启动时自动 `adopt()` 进表（admin / 永不过期），并去掉前缀短路。
- 修掉一处把 `mode` 初值 `"none"` 当假值判断的写法（`if not mode` 恒为 False），它导致「登录成功但立刻问状态又说没登录」。

### 测试

- 新增 `tests/test_auth_store.py`：41 项（scrypt 参数、用户 CRUD、epoch 吊销、最后管理员保护、限时限次、去重窗口、adopt 兼容、角色→工具组）。
- 原有 `tests/test_web.py` 83 项无回归。
- 线上端到端 `tools/verify-auth.py`：25 项（真 HTTP，含角色越权、令牌吊销即时生效）。
- 页面用**无头 Chrome + CDP** 真验（不是只看接口）：本机 15 项、容器 16 项，覆盖「导航 5 项 / 登录框 / 页面渲染 / Tab 切换 / 一次性明文横幅」。纯接口测试无法发现模板拼接错误 —— 那类错误表现为白屏，而 API 全绿。

## [1.5.0] - 2026-10-21

> 主题：**把门装上，并且不设默认钥匙** —— 此前 `/api/*` 只有一枚共享 token，谁拿到谁就是管理员，且无法撤销单个使用者。本轮加一条独立于 token 的账号登录路径（口令哈希 + 签名会话 Cookie），token 通道原样保留给脚本。

### Added

- **账号登录**（`web_auth.py` + `/api/login` `/api/logout` `/api/session`）—— 与 token 并存的第二条通道，两者可同时启用，登录框底部一键互切。
  - 口令用 **scrypt**（n=2^14, r=8, p=1，单次 ~160–180 ms）哈希后存环境变量；**只依赖标准库** —— 容器里 `requirements.txt` 只有 `mcp`，为了一个口令哈希去加 passlib/bcrypt，等于把「装不上依赖就起不来」引进来。
  - 会话 = `<payload_b64>.<sig_b64>` 的 **HMAC-SHA256 无状态 Cookie**（`HttpOnly` + `SameSite=Lax`，`Secure` 跟随部署形态）。服务端不存会话表，重启不掉线；代价是无法单个吊销（见下方「失效」口径）。
  - 免鉴权路径 `/api/login` `/api/logout` `/api/session` **精确匹配**（非前缀）：实测 `/api/session/xxx`、`/api/loginfoo`、`/api/loginx` 全部 401，无法靠拼后缀绕过。
  - `/api/logout` **不校验登录态**：登出必须永远成功。否则「会话已过期但页面还挂着」时点登出会收到 401，比登不出去更让人困惑。
- **`make_password.py`** —— 生成 `AI_MEMORY_WEB_PASSWORD_HASH`。依赖同目录 `web_auth`，不重复实现 scrypt 参数，避免两处口径漂移。
- **登录失败限流**（`LoginLimiter`）—— 同一来源 IP 5 次 / 5 分钟，超限锁 5 分钟。口令可以短到人能记住，没有限流等于把爆破成本降到「脚本跑一晚上」；32 hex 的 token 不需要限流，因为搜索空间本身就够大。
- **双模式登录框**（`views/Root.js`）+ 侧栏底部「当前身份 / 登出」，`core/api.js` 增 `session/login/logout` 并显式 `credentials: "same-origin"`（会话是 HttpOnly Cookie，不显式带凭据就永远拿不到）。
- **`tests/` 之外的三条验收判据已并入部署侧验收脚本**：未登录必拦 / 登录放行 / 登出回锁。

### Changed

- **登录框不再有任何说明文字** —— 先是删掉「会话保存在 HttpOnly Cookie 中，页面脚本读不到」，随后主人指出 token 那句「令牌只保存在本次浏览器会话（sessionStorage）…」也「不要也没必要加」。结论是**整块 `authHint` 去掉**，`modal-head` 只留标题：那两行是实现说明，用户不需要读，写在登录框里尤其多余。
- **scrypt 哈希的分隔符从 `$` 改成 `:`**（`scrypt:16384:8:1:salt:hash`）。这不是审美问题：哈希要写进 `.env`，而部署脚本是 `set -a; . ./.env` —— `scrypt$16384$8$1$...` 里的 `$16384` 会被 shell 当变量引用展开成空串，**哈希当场损坏，且只在登录时才暴露成「口令永远不对」**，极难联想回 `.env`。`verify_password` 仍兼容旧 `$` 格式。

### Fixed

- **限流器锁定后第 4 次尝试又被放行**（`LoginLimiter._prune`）—— 锁定瞬间 `stamps` 已被清空，下次调用把整条记录 `pop` 掉（连同 `locked_until`），锁等于没锁。改为仅当「无时间戳 **且** 锁定已过期」才丢记录。
- **半配静默开门的风险** —— 只给 `AI_MEMORY_WEB_USER` 却没给哈希时**拒绝启动**，并在报错里给出生成命令。半配最容易让人以为「门已经锁上了」。

### Security

- 用户名错与口令错**返回同一句话**，且用位与 `&`（而非短路 `and`）强制两者都真实计算一次 scrypt —— 短路会让「用户名不存在」跳过 160 ms 的慢哈希，时间差可枚举用户名。
- 失败次数**不告诉调用方还剩几次**（那等于免费送一个爆破进度条）。
- 会话密钥默认从 token 派生 ⇒ **换 token 会让所有会话立即失效**；设 `AI_MEMORY_WEB_SECRET` 可解耦。注意反面：**改口令不会踢掉已登录会话**，因为签名密钥与口令无关。
- ⚠️ cookie 的 `Secure` 属性**不能无条件打开**：纯 HTTP 部署下加了 `Secure`，浏览器根本不存 Cookie，表现为「点登录没反应」而不是报错。故由 `AI_MEMORY_WEB_COOKIE_SECURE` 显式控制，默认关。

## [1.4.1] - 2026-10-20

> 主题：**把「歪」找出来** —— 图标歪的真正原因不是 SVG 画得不准，是 CSS 让 SVG 去参与行盒；顺带把 A 档缺的「悬停跟随」补回来。

### Fixed

- **全站图标统一下坠 2~4px**（主人反馈「还有把所有的图标纠正一下，怎么都有点歪歪的」）。根因在基础规则 `svg { display: inline-block; vertical-align: middle }`（`1-tokens.css`）：inline-block 的 SVG 会参与父级**行盒**，`body` 继承来的 `line-height: 23.2px`（1.6 × 14.5px）在图标上下各摊一半行距，而 inline-block 又按**基线**对齐 —— 于是每个图标都被往下顶。实测（svg 盒中心 − 父盒中心，headless Chromium）：`.nav-icon` 19×19 **+4.00**、`.cfg-icon` 17×17 **+3.50**、`.tab` 15×20 **+2.00**。改成 `display: block` 后四页实测全部归零（`[0,0,0,0]`），居中交给父级 grid/flex。
- **`play` 光学重心**：墨迹重心实测 10.90（包围盒中心 13.00），包围盒居中后肉眼仍偏左。按 Material `play_arrow` 的口径改成让重心说话，`translate` 由 `-1` → `+0.6`（重心落到 11.5）。其余 28 个图标经 480×480 alpha 加权重心复测，`alert / download / layers / inbox / key / trash / check` 这类**锥形字形**重心天然偏低 0.7~3.8 单位，是形状本身而不是画歪，维持包围盒居中（按重心居中会把 download 抬上去 3 个单位，反而更歪）；`chevron` 重心 11.73 已接近中心，不动。

### Added

- **侧栏「悬停跟随」玻璃透镜**（主人问「悬停跟随呢？」）—— `core/lens.js` + `.rail-lens` + `css/3-components.css §18b`。透镜是 `.sidebar` 的**兄弟**且 `z-index` 高一级，这样它的 `backdrop-filter` 采样到的是**侧栏的合成结果**（图标 / 指示条 / 文字都会被边圈弯折），做成子元素就只采到侧栏自己那层半透明底，折射等于没有。跟手用 GSAP `quickTo`（0.40s / power3）而非逐帧硬贴 —— 硬贴像鼠标拖了个色块。进场先 `gsap.set` 落位再淡入，避免从 (0,0) 飞过来；`rAF` 闸门合并高刷鼠标的重复事件；位置 `clamp` 在轨道与视口内。
- **`lg.js` 新增 `dressLens()`**，与 `dressPanel()` 分开。透镜压在 19px 图标上，沿用面板那套参数会把图标折成一团糊（实测 scale 15/22 时 `>` 和 `-` 完全认不出来）；尺寸由调用方量好传入，`r` 与 `.nav-item` 的 `--r-sm` 对齐。
- **选中态跟随**（主人追加：「这个 nav-item active 也跟随」）—— `core/lens.js` 加命中检测：透镜滑到哪一项，就给它挂 `.lens-hit`，与 `.nav-item.active` **共用同一条 CSS 规则**（`2-layout.css`），于是高亮本身跟着手走，不再是只有玻璃珠孤零零地滑。同时给 `.sidebar` 挂 `.has-hit`，让当前页把**填充**让出去、只留 accent 边框 —— 口径变成「填充 = 手在哪、边框 + 白色滑块 = 你在哪一页」，任一时刻只有一块填充，不会看成「两个都选中」；手一离开轨道 `.has-hit` 摘掉，当前页填充立刻回来。
  - 命中口径：纵向给 3px 容差（条目之间只有 3px 缝，严格按 rect 判定指针划过去会有一两帧落空，`.has-hit` 跟着闪）、横向直接用轨道宽度兜住（轨道 64px、条目 44px，两侧各 10px，贴边时严格判定也会落空）。实测扫过缝隙连采 6 帧 `has-hit` 全 `True`，不闪。
  - 只在命中索引变化时碰 DOM（每帧 `classList.remove` 会让 style 失效重算）。
- **玻璃尺寸贴合条**（主人：「玻璃大小要贴合 active」）—— 透镜从「浮在条目里的 38×38 珠子」改成**与 `.nav-item` 1:1 等大的玻璃片**（实测 44×43、圆角同为 `--r-sm` 8px），尺寸在运行时从第一个 `.nav-item` 量出来（`core/lens.js#fit()`），不写死：侧栏宽度响应式，写死会在抽屉/窄屏错位；`resize` 时重新量体裁衣并重算位移贴图。
  - **等大之后必须吸附**：条目高 43、间隙 3，若玻璃继续逐像素跟手，指针落在缝隙时玻璃一半压在选中项、一半压在空项上，而填充只出现在一侧 ⇒「玻璃和选中块错位」。改为命中哪项就整片贴到哪项，跨项靠 `quickTo` 的 0.4s 插值滑过去；指针落在轨道空白处（品牌区/底部）判为无命中、玻璃淡出，保证「玻璃 ≡ 填充」这条不变量。
  - 透镜拆成 **`.rail-lens`（外层：圆角 + `overflow:hidden` + 顶光伪元素）+ `.rail-lens-glass`（内层：真正的 `backdrop-filter`）** 两层。
- **`web_console.py` 静态资源补 `Cache-Control: no-cache`**（新增 `_NoCacheStatic(StaticFiles)`）。`StaticFiles` 默认只发 ETag / Last-Modified、**不发 Cache-Control**，浏览器于是对 `/assets` 走启发式缓存 —— 改了 js/css 还可能拿旧文件，界面上就是「新功能怎么没有？」。`no-cache` = 可存但每次回源验，没改就 304，性能零损失。`index.html` 原本就有 `no-store`，只有静态资源是漏的。

### Fixed

- **`prefers-reduced-motion` 下玻璃几乎不可见**（主人两次报「8890 怎么没有？」的真凶）。`gsap.quickTo(el, prop, {duration: 0})` **不会「立即到位」**：实测（`Emulation.setEmulatedMedia` 模拟 reduce）`opacity` 停在 **0.1**、`transform` 停在 `(10.1, 120.1)` —— 每帧只挪一小步，永远到不了终点。玻璃只有一成不透明度，看着就是「没有」。Windows 关掉「显示动画」就会走进这条分支，是最难在自己机器上复现的那种「你那儿没有」。修法：reduced 时**不创建 quickTo**，`put/fade` 退化成 `gsap.set` / 直接写 `style`（修后 reduce 与 default 的 `opacity`、`transform` 完全一致）。其余模块（`anim.js` / `flip.js` / `ThemeSwitch.js`）本来就用 `reduced()` 开关走静态赋值，没有这个问题。
- **玻璃改成「常显 + 回落当前页」**（主人：「玻璃大小要贴合 active」）—— 之前只在指针位于条目上时才淡入，打开页面不动鼠标就是「没有玻璃」。现在：`rest()` 把玻璃放到 `.nav-item.active` 上（首次挂载 `requestAnimationFrame` 落位；指针离开轨道、或落在品牌区/底部这类空白处，都回落到当前页）；`MutationObserver` 监听四个条目的 `class`，路由切页把 `.active` 挪走后玻璃跟着搬过去（不在悬停时响应，避免自己挂/摘 `.lens-hit` 造成回路）。于是玻璃永远贴着某一块填充，「玻璃在、填充不在」的错位不可能出现。
- **圆角外的深色楔子**：玻璃与条目等大后，右下角糊出一块黑三角。逐个排除（关位移 / 关滤镜 / 关伪元素 / 改 `border-radius`）定位到 `feDisplacementMap` —— Chromium **不把滤镜输出裁到 `border-radius`**，圆角外侧那几像素位移后采到的是盒子外的空 backdrop。三条措施：① 位移改**向内**采样（`inward`，凸透镜本来就是从内侧取放大样）；② 圆角弧段按 `1-2|nx·ny|` 平滑减幅（直边法线轴对齐 ⇒ 权重 1，圆角 45° ⇒ 0）；③ `scale` 收到 **2**（实测边界：2 干净、3 有淡痕、4 起明显）。另外把透镜拆成「外层圆角 + overflow 裁切 / 内层滤镜」两层兜住。
- **`will-change` 与 `backdrop-filter` 冲突**：`.rail-lens` 上原有的 `will-change: transform, opacity` 已移除 —— 带 `backdrop-filter` 的元素被提升成独立合成层后，Chromium 部分 GPU 路径会采到空 backdrop，玻璃只剩一层底色，看起来就是「透镜根本没出现」；`headless --disable-gpu` 复现不出来，真机才看得到。

### Tests

- 图标落位：四页 `.nav-icon` 的 svg 盒中心 − item 盒中心 = `[0,0,0,0]`；`.cfg-icon` / `.tab` 同步归零。A/B 复核：运行时注入旧规则 `display:inline-block` 立刻回到 `[4,4,4,4]`。
- 透镜几何：`lens` 与 `item` 的 rect **逐值相等**（`[10,120,44,43]` vs `[10,120,44,43]`，`d=[0,0]`）；命中第 1/2/4 项与浅色主题各测一次。
- 常显/回落：打开页面不碰鼠标 ⇒ 玻璃落在 `.active` 上（`[10,74]`、`aligned [0,0]`、`opacity 1`）；悬停第 3 项 ⇒ `[10,166]`；离开轨道 ⇒ 回到 `.active` `[10,74]`；点「配置」切页后 ⇒ `active=3`、玻璃搬到 `[10,212]`，四次 `aligned` 均为 `[0,0]`。
- **`prefers-reduced-motion: reduce`**（`Emulation.setEmulatedMedia`）：`opacity 1`、`transform matrix(1,0,0,1,10,120)`，与 default 完全一致 —— 修复前是 `opacity 0.1` / `10.1,120.1`。
- 位移贴图逐像素抽检（44×43）：四角 `128,128`（不偏移）、`edgeL 244 / edgeR 11 / edgeT 244 / edgeB 11`（向内）、中心与圆角弧段 `128`。
- 回归：四页 × 双主题整页截图无塌版；560 / 320 无横向溢出（`docScroll == vw`）；`console.error` 全程 `[]`；`tests/test_web.py` **83/83**。
- 选中态跟随：指第 2 项 ⇒ `hit=[F,T,F,F]`、第 1 项填充 `rgba(0,0,0,0)`（让位）、第 2 项 `rgba(223,228,231,.1)` + accent 边框；指当前页 ⇒ 同一项同时带 `.active` 与 `.lens-hit`、只有一块填充；离场后 `has-hit` 摘除、当前页填充恢复；浅色主题同套行为。

## [1.4.0] - 2026-10-20

> 主题：**开关从「近似」改成「照抄」** —— 日夜开关按 WPF 原文矢量 1:1 重做；玻璃 Dock 按主人指示撤除，液态玻璃整体转给侧栏（A 档：轨道原地不动，只换材质）。

### Changed

- **日夜开关整块重写为内联 SVG 矢量 1:1 移植**（`components/ThemeSwitch.js` + `css/3-components.css §16`）。1.3.0 那版是拿 CSS 圆/椭圆去「近似」原控件 —— 星星退化成圆点、云退化成椭圆、日月没有任何高光弧与陨石坑描边，主人判定「没做好」。这一版把 `ToggleButtonStyles.xaml` 原文取回来逐条复刻：11 颗 `starGeometry` 四角星（3/5/7px 三档）、两层云的贝塞尔原路径（`UniformToFill` 用 `getBBox()` 现场归一化）、三层光晕、日/月共用的月牙高光与暗角（线性渐变 stop 逐字对）、三颗陨石坑（`#66000000` / 0.6 描边）、护角描边（WPF 描边画在内侧 → 取中线 `-1.1 / 102.2×42.2 / r20.1`）。动效改由 **GSAP timeline 复刻 Storyboard**：滑块 `0→0.6s:66 → 1.5s:63`（有回弹）、星星 `-36→3→0`、光晕 `23/35/47→21/33/45`、云 `-6→4→0`（3.6s）、五颗星 1.3~3.6s 错峰三段脉冲；悬停自转 30° 用 `svgOrigin` 精确对齐 `RenderTransformOrigin="0.5,0.5"`。
- **`transform-origin` 修正**：`.tsw-box` 由 `0 50%` 改为 `0 0`。前者让 40 高的内容在缩放到 28.8 后仍以「未缩放的 20」为中线，整块比容器低 5.6px —— 这就是主人报的「有点歪」。实测：顶栏中心 31.00 / 按钮盒 30.49 / 内容实际中心 **36.09**，改后三者对齐。
- **玻璃 Dock 整块撤除**（主人指示）：删 `components/GlassDock.js`、`main.js` 注册、`Root.js` 顶栏节点、`css/3-components.css` 的 `.lg-*`、`css/8-responsive.css` 的 Dock 收口段。Dock 的三个动作一个没丢：命令面板与「刷新全部数据」面板本来就有，**「复制 MCP 端点」补进面板动作表**（面板 32 → 33 项）。

### Added

- **侧栏液态玻璃（A 档）**：`core/lg.js` 拆出 `mountFilter()` + 新增 `dressPanel()` —— 透镜是固定 36×36 写死尺寸，侧栏是 64×视口高、尺寸得运行时量（`ResizeObserver` + `resize` 防抖 180ms 重算贴图，同 id 只换 `feImage` 不重建节点，避免 resize 时闪一下）。新增 `.rail-glass-bg`（`.sidebar` 的**兄弟**、`z-index` 更低）在轨道那一列打一道单色柔光 —— 没有它，玻璃背后是纯色 `--bg`，折射根本没有对比度可折。`3-components.css §18` 负责半透明底（`--surface` 42%）、兜底磨砂、外侧分离阴影与右侧 1px 镜面边；CSS 里**不写** `url(#lg-panel)`（JS 追加，滤镜缺失时整条 `backdrop-filter` 会失效 ⇒ 侧栏不可见）。抽屉态（≤899）底放到 64% —— 那是全站唯一「内容真的从玻璃底下过」的场景。

### Fixed

- **GSAP `fill` 通道不一致**：补间写的是 inline style，而 `setStatic()` 写的是属性，导致属性值永远停在上一态（探针读属性与眼睛看到的会是两个颜色）。统一改走 `style.fill`。
- **首次切换不演动画**：`apply()` 里曾有「先 `gsap.set` 终态再起播」的 `_primed` 预置，等于把起点按到终点上。GSAP 起播时自己会读当前 inline 值，预置有害，已删。

### Tests

- 后端回归 **83 断言全绿**。
- **前端无头探针**（Chrome + 裸 CDP）：开关 `thumb` 0.45s 处 `x=65.87`（正在冲向 66 的回弹段）、`moon x=-0.928`、`stars y=2.92`、光晕在峰值 —— 与 XAML 关键帧时间点逐一吻合；四态（昼/夜 × 收窄/展开）截图核对；切到昼后 `thumb=4 / moon=34 / stars=-36 / c1=0.69 / c2=2.90`（云还在 3.6s 的落位段内）。侧栏：`.sidebar` 64×900、`backdrop-filter` 计算值含 `url("#lg-panel")`、`feDisplacementMap scale=20`、贴图 dataURL 4.4KB、`docScroll == vw`（无横向溢出）、820 宽抽屉态光晕层宽度自动归 0。`.lg-*` 计数 0，`#app` 0 页面错误。560/320 顶栏仍无横向溢出。

## [1.3.0] - 2026-10-20

> 主题：**顶栏重做一遍材质与手感** —— 液态玻璃 Dock + 命令面板、WPF 日夜开关、断点跨越 FLIP，顺带把「记忆类型」整段汉化、把 29 个图标的视觉重心校到同一个点上。**纯前端**，后端零改动。

### Added

- **液态玻璃快捷 Dock**（`components/GlassDock.js` + `core/lg.js` + `css/3-components.css §17`）：顶栏新增 3 个圆形按钮，悬停处浮出一块**真折射玻璃**透镜并跟手滑动。材质不是 CSS 造假：按 `liquid-glass.md` 的技术本质自建 —— 圆角矩形 SDF 求边圈法线 → Snell 近似的位移量编进 R/G 通道（128 = 不偏移）→ 吐成 dataURL 位移贴图 → `feDisplacementMap` 挂进 `backdrop-filter: blur(2px) saturate(1.55) url(#lg-refract)`。三条硬约束全部落到注释里：玻璃叠玻璃必须是**兄弟节点**（透镜 `pointer-events:none`）、贴图尺寸与元素盒子 1:1（尺寸由 `core/lg.js` 的 `LG` 常量单点写死）、**CSS 里不许硬写 `url(#id)`**（滤镜缺失会让整条 `backdrop-filter` 失效 ⇒ 元素不可见，故折射由 JS 在滤镜装好后再追加；不支持时退化为霜化模糊）。透镜内还有一颗跟指针走的镜面高光（`mix-blend-mode: plus-lighter`）+ 1px 锥形色散边。
- **三个新功能**（不是把已有导航项重排）：**命令面板**（`components/CommandPalette.js`，Ctrl/⌘+K 唤出，一个输入框同时检索 4 个页面 / 4 个动作 / 24 个 MCP 工具，↑↓ 选、Enter 执行、Esc 关）；**刷新全部数据**（健康 + 概览 + 更新日历 + 工具清单四条一起拉，严格超集于被它取代的「仅概览页刷新」）；**复制 MCP 端点**（`navigator.clipboard`，非安全上下文退回 `execCommand`）。
- **日夜主题开关**（`components/ThemeSwitch.js` + `css/3-components.css §16`）：移植 WPF 控件 `SunnyDesignor/WpfGorgeousThemeSwitch`（MIT）—— 100×40 胶囊天空（白天 `#4685C0` / 夜晚 `#171E33`）、金黄太阳滑出 / 带陨石坑的月亮滑入、11 颗星自 -36 升起且 5 颗错峰闪烁、两层云下沉、悬停时太阳自转 30° 且开关由「只露圆钮」展开成完整天空。取代原「浅色 / 跟随系统 / 深色」三按钮组；**三态里的「跟随系统」改为右键触发**（桌面天然的第二通道，不占视觉位）。原控件「非悬停收窄 + 内容负 margin 左推」的做法完整保留 —— 没有它，夜间收窄态窗口里只有空天空，月亮在 X=63 根本看不见。
- **断点跨越 FLIP 动画**（`core/flip.js`，落在概览页三组卡片）：落地《GSAP 断点 Flip 施工手册》。核心不是 `Flip.from` 而是**每 150ms 周期性预抓取旧布局** —— resize 回调里读到的 rect 已是新布局，用它当基线算出的位移恒为 0（手册 §5-1 的唯一正解）。动画期间 `absolute:true` 脱流、`Flip.from` 包进 rAF（Windows 拖动是模态循环）、播放中不抓基线、页面隐藏跳过、`prefers-reduced-motion` 整段不注册、卸载时 interval / mq 监听 / rAF / tween 全拆。附 `window.__amFlip` 计数钩子供无头探针断言。
- **记忆类型汉化**（`core/util.js` 新增 `TYPE_ZH / TIER_ZH / CONF_ZH / SCOPE_ZH / STATUS_ZH` + `typeZh()` 等）：概览页「记忆类型」卡由 `fact / project / … / workflow` 改为 **事实 / 项目 / 经验 / 流程 / 决策 / 情景 / 约束 / 偏好**，原文保留在行 `title` 上；记忆库右栏 NODE INFO 的类型 / 热度 / 状态 / 置信度同步汉化。表只作用于**展示层**，写回与过滤仍用原文枚举（中文串绝不能流进 `memory_write` 的 `mem_type`）。

### Changed

- **29 个图标的视觉重心统一**（`core/icons.js` 的 `OPTICAL` 表）：`grid` 是 3..21、`book` 只有 4..19、`play` 的三角形 7..19、`layers` 纵向只到 18 —— CSS 能居中的只有 24×24 的**盒子**，管不到盒子里图形的偏置，排成一列时重心并不共线。用 headless Chromium 逐个量 `getBBox()` 的中心，算出到 (12,12) 的偏移后给图形套 `translate`，14 个偏移 ≥0.25 单位的图标（book / alert / layers / hash / search / play / chevron / refresh / moon / copy / bolt / key / trash / download）就此对齐。复测 29/29 的包围盒中心 = (12.00, 12.00)。
- **顶栏「仅概览页可见」的刷新 tab 撤除**：Dock 的「刷新全部」是它的严格超集，两个刷新按钮并排只会让人犹豫。
- **`Root.theme(p)` 方法删除**：主题写入口收敛到 `<theme-switch>` 一处，避免第二个写 `themePref` 的地方与开关显示状态不一致。

### Tests

- 后端回归 **83 断言全绿**（`tests/test_web.py`，退出码 0）。
- **前端无头探针**（Chrome + 裸 CDP，标准库手写 WebSocket 客户端；本机装不了 playwright）：透镜 `backdrop-filter` 计算值含 `url("#lg-refract")`、跟手位移 43px→83px 且命中项 1→2、离场 `opacity:0`；开关收窄 30.2px / 展开 72px、点击后 `data-theme=light`；命令面板 32 项 → 输入 `memory` 过滤到 25 项且首项 `memory_archive`；断点 1440→880 逐帧采到 `transform: translate3d(80,446) → (8.18,221.58)` 的真实插值（动画计数 1，反向再 +1），`position` 终态回到 `static`；560 / 320 两档顶栏 `scrollWidth == clientWidth == innerWidth`（无横向溢出），`#app` 0 页面错误。

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
