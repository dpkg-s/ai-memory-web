"""前端「按角色裁剪入口」的结构与逻辑校验（2026-10-26 建立）。

背景
----
主人连着提了三条界面收口要求：只读账号不许进「访问控制」、配置页里能改的项
要按角色隐藏、随后又发现「调试台」对只读仍然是敞开的那一个。三次都是同一个
毛病 —— 入口散落在四处（侧栏 nav、快捷键、命令面板、hash 深链），改一处漏三处。

因此本轮把判据收成一份表（``web/js/core/router.js#PAGE_ROLES``），本测试负责
在**不启浏览器**的前提下守住三件事：

1. 表格判据本身对三种角色给出预期结果（逻辑层，走真实的 computed）；
2. 模板里凡是受限页面/页签，都必须挂在带 ``canSee(...)`` / ``canEdit`` 的条件链上
   （结构层，用 HTMLParser 按**祖先链**判断，而不是数「附近多少字符」——
   字符串距离判据在嵌套卡片里必然误报）；
3. 命令面板这个第二入口同样被裁剪（它是 ``go()`` 的另一条路）。

依赖 node：用 node 求值 ESM 模块里的组件对象，取 ``template`` / ``computed``。
缺 node 时整例跳过（不判红）—— CI 里没有 node 不该算前端写错了。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_BASE = os.path.join(WEB, "web", "js")

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

# node 求值脚本。注意两点：
#   · 用 ``with (proxy)`` 兜住被剥掉的 import —— 组件模块只取 template /
#     computed，不跑生命周期，所以任何外部标识符给个空实现就够；
#   · ``pageAllowed`` 必须用 router.js 里的**真实**实现，不能在测试里复制一份
#     表 —— 复制出来的判据与被测对象各说各话，正是这轮要消灭的问题。
PROBE_JS = r"""
import fs from "fs";
const base = process.env.WEBJS_BASE;

const known = {
  watch() {},
  nextTick() {},
  document: { querySelector: () => null, body: { style: {} }, addEventListener() {} },
  window: { addEventListener() {}, innerWidth: 1440, scrollTo() {} },
  S: { health: {}, tools: [], theme: "dark", palette: {}, role: "", settingsTab: "conn" },
};
const stub = new Proxy(known, {
  has: () => true,
  get: (t, k) => (k in t ? t[k] : function () {}),
});

function load(file, ret) {
  let s = fs.readFileSync(base + file, "utf8");
  s = s.replace(/^import[\s\S]*?;[ \t]*$/gm, "");
  s = s.replace(/^export\s*\{[\s\S]*?\};?[ \t]*$/gm, "");
  const body = "with (__stub) {\n" + s + "\n; return (" + ret + ");\n}";
  return new Function("__stub", body)(stub);
}

const router = load("core/router.js", "({ PAGE_ROLES, pageAllowed })");
known.pageAllowed = router.pageAllowed;

const Root = load("views/Root.js", "Root");
const SP = load("views/SettingsPage.js", "SettingsPage");
const CP = load("components/CommandPalette.js", "CommandPalette");

const S = known.S;
const out = { templates: {}, roles: {}, settings: {}, palette: {} };
out.templates.Root = Root.template;
out.templates.SettingsPage = SP.template;
out.templates.CommandPalette = CP.template;

function navOf(role) {
  S.role = role;
  const visiblePages = Root.computed.visiblePages.call({});
  const nav = Root.computed.nav.call({ visiblePages });
  return {
    visible: visiblePages,
    navIds: nav.map((n) => n.id),
    canSee: Object.fromEntries(
      ["dashboard", "console", "library", "access", "settings"].map((id) => [
        id,
        Root.methods.canSee.call({ visiblePages }, id),
      ]),
    ),
  };
}
for (const role of ["", "admin", "operator", "viewer"]) out.roles[role || "(空)"] = navOf(role);

function settingsOf(canEdit) {
  return {
    tabs: SP.computed.tabs.call({ canEdit }).map((t) => t.id),
    tabConn: (S.settingsTab = "conn", SP.computed.tab.call({ canEdit })),
    tabFns: (S.settingsTab = "fns", SP.computed.tab.call({ canEdit })),
    tabTh: (S.settingsTab = "th", SP.computed.tab.call({ canEdit })),
  };
}
out.settings.admin = settingsOf(true);
out.settings.viewer = settingsOf(false);

function paletteOf(role) {
  S.role = role;
  S.tools = [{ name: "memory_read", description: "read" }];
  const all = CP.computed.all.call({});
  return all.map((i) => i.key);
}
out.palette.admin = paletteOf("admin");
out.palette.viewer = paletteOf("viewer");

process.stdout.write(JSON.stringify(out));
"""


class _Stack(HTMLParser):
    """维护 (标签, 属性) 栈，供按祖先链判断条件覆盖。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict]] = []
        self.hits: list[tuple[str, dict, list[tuple[str, dict]]]] = []
        self.broken: list[str] = []
        self.both_if_for: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        self.hits.append((tag, a, list(self.stack)))
        if ("v-if" in a or "v-else-if" in a) and "v-for" in a:
            self.both_if_for.append(tag)
        if tag not in VOID_TAGS:
            self.stack.append((tag, a))

    def handle_startendtag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        self.hits.append((tag, a, list(self.stack)))

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        # 弹到最近的同名开始标签；找不到就记一笔不闭合
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return
        self.broken.append(tag)


def _parse(tpl: str) -> _Stack:
    p = _Stack()
    p.feed(tpl)
    p.close()
    return p


def _chain_has(chain, needle: str) -> bool:
    for _tag, a in chain:
        for k in ("v-if", "v-else-if"):
            if needle in a.get(k, ""):
                return True
    return False


def _run_probe() -> dict:
    node = shutil.which("node") or shutil.which("node.exe")
    if not node:
        for cand in (r"D:\nodejs\node.exe", r"C:\Program Files\nodejs\node.exe"):
            if os.path.exists(cand):
                node = cand
                break
    if not node:
        print("SKIP: 未找到 node，跳过前端结构与逻辑校验。")
        raise SystemExit(0)

    tmp = tempfile.mkdtemp(prefix="tpl_probe_")
    js = os.path.join(tmp, "probe.mjs")
    with open(js, "w", encoding="utf-8") as f:
        f.write(PROBE_JS)
    env = dict(os.environ, WEBJS_BASE=JS_BASE + os.sep)
    r = subprocess.run([node, js], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print("FAIL: node 求值组件失败\n" + (r.stderr or ""))
        raise SystemExit(1)
    return json.loads(r.stdout)


def main() -> int:
    data = _run_probe()
    fails: list[str] = []

    def ck(cond, msg):
        if not cond:
            fails.append(msg)

    # ---------- 逻辑层：PAGE_ROLES 的判定结果 ----------
    roles = data["roles"]
    ck(roles["(空)"]["navIds"] == ["dashboard", "console", "library", "access", "settings"],
       "角色为空时不该裁剪任何入口（首帧会误藏管理员入口）")
    ck(roles["admin"]["navIds"] == ["dashboard", "console", "library", "access", "settings"],
       "admin 应看到全部入口")
    ck(roles["operator"]["navIds"] == ["dashboard", "console", "library", "access", "settings"],
       "operator 应看到全部入口（含调试台与访问控制）")
    ck(roles["viewer"]["navIds"] == ["dashboard", "library", "settings"],
       f"viewer 只能看到 概览/记忆库/配置，实际 {roles['viewer']['navIds']}")
    ck(roles["viewer"]["canSee"]["console"] is False, "viewer 不应能进调试台")
    ck(roles["viewer"]["canSee"]["access"] is False, "viewer 不应能进访问控制")
    ck(roles["viewer"]["canSee"]["library"] is True, "viewer 应能进记忆库")

    # ---------- 逻辑层：配置页 FNS 页签 ----------
    sa, sv = data["settings"]["admin"], data["settings"]["viewer"]
    ck("fns" in sa["tabs"], "admin 应看到 FNS 同步页签")
    ck("fns" not in sv["tabs"], f"非管理员不应看到 FNS 同步页签，实际 {sv['tabs']}")
    ck(sa["tabFns"] == "fns", "admin 深链 ?tab=fns 应落到 FNS 页签")
    ck(sv["tabFns"] == "conn", "非管理员深链 ?tab=fns 应回落到连接页")
    ck(sv["tabTh"] == "th", "非管理员仍应能看运行时阈值页")

    # ---------- 逻辑层：命令面板（第二入口） ----------
    pa, pv = data["palette"]["admin"], data["palette"]["viewer"]
    ck("page:console" in pa and "page:access" in pa, "admin 的命令面板应含全部页面")
    ck("page:console" not in pv, "viewer 的命令面板不应出现调试台")
    ck("page:access" not in pv, "viewer 的命令面板不应出现访问控制")
    ck(not [k for k in pv if k.startswith("tool:")],
       f"viewer 的命令面板不应出现工具候选，实际 {pv}")
    ck([k for k in pa if k.startswith("tool:")], "admin 的命令面板应含工具候选")

    # ---------- 结构层：模板条件链 ----------
    root = _parse(data["templates"]["Root"])
    ck(not root.stack, f"Root 模板有未闭合标签：{[t for t, _ in root.stack]}")
    ck(not root.broken, f"Root 模板有孤儿闭标签：{root.broken}")
    ck(not root.both_if_for, f"Root 模板同一元素混用 v-if 与 v-for：{root.both_if_for}")
    for tag in ("console-page", "access-page"):
        el = [h for h in root.hits if h[0] == tag]
        ck(bool(el), f"Root 模板找不到 <{tag}>")
        if el:
            e_tag, e_attr, chain = el[0]
            own = e_attr.get("v-else-if", "") + e_attr.get("v-if", "")
            ck("canSee(" in own,
               f"<{tag}> 的渲染条件应自带 canSee(...)，实际 {own!r}")

    sp = _parse(data["templates"]["SettingsPage"])
    ck(not sp.stack, f"SettingsPage 模板有未闭合标签：{[t for t, _ in sp.stack]}")
    ck(not sp.broken, f"SettingsPage 模板有孤儿闭标签：{sp.broken}")
    ck(not sp.both_if_for, f"SettingsPage 模板同一元素混用 v-if 与 v-for：{sp.both_if_for}")
    fns_cards = [h for h in sp.hits if "FNS 同步" in h[1].get("title", "")]
    ck(bool(fns_cards), "SettingsPage 模板找不到「FNS 同步」卡片")
    for tag, a, chain in fns_cards:
        ck(_chain_has(chain + [(tag, a)], "canEdit"),
           "「FNS 同步」卡片必须挂在 canEdit 条件链下（非管理员不应看到）")

    # ---------- 结构层：命令面板页面候选受 pageAllowed 约束 ----------
    cp_src = open(os.path.join(JS_BASE, "components", "CommandPalette.js"), encoding="utf-8").read()
    ck("pageAllowed(S.role, p.id)" in cp_src,
       "命令面板的页面候选必须过 pageAllowed（否则等于给侧栏开了个旁门）")
    ck('pageAllowed(S.role, "console")' in cp_src,
       "命令面板的工具候选必须受调试台可见性约束")

    if fails:
        print("FAIL: 前端角色裁剪校验未通过")
        for f in fails:
            print("  - " + f)
        return 1
    print("PASS: 前端角色裁剪校验（逻辑 16 项 / 结构 12 项）全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
