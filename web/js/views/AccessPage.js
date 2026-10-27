import { S, toast } from "../core/store.js";
import { api } from "../core/api.js";

/* ======================================================================
 * 15. 访问控制页（2026-10-22，控制台 v1.7.0）
 *
 * 一个页面两个 Tab：**账号**与**令牌**。
 *
 * 为什么合并而不分成两个导航项（主人 2026-10-22 选型 B）：
 *   两者回答的是同一个问题 ——「谁有权限、以什么身份、到什么时候为止」。
 *   账号是「人的身份」，令牌是「程序的身份」，本质是一张表的两半。
 *   分成两页会让侧栏变成 6 项（手机端要折叠），而它们从不同时使用。
 *
 * 2026-10-22 第二次改版（主人选型 A · 行内展开）：
 *   旧版把「新建账号 / 签发令牌」两张表单**常驻**在右栏，于是清单行上的
 *   「重置口令」只能在卡片尾部展开一段输入框 —— 点击点在第 1 行，输入框
 *   出现在第 8 行下面，这是本页最刺眼的错位。改版后：
 *     · 清单底部一条虚线「+ 新建账号 / + 签发令牌」，点击就地展开表单；
 *     · 行按钮「改密码」在该行**正下方**展开一行输入；
 *     · 右栏只剩「我的账号」（身份管理，仍贴着页头身份标签）。
 *   为什么不用抽屉/弹窗：本页的操作都只需 1–3 个字段，浮层要额外管理
 *   焦点陷阱、Esc、遮罩点击与移动端整屏化，收益抵不上成本。
 *
 * 权限口径：本页只做**界面裁剪**。真正的拦截全在服务端 ——
 *   viewer 打开本页只会看到「设置」之外什么都没，调接口必然 403。
 *   藏 UI 不是安全措施，只是别让人点进一个注定失败的页面。
 * ==================================================================== */

var ROLE_ZH = { admin: "管理员", operator: "操作员", viewer: "只读" };
var ROLE_DESC = {
  admin: "全部工具 + 管人管令牌",
  operator: "全部工具，不能管人",
  viewer: "只能调只读工具",
};

/* 数据视野（2026-10-26）—— 与「工具组」正交的第二维度。
 *
 * 工具组管**能调什么**，视野管**能看见哪些密级的记忆**。缺了它，
 * viewer 令牌虽然只能调 memory_search，返回的却是全库含 sensitive/secret：
 * 工具粒度收紧了、数据粒度没收紧，等于只锁了门没锁抽屉。
 *
 * 服务端 ROLE_CLEARANCE 是唯一事实源（web_store.py），这里只是镜像用于
 * 收窄下拉选项；真正的越界拦截在服务端，前端收窄只是为了别让人填完才吃 403。
 */
var CLEARANCE_ZH = {
  owner: "全权",
  member: "标准",
  reader: "只读共享",
  guest: "仅公开",
};
var CLEARANCE_DESC = {
  owner: "全部条目，含绝密",
  member: "含敏感条目",
  reader: "日常条目，不含敏感 / 绝密",
  guest: "仅标记为公开的条目",
};
var CLEARANCE_RANK = { guest: 0, reader: 1, member: 2, owner: 3 };
var ROLE_CLEARANCE = { admin: "owner", operator: "member", viewer: "reader" };
/* 顺序即下拉呈现顺序（2026-10-26 主人指令：权级从高到低排）。
   高 → 低，与 CLEARANCE_RANK 相反 —— 下拉要的是「从最宽到最窄」的直觉，
   而不是数值升序；排序口径只在这一处，别在别处再排一遍。 */
var CLEARANCE_ALL = ["owner", "member", "reader", "guest"];

/* 读写模式（2026-10-26）—— 与视野正交的第三维度。
 *
 * 视野管「看得见多少」，读写模式管「能不能改」。二者正交，所以「全权 + 只读」
 * 是一个合法且最常用的组合：别的设备能读整个库，但一个字都改不动。
 *
 * 服务端 ROLE_ACCESS 是唯一事实源（web_store.py）；这里镜像默认值，只为把
 * 下拉初值设成「角色的默认」。真正的拦截在服务端（/api/call 与 MCP 的
 * /mcp/<档位>-ro 端点），前端不做安全判断。
 */
var ACCESS_ZH = { rw: "可读写", ro: "只读" };
var ACCESS_DESC = {
  rw: "能写条目，仍受视野与角色限制",
  ro: "只能读，任何写入都会被拒",
};
var ACCESS_ALL = ["rw", "ro"];
var ROLE_ACCESS = { admin: "rw", operator: "rw", viewer: "ro" };

function fmtTs(v) {
  if (v === null || v === undefined || v === "") return "";
  var d = new Date(Number(v) * 1000);
  if (isNaN(d.getTime())) return "";
  function p(n) {
    return (n < 10 ? "0" : "") + n;
  }
  return (
    d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
    " " + p(d.getHours()) + ":" + p(d.getMinutes())
  );
}

/* 到期/次数的人话描述。分开算是因为两者都可能缺 —— 缺 = 不限。 */
function expiresZh(t) {
  if (!t.expires_at) return "永久";
  var left = Number(t.expires_at) - Date.now() / 1000;
  if (left <= 0) return "已过期";
  if (left < 3600) return Math.round(left / 60) + " 分钟后";
  if (left < 86400) return Math.round(left / 3600) + " 小时后";
  return Math.round(left / 86400) + " 天后（" + fmtTs(t.expires_at) + "）";
}

function usesZh(t) {
  if (!t.max_uses) return "不限（已用 " + (t.uses || 0) + "）";
  return (t.uses || 0) + " / " + t.max_uses;
}

/* ---------------------------------------------------------------------------
 * 访问日志的呈现（2026-10-27）
 *
 * 服务端只回结构化字段（kind / action / actor / target / t），中文一律在**前端**
 * 映射：文案改动不该要求重启后端（Python 改动要重启，JS 保存即生效）。
 * 映射表留兜底 —— 将来服务端多一个动作，界面上显示原始 action 而不是空白，
 * 这比「静默丢一行」有用得多。
 * ------------------------------------------------------------------------- */
var AUDIT_ACTION_ZH = {
  "login.ok": "登录",
  "login.fail": "登录失败",
  "logout": "登出",
  "password.change": "修改口令",
  "account.create": "创建账号",
  "account.update": "修改账号",
  "account.delete": "删除账号",
  "token.issue": "签发令牌",
  "token.revoke": "吊销令牌",
  "config.write": "修改配置",
  "config.thresholds": "修改阈值",
  "tool.call": "调用工具",
  "tool.denied": "调用被拒",
  "mcp.connect": "MCP 接入",
  "auth.denied": "鉴权拦截",
  "audit.export": "导出日志",
};

/* 一条事件压成「谁 · 什么时候 · 干了什么」三段：
   fact 段给人一眼认出动作，detail 段补充「哪个工具 / 什么角色 / 多久」。
   2026-10-27 追加 ip：这是判断「同一个人 vs 同一枚令牌被两个人用」的关键旁证，
   只放在 detail 里（服务端本来就有）等于白存 —— 界面上得看得见才算记录。 */
function auditRow(e) {
  var actor = String(e.actor || "").trim();
  if (!actor || actor === "anonymous") actor = "匿名";
  /* 令牌通道的主体是「哪枚令牌的 owner」+ 标记，否则同名的人与脚本会混成一列。 */
  if (e.via === "token") actor += "（令牌）";
  return {
    id: (e.t || 0) + "-" + (e.action || "") + "-" + (e.target || ""),
    kind: e.kind || "other",
    actor: actor,
    action: AUDIT_ACTION_ZH[e.action] || e.action || "—",
    target: e.target || "",
    detail: e.detail || "",
    /* 回环地址单独标一下：它既可能是「本机直连」，也可能是 cloudflared
       隧道没带 CF-Connecting-IP（服务端只信这个头）。混在公网 IP 里看是噪音。 */
    ip: e.ip || "",
    ipLocal: e.ip === "127.0.0.1" || e.ip === "::1" || e.ip === "::ffff:127.0.0.1",
    time: fmtTs(e.t),
    ok: e.ok !== false,
    /* 类名在 JS 里拼好，模板里就只剩一个属性绑定 —— 在单引号字符串里再嵌
       单引号（:'k-' + ...）既难读又极易被转义吃掉（2026-10-27 踩过）。 */
    dot: "k-" + (e.kind || "other"),
    bad: e.ok === false,
  };
}

var AccessPage = {
  data: function () {
    return {
      S: S,
      /* 空串 = 尚未手动切过，由 activeTab 按角色给默认值（2026-10-25）：
         管理员默认「账号」，「操作员 / 只读」默认「令牌」—— 他们压根没有
         账号页，若仍默认到那一页，会看到一条空白列表。 */
      tab: "",
      loading: false,
      users: [],
      tokens: [],
      /* 新建账号（行内展开，默认收起） */
      nuOpen: false,
      nu: { name: "", password: "", role: "viewer" },
      nuBusy: false,
      /* 签发令牌（行内展开，默认收起） */
      ntOpen: false,
      nt: { name: "", role: "operator", clearance: "", access: "", expires: "604800", max_uses: 0 },
      ntBusy: false,
      /* 一次性明文：**只在创建那一瞬间存在**，关掉就取不回 */
      issued: "",
      issuedName: "",
      /* 连接串主机：默认当前访问地址，可改成局域网 IP 或域名 */
      baseUrl: "",
      /* 改密码（行内展开在该行下方，不用 prompt —— prompt 无法遮蔽明文） */
      resetOf: "",
      resetPw: "",
      /* 删除二次确认（行内两步，避免引入第三个确认弹窗形态） */
      pendingDel: "",
      /* 重发二次确认，**必须与删除分开**：两者都以 t.id 为键，
         共用一个字段会让「点重发 → 删除按钮也进入确认态」。 */
      pendingRe: "",
      /* 我的账号卡默认收起：口令输入框是低频操作，展开一次即可 */
      pwOpen: false,
      pw: { old: "", n1: "", n2: "" },
      pwBusy: false,
      /* 访问日志（2026-10-27）：admin 专属，服务端 /api/audit 同步卡 admin。 */
      auditEvents: [],
      auditKinds: [],
      auditKind: "",
      auditTotal: 0,
      auditBusy: false,
      /* 首屏还没成功读过一次 ⇒ 显示骨架而不是「暂无记录」。两者长得像、
         含义完全不同：一个是「在等」、一个是「真没有」。 */
      auditLoaded: false,
      /* 导出独立的忙标志：与「刷新」共用会让刷新按钮在导出时也转圈。 */
      auditExporting: false,
    };
  },
  computed: {
    me: function () {
      return S.sessionUser || "";
    },
    myRole: function () {
      return S.role || "";
    },
    myRoleZh: function () {
      return ROLE_ZH[this.myRole] || "未知";
    },
    isAdmin: function () {
      return !!S.canManage;
    },
    /* 实际生效的分段（2026-10-25 主人指令：权限不足的界面直接隐藏）。
       设计原则：**不给「你没有权限」这种提示**，而是让那一页根本不存在 ——
       非管理员的分段条里只有「令牌」，也就不存在点进去看提示的路径。
       身份是异步到位的，所以默认值必须放在 computed 而不是 data 里求值。 */
    activeTab: function () {
      if (this.tab) return this.tab;
      return this.isAdmin ? "users" : "tokens";
    },
    /* operator 不能签发 admin 令牌（服务端也会拒）；这里先把选项收窄，
       让人别先填完才吃一个 403。 */
    roleOptions: function () {
      if (this.isAdmin) return ["admin", "operator", "viewer"];
      return ["operator", "viewer"];
    },
    canCreateToken: function () {
      return this.isAdmin || this.myRole === "operator";
    },
    selfOnly: function () {
      return !this.isAdmin;
    },
    /* 连接串：主机留空时退化为同源相对地址，至少不会拼出 "undefined/mcp"。 */
    connBase: function () {
      return String(this.baseUrl || "").trim().replace(/\/+$/, "");
    },
    connUrl: function () {
      return this.connBase + "/mcp?token=" + this.issued;
    },
    connHeader: function () {
      return "Authorization: Bearer " + this.issued;
    },
    roleZh: function () {
      return function (r) {
        return ROLE_ZH[r] || r;
      };
    },
    roleDesc: function () {
      return function (r) {
        return ROLE_DESC[r] || "";
      };
    },
    /* 当前选中角色的权级上限。下拉只列 ≤ 上限的档 —— 服务端还会再拦一次，
       这里收窄纯粹是别让人填完才吃 403。 */
    clearanceCeil: function () {
      return ROLE_CLEARANCE[this.nt.role] || "reader";
    },
    clearanceOptions: function () {
      /* ⚠️ clearanceCeil 是 computed，取值即结果，**不能加括号调用**。
         2026-10-26 实拍复现过代价：写成 this.clearanceCeil() 会抛
         TypeError，Vue 渲染这棵子树直接失败 —— 表现是点「+ 签发令牌」
         后整张令牌卡（连同表单）凭空消失，只剩顶栏。 */
      var ceilRank = CLEARANCE_RANK[this.clearanceCeil];
      var out = [];
      for (var i = 0; i < CLEARANCE_ALL.length; i++) {
        var c = CLEARANCE_ALL[i];
        if (CLEARANCE_RANK[c] <= ceilRank) out.push(c);
      }
      return out;
    },
    clearanceZh: function () {
      return function (c) {
        return CLEARANCE_ZH[c] || c || "";
      };
    },
    clearanceDesc: function () {
      return function (c) {
        return CLEARANCE_DESC[c] || "";
      };
    },
    /* 令牌实际生效的视野：没显式选就按角色推导，与服务端 clearance_of 同口径 */
    tokenClearance: function () {
      return function (t) {
        return t.clearance || ROLE_CLEARANCE[t.role] || "reader";
      };
    },
    /* 令牌实际生效的读写模式：同口径推导（服务端 access_of） */
    tokenAccess: function () {
      return function (t) {
        return t.access || ROLE_ACCESS[t.role] || "rw";
      };
    },
    accessZh: function () {
      return function (a) {
        return ACCESS_ZH[a] || a || "";
      };
    },
    accessDesc: function () {
      return function (a) {
        return ACCESS_DESC[a] || "";
      };
    },
    /* viewer 只列「只读」：它的角色默认就是 ro，服务端也会拒绝 rw 声明。
       与其让人选完吃 400，不如不给这个选项。 */
    accessOptions: function () {
      return (ROLE_ACCESS[this.nt.role] === "ro") ? ["ro"] : ACCESS_ALL;
    },
    /* 角色默认的读写模式。模板里**不能**直接写 ROLE_ACCESS[nt.role] ——
       模块级变量不在组件渲染上下文里，那样写会得到 undefined（并把整段
       hint 渲染成空白），所以必须经一个 computed 转一手。 */
    accessDefault: function () {
      return ROLE_ACCESS[this.nt.role] || "rw";
    },
    tsZh: function () {
      return function (v) {
        return fmtTs(v);
      };
    },
    /* 日志卡的副标题：条数 + 是否在筛。不用「共 N 条」这种话 —— 卡片里已有
       筛选 chip，副标题只该回答「现在这一屏是多少」。 */
    auditSub: function () {
      if (this.auditBusy) return "读取中…";
      if (!this.auditEvents.length) return this.auditKind ? "无匹配" : "暂无记录";
      return this.auditEvents.length + " 条" +
        (this.auditKind ? "（已筛）" : " / 库内 " + this.auditTotal);
    },
    /* 首屏骨架：只在「第一次读、还没结果」时出现。已有数据时再刷新不该把
       列表换成骨架 —— 那会把正在看的那一行整页抽走，比转圈更烦人。 */
    auditSkel: function () {
      return this.auditBusy && !this.auditLoaded && !this.auditEvents.length;
    },
    auditRows: function () {
      return (this.auditEvents || []).map(auditRow);
    },
    expZh: function () {
      return function (t) {
        return expiresZh(t);
      };
    },
    usesText: function () {
      return function (t) {
        return usesZh(t);
      };
    },
  },
  /* 身份是**异步到位**的：main.js 直接 mount，Root 挂载后才去问 /api/session，
     于是本页首帧拿到的 S.canManage 还是 false —— 那时 refresh() 走的是
     「非管理员」分支，users 恒为空数组。之后权限到了，页面却不会自己重取，
     表现为「账号 0 个、只有一个 + 新建账号」，刷新整页才恢复。
     修法就是盯住权限翻转补一次拉取（2026-10-22 探针实测抓到）。 */
  watch: {
    isAdmin: function (v) {
      if (v) this.refresh();
      /* 权限一旦落定为否，把停留过的「账号」分段收回「令牌」—— 否则用户
         会停在一条已经没有按钮指向它的分段上（该页内容也不再渲染）。 */
      if (!v && this.tab === "users") this.tab = "tokens";
    },
    /* 改角色后权级必须跟着收窄（2026-10-26）：下拉已改为直接列权级、不再有
       「随角色」兜底项，所以「先选全权、再把角色降成只读」会留下一个超出
       上限的值 —— 签发时才被服务端 403 就太晚了，这里直接钳到新上限。 */
    "nt.role": function () {
      var ceil = ROLE_CLEARANCE[this.nt.role] || "reader";
      var cur = this.nt.clearance;
      if (CLEARANCE_RANK[cur] === undefined || CLEARANCE_RANK[cur] > CLEARANCE_RANK[ceil]) {
        this.nt.clearance = ceil;
      }
      /* 读写模式跟着角色收窄（2026-10-26）：viewer 只能只读，所以切到 viewer
         必须把它按到 ro。反方向**不动** —— 用户手动选的只读要保留，那是意图，
         不能因为换了个角色就被悄悄放宽成可写。 */
      var defAccess = ROLE_ACCESS[this.nt.role] || "rw";
      if (defAccess === "ro") {
        this.nt.access = "ro";
      } else if (ACCESS_ALL.indexOf(this.nt.access) < 0) {
        this.nt.access = defAccess;
      }
    },
  },
  methods: {
    /* 读访问日志。筛选切换也走这里 —— 服务端已支持 kind 过滤，
       前端不再自己 filter 一遍（两处过滤迟早会不一致）。

       `opts.silent`（2026-10-27）：静默轮询用。三条自我约束缺一条，这块就会
       变成「每 8 秒闪一下」的东西：
        1. **不置 auditBusy** ⇒ 不触发骨架、不给列表降透明度；
        2. **用户已往下翻就整次跳过**（scrollTop > 4）—— 新事件插在顶部会把
           正在读的那条顶走；
        3. **失败不弹 toast**，否则后台每 8 秒一条错误能把屏幕糊满。 */
    loadAudit: function (opts) {
      var self = this;
      var silent = !!(opts && opts.silent);
      if (!self.isAdmin) {
        self.auditEvents = [];
        return;
      }
      if (silent) {
        var box = self.$el && self.$el.querySelector
          ? self.$el.querySelector(".audit-list")
          : null;
        if (box && box.scrollTop > 4) return;
      } else {
        self.auditBusy = true;
      }
      var q = { limit: 40 };
      if (self.auditKind) q.kind = self.auditKind;
      api
        .audit(q)
        .then(function (d) {
          self.auditEvents = (d && d.events) || [];
          self.auditKinds = (d && d.kinds) || [];
          self.auditTotal = ((d && d.stats) || {}).total || 0;
          self.auditLoaded = true;
        })
        .catch(function (e) {
          if (!silent) toast("err", "读取访问日志失败", e.message || String(e));
        })
        .then(function () {
          if (!silent) self.auditBusy = false;
        });
    },
    /* ------------------------------------------------------------------
     * 即时同步（2026-10-27 主人选型 C「先 A 再 B」的 A 档：轮询）
     *
     * 为什么先上轮询：这是纯前端改动，**保存即生效**；B 档（SSE）要后端新
     * 端点 + 心跳 + 断线重连，非重启不可。先把「不用手点刷新」拿到手，
     * B 档再来把延迟从 8 秒压到 1 秒内、并把这里降级为断线兜底。
     *
     * 8 秒的口径：审计日增几十条，8 秒足够「另开一个窗口改东西、回来就看见」；
     * 再密就是拿请求换一个没人感知的差别。
     * 切到别的标签页/最小化时**不发请求**（document.hidden）—— 后台轮询纯属
     * 白烧电，回来时 visibilitychange 会立刻补一次。
     * ------------------------------------------------------------------ */
    startAuditWatch: function () {
      var self = this;
      self.stopAuditWatch();
      self._auditTimer = setInterval(function () {
        if (document.hidden) return;
        if (!self.isAdmin) return;
        self.loadAudit({ silent: true });
      }, 8000);
      /* 记在实例上而非 data：定时器 id 参与响应式毫无意义，只会让 Vue 追它。 */
      self._auditVis = function () {
        if (document.hidden || !self.isAdmin) return;
        self.loadAudit({ silent: true });
      };
      document.addEventListener("visibilitychange", self._auditVis);
    },
    stopAuditWatch: function () {
      if (this._auditTimer) {
        clearInterval(this._auditTimer);
        this._auditTimer = null;
      }
      if (this._auditVis) {
        document.removeEventListener("visibilitychange", this._auditVis);
        this._auditVis = null;
      }
    },
    /* 导出（2026-10-27）：带当前筛选条件导**全量**，不是导出这一屏。
       文件名带本地时间戳 —— 同一分钟导两次不该互相覆盖（浏览器默认会加
       「(1)」，但那串括号在给别人发文件时很难看）。 */
    exportAudit: function (fmt) {
      var self = this;
      if (self.auditExporting) return;
      self.auditExporting = true;
      var q = { format: fmt || "csv" };
      if (self.auditKind) q.kind = self.auditKind;
      api
        .auditExport(q)
        .then(function (blob) {
          var d = new Date();
          var p = function (n) {
            return (n < 10 ? "0" : "") + n;
          };
          var stamp =
            d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "-" +
            p(d.getHours()) + p(d.getMinutes());
          var url = URL.createObjectURL(blob);
          var a = document.createElement("a");
          a.href = url;
          a.download = "ai-memory-audit-" + stamp + "." + q.format;
          document.body.appendChild(a);
          a.click();
          a.remove();
          /* 立刻 revoke 会让某些浏览器的下载拿到空文件；给 4 秒宽限。 */
          setTimeout(function () {
            URL.revokeObjectURL(url);
          }, 4000);
          toast("ok", "已导出", "整份日志（" + q.format.toUpperCase() + "）已开始下载");
        })
        .catch(function (e) {
          toast("err", "导出失败", e.message || String(e));
        })
        .then(function () {
          self.auditExporting = false;
          /* 导出本身也进了审计流（服务端记 audit.export），顺手刷一次
             让「我刚做的这件事」立刻出现在列表里 —— 否则用户会怀疑没记上。
             走静默：这里只是补一条回读，不该让整列闪一下。 */
          self.loadAudit({ silent: true });
        });
    },
    setAuditKind: function (k) {
      if (this.auditKind === k) return;
      this.auditKind = k;
      this.loadAudit();
    },
    refresh: function () {
      var self = this;
      self.loading = true;
      var jobs = [];
      jobs.push(
        api.tokens().then(function (d) {
          self.tokens = (d && d.tokens) || [];
        }),
      );
      if (self.isAdmin) {
        jobs.push(
          api.users().then(function (d) {
            self.users = (d && d.users) || [];
          }),
        );
      } else {
        self.users = [];
      }
      Promise.all(jobs)
        .catch(function (e) {
          toast("err", "加载失败", e.message || String(e));
        })
        .then(function () {
          self.loading = false;
        });
    },

    /* 剪贴板：writeText 是异步的，旧版用同步 try/catch 包住等于没接住失败
       （Promise 里的 reject 不会被外层 catch 捕获）。 */
    copy: function (text, okTitle, okMsg) {
      function ok() {
        toast("ok", okTitle, okMsg);
      }
      function fail() {
        toast("err", "复制失败", "浏览器拒绝了剪贴板访问，请手动选中复制。");
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(ok).catch(fail);
      } else {
        fail();
      }
    },

    /* ---------------- 账号 ---------------- */
    toggleNewUser: function () {
      this.nuOpen = !this.nuOpen;
      if (this.nuOpen) this.nu = { name: "", password: "", role: "viewer" };
    },
    createUser: function () {
      var self = this;
      if (!self.nu.name || !self.nu.password) {
        toast("err", "信息不完整", "用户名与口令都要填。");
        return;
      }
      if (self.nu.password.length < 8) {
        toast("err", "口令太短", "至少 8 位。");
        return;
      }
      self.nuBusy = true;
      api
        .userCreate({
          name: self.nu.name,
          password: self.nu.password,
          role: self.nu.role,
        })
        .then(function () {
          toast("ok", "账号已创建", self.nu.name + "（" + ROLE_ZH[self.nu.role] + "）");
          self.nu = { name: "", password: "", role: "viewer" };
          self.nuOpen = false;
          self.refresh();
        })
        .catch(function (e) {
          toast("err", "创建失败", e.message || String(e));
        })
        .then(function () {
          self.nuBusy = false;
        });
    },
    setRole: function (u, role) {
      var self = this;
      if (role === u.role) return;
      api
        .userUpdate(u.name, { role: role })
        .then(function () {
          toast("ok", "角色已改", u.name + " → " + ROLE_ZH[role]);
          self.refresh();
        })
        .catch(function (e) {
          toast("err", "改角色失败", e.message || String(e));
          self.refresh();
        });
    },
    toggleUser: function (u) {
      var self = this;
      api
        .userUpdate(u.name, { enabled: !u.enabled })
        .then(function () {
          toast("ok", u.enabled ? "已禁用" : "已启用", u.name + " 的现有会话已失效。");
          self.refresh();
        })
        .catch(function (e) {
          toast("err", "操作失败", e.message || String(e));
        });
    },
    startReset: function (u) {
      if (this.resetOf === u.name) {
        this.resetOf = "";
        this.resetPw = "";
        return;
      }
      this.resetOf = u.name;
      this.resetPw = "";
    },
    doReset: function () {
      var self = this;
      if (self.resetPw.length < 8) {
        toast("err", "口令太短", "至少 8 位。");
        return;
      }
      api
        .userUpdate(self.resetOf, { password: self.resetPw })
        .then(function () {
          toast("ok", "口令已重置", self.resetOf + " 需重新登录。");
          self.resetOf = "";
          self.resetPw = "";
        })
        .catch(function (e) {
          toast("err", "重置失败", e.message || String(e));
        });
    },
    askDelete: function (u) {
      var self = this;
      if (self.pendingDel !== u.name) {
        self.pendingDel = u.name;
        setTimeout(function () {
          if (self.pendingDel === u.name) self.pendingDel = "";
        }, 3000);
        return;
      }
      self.pendingDel = "";
      api
        .userDelete(u.name)
        .then(function () {
          toast("ok", "账号已删除", u.name + " 及其全部令牌已失效。");
          self.refresh();
        })
        .catch(function (e) {
          toast("err", "删除失败", e.message || String(e));
        });
    },

    /* ---------------- 令牌 ---------------- */
    toggleNewToken: function () {
      this.ntOpen = !this.ntOpen;
      if (this.ntOpen) {
        /* 权级默认落在角色的上限档（2026-10-26 主人指令：取消「视野随角色」
           这一伪选项，直接给权级）。默认值等价于旧行为 —— 不手动降档时
           令牌的权级就是角色上限。 */
        this.nt = {
          name: "",
          role: "operator",
          clearance: ROLE_CLEARANCE.operator || "reader",
          access: ROLE_ACCESS.operator || "rw",
          expires: "604800",
          max_uses: 0,
        };
      }
    },
    createToken: function () {
      var self = this;
      if (!self.nt.name) {
        toast("err", "请填名称", "名称是为了以后能认出这枚令牌是谁的。");
        return;
      }
      self.ntBusy = true;
      var body = {
        name: self.nt.name,
        role: self.nt.role,
        max_uses: Number(self.nt.max_uses) || 0,
      };
      /* 权级：表单恒有值（默认 = 角色上限），照直带上；服务端仍会校验 ≤ 角色上限 */
      if (self.nt.clearance) body.clearance = self.nt.clearance;
      /* 读写模式：表单恒有值（默认 = 角色默认），照直带上。传 ro 永远合法，
         传 rw 会被服务端按角色上限再拦一次 —— 前端不做安全判断。 */
      if (self.nt.access) body.access = self.nt.access;
      if (self.nt.expires) body.expires_in = Number(self.nt.expires);
      api
        .tokenCreate(body)
        .then(function (d) {
          self.issued = d.token || "";
          self.issuedName = self.nt.name;
          self.nt = {
            name: "",
            role: "operator",
            clearance: ROLE_CLEARANCE.operator || "reader",
            access: ROLE_ACCESS.operator || "rw",
            expires: "604800",
            max_uses: 0,
          };
          self.ntOpen = false;
          self.refresh();
        })
        .catch(function (e) {
          toast("err", "签发失败", e.message || String(e));
        })
        .then(function () {
          self.ntBusy = false;
        });
    },
    /* 重发 = 吊销旧令牌 + 同参数新签一枚。为什么不叫「复制」：
       表里只有 sha256，明文物理上取不回来，假装能复制只会让人以为点错了。 */
    reissue: function (t) {
      var self = this;
      if (self.pendingRe !== t.id) {
        self.pendingRe = t.id;
        setTimeout(function () {
          if (self.pendingRe === t.id) self.pendingRe = "";
        }, 3000);
        return;
      }
      self.pendingRe = "";
      var expiresIn = null;
      if (t.expires_at) {
        var left = Math.floor(Number(t.expires_at) - Date.now() / 1000);
        if (left <= 0) {
          toast("err", "令牌已过期", "请直接签发一枚新令牌。");
          return;
        }
        expiresIn = left;
      }
      api
        .tokenDelete(t.id)
        .then(function () {
          return api.tokenCreate({
            name: t.name,
            role: t.role,
            /* 重发必须原样带上视野：否则自定义档位会静默退回角色默认，
               行为上表现为「重发一次，能看的东西就变多了」—— 属于不该有的
               隐性放宽。旧令牌没有该字段时按角色推导，与服务端同口径。 */
            clearance: t.clearance || ROLE_CLEARANCE[t.role] || "reader",
            /* 读写模式同理必须原样带上：漏了它，一枚「全权只读」令牌重发之后
               会变回可写 —— 那是比视野退回更严重的一类隐性放宽（读写比能看
               多少更接近不可逆），所以这里宁可显式推导也不省略。 */
            access: t.access || ROLE_ACCESS[t.role] || "rw",
            expires_in: expiresIn,
            max_uses: t.max_uses || 0,
          });
        })
        .then(function (d) {
          self.issued = d.token || "";
          self.issuedName = t.name;
          toast("ok", "已重发", "旧令牌立即失效，新明文在上方卡片里。");
          self.refresh();
        })
        .catch(function (e) {
          toast("err", "重发失败", e.message || String(e));
          self.refresh();
        });
    },
    revokeToken: function (t) {
      var self = this;
      if (self.pendingDel !== t.id) {
        self.pendingDel = t.id;
        setTimeout(function () {
          if (self.pendingDel === t.id) self.pendingDel = "";
        }, 3000);
        return;
      }
      self.pendingDel = "";
      api
        .tokenDelete(t.id)
        .then(function () {
          toast("ok", "令牌已吊销", "下一次请求立即 401。");
          self.refresh();
        })
        .catch(function (e) {
          toast("err", "吊销失败", e.message || String(e));
        });
    },
    copyIssued: function () {
      this.copy(this.issued, "令牌已复制", "粘到客户端的 Authorization 头里。");
    },
    copyConn: function () {
      this.copy(this.connUrl, "连接串已复制", "粘到 MCP 客户端的 URL 里。");
    },
    copyHeader: function () {
      this.copy(this.connHeader, "请求头已复制", "粘到 MCP 客户端的自定义 Header。");
    },
    resetBase: function () {
      this.baseUrl = location.origin;
    },

    /* ---------------- 改自己的口令 ---------------- */
    changePw: function () {
      var self = this;
      if (!self.pw.old || !self.pw.n1) {
        toast("err", "信息不完整", "原口令与新口令都要填。");
        return;
      }
      if (self.pw.n1 !== self.pw.n2) {
        toast("err", "两次不一致", "新口令两次输入不同。");
        return;
      }
      if (self.pw.n1.length < 8) {
        toast("err", "口令太短", "至少 8 位。");
        return;
      }
      self.pwBusy = true;
      api
        .passwordChange(self.pw.old, self.pw.n1)
        .then(function () {
          toast("ok", "口令已改", "所有会话已失效，请重新登录。", 6000);
          self.pw = { old: "", n1: "", n2: "" };
          setTimeout(function () {
            location.reload();
          }, 1200);
        })
        .catch(function (e) {
          toast("err", "改口令失败", e.message || String(e));
        })
        .then(function () {
          self.pwBusy = false;
        });
    },
  },
  mounted: function () {
    this.baseUrl = location.origin;
    this.refresh();
    this.loadAudit();
    /* 轮询无条件启动，回调里再守 isAdmin —— 身份是异步到位的（见下方 watch
       的注释），在这里判角色会永久判成 false。 */
    this.startAuditWatch();
  },
  /* 切走本页必须拆定时器与 visibility 监听：hash 路由切页会销毁组件，
     但 setInterval 不会自己停，留着就是「离开这一页还在后台打接口」。 */
  beforeUnmount: function () {
    this.stopAuditWatch();
  },
  template:
    '<div class="page">' +
    /* ---- 工具条：左「账号 / 令牌」分段，右当前身份标签（2026-10-22 主人指令）----
       为什么把身份标签并进这一行：页头大标题删掉后，它独占一整行只为放两个
       chip，纵向白白吃掉约 40px；并进分段控件右侧后，一行既说清「在看哪一类」
       也交代了「我以什么身份在看」，视线不必跨两行。 */
    '  <div class="ac-bar">' +
    '    <div class="ac-seg" role="tablist">' +
    /* 账号分段只对管理员存在（2026-10-25）：不再是「点进去看一句你没权限」，
       而是根本没有这个按钮。 */
    '      <button v-if="isAdmin" role="tab" :aria-selected="activeTab===\'users\'"' +
    '              :class="{on:activeTab===\'users\'}" @click="tab=\'users\'">' +
    "        <span v-html=\"svg('shield')\"></span>账号</button>" +
    '      <button role="tab" :aria-selected="activeTab===\'tokens\'"' +
    '              :class="{on:activeTab===\'tokens\'}" @click="tab=\'tokens\'">' +
    "        <span v-html=\"svg('key')\"></span>令牌</button>" +
    "    </div>" +
    '    <div class="tags ac-who">' +
    '      <span class="tag">{{ S.sessionUser || "—" }}</span>' +
    '      <span class="tag">{{ myRoleZh }}</span>' +
    '      <span class="tag" v-if="S.authVia===\'token\'">令牌通道</span>' +
    "    </div>" +
    "  </div>" +

    /* ---- 双栏骨架：左清单（含全部行内表单）/ 右身份 ---- */
    /* 双栏恒开（2026-10-27 主人选型 A）：右栏从「只对非管理员存在」改为
       「管理员看访问日志、非管理员看我的账号」。原 ac-solo 单栏特例随之取消 ——
       它的存在前提是「管理员右栏无可放」，现在不成立了。 */
    '  <div class="ac-grid">' +
    '    <div class="ac-main">' +

    /* ===== 账号清单（仅管理员渲染）===== */
    '      <div v-if="isAdmin && activeTab===\'users\'" class="ac-col">' +
    '        <x-card title="账号" :sub="users.length + \' 个\'">' +
    '            <div class="list" v-if="users.length">' +
    '              <template v-for="u in users" :key="u.name">' +
    '                <div class="list-item">' +
    '                  <div class="li-main">' +
    '                    <div class="li-title">{{ u.name }}' +
    '                      <span class="pill" v-if="u.name===me">当前</span>' +
    '                      <span class="pill" v-if="!u.enabled">已禁用</span>' +
    "                    </div>" +
    '                    <div class="li-sub">' +
    '                      <span>{{ roleDesc(u.role) }}</span>' +
    '                      <span v-if="u.last_login_at"> · 最后登录 {{ tsZh(u.last_login_at) }}</span>' +
    '                      <span v-if="u.login_count"> · 共 {{ u.login_count }} 次</span>' +
    '                      <span v-else> · 从未登录</span>' +
    "                    </div>" +
    "                  </div>" +
    '                  <div class="li-right ac-acts">' +
    '                    <select class="select" :value="u.role" @change="setRole(u, $event.target.value)"' +
    '                            :disabled="u.name===me" :title="u.name===me ? \'不能改自己的角色\' : \'改角色\'">' +
    '                      <option value="admin">管理员</option>' +
    '                      <option value="operator">操作员</option>' +
    '                      <option value="viewer">只读</option>' +
    "                    </select>" +
    '                    <button class="btn btn-sm" :class="{on:resetOf===u.name}" @click="startReset(u)">改密码</button>' +
    '                    <button class="btn btn-sm" @click="toggleUser(u)" :disabled="u.name===me">' +
    '                      {{ u.enabled ? "禁用" : "启用" }}</button>' +
    '                    <button class="btn btn-sm btn-danger" @click="askDelete(u)" :disabled="u.name===me">' +
    '                      {{ pendingDel===u.name ? "再点确认" : "删除" }}</button>' +
    "                  </div>" +
    "                </div>" +
    /* 改密码：紧贴该行下方展开 */
    '                <div class="ac-inline" v-if="resetOf===u.name">' +
    '                  <div class="ac-inline-head"><b>{{ u.name }} · 改密码</b>' +
    '                    <span class="hint">该账号现有会话立即失效</span></div>' +
    '                  <div class="ac-inline-body">' +
    '                    <input class="input" type="password" v-model="resetPw" placeholder="新口令，至少 8 位"' +
    '                           autocomplete="new-password" @keyup.enter="doReset">' +
    '                    <button class="btn btn-primary" @click="doReset">确定</button>' +
    '                    <button class="btn" @click="resetOf=\'\'; resetPw=\'\'">取消</button>' +
    "                  </div>" +
    "                </div>" +
    "              </template>" +
    "            </div>" +
    '            <div class="hint" v-else>还没有其他账号。</div>' +

    /* 「+」新建账号：清单下面那一条 */
    '            <button class="ac-add" v-if="!nuOpen" @click="toggleNewUser">+ 新建账号</button>' +
    '            <div class="ac-inline" v-if="nuOpen">' +
    '              <div class="ac-inline-head"><b>新建账号</b>' +
    '                <span class="hint">口令以 scrypt 哈希存 users.json</span></div>' +
    '              <div class="ac-inline-body">' +
    '                <input class="input mono" v-model="nu.name" placeholder="用户名"' +
    '                       autocomplete="off" @keyup.enter="createUser">' +
    '                <input class="input" type="password" v-model="nu.password" placeholder="初始口令，至少 8 位"' +
    '                       autocomplete="new-password" @keyup.enter="createUser">' +
    '                <select class="select" v-model="nu.role">' +
    '                  <option value="viewer">只读</option>' +
    '                  <option value="operator">操作员</option>' +
    '                  <option value="admin">管理员</option>' +
    "                </select>" +
    '                <button class="btn btn-primary" @click="createUser" :class="{loading:nuBusy}">创建</button>' +
    '                <button class="btn" @click="toggleNewUser">取消</button>' +
    "              </div>" +
    '              <div class="hint">{{ roleDesc(nu.role) }}</div>' +
    "            </div>" +
    "        </x-card>" +
    "      </div>" +

    /* ===== 令牌清单 ===== */
    '      <div v-if="activeTab===\'tokens\'" class="ac-col">' +
    /* 一次性明文 + 连接串：签发成功后浮到最上方 */
    '        <x-card v-if="issued" title="这串令牌只显示这一次">' +
    '          <div class="hint" style="margin-bottom:10px">' +
    "            「{{ issuedName }}」已签发。关闭后无法再取回 —— 表里只存 sha256，谁都拿不回明文。" +
    "            丢了就用行内「重发」。</div>" +
    '          <div class="ac-conn-row">' +
    '            <input class="input mono" :value="issued" readonly @focus="$event.target.select()">' +
    '            <button class="btn btn-primary" @click="copyIssued">复制令牌</button>' +
    "          </div>" +
    '          <div class="ac-sub">接入 MCP · 主机可改（域名 / IP / 无端口都行）</div>' +
    '          <div class="ac-conn-row">' +
    '            <input class="input mono" v-model="baseUrl" placeholder="http://192.168.0.1:8811">' +
    '            <button class="btn btn-sm" @click="resetBase" title="恢复为当前访问地址">当前</button>' +
    "          </div>" +
    '          <div class="ac-conn" @click="copyConn">{{ connUrl }}</div>' +
    '          <div class="ac-conn-row">' +
    '            <button class="btn btn-sm" @click="copyConn">复制 URL</button>' +
    '            <button class="btn btn-sm" @click="copyHeader">复制 Header</button>' +
    '            <button class="btn btn-sm" @click="issued=\'\'">我已保存</button>' +
    "          </div>" +
    '          <div class="hint mt">URL 里的 <b>?token=</b> 会进访问日志与浏览器历史，内网够用；' +
    "            客户端支持自定义 Header 时优先用 <b>Authorization: Bearer …</b>。</div>" +
    "        </x-card>" +
    '        <x-card :title="selfOnly ? \'我的令牌\' : \'全部令牌\'" :sub="tokens.length + \' 枚\'">' +
    '          <div class="list" v-if="tokens.length">' +
    '            <div class="list-item" v-for="t in tokens" :key="t.id">' +
    '              <div class="li-main">' +
    '                <div class="li-title">{{ t.name }}' +
    '                  <span class="pill">{{ roleZh(t.role) }}</span>' +
    '                  <span class="pill" :title="clearanceDesc(tokenClearance(t))">{{ clearanceZh(tokenClearance(t)) }}</span>' +
    /* 只读令牌必须一眼认出来（2026-10-26）：它决定「这台设备能不能改库」，比
       视野更该显眼。可读写不挂 pill —— 默认态不喧哗，与列表只在非默认档显示
       彩色 pill 是同一取向。 */
    '                  <span class="pill" v-if="tokenAccess(t)===\'ro\'" :title="accessDesc(\'ro\')">只读</span>' +
    '                  <span class="pill" v-if="!t.enabled">已停用</span>' +
    "                </div>" +
    '                <div class="li-sub mono">' +
    "                  {{ t.prefix }}… · {{ t.owner }}" +
    "                  · 到期 {{ expZh(t) }} · 次数 {{ usesText(t) }}" +
    "                </div>" +
    "              </div>" +
    '              <div class="li-right ac-acts">' +
    '                <button class="btn btn-sm" @click="reissue(t)">' +
    '                  {{ pendingRe===t.id ? "再点即重发" : "重发" }}</button>' +
    '                <button class="btn btn-sm btn-danger" @click="revokeToken(t)">' +
    '                  {{ pendingDel===t.id ? "再点确认" : "吊销" }}</button>' +
    "              </div>" +
    "            </div>" +
    "          </div>" +
    '          <div class="hint" v-else>还没有令牌。</div>' +

    /* 「+」签发令牌 */
    '          <button class="ac-add" v-if="!ntOpen && canCreateToken" @click="toggleNewToken">+ 签发令牌</button>' +
    '          <div class="ac-inline" v-if="ntOpen">' +
    '            <div class="ac-inline-head"><b>签发新令牌</b>' +
    '              <span class="hint">明文只在签发后显示一次</span></div>' +
    '            <div class="ac-inline-body">' +
    '              <input class="input" v-model="nt.name" placeholder="名称：谁用、用在哪（如 笔记本-Claude）"' +
    '                     @keyup.enter="createToken">' +
    '              <select class="select" v-model="nt.role">' +
    '                <option v-for="r in roleOptions" :key="r" :value="r">{{ roleZh(r) }}</option>' +
    "              </select>" +
    /* 权级（2026-10-26 主人指令）：直接列权级本身，从高到低排，
       不再放「视野随角色（标准）」这种伪选项 —— 它既与下方首个真选项
       同义，展开时就出现两行一样的字。选项只列 ≤ 角色上限的档，
       默认选中该上限（等价于旧「随角色」），服务端仍会再拦一次。 */
    '              <select class="select" v-model="nt.clearance" title="权级：该令牌能看见哪些密级的记忆">' +
    '                <option v-for="c in clearanceOptions" :key="c" :value="c">{{ clearanceZh(c) }}</option>' +
    "              </select>" +
    /* 读写模式（2026-10-26）：与权级正交的第二个下拉。「全权 + 只读」就是
       「能读完整库、一个字都不许改」，是别的设备最常用的形态。 */
    '              <select class="select" v-model="nt.access" title="读写模式：该令牌能否修改记忆">' +
    '                <option v-for="a in accessOptions" :key="a" :value="a">{{ accessZh(a) }}</option>' +
    "              </select>" +
    '              <select class="select" v-model="nt.expires">' +
    '                <option value="3600">1 小时</option>' +
    '                <option value="86400">1 天</option>' +
    '                <option value="604800">7 天</option>' +
    '                <option value="2592000">30 天</option>' +
    '                <option value="7776000">90 天</option>' +
    '                <option value="">永久（不推荐）</option>' +
    "              </select>" +
    '              <input class="input" type="number" min="0" v-model.number="nt.max_uses"' +
    '                     placeholder="次数，0=不限" style="max-width:120px">' +
    '              <button class="btn btn-primary" @click="createToken" :class="{loading:ntBusy}">签发</button>' +
    '              <button class="btn" @click="toggleNewToken">取消</button>' +
    "            </div>" +
    '            <div class="hint">{{ roleDesc(nt.role) }} · 权级：{{ clearanceDesc(nt.clearance || clearanceCeil) }} · 读写：{{ accessDesc(nt.access || accessDefault) }} · 同一令牌 30 秒内的多个请求只计 1 次</div>' +
    "          </div>" +
    "        </x-card>" +
    "      </div>" +
    "    </div>" +

    /* ===== 右：我的账号（**仅非管理员**，2026-10-22 主人选型 A）=====
       管理员不需要这张卡：他改自己口令走左栏行内「改密码」（不需要原口令），
       身份又已经在工具条右侧标签里写着，留着它就是一张几乎空的卡。
       而 operator / viewer **看不到账号清单**（GET /api/users 是 admin 专属），
       行内「改密码」对他们根本不存在 ⇒ 这张卡是他们唯一的改口令入口，必须留。 */
    /* ac-fill（2026-10-27 主人：「高也是顶满的」）：管理员右栏只有日志一张卡，
       让它撑满可视区高度、列表内部滚动。非管理员的「我的账号」是一张短表单，
       拉满整屏只会得到一大片空白，所以只对 isAdmin 挂这个类。 */
    '    <div class="ac-side" :class="{\'ac-fill\': isAdmin}">' +
    /* ===== 访问日志（仅管理员）=====
       数据面是 audit.jsonl（append-only），接口 /api/audit 也只给 admin ——
       与「账号」分段同一取向：权限不足时这一块**根本不存在**，而不是给一句
       「你没权限」。 */
    '      <x-card v-if="isAdmin" title="访问日志" :sub="auditSub">' +
    "        <template #actions>" +
    /* 导出与刷新并排：导出的是**当前筛选下的全量**，不是这一屏 40 条。
       按钮用 CSV 作默认（绝大多数人要的是「丢进 Excel 看一眼」）；
       JSON 走同一个接口的 format=json，留给脚本，不在 344px 的卡头再挤一个按钮。 */
    '          <button class="btn btn-sm" @click="exportAudit(\'csv\')"' +
    '                  :class="{loading:auditExporting}" title="导出当前筛选下的全部日志（CSV，Excel 可直接打开）">' +
    "            导出</button>" +
    '          <button class="btn btn-sm" @click="loadAudit" :class="{loading:auditBusy}">' +
    "            刷新</button>" +
    "        </template>" +
    '        <div class="ac-audit-kinds" v-if="auditKinds.length">' +
    '          <button class="ac-chip" :class="{on:!auditKind}" @click="setAuditKind(\'\')">' +
    "            全部</button>" +
    '          <button class="ac-chip" v-for="k in auditKinds" :key="k.key"' +
    '                  :class="{on:auditKind===k.key}" @click="setAuditKind(k.key)">' +
    "            {{ k.label }}</button>" +
    "        </div>" +
    /* 首屏骨架：6 行「圆点 + 两段线」，形状与真实条目一致 —— 用灰条而不是
       转圈，是因为它同时告诉眼睛「这里将出现一列什么形状的东西」。
       骨架行复用 .audit-item 的排布，高度对得上，替换时不跳。 */
    '        <div class="audit-list audit-skel" v-if="auditSkel" aria-busy="true">' +
    '          <div class="audit-item" v-for="i in 6" :key="i">' +
    '            <span class="audit-dot skel-dot"></span>' +
    '            <div class="audit-main">' +
    '              <div class="skel line skel-l1"></div>' +
    '              <div class="skel line w40"></div>' +
    "            </div>" +
    "          </div>" +
    "        </div>" +
    /* 已有数据时的刷新：整列降透明度 + 卡头按钮转圈。不换成骨架 ——
       那会把用户正在看的那一行整页抽走。 */
    '        <div class="audit-list" v-else-if="auditRows.length" :class="{stale:auditBusy}">' +
    '          <div class="audit-item" v-for="e in auditRows" :key="e.id">' +
    '            <span class="audit-dot" :class="e.dot" :data-bad="e.bad"></span>' +
    '            <div class="audit-main">' +
    '              <div class="audit-line"><b>{{ e.actor }}</b> {{ e.action }}' +
    '                <code class="audit-target" v-if="e.target">{{ e.target }}</code></div>' +
    '              <div class="audit-sub"><span>{{ e.time }}</span>' +
    '                <span class="audit-ip" :class="{local:e.ipLocal}" v-if="e.ip"' +
    '                      :title="e.ipLocal ? \'本机直连或隧道未带真实来源\' : \'来源 IP\'">' +
    "                  · {{ e.ip }}</span>" +
    '                <span v-if="e.detail"> · {{ e.detail }}</span></div>' +
    "            </div>" +
    "          </div>" +
    "        </div>" +
    '        <x-empty v-else-if="!auditBusy" icon="clock"' +
    '                  :title="auditKind ? \'没有匹配记录\' : \'还没有记录\'"' +
    '                  text="登录、令牌、配置与工具调用都会记在这里。"></x-empty>' +
    /* 采集面边界（2026-10-27 主人要求写明，放在卡底而不是标题旁：
       它是「读日志之前该知道的一条口径」，不是警告，不该抢视线）。
       写清这一句是为了避免日后误判 —— 直连 8700 的调用**不会**出现在
       这里，别把「没记录」当成「没发生」。 */
    '        <div class="audit-foot">只统计经过本控制台的调用' +
    "          （<code>/mcp</code> 反代与 <code>/api/*</code>）；客户端直连 MCP 端口" +
    "          （默认 8700）的请求不在此列。每 8 秒静默同步一次。</div>" +
    "      </x-card>" +
    /* ===== 我的账号（仅非管理员，2026-10-22 主人选型 A 保留）===== */
    '      <x-card v-if="!isAdmin" title="我的账号" :sub="myRoleZh">' +
    "        <template #actions>" +
    '          <button class="btn btn-sm" @click="pwOpen=!pwOpen">' +
    '            {{ pwOpen ? "收起" : "修改口令" }}</button>' +
    "        </template>" +
    '        <div v-if="!pwOpen" class="hint">当前以 <b>{{ S.sessionUser || "—" }}</b> 登录，' +
    "          {{ myRole === 'admin' ? '可管理账号与令牌' : (myRole === 'operator' ? '可签发令牌，不能管人' : '只能调用只读工具') }}。" +
    "        </div>" +
    "        <template v-else>" +
    '          <x-field flat label="原口令">' +
    '            <input class="input" type="password" v-model="pw.old" autocomplete="current-password"></x-field>' +
    '          <x-field flat label="新口令">' +
    '            <input class="input" type="password" v-model="pw.n1" placeholder="至少 8 位"' +
    '                   autocomplete="new-password"></x-field>' +
    '          <x-field flat label="再输一次">' +
    '            <input class="input" type="password" v-model="pw.n2" autocomplete="new-password"' +
    '                   @keyup.enter="changePw"></x-field>' +
    '          <button class="btn btn-primary btn-block mt" @click="changePw" :class="{loading:pwBusy}">' +
    "            确认修改</button>" +
    '          <div class="hint mt">改完所有会话立即失效，需要重新登录。</div>' +
    "        </template>" +
    "      </x-card>" +
    "    </div>" +
    "  </div>" +
    "</div>",

};

export { AccessPage };
