/* ============================================================================
 * core/flip.js —— 断点跨越的布局 FLIP 动画
 *
 * 出处：《GSAP 断点 Flip 布局动画 · 跨项目施工手册》（graphite-workspace 2026-10-16
 * 实装，3 段跨越探针 ALL PASS）。本文件是那份手册在本项目的落地版，
 * 逐条对齐它的「关键原理」，**没有自创时序**：
 *
 *   ① 旧布局**只能靠周期性预抓取**（手册 §5-1）。resize 回调里读到的 rect
 *      已经是新布局（事件顺序：视口变 → 重排 → 派发 resize），拿它当基线
 *      算出的位移永远是 0，动画凭空消失。所以这里每 150ms 存一份 Flip.getState。
 *   ② 抓取要跳过「动画进行中」与「页面隐藏」（§5-2），
 *      抓到 0 个目标必须存 null 而不是空 state（否则 Flip.from 会拿到空基线）。
 *   ③ absolute:true 必须开（§5-3）：动画期间卡片脱流，兄弟不会互相推挤。
 *   ④ Flip.from 要包进 rAF（§5-4）：Windows 拖动窗口边缘是模态循环，
 *      rAF 挂起，直接启动会把卡片钉死在旧位置。
 *   ⑤ 任何一路断掉（没抓到旧态 / 被新跨越打断）就**放弃动画**，
 *      退化成瞬间重排 —— 永远不会比不装更糟（§5-5）。
 *   ⑥ prefers-reduced-motion 时整个模块不注册（§5-6）。
 *   ⑦ 目标选择器在断点前后必须命中**同一批 DOM 元素**（§4）。
 *      本项目概览页的卡是 v-if 条件渲染的（骨架 ↔ 真卡），
 *      骨架态抓到 0 个目标 ⇒ 存 null ⇒ 退化成硬切，符合预期。
 *
 * 与手册的唯一差异：触发只挂 matchMedia 的 change，**不挂 resize**。
 * 手册自己也只在 mq change 上触发；拖动窗口时连续 resize 会不断用「半旧」的
 * 基线起新动画，观感是抖而不是顺。断点（899 / 560）才是真正的布局跳变点。
 * ========================================================================== */

import { reduced } from "./anim.js";

/* 探针钩子：{ runs, lastAt }，供无头验收断言「动画真的播了」。
   与 index.html 的 window.__amError 同一种做法 —— 只暴露计数，不暴露内部状态。 */
function hook() {
  if (!window.__amFlip) window.__amFlip = { runs: 0, lastAt: 0, skipped: 0 };
  return window.__amFlip;
}

/**
 * @param {string}   sel         动画目标选择器（断点前后同一批元素）
 * @param {string[]} breakpoints matchMedia 查询串，与 CSS @media 逐字符一致
 * @param {object}   [opt]       { duration, stagger, ease }
 * @returns {function} teardown
 */
export function breakpointFlip(sel, breakpoints, opt) {
  var gsap = window.gsap;
  var Flip = window.Flip;
  var noop = function () {};
  /* 缺 GSAP / 缺插件 / 用户要求减弱动效 —— 三种情况一视同仁：
     直接不注册，页面行为与未安装时完全一致。 */
  if (!gsap || !Flip || reduced()) return noop;

  opt = opt || {};
  var duration = opt.duration == null ? 0.5 : opt.duration;
  var stagger = opt.stagger == null ? 0.02 : opt.stagger;
  var ease = opt.ease || "power1.inOut";
  var stat = hook();

  var targets = function () {
    return Array.prototype.slice.call(document.querySelectorAll(sel));
  };

  var lastState = null;
  /* 旧布局的「裸 rect」快照：Flip.getState 内部当然也存了位置，但那是私有结构，
     拿不到可比对的数值。这里在**采样那一刻**另存一份 (left, top)，用于跨越后
     判断「布局到底有没有真的变」—— 没有它就只能无条件起动画，空动画会让探针
     的 runs 计数虚高，也让「断点跨越」这件事失去可信度。 */
  var lastRects = null;
  var anim = null;
  var raf = 0;

  var sample = function () {
    if (anim || document.hidden) return; // ① 中间态不能当基线
    var els = targets();
    if (!els.length) {
      lastState = null; // ② 目标未挂载，存 null 而不是空 state
      lastRects = null;
      return;
    }
    var st = Flip.getState(els);
    lastState = st.targets.length ? st : null;
    lastRects = els.map(function (t) {
      var r = t.getBoundingClientRect();
      return [Math.round(r.left), Math.round(r.top)];
    });
  };

  var onBreak = function () {
    var st = lastState;
    var oldRects = lastRects;
    lastState = null;
    lastRects = null;
    if (!st) {
      stat.skipped++;
      return; // ⑤ 没有旧布局 → 放弃
    }
    /* 布局没真的变（某个断点只影响别的页 / 只是高度变了）就别演空动画。 */
    var moved = !oldRects || oldRects.length !== st.targets.length;
    if (!moved) {
      for (var i = 0; i < st.targets.length; i++) {
        var nr = st.targets[i].getBoundingClientRect();
        if (
          Math.abs(Math.round(nr.left) - oldRects[i][0]) > 1 ||
          Math.abs(Math.round(nr.top) - oldRects[i][1]) > 1
        ) {
          moved = true;
          break;
        }
      }
    }
    if (!moved) {
      stat.skipped++;
      return;
    }
    if (anim) {
      anim.kill();
      anim = null;
    }
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(function () {
      anim = Flip.from(st, {
        duration: duration,
        ease: ease,
        absolute: true,
        stagger: stagger,
        onComplete: function () {
          anim = null;
        },
      });
      stat.runs++;
      stat.lastAt = Date.now();
    });
  };

  var mqs = breakpoints.map(function (q) {
    return window.matchMedia(q);
  });
  mqs.forEach(function (m) {
    m.addEventListener("change", onBreak);
  });
  sample();
  var timer = setInterval(sample, 150);

  return function () {
    clearInterval(timer);
    mqs.forEach(function (m) {
      m.removeEventListener("change", onBreak);
    });
    cancelAnimationFrame(raf);
    if (anim) anim.kill();
  };
}
