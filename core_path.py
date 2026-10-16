# -*- coding: utf-8 -*-
"""定位 ai-memory 核心模块目录，并把它注入 ``sys.path``。

为什么需要这个模块
------------------
本仓（ai-memory-web）是 Web 控制台的独立仓，只含 **Web 侧**代码：``serve_web.py``
``web_console.py`` 与前端静态资源 ``web/``。

控制台依赖两个**核心模块**：

- ``memory_config`` —— 读写 vault 根的 ``memory.toml``（阈值配置面）
- ``transport_http`` —— MCP HTTP 端点的默认地址常量

二者的唯一事实源在 MCP 仓 ``ai-memory-template``（``server.py`` / ``serve_http.py``
同样依赖它们）。因此本仓**不复制、不派生**这两份代码，而是运行时定位核心目录并
注入 ``sys.path`` —— 这是两个仓之间唯一的耦合点，集中在这里以便审计。

定位顺序（先显式、后推断；任何一步失败都不静默兜底）
----------------------------------------------------
1. ``AI_MEMORY_CORE_DIR`` 环境变量 —— 显式指定。指向的目录里没有
   ``memory_config.py`` 时**直接报错**：配置写错要立刻暴露，不能被回落掩盖。
2. 自动上溯 —— 本仓作为 git submodule 挂在 ``ai-memory-template/web-console/``
   时，上一级就是核心目录。
3. 都失败 ⇒ 抛 ``CoreNotFound``，并附可照抄的修复命令。

命中判据统一为「目录里存在 ``memory_config.py``」。只判断目录是否存在会把空目录、
写错的路径都当成命中，进而让错误推迟到某个无关的 import 上爆发。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: 环境变量名（显式指定核心目录）
CORE_ENV = "AI_MEMORY_CORE_DIR"

#: 命中判据：核心目录里必须存在这个文件
_CORE_MARKER = "memory_config.py"

#: 自动上溯的层数。作为 submodule 挂在 ``<template>/web-console/`` 时上溯 1 层；
#: 留 2 层是为了容忍「多包一层目录」的克隆方式。
_UPWARD_LEVELS = (1, 2)


class CoreNotFound(RuntimeError):
    """无法定位 ai-memory 核心模块目录。"""


def _looks_like_core(path: Path) -> bool:
    return (path / _CORE_MARKER).is_file()


def find_core_dir() -> Path:
    """返回核心模块目录的绝对路径。

    Raises:
        CoreNotFound: 显式指定无效，或既未指定也无法上溯定位。
    """
    raw = (os.environ.get(CORE_ENV) or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if _looks_like_core(p):
            return p.resolve()
        raise CoreNotFound(
            f"{CORE_ENV}={raw!r} 下找不到 {_CORE_MARKER}，显式配置无效。\n"
            f"请把它指向 ai-memory-template 仓库根目录（或任何含核心模块的目录）。")

    here = Path(__file__).resolve().parent
    for level in _UPWARD_LEVELS:
        cand = here
        for _ in range(level):
            cand = cand.parent
        if _looks_like_core(cand):
            return cand

    raise CoreNotFound(
        "找不到 ai-memory 核心模块目录（需含 memory_config.py / transport_http.py）。\n"
        "本仓只含 Web 控制台代码，核心模块的唯一事实源在 MCP 仓 ai-memory-template。\n"
        "请任选其一后重试：\n"
        "  · 把本仓作为 submodule 挂在 ai-memory-template/web-console/ 下"
        "（默认即可自动上溯定位）；\n"
        f"  · 显式指定核心目录：\n"
        f"      Windows : set {CORE_ENV}=D:\\path\\to\\ai-memory-template\n"
        f"      POSIX   : export {CORE_ENV}=/path/to/ai-memory-template")


def ensure_core_on_path() -> Path:
    """把核心目录置于 ``sys.path`` **首位**并返回它。

    幂等：重复调用不会让 ``sys.path`` 长出重复项。置于首位而非追加，是为了让
    核心模块优先于任何同名模块被解析。
    """
    core = find_core_dir()
    s = str(core)
    if s in sys.path:
        sys.path.remove(s)
    sys.path.insert(0, s)
    return core


__all__ = ["CORE_ENV", "CoreNotFound", "find_core_dir", "ensure_core_on_path"]
