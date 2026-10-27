import { nextTick } from "../../vendor/vue.esm-browser.prod.js";
import { S, toast } from "../core/store.js";
import { go, pageAllowed } from "../core/router.js";
import { applyTheme } from "../core/theme.js";
import { loadHealth, loadOverview, loadRecentActivity, loadTools } from "../core/data.js";
import { selectTool } from "../features/console.js";
import { toolZhName } from "../core/util.js";

/* ======================================================================
 * 命令面板（2026-10-20）
 *
 * 这是玻璃 Dock 第一个按钮落地的「新功能」本体：Ctrl / Cmd + K 唤出，
 * 在一个输入框里同时检索**页面 / 动作 / MCP 工具**三类目标，↑↓ 选、Enter 执行。
 *
 * 为什么值得单独做：这个控制台的导航只有 4 个页面，但工具是 24 个 ——
 * 「去调试台 → 在左栏翻到 memory_archive_old → 点开」是四步操作，
 * 而在这里敲三个字母就到位。面板不重复实现业务，一切执行都转交给
 * 既有的 go() / selectTool() / applyTheme()，它只负责「找」。
 *
 * ⚠️ 候选项**每次渲染现算**，不缓存：页面、工具清单、主题偏好都会变，
 *    缓存一份快照迟早与真实状态脱节（典型症状：面板里跳到一个已经不存在的工具）。
 * ==================================================================== */

var PAGES = [
  { id: "dashboard", label: "概览", icon: "grid", sub: "健康度与最近动态" },
  { id: "console", label: "调试台", icon: "terminal", sub: "直接调用 MCP 工具" },
  { id: "library", label: "记忆库", icon: "book", sub: "浏览与检索条目" },
  { id: "access", label: "访问控制", icon: "shield", sub: "账号 · 令牌 · 权限" },
  { id: "settings", label: "配置", icon: "sliders", sub: "连接 · 阈值 · 同步" },
];

var CommandPalette = {
  data: function () {
    return { S: S };
  },
  computed: {
    q: {
      get: function () {
        return S.palette.q;
      },
      set: function (v) {
        S.palette.q = v;
        S.palette.idx = 0;
      },
    },
    all: function () {
      var out = [];
      /* 页面候选按角色裁剪（2026-10-26）：面板是第二个入口，藏着侧栏却留着
         面板里的「调试台 / 访问控制」，等于换了个地方把门打开。
         判据与侧栏同源 —— core/router.js#PAGE_ROLES。 */
      PAGES.forEach(function (p) {
        if (!pageAllowed(S.role, p.id)) return;
        out.push({
          key: "page:" + p.id,
          group: "页面",
          label: p.label,
          sub: p.sub,
          icon: p.icon,
          hit: p.label + " " + p.sub,
          run: function () {
            go(p.id);
          },
        });
      });
      out.push({
        key: "act:refresh",
        group: "动作",
        label: "刷新全部数据",
        sub: "健康 · 概览 · 更新日历 · 工具清单",
        icon: "refresh",
        hit: "刷新 重新加载 refresh",
        run: function () {
          toast("info", "正在刷新…", "");
          Promise.all([
            loadHealth(),
            loadOverview(),
            loadRecentActivity(),
            loadTools(true),
          ]).then(function () {
            toast("ok", "已刷新", "四项数据均已重新拉取");
          });
        },
      });
      out.push({
        key: "act:theme",
        group: "动作",
        label: S.theme === "dark" ? "切换到浅色" : "切换到深色",
        sub: "主题",
        icon: S.theme === "dark" ? "sun" : "moon",
        hit: "主题 深色 浅色 theme",
        run: function () {
          var p = S.theme === "dark" ? "light" : "dark";
          S.themePref = p;
          S.theme = applyTheme(p);
        },
      });
      out.push({
        key: "act:auto",
        group: "动作",
        label: "跟随系统主题",
        sub: "自动随系统深浅色切换",
        icon: "auto",
        hit: "跟随系统 auto theme",
        run: function () {
          S.themePref = "auto";
          S.theme = applyTheme("auto");
          toast("info", "已跟随系统主题", "");
        },
      });
      /* 2026-10-20：玻璃 Dock 撤除后，它原本第三个按钮「复制端点」不能跟着丢，
         这里补成面板动作（前两个「命令面板 / 刷新全部」面板本来就有）。 */
      out.push({
        key: "act:copy-endpoint",
        group: "动作",
        label: "复制 MCP 端点",
        sub: S.health.endpoint || "当前连接地址",
        icon: "copy",
        hit: "复制 端点 endpoint copy mcp",
        run: function () {
          var v = S.health.endpoint || "";
          if (!v) {
            toast("err", "还没有端点", "先等连接检查完成");
            return;
          }
          var done = function () {
            toast("ok", "端点已复制", v);
          };
          if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(v).then(done, function () {
              toast("err", "复制失败", "浏览器拒绝了剪贴板写入");
            });
          } else {
            /* 非安全上下文（http 访问局域网）没有 clipboard API */
            var ta = document.createElement("textarea");
            ta.value = v;
            ta.style.cssText = "position:fixed;opacity:0;top:0;left:0";
            document.body.appendChild(ta);
            ta.select();
            var ok = false;
            try {
              ok = document.execCommand("copy");
            } catch (e) {}
            document.body.removeChild(ta);
            if (ok) done();
            else toast("err", "复制失败", "请手动选中复制");
          }
        },
      });
      /* 工具候选的目标是调试台 —— 那一页不可见时整段不产候选，
         否则「搜了个工具名、回车却掉进空页面」。 */
      if (pageAllowed(S.role, "console"))
        (S.tools || []).forEach(function (t) {
          out.push({
            key: "tool:" + t.name,
            group: "工具",
            label: toolZhName(t.name) || t.name,
            sub: t.name,
            icon: "terminal",
            hit: t.name + " " + (toolZhName(t.name) || "") + " " + (t.description || ""),
            run: function () {
              go("console");
              nextTick(function () {
                selectTool(t);
              });
            },
          });
        });
      return out;
    },
    items: function () {
      var q = String(S.palette.q || "").trim().toLowerCase();
      var all = this.all;
      if (!q) return all;
      return all.filter(function (it) {
        return (it.hit || "").toLowerCase().indexOf(q) >= 0;
      });
    },
  },
  watch: {
    "S.palette.open": function (v) {
      if (v) {
        /* 每次打开都重新拉一次工具清单：工具是面板里最有用的一类目标，
           而 S.tools 在「没进过调试台」时是空的。loadTools 自带缓存，
           已加载过时是零请求。 */
        loadTools();
        nextTick(
          function () {
            if (this.$refs.input) this.$refs.input.focus();
          }.bind(this),
        );
      }
    },
    "S.palette.q": function () {
      /* 输入变化后高亮项必须回到第一条，否则会停在越界下标上
         （列表短了以后 idx 指向不存在的项，Enter 就等于凭空执行上一次的目标）。 */
      S.palette.idx = 0;
    },
  },
  methods: {
    close: function () {
      S.palette.open = false;
    },
    move: function (d) {
      var n = this.items.length;
      if (!n) return;
      S.palette.idx = (S.palette.idx + d + n) % n;
      var el = this.$el.querySelector(".pal-item.on");
      if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
    },
    run: function (it) {
      if (!it) return;
      this.close();
      it.run();
    },
    key: function (e) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        this.move(1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        this.move(-1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        this.run(this.items[S.palette.idx]);
      } else if (e.key === "Escape") {
        e.preventDefault();
        this.close();
      }
    },
    /* 全局快捷键：Ctrl/Cmd + K 开、Esc 关。
       ⚠️ 不用 Root.onKey 那条通道 —— 它在输入框里会提前 return，
          而「正在输入时也想按 Ctrl+K 换目标」恰恰是面板的常用路径。 */
    onKey: function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        S.palette.open = !S.palette.open;
        if (S.palette.open) {
          S.palette.q = "";
          S.palette.idx = 0;
        }
      }
    },
  },
  mounted: function () {
    window.addEventListener("keydown", this.onKey);
  },
  beforeUnmount: function () {
    window.removeEventListener("keydown", this.onKey);
  },
  template:
    '<transition name="fade">' +
    '<div class="pal-mask" v-if="S.palette.open" @click.self="close">' +
    '  <div class="pal" role="dialog" aria-modal="true" aria-label="命令面板">' +
    '    <div class="pal-head">' +
    '      <span class="pal-lead" v-html="svg(\'search\')"></span>' +
    '      <input class="pal-input" ref="input" v-model="q" @keydown="key"' +
    '             placeholder="搜索页面、动作或工具…" aria-label="搜索" />' +
    '      <span class="pal-esc">Esc</span>' +
    "    </div>" +
    '    <div class="pal-list" v-if="items.length">' +
    '      <button class="pal-item" v-for="(it,i) in items" :key="it.key" :class="{on: i===S.palette.idx}"' +
    '              @click="run(it)" @mouseenter="S.palette.idx=i">' +
    '        <span class="pal-ico" v-html="svg(it.icon)"></span>' +
    '        <span class="pal-label">{{ it.label }}</span>' +
    '        <span class="pal-sub">{{ it.sub }}</span>' +
    '        <span class="pal-g">{{ it.group }}</span>' +
    "      </button>" +
    "    </div>" +
    '    <div class="pal-empty" v-else>没有匹配项</div>' +
    '    <div class="pal-foot"><span>↑↓ 选择</span><span>Enter 执行</span><span>Esc 关闭</span></div>' +
    "  </div>" +
    "</div>" +
    "</transition>",
};

export { CommandPalette };
