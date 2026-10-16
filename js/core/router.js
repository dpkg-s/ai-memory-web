import { h, nextTick } from "../../vendor/vue.esm-browser.prod.js";
import { loadTools } from "./data.js";
import { S } from "./store.js";
import { loadThresholds } from "../features/settings.js";

/* ======================================================================
 * 7. hash 路由
 * ==================================================================== */
var PAGES = ["dashboard", "console", "library", "settings"];
function readHash() {
  var m = (location.hash || "").replace(/^#\/?/, "").split("?")[0];
  return PAGES.indexOf(m) >= 0 ? m : "dashboard";
}
function go(page) {
  location.hash = "#/" + page;
}

/* 导航指示条定位：把 .nav-ind 滑到当前 active 条目的垂直位置。
   用两侧 getBoundingClientRect 求**差**，而不是 offsetTop ——
   .sidebar 是 position:fixed，窄屏还是带 transform 的抽屉，offsetParent
   语义在那种状态下不可靠；求差则天然免疫整体平移。
   animate=false 时先摘掉 transition、写完值强制重排再挂回，否则首次进入会
   从 (0,0) 滑到目标位，像是「指示条自己飞过来」。

   ⚠️ 2026-10-16：与配置页左栏的 syncCfgInd **统一**（css/6-anim.css §17l 一份定义
   两处挂载）。因此这里跟它保持同一套契约：
     · 几何写 `--ind-y / --ind-h` 到 **root（.sidebar）** 上，而不是主条自己身上
       —— 自定义属性只沿后代继承，写在主条上时兄弟残影读不到；
     · 残影 `.nav-ind-trail` 与主条同步 `.on`；
     · 首帧 / resize 给 root 挂 `.ind-noanim`，闸掉**残影**的过渡（主条靠内联
       `transition: none`，闸不到兄弟元素）。
   之前这三个特征只在配置页那侧有 ⇒ 两处切换线的观感开始漂移，这就是「不同步」。 */
function syncNavInd(animate) {
  var sb = document.querySelector(".sidebar");
  var ind = sb && sb.querySelector(".nav-ind");
  if (!sb || !ind) return;
  var trail = sb.querySelector(".nav-ind-trail");
  var item = sb.querySelector(".nav-item.active");
  if (!item) {
    ind.classList.remove("on");
    if (trail) trail.classList.remove("on");
    return;
  }
  var ir = item.getBoundingClientRect();
  var sr = sb.getBoundingClientRect();
  /* 指示条固定 20px 并垂直居中于条目；条目本身更矮时以条目高度为准，
     免得在短条目上探出上下两端。 */
  var h = Math.min(20, Math.round(ir.height));
  var y = Math.round(ir.top - sr.top + (ir.height - h) / 2);
  if (!animate) {
    ind.style.transition = "none";
    sb.classList.add("ind-noanim");
  }
  sb.style.setProperty("--ind-y", y + "px");
  sb.style.setProperty("--ind-h", h + "px");
  if (!animate) {
    void ind.offsetWidth;
    ind.style.transition = "";
    sb.classList.remove("ind-noanim");
  }
  ind.classList.add("on");
  if (trail) trail.classList.add("on");
}

/* 终端视图 tab 的滑动指示条定位（横向版 syncNavInd）。
   同样用 rect 求差：.term-tabs 是 flex 子项，宽度随中栏档位变化，
   写死像素值在缩放窗口后立刻错位。 */
function syncTabInd(root) {
  if (!root) return;
  var ind = root.querySelector(".tab-ind");
  if (!ind) return;
  var act = root.querySelector(".tab.active");
  if (!act) {
    ind.style.opacity = "0";
    return;
  }
  var ar = act.getBoundingClientRect();
  var rr = root.getBoundingClientRect();
  var x = Math.round(ar.left - rr.left + root.scrollLeft);
  /* 下划线两侧各内缩 8px，免得贴着 tab 的圆角 */
  ind.style.width = Math.max(0, Math.round(ar.width - 16)) + "px";
  ind.style.transform = "translateX(" + (x + 8) + "px)";
  ind.style.opacity = "1";
}

/* 配置页左栏 CONFIGURATION 导航的滑动指示条（纵向 —— 与 syncNavInd 同款）。
   🔴 2026-10-16：与 syncNavInd **统一**（css/6-anim.css §17l 一份定义、两处挂载），
   两者的契约完全一致：几何写 root、残影同步 .on、首帧挂 .ind-noanim。
   唯一的差别是**包含块**：那边是 .sidebar（position: fixed），这边是 .cfg-nav
   （position: sticky）—— sticky 同样是定位元素，绝对定位的指示条照常以它为参照，
   **不需要**再给 .cfg-nav 补 position: relative（那是 position 的互斥取值，
   写了会把 sticky 顶掉，导航就不吸顶了）。

   仍然走 rect 求差，不写死像素：.cfg-item 的高度 = padding 20 + 图标 17 +
   边框 2 ≈ 39px，但这套算术会随字号与浏览器 zoom 漂移；而且 cfg-sec 分组标题
   的高度也不是整数。求差是唯一在缩放后仍然正确的口径（同 syncTabInd）。

   @param {Element} root    .cfg-nav 元素
   @param {boolean} animate true = 带滑动过渡；false = 直接落位（首帧 / resize） */
function syncCfgInd(root, animate) {
  if (!root) return;
  var ind = root.querySelector(".cfg-ind");
  if (!ind) return;
  /* 拖尾残影（§17j ② v2）：与 .cfg-ind 同级的兄弟元素。它读的是**同一份**
     --ind-y / --ind-h，但过渡更长、还带 80ms 延迟 ⇒ 主体先走、残影慢半拍跟上。
     ⚠️ 几何写在 root（.cfg-nav）上、而不是 ind 上：自定义属性只沿**后代**继承，
     写在 ind 上的话兄弟元素读不到。写在 root 上两边都继承得到，探针从 .cfg-ind
     的 computed 值里读 --ind-y 也照旧拿得到（继承值）。
     ⚠️ 缺了它不算致命（旧缓存 HTML / 模板改坏时），所以这里全程 if (trail)。 */
  var trail = root.querySelector(".cfg-trail");
  var item = root.querySelector(".cfg-item.active");
  if (!item) {
    /* 没有选中项（理论上不会发生：tab 恒有默认值）—— 收起指示条而不是
       留在上一个位置当装饰。 */
    ind.classList.remove("on");
    if (trail) trail.classList.remove("on");
    return;
  }
  var ir = item.getBoundingClientRect();
  var rr = root.getBoundingClientRect();
  /* 与 .nav-ind 完全同参数：条固定 20px 并垂直居中于条目，
     条目本身更矮时以条目高度为准，免得在短条目上探出上下两端。 */
  var h = Math.min(20, Math.round(ir.height));
  var y = Math.round(ir.top - rr.top + (ir.height - h) / 2);
  if (!animate) {
    ind.style.transition = "none";
    /* 内联的 transition: none 只作用于 ind 自己，闸不到同级的 trail ⇒
       另给 root 挂一个类，由 CSS 闸掉 trail 的过渡（见 6-anim.css §17j ②）。 */
    root.classList.add("ind-noanim");
  }
  root.style.setProperty("--ind-y", y + "px");
  root.style.setProperty("--ind-h", h + "px");
  if (!animate) {
    /* 强制样式重算，让上面的 none 生效后再恢复，否则「落位」这一步本身
       会带上过渡（同 syncNavInd 的写法）。摘掉 ind-noanim 本身不会起过渡：
       那一刻 transform 的计算值没变，只是 transition-property 换了。 */
    void ind.offsetWidth;
    ind.style.transition = "";
    root.classList.remove("ind-noanim");
  }
  ind.classList.add("on");
  if (trail) trail.classList.add("on");
}

window.addEventListener("hashchange", function () {
  var prev = S.page;
  S.page = readHash();
  var a = PAGES.indexOf(prev),
    b = PAGES.indexOf(S.page);
  if (b !== a && b >= 0) S.pageDir = b > a ? 1 : -1;
  S.sidebarOpen = false;
  if (S.page === "console") loadTools();
  if (S.page === "settings") loadThresholds();
  window.scrollTo({ top: 0, behavior: "smooth" });
  /* 指示条必须等 Vue 把 .active 换到新条目上之后再量 */
  nextTick(function () {
    syncNavInd(true);
  });
});

export { PAGES, readHash, go, syncNavInd, syncTabInd, syncCfgInd };
