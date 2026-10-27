# -*- coding: utf-8 -*-
"""访问审计日志（2026-10-27，「访问日志」卡片的数据面）。

回答三个问题：**谁、什么时候、干了什么**。所以一条记录的字段是刻意收窄的：
``t`` + ``actor`` + ``kind``/``action``/``target``，其余（role / ip / ok / detail）
都是帮助判断的旁证。

为什么要单独一个模块而不是复用 logging
--------------------------------------
``logging`` 的产物是**给人 grep 的文本**：格式随 handler 变、字段靠正则切、
编码受控制台代码页影响（本机是 GBK，2026-10-27 已踩过一次）。而卡片要按人、
按类型、按时间**筛**，文本日志做不了这件事 —— 要么前端正则，要么后端二次解析，
两条路都会在「字段多一个空格」时静默错位。所以这里落 **JSONL**：一行一条，
追加即持久，读时 ``json.loads`` 直得结构。

三条硬约束
----------
1. **append-only**：只追加，不修改历史行。审计日志被编辑过就不再是审计日志。
2. **不落凭据**：``_SECRET_KEYS`` 里的键在入库前直接丢弃 —— 调用方传错也只是
   丢字段，不会把令牌明文 / 口令写进一个「给人看」的文件。
3. **有界**：超过 ``max_bytes`` 就压缩到最近 ``keep_entries`` 条。无限增长的文件
   迟早会把磁盘和「读最近 40 条」的延迟一起拖垮。

为什么用「大小阈值 + 全量重写」而不是「按天分文件」：本场景日增量是几十条量级，
分天会制造一堆小文件反而更难查；2 MB 对几十条/天意味着数周到数月的窗口，够用。
真到了需要按天归档的量级，再换成 ``audit-YYYYMMDD.jsonl`` 一行改动即可。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable

#: 入库前必须丢掉的键（键名小写匹配）。审计文件是「给人看」的，
#: 任何凭据类字段都不该出现在里面 —— 这里做成硬过滤而不是靠调用方自觉。
_SECRET_KEYS = frozenset({
    "token", "password", "old_password", "new_password", "secret",
    "authorization", "cookie", "hash", "code", "code_verifier",
})

#: 单条事件里 ``detail`` 的长度上限：审计要的是「能认出来」，不是全文留档。
_DETAIL_MAX = 240


class AuditLog:
    """一条有界、追加式、可筛选的审计流。"""

    def __init__(self, path: Path | str, *, max_bytes: int = 2 * 1024 * 1024,
                 keep_entries: int = 1500) -> None:
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        self.keep_entries = int(keep_entries)
        self._lock = threading.Lock()

    # -- 写 -----------------------------------------------------------------
    def append(self, event: dict[str, Any]) -> None:
        """追加一条。缺 ``t`` 时补当前时间；密钥类字段一律丢掉。"""
        rec = {k: v for k, v in event.items()
               if str(k).lower() not in _SECRET_KEYS}
        rec.setdefault("t", round(time.time(), 3))
        if not rec.get("actor"):
            rec["actor"] = "anonymous"
        detail = rec.get("detail")
        if isinstance(detail, str) and len(detail) > _DETAIL_MAX:
            rec["detail"] = detail[:_DETAIL_MAX] + "…"
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
            try:
                too_big = self.path.stat().st_size > self.max_bytes
            except OSError:
                too_big = False
            if too_big:
                self._compact()

    def _compact(self) -> None:
        """压缩到最近 ``keep_entries`` 条。调用方须已持锁。"""
        rows = self._read_all()[-self.keep_entries:]
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent),
                                  prefix=self.path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False,
                                        separators=(",", ":")) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -- 读 -----------------------------------------------------------------
    def _read_all(self) -> list[dict]:
        """整文件读成记录列表。坏行**跳过而不是整段失败** —— 一条被磁盘写坏的
        行不该让「看日志」这件事本身变成不可用。"""
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
                out.append(rec)
        return out

    def _slice(self, *, kind: str = "", actor: str = "", action: str = "",
               since: float | None = None) -> list[dict]:
        """按维度筛出命中项，**保持文件里的原顺序（旧→新）**。

        筛选逻辑只此一份：``tail()``（界面看最近 N 条）与 ``dump()``（导出全量）
        若各写一套，两边迟早对同一条记录给出不同答案 —— 而「界面上看得到、
        导出来却没有」是最难排查的一类问题。
        """
        rows = self._read_all()
        if kind:
            rows = [r for r in rows if str(r.get("kind") or "") == kind]
        if actor:
            rows = [r for r in rows if str(r.get("actor") or "") == actor]
        if action:
            rows = [r for r in rows if str(r.get("action") or "").startswith(action)]
        if since is not None:
            rows = [r for r in rows if float(r.get("t") or 0) >= since]
        return rows

    def tail(self, *, limit: int = 40, kind: str = "", actor: str = "",
             action: str = "", since: float | None = None) -> list[dict]:
        """最近 ``limit`` 条（**新→旧**），可按类型 / 人 / 动作前缀 / 起始时间筛。

        过滤放在切片**之前**：先切后筛会得到「最近 40 条里命中的少数几条」，
        与「命中项里最近 40 条」是两种语义，后者才符合「我要找某人的动作」。
        """
        rows = self._slice(kind=kind, actor=actor, action=action, since=since)
        rows.reverse()
        try:
            limit = max(1, min(int(limit), 500))
        except (TypeError, ValueError):
            limit = 40
        return rows[:limit]

    def dump(self, *, kind: str = "", actor: str = "", action: str = "",
             since: float | None = None) -> list[dict]:
        """导出用：命中项**全量**、按时间**正序**（旧→新）返回。

        这里刻意不套 ``tail()`` 的 500 条上限 —— 导出的意义就是「把整段历史
        带走」，截断会让使用者以为日志只有这么点。真正的上限是文件本身：
        ``append()`` 超过 ``max_bytes`` 会压到 ``keep_entries`` 条，所以这里
        最坏也就几千行，内存无压力。

        正序而非倒序：导出的产物通常是拿去按时间线读或喂给别的工具，倒序的
        CSV 在 Excel 里要手动反一遍。
        """
        return self._slice(kind=kind, actor=actor, action=action, since=since)

    def stats(self) -> dict:
        rows = self._read_all()
        by_kind: dict[str, int] = {}
        for r in rows:
            k = str(r.get("kind") or "other")
            by_kind[k] = by_kind.get(k, 0) + 1
        return {"total": len(rows), "by_kind": by_kind,
                "oldest": rows[0].get("t") if rows else None,
                "newest": rows[-1].get("t") if rows else None}


#: 卡片筛选用的类型清单（唯一事实源：前端也从 /api/audit 的 ``kinds`` 取）。
AUDIT_KINDS: tuple[tuple[str, str], ...] = (
    ("auth", "身份"),
    ("token", "令牌"),
    ("account", "账号"),
    ("config", "配置"),
    ("tool", "工具"),
    ("access", "拒绝"),
)


def kind_labels() -> list[dict]:
    return [{"key": k, "label": v} for k, v in AUDIT_KINDS]


def describe_events(rows: Iterable[dict]) -> list[str]:
    """把若干事件压成「谁 什么时候 干了什么」的可读行（调试/CLI 用）。"""
    out = []
    for r in rows:
        out.append(f"{time.strftime('%m-%d %H:%M', time.localtime(float(r.get('t') or 0)))} "
                   f"{r.get('actor')} {r.get('action')} {r.get('target') or ''}".strip())
    return out


__all__ = ["AuditLog", "AUDIT_KINDS", "kind_labels", "describe_events"]
