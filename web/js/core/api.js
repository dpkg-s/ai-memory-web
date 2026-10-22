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
  passwordChange: function (oldPw, newPw) {
    return this.req("/api/password", {
      method: "POST",
      body: { old_password: oldPw, new_password: newPw },
      silent401: true,
    });
  },
};

export { TOKEN_KEY, api };
