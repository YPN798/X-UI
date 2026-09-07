# -*- coding: utf-8 -*-
"""业务节点：自己管 VMess、Xray 分流和本机代理池。不依赖 X-UI。

  python3 主程序.py
  python3 主程序.py --配置 /etc/dola-node/config.json
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

根 = Path(__file__).resolve().parent
if str(根) not in sys.path:
    sys.path.insert(0, str(根))

from 池 import 池
from 监督xray import 监督xray
from 网页 import 开网页
from 转发 import 开socks, 验活循环

日志 = logging.getLogger("xui桥")


def 默配置径() -> Path:
    环境 = (os.environ.get("DOLA_NODE_CONFIG") or "").strip()
    if 环境:
        return Path(环境)
    系统 = Path("/etc/dola-node/config.json")
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
    xray径 = Path("/etc/dola-node/xray.json") if Path("/etc/dola-node").is_dir() else 径.with_name("xray.json")
    监督 = 监督xray(池子, xray径)
    socks = await 开socks(池子)
    页 = await 开网页(池子, 监督)
    验 = asyncio.create_task(验活循环(池子, 停))
    核 = asyncio.create_task(监督.守护(停))
    日志.info("配置 %s ，池内 %s 条，节点口 %s", 径, len(池子.条们), 池子.设.get("node_port"))
    try:
        await asyncio.gather(socks.serve_forever(), 页.serve_forever())
    finally:
        停.set()
        验.cancel()
        核.cancel()
        socks.close()
        页.close()
        await 监督.停()
        await asyncio.gather(socks.wait_closed(), 页.wait_closed(), return_exceptions=True)


def 主() -> int:
    p = argparse.ArgumentParser(description="业务节点（VMess + 本机桥）")
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
