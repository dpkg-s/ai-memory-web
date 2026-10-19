import { api } from "../core/api.js";
import { S, askConfirm, toast } from "../core/store.js";

/* ======================================================================
 * 9. 更新面（2026-10-15 建立；2026-10-16 扩为**双目标**）
 *
 * 「更新」= 从 git 远端把**白名单内**的文件取到当前工作区。两个目标分属两仓、
 * 两目录，各查各的、各更各的：
 *   web  —— 本仓（dpkg-s/ai-memory-web）：后端两件 + web/ 前端
 *   core —— 核心仓（dpkg-s/ai-memory-template）：MCP 运行时模块 + 依赖声明
 *
 * 四个**不在前端**做决定的点：
 *   ① 白名单 —— 由服务端给出（web_console.UPDATE_WEB_PATHS / CORE_PROGRAM_FILES）。
 *      前端不维护第二份清单，否则每加一个模块就要改两处。
 *   ② 目标定位 —— 核心目录由服务端 `core_root()` 解析
 *      （AI_MEMORY_CORE_DIR → 本目录父目录 → ~/.workbuddy/mcp-servers/ai-memory），
 *      前端只显示结果与失败原因。
 *   ③ 行尾转换 —— git 自己按 .gitattributes / core.autocrlf 写文件；前端与
 *      后端都不碰内容，只传递路径。
 *   ④ 重启时序 —— 控制台会在响应之后自退，由助手接手「停 → 起」。
 *      因此请求被切断属**预期路径**，不能当成失败。
 * ==================================================================== */

/* 界面顺序（服务端也按此序返回，这里只用于合并时的稳定排序）。 */
var ORDER = ["web", "core"];

function targetOf(key) {
  var list = S.update.targets || [];
  for (var i = 0; i < list.length; i++) {
    if (list[i].target === key) return list[i];
  }
  return null;
}

/* 单目标请求只回一项 ⇒ **就地替换那一项**。整包覆盖会让另一张卡瞬空，
   看起来像「另一个目标消失了」。

   ⚠️ 只有联网 `?fetch=1` 才有的远端结论字段：本地状态 payload（`?fetch=0`）
   **一律不含**它们 —— 若直接覆盖，用户从「关于」页返回、或点「只读本地」时，
   远端版本会从 `v1.1.0  94e0521` 退回「（未检查）」，看起来像读不到（2026-10-19
   主人报的就是这个观感）。所以这里按字段做**降级保护**：本地字段取新的，
   远端结论留着。 */
var REMOTE_KEYS = [
  "checked",
  "fetched",
  "ref",
  "remote_sha",
  "remote_short",
  "remote_version",
  "ahead",
  "behind",
  "changed",
  "changed_count",
  "can_apply",
  "blocked_reason",
];

function mergeTargets(list) {
  var u = S.update;
  if (!list || !list.length) return;
  var prev = {};
  (u.targets || []).forEach(function (t) {
    prev[t.target] = t;
  });
  var incoming = {};
  var merged = list.map(function (t) {
    incoming[t.target] = true;
    var p = prev[t.target];
    if (p && t.checked === false && p.checked === true) {
      var keep = {};
      REMOTE_KEYS.forEach(function (k) {
        if (k in p) keep[k] = p[k];
      });
      return Object.assign({}, t, keep);
    }
    return t;
  });
  var kept = (u.targets || []).filter(function (t) {
    return !incoming[t.target];
  });
  u.targets = kept.concat(merged).sort(function (a, b) {
    return ORDER.indexOf(a.target) - ORDER.indexOf(b.target);
  });
}

/* 单个目标「有更新」的判据 —— 只认服务端给的 behind / changed_count。
   前端不拿「版本号不同」当判据：本地领先远端时两边版本号也不同，会误报。 */
function pendingOf(d) {
  d = d || {};
  return !!(d.behind > 0 || d.changed_count > 0);
}

/* 有更新的目标数量（导航圆点用）。 */
function pendingCount() {
  return (S.update.targets || []).filter(function (t) {
    return t.available !== false && pendingOf(t);
  }).length;
}

/* 旧契约归一化（版本错配兜底）：
   只更新了前端、后端仍是被更新前的进程时，`/api/update` 回的是 2026-10-16 之前
   的**扁平**结构（无 targets）⇒ 这里把它折成单目标，页面不至于整片空白。
   这不是异常状态而是**受支持的状态**：前端静态资源保存即生效，只有后端模块
   变化才需要重启（`restart_required` 就是这个判据）。 */
function normalize(d) {
  if (d && d.targets && d.targets.length) return d.targets;
  if (d && (d.root !== undefined || d.is_repo !== undefined)) {
    return [
      Object.assign(
        {
          target: "web",
          target_name: "Web 控制台",
          available: true,
          checked: d.checked !== false,
        },
        d,
      ),
    ];
  }
  return [];
}

/* withFetch=false ⇒ 只读本地状态（进页面时用，不联网跑 git fetch）。
   key 省略 ⇒ 同时刷新全部目标。
   quiet=true ⇒ 失败不弹条（自动检测用，网络抖一下就报错太吵）。 */
function loadUpdate(withFetch, key, quiet) {
  var u = S.update;
  u.loading = true;
  u.error = null;
  var q = withFetch === false ? "?fetch=0" : "";
  if (key) q = (q ? q + "&" : "?") + "target=" + encodeURIComponent(key);
  return api
    .get("/api/update" + q)
    .then(function (d) {
      u.loading = false;
      var list = normalize(d);
      mergeTargets(list);
      /* 后端把「git 拉取失败」表达成 200 + ok:false + error/stderr，
         因为它同时还要把本地状态带回来。这里不要把它当请求失败。 */
      if (!list.length && d && d.error) u.error = d.error;
      return d;
    })
    .catch(function (e) {
      u.loading = false;
      u.error = e.message;
      if (!quiet && e.status !== 401) toast("err", "读取更新状态失败", e.message);
    });
}

/* 进 web 时自动检测更新（2026-10-19 主人令：「每次进 web 时自动检测更新，
   有就提示有更新」）。三条约束：
   ① **不阻塞首屏** —— fire-and-forget，失败静默（网络抖一下就弹红条太吵），
      真实原因仍可在「关于」页看到；
   ② **同一次页面会话只跑一次**（`autoStarted` 闸门）—— mounted 调一次；
      `watchReconnect` 之后刷的是本地状态（fetch=0），不会重复联网；
   ③ 结果不另存 —— 合并进 `S.update.targets`，关于页两张卡与导航圆点共用同一份。
   ⚠️ 判据只看服务端的 `behind / changed_count`，不看版本号差异。 */
function autoCheckUpdates() {
  var u = S.update;
  if (u.autoStarted) return Promise.resolve(null);
  u.autoStarted = true;
  if (S.authRequired) return Promise.resolve(null);
  return loadUpdate(true, "", true).then(function (d) {
    if (!d) return null;
    var pend = (u.targets || []).filter(function (t) {
      return t.available !== false && pendingOf(t);
    });
    if (!pend.length) return d;
    var names = pend.map(function (t) {
      var v = t.remote_version ? "v" + t.remote_version : t.remote_short || "";
      return (t.target_name || t.target) + (v ? " " + v : "");
    });
    /* warn 而不是 ok：它是「该做点什么」的提示，不是操作结果。9 秒够看清，
       圆点会一直留在侧栏「配置」上，不会漏。 */
    toast(
      "warn",
      "发现可用更新",
      names.join("、") + "。到「配置 → 关于」可查看差异并更新。",
      9000,
    );
    return d;
  });
}

function applyUpdate(key, force) {
  var u = S.update;
  var d = targetOf(key) || {};
  var name = d.target_name || key;
  var body = [
    "将把「" + name + "」白名单内的 " + (d.changed_count || 0) + " 个文件覆盖为远端版本。",
    "程序目录：" + (d.root || "?"),
    "目标提交：" + (d.remote_short || "?") +
      (d.remote_version ? "（v" + d.remote_version + "）" : ""),
    "覆盖前会逐个备份到该目录下的 " + (d.backup_dir || ".ai-memory-backup"),
  ];
  if (force && (d.conflicts || []).length) {
    body.push("");
    body.push("⚠ 强制覆盖会丢弃 " + d.conflicts.length + " 个文件的本地未提交改动。");
  }
  askConfirm(
    "确认执行更新 · " + name,
    body.join("\n"),
    force ? "强制更新" : "更新",
    function () {
      u.applying[key] = true;
      api
        .post("/api/update", {
          target: key,
          force: !!force,
          ref: d.ref || "",
          expected_sha: d.remote_sha || "",
        })
        .then(function (r) {
          u.applying[key] = false;
          u.result[key] = r;
          if (r.up_to_date) {
            toast("ok", "已是最新", r.message || "未改动任何文件。");
          } else {
            toast(
              "ok",
              name + "：已更新 " + (r.written || []).length + " 个文件",
              r.restart_required
                ? "后端模块已变化，需重启服务才能生效。"
                : "前端刷新即生效。",
            );
          }
          loadUpdate(false, key);
        })
        .catch(function (e) {
          /* 业务失败走 409，详情在 e.data（后端把 conflicts 等一并带回来）。 */
          u.applying[key] = false;
          var p = e.data || {};
          u.result[key] = p;
          toast("err", name + "：更新未完成", p.error || e.message);
          loadUpdate(false, key);
        });
    },
    force,
  );
}

/* 重启是**全局**的（launcher 的 restart 会同时停/起 8700 与 8811），
   因此不像「执行更新」那样按目标区分 —— 界面上只放一颗按钮。 */
function restartBackend() {
  var u = S.update;
  askConfirm(
    "重启服务",
    "将重启 MCP 上游（8700）与 Web 控制台（8811）。本页面会断开数秒，随后自动重连。",
    "重启",
    function () {
      u.restarting = true;
      api
        .post("/api/update/restart", {})
        .then(function (d) {
          if (!d.ok) {
            u.restarting = false;
            toast("err", "无法重启", d.error || "");
            return;
          }
          toast("ok", "正在重启", "约 " + Math.round(d.delay || 3) + " 秒后自动重连…");
          watchReconnect(Math.round(d.delay || 3) + 3);
        })
        .catch(function (e) {
          var p = e.data || {};
          if (p.ok === false) {
            /* 真失败（未找到重启助手 / 解释器不可用）—— 控制台还活着。 */
            u.restarting = false;
            toast("err", "无法重启", p.error || e.message);
            return;
          }
          /* 连接被切断 ⇒ 控制台已在自退，属预期路径。 */
          toast("ok", "正在重启", "页面将在数秒后自动重连…");
          watchReconnect(6);
        });
    },
    false,
  );
}

/* 轮询 /api/health 直到后端回来。1 秒一格，前两秒不打扰（肯定还没起来）。 */
function watchReconnect(seconds) {
  var u = S.update;
  u.reconnecting = true;
  u.seconds = Math.max(1, seconds);
  var tries = 0;
  var timer = setInterval(function () {
    tries += 1;
    u.seconds = Math.max(0, u.seconds - 1);
    if (tries < 3) return;
    api
      .get("/api/health")
      .then(function (d) {
        if (!d || !d.ok) return;
        clearInterval(timer);
        u.reconnecting = false;
        u.restarting = false;
        u.result = {};
        toast("ok", "服务已恢复", "连接正常（延迟 " + d.latency_ms + " ms）。");
        loadUpdate(false);
      })
      .catch(function () {
        /* 还没起来，继续等下一次。 */
      });
  }, 1000);
}

export {
  loadUpdate,
  applyUpdate,
  restartBackend,
  watchReconnect,
  targetOf,
  pendingCount,
  autoCheckUpdates,
};
