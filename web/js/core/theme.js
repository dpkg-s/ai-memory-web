/* 主题：深/浅色解析与落盘
 * index.html 的内联脚本已做过一次预设（防 FOUC），
 * 这里负责运行期切换与监听系统主题变化。
 *
 * ======================================================================
 * 2026-10-22 · 方案 A″「底片挖孔」—— 扩散与开关真正同时
 *
 * 演进（同一天五轮，结论都留在这里，别再走回头路）：
 *   1.0 直接改 data-theme ⇒ 页面一帧换完，与开关 1.5s 天空渐变反差太大（生硬）。
 *   2.0 浏览器 View Transition 圆形扩散，与开关同时起跑 ⇒ 扩散期间整页是**静态
 *       快照**，开关被冻在里面，揭示瞬间从第 0 帧跳到第 0.55s 帧（跳帧）。
 *   2.1 扩散优先、timeline 暂停等 ⇒ 页面先换完、开关后补演（错位 671ms）。
 *   3.0 撤 VT，整页渐变与开关单时钟同帧 ⇒ 真同步，但没有圆形扩散。
 *   4.0 顺序化（开关先演 0.45s、再扩散 0.45s）⇒ 两段都完整，但不是同时。
 *   5.0 自己实现圆形揭示，绕开 VT 的快照冻结 ⇒ 扩散与开关真正同时。
 *   6.0 本轮（主人 2026-10-23 定调）：5.0 两个方向都是「新主题从开关圆心长出来」，
 *       于是夜→昼看到的是**浅色铺开**，不是**黑色收回去**。要的是方向明确的
 *       「黑色扩出去 / 黑色缩回来」，所以两向的遮罩形式必须互换（见下 §方向）。
 *
 * 🔴 §方向（两向不是同一个渐变，这是本轮的核心）：
 *      toDark （进夜）  黑 = 新深色页面，在**实时层**：
 *                       mask 圆心透明、圆外不透明 ⇒ 孔从 0 扩到 rMax，
 *                       深色从开关扩出去覆盖旧浅色底片。
 *      toLight（回昼）  黑 = 旧深色底片，在**底片层**：
 *                       mask 圆心不透明、圆外透明 ⇒ 黑盘从 rMax 缩到 0，
 *                       黑色收回到开关处，浅色内容从四周涌进来。
 *      两向都在 t=0 让「旧外观」完整在场，所以都没有首帧跳变。
 *
 * 🔴 回昼期间开关必须浮在黑盘之上（html.vt-lift + liftSwitch 搬家）：黑盘盖满
 *    全屏时，开关若被压在静态快照里就会「冻住不动」，看不到「变成太阳」。
 *    ⚠️ 只抬开关、**不抬顶栏** —— 顶栏要跟着黑盘一起收（主人 2026-10-23 定：
 *    「顶栏提前白了，没有被蒙版覆盖到」）。而单给 .tsw-wrap 写 z-index 抬不动
 *    （sticky 祖先必然创建层叠上下文，见 liftSwitch 注释），所以回昼时把这个
 *    节点搬到 body 顶层。进夜**不搬**：孔从开关内生出来，开关本来就随后露出。
 *    ⚠️ 这套「只抬开关」的层叠安排在降级路径（无底片）下不需要，也不执行。
 *
 * 🔴 原理（底片挖孔）：
 *   1) 点击瞬间先把**当前（旧主题）页面拍成一张活的 DOM 底片**：克隆 body 子树，
 *      把旧主题的 CSS 变量逐个拷成行内样式（否则克隆体会继承刚换的新变量），
 *      同步各滚动容器的 scrollTop，canvas 用 drawImage 补像素；
 *   2) 底片以 position:fixed 盖满视口，用 radial-gradient 做 mask，在开关圆心处
 *      留一个半径 --vt-r 的**透明孔**；--vt-r 从 0 长到视口外接圆 ⇒ 圆孔从小扩大，
 *      透出底下的实时页面；
 *   3) 底片下面是**活的**页面 —— 主题已在新值、开关的 GSAP timeline 从第 0 帧起跑，
 *      所以「扩散扫过哪里，那里的开关就在演」。
 *
 * 🔴 为什么不用 document.startViewTransition：VT 的快照是**位图且冻结**，页面内元素
 *   在那段时间不可见、不可动。想让开关与扩散同时，就必须让底层保持实时渲染，
 *   而「旧外观」只能由我们自己造一层 —— 这就是底片。
 *
 * 🔴 首屏那次一律不演；prefers-reduced-motion 也不演。
 * ==================================================================== */
import { S } from "./store.js";
import { reduced } from "./anim.js";

/* 版本标记（2026-10-26 加）：排查「改了但看不见」时，在控制台敲
   window.__VT_VER 就知道当前页面跑的是哪一份代码 —— 比对着文件大小猜可靠。
   改动本文件里的动画逻辑请顺手改这里。 */
if (typeof window !== "undefined") window.__VT_VER = "2026-10-26-h";

var _booted = false;
var _lead = null; /* 底片挖孔动画的 rAF 句柄 */
var _hold = null; /* 底片移除 / 降级摘类的定时器 */
var _pending = null; /* 已备好但还没开孔的底片，等开关的第一帧 */

/* 圆孔扩张时长。与开关滑块首段（0.45s）等长：一圈扫完，开关也刚落到月亮位。 */
var REVEAL_MS = 450;
/* 降级路径（底片造不出来）的整页渐变时长。 */
var FADE_MS = 450;

/* 🔴 已停用（2026-10-26 第七轮第二轮，主人定案）：
 *    回昼黑盘的「提亮版」变量表 PLATE_LIFT 已删除 —— 它让回昼的盘内卡片
 *    （--surface #1f2328 / --surface-3 #2d333a）比进夜孔内的真实深色页面
 *    （#101112）亮 15~30 个灰阶，两次圆动画的「黑」一眼就能看出不一样
 *    （主人：「那个圆的两次动画颜色不对 —— 回昼比进夜偏灰」）。
 *
 *    历史（2026-10-23 为什么加它）：深色主题面与面色差压到 1.02~1.05，
 *    黑盘里 .card #101112 与页底 #0b0c0d 只差 5 个灰阶，缩小时「内容全在、
 *    就是不可辨」，所以要「看得见旧页面缩回去」就得拉开面阶。
 *
 *    ⇒ 两条诉求直接互斥：**颜色一致** 与 **盘内可辨** 只能二选一。
 *      主人 2026-10-26 选前者，故整表停用。若日后要回可辨性，别再加全局提亮，
 *      改为只提亮描边（--border）或加一层极淡的内阴影 —— 那两项对整体亮度
 *      影响小到两向对比看不出来。 */

function systemDark() {
  return (
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

/* 圆心到视口四角的最远距离 + 8px：任何视口比例都能把整页盖完。 */
function radiusToCorner(x, y) {
  var w = window.innerWidth || 1;
  var h = window.innerHeight || 1;
  return Math.hypot(Math.max(x, w - x), Math.max(y, h - y)) + 8;
}

/* 没拿到点击坐标（命令面板、跟随系统）时退化成「当前焦点元素中心」，
   再不行就用视口顶部中心 —— 顶栏附近，视觉上仍像从控件处扩散。 */
function resolveOrigin(origin) {
  if (origin && isFinite(origin.x) && isFinite(origin.y)) return origin;
  var a = document.activeElement;
  if (a && a !== document.body && a.getBoundingClientRect) {
    var r = a.getBoundingClientRect();
    if (r.width && r.height) {
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }
  }
  return { x: (window.innerWidth || 0) / 2, y: 40 };
}

/* 旧主题下的 token 名。**不能**靠 getComputedStyle 遍历拿：实现上自定义属性
   通常不在枚举列表里（实测一个都取不到），克隆体于是继承到刚换上的新值 ——
   底片会变成新主题的样子，圆孔挖开的瞬间就看不出任何变化。
   所以从样式表里把 `html[data-theme=...]` 规则声明过的 --* 名字抠出来。 */
function tokenNames() {
  var seen = {};
  var out = [];
  function walk(rules) {
    if (!rules) return;
    for (var i = 0; i < rules.length; i++) {
      var r = rules[i];
      /* 🔴 顺序不能反（2026-10-23 实测踩到）：CSS 嵌套支持之后，**CSSStyleRule
         自己也有 cssRules**（空 CSSRuleList 也是 truthy）。上一版先判
         `if (r.cssRules) { walk(); continue; }`，于是每一条样式规则都被当成
         容器递归进一个空列表，selectorText 分支一次都没执行 ⇒ 拿到 0 个变量名，
         底片全靠继承新主题的值 —— 进夜时是一张「浅底 + 新主题浅字」的糊图。
         先取自身声明，再按需递归子规则。 */
      if (r.selectorText && r.selectorText.indexOf("data-theme") >= 0) {
        var st = r.style;
        if (st) {
          for (var k = 0; k < st.length; k++) {
            var p = st[k];
            if (p.slice(0, 2) === "--" && !seen[p]) {
              seen[p] = 1;
              out.push(p);
            }
          }
        }
      }
      if (r.cssRules && r.cssRules.length) walk(r.cssRules);
    }
  }
  for (var s = 0; s < document.styleSheets.length; s++) {
    try {
      walk(document.styleSheets[s].cssRules);
    } catch (e) {
      /* 跨域样式表读不到 cssRules，跳过 */
    }
  }
  return out;
}

/* 把当前 :root 上生效的自定义属性一次性读出来 —— 必须在 commit 之前读，
   否则拿到的是新主题的值。 */
function snapshotVars() {
  var cs = getComputedStyle(document.documentElement);
  var names = tokenNames();
  var out = [];
  var i;
  for (i = 0; i < names.length; i++) {
    out.push([names[i], cs.getPropertyValue(names[i])]);
  }
  /* 兜底：样式表读不到时，再试枚举（某些实现能列出）。 */
  if (!out.length) {
    for (i = 0; i < cs.length; i++) {
      var p = cs[i];
      if (p && p.charCodeAt(0) === 45 && p.charCodeAt(1) === 45) {
        out.push([p, cs.getPropertyValue(p)]);
      }
    }
  }
  return out;
}

function solid(c) {
  return c && c !== "rgba(0, 0, 0, 0)" && c !== "transparent" ? c : null;
}

/* 造底片：克隆 body 子树 + 旧主题变量 + 滚动位置 + canvas 像素。 */
function buildPlate(vars) {
  var old = document.querySelector(".vt-plate");
  if (old && old.parentNode) old.parentNode.removeChild(old);

  var wrap = document.createElement("div");
  wrap.className = "vt-plate";
  wrap.setAttribute("aria-hidden", "true");
  try {
    wrap.inert = true;
  } catch (e) {
    /* 老浏览器没有 inert */
  }

  for (var i = 0; i < vars.length; i++) {
    wrap.style.setProperty(vars[i][0], vars[i][1]);
  }
  wrap.style.setProperty("--vt-r", "0px");

  var inner = document.createElement("div");
  inner.className = "vt-plate-inner";
  /* html 与 body 的底色要各拷一层：app 可能只给 body 上色。 */
  var hbg = solid(getComputedStyle(document.documentElement).backgroundColor);
  var bbg = solid(getComputedStyle(document.body).backgroundColor);
  if (hbg) wrap.style.background = hbg;
  if (bbg) inner.style.background = bbg;

  /* 先在**未插入**时取一份节点表，索引才能与克隆体一一对应。 */
  var origin = document.body.querySelectorAll("*");
  var kids = document.body.children;
  for (var k = 0; k < kids.length; k++) {
    var tag = kids[k].tagName;
    if (tag === "SCRIPT") continue;
    inner.appendChild(kids[k].cloneNode(true));
  }
  wrap.appendChild(inner);

  var copy = inner.querySelectorAll("*");
  var n = Math.min(origin.length, copy.length);
  for (var j = 0; j < n; j++) {
    var s = origin[j].scrollTop;
    var sl = origin[j].scrollLeft;
    if (s) copy[j].scrollTop = s;
    if (sl) copy[j].scrollLeft = sl;
  }

  var ca = document.body.querySelectorAll("canvas");
  var cb = inner.querySelectorAll("canvas");
  for (var c = 0; c < Math.min(ca.length, cb.length); c++) {
    try {
      cb[c].getContext("2d").drawImage(ca[c], 0, 0);
    } catch (e) {
      /* 跨域/被污染的 canvas 就算了 */
    }
  }

  document.body.appendChild(wrap);
  return wrap;
}

/* 造「羽化边」：一块**纯色**全屏层，只负责边缘那圈柔化。
 *
 * 🔴 为什么单独一层（2026-10-26 重写的核心）：
 *   旧实现把羽化写进底片自己的 mask —— 一条 radial-gradient 从 r-90 淡到 r。
 *   可底片内部本来就有好几种颜色（--bg #0b0c0d、提亮后的 --surface #1f2328、
 *   边框 #454d56、卡片文字……）。alpha 渐变意味着「同一圈里不同像素的 alpha
 *   相同、但底色不同」，与下层新页面混合后得到的灰各不相同 ⇒ 边缘一圈花掉，
 *   主人看到的就是「蒙版颜色不统一」。
 *
 *   拆开之后：内容层（.vt-plate）用**硬边**裁剪，只负责「看得见什么」；
 *   这一层纯色只负责「边缘怎么淡出」。羽化带里只是**一种颜色**在降 alpha，
 *   任何位置混合出来的灰都一致，物理上不可能斑驳。
 *
 *   颜色取**旧主题的 --bg**：黑盘主体是它、进夜底片主体也是它，所以内容层与
 *   羽化带在交界处同色，看不出接缝（内容层半径正好比它小一个 feather）。
 *
 * 边界性质（两向都验算过，别再改回去）：
 *   · r = 0（回昼终态）：三个停靠点全落在 0 ⇒ 径向渐变用**末色**填充 = 透明，
 *     整层消失，正确。
 *   · r = 0（进夜首帧）：末色 #000 ⇒ 整层不透明，正好接住「孔还没开」的瞬间，
 *     而它压在内容层**下面**，不遮挡孔内要露出的新页面。 */
function buildHalo(vars) {
  var old = document.querySelector(".vt-halo");
  if (old && old.parentNode) old.parentNode.removeChild(old);

  var el = document.createElement("div");
  el.className = "vt-halo";
  el.setAttribute("aria-hidden", "true");

  var bg = null;
  for (var i = 0; i < vars.length; i++) {
    if (vars[i][0] === "--bg") {
      bg = solid(vars[i][1]);
      break;
    }
  }
  /* 拿不到 --bg 就按方向兜底：回昼的盘是深色、进夜的底片是浅色。 */
  el.style.background = bg || "#0b0c0d";
  el.style.setProperty("--vt-r", "0px");
  /* 安全默认：任何异常路径下这一层都不该以「不透明」状态留在页面上。
     真正的初值由 applyTheme 按方向写入（回昼 1 / 进夜 0）。 */
  el.style.opacity = "0";

  document.body.appendChild(el);
  return el;
}

function killPlate() {
  var old = document.querySelector(".vt-plate");
  if (old && old.parentNode) old.parentNode.removeChild(old);
  var halo = document.querySelector(".vt-halo");
  if (halo && halo.parentNode) halo.parentNode.removeChild(halo);
}

/* ---- 回昼期间把开关「搬」到 body 顶层（2026-10-26 第七轮）----------------
 *
 * 症状：暗切亮（toLight）时，开关的展开/切换动画在画面上完全看不到 —— 黑盘
 *       收完的那一瞬间，开关已经是太阳了。亮切暗（toDark）却一切正常。
 *
 * 根因（实测，不是猜）：`.topbar` 是 `position: sticky`，而 CSS 规范规定
 *   **sticky 元素无条件创建层叠上下文**（与 z-index 是否 auto 无关）。
 *   于是 `html.vt-lift .tsw-wrap { z-index: 2147483001 }` 只在这个上下文**内部**
 *   比较，对挂在 body 上的 `.vt-plate`(2147483000) 毫无意义 —— 整个 topbar
 *   （含开关）仍被黑盘压住。画面上看到的是底片里那张**静止的窄开关**；
 *   实时开关在黑盘下面把 0.45s 演完，等黑盘收到 0 才露脸，于是「没有动画」。
 *
 * 为什么不用「topbar 改 position: relative」这个一行方案：sticky 在滚动时
 *   相对视口固定，改成 relative 后顶栏会跳回文档顶部；黑盘撤掉那一刻顶栏
 *   会从上方向下「掉」回吸顶位，是肉眼可见的跳变。
 *
 * 为什么是搬节点而不是换定位：层叠上下文的父子关系由 **DOM 祖先**决定，
 *   就地改 position:fixed / 加 transform / 提 z-index 都逃不出 topbar。
 *   把节点直接挂到 body 之后，它的层叠上下文就是 root，z-index 才真正生效。
 *
 * 时序约束：
 *   · 必须在 buildPlate **之后**搬 —— 底片克隆的是 body.children，先搬会让
 *     克隆体里多出一份带 2147483001 的开关（双影）。
 *   · 必须在 startReveal 的收尾里与 killPlate **同一个任务**搬回去 ——
 *     否则会有一帧「开关在 body 上、顶栏里空着」可被看见。
 *   · 只写行内样式，原 style 属性整体存下再还原（wrap 平时没有 style）。
 */
var _lifted = null;

function liftSwitch() {
  if (_lifted) return;
  var wrap = document.querySelector(".tsw-wrap");
  if (!wrap || !wrap.parentNode || wrap.parentNode === document.body) return;
  var r = wrap.getBoundingClientRect();
  _lifted = {
    el: wrap,
    parent: wrap.parentNode,
    next: wrap.nextSibling,
    style: wrap.getAttribute("style"),
  };
  /* 屏幕坐标原样钉住：搬家前后视觉位置必须一模一样，否则开关会「跳」一下。 */
  wrap.style.position = "fixed";
  wrap.style.left = Math.round(r.left) + "px";
  wrap.style.top = Math.round(r.top) + "px";
  wrap.style.margin = "0";
  wrap.style.zIndex = "2147483001";
  document.body.appendChild(wrap);
}

function unliftSwitch() {
  if (!_lifted) return;
  var s = _lifted;
  _lifted = null;
  /* 先还原 style，再搬回原位：两步同一个任务，浏览器只算一次布局，
     不存在「fixed 的和流内的开关同时存在」的中间帧。 */
  if (s.style === null) s.el.removeAttribute("style");
  else s.el.setAttribute("style", s.style);
  if (s.next && s.next.parentNode === s.parent) {
    s.parent.insertBefore(s.el, s.next);
  } else {
    s.parent.appendChild(s.el);
  }
}

/* 开孔 / 收盘。由 ThemeSwitch 在自己的 timeline 建好之后调用（见其 apply()），
 * 这样「遮罩开始动」与「滑块开始移动」落在同一帧。
 * 为什么要等它：克隆整棵 body 并画一帧底片要几十到上百毫秒 —— 这段开销发生在
 * commit 之前，如果这里立刻开演，孔会比滑块早走 0.1s 左右，又变成「页面先动」。
 * 没人调用时（拿不到 gsap / 组件没挂）260ms 后自己兜底开始，绝不卡死。 */
function startReveal() {
  if (!_pending) return;
  var p = _pending;
  _pending = null;
  if (p.timer) clearTimeout(p.timer);
  grow(p.wrap, p.halo, p.x, p.y, p.dir, function () {
    killPlate();
    /* 黑盘一撤就把开关搬回顶栏 —— 同一个任务内完成，不会出现
       「开关还挂在 body 上、顶栏里空着」的可见中间帧。 */
    unliftSwitch();
    /* 顶栏抬升只服务于「回昼期间开关要实时演」，底片一撤就得放下，
       否则 z-index 2147483001 会长期悬在所有弹层之上。 */
    document.documentElement.classList.remove("vt-lift");
  });
}

/* 圆孔 0 → 视口外接圆（进夜），或黑盘 外接圆 → 0（回昼）。
   用 rAF 逐帧写 --vt-r：mask 每帧都得重算，CSS 过渡也省不下这笔重绘，
   rAF 版本还不依赖 @property。
   2026-10-26：半径要同时写给**内容层**和**羽化层**，两层的停靠点由 CSS 用
   var(--vt-feather) 各自算，JS 只负责推进同一个 r —— 这才是两向严格同帧的保证。 */
function grow(wrap, halo, x, y, dir, done) {
  var rMax = radiusToCorner(x, y);
  /* 羽化宽度以 CSS 的 --vt-feather 为唯一事实源（6-anim.css 里定义），
     读一次就够 —— 动画期间没人会改它。 */
  var feather = 90;
  try {
    var fv = parseFloat(
      getComputedStyle(wrap).getPropertyValue("--vt-feather"),
    );
    if (isFinite(fv) && fv > 0) feather = fv;
  } catch (e) {
    /* 读不到就用 90 与 CSS 默认值对齐 */
  }

  /* 🔴 2026-10-26「提前收纳」的真因与兜底：
   *   这条推进循环靠 rAF，而 rAF 在**窗口被遮挡 / 标签页切后台**时会停。
   *   底片于是冻在半途，可 ThemeSwitch 的摘锁是 setTimeout —— 定时器照跑，
   *   到点照样把 data-anim 摘掉、胶囊照样收窄。
   *   结果就是主人截图里那一幕：底片还挂在半屏，开关已经收回去了。
   *   所以这里补两道**不依赖 rAF** 的收尾：
   *     · 看门狗定时器：超过 REVEAL_MS + 500ms 无论画到哪，直接落终值并撤片；
   *     · visibilitychange：一进后台立刻落终值（没人看，不需要继续演）。
   *   finish() 做了幂等，rAF 正常收尾、看门狗、可见性三路都走它，不会重复。 */
  var finished = false;
  var wd = null;
  var t0 = performance.now();

  function finish(force) {
    if (finished) return;
    finished = true;
    if (_lead) {
      cancelAnimationFrame(_lead);
      _lead = null;
    }
    if (wd) {
      clearTimeout(wd);
      wd = null;
    }
    document.removeEventListener("visibilitychange", onVis);
    if (force) {
      /* 强制落终值：回昼收到 0（黑盘消失），进夜放到 rMax（孔已开满）。 */
      var rend = dir === "toLight" ? "0px" : Math.round(rMax) + "px";
      wrap.style.setProperty("--vt-r", rend);
      if (halo) {
        halo.style.setProperty("--vt-r", rend);
        halo.style.opacity = dir === "toLight" ? "0" : "1";
      }
    }
    if (done) done();
  }

  function onVis() {
    if (document.hidden) finish(true);
  }

  document.addEventListener("visibilitychange", onVis);
  wd = setTimeout(function () {
    finish(true);
  }, REVEAL_MS + 500);

  function step() {
    var p = (performance.now() - t0) / REVEAL_MS;
    if (p >= 1) p = 1;
    /* cubic-bezier(.65,0,.35,1) 的近似 —— 与 --ease-in-out 同族 */
    var e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
    /* toLight 走的是同一条缓动曲线的**反演**：黑盘收得「先慢后快再慢」，
       与进夜时孔扩出去的手感镜像对称。 */
    var r = dir === "toLight" ? rMax * (1 - e) : rMax * e;
    var px = Math.round(r) + "px";
    wrap.style.setProperty("--vt-r", px);
    if (halo) {
      halo.style.setProperty("--vt-r", px);
      /* 回昼半径小于一个羽化宽度时，内容层按设计已经整个透明（末色透明），
         只剩羽化层那团纯色 —— 不淡出就会看到「一小块暗斑贴在开关旁」。
         进夜反过来：r 很小时羽化层正是用来填满孔的那一圈，必须保持不透明，
         所以这里按方向分开，不能统一成 r/feather。 */
      var a = dir === "toLight" ? r / feather : 1;
      if (a > 1) a = 1;
      halo.style.opacity = a.toFixed(3);
    }
    if (p < 1) {
      _lead = requestAnimationFrame(step);
    } else {
      _lead = null;
      finish(false);
    }
  }
  _lead = requestAnimationFrame(step);
}

function applyTheme(pref, opts) {
  if (opts === true) opts = { silent: true };
  opts = opts || {};
  var root = document.documentElement;
  var resolved = pref === "auto" ? (systemDark() ? "dark" : "light") : pref;

  function cancel() {
    if (_lead) {
      cancelAnimationFrame(_lead);
      _lead = null;
    }
    if (_pending) {
      if (_pending.timer) clearTimeout(_pending.timer);
      _pending = null;
    }
    if (_hold) {
      clearTimeout(_hold);
      _hold = null;
      root.classList.remove("theming");
    }
    killPlate();
    /* 被中断的那一次也要把开关搬回顶栏，否则它会永久留在 body 上（fixed）。 */
    unliftSwitch();
    root.classList.remove("vt-lift");
  }

  function commit() {
    root.setAttribute("data-theme", resolved);
    root.setAttribute("data-theme-pref", pref);
    try {
      localStorage.setItem("am.theme", pref);
    } catch (e) {
      /* 忽略 */
    }
  }

  var animate = _booted && !opts.silent && !reduced();
  _booted = true;

  if (!animate) {
    cancel();
    commit();
    return resolved;
  }

  /* 主题没变（例：已在跟随系统时再右键一次）：只落 pref，不演。 */
  if (resolved === root.getAttribute("data-theme")) {
    cancel();
    root.setAttribute("data-theme-pref", pref);
    try {
      localStorage.setItem("am.theme", pref);
    } catch (e) {
      /* 忽略 */
    }
    return resolved;
  }

  cancel();

  /* 方向要在 commit **之前**定：此刻 root 上还是旧主题，resolved 就是新主题。 */
  var dir = resolved === "dark" ? "toDark" : "toLight";

  var o = resolveOrigin(opts.origin);
  var rMax = radiusToCorner(o.x, o.y);
  root.style.setProperty("--vt-x", Math.round(o.x) + "px");
  root.style.setProperty("--vt-y", Math.round(o.y) + "px");

  /* 回昼：黑盘 t=0 就必须是「满屏」，否则第一帧会把旧深色整页闪出来。
     顶栏同时抬到黑盘之上（见文件头 §方向），开关才看得见「变成太阳」。 */
  if (dir === "toLight") root.classList.add("vt-lift");

  var wrap = null;
  var halo = null;
  try {
    /* 底片必须在 commit **之前**拍：它要的是旧主题的外观。
       变量只取一次，两层共用 —— 分两次取会在中间看到不一致的值。 */
    var vars = snapshotVars();
    /* 🔴 羽化层两向都要建（2026-10-26 第三次修正，之前只给回昼建是错的）。
     *
     *   曾经的想法：进夜的底片盖在孔**外**，下面的羽化层会被压住 ⇒ 建了白建。
     *   那个判断漏了一步 —— 只要把**底片的硬边整体往外让出一个 feather**
     *   （进夜落在 r + feather），羽化带 [r, r+feather] 就重新空出来了，
     *   层在下面又如何？那里没有底片挡着。
     *
     *   为什么必须这么改：进夜原先靠底片**自己**做 alpha 渐变，而底片里装的是
     *   整张旧页面的内容（白卡片、进度条、文字）。半透明一混，这些内容就跟着
     *   变成灰影透出来，看起来是一条发脏的带子 —— 主人说的「两个蒙版颜色不一样」。
     *   换成纯色羽化层后，带子里只有**一种颜色**在降 alpha，没有内容可糊。
     *
     *   于是两向结构完全对称，只差硬边让位的方向：
     *     回昼 底片在盘**内** → 硬边缩到 r - feather，羽化带在外侧；
     *     进夜 底片在孔**外** → 硬边放到 r + feather，羽化带在内侧。
     *   颜色只有一个来源：旧主题的 --bg。 */
    halo = buildHalo(vars);
    halo.setAttribute("data-vt-dir", dir);
    wrap = buildPlate(vars);
    if (wrap) {
      wrap.setAttribute("data-vt-dir", dir);
      /* 🔴 这里曾有「回昼把 PLATE_LIFT 逐条压到 .vt-plate 上」的一段，
         2026-10-26 已删 —— 它让回昼盘内的卡片比进夜孔内亮 15~30 个灰阶，
         两次圆动画的黑色不一致。原因与取舍见文件上方 PLATE_LIFT 的注释。 */
      /* 同一任务内写初始半径，浏览器不会渲染中间态 —— 不存在「先全露再收」的闪帧。
         羽化层必须写同一个初值：否则它停在 0，第一帧就会露出一圈
         与内容层不符的边。 */
      var r0 = dir === "toLight" ? Math.round(rMax) + "px" : "0px";
      wrap.style.setProperty("--vt-r", r0);
      if (halo) {
        halo.style.setProperty("--vt-r", r0);
        /* 两向的首帧都要求羽化层**不透明**：
             回昼 t=0 是满屏深色盘，羽化带是它的最外圈，缺一圈就是缺口；
             进夜 t=0 是满屏旧亮色，孔还没开，羽化带负责把那 90px 填满。 */
        halo.style.opacity = "1";
      }
    }
  } catch (e) {
    /* 任何一步失败都要连羽化层一起撤，否则会留一层纯色盖住整页。 */
    wrap = null;
    halo = null;
    killPlate();
  }

  commit();

  if (wrap) {
    /* 🔴 回昼必须把开关搬到 body 顶层（就在 buildPlate 之后、开演之前）：
       见 liftSwitch 的注释 —— sticky 顶栏的层叠上下文会把 z-index 锁死，
       不搬的话实时开关全程被黑盘压住，观感就是「切换动画没生效」。 */
    if (dir === "toLight") liftSwitch();
    /* 底片已就位，先不动遮罩 —— 交给 ThemeSwitch 的 timeline
       在自己的第一帧调用 startReveal()，两者才严格同帧。 */
    _pending = {
      wrap: wrap,
      halo: halo,
      x: o.x,
      y: o.y,
      dir: dir,
      /* 150 → 260ms（2026-10-26）：ThemeSwitch 改成「两次 rAF 后才起播」，
         正常路径下 onStart 大约在拍完底片 +2 帧处触发（底片构建就要几十~上百毫秒）。
         兜底若还设在 150ms，就可能抢在起播之前把孔先扩出去，又变成两条时钟。
         260 给足余量；真的没人调 startReveal（拿不到 gsap / 组件没挂）时它仍然兜得住。 */
      timer: setTimeout(startReveal, 260),
    };
  } else {
    /* 底片造不出来（极端 DOM / 内存不足）就退回整页渐变，别让切换失灵。
       降级路径没有黑盘，顶栏不必抬。 */
    root.classList.remove("vt-lift");
    root.classList.add("theming");
    _hold = setTimeout(function () {
      root.classList.remove("theming");
      _hold = null;
    }, FADE_MS + 60);
  }

  return resolved;
}

if (window.matchMedia) {
  try {
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", function () {
        /* 系统自己变的不演：用户没操作，突然一圈扩散会很突兀。 */
        if (S.themePref === "auto") {
          S.theme = applyTheme("auto", { silent: true });
        }
      });
  } catch (e) {
    /* 老浏览器 */
  }
}

export { systemDark, applyTheme, startReveal, REVEAL_MS };
