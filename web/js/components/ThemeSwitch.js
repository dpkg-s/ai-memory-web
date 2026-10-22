import { S, toast } from "../core/store.js";
import { applyTheme } from "../core/theme.js";
import { reduced } from "../core/anim.js";

/* ======================================================================
 * 日夜主题开关 · 矢量 1:1 移植（2026-10-20 第二版）
 *
 * 唯一事实源：SunnyDesignor/WpfGorgeousThemeSwitch 的 ToggleButtonStyles.xaml
 * （MIT）。上一版拿 CSS 圆和椭圆去「近似」，造型与动效细节全丢，主人判不合格。
 * 这一版改成**内联 SVG 逐条复刻**：路径字符串、坐标、渐变 stop、关键帧时间点
 * 全部照抄 XAML，不再有「画个圆代替」的东西。
 *
 * ---------------------------------------------------------------------------
 * 一、几何对照表（XAML → SVG，单位一律是 100×40 逻辑单位，缩放交给 --tsw-s）
 *
 *   frameBorder    100×40 r20，Clip = Rect(0,0,100,40) r20  ⇒ .tsw-box 的圆角裁切
 *   backBorder     #4685C0 ↔ #171E33                        ⇒ <rect class="tsw-sky">
 *   stars          11 颗 starGeometry 四角星，Canvas 整体 TranslateY=-36
 *   cloud1/2       Data 原样抄，Stretch=UniformToFill + Margin 换算成目标框
 *                  （cloud1: 2,2,-3,-9 ⇒ 101×47；cloud2: 2,8,-2,-8 ⇒ 100×40）
 *   glow1/2/3      79/67/55 圆形，Left + 垂直居中 ⇒ y = -19.5 / -13.5 / -7.5
 *   thumb          36×38 圆角 20，TranslateX=4，垂直居中 ⇒ translate(4 1)
 *   sun            33×33 r16.5 圆，fill #F3C62B，Clip 同尺寸
 *   moon           33×33 灰蓝 #C4C9D4 + 三颗陨石坑 + 高光/暗角弧，TranslateX=34
 *   ShadowElement  104×44 r21 @(-2,-2)，描边 #5C6170 1.8 —— 被胶囊裁切后**只剩
 *                  四个角的弧线残段**，这不是 bug，是原控件刻意留的护角
 *
 * 太阳/月亮上的弧（Data 完全相同的一枚「月牙」路径）在 WPF 里靠
 * Stretch=Uniform + Margin 定位。浏览器里没法直接照抄，所以在 mounted 时用
 * getBBox() 现场量、再写一条 transform —— 这比手算贝塞尔包围盒更贴 WPF 的
 * 语义（WPF 的 Stretch 用的也是几何 bounds）。
 *
 * ---------------------------------------------------------------------------
 * 二、时序对照表（Storyboard → GSAP timeline，秒为绝对时刻）
 *
 *   昼 → 夜（StoryboardChecked）
 *     thumb.x   0→0.6: 66（power2.inOut）· 0.6→1.5: 63（power2.out）   ← 有回弹
 *     sky       0→0.6: #171E33
 *     glow1/2/3 0→0.6: 23/35/47 · 0.6→1.3: 21/33/45
 *     cloud1/2  0→0.6: y 34 / 26（沉到画面外）
 *     stars.y   0→0.6: 3 · 0.6→1.3: 0（自 -36 升起，带一点过冲）
 *     moon.x    0→0.6: -1 · 0.6→1.3: 0
 *     star1..5  错峰闪：1.3/1.9/2.5 · 1.6/2.2/2.8 · 2.0/2.5/3.1 ·
 *                        2.2/2.7/3.3 · 2.6/3.0/3.6（ScaleX 1→0→1）
 *   夜 → 昼（StoryboardUnChecked）
 *     thumb.x   0→0.6: 2 · 0.6→1.3: 4
 *     sky       0→0.7: #4685C0
 *     glow1/2/3 0→0.6: -2 · 0.6→1.3: 0
 *     cloud1    0→0.6: -6 · 0.6→2.4: 4 · 2.4→3.6: 0
 *     cloud2    0→0.6: -4 · 0.6→1.8: 3 · 1.8→2.8: 0
 *     stars.y   0→0.6: -36
 *     moon.x    0→0.6: 34
 *   悬停（ThumbMouseHover / Leave）
 *     sun 自转 0→30°（0.6s）/ 30°→0（0.7s）· highlightMask opacity 0↔1（0.5s）
 *
 * ---------------------------------------------------------------------------
 * 三、为什么用 GSAP 而不是 CSS keyframes
 *
 *   这套动效有**回弹**（66→63、3→0）、有**两条不同时长的关键帧**、还有 5 颗星
 *   各自错峰的三段脉冲。CSS 要表达得写 12 组 keyframes 且没法中途打断；
 *   GSAP 一条 timeline 就是 XAML 一个 Storyboard，连「快速连点」都天然处理
 *   （kill 旧 timeline 再起新的）。--ease 那套 CSS token 在这里不适用，
 *   所以下面全部显式写 power2.inOut / power2.out —— 即 XAML 的 PowerEase。
 *
 * 🔴 与 theme.js 的分工不变：本组件只决定 pref，DOM 属性与 localStorage 仍由
 *    applyTheme 单点负责。
 * ==================================================================== */

/* ---- 原样抄自 XAML 的矢量数据 ---------------------------------------- */

/* starGeometry：100×100 四角星（凹边），WPF 用 Stretch 缩到 3/5/7 ---- */
var STAR_D =
  "M100,50C72.38589,50 50,72.38589 50,100C50,72.38589 27.61411,50 0,50" +
  "C27.61411,50 50,27.61411 50,0C50,27.61411 72.38589,50 100,50z";

/* 太阳高光/暗角、月亮高光/暗角共用的那枚月牙（WPF 里出现 4 次，Data 一致） */
var CRESCENT_D =
  "M195.79568,256.36186C128.27033,194.80746 208.6956,103.20326 276.96226,155.20326" +
  "C220.40909,129.80395 148.71988,171.59981 195.79568,256.36186z";

/* cloud1：Fill #88FFFFFF，Margin 2,2,-3,-9 */
var CLOUD1_D =
  "M158.99223,453.55724 C169.78284,423.31232 203.15378,392.41965 241.59875,404.12313" +
  " 261.99875,383.72313 299.3,391.57463 305.3,392.77701 330.15525,362.39707" +
  " 353.16314,370.00505 368.58869,378.91567 370.80287,377.8725 376.53823,377.01298" +
  " 381.06677,376.82559 387.43795,354.90123 410.63981,354.27147 420.4351,355.75324" +
  " 432.85079,341.48144 440.27525,342.83843 451.87985,342.32945 457.75133,307.27233" +
  " 472.82215,288.94564 509.06064,292.16184 512.31051,292.45027 525.93938,292.61638" +
  " 525.93938,292.61638 525.90428,295.34879 526.73875,460.86787 526.8053,465.68179" +
  " L154.99571,465.6552 z";

/* cloud2：Fill #FFFFFF，Width/Height 100×40 + Margin 2,8,-2,-8 */
var CLOUD2_D =
  "M158.99223,453.55724 C169.78284,423.31232 203.15378,392.41965 241.59875,404.12313" +
  " 261.99875,383.72313 299.3,391.57463 305.3,392.77701 337.22357,353.75764" +
  " 390.50003,373.43798 398.90003,384.97667 412.50003,378.21261 430.04088,381.41688" +
  " 430.04088,381.41688 436.82018,362.13027 456.18064,352.96024 465.00342,351.59457" +
  " 460.57167,304.02021 510.55723,292.35177 521.33687,292.25901 530.92623,292.1765" +
  " 525.93938,292.61638 525.93938,292.61638 525.90428,295.34879 526.73875,460.86787" +
  " 526.8053,465.68179 L154.99571,465.6552 z";

/* 11 颗星：[Canvas.Left, Canvas.Top, Width, 闪烁组]。
   闪烁组 0 = 常亮（原控件没给它 x:Name，从不参与动画）；
   1..5 对应 star1..star5，错峰时刻见文件头 §二。 */
var STARS = [
  [11.5, 26.5, 5, 0],
  [24.635, 26.5, 5, 3], /* star3 */
  [44.5, 29.5, 5, 5], /* star5 */
  [20.635, 5.5, 7, 1], /* star1 */
  [48.5, 10, 7, 2], /* star2 */
  [32.315, 12.5, 3, 0],
  [23.635, 18, 3, 0],
  [33.999, 24, 3, 0],
  [47, 22.5, 3, 0],
  [39.481, 7.997, 3, 0],
  [10, 11, 3, 4], /* star4 */
];

/* 五颗闪烁星的三个关键帧时刻（XAML 原值，秒） */
var TWINKLE = [
  [1, 1.3, 1.9, 2.5],
  [2, 1.6, 2.2, 2.8],
  [3, 2.0, 2.5, 3.1],
  [4, 2.2, 2.7, 3.3],
  [5, 2.6, 3.0, 3.6],
];

/* 两个终态（昼 / 夜）。GSAP 与手工兜底共用这一份数值。 */
var LIGHT = {
  thumb: 4,
  moon: 34,
  stars: -36,
  c1: 0,
  c2: 0,
  g1: 0,
  g2: 0,
  g3: 0,
  sky: "#4685C0",
};
var DARK = {
  thumb: 63,
  moon: 0,
  stars: 0,
  c1: 34,
  c2: 26,
  g1: 21,
  g2: 33,
  g3: 45,
  sky: "#171E33",
};

function starMarkup() {
  var out = "";
  for (var i = 0; i < STARS.length; i++) {
    var s = STARS[i];
    var k = s[2] / 100; /* starGeometry 是 100×100，缩到 3/5/7 */
    out +=
      '<g transform="translate(' + s[0] + " " + s[1] + ") scale(" + k + ')">' +
      '<path class="tsw-star' + (s[3] ? " t" + s[3] : "") + '" d="' + STAR_D + '" fill="#fff"/>' +
      "</g>";
  }
  return out;
}

/* 把 WPF 的「Stretch + Margin」换算成一条 transform。
   data-cover  有无 → UniformToFill（等比铺满并居中，可溢出）
   data-w/h    目标框（cover 用两个都填；contain 只填 w）
   data-x/y    目标框左上角；data-anchor="br" 时 x/y 指右下角
   data-rot    绕自身包围盒中心旋转（对应 RenderTransformOrigin 0.5,0.5） */
function fitPaths(root) {
  var list = root.querySelectorAll("path[data-fit]");
  for (var i = 0; i < list.length; i++) {
    var el = list[i];
    var d = el.dataset || {};
    var bb;
    try {
      bb = el.getBBox();
    } catch (e) {
      continue;
    }
    if (!bb.width || !bb.height) continue;

    var k, x, y;
    if (d.cover != null) {
      var cw = parseFloat(d.w), ch = parseFloat(d.h);
      k = Math.max(cw / bb.width, ch / bb.height);
      x = parseFloat(d.x) + (cw - bb.width * k) / 2;
      y = parseFloat(d.y) + (ch - bb.height * k) / 2;
    } else {
      k = parseFloat(d.w) / bb.width;
      x = parseFloat(d.x);
      y = d.anchor === "br" ? parseFloat(d.y) - bb.height * k : parseFloat(d.y);
    }

    var t =
      "translate(" + x + " " + y + ") scale(" + k + ") translate(" +
      -bb.x + " " + -bb.y + ")";
    if (d.rot) {
      t += " rotate(" + d.rot + " " + bb.width / 2 + " " + bb.height / 2 + ")";
    }
    el.setAttribute("transform", t);
  }
}

var ThemeSwitch = {
  data: function () {
    return { S: S };
  },
  computed: {
    night: function () {
      return S.theme === "dark";
    },
    tip: function () {
      var cur = this.night ? "深色" : "浅色";
      var tail = S.themePref === "auto" ? "（当前跟随系统）" : "";
      return "当前：" + cur + tail + " · 点击切换深浅 · 右键恢复跟随系统";
    },
  },
  watch: {
    night: function (v) {
      this.apply(v, true);
    },
  },
  methods: {
    toggle: function () {
      /* 动画期间不接受新点击（2026-10-22 第四轮，主人要求）：
         连点会让旧 timeline 被 kill、门控重新加锁，视觉上「滑块抖一下再重来」。
         互斥窗口 = timeline 主段（0.95s），到点自动放开。 */
      if (this._busy) return;
      var p = S.theme === "dark" ? "light" : "dark";
      S.themePref = p;
      /* 页面渐变与开关 timeline 同一帧起跑（单时钟）。 */
      S.theme = applyTheme(p);
    },
    followSystem: function () {
      if (this._busy) return;
      S.themePref = "auto";
      S.theme = applyTheme("auto");
      toast("info", "已跟随系统主题", "外观将随系统深浅色自动切换");
    },

    /* 悬停：太阳自转 30° + 高光罩淡入。WPF 挂在 thumb 的 MouseEnter 上，
       Web 挂在整颗按钮上更稳（thumb 只占 36×38，边缘擦过会闪）。 */
    hoverIn: function () {
      this.spin(30, 0.6);
      this.highlight(1, 0.5);
    },
    hoverOut: function () {
      this.spin(0, 0.7);
      this.highlight(0, 0.5);
    },
    spin: function (deg, dur) {
      var m = this._m;
      if (!m || !m.sun) return;
      var g = window.gsap;
      if (!g || reduced()) {
        m.sun.setAttribute("transform", deg ? "rotate(" + deg + " 16.5 16.5)" : "");
        return;
      }
      /* svgOrigin 是 GSAP 专给 SVG 用的「本地坐标系原点」，
         正好等价于 XAML 的 RenderTransformOrigin="0.5,0.5"（33×33 的中心）。 */
      g.to(m.sun, {
        rotation: deg,
        svgOrigin: "16.5 16.5",
        duration: dur,
        ease: "power2.inOut",
        overwrite: "auto",
      });
    },
    highlight: function (to, dur) {
      var m = this._m;
      if (!m || !m.hl) return;
      var g = window.gsap;
      if (!g || reduced()) {
        m.hl.setAttribute("opacity", String(to));
        return;
      }
      g.to(m.hl, { opacity: to, duration: dur, ease: "power2.inOut", overwrite: "auto" });
    },

    /* 一帧到位（无 GSAP / 减弱动效 / 首次挂载）—— 直接写属性，
       不经过 GSAP 缓存，保证任何情况下造型都对。 */
    setStatic: function (night) {
      var m = this._m;
      if (!m) return;
      var v = night ? DARK : LIGHT;
      m.thumb.setAttribute("transform", "translate(" + v.thumb + " 1)");
      m.moon.setAttribute("transform", "translate(" + v.moon + " 0)");
      m.stars.setAttribute("transform", "translate(0 " + v.stars + ")");
      m.c1.setAttribute("transform", "translate(0 " + v.c1 + ")");
      m.c2.setAttribute("transform", "translate(0 " + v.c2 + ")");
      m.g1.setAttribute("transform", "translate(" + v.g1 + " -19.5)");
      m.g2.setAttribute("transform", "translate(" + v.g2 + " -13.5)");
      m.g3.setAttribute("transform", "translate(" + v.g3 + " -7.5)");
      /* 🔴 天空色必须写 style.fill：GSAP 补的是 CSS 的 fill（落到 inline style），
         这里若写属性，inline style 会一直压住它 —— 首切之后属性值就永远停在
         上一态，探针读属性和眼睛看到的会是两个颜色。统一走 style 才不打架。 */
      m.sky.style.fill = v.sky;
      for (var i = 0; i < m.tw.length; i++) {
        m.tw[i].setAttribute("transform", "");
      }
    },

    /* ---- 门控串行（2026-10-22，主人选的方案 A）------------------------
     *
     * 症状：收纳（收窄）与点击切换同时起跑会打架。
     *
     * 根因不是「谁太快」，是**两条时钟抢同一个视觉结果**：
     *   · 收窄走 CSS 过渡（.tsw 的 width、.tsw-box 的 left，各 0.62s）；
     *   · 切换走 GSAP timeline（滑块 0→1.5s，云/星尾巴到 3.6s）。
     * 而 `.tsw.night .tsw-box { left: -59s }` 是**类切换即生效**的终态值，
     * 不看 GSAP 播到第几帧。于是点击后若鼠标移开：窗口先按终态左移 42.5px，
     * 滑块却还在半路 ⇒ 收窄后的 30.24px 窗口里只剩空天空，月亮被切成一半
     * 再滑出来。连点两次时两条运动还会相向而行，错位叠加。
     *
     * 方案 A：把「并行窗口期」清零 —— timeline 播放期间窗口锁定为全展开并
     * 禁用过渡（CSS 侧见 3-components.css §16 的 .tsw[data-anim="1"]），
     * 等滑块**第一段**落定（0.45s）后再解禁，此时若鼠标已移出，收窄才开始。
     *
     * 为什么锁到 0.45s 而不是 timeline 末尾（0.95s）：星星闪烁等尾巴与收窄窗口
     * 不冲突 —— 夜间星星在画面上方、滑块在右侧，收窄到滑块位后看到的是月亮；
     * 而 0.45s 后滑块已在 66、占 66~102，收窄窗口覆盖 59~101，月亮完整在窗内。
     * 锁更久只会让开关「大着不动」，反而钝（0.65 → 0.45 是主人两次催快的结论）。
     *
     * 🔴 为什么用 data-anim 而不是加 class（2026-10-22 实测踩到）：
     *    这个 button 的模板是 `class="tsw" :class="{night: night}"`。Vue 3 的
     *    options watch 默认 flush:'pre' ⇒ 点击后 watch 先跑（此时加类成功），
     *    紧接着本组件的 patch 重算 :class 并把整个 class 属性覆写成 "tsw  night"，
     *    手动加的类被**静默抹掉**。探针实测：classList.add("animating") 调用过 1 次，
     *    60ms 后 classList 里却没有它，MutationObserver 也只看到 "tsw > tsw > tsw"。
     *    data- 属性不在 Vue 的 diff 目标里，不会被覆盖，所以改走 data-anim。 */
    lock: function (on) {
      var btn = this._btn;
      if (!btn) return;
      if (this._unlock) {
        clearTimeout(this._unlock);
        this._unlock = null;
      }
      if (on) {
        btn.setAttribute("data-anim", "1");
        return;
      }
      /* 摘锁延迟 150 → 300ms（2026-10-22 第四轮，主人要求「动画结束后等 0.3 收纳」）：
         这个延迟就是「动画演完 → 停一拍 → 胶囊收窄」里那一拍。 */
      var self = this;
      this._unlock = setTimeout(function () {
        btn.removeAttribute("data-anim");
        self._unlock = null;
      }, 300);
    },

    /* 落终态：animate=false 只摆位；true 则播 timeline。 */
    apply: function (night, animate) {
      var m = this._m;
      if (!m) return;
      if (this._tl) {
        this._tl.kill();
        this._tl = null;
      }
      var g = window.gsap;
      if (!animate || !g || reduced()) {
        this._busy = false;
        this.lock(false);
        this.setStatic(night);
        return;
      }

      /* 不需要「先摆终态再起播」那一步：GSAP 在 tween 开始时读的正是当前
         inline 值（属性形式它也会解析），替它预置终态只会让首切瞬跳、动画白播。
         上一版在这里有过一次 _primed 预置，实测「第一次切换不演」就是它造成的。 */

      /* 门控：从这一刻起窗口锁定为全展开，直到滑块落定后再解禁。 */
      this.lock(true);
      /* 互斥窗口：动画期间 toggle / followSystem 直接早返回，连点不再互相 kill。 */
      this._busy = true;

      var self = this;
      /* 🔴 单时钟（2026-10-22 第三轮，主人定案 B）：View Transition 期间整页是
         静态快照，开关被冻在快照里 —— 等扩散结束再放行，就成了「页面先换完、
         开关 0.55s 后才补演」（实测错位 671ms）。撤掉 VT 后页面改走 0.45s 整页
         渐变，与本 timeline 同帧起跑，这里不需要任何等待。 */
      var t = (this._tl = g.timeline());
      /* 0.95s = 滑块**回弹段**结束（0→66 用 0.45s，66→63 用 0.5s）——
         也就是肉眼上「开关演完了」的时刻。此后 300ms 摘锁 ⇒ 动画结束 + 0.3s 才开始收窄。
         为什么不等星星闪烁的尾巴（到 2.55s，见 TWINKLE）：星星在画面上方、滑块在
         右侧，收窄后的窗口覆盖 59~101，月亮始终在窗内，等它只是白让开关「大着不动」。
         第四轮主人明确「动画结束后等 0.3 收纳」，所以从第二轮的 0.45s 前移到整段结束。 */
      t.call(function () {
        self._busy = false;
        self.lock(false);
      }, null, 0.95);
      if (night) {
        t.to(m.thumb, { x: 66, duration: 0.45, ease: "power2.inOut" }, 0).to(
          m.thumb,
          { x: 63, duration: 0.5, ease: "power2.out" },
          0.45,
        );
        t.to(m.sky, { fill: "#171E33", duration: 0.5, ease: "power2.out" }, 0);
        this.glowTrack(t, "g1", 23, 21);
        this.glowTrack(t, "g2", 35, 33);
        this.glowTrack(t, "g3", 47, 45);
        t.to(m.c1, { y: 34, duration: 0.45, ease: "power2.inOut" }, 0);
        t.to(m.c2, { y: 26, duration: 0.45, ease: "power2.inOut" }, 0);
        t.to(m.stars, { y: 3, duration: 0.45, ease: "power2.inOut" }, 0).to(
          m.stars,
          { y: 0, duration: 0.5, ease: "power2.out" },
          0.45,
        );
        t.to(m.moon, { x: -1, duration: 0.45, ease: "power2.inOut" }, 0).to(
          m.moon,
          { x: 0, duration: 0.5, ease: "power2.out" },
          0.45,
        );
        /* 五颗星各自 1→0→1 的三段脉冲，时刻见 TWINKLE */
        for (var i = 0; i < TWINKLE.length; i++) {
          var w = TWINKLE[i];
          var el = m["t" + w[0]];
          if (!el) continue;
          t.set(el, { scaleX: 1 }, w[1]);
          t.to(el, { scaleX: 0, duration: w[2] - w[1], ease: "none" }, w[1]);
          t.to(el, { scaleX: 1, duration: w[3] - w[2], ease: "none" }, w[2]);
        }
      } else {
        t.to(m.thumb, { x: 2, duration: 0.45, ease: "power2.inOut" }, 0).to(
          m.thumb,
          { x: 4, duration: 0.5, ease: "power2.out" },
          0.45,
        );
        t.to(m.sky, { fill: "#4685C0", duration: 0.55, ease: "power2.inOut" }, 0);
        this.glowTrack(t, "g1", -2, 0);
        this.glowTrack(t, "g2", -2, 0);
        this.glowTrack(t, "g3", -2, 0);
        t.to(m.c1, { y: -6, duration: 0.45, ease: "power2.inOut" }, 0)
          .to(m.c1, { y: 4, duration: 1.2, ease: "power2.inOut" }, 0.45)
          .to(m.c1, { y: 0, duration: 0.9, ease: "power2.inOut" }, 1.65);
        t.to(m.c2, { y: -4, duration: 0.45, ease: "power2.inOut" }, 0)
          .to(m.c2, { y: 3, duration: 0.8, ease: "power2.inOut" }, 0.45)
          .to(m.c2, { y: 0, duration: 0.7, ease: "power2.inOut" }, 1.25);
        t.to(m.stars, { y: -36, duration: 0.45, ease: "power2.inOut" }, 0);
        t.to(m.moon, { x: 34, duration: 0.45, ease: "power2.inOut" }, 0);
        for (var j = 0; j < m.tw.length; j++) t.set(m.tw[j], { scaleX: 1 }, 0);
      }
    },

    /* 光晕是「冲到过冲位、再微收回」两段，日月两向共用。
       0.6/0.7 → 0.5/0.5（2026-10-22 第二轮，与滑块首段同频）。 */
    glowTrack: function (t, key, peak, rest) {
      var m = this._m;
      t.to(m[key], { x: peak, duration: 0.5, ease: "power2.inOut" }, 0).to(
        m[key],
        { x: rest, duration: 0.5, ease: "power2.out" },
        0.45,
      );
    },
  },
  mounted: function () {
    var root = this.$el;
    this._btn = root.querySelector(".tsw");
    this._m = {
      sky: root.querySelector(".tsw-sky"),
      stars: root.querySelector(".tsw-stars"),
      c1: root.querySelector(".tsw-c1"),
      c2: root.querySelector(".tsw-c2"),
      g1: root.querySelector(".tsw-g1"),
      g2: root.querySelector(".tsw-g2"),
      g3: root.querySelector(".tsw-g3"),
      thumb: root.querySelector(".tsw-thumb"),
      moon: root.querySelector(".tsw-moon"),
      sun: root.querySelector(".tsw-sunrot"),
      hl: root.querySelector(".tsw-hl"),
      t1: root.querySelector(".tsw-star.t1"),
      t2: root.querySelector(".tsw-star.t2"),
      t3: root.querySelector(".tsw-star.t3"),
      t4: root.querySelector(".tsw-star.t4"),
      t5: root.querySelector(".tsw-star.t5"),
      tw: root.querySelectorAll(".tsw-star"),
    };
    fitPaths(root);
    this.apply(this.night, false);
  },
  beforeUnmount: function () {
    if (this._tl) {
      this._tl.kill();
      this._tl = null;
    }
    /* 门控定时器必须清掉：它闭包里攥着 DOM 节点，组件销毁后再触发没有意义。 */
    if (this._unlock) {
      clearTimeout(this._unlock);
      this._unlock = null;
    }
  },
  template:
    '<span class="tsw-wrap">' +
    '<button class="tsw" :class="{night: night}" type="button" :title="tip"' +
    '        :aria-label="night ? \'切换到浅色\' : \'切换到深色\'" :aria-pressed="night"' +
    '        @click="toggle" @contextmenu.prevent="followSystem"' +
    '        @mouseenter="hoverIn" @mouseleave="hoverOut" @focus="hoverIn" @blur="hoverOut">' +
    '  <span class="tsw-box">' +
    '  <svg class="tsw-svg" viewBox="0 0 100 40" width="100" height="40"' +
    '       aria-hidden="true" focusable="false">' +
    "  <defs>" +
    '    <clipPath id="tswSunClip"><rect width="33" height="33" rx="16.5" ry="16.5"/></clipPath>' +
    '    <radialGradient id="tswVig" cx="0.5" cy="0.5" r="0.5">' +
    '      <stop offset="0.7" stop-color="#000" stop-opacity="0.9"/>' +
    '      <stop offset="1" stop-color="#000" stop-opacity="0"/>' +
    "    </radialGradient>" +
    '    <linearGradient id="tswSunHi" x1="0.5" y1="0" x2="0.3" y2="1">' +
    '      <stop offset="0" stop-color="#fff" stop-opacity="0"/>' +
    '      <stop offset="0.1" stop-color="#fff" stop-opacity="1"/>' +
    '      <stop offset="1" stop-color="#fff" stop-opacity="0"/>' +
    "    </linearGradient>" +
    '    <linearGradient id="tswSunLo" x1="1" y1="0" x2="0" y2="1">' +
    '      <stop offset="0" stop-color="#000" stop-opacity="0"/>' +
    '      <stop offset="0.3" stop-color="#000" stop-opacity="0.4"/>' +
    '      <stop offset="1" stop-color="#000" stop-opacity="0"/>' +
    "    </linearGradient>" +
    '    <linearGradient id="tswMoonHi" x1="0.5" y1="0" x2="0.5" y2="1">' +
    '      <stop offset="0" stop-color="#fff" stop-opacity="0"/>' +
    '      <stop offset="0.2" stop-color="#fff" stop-opacity="0.87"/>' +
    '      <stop offset="1" stop-color="#fff" stop-opacity="0"/>' +
    "    </linearGradient>" +
    '    <linearGradient id="tswMoonLo" x1="0.2" y1="0" x2="0.5" y2="1">' +
    '      <stop offset="0" stop-color="#000" stop-opacity="0"/>' +
    '      <stop offset="0.1" stop-color="#000" stop-opacity="0.4"/>' +
    '      <stop offset="1" stop-color="#000" stop-opacity="0"/>' +
    "    </linearGradient>" +
    '    <linearGradient id="tswHL" x1="0" y1="0" x2="1" y2="1">' +
    '      <stop offset="0" stop-color="#fff" stop-opacity="0.44"/>' +
    '      <stop offset="1" stop-color="#fff" stop-opacity="0"/>' +
    "    </linearGradient>" +
    "  </defs>" +
    /* 天空 */
    '  <rect class="tsw-sky" width="100" height="40" rx="20" fill="#4685C0"/>' +
    /* 星星（整体 TranslateY=-36，白天在画面外） */
    '  <g class="tsw-stars" transform="translate(0 -36)">' +
    starMarkup() +
    "  </g>" +
    /* 两层云：云与太阳/月亮之间没有别的图层，顺序即原 XAML 顺序 */
    '  <g class="tsw-c1" transform="translate(0 0)">' +
    '    <path data-fit data-cover="1" data-x="2" data-y="2" data-w="101" data-h="47"' +
    '          fill="#ffffff" fill-opacity="0.533" d="' + CLOUD1_D + '"/>' +
    "  </g>" +
    '  <g class="tsw-c2" transform="translate(0 0)">' +
    '    <path data-fit data-cover="1" data-x="2" data-y="8" data-w="100" data-h="40"' +
    '          fill="#ffffff" d="' + CLOUD2_D + '"/>' +
    "  </g>" +
    /* 三层光晕（79/67/55 圆，左对齐垂直居中） */
    '  <g class="tsw-g1" transform="translate(0 -19.5)">' +
    '    <rect width="79" height="79" rx="39.5" fill="#fff" fill-opacity="0.067"/></g>' +
    '  <g class="tsw-g2" transform="translate(0 -13.5)">' +
    '    <rect width="67" height="67" rx="33.5" fill="#fff" fill-opacity="0.133"/></g>' +
    '  <g class="tsw-g3" transform="translate(0 -7.5)">' +
    '    <rect width="55" height="55" rx="27.5" fill="#fff" fill-opacity="0.133"/></g>' +
    /* 滑块：36×38 圆角 20，TranslateX=4，垂直居中 ⇒ y=1 */
    '  <g class="tsw-thumb" transform="translate(4 1)">' +
    '    <rect x="0" y="2.5" width="36" height="36" rx="18" fill="url(#tswVig)"/>' +
    '    <g transform="translate(0 2.5)" clip-path="url(#tswSunClip)">' +
    '      <g class="tsw-sunrot">' +
    '        <rect width="33" height="33" fill="#F3C62B"/>' +
    '        <path data-fit data-x="-1.5" data-y="-1.5" data-w="29" data-rot="2"' +
    '              fill="url(#tswSunHi)" d="' + CRESCENT_D + '"/>' +
    '        <path data-fit data-anchor="br" data-x="33.6" data-y="35.2" data-w="28" data-rot="200"' +
    '              fill="url(#tswSunLo)" d="' + CRESCENT_D + '"/>' +
    '        <rect class="tsw-hl" width="33" height="33" fill="url(#tswHL)" opacity="0"/>' +
    '        <g class="tsw-moon" transform="translate(34 0)">' +
    '          <rect width="33" height="33" fill="#C4C9D4"/>' +
    '          <circle cx="11" cy="19" r="5" fill="#9A9FB2" stroke="#000" stroke-opacity="0.4" stroke-width="0.6"/>' +
    '          <circle cx="16" cy="8" r="3" fill="#9A9FB2" stroke="#000" stroke-opacity="0.4" stroke-width="0.6"/>' +
    '          <circle cx="23.5" cy="21.5" r="3.5" fill="#9A9FB2" stroke="#000" stroke-opacity="0.4" stroke-width="0.6"/>' +
    '          <path data-fit data-x="-1.5" data-y="-1.5" data-w="29" data-rot="2"' +
    '                fill="url(#tswMoonHi)" d="' + CRESCENT_D + '"/>' +
    '          <path data-fit data-anchor="br" data-x="34" data-y="35" data-w="28" data-rot="192"' +
    '                fill="url(#tswMoonLo)" d="' + CRESCENT_D + '"/>' +
    "        </g>" +
    "      </g>" +
    "    </g>" +
    "  </g>" +
    /* 护角描边：WPF 的 Border 把 1.8 的描边画在**边界内侧**（外沿 -2,-2 / 104×44
       r21，内沿 -0.2 r19.2），SVG 的 stroke 却是骑在中线上 —— 所以矩形的几何边
       要按中线缩到 -1.1 / 102.2×42.2 / r20.1 才与原文重合。被胶囊裁切后只剩
       四个角的弧段，这是原控件刻意留的护角。 */
    '  <rect class="tsw-ring" x="-1.1" y="-1.1" width="102.2" height="42.2" rx="20.1"' +
    '        fill="none" stroke="#5C6170" stroke-width="1.8"/>' +
    "  </svg>" +
    "  </span>" +
    "</button></span>",
};

export { ThemeSwitch };
