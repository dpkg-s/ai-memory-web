/* ============================================================================
 * core/flip.js —— 断点跨越的布局 FLIP 动画
 *
 * 出处：《GSAP 断点 Flip 布局动画 · 跨项目施工手册》（graphite-workspace 2026-10-16
 * 实装，3 段跨越探针 ALL PASS）。本文件是那份手册在本项目的落地版，
 * 逐条对齐它的「关键原理」，**没有自创时序**：
 *
 *   ① 旧布局**只能靠周期性预抓取**（手册 §5-1）。resize 回调里读到的 rect
 *      已经是新布局（事件顺序：视口变 → 重排 → 派发 resize），拿它当基线
 *      算出的位移永远是 0，动画凭空消失。所以这里每 150ms 存一份目标矩形快照
 *      （手册用 `Flip.getState`；2026-10-30 起改为自己量 rect，见修正④）。
 *   ② 抓取要跳过「动画进行中」与「页面隐藏」（§5-2），
 *      抓到 0 个目标必须清空历史而不是存空快照（否则差量算不出来）。
 *   ③ 任何一路断掉（没抓到旧态 / 判定没位移 / 被新跨越打断）就**放弃动画**，
 *      退化成瞬间重排 —— 永远不会比不装更糟（§5-5）。
 *   ④ 起动画要包进 rAF（§5-4）：Windows 拖动窗口边缘是模态循环，
 *      rAF 挂起，直接启动会把卡片钉死在旧位置。
 *   ⑤ prefers-reduced-motion 时整个模块不注册（§5-6）。
 *   ⑥ 目标选择器在断点前后必须命中**同一批 DOM 元素**（§4）。
 *      本项目概览页的卡是 v-if 条件渲染的（骨架 ↔ 真卡），
 *      骨架态抓到 0 个目标 ⇒ 存 null ⇒ 退化成硬切，符合预期。
 *
 * 与手册的差异一：触发只挂 matchMedia 的 change，**不挂 resize 触发**。
 *   手册自己也只在 mq change 上触发；拖动窗口时连续 resize 会不断用「半旧」的
 *   基线起新动画，观感是抖而不是顺。断点（1399 / 1024 / 899 / 699 / 560）才是
 *   真正的布局跳变点。``resize`` 只用来量「是不是正在拖」以缩短时长（见下）。
 *
 * 与手册的差异二：**不开 `absolute: true`、也不用 `Flip.from`**。
 *   位移由本模块自己算（矩形差量）+ `gsap.timeline` 逐元素 `fromTo` 补间，
 *   理由见 2026-10-30 修正②④。
 *
 * ---------------------------------------------------------------------------
 * 🔴 2026-10-30 四处修正（前一轮的「给父容器钉 min-height」方案整体撤除）
 *
 *   ① **CSS 入场动画压住 inline transform —— FLIP 从来没有真正动过（最致命）**
 *      `.grid.stats > .stat` 挂着 `animation: statReveal … both`、
 *      `.grid.two > .card` 挂着 `animation: riseIn … both`。`both` 意味着动画
 *      **播完仍继续填终值**，而 CSS 动画在层叠里**高于 inline style**
 *      ⇒ GSAP 每帧写的 `transform` 被整体覆盖成终值。
 *      实测（`_flip_probe.html`，跨越 1440→1280，abs=1 的那 38 帧）：
 *        computed transform = matrix(1,0,0,1,0,0)       ← 恒等
 *        inline   transform = translate(1056px, 817px)  ← 被完全吃掉
 *      即卡片**一个像素都没移动**，只有容器高度在补间 ⇒ 观感是「卡片忽然跑到
 *      别处、页面在抖，动画却像没播」。
 *      治法：起动画前把目标身上**已经播完**的 CSSAnimation `cancel()` 掉。
 *      终值本来就等于基础样式（translateY(0) / opacity:1），取消不产生视觉变化；
 *      仍在 running 的不碰（跨越恰好撞上入场那 0.7s 属于极少数）。
 *
 *   ② **`absolute: true` 把卡片量到 (0,0)**
 *      `.grid.stats` / `.grid.two` 的 computed `position` 是 `static`，Flip 把子项
 *      改成 `position:absolute` 后包含块跳到 `.page` 一级，实测矩形直接 top=0
 *      —— 卡片瞬间跑到页面顶端，动画结束再落回。
 *      治法：**不脱流**。跨越断点时新布局已经落地，目标留在自己新格位里只做
 *      transform 位移 —— 这才是标准 FLIP。脱流在这里没有任何收益。
 *
 *   ③ **「钉父容器 min-height 再补间」是自找的抖动**
 *      它治的是 ② 造成的容器塌陷；② 去掉后塌陷不再存在，这套托底整段撤除。
 *      更要紧的是它本身有害：跨越瞬间页面**必然**先按新高度重排一次，托底又把
 *      容器**拽回旧高度**再补间回去 —— 实测 tagsTop 642 → 821（新布局）→ 跳回
 *      642 → 再补到 821，等于动画起手先把整页往回甩 179px。那是二次跳版，不是平滑。
 *
 *   另：`data-flipping` 改为 **onComplete 之后隔两帧再摘牌**。同步摘牌会在同一帧
 *   把 `.card { transition: transform }` 重新打开，而 GSAP 恰在这一帧清掉 inline
 *   transform ⇒ 浏览器按"从位移回到 0"补间一段，这就是收尾那下闪烁。等两帧让终态
 *   先落定，摘牌时已无事可补。
 *
 *   ④ **`Flip.from` 自带「尺寸补间」，会把旧宽高写回卡片**
 *      Flip 默认不只用 transform 表达位移，它还会把目标的**旧宽高**写成内联样式
 *      （实测 `width:546px; height:243px`）再补间到新尺寸。这两条内联宽高一落到
 *      卡片上，`.grid.two` 的网格轨道立刻按**旧尺寸**重算 ⇒ 容器 678 → 500、
 *      整页内容跟着上跳 179px，动画结束才弹回。`props:"x,y"` 关不掉它
 *      （尺寸走的是另一条通道），`scale:true` 能关掉宽高但又改用 scaleX/scaleY
 *      补偿 —— 卡片内容会被拉伸 1.17 倍，更难看。
 *      治法：**不用 Flip.from**。基线矩形本来就由本模块自己采样（`rects`），
 *      差量 `旧 − 新` 直接喂给 `gsap.fromTo(el, {x,y}, {x:0,y:0})`：
 *      只动 transform，不碰尺寸，新布局在整个动画期间一寸不移。
 *      代价：不做旋转/缩放/嵌套变换的归一化 —— 本场景只需要平移，够用。
 *      实测（跨越 1440→1280，9 个目标）：动画期间页面 tagsTop / 容器高度跨度
 *      从 **178px 降到 0**，卡片自身逐帧位移 ≤ 4px（连续滑动，无跳变）。
 * ------------------------------------------------------------------------- */

import { reduced } from "./anim.js";

/* 探针钩子：{ runs, lastAt, skipped, why, gap }，供无头验收断言「动画真的播了」。
   与 index.html 的 window.__amError 同一种做法 —— 只暴露计数与放弃原因，
   不暴露内部状态。
   2026-10-29 补 `why` / `gap`：只统计「跳过几次」无法定位是哪条放弃路径
   （没抓到旧态 / 判定没位移），而这两条的修法完全不同 ⇒ 放弃时必须留因。 */
function hook() {
  if (!window.__amFlip) {
    window.__amFlip = {
      runs: 0,
      lastAt: 0,
      skipped: 0,
      why: "",
      gap: 0, // 跨越时刻距上一次成功采样多少毫秒
      n: 0, // 上一次采样命中的目标数
      coalesced: 0, // 同一次拖动跨多条断点时的连带事件（不计入 skipped）
      settled: 0, // 累计取消掉的「已播完」入场动画个数（诊断用）
    };
  }
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
  var noop = function () {};
  /* 缺 GSAP / 用户要求减弱动效 —— 直接不注册，页面行为与未安装时完全一致。
     ⚠️ 2026-10-30 起**不再需要 Flip 插件**：位移由本模块自己用 gsap.fromTo 做
     （原因见文件头修正④）。window.Flip 仍随 vendor 加载，供将来别的场景用。 */
  if (!gsap || reduced()) return noop;

  opt = opt || {};
  var duration = opt.duration == null ? 0.46 : opt.duration;
  var stagger = opt.stagger == null ? 0.02 : opt.stagger;
  var ease = opt.ease || "power1.inOut";
  var stat = hook();

  var targets = function () {
    return Array.prototype.slice.call(document.querySelectorAll(sel));
  };

  /* ---- 基线环形缓冲（2026-10-29 重做）------------------------------------
   * 旧实现只留「最新一次采样」，跨越时直接拿它当旧布局。实测踩到 1 帧竞态：
   *   · 视口变宽/变窄 → 浏览器重排 → 派发 resize → 派发 matchMedia 的 change；
   *   · 150ms 的采样定时器若正好落在「重排之后、change 之前」这一帧，
   *     最新基线就被改写成**新布局**的位置；
   *   · change 到达时比对「新旧位置」得到 0 位移 ⇒ 判 noMove ⇒ 放弃动画。
   *   探针实测证据：`why=noMove gap=2` 与 `why=stale gap=1`（gap = 跨越距上次采样）。
   *   治法不再和这 1 帧赛跑：留 **最近 3 份** 基线，跨越时从新到旧挑第一份
   * 「确实和当前布局不同」的 —— 被污染的那份与当前一致而被跳过，退回它上一份
   * （必定是跨越前的布局）。于是动画要么拿到真基线，要么确实是没位移。
   * ---------------------------------------------------------------------- */
  var HIST = 3;
  var hist = [];
  var anim = null;
  var raf = 0;
  /* 拖动窗口边缘时用更短的时长：0.46s 的补间在「宽度每帧都在变」的环境里会明显
     拖尾（基线在起手那一刻就冻结了，而真实布局还在变）。判断只靠 resize 的时间戳，
     不改变触发条件。 */
  var lastResize = 0;

  var snapRects = function (els) {
    return els.map(function (t) {
      var r = t.getBoundingClientRect();
      return [Math.round(r.left), Math.round(r.top)];
    });
  };

  /* 两份 rect 快照之间是否存在 > 1px 的位移（顺序必须一一对应）。 */
  var differs = function (a, b) {
    if (!a || !b || a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (Math.abs(a[i][0] - b[i][0]) > 1 || Math.abs(a[i][1] - b[i][1]) > 1) return true;
    }
    return false;
  };

  /* ---- 让 inline transform 重新说话（2026-10-30）-------------------------
   * 见文件头修正①：`statReveal` / `riseIn` 都是 `animation … both`，
   * 播完仍填终值，而 CSS 动画优先级高于 inline style ⇒ GSAP 写的位移被整体覆盖。
   * 只取消 **finished** 的动画：终值 == 基础样式，取消不可见；仍在跑的不动
   * （打断一次入场动画的代价比"这次跨越不补间"更大）。
   * ---------------------------------------------------------------------- */
  var settleEntrance = function (els) {
    if (!els.length || typeof els[0].getAnimations !== "function") return;
    els.forEach(function (el) {
      el.getAnimations().forEach(function (a) {
        try {
          if (a.playState === "finished") {
            a.cancel();
            stat.settled++;
          }
        } catch (e) {
          /* 动画已被回收 */
        }
      });
    });
  };

  var sample = function () {
    if (anim || document.hidden) return; // ① 中间态不能当基线
    var els = targets();
    if (!els.length) {
      hist.length = 0; // ② 目标未挂载：不留过期基线（空快照会让差量算不出来）
      return;
    }
    var rects = snapRects(els);
    hist.push({ rects: rects, at: Date.now(), n: els.length });
    if (hist.length > HIST) hist.shift();
    stat.n = els.length;
  };

  var doBreak = function () {
    var cand = hist.slice();
    hist.length = 0;
    var cur = snapRects(targets());
    var pick = null;
    for (var i = cand.length - 1; i >= 0; i--) {
      if (cand[i].n !== cur.length) continue;
      if (differs(cur, cand[i].rects)) {
        pick = cand[i];
        break;
      }
    }
    if (!pick) {
      stat.why = cand.length ? "noMove" : "noState";
      stat.skipped++;
      return; // ③ 没有可用旧布局 / 布局确实没变 → 放弃，退化成即时重排
    }
    stat.gap = pick.at ? Date.now() - pick.at : -1;
    /* 位移差量（旧矩形 − 新矩形）。这就是 FLIP 的全部数学：新布局已经落地，
       只把目标先"推回"旧位置，再补间到 0。 */
    var els = targets();
    var dx = [];
    var dy = [];
    var moved = 0;
    for (var k = 0; k < els.length; k++) {
      dx[k] = pick.rects[k][0] - cur[k][0];
      dy[k] = pick.rects[k][1] - cur[k][1];
      if (Math.abs(dx[k]) > 1 || Math.abs(dy[k]) > 1) moved++;
    }
    if (!moved) {
      stat.why = "noMove";
      stat.skipped++;
      return;
    }
    /* 🔴 中断收尾（2026-10-29）：原来直接 `anim.kill()` 会在**动画中途**把元素
       留在 Flip 写进去的位移上 —— 连续快速跨越两次时，第二次的旧位置基线其实来自
       「已经不存在的中间态布局」，量出来是错的，表现为卡片先飞一段再跳回。
       先 `progress(1)` 把它推到终态（触发 onComplete ⇒ 走统一收尾），再 kill。 */
    if (anim) {
      var a = anim;
      anim = null;
      try {
        a.progress(1);
      } catch (e) {
        /* 已被回收 */
      }
      try {
        a.kill();
      } catch (e) {
        /* 同上 */
      }
    }
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(function () {
      /* 动画期间给根节点挂牌，让 CSS 层让位（见 6-anim.css §17n）：
         `.card` 自带 `transition: transform`，GSAP 每帧写 inline transform
         会被这层过渡再插值一次 ⇒ 观感是"拖着走 / 落点迟半拍"。 */
      document.documentElement.setAttribute("data-flipping", "1");
      settleEntrance(els);
      var finish = function () {
        if (anim) anim = null;
        /* 先把 GSAP 留下的 translate(0,0) 内联清掉（此时还挂着 data-flipping，
           过渡被压着，不会补间）；再隔两帧摘牌。 */
        els.forEach(function (el) {
          gsap.set(el, { clearProps: "transform,x,y" });
        });
        /* 隔两帧摘牌：见文件头末段。中断时若已经有下一段动画在跑，就别替它摘。 */
        requestAnimationFrame(function () {
          requestAnimationFrame(function () {
            if (anim) return;
            document.documentElement.removeAttribute("data-flipping");
            /* 收尾立刻补一次采样：动画期间 sampler 全程停摆（① 不能拿中间态当
               基线），若跨越紧跟在上一次动画之后到来，这里不留一次就会被判
               「没抓到旧态」。 */
            setTimeout(sample, 0);
          });
        });
      };
      var dur = Date.now() - lastResize < 240 ? Math.min(duration, 0.24) : duration;
      var tl = gsap.timeline({ onComplete: finish, onInterrupt: finish });
      els.forEach(function (el, i) {
        /* 位移 < 1px 的元素不入队：它们本来就在原地，补间只是白烧一帧。
           delay 用 stagger 逐级铺开，保持原有错峰观感。 */
        if (Math.abs(dx[i]) <= 1 && Math.abs(dy[i]) <= 1) return;
        tl.fromTo(
          el,
          { x: dx[i], y: dy[i] },
          { x: 0, y: 0, duration: dur, ease: ease },
          i * stagger,
        );
      });
      anim = tl;
      stat.runs++;
      stat.why = "run";
      stat.lastAt = Date.now();
    });
  };

  /* 一次拖动可能同时跨多条断点（例：1440 → 860 会同时触发 1399 / 1024 / 899 三条），
     浏览器为每条派发一次 change。基线只有一份，第一条已经消费掉并起了动画，
     后面几条必然"没抓到旧态" —— 那是同一次布局变化的连带事件，不是「该动没动」。
     所以基线为空时记 `coalesced`（合并），不再污染 `skipped`（真放弃）的计数，
     免得探针看到 skip 就误判成动画失效。 */
  var onBreak = function () {
    if (!hist.length) {
      stat.why = "coalesced";
      stat.coalesced++;
      return;
    }
    doBreak();
  };

  /* resize 只做一件事：记时间戳，供 doBreak 判断「当前是不是在拖动」以缩短时长。
     不触发动画（见文件头「差异一」）。 */
  var onResize = function () {
    lastResize = Date.now();
  };

  var mqs = breakpoints.map(function (q) {
    return window.matchMedia(q);
  });
  mqs.forEach(function (m) {
    m.addEventListener("change", onBreak);
  });
  window.addEventListener("resize", onResize, { passive: true });
  sample();
  var timer = setInterval(sample, 150);

  return function () {
    clearInterval(timer);
    mqs.forEach(function (m) {
      m.removeEventListener("change", onBreak);
    });
    window.removeEventListener("resize", onResize);
    cancelAnimationFrame(raf);
    if (anim) anim.kill();
    hist.length = 0;
    document.documentElement.removeAttribute("data-flipping");
  };
}
