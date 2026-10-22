/* 主题：深/浅色解析与落盘
 * index.html 的内联脚本已做过一次预设（防 FOUC），
 * 这里负责运行期切换与监听系统主题变化。
 *
 * ======================================================================
 * 2026-10-22 · 方案 A「圆形扩散」+ 三层错峰降级
 *
 * 旧行为：直接改 data-theme，CSS 变量瞬时重算 ⇒ 页面在一帧内换完；而开关自己
 * 要演 1.5s 天空渐变。控件演了一秒半、页面一帧换完，反差就是「生硬」的来源。
 *
 * 现在按能力择一，**两套绝不并行**（叠加会让新快照抓到元素过渡中的中间色，
 * 比生硬更脏）：
 *
 *   1) 支持 View Transitions（Chrome/Edge 111+、Safari 18+）
 *      ⇒ document.startViewTransition()，新主题以开关为圆心扩散揭示
 *        （几何见 css/6-anim.css 末尾 §主题过渡）。
 *   2) 不支持（或 prefers-reduced-motion）
 *      ⇒ .theming 三层错峰：顶栏 0ms / 侧栏 60ms / 主区 140ms 颜色过渡，
 *        460ms 后摘类。这条路径纯 CSS，无兼容问题。
 *
 * 🔴 与开关 GSAP 的协作（2026-10-22 第二轮修正）：VT 期间整页是**静态快照**，
 *   原 DOM 不可见。开关的 timeline 若照常起跑，观众看到的是「定格 → 揭示完成
 *   瞬间跳到 0.55s 那一帧」，滑块像被抽了一下 —— 这就是「两段动画不融洽」。
 *   现在改成串行：扩散期间 timeline 以 paused 创建，扩散结束（或失败/跳过）
 *   后由 whenVtDone 放行。扩散 0.55s 与滑块首段 0.45s 同频，节奏是一条线。
 *   要彻底消除得让开关等 VT 结束再起播 —— 那会变成「先扩散、后演开关」，
 *   节奏更怪。权衡后选了短时长。
 *
 * 🔴 首屏那次一律不演：此时样式表可能还没应用完，演出来只会闪一下。
 * ==================================================================== */
import { S } from "./store.js";
import { reduced } from "./anim.js";

var _booted = false;
var _timer = null;
var _vt = null; /* 正在进行中的 View Transition（供 ThemeSwitch 串行用） */

/* 扩散时长：与开关滑块首段同频（滑块 0→66 用 0.45s）。两条动画同频是
   「融洽」的关键 —— 一快一慢时，观众会看到页面已经换完、开关还在慢慢爬。 */
var VT_MS = 0.55;

function systemDark() {
  return (
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

function vtSupported() {
  return typeof document.startViewTransition === "function";
}

/* 🔴 给 ThemeSwitch 的两个钩子（2026-10-22 第二轮）：
 *    VT 期间整页是**静态快照**，原 DOM 不可见。所以开关的 timeline 如果照常
 *    起跑，观众看到的是「定格 → 揭示完成瞬间跳到 0.55s 那一帧」，滑块像被
 *    抽了一下 —— 这就是主人说的「点击切换动画和主题切换动画不融洽」。
 *    解法：扩散期间 timeline 以 paused 创建，扩散结束后再 play（串行）。
 *    若浏览器不支持 VT（或降级为 .theming），vtBusy() 恒为 false，直接正常播。 */
function vtBusy() {
  return !!_vt;
}

function whenVtDone(fn) {
  if (!_vt) {
    fn();
    return;
  }
  var done = false;
  var once = function () {
    if (done) return;
    done = true;
    fn();
  };
  /* rejected = 被跳过（连点 / 页面隐藏），也必须放行，否则 timeline 永久暂停。 */
  _vt.finished.then(once, once);
  /* 兜底：finished 在某些实现下可能迟迟不 settle，宁可早放也不卡死。 */
  setTimeout(once, VT_MS * 1000 + 260);
}

/* 把扩散圆心与半径写到 :root，供 6-anim.css 的 clip-path 读取。
   半径取「圆心到四角的最远距离」+ 8px，任何视口比例都能铺满。 */
function setOrigin(x, y) {
  var root = document.documentElement;
  var w = window.innerWidth || 1;
  var h = window.innerHeight || 1;
  var r = Math.hypot(Math.max(x, w - x), Math.max(y, h - y)) + 8;
  root.style.setProperty("--vt-x", Math.round(x) + "px");
  root.style.setProperty("--vt-y", Math.round(y) + "px");
  root.style.setProperty("--vt-r", Math.round(r) + "px");
}

/* 没拿到点击坐标时（命令面板、跟随系统）退化成「当前焦点元素中心」，
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

/* applyTheme(pref, origin?, silent?)
 *   pref    "light" | "dark" | "auto"
 *   origin  {x, y} 圆形扩散的圆心（屏幕坐标）
 *   silent  true = 不动画（首屏预设、系统主题自动跟随用）
 */
function applyTheme(pref, origin, silent) {
  var root = document.documentElement;
  var resolved = pref === "auto" ? (systemDark() ? "dark" : "light") : pref;

  function commit() {
    root.setAttribute("data-theme", resolved);
    root.setAttribute("data-theme-pref", pref);
    try {
      localStorage.setItem("am.theme", pref);
    } catch (e) {
      /* 忽略 */
    }
  }

  var animate = _booted && !silent && !reduced();
  _booted = true;

  if (!animate) {
    commit();
    return resolved;
  }

  if (vtSupported()) {
    var o = resolveOrigin(origin);
    setOrigin(o.x, o.y);
    var vt = document.startViewTransition(commit);
    _vt = vt;
    var clear = function () {
      if (_vt === vt) _vt = null;
    };
    /* 扩散被跳过（连点、页面隐藏）是正常行为，别让 rejection 刷控制台。 */
    vt.finished.then(clear, clear);
  } else {
    if (_timer) clearTimeout(_timer);
    root.classList.add("theming");
    commit();
    _timer = setTimeout(function () {
      root.classList.remove("theming");
      _timer = null;
    }, 460);
  }
  return resolved;
}

if (window.matchMedia) {
  try {
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", function () {
        /* 系统自己变的不演：用户没操作，突然一圈扩散会很突兀。 */
        if (S.themePref === "auto") S.theme = applyTheme("auto", null, true);
      });
  } catch (e) {
    /* 老浏览器 */
  }
}

export { systemDark, applyTheme, vtBusy, whenVtDone };
