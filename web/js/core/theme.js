/* 主题：深/浅色解析与落盘
 * index.html 的内联脚本已做过一次预设（防 FOUC），
 * 这里负责运行期切换与监听系统主题变化。
 *
 * ======================================================================
 * 2026-10-22 · 方案 B「单时钟」（第三轮，主人定案）
 *
 * 演进：
 *   1.0 直接改 data-theme，页面一帧换完 ⇒ 与开关 1.5s 的天空渐变反差太大（生硬）。
 *   2.0 改 View Transitions 圆形扩散（0.55s）⇒ 扩散确实好看，但 VT 期间整页是
 *       静态快照，开关被冻在快照里：
 *         · 让 timeline 照常跑 ⇒ 揭示完成瞬间画面从 0 帧跳到第 0.55s 帧（跳帧）；
 *         · 让 timeline 暂停等扩散 ⇒ 页面先换完、开关 0.55s 后才补演（错位）。
 *       实测第二版错位 671ms（页面 t=108ms 已换，滑块 t=779ms 才起跑）。
 *       —— 这是物理约束：整页快照下，「扩散期间」不存在任何可见的活体动画。
 *   3.0 撤 VT，回到 **单时钟**：页面颜色与开关 timeline 同一帧起跑、同时收尾。
 *       没有快照 ⇒ 没有冻结 ⇒ 没有跳帧也没有滞后。代价是失去圆形扩散，
 *       换成整页统一的颜色渐变（0.45s，与滑块首段同长、同缓动）。
 *
 * 🔴 三条边界（CSS 侧见 6-anim.css 末尾 §主题过渡）：
 *   1) 只用 .theming 期间生效的过渡，绝不常驻 —— 常驻会让 hover / 焦点响应变慢；
 *   2) 只过渡颜色类属性，不碰 transform / width 这类几何属性；
 *   3) 类在 PAGE_MS + 60ms 后摘掉，避免过渡规则挂在 DOM 上。
 *
 * 🔴 首屏那次一律不演：此时样式表可能还没应用完，演出来只会闪一下。
 * ==================================================================== */
import { S } from "./store.js";
import { reduced } from "./anim.js";

var _booted = false;
var _timer = null;

/* 页面换色时长 0.45s：与开关滑块首段落定（0.45s）同长，缓动同为 --ease-in-out。
   两者同帧起跑、同帧收尾，这就是「同步」的定义。 */
var PAGE_MS = 450;
/* 摘类比动画多留 60ms —— 少于动画时长会在最后一帧把过渡掐断（肉眼是「顿一下」）。 */
var HOLD_MS = PAGE_MS + 60;

function systemDark() {
  return (
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

function applyTheme(pref, silent) {
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
    if (_timer) {
      clearTimeout(_timer);
      _timer = null;
      root.classList.remove("theming");
    }
    commit();
    return resolved;
  }

  /* 先挂类再改属性：过渡规则必须在「改动那一帧」就已经生效，
     否则 old 值取不到、只能瞬切。 */
  if (_timer) clearTimeout(_timer);
  root.classList.add("theming");
  commit();
  _timer = setTimeout(function () {
    root.classList.remove("theming");
    _timer = null;
  }, HOLD_MS);

  return resolved;
}

if (window.matchMedia) {
  try {
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", function () {
        /* 系统自己变的不演：用户没操作，突然整页渐变会很突兀。 */
        if (S.themePref === "auto") S.theme = applyTheme("auto", true);
      });
  } catch (e) {
    /* 老浏览器 */
  }
}

export { systemDark, applyTheme };
