import { computed, nextTick, watch } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../core/api.js";
import { boot, loadTools } from "../core/data.js";
import { go, pageAllowed, readHash, syncNavInd, syncTabInd } from "../core/router.js";
import { S, closeConfirm, dismiss, toast } from "../core/store.js";
import { loadThresholds } from "../features/settings.js";
import { autoCheckUpdates, pendingCount } from "../features/update.js";
import { dressPanel } from "../core/lg.js";
import { mountRailLens } from "../core/lens.js";

/* ======================================================================
 * 14. 根组件
 * ==================================================================== */
var NAV = [
  { id: "dashboard", label: "概览", icon: "grid", key: "1" },
  { id: "console", label: "调试台", icon: "terminal", key: "2" },
  { id: "library", label: "记忆库", icon: "book", key: "3" },
  { id: "access", label: "访问控制", icon: "shield", key: "4" },
  { id: "settings", label: "配置", icon: "sliders", key: "5" },
];
var PAGE_TITLES = {
  dashboard: "概览",
  console: "调试台",
  library: "记忆库",
  access: "访问控制",
  settings: "配置",
};
var PAGE_SUBS = {
  dashboard: "健康度与最近动态",
  console: "直接调用 MCP 工具",
  library: "浏览与检索条目",
  access: "账号 · 令牌 · 权限",
  settings: "连接 · 阈值 · 同步",
};

/* 2026-10-13：VIEWS（标签条视图表）与 PANELS（底部面板页签表）已随两条横带整块摘除。
   原来的「专注模式」（概览只看最近更新 / 调试台只看终端输出·日志 / 记忆库只看节点信息）
   一并下线 —— 各页固定为默认视图，所有栏目常显。 */

/* 侧栏在窄屏是抽屉：给 body 加锁避免滚动穿透 */
function fixSidebarVar() {
  var narrow = window.innerWidth < 900;
  if (!narrow) S.sidebarOpen = false;
  document.body.style.overflow = narrow && S.sidebarOpen ? "hidden" : "";
  /* 视口变化后侧栏几何会变，指示条重新对位（不带动画，避免拖尾感） */
  syncNavInd(false);
}
watch(function () {
  return S.sidebarOpen;
}, fixSidebarVar);
/* 终端视图切换的滑动指示条 —— 挂在全局 watch 而不是改模板的 @click：
   视图还有程序化入口（执行完工具后会把 view 重置为 rendered，另见
   S.console.view 的赋值点），watch 一次覆盖两条路径，@click 只覆盖前者。
   签名里带上 result / foldResult：结果区是动态出现的，
   它出现的那一刻指示条需要首次落位（否则永远停在 opacity:0）。 */
watch(
  function () {
    return (
      S.console.view +
      "|" +
      (S.console.result ? 1 : 0) +
      "|" +
      (S.console.foldResult ? 1 : 0)
    );
  },
  function () {
    nextTick(function () {
      syncTabInd(document.querySelector(".term-tabs"));
    });
  },
);

/* 共享工具与组件统一挂到 app 上（Vue 全局构建没有 setup 作用域）。
   改造前这里是 14 行 `X.methods.foo = foo` 的逐组件打补丁 —— 同一个 svg/fmtNum
   在 5 个组件里各写一遍。现在一次注册，任何模板都能直接用；
   组件自己声明的同名方法优先级更高，不会互撞。 */

var Root = {
  data: function () {
    return {
      S: S,
      titles: PAGE_TITLES,
      subs: PAGE_SUBS,
    };
  },
  computed: {
    /* 可见页面 id 列表 —— 判据全部来自 core/router.js#PAGE_ROLES（唯一事实源）。
       2026-10-26 主人先要求「只读也不许进访问控制」，随后又指出「调试台在只读
       怎么也在」。两次都是同一个问题的两面：入口散落在三处（侧栏、命令面板、
       hash 直达）。所以这里不再为某一页写一个 canSeeXxx，而是统一产出
       visiblePages，让侧栏、路由守卫、命令面板都读同一份。

       ⚠️ 角色是**异步到位**的：首帧 S.role 为空串。空值必须视为「不裁剪」
       （pageAllowed 已内建该口径），否则管理员入口会在首帧被藏掉，之后 role
       到了也未必补得回来（这正是 2026-10-22「账号 0 个」那个坑的同源问题）。 */
    visiblePages: function () {
      var role = S.role;
      return NAV.filter(function (n) {
        return pageAllowed(role, n.id);
      }).map(function (n) {
        return n.id;
      });
    },
    /* 侧栏条目改为按可见性裁剪。data 里原本是静态 NAV，现在必须走 computed ——
       静态数组无法随角色变化重算。 */
    nav: function () {
      var ids = this.visiblePages;
      return NAV.filter(function (n) {
        return ids.indexOf(n.id) >= 0;
      });
    },
    pageTitle: function () {
      return this.titles[S.page] || "";
    },
    pageSub: function () {
      return this.subs[S.page] || "";
    },
    endpointShort: function () {
      var e = S.health.endpoint || S.about.resolved.mcp_endpoint || "";
      return e.replace(/^https?:\/\//, "");
    },
    /* 活动栏**单簇**（2026-10-15 主人令：「把配置从最下面移上来」）。
       原「主功能在上 + 配置落底簇」的 VS Code 式两簇结构已取消 —— 四项导航
       连续排在顶部，底部整块留给 .sidebar-foot（它自带 margin-top:auto）。
       模板直接遍历 data.nav，不再经 navTop / navBot 两个 computed 切片。 */
    /* 面包屑 = 根 › 页（视图切换已下线，不再有第三段）。 */
    crumbs: function () {
      return ["ai-memory", this.pageTitle];
    },
    numStat: function () {
      return ((S.overview || {}).parsed || {}).nums || {};
    },
    logs: function () {
      return S.console.logs || [];
    },
    lastLog: function () {
      return (S.console.logs || [])[0] || null;
    },
    /* 登录框只留标题（2026-10-21）：原先还带一行说明，两种模式各写一句
       （Cookie / sessionStorage 的实现细节）。那属于实现说明而不是用户需要
       读的信息，登录框里尤其多余 —— 全部去掉，标题足够。 */
    authTitle: function () {
      return S.authMode === "password" ? "登录" : "输入访问令牌";
    },
    isPasswordMode: function () {
      return S.authMode === "password";
    },
    authSwitchLabel: function () {
      return S.authMode === "password" ? "改用访问令牌" : "改用账号密码";
    },
    authSubmitLabel: function () {
      if (S.loginBusy) return "登录中…";
      return "进入";
    },
    /* 侧栏底部显示的「当前身份」：会话登录显示用户名，令牌模式显示「令牌」，
       两者都没有（回环免鉴权）则整行不出现。 */
    authWho: function () {
      if (S.sessionUser) return S.sessionUser;
      return S.authVia === "token" ? "令牌" : "";
    },
    /* 「注销」按钮的显隐（2026-10-23）：只在**确实有可注销的登录态**时出现。
       三个来源任一成立即可 ——
         · sessionUser      会话登录（Cookie）
         · authVia==="token" 令牌通道（凭据在 sessionStorage）
         · role             服务端认过身份（降级兜底，防止会话里 user 为空）
       回环免鉴权 / 已经弹着登录框时不显示 —— 前者没有登录态可退，后者按钮
       本来就被登录浮层盖住，多画一个只会显得界面没收干净。 */
    canLogout: function () {
      if (S.authRequired) return false;
      return !!(S.sessionUser || S.authVia === "token" || S.role);
    },
  },
  /* 路由守卫（2026-10-26）：把「入口藏起来」升级成「进不去」。
     只藏侧栏是不够的 —— hash 可以直接编辑、书签会留着旧地址、刷新后还会
     还原上次的 #console / #access。两种触发都要覆盖：进来时角色已知、
     以及角色后到（visiblePages 依赖 S.role，role 一变它就重算 ⇒ 第二个
     watch 会被点着）。 */
  watch: {
    "S.page": function (p) {
      if (!this.canSee(p)) go("dashboard");
    },
    visiblePages: function () {
      if (!this.canSee(S.page)) go("dashboard");
    },
  },
  methods: {
    dismiss: dismiss,
    closeConfirm: closeConfirm,
    /* 某一页当前角色能不能看。模板与守卫共用同一处口径，避免
       「守卫放过去了、模板却画不出来」这种一半对一半错的状态。 */
    canSee: function (id) {
      return this.visiblePages.indexOf(id) >= 0;
    },
    /* 「有可用更新」的导航圆点判据（2026-10-19）。方法而非 computed：
       S.update 是普通响应式对象，模板渲染时读到 targets 就能正常追踪。 */
    pendingCount: pendingCount,
    /* 2026-10-20：主题切换已整体移交给 <theme-switch>（它直接调 applyTheme），
       原来的 theme(p) 三态入口随之删除 —— 留着就是第二个写 themePref 的地方，
       迟早与开关的显示状态不一致。 */
    doConfirm: function () {
      if (S.confirm.phrase && S.confirm.typed.trim() !== S.confirm.phrase)
        return;
      var fn = S.confirm.onOk;
      closeConfirm();
      if (fn) fn();
    },
    submitToken: function () {
      if (!S.tokenInput) {
        S.loginError = "请填入访问令牌。";
        return;
      }
      api.setToken(S.tokenInput.trim());
      S.tokenInput = "";
      S.loginError = "";
      S.authRequired = false;
      boot();
    },
    /* 账号密码登录。成功后服务端下发 HttpOnly Cookie，前端**不保存任何口令**。
       这里不自己判断「成功与否」——只看后端 200/401，前端的任何预判都会
       变成第二处真相（后端改了口径，前端还按老规矩放行/拦截）。 */
    submitLogin: function () {
      if (S.loginBusy) return;
      var u = String(S.loginUser || "").trim();
      var p = String(S.loginPassword || "");
      if (!u || !p) {
        S.loginError = "请输入用户名与口令。";
        return;
      }
      S.loginBusy = true;
      S.loginError = "";
      api
        .login(u, p)
        .then(function (d) {
          S.loginPassword = "";
          S.sessionUser = (d && d.user) || u;
          S.authVia = "session";
          S.authRequired = false;
          S.loginBusy = false;
          boot();
        })
        .catch(function (e) {
          var d = (e && e.data) || {};
          S.loginBusy = false;
          S.loginPassword = "";
          S.loginError = d.error || e.message || "登录失败";
        });
    },
    toggleAuthMode: function () {
      S.authMode = S.authMode === "password" ? "token" : "password";
      S.loginError = "";
    },
    logout: function () {
      /* 先让服务端清 Cookie，再清本地的令牌与状态。顺序反了会留下
         「Cookie 还在、界面却已回到登录框」的错位 —— 刷新一下又进去了，
         看起来像登出失败。 */
      api
        .logout()
        .catch(function () {
          /* 登出接口不通也要把本地清干净：宁可多登出几次，也不能留着旧态 */
        })
        .then(function () {
          api.setToken("");
          S.tokenInput = "";
          S.loginPassword = "";
          S.sessionUser = "";
          S.authVia = "none";
          /* 身份相关的三个字段必须一起清：留着 role 会让侧栏继续显示
             「访问控制」入口，点进去必然 401 —— 比直接藏掉更让人困惑。 */
          S.role = "";
          S.canManage = false;
          S.multiUser = false;
          S.loginError = "";
          S.authRequired = true;
          S.authMode = S.loginEnabled ? "password" : "token";
          /* 2026-10-23：给一个明确回执。原来点了「登出」界面只是静悄悄
             弹回登录框 —— 分不清是注销成功、还是会话过期被踢。 */
          toast("ok", "已注销", "本地令牌与登录会话已清除。");
        });
    },
    onKey: function (e) {
      if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
      if (e.key === "Escape") {
        S.sidebarOpen = false;
        closeConfirm();
        return;
      }
      /* 快捷键 1–5 也必须走**可见**清单：写死 NAV 的话，只读账号按「2」
         照样跳进已经藏起来的调试台，等于给了一条隐形入口。 */
      var hit = this.nav.filter(function (n) {
        return n.key === e.key;
      })[0];
      if (hit) go(hit.id);
    },
  },
  mounted: function () {
    /* 侧栏上玻璃：贴图尺寸按布局实时量（64 × 视口高），resize 后重算。 */
    var rail = this.$el.querySelector(".sidebar");
    this._railOff = dressPanel(rail);
    /* 悬停跟随透镜：跟手滑动 + 命中侧栏内任何位置都能折射。 */
    this._lensOff = mountRailLens(rail, this.$el.querySelector(".rail-lens"));
    // 深链：#/settings?tab=th 直接落到指定页签（可分享、可测）。
    var hq = location.hash.split("?")[1] || "";
    var sp = hq || (location.search || "").replace(/^\?/, "");
    try {
      var tab = new URLSearchParams(sp).get("tab");
      if (tab && ["conn", "th", "fns", "about"].indexOf(tab) >= 0)
        S.settingsTab = tab;
    } catch (e) {
      /* 忽略 */
    }
    S.page = readHash();
    fixSidebarVar();
    window.addEventListener("resize", fixSidebarVar);
    window.addEventListener("keydown", this.onKey);
    boot();
    /* 进 web 就检测一次更新（不阻塞首屏、失败静默）。有更新时
       toast 提示一次 + 侧栏「配置」上留一个圆点，直到更新完/再检测为最新。 */
    autoCheckUpdates();
    if (S.page === "console") loadTools();
    if (S.page === "settings") loadThresholds();
    /* 首帧落位不带动画（不走 hashchange 分支） */
    nextTick(function () {
      syncNavInd(false);
    });
  },
  template:
    '<div class="shell">' +
    /* 侧栏玻璃的背景层（2026-10-20，主人选 A 档：轨道位置不动，只换材质）。
       🔴 它必须是 .sidebar 的**兄弟**且 z-index 更低：backdrop-filter 只采样
          「元素自己之外、绘制顺序在前」的内容，做成 .sidebar 的子元素会被它
          自己的 background 挡住，折射就完全失效（liquid-glass.md 约束 1 的同一条）。
       宽度跟 --sidebar-w 走，抽屉态（0px）自动消失。 */
    '  <div class="rail-glass-bg" aria-hidden="true"></div>' +
    '  <aside class="sidebar" :class="{open: S.sidebarOpen}">' +
    /* 拖尾残影 + 指示条是 .sidebar 的**头两个**子元素（绝对定位 ⇒ 不参与 flex
       布局，也不计入 .sidebar 的 gap）。⚠️ 顺序不能反：同为绝对定位、同为
       z-index:auto，后写的兄弟盖在上面 —— 残影必须在前，才会被不透明的主条压住；
       静止时两者矩形完全相同，残影自动隐没，不需要任何「清尾巴」的 JS。
       与配置页左栏共用同一份定义，见 css/6-anim.css §17l。 */
    '    <span class="nav-ind-trail" aria-hidden="true"></span>' +
    '    <span class="nav-ind" aria-hidden="true"></span>' +
    '    <div class="brand">' +
    '      <span class="brand-mark" v-html="svg(\'layers\')"></span>' +
    '      <span class="brand-text"><span class="brand-name">记忆库控制台</span>' +
    "        <span class=\"brand-sub\">ai-memory · v{{ S.about.resolved.version || '1.0.0' }}</span></span>" +
    "    </div>" +
    '    <div class="nav-sec">导航</div>' +
    '    <nav class="nav">' +
    '      <button class="nav-item" v-for="n in nav" :key="n.id" :class="{active: S.page===n.id}"' +
    "        :title=\"n.label + '（' + n.key + '）'\" :aria-label=\"n.label\" @click=\"go(n.id)\">" +
    '        <span class="nav-icon" v-html="svg(n.icon)"></span>' +
    '        <span class="nav-label">{{ n.label }}</span>' +
    '        <span class="nav-kbd">{{ n.key }}</span>' +
    '        <span class="nav-dot" v-if="n.id===\'settings\' && pendingCount()"' +
    "          :title=\"'有 ' + pendingCount() + ' 个目标可更新'\"></span></button>" +
    "    </nav>" +
    '    <div class="sidebar-foot">' +
    '      <div class="foot-line"><span>端点</span><b class="mono">{{ endpointShort }}</b></div>' +
    '      <div class="foot-line mt-sm"><span>工具</span><b>{{ S.health.tools_count }}</b></div>' +
    '      <div class="foot-line mt-sm"><span>状态</span>' +
    "        <b :style=\"{color: S.health.ok ? 'var(--ok)' : 'var(--err)'}\">{{ S.health.ok ? '在线' : '离线' }}</b></div>" +
    '      <div class="foot-line mt-sm" v-if="authWho"><span>账号</span>' +
    '        <b class="mono" style="margin-left:auto">{{ authWho }}</b></div>' +
    "    </div>" +
    /* 注销按钮（2026-10-23，主人令「web 添加个注销按钮取消登录」→「放到左栏下面」）。
       位置：.sidebar-foot 之后、侧栏最底。
       · ≥900px 左栏是 64px 窄图标条（.sidebar-foot 整体 display:none）⇒ 这里是
         一个 36×38 的纯图标按钮，语义靠 :title / aria-label，与 .nav-item 同口径；
       · ≤899px 左栏是 272px 抽屉（footer 恢复显示）⇒ .lo-label 恢复，变成
         图标+文字的整行按钮，紧接在 footer 下方。
       margin-top:auto 只在桌面档给 —— 抽屉档 footer 自己已是 auto，两个 auto 会
       平分剩余空间、把 footer 悬在半空。 */
    '    <div class="side-logout" v-if="canLogout">' +
    "      <button class=\"lo-btn\" @click=\"logout\" title=\"注销并返回登录框\" aria-label=\"注销\">" +
    "        <span v-html=\"svg('logout')\"></span>" +
    '        <span class="lo-label">注销</span></button>' +
    "    </div>" +
    "  </aside>" +
    /* 悬停跟随透镜（2026-10-20，主人问「悬停跟随呢？」）：
       🔴 必须是 .sidebar 的**兄弟**且 z-index 高一级 —— 这样它的 backdrop-filter
          采样到的是侧栏的**合成结果**（图标 / 指示条 / 文字），压在下面被边圈弯折；
          做成 .sidebar 的子元素就只采到侧栏自己那层半透明底，折射等于没有。
       pointer-events:none 保证导航点击照常穿透。见 core/lens.js 顶部说明。 */
    '  <div class="rail-lens" aria-hidden="true"><div class="rail-lens-glass"></div></div>' +
    '  <div class="scrim" v-if="S.sidebarOpen" @click="S.sidebarOpen=false"></div>' +
    '  <div class="shell-main">' +
    '    <header class="topbar">' +
    '      <button class="icon-btn" @click="S.sidebarOpen=!S.sidebarOpen" :aria-label="\'菜单\'">' +
    '        <span v-html="svg(\'menu\')" style="width:20px;height:20px;display:block"></span></button>' +
    '      <div class="topbar-titles">' +
    '        <div class="topbar-title">记忆库控制台' +
    '          <span class="tb-ver mono">v{{ S.about.resolved.version || "1.0.0" }}</span></div>' +
    '        <div class="topbar-sub">{{ pageSub }}</div></div>' +
    '      <div class="spacer"></div>' +
    "      <div class=\"conn\" :class=\"S.health.ok ? 'ok' : (S.health.checking ? '' : 'err')\" " +
    '           @click="loadHealth(); loadTools(true)" :title="S.health.endpoint">' +
    "        <span class=\"dot\" :class=\"S.health.checking ? 'idle' : (S.health.ok ? 'ok' : 'err')\"></span>" +
    "        <span class=\"hide-mobile\">{{ S.health.checking ? '检查中…' : (S.health.ok ? '已连接' : '未连接') }}</span>" +
    '        <span class="mono small faint hide-mobile" v-if="S.health.latency_ms!=null">{{ S.health.latency_ms }}ms</span></div>' +
    /* 主题：三按钮组（浅色 / 跟随系统 / 深色）已由单个「日夜天空开关」取代
       （2026-10-20，移植 WPF WpfGorgeousThemeSwitch）。三态里的「跟随系统」
       改由右键触发，见 components/ThemeSwitch.js 顶部的取舍说明。 */
    '      <theme-switch></theme-switch>' +
    "    </header>" +
    '    <nav class="crumbs" aria-label="面包屑">' +
    '      <template v-for="(c,i) in crumbs" :key="i">' +
    '        <span class="crumb-sep" v-if="i">›</span>' +
    '        <span class="crumb" :class="{last: i===crumbs.length-1}">{{ c }}</span>' +
    "      </template>" +
    "    </nav>" +
    "    <main class=\"main\" :style=\"{'--pdir': S.pageDir}\">" +
    '      <div class="banner err" v-if="S.authRequired" style="align-items:center">' +
    "        <span v-html=\"svg('key')\"></span><div><b>需要登录</b>" +
    '        <div class="small">请先在下方完成登录，或改用访问令牌。</div></div></div>' +
    /* appear：Vue 的 transition 默认不播首帧，而这里撤掉了 .page 自带的
       pageIn animation（改用 §17c 的过渡类），不加 appear 首屏就没有入场。 */
    '      <transition name="page" mode="out-in" appear>' +
    "      <dashboard v-if=\"S.page==='dashboard'\"></dashboard>" +
    "      <console-page v-else-if=\"S.page==='console' && canSee('console')\"></console-page>" +
    "      <library-page v-else-if=\"S.page==='library'\"></library-page>" +
    /* 多一道 canSee：watch 的重定向要等一拍才生效，这一帧不该把整页画出来
       （哪怕只有一帧，也不该让只读账号看见「调试台」「账号」这些字样）。 */
    "      <access-page v-else-if=\"S.page==='access' && canSee('access')\"></access-page>" +
    "      <settings-page v-else-if=\"S.page==='settings'\"></settings-page>" +
    '      </transition>' +
    "    </main>" +
    '    <footer class="statusbar">' +
    '      <div class="sb-grp">' +
    "        <span class=\"dot\" :class=\"S.health.checking ? 'idle' : (S.health.ok ? 'ok' : 'err')\"></span>" +
    "        <span>{{ S.health.checking ? '正在检查' : (S.health.ok ? '已连接' : '未连接') }}</span>" +
    '        <span class="mono" v-if="S.health.latency_ms!=null">{{ S.health.latency_ms }} ms</span></div>' +
    '      <span class="spacer"></span>' +
    '      <div class="sb-grp">' +
    '        <span>条目 <b>{{ fmtNum(numStat.total || 0) }}</b></span>' +
    '        <span>孤立 <b>{{ fmtNum(numStat.orphans || 0) }}</b></span></div>' +
    '    </footer>' +
    "  </div>" +
    '  <transition name="fade">' +
    '    <div class="modal-mask" v-if="S.authRequired">' +
    '      <div class="modal" style="max-width:420px">' +
    '        <div class="modal-head"><h3>{{ authTitle }}</h3></div>' +
    '        <div class="modal-body">' +
    '          <div class="field" style="margin:0 0 12px" v-if="isPasswordMode">' +
    '            <label class="label">用户名</label>' +
    '            <input class="input mono" v-model="S.loginUser" autocomplete="username" @keyup.enter="submitLogin"></div>' +
    '          <div class="field" style="margin:0" v-if="isPasswordMode">' +
    '            <label class="label">口令</label>' +
    '            <input class="input mono" type="password" v-model="S.loginPassword" autocomplete="current-password" @keyup.enter="submitLogin"></div>' +
    '          <div class="field" style="margin:0" v-if="!isPasswordMode">' +
    '            <input class="input mono" type="password" v-model="S.tokenInput" placeholder="Bearer token" @keyup.enter="submitToken"></div>' +
    '          <div class="small" v-if="S.loginError" style="color:var(--err);margin-top:10px">{{ S.loginError }}</div>' +
    '        </div>' +
    '        <div class="modal-foot">' +
    '          <a class="small" href="#" style="margin-right:auto" v-if="S.loginEnabled" @click.prevent="toggleAuthMode">{{ authSwitchLabel }}</a>' +
    '          <button class="btn btn-primary" :disabled="S.loginBusy" @click="isPasswordMode ? submitLogin() : submitToken()">{{ authSubmitLabel }}</button>' +
    "        </div>" +
    "      </div></div>" +
    "  </transition>" +
    '  <transition name="fade">' +
    '    <div class="modal-mask" v-if="S.confirm.open" @click.self="closeConfirm">' +
    '      <div class="modal">' +
    '        <div class="modal-head"><h3>{{ S.confirm.title }}</h3><p>{{ S.confirm.body }}</p></div>' +
    '        <div class="modal-body" v-if="S.confirm.phrase">' +
    '          <div class="field" style="margin:0"><label class="label">请输入 <code>{{ S.confirm.phrase }}</code> 以确认</label>' +
    '            <input class="input mono" v-model="S.confirm.typed" :placeholder="S.confirm.phrase" @keyup.enter="doConfirm"></div></div>' +
    '        <div class="modal-foot">' +
    '          <button class="btn" @click="closeConfirm">取消</button>' +
    "          <button class=\"btn\" :class=\"S.confirm.danger ? 'btn-danger' : 'btn-primary'\" " +
    '            :disabled="S.confirm.phrase && S.confirm.typed.trim() !== S.confirm.phrase" @click="doConfirm">确认</button>' +
    "        </div></div></div>" +
    "  </transition>" +
    '  <transition-group name="toast" tag="div" class="toast-wrap">' +
    '    <div class="toast" v-for="t in S.toasts" :key="t.id" :class="t.kind">' +
    '      <span class="grow"><span class="toast-title">{{ t.title }}</span>' +
    '        <span class="toast-body" v-if="t.body">{{ t.body }}</span></span>' +
    '      <button class="toast-close" @click="dismiss(t.id)">×</button></div>' +
    "  </transition-group>" +
    /* 命令面板：挂在 Root 根部（而不是 Dock 内部）—— 它是全屏浮层，
       需要脱离顶栏的 backdrop-filter 上下文，否则会被裁在顶栏盒子里。 */
    "  <command-palette></command-palette>" +
    "</div>",
};

export { NAV, PAGE_TITLES, PAGE_SUBS, fixSidebarVar, Root };
