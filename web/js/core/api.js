import { S } from "./store.js";

/* ======================================================================
 * 4. API 客户端
 * ==================================================================== */
var TOKEN_KEY = "am.token";
var api = {
  token: (function () {
    try {
      return sessionStorage.getItem(TOKEN_KEY) || "";
    } catch (e) {
      return "";
    }
  })(),
  setToken: function (t) {
    this.token = String(t || "");
    try {
      if (this.token) sessionStorage.setItem(TOKEN_KEY, this.token);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch (e) {
      /* 忽略 */
    }
  },
  req: function (path, opts) {
    opts = opts || {};
    var headers = { Accept: "application/json" };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    if (this.token) headers["Authorization"] = "Bearer " + this.token;
    return fetch(path, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      cache: "no-store",
      /* 会话是 HTTP-only Cookie，同源请求要显式带上凭据。
         'same-origin' 是 fetch 的默认值，这里写出来是因为它现在**有语义**了：
         以前只有 header 里的 token，cookie 与否无所谓；现在登录态全靠它。 */
      credentials: "same-origin",
    }).then(function (res) {
      return res.text().then(function (txt) {
        var data = null;
        try {
          data = txt ? JSON.parse(txt) : null;
        } catch (e) {
          data = { error: txt.slice(0, 300) };
        }
        if (res.status === 401) {
          /* silent401：登录接口自己的 401 是「口令错」，不是「会话失效」——
             由调用方就地显示，不该再弹一次登录框（弹了会把人困在两层里）。 */
          if (!opts.silent401) S.authRequired = true;
          throw Object.assign(new Error((data && data.error) || "未授权"), {
            status: 401,
            data: data,
          });
        }
        if (!res.ok) {
          throw Object.assign(
            new Error((data && data.error) || "HTTP " + res.status),
            { status: res.status, data: data },
          );
        }
        return data;
      });
    });
  },
  get: function (p) {
    return this.req(p);
  },
  post: function (p, body) {
    return this.req(p, { method: "POST", body: body || {} });
  },
  /* ---- 认证面（2026-10-21）---- */
  session: function () {
    return this.req("/api/session");
  },
  login: function (username, password) {
    return this.req("/api/login", {
      method: "POST",
      body: { username: username, password: password },
      silent401: true,
    });
  },
  logout: function () {
    return this.req("/api/logout", { method: "POST", body: {}, silent401: true });
  },
  /* ---- 管理面（2026-10-22，v1.6.0）----
     用户与令牌。注意 tokenCreate 的返回值里带**明文令牌**，且只此一次 ——
     页面必须当场展示并提示「关掉就取不回了」，不能丢进 log 或再请求一次。 */
  users: function () {
    return this.req("/api/users");
  },
  userCreate: function (body) {
    return this.req("/api/users", { method: "POST", body: body });
  },
  userUpdate: function (name, body) {
    return this.req("/api/users/" + encodeURIComponent(name), { method: "PATCH", body: body });
  },
  userDelete: function (name) {
    return this.req("/api/users/" + encodeURIComponent(name), { method: "DELETE" });
  },
  tokens: function () {
    return this.req("/api/tokens");
  },
  tokenCreate: function (body) {
    return this.req("/api/tokens", { method: "POST", body: body });
  },
  tokenDelete: function (id) {
    return this.req("/api/tokens/" + encodeURIComponent(id), { method: "DELETE" });
  },
  /* 访问日志（2026-10-27）。参数全部可选：limit / kind / actor / since。
     服务端对非 admin 回 403 —— 这里不做前端判断，让权限只有一处事实源。 */
  audit: function (params) {
    var qs = [];
    var p = params || {};
    Object.keys(p).forEach(function (k) {
      if (p[k] !== "" && p[k] !== null && p[k] !== undefined) {
        qs.push(encodeURIComponent(k) + "=" + encodeURIComponent(p[k]));
      }
    });
    return this.req("/api/audit" + (qs.length ? "?" + qs.join("&") : ""));
  },
  /* 导出访问日志（2026-10-27）——**唯一一个不走 req() 的接口**。
     为什么不用 `<a download>` 直接指过去：会话过期时浏览器会把那段 JSON
     错误原样存成 .csv，使用者拿到一个打不开的文件，却看不到「你掉线了」。
     这里先用 fetch 取回正文，成功才转 Blob 下载，失败就能照常弹 toast。
     返回值是 Blob（不是解析后的对象）—— CSV 不是 JSON，req() 的解析会把它
     拆成 {error: "时间,类型,..."}，等于当场毁掉数据。 */
  auditExport: function (params) {
    var qs = [];
    var p = params || {};
    Object.keys(p).forEach(function (k) {
      if (p[k] !== "" && p[k] !== null && p[k] !== undefined) {
        qs.push(encodeURIComponent(k) + "=" + encodeURIComponent(p[k]));
      }
    });
    var headers = {};
    if (this.token) headers.Authorization = "Bearer " + this.token;
    return fetch("/api/audit/export" + (qs.length ? "?" + qs.join("&") : ""), {
      headers: headers,
      credentials: "same-origin",
      cache: "no-store",
    }).then(function (res) {
      if (!res.ok) {
        return res.text().then(function (txt) {
          var msg = "HTTP " + res.status;
          try {
            msg = JSON.parse(txt).error || msg;
          } catch (e) {
            /* 非 JSON 正文：保留状态码，别把 HTML 错误页塞进 toast */
          }
          throw Object.assign(new Error(msg), { status: res.status });
        });
      }
      return res.blob();
    });
  },
  passwordChange: function (oldPw, newPw) {
    return this.req("/api/password", {
      method: "POST",
      body: { old_password: oldPw, new_password: newPw },
      silent401: true,
    });
  },
};

export { TOKEN_KEY, api };
