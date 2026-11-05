# -*- coding: utf-8 -*-
"""FNS 同步事件日志的读取面（2026-11-05，「日志」页右栏的数据源）。

数据从哪来
----------
``fns-sync``（Go，容器内）在每次同步动作后往 ``sync-events.jsonl`` 追一行
（见该仓 ``internal/sync/eventlog.go``）。本模块**只读**那个文件：

* 事件文件与 ``state.json`` 同目录（容器里是 ``/state`` 卷）；
* 控制台容器以**只读**方式把同一个卷挂到 ``/fns-state``（compose.yaml），
  本机开发时用 ``AI_MEMORY_WEB_FNS_LOG`` 指到任意路径。

三条刻意的取舍
--------------
1. **只读**：控制台永远不写这个文件 —— 写者是 FNS 客户端，两个写者会让
   「谁是最后一行」变得不可知。文件不存在（FNS 没启用 / 卷没挂）不是错误，
   而是一个**可用性状态**：界面要能说「这里没有数据源」，而不是报错。
2. **坏行跳过**：半行 JSON 不该让整页日志不可用（与 web_audit 同一取向）。
3. **毫秒归一成秒**：Go 侧写 unix 毫秒，而审计流用 unix 秒。时间轴要把两种
   事件排在同一条线上，所以在这里一次性归一，别让前端记两套单位。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

#: 事件文件默认名（与 Go 侧 eventLogPath 的落点一致）。
DEFAULT_LOG_NAME = "sync-events.jsonl"

#: 容器内 FNS state 卷的只读挂载点（compose 里约定，见 compose.yaml）。
CONTAINER_MOUNT = "/fns-state"

#: 动作清单（服务端只做**校验与导出**，界面文案在前端）。
SYNC_ACTIONS: tuple[tuple[str, str], ...] = (
    ("upload", "上传"),
    ("download", "下载"),
    ("modify", "修改"),
    ("delete", "删除"),
    ("rename", "重命名"),
)

#: 对象类型清单。
SYNC_KINDS: tuple[tuple[str, str], ...] = (
    ("note", "笔记"),
    ("file", "附件"),
    ("setting", "配置"),
    ("folder", "目录"),
)

_ACTION_KEYS = frozenset(k for k, _ in SYNC_ACTIONS)
_KIND_KEYS = frozenset(k for k, _ in SYNC_KINDS)


def resolve_sync_log_path(cfg_dir: Path) -> Path:
    """事件文件的最终路径。

    优先级：``AI_MEMORY_WEB_FNS_LOG`` > 容器挂载点 > 配置目录旁边的同名文件。

    为什么留「配置目录旁边」这一档：本机开发实例（8890）没有容器卷可挂，
    要把 FNS 的事件文件放哪都行 —— 给一条可预期的默认路径，测试与本地手测
    都能直接指向临时目录，不必真起 FNS。
    """
    raw = (os.environ.get("AI_MEMORY_WEB_FNS_LOG") or "").strip()
    if raw:
        return Path(raw)
    mounted = Path(CONTAINER_MOUNT) / DEFAULT_LOG_NAME
    if mounted.is_file():
        return mounted
    return Path(cfg_dir) / DEFAULT_LOG_NAME


class SyncEventLog:
    """FNS 事件文件的只读视图（无锁：写者是另一个进程，读方只吃不改）。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    # -- 读 -----------------------------------------------------------------
    def available(self) -> bool:
        try:
            return self.path.is_file()
        except OSError:
            return False

    def status(self) -> dict:
        """给界面的一句话状态：能用？文件在哪？为什么读不到？"""
        try:
            exists = self.path.is_file()
        except OSError as e:                                  # noqa: BLE001
            return {"available": False, "path": str(self.path),
                    "error": str(e)}
        if not exists:
            return {"available": False, "path": str(self.path), "error": ""}
        try:
            size = self.path.stat().st_size
        except OSError as e:                                  # noqa: BLE001
            return {"available": True, "path": str(self.path),
                    "size": 0, "error": str(e)}
        # 空文件是**已就绪但还没有事件**，与「没有数据源」必须区分开：
        # 前者说明 FNS 已经接好了，只是这段时间没同步过东西。
        return {"available": True, "path": str(self.path), "size": size,
                "error": ""}

    def _read_all(self) -> list[dict]:
        if not self.available():
            return []
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        out: list[dict] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                out.append(_normalize(rec))
        return out

    def _slice(self, *, action: str = "", kind: str = "",
               since: float | None = None) -> list[dict]:
        rows = self._read_all()
        if action:
            rows = [r for r in rows if str(r.get("action") or "") == action]
        if kind:
            rows = [r for r in rows if str(r.get("kind") or "") == kind]
        if since is not None:
            rows = [r for r in rows if float(r.get("t") or 0) >= since]
        return rows

    def tail(self, *, limit: int = 60, action: str = "", kind: str = "",
             since: float | None = None) -> list[dict]:
        """最近 ``limit`` 条（新→旧）。过滤在切片之前，理由同 web_audit.tail。"""
        rows = self._slice(action=action, kind=kind, since=since)
        rows.reverse()
        try:
            limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            limit = 60
        return rows[:limit]

    def dump(self, *, action: str = "", kind: str = "",
             since: float | None = None) -> list[dict]:
        """导出用：命中项全量、按时间正序（旧→新）。"""
        return self._slice(action=action, kind=kind, since=since)

    def stats(self) -> dict:
        rows = self._read_all()
        by_action: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for r in rows:
            a = str(r.get("action") or "other")
            k = str(r.get("kind") or "other")
            by_action[a] = by_action.get(a, 0) + 1
            by_kind[k] = by_kind.get(k, 0) + 1
        return {"total": len(rows), "by_action": by_action, "by_kind": by_kind,
                "oldest": rows[0].get("t") if rows else None,
                "newest": rows[-1].get("t") if rows else None}


def _normalize(rec: dict) -> dict:
    """把一行 Go 事件整成界面/导出都能直接用的形态。

    * ``t``：unix 毫秒 → unix 秒（**审计流用秒**，两条流要在同一条时间轴上排队）；
    * ``action`` / ``kind``：限定在已知枚举内，未知值原样保留但不冒充已知；
    * ``title``：缺失时由 ``path`` 现推 —— 老事件（写 title 之前）也能点开笔记。
    """
    out: dict[str, Any] = {"source": "fns"}
    raw_t = rec.get("t")
    try:
        t = float(raw_t)
    except (TypeError, ValueError):
        t = 0.0
    # 阈值 1e11 秒 ≈ 西历 5000 年，任何毫秒时间戳都远大于它 —— 用它区分
    # 「毫秒」与「秒」不会误判，也不必给事件加单位字段。
    if t > 1e11:
        t = t / 1000.0
    out["t"] = round(t, 3)
    kind = str(rec.get("kind") or "")
    action = str(rec.get("action") or "")
    out["kind"] = kind if kind in _KIND_KEYS else (kind or "other")
    out["action"] = action if action in _ACTION_KEYS else (action or "other")
    path = str(rec.get("path") or "")
    out["path"] = path
    title = str(rec.get("title") or "")
    out["title"] = title or path_to_title(path)
    try:
        out["size"] = int(rec.get("size") or 0)
    except (TypeError, ValueError):
        out["size"] = 0
    out["detail"] = str(rec.get("detail") or "")
    return out


def path_to_title(path: str) -> str:
    """vault 相对路径 → 条目标题（文件 stem）。

    与核心仓的落点规则对齐：frontmatter 只存叶子名，目录由路径表达，
    所以 stem 就是 ``memory_read(title=…)`` 能打开的那个名字。
    """
    p = str(path or "").replace("\\", "/").strip()
    if not p:
        return ""
    base = p.rsplit("/", 1)[-1]
    if base.lower().endswith(".md"):
        base = base[:-3]
    return base


def action_labels() -> list[dict]:
    return [{"key": k, "label": v} for k, v in SYNC_ACTIONS]


def kind_labels() -> list[dict]:
    return [{"key": k, "label": v} for k, v in SYNC_KINDS]


def fmt_ts(t: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(float(t or 0)))
    except (OSError, ValueError, OverflowError):
        return ""


__all__ = [
    "DEFAULT_LOG_NAME", "CONTAINER_MOUNT", "SYNC_ACTIONS", "SYNC_KINDS",
    "SyncEventLog", "resolve_sync_log_path", "path_to_title",
    "action_labels", "kind_labels", "fmt_ts",
]
