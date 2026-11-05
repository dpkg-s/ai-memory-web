import { api } from "../core/api.js";
import { S, toast } from "../core/store.js";
import { parseSearch, tryJson } from "../core/util.js";

/* ======================================================================
 * 10. 记忆库
 * ==================================================================== */
/* 每页条数（2026-10-29）。40 的取法基于实测：本库 545 条（2026-10-29 实测），
   40 条一包的 JSON 约 23KB，横向够铺 1080p 一屏半，竖向上滚一次就补一页。
   再大（如 100 条）首屏字节翻倍却换不到可见收益；再小则滚两下就要请求。
   改这个值只影响「一次要多少条」，偏移量由 items.length 自动接续
   （见 core/store.js 的 library 注释）。 */
var PAGE_SIZE = 40;

/* 列举记忆（分页）。`reset=true` = 从头要第一页（切标签 / 切热度 / 点浏览）；
   `reset=false` = 续载下一页（滚动到底触发）。
   🔴 回到 Promise：`openTag` 要靠它拿到真实命中数再提示，不能 fire-and-forget。 */
function browseLibrary() {
  S.library.mode = "browse";
  return fetchLibraryPage(true);
}
function loadMoreLibrary() {
  return fetchLibraryPage(false);
}
function fetchLibraryPage(reset) {
  var L = S.library;
  /* 并发闸门：IO 在滚动时会连发多次，重复请求会让同一页插两遍。
     首屏加载与续载互斥 —— 两个开关任一为真都不许再进。 */
  if (L.loading || L.loadingMore) return Promise.resolve();
  if (!reset && !L.hasMore) return Promise.resolve();
  var offset = reset ? 0 : L.items.length;
  if (reset) {
    L.loading = true;
    L.error = null;
  } else {
    L.loadingMore = true;
  }
  var qs = "?offset=" + offset + "&limit=" + PAGE_SIZE;
  if (L.tag) qs += "&tag=" + encodeURIComponent(L.tag);
  if (L.tier) qs += "&tier=" + encodeURIComponent(L.tier);
  /* 排序（2026-11-05）：必须随每页请求一起发 —— 服务端按同一口径排序后
     再切片，续载的那一页才接得上；只在首屏排一次会让后面的页原地错位。 */
  if (L.sort) {
    qs += "&sort=" + encodeURIComponent(L.sort);
    if (L.order) qs += "&order=" + encodeURIComponent(L.order);
  }
  return api
    .get("/api/library" + qs)
    .then(function (d) {
      var items = (d && d.items) || [];
      L.items = reset ? items : L.items.concat(items);
      L.hidden = (d && d.hidden) || 0;
      L.count = (d && d.count) || L.items.length;
      /* 空页一律判「没有更多」：服务端 count 与 entries 万一不一致
         （并发写入、权级过滤），据此兜底是为了不让人滚到底后无限空转请求。 */
      L.hasMore = items.length > 0 && L.items.length < L.count;
      L.loading = false;
      L.loadingMore = false;
    })
    .catch(function (e) {
      L.loading = false;
      L.loadingMore = false;
      L.error = e.message;
      if (e.status !== 401)
        toast("err", reset ? "列举失败" : "加载更多失败", e.message);
    });
}
function searchLibrary() {
  var L = S.library;
  if (!L.keyword.trim()) {
    L.mode = "browse";
    return browseLibrary();
  }
  L.mode = "search";
  /* 搜索面**不分页**：`memory_search` 没有 offset，服务端只回前 N 条，
     伪续载只会重复同一批。故显式关掉续载闸门，免得底部哨兵误触。 */
  L.hasMore = false;
  L.loadingMore = false;
  L.loading = true;
  L.error = null;
  var args = { keyword: L.keyword.trim(), limit: 40 };
  if (L.tag) args.tag = L.tag;
  api
    .post("/api/call", { tool: "memory_search", arguments: args })
    .then(function (d) {
      L.searchRaw = d.text || "";
      L.searchItems = parseSearch(L.searchRaw);
      L.loading = false;
    })
    .catch(function (e) {
      L.loading = false;
      L.error = e.message;
      if (e.status !== 401) toast("err", "搜索失败", e.message);
    });
}
function openNote(title, maxChars) {
  var L = S.library;
  L.noteLoading = true;
  L.note = { title: title, body: "", meta: {} };
  api
    .post("/api/call", {
      tool: "memory_read",
      arguments: {
        title: title,
        max_chars: maxChars || 20000,
        output_format: "json",
      },
    })
    .then(function (d) {
      var j = tryJson(d.text);
      L.noteLoading = false;
      if (j && j.found)
        L.note = {
          title: j.title,
          path: j.path,
          meta: j.meta || {},
          body: j.body || "",
          truncated: j.truncated,
          total_chars: j.total_chars,
        };
      else
        L.note = {
          title: title,
          meta: {},
          body: d.text || "（未找到）",
          notFound: true,
        };
    })
    .catch(function (e) {
      L.noteLoading = false;
      L.error = e.message;
      if (e.status !== 401) toast("err", "读取失败", e.message);
    });
}
function onMdClick(ev) {
  var el = ev.target.closest ? ev.target.closest(".wikilink") : null;
  if (!el) return;
  ev.preventDefault();
  openNote(el.getAttribute("data-title"));
}

/* 切换「全部条目」的排序（2026-11-05）。
   选型是「字段 | 方向」两项而不是一长串预设组合：主人要的是排序方式，
   不是十几个「标题 A→Z / 标题 Z→A / 创建新→旧 …」的选项墙；
   两项各自自由组合，也省掉「某个预设没实现」这种半成品状态。 */
function setLibrarySort(sort, order) {
  var L = S.library;
  L.sort = sort || "";
  L.order = order || "";
  if (L.mode !== "browse") L.mode = "browse";
  L.keyword = "";
  return browseLibrary();
}

export {
  browseLibrary,
  loadMoreLibrary,
  searchLibrary,
  openNote,
  onMdClick,
  setLibrarySort,
};
