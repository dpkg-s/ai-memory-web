import { api } from "../core/api.js";
import { S, askConfirm, toast } from "../core/store.js";

/* ======================================================================
 * 8. 配置面
 * ==================================================================== */
function loadThresholds(force) {
  if (S.thresholds.data && !force) return Promise.resolve(S.thresholds.data);
  S.thresholds.loading = true;
  S.thresholds.error = null;
  return api
    .get("/api/thresholds")
    .then(function (d) {
      S.thresholds.data = d;
      S.thresholds.loading = false;
      var draft = {};
      Object.keys(d.keys || {}).forEach(function (k) {
        draft[k] = d.keys[k].value;
      });
      S.thresholds.draft = draft;
      S.thresholds.dirty = false;
      return d;
    })
    .catch(function (e) {
      S.thresholds.loading = false;
      S.thresholds.error = e.message;
      if (e.status !== 401) toast("err", "读取阈值失败", e.message);
    });
}
function saveThresholds() {
  var st = S.thresholds;
  if (!st.data || !st.data.writable) {
    toast(
      "warn",
      "不可写入",
      "阈值当前为只读（未配置 vault 或已关闭写入）。",
    );
    return;
  }
  var values = {};
  Object.keys(st.draft).forEach(function (k) {
    var isInt = st.data.keys[k].type === "int";
    values[k] = isInt ? parseInt(st.draft[k], 10) : parseFloat(st.draft[k]);
  });
  askConfirm(
    "确认写入 memory.toml",
    "将写入 " +
      (st.data.config_path || "memory.toml") +
      "（约 2 秒内生效）。仅写入该配置文件，不会触碰任何 .md 笔记；写入前会自动备份" +
      "为同目录下的 memory.toml.bak.<时间戳>（保留最近 10 份）。",
    "写入",
    function () {
      st.saving = true;
      api
        .post("/api/thresholds", { values: values })
        .then(function (d) {
          st.saving = false;
          st.data = d;
          st.dirty = false;
          var draft = {};
          Object.keys(d.keys || {}).forEach(function (k) {
            draft[k] = d.keys[k].value;
          });
          st.draft = draft;
          /* 写入成功的**行级反馈**（css/6-anim.css §17j ④）：false → true 让
             .row2 的 cfgFlash 动画重新启动（同名 class 常驻不会重播），900ms 后
             回 false，以便下一次保存能再次触发。900ms = 动画本身 620ms + 一个
             身位余量；保存链路前置一个二次确认弹窗 ⇒ 两次保存的间隔必然远大于它。 */
          st.flash = true;
          setTimeout(function () {
            st.flash = false;
          }, 900);
          toast(
            "ok",
            "已写入 memory.toml",
            "备份：" + (d.backup || "（首次创建，无备份）"),
          );
        })
        .catch(function (e) {
          st.saving = false;
          toast("err", "写入失败", e.message);
        });
    },
    false,
  );
}

export { loadThresholds, saveThresholds };
