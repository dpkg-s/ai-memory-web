/* ============================================================================
 * core/lg.js —— 液态玻璃（Liquid Glass）折射滤镜工厂
 *
 * 出处：`liquid-glass.md`（Graphite Workspace 悬浮 Dock 的落地经验，2026-10-15）。
 * 那份文档用的是 React 库 @vepando/liquid-glass-react，本项目是**零构建 + 手写
 * 原生模块**，装不了 npm 包，于是按文档第二节的**技术本质**自己做最小实现：
 *
 *   Snell 定律（n≈1.5）算出边圈每个像素的采样偏移
 *     → 编码成 R/G 通道的位移贴图（128 = 不偏移）
 *     → feDisplacementMap 挂进 backdrop-filter。
 *
 * 两个消费方（同一套贴图生成，只是几何来源不同）：
 *   · dressLens(el)   悬停透镜，固定 38×38（侧栏跟手玻璃珠，2026-10-20）
 *   · dressPanel(el)  面板，尺寸运行时量（侧栏 64 × 视口高，2026-10-20）
 *
 * 📌 1.4.1 删掉了 dressGlass / install / LG 三件遗留：它们是原悬浮 Dock 的
 *    「36×36 固定尺寸 + 安装式单例」接口，Dock 撤除后已无消费方。
 *    现在只剩「透镜」和「面板」两条路，各自把尺寸收在自己的常量里。
 *
 * 为什么不用 feTurbulence「假装」玻璃：湍流是噪声，只能做磨砂；真玻璃的边圈是
 * **有方向的偏折**（背景条纹在边缘弯折），必须用位移贴图，否则一眼假。
 *
 * ---------------------------------------------------------------------------
 * 🔴 三条硬约束（都是实测/文档明确的坑，别绕）
 *
 *  1. **玻璃叠玻璃必须用兄弟节点**（文档 §5）。透镜若嵌进玻璃条内部，它的
 *     backdrop-filter 拿到的是空 backdrop root，折射直接失效。所以 .lg-lens 与
 *     各个 .lg-btn 是兄弟，且透镜 pointer-events:none。
 *  2. **贴图尺寸必须与元素盒子 1:1**。feImage 的 preserveAspectRatio="none" 会把
 *     贴图拉伸到滤镜区域，尺寸不一致时圆角与位移错位（边缘出现硬折线）。
 *     因此本文件把「贴图尺寸」与「元素尺寸」收口在同一份 LG 常量里，
 *     元素尺寸由 JS 内联写入，物理上不可能不一致。
 *  3. **不能让 CSS 里硬写 url(#id)**。滤镜缺失时（脚本没跑到）Chrome 会把整条
 *     backdrop-filter 判为无效 ⇒ 元素**完全不可见**。所以静态 CSS 只写
 *     blur/saturate 兜底，折射由 JS 在滤镜装好之后**追加**上去。
 *
 * 兼容性（文档 §7）：完整折射仅 Chromium 系；其它引擎 CSS.supports 返回 false，
 * 停留在「重霜化模糊玻璃」的兜底外观 —— 这正是文档推荐的降级路径，不必另写。
 * ========================================================================== */

var PANEL_ID = "lg-panel";
var svgRoot = null; // 承载所有 <filter> 的 0×0 svg
var reg = {}; // filterId -> { feImg, disp }，便于原地换贴图而不重建节点

/* 圆角矩形 SDF（内负外正），位移方向取它的梯度即「向外的法线」。 */
function sdfRoundedRect(px, py, w, h, r) {
  var qx = Math.abs(px - w / 2) - (w / 2 - r);
  var qy = Math.abs(py - h / 2) - (h / 2 - r);
  var ax = Math.max(qx, 0);
  var ay = Math.max(qy, 0);
  return Math.hypot(ax, ay) + Math.min(Math.max(qx, qy), 0) - r;
}

/* 生成位移贴图：中心区 128/128（不偏移），边圈沿法线给出正比于
   (1 - 距边/bezel)^2.2 的偏移量 —— 越贴边折得越狠，向内迅速归零，
   于是「只有边圈在弯」而不是整块玻璃都在糊。

   `o.inward`：位移方向取反（法线朝内）。
     · 默认（朝外）适合**大块面板** —— 边缘像是把外面的东西「吸」进来；
     · 凸透镜（我们的悬停玻璃片）必须**朝内**：透镜成像是把内侧一小块放大，
       取样本就来自内侧；更关键的是 CSS backdrop-filter 的 backdrop 只覆盖
       元素盒自己，朝外采样会采到盒子以外的空白 ⇒ 四角糊出黑色三角
       （2026-10-20 实测：玻璃与条目等大后右下角出现黑楔子）。*/
function buildMap(o) {
  var w = o.w,
    h = o.h,
    r = o.r,
    bezel = o.bezel,
    scale = o.scale;
  var dir = o.inward ? -1 : 1;
  var c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  var ctx = c.getContext("2d");
  var img = ctx.createImageData(w, h);
  var E = 0.75; // 法线的有限差分步长
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      var px = x + 0.5,
        py = y + 0.5;
      var i = (y * w + x) * 4;
      img.data[i] = 128;
      img.data[i + 1] = 128;
      img.data[i + 2] = 128;
      img.data[i + 3] = 255;
      var inside = -sdfRoundedRect(px, py, w, h, r);
      if (inside <= 0 || inside > bezel) continue;
      var t = 1 - inside / bezel; // 边沿 1 → bezel 内界 0
      var nx = sdfRoundedRect(px + E, py, w, h, r) - sdfRoundedRect(px - E, py, w, h, r);
      var ny = sdfRoundedRect(px, py + E, w, h, r) - sdfRoundedRect(px, py - E, w, h, r);
      var len = Math.hypot(nx, ny) || 1;
      nx /= len;
      ny /= len;
      var mag = Math.pow(t, 2.2) * bezel * 1.15;
      /* 圆角弧段减幅（2026-10-20）：直边上法线是轴对齐的（|nx·ny| = 0），
         圆角处法线指向 45°（|nx·ny| ≈ 0.5）。玻璃四角本来也折不动光，
         而且 Chromium **不会把 feDisplacementMap 的输出裁到 border-radius** ——
         角落的位移会采到盒子外的空 backdrop，糊出黑三角（实测，
         玻璃与条目等大后右下角特别明显）。这里用一个"角越圆越不折"的权重
         把弧段平滑压到 0，既除掉了黑角，也符合物理直觉。 */
      mag *= 1 - 2 * Math.abs(nx * ny);
      var dx = (dir * nx * mag) / scale; // 归一化到 ±0.5
      var dy = (dir * ny * mag) / scale;
      img.data[i] = Math.round(255 * (0.5 + Math.max(-0.5, Math.min(0.5, dx))));
      img.data[i + 1] = Math.round(255 * (0.5 + Math.max(-0.5, Math.min(0.5, dy))));
    }
  }
  ctx.putImageData(img, 0, 0);
  return c.toDataURL("image/png");
}

function supported() {
  try {
    return (
      !!window.CSS &&
      !!CSS.supports &&
      CSS.supports("backdrop-filter", "url(#lg-probe)")
    );
  } catch (e) {
    return false;
  }
}

/* 所有滤镜共用一个 0×0 的宿主 svg（挂 body）。
   一个 filter 一个 id，同 id 重复挂载只换贴图、不重建节点 —— 面板在 resize
   时会反复重算贴图，重建节点会让 backdrop-filter 短暂失效并闪一下。 */
function mountFilter(id, mapUrl, scale) {
  var NS = "http://www.w3.org/2000/svg";
  if (!svgRoot) {
    svgRoot = document.createElementNS(NS, "svg");
    svgRoot.setAttribute("width", "0");
    svgRoot.setAttribute("height", "0");
    svgRoot.setAttribute("aria-hidden", "true");
    svgRoot.style.cssText = "position:absolute;width:0;height:0;overflow:hidden";
    document.body.appendChild(svgRoot);
  }
  var entry = reg[id];
  if (!entry) {
    var filter = document.createElementNS(NS, "filter");
    filter.setAttribute("id", id);
    /* 区域必须正好覆盖元素盒子：留白会让位移被裁掉，溢出的部分则取不到贴图。 */
    filter.setAttribute("x", "0");
    filter.setAttribute("y", "0");
    filter.setAttribute("width", "100%");
    filter.setAttribute("height", "100%");
    /* sRGB：默认的 linearRGB 会让贴图里的 128 在解码后被伽马校正，
       结果是「不偏移」的位置也轻微偏移，边缘出现一圈脏。 */
    filter.setAttribute("color-interpolation-filters", "sRGB");
    var feImg = document.createElementNS(NS, "feImage");
    feImg.setAttribute("preserveAspectRatio", "none");
    feImg.setAttribute("width", "100%");
    feImg.setAttribute("height", "100%");
    feImg.setAttribute("result", "map");
    var disp = document.createElementNS(NS, "feDisplacementMap");
    disp.setAttribute("in", "SourceGraphic");
    disp.setAttribute("in2", "map");
    disp.setAttribute("xChannelSelector", "R");
    disp.setAttribute("yChannelSelector", "G");
    filter.appendChild(feImg);
    filter.appendChild(disp);
    svgRoot.appendChild(filter);
    entry = reg[id] = { feImg: feImg, disp: disp };
  }
  entry.feImg.setAttribute("href", mapUrl);
  entry.disp.setAttribute("scale", String(scale));
  return id;
}

/* ============================================================================
 * 悬停透镜（2026-10-20）：与 dressPanel 同一套贴图，但**单独一份几何**
 *
 * 为什么不能复用面板那套（bezel 11 / scale 20）：那是给 64×视口高的整块侧栏用的，
 * 折射对象是页面的浅色背景。透镜压在 19px 图标上时，那套参数会把图标折成一团糊，
 * 实测截图里 `>` 和 `-` 已经完全认不出来。所以透镜收一档：边圈更薄、位移更轻 ——
 * 目标是「图标在玻璃底下微微弯」，而不是「图标被搅成漩涡」。
 *
 * 🔴 w/h 只是**兜底值**：真正的尺寸由 core/lens.js 从 `.nav-item` 量出来传进来
 *    （主人 2026-10-20：「玻璃大小要贴合 active」⇒ 玻璃与条目 1:1 等大）。
 *    侧栏宽度是响应式的，写死会在抽屉/窄屏错位。
 *    r 必须与 `.nav-item` 的 `--r-sm`（8px）一致，否则圆角与位移错位。
 *
 * 🔴 scale 只能到 2（实测边界，别往上调）：
 *    玻璃与条目等大后，位移一旦超过约 1px，右下角就会糊出一块**深色楔子** ——
 *    Chromium 不把 feDisplacementMap 的输出裁到 border-radius，圆角外侧那几像素
 *    位移后采到的是盒子外的空 backdrop。实测对照：scale=2 干净、3 有淡痕、
 *    4 起明显。所以「折射」在这块 44×43 的玻璃片上只能是很淡的一层 ——
 *    反正 19px 图标也经不起强折（早期 scale=15/22 时图标直接被搅成糊）。
 *    另有两条减幅措施配合：`inward`（向内采样）+ 圆角弧段权重 `1-2|nx·ny|`，
 *    它们不改变观感，但把采样点全部压回元素盒内，是 scale 能到 2 的前提。
 * ========================================================================== */
export var LENS = { w: 44, h: 43, r: 8, bezel: 6, scale: 2 };
var LENS_ID = "lg-lens";

/**
 * 给悬停透镜上妆。尺寸**由调用方量好传进来**（侧栏条目 = 44×43 那种），
 * 传了就用，没传退回 LENS 的默认值 —— 贴图与元素盒必须 1:1（约束 2），
 * 所以两者在这里一起写，中间不存在「只改了一边」的窗口。
 * @param {object} [opt] { w, h, base, fallback }
 * @returns {boolean} 是否用上了真折射
 */
export function dressLens(el, opt) {
  if (!el) return false;
  opt = opt || {};
  var w = Math.round(opt.w || LENS.w);
  var h = Math.round(opt.h || LENS.h);
  el.style.width = w + "px";
  el.style.height = h + "px";
  if (!supported()) {
    var fb = opt.fallback || "blur(7px) saturate(1.35)";
    el.style.backdropFilter = fb;
    el.style.webkitBackdropFilter = fb;
    el.classList.remove("lg-refract");
    return false;
  }
  mountFilter(
    LENS_ID,
    buildMap({ w: w, h: h, r: LENS.r, bezel: LENS.bezel, scale: LENS.scale, inward: true }),
    LENS.scale,
  );
  var v = (opt.base || "blur(0.6px) saturate(1.6) brightness(1.05)") + " url(#" + LENS_ID + ")";
  el.style.backdropFilter = v;
  el.style.webkitBackdropFilter = v;
  el.classList.add("lg-refract");
  return true;
}

/* ============================================================================
 * 大块玻璃（2026-10-20）：侧栏 A 档「原地玻璃」
 *
 * 与透镜的区别只在**尺寸来源**：透镜是固定 36×36，面板是布局给的（侧栏是
 * 64px × 视口高）。约束 2 要求贴图与盒子 1:1，所以尺寸必须在运行时量，
 * 且视口高度变了要重算 —— 这也是本函数返回 teardown 的原因。
 *
 * ⚠️ 尺寸**不写死**到元素上（透镜那套 dressLens 才写死）：面板的宽高由
 *    布局决定，写死会把响应式布局顶掉。
 *
 * 🔴 A 档的固有局限（已与主人确认）：侧栏背后只有纯色底，折射没有对比度，
 *    观感上更接近「磨砂玻璃 + 边缘一圈光」。真正让折射可读的是背景里的
 *    `.rail-glass-bg` 光晕层 + 右侧镜面边（见 3-components.css §18）。
 * ========================================================================== */
export var PANEL = { bezel: 11, scale: 20 };

/**
 * @param {Element} el  玻璃元素（须是 fixed/absolute 定位的实心块）
 * @param {object} [opt] { id, bezel, scale, base, fallback }
 * @returns {function|null} teardown；元素尺寸为 0 时返回 null（如窄屏抽屉态）
 */
export function dressPanel(el, opt) {
  if (!el) return null;
  opt = opt || {};
  var id = opt.id || PANEL_ID;
  var bezel = opt.bezel == null ? PANEL.bezel : opt.bezel;
  var scale = opt.scale == null ? PANEL.scale : opt.scale;
  var base = opt.base || "saturate(150%) blur(16px) brightness(1.04)";
  var fallback = opt.fallback || "saturate(135%) blur(18px) brightness(1.02)";

  var apply = function () {
    var w = Math.round(el.offsetWidth);
    var h = Math.round(el.offsetHeight);
    /* 抽屉态（--sidebar-w:0）宽 0，没有可折的区域，直接跳过 —— 
       此时由 CSS 的兜底模糊顶着，视觉上不空。 */
    if (!w || !h) return false;
    if (!supported()) {
      el.style.backdropFilter = fallback;
      el.style.webkitBackdropFilter = fallback;
      el.classList.remove("lg-refract");
      return false;
    }
    mountFilter(id, buildMap({ w: w, h: h, r: 0, bezel: bezel, scale: scale }), scale);
    var v = base + " url(#" + id + ")";
    el.style.backdropFilter = v;
    el.style.webkitBackdropFilter = v;
    el.classList.add("lg-refract");
    return true;
  };

  apply();

  var timer = 0;
  var later = function () {
    clearTimeout(timer);
    timer = setTimeout(apply, 180); // 拖窗口时别每帧重算贴图
  };
  window.addEventListener("resize", later);
  var ro = null;
  if (typeof ResizeObserver === "function") {
    ro = new ResizeObserver(later);
    ro.observe(el);
  }
  return function () {
    clearTimeout(timer);
    window.removeEventListener("resize", later);
    if (ro) ro.disconnect();
  };
}
