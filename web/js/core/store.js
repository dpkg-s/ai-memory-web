import { reactive } from "../../vendor/vue.esm-browser.prod.js";
import { applyTheme } from "./theme.js";

/* ======================================================================
 * 5. 全局状态
 * ==================================================================== */
var S = reactive({
  ready: false,
  page: "dashboard",
  /* 页面切换方向：+1 = 沿 NAV 顺序往后（新页从下方进），-1 = 往回。
     由 hashchange 比较新旧页序号得出，供 §17c 的 .page-enter/leave 使用。
     同一页（例如只改了 ?tab=）不动方向，免得 keyframes 无谓抖动。 */
  pageDir: 1,
  /* 配置页页签切换方向：+1 = 沿 SETTINGS_TABS 顺序往后（新页签从**下方**浮入），
     -1 = 往回（从上方浮入）。语义与 pageDir 完全一致，只是作用域从整页缩到
     配置页的 cfg-body。由 SettingsPage 对 S.settingsTab 的 watch 单点算出
     —— pick / 深链 ?tab= / 键盘导航三条路径都会经过那个 watch。
     供 §17j 的 `.cfg-body > [data-cfg-pane]`（读 --cfg-dir）使用。 */
  settingsDir: 1,
  sidebarOpen: false,
  /* 2026-10-13：概览右栏「最近更新」的**收纳（折叠）功能已砍除** ——
     原 S.ovRail（折叠成 40px 竖条）+ `.grid.ov.rail-off` + `.ide-panel.collapsed`
     三者一并删除，右栏改为**恒常显**（面板本体与终端口径行保留）。 */
  /* 2026-10-13：VS Code 骨架的「编辑器标签条」与「底部面板」已整块摘除，
     连带删除 S.views / S.panelOpen / S.panelTab 三个纯 UI 偏好。 */
  themePref: (function () {
    try {
      return localStorage.getItem("am.theme") || "auto";
    } catch (e) {
      return "auto";
    }
  })(),
  theme: document.documentElement.getAttribute("data-theme") || "dark",
  authRequired: false,
  tokenInput: "",
  /* 账号登录（2026-10-21，方案 A）。弹框有两条通道：
     password = 账号密码 → 服务端下发 HttpOnly Cookie（JS 读不到）
     token    = 访问令牌 → 存 sessionStorage 并随 header 发（给脚本/临时排障用）
     两者由服务端 /api/session 的 login_enabled 决定是否可切换。 */
  authMode: "password",
  loginEnabled: false,
  loginUser: "",
  loginPassword: "",
  loginError: "",
  loginBusy: false,
  sessionUser: "",
  authVia: "none",
  /* 多用户（2026-10-22，控制台 v1.6.0）。服务端 /api/session 一次给全：
     role = admin / operator / viewer；canManage 只对 admin 为真。
     前端拿 role 只做**界面裁剪**（藏掉入口），真正的拦截在服务端 —— 
     藏 UI 不是权限，只是别让人点进一个必然 403 的页面。 */
  role: "",
  canManage: false,
  multiUser: false,

  about: { resolved: {}, app: {} },
  health: {
    ok: false,
    checking: true,
    error: null,
    tools_count: 0,
    latency_ms: null,
    server: null,
    protocol: null,
    endpoint: "",
  },
  tools: [],
  /* 工具功能分组的**组定义**（key/label/desc + 组序），由服务端下发
     （`/api/tools` 的 `groups`，源自 `web_console.py` 的 `TOOL_GROUPS`）。
     🔴 前端**不建分类表** —— 归属只能由服务端声明，否则会随工具数增长而失配。
     空数组 = 服务端还是旧版（没有 groups 字段）⇒ 左栏退化为单组平铺，
     不做假分组（见 `ConsolePage.groups`）。 */
  toolGroups: [],
  toolsLoading: false,
  toolsError: null,

  overview: null,
  overviewLoading: false,
  overviewError: null,
  /* 「最近更新」日历的**独立数据面**（2026-10-15，概览右栏改热力日历）。
     `/api/overview` 里那条 memory_recent 是 30 天 / 12 条口径，只够铺一两天，
     撑不起按月着色的日历；日历的数据改由后端按天聚合后单独下发
     （`GET /api/activity` ⇒ {days, total, today, counts, items}）。
     🔴 刻意**不**复用 S.overview.recent：两条数据线的到达顺序不确定，
     分开存才不会互相覆盖（并且 /api/overview 的那条仍按原样供其它口径使用）。 */
  recentActivity: null,
  recentLoading: false,
  recentError: null,

  console: {
    filter: "",
    attr: "all",
    collapsed: {},
    selected: null,
    args: {},
    running: false,
    result: null,
    error: null,
    elapsed: null,
    view: "rendered",
    /* 终端输出卡的两区块折叠态（2026-10-14 主人改定：**各自独立、允许全折**）：
       「结果并入终端输出」后，终端卡内分两区块 —— 日志流 + 结果，各带 caret。
       🔴 曾用 `fold` 三值枚举（none|log|result）实现「折一个自动展另一个」；
       主人 2026-10-14 判定「联动逻辑不对」⇒ 改回**两个独立 bool**：
       折日志不影响结果、折结果不影响日志，两边都折也合法
       （终端只剩两行标题，点卡头三角箭头 `expandAll` 一键全展）。 */
    foldLog: false,
    foldResult: false,
    /* 「单击上面恢复工具最高高度」（2026-10-14 方案 E）：执行后参数段会被收纳到
       30%，点一下参数卡即置位本标记 ⇒ 参数段回到内容高。换工具 / 再次执行时清零。 */
    paramOpen: false,
    history: [],
    logs: [],
    logFilter: "",
  },
  library: {
    mode: "browse",
    keyword: "",
    tag: "",
    tier: "",
    loading: false,
    error: null,
    items: [],
    searchRaw: "",
    searchItems: [],
    note: null,
    noteLoading: false,
  },
  settingsTab: "conn",
  thresholds: {
    loading: false,
    error: null,
    data: null,
    draft: {},
    saving: false,
    dirty: false,
    /* 写入 memory.toml 成功后的**一次性**高亮开关：true → 900ms 后回 false。
       不是「递增计数」也不是 `:key` 重建 —— 见 6-anim.css §17j ④ 的取舍说明
       （重建 .row2 会连带重置 8 个 input 的 DOM）。 */
    flash: false,
  },
  fns: { dirty: false, saved: null },
  /* 更新面（2026-10-15 建立；2026-10-16 扩为**双目标**：Web 控制台 + 核心 MCP）。
     数据源 `GET /api/update`，返回 `targets` 数组 —— 每项是一个目标的完整
     payload，**定位不到的目标也占位并带 error**，界面据此显式提示而不是静默少一张卡。
     🔴 白名单（哪些文件算「程序」）由**服务端**决定（web = UPDATE_WEB_PATHS，
     core = CORE_PROGRAM_FILES），前端不维护第二份清单 —— 否则每加一个运行时
     模块就要改两处，必然失配。这里只存服务端给的结果，不做任何 git 语义推断。 */
  update: {
    loading: false,
    restarting: false,
    error: null,
    targets: [],          // [{target, target_name, root, available, ...}]
    applying: {},         // target -> bool（该目标正在执行更新）
    result: {},           // target -> 最近一次 apply 的返回值
    reconnecting: false,  // 重启后轮询 /api/health 期间为 true
    seconds: 0,
    /* 进 web 时那次自动检测是否已发起（2026-10-19）。一次页面会话只联网一次，
       避免 mounted / 深链 / watch 多处调用各跑一遍 git fetch。 */
    autoStarted: false,
  },
  confirm: {
    open: false,
    title: "",
    body: "",
    phrase: "",
    typed: "",
    onOk: null,
    danger: false,
  },
  /* 命令面板（2026-10-20，玻璃 Dock 的第一个按钮 / Ctrl·Cmd+K 唤出）。
     只存「开着吗 + 当前输入 + 高亮项」，候选项由 CommandPalette 现算 ——
     候选项依赖 S.page / S.tools / S.theme，存快照必然会与它们脱节。 */
  palette: { open: false, q: "", idx: 0 },
  toasts: [],
});
S.theme = applyTheme(S.themePref);

function toast(kind, title, body, ms) {
  var id = Math.random().toString(36).slice(2);
  S.toasts.push({ id: id, kind: kind, title: title, body: body || "" });
  setTimeout(
    function () {
      dismiss(id);
    },
    ms || (kind === "err" ? 8000 : 4200),
  );
}
function dismiss(id) {
  var i = S.toasts.findIndex(function (t) {
    return t.id === id;
  });
  if (i >= 0) S.toasts.splice(i, 1);
}
function askConfirm(title, body, phrase, onOk, danger) {
  S.confirm = {
    open: true,
    title: title,
    body: body,
    phrase: phrase || "",
    typed: "",
    onOk: onOk,
    danger: !!danger,
  };
}
function closeConfirm() {
  S.confirm.open = false;
  S.confirm.onOk = null;
}

export { S, toast, dismiss, askConfirm, closeConfirm };
