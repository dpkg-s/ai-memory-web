/* ============================================================================
 * core/lens.js —— 侧栏「悬停跟随」玻璃透镜（2026-10-20）
 *
 * 主人原话：「悬停跟随呢？」—— `liquid-glass.md` 里这条交互才是液态玻璃的**主角**
 * （文档 §4：透镜跟手滑动，命中项浮起）。上一轮把 Dock 整块撤了、材质给了侧栏，
 * 跟随一起丢了，这里补回来。
 *
 * 后续两条修正都落在这一版里：
 *   · 「这个 nav-item active 也跟随」→ 透镜命中哪一项，就给哪一项挂 `.lens-hit`
 *     （视觉与 `.active` 共用同一条规则），选中态本身跟着手走；
 *   · 「玻璃大小要贴合 active」→ 玻璃不再是浮在条目里的一颗珠子，而是**与条目 1:1
 *     等大**的玻璃片，正好压住那一格。尺寸在运行时从第一个 `.nav-item` 量出来
 *     —— 不写死：侧栏宽度是响应式的，写死会在抽屉/窄屏错位。
 *
 * ---------------------------------------------------------------------------
 * 🔴 为什么透镜是 `.sidebar` 的**兄弟**而不是它的子元素
 *
 *   约束 1（lg.js 顶部）：backdrop-filter 只采样「元素自己之外、绘制顺序在前」的
 *   内容，且祖先带 backdrop-filter 会另起一个 backdrop root。把透镜塞进
 *   `.sidebar` 内部，它采到的是侧栏自己的 background（一层 42% 的半透明色），
 *   折射等于折了个寂寞；做成兄弟、z-index 高一级，它采到的就是**侧栏的合成结果**
 *   —— 于是图标、指示条、选中态的填充都会被边圈弯折，这才是「玻璃压在上面」。
 *
 * ---------------------------------------------------------------------------
 * 位移：等大之后**必须**吸附到条目，不能再逐像素跟手。
 *   条目高 43、间隙 3；若玻璃自由跟手，指针落在缝隙时玻璃一半压在选中项、一半压在
 *   空项上，而填充只出现在一侧 —— 视觉上就是「玻璃和选中块错位」。所以命中哪一项就
 *   整片贴到哪一项；跨项时靠 quickTo 的 0.4s 插值滑过去，仍然读作「跟手」，
 *   但边缘永远与填充严丝合缝。指针落在轨道空白处（品牌区 / 底部）判为无命中，
 *   玻璃淡出 —— 保证「玻璃 ≡ 填充」这条不变量始终成立。
 *
 * 手感：GSAP quickTo（duration 0.40 / power3）；进场用 gsap.set 直接落位再淡入，
 *      避免从 (0,0) 飞过来；rAF 闸门合并高刷鼠标的重复事件。
 *
 * 降级：无 GSAP 或 prefers-reduced-motion ⇒ 直接写 transform，位置仍然正确。
 * ========================================================================== */
import { dressLens, LENS } from "./lg.js";

/**
 * 挂载悬停跟随透镜。
 * @param {Element} host 轨道（.sidebar）
 * @param {Element} lens 透镜（.rail-lens，须为 host 的兄弟）
 * @param {object} [opt] { hit: 命中选择器, hitClass: 命中类名 }
 * @returns {function} teardown
 */
export function mountRailLens(host, lens, opt) {
  if (!host || !lens) return function () {};
  opt = opt || {};
  var hitSel = opt.hit || ".nav-item";
  var hitClass = opt.hitClass || "lens-hit";
  var hits = host.querySelectorAll(hitSel);
  var hot = -1;
  /* 滤镜必须挂在内层 .rail-lens-glass 上，不能挂外层：
     Chromium **不把 feDisplacementMap 的输出裁到 border-radius** —— 位移后的像素会
     溢出到圆角外面那四小块矩形里，而那里 backdrop 是空的 ⇒ 四角糊出黑三角
     （玻璃与条目等大后右下角特别明显，实测截图确认）。外层负责圆角 + overflow:hidden
     把内层的滤镜输出裁干净，这是 backdrop-filter 配圆角的标准做法。 */
  var glass = lens.querySelector(".rail-lens-glass") || lens;

  var gsap = (typeof window !== "undefined" && window.gsap) || null;
  var reduced = false;
  try {
    reduced = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  } catch (e) {
    /* 忽略 */
  }

  var W = LENS.w;
  var H = LENS.h;

  /* 贴图尺寸 = 元素盒尺寸（lg.js 约束 2），两者只能同时改 —— 所以先量后写。
     ⚠️ 外层也要写尺寸：内层是绝对定位，不撑开外层，不写的话外层是 0×0，
        rect 全 0、GSAP 的 x/y 定位也会跟着错。 */
  function fit() {
    var b = hits.length ? hits[0].getBoundingClientRect() : null;
    W = b && b.width ? Math.round(b.width) : LENS.w;
    H = b && b.height ? Math.round(b.height) : LENS.h;
    lens.style.width = W + "px";
    lens.style.height = H + "px";
    /* 透镜自身的折射：边缘折得狠、中心几乎不糊（blur 只给 0.6px，
       否则压在 19px 图标上会把图形糊成一团）。 */
    dressLens(glass, { w: W, h: H });
  }

  fit();

  var qx = null,
    qy = null,
    qo = null;
  /* 🔴 reduced motion 下**不能**用 quickTo，哪怕把 duration 设成 0。
     实测（Chrome，Emulation.setEmulatedMedia prefers-reduced-motion:reduce）：
     duration:0 的 quickTo 不会「立即到位」，而是每帧只挪一小步 ——
     opacity 卡在 0.1、transform 停在 (10.1, 120.1)，玻璃只有一成不透明度，
     看起来就是「根本没出现」。Windows 关掉「显示动画」就会走到这条分支，
     是最难在自己机器上复现的那种「你那儿没有」。
     所以 reduced 时直接不走 GSAP 补间：下面 put/fade 会退化成 gsap.set / 直接写样式。 */
  if (gsap && !reduced) {
    qx = gsap.quickTo(lens, "x", { duration: 0.4, ease: "power3" });
    qy = gsap.quickTo(lens, "y", { duration: 0.4, ease: "power3" });
    qo = gsap.quickTo(lens, "opacity", { duration: 0.16, ease: "power2.out" });
  }

  function put(x, y, instant) {
    if (qx && !instant) {
      qx(x);
      qy(y);
      return;
    }
    if (gsap) gsap.set(lens, { x: x, y: y });
    else lens.style.transform = "translate(" + x + "px," + y + "px)";
  }

  function fade(v) {
    if (qo) qo(v);
    else if (gsap) gsap.set(lens, { opacity: v });
    else lens.style.opacity = String(v);
  }

  /* ⚠️ 纵向给 PAD 容差、横向直接按整条轨道判：
        · 条目之间只有 3px 缝，严格按 rect 判定的话指针划过去会有一两帧落空，
          `.has-hit` 跟着闪，当前页的填充会一明一暗 —— 加 PAD 把缝补上；
        · 轨道 64px、条目 44px，两侧各留 10px，指针贴在边上时严格判定也会落空，
          而用户明明就在那一项旁边 ⇒ 横向用轨道宽度兜住。 */
  var PAD = 3;

  function hitIndex(cx, cy) {
    var hb = host.getBoundingClientRect();
    if (!hb.width || cx < hb.left || cx > hb.right) return -1;
    for (var i = 0; i < hits.length; i++) {
      var b = hits[i].getBoundingClientRect();
      if (cy >= b.top - PAD && cy <= b.bottom + PAD) return i;
    }
    return -1;
  }

  /* 只在索引变化时碰 DOM（每帧 classList.remove 会让 style 失效重算）。 */
  function setHit(idx) {
    if (idx === hot) return;
    if (hot >= 0 && hits[hot]) hits[hot].classList.remove(hitClass);
    hot = idx;
    if (idx >= 0) hits[idx].classList.add(hitClass);
    /* .has-hit 让当前页把填充让给「手指着的那一项」（见 2-layout.css 注释）：
       填充 = 手在哪，边框 + 白色滑块 = 你在哪一页，任一时刻只有一块填充。 */
    host.classList.toggle("has-hit", idx >= 0);
  }

  function clearHit() {
    if (hot >= 0 && hits[hot]) hits[hot].classList.remove(hitClass);
    hot = -1;
    host.classList.remove("has-hit");
  }

  /* 玻璃整片贴到命中的条目上（尺寸已与条目 1:1，这里只做居中校正）。 */
  function placeTo(b, instant) {
    put(b.left + (b.width - W) / 2, b.top + (b.height - H) / 2, instant);
  }

  var live = false;
  var raf = 0;
  var px = 0,
    py = 0;

  function sync(instant) {
    var idx = hitIndex(px, py);
    setHit(idx);
    if (idx >= 0) {
      placeTo(hits[idx].getBoundingClientRect(), instant);
      fade(1);
      return;
    }
    rest(instant);
  }

  /* 没有命中时的落点 = **当前页那一项**（2026-10-20 追加）。
     主人「玻璃大小要贴合 active」的直读就是「玻璃该在 active 上」；
     只在悬停时出现的话，打开页面不动鼠标看着就是「玻璃怎么没有」。
     所以：手在条目上 ⇒ 跟着手；手在轨道空白处/离开轨道 ⇒ 回到当前页。
     玻璃因此常显，永远贴着某一块填充，不会出现「玻璃在、填充不在」的错位。 */
  function rest(instant) {
    setHit(-1);
    var a = host.querySelector(".nav-item.active");
    if (!a) {
      fade(0);
      return;
    }
    placeTo(a.getBoundingClientRect(), instant);
    fade(1);
  }

  function flush() {
    raf = 0;
    if (live) sync(false);
  }

  function onEnter(e) {
    px = e.clientX;
    py = e.clientY;
    live = true;
    /* 进场先落位再淡入：否则第一帧会从上一轮的停留点滑过来 */
    sync(true);
  }

  function onMove(e) {
    px = e.clientX;
    py = e.clientY;
    if (!live) {
      onEnter(e);
      return;
    }
    /* rAF 闸门：高刷鼠标一帧能来 3~4 个事件，quickTo 已经够顺，不必每个都算 */
    if (!raf) raf = requestAnimationFrame(flush);
  }

  function onLeave() {
    live = false;
    /* 手离开轨道：选中态还回真正的当前页，玻璃也回落到那一项上（不消失）。 */
    clearHit();
    rest(false);
  }

  /* 视口变化后：条目尺寸可能变（桌面轨道 ↔ 抽屉），玻璃重新量体裁衣；
     位置也重算（不带动画，免得拖尾）。 */
  function onResize() {
    fit();
    if (live) sync(true);
    else rest(true);
  }

  /* 当前页换了（路由把 .active 挪到别的条目）时，玻璃也要跟着搬过去 ——
     否则它会停在旧的那一项上，变成「玻璃和选中块错位」。
     只在鼠标不在轨道里时响应；否则我们自己挂/摘 .lens-hit 也会触发这个观察器。 */
  var mo = null;
  if (typeof MutationObserver === "function" && hits.length) {
    mo = new MutationObserver(function () {
      if (!live) rest(true);
    });
    for (var i = 0; i < hits.length; i++) {
      mo.observe(hits[i], { attributes: true, attributeFilter: ["class"] });
    }
  }

  host.addEventListener("pointerenter", onEnter);
  host.addEventListener("pointermove", onMove);
  host.addEventListener("pointerleave", onLeave);
  window.addEventListener("resize", onResize);

  /* 首次落位：直接把玻璃放在当前页那一项上（主人要的「贴合 active」）。
     必须等一帧 —— mounted 时布局可能还没稳，`.nav-item` 的 rect 会是 0。 */
  requestAnimationFrame(function () {
    fit();
    rest(true);
  });

  return function () {
    host.removeEventListener("pointerenter", onEnter);
    host.removeEventListener("pointermove", onMove);
    host.removeEventListener("pointerleave", onLeave);
    window.removeEventListener("resize", onResize);
    if (mo) mo.disconnect();
    clearHit();
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  };
}
