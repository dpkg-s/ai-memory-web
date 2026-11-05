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

function loadLogs(opts) {
  var L = S.logs;
  if (L.loading) return Promise.resolve();
  var silent = !!(opts && opts.silent);
  L.loading = true;
  if (!silent) L.error = null;
  var params = { limit: 240, source: L.source };
  if (L.akind) params.akind = L.akind;
  if (L.faction) params.faction = L.faction;
  return api
    .logs(params)
    .then(function (d) {
      var data = d || {};
      L.events = data.events || [];
      L.counts = data.counts || { access: 0, fns: 0 };
      L.total = typeof data.total === "number" ? data.total : L.events.length;
      L.fns = data.fns || { available: false, path: "", error: "" };
      if (data.filters) L.filters = data.filters;
      if (data.stats) L.stats = data.stats;
      L.loading = false;
      L.loaded = true;
      L.error = null;
    })
    .catch(function (e) {
      L.loading = false;
      L.error = e.message;
      if (e.status !== 401) toast("err", "读取日志失败", e.message);
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
  setSource,
  setAccessKind,
  setSyncAction,
  exportLogs,
  openNoteAt,
  startLogsWatch,
  stopLogsWatch,
};
