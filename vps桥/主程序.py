# -*- coding: utf-8 -*-
"""本机桥：Xray 连 127.0.0.1:41000，代理池和负载在这里改。

  python3 主程序.py
  python3 主程序.py --配置 /etc/xui-bridge/config.json

管理页默认 http://公网IP:41001/ （听 0.0.0.0）。
密码默认 YPN940815...，页面登录或 API 头 X-Pass / Authorization: Bearer。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

根 = Path(__file__).resolve().parent
if str(根) not in sys.path:
    sys.path.insert(0, str(根))


def 用北京时间() -> None:
    """VPS 基本都是 UTC，面板上的时间跟人对不上。外面显式设过 TZ 就听外面的。"""
    if not (os.environ.get("TZ") or "").strip():
        os.environ["TZ"] = "Asia/Shanghai"
    if not hasattr(time, "tzset"):
        return
    time.tzset()
    # 机器上没装时区库的话，Asia/Shanghai 会被当成 UTC，退回不依赖库的写法
    if os.environ["TZ"] == "Asia/Shanghai" and time.timezone != -8 * 3600:
        os.environ["TZ"] = "CST-8"
        time.tzset()


用北京时间()

from 池 import 池
from 更新 import 自动更新循环
from 转发 import 开socks, 验活循环
from 网页 import 开网页

日志 = logging.getLogger("xui桥")


def 默配置径() -> Path:
    环境 = (os.environ.get("XUI_BRIDGE_CONFIG") or "").strip()
    if 环境:
        return Path(环境)
    系统 = Path("/etc/xui-bridge/config.json")
    if 系统.is_file():
        return 系统
    旁 = 根 / "配置.json"
    例 = 根 / "配置.示例.json"
    if not 旁.is_file() and 例.is_file():
        旁.write_text(例.read_text(encoding="utf-8"), encoding="utf-8")
    return 旁


async def 跑(径: Path) -> None:
    池子 = 池(径)
    停 = asyncio.Event()
    socks = await 开socks(池子)
    页 = await 开网页(池子)
    验 = asyncio.create_task(验活循环(池子, 停))
    更 = asyncio.create_task(自动更新循环(池子, 停))
    日志.info("配置 %s ，池内 %s 条", 径, len(池子.条们))
    try:
        await asyncio.gather(socks.serve_forever(), 页.serve_forever())
    finally:
        停.set()
        验.cancel()
        更.cancel()
        socks.close()
        页.close()
        await asyncio.gather(socks.wait_closed(), 页.wait_closed(), return_exceptions=True)


def 主() -> int:
    p = argparse.ArgumentParser(description="X-UI 本机代理桥")
    p.add_argument("--配置", default="", help="config.json 路径")
    a = p.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    径 = Path(a.配置).expanduser() if a.配置 else 默配置径()
    try:
        asyncio.run(跑(径))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(主())
