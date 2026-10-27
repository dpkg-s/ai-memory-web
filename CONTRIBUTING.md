# Contributing

面向要**改代码、发版本**的人。只想把控制台跑起来，看 [README.md](README.md) 就够了。

---

## 三仓拓扑

```
ai-memory-docker
  └── template/ (submodule) ── dpkg-s/ai-memory-template
        └── web-console/ (submodule) ── dpkg-s/ai-memory-web   ← 本仓
```

本仓是**二级子模块**，同时又被 docker 仓当作源码目录直接 `COPY` 进镜像。

### 发布顺序是硬约束

**ai-memory-template 先 → 本仓后 → ai-memory-docker 跟随。**

本仓的 Release 会从核心仓 `latest` 拉取 `ai-memory-setup.exe` 转挂。反序的后果：发出的
安装器是**上一个版本**的，而文件名不带版本号，下载的人无从发现。

## 改动记录只写本仓

**谁改了东西，就写在谁自己的那个仓里。** 本仓只记录外部端（控制台）的改动，另两端去看它们自己的记录。

| 端 | 仓库 | 谁能写进本仓的文档 |
| --- | --- | --- |
| 核心 | [ai-memory-template](https://github.com/dpkg-s/ai-memory-template) · [CONTRIBUTING](https://github.com/dpkg-s/ai-memory-template/blob/master/CONTRIBUTING.md) | MCP 服务端、索引/检索、测试、安装器 exe —— 归它自己写 |
| **外部端（本仓）** | [ai-memory-web](https://github.com/dpkg-s/ai-memory-web) | 页面、CSS、前端交互、`WEB_VERSION`、`tests/test_web.py` —— 只有这些 |
| 容器端 | [ai-memory-docker](https://github.com/dpkg-s/ai-memory-docker) · [CONTRIBUTING](https://github.com/dpkg-s/ai-memory-docker/blob/master/CONTRIBUTING.md) | Dockerfile / compose / 镜像 tag —— 归它自己写 |

执行细则：

1. `commit message`、`CHANGELOG.md`、`README.md`、PR 正文、Release 正文，**只描述本仓的改动**。
2. **不写**另两端的改动清单、对方的 commit SHA、对方的运行/验证过程、对方的发版动作。
   那些属于对方仓自己那份记录 —— 写在这里就是混写。
3. 必须提到另一端时，**给完整超链接**（仓 / commit / 文件 / Release 的绝对 URL），
   并只写结论（如「需配合核心仓 v3.1.3」），不复述对方实现细节。
4. 一次改动横跨多端 ⇒ 三仓各一笔提交、各写一句，本仓只留本仓那一笔。
5. 本仓**不登记 submodule 指针**：`web-console/` 指针由
   [核心仓](https://github.com/dpkg-s/ai-memory-template/blob/master/CONTRIBUTING.md) 记录，
   故本仓不需要、也不应该写「指针指向哪里」这类仓间拓扑状态。

提交前自查：`git diff --cached` 里出现的仓库名，只能是本仓（超链接除外）。

## 版本号规则

major 位固定不动，**只叠加**：

| 变更 | 位 |
| --- | --- |
| 修 bug / 文档 / CI / 重构 | `+0.0.1` |
| 用户可见的新能力 | `+0.1` |

### 版本源

`web_console.py` 的 `WEB_VERSION` 是本仓**唯一机器可读版本源**。刻意不引入第二个来源
（不建 `VERSION` 文件），避免两处漂移。它曾被漏改两个版本（`1.11.1` vs tag `v1.11.3`），
界面「关于」显示的版本号因此是错的 —— 现在由门禁拦住。

### 一个版本号要同时出现在三处

```
tag 名  ==  web_console.py:WEB_VERSION  ==  CHANGELOG.md 首条
```

三者不一致时 `release.yml` 的 `Verify version consistency` 会在**跑测试之前**判红。

## 发版流程

```bash
# 1. 改三处版本号
#    web_console.py 的 WEB_VERSION
#    CHANGELOG.md 顶部加条目
git commit -am "chore: bump to 1.11.4"
git tag -a v1.11.4 -m "v1.11.4"

# 2. 发布前门禁（只读，退出码 1 = 禁止打 tag）
python ~/.workbuddy/skills/ai-memory-release-flow/scripts/check_release.py \
  --repo web --proxy http://127.0.0.1:7897

# 3. 推送（tag 会触发 release.yml）
git push origin master --follow-tags
```

**前置条件**：核心仓的对应版本必须已经发布。本仓会拉它的 `latest`，核心仓没发就拿到旧安装器。

### Release 正文写什么

**只写使用者能感知的**：升级后看到什么不同、要不要动手、有没有破坏性变更、怎么校验附件。

从 `CHANGELOG.md` 里**筛**，不是复制。禁止出现：仓间归属、子模块指针、commit SHA、
`release.yml` / workflow / CI job、发布顺序、`gh release upload`、构建环境、字节数。

纯内部变更（只动了 CI、只改了测试）照实写「**本版无功能变更**」三行结束。

骨架见 `~/.workbuddy/skills/ai-memory-release-flow/references/release-body-template.md`。

**写在哪里**：存成 `.github/release-notes/<tag>.md`（如 `v1.11.4.md`），`release.yml` 优先取它当正文；
文件不存在才退回 `--generate-notes`。文件名必须与 tag **完全一致、含 `v` 前缀**，大小写敏感。
2026-10-27 起三仓口径统一 —— docker 仓先这么改，core 仓与本仓跟进。

### 附件

| 附件 | 来源 | 命名 |
| --- | --- | --- |
| 源码包 | `git archive` 现场打包（排除 `.github/`、`tests/`） | `web-console-v<X.Y.Z>.tgz` + `.sha256` |
| 安装器 | 从核心仓 `latest` 下载后转挂 | `ai-memory-setup.exe` + `.sha256` |

exe 的 `.sha256` 必须与核心仓那份**一致** —— 是同一个字节，不一致说明核心仓刚发了新版而本仓还在转旧版。

## 开发约定

1. **零构建**：前端没有打包器、没有 npm 依赖、没有产物目录，改完刷新浏览器即生效。
2. **CSS 分片顺序不可变**：CSS 没有 `import` 那样的显式依赖，层叠顺序就是加载顺序，因此
   `web/index.html` 中 8 个 `<link>` 的顺序不可调换、不可改为按需加载。
3. **核心模块不复制、也不 import**：阈值一律经 MCP 工具 `memory_config` 读写；需要新能力时
   **先加 MCP 工具**，而不是在仓内新增一份核心逻辑的副本 —— 那会让两边各自漂移。
4. **分层守卫**：控制台不 import `server`，也不 import 核心仓任何模块；对记忆库的一切读写
   都走 MCP 协议（不直连 vault、不进程内直调）。`tests/test_web.py` 的 C 段把这个钉成了
   断言：导入控制台后 `sys.modules` 里**不得**出现 `memory_config` / `transport_http` /
   `core_path` / `server`。
5. **主题**：`data-theme`（解析值）+ `data-theme-pref`（用户偏好），早于首帧生效以避免闪烁；
   `?theme=light|dark|auto` 可作深链覆盖并写回 `localStorage`。
6. **hash 路由**：`#/dashboard` 等，不依赖服务端路由重写。

第 3、4 条的背景：跨仓 import 意味着「`memory.toml` 怎么读、怎么写、怎么校验」在两侧各有
一份实现，任一侧改动都可能让两边对不上。2026-10-16 收敛后这三件事只有一处实现，本仓只负责
「转成前端契约的 JSON」和「施加本台的只读开关」。

## 本地检查

```bash
python tests/test_web.py     # 脚本式，非 pytest；退出码 0 = 全绿
python tests/test_auth_store.py
python serve_web.py --check  # 只校验配置并打印摘要，不起服务

# lint 只查语法级致命错误（本仓没有自己的 ruff.toml，不跨仓借用配置）
ruff check --select E9,F63,F7,F82 web_console.py serve_web.py tests/
```

## 历史欠账口径

`1.3.0`–`1.7.0` **未单独发布**，内容已并入 `1.8.0` 及之后，逐版记录仍在 `CHANGELOG.md`。

**不补发**：GitHub 不允许修改 `published_at`，补发旧版会让 Releases 页面出现「旧版本比新版本
更晚」的倒挂，比缺版本更误导。早期 Release 没有 `.sha256` 附件同样不追溯。

## 几条容易踩的坑

- **`git add -A` 会用子模块当前 HEAD 覆盖手工登记的 gitlink**：本仓作为 submodule 被核心仓
  引用，动过就回核心仓 `git add web-console`，不要在核心仓 `git add -A`。
- **`AI_MEMORY_WEB_COOKIE_SECURE=1` 在纯 HTTP 下会让登录整个失效** —— 浏览器不存 `Secure`
  Cookie，且症状是「登录成功但立刻又弹登录框」，很容易误判成会话逻辑有 bug。
- **探活打 `/api/session`，不是 `/api/health`** —— 开启登录后后者要 401，容器会被反复判死。
- **静态文件每请求读盘**：改 `web/` 保存即生效；改 `web_console.py` 等 Python 必须重启实例。
