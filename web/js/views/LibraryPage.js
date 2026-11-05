import { computed } from "../../vendor/vue.esm-browser.prod.js";
import { S, toast } from "../core/store.js";
import { clearanceZh, confZh, fmtNum, mdRender, securityPill, securityZh, statusZh, tierZh, typeZh } from "../core/util.js";
import { browseLibrary, loadMoreLibrary, onMdClick, openNote, setLibrarySort } from "../features/library.js";

/* 滚动续载的预取余量（2026-10-29）：哨兵进入「视口 + 这个余量」就要下一页。
   取值要**小于一页的高度**（40 条 ≈ 2160px），否则追加一页后哨兵仍在预取区内、
   下一次滚动才算「再次进入」，用户会看到「滚到底却没反应」。实测一页远超 400px，
   360 足够提前 6~7 条开始要数据。 */
var TAIL_MARGIN_PX = 360;

var LibraryPage = {
  data: function () {
    return { S: S };
  },
  /* 续载哨兵的两处挂钩（2026-10-29）：
     · mounted —— 装滚动捕获（第三参 true = 捕获阶段，能收到**任何**容器的滚动）；
     · watch —— 数据到达不会触发 scroll，必须单独补一次「是否已经该续载」。
     ⚠️ 这里**不用 IntersectionObserver**：实测（2026-10-29，无头 Chrome 劫持
     构造函数取证）本页 IO 一次都没有被创建 —— `$refs` 在 `v-if` 哨兵上取不到，
     且真正的滚动容器是 `.grid.lib` 里的 **.card**（overflow:auto，
     clientH 610 / scrollH 6044），不是页面层。scroll 捕获 + rAF 节流不依赖
     「滚动容器是谁」，也不依赖 ref 时序，是实测能跑通的那条路。 */
  mounted: function () {
    window.addEventListener("scroll", this.onScrollCapture, true);
    this.$nextTick(this.maybeLoad);
  },
  watch: {
    /* 只看长度变化：翻页一定改长度，而 loading / error 这类翻转不需要重算。 */
    "L.items.length": function () {
      this.$nextTick(this.maybeLoad);
    },
  },
  unmounted: function () {
    window.removeEventListener("scroll", this.onScrollCapture, true);
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = 0;
    }
  },
  computed: {
    L: function () {
      return S.library;
    },
    tagsOf: function () {
      return function (it) {
        return (it.tags || []).slice(0, 4);
      };
    },
    /* 列表行的访问控制 pill（2026-10-25）：**只在非默认档时出现**。
       服务端 `_meta_facets` 只回写非默认值，所以默认的 internal/member 在这里
       天然拿不到条目 —— 416 条存量不会整屏挂 pill；一旦某条被提级成 secret /
       owner，它会在列表里自己跳出来。 */
    accessTag: function () {
      return function (it) {
        var f = (it && it.facets) || {};
        var sec = f.security;
        if (!sec && !f.clearance) return null;
        var key = sec || "internal";
        return { kind: securityPill(key), text: securityZh(key) };
      };
    },
    rendered: function () {
      return this.L.note ? mdRender(this.L.note.body) : "";
    },
    /* 节点信息 · 元数据：只挑「节点身份」字段；summary / source_context 这类
       长文本不进面板（否则右栏会被一句话撑爆）。
       2026-10-14 汉化：键名走中文（口径 = 概览页既有译法：热度 / 读取 / 置信度）。
       2026-10-20 值也汉化：类型 / 热度 / 状态 / 置信度 四个枚举值改走 util.js 的
       TYPE_ZH / TIER_ZH / STATUS_ZH / CONF_ZH —— 与概览页「记忆类型」卡共用同一份表。
       原文放进 `raw`，模板挂在 title 上（指上去仍能看到 project / warm / high）。 */
    nodeMeta: function () {
      var n = this.L.note || {};
      var m = n.meta || {};
      var rows = [
        ["路径", n.path || n.title, ""],
        ["类型", typeZh(m.type), m.type],
        ["大小", n.total_chars ? fmtNum(n.total_chars) + " 字符" : "", ""],
        ["创建", this.dateOnly(m.created), ""],
        ["更新", this.dateOnly(m.updated), ""],
        ["热度", tierZh(m.tier), m.tier],
        ["读取", m.access_count, ""],
        ["版本", m.version, ""],
        ["状态", statusZh(m.status), m.status],
        ["置信度", confZh(m.confidence), m.confidence],
        /* v3 访问控制（2026-10-25）：元数据表**总是**列出这两行 —— 默认档也显示，
           因为「这条谁能读」是审计问题，而审计不能靠「没显示 = 默认」去猜。
           列表行那边才做省略（见 listPills），否则 416 条会挂满 pill。 */
        ["安全等级", securityZh(m.security || "internal"), m.security || "internal"],
        ["权级", clearanceZh(m.clearance || "member"), m.clearance || "member"],
      ];
      return rows
        .filter(function (r) {
          return r[1] !== undefined && r[1] !== null && r[1] !== "";
        })
        .map(function (r) {
          return { k: r[0], v: r[1], raw: r[2] || "" };
        });
    },
    nodeTags: function () {
      var t =
        (this.L.note && this.L.note.meta && this.L.note.meta.tags) || [];
      if (!Array.isArray(t)) t = [t];
      return t.filter(Boolean);
    },
    /* 节点信息 · 关联节点：从正文抽 [[双链]]，按出现次数当 references。 */
    nodeLinks: function () {
      var b = (this.L.note && this.L.note.body) || "";
      var hits = b.match(/\[\[[^\]]+\]\]/g) || [];
      var count = {};
      var order = [];
      hits.forEach(function (x) {
        var t = x
          .replace(/^\[\[/, "")
          .replace(/\]\]$/, "")
          .split("|")[0]
          .trim();
        if (!t) return;
        if (!count[t]) {
          count[t] = 0;
          order.push(t);
        }
        count[t] += 1;
      });
      return order.map(function (t) {
        return { title: t, n: count[t] };
      });
    },
    /* 排序（2026-11-05，主人：「全部条目 添加笔记排序方式」）。
       字段与方向各自一项、可自由组合 —— 不做「标题 A→Z」这类预设墙：
       预设越多，没实现的组合越容易被当成本该有。 */
    libSorts: function () {
      return [
        { key: "", label: "默认（路径倒序）" },
        { key: "created", label: "创建时间" },
        { key: "title", label: "标题" },
        { key: "tier", label: "热度" },
        { key: "reads", label: "读取次数" },
        { key: "path", label: "路径" },
      ];
    },
  },
  methods: {
    /* 改排序 = 重新取第一页（必须重置：服务端排完再切片，续载才接得上）。 */
    applySort: function (key, order) {
      setLibrarySort(key, order);
    },
    /* ---------- 滚动续载（2026-10-29） ----------
       形态由主人选定：**滚到底自动追加**，不让人点按钮。
       判据用 `getBoundingClientRect()` 而不是 IO 的交叉状态：实测本页的滚动容器
       是卡片自身（`.card`，overflow:auto），窗口根本不滚；而 window 上的
       **捕获阶段** scroll 监听能收到任意容器冒泡上来的滚动事件，与滚动容器是谁无关。
       rAF 节流：滚动每帧都可能触发，读一次布局本身便宜，但没必要一帧跑多次。 */
    tailInView: function () {
      var el = this.$el && this.$el.querySelector(".lib-tail");
      if (!el) return false;
      var r = el.getBoundingClientRect();
      var vh = window.innerHeight || document.documentElement.clientHeight || 0;
      return r.top < vh + TAIL_MARGIN_PX && r.bottom > -TAIL_MARGIN_PX;
    },
    maybeLoad: function () {
      if (this.tailInView()) this.loadMore();
    },
    onScrollCapture: function () {
      var self = this;
      if (this._raf) return;
      this._raf = requestAnimationFrame(function () {
        self._raf = 0;
        self.maybeLoad();
      });
    },
    loadMore: function () {
      var L = S.library;
      if (L.mode !== "browse" || !L.hasMore) return;
      if (L.loading || L.loadingMore) return;
      loadMoreLibrary();
    },
    onMd: function (ev) {
      onMdClick(ev);
    },
    dateOnly: function (s) {
      return s ? String(s).slice(0, 10) : "";
    },
    openLink: function (t) {
      openNote(t);
    },
    /* 节点信息 · 标签 点击（2026-10-14 修）
       原实现 `@click="openLink(t)"` → `openNote(t)` → `memory_read(title=标签名)`：
       `memory_read` 按**条目标题**精确查找，而标签名从来不是标题 ⇒ 必然 not found，
       中间栏渲染「（未找到）」、右栏「节点信息」被清空。这就是「点 TAGS 列不出该标签
       的笔记」的根因 —— **接线接错对象**，不是标签过滤能力缺失。

       标签过滤早已具备：`memory_list(tag=…)` 在服务端按 frontmatter tags 过滤
       （server.py `memory_list`，大小写不敏感），页面顶部本就有「标签过滤」输入框。
       故复用概览页「热门标签」的既定接法：写回 L.tag → 切 browse → 重新列举。
       同标签再点是**取消**（进得去也出得来）。 */
    openTag: function (t) {
      var L = this.L;
      var off = L.tag === t;
      L.tag = off ? "" : t;
      L.keyword = "";
      L.mode = "browse";
      browseLibrary().then(function () {
        if (L.error) return; /* 失败已有 err toast，不再叠加成功提示 */
        if (off) toast("ok", "已取消标签过滤", "共 " + L.count + " 条");
        else toast("ok", "已按标签过滤", "「" + t + "」共 " + L.count + " 条");
      });
    },
    niTagHint: function (t) {
      return this.L.tag === t ? "取消该标签过滤" : "列出带有「" + t + "」的条目";
    },
    tierPill: function (t) {
      return t === "hot" ? "err" : t === "cold" ? "" : "info";
    },
  },
  template:
    '<div class="page">' +
    '  <x-card class="mb">' +
    '    <div class="input-group">' +
    '      <input class="input" v-model="L.keyword" placeholder="关键词搜索（标题 / 标签 / 正文）…" ' +
    '             @keyup.enter="searchLibrary()">' +
    '      <button class="btn btn-primary" @click="searchLibrary()" :class="{loading:L.loading}">' +
    "        <span v-html=\"svg('search')\"></span>搜索</button>" +
    "      <button class=\"btn\" @click=\"L.mode='browse'; L.keyword=''; browseLibrary()\">浏览</button>" +
    "    </div>" +
    '    <div class="row2 mt">' +
    '      <x-field flat label="标签过滤">' +
    '        <input class="input" v-model="L.tag" placeholder="如 mcp / v3" @keyup.enter="L.mode===\'search\'?searchLibrary():browseLibrary()"></x-field>' +
    '      <x-field flat label="热度">' +
    '        <select class="select" v-model="L.tier" @change="browseLibrary()">' +
    '          <option value="">全部</option><option value="hot">hot</option>' +
    '          <option value="warm">warm</option><option value="cold">cold</option></select></x-field>' +
    "    </div>" +
    /* 排序（2026-11-05）。放在单独一行的理由：它与上面两个是**同一次取数**的
       参数，但语义不同 —— 上面是「筛出哪些」，这里是「按什么顺序排」。
       挤进同一行会在窄屏被压成四个半宽控件，选项名全被截断。 */
    '    <div class="row2 mt">' +
    '      <x-field flat label="排序">' +
    '        <select class="select" v-model="L.sort" @change="applySort(L.sort, L.order)">' +
    '          <option v-for="s in libSorts" :key="s.key" :value="s.key">{{ s.label }}</option>' +
    "        </select></x-field>" +
    '      <x-field flat label="方向">' +
    '        <select class="select" v-model="L.order" :disabled="!L.sort"' +
    '                @change="applySort(L.sort, L.order)">' +
    '          <option value="">默认</option><option value="asc">升序</option>' +
    '          <option value="desc">降序</option></select></x-field>' +
    "    </div></x-card>" +
    '  <div class="grid lib">' +
    '    <x-card bare>' +
    "      <div class=\"card-head\"><h3>{{ L.mode==='search' ? '搜索结果' : '全部条目' }}</h3>" +
    '        <span class="spacer"></span>' +
    "        <x-pill>{{ L.mode==='search' ? L.searchItems.length : (L.count||L.items.length) }}</x-pill></div>" +
    '      <div class="card-body tight">' +
    '        <x-skel v-if="L.loading" :n="6"></x-skel>' +
    '        <x-empty v-else-if="L.error" icon="alert">{{ L.error }}</x-empty>' +
    "        <transition-group tag=\"div\" name=\"liblist\" class=\"list\" appear v-else-if=\"L.mode==='search' && L.searchItems.length\">" +
    '          <x-list-item v-for="(it, i) in L.searchItems" :key="it.file" :style="\'--i:\' + i" :title="it.title" @click="openNote(it.title)">' +
    '            <template #sub><span class="mono">{{ it.file }}</span></template>' +
    '            <template #right><x-pill kind="accent">打开</x-pill></template>' +
    "          </x-list-item></transition-group>" +
    "        <transition-group tag=\"div\" name=\"liblist\" class=\"list\" appear v-else-if=\"L.mode==='browse' && L.items.length\">" +
    /* `--i` 取模（2026-10-29）：续载是**追加**，全局索引会一路涨到 400+，
       而 6-anim.css 的 `min(var(--i),12) * 30ms` 夹到 360ms ⇒ 后面每一页的
       条目都要先干等 360ms 才齐刷出现，追加手感像卡住。按 12 取模让每一批
       都重新错峰，视觉一致且不积压。 */
    '          <x-list-item v-for="(it, i) in L.items" :key="it.path || it.title" :style="\'--i:\' + (i % 12)" :title="it.title" :sub="short(it.preview)" @click="openNote(it.title)">' +
    '            <div class="tags mt-sm"><span class="tag" v-for="tg in tagsOf(it)" :key="tg">{{ tg }}</span></div>' +
    '            <template #right><x-pill v-if="accessTag(it)" :kind="accessTag(it).kind">{{ accessTag(it).text }}</x-pill>' +
    '              <x-pill :kind="tierPill(it.tier)">{{ it.tier }}</x-pill>' +
    '              <span class="small faint nowrap">{{ it.reads }} 次</span></template>' +
    "          </x-list-item></transition-group>" +
    '        <x-empty v-else-if="L.mode===\'search\' && L.searchRaw" icon="search" title="没有命中">' +
    '          <pre class="code mt" style="text-align:left">{{ L.searchRaw }}</pre></x-empty>' +
    '        <x-empty v-else icon="book" title="还没有加载内容" text="点上面「浏览」看全部条目，或输入关键词搜索。"></x-empty>' +
    /* 续载哨兵（2026-10-29）。必须挂在 v-if/v-else 链**之外**：插进链中间会
       把后面的 `v-else` 变成「无前置 v-if」，直接编译失败。
       容器常留、内容按状态切换 —— 节点稳定，IO 的 observe 目标才不会每页换一次。
       按钮不是主通道（自动续载已覆盖），它是 IO 不可用时的降级入口，所以做成
       低对比度的纯文字样式，不抢列表的注意力。 */
    '        <div class="lib-tail" v-if="L.mode===\'browse\' && !L.loading && !L.error && L.items.length">' +
    '          <template v-if="L.hasMore">' +
    '            <button class="lib-more" @click="loadMore" :disabled="L.loadingMore">' +
    "              {{ L.loadingMore ? '正在加载…' : '加载更多' }}</button>" +
    '            <div class="small faint">{{ L.items.length }} / {{ L.count }} 条 · 继续下滑自动加载</div>' +
    "          </template>" +
    '          <div class="small faint" v-else>已全部加载 · 共 {{ L.items.length }} 条</div>' +
    "        </div>" +
    "      </div></x-card>" +
    '    <x-card sticky bare>' +
    '      <div class="card-head" v-if="L.note"><h3>{{ L.note.title }}</h3>' +
    '        <span class="spacer"></span>' +
    '        <x-pill mono v-if="L.note.total_chars">{{ fmtNum(L.note.total_chars) }} 字符</x-pill></div>' +
    '      <div class="card-body">' +
    '        <transition name="reader" mode="out-in">' +
    '        <div v-if="L.noteLoading" key="skel"><x-skel :n="1" w="w40"></x-skel><x-skel :n="1" block mt></x-skel></div>' +
    "        <div v-else-if=\"L.note\" :key=\"L.note.title || 'note'\">" +
    '          <x-banner v-if="L.note.truncated" icon="info">' +
    "            <div>正文较长，已截断显示。</div></x-banner>" +
    '          <div class="md" v-html="rendered" @click="onMd"></div>' +
    "        </div>" +
    '        <x-empty v-else key="empty" icon="file" title="未选中条目" text="左边点任意条目即可在此查看渲染结果。"></x-empty>' +
    "        </transition>" +
    "      </div></x-card>" +
    '    <x-card bare class="sticky-side">' +
    '      <div class="card-head"><h3 class="mono">节点信息</h3>' +
    '        <span class="spacer"></span>' +
    '        <x-pill mono v-if="L.note && L.note.meta && L.note.meta.tier">{{ L.note.meta.tier }}</x-pill></div>' +
    '      <div class="card-body">' +
    '        <x-empty v-if="!L.note" icon="file" title="未选中条目" text="点开任意条目查看节点信息。"></x-empty>' +
    "        <template v-else>" +
    '          <div class="ni-sec">元数据</div>' +
    '          <x-kv class="ni-kv stagger-in">' +
    '            <x-kv-row v-for="(r, i) in nodeMeta" :key="r.k" :style="\'--i:\' + i" :label="r.k" :value="r.v" :title="r.raw || null"></x-kv-row>' +
    "          </x-kv>" +
    '          <div class="ni-sec">标签</div>' +
    '          <div class="tags stagger-in" v-if="nodeTags.length">' +
    '            <button class="tag tg-btn" v-for="(t, i) in nodeTags" :key="t" :style="\'--i:\' + i" @click="openTag(t)" :title="niTagHint(t)">{{ t }}</button></div>' +
    '          <div class="small faint" v-else>（无标签）</div>' +
    '          <div class="ni-sec">关联节点</div>' +
    '          <div class="ni-links stagger-in" v-if="nodeLinks.length">' +
    '            <button class="ni-link" v-for="(l, i) in nodeLinks" :key="l.title" :style="\'--i:\' + i" @click="openLink(l.title)">' +
    '              <span class="mono ni-link-t">{{ l.title }}</span>' +
    '              <span class="small faint">{{ l.n }} 处引用</span></button></div>' +
    '          <div class="small faint" v-else>（无关联节点）</div>' +
    "        </template>" +
    "      </div></x-card>" +
    "  </div>" +
    "</div>",
};

export { LibraryPage };
