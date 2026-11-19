import { api } from "../core/api.js";
import { go } from "../core/router.js";
import { S, toast } from "../core/store.js";
import { openNote } from "./library.js";

/* ======================================================================
 * 12. 日志（2026-11-05）
 *
 * 一条合并时间轴：左边「访问日志」（谁、从哪、用什么工具、动了什么），
 * 右边「FNS 同步日志」（什么时候、上传/修改/下载了哪条笔记）。
 *
 * 三条刻意的边界：
 * 1. **合并只在服务端做**（/api/logs 一次下发）。前端分两次拉会让两条流各自
 *    截断，拼起来中间是空的 —— 看起来像「那段时间什么都没发生」。
 * 2. **排序口径只有服务端一处**。前端只按天/按分钟**分组**，不重新排序。
 * 3. **FNS 无数据源不是错误**（没有事件文件 = 没启用 FNS 或卷没挂），
 *    界面显示成「尚未接入」，不当红错误处理。
 * ==================================================================== */

/* 静默刷新间隔：与访问控制页的 8 秒审计同步错开，避免两个页面同时打服务端；
   12 秒对「看日志」这个场景足够 —— 日志不是监控大盘，没人盯着等秒变。 */
var POLL_MS = 12000;

/* 一页多少条（2026-11-12 主人：「添加全局懒加载，还有访问日志的懒加载」）：
   原先是首屏一次 240 条 —— 90% 的访问是「进来瞄一眼最近发生了什么」，
   多出来的 180 条只是把首屏渲染和 FNS 事件文件的读取拖慢。
   现在首屏 60、每次续载 60，口径与服务端 limit(1..1000) 兼容。 */
var PAGE_SIZE = 60;

/* 事件去重键：服务端下发的 t 是 unix **秒**，同一秒里天然会有多条
   （一次工具调用往往同时产生「访问」与「同步」两条），所以键里必须带上
   source / action / 对象 —— 只用 t 去重会把同秒的合法事件吞掉。
   对象取 target / path / title 三者里第一个有值的：访问日志用 target，
   FNS 事件用 path（有的带 title），拼成同一个键才可比。 */
function evKey(e) {
  e = e || {};
  return [
    e.t,
    e.source,
    e.action,
    e.target || e.path || e.title || e.note || "",
  ].join("\u0001");
}

/* 首屏与续载共用的筛选参数：口径只在这一处拼，避免「加载更早」悄悄漏掉
   hide_self 或某个筛选，导致续上来的那半页与上半页不是同一个视图。 */
function queryParams() {
  var L = S.logs;
  var p = { source: L.source, hide_self: L.hideSelf ? "1" : "0" };
  if (L.akind) p.akind = L.akind;
  if (L.faction) p.faction = L.faction;
  return p;
}

/* 静默刷新时把新一页与既有数组拼起来（2026-11-12）。
   取舍说明（任务要求写清的一处）：静默轮询**永远只拉最新一页**（不带 before），
   它负责的是「上面那段有没有新事件」，不负责往下翻。所以：
   · 以服务端新一页为准（它是最新 60 条，口径权威）；
   · 再把旧数组里**比新一页最旧那条还早**、且新一页里没有的条目接回尾部 ——
     那就是用户自己按「加载更早」翻出来的历史，绝不能被一次后台轮询清掉。
   · 反过来，旧数组里与新一页**同一时间范围**的条目一律丢弃：服务端刚重算过，
     保留旧副本只会让「刷新后还挂着已被过滤掉的条目」这种怪事出现。
   代价：若用户翻过页后，服务端的过滤口径在下一轮偷偷变了（例如事件文件被轮转），
   已经取到手的更早历史仍会留在页面上，直到下一次非静默刷新。这是刻意的 ——
   日志是「看过的就是看过的」，凭空消失比多留几秒更让人怀疑数据丢了。 */
function mergeNewestPage(fresh, prev) {
  var list = (fresh || []).slice();
  if (!prev || !prev.length) return list;
  /* 新一页为空一般是筛选/口径刚变过，此时不能把旧历史接上（否则新旧口径混在一屏）。 */
  if (!list.length) return list;
  var oldest = Number(list[list.length - 1] && list[list.length - 1].t) || 0;
  if (!oldest) return list;
  var seen = {};
  for (var i = 0; i < list.length; i++) seen[evKey(list[i])] = 1;
  for (var j = 0; j < prev.length; j++) {
    var e = prev[j] || {};
    var t = Number(e.t) || 0;
    if (t >= oldest) continue; // 同段时间以服务端新一页为准
    if (seen[evKey(e)]) continue;
    list.push(e);
  }
  return list;
}

/* 当前「第一页」请求的 promise（2026-11-12）。
   为什么不放进 S.logs：store 只放界面要读的状态，promise 进去会被 Vue 包成响应式代理，
   徒增开销还会在 devtools 里刷一堆 setter。有它才能回答「现在这一页到底有没有在飞」——
   切换 hideSelf / 手动续载撞上一次刷新时，要等这页落地再发新请求，
   否则会被 loadLogs 里的 loading 闸静默吞掉（按钮变了、列表没变）。 */
var inflight = null;

/* 视图代数（2026-11-12）：每次非静默重取（刷新 / 切筛选 / 切 hideSelf）都 +1。
   为什么需要它：续载一页可能在飞的时候用户切换了口径 —— 那一页是按**旧口径**
   取回来的（旧 before、旧的 hide_self），落地后如果照旧追加，就会把旧视图的
   事件接进新视图的尾巴里，看起来像「切了开关还是混着隐藏事件」。
   代数不一致就整份丢弃：宁可就地少一页，也不能把两个口径混进同一份 events。 */
var viewGen = 0;

function loadLogs(opts) {
  var L = S.logs;
  if (L.loading) return inflight || Promise.resolve();
  var silent = !!(opts && opts.silent);
  L.loading = true;
  if (!silent) L.error = null;
  /* 口径换代在**发请求之前**发生：这一刻起，任何还在飞的「加载更早」都作废，
     它的结果不能落到新视图的数组里（见 loadMore 里的 myGen 判据）。 */
  if (!silent) viewGen += 1;
  var params = queryParams();
  params.limit = PAGE_SIZE;
  inflight = api
    .logs(params)
    .then(function (d) {
      var data = d || {};
      var fresh = data.events || [];
      /* 静默刷新只更新「第一页语境」，翻过的更早历史原样留着（见 mergeNewestPage）。 */
      L.events = silent ? mergeNewestPage(fresh, L.events) : fresh;
      L.counts = data.counts || { access: 0, fns: 0 };
      /* 自事件条数：服务端无论隐藏与否都会报，界面据此显示「已隐去/含自身同步 N 条」。
         老的响应没有这个字段时保持原值（别把已有的数字抹成 0）。 */
      if (data.counts && typeof data.counts.self === "number") L.selfCount = data.counts.self;
      L.total = typeof data.total === "number" ? data.total : L.events.length;
      /* has_more 只在「没翻过页」时跟随服务端。翻过页的人，续到哪了由 loadMore
         自己维护 —— 服务端的 has_more 是按**第一页**算的，拿它覆盖会让按钮
         每次静默刷新后被重新点亮，白点一轮才灭。判据用「合并后是否比新一页长」，
         而不是另存一个 paged 标志：多一个标志就多一处要同步的真值。 */
      /* ⚠️ 非静默（刷新 / 切筛选 / 切 hideSelf）是**从「翻过页的视图」切回第一页**，
         这时候即使服务端没回 has_more 也必须重算：留着上一次续到底的 false，
         会让「换了口径明明还有更早的事件，按钮却不出现」；留着旧的 true，
         就是一颗点了没反应的按钮。所以缺字段时按「这一页装没装满」保守兜底。
         （静默刷新缺字段时不动 hasMore —— 那是翻过页的人自己维护的值。） */
      var paged = L.events.length > fresh.length;
      if (typeof data.has_more === "boolean") {
        if (!silent || !paged) L.hasMore = data.has_more;
      } else if (!silent) {
        L.hasMore = fresh.length >= PAGE_SIZE;
      }
      L.fns = data.fns || { available: false, path: "", error: "" };
      /* 访问日志落点（2026-11-08）：日志进了记忆库当附件，界面要能看出
         「在哪、会不会跟着 FNS 同步」—— 否则「别的端看不到日志」无从小查。 */
      L.access = data.access || { path: "", in_vault: false, writable: true, note: "" };
      if (data.filters) L.filters = data.filters;
      if (data.stats) L.stats = data.stats;
      L.loading = false;
      L.loaded = true;
      L.error = null;
      /* 回到第一页 ⇒ 之前那次续载已经作废（它的 loadingMore 由这里统一收尾，
         不让作废的响应自己去改，免得把「新一代」正在续载的 true 抹成 false）。 */
      if (!silent) L.loadingMore = false;
      inflight = null;
    })
    .catch(function (e) {
      L.loading = false;
      L.error = e.message;
      inflight = null;
      if (e.status !== 401) toast("err", "读取日志失败", e.message);
    });
  return inflight;
}

/* 隐藏/显示「日志自身同步」（2026-11-12 主人：「web 里的这个能不能隐藏」）。
   切换即**非静默重取**：口径变了，已追加的更早历史也就不再是同一个视图的尾巴，
   继续留着会让「上半屏隐藏、下半屏还藏着旧口径的历史」同时存在 —— 直接回第一页。 */
function setHideSelf(v) {
  var L = S.logs;
  var on = v === undefined ? !L.hideSelf : !!v;
  if (L.hideSelf === on) return Promise.resolve();
  L.hideSelf = on;
  /* 正有一页在飞时先等它落地：直接调 loadLogs 会被 loading 闸挡回来，
     结果就是「按钮变了、列表还是旧口径」，比不动更让人困惑。 */
  return (inflight || Promise.resolve()).then(function () {
    return loadLogs();
  });
}

/* 续载更早一页（2026-11-12）。时间轴是**新→旧**，所以 before 取「当前最旧一条」的 t，
   服务端返回 t < before（严格更早），新结果接在数组**尾部**。
   防重入靠 loadingMore，不是靠 loading：续载期间上面那条静默轮询照常可以跑。 */
function loadMore() {
  var L = S.logs;
  if (L.loadingMore) return Promise.resolve();
  /* 首屏/刷新还在飞：等它落地再算 before —— 现在算出来的「最旧一条」是上一个视图的。 */
  if (L.loading) {
    return (inflight || Promise.resolve()).then(function () {
      return loadMore();
    });
  }
  /* 没有更多时绝不发请求：续到底以后 IO 哨兵会一直在视口里，
     少了这道闸就会每次滚动都打一次空请求。 */
  if (!L.hasMore) return Promise.resolve();
  var evs = L.events || [];
  var before = 0;
  for (var i = evs.length - 1; i >= 0; i--) {
    var t = Number(evs[i] && evs[i].t);
    if (isFinite(t) && t > 0) {
      before = t;
      break;
    }
  }
  /* 一条可用时间都没有 ⇒ 没法往回取，直接收起按钮，别拿 before=0 去要全量。 */
  if (!before) {
    L.hasMore = false;
    return Promise.resolve();
  }
  L.loadingMore = true;
  var myGen = viewGen;
  var params = queryParams();
  params.limit = PAGE_SIZE;
  params.before = before;
  return api
    .logs(params)
    .then(function (d) {
      /* 落地时口径已经换过（用户在等这一页时点了开关或换了筛选）⇒ 整份丢弃，
         也不碰 loadingMore：那面旗现在属于新一代，由它自己的请求收尾。 */
      if (myGen !== viewGen) return;
      var data = d || {};
      var add = data.events || [];
      if (add.length) {
        /* 去重后追加：服务端 t < before 是严格更早，理论上不会与现有条目重叠，
           但 before 那一秒若有第二条（服务端用 < 截掉了一半）就可能重来一条，
           按 evKey 过一遍比信任边界安全。 */
        var seen = {};
        var cur = L.events || [];
        for (var i = 0; i < cur.length; i++) seen[evKey(cur[i])] = 1;
        for (var j = 0; j < add.length; j++) {
          if (seen[evKey(add[j])]) continue;
          seen[evKey(add[j])] = 1;
          cur.push(add[j]);
        }
        L.events = cur;
      }
      /* 服务端没给 has_more 时按「这一页没满 ⇒ 到底了」保守收尾，
         避免老服务端下按钮永远点不完。 */
      L.hasMore =
        typeof data.has_more === "boolean" ? data.has_more : add.length >= PAGE_SIZE;
      L.loadingMore = false;
    })
    .catch(function (e) {
      if (myGen !== viewGen) return;
      L.loadingMore = false;
      if (e.status !== 401) toast("err", "加载更早日志失败", e.message);
    });
}

/* 来源 / 类型 / 动作筛选：改状态 → 立刻重取。
   三个 setter 分开写而不是一个通用 set(key, val)：模板里绑的是具体动作，
   通用 setter 会让「谁改了 source」变得不可 grep。 */
function setSource(v) {
  S.logs.source = v === "access" || v === "fns" ? v : "all";
  return loadLogs();
}
function setAccessKind(k) {
  S.logs.akind = S.logs.akind === k ? "" : k || "";
  return loadLogs();
}
function setSyncAction(a) {
  S.logs.faction = S.logs.faction === a ? "" : a || "";
  return loadLogs();
}

function stamp() {
  var d = new Date();
  var p = function (n) {
    return (n < 10 ? "0" : "") + n;
  };
  return (
    d.getFullYear() +
    p(d.getMonth() + 1) +
    p(d.getDate()) +
    "-" +
    p(d.getHours()) +
    p(d.getMinutes()) +
    p(d.getSeconds())
  );
}

function saveBlob(blob, name) {
  var url = URL.createObjectURL(blob);
  var a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  /* 立刻 revoke 会让部分浏览器在下载真正开始前就丢掉 blob（Safari 尤甚），
     给一拍再释放。 */
  setTimeout(function () {
    URL.revokeObjectURL(url);
  }, 1500);
}

function exportLogs(fmt) {
  var L = S.logs;
  if (L.exporting) return;
  var type = fmt === "json" ? "json" : "csv";
  L.exporting = true;
  var params = { format: type, source: L.source };
  /* 导出必须带上同一个 hide_self 口径：导出的东西要和屏幕上看到的一致，
     否则「界面上藏了自身同步、导出的 CSV 里又冒出来」，主人核对时会以为漏了数据。
     （服务端默认也是 1，这里显式给，免得以后服务端默认值一改就静默错位。） */
  params.hide_self = L.hideSelf ? "1" : "0";
  if (L.akind) params.akind = L.akind;
  if (L.faction) params.faction = L.faction;
  api
    .logsExport(params)
    .then(function (blob) {
      saveBlob(blob, "ai-memory-logs-" + stamp() + "." + type);
      L.exporting = false;
      toast("ok", "已导出", type === "csv" ? "CSV（Excel 可直接打开）" : "JSON");
    })
    .catch(function (e) {
      L.exporting = false;
      if (e.status !== 401) toast("err", "导出失败", e.message);
    });
}

/* 点击事件卡 → 打开对应笔记。
   为什么跳回记忆库页而不是在本页开抽屉：阅读器只有一份（LibraryPage 的
   中间栏 + 节点信息），在日志页再实现一个「只读预览」就会出现两套渲染与
   两套「打开下一条」的语义。跳页 + 复用同一个阅读器，行为与点列表完全一致。 */
function openNoteAt(title) {
  var t = String(title || "").trim();
  if (!t) return;
  go("library");
  openNote(t);
}

var watchTimer = 0;

/* 静默轮询：只在页面可见时跑（切到后台标签页时浏览器本来就会节流定时器，
   这里显式判一下，免得回来时补一串过期请求）。 */
function startLogsWatch() {
  stopLogsWatch();
  watchTimer = setInterval(function () {
    if (document.visibilityState !== "visible") return;
    if (S.page !== "logs") return;
    loadLogs({ silent: true });
  }, POLL_MS);
}
function stopLogsWatch() {
  if (watchTimer) {
    clearInterval(watchTimer);
    watchTimer = 0;
  }
}

export {
  loadLogs,
  loadMore,
  setHideSelf,
  setSource,
  setAccessKind,
  setSyncAction,
  exportLogs,
  openNoteAt,
  startLogsWatch,
  stopLogsWatch,
};
