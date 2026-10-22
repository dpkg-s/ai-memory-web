#!/usr/bin/env python3
"""生成控制台登录用的口令哈希（写进部署侧的 AI_MEMORY_WEB_PASSWORD_HASH）。

用法：
  python make_password.py                # 交互式输入（不回显，推荐）
  python make_password.py "口令"          # 直接给（会留在 shell 历史里）

产出格式 ``scrypt:n:r:p:salt:hash``，直接粘到部署环境变量里：
  AI_MEMORY_WEB_USER=admin
  AI_MEMORY_WEB_PASSWORD_HASH=scrypt:16384:8:1:....

⚠️ 分隔符是**冒号**不是 ``$``：若把 .env 交给 `set -a; . ./.env` 之类的 shell
加载，``scrypt$16384$8$1$...`` 里的 ``$16384`` 会被当成变量引用展开成空串，哈希
当场损坏，而且**只在登录时**才暴露成「口令永远不对」。别手写，让本脚本生成。

为什么不把明文口令写进环境：环境变量会随部署脚本、备份、`docker inspect`
在多处摊开；哈希即使泄露也不能直接登录。若图省事，控制台也接受
``AI_MEMORY_WEB_PASSWORD``（启动时现场哈希），但那是「明文存在盘上」，
安全等级等同于访问令牌 —— 能用哈希就别用明文。

只依赖标准库 + 同目录的 ``web_auth``（scrypt 参数、编码、分隔符都在那里，
本脚本不重复实现，避免两处口径漂移）。
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import web_auth  # noqa: E402


def main() -> int:
    if len(sys.argv) > 1:
        pw = sys.argv[1]
    else:
        pw = getpass.getpass("口令: ")
        again = getpass.getpass("再输一次: ")
        if pw != again:
            print("两次输入不一致。")
            return 2
    if not pw:
        print("口令不能为空。")
        return 2
    if len(pw) < 8:
        print("⚠️  口令短于 8 位。控制台有 5 次 / 5 分钟的登录限流兜底，"
              "但仍建议至少 12 位随机串。")
    h = web_auth.hash_password(pw)
    print()
    print("把下面两行写进部署环境（替换旧值）：")
    print()
    print("AI_MEMORY_WEB_USER=admin")
    print(f"AI_MEMORY_WEB_PASSWORD_HASH={h}")
    print()
    print(f"（哈希长度 {len(h)}，口令不会以任何形式留下）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
