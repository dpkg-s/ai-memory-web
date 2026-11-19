/* 通用页面骨架 —— 视图懒加载（defineAsyncComponent）期间的占位。

   为什么它必须留在**主包**里同步 import：
   它是 async 视图解析**之前**就要画出来的东西（Vue 的 loadingComponent）。
   骨架自己也懒加载的话，用户就得先等骨架模块、再等视图模块，两个请求串行，
   比不做懒加载还慢。

   为什么形状要一板一眼地贴着真页面：
   骨架高度 ≈ 真页面高度，模块到位那一刻才不会把下面的内容「顶一下」
   （布局位移比慢一点更让人难受）。所以尺寸全部复用既有工具类
   （.grid.stats / .skel.stat-skel / .grid.two / .card / .card-body），
   **不新增任何 CSS**：一来 CSS 归另一条线管，二来
   `.grid.stats > .stat-skel` 的高度是探针实测校准过的（桌面 123px / 窄屏 111px，
   见 7-views.css §17c-4 与 8-responsive.css §20），自己写死数字必然与真卡失配。

   根元素必须带 .page：壳层的 <transition name="page"> 与一批
   `.page:has(...)` 规则都认这个类 —— 缺了会出现「骨架没有入场动画、真页面有」，
   以及 :has() 规则生效瞬间的跳变。

   调用方式：由 main.js 的视图表闭包捏成「带自己那套规格」的小组件
   （loadingComponent 由 Vue 直接 createVNode 出来，拿不到 props，
   见 main.js#skeletonFor）。 */
var PageSkeleton = {
  name: "PageSkeleton",
  props: {
    /* 统计卡占位数量：概览 / 访问控制顶部是 4 块统计卡，其余页没有这一行。 */
    stats: { type: Number, default: 4 },
    /* 每张卡里的骨架行数：大致对应真卡里的行数，太少会显得「矮瘦」。 */
    rows: { type: Number, default: 5 },
    /* 两栏（左列表 + 右详情）还是单栏大卡。 */
    split: { type: Boolean, default: true },
    /* 读屏器的念白：骨架本身没有任何文字，没有名字等于一片空白。 */
    label: { type: String, default: "页面加载中" },
  },
  computed: {
    /* 撑满可视区（扣掉顶栏 / 面包屑 / 状态栏）。
       用 var() 而不是硬编码像素：这三条是 1-tokens.css 的全局令牌，
       8-responsive.css 的窄屏档会把 --topbar-h 从 62px 改成 58px，
       写死像素在手机档必然对不上，骨架会短一截。 */
    fill: function () {
      return (
        "calc(100vh - var(--topbar-h) - var(--crumbs-h) - var(--statusbar-h))"
      );
    },
  },
  template:
    '<div class="page" :style="{ minHeight: fill }" role="status" aria-busy="true" :aria-label="label">' +
    '  <div class="grid stats" v-if="stats">' +
    '    <div class="skel stat-skel" v-for="i in stats" :key="i"></div>' +
    "  </div>" +
    '  <div class="grid two mt" v-if="split">' +
    '    <div class="card"><div class="card-body"><x-skel :n="rows"></x-skel></div></div>' +
    '    <div class="card"><div class="card-body"><x-skel :n="rows + 2"></x-skel></div></div>' +
    "  </div>" +
    '  <div class="card mt" v-else><div class="card-body"><x-skel :n="rows + 4"></x-skel></div></div>' +
    "</div>",
};

export { PageSkeleton };
