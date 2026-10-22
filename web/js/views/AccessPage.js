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

var AccessPage = {
  data: function () {
    return {
      S: S,
      tab: "users",
      loading: false,
      users: [],
      tokens: [],
      /* 新建账号（行内展开，默认收起） */
      nuOpen: false,
      nu: { name: "", password: "", role: "viewer" },
      nuBusy: false,
      /* 签发令牌（行内展开，默认收起） */
      ntOpen: false,
      nt: { name: "", role: "operator", expires: "604800", max_uses: 0 },
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
    tsZh: function () {
      return function (v) {
        return fmtTs(v);
      };
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
    },
  },
  methods: {
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
        this.nt = { name: "", role: "operator", expires: "604800", max_uses: 0 };
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
      if (self.nt.expires) body.expires_in = Number(self.nt.expires);
      api
        .tokenCreate(body)
        .then(function (d) {
          self.issued = d.token || "";
          self.issuedName = self.nt.name;
          self.nt = { name: "", role: "operator", expires: "604800", max_uses: 0 };
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
  },
  template:
    '<div class="page">' +
    /* ---- 工具条：左「账号 / 令牌」分段，右当前身份标签（2026-10-22 主人指令）----
       为什么把身份标签并进这一行：页头大标题删掉后，它独占一整行只为放两个
       chip，纵向白白吃掉约 40px；并进分段控件右侧后，一行既说清「在看哪一类」
       也交代了「我以什么身份在看」，视线不必跨两行。 */
    '  <div class="ac-bar">' +
    '    <div class="ac-seg" role="tablist">' +
    '      <button role="tab" :aria-selected="tab===\'users\'" :class="{on:tab===\'users\'}" @click="tab=\'users\'">' +
    "        <span v-html=\"svg('shield')\"></span>账号</button>" +
    '      <button role="tab" :aria-selected="tab===\'tokens\'" :class="{on:tab===\'tokens\'}" @click="tab=\'tokens\'">' +
    "        <span v-html=\"svg('key')\"></span>令牌</button>" +
    "    </div>" +
    '    <div class="tags ac-who">' +
    '      <span class="tag">{{ S.sessionUser || "—" }}</span>' +
    '      <span class="tag">{{ myRoleZh }}</span>' +
    '      <span class="tag" v-if="S.authVia===\'token\'">令牌通道</span>' +
    "    </div>" +
    "  </div>" +

    /* ---- 双栏骨架：左清单（含全部行内表单）/ 右身份 ---- */
    '  <div class="ac-grid" :class="{\'ac-solo\': isAdmin}">' +
    '    <div class="ac-main">' +

    /* ===== 账号清单 ===== */
    '      <div v-if="tab===\'users\'" class="ac-col">' +
    '        <x-card v-if="!isAdmin" title="需要管理员权限">' +
    '          <div class="hint">当前账号是 <b>{{ myRoleZh }}</b>，只能管理自己签发的令牌。' +
    "            账号的增删改需要 <b>管理员</b>。</div>" +
    "        </x-card>" +
    "        <template v-else>" +
    '          <x-card title="账号" :sub="users.length + \' 个\'">' +
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
    "          </x-card>" +
    "        </template>" +
    "      </div>" +

    /* ===== 令牌清单 ===== */
    '      <div v-if="tab===\'tokens\'" class="ac-col">' +
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
    '            <div class="hint">{{ roleDesc(nt.role) }} · 同一令牌 30 秒内的多个请求只计 1 次</div>' +
    "          </div>" +
    '          <div class="hint mt" v-if="!canCreateToken">当前账号是 <b>{{ myRoleZh }}</b>，不能签发令牌。请让管理员代办。</div>' +
    "        </x-card>" +
    "      </div>" +
    "    </div>" +

    /* ===== 右：我的账号（**仅非管理员**，2026-10-22 主人选型 A）=====
       管理员不需要这张卡：他改自己口令走左栏行内「改密码」（不需要原口令），
       身份又已经在工具条右侧标签里写着，留着它就是一张几乎空的卡。
       而 operator / viewer **看不到账号清单**（GET /api/users 是 admin 专属），
       行内「改密码」对他们根本不存在 ⇒ 这张卡是他们唯一的改口令入口，必须留。 */
    '    <div class="ac-side" v-if="!isAdmin">' +
    '      <x-card title="我的账号" :sub="myRoleZh">' +
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
