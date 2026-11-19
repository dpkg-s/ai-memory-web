import { createApp, defineAsyncComponent, h } from "../vendor/vue.esm-browser.prod.js";
import { AnimatedNumber } from "./components/AnimatedNumber.js";
import { CommandPalette } from "./components/CommandPalette.js";
import { DistributionBars } from "./components/DistributionBars.js";
import { JsonTree } from "./components/JsonTree.js";
import { MarkdownBox } from "./components/MarkdownBox.js";
import { PageSkeleton } from "./components/PageSkeleton.js";
import { ThemeSwitch } from "./components/ThemeSwitch.js";
import { XBanner } from "./components/XBanner.js";
import { XCard } from "./components/XCard.js";
import { XEmpty } from "./components/XEmpty.js";
import { XField } from "./components/XField.js";
import { XKv } from "./components/XKv.js";
import { XKvRow } from "./components/XKvRow.js";
import { XListItem } from "./components/XListItem.js";
import { XPill } from "./components/XPill.js";
import { XSkel } from "./components/XSkel.js";
import { XStat } from "./components/XStat.js";
import { loadHealth, loadOverview, loadTools } from "./core/data.js";
import { svg } from "./core/icons.js";
import { go, readHash } from "./core/router.js";
import { fmtBytes, fmtNum, kindZh, mdRender, relTime, shortDesc, toolZhDesc, toolZhName } from "./core/util.js";
import { runTool, selectTool } from "./features/console.js";
import { browseLibrary, openNote, searchLibrary } from "./features/library.js";
import { Root } from "./views/Root.js";


/* ======================================================================
 * 视图懒加载（2026-11-05）
 * ----------------------------------------------------------------------
 * 为什么改：6 个视图的源码体量是 AccessPage 61 / SettingsPage 43 /
 * Dashboard 31 / ConsolePage 30 / LibraryPage 18 / LogsPage 15 KB，合计近
 * 200 KB，而任意时刻首屏只显示其中**一页**。它们原先是 main.js 的顶层同步
 * import ⇒ 全串在一张 import 图里，浏览器必须把最慢的那份也下载、
 * 解析、编译完模板，才执行整棵模块树。等于打开概览页要为「配置 / 访问控制」
 * 付两次费：一次是首屏白屏，一次是每次刷新的缓存校验。
 *
 * 现在分两层：
 *   · 壳层（Root / 侧栏 / 顶栏 / 命令面板 / 主题）**继续同步**——
 *     壳先出来这一条不能赌。壳也异步的话首帧就只剩一个空 <div>，
 *     index.html 那 4 秒兜底会把它判成「前端没启动」，用户看到的是
 *     「前端未能启动」而不是一个漂亮的骨架。
 *   · 视图用 defineAsyncComponent + 动态 import()，一页一个独立请求；
 *     mount 之后再空闲预取，切页时模块已在模块表里，基本无感。
 *
 * ⚠️ 三个必须守住的约束（踩一条这套改造就白做）：
 *  ① 动态 import 的路径必须相对 **main.js（本文件）** 写，且与原来的静态
 *     import 完全同串："./views/Dashboard.js"。写成别的相对深度不是「找不到」
 *     那么友好 —— 某些静态服务器会把 404 兜成 index.html，浏览器拿 HTML 当
 *     ES 模块解析，报的是一个跟路径毫无关系的 SyntaxError。
 *  ② 「别处又静态 import 了 views/*.js」会让主包把该视图重新拖回同步图，
 *     懒加载当场失效，而且**看起来一切正常**（Network 里多一个预加载请求而已）。
 *     2026-11-05 已 grep 核实：全仓只有本文件的 VIEWS 表提到 views/，Root.js
 *     也只被本文件引用。以后若要「features 反向引用某个视图」，请用动态 import。
 *  ③ 加载失败必须落到可见的地方：errorComponent 给「失败 + 重试」，
 *     同时写 window.__amError（index.html 的兜底读它）—— 不能只剩一个空 <main>。
 * ==================================================================== */

/* 视图清单：id（= 全局组件名的一段） / 中文名 / 骨架规格 / 加载器，一张表管到底。
   为什么集中成表而不是六份 defineAsyncComponent 各写一遍：
   懒加载的路径、骨架形状、错误页文案在**两个**调用点要一致 ——
   defineAsyncComponent 与空闲预取。分开写就是「改了一处忘另一处」的老剧本。
   数组顺序沿用侧栏导航顺序，预取也照这个顺序排队。 */
var VIEWS = [
  {
    id: "dashboard",
    label: "概览",
    /* 概览：4 块统计卡 + 两栏（左动态 / 右分布）。 */
    skel: { stats: 4, rows: 5, label: "概览加载中" },
    load: function () {
      return import("./views/Dashboard.js").then(function (m) {
        return m.Dashboard;
      });
    },
  },
  {
    id: "console",
    label: "调试台",
    /* 调试台没有统计卡行，是三栏工作面，骨架用单栏长卡近似。 */
    skel: { stats: 0, rows: 8, split: false, label: "调试台加载中" },
    load: function () {
      return import("./views/ConsolePage.js").then(function (m) {
        return m.ConsolePage;
      });
    },
  },
  {
    id: "library",
    label: "记忆库",
    skel: { stats: 0, rows: 8, label: "记忆库加载中" },
    load: function () {
      return import("./views/LibraryPage.js").then(function (m) {
        return m.LibraryPage;
      });
    },
  },
  {
    id: "logs",
    label: "日志",
    skel: { stats: 0, rows: 8, label: "日志加载中" },
    load: function () {
      return import("./views/LogsPage.js").then(function (m) {
        return m.LogsPage;
      });
    },
  },
  {
    id: "access",
    label: "访问控制",
    skel: { stats: 4, rows: 5, label: "访问控制加载中" },
    load: function () {
      return import("./views/AccessPage.js").then(function (m) {
        return m.AccessPage;
      });
    },
  },
  {
    id: "settings",
    label: "配置",
    skel: { stats: 0, rows: 7, label: "配置加载中" },
    load: function () {
      return import("./views/SettingsPage.js").then(function (m) {
        return m.SettingsPage;
      });
    },
  },
];

var VIEW_BY_ID = {};
VIEWS.forEach(function (v) {
  VIEW_BY_ID[v.id] = v;
});

/* 骨架工厂：loadingComponent 是 Vue 自己 createVNode 出来的，拿不到任何 props，
   所以每个视图用闭包捏一份「带着自己那套规格」的小组件。
   （直接 h(PageSkeleton, spec) 当 loadingComponent 是不行的 —— Vue 会把它当
   组件类型去解析，传 vnode 进去只会得到一句空的渲染。） */
function skeletonFor(spec) {
  return {
    name: "page-skeleton",
    render: function () {
      return h(PageSkeleton, spec);
    },
  };
}

/* 错误页（每视图一份闭包，只为把「哪一页失败了」写进徽标 —— 六个视图共用
   一个错误页时，用户看到「页面加载失败」还得自己猜是哪页）。
   为什么不接 Vue 自带的重试钩子：本仓的 vue 构建只把 { error } 喂给
   errorComponent（源码里是 `createVNode(errorComponent, { error })`，没有
   retry prop）。而 onError 里那个 retry 会让 async 组件**一直停在 pending**
   —— 界面就是骨架永驻，用户连「出错了」都看不到，正是我们要避免的静默空屏。
   所以：瞬时失败在 onError 里自动重试两次，仍失败才 fail() 落到这里；
   这里的「重试」走整页 reload（失败本来就意味着「这个文件没拿到」，
   刷新让浏览器重新请求一次，是最可靠的恢复路径）。 */
function errorFor(label) {
  return {
    name: "view-load-error",
    props: { error: { type: [Object, String], default: null } },
    data: function () {
      return { pageLabel: label };
    },
    computed: {
      msg: function () {
        var e = this.error;
        return (e && (e.message || String(e))) || "未知错误";
      },
    },
    methods: {
      retry: function () {
        location.reload();
      },
    },
    template:
      '<div class="page" role="alert">' +
      '  <div class="card">' +
      '    <div class="card-head"><h3>页面加载失败</h3>' +
      '      <span class="spacer"></span>' +
      '      <x-pill kind="err">{{ pageLabel }}</x-pill></div>' +
      '    <div class="card-body">' +
      '      <div class="small mono">{{ msg }}</div>' +
      '      <div class="small faint mt">视图片段没能取到。常见原因：静态文件缺失、' +
      "        服务端把该路径兜成了 index.html，或网络中断。</div>" +
      '      <div class="mt"><button class="btn btn-primary" @click="retry">重试</button></div>' +
      "    </div>" +
      "  </div>" +
      "</div>",
  };
}

/* 一个视图的 async 组件定义。组件名（全局注册名）仍然在下面的注册表里给，
   与改造前逐字一致 ⇒ Root.js 的模板一个字都不用动。 */
function lazyView(id) {
  var view = VIEW_BY_ID[id];
  return defineAsyncComponent({
    loader: view.load,
    /* delay 120ms：本地 / 局域网下模块往往在 120ms 内就到齐了，
       立刻闪一下骨架反而像「抖了一下」；超过 120ms 才说明真在等网络，
       这时骨架比空白诚实。 */
    delay: 120,
    loadingComponent: skeletonFor(view.skel),
    errorComponent: errorFor(view.label),
    onError: function (err, retry, fail, attempts) {
      /* 瞬时失败自愈：模块请求偶发超时 / 连接被掐时先自动重试两次
         （400ms、800ms 退避），用户根本看不到错误页。
         SyntaxError 属于「文件本身有问题」（最典型的是路径写错、服务器返回了
         HTML），重试一百次也一样，直接失败，别让骨架在那儿空转。 */
      if (!(err instanceof SyntaxError) && attempts <= 2) {
        setTimeout(function () {
          retry();
        }, 400 * attempts);
        return;
      }
      /* 落进 index.html 的兜底视野（它读 window.__amError）。
         #app 非空时兜底不会接管页面，但排障时这一行是唯一还留得住的线索。 */
      window.__amError =
        "视图 " + view.id + " 加载失败：" + ((err && err.message) || err);
      console.error("[view]", view.id, err);
      fail(err);
    },
  });
}

/* 原 `if (!window.Vue) { … return; }` 守卫已移除：ESM 模块顶层不允许 return。
   Vue 缺失时浏览器会直接报模块加载失败，交由 index.html 的 4 秒兜底提示呈现。 */
var app = createApp(Root);
Object.assign(app.config.globalProperties, {
  svg: svg,
  fmtNum: fmtNum,
  fmtBytes: fmtBytes,
  relTime: relTime,
  short: shortDesc,
  toolZhName: toolZhName,
  toolZhDesc: toolZhDesc,
  kindZh: kindZh,
  md: mdRender,
  go: go,
  openNote: openNote,
  browseLibrary: browseLibrary,
  searchLibrary: searchLibrary,
  selectTool: selectTool,
  runTool: runTool,
  loadHealth: loadHealth,
  loadTools: loadTools,
  loadOverview: loadOverview,
});

[
  ["animated-number", AnimatedNumber],
  ["markdown-box", MarkdownBox],
  ["json-tree", JsonTree],
  ["distribution-bars", DistributionBars],
  ["x-card", XCard],
  ["x-kv", XKv],
  ["x-kv-row", XKvRow],
  ["x-field", XField],
  ["x-empty", XEmpty],
  ["x-pill", XPill],
  ["x-skel", XSkel],
  ["x-banner", XBanner],
  ["x-stat", XStat],
  ["x-list-item", XListItem],
  ["theme-switch", ThemeSwitch],
  ["command-palette", CommandPalette],
  /* 视图：注册名与改造前完全一致，只是值是 async 组件（首帧只解析当前页）。 */
  ["dashboard", lazyView("dashboard")],
  ["console-page", lazyView("console")],
  ["library-page", lazyView("library")],
  ["logs-page", lazyView("logs")],
  ["access-page", lazyView("access")],
  ["settings-page", lazyView("settings")],
].forEach(function (c) {
  app.component(c[0], c[1]);
});

app.mount("#app");

/* 空闲预取（挂载之后立刻排队）。
   目的：首屏只为**当前页**付下载钱，其余 5 页趁浏览器空闲逐个拉回来，
   等用户点导航时模块已进模块表 ⇒ 同步命中，切页感觉不到等待。

   三条纪律：
   ① 一次空闲只取一个：并发 5 个请求会跟当前页抢连接、抢带宽，
      本该快的首屏反而更慢（优化不能反客为主）。
   ② 用 requestIdleCallback，但必须带 timeout 兜底（Safari 没有这个 API 就退化
      成 setTimeout）—— 否则标签页一直忙时永远轮不到预取。
   ③ 预取失败**静默吞掉**：它只是优化，不是功能。漏出去会变成
      unhandledrejection，把 index.html 的 window.__amError 写脏，
      4 秒兜底就会对着一个完全正常的页面报「前端未能启动」。 */
function prefetchViews(skipId) {
  var queue = VIEWS.filter(function (v) {
    return v.id !== skipId;
  });
  var i = 0;
  var idle = window.requestIdleCallback;
  function tick() {
    if (i >= queue.length) return;
    var view = queue[i++];
    var p = null;
    try {
      p = view.load();
    } catch (e) {
      /* 动态 import 的同步异常（极少见）同样不许漏出去 */
      p = null;
    }
    if (p && p.catch) {
      p.catch(function () {
        /* 静默：见纪律③ */
      });
    }
    schedule();
  }
  function schedule() {
    if (typeof idle === "function") idle(tick, { timeout: 2000 });
    else setTimeout(tick, 300);
  }
  schedule();
}

/* 起始页（可能来自 #hash 深链）由 Root 的 mounted 再确认一次，这里只用于
   跳过「已经在加载的那一页」—— 重复调一次虽然命中的是同一个模块请求，
   但会白占一个空闲时隙，把它推到队尾就更好了。 */
prefetchViews(readHash());


export { app };
