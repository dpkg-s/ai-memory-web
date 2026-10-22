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
 *   5.0 本轮：**自己实现圆形揭示**，绕开 VT 的快照冻结 ⇒ 扩散与开关真正同时。
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

var _booted = false;
var _lead = null; /* 底片挖孔动画的 rAF 句柄 */
var _hold = null; /* 底片移除 / 降级摘类的定时器 */
var _pending = null; /* 已备好但还没开孔的底片，等开关的第一帧 */

/* 圆孔扩张时长。与开关滑块首段（0.45s）等长：一圈扫完，开关也刚落到月亮位。 */
var REVEAL_MS = 450;
/* 降级路径（底片造不出来）的整页渐变时长。 */
var FADE_MS = 450;

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
      if (r.cssRules) {
        walk(r.cssRules);
        continue;
      }
      if (!r.selectorText || r.selectorText.indexOf("data-theme") < 0) continue;
      var st = r.style;
      if (!st) continue;
      for (var k = 0; k < st.length; k++) {
        var p = st[k];
        if (p.slice(0, 2) === "--" && !seen[p]) {
          seen[p] = 1;
          out.push(p);
        }
      }
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

function killPlate() {
  var old = document.querySelector(".vt-plate");
  if (old && old.parentNode) old.parentNode.removeChild(old);
}

/* 开孔。由 ThemeSwitch 在自己的 timeline 建好之后调用（见其 apply()），
 * 这样「圆孔开始扩大」与「滑块开始移动」落在同一帧。
 * 为什么要等它：克隆整棵 body 并画一帧底片要几十到上百毫秒 —— 这段开销发生在
 * commit 之前，如果这里立刻开孔，孔会比滑块早走 0.1s 左右，又变成「页面先动」。
 * 没人调用时（拿不到 gsap / 组件没挂）150ms 后自己兜底开始，绝不卡死。 */
function startReveal() {
  if (!_pending) return;
  var p = _pending;
  _pending = null;
  if (p.timer) clearTimeout(p.timer);
  grow(p.wrap, p.x, p.y, killPlate);
}

/* 圆孔 0 → 视口外接圆。用 rAF 逐帧写 --vt-r：
   mask 每帧都得重算，CSS 过渡也省不下这笔重绘，rAF 版本还不依赖 @property。 */
function grow(wrap, x, y, done) {
  var rMax = radiusToCorner(x, y);
  var t0 = performance.now();
  function step() {
    var p = (performance.now() - t0) / REVEAL_MS;
    if (p >= 1) p = 1;
    /* cubic-bezier(.65,0,.35,1) 的近似 —— 与 --ease-in-out 同族 */
    var e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
    wrap.style.setProperty("--vt-r", Math.round(rMax * e) + "px");
    if (p < 1) {
      _lead = requestAnimationFrame(step);
    } else {
      _lead = null;
      if (done) done();
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

  var o = resolveOrigin(opts.origin);
  root.style.setProperty("--vt-x", Math.round(o.x) + "px");
  root.style.setProperty("--vt-y", Math.round(o.y) + "px");

  var wrap = null;
  try {
    /* 底片必须在 commit **之前**拍：它要的是旧主题的外观。 */
    wrap = buildPlate(snapshotVars());
  } catch (e) {
    wrap = null;
  }

  commit();

  if (wrap) {
    /* 底片已就位（孔半径 0），先不开孔 —— 交给 ThemeSwitch 的 timeline
       在自己的第一帧调用 startReveal()，两者才严格同帧。 */
    _pending = {
      wrap: wrap,
      x: o.x,
      y: o.y,
      timer: setTimeout(startReveal, 150),
    };
  } else {
    /* 底片造不出来（极端 DOM / 内存不足）就退回整页渐变，别让切换失灵。 */
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
