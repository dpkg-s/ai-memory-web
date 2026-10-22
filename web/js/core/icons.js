/* ======================================================================
 * 2. 图标（内联 SVG，零依赖）
 * ==================================================================== */
var P =
  'stroke="currentColor" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';
var ICONS = {
  grid:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></svg>',
  terminal:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 9l3 3-3 3M13 15h4"/></svg>',
  book:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 5.5V20.5"/></svg>',
  sliders:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></svg>',
  clock:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  check:
    '<svg viewBox="0 0 24 24" ' + P + '><path d="M4 12.5l5 5L20 6.5"/></svg>',
  alert:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M12 3l9 16H3z"/><path d="M12 9v4M12 16.5v.5"/></svg>',
  layers:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/></svg>',
  hash:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M9 3L7 21M17 3l-2 18M3.5 9h17M3 15h17"/></svg>',
  search:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><circle cx="11" cy="11" r="7"/><path d="M16.5 16.5L21 21"/></svg>',
  play:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M7 4.5l12 7.5-12 7.5z"/></svg>',
  chevron:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M9 5l7 7-7 7"/></svg>',
  refresh:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/></svg>',
  sun:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19"/></svg>',
  moon:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/></svg>',
  auto:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><circle cx="12" cy="12" r="9"/><path d="M12 3v18" /><path d="M12 12a9 9 0 0 0 6.4 8.5"/></svg>',
  menu:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
  copy:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 5.5A2.5 2.5 0 0 0 12.5 3H6.5A3.5 3.5 0 0 0 3 6.5v6A2.5 2.5 0 0 0 5.5 15"/></svg>',
  link:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/></svg>',
  save:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M5 3h11l3 3v15H5z"/><path d="M8 3v6h7V3M8 21v-6h8v6"/></svg>',
  shield:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M12 3l7 3v6c0 4.5-3 8-7 9-4-1-7-4.5-7-9V6z"/></svg>',
  inbox:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M3 13l3-8h12l3 8v6H3z"/><path d="M3 13h5l1 2h6l1-2h5"/></svg>',
  bolt:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M13 2L5 14h6l-1 8 8-12h-6z"/></svg>',
  file:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/></svg>',
  key:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><circle cx="8" cy="15" r="4"/><path d="M11 12l8-8M17 6l2 2M14 9l2 2"/></svg>',
  close:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M6 6l12 12M18 6L6 18"/></svg>',
  trash:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/></svg>',
  info:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/></svg>',
  download:
    '<svg viewBox="0 0 24 24" ' +
    P +
    '><path d="M12 3v11"/><path d="M8 10l4 4 4-4"/><path d="M4 19h16"/></svg>',
};
/* ======================================================================
 * 视觉重心校正（2026-10-20，主人令「把图标的视觉中心对称给做了」）
 *
 * 问题：图标都画在同一个 24×24 viewBox 里，但**图形本身的包围盒各不相同**
 * （grid 是整齐的 3..21，book 只有 4..19，play 的三角形 7..19，
 * layers 纵向只到 18）⇒ 把 29 个图标排成一列时，各自的「视觉重心」并不在
 * 同一条线上，窄图标会显得偏向一侧、扁图标会显得偏高。CSS 能居中的只有
 * 那个 24×24 的**盒子**，管不到盒子里图形的偏置。
 *
 * 做法：逐个量出 Ink 包围盒（含 stroke）的中心，算出它到 (12,12) 的偏移，再给图形
 * 整体套一层 `translate`。这样每个图标的**墨迹包围盒中心**都精确落在 viewBox 中心。
 * （2026-10-20 复测：29/29 全部落在 12.00,12.00，说明这张表本身是自洽的；
 *   主人看到的「歪」实际来自 CSS 的行盒问题，见本节末尾第 1 条。）
 *
 * 数值来源：headless Chromium 实测 `svg.getBBox()`（不是目测估的），
 * 只对偏移 ≥0.25 单位的图标下位移，恰好居中的一律不写 —— 没有偏移就不能有
 * transform，否则只是给渲染多套一层无意义的组合。将来新增图标若看起来「歪」，
 * 用同一口径量一遍再往表里加一行即可，不要手调。
 *
 *   book +0.5,+0.25   alert  0,+1      layers 0,+1.5    hash +0.25,0
 *   search -0.5,-0.5  play  +0.6,0     chevron -0.5,0   refresh 0,+0.91
 *   moon +0.34,-0.34  copy  +0.5,+0.5  bolt  +0.5,0     key +0.5,+0.5
 *   trash 0,-0.5      download 0,+1
 *
 * ---------------------------------------------------------------------------
 * ⚠️ 2026-10-20 修正（主人二次反馈「还有把所有的图标纠正一下，怎么都有点歪歪的」）：
 *
 *   1. **主因不在本文件，在 CSS**。基础规则 `svg{display:inline-block;vertical-align:
 *      middle}` 让每个图标去参与父级的**行盒**，被 `line-height:23.2px` 往下顶了
 *      4px（.nav-icon）/ 3.5px（.cfg-icon）/ 2px（.tab）。已改成 display:block，
 *      实测全站 svg 盒中心 − 父盒中心 = 0.00。**先看 1-tokens.css 那条注释**。
 *   2. **光学重心 ≠ 包围盒中心**，但两者对绝大多数图标是同一件事。用 canvas
 *      按 alpha 加权算了 29 个图标的「墨迹重心」，与包围盒中心的偏差分两类：
 *        · 锥形字形（alert 三角底宽、download 箭头头大、layers 双层、inbox 托盘、
 *          key 圆头+细杆、trash 上宽下窄、check 折线）偏差 0.7~3.8 单位（纵向居多）
 *          —— 这**不是**画歪，是形状本身的重心。真实图标库（Feather / Material）
 *          对它们一律按包围盒居中，按重心居中的话 download 会被抬上去 3 个单位，
 *          反而更歪。故保持包围盒口径，不动。
 *        · 指向性字形里只有 play 需要让重心说话：三角形顶点朝右、质量全在左边，
 *          包围盒居中后肉眼仍觉得它偏左。Material 的 `play_arrow` 是把三角形
 *          **右移**（bbox 中心 13.5 而非 12，重心 11.67≈居中）。这里同口径：
 *          translate 由 -1 改成 +0.6，重心落在 11.5。
 *          chevron 实测重心 11.73（已接近 12），维持 -0.5 不动。
 *
 * 量测脚本（一次性，不入库）口径：包围盒 = 子元素 getBoundingClientRect() 并集
 * （**含 stroke**，1.8 宽向外扩 0.9）；重心 = 480×480 渲染后 alpha 加权一阶矩。
 *
 * ⚠️ 只动**图形**不动 viewBox：位移后的极值仍在 2..22 内，描边不会被裁。
 * ==================================================================== */
var OPTICAL = {
  book: [0.5, 0.25],
  alert: [0, 1],
  layers: [0, 1.5],
  hash: [0.25, 0],
  search: [-0.5, -0.5],
  play: [0.6, 0],
  chevron: [-0.5, 0],
  refresh: [0, 0.91],
  moon: [0.34, -0.34],
  copy: [0.5, 0.5],
  bolt: [0.5, 0],
  key: [0.5, 0.5],
  trash: [0, -0.5],
  download: [0, 1],
};
Object.keys(OPTICAL).forEach(function (k) {
  var s = OPTICAL[k];
  ICONS[k] = ICONS[k].replace(
    /^(<svg[^>]*>)([\s\S]*)(<\/svg>)$/,
    function (_, head, inner, tail) {
      return head + '<g transform="translate(' + s[0] + ' ' + s[1] + ')">' + inner + "</g>" + tail;
    },
  );
});

function svg(name) {
  return ICONS[name] || ICONS.info;
}

export { P, ICONS, OPTICAL, svg };
