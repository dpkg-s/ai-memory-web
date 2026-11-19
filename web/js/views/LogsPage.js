import { S } from "../core/store.js";
import { AUDIT_ACTION_ZH, SYNC_ACTION_ZH, SYNC_KIND_ZH, fmtBytes } from "../core/util.js";
import {
  exportLogs,
  loadLogs,
  loadMore,
  openNoteAt,
  setAccessKind,
  setHideSelf,
  setSource,
  setSyncAction,
  startLogsWatch,
  stopLogsWatch,
} from "../features/logs.js";

/* ======================================================================
 * 18. 日志页（2026-11-05，主人：「添加新页面日志」）
 *
 * 形态（主人指定）：**左右两个模块 + 共用一条时间轴**。
 *   · 左：访问日志（时间 / IP / 账号 › 令牌 / 工具 / 动作 / 对象）
 *   · 右：FNS 同步日志（时间 / 上传·修改·下载 / 哪条笔记）
 *   · 中：一条竖轴，按「天 → 分钟」给刻度，两侧事件对齐在同一行。
 *
 * 为什么不是「两张各自滚动的列表」：主人在意的正是「这一刻访问与同步同时
 * 发生了什么」。两条独立列表不在同一坐标系里，看一眼要自己拿时间戳对齐，
 * 那就等于把「共用时间轴」这件事又丢回给人来做。
 *
 * ⚠️ 分组只按**分钟**（不是秒）：同一秒里两三条事件挤在同一刻度上，
 * 秒级刻度会让每一行都比上一行低半厘米，读起来是锯齿而不是轴。
 * ==================================================================== */

function pad2(n) {
  return (n < 10 ? "0" : "") + n;
}
function tsOf(t) {
  /* 服务端统一给 unix 秒（FNS 事件的毫秒已在 web_synclog 归一）。 */
  var n = Number(t);
  if (!isFinite(n) || n <= 0) return null;
  return new Date(n * 1000);
}
function fmtHm(t) {
  var d = tsOf(t);
  if (!d) return "—";
  return pad2(d.getHours()) + ":" + pad2(d.getMinutes());
}
function fmtDay(t) {
  var d = tsOf(t);
  if (!d) return "未知日期";
  return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
}
function fmtFull(t) {
  var d = tsOf(t);
  if (!d) return "";
  return (
    fmtDay(t) +
    " " +
    pad2(d.getHours()) +
    ":" +
    pad2(d.getMinutes()) +
    ":" +
    pad2(d.getSeconds())
  );
}

var LogsPage = {
  data: function () {
    return { S: S };
  },
  /* 续载哨兵（2026-11-12 主人：「添加全局懒加载，还有访问日志的懒加载」）：
     · mounted 装 IntersectionObserver，unmounted 拆掉；
     · ⚠️ 这里**哨兵是常驻元素**（不带 v-if），所以 $refs 一定取得到 ——
       LibraryPage 当初放弃 IO 的坑是「`v-if` 哨兵取不到 ref」，不是 IO 本身不好；
     · 本页也没有内滚容器（`.lg-card` 是 overflow:hidden、`.lg-body` 不滚，
       真正滚动的是文档），祖先不会把哨兵裁在自己的可视区外 ⇒ 默认 root（视口）正确。
       真要换成卡内滚动，只要把 root 指过去即可，判据不用改。 */
  mounted: function () {
    if (!this.L.loaded) loadLogs();
    startLogsWatch();
    this.setupMoreWatch();
  },
  unmounted: function () {
    stopLogsWatch();
    this.teardownMoreWatch();
  },
  computed: {
    L: function () {
      return S.logs;
    },
    /* 分组：天 → 分钟。数据已是服务端排好的新→旧，这里**只分组不排序**。 */
    timeline: function () {
      var evs = this.L.events || [];
      var days = [];
      var dayIdx = {};
      for (var i = 0; i < evs.length; i++) {
        var e = evs[i] || {};
        var dayKey = fmtDay(e.t);
        var hm = fmtHm(e.t);
        var day = dayIdx[dayKey];
        if (!day) {
          day = { key: dayKey, day: dayKey, count: 0, rows: [], rowIdx: {} };
          dayIdx[dayKey] = day;
          days.push(day);
        }
        var rowKey = dayKey + " " + hm;
        var row = day.rowIdx[rowKey];
        if (!row) {
          row = { key: rowKey, hm: hm, access: [], fns: [], dot: "" };
          day.rowIdx[rowKey] = row;
          day.rows.push(row);
        }
        day.count += 1;
        if (e.source === "fns") row.fns.push(e);
        else row.access.push(e);
      }
      /* 圆点语义：有过失败（红色拒绝）优先；否则「这一刻只有同步」用同步色。
         放在分组后统一算，避免模板里写三层三元表达式。 */
      days.forEach(function (d) {
        d.rows.forEach(function (r) {
          var bad = false;
          for (var j = 0; j < r.access.length; j++) {
            if (r.access[j].ok === false) {
              bad = true;
              break;
            }
          }
          r.dot = bad ? "err" : r.fns.length && !r.access.length ? "sync" : "";
        });
      });
      return days;
    },
    showAccess: function () {
      return this.L.source !== "fns";
    },
    showFns: function () {
      return this.L.source !== "access";
    },
  },
  methods: {
    /* 组件内直接转发，模板里不 import（Vue 全局构建没有 setup 作用域）。 */
    setSource: setSource,
    setAccessKind: setAccessKind,
    setSyncAction: setSyncAction,
    setHideSelf: setHideSelf,
    exportLogs: exportLogs,
    refresh: function () {
      return loadLogs();
    },
    /* 主动续载一页更早的。滚到底自动续载也走这里 —— 两条入口共用同一个防重入闸
       （features/logs.js 的 loadingMore），所以手点与自动撞在一起也只会发一个请求。 */
    loadMore: function () {
      return loadMore();
    },
    /* 哨兵进了视口就续载；三个前置判据缺一不可：
       ① 还有更早的（hasMore）—— 否则哨兵一直在视口里，滚一下就发一次空请求；
       ② 没有正在续载 —— 不然一次滚动会连发好几页；
       ③ 页面可见 —— 切到后台标签页时 IO 仍会因布局变化触发，
          在后台刷日志既没用又白烧服务端 CPU。 */
    setupMoreWatch: function () {
      var vm = this;
      var el = this.$refs.moreSentinel;
      if (!el || typeof IntersectionObserver === "undefined") return;
      this._moreIO = new IntersectionObserver(
        function (entries) {
          for (var i = 0; i < entries.length; i++) {
            if (!entries[i].isIntersecting) continue;
            if (document.visibilityState !== "visible") return;
            if (!vm.L.hasMore || vm.L.loadingMore || vm.L.loading) return;
            vm.loadMore();
            return;
          }
        },
        /* 提前 200px 触发：等真滚到最底才请求，用户会看到半秒空白，
           那一瞬间很容易被当成「到底了」。 */
        { rootMargin: "0px 0px 200px 0px" }
      );
      this._moreIO.observe(el);
    },
    teardownMoreWatch: function () {
      if (this._moreIO) {
        this._moreIO.disconnect();
        this._moreIO = null;
      }
    },
    openAt: openNoteAt,
    fmtBytes: fmtBytes,
    full: fmtFull,
    actZh: function (a) {
      return AUDIT_ACTION_ZH[a] || a || "—";
    },
    syncActZh: function (a) {
      return SYNC_ACTION_ZH[a] || a || "—";
    },
    syncKindZh: function (k) {
      return SYNC_KIND_ZH[k] || k || "";
    },
    ipZh: function (e) {
      if (!e || !e.ip) return "";
      var local =
        e.ip === "127.0.0.1" || e.ip === "::1" || e.ip === "::ffff:127.0.0.1";
      return local ? "本机" : e.ip;
    },
    /* 「账号 › 令牌」里的令牌那一半（2026-11-05）。
       优先级与服务端一致：快照名 → 通道兜底。这里**不**复用 AccessPage 的
       五级辨认（按 id join 现表、前缀兜底、同 owner 同角色唯一匹配）——
       那套要额外拉 /api/tokens，而日志页的定位是「快照级可读」：
       令牌改名/删除后历史记录仍显示当时的名字，认不出来的就写「令牌」，
       不猜。真要逐枚辨认，访问控制页那栏更合适。 */
    tokZh: function (e) {
      if (!e) return "";
      if (e.token_name) return e.token_name;
      if (e.via === "token") return "令牌";
      if (e.via) return "会话";
      return "";
    },
    /* 重命名的 detail 记的是**旧路径**（见 Go 侧 eventlog 的说明），
       加个箭头让人一眼看出方向，而不是当成「又一条路径信息」。 */
    detailZh: function (e) {
      var d = String((e && e.detail) || "");
      if (!d) return "";
      if (e && e.action === "rename") return "← " + d;
      return d;
    },
  },
  template:
    '<div class="page lg-page">' +
    /* ---- 工具条：来源切换 + 两个独立筛选 + 导出 / 刷新 ---- */
    '  <x-card class="mb lg-toolbar">' +
    '    <div class="lg-bar">' +
    '      <div class="lg-seg" role="tablist">' +
    '        <button class="lg-seg-btn" :class="{on:L.source===\'all\'}" @click="setSource(\'all\')">全部</button>' +
    '        <button class="lg-seg-btn" :class="{on:L.source===\'access\'}" @click="setSource(\'access\')">访问日志</button>' +
    '        <button class="lg-seg-btn" :class="{on:L.source===\'fns\'}" @click="setSource(\'fns\')">FNS 同步</button>' +
    "      </div>" +
    '      <span class="spacer"></span>' +
    '      <button class="btn btn-sm" @click="exportLogs(\'csv\')" :class="{loading:L.exporting}"' +
    '              title="导出当前筛选下的全部日志（CSV，Excel 可直接打开）">导出 CSV</button>' +
    '      <button class="btn btn-sm" @click="exportLogs(\'json\')" :class="{loading:L.exporting}"' +
    '              title="导出当前筛选下的全部日志（JSON，给脚本用）">导出 JSON</button>' +
    '      <button class="btn btn-sm" @click="refresh" :class="{loading:L.loading}">刷新</button>' +
    "    </div>" +
    /* 两组筛选各自独立：左侧筛「访问日志的类型」，右侧筛「同步动作」。
       合成一个下拉会逼人先想「我要筛的是哪一类」，而这两件事本来互不相干。 */
    '    <div class="lg-chips" v-if="showAccess && L.filters.access_kinds.length">' +
    '      <span class="lg-chip-label">访问</span>' +
    '      <button class="ac-chip" :class="{on:!L.akind}" @click="setAccessKind(\'\')">全部</button>' +
    '      <button class="ac-chip" v-for="k in L.filters.access_kinds" :key="k.key"' +
    '              :class="{on:L.akind===k.key}" @click="setAccessKind(k.key)">{{ k.label }}</button>' +
    "    </div>" +
    '    <div class="lg-chips" v-if="showFns && L.filters.sync_actions.length">' +
    '      <span class="lg-chip-label">同步</span>' +
    '      <button class="ac-chip" :class="{on:!L.faction}" @click="setSyncAction(\'\')">全部</button>' +
    '      <button class="ac-chip" v-for="a in L.filters.sync_actions" :key="a.key"' +
    '              :class="{on:L.faction===a.key}" @click="setSyncAction(a.key)">{{ a.label }}</button>' +
    "    </div>" +
    /* 「隐藏日志自身同步」（2026-11-12 主人：「这个能不能隐藏，默认是同步的了，
       老显示看起来东西不直观」）：访问日志落在记忆库附件里，跟着 FNS 同步，
       写一行就镜像一条 —— 不隐藏的话右栏全是 audit.jsonl，真正的同步看不见。
       单独占一行而不是塞进上面「同步」那排：那排是按 sync_actions 动态生成的，
       只筛到「访问日志」视图时整排不渲染，开关会跟着一起消失。 */
    '    <div class="lg-chips">' +
    '      <span class="lg-chip-label">过滤</span>' +
    '      <button class="ac-chip" :class="{on:L.hideSelf}"' +
    '              @click="setHideSelf(!L.hideSelf)"' +
    '              title="访问日志落在记忆库附件里（附件/日志/audit.jsonl），会被 FNS 同步；默认不显示这些镜像事件">' +
    "        隐藏日志自身同步</button>" +
    "    </div>" +
    '    <div class="lg-status small faint">' +
    "      <span>共 {{ L.total }} 条 · 访问 {{ L.counts.access }} · 同步 {{ L.counts.fns }}</span>" +
    /* 被隐去多少要说出来（而不是默默少一截）：日志页是排查用的，
       「少掉的那些去哪了」必须能一句话答上，否则开关就变成了「数据不见了」的嫌疑。 */
    '      <span class="lg-src-on" v-if="L.selfCount > 0 && L.hideSelf"' +
    '            title="这些是访问日志自身被 FNS 同步时产生的镜像事件，可用上面的开关显示">' +
    "        · 已隐去自身同步 {{ L.selfCount }} 条</span>" +
    '      <span class="lg-src-on" v-else-if="L.selfCount > 0"' +
    '            title="访问日志自身被 FNS 同步时产生的镜像事件（当前已显示）">' +
    "        · 含自身同步 {{ L.selfCount }} 条</span>" +
    '      <span v-if="!L.fns.available" class="lg-src-off" :title="L.fns.path">' +
    "        · FNS 事件源未接入</span>" +
    '      <span v-else class="lg-src-on" :title="L.fns.path">· FNS 事件源已接入</span>' +
    '      <span v-if="L.access && L.access.in_vault" class="lg-src-on" :title="L.access.path">' +
    "        · 访问日志在记忆库内（随 FNS 同步）</span>" +
    '      <span v-else-if="L.access && !L.access.writable" class="lg-src-off" :title="L.access.path">' +
    "        · 访问日志不可写，事件会被丢弃</span>" +
    "    </div>" +
    "  </x-card>" +
    /* ---- 主体：一条时间轴，左右两栏 ---- */
    '  <x-card bare class="lg-card">' +
    '    <div class="lg-head">' +
    '      <div class="lg-col-head"><span class="nav-icon" v-html="svg(\'shield\')"></span>' +
    '        访问日志 <x-pill>{{ L.counts.access }}</x-pill></div>' +
    '      <div class="lg-col-head lg-col-axis">时间轴</div>' +
    '      <div class="lg-col-head"><span class="nav-icon" v-html="svg(\'clock\')"></span>' +
    '        FNS 同步日志 <x-pill>{{ L.counts.fns }}</x-pill></div>' +
    "    </div>" +
    '    <div class="lg-body">' +
    /* 首屏骨架：形状与真实行一致（时间轴 + 左右两块），替换时整列不跳。 */
    '      <div class="lg-skel" v-if="L.loading && !L.loaded" aria-busy="true">' +
    '        <div class="lg-row" v-for="i in 6" :key="i">' +
    '          <div class="lg-cell lg-l"><span class="skel line skel-l1"></span></div>' +
    '          <div class="lg-cell lg-axis"><span class="skel line w-time"></span></div>' +
    '          <div class="lg-cell lg-r"><span class="skel line w40"></span></div>' +
    "        </div>" +
    "      </div>" +
    '      <x-empty v-else-if="L.error" icon="alert">{{ L.error }}</x-empty>' +
    '      <div class="lg-tl" v-else-if="timeline.length">' +
    '        <template v-for="d in timeline" :key="d.key">' +
    '          <div class="lg-day"><span class="mono">{{ d.day }}</span>' +
    '            <span class="small faint">{{ d.count }} 条</span></div>' +
    '          <div class="lg-row" v-for="r in d.rows" :key="r.key">' +
    /* 左：访问日志 ---------------------------------------------------- */
    '            <div class="lg-cell lg-l">' +
    '              <button class="lg-ev lg-a" v-for="(e, i) in r.access" :key="\'a\'+i"' +
    '                      :class="{link: !!e.note}" :title="full(e.t)"' +
    '                      @click="openAt(e.note)">' +
    '                <span class="lg-ev-head">' +
    '                  <code class="lg-tool">{{ e.target || e.action }}</code>' +
    '                  <span class="lg-act">{{ actZh(e.action) }}</span>' +
    '                  <span class="lg-bad" v-if="e.ok===false">失败</span>' +
    "                </span>" +
    '                <span class="lg-ev-obj" v-if="e.note">› {{ e.note }}</span>' +
    '                <span class="lg-ev-meta">' +
    '                  <b>{{ e.actor || \'匿名\' }}</b>' +
    '                  <span v-if="tokZh(e)"> › {{ tokZh(e) }}</span>' +
    '                  <span v-if="e.ip"> · {{ ipZh(e) }}</span>' +
    '                  <span v-if="e.ms"> · {{ e.ms }}ms</span>' +
    /* 渠道（MCP 反代 / 调试台 / 地址栏）：同样一次工具调用，「从哪进来的」
       决定了它该不该被当成真人操作 —— 只写工具名会让脚本调用看起来像人手点的。 */
    '                  <span v-if="e.detail"> · {{ e.detail }}</span>' +
    "                </span>" +
    "              </button>" +
    '              <span class="lg-gap" v-if="!r.access.length"></span>' +
    "            </div>" +
    /* 中：时间轴 ------------------------------------------------------ */
    '            <div class="lg-cell lg-axis">' +
    '              <span class="lg-hm">{{ r.hm }}</span>' +
    '              <span class="lg-dot" :class="r.dot"></span>' +
    "            </div>" +
    /* 右：FNS 同步日志 ------------------------------------------------ */
    '            <div class="lg-cell lg-r">' +
    '              <button class="lg-ev lg-s" v-for="(e, i) in r.fns" :key="\'s\'+i"' +
    '                      :class="[\'s-\' + e.action, {link: !!e.title}]"' +
    '                      :title="e.path || \'\'" @click="openAt(e.title)">' +
    '                <span class="lg-ev-head">' +
    '                  <span class="lg-act">{{ syncActZh(e.action) }}</span>' +
    '                  <code class="lg-tool">{{ e.title || e.path }}</code>' +
    "                </span>" +
    '                <span class="lg-ev-meta">' +
    "                  <span>{{ syncKindZh(e.kind) }}</span>" +
    '                  <span v-if="e.size"> · {{ fmtBytes(e.size) }}</span>' +
    '                  <span v-if="e.detail"> · {{ detailZh(e) }}</span>' +
    "                </span>" +
    "              </button>" +
    '              <span class="lg-gap" v-if="!r.fns.length">' +
    "                <span class=\"small faint\">·</span></span>" +
    "            </div>" +
    "          </div>" +
    "        </template>" +
    "      </div>" +
    '      <div class="lg-empty" v-else>' +
    '        <x-empty icon="clock" title="还没有日志"' +
    '                  text="登录、调用工具、同步笔记都会记在这里。"></x-empty>' +
    /* FNS 没有数据源时的说明放在空状态里（而不是顶部红条）：它不是错误，
       而是「这块还没接线」；写清怎么接，比给一句警告有用。 */
    '        <div class="lg-empty-hint small faint" v-if="!L.fns.available">' +
    "          FNS 同步日志需要 <code>fns-sync</code> 容器（compose profile <code>fns</code>）——" +
    "          它把事件写到 <code>/state/sync-events.jsonl</code>，控制台以只读方式挂到" +
    "          <code>/fns-state</code>。没有这个文件时右栏为空，访问日志不受影响。" +
    "        </div>" +
    "      </div>" +
    /* ---- 时间轴尾部：续载更早（2026-11-12） -------------------------------
       时间轴是新→旧，所以「加载更早」只能挂在最底下 —— 挂在顶部既违反直觉
       （顶部是新的），也会让人误以为点它会刷新。
       按钮与哨兵都在这里：主通道是滚动自动续载，按钮同时服务「内核没有
       IntersectionObserver」「想手动催一页」和「无障碍键盘操作」三种情形
       （与记忆库 .lib-more 同一取向：故意压到文字级对比度，不抢注意力）。 */
    '      <div class="lib-tail" v-if="L.hasMore">' +
    '        <button class="lib-more" @click="loadMore" :disabled="L.loadingMore">' +
    "          {{ L.loadingMore ? '加载更早…' : '加载更早' }}</button>" +
    "      </div>" +
    /* 哨兵：常驻（不 v-if）—— 见 mounted 上方注释；高度 1px 而不是 0：
       零面积元素的交集判定在部分内核里永远报「不相交」，给它 1px 才是稳的
       （这点也不占布局，肉眼看不见）。 */
    '      <div class="lg-sentinel" ref="moreSentinel" aria-hidden="true" style="height:1px"></div>' +
    "    </div>" +
    /* 采集面边界（与访问控制页同一句口径）：直连 MCP 端口的调用不在此列。
       顺带把「首屏只取 60 条 + 滚到底续载」写在这里：用户看到列表到底时，
       得知道「这是分页的底，不是日志的底」。 */
    '    <div class="lg-foot">只统计经过本控制台的调用（<code>/mcp</code> 反代与' +
    "      <code>/api/*</code>）；首屏 60 条，滚到底（或点「加载更早」）续载更早的事件；" +
    "      每 12 秒静默刷新最近一页。左栏点条目可打开对应笔记。</div>" +
    "  </x-card>" +
    "</div>",
};

export { LogsPage };
